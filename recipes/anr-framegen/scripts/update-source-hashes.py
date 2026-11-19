#!/usr/bin/env python3
"""Refresh only recipe-local runtime pins and physical entrypoints (no network).

Commit loader.py and downloads.json first, then supply that immutable commit with
--bundle-revision. This does not commit, publish or build a catalog.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def main():
    previous = (HERE / 'install.sh').read_text() if (HERE / 'install.sh').exists() else ''
    retained = re.search(r'^BUNDLE_REVISION=([a-f0-9]{40})$', previous, re.M)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-revision', default=retained[1] if retained else None)
    parser.add_argument('--bundle-repository', default='Wurielle/decky-launch-options-recipes')
    args = parser.parse_args()
    if not args.bundle_revision or not re.fullmatch(r'[a-f0-9]{40}', args.bundle_revision):
        parser.error('--bundle-revision must be a full lowercase Git commit')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', args.bundle_repository):
        parser.error('bundle repository must be owner/repository')
    manifest = json.loads((HERE / 'downloads.json').read_bytes())
    manifest['runtime'] = {'loader.py': hashlib.sha256((HERE / 'loader.py').read_bytes()).hexdigest()}
    raw = (json.dumps(manifest, indent=2) + '\n').encode()
    (HERE / 'downloads.json').write_bytes(raw)
    template = (HERE / 'entrypoint.sh.in').read_text()
    for action in ('install', 'uninstall'):
        output = template.replace('@REVISION@', args.bundle_revision).replace('@REPOSITORY@', args.bundle_repository)
        output = output.replace('@MANIFEST@', hashlib.sha256(raw).hexdigest()).replace('@ACTION@', action)
        (HERE / (action + '.sh')).write_text(output)
    print('ANR FG runtime hashes and entrypoints generated; bundle:', args.bundle_revision)


if __name__ == '__main__':
    main()
