"""Offline runner/import checks: python3 scripts/test-runner.py (Linux/WSL)."""
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
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

    def command(self, source=None, pinned=True, wrapper=False):
        source = self.source if source is None else source
        return [str(self.home / ".dlor/run"), *(["--wrapper"] if wrapper else []),
                source["recipe"], source["script"],
                *([source["sha"]] if pinned else []), "--",
                "/bin/bash", "-c", 'printf game > "$HOME/game-ran"; exit "${GAME_STATUS:-0}"']

    def run_game(self, source=None, pinned=True, wrapper=False):
        result = subprocess.run(self.command(source, pinned, wrapper), env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual((self.home / "game-ran").read_text(), "game")
        self.assertEqual(list(self.downloads.iterdir()), [])
        return result

    def test_wrapper_preserves_game_boundary_and_exports_validated_revision(self):
        self.env.update(DLOR_RUN_MODE="legacy-value", STEAM_RUNTIME="/steam/runtime",
                        LD_LIBRARY_PATH="/steam/libraries", LD_PRELOAD="/steam/overlay.so",
                        SYSTEM_LD_LIBRARY_PATH="/host/libraries", PYTHONHOME="/steam/python",
                        PYTHONPATH="/steam/modules", GAME_STATUS="42")
        snapshot = '''printf '%s\\0' "${LD_LIBRARY_PATH-unset}" "${LD_PRELOAD-unset}" \\
"${STEAM_RUNTIME-unset}" "${PYTHONHOME-unset}" "${PYTHONPATH-unset}" "$PATH"'''
        self.tool("curl", snapshot + ''' > "$HOME/curl-env"
while [[ "$1" != --output ]]; do shift; done
cat "$HOME/remote.sh" > "$2"
''')
        self.payload.write_text(snapshot + ''' > "$HOME/wrapper-env"
printf '%s\\0' "$@" > "$HOME/wrapper-args"
printf '%s\\0' "$DLOR_SCRIPT_REVISION" "${DLOR_RUN_MODE-unset}" "${mode-unset}" >> "$HOME/wrapper-state"
shopt -s nullglob
downloads=("$TMPDIR"/dlor-script.*.sh)
(( ${#downloads[@]} == 0 )) || exit 93
export SAMPLE_GAME_OVERRIDE='selected override'
exec "$@"
''')
        game = '''printf 'game\\n' >> "$HOME/game-ran"
printf '%s\\0' "$@" "$SAMPLE_GAME_OVERRIDE" > "$HOME/game-args"
IFS= read -r line; printf '%s' "$line" > "$HOME/game-stdin"
IFS= read -r -u "$TEST_FD" line; printf '%s' "$line" > "$HOME/game-fd"
printf 'game stdout\\n'; printf 'game stderr\\n' >&2
exit "$GAME_STATUS"'''
        args = ["", "path with spaces", 'with "quotes"', "$literal", "--", "line\nbreak"]
        command = self.command(wrapper=True)
        game_index = command.index("--") + 1
        game_argv = ["/bin/bash", "-c", game, "--", *args]
        command[game_index:] = game_argv
        fd_path = self.home / "inherited-fd"
        fd_path.write_text("fd payload\n")
        with fd_path.open() as inherited:
            self.env["TEST_FD"] = str(inherited.fileno())
            result = subprocess.run(command, env=self.env, input="stdin payload\n",
                                    pass_fds=(inherited.fileno(),), capture_output=True,
                                    text=True, timeout=15)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual((self.home / "game-ran").read_text(), "game\n")
        self.assertEqual((self.home / "wrapper-args").read_bytes(),
                         b"\0".join(arg.encode() for arg in game_argv) + b"\0")
        self.assertEqual((self.home / "game-args").read_bytes(),
                         b"\0".join(arg.encode() for arg in [*args, "selected override"]) + b"\0")
        expected_env = [self.env[key] for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "STEAM_RUNTIME",
                                                 "PYTHONHOME", "PYTHONPATH", "PATH")]
        self.assertEqual((self.home / "wrapper-env").read_bytes(),
                         b"\0".join(value.encode() for value in expected_env) + b"\0")
        clean_env = ["/host/libraries", "unset", "unset", "unset", "unset", self.env["SYSTEM_PATH"]]
        self.assertEqual((self.home / "curl-env").read_bytes(),
                         b"\0".join(value.encode() for value in clean_env) + b"\0")
        self.assertEqual((self.home / "wrapper-state").read_bytes(),
                         (self.source["sha"] + "\0legacy-value\0unset\0").encode())
        self.assertEqual((self.home / "game-stdin").read_text(), "stdin payload")
        self.assertEqual((self.home / "game-fd").read_text(), "fd payload")
        self.assertIn("game stdout", result.stdout)
        self.assertNotIn("game stdout", "".join(p.read_text() for p in (self.home / ".dlor/logs/run").glob("*.log")))
        self.assertIn("game stderr", result.stderr)
        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assertFalse((self.home / ".dlor/scripts").exists())

    def test_environment_cannot_select_wrapper_mode(self):
        self.env["DLOR_RUN_MODE"] = "wrapper"
        result = self.run_game()
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.home / "helper-ran").read_text(), "game with spaces")

    def test_wrapper_requires_full_pinned_revision(self):
        result = subprocess.run(self.command(pinned=False, wrapper=True), env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertFalse((self.home / "downloads").exists())
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.home / "game-ran").read_text(), "game")
        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assertFalse((self.home / "helper-ran").exists())
        self.assertIn("wrapper requires a full commit SHA", result.stdout)

    def test_wrapper_temp_allocation_failure_cleans_its_partial_file(self):
        self.env["DLOR_RUN_MODE"] = "wrapper"
        self.tool("mktemp", '''
file="$TMPDIR/dlor-script.partial.sh"
printf 'partial' > "$file"
printf '%s\\n' "$file"
exit 1
''')
        result = self.run_game(wrapper=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.home / "downloads").exists())
        self.assertIn("could not allocate wrapper download", result.stderr)

    def test_wrapper_parent_cancellation_during_download_cleans_only_its_temp(self):
        self.env.update(STEAM_RUNTIME="/steam/runtime", LD_LIBRARY_PATH="/steam/libraries",
                        SYSTEM_LD_LIBRARY_PATH="/host/libraries", PYTHONHOME="/steam/python",
                        PYTHONPATH="/steam/modules", LD_PRELOAD="/steam/overlay.so")
        self.payload.write_text('printf wrapper > "$HOME/wrapper-ran"\nexec "$@"\n')
        self.tool("curl", '''
while [[ "$1" != --output ]]; do shift; done
cat "$HOME/remote.sh" > "$2"
printf ready > "$HOME/download-ready"
sleep 0.5
printf complete > "$HOME/download-complete"
''')
        self.tool("rm", '''
printf '%s\\0' "${LD_PRELOAD-unset}" "${STEAM_RUNTIME-unset}" "$LD_LIBRARY_PATH" \\
"${PYTHONHOME-unset}" "${PYTHONPATH-unset}" "$PATH" > "$HOME/cleanup-env"
exec /bin/rm "$@"
''')
        unrelated = self.downloads / "dlor-script.other-launch.sh"
        unrelated.write_text("another launch owns this")
        for cancellation in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=cancellation.name):
                for path in set(self.downloads.iterdir()) - {unrelated}:
                    path.unlink()
                for marker in ("download-ready", "download-complete", "cleanup-env"):
                    (self.home / marker).unlink(missing_ok=True)
                process = subprocess.Popen(self.command(wrapper=True), env=self.env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 5
                    while not (self.home / "download-ready").exists():
                        self.assertIsNone(process.poll(), "runner exited before download")
                        self.assertLess(time.monotonic(), deadline, "download did not start")
                        time.sleep(0.01)
                    private_downloads = set(self.downloads.iterdir()) - {unrelated}
                    self.assertEqual(len(private_downloads), 1)
                    process.send_signal(cancellation)  # Parent PID only, not its download child.
                    stdout, stderr = process.communicate(timeout=10)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=10)
                self.assertEqual((self.home / "download-complete").read_text(), "complete")
                self.assertEqual(set(self.downloads.iterdir()), {unrelated}, stdout + stderr)
                self.assertEqual(process.returncode, 128 + cancellation, stdout + stderr)
                self.assertEqual(unrelated.read_text(), "another launch owns this")
                self.assertFalse((self.home / "wrapper-ran").exists())
                self.assertFalse((self.home / "game-ran").exists())
                self.assertEqual((self.home / "cleanup-env").read_bytes(),
                                 b"unset\0unset\0/host/libraries\0unset\0unset\0"
                                 + self.env["SYSTEM_PATH"].encode() + b"\0")

    def test_default_helper_keeps_existing_python_environment(self):
        self.env.update(PYTHONHOME="/steam/python", PYTHONPATH="/steam/modules")
        self.payload.write_text('printf "%s\\0" "$PYTHONHOME" "$PYTHONPATH" > "$HOME/helper-env"\n')
        self.assertEqual(self.run_game().returncode, 0)
        self.assertEqual((self.home / "helper-env").read_bytes(), b"/steam/python\0/steam/modules\0")

    def wrapper_fallback(self):
        self.env.update(DLOR_RUN_MODE="wrapper", STEAM_RUNTIME="/steam/runtime",
                        LD_LIBRARY_PATH="/steam/libraries", PYTHONHOME="/steam/python",
                        DLOR_SCRIPT_REVISION="original-revision")
        command = self.command(wrapper=True)
        command[command.index("--") + 1:] = ["/bin/bash", "-c", '''
printf 'game\\n' >> "$HOME/game-ran"
printf '%s\\0' "$@" "$LD_LIBRARY_PATH" "$STEAM_RUNTIME" "$PYTHONHOME" \\
"$DLOR_RUN_MODE" "$DLOR_SCRIPT_REVISION" "${SAMPLE_GAME_OVERRIDE-unset}" > "$HOME/fallback-state"
exit 42
''', "--", "", "argument with spaces", "$literal"]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual((self.home / "game-ran").read_text(), "game\n")
        self.assertEqual((self.home / "fallback-state").read_bytes(),
                         b"\0argument with spaces\0$literal\0/steam/libraries\0/steam/runtime\0"
                         b"/steam/python\0wrapper\0original-revision\0unset\0")
        self.assertFalse((self.home / "wrapper-ran").exists())
        self.assertEqual(list(self.downloads.iterdir()), [])
        return result

    def test_wrapper_partial_download_falls_back_once_unchanged(self):
        self.env["DOWNLOAD_STATUS"] = "22"
        self.payload.write_text('printf wrapper > "$HOME/wrapper-ran"\n'
                                'export SAMPLE_GAME_OVERRIDE=changed\nexec "$@"\n')
        result = self.wrapper_fallback()
        self.assertIn("exit 22", result.stderr)

    def test_wrapper_empty_download_falls_back_once_unchanged(self):
        self.payload.write_text("")
        result = self.wrapper_fallback()
        self.assertIn("downloaded script is empty", result.stdout)

    def test_wrapper_empty_body_after_builtin_read_falls_back_once(self):
        self.payload.write_text("\n\n")
        result = self.wrapper_fallback()
        self.assertIn("wrapper unavailable", result.stderr)

    def test_wrapper_read_failure_cleans_download_and_falls_back_once(self):
        self.tool("curl", '''
while [[ "$1" != --output ]]; do shift; done
cat "$HOME/remote.sh" > "$2"
chmod 000 "$2"
''')
        result = self.wrapper_fallback()
        self.assertIn("Permission denied", result.stderr)

    def test_wrapper_invalid_revision_never_downloads(self):
        self.source["sha"] = "main"
        self.wrapper_fallback()
        self.assertFalse((self.home / "downloads").exists())

    def test_wrapper_exit_is_not_retried_as_a_game_launch(self):
        self.env["DLOR_RUN_MODE"] = "wrapper"
        self.payload.write_text('printf wrapper >> "$HOME/wrapper-ran"\nexit 17\n')
        result = subprocess.run(self.command(wrapper=True), env=self.env, capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual((self.home / "wrapper-ran").read_text(), "wrapper")
        self.assertFalse((self.home / "game-ran").exists())
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_wrapper_can_invoke_nested_default_helper_once(self):
        self.env["DLOR_RUN_MODE"] = "wrapper"
        self.payload.write_text('''
if [[ "$1" == "$STEAM_COMPAT_INSTALL_PATH" ]]; then
    printf helper >> "$HOME/helper-ran"
    exit 0
fi
printf wrapper >> "$HOME/wrapper-ran"
exec "$HOME/.dlor/run" optiscaler update-nightly "$DLOR_SCRIPT_REVISION" -- "$@"
''')
        self.assertEqual(self.run_game(wrapper=True).returncode, 0)
        self.assertEqual((self.home / "wrapper-ran").read_text(), "wrapper")
        self.assertEqual((self.home / "helper-ran").read_text(), "helper")
        self.assertEqual((self.home / "downloads").read_text().splitlines(), [self.source["url"]] * 2)

    def test_normal_helper_then_wrapper_modes_are_invocation_scoped(self):
        self.env["DLOR_RUN_MODE"] = "wrapper"
        self.payload.write_text('''
if [[ "$1" == "$STEAM_COMPAT_INSTALL_PATH" ]]; then
    printf 'helper\\n' >> "$HOME/execution-order"
    exit 0
fi
printf 'wrapper\\n' >> "$HOME/execution-order"
exec "$@"
''')
        wrapper = self.command(wrapper=True)
        wrapper[wrapper.index("--") + 1:] = ["/bin/bash", "-c", '''
printf 'game\\n' >> "$HOME/execution-order"
exit 42
''']
        command = self.command()
        command[command.index("--") + 1:] = wrapper
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual((self.home / "execution-order").read_text(), "helper\nwrapper\ngame\n")
        self.assertEqual((self.home / "downloads").read_text().splitlines(), [self.source["url"]] * 2)
        self.assertEqual(list(self.downloads.iterdir()), [])

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
