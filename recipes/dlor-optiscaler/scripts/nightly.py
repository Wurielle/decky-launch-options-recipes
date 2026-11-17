"""Legacy fgmod-only nightly updater, called only without a DLOR journal.

The DLOR installer owns managed updates; this module never writes its journal.
Preserve legacy supporting-DLL precedence without accepting unverified archives
or extracted caches. No setup program or downloaded DLL is executed here.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
import time

import artifacts
from installer import InstallerError, safe_target, package_inventory, atomic_write, game_state


def dlls(root, excluded=()):
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part.casefold() == 'renames' or part.casefold().startswith('fsr4-')
               or part.casefold() in excluded for part in relative.parts[:-1]):
            continue
        if path.suffix.casefold() != '.dll' or path.name.casefold() == 'optiscaler.dll':
            continue
        path = safe_target(root, relative.as_posix())
        if not path.is_file():
            continue
        key = relative.as_posix().casefold()
        if key in result:
            raise InstallerError('Ambiguous legacy support filename')
        result[key] = path
    return result


def overlay(cache, fgmod, directories):
    metadata_path = safe_target(fgmod, 'install-manifest.json')
    metadata = json.loads(metadata_path.read_bytes()) if metadata_path.is_file() else {}
    variants = metadata.get('fsr4_variants', {})
    sources = dlls(fgmod, {v['dir_name'].casefold() for v in variants.values() if 'dir_name' in v})
    selected = os.environ.get('FGMOD_FSR4_VARIANT') or metadata.get('selected_default_variant')
    variant_dir = variants.get(selected, {}).get('dir_name')
    variant = safe_target(fgmod, variant_dir) if variant_dir else None
    if variant is not None:
        sources.update(dlls(variant))
    archive_files = dlls(cache)
    modern_layout = (cache / 'OptiScaler').is_dir()
    # Preflight every destination before touching any installation.
    plans = []
    for directory in directories:
        target = safe_target(directory, 'OptiScaler') if modern_layout else directory
        manifest = safe_target(target, '.dlor-fgmod.json')
        legacy_manifest = safe_target(target, '.dlor-fsr4.json')
        previous_file = manifest if manifest.is_file() else legacy_manifest
        previous = json.loads(previous_file.read_bytes()) if previous_file.is_file() else {}
        copies = {safe_target(directory, source.relative_to(cache).as_posix()): source
                  for source in archive_files.values()}
        current = {}
        for relative, source in sources.items():
            archive_key = 'optiscaler/' + relative if modern_layout else relative
            bundled = archive_files.get(archive_key)
            source_root = variant if variant is not None and source.is_relative_to(variant) else fgmod
            destination = (safe_target(directory, bundled.relative_to(cache).as_posix()) if bundled
                           else safe_target(target, source.relative_to(source_root).as_posix()))
            copies[destination] = source
            current[destination.relative_to(target).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
        removals = []
        for relative, digest in previous.items():
            destination = safe_target(target, relative)
            archive_key = 'optiscaler/' + relative.casefold() if modern_layout else relative.casefold()
            if relative not in current and archive_key not in archive_files and destination.is_file():
                if hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
                    removals.append(destination)
        copies[safe_target(directory, 'dxgi.dll')] = cache / 'OptiScaler.dll'
        plans.append((copies, removals, manifest, current))
    for copies, removals, manifest, current in plans:
        for destination, source in copies.items():
            atomic_write(destination, source.read_bytes(), destination.stat().st_mode & 0o777 if destination.exists() else 0o600)
        for destination in removals:
            destination.unlink()
        atomic_write(manifest, (json.dumps(current) + '\n').encode())


def legacy_upgrade(root):
    root = Path(root).resolve(strict=True)
    directories = []
    for config in root.rglob('*'):
        if config.name.casefold() != 'optiscaler.ini' or not config.is_file():
            continue
        config = safe_target(root, config.relative_to(root).as_posix())
        if safe_target(config.parent, 'dxgi.dll').is_file():
            directories.append(config.parent)
    if not directories:
        raise InstallerError('No fgmod OptiScaler installation found')
    home = Path.home().resolve(strict=True)
    cache = Path(os.environ.get('OPTISCALER_CACHE_DIR', str(Path(os.environ.get('TMPDIR', '/tmp')) / 'update-optiscaler')))
    with artifacts._lock(cache) as cache:
        # Force a current official response, even when cached metadata is warm.
        # This request is deliberately not permitted to fall back offline.
        url = 'https://api.github.com/repos/optiscaler/OptiScaler-nightly/releases?per_page=20'
        try:
            with artifacts._open(url) as response:
                releases = json.loads(b''.join(artifacts._http_chunks(response, limit=artifacts.MAX_METADATA, deadline=time.monotonic() + 60)))
        except OSError as error:
            raise InstallerError('Could not download the latest nightly release metadata') from error
        release = next((entry for entry in releases if not entry.get('draft')), None)
        asset = artifacts._select(release, 'optiscaler/OptiScaler-nightly', r'(?i)(?!.*(?:debug|symbols|source)).*optiscaler.*\.7z')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', asset['tag']):
            raise InstallerError('Invalid nightly release tag')
        directory = artifacts._private(cache / asset['tag'])
        archive = directory / asset['name']
        files = directory / 'files'
        receipt = directory / 'verified.json'
        for path in (archive, files, receipt):
            if path.is_symlink():
                raise InstallerError('Symlink in legacy cache')
        valid = False
        if files.is_dir() and receipt.is_file():
            try:
                record = json.loads(receipt.read_bytes())
                valid = record['asset'] == asset and record['files'] == package_inventory(files)
            except (OSError, ValueError, KeyError):
                pass
        if not valid:
            if not artifacts._verified(archive, asset):
                fd, temporary = tempfile.mkstemp(prefix='.download-', dir=directory)
                os.close(fd)
                try:
                    with artifacts._open(asset['url']) as response, open(temporary, 'wb') as output:
                        for chunk in artifacts._http_chunks(response, limit=asset['size'], deadline=time.monotonic() + 600):
                            output.write(chunk)
                    if not artifacts._verified(Path(temporary), asset):
                        raise InstallerError('Nightly archive SHA256 or size mismatch')
                    os.replace(temporary, archive)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(prefix='.files-', dir=directory) as temporary:
                staging = Path(temporary) / 'files'
                artifacts.extract_archive(archive, staging, cache=cache / 'tools')
                if not (staging / 'OptiScaler.dll').is_file():
                    raise InstallerError('Nightly archive contains no OptiScaler.dll')
                if files.exists():
                    shutil.rmtree(files)
                os.replace(staging, files)
                atomic_write(receipt, (json.dumps({'asset': asset, 'files': package_inventory(files)}) + '\n').encode())
        # Finish artifact/tool acquisition before taking the game lock. Keep
        # the cache stable through copying; DLOR never acquires artifact locks
        # while holding its game lock, so this order cannot invert main ON/OFF.
        # Eligibility and every overlay write share main's lock. Inspection must
        # neither recover/migrate an intervening DLOR journal nor create one:
        # a legacy-only update must remain eligible on its next invocation.
        with game_state(root, home / '.dlor/state/dlor-optiscaler', recover=False) as (_, _, journal, _):
            if journal.exists():
                raise InstallerError('Game now has a DLOR journal; refusing legacy overlay')
            overlay(files, home / 'fgmod', directories)
    print('Nightly legacy update completed:', asset['tag'])
    return 0
