"""Additional reversible/safety contracts on real temporary trees and pinned bytes."""
import hashlib
import json
import os
from pathlib import Path
import unittest
import test_lifecycle as fixtures


class Contracts(fixtures.Fixture):

    def test_symlink_home_ancestor_is_canonicalized(self):
        real = self.home
        alias = self.base / 'alias'
        alias.symlink_to(self.base, target_is_directory=True)
        self.home = alias / 'home'
        engine = self.engine()
        self.assertEqual(engine.home, real)
        engine.run('install', self.game)
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)

    def test_auto_uses_case_varied_optiscaler_subdirectory(self):
        main = self.game / 'oPtIsCaLeR'
        main.mkdir()
        self.engine().run('install', self.game)
        self.assertTrue((main / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll').is_file())
        self.engine().run('uninstall', self.game)
        self.assertTrue(main.is_dir())
        self.assertFalse(list(main.iterdir()))

    def test_missing_explicit_native_path_falls_back_without_creating_it(self):
        self.ini.write_bytes(self.original + b'[Libraries]\nOptiDllPath=missing\\library\n')
        self.engine().run('install', self.game)
        self.assertFalse((self.game / 'missing').exists())
        self.assertTrue((self.game / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll').is_file())

    def test_absolute_z_path_honors_case_and_unicode_component_boundaries(self):
        main = self.game / 'Libß'
        main.mkdir()
        configured = str(main).replace('Libß', 'LIBSS')
        self.ini.write_bytes(self.original + b'[Libraries]\nOptiDllPath=Z:' + configured.encode() + b'\n')
        self.engine().run('install', self.game)
        self.assertTrue((main / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll').is_file())

    def test_traversal_and_external_library_paths_fail_closed(self):
        for value in ('../outside', '/not/in/game', 'C:\\unknown', 'dir/../../outside'):
            with self.subTest(value=value):
                self.ini.write_bytes(self.original + b'[Libraries]\nOptiDllPath=' + value.encode() + b'\n')
                with self.assertRaises(fixtures.runtime().Refusal):
                    self.engine().run('install', self.game)
                self.assertEqual(self.fetches, [])
                self.assertFalse((self.game / 'custom').exists())

    def test_off_never_reads_or_reacquires_payload(self):
        engine = self.engine()
        engine.run('install', self.game)
        for archive in engine.cache.glob('*.zip'):
            archive.unlink()
        engine.payload = lambda: self.fail('OFF may not prepare payload')
        engine.fetch = lambda _: self.fail('OFF may not download payload')
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse(list(engine.cache.glob('*.zip')))

    def test_foreign_setting_edit_retained_other_owned_setting_restored(self):
        engine = self.engine()
        engine.run('install', self.game)
        self.ini.write_bytes(self.ini.read_bytes().replace(b'FGInput=nvngxfg', b'FGInput=fsr31'))
        engine.run('install', self.game)
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'FGInput = auto', b'FGInput=fsr31'))

    def test_modified_provider_and_user_additions_survive_off(self):
        engine = self.engine()
        engine.run('install', self.game)
        dest = self.game / 'custom/Apex Neural Rendering FG'
        provider = dest / 'dlssg/nvngx_dlssg.dll'
        provider.write_bytes(b'foreign replacement')
        (dest / 'user.log').write_bytes(b'game log')
        engine.run('uninstall', self.game)
        self.assertEqual(provider.read_bytes(), b'foreign replacement')
        self.assertEqual((dest / 'user.log').read_bytes(), b'game log')
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign'):
            engine.run('install', self.game)

    def test_interrupted_off_after_config_restoration_retries_under_umask_077(self):
        engine = self.engine()
        engine.run('install', self.game)
        class Interrupted(type(engine)):
            def applied(self, index):
                if index == 0:
                    raise RuntimeError('controlled OFF interruption')
        old_mask = os.umask(0o077)
        try:
            with self.assertRaisesRegex(RuntimeError, 'OFF interruption'):
                Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('uninstall', self.game)
            self.assertEqual(self.ini.read_bytes(), self.original)
            self.assertEqual(self.ini.stat().st_mode & 0o777, 0o640)
            engine.run('uninstall', self.game)
        finally:
            os.umask(old_mask)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse((self.game / 'custom').exists())

    def test_pending_off_refuses_payload_chmod_and_keeps_transaction(self):
        engine = self.engine()
        engine.run('install', self.game)
        class Interrupted(type(engine)):
            def applied(self, index):
                if index == 0:
                    raise RuntimeError('controlled OFF interruption')
        with self.assertRaisesRegex(RuntimeError, 'OFF interruption'):
            Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('uninstall', self.game)
        payload = self.game / 'custom/Apex Neural Rendering FG/dlssg/nr_fg.ini'
        payload.chmod(0o600)
        pending = next(engine.cache.glob('*.pending.json'))
        pending_bytes = pending.read_bytes()
        snapshot = {p.relative_to(self.game): (p.read_bytes(), p.stat().st_mode)
                    for p in self.game.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign edit'):
            engine.run('uninstall', self.game)
        self.assertEqual({p.relative_to(self.game): (p.read_bytes(), p.stat().st_mode)
                          for p in self.game.rglob('*') if p.is_file()}, snapshot)
        self.assertEqual(pending.read_bytes(), pending_bytes)

    def test_payload_chmod_after_preflight_is_rechecked_before_delete(self):
        engine = self.engine()
        engine.run('install', self.game)
        payload = self.game / 'custom/Apex Neural Rendering FG/dlssg/nr_fg.ini'
        original = payload.read_bytes()
        class ConcurrentChmod(type(engine)):
            def applied(self, index):
                if index == 0:
                    payload.chmod(0o600)
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign edit'):
            ConcurrentChmod(self.home, engine.manifest, fetch=engine.fetch).run('uninstall', self.game)
        self.assertEqual(payload.read_bytes(), original)
        self.assertEqual(payload.stat().st_mode & 0o777, 0o600)
        self.assertTrue(list(engine.cache.glob('*.pending.json')))

    def test_pending_settings_writes_preserve_current_ini_mode(self):
        engine = self.engine()
        class Interrupted(type(engine)):
            def replay(self, root, state_path, pending_path, plan):
                if not pending_path.is_file():
                    raise AssertionError('pending plan must already be durable')
                raise RuntimeError('controlled pending interruption')
        for action in ('install', 'uninstall'):
            with self.subTest(action=action):
                self.ini.chmod(0o640)
                with self.assertRaisesRegex(RuntimeError, 'pending interruption'):
                    Interrupted(self.home, engine.manifest, fetch=engine.fetch).run(action, self.game)
                self.ini.chmod(0o600)
                engine.run(action, self.game)
                self.assertEqual(self.ini.stat().st_mode & 0o777, 0o600)
                expected = fixtures.runtime().configure(self.original) if action == 'install' else self.original
                self.assertEqual(self.ini.read_bytes(), expected)
                self.assertFalse(list(engine.cache.glob('*.pending.json')))

    def test_foreign_edit_during_interruption_is_not_overwritten_by_recovery(self):
        engine = self.engine()
        class Interrupted(type(engine)):
            def applied(self, index):
                if index == 0:
                    raise RuntimeError('interrupt')
        with self.assertRaises(RuntimeError):
            Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('install', self.game)
        self.ini.write_bytes(b'user changed after interruption')
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign edit'):
            engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), b'user changed after interruption')
        self.assertTrue(list(engine.cache.glob('*.pending.json')))

    def test_changed_library_path_on_off_uses_recorded_destination(self):
        engine = self.engine()
        engine.run('install', self.game)
        main = self.game / 'other'
        main.mkdir()
        self.ini.write_bytes(self.ini.read_bytes() + b'[Libraries]\nOptiDllPath=other\n')
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'OptiDllPath changed'):
            engine.run('install', self.game)
        engine.run('uninstall', self.game)
        self.assertFalse((self.game / 'custom').exists())
        self.assertEqual(self.ini.read_bytes(), self.original + b'[Libraries]\nOptiDllPath=other\n')

    def test_edit_after_preflight_is_rechecked_before_each_write(self):
        engine = self.engine()
        ini = self.ini
        changed = self.original.replace(b'X=1', b'X=concurrent-edit')
        class ConcurrentEditor(type(engine)):
            def applied(self, index):
                if index == 0:
                    ini.write_bytes(changed)
        with self.assertRaisesRegex(fixtures.runtime().Refusal, 'foreign edit'):
            ConcurrentEditor(self.home, engine.manifest, fetch=engine.fetch).run('install', self.game)
        self.assertEqual(self.ini.read_bytes(), changed)

    def test_modified_payload_permissions_are_preserved_on_off(self):
        engine = self.engine()
        engine.run('install', self.game)
        file = self.game / 'custom/Apex Neural Rendering FG/dlssg/nr_fg.ini'
        file.chmod(0o600)
        engine.run('uninstall', self.game)
        self.assertTrue(file.exists(), 'a user chmod is a foreign change')
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
