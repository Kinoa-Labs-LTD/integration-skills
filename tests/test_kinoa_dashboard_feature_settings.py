"""Offline unit tests for skills/kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py.

No network — `_request` is monkeypatched. Focuses on the derived-logic spots
where a silent regression corrupts live dashboard state: latest-version
selection, create-config's tableColumns synthesis, the DRAFT → IN_REVIEW →
publish sequencing, and the --expect-game cross-game backstop.

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
    REPO_ROOT, "skills", "kinoa-dashboard-feature-settings", "kinoa_dashboard_feature_settings.py"
)

GAME_ID = "11111111-1111-1111-1111-111111111111"
SCHEMA_ID = "33333333-3333-3333-3333-333333333333"
VERSION_ID = "44444444-4444-4444-4444-444444444444"
CONFIG_ID = "55555555-5555-5555-5555-555555555555"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "kinoa_dashboard_feature_settings_under_test", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FeatureSettingsHelperTests(unittest.TestCase):
    def setUp(self):
        self._saved_environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._saved_environ)))
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        os.environ["USERPROFILE"] = self._home.name
        os.environ["HOME"] = self._home.name
        self.mod = _load_module()
        os.environ["KINOA_BEARER_TOKEN"] = "FAKE_TOKEN"
        os.environ["KINOA_GAME_ID"] = GAME_ID
        os.environ["KINOA_GAME_SECRET"] = "FAKE_SECRET"
        self.requests = []

    def _mock_request(self, responses):
        queue = list(responses)

        def fake_request(method, url, headers=None, body=None, content_type="application/json"):
            self.requests.append({
                "method": method, "url": url, "headers": headers,
                "body": body, "content_type": content_type,
            })
            return queue.pop(0)

        self.mod._request = fake_request

    def _call(self, func, args_ns, responses):
        self._mock_request(responses)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = func(args_ns)
        return code, json.loads(out.getvalue())

    # ---- latest-version selection ----

    def test_pick_latest_version_numeric_max_not_lexicographic(self):
        schema = {"versions": [
            {"version": "2", "id": "v2", "order": 1},
            {"version": "10", "id": "v10", "order": 2},
            {"version": "9", "id": "v9", "order": 3},
        ]}
        latest = self.mod._pick_latest_version(schema)
        self.assertEqual(latest["id"], "v10")  # "9" > "10" lexicographically — must not win

    def test_pick_latest_version_non_numeric_falls_back_to_order(self):
        schema = {"versions": [
            {"version": "draft-a", "id": "a", "order": 1},
            {"version": "draft-b", "id": "b", "order": 5},
        ]}
        self.assertEqual(self.mod._pick_latest_version(schema)["id"], "b")

    def test_pick_latest_version_empty(self):
        self.assertIsNone(self.mod._pick_latest_version({"versions": []}))
        self.assertIsNone(self.mod._pick_latest_version({}))

    def test_latest_version_fetch_failure_is_error_not_guess(self):
        ns = argparse.Namespace(schema_id=SCHEMA_ID)
        code, result = self._call(self.mod.cmd_latest_version, ns, [(500, "")])
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "fetch_failed")

    def test_latest_version_happy_path(self):
        schema = {"name": "Shop", "status": "ACTIVE", "versions": [
            {"version": "1", "id": "v1", "order": 0, "status": "ACTIVE"},
            {"version": "2", "id": "v2", "order": 1, "status": "DRAFT"},
        ]}
        ns = argparse.Namespace(schema_id=SCHEMA_ID)
        code, result = self._call(self.mod.cmd_latest_version, ns, [(200, json.dumps(schema))])
        self.assertEqual(code, 0)
        self.assertEqual(result["schema_version_id"], "v2")
        self.assertEqual(result["version"], "2")

    # ---- create-config tableColumns synthesis ----

    def _create_config_ns(self, **overrides):
        ns = argparse.Namespace(
            name="Test config", description=None, setting_id="set-1",
            schema_id=SCHEMA_ID, schema_version_id=VERSION_ID,
            priority=0, default=True, expect_game=None,
        )
        for k, v in overrides.items():
            setattr(ns, k, v)
        return ns

    def test_create_config_builds_one_column_per_schema_field(self):
        schema = {"versions": [{
            "id": VERSION_ID,
            "tableFields": [
                {"id": "f1", "name": "price", "type": "number"},
                {"id": "f2", "name": "sku", "type": "string"},
            ],
        }]}
        code, result = self._call(
            self.mod.cmd_create_config, self._create_config_ns(),
            [(200, json.dumps(schema)), (201, "{}")],
        )
        self.assertEqual(code, 0)
        body = self.requests[1]["body"]
        self.assertEqual(body["status"], "DRAFT")
        self.assertTrue(body["isDefault"])
        cols = body["tableColumns"]
        self.assertEqual(len(cols), 2)  # backend rejects a config missing a column per field
        self.assertEqual(cols[0], {"name": "price", "fieldId": "f1", "fieldName": "price",
                                   "isFilter": False, "order": 0, "type": "number"})
        self.assertEqual(cols[1]["fieldId"], "f2")
        self.assertEqual(cols[1]["order"], 1)

    def test_create_config_unknown_version_id_fails_closed(self):
        schema = {"versions": [{"id": "other-version", "tableFields": []}]}
        code, result = self._call(
            self.mod.cmd_create_config, self._create_config_ns(),
            [(200, json.dumps(schema))],
        )
        self.assertEqual(result["error"], "version_not_found")
        # No POST fired after the failed resolution: exactly one request (the GET).
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_create_config_schema_fetch_failure_fails_closed(self):
        code, result = self._call(
            self.mod.cmd_create_config, self._create_config_ns(), [(503, "")],
        )
        self.assertEqual(result["error"], "schema_fetch_failed")
        self.assertEqual(len(self.requests), 1)

    # ---- status lifecycle sequencing ----

    def test_submit_config_patches_status_to_in_review_as_json_patch(self):
        ns = argparse.Namespace(config_id=CONFIG_ID, expect_game=None)
        code, _ = self._call(self.mod.cmd_submit_config, ns, [(200, "{}")])
        req = self.requests[0]
        self.assertEqual(req["method"], "PATCH")
        self.assertEqual(req["content_type"], "application/json-patch+json")
        self.assertEqual(req["body"], [{"op": "replace", "path": "/status", "value": "IN_REVIEW"}])

    def test_publish_config_posts_publish_endpoint(self):
        ns = argparse.Namespace(config_id=CONFIG_ID, expect_game=None)
        self._call(self.mod.cmd_publish_config, ns, [(200, "{}")])
        req = self.requests[0]
        self.assertEqual(req["method"], "POST")
        self.assertTrue(req["url"].endswith(f"/{CONFIG_ID}/publish"))

    # ---- cross-game backstop ----

    def test_expect_game_mismatch_exits_before_any_request(self):
        ns = argparse.Namespace(expect_game="99999999-9999-9999-9999-999999999999")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod._guard_expected_game(ns)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "session_game_mismatch")

    def test_expect_game_match_passes(self):
        ns = argparse.Namespace(expect_game=GAME_ID)
        self.mod._guard_expected_game(ns)  # must not raise

    def test_expect_game_empty_string_fails_closed(self):
        # An unset shell variable expands to "" — that must be an error, not a
        # silently disabled guard.
        ns = argparse.Namespace(expect_game="")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod._guard_expected_game(ns)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "empty_expect_game")

    def test_expect_game_accepted_on_readonly_list_configs(self):
        # Regression (live 2026-07-17): list-configs --expect-game used to die in
        # argparse with "unrecognized arguments" because the guard parent was only
        # attached to mutating subparsers. Read-only subcommands must accept the
        # flag and run the same guard.
        self._mock_request([(200, json.dumps({"data": []}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["list-configs", "--setting-id", "set-1",
                                  "--expect-game", GAME_ID])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "GET")

    def test_expect_game_mismatch_on_readonly_exits_before_request(self):
        self._mock_request([])  # any request would raise IndexError — proves none fired
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            self.mod.main(["list-configs", "--setting-id", "set-1",
                           "--expect-game", "99999999-9999-9999-9999-999999999999"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "session_game_mismatch")
        self.assertEqual(self.requests, [])

    def test_expect_game_mismatch_still_aborts_mutating_delete_config(self):
        # Mutating behavior unchanged: delete-config still guards through main().
        self._mock_request([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            self.mod.main(["delete-config", "--config-id", CONFIG_ID,
                           "--expect-game", "99999999-9999-9999-9999-999999999999"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "session_game_mismatch")
        self.assertEqual(self.requests, [])

    # ---- public runtime read ----

    def test_get_config_uses_game_secret_not_bearer(self):
        ns = argparse.Namespace(setting_key="shop", version="1", player_id="p-1",
                                get_default=False, checksum=[], include_filters=False,
                                checksum_only=False)
        self._call(self.mod.cmd_get_config, ns, [(200, "{}")])
        headers = self.requests[0]["headers"]
        self.assertEqual(headers, {"game": "FAKE_SECRET"})
        body = self.requests[0]["body"]
        self.assertEqual(body["settings"][0]["key"], "shop")
        self.assertEqual(body["settings"][0]["version"], "1")
        self.assertFalse(body["settings"][0]["getDefault"])


if __name__ == "__main__":
    unittest.main()
