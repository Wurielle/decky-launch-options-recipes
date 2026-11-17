"""Offline integration checks: python3 scripts/test-optiscaler-nightly.py.

Requires Bash and Python 3. Synthetic ZIP bytes and an HTTP boundary fixture
exercise the physical updater; no live networking or DLL execution occurs.
"""

import json
import contextlib
import hashlib
import fcntl
import importlib.util
import io
import sys
import zipfile
from unittest.mock import patch
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest
from runner_test_support import install_runner


SCRIPT = Path(__file__).resolve().parents[1] / "recipes/optiscaler/scripts/update-nightly.sh"


class NightlyUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optiscaler-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "update-nightly.sh"
        self.script.write_text(SCRIPT.read_text())
        self.game = self.root / "Steam game"
        self.install = self.game / "Binaries" / "Win64"
        self.install.mkdir(parents=True)
        (self.install / "OptiScaler.ini").write_text("user settings")
        (self.install / "dxgi.dll").write_text("fgmod version")
        self.cache = self.root / "cache"
        self.version = self.cache / "nightly-test"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.fgmod = self.root / "home/fgmod"
        self.fgmod.mkdir(parents=True)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        OPTISCALER_CACHE_DIR=str(self.cache), TEST_ROOT=str(self.root),
                        HOME=str(self.root / "home"))
        self.package_files = {
            "OptiScaler.dll": b"nightly version", "OptiScaler.ini": b"default settings",
            "amd_fidelityfx_dx12.dll": b"nightly dependency",
            "OptiScaler/amd_fidelityfx_upscaler_dx12.dll": b"stock nightly upscaler",
            "OptiScaler/amd_fidelityfx_loader_dx12.dll": b"nightly loader",
        }

    def archive_bytes(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, data in self.package_files.items():
                archive.writestr(name, data)
        return output.getvalue()

    def tool(self, name, code):
        path = self.bin / name
        path.write_text("#!/usr/bin/env python3\n" + code)
        path.chmod(0o755)

    def run_update(self, success=True):
        runtime = SCRIPT.parents[2] / "dlor-optiscaler/scripts"
        self.assertTrue((runtime / "nightly.py").is_file(), "physical verified nightly module is missing")
        with patch.object(sys, "path", [str(runtime), *sys.path]):
            import artifacts, nightly
        output = io.StringIO()
        def transport(url):
            download = "/releases/download/" in url
            with self.calls.open("a") as log:
                log.write("download\n" if download else "check\n")
            if (self.root / "network-failure").exists():
                raise OSError("Could not download the latest nightly release metadata")
            payload = self.archive_bytes()
            if download:
                data = b"invalid" if (self.root / "bad-download").exists() else payload
            else:
                data = json.dumps([{"draft": False, "tag_name": "nightly-test", "assets": [{
                    "name": "OptiScaler_test.7z", "size": len(payload),
                    "browser_download_url": "https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-test/OptiScaler_test.7z",
                    "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}]}]).encode()
            response = io.BytesIO(data)
            response.headers = {"Content-Length": str(len(data))}
            return response
        real_extract = artifacts.extract_archive
        def extract(*args, **kwargs):
            self.assertNotEqual(kwargs.get("cache"), self.cache, "tool bootstrap must not deadlock on the held legacy cache lock")
            with self.calls.open("a") as log: log.write("extract\n")
            return real_extract(*args, **kwargs)
        status = 0
        with patch.dict(os.environ, self.env, clear=True), patch.object(artifacts, "_open", transport), patch.object(artifacts, "extract_archive", extract), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                status = nightly.legacy_upgrade(self.game)
            except Exception as error:
                print(str(error))
                status = 1
        result = subprocess.CompletedProcess([], status, output.getvalue(), "")
        self.assertEqual(status == 0, success, result.stdout)
        return result

    def assert_updated(self):
        self.assertEqual((self.install / "dxgi.dll").read_text(), "nightly version")
        self.assertEqual((self.install / "OptiScaler.ini").read_text(), "user settings")
        self.assertEqual((self.install / "amd_fidelityfx_dx12.dll").read_text(),
                         "nightly dependency")

    def test_first_install_and_extracted_cache_reuse(self):
        self.run_update()
        self.assert_updated()
        (self.install / "dxgi.dll").write_text("fgmod reinstalled")
        self.run_update()
        self.assert_updated()
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["check", "download", "extract", "check"])

    def test_overlay_holds_game_lock_without_creating_a_journal(self):
        runtime = SCRIPT.parents[2] / "dlor-optiscaler/scripts"
        with patch.object(sys, "path", [str(runtime), *sys.path]):
            import nightly
        state = Path(self.env["HOME"]) / ".dlor/state/dlor-optiscaler" / hashlib.sha256(os.fsencode(self.game.resolve())).hexdigest()
        writes = []
        real_write = nightly.atomic_write
        def checked_write(path, *args, **kwargs):
            if path.is_relative_to(self.game):
                # A distinct descriptor must fail to acquire the actual main
                # installer's lock while any legacy game write is in progress.
                with (state / "lock").open("r+b") as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                writes.append(path)
            return real_write(path, *args, **kwargs)
        with patch.object(nightly, "atomic_write", checked_write):
            for _ in range(2):
                self.run_update()
                self.assertFalse((state / "state.json").exists(), "legacy updates must not create a disabling empty journal")
                self.assert_updated()
        self.assertGreater(len(writes), 2)

    def test_legacy_refusal_does_not_recover_an_interrupted_dlor_transaction(self):
        runtime = SCRIPT.parents[2] / "dlor-optiscaler/scripts"
        with patch.object(sys, "path", [str(runtime), *sys.path]):
            import installer
        payload = self.root / "managed-core"
        payload.write_bytes(b"pending DLOR core")
        proxy = self.install / "dxgi.dll"
        real_save = installer.save_state
        def interrupted(path, state):
            if state.get("transaction") and proxy.read_bytes() == payload.read_bytes():
                raise SystemExit("interrupted after actual game write")
            return real_save(path, state)
        state_home = Path(self.env["HOME"]) / ".dlor/state/dlor-optiscaler"
        with patch.object(installer, "save_state", interrupted), patch.object(installer, "recover_transaction", side_effect=SystemExit("power loss")):
            with self.assertRaises(SystemExit):
                installer.apply_install(self.game, self.install, {"dxgi.dll": payload}, state_home)
        journal = next(state_home.glob("*/state.json"))
        self.assertIn("transaction", json.loads(journal.read_bytes()))
        before = proxy.read_bytes(), journal.read_bytes(), (self.install / "OptiScaler.ini").read_bytes()
        result = self.run_update(success=False)
        self.assertIn("DLOR", result.stdout)
        self.assertEqual((proxy.read_bytes(), journal.read_bytes(), (self.install / "OptiScaler.ini").read_bytes()), before)
        self.assertFalse((self.install / "OptiScaler").exists())

    def test_corrupt_extracted_cache_is_rebuilt_from_verified_archive(self):
        self.run_update()
        (self.version / "files/OptiScaler.dll").write_bytes(b"poisoned cached DLL")
        self.run_update()
        self.assert_updated()
        self.assertEqual(self.calls.read_text().splitlines(), ["check", "download", "extract", "check", "extract"])

    def test_case_varied_proxy_and_config_preserve_disk_spelling(self):
        (self.install / "dxgi.dll").rename(self.install / "DXGI.DLL")
        (self.install / "OptiScaler.ini").rename(self.install / "OPTISCALER.INI")
        self.run_update()
        self.assertEqual((self.install / "DXGI.DLL").read_text(), "nightly version")
        self.assertEqual((self.install / "OPTISCALER.INI").read_text(), "user settings")
        self.assertFalse((self.install / "dxgi.dll").exists())

    def test_cached_archive_reuse(self):
        self.version.mkdir(parents=True)
        (self.version / "OptiScaler_test.7z").write_bytes(self.archive_bytes())
        self.run_update()
        self.assert_updated()
        self.assertNotIn("download", self.calls.read_text())

    def test_fgmod_overrides_all_support_dlls_but_not_nightly_injector(self):
        for name in ("amd_fidelityfx_upscaler_dx12.dll", "amd_fidelityfx_loader_dx12.dll",
                     "libxess.dll", "future-support.dll", "OptiScaler.dll"):
            (self.fgmod / name).write_text("fgmod " + name)
        (self.fgmod / "OptiScaler.ini").write_text("fgmod settings")
        (self.fgmod / "renames").mkdir()
        (self.fgmod / "renames/dxgi.dll").write_text("old renamed injector")
        (self.fgmod / "fsr4-unused").mkdir()
        (self.fgmod / "fsr4-unused/amd_fidelityfx_upscaler_dx12.dll").write_text("unselected variant")
        (self.install / "amd_fidelityfx_upscaler_dx12.dll").write_text("stale game copy")
        self.run_update()
        self.assert_updated()
        for name in ("amd_fidelityfx_upscaler_dx12.dll", "amd_fidelityfx_loader_dx12.dll",
                     "libxess.dll", "future-support.dll"):
            self.assertEqual((self.install / "OptiScaler" / name).read_text(), "fgmod " + name)
        self.assertFalse((self.install / "OptiScaler/OptiScaler.dll").exists())
        self.assertFalse((self.install / "OptiScaler/renames").exists())
        self.assertFalse((self.install / "OptiScaler/fsr4-unused").exists())
        self.assertEqual((self.version / "files/OptiScaler/amd_fidelityfx_upscaler_dx12.dll").read_text(),
                         "stock nightly upscaler")

    def test_support_subfolders_match_nightly_path_casing(self):
        files = self.version / "files"
        (files / "OptiScaler/D3D12_OptiScaler").mkdir(parents=True)
        (files / "OptiScaler.dll").write_text("nightly version")
        (files / "OptiScaler/D3D12_OptiScaler/D3D12Core.dll").write_text("stock core")
        (self.fgmod / "D3D12_Optiscaler").mkdir()
        (self.fgmod / "D3D12_Optiscaler/D3D12Core.dll").write_text("fgmod core")
        self.package_files["OptiScaler/D3D12_OptiScaler/D3D12Core.dll"] = b"stock core"
        self.run_update()
        self.assertEqual((self.install / "OptiScaler/D3D12_OptiScaler/D3D12Core.dll").read_text(), "fgmod core")
        self.assertFalse((self.install / "OptiScaler/D3D12_Optiscaler").exists())

    def test_selected_variant_overrides_fgmod_base_without_replacing_injector(self):
        (self.fgmod / "amd_fidelityfx_upscaler_dx12.dll").write_text("base variant")
        for name in ("selected", "other"):
            folder = self.fgmod / name
            folder.mkdir()
            (folder / "amd_fidelityfx_upscaler_dx12.dll").write_text(name)
            (folder / "future-driver.dll").write_text(name + " driver")
            (folder / "OptiScaler.dll").write_text("variant injector")
        (self.fgmod / "install-manifest.json").write_text(json.dumps({
            "selected_default_variant": "other",
            "fsr4_variants": {"selected": {"dir_name": "selected"}, "other": {"dir_name": "other"}},
        }))
        self.env["FGMOD_FSR4_VARIANT"] = "selected"
        self.run_update()
        self.assert_updated()
        self.assertEqual((self.install / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll").read_text(), "selected")
        self.assertEqual((self.install / "OptiScaler/future-driver.dll").read_text(), "selected driver")
        self.assertFalse((self.install / "OptiScaler/other").exists())
        self.assertFalse((self.install / "OptiScaler/selected").exists())

    def test_cached_update_refreshes_fgmod_and_removes_only_managed_copies(self):
        for name in ("future-support.dll", "removed-support.dll", "modified-support.dll"):
            (self.fgmod / name).write_text("fgmod version")
        self.run_update()
        (self.fgmod / "future-support.dll").write_text("updated fgmod version")
        (self.fgmod / "removed-support.dll").unlink()
        (self.fgmod / "modified-support.dll").unlink()
        (self.install / "OptiScaler/modified-support.dll").write_text("another mod")
        self.run_update()
        self.assertEqual((self.install / "OptiScaler/future-support.dll").read_text(), "updated fgmod version")
        self.assertFalse((self.install / "OptiScaler/removed-support.dll").exists())
        self.assertEqual((self.install / "OptiScaler/modified-support.dll").read_text(), "another mod")
        self.assertEqual(self.calls.read_text().splitlines().count("download"), 1)

    def test_without_fgmod_uses_nightly_files(self):
        shutil.rmtree(self.fgmod)
        self.run_update()
        self.assertEqual((self.install / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll").read_text(),
                         "stock nightly upscaler")

    def test_flat_archive_uses_fgmod_support_dlls(self):
        files = self.version / "files"
        files.mkdir(parents=True)
        (files / "OptiScaler.dll").write_text("nightly version")
        (files / "future-support.dll").write_text("stock archive file")
        (self.fgmod / "future-support.dll").write_text("fgmod version")
        (self.fgmod / "OptiScaler.dll").write_text("old injector")
        self.package_files = {"OptiScaler.dll": b"nightly version", "future-support.dll": b"stock archive file"}
        self.run_update()
        self.assertEqual((self.install / "dxgi.dll").read_text(), "nightly version")
        self.assertEqual((self.install / "future-support.dll").read_text(), "fgmod version")

    def test_corrupt_archive_is_downloaded_again(self):
        self.version.mkdir(parents=True)
        (self.version / "OptiScaler_test.7z").write_text("broken")
        self.run_update()
        self.assert_updated()
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["check", "download", "extract"])

    def test_bad_download_leaves_installation_unchanged(self):
        (self.root / "bad-download").touch()
        self.run_update(success=False)
        self.assertEqual((self.install / "dxgi.dll").read_text(), "fgmod version")
        self.assertFalse((self.version / "files").exists())
        self.assertEqual(list(self.version.glob(".files.*")), [])

    def test_unrelated_dxgi_is_untouched(self):
        unrelated = self.game / "Other"
        unrelated.mkdir()
        (unrelated / "dxgi.dll").write_text("other mod")
        self.run_update()
        self.assertEqual((unrelated / "dxgi.dll").read_text(), "other mod")

    def test_missing_installation_does_not_download(self):
        shutil.rmtree(self.install)
        self.run_update(success=False)
        self.assertFalse(self.calls.exists())

    def test_network_failure_leaves_installation_unchanged(self):
        (self.root / "network-failure").touch()
        result = self.run_update(success=False)
        self.assertIn("Could not download the latest nightly release metadata", result.stdout)
        self.assertNotIn("JSONDecodeError", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual((self.install / "dxgi.dll").read_text(), "fgmod version")

    def test_launch_wrapper_continues_after_updater_failure_and_preserves_arguments(self):
        install_runner(Path(self.env["HOME"]))
        recipes = json.loads((SCRIPT.parents[3] / "recipes.json").read_text())
        recipe = next(r for r in recipes if r["name"] == "OptiScaler")
        option = next(o for o in recipe["launchOptions"]
                      if o["id"] == "optiscaler-nightly-upgrade")
        self.assertEqual(option["priority"], -1)
        self.assertNotIn("valueId", option)
        self.assertEqual(option["off"], "")
        runtime = self.root / "Steam runtime"
        (runtime / "scripts").mkdir(parents=True)
        switch = runtime / "scripts/switch-runtime.sh"
        switch.write_text('#!/usr/bin/env bash\nshift 2\nexec "$@"\n')
        switch.chmod(0o755)
        self.env.update(STEAM_RUNTIME=str(runtime), STEAM_COMPAT_INSTALL_PATH=str(self.game))
        self.env["SYSTEM_PATH"] = self.env["PATH"]
        self.tool("curl", 'import pathlib, sys; pathlib.Path(sys.argv[sys.argv.index("--output") + 1]).write_text("exit 1\\n")')
        args = ["game path with spaces", 'argument with "quotes"', "$literal"]
        marker = self.root / "game-arguments.json"
        command = shlex.join(["python3", "-c",
                              "import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))",
                              str(marker), *args])
        result = subprocess.run(["bash", "-c", option["on"].replace("%command%", command)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(marker.read_text()), args)
        self.assertIn("Recipe helper failed (exit 1)", result.stderr)


if __name__ == "__main__":
    unittest.main()
