"""Local discovery tests. PE fixtures are SYNTHETIC, not real-game evidence."""
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import game_discovery as discovery  # pyright: ignore[reportMissingImports]


def synthetic_pe(imports=("d3d12.dll",), *, machine=0x8664, characteristics=0x22):
    """Construct tiny PE32+ metadata; this is NOT an executable game payload."""
    data = bytearray(0x800)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, machine, 1, 0, 0, 0, 0xF0, characteristics)
    struct.pack_into("<H", data, 0x98, 0x20B)
    struct.pack_into("<II", data, 0x98 + 56, 0x2000, 0x200)
    struct.pack_into("<I", data, 0x98 + 108, 16)
    if imports:
        struct.pack_into("<II", data, 0x98 + 120, 0x1000, (len(imports) + 1) * 20)
    struct.pack_into("<8sIIIIIIHHI", data, 0x188, b".rdata\0\0", 0x600, 0x1000, 0x600, 0x200, 0, 0, 0, 0, 0x40000040)
    name_offset = 0x400
    for index, name in enumerate(imports):
        struct.pack_into("<IIIII", data, 0x200 + index * 20, 0, 0, 0, name_offset + 0xE00, 0x1400)
        encoded = name.encode("ascii") + b"\0"
        data[name_offset:name_offset + len(encoded)] = encoded
        name_offset += len(encoded)
    return bytes(data)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Selected Game"
        self.root.mkdir()

    def file(self, relative, data=b""):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_case_insensitive_safe_path_preserves_disk_spelling(self):
        target = self.file("Odd Folder/Grüße/OpTiScAlEr.InI")
        self.assertIsNotNone(discovery, "game_discovery implementation is missing")
        self.assertEqual(discovery.safe_path(self.root, "odd folder\\GRÜSSE\\optiscaler.ini"), target)
        self.assertEqual(discovery.safe_path(self.root, "odd FOLDER/New.dll"), target.parent.parent / "New.dll")

    def test_safe_path_rejects_unsafe_or_ambiguous_targets(self):
        self.file("Render/game.exe")
        self.file("render/other.exe")
        external = Path(self.temp.name) / "external"
        external.mkdir()
        (self.root / "link").symlink_to(external, target_is_directory=True)
        (self.root / "filelink").symlink_to(self.file("original"))
        for value in ("../escape", "sub/../../escape", "/absolute", "C:\\outside", "\\\\server\\share", "render/game.exe", "link/a", "filelink", "original/child", "bad\x00name"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    discovery.safe_path(self.root, value)
        with self.assertRaises(ValueError):
            discovery.safe_path(self.root, "not-created", allow_missing=False)

    def test_safe_path_accepts_external_root_symlink(self):
        self.file("Data/item")
        alias = Path(self.temp.name) / "steam-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(discovery.safe_path(alias, "data/item"), self.root / "Data/item")

    def test_unique_ini_wins_over_misleading_launch_executable(self):
        ini = self.file("任意 project/strange WinGDK folder/OpTiScaler.INI")
        launcher = self.file("launcher.exe", b"not even a PE")
        self.assertTrue(hasattr(discovery, "discover_ini"), "INI discovery is missing")
        self.assertTrue(hasattr(discovery, "discover_game_directory"), "game discovery is missing")
        self.assertEqual(discovery.discover_ini(self.root), ini)
        self.assertEqual(discovery.discover_game_directory(self.root, [str(launcher)]), ini.parent)

    def test_ini_scan_rejects_case_colliding_ancestors_and_internal_links(self):
        for kind in ("collision", "directory-link", "file-link"):
            with self.subTest(kind=kind):
                root = self.root / kind
                root.mkdir()
                if kind == "collision":
                    (root / "Render").mkdir()
                    (root / "render").mkdir()
                    (root / "Render/OptiScaler.ini").touch()
                elif kind == "directory-link":
                    outside = Path(self.temp.name) / "outside"
                    outside.mkdir()
                    (outside / "OptiScaler.ini").touch()
                    (root / "link").symlink_to(outside, target_is_directory=True)
                else:
                    (root / "actual.ini").touch()
                    (root / "OptiScaler.ini").symlink_to(root / "actual.ini")
                with self.assertRaises(ValueError):
                    discovery.discover_ini(root)
                with self.assertRaises(ValueError):
                    discovery.discover_game_directory(root, [])

    def test_fresh_generic_install_uses_amd64_graphics_import_evidence(self):
        game = self.file("arbitrary/deeply nested/Grüße 空間/Actual.EXE", synthetic_pe(("KERNEL32.dll", "D3D11.DLL")))
        self.file("big.exe", b"not a PE" * 10000)
        self.file("tools/foreign.exe", synthetic_pe(machine=0x14C))
        self.file("helpers/helper.exe", synthetic_pe(("KERNEL32.dll",)))
        self.file("helpers/a-dll.exe", synthetic_pe(characteristics=0x2022))
        other_game = Path(self.temp.name) / "Different install"
        other_game.mkdir()
        (other_game / "OptiScaler.ini").touch()
        (other_game / "link").symlink_to(self.root, target_is_directory=True)
        self.assertIsNone(discovery.discover_ini(self.root))
        self.assertEqual(discovery.discover_game_directory(self.root, []), game.parent)

    def test_main_argv_renderer_disambiguates_without_choosing_argument_exe(self):
        main = self.file("任意/Main Folder/Actual.EXE", synthetic_pe())
        other = self.file("different/other.exe", synthetic_pe(("vulkan-1.dll",)))
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [])
        argv = ["/some/proton", "waitforexitandrun", "任意\\main folder\\actual.exe", "--helper", str(other)]
        self.assertEqual(discovery.discover_game_directory(self.root, argv), main.parent)
        self.assertEqual(discovery.discover_game_directory(self.root, [str(other)]), other.parent)
        foreign = self.file("runtime/foreign.exe", synthetic_pe(machine=0xAA64))
        invalid = self.file("runtime/not-a-pe.exe", b"not executable")
        self.assertEqual(discovery.discover_game_directory(self.root, [str(foreign), str(invalid), *argv]), main.parent)

    def test_unreal_bootstrap_selects_unique_nested_shipping_for_win64_or_wingdk(self):
        for platform in ("Win64", "WinGDK"):
            with self.subTest(platform=platform):
                root = self.root / platform
                bootstrap = self.file(f"{platform}/Project Space.exe", synthetic_pe())
                shipping = self.file(f"{platform}/Unrelated Ω project/arbitrary binaries/{platform}/Project Space-{platform}-Shipping.EXE", synthetic_pe(("KERNEL32.dll",)))
                self.assertEqual(discovery.discover_game_directory(root, [str(bootstrap)]), shipping.parent)
                self.assertEqual(discovery.discover_game_directory(root, []), shipping.parent)

    def test_multiple_ini_anchors_require_colocated_renderer_context(self):
        first = self.file("edition A/run/OptiScaler.ini")
        second = self.file("edition B/run/optiscaler.INI")
        main = self.file("edition A/run/game.exe", synthetic_pe())
        self.file("edition B/run/other.exe", synthetic_pe())
        with self.assertRaises(ValueError):
            discovery.discover_ini(self.root)
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [])
        self.assertEqual(discovery.discover_ini(self.root, main), first)
        self.assertEqual(discovery.discover_ini(self.root, second.parent), second)
        self.assertEqual(discovery.discover_game_directory(self.root, [str(main)]), first.parent)
        elsewhere = self.file("unassociated/game.exe", synthetic_pe())
        with self.assertRaises(ValueError):
            discovery.discover_ini(self.root, elsewhere)

    def test_advanced_executable_override_is_local_validated_and_optional(self):
        main = self.file("main/game.exe", synthetic_pe())
        dynamic = self.file("custom/renderer.exe", synthetic_pe(("KERNEL32.dll",)))
        self.assertEqual(discovery.discover_game_directory(self.root, [str(main)], executable="CUSTOM\\RENDERER.EXE"), dynamic.parent)
        bad = self.file("not-a-pe.exe", b"arbitrary")
        x86 = self.file("32bit.exe", synthetic_pe(machine=0x14C))
        for override in ("../outside.exe", str(Path(self.temp.name) / "outside.exe"), "C:\\other.exe", "missing.exe", str(bad), str(x86), "custom"):
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    discovery.discover_game_directory(self.root, [str(main)], executable=override)

    def test_unassociated_bootstrap_cannot_hide_ambiguous_nested_renderers(self):
        launcher = self.file("unknown-launcher.exe", synthetic_pe())
        self.file("arbitrary project/a/Project-Win64-Shipping.exe", synthetic_pe())
        self.file("other project/b/Other-WinGDK-Shipping.exe", synthetic_pe())
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [str(launcher)])
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [])

    def test_symlinked_steam_parent_preserves_absolute_argv_disambiguation(self):
        main = self.file("install/alpha/game.exe", synthetic_pe())
        self.file("install/beta/other.exe", synthetic_pe())
        alias = Path(self.temp.name) / "library alias"
        alias.symlink_to(self.root, target_is_directory=True)
        selected = alias / "install"
        launched = selected / "alpha/game.exe"
        self.assertEqual(discovery.discover_game_directory(selected, [str(launched)]), main.parent)
        self.assertEqual(discovery.discover_game_directory(selected, [], executable=str(launched)), main.parent)

    def test_malformed_pe_metadata_never_counts_as_renderer(self):
        cases = {"truncated": synthetic_pe()[:300], "plain-text": b"d3d12.dll"}
        for label, offset, fmt, value in (
            ("huge-pe-offset", 0x3C, "<I", 0xFFFFFFF0),
            ("bad-optional-magic", 0x98, "<H", 0x10B),
            ("too-many-sections", 0x86, "<H", 65535),
            ("huge-import-size", 0x98 + 124, "<I", 0xFFFFFFFF),
            ("unbacked-name-rva", 0x20C, "<I", 0x9000),
            ("unbacked-import-rva", 0x98 + 120, "<I", 0x9000),
            ("unterminated-directory", 0x98 + 124, "<I", 20),
            ("raw-section-outside-file", 0x188 + 20, "<I", 0xFFFFF000),
        ):
            data = bytearray(synthetic_pe())
            struct.pack_into(fmt, data, offset, value)
            cases[label] = bytes(data)
        unterminated = bytearray(synthetic_pe())
        unterminated[0x400:0x500] = b"d" * 256
        cases["unterminated-name"] = bytes(unterminated)
        overlap = bytearray(synthetic_pe())
        struct.pack_into("<H", overlap, 0x86, 2)
        struct.pack_into("<8sIIIIIIHHI", overlap, 0x1B0, b".bad\0\0\0\0", 10, 0x1000, 10, 0x600, 0, 0, 0, 0, 0x40000040)
        cases["partially-overlapping-sections"] = bytes(overlap)
        wrapped = bytearray(synthetic_pe())
        struct.pack_into("<I", wrapped, 0x188 + 12, 0xFFFFFF00)
        struct.pack_into("<I", wrapped, 0x98 + 120, 0xFFFFFF00)
        struct.pack_into("<I", wrapped, 0x20C, 0xFFFFFF80)
        wrapped[0x280:0x28B] = b"d3d12.dll\0\0"
        cases["section-rva-overflows-32bit"] = bytes(wrapped)
        for label, data in cases.items():
            with self.subTest(label=label):
                exe = self.file(f"{label}/game.exe", data)
                with self.assertRaises(ValueError):
                    discovery.discover_game_directory(exe.parent, [])

    def test_unique_main_argv_amd64_does_not_require_static_graphics_imports(self):
        game = self.file("unusual generic directory/Game.EXE", synthetic_pe(("KERNEL32.dll",)))
        self.assertEqual(discovery.discover_game_directory(self.root, [str(game)]), game.parent)
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [])
        self.file("unusual generic directory/deeper/possible-renderer.exe", synthetic_pe(("KERNEL32.dll",)))
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [str(game)])

    def test_oversized_pe_is_rejected_without_opening_it(self):
        game = self.file("huge/game.exe", synthetic_pe())
        with game.open("r+b") as stream:
            stream.truncate(4 * 1024 ** 3 + 1)  # Sparse fixture; no 4 GiB allocation.
        with patch.object(Path, "open", side_effect=AssertionError("oversized PE opened")):
            with self.assertRaises(ValueError):
                discovery.discover_game_directory(game.parent, [])

    def test_unicode_casefold_root_prefix_does_not_corrupt_absolute_context(self):
        renamed = self.root.with_name("Grüße root")
        self.root.rename(renamed)
        self.root = renamed
        main = self.file("a/game.exe", synthetic_pe())
        self.file("b/other.exe", synthetic_pe())
        context = str(main).replace("Grüße root", "GRÜSSE ROOT")
        self.assertEqual(discovery.discover_game_directory(self.root, [context]), main.parent)
        self.assertEqual(discovery.discover_game_directory(self.root, [], executable=context), main.parent)
        ini = self.file("a/OptiScaler.ini")
        self.file("b/OptiScaler.ini")
        self.assertEqual(discovery.discover_ini(self.root, Path(context)), ini)

    def test_bootstrap_graphics_imports_cannot_hide_nested_generic_renderer(self):
        bootstrap = self.file("launcher.exe", synthetic_pe(("d3d11.dll",)))
        renderer = self.file("arbitrary/nested/render.exe", synthetic_pe())
        with self.assertRaises(ValueError):
            discovery.discover_game_directory(self.root, [str(bootstrap)])
        self.assertEqual(discovery.discover_game_directory(self.root, [str(renderer)]), renderer.parent)
        bootstrap.write_bytes(synthetic_pe(("KERNEL32.dll",)))
        self.assertEqual(discovery.discover_game_directory(self.root, [str(bootstrap)]), renderer.parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
