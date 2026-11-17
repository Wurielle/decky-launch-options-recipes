"""Offline window ownership, sizing, logging, and runner-continuation checks."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from runner_test_support import install_runner


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'recipes/non-steam/scripts/resize-window.sh'
window = types.ModuleType('non_steam_window')
exec(compile(SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0], str(SCRIPT), 'exec'), window.__dict__)


class WindowTests(unittest.TestCase):
    def test_fullscreen_and_explicit_sizes_and_invalid_input(self):
        self.assertEqual(window.dimensions('fullscreen', (3840, 2160)), (3840, 2160))
        self.assertEqual(window.dimensions('1920x1080', (3840, 2160)), (1920, 1080))
        for value in ['', '0x1080', '1920x0', '20000x1080', '1920x1080; touch /tmp/no']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                window.dimensions(value, (3840, 2160))

    def test_real_process_ownership_does_not_accept_other_app(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'],
                                   env={**os.environ, 'SteamAppId': '3433671360'})
        try:
            self.assertTrue(window.belongs_to_app(process.pid, '3433671360'))
            self.assertFalse(window.belongs_to_app(process.pid, '2956561548'))
            self.assertFalse(window.belongs_to_app(999999999, '3433671360'))
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_monitor_resizes_only_owned_main_window(self):
        x11 = Mock()
        x11.window_pid.side_effect = lambda wid: {'0x1': 1, '0x2': 2, '0x3': 3}[wid]
        x11.screen_size.return_value = (3840, 2160)
        with patch.object(window, 'windows', return_value=['0x1', '0x2', '0x3']), \
             patch.object(window, 'belongs_to_app', side_effect=lambda pid, _: pid in [2, 3]), \
             patch.object(window, 'main_window', side_effect=lambda wid: wid == '0x3'), \
             patch.object(window.subprocess, 'run') as run, patch.object(window.time, 'sleep'):
            window.monitor(x11, '3433671360', 'fullscreen', window.time.monotonic() + 30)
        self.assertEqual(len(run.call_args_list), 9)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][2], '0x3')
        self.assertEqual(run.call_args.args[0][-1], '0,0,0,3840,2160')

    def test_monitor_times_out_without_touching_unrelated_windows(self):
        x11 = Mock()
        x11.window_pid.return_value = 1
        with patch.object(window, 'windows', return_value=['0x1']), \
             patch.object(window, 'belongs_to_app', return_value=False), \
             patch.object(window.subprocess, 'run') as run, \
             patch.object(window.time, 'monotonic', side_effect=[0, 31]), \
             patch.object(window.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'No matching app window'):
                window.monitor(x11, '3433671360', '1920x1080', 30)
        run.assert_not_called()

    def test_dialogs_and_transient_windows_are_not_main_windows(self):
        for properties in ['_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_DIALOG',
                           'WM_TRANSIENT_FOR(WINDOW): window id # 0x123',
                           '_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_SPLASH']:
            with patch.object(window.subprocess, 'run', return_value=types.SimpleNamespace(stdout=properties)):
                self.assertFalse(window.main_window('0x1'))
        with patch.object(window.subprocess, 'run', return_value=types.SimpleNamespace(stdout='_NET_WM_WINDOW_TYPE_NORMAL')):
            self.assertTrue(window.main_window('0x1'))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='non-steam tools ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = b'#!/bin/sh\necho fixture wmctrl\n'
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w:xz') as archive:
            for name, content in [('./usr/bin/wmctrl', self.binary),
                                  ('./usr/share/doc/wmctrl/copyright', b'fixture license')]:
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        data = payload.getvalue()
        header = f'{"data.tar.xz/":<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n'.encode()
        self.package = b'!<arch>\n' + header + data + (b'\n' if len(data) % 2 else b'')
        for context in [patch.dict(window.os.environ, DLOR_NON_STEAM_CACHE_DIR=str(self.root)),
                        patch.object(window.shutil, 'which', return_value=None),
                        patch.object(window.platform, 'machine', return_value='x86_64'),
                        patch.dict(window.WMCTRL_PACKAGES, {'x86_64': ('amd64',
                            hashlib.sha256(self.package).hexdigest(), hashlib.sha256(self.binary).hexdigest())})]:
            context.start()
            self.addCleanup(context.stop)
        self.cache = self.root / 'wmctrl' / window.WMCTRL_VERSION / 'amd64'
        self.asset = self.cache / f'wmctrl_{window.WMCTRL_VERSION}_amd64.deb'

    def download(self, data=None):
        return patch.object(window.urllib.request, 'urlopen', return_value=io.BytesIO(
            self.package if data is None else data))

    def test_system_command_avoids_download_or_cache(self):
        with patch.object(window.shutil, 'which', return_value='/usr/bin/wmctrl'), \
             patch.object(window.urllib.request, 'urlopen') as fetch:
            self.assertEqual(window.ensure_wmctrl(), '/usr/bin/wmctrl')
        fetch.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_cold_download_and_offline_binary_reuse(self):
        with self.download() as fetch:
            binary = Path(window.ensure_wmctrl())
        self.assertEqual(binary.read_bytes(), self.binary)
        self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.cache / 'copyright').read_bytes(), b'fixture license')
        self.assertEqual(self.asset.read_bytes(), self.package)
        self.assertTrue(fetch.call_args.args[0].startswith('https://deb.debian.org/'))
        self.asset.unlink()
        with patch.object(window.urllib.request, 'urlopen', side_effect=OSError('offline')) as fetch:
            self.assertEqual(window.ensure_wmctrl(), str(binary))
        fetch.assert_not_called()

    def test_corrupt_binary_recovers_from_verified_archive_without_download(self):
        with self.download():
            binary = Path(window.ensure_wmctrl())
        binary.write_text('corrupt')
        with patch.object(window.urllib.request, 'urlopen', side_effect=OSError('offline')) as fetch:
            window.ensure_wmctrl()
        fetch.assert_not_called()
        self.assertEqual(binary.read_bytes(), self.binary)

    def test_corrupt_archive_is_redownloaded(self):
        self.cache.mkdir(parents=True)
        self.asset.write_text('bad archive')
        with self.download() as fetch:
            self.assertEqual(Path(window.ensure_wmctrl()).read_bytes(), self.binary)
        fetch.assert_called_once()

    def test_bad_download_is_not_promoted_and_staging_is_cleaned(self):
        with self.download(b'bad checksum'), self.assertRaisesRegex(ValueError, 'SHA-256'):
            window.ensure_wmctrl()
        self.assertFalse(self.asset.exists())
        self.assertFalse((self.cache / 'wmctrl').exists())
        self.assertEqual(list(self.cache.glob('.install-*')), [])

    def test_network_error_cleans_staging(self):
        with patch.object(window.urllib.request, 'urlopen', side_effect=OSError('offline')), \
             self.assertRaisesRegex(OSError, 'offline'):
            window.ensure_wmctrl()
        self.assertEqual(list(self.cache.glob('.install-*')), [])
        self.assertFalse((self.cache / 'wmctrl').exists())

    def test_unsupported_architecture_leaves_download_untouched(self):
        with patch.object(window.platform, 'machine', return_value='unknown'), \
             patch.object(window.urllib.request, 'urlopen') as fetch, \
             self.assertRaisesRegex(RuntimeError, 'unsupported architecture'):
            window.ensure_wmctrl()
        fetch.assert_not_called()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='non-steam runner ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': str(self.bin) + ':' + os.environ['PATH']}
        self.env['SYSTEM_PATH'] = self.env['PATH']

    def tool(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\n' + body)
        path.chmod(0o755)

    def help(self):
        return subprocess.run(['bash', str(SCRIPT), '--help'], env=self.env, capture_output=True, text=True, timeout=10)

    def test_help_log_retention_preserves_unrelated_entries(self):
        logs = self.home / '.dlor/logs/non-steam/resize-window'
        logs.mkdir(parents=True)
        for index in range(14):
            (logs / f'2000-{index:02}.log').write_text('old')
        outside = self.home / 'outside.log'
        outside.write_text('keep')
        (logs / '2000-link.log').symlink_to(outside)
        (logs / 'keep.txt').write_text('keep')
        (logs / 'keep.log').mkdir()
        result = self.help()
        self.assertEqual(result.returncode, 0, result.stderr)
        regular = [p for p in logs.glob('*.log') if p.is_file() and not p.is_symlink()]
        self.assertEqual(len(regular), 10)
        self.assertTrue((logs / '2000-link.log').is_symlink())
        self.assertEqual(outside.read_text(), 'keep')
        self.assertTrue((logs / 'keep.log').is_dir())
        self.assertTrue((logs / 'keep.txt').exists())

    def test_help_survives_unavailable_logging(self):
        (self.home / '.dlor').mkdir()
        (self.home / '.dlor/logs').write_text('blocked')
        result = self.help()
        self.assertEqual(result.returncode, 0)
        self.assertIn('Usage:', result.stdout)

    def test_runner_keeps_app_arguments_environment_and_exit_status_on_helper_failure(self):
        install_runner(self.home)
        self.tool('curl', 'while [[ "$1" != --output ]]; do shift; done\ncat "$FIXTURE_SCRIPT" > "$2"\n')
        for tool in ['wmctrl', 'xprop', 'xwininfo']:
            self.tool(tool, 'exit 0\n')
        self.tool('python3', '[[ -z "${LD_PRELOAD:-}" && -z "${STEAM_RUNTIME:-}" && -z "${LD_LIBRARY_PATH:-}" ]] || exit 99\necho "fixture host failure" >&2\nexit 17\n')
        self.env.update(FIXTURE_SCRIPT=str(SCRIPT), STEAM_RUNTIME='/fixture/runtime',
                        LD_LIBRARY_PATH='/fixture/steam-libs', SYSTEM_LD_LIBRARY_PATH='',
                        SteamAppId='3433671360', DLOR_NON_STEAM_APP_SIZE='fullscreen')
        command = [str(self.home / '.dlor/run'), 'non-steam', 'resize-window', '1' * 40, '--',
                   '/bin/bash', '-c', 'printf "%s|%s|%s" "$1" "$STEAM_RUNTIME" "$LD_LIBRARY_PATH"; exit 37',
                   '--', 'argument with spaces and $literal']
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertIn('argument with spaces and $literal|/fixture/runtime|/fixture/steam-libs', result.stdout)
        self.assertIn('Recipe helper failed (exit 17)', result.stderr)
        log = next((self.home / '.dlor/logs/non-steam/resize-window').glob('*.log')).read_text()
        self.assertIn('fixture host failure', log)
        self.assertIn('finished with exit status 17', log)


if __name__ == '__main__':
    unittest.main()
