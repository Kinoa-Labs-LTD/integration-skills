"""Offline unit tests for skills/kinoa-sdk-dashboard-sync/generate_merge_plan_page.py.

Pure generator — no network by design. Run from the repo root:

    python -m unittest discover tests -v
"""

import ast
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-sdk-dashboard-sync",
                           "generate_merge_plan_page.py")
PLANNER_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-sdk-dashboard-sync",
                            "kinoa_sdk_sync_plan.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_merge_plan_page_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(**overrides):
    base = {
        "generated_at": "2026-07-24T09:00:00Z",
        "game_id": "11111111-1111-1111-1111-111111111111",
        "events": [
            {"id": 1, "kind": "custom", "name": "gold_purchase", "existing": False,
             "source": "Scripts/Shop.cs:118",
             "params": [{"name": "amount", "kind": "number", "extra": ""}]},
            {"id": 2, "kind": "predefined", "name": "session_start", "existing": True,
             "source": "KinoaGameController.cs:41", "params": []},
        ],
        "player_fields": [
            {"id": 20, "name": "Wallet.Gold", "kind": "number", "existing": False,
             "source": "Scripts/Model/Player/Wallet.cs:12"},
        ],
        "feature_settings": {
            "schemas": [{"id": 40, "name": "BoosterEconomy", "existing": False,
                         "source": "booster_economy.csv",
                         "columns": [{"name": "sku", "kind": "bundle_key"}]}],
            "settings": [{"id": 41, "key": "BoosterEconomy", "schema_name": "BoosterEconomy",
                          "version": 1, "existing": False, "source": "booster_economy.csv"}],
        },
        "resources": [
            {"id": 60, "name": "Legendary Sword", "key": "legendary_sword", "existing": False,
             "description": "Boss reward.", "source": "Model/Enums/RewardType.cs:10",
             "fields": [{"name": "attack", "field_type": "number", "required": True,
                         "default": "100", "enumeration_values": [], "description": ""}]},
        ],
    }
    base.update(overrides)
    return base


class MergePlanPageTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, payload, name="page.html"):
        inp = os.path.join(self.tmp.name, "in.json")
        with open(inp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        out_path = os.path.join(self.tmp.name, name)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--input", inp, "--output", out_path, "--no-open"])
        return code, json.loads(out.getvalue()), out_path

    def test_generates_page_with_all_sections(self):
        code, result, out_path = self._run(_payload())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertFalse(result["opened_in_browser"])  # --no-open
        html = open(out_path, encoding="utf-8").read()
        for marker in ("gold_purchase", "session_start", "Wallet.Gold", "BoosterEconomy",
                       "legendary_sword", "page_generated_at", "already in code"):
            self.assertIn(marker, html)

    def test_kind_vocabularies_embedded(self):
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertIn(json.dumps(self.mod.EVENT_PARAM_KINDS), html)
        self.assertIn(json.dumps(self.mod.FIELD_KINDS), html)
        self.assertIn(json.dumps(self.mod.FS_COLUMN_KINDS), html)
        self.assertIn(json.dumps(self.mod.RESOURCE_FIELD_TYPES), html)
        self.assertIn(json.dumps(self.mod.RESOURCE_KEY_RE), html)

    def test_vocabularies_match_planner(self):
        # The page's dropdowns/validation and the planner's must agree, or the page lets
        # the developer author a kind/key the sync later refuses.
        with open(PLANNER_PATH, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        consts = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in (
                            "EVENT_PARAM_KINDS", "FIELD_KINDS", "FS_COLUMN_KINDS",
                            "RESOURCE_FIELD_TYPES", "RESOURCE_KEY_RE", "SYSTEM_EVENT_PARAM_NAMES"):
                        consts[t.id] = ast.literal_eval(node.value)
        self.assertEqual(self.mod.EVENT_PARAM_KINDS, list(consts["EVENT_PARAM_KINDS"]))
        self.assertEqual(self.mod.FIELD_KINDS, list(consts["FIELD_KINDS"]))
        self.assertEqual(self.mod.FS_COLUMN_KINDS, list(consts["FS_COLUMN_KINDS"]))
        self.assertEqual(self.mod.RESOURCE_FIELD_TYPES, list(consts["RESOURCE_FIELD_TYPES"]))
        self.assertEqual(self.mod.RESOURCE_KEY_RE, consts["RESOURCE_KEY_RE"])
        self.assertEqual(self.mod.SYSTEM_EVENT_PARAM_NAMES, list(consts["SYSTEM_EVENT_PARAM_NAMES"]))

    def test_audit_contract_markers_present(self):
        # Semantic-audit fixes: system-param warning list embedded; FS v1 hint; predefined
        # names read-only comment; name-uniqueness tooltip; required checkbox defaults.
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertIn(json.dumps(self.mod.SYSTEM_EVENT_PARAM_NAMES), html)
        self.assertIn("v1 (new schemas always start at 1)", html)
        self.assertIn("never editable", html)                      # predefined wire names
        self.assertIn("unique on the server across ALL statuses", html)  # resource NAME rule
        self.assertIn("c.is_required = true", html)                # FS required: ALWAYS true, no UI control
        # Enum values: state survives kind toggles; the EXPORT strips them for non-enum kinds.
        self.assertIn("cleanParam", html)
        self.assertIn("cleanField", html)
        self.assertIn('r.kind === "enumeration" ? r : {...r, extra: ""}', html)
        self.assertNotIn("c.is_required !== false", html)          # the old FS checkbox is gone
        self.assertIn("req.checked = !!f.required", html)          # resource required checkbox STAYS (default FALSE)

    def test_fs_split_schemas_and_settings(self):
        # FS mirrors the manifest/domain: schemas own columns; settings bind a schema via a
        # DROPDOWN (kills dangling schema_name + same-schema-different-columns by construction).
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertIn("Add schema", html)
        self.assertIn("Add setting (key)", html)
        self.assertIn("ONE schema may back several setting keys", html)
        self.assertIn("no schemas defined above", html)             # missing-schema guard in select
        self.assertIn("normalizeFs", html)                          # flat-array tolerance
        self.assertIn("isReservedFsColumn", html)                   # filter:/<> namespace guard
        self.assertIn("filters are configuration-level", html)      # its tooltip
        self.assertIn("values must be existing Bundle keys", html)  # bundle_key hint
        self.assertIn("v1 (new schema)", html)                      # setting bound to new schema
        self.assertIn("shared schema — also used by", html)          # live many-keys indicator
        self.assertIn("validation error(s) — fix to enable export", html)  # global export block
        self.assertNotIn("drags its bound settings along", html)    # auto-follow REVERTED (red + explicit choice)
        self.assertIn("maximum 30 characters", html)                 # event/param/field name caps
        self.assertIn("50 characters or less", html)                 # enum value caps
        self.assertIn("enumValuesTooLong", html)
        self.assertIn("the schema's newest wired version", html)    # existing-schema version display
        self.assertIn("valid for backward compatibility", html)      # multi-version info note
        self.assertIn(".grid > button.del", html)                     # row drop pinned right
        self.assertIn("minimum 1 column (server rule)", html)        # zero-column schema invalid
        self.assertIn("maxlength: 255", html)                        # schema-name length cap
        self.assertIn("maxlength: 100", html)                        # setting-key length cap

    def test_fs_flat_payload_tolerated(self):
        p = {"generated_at": "2026-07-28T15:00:00Z", "game_id": None,
             "feature_settings": [
                 {"id": 1, "key": "WheelOfFortune", "schema_name": "WheelOfFortune",
                  "version": 1, "existing": False,
                  "columns": [{"name": "prize", "kind": "string"}]}]}
        code, result, out_path = self._run(p)
        self.assertEqual(code, 0)
        self.assertIn("WheelOfFortune", open(out_path, encoding="utf-8").read())

    def test_fs_split_duplicate_ids_rejected(self):
        p = _payload()
        p["feature_settings"]["settings"][0]["id"] = 40  # collides with its schema
        code, result, _ = self._run(p)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_rows")

    def test_script_close_tag_in_data_is_escaped(self):
        p = _payload(events=[{"id": 1, "kind": "custom", "name": "x</script><script>alert(1)",
                              "existing": False, "params": []}])
        code, _, out_path = self._run(p)
        self.assertEqual(code, 0)
        html = open(out_path, encoding="utf-8").read()
        self.assertNotIn("x</script>", html)
        self.assertIn("x<\\/script>", html)

    def test_duplicate_ids_across_sections_rejected(self):
        p = _payload()
        p["player_fields"][0]["id"] = 1  # collides with events[0]
        code, result, _ = self._run(p)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_rows")

    def test_missing_id_rejected(self):
        p = _payload(events=[{"kind": "custom", "name": "a", "existing": False, "params": []}],
                     player_fields=[], feature_settings=[])
        code, result, _ = self._run(p)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_rows")

    def test_invalid_json_rejected(self):
        inp = os.path.join(self.tmp.name, "bad.json")
        with open(inp, "w") as f:
            f.write("{not json")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--input", inp,
                                  "--output", os.path.join(self.tmp.name, "x.html"), "--no-open"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "invalid_json")

    def test_empty_sections_ok(self):
        code, result, _ = self._run(_payload(events=[], player_fields=[],
                                             feature_settings=[], resources=[]))
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])

    def test_payload_contract_tolerance_unknown_and_minimal_keys(self):
        # Contract clause 1: an OLDER producer's payload (missing optional keys) and a NEWER
        # producer's payload (unknown keys) must both build without error.
        p = {"generated_at": "2026-07-24T09:00:00Z",
             "future_top_level_key": {"anything": True},
             "events": [{"id": 1, "future_key": "x"}],                    # minimal + unknown
             "player_fields": [{"id": 2}],
             "feature_settings": [{"id": 3}],  # flat pre-split shape -> converted on load
             "resources": [{"id": 4}]}
        code, result, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])

    def test_handback_contract_freeze(self):
        # Contract clause 2: the hand-back keys are APPEND-ONLY. Renaming any of these
        # breaks this test on purpose — a conscious decision, not an accident.
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        for frozen in ("confirmed_at:", "page_generated_at:", "payload_version:",
                       "events: state.events", "player_fields: state.player_fields",
                       "feature_settings: {schemas: state.feature_settings.schemas", "resources: state.resources"):
            self.assertIn(frozen, html)

    def test_payload_version_guard(self):
        # Contract clause 3: version constant embedded; newer-payload path disables export.
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertIn("const PAYLOAD_VERSION = 1", html)
        self.assertIn("VERSION_MISMATCH", html)
        self.assertIn("export is disabled", html)
        self.assertEqual(self.mod.PAYLOAD_VERSION, 1)

    def test_event_registries_are_payload_driven_and_reclassification_wired(self):
        # The two registries (game-wired predefined vs SDK-fired debug) travel IN THE PAYLOAD
        # (single maintained source: module-13 tables) — no hardcoded page copy to go stale.
        # Matching rows are live-tagged and EXPORTED with kind normalized (predefined/sdk).
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertIn("DATA.predefined_wire_names || []", html)
        self.assertIn("DATA.debug_wire_names || DATA.sdk_debug_wire_names || []", html)
        self.assertIn("DATA.sdk_automatic_wire_names || []", html)
        self.assertIn('DATA.integration_type || "SDK"', html)
        self.assertIn("effectiveKind", html)
        self.assertIn("kind: effectiveKind(r)", html)   # export normalization
        self.assertIn("existing builder", html)          # predefined badge tooltip
        self.assertIn("debug telemetry", html)           # debug badge tooltip (NOT sdk-bound)
        self.assertNotIn(">sdk debug<", html)            # old tag name gone
        self.assertIn("b-debug", html)                   # distinct badge style
        # Debug-tagged rows collapse their param editor (nothing gets implemented for them);
        # SDK-automatic predefined rows collapse it too under an SDK integration.
        self.assertIn("params are not applicable", html)
        self.assertIn("not redefinable in an SDK integration", html)

    def test_light_theme_only_and_visible_button_text(self):
        # Manual-run finding 2026-07-28: `color-scheme: light dark` made the UA flip button
        # text colors in dark mode over our fixed light backgrounds — invisible labels.
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertNotIn("prefers-color-scheme", html)
        self.assertIn("color-scheme: light;", html)
        self.assertIn("background: #fff; color: #1f2328;", html)  # button text pinned

    def test_sections_render_only_when_present(self):
        # Manual-run finding 2026-07-28: /kinoa resources must yield a resources-ONLY page —
        # absent payload keys hide their whole card (add button included).
        _, _, out_path = self._run(_payload())
        html = open(out_path, encoding="utf-8").read()
        self.assertIn("SECTIONS_PRESENT", html)
        self.assertIn('style.display = "none"', html)

    def test_resources_only_payload_ok(self):
        # /kinoa resources renders the resources-only page — other sections omitted entirely.
        p = {"generated_at": "2026-07-24T09:00:00Z", "game_id": None,
             "resources": [{"id": 1, "name": "Gold Chest", "key": "gold_chest",
                            "existing": False, "fields": []}]}
        code, result, out_path = self._run(p)
        self.assertEqual(code, 0)
        self.assertIn("gold_chest", open(out_path, encoding="utf-8").read())

    def test_duplicate_id_between_resources_and_events_rejected(self):
        p = _payload()
        p["resources"][0]["id"] = 1  # collides with events[0]
        code, result, _ = self._run(p)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_rows")


if __name__ == "__main__":
    unittest.main()
