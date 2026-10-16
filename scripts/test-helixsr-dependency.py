"""Offline dependency checks; fixtures are not working Windows binaries.

Run: python3 scripts/test-helixsr-dependency.py
Only download/extractor/desktop subprocess boundaries are replaced. The actual
embedded helper performs selection, journaling, filesystem writes and cleanup.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "recipes/helixsr/scripts/dependency.sh"
DIGEST = "575cb4df866116093df75af607e37fd70e10f5163e0f23fd5c804142e80ef0ad"
INI = b"[Upscalers]\nDx12Upscaler=auto\n[Libraries]\nFfxDx12Path=auto\nFfxDx12SRPath=auto\n"
FIXTURE = {"OptiScaler.dll": b"MZ explicit offline OptiScaler fixture",
           "OptiScaler.ini": INI,
           "amd_fidelityfx_dx12.dll": b"MZ explicit support fixture",
           "D3D12_Optiscaler/D3D12Core.dll": b"MZ explicit D3D fixture",
           "Licenses/FidelityFX_v2_LICENSE.md": b"offline license fixture",
           "!! README_EXTRACT ALL FILES TO GAME FOLDER !!.txt": b"offline readme fixture",
           "setup_linux.sh": b"exit 99 # MUST NEVER RUN\n"}

HARNESS = r'''
import hashlib, json, os, pathlib, shutil, subprocess, sys, zipfile
script, game, fixture, trace = map(pathlib.Path, sys.argv[1:])
original_run, original_which = subprocess.run, shutil.which

def record(argv):
    with trace.open("a") as stream:
        stream.write(json.dumps([str(x) for x in argv]) + "\n")

def run(argv, *args, **kwargs):
    argv = [str(x) for x in argv]
    record(argv)
    if pathlib.Path(argv[0]).name == "curl":
        if os.environ.get("TEST_NO_DOWNLOAD"):
            raise AssertionError("unexpected download")
        payload = pathlib.Path(os.environ["TEST_7ZIP_ARCHIVE"]) if "ip7z/7zip" in argv[-1] else fixture
        shutil.copyfile(payload, argv[argv.index("--output") + 1])
        if os.environ.get("TEST_CORRUPT_DOWNLOAD"):
            pathlib.Path(argv[argv.index("--output") + 1]).write_bytes(b"corrupt offline download")
        return subprocess.CompletedProcess(argv, 0, "", "")
    if pathlib.Path(argv[0]).name == "7zz":
        with zipfile.ZipFile(fixture) as archive:
            if argv[1] == "l":
                listing = "\n----------\n" + "\n\n".join(
                    "Path = " + item.filename + "\nSize = " + str(item.file_size) + "\nAttributes = A"
                    for item in archive.infolist()) + "\n"
                if os.environ.get("TEST_ARCHIVE_LINK"):
                    listing = listing.replace("Attributes = A", "Attributes = A_ lrwxrwxrwx\nSymbolic Link = ../outside", 1)
                return subprocess.CompletedProcess(argv, 0, listing, "")
            if argv[1] == "x":
                destination = next(x[2:] for x in argv if x.startswith("-o"))
                archive.extractall(destination)
                return subprocess.CompletedProcess(argv, 0, "", "")
    if argv[0] in ("/offline/zenity", "/offline/kdialog"):
        return subprocess.CompletedProcess(argv, int(os.environ.get("TEST_GUI_STATUS", "0")),
                                          os.environ.get("TEST_GUI_CHOICE", "") + "\n", "")
    if len(argv) > 2 and argv[1] == "-m" and argv[2] == "pip":
        if os.environ.get("TEST_NO_DOWNLOAD"):
            raise AssertionError("unexpected pip download")
        pathlib.Path(argv[argv.index("--target") + 1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, "", "")
    if "-c" in argv and "import py7zr" in argv[argv.index("-c") + 1]:
        environment = kwargs.get("env", {})
        record(["environment", environment.get("PYTHONPATH", ""), environment.get("PYTHONNOUSERSITE", "")])
        if argv[-1] == "probe":
            return subprocess.CompletedProcess(argv, 1, "", "fixture: dependency not installed")
        with zipfile.ZipFile(fixture) as archive:
            if argv[-1] == "list":
                data = [dict(name=x.filename, size=x.file_size, directory=x.is_dir(), link=False) for x in archive.infolist()]
                if os.environ.get("TEST_ARCHIVE_LINK"):
                    data[0]["link"] = True
                return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
            if argv[-1] == "extract":
                if os.environ.get("TEST_BCJ2"):
                    raise subprocess.CalledProcessError(1, argv, stderr="BCJ2 filter is not supported by py7zr")
                archive.extractall(argv[-2])
                return subprocess.CompletedProcess(argv, 0, "", "")
    if "pip" in argv:
        raise AssertionError("unexpected pip boundary")
    raise AssertionError("unexpected subprocess: " + repr(argv))

def which(name, *args, **kwargs):
    if name == "7zz" and not os.environ.get("TEST_NO_7Z"):
        return "/offline/7zz"
    if name == os.environ.get("TEST_GUI_TOOL", "zenity"):
        return "/offline/" + name
    return None

subprocess.run, shutil.which = run, which
original_link = os.link

def link(source, destination, *args, **kwargs):
    if os.environ.get("TEST_INTERRUPT") == "before_link":
        os._exit(79)
    result = original_link(source, destination, *args, **kwargs)
    if os.environ.get("TEST_INTERRUPT") == "after_link":
        os._exit(79)
    return result

os.link = link
original_mkdir, original_fsync = os.mkdir, os.fsync

def mkdir(path, *args, **kwargs):
    result = original_mkdir(path, *args, **kwargs)
    record(["mkdir", str(path)])
    return result

def fsync(fd):
    result = original_fsync(fd)
    record(["fsync", os.readlink("/proc/self/fd/" + str(fd))])
    return result

os.mkdir, os.fsync = mkdir, fsync
original_replace = os.replace

def replace(source, destination, *args, **kwargs):
    if os.environ.get("TEST_CACHE_FAILURE") and pathlib.Path(destination).name == "release":
        raise OSError("offline injected release cache finalization failure")
    return original_replace(source, destination, *args, **kwargs)

os.replace = replace
body = script.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
# Explicitly replace the release pin for an offline fixture, not a production bypass.
body = body.replace("575cb4df866116093df75af607e37fd70e10f5163e0f23fd5c804142e80ef0ad",
                    hashlib.sha256(fixture.read_bytes()).hexdigest())
if os.environ.get("TEST_7ZIP_ARCHIVE"):
    body = body.replace("fc0327ba27e89bd086cf426dff17d77de582953cdbbc10a6576540a06853ffcd",
                        hashlib.sha256(pathlib.Path(os.environ["TEST_7ZIP_ARCHIVE"]).read_bytes()).hexdigest())
    body = body.replace("d1bc79f00e9815b24048ab167690bdd1dbc387de7dbc47e8d75d68689e49cf4f",
                        hashlib.sha256(b"explicit offline 7zz boundary fixture").hexdigest())
sys.argv = [str(script), str(game)]
exec(compile(body, str(script) + ":embedded", "exec"), {"__name__": "__main__"})
'''


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlor dependency ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.game = self.home / "game"
        self.target = self.game / "Project/Binaries/Win64"
        self.target.mkdir(parents=True)
        self.exe = self.target / "Project-Win64-Shipping.exe"
        self.exe.write_bytes(b"MZ offline executable fixture")
        self.runtime = self.home / "runtime"
        self.runtime.touch(mode=0o600)
        self.fixture = self.home / "release.zip"
        self.archive(FIXTURE)
        self.trace = self.home / "subprocess.jsonl"
        self.identity = hashlib.sha256(str(self.game.resolve()).encode()).hexdigest()
        self.state_dir = self.home / ".dlor/state/helixsr"
        self.manifest = self.state_dir / (self.identity + ".dependency.json")
        self.config_state = self.state_dir / (self.identity + ".json")
        self.env = dict(os.environ, HOME=str(self.home),
                        DLOR_HELIXSR_ARGS=json.dumps(["/proton", "waitforexitandrun", str(self.exe)]),
                        DLOR_HELIXSR_RUNTIME_FILE=str(self.runtime))
        for key in ("HELIXSR_CONFIG", "STEAM_COMPAT_DATA_PATH", "WINEPREFIX",
                    "DLOR_OPTISCALER_REQUESTED", "TEST_GUI_CHOICE", "TEST_NO_DOWNLOAD"):
            self.env.pop(key, None)

    def archive(self, files):
        with zipfile.ZipFile(self.fixture, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)

    def run_helper(self, action="on", expected=0, shell=False):
        self.assertTrue(SCRIPT.is_file(), "self-contained dependency helper is missing")
        command = (["bash", str(SCRIPT), str(self.game)] if shell else
                   [sys.executable, "-c", HARNESS, str(SCRIPT), str(self.game),
                    str(self.fixture), str(self.trace)])
        result = subprocess.run(command, env=dict(self.env, DLOR_HELIXSR_ACTION=action),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def calls(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def test_unknown_release_file_collisions_abort_before_any_game_write(self):
        for name in ("OptiScaler.ini", "amd_fidelityfx_dx12.dll", "D3D12_Optiscaler/D3D12Core.dll"):
            with self.subTest(name=name):
                path = self.target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"user mod")
                self.run_helper(expected=1)
                self.assertEqual(path.read_bytes(), b"user mod")
                self.assertFalse((self.target / "dxgi.dll").exists())
                self.assertFalse(self.manifest.exists())
                self.assertEqual(self.runtime.read_bytes(), b"")
                path.unlink()

    def test_disable_removes_only_owned_unchanged_files_without_download(self):
        borrowed = self.target / "amd_fidelityfx_dx12.dll"
        borrowed.write_bytes(FIXTURE[borrowed.name])
        self.run_helper()
        edited = self.target / "dxgi.dll"
        edited.write_bytes(b"user replacement")
        self.env["TEST_NO_DOWNLOAD"] = "1"
        self.env.pop("DLOR_HELIXSR_ARGS")
        self.run_helper("off")
        self.assertEqual(edited.read_bytes(), b"user replacement")
        self.assertEqual(borrowed.read_bytes(), FIXTURE[borrowed.name])
        self.assertFalse((self.target / "OptiScaler.ini").exists())
        self.assertFalse((self.target / "OptiScaler.dll").exists())
        self.assertFalse(self.manifest.exists())
        self.run_helper("off", shell=True)
        logs = list((self.home / ".dlor/logs/helixsr/dependency").glob("*.log"))
        self.assertEqual(len(logs), 1)

    def test_disable_defers_while_config_restore_pending_then_hands_over_independent_demand(self):
        self.run_helper()
        self.env["TEST_NO_DOWNLOAD"] = "1"
        self.config_state.write_text('{"pending": true}')
        self.run_helper("off", expected=1)
        self.assertTrue((self.target / "OptiScaler.ini").exists())
        self.assertTrue(self.manifest.exists())
        self.config_state.unlink()
        self.env["DLOR_OPTISCALER_REQUESTED"] = "1"
        self.run_helper("off")
        self.assertTrue((self.target / "dxgi.dll").exists())
        self.assertTrue((self.target / "OptiScaler.ini").exists())
        self.assertFalse(self.manifest.exists())
        self.env.pop("DLOR_OPTISCALER_REQUESTED")
        self.run_helper("off")
        self.assertTrue((self.target / "dxgi.dll").exists())

    def test_verified_existing_proxy_is_borrowed_without_download_or_file_ownership(self):
        for source_location in (self.target, self.home / "fgmod"):
            with self.subTest(source=source_location):
                source_location.mkdir(exist_ok=True)
                source = source_location / "OptiScaler.dll"
                source.write_bytes(b"MZ legacy verified source fixture")
                ini = self.target / "oPtIsCaLeR.InI"
                ini.write_bytes(INI)
                proxy = self.target / "WiNmM.DlL"
                proxy.write_bytes(source.read_bytes())
                self.env["TEST_NO_DOWNLOAD"] = "1"
                self.run_helper()
                self.assertEqual(self.runtime.read_text(), "winmm\n")
                self.assertEqual(Path(str(self.runtime) + ".config").read_text(), str(ini) + "\n")
                self.assertFalse(self.manifest.exists())
                self.run_helper("off")
                self.assertEqual(proxy.read_bytes(), source.read_bytes())
                self.assertEqual(ini.read_bytes(), INI)
                proxy.unlink()
                ini.unlink()
                source.unlink()

    def test_interrupted_install_can_retry_without_dropping_original_ownership(self):
        self.env["TEST_INTERRUPT"] = "after_link"
        self.run_helper(expected=79)
        state = json.loads(self.manifest.read_text())
        self.assertTrue(state["files"])
        self.env.pop("TEST_INTERRUPT")
        self.env["TEST_NO_DOWNLOAD"] = "1"
        self.run_helper()
        self.run_helper("off")
        for name in state["files"]:
            self.assertFalse((self.target / name).exists(), name)

    def test_wine_drive_executable_is_resolved_case_insensitively(self):
        compat = self.home / "compat"
        drives = compat / "pfx/dosdevices"
        drives.mkdir(parents=True)
        (drives / "g:").symlink_to(self.game)
        self.env["STEAM_COMPAT_DATA_PATH"] = str(compat)
        self.env["DLOR_HELIXSR_ARGS"] = json.dumps(["proton", r"G:\project\binaries\win64\project-win64-shipping.exe", "$literal; no eval"])
        self.run_helper()
        self.assertTrue((self.target / "dxgi.dll").exists())
        self.assertFalse((self.game / "dxgi.dll").exists())

    def test_unreal_root_launcher_selects_nested_shipping_executable(self):
        launcher = self.game / "Project.exe"
        launcher.write_bytes(b"MZ launcher fixture")
        helper = self.target / "CrashReportClient.exe"
        helper.write_bytes(b"MZ non-rendering helper fixture")
        self.env["DLOR_HELIXSR_ARGS"] = json.dumps([str(launcher)])
        self.run_helper()
        self.assertTrue((self.target / "dxgi.dll").exists())
        self.assertFalse((self.game / "dxgi.dll").exists())

    def test_ambiguous_renderers_are_logged_without_dialogs_or_game_changes(self):
        other = self.game / "Other/Binaries/Win64/Other-Win64-Shipping.exe"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"MZ second offline renderer")
        self.env["DLOR_HELIXSR_ARGS"] = "[]"
        self.env["TEST_NO_DOWNLOAD"] = "1"
        before = {path.relative_to(self.game): path.read_bytes() for path in self.game.rglob("*") if path.is_file()}
        self.run_helper(expected=1)
        self.assertFalse(any(call[0] in ("/offline/zenity", "/offline/kdialog") for call in self.calls()))
        self.assertFalse(self.manifest.exists())
        self.assertEqual({path.relative_to(self.game): path.read_bytes() for path in self.game.rglob("*") if path.is_file()}, before)

    def test_selected_renderer_wins_over_unrelated_verified_launcher_installation(self):
        legacy = self.game / "ObsoleteLauncher"
        legacy.mkdir()
        borrowed = {"OptiScaler.dll": FIXTURE["OptiScaler.dll"],
                    "version.dll": FIXTURE["OptiScaler.dll"], "OptiScaler.ini": INI}
        for name, data in borrowed.items():
            (legacy / name).write_bytes(data)
        launcher = self.game / "Project.exe"
        launcher.write_bytes(b"MZ launcher fixture")
        drives = self.home / "compat/pfx/dosdevices"
        drives.mkdir(parents=True)
        (drives / "g:").symlink_to(self.game)
        self.env["STEAM_COMPAT_DATA_PATH"] = str(self.home / "compat")
        for mode in ("direct", "wine", "unreal", "discovery"):
            with self.subTest(mode=mode):
                arguments = {"direct": [str(self.exe)],
                             "wine": [r"G:\project\binaries\win64\project-win64-shipping.exe"],
                             "unreal": [str(launcher)], "discovery": []}
                self.env["DLOR_HELIXSR_ARGS"] = json.dumps(arguments[mode])
                self.run_helper()
                self.assertTrue((self.target / "dxgi.dll").is_file())
                self.assertEqual(self.runtime.read_text(), "dxgi\n")
                self.assertEqual(Path(str(self.runtime) + ".config").read_text(),
                                 str(self.target / "OptiScaler.ini") + "\n")
                self.assertEqual(json.loads(self.manifest.read_text())["target"], str(self.target))
                self.run_helper("off")
                self.assertFalse((self.target / "dxgi.dll").exists())
                for name, data in borrowed.items():
                    self.assertEqual((legacy / name).read_bytes(), data)
                self.env["TEST_NO_DOWNLOAD"] = "1"

    def test_changed_renderer_refuses_stale_manifest_until_owned_dependency_is_disabled(self):
        self.run_helper()
        previous = self.manifest.read_bytes()
        replacement = self.game / "Updated/Binaries/Win64/Updated-Win64-Shipping.exe"
        replacement.parent.mkdir(parents=True)
        replacement.write_bytes(b"MZ replacement renderer fixture")
        before = {path.relative_to(self.game): path.read_bytes()
                  for path in self.game.rglob("*") if path.is_file()}
        self.env["DLOR_HELIXSR_ARGS"] = json.dumps([str(replacement)])
        self.env["TEST_NO_DOWNLOAD"] = "1"
        result = self.run_helper(expected=1)
        self.assertIn("Rendering executable directory changed", result.stderr)
        self.assertEqual(self.runtime.read_bytes(), b"")
        self.assertFalse(Path(str(self.runtime) + ".config").exists())
        self.assertEqual(self.manifest.read_bytes(), previous)
        self.assertEqual({path.relative_to(self.game): path.read_bytes()
                          for path in self.game.rglob("*") if path.is_file()}, before)
        self.run_helper("off")
        self.assertFalse((self.target / "dxgi.dll").exists())
        self.run_helper()
        self.assertEqual(json.loads(self.manifest.read_text())["target"], str(replacement.parent))
        self.assertTrue((replacement.parent / "dxgi.dll").is_file())
        self.assertEqual(Path(str(self.runtime) + ".config").read_text(),
                         str(replacement.parent / "OptiScaler.ini") + "\n")
        self.run_helper("off")
        self.assertFalse((replacement.parent / "dxgi.dll").exists())

    def test_unsafe_archive_names_are_rejected_before_extraction(self):
        for name in ("../escape.dll", "/absolute.dll", "C:/drive.dll", "bad\\name.dll", "Licenses/../../escape.dll", "optiscaler.DLL"):
            with self.subTest(name=name):
                self.archive(dict(FIXTURE, **{name: b"unsafe fixture"}))
                self.trace.write_text("")
                self.run_helper(expected=1)
                self.assertFalse(any(call[0] == "/offline/7zz" and call[1] == "x" for call in self.calls()))
                self.assertFalse(self.manifest.exists())
                self.assertFalse((self.target / "dxgi.dll").exists())

    def test_missing_host_extractor_bootstraps_private_binary_only_pinned_py7zr(self):
        self.env["TEST_NO_7Z"] = "1"
        self.env["PYTHONPATH"] = "/must-not-propagate"
        self.run_helper()
        pip, = [call for call in self.calls() if len(call) > 2 and call[1:3] == ["-m", "pip"]]
        self.assertIn("py7zr==1.0.0", pip)
        self.assertIn("--only-binary=:all:", pip)
        self.assertIn("--target", pip)
        self.assertIn("--cache-dir", pip)
        for call in self.calls():
            if call[0] == "environment":
                self.assertNotIn("/must-not-propagate", call[1])
                self.assertTrue(call[1].startswith(str(self.home)))
                self.assertEqual(call[2], "1")
        self.assertEqual(self.runtime.read_text(), "dxgi\n")

    def test_bcj2_archive_uses_verified_private_console_tool_when_py7zr_cannot_decode(self):
        import io
        import tarfile
        tool_archive = self.home / "7zip.tar.xz"
        with tarfile.open(tool_archive, "w:xz") as archive:
            for name, data in {"7zz": b"explicit offline 7zz boundary fixture", "License.txt": b"offline tool license"}.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        self.env.update(TEST_NO_7Z="1", TEST_BCJ2="1", TEST_7ZIP_ARCHIVE=str(tool_archive))
        self.run_helper()
        self.assertEqual(self.runtime.read_text(), "dxgi\n")
        downloads = [call[-1] for call in self.calls() if call[0] == "curl"]
        self.assertTrue(any("ip7z/7zip/releases/download/26.04/" in url for url in downloads))
        self.assertTrue(any(Path(call[0]).name == "7zz" for call in self.calls()))

    def test_release_cache_preserves_all_unmodified_members_after_disable(self):
        self.run_helper()
        cache = self.home / ".dlor/cache/helixsr/optiscaler/v0.9.4/release"
        for name, data in FIXTURE.items():
            self.assertTrue((cache / name).is_file(), "complete extracted release cache must be retained")
            self.assertEqual((cache / name).read_bytes(), data)
        self.run_helper("off")
        self.assertTrue((cache / "setup_linux.sh").exists())
        self.assertTrue((cache.parent / "Optiscaler_0.9.4-final.20260718._MM.7z").exists())

    def test_failure_clears_stale_outputs_and_reports_in_desktop_dialog(self):
        self.runtime.write_text("dxgi\n")
        config_output = Path(str(self.runtime) + ".config")
        config_output.write_text("/stale/OptiScaler.ini\n")
        config_output.chmod(0o600)
        (self.target / "OptiScaler.ini").write_bytes(b"unknown mod config")
        self.run_helper(expected=1)
        self.assertEqual(self.runtime.read_bytes(), b"")
        self.assertFalse(config_output.exists())
        self.assertFalse(any(call[0] in ("/offline/zenity", "/offline/kdialog") for call in self.calls()))

    def test_runtime_output_must_be_private_owned_regular_file_not_symlink(self):
        outside = self.home / "outside"
        outside.write_bytes(b"keep")
        self.runtime.unlink()
        self.runtime.symlink_to(outside)
        self.run_helper(expected=1)
        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual(outside.read_bytes(), b"keep")
        self.assertFalse(self.manifest.exists())
        self.runtime.unlink()
        self.runtime.touch(mode=0o644)
        self.runtime.chmod(0o644)
        self.run_helper(expected=1)
        self.assertFalse(self.manifest.exists())

    def test_journal_directory_creation_is_durable_before_game_installation(self):
        self.run_helper()
        events = self.calls()
        directories = (self.home / ".dlor", self.home / ".dlor/state", self.state_dir,
                       self.target / "D3D12_Optiscaler", self.target / "Licenses")
        for directory in directories:
            with self.subTest(directory=directory):
                index = events.index(["mkdir", str(directory)])
                self.assertEqual(events[index + 1], ["fsync", str(directory.parent)])

    def test_case_variant_identical_ini_is_borrowed_and_published_at_its_actual_path(self):
        ini = self.target / "optiscaler.INI"
        ini.write_bytes(INI)
        self.run_helper()
        self.assertEqual(Path(str(self.runtime) + ".config").read_text(), str(ini) + "\n")
        self.run_helper("off")
        self.assertEqual(ini.read_bytes(), INI)

    def test_selected_directory_line_break_is_refused_before_install(self):
        target = self.game / "unsafe\npath"
        target.mkdir()
        exe = target / "Actual.exe"
        exe.write_bytes(b"MZ offline fixture")
        self.env["DLOR_HELIXSR_ARGS"] = json.dumps([str(exe)])
        self.run_helper(expected=1)
        self.assertFalse((target / "OptiScaler.ini").exists())
        self.assertFalse(self.manifest.exists())

    def test_malformed_dependency_journal_is_refused_without_dialogs_or_traceback(self):
        self.state_dir.mkdir(parents=True)
        self.manifest.write_text("[]")
        self.env["TEST_NO_DOWNLOAD"] = "1"
        result = self.run_helper("off", expected=1)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.manifest.read_text(), "[]")
        self.assertFalse(any(call[0] in ("/offline/zenity", "/offline/kdialog") for call in self.calls()))

    def test_bad_download_checksum_never_reaches_an_extractor(self):
        self.env["TEST_CORRUPT_DOWNLOAD"] = "1"
        result = self.run_helper(expected=1)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(any(Path(call[0]).name == "7zz" for call in self.calls()))
        self.assertFalse(self.manifest.exists())

    def test_archive_links_are_rejected_before_either_extraction_backend_writes(self):
        self.env["TEST_ARCHIVE_LINK"] = "1"
        for no_host in ("", "1"):
            with self.subTest(no_host=no_host):
                self.env["TEST_NO_7Z"] = no_host
                self.trace.write_text("")
                self.run_helper(expected=1)
                self.assertFalse(any((Path(call[0]).name == "7zz" and call[1] == "x")
                                     or ("-c" in call and call[-1] == "extract") for call in self.calls()))
                self.assertFalse(self.manifest.exists())

    def test_unknown_proxy_names_are_preserved_and_only_unused_proxy_is_selected(self):
        for name in ("DXGI.dll", "winmm.DLL"):
            (self.target / name).write_bytes(b"unknown existing proxy")
        self.run_helper()
        self.assertEqual(self.runtime.read_text(), "version\n")
        self.run_helper("off")
        for name in ("DXGI.dll", "winmm.DLL"):
            self.assertEqual((self.target / name).read_bytes(), b"unknown existing proxy")
        (self.target / "version.dll").write_bytes(b"third existing proxy")
        self.run_helper(expected=1)
        self.assertFalse((self.target / "OptiScaler.ini").exists())

    def test_helper_shares_configurator_lock_before_game_mutations(self):
        import fcntl
        self.state_dir.mkdir(parents=True)
        with (self.state_dir / (self.identity + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            command = [sys.executable, "-c", HARNESS, str(SCRIPT), str(self.game), str(self.fixture), str(self.trace)]
            process = subprocess.Popen(command, env=dict(self.env, DLOR_HELIXSR_ACTION="on"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.2)
                self.assertFalse((self.target / "OptiScaler.ini").exists())
                fcntl.flock(lock, fcntl.LOCK_UN)
                output, error = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, output + error)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_shell_restores_host_environment_retains_ten_logs_and_never_logs_argv(self):
        import shlex
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        snapshot = self.home / "host-env.json"
        probe = ("import json,os,pathlib; pathlib.Path(" + repr(str(snapshot)) + ").write_text(json.dumps("
                 "{k:os.environ.get(k) for k in ['STEAM_RUNTIME','LD_LIBRARY_PATH','LD_PRELOAD','PATH']}))")
        python = bin_dir / "python3"
        python.write_text("#!/bin/bash\n" + shlex.join([sys.executable, "-c", probe])
                          + "\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
        python.chmod(0o700)
        system_path = str(bin_dir) + ":" + os.defpath
        self.env.update(STEAM_RUNTIME="/steam/runtime", SYSTEM_LD_LIBRARY_PATH="/host/libs",
                        SYSTEM_PATH=system_path, LD_LIBRARY_PATH="/steam/libs", LD_PRELOAD="")
        secret = "PRIVATE_ARGV_TOKEN_DO_NOT_LOG"
        self.env["DLOR_HELIXSR_ARGS"] = json.dumps([str(self.exe), secret])
        logs = self.home / ".dlor/logs/helixsr/dependency"
        logs.mkdir(parents=True)
        for index in range(12):
            (logs / ("2000-01-01." + str(index).zfill(2) + ".log")).touch()
        outside = self.home / "unowned.log"
        outside.write_text("keep")
        (logs / "0000-symlink.log").symlink_to(outside)
        self.run_helper("off", shell=True)
        self.assertEqual(json.loads(snapshot.read_text()), dict(STEAM_RUNTIME=None, LD_LIBRARY_PATH="/host/libs", LD_PRELOAD=None, PATH=system_path))
        retained = [path for path in logs.glob("*.log") if not path.is_symlink()]
        self.assertEqual(len(retained), 10)
        self.assertTrue((logs / "0000-symlink.log").is_symlink())
        self.assertEqual(outside.read_text(), "keep")
        self.assertTrue(all(secret not in path.read_text() for path in retained))

    def test_runtime_is_not_published_until_all_install_finalization_succeeds(self):
        self.env["TEST_CACHE_FAILURE"] = "1"
        self.run_helper(expected=1)
        self.assertEqual(self.runtime.read_bytes(), b"")
        self.assertFalse(json.loads(self.manifest.read_text())["complete"])
        self.env.pop("TEST_CACHE_FAILURE")
        self.run_helper()
        self.assertEqual(self.runtime.read_text(), "dxgi\n")
        self.run_helper("off")
        self.assertFalse((self.target / "dxgi.dll").exists())

    def test_install_targets_actual_executable_and_publishes_verified_outputs(self):
        self.run_helper()
        self.assertEqual(self.runtime.read_text(), "dxgi\n")
        self.assertEqual(Path(str(self.runtime) + ".config").read_text(), str(self.target / "OptiScaler.ini") + "\n")
        for name, data in FIXTURE.items():
            if name != "setup_linux.sh":
                self.assertEqual((self.target / name).read_bytes(), data)
        self.assertEqual((self.target / "dxgi.dll").read_bytes(), FIXTURE["OptiScaler.dll"])
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest["game"], str(self.game))
        self.assertEqual(manifest["proxy"], "dxgi")
        self.assertTrue(manifest["files"])
        self.assertTrue((self.state_dir / (self.identity + ".lock")).exists())
        self.assertFalse((self.game / "OptiScaler.ini").exists())
        self.assertTrue(any(x[0] == "curl" for x in self.calls()))
        self.assertFalse(any("setup_linux.sh" in x for call in self.calls() for x in call))


if __name__ == "__main__":
    unittest.main()
