"""Credential-free fixtures; live GitHub networking is forbidden in this suite."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('artifacts', Path(__file__).resolve().parents[1] / 'scripts/artifacts.py')
assert SPEC is not None and SPEC.loader is not None
artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifacts)


class Response(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {'Content-Length': str(len(content))}


class ArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        network = patch('socket.create_connection', side_effect=AssertionError('unexpected live network call'))
        network.start()
        self.addCleanup(network.stop)
        self.payload = b'official archive'
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.release = {'tag_name': 'v1', 'draft': False, 'prerelease': False, 'assets': [
            {'name': 'tool.zip', 'browser_download_url': 'https://github.com/owner/project/releases/download/v1/tool.zip',
             'digest': 'sha256:' + self.digest, 'size': len(self.payload)}]}

    def response(self, content):
        return Response(content)

    def test_all_binary_manifest_selections_require_no_metadata(self):
        import re
        manifest = json.loads((Path(__file__).resolve().parents[1] / 'scripts/downloads.json').read_bytes())
        self.assertEqual(len(manifest['downloads']), 9)
        with patch.object(artifacts, 'DOWNLOADS', manifest['downloads']), patch.object(artifacts, '_open', side_effect=AssertionError('pinned dependency queried mutable metadata')):
            for pin in manifest['downloads'].values():
                selected = artifacts.resolve_asset(pin['repository'], pin['channel'], re.escape(pin['name']), self.root)
                self.assertEqual(selected, {key: value for key, value in pin.items() if key != 'channel'})

    def test_manifest_pin_bypasses_metadata_and_latest_ignores_ttl(self):
        pinned = {'repository': 'owner/project', 'tag': 'pinned-v0', 'name': 'tool.zip',
                  'url': self.release['assets'][0]['browser_download_url'],
                  'sha256': self.digest, 'size': len(self.payload)}
        downloads = {'core': dict(pinned, channel='nightly')}
        with patch.object(artifacts, 'DOWNLOADS', downloads, create=True):
            with patch.object(artifacts, '_open', side_effect=AssertionError('pins must not fetch metadata')):
                self.assertEqual(artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root), pinned)
            with patch.object(artifacts, '_open', return_value=self.response(json.dumps([self.release]).encode())) as request:
                latest = artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root, fresh=True)
                self.assertEqual(latest['tag'], 'v1')
                request.assert_called_once()
            with patch.object(artifacts, '_open', return_value=self.response(json.dumps([dict(self.release, tag_name='v2')]).encode())) as request:
                self.assertEqual(artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root, fresh=True)['tag'], 'v2')
                request.assert_called_once()
            with patch.object(artifacts, '_open', return_value=self.response(self.payload)):
                artifacts.download_asset(dict(latest, tag='v2'), self.root)
            import urllib.error
            with patch.object(artifacts, '_open', side_effect=urllib.error.URLError('offline')):
                with self.assertRaises(urllib.error.URLError):
                    artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root, fresh=True)
            with patch.object(artifacts, '_open', side_effect=AssertionError('missing pin fails closed')):
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.resolve_asset('unknown/repo', 'stable', r'.*', self.root)

    def test_stable_release_resolves_and_downloads_verified_private_cache(self):
        self.assertIsNotNone(artifacts, 'verified acquisition module is not implemented')
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps(self.release).encode())) as request:
            asset = artifacts.resolve_asset('owner/project', 'stable', r'tool\.zip', self.root)
        self.assertEqual(request.call_args.args[0], 'https://api.github.com/repos/owner/project/releases/latest')
        self.assertEqual(asset['sha256'], self.digest)
        self.assertEqual(asset['tag'], 'v1')
        self.assertEqual(asset['repository'], 'owner/project')
        self.assertEqual(asset['name'], 'tool.zip')
        with patch.object(artifacts, '_open', return_value=self.response(self.payload)):
            target = artifacts.download_asset(asset, self.root)
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with patch.object(artifacts, '_open', side_effect=AssertionError('warm cache must not use network')):
            self.assertEqual(artifacts.download_asset(asset, self.root), target)

    def test_named_tag_channels_encode_exact_tag_and_isolate_metadata_cache(self):
        from urllib.parse import quote
        repository = 'xXJSONDeruloXx/OptiScaler-Bleeding-Edge'
        cases = [(repository, 'tag:' + tag, tag) for tag in
                 ('opti-9-2-a', 'fsr-4-1-1', 'fsr-4-1-1-rdna2', 'compat/v1+build')]
        cases += [(repository, 'stable', 'latest'), (repository, 'nightly', 'nightly'),
                  ('owner/project', 'tag:opti-9-2-a', 'opti-9-2-a')]
        assets = []
        for repo, channel, tag in cases:
            release = dict(self.release, tag_name=tag)
            body = [release] if channel == 'nightly' else release
            suffix = ('/latest' if channel == 'stable' else '?per_page=20' if channel == 'nightly'
                      else '/tags/' + quote(tag, safe=''))
            with self.subTest(repository=repo, channel=channel), patch.object(
                    artifacts, '_open', return_value=self.response(json.dumps(body).encode())) as request:
                asset = artifacts.resolve_asset(repo, channel, r'tool\.zip', self.root)
                request.assert_called_once_with(f'https://api.github.com/repos/{repo}/releases{suffix}')
                self.assertEqual(asset, {'repository': repo, 'tag': tag, 'name': 'tool.zip',
                                        'url': self.release['assets'][0]['browser_download_url'],
                                        'sha256': self.digest, 'size': len(self.payload)})
                assets.append(asset)
        self.assertEqual(len(list((self.root / 'metadata').glob('*.json'))), len(cases))
        self.assertEqual(len({artifacts._asset_path(asset, self.root) for asset in assets}), len(cases))
        with patch.object(artifacts, '_open', side_effect=AssertionError('warm channel cache must be isolated')):
            for (repo, channel, _), asset in zip(cases, assets):
                self.assertEqual(artifacts.resolve_asset(repo, channel, r'tool\.zip', self.root), asset)

    def test_named_tag_rejects_unsafe_tags_before_cache_or_network(self):
        tags = ('', '.', '..', '../latest', 'v1/../latest', '/v1', 'v1/', 'v1//x',
                'v1..x', '.hidden', 'v1/.hidden', 'v1.', 'v1.lock', 'v1.lock/x',
                'v1?per_page=20', 'v1#fragment', 'v1%2Fother', 'v1\\other',
                'https://evil.example/x', 'v1:other', '-v1', 'v 1', 'v1\n',
                'v1\x00', 'v1\x7f', 'v1\u202e', 'v' * 256)
        for tag in tags:
            with self.subTest(tag=tag), patch.object(artifacts, '_open', side_effect=AssertionError('unsafe tag reached network')) as request:
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.resolve_asset('owner/project', 'tag:' + tag, r'tool\.zip', self.root / 'unused')
                request.assert_not_called()
                self.assertFalse((self.root / 'unused').exists())

    def test_unsupported_channel_types_are_rejected_without_network(self):
        for channel in (None, 1, [], {}, '', 'latest', 'Tag:v1', 'v1'):
            with self.subTest(channel=channel), patch.object(artifacts, '_open') as request:
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.resolve_asset('owner/project', channel, r'tool\.zip', self.root)
                request.assert_not_called()

    def test_named_tag_rejects_mismatched_release_without_publishing_metadata(self):
        for index, tag in enumerate(('v2', 'V1', '')):
            cache = self.root / str(index)
            release = dict(self.release, tag_name=tag)
            with self.subTest(tag=tag), patch.object(
                    artifacts, '_open', return_value=self.response(json.dumps(release).encode())):
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.resolve_asset('owner/project', 'tag:v1', r'tool\.zip', cache)
            self.assertFalse(list(cache.rglob('*.json')))

    def test_named_tag_ignores_cached_wrong_tag_even_with_verified_archive(self):
        import urllib.error
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps(self.release).encode())):
            asset = artifacts.resolve_asset('owner/project', 'tag:v1', r'tool\.zip', self.root)
        wrong_asset = dict(asset, tag='v2')
        with patch.object(artifacts, '_open', return_value=self.response(self.payload)):
            artifacts.download_asset(wrong_asset, self.root)
        metadata = next((self.root / 'metadata').glob('*.json'))
        stored = json.loads(metadata.read_bytes())
        stored['asset'] = wrong_asset
        metadata.write_text(json.dumps(stored))
        for ttl in (artifacts.METADATA_TTL, -1):
            with self.subTest(ttl=ttl), patch.object(artifacts, 'METADATA_TTL', ttl), patch.object(
                    artifacts, '_open', side_effect=urllib.error.URLError('offline')) as request:
                with self.assertRaises(urllib.error.URLError):
                    artifacts.resolve_asset('owner/project', 'tag:v1', r'tool\.zip', self.root)
                request.assert_called_once()
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps(self.release).encode())) as request:
            self.assertEqual(artifacts.resolve_asset('owner/project', 'tag:v1', r'tool\.zip', self.root), asset)
            request.assert_called_once()

    def test_metadata_security_boundary_rejects_untrusted_inputs(self):
        import copy
        variants = []
        for digest in (None, '', 'sha512:' + self.digest, 'sha256:1234'):
            release = copy.deepcopy(self.release)
            release['assets'][0]['digest'] = digest
            variants.append(release)
        for url in ('http://github.com/x', 'https://evil.example/tool.zip',
                    'https://github.com.evil.example/x', 'https://github.com@evil.example/x',
                    'https://github.com:444/x'):
            release = copy.deepcopy(self.release)
            release['assets'][0]['browser_download_url'] = url
            variants.append(release)
        for field, value in (('tag_name', ''), ('draft', True)):
            release = copy.deepcopy(self.release)
            release[field] = value
            variants.append(release)
        release = copy.deepcopy(self.release)
        release['assets'].append(release['assets'][0])
        variants.append(release)
        for release in variants:
            with self.subTest(release=release), patch.object(artifacts, '_open', return_value=self.response(json.dumps(release).encode())):
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.resolve_asset('owner/project', 'stable', r'.*', self.root / str(len(json.dumps(release))))
        for repository in ('../x', 'https://evil/x', 'owner/project/extra'):
            with self.subTest(repository=repository), patch.object(artifacts, '_open') as request:
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.resolve_asset(repository, 'stable', r'.*', self.root)
                request.assert_not_called()
        for url in ('http://github.com/x', 'https://evil.example/x', 'https://objects.githubusercontent.com/x',
                    'https://release-assets.githubusercontent.com.evil/x'):
            with self.subTest(redirect=url):
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts._Redirects().redirect_request(None, None, 302, 'redirect', {}, url)

    def test_nightly_prerelease_metadata_ttl_and_verified_offline_fallback(self):
        import urllib.error
        nightly = dict(self.release, prerelease=True)
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps([nightly]).encode())) as request:
            asset = artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root)
        self.assertEqual(request.call_args.args[0], 'https://api.github.com/repos/owner/project/releases?per_page=20')
        with patch.object(artifacts, '_open', side_effect=AssertionError('metadata TTL reuse')):
            self.assertEqual(artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root), asset)
        with patch.object(artifacts, '_open', return_value=self.response(self.payload)):
            archive = artifacts.download_asset(asset, self.root)
        with patch.object(artifacts, 'METADATA_TTL', -1), patch.object(artifacts, '_open', side_effect=urllib.error.URLError('offline')):
            self.assertEqual(artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root), asset)
            archive.write_bytes(b'corrupt')
            with self.assertRaises((artifacts.ArtifactError, urllib.error.URLError)):
                artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root)
        with patch.object(artifacts, '_open', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises((artifacts.ArtifactError, urllib.error.URLError)):
                artifacts.resolve_asset('owner/project', 'stable', r'tool\.zip', self.root / 'first-install')
        broken = dict(nightly, assets=[])
        with patch.object(artifacts, 'METADATA_TTL', -1), patch.object(artifacts, '_open', return_value=self.response(json.dumps([broken]).encode())):
            with self.assertRaises(artifacts.ArtifactError):
                artifacts.resolve_asset('owner/project', 'nightly', r'tool\.zip', self.root)

    def test_download_rejects_bad_payloads_and_repairs_corruption_under_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps(self.release).encode())):
            asset = artifacts.resolve_asset('owner/project', 'stable', r'tool\.zip', self.root)
        for payload in (self.payload[:-1], b'x' * len(self.payload), self.payload + b'extra'):
            response = self.response(payload)
            response.headers['Content-Length'] = str(len(self.payload))
            with self.subTest(payload=payload), patch.object(artifacts, '_open', return_value=response):
                with self.assertRaises(artifacts.ArtifactError):
                    artifacts.download_asset(asset, self.root)
            self.assertFalse(list(self.root.rglob('.partial-*')))
            self.assertFalse(list(self.root.rglob('tool.zip')))
        calls = []
        mutex = threading.Lock()
        def transport(url):
            with mutex:
                calls.append(url)
            return self.response(self.payload)
        with patch.object(artifacts, '_open', side_effect=transport):
            with ThreadPoolExecutor(max_workers=6) as pool:
                paths = list(pool.map(lambda _: artifacts.download_asset(asset, self.root), range(6)))
        self.assertEqual(len(calls), 1, 'concurrent cache misses must serialize')
        self.assertEqual(len(set(paths)), 1)
        paths[0].write_bytes(b'corrupt')
        with patch.object(artifacts, '_open', side_effect=transport):
            self.assertEqual(artifacts.download_asset(asset, self.root).read_bytes(), self.payload)
        with patch.object(artifacts, '_open', side_effect=AssertionError('validate before network')):
            for changes in ({'sha256': ''}, {'name': '../escape'}, {'size': -1}, {'url': 'https://evil.example/x'}):
                with self.subTest(changes=changes), self.assertRaises(artifacts.ArtifactError):
                    artifacts.download_asset(dict(asset, **changes), self.root)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        linked = self.root / 'linked'
        linked.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.download_asset(asset, linked)

    def test_zip_and_tar_preserve_layout_executable_mode_and_atomic_destination(self):
        import stat
        import tarfile
        import zipfile
        archive = self.root / 'fixture.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            info = zipfile.ZipInfo('OptiScaler/Support/helper')
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            z.writestr(info, b'tool')
            z.writestr('OptiScaler/OptiScaler.ini', b'[config]')
        destination = self.root / 'unzipped'
        artifacts.extract_archive(archive, destination)
        self.assertEqual((destination / 'OptiScaler/Support/helper').read_bytes(), b'tool')
        self.assertTrue((destination / 'OptiScaler/Support/helper').stat().st_mode & 0o100)
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.extract_archive(archive, destination)
        self.assertEqual((destination / 'OptiScaler/OptiScaler.ini').read_bytes(), b'[config]')
        archive = self.root / 'fixture.tar.xz'
        with tarfile.open(archive, 'w:xz') as tar:
            info = tarfile.TarInfo('nested/data.dll')
            info.size = 4
            tar.addfile(info, io.BytesIO(b'data'))
        destination = self.root / 'untarred'
        destination.mkdir()
        artifacts.extract_archive(archive, destination)
        self.assertEqual((destination / 'nested/data.dll').read_bytes(), b'data')

    def test_archives_reject_path_type_collision_and_resource_attacks_before_publish(self):
        import stat
        import tarfile
        import zipfile
        attacks = [('../escaped',), (str(self.root / 'absolute-escaped'),), ('C:/drive',), ('a\\b',),
                   ('a/./b',), ('a//b',), ('a/../b',), ('a:stream',), ('name. ',),
                   ('file', 'FILE'), ('file', 'file/child'), ('file/child', 'file'),
                   ('Render/a', 'render/b')]
        for index, names in enumerate(attacks):
            archive = self.root / f'attack-{index}.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('safe-first', b'safe')
                for name in names:
                    z.writestr(name, b'attack')
            destination = self.root / f'out-{index}'
            with self.subTest(names=names), self.assertRaises(artifacts.ArtifactError):
                artifacts.extract_archive(archive, destination)
            self.assertFalse(destination.exists())
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFREG | 0o4755, stat.S_IFREG | 0o2755):
            archive = self.root / 'bad-mode.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                info = zipfile.ZipInfo('link')
                info.external_attr = mode << 16
                z.writestr(info, b'target')
            with self.subTest(mode=mode), self.assertRaises(artifacts.ArtifactError):
                artifacts.extract_archive(archive, self.root / 'bad-mode')
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            archive = self.root / 'bad.tar'
            with tarfile.open(archive, 'w') as tar:
                info = tarfile.TarInfo('unsafe')
                info.type = kind
                info.linkname = '../escaped'
                tar.addfile(info)
            with self.subTest(kind=kind), self.assertRaises(artifacts.ArtifactError):
                artifacts.extract_archive(archive, self.root / 'bad-tar')
        archive = self.root / 'limits.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('a', b'12345')
            z.writestr('b', b'12345')
        for limit, value in (('MAX_ENTRIES', 1), ('MAX_FILE', 4), ('MAX_UNPACKED', 9)):
            with self.subTest(limit=limit), patch.object(artifacts, limit, value), self.assertRaises(artifacts.ArtifactError):
                artifacts.extract_archive(archive, self.root / 'limits')
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'link').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.extract_archive(archive, self.root / 'link/out')
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(list(self.root.glob('.extract-*')))
        self.assertFalse((self.root / 'escaped').exists())

    def test_7zip_bootstrap_uses_official_verified_tar_without_global_install(self):
        import tarfile
        archive = self.root / 'tool.tar.xz'
        with tarfile.open(archive, 'w:xz') as tar:
            for name, data in (('7zz', b'fake verified console'), ('License.txt', b'license')):
                info = tarfile.TarInfo(name)
                info.mode = 0o755
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        asset = {'official': 'test-boundary'}
        with patch.object(artifacts.shutil, 'which', return_value=None), patch.object(artifacts, 'resolve_asset', return_value=asset) as resolve, patch.object(artifacts, 'download_asset', return_value=archive) as download:
            with artifacts._sevenzip(self.root / 'tools') as tool:
                self.assertEqual(tool.read_bytes(), b'fake verified console')
                self.assertTrue(tool.stat().st_mode & 0o100)
            resolve.assert_called_once()
            self.assertEqual(resolve.call_args.args[:2], ('ip7z/7zip', 'stable'))
            self.assertRegex('7z2605-linux-x64.tar.xz', resolve.call_args.args[2])
            download.assert_called_once_with(asset, self.root / 'tools')
            self.assertFalse(tool.exists(), 'no unverified extracted-tool reuse')

    def test_real_7zip_bcj2_extraction_and_symlink_rejection(self):
        import os
        import shutil
        import subprocess
        tool = os.environ.get('DLOR_TEST_7ZZ') or shutil.which('7zz') or shutil.which('7z')
        if not tool:
            self.skipTest('set DLOR_TEST_7ZZ to verified official 7zz to exercise BCJ2')
        source = self.root / 'source'
        (source / 'nested').mkdir(parents=True)
        (source / 'nested/backend.dll').write_bytes(b'BCJ2 fixture payload' * 100)
        archive = self.root / 'fixture.7z'
        subprocess.run([tool, 'a', '-t7z', '-m0=BCJ2', '-m1=LZMA2', str(archive), 'nested'], cwd=source, capture_output=True, check=True)
        with patch.object(artifacts.shutil, 'which', return_value=tool):
            artifacts.extract_archive(archive, self.root / 'sevenzip')
        self.assertEqual((self.root / 'sevenzip/nested/backend.dll').read_bytes(), (source / 'nested/backend.dll').read_bytes())
        (source / 'link').symlink_to('nested/backend.dll')
        archive = self.root / 'symlink.7z'
        subprocess.run([tool, 'a', '-snl', str(archive), 'link'], cwd=source, capture_output=True, check=True)
        with patch.object(artifacts.shutil, 'which', return_value=tool), self.assertRaises(artifacts.ArtifactError):
            artifacts.extract_archive(archive, self.root / 'bad-7zip')
        self.assertFalse((self.root / 'bad-7zip').exists())

    def test_http_reader_deadline_and_corrupted_metadata_are_fail_closed(self):
        import urllib.error
        with patch.object(artifacts, 'MAX_METADATA', 3), patch.object(artifacts, '_open', return_value=self.response(b'1234')):
            with self.assertRaises(artifacts.ArtifactError):
                artifacts.resolve_asset('owner/project', 'stable', r'.*', self.root)
        with patch.object(artifacts, 'time') as clock:
            clock.monotonic.side_effect = [0, 100]
            with self.assertRaises(artifacts.ArtifactError):
                list(artifacts._http_chunks(self.response(b'data'), limit=10, deadline=1))
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps(self.release).encode())):
            asset = artifacts.resolve_asset('owner/project', 'stable', r'tool\.zip', self.root)
        metadata = next((self.root / 'metadata').glob('*.json'))
        metadata.write_bytes(b'{incomplete')
        with patch.object(artifacts, '_open', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(urllib.error.URLError):
                artifacts.resolve_asset('owner/project', 'stable', r'tool\.zip', self.root)
        with patch.object(artifacts, '_open', return_value=self.response(json.dumps(self.release).encode())):
            self.assertEqual(artifacts.resolve_asset('owner/project', 'stable', r'tool\.zip', self.root), asset)

    def test_concurrent_first_install_creates_missing_cache_without_races(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        cache = self.root / 'brand-new-cache'
        barrier = threading.Barrier(4)
        original_mkdir = Path.mkdir
        def synchronized_mkdir(path, *args, **kwargs):
            if path == cache:
                barrier.wait(timeout=5)
            return original_mkdir(path, *args, **kwargs)
        asset = {'repository': 'owner/project', 'tag': 'v1', 'name': 'tool.zip',
                 'url': self.release['assets'][0]['browser_download_url'], 'sha256': self.digest, 'size': len(self.payload)}
        with patch.object(Path, 'mkdir', synchronized_mkdir), patch.object(artifacts, '_open', side_effect=lambda _: self.response(self.payload)) as transport:
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = list(pool.map(lambda _: artifacts.download_asset(asset, cache), range(4)))
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual(transport.call_count, 1)

    def test_redirects_close_untrusted_body_without_unbounded_read(self):
        import urllib.request
        from types import SimpleNamespace
        from unittest.mock import Mock
        request = urllib.request.Request('https://github.com/owner/project/releases/download/v1/tool.zip')
        request.timeout = 30
        body = Mock()
        body.read.side_effect = AssertionError('must not drain an unbounded redirect body')
        handler = artifacts._Redirects()
        handler.parent = SimpleNamespace(open=Mock(return_value='response'))
        target = 'https://release-assets.githubusercontent.com/github-production-release-asset/123/tool.zip'
        self.assertEqual(handler.http_error_302(request, body, 302, 'redirect', {'location': target}), 'response')
        body.read.assert_not_called()
        body.close.assert_called_once()
        for method in ('http_error_301', 'http_error_303', 'http_error_307', 'http_error_308'):
            self.assertIs(getattr(type(handler), method), type(handler).http_error_302)

    def test_real_7zip_treats_at_sign_and_wildcard_names_as_literal_members(self):
        import os
        import shutil
        import subprocess
        tool = os.environ.get('DLOR_TEST_7ZZ') or shutil.which('7zz') or shutil.which('7z')
        if not tool:
            self.skipTest('set DLOR_TEST_7ZZ to verified official 7zz')
        source = self.root / 'source'
        source.mkdir()
        names = ['@literal.dll', 'wild*.dll', 'wild-other.dll', '-switch.dll']
        for name in names:
            (source / name).write_bytes(name.encode())
        archive = self.root / 'literal.7z'
        subprocess.run([tool, 'a', str(archive), '.'], cwd=source, capture_output=True, check=True)
        with patch.object(artifacts.shutil, 'which', return_value=tool):
            artifacts.extract_archive(archive, self.root / 'literal')
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / 'literal').iterdir()},
                         {name: name.encode() for name in names})


if __name__ == '__main__':
    unittest.main()
