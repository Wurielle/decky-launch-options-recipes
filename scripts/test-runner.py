"""Offline runner/import checks: python3 scripts/test-runner.py (Linux/WSL)."""
import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runner_test_support import ROOT, install_runner, plugin


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlor runner ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        install_runner(self.home)
        self.source = {"recipe": "optiscaler", "script": "update-nightly", "sha": "1" * 40}
        self.source["url"] = ("https://raw.githubusercontent.com/Wurielle/decky-launch-options-recipes/"
                              + self.source["sha"] + "/recipes/optiscaler/scripts/update-nightly.sh")
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.downloads = self.home / "tmp"
        self.downloads.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=f"{self.bin}:{os.environ['PATH']}",
                        TMPDIR=str(self.downloads), STEAM_COMPAT_INSTALL_PATH="game with spaces")
        self.env["SYSTEM_PATH"] = self.env["PATH"]
        self.payload = self.home / "remote.sh"
        self.payload.write_text('printf "%s" "$1" > "$HOME/helper-ran"\n')
        self.tool("curl", '''
printf '%s\n' "${@: -1}" >> "$HOME/downloads"
while [[ "$1" != --output ]]; do shift; done
cat "$HOME/remote.sh" > "$2"
exit "${DOWNLOAD_STATUS:-0}"
''')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    def command(self, source=None, pinned=True):
        source = self.source if source is None else source
        return [str(self.home / ".dlor/run"), source["recipe"], source["script"],
                *([source["sha"]] if pinned else []), "--",
                "/bin/bash", "-c", 'printf game > "$HOME/game-ran"; exit "${GAME_STATUS:-0}"']

    def run_game(self, source=None, pinned=True):
        result = subprocess.run(self.command(source, pinned), env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual((self.home / "game-ran").read_text(), "game")
        self.assertEqual(list(self.downloads.iterdir()), [])
        return result

    def test_downloads_every_time_without_metadata(self):
        for _ in range(2):
            self.assertEqual(self.run_game().returncode, 0)
        self.assertEqual((self.home / "downloads").read_text().splitlines(), [self.source["url"]] * 2)
        self.assertEqual((self.home / "helper-ran").read_text(), "game with spaces")
        self.assertFalse((self.home / ".dlor/scripts").exists())

    def test_omitted_sha_downloads_dev_each_time_without_import(self):
        self.assertEqual(self.run_game(pinned=False).returncode, 0)
        self.assertEqual(self.run_game(pinned=False).returncode, 0)
        self.assertEqual(self.run_game().returncode, 0)
        dev_url = self.source["url"].replace(self.source["sha"], "refs/heads/dev")
        self.assertEqual((self.home / "downloads").read_text().splitlines(),
                         [dev_url, dev_url, self.source["url"]])

    def test_repository_override_preserves_fork_source(self):
        self.env["DLOR_REPOSITORY"] = "someone/custom-recipes"
        self.assertEqual(self.run_game().returncode, 0)
        expected = self.source["url"].replace("Wurielle/decky-launch-options-recipes", "someone/custom-recipes")
        self.assertEqual((self.home / "downloads").read_text().strip(), expected)

    def test_invalid_repository_never_downloads(self):
        self.env["DLOR_REPOSITORY"] = "../bad/path"
        self.assertEqual(self.run_game().returncode, 0)
        self.assertFalse((self.home / "downloads").exists())

    def test_unpinned_game_arguments_are_preserved(self):
        args = ["path with spaces", 'with "quotes"', "$literal", "--"]
        command = self.command(pinned=False)
        game_index = command.index("--") + 1
        command[game_index:] = ["python3", "-c",
                               "import json, sys; print(json.dumps(sys.argv[1:]))", *args]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        import json
        self.assertIn(json.dumps(args), result.stdout)

    def test_failed_partial_download_never_executes_but_game_still_runs(self):
        self.env["DOWNLOAD_STATUS"] = "22"
        result = self.run_game()
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.home / "helper-ran").exists())
        logs = list((self.home / ".dlor/logs/run").glob("*.log"))
        self.assertIn("finished with exit status 22", logs[0].read_text())

    def test_empty_download_is_rejected(self):
        self.payload.write_text("")
        result = self.run_game()
        self.assertIn("downloaded script is empty", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_script_failure_and_game_exit_status(self):
        self.payload.write_text('echo "helper failure" >&2\nexit 17\n')
        self.env["GAME_STATUS"] = "42"
        result = self.run_game()
        self.assertEqual(result.returncode, 42)
        self.assertIn("Recipe helper failed (exit 17)", result.stderr)

    def test_invalid_arguments_continue_game(self):
        for source in (
            {**self.source, "recipe": "../../outside"},
            {**self.source, "script": "../update.sh"},
            {**self.source, "script": "update.sh"},
            {**self.source, "sha": "main"},
            {**self.source, "sha": self.source["sha"][:7]},
        ):
            result = self.run_game(source)
            self.assertEqual(result.returncode, 0)
        self.assertFalse((self.home / "downloads").exists())

    def test_log_creation_and_write_failure_do_not_stop_launch(self):
        blocker = self.home / ".dlor/logs"
        blocker.write_text("blocked")
        self.assertEqual(self.run_game().returncode, 0)
        blocker.unlink()
        self.tool("tee", 'exec /usr/bin/tee "$@" /dev/full\n')
        self.assertEqual(self.run_game().returncode, 0)

    def test_concurrent_launches_use_separate_downloads(self):
        self.payload.write_text('sleep 0.1\n')
        processes = [subprocess.Popen(self.command(), env=self.env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0)
        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assertEqual(len((self.home / "downloads").read_text().splitlines()), 2)

    def test_plugin_startup_repairs_launcher(self):
        with patch.object(plugin.decky, "DECKY_USER_HOME", str(self.home)):
            (self.home / ".dlor/run").write_text("old launcher")
            asyncio.run(plugin.Plugin()._main())
            self.assertTrue((self.home / ".dlor/run").read_text().startswith("#!/bin/bash"))
        self.assertEqual(self.run_game().returncode, 0)

    def test_packaged_plugin_installs_runner_without_recipe_sources(self):
        package = self.home / "plugin"
        package.mkdir()
        # Match Decky CLI: defaults/dlor-run.sh becomes dlor-run.sh in the ZIP.
        (package / "dlor-run.sh").write_bytes((ROOT / "defaults/dlor-run.sh").read_bytes())
        with patch.object(plugin, "__file__", str(package / "main.py")), \
                patch.object(plugin.decky, "DECKY_USER_HOME", str(self.home)):
            plugin._install_runner()
        self.assertEqual(self.run_game().returncode, 0)


if __name__ == "__main__":
    unittest.main()
