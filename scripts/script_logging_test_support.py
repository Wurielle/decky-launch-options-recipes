"""Shared offline logging fixtures and assertions; recipe suites own test cases."""

import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
install_runner = runpy.run_path(str(ROOT / "scripts/runner_test_support.py"))["install_runner"]


class ScriptLoggingFixture(unittest.TestCase):
    script_sources: dict[str, Path]
    launch_cases: list[tuple[str, str, str]]
    option_ids: list[str]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="recipe-logging-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Test the same LF script contents served by GitHub from Windows checkouts.
        self.scripts = {}
        for name, source in self.script_sources.items():
            script = self.root / f"{name}.sh"
            script.write_text(source.read_text())
            self.scripts[name] = script
        self.home = self.root / "home"
        self.home.mkdir()
        install_runner(self.home)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.game = self.root / "Steam game"
        self.game.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=f"{self.bin}:{os.environ['PATH']}")
        self.env["SYSTEM_PATH"] = self.env["PATH"]

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, name, *args, stdin=False):
        command = ["bash", "-s", "--"] if stdin else ["bash", str(self.scripts[name])]
        return subprocess.run([*command, *map(str, args)], env=self.env,
                              input=self.scripts[name].read_text() if stdin else None,
                              capture_output=True, text=True, timeout=15)

    def log(self, name, count=1):
        recipe, script = name.split("-", 1)
        logs = sorted((self.home / ".dlor/logs" / recipe / script).glob("*.log"))
        self.assertEqual(len(logs), count)
        return logs[-1].read_text()

    def check_help_logging(self):
        for name in self.scripts:
            with self.subTest(script=name):
                for count in (1, 2):
                    result = self.run_script(name, "--help")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    log = self.log(name, count)
                    self.assertIn("Usage:", log)
                    self.assertIn("finished with exit status 0", log)

    def check_validation_logging(self):
        for name in self.scripts:
            with self.subTest(script=name):
                result = self.run_script(name, self.root / "missing", stdin=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                log = self.log(name)
                self.assertIn("Error:", log)
                self.assertIn("missing", log)
                self.assertIn("finished with exit status 1", log)

    def check_logging_setup_failure(self):
        (self.home / ".dlor/logs").write_text("blocks log directory creation")
        for name in self.scripts:
            with self.subTest(script=name):
                result = self.run_script(name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("could not enable logging", result.stderr)
                self.assertIn("Usage:", result.stdout)

    def check_log_write_failure(self):
        # Exercise GNU tee's real write-error handling without filling the disk.
        self.tool("tee", 'exec /usr/bin/tee "$@" /dev/full')
        for name in self.scripts:
            with self.subTest(script=name):
                result = self.run_script(name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("/dev/full", result.stderr)
                self.assertIn("finished with exit status 0", self.log(name))

    def check_runner_token_classification(self):
        # Compatibility with the deployed Launch Options parser: it classifies
        # every token before %command%, including the quoted bash -c body.
        recipes = json.loads((ROOT / "recipes.json").read_text())
        found = set()
        for recipe in recipes:
            self.assertTrue({"name", "launchOptions"} <= set(recipe))
            for option in recipe["launchOptions"]:
                if option["id"] not in self.option_ids:
                    continue
                found.add(option["id"])
                with self.subTest(option=option["id"]):
                    tokens = shlex.split(option["on"])
                    prefix, environment = [], {}
                    for token in tokens[:tokens.index("%command%")]:
                        if "=" in token and not token.startswith("-") and "/" not in token.split("=", 1)[0]:
                            key, value = token.split("=", 1)
                            environment[key] = value
                        else:
                            prefix.append(token)
                    self.assertNotIn("LD_PRELOAD", environment)
                    allowed_environment = {"WINEDLLOVERRIDES"}
                    self.assertTrue(set(environment) <= allowed_environment)
                    self.assertEqual(prefix[0], "~/.dlor/run")
                    self.assertEqual(len(prefix), 5)
                    self.assertRegex(prefix[1], r"^[a-z0-9-]+$")
                    self.assertRegex(prefix[2], r"^[a-z0-9-]+$")
                    self.assertRegex(prefix[3], r"^[a-f0-9]{40}$")
                    self.assertEqual(prefix[4], "--")
        self.assertEqual(found, set(self.option_ids))

    def check_host_tools_environment(self, curl_body, cached_files):
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
                        LD_LIBRARY_PATH="/test/steam/pinned_libs_64",
                        LD_PRELOAD="/test/steam/gameoverlayrenderer.so",
                        SYSTEM_PATH=self.env["PATH"], SYSTEM_LD_LIBRARY_PATH="")
        self.tool("unzip", "exit 0")
        self.tool("curl", curl_body)
        for relative in cached_files:
            dll = self.root / relative
            dll.parent.mkdir(parents=True)
            dll.write_text("cached release")
        marker = self.root / "game-environment.json"
        game = shlex.join(["python3", "-c",
                           "import json, os, pathlib; pathlib.Path(os.environ['TEST_GAME_MARKER']).write_text(json.dumps({key: os.environ.get(key) for key in ['LD_LIBRARY_PATH', 'LD_PRELOAD', 'STEAM_RUNTIME']}))"])
        self.env["TEST_GAME_MARKER"] = str(marker)
        for name, option, success in self.launch_cases:
            with self.subTest(script=name):
                self.env["TEST_RECIPE_SCRIPT"] = str(self.scripts[name])
                marker.unlink(missing_ok=True)
                result = subprocess.run(["bash", "-c", options[option]["on"].replace("%command%", game)],
                                        env=self.env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                log = self.log(name)
                self.assertIn(success, log)
                self.assertIn("finished with exit status 0", log)
                self.assertNotIn("CURL_OPENSSL_4", log)
                self.assertNotIn("ld.so", log)
                environment = json.loads(marker.read_text())
                self.assertEqual(environment["LD_LIBRARY_PATH"], self.env["LD_LIBRARY_PATH"])
                self.assertEqual(environment["LD_PRELOAD"], self.env["LD_PRELOAD"])
                self.assertEqual(environment["STEAM_RUNTIME"], str(runtime))

                # Older imported wrappers can still pipe directly into bash -s.
                # The script must clean its own environment before any tools run.
                self.prepare_direct_run(name)
                result = self.run_script(name, self.game, stdin=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                log = self.log(name, count=2)
                self.assertIn(success, log)
                self.assertNotIn("CURL_OPENSSL_4", log)
                self.assertNotIn("ld.so", log)

    def prepare_direct_run(self, name):
        """Recipe suites may restore inputs consumed by their first invocation."""

    def check_launch_failure_continuation(self, verified_source_path=""):
        recipes = json.loads((ROOT / "recipes.json").read_text())
        options = {o["id"]: o for r in recipes for o in r["launchOptions"]}
        runtime = self.root / "Steam runtime"
        (runtime / "scripts").mkdir(parents=True)
        switch = runtime / "scripts/switch-runtime.sh"
        switch.write_text('#!/usr/bin/env bash\nshift 2\nexec "$@"\n')
        switch.chmod(0o755)
        self.env.update(STEAM_RUNTIME=str(runtime), STEAM_COMPAT_INSTALL_PATH=str(self.game),
                        TEST_VERIFIED_SOURCE_PATH=verified_source_path)
        self.tool("unzip", "exit 0")
        self.tool("rm", "echo 'uninstall failed' >&2; exit 9")
        arguments = ["path with spaces", 'with "quotes"', "$literal"]
        marker = self.root / "launched.json"
        game = shlex.join(["python3", "-c",
                           "import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))",
                           str(marker), *arguments])
        for name, option, _ in self.launch_cases:
            with self.subTest(script=name):
                marker.unlink(missing_ok=True)
                self.tool("curl", f'''
if [[ -n "$TEST_VERIFIED_SOURCE_PATH" && "$*" == *"$TEST_VERIFIED_SOURCE_PATH"* ]]; then
    echo 'verified source download failed' >&2
    exit 22
elif [[ "$*" == *raw.githubusercontent.com* ]]; then
    while [[ "$1" != --output && "$1" != -o ]]; do shift; done
    cat {shlex.quote(str(self.scripts[name]))} > "$2"
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
