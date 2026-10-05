"""Offline tests for the in-app template builder.

No network, no credentials — the helper is a pure function of its input.
The One CTA case is the load-bearing one: it is reconstructed from Kinoa's
real production template, so a regression there means the builder stopped
matching reality.
"""

import copy
import importlib.util
import json
import os
import sys
import unittest

_HELPER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugin",
    "skills",
    "kinoa-inapp-template-from-image",
    "inapp_template_build.py",
)
_spec = importlib.util.spec_from_file_location("inapp_template_build", _HELPER)
build_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_mod)


def analysis(elements, feature=None, template=None):
    return {
        "schema_version": "1.0",
        "template": template or {"suggested_name": "T", "suggested_key": "t"},
        "feature": feature or {"type": "standard"},
        "elements": elements,
    }


ONE_CTA = analysis(
    [
        {"role": "background_image", "bbox": {"x": 0.2, "y": 0.06, "w": 0.57, "h": 0.7}},
        {"role": "close_button", "bbox": {"x": 0.72, "y": 0.04, "w": 0.09, "h": 0.07}, "observed_text": "X"},
        {"role": "header", "bbox": {"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05}, "observed_text": "HEADER"},
        {"role": "upper_text", "bbox": {"x": 0.33, "y": 0.18, "w": 0.31, "h": 0.04}},
        {"role": "resource_badge", "bbox": {"x": 0.22, "y": 0.46, "w": 0.16, "h": 0.11}},
        {"role": "resource_area", "bbox": {"x": 0.25, "y": 0.50, "w": 0.48, "h": 0.13}},
        {"role": "price_before_sale", "bbox": {"x": 0.33, "y": 0.66, "w": 0.31, "h": 0.04}},
        {"role": "cta_button", "bbox": {"x": 0.34, "y": 0.72, "w": 0.29, "h": 0.07}, "observed_text": "CTA"},
        {"role": "price_cut_badge", "bbox": {"x": 0.65, "y": 0.73, "w": 0.19, "h": 0.06}},
        {"role": "timer", "bbox": {"x": 0.40, "y": 0.82, "w": 0.19, "h": 0.03}},
        {"role": "fine_print", "bbox": {"x": 0.20, "y": 0.86, "w": 0.57, "h": 0.04}},
    ]
)


class TestOneCTAReconstruction(unittest.TestCase):
    """The builder must reproduce Kinoa's real One CTA template inventory."""

    def setUp(self):
        self.payload, self.report = build_mod.build_payload(copy.deepcopy(ONE_CTA))

    def test_bucket_membership_matches_production(self):
        self.assertEqual([i["key"] for i in self.payload["images"]], ["background_image"])
        self.assertEqual(
            sorted(b["key"] for b in self.payload["buttons"]), ["close_button", "cta_button"]
        )
        self.assertEqual(
            sorted(t["key"] for t in self.payload["texts"]),
            ["fine_print", "header", "price_cut_badge", "resource_badge", "upper_text"],
        )

    def test_cta_offers_the_production_action_set(self):
        cta = next(b for b in self.payload["buttons"] if b["key"] == "cta_button")
        self.assertEqual(
            cta["clickActionType"],
            ["close", "show_ad", "billing", "collect_resource", "deep_link", "soft_billing"],
        )

    def test_client_rendered_zones_are_reported_not_emitted(self):
        emitted = {i["key"] for b in build_mod.BUCKETS for i in self.payload[b]}
        self.assertNotIn("resource_area", emitted)
        self.assertNotIn("timer", emitted)
        self.assertNotIn("price_before_sale", emitted)
        self.assertEqual(
            sorted(c["role"] for c in self.report["client_rendered"]),
            ["price_before_sale", "resource_area", "timer"],
        )

    def test_payload_validates(self):
        self.assertTrue(build_mod.validate_payload(self.payload)["ok"])


class TestIndexing(unittest.TestCase):
    def test_indexes_are_dense_and_unique_across_buckets(self):
        payload, report = build_mod.build_payload(copy.deepcopy(ONE_CTA))
        indexes = sorted(i["index"] for b in build_mod.BUCKETS for i in payload[b])
        self.assertEqual(indexes, list(range(report["element_count"])))

    def test_reading_order_drives_index(self):
        payload, _ = build_mod.build_payload(
            analysis(
                [
                    {"role": "fine_print", "bbox": {"x": 0.1, "y": 0.9, "w": 0.8, "h": 0.05}},
                    {"role": "header", "bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.05}},
                ]
            )
        )
        by_key = {t["key"]: t["index"] for t in payload["texts"]}
        self.assertLess(by_key["header"], by_key["fine_print"])

    def test_elements_without_bbox_sort_last_but_are_kept(self):
        payload, report = build_mod.build_payload(
            analysis(
                [
                    {"role": "toggle_custom", "suggested_key": "show_area"},
                    {"role": "header", "bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.05}},
                ]
            )
        )
        self.assertEqual(report["element_count"], 2)
        self.assertEqual(payload["texts"][0]["index"], 0)
        self.assertEqual(payload["customs"][0]["index"], 1)


class TestKeys(unittest.TestCase):
    def test_duplicate_roles_get_unique_keys(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "product_image"}, {"role": "product_image"}, {"role": "product_image"}])
        )
        self.assertEqual([i["key"] for i in payload["images"]], ["product_image", "product_image_2", "product_image_3"])

    def test_keys_are_slugified(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header", "suggested_key": "Main Header!! 2"}])
        )
        self.assertEqual(payload["texts"][0]["key"], "main_header_2")
        self.assertRegex(payload["texts"][0]["key"], build_mod.KEY_RE)

    def test_template_key_is_repaired_when_invalid(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "header"}], template={"suggested_name": "X", "suggested_key": "9 bad key"})
        )
        self.assertEqual(payload["key"], "template_9_bad_key")
        self.assertTrue(any("not a valid identifier" in w for w in report["warnings"]))


class TestClickActionInference(unittest.TestCase):
    def infer(self, text, role="cta_button"):
        payload, _ = build_mod.build_payload(analysis([{"role": role, "observed_text": text}]))
        return payload["buttons"][0]["clickActionType"]

    def test_wording_wins_over_role_default(self):
        self.assertEqual(self.infer("WATCH AD"), ["show_ad"])
        self.assertEqual(self.infer("Collect now"), ["collect_resource"])
        self.assertEqual(self.infer("Update"), ["update_app_version"])

    def test_hard_currency_means_billing(self):
        self.assertEqual(self.infer("Buy $4.99"), ["billing"])

    def test_buy_without_a_currency_mark_is_soft_billing(self):
        self.assertEqual(self.infer("Buy for 500"), ["soft_billing"])

    def test_explicit_actions_override_everything(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "cta_button", "observed_text": "WATCH AD", "click_action_types": ["billing"]}])
        )
        self.assertEqual(payload["buttons"][0]["clickActionType"], ["billing"])

    def test_invalid_explicit_actions_fall_back_to_inference(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "close_button", "click_action_types": ["teleport"]}])
        )
        self.assertEqual(payload["buttons"][0]["clickActionType"], ["close"])

    def test_item_bearing_actions_get_required_items_count(self):
        payload, _ = build_mod.build_payload(analysis([{"role": "collect_button", "observed_text": "Claim"}]))
        self.assertEqual(payload["buttons"][0]["requiredItemsCount"], 1)

    def test_plain_buttons_have_no_required_items_count(self):
        payload, _ = build_mod.build_payload(analysis([{"role": "close_button"}]))
        self.assertNotIn("requiredItemsCount", payload["buttons"][0])


class TestElementDefaults(unittest.TestCase):
    def test_texts_carry_a_text_colour_knob(self):
        payload, _ = build_mod.build_payload(analysis([{"role": "header"}]))
        fields = {f["key"]: f for f in payload["texts"][0]["customFields"]}
        self.assertEqual(fields["text_color"]["defaultValue"], "#FFFFFF")
        self.assertEqual(fields["text_color"]["kind"], "string")

    def test_resource_badge_also_carries_a_badge_colour(self):
        payload, _ = build_mod.build_payload(analysis([{"role": "resource_badge"}]))
        keys = {f["key"] for f in payload["texts"][0]["customFields"]}
        self.assertEqual(keys, {"text_color", "badge_color"})

    def test_supplied_custom_field_is_not_duplicated(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header", "custom_fields": [{"key": "text_color", "kind": "string", "defaultValue": "#000"}]}])
        )
        fields = payload["texts"][0]["customFields"]
        self.assertEqual([f["key"] for f in fields], ["text_color"])
        self.assertEqual(fields[0]["defaultValue"], "#000")

    def test_cta_cannot_be_hidden_but_background_can(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "cta_button"}, {"role": "background_image"}])
        )
        self.assertFalse(payload["buttons"][0]["canBeHidden"])
        self.assertTrue(payload["images"][0]["canBeHidden"])

    def test_enumeration_custom_gets_enum_values(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "variant_custom", "kind": "enumeration", "enum_values": "a,b,c"}])
        )
        self.assertEqual(payload["customs"][0]["enumValues"], "a,b,c")


class TestFeatures(unittest.TestCase):
    def test_standard_has_empty_features_and_tags(self):
        # The observed create contract sends {} for standard (older GET records
        # return null; the validator accepts both).
        payload, _ = build_mod.build_payload(analysis([{"role": "header"}]))
        self.assertEqual(payload["featureType"], "standard")
        self.assertEqual(payload["features"], {})
        self.assertEqual(payload["tagsIds"], [])
        legacy = dict(payload, features=None)
        self.assertTrue(build_mod.validate_payload(legacy)["ok"])

    def test_milestone_limit_follows_detected_marker_count(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "milestone", "detected": {"milestone_count": 5}})
        )
        self.assertEqual(payload["features"]["milestone"]["limit"], 5)
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_mission_counts_follow_detection(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "mission", "detected": {"mission_count": 4, "set_count": 2}})
        )
        mission = payload["features"]["mission"]
        self.assertEqual(mission["maxPlacements"], 4)
        self.assertEqual(mission["maxSetsCount"], 2)
        self.assertEqual(mission["minPlacements"], 1)

    def test_unknown_feature_type_falls_back_with_a_warning(self):
        payload, report = build_mod.build_payload(analysis([{"role": "header"}], feature={"type": "raid"}))
        self.assertEqual(payload["featureType"], "standard")
        self.assertTrue(any("raid" in w for w in report["warnings"]))


class TestUnmapped(unittest.TestCase):
    def test_unknown_role_is_reported_not_dropped(self):
        payload, report = build_mod.build_payload(analysis([{"role": "spinning_wheel", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}]))
        self.assertEqual(report["element_count"], 0)
        self.assertEqual(len(report["unmapped"]), 1)
        self.assertEqual(report["unmapped"][0]["role"], "spinning_wheel")

    def test_low_confidence_is_warned_about(self):
        _, report = build_mod.build_payload(analysis([{"role": "header", "confidence": 0.2}]))
        self.assertTrue(any("low detection confidence" in w for w in report["warnings"]))

    def test_missing_button_is_warned_about(self):
        _, report = build_mod.build_payload(analysis([{"role": "header"}]))
        self.assertTrue(any("no buttons detected" in w for w in report["warnings"]))


class TestStruckPriceAmbiguity(unittest.TestCase):
    """A struck-through price is either an operator-typed soft-billing element
    or a client-rendered zone, and the image cannot tell you which."""

    def test_soft_billing_old_price_is_flagged_for_confirmation(self):
        payload, report = build_mod.build_payload(analysis([{"role": "soft_billing_old_price"}]))
        self.assertEqual([t["key"] for t in payload["texts"]], ["soft_billing_old_price"])
        self.assertEqual(len(report["needs_confirmation"]), 1)
        self.assertEqual(report["needs_confirmation"][0]["key"], "soft_billing_old_price")

    def test_price_before_sale_stays_client_rendered(self):
        payload, report = build_mod.build_payload(analysis([{"role": "price_before_sale"}]))
        self.assertEqual(payload["texts"], [])
        self.assertEqual([c["role"] for c in report["client_rendered"]], ["price_before_sale"])

    def test_unambiguous_roles_are_not_flagged(self):
        _, report = build_mod.build_payload(copy.deepcopy(ONE_CTA))
        self.assertEqual(report["needs_confirmation"], [])


class TestCorpusDrivenRoles(unittest.TestCase):
    """Roles added after the shipped-game corpus runs."""

    def test_info_button_maps_to_the_custom_action(self):
        payload, report = build_mod.build_payload(analysis([{"role": "info_button", "observed_text": "i"}]))
        button = payload["buttons"][0]
        self.assertEqual(button["clickActionType"], ["custom", "close"])
        self.assertEqual(button["customCtaNames"], ["Info"])
        # The custom action expresses it natively — no developer confirmation needed.
        self.assertEqual(report["needs_confirmation"], [])
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_custom_action_without_cta_names_fails_validation(self):
        payload, _ = build_mod.build_payload(analysis([{"role": "info_button"}]))
        payload["buttons"][0].pop("customCtaNames")
        result = build_mod.validate_payload(payload)
        self.assertFalse(result["ok"])
        self.assertTrue(any("customCtaNames" in e for e in result["errors"]))

    def test_explicit_custom_cta_names_win_over_the_role_default(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "info_button", "custom_cta_names": ["Rules", "Preview"]}])
        )
        self.assertEqual(payload["buttons"][0]["customCtaNames"], ["Rules", "Preview"])

    def test_image_kind_is_valid_on_custom_fields_but_not_elements(self):
        payload, _ = build_mod.build_payload(
            analysis(
                [
                    {"role": "cta_button", "observed_text": "Buy $1",
                     "custom_fields": [{"key": "btn_art", "kind": "image", "defaultValue": "x"}]},
                    {"role": "variant_custom", "kind": "image"},
                ]
            )
        )
        self.assertEqual(payload["buttons"][0]["customFields"][0]["kind"], "image")
        # custom ELEMENTS are constrained to KINDS — image falls back to string
        self.assertEqual(payload["customs"][0]["kind"], "string")
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_value_badge_is_a_text_with_badge_colour(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "value_badge", "observed_text": "240% VALUE"}])
        )
        self.assertEqual(payload["texts"][0]["key"], "value_badge")
        keys = {f["key"] for f in payload["texts"][0]["customFields"]}
        self.assertEqual(keys, {"text_color", "badge_color"})
        self.assertEqual(report["needs_confirmation"], [])


class TestDescriptionLimit(unittest.TestCase):
    """The server 422s a create whose template description exceeds 50 chars."""

    def test_long_description_is_truncated_with_a_warning(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "header"}], template={"suggested_key": "k", "description": "x" * 80})
        )
        self.assertLessEqual(len(payload["description"]), build_mod.TEMPLATE_DESCRIPTION_MAX)
        self.assertTrue(any("truncated" in w for w in report["warnings"]))
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_validator_rejects_an_overlong_description(self):
        payload, _ = build_mod.build_payload(analysis([{"role": "header"}]))
        payload["description"] = "y" * 51
        self.assertFalse(build_mod.validate_payload(payload)["ok"])

    def test_element_descriptions_are_not_capped(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header", "notes": "z" * 90}])
        )
        self.assertEqual(len(payload["texts"][0]["description"]), 90)
        self.assertTrue(build_mod.validate_payload(payload)["ok"])


class TestMockupDerivedCtaMenus(unittest.TestCase):
    """Operator decision: CTA menus ship only when read off the mockup; the
    API-required mission completionCta falls back to ['close'] with a warning."""

    def test_milestone_menus_omitted_when_not_derived(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "milestone", "detected": {"milestone_count": 5}})
        )
        ms = payload["features"]["milestone"]
        self.assertNotIn("mainActionTypes", ms)
        self.assertNotIn("milestonesActionTypes", ms)
        self.assertEqual(sum("not derivable from the mockup" in w for w in report["warnings"]), 2)
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_milestone_menus_present_when_derived(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "milestone", "detected": {
                "milestone_count": 5, "main_actions": ["billing", "close"],
                "milestone_actions": ["collect_resource"]}})
        )
        ms = payload["features"]["milestone"]
        self.assertEqual(ms["mainActionTypes"], ["billing", "close"])
        self.assertEqual(ms["milestonesActionTypes"], ["collect_resource"])
        self.assertFalse(any("not derivable" in w for w in report["warnings"]))

    def test_mission_completion_falls_back_to_close_with_warning(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "mission", "detected": {"mission_count": 3}})
        )
        self.assertEqual(payload["features"]["mission"]["completionCta"], ["close"])
        self.assertTrue(any("completionCta not derivable" in w for w in report["warnings"]))

    def test_mission_completion_derived_from_mockup(self):
        payload, report = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "mission", "detected": {
                "mission_count": 3, "completion_actions": ["collect_resource", "billing"]}})
        )
        self.assertEqual(payload["features"]["mission"]["completionCta"], ["collect_resource", "billing"])
        self.assertFalse(any("completionCta not derivable" in w for w in report["warnings"]))

    def test_unknown_actions_are_filtered(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "mission", "detected": {
                "completion_actions": ["collect_resource", "teleport"]}})
        )
        self.assertEqual(payload["features"]["mission"]["completionCta"], ["collect_resource"])

    def test_no_fallback_flag_leaks_into_payload(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header"}], feature={"type": "mission"})
        )
        self.assertNotIn("_completion_fallback", payload["features"]["mission"])


class TestUnsupportedMechanics(unittest.TestCase):
    """Real offers out-run the template model. The portable part must still
    build, and what did not fit must survive into the report."""

    def with_unsupported(self, items):
        a = analysis([{"role": "header"}, {"role": "cta_button", "observed_text": "Buy $9.99"}])
        a["unsupported"] = items
        return build_mod.build_payload(a)

    def test_unsupported_entries_are_carried_into_the_report(self):
        payload, report = self.with_unsupported(
            [
                {"what": "serpentine chain of 6 visible deals", "why": "no sequencing in the model"},
                {"what": "hidden total deal count", "why": "no per-deal state"},
            ]
        )
        self.assertEqual(len(report["unsupported"]), 2)
        self.assertEqual(report["unsupported"][0]["what"], "serpentine chain of 6 visible deals")

    def test_the_portable_remainder_still_builds_and_validates(self):
        payload, _ = self.with_unsupported([{"what": "minigame", "why": "not expressible"}])
        self.assertEqual(len(payload["texts"]), 1)
        self.assertEqual(len(payload["buttons"]), 1)
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_unsupported_never_reaches_the_payload(self):
        payload, _ = self.with_unsupported([{"what": "shop grid", "why": "not expressible"}])
        self.assertNotIn("unsupported", payload)

    def test_malformed_unsupported_entries_are_ignored(self):
        _, report = self.with_unsupported([{"why": "no what key"}, "a bare string", {"what": "kept"}])
        self.assertEqual([u["what"] for u in report["unsupported"]], ["kept"])

    def test_absent_unsupported_yields_an_empty_list(self):
        _, report = build_mod.build_payload(copy.deepcopy(ONE_CTA))
        self.assertEqual(report["unsupported"], [])


class TestCustomFieldValidation(unittest.TestCase):
    """Custom FIELDS (attached to elements) vs custom ELEMENTS are distinct:
    fields allow kind image and must have unique keys within their element."""

    def test_duplicate_field_key_within_one_element_is_an_error(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header", "custom_fields": [
                {"key": "c", "kind": "string"}, {"key": "c", "kind": "boolean"}]}])
        )
        # builder de-duplicates on build; force the duplicate to test the validator
        payload["texts"][0]["customFields"][1]["key"] = payload["texts"][0]["customFields"][0]["key"]
        result = build_mod.validate_payload(payload)
        self.assertFalse(result["ok"])
        self.assertTrue(any("duplicate custom field key" in e for e in result["errors"]))

    def test_same_field_key_on_two_elements_is_fine(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header"}, {"role": "upper_text"}])
        )
        # both carry text_color — legal per the observed contract
        self.assertTrue(build_mod.validate_payload(payload)["ok"])

    def test_enumeration_field_without_values_warns(self):
        payload, _ = build_mod.build_payload(
            analysis([{"role": "header", "custom_fields": [{"key": "e", "kind": "enumeration"}]}])
        )
        result = build_mod.validate_payload(payload)
        self.assertTrue(result["ok"])
        self.assertTrue(any("without enumValues" in w for w in result["warnings"]))


class TestValidation(unittest.TestCase):
    def base(self):
        payload, _ = build_mod.build_payload(copy.deepcopy(ONE_CTA))
        return payload

    def test_duplicate_index_is_an_error(self):
        payload = self.base()
        payload["texts"][0]["index"] = payload["texts"][1]["index"]
        result = build_mod.validate_payload(payload)
        self.assertFalse(result["ok"])
        self.assertTrue(any("used twice" in e for e in result["errors"]))

    def test_duplicate_key_within_a_bucket_is_an_error(self):
        payload = self.base()
        payload["texts"][1]["key"] = payload["texts"][0]["key"]
        self.assertFalse(build_mod.validate_payload(payload)["ok"])

    def test_bad_key_pattern_is_an_error(self):
        payload = self.base()
        payload["texts"][0]["key"] = "Not A Key"
        self.assertFalse(build_mod.validate_payload(payload)["ok"])

    def test_unknown_click_action_is_an_error(self):
        payload = self.base()
        payload["buttons"][0]["clickActionType"] = ["self_destruct"]
        self.assertFalse(build_mod.validate_payload(payload)["ok"])

    def test_button_without_actions_is_an_error(self):
        payload = self.base()
        payload["buttons"][0]["clickActionType"] = []
        self.assertFalse(build_mod.validate_payload(payload)["ok"])

    def test_standard_with_a_feature_block_is_an_error(self):
        payload = self.base()
        payload["features"] = {"mission": {}}
        self.assertFalse(build_mod.validate_payload(payload)["ok"])

    def test_feature_type_without_its_block_is_an_error(self):
        payload = self.base()
        payload["featureType"] = "milestone"
        self.assertFalse(build_mod.validate_payload(payload)["ok"])


class TestCLI(unittest.TestCase):
    def run_cli(self, argv):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = build_mod.main(argv)
        return code, json.loads(buf.getvalue())

    def test_roles_lists_every_bucket_and_the_client_rendered_set(self):
        code, out = self.run_cli(["roles"])
        self.assertEqual(code, 0)
        self.assertEqual(set(out["roles_by_bucket"]), set(build_mod.BUCKETS))
        self.assertIn("resource_area", out["client_rendered_roles"])
        self.assertEqual(out["click_action_types"], list(build_mod.CLICK_ACTIONS))

    def test_schema_is_printable(self):
        code, out = self.run_cli(["schema"])
        self.assertEqual(code, 0)
        self.assertIn("elements", out["shape"])

    def test_build_from_stdin_round_trips(self):
        import io
        from contextlib import redirect_stdout

        stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(ONE_CTA))
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = build_mod.main(["build", "--analysis", "-", "--game-id", "abc"])
            out = json.loads(buf.getvalue())
        finally:
            sys.stdin = stdin
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["payload"]["gameId"], "abc")

    def test_an_empty_milestone_analysis_still_builds_a_valid_payload(self):
        """No elements at all is a poor template, but it must not be malformed —
        the builder still emits the milestone feature block it promised."""
        import io
        from contextlib import redirect_stdout

        stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(analysis([], feature={"type": "milestone"}, template={"suggested_key": "k"})))
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = build_mod.main(["build", "--analysis", "-"])
            out = json.loads(buf.getvalue())
        finally:
            sys.stdin = stdin
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertIn("milestone", out["payload"]["features"])
        self.assertTrue(any("no buttons detected" in w for w in out["report"]["warnings"]))


# --------------------------------------------------------------------------
# match — reuse an existing template instead of minting a new one
# --------------------------------------------------------------------------


def image_slot(key, **over):
    slot = {
        "key": key,
        "name": key.replace("_", " ").title(),
        "index": 0,
        "description": "",
        "canBeHidden": True,
        "customFields": [],
        "size": {"width": 10000, "height": 10000, "maxSize": 16000},
    }
    slot.update(over)
    return slot


def button_slot(key, actions, **over):
    slot = {
        "key": key,
        "name": key.replace("_", " ").title(),
        "index": 0,
        "description": "",
        "canBeHidden": True,
        "customFields": [],
        "textLimit": 255,
        "backgroundImg": {"width": 10000, "height": 10000, "maxSize": 10000},
        "clickActionType": list(actions),
    }
    slot.update(over)
    return slot


def text_slot(key, **over):
    slot = {
        "key": key,
        "name": key.replace("_", " ").title(),
        "index": 0,
        "description": "",
        "canBeHidden": True,
        "customFields": [{"key": "text_color", "kind": "string", "name": "Text color",
                          "nullable": False, "description": "", "defaultValue": "#FFFFFF"}],
        "nullable": True,
        "textLimit": 255,
    }
    slot.update(over)
    return slot


def custom_slot(key, kind, **over):
    slot = {
        "key": key,
        "kind": kind,
        "name": key.replace("_", " ").title(),
        "index": 0,
        "description": "",
        "canBeHidden": True,
        "customFields": [],
        "nullable": True,
        "defaultValue": "",
    }
    slot.update(over)
    return slot


def template_record(key="tpl", images=None, buttons=None, texts=None, customs=None, **over):
    record = {
        "id": "id-" + key,
        "name": key,
        "key": key,
        "description": "",
        "status": "active",
        "featureType": "standard",
        "features": {},
        "images": images or [],
        "buttons": buttons or [],
        "texts": texts or [],
        "customs": customs or [],
    }
    record.update(over)
    return record


# Kinoa's boxed single-CTA template, reconstructed from the real record: the
# close button offers only `close`, the CTA offers the full six-action menu and
# cannot be hidden, and a boolean custom toggles the resource area.
ONE_CTA_TEMPLATE = template_record(
    key="one_cta_predefined",
    name="One CTA Template",
    images=[image_slot("background_image")],
    buttons=[
        button_slot("close_the_x_button", ["close"], textLimit=100),
        button_slot(
            "cta",
            ["close", "show_ad", "billing", "collect_resource", "deep_link", "soft_billing"],
            canBeHidden=False,
            requiredItemsCount=1,
        ),
    ],
    texts=[
        text_slot("header", nullable=False),
        text_slot("upper_text"),
        text_slot("resource_badge"),
        text_slot("price_cut_badge"),
        text_slot("fine_print"),
    ],
    customs=[custom_slot("show_resource_area", "boolean", defaultValue=False)],
)


class TestMatchOneCTAReuse(unittest.TestCase):
    """The load-bearing reuse case: the One CTA mockup against the boxed
    one_cta_predefined template must come back 'reuse', or the skill mints a
    duplicate template for an offer the game can already configure."""

    def setUp(self):
        self.result = build_mod.match_templates(
            copy.deepcopy(ONE_CTA), [copy.deepcopy(ONE_CTA_TEMPLATE)]
        )
        self.entry = self.result["results"][0]

    def test_the_boxed_template_is_a_full_reuse(self):
        self.assertEqual(self.entry["verdict"], "reuse")
        self.assertEqual(self.entry["coverage"], 1.0)
        self.assertEqual(self.entry["missing"], [])
        self.assertEqual(self.result["best"]["template_key"], "one_cta_predefined")
        self.assertEqual(self.result["best"]["template_id"], "id-one_cta_predefined")

    def test_every_element_maps_to_its_named_slot(self):
        slots = {m["role"]: m["slot"] for m in self.entry["mapping"]}
        self.assertEqual(slots["close_button"], "close_the_x_button")
        self.assertEqual(slots["cta_button"], "cta")
        self.assertEqual(slots["background_image"], "background_image")
        self.assertEqual(slots["header"], "header")
        self.assertEqual(slots["fine_print"], "fine_print")

    def test_the_hideable_leftover_custom_is_optional_not_required(self):
        # ONE_CTA has no toggle_custom, so show_resource_area goes unused — but
        # it can be hidden, so it never blocks the reuse verdict.
        self.assertEqual(self.entry["leftover_required_slots"], [])
        self.assertEqual(self.entry["unused_optional_slots"], 1)

    def test_client_rendered_roles_never_become_needs(self):
        needs, skipped = build_mod._analysis_needs(copy.deepcopy(ONE_CTA))
        self.assertEqual(skipped, [])
        self.assertEqual(len(needs), 8)
        self.assertFalse({n["role"] for n in needs} & set(build_mod.CLIENT_RENDERED))
        self.assertEqual(self.result["needs_count"], 8)

    def test_unknown_roles_are_skipped_not_matched(self):
        result = build_mod.match_templates(
            analysis([{"role": "header"}, {"role": "spinning_wheel"}, {"role": "mini_game"}]),
            [copy.deepcopy(ONE_CTA_TEMPLATE)],
        )
        self.assertEqual(result["skipped_roles"], ["spinning_wheel", "mini_game"])
        self.assertEqual(result["needs_count"], 1)
        self.assertEqual([m["role"] for m in result["results"][0]["mapping"]], ["header"])


class TestMatchScoring(unittest.TestCase):
    def match(self, elements, templates, feature=None):
        return build_mod.match_templates(analysis(elements, feature=feature), templates)

    def one(self, elements, tpl, feature=None):
        return self.match(elements, [tpl], feature=feature)["results"][0]

    def test_feature_type_mismatch_is_a_no_in_both_directions(self):
        entry = self.one(
            [{"role": "header"}], template_record(texts=[text_slot("header")]), feature={"type": "mission"}
        )
        self.assertEqual(entry["verdict"], "no")
        self.assertIn("feature type mismatch", entry["reason"])
        self.assertIn("mission", entry["reason"])
        reverse = self.one(
            [{"role": "header"}],
            template_record(featureType="mission", texts=[text_slot("header")]),
        )
        self.assertEqual(reverse["verdict"], "no")
        self.assertIn("feature type mismatch", reverse["reason"])
        # A rejected template is never scored — no phantom coverage.
        self.assertNotIn("coverage", entry)

    def test_a_wording_inferred_action_is_a_hard_requirement(self):
        entry = self.one(
            [{"role": "cta_button", "observed_text": "WATCH AD"}],
            template_record(buttons=[button_slot("cta", ["close", "billing"])]),
        )
        self.assertEqual(
            entry["missing"],
            [{"need_index": 0, "role": "cta_button", "bucket": "buttons", "key_hint": "cta_button"}])
        self.assertEqual(entry["mapping"], [])

    def test_a_wording_inferred_action_matches_a_slot_offering_it(self):
        entry = self.one(
            [{"role": "cta_button", "observed_text": "WATCH AD"}],
            template_record(buttons=[button_slot("cta", ["show_ad", "close"])]),
        )
        self.assertEqual(
            entry["mapping"],
            [{"need_index": 0, "role": "cta_button", "bucket": "buttons",
              "key_hint": "cta_button", "slot": "cta"}])
        self.assertEqual(entry["missing"], [])

    def test_explicitly_declared_actions_must_all_be_offered(self):
        # Strictness only bites on a multi-action need: a wording-inferred need
        # carries one action, where "all of them" and "any of them" coincide.
        entry = self.one(
            [{"role": "cta_button", "click_action_types": ["show_ad", "billing"]}],
            template_record(buttons=[button_slot("cta", ["show_ad", "close"])]),
        )
        self.assertEqual(
            entry["missing"],
            [{"need_index": 0, "role": "cta_button", "bucket": "buttons", "key_hint": "cta_button"}])
        full = self.one(
            [{"role": "cta_button", "click_action_types": ["show_ad", "billing"]}],
            template_record(buttons=[button_slot("cta", ["show_ad", "billing", "close"])]),
        )
        self.assertEqual(full["mapping"][0]["slot"], "cta")

    def test_a_role_default_menu_only_needs_one_shared_action(self):
        # No wording to go on -> the six-action role default is a wish list, so
        # any slot sharing one of them will do.
        hit = self.one(
            [{"role": "cta_button"}],
            template_record(buttons=[button_slot("buy_button", ["billing"])]),
        )
        self.assertEqual(hit["mapping"][0]["slot"], "buy_button")
        miss = self.one(
            [{"role": "cta_button"}],
            template_record(buttons=[button_slot("updater", ["update_app_version"])]),
        )
        self.assertEqual(
            miss["missing"],
            [{"need_index": 0, "role": "cta_button", "bucket": "buttons", "key_hint": "cta_button"}])

    def test_a_custom_slot_must_carry_the_same_kind(self):
        wrong_kind = self.one(
            [{"role": "toggle_custom", "suggested_key": "show_area"}],
            template_record(customs=[custom_slot("show_area", "string")]),
        )
        self.assertEqual(
            wrong_kind["missing"],
            [{"need_index": 0, "role": "toggle_custom", "bucket": "customs", "key_hint": "show_area"}])
        right_kind = self.one(
            [{"role": "toggle_custom", "suggested_key": "show_area"}],
            template_record(customs=[custom_slot("show_area", "boolean")]),
        )
        self.assertEqual(right_kind["mapping"][0]["slot"], "show_area")

    def test_the_key_hint_beats_slot_order(self):
        entry = self.one(
            [{"role": "header"}],
            template_record(texts=[text_slot("upper_text"), text_slot("header")]),
        )
        self.assertEqual(entry["mapping"][0]["slot"], "header")

    def test_an_unhideable_leftover_slot_caps_a_full_cover_at_partial(self):
        entry = self.one(
            [{"role": "header"}],
            template_record(
                texts=[text_slot("header")],
                buttons=[button_slot("cta", ["billing"], canBeHidden=False)],
            ),
        )
        self.assertEqual(entry["coverage"], 1.0)
        self.assertEqual(entry["missing"], [])
        self.assertEqual(entry["leftover_required_slots"], [{"bucket": "buttons", "slot": "cta"}])
        self.assertEqual(entry["unused_optional_slots"], 0)
        self.assertEqual(entry["verdict"], "partial")

    def test_coverage_decides_between_partial_and_no(self):
        four = [{"role": "header"}, {"role": "upper_text"}, {"role": "body_text"}, {"role": "fine_print"}]
        at_threshold = self.one(four, template_record(texts=[text_slot("header"), text_slot("upper_text")]))
        self.assertEqual(at_threshold["coverage"], build_mod.MATCH_PARTIAL_THRESHOLD)
        self.assertEqual(at_threshold["verdict"], "partial")
        below = self.one(four, template_record(texts=[text_slot("header")]))
        self.assertLess(below["coverage"], build_mod.MATCH_PARTIAL_THRESHOLD)
        self.assertEqual(below["verdict"], "no")

    def test_a_summary_record_is_refused_with_a_fetch_hint(self):
        entry = self.one(
            [{"role": "header"}],
            {"id": "x", "key": "one_cta_predefined", "status": "active", "buttonsCount": 2, "textsCount": 5},
        )
        self.assertEqual(entry["verdict"], "no")
        self.assertIn("summary record", entry["reason"])
        self.assertIn("fetch the full template", entry["reason"])
        self.assertNotIn("mapping", entry)

    def test_results_are_ordered_best_first(self):
        reuse = template_record(key="reuse_me", texts=[text_slot("header")])
        partial = template_record(
            key="partial_me",
            texts=[text_slot("header")],
            buttons=[button_slot("cta", ["billing"], canBeHidden=False)],
        )
        nope = template_record(key="no_thanks", buttons=[button_slot("cta", ["billing"])])
        result = self.match([{"role": "header"}], [nope, partial, reuse])
        self.assertEqual([r["template_key"] for r in result["results"]], ["reuse_me", "partial_me", "no_thanks"])
        self.assertEqual([r["verdict"] for r in result["results"]], ["reuse", "partial", "no"])
        self.assertEqual(result["best"]["template_key"], "reuse_me")

    def test_best_is_none_when_nothing_is_reusable(self):
        result = self.match(
            [{"role": "header"}],
            [template_record(key="a"), template_record(key="b", buttons=[button_slot("cta", ["billing"])])],
        )
        self.assertIsNone(result["best"])
        self.assertEqual({r["verdict"] for r in result["results"]}, {"no"})


class TestMatchHideabilityAmbiguity(unittest.TestCase):
    """Absent canBeHidden on an unmatched slot is ambiguous in old records —
    it must be surfaced as a warning, never silently pass or veto."""

    def test_absent_can_be_hidden_is_warned_not_vetoed(self):
        tpl = {
            "key": "old_style", "id": "x", "status": "active", "featureType": "standard",
            "images": [], "customs": [],
            "texts": [{"key": "header"}],
            "buttons": [{"key": "cta", "clickActionType": ["billing"]}],  # no canBeHidden at all
        }
        result = build_mod.match_templates(analysis([{"role": "header"}]), [tpl])
        entry = result["results"][0]
        self.assertEqual(entry["verdict"], "reuse")  # not vetoed
        self.assertEqual(entry["leftover_required_slots"], [])
        self.assertEqual(entry["leftover_unknown_hideability"], [{"bucket": "buttons", "slot": "cta"}])

    def test_explicit_false_still_vetoes_reuse(self):
        tpl = {
            "key": "strict", "id": "x", "status": "active", "featureType": "standard",
            "images": [], "customs": [],
            "texts": [{"key": "header"}],
            "buttons": [{"key": "cta", "clickActionType": ["billing"], "canBeHidden": False}],
        }
        entry = build_mod.match_templates(analysis([{"role": "header"}]), [tpl])["results"][0]
        self.assertEqual(entry["verdict"], "partial")
        self.assertEqual(entry["leftover_required_slots"], [{"bucket": "buttons", "slot": "cta"}])


class TestMatchCLI(unittest.TestCase):
    def run_match(self, templates_payload, analysis_payload=None):
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            analysis_path = os.path.join(tmp, "analysis.json")
            templates_path = os.path.join(tmp, "templates.json")
            with open(analysis_path, "w", encoding="utf-8") as fh:
                json.dump(analysis_payload or ONE_CTA, fh)
            with open(templates_path, "w", encoding="utf-8") as fh:
                json.dump(templates_payload, fh)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = build_mod.main(["match", "--analysis", analysis_path, "--templates", templates_path])
            return code, json.loads(buf.getvalue())

    def test_templates_may_be_a_bare_array_or_a_list_wrapper(self):
        bare_code, bare = self.run_match([ONE_CTA_TEMPLATE])
        wrapped_code, wrapped = self.run_match({"list": [ONE_CTA_TEMPLATE], "total": 1})
        self.assertEqual((bare_code, wrapped_code), (0, 0))
        self.assertTrue(bare["ok"])
        self.assertTrue(wrapped["ok"])
        self.assertEqual(bare["results"][0]["verdict"], "reuse")
        self.assertEqual(bare["results"], wrapped["results"])

    def test_a_non_list_templates_input_is_an_error(self):
        code, out = self.run_match({"total": 0})
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertIn("must be a JSON array", out["error"])

if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------
# layout — the geometry artifact (`<template_key>.layout.json`)
# --------------------------------------------------------------------------


def _geometry_for(payload, report, sha="f" * 64):
    """Envelope-style geometry synthesized from a build result — what the
    confirmation page's geometryOut() hands back when nothing was touched."""
    src = report.get("source_image") or {}
    return {
        "source_image": {"sha256": sha, "width": src.get("width"),
                         "height": src.get("height"), "filename": "mockup.png"},
        "elements": [
            {"key": t["key"], "bucket": t["bucket"], "bbox": t["bbox"], "role": t["role"],
             "observed_text": t.get("observed_text"), "confidence": t.get("confidence")}
            for t in report["elements"]
        ],
        "client_rendered": [
            {"role": c["role"], "bbox": c.get("bbox")} for c in report["client_rendered"]
        ],
    }


class TestBuildLayout(unittest.TestCase):
    def setUp(self):
        ana = copy.deepcopy(ONE_CTA)
        ana["source_image"] = {"path": "art/mockup.png", "width": 720, "height": 960}
        self.ana = ana
        self.payload, self.report = build_mod.build_payload(ana)
        self.geometry = _geometry_for(self.payload, self.report)

    def test_elements_join_one_to_one_in_index_order(self):
        layout, rep = build_mod.build_layout(self.payload, self.geometry, self.ana)
        self.assertEqual(rep["errors"], [])
        self.assertEqual(rep["unplaced"], [])
        want = sum(len(self.payload[b]) for b in build_mod.BUCKETS)
        self.assertEqual(len(layout["elements"]), want)
        self.assertEqual([e["index"] for e in layout["elements"]], list(range(want)))
        header = next(e for e in layout["elements"] if e["key"] == "header")
        self.assertEqual(header["bucket"], "texts")
        self.assertEqual(header["bbox"], {"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05})
        self.assertEqual(header["observed_text"], "HEADER")

    def test_contract_fields(self):
        layout, _ = build_mod.build_layout(self.payload, self.geometry, self.ana)
        self.assertEqual(layout["schema_version"], build_mod.LAYOUT_SCHEMA_VERSION)
        self.assertEqual(layout["template_key"], self.payload["key"])
        self.assertEqual(layout["coordinates"], {"space": "normalized", "origin": "top-left"})
        self.assertEqual(layout["source_image"],
                         {"width": 720, "height": 960, "sha256": "f" * 64, "path": "art/mockup.png"})
        self.assertEqual(layout["feature"], {"type": "standard"})

    def test_client_rendered_zones_ride_along_but_are_not_elements(self):
        layout, _ = build_mod.build_layout(self.payload, self.geometry, self.ana)
        roles = [c["role"] for c in layout["client_rendered"]]
        self.assertIn("timer", roles)
        self.assertIn("resource_area", roles)
        self.assertIn("price_before_sale", roles)
        element_keys = {e["key"] for e in layout["elements"]}
        for r in roles:
            self.assertNotIn(r, element_keys)

    def test_missing_geometry_entry_flags_unplaced_never_drops(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["elements"] = [g for g in geometry["elements"] if g["key"] != "header"]
        layout, rep = build_mod.build_layout(self.payload, geometry, self.ana)
        header = next(e for e in layout["elements"] if e["key"] == "header")
        self.assertIsNone(header["bbox"])
        self.assertTrue(header["unplaced"])
        self.assertEqual(rep["unplaced"], ["texts.header"])
        self.assertEqual(rep["errors"], [])

    def test_stray_geometry_row_is_an_error(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["elements"].append({"key": "ghost", "bucket": "texts",
                                     "bbox": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}})
        _, rep = build_mod.build_layout(self.payload, geometry, self.ana)
        self.assertTrue(any("ghost" in e for e in rep["errors"]))

    def test_out_of_range_bbox_is_an_error_and_nulls_the_box(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["elements"][0]["bbox"] = {"x": -0.2, "y": 0.1, "w": 0.5, "h": 0.5}
        layout, rep = build_mod.build_layout(self.payload, geometry, self.ana)
        self.assertTrue(any("bbox.x" in e for e in rep["errors"]))
        bad = next(e for e in layout["elements"]
                   if (e["bucket"], e["key"]) == (geometry["elements"][0]["bucket"],
                                                  geometry["elements"][0]["key"]))
        self.assertIsNone(bad["bbox"])
        self.assertTrue(bad["unplaced"])

    def test_edge_overflow_is_a_warning_not_an_error(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["elements"][0]["bbox"] = {"x": 0.6, "y": 0.1, "w": 0.5, "h": 0.5}
        _, rep = build_mod.build_layout(self.payload, geometry, self.ana)
        self.assertEqual(rep["errors"], [])
        self.assertTrue(any("past the image edge" in w for w in rep["warnings"]))

    def test_area_bbox_feeds_feature_when_valid(self):
        ana = copy.deepcopy(self.ana)
        ana["feature"] = {"type": "milestone",
                          "detected": {"milestone_count": 3,
                                       "area_bbox": {"x": 0.1, "y": 0.4, "w": 0.8, "h": 0.3}}}
        payload, report = build_mod.build_payload(ana)
        layout, rep = build_mod.build_layout(payload, _geometry_for(payload, report), ana)
        self.assertEqual(layout["feature"]["type"], "milestone")
        self.assertEqual(layout["feature"]["area_bbox"], {"x": 0.1, "y": 0.4, "w": 0.8, "h": 0.3})

    def test_invalid_area_bbox_is_dropped_with_a_warning(self):
        ana = copy.deepcopy(self.ana)
        ana["feature"] = {"type": "milestone", "detected": {"area_bbox": {"x": 2, "y": 0, "w": 1, "h": 1}}}
        payload, report = build_mod.build_payload(ana)
        layout, rep = build_mod.build_layout(payload, _geometry_for(payload, report), ana)
        self.assertNotIn("area_bbox", layout["feature"])
        self.assertTrue(any("area_bbox dropped" in w for w in rep["warnings"]))

    def test_client_rendered_falls_back_to_the_analysis(self):
        geometry = copy.deepcopy(self.geometry)
        del geometry["client_rendered"]
        layout, _ = build_mod.build_layout(self.payload, geometry, self.ana)
        self.assertIn("timer", [c["role"] for c in layout["client_rendered"]])

    def test_hand_placed_and_adjusted_flags_survive(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["elements"][0]["hand_placed"] = True
        geometry["elements"][1]["adjusted"] = True
        layout, _ = build_mod.build_layout(self.payload, geometry, self.ana)
        flags = {(e["bucket"], e["key"]): e for e in layout["elements"]}
        g0, g1 = geometry["elements"][0], geometry["elements"][1]
        self.assertTrue(flags[(g0["bucket"], g0["key"])].get("hand_placed"))
        self.assertTrue(flags[(g1["bucket"], g1["key"])].get("adjusted"))

    def test_missing_fingerprint_and_size_warn(self):
        geometry = copy.deepcopy(self.geometry)
        geometry["source_image"] = None
        ana = copy.deepcopy(self.ana)
        del ana["source_image"]
        _, rep = build_mod.build_layout(self.payload, geometry, ana)
        self.assertTrue(any("sha256" in w for w in rep["warnings"]))
        self.assertTrue(any("pixel size" in w for w in rep["warnings"]))


class TestValidateLayout(unittest.TestCase):
    def setUp(self):
        ana = copy.deepcopy(ONE_CTA)
        ana["source_image"] = {"path": "m.png", "width": 720, "height": 960}
        self.ana = ana
        self.payload, report = build_mod.build_payload(ana)
        self.layout, _ = build_mod.build_layout(
            self.payload, _geometry_for(self.payload, report), ana)

    def test_built_layout_validates_against_its_payload(self):
        res = build_mod.validate_layout(self.layout, self.payload)
        self.assertTrue(res["ok"], res["errors"])

    def test_missing_layout_entry_is_an_error(self):
        layout = copy.deepcopy(self.layout)
        layout["elements"] = [e for e in layout["elements"] if e["key"] != "cta_button"]
        res = build_mod.validate_layout(layout, self.payload)
        self.assertFalse(res["ok"])
        self.assertTrue(any("has no layout entry" in e for e in res["errors"]))

    def test_extra_layout_entry_is_an_error(self):
        layout = copy.deepcopy(self.layout)
        layout["elements"].append({"key": "ghost", "bucket": "texts", "index": 99,
                                   "bbox": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}})
        res = build_mod.validate_layout(layout, self.payload)
        self.assertFalse(res["ok"])
        self.assertTrue(any("not in the payload" in e for e in res["errors"]))

    def test_index_mismatch_is_an_error(self):
        layout = copy.deepcopy(self.layout)
        layout["elements"][0]["index"] = 42
        res = build_mod.validate_layout(layout, self.payload)
        self.assertFalse(res["ok"])
        self.assertTrue(any("!= payload index" in e for e in res["errors"]))

    def test_template_key_mismatch_is_an_error(self):
        layout = copy.deepcopy(self.layout)
        layout["template_key"] = "other"
        res = build_mod.validate_layout(layout, self.payload)
        self.assertTrue(any("template_key" in e for e in res["errors"]))

    def test_wrong_coordinate_convention_is_an_error(self):
        layout = copy.deepcopy(self.layout)
        layout["coordinates"] = {"space": "pixels", "origin": "top-left"}
        res = build_mod.validate_layout(layout)
        self.assertFalse(res["ok"])

    def test_null_bbox_without_unplaced_flag_warns(self):
        layout = copy.deepcopy(self.layout)
        layout["elements"][0]["bbox"] = None
        res = build_mod.validate_layout(layout)
        self.assertTrue(any("not flagged 'unplaced'" in w for w in res["warnings"]))


# --------------------------------------------------------------------------
# remap — layout path B (existing dashboard template + tip-image analysis)
# --------------------------------------------------------------------------


class TestRemapRecord(unittest.TestCase):
    def setUp(self):
        ana = copy.deepcopy(ONE_CTA)
        ana["source_image"] = {"path": "tip.png", "width": 720, "height": 960}
        self.ana = ana
        payload, _ = build_mod.build_payload(ana)
        self.record = dict(payload, id="tpl-1", status="draft")

    def test_happy_path_keys_come_from_the_record(self):
        res = build_mod.remap_record(self.record, self.ana)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["payload"]["key"], self.record["key"])
        record_keys = {(b, i["key"]) for b in build_mod.BUCKETS for i in self.record[b]}
        trace_keys = {(t["bucket"], t["key"]) for t in res["report"]["elements"]}
        self.assertEqual(trace_keys, record_keys)
        self.assertTrue(all(t["bbox"] for t in res["report"]["elements"]))
        self.assertEqual(res["match"]["unmatched_slots"], [])
        self.assertTrue(res["validation"]["ok"])

    def test_remap_feeds_the_layout_pipeline(self):
        res = build_mod.remap_record(self.record, self.ana)
        geometry = _geometry_for(res["payload"], res["report"])
        layout, rep = build_mod.build_layout(res["payload"], geometry, self.ana)
        self.assertEqual(rep["errors"], [])
        check = build_mod.validate_layout(layout, res["payload"])
        self.assertTrue(check["ok"], check["errors"])

    def test_feature_type_mismatch_fails_closed(self):
        ana = copy.deepcopy(self.ana)
        ana["feature"] = {"type": "milestone"}
        res = build_mod.remap_record(self.record, ana)
        self.assertFalse(res["ok"])
        self.assertIn("feature type mismatch", res["reason"])

    def test_alien_elements_fail_closed_with_the_mismatch(self):
        ana = copy.deepcopy(self.ana)
        ana["elements"] = ana["elements"] + [
            {"role": "cta_button", "suggested_key": "second_cta", "observed_text": "$9.99",
             "bbox": {"x": 0.1, "y": 0.9, "w": 0.3, "h": 0.06}},
        ]
        res = build_mod.remap_record(self.record, ana)
        self.assertFalse(res["ok"])
        self.assertIn("stale or", res["reason"])
        self.assertEqual(len(res["mismatch"]), 1)
        self.assertEqual(res["mismatch"][0]["bucket"], "buttons")

    def test_unmatched_slots_warn_and_stay_out_of_the_trace(self):
        ana = copy.deepcopy(self.ana)
        ana["elements"] = [el for el in ana["elements"] if el["role"] != "fine_print"]
        res = build_mod.remap_record(self.record, ana)
        self.assertTrue(res["ok"], res)
        self.assertIn("texts.fine_print", res["match"]["unmatched_slots"])
        self.assertTrue(any("bbox null" in w for w in res["report"]["warnings"]))
        self.assertNotIn("fine_print", [t["key"] for t in res["report"]["elements"]])

    def test_duplicate_roles_join_their_own_bboxes(self):
        # Two elements with the SAME role must each land on its own slot with
        # its own bbox — the need_index join is what prevents the old
        # role-keyed ambiguity.
        ana = analysis([
            {"role": "label_text", "suggested_key": "row_one",
             "bbox": {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.05}, "observed_text": "one"},
            {"role": "label_text", "suggested_key": "row_two",
             "bbox": {"x": 0.1, "y": 0.3, "w": 0.3, "h": 0.05}, "observed_text": "two"},
        ])
        record = template_record(texts=[text_slot("row_one"), text_slot("row_two")])
        res = build_mod.remap_record(record, ana)
        self.assertTrue(res["ok"], res)
        by_key = {t["key"]: t for t in res["report"]["elements"]}
        self.assertEqual(by_key["row_one"]["bbox"]["y"], 0.1)
        self.assertEqual(by_key["row_two"]["bbox"]["y"], 0.3)

    def test_summary_record_fails_closed(self):
        res = build_mod.remap_record({"key": "t", "buttonsCount": 2}, self.ana)
        self.assertFalse(res["ok"])
        self.assertIn("summary record", res["reason"])


class TestLayoutCLI(unittest.TestCase):
    def run_cli(self, argv):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = build_mod.main(argv)
        return code, json.loads(buf.getvalue())

    def _tmp(self, name, obj):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    def setUp(self):
        import tempfile

        self.dir = tempfile.mkdtemp()
        ana = copy.deepcopy(ONE_CTA)
        ana["source_image"] = {"path": "mockup.png", "width": 720, "height": 960}
        self.ana = ana
        payload, report = build_mod.build_payload(ana)
        self.payload, self.report = payload, report
        self.build_path = self._tmp("build.json", {
            "ok": True, "payload": payload, "report": report,
            "validation": build_mod.validate_payload(payload)})

    def tearDown(self):
        import shutil

        shutil.rmtree(self.dir, ignore_errors=True)

    def test_layout_from_build_writes_the_bare_artifact(self):
        out = os.path.join(self.dir, "t.layout.json")
        code, res = self.run_cli(["layout", "--build", self.build_path,
                                  "--analysis", self._tmp("a.json", self.ana), "--out", out])
        self.assertEqual(code, 0, res)
        self.assertTrue(res["ok"])
        self.assertTrue(any("pre-confirmation" in w for w in res["warnings"]))
        with open(out, encoding="utf-8") as fh:
            artifact = json.load(fh)
        self.assertEqual(artifact, res["layout"])
        self.assertEqual(artifact["template_key"], self.payload["key"])

    def test_layout_from_confirmed_envelope(self):
        env = {"confirmed_at": "2026-09-30T00:00:00Z", "page_generated_at": "x",
               "corrections": {}, "geometry": _geometry_for(self.payload, self.report),
               "payload": self.payload}
        code, res = self.run_cli(["layout", "--envelope", self._tmp("env.json", env),
                                  "--analysis", self._tmp("a.json", self.ana)])
        self.assertEqual(code, 0, res)
        self.assertTrue(res["ok"])
        self.assertFalse(any("pre-confirmation" in w for w in res["warnings"]))
        self.assertEqual(res["layout"]["source_image"]["sha256"], "f" * 64)

    def test_envelope_without_geometry_fails_with_guidance(self):
        env = {"confirmed_at": "x", "corrections": {}, "payload": self.payload}
        code, res = self.run_cli(["layout", "--envelope", self._tmp("env.json", env)])
        self.assertEqual(code, 1)
        self.assertIn("no geometry block", res["error"])

    def test_validate_accepts_the_layout_against_the_payload(self):
        env = {"geometry": _geometry_for(self.payload, self.report), "payload": self.payload}
        out = os.path.join(self.dir, "t.layout.json")
        self.run_cli(["layout", "--envelope", self._tmp("env.json", env),
                      "--analysis", self._tmp("a.json", self.ana), "--out", out])
        code, res = self.run_cli(["validate", "--payload", self._tmp("p.json", self.payload),
                                  "--layout", out])
        self.assertEqual(code, 0, res)
        self.assertTrue(res["ok"])

    def test_remap_cli_round_trip(self):
        record = dict(self.payload, id="tpl-9", status="active")
        code, res = self.run_cli(["remap", "--record", self._tmp("r.json", record),
                                  "--analysis", self._tmp("a.json", self.ana)])
        self.assertEqual(code, 0, res)
        self.assertTrue(res["ok"])
        self.assertEqual(res["match"]["verdict"], "reuse")
