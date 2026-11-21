"""Versioned recipe contracts using upstream INIs and the legacy fgmod updater."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).with_name("fixtures")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assignments(option, action="on"):
    return dict(token.split("=", 1) for token in shlex.split(option.get(action, ""))
                if token.startswith(("OptiScaler_", "VSync_")) and "=" in token)


class VersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, RECIPE_REPOSITORY_OWNER="Wurielle",
                   RECIPE_REPOSITORY_NAME="decky-launch-options-recipes", RECIPE_COMMIT_SHA="0" * 40)
        subprocess.run(["pnpm", "exec", "tsc", "-p", "tsconfig.recipes.json"],
                       cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        module = (ROOT / ".generated/recipes-build/recipes/optiscaler/index.js").as_uri()
        result = subprocess.run(["node", "--input-type=module", "-e",
                                 "const {default: stable} = await import(process.argv[1]); "
                                 "const {default: nightly} = await import(new URL('../dlor-optiscaler/index.js', process.argv[1])); "
                                 "console.log(JSON.stringify([stable, nightly]));", module],
                                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        cls.stable, cls.nightly = [r["launchOptions"] for r in json.loads(result.stdout)]
        cls.updater = load_module("version_config", ROOT / "recipes/dlor-optiscaler/scripts/update_optiscaler_config.py")
        cls.legacy = load_module("legacy_config", FIXTURES / "legacy_config.py")

    def values(self, variable):
        return {env[variable] for option in self.stable for env in [assignments(option)] if variable in env}

    def test_every_emitted_key_exists_in_its_real_versioned_ini(self):
        for name, options in (("stable-0.9.5", self.stable), ("nightly-10", self.nightly)):
            data = (FIXTURES / (name + ".ini")).read_bytes()
            checked = 0
            for option in options:
                for action in ("on", "off"):
                    env = assignments(option, action)
                    if not env:
                        continue
                    with self.subTest(version=name, option=option["id"], action=action):
                        resolved = self.updater.resolve_overrides(data, env)
                        self.assertEqual(len(resolved), len(env))
                        rendered = self.updater.render_overrides(data, resolved)
                        entries = self.updater.entries(data)
                        ownership = {str(i): {"section": section, "key": key, "after": value,
                                             "before_line": entries[(section, key)]["line"]}
                                     for i, ((section, key), value) in enumerate(resolved.items())}
                        self.assertEqual(self.updater.restore_overrides(rendered, ownership), data)
                    checked += 1
            self.assertGreater(checked, 50)

    def test_stable_framegen_values_match_native_whitelists(self):
        self.assertEqual(self.values("OptiScaler_FrameGen_FGInput"),
                         {"auto", "nofg", "dlssg", "nukems", "fsrfg", "upscaler", "fsrfg30"})
        self.assertEqual(self.values("OptiScaler_FrameGen_FGOutput"),
                         {"auto", "nofg", "fsrfg", "xefg", "nukems"})

    def test_stable_fidelityfx_values_use_legacy_backend_codes(self):
        for api in ("Dx11", "Dx12", "Vulkan"):
            values = self.values("OptiScaler_Upscalers_" + api + "Upscaler")
            with self.subTest(api=api):
                self.assertTrue(values.isdisjoint({"ffx", "ffx_12"}))
                self.assertIn("fsr31_12" if api == "Dx11" else "fsr31", values)
                if api == "Vulkan":
                    self.assertIn("fsr31_12", values)
        self.assertEqual(self.values("OptiScaler_XeFG_InterpolationCount"), {"auto", "1", "2", "3"})
        self.assertEqual(self.values("OptiScaler_FSR_Fsr4Preset"), {"auto", "0", "1", "2", "3", "4", "5"})

    def test_stable_vsync_reaches_legacy_updater(self):
        original = (FIXTURES / "stable-0.9.5.ini").read_bytes()
        choices = [o for o in self.stable if o.get("valueId") == "optiscaler-vsync"]
        self.assertEqual([o["valueName"] for o in choices], ["None", "Auto", "On", "Off"])
        expected = {"None": ("auto", "auto"), "Auto": ("auto", "auto"),
                    "On": ("true", "true"), "Off": ("true", "false")}
        with tempfile.TemporaryDirectory() as temporary:
            ini = Path(temporary) / "OptiScaler.ini"
            for option in choices:
                with self.subTest(choice=option["valueName"]):
                    ini.write_bytes(original)
                    with patch.dict(os.environ, assignments(option), clear=True), contextlib.redirect_stdout(io.StringIO()):
                        self.legacy.update_optiscaler_config(ini)
                    entries = self.updater.entries(ini.read_bytes())
                    self.assertEqual(tuple(entries[("V-Sync", key)]["value"]
                                           for key in ("OverrideVsync", "ForceVsync")), expected[option["valueName"]])
                    self.assertNotIn("%command%", option["on"])
                    self.assertNotIn("env ", option["on"])

    def test_both_versions_keep_unique_ids_and_inert_dropdown_defaults(self):
        for options in (self.stable, self.nightly):
            ids = [o["id"] for o in options]
            self.assertEqual(len(ids), len(set(ids)))
            groups = {}
            for option in options:
                if option.get("valueId"):
                    groups.setdefault(option["valueId"], []).append(option)
            for group, choices in groups.items():
                with self.subTest(group=group):
                    defaults = [o for o in choices if o.get("fallbackValue")]
                    self.assertEqual(len(defaults), 1)
                    if group == "dlor-optiscaler-fsr-override":
                        self.assertEqual(defaults[0]["valueName"], "AMD SDK")
                    else:
                        self.assertEqual((defaults[0]["valueName"], defaults[0]["on"], defaults[0]["off"]),
                                         ("None", "", ""))
