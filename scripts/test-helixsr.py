"""Offline configuration checks: python3 scripts/test-helixsr.py."""
import os
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from runner_test_support import install_runner

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "recipes/helixsr/scripts/configure.sh"
ORIGINAL = "[Upscalers]\nDx12Upscaler=dlss\n\n[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n\n[Other]\nKeep=true\n"

# Execute the actual embedded Python with real filesystem operations. Only the
# syscall boundaries are wrapped to observe durability or terminate the process.
INSTRUMENTED_CONFIGURATOR = r'''
import json
import os
from pathlib import Path
import stat
import sys

script, game, ini, trace, interruption = sys.argv[1:]
ini = Path(ini)
original_replace, original_fsync = os.replace, os.fsync
original_unlink, original_mkdir = os.unlink, os.mkdir
ini_replaced = False

def record(*event):
    with open(trace, "a") as stream:
        stream.write(json.dumps(event) + "\n")

def checkpoint(point):
    if point == interruption:
        os._exit(79)

def replace(source, destination):
    global ini_replaced
    if Path(destination) == ini:
        checkpoint("before_ini_replace")
    original_replace(source, destination)
    record("replace", str(source), str(destination))
    if Path(destination) == ini:
        ini_replaced = True
        checkpoint("after_ini_replace")

def fsync(fd):
    path = os.readlink(f"/proc/self/fd/{fd}")
    directory = stat.S_ISDIR(os.fstat(fd).st_mode)
    original_fsync(fd)
    record("fsync", path, directory)
    if directory and Path(path) == ini.parent and ini_replaced:
        checkpoint("after_ini_sync")

def unlink(path, *args, **kwargs):
    original_unlink(path, *args, **kwargs)
    record("unlink", str(path))

def mkdir(path, *args, **kwargs):
    original_mkdir(path, *args, **kwargs)
    record("mkdir", str(path))

os.replace, os.fsync = replace, fsync
os.unlink, os.mkdir = unlink, mkdir
body = Path(script).read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
sys.argv = [script, game]
exec(compile(body, script + ":embedded", "exec"), {"__name__": "__main__"})
'''


class HelixSRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlor helixsr ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.source = self.home / ".local/share/helixsr/fsr3-drop-in"
        self.source.mkdir(parents=True)
        # Explicit offline fixtures, not usable HelixSR binaries.
        for name in ("amd_fidelityfx_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll"):
            (self.source / name).write_bytes(b"MZ offline fixture")
        self.game = self.home / "game/Binaries/Win64"
        self.game.mkdir(parents=True)
        self.ini = self.game / "OptiScaler.ini"
        self.ini.write_text(ORIGINAL)
        self.compat = self.home / "compatdata/123"
        (self.compat / "pfx/dosdevices").mkdir(parents=True)
        (self.compat / "pfx/dosdevices/z:").symlink_to("/")
        self.env = dict(os.environ, HOME=str(self.home), STEAM_COMPAT_DATA_PATH=str(self.compat))
        for key in ("HELIXSR_DIR", "HELIXSR_CONFIG", "WINEPREFIX"):
            self.env.pop(key, None)

    def configure(self, action="on", expected=0):
        result = subprocess.run(["bash", str(SCRIPT), str(self.home / "game")],
                                env=dict(self.env, DLOR_HELIXSR_ACTION=action),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def instrumented_configure(self, action="on", interruption="", expected=0):
        trace = self.home / "syscalls.jsonl"
        trace.write_text("")
        result = subprocess.run([sys.executable, "-c", INSTRUMENTED_CONFIGURATOR,
                                 str(SCRIPT), str(self.home / "game"), str(self.ini),
                                 str(trace), interruption],
                                env=dict(self.env, DLOR_HELIXSR_ACTION=action),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return [json.loads(line) for line in trace.read_text().splitlines()]

    def test_state_and_ini_mutations_fsync_parent_directories_in_order(self):
        events = self.instrumented_configure()
        state_path, = (self.home / ".dlor/state/helixsr").glob("*.json")
        replacements = [event[2] for event in events if event[0] == "replace"]
        self.assertEqual(replacements, [str(state_path), str(self.ini), str(state_path)])
        directories = [self.home / ".dlor", self.home / ".dlor/state", state_path.parent]
        self.assertEqual([event[1] for event in events if event[0] == "mkdir"],
                         [str(path) for path in directories])
        for index, event in enumerate(events):
            with self.subTest(action="on", event=event):
                if event[0] == "mkdir":
                    self.assertEqual(events[index + 1:index + 2],
                                     [["fsync", str(Path(event[1]).parent), True]])
                elif event[0] == "replace":
                    self.assertEqual(events[index - 1], ["fsync", event[1], False])
                    self.assertEqual(events[index + 1:index + 2],
                                     [["fsync", str(Path(event[2]).parent), True]])
        # The durable journal precedes the INI, and only new values remain after commit.
        self.assertTrue(all("previous_values" not in item
                            for item in json.loads(state_path.read_text())["settings"]))
        events = self.instrumented_configure("off")
        mutations = [event for event in events if event[0] in ("replace", "unlink")]
        self.assertEqual([event[-1] for event in mutations], [str(self.ini), str(state_path)])
        for index, event in enumerate(events):
            if event[0] in ("replace", "unlink"):
                with self.subTest(action="off", event=event):
                    self.assertEqual(events[index + 1:index + 2],
                                     [["fsync", str(Path(event[-1]).parent), True]])
        self.assertEqual(self.ini.read_text(), ORIGINAL)

    def check_activation_interruptions(self, repeated):
        custom = self.home / "pending HelixSR/fsr3-drop-in"
        custom.mkdir(parents=True)
        for library in self.source.iterdir():
            (custom / library.name).write_bytes(library.read_bytes())
        for point in ("before_ini_replace", "after_ini_replace", "after_ini_sync"):
            for recovery in ("off", "retry"):
                with self.subTest(point=point, recovery=recovery):
                    self.env.pop("HELIXSR_DIR", None)
                    if repeated:
                        self.configure()
                    before = self.ini.read_bytes()
                    self.env["HELIXSR_DIR"] = str(custom.parent)
                    self.instrumented_configure(interruption=point, expected=79)
                    state_path, = (self.home / ".dlor/state/helixsr").glob("*.json")
                    if point == "before_ini_replace":
                        self.assertEqual(self.ini.read_bytes(), before)
                    else:
                        self.assertIn("FfxDx12Path=Z:" + str(custom / "amd_fidelityfx_dx12.dll"),
                                      self.ini.read_text())
                    if recovery == "retry":
                        self.configure()
                        self.assertTrue(all("previous_values" not in item
                                            for item in json.loads(state_path.read_text())["settings"]))
                    self.configure("off")
                    self.assertEqual(self.ini.read_text(), ORIGINAL)
                    self.assertFalse(state_path.exists())

    def test_interrupted_initial_activation_can_restore_or_retry(self):
        self.check_activation_interruptions(repeated=False)

    def test_interrupted_changed_source_reactivation_can_restore_or_retry(self):
        self.check_activation_interruptions(repeated=True)

    def test_activation_uses_locally_prepared_libraries(self):
        self.configure()
        text = self.ini.read_text()
        self.assertIn("Dx12Upscaler=fsr31", text)
        self.assertIn("FfxDx12Path=Z:" + str(self.source / "amd_fidelityfx_dx12.dll"), text)
        self.assertIn("FfxDx12SRPath=Z:" + str(self.source / "amd_fidelityfx_upscaler_dx12.dll"), text)
        self.assertIn("Keep=true", text)
        self.assertEqual(len(list((self.home / ".dlor/logs/helixsr/configure").glob("*.log"))), 1)


    def test_provider_index_is_reset_and_restored(self):
        self.ini.write_text(ORIGINAL + "\n[FSR]\nUpscalerIndex=7\n")
        self.configure()
        self.assertIn("UpscalerIndex=0", self.ini.read_text())
        self.configure("off")
        self.assertEqual(self.ini.read_text(), ORIGINAL + "\n[FSR]\nUpscalerIndex=7\n")


    def test_disable_restores_original_keys_and_keeps_other_changes(self):
        self.configure()
        self.configure()
        self.ini.write_text(self.ini.read_text().replace("Keep=true", "Keep=edited"))
        self.configure("off")
        self.assertEqual(self.ini.read_text(), ORIGINAL.replace("Keep=true", "Keep=edited"))
        self.configure("off")

    @unittest.skipIf(os.geteuid() == 0, "root bypasses directory write permissions")
    def test_failed_reactivation_with_changed_source_can_restore_original(self):
        self.configure()
        activated = self.ini.read_bytes()
        custom = self.home / "second HelixSR"
        self.source.parent.rename(custom)
        self.env["HELIXSR_DIR"] = str(custom)
        self.game.chmod(0o555)
        try:
            result = self.configure(expected=1)
            self.assertIn("Permission denied", result.stdout + result.stderr)
            self.assertEqual(self.ini.read_bytes(), activated)
            self.assertEqual(len(list((self.home / ".dlor/state/helixsr").glob("*.json"))), 1)
        finally:
            self.game.chmod(0o755)
        self.configure("off")
        self.assertEqual(self.ini.read_text(), ORIGINAL)
        self.assertEqual(list((self.home / ".dlor/state/helixsr").glob("*.json")), [])

    def test_disable_preserves_deleted_owned_key(self):
        self.configure()
        self.ini.write_text("".join(line for line in self.ini.read_text().splitlines(keepends=True)
                                     if not line.startswith("FfxDx12SRPath=")))
        self.configure("off")
        self.assertIn("Dx12Upscaler=dlss", self.ini.read_text())
        self.assertNotIn("FfxDx12SRPath=", self.ini.read_text())

    def test_disable_preserves_user_replacement(self):
        self.configure()
        self.ini.write_text(self.ini.read_text().replace("Dx12Upscaler=fsr31", "Dx12Upscaler=xess"))
        self.configure("off")
        self.assertIn("Dx12Upscaler=xess", self.ini.read_text())
        self.assertIn("FfxDx12Path=auto", self.ini.read_text())


    def test_missing_dll_does_not_touch_configuration(self):
        (self.source / "amd_fidelityfx_upscaler_dx12.dll").unlink()
        result = self.configure(expected=1)
        self.assertIn("Missing prepared HelixSR DLL", result.stdout + result.stderr)
        self.assertEqual(self.ini.read_text(), ORIGINAL)
        self.assertEqual(list((self.home / ".dlor/state/helixsr").glob("*.json")), [])

    def test_disable_needs_neither_dlls_nor_prefix(self):
        self.configure()
        for path in self.source.iterdir():
            path.unlink()
        self.env.pop("STEAM_COMPAT_DATA_PATH")
        self.configure("off")
        self.assertEqual(self.ini.read_text(), ORIGINAL)

    def test_custom_source_and_mapped_drive(self):
        custom = self.home / "custom HelixSR"
        self.source.parent.rename(custom)
        self.env["HELIXSR_DIR"] = str(custom)
        (self.compat / "pfx/dosdevices/z:").unlink()
        (self.compat / "pfx/dosdevices/h:").symlink_to(self.home)
        self.configure()
        self.assertIn("FfxDx12Path=H:/custom HelixSR/fsr3-drop-in/amd_fidelityfx_dx12.dll", self.ini.read_text())

    def test_unmapped_source_fails_without_guessing_z_drive(self):
        (self.compat / "pfx/dosdevices/z:").unlink()
        self.configure(expected=1)
        self.assertEqual(self.ini.read_text(), ORIGINAL)

    def test_ambiguous_configuration_is_not_changed(self):
        other = self.home / "game/OptiScaler.ini"
        other.write_text(ORIGINAL)
        self.configure(expected=1)
        self.assertEqual(self.ini.read_text(), ORIGINAL)
        self.assertEqual(other.read_text(), ORIGINAL)
        self.env["HELIXSR_CONFIG"] = "Binaries/Win64/OptiScaler.ini"
        self.configure()
        self.assertIn("Dx12Upscaler=fsr31", self.ini.read_text())
        self.assertEqual(other.read_text(), ORIGINAL)

    def test_configuration_outside_game_and_symlink_are_rejected(self):
        outside = self.home / "outside.ini"
        outside.write_text(ORIGINAL)
        self.env["HELIXSR_CONFIG"] = str(outside)
        self.configure(expected=1)
        self.env["HELIXSR_CONFIG"] = str(self.ini)
        self.ini.unlink()
        self.ini.symlink_to(outside)
        self.configure(expected=1)
        self.assertEqual(outside.read_text(), ORIGINAL)

    def test_crlf_bom_and_original_key_format_round_trip(self):
        data = ("\ufeff" + ORIGINAL.replace("Dx12Upscaler=", "  Dx12Upscaler = ")).replace("\n", "\r\n").encode()
        self.ini.write_bytes(data)
        self.configure()
        self.configure("off")
        self.assertEqual(self.ini.read_bytes(), data)

    def test_generated_runner_continues_game_after_configuration_failure(self):
        install_runner(self.home)
        recipe = next(item for item in json.loads((ROOT / "recipes.json").read_text())
                      if item["name"] == "HelixSR")
        option, = recipe["launchOptions"]
        self.assertFalse(option["enableGlobally"])
        self.assertEqual(option["priority"], -2)
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        curl.write_text("#!/bin/bash\nwhile [[ $1 != --output ]]; do shift; done\n"
                        + "cp -- " + shlex.quote(str(SCRIPT)) + ' "$2"\n')
        curl.chmod(0o755)
        self.env.update(PATH=str(bin_dir) + ":" + self.env["PATH"],
                        STEAM_COMPAT_INSTALL_PATH=str(self.home / "game"),
                        STEAM_RUNTIME="/test/steam/runtime", LD_LIBRARY_PATH="/test/steam/libs")
        self.env["SYSTEM_PATH"] = self.env["PATH"]
        self.env["SYSTEM_LD_LIBRARY_PATH"] = ""
        (self.source / "amd_fidelityfx_upscaler_dx12.dll").unlink()
        game = shlex.join([sys.executable, "-c",
                           "import json,os,sys; print(json.dumps([sys.argv[1:],os.environ['STEAM_RUNTIME'],os.environ['LD_LIBRARY_PATH']])); sys.exit(42)",
                           "argument with spaces", "$literal"])
        for action in ("on", "off"):
            result = subprocess.run(["bash", "-c", option[action].replace("%command%", game)],
                                    env=self.env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
            snapshot = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(snapshot, [["argument with spaces", "$literal"],
                                        "/test/steam/runtime", "/test/steam/libs"])
            if action == "on":
                self.assertIn("Recipe helper failed", result.stderr)
        self.assertEqual(self.ini.read_text(), ORIGINAL)

    def test_line_break_in_library_path_is_rejected(self):
        custom = self.home / "HelixSR\nInjected=true"
        self.source.parent.rename(custom)
        self.env["HELIXSR_DIR"] = str(custom)
        self.configure(expected=1)
        self.assertEqual(self.ini.read_text(), ORIGINAL)


if __name__ == "__main__":
    unittest.main()
