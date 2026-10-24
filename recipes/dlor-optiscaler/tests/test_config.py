"""Pure selector and literal-byte tests for the user's Framegen updater port."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("environment_updater", SCRIPTS / "update_optiscaler_config.py")
assert spec is not None and spec.loader is not None
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class ConfigTests(unittest.TestCase):
    def test_three_formats_normalization_priority_and_case(self):
        data = b"[V-Sync]\nMode=auto\nUnique=old\nPath=old\nPATH=old\n[Other]\nMode=other\n"
        env = {"Mode": "ambiguous", "Unique": "bare", "VSync_Unique": "section", "OptiScaler_VSync_Unique": "full", "VSync_Mode": "section", "OptiScaler_VSync_Path": "mixed", "PATH": "caps", "Unknown": "ignored", "OptiScaler_Other_Unknown": "ignored"}
        self.assertEqual(updater.resolve_overrides(data, env), {("V-Sync", "Unique"): "full", ("V-Sync", "Mode"): "section", ("V-Sync", "Path"): "mixed", ("V-Sync", "PATH"): "caps"})
        self.assertEqual(updater.resolve_overrides(data, dict(reversed(list(env.items())))), updater.resolve_overrides(data, env))
        self.assertEqual(updater.resolve_overrides(data, {"Unique": "bare"}), {("V-Sync", "Unique"): "bare"})

    def test_ambiguous_normalized_sections_are_refused(self):
        with self.assertRaisesRegex(ValueError, "[Aa]mbiguous"):
            updater.resolve_overrides(b"[V-Sync]\nKey=a\n[VSync]\nKey=b\n", {"VSync_Key": "new"})

    def test_literals_injection_and_noop(self):
        data = b"\xef\xbb\xbf; keep\r\n[User]\r\n  Key = old ; annotation\r\nLast=no-newline"
        value = r"Z:\folder\1\g<1> $HOME 50% ; literal # text"
        result = updater.render_overrides(data, {("User", "Key"): value})
        self.assertEqual(result, data.replace(b" old ; annotation", value.encode()))
        self.assertEqual(updater.render_overrides(data, {}), data)
        self.assertEqual(updater.resolve_overrides(data, {"Other": "unrelated-secret"}), {})
        for bad in ("one\ntwo", "one\rtwo", "one\0two"):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                updater.resolve_overrides(data, {"Key": bad})

    def test_standalone_interface_preserves_mode_noop_and_never_logs_values(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            ini = Path(directory) / "OptiScaler.ini"
            original = b"\xef\xbb\xbf[User]\r\nKey=old\r\n"
            ini.write_bytes(original)
            ini.chmod(0o640)
            with patch.dict(os.environ, {}, clear=True):
                updater.update_optiscaler_config(ini)
            self.assertEqual(ini.read_bytes(), original)
            output = io.StringIO()
            with patch.dict(os.environ, {"Key": "secret-value"}, clear=True), contextlib.redirect_stdout(output):
                updater.update_optiscaler_config(ini)
            self.assertEqual(ini.read_bytes(), original.replace(b"Key=old", b"Key=secret-value"))
            self.assertEqual(ini.stat().st_mode & 0o7777, 0o640)
            self.assertNotIn("secret-value", output.getvalue())
