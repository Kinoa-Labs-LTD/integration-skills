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

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

with open(os.path.join(FIX, "template_one_cta.json"), encoding="utf-8") as _fh:
    TEMPLATE = json.load(_fh)
with open(os.path.join(FIX, "build_result_one_cta.json"), encoding="utf-8") as _fh:
    BUILD = json.load(_fh)
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
                     "Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"):
            self.assertIn(path, self.files)

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


def _milestone_plan():
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "chase"
    t["featureType"] = "milestone"
    t["features"] = {"milestone": {"key": "main_progressbar", "limit": 3, "mainActionTypes": ["close"]}}
    return _plan(template=t)


def _mission_plan():
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "board"
    t["featureType"] = "mission"
    t["features"] = {"mission": {"progressBar": {"display": "show_for_all_sets_combined"}, "completionCta": ["collect_resource"]}}
    return _plan(template=t)


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

    def test_milestone_feature(self):
        plan = _milestone_plan()
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("using Kinoa.Data.Messaging.InApp.Features;", view)
        self.assertIn("using Kinoa.Data.Messaging.InApp.Features.Milestones;", view)
        self.assertIn("var feature = Data.Feature as InAppMilestonesFeature;", view)
        self.assertIn("milestoneFill.fillAmount", view)
        self.assertIn("step.Status == InAppMilestoneStatus.Reached", view)
        self.assertIn("Kinoa.Messaging.CollectMilestonesAsync(Message, new List<uint> { index })", view)
        self.assertIn("marker.SetButton(false, null);", view)
        self.assertIn("response.Data.Collected.Contains(index)", view)
        self.assertIn("response?.Error?.Message", view)
        self.assertIn("Message.SetMilestonesStatusAsCollected(response.Data.Collected);", view)
        self.assertIn("if (response.Data.InApp != null)", view)
        self.assertIn('ApplyButtonSlot(milestoneMainButton, milestoneMainButtonLabel, "milestone_main", feature.ActiveProgressButton, canBeHidden: true);', view)
        self.assertIn("private void BindGrandPrize(", view)
        self.assertIn("%s apply the collected step's Button.Resources" % mod.TODO, view)

    def test_mission_feature(self):
        plan = _mission_plan()
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("using Kinoa.Data.Messaging.InApp.Features.Missions;", view)
        self.assertIn("var feature = Data.Feature as InAppMissionsFeature;", view)
        self.assertIn("row.SetValue($\"{mission.CurrentScore}/{mission.GoalScore}\");", view)
        self.assertIn("mission.Status == InAppMissionStatus.Reached", view)
        self.assertIn("Kinoa.Messaging.CollectMissionsProgressAsync(Message, setNumber, new List<int> { mission.RowNumber })", view)
        self.assertIn("row.SetButton(false, null);", view)
        self.assertIn("mission.ProcessedResources", view)
        self.assertIn("response?.Error?.Message", view)
        self.assertIn("missionBarFill.fillAmount", view)
        self.assertIn("Bind(response.Data);", view)
        t = copy.deepcopy(TEMPLATE)
        t["key"] = "board"
        t["featureType"] = "mission"
        t["features"] = {"mission": {"progressBar": {"display": "dont_show_at_all"}, "completionCta": ["collect_resource"]}}
        plan_no_bar = _plan(template=t)
        view_no_bar = mod.generate_code(plan_no_bar, {})["files"][plan_no_bar["paths"]["view_path"]]
        self.assertNotIn("missionBarFill", view_no_bar)   # the bar fields do not exist on that view — referencing them would not compile



class TestBuilderArtIsClickThrough(unittest.TestCase):
    def test_image_nodes_do_not_block_raycasts(self):
        builder = mod.generate_code(_plan(), {})["files"]["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertIn('case "image":\n                case "text":\n                case "button_label":', builder)


    def test_builder_header_says_generate_always_rewrites_it(self):
        builder = mod.generate_code(_plan(), {})["files"]["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        header = builder.split("// </auto-generated>")[0]
        self.assertNotIn("--force-shared", header)
        self.assertIn("rewritten by every generate run", header)
