#!/usr/bin/env python3
"""ANR FG addon preparation only. Never execute upstream installers or DLLs."""
import hashlib
import io
import fcntl
import stat
import tempfile
import json
import base64
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import zipfile


class Refusal(RuntimeError):
    """Unsafe or ambiguous installation; leave the game alone."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def setting_lines(data):
    if b'\x00' in data or len(data) > 4 * 1024 * 1024:
        raise Refusal('unsupported INI encoding or size')
    lines = data.splitlines(keepends=True)
    section = b''
    sections = set()
    found = {}
    for index, line in enumerate(lines):
        header = re.match(rb'^\s*\[([^]]+)\]', line.removeprefix(b'\xef\xbb\xbf'))
        if header:
            section = header[1].strip().lower()
            if section in (b'framegen', b'libraries') and section in sections:
                raise Refusal('duplicate configuration section')
            sections.add(section)
        key = re.match(rb'^\s*([^;#=\s]+)\s*=(.*?)[\r\n]*$', line)
        if key:
            pair = (section, key[1].lower())
            if pair in found and pair in ((b'framegen', b'fginput'), (b'framegen', b'fgnvngxreplacement'), (b'libraries', b'optidllpath')):
                raise Refusal('duplicate configuration key')
            found[pair] = (index, key[2].strip())
    return lines, found


def configure(data):
    bom = b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''
    body = data[len(bom):]
    newline = b'\r\n' if b'\r\n' in body else b'\n'
    for key, value in ((b'FGInput', b'nvngxfg'), (b'FGNvngxReplacement', b'Apex Neural Rendering FG')):
        lines, found = setting_lines(body)
        pair = (b'framegen', key.lower())
        if pair in found:
            index = found[pair][0]
            ending = newline if lines[index].endswith(b'\n') else b''
            lines[index] = key + b'=' + value + ending
        else:
            start, end = None, len(lines)
            for index, line in enumerate(lines):
                header = re.match(rb'^\s*\[([^]]+)\]', line)
                if header:
                    if start is not None:
                        end = index
                        break
                    if header[1].strip().lower() == b'framegen':
                        start = index
            if start is None:
                if lines and not lines[-1].endswith(b'\n'):
                    lines[-1] += newline
                lines.append(b'[FrameGen]' + newline)
                end = len(lines)
            elif end and not lines[end - 1].endswith(b'\n'):
                lines[end - 1] += newline
            lines.insert(end, key + b'=' + value + newline)
        body = b''.join(lines)
    return bom + body


def restore_config(current, original):
    installed = configure(original)
    if current == installed:
        return original
    lines, found = setting_lines(current)
    old_lines, old_found = setting_lines(original)
    managed_lines, managed_found = setting_lines(installed)
    for key in (b'fginput', b'fgnvngxreplacement'):
        pair = (b'framegen', key)
        if pair in found and lines[found[pair][0]] == managed_lines[managed_found[pair][0]]:
            lines[found[pair][0]] = old_lines[old_found[pair][0]] if pair in old_found else b''
    if not re.search(rb'^\s*\[framegen\]', original.removeprefix(b'\xef\xbb\xbf'), re.I | re.M):
        for index, line in enumerate(lines):
            if re.match(rb'^\s*\[framegen\]', line, re.I):
                end = index + 1
                while end < len(lines) and not re.match(rb'^\s*\[', lines[end]):
                    end += 1
                if not b''.join(lines[index + 1:end]).strip():
                    lines[index:end] = []
                break
    restored = b''.join(lines)
    if not original.endswith(b'\n') and restored.endswith(b'\n'):
        # A delimiter inserted before our appended section is ours only when
        # the remaining last line matches the original last line exactly.
        old_last = original.splitlines()[-1:] or [b'']
        if restored.splitlines()[-1:] == old_last:
            restored = restored.removesuffix(b'\r\n') if restored.endswith(b'\r\n') else restored[:-1]
    return restored


def safe_path(root, relative=''):
    """Windows case-aware containment without resolving controlled symlinks."""
    root = Path(root)
    current = root
    for part in Path(relative).parts:
        if part in ('.', '..') or '/' in part or '\\' in part or ':' in part or part.endswith((' ', '.')):
            raise Refusal('unsafe relative path')
        if current.exists():
            matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()]
            if len(matches) > 1:
                raise Refusal('case collision')
            current = matches[0] if matches else current / part
        else:
            current = current / part
        if current.is_symlink():
            raise Refusal('symlink target')
    if current.is_symlink():
        raise Refusal('symlink target')
    return current


def private_dir(home, relative):
    current = home
    for part in Path(relative).parts:
        current = safe_path(current, part)
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        stat = current.stat()
        if not current.is_dir() or stat.st_uid != os.getuid() or stat.st_mode & 0o022:
            raise Refusal('unsafe user cache directory')
    if current.stat().st_mode & 0o077:
        raise Refusal('state cache must be private')
    return current


def scan(root):
    for path in (root, *root.parents):
        if path.is_symlink():
            raise Refusal('symlink game path')
    if not root.is_dir():
        raise Refusal('game directory missing')
    anchors = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        names = dirs + files
        if len({name.casefold() for name in names}) != len(names):
            raise Refusal('case collision in game tree')
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                raise Refusal('symlink in game tree')
            if name.casefold() == 'optiscaler.ini' and path.is_file():
                anchors.append(path)
    if len(anchors) != 1:
        raise Refusal('need exactly one OptiScaler.ini')
    return anchors[0]


def library_root(root, ini):
    _, settings = setting_lines(ini.read_bytes())
    value = settings.get((b'libraries', b'optidllpath'), (0, b'auto'))[1].decode('utf-8')
    if not value or value.casefold() == 'auto':
        selected = safe_path(ini.parent, 'OptiScaler')
    else:
        value = value.replace('\\', '/')
        if value[:3].casefold() == 'z:/':
            value = value[2:]
        if ':' in value or '..' in value.split('/'):
            raise Refusal('unsupported or traversing OptiDllPath')
        if value.startswith('/'):
            parts = Path(value).parts
            base = root.parts
            if [s.casefold() for s in parts[:len(base)]] != [s.casefold() for s in base]:
                raise Refusal('OptiDllPath outside game')
            selected = safe_path(root, Path(*parts[len(base):]))
        else:
            selected = safe_path(ini.parent, value)
    return selected if selected.is_dir() else ini.parent


def encoded(data):
    return None if data is None else base64.b64encode(data).decode('ascii')


def decoded(data):
    return None if data is None else base64.b64decode(data, validate=True)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data, mode=0o600):
    """Publish synced bytes with exact ordinary permission bits, even at umask 077."""
    fd, temporary = tempfile.mkstemp(prefix='.anr-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode & 0o777)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_bytes(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Refusal('unsafe file type')
    return path.read_bytes() if path.exists() else None


class Engine:
    def __init__(self, home, manifest, fetch=None):
        self.home = Path(home).resolve(strict=True)
        self.manifest = manifest
        self.fetch = fetch or self.download
        self.cache = private_dir(self.home, '.dlor/cache/anr-framegen')

    def download(self, desc):
        fd, temporary = tempfile.mkstemp(prefix='.download-', dir=self.cache)
        os.close(fd)
        child = None
        try:
            child = subprocess.Popen(['curl', '-fL', '--silent', '--show-error', '--connect-timeout', '15',
                                      '--max-time', '180', '--max-filesize', str(desc['size']),
                                      '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '5',
                                      '--tlsv1.2', '-o', temporary, desc['url']],
                                     stdin=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            if child.wait(timeout=190) != 0:
                raise Refusal('addon download failed')
            with open(temporary, 'rb') as stream:
                return stream.read(desc['size'] + 1)
        finally:
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            os.unlink(temporary)


    def payload(self):
        desc = self.manifest['downloads']['addon']
        archive_path = safe_path(self.cache, desc['sha256'] + '.zip')
        data = file_bytes(archive_path) or b''
        if len(data) != desc['size'] or digest(data) != desc['sha256']:
            data = self.fetch(desc)
            if len(data) != desc['size'] or digest(data) != desc['sha256']:
                raise Refusal('addon checksum mismatch')
            atomic(archive_path, data)
        result = {}
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            seen = set()
            total = 0
            for info in archive.infolist():
                parts = info.filename.rstrip('/').split('/')
                mode = info.external_attr >> 16
                if (any(not part or part in ('.', '..') or ':' in part or '\\' in part or part.endswith((' ', '.')) for part in parts)
                        or info.filename.casefold() in seen or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or mode & 0o7000 or info.flag_bits & 1):
                    raise Refusal('unsafe archive member')
                seen.add(info.filename.casefold())
                total += info.file_size
                if total > 32 * 1024 * 1024:
                    raise Refusal('archive expanded-size limit')
            for name, item in desc['members'].items():
                if archive.getinfo(name).file_size != item['size']:
                    raise Refusal('archive member size mismatch')
                content = archive.read(name)
                if len(content) != item['size'] or digest(content) != item['sha256']:
                    raise Refusal('archive member checksum mismatch')
                result[item['path']] = content
        return result

    def applied(self, index):
        """Post-write observation boundary (overridden by interruption tests)."""

    def validate_state(self, root, state):
        if not isinstance(state, dict) or state.get('schema') != 1 or state.get('root') != str(root):
            raise Refusal('invalid ownership journal')
        ini = safe_path(root, state['ini'])
        dest = safe_path(root, state['dest'])
        if ini != scan(root) or dest.name.casefold() != 'apex neural rendering fg' or dest.parent.name.casefold() != 'custom':
            raise Refusal('ownership policy anchor mismatch')
        descriptor = self.manifest['downloads']['addon']
        expected = {item['path']: item['sha256'] for item in descriptor['members'].values()}
        if state['files'] != expected or state['provenance'] != descriptor:
            raise Refusal('ownership policy provenance mismatch')
        configure(decoded(state['original']))
        for relative in state['directories']:
            path = safe_path(root, relative)
            if path != dest.parent and path != dest and dest not in path.parents:
                raise Refusal('ownership policy directory mismatch')
        return ini, dest

    def replay(self, root, state_path, pending_path, plan):
        if plan.get('schema') != 1 or plan.get('root') != str(root) or plan.get('policy') != 'anr-fg-two-keys-v1':
            raise Refusal('invalid pending transaction policy')
        ini, dest = self.validate_state(root, plan['context'])
        action = plan['action']
        if action not in ('install', 'uninstall') or plan['prune'] != (plan['context']['directories'] if action == 'uninstall' else []):
            raise Refusal('pending transaction policy mismatch')
        if plan['state'] != (plan['context'] if action == 'install' else None):
            raise Refusal('pending state policy mismatch')
        allowed = {safe_path(dest, name): expected for name, expected in plan['context']['files'].items()}
        operations = []
        seen = set()
        for operation in plan['operations']:
            path = safe_path(root, operation['path'])
            current = file_bytes(path)
            before, after = decoded(operation['before']), decoded(operation['after'])
            if path in seen:
                raise Refusal('duplicate pending operation policy')
            seen.add(path)
            if path == ini:
                expected = configure(before) if action == 'install' else restore_config(before, decoded(plan['context']['original']))
                if after != expected:
                    raise Refusal('pending INI write violates two-key policy')
            elif path not in allowed or (action == 'install' and (before is not None or after is None or digest(after) != allowed[path])) or (action == 'uninstall' and (after is not None or before is None or digest(before) != allowed[path])):
                raise Refusal('pending file write violates addon-only policy')
            before_mode = operation.get('before_mode')
            if before is not None and (type(before_mode) is not int or not 0 <= before_mode <= 0o7777):
                raise Refusal('pending transaction lacks valid permission policy')
            if path != ini:
                if (before is not None and before_mode != 0o644) or (after is not None and operation['mode'] != 0o644):
                    raise Refusal('pending payload permission policy mismatch')
                current_mode = stat.S_IMODE(path.stat().st_mode) if current is not None else None
                if (current, current_mode) not in ((before, before_mode), (after, operation['mode'] if after is not None else None)):
                    raise Refusal('foreign edit conflicts with pending transaction')
            if current not in (before, after):
                raise Refusal('foreign edit conflicts with pending transaction')
            operations.append((operation, path, current, after))
        # Preflight every operation before changing anything. Never blindly replay.
        for index, (operation, path, current, after) in enumerate(operations):
            path = safe_path(root, operation['path'])
            current = file_bytes(path)
            current_mode = stat.S_IMODE(path.stat().st_mode) if current is not None else None
            if path != ini and (current, current_mode) not in (
                    (decoded(operation['before']), operation['before_mode']),
                    (after, operation['mode'] if after is not None else None)):
                raise Refusal('foreign edit occurred after transaction preflight')
            if current not in (decoded(operation['before']), after):
                raise Refusal('foreign edit occurred after transaction preflight')
            if current != after:
                if after is None:
                    path.unlink()
                    sync_dir(path.parent)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Setting-only replacement retains a chmod made since planning.
                    mode = operation['mode']
                    if path == ini:
                        assert current_mode is not None
                        mode = current_mode
                    atomic(path, after, mode)
                self.applied(index)
        for relative in sorted(plan['prune'], key=lambda p: len(Path(p).parts), reverse=True):
            path = safe_path(root, relative)
            if path.is_dir():
                try:
                    path.rmdir()
                    sync_dir(path.parent)
                except OSError as error:
                    if error.errno not in (39, 17):  # ENOTEMPTY/EEXIST preserve user additions
                        raise
        atomic(state_path, json.dumps(plan['state'], sort_keys=True).encode())
        pending_path.unlink()
        sync_dir(pending_path.parent)

    def run(self, action, root):
        if action not in ('install', 'uninstall'):
            raise Refusal('invalid action')
        # Steam's selected installation may be reached through library aliases.
        # Canonicalize only this trusted root, before discovery/lock/journal keys;
        # paths discovered beneath it still use symlink-rejecting validation.
        root = Path(root).resolve(strict=True)
        ini = scan(root)
        key = digest(os.fsencode(root))
        state_path = safe_path(self.cache, key + '.json')
        pending_path = safe_path(self.cache, key + '.pending.json')
        lock_path = safe_path(self.cache, key + '.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            scan(root)
            raw = file_bytes(pending_path)
            if raw is not None:
                self.replay(root, state_path, pending_path, json.loads(raw))
            raw = file_bytes(state_path)
            state = json.loads(raw) if raw is not None else None
            if state:
                _, dest = self.validate_state(root, state)
                if action == 'install' and library_root(root, ini) != dest.parent.parent:
                    raise Refusal('OptiDllPath changed while addon is owned')
            else:
                if action == 'uninstall':
                    print('ANR FG: no owned addon; nothing to remove')
                    return
                dest = safe_path(library_root(root, ini), 'custom/Apex Neural Rendering FG')
                if dest.exists():
                    raise Refusal('foreign addon directory')
            operations = []
            def change(path, after, mode=0o644):
                before = file_bytes(path)
                if before != after:
                    operations.append({'path': str(path.relative_to(root)), 'before': encoded(before),
                                       'before_mode': stat.S_IMODE(path.stat().st_mode) if before is not None else None,
                                       'after': encoded(after), 'mode': mode})
            if action == 'uninstall':
                assert state is not None
                current = ini.read_bytes()
                restored = restore_config(current, decoded(state['original']))
                change(ini, restored, stat.S_IMODE(ini.stat().st_mode))
                for name, expected in state['files'].items():
                    path = safe_path(dest, name)
                    content = file_bytes(path)
                    if content is not None and digest(content) == expected and stat.S_IMODE(path.stat().st_mode) == 0o644:
                        change(path, None)
                    elif content is not None:
                        print('ANR FG: retaining modified owned file:', repr(str(path.relative_to(root))))
                prune = state['directories']
                after_state = None
            else:
                payload = self.payload()
                for name, content in payload.items():
                    path = safe_path(dest, name)
                    if file_bytes(path) is None:
                        change(path, content)
                if state is None:
                    directories = set()
                    for operation in operations:
                        path = safe_path(root, operation['path']).parent
                        while path != root and not path.exists():
                            directories.add(str(path.relative_to(root)))
                            path = path.parent
                    state = {'schema': 1, 'root': str(root), 'ini': str(ini.relative_to(root)),
                             'dest': str(dest.relative_to(root)), 'original': encoded(ini.read_bytes()),
                             'files': {name: digest(content) for name, content in payload.items()},
                             'directories': sorted(directories),
                             'provenance': self.manifest['downloads']['addon']}
                    change(ini, configure(ini.read_bytes()), stat.S_IMODE(ini.stat().st_mode))
                after_state, prune = state, []
            plan = {'schema': 1, 'root': str(root), 'operations': operations,
                    'policy': 'anr-fg-two-keys-v1', 'action': action, 'context': state,
                    'prune': prune, 'state': after_state}
            atomic(pending_path, json.dumps(plan, sort_keys=True).encode())
            self.replay(root, state_path, pending_path, plan)
            print('ANR FG:', action, 'complete')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('install', 'uninstall'):
        raise Refusal('usage: loader.py install|uninstall GAME_DIRECTORY')
    raw = Path(os.environ['DLOR_ANR_MANIFEST']).read_bytes()
    expected = os.environ['DLOR_ANR_MANIFEST_SHA256']
    if not re.fullmatch(r'[a-f0-9]{64}', expected) or digest(raw) != expected:
        raise Refusal('manifest authentication failed')
    manifest = json.loads(raw)
    if manifest.get('schema') != 1 or digest(Path(__file__).read_bytes()) != manifest['runtime']['loader.py']:
        raise Refusal('runtime authentication failed')
    Engine(os.environ['HOME'], manifest).run(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    def interrupted(number, _frame):
        raise SystemExit(128 + number)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        main()
    except Exception as error:
        print('ANR FG preparation failed; game runner may continue:', type(error).__name__, str(error), file=sys.stderr)
        sys.exit(1)
