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
FIX_MISSIONS = os.path.join(SKILL, "evals", "fixtures", "missions")

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


TEMPLATE = _load("template_one_cta.json")
BUILD = _load("build_result_one_cta.json")
with open(os.path.join(FIX_MISSIONS, "template_missions.json"), encoding="utf-8") as _fh:
    MISSIONS = json.load(_fh)
with open(os.path.join(FIX_MISSIONS, "daily_missions.layout.json"), encoding="utf-8") as _fh:
    ART_RAW = json.load(_fh)
ART = mod.layout_from_artifact(ART_RAW)
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


def _milestone_template(buttons=None):
    t = copy.deepcopy(TEMPLATE)
    if buttons is not None:
        t["buttons"] = [b for b in t["buttons"] if b["key"] in buttons]
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
        scroll = _node(plan, "MilestoneScroll")
        self.assertEqual(scroll["field"], "milestoneScroll")
        amin, _ = mod.anchors_from_bbox({"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.04}, plan["report"]["panel_bbox"])
        self.assertEqual(scroll["anchor_min"], amin)  # follows bar_image
        self.assertEqual(_node(plan, "MilestoneContent")["components"], ["HorizontalLayoutGroup", "ContentSizeFitter"])
        step = _node(plan, "MilestoneStep")
        self.assertEqual(step["parent"], "MilestoneContent")
        self.assertEqual(step["field"], "milestoneStepTemplate")
        # the template's one CTA slot is the milestone CTA, so no extra main button is built
        self.assertNotIn("MilestoneMainButton", [n["name"] for n in plan["nodes"]])
        self.assertEqual(_node(plan, "GrandPrizeArea")["field"], "grandPrizeRoot")
        self.assertEqual(plan["template"]["feature_type"], "milestone")

    def test_mission_nodes_with_and_without_bar(self):
        plan = mod.plan_prefab(_mission_template(), None, STYLE, {})["plan"]
        # the task list is the shared scroll chain, vertical: rows live under MissionViewport/MissionRows
        self.assertEqual(_node(plan, "MissionList")["field_type"], "ScrollRect")
        self.assertEqual(_node(plan, "MissionList")["components"], ["ScrollRect"])
        self.assertEqual(_node(plan, "MissionRows")["components"], ["VerticalLayoutGroup", "ContentSizeFitter"])
        self.assertEqual(_node(plan, "MissionRow")["field"], "missionRowTemplate")
        self.assertEqual(_node(plan, "MissionRow")["field_type"], "KinoaInAppMissionRowView")
        self.assertEqual(_node(plan, "MissionBarStep")["field"], "missionBarStepTemplate")
        self.assertIn("MissionList", plan["report"]["estimated_positions"])
        names = [n["name"] for n in plan["nodes"]]
        for name in ("MissionBar", "MissionBarFill", "MissionBarMarkers", "MissionBarMarker"):
            self.assertNotIn(name, names)   # the bar-and-markers shape is gone: the bar is a milestone ladder
        plan2 = mod.plan_prefab(_mission_template("dont_show_at_all"), None, STYLE, {})["plan"]
        names2 = [n["name"] for n in plan2["nodes"]]
        for name in ("MissionBarScroll", "MissionBarViewport", "MissionBarContent", "MissionBarStep"):
            self.assertNotIn(name, names2)
        self.assertIn("MissionTabs", names2)

    def test_part_nodes_only_live_under_tab_or_row_templates(self):
        # The builder fails a build on a tab_part / row_part with no template above it; slot nodes with a
        # layout role must never be such parts.
        art = mod.layout_from_artifact(ARTIFACT)
        standard = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        standard_art = mod.plan_prefab(TEMPLATE, art, STYLE, {})["plan"]
        milestone_template = _milestone_template()
        milestone_art = copy.deepcopy(ARTIFACT)
        milestone_art["template_key"] = milestone_template["key"]
        milestone = mod.plan_prefab(milestone_template, mod.layout_from_artifact(milestone_art), STYLE, {})["plan"]
        self.assertTrue(any(n.get("role") for n in milestone["nodes"]), "fixture slots should carry layout roles")
        self.assertTrue(any(n.get("role") for n in standard_art["nodes"]), "fixture slots should carry layout roles")
        for plan in (standard, standard_art, milestone):
            self.assertEqual([n["name"] for n in plan["nodes"] if n["binding"] in ("tab_part", "row_part")], [])
        mission = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        by_name = {n["name"]: n for n in mission["nodes"]}
        parts = [n for n in mission["nodes"] if n["binding"] in ("tab_part", "row_part")]
        self.assertTrue(parts)
        for node in parts:
            parent, found = node["parent"], None
            while parent and not found:
                anc = by_name[parent]
                found = anc if anc["binding"] in ("tab_template", "mission_row_template") else None
                parent = anc["parent"]
            self.assertIsNotNone(found, "%s has no tab/row template ancestor" % node["name"])


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
        mission_bar = _node(plan, "MissionBarScroll")
        self.assertFalse(mission_bar["placed"])

    def test_milestone_nodes_without_layout_have_placed_false(self):
        plan = mod.plan_prefab(_milestone_template(buttons=["close_button"]), None, STYLE, {})["plan"]
        scroll = _node(plan, "MilestoneScroll")
        self.assertFalse(scroll["placed"])
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

    def test_milestone_area_bbox_places_the_scroll_when_no_bar_image(self):
        art = copy.deepcopy(ARTIFACT)
        art["template_key"] = "chase"
        art["feature"] = {"type": "milestone", "area_bbox": {"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.05}}
        plan = mod.plan_prefab(_milestone_template(), mod.layout_from_artifact(art), STYLE, {})["plan"]
        scroll = _node(plan, "MilestoneScroll")
        self.assertTrue(scroll["placed"])
        self.assertNotIn("MilestoneScroll", plan["report"]["estimated_positions"])

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
        self.assertFalse(_node(plan, "MilestoneScroll")["placed"])
        self.assertIn("MilestoneScroll", plan["report"]["estimated_positions"])

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
                                "bbox": {"x": 0.25, "y": 0.635, "w": 0.5, "h": 0.03}})  # grazes ResourceArea
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        adjusted = {a["node"] for a in plan["report"]["layout_adjustments"]}
        self.assertNotIn("MilestoneScroll", adjusted)
        self.assertNotIn("ResourceArea", adjusted)
        bar, art_node = _node(plan, "MilestoneScroll"), _node(plan, "BarImage")
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


class TestCliOutputEncoding(unittest.TestCase):
    def test_stdout_is_utf8_even_on_a_legacy_console(self):
        import subprocess, sys, tempfile
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        out = os.path.join(tempfile.mkdtemp(), "p.json")
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"), "--out", out],
                             capture_output=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout.decode("utf-8"))  # the no-layout warning contains an em-dash
        self.assertTrue(any("—" in w for w in data["report"]["warnings"]))


class TestPlanCanvas(unittest.TestCase):
    def test_default_canvas_fits_a_popup_and_the_design_frame(self):
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), STYLE, {})["plan"]
        self.assertEqual(plan["ui"]["canvas"], {"render_mode": "overlay", "override_sorting": True, "sorting_order": 100,
                                                "scale_mode": "scale_with_screen_size",
                                                "reference_resolution": plan["ui"]["frame_size"], "match": 0.5,
                                                "source": "default"})
        self.assertTrue(any("Canvas" in n and "align" in n for n in plan["report"]["needs_developer"]))

    def test_probed_canvas_is_copied(self):
        probed = {"render_mode": "camera", "override_sorting": True, "sorting_order": 250,
                  "scale_mode": "scale_with_screen_size", "reference_resolution": [1080.0, 1920.0], "match": 0.3,
                  "graphic_raycaster": True, "source": "PopupWithCanvas"}
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_artifact(ARTIFACT), dict(STYLE, canvas=probed), {})["plan"]
        canvas = plan["ui"]["canvas"]
        self.assertEqual((canvas["render_mode"], canvas["sorting_order"], canvas["reference_resolution"], canvas["match"]),
                         ("camera", 250, [1080.0, 1920.0], 0.3))
        self.assertEqual(canvas["source"], "PopupWithCanvas")
        self.assertTrue(any("camera" in n.lower() for n in plan["report"]["needs_developer"]))


def _with_collect_all(t, key="collect_all_button", name="Collect All"):
    t["buttons"].append({"key": key, "name": name, "index": 20, "canBeHidden": True,
                         "clickActionType": ["collect_resource"], "customFields": []})
    return t


def _ms_artifact(unplaced=()):
    art = copy.deepcopy(ARTIFACT)
    art["template_key"] = "chase"
    art["feature"] = {"type": "milestone"}
    for e in art["elements"]:
        if e["key"] in unplaced:
            e["bbox"] = None
            e["unplaced"] = True
    return art


def _plan_ms(template, artifact=False, unplaced=(), **opts):
    layout = mod.layout_from_artifact(_ms_artifact(unplaced)) if artifact else None
    result = mod.plan_prefab(template, layout, STYLE, opts)
    assert result["ok"], result
    return result["plan"]


class TestMilestoneCtaMode(unittest.TestCase):
    def test_one_placed_cta_slot_means_single(self):
        plan = _plan_ms(_milestone_template(), artifact=True)
        cta = next(n for n in plan["nodes"] if n.get("key") == "cta_button" and n["binding"] == "button")
        ms = plan["milestone"]
        self.assertEqual((ms["cta_mode"], ms["cta_mode_source"]), ("single", "template_cta_count"))
        self.assertEqual(ms["single_cta"], {"key": "cta_button", "button_field": cta["field"],
                                            "label_field": cta["field"] + "Label"})
        self.assertEqual(ms["cta_slots"], ["cta_button"])

    def test_no_cta_slot_means_per_step(self):
        ms = _plan_ms(_milestone_template(buttons=["close_button"]))["milestone"]
        self.assertEqual((ms["cta_mode"], ms["cta_mode_source"], ms["single_cta"]), ("per_step", "default", None))

    def _two_cta_template(self):
        t = _milestone_template()
        t["buttons"].append({"key": "second_button", "name": "Second", "index": 6, "canBeHidden": False,
                             "clickActionType": ["deep_link"], "customFields": []})
        return t

    def test_two_cta_slots_mean_per_step(self):
        ms = _plan_ms(self._two_cta_template())["milestone"]
        self.assertEqual((ms["cta_mode"], ms["cta_mode_source"], ms["single_cta"]), ("per_step", "default", None))
        self.assertEqual(ms["cta_slots"], ["cta_button", "second_button"])

    def test_unplaced_cta_slot_is_not_on_the_tip_image(self):
        ms = _plan_ms(_milestone_template(), artifact=True, unplaced=("cta_button",))["milestone"]
        self.assertEqual(ms["cta_slots"], [])
        self.assertEqual((ms["cta_mode"], ms["cta_mode_source"]), ("per_step", "default"))

    def test_override_single_without_slot_uses_main_button(self):
        ms = _plan_ms(_milestone_template(buttons=["close_button"]), milestone_cta="single")["milestone"]
        self.assertEqual(ms["cta_mode_source"], "override")
        self.assertEqual(ms["single_cta"], {"key": None, "button_field": "milestoneMainButton",
                                            "label_field": "milestoneMainButtonLabel"})

    def test_override_per_step_wins_over_single_cta_slot(self):
        ms = _plan_ms(_milestone_template(), milestone_cta="per_step")["milestone"]
        self.assertEqual((ms["cta_mode"], ms["cta_mode_source"], ms["single_cta"]), ("per_step", "override", None))

    def test_override_single_with_two_slots_warns(self):
        plan = _plan_ms(self._two_cta_template(), milestone_cta="single")
        self.assertEqual(plan["milestone"]["single_cta"]["key"], None)
        self.assertTrue(any("--milestone-cta single with 2 CTA slots" in w for w in plan["report"]["warnings"]))

    def test_collect_all_by_key_and_by_name(self):
        by_key = _plan_ms(_with_collect_all(_milestone_template()))["milestone"]
        self.assertEqual(by_key["collect_all"]["key"], "collect_all_button")
        self.assertTrue(by_key["collect_all"]["can_be_hidden"])
        self.assertEqual(by_key["collect_all"]["label_field"], by_key["collect_all"]["button_field"] + "Label")
        self.assertNotIn("collect_all_button", by_key["cta_slots"])
        self.assertEqual((by_key["cta_mode"], by_key["cta_slots"]), ("single", ["cta_button"]))
        by_name = _plan_ms(_with_collect_all(_milestone_template(), key="claim_btn", name="Claim All"))["milestone"]
        self.assertEqual(by_name["collect_all"]["key"], "claim_btn")
        self.assertNotIn("claim_btn", by_name["cta_slots"])

    def test_several_collect_all_slots_warn_and_first_by_index_wins(self):
        t = _with_collect_all(_milestone_template())
        t["buttons"].append({"key": "claim_all", "name": "Claim all", "index": 21, "canBeHidden": False,
                             "clickActionType": ["collect_resource"], "customFields": []})
        plan = _plan_ms(t)
        self.assertEqual(plan["milestone"]["collect_all"]["key"], "collect_all_button")
        self.assertTrue(any("collect-all" in w for w in plan["report"]["warnings"]))

    def _with_info(self, t, actions=("custom", "close")):
        t["buttons"].append({"key": "info_button", "name": "Info", "index": 7, "canBeHidden": False,
                             "clickActionType": list(actions), "customFields": []})
        return t

    def test_info_button_with_custom_action_is_not_a_cta(self):
        ms = _plan_ms(self._with_info(_milestone_template(buttons=["close_button"])))["milestone"]
        self.assertEqual(ms["cta_slots"], [])
        self.assertEqual((ms["cta_mode"], ms["cta_mode_source"]), ("per_step", "default"))

    def test_info_button_beside_one_cta_keeps_single(self):
        ms = _plan_ms(self._with_info(_milestone_template()))["milestone"]
        self.assertEqual(ms["cta_slots"], ["cta_button"])
        self.assertEqual((ms["cta_mode"], ms["single_cta"]["key"]), ("single", "cta_button"))

    def test_info_button_role_is_never_a_cta(self):
        t = self._with_info(_milestone_template(buttons=["close_button"]), actions=("deep_link",))
        art = _ms_artifact()
        art["elements"].append({"bucket": "buttons", "key": "info_button", "role": "info_button",
                                "bbox": {"x": 0.1, "y": 0.04, "w": 0.08, "h": 0.06}})
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertEqual(plan["milestone"]["cta_slots"], [])
        self.assertEqual(plan["milestone"]["cta_mode"], "per_step")
        # without the role the same deep_link button would be the single CTA
        art["elements"][-1]["role"] = "secondary_button"
        plan = mod.plan_prefab(t, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertEqual(plan["milestone"]["cta_slots"], ["info_button"])

    def test_secondary_close_and_deep_link_button_still_counts(self):
        t = _milestone_template(buttons=["close_button"])
        t["buttons"].append({"key": "more_button", "name": "More", "index": 7, "canBeHidden": False,
                             "clickActionType": ["close", "deep_link"], "customFields": []})
        ms = _plan_ms(t)["milestone"]
        self.assertEqual((ms["cta_mode"], ms["cta_slots"]), ("single", ["more_button"]))

    def test_collect_all_pattern_needs_word_boundaries(self):
        rx = mod._COLLECT_ALL_RE
        for text in ("collect_all_button", "Collect All", "claim_all", "Get All", "btn_get-all", "collectall"):
            self.assertTrue(rx.search(text), text)
        for text in ("budget_all", "forget_all", "collect_allowance", "reclaim all", "get_allies"):
            self.assertFalse(rx.search(text), text)
        t = _with_collect_all(_milestone_template(), key="budget_all", name="Budget all")
        ms = _plan_ms(t)["milestone"]
        self.assertIsNone(ms["collect_all"])

    def test_collect_all_ignored_on_standard_template(self):
        plan = mod.plan_prefab(_with_collect_all(copy.deepcopy(TEMPLATE)), None, STYLE, {})["plan"]
        self.assertNotIn("milestone", plan)

    def test_report_summary(self):
        plan = _plan_ms(_with_collect_all(_milestone_template()))
        self.assertEqual(plan["report"]["milestone"], {"cta_mode": "single", "cta_mode_source": "template_cta_count",
                                                       "collect_all": "collect_all_button"})

    def test_cli_flag(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tpath = os.path.join(tmp, "t.json")
            with open(tpath, "w", encoding="utf-8") as fh:
                json.dump(_milestone_template(), fh)
            out = os.path.join(tmp, "plan.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mod.main(["plan", "--template", tpath, "--milestone-cta", "per_step", "--out", out]), 0)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["milestone"]["cta_mode_source"], "override")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                mod.main(["plan", "--template", tpath, "--milestone-cta", "bogus", "--out", out])
            self.assertEqual(cm.exception.code, 2)


def _ms_names(plan):
    return [n["name"] for n in plan["nodes"]]


class TestMilestoneScrollNodes(unittest.TestCase):
    def test_scroll_chain(self):
        plan = _plan_ms(_milestone_template(buttons=["close_button"]))
        rows = [(n["name"], n["parent"], n["binding"], n["components"], n["field"], n["field_type"])
                for n in plan["nodes"] if n["name"].startswith("Milestone")]
        self.assertEqual(rows[:4], [
            ("MilestoneScroll", "Panel", "scroll", ["ScrollRect"], "milestoneScroll", "ScrollRect"),
            ("MilestoneViewport", "MilestoneScroll", "viewport", ["Image", "RectMask2D"], None, None),
            ("MilestoneContent", "MilestoneViewport", "scroll_content",
             ["HorizontalLayoutGroup", "ContentSizeFitter"], "milestoneContent", "RectTransform"),
            ("MilestoneStep", "MilestoneContent", "milestone_step", [], "milestoneStepTemplate",
             "KinoaInAppMilestoneStepView")])

    def test_chain_geometry(self):
        plan = _plan_ms(_milestone_template(buttons=["close_button"]))
        viewport, content, step = _node(plan, "MilestoneViewport"), _node(plan, "MilestoneContent"), _node(plan, "MilestoneStep")
        self.assertEqual((viewport["anchor_min"], viewport["anchor_max"]), ([0.0, 0.0], [1.0, 1.0]))
        self.assertEqual((content["anchor_min"], content["anchor_max"]), ([0.0, 0.0], [0.0, 1.0]))
        self.assertTrue(step["inactive"])
        self.assertEqual(len(step["size"]), 2)

    def test_step_button_only_in_per_step(self):
        per_step = _plan_ms(_milestone_template(buttons=["close_button"]))
        self.assertEqual(per_step["milestone"]["cta_mode"], "per_step")
        self.assertTrue(_node(per_step, "MilestoneStep")["step_button"])
        single = _plan_ms(_milestone_template(buttons=["close_button"]), milestone_cta="single")
        self.assertFalse(_node(single, "MilestoneStep")["step_button"])

    def test_single_slot_mode_builds_no_main_button(self):
        plan = _plan_ms(_milestone_template(), artifact=True)
        self.assertEqual(plan["milestone"]["single_cta"]["key"], "cta_button")
        names = _ms_names(plan)
        self.assertNotIn("MilestoneMainButton", names)
        self.assertNotIn("MilestoneMainButtonLabel", names)
        self.assertTrue(any(n.get("key") == "cta_button" and n["binding"] == "button" for n in plan["nodes"]))

    def test_single_without_slot_keeps_main_button(self):
        plan = _plan_ms(_milestone_template(buttons=["close_button"]), milestone_cta="single")
        self.assertIsNone(plan["milestone"]["single_cta"]["key"])
        self.assertIn("MilestoneMainButton", _ms_names(plan))
        self.assertEqual(_node(plan, "MilestoneMainButtonLabel")["parent"], "MilestoneMainButton")

    def test_per_step_keeps_main_button(self):
        plan = _plan_ms(_milestone_template(buttons=["close_button"]))
        self.assertIn("MilestoneMainButton", _ms_names(plan))

    def test_scroll_prefers_feature_area_over_bar_image(self):
        art = _ms_artifact()
        art["feature"] = {"type": "milestone", "area_bbox": {"x": 0.2, "y": 0.5, "w": 0.6, "h": 0.1}}
        art["elements"].append({"key": "bar_image", "bucket": "images", "index": 10, "role": "bar_image",
                                "bbox": {"x": 0.3, "y": 0.7, "w": 0.4, "h": 0.03}})
        plan = mod.plan_prefab(_milestone_template(), mod.layout_from_artifact(art), STYLE, {})["plan"]
        scroll = _node(plan, "MilestoneScroll")
        panel = plan["report"]["panel_bbox"]
        amin, amax = mod.anchors_from_bbox({"x": 0.2, "y": 0.5, "w": 0.6, "h": 0.1}, panel)
        self.assertTrue(scroll["placed"])
        self.assertEqual((scroll["anchor_min"], scroll["anchor_max"]), (amin, amax))
        self.assertNotIn("MilestoneScroll", plan["report"]["estimated_positions"])

    def test_scroll_falls_back_to_bar_image_then_default(self):
        layout = mod.layout_from_build(BUILD)
        layout["elements"].append({"bucket": "images", "key": "bar_image", "role": "bar_image",
                                   "bbox": {"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.04}, "observed_text": None})
        plan = mod.plan_prefab(_milestone_template(), layout, STYLE, {})["plan"]
        scroll = _node(plan, "MilestoneScroll")
        amin, amax = mod.anchors_from_bbox({"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.04}, plan["report"]["panel_bbox"])
        self.assertTrue(scroll["placed"])
        self.assertEqual((scroll["anchor_min"], scroll["anchor_max"]), (amin, amax))
        no_layout = mod.plan_prefab(_milestone_template(), None, STYLE, {})["plan"]
        self.assertFalse(_node(no_layout, "MilestoneScroll")["placed"])
        self.assertIn("MilestoneScroll", no_layout["report"]["estimated_positions"])
        self.assertEqual(mod._ZONE_DEFAULT_ANCHORS["milestone_scroll"], ([0.05, 0.3], [0.95, 0.55]))

    def _step_size(self, scroll_h_anchor, frame=(1080, 1920), panel_h=1.0):
        plan = {"nodes": [], "ui": {"frame_size": list(frame)},
                "report": {"estimated_positions": [], "warnings": []},
                "milestone": {"cta_mode": "per_step", "cta_mode_source": "default", "cta_slots": [],
                              "single_cta": None, "collect_all": None}}
        area = {"x": 0.0, "y": 0.4, "w": 1.0, "h": scroll_h_anchor}
        mod._add_feature(plan, _milestone_template(), {}, {"x": 0.0, "y": 0.0, "w": 1.0, "h": panel_h}, area)
        return next(n for n in plan["nodes"] if n["name"] == "MilestoneStep")["size"]

    def test_step_size_formula(self):
        w, h = self._step_size(0.25)          # 1920 * 1.0 * 0.25 = 480 px -> h = 464
        self.assertEqual((h, w), (464, 260))

    def test_step_size_is_clamped(self):
        w, h = self._step_size(0.02)          # ~38 px scroll -> floor
        self.assertEqual((h, w), (120, 120))
        w, h = self._step_size(0.10)          # 192 px -> h = 176, w = 132
        self.assertEqual((h, w), (176, 132))

    def test_every_node_carries_step_button(self):
        for template in (_milestone_template(), _mission_template(), copy.deepcopy(TEMPLATE)):
            if template["featureType"] == "milestone":
                plan = _plan_ms(template)
            else:
                plan = mod.plan_prefab(template, None, STYLE, {})["plan"]
            self.assertTrue(all("step_button" in n for n in plan["nodes"]), template["featureType"])
        self.assertIs(mod._node("x", "Panel", "text")["step_button"], False)

    def test_scroll_is_never_split(self):
        scroll = mod._node("MilestoneScroll", "Panel", "scroll", ["ScrollRect"], placed=True,
                           anchor_min=[0.1, 0.40], anchor_max=[0.9, 0.55])
        text = mod._node("GrazingText", "Panel", "text", placed=True,
                         anchor_min=[0.2, 0.53], anchor_max=[0.8, 0.62])
        before = (list(scroll["anchor_min"]), list(scroll["anchor_max"]))
        report = {"warnings": []}
        mod.resolve_overlaps([scroll, text], report)
        self.assertEqual((scroll["anchor_min"], scroll["anchor_max"]), before)
        self.assertEqual([a for a in report["layout_adjustments"] if a["node"] == "MilestoneScroll"], [])

    def test_scroll_names_are_reserved(self):
        for name in ("MilestoneScroll", "MilestoneViewport", "MilestoneContent", "MilestoneStep"):
            self.assertIn(name, mod.RESERVED_NODE_NAMES)
        for fld in ("milestoneScroll", "milestoneContent", "milestoneStepTemplate"):
            self.assertIn(fld, mod.RESERVED_FIELDS)
        self.assertIn("MilestoneScroll", mod._CONTAINERS)


class TestMissionActions(unittest.TestCase):
    def test_mission_action_detection(self):
        f = mod.mission_action
        self.assertEqual(f({"key": "collect_all_button", "name": "x"}), "collect_all")
        self.assertEqual(f({"key": "btn_1", "name": "Claim All"}), "collect_all")
        self.assertEqual(f({"key": "reachAll", "name": ""}), "reach_all")
        self.assertEqual(f({"key": "collect_all_milestones", "name": ""}), "collect_all_milestones")
        self.assertEqual(f({"key": "btn_2", "name": "Claim all bar rewards"}), "collect_all_milestones")
        for key, name in (("collect_button", "Collect"), ("collect_resources", "Collect resources"),
                          ("reach_level", "Reach level"), ("cta_button", "CTA")):
            self.assertIsNone(f({"key": key, "name": name}), key)

    def test_feature_actions_marked_and_reported(self):
        plan = mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]
        self.assertEqual(_node(plan, "CollectAllButton")["feature_action"], "collect_all")
        self.assertEqual(_node(plan, "ReachAllButton")["feature_action"], "reach_all")
        self.assertEqual(_node(plan, "CollectAllMilestonesButton")["feature_action"], "collect_all_milestones")
        self.assertIsNone(_node(plan, "CloseButton")["feature_action"])
        self.assertEqual(plan["report"]["mission_actions"], {"reach_all": "reach_all_button", "collect_all": "collect_all_button",
                                                             "collect_all_milestones": "collect_all_milestones_button"})

    def test_feature_actions_only_on_mission_templates(self):
        t = copy.deepcopy(MISSIONS); t["featureType"] = "standard"; t["features"] = {}
        plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
        self.assertIsNone(_node(plan, "CollectAllButton")["feature_action"])
        self.assertNotIn("mission_actions", plan["report"])

    def test_duplicate_feature_action_keeps_lowest_index(self):
        t = copy.deepcopy(MISSIONS)
        t["buttons"].append({"key": "claim_all", "name": "Claim all", "index": 12, "canBeHidden": True,
                             "customFields": [], "clickActionType": ["collect_resource"]})
        plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
        self.assertEqual(plan["report"]["mission_actions"]["collect_all"], "collect_all_button")
        self.assertIsNone(_node(plan, "ClaimAllButton")["feature_action"])
        self.assertTrue(any("claim_all" in w and "collect_all" in w for w in plan["report"]["warnings"]))

    def test_duplicate_feature_action_sorts_by_index_not_list_order(self):
        t = copy.deepcopy(MISSIONS)
        for slot in t["buttons"]:
            if slot["key"] != "close_button":
                slot["index"] += 1                     # make room for an index below collect_all_button's
        t["buttons"].append({"key": "claim_all", "name": "Claim all", "index": 8, "canBeHidden": True,
                             "customFields": [], "clickActionType": ["collect_resource"]})   # last in the list, lowest index
        plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
        self.assertEqual(plan["report"]["mission_actions"]["collect_all"], "claim_all")
        self.assertEqual(_node(plan, "ClaimAllButton")["feature_action"], "collect_all")
        self.assertIsNone(_node(plan, "CollectAllButton")["feature_action"])
        self.assertTrue(any("collect_all_button" in w and "claim_all" in w for w in plan["report"]["warnings"]))

    def test_feature_action_buttons_do_not_request_zones(self):
        self.assertNotIn("resource_area", mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]["report"]["client_zones"])

    def test_collect_all_milestones_needs_a_bar(self):
        t = copy.deepcopy(MISSIONS); t["features"]["mission"]["progressBar"] = {"display": "dont_show_at_all"}
        plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
        self.assertIsNone(plan["report"]["mission_actions"]["collect_all_milestones"])
        self.assertTrue(any("collect_all_milestones_button" in w and "progress bar" in w for w in plan["report"]["warnings"]))


class TestMissionGeometry(unittest.TestCase):
    def test_mission_node_tree_shape(self):
        plan = mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]
        for name, parent, binding in (("MissionTabs", "Panel", "zone"), ("MissionTab", "MissionTabs", "tab_template"),
                                      ("MissionList", "Panel", "scroll"), ("MissionViewport", "MissionList", "viewport"),
                                      ("MissionRows", "MissionViewport", "scroll_content"),
                                      ("MissionRow", "MissionRows", "mission_row_template"), ("MissionRowDismiss", "MissionRow", "row_part"),
                                      ("MissionRowReward", "MissionRowRewards", "item_template"),
                                      ("MissionBarScroll", "Panel", "scroll"), ("MissionBarViewport", "MissionBarScroll", "viewport"),
                                      ("MissionBarContent", "MissionBarViewport", "scroll_content"),
                                      ("MissionBarStep", "MissionBarContent", "milestone_step")):
            n = _node(plan, name)
            self.assertEqual((n["parent"], n["binding"]), (parent, binding), name)
        self.assertEqual(_node(plan, "MissionRowTitle")["role"], "titleText")
        self.assertIsNone(_node(plan, "MissionRowTitle")["field"])
        names = [n["name"] for n in plan["nodes"]]
        self.assertTrue(all(names.index(n["parent"]) < names.index(n["name"]) for n in plan["nodes"] if n["parent"]))
        self.assertTrue({"MissionTabs", "MissionList", "MissionBarScroll"} <= set(mod._CONTAINERS))
        self.assertEqual(plan["report"]["mission_geometry"]["source"], "defaults")

    def test_mission_geometry_from_artifact(self):
        plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        feat = ART_RAW["feature"]
        close = lambda a, b: all(abs(x - y) < 1e-3 for x, y in zip(a, b))   # report.panel_bbox is rounded to 4 places
        self.assertTrue(close(_node(plan, "MissionList")["anchor_min"], mod.anchors_from_bbox(feat["parts"]["task_list"], plan["report"]["panel_bbox"])[0]))
        self.assertEqual(_node(plan, "MissionRowTitle")["anchor_min"], mod.anchors_from_bbox(feat["row_parts"]["title"], feat["parts"]["row"])[0])
        fw, fh = plan["ui"]["frame_size"]
        self.assertEqual(_node(plan, "MissionRow")["size"], [round(feat["parts"]["row"]["w"] * fw, 1), round(feat["parts"]["row"]["h"] * fh, 1)])
        self.assertEqual(_node(plan, "MissionRow")["color"], feat["style"]["card"])
        self.assertEqual(_node(plan, "MissionBarStep")["color"], feat["style"]["bar_fill"])      # each step's progress fill
        self.assertEqual(_node(plan, "MissionBarViewport")["color"], feat["style"]["bar_track"])  # the ladder's backdrop
        self.assertEqual(plan["report"]["mission_geometry"]["defaulted"], [])

    def test_mission_geometry_falls_back_per_part(self):
        art = copy.deepcopy(ART_RAW); del art["feature"]["row_parts"]["status"]; del art["feature"]["parts"]["tabs"]
        plan = mod.plan_prefab(MISSIONS, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertEqual(sorted(plan["report"]["mission_geometry"]["defaulted"]), ["MissionRowStatus", "MissionTabs"])
        self.assertEqual(_node(plan, "MissionRowStatus")["anchor_min"], [0.77, 0.66])

    def test_invalid_part_and_colour_degrade_with_warning(self):
        art = copy.deepcopy(ART_RAW); art["feature"]["parts"]["row"] = {"x": 2, "y": 0, "w": 1, "h": 1}; art["feature"]["style"]["card"] = "blue"
        layout = mod.layout_from_artifact(art)          # must not raise
        plan = mod.plan_prefab(MISSIONS, layout, STYLE, {})["plan"]
        self.assertIsNone(_node(plan, "MissionRow")["color"])
        self.assertIn("MissionRow", plan["report"]["mission_geometry"]["defaulted"])
        self.assertTrue(any("parts.row" in w for w in plan["report"]["warnings"]))

    # --- beyond the brief: the contract details the planner relies on

    def test_fixture_joins_its_template_cleanly(self):
        report = mod.plan_prefab(MISSIONS, ART, STYLE, {})["report"]
        self.assertEqual([w for w in report["warnings"] if "layout artifact" in w], [])
        self.assertEqual(report["unmapped_layout"], [])
        geo = report["mission_geometry"]
        self.assertEqual(geo["source"], "layout_artifact")
        self.assertEqual(geo["parts"], list(mod.MISSION_PARTS))
        self.assertEqual(geo["row_parts"], list(mod.MISSION_ROW_PARTS))
        self.assertEqual(geo["style"], list(mod.MISSION_STYLE_KEYS))

    def test_every_node_carries_color(self):
        for template, layout in ((MISSIONS, ART), (TEMPLATE, mod.layout_from_build(BUILD)), (_milestone_template(), None)):
            plan = mod.plan_prefab(template, layout, STYLE, {})["plan"]
            self.assertTrue(all("color" in n for n in plan["nodes"]))
        standard = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        self.assertTrue(all(n["color"] is None for n in standard["nodes"]))
        self.assertNotIn("mission_geometry", standard["report"])

    def test_card_children_follow_the_row_and_colours_follow_style(self):
        plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        feat = ART_RAW["feature"]
        for name, part in (("MissionRowPlacement", "placement_badge"), ("MissionRowDismiss", "dismiss_button"),
                           ("MissionRowProgress", "progress_track"), ("MissionRowAction", "action_button")):
            amin, amax = mod.anchors_from_bbox(feat["row_parts"][part], feat["parts"]["row"])
            self.assertEqual((_node(plan, name)["anchor_min"], _node(plan, name)["anchor_max"]), (amin, amax), name)
            self.assertIsNone(_node(plan, name)["field"])
        fw, fh = plan["ui"]["frame_size"]
        self.assertEqual(_node(plan, "MissionTab")["size"], [round(feat["parts"]["tab"]["w"] * fw, 1), round(feat["parts"]["tab"]["h"] * fh, 1)])
        self.assertEqual(_node(plan, "MissionTab")["color"], "#00000000")
        for name, key in (("MissionTabLabel", "tab_text"), ("MissionTabSelected", "tab_selected"), ("MissionRowPlacement", "accent"),
                          ("MissionRowActionLabel", "card_text"), ("MissionRowProgressFill", "progress_fill"),
                          ("MissionRowAction", "action"), ("MissionRowDismiss", "dismiss"), ("MissionBarViewport", "bar_track"),
                          ("MissionBarStep", "bar_fill")):
            self.assertEqual(_node(plan, name)["color"], feat["style"][key], name)
        self.assertEqual(_node(plan, "MissionRowProgressFill")["role"], "progressFill")
        self.assertTrue(_node(plan, "MissionRow")["inactive"] and _node(plan, "MissionTab")["inactive"])

    def test_panel_level_parts_are_placed_from_the_artifact(self):
        plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        feat = ART_RAW["feature"]
        panel = plan["report"]["panel_bbox"]
        close = lambda a, b: all(abs(x - y) < 1e-3 for x, y in zip(a, b))
        for name, part in (("MissionTabs", "tabs"), ("MissionBarScroll", "progress_bar")):
            node = _node(plan, name)
            self.assertTrue(close(node["anchor_min"] + node["anchor_max"], sum(mod.anchors_from_bbox(feat["parts"][part], panel), [])), name)
            self.assertTrue(node["placed"], name)
            self.assertNotIn(name, plan["report"]["estimated_positions"])
        self.assertEqual(plan["report"]["layout_adjustments"], [])

    def test_task_list_falls_back_to_area_bbox(self):
        art = copy.deepcopy(ART_RAW); del art["feature"]["parts"]["task_list"]
        plan = mod.plan_prefab(MISSIONS, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertTrue(_node(plan, "MissionList")["placed"])
        self.assertNotIn("MissionList", plan["report"]["mission_geometry"]["defaulted"])
        del art["feature"]["area_bbox"]
        plan = mod.plan_prefab(MISSIONS, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertIn("MissionList", plan["report"]["mission_geometry"]["defaulted"])

    def test_missing_row_defaults_every_card_part(self):
        art = copy.deepcopy(ART_RAW); del art["feature"]["parts"]["row"]
        layout = mod.layout_from_artifact(art)
        self.assertEqual(layout["feature_row_parts"], {})
        self.assertTrue(any("row_parts" in w for w in layout["warnings"]))
        plan = mod.plan_prefab(MISSIONS, layout, STYLE, {})["plan"]
        defaulted = plan["report"]["mission_geometry"]["defaulted"]
        self.assertEqual(sorted(defaulted), sorted(["MissionRow", "MissionRowPlacement", "MissionRowTitle", "MissionRowSubMission",
                                                    "MissionRowStatus", "MissionRowProgress", "MissionRowProgressText",
                                                    "MissionRowRewards", "MissionRowAction", "MissionRowDismiss"]))
        self.assertEqual(_node(plan, "MissionRow")["size"], [900.0, 180.0])

    def test_unknown_and_malformed_feature_blocks_only_warn(self):
        art = copy.deepcopy(ART_RAW)
        art["feature"]["parts"]["banner"] = {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}
        art["feature"]["style"]["glow"] = "#FFFFFF"
        art["feature"]["row_parts"] = ["not", "an", "object"]
        layout = mod.layout_from_artifact(art)
        self.assertNotIn("banner", layout["feature_parts"])
        self.assertNotIn("glow", layout["feature_style"])
        self.assertEqual(layout["feature_row_parts"], {})
        for needle in ("parts.banner", "style.glow", "row_parts"):
            self.assertTrue(any(needle in w for w in layout["warnings"]), needle)

    def test_feature_blocks_ignored_when_feature_types_disagree(self):
        art = copy.deepcopy(ART_RAW); art["feature"]["type"] = "milestone"
        plan = mod.plan_prefab(MISSIONS, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertEqual(plan["report"]["mission_geometry"]["source"], "defaults")
        self.assertIsNone(_node(plan, "MissionRow")["color"])

    def test_bar_less_template_has_no_bar_geometry(self):
        t = copy.deepcopy(MISSIONS); t["features"]["mission"]["progressBar"] = {"display": "dont_show_at_all"}
        plan = mod.plan_prefab(t, ART, STYLE, {})["plan"]
        self.assertNotIn("MissionBarScroll", [n["name"] for n in plan["nodes"]])
        self.assertNotIn("MissionBarScroll", plan["report"]["mission_geometry"]["defaulted"])

    def test_new_names_are_reserved(self):
        for name in ("MissionTabs", "MissionTab", "MissionViewport", "MissionRows", "MissionRowTitle",
                     "MissionBarScroll", "MissionBarViewport", "MissionBarContent", "MissionBarStep"):
            self.assertIn(name, mod.MISSION_RESERVED_NODE_NAMES)
        for name in ("MissionList", "MissionRow", "MissionBar", "MissionBarFill"):   # the release's names: global
            self.assertIn(name, mod.RESERVED_NODE_NAMES)
        for fld in ("missionTabsRoot", "missionTabTemplate", "missionScroll", "missionRowsRoot",
                    "missionBarScroll", "missionBarContent", "missionBarStepTemplate"):
            self.assertIn(fld, mod.MISSION_RESERVED_FIELDS)
        for fld in ("missionListRoot", "missionRowTemplate", "missionBarRoot", "missionBarFill"):
            self.assertIn(fld, mod.RESERVED_FIELDS)


class TestMissionOnlyReservedNames(unittest.TestCase):
    """The names the missions UI adds are reserved on mission templates only: a standard or milestone template
       keeps exactly the names the milestone base (6d5deb8) gave its slots."""

    # RESERVED_* exactly as shipped by the milestone base
    BASE_NODE_NAMES = {"Dimmer", "Frame", "Panel", "Unplaced", "TimerZone", "TimerText", "PriceBeforeSaleZone",
                       "PriceBeforeSaleText", "PriceBeforeSaleStrike", "ResourceArea", "ResourceItem",
                       "GrandPrizeArea", "GrandPrizeImage", "GrandPrizeText", "MilestoneMainButton",
                       "MilestoneMainButtonLabel", "MilestoneScroll", "MilestoneViewport", "MilestoneContent",
                       "MilestoneStep", "MissionList", "MissionRow", "MissionBar", "MissionBarFill"}
    BASE_FIELDS = {"dimmer", "panel", "timerRoot", "timerText", "priceBeforeSaleRoot", "priceBeforeSaleText",
                   "resourceAreaRoot", "resourceItemTemplate", "grandPrizeRoot", "grandPrizeImage", "grandPrizeText",
                   "milestoneMainButton", "milestoneMainButtonLabel", "missionListRoot", "missionRowTemplate",
                   "missionBarRoot", "missionBarFill", "milestoneScroll", "milestoneContent", "milestoneStepTemplate"}

    def test_global_sets_are_the_bases(self):
        self.assertEqual(mod.RESERVED_NODE_NAMES, self.BASE_NODE_NAMES)
        self.assertEqual(mod.RESERVED_FIELDS, self.BASE_FIELDS)
        self.assertFalse(mod.MISSION_RESERVED_NODE_NAMES & mod.RESERVED_NODE_NAMES)
        self.assertFalse(mod.MISSION_RESERVED_FIELDS & mod.RESERVED_FIELDS)
        mission = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        added = {n["name"] for n in mission["nodes"] if n["name"].startswith("Mission")} - mod.RESERVED_NODE_NAMES
        self.assertEqual(added, mod.MISSION_RESERVED_NODE_NAMES)   # every name the missions UI adds is reserved for it
        fields = {n["field"] for n in mission["nodes"] if (n["field"] or "").startswith("mission")} - mod.RESERVED_FIELDS
        self.assertEqual(fields, mod.MISSION_RESERVED_FIELDS)

    def _with_slot(self, template, key):
        t = copy.deepcopy(template)
        t["texts"].append({"key": key, "name": key, "index": 30, "canBeHidden": True, "customFields": []})
        return t

    def test_standard_and_milestone_slots_keep_their_names(self):
        for template in (TEMPLATE, _milestone_template()):
            plan = mod.plan_prefab(self._with_slot(template, "mission_tabs"), None, STYLE, {})["plan"]
            node = next(n for n in plan["nodes"] if n.get("key") == "mission_tabs")
            self.assertEqual((node["name"], node["field"]), ("MissionTabsText", "missionTabsText"))
            self.assertFalse(any("mission_tabs" in w and "renamed" in w for w in plan["report"]["warnings"]))

    def test_the_reservation_is_gated_by_feature_type(self):
        # slot names always end in Image / Text / Button, so no real key reaches a mission name today: prove the
        # gate itself by reserving a slot-shaped name for missions for the duration of the test
        saved = (set(mod.MISSION_RESERVED_NODE_NAMES), set(mod.MISSION_RESERVED_FIELDS))
        mod.MISSION_RESERVED_NODE_NAMES.add("MissionTabsText")
        mod.MISSION_RESERVED_FIELDS.add("missionTabsText")
        try:
            standard = mod.plan_prefab(self._with_slot(TEMPLATE, "mission_tabs"), None, STYLE, {})["plan"]
            milestone = mod.plan_prefab(self._with_slot(_milestone_template(), "mission_tabs"), None, STYLE, {})["plan"]
            mission = mod.plan_prefab(self._with_slot(MISSIONS, "mission_tabs"), None, STYLE, {})["plan"]
        finally:
            mod.MISSION_RESERVED_NODE_NAMES.clear(); mod.MISSION_RESERVED_NODE_NAMES.update(saved[0])
            mod.MISSION_RESERVED_FIELDS.clear(); mod.MISSION_RESERVED_FIELDS.update(saved[1])
        name = lambda plan: next(n["name"] for n in plan["nodes"] if n.get("key") == "mission_tabs")
        self.assertEqual(name(standard), "MissionTabsText")
        self.assertEqual(name(milestone), "MissionTabsText")
        self.assertEqual(name(mission), "MissionTabsText2")


class TestMissionLadderNodes(unittest.TestCase):
    """Rule 2: the mission ProgressBarState is planned as the milestone ladder (the same scroll chain + step template)."""

    def test_ladder_chain_and_step(self):
        plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        rows = [(n["name"], n["parent"], n["binding"], n["components"], n["field"], n["field_type"])
                for n in plan["nodes"] if n["name"].startswith("MissionBar")]
        self.assertEqual(rows, [
            ("MissionBarScroll", "Panel", "scroll", ["ScrollRect"], "missionBarScroll", "ScrollRect"),
            ("MissionBarViewport", "MissionBarScroll", "viewport", ["Image", "RectMask2D"], None, None),
            ("MissionBarContent", "MissionBarViewport", "scroll_content", ["HorizontalLayoutGroup", "ContentSizeFitter"],
             "missionBarContent", "RectTransform"),
            ("MissionBarStep", "MissionBarContent", "milestone_step", [], "missionBarStepTemplate", "KinoaInAppMilestoneStepView")])
        step = _node(plan, "MissionBarStep")
        self.assertTrue(step["step_button"])    # every step claims through its own button (the milestone per_step look)
        self.assertTrue(step["inactive"])
        scroll = _node(plan, "MissionBarScroll")
        self.assertIsNone(scroll["scroll_axis"])   # horizontal, like the milestone ladder
        self.assertEqual(step["size"], mod._step_size(plan, plan["report"]["panel_bbox"], scroll["anchor_min"], scroll["anchor_max"]))

    def test_ladder_matches_the_milestone_ladder_shape(self):
        milestone = mod.plan_prefab(_milestone_template(buttons=["close_button"]), None, STYLE, {})["plan"]
        mission = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        shape = lambda plan, prefix: [(n["binding"], n["components"], n["field_type"], n["step_button"])
                                      for n in plan["nodes"] if n["name"] in tuple(prefix + s for s in ("Scroll", "Viewport", "Content", "Step"))]
        self.assertEqual(shape(mission, "MissionBar"), shape(milestone, "Milestone"))

    def test_progress_bar_part_places_the_ladder(self):
        plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        scroll = _node(plan, "MissionBarScroll")
        self.assertTrue(scroll["placed"])
        amin, amax = mod.anchors_from_bbox(ART_RAW["feature"]["parts"]["progress_bar"], plan["report"]["panel_bbox"])
        close = lambda a, b: all(abs(x - y) < 1e-3 for x, y in zip(a, b))
        self.assertTrue(close(scroll["anchor_min"] + scroll["anchor_max"], amin + amax))
        self.assertFalse(any("ladder steps need" in w for w in plan["report"]["warnings"]))

    def test_thin_progress_bar_is_reported(self):
        art = copy.deepcopy(ART_RAW)
        art["feature"]["parts"]["progress_bar"] = {"x": 0.1, "y": 0.76, "w": 0.8, "h": 0.02}   # the bar line alone
        plan = mod.plan_prefab(MISSIONS, mod.layout_from_artifact(art), STYLE, {})["plan"]
        self.assertTrue(any("MissionBarScroll" in w and "ladder steps need" in w for w in plan["report"]["warnings"]))

    def test_default_ladder_band_fits_a_step(self):
        plan = mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]
        self.assertIn("MissionBarScroll", plan["report"]["estimated_positions"])
        self.assertFalse(any("ladder steps need" in w for w in plan["report"]["warnings"]))

    def test_ladder_is_a_container_and_never_split(self):
        self.assertIn("MissionBarScroll", mod._CONTAINERS)
        plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
        self.assertEqual([a for a in plan["report"]["layout_adjustments"] if a["node"].startswith("MissionBar")], [])
