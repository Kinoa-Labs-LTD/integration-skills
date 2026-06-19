"""Offline unit tests for skills/kinoa-dashboard-event/kinoa_dashboard_event.py.

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
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-dashboard-event", "kinoa_dashboard_event.py")

EVENT_ID = "22222222-2222-2222-2222-222222222222"


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_dashboard_event_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EventHelperTests(unittest.TestCase):
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

    # ---- _parse_param_spec ----

    def test_param_spec_date_kind_supported(self):
        spec = self.mod._parse_param_spec("purchase_date:date")
        self.assertEqual(spec, {"name": "purchase_date", "kind": "date", "system": False})

    def test_param_spec_all_allowed_kinds_parse(self):
        for kind in self.mod.ALLOWED_PARAM_KINDS:
            extra = ":a,b" if kind == "enumeration" else ""
            spec = self.mod._parse_param_spec(f"p_{kind}:{kind}{extra}")
            self.assertEqual(spec["kind"], kind)

    def test_param_spec_enumeration_requires_extra(self):
        with self.assertRaises(ValueError):
            self.mod._parse_param_spec("tier:enumeration")

    def test_param_spec_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            self.mod._parse_param_spec("foo:datetime")

    # ---- list --states ----

    def test_list_custom_with_states_filter(self):
        ns = argparse.Namespace(rows=100, states="deleted")
        code, result = self._call(self.mod.cmd_list_custom, ns, [(200, json.dumps({"data": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        self.assertIn("selectedFilters=states", url)
        self.assertIn("states=deleted", url)
        self.assertIn("types=USER", url)

    def test_list_custom_without_states_keeps_legacy_query(self):
        ns = argparse.Namespace(rows=100, states=None)
        self._call(self.mod.cmd_list_custom, ns, [(200, json.dumps({"data": []}))])
        url = self.requests[0]["url"]
        self.assertNotIn("selectedFilters", url)
        self.assertNotIn("states=", url)

    def test_list_predefined_with_states_filter(self):
        # cmd_list_predefined reads args.states unconditionally — pin the wiring so a
        # dropped add_argument (or signature change) can't silently break every
        # legacy list-predefined call used by the sync/API orchestrators.
        ns = argparse.Namespace(rows=100, states="not_implemented")
        code, _ = self._call(self.mod.cmd_list_predefined, ns, [(200, json.dumps({"data": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        self.assertIn("types=PREDEFINED", url)
        self.assertIn("selectedFilters=states", url)
        self.assertIn("states=not_implemented", url)

    def test_list_predefined_without_states_keeps_legacy_query(self):
        ns = argparse.Namespace(rows=100, states=None)
        self._call(self.mod.cmd_list_predefined, ns, [(200, json.dumps({"data": []}))])
        url = self.requests[0]["url"]
        self.assertIn("types=PREDEFINED", url)
        self.assertNotIn("selectedFilters", url)
        self.assertNotIn("states=", url)

    # ---- create ----

    def test_create_body_shape_with_date_param(self):
        ns = argparse.Namespace(name="gold_purchase", no_analytics=False,
                                param=["amount:number", "purchase_date:date"])
        code, result = self._call(self.mod.cmd_create, ns, [(200, json.dumps({"status": "ACTIVE"}))])
        self.assertEqual(code, 0)
        body = self.requests[0]["body"]
        self.assertEqual(body["name"], "gold_purchase")
        self.assertTrue(body["send_to_analytics"])
        self.assertFalse(body["system"])
        kinds = {p["name"]: p["kind"] for p in body["game_event_parameters"]}
        self.assertEqual(kinds, {"amount": "number", "purchase_date": "date"})

    def test_create_invalid_param_exits_2_without_request(self):
        ns = argparse.Namespace(name="x", no_analytics=False, param=["broken"])
        code, result = self._call(self.mod.cmd_create, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_param")
        self.assertEqual(self.requests, [])

    # ---- publish ----

    def test_publish_gets_then_puts_to_publish_endpoint(self):
        event = {"id": EVENT_ID, "name": "tutorial", "status": "NOT_IMPLEMENTED",
                 "game_event_parameters": []}
        ns = argparse.Namespace(event_id=EVENT_ID)
        code, result = self._call(self.mod.cmd_publish, ns,
                                  [(200, json.dumps(event)), (200, json.dumps({"status": "ACTIVE"}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "GET")
        self.assertEqual(self.requests[1]["method"], "PUT")
        self.assertTrue(self.requests[1]["url"].endswith(f"/game_events/{EVENT_ID}/publish"))
        self.assertEqual(self.requests[1]["body"], event)
        self.assertEqual(result["previous_status"], "NOT_IMPLEMENTED")

    # ---- add-params ----

    def test_add_params_merges_new_and_skips_existing(self):
        event = {"id": EVENT_ID, "name": "level_up", "status": "ACTIVE",
                 "game_event_parameters": [{"name": "level", "kind": "number", "system": False}]}
        ns = argparse.Namespace(event_id=EVENT_ID, param=["level:number", "score:number"])
        code, result = self._call(self.mod.cmd_add_params, ns,
                                  [(200, json.dumps(event)), (200, json.dumps({"ok": True}))])
        self.assertEqual(code, 0)
        self.assertEqual([p["name"] for p in result["added"]], ["score"])
        self.assertEqual(result["skipped_existing"], ["level"])
        put = self.requests[1]
        self.assertEqual(put["method"], "PUT")
        self.assertTrue(put["url"].endswith(f"/game_events/{EVENT_ID}"))
        self.assertNotIn("/publish", put["url"])
        names = [p["name"] for p in put["body"]["game_event_parameters"]]
        self.assertEqual(names, ["level", "score"])
        appended = put["body"]["game_event_parameters"][1]
        # Mirrors the live record shape of operator params.
        self.assertEqual(appended["path"], "extra")
        self.assertFalse(appended["system"])

    def test_add_params_skips_names_held_by_system_params(self):
        # Kinoa auto-adds device_id/time/time_ms (system: true) to every event —
        # a same-named operator param must be skipped, not duplicated.
        event = {"id": EVENT_ID, "name": "level_up", "status": "ACTIVE",
                 "game_event_parameters": [{"name": "time", "kind": "number", "system": True}]}
        ns = argparse.Namespace(event_id=EVENT_ID, param=["time:number"])
        code, result = self._call(self.mod.cmd_add_params, ns, [(200, json.dumps(event))])
        self.assertEqual(code, 0)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["skipped_existing"], ["time"])

    def test_add_params_noop_when_all_exist(self):
        event = {"id": EVENT_ID, "name": "level_up", "status": "ACTIVE",
                 "game_event_parameters": [{"name": "level", "kind": "number", "system": False}]}
        ns = argparse.Namespace(event_id=EVENT_ID, param=["level:number"])
        code, result = self._call(self.mod.cmd_add_params, ns, [(200, json.dumps(event))])
        self.assertEqual(code, 0)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["skipped_existing"], ["level"])
        # Only the GET fired — no mutation when nothing to add.
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_add_params_requires_at_least_one_param(self):
        ns = argparse.Namespace(event_id=EVENT_ID, param=[])
        code, result = self._call(self.mod.cmd_add_params, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "no_params")
        self.assertEqual(self.requests, [])

    def test_add_params_propagates_fetch_failure(self):
        ns = argparse.Namespace(event_id=EVENT_ID, param=["score:number"])
        code, result = self._call(self.mod.cmd_add_params, ns, [(404, "")])
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "fetch_failed")

    def test_add_params_put_failure_returns_exit_1_with_payload(self):
        event = {"id": EVENT_ID, "name": "level_up", "status": "ACTIVE", "game_event_parameters": []}
        ns = argparse.Namespace(event_id=EVENT_ID, param=["score:number"])
        # GET ok, PUT fails 500.
        code, result = self._call(self.mod.cmd_add_params, ns,
                                  [(200, json.dumps(event)), (500, "boom")])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 500)
        self.assertEqual([p["name"] for p in result["added"]], ["score"])
        self.assertEqual([r["method"] for r in self.requests], ["GET", "PUT"])

    def test_add_params_unexpected_event_shape_exit_1(self):
        ns = argparse.Namespace(event_id=EVENT_ID, param=["score:number"])
        # GET returns a JSON list, not an event object → guarded, no PUT issued.
        code, result = self._call(self.mod.cmd_add_params, ns, [(200, json.dumps([1, 2, 3]))])
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "unexpected_event_shape")
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_add_params_invalid_spec_exit_2_no_request(self):
        ns = argparse.Namespace(event_id=EVENT_ID, param=["bad:datetime"])
        code, result = self._call(self.mod.cmd_add_params, ns, [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_param")
        self.assertEqual(self.requests, [])

    def test_add_params_enumeration_carries_extra_and_path(self):
        event = {"id": EVENT_ID, "name": "level_up", "status": "ACTIVE", "game_event_parameters": []}
        ns = argparse.Namespace(event_id=EVENT_ID, param=["tier:enumeration:bronze,silver,gold"])
        code, result = self._call(self.mod.cmd_add_params, ns,
                                  [(200, json.dumps(event)), (200, json.dumps({"ok": True}))])
        self.assertEqual(code, 0)
        # Appended row carries BOTH the enumeration values (extra) AND path="extra" — two
        # distinct uses of the word "extra" that must not be conflated by a future refactor.
        put_body = self.requests[1]["body"]
        appended = put_body["game_event_parameters"][-1]
        self.assertEqual(appended["name"], "tier")
        self.assertEqual(appended["kind"], "enumeration")
        self.assertEqual(appended["extra"], "bronze,silver,gold")
        self.assertEqual(appended["path"], "extra")

    # ---- CLI wiring ----

    def test_main_parses_add_params_subcommand(self):
        self._mock_request([(200, json.dumps({"id": EVENT_ID, "name": "x",
                                              "game_event_parameters": []})),
                            (200, json.dumps({"ok": True}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["add-params", "--event-id", EVENT_ID, "--param", "score:number"])
        self.assertEqual(code, 0)

    # ---- cross-game guard (--expect-game) ----

    def test_expect_game_mismatch_aborts_before_any_request(self):
        # session.env game (set in setUp) != --expect-game → abort before the DELETE.
        self._mock_request([])  # any request would raise IndexError — proves none fired
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["delete", "--event-id", EVENT_ID,
                           "--expect-game", "99999999-9999-9999-9999-999999999999"])
        self.assertEqual(cm.exception.code, 2)
        result = json.loads(out.getvalue())
        self.assertEqual(result["error"], "session_game_mismatch")
        self.assertEqual(self.requests, [])

    def test_expect_game_match_proceeds(self):
        # --expect-game equal to session.env game → guard passes, DELETE fires.
        self._mock_request([(200, json.dumps({"ok": True}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["delete", "--event-id", EVENT_ID,
                                  "--expect-game", os.environ["KINOA_GAME_ID"]])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "DELETE")

    def test_expect_game_is_case_insensitive_and_trims(self):
        self._mock_request([(200, json.dumps({"ok": True}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["delete", "--event-id", EVENT_ID,
                                  "--expect-game", "  " + os.environ["KINOA_GAME_ID"].upper() + "  "])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "DELETE")


if __name__ == "__main__":
    unittest.main()
