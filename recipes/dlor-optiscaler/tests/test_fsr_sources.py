"""Synthetic payloads exercise source selection and real ownership transactions."""
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
DLL = "amd_fidelityfx_upscaler_dx12.dll"


class FsrSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.game = self.root / "game"
        self.target = self.game / "nested renderer"
        self.target.mkdir(parents=True)
        self.core = self.root / "core"
        (self.core / "OptiScaler").mkdir(parents=True)
        (self.core / "OptiScaler.dll").write_bytes(b"synthetic injector")
        self.ini = b"[Libraries]\nOptiDllPath=auto\nFfxDx12SRPath=auto\n[Plugins]\nPath=auto\nLoadAsiPlugins=false\n[FSR]\nFsr4GpuSupport=auto\n"
        (self.core / "OptiScaler.ini").write_bytes(self.ini)
        (self.core / "OptiScaler" / DLL).write_bytes(b"synthetic bundled SDK")
        self.assets = {}
        self.payloads = {}
        self.packages = {}
        self.requests = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sys, "path", [str(HERE / "scripts"), *sys.path]))
        spec = importlib.util.spec_from_file_location("fsr_installer", HERE / "scripts/installer.py")
        assert spec is not None and spec.loader is not None
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        import artifacts
        import game_discovery
        self.real_download = artifacts.download_asset
        self.stack.enter_context(patch.object(artifacts, "resolve_asset", side_effect=self.resolve))
        self.stack.enter_context(patch.object(artifacts, "download_asset", side_effect=self.download))
        self.stack.enter_context(patch.object(self.installer, "cached_package", side_effect=lambda asset, cache: self.core if asset["repository"] == "optiscaler/OptiScaler-nightly" else self.packages[asset["sha256"]]))
        self.stack.enter_context(patch.object(game_discovery, "discover_game_directory", return_value=self.target))
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.home)}, clear=True))
        self.add_asset("optiscaler/OptiPatcher", "stable", "OptiPatcher_v0.42.asi", b"synthetic ASI")
        self.add_asset("optiscaler/OptiScaler-nightly", "nightly", "OptiScaler.7z", b"synthetic core archive")
        self.add_asset("xXJSONDeruloXx/OptiScaler-Bleeding-Edge", "tag:opti-9-2-a", DLL, b"synthetic legacy upscaler")

    def add_asset(self, repository, channel, name, data):
        sha = hashlib.sha256(data).hexdigest()
        path = self.root / "payloads" / sha / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        asset = {"repository": repository, "tag": channel.removeprefix("tag:"), "name": name,
                 "sha256": sha, "size": len(data), "url": f"https://github.com/{repository}/releases/download/fixture/{name}"}
        self.assets[(repository, channel, name)] = asset
        self.payloads[sha] = path
        return asset

    def resolve(self, repository, channel, pattern, cache, **kwargs):
        import re
        self.requests.append((repository, channel, kwargs))
        matches = [asset for (repo, selected_channel, name), asset in self.assets.items()
                   if (repo, selected_channel) == (repository, channel) and re.fullmatch(pattern, name)]
        self.assertEqual(len(matches), 1)
        asset = matches[0]
        return dict(asset)

    def download(self, asset, cache):
        return self.payloads[asset["sha256"]]

    def run_action(self, action, profile=None):
        os.environ.pop("DLOR_OPTISCALER_FSR_PROFILE", None)
        os.environ.pop("DLOR_OPTISCALER_LATEST", None)
        if profile is not None:
            os.environ["DLOR_OPTISCALER_FSR_PROFILE"] = profile
        return self.installer.main([action, str(self.game)])

    def state(self):
        return json.loads(next((self.home / ".dlor/state/dlor-optiscaler").glob("*/state.json")).read_bytes())

    def add_optimized(self, family="igpu-rdna2", variant="exact"):
        date, version = "2026-11-05", "4.1.2"
        self.add_asset("zgauthier2000/fsr4-shader-performance-overrides", "tag:dll-" + date,
                       "LICENSE", b"synthetic GPL license")
        flavor = family.replace("igpu-", "igpu-cyboman-") if family.startswith("igpu-") else "cyboman-" + family
        name = f"fsr{version}-{flavor}-{date}.7z"
        asset = self.add_asset("zgauthier2000/fsr4-shader-performance-overrides", "tag:dll-" + date, name, ("synthetic archive " + family + date).encode())
        directory = self.root / "packages" / asset["sha256"]
        directory.mkdir(parents=True, exist_ok=True)
        contents = {
            "exact/" + DLL: b"synthetic optimized exact",
            "lossy/" + DLL: b"synthetic optimized lossy",
            "4.1.2l-exact/" + DLL: b"synthetic unselected Lite exact",
            "4.1.2l-lossy/" + DLL: b"synthetic unselected Lite lossy",
            "NOTICE.md": b"synthetic AMD and shader notices",
            "lossy/WARNING.txt": b"synthetic lossy warning",
            "4.1.2l-lossy/WARNING.txt": b"synthetic unselected Lite warning",
        }
        for member, data in contents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.packages[asset["sha256"]] = directory
        return asset

    def test_optimized_exact_selects_one_member_and_restores_bundled_files(self):
        asset = self.add_optimized()
        self.assertEqual(self.run_action("install", "bundled"), 0)
        self.assertEqual(self.run_action("install", "zgauthier-igpu-rdna2-exact"), 0)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic optimized exact")
        provenance = self.state()["components"][-1]
        self.assertEqual(provenance["sha256"], asset["sha256"])
        self.assertEqual(provenance["fsr_profile"], "zgauthier-igpu-rdna2-exact")
        self.assertEqual(provenance["fsr_members"][DLL], {"path": "exact/" + DLL, "sha256": hashlib.sha256(b"synthetic optimized exact").hexdigest()})
        notice = self.target / "OptiScaler/licenses/fsr-profile/NOTICE.md"
        self.assertEqual(notice.read_bytes(), b"synthetic AMD and shader notices")
        self.assertFalse(list(self.target.rglob("WARNING.txt")))
        self.assertFalse((self.target / "OptiScaler/exact").exists())
        self.assertEqual((self.target / "OptiScaler.ini").read_bytes(), self.ini.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
        self.assertEqual(self.run_action("install", "bundled"), 0)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic bundled SDK")
        self.assertFalse(notice.exists())
        self.assertEqual(self.run_action("uninstall"), 0)
        self.assertEqual(list(self.game.rglob("*.dll")), [])

    def test_every_optimized_gpu_variant_retains_exact_member_on_standalone_upgrade(self):
        for family in ("rx6000", "rx7000", "igpu-rdna2", "igpu-rdna3"):
            for variant in ("exact", "lossy"):
                with self.subTest(family=family, variant=variant):
                    asset = self.add_optimized(family, variant)
                    profile = f"zgauthier-{family}-{variant}"
                    self.assertEqual(self.run_action("install", profile), 0)
                    self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), ("synthetic optimized " + variant).encode())
                    before = self.state()["components"][-1]
                    self.assertEqual(before["fsr_profile"], profile)
                    self.assertEqual(before["tag"], "dll-2026-11-05")
                    warnings = list(self.target.rglob("WARNING.txt"))
                    self.assertEqual(len(warnings), 0 if variant == "exact" else 1)
                    if warnings:
                        self.assertEqual(warnings[0].read_bytes(), ("synthetic " + variant + " warning").encode())
                    self.assets[(asset["repository"], "tag:" + asset["tag"], asset["name"])] = {**asset, "sha256": "b" * 64}
                    self.requests.clear()
                    self.assertEqual(self.run_action("upgrade"), 0)
                    self.assertEqual(self.state()["components"][-1], before)
                    self.assertEqual(len(self.requests), 2)
                    self.assertEqual(self.run_action("install", "bundled"), 0)
                    self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic bundled SDK")
                    self.assertFalse(list(self.target.rglob("NOTICE.md")))
                    self.assertFalse(list(self.target.rglob("WARNING.txt")))
                    self.assertEqual(self.run_action("uninstall"), 0)

    def test_legacy_unmarked_profile_provenance_survives_standalone_upgrade(self):
        self.assertEqual(self.run_action("install", "rdna23-int8"), 0)
        journal = next((self.home / ".dlor/state/dlor-optiscaler").glob("*/state.json"))
        state = self.state()
        state["components"][-1].pop("fsr_profile")
        original = dict(state["components"][-1])
        journal.write_text(json.dumps(state))
        self.add_asset("xXJSONDeruloXx/OptiScaler-Bleeding-Edge", "tag:opti-9-2-a", DLL, b"changed current manifest")
        self.assertEqual(self.run_action("upgrade"), 0)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic legacy upscaler")
        self.assertEqual(self.state()["components"][-1], {**original, "fsr_profile": "rdna23-int8"})

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for base in (self.game, self.home / ".dlor/state") if base.exists()
                for path in base.rglob("*") if path.is_file() and path.name != "lock"}

    def test_profile_custom_fsr_library_paths_preserve_ini_and_restore_foreign_original(self):
        self.add_optimized()
        for path_value, relative in (("custom fsr/Selected.DLL", "custom fsr/Selected.DLL"),
                                     (str(self.game / "absolute fsr"), "absolute fsr/" + DLL)):
            with self.subTest(path=relative):
                ini = self.target / "OptiScaler.ini"
                original = self.ini.replace(b"FfxDx12SRPath=auto", ("FfxDx12SRPath=" + path_value).encode())
                ini.write_bytes(original)
                destination = self.game / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"foreign library original")
                with patch.object(os, "getcwd", return_value=str(self.game)):
                    self.assertEqual(self.run_action("install", "zgauthier-igpu-rdna2-exact"), 0)
                    self.assertEqual(destination.read_bytes(), b"synthetic optimized exact")
                    self.assertEqual(ini.read_bytes(), original.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
                    self.assertFalse((self.target / "OptiScaler" / DLL).exists())
                    self.assertEqual(self.run_action("uninstall"), 0)
                self.assertEqual(destination.read_bytes(), b"foreign library original")
                self.assertEqual(ini.read_bytes(), original)
                destination.unlink()
                ini.unlink()

    def test_changed_owned_fsr_library_refuses_switch_without_other_writes(self):
        self.add_optimized()
        self.run_action("install", "zgauthier-igpu-rdna2-exact")
        library = self.target / "OptiScaler" / DLL
        library.write_bytes(b"user edited FSR library")
        before = self.snapshot()
        with self.assertRaisesRegex(self.installer.InstallerError, "changed outside"):
            self.run_action("install", "bundled")
        self.assertEqual(self.snapshot(), before)
        self.run_action("uninstall")
        self.assertEqual(library.read_bytes(), b"user edited FSR library")

    def test_switch_preserves_changed_obsolete_profile_notice(self):
        self.add_optimized(variant="lossy")
        self.run_action("install", "zgauthier-igpu-rdna2-lossy")
        warning = self.target / "OptiScaler/licenses/fsr-profile/WARNING.txt"
        warning.write_bytes(b"user annotated warning")
        self.run_action("install", "bundled")
        self.assertTrue(warning.is_file(), "Changed obsolete warning must survive the switch")
        self.assertEqual(warning.read_bytes(), b"user annotated warning")
        self.assertFalse((warning.parent / "NOTICE.md").exists())
        self.run_action("uninstall")
        self.assertEqual(warning.read_bytes(), b"user annotated warning")

    def test_foreign_proxy_collision_refuses_before_acquisition(self):
        self.add_optimized()
        (self.target / "dxgi.dll").write_bytes(b"foreign injection mod")
        before = self.snapshot()
        with self.assertRaisesRegex(self.installer.InstallerError, "occupied"):
            self.run_action("install", "zgauthier-igpu-rdna2-exact")
        self.assertEqual(self.requests, [])
        self.assertEqual(self.snapshot(), before)

    def test_missing_selected_archive_member_fails_before_game_or_state_writes(self):
        asset = self.add_optimized()
        self.run_action("install", "bundled")
        (self.packages[asset["sha256"]] / "exact" / DLL).unlink()
        before = self.snapshot()
        with self.assertRaisesRegex(self.installer.InstallerError, "member is missing"):
            self.run_action("install", "zgauthier-igpu-rdna2-exact")
        self.assertEqual(self.snapshot(), before)

    def test_off_with_profile_never_resolves_downloads_or_extracts_payloads(self):
        self.add_optimized(variant="lossy")
        self.run_action("install", "zgauthier-igpu-rdna2-lossy")
        import artifacts
        with patch.object(artifacts, "resolve_asset", side_effect=AssertionError("OFF resolved payload")), patch.object(artifacts, "download_asset", side_effect=AssertionError("OFF downloaded payload")), patch.object(self.installer, "cached_package", side_effect=AssertionError("OFF extracted payload")):
            self.assertEqual(self.run_action("uninstall", "zgauthier-igpu-rdna2-lossy"), 0)
        self.assertEqual([p for p in self.game.rglob("*") if p.is_file()], [])
        self.assertEqual(self.state()["files"], {})

    def test_optimized_installs_gpl_license_and_removes_it_on_return_to_bundled(self):
        self.add_optimized()
        self.run_action("install", "zgauthier-igpu-rdna2-exact")
        license_path = self.target / "OptiScaler/licenses/fsr-profile/zgauthier-LICENSE"
        self.assertTrue(license_path.is_file(), "Optimized source must include its GPL license")
        self.assertEqual(license_path.read_bytes(), b"synthetic GPL license")
        self.assertEqual([c["name"] for c in self.state()["components"]][-2:],
                         ["LICENSE", "fsr4.1.2-igpu-cyboman-rdna2-2026-11-05.7z"])
        self.run_action("install", "bundled")
        self.assertFalse(license_path.exists())

    def add_sdk(self):
        repository = "GPUOpen-LibrariesAndSDKs/FidelityFX-SDK"
        license_asset = self.add_asset(repository, "tag:v2.4.0", "license.md", b"synthetic full AMD license")
        upscaler = self.add_asset(repository, "tag:v2.4.0", DLL, b"synthetic SDK 2.4.0")
        return license_asset, upscaler

    def test_bundled_sdk_optimized_bundled_lifecycle_keeps_provenance_and_cleans_obsolete_files(self):
        license_asset, sdk = self.add_sdk()
        self.add_optimized(variant="lossy")
        self.run_action("install", "bundled")
        self.assertEqual(self.run_action("install", "sdk-amd"), 0)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic SDK 2.4.0")
        license_path = self.target / "OptiScaler/licenses/fsr-profile/AMD-FidelityFX-SDK-LICENSE.md"
        self.assertEqual(license_path.read_bytes(), b"synthetic full AMD license")
        installed = self.state()["components"][-2:]
        self.assertEqual(installed, [{**license_asset, "fsr_profile": "sdk-amd"}, {**sdk, "fsr_profile": "sdk-amd"}])
        self.add_asset(sdk["repository"], "tag:v2.4.0", DLL, b"changed SDK pin")
        self.requests.clear()
        self.assertEqual(self.run_action("upgrade"), 0)
        self.assertEqual(self.state()["components"][-2:], installed)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic SDK 2.4.0")
        self.run_action("install", "zgauthier-igpu-rdna2-lossy")
        self.assertFalse(license_path.exists())
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic optimized lossy")
        self.run_action("install", "bundled")
        self.assertFalse([p for p in self.target.rglob("*LICENSE*") if p.is_file()])
        self.assertFalse(list(self.target.rglob("WARNING.txt")))
        self.assertFalse(list(self.target.rglob("NOTICE.md")))
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic bundled SDK")
        self.assertEqual((self.target / "OptiScaler.ini").read_bytes(), self.ini.replace(b"LoadAsiPlugins=false", b"LoadAsiPlugins=true"))
        self.run_action("uninstall")
        self.assertEqual([p for p in self.game.rglob("*") if p.is_file()], [])

    def test_standalone_upgrade_with_same_explicit_source_keeps_installed_pins(self):
        self.add_sdk()
        self.run_action("install", "sdk-amd")
        original = self.state()["components"][-2:]
        self.add_asset("GPUOpen-LibrariesAndSDKs/FidelityFX-SDK", "tag:v2.4.0", DLL, b"changed SDK pin")
        self.run_action("upgrade", "sdk-amd")
        self.assertEqual(self.state()["components"][-2:], original)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic SDK 2.4.0")
        self.run_action("upgrade", "bundled")
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic bundled SDK")
        self.assertFalse(list(self.target.rglob("*LICENSE*")))

    def test_failed_profile_switch_rolls_back_files_and_exact_component_provenance(self):
        self.add_sdk()
        self.add_optimized()
        self.run_action("install", "sdk-amd")
        before = {p.relative_to(self.game).as_posix(): p.read_bytes() for p in self.game.rglob("*") if p.is_file()}
        state = self.state()
        write = self.installer.atomic_write
        license_path = self.target / "OptiScaler/licenses/fsr-profile/zgauthier-LICENSE"

        def interrupted(path, data, mode=0o600):
            if path == license_path:
                raise OSError("controlled interruption during profile transaction")
            return write(path, data, mode)

        with patch.object(self.installer, "atomic_write", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "controlled interruption"):
                self.run_action("install", "zgauthier-igpu-rdna2-exact")
        self.assertEqual({p.relative_to(self.game).as_posix(): p.read_bytes() for p in self.game.rglob("*") if p.is_file()}, before)
        self.assertEqual(self.state(), state)
        self.run_action("install", "zgauthier-igpu-rdna2-exact")
        self.run_action("uninstall")
        self.assertEqual([p for p in self.game.rglob("*") if p.is_file()], [])

    def test_corrupt_profile_provenance_refuses_upgrade_without_writes(self):
        self.add_optimized()
        self.run_action("install", "zgauthier-igpu-rdna2-exact")
        journal = next((self.home / ".dlor/state/dlor-optiscaler").glob("*/state.json"))
        original = journal.read_bytes()
        for corruption in ("missing-license", "member-digest", "mixed-profiles"):
            with self.subTest(corruption=corruption):
                state = json.loads(original)
                if corruption == "missing-license":
                    state["components"] = [c for c in state["components"] if c["name"] != "LICENSE"]
                elif corruption == "member-digest":
                    state["components"][-1]["fsr_members"][DLL]["sha256"] = "0" * 64
                else:
                    state["components"][-2]["fsr_profile"] = "sdk-amd"
                journal.write_text(json.dumps(state))
                before = self.snapshot()
                with self.assertRaisesRegex(self.installer.InstallerError, "provenance|Ambiguous"):
                    self.run_action("upgrade")
                self.assertEqual(self.snapshot(), before)
        journal.write_bytes(original)

    def test_retained_profile_reuses_canonical_verified_download_cache_offline(self):
        self.add_sdk()
        self.run_action("install", "sdk-amd")
        import artifacts
        cache = self.home / ".dlor/cache/dlor-optiscaler/artifacts"
        for asset in self.assets.values():
            path = artifacts._asset_path(asset, cache)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.payloads[asset["sha256"]].read_bytes())
        with patch.object(artifacts, "download_asset", side_effect=self.real_download), patch.object(artifacts, "_open", side_effect=AssertionError("Verified retained payload should be reused offline")):
            self.assertEqual(self.run_action("upgrade"), 0)
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic SDK 2.4.0")

    def test_standalone_upgrade_keeps_profile_descriptor_not_current_manifest(self):
        self.assertEqual(self.run_action("install", "rdna23-int8"), 0)
        before = self.state()["components"][-1]
        self.assertEqual(before.get("fsr_profile"), "rdna23-int8")
        self.add_asset("xXJSONDeruloXx/OptiScaler-Bleeding-Edge", "tag:opti-9-2-a", DLL, b"different reviewed pin")
        self.requests.clear()
        (self.core / "OptiScaler.dll").write_bytes(b"synthetic fresh injector")
        self.assertEqual(self.run_action("upgrade"), 0)
        self.assertEqual((self.target / "dxgi.dll").read_bytes(), b"synthetic fresh injector")
        self.assertEqual((self.target / "OptiScaler" / DLL).read_bytes(), b"synthetic legacy upscaler")
        self.assertEqual(self.state()["components"][-1], before)
        self.assertEqual(self.requests, [("optiscaler/OptiScaler-nightly", "nightly", {"fresh": True}),
                                         ("optiscaler/OptiPatcher", "stable", {})])
        self.assertEqual(self.run_action("uninstall"), 0)
        self.assertEqual(list(self.game.rglob("*.dll")), [])
