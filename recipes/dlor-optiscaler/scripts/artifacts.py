"""Recipe-local, public GitHub acquisition; no credentials or payload execution.

Normal recipe calls select exact descriptors from the loader-authenticated JSON.
Explicit fresh resolution requires GitHub's full ``sha256:`` asset digest and
never accepts metadata TTL reuse or offline fallback. The generic resolver
retains six-hour/seven-day verified offline caching for non-fresh callers. Archives are keyed
by repository, release tag, name and digest (hashed descriptor), locked per cache,
and atomically published. ZIP and stdlib-readable tar variants need no tools;
7z/BCJ2 uses system 7zz/7z or a SHA-verified official Linux console in this cache.

Use resolve_asset -> download_asset -> extract_archive in a private preparation
area. Extraction accepts only absent/empty destinations, preserving relative
layout; it never installs, runs setup scripts, or writes into a nonempty game.
Validation raises ArtifactError; network, storage and native archive errors may
also propagate, and callers must abort preparation on *any* such failure.
"""
import hashlib
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import unicodedata
from urllib.parse import quote, urljoin, urlsplit
import zipfile


class ArtifactError(ValueError):
    """Untrusted metadata, payload, or archive; caller must not change game files."""


MAX_METADATA = 4 * 1024 * 1024
MAX_DOWNLOAD = 1024 * 1024 * 1024
TIMEOUT = 30
METADATA_TTL = 6 * 60 * 60
OFFLINE_TTL = 7 * 24 * 60 * 60
MAX_ENTRIES = 10000
MAX_UNPACKED = 2 * 1024 * 1024 * 1024
MAX_FILE = 1024 * 1024 * 1024
TOOL_TIMEOUT = 180
# Set only by the verified loader, from its authenticated private JSON snapshot.
DOWNLOADS = None


def _url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in
            {'api.github.com', 'github.com', 'release-assets.githubusercontent.com'}
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment or any(ord(c) < 33 for c in url)):
        raise ArtifactError('non-official HTTPS URL rejected')
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_302(self, req, fp, code, msg, headers):
        # urllib's default handler drains redirect bodies with unbounded read().
        # Public downloads are GET only; close the body instead of consuming it.
        try:
            location = headers.get('location')
            if not location:
                raise ArtifactError('redirect has no Location')
            target = _url(urljoin(req.full_url, location))
            count = getattr(req, '_dlor_redirects', 0)
            if count >= 5:
                raise ArtifactError('GitHub redirect limit exceeded')
            request = self.redirect_request(req, fp, code, msg, headers, target)
            request._dlor_redirects = count + 1
        finally:
            fp.close()
        return self.parent.open(request, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _open(url):
    _url(url)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects()).open(
        urllib.request.Request(url, headers={'User-Agent': 'DLOR-OptiScaler', 'Accept': 'application/vnd.github+json'}),
        timeout=TIMEOUT)


def _http_chunks(response, *, limit, deadline):
    # HTTPResponse.read(n) can keep filling n forever on a slow trickle;
    # read1 performs one socket read, allowing our wall deadline to run.
    read = getattr(response, 'read1', response.read)
    total = 0
    while True:
        if time.monotonic() > deadline:
            raise ArtifactError('HTTP wall time limit exceeded')
        chunk = read(min(65536, limit - total + 1))
        total += len(chunk)
        if total > limit or time.monotonic() > deadline:
            raise ArtifactError('HTTP size or wall time limit exceeded')
        if not chunk:
            return
        yield chunk


def _private(path):
    path = Path(path).absolute()
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise ArtifactError('symlink in private cache path')
        if not parent.exists():
            parent.mkdir(mode=0o700, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise ArtifactError('unsafe private cache parent')
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ArtifactError('private directory must be owned by current user')
    os.chmod(path, 0o700)
    return path


@contextmanager
def _lock(cache):
    cache = _private(cache)
    fd = os.open(cache / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield cache
    finally:
        os.close(fd)


def _atomic_json(path, data):
    fd, name = tempfile.mkstemp(prefix='.partial-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _asset_path(asset, cache):
    key = hashlib.sha256(json.dumps(asset, sort_keys=True).encode()).hexdigest()
    return Path(cache) / 'archives' / key / asset['name']


def _verified(path, asset):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != asset['size']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == asset['sha256']


def _validate_asset(asset):
    _url(asset['url'])
    if not isinstance(asset['name'], str) or not re.fullmatch(r'[A-Za-z0-9_ .()+-]+', asset['name']) or asset['name'] in ('.', '..'):
        raise ArtifactError('invalid asset name')
    if type(asset.get('size')) is not int or not 0 < asset['size'] <= MAX_DOWNLOAD:
        raise ArtifactError('invalid asset size')
    if not re.fullmatch(r'[a-f0-9]{64}', asset['sha256']):
        raise ArtifactError('official SHA256 digest is required')
    if not isinstance(asset['tag'], str) or not asset['tag']:
        raise ArtifactError('invalid release tag')


def resolve_asset(repository: str, channel: str, pattern: str, cache: Path, *, fresh=False) -> dict:
    """Resolve stable, nightly, or tag:<exact tag> without changing asset shape.

    Explicit tags use a conservative ASCII Git-ref subset (1–255 characters):
    letters/digits/underscore first, then letters/digits/underscore/dot/plus/dash
    or slash. Empty/hidden components, '..', trailing dots and '.lock' suffixes
    are rejected. Tags are never normalized and are URL-encoded as one segment.
    """
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or any(
            part in ('.', '..') for part in repository.split('/')):
        raise ArtifactError('invalid GitHub repository')
    tag = channel[4:] if isinstance(channel, str) and channel.startswith('tag:') else None
    if channel not in ('stable', 'nightly') and tag is None:
        raise ArtifactError('unsupported release channel')
    if tag is not None and (not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./+-]{0,254}', tag)
                            or '..' in tag or any(not part or part.startswith('.') or
                            part.endswith(('.', '.lock')) for part in tag.split('/'))):
        raise ArtifactError('invalid explicit release tag')
    re.compile(pattern)
    if DOWNLOADS is not None and not fresh:
        matches = [asset for asset in DOWNLOADS.values()
                   if asset['repository'] == repository and asset['channel'] == channel
                   and re.fullmatch(pattern, asset['name'])]
        if len(matches) != 1:
            raise ArtifactError('download manifest selection must match exactly once')
        asset = {key: matches[0][key] for key in ('repository', 'tag', 'name', 'url', 'sha256', 'size')}
        _validate_asset(asset)
        return asset
    with _lock(cache) as cache:
        meta = _private(cache / 'metadata') / (hashlib.sha256(json.dumps([repository, channel, pattern]).encode()).hexdigest() + '.json')
        previous = None
        age = float('inf')
        try:
            if not meta.is_symlink() and meta.stat().st_size <= MAX_METADATA:
                stored = json.loads(meta.read_bytes())
                candidate = stored['asset']
                _validate_asset(candidate)
                if (candidate['repository'] == repository and re.fullmatch(pattern, candidate['name'])
                        and (tag is None or candidate['tag'] == tag)):
                    age = time.time() - stored['timestamp']
                    if 0 <= age <= OFFLINE_TTL:
                        previous = candidate
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not fresh and previous is not None and age <= METADATA_TTL:
            return previous
        url = f'https://api.github.com/repos/{repository}/releases'
        url += ('/tags/' + quote(tag, safe='') if tag is not None else
                '/latest' if channel == 'stable' else '?per_page=20')
        try:
            with _open(url) as response:
                raw = b''.join(_http_chunks(response, limit=MAX_METADATA, deadline=time.monotonic() + 60))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            # Authorization errors, redirects and invalid metadata are NOT offline.
            transient = not isinstance(exc, urllib.error.HTTPError) or exc.code in (408, 429, 500, 502, 503, 504)
            if not fresh and transient and previous is not None and _verified(_asset_path(previous, cache), previous):
                return previous
            raise
        release = json.loads(raw)
        if channel == 'nightly':
            if not isinstance(release, list):
                raise ArtifactError('invalid nightly release list')
            release = next((r for r in release if not r.get('draft')), None)
        asset = _select(release, repository, pattern)
        if tag is not None and asset['tag'] != tag:
            raise ArtifactError('release does not match explicit tag')
        _atomic_json(meta, {'timestamp': time.time(), 'asset': asset})
        return asset


def _select(release, repository, pattern):
    if not isinstance(release, dict):
        raise ArtifactError('release not found')
    if release.get('draft') or not release.get('tag_name'):
        raise ArtifactError('invalid release')
    matches = [a for a in release['assets'] if re.fullmatch(pattern, a['name'])]
    if len(matches) != 1:
        raise ArtifactError('release asset selection must match exactly once')
    asset = matches[0]

    digest = asset.get('digest') or ''
    if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
        raise ArtifactError('official SHA256 digest is required')
    result = {'repository': repository, 'tag': release['tag_name'], 'name': asset['name'],
            'url': asset['browser_download_url'], 'sha256': digest[7:].lower(), 'size': asset['size']}
    _validate_asset(result)
    return result


def download_asset(asset: dict, cache: Path) -> Path:
    _validate_asset(asset)
    with _lock(cache) as cache:
        target = _asset_path(asset, cache)
        directory = _private(target.parent)
        if _verified(target, asset):
            os.chmod(target, 0o600)
            return target
        if target.is_symlink() or target.is_file():
            target.unlink()
        fd, name = tempfile.mkstemp(prefix='.partial-', dir=directory)
        try:
            digest = hashlib.sha256()
            total = 0
            deadline = time.monotonic() + 10 * 60
            with os.fdopen(fd, 'wb') as output, _open(asset['url']) as response:
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != asset['size']:
                    raise ArtifactError('download Content-Length mismatch')
                for chunk in _http_chunks(response, limit=asset['size'], deadline=deadline):
                    total += len(chunk)
                    if total > asset['size'] or total > MAX_DOWNLOAD or time.monotonic() > deadline:
                        raise ArtifactError('download size or time limit exceeded')
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != asset['sha256'] or total != asset['size']:
                raise ArtifactError('download SHA256 or size mismatch')
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        return target


def _copy_member(source, target, size, mode):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    total = 0
    with target.open('xb') as output:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > size:
                raise ArtifactError('archive member exceeds declared size')
            output.write(chunk)
    if total != size:
        raise ArtifactError('truncated archive member')
    os.chmod(target, 0o600 | (mode & 0o111))


def _check_entries(entries):
    """Validate an entire member table before writing even staging files."""
    paths, explicit = {}, set()
    total = 0
    if len(entries) > MAX_ENTRIES:
        raise ArtifactError('archive entry count limit exceeded')
    for name, is_dir, size, mode, member in entries:
        if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/'):
            raise ArtifactError('unsafe archive path')
        name = name[:-1] if is_dir and name.endswith('/') else name
        parts = name.split('/')
        if any(not p or p in ('.', '..') or p.endswith((' ', '.')) or
               any(ord(c) < 32 or ord(c) == 127 for c in p) for p in parts):
            raise ArtifactError('ambiguous archive path')
        if mode & 0o7000 or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ArtifactError('archive links, devices and privileged modes forbidden')
        if stat.S_IFMT(mode) == stat.S_IFDIR and not is_dir:
            raise ArtifactError('archive entry type mismatch')
        if size < 0 or size > MAX_FILE or (is_dir and size):
            raise ArtifactError('archive member size limit exceeded')
        total += size
        if total > MAX_UNPACKED:
            raise ArtifactError('archive unpacked size limit exceeded')
        for depth in range(1, len(parts) + 1):
            relative = '/'.join(parts[:depth])
            key = unicodedata.normalize('NFC', relative).casefold()
            directory = depth < len(parts) or is_dir
            if key in paths:
                old_name, old_dir = paths[key]
                if relative != old_name or not old_dir or not directory:
                    raise ArtifactError('case or prefix collision in archive')
            else:
                paths[key] = (relative, directory)
            if depth == len(parts):
                if key in explicit:
                    raise ArtifactError('duplicate archive member')
                explicit.add(key)


def _safe_parent(path):
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise ArtifactError('symlink in extraction path')
        if not parent.exists():
            parent.mkdir(mode=0o700)
        elif not parent.is_dir():
            raise ArtifactError('extraction parent is not a directory')


@contextmanager
def _sevenzip(cache):
    system = shutil.which('7zz') or shutil.which('7z')
    if system:
        yield Path(system)
        return
    if cache is None:
        raise ArtifactError('7z extraction needs system 7zz/7z or a cache for verified official 7zip')
    machine = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64', 'i686': 'x86'}.get(platform.machine().lower())
    if platform.system() != 'Linux' or machine is None:
        raise ArtifactError('automatic official 7zip bootstrap supports Linux x64/arm64/x86 only')
    asset = resolve_asset('ip7z/7zip', 'stable', rf'7z\d+-linux-{machine}\.tar\.xz', cache)
    archive = download_asset(asset, cache)
    # Re-extract from the rehashed official archive, never trust an old binary.
    with tempfile.TemporaryDirectory(prefix='.7zip-', dir=_private(cache)) as temporary:
        destination = Path(temporary) / 'console'
        extract_archive(archive, destination)
        tool = destination / '7zz'
        if tool.is_symlink() or not tool.is_file() or not os.access(tool, os.X_OK):
            raise ArtifactError('verified official 7zip archive contains no executable console')
        yield tool


def _run_tool(command, *, limit, output=None, deadline=None):
    """Bound stdout, stderr and wall time; never give 7zip filesystem output."""
    deadline = min(deadline or float('inf'), time.monotonic() + TOOL_TIMEOUT)
    data, errors = bytearray(), bytearray()
    total = 0
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
                selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ArtifactError('7zip time limit exceeded')
                    for key, event in selector.select(min(remaining, 0.25)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        elif key.data == 'stderr':
                            errors.extend(chunk)
                            if len(errors) > 65536:
                                raise ArtifactError('7zip diagnostic size limit exceeded')
                        else:
                            total += len(chunk)
                            if total > limit:
                                raise ArtifactError('7zip output size limit exceeded')
                            if output is not None:
                                output.write(chunk)
                            else:
                                data.extend(chunk)
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if code:
                # Do not print arbitrary payload filenames or terminal controls.
                raise ArtifactError(f'7zip exited with status {code}')
            return bytes(data) if output is None else total
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def _extract_7z(archive, staging, cache):
    with _sevenzip(cache) as tool:
        deadline = time.monotonic() + 15 * 60
        listing = _run_tool([str(tool), 'l', '-slt', '-ba', '-sccUTF-8', '-pDLOR-no-password', '--', str(archive)], limit=MAX_METADATA, deadline=deadline).decode('utf-8')
        entries = []
        for block in listing.strip().split('\n\n'):
            fields = {}
            for line in block.splitlines():
                key, separator, value = line.partition(' = ')
                if not separator or key in fields:
                    raise ArtifactError('ambiguous 7zip member listing')
                fields[key] = value
            if not {'Path', 'Size', 'Attributes', 'Encrypted'} <= fields.keys():
                raise ArtifactError('incomplete 7zip member listing')
            if fields['Encrypted'] != '-' or any('link' in k.casefold() for k in fields):
                raise ArtifactError('encrypted or linked 7zip member forbidden')
            attributes = fields['Attributes']
            posix = attributes.split()[-1] if attributes.split() else ''
            directory = attributes.startswith('D') or posix.startswith('d')
            mode = 0
            if len(posix) == 10:
                if posix[0] not in ('d', '-') or any(c in posix for c in 'sStT'):
                    raise ArtifactError('unsafe 7zip member type or mode')
                mode = sum(1 << (8 - i) for i, char in enumerate(posix[1:]) if char != '-')
            entries.append((fields['Path'], directory, int(fields['Size']), mode, fields))
        _check_entries(entries)
        for name, directory, size, mode, fields in entries:
            target = staging / name
            if directory:
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # stdout-only extraction means even a deceptive native member table
            # can never create links or files outside our validated destination.
            with target.open('xb') as output:
                count = _run_tool([str(tool), 'x', '-so', '-bd', '-y', '-spd', '-ssc', '-pDLOR-no-password', '--', str(archive), name],
                                  limit=size, output=output, deadline=deadline)
            if count != size:
                raise ArtifactError('7zip member size mismatch')
            os.chmod(target, 0o600 | (mode & 0o111))


def extract_archive(archive: Path, destination: Path, *, cache: Path | None = None) -> None:
    """Extract only to a fresh/empty staging destination, never overlay a game.

    The caller must first obtain the archive through download_asset. Unsupported
    formats and damaged archives fail without publishing any partial directory.
    """
    archive, destination = Path(archive).absolute(), Path(destination).absolute()
    if destination.is_symlink() or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
        raise ArtifactError('extraction destination must be absent or empty')
    _safe_parent(destination.parent)
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_DOWNLOAD:
        raise ArtifactError('archive must be a bounded regular file')
    staging = Path(tempfile.mkdtemp(prefix='.extract-', dir=destination.parent))
    try:
        with archive.open('rb') as source:
            magic = source.read(6)
        if magic == b'7z\xbc\xaf\x27\x1c':
            _extract_7z(archive, staging, cache)
        elif zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as bundle:
                entries = [(m.orig_filename, m.is_dir(), m.file_size, m.external_attr >> 16, m) for m in bundle.infolist()]
                _check_entries(entries)
                for name, is_dir, size, mode, member in entries:
                    if '\x00' in name or member.flag_bits & 1:
                        raise ArtifactError('NUL path or encrypted ZIP unsupported')
                    target = staging / member.filename
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    else:
                        with bundle.open(member) as source:
                            _copy_member(source, target, member.file_size, member.external_attr >> 16)
        else:
            with tarfile.open(archive, 'r:*') as bundle:
                entries = []
                for member in bundle:
                    if len(entries) >= MAX_ENTRIES:
                        raise ArtifactError('archive entry count limit exceeded')
                    if not (member.isdir() or member.isfile()) or member.issparse():
                        raise ArtifactError('archive links, devices and sparse files forbidden')
                    entries.append((member.name, member.isdir(), member.size, member.mode, member))
                _check_entries(entries)
                for name, is_dir, size, mode, member in entries:
                    target = staging / member.name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    elif member.isfile():
                        source = bundle.extractfile(member)
                        if source is None:
                            raise ArtifactError('unreadable archive member')
                        with source:
                            _copy_member(source, target, member.size, member.mode)
                    else:
                        raise ArtifactError('unsupported archive entry')
        os.replace(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
