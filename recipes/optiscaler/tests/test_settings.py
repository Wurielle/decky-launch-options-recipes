"""Offline checks of compiled nightly settings and their updater integration.

Run with Node/pnpm on PATH:
python3 -I -B -m unittest discover -s recipes/optiscaler/tests -v
"""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        environment = dict(os.environ, RECIPE_REPOSITORY_OWNER="Wurielle",
                           RECIPE_REPOSITORY_NAME="decky-launch-options-recipes",
                           RECIPE_COMMIT_SHA="0" * 40)
        subprocess.run(["pnpm", "exec", "tsc", "-p", "tsconfig.recipes.json"],
                       cwd=ROOT, env=environment, capture_output=True, text=True, check=True)
        module = (ROOT / ".generated/recipes-build/recipes/optiscaler/index.js").as_uri()
        result = subprocess.run(["node", "--input-type=module", "-e",
                                 "const {default: recipe} = await import(process.argv[1]); "
                                 "const {default: installer} = await import(new URL('../dlor-optiscaler/index.js', process.argv[1])); "
                                 "console.log(JSON.stringify([recipe, installer]));", module],
                                cwd=ROOT, env=environment, capture_output=True, text=True, check=True)
        recipes = json.loads(result.stdout)
        cls.options = recipes[0]["launchOptions"]
        cls.installer_options = recipes[1]["launchOptions"]

    def assignments(self, value_id):
        return [dict(token.split("=", 1) for token in shlex.split(option["on"])
                     if "=" in token)
                for option in self.options if option.get("valueId") == value_id
                and option["on"]]

    def values(self, value_id, variable):
        return {entry[variable] for entry in self.assignments(value_id)}

    def test_framegen_routes_use_current_input_and_output_settings(self):
        self.assertEqual(self.values("optiscaler-framegen-output", "OptiScaler_FrameGen_FGOutput"),
                         {"auto", "nofg", "fsrfg", "xefg", "dlssg", "reprojection"})
        self.assertEqual(self.values("optiscaler-framegen-input", "OptiScaler_FrameGen_FGInput"),
                         {"auto", "nofg", "dlssg", "nvngxfg", "fsrfg", "upscaler", "fsrfg30", "xefg"})

    def test_fsr_controls_use_canonical_upscalers_and_separate_gpu_model(self):
        for renderer in ("dx11", "dx12", "vk"):
            suffix = {"dx11": "Dx11", "dx12": "Dx12", "vk": "Vulkan"}[renderer]
            values = self.values("optiscaler-upscalers-" + renderer,
                                 "OptiScaler_Upscalers_" + suffix + "Upscaler")
            self.assertNotIn("fsr31_12", values)
            self.assertIn("ffx_12" if renderer == "dx11" else "ffx", values)
            if renderer == "dx11":
                self.assertIn("fsr31", values)
            else:
                self.assertNotIn("fsr31", values)
        self.assertEqual(self.values("optiscaler-fsr4-gpu-support", "OptiScaler_FSR_Fsr4GpuSupport"),
                         {"auto", "0", "1", "2", "3", "4"})
        self.assertEqual(self.values("optiscaler-fsr4-model", "OptiScaler_FSR_Fsr4Model"),
                         {"auto", "0", "1", "2", "3"})
        self.assertEqual(self.values("optiscaler-fsr4-preset", "OptiScaler_FSR_Fsr4Preset"),
                         {"auto", "0", "1", "2", "3", "4", "5"})

    def test_settings_are_assignments_with_inert_dropdown_defaults(self):
        ids = [option["id"] for option in self.options]
        self.assertEqual(len(ids), len(set(ids)))
        groups = {}
        for option in self.options:
            if option.get("valueId"):
                groups.setdefault(option["valueId"], []).append(option)
                for token in shlex.split(option["on"]):
                    self.assertRegex(token, r"^OptiScaler_[A-Za-z0-9_]+=.*$")
        for name, options in groups.items():
            with self.subTest(group=name):
                defaults = [option for option in options if option.get("fallbackValue")]
                self.assertEqual(len(defaults), 1)
                self.assertEqual((defaults[0]["valueName"], defaults[0]["on"], defaults[0]["off"]),
                                 ("None", "", ""))
                self.assertTrue(all(option.get("enableGlobally") is False for option in options))
        self.assertEqual(self.values("optiscaler-vsync", "OptiScaler_VSync_OverrideVsync"),
                         {"auto", "true"})

    def test_mfg_controls_use_documented_counts_and_current_dynamic_keys(self):
        for engine, section, maximum in (("xefg", "XeFG", 3), ("dlssg", "DLSSG", 5)):
            with self.subTest(engine=engine):
                count_values = {str(count) for count in range(1, maximum + 1)}
                group = "optiscaler-" + engine
                self.assertEqual(self.values(group + "-mfg-count", "OptiScaler_" + section + "_InterpolationCount"),
                                 {"auto"} | count_values)
                for count in range(1, maximum + 1):
                    option = next(o for o in self.options if o["id"] == group + "-mfg-count-" + str(count))
                    self.assertIn(str(count + 1) + "×", option["valueName"])
                targets = self.values(group + "-target-fps", "OptiScaler_" + section + "_FramerateTargetDMFG")
                self.assertIn("auto", targets)
                self.assertTrue(all(float(v) >= (10 if engine == "xefg" else 0) for v in targets if v != "auto"))
        for group, setting in {
            "xefg-dynamic-mfg": "XeFG_DynamicMFG",
            "xefg-target-as-cap-dmfg": "XeFG_TargetAsCapDMFG",
            "dlssg-force-dmfg": "DLSSG_ForceDMFG",
        }.items():
            self.assertEqual(self.values("optiscaler-" + group, "OptiScaler_" + setting),
                             {"auto", "true", "false"})
        self.assertEqual(self.values("optiscaler-xefg-rounding-dmfg", "OptiScaler_XeFG_RoundingDMFG"),
                         {"auto", "0", "1", "2"})
        self.assertFalse(any("OptiScaler_FSRFG_InterpolationCount=" in option["on"]
                             for option in self.options))

    def test_reprojection_uses_current_output(self):
        option = next((o for o in self.options if o["id"] == "optiscaler-framegen-output-reprojection"), None)
        assert option is not None, 'Reprojection choice is missing'
        self.assertEqual(option["on"], 'OptiScaler_FrameGen_FGOutput="reprojection"')
        self.assertEqual(option["valueName"], "Reprojection")

    def test_menu_only_controls_are_absent_and_legacy_launchers_remain(self):
        removed = {
            "optiscaler-framegen-nvngx-replacement",
            "optiscaler-fsr-upscaler-index", "optiscaler-fsr-fg-index",
            "optiscaler-xefg-mfg-game-count", "optiscaler-dlssg-mfg-game-count",
            "optiscaler-dlssg-override-force-dmfg", "optiscaler-xefg-dynamic-allow-1x",
            "optiscaler-vsync-sync-interval",
        }
        for option in self.options:
            with self.subTest(option=option["id"]):
                self.assertNotIn(option["id"], removed)
                self.assertNotIn(option.get("valueId"), removed)
                for variable in ["FrameGen_FGNvngxReplacement", "FSR_UpscalerIndex", "FSR_FGIndex",
                                 "XeFG_OverrideInterpolationCount", "DLSSG_OverrideInterpolationCount",
                                 "DLSSG_OverrideForceDMFG", "XeFG_DynamicAllow1X", "VSync_SyncInterval"]:
                    self.assertNotIn("OptiScaler_" + variable + "=", option.get("on", ""))
        self.assertTrue(any(o["id"] == "dlor-optiscaler" for o in self.installer_options))
        legacy = next(o for o in self.options if o["id"] == "optiscaler")
        self.assertEqual(legacy["on"], "~/fgmod/fgmod %command%")
        self.assertEqual(legacy["off"], "~/fgmod/fgmod-uninstaller.sh %command%")
        nightly = next(o for o in self.options if o["id"] == "optiscaler-nightly-upgrade")
        self.assertIn("~/.dlor/run optiscaler update-nightly ", nightly["on"])
        self.assertEqual(nightly["priority"], -1)
        self.assertEqual(self.values("optiscaler-fsr4-gpu-support", "OptiScaler_FSR_Fsr4GpuSupport"),
                         {"auto", "0", "1", "2", "3", "4"})

    def test_option_labels_have_no_parenthetical_text(self):
        for option in [*self.options, *self.installer_options]:
            for field in ("name", "valueName"):
                with self.subTest(option=option["id"], field=field):
                    self.assertNotRegex(option.get(field, ""), r"[()]")

    def test_framegen_controls_share_the_framegen_label_prefix(self):
        for option in self.options:
            variables = [token.split("=", 1)[0] for token in shlex.split(option.get("on", ""))]
            related = any(variable.startswith(("OptiScaler_FrameGen_", "OptiScaler_OptiFG_",
                                               "OptiScaler_XeFG_", "OptiScaler_DLSSG_"))
                          or variable == "OptiScaler_FSR_FGIndex" for variable in variables)
            if related:
                with self.subTest(option=option["id"]):
                    self.assertTrue(option["name"].startswith("OptiScaler FrameGen"))

    def test_every_setting_round_trips_through_physical_updater(self):
        path = ROOT / "recipes/dlor-optiscaler/scripts/update_optiscaler_config.py"
        spec = importlib.util.spec_from_file_location("settings_updater", path)
        assert spec is not None and spec.loader is not None
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        # Synthetic settings surface; values/bytes do not represent a game or DLL.
        sections = {
            "Upscalers": ("Dx11Upscaler", "Dx12Upscaler", "VulkanUpscaler"),
            "FrameGen": ("Enabled", "FGInput", "FGOutput", "FGNvngxReplacement"),
            "OptiFG": ("HUDFix",), "Menu": ("ShortcutKey",),
            "Framerate": ("FramerateLimit",),
            "FSR": ("UpscalerIndex", "FGIndex", "Fsr4Preset", "Fsr4GpuSupport", "Fsr4Model"),
            "V-Sync": ("OverrideVsync", "ForceVsync", "SyncInterval"),
            "XeFG": ("InterpolationCount", "OverrideInterpolationCount", "DynamicMFG",
                     "FramerateTargetDMFG", "RoundingDMFG", "DynamicAllow1X", "TargetAsCapDMFG"),
            "DLSSG": ("InterpolationCount", "OverrideInterpolationCount", "ForceDMFG",
                      "OverrideForceDMFG", "FramerateTargetDMFG"),
        }
        text = "; Keep literal % \\ and comments\r\n" + "".join(
            "[" + section + "]\r\n" + "".join("  " + key + " =auto\r\n" for key in keys)
            for section, keys in sections.items())
        data = b"\xef\xbb\xbf" + text.encode()
        checked = 0
        for option in self.options:
            for action in ("on", "off"):
                tokens = shlex.split(option.get(action, ""))
                env = dict(token.split("=", 1) for token in tokens if token.startswith("OptiScaler_"))
                if not env:
                    continue
                with self.subTest(option=option["id"], action=action):
                    overrides = updater.resolve_overrides(data, env)
                    self.assertEqual(len(overrides), len(env))
                    self.assertEqual(set(overrides.values()), set(env.values()))
                    rendered = updater.render_overrides(data, overrides)
                    entries = updater.entries(data)
                    ownership = {str(index): {"section": section, "key": key, "after": value,
                                               "before_line": entries[(section, key)]["line"]}
                                 for index, ((section, key), value) in enumerate(overrides.items())}
                    self.assertEqual(updater.restore_overrides(rendered, ownership), data)
                    checked += 1
        self.assertGreater(checked, 100)
