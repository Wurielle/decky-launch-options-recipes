"""Portable file-preparation tests; no ANR DLL or upstream setup is executed."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

RECIPE = Path(__file__).resolve().parents[1]
ARCHIVE = Path(os.environ.get('ANR_TEST_ARCHIVE', Path(os.environ['TMPDIR']) / 'anr-fg-V.B14-addon.zip'))
from functools import cache


@cache
def runtime():
    path = RECIPE / 'scripts/loader.py'
    if not path.exists():
        raise AssertionError('physical addon loader is not implemented')
    spec = importlib.util.spec_from_file_location('anr_loader', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.game = self.base / 'game with spaces ü'
        self.game.mkdir()
        self.ini = self.game / 'OptiScaler.ini'
        self.original = b'; keep\r\n[FrameGen]\r\nFGInput = auto\r\nFGNvngxReplacement=auto\r\n[Other]\r\nX=1\r\n'
        self.ini.write_bytes(self.original)
        self.ini.chmod(0o640)
        self.fetches = []

    def engine(self):
        mod = runtime()
        manifest = json.loads((RECIPE / 'scripts/downloads.json').read_bytes())
        def fetch(desc):
            self.fetches.append(desc['url'])
            return ARCHIVE.read_bytes()
        return mod.Engine(self.home, manifest, fetch=fetch)


class Lifecycle(Fixture):
    def test_cold_enable_places_only_addon_and_native_settings(self):
        self.engine().run('install', self.game)
        dest = self.game / 'custom/Apex Neural Rendering FG'
        with zipfile.ZipFile(ARCHIVE) as archive:
            for name in archive.namelist():
                if name.startswith('Apex Neural Rendering FG/'):
                    self.assertEqual((dest / name.split('/', 1)[1]).read_bytes(), archive.read(name))
        self.assertIn(b'FGInput=nvngxfg\r\n', self.ini.read_bytes())
        self.assertIn(b'FGNvngxReplacement=Apex Neural Rendering FG\r\n', self.ini.read_bytes())
        self.assertEqual(self.ini.stat().st_mode & 0o777, 0o640)
        self.assertEqual(len(self.fetches), 1)
        self.assertFalse((self.game / 'dxgi.dll').exists())

    def test_foreign_addon_directory_is_never_adopted(self):
        dest = self.game / 'custom/Apex Neural Rendering FG'
        dest.mkdir(parents=True)
        foreign = dest / 'foreign.txt'
        foreign.write_text('mine')
        with self.assertRaisesRegex(runtime().Refusal, 'foreign'):
            self.engine().run('install', self.game)
        self.assertEqual(foreign.read_text(), 'mine')
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertEqual(self.fetches, [])

    def test_foreign_edits_and_chmod_survive_reenable_and_off(self):
        self.engine().run('install', self.game)
        changed = self.ini.read_bytes().replace(b'X=1', b'X=edited')
        self.ini.write_bytes(changed)
        self.ini.chmod(0o600)
        owned = self.game / 'custom/Apex Neural Rendering FG/dlssg/nr_fg.ini'
        owned.write_bytes(b'user settings')
        self.engine().run('install', self.game)
        self.assertEqual(owned.read_bytes(), b'user settings')
        self.engine().run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original.replace(b'X=1', b'X=edited'))
        self.assertEqual(self.ini.stat().st_mode & 0o777, 0o600)
        self.assertEqual(owned.read_bytes(), b'user settings')

    def test_unsafe_paths_refused_before_acquisition(self):
        # Each row starts with an independent game and cache.
        for kind in ('ini-link', 'parent-link', 'cache-link', 'case-parent', 'case-ini', 'ambiguous'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
                base = Path(temp)
                game = base / 'game'
                home = base / 'home'
                home.mkdir()
                game.mkdir()
                ini = game / 'OptiScaler.ini'
                ini.write_bytes(self.original)
                if kind == 'ini-link':
                    ini.unlink()
                    ini.symlink_to(self.ini)
                elif kind == 'parent-link':
                    ini.unlink()
                    (game / 'nested').symlink_to(self.game, target_is_directory=True)
                elif kind == 'cache-link':
                    (home / '.dlor').symlink_to(self.home, target_is_directory=True)
                elif kind == 'case-parent':
                    (game / 'Render').mkdir()
                    (game / 'render').mkdir()
                    ini.rename(game / 'Render/OptiScaler.ini')
                elif kind == 'case-ini':
                    (game / 'optiscaler.INI').write_bytes(self.original)
                else:
                    (game / 'other').mkdir()
                    (game / 'other/OptiScaler.ini').write_bytes(self.original)
                mod = runtime()
                with self.assertRaises(mod.Refusal):
                    mod.Engine(home, json.loads((RECIPE / 'scripts/downloads.json').read_bytes()),
                               fetch=lambda _: self.fail('unsafe target must not download')).run('install', game)

    def test_native_library_root_selection_and_nested_case_anchor(self):
        nested = self.game / 'Render/Binaries'
        nested.mkdir(parents=True)
        self.ini.rename(nested / 'oPtIsCaLeR.InI')
        self.ini = nested / 'oPtIsCaLeR.InI'
        library = nested / 'PrivateLib'
        library.mkdir()
        self.ini.write_bytes(self.original + b'[Libraries]\r\nOptiDllPath=privatelib\r\n')
        self.engine().run('install', self.game)
        self.assertTrue((library / 'custom/Apex Neural Rendering FG/dlssg/nvngx_dlssg.dll').is_file())
        self.engine().run('uninstall', self.game)
        self.assertFalse((library / 'custom/Apex Neural Rendering FG').exists())
        self.assertEqual(self.ini.read_bytes(), self.original + b'[Libraries]\r\nOptiDllPath=privatelib\r\n')

    def test_interrupted_writes_recover_on_retry_without_payload_on_off(self):
        mod = runtime()
        class Interrupted(mod.Engine):
            def applied(self, index):
                if index == 2:
                    raise RuntimeError('controlled interruption')
        engine = self.engine()
        broken = Interrupted(self.home, engine.manifest, fetch=engine.fetch)
        with self.assertRaisesRegex(RuntimeError, 'controlled interruption'):
            broken.run('install', self.game)
        # OFF must complete/reverse the pending plan using journal bytes alone.
        engine.fetch = lambda _: self.fail('OFF must never fetch payloads')
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse((self.game / 'custom/Apex Neural Rendering FG').exists())
        self.assertEqual(self.ini.stat().st_mode & 0o777, 0o640)

    def test_missing_keys_bom_no_final_newline_restore_with_unrelated_edit(self):
        for original in (b'\xef\xbb\xbf; config\r\n[Other]\r\nX=1', b'[FrameGen]\n; comment\n', b'[FrameGen]\nFGInput=auto'):
            with self.subTest(original=original):
                self.ini.write_bytes(original)
                self.engine().run('install', self.game)
                installed = self.ini.read_bytes()
                self.assertIn(b'FGInput=nvngxfg', installed)
                self.assertIn(b'FGNvngxReplacement=Apex Neural Rendering FG', installed)
                self.engine().run('uninstall', self.game)
                self.assertEqual(self.ini.read_bytes(), original)
        self.ini.write_bytes(b'[Other]\nX=1\n')
        self.engine().run('install', self.game)
        self.ini.write_bytes(self.ini.read_bytes().replace(b'X=1', b'X=2'))
        self.engine().run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), b'[Other]\nX=2\n')

    def test_whitespace_framegen_missing_key_repeated_on_and_edited_off(self):
        original = b'[ FrameGen ]\nFGInput=auto\n[Other]\nX=1\n'
        self.ini.write_bytes(original)
        engine = self.engine()
        engine.run('install', self.game)
        installed = self.ini.read_bytes()
        self.assertEqual(installed.count(b'[FrameGen]'), 0, 'reuse the existing spaced section')
        self.assertIn(b'FGNvngxReplacement=Apex Neural Rendering FG\n[Other]', installed)
        engine.run('install', self.game)
        self.ini.write_bytes(installed.replace(b'X=1', b'X=2'))
        engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), original.replace(b'X=1', b'X=2'))
        self.assertFalse((self.game / 'custom').exists())

    def test_artifact_cache_symlink_refused(self):
        engine = self.engine()
        expected = engine.manifest['downloads']['addon']['sha256']
        archive = engine.cache / (expected + '.zip')
        victim = self.base / 'victim'
        victim.write_bytes(b'untouched')
        archive.symlink_to(victim)
        with self.assertRaises(runtime().Refusal):
            engine.run('install', self.game)
        self.assertEqual(victim.read_bytes(), b'untouched')
        self.assertEqual(self.fetches, [])

    def test_corrupt_cache_repaired_but_corrupt_download_never_touches_game(self):
        engine = self.engine()
        archive = engine.cache / (engine.manifest['downloads']['addon']['sha256'] + '.zip')
        archive.write_bytes(b'corrupt')
        engine.fetch = lambda _: b'corrupt download'
        with self.assertRaisesRegex(runtime().Refusal, 'checksum'):
            engine.run('install', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)
        self.assertFalse((self.game / 'custom').exists())
        self.engine().run('install', self.game)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), engine.manifest['downloads']['addon']['sha256'])

    def test_ambiguous_configuration_refused_before_download(self):
        for extra in (b'[FrameGen]\nFGInput=auto\n', b'[FrameGen]\n', b'[Libraries]\nOptiDllPath=auto\nOptiDllPath=other\n'):
            with self.subTest(extra=extra):
                self.ini.write_bytes(self.original + extra)
                with self.assertRaisesRegex(runtime().Refusal, 'duplicate'):
                    self.engine().run('install', self.game)
                self.assertEqual(self.fetches, [])

    def test_recovery_rejects_non_allowlisted_ini_change(self):
        mod = runtime()
        class Interrupted(mod.Engine):
            def applied(self, index):
                if index == 0:
                    raise RuntimeError('interrupted')
        engine = self.engine()
        with self.assertRaises(RuntimeError):
            Interrupted(self.home, engine.manifest, fetch=engine.fetch).run('install', self.game)
        pending = next(engine.cache.glob('*.pending.json'))
        plan = json.loads(pending.read_bytes())
        operation = next(op for op in plan['operations'] if op['path'] == 'OptiScaler.ini')
        operation['after'] = mod.encoded(self.original.replace(b'X=1', b'X=unauthorized'))
        pending.write_text(json.dumps(plan))
        with self.assertRaisesRegex(mod.Refusal, 'policy'):
            engine.run('uninstall', self.game)
        self.assertEqual(self.ini.read_bytes(), self.original)

    def test_state_cache_must_be_private(self):
        cache = self.home / '.dlor/cache/anr-framegen'
        cache.mkdir(parents=True)
        cache.chmod(0o755)
        with self.assertRaisesRegex(runtime().Refusal, 'private'):
            self.engine()

    def test_archive_unsafe_members_rejected_even_with_matching_archive_pin(self):
        import io
        for name, mode in (('../outside', 0o100644), ('/absolute', 0o100644), ('link', 0o120777), ('privileged', 0o104755)):
            with self.subTest(name=name):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, 'w') as archive:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = mode << 16
                    archive.writestr(info, b'bad')
                data = buffer.getvalue()
                engine = self.engine()
                desc = engine.manifest['downloads']['addon']
                desc.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data), members={})
                engine.fetch = lambda _: data
                with self.assertRaisesRegex(runtime().Refusal, 'archive'):
                    engine.payload()

    def test_repeated_toggle_uses_cache_and_restores_exact_config(self):
        for _ in range(2):
            self.engine().run('install', self.game)
            self.engine().run('install', self.game)
            self.engine().run('uninstall', self.game)
            self.engine().run('uninstall', self.game)
            self.assertEqual(self.ini.read_bytes(), self.original)
            self.assertEqual(self.ini.stat().st_mode & 0o777, 0o640)
            self.assertFalse((self.game / 'custom/Apex Neural Rendering FG').exists())
        self.assertEqual(len(self.fetches), 1)


if __name__ == '__main__':
    unittest.main()
