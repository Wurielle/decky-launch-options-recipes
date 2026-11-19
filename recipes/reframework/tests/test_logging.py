"""Offline logging checks: python3 -I -B -m unittest discover -s recipes/reframework/tests -v."""

from pathlib import Path
import runpy
import unittest


RECIPE = Path(__file__).resolve().parents[1]
ROOT = RECIPE.parents[1]
ScriptLoggingFixture = runpy.run_path(str(ROOT / "scripts/script_logging_test_support.py"))["ScriptLoggingFixture"]


class REFrameworkLoggingTests(ScriptLoggingFixture):
    script_sources = {
        "reframework-update": RECIPE / "scripts/update.sh",
        "reframework-uninstall": RECIPE / "scripts/uninstall.sh",
    }
    launch_cases = [
        ("reframework-update", "reframework-install-update", "Installed:"),
        ("reframework-uninstall", "reframework-uninstall", "Uninstalled:"),
    ]
    option_ids = [case[1] for case in launch_cases]

    def setUp(self):
        super().setUp()
        (self.game / "dinput8.dll").write_text("original")
        self.env["REFRAMEWORK_CACHE_DIR"] = str(self.root / "reframework-cache")

    def test_help_logs_stdout_and_uses_separate_timestamped_files(self):
        self.check_help_logging()

    def test_validation_errors_are_logged_when_piped_into_bash(self):
        self.check_validation_logging()

    def test_logging_setup_failure_does_not_stop_scripts(self):
        self.check_logging_setup_failure()

    def test_log_write_failure_does_not_stop_output_or_commands(self):
        self.check_log_write_failure()

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

    def test_runner_survives_decky_launch_options_token_classification(self):
        self.check_runner_token_classification()

    def prepare_direct_run(self, name):
        if name == "reframework-uninstall":
            (self.game / "dinput8.dll").write_text("original")

    def test_host_tools_escape_steam_libraries_but_game_keeps_its_environment(self):
        self.check_host_tools_environment('''
if [[ -n "${LD_LIBRARY_PATH:-}" || -n "${LD_PRELOAD:-}" ]]; then
    echo "curl: Steam libcurl does not provide CURL_OPENSSL_4" >&2
    exit 1
fi
if [[ "$*" == *raw.githubusercontent.com* ]]; then
    while [[ "$1" != --output && "$1" != -o ]]; do shift; done
    cat "$TEST_RECIPE_SCRIPT" > "$2"
elif [[ "$*" == *url_effective* ]]; then
    printf 'https://github.com/praydog/REFramework-nightly/releases/tag/test'
else
    echo 'unexpected artifact download' >&2
    exit 22
fi''', ["reframework-cache/test/dinput8.dll"])

    def test_launch_wrappers_continue_after_real_script_failures(self):
        self.check_launch_failure_continuation()


if __name__ == "__main__":
    unittest.main()
