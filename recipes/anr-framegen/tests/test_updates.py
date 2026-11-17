"""V.B14 journal compatibility using both verified official release archives."""
import copy
import json
import os
from pathlib import Path
import unittest
import test_lifecycle as fixtures

OLD_ARCHIVE = Path(os.environ.get('ANR_TEST_PREVIOUS_ARCHIVE', Path(os.environ['TMPDIR']) / 'anr-fg-V.B14-addon.zip'))


class Updates(fixtures.Fixture):
    def old_engine(self):
        engine = self.engine()
        manifest = copy.deepcopy(engine.manifest)
        manifest['downloads']['addon'] = manifest['downloads'].pop('regression_vb14')
        # Published legacy runtime owned only the two provider selectors.
        manifest.pop('activation_policy', None)
        return fixtures.runtime().Engine(self.home, manifest, fetch=lambda _: OLD_ARCHIVE.read_bytes())

    def test_vb14_off_uses_exact_old_journal_without_payload_acquisition(self):
        old = self.old_engine()
        old.run('install', self.game)
        for archive in old.cache.glob('*.zip'):
            archive.unlink()
        engine = self.engine()
        engine.payload = lambda: self.fail('OFF must not acquire payload')
        engine.fetch = lambda _: self.fail('OFF must not download')
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertEqual(self.ini.stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.game / 'custom').exists())

    def test_vb14_install_updates_unchanged_payload_and_restores_original_config(self):
        self.original = self.original.replace(b'FGInput = auto', b'DisableHudless=true\r\nFGInput = auto')
        self.ini.write_bytes(self.original)
        core = self.game / 'dxgi.dll'
        core.write_bytes(b'unchanged existing OptiScaler core fixture')
        game_provider = self.game / 'nvngx_dlssg.dll'
        game_provider.write_bytes(b'unchanged existing game provider fixture')
        old = self.old_engine()
        old.run('install', self.game)
        self.ini.write_bytes(self.ini.read_bytes().replace(b'X=1', b'X=edited'))
        self.ini.chmod(0o600)
        engine = self.engine()
        engine.run('install', self.game)
        dest = self.game / 'custom/Apex Neural Rendering FG'
        for name, content in engine.payload().items():
            self.assertEqual((dest / name).read_bytes(), content, name)
        state = json.loads(next(p for p in engine.cache.glob('*.json') if not p.name.endswith('.pending.json')).read_bytes())
        self.assertEqual(state['provenance'], engine.manifest['downloads']['addon'])
        self.assertEqual(fixtures.runtime().decoded(state['original']), self.original)
        self.assertIn(b'[FrameGen]\r\nDisableHudless=false\r\n', self.ini.read_bytes())
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'X=1', b'X=edited'))
        self.assertEqual(self.ini.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.game / 'custom').exists())
        self.assertEqual(core.read_bytes(), b'unchanged existing OptiScaler core fixture')
        self.assertEqual(game_provider.read_bytes(), b'unchanged existing game provider fixture')

    def test_journal_null_hash_cannot_authorize_a_payload_path(self):
        engine = self.engine()
        engine.run('install', self.game)
        journal = next(engine.cache.glob('*.json'))
        state = json.loads(journal.read_bytes())
        state['files']['dlssg/nvngx_dlssg.dll'] = None
        journal.write_text(json.dumps(state))
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'provenance'):
            engine.run('uninstall', self.game)

    def test_update_retains_edited_config_and_chmod_without_losing_old_claims(self):
        self.old_engine().run('install', self.game)
        dest = self.game / 'custom/Apex Neural Rendering FG'
        config = dest / 'dlssg/nr_fg.ini'
        provider = dest / 'dlssg/nvngx_dlssg.dll'
        old_provider = provider.read_bytes()
        config.write_bytes(config.read_bytes() + b'\n; user setting\n')
        edited_config = config.read_bytes()
        provider.chmod(0o600)
        self.ini.write_bytes(self.ini.read_bytes().replace(b'FGInput=nvngxfg', b'FGInput=fsr31'))
        engine = self.engine()
        engine.run('install', self.game)
        engine.run('install', self.game)
        self.assertEqual(provider.read_bytes(), old_provider)
        self.assertEqual(provider.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.read_bytes(), edited_config)
        journal = json.loads(next(engine.cache.glob('*.json')).read_bytes())
        self.assertEqual(journal['previous_provenance'], [engine.manifest['downloads']['regression_vb14']])
        for name in ('dlssg/nr_fg.ini', 'dlssg/nvngx_dlssg.dll'):
            self.assertEqual(journal['files'][name], next(v['sha256'] for v in journal['previous_provenance'][0]['members'].values() if v['path'] == name))
        engine.payload = lambda: self.fail('OFF may not unpack payloads')
        engine.run('uninstall', self.game)
        self.assertEqual(config.read_bytes(), edited_config)
        self.assertEqual(provider.read_bytes(), old_provider)
        self.assertEqual(provider.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'FGInput = auto', b'FGInput=fsr31'))

    def test_update_new_member_collision_refuses_even_identical_foreign_bytes(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        new_members = set(engine.payload()) - set(v['path'] for v in engine.manifest['downloads']['regression_vb14']['members'].values())
        foreign_name = sorted(new_members)[0]
        foreign = self.game / 'custom/Apex Neural Rendering FG' / foreign_name
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(engine.payload()[foreign_name])
        snapshot = self.snapshot()
        journal = next(engine.cache.glob('*.json')).read_bytes()
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign file'):
            engine.run('install', self.game)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(next(engine.cache.glob('*.json')).read_bytes(), journal)
        self.assertFalse(list(engine.cache.glob('*.pending.json')))

    def snapshot(self):
        return {str(p.relative_to(self.game)): (p.read_bytes(), p.stat().st_mode & 0o7777)
                for p in self.game.rglob('*') if p.is_file()}

    def test_old_interrupted_install_recovers_and_uninstalls_without_download(self):
        self.check_old_interruption('install')

    def test_old_interrupted_uninstall_recovers_without_download(self):
        self.check_old_interruption('uninstall')

    def check_old_interruption(self, action):
        old = self.old_engine()
        if action == 'uninstall':
            old.run('install', self.game)
        class Interrupted(type(old)):
            def applied(self, index):
                if index == 2:
                    raise RuntimeError('controlled old interruption')
        with self.assertRaisesRegex(RuntimeError, 'old interruption'):
            Interrupted(self.home, old.manifest, fetch=old.fetch).run(action, self.game)
        engine = self.engine()
        for archive in engine.cache.glob('*.zip'):
            archive.unlink()
        engine.payload = lambda: self.fail('OFF must not acquire payload')
        engine.fetch = lambda _: self.fail('OFF must not download')
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse((self.game / 'custom').exists())
        self.assertFalse(list(engine.cache.glob('*.pending.json')))

    def test_interrupted_update_off_recovers_without_any_archive(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        class Interrupted(type(engine)):
            def applied(self, index):
                if index == 2:
                    raise RuntimeError('controlled update interruption')
        with self.assertRaisesRegex(RuntimeError, 'update interruption'):
            Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('install', self.game)
        for archive in engine.cache.glob('*.zip'):
            archive.unlink()
        engine.payload = lambda: self.fail('OFF may not acquire payload')
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse((self.game / 'custom').exists())

    def test_pending_update_chmod_conflict_preserves_files_and_pending_journal(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        class Interrupted(type(engine)):
            def replay(self, *args):
                raise RuntimeError('controlled pending update')
        with self.assertRaisesRegex(RuntimeError, 'pending update'):
            Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('install', self.game)
        provider = self.game / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll'
        provider.chmod(0o600)
        snapshot = self.snapshot()
        pending = next(engine.cache.glob('*.pending.json'))
        pending_bytes = pending.read_bytes()
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign edit'):
            engine.run('uninstall', self.game)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(pending.read_bytes(), pending_bytes)

    def test_untrusted_prior_descriptor_refuses_before_download_or_game_changes(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        journal = next(engine.cache.glob('*.json'))
        state = json.loads(journal.read_bytes())
        state['provenance']['tag'] = 'FG-V.B15'
        journal.write_text(json.dumps(state))
        engine.fetch = lambda _: self.fail('invalid prior provenance must not download')
        snapshot = self.snapshot()
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'provenance'):
            engine.run('install', self.game)
        self.assertEqual(self.snapshot(), snapshot)

    def test_recorded_prior_release_removal_does_not_require_manifest_history(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        engine.manifest['downloads'].pop('regression_vb14')
        engine.fetch = lambda _: self.fail('OFF must not fetch archive or history')
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse((self.game / 'custom').exists())

    def test_recorded_prior_release_update_does_not_require_manifest_history(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        engine.manifest['downloads'].pop('regression_vb14')
        engine.run('install', self.game)
        self.assertEqual((self.game / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll').read_bytes(), engine.payload()['dlssg/nvngx_dlssg.dll'])
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)

    def test_recorded_descriptor_shape_cannot_escape_addon_policy(self):
        self.old_engine().run('install', self.game)
        engine = self.engine()
        journal = next(engine.cache.glob('*.json'))
        original = json.loads(journal.read_bytes())
        snapshot = self.snapshot()
        for mutation in ('repository', 'url', 'asset', 'archive-hash', 'revision', 'member-path', 'member-hash', 'member-size'):
            with self.subTest(mutation=mutation):
                state = copy.deepcopy(original)
                desc = state['provenance']
                if mutation == 'repository':
                    desc['repository'] = 'someone/else'
                elif mutation == 'url':
                    desc['url'] = 'https://untrusted.invalid/addon.zip'
                elif mutation == 'asset':
                    desc['asset'] = 'anr-full.zip'
                elif mutation == 'archive-hash':
                    desc['sha256'] = 'not-a-digest'
                elif mutation == 'revision':
                    desc['code_revision'] = 'main'
                elif mutation == 'member-path':
                    desc['members']['README.txt']['path'] = '../../OptiScaler.ini'
                elif mutation == 'member-hash':
                    desc['members']['README.txt']['sha256'] = 'not-a-digest'
                else:
                    desc['members']['README.txt']['size'] = -1
                journal.write_text(json.dumps(state))
                engine.fetch = lambda _: self.fail('invalid journal may not download')
                with self.assertRaisesRegex(fixtures.runtime().Refusal, 'policy'):
                    engine.run('uninstall', self.game)
                self.assertEqual(self.snapshot(), snapshot)


if __name__ == '__main__':
    unittest.main()
