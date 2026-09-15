"""Offline logging and launch-continuation checks for downloaded recipe scripts."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "reframework-update": ROOT / "recipes/reframework/scripts/update.sh",
    "reframework-uninstall": ROOT / "recipes/reframework/scripts/uninstall.sh",
    "optiscaler-update-nightly": ROOT / "recipes/optiscaler/scripts/update-nightly.sh",
}


class ScriptLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="recipe-logging-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.game = self.root / "Steam game"
        self.game.mkdir()
        (self.game / "OptiScaler.ini").write_text("user config")
        (self.game / "dxgi.dll").write_text("original")
        (self.game / "dinput8.dll").write_text("original")
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=f"{self.bin}:{os.environ['PATH']}",
                        REFRAMEWORK_CACHE_DIR=str(self.root / "reframework-cache"),
                        OPTISCALER_CACHE_DIR=str(self.root / "optiscaler-cache"))

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, name, *args, stdin=False):
        command = ["bash", "-s", "--"] if stdin else ["bash", str(SCRIPTS[name])]
        return subprocess.run([*command, *map(str, args)], env=self.env,
                              input=SCRIPTS[name].read_text() if stdin else None,
                              capture_output=True, text=True, timeout=15)

    def log(self, name, count=1):
        recipe, script = name.split("-", 1)
        logs = sorted((self.home / ".dlor/logs" / recipe / script).glob("*.log"))
        self.assertEqual(len(logs), count)
        return logs[-1].read_text()

    def test_help_logs_stdout_and_uses_separate_timestamped_files(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                for count in (1, 2):
                    result = self.run_script(name, "--help")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    log = self.log(name, count)
                    self.assertIn("Usage:", log)
                    self.assertIn("finished with exit status 0", log)

    def test_validation_errors_are_logged_when_piped_into_bash(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                result = self.run_script(name, self.root / "missing", stdin=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                log = self.log(name)
                self.assertIn("Error:", log)
                self.assertIn("missing", log)
                self.assertIn("finished with exit status 1", log)

    def test_logging_setup_failure_does_not_stop_scripts(self):
        (self.home / ".dlor").write_text("blocks log directory creation")
        for name in SCRIPTS:
            with self.subTest(script=name):
                result = self.run_script(name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("could not enable logging", result.stderr)
                self.assertIn("Usage:", result.stdout)

    def test_log_write_failure_does_not_stop_output_or_commands(self):
        # Exercise GNU tee's real write-error handling without filling the disk.
        self.tool("tee", 'exec /usr/bin/tee "$@" /dev/full')
        for name in SCRIPTS:
            with self.subTest(script=name):
                result = self.run_script(name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("/dev/full", result.stderr)
                self.assertIn("finished with exit status 0", self.log(name))

    def test_unexpected_failure_logs_status_and_cleanup_errors(self):
        self.tool("curl", '''
if [[ "$*" == *url_effective* ]]; then
    printf 'https://github.com/praydog/REFramework-nightly/releases/tag/test'
else
    echo 'artifact download failed' >&2
    exit 22
fi''')
        self.tool("unzip", "exit 0")
        self.tool("rm", "echo 'cleanup failed' >&2; exit 9")
        result = self.run_script("reframework-update", self.game)
        self.assertEqual(result.returncode, 22, result.stderr)
        log = self.log("reframework-update")
        self.assertIn("artifact download failed", log)
        self.assertIn("reframework/update line", log)
        self.assertIn("cleanup failed", log)
        self.assertIn("finished with exit status 22", log)

    def test_uninstaller_success_is_logged(self):
        result = self.run_script("reframework-uninstall", self.game)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.game / "dinput8.dll").exists())
        self.assertIn("Uninstalled:", self.log("reframework-uninstall"))

    def test_host_tools_escape_steam_libraries_but_game_keeps_its_environment(self):
        recipes = json.loads((ROOT / "recipes.json").read_text())
        options = {o["id"]: o for r in recipes for o in r["launchOptions"]}
        runtime = self.root / "Steam runtime"
        (runtime / "scripts").mkdir(parents=True)
        self.tool_path = runtime / "scripts/switch-runtime.sh"
        self.tool_path.write_text(
            '#!/usr/bin/env bash\nshift 2\nunset LD_LIBRARY_PATH\n'
            'export STEAM_RUNTIME=""\nexec "$@"\n')
        self.tool_path.chmod(0o755)
        self.env.update(STEAM_RUNTIME=str(runtime), STEAM_COMPAT_INSTALL_PATH=str(self.game),
                        LD_LIBRARY_PATH="/test/steam/pinned_libs_64")
        self.tool("unzip", "exit 0")
        self.tool("curl", '''
if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    echo "curl: Steam libcurl does not provide CURL_OPENSSL_4" >&2
    exit 1
fi
if [[ "$*" == *raw.githubusercontent.com* ]]; then
    cat "$TEST_RECIPE_SCRIPT"
elif [[ "$*" == *url_effective* ]]; then
    printf 'https://github.com/praydog/REFramework-nightly/releases/tag/test'
else
    printf '%s' '[{"draft":false,"tag_name":"test","assets":[{"name":"OptiScaler_test.7z"}]}]'
fi''')
        for cache, relative in (("reframework-cache", "test/dinput8.dll"),
                                ("optiscaler-cache", "test/files/OptiScaler.dll")):
            dll = self.root / cache / relative
            dll.parent.mkdir(parents=True)
            dll.write_text("cached release")
        marker = self.root / "game-environment.json"
        game = shlex.join(["python3", "-c",
                           "import json, os, pathlib; pathlib.Path(os.environ['TEST_GAME_MARKER']).write_text(json.dumps({key: os.environ.get(key) for key in ['LD_LIBRARY_PATH', 'STEAM_RUNTIME']}))"])
        self.env["TEST_GAME_MARKER"] = str(marker)
        for name, option, success in [
            ("reframework-update", "reframework-install-update", "Installed:"),
            ("reframework-uninstall", "reframework-uninstall", "Uninstalled:"),
            ("optiscaler-update-nightly", "optiscaler-nightly-upgrade", "Upgraded:"),
        ]:
            with self.subTest(script=name):
                self.env["TEST_RECIPE_SCRIPT"] = str(SCRIPTS[name])
                marker.unlink(missing_ok=True)
                result = subprocess.run(["bash", "-c", options[option]["on"].replace("%command%", game)],
                                        env=self.env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                log = self.log(name)
                self.assertIn(success, log)
                self.assertIn("finished with exit status 0", log)
                self.assertNotIn("CURL_OPENSSL_4", log)
                environment = json.loads(marker.read_text())
                self.assertEqual(environment["LD_LIBRARY_PATH"], self.env["LD_LIBRARY_PATH"])
                self.assertEqual(environment["STEAM_RUNTIME"], str(runtime))

    def test_launch_wrappers_continue_after_real_script_failures(self):
        recipes = json.loads((ROOT / "recipes.json").read_text())
        options = {o["id"]: o for r in recipes for o in r["launchOptions"]}
        runtime = self.root / "Steam runtime"
        (runtime / "scripts").mkdir(parents=True)
        switch = runtime / "scripts/switch-runtime.sh"
        switch.write_text('#!/usr/bin/env bash\nshift 2\nexec "$@"\n')
        switch.chmod(0o755)
        self.env.update(STEAM_RUNTIME=str(runtime), STEAM_COMPAT_INSTALL_PATH=str(self.game))
        self.tool("unzip", "exit 0")
        self.tool("rm", "echo 'uninstall failed' >&2; exit 9")
        arguments = ["path with spaces", 'with "quotes"', "$literal"]
        marker = self.root / "launched.json"
        game = shlex.join(["python3", "-c",
                           "import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))",
                           str(marker), *arguments])
        for name, option in [
            ("reframework-update", "reframework-install-update"),
            ("reframework-uninstall", "reframework-uninstall"),
            ("optiscaler-update-nightly", "optiscaler-nightly-upgrade"),
        ]:
            with self.subTest(script=name):
                marker.unlink(missing_ok=True)
                self.tool("curl", f'''
if [[ "$*" == *raw.githubusercontent.com* ]]; then
    cat {shlex.quote(str(SCRIPTS[name]))}
else
    echo 'network failed' >&2
    exit 22
fi''')
                result = subprocess.run(["bash", "-c", options[option]["on"].replace("%command%", game)],
                                        env=self.env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(marker.read_text()), arguments)
                log = self.log(name)
                self.assertIn("failed", log)
                self.assertIn("finished with exit status", log)
                self.assertNotIn("finished with exit status 0", log)


if __name__ == "__main__":
    unittest.main()
