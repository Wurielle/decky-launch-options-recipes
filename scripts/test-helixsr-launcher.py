"""Offline single-toggle launcher tests with explicitly fake helper boundaries."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "recipes/helixsr/launcher.sh"
HELPER = r'''
import json, os, pathlib, sys
stage = sys.argv[1]
runtime = pathlib.Path(os.environ["DLOR_HELIXSR_RUNTIME_FILE"])
with open(os.environ["TEST_ORDER"], "a") as output:
    output.write(stage + ":" + os.environ["DLOR_HELIXSR_ACTION"] + "\n")
assert os.environ.get("LD_LIBRARY_PATH", "") == ""
assert not os.environ.get("STEAM_RUNTIME")
if stage == os.environ.get("TEST_FAIL_STAGE") and os.environ["DLOR_HELIXSR_ACTION"] == os.environ.get("TEST_FAIL_ACTION", os.environ["DLOR_HELIXSR_ACTION"]):
    sys.exit(17)
if stage == "setup":
    pathlib.Path(str(runtime) + ".setup").write_text("ready\n")
elif stage == "dependency" and os.environ["DLOR_HELIXSR_ACTION"] == "on":
    runtime.write_text("dxgi\n")
    pathlib.Path(str(runtime) + ".config").write_text(os.environ["TEST_CONFIG"] + "\n")
    pathlib.Path(os.environ["TEST_ARGS"]).write_text(os.environ["DLOR_HELIXSR_ARGS"])
elif stage == "configure":
    pathlib.Path(str(runtime) + ".configured").write_text("ready\n")
'''


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="helixsr launcher ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.helper = self.home / "offline_helper.py"
        self.helper.write_text(HELPER)
        self.config = self.home / "game/OptiScaler.ini"
        self.config.parent.mkdir()
        self.config.write_text("fixture configuration")
        self.env = dict(os.environ, HOME=str(self.home), TEST_ORDER=str(self.home / "order"),
                        TEST_CONFIG=str(self.config), TEST_ARGS=str(self.home / "args"),
                        STEAM_RUNTIME="/original/steam/runtime", SYSTEM_LD_LIBRARY_PATH="",
                        LD_LIBRARY_PATH="/original/steam/libs", SYSTEM_PATH=os.environ["PATH"],
                        WINEDLLOVERRIDES="dxgi=b;dinput8=n,b;foo,version=b")

    def launch(self, action="on"):
        self.assertTrue(LAUNCHER.exists(), "HelixSR needs a complete single-toggle launcher")
        template = LAUNCHER.read_text()
        for stage in ("setup", "dependency", "configure"):
            template = template.replace("@@" + stage.upper() + "@@", shlex.join([sys.executable, str(self.helper), stage]))
        game = [sys.executable, "-I", "-c", "import json,os,sys; print(json.dumps({'args':sys.argv[1:],'env':{k:os.environ.get(k) for k in ['LD_LIBRARY_PATH','STEAM_RUNTIME','WINEDLLOVERRIDES','PYTHONHOME']}}));sys.exit(42)",
                "argument with spaces", 'literal "quote"', "$literal", "line\nbreak"]
        result = subprocess.run(["bash", "-c", template, "--", *game],
                                env=dict(self.env, DLOR_HELIXSR_ACTION=action), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        value = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(value["args"], game[4:])
        self.assertEqual(value["env"]["LD_LIBRARY_PATH"], self.env["LD_LIBRARY_PATH"])
        self.assertEqual(value["env"]["STEAM_RUNTIME"], self.env["STEAM_RUNTIME"])
        self.assertEqual(list((self.home / ".dlor/runtime/helixsr").glob("*")), [])
        order = self.home / "order"
        return value, order.read_text().splitlines() if order.exists() else [], game

    def test_single_toggle_prepares_dependency_configures_and_merges_override(self):
        value, order, game = self.launch()
        self.assertEqual(order, ["setup:on", "dependency:on", "configure:on"])
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], "dinput8=n,b;foo,version=b;dxgi=n,b")
        self.assertEqual(json.loads((self.home / "args").read_text()), game)
        logs = list((self.home / ".dlor/logs/helixsr/launcher").glob("*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("launching game", logs[0].read_text())
        self.assertNotIn("argument with spaces", logs[0].read_text())


    def test_generated_recipe_contains_automatic_setup_and_dependency(self):
        options = [option for recipe in json.loads((ROOT / "recipes.json").read_text())
                   for option in recipe["launchOptions"] if option["id"] == "helixsr"]
        option, = options
        self.assertIn("helixsr setup", option["on"])
        self.assertIn("helixsr dependency", option["on"])

        self.assertEqual(option["on"].count("%command%"), 1)
        self.assertEqual(option["off"].count("%command%"), 1)

    def test_disabled_toggle_never_runs_setup(self):
        value, order, _ = self.launch("off")
        self.assertEqual(order, ["configure:off", "dependency:off"])
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], self.env["WINEDLLOVERRIDES"])

    def test_independent_optiscaler_off_respects_helixsr_demand(self):
        option = next(option for recipe in json.loads((ROOT / "recipes.json").read_text())
                      for option in recipe["launchOptions"] if option["id"] == "optiscaler")
        script = self.home / "fgmod/fgmod-uninstaller.sh"
        script.parent.mkdir()
        script.write_text('#!/bin/bash\nprintf called > "$HOME/uninstaller-called"\nexec "$@"\n')
        script.chmod(0o755)
        for demand in ("on", "off"):
            result = subprocess.run(["bash", "-c", option["off"].replace("%command%", "/bin/true")],
                                    env=dict(self.env, DLOR_HELIXSR_ACTION=demand), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((self.home / "uninstaller-called").exists(), demand == "off")


    def test_setup_cancellation_stops_dependent_work_and_keeps_game(self):
        self.env["TEST_FAIL_STAGE"] = "setup"
        value, order, _ = self.launch()
        self.assertEqual(order, ["setup:on"])
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], self.env["WINEDLLOVERRIDES"])

    def test_dependency_failure_stops_configuration_and_keeps_game(self):
        self.env["TEST_FAIL_STAGE"] = "dependency"
        value, order, _ = self.launch()
        self.assertEqual(order, ["setup:on", "dependency:on"])
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], self.env["WINEDLLOVERRIDES"])

    def test_failed_restore_does_not_remove_dependency(self):
        self.env["TEST_FAIL_STAGE"] = "configure"
        _, order, _ = self.launch("off")
        self.assertEqual(order, ["configure:off"])

    def test_configuration_failure_attempts_restore_before_dependency_cleanup(self):
        self.env["TEST_FAIL_STAGE"] = "configure"
        value, order, _ = self.launch()
        self.assertEqual(order, ["setup:on", "dependency:on", "configure:on", "configure:off"])
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], self.env["WINEDLLOVERRIDES"])

    def test_successful_rollback_precedes_dependency_cleanup(self):
        self.env.update(TEST_FAIL_STAGE="configure", TEST_FAIL_ACTION="on")
        value, order, _ = self.launch()
        self.assertEqual(order, ["setup:on", "dependency:on", "configure:on", "configure:off", "dependency:off"])
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], self.env["WINEDLLOVERRIDES"])

    def test_shared_override_groups_preserve_non_dependency_names(self):
        self.env["WINEDLLOVERRIDES"] = "dxgi,version=b;dinput8=n"
        value, _, _ = self.launch()
        self.assertEqual(value["env"]["WINEDLLOVERRIDES"], "version=b;dinput8=n;dxgi=n,b")


    def test_game_inherits_existing_file_descriptors(self):
        template = LAUNCHER.read_text()
        for stage in ("setup", "dependency", "configure"):
            template = template.replace("@@" + stage.upper() + "@@", shlex.join([sys.executable, str(self.helper), stage]))
        result = subprocess.run(["bash", "-c", 'exec 7<<<"keep-me"; exec bash -c "$1" -- bash -c "$2"',
                                 "--", template, 'IFS= read -r -u 7 value; [[ "$value" == keep-me ]]'],
                                env=dict(self.env, DLOR_HELIXSR_ACTION="off"), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_auxiliary_python_ignores_game_pythonhome_but_game_keeps_it(self):
        self.env["PYTHONHOME"] = str(self.home / "game python")
        value, order, _ = self.launch()
        self.assertEqual(order, ["setup:on", "dependency:on", "configure:on"])
        self.assertEqual(value["env"]["PYTHONHOME"], self.env["PYTHONHOME"])

    def test_launcher_logging_failure_does_not_block_feature_or_game(self):
        directory = self.home / ".dlor/logs"
        directory.mkdir(parents=True)
        (directory / "helixsr").write_text("explicit log-directory obstruction fixture")
        _, order, _ = self.launch()
        self.assertEqual(order, ["setup:on", "dependency:on", "configure:on"])

    def test_launcher_log_retention_preserves_unrelated_entries(self):
        directory = self.home / ".dlor/logs/helixsr/launcher"
        directory.mkdir(parents=True)
        for number in range(15):
            (directory / f"2000-01-01T00-00-{number:02d}.log").write_text("old fixture log")
        (directory / "notes.txt").write_text("keep")
        (directory / "000-link.log").symlink_to(directory / "notes.txt")
        (directory / "000-directory.log").mkdir()
        self.launch("off")
        logs = [p for p in directory.glob("*.log") if p.is_file() and not p.is_symlink()]
        self.assertEqual(len(logs), 10)
        self.assertEqual((directory / "notes.txt").read_text(), "keep")
        self.assertTrue((directory / "000-link.log").is_symlink())
        self.assertTrue((directory / "000-directory.log").is_dir())


    def test_generated_wrapper_survives_dlo_home_expansion_with_spaces(self):
        from runner_test_support import install_runner
        install_runner(self.home)
        payloads = self.home / "payloads"
        payloads.mkdir()
        for stage in ("setup", "dependency", "configure"):
            (payloads / (stage + ".sh")).write_text("#!/bin/bash\nexec " + shlex.join([sys.executable, "-I", str(self.helper), stage]) + "\n")
        tools = self.home / "bin"
        tools.mkdir()
        curl = tools / "curl"
        curl.write_text('#!/bin/bash\nurl="${@: -1}"; name="${url##*/}"; while [[ "$1" != --output ]]; do shift; done; cp -- "$HOME/payloads/$name" "$2"\n')
        curl.chmod(0o755)
        option = next(option for recipe in json.loads((ROOT / "recipes.json").read_text())
                      for option in recipe["launchOptions"] if option["id"] == "helixsr")
        tokens = shlex.split(option["on"])
        assignment = tokens.pop(0)
        key, value = assignment.split("=", 1)
        # DLO expands ~ in every prefix token, including an entire bash -c body.
        prefix = [token.replace("~", str(self.home)) for token in tokens[:tokens.index("%command%")]]
        env = dict(self.env, PATH=str(tools) + ":" + self.env["PATH"],
                   SYSTEM_PATH=str(tools) + ":" + self.env["PATH"],
                   STEAM_COMPAT_INSTALL_PATH=str(self.config.parent), **{key: value})
        result = subprocess.run([*prefix, "/bin/bash", "-c", "exit 42"],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        order = self.home / "order"
        self.assertTrue(order.exists(), result.stdout + result.stderr)
        self.assertEqual(order.read_text().splitlines(), ["setup:on", "dependency:on", "configure:on"])


if __name__ == "__main__":
    unittest.main()
