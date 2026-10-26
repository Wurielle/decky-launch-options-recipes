#!/usr/bin/env python3
"""Acquire and compile SHA-verified OptiScaler runtime modules."""
import hashlib, importlib.abc, importlib.util, json, os, pathlib, re, signal, stat, subprocess, sys, tempfile

active_child = None

def cancel_auxiliary(signum, frame):
    # Each bounded auxiliary command has its own process group. Never signal the
    # game/Steam process group, and reap children before removing handoff files.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if active_child is not None:
        try:
            os.killpg(active_child.pid, signum)
        except ProcessLookupError:
            pass
    # Do not call Popen.wait from a signal handler: a signal can interrupt
    # communicate while its non-reentrant waitpid lock is held. Reap on unwind.
    raise SystemExit(128 + signum)

signal.signal(signal.SIGINT, cancel_auxiliary)
signal.signal(signal.SIGTERM, cancel_auxiliary)

def run_auxiliary(command):
    global active_child
    active_child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
    try:
        active_child.communicate()
        if active_child.returncode:
            raise subprocess.CalledProcessError(active_child.returncode, command)
    except BaseException:
        try:
            active_child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(active_child.pid, signal.SIGKILL)
            active_child.wait()
        raise
    finally:
        active_child = None

def private_directory(path):
    path = pathlib.Path(path)
    for part in [*reversed(path.parents), path]:
        if not part.exists() and not part.is_symlink():
            try: part.mkdir(mode=0o700)
            except FileExistsError: pass
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('unsafe cache directory: ' + str(part))
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('source cache must be private and user owned: ' + str(path))
    return path

def source_context():
    revision = os.environ.get('DLOR_OPTISCALER_SOURCE_REVISION', os.environ.get('DLOR_SCRIPT_REVISION', ''))
    repository = os.environ.get('DLOR_OPTISCALER_SOURCE_REPOSITORY', os.environ.get('DLOR_REPOSITORY', 'Wurielle/decky-launch-options-recipes'))
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('invalid DLOR_SCRIPT_REVISION: expected a full lowercase Git commit')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repository):
        raise ValueError('invalid DLOR_REPOSITORY')
    cache = private_directory(pathlib.Path.home().resolve(strict=True) / '.dlor/cache/dlor-optiscaler/source' / revision)
    base = 'https://raw.githubusercontent.com/' + repository + '/' + revision + '/recipes/dlor-optiscaler/scripts/'
    return cache, base

def verified_file(cache, base, name, digest):
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('invalid source digest for ' + name)
    path = cache / name
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('unsafe source cache file: ' + str(path))
    if path.is_file():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == digest:
            return data
        print('Source cache checksum mismatch; fetching ' + name, file=sys.stderr)
    fd, temporary = tempfile.mkstemp(prefix='.' + name + '.', dir=cache)
    os.close(fd)
    try:
        run_auxiliary(['curl', '-fL', '--silent', '--show-error', '--connect-timeout', '15',
                       '--max-time', '180', '--proto', '=https', '--tlsv1.2', '-o', temporary,
                       base + name])
        data = pathlib.Path(temporary).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('source checksum mismatch: ' + name)
        os.replace(temporary, path)
        return data
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass

# -B prevents writes, not reads: compile the verified bytes rather than trusting
# importlib's timestamp-based .pyc cache, including any preexisting __pycache__.
class VerifiedSource(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, cache, sources):
        self.cache, self.sources = cache, sources
    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_loader(fullname, self, origin=str(self.cache / (fullname + '.py')))
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        module.__file__ = str(self.cache / (module.__name__ + '.py'))
        exec(compile(self.sources[module.__name__], module.__file__, 'exec'), module.__dict__)

try:
    action = sys.argv[1]
    if action not in ('install', 'uninstall', 'upgrade'):
        raise ValueError('invalid loader action')
    manifest_path = pathlib.Path(os.environ.pop('DLOR_OPTISCALER_MANIFEST'))
    manifest_digest = os.environ.pop('DLOR_OPTISCALER_MANIFEST_SHA256')
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('unsafe manifest snapshot')
    data = manifest_path.read_bytes()
    if not re.fullmatch(r'[a-f0-9]{64}', manifest_digest) or hashlib.sha256(data).hexdigest() != manifest_digest:
        raise ValueError('manifest snapshot checksum mismatch')
    manifest = json.loads(data)
    runtime = manifest['runtime']
    if manifest.get('version') != 1 or set(runtime) != {'loader.py', 'installer.py', 'artifacts.py', 'game_discovery.py', 'update_optiscaler_config.py', 'nightly.py'}:
        raise ValueError('unsupported download manifest')
    cache, base = source_context()
    sources = {name[:-3]: verified_file(cache, base, name, digest)
               for name, digest in runtime.items() if name != 'loader.py' and (name != 'nightly.py' or action == 'upgrade')}
    sys.meta_path.insert(0, VerifiedSource(cache, sources))
    import artifacts
    artifacts.DOWNLOADS = manifest['downloads']
    import installer
    status = installer.main([action, *sys.argv[2:]])
    sys.exit(0 if status is None else status)
except Exception as error:
    print('DLOR OptiScaler: ' + str(error), file=sys.stderr)
    sys.exit(1)
