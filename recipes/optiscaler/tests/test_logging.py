"""Offline logging checks: python3 -I -B -m unittest discover -s recipes/optiscaler/tests -v."""

from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import unittest


RECIPE = Path(__file__).resolve().parents[1]
ROOT = RECIPE.parents[1]
ScriptLoggingFixture = runpy.run_path(str(ROOT / "scripts/script_logging_test_support.py"))["ScriptLoggingFixture"]


class OptiScalerLoggingTests(ScriptLoggingFixture):
    script_sources = {"optiscaler-update-nightly": RECIPE / "scripts/update-nightly.sh"}
    launch_cases = [("optiscaler-update-nightly", "optiscaler-nightly-upgrade", "Upgraded:")]
    option_ids = [case[1] for case in launch_cases]

    def setUp(self):
        super().setUp()
        (self.game / "OptiScaler.ini").write_text("user config")
        (self.game / "dxgi.dll").write_text("original")
        self.env["OPTISCALER_CACHE_DIR"] = str(self.root / "optiscaler-cache")

    def verified_nightly_logging_fixture(self):
        # Isolate host cleanup/logging from binary acquisition while retaining
        # the real manifest -> loader -> verified-module trust chain.
        runtime = self.root / "recipes/dlor-optiscaler/scripts"
        runtime.mkdir(parents=True)
        source = ROOT / "recipes/dlor-optiscaler/scripts"
        for name in ("loader.py", "artifacts.py", "game_discovery.py",
                     "update_optiscaler_config.py", "nightly.py", "downloads.json",
                     "update-source-hashes.py"):
            shutil.copyfile(source / name, runtime / name)
        (runtime / "installer.py").write_text('''import os

def main(argv=None):
    assert not os.environ.get('LD_PRELOAD'), 'host module inherited preload'
    assert not os.environ.get('LD_LIBRARY_PATH'), 'host module inherited Steam libraries'
    assert not os.environ.get('STEAM_RUNTIME', '').startswith('/'), 'host module inherited Steam runtime'
    print('Upgraded: synthetic logging fixture')
    return 0
''')
        entry = self.root / "recipes/optiscaler/scripts"
        entry.mkdir(parents=True)
        subprocess.run([sys.executable, "-I", "-B", str(runtime / "update-source-hashes.py")],
                       capture_output=True, text=True, check=True)
        self.scripts["optiscaler-update-nightly"].write_bytes((entry / "update-nightly.sh").read_bytes())
        self.env.update(TEST_NIGHTLY_RUNTIME=str(runtime), DLOR_SCRIPT_REVISION="a" * 40)

    def test_help_logs_stdout_and_uses_separate_timestamped_files(self):
        self.check_help_logging()

    def test_validation_errors_are_logged_when_piped_into_bash(self):
        self.check_validation_logging()

    def test_logging_setup_failure_does_not_stop_scripts(self):
        self.check_logging_setup_failure()

    def test_log_write_failure_does_not_stop_output_or_commands(self):
        self.check_log_write_failure()

    def test_runner_survives_decky_launch_options_token_classification(self):
        self.check_runner_token_classification()

    def test_host_tools_escape_steam_libraries_but_game_keeps_its_environment(self):
        self.verified_nightly_logging_fixture()
        self.check_host_tools_environment('''
if [[ -n "${LD_LIBRARY_PATH:-}" || -n "${LD_PRELOAD:-}" ]]; then
    echo "curl: Steam libcurl does not provide CURL_OPENSSL_4" >&2
    exit 1
fi
if [[ "$*" == *raw.githubusercontent.com* ]]; then
    url="${@: -1}"
    while [[ "$1" != --output && "$1" != -o ]]; do shift; done
    name="${url##*/}"
    if [[ "$url" == */recipes/dlor-optiscaler/scripts/* && -f "$TEST_NIGHTLY_RUNTIME/$name" ]]; then
        cat "$TEST_NIGHTLY_RUNTIME/$name" > "$2"
    else
        cat "$TEST_RECIPE_SCRIPT" > "$2"
    fi
else
    printf '%s' '[{"draft":false,"tag_name":"test","assets":[{"name":"OptiScaler_test.7z"}]}]'
fi''', ["optiscaler-cache/test/files/OptiScaler.dll"])

    def test_launch_wrappers_continue_after_real_script_failures(self):
        self.check_launch_failure_continuation("/recipes/dlor-optiscaler/scripts/")


if __name__ == "__main__":
    unittest.main()
