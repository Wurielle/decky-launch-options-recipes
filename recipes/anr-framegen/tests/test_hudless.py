"""HUD compositing ownership; portable bytes/journal tests, not gameplay."""
import json
import test_lifecycle as fixtures
import test_updates


class Hudless(fixtures.Fixture):
    old_engine = test_updates.Updates.old_engine

    def test_fresh_true_and_absent_are_owned_and_exactly_restored(self):
        for value in (None, b'true'):
            with self.subTest(value=value):
                original = self.original if value is None else self.original.replace(
                    b'FGInput = auto', b'DisableHudless=true\r\nFGInput = auto')
                self.ini.write_bytes(original)
                engine = self.engine()
                engine.run('install', self.game)
                self.assertIn(b'DisableHudless=false\r\n', self.ini.read_bytes())
                self.ini.chmod(0o600)
                engine.run('uninstall', self.game)
                self.assertEqual(self.ini.read_bytes(), original)
                self.assertEqual(self.ini.stat().st_mode & 0o777, 0o600)

    def test_upgrade_restores_latest_displaced_value_not_old_baseline(self):
        self.original = self.original.replace(b'FGInput = auto', b'DisableHudless=auto\r\nFGInput = auto')
        self.ini.write_bytes(self.original)
        self.old_engine().run('install', self.game)
        self.ini.write_bytes(self.ini.read_bytes().replace(b'DisableHudless=auto', b'  DisableHudless = true').replace(b'X=1', b'X=2'))
        engine = self.engine()
        engine.run('install', self.game)
        self.assertIn(b'DisableHudless=false\r\n', self.ini.read_bytes())
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'DisableHudless=auto', b'  DisableHudless = true').replace(b'X=1', b'X=2'))

    def test_later_foreign_hud_edit_survives_reinstall_and_off(self):
        engine = self.engine()
        engine.run('install', self.game)
        self.assertIn(b'DisableHudless=false', self.ini.read_bytes())
        self.ini.write_bytes(self.ini.read_bytes().replace(b'DisableHudless=false', b'DisableHudless=true').replace(b'X=1', b'X=2'))
        engine.run('install', self.game)
        self.assertIn(b'DisableHudless=true', self.ini.read_bytes())
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'[Other]', b'DisableHudless=true\r\n[Other]').replace(b'X=1', b'X=2'))

    def test_legacy_off_does_not_restore_unowned_hud_setting(self):
        self.old_engine().run('install', self.game)
        self.ini.write_bytes(self.ini.read_bytes().replace(b'[Other]', b'DisableHudless=true\r\n[Other]'))
        self.engine().run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'[Other]', b'DisableHudless=true\r\n[Other]'))

    def test_new_install_upgrade_and_off_interrupted_after_ini_recover_without_archive(self):
        for kind in ('fresh', 'upgrade', 'off'):
            with self.subTest(kind=kind):
                self.ini.write_bytes(self.original)
                if kind == 'upgrade':
                    self.old_engine().run('install', self.game)
                engine = self.engine()
                if kind == 'off':
                    engine.run('install', self.game)
                ini = self.ini
                class Interrupted(type(engine)):
                    def applied(self, index):
                        # INI is last on Install and first on OFF.
                        if (kind == 'off' and index == 0) or (kind != 'off' and b'DisableHudless=false' in ini.read_bytes()):
                            raise RuntimeError('controlled HUD interruption')
                with self.assertRaisesRegex(RuntimeError, 'HUD interruption'):
                    Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('uninstall' if kind == 'off' else 'install', self.game)
                pending = json.loads(next(engine.cache.glob('*.pending.json')).read_bytes())
                self.assertEqual(pending['policy'], 'anr-fg-three-keys-v1')
                for archive in engine.cache.glob('*.zip'):
                    archive.unlink()
                engine.fetch = lambda _: self.fail('OFF may not download')
                engine.run('uninstall', self.game)
                self.assertEqual(self.ini.read_bytes(), self.original)
                self.assertFalse(list(engine.cache.glob('*.pending.json')))

    def test_legacy_policy_cannot_authorize_three_key_recovery(self):
        engine = self.engine()
        class Interrupted(type(engine)):
            def replay(self, *args):
                raise RuntimeError('controlled pending HUD')
        with self.assertRaisesRegex(RuntimeError, 'pending HUD'):
            Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('install', self.game)
        pending = next(engine.cache.glob('*.pending.json'))
        plan = json.loads(pending.read_bytes())
        self.assertEqual(plan['policy'], 'anr-fg-three-keys-v1')
        plan['policy'] = 'anr-fg-two-keys-v1'
        pending.write_text(json.dumps(plan))
        before = self.ini.read_bytes()
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'policy'):
            engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), before)
        self.assertTrue(pending.exists())
