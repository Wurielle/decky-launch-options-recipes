"""Offline integration checks: python3 scripts/test-optiscaler-nightly.py.

Requires Bash and Python 3. Fake curl/7z isolate network and archive tooling;
the real updater handles discovery, cache recovery, and installation.
"""

import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "recipes/optiscaler/scripts/update-nightly.sh"


class NightlyUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="optiscaler-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
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
        self.tool("curl", '''
import json, os, pathlib, sys
root = pathlib.Path(os.environ["TEST_ROOT"])
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write("download\\n" if "-o" in args else "check\\n")
if (root / "network-failure").exists():
    sys.exit(22)
if "-o" in args:
    pathlib.Path(args[args.index("-o") + 1]).write_text(
        "invalid" if (root / "bad-download").exists() else "valid archive")
else:
    print(json.dumps([{"draft": False, "tag_name": "nightly-test", "assets": [
        {"name": "OptiScaler_test.7z"}]}]))
''')
        self.tool("7z", '''
import os, pathlib, sys
root = pathlib.Path(os.environ["TEST_ROOT"])
with (root / "calls").open("a") as log:
    log.write("extract\\n")
if pathlib.Path(sys.argv[-1]).read_text() != "valid archive":
    sys.exit(2)
dest = pathlib.Path(next(a[2:] for a in sys.argv if a.startswith("-o")))
(dest / "OptiScaler.dll").write_text("nightly version")
(dest / "OptiScaler.ini").write_text("default settings")
(dest / "amd_fidelityfx_dx12.dll").write_text("nightly dependency")
(dest / "OptiScaler").mkdir()
(dest / "OptiScaler/amd_fidelityfx_upscaler_dx12.dll").write_text("stock nightly upscaler")
(dest / "OptiScaler/amd_fidelityfx_loader_dx12.dll").write_text("nightly loader")
''')

    def tool(self, name, code):
        path = self.bin / name
        path.write_text("#!/usr/bin/env python3\n" + code)
        path.chmod(0o755)

    def run_update(self, success=True):
        result = subprocess.run(["bash", str(SCRIPT), str(self.game)], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
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

    def test_cached_archive_reuse(self):
        self.version.mkdir(parents=True)
        (self.version / "OptiScaler_test.7z").write_text("valid archive")
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
        self.run_update()
        self.assertEqual((self.install / "dxgi.dll").read_text(), "nightly version")
        self.assertEqual((self.install / "future-support.dll").read_text(), "fgmod version")

    def test_corrupt_archive_is_downloaded_again(self):
        self.version.mkdir(parents=True)
        (self.version / "OptiScaler_test.7z").write_text("broken")
        self.run_update()
        self.assert_updated()
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["check", "extract", "download", "extract"])

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
        self.tool("curl", 'print("exit 1")')
        args = ["game path with spaces", 'argument with "quotes"', "$literal"]
        command = shlex.join(["python3", "-c",
                              "import json, sys; print(json.dumps(sys.argv[1:]))", *args])
        result = subprocess.run(["bash", "-c", option["on"].replace("%command%", command)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), args)


if __name__ == "__main__":
    unittest.main()
