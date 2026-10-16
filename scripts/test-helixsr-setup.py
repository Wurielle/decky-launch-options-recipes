"""Offline automatic-setup checks; no NVIDIA artifacts or models are fetched."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import io
import stat
import tarfile
import zipfile
import json
import struct
from unittest.mock import patch
from typing import Any
import os
import subprocess
import sys


# Synthetic network bytes only; never executable or derived from NVIDIA models.
FIXTURE_WEIGHTS = b"offline synthetic weights"


def built_fixture(folder, source_sha):
    folder.mkdir(parents=True, exist_ok=True)
    pak = b"HXSRKPAK" + struct.pack("<II", 2, 1) + struct.pack("<32sII", b"shader", 56, 4) + b"FAKE"
    dll = b"MZ offline non-executable fixture" + FIXTURE_WEIGHTS + pak + b"HXSRNET1" + struct.pack("<QQQ", len(FIXTURE_WEIGHTS), len(pak), 1)
    (folder / "amd_fidelityfx_dx12.dll").write_bytes(dll)
    drop = folder / "fsr3-drop-in"
    drop.mkdir(exist_ok=True)
    for name in ("amd_fidelityfx_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll"):
        (drop / name).write_bytes(dll)
    (folder / "helixsr_setup.json").write_text(json.dumps({"source_sha256": source_sha, "weights_sha256": hashlib.sha256(FIXTURE_WEIGHTS).hexdigest()}))
    return dll


def fixture_module():
    module = setup_module()
    module["WEIGHTS_SIZE"] = len(FIXTURE_WEIGHTS)
    module["WEIGHTS_SHA"] = hashlib.sha256(FIXTURE_WEIGHTS).hexdigest()
    return module


def zip_fixture(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "recipes/helixsr/scripts/setup.sh"


def setup_module():
    if not SETUP.exists():
        raise AssertionError("The HelixSR toggle needs its own automatic setup helper")
    source = SETUP.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    module: dict[str, Any] = {"__name__": "helixsr_setup_test"}
    exec(compile(source, str(SETUP) + ":embedded", "exec"), module)
    return module


class SetupTests(unittest.TestCase):
    def test_downloads_once_reuses_valid_archive_and_replaces_corruption(self):
        module = setup_module()
        payload = b"explicit offline download fixture"
        digest = hashlib.sha256(payload).hexdigest()
        downloads = []

        def download(url, destination):
            downloads.append(url)
            destination.write_bytes(payload)

        module["download_file"] = download
        with tempfile.TemporaryDirectory(prefix="helixsr setup ") as folder:
            archive = Path(folder) / "release/archive.zip"
            for _ in range(2):
                self.assertEqual(module["cached_download"](archive, "https://fixture.invalid/archive.zip", digest), archive)
                self.assertEqual(archive.read_bytes(), payload)
            self.assertEqual(len(downloads), 1)
            archive.write_bytes(b"corrupt fixture")
            module["cached_download"](archive, "https://fixture.invalid/archive.zip", digest)
            self.assertEqual(archive.read_bytes(), payload)
            self.assertEqual(len(downloads), 2)
            self.assertEqual([p.name for p in archive.parent.iterdir()], ["archive.zip"])


    def test_extracts_complete_zip_normalizes_windows_paths_and_rejects_escapes(self):
        module = setup_module()
        self.assertIn("safe_extract", module, "Setup must extract complete verified releases safely")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "fixture.zip"
            zip_fixture(archive, {"release/setup/main.py": b"unmodified fixture", "bin\\x64\\": b"", "bin\\x64\\dxc.exe": b"fixture compiler", "release/extra.dat": b"retain me"})
            try:
                module["safe_extract"](archive, root / "good")
            except OSError as error:
                self.fail(f"Windows ZIP directory separators must be normalized before extraction: {error}")
            self.assertEqual((root / "good/release/extra.dat").read_bytes(), b"retain me")
            self.assertEqual((root / "good/bin/x64/dxc.exe").read_bytes(), b"fixture compiler")
            for index, name in enumerate(("../escape", "/absolute", "C:\\escape", "safe/../../escape")):
                zip_fixture(archive, {name: b"bad"})
                with self.subTest(name=name), self.assertRaises(ValueError):
                    module["safe_extract"](archive, root / f"bad{index}")
            with zipfile.ZipFile(archive, "w") as stream:
                link = zipfile.ZipInfo("link")
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                stream.writestr(link, "../escape")
            with self.assertRaises(ValueError):
                module["safe_extract"](archive, root / "badlink")


    def test_validates_embedded_network_pak_metadata_and_both_dropins(self):
        module = fixture_module()
        self.assertTrue(callable(module.get("validate_output")), "Readiness requires network validation")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            dll = built_fixture(folder, module["DLSS_SHA"])
            self.assertEqual(module["validate_output"](folder), hashlib.sha256(dll).hexdigest())
            mutations = [b"NO" + dll[2:], dll[:-1], dll[:-8] + struct.pack("<Q", 2),
                         dll[:-24] + struct.pack("<QQQ", 999999, 10, 1),
                         dll.replace(FIXTURE_WEIGHTS, b"x" * len(FIXTURE_WEIGHTS)),
                         dll.replace(b"HXSRKPAK", b"BADPAK!!"),
                         dll.replace(struct.pack("<II", 2, 1), struct.pack("<II", 3, 1)),
                         dll.replace(struct.pack("<II", 56, 4), struct.pack("<II", 999999, 4))]
            for index, damaged in enumerate(mutations):
                with self.subTest(mutation=index):
                    (folder / "amd_fidelityfx_dx12.dll").write_bytes(damaged)
                    with self.assertRaises(ValueError):
                        module["validate_output"](folder)
            built_fixture(folder, module["DLSS_SHA"])
            (folder / "fsr3-drop-in/amd_fidelityfx_upscaler_dx12.dll").write_bytes(b"bad")
            with self.assertRaises(ValueError):
                module["validate_output"](folder)
            built_fixture(folder, "wrong source")
            with self.assertRaises(ValueError):
                module["validate_output"](folder)


    def test_first_toggle_provisions_without_display_or_dialog_tools(self):
        module = fixture_module()
        calls = []
        def build(cache, output, marker):
            calls.append(output)
            dll = built_fixture(output, module["DLSS_SHA"])
            module["atomic_json"](marker, dict(module["source_identity"](), dll_sha256=hashlib.sha256(dll).hexdigest()))
            return output
        module["build_release"] = build
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True), patch.object(
                module["shutil"], "which", return_value=None), patch.object(
                module["subprocess"], "run", side_effect=AssertionError("No desktop interaction is allowed")):
            cache = Path(temporary)
            output = cache / "HelixSR-1.9.0"
            self.assertEqual(module["provision"](cache), output)
            self.assertEqual(module["provision"](cache), output)
            self.assertEqual(calls, [output])
            self.assertFalse((cache / "consent.json").exists())


    def test_first_run_builds_complete_release_unattended_then_reuses_validated_cache(self):
        module = fixture_module()
        self.assertTrue(callable(module.get("run_setup")), "First toggle must automatically provision")
        with tempfile.TemporaryDirectory(prefix="helixsr offline ") as temporary:
            home = Path(temporary)
            cache = home / "override cache/1.9.0"
            runtime = home / "runtime"
            archive = home / "fixture.zip"
            zip_fixture(archive, {"HelixSR-1.9.0/setup/helixsr_setup.py": b"# unmodified offline fixture\n", "HelixSR-1.9.0/amd_fidelityfx_dx12.dll": b"MZ placeholder", "HelixSR-1.9.0/retained/nested.txt": b"complete release", "HelixSR-1.9.0/setup/lib/model/launch_synth": b"offline non-executable helper fixture"})
            release_bytes = archive.read_bytes()
            dlss_bytes = b"offline non-NVIDIA DLL fixture"
            module["RELEASE_SHA"] = hashlib.sha256(release_bytes).hexdigest()
            module["DLSS_SHA"] = hashlib.sha256(dlss_bytes).hexdigest()
            events = []
            def download(url, destination):
                events.append(url)
                destination.write_bytes(release_bytes if url == module["RELEASE_URL"] else dlss_bytes)
            def tools(path):
                events.append("tools")
                return Path("/fixture/python3"), cache / "dxc-wrapper"
            commands = []
            def build(command, **kwargs):
                self.assertTrue(os.access(cache / "HelixSR-1.9.0/setup/lib/model/launch_synth", os.X_OK),
                                "The official static helper must work even when ZIP executable bits are absent")
                commands.append((command, kwargs))
                built_fixture(cache / "HelixSR-1.9.0", module["DLSS_SHA"])
                return type("Result", (), {"returncode": 0})()
            module.update(download_file=download, ensure_tools=tools)
            env = {"HOME": str(home), "HELIXSR_CACHE_DIR": str(home / "override cache"), "DLOR_HELIXSR_RUNTIME_FILE": str(runtime)}
            with patch.dict(module["os"].environ, env, clear=True), patch.object(module["subprocess"], "run", side_effect=build):
                output = module["run_setup"]()
                self.assertEqual(output, cache / "HelixSR-1.9.0")
                self.assertEqual(Path(str(runtime) + ".setup").read_text(), "ready")
                self.assertEqual((output / "retained/nested.txt").read_bytes(), b"complete release")
                self.assertEqual((output / "setup/helixsr_setup.py").read_bytes(), b"# unmodified offline fixture\n")
                command, kwargs = commands[0]
                self.assertEqual(command, ["/fixture/python3", "-I", "-B", str(output / "setup/helixsr_setup.py"), str(output), "--yes", "--no-fg", "--dxc", str(cache / "dxc-wrapper"), "--dlss", str(cache / "downloads/nvngx_dlss.dll")])
                self.assertEqual(kwargs["env"]["TMPDIR"], str(cache / "tmp"))
                before = list(events)
                module["run_setup"]()
                self.assertEqual(events, before, "Valid cache must skip downloads and build")
                self.assertEqual(len(commands), 1)
                (output / "fsr3-drop-in/amd_fidelityfx_dx12.dll").write_bytes(b"corrupt")
                module["run_setup"]()
                self.assertEqual(len(commands), 2)
                self.assertEqual(events.count(module["RELEASE_URL"]), 1)
                self.assertEqual(events.count(module["DLSS_URL"]), 1)


    def test_builder_nonisolated_descendants_do_not_inherit_game_python_environment(self):
        module = fixture_module()
        with tempfile.TemporaryDirectory(prefix="helixsr descendants ") as temporary:
            root = Path(temporary)
            release = root / "fixture-release"
            built_fixture(release, module["DLSS_SHA"])
            setup = release / "setup"
            setup.mkdir()
            builder = ("import subprocess,sys\nfrom pathlib import Path\n"
                       "subprocess.run([sys.executable, str(Path(__file__).with_name('trace_tables.py'))], check=True)\n")
            child = ("import json,os,sys\nfrom pathlib import Path\nimport fixture_kernel\n"
                     "Path(os.environ['FIXTURE_RESULT']).write_text(json.dumps(dict("
                     "isolated=sys.flags.isolated, no_bytecode=sys.dont_write_bytecode, "
                     "home=os.environ.get('PYTHONHOME'), path=os.environ.get('PYTHONPATH'), "
                     "token=os.environ['FIXTURE_TOKEN'], tmp=os.environ['TMPDIR'], value=fixture_kernel.VALUE)))\n")
            (setup / "helixsr_setup.py").write_text(builder)
            (setup / "trace_tables.py").write_text(child)
            (setup / "fixture_kernel.py").write_text("VALUE = 'clean descendant'\n")
            archive = root / "release.zip"
            zip_fixture(archive, {"HelixSR-1.9.0/" + str(path.relative_to(release)): path.read_bytes()
                                  for path in release.rglob("*") if path.is_file()})
            game_path = root / "game-pythonpath"
            game_path.mkdir()
            (game_path / "json.py").write_text("raise RuntimeError('game PYTHONPATH leaked into descendant')\n")
            module["ensure_tools"] = lambda cache: (Path(sys.executable), cache / "wrapper")
            module["cached_download"] = lambda destination, url, digest: archive if url == module["RELEASE_URL"] else root / "offline-dlss"
            real_run = subprocess.run
            for name, game_env in (("home", {"PYTHONHOME": str(root / "missing-game-python")}),
                                   ("path", {"PYTHONPATH": str(game_path)})):
                with self.subTest(variable=name):
                    cache = root / name
                    cache.mkdir()
                    output = cache / "HelixSR-1.9.0"
                    report = cache / "descendant.json"
                    environment = dict(game_env, PYTHONDONTWRITEBYTECODE="", FIXTURE_RESULT=str(report),
                                       FIXTURE_TOKEN="preserved", TMPDIR=str(cache))
                    with patch.dict(os.environ, environment, clear=True), patch.object(
                            subprocess, "run", side_effect=lambda command, **kwargs: real_run(
                                command, capture_output=True, text=True, **kwargs)):
                        try:
                            self.assertEqual(module["build_release"](cache, output, cache / "ready.json"), output)
                        except subprocess.CalledProcessError as error:
                            self.fail("Builder's nonisolated descendant failed: " + error.stderr)
                        self.assertEqual(dict(os.environ), environment, "Do not change the caller/game environment")
                    result = json.loads(report.read_text())
                    self.assertEqual(result, dict(isolated=0, no_bytecode=True, home=None, path=None,
                                                  token="preserved", tmp=str(cache), value="clean descendant"))
                    self.assertEqual(list(output.rglob("*.pyc")), [], "Descendants must not regenerate bytecode")
                    self.assertEqual((output / "setup/helixsr_setup.py").read_text(), builder,
                                     "Do not modify upstream scripts to repair inheritance")
                    self.assertTrue((cache / "ready.json").is_file())


    def test_extracts_portable_tar_internal_file_links_without_unsafe_links_or_devices(self):
        module = setup_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "python.tar.gz"
            def write_tar(link_target="python3.12", link_type=tarfile.SYMTYPE):
                with tarfile.open(archive, "w:gz") as stream:
                    binary = tarfile.TarInfo("python/bin/python3.12")
                    binary.mode = 0o755
                    binary.size = 7
                    stream.addfile(binary, io.BytesIO(b"fixture"))
                    link = tarfile.TarInfo("python/bin/python3")
                    link.type = link_type
                    link.linkname = link_target
                    stream.addfile(link)
            write_tar()
            try:
                module["safe_extract"](archive, root / "valid")
            except zipfile.BadZipFile as error:
                self.fail(f"Portable Python tar archives must be supported: {error}")
            self.assertEqual((root / "valid/python/bin/python3").read_bytes(), b"fixture")
            self.assertTrue((root / "valid/python/bin/python3").stat().st_mode & stat.S_IXUSR)
            for index, (target, kind) in enumerate((("../../../escape", tarfile.SYMTYPE), ("/escape", tarfile.SYMTYPE), ("python/bin/python3.12", tarfile.CHRTYPE))):
                write_tar(target, kind)
                with self.assertRaises(ValueError):
                    module["safe_extract"](archive, root / f"bad{index}")


    def test_portable_python_installs_pinned_binary_numpy_without_touching_host_packages(self):
        module = setup_module()
        self.assertTrue(callable(module.get("ensure_python")), "Missing numpy must provision isolated portable Python")
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            archive = cache / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                info = tarfile.TarInfo("python/bin/python3")
                info.mode, info.size = 0o755, 7
                stream.addfile(info, io.BytesIO(b"fixture"))
            payload = archive.read_bytes()
            module["PYTHON_SHA"] = hashlib.sha256(payload).hexdigest()
            downloads, commands = [], []
            installed = [False]
            def download(url, destination):
                downloads.append(url)
                destination.write_bytes(payload)
            def run(command, **kwargs):
                commands.append(command)
                if "pip" in command:
                    self.assertEqual(command[0], str(cache / "python/bin/python3"))
                    self.assertIn("numpy==2.3.3", command)
                    self.assertIn("--only-binary=:all:", command)
                    self.assertIn("--isolated", command)
                    self.assertIn("-B", command)
                    self.assertIn("--no-compile", command)
                    self.assertIn(str(cache / "pip"), command)
                    installed[0] = True
                    return type("Result", (), {"returncode": 0})()
                portable = command[0] == str(cache / "python/bin/python3")
                return type("Result", (), {"returncode": 0 if portable and installed[0] else 1})()
            module["download_file"] = download
            with patch.object(module["subprocess"], "run", side_effect=run):
                self.assertEqual(module["ensure_python"](cache), cache / "python/bin/python3")
                self.assertEqual(module["ensure_python"](cache), cache / "python/bin/python3")
                (cache / "python/bin/python3").write_bytes(b"corrupt executable fixture")
                module["ensure_python"](cache)
                self.assertEqual((cache / "python/bin/python3").read_bytes(), b"fixture", "Cached executables require integrity validation before execution")
            self.assertEqual(len(downloads), 1)
            self.assertEqual(sum("pip" in command for command in commands), 2)
            with patch.object(module["subprocess"], "run", return_value=type("Result", (), {"returncode": 0})()):
                self.assertEqual(module["ensure_python"](cache), Path(module["sys"].executable))


    def test_cached_private_python_discards_matching_untrusted_bytecode_before_execution(self):
        import py_compile
        import venv

        module = setup_module()
        with tempfile.TemporaryDirectory(prefix="helixsr bytecode ") as temporary:
            cache = Path(temporary)
            private = cache / "python"
            venv.EnvBuilder(with_pip=False, symlinks=False).create(private)
            python = private / "bin/python3"
            site = next((private / "lib").glob("python*/site-packages"))
            source = site / "numpy.py"
            probe = cache / "import-result"
            clean = (f"from pathlib import Path\nPath({str(probe)!r}).write_text('1')\n"
                     "__version__ = '2.3.3'\ndef frombuffer(*args, **kwargs): return [1]\n")
            source.write_text(clean)
            timestamp = source.stat().st_mtime_ns
            state = module["python_state"](cache)
            module["atomic_json"](cache / "python-ready.json", state)
            source.write_text(clean.replace("write_text('1')", "write_text('2')"))
            os.utime(source, ns=(timestamp, timestamp))
            compiled = py_compile.compile(str(source), doraise=True)
            assert compiled is not None
            pyc = Path(compiled)
            source.write_text(clean)
            os.utime(source, ns=(timestamp, timestamp))
            legacy = site / "unused.pyc"
            legacy.write_bytes(pyc.read_bytes())
            outside = cache / "not-owned/__pycache__/keep.pyc"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(b"must not touch host or unrelated bytecode")
            self.assertEqual(module["python_state"](cache), state,
                             "Matching bytecode is intentionally excluded from source integrity")
            control = subprocess.run([str(python), "-I", "-B", "-c", "import numpy"],
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(control.returncode, 0, control.stderr)
            self.assertEqual(probe.read_text(), "2", "Even -B reads matching poisoned bytecode")
            probe.unlink()
            compatible = module["python_compatible"]
            module["python_compatible"] = lambda candidate: (
                False if candidate == Path(sys.executable) else compatible(candidate))
            module["download_file"] = lambda *args: self.fail("Valid private sources must be reused offline")
            with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}):
                self.assertEqual(module["ensure_python"](cache), python)
            self.assertEqual(probe.read_text(), "1", "Private compatibility check executed untrusted cached code")
            self.assertEqual(list(private.rglob("*.pyc")), [], "Private Python must not regenerate bytecode under -I")
            self.assertEqual(list(private.rglob("__pycache__")), [])
            self.assertEqual(outside.read_bytes(), b"must not touch host or unrelated bytecode")
            self.assertEqual(module["read_json"](cache / "python-ready.json"), state)


    def test_dxc_wrapper_executes_selected_proton_wine_in_private_prefix_with_windows_paths(self):
        module = setup_module()
        self.assertTrue(callable(module.get("ensure_tools")), "DXC needs automatic Proton/Wine provisioning")
        with tempfile.TemporaryDirectory(prefix="helixsr wine ") as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            proton = root / "actual proton"
            wine = proton / "files/bin/wine64"
            wine.parent.mkdir(parents=True)
            wine.write_text("#!" + sys.executable + " -I\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ['FIXTURE_RESULT']).write_text(json.dumps(dict(args=sys.argv[1:], prefix=os.environ['WINEPREFIX'], debug=os.environ['WINEDEBUG'])))\n")
            wine.chmod(0o755)
            archive = root / "fixture.zip"
            zip_fixture(archive, {"bin\\x64\\dxc.exe": b"offline non-executable compiler", "bin\\x64\\dxcompiler.dll": b"compiler dependency", "bin\\x64\\dxil.dll": b"validator dependency", "LICENSE-MS.txt": b"retain license"})
            payload = archive.read_bytes()
            module["DXC_SHA"] = hashlib.sha256(payload).hexdigest()
            module["download_file"] = lambda url, destination: destination.write_bytes(payload)
            module["ensure_python"] = lambda path: Path("/fixture/python3")
            result = root / "result.json"
            env = {"HOME": str(root), "STEAM_COMPAT_TOOL_PATHS": str(root / "not-proton") + ":" + str(proton), "WINEPREFIX": "/game/prefix", "FIXTURE_RESULT": str(result), "PYTHONHOME": str(root / "game bundled python")}
            with patch.dict(module["os"].environ, env):
                python, wrapper = module["ensure_tools"](cache)
                self.assertEqual(python, Path("/fixture/python3"))
                self.assertEqual((cache / "dxc/bin/x64/dxcompiler.dll").read_bytes(), b"compiler dependency")
                self.assertEqual((cache / "dxc/LICENSE-MS.txt").read_bytes(), b"retain license")
                source, output = root / "input shader.hlsl", root / "output shader.cso"
                executed = module["subprocess"].run([str(wrapper), "-T", "cs_6_6", "-Fo", str(output), str(source), "PX_FAST=1"], capture_output=True, text=True)
                self.assertEqual(executed.returncode, 0, "DXC wrapper must ignore game Python settings: " + executed.stderr)
                report = json.loads(result.read_text())
                windows = lambda path: "Z:" + str(path).replace("/", "\\")
                self.assertEqual(report["args"], [windows(cache / "dxc/bin/x64/dxc.exe"), "-T", "cs_6_6", "-Fo", windows(output), windows(source), "PX_FAST=1"])
                self.assertEqual(report["prefix"], str(cache / "wineprefix"))
                self.assertEqual(report["debug"], "-all")


    def test_runtime_helpers_have_no_desktop_dialog_dependency(self):
        import re
        for path in (ROOT / "recipes/helixsr").rglob("*.sh"):
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(r"zenity|kdialog|--question|--yesno|--msgbox|--progress", path.read_text(), re.I))


    def test_version_cache_is_exclusively_locked_through_readiness_publication(self):
        import fcntl
        module = setup_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            def provision(cache):
                with (cache / "setup.lock").open("a") as contender:
                    with self.assertRaises(BlockingIOError, msg="A second toggle must not enter provisioning"):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFalse(Path(str(runtime) + ".setup").exists())
                return cache / "HelixSR-1.9.0"
            module["provision"] = provision
            with patch.dict(module["os"].environ, {"HOME": str(root), "DLOR_HELIXSR_RUNTIME_FILE": str(runtime)}, clear=True):
                output = module["run_setup"]()
            self.assertEqual(output, root / ".dlor/cache/helixsr/1.9.0/HelixSR-1.9.0")
            self.assertEqual(Path(str(runtime) + ".setup").read_text(), "ready")


    def test_download_build_failure_and_invalid_output_never_publish_runtime_readiness(self):
        module = fixture_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            success = Path(str(runtime) + ".setup")
            archive = root / "fixture.zip"
            zip_fixture(archive, {"HelixSR-1.9.0/setup/helixsr_setup.py": b"# offline fixture", "HelixSR-1.9.0/amd_fidelityfx_dx12.dll": b"MZ unbuilt"})
            payload = archive.read_bytes()
            module["RELEASE_SHA"] = hashlib.sha256(payload).hexdigest()
            module["DLSS_SHA"] = hashlib.sha256(b"offline DLL").hexdigest()
            def download(url, destination):
                destination.write_bytes(payload if url == module["RELEASE_URL"] else b"offline DLL")
            module["ensure_tools"] = lambda cache: (Path("/fixture/python3"), cache / "wrapper")
            env = {"HOME": str(root), "DLOR_HELIXSR_RUNTIME_FILE": str(runtime)}
            with patch.dict(module["os"].environ, env, clear=True):
                success.write_text("ready")
                with patch.dict(module, download_file=lambda *args: (_ for _ in ()).throw(OSError("fixture transfer failed"))):
                    with self.assertRaisesRegex(OSError, "transfer failed"):
                        module["run_setup"]()
                self.assertFalse(success.exists())
                module["download_file"] = download
                for fault in (module["subprocess"].CalledProcessError(1, "fixture-build"), None):
                    success.write_text("ready")
                    with patch.object(module["subprocess"], "run", side_effect=fault) as run:
                        with self.assertRaises((module["subprocess"].CalledProcessError, ValueError)):
                            module["run_setup"]()
                    self.assertTrue(run.called)
                    self.assertFalse(success.exists())
                    self.assertFalse((root / ".dlor/cache/helixsr/1.9.0/ready.json").exists())

    def test_prebuilt_override_is_validated_without_download_or_build(self):
        module = fixture_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "already built output"
            built_fixture(output, module["DLSS_SHA"])
            runtime = root / "runtime"
            def forbidden(*args, **kwargs):
                self.fail("Prebuilt output must not build or download")
            module.update(download_file=forbidden, ensure_tools=forbidden)
            with patch.dict(module["os"].environ, {"HOME": str(root), "HELIXSR_DIR": str(output), "DLOR_HELIXSR_RUNTIME_FILE": str(runtime)}, clear=True):
                self.assertEqual(module["run_setup"](), output)
                self.assertEqual(Path(str(runtime) + ".setup").read_text(), "ready")
                (output / "amd_fidelityfx_dx12.dll").write_bytes(b"MZ unbuilt")
                with self.assertRaises(ValueError):
                    module["run_setup"]()
                self.assertFalse(Path(str(runtime) + ".setup").exists())

    def test_rejected_download_does_not_replace_good_cache_and_cleans_partial_files(self):
        module = setup_module()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "archive.zip"
            destination.write_bytes(b"old invalid fixture")
            module["download_file"] = lambda url, path: path.write_bytes(b"wrong bytes")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                module["cached_download"](destination, "https://fixture.invalid/test", hashlib.sha256(b"expected").hexdigest())
            self.assertEqual(destination.read_bytes(), b"old invalid fixture")
            self.assertEqual([path.name for path in destination.parent.iterdir()], ["archive.zip"])
            def failed(url, path):
                path.write_bytes(b"partial")
                raise OSError("offline transfer failed")
            module["download_file"] = failed
            with self.assertRaises(OSError):
                module["cached_download"](destination, "https://fixture.invalid/test", "unused")
            self.assertEqual([path.name for path in destination.parent.iterdir()], ["archive.zip"])

    def test_discovers_proton_from_custom_steam_library_then_wine_fallback(self):
        module = setup_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steam = root / ".local/share/Steam"
            (steam / "steamapps").mkdir(parents=True)
            library = root / "custom library"
            wine = library / "steamapps/common/Proton Fixture/files/bin/wine"
            wine.parent.mkdir(parents=True)
            wine.write_text("offline fixture")
            wine.chmod(0o755)
            (steam / "steamapps/libraryfolders.vdf").write_text('"libraryfolders" { "1" { "path" "' + str(library) + '" } }')
            with patch.dict(module["os"].environ, {"HOME": str(root)}, clear=True), patch.object(module["shutil"], "which", return_value="/fixture/wine64"):
                self.assertEqual(module["find_wine"](), wine)
                wine.unlink()
                self.assertEqual(module["find_wine"](), Path("/fixture/wine64"))
            with patch.dict(module["os"].environ, {"HOME": str(root)}, clear=True), patch.object(module["shutil"], "which", return_value=None):
                with self.assertRaises(RuntimeError):
                    module["find_wine"]()


    def test_shell_bootstrap_ignores_game_pythonhome_and_clears_stale_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game").mkdir()
            runtime = root / "runtime"
            success = Path(str(runtime) + ".setup")
            success.write_text("ready")
            env = dict(os.environ, HOME=str(root), HELIXSR_DIR=str(root / "missing prebuilt output"),
                       HELIXSR_CACHE_DIR=str(root / "cache"), DLOR_HELIXSR_RUNTIME_FILE=str(runtime),
                       PYTHONHOME=str(root / "game bundled python"))
            result = subprocess.run(["bash", str(SETUP), str(root / "game")], env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Incomplete HelixSR output", result.stdout + result.stderr,
                          "Bootstrap Python must ignore game PYTHONHOME before using the isolated cache")
            self.assertFalse(success.exists())
            self.assertTrue(list((root / ".dlor/logs/helixsr/setup").glob("*.log")))


    def test_invalid_arguments_clear_stale_runtime_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            file = root / "not-a-directory"
            file.write_text("fixture")
            runtime = root / "runtime"
            success = Path(str(runtime) + ".setup")
            env = dict(os.environ, HOME=str(root), DLOR_HELIXSR_RUNTIME_FILE=str(runtime))
            for args in ([], [""], [str(game), "extra"], [str(root / "missing")], [str(file)]):
                with self.subTest(args=args):
                    success.write_text("ready")
                    result = subprocess.run(["bash", str(SETUP), *args], env=env,
                                            capture_output=True, text=True, timeout=15)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(success.exists(), "Rejected setup must not leave stale readiness")


if __name__ == "__main__":
    unittest.main()
