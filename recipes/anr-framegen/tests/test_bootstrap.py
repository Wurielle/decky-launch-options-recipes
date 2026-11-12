"""Physical entrypoint and authenticated bundle tests with bounded local transport."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parents[1]
SCRIPTS = HERE / 'scripts'
REVISION = 'bcf6b831e1439ddc4025b8819c68d641ef7174e4'
TRANSPORT = '''#!/bin/bash
printf '%s\\n' "${@: -1}" >> "$ANR_TRANSPORT_LOG"
output=''
while (( $# )); do
  if [[ $1 == -o ]]; then output=$2; shift 2; else url=$1; shift; fi
done
case "$url" in
  */downloads.json)
    if [[ ${ANR_CORRUPT_SOURCE:-} == manifest ]]; then printf 'bad json' > "$output"; else cp "$ANR_FIXTURE_SCRIPTS/downloads.json" "$output"; fi ;;
  */loader.py)
    if [[ ${ANR_CORRUPT_SOURCE:-} == loader ]]; then printf 'raise RuntimeError("unverified code executed")' > "$output"; else cp "$ANR_FIXTURE_SCRIPTS/loader.py" "$output"; fi ;;
  */anr-fg-V.B14-addon.zip)
    [[ ${ANR_FAIL_PAYLOAD:-} != 1 ]] || exit 28
    if [[ ${ANR_BLOCK_PAYLOAD:-} == 1 ]]; then printf '%s' "$$" > "$ANR_CURL_PID"; exec sleep 180; fi
    cp "$ANR_TEST_ARCHIVE" "$output" ;;
  *) exit 87 ;;
esac
'''


class Bootstrap(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        scripts = root / 'scripts'
        shutil.copytree(SCRIPTS, scripts)
        subprocess.run([sys.executable, '-I', '-B', str(scripts / 'update-source-hashes.py'), '--bundle-revision', REVISION], check=True, capture_output=True)
        home, game, bins = root / 'home', root / 'Game ü', root / 'bin'
        home.mkdir(); game.mkdir(); bins.mkdir()
        original = b'[FrameGen]\nFGInput=auto\nFGNvngxReplacement=auto\n'
        (game / 'OptiScaler.ini').write_bytes(original)
        (game / 'OptiScaler.ini').chmod(0o640)
        (bins / 'curl').write_text(TRANSPORT)
        (bins / 'curl').chmod(0o755)
        (bins / 'python3').write_text('#!/bin/bash\numask >> "$ANR_MASK_LOG"\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        (bins / 'python3').chmod(0o755)
        env = dict(os.environ, HOME=str(home), PATH=str(bins) + ':' + os.environ['PATH'],
                   ANR_TRANSPORT_LOG=str(root / 'transport.log'), ANR_MASK_LOG=str(root / 'mask.log'),
                   ANR_CURL_PID=str(root / 'curl.pid'), ANR_FIXTURE_SCRIPTS=str(scripts),
                   ANR_TEST_ARCHIVE=os.environ.get('ANR_TEST_ARCHIVE', str(Path(os.environ['TMPDIR']) / 'anr-fg-V.B14-addon.zip')))
        return root, scripts, home, game, env

    def invoke(self, scripts, game, env, action='install', check=True):
        result = subprocess.run(['bash', '-c', 'umask 027; bash "$1" "$2"', '--', str(scripts / (action + '.sh')), str(game)],
                                env=env, capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_shell_cold_warm_off_runs_verified_loader(self):
        root, scripts, home, game, env = self.fixture()
        original = (game / 'OptiScaler.ini').read_bytes()
        for action in ('install', 'install', 'uninstall', 'uninstall'):
            self.invoke(scripts, game, env, action)
            if action == 'install':
                self.assertTrue((game / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll').is_file())
        self.assertEqual((game / 'OptiScaler.ini').read_bytes(), original)
        self.assertEqual((game / 'OptiScaler.ini').stat().st_mode & 0o777, 0o640)
        self.assertEqual((root / 'mask.log').read_text().splitlines(), ['0027'] * 4)
        urls = (root / 'transport.log').read_text().splitlines()
        self.assertEqual(len(urls), 3, urls)
        self.assertEqual(len(list((home / '.dlor/logs/anr-framegen/install').glob('*.log'))), 2)
        self.assertFalse(list(home.rglob('.loader.*')))

    def test_corrupt_source_download_never_executes_python(self):
        for corruption in ('manifest', 'loader'):
            with self.subTest(corruption=corruption):
                root, scripts, home, game, env = self.fixture()
                env['ANR_CORRUPT_SOURCE'] = corruption
                original = (game / 'OptiScaler.ini').read_bytes()
                result = self.invoke(scripts, game, env, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('checksum mismatch', result.stdout + result.stderr)
                self.assertFalse((root / 'mask.log').exists())
                self.assertEqual((game / 'OptiScaler.ini').read_bytes(), original)
                self.assertFalse((game / 'custom').exists())
                self.assertFalse(list(home.rglob('.loader.*')))

    def test_corrupt_cached_source_is_reacquired(self):
        root, scripts, home, game, env = self.fixture()
        self.invoke(scripts, game, env)
        cache = home / '.dlor/cache/anr-framegen/source' / REVISION
        (cache / 'loader.py').write_bytes(b'corrupt cached code')
        self.invoke(scripts, game, env, 'uninstall')
        self.assertEqual((cache / 'loader.py').read_bytes(), (scripts / 'loader.py').read_bytes())
        self.assertEqual(len((root / 'transport.log').read_text().splitlines()), 4)

    def test_payload_transport_failure_is_logged_and_leaves_game_unchanged(self):
        root, scripts, home, game, env = self.fixture()
        env['ANR_FAIL_PAYLOAD'] = '1'
        original = (game / 'OptiScaler.ini').read_bytes()
        result = self.invoke(scripts, game, env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((game / 'OptiScaler.ini').read_bytes(), original)
        self.assertFalse((game / 'custom').exists())
        logs = list((home / '.dlor/logs/anr-framegen/install').glob('*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('addon download failed', logs[0].read_text())
        self.assertIn('exit status: 1', logs[0].read_text())
        self.assertFalse(list(home.rglob('.download-*')))

    def test_log_retention_and_unavailable_logging_do_not_block_helper(self):
        root, scripts, home, game, env = self.fixture()
        folder = home / '.dlor/logs/anr-framegen/install'
        folder.mkdir(parents=True)
        for index in range(15):
            (folder / f'20000101.{index:03}.log').write_text('old')
        (folder / 'unrelated.txt').write_text('mine')
        (folder / 'directory.log').mkdir()
        (folder / 'link.log').symlink_to(folder / 'unrelated.txt')
        self.invoke(scripts, game, env)
        self.assertEqual(len([p for p in folder.glob('*.log') if p.is_file() and not p.is_symlink()]), 10)
        self.assertTrue((folder / 'link.log').is_symlink())
        self.assertTrue((folder / 'directory.log').is_dir())
        self.assertEqual((folder / 'unrelated.txt').read_text(), 'mine')
        # OFF still works if a user makes its log directory unavailable.
        unavailable = home / '.dlor/logs/anr-framegen/uninstall'
        unavailable.write_text('not a directory')
        self.invoke(scripts, game, env, 'uninstall')
        self.assertFalse((game / 'custom').exists())

    def test_direct_loader_termination_reaps_its_payload_downloader(self):
        root, scripts, home, game, env = self.fixture()
        env['ANR_BLOCK_PAYLOAD'] = '1'
        env['DLOR_ANR_MANIFEST'] = str(scripts / 'downloads.json')
        env['DLOR_ANR_MANIFEST_SHA256'] = hashlib.sha256((scripts / 'downloads.json').read_bytes()).hexdigest()
        child = subprocess.Popen([sys.executable, '-I', '-B', str(scripts / 'loader.py'), 'install', str(game)],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is not None or child.kill())
        deadline = time.monotonic() + 10
        marker = root / 'curl.pid'
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), 'payload child did not reach controlled wait')
        downloader_pid = int(marker.read_text())
        child.send_signal(signal.SIGTERM)
        stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 143, stdout + stderr)
        with self.assertRaises(ProcessLookupError):
            os.kill(downloader_pid, 0)
        self.assertFalse(list(home.rglob('.download-*')))
        self.assertFalse((game / 'custom').exists())

    def test_recipe_only_stock_remote_script_no_core_environment(self):
        path = HERE / 'index.ts'
        self.assertTrue(path.exists(), 'addon recipe index is missing')
        source = path.read_text()
        self.assertIn("name: 'OptiScaler FrameGen ANR'", source)
        self.assertIn("group: 'OptiScaler'", source)
        self.assertIn("remoteScript('anr-framegen', 'install')", source)
        self.assertIn("remoteScript('anr-framegen', 'uninstall')", source)
        self.assertNotIn('WINEDLLOVERRIDES', source)
        self.assertNotIn('SteamDeck', source)
        self.assertNotIn('wrapper', source)

    def test_logging_never_follows_controlled_home_symlink(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
            root = Path(temp)
            home, victim = root / 'home', root / 'victim'
            home.mkdir(); victim.mkdir()
            (home / '.dlor').symlink_to(victim, target_is_directory=True)
            result = subprocess.run(['bash', str(SCRIPTS / 'install.sh'), str(root)], env=dict(os.environ, HOME=str(home)),
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(victim.iterdir()), [], result.stdout + result.stderr)

    def test_generator_emits_physical_authenticated_on_off(self):
        generator = SCRIPTS / 'update-source-hashes.py'
        self.assertTrue(generator.exists(), 'source pin generator is missing')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temporary:
            scripts = Path(temporary) / 'scripts'
            shutil.copytree(SCRIPTS, scripts)
            subprocess.run([sys.executable, '-I', '-B', str(scripts / generator.name), '--bundle-revision', REVISION], check=True, capture_output=True)
            manifest = json.loads((scripts / 'downloads.json').read_bytes())
            self.assertEqual(manifest['runtime']['loader.py'], hashlib.sha256((scripts / 'loader.py').read_bytes()).hexdigest())
            for entry in ('install', 'uninstall'):
                shell = (scripts / (entry + '.sh')).read_text()
                self.assertIn('BUNDLE_REVISION=' + REVISION, shell)
                self.assertIn(hashlib.sha256((scripts / 'downloads.json').read_bytes()).hexdigest(), shell)
                self.assertIn('python3 -I -B "$private_work/loader.py"', shell)
                self.assertNotIn('python3 -c', shell)
                self.assertNotIn('python3 - <<', shell)
                self.assertEqual(subprocess.run(['bash', '-n', str(scripts / (entry + '.sh'))]).returncode, 0)


if __name__ == '__main__':
    unittest.main()
