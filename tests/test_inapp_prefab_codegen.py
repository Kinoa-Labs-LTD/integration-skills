"""Offline tests for the C# generator. Assertions are on text: the Unity compile gate runs in Task 11."""
import copy
import importlib.util
import json
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
HELPER = os.path.join(SKILL, "inapp_prefab_plan.py")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")
FIX_MISSIONS = os.path.join(SKILL, "evals", "fixtures", "missions")
GOLDEN_VIEWS = os.path.join(REPO, "tests", "golden")   # view goldens rendered from the milestone base (6d5deb8)

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

with open(os.path.join(FIX, "template_one_cta.json"), encoding="utf-8") as _fh:
    TEMPLATE = json.load(_fh)
with open(os.path.join(FIX, "build_result_one_cta.json"), encoding="utf-8") as _fh:
    BUILD = json.load(_fh)
with open(os.path.join(FIX_MISSIONS, "template_missions.json"), encoding="utf-8") as _fh:
    MISSIONS = json.load(_fh)
with open(os.path.join(FIX_MISSIONS, "daily_missions.layout.json"), encoding="utf-8") as _fh:
    ART_RAW = json.load(_fh)
_ACTION_BUTTON_KEYS = ("collect_all_button", "reach_all_button", "collect_all_milestones_button")
# The layout fixture without the three feature-action buttons, so the 1:1 join with a close-only template holds.
ART_RAW_WITHOUT_ACTION_BUTTONS = dict(ART_RAW, elements=[e for e in ART_RAW["elements"] if e["key"] not in _ACTION_BUTTON_KEYS])
STYLE = {"text_system": "legacy", "font_guid": "e7a63bee4e93df34ca0dd3548b336621", "tmp_font_guid": None,
         "root_size": [900.0, 1400.0], "close_sprite_guid": None, "base_classes": [], "prefabs": [], "warnings": []}
FORBIDDEN = ("dashboard.kinoa.io", "Bearer", "UnityWebRequest", "Addressables.Load")


def _plan(template=TEMPLATE, style=STYLE, layout=None):
    layout = mod.layout_from_build(BUILD) if layout is None else layout
    return mod.plan_prefab(template, layout, style, {})["plan"]


class TestSharedFiles(unittest.TestCase):
    def setUp(self):
        self.out = mod.generate_code(_plan(), {})
        self.files = self.out["files"]

    def test_file_set(self):
        for path in ("Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs",
                     "Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs",
                     "Assets/Kinoa/InApps/Shared/KinoaInAppFeatureHooks.cs",
                     "Assets/Kinoa/InApps/Shared/KinoaInAppMilestoneStepView.cs",
                     "Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs",
                     "Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs",
                     "Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"):
            self.assertIn(path, self.files)

    def test_mission_shared_views_api(self):
        row = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs"]
        for sig in ("public void SetSubMission(int? number)", "public void SetProgress(decimal current, decimal goal)",
                    "public KinoaInAppItemView AddReward(Sprite icon, string amount)",
                    "public void SetAction(string label, UnityAction onClick)",
                    "public void SetDismiss(bool visible, UnityAction onClick)",
                    "[SerializeField] private Button dismissButton;", "[SerializeField] private KinoaInAppItemView rewardTemplate;"):
            self.assertIn(sig, row)
        tab = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs"]
        self.assertIn("public void Setup(int setNumber, string text, bool selected, UnityAction onClick)", tab)
        self.assertIn("[SerializeField] private GameObject selectedMarker;", tab)
        for content in (row, tab):
            self.assertIn("using KinoaText = UnityEngine.UI.Text;", content)

    def test_mission_shared_views_serialized_fields_match_plan_roles(self):
        row = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs"]
        for name in ("placementText", "titleText", "subMissionText", "statusText", "progressText", "actionLabel",
                     "dismissLabel", "progressFill", "rewardsRoot", "rewardTemplate", "actionButton", "dismissButton"):
            self.assertRegex(row, r"\[SerializeField\] private \w+ %s;" % name)
        tab = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs"]
        for name in ("label", "selectedMarker", "button"):
            self.assertRegex(tab, r"\[SerializeField\] private \w+ %s;" % name)

    def test_mission_shared_views_formats_and_tmp_alias(self):
        row = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs"]
        for fmt in ('"P" + placementNumber', '"Sub-mission " + number', '"\\u00d7"'):
            self.assertIn(fmt, row)
        # whole numbers print bare, decimals without a culture's separator or a fixed scale ("5/10", "2.5/10")
        self.assertIn("using System.Globalization;", row)
        self.assertIn('progressText.text = current.ToString("0.##", CultureInfo.InvariantCulture) + "/" + goal.ToString("0.##", CultureInfo.InvariantCulture);', row)
        self.assertNotIn("current + \"/\" + goal", row)
        style = dict(STYLE, text_system="tmp", tmp_font_guid="cccccccccccccccccccccccccccccccc")
        files = mod.generate_code(_plan(style=style), {})["files"]
        for name in ("KinoaInAppMissionRowView", "KinoaInAppTabView"):
            self.assertIn("using KinoaText = TMPro.TMP_Text;", files["Assets/Kinoa/InApps/Shared/%s.cs" % name])

    def test_no_forbidden_strings_anywhere(self):
        for path, content in self.files.items():
            for bad in FORBIDDEN:
                self.assertNotIn(bad, content, "%s contains %s" % (path, bad))

    def test_hooks_leave_todos_and_null_delegates_by_default(self):
        hooks = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs"]
        self.assertIn("public static Func<string, Task<Sprite>> LoadSpriteFromUrl = null;", hooks)
        self.assertIn("public static Func<InAppStorePackages, bool, string> ResolveStorePrice = null;", hooks)
        self.assertIn("public static Func<string, Sprite> ResolveResourceIcon = null;", hooks)
        self.assertEqual(hooks.count("TODO(kinoa-prefab):"), 3)
        self.assertIn("using Kinoa.Data.Messaging.InApp;", hooks)
        self.assertIn("namespace Kinoa.InApps", hooks)

    def test_hooks_wire_named_methods_when_given(self):
        out = mod.generate_code(_plan(), {"image_loader": "Game.Utils.ImageCache.LoadSpriteAsync",
                                          "price_resolver": "Game.Iap.Store.PriceFor"})
        hooks = out["files"]["Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs"]
        self.assertIn("LoadSpriteFromUrl = Game.Utils.ImageCache.LoadSpriteAsync;", hooks)
        self.assertIn("ResolveStorePrice = Game.Iap.Store.PriceFor;", hooks)
        self.assertIn("ResolveResourceIcon = null;", hooks)
        self.assertEqual(hooks.count("TODO(kinoa-prefab):"), 1)

    def test_item_view_uses_legacy_alias(self):
        item = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs"]
        self.assertIn("using KinoaText = UnityEngine.UI.Text;", item)
        self.assertIn("public void SetButton(bool interactable, UnityAction onClick)", item)
        self.assertIn("[SerializeField] private Image icon;", item)

    def test_item_view_uses_tmp_alias_when_probe_said_tmp(self):
        style = dict(STYLE, text_system="tmp", tmp_font_guid="cccccccccccccccccccccccccccccccc")
        item = mod.generate_code(_plan(style=style), {})["files"]["Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs"]
        self.assertIn("using KinoaText = TMPro.TMP_Text;", item)

    def test_builder_contract(self):
        builder = self.files["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertIn('public const string MenuPath = "Tools/Kinoa/In-Apps/Build Prefabs From Plans";', builder)
        self.assertIn("[MenuItem(MenuPath)]", builder)
        self.assertIn("public static string BuildAll()", builder)
        self.assertIn("public static BuildReport BuildFromPlan(string planPath)", builder)
        self.assertIn('".build-report.json"', builder)
        self.assertIn("PrefabUtility.SaveAsPrefabAsset", builder)
        self.assertIn("namespace Kinoa.InApps.Editor", builder)
        # every plan node key the builder deserialises must exist in the Python node shape
        node = mod._node("X", None, "text")
        for fld in re.findall(r"public (?:string|bool|float\[\]|string\[\]) (\w+);", builder.split("class PlanNode")[1].split("}")[0]):
            self.assertIn(fld, node, "builder reads PlanNode.%s which the planner never writes" % fld)

    def test_builder_uses_try_get_component_not_null_coalescing(self):
        builder = self.files["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertNotIn("?? go.AddComponent", builder, "builder should use TryGetComponent, not ??")
        self.assertNotIn("?? BuiltinFont", builder, "builder should use explicit null check, not ??")
        self.assertIn("TryGetComponent<Image>(out var background)", builder, "builder should use TryGetComponent for background")

    def test_builder_sizes_unplaced_slots(self):
        builder = self.files["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertIn("rt.sizeDelta = new Vector2(0f, 80f);", builder, "unplaced slots must have explicit sizeDelta")

    def test_builder_handles_builtin_font_per_version(self):
        builder = self.files["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertIn("#if UNITY_2022_2_OR_NEWER", builder, "builder should use version-specific preprocessor directive")
        self.assertIn('Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf")', builder, "builder should try LegacyRuntime.ttf")
        self.assertIn('Resources.GetBuiltinResource<Font>("Arial.ttf")', builder, "builder should fallback to Arial.ttf")
        self.assertNotIn("catch (Exception) { return Resources.GetBuiltinResource", builder, "builder should not use try-catch for BuiltinFont")

    def test_builder_knows_mission_bindings(self):
        b = mod.BUILDER_CS
        for s in ('case "scroll":', 'case "tab_template":', 'case "mission_row_template":',
                  'case "row_part":', 'case "tab_part":', "public string color;", "public string role;",
                  "public string scroll_axis;", "ColorUtility.TryParseHtmlString(node.color", "AddComponent<RectMask2D>()",
                  "ContentSizeFitter.FitMode.PreferredSize", 'case "ScrollRect":',
                  'case "KinoaInAppTabView":', 'case "KinoaInAppMissionRowView":', "not assigned"):
            self.assertIn(s, b)
        self.assertNotIn("MissionDialog", b)
        self.assertNotIn('case "list_content":', b)   # the mission list is the shared scroll chain now

    def test_builder_orphan_role_check_is_limited_to_part_bindings(self):
        # slot nodes carry layout roles ("header", "bar_image", ...) that are not view-field names;
        # only tab_part / row_part roles are wiring contracts, so only they may fail the build as orphans
        b = mod.BUILDER_CS
        orphan = b.split("foreach (var orphan in", 1)[1].split(";", 1)[0]
        self.assertIn('IsPartBinding(n.binding)', orphan)
        self.assertIn('private static bool IsPartBinding(string binding) => binding == "tab_part" || binding == "row_part";', b)


class TestGenerateCli(unittest.TestCase):
    def _run(self, *extra):
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, *extra],
                             capture_output=True, text=True)
        return root, res

    def test_invalid_hook_method_is_rejected(self):
        for flag in ("--image-loader", "--price-resolver", "--resource-icon-resolver"):
            root, res = self._run(flag, "Foo.Bar;System.Exit()")
            self.assertEqual(res.returncode, 2, res.stdout)
            data = json.loads(res.stdout)
            self.assertEqual(data["error"], "invalid_hook_method")
            self.assertEqual(data["flag"], flag)
            self.assertEqual(data["value"], "Foo.Bar;System.Exit()")
            self.assertFalse(os.path.exists(os.path.join(root, "Assets")))
        # a bare identifier (no class) is rejected too; a qualified one passes
        _, res = self._run("--image-loader", "Loader")
        self.assertEqual(res.returncode, 2)
        _, res = self._run("--image-loader", "Game.Util.SpriteLoader.LoadAsync")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_writes_files_and_snippets(self):
        root, res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])
        view = os.path.join(root, "Assets", "Kinoa", "InApps", "OneCtaOffer", "KinoaInAppOneCtaOfferView.cs")
        self.assertTrue(os.path.isfile(view))
        self.assertTrue(os.path.isfile(os.path.join(root, "Assets", "Kinoa", "InApps", "Editor", "KinoaInAppPrefabBuilder.cs")))
        self.assertTrue(os.path.isfile(os.path.join(root, "Assets", "Kinoa", "InApps", "OneCtaOffer", "one_cta_offer.inapp-plan.json")))
        self.assertEqual(data["snippets"]["constant"], '        public const string TemplateKeyOneCtaOffer = "one_cta_offer";')
        self.assertEqual(data["snippets"]["allowlist_arm"], "            KinoaInAppTemplateConstants.TemplateKeyOneCtaOffer => true,")
        self.assertIn("KinoaInAppOneCtaOfferView", data["snippets"]["create_game_inapp"])
        self.assertTrue(any(t["text"].startswith("TODO(kinoa-prefab):") for t in data["todos"]))
        self.assertTrue(all(t["path"].endswith(".cs") for t in data["todos"]))

    def test_second_run_refuses_to_overwrite_view_without_flag(self):
        root, res = self._run()
        import subprocess
        import sys
        plan_path = os.path.join(root, "p.json")
        res2 = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                              capture_output=True, text=True)
        self.assertEqual(res2.returncode, 2)
        self.assertEqual(json.loads(res2.stdout)["error"], "view_exists")
        res3 = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, "--overwrite"],
                              capture_output=True, text=True)
        data = json.loads(res3.stdout)
        self.assertTrue(data["ok"])
        self.assertIn("Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs", data["skipped"])  # shared files kept

    def test_shared_text_system_mismatch_is_refused(self):
        root, _ = self._run()
        hooks_dir = os.path.join(root, "Assets", "Kinoa", "InApps", "Shared")
        with open(os.path.join(hooks_dir, "KinoaInAppItemView.cs"), "w", encoding="utf-8") as fh:
            fh.write("using KinoaText = TMPro.TMP_Text;\n")
        import subprocess
        import sys
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", os.path.join(root, "p.json"),
                              "--project-root", root, "--overwrite"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)["error"], "shared_text_system_mismatch")

    def test_generate_writes_new_shared_files_next_to_kept_ones(self):
        """Project already has the old shared files: the two new ones are written, the old ones kept."""
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)
        shared = os.path.join(root, "Assets", "Kinoa", "InApps", "Shared")
        os.makedirs(shared)
        for name in ("KinoaInAppItemView.cs", "KinoaInAppHooks.cs"):
            with open(os.path.join(shared, name), "w", encoding="utf-8") as fh:
                fh.write("// old %s\nusing KinoaText = UnityEngine.UI.Text;\n" % name)
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        data = json.loads(res.stdout)
        base = "Assets/Kinoa/InApps/Shared/"
        for name in ("KinoaInAppMissionRowView.cs", "KinoaInAppTabView.cs"):
            self.assertIn(base + name, data["written"])
            self.assertTrue(os.path.isfile(os.path.join(shared, name)))
        for name in ("KinoaInAppItemView.cs", "KinoaInAppHooks.cs"):
            self.assertIn(base + name, data["skipped"])
            with open(os.path.join(shared, name), encoding="utf-8") as fh:
                self.assertTrue(fh.read().startswith("// old"))

    def test_mismatch_guard_covers_mission_shared_files(self):
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)  # legacy plan
        shared = os.path.join(root, "Assets", "Kinoa", "InApps", "Shared")
        os.makedirs(shared)
        with open(os.path.join(shared, "KinoaInAppTabView.cs"), "w", encoding="utf-8") as fh:
            fh.write("using KinoaText = TMPro.TMP_Text;\n")
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        data = json.loads(res.stdout)
        self.assertEqual(data["error"], "shared_text_system_mismatch")
        self.assertEqual(data["path"], "Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs")

    def test_facade_flag_reaches_the_view(self):
        root, res = self._run("--facade", "present", "--facade-namespace", "Game.Kinoa")
        with open(os.path.join(root, "Assets", "Kinoa", "InApps", "OneCtaOffer", "KinoaInAppOneCtaOfferView.cs"), encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn("using Game.Kinoa;", view)
        self.assertIn("HandleInAppButtonClickAsync(Message, key)", view)

    def test_exact_shared_file_classification_with_custom_out_dir(self):
        """Fix 1: View and plan are not misclassified as shared when out_dir contains 'Shared'."""
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        # Create a plan with out_dir = "Assets/Shared/Kinoa/InApps"
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {"out_dir": "Assets/Shared/Kinoa/InApps"})["plan"]
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        # First run
        res1 = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                              capture_output=True, text=True)
        self.assertEqual(res1.returncode, 0)
        # Second run with --overwrite should write view and plan (not skip them)
        res2 = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, "--overwrite"],
                              capture_output=True, text=True)
        self.assertEqual(res2.returncode, 0)
        data = json.loads(res2.stdout)
        self.assertIn("Assets/Shared/Kinoa/InApps/OneCtaOffer/KinoaInAppOneCtaOfferView.cs", data["written"])
        self.assertIn("Assets/Shared/Kinoa/InApps/OneCtaOffer/one_cta_offer.inapp-plan.json", data["written"])

    def test_builder_always_refreshed_never_skipped(self):
        """Fix 2: Editor builder is always rewritten, never skipped."""
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)
        # First run
        subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                       capture_output=True, text=True)
        # Corrupt the builder on disk
        builder_path = os.path.join(root, "Assets", "Kinoa", "InApps", "Editor", "KinoaInAppPrefabBuilder.cs")
        with open(builder_path, "w", encoding="utf-8") as fh:
            fh.write("stale")
        # Second run with --overwrite should still rewrite the builder
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, "--overwrite"],
                             capture_output=True, text=True)
        data = json.loads(res.stdout)
        self.assertIn("Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs", data["written"])
        with open(builder_path, encoding="utf-8") as fh:
            builder_content = fh.read()
        self.assertIn("KinoaInAppPrefabBuilder", builder_content)
        self.assertNotIn("stale", builder_content)

    def test_todo_collection_uses_disk_for_skipped_files(self):
        """Fix 3: TODO index collects from disk content for skipped files."""
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)
        # First run
        subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                       capture_output=True, text=True)
        # Rewrite hooks file on disk to remove TODO markers
        hooks_path = os.path.join(root, "Assets", "Kinoa", "InApps", "Shared", "KinoaInAppHooks.cs")
        with open(hooks_path, "w", encoding="utf-8") as fh:
            fh.write("// no TODOs here\n")
        # Second run with --overwrite should collect todos from disk content for skipped hooks
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, "--overwrite"],
                             capture_output=True, text=True)
        data = json.loads(res.stdout)
        # Check that no todos mention KinoaInAppHooks
        todos_paths = [t["path"] for t in data["todos"]]
        self.assertTrue(all(not p.endswith("KinoaInAppHooks.cs") for p in todos_paths),
                        "todos should not include KinoaInAppHooks.cs since we removed its TODOs")

    def test_warnings_for_unapplied_hook_options(self):
        """Fix 4: Warnings are generated when hook options cannot be applied."""
        import subprocess
        import sys
        import tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)
        # First run
        subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                       capture_output=True, text=True)
        # Second run with hook option and --overwrite (hooks file will be skipped without --force-shared)
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root,
                              "--overwrite", "--image-loader", "Game.Img.Load"],
                             capture_output=True, text=True)
        data = json.loads(res.stdout)
        self.assertIn("--image-loader", str(data.get("warnings", [])),
                      "warnings should mention that --image-loader was not applied")


class TestViewStandard(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()
        self.view = mod.generate_code(self.plan, {})["files"][self.plan["paths"]["view_path"]]

    def test_header_and_identity(self):
        self.assertTrue(self.view.startswith("// <auto-generated>"))
        self.assertIn("namespace Kinoa.InApps", self.view)
        self.assertIn("public class KinoaInAppOneCtaOfferView : MonoBehaviour", self.view)
        self.assertIn('public const string TemplateKey = "one_cta_offer";', self.view)
        self.assertIn("using KinoaText = UnityEngine.UI.Text;", self.view)
        for bad in FORBIDDEN:
            self.assertNotIn(bad, self.view)

    def test_serialized_fields_match_plan(self):
        for node in self.plan["nodes"]:
            if node["field"]:
                cs_type = {"Text": "KinoaText"}.get(node["field_type"], node["field_type"])
                self.assertIn("[SerializeField] private %s %s;" % (cs_type, node["field"]), self.view,
                              "field %s missing" % node["field"])

    def test_bind_covers_every_slot(self):
        self.assertIn('ApplyText(headerText, "header", canBeHidden: true);', self.view)
        self.assertIn('ApplyText(finePrintText, "fine_print", canBeHidden: true);', self.view)
        self.assertIn('ApplyImage(backgroundImage, "background_image", canBeHidden: true);', self.view)
        self.assertIn('ApplyButton(ctaButton, ctaButtonLabel, "cta_button", canBeHidden: false);', self.view)
        self.assertIn('ApplyButton(closeButton, closeButtonLabel, "close_button", canBeHidden: true);', self.view)
        self.assertIn('ApplyToggle("show_resource_area", resourceAreaRoot);', self.view)
        self.assertIn("if (data == null || data.TemplateKey != TemplateKey)", self.view)

    def test_lifecycle_events(self):
        self.assertIn("Kinoa.GameEvents.SendInAppImpressionEvent(new InAppImpressionEventData(Message));", self.view)
        self.assertIn("Kinoa.GameEvents.SendInAppCloseEvent(new InAppCloseEventData(Message));", self.view)
        self.assertIn("Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));", self.view)
        self.assertIn("public event Action<KinoaInAppOneCtaOfferView> Closed;", self.view)

    def test_close_is_reentrancy_guarded(self):
        self.assertIn("private bool _closed;", self.view)
        close = self.view[self.view.index("public void Close()"):]
        close = close[:close.index("Destroy(gameObject);")]
        self.assertIn("if (_closed) return;", close)
        self.assertIn("_closed = true;", close)
        self.assertLess(close.index("if (_closed) return;"), close.index("SendInAppCloseEvent"))
        self.assertLess(close.index("_closed = true;"), close.index("SendInAppCloseEvent"))

    def test_click_routing_without_facade_leaves_todo(self):
        self.assertIn("if (slot.ClickConfig is InAppCloseClickConfiguration)", self.view)
        self.assertIn("ButtonClicked?.Invoke(this, key, slot.ClickConfig);", self.view)
        self.assertIn("%s route slot.ClickConfig" % mod.TODO, self.view)
        self.assertNotIn("KinoaUiService", self.view)

    def test_click_routing_with_facade(self):
        view = mod.generate_code(self.plan, {"facade": "present", "facade_namespace": "Core.Services"})["files"][self.plan["paths"]["view_path"]]
        self.assertIn("using Core.Services;", view)
        self.assertIn("_ = KinoaUiService.Instance.HandleInAppButtonClickAsync(Message, key);", view)
        self.assertNotIn("%s route slot.ClickConfig" % mod.TODO, view)

    def test_image_loading_goes_through_hooks_only(self):
        self.assertIn("case InAppImageContentType.WebUrl:", self.view)
        self.assertIn("KinoaInAppHooks.LoadSpriteFromUrl == null", self.view)
        self.assertIn("case InAppImageContentType.LocalPath:", self.view)
        self.assertIn("Resources.Load<Sprite>(image.Content)", self.view)
        self.assertIn("%s load the addressable sprite" % mod.TODO, self.view)

    def test_text_color_custom_field(self):
        self.assertIn('TryGetColor(slot.CustomFields, "text_color", out var color)', self.view)
        self.assertIn("ColorUtility.TryParseHtmlString", self.view)

    def test_tmp_alias(self):
        style = dict(STYLE, text_system="tmp", tmp_font_guid="cccccccccccccccccccccccccccccccc")
        plan = _plan(style=style)
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("using KinoaText = TMPro.TMP_Text;", view)

    def test_toggle_on_slot_target_passes_gameobject(self):
        """Controller ruling R6: boolean customs may target SLOT nodes (Image/Text/Button) as well as zone roots (GameObject).
           Slot toggles can only hide, never re-show an emptied slot."""
        t = copy.deepcopy(TEMPLATE)
        t["customs"].append({
            "key": "show_header",
            "kind": "boolean",
            "name": "Show Header",
            "index": 9,
            "nullable": True,
            "description": "",
            "canBeHidden": True,
            "customFields": [],
            "defaultValue": True
        })
        plan = _plan(template=t)
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        # Slot-target toggle should use ApplySlotToggle with .gameObject accessor
        self.assertIn('ApplySlotToggle("show_header", headerText != null ? headerText.gameObject : null);', view,
                      "toggle on Text slot should use ApplySlotToggle with .gameObject accessor")
        # Zone-root toggle should still use ApplyToggle
        self.assertIn('ApplyToggle("show_resource_area", resourceAreaRoot);', view,
                      "toggle on zone root should use ApplyToggle")
        # ApplySlotToggle method should exist and only hide (not show)
        self.assertIn("private void ApplySlotToggle(string customKey, GameObject target)", view,
                      "ApplySlotToggle method should be defined")
        self.assertIn("if (TryGetCustom<bool>(customKey, out var on) && !on) target.SetActive(false);", view,
                      "ApplySlotToggle should only hide when custom is false")


def _milestone_plan(mode="single_slot", collect_all=False, style=STYLE):
    """mode: per_step (no CTA slot) | single_slot (the template's one CTA slot) | single_main (--milestone-cta single, no slot)."""
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "chase"
    t["featureType"] = "milestone"
    t["features"] = {"milestone": {"key": "main_progressbar", "limit": 3, "mainActionTypes": ["close"]}}
    opts = {}
    if mode in ("per_step", "single_main"):
        t["buttons"] = [b for b in t["buttons"] if b["key"] == "close_button"]
    if mode == "single_main":
        opts["milestone_cta"] = "single"
    if collect_all:
        t["buttons"].append({"key": "collect_all_button", "name": "Collect All", "index": 20, "canBeHidden": True,
                             "clickActionType": ["collect_resource"], "customFields": []})
    result = mod.plan_prefab(t, mod.layout_from_build(BUILD), style, opts)
    assert result["ok"], result
    return result["plan"]


def _mission_plan():
    return _plan(template=MISSIONS, layout=mod.layout_from_artifact(ART_RAW))


def _selection(bind_feature):
    """Evaluates the generated D4 selection expression (a ?? chain of `(cond && cond ? set : null)` terms)
       for given sets: prev / active are (setNumber, hasRows) or None. Returns "prev", "active" or None."""
    expr = re.search(r"var target = (.*?);\n", bind_feature, re.S).group(1)
    terms = [t.strip() for t in re.split(r"\s*\?\?\s*", expr)]
    names = {"state.PreviousSetProgress": "prev", "state.ActiveSetProgress": "active"}

    def pick(selected, prev, active):
        sets = {"prev": prev, "active": active}
        for term in terms:
            m = re.fullmatch(r"\((.*) \? (state\.\w+) : null\)", term)
            if not m:
                if sets[names[term]] is not None:
                    return names[term]
                continue
            ok = True
            for cond in m.group(1).split(" && "):
                c = re.fullmatch(r"_selectedSetNumber == (state\.\w+)\?\.SetNumber", cond)
                h = re.fullmatch(r"HasRows\((state\.\w+)\)", cond)
                if c:
                    target = sets[names[c.group(1)]]
                    ok = ok and selected == (target[0] if target else None)
                elif h:
                    target = sets[names[h.group(1)]]
                    ok = ok and bool(target and target[1])
                else:
                    raise AssertionError("unknown condition: " + cond)
            if ok and sets[names[m.group(2)]] is not None:
                return names[m.group(2)]
        return None
    return pick


def _method_body(view, declaration):
    """The generated method from its declaration line to the next member at method indentation."""
    start = view.index(declaration)
    end = view.find("\n        private ", start + len(declaration))
    return view[start:] if end < 0 else view[start:end]


class TestViewZonesAndFeatures(unittest.TestCase):
    def test_timer_price_and_resources_on_standard(self):
        plan = _plan()
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("private void BindTimer()", view)
        self.assertIn("timer.IsVisible && !timer.IsExpired", view)
        self.assertIn("Message.CountdownTimer.EndTimestamp - Kinoa.Time.GetUnixTime()", view)
        self.assertIn('left.ToString(@"hh\\:mm\\:ss")', view)
        self.assertIn('left.Days > 0 ? $"{left.Days}d {clock}" : clock', view)
        self.assertIn("private void BindPriceBeforeSale()", view)
        self.assertIn("packages.AndroidDiscountPackageID", view)
        self.assertIn("KinoaInAppHooks.ResolveStorePrice(packages, true)", view)
        self.assertIn("private void BindResourceArea()", view)
        self.assertIn("item.SetLabel(resource.Amount.ToString());", view)
        self.assertIn("KinoaInAppHooks.ResolveResourceIcon", view)
        self.assertNotIn("BindFeature", view)
        self.assertNotIn("Kinoa.Data.Messaging.InApp.Features", view)

    def test_price_zone_absent_when_no_billing(self):
        t = copy.deepcopy(TEMPLATE)
        t["buttons"][1]["clickActionType"] = ["close", "deep_link"]
        plan = _plan(template=t)
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertNotIn("BindPriceBeforeSale", view)
        self.assertNotIn("BindResourceArea", view)
        self.assertIn("BindTimer();", view)




def _view(plan, options=None):
    return mod.generate_code(plan, options or {})["files"][plan["paths"]["view_path"]]


def _method(view, signature):
    """The text of one generated method: from its signature to the next member declaration."""
    return re.split(r"\n        (?:private|public|internal) ", view.split(signature, 1)[1], 1)[0]


class TestMilestoneView(unittest.TestCase):
    def setUp(self):
        self.per_step = _view(_milestone_plan("per_step"))
        self.single_slot_plan = _milestone_plan("single_slot")
        self.single_slot = _view(self.single_slot_plan)
        self.single_main = _view(_milestone_plan("single_main"))
        self.collect_all_plan = _milestone_plan("single_slot", collect_all=True)
        self.collect_all = _view(self.collect_all_plan)

    def test_modes_are_what_the_helper_says(self):
        self.assertEqual(_milestone_plan("per_step")["milestone"]["cta_mode"], "per_step")
        self.assertEqual(self.single_slot_plan["milestone"]["single_cta"]["key"], "cta_button")
        self.assertIsNone(_milestone_plan("single_main")["milestone"]["single_cta"]["key"])
        self.assertEqual(self.collect_all_plan["milestone"]["collect_all"]["key"], "collect_all_button")

    def test_shared_milestone_members(self):
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all):
            self.assertIn("using Kinoa.Data.Messaging.InApp.Features;", view)
            self.assertIn("using Kinoa.Data.Messaging.InApp.Features.Milestones;", view)
            self.assertIn("private bool _collecting;", view)
            self.assertIn("private void BindFeature()", view)
            self.assertIn("var feature = Data.Feature as InAppMilestonesFeature;", view)
            self.assertIn("private KinoaInAppMilestoneStepView SpawnStep(KinoaInAppMilestoneStepView template)", view)
            self.assertIn("_spawned.Add(item.gameObject);", _method(view, "private KinoaInAppMilestoneStepView SpawnStep("))
            self.assertIn("private static float StepProgress(decimal progress, long previous, long score)", view)
            self.assertIn("private string StepLabel(InAppCustomButton button)", view)
            self.assertIn('"Collect"', _method(view, "private string StepLabel("))
            self.assertIn("private void FocusStep(int index, int count)", view)
            self.assertIn("Canvas.ForceUpdateCanvases();", view)
            self.assertIn("private void ApplyFeatureButton(Button button, KinoaText label, InAppCustomButton slot, string clickKey, List<uint> indexes, bool canBeHidden)", view)
            self.assertIn("private void OnFeatureButtonClicked(string clickKey, InAppCustomButton slot, List<uint> indexes)", view)
            self.assertIn("private async Task RunActionThenCollectAsync(InAppCustomButton slot, List<uint> indexes)", view)
            self.assertIn("private async Task CollectStepsAsync(List<uint> indexes)", view)
            self.assertIn("BindGrandPrize(steps);", view)
            self.assertIn("private void BindGrandPrize(List<InAppMilestoneStep> steps)", view)
            self.assertLess(view.index("BindButtons();"), view.index("BindFeature();"))

    def test_per_step_binds_each_step_with_its_own_button(self):
        bind = _method(self.per_step, "private void BindFeature()")
        self.assertIn("SpawnStep(milestoneStepTemplate)", bind)
        self.assertIn("item.SetScore(step.Score.ToString());", bind)
        self.assertIn("item.SetStatus(step.Status);", bind)
        self.assertIn("item.SetProgress(StepProgress(feature.Progress, previous, step.Score));", bind)
        self.assertIn("item.SetReward(", bind)
        self.assertIn('"milestone_step_"', bind)
        self.assertIn("new List<uint> { index }", bind)
        self.assertIn("step.Status != InAppMilestoneStatus.Collected, step.Status == InAppMilestoneStatus.Reached, StepLabel(step.Button)", bind)
        self.assertIn('ApplyFeatureButton(milestoneMainButton, milestoneMainButtonLabel, feature.ActiveProgressButton, "milestone_main",\n'
                      '                FeatureIndexes(feature.ActiveProgressButton, steps, reached), canBeHidden: true);', bind)
        self.assertNotIn("BindSingleCta", self.per_step)
        self.assertNotIn("item.SetCollect(false, false, null, null);", self.per_step)

    def test_single_slot_reassigns_the_ready_step_cta(self):
        self.assertIn("item.SetCollect(false, false, null, null);", self.single_slot)
        self.assertIn("BindSingleCta(feature, steps, reached);", self.single_slot)
        cta = _method(self.single_slot, "private void BindSingleCta(")
        self.assertIn('ApplyFeatureButton(ctaButton, ctaButtonLabel, steps[(int)reached[0]].Button, "milestone_step_" + reached[0], new List<uint> { reached[0] }, canBeHidden: false);', cta)
        self.assertIn('ApplyFeatureButton(ctaButton, ctaButtonLabel, feature.ActiveProgressButton, "milestone_main", new List<uint>(), canBeHidden: false);', cta)
        self.assertNotIn("SetActive(false)", cta)            # an idle template slot keeps its BindButtons binding
        self.assertNotIn("ApplyFeatureButton(milestoneMainButton", self.single_slot)
        self.assertNotIn("milestoneMainButton", self.single_slot)   # the node does not exist on this view
        self.assertIn('ApplyButton(ctaButton, ctaButtonLabel, "cta_button", canBeHidden: false);', self.single_slot)

    def test_single_main_hides_main_button_when_idle(self):
        cta = _method(self.single_main, "private void BindSingleCta(")
        self.assertIn("steps[(int)reached[0]].Button", cta)
        self.assertIn("ApplyFeatureButton(milestoneMainButton, milestoneMainButtonLabel, feature.ActiveProgressButton", cta)
        self.assertIn("milestoneMainButton.gameObject.SetActive(false)", cta)
        self.assertIn("item.SetCollect(false, false, null, null);", self.single_main)
        self.assertNotIn("ctaButton", self.single_main)

    def test_collect_all_present_only_when_detected(self):
        ca = self.collect_all_plan["milestone"]["collect_all"]
        bind = _method(self.collect_all, "private void BindFeature()")
        self.assertIn('Data.Buttons?.TryGetValue("collect_all_button", out collectAllSlot);', bind)
        self.assertIn("var collectAllIndexes = FeatureIndexes(collectAllSlot, steps, reached);", bind)
        self.assertIn('ApplyFeatureButton(%s, %s, collectAllSlot, "collect_all_button", collectAllIndexes, canBeHidden: true);'
                      % (ca["button_field"], ca["label_field"]), bind)
        self.assertIn("%s.interactable = collectAllSlot != null && collectAllIndexes.Count > 0;" % ca["button_field"], bind)
        self.assertLess(bind.index("FeatureIndexes(collectAllSlot"), bind.index('"collect_all_button", collectAllIndexes'))
        self.assertLess(bind.index('"collect_all_button", collectAllIndexes'), bind.index("FocusStep("))
        for view in (self.per_step, self.single_slot, self.single_main):
            self.assertNotIn("collectAllIndexes", view)
            self.assertNotIn("collectAllSlot", view)

    def test_click_resolution(self):
        click = _method(self.per_step, "private void OnFeatureButtonClicked(")
        order = ["if (_collecting) return;",
                 "Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));",
                 "ButtonClicked?.Invoke(this, clickKey, slot?.ClickConfig);",
                 "is InAppCloseClickConfiguration", "Close();",
                 "if (IsFreeClick(config))",
                 "if (indexes.Count > 0) _ = CollectStepsAsync(indexes);",
                 "_ = RunActionThenCollectAsync(slot, indexes);"]
        positions = [click.index(s) for s in order]
        self.assertEqual(positions, sorted(positions))
        apply = _method(self.per_step, "private void ApplyFeatureButton(")
        self.assertIn("ApplyButtonSlot(button, label, clickKey, slot, canBeHidden);", apply)
        self.assertIn("if (button == null) return;", apply)
        self.assertIn("button.onClick.RemoveAllListeners();", apply)
        self.assertIn("button.onClick.AddListener(() => OnFeatureButtonClicked(clickKey, slot, indexes));", apply)

    def test_free_click_predicate_is_defined_once(self):
        cond = "config == null || config is InAppCollectResourceClickConfiguration || config is InAppPromiseRewardsClickConfiguration"
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all):
            self.assertEqual(view.count(cond), 1)
            self.assertIn("private static bool IsFreeClick(InAppClickConfiguration config) =>\n            " + cond + ";", view)

    def test_feature_indexes_follow_the_buttons_own_config(self):
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all):
            body = _method(view, "private static List<uint> FeatureIndexes(")
            self.assertIn("(InAppCustomButton slot, List<InAppMilestoneStep> steps, List<uint> reached)", view)
            # a paid / ad / link button: its own action gates every reached step
            self.assertIn("if (!IsFreeClick(slot?.ClickConfig)) return reached;", body)
            # a free button: only reached steps whose own CTA is free too
            self.assertIn("foreach (var index in reached)", body)
            self.assertIn("if (IsFreeClick(steps[(int)index]?.Button?.ClickConfig)) free.Add(index);", body)
            self.assertIn("return free;", body)
            self.assertLess(body.index("return reached;"), body.index("return free;"))

    def test_single_cta_keeps_the_ready_steps_own_button(self):
        for view in (self.single_slot, self.single_main):
            cta = _method(view, "private void BindSingleCta(")
            self.assertIn("new List<uint> { reached[0] }", cta)
            self.assertNotIn("FeatureIndexes", cta)

    def test_kept_visible_button_without_slot_is_inert(self):
        apply = _method(self.per_step, "private void ApplyFeatureButton(")
        branch = apply.split("if (slot == null)")[1].split("return;")[0]
        self.assertIn("if (!canBeHidden)", branch)
        self.assertIn("button.onClick.RemoveAllListeners();", branch)
        self.assertIn("button.interactable = false;", branch)
        rest = apply.split("if (slot == null)")[1].split("return;", 1)[1]
        self.assertLess(rest.index("button.interactable = true;"), rest.index("AddListener"))
        self.assertLess(apply.index("ApplyButtonSlot("), apply.index("if (slot == null)"))

    def test_paid_step_never_collects_without_hook(self):
        view = self.per_step
        body = view.split("private async Task RunActionThenCollectAsync")[1].split("private ")[0]
        guard = body.split("KinoaInAppFeatureHooks.RunButtonAction == null")[1].split("return;")[0]
        self.assertNotIn("CollectStepsAsync", guard)
        self.assertIn("KinoaInAppFeatureHooks.WarnMissing(nameof(KinoaInAppFeatureHooks.RunButtonAction));", guard)
        self.assertIn("await KinoaInAppFeatureHooks.RunButtonAction(Message, slot)", body)
        catch = body.split("catch (Exception e)")[1].split("finally")[0]
        self.assertIn("return;", catch)
        self.assertNotIn("CollectStepsAsync", catch)
        self.assertIn("if (this == null) return;", body)
        self.assertIn("if (done && indexes.Count > 0) await CollectStepsAsync(indexes);", body)

    def test_collect_failure_is_caught_and_rebinds(self):
        body = _method(self.per_step, "private async Task CollectStepsAsync(")
        catch = body.split("catch (Exception e)")[1].split("finally")[0]
        self.assertIn('Debug.LogWarning($"[{GetType().Name}] milestone collect failed for steps {string.Join(",", indexes)}: {e.Message}");', catch)
        self.assertIn("if (this != null) Bind(Message);", catch)
        self.assertLess(body.index("catch (Exception e)"), body.index("finally"))
        self.assertIn("_collecting = false;", body.split("finally")[1])

    def test_collect_is_guarded_against_double_tap(self):
        body = _method(self.per_step, "private async Task CollectStepsAsync(")
        self.assertIn("if (_collecting) return;", _method(self.per_step, "private void OnFeatureButtonClicked("))
        self.assertLess(body.index("_collecting = true;"), body.index("try"))
        self.assertIn("finally", body)
        self.assertIn("_collecting = false;", body.split("finally")[1])

    def test_rewards_read_before_rebind(self):
        view = self.per_step
        body = view.split("private async Task CollectStepsAsync")[1]
        self.assertLess(body.index("var steps = "), body.index("Kinoa.Messaging.CollectMilestonesAsync(Message, indexes)"))
        self.assertLess(body.index("Button.Resources"), body.index("Bind(response.Data.InApp);"))
        self.assertIn("var steps = (Data.Feature as InAppMilestonesFeature)?.Steps;", body)
        self.assertIn("foreach (var index in response.Data.Collected)", body)
        self.assertIn("%s apply steps[(int)index].Button.Resources to the player's economy here (same place as KinoaUiService.GrantRewards)." % mod.TODO, body)
        self.assertIn("response?.Error?.Message", body)
        self.assertLess(body.index("Bind(response.Data.InApp);"), body.index("Message.SetMilestonesStatusAsCollected(response.Data.Collected);"))
        fail = body.split("response?.Error?.Message")[1].split("return;")[0]
        self.assertIn("Bind(Message);", fail)

    def test_empty_and_finished_ladders_are_safe(self):
        view = self.per_step
        self.assertIn("count > 1 ? (float)index / (count - 1) : 0f", view)
        self.assertIn("feature.Steps ?? new List<InAppMilestoneStep>()", view)
        self.assertIn("progress >= score ? 1f : 0f", view)
        self.assertIn("Mathf.Clamp01((float)((progress - previous) / (score - previous)))", view)
        focus = _method(view, "private void FocusStep(")
        self.assertIn("count == 0", focus)
        bind = _method(view, "private void BindFeature()")
        self.assertIn("milestoneScroll.gameObject.SetActive(feature != null);", bind)
        self.assertLess(bind.index("InAppMilestoneStatus.Reached"), bind.index("InAppMilestoneStatus.Closed"))
        self.assertIn("focus = steps.Count - 1;", bind)

    def test_rebind_hides_old_steps_before_layout(self):
        # ClearSpawned's Destroy is deferred to end of frame: the old steps must not stay in the layout FocusStep measures.
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all):
            bind = _method(view, "private void BindFeature()")
            self.assertIn("foreach (Transform child in milestoneStepTemplate.transform.parent)", bind)
            self.assertIn("if (child != milestoneStepTemplate.transform) child.gameObject.SetActive(false);", bind)
            self.assertLess(bind.index("child.gameObject.SetActive(false);"), bind.index("SpawnStep(milestoneStepTemplate)"))
            self.assertLess(bind.index("SpawnStep(milestoneStepTemplate)"), bind.index("FocusStep(focus, steps.Count);"))
            focus = _method(view, "private void FocusStep(")
            self.assertLess(focus.index("LayoutRebuilder.ForceRebuildLayoutImmediate(milestoneContent);"),
                            focus.index("milestoneScroll.horizontalNormalizedPosition ="))

    def test_focus_waits_until_the_view_is_active(self):
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all):
            self.assertIn("private int _pendingFocusIndex = -1;", view)
            self.assertIn("private int _pendingFocusCount;", view)
            focus = _method(view, "private void FocusStep(")
            inactive = focus.split("if (!isActiveAndEnabled)")[1].split("}")[0]
            self.assertIn("_pendingFocusIndex = index;", inactive)
            self.assertIn("_pendingFocusCount = count;", inactive)
            self.assertIn("return;", inactive)
            self.assertLess(focus.index("if (!isActiveAndEnabled)"), focus.index("Canvas.ForceUpdateCanvases();"))
            self.assertLess(focus.index("_pendingFocusIndex = -1;"), focus.index("Canvas.ForceUpdateCanvases();"))
            enable = _method(view, "private void OnEnable()")
            self.assertIn("if (_pendingFocusIndex < 0) return;", enable)
            self.assertIn("StartCoroutine(ApplyPendingFocusNextFrame());", enable)
            later = _method(view, "private System.Collections.IEnumerator ApplyPendingFocusNextFrame()")
            self.assertLess(later.index("yield return null;"), later.index("FocusStep(_pendingFocusIndex, _pendingFocusCount);"))
            self.assertEqual(view.count("private void OnEnable()"), 1)

    def test_milestone_view_needs_no_change_to_old_shared_files(self):
        hooks = _read_exact(os.path.join(GOLDEN, "hooks.cs"))
        hook_members = set(re.findall(r"(?:public|internal) static [^=(]*?(\w+)\s*(?:=|\()", hooks))
        item_members = set(re.findall(r"public \w+ (\w+)\(", _read_exact(os.path.join(GOLDEN, "item_view_legacy.cs"))))
        step_members = set(re.findall(r"public \w+ (\w+)\(", mod.render_milestone_step_view("legacy")))
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all):
            used = set(re.findall(r"KinoaInAppHooks\.(\w+)", view))
            self.assertTrue(used <= hook_members, used - hook_members)
            for method in re.split(r"\n        (?=private |public |internal )", view):
                for var in re.findall(r"var (\w+) = Spawn\(", method):
                    calls = set(re.findall(r"\b%s\.(\w+)\(" % var, method))
                    self.assertTrue(calls <= item_members, calls - item_members)
                for var in re.findall(r"var (\w+) = SpawnStep\(", method):
                    calls = set(re.findall(r"\b%s\.(\w+)\(" % var, method))
                    self.assertTrue(calls <= step_members, calls - step_members)
            milestone_part = view.split("// ------------------------------------------------------------------ milestones feature")[1]
            self.assertNotIn("KinoaInAppItemView", milestone_part)

    def test_standard_and_mission_views_have_no_milestone_code(self):
        # the milestone FEATURE's code: never on a standard view, never on a mission view
        feature_only = ("InAppMilestonesFeature", "InAppMilestoneStep>", "milestoneScroll", "_collecting",
                        "CollectMilestonesAsync", "OnFeatureButtonClicked", "SpawnStep(", "FeatureIndexes(",
                        "_pendingFocus", "ApplyPendingFocusNextFrame", "BindGrandPrize")
        for plan in (_plan(), _mission_plan()):
            for options in ({}, {"facade": "present"}):
                view = _view(plan, options)
                for bad in feature_only:
                    self.assertNotIn(bad, view)
        # a standard view has no ladder at all; a mission view's ladder is the missions bar (TestMissionLadder)
        for options in ({}, {"facade": "present"}):
            view = _view(_plan(), options)
            for bad in ("InAppMilestone", "MilestoneStepView", "KinoaInAppFeatureHooks", "OnEnable"):
                self.assertNotIn(bad, view)

    def test_plan_without_the_scroll_ladder_is_refused(self):
        for drop in ("block", "scroll"):
            plan = copy.deepcopy(self.single_slot_plan)
            if drop == "block":
                plan.pop("milestone")                    # a plan written before the milestone scroll ladder
            else:
                plan["nodes"] = [n for n in plan["nodes"] if n["name"] != "MilestoneScroll"]
            with self.assertRaises(mod.PlanOutdatedError):
                mod.generate_code(plan, {})

    def test_tmp_variant(self):
        tmp_style = dict(STYLE, text_system="tmp", tmp_font_guid="0123456789abcdef0123456789abcdef")
        view = _view(_milestone_plan("single_slot", collect_all=True, style=tmp_style))
        self.assertIn("using KinoaText = TMPro.TMP_Text;", view)
        self.assertIn("private void ApplyFeatureButton(Button button, KinoaText label,", view)

    def test_no_forbidden_strings(self):
        for view in (self.per_step, self.single_slot, self.single_main, self.collect_all,
                     _view(self.collect_all_plan, {"facade": "present"})):
            for bad in FORBIDDEN:
                self.assertNotIn(bad, view)


class TestGoldenViews(unittest.TestCase):
    def test_standard_and_milestone_views_unchanged(self):
        # Goldens rendered from the module at the milestone base (6d5deb8 "Milestone template to prefab") with
        # these exact inputs: the missions work must leave standard and milestone views byte-identical.
        for name, plan in (("one_cta_view.cs.txt", _plan()),
                           ("milestone_view.cs.txt", _milestone_plan("single_slot")),
                           ("milestone_per_step_view.cs.txt", _milestone_plan("per_step")),
                           ("milestone_single_main_collect_all_view.cs.txt", _milestone_plan("single_main", collect_all=True))):
            self.assertEqual(_view(plan), _read_exact(os.path.join(GOLDEN_VIEWS, name)), "%s drifted from the golden" % name)


class TestViewMissions(unittest.TestCase):
    def setUp(self):
        self.view = _view(_mission_plan())

    def test_mission_view_declarations(self):
        v = self.view
        for s in ("using System.Linq;", "using UnityEngine.Events;", "using Kinoa.Data.Messaging.InApp.Features.Missions;",
                  "public event Action<KinoaInAppDailyMissionsView, int, InAppMission, InAppClickConfiguration> MissionCtaClicked;",
                  "private int? _selectedSetNumber;", "private string _boundMessageId;",
                  "private readonly List<GameObject> _missionRows = new List<GameObject>();",
                  "private readonly HashSet<(int setNumber, int rowNumber)> _dismissedRows",
                  "private readonly HashSet<int> _collectedBarRows", "private bool _missionBusy;",
                  "private void BindFeature()", "private void ShowMissionSet(InAppMissionSetProgress set)",
                  "private async Task CollectMissionAsync(KinoaInAppMissionRowView row, int setNumber, InAppMission mission)",
                  "private async Task DismissMissionAsync(int setNumber, InAppMission mission)",
                  "private void BindMissionBar(InAppMissionsProgress state)",
                  "private async Task CollectMissionBarStepAsync(int setNumber, List<InAppMissionsMilestoneStep> steps)",
                  "private void SetMissionBusy(bool busy)",
                  "private void ApplyMissionActionButton(Button button, KinoaText label, string key, bool canBeHidden, bool show, bool interactable, Func<Task> action)",
                  "private T SpawnMission<T>(T template, List<GameObject> into) where T : Component",
                  '[Header("Missions")]', "[SerializeField] private KinoaInAppTabView missionTabTemplate;",
                  "[SerializeField] private KinoaInAppMissionRowView missionRowTemplate;",
                  "[SerializeField] private ScrollRect missionScroll;"):
            self.assertIn(s, v)
        for bad in FORBIDDEN:
            self.assertNotIn(bad, v)

    def test_bind_resets_per_message_state_before_replacing_message(self):
        bind = _method_body(self.view, "public bool Bind(InAppMessage message)")
        self.assertLess(bind.index("if (message.MessageId != _boundMessageId)"), bind.index("_dismissedRows.Clear();"))
        self.assertLess(bind.index("_collectedBarRows.Clear();"), bind.index("Message = message;"))

    def test_mission_view_tabs_and_selection(self):
        v = self.view
        for s in ("state.PreviousSetProgress", '$"Set {set.SetNumber} (prev)"', '$"Set {set.SetNumber}"',
                  "_selectedSetNumber", "?? state.ActiveSetProgress", "HasRows("):
            self.assertIn(s, v)
        # the selected set survives a rebind only while it still has rows; else the active set (D4)
        self.assertIn("_selectedSetNumber == state.PreviousSetProgress?.SetNumber && HasRows(state.PreviousSetProgress)", v)
        self.assertIn("_dismissedRows.Contains((set.SetNumber, m.RowNumber))", v)   # dismissed rows never count

    def test_mission_view_selection_skips_an_emptied_set(self):
        """D4 + final review #2: a selected or active set left without visible rows (all dismissed) never wins
           over a set that still has rows; the bare active set is only the last resort."""
        body = _method_body(self.view, "private void BindFeature()")
        self.assertIn(
            "            var target = (_selectedSetNumber == state.PreviousSetProgress?.SetNumber && HasRows(state.PreviousSetProgress) ? state.PreviousSetProgress : null)\n"
            "                         ?? (_selectedSetNumber == state.ActiveSetProgress?.SetNumber && HasRows(state.ActiveSetProgress) ? state.ActiveSetProgress : null)\n"
            "                         ?? (HasRows(state.ActiveSetProgress) ? state.ActiveSetProgress : null)\n"
            "                         ?? (HasRows(state.PreviousSetProgress) ? state.PreviousSetProgress : null)\n"
            "                         ?? state.ActiveSetProgress;\n", body)
        pick = _selection(body)
        # active set all dismissed, previous set has rows: the previous set, whichever was selected
        for selected in (None, 1, 2):
            self.assertEqual(pick(selected, prev=(1, True), active=(2, False)), "prev", selected)
        self.assertEqual(pick(2, prev=(1, True), active=(2, True)), "active")      # selection kept while it has rows
        self.assertEqual(pick(1, prev=(1, True), active=(2, True)), "prev")
        self.assertEqual(pick(1, prev=(1, False), active=(2, True)), "active")     # emptied previous set: back to active
        self.assertEqual(pick(None, prev=None, active=(2, False)), "active")       # nothing has rows: the empty active set
        self.assertEqual(pick(None, prev=(1, False), active=None), None)

    def test_mission_view_cards(self):
        v = self.view
        for s in ("row.SetPlacement(mission.PlacementNumber);", "row.SetTitle(mission.MissionText);",
                  "row.SetSubMission(mission.SubMissionNumber);", "row.SetStatus(mission.Status.ToString());",
                  "row.SetProgress(mission.CurrentScore, mission.GoalScore);",
                  "row.AddReward(ResolveIcon(resource.ResourceKey), resource.Amount.ToString());",
                  "InAppMissionStatus.Reached => 0", "ThenBy(m => m.PlacementNumber)",
                  "Kinoa.Messaging.CollectMissionsProgressAsync(Message, setNumber, new List<int> { mission.RowNumber })",
                  "MissionCtaClicked?.Invoke(this, setNumber, mission, mission.ProgressionCta);",
                  'row.SetAction("Go", () => OnMissionProgressionClicked(setNumber, captured));',
                  "private void OnMissionProgressionClicked(int setNumber, InAppMission mission)",
                  "%s route mission.ProgressionCta" % mod.TODO, "mission.CompletionCta", "mission.ProcessedResources",
                  'row.SetAction("Collect",', 'row.SetAction("Go",', "row.SetAction(null, null);"):
            self.assertIn(s, v)
        self.assertIn("the int is the mission's setNumber", v)   # the event's XML doc names the extra argument
        go = [l.strip() for l in v.splitlines() if l.strip().startswith("// %s route mission.ProgressionCta" % mod.TODO)]
        self.assertEqual(len(go), 1)   # one TODO line covering every Go action (final review #3)
        for s in ("deep_link / web_link", "show_ad",
                  "Kinoa.Messaging.ReachMissionsProgress(Message, setNumber, new List<int> { mission.RowNumber })",
                  "Bind(response.Data)", "close", "Close()"):
            self.assertIn(s, go[0])
        # collect TODOs grant only what the server confirms (final review #5), like the SDK sample's GetCollectedRows
        for decl in ("private async Task CollectMissionAsync(", "private async Task CollectAllMissionsAsync()"):
            todo = [l for l in _method_body(v, decl).splitlines() if mod.TODO in l]
            self.assertEqual(len(todo), 1, decl)
            self.assertIn("response.Data", todo[0], decl)
            self.assertIn("no longer Reached (Collected or removed)", todo[0], decl)
        body = _method_body(v, "private void ShowMissionSet(InAppMissionSetProgress set)")   # ruling R5
        self.assertIn("row.SetStatus(", body)
        self.assertNotIn(".color =", body)   # D6: no status recolouring

    def test_resolve_icon_emitted_exactly_once(self):
        self.assertEqual(self.view.count("private static Sprite ResolveIcon(string resourceKey)"), 1)
        t = copy.deepcopy(MISSIONS); t["features"]["mission"]["progressBar"] = {"display": "dont_show_at_all"}
        plan = _plan(template=t, layout=None)
        self.assertIn("ResourceArea", {n["name"] for n in plan["nodes"]})   # resource area AND missions both need it
        self.assertEqual(_view(plan).count("private static Sprite ResolveIcon(string resourceKey)"), 1)

    def test_mission_view_dismiss(self):
        v = self.view
        for s in ("Kinoa.Messaging.DeleteMissionsProgress(Message, setNumber, new List<int> { mission.RowNumber })",
                  "_dismissedRows.Add((setNumber, mission.RowNumber));",
                  "mission.Status == InAppMissionStatus.Reached || mission.Status == InAppMissionStatus.Collected",
                  "row.SetDismiss("):
            self.assertIn(s, v)

    def test_mission_view_bar_like_milestones(self):
        v = self.view
        for s in ("state.ProgressBarState", "OrderBy(s => s.MilestoneNumber)",
                  "Kinoa.Messaging.CollectMissionsMilestonesProgress(Message, setNumber,", "_collectedBarRows.Add(",
                  "InAppMilestoneStatus.Reached", "%s apply step.Button.Resources" % mod.TODO):
            self.assertIn(s, v)
        bar_todo = [l for l in _method_body(v, "private async Task CollectMissionBarStepAsync(").splitlines() if mod.TODO in l]
        self.assertEqual(len(bar_todo), 1)
        # the milestone view's grant TODO: the click config was already resolved (ClaimMissionBarStepsAsync), so it
        # names only the resources, as the milestone view's CollectStepsAsync does
        self.assertEqual(bar_todo[0].strip(), "// %s apply step.Button.Resources to the player's economy here "
                                              "(same place as KinoaUiService.GrantRewards)." % mod.TODO)
        for gone in ("missionBarFill", "missionBarRoot", "missionBarMarkerTemplate", "_missionBarMarkers", "KinoaInAppItemView>(out var marker"):
            self.assertNotIn(gone, v)

    def test_mission_view_action_buttons_only_when_in_template(self):
        v = self.view
        for s in ("Kinoa.Messaging.ReachMissionsProgress(Message,", "private async Task CollectAllMissionsAsync()",
                  "private async Task CollectAllMissionBarStepsAsync()",
                  'ApplyMissionActionButton(collectAllButton, collectAllButtonLabel, "collect_all_button"',
                  'ApplyMissionActionButton(collectAllMilestonesButton, collectAllMilestonesButtonLabel, "collect_all_milestones_button"'):
            self.assertIn(s, v)
        self.assertNotIn("ApplyButton(collectAllButton,", v)      # D2
        self.assertIn('ApplyButton(closeButton, closeButtonLabel, "close_button", canBeHidden: true);', v)
        t = copy.deepcopy(MISSIONS); t["buttons"] = [b for b in t["buttons"] if b["key"] == "close_button"]
        v2 = _view(_plan(template=t, layout=mod.layout_from_artifact(ART_RAW_WITHOUT_ACTION_BUTTONS)))
        # (the Go TODO names ReachMissionsProgress for show_ad CTAs; the reach-all call itself is gone)
        for s in ("ReachMissionsProgress(Message, set.SetNumber", "ReachAllMissionsAsync", "CollectAllMissionsAsync",
                  "CollectAllMissionBarStepsAsync", "collectAllButton"):
            self.assertNotIn(s, v2)
        self.assertIn("DeleteMissionsProgress", v2)               # dismiss is always there

    def test_feature_action_click_bypasses_facade(self):
        plan = _mission_plan()
        v = mod.generate_code(plan, {"facade": "present"})["files"][plan["paths"]["view_path"]]
        apply = _method_body(v, "private void ApplyMissionActionButton(")
        for s in ("Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));",
                  "ButtonClicked?.Invoke(this, key, slot?.ClickConfig);", "_ = action();", "ResolveButtonLabel(slot)"):
            self.assertIn(s, apply)
        self.assertNotIn("KinoaUiService", apply)
        self.assertLess(apply.index("SendInAppClickEvent"), apply.index("_ = action();"))

    def test_boolean_custom_on_feature_action_button_survives_rerenders(self):
        """Final review #4: re-renders re-show feature-action buttons, so a boolean custom mapped onto one
           must be part of its visibility, not only the one-shot ApplySlotToggle in Bind."""
        t = copy.deepcopy(MISSIONS)
        for key in ("show_collect_all_button", "show_collect_all_milestones_button"):
            t["customs"].append({"key": key, "kind": "boolean", "name": key, "index": len(t["customs"]) + 20,
                                 "nullable": True, "description": "", "canBeHidden": True, "customFields": [],
                                 "defaultValue": True})
        plan = _plan(template=t, layout=mod.layout_from_artifact(ART_RAW))
        targets = {c["key"]: c["target_node"] for c in plan["customs"]}
        fields = {n["name"]: n["field"] for n in plan["nodes"]}
        self.assertEqual(fields[targets["show_collect_all_button"]], "collectAllButton")
        self.assertEqual(fields[targets["show_collect_all_milestones_button"]], "collectAllMilestonesButton")
        v = _view(plan)
        self.assertIn('show: missions.Any(m => m.Status == InAppMissionStatus.Reached) && '
                      '!(TryGetCustom<bool>("show_collect_all_button", out var collectAllButtonOn) && !collectAllButtonOn),', v)
        self.assertIn('show: hasBar && !(TryGetCustom<bool>("show_collect_all_milestones_button", out var collectAllMilestonesButtonOn)'
                      ' && !collectAllMilestonesButtonOn),', v)
        self.assertIn('show: missions.Any(m => m.Status == InAppMissionStatus.Active), interactable:', v)   # unmapped: unchanged
        # nothing maps onto a feature-action button in the fixture: no extra visibility term anywhere
        self.assertNotIn("ButtonOn", self.view)
        self.assertNotIn("TryGetCustom<bool>(\"show_", self.view)

    def test_mission_view_busy_state(self):
        v = self.view
        for decl in ("private async Task CollectMissionAsync(", "private async Task DismissMissionAsync(",
                     "private async Task CollectAllMissionsAsync()", "private async Task ReachAllMissionsAsync()",
                     "private async Task CollectMissionBarStepAsync("):
            body = _method_body(v, decl)
            self.assertIn("SetMissionBusy(true);", body, decl)
            self.assertIn("SetMissionBusy(false);", body, decl)   # failure path re-enables
            self.assertIn("response?.Error?.Message", body, decl)
        self.assertIn("if (_missionBusy) return;", v)

    def test_mission_view_null_guards(self):
        v = self.view
        for s in ("var state = feature?.MissionState;", "if (state == null)", "set?.ActiveMissions",
                  "bar?.Milestones == null || bar.Milestones.Count == 0", "if (this == null) return;"):
            self.assertIn(s, v)
        # every mission await is followed by the destroyed-view guard
        lines = v.splitlines()
        for i, line in enumerate(lines):
            if re.match(r"\s*(var \w+ = )?await Kinoa\.Messaging\.|\s*await (Collect|Claim|RunBar)", line):
                # the guard follows every await, unless the await is the method's last statement
                self.assertIn(lines[i + 1].strip(), ("if (this == null) return;", "}"), line.strip())
            if "await KinoaInAppFeatureHooks.RunButtonAction" in line:
                self.assertIn("if (this == null) return;", "\n".join(lines[i:i + 8]))

    def test_mission_view_without_bar_has_no_bar_code(self):
        t = copy.deepcopy(MISSIONS); t["features"]["mission"]["progressBar"] = {"display": "dont_show_at_all"}
        v = _view(_plan(template=t, layout=None))
        for s in ("missionBarScroll", "missionBarStepTemplate", "CollectMissionsMilestonesProgress", "KinoaInAppMilestoneStepView",
                  "KinoaInAppFeatureHooks", "_missionBarSteps", "OnEnable", "IsFreeClick"):
            self.assertNotIn(s, v)
        # without a bar, the milestones button is an ordinary template button routed like any other
        self.assertIn('ApplyButton(collectAllMilestonesButton, collectAllMilestonesButtonLabel, "collect_all_milestones_button"', v)

    def test_mission_view_tmp_alias(self):
        style = dict(STYLE, text_system="tmp", tmp_font_guid="cccccccccccccccccccccccccccccccc")
        v = _view(_plan(template=MISSIONS, style=style, layout=mod.layout_from_artifact(ART_RAW)))
        self.assertIn("using KinoaText = TMPro.TMP_Text;", v)



class TestMissionLadder(unittest.TestCase):
    """Rule 2: ProgressBarState is the milestone ladder - KinoaInAppMilestoneStepView steps claimed through the
       milestone click resolver (close / free collect / RunButtonAction then collect)."""

    def setUp(self):
        self.plan = _mission_plan()
        self.view = _view(self.plan)
        self.bind = _method_body(self.view, "private void BindMissionBar(InAppMissionsProgress state)")

    def test_fields_are_the_ladder(self):
        for decl in ("[SerializeField] private ScrollRect missionBarScroll;",
                     "[SerializeField] private RectTransform missionBarContent;",
                     "[SerializeField] private KinoaInAppMilestoneStepView missionBarStepTemplate;",
                     "private readonly List<GameObject> _missionBarSteps = new List<GameObject>();"):
            self.assertIn(decl, self.view)

    def test_one_step_view_per_step_ordered_by_milestone_number(self):
        b = self.bind
        self.assertIn("bar.Milestones.Where(s => s != null).OrderBy(s => s.MilestoneNumber).ToList()", b)
        self.assertIn("var item = SpawnMission(missionBarStepTemplate, _missionBarSteps);", b)
        self.assertLess(b.index("OrderBy(s => s.MilestoneNumber)"), b.index("SpawnMission(missionBarStepTemplate"))
        self.assertIn("missionBarScroll.gameObject.SetActive(hasBar);", b)
        self.assertIn("ClearMission(_missionBarSteps);", b)

    def test_step_is_bound_like_a_milestone_step(self):
        b = self.bind
        self.assertIn('item.SetScore(step.Score.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture));', b)
        # reward: the first Button.Resources entry's icon through ResolveIcon, amount as on the milestone view
        self.assertIn("var resources = step.Button?.Resources;", b)
        self.assertIn("ResolveIcon(resources[0].ResourceKey)", b)
        self.assertIn('resources.Count == 1 ? resources[0].Amount.ToString() : $"x{resources.Count}"', b)
        # progress: the share of the band between the previous step's score and this one's, as StepProgress
        self.assertIn("item.SetProgress(MissionStepProgress(bar.TotalScore, previous, step.Score));", b)
        progress = _method_body(self.view, "private static float MissionStepProgress(")
        self.assertIn("if (score > previous) return Mathf.Clamp01((float)((total - previous) / (score - previous)));", progress)
        self.assertIn("return total >= score ? 1f : 0f;", progress)
        self.assertIn("previous = step.Score;", b)
        # status: a row collected here (results only, no refreshed in-app) shows as Collected
        self.assertIn("var status = _collectedBarRows.Contains(step.RowNumber) ? InAppMilestoneStatus.Collected : step.Status;", b)
        self.assertIn("item.SetStatus(status);", b)
        # collect button: the milestone per-step rules - visible until collected, interactable when Reached
        self.assertIn("item.SetCollect(status != InAppMilestoneStatus.Collected,", b)
        self.assertIn("status == InAppMilestoneStatus.Reached && setNumber.HasValue && !_missionBusy, StepLabel(step.Button),", b)
        self.assertIn("() => OnMissionBarStepClicked(claimSet, captured));", b)
        self.assertIn('"Collect"', _method_body(self.view, "private string StepLabel("))

    def test_step_view_api_is_the_shared_one(self):
        step_members = set(re.findall(r"public \w+ (\w+)\(", mod.render_milestone_step_view("legacy")))
        calls = set(re.findall(r"\bitem\.(\w+)\(", self.bind))
        self.assertTrue(calls <= step_members, calls - step_members)
        self.assertEqual(calls, {"SetScore", "SetReward", "SetProgress", "SetStatus", "SetCollect"})

    def test_click_resolution_is_the_milestone_resolver(self):
        click = _method_body(self.view, "private void OnMissionBarStepClicked(")
        order = ["if (_missionBusy) return;", "Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));",
                 'ButtonClicked?.Invoke(this, "mission_bar_step_" + step.MilestoneNumber, step.Button?.ClickConfig);',
                 "_ = ClaimMissionBarStepsAsync(step.Button, setNumber, new List<InAppMissionsMilestoneStep> { step });"]
        positions = [click.index(x) for x in order]
        self.assertEqual(positions, sorted(positions))
        claim = _method_body(self.view, "private async Task ClaimMissionBarStepsAsync(")
        order = ["config is InAppCloseClickConfiguration", "Close();", "if (IsFreeClick(config))",
                 "if (steps.Count > 0) await CollectMissionBarStepAsync(setNumber, steps);",
                 "await RunBarActionThenCollectAsync(slot, setNumber, steps);"]
        positions = [claim.index(x) for x in order]
        self.assertEqual(positions, sorted(positions))
        cond = "config == null || config is InAppCollectResourceClickConfiguration || config is InAppPromiseRewardsClickConfiguration"
        self.assertEqual(self.view.count(cond), 1)

    def test_paid_step_never_collects_without_the_hook(self):
        body = _method_body(self.view, "private async Task RunBarActionThenCollectAsync(")
        guard = body.split("KinoaInAppFeatureHooks.RunButtonAction == null")[1].split("return;")[0]
        self.assertIn("KinoaInAppFeatureHooks.WarnMissing(nameof(KinoaInAppFeatureHooks.RunButtonAction));", guard)
        self.assertNotIn("Collect", guard)
        self.assertIn("try { done = await KinoaInAppFeatureHooks.RunButtonAction(Message, slot); }", body)
        catch = body.split("catch (Exception e)")[1].split("if (this == null) return;")[0]
        self.assertIn("done = false;", catch)
        self.assertNotIn("Collect", catch)
        failed = body.split("if (!done || steps.Count == 0)")[1].split("}")[0]
        self.assertIn("SetMissionBusy(false);", failed)
        self.assertIn("return;", failed)
        self.assertNotIn("Collect", failed)
        # the collect is reached only after the hook returned true
        self.assertLess(body.index("if (!done || steps.Count == 0)"), body.index("await CollectMissionBarStepAsync(setNumber, steps);"))
        self.assertLess(body.index("await KinoaInAppFeatureHooks.RunButtonAction"), body.index("await CollectMissionBarStepAsync"))

    def test_double_tap_is_guarded(self):
        body = _method_body(self.view, "private async Task RunBarActionThenCollectAsync(")
        self.assertIn("if (_missionBusy) return;", body)
        # busy is taken BEFORE the game's action is awaited: a second tap cannot start a second purchase
        self.assertLess(body.index("SetMissionBusy(true);"), body.index("await KinoaInAppFeatureHooks.RunButtonAction"))
        collect = _method_body(self.view, "private async Task CollectMissionBarStepAsync(")
        self.assertIn("if (_missionBusy || steps == null || steps.Count == 0) return;", collect)
        self.assertLess(collect.index("SetMissionBusy(true);"), collect.index("await Kinoa.Messaging.CollectMissionsMilestonesProgress"))
        self.assertIn("if (_missionBusy) return;", _method_body(self.view, "private void OnMissionBarStepClicked("))
        # while busy, every step button is disabled (the step view has no interactable setter of its own)
        busy = _method_body(self.view, "private void SetMissionBusy(bool busy)")
        self.assertIn("foreach (var stepButton in go.GetComponentsInChildren<Button>()) stepButton.interactable = false;", busy)

    def test_collect_reads_rewards_from_the_captured_steps_then_rebinds(self):
        collect = _method_body(self.view, "private async Task CollectMissionBarStepAsync(")
        self.assertIn("var rows = steps.Select(s => s.RowNumber).ToList();", collect)
        self.assertIn("Kinoa.Messaging.CollectMissionsMilestonesProgress(Message, setNumber, rows)", collect)
        self.assertIn("_collectedBarRows.Add(result.RowNumber);", collect)
        self.assertLess(collect.index("Button.Resources"), collect.index("Bind(Message);"))

    def test_throwing_collect_releases_the_busy_state(self):
        # as the milestone CollectStepsAsync: a failed or throwing request logs a warning and re-renders, never
        # leaving every mission control disabled
        collect = _method_body(self.view, "private async Task CollectMissionBarStepAsync(")
        self.assertLess(collect.index("SetMissionBusy(true);"), collect.index("try"))
        self.assertLess(collect.index("try"), collect.index("await Kinoa.Messaging.CollectMissionsMilestonesProgress"))
        catch = collect.split("catch (Exception e)")[1]
        self.assertIn('Debug.LogWarning($"[{GetType().Name}] mission bar rows {string.Join(", ", rows)} collect failed: {e.Message}");', catch)
        self.assertIn("if (this != null) SetMissionBusy(false);", catch)
        self.assertLess(collect.index("Bind(Message);"), collect.index("catch (Exception e)"))   # success path inside the try

    def test_collect_all_milestones_goes_through_the_resolver(self):
        v = self.view
        ca = _method_body(v, "private async Task CollectAllMissionBarStepsAsync()")
        self.assertIn('var slot = MissionSlot("collect_all_milestones_button");', ca)
        self.assertIn("var steps = CollectAllBarSteps(state, slot);", ca)
        self.assertIn("await ClaimMissionBarStepsAsync(slot, state.ActiveSetProgress.SetNumber, steps);", ca)
        self.assertNotIn("CollectMissionBarStepAsync", ca)   # never straight to the collect call
        # the milestone collect-all semantics: a free button takes only free steps; a paid one gates them all
        steps = _method_body(v, "private List<InAppMissionsMilestoneStep> CollectAllBarSteps(")
        self.assertIn("IsFreeClick(slot?.ClickConfig) ? claimable.Where(s => IsFreeClick(s.Button?.ClickConfig)).ToList() : claimable", steps)
        claimable = _method_body(v, "private List<InAppMissionsMilestoneStep> ClaimableBarSteps(")
        self.assertIn("s.Status == InAppMilestoneStatus.Reached && !_collectedBarRows.Contains(s.RowNumber)", claimable)
        self.assertIn('interactable: !_missionBusy && setNumber.HasValue && CollectAllBarSteps(state, MissionSlot("collect_all_milestones_button")).Count > 0', v)

    def test_focus_is_safe_on_empty_ladders_and_waits_for_the_view(self):
        focus = _method_body(self.view, "private void FocusMissionBarStep(")
        self.assertIn("if (missionBarScroll == null || count == 0) return;", focus)
        self.assertIn("count > 1 ? (float)index / (count - 1) : 0f", focus)
        self.assertIn("if (!isActiveAndEnabled)", focus)
        self.assertLess(focus.index("LayoutRebuilder.ForceRebuildLayoutImmediate(missionBarContent);"),
                        focus.index("missionBarScroll.horizontalNormalizedPosition ="))
        self.assertEqual(self.view.count("private void OnEnable()"), 1)

    def test_no_forbidden_strings(self):
        for options in ({}, {"facade": "present"}):
            for bad in FORBIDDEN:
                self.assertNotIn(bad, _view(self.plan, options))

    def test_outdated_mission_plans_are_refused(self):
        legacy = copy.deepcopy(self.plan)   # the release's flat list: MissionList is a plain zone
        for n in legacy["nodes"]:
            if n["name"] == "MissionList":
                n["binding"] = "zone"
        bar_and_markers = copy.deepcopy(self.plan)   # the bar-and-markers shape the ladder replaced
        bar_and_markers["nodes"].append(mod._node("MissionBar", "Panel", "zone", ["Image"], field="missionBarRoot",
                                                  field_type="GameObject", anchor_min=[0, 0], anchor_max=[1, 1]))
        for plan in (legacy, bar_and_markers):
            with self.assertRaises(mod.PlanOutdatedError):
                mod.generate_code(plan, {})

    def test_outdated_mission_plan_cli_error(self):
        import contextlib
        import io
        import tempfile
        root = tempfile.mkdtemp()
        plan = copy.deepcopy(self.plan)
        plan["nodes"] = [n for n in plan["nodes"] if n["name"] != "MissionTabs"]
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mod.main(["generate", "--plan", plan_path, "--project-root", root])
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(data["error"], "mission_plan_outdated")
        self.assertIn("re-run `plan`", data["detail"])
        self.assertEqual(os.listdir(root), ["p.json"])


class TestUnifiedScroll(unittest.TestCase):
    """Rule 3: one ScrollRect / viewport / content binding set in the builder; the mission list is its vertical use;
       a milestone plan (no scroll_axis) builds exactly as before."""
    B = mod.BUILDER_CS

    def test_one_case_per_scroll_binding(self):
        for case in ('case "scroll":', 'case "viewport":', 'case "scroll_content":', 'case "ScrollRect":',
                     'case "RectMask2D":', 'case "ContentSizeFitter":'):
            body = self.B
            self.assertEqual(body.count(case), 2 if case == 'case "ScrollRect":' else 1, case)   # ScrollRect: AddComponent + Resolve
        self.assertEqual(self.B.count("private static void WireScrollRects("), 1)
        self.assertNotIn("list_content", self.B)

    def test_vertical_is_opt_in_and_defaults_to_the_milestone_behaviour(self):
        self.assertIn("public string scroll_axis;", self.B)
        scroll = self.B.split('case "scroll":')[1].split("break;")[0]
        self.assertIn('if (node.scroll_axis == "vertical" && go.TryGetComponent<ScrollRect>(out var scroll))', scroll)
        self.assertIn("scroll.horizontal = false; scroll.vertical = true;", scroll)
        content = self.B.split('case "scroll_content":')[1].split("break;")[0]
        horizontal, vertical = content.split('if (node.scroll_axis == "vertical")')
        # the milestone base's horizontal path comes first, verbatim; its group lookup is a no-op on a vertical list
        for snippet in ("pivot = new Vector2(0f, 0.5f)", "GetComponent<HorizontalLayoutGroup>()", "spacing = 12f",
                        "padding = new RectOffset(8, 8, 8, 8)", "childControlWidth = true", "childControlHeight = true",
                        "childForceExpandWidth = false", "childForceExpandHeight = true"):
            self.assertIn(snippet, horizontal)
        # only a plan node that says scroll_axis "vertical" reaches the list settings
        self.assertIn("pivot = new Vector2(0.5f, 1f)", vertical)
        self.assertIn("listFitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;", vertical)
        component = self.B.split('case "ScrollRect":')[1].split("break;")[0]
        self.assertIn("sr.horizontal = true; sr.vertical = false;", component)

    def test_mission_list_is_the_vertical_scroll_chain(self):
        plan = _mission_plan()
        by = {n["name"]: n for n in plan["nodes"]}
        self.assertEqual((by["MissionList"]["binding"], by["MissionList"]["components"], by["MissionList"]["field"],
                          by["MissionList"]["field_type"], by["MissionList"]["scroll_axis"]),
                         ("scroll", ["ScrollRect"], "missionScroll", "ScrollRect", "vertical"))
        self.assertEqual((by["MissionViewport"]["parent"], by["MissionViewport"]["binding"], by["MissionViewport"]["components"]),
                         ("MissionList", "viewport", ["Image", "RectMask2D"]))
        self.assertEqual((by["MissionRows"]["parent"], by["MissionRows"]["binding"], by["MissionRows"]["components"],
                          by["MissionRows"]["scroll_axis"]),
                         ("MissionViewport", "scroll_content", ["VerticalLayoutGroup", "ContentSizeFitter"], "vertical"))
        view = _view(plan)
        self.assertIn("missionScroll.gameObject.SetActive(state != null);", view)
        self.assertIn("missionScroll.verticalNormalizedPosition = 1f;", view)
        self.assertNotIn("missionListRoot", view)

    def test_ladders_are_horizontal_scroll_chains(self):
        for plan, names in ((_mission_plan(), ("MissionBarScroll", "MissionBarViewport", "MissionBarContent")),
                            (_milestone_plan("per_step"), ("MilestoneScroll", "MilestoneViewport", "MilestoneContent"))):
            by = {n["name"]: n for n in plan["nodes"]}
            scroll, viewport, content = (by[n] for n in names)
            self.assertEqual((scroll["binding"], scroll["components"], scroll["scroll_axis"]), ("scroll", ["ScrollRect"], None))
            self.assertEqual((viewport["parent"], viewport["binding"]), (scroll["name"], "viewport"))
            self.assertEqual((content["parent"], content["binding"], content["components"], content["scroll_axis"]),
                             (viewport["name"], "scroll_content", ["HorizontalLayoutGroup", "ContentSizeFitter"], None))

    def test_old_milestone_plan_still_builds_the_same(self):
        # a plan written by the milestone base has no scroll_axis / color on any node: JsonUtility leaves them
        # empty, so every new builder branch (vertical scroll, node colour) is skipped for it
        plan = _milestone_plan("per_step")
        for node in plan["nodes"]:
            self.assertIsNone(node["scroll_axis"], node["name"])
            self.assertIsNone(node["color"], node["name"])
        apply_color = self.B.split("private static void ApplyColor(")[1].split("\n        }\n")[0]
        self.assertLess(apply_color.index("if (string.IsNullOrEmpty(node.color)"), apply_color.index('node.binding == "milestone_step"'))
        old = copy.deepcopy(plan)
        for node in old["nodes"]:
            for key in ("feature_action", "color", "scroll_axis"):
                del node[key]
        self.assertEqual(_read_exact(os.path.join(GOLDEN_VIEWS, "milestone_per_step_plan.json")),
                         json.dumps(old, indent=2, ensure_ascii=False) + "\n")


class TestBuilderArtIsClickThrough(unittest.TestCase):
    def test_image_nodes_do_not_block_raycasts(self):
        builder = mod.generate_code(_plan(), {})["files"]["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertIn('case "image":\n                case "text":\n                case "button_label":', builder)


    def test_builder_header_says_generate_always_rewrites_it(self):
        builder = mod.generate_code(_plan(), {})["files"]["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        header = builder.split("// </auto-generated>")[0]
        self.assertNotIn("--force-shared", header)
        self.assertIn("rewritten by every generate run", header)


class TestBuilderCanvas(unittest.TestCase):
    def setUp(self):
        self.builder = mod.generate_code(_plan(), {})["files"]["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]

    def test_root_gets_canvas_scaler_and_raycaster(self):
        self.assertIn("AddCanvas(root, plan.ui);", self.builder)
        for snippet in ("root.AddComponent<Canvas>()", "root.AddComponent<CanvasScaler>()",
                        "root.AddComponent<GraphicRaycaster>()", "CanvasScaler.ScaleMode.ScaleWithScreenSize",
                        "RenderMode.ScreenSpaceOverlay"):
            self.assertIn(snippet, self.builder)

    def test_plan_canvas_fields_match_the_planner(self):
        decl = self.builder.split("class PlanCanvas")[1].split("}")[0]
        fields = set(re.findall(r"public (?:string|bool|int|float|float\[\]) (\w+);", decl))
        plan = _plan()
        self.assertEqual(fields, set(plan["ui"]["canvas"].keys()))


GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "inapp_prefab")
SHARED = "Assets/Kinoa/InApps/Shared/"


def _read_exact(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


class TestNewSharedFiles(unittest.TestCase):
    def _generate(self, root, plan, *extra):
        import contextlib
        import io
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mod.main(["generate", "--plan", plan_path, "--project-root", root, *extra])
        return code, json.loads(buf.getvalue())

    def _seed(self, root, name, content):
        path = os.path.join(root, *(SHARED + name).split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return path

    def test_feature_hooks_declaration(self):
        src = mod.render_feature_hooks({})
        self.assertIn("namespace Kinoa.InApps", src)
        for using in ("System", "System.Threading.Tasks", "Kinoa.Data.Messaging.InApp",
                      "Kinoa.Data.Messaging.InApp.Templates.Custom", "UnityEngine"):
            self.assertIn("using %s;" % using, src)
        self.assertIn("public static class KinoaInAppFeatureHooks", src)
        self.assertIn("public static Func<InAppMessage, InAppCustomButton, Task<bool>> RunButtonAction = null;", src)
        self.assertIn("internal static void WarnMissing(string hook)", src)
        self.assertEqual(src.count("TODO(kinoa-prefab):"), 1)
        self.assertNotIn("KinoaText", src)

    def test_supplied_runner_is_assigned(self):
        src = mod.render_feature_hooks({"feature_action_runner": "Game.Shop.RunAsync"})
        self.assertIn("Task<bool>> RunButtonAction = Game.Shop.RunAsync;", src)
        self.assertNotIn("TODO(kinoa-prefab):", src)

    def test_step_view_api(self):
        src = mod.render_milestone_step_view("legacy")
        self.assertIn("using KinoaText = UnityEngine.UI.Text;", src)
        self.assertIn("namespace Kinoa.InApps", src)
        for using in ("Kinoa.Data.Enum", "UnityEngine", "UnityEngine.Events", "UnityEngine.UI"):
            self.assertIn("using %s;" % using, src)
        self.assertIn("public class KinoaInAppMilestoneStepView : MonoBehaviour", src)
        for field in ("KinoaText score", "Image rewardIcon", "KinoaText rewardAmount", "Image progress",
                      "GameObject lockedMark", "GameObject collectedMark", "Button collectButton", "KinoaText collectLabel"):
            self.assertIn("[SerializeField] private %s;" % field, src)
        for sig in ("public void SetScore(string text)", "public void SetReward(Sprite icon, string amount)",
                    "public void SetProgress(float amount)", "public void SetStatus(InAppMilestoneStatus status)",
                    "public void SetCollect(bool visible, bool interactable, string label, UnityAction onClick)"):
            self.assertIn(sig, src)
        self.assertIn("Mathf.Clamp01", src)
        self.assertIn("using KinoaText = TMPro.TMP_Text;", mod.render_milestone_step_view("tmp"))

    def test_old_shared_renderers_are_unchanged(self):
        for name, text in (("hooks", mod.render_hooks({})), ("item_view_legacy", mod.render_item_view("legacy")),
                           ("item_view_tmp", mod.render_item_view("tmp"))):
            self.assertEqual(text, _read_exact(os.path.join(GOLDEN, name + ".cs")), name)

    def test_generate_code_emits_both_new_files_for_every_plan(self):
        for plan in (_plan(), _milestone_plan(), _mission_plan()):
            files = mod.generate_code(plan, {})["files"]
            self.assertIn(SHARED + "KinoaInAppFeatureHooks.cs", files)
            self.assertIn(SHARED + "KinoaInAppMilestoneStepView.cs", files)

    def test_existing_project_is_extended_not_rewritten(self):
        import tempfile
        root = tempfile.mkdtemp()
        hooks = "// game edit\npublic static class KinoaInAppHooks { }\n"
        item = "// game edit\nusing KinoaText = UnityEngine.UI.Text;\npublic class KinoaInAppItemView { }\n"
        hooks_path = self._seed(root, "KinoaInAppHooks.cs", hooks)
        item_path = self._seed(root, "KinoaInAppItemView.cs", item)
        code, data = self._generate(root, _milestone_plan())
        self.assertEqual(code, 0, data)
        self.assertEqual(_read_exact(hooks_path), hooks)
        self.assertEqual(_read_exact(item_path), item)
        self.assertIn(SHARED + "KinoaInAppHooks.cs", data["skipped"])
        self.assertIn(SHARED + "KinoaInAppItemView.cs", data["skipped"])
        for name in ("KinoaInAppFeatureHooks.cs", "KinoaInAppMilestoneStepView.cs"):
            self.assertTrue(os.path.isfile(os.path.join(root, *(SHARED + name).split("/"))), name)
            self.assertIn(SHARED + name, data["written"])

    def test_new_files_skipped_when_present_and_forced_with_flag(self):
        import tempfile
        root = tempfile.mkdtemp()
        fh_path = self._seed(root, "KinoaInAppFeatureHooks.cs", "// game edit\n")
        sv_path = self._seed(root, "KinoaInAppMilestoneStepView.cs", "// game edit\nusing KinoaText = UnityEngine.UI.Text;\n")
        code, data = self._generate(root, _milestone_plan())
        self.assertEqual(code, 0, data)
        self.assertIn(SHARED + "KinoaInAppFeatureHooks.cs", data["skipped"])
        self.assertIn(SHARED + "KinoaInAppMilestoneStepView.cs", data["skipped"])
        self.assertEqual(_read_exact(fh_path), "// game edit\n")
        code, data = self._generate(root, _milestone_plan(), "--overwrite", "--force-shared",
                                    "--feature-action-runner", "Game.Shop.RunAsync")
        self.assertEqual(code, 0, data)
        self.assertIn("RunButtonAction = Game.Shop.RunAsync;", _read_exact(fh_path))
        self.assertIn("public class KinoaInAppMilestoneStepView", _read_exact(sv_path))

    def test_feature_action_runner_flag_is_validated(self):
        import tempfile
        root = tempfile.mkdtemp()
        code, data = self._generate(root, _milestone_plan(), "--feature-action-runner", "Foo.Bar;System.Exit()")
        self.assertEqual(code, 2)
        self.assertEqual(data["error"], "invalid_hook_method")
        self.assertEqual(data["flag"], "--feature-action-runner")
        code, data = self._generate(root, _milestone_plan(), "--feature-action-runner", "Game.Shop.RunAsync")
        self.assertEqual(code, 0, data)
        src = _read_exact(os.path.join(root, *(SHARED + "KinoaInAppFeatureHooks.cs").split("/")))
        self.assertIn("RunButtonAction = Game.Shop.RunAsync;", src)

    def test_feature_action_runner_not_applied_warning_when_hooks_exist(self):
        import tempfile
        root = tempfile.mkdtemp()
        self._seed(root, "KinoaInAppFeatureHooks.cs", "// game edit\n")
        code, data = self._generate(root, _milestone_plan(), "--feature-action-runner", "Game.Shop.RunAsync")
        self.assertEqual(code, 0, data)
        self.assertTrue(any("--feature-action-runner was not applied" in w for w in data["warnings"]), data["warnings"])

    def test_step_view_alias_mismatch_is_reported(self):
        import tempfile
        root = tempfile.mkdtemp()
        self._seed(root, "KinoaInAppMilestoneStepView.cs", "using KinoaText = TMPro.TMP_Text;\n")
        code, data = self._generate(root, _milestone_plan())  # legacy plan
        self.assertEqual(code, 2)
        self.assertEqual(data["error"], "shared_text_system_mismatch")
        self.assertTrue(data["path"].endswith("KinoaInAppMilestoneStepView.cs"))

    def test_outdated_milestone_plan_is_refused_and_nothing_is_written(self):
        import tempfile
        for drop in ("block", "scroll"):
            root = tempfile.mkdtemp()
            plan = _milestone_plan()
            if drop == "block":
                del plan["milestone"]
            else:
                plan["nodes"] = [n for n in plan["nodes"] if n["name"] != "MilestoneScroll"]
            code, data = self._generate(root, plan)
            self.assertEqual(code, 2, data)
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"], "milestone_plan_outdated")
            self.assertIn("re-run `plan`", data["detail"])
            self.assertIn("p.json", data["detail"])
            self.assertEqual(os.listdir(root), ["p.json"], "a refused plan must write nothing")

    def test_no_forbidden_strings(self):
        for src in (mod.render_feature_hooks({}), mod.render_feature_hooks({"feature_action_runner": "A.B.C"}),
                    mod.render_milestone_step_view("legacy"), mod.render_milestone_step_view("tmp")):
            for bad in FORBIDDEN:
                self.assertNotIn(bad, src)


# Every `case "..."` literal in BUILDER_CS as shipped in release 1.1.0 (AddComponent, ApplyBinding, Resolve).
# Frozen from the unmodified builder: the milestone-scroll change is additive, so none may disappear.
RELEASE_1_1_0_BUILDER_CASES = [
    "Image", "Button", "Text", "HorizontalLayoutGroup", "VerticalLayoutGroup",
    "dimmer", "strike", "fill", "item_template", "image", "text", "button_label",
    "GameObject", "RectTransform", "KinoaInAppItemView",
]


class TestBuilderScroll(unittest.TestCase):
    B = mod.BUILDER_CS
    STEP = B.split("private static void BuildMilestoneStep")[-1].split("private static GameObject Child")[0]

    def test_plan_node_gains_step_button(self):
        self.assertIn("public bool step_button;", self.B)

    def test_scroll_components(self):
        for snippet in ('case "ScrollRect":', "horizontal = true", "vertical = false",
                        "movementType = ScrollRect.MovementType.Clamped", "inertia = true",
                        'case "RectMask2D":', 'case "ContentSizeFitter":',
                        "horizontalFit = ContentSizeFitter.FitMode.PreferredSize",
                        "verticalFit = ContentSizeFitter.FitMode.Unconstrained"):
            self.assertIn(snippet, self.B)

    def test_viewport_binding(self):
        self.assertIn('case "viewport":', self.B)
        body = self.B.split('case "viewport":')[1].split("break;")[0]
        self.assertIn("new Color(1f, 1f, 1f, 0f)", body)
        self.assertIn("raycastTarget = true", body)

    def test_scroll_content_binding_overrides_the_layout_group(self):
        self.assertIn('case "scroll_content":', self.B)
        body = self.B.split('case "scroll_content":')[1].split("break;")[0]
        self.assertIn("pivot = new Vector2(0f, 0.5f)", body)
        self.assertIn("GetComponent<HorizontalLayoutGroup>()", body)
        self.assertNotIn("AddComponent<HorizontalLayoutGroup>", body)   # the generic component case already added it
        for snippet in ("spacing = 12f", "padding = new RectOffset(8, 8, 8, 8)", "childControlWidth = true",
                        "childControlHeight = true", "childForceExpandWidth = false", "childForceExpandHeight = true"):
            self.assertIn(snippet, body)

    def test_components_are_added_before_bindings(self):
        loop = self.B.split("foreach (var node in plan.nodes)")[1]
        self.assertLess(loop.index("AddComponent(go, component, plan.ui)"), loop.index("ApplyBinding(go, node, plan.ui)"))

    def test_milestone_step_binding_and_layout_element(self):
        self.assertIn('case "milestone_step":', self.B)
        self.assertIn("BuildMilestoneStep(go, ui, node);", self.B)
        self.assertIn("preferredWidth = node.size[0]", self.STEP)
        self.assertIn("flexibleHeight = 1f", self.STEP)
        self.assertIn("new Color(1f, 1f, 1f, 0.15f)", self.STEP)
        self.assertIn("raycastTarget = true", self.STEP)

    def test_step_children_and_anchors(self):
        for name, amin, amax in (
                ("Score", "0.05f, 0.80f", "0.95f, 0.98f"), ("RewardIcon", "0.20f, 0.42f", "0.80f, 0.78f"),
                ("RewardAmount", "0.05f, 0.30f", "0.95f, 0.42f"), ("Progress", "0.05f, 0.25f", "0.95f, 0.29f"),
                ("CollectButton", "0.10f, 0.03f", "0.90f, 0.22f"), ("LockedMark", "0f, 0f", "1f, 1f"),
                ("CollectedMark", "0.60f, 0.75f", "0.95f, 0.98f")):
            self.assertIn('Child(go, "%s", new Vector2(%s), new Vector2(%s))' % (name, amin, amax), self.STEP)
        self.assertIn('"CollectLabel"', self.STEP)
        self.assertIn("preserveAspect = true", self.STEP)
        self.assertIn("Image.Type.Filled", self.STEP)
        self.assertIn("fillAmount = 0f", self.STEP)
        self.assertIn("new Color(0f, 0f, 0f, 0.45f)", self.STEP)
        self.assertIn("SetActive(false)", self.STEP)

    def test_collect_button_only_when_step_button(self):
        before, guarded = self.STEP.split("if (node.step_button)", 1)
        self.assertIn('"CollectButton"', guarded)
        self.assertIn('SetRef(so, "collectButton"', guarded)
        self.assertIn('SetRef(so, "collectLabel"', guarded)
        self.assertNotIn('"CollectButton"', before)
        self.assertNotIn('SetRef(so, "collectButton"', before)

    def test_step_view_fields_are_all_assigned(self):
        src = mod.render_milestone_step_view("legacy")
        names = re.findall(r"\[SerializeField\] private \w+ (\w+);", src)
        self.assertEqual(len(names), 8)
        for name in names:
            self.assertIn('SetRef(so, "%s"' % name, self.B)

    def test_wire_scroll_rects(self):
        self.assertIn("WireScrollRects(plan.nodes, byName);", self.B)
        wire = self.B.split("private static void WireScrollRects")[1].split("private static ")[0]
        for snippet in ('"scroll"', '"viewport"', '"scroll_content"', ".viewport =", ".content ="):
            self.assertIn(snippet, wire)
        # wiring happens after every node is built, before the view fields and the save
        main = self.B.split("public static BuildReport BuildFromPlan")[1]
        self.assertLess(main.index("byName[node.name] = go;"), main.index("WireScrollRects(plan.nodes, byName);"))
        self.assertLess(main.index("WireScrollRects(plan.nodes, byName);"), main.index("FindType(plan.view.class_name"))

    def test_resolve_gains_scroll_and_step_cases(self):
        self.assertIn("private static UnityEngine.Object Resolve", self.B)
        resolve = self.B.split("private static UnityEngine.Object Resolve")[1].split("private static Type FindType")[0]
        self.assertIn('case "ScrollRect": return go.GetComponent<ScrollRect>();', resolve)
        self.assertIn('case "KinoaInAppMilestoneStepView": return go.GetComponent<KinoaInAppMilestoneStepView>();', resolve)

    def test_old_plan_cases_still_supported(self):
        for case in RELEASE_1_1_0_BUILDER_CASES:
            self.assertIn('case "%s":' % case, self.B)
