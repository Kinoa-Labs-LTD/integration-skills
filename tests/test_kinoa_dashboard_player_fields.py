"""Offline unit tests for skills/kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py.

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
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-dashboard-player-fields",
                           "kinoa_dashboard_player_fields.py")

FIELD_ID = "33333333-3333-3333-3333-333333333333"


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_dashboard_player_fields_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PlayerFieldsHelperTests(unittest.TestCase):
    def setUp(self):
        # Isolate HOME from a real ~/.kinoa and snapshot/restore os.environ (no leak).
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

    def test_allowed_kinds_cover_dashboard_vocabulary(self):
        self.assertEqual(
            set(self.mod.ALLOWED_KINDS),
            {"number", "boolean", "string", "date", "long_string", "enumeration", "version"},
        )

    def test_create_body_shape_long_string(self):
        ns = argparse.Namespace(name="Bio", path="profile.bio", kind="long_string",
                                extra="", description="", default_value="", app_version="",
                                calculated=False)
        code, result = self._call(self.mod.cmd_create, ns, [(200, json.dumps({"state": "active"}))])
        self.assertEqual(code, 0)
        body = self.requests[0]["body"]
        self.assertEqual(body["kind"], "long_string")
        self.assertEqual(body["path"], "profile.bio")
        # camelCase contract of the player_fields POST body
        self.assertIn("appVersion", body)
        self.assertIn("defaultValue", body)
        self.assertIn("calculated", body)

    def test_create_date_kind_accepted_by_cli(self):
        self._mock_request([(200, json.dumps({"state": "active"}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["create", "--name", "Last Purchase", "--path",
                                  "wallet.last_purchase", "--kind", "date"])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["body"]["kind"], "date")

    def test_create_enumeration_requires_extra(self):
        ns = argparse.Namespace(name="Tier", path="profile.tier", kind="enumeration",
                                extra="", description="", default_value="", app_version="",
                                calculated=False)
        code, result = self._call(self.mod.cmd_create, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "missing_extra")
        self.assertEqual(self.requests, [])

    def test_activate_patches_activate_endpoint(self):
        ns = argparse.Namespace(field_id=FIELD_ID)
        code, result = self._call(self.mod.cmd_activate, ns, [(200, json.dumps({"state": "active"}))])
        self.assertEqual(code, 0)
        req = self.requests[0]
        self.assertEqual(req["method"], "PATCH")
        self.assertTrue(req["url"].endswith(f"/player_fields/{FIELD_ID}/ACTIVATE"))

    def test_list_custom_states_filter_propagates(self):
        ns = argparse.Namespace(states="deleted", rows=100)
        code, _ = self._call(self.mod.cmd_list_custom, ns, [(200, json.dumps({"data": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        self.assertIn("states=deleted", url)
        self.assertIn("types=USER", url)

    # ---- cross-game guard (--expect-game) ----

    def test_expect_game_mismatch_aborts_delete_before_request(self):
        self._mock_request([])  # any request would raise IndexError — proves none fired
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["delete", "--field-id", FIELD_ID,
                           "--expect-game", "99999999-9999-9999-9999-999999999999"])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "session_game_mismatch")
        self.assertEqual(self.requests, [])

    def test_expect_game_match_proceeds_on_activate(self):
        self._mock_request([(200, json.dumps({"state": "active"}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["activate", "--field-id", FIELD_ID,
                                  "--expect-game", os.environ["KINOA_GAME_ID"]])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "PATCH")


if __name__ == "__main__":
    unittest.main()
