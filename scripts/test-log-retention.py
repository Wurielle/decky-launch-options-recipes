"""Offline retention checks: python3 scripts/test-log-retention.py."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "run": ROOT / "defaults/dlor-run.sh",
    "optiscaler/update-nightly": ROOT / "recipes/optiscaler/scripts/update-nightly.sh",
    "reframework/update": ROOT / "recipes/reframework/scripts/update.sh",
    "reframework/uninstall": ROOT / "recipes/reframework/scripts/uninstall.sh",
}


class LogRetentionTests(unittest.TestCase):
    def run_script(self, folder, home, **environment):
        env = dict(os.environ, HOME=str(home), **environment)
        env["SYSTEM_PATH"] = env["PATH"]
        if folder == "run":
            # Invalid recipe skips network access and still launches the game.
            args = ["../invalid", "script", "--", "bash", "-c", "echo game-ran"]
        else:
            args = ["--help"]
        result = subprocess.run(["bash", "-s", "--", *args],
                                input=SCRIPTS[folder].read_text(), env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("game-ran" if folder == "run" else "Usage:", result.stdout)
        return result

    def seed_logs(self, directory, count):
        directory.mkdir(parents=True)
        logs = []
        for index in range(count):
            path = directory / f"2000-01-01T00-00-{index:02d}.000000.log"
            path.write_text(f"old log {index}")
            # Recent writes to an old log must not change creation order.
            os.utime(path, (2000000000 - index, 2000000000 - index))
            logs.append(path)
        return logs

    def test_keeps_newest_ten_and_preserves_unrelated_files(self):
        for folder in SCRIPTS:
            for count in (0, 8, 9, 10, 15):
                with self.subTest(folder=folder, existing=count), \
                        tempfile.TemporaryDirectory(prefix="log retention ") as temp:
                    home = Path(temp)
                    directory = home / ".dlor/logs" / folder
                    old = self.seed_logs(directory, count)
                    unrelated = directory / "notes.txt"
                    unrelated.write_text("keep")
                    nested = directory / "000-directory.log"
                    nested.mkdir()
                    nested_log = nested / "nested.log"
                    nested_log.write_text("keep")
                    symlink = directory / "000-link.log"
                    symlink.symlink_to(unrelated)
                    other = home / ".dlor/logs/other-script"
                    other_logs = self.seed_logs(other, 12)

                    self.run_script(folder, home)

                    logs = sorted(p for p in directory.glob("*.log")
                                  if p.is_file() and not p.is_symlink())
                    self.assertEqual(len(logs), min(count + 1, 10))
                    self.assertEqual(logs[:-1], old[-9:])
                    self.assertIn("finished with exit status", logs[-1].read_text())
                    self.assertEqual(unrelated.read_text(), "keep")
                    self.assertEqual(nested_log.read_text(), "keep")
                    self.assertTrue(symlink.is_symlink())
                    self.assertEqual(sorted(other.glob("*.log")), other_logs)

    def test_cleanup_failure_warns_and_continues(self):
        for folder in SCRIPTS:
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                directory = home / ".dlor/logs" / folder
                self.seed_logs(directory, 10)
                bin_dir = home / "bin"
                bin_dir.mkdir()
                rm = bin_dir / "rm"
                rm.write_text("#!/bin/bash\necho 'deletion failed' >&2\nexit 1\n")
                rm.chmod(0o755)

                result = self.run_script(folder, home, PATH=f"{bin_dir}:{os.environ['PATH']}")

                self.assertIn("could not remove old logs", result.stdout)
                logs = sorted(directory.glob("*.log"))
                self.assertEqual(len(logs), 11)
                self.assertIn("could not remove old logs", logs[-1].read_text())
                self.assertIn("finished with exit status", logs[-1].read_text())


if __name__ == "__main__":
    unittest.main()
