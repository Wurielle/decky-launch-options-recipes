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
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        OPTISCALER_CACHE_DIR=str(self.cache), TEST_ROOT=str(self.root))
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
        self.run_update(success=False)
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
