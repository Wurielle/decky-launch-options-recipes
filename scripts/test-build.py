"""Offline build wrapper checks: python3 scripts/test-build.py."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="decky-build-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project with spaces"
        (self.root / ".vscode").mkdir(parents=True)
        shutil.copy2(ROOT / ".vscode/build.sh", self.root / ".vscode/build.sh")
        shutil.copy2(ROOT / ".gitignore", self.root / ".gitignore")
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        (self.root / "main.py").write_text("uncommitted backend")
        (self.root / "src").mkdir()
        (self.root / "src/logs.tsx").write_text("untracked log browser")
        for name in ("node_modules", ".pnpm-store", "dist", "out"):
            (self.root / name).mkdir()
            (self.root / name / "old").write_text("old build data")
        (self.root / ".env.local").write_text("DECK_PASS=fixture-only\n")
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.tmp = Path(self.temp.name) / "tmp"
        self.tmp.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        TMPDIR=str(self.tmp), BUILD_TEST_ROOT=str(self.root))
        self.tool(self.bin / "docker", "#!/bin/sh\nexit 1\n")
        self.tool(self.bin / "podman", "#!/bin/sh\nprintf 'true\\n'\n")
        (self.root / "cli").mkdir()
        self.tool(self.root / "cli/decky", '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["BUILD_TEST_ROOT"])
args = sys.argv[1:]
source = pathlib.Path(args[-1])
assert source != root
assert (source / "main.py").read_text() == "uncommitted backend"
assert (source / "src/logs.tsx").read_text() == "untracked log browser"
for name in ("node_modules", ".pnpm-store", "dist", "out", ".env.local", ".git", "cli"):
    assert not (source / name).exists(), name
(root / "invocation.json").write_text(json.dumps(args))
if os.environ.get("BUILD_TEST_FAIL"):
    sys.exit(17)
output = pathlib.Path(args[args.index("--output-path") + 1])
output.mkdir()
(output / "Launch Options Recipes.zip").write_bytes(b"new archive")
''')

    def tool(self, path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_build(self):
        return subprocess.run(["bash", str(self.root / ".vscode/build.sh")],
                              cwd=self.temp.name, env=self.env, capture_output=True,
                              text=True, timeout=15)

    def test_rootless_build_stages_current_source_and_publishes_archive(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = json.loads((self.root / "invocation.json").read_text())
        self.assertEqual(args[args.index("--engine") + 1], "podman")
        self.assertIn("--build-as-root", args)
        self.assertEqual((self.root / "out/Launch Options Recipes.zip").read_bytes(), b"new archive")
        self.assertEqual((self.root / "dist/old").read_text(), "old build data")
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_failed_build_preserves_output_and_cleans_staging(self):
        self.env["BUILD_TEST_FAIL"] = "1"
        result = self.run_build()
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertEqual((self.root / "out/old").read_text(), "old build data")
        self.assertFalse((self.root / "out/Launch Options Recipes.zip").exists())
        self.assertEqual(list(self.tmp.iterdir()), [])

    @unittest.skipIf(os.geteuid() == 0, "Requires an unprivileged user")
    def test_unwritable_output_is_preserved_and_replaced(self):
        (self.root / "out").chmod(0o555)
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        backups = list(self.root.glob(".out-backup.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "old").read_text(), "old build data")
        self.assertTrue(os.access(self.root / "out", os.W_OK))
        ignored = subprocess.run(["git", "check-ignore", str(backups[0])],
                                 cwd=self.root, capture_output=True)
        self.assertEqual(ignored.returncode, 0)

    def test_available_docker_does_not_build_as_root(self):
        self.tool(self.bin / "docker", "#!/bin/sh\nexit 0\n")
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = json.loads((self.root / "invocation.json").read_text())
        self.assertEqual(args[args.index("--engine") + 1], "docker")
        self.assertNotIn("--build-as-root", args)


if __name__ == "__main__":
    unittest.main()
