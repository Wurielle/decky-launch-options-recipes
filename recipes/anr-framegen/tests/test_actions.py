"""Compile the real recipe and verify its installer dropdown contract."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
REVISION = 'a' * 40
VALUE_ID = 'optiscaler-framegen-anr'


class Actions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        (output / 'package.json').write_text('{"type":"module"}')
        subprocess.run([str(ROOT / 'node_modules/.bin/tsc'), '-p', str(ROOT / 'tsconfig.recipes.json'),
                        '--outDir', str(output)], check=True, capture_output=True, text=True)
        env = dict(os.environ, RECIPE_REPOSITORY_OWNER='Wurielle',
                   RECIPE_REPOSITORY_NAME='decky-launch-options-recipes', RECIPE_COMMIT_SHA=REVISION)
        module = output / 'recipes/anr-framegen/index.js'
        script = f'import recipe from {json.dumps(module.as_uri())}; console.log(JSON.stringify(recipe))'
        cls.recipe = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', script], env=env, text=True))
        cls.options = cls.recipe['launchOptions']

    def test_exact_hierarchical_ids_and_ordered_dropdown_values(self):
        self.assertEqual([option['id'] for option in self.options], [VALUE_ID + '-' + action for action in ('none', 'install', 'uninstall')])
        self.assertEqual([option['valueName'] for option in self.options], ['None', 'Install', 'Uninstall'])
        for option in self.options:
            self.assertEqual(option['valueId'], VALUE_ID)
            self.assertEqual(option['group'], 'OptiScaler')
            self.assertEqual(option['name'], 'OptiScaler FrameGen ANR')

    def test_none_is_the_only_inert_default_and_off_never_removes_files(self):
        self.assertEqual(len(self.options), 3)
        none, install, uninstall = self.options
        self.assertEqual(none['on'], '')
        self.assertEqual([o['id'] for o in self.options if o.get('fallbackValue')], [VALUE_ID + '-none'])
        for option in self.options:
            self.assertEqual(option['off'], '')
            self.assertFalse(option['enableGlobally'])
        self.assertEqual(install['on'], f'~/.dlor/run anr-framegen install {REVISION} -- %command%')
        self.assertEqual(uninstall['on'], f'~/.dlor/run anr-framegen uninstall {REVISION} -- %command%')

    def test_actual_consumer_runs_only_the_selected_action(self):
        location = os.environ.get('DLO_CONSUMER_SOURCE')
        if not location:
            self.skipTest('Set DLO_CONSUMER_SOURCE to DLO a3996e590b61f0a985a0182cb89278a4850e39f6')
        source = Path(location)
        for name, expected in {
            'run.py': '2e78c2b0739595ab00eab7bfc21a8778c15cbb2cfe2dc8c0beaa1e705655860e',
            'shared.py': 'e12a4ccf2a8e957ebd99cab1677aa00704dc9ae98b12d34c24c98d9aeb4fab0b',
        }.items():
            self.assertEqual(hashlib.sha256((source / name).read_bytes()).hexdigest(), expected)
        shared = runpy.run_path(str(source / 'shared.py'))
        with patch.dict(sys.modules, shared=types.SimpleNamespace(**shared)):
            spec = importlib.util.spec_from_file_location('anr_dlo_actions', source / 'run.py')
            assert spec is not None and spec.loader is not None
            consumer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(consumer)
        home = Path(self.temporary.name) / 'consumer-home'
        home.mkdir()
        runpy.run_path(str(ROOT / 'scripts/runner_test_support.py'))['install_runner'](home)
        for selected in (None, 'none', 'install', 'uninstall'):
            with self.subTest(selected=selected):
                state = {VALUE_ID + '-' + action: action == selected for action in ('none', 'install', 'uninstall')}
                settings = {'launchOptions': self.options, 'profiles': {'123': {'state': state, 'originalLaunchOptions': '%command%'}}}
                with patch.object(sys, 'argv', ['run.py', '/harmless-game', 'literal argument']), patch.dict(os.environ, HOME=str(home)):
                    final, variables = consumer.get_final_args_details(settings, '123')
                expected = ['/harmless-game', 'literal argument']
                if selected in ('install', 'uninstall'):
                    expected = [str(home / '.dlor/run'), 'anr-framegen', selected, REVISION, '--', *expected]
                self.assertEqual(final, expected)
                self.assertEqual(variables, {})


if __name__ == '__main__':
    unittest.main()
