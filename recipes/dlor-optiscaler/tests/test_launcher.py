"""Offline entrypoint fixtures; these do not validate games or provider payloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
REVISION = 'a' * 40

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dlor-launcher-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.trace = self.root / 'trace.json'
        self.fetches = self.root / 'fetches'
        self.env = dict(os.environ, HOME=str(self.home), DLOR_SCRIPT_REVISION=REVISION,
                        FIXTURE_SCRIPTS=str(self.scripts), FIXTURE_TRACE=str(self.trace),
                        FIXTURE_FETCHES=str(self.fetches), PATH=f'{self.bin}:/usr/bin:/bin',
                        SYSTEM_PATH=f'{self.bin}:/usr/bin:/bin', TMPDIR=str(self.root), PYTHONDONTWRITEBYTECODE='1')
        self.game = self.root / 'Game Space \" café'
        self.game.mkdir()
        self.env['STEAM_COMPAT_INSTALL_PATH'] = str(self.game)
        (self.bin / 'curl').write_text(f'''#!{sys.executable} -I
import os, pathlib, shutil, sys
args = sys.argv[1:]
url = args[-1]
assert (url.startswith('https://raw.githubusercontent.com/Wurielle/decky-launch-options-recipes/{REVISION}/recipes/')
        or url == os.environ.get('FIXTURE_CUSTOM_HELPER_URL')), url
assert 'LD_PRELOAD' not in os.environ, 'host downloader inherited overlay preload'
assert not os.environ.get('STEAM_RUNTIME', '').startswith('/'), 'host downloader inherited Steam runtime'
name = url.rsplit('/', 1)[-1]
with open(os.environ['FIXTURE_FETCHES'], 'a') as f: f.write(name + '\\n')
if os.environ.get('FIXTURE_OFFLINE') == '1': sys.exit(22)
if '-o' in args or '--output' in args:
    option = '-o' if '-o' in args else '--output'
    shutil.copyfile(pathlib.Path(os.environ['FIXTURE_SCRIPTS']) / name, args[args.index(option) + 1])
else:
    sys.stdout.buffer.write((pathlib.Path(os.environ['FIXTURE_SCRIPTS']) / name).read_bytes())
''')
        (self.bin / 'curl').chmod(0o755)
        (self.scripts / 'installer.py').write_text('''import json, os, pathlib, sys
import artifacts, game_discovery, update_optiscaler_config
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print('fixture usage: ACTION GAME_ROOT', file=sys.stderr)
        return 2
    record = {'argv': argv, 'env': {k: v for k, v in os.environ.items() if k in ('STEAM_RUNTIME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PATH', 'PYTHONHOME', 'PYTHONPATH', 'WINEDLLOVERRIDES', 'SteamDeck', 'work', 'status', 'entry_name', 'helper_pid', 'logger_pid', 'merged', 'console_out', 'console_err')}, 'isolated': sys.flags.isolated,
              'bytecode': sys.dont_write_bytecode}
    pathlib.Path(os.environ['FIXTURE_TRACE']).write_text(json.dumps(record))
    print('fixture installer output', flush=True)
    print('fixture installer stderr', file=sys.stderr, flush=True)
    if os.environ.get('FIXTURE_FAIL') == '1': return 7
    return 0
''')
        for name in ('artifacts.py', 'game_discovery.py', 'update_optiscaler_config.py'):
            (self.scripts / name).write_text('FIXTURE = True\n')

    def test_physical_loader_and_no_inline_python(self):
        loader = SCRIPTS / 'loader.py'
        self.assertTrue(loader.is_file(), 'physical loader.py is missing')
        metadata = self.generate()
        import hashlib
        manifest = json.loads((self.scripts / 'downloads.json').read_bytes())
        self.assertEqual(metadata['MANIFEST_SHA256'], hashlib.sha256((self.scripts / 'downloads.json').read_bytes()).hexdigest())
        self.assertEqual(manifest['runtime']['loader.py'], hashlib.sha256((self.scripts / 'loader.py').read_bytes()).hexdigest())
        self.assertNotIn('SOURCE_SHA256', loader.read_text())
        self.assertEqual(loader.read_bytes(), (self.scripts / 'loader.py').read_bytes())
        for name in ('install.sh', 'uninstall.sh'):
            shell = (self.scripts / name).read_text()
            self.assertIn('host python3 -I -B "$private_work/loader.py" "$entry_name" "$@"', shell)
            self.assertNotIn('python3 -I -B -c', shell)
            self.assertNotIn('import hashlib', shell)
            self.assertNotIn('eval ', shell)
            self.assertNotIn('<<', shell)

    def test_bootstrap_rejects_malformed_stat_mode_before_fetch(self):
        self.generate()
        (self.bin / 'stat').write_text('#!/bin/bash\nprintf "%s:bogus\\n" "$EUID"\n')
        (self.bin / 'stat').chmod(0o755)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.fetches.exists())
        self.assertFalse(self.trace.exists())

    def test_loader_transfer_failure_never_publishes_or_executes(self):
        self.generate()
        curl = self.bin / 'curl'
        normal = curl.read_text()
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        for action in ('install', 'uninstall'):
            for variant in ('offline', 'partial', 'wrong-sha', 'empty'):
                with self.subTest(action=action, transfer=variant):
                    payload = b'' if variant == 'empty' else b'raise Exception("UNVERIFIED-LOADER")\n'
                    body = (f"pathlib.Path(args[args.index('-o') + 1]).write_bytes({payload!r})\n"
                            f"sys.exit({18 if variant == 'partial' else 22 if variant == 'offline' else 0})\n")
                    curl.write_text(normal.replace("if os.environ.get('FIXTURE_OFFLINE') == '1': sys.exit(22)",
                        "if name == 'loader.py':\n" + ''.join('    ' + line + '\n' for line in body.splitlines())))
                    result = self.run_script(action + '.sh', self.game)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse(self.trace.exists())
                    self.assertNotIn('UNVERIFIED-LOADER', result.stdout + result.stderr)
                    self.assertEqual([p.name for p in cache.iterdir()], ['downloads.json'])
        self.assertEqual(set(self.fetches.read_text().splitlines()), {'downloads.json', 'loader.py'})

    def test_loader_rechecks_readonly_manifest_snapshot_before_module_fetch(self):
        self.generate()
        (self.bin / 'python3').write_text('''#!/bin/bash
[[ $(/usr/bin/stat -c %a "$DLOR_OPTISCALER_MANIFEST") == 400 ]] || exit 90
[[ $(/usr/bin/stat -c %a "${@: -3:1}") == 400 ]] || exit 91
chmod u+w "$DLOR_OPTISCALER_MANIFEST" || exit
printf ' ' >> "$DLOR_OPTISCALER_MANIFEST"
exec /usr/bin/python3 "$@"
''')
        (self.bin / 'python3').chmod(0o755)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('manifest snapshot checksum mismatch', result.stdout + result.stderr)
        self.assertFalse(self.trace.exists())
        self.assertEqual(self.fetches.read_text().splitlines(), ['downloads.json', 'loader.py'])

    def test_manifest_tamper_offline_refusal_repair_and_symlink_guard(self):
        self.generate()
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        manifest = cache / 'downloads.json'
        data = json.loads(manifest.read_bytes())
        data['runtime']['installer.py'] = '0' * 64
        manifest.write_text(json.dumps(data))
        self.trace.unlink()
        self.env['FIXTURE_OFFLINE'] = '1'
        self.assertNotEqual(self.run_script('install.sh', self.game).returncode, 0)
        self.assertFalse(self.trace.exists())
        self.env['FIXTURE_OFFLINE'] = '0'
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(manifest.read_bytes(), (self.scripts / 'downloads.json').read_bytes())
        manifest.unlink()
        outside = self.root / 'external-manifest'
        outside.write_bytes((self.scripts / 'downloads.json').read_bytes())
        manifest.symlink_to(outside)
        self.trace.unlink()
        fetched = self.fetches.read_bytes()
        self.assertNotEqual(self.run_script('uninstall.sh', self.game).returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertEqual(self.fetches.read_bytes(), fetched)

    def test_loader_tamper_repair_offline_refusal_and_bytecode(self):
        self.generate()
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        poison = self.root / 'poison.py'
        poison.write_text('raise Exception("UNVERIFIED-LOADER")\n')
        # Both adjacent legacy and import-cache bytecode must be irrelevant to
        # direct execution of the physical verified source file.
        code = ('import pathlib,py_compile,sys; '
                'py_compile.compile(sys.argv[1], cfile=sys.argv[2], '
                'invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)')
        subprocess.run([sys.executable, '-I', '-B', '-c', code, str(poison), str(cache / 'loader.pyc')], check=True)
        (cache / '__pycache__').mkdir()
        import importlib.util
        subprocess.run([sys.executable, '-I', '-B', '-c', code, str(poison),
                        str(Path(importlib.util.cache_from_source(str(cache / 'loader.py'))))], check=True)
        self.env['FIXTURE_OFFLINE'] = '1'
        result = self.run_script('uninstall.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (cache / 'loader.py').write_bytes(poison.read_bytes())
        self.trace.unlink()
        result = self.run_script('uninstall.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertNotIn('UNVERIFIED-LOADER', result.stdout + result.stderr)
        self.assertFalse(list(cache.glob('.loader.*')))
        self.env['FIXTURE_OFFLINE'] = '0'
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((cache / 'loader.py').read_bytes(), (self.scripts / 'loader.py').read_bytes())
        self.assertNotIn('UNVERIFIED-LOADER', result.stdout + result.stderr)

    def test_private_loader_snapshot_is_reverified_before_execution(self):
        self.generate()
        (self.bin / 'cp').write_text('#!/bin/bash\n/usr/bin/cp "$@" || exit\nprintf \'raise Exception("UNVERIFIED-SNAPSHOT")\\n\' > "${@: -1}"\n')
        (self.bin / 'cp').chmod(0o755)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('snapshot checksum mismatch', result.stdout)
        self.assertNotIn('UNVERIFIED-SNAPSHOT', result.stdout + result.stderr)
        self.assertFalse(self.trace.exists())
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        self.assertEqual([p.name for p in cache.iterdir()], ['downloads.json'])

    def test_loader_cache_link_and_foreign_owner_refused_before_fetch(self):
        self.generate()
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        cache.mkdir(parents=True, mode=0o700)
        outside = self.root / 'foreign-loader'
        outside.write_text('foreign bytes')
        (cache / 'loader.py').symlink_to(outside)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.fetches.exists())
        self.assertEqual(outside.read_text(), 'foreign bytes')
        (cache / 'loader.py').unlink()
        (self.bin / 'stat').write_text('#!/bin/bash\nprintf "%s:700\\n" "$((EUID + 1))"\n')
        (self.bin / 'stat').chmod(0o755)
        result = self.run_script('uninstall.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.fetches.exists())

    def test_bootstrap_cancels_only_owned_manifest_download(self):
        self.assert_bootstrap_download_cancellation('downloads.json')

    def test_bootstrap_cancels_only_owned_loader_download(self):
        self.assert_bootstrap_download_cancellation('loader.py')

    def assert_bootstrap_download_cancellation(self, name):
        import signal
        import time
        self.generate()
        curl = self.bin / 'curl'
        normal = curl.read_text()
        ready = self.root / 'bootstrap-pids'
        self.env['FIXTURE_READY'] = str(ready)
        curl.write_text(normal.replace('args = sys.argv[1:]',
            "import time\n"
            "if sys.argv[-1].endswith('/" + name + "'):\n"
            "    pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(b'partial')\n"
            "    pathlib.Path(os.environ['FIXTURE_READY']).write_text(str(os.getpid()) + ':' + str(os.getppid()))\n"
            "    while True: time.sleep(0.02)\nargs = sys.argv[1:]"))
        sentinel = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'])
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(signal=signum):
                    ready.unlink(missing_ok=True)
                    process = subprocess.Popen(['bash', str(self.scripts / 'install.sh'), str(self.game)],
                                               env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               start_new_session=True)
                    try:
                        deadline = time.monotonic() + 5
                        while not ready.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue(ready.exists(), 'bootstrap never reached loader downloader')
                        downloader, bootstrap = map(int, ready.read_text().split(':'))
                        os.kill(bootstrap, signum)
                        stdout, stderr = process.communicate(timeout=4)
                        self.assertEqual(process.returncode, 128 + signum, stdout + stderr)
                        self.assertFalse(Path(f'/proc/{downloader}').exists())
                        self.assertFalse(self.trace.exists())
                        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
                        self.assertEqual([p.name for p in cache.iterdir()], ['downloads.json'] if name == 'loader.py' else [])
                        self.assertIsNone(sentinel.poll())
                    finally:
                        if process.poll() is None:
                            if ready.exists():
                                for pid in map(int, ready.read_text().split(':')):
                                    try: os.kill(pid, signal.SIGKILL)
                                    except ProcessLookupError: pass
                            process.kill()
                        process.communicate(timeout=5)
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=5)

    def test_bootstrap_host_tools_atomic_publish_and_newline_home(self):
        self.generate()
        renamed = self.root / 'home space\n café'
        self.home.rename(renamed)
        self.home = renamed
        self.env.update(HOME=str(renamed), STEAM_RUNTIME='/steam/runtime',
                        LD_LIBRARY_PATH='/steam/lib', SYSTEM_LD_LIBRARY_PATH='',
                        PYTHONHOME='/steam/python', PYTHONPATH='/steam/modules')
        for tool in ('readlink', 'stat', 'mkdir', 'mktemp', 'mv', 'cp', 'sha256sum', 'rm'):
            (self.bin / tool).write_text(f'''#!{sys.executable} -I
import os, pathlib, sys
assert 'LD_PRELOAD' not in os.environ
assert 'PYTHONHOME' not in os.environ and 'PYTHONPATH' not in os.environ
assert not os.environ.get('STEAM_RUNTIME', '').startswith('/')
assert os.environ['PATH'] == os.environ['SYSTEM_PATH']
assert os.environ.get('LD_LIBRARY_PATH', '') == os.environ.get('SYSTEM_LD_LIBRARY_PATH', '')
if {tool!r} == 'sha256sum': assert len(sys.argv) == 1, 'hash filenames only via stdin'
if {tool!r} == 'mv':
    source, target = map(pathlib.Path, sys.argv[-2:])
    assert source.parent.parent == target.parent, 'publication must stay on cache filesystem'
    assert source.read_bytes() == (pathlib.Path(os.environ['FIXTURE_SCRIPTS']) / target.name).read_bytes()
os.execv('/usr/bin/{tool}', ['{tool}', *sys.argv[1:]])
''')
            (self.bin / tool).chmod(0o755)
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists())
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        self.assertFalse(list(cache.glob('.loader.*')))

    def test_verified_snapshot_survives_cache_change_after_copy(self):
        self.generate()
        (self.bin / 'cp').write_text('#!/bin/bash\n/usr/bin/cp "$@" || exit\nprintf \'raise Exception("MUTABLE-CACHE-EXECUTED")\\n\' > "${@: -2:1}"\n')
        (self.bin / 'cp').chmod(0o755)
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists())
        self.assertNotIn('MUTABLE-CACHE-EXECUTED', result.stdout + result.stderr)

    def generate(self):
        updater = SCRIPTS / 'update-source-hashes.py'
        self.assertTrue(updater.is_file(), 'maintainer entrypoint generator is missing')
        shutil.copyfile(updater, self.scripts / updater.name)
        if not (self.scripts / 'nightly.py').exists():
            shutil.copyfile(SCRIPTS / 'nightly.py', self.scripts / 'nightly.py')
        if not (self.scripts / 'loader.py').exists():
            shutil.copyfile(SCRIPTS / 'loader.py', self.scripts / 'loader.py')
        result = subprocess.run([sys.executable, '-I', '-B', str(self.scripts / updater.name), '--source-revision', REVISION],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def run_script(self, name, *args):
        return subprocess.run(['bash', str(self.scripts / name), *map(str, args)],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_sources_accept_a_symlinked_home_ancestor(self):
        self.generate()
        alias = self.root / 'home-parent-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        self.env['HOME'] = str(alias / self.home.name)
        for name in ('install.sh', 'uninstall.sh'):
            with self.subTest(entry=name):
                result = self.run_script(name, self.game)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
                self.trace.unlink()

    def test_sources_still_reject_a_symlink_inside_the_home_cache(self):
        self.generate()
        target = self.root / 'outside-source-cache'
        target.mkdir()
        source = self.home / '.dlor/cache/dlor-optiscaler/source'
        source.parent.mkdir(parents=True)
        source.symlink_to(target, target_is_directory=True)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe cache directory', result.stderr + result.stdout)
        self.assertFalse(self.trace.exists())
        self.assertEqual(list(target.iterdir()), [])

    def test_cold_direct_install_fetches_verified_isolated_source(self):
        self.generate()
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = json.loads(self.trace.read_text())
        self.assertEqual(trace['argv'], ['install', str(self.game)])
        self.assertEqual(trace['isolated'], 1)
        self.assertTrue(trace['bytecode'])
        self.assertEqual(trace['env']['SteamDeck'], '0')
        self.assertEqual(self.fetches.read_text().splitlines(), ['downloads.json', 'loader.py', 'installer.py', 'artifacts.py', 'game_discovery.py', 'update_optiscaler_config.py'])
        logs = list((self.home / '.dlor/logs/dlor-optiscaler/install').glob('*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('fixture installer stderr', logs[0].read_text())
        self.assertFalse(list(self.home.rglob('*.pyc')))

    def game_command(self, *extra):
        output = self.root / 'game-result.json'
        code = ("import json, os, pathlib, sys; "
                "pathlib.Path(sys.argv[1]).write_text(json.dumps({'argv': sys.argv[2:], 'env': {k: v for k, v in os.environ.items() if k in ('STEAM_RUNTIME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PATH', 'PYTHONHOME', 'PYTHONPATH', 'WINEDLLOVERRIDES', 'SteamDeck', 'work', 'status', 'entry_name', 'helper_pid', 'logger_pid', 'merged', 'console_out', 'console_err', 's', 'REPLY', 'p', 'f', 'COPROC', 'COPROC_PID', 'ORIGINAL_TEST_VALUE', 'DLOR_SCRIPT_REVISION', 'DLOR_REPOSITORY')}})); "
                "print('GAMEPLAY-SENTINEL', flush=True); sys.exit(23)")
        return [sys.executable, '-I', '-B', '-c', code, str(output), *extra]

    def compiled_recipe(self, name="dlor-optiscaler"):
        repo = SCRIPTS.parents[2]
        compiled = self.root / 'compiled'
        result = subprocess.run([shutil.which('node') or 'node', str(repo / 'node_modules/typescript/bin/tsc'),
                                 str(SCRIPTS.parent.parent / name / 'index.ts'), '--target', 'ES2020', '--module', 'nodenext',
                                 '--moduleResolution', 'nodenext', '--skipLibCheck', '--outDir', str(compiled)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (compiled / 'package.json').write_text('{"type":"module"}')
        result = subprocess.run([shutil.which('node') or 'node', '--input-type=module', '-e',
                                 f"import recipe from '{(compiled / name / 'index.js').as_uri()}'; console.log(JSON.stringify(recipe))"],
                                env=dict(self.env, RECIPE_COMMIT_SHA=REVISION,
                                         RECIPE_REPOSITORY_OWNER='Wurielle',
                                         RECIPE_REPOSITORY_NAME='decky-launch-options-recipes'),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_file_backed_toggle_through_actual_consumer(self):
        import runpy
        self.generate()
        runpy.run_path(str(SCRIPTS.parents[2] / 'scripts/runner_test_support.py'))['install_runner'](self.home)
        recipe = self.compiled_recipe()
        self.env['SteamDeck'] = '1'
        for enabled, action in ((True, 'install'), (False, 'uninstall')):
            with self.subTest(enabled=enabled):
                expected = (('WINEDLLOVERRIDES="dxgi=n,b" SteamDeck=0 ' if enabled else '')
                            + f'~/.dlor/run dlor-optiscaler {action} {REVISION} -- %command%')
                self.assertEqual(recipe['launchOptions'][0]['on' if enabled else 'off'], expected)
                self.env.pop('DLOR_SCRIPT_REVISION', None)
                final, env, variables = self.consumer_launch(recipe, self.game_command('quoted " café path'), enabled)
                self.assertEqual(final[:5], [str(self.home / '.dlor/run'), 'dlor-optiscaler', action, REVISION, '--'])
                result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                self.assertEqual(json.loads(self.trace.read_text())['argv'], [action, str(self.game)])
                observed = json.loads((self.root / 'game-result.json').read_text())
                self.assertEqual(observed['argv'], ['quoted " café path', '--original-arg'])
                self.assertEqual(observed['env']['SteamDeck'], '0' if enabled else '1')
                if enabled:
                    self.assertEqual(variables['WINEDLLOVERRIDES'], 'dxgi=n,b')
                    self.assertEqual(variables['SteamDeck'], '0')
                else:
                    self.assertNotIn('WINEDLLOVERRIDES', variables)
                    self.assertNotIn('SteamDeck', variables)

    def test_actual_consumer_executes_file_backed_entrypoint(self):
        import runpy
        self.generate()
        runpy.run_path(str(SCRIPTS.parents[2] / 'scripts/runner_test_support.py'))['install_runner'](self.home)
        self.env.pop('DLOR_SCRIPT_REVISION')
        recipe = self.compiled_recipe()
        final, env, _ = self.consumer_launch(recipe, self.game_command())
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        self.assertEqual(self.fetches.read_text().splitlines()[0], 'install.sh')

    def test_actual_consumer_passes_all_three_formats_to_verified_physical_updater(self):
        shutil.copyfile(SCRIPTS / 'update_optiscaler_config.py', self.scripts / 'update_optiscaler_config.py')
        installer = self.scripts / 'installer.py'
        installer.write_text(installer.read_text().replace(
            "    pathlib.Path(os.environ['FIXTURE_TRACE']).write_text(json.dumps(record))",
            "    data = b'[FG]\\nEnabled=auto\\n[FSR]\\nFsr4GpuSupport=auto\\n[User]\\nUniqueFont=auto\\n'\n"
            "    record['overrides'] = [[s, k, v] for (s, k), v in update_optiscaler_config.resolve_overrides(data).items()]\n"
            "    pathlib.Path(os.environ['FIXTURE_TRACE']).write_text(json.dumps(record))"))
        recipe = self.fixture_recipe()
        helper = {'id': 'explicit', 'on': 'OptiScaler_FG_Enabled="true" FSR_Fsr4GpuSupport="2" UniqueFont="50% literal"', 'off': '', 'priority': 10}
        final, env, variables = self.consumer_launch(recipe, self.game_command(), helpers=(helper,))
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(sorted(json.loads(self.trace.read_text())['overrides']),
                         [['FG', 'Enabled', 'true'], ['FSR', 'Fsr4GpuSupport', '2'], ['User', 'UniqueFont', '50% literal']])
        self.assertIn('update_optiscaler_config.py', self.fetches.read_text().splitlines())

    def test_updater_cache_tamper_offline_and_symlink_are_rejected(self):
        self.generate()
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        updater = cache / 'update_optiscaler_config.py'
        updater.write_text('raise Exception("UNVERIFIED-UPDATER")\n')
        self.trace.unlink()
        self.env['FIXTURE_OFFLINE'] = '1'
        result = self.run_script('uninstall.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertNotIn('UNVERIFIED-UPDATER', result.stdout + result.stderr)
        self.env['FIXTURE_OFFLINE'] = '0'
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        outside = self.root / 'foreign-updater.py'
        outside.write_text('foreign bytes')
        updater.unlink()
        updater.symlink_to(outside)
        self.fetches.unlink()
        self.trace.unlink()
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertFalse(self.fetches.exists())
        self.assertEqual(outside.read_text(), 'foreign bytes')

    def test_actual_consumer_requires_explicit_source_location(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(unittest.SkipTest):
                self.actual_consumer()

    def actual_consumer(self):
        import hashlib
        import importlib.util
        import runpy
        from unittest.mock import patch
        # Supply the unmodified DLO sources at this pinned consumer revision.
        location = os.environ.get('DLO_CONSUMER_SOURCE')
        if not location:
            self.skipTest('Set DLO_CONSUMER_SOURCE to a checkout of DLO a3996e590b61f0a985a0182cb89278a4850e39f6')
        source = Path(location)
        expected = {'run.py': '2e78c2b0739595ab00eab7bfc21a8778c15cbb2cfe2dc8c0beaa1e705655860e',
                    'shared.py': 'e12a4ccf2a8e957ebd99cab1677aa00704dc9ae98b12d34c24c98d9aeb4fab0b'}
        for name, digest in expected.items():
            self.assertTrue((source / name).is_file(), 'Set DLO_CONSUMER_SOURCE to DLO a3996e590b61f0a985a0182cb89278a4850e39f6 sources')
            self.assertEqual(hashlib.sha256((source / name).read_bytes()).hexdigest(), digest)
        shared = runpy.run_path(str(source / 'shared.py'))
        import types
        with patch.dict(sys.modules, shared=types.SimpleNamespace(**shared)):
            spec = importlib.util.spec_from_file_location('actual_dlo_consumer', source / 'run.py')
            assert spec is not None and spec.loader is not None
            consumer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(consumer)
        return consumer

    def consumer_launch(self, recipe, game, enabled=True, helpers=()):
        from unittest.mock import patch
        consumer = self.actual_consumer()
        settings = {'launchOptions': [*helpers, *recipe['launchOptions']],
                    'profiles': {'123': {'state': {'dlor-optiscaler': enabled, **{h['id']: True for h in helpers}},
                                         'originalLaunchOptions': 'ORIGINAL_TEST_VALUE="original value" %command% --original-arg'}}}
        with patch.dict(os.environ, self.env, clear=True), patch.object(sys, 'argv', ['run.py', *game]):
            final, variables = consumer.get_final_args_details(settings, '123')
            child_env = dict(os.environ)
        return final, child_env, variables

    def fixture_recipe(self):
        import runpy
        self.generate()
        # Only transport/installer modules are synthetic; parser, backend runner
        # installation and generated install/uninstall entrypoints are real.
        runpy.run_path(str(SCRIPTS.parents[2] / 'scripts/runner_test_support.py'))['install_runner'](self.home)
        return self.compiled_recipe()

    def test_actual_consumer_preserves_shared_source_context_for_nested_recipes(self):
        import runpy
        recipe = self.fixture_recipe()
        runpy.run_path(str(SCRIPTS.parents[2] / 'scripts/runner_test_support.py'))['install_runner'](self.home)
        marker = self.root / 'custom-helper-context'
        self.env.update(DLOR_SCRIPT_REVISION='b' * 40, DLOR_REPOSITORY='Wurielle/decky-launch-options-recipes',
                        FIXTURE_CUSTOM_CONTEXT=str(marker),
                        FIXTURE_CUSTOM_HELPER_URL=f'https://raw.githubusercontent.com/Wurielle/decky-launch-options-recipes/{REVISION}/recipes/fixture/scripts/custom.sh')
        (self.scripts / 'custom.sh').write_text(
            '#!/bin/bash\nprintf "%s\\n" "$DLOR_REPOSITORY:$DLOR_SCRIPT_REVISION" > "$FIXTURE_CUSTOM_CONTEXT"\n')
        helper = {'id': 'custom', 'on': f'~/.dlor/run fixture custom {REVISION} -- %command%',
                  'off': '', 'priority': -10}
        final, env, _ = self.consumer_launch(recipe, self.game_command(), helpers=(helper,))
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        self.assertTrue(marker.exists(), result.stdout + result.stderr)
        self.assertEqual(marker.read_text().strip(), 'Wurielle/decky-launch-options-recipes:' + 'b' * 40)
        game = json.loads((self.root / 'game-result.json').read_text())
        for key in ('DLOR_SCRIPT_REVISION', 'DLOR_REPOSITORY'):
            self.assertEqual(game['env'][key], self.env[key])

    def test_actual_consumer_chains_unchanged_dev_helpers_on_off_and_failure(self):
        import hashlib
        import runpy
        repo = SCRIPTS.parents[2]
        recipe = self.fixture_recipe()
        spaced_home = self.root / 'home with spaces'
        self.home.rename(spaced_home)
        self.home = spaced_home
        self.env['HOME'] = str(spaced_home)
        runpy.run_path(str(repo / 'scripts/runner_test_support.py'))['install_runner'](self.home)
        self.assertEqual((self.home / '.dlor/run').read_bytes(), (repo / 'defaults/dlor-run.sh').read_bytes())
        self.assertEqual(hashlib.sha256((self.home / '.dlor/run').read_bytes()).hexdigest(),
                         'cff808048a9786f149b8a5d359e362477b9f50e90fb3308d50d1ea1d98996f1a')
        helpers = []
        helper_trace = self.root / 'helper-trace'
        self.env['FIXTURE_HELPER_TRACE'] = str(helper_trace)
        for script, priority in [('before', 10), ('after', -10)]:
            (self.scripts / (script + '.sh')).write_text(
                f'#!/bin/bash\nprintf "%s\\n" "{script}:$1" >> "$FIXTURE_HELPER_TRACE"\n')
            helpers.append({'id': script, 'on': f'~/.dlor/run fixture {script} {REVISION} -- %command%',
                            'off': '', 'priority': priority})
        helpers.append({'id': 'other-wine', 'on': 'WINEDLLOVERRIDES="dinput8=n;version=b"',
                        'off': '', 'priority': -20})
        self.env.pop('DLOR_SCRIPT_REVISION')
        self.env.update(STEAM_RUNTIME='/steam/runtime', LD_LIBRARY_PATH='/steam/libraries',
                        SYSTEM_LD_LIBRARY_PATH='', PYTHONHOME='/steam/python', PYTHONPATH='/steam/modules',
                        WINEDLLOVERRIDES='dinput8=n;dxgi,version=b', s='original-s',
                        ORIGINAL_TEST_VALUE='will be replaced')
        acquisition_keys = ('REPLY', 'p', 'f', 'COPROC', 'COPROC_PID')
        self.env.update({key: 'original-' + key for key in acquisition_keys})
        # Hashing must use the host environment just like curl, not Steam's.
        (self.bin / 'sha256sum').write_text(f'''#!{sys.executable} -I
import os, sys
assert 'LD_PRELOAD' not in os.environ
assert not os.environ.get('STEAM_RUNTIME', '').startswith('/')
assert os.environ['PATH'] == os.environ['SYSTEM_PATH']
assert os.environ.get('LD_LIBRARY_PATH', '') == os.environ.get('SYSTEM_LD_LIBRARY_PATH', '')
os.execv('/usr/bin/sha256sum', ['sha256sum', *sys.argv[1:]])
''')
        (self.bin / 'sha256sum').chmod(0o755)
        game = self.game_command('space arg', '', 'semi;colon', 'quote"arg', 'line\nbreak')
        for enabled, fail in [(True, False), (False, False), (True, True)]:
            with self.subTest(enabled=enabled, preparation_failure=fail):
                self.env['FIXTURE_FAIL'] = '1' if fail else '0'
                self.trace.unlink(missing_ok=True)
                helper_trace.unlink(missing_ok=True)
                final, env, variables = self.consumer_launch(recipe, game, enabled, helpers)
                self.assertEqual(final[:2], [str(self.home / '.dlor/run'), 'fixture'])
                self.assertNotIn('--wrapper', final)
                result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                self.assertTrue(helper_trace.exists(), result.stdout + result.stderr)
                self.assertEqual(helper_trace.read_text().splitlines(),
                                 [f'before:{self.game}', f'after:{self.game}'])
                trace = json.loads(self.trace.read_text())
                self.assertEqual(trace['argv'][0], 'install' if enabled else 'uninstall')
                observed = json.loads((self.root / 'game-result.json').read_text())
                self.assertEqual(observed['argv'], game[6:] + ['--original-arg'])
                for key in ('STEAM_RUNTIME', 'LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH', 'PATH', 's', *acquisition_keys):
                    self.assertEqual(observed['env'][key], self.env[key])
                self.assertEqual(observed['env']['ORIGINAL_TEST_VALUE'], 'original value')
                expected = 'dinput8=n;version=b;dxgi=n,b' if enabled else 'dinput8=n;version=b'
                self.assertEqual(observed['env']['WINEDLLOVERRIDES'], expected)
                self.assertNotIn('DLOR_SCRIPT_REVISION', variables)

    def test_actual_consumer_preserves_stdin_and_extra_fds_across_source_acquisition(self):
        recipe = self.fixture_recipe()
        # Module downloaders see EOF; the unchanged runner curl does not read input.
        curl = self.bin / 'curl'
        curl.write_text(curl.read_text().replace('args = sys.argv[1:]',
            "if sys.argv[-1].endswith('.py'): assert sys.stdin.buffer.read() == b'', 'module downloader consumed game stdin'\nargs = sys.argv[1:]"))
        output = self.root / 'consumer-fds.json'
        fd_path = self.root / 'consumer-inherited'
        with fd_path.open('wb') as stream:
            fd = stream.fileno()
            code = ("import json,os,pathlib,sys\n"
                    "os.write(int(sys.argv[2]), b'inherited:' + sys.stdin.buffer.read())\n"
                    "fds=[]\n"
                    "for item in os.listdir('/proc/self/fd'):\n"
                    "    try: os.fstat(int(item)); fds.append(int(item))\n"
                    "    except OSError: pass\n"
                    "pathlib.Path(sys.argv[1]).write_text(json.dumps(sorted(fds)))\n"
                    "print('GAME-STDOUT-SENTINEL', flush=True)\n"
                    "print('GAME-STDERR-SENTINEL', file=sys.stderr, flush=True)\n"
                    "sys.exit(23)\n")
            game = [sys.executable, '-I', '-B', '-c', code, str(output), str(fd)]
            final, env, _ = self.consumer_launch(recipe, game)
            result = subprocess.run(final, env=env, input=b'game stdin\n', pass_fds=(fd,), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        self.assertEqual(fd_path.read_bytes(), b'inherited:game stdin\n')
        self.assertEqual(json.loads(output.read_text()), sorted({0, 1, 2, fd}))
        self.assertIn(b'GAME-STDERR-SENTINEL', result.stderr)
        self.assertTrue(all('GAME-STDOUT-SENTINEL' not in log.read_text()
                            and 'GAME-STDERR-SENTINEL' not in log.read_text()
                            for log in (self.home / '.dlor/logs').rglob('*.log')))

    def test_generator_emits_only_two_deterministic_entrypoints(self):
        index = self.root / 'index.ts'
        index.write_text('recipe source must remain untouched\n')
        metadata = self.generate()
        self.assertEqual(set(metadata), {'runtime', 'MANIFEST_SHA256'})
        self.assertEqual(set(metadata['runtime']), {'loader.py', 'installer.py', 'artifacts.py', 'game_discovery.py', 'update_optiscaler_config.py', 'nightly.py'})
        self.assertEqual(index.read_text(), 'recipe source must remain untouched\n')
        self.assertFalse((self.scripts / 'launch.sh').exists())
        before = {name: (self.scripts / name).read_bytes() for name in ('install.sh', 'uninstall.sh')}
        self.generate()
        self.assertEqual(before, {name: (self.scripts / name).read_bytes() for name in before})
        for name in before:
            self.assertIn(b'MANIFEST_SHA256=', before[name])
            self.assertNotIn(b'SOURCE_SHA256', before[name])
            self.assertNotIn(b'ENTRY_SHA256', before[name])
            result = subprocess.run(['bash', '-n', str(self.scripts / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_nightly_option_routes_explicit_latest_through_stock_consumer(self):
        nightly = next(option for option in self.compiled_recipe("optiscaler")["launchOptions"]
                       if option["id"] == "optiscaler-nightly-upgrade")
        self.assertEqual((nightly["name"], nightly["priority"], nightly["off"]),
                         ("OptiScaler Nightly Upgrade", -1, ""))
        parsed = self.actual_consumer().parse_launch_option(nightly["on"])
        self.assertEqual(parsed["env_vars"], {})
        self.assertEqual(parsed["prefix"], ["~/.dlor/run", "optiscaler", "update-nightly", REVISION, "--"])
        self.assertNotIn("python", nightly["on"])
        recipe = self.fixture_recipe()
        import runpy
        generator = runpy.run_path(str(self.scripts / 'update-source-hashes.py'))
        import hashlib
        digest = hashlib.sha256((self.scripts / 'downloads.json').read_bytes()).hexdigest()
        (self.scripts / 'update-nightly.sh').write_text(generator['render_entry']('upgrade', digest))
        for enabled in (True, False):
            final, env, variables = self.consumer_launch(recipe, self.game_command('nightly literal'), enabled, helpers=(nightly,))
            result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertEqual(json.loads(self.trace.read_text())["argv"], ["upgrade", str(self.game)])
            self.assertNotIn("DLOR_OPTISCALER_LATEST", variables)
            self.assertNotIn("DLOR_OPTISCALER_ACTION", variables)

    def test_recipe_has_short_file_calls_and_none_only_dropdown_defaults(self):
        recipe = self.compiled_recipe()
        self.assertEqual(recipe['name'], 'DLOR OptiScaler')
        toggle = recipe['launchOptions'][0]
        consumer = self.actual_consumer()
        for action, key in [('install', 'on'), ('uninstall', 'off')]:
            option = toggle[key]
            self.assertLess(len(option), 150)
            parsed = consumer.parse_launch_option(option)
            expected = {'WINEDLLOVERRIDES': 'dxgi=n,b', 'SteamDeck': '0'} if key == 'on' else {}
            self.assertEqual(parsed['env_vars'], expected)
            self.assertEqual(parsed['prefix'], ['~/.dlor/run', 'dlor-optiscaler', action, REVISION, '--'])
            self.assertEqual(parsed['pre_commands'], [])
            self.assertEqual(parsed['suffix'], [])
        for option in recipe['launchOptions']:
            for key in ('on', 'off'):
                parsed = consumer.parse_launch_option(option[key])
                self.assertNotIn('bash', parsed['prefix'])
                self.assertNotIn('curl', option[key])
                self.assertNotIn('eval', option[key])
                self.assertNotIn('coproc', option[key])
                self.assertNotIn('\n', option[key])
        options = recipe['launchOptions'][1:]
        groups = {}
        for option in options:
            if 'valueId' in option:
                groups.setdefault(option['valueId'], []).append(option)
        self.assertEqual(set(groups), {'dlor-optiscaler-fsr-profile'})
        self.assertFalse(any('DLOR_OPTISCALER_CHANNEL' in o['on'] or 'DLOR_OPTISCALER_PROXY' in o['on'] for o in options))
        fsr = groups['dlor-optiscaler-fsr-profile']
        self.assertEqual([v['on'] for v in fsr], ['',
                         'DLOR_OPTISCALER_FSR_PROFILE="bundled"',
                         'DLOR_OPTISCALER_FSR_PROFILE="rdna23-int8"',
                         'DLOR_OPTISCALER_FSR_PROFILE="rdna34-official-411"',
                         'DLOR_OPTISCALER_FSR_PROFILE="rdna2-valve-411"'])
        self.assertTrue(all(v['name'] == 'FSR4 compatibility' for v in fsr))
        defaults = [v for v in fsr if v.get('fallbackValue')]
        self.assertEqual(len(defaults), 1)
        self.assertEqual((defaults[0]['valueName'], defaults[0]['on'], defaults[0]['off']), ('None', '', ''))
        self.assertFalse(any('DLOR_OPTISCALER_OPTIPATCHER' in o[key] for o in recipe['launchOptions'] for key in ('on', 'off')))

    def test_shell_bookkeeping_does_not_overwrite_game_environment(self):
        recipe = self.fixture_recipe()
        keys = ('work', 'status', 'entry_name', 'helper_pid', 'logger_pid', 'merged', 'console_out', 'console_err')
        for key in keys:
            self.env[key] = 'original-' + key
        final, env, _ = self.consumer_launch(recipe, self.game_command())
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        game = json.loads((self.root / 'game-result.json').read_text())
        for key in keys:
            self.assertEqual(game['env'][key], self.env[key])
        self.assertTrue(all('GAMEPLAY-SENTINEL' not in p.read_text()
                            for p in (self.home / '.dlor/logs').rglob('*.log')))

    def test_warm_install_and_cached_uninstall_modules_are_offline(self):
        self.generate()
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        fetched = self.fetches.read_text()
        self.env['FIXTURE_OFFLINE'] = '1'
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        self.assertEqual(self.run_script('uninstall.sh', self.game).returncode, 0)
        self.assertEqual(self.fetches.read_text(), fetched)
        self.assertEqual(json.loads(self.trace.read_text())['argv'][0], 'uninstall')
        # Outer entrypoints still download on every launch under stock dlor/run.

    def test_tampered_source_is_refetched_and_pyc_is_not_executed(self):
        self.generate()
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        (cache / 'artifacts.py').write_text('raise Exception("tampered source")\n')
        poison = self.root / 'poison.py'
        poison.write_text('raise Exception("unverified bytecode executed")\n')
        python = shutil.which('python3', path=self.env['PATH']) or 'python3'
        compile_code = ("import importlib.util, pathlib, py_compile, sys; "
                        "target=pathlib.Path(importlib.util.cache_from_source(sys.argv[2])); "
                        "target.parent.mkdir(exist_ok=True); "
                        "py_compile.compile(sys.argv[1], cfile=str(target), "
                        "invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)")
        subprocess.run([python, '-I', '-B', '-c', compile_code, str(poison), str(cache / 'installer.py')], check=True)
        # Prove this bytecode would execute through the ordinary import path,
        # even under -I -B. The verified-source loader must not use that path.
        unsafe = subprocess.run([python, '-I', '-B', '-c',
                                 'import sys; sys.path.insert(0, sys.argv[1]); import installer', str(cache)],
                                capture_output=True, text=True)
        self.assertNotEqual(unsafe.returncode, 0)
        self.assertIn('unverified bytecode executed', unsafe.stderr)
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.fetches.read_text().splitlines().count('artifacts.py'), 2)
        self.assertIn('checksum mismatch', result.stdout)

    def test_symlink_source_cache_is_rejected(self):
        self.generate()
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        cache.parent.mkdir(parents=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        cache.symlink_to(elsewhere, target_is_directory=True)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertFalse(self.fetches.exists())
        self.assertIn('unsafe cache', result.stdout)

    def test_invalid_revision_repository_and_digest_are_rejected(self):
        self.generate()
        for key, value in [('DLOR_OPTISCALER_SOURCE_REVISION', 'main'), ('DLOR_OPTISCALER_SOURCE_REPOSITORY', 'owner/../repo')]:
            with self.subTest(key=key):
                old = self.env.get(key)
                self.env[key] = value
                result = self.run_script('install.sh', self.game)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.trace.exists())
                self.assertFalse(self.fetches.exists())
                if old is None: self.env.pop(key)
                else: self.env[key] = old
        script = self.scripts / 'install.sh'
        text = script.read_text()
        import re
        text = re.sub(r"[a-f0-9]{64}", 'invalid-sha', text, count=1)
        script.write_text(text)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.fetches.exists())

    def test_log_retention_and_unavailable_logging_do_not_block(self):
        self.generate()
        folder = self.home / '.dlor/logs/dlor-optiscaler/install'
        folder.mkdir(parents=True)
        for number in range(15):
            (folder / f'000{number:02}.log').write_text('old')
        (folder / 'keep.txt').write_text('keep')
        (folder / '00000-link.log').symlink_to(folder / 'keep.txt')
        (folder / 'directory.log').mkdir()
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        self.assertEqual(len([p for p in folder.glob('*.log') if p.is_file() and not p.is_symlink()]), 10)
        self.assertTrue((folder / 'keep.txt').exists())
        self.assertTrue((folder / '00000-link.log').is_symlink())
        self.assertTrue((folder / 'directory.log').is_dir())
        shutil.rmtree(self.home / '.dlor/logs')
        (self.home / '.dlor/logs').write_text('block logging')
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)

    def test_invalid_arguments_still_log_diagnostics_and_exact_status(self):
        self.generate()
        for name in ('install', 'uninstall'):
            with self.subTest(entry=name):
                result = self.run_script(name + '.sh')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                logs = list((self.home / '.dlor/logs/dlor-optiscaler' / name).glob('*.log'))
                self.assertEqual(len(logs), 1)
                self.assertIn(f'DLOR OptiScaler {name} exit status: 2', logs[0].read_text())

    def test_failed_logger_falls_back_to_console_without_stopping_game(self):
        recipe = self.fixture_recipe()
        # Only fail the recipe's tee, not the unchanged runner's independent tee.
        (self.bin / 'tee').write_text('#!/bin/bash\ncase "$*" in *dlor-optiscaler*) exit 1;; esac\nexec /usr/bin/tee "$@"\n')
        (self.bin / 'tee').chmod(0o755)
        final, env, _ = self.consumer_launch(recipe, self.game_command())
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        self.assertIn('fixture installer output', result.stdout)
        self.assertIn('GAMEPLAY-SENTINEL', result.stdout)

    def test_actual_consumer_cold_off_adds_no_wine_override(self):
        recipe = self.fixture_recipe()
        self.env.pop('DLOR_SCRIPT_REVISION')
        self.env['WINEDLLOVERRIDES'] = 'version=n'
        final, env, variables = self.consumer_launch(recipe, self.game_command(), enabled=False)
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.trace.read_text())['argv'], ['uninstall', str(self.game)])
        self.assertEqual(json.loads((self.root / 'game-result.json').read_text())['env']['WINEDLLOVERRIDES'], 'version=n')
        self.assertNotIn('WINEDLLOVERRIDES', variables)
        self.assertEqual(list(self.game.iterdir()), [])
        self.assertEqual(self.fetches.read_text().splitlines(), ['uninstall.sh', 'downloads.json', 'loader.py', 'installer.py', 'artifacts.py', 'game_discovery.py', 'update_optiscaler_config.py'])

    def test_actual_consumer_failed_entry_transfer_continues_with_declared_policy(self):
        recipe = self.fixture_recipe()
        curl = self.bin / 'curl'
        normal = curl.read_text()
        for enabled in (True, False):
            for variant in ('offline', 'partial', 'empty'):
                with self.subTest(enabled=enabled, transfer=variant):
                    self.trace.unlink(missing_ok=True)
                    # The stock runner checks completion/nonempty, not an outer
                    # SHA. Failed bytes must not execute even if valid shell.
                    body = ("target = args[args.index('--output') + 1]\n"
                            "pathlib.Path(target).write_text('echo UNVERIFIED-ENTRY\\n')\n"
                            "sys.exit(18)\n") if variant == 'partial' else (
                            "target = args[args.index('--output') + 1]\n"
                            "pathlib.Path(target).write_bytes(b'')\nsys.exit(0)\n")
                    curl.write_text(normal if variant == 'offline' else
                                    f'#!{sys.executable} -I\nimport pathlib, sys\nargs = sys.argv[1:]\n' + body)
                    self.env['FIXTURE_OFFLINE'] = '1' if variant == 'offline' else '0'
                    self.env['WINEDLLOVERRIDES'] = 'ambient=n'
                    final, env, variables = self.consumer_launch(recipe, self.game_command('fallback arg'), enabled)
                    result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                    self.assertFalse(self.trace.exists())
                    self.assertNotIn('UNVERIFIED-ENTRY', result.stdout)
                    self.assertIn('continuing game launch', result.stderr)
                    observed = json.loads((self.root / 'game-result.json').read_text())
                    self.assertEqual(observed['argv'], ['fallback arg', '--original-arg'])
                    self.assertEqual(observed['env']['WINEDLLOVERRIDES'], 'dxgi=n,b' if enabled else 'ambient=n')
                    self.assertEqual('WINEDLLOVERRIDES' in variables, enabled)
                    self.assertEqual(list(self.root.glob('dlor-script.*.sh')), [])

    def test_module_transfer_failure_never_publishes_partial_or_executes_source(self):
        self.generate()
        curl = self.bin / 'curl'
        normal = curl.read_text()
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        for variant in ('offline', 'partial', 'wrong-sha', 'empty'):
            with self.subTest(transfer=variant):
                self.trace.unlink(missing_ok=True)
                payload = b'' if variant == 'empty' else b'raise Exception("UNVERIFIED-MODULE")\n'
                body = (f"pathlib.Path(args[args.index('-o') + 1]).write_bytes({payload!r})\n"
                        f"sys.exit({18 if variant == 'partial' else 0})\n")
                if variant == 'offline':
                    body = 'sys.exit(22)\n'
                curl.write_text(normal.replace("if os.environ.get('FIXTURE_OFFLINE') == '1': sys.exit(22)",
                    "if name == 'installer.py':\n" + ''.join('    ' + line + '\n' for line in body.splitlines())))
                self.env['FIXTURE_OFFLINE'] = '0'
                result = self.run_script('install.sh', self.game)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(self.trace.exists())
                self.assertNotIn('UNVERIFIED-MODULE', result.stdout + result.stderr)
                self.assertEqual(sorted(p.name for p in cache.iterdir()), ['downloads.json', 'loader.py'])
        curl.write_text(normal)
        self.env['FIXTURE_OFFLINE'] = '0'
        self.assertEqual(self.run_script('install.sh', self.game).returncode, 0)
        self.assertEqual(sorted(p.name for p in cache.iterdir()), ['artifacts.py', 'downloads.json', 'game_discovery.py', 'installer.py', 'loader.py', 'update_optiscaler_config.py'])
        self.trace.unlink()
        # A corrupt prior cache is not executable when repair is unavailable.
        (cache / 'installer.py').write_text('raise Exception("UNVERIFIED-MODULE")\n')
        self.env['FIXTURE_OFFLINE'] = '1'
        result = self.run_script('uninstall.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.trace.exists())
        self.assertNotIn('UNVERIFIED-MODULE', result.stdout + result.stderr)
        self.assertFalse(list(cache.glob('.*')))

    def test_module_hash_covers_trailing_source_newlines(self):
        self.generate()
        source = self.scripts / 'installer.py'
        source.write_bytes(source.read_bytes() + b'\n')
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source checksum mismatch', result.stdout)
        self.assertFalse(self.trace.exists())

    def test_private_cache_file_guards_remain_enforced(self):
        self.generate()
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        cache.mkdir(parents=True, mode=0o700)
        cache.chmod(0o755)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source cache must be private', result.stdout)
        cache.chmod(0o700)
        outside = self.root / 'foreign.py'
        outside.write_text('foreign bytes')
        (cache / 'installer.py').symlink_to(outside)
        result = self.run_script('install.sh', self.game)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe source cache file', result.stdout)
        self.assertEqual(outside.read_text(), 'foreign bytes')
        self.assertFalse(self.fetches.exists())

    def test_failed_preparation_returns_nonzero_and_logs_exact_status(self):
        self.generate()
        self.env['FIXTURE_FAIL'] = '1'
        for action in ('install', 'uninstall'):
            with self.subTest(action=action):
                result = self.run_script(action + '.sh', self.game)
                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                logs = list((self.home / '.dlor/logs/dlor-optiscaler' / action).glob('*.log'))
                self.assertEqual(len(logs), 1)
                self.assertIn(f'{action} exit status: 7', logs[0].read_text())

    def test_source_loader_cancels_only_its_auxiliary_download(self):
        import signal
        import time
        self.generate()
        curl = self.bin / 'curl'
        normal = curl.read_text()
        ready = self.root / 'source-download-pids'
        self.env['FIXTURE_READY'] = str(ready)
        curl.write_text(normal.replace('args = sys.argv[1:]',
            "import time\n"
            "if sys.argv[-1].endswith('/installer.py'):\n"
            "    pathlib.Path(os.environ['FIXTURE_READY']).write_text(str(os.getpid()) + ':' + str(os.getppid()))\n"
            "    while True: time.sleep(0.02)\n"
            "args = sys.argv[1:]"))
        sentinel = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'])
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(signal=signum):
                    ready.unlink(missing_ok=True)
                    process = subprocess.Popen(['bash', str(self.scripts / 'install.sh'), str(self.game)],
                                               env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               start_new_session=True)
                    try:
                        deadline = time.monotonic() + 5
                        while not ready.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue(ready.exists(), 'source loader never reached downloader')
                        downloader, loader = map(int, ready.read_text().split(':'))
                        # This is the source loader's own signal contract, NOT
                        # parent-only cancellation of the unchanged stock runner.
                        os.kill(loader, signum)
                        stdout, stderr = process.communicate(timeout=4)
                        self.assertEqual(process.returncode, 128 + signum, stdout + stderr)
                        self.assertFalse(Path(f'/proc/{downloader}').exists())
                        self.assertFalse(self.trace.exists())
                        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
                        self.assertEqual(sorted(p.name for p in cache.iterdir()), ['downloads.json', 'loader.py'])
                        self.assertIsNone(sentinel.poll())
                    finally:
                        if process.poll() is None:
                            # Release only the known fixture downloader/loader.
                            if ready.exists():
                                downloader, loader = map(int, ready.read_text().split(':'))
                                for pid in (downloader, loader):
                                    try: os.kill(pid, signal.SIGKILL)
                                    except ProcessLookupError: pass
                            process.kill()
                        process.communicate(timeout=5)
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=5)

if __name__ == '__main__':
    unittest.main()
