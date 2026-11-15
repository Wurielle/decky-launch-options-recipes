"""Offline DLO-only update, native installer, cache, and game handoff tests."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

from runner_test_support import install_runner


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'recipes/decky-launch-options/scripts/auto-update.sh'
updater = types.ModuleType('dlo_auto_update')
exec(compile(SCRIPT.read_text().split("<<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0],
             str(SCRIPT), 'exec'), updater.__dict__)
REGULAR_ASSET = updater.ASSETS['regular']
STORE_ASSET = updater.ASSETS['with-store']


def plugin_zip(version='1.2.0', name='Launch Options', extras=()):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for filename, data in [
            ('Launch Options/plugin.json', json.dumps({'name': name})),
            ('Launch Options/package.json', json.dumps({'version': version})),
            ('Launch Options/main.py', '# fixture only'),
            ('Launch Options/dist/index.js', '// fixture only'),
            *extras,
        ]:
            archive.writestr(filename, data)
    return stream.getvalue()


def release_for(payload, version='1.2.0', variant='regular'):
    asset = updater.ASSETS[variant]
    return {'version': version + ('-with-store' if variant == 'with-store' else ''),
            'asset': asset, 'sha256': hashlib.sha256(payload).hexdigest(),
            'size': len(payload), 'url': f'https://github.com/Wurielle/decky-launch-options/releases/download/v{version}/{asset}'}


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='DLO cache space ')
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.payload = plugin_zip()
        self.release = release_for(self.payload)

    def fetch(self, data=None):
        return patch.object(updater, 'request', return_value=io.BytesIO(self.payload if data is None else data))

    def test_download_and_offline_cache_reuse(self):
        with self.fetch() as request:
            package = updater.cached_package(self.cache, self.release)
        self.assertEqual(package.read_bytes(), self.payload)
        request.assert_called_once_with(self.release['url'], timeout=30)
        with patch.object(updater, 'request', side_effect=OSError('offline')) as request:
            self.assertEqual(updater.cached_package(self.cache, self.release), package)
        request.assert_not_called()
        self.assertEqual(package.parent.stat().st_mode & 0o777, 0o700)

    def test_corrupt_cache_is_repaired_and_temporary_files_are_removed(self):
        with self.fetch():
            package = updater.cached_package(self.cache, self.release)
        package.write_bytes(b'broken')
        with self.fetch() as request:
            updater.cached_package(self.cache, self.release)
        request.assert_called_once()
        self.assertEqual(package.read_bytes(), self.payload)
        self.assertEqual(list(package.parent.glob('.download-*')), [])

    def test_bad_hash_bad_size_and_network_failure_are_not_published(self):
        for payload in [b'x' * self.release['size'], self.payload[:-1], self.payload + b'x']:
            with self.subTest(payload_size=len(payload)), self.fetch(payload), self.assertRaises(ValueError):
                updater.cached_package(self.cache, self.release)
            self.assertFalse((self.cache / '1.2.0' / REGULAR_ASSET).exists())
            self.assertEqual(list(self.cache.rglob('.download-*')), [])
        with patch.object(updater, 'request', side_effect=OSError('offline')), self.assertRaises(OSError):
            updater.cached_package(self.cache, self.release)
        self.assertEqual(list(self.cache.rglob('.download-*')), [])

    def test_zip_rejects_wrong_plugin_version_and_escaping_paths(self):
        cases = [plugin_zip(name='Launch Options Recipes'), plugin_zip(version='9.0.0'),
                 plugin_zip(extras=[('../other-plugin/main.py', 'bad')]),
                 plugin_zip(extras=[('Launch Options/./main.py', 'collision')]),
                 plugin_zip(extras=[('Another Plugin/main.py', 'bad')])]
        for payload in cases:
            with self.subTest(payload=hashlib.sha256(payload).hexdigest()), self.fetch(payload), self.assertRaises(ValueError):
                updater.cached_package(self.cache, release_for(payload))
        self.assertFalse((self.cache / '1.2.0' / REGULAR_ASSET).exists())

    def test_symlink_cache_is_never_used_or_replaced(self):
        directory = updater.private_directory(self.cache / '1.2.0')
        other = self.cache / 'user-file'
        other.write_bytes(self.payload)
        (directory / REGULAR_ASSET).symlink_to(other)
        with patch.object(updater, 'request') as fetch, self.assertRaisesRegex(ValueError, 'symlink'):
            updater.cached_package(self.cache, self.release)
        fetch.assert_not_called()
        self.assertEqual(other.read_bytes(), self.payload)

    def test_release_requires_stable_official_asset_and_complete_upstream_digest(self):
        metadata = {'tag_name': 'v1.2.0', 'draft': False, 'prerelease': False, 'assets': [{
            'name': REGULAR_ASSET, 'browser_download_url': self.release['url'],
            'size': self.release['size'], 'digest': 'sha256:' + self.release['sha256'],
        }]}
        with patch.object(updater, 'read_json', return_value=metadata):
            self.assertEqual(updater.latest_release(), self.release)
        for updates in [{'digest': None}, {'digest': 'sha256:abc'}, {'size': -1},
                        {'browser_download_url': 'https://example.com/other.zip'}]:
            invalid = {**metadata, 'assets': [{**metadata['assets'][0], **updates}]}
            with self.subTest(updates=updates), patch.object(updater, 'read_json', return_value=invalid), self.assertRaises(ValueError):
                updater.latest_release()
        for updates in [{'prerelease': True}, {'draft': True}, {'tag_name': 'v1.2.0-rc.1'}, {'assets': []}]:
            with patch.object(updater, 'read_json', return_value={**metadata, **updates}), self.assertRaises(ValueError):
                updater.latest_release()

    def test_each_variant_selects_its_exact_asset_digest_and_package_version(self):
        store_payload = plugin_zip(version='1.2.0-with-store')
        store = release_for(store_payload, variant='with-store')
        releases = [self.release, store]
        metadata = {'tag_name': 'v1.2.0', 'assets': [{
            'name': r['asset'], 'browser_download_url': r['url'], 'size': r['size'],
            'digest': 'sha256:' + r['sha256'],
        } for r in releases]}
        for variant, expected in zip(['regular', 'with-store'], releases):
            with self.subTest(variant=variant), patch.object(updater, 'read_json', return_value=metadata):
                self.assertEqual(updater.latest_release(variant), expected)
        metadata['assets'] = metadata['assets'][:1]
        with patch.object(updater, 'read_json', return_value=metadata), self.assertRaisesRegex(ValueError, 'with-store plugin ZIP'):
            updater.latest_release('with-store')

    def test_variant_caches_are_independent_and_reject_the_wrong_build(self):
        with self.fetch():
            regular = updater.cached_package(self.cache, self.release)
        payload = plugin_zip(version='1.2.0-with-store')
        store_release = release_for(payload, variant='with-store')
        with self.fetch(payload):
            store = updater.cached_package(self.cache, store_release)
        self.assertNotEqual(regular, store)
        self.assertEqual(regular.name, REGULAR_ASSET)
        self.assertEqual(store.name, STORE_ASSET)
        with patch.object(updater, 'request', side_effect=OSError('offline')) as fetch:
            self.assertEqual(updater.cached_package(self.cache, self.release), regular)
            self.assertEqual(updater.cached_package(self.cache, store_release), store)
        fetch.assert_not_called()
        with self.fetch(self.payload), self.assertRaisesRegex(ValueError, 'name/version mismatch'):
            updater.cached_package(self.cache, release_for(self.payload, variant='with-store'))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.release = release_for(plugin_zip())
        self.frontend = Mock()

    def test_only_a_newer_installed_enabled_dlo_is_updated(self):
        for installed in [None, {'name': 'Launch Options', 'version': '1.0.0', 'disabled': True},
                          {'name': 'Launch Options', 'version': '1.2.0'},
                          {'name': 'Launch Options', 'version': '2.0.0'}]:
            self.frontend.reset_mock()
            self.frontend.evaluate.return_value = installed
            with self.subTest(installed=installed), patch.object(updater, 'latest_release', return_value=self.release), \
                    patch.object(updater, 'cached_package') as package:
                updater.update(self.home, self.frontend)
            package.assert_not_called()
            self.assertEqual(self.frontend.evaluate.call_count, 1)
        self.frontend.evaluate.side_effect = [{'name': 'Launch Options', 'version': '1.1.0'}, {'status': 'updated'}]
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'cached_package', return_value=self.home / REGULAR_ASSET), \
                patch.object(updater, 'unique_installation'):
            updater.update(self.home, self.frontend)
        code = self.frontend.evaluate.call_args.args[0]
        self.assertIn('"name": "Launch Options"', code)
        self.assertNotIn('Launch Options Recipes', code)
        self.assertNotIn('restart_webhelper', code)

    def test_unknown_version_network_and_failed_installer_do_not_retry_install(self):
        self.frontend.evaluate.return_value = {'name': 'Launch Options', 'version': 'custom'}
        with patch.object(updater, 'latest_release') as release, self.assertRaises(ValueError):
            updater.update(self.home, self.frontend)
        release.assert_not_called()
        self.frontend.evaluate.return_value = {'name': 'Launch Options', 'version': '1.0.0'}
        with patch.object(updater, 'latest_release', side_effect=OSError('offline')), self.assertRaises(OSError):
            updater.update(self.home, self.frontend)
        self.frontend.reset_mock()
        self.frontend.evaluate.side_effect = [{'name': 'Launch Options', 'version': '1.0.0'}, ConnectionError('interrupted')]
        with patch.object(updater, 'latest_release', return_value=self.release), \
                patch.object(updater, 'cached_package', return_value=self.home / REGULAR_ASSET), \
                patch.object(updater, 'unique_installation'), self.assertRaises(ConnectionError):
            updater.update(self.home, self.frontend)
        self.assertEqual(self.frontend.evaluate.call_count, 2)

    def test_semver_comparison_does_not_use_lexicographic_order_or_downgrade(self):
        self.assertGreater(updater.version('1.16.0'), updater.version('1.9.0'))
        self.assertGreater(updater.version('1.2.0'), updater.version('1.2.0-rc.1'))
        self.assertGreater(updater.version('2.0.0-rc.1'), updater.version('1.2.0'))
        self.assertEqual(updater.version('v1.2.0+build'), updater.version('1.2.0'))
        self.assertEqual(updater.version('1.2.0-with-store'), updater.version('1.2.0'))

    def test_switch_variants_at_same_release_and_never_downgrade_a_newer_release(self):
        cases = [
            ('1.2.0', 'with-store', True),
            ('1.2.0-with-store', 'regular', True),
            ('1.1.0-with-store', 'with-store', True),
            ('1.1.0-with-store', 'regular', True),
            ('1.1.0', 'with-store', True),
            ('1.2.0-with-store', 'with-store', False),
            ('1.2.0', 'regular', False),
            ('1.3.0-with-store', 'regular', False),
            ('1.3.0', 'with-store', False),
        ]
        for installed, variant, expected in cases:
            self.frontend.reset_mock()
            self.frontend.evaluate.side_effect = [{'name': 'Launch Options', 'version': installed}, {'status': 'updated'}]
            target_version = '1.2.0-with-store' if variant == 'with-store' else '1.2.0'
            release = release_for(plugin_zip(version=target_version), variant=variant)
            with self.subTest(installed=installed, variant=variant), \
                    patch.object(updater, 'latest_release', return_value=release) as latest, \
                    patch.object(updater, 'cached_package', return_value=self.home / release['asset']) as package, \
                    patch.object(updater, 'unique_installation'):
                updater.update(self.home, self.frontend, variant)
            latest.assert_called_once_with(variant)
            self.assertEqual(package.called, expected)
            if expected:
                code = self.frontend.evaluate.call_args.args[0]
                self.assertIn('"version": ' + json.dumps(target_version), code)
                self.assertIn(release['asset'], code)

    def test_unknown_variant_fails_before_connection_or_release_lookup(self):
        with patch.dict(os.environ, DLO_UPDATE_VARIANT='unknown'), \
                patch.object(updater, 'connect_frontend') as connect, \
                patch.object(updater, 'latest_release') as latest, self.assertRaises(ValueError):
            updater.main()
        connect.assert_not_called()
        latest.assert_not_called()

    def test_duplicate_dlo_folders_abort_before_installation(self):
        for folder in ['Launch Options', 'decky-launch-options']:
            directory = self.home / 'homebrew/plugins' / folder
            directory.mkdir(parents=True)
            (directory / 'plugin.json').write_text('{"name":"Launch Options"}')
        with patch.object(updater.Path, 'home', return_value=self.home), self.assertRaisesRegex(RuntimeError, 'Multiple DLO'):
            updater.unique_installation()

    def test_concurrent_launch_does_not_connect_or_download(self):
        cache = updater.private_directory(self.home / 'cache')
        with (cache / 'update.lock').open('w') as lock:
            updater.fcntl.flock(lock, updater.fcntl.LOCK_EX | updater.fcntl.LOCK_NB)
            with patch.dict(os.environ, DLO_UPDATE_CACHE_DIR=str(cache)), patch.object(updater, 'connect_frontend') as connect:
                updater.main()
        connect.assert_not_called()


JS_FIXTURE = r'''
const fs = require('node:fs'), vm = require('node:vm');
const {code, mode, currentVersion} = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [], prompts = [], events = new Map();
let current = mode === 'race' ? '2.0.0' : currentVersion;
let order = ['Other Plugin', 'Launch Options'];
let pending;
const original = (...args) => prompts.push(args[0]);
events.set('loader/add_plugin_install_prompt', new Set([original]));
const loader = {plugins: [{name:'Launch Options',version:'1.0.0'}], async importPlugin(name,version) {
    calls.push(['frontend/import',name,version]);
    this.plugins = [{name,version,onDismount(){}}];
}};
const backend = {
    eventListeners: events,
    addEventListener(event, handler) { if (!events.has(event)) events.set(event,new Set()); events.get(event).add(handler); },
    removeEventListener(event, handler) { events.get(event)?.delete(handler); },
    async call(route, ...args) {
        calls.push([route,...args]);
        if (route === 'loader/get_plugins') return [{name:'Launch Options',version:current,load_type:1,disabled:false}];
        if (route === 'utilities/settings/get') return [...order];
        if (route === 'utilities/settings/set') { order=args[1]; return; }
        if (route === 'utilities/install_plugin') {
            pending = args;
            for (const handler of events.get('loader/add_plugin_install_prompt')) {
                handler('Other Plugin','9.0.0','unrelated-id','other-hash',2);
                handler(args[1],args[2],'wrong-hash-id','wrong-hash',2);
                handler(args[1],args[2],'our-id',args[3],2);
            }
            return;
        }
        if (route === 'utilities/confirm_plugin_install') {
            if (args[0] !== 'our-id') throw Error('Confirmed someone else!');
            if (mode === 'failure') throw Error('fixture install failure');
            if (mode === 'pending') await new Promise(resolve => setTimeout(resolve,30));
            if (mode !== 'mismatch') current=pending[2];
            order=['Launch Options','Other Plugin'];
            return;
        }
        throw Error('Unexpected route '+route);
    },
};
const context={window:{DeckyBackend:backend,DeckyPluginLoader:loader},console,
    setTimeout:(fn,ms)=>setTimeout(fn,mode==='pending' && ms>=10000 ? 2 : ms),clearTimeout,Error,Promise};
if(mode==='unsupported') delete backend.addEventListener;
(async()=>{
    let result,error;
    try { result=await vm.runInNewContext(code,context); } catch(e) { error=e.message; }
    const busyInitially=context.window.dlorDloAutoUpdateRunning;
    if(mode==='pending') await new Promise(resolve=>setTimeout(resolve,70));
    console.log(JSON.stringify({result,error,calls,prompts,order,busyInitially,
        restored:events.get('loader/add_plugin_install_prompt').size===1 && events.get('loader/add_plugin_install_prompt').has(original),
        busy:context.window.dlorDloAutoUpdateRunning}));
})().catch(e=>{console.error(e);process.exitCode=1});
'''


class InstallerJavascriptTests(unittest.TestCase):
    def run_fixture(self, mode, variant='regular', current='1.0.0'):
        version = '1.2.0-with-store' if variant == 'with-store' else '1.2.0'
        release = release_for(plugin_zip(version=version), variant=variant)
        code = updater.install_code(Path('/private cache/1.2.0') / release['asset'], release, current)
        result = subprocess.run(['node', '-e', JS_FIXTURE], input=json.dumps({'code': code, 'mode': mode, 'currentVersion': current}),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_native_install_confirm_frontend_refresh_and_other_prompts(self):
        result = self.run_fixture('success')
        self.assertEqual(result['result'], {'status': 'updated', 'version': '1.2.0'})
        installs = [c for c in result['calls'] if c[0] == 'utilities/install_plugin']
        self.assertEqual(len(installs), 1)
        self.assertEqual(installs[0][1], 'file:///private cache/1.2.0/decky-launch-options.zip')
        self.assertEqual(installs[0][2:4], ['Launch Options', '1.2.0'])
        self.assertEqual([c for c in result['calls'] if c[0] == 'utilities/confirm_plugin_install'],
                         [['utilities/confirm_plugin_install', 'our-id']])
        self.assertIn(['frontend/import', 'Launch Options', '1.2.0'], result['calls'])
        self.assertEqual(result['prompts'], ['Other Plugin', 'Launch Options'])
        self.assertEqual(result['order'], ['Other Plugin', 'Launch Options'])
        self.assertTrue(result['restored'])
        self.assertFalse(result['busy'])

    def test_same_release_variant_switch_installs_and_refreshes_selected_build(self):
        for variant, current in [('regular', '1.2.0-with-store'), ('with-store', '1.2.0')]:
            with self.subTest(variant=variant):
                result = self.run_fixture('success', variant, current)
                target = '1.2.0-with-store' if variant == 'with-store' else '1.2.0'
                self.assertEqual(result['result'], {'status': 'updated', 'version': target})
                install, = [c for c in result['calls'] if c[0] == 'utilities/install_plugin']
                self.assertEqual(install[1], 'file:///private cache/1.2.0/' + updater.ASSETS[variant])
                self.assertEqual(install[2:4], ['Launch Options', target])
                self.assertIn(['frontend/import', 'Launch Options', target], result['calls'])
                self.assertTrue(result['restored'])

    def test_install_failure_restores_handlers_and_does_not_refresh_or_retry(self):
        for mode in ['failure', 'mismatch']:
            with self.subTest(mode=mode):
                result = self.run_fixture(mode)
                self.assertIn('failure' if mode == 'failure' else 'expected backend', result['error'])
                self.assertTrue(result['restored'])
                self.assertFalse(result['busy'])
                self.assertFalse(any(c[0] == 'frontend/import' for c in result['calls']))
                self.assertEqual(len([c for c in result['calls'] if c[0] == 'utilities/install_plugin']), 1)

    def test_concurrent_version_change_and_unsupported_api_do_not_install(self):
        for mode in ['race', 'unsupported']:
            with self.subTest(mode=mode):
                result = self.run_fixture(mode)
                self.assertFalse(any(c[0] == 'utilities/install_plugin' for c in result['calls']))
                self.assertTrue(result['restored'])
                if mode == 'race':
                    self.assertEqual(result['result']['status'], 'skipped')
                else:
                    self.assertIn('Unsupported', result['error'])

    def test_timeout_keeps_guard_until_native_install_and_order_restoration_finish(self):
        result = self.run_fixture('pending')
        self.assertIn('timed out', result['error'])
        self.assertTrue(result['busyInitially'])
        self.assertFalse(result['busy'])
        self.assertEqual(result['order'], ['Other Plugin', 'Launch Options'])
        self.assertEqual(len([c for c in result['calls'] if c[0] == 'utilities/install_plugin']), 1)


class ProtocolTests(unittest.TestCase):
    def test_real_upgrade_handshake_and_evaluate_reply(self):
        client, server = socket.socketpair()
        self.addCleanup(server.close)
        errors = []
        def peer():
            try:
                with server.makefile('rb') as stream:
                    self.assertEqual(stream.readline(), b'GET /devtools/page/fixture HTTP/1.1\r\n')
                    headers = {}
                    while True:
                        line = stream.readline()
                        if line == b'\r\n':
                            break
                        key, value = line.decode().split(':', 1)
                        headers[key.lower()] = value.strip()
                    accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] +
                        '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                    server.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                                    'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode())
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=peer)
        worker.start()
        with patch.object(updater.socket, 'create_connection', return_value=client):
            cdp = updater.CDP('ws://127.0.0.1:8080/devtools/page/fixture')
        self.addCleanup(cdp.close)
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        if errors:
            raise errors[0]

    def test_masked_client_frames_and_fragmented_reply_with_ping(self):
        client, server = socket.socketpair()
        self.addCleanup(server.close)
        cdp = updater.CDP.__new__(updater.CDP)
        cdp.sock, cdp.stream, cdp.sequence = client, client.makefile('rb'), 0
        self.addCleanup(cdp.close)
        client.settimeout(3)
        errors = []

        def peer():
            try:
                stream = server.makefile('rb')
                with stream:
                    first, second = stream.read(2)
                    self.assertEqual(first, 0x81)
                    self.assertTrue(second & 0x80)
                    size = second & 127
                    if size == 126:
                        size = struct.unpack('!H', stream.read(2))[0]
                    mask = stream.read(4)
                    data = stream.read(size)
                    message = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
                    self.assertEqual(message['method'], 'Runtime.evaluate')
                    result = json.dumps({'id': message['id'], 'result': {'result': {'value': {'ok': True}}}}).encode()
                    half = len(result) // 2
                    server.sendall(bytes([0x01, half]) + result[:half] + b'\x89\x01x'
                                   + bytes([0x80, len(result) - half]) + result[half:])
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=peer)
        worker.start()
        self.assertEqual(cdp.evaluate('x' * 200), {'ok': True})
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        if errors:
            raise errors[0]

    def test_debugger_socket_must_be_loopback_port_8080(self):
        for url in ['ws://example.com:8080/devtools/page/1', 'wss://127.0.0.1:8080/x',
                    'ws://127.0.0.1:1337/ws', 'ws://user:pass@localhost:8080/x']:
            with self.subTest(url=url), patch.object(updater.socket, 'create_connection') as connect, self.assertRaises(ValueError):
                updater.CDP(url)
            connect.assert_not_called()


class LauncherTests(unittest.TestCase):
    def test_helper_failure_logs_but_preserves_game_arguments_and_environment(self):
        with tempfile.TemporaryDirectory(prefix='DLO game handoff ') as temp:
            home = Path(temp)
            install_runner(home)
            binary = home / 'bin'
            binary.mkdir()
            curl = binary / 'curl'
            curl.write_text('#!/usr/bin/env python3\nimport shutil,sys\n'
                            'shutil.copyfile(' + repr(str(SCRIPT)) + ',sys.argv[sys.argv.index("--output")+1])\n')
            curl.chmod(0o755)
            python = binary / 'python3'
            # A deterministic missing-CEF failure; the runner/downloader use the
            # real Python via an explicit shebang to avoid launching anything.
            curl.write_text(curl.read_text().replace('#!/usr/bin/env python3', '#!' + sys.executable))
            python.write_text('#!/bin/bash\necho "fixture: CEF unavailable" >&2\nexit 7\n')
            python.chmod(0o755)
            game = home / 'game with spaces.py'
            output = home / 'game-result.json'
            game.write_text('import json,os,sys\nfrom pathlib import Path\n'
                            'Path(sys.argv[1]).write_text(json.dumps({"args":sys.argv[2:],"env":os.environ["GAME_ONLY"]}))\n'
                            'sys.exit(23)\n')
            env = {**os.environ, 'HOME': str(home), 'PATH': str(binary) + ':' + os.environ['PATH'],
                   'GAME_ONLY': 'original', 'STEAM_RUNTIME': '/fixture steam runtime',
                   'SYSTEM_PATH': str(binary) + ':' + os.environ['PATH'], 'SYSTEM_LD_LIBRARY_PATH': ''}
            command = [str(home / '.dlor/run'), 'decky-launch-options', 'auto-update', 'a' * 40,
                       '--', sys.executable, str(game), str(output), 'space argument', 'quote"argument', '日本語']
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertEqual(json.loads(output.read_text()), {'args': ['space argument', 'quote"argument', '日本語'], 'env': 'original'})
            logs = list((home / '.dlor/logs/decky-launch-options/auto-update').glob('*.log'))
            self.assertEqual(len(logs), 1)
            self.assertIn('fixture: CEF unavailable', logs[0].read_text())
            self.assertIn('exit status 7', logs[0].read_text())

    def test_successful_helper_cleans_steam_environment_and_logs_both_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            binary = home / 'bin'
            binary.mkdir()
            python = binary / 'python3'
            python.write_text('#!/bin/bash\n'
                              '[[ -z "${LD_PRELOAD-}" && -z "${STEAM_RUNTIME-}" && "$LD_LIBRARY_PATH" == /host-libraries ]] || exit 9\n'
                              'echo helper-success\necho helper-diagnostic >&2\n')
            python.chmod(0o755)
            env = {**os.environ, 'HOME': str(home), 'PATH': os.environ['PATH'],
                   'SYSTEM_PATH': str(binary) + ':' + os.environ['PATH'], 'STEAM_RUNTIME': '/steam-runtime',
                   'SYSTEM_LD_LIBRARY_PATH': '/host-libraries', 'LD_LIBRARY_PATH': '/steam-libraries', 'LD_PRELOAD': ''}
            result = subprocess.run(['bash', '-s'], input=SCRIPT.read_text(), env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            log, = (home / '.dlor/logs/decky-launch-options/auto-update').glob('*.log')
            for expected in ['helper-success', 'helper-diagnostic', 'exit status 0']:
                self.assertIn(expected, log.read_text())

    def test_logging_unavailable_does_not_prevent_help_or_helper_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.dlor').write_text('logging unavailable')
            result = subprocess.run(['bash', '-s', '--', '--help'], input=SCRIPT.read_text(),
                                    env={**os.environ, 'HOME': str(home)}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Usage:', result.stdout)
            self.assertIn('could not enable logging', result.stderr)
            binary = home / 'bin'
            binary.mkdir()
            python = binary / 'python3'
            python.write_text('#!/bin/bash\necho helper-ran\n')
            python.chmod(0o755)
            result = subprocess.run(['bash', '-s'], input=SCRIPT.read_text(),
                                    env={**os.environ, 'HOME': str(home), 'PATH': str(binary) + ':' + os.environ['PATH']},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('helper-ran', result.stdout)

    def test_dropdown_round_trips_through_real_dlo_parser(self):
        compile_result = subprocess.run(['pnpm', 'exec', 'tsc', '-p', 'tsconfig.recipes.json'], cwd=ROOT,
                                        capture_output=True, text=True, timeout=60)
        self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
        result = subprocess.run(['node', '--input-type=module', '-e',
                                 "console.log(JSON.stringify((await import('./.generated/recipes-build/recipes/decky-launch-options/index.js')).default))"],
                                cwd=ROOT, env={**os.environ, 'RECIPE_REPOSITORY_OWNER': 'Wurielle',
                                               'RECIPE_REPOSITORY_NAME': 'decky-launch-options-recipes', 'RECIPE_COMMIT_SHA': 'a' * 40},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        options = json.loads(result.stdout)['launchOptions']
        self.assertEqual([o['valueName'] for o in options], ['None', 'Regular', 'With store'])
        self.assertEqual([o['id'] for o in options], ['decky-launch-options-auto-update-' + v for v in ['none', 'regular', 'with-store']])
        self.assertEqual([o['valueName'] for o in options if o.get('fallbackValue')], ['None'])
        for option, variant in zip(options, [None, 'regular', 'with-store']):
            self.assertFalse(option['enableGlobally'])
            self.assertEqual(option['off'], '')
            self.assertEqual(option['valueId'], 'decky-launch-options-auto-update')
            expected = '' if variant is None else ('DLO_UPDATE_VARIANT="' + variant + '" ~/.dlor/run decky-launch-options auto-update ' + 'a' * 40 + ' -- %command%')
            self.assertEqual(option['on'], expected)
        consumer = Path(os.environ.get('DLO_CONSUMER_SOURCE', ROOT.parent / 'decky-launch-options'))
        if not (consumer / 'run.py').is_file():
            self.skipTest('Set DLO_CONSUMER_SOURCE to run parser compatibility checks.')
        source = types.ModuleType('dlo_consumer')
        with patch.dict(sys.modules, shared=types.SimpleNamespace(SETTINGS_FOLDER_PATH='/unused', SETTINGS_PATH='/unused')):
            exec(compile((consumer / 'run.py').read_text(), str(consumer / 'run.py'), 'exec'), source.__dict__)
        for option, variant in zip(options, [None, 'regular', 'with-store']):
            parsed = source.parse_launch_option(option['on'])
            self.assertEqual(parsed['prefix'], [] if variant is None else ['~/.dlor/run', 'decky-launch-options', 'auto-update', 'a' * 40, '--'])
            self.assertEqual(parsed['suffix'], [])
            self.assertEqual(parsed['env_vars'], {} if variant is None else {'DLO_UPDATE_VARIANT': variant})
            self.assertEqual(source.parse_launch_option(option['off'])['prefix'], [])
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            install_runner(home)
            other = {'id': 'other-helper', 'on': 'echo other %command%', 'off': '', 'enableGlobally': True, 'priority': 0}
            for selected, variant in [(None, None), (options[0], None), (options[1], 'regular'), (options[2], 'with-store')]:
                state = {} if selected is None else {selected['id']: True}
                settings = {'launchOptions': [*options, other], 'profiles': {'123': {'state': state}}}
                with patch.dict(os.environ, HOME=str(home)), patch.object(sys, 'argv', ['run.py', '/bin/echo', 'game']):
                    final, variables = source.get_final_args_details(settings, '123')
                self.assertEqual(variables, {} if variant is None else {'DLO_UPDATE_VARIANT': variant})
                if variant is not None:
                    self.assertEqual(final[:2], ['echo', 'other'])
                    self.assertIn(str(home / '.dlor/run'), final)
                else:
                    self.assertNotIn(str(home / '.dlor/run'), final)


if __name__ == '__main__':
    unittest.main()
