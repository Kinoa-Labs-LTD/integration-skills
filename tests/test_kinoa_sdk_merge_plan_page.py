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
        "feature_settings": [
            {"id": 40, "schema_name": "BoosterEconomy", "key": "BoosterEconomy", "version": 1,
             "existing": False, "source": "booster_economy.csv",
             "columns": [{"name": "sku", "kind": "bundle_key"}]},
        ],
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
        self.assertIn("c.is_required !== false", html)             # FS required default TRUE
        self.assertIn("req.checked = !!f.required", html)          # resource required default FALSE

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
