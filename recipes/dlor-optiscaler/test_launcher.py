"""Offline entrypoint fixtures; these do not validate games or provider payloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).with_name('scripts')
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
        self.game = self.root / 'Game Space'
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
import artifacts, game_discovery
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print('fixture usage: ACTION GAME_ROOT', file=sys.stderr)
        return 2
    record = {'argv': argv, 'env': {k: v for k, v in os.environ.items() if k in ('STEAM_RUNTIME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PATH', 'PYTHONHOME', 'PYTHONPATH', 'WINEDLLOVERRIDES', 'work', 'status', 'entry_name', 'helper_pid', 'logger_pid', 'merged', 'console_out', 'console_err')}, 'isolated': sys.flags.isolated,
              'bytecode': sys.dont_write_bytecode}
    if '--argv-file' in argv:
        record['game_argv'] = json.loads(pathlib.Path(argv[argv.index('--argv-file') + 1]).read_text())
    pathlib.Path(os.environ['FIXTURE_TRACE']).write_text(json.dumps(record))
    print('fixture installer output', flush=True)
    print('fixture installer stderr', file=sys.stderr, flush=True)
    if os.environ.get('FIXTURE_FAIL') == '1': return 7
    if '--result' in argv:
        pathlib.Path(argv[argv.index('--result') + 1]).write_text(json.dumps({'proxy': os.environ.get('FIXTURE_PROXY', 'dxgi'), 'target': argv[1]}))
    return 0
''')
        for name in ('artifacts.py', 'game_discovery.py'):
            (self.scripts / name).write_text('FIXTURE = True\n')

    def generate(self):
        updater = SCRIPTS / 'update-source-hashes.py'
        self.assertTrue(updater.is_file(), 'maintainer bootstrap generator is missing')
        shutil.copyfile(updater, self.scripts / updater.name)
        result = subprocess.run([sys.executable, '-I', '-B', str(self.scripts / updater.name)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_script(self, name, *args):
        return subprocess.run(['bash', str(self.scripts / name), *map(str, args)],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_cold_direct_install_fetches_verified_isolated_source(self):
        self.generate()
        result = self.run_script('install.sh', self.game)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        trace = json.loads(self.trace.read_text())
        self.assertEqual(trace['argv'], ['install', str(self.game)])
        self.assertEqual(trace['isolated'], 1)
        self.assertTrue(trace['bytecode'])
        self.assertEqual(self.fetches.read_text().splitlines(), ['installer.py', 'artifacts.py', 'game_discovery.py'])
        logs = list((self.home / '.dlor/logs/dlor-optiscaler/install').glob('*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('fixture installer stderr', logs[0].read_text())
        self.assertFalse(list(self.home.rglob('*.pyc')))

    def game_command(self, *extra):
        output = self.root / 'game-result.json'
        code = ("import json, os, pathlib, sys; "
                "pathlib.Path(sys.argv[1]).write_text(json.dumps({'argv': sys.argv[2:], 'env': {k: v for k, v in os.environ.items() if k in ('STEAM_RUNTIME', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PATH', 'PYTHONHOME', 'PYTHONPATH', 'WINEDLLOVERRIDES', 'work', 'status', 'entry_name', 'helper_pid', 'logger_pid', 'merged', 'console_out', 'console_err', 's', 'REPLY', 'p', 'f', 'COPROC', 'COPROC_PID', 'ORIGINAL_TEST_VALUE', 'DLOR_SCRIPT_REVISION', 'DLOR_REPOSITORY')}})); "
                "print('GAMEPLAY-SENTINEL', flush=True); sys.exit(23)")
        return [sys.executable, '-I', '-B', '-c', code, str(output), *extra]

    def test_cold_launcher_preserves_game_handoff_merges_wine_and_drains_logs(self):
        self.generate()
        self.env.update(STEAM_RUNTIME='/steam/runtime', LD_LIBRARY_PATH='/steam/libraries',
                        PYTHONHOME='/steam/python', PYTHONPATH='/steam/python-modules',
                        WINEDLLOVERRIDES='dinput8=n;DXGI,version=b;foo=;dxgi.dll=b',
                        DLOR_OPTISCALER_ACTION='install')
        command = self.game_command('space arg', '', 'semi;colon', 'quote"arg', 'line\nbreak')
        result = self.run_script('launch.sh', *command)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        game = json.loads((self.root / 'game-result.json').read_text())
        self.assertEqual(game['argv'], command[6:])
        self.assertEqual(game['env']['WINEDLLOVERRIDES'], 'dinput8=n;version=b;foo=;dxgi=n,b')
        for key in ('STEAM_RUNTIME', 'LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH', 'PATH'):
            self.assertEqual(game['env'][key], self.env[key])
        trace = json.loads(self.trace.read_text())
        self.assertEqual(trace['game_argv'], command)
        self.assertNotIn('PYTHONHOME', trace['env'])
        self.assertNotIn('PYTHONPATH', trace['env'])
        self.assertNotIn('STEAM_RUNTIME', trace['env'])
        self.assertEqual(sorted(self.fetches.read_text().splitlines()),
                         sorted(['install.sh', 'uninstall.sh', 'installer.py', 'artifacts.py', 'game_discovery.py']))
        logs = list((self.home / '.dlor/logs/dlor-optiscaler').rglob('*.log'))
        self.assertEqual(len(logs), 2)
        self.assertTrue(all('GAMEPLAY-SENTINEL' not in p.read_text() for p in logs))
        self.assertIn('GAMEPLAY-SENTINEL', result.stdout)

    def compiled_recipe(self):
        repo = SCRIPTS.parents[2]
        compiled = self.root / 'compiled'
        result = subprocess.run([shutil.which('node') or 'node', str(repo / 'node_modules/typescript/bin/tsc'),
                                 str(SCRIPTS.parent / 'index.ts'), '--target', 'ES2020', '--module', 'nodenext',
                                 '--moduleResolution', 'nodenext', '--skipLibCheck', '--outDir', str(compiled)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (compiled / 'package.json').write_text('{"type":"module"}')
        result = subprocess.run([shutil.which('node') or 'node', '--input-type=module', '-e',
                                 f"import recipe from '{(compiled / 'dlor-optiscaler/index.js').as_uri()}'; console.log(JSON.stringify(recipe))"],
                                env=dict(self.env, RECIPE_COMMIT_SHA=REVISION,
                                         RECIPE_REPOSITORY_OWNER='Wurielle',
                                         RECIPE_REPOSITORY_NAME='decky-launch-options-recipes'),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

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
        import hashlib
        self.generate()
        recipe = self.compiled_recipe()
        # Only the source transport is substituted: full real shell entrypoints
        # still verify and run the explicitly synthetic installer modules.
        actual = hashlib.sha256((SCRIPTS / 'launch.sh').read_bytes()).hexdigest()
        fixture = hashlib.sha256((self.scripts / 'launch.sh').read_bytes()).hexdigest()
        for action in ('on', 'off'):
            self.assertIn(actual, recipe['launchOptions'][0][action])
            recipe['launchOptions'][0][action] = recipe['launchOptions'][0][action].replace(actual, fixture)
        return recipe

    def test_actual_consumer_runs_independent_bootstrap_without_revision_from_runner(self):
        recipe = self.fixture_recipe()
        acquisition_pid = self.root / 'successful-downloader.pid'
        curl = self.bin / 'curl'
        curl.write_text(curl.read_text().replace("name = url.rsplit('/', 1)[-1]",
            "name = url.rsplit('/', 1)[-1]\n"
            f"if name == 'launch.sh': pathlib.Path({str(acquisition_pid)!r}).write_text(str(os.getpid()))"))
        self.env.pop('DLOR_SCRIPT_REVISION')
        self.env.update(DLOR_REPOSITORY='ignored/foreign', DLOR_OPTISCALER_ACTION='install',
                        WINEDLLOVERRIDES='dinput8=n;dxgi,version=b')
        game = self.game_command('space arg', '', 'semi;colon', 'quote"arg', 'line\nbreak')
        final, env, variables = self.consumer_launch(recipe, game)
        self.assertEqual(final[:2], ['bash', '-c'])
        self.assertNotIn('--wrapper', final)
        self.assertEqual(variables, {'ORIGINAL_TEST_VALUE': 'original value',
                                    'DLOR_OPTISCALER_ACTION': 'install', 'DLOR_OPTISCALER_OPTIPATCHER': '0'})
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        observed = json.loads((self.root / 'game-result.json').read_text())
        self.assertEqual(observed['argv'], game[6:] + ['--original-arg'])
        self.assertEqual(observed['env']['WINEDLLOVERRIDES'], 'dinput8=n;version=b;dxgi=n,b')
        for key in ('REPLY', 'p', 'f', 'COPROC', 'COPROC_PID'):
            if key not in self.env:
                self.assertNotIn(key, observed['env'], 'bootstrap leaked acquisition bookkeeping')
        self.assertEqual(self.fetches.read_text().splitlines()[0], 'launch.sh')
        self.assertFalse(Path(f'/proc/{int(acquisition_pid.read_text())}').exists(), 'successful downloader was not reaped')

    def test_actual_consumer_preserves_shared_source_context_for_nested_recipes(self):
        import runpy
        recipe = self.fixture_recipe()
        runpy.run_path(str(SCRIPTS.parents[2] / 'scripts/runner_test_support.py'))['install_runner'](self.home)
        marker = self.root / 'custom-helper-context'
        self.env.update(DLOR_SCRIPT_REVISION='b' * 40, DLOR_REPOSITORY='Other/Recipes',
                        FIXTURE_CUSTOM_CONTEXT=str(marker),
                        FIXTURE_CUSTOM_HELPER_URL=f'https://raw.githubusercontent.com/Other/Recipes/{REVISION}/recipes/fixture/scripts/custom.sh')
        (self.scripts / 'custom.sh').write_text(
            '#!/bin/bash\nprintf "%s\\n" "$DLOR_REPOSITORY:$DLOR_SCRIPT_REVISION" > "$FIXTURE_CUSTOM_CONTEXT"\n')
        helper = {'id': 'custom', 'on': f'~/.dlor/run fixture custom {REVISION} -- %command%',
                  'off': '', 'priority': -10}
        final, env, _ = self.consumer_launch(recipe, self.game_command(), helpers=(helper,))
        result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        self.assertTrue(marker.exists(), result.stdout + result.stderr)
        self.assertEqual(marker.read_text().strip(), 'Other/Recipes:' + 'b' * 40)
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
                expected = 'dinput8=n;version=b;dxgi=n,b' if enabled and not fail else self.env['WINEDLLOVERRIDES']
                self.assertEqual(observed['env']['WINEDLLOVERRIDES'], expected)
                self.assertNotIn('DLOR_SCRIPT_REVISION', variables)

    def test_actual_consumer_preserves_stdin_and_extra_fds_across_source_acquisition(self):
        recipe = self.fixture_recipe()
        # A downloader that tries to consume stdin must see EOF, not game input.
        curl = self.bin / 'curl'
        curl.write_text(curl.read_text().replace('args = sys.argv[1:]',
            "assert sys.stdin.buffer.read() == b'', 'downloader consumed game stdin'\nargs = sys.argv[1:]"))
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
                    "sys.exit(23)\n")
            game = [sys.executable, '-I', '-B', '-c', code, str(output), str(fd)]
            final, env, _ = self.consumer_launch(recipe, game)
            result = subprocess.run(final, env=env, input=b'game stdin\n', pass_fds=(fd,), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists(), result.stdout + result.stderr)
        self.assertEqual(fd_path.read_bytes(), b'inherited:game stdin\n')
        self.assertEqual(json.loads(output.read_text()), sorted({0, 1, 2, fd}))

    def test_actual_consumer_rejects_partial_or_wrong_launcher_and_falls_back(self):
        recipe = self.fixture_recipe()
        curl = self.bin / 'curl'
        normal = curl.read_text()
        self.env['WINEDLLOVERRIDES'] = 'version=b'
        for variant in ('offline', 'partial', 'wrong-sha', 'empty'):
            with self.subTest(variant=variant):
                self.trace.unlink(missing_ok=True)
                self.env['FIXTURE_OFFLINE'] = '1' if variant == 'offline' else '0'
                if variant == 'partial':
                    curl.write_text(f'#!{sys.executable}\nimport sys\nprint("echo UNVERIFIED-LAUNCHER")\nsys.exit(18)\n')
                elif variant == 'wrong-sha':
                    curl.write_text(f'#!{sys.executable}\nprint("echo UNVERIFIED-LAUNCHER")\n')
                elif variant == 'empty':
                    curl.write_text('#!/bin/bash\nexit 0\n')
                else:
                    curl.write_text(normal)
                final, env, _ = self.consumer_launch(recipe, self.game_command('fallback arg'))
                result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                self.assertFalse(self.trace.exists())
                self.assertNotIn('UNVERIFIED-LAUNCHER', result.stdout)
                self.assertIn('continuing original game', result.stderr)
                game = json.loads((self.root / 'game-result.json').read_text())
                self.assertEqual(game['argv'], ['fallback arg', '--original-arg'])
                self.assertEqual(game['env']['WINEDLLOVERRIDES'], 'version=b')

    def test_actual_consumer_hashes_complete_launcher_including_trailing_newlines(self):
        import hashlib
        recipe = self.fixture_recipe()
        launcher = self.scripts / 'launch.sh'
        original = launcher.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        for ending in (b'', b'\n', b'\n\n\n'):
            with self.subTest(ending=ending):
                self.trace.unlink(missing_ok=True)
                source = original.rstrip(b'\n') + ending
                launcher.write_bytes(source)
                pinned = hashlib.sha256(source).hexdigest()
                option = recipe['launchOptions'][0]
                option['on'] = option['on'].replace(digest, pinned)
                digest = pinned
                final, env, _ = self.consumer_launch(recipe, self.game_command())
                result = subprocess.run(final, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                self.assertTrue(self.trace.exists(), result.stdout + result.stderr)

    def test_generator_refreshes_recipe_digest_and_is_deterministic(self):
        import hashlib
        index = self.root / 'index.ts'
        index.write_text("const launchSha256 = '" + '0' * 64 + "'\n")
        self.generate()
        expected = hashlib.sha256((self.scripts / 'launch.sh').read_bytes()).hexdigest()
        self.assertIn("const launchSha256 = '" + expected + "'", index.read_text())
        before = {name: (self.scripts / name).read_bytes() for name in ('launch.sh', 'install.sh', 'uninstall.sh')}
        self.generate()
        self.assertEqual(before, {name: (self.scripts / name).read_bytes() for name in before})
        for name in before:
            result = subprocess.run(['bash', '-n', str(self.scripts / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_recipe_has_short_typed_toggle_and_none_only_dropdown_defaults(self):
        import hashlib
        recipe = self.compiled_recipe()
        self.assertEqual(recipe['name'], 'DLOR OptiScaler')
        toggle = recipe['launchOptions'][0]
        digest = hashlib.sha256((SCRIPTS / 'launch.sh').read_bytes()).hexdigest()
        consumer = self.actual_consumer()
        for action, key in [('install', 'on'), ('uninstall', 'off')]:
            option = toggle[key]
            self.assertTrue(option.startswith(f'DLOR_OPTISCALER_ACTION="{action}" bash -c '))
            self.assertLess(len(option), 1400)
            self.assertNotIn('\n', option)
            self.assertNotIn('--wrapper', option)
            self.assertIn(digest, option)
            self.assertIn(f'/{REVISION}/recipes/dlor-optiscaler/scripts/launch.sh', option)
            parsed = consumer.parse_launch_option(option)
            self.assertEqual(parsed['env_vars'], {'DLOR_OPTISCALER_ACTION': action})
            self.assertEqual(parsed['prefix'][:2], ['bash', '-c'])
            self.assertEqual(parsed['prefix'][3:], ['--'])
            self.assertEqual(parsed['pre_commands'], [])
            self.assertEqual(parsed['suffix'], [])
            body = parsed['prefix'][2]
            import shlex
            self.assertEqual(parsed['prefix'], shlex.split(option)[1:-1], 'DLO changed the exact Bash body')
            self.assertIn('/', body.split('=', 1)[0])
            self.assertNotIn('python', body)
            self.assertNotIn('eval', body)
        options = recipe['launchOptions'][1:]
        groups = {}
        for option in options:
            if 'valueId' in option:
                groups.setdefault(option['valueId'], []).append(option)
        self.assertEqual(set(groups), {'dlor-optiscaler-proxy', 'dlor-optiscaler-fsr-profile'})
        self.assertFalse(any('DLOR_OPTISCALER_CHANNEL' in o.get('on', '') for o in options))
        fsr = groups['dlor-optiscaler-fsr-profile']
        self.assertEqual([v['on'] for v in fsr], ['',
                         'DLOR_OPTISCALER_FSR_PROFILE="bundled"',
                         'DLOR_OPTISCALER_FSR_PROFILE="rdna23-int8"',
                         'DLOR_OPTISCALER_FSR_PROFILE="rdna34-official-411"',
                         'DLOR_OPTISCALER_FSR_PROFILE="rdna2-valve-411"'])
        self.assertTrue(all('third-party' in v['name'] for v in fsr))
        for values in groups.values():
            defaults = [v for v in values if v.get('fallbackValue')]
            self.assertEqual(len(defaults), 1)
            self.assertEqual((defaults[0]['valueName'], defaults[0]['on'], defaults[0]['off']), ('None', '', ''))
        self.assertTrue(any(o['on'] == 'DLOR_OPTISCALER_OPTIPATCHER="1"' for o in options))

    def test_actual_consumer_parent_only_termination_during_initial_download(self):
        import signal
        self.assert_initial_download_cancelled(signal.SIGTERM, 143)

    def test_actual_consumer_parent_only_interrupt_during_initial_download(self):
        import signal
        self.assert_initial_download_cancelled(signal.SIGINT, 130)

    def assert_initial_download_cancelled(self, signum, expected):
        import signal
        import time
        recipe = self.fixture_recipe()
        pid_file = self.root / 'downloader.pid'
        release = self.root / 'download-release'
        self.env.update(FIXTURE_DOWNLOAD_PID=str(pid_file), FIXTURE_DOWNLOAD_RELEASE=str(release))
        curl = self.bin / 'curl'
        curl.write_text(curl.read_text().replace("name = url.rsplit('/', 1)[-1]",
            "name = url.rsplit('/', 1)[-1]\n"
            "if name == 'launch.sh':\n"
            "    import time\n"
            "    print('INITIAL-DOWNLOAD-STDERR', file=sys.stderr, flush=True)\n"
            "    pid_file = pathlib.Path(os.environ['FIXTURE_DOWNLOAD_PID'])\n"
            "    ready = pid_file.with_suffix('.ready')\n"
            "    ready.write_text(str(os.getpid()))\n"
            "    ready.replace(pid_file)\n"
            "    while not pathlib.Path(os.environ['FIXTURE_DOWNLOAD_RELEASE']).exists(): time.sleep(0.02)"))
        command, env, variables = self.consumer_launch(recipe, self.game_command())
        self.assertEqual(command[:2], ['bash', '-c'])
        self.assertEqual(variables, {'ORIGINAL_TEST_VALUE': 'original value',
                                    'DLOR_OPTISCALER_ACTION': 'install', 'DLOR_OPTISCALER_OPTIPATCHER': '0'})
        # Same process group, deliberately not owned by the bootstrap: a broad
        # process-group/parent kill would wrongly terminate this sentinel.
        sentinel = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'])
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        downloader = None
        try:
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(pid_file.exists(), 'fixture never entered initial launch.sh download')
            downloader = int(pid_file.read_text())
            owned = []
            pid = downloader
            while pid != process.pid:
                self.assertGreater(pid, 1, 'downloader is not a descendant of this bootstrap')
                owned.append(pid)
                status = Path(f'/proc/{pid}/status').read_text()
                pid = int(next(line.split()[1] for line in status.splitlines() if line.startswith('PPid:')))
            self.assertFalse(self.trace.exists(), 'signal must precede installer entry')
            self.assertFalse((self.root / 'game-result.json').exists())
            process.send_signal(signum)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                self.fail('parent-only initial-download signal left bootstrap/downloader alive or output pipes open')
            self.assertEqual(process.returncode, expected, stdout + stderr)
            self.assertIn(b'INITIAL-DOWNLOAD-STDERR', stderr)
            for pid in owned:
                self.assertFalse(Path(f'/proc/{pid}').exists(), f'owned auxiliary {pid} was not terminated and reaped')
            self.assertIsNone(sentinel.poll(), 'cancellation signalled an unrelated process')
            self.assertFalse(self.trace.exists())
            self.assertFalse((self.root / 'game-result.json').exists(), 'cancelled launch executed Game')
        finally:
            # Never leak fixtures even when the pre-fix bootstrap ignores INT.
            # Kill the held downloader before releasing any source to the shell.
            if downloader is not None and Path(f'/proc/{downloader}').exists():
                try: os.kill(downloader, signal.SIGKILL)
                except ProcessLookupError: pass
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
            sentinel.terminate()
            sentinel.wait(timeout=5)

    def test_parent_only_termination_cancels_helpers_and_removes_private_handoff(self):
        import signal
        self.assert_cancelled(signal.SIGTERM, 143)

    def test_parent_only_interrupt_cancels_helpers_and_removes_private_handoff(self):
        import signal
        self.assert_cancelled(signal.SIGINT, 130)

    def test_actual_consumer_parent_only_termination_preserves_launch_cancellation(self):
        import signal
        self.assert_cancelled(signal.SIGTERM, 143, through_consumer=True)

    def test_actual_consumer_parent_only_interrupt_preserves_launch_cancellation(self):
        import signal
        self.assert_cancelled(signal.SIGINT, 130, through_consumer=True)

    def assert_cancelled(self, signum, expected, through_consumer=False):
        self.generate()
        other = self.root / 'dlor-optiscaler.otherlaunch'
        other.mkdir()
        (other / 'argv.json').write_text('other launch')
        self.env.update(DLOR_OPTISCALER_ACTION='install', FIXTURE_WAIT=str(self.root / 'release'))
        source = self.scripts / 'installer.py'
        source.write_text(source.read_text().replace("    print('fixture installer output', flush=True)",
            "    if os.environ.get('FIXTURE_WAIT'):\n"
            "        import time\n"
            "        while not pathlib.Path(os.environ['FIXTURE_WAIT']).exists(): time.sleep(0.02)\n"
            "    print('fixture installer output', flush=True)"))
        # Regenerate hashes around this explicitly slow, harmless fixture.
        result = subprocess.run([sys.executable, '-I', '-B', str(self.scripts / 'update-source-hashes.py')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        import signal
        import time
        command = ['bash', str(self.scripts / 'launch.sh'), *self.game_command()]
        env = self.env
        if through_consumer:
            recipe = self.fixture_recipe()
            command, env, _ = self.consumer_launch(recipe, self.game_command())
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not self.trace.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(self.trace.exists(), 'fixture never reached installer')
            trace = json.loads(self.trace.read_text())
            argv_file = Path(trace['argv'][trace['argv'].index('--argv-file') + 1])
            process.send_signal(signum)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                (self.root / 'release').touch()
                process.communicate(timeout=5)
                self.fail('parent-only signal left helper running')
            self.assertEqual(process.returncode, expected, stdout + stderr)
            self.assertFalse(argv_file.parent.exists())
            self.assertEqual((other / 'argv.json').read_text(), 'other launch')
            self.assertFalse((self.root / 'game-result.json').exists())
        finally:
            (self.root / 'release').touch()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()

    def test_shell_bookkeeping_does_not_overwrite_unrelated_exported_environment(self):
        self.generate()
        self.env['DLOR_OPTISCALER_ACTION'] = 'install'
        keys = ('work', 'status', 'entry_name', 'helper_pid', 'logger_pid', 'merged', 'console_out', 'console_err')
        for key in keys:
            self.env[key] = 'original-' + key
        result = self.run_script('launch.sh', *self.game_command())
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        game = json.loads((self.root / 'game-result.json').read_text())
        for key in keys:
            self.assertEqual(game['env'][key], self.env[key])

    def test_warm_install_and_cached_uninstall_are_offline(self):
        self.generate()
        self.env['DLOR_OPTISCALER_ACTION'] = 'install'
        self.assertEqual(self.run_script('launch.sh', *self.game_command()).returncode, 23)
        fetched = self.fetches.read_text()
        self.env['FIXTURE_OFFLINE'] = '1'
        self.assertEqual(self.run_script('launch.sh', *self.game_command()).returncode, 23)
        self.env['DLOR_OPTISCALER_ACTION'] = 'uninstall'
        self.env['WINEDLLOVERRIDES'] = 'dxgi=b;version=n'
        self.assertEqual(self.run_script('launch.sh', *self.game_command()).returncode, 23)
        self.assertEqual(self.fetches.read_text(), fetched)
        self.assertEqual(json.loads(self.trace.read_text())['argv'][0], 'uninstall')
        game = json.loads((self.root / 'game-result.json').read_text())
        self.assertEqual(game['env']['WINEDLLOVERRIDES'], self.env['WINEDLLOVERRIDES'])

    def test_failure_and_invalid_result_never_add_override(self):
        self.generate()
        self.env.update(DLOR_OPTISCALER_ACTION='install', WINEDLLOVERRIDES='version=b')
        for setting in ({'FIXTURE_FAIL': '1'}, {'FIXTURE_PROXY': 'not-a-proxy'}):
            with self.subTest(setting=setting):
                self.env.pop('FIXTURE_FAIL', None)
                self.env.pop('FIXTURE_PROXY', None)
                self.env.update(setting)
                result = self.run_script('launch.sh', *self.game_command())
                self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                game = json.loads((self.root / 'game-result.json').read_text())
                self.assertEqual(game['env']['WINEDLLOVERRIDES'], 'version=b')
        self.assertIn('continuing original game', result.stdout)

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

    def test_offline_tampered_entry_does_not_execute_or_reuse_a_success_result(self):
        self.generate()
        self.env.update(DLOR_OPTISCALER_ACTION='install', WINEDLLOVERRIDES='version=b')
        self.assertEqual(self.run_script('launch.sh', *self.game_command()).returncode, 23)
        self.trace.unlink()
        cache = self.home / '.dlor/cache/dlor-optiscaler/source' / REVISION
        (cache / 'install.sh').write_text('printf "UNVERIFIED-ENTRY"\n')
        self.env['FIXTURE_OFFLINE'] = '1'
        result = self.run_script('launch.sh', *self.game_command())
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertFalse(self.trace.exists())
        self.assertNotIn('UNVERIFIED-ENTRY', result.stdout)
        game = json.loads((self.root / 'game-result.json').read_text())
        self.assertEqual(game['env']['WINEDLLOVERRIDES'], 'version=b')
        self.assertIn('continuing original game', result.stdout)

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
        for key, value in [('DLOR_SCRIPT_REVISION', 'main'), ('DLOR_REPOSITORY', 'owner/../repo')]:
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
        for name in ('install', 'uninstall', 'launch'):
            with self.subTest(entry=name):
                result = self.run_script(name + '.sh')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                logs = list((self.home / '.dlor/logs/dlor-optiscaler' / name).glob('*.log'))
                self.assertEqual(len(logs), 1)
                self.assertIn(f'DLOR OptiScaler {name} exit status: 2', logs[0].read_text())

    def test_failed_logger_falls_back_to_console_without_stopping_game(self):
        self.generate()
        (self.bin / 'tee').write_text('#!/bin/bash\nexit 1\n')
        (self.bin / 'tee').chmod(0o755)
        self.env['DLOR_OPTISCALER_ACTION'] = 'install'
        result = self.run_script('launch.sh', *self.game_command())
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(self.trace.exists())
        self.assertIn('fixture installer output', result.stdout)
        self.assertIn('GAMEPLAY-SENTINEL', result.stdout)

    def test_game_inherits_original_extra_fd_without_logger_descriptors(self):
        self.generate()
        self.env['DLOR_OPTISCALER_ACTION'] = 'install'
        destination = self.root / 'fd-output'
        with destination.open('wb') as stream:
            fd = stream.fileno()
            code = ("import json, os, sys\n"
                    "os.write(int(sys.argv[1]), b'original descriptor:' + sys.stdin.buffer.read())\n"
                    "fds = []\n"
                    "for name in os.listdir('/proc/self/fd'):\n"
                    "    try: os.fstat(int(name)); fds.append(int(name))\n"
                    "    except OSError: pass\n"
                    "print('GAME-FDS=' + json.dumps(sorted(fds)), flush=True)\n"
                    "print('GAMEPLAY-SENTINEL', flush=True)\n"
                    "print('GAME-STDERR-SENTINEL', file=sys.stderr, flush=True)\n")
            result = subprocess.run(['bash', str(self.scripts / 'launch.sh'), sys.executable,
                                     '-I', '-B', '-c', code, str(fd)], env=self.env,
                                    pass_fds=(fd,), input=b'original stdin\n', capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(destination.read_bytes(), b'original descriptor:original stdin\n')
        observed = next(line.removeprefix('GAME-FDS=') for line in result.stdout.decode().splitlines()
                        if line.startswith('GAME-FDS='))
        self.assertEqual(json.loads(observed), sorted({0, 1, 2, fd}))
        self.assertIn(b'GAME-STDERR-SENTINEL', result.stderr)
        self.assertTrue(all('GAMEPLAY-SENTINEL' not in p.read_text() and 'GAME-STDERR-SENTINEL' not in p.read_text()
                            for p in (self.home / '.dlor/logs').rglob('*.log')))


if __name__ == '__main__':
    unittest.main()
