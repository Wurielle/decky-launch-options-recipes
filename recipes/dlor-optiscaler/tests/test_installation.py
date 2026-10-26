"""Filesystem fixtures only; the fake DLL bytes are not graphics binaries."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
import types
import json
import io
import zipfile

HERE = Path(__file__).resolve().parents[1]


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.game = self.directory / "Game with spaces"
        self.target = self.game / "Arbitrary project" / "Renderer"
        self.target.mkdir(parents=True)
        self.payload = self.directory / "verified-payload"
        self.payload.mkdir()
        self.state = self.directory / "state"
        self.import_path = patch.object(sys, "path", [str(HERE / "scripts"), *sys.path])
        self.import_path.start()
        self.addCleanup(self.import_path.stop)
        self.assertTrue((HERE / "scripts/installer.py").is_file(), "installer implementation is missing")
        spec = importlib.util.spec_from_file_location("opti_installer", HERE / "scripts/installer.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)

    def files(self, contents):
        result = {}
        for relative, data in contents.items():
            path = self.payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            result[relative] = path
        return result

    def test_clean_name_discovery_installs_and_removes_only_renderer_files(self):
        from test_discovery import synthetic_pe
        game = self.directory / 'Cyberpunk 2077'
        target = game / 'unlisted/renderer location'
        target.mkdir(parents=True)
        executable = target / 'Cyberpunk2077.exe'
        executable.write_bytes(synthetic_pe(('KERNEL32.dll',)))
        (game / 'REDprelauncher.exe').write_bytes(synthetic_pe(('d3d11.dll',)))
        (game / 'CrashReportClient.exe').write_bytes(synthetic_pe(('d3d11.dll',)))
        (target / 'foreign-user.dll').write_bytes(b'keep foreign bytes')
        original = {p: p.read_bytes() for p in game.rglob('*') if p.is_file()}
        core = self.directory / 'synthetic core'
        (core / 'OptiScaler').mkdir(parents=True)
        (core / 'OptiScaler.dll').write_bytes(b'synthetic OptiScaler injector')
        (core / 'OptiScaler.ini').write_bytes(b'[Plugins]\nLoadAsiPlugins=false\nPath=auto\n[Libraries]\nOptiDllPath=auto\n')
        (core / 'OptiScaler/libxess.dll').write_bytes(b'synthetic support')
        plugin = self.files({'OptiPatcher.asi': b'synthetic ASI'})['OptiPatcher.asi']
        acquisition = types.SimpleNamespace(resolve_asset=lambda *a, **kw: {'tag': 'synthetic-pinned-core'})
        with patch.dict(sys.modules, artifacts=acquisition), patch.object(self.installer, 'cached_package', return_value=core), patch.object(self.installer, 'optional_components', return_value=({'OptiPatcher.asi': plugin}, {}, {}, [])), patch.dict(os.environ, HOME=str(self.directory)):
            self.assertEqual(self.installer.main(['install', str(game)]), 0)
            self.assertTrue((target / 'dxgi.dll').is_file())
            self.assertTrue((target / 'OptiScaler/plugins/OptiPatcher.asi').is_file())
            self.assertFalse((game / 'dxgi.dll').exists())
            state = json.loads(next((self.directory / '.dlor/state/dlor-optiscaler').glob('*/state.json')).read_bytes())
            self.assertEqual(state['target'], target.relative_to(game).as_posix())
            self.assertEqual(self.installer.main(['uninstall', str(game)]), 0)
        self.assertEqual({p: p.read_bytes() for p in game.rglob('*') if p.is_file()}, original)

    def test_optional_components_use_versioned_official_pins_without_metadata(self):
        import artifacts
        manifest = json.loads((HERE / "scripts/downloads.json").read_bytes())
        with patch.object(artifacts, "DOWNLOADS", manifest["downloads"]), patch.object(artifacts, "_open", side_effect=AssertionError("pinned components need no metadata")), patch.object(artifacts, "download_asset", return_value=self.payload), patch.dict(os.environ, {"DLOR_OPTISCALER_FSR_PROFILE": "rdna2-valve-411"}):
            plugins, libraries, settings, components = self.installer.optional_components(self.directory)
        self.assertEqual(set(plugins), {"OptiPatcher.asi"})
        self.assertEqual(components[0]["name"], "OptiPatcher_v0.42.asi")
        self.assertEqual(components[0]["tag"], "v0.42")
        self.assertEqual(set(libraries), {"amdxc64.dll", "amdxcffx64.dll"})

    def test_upgrade_commit_guard_refuses_after_concurrent_off(self):
        files = self.files({"dxgi.dll": b"synthetic core"})
        with self.assertRaisesRegex(self.installer.InstallerError, "no longer installed"):
            self.installer.apply_install(self.game, self.target, files, self.state, require_installed=True)
        self.assertFalse((self.target / "dxgi.dll").exists())

    def test_cli_latest_flag_forces_only_core_and_off_does_not_install(self):
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        original = b"[Plugins]\nLoadAsiPlugins=false\n"
        (core / "OptiScaler.ini").write_bytes(original)
        plugin = self.files({"OptiPatcher.asi": b"ASI"})["OptiPatcher.asi"]
        calls = []
        def resolve(*args, **kwargs):
            calls.append(kwargs)
            return {"tag": "latest"}
        artifacts = types.SimpleNamespace(resolve_asset=resolve)
        discovery = types.SimpleNamespace(discover_game_directory=lambda *a, **kw: self.target)
        with patch.dict(sys.modules, artifacts=artifacts, game_discovery=discovery), patch.object(self.installer, "cached_package", return_value=core), patch.object(self.installer, "optional_components", return_value=({"OptiPatcher.asi": plugin}, {}, {}, [])), patch.dict(os.environ, {"HOME": str(self.directory)}):
            self.installer.main(["install", str(self.game)])
            self.assertEqual(calls, [{}], 'ordinary install uses manifest pins')
            with patch.dict(os.environ, {"DLOR_OPTISCALER_LATEST": "1"}):
                self.installer.main(["install", str(self.game)])
                self.assertEqual(calls[-1], {"fresh": True})
                self.installer.main(["upgrade", str(self.game)])
                self.assertEqual(calls[-1], {"fresh": True})
                with patch.dict(os.environ, {"DLOR_OPTISCALER_ACTION": "install"}):
                    count = len(calls)
                    self.installer.main(["upgrade", str(self.game)])
                    self.assertEqual(len(calls), count)
                self.installer.main(["uninstall", str(self.game)])
                count = len(calls)
                self.installer.main(["upgrade", str(self.game)])
                self.assertEqual(len(calls), count, 'empty DLOR journal must not reinstall through legacy updater')
        self.assertFalse((self.target / "dxgi.dll").exists())

    def test_case_varied_managed_install_upgrade_and_off_restore_originals(self):
        fixture = os.environ.get("DLOR_TEST_OPTISCALER_DLL")
        if not fixture:
            self.skipTest("Set DLOR_TEST_OPTISCALER_DLL to the verified nightly fixture")
        proxy = self.target / "DXGI.DLL"
        original_proxy = Path(fixture).read_bytes()  # Identification only; never executed.
        proxy.write_bytes(original_proxy)
        ini = self.target / "OPTISCALER.INI"
        original_ini = b"[Libraries]\nOptiDllPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=false\n"
        ini.write_bytes(original_ini)
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        pinned_core = original_proxy + b"\nfixture pinned core\n"
        fresh_core = original_proxy + b"\nfixture fresh core\n"
        (core / "OptiScaler.dll").write_bytes(pinned_core)
        (core / "OptiScaler.ini").write_bytes(original_ini)
        plugin = self.files({"OptiPatcher.asi": b"synthetic ASI"})["OptiPatcher.asi"]
        calls = []
        def resolve(*args, **kwargs):
            calls.append(kwargs)
            return {"tag": "latest" if kwargs else "pinned"}
        acquisition = types.SimpleNamespace(resolve_asset=resolve)
        discovery = types.SimpleNamespace(discover_game_directory=lambda *a, **kw: self.target)
        with patch.dict(sys.modules, artifacts=acquisition, game_discovery=discovery), patch.object(self.installer, "cached_package", return_value=core), patch.object(self.installer, "optional_components", return_value=({"OptiPatcher.asi": plugin}, {}, {}, [])), patch.dict(os.environ, {"HOME": str(self.directory)}):
            for key in ("DLOR_OPTISCALER_ACTION", "DLOR_OPTISCALER_LATEST"):
                os.environ.pop(key, None)
            self.assertEqual(self.installer.main(["install", str(self.game)]), 0)
            journal = next((self.directory / ".dlor/state/dlor-optiscaler").glob("*/state.json"))
            key = proxy.relative_to(self.game).as_posix()
            self.assertIn(key, json.loads(journal.read_bytes())["files"])
            self.assertEqual(proxy.read_bytes(), pinned_core)
            (core / "OptiScaler.dll").write_bytes(fresh_core)
            # Real preliminary ownership check, planning, and final locked guard.
            self.assertEqual(self.installer.main(["upgrade", str(self.game)]), 0)
            self.assertEqual(calls, [{}, {"fresh": True}])
            self.assertEqual(proxy.read_bytes(), fresh_core)
            record = json.loads(journal.read_bytes())["files"][key]
            self.assertEqual(record["installed"], self.installer.digest(proxy))
            self.assertFalse((self.target / "dxgi.dll").exists())
            self.assertFalse((self.target / "OptiScaler.ini").exists())
            self.assertEqual(self.installer.main(["uninstall", str(self.game)]), 0)
        self.assertEqual(proxy.read_bytes(), original_proxy)
        self.assertEqual(ini.read_bytes(), original_ini)
        self.assertEqual(json.loads(journal.read_bytes())["files"], {})

    def test_legacy_upgrade_refuses_if_main_install_finishes_during_metadata(self):
        import artifacts
        fixture = os.environ.get("DLOR_TEST_OPTISCALER_DLL")
        if not fixture:
            self.skipTest("Set DLOR_TEST_OPTISCALER_DLL to the verified nightly fixture")
        (self.target / "dxgi.dll").write_bytes(Path(fixture).read_bytes())
        original_ini = b"[Libraries]\nOptiDllPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=false\n"
        (self.target / "OptiScaler.ini").write_bytes(original_ini)
        fgmod = self.directory / "fgmod"
        fgmod.mkdir()
        (fgmod / "libxess.dll").write_bytes(b"legacy fgmod overlay")
        core = self.directory / "pinned-core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"PINNED MANAGED CORE")
        (core / "OptiScaler.ini").write_bytes(original_ini)
        (core / "OptiScaler/libxess.dll").write_bytes(b"PINNED MANAGED SUPPORT")
        plugin = self.files({"OptiPatcher.asi": b"synthetic ASI"})["OptiPatcher.asi"]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("OptiScaler.dll", b"legacy fresh core")
            archive.writestr("OptiScaler/libxess.dll", b"legacy stock support")
        payload = output.getvalue()
        asset_url = "https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-race/OptiScaler_test.7z"
        snapshots = {}
        requests = []
        def snapshot_game():
            return {path.relative_to(self.game).as_posix(): path.read_bytes()
                    for path in self.game.rglob("*") if path.is_file()}
        def transport(url):
            requests.append(url)
            if url == asset_url:
                data = payload
            else:
                # Deterministic interleaving: actual main ON completes after
                # legacy dispatch, before the pending metadata response returns.
                with patch.object(artifacts, "resolve_asset", return_value={"tag": "pinned"}), patch.object(self.installer, "cached_package", return_value=core), patch.object(self.installer, "optional_components", return_value=({"OptiPatcher.asi": plugin}, {}, {}, [])):
                    self.assertEqual(self.installer.main(["install", str(self.game)]), 0)
                journal = next((self.directory / ".dlor/state/dlor-optiscaler").glob("*/state.json"))
                snapshots.update(game=snapshot_game(), journal=journal, state=journal.read_bytes())
                self.assertEqual((self.target / "OptiScaler/libxess.dll").read_bytes(), b"PINNED MANAGED SUPPORT")
                data = json.dumps([{"draft": False, "tag_name": "nightly-race", "assets": [{
                    "name": "OptiScaler_test.7z", "size": len(payload),
                    "browser_download_url": asset_url,
                    "digest": "sha256:" + self.installer.hashlib.sha256(payload).hexdigest()}]}]).encode()
            response = io.BytesIO(data)
            response.headers = {"Content-Length": str(len(data))}
            return response
        spec = importlib.util.spec_from_file_location("opti_nightly", HERE / "scripts/nightly.py")
        nightly = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, installer=self.installer):
            spec.loader.exec_module(nightly)
        discovery = types.SimpleNamespace(discover_game_directory=lambda *a, **kw: self.target)
        with patch.dict(sys.modules, nightly=nightly, game_discovery=discovery), patch.dict(os.environ, {"HOME": str(self.directory), "OPTISCALER_CACHE_DIR": str(self.directory / "legacy-cache")}), patch.object(artifacts, "_open", transport):
            for key in ("DLOR_OPTISCALER_ACTION", "DLOR_OPTISCALER_LATEST"):
                os.environ.pop(key, None)
            refusal = None
            try:
                self.installer.main(["upgrade", str(self.game)])
            except self.installer.InstallerError as error:
                refusal = str(error)
            self.assertEqual(len(requests), 2, "real metadata, SHA verification and extraction must complete")
            self.assertEqual(snapshot_game(), snapshots["game"], "legacy overlay changed a newly DLOR-managed game")
            self.assertEqual(snapshots["journal"].read_bytes(), snapshots["state"])
            self.assertIsNotNone(refusal, "managed transition must refuse rather than overlay")
            self.assertIn("DLOR", refusal)

    def test_upgrade_guards_preserve_ambiguous_and_symlinked_proxies(self):
        state_home = self.directory / ".dlor/state/dlor-optiscaler"
        files = self.files({"DXGI.DLL": b"owned fixture core"})
        self.installer.apply_install(self.game, self.target, files, state_home)
        journal = next(state_home.glob("*/state.json"))
        before = journal.read_bytes()
        proxy = self.target / "DXGI.DLL"
        for kind, message in (("ambiguous", "Ambiguous Windows"), ("symlink", "Symlink inside")):
            with self.subTest(kind=kind), patch.dict(os.environ, {"HOME": str(self.directory)}):
                os.environ.pop("DLOR_OPTISCALER_ACTION", None)
                if kind == "ambiguous":
                    extra = self.target / "dxgi.dll"
                    extra.write_bytes(b"foreign collision")
                else:
                    extra = self.directory / "outside-proxy"
                    proxy.rename(extra)
                    proxy.symlink_to(extra)
                try:
                    with self.assertRaisesRegex(self.installer.InstallerError, message):
                        self.installer.main(["upgrade", str(self.game)])
                    with self.assertRaisesRegex(self.installer.InstallerError, message):
                        self.installer.apply_install(self.game, self.target, files, state_home, require_installed=True)
                    self.assertEqual(journal.read_bytes(), before)
                    self.assertEqual(extra.read_bytes(), b"foreign collision" if kind == "ambiguous" else b"owned fixture core")
                finally:
                    if kind == "symlink":
                        proxy.unlink()
                        extra.rename(proxy)
                    else:
                        extra.unlink()

    def test_cli_applies_explicit_environment_and_restores_on_off(self):
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        original = b"\xef\xbb\xbf[FG]\r\nEnabled=auto\r\n[Plugins]\r\nLoadAsiPlugins=false\r\nPath=auto\r\n"
        (core / "OptiScaler.ini").write_bytes(original)
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        ini.chmod(0o640)
        plugin = self.files({"OptiPatcher.asi": b"synthetic ASI"})["OptiPatcher.asi"]
        artifacts = types.SimpleNamespace(resolve_asset=lambda *a: {"tag": "nightly"})
        discovery = types.SimpleNamespace(discover_game_directory=lambda *a, **kw: self.target)
        with patch.dict(sys.modules, artifacts=artifacts, game_discovery=discovery), patch.object(self.installer, "cached_package", return_value=core), patch.object(self.installer, "optional_components", return_value=({"OptiPatcher.asi": plugin}, {}, {}, [])), patch.dict(os.environ, {"HOME": str(self.directory), "OptiScaler_FG_Enabled": "true"}), patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
            self.installer.main(["install", str(self.game)])
            self.assertIn(b"Enabled=true\r\n", ini.read_bytes())
            self.installer.main(["uninstall", str(self.game)])
        self.assertEqual(ini.read_bytes(), original)
        self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)

    def test_active_environment_reapplies_after_overlay_edit_and_restores_latest_value(self):
        ini = self.target / "OptiScaler.ini"
        original = b"[User]\nFont=original\n[Plugins]\nLoadAsiPlugins=false\n"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        override = {("User", "Font"): "requested"}
        with patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
            for _ in range(2):
                self.installer.apply_install(self.game, self.target, files, self.state, configuration=override, explicit_overrides=override, asi_only=True)
                ini.write_bytes(ini.read_bytes().replace(b"Font=requested", b"Font=latest-overlay"))
            self.installer.apply_install(self.game, self.target, files, self.state, configuration=override, explicit_overrides=override, asi_only=True)
            self.assertIn(b"Font=requested", ini.read_bytes())
            self.installer.uninstall(self.game, self.state, asi_only=True)
        self.assertEqual(ini.read_bytes(), original.replace(b"Font=original", b"Font=latest-overlay"))

    def test_cli_environment_path_removal_is_planned_before_placement(self):
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        original = b"[Libraries]\nOptiDllPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=false\n"
        (core / "OptiScaler.ini").write_bytes(original)
        (core / "OptiScaler/libxess.dll").write_bytes(b"synthetic XeSS")
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        plugin = self.files({"OptiPatcher.asi": b"synthetic ASI"})["OptiPatcher.asi"]
        artifacts = types.SimpleNamespace(resolve_asset=lambda *a: {"tag": "nightly"})
        discovery = types.SimpleNamespace(discover_game_directory=lambda *a, **kw: self.target)
        override = {"OptiScaler_Libraries_OptiDllPath": "custom", "OptiScaler_Plugins_Path": str(self.game / "explicit-plugins"), "OptiScaler_Plugins_LoadAsiPlugins": "false"}
        with patch.dict(sys.modules, artifacts=artifacts, game_discovery=discovery), patch.object(self.installer, "cached_package", return_value=core), patch.object(self.installer, "optional_components", return_value=({"OptiPatcher.asi": plugin}, {}, {}, [])), patch.dict(os.environ, {"HOME": str(self.directory), **override}), patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
            self.installer.main(["install", str(self.game)])
            self.assertTrue((self.target / "custom/libxess.dll").is_file())
            self.assertTrue((self.game / "explicit-plugins/OptiPatcher.asi").is_file())
            self.assertNotIn(b"LoadAsiPlugins=true", ini.read_bytes())
            for key in override:
                os.environ.pop(key)
            self.installer.main(["install", str(self.game)])
            self.assertTrue((self.target / "OptiScaler/libxess.dll").is_file())
            self.assertTrue((self.target / "OptiScaler/plugins/OptiPatcher.asi").is_file())
            self.assertFalse((self.target / "custom/libxess.dll").exists())
            self.assertFalse((self.game / "explicit-plugins/OptiPatcher.asi").exists())
            self.assertEqual(ini.read_bytes(), original.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
            self.installer.main(["uninstall", str(self.game)])
        self.assertEqual(ini.read_bytes(), original)

    def test_interrupted_environment_transaction_recovers_exact_permissions(self):
        ini = self.target / "OptiScaler.ini"
        original = b"[User]\nFont=old\n[Plugins]\nLoadAsiPlugins=false\n"
        ini.write_bytes(original)
        ini.chmod(0o640)
        files = self.files({"OptiScaler.ini": original})
        override = {("User", "Font"): "requested"}
        real_save = self.installer.save_state
        def interrupted(path, state):
            if state.get("transaction") and ini.read_bytes() != original:
                raise SystemExit("power loss after INI write")
            return real_save(path, state)
        with patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]), patch.object(self.installer, "save_state", interrupted), patch.object(self.installer, "recover_transaction", side_effect=SystemExit("power loss")):
            with self.assertRaises(SystemExit):
                self.installer.apply_install(self.game, self.target, files, self.state, configuration=override, explicit_overrides=override, asi_only=True)
        self.assertIn(b"Font=requested", ini.read_bytes())
        with patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
            self.installer.uninstall(self.game, self.state, asi_only=True)
        self.assertEqual(ini.read_bytes(), original)
        self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)

    def test_explicit_case_sensitive_literal_values_survive_removal_and_foreign_edits(self):
        ini = self.target / "OptiScaler.ini"
        original = b"\xef\xbb\xbf[User]\r\nPath=old\r\nPATH=other\r\n[Plugins]\r\nLoadAsiPlugins=false\r\n"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        override = {("User", "Path"): r"C:\1\g<1> 50% $HOME ; literal # value"}
        configuration = {("Plugins", "LoadAsiPlugins"): "true", **override}
        with patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
            for _ in range(2):
                self.installer.apply_install(self.game, self.target, files, self.state, configuration=configuration, explicit_overrides=override, asi_only=True)
            self.assertIn(("Path=" + override[("User", "Path")] + "\r\nPATH=other").encode(), ini.read_bytes())
            ini.write_bytes(ini.read_bytes().replace(override[("User", "Path")].encode(), b"overlay-user-value") + b"[Added]\r\nKey=keep\r\n")
            self.installer.apply_install(self.game, self.target, files, self.state, configuration={("Plugins", "LoadAsiPlugins"): "true"}, asi_only=True)
            self.installer.uninstall(self.game, self.state, asi_only=True)
        self.assertEqual(ini.read_bytes(), original.replace(b"Path=old", b"Path=overlay-user-value") + b"[Added]\r\nKey=keep\r\n")

    def test_explicit_permissions_cannot_write_unrequested_or_mismatched_values(self):
        original = b"[User]\nFont=old\n"
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        for configuration in ({}, {("User", "Font"): "different"}):
            with self.subTest(configuration=configuration), patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
                with self.assertRaises(self.installer.InstallerError):
                    self.installer.apply_install(self.game, self.target, files, self.state, configuration=configuration, explicit_overrides={("User", "Font"): "requested"}, asi_only=True)
            self.assertEqual(ini.read_bytes(), original)

    def test_stale_effective_configuration_refuses_before_file_placement(self):
        original = b"[User]\nFont=old\n"
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original, "dxgi.dll": b"synthetic proxy"})
        with patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]):
            with self.assertRaises(self.installer.InstallerError):
                self.installer.apply_install(self.game, self.target, files, self.state, configuration={}, asi_only=True, expected_configuration_data=b"[User]\nFont=stale\n")
        self.assertEqual(ini.read_bytes(), original)
        self.assertFalse((self.target / "dxgi.dll").exists())

    def test_new_environment_override_reacquires_current_not_retired_legacy_original(self):
        original = b"[User]\nFont=old-original\n"
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        self.installer.apply_install(self.game, self.target, files, self.state, configuration={("User", "Font"): "legacy-current"})
        override = {("User", "Font"): "explicit-new"}
        self.installer.apply_install(self.game, self.target, files, self.state, configuration=override, explicit_overrides=override, asi_only=True)
        self.installer.uninstall(self.game, self.state, asi_only=True)
        self.assertEqual(ini.read_bytes(), original.replace(b"old-original", b"legacy-current"))

    def test_pending_environment_policy_cannot_authorize_other_setting_recovery(self):
        ini = self.target / "OptiScaler.ini"
        original = b"[User]\nFont=old\nOther=keep\n"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        override = {("User", "Font"): "requested"}
        real_save = self.installer.save_state
        def interrupted(path, state):
            if state.get("transaction") and ini.read_bytes() != original:
                raise SystemExit("power loss")
            return real_save(path, state)
        with patch.object(self.installer, "save_state", interrupted), patch.object(self.installer, "recover_transaction", side_effect=SystemExit("power loss")):
            with self.assertRaises(SystemExit):
                self.installer.apply_install(self.game, self.target, files, self.state, configuration=override, explicit_overrides=override, asi_only=True)
        journal = next(self.state.glob("*/state.json"))
        state = json.loads(journal.read_text())
        relative = ini.relative_to(self.game).as_posix()
        ini.write_bytes(ini.read_bytes().replace(b"Other=keep", b"Other=forbidden"))
        state["transaction"]["changes"][relative]["next"] = self.installer.digest(ini)
        journal.write_text(json.dumps(state))
        before = ini.read_bytes(), journal.read_bytes()
        with self.assertRaisesRegex(self.installer.InstallerError, "setting permissions"):
            self.installer.uninstall(self.game, self.state, asi_only=True)
        self.assertEqual((ini.read_bytes(), journal.read_bytes()), before)

    def test_every_profile_is_file_only_and_optipatcher_is_mandatory(self):
        calls = []
        def resolve(repository, channel, pattern, cache):
            calls.append((repository, channel, pattern))
            return {"repository": repository, "tag": channel, "sha256": "a" * 64, "name": pattern}
        artifacts = types.SimpleNamespace(resolve_asset=resolve, download_asset=lambda asset, cache: self.payload)
        for profile in ("bundled", "rdna23-int8", "rdna34-official-411", "rdna2-valve-411"):
            with self.subTest(profile=profile), patch.dict(sys.modules, artifacts=artifacts), patch.dict(os.environ, {"DLOR_OPTISCALER_FSR_PROFILE": profile, "DLOR_OPTISCALER_OPTIPATCHER": "0"}):
                plugins, libraries, settings, components = self.installer.optional_components(self.directory)
                self.assertEqual(set(plugins), {"OptiPatcher.asi"})
                self.assertEqual(settings, {}, "Profiles may supply files, never activate FSR settings")
                self.assertEqual(components[0]["repository"], "optiscaler/OptiPatcher")
                self.assertEqual(len(components), 1 + len(libraries))

    def test_cli_off_relinquishes_legacy_non_asi_settings_without_rewriting(self):
        for created in (False, True):
            for foreign in (False, True):
                with self.subTest(created=created, foreign=foreign):
                    target = self.target / f"legacy-{created}-{foreign}"
                    target.mkdir()
                    ini = target / "OptiScaler.ini"
                    original = b"\xef\xbb\xbf[Plugins]\r\nLoadAsiPlugins=false\r\nPath=original-plugins\r\nLoadCustomAmdxc64OnRdna2=false\r\n[FSR]\r\nFsr4GpuSupport=auto\r\n[Libraries]\r\nXeSSPath=original-library\r\n"
                    if not created:
                        ini.write_bytes(original)
                    files = self.files({"OptiScaler.ini": original, "OptiPatcher.asi": b"synthetic plugin"})
                    state = self.directory / ".dlor/state/dlor-optiscaler"
                    legacy = {("Plugins", "LoadAsiPlugins"): "true", ("Plugins", "Path"): "legacy-plugins", ("Plugins", "LoadCustomAmdxc64OnRdna2"): "true", ("FSR", "Fsr4GpuSupport"): "2", ("Libraries", "XeSSPath"): "legacy-library"}
                    self.installer.apply_install(self.game, target, files, state, configuration=legacy)
                    if foreign:
                        ini.write_bytes(ini.read_bytes() + b"[User]\r\nFont=keep\r\n")
                    ini.chmod(0o604)
                    current = ini.read_bytes()
                    with patch.dict(os.environ, HOME=str(self.directory)):
                        self.installer.main(["uninstall", str(self.game)])
                    self.assertTrue(ini.is_file(), "Legacy non-ASI bytes cannot become whole-file removal ownership")
                    self.assertEqual(ini.read_bytes(), current.replace(b"LoadAsiPlugins=true", b"LoadAsiPlugins=false"))
                    self.assertEqual(ini.stat().st_mode & 0o7777, 0o604)
                    self.assertFalse((target / "OptiPatcher.asi").exists())

    def test_cli_refuses_unfinished_legacy_ini_transaction_before_recovery_writes(self):
        original = b"[FSR]\nFsr4GpuSupport=auto\n[Plugins]\nLoadAsiPlugins=false\n"
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        state_home = self.directory / ".dlor/state/dlor-optiscaler"
        files = self.files({"OptiScaler.ini": original})
        self.installer.apply_install(self.game, self.target, files, state_home)
        with self.installer.game_state(self.game, state_home) as (_, directory, journal, state):
            before = json.loads(json.dumps(state))
            old_hash = self.installer.digest(ini)
            backup = directory / "backups" / old_hash
            backup.parent.mkdir(exist_ok=True)
            backup.write_bytes(original)
            ini.write_bytes(original.replace(b"Fsr4GpuSupport=auto", b"Fsr4GpuSupport=2"))
            # A first legacy install can crash before settings ownership was
            # saved: no settings map may be available to detect old rewrites.
            state["transaction"] = {"before": before, "changes": {ini.relative_to(self.game).as_posix(): {"previous": old_hash, "next": self.installer.digest(ini), "mode": 0o600}}}
            self.installer.save_state(journal, state)
        current, journal_bytes = ini.read_bytes(), journal.read_bytes()
        with patch.dict(os.environ, HOME=str(self.directory)):
            with self.assertRaisesRegex(self.installer.InstallerError, "Interrupted.*INI transaction"):
                self.installer.main(["uninstall", str(self.game)])
        self.assertEqual(ini.read_bytes(), current)
        self.assertEqual(journal.read_bytes(), journal_bytes)
        self.assertEqual(backup.read_bytes(), original)

    def test_cli_off_preserves_later_ini_mode_without_foreign_content_edits(self):
        ini = self.target / "OptiScaler.ini"
        original = b"[Plugins]\nLoadAsiPlugins=false\n[User]\nFont=keep\n"
        ini.write_bytes(original)
        ini.chmod(0o640)
        state = self.directory / ".dlor/state/dlor-optiscaler"
        self.installer.apply_install(self.game, self.target, self.files({"OptiScaler.ini": original}), state, configuration={("Plugins", "LoadAsiPlugins"): "true"})
        ini.chmod(0o604)
        with patch.dict(os.environ, HOME=str(self.directory)):
            self.installer.main(["uninstall", str(self.game)])
        self.assertEqual(ini.read_bytes(), original)
        self.assertEqual(ini.stat().st_mode & 0o7777, 0o604)

    def test_verified_nightly_retains_nukem_and_integrated_fakenvapi_defaults(self):
        fixture = os.environ.get("DLOR_TEST_OPTISCALER_DLL")
        if not fixture:
            self.skipTest("Set DLOR_TEST_OPTISCALER_DLL to the verified nightly fixture")
        core = Path(fixture).parent
        plugin = self.files({"OptiPatcher.asi": b"synthetic ASI"})["OptiPatcher.asi"]
        plan = self.installer.build_plan(self.game, self.target, core, plugins={"OptiPatcher.asi": plugin})
        prefix = self.target.relative_to(self.game).as_posix()
        self.assertIn(prefix + "/OptiScaler/dlssg_to_fsr3_amd_is_better.dll", plan["files"])
        self.assertFalse(any(Path(name).name.casefold() in ("fakenvapi.dll", "nvapi64.dll") for name in plan["files"]))
        data = (core / "OptiScaler.ini").read_bytes()
        self.assertEqual(self.installer.ini_value(data, "fakenvapi", "UseFakenvapi"), "auto")
        self.assertIn(b"; true or false - Default (auto) is true\r\nUseFakenvapi=auto", data)
        self.assertEqual(plan["settings"], {("Plugins", "LoadAsiPlugins"): "true"})

    def test_absolute_custom_paths_are_preserved_byte_for_byte(self):
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler.ini").write_bytes(b"[Libraries]\nOptiDllPath=auto\n")
        (core / "OptiScaler/libxess.dll").write_bytes(b"synthetic library")
        plugin = self.files({"fixture.asi": b"synthetic ASI"})["fixture.asi"]
        wine = lambda path: ("Z:" + str(path).replace("/", "\\")).encode()
        original = b"\xef\xbb\xbf[Libraries]\r\nOptiDllPath=" + wine(self.game / "support") + b"\r\nXeSSPath=" + wine(self.game / "custom/libxess.dll") + b"\r\n[Plugins]\r\nPath=" + wine(self.game / "plugins") + b"\r\nLoadAsiPlugins=false\r\n"
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        plan = self.installer.build_plan(self.game, self.target, core, plugins={"fixture.asi": plugin})
        self.assertIn("custom/libxess.dll", plan["files"])
        self.assertIn("plugins/fixture.asi", plan["files"])
        self.installer.apply_install(self.game, self.target, plan["files"], self.state, relative_to_root=True, configuration=plan["settings"], asi_only=True)
        self.assertEqual(ini.read_bytes(), original.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
        self.installer.uninstall(self.game, self.state, asi_only=True)
        self.assertEqual(ini.read_bytes(), original)

    def test_quoted_custom_paths_refuse_instead_of_normalizing_ini(self):
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler/libxess.dll").write_bytes(b"synthetic library")
        plugin = self.files({"fixture.asi": b"synthetic ASI"})["fixture.asi"]
        for section, key in (("Libraries", "OptiDllPath"), ("Libraries", "XeSSPath"), ("Plugins", "Path")):
            with self.subTest(section=section, key=key):
                data = f'[{section}]\n{key}="Z:{self.game}/custom" ; annotation\n'.encode()
                (core / "OptiScaler.ini").write_bytes(data)
                with self.assertRaisesRegex(self.installer.InstallerError, "[Qq]uoted"):
                    self.installer.build_plan(self.game, self.target, core, plugins={"fixture.asi": plugin})
        self.assertEqual(list(self.target.iterdir()), [])

    def test_flat_legacy_core_layout_is_rejected(self):
        core = self.directory / "legacy-core"
        core.mkdir()
        (core / "OptiScaler.dll").write_bytes(b"synthetic legacy injector")
        (core / "OptiScaler.ini").write_bytes(b"[Libraries]\nOptiDllPath=auto\n")
        (core / "libxess.dll").write_bytes(b"synthetic flat support")
        with self.assertRaises(self.installer.InstallerError):
            self.installer.build_plan(self.game, self.target, core)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_uninstall_restores_original_permissions_under_restrictive_umask(self):
        original = self.target / "support.dll"
        original.write_bytes(b"original user content")
        original.chmod(0o640)
        files = self.files({"support.dll": b"synthetic replacement"})
        previous_umask = os.umask(0o077)
        try:
            self.installer.apply_install(self.game, self.target, files, self.state)
            self.installer.uninstall(self.game, self.state)
        finally:
            os.umask(previous_umask)
        self.assertEqual(original.read_bytes(), b"original user content")
        self.assertEqual(original.stat().st_mode & 0o7777, 0o640)

    def test_ini_setting_changes_preserve_current_permissions_under_restrictive_umask(self):
        ini = self.target / "OptiScaler.ini"
        original = b"[Plugins]\nLoadAsiPlugins=false\n[User]\nValue=keep\n"
        ini.write_bytes(original)
        ini.chmod(0o640)
        files = self.files({"OptiScaler.ini": original})
        settings = {("Plugins", "LoadAsiPlugins"): "true"}
        previous_umask = os.umask(0o077)
        try:
            self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
            with self.subTest(stage="enable"):
                self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)
            ini.write_bytes(ini.read_bytes() + b"Added=keep\n")
            self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
            self.installer.uninstall(self.game, self.state)
            with self.subTest(stage="partial-restore"):
                self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)
            self.assertEqual(ini.read_bytes(), original + b"Added=keep\n")
            self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
            ini.chmod(0o604)  # A later permission change belongs to the user.
            ini.write_bytes(ini.read_bytes() + b"Later=keep\n")
            self.installer.apply_install(self.game, self.target, files, self.state, configuration={})
            with self.subTest(stage="disable-after-chmod"):
                self.assertEqual(ini.stat().st_mode & 0o7777, 0o604)
            self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
            with self.subTest(stage="reenable"):
                self.assertEqual(ini.stat().st_mode & 0o7777, 0o604)
            ini.chmod(0o660)
            self.installer.uninstall(self.game, self.state)
            with self.subTest(stage="partial-restore-after-chmod"):
                self.assertEqual(ini.stat().st_mode & 0o7777, 0o660)
        finally:
            os.umask(previous_umask)
        self.assertEqual(ini.read_bytes(), original + b"Added=keep\nLater=keep\n")

    def test_owned_file_removal_is_directory_synced_before_forgetting_ownership(self):
        files = self.files({"dxgi.dll": b"synthetic proxy"})
        self.installer.apply_install(self.game, self.target, files, self.state)
        events = []
        real_remove = self.installer.remove_owned
        real_save = self.installer.save_state
        def remove(path):
            real_remove(path)
            events.append("removed-and-synced")
        def save(path, state):
            if not state["files"]:
                events.append("ownership-cleared")
            return real_save(path, state)
        self.installer.remove_owned = remove
        self.installer.save_state = save
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(events, ["removed-and-synced", "ownership-cleared"])

    def test_third_party_profile_and_optipatcher_use_resolved_nightly_directories(self):
        archive = self.directory / "fixture-core.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("OptiScaler.dll", b"synthetic core")
            output.writestr("OptiScaler.ini", "[Libraries]\nOptiDllPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=false\n[FSR]\nFsr4GpuSupport=auto\n")
            output.writestr("OptiScaler/amd_fidelityfx_upscaler_dx12.dll", b"bundled SDK")
        blobs = {"OptiPatcher.asi": b"synthetic plugin", "amdxcffx64.dll": b"synthetic driver", "amdxc64.dll": b"synthetic second driver"}
        paths = {}
        for name, data in blobs.items():
            paths[name] = self.directory / name
            paths[name].write_bytes(data)
        spec = importlib.util.spec_from_file_location("artifacts", HERE / "scripts/artifacts.py")
        assert spec and spec.loader
        artifacts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(artifacts)
        calls = []
        def resolve(repository, channel, pattern, cache, **kwargs):
            import re
            calls.append((repository, channel))
            matches = [path for name, path in paths.items() if re.fullmatch(pattern, name)]
            path = archive if repository.endswith("OptiScaler-nightly") else matches[0]
            return {"repository": repository, "tag": channel.removeprefix("tag:"), "name": path.name, "url": "https://github.com/fixture/release", "sha256": self.installer.digest(path), "size": path.stat().st_size}
        discovery = types.SimpleNamespace(discover_game_directory=lambda *args, **kwargs: self.target)
        (self.directory / ".dlor/cache/dlor-optiscaler/artifacts").mkdir(parents=True)
        environment = {"HOME": str(self.directory), "DLOR_OPTISCALER_CHANNEL": "nightly", "DLOR_OPTISCALER_OPTIPATCHER": "1", "DLOR_OPTISCALER_FSR_PROFILE": "rdna2-valve-411"}
        with patch.dict(sys.modules, {"artifacts": artifacts, "game_discovery": discovery}), patch.object(artifacts, "resolve_asset", resolve), patch.object(artifacts, "download_asset", lambda asset, cache: archive if asset["name"] == archive.name else paths[asset["name"]]), patch.dict(os.environ, environment):
            self.installer.main(["install", str(self.game)])
            for name in ["amdxcffx64.dll", "amdxc64.dll"]:
                self.assertEqual((self.target / "OptiScaler" / name).read_bytes(), blobs[name])
            self.assertEqual((self.target / "OptiScaler/plugins/OptiPatcher.asi").read_bytes(), blobs["OptiPatcher.asi"])
            data = (self.target / "OptiScaler.ini").read_bytes()
            self.assertEqual(self.installer.ini_value(data, "FSR", "Fsr4GpuSupport"), "auto")
            self.assertEqual(self.installer.ini_value(data, "Plugins", "LoadCustomAmdxc64OnRdna2"), "auto")
            self.assertEqual(data, b"[Libraries]\nOptiDllPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=true\n[FSR]\nFsr4GpuSupport=auto\n")
            self.assertIn(("xXJSONDeruloXx/OptiScaler-Bleeding-Edge", "tag:fsr-4-1-1-rdna2"), calls)
            os.environ.pop("DLOR_OPTISCALER_FSR_PROFILE")
            self.installer.main(["upgrade", str(self.game)])
            self.assertTrue((self.target / "OptiScaler/amdxc64.dll").is_file(), "Standalone upgrade must retain the installed profile")
            os.environ["DLOR_OPTISCALER_OPTIPATCHER"] = "0"
            os.environ["DLOR_OPTISCALER_FSR_PROFILE"] = "bundled"
            self.installer.main(["install", str(self.game)])
            self.assertFalse((self.target / "OptiScaler/amdxc64.dll").exists())
            self.assertEqual((self.target / "OptiScaler/plugins/OptiPatcher.asi").read_bytes(), blobs["OptiPatcher.asi"])
            data = (self.target / "OptiScaler.ini").read_bytes()
            self.assertEqual(self.installer.ini_value(data, "FSR", "Fsr4GpuSupport"), "auto")
            self.assertEqual(self.installer.ini_value(data, "Plugins", "LoadAsiPlugins"), "true")
            self.installer.uninstall(self.game, self.directory / ".dlor/state/dlor-optiscaler")
            self.assertFalse((self.target / "OptiScaler/amdxc64.dll").exists())

    def test_cli_selects_official_nightly_and_uninstall_never_resolves_assets(self):
        archive = self.directory / "fixture.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("OptiScaler.dll", b"synthetic core")
            output.writestr("OptiScaler.ini", "[Libraries]\nOptiDllPath=auto\n")
            output.writestr("OptiScaler/libxess.dll", b"synthetic supporting library")
        spec = importlib.util.spec_from_file_location("artifacts", HERE / "scripts/artifacts.py")
        assert spec and spec.loader
        artifacts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(artifacts)
        plugin = self.directory / "OptiPatcher.asi"
        plugin.write_bytes(b"synthetic official plugin")
        original = b"\xef\xbb\xbf[Libraries]\r\nOptiDllPath=auto\r\n[Plugins]\r\nLoadAsiPlugins=false\r\n[FG]\r\nEnabled=user-policy\r\n[FSR]\r\nFsr4GpuSupport=user-policy\r\n[User]\r\nFont=keep\r\n"
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(original)
        ini.chmod(0o640)
        calls = []
        def resolve(repository, channel, pattern, cache, **kwargs):
            import re
            calls.append((repository, channel))
            path = plugin if repository == "optiscaler/OptiPatcher" else archive
            if path == plugin:
                self.assertIsNotNone(re.fullmatch(pattern, "OptiPatcher.asi"))
                self.assertIsNone(re.fullmatch(pattern, "OtherOptiPatcher.asi"))
            return {"repository": repository, "tag": "nightly-fixture", "name": path.name, "url": "https://github.com/fixture/release", "sha256": self.installer.digest(path), "size": path.stat().st_size}
        discovery = types.SimpleNamespace(discover_game_directory=lambda *args, **kwargs: self.target)
        result = self.directory / "result.json"
        (self.directory / ".dlor/cache/dlor-optiscaler/artifacts").mkdir(parents=True)
        home_alias = self.directory / "home-alias"
        home_alias.symlink_to(self.directory, target_is_directory=True)
        with patch.dict(sys.modules, {"artifacts": artifacts, "game_discovery": discovery}), patch.object(artifacts, "resolve_asset", resolve), patch.object(artifacts, "download_asset", lambda asset, cache: plugin if asset["name"] == plugin.name else archive), patch.dict(os.environ, {"HOME": str(home_alias), "DLOR_OPTISCALER_OPTIPATCHER": "0"}):
            os.environ.pop("DLOR_OPTISCALER_CHANNEL", None)
            self.installer.main(["install", str(self.game), "--result", str(result)])
            self.assertEqual(json.loads(result.read_text())["proxy"], "dxgi")
            self.assertEqual((self.target / "OptiScaler/libxess.dll").read_bytes(), b"synthetic supporting library")
            self.assertEqual(calls, [("optiscaler/OptiScaler-nightly", "nightly"), ("optiscaler/OptiPatcher", "stable")])
            self.assertEqual((self.target / "OptiScaler/plugins/OptiPatcher.asi").read_bytes(), plugin.read_bytes())
            self.assertEqual(ini.read_bytes(), original.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
            self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)
            journal = next((self.directory / ".dlor/state/dlor-optiscaler").glob("*/state.json"))
            provenance = json.loads(journal.read_text())["components"]
            self.assertEqual(provenance[0]["sha256"], self.installer.digest(archive))
            self.assertEqual(provenance[0]["repository"], "optiscaler/OptiScaler-nightly")
            legacy_state = json.loads(journal.read_text())
            record = legacy_state["files"][ini.relative_to(self.game).as_posix()]
            for name in ("FSR.Fsr4GpuSupport", "FG.Enabled", "User.Font"):
                record["settings"][name] = {"before": "old-original", "before_raw": "old-original", "after": "keep" if name == "User.Font" else "user-policy"}
            journal.write_text(json.dumps(legacy_state))
            calls.clear()
            os.environ["DLOR_OPTISCALER_CHANNEL"] = "stable"
            os.environ["DLOR_OPTISCALER_PROXY"] = "winmm"
            self.installer.main(["install", str(self.game), "--result", str(result)])
            self.assertEqual(calls, [("optiscaler/OptiScaler-nightly", "nightly"), ("optiscaler/OptiPatcher", "stable")])
            self.assertEqual((self.target / "OptiScaler/plugins/OptiPatcher.asi").read_bytes(), plugin.read_bytes())
            self.assertEqual(ini.read_bytes(), original.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
            self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)
            self.assertEqual(json.loads(result.read_text())["proxy"], "dxgi")
            calls.clear()
            self.installer.main(["uninstall", str(self.game)])
            self.assertEqual(calls, [])
            self.assertFalse((self.target / "dxgi.dll").exists())
            (self.target / "dxgi.dll").write_bytes(b"a different user mod installed later")
            with self.assertRaises(self.installer.InstallerError):
                self.installer.main(["install", str(self.game), "--result", str(result)])
            self.assertEqual(calls, [])
            self.assertFalse((self.target / "winmm.dll").exists())
            self.assertEqual((self.target / "dxgi.dll").read_bytes(), b"a different user mod installed later")

    def test_owned_plugin_settings_restore_without_losing_other_user_edits(self):
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(b"[Plugins]\nLoadAsiPlugins=false\n[User]\nValue=keep\n")
        files = self.files({"OptiScaler.ini": ini.read_bytes(), "plugins/OptiPatcher.asi": b"synthetic plugin"})
        self.installer.apply_install(self.game, self.target, files, self.state, configuration={("Plugins", "LoadAsiPlugins"): "true"})
        self.assertIn(b"LoadAsiPlugins=true", ini.read_bytes())
        ini.write_bytes(ini.read_bytes() + b"Extra=user-added\n")
        self.installer.uninstall(self.game, self.state)
        self.assertIn(b"LoadAsiPlugins=false", ini.read_bytes())
        self.assertIn(b"Extra=user-added", ini.read_bytes())
        self.assertFalse((self.target / "plugins/OptiPatcher.asi").exists())

    def test_foreign_ini_edits_survive_reinstall_update_and_disable(self):
        for existing in (False, True):
            for disable in (False, True):
                with self.subTest(existing=existing, disable=disable):
                    target = self.target / f"{existing}-{disable}"
                    target.mkdir()
                    ini = target / "OptiScaler.ini"
                    original = b"[Plugins]\nLoadAsiPlugins=false\n[User]\nValue=keep\n"
                    if existing:
                        ini.write_bytes(original)
                    files = self.files({"OptiScaler.ini": original, "support.dll": b"version one"})
                    settings = {("Plugins", "LoadAsiPlugins"): "true"}
                    state = self.state / target.name
                    self.installer.apply_install(self.game, target, files, state, configuration=settings)
                    ini.write_bytes(ini.read_bytes() + b"UserAdded=must-survive\n")
                    self.installer.apply_install(self.game, target, files, state, configuration=settings)
                    files["support.dll"].write_bytes(b"version two")
                    self.installer.apply_install(self.game, target, files, state, configuration={} if disable else settings)
                    self.installer.uninstall(self.game, state)
                    self.assertTrue(ini.is_file(), "Uninstall deleted an INI containing foreign edits")
                    self.assertEqual(ini.read_bytes(), original + b"UserAdded=must-survive\n")
                    journal = next(state.glob("*/state.json"))
                    self.assertEqual(json.loads(journal.read_text())["files"], {})

    def test_equal_foreign_ini_with_requested_settings_stays_unowned(self):
        ini = self.target / "OptiScaler.ini"
        original = b"[Plugins]\nLoadAsiPlugins=true\n"
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        for _ in range(2):
            self.installer.apply_install(self.game, self.target, files, self.state, configuration={("Plugins", "LoadAsiPlugins"): "true"})
        journal = next(self.state.glob("*/state.json"))
        self.assertEqual(json.loads(journal.read_text())["files"], {})
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(ini.read_bytes(), original)

    def test_case_resolved_ini_settings_restore_after_unrelated_edit(self):
        for index, spelling in enumerate(("optiscaler.ini", "oPtIsCaLeR.InI")):
            with self.subTest(spelling=spelling):
                target = self.target / str(index)
                target.mkdir()
                state = self.state / str(index)
                ini = target / spelling
                original = b"[Plugins]\nLoadAsiPlugins=false\n[User]\nValue=keep\n"
                ini.write_bytes(original)
                files = self.files({"OptiScaler.ini": original})
                self.installer.apply_install(self.game, target, files, state, configuration={("Plugins", "LoadAsiPlugins"): "true"})
                ini.write_bytes(ini.read_bytes() + b"Extra=keep\n")
                self.installer.uninstall(self.game, state)
                self.assertEqual(ini.read_bytes(), original + b"Extra=keep\n")
                self.assertEqual(list(target.iterdir()), [ini])

    def test_inline_comment_settings_survive_repeat_install_and_restore(self):
        for index, comment in enumerate((b" ; keep comment", b" # keep comment")):
            with self.subTest(comment=comment):
                target = self.target / str(index)
                target.mkdir()
                state = self.state / str(index)
                ini = target / "OptiScaler.ini"
                original = b"\xef\xbb\xbf[Plugins]\r\nLoadAsiPlugins=false" + comment + b"\r\n[User]\r\nQuoted=\"folder ; literal # name\"\r\n"
                ini.write_bytes(original)
                files = self.files({"OptiScaler.ini": original})
                settings = {("Plugins", "LoadAsiPlugins"): "true"}
                self.installer.apply_install(self.game, target, files, state, configuration=settings)
                # SimpleIni reads the whole RHS; inline comments are not stripped.
                value = next(line.split(b"=", 1)[1] for line in ini.read_bytes().splitlines() if line.startswith(b"LoadAsiPlugins="))
                self.assertEqual(value, b"true")
                self.assertIn(comment + b"\r\nLoadAsiPlugins=true\r\n", ini.read_bytes())
                try:
                    self.installer.apply_install(self.game, target, files, state, configuration=settings)
                except self.installer.InstallerError as error:
                    self.fail(f"Unchanged commented setting rejected on repeat install: {error}")
                ini.write_bytes(ini.read_bytes() + b"Extra=keep\r\n")
                self.installer.uninstall(self.game, state)
                self.assertEqual(ini.read_bytes(), original + b"Extra=keep\r\n")

    def test_already_matching_annotated_booleans_are_normalized_reversibly(self):
        for value in (b"true", b"false"):
            with self.subTest(value=value):
                target = self.target / value.decode()
                target.mkdir()
                state = self.state / value.decode()
                ini = target / "OptiScaler.ini"
                original = b"\xef\xbb\xbf[Plugins]\r\n  LoadAsiPlugins = " + value + b" \t; keep trailing spaces  \r\n"
                ini.write_bytes(original)
                files = self.files({"OptiScaler.ini": original})
                settings = {("Plugins", "LoadAsiPlugins"): value.decode()}
                for _ in range(2):
                    self.installer.apply_install(self.game, target, files, state, configuration=settings)
                    emitted = next(line.split(b"=", 1)[1].lstrip() for line in ini.read_bytes().splitlines() if b"LoadAsiPlugins" in line)
                    self.assertEqual(emitted, value)
                ini.write_bytes(ini.read_bytes() + b"[User]\r\nAdded=keep\r\n")
                self.installer.uninstall(self.game, state)
                self.assertEqual(ini.read_bytes(), original + b"[User]\r\nAdded=keep\r\n")

    def test_quoted_ini_values_do_not_turn_embedded_semicolons_into_comments(self):
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(b'[Libraries]\nXeSSPath="folder ; literal # name/libxess.dll" ; keep\n')
        self.assertEqual(self.installer.ini_value(ini.read_bytes(), "Libraries", "XeSSPath"), "folder ; literal # name/libxess.dll")
        edited = self.installer.edit_ini(ini.read_bytes(), {("Libraries", "XeSSPath"): "new/libxess.dll"})
        self.assertEqual(edited, b'[Libraries]\n ; keep\nXeSSPath=new/libxess.dll\n')
        self.assertEqual(self.installer.ini_value(edited, "Libraries", "XeSSPath"), "new/libxess.dll")

    def test_quoted_path_setting_keeps_literal_comment_markers_across_toggles(self):
        ini = self.target / "OptiScaler.ini"
        original = b'[Libraries]\nXeSSPath="old ; literal # path/libxess.dll" ; keep\n'
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        value = "Z:" + str(self.game / "new ; literal # path/libxess.dll").replace("/", "\\")
        settings = {("Libraries", "XeSSPath"): value}
        self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
        emitted = next(line.split(b"=", 1)[1] for line in ini.read_bytes().splitlines() if line.startswith(b"XeSSPath="))
        self.assertEqual(emitted, value.encode(), "SimpleIni does not remove quotes or inline suffixes")
        self.assertEqual(self.installer.ini_value(ini.read_bytes(), "Libraries", "XeSSPath"), value)
        self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
        ini.write_bytes(ini.read_bytes() + b"UserAdded=keep\n")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(ini.read_bytes(), original + b"UserAdded=keep\n")

    def test_raw_path_literals_survive_planning_repeat_install_and_restore(self):
        from contextlib import chdir
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler.ini").write_bytes(b"[Libraries]\nOptiDllPath=auto\n")
        (core / "OptiScaler/libxess.dll").write_bytes(b"synthetic XeSS")
        (core / "OptiScaler/fakenvapi.dll").write_bytes(b"synthetic NVAPI")
        plugin = self.directory / "fixture.asi"
        plugin.write_bytes(b"synthetic ASI")
        ini = self.target / "OptiScaler.ini"
        original = b"\xef\xbb\xbf[Libraries]\r\nOptiDllPath=support ; literal # name\r\nXeSSPath=custom ; literal # name/libxess.dll\r\n[Plugins]\r\nPath=plugins ; literal # name\r\nLoadAsiPlugins=false ; keep annotation\r\n"
        ini.write_bytes(original)
        expected = {
            ("Libraries", "XeSSPath"): self.game / "custom ; literal # name/libxess.dll",
            ("Plugins", "Path"): self.game / "plugins ; literal # name",
        }
        for iteration in range(3):
            with chdir(self.game):
                plan = self.installer.build_plan(self.game, self.target, core, plugins={"fixture.asi": plugin})
            self.assertIn((self.target.relative_to(self.game) / "support ; literal # name/fakenvapi.dll").as_posix(), plan["files"])
            self.assertIn("custom ; literal # name/libxess.dll", plan["files"])
            self.assertIn("plugins ; literal # name/fixture.asi", plan["files"])
            self.installer.apply_install(self.game, self.target, plan["files"], self.state, configuration=plan["settings"], relative_to_root=True)
            data = ini.read_bytes()
            for (_, key), destination in expected.items():
                emitted = next(line.split(b"=", 1)[1] for line in data.splitlines() if line.startswith(key.encode() + b"="))
                original_value = next(line.split(b"=", 1)[1] for line in original.splitlines() if line.startswith(key.encode() + b"="))
                self.assertEqual(emitted, original_value, "Custom paths are never rewritten")
            self.assertEqual(plan["settings"], {("Plugins", "LoadAsiPlugins"): "true"})
            self.assertIn(b"LoadAsiPlugins=true\r\n", data)
            self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
            if iteration == 0:
                ini.write_bytes(data + b"[User]\r\nAdded=keep\r\n")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(ini.read_bytes(), original + b"[User]\r\nAdded=keep\r\n")
        for destination in expected.values():
            self.assertFalse(destination.is_file())
        self.assertFalse((expected[("Plugins", "Path")] / "fixture.asi").exists())

    def test_foreign_managed_path_and_moved_annotation_edits_remain_foreign(self):
        ini = self.target / "OptiScaler.ini"
        original = b'[Libraries]\nXeSSPath="old ; path/libxess.dll" ; original annotation\n[Plugins]\nLoadAsiPlugins=false\n'
        ini.write_bytes(original)
        files = self.files({"OptiScaler.ini": original})
        value = "Z:" + str(self.game / "new ; path/libxess.dll").replace("/", "\\")
        settings = {("Libraries", "XeSSPath"): value, ("Plugins", "LoadAsiPlugins"): "true"}
        self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
        # A raw suffix is part of this path, not an annotation to discard.
        changed = ini.read_bytes().replace(value.encode(), (value + " ; foreign # path").encode()).replace(b"; original annotation", b"; user-edited annotation")
        ini.write_bytes(changed)
        with self.assertRaises(self.installer.InstallerError):
            self.installer.apply_install(self.game, self.target, files, self.state, configuration=settings)
        self.assertEqual(ini.read_bytes(), changed)
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(ini.read_bytes(), changed.replace(b"LoadAsiPlugins=true", b"LoadAsiPlugins=false"))

    def test_interrupted_uninstall_recognizes_already_restored_original(self):
        destination = self.target / "support.dll"
        original = b"original support library"
        destination.write_bytes(original)
        destination.chmod(0o640)
        files = self.files({"support.dll": b"verified replacement"})
        self.installer.apply_install(self.game, self.target, files, self.state)
        journal = next(self.state.glob("*/state.json"))
        events = []
        real_write = self.installer.atomic_write
        real_save = self.installer.save_state
        def write(path, data, mode=0o600):
            real_write(path, data, mode)
            if path == destination:
                events.append("restored-and-synced")
        def interrupt_save(path, state):
            if not state["files"]:
                events.append("ownership-save-interrupted")
                raise SystemExit("simulated interruption after durable restoration")
            return real_save(path, state)
        with patch.object(self.installer, "atomic_write", write), patch.object(self.installer, "save_state", interrupt_save):
            with self.assertRaises(SystemExit):
                self.installer.uninstall(self.game, self.state)
        self.assertEqual(events, ["restored-and-synced", "ownership-save-interrupted"])
        self.assertEqual(destination.read_bytes(), original)
        self.assertTrue(json.loads(journal.read_text())["files"])
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(json.loads(journal.read_text())["files"], {}, "Retry stranded the restored original as foreign content")
        self.installer.apply_install(self.game, self.target, files, self.state)
        self.assertEqual(destination.read_bytes(), b"verified replacement")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(destination.read_bytes(), original)

    def test_proxy_identification_rejects_strings_outside_a_pe_version_resource(self):
        fake = self.directory / "dxgi.dll"
        fake.write_bytes(b"MZ" + b"\0" * 100 + "OriginalFilename\0OptiScaler.dll\0".encode("utf-16le"))
        self.assertFalse(self.installer.identifies_optiscaler(fake))
        genuine = os.environ.get("DLOR_TEST_OPTISCALER_DLL")
        if genuine:
            self.assertTrue(self.installer.identifies_optiscaler(Path(genuine)))

    def test_per_library_override_uses_launch_cwd_and_restores_configuration(self):
        from contextlib import chdir
        core = self.directory / "nightly fixture"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler.ini").write_bytes(b"[Libraries]\nOptiDllPath=auto\n")
        (core / "OptiScaler/libxess.dll").write_bytes(b"bundled XeSS")
        (core / "OptiScaler/fakenvapi.dll").write_bytes(b"bundled NVAPI")
        extra = self.directory / "replacement-xess.dll"
        extra.write_bytes(b"optional XeSS")
        ini = self.target / "OptiScaler.ini"
        original = b"[Libraries]\nOptiDllPath=custom-support\nXeSSPath=custom/libxess.dll\nNvapiPath=other-libs\n[Plugins]\nPath=my_plugins\n"
        ini.write_bytes(original)
        existing = self.game / "custom/libxess.dll"
        existing.parent.mkdir()
        existing.write_bytes(b"original user XeSS")
        for libraries, expected in (({}, b"bundled XeSS"), ({"libxess.dll": extra}, b"optional XeSS")):
            with self.subTest(extra=bool(libraries)):
                with chdir(self.game):
                    plan = self.installer.build_plan(self.game, self.target, core, extra_libraries=libraries)
                self.assertIn("custom/libxess.dll", plan["files"], "Relative override was placed beside renderer instead of process CWD")
                self.assertIn("other-libs/fakenvapi.dll", plan["files"])
                self.assertEqual(plan["settings"], {})
                self.assertNotIn(("Libraries", "OptiDllPath"), plan["settings"])
                self.assertNotIn(("Plugins", "Path"), plan["settings"])
                self.installer.apply_install(self.game, self.target, plan["files"], self.state, configuration=plan["settings"], relative_to_root=True)
                self.assertEqual(existing.read_bytes(), expected)
                self.assertEqual(ini.read_bytes(), original)
                # No path normalization is persisted; unsafe later CWD is refused.
                with chdir(self.directory):
                    with self.assertRaises(ValueError):
                        self.installer.build_plan(self.game, self.target, core, extra_libraries=libraries)
                with chdir(self.game):
                    repeated = self.installer.build_plan(self.game, self.target, core, extra_libraries=libraries)
                self.assertIn("custom/libxess.dll", repeated["files"])
                self.installer.apply_install(self.game, self.target, repeated["files"], self.state, configuration=repeated["settings"], relative_to_root=True)
                ini.write_bytes(ini.read_bytes() + b"UserAdded=keep\n")
                self.installer.uninstall(self.game, self.state)
                self.assertEqual(existing.read_bytes(), b"original user XeSS")
                self.assertEqual(ini.read_bytes(), original + b"UserAdded=keep\n")
                ini.write_bytes(original)

    def test_relative_per_library_override_refuses_unverified_launch_cwd(self):
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler.ini").write_bytes(b"[Libraries]\nXeSSPath=custom/libxess.dll\n")
        (core / "libxess.dll").write_bytes(b"synthetic XeSS")
        (self.game / "Case").mkdir()
        (self.game / "case").mkdir()
        (self.game / "link").symlink_to(self.target, target_is_directory=True)
        for cwd in (self.directory, self.game / "missing", self.game / "Case", self.game / "link"):
            with self.subTest(cwd=cwd), patch.object(Path, "cwd", return_value=cwd):
                with self.assertRaises(ValueError, msg="Unverified CWD must not silently use the renderer directory"):
                    self.installer.build_plan(self.game, self.target, core)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_relative_plugin_path_refuses_unverified_launch_cwd(self):
        from contextlib import chdir
        core = self.directory / "core"
        (core / "OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler.ini").write_bytes(b"[Plugins]\nPath=my_plugins\n")
        plugin = self.directory / "fixture.asi"
        plugin.write_bytes(b"synthetic ASI")
        (self.game / "Case").mkdir()
        (self.game / "case").mkdir()
        (self.game / "link").symlink_to(self.target, target_is_directory=True)
        with chdir(self.directory):
            with self.assertRaises(ValueError, msg="Outside-game CWD must not silently use the game root"):
                self.installer.build_plan(self.game, self.target, core, plugins={"fixture.asi": plugin})
        for cwd in (self.game / "missing", self.game / "Case", self.game / "link"):
            with self.subTest(cwd=cwd), patch.object(Path, "cwd", return_value=cwd):
                with self.assertRaises(ValueError):
                    self.installer.build_plan(self.game, self.target, core, plugins={"fixture.asi": plugin})
        self.assertEqual(list(self.target.iterdir()), [])
        # The default path is library-relative, independent of launch CWD.
        (core / "OptiScaler.ini").write_bytes(b"[Plugins]\nPath=auto\n")
        with chdir(self.directory):
            plan = self.installer.build_plan(self.game, self.target, core, plugins={"fixture.asi": plugin})
        self.assertIn((self.target.relative_to(self.game) / "OptiScaler/plugins/fixture.asi").as_posix(), plan["files"])
        self.assertNotIn(("Plugins", "Path"), plan["settings"])

    def test_nightly_plan_respects_custom_library_and_plugin_paths(self):
        from contextlib import chdir
        core = self.directory / "nightly fixture"
        (core / "OptiScaler/D3D12_OptiScaler").mkdir(parents=True)
        (core / "OptiScaler.dll").write_bytes(b"synthetic core")
        (core / "OptiScaler.ini").write_bytes(b"[Libraries]\nOptiDllPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=false\n")
        (core / "OptiScaler/libxess.dll").write_bytes(b"synthetic library")
        (core / "OptiScaler/D3D12_OptiScaler/D3D12Core.dll").write_bytes(b"synthetic D3D")
        ini = self.target / "OptiScaler.ini"
        original = b"[Libraries]\nOptiDllPath=custom\\libs\n[Plugins]\nPath=my_plugins\nLoadAsiPlugins=false\n"
        ini.write_bytes(original)
        foreign = self.target / "my_plugins/foreign.asi"
        foreign.parent.mkdir()
        foreign.write_bytes(b"original user plugin")
        plugin = self.directory / "OptiPatcher.asi"
        plugin.write_bytes(b"synthetic ASI")
        # Custom PluginPath is passed directly to filesystem operations, so
        # relative values use process CWD, not the game or library directory.
        with chdir(self.target):
            plan = self.installer.build_plan(self.game, self.target, core, plugins={"OptiPatcher.asi": plugin}, proxy="dxgi")
        prefix = self.target.relative_to(self.game).as_posix()
        self.assertIn(prefix + "/dxgi.dll", plan["files"])
        self.assertIn(prefix + "/custom/libs/libxess.dll", plan["files"])
        self.assertIn(prefix + "/custom/libs/D3D12_OptiScaler/D3D12Core.dll", plan["files"])
        self.assertIn(prefix + "/my_plugins/OptiPatcher.asi", plan["files"])
        self.assertNotIn(("Plugins", "Path"), plan["settings"])
        self.assertEqual(plan["settings"][("Plugins", "LoadAsiPlugins")], "true")
        self.assertNotIn(prefix + "/OptiScaler/libxess.dll", plan["files"])
        self.installer.apply_install(self.game, self.target, plan["files"], self.state, configuration=plan["settings"], relative_to_root=True)
        with chdir(self.directory):
            with self.assertRaises(ValueError):
                self.installer.build_plan(self.game, self.target, core, plugins={"OptiPatcher.asi": plugin})
        self.assertEqual(ini.read_bytes(), original.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
        with chdir(self.target):
            repeated = self.installer.build_plan(self.game, self.target, core, plugins={"OptiPatcher.asi": plugin})
        self.assertEqual(repeated["files"], plan["files"])
        self.installer.apply_install(self.game, self.target, repeated["files"], self.state, configuration=repeated["settings"], relative_to_root=True)
        self.assertEqual((foreign.parent / "OptiPatcher.asi").read_bytes(), b"synthetic ASI")
        self.assertEqual(foreign.read_bytes(), b"original user plugin")
        self.assertFalse((self.game / "my_plugins").exists())
        ini.write_bytes(ini.read_bytes() + b"[User]\nAdded=keep\n")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(ini.read_bytes(), original + b"[User]\nAdded=keep\n")
        self.assertEqual(foreign.read_bytes(), b"original user plugin")
        self.assertFalse((foreign.parent / "OptiPatcher.asi").exists())

    def test_failed_update_restores_previous_working_files_and_ownership(self):
        original = self.target / "a.dll"
        original.write_bytes(b"original game library")
        files = self.files({"a.dll": b"version one a", "b.dll": b"version one b"})
        self.installer.apply_install(self.game, self.target, files, self.state)
        for source in files.values():
            source.write_bytes(b"version two")
        real_write = self.installer.atomic_write
        failed = False
        def fail_once(path, data, mode=0o600):
            nonlocal failed
            if path == self.target / "b.dll" and not failed:
                failed = True
                raise OSError("simulated write failure")
            return real_write(path, data, mode)
        self.installer.atomic_write = fail_once
        with self.assertRaises(OSError):
            self.installer.apply_install(self.game, self.target, files, self.state)
        self.assertEqual(original.read_bytes(), b"version one a")
        self.assertEqual((self.target / "b.dll").read_bytes(), b"version one b")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(original.read_bytes(), b"original game library")
        self.assertFalse((self.target / "b.dll").exists())

    def test_unsafe_plan_is_rejected_before_any_game_file_changes(self):
        good = self.files({"new.dll": b"verified fixture"})["new.dll"]
        for bad in ["../escape.dll", "/absolute.dll", "folder/../../escape.dll", "bad\\name.dll"]:
            with self.subTest(path=bad):
                with self.assertRaises(ValueError):
                    self.installer.apply_install(self.game, self.target, {"new.dll": good, bad: good}, self.state)
                self.assertFalse((self.target / "new.dll").exists())
        outside = self.directory / "outside"
        outside.mkdir()
        (self.target / "redirect").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.installer.apply_install(self.game, self.target, {"new.dll": good, "redirect/escape.dll": good}, self.state)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.target / "new.dll").exists())

    def test_existing_configuration_and_equal_foreign_files_remain_unowned(self):
        ini = self.target / "OptiScaler.ini"
        ini.write_bytes(b"[User]\nCustom=keep\n")
        equal = self.target / "LICENSE.txt"
        equal.write_bytes(b"same license")
        files = self.files({"OptiScaler.ini": b"[Defaults]\nSetting=auto\n", "LICENSE.txt": b"same license"})
        self.installer.apply_install(self.game, self.target, files, self.state)
        self.assertEqual(ini.read_bytes(), b"[User]\nCustom=keep\n")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(ini.read_bytes(), b"[User]\nCustom=keep\n")
        self.assertEqual(equal.read_bytes(), b"same license")

    def test_repeated_install_updates_owned_files_and_preserves_first_backup(self):
        original = b"original supporting library"
        destination = self.target / "OptiScaler/support.dll"
        destination.parent.mkdir()
        destination.write_bytes(original)
        files = self.files({"OptiScaler/support.dll": b"verified replacement v1"})
        self.installer.apply_install(self.game, self.target, files, self.state)
        self.installer.apply_install(self.game, self.target, files, self.state)
        files["OptiScaler/support.dll"].write_bytes(b"verified replacement v2")
        self.installer.apply_install(self.game, self.target, files, self.state)
        self.assertEqual(destination.read_bytes(), b"verified replacement v2")
        self.installer.uninstall(self.game, self.state)
        self.assertEqual(destination.read_bytes(), original)

    def test_install_and_uninstall_preserve_nested_payload_layout(self):
        files = self.files({
            "dxgi.dll": b"synthetic proxy",
            "OptiScaler.ini": b"[OptiScaler]\nOptiDllPath=auto\n",
            "OptiScaler/futureBackend.dll": b"synthetic supporting DLL",
            "LICENSE.txt": b"upstream license fixture",
        })
        result = self.installer.apply_install(self.game, self.target, files, self.state, proxy="dxgi")
        self.assertEqual(result["proxy"], "dxgi")
        for name, source in files.items():
            self.assertEqual((self.target / name).read_bytes(), source.read_bytes())
        self.installer.uninstall(self.game, self.state)
        self.assertFalse((self.target / "dxgi.dll").exists())
        self.assertFalse((self.target / "OptiScaler/futureBackend.dll").exists())
        self.assertTrue(self.game.exists())


if __name__ == "__main__":
    unittest.main()
