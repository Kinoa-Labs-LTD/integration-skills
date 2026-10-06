"""Offline tests for the prefab planner (template + layout -> plan JSON)."""
import copy
import importlib.util
import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
HELPER = os.path.join(SKILL, "inapp_prefab_plan.py")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


TEMPLATE = _load("template_one_cta.json")
BUILD = _load("build_result_one_cta.json")
STYLE = {"text_system": "legacy", "font_guid": "e7a63bee4e93df34ca0dd3548b336621", "tmp_font_guid": None,
         "root_size": [900.0, 1400.0], "close_sprite_guid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
         "base_classes": ["OfferPopup"], "prefabs": [], "warnings": []}


def _node(plan, name):
    for n in plan["nodes"]:
        if n["name"] == name:
            return n
    raise AssertionError("node %s missing; have %s" % (name, [n["name"] for n in plan["nodes"]]))


class TestNaming(unittest.TestCase):
    def test_pascal_camel_field(self):
        self.assertEqual(mod.pascal("one_cta_offer"), "OneCtaOffer")
        self.assertEqual(mod.camel("background_image"), "backgroundImage")
        self.assertEqual(mod.field_name("images", "background_image"), "backgroundImage")
        self.assertEqual(mod.field_name("images", "hero"), "heroImage")
        self.assertEqual(mod.field_name("texts", "header"), "headerText")
        self.assertEqual(mod.field_name("buttons", "cta_button"), "ctaButton")
        self.assertEqual(mod.field_name("buttons", "cta"), "ctaButton")
        self.assertEqual(mod.node_name("texts", "fine_print"), "FinePrintText")


class TestNamingEdgeCases(unittest.TestCase):
    def test_key_without_alphanumerics_does_not_crash(self):
        self.assertEqual(mod.field_name("images", "---"), "elementImage")
        self.assertEqual(mod.field_name("texts", ""), "elementText")
        self.assertEqual(mod.field_name("customs", "---"), "element")

    def test_suffix_detection_single_vs_multi_token(self):
        # Single-token keys always get suffix appended
        self.assertEqual(mod.field_name("texts", "context"), "contextText")
        self.assertEqual(mod.field_name("texts", "text"), "textText")
        self.assertEqual(mod.field_name("images", "image"), "imageImage")
        self.assertEqual(mod.field_name("buttons", "button"), "buttonButton")
        # Multi-token keys with last token matching suffix: no suffix appended
        self.assertEqual(mod.field_name("images", "background_image"), "backgroundImage")
        self.assertEqual(mod.field_name("buttons", "cta_button"), "ctaButton")
        # Multi-token keys with last token NOT matching suffix: append suffix
        self.assertEqual(mod.field_name("images", "hero"), "heroImage")
        self.assertEqual(mod.field_name("texts", "header"), "headerText")

    def test_duplicate_image_keys_get_numbered(self):
        # Template with two images: "hero" and "hero_image" (both generate "HeroImage")
        template = {
            "key": "test_template",
            "images": [
                {"key": "hero", "index": 1},
                {"key": "hero_image", "index": 2}
            ],
            "buttons": [],
            "texts": [],
            "customs": []
        }
        result = mod.plan_prefab(template, mod.layout_from_build({"report": {}}), STYLE, {})
        self.assertTrue(result["ok"])
        plan = result["plan"]
        hero = mod.node_name("images", "hero")
        self.assertEqual(hero, "HeroImage")
        # hero_image should be renamed to HeroImage2
        node_names = {n["name"] for n in plan["nodes"]}
        self.assertIn("HeroImage", node_names)
        self.assertIn("HeroImage2", node_names)
        # Check warning was added
        self.assertTrue(any("renamed to HeroImage2" in w for w in plan["report"]["warnings"]))

    def test_duplicate_button_keys_with_labels(self):
        # Template with two buttons: "close" and "close_button" (both should generate "CloseButton")
        template = {
            "key": "test_template",
            "images": [],
            "buttons": [
                {"key": "close", "index": 1, "clickActionType": [], "customCtaNames": []},
                {"key": "close_button", "index": 2, "clickActionType": [], "customCtaNames": []}
            ],
            "texts": [],
            "customs": []
        }
        result = mod.plan_prefab(template, mod.layout_from_build({"report": {}}), STYLE, {})
        self.assertTrue(result["ok"])
        plan = result["plan"]
        node_names = {n["name"] for n in plan["nodes"]}
        # First button: CloseButton (and CloseButtonLabel)
        self.assertIn("CloseButton", node_names)
        self.assertIn("CloseButtonLabel", node_names)
        # Second button: CloseButton2 (and CloseButton2Label)
        self.assertIn("CloseButton2", node_names)
        self.assertIn("CloseButton2Label", node_names)
        # Verify label parents
        cta = next((n for n in plan["nodes"] if n["name"] == "CloseButton"), None)
        label = next((n for n in plan["nodes"] if n["name"] == "CloseButtonLabel"), None)
        self.assertEqual(label["parent"], "CloseButton")
        cta2 = next((n for n in plan["nodes"] if n["name"] == "CloseButton2"), None)
        label2 = next((n for n in plan["nodes"] if n["name"] == "CloseButton2Label"), None)
        self.assertEqual(label2["parent"], "CloseButton2")

    def test_reserved_text_name_timer(self):
        # Text slot "timer" should generate "TimerText" which clashes with a reserved name
        template = {
            "key": "test_template",
            "images": [],
            "buttons": [],
            "texts": [
                {"key": "timer", "index": 1}
            ],
            "customs": []
        }
        result = mod.plan_prefab(template, mod.layout_from_build({"report": {}}), STYLE, {})
        self.assertTrue(result["ok"])
        plan = result["plan"]
        node_names = {n["name"] for n in plan["nodes"]}
        # "timer" should be renamed to "TimerText2" to avoid clash with reserved "TimerText"
        self.assertIn("TimerText2", node_names)
        self.assertNotIn("TimerText", [n["name"] for n in plan["nodes"] if n.get("bucket") == "texts"])


class TestAnchors(unittest.TestCase):
    def test_header_relative_to_background_panel(self):
        amin, amax = mod.anchors_from_bbox({"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05},
                                           {"x": 0.2, "y": 0.06, "w": 0.57, "h": 0.7})
        self.assertAlmostEqual(amin[0], 0.1404, places=3)
        self.assertAlmostEqual(amin[1], 0.8571, places=3)
        self.assertAlmostEqual(amax[0], 0.8772, places=3)
        self.assertAlmostEqual(amax[1], 0.9286, places=3)

    def test_clamps_and_keeps_a_minimum_extent(self):
        amin, amax = mod.anchors_from_bbox({"x": -0.5, "y": 0.5, "w": 0.1, "h": 0.0},
                                           {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})
        self.assertEqual(amin[0], 0.0)
        self.assertGreaterEqual(amax[1] - amin[1], 0.01)


class TestLayoutFromBuild(unittest.TestCase):
    def test_elements_and_zones(self):
        layout = mod.layout_from_build(BUILD)
        keys = {(e["bucket"], e["key"]) for e in layout["elements"]}
        self.assertIn(("texts", "header"), keys)
        self.assertIn(("buttons", "cta_button"), keys)
        self.assertEqual({z["zone"] for z in layout["client_zones"]},
                         {"resource_area", "price_before_sale", "timer"})

    def test_image_size_forwarded_from_source_image(self):
        layout = mod.layout_from_build(BUILD)
        src = BUILD["report"]["source_image"]
        self.assertEqual(layout["image_size"], [src["width"], src["height"]])
        plan = mod.plan_prefab(TEMPLATE, layout, {"root_size": [900.0, 1400.0]},
                               {"image_size": layout["image_size"]})["plan"]
        self.assertEqual(plan["ui"]["frame_size"],
                         [900.0, round(900.0 * src["height"] / src["width"], 1)])

    def test_envelope_corrections_apply(self):
        envelope = {"corrections": {
            "excluded": [{"key": "fine_print", "bucket": "texts"}],
            "adjusted": [{"key": "header", "bucket": "texts", "bbox": {"x": 0.3, "y": 0.12, "w": 0.4, "h": 0.05},
                          "original_bbox": {"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05}}],
            "missed": [{"key": "hero_image", "bucket": "images", "bbox": {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.2}}]}}
        layout = mod.layout_from_build(BUILD, envelope)
        by_key = {e["key"]: e for e in layout["elements"]}
        self.assertNotIn("fine_print", by_key)
        self.assertEqual(by_key["header"]["bbox"]["x"], 0.3)
        self.assertEqual(by_key["hero_image"]["bucket"], "images")


class TestPlanCore(unittest.TestCase):
    def setUp(self):
        self.result = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})
        self.plan = self.result["plan"]

    def test_identity_and_paths(self):
        self.assertTrue(self.result["ok"])
        self.assertEqual(self.plan["view"]["class_name"], "KinoaInAppOneCtaOfferView")
        self.assertEqual(self.plan["view"]["ns"], "Kinoa.InApps")
        self.assertEqual(self.plan["paths"]["prefab_path"],
                         "Assets/Kinoa/InApps/OneCtaOffer/KinoaInApp_OneCtaOffer.prefab")
        self.assertEqual(self.plan["paths"]["plan_path"],
                         "Assets/Kinoa/InApps/OneCtaOffer/one_cta_offer.inapp-plan.json")
        self.assertEqual(self.plan["template"]["key"], "one_cta_offer")
        self.assertEqual(self.plan["template"]["id"], TEMPLATE["id"])

    def test_frame_follows_style_root_size_when_no_image_size(self):
        self.assertEqual(self.plan["ui"]["frame_size"], [900.0, 1400.0])
        self.assertEqual(self.plan["ui"]["text_system"], "legacy")
        self.assertEqual(self.plan["ui"]["font_guid"], STYLE["font_guid"])

    def test_frame_height_follows_image_aspect(self):
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {"image_size": [1080, 1920]})["plan"]
        self.assertEqual(plan["ui"]["frame_size"], [900.0, 1600.0])

    def test_fixed_chrome_nodes(self):
        dimmer, frame, panel = _node(self.plan, "Dimmer"), _node(self.plan, "Frame"), _node(self.plan, "Panel")
        self.assertEqual(dimmer["field"], "dimmer")
        self.assertEqual(frame["size"], [900.0, 1400.0])
        self.assertEqual(panel["parent"], "Frame")
        self.assertEqual(panel["field_type"], "RectTransform")
        # panel = union of every placed box: x .20-.84 (price cut badge), y .04 (close) - .90 (fine print)
        self.assertAlmostEqual(panel["anchor_min"][0], 0.2, places=3)
        self.assertAlmostEqual(panel["anchor_max"][0], 0.84, places=3)
        self.assertAlmostEqual(panel["anchor_min"][1], 0.10, places=3)
        self.assertAlmostEqual(panel["anchor_max"][1], 0.96, places=3)

    def test_background_sits_by_its_own_box_inside_the_panel(self):
        bg = _node(self.plan, "BackgroundImage")
        self.assertEqual(bg["parent"], "Panel")
        amin, amax = mod.anchors_from_bbox({"x": 0.2, "y": 0.06, "w": 0.57, "h": 0.7}, self.plan["report"]["panel_bbox"])
        self.assertEqual(bg["anchor_min"], amin)
        self.assertEqual(bg["anchor_max"], amax)
        self.assertEqual(bg["components"], ["Image"])
        self.assertEqual(bg["field"], "backgroundImage")

    def test_text_node_is_placed_from_layout(self):
        header = _node(self.plan, "HeaderText")
        self.assertTrue(header["placed"])
        self.assertEqual(header["components"], ["Text"])
        self.assertEqual(header["field_type"], "Text")
        amin, _ = mod.anchors_from_bbox({"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05}, self.plan["report"]["panel_bbox"])
        self.assertEqual(header["anchor_min"], amin)

    def test_button_node_and_label_child(self):
        cta = _node(self.plan, "CtaButton")
        self.assertEqual(cta["components"], ["Image", "Button"])
        self.assertEqual(cta["click_actions"], TEMPLATE["buttons"][1]["clickActionType"])
        self.assertFalse(cta["can_be_hidden"])
        label = _node(self.plan, "CtaButtonLabel")
        self.assertEqual(label["parent"], "CtaButton")
        self.assertEqual(label["binding"], "button_label")
        self.assertEqual(label["field"], "ctaButtonLabel")
        close = _node(self.plan, "CloseButton")
        self.assertEqual(close["sprite_guid"], STYLE["close_sprite_guid"])

    def test_no_unplaced_when_layout_is_complete(self):
        self.assertEqual(self.plan["report"]["unplaced"], [])
        self.assertNotIn("Unplaced", [n["name"] for n in self.plan["nodes"]])

    def test_fallback_without_layout_stacks_every_slot(self):
        result = mod.plan_prefab(TEMPLATE, None, STYLE, {})
        plan = result["plan"]
        self.assertIn("Unplaced", [n["name"] for n in plan["nodes"]])
        header = _node(plan, "HeaderText")
        self.assertFalse(header["placed"])
        self.assertEqual(header["parent"], "Unplaced")
        self.assertIn("header", plan["report"]["unplaced"])
        self.assertTrue(any("no layout" in w for w in plan["report"]["warnings"]))
        bg = _node(plan, "BackgroundImage")
        self.assertEqual(bg["parent"], "Panel")  # background always stretches the panel

    def test_template_can_be_raw_get_output(self):
        wrapped = {"http_status": 200, "ok": True, "id": TEMPLATE["id"], "response": copy.deepcopy(TEMPLATE)}
        self.assertEqual(mod.unwrap_template(wrapped)["key"], "one_cta_offer")


ITEM_BEARING = {"collect_resource", "billing", "soft_billing", "show_ad", "promise_rewards"}


def _milestone_template():
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "chase"
    t["featureType"] = "milestone"
    t["features"] = {"milestone": {"key": "main_progressbar", "name": "Main Progressbar", "limit": 3,
                                   "mainActionTypes": ["close"], "milestonesActionTypes": ["collect_resource"]}}
    t["images"].append({"key": "bar_image", "name": "Bar", "index": 10, "canBeHidden": False, "customFields": []})
    return t


def _mission_template(display="show_for_all_sets_combined"):
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "board"
    t["featureType"] = "mission"
    t["features"] = {"mission": {"key": "missions", "name": "Missions",
                                 "progressBar": {"display": display, "completionBarCta": ["collect_resource"]},
                                 "completionCta": ["collect_resource"], "activeProgressCta": ["close"],
                                 "maxPlacements": 10, "maxSetsCount": 7, "minPlacements": 1, "minSetsCount": 1}}
    return t


class TestClientZonesAndCustoms(unittest.TestCase):
    def setUp(self):
        self.plan = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]

    def test_timer_zone_is_placed_from_layout_and_inactive(self):
        zone = _node(self.plan, "TimerZone")
        self.assertEqual(zone["field"], "timerRoot")
        self.assertEqual(zone["field_type"], "GameObject")
        self.assertTrue(zone["inactive"])
        self.assertTrue(zone["placed"])
        text = _node(self.plan, "TimerText")
        self.assertEqual(text["parent"], "TimerZone")
        self.assertEqual(text["field"], "timerText")

    def test_price_zone_present_because_cta_lists_billing(self):
        zone = _node(self.plan, "PriceBeforeSaleZone")
        self.assertEqual(zone["field"], "priceBeforeSaleRoot")
        strike = _node(self.plan, "PriceBeforeSaleStrike")
        self.assertEqual(strike["components"], ["Image"])
        self.assertEqual(strike["parent"], "PriceBeforeSaleZone")

    def test_resource_area_with_item_template(self):
        area = _node(self.plan, "ResourceArea")
        self.assertEqual(area["components"], ["HorizontalLayoutGroup"])
        item = _node(self.plan, "ResourceItem")
        self.assertEqual(item["binding"], "item_template")
        self.assertEqual(item["field"], "resourceItemTemplate")
        self.assertEqual(item["field_type"], "KinoaInAppItemView")
        self.assertTrue(item["inactive"])

    def test_no_grand_prize_on_standard(self):
        self.assertNotIn("GrandPrizeArea", [n["name"] for n in self.plan["nodes"]])

    def test_boolean_custom_targets_the_resource_area(self):
        customs = {c["key"]: c for c in self.plan["customs"]}
        self.assertEqual(customs["show_resource_area"]["kind"], "boolean")
        self.assertEqual(customs["show_resource_area"]["target_node"], "ResourceArea")
        self.assertEqual(customs["show_resource_area"]["target_field"], "resourceAreaRoot")

    def test_zone_without_layout_gets_default_anchors_and_is_reported(self):
        plan = mod.plan_prefab(TEMPLATE, None, STYLE, {})["plan"]
        timer = _node(plan, "TimerZone")
        self.assertIn("TimerZone", plan["report"]["estimated_positions"])
        self.assertFalse(timer["placed"])
        # it starts at the timer's default anchors; the de-overlap pass may then move it off the
        # Unplaced container, and says so
        moves = [a for a in plan["report"]["layout_adjustments"] if a["node"] == "TimerZone"]
        self.assertEqual(len(moves), 1)  # its default sits on the Unplaced container
        self.assertEqual(moves[0]["from"][0], [0.3, 0.02])

    def test_no_price_zone_without_billing(self):
        t = copy.deepcopy(TEMPLATE)
        t["buttons"][1]["clickActionType"] = ["close", "deep_link"]
        plan = mod.plan_prefab(t, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        names = [n["name"] for n in plan["nodes"]]
        self.assertNotIn("PriceBeforeSaleZone", names)
        self.assertNotIn("ResourceArea", names)


class TestFeatures(unittest.TestCase):
    def test_milestone_nodes(self):
        layout = mod.layout_from_build(BUILD)
        layout["elements"].append({"bucket": "images", "key": "bar_image", "role": "bar_image",
                                   "bbox": {"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.04}, "observed_text": None})
        plan = mod.plan_prefab(_milestone_template(), layout, STYLE, {})["plan"]
        bar = _node(plan, "MilestoneBar")
        self.assertEqual(bar["field"], "milestoneBarRoot")
        amin, _ = mod.anchors_from_bbox({"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.04}, plan["report"]["panel_bbox"])
        self.assertEqual(bar["anchor_min"], amin)  # follows bar_image
        self.assertEqual(_node(plan, "MilestoneFill")["field_type"], "Image")
        self.assertEqual(_node(plan, "MilestoneMarkers")["components"], ["HorizontalLayoutGroup"])
        marker = _node(plan, "MilestoneMarker")
        self.assertEqual(marker["parent"], "MilestoneMarkers")
        self.assertEqual(marker["field"], "milestoneMarkerTemplate")
        self.assertEqual(_node(plan, "MilestoneMainButtonLabel")["parent"], "MilestoneMainButton")
        self.assertEqual(_node(plan, "GrandPrizeArea")["field"], "grandPrizeRoot")
        self.assertEqual(plan["template"]["feature_type"], "milestone")

    def test_mission_nodes_with_and_without_bar(self):
        plan = mod.plan_prefab(_mission_template(), None, STYLE, {})["plan"]
        self.assertEqual(_node(plan, "MissionList")["field_type"], "RectTransform")
        self.assertEqual(_node(plan, "MissionRow")["field"], "missionRowTemplate")
        self.assertEqual(_node(plan, "MissionBarFill")["field"], "missionBarFill")
        self.assertIn("MissionList", plan["report"]["estimated_positions"])
        plan2 = mod.plan_prefab(_mission_template("dont_show_at_all"), None, STYLE, {})["plan"]
        self.assertNotIn("MissionBar", [n["name"] for n in plan2["nodes"]])


class TestLayoutFile(unittest.TestCase):
    def test_layout_file_elements_and_unknown_keys(self):
        layout = mod.layout_from_layout_file({
            "schema_version": "1.0", "source_image": {"width": 1080, "height": 1920},
            "elements": [{"key": "header", "bbox": {"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.05}},
                         {"key": "bogus", "bucket": "texts", "bbox": {"x": 0.3, "y": 0.5, "w": 0.4, "h": 0.05}}],
            "client_zones": [{"zone": "timer", "bbox": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.03}}]})
        self.assertEqual(layout["elements"][0]["bucket"], None)
        self.assertEqual(layout["image_size"], [1080, 1920])
        plan = mod.plan_prefab(TEMPLATE, layout, STYLE, {})
        self.assertEqual(plan["report"]["unmapped_layout"], [{"bucket": "texts", "key": "bogus"}])
        self.assertTrue(_node(plan["plan"], "HeaderText")["placed"])

    def test_unknown_client_zone_is_reported_not_dropped(self):
        layout = mod.layout_from_layout_file({
            "elements": [],
            "client_zones": [{"zone": "timr", "bbox": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.03}},
                            {"zone": "timer", "bbox": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.03}}]})
        result = mod.plan_prefab(TEMPLATE, layout, STYLE, {})
        self.assertIn({"zone": "timr"}, result["report"]["unmapped_layout"])
        self.assertNotIn({"zone": "timer"}, result["report"]["unmapped_layout"])

    def test_layout_schema_lists_zones(self):
        self.assertEqual(mod.LAYOUT_SCHEMA["shape"]["client_zones"][0]["zone"],
                         "timer | price_before_sale | resource_area | grand_prize_area")


class TestPlanCli(unittest.TestCase):
    def test_plan_cli_writes_file(self):
        import subprocess, sys, tempfile
        out = os.path.join(tempfile.mkdtemp(), "p.json")
        style = os.path.join(tempfile.mkdtemp(), "s.json")
        with open(style, "w", encoding="utf-8") as fh:
            json.dump(STYLE, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--build", os.path.join(FIX, "build_result_one_cta.json"), "--style", style,
                              "--image-size", "1080x1920", "--out", out], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["plan"]["ui"]["frame_size"], [900.0, 1600.0])
        self.assertTrue(os.path.isfile(out))

    def test_plan_cli_consumes_probe_style_output(self):
        import subprocess, sys, tempfile
        tmp = tempfile.mkdtemp()
        style = os.path.join(tmp, "style.json")
        res = subprocess.run([sys.executable, HELPER, "probe-style", "--prefab", os.path.join(FIX, "OfferPopup.prefab"),
                              "--assets-root", FIX, "--out", style], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = os.path.join(tmp, "p.json")
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--build", os.path.join(FIX, "build_result_one_cta.json"), "--style", style,
                              "--out", out], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        ui = data["plan"]["ui"]
        self.assertEqual(ui["font_guid"], "e7a63bee4e93df34ca0dd3548b336621")
        self.assertEqual(ui["text_system"], "legacy")
        self.assertEqual(ui["frame_size"][0], 900.0)
        self.assertTrue(any("OfferPopup" in n for n in data["report"]["needs_developer"]))
        # F2: no --image-size -> aspect comes from build_result.report.source_image
        src = BUILD["report"]["source_image"]
        self.assertEqual(ui["frame_size"][1], round(900.0 * src["height"] / src["width"], 1))

    def test_plan_cli_accepts_bare_style_dict(self):
        import subprocess, sys, tempfile
        tmp = tempfile.mkdtemp()
        style = os.path.join(tmp, "s.json")
        with open(style, "w", encoding="utf-8") as fh:
            json.dump({"text_system": "tmp"}, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--out", os.path.join(tmp, "p.json"), "--style", style], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        ui = json.loads(res.stdout)["plan"]["ui"]
        self.assertEqual(ui["text_system"], "tmp")
        self.assertEqual(ui["frame_size"], [1080.0, 1920.0])

    def test_plan_cli_rejects_invalid_template(self):
        import subprocess, sys, tempfile
        bad = os.path.join(tempfile.mkdtemp(), "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump({"name": "x"}, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", bad], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)["error"], "template_invalid")

    def test_plan_cli_rejects_malformed_layout_with_bad_bbox(self):
        import subprocess, sys, tempfile
        bad_layout = os.path.join(tempfile.mkdtemp(), "bad_layout.json")
        with open(bad_layout, "w", encoding="utf-8") as fh:
            json.dump({"elements": [{"key": "header", "bbox": {"x": "a"}}]}, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--layout", bad_layout], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertEqual(json.loads(res.stdout)["error"], "unreadable_input")

    def test_plan_cli_rejects_layout_with_non_list_elements(self):
        import subprocess, sys, tempfile
        bad_layout = os.path.join(tempfile.mkdtemp(), "bad_layout2.json")
        with open(bad_layout, "w", encoding="utf-8") as fh:
            json.dump({"elements": "not a list"}, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--layout", bad_layout], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)["error"], "unreadable_input")

    def test_plan_cli_creates_parent_directories_on_write(self):
        import subprocess, sys, tempfile
        tmpdir = tempfile.mkdtemp()
        out = os.path.join(tmpdir, "sub", "dir", "p.json")
        style = os.path.join(tmpdir, "s.json")
        with open(style, "w", encoding="utf-8") as fh:
            json.dump(STYLE, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--build", os.path.join(FIX, "build_result_one_cta.json"), "--style", style,
                              "--image-size", "1080x1920", "--out", out], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.isfile(out))
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])


class TestPlacedFlagConsistency(unittest.TestCase):
    def test_mission_nodes_without_layout_have_placed_false(self):
        plan = mod.plan_prefab(_mission_template(), None, STYLE, {})["plan"]
        mission_list = _node(plan, "MissionList")
        self.assertFalse(mission_list["placed"])
        mission_bar = _node(plan, "MissionBar")
        self.assertFalse(mission_bar["placed"])

    def test_milestone_nodes_without_layout_have_placed_false(self):
        plan = mod.plan_prefab(_milestone_template(), None, STYLE, {})["plan"]
        bar = _node(plan, "MilestoneBar")
        self.assertFalse(bar["placed"])
        button = _node(plan, "MilestoneMainButton")
        self.assertFalse(button["placed"])

    def test_timer_zone_with_layout_has_placed_true(self):
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        timer = _node(plan, "TimerZone")
        self.assertTrue(timer["placed"])


ARTIFACT = _load("one_cta_offer.layout.json")


def _run_cli(*argv):
    import subprocess
    import sys
    return subprocess.run([sys.executable, HELPER, *argv], capture_output=True, text=True)


class TestLayoutArtifact(unittest.TestCase):
    """The from-image skill's <template_key>.layout.json (references/layout-artifact.md) as a layout source."""

    def test_reader_maps_elements_zones_and_size(self):
        layout = mod.layout_from_artifact(ARTIFACT)
        by_key = {e["key"]: e for e in layout["elements"]}
        self.assertEqual(by_key["header"]["bucket"], "texts")
        self.assertEqual(by_key["header"]["bbox"], ARTIFACT["elements"][2]["bbox"])
        self.assertNotIn("show_resource_area", by_key)  # customs carry no geometry for the planner
        self.assertEqual({z["zone"] for z in layout["client_zones"]}, {"resource_area", "price_before_sale", "timer"})
        self.assertEqual(layout["image_size"], [706, 898])
        self.assertEqual(layout["template_key"], "one_cta_offer")
        self.assertEqual(layout["source"], "layout_artifact")

    def test_plan_from_artifact_matches_plan_from_build(self):
        from_build = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        from_artifact = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), STYLE, {})["plan"]
        build_nodes = {n["name"]: (n["anchor_min"], n["anchor_max"], n["placed"]) for n in from_build["nodes"]}
        artifact_nodes = {n["name"]: (n["anchor_min"], n["anchor_max"], n["placed"]) for n in from_artifact["nodes"]}
        self.assertEqual(artifact_nodes, build_nodes)
        self.assertEqual(from_artifact["report"]["layout_source"]["kind"], "layout_artifact")

    def test_unplaced_artifact_element_goes_to_unplaced(self):
        art = copy.deepcopy(ARTIFACT)
        for e in art["elements"]:
            if e["key"] == "fine_print":
                e["bbox"] = None
                e["unplaced"] = True
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertIn("fine_print", plan["report"]["unplaced"])
        self.assertEqual(_node(plan, "FinePrintText")["parent"], "Unplaced")

    def test_template_key_mismatch_is_refused(self):
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "some_other_template"
        result = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "layout_template_mismatch")

    def test_index_mismatch_is_a_warning(self):
        art = copy.deepcopy(ARTIFACT)
        for e in art["elements"]:
            if e["key"] == "header":
                e["index"] = 99
        report = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["report"]
        self.assertTrue(any("header" in w and "index" in w for w in report["warnings"]))

    def test_rejects_other_coordinate_conventions(self):
        art = copy.deepcopy(ARTIFACT)
        art["coordinates"] = {"space": "pixels", "origin": "top-left"}
        with self.assertRaises(ValueError):
            mod.layout_from_artifact(art)
        art["coordinates"] = {"space": "normalized", "origin": "bottom-left"}
        with self.assertRaises(ValueError):
            mod.layout_from_artifact(art)

    def test_rejects_unknown_major_schema_version_and_bad_bbox(self):
        art = copy.deepcopy(ARTIFACT)
        art["schema_version"] = "2.0"
        with self.assertRaises(ValueError):
            mod.layout_from_artifact(art)
        art = copy.deepcopy(ARTIFACT)
        art["elements"][0]["bbox"] = {"x": "a", "y": 0, "w": 1, "h": 1}
        with self.assertRaises(ValueError):
            mod.layout_from_artifact(art)

    def test_mission_area_bbox_places_the_task_list(self):
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "board"
        art["feature"] = {"type": "mission", "area_bbox": {"x": 0.25, "y": 0.3, "w": 0.5, "h": 0.4}}
        plan = mod.plan_prefab(_mission_template(), mod.layout_from_artifact(art), STYLE, {})["plan"]
        mission_list = _node(plan, "MissionList")
        self.assertTrue(mission_list["placed"])
        self.assertNotIn("MissionList", plan["report"]["estimated_positions"])
        amin, amax = mod.anchors_from_bbox(art["feature"]["area_bbox"], plan["report"]["panel_bbox"])
        self.assertEqual(mission_list["anchor_min"], amin)
        self.assertEqual(mission_list["anchor_max"], amax)
        # the task list holds other UI; the placed zones on it are kept as overlays, never trimmed
        trimmed = [a["node"] for a in plan["report"]["layout_adjustments"] if a["reason"] == "split_overlap"]
        self.assertEqual(trimmed, [])
        self.assertIn(["ResourceArea", "MissionList"], plan["report"]["overlays"])
        for name in ("ResourceArea", "PriceBeforeSaleZone"):
            self.assertNotIn(name, [a["node"] for a in plan["report"]["layout_adjustments"]])

    def test_milestone_area_bbox_places_the_bar_when_no_bar_image(self):
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "chase"
        art["feature"] = {"type": "milestone", "area_bbox": {"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.05}}
        plan = mod.plan_prefab(_milestone_template(), mod.layout_from_artifact(art), STYLE, {})["plan"]
        bar = _node(plan, "MilestoneBar")
        self.assertTrue(bar["placed"])
        self.assertNotIn("MilestoneBar", plan["report"]["estimated_positions"])

    def test_feature_type_mismatch_is_a_warning(self):
        art = copy.deepcopy(ARTIFACT)
        art["feature"] = {"type": "mission"}
        report = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["report"]
        self.assertTrue(any("feature" in w and "mission" in w for w in report["warnings"]))

    def test_cli_layout_artifact_round_trip(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "p.json")
        res = _run_cli("plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                       "--layout-artifact", os.path.join(FIX, "one_cta_offer.layout.json"), "--out", out)
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        data = json.loads(res.stdout)
        self.assertEqual(data["report"]["layout_source"]["kind"], "layout_artifact")
        self.assertEqual(data["plan"]["ui"]["frame_size"], [1080.0, round(1080.0 * 898 / 706, 1)])
        self.assertTrue(_node(data["plan"], "HeaderText")["placed"])

    def test_cli_layout_artifact_mismatch_exits_2(self):
        import tempfile
        d = tempfile.mkdtemp()
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "nope"
        path = os.path.join(d, "nope.layout.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(art, fh)
        res = _run_cli("plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                       "--layout-artifact", path, "--out", os.path.join(d, "p.json"))
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)["error"], "layout_template_mismatch")

    def test_cli_layout_artifact_excludes_build(self):
        res = _run_cli("plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                       "--layout-artifact", os.path.join(FIX, "one_cta_offer.layout.json"),
                       "--build", os.path.join(FIX, "build_result_one_cta.json"))
        self.assertEqual(res.returncode, 2)  # argparse mutual exclusion


FROM_IMAGE = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-from-image")
FROM_IMAGE_BUILDER = os.path.join(FROM_IMAGE, "inapp_template_build.py")
FROM_IMAGE_FIX = os.path.join(FROM_IMAGE, "evals", "fixtures", "one-cta")


class TestLayoutArtifactStrictness(unittest.TestCase):
    """Fail closed where the contract requires it; warn where the join is broken."""

    def test_missing_or_empty_template_key_is_rejected(self):
        for value in (None, ""):
            art = copy.deepcopy(ARTIFACT)
            art["template_key"] = value
            with self.assertRaises(ValueError):
                mod.layout_from_artifact(art)
        art = copy.deepcopy(ARTIFACT)
        del art["template_key"]
        with self.assertRaises(ValueError):
            mod.layout_from_artifact(art)

    def test_out_of_range_or_zero_element_box_is_rejected(self):
        for bad in ({"x": 200, "y": 100, "w": 300, "h": 40}, {"x": 0.1, "y": 0.1, "w": 0, "h": 0.2},
                    {"x": -0.1, "y": 0.1, "w": 0.2, "h": 0.2}):
            art = copy.deepcopy(ARTIFACT)
            art["elements"][2]["bbox"] = bad
            with self.assertRaises(ValueError):
                mod.layout_from_artifact(art)
        art = copy.deepcopy(ARTIFACT)
        art["feature"] = {"type": "standard", "area_bbox": {"x": 2, "y": 0, "w": 1, "h": 1}}
        with self.assertRaises(ValueError):
            mod.layout_from_artifact(art)

    def test_out_of_range_zone_box_is_dropped_with_a_warning(self):
        art = copy.deepcopy(ARTIFACT)
        for z in art["client_rendered"]:
            if z["role"] == "timer":
                z["bbox"] = {"x": 400, "y": 800, "w": 100, "h": 30}
        layout = mod.layout_from_artifact(art)
        timer = next(z for z in layout["client_zones"] if z["zone"] == "timer")
        self.assertIsNone(timer["bbox"])
        report = mod.plan_prefab(TEMPLATE, layout, STYLE, {})["report"]
        self.assertTrue(any("timer" in w for w in report["warnings"]))
        self.assertIn("TimerZone", report["estimated_positions"])

    def test_template_slot_missing_from_artifact_is_a_warning(self):
        art = copy.deepcopy(ARTIFACT)
        art["elements"] = [e for e in art["elements"] if e["key"] != "fine_print"]
        report = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["report"]
        self.assertTrue(any("texts.fine_print" in w and "no entry" in w for w in report["warnings"]))

    def test_artifact_entry_not_on_template_is_unmapped_even_when_unplaced(self):
        art = copy.deepcopy(ARTIFACT)
        art["elements"].append({"key": "ghost", "bucket": "texts", "index": 20, "role": "", "bbox": None, "unplaced": True})
        report = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["report"]
        self.assertIn({"bucket": "texts", "key": "ghost"}, report["unmapped_layout"])

    def test_wrong_bucket_is_not_placed_through_a_key_only_fallback(self):
        art = copy.deepcopy(ARTIFACT)
        for e in art["elements"]:
            if e["key"] == "header":
                e["bucket"] = "images"
        result = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})
        self.assertFalse(_node(result["plan"], "HeaderText")["placed"])
        self.assertIn({"bucket": "images", "key": "header"}, result["report"]["unmapped_layout"])

    def test_duplicate_entries_are_a_warning(self):
        art = copy.deepcopy(ARTIFACT)
        art["elements"].append(copy.deepcopy(art["elements"][2]))
        report = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["report"]
        self.assertTrue(any("duplicate" in w and "header" in w for w in report["warnings"]))

    def test_valid_artifact_raises_no_join_warnings(self):
        report = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), STYLE, {})["report"]
        self.assertEqual([w for w in report["warnings"] if "layout artifact" in w], [])
        self.assertEqual(report["unmapped_layout"], [])

    def test_feature_area_is_ignored_when_feature_types_disagree(self):
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "chase"
        art["feature"] = {"type": "mission", "area_bbox": {"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.05}}
        plan = mod.plan_prefab(_milestone_template(), mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertFalse(_node(plan, "MilestoneBar")["placed"])
        self.assertIn("MilestoneBar", plan["report"]["estimated_positions"])

    def test_layout_source_counts_developer_boxes(self):
        art = copy.deepcopy(ARTIFACT)
        art["elements"][2]["hand_placed"] = True
        art["elements"][3]["adjusted"] = True
        source = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["report"]["layout_source"]
        self.assertEqual(source["hand_placed"], 1)
        self.assertEqual(source["adjusted"], 1)


class TestLayoutArtifactFromRealProducer(unittest.TestCase):
    """The contract boundary: real `inapp_template_build.py` output feeds `plan --layout-artifact`."""

    def _producer(self, *argv):
        import subprocess
        import sys
        res = subprocess.run([sys.executable, FROM_IMAGE_BUILDER, *argv], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        return json.loads(res.stdout)

    def _plan(self, artifact_path, template_path):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "p.json")
        res = _run_cli("plan", "--template", template_path, "--layout-artifact", artifact_path, "--out", out)
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        return json.loads(res.stdout)

    def test_path_a_layout_from_build_plans_cleanly(self):
        import tempfile
        d = tempfile.mkdtemp()
        build = os.path.join(d, "build.json")
        self._producer("build", "--analysis", os.path.join(FROM_IMAGE_FIX, "analysis_one_cta.json"),
                       "--name", "One CTA Offer", "--key", "one_cta_offer", "--out", build)
        art = os.path.join(d, "one_cta_offer.layout.json")
        self._producer("layout", "--build", build,
                       "--analysis", os.path.join(FROM_IMAGE_FIX, "analysis_one_cta.json"), "--out", art)
        data = self._plan(art, os.path.join(FIX, "template_one_cta.json"))
        self.assertEqual(data["report"]["layout_source"]["kind"], "layout_artifact")
        self.assertEqual(data["report"]["unmapped_layout"], [])
        self.assertEqual(data["report"]["unplaced"], [])
        self.assertTrue(_node(data["plan"], "CtaButton")["placed"])

    def test_path_b_remap_of_the_dashboard_record_plans_cleanly(self):
        import tempfile
        d = tempfile.mkdtemp()
        page_build = os.path.join(d, "build_for_page.json")
        self._producer("remap", "--record", os.path.join(FIX, "template_one_cta.json"),
                       "--analysis", os.path.join(FROM_IMAGE_FIX, "analysis_one_cta.json"), "--out", page_build)
        art = os.path.join(d, "one_cta_offer.layout.json")
        self._producer("layout", "--build", page_build, "--out", art)
        data = self._plan(art, os.path.join(FIX, "template_one_cta.json"))
        self.assertEqual(data["report"]["unmapped_layout"], [])
        self.assertEqual([w for w in data["report"]["warnings"] if "layout artifact" in w], [])
        self.assertTrue(_node(data["plan"], "HeaderText")["placed"])


class TestLayoutArtifactMisuse(unittest.TestCase):
    def test_build_result_passed_as_artifact_names_the_right_flag(self):
        with self.assertRaises(ValueError) as ctx:
            mod.layout_from_artifact(BUILD)
        self.assertIn("--build", str(ctx.exception))



# --------------------------------------------------------------------------- layout: panel extent + de-overlap

def _flow_boxes(plan):
    """Top-level texts, buttons and zones (badges excluded) as (name, x0, y0, x1, y1) in panel anchors."""
    return [(n["name"],) + tuple(mod._box(n)) for n in plan["nodes"] if mod._is_flow(n)]


def _overlaps(plan, tol=0.002):
    """Colliding flow pairs, excluding the ones the planner deliberately kept as overlays."""
    boxes, hits = _flow_boxes(plan), []
    kept = {tuple(pair) for pair in plan["report"].get("overlays", [])}
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            dx = min(a[3], b[3]) - max(a[1], b[1])
            dy = min(a[4], b[4]) - max(a[2], b[2])
            if dx > tol and dy > tol and (a[0], b[0]) not in kept and (b[0], a[0]) not in kept:
                hits.append((a[0], b[0]))
    return hits


class TestPanelCoversEveryElement(unittest.TestCase):
    """Elements outside the background art (CTA, timer, fine print below it) are never clamped."""

    def setUp(self):
        self.plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), STYLE, {})["plan"]

    def test_panel_is_the_union_of_all_placed_boxes(self):
        panel = self.plan["report"]["panel_bbox"]
        self.assertAlmostEqual(panel["x"], 0.20, places=3)
        self.assertAlmostEqual(panel["y"], 0.04, places=3)
        self.assertAlmostEqual(panel["x"] + panel["w"], 0.84, places=3)
        self.assertAlmostEqual(panel["y"] + panel["h"], 0.90, places=3)

    def test_bottom_elements_keep_their_mockup_order_and_size(self):
        cta, timer, fine = (_node(self.plan, n) for n in ("CtaButton", "TimerZone", "FinePrintText"))
        # anchors are y-up: CTA above timer above fine print, each with real height
        self.assertGreater(cta["anchor_min"][1], timer["anchor_max"][1])
        self.assertGreater(timer["anchor_min"][1], fine["anchor_max"][1])
        for node in (cta, timer, fine):
            self.assertGreater(node["anchor_max"][1] - node["anchor_min"][1], 0.02, node["name"])

    def test_no_text_button_or_zone_overlaps(self):
        self.assertEqual(_overlaps(self.plan), [])
        self.assertEqual(self.plan["report"]["layout_adjustments"], [])
        self.assertEqual(self.plan["report"]["overlays"], [])  # a returning clamp would hide here as a 1.0 "overlay"

    def test_background_without_a_box_stretches_the_panel(self):
        plan = mod.plan_prefab(TEMPLATE, None, STYLE, {})["plan"]
        bg = _node(plan, "BackgroundImage")
        self.assertEqual(bg["anchor_min"], [0.0, 0.0])
        self.assertEqual(bg["anchor_max"], [1.0, 1.0])


class TestDeOverlap(unittest.TestCase):
    """Texts, buttons and zones never overlap in the plan; badges may overlay on purpose."""

    def _plan(self, art):
        return mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["plan"]

    def test_estimated_zone_moves_off_a_placed_text(self):
        art = copy.deepcopy(ARTIFACT)
        art["client_rendered"] = [z for z in art["client_rendered"] if z["role"] != "timer"]
        plan = self._plan(art)
        self.assertEqual(_overlaps(plan), [])
        moved = [a for a in plan["report"]["layout_adjustments"] if a["node"] == "TimerZone"]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["reason"], "moved_to_free_space")
        fine = _node(plan, "FinePrintText")
        amin, amax = mod.anchors_from_bbox(next(e["bbox"] for e in art["elements"] if e["key"] == "fine_print"),
                                           plan["report"]["panel_bbox"])
        self.assertEqual((fine["anchor_min"], fine["anchor_max"]), (amin, amax))  # the placed text did not move
        self.assertTrue(any("TimerZone" in w for w in plan["report"]["warnings"]))

    def test_slightly_overlapping_placed_text_and_button_are_split(self):
        art = copy.deepcopy(ARTIFACT)
        for e in art["elements"]:
            if e["key"] == "fine_print":
                e["bbox"] = {"x": 0.25, "y": 0.775, "w": 0.5, "h": 0.035}  # grazes the CTA's bottom (y .72-.79), clear of the timer
        plan = self._plan(art)
        self.assertEqual(_overlaps(plan), [])
        reasons = {a["node"]: a["reason"] for a in plan["report"]["layout_adjustments"]}
        self.assertEqual(reasons.get("CtaButton"), "split_overlap")
        self.assertEqual(reasons.get("FinePrintText"), "split_overlap")
        for name, original_h in (("CtaButton", 0.07), ("FinePrintText", 0.035)):
            node = _node(plan, name)
            kept = (node["anchor_max"][1] - node["anchor_min"][1]) * plan["report"]["panel_bbox"]["h"]
            self.assertGreaterEqual(kept, 0.4 * original_h - 1e-6, name)

    def test_badges_may_overlay_the_cta(self):
        art = copy.deepcopy(ARTIFACT)
        for e in art["elements"]:
            if e["key"] == "price_cut_badge":
                e["bbox"] = {"x": 0.55, "y": 0.70, "w": 0.19, "h": 0.06}  # sits on the CTA's corner
        plan = self._plan(art)
        self.assertEqual(plan["report"]["layout_adjustments"], [])

    def test_no_layout_still_yields_no_overlaps(self):
        plan = mod.plan_prefab(TEMPLATE, None, STYLE, {})["plan"]
        self.assertEqual(_overlaps(plan), [])

    def test_mission_and_milestone_estimates_do_not_overlap_silently(self):
        for template in (_mission_template(), _milestone_template()):
            plan = mod.plan_prefab(template, mod.layout_from_build(BUILD), STYLE, {})["plan"]
            # the one-CTA mockup has no milestone geometry at all; when an estimated node finds no
            # room it may stay put, but only with a warning that names the overlap
            for a, b in _overlaps(plan):
                self.assertTrue(any(w.startswith((a + " has no free space", b + " has no free space")) and a in w and b in w
                                    for w in plan["report"]["warnings"]), (template["featureType"], a, b))
        plan = mod.plan_prefab(_mission_template(), mod.layout_from_build(BUILD), STYLE, {})["plan"]
        self.assertEqual(_overlaps(plan), [])

    def test_from_build_and_from_artifact_still_agree(self):
        from_build = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        from_artifact = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), STYLE, {})["plan"]
        self.assertEqual({n["name"]: (n["anchor_min"], n["anchor_max"]) for n in from_build["nodes"]},
                         {n["name"]: (n["anchor_min"], n["anchor_max"]) for n in from_artifact["nodes"]})



def _with_text_slot(key, bbox, role=""):
    """TEMPLATE + ARTIFACT with one more text slot at `bbox`."""
    t = copy.deepcopy(TEMPLATE)
    t["texts"].append({"key": key, "name": key, "index": 9, "nullable": True, "description": "",
                       "canBeHidden": True, "customFields": []})
    art = copy.deepcopy(ARTIFACT)
    art["elements"].append({"key": key, "bucket": "texts", "index": 9, "role": role, "bbox": bbox})
    return t, art


class TestDeOverlapRules(unittest.TestCase):
    def test_contained_text_on_a_button_is_an_overlay(self):
        t, art = _with_text_slot("price_text", {"x": 0.40, "y": 0.735, "w": 0.15, "h": 0.04}, "price_text")
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertEqual(plan["report"]["layout_adjustments"], [])
        self.assertIn(["CtaButton", "PriceText"], plan["report"]["overlays"])
        self.assertFalse(any("PriceText" in w for w in plan["report"]["warnings"]))

    def test_substantial_overlap_is_left_and_reported(self):
        art = copy.deepcopy(ARTIFACT)
        for e in art["elements"]:
            if e["key"] == "fine_print":
                e["bbox"] = {"x": 0.25, "y": 0.76, "w": 0.5, "h": 0.06}  # 43 % of the CTA
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertEqual(plan["report"]["layout_adjustments"], [])
        hits = [w for w in plan["report"]["warnings"] if "CtaButton" in w and "FinePrintText" in w]
        self.assertEqual(len(hits), 1)

    def test_split_uses_the_true_overlap_band_in_either_order(self):
        a, b = [0.0, 0.0, 1.0, 0.5], [0.0, 0.45, 1.0, 1.0]
        new_a, new_b = mod._split(a, b, {})
        self.assertAlmostEqual(new_a[3], 0.475 - mod._SPLIT_GAP / 2, places=6)
        self.assertAlmostEqual(new_b[1], 0.475 + mod._SPLIT_GAP / 2, places=6)
        swapped_b, swapped_a = mod._split(b, a, {})
        self.assertEqual((new_a, new_b), (swapped_a, swapped_b))
        self.assertIsNone(mod._split([0.0, 0.0, 1.0, 1.0], [0.2, 0.2, 0.8, 0.8], {}))  # nested both ways

    def test_no_free_space_is_reported_with_every_blocker(self):
        boxes = [mod._node("A%d" % i, "Panel", "text", placed=True, anchor_min=[0.0, i / 10.0],
                           anchor_max=[1.0, (i + 1) / 10.0 - 0.003]) for i in range(10)]
        lost = mod._node("Lost", "Panel", "zone", placed=False, anchor_min=[0.0, 0.0], anchor_max=[1.0, 0.25])
        report = {"warnings": []}
        mod.resolve_overlaps(boxes + [lost], report)
        hits = [w for w in report["warnings"] if w.startswith("Lost has no free space")]
        self.assertEqual(len(hits), 1)
        for name in ("A0", "A1", "A2"):
            self.assertIn(name, hits[0])

    def test_short_movable_box_is_still_placed(self):
        self.assertIsNotNone(mod._free_slot([0.1, 0.5, 0.9, 0.515], []))

    def test_unplaced_container_never_shrinks_below_its_rows(self):
        nodes = [mod._node("Wall", "Panel", "text", placed=True, anchor_min=[0.0, 0.0], anchor_max=[1.0, 0.6]),
                 mod._node("Unplaced", "Panel", "unplaced", placed=False, anchor_min=[0.05, 0.02], anchor_max=[0.95, 0.30])]
        nodes += [mod._node("Row%d" % i, "Unplaced", "text") for i in range(3)]
        report = {"warnings": []}
        mod.resolve_overlaps(nodes, report, panel_px_height=1000.0)
        unplaced = nodes[1]
        self.assertGreaterEqual(unplaced["anchor_max"][1] - unplaced["anchor_min"][1], 3 * 88.0 / 1000.0 - 1e-6)

    def test_every_anchor_stays_inside_the_panel(self):
        import random
        rng = random.Random(7)
        for _ in range(60):
            art = copy.deepcopy(ARTIFACT)
            for e in art["elements"]:
                if e.get("bbox"):
                    w, h = rng.uniform(0.05, 0.6), rng.uniform(0.02, 0.2)
                    e["bbox"] = {"x": rng.uniform(0, 1 - w), "y": rng.uniform(0, 1 - h), "w": w, "h": h}
            plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["plan"]
            for n in plan["nodes"]:
                if mod._is_flow(n):
                    for v in n["anchor_min"] + n["anchor_max"]:
                        self.assertGreaterEqual(v, -1e-6, n["name"])
                        self.assertLessEqual(v, 1 + 1e-6, n["name"])

    def test_milestone_markers_are_part_of_the_bar_footprint(self):
        bar = mod._node("MilestoneBar", "Panel", "zone", anchor_min=[0.1, 0.4], anchor_max=[0.9, 0.45])
        self.assertEqual(mod._box(bar), [0.1, 0.35000000000000003, 0.9, 0.5])
        mod._set_box(bar, [0.1, 0.55, 0.9, 0.70])
        self.assertEqual(bar["anchor_min"], [0.1, 0.6])
        self.assertEqual(bar["anchor_max"], [0.9, 0.65])

    def test_art_is_built_before_controls(self):
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), STYLE, {})["plan"]
        names = [n["name"] for n in plan["nodes"]]
        self.assertLess(names.index("BackgroundImage"), names.index("CloseButton"))
        self.assertLess(names.index("BackgroundImage"), names.index("HeaderText"))

    def test_panel_ignores_zones_that_are_not_built(self):
        t = copy.deepcopy(TEMPLATE)
        t["buttons"][1]["clickActionType"] = ["close", "deep_link"]  # no billing, no items
        art = copy.deepcopy(ARTIFACT)
        art["client_rendered"].append({"role": "grand_prize_area", "bbox": {"x": 0.0, "y": 0.95, "w": 1.0, "h": 0.05}})
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        panel = plan["report"]["panel_bbox"]
        self.assertLess(panel["y"] + panel["h"], 0.95)



class TestDeOverlapContainersAndOrder(unittest.TestCase):
    def test_container_partly_over_the_cta_is_warned_not_kept_silently(self):
        art = copy.deepcopy(ARTIFACT)
        for z in art["client_rendered"]:
            if z["role"] == "resource_area":
                z["bbox"] = {"x": 0.25, "y": 0.66, "w": 0.48, "h": 0.10}  # covers ~57 % of the CTA's height
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertNotIn(["CtaButton", "ResourceArea"], plan["report"]["overlays"])
        self.assertTrue(any("CtaButton" in w and "ResourceArea" in w for w in plan["report"]["warnings"]))
        trimmed = {a["node"] for a in plan["report"]["layout_adjustments"]}
        self.assertNotIn("ResourceArea", trimmed)  # a container is never trimmed

    def test_box_mostly_inside_a_container_is_an_overlay(self):
        nodes = [mod._node("MissionList", "Panel", "zone", placed=True, anchor_min=[0.1, 0.1], anchor_max=[0.9, 0.8]),
                 mod._node("SmallText", "Panel", "text", placed=True, anchor_min=[0.2, 0.70], anchor_max=[0.5, 0.77])]
        report = {"warnings": []}
        mod.resolve_overlaps(nodes, report)
        self.assertEqual(report["overlays"], [["MissionList", "SmallText"]])
        self.assertEqual(report["warnings"], [])

    def test_moved_milestone_bar_keeps_a_usable_height_and_records_anchors(self):
        wall = [mod._node("W%d" % i, "Panel", "text", placed=True, anchor_min=[0.0, i * 0.25],
                          anchor_max=[1.0, i * 0.25 + 0.17]) for i in range(4)]  # 0.08 gaps
        bar = mod._node("MilestoneBar", "Panel", "zone", placed=False, anchor_min=[0.1, 0.3], anchor_max=[0.9, 0.36])
        report = {"warnings": []}
        mod.resolve_overlaps(wall + [bar], report)
        moves = [a for a in report["layout_adjustments"] if a["node"] == "MilestoneBar"]
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["from"], [[0.1, 0.3], [0.9, 0.36]])  # anchors, not the marker footprint
        self.assertGreaterEqual(bar["anchor_max"][1] - bar["anchor_min"][1], mod._MIN_SLOT - 1e-6)

    def test_badge_images_render_in_front_of_controls(self):
        t = copy.deepcopy(TEMPLATE)
        t["images"].append({"key": "badge_image", "name": "Badge", "index": 9, "canBeHidden": True, "customFields": []})
        art = copy.deepcopy(ARTIFACT)
        art["elements"].append({"key": "badge_image", "bucket": "images", "index": 9, "role": "badge_image",
                                "bbox": {"x": 0.60, "y": 0.70, "w": 0.08, "h": 0.05}})
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertTrue(_node(plan, "BadgeImage")["placed"])
        names = [n["name"] for n in plan["nodes"]]
        self.assertLess(names.index("BackgroundImage"), names.index("CtaButton"))
        self.assertGreater(names.index("BadgeImage"), names.index("CtaButton"))


    def test_unplaced_container_is_sized_to_its_rows(self):
        plan = mod.plan_prefab(_milestone_template(), mod.layout_from_build(BUILD), STYLE, {})["plan"]
        unplaced = _node(plan, "Unplaced")
        rows = sum(1 for n in plan["nodes"] if n["parent"] == "Unplaced")
        panel_px = plan["ui"]["frame_size"][1] * plan["report"]["panel_bbox"]["h"]
        self.assertAlmostEqual(unplaced["anchor_max"][1] - unplaced["anchor_min"][1],
                               rows * 88.0 / panel_px + 0.01, places=3)


    def test_two_containers_are_never_trimmed(self):
        t = _milestone_template()  # its CTA is item-bearing, so ResourceArea is built too
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "chase"
        art["feature"] = {"type": "milestone"}
        art["elements"].append({"key": "bar_image", "bucket": "images", "index": 10, "role": "bar_image",
                                "bbox": {"x": 0.25, "y": 0.635, "w": 0.5, "h": 0.03}})  # markers graze ResourceArea
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        adjusted = {a["node"] for a in plan["report"]["layout_adjustments"]}
        self.assertNotIn("MilestoneBar", adjusted)
        self.assertNotIn("ResourceArea", adjusted)
        bar, art_node = _node(plan, "MilestoneBar"), _node(plan, "BarImage")
        self.assertEqual((bar["anchor_min"], bar["anchor_max"]), (art_node["anchor_min"], art_node["anchor_max"]))
        for v in bar["anchor_min"] + bar["anchor_max"]:
            self.assertTrue(0.0 <= v <= 1.0)

    def test_unplaced_container_grows_when_its_rows_need_more_room(self):
        plan = mod.plan_prefab(TEMPLATE, None, STYLE, {})["plan"]
        unplaced = _node(plan, "Unplaced")
        rows = sum(1 for n in plan["nodes"] if n["parent"] == "Unplaced")
        panel_px = plan["ui"]["frame_size"][1] * plan["report"]["panel_bbox"]["h"]
        need = min(1.0, rows * 88.0 / panel_px + 0.01)
        self.assertGreaterEqual(unplaced["anchor_max"][1] - unplaced["anchor_min"][1], need - 1e-3)
        sized = [a for a in plan["report"]["layout_adjustments"] if a["node"] == "Unplaced" and a["reason"] == "sized_to_rows"]
        self.assertEqual(len(sized), 1)

    def test_badge_role_without_badge_key_renders_in_front(self):
        t = copy.deepcopy(TEMPLATE)
        t["images"].append({"key": "sale_sticker", "name": "Sticker", "index": 9, "canBeHidden": True, "customFields": []})
        art = copy.deepcopy(ARTIFACT)
        art["elements"].append({"key": "sale_sticker", "bucket": "images", "index": 9, "role": "badge_image",
                                "bbox": {"x": 0.60, "y": 0.70, "w": 0.08, "h": 0.05}})
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        names = [n["name"] for n in plan["nodes"]]
        self.assertGreater(names.index("SaleStickerImage"), names.index("CtaButton"))
