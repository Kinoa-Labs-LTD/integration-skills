"""Offline unit tests for
skills/kinoa-dashboard-resource-template/kinoa_dashboard_resource_template.py.

No network — `_request` is monkeypatched. Run from the repo root:

    python -m unittest discover tests -v
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(
    REPO_ROOT, "skills", "kinoa-dashboard-resource-template",
    "kinoa_dashboard_resource_template.py",
)

TEMPLATE_ID = "33333333-3333-3333-3333-333333333333"


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_dashboard_resource_template_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ResourceTemplateHelperTests(unittest.TestCase):
    def setUp(self):
        # Isolate HOME so the import-time session.env read can't touch a real ~/.kinoa,
        # and snapshot/restore os.environ so fake KINOA_* keys never leak to later modules.
        self._saved_environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._saved_environ)))
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        os.environ["USERPROFILE"] = self._home.name
        os.environ["HOME"] = self._home.name
        self.mod = _load_module()
        os.environ["KINOA_BEARER_TOKEN"] = "FAKE_TOKEN"
        os.environ["KINOA_GAME_ID"] = "11111111-1111-1111-1111-111111111111"
        self.requests = []

    def _mock_request(self, responses):
        queue = list(responses)

        def fake_request(method, url, headers=None, body=None):
            self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
            return queue.pop(0)

        self.mod._request = fake_request

    def _call(self, func, args_ns, responses):
        self._mock_request(responses)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = func(args_ns)
        return code, json.loads(out.getvalue())

    # ---- _parse_field_spec ----

    def test_field_spec_basic_number(self):
        f = self.mod._parse_field_spec("gold:number")
        self.assertEqual(f, {"name": "gold", "field_type": "number", "required": False})

    def test_field_spec_all_allowed_types_parse(self):
        for ftype in self.mod.ALLOWED_FIELD_TYPES:
            extra = ":a,b" if ftype == "enumeration" else ""
            f = self.mod._parse_field_spec(f"p_{ftype}:{ftype}{extra}")
            self.assertEqual(f["field_type"], ftype)

    def test_field_spec_required_flag(self):
        f = self.mod._parse_field_spec("title:string:req")
        self.assertTrue(f["required"])

    def test_field_spec_enumeration_values(self):
        f = self.mod._parse_field_spec("rarity:enumeration:common,rare,epic")
        self.assertEqual(f["enumeration_values"], ["common", "rare", "epic"])
        self.assertFalse(f["required"])

    def test_field_spec_enumeration_values_and_required(self):
        f = self.mod._parse_field_spec("rarity:enumeration:common,rare:req")
        self.assertEqual(f["enumeration_values"], ["common", "rare"])
        self.assertTrue(f["required"])

    def test_field_spec_enumeration_requires_values(self):
        with self.assertRaises(ValueError):
            self.mod._parse_field_spec("rarity:enumeration")

    def test_field_spec_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            self.mod._parse_field_spec("foo:datetime")

    def test_field_spec_rejects_missing_type(self):
        with self.assertRaises(ValueError):
            self.mod._parse_field_spec("gold")

    # ---- list ----

    def test_list_default_query(self):
        ns = argparse.Namespace(rows=100, page=0, statuses=None, name=None,
                                sort_by="updated_at", order="desc")
        code, _ = self._call(self.mod.cmd_list, ns, [(200, json.dumps({"total": 0, "summaries": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        self.assertIn("rows=100", url)
        self.assertIn("sortBy=updated_at", url)
        self.assertIn("order=desc", url)
        self.assertNotIn("statuses=", url)

    def test_list_statuses_filter_repeats_uppercased(self):
        ns = argparse.Namespace(rows=50, page=0, statuses="draft,active", name=None,
                                sort_by="updated_at", order="desc")
        code, _ = self._call(self.mod.cmd_list, ns, [(200, json.dumps({"total": 0, "summaries": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        self.assertIn("statuses=DRAFT", url)
        self.assertIn("statuses=ACTIVE", url)

    def test_list_name_filter(self):
        ns = argparse.Namespace(rows=100, page=0, statuses=None, name="chest",
                                sort_by="updated_at", order="desc")
        self._call(self.mod.cmd_list, ns, [(200, json.dumps({"total": 0, "summaries": []}))])
        self.assertIn("name=chest", self.requests[0]["url"])

    # ---- create ----

    def test_create_body_shape_defaults_to_draft(self):
        ns = argparse.Namespace(name="Legendary Sword", key="legendary_sword", description="A prize",
                                status="draft", body=None, field=["attack:number", "rarity:enumeration:common,epic"],
                                fields_json=None)
        code, result = self._call(self.mod.cmd_create, ns, [(200, json.dumps({"id": TEMPLATE_ID}))])
        self.assertEqual(code, 0)
        body = self.requests[0]["body"]
        self.assertEqual(body["name"], "Legendary Sword")
        self.assertEqual(body["resourceKey"], "legendary_sword")
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["description"], "A prize")
        self.assertEqual(body["body"], {})
        types = {f["name"]: f["field_type"] for f in body["fields"]}
        self.assertEqual(types, {"attack": "number", "rarity": "enumeration"})
        self.assertEqual(self.requests[0]["method"], "POST")

    def test_create_fields_json_takes_precedence(self):
        rich = [{"name": "attack", "field_type": "number", "required": True, "description": "dmg"}]
        ns = argparse.Namespace(name="Sword", key="sword", description=None, status="draft",
                                body=None, field=["ignored:string"], fields_json=json.dumps(rich))
        code, _ = self._call(self.mod.cmd_create, ns, [(200, json.dumps({"id": TEMPLATE_ID}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["body"]["fields"], rich)

    def test_create_with_body_json(self):
        ns = argparse.Namespace(name="Sword", key="sword", description=None, status="draft",
                                body='{"tier":"${rarity}"}', field=[], fields_json=None)
        code, _ = self._call(self.mod.cmd_create, ns, [(200, json.dumps({"id": TEMPLATE_ID}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["body"]["body"], {"tier": "${rarity}"})

    def test_create_invalid_field_exits_2_without_request(self):
        ns = argparse.Namespace(name="x", key="x", description=None, status="draft",
                                body=None, field=["broken"], fields_json=None)
        code, result = self._call(self.mod.cmd_create, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_field")
        self.assertEqual(self.requests, [])

    def test_create_invalid_fields_json_exits_2(self):
        ns = argparse.Namespace(name="x", key="x", description=None, status="draft",
                                body=None, field=[], fields_json='{"not":"a list"}')
        code, result = self._call(self.mod.cmd_create, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_fields_json")
        self.assertEqual(self.requests, [])

    def test_create_invalid_body_json_exits_2(self):
        ns = argparse.Namespace(name="x", key="x", description=None, status="draft",
                                body="[1,2,3]", field=[], fields_json=None)
        code, result = self._call(self.mod.cmd_create, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_body")
        self.assertEqual(self.requests, [])

    # ---- update (GET + merged PUT) ----

    def test_update_merges_only_provided_fields(self):
        current = {"id": TEMPLATE_ID, "name": "Old", "resourceKey": "old_key", "status": "draft",
                   "body": {"x": 1}, "fields": [{"name": "a", "field_type": "number", "required": False}],
                   "description": "keep me"}
        ns = argparse.Namespace(id=TEMPLATE_ID, name="New Name", key=None, description=None,
                                status=None, body=None, field=[], fields_json=None)
        code, result = self._call(self.mod.cmd_update, ns,
                                  [(200, json.dumps(current)), (200, json.dumps({"ok": True}))])
        self.assertEqual(code, 0)
        self.assertEqual([r["method"] for r in self.requests], ["GET", "PUT"])
        put_body = self.requests[1]["body"]
        # only name overridden; everything else preserved from the fetched record
        self.assertEqual(put_body["name"], "New Name")
        self.assertEqual(put_body["resourceKey"], "old_key")
        self.assertEqual(put_body["description"], "keep me")
        self.assertEqual(put_body["body"], {"x": 1})
        self.assertEqual(put_body["fields"], current["fields"])

    def test_update_propagates_fetch_failure(self):
        ns = argparse.Namespace(id=TEMPLATE_ID, name="x", key=None, description=None,
                                status=None, body=None, field=[], fields_json=None)
        code, result = self._call(self.mod.cmd_update, ns, [(404, "")])
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "fetch_failed")
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_update_unexpected_shape_exit_1(self):
        ns = argparse.Namespace(id=TEMPLATE_ID, name="x", key=None, description=None,
                                status=None, body=None, field=[], fields_json=None)
        code, result = self._call(self.mod.cmd_update, ns, [(200, json.dumps([1, 2, 3]))])
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "unexpected_template_shape")
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    # ---- activate / deprecate / clone ----

    def test_activate_posts_to_activate_endpoint(self):
        ns = argparse.Namespace(id=TEMPLATE_ID)
        code, _ = self._call(self.mod.cmd_activate, ns, [(200, json.dumps({"status": "active"}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "POST")
        self.assertTrue(self.requests[0]["url"].endswith(f"/resource-templates/{TEMPLATE_ID}/activate"))

    def test_deprecate_carries_reason(self):
        ns = argparse.Namespace(id=TEMPLATE_ID, reason="retired for season 5")
        code, _ = self._call(self.mod.cmd_deprecate, ns, [(200, json.dumps({"status": "deprecated"}))])
        self.assertEqual(code, 0)
        self.assertTrue(self.requests[0]["url"].endswith(f"/{TEMPLATE_ID}/deprecate"))
        self.assertEqual(self.requests[0]["body"], {"deprecationReason": "retired for season 5"})

    def test_clone_body(self):
        ns = argparse.Namespace(id=TEMPLATE_ID, key="sword_copy", name="Sword Copy")
        code, _ = self._call(self.mod.cmd_clone, ns, [(200, json.dumps({"id": "new"}))])
        self.assertEqual(code, 0)
        self.assertTrue(self.requests[0]["url"].endswith(f"/{TEMPLATE_ID}/clone"))
        self.assertEqual(self.requests[0]["body"], {"key": "sword_copy", "name": "Sword Copy"})

    # ---- delete ----

    def test_delete_hits_endpoint(self):
        ns = argparse.Namespace(id=TEMPLATE_ID)
        code, _ = self._call(self.mod.cmd_delete, ns, [(200, "")])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "DELETE")
        self.assertTrue(self.requests[0]["url"].endswith(f"/resource-templates/{TEMPLATE_ID}"))

    def test_delete_409_adds_deprecate_hint(self):
        ns = argparse.Namespace(id=TEMPLATE_ID)
        code, result = self._call(self.mod.cmd_delete, ns,
                                  [(409, json.dumps({"message": "Cannot delete template for this status"}))])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertIn("DRAFT", result["hint"])
        self.assertIn("deprecate", result["hint"])

    # ---- cross-game guard (--expect-game) ----

    def test_expect_game_mismatch_aborts_before_any_request(self):
        self._mock_request([])  # any request would raise IndexError — proves none fired
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["delete", "--id", TEMPLATE_ID,
                           "--expect-game", "99999999-9999-9999-9999-999999999999"])
        self.assertEqual(cm.exception.code, 2)
        result = json.loads(out.getvalue())
        self.assertEqual(result["error"], "session_game_mismatch")
        self.assertEqual(self.requests, [])

    def test_expect_game_match_proceeds(self):
        self._mock_request([(200, json.dumps({"ok": True}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["delete", "--id", TEMPLATE_ID,
                                  "--expect-game", os.environ["KINOA_GAME_ID"]])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "DELETE")

    def test_expect_game_guards_create(self):
        # create is mutating → the guard applies there too, not just delete.
        self._mock_request([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["create", "--name", "X", "--key", "x",
                           "--expect-game", "99999999-9999-9999-9999-999999999999"])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.requests, [])

    # ---- CLI wiring ----

    def test_main_parses_create_subcommand(self):
        self._mock_request([(200, json.dumps({"id": TEMPLATE_ID}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["create", "--name", "Sword", "--key", "sword", "--field", "attack:number"])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "POST")

    def test_admin_headers_have_bearer_and_game_id_only(self):
        headers = self.mod._admin_headers()
        self.assertEqual(headers["Authorization"], "Bearer FAKE_TOKEN")
        self.assertIn("Game-Id", headers)
        # bundles reads only Game-Id — the gamemetaapi-style `Game` header is not sent here.
        self.assertNotIn("Game", headers)


if __name__ == "__main__":
    unittest.main()
