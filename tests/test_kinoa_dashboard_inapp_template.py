"""Offline unit tests for
plugin/skills/kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py.

No network — `_request` is monkeypatched. No credentials — HOME is redirected at
a temp dir so the import-time session.env read can't touch a real ~/.kinoa.
Run from the repo root:

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
import urllib.parse
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(
    REPO_ROOT, "plugin", "skills", "kinoa-dashboard-inapp-template",
    "kinoa_dashboard_inapp_template.py",
)

TEMPLATE_ID = "44444444-4444-4444-4444-444444444444"
GAME_ID = "11111111-1111-1111-1111-111111111111"
OTHER_GAME_ID = "99999999-9999-9999-9999-999999999999"

DEFAULT_BASE = "https://dashboard.kinoa.io/api/message_templates"


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_dashboard_inapp_template_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _builder_payload(**overrides):
    """The shape inapp_template_build.py `build` emits: camelCase (the canonical
    template model), standard feature type ⇒ features: null, and a gameId when
    --game-id was passed. Under Key-Inflection: camel this IS the wire form, so
    the helper passes it through byte-for-byte apart from the normalizations."""
    payload = {
        "name": "Summer Offer",
        "key": "summer_offer",
        "description": "",
        "images": [{"key": "background", "index": 0}],
        "buttons": [{
            "key": "cta_button",
            "index": 1,
            "clickActionType": "open_shop",
            "customCtaNames": ["Buy now"],
            "canBeHidden": True,
            "customFields": [{"key": "sku", "defaultValue": "pack_A",
                              "enumValues": ["packA", "packB"]}],
        }],
        "texts": [{"key": "headline", "index": 2, "textLimit": 40, "nullable": False}],
        "customs": [],
        "featureType": "standard",
        "features": None,
    }
    payload.update(overrides)
    return payload


def _stored_record(**overrides):
    """A stored DRAFT template as the by-id GET returns it under
    Key-Inflection: camel — same slot keys as _builder_payload, so the default
    pairing yields an empty slot diff."""
    record = {
        "id": TEMPLATE_ID,
        "name": "Summer Offer",
        "status": "draft",
        "system": False,
        "availableActions": ["show", "update", "clone", "delete"],
        "images": [{"key": "background", "index": 0}],
        "buttons": [{"key": "cta_button", "index": 1}],
        "texts": [{"key": "headline", "index": 2}],
        "customs": [],
    }
    record.update(overrides)
    return record


class InAppTemplateHelperTests(unittest.TestCase):
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
        os.environ["KINOA_GAME_ID"] = GAME_ID
        self.requests = []
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    # ---- harness ----

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

    def _main(self, argv, responses):
        self._mock_request(responses)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(argv)
        return code, json.loads(out.getvalue())

    def _payload_file(self, payload, name="payload.json"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def _update_ns(self, path, **overrides):
        ns = dict(id=TEMPLATE_ID, payload=path, allow_referenced=False,
                  allow_slot_removal=False, dry_run=False)
        ns.update(overrides)
        return argparse.Namespace(**ns)

    def _update_responses(self, record=None, referenced=False, patch=(200, "{}")):
        """The three calls a guarded update makes: pre-flight GET, has-related
        probe, PATCH."""
        record = _stored_record() if record is None else record
        return [
            (200, json.dumps(record)),
            (200, json.dumps({"hasRelatedInAppMessages": referenced})),
            patch,
        ]

    def _list_ns(self, **overrides):
        ns = dict(page=1, rows=20, sort_by="updated_at", sort_direction="desc", status=[])
        ns.update(overrides)
        return argparse.Namespace(**ns)

    # ---- list ----

    def test_list_default_query(self):
        code, _ = self._call(self.mod.cmd_list, self._list_ns(),
                             [(200, json.dumps({"list": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        self.assertTrue(url.startswith(DEFAULT_BASE + "?"))
        self.assertIn("page=1", url)
        self.assertIn("rows=20", url)
        self.assertIn("sort_by=updated_at", url)
        self.assertIn("sort_direction=desc", url)
        # no status filter ⇒ neither the values nor the selectedFilters switch
        keys = [k for k, _ in urllib.parse.parse_qsl(url.split("?", 1)[1])]
        self.assertEqual(keys, ["page", "rows", "sort_by", "sort_direction"])
        self.assertEqual(self.requests[0]["method"], "GET")

    def test_list_repeatable_status_adds_selected_filters_switch(self):
        code, _ = self._call(self.mod.cmd_list, self._list_ns(status=["draft", "active"]),
                             [(200, json.dumps({"list": []}))])
        self.assertEqual(code, 0)
        url = self.requests[0]["url"]
        # brackets stay literal (byte-for-byte with the observed dashboard request)
        self.assertIn("selectedFilters[]=status", url)
        self.assertIn("status[]=draft", url)
        self.assertIn("status[]=active", url)
        self.assertNotIn("%5B%5D", url)

    def test_list_single_status_still_carries_selected_filters(self):
        # The values alone are ignored server-side without the switch — one
        # status must not be a special case.
        self._call(self.mod.cmd_list, self._list_ns(status=["draft"]), [(200, json.dumps({"list": []}))])
        url = self.requests[0]["url"]
        self.assertIn("selectedFilters[]=status", url)
        self.assertIn("status[]=draft", url)

    def test_list_paging_and_sort_overrides(self):
        self._call(self.mod.cmd_list, self._list_ns(page=3, rows=50, sort_by="name", sort_direction="asc"),
                   [(200, json.dumps({"list": []}))])
        url = self.requests[0]["url"]
        self.assertIn("page=3", url)
        self.assertIn("rows=50", url)
        self.assertIn("sort_by=name", url)
        self.assertIn("sort_direction=asc", url)

    def test_list_serializes_http_error(self):
        code, result = self._call(self.mod.cmd_list, self._list_ns(),
                                  [(401, json.dumps({"message": "expired"}))])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 401)
        self.assertEqual(result["response"], {"message": "expired"})

    def test_list_serializes_transport_failure_as_status_zero(self):
        code, result = self._call(self.mod.cmd_list, self._list_ns(),
                                  [(0, "URLError: [Errno 8] nodename nor servname provided")])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 0)
        self.assertIn("URLError", result["response"])

    # ---- get ----

    def test_get_hits_id_route(self):
        record = {"id": TEMPLATE_ID, "name": "Summer Offer", "status": "draft"}
        code, result = self._call(self.mod.cmd_get, argparse.Namespace(id=TEMPLATE_ID),
                                  [(200, json.dumps(record))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "GET")
        self.assertEqual(self.requests[0]["url"], f"{DEFAULT_BASE}/{TEMPLATE_ID}")
        self.assertEqual(result["id"], TEMPLATE_ID)
        self.assertEqual(result["response"], record)

    def test_get_404_serialized(self):
        code, result = self._call(self.mod.cmd_get, argparse.Namespace(id=TEMPLATE_ID),
                                  [(404, json.dumps({"message": "not found"}))])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 404)

    def test_falsy_json_body_stays_parsed(self):
        # An empty-object 200 body must come through as {} (parsed), not the
        # string "{}" — `{} or raw` would have swapped it for the raw string.
        code, result = self._call(self.mod.cmd_get, argparse.Namespace(id=TEMPLATE_ID), [(200, "{}")])
        self.assertEqual(code, 0)
        self.assertEqual(result["response"], {})

    # ---- create ----

    def test_create_posts_normalized_body(self):
        path = self._payload_file(_builder_payload(gameId=GAME_ID))
        code, result = self._call(self.mod.cmd_create, argparse.Namespace(payload=path),
                                  [(200, json.dumps({"id": TEMPLATE_ID, "status": "draft"}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "POST")
        self.assertEqual(self.requests[0]["url"], DEFAULT_BASE)
        body = self.requests[0]["body"]
        # gameId stripped — the server derives it from the Game-Id header
        self.assertNotIn("gameId", body)
        self.assertNotIn("game_id", body)
        # tagsIds defaulted, in the canonical camelCase spelling
        self.assertEqual(body["tagsIds"], [])
        # standard + features:null ⇒ {} (the create contract)
        self.assertEqual(body["features"], {})
        # keys stay camelCase — that is the wire form under Key-Inflection: camel
        self.assertEqual(body["featureType"], "standard")
        self.assertEqual(body["key"], "summer_offer")
        self.assertEqual(len(body["images"]), 1)
        # the request body is echoed for the caller/report
        self.assertEqual(result["request_body"], body)

    def test_create_keeps_existing_tags_ids(self):
        path = self._payload_file(_builder_payload(tagsIds=["tag-1", "tag-2"]))
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        self.assertEqual(self.requests[0]["body"]["tagsIds"], ["tag-1", "tag-2"])

    def test_create_null_tags_ids_becomes_empty_list(self):
        path = self._payload_file(_builder_payload(tagsIds=None))
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        self.assertEqual(self.requests[0]["body"]["tagsIds"], [])

    def test_create_non_standard_feature_block_preserved(self):
        mission = {"mission": {"missionCount": 3, "description": ""}}
        path = self._payload_file(_builder_payload(featureType="mission", features=mission))
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        # the block survives byte-for-byte, camelCase keys included
        self.assertEqual(self.requests[0]["body"]["features"], mission)
        self.assertEqual(self.requests[0]["body"]["featureType"], "mission")

    def test_create_non_standard_null_features_left_alone(self):
        # Only "standard" gets the null→{} rewrite; a malformed mission payload
        # must reach the server as-is so its validation speaks, not ours.
        path = self._payload_file(_builder_payload(featureType="mission", features=None))
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        self.assertIsNone(self.requests[0]["body"]["features"])

    def test_create_reads_payload_from_stdin(self):
        payload = _builder_payload()
        self._mock_request([(200, json.dumps({"id": TEMPLATE_ID}))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))):
                code = self.mod.cmd_create(argparse.Namespace(payload="-"))
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["body"]["key"], "summer_offer")

    def test_create_missing_payload_file_exits_2_without_request(self):
        code, result = self._call(self.mod.cmd_create,
                                  argparse.Namespace(payload=os.path.join(self._tmp.name, "nope.json")), [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "payload_read_failed")
        self.assertEqual(self.requests, [])

    def test_create_invalid_json_exits_2_without_request(self):
        path = os.path.join(self._tmp.name, "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        code, result = self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_payload_json")
        self.assertEqual(self.requests, [])

    def test_create_list_payload_exits_2_without_request(self):
        path = self._payload_file([1, 2, 3], name="list.json")
        code, result = self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_payload")
        self.assertEqual(self.requests, [])

    def test_create_serializes_http_error(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_create, argparse.Namespace(payload=path),
                                  [(422, json.dumps({"message": "key already exists"}))])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 422)
        # the attempted body is still reported so the operator can see what was sent
        self.assertEqual(result["request_body"]["key"], "summer_offer")

    # ---- camelCase passthrough + the Key-Inflection header ----

    def test_create_body_passes_through_in_camel_case(self):
        path = self._payload_file(_builder_payload(gameId=GAME_ID))
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path),
                   [(200, json.dumps({"id": TEMPLATE_ID}))])
        body = self.requests[0]["body"]
        button = body["buttons"][0]
        text = body["texts"][0]
        # camelCase survives byte-for-byte — no conversion anywhere
        self.assertEqual(button["clickActionType"], "open_shop")
        self.assertEqual(button["customCtaNames"], ["Buy now"])
        self.assertTrue(button["canBeHidden"])
        self.assertEqual(button["customFields"][0]["defaultValue"], "pack_A")
        self.assertEqual(button["customFields"][0]["enumValues"], ["packA", "packB"])
        self.assertEqual(text["textLimit"], 40)
        self.assertEqual(body["featureType"], "standard")

    def test_create_body_differs_from_payload_only_by_normalizations(self):
        # The strongest passthrough statement: the sent body IS the payload,
        # modulo the three documented normalizations.
        payload = _builder_payload(gameId=GAME_ID)
        path = self._payload_file(payload)
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        expected = {k: v for k, v in payload.items() if k != "gameId"}
        expected["features"] = {}
        expected["tagsIds"] = []
        self.assertEqual(self.requests[0]["body"], expected)

    def test_every_subcommand_sends_key_inflection_camel(self):
        # LOAD-BEARING: without this header the API answers snake_case and a
        # camelCase body is silently dropped on a 200.
        path = self._payload_file(_builder_payload())
        cases = [
            ["list"],
            ["get", "--id", TEMPLATE_ID],
            ["create", "--payload", path],
            ["update", "--id", TEMPLATE_ID, "--payload", path],
            ["has-related", "--id", TEMPLATE_ID],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.requests = []
                self._main(argv, [(200, json.dumps({"list": []}))])
                self.assertEqual(self.requests[0]["headers"]["Key-Inflection"], "camel")

    def test_snake_payload_still_gets_contract_normalizations(self):
        # A body read back from a headerless call is snake_case; it must not
        # grow a duplicate tagsIds/features key when re-sent.
        snake = {"name": "N", "key": "k", "feature_type": "standard", "features": None,
                 "game_id": GAME_ID}
        path = self._payload_file(snake, name="snake.json")
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        body = self.requests[0]["body"]
        self.assertEqual(body["features"], {})
        self.assertEqual(body["tagsIds"], [])
        self.assertNotIn("game_id", body)

    def test_snake_tags_ids_not_duplicated(self):
        snake = {"name": "N", "key": "k", "feature_type": "standard",
                 "features": {}, "tags_ids": ["t1"]}
        path = self._payload_file(snake, name="snake_tags.json")
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        body = self.requests[0]["body"]
        self.assertEqual(body["tags_ids"], ["t1"])
        self.assertNotIn("tagsIds", body)

    def test_both_game_id_spellings_stripped(self):
        path = self._payload_file(_builder_payload(gameId=GAME_ID, game_id=GAME_ID),
                                  name="bothgame.json")
        self._call(self.mod.cmd_create, argparse.Namespace(payload=path), [(200, "{}")])
        body = self.requests[0]["body"]
        self.assertNotIn("game_id", body)
        self.assertNotIn("gameId", body)

    def test_no_case_conversion_helpers_remain(self):
        # The API inflects case via the header; a converter here would be a
        # second, conflicting source of truth.
        for gone in ("_snake_key", "_snake_keys", "_wire_body"):
            self.assertFalse(hasattr(self.mod, gone), gone)

    def test_normalize_payload_does_not_mutate_caller(self):
        original = _builder_payload(gameId=GAME_ID)
        snapshot = json.loads(json.dumps(original))
        normalized = self.mod._normalize_payload(original)
        self.assertEqual(original, snapshot)
        self.assertNotIn("gameId", normalized)

    # ---- update ----

    def test_update_patches_id_route_with_normalized_body(self):
        path = self._payload_file(_builder_payload(gameId=GAME_ID, name="Edited"))
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  self._update_responses())
        self.assertEqual(code, 0)
        self.assertEqual([r["method"] for r in self.requests], ["GET", "GET", "PATCH"])
        self.assertEqual(self.requests[2]["url"], f"{DEFAULT_BASE}/{TEMPLATE_ID}")
        body = self.requests[2]["body"]
        self.assertNotIn("gameId", body)
        self.assertNotIn("game_id", body)
        self.assertEqual(body["tagsIds"], [])
        self.assertEqual(body["features"], {})
        self.assertEqual(body["buttons"][0]["clickActionType"], "open_shop")
        self.assertEqual(result["id"], TEMPLATE_ID)
        self.assertEqual(result["request_body"], body)
        self.assertEqual(result["slot_diff"], {"added": {}, "removed": {}})
        self.assertTrue(all(g["passed"] for g in result["guards"].values()))

    def test_update_is_deliberately_multi_call(self):
        # Guarded update = pre-flight GET + has-related probe + PATCH. The
        # deviation from one-call-per-subcommand is deliberate (precedent:
        # resource-template's GET + merged PUT).
        path = self._payload_file(_builder_payload())
        self._call(self.mod.cmd_update, self._update_ns(path), self._update_responses())
        self.assertEqual([r["method"] for r in self.requests], ["GET", "GET", "PATCH"])
        self.assertEqual(self.requests[0]["url"], f"{DEFAULT_BASE}/{TEMPLATE_ID}")
        self.assertTrue(self.requests[1]["url"].endswith("/has_related_in_app_messages"))

    def test_update_missing_payload_exits_2_without_request(self):
        code, result = self._call(
            self.mod.cmd_update,
            self._update_ns(os.path.join(self._tmp.name, "nope.json")), [])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "payload_read_failed")
        self.assertEqual(self.requests, [])

    # ---- update guard ladder ----

    def _assert_no_patch(self):
        self.assertNotIn("PATCH", [r["method"] for r in self.requests])

    def test_update_refuses_system_template(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  [(200, json.dumps(_stored_record(system=True)))])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "system_template")
        self.assertIsNone(result["override"])  # absolute
        self._assert_no_patch()

    def test_update_refuses_non_draft(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  [(200, json.dumps(_stored_record(status="active")))])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "not_draft")
        self.assertIsNone(result["override"])
        self.assertEqual(result["guards"]["status"]["value"], "active")
        self._assert_no_patch()

    def test_update_refuses_when_available_actions_omit_update(self):
        # Production: an ACTIVE non-system template offers
        # show/clone/deprecate/export_to_game/hide — no update.
        record = _stored_record(
            availableActions=["show", "clone", "deprecate", "export_to_game", "hide"])
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  [(200, json.dumps(record))])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "update_not_available")
        self.assertIsNone(result["override"])
        self._assert_no_patch()

    def test_update_absolute_guards_ignore_override_flags(self):
        path = self._payload_file(_builder_payload())
        for record, reason in (
            (_stored_record(system=True), "system_template"),
            (_stored_record(status="active"), "not_draft"),
            (_stored_record(availableActions=["show", "clone"]), "update_not_available"),
        ):
            with self.subTest(reason=reason):
                self.requests = []
                code, result = self._call(
                    self.mod.cmd_update,
                    self._update_ns(path, allow_referenced=True, allow_slot_removal=True),
                    [(200, json.dumps(record))])
                self.assertEqual(code, 1)
                self.assertEqual(result["reason"], reason)
                self._assert_no_patch()

    def test_update_missing_available_actions_is_not_a_refusal(self):
        # Not every deployment sends the field; absence must not block.
        record = _stored_record()
        record.pop("availableActions")
        path = self._payload_file(_builder_payload())
        code, _ = self._call(self.mod.cmd_update, self._update_ns(path),
                             self._update_responses(record=record))
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[-1]["method"], "PATCH")

    def test_update_refuses_referenced_template(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  self._update_responses(referenced=True))
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "template_referenced")
        self.assertEqual(result["override"], "--allow-referenced")
        self._assert_no_patch()

    def test_allow_referenced_override_proceeds(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update,
                                  self._update_ns(path, allow_referenced=True),
                                  self._update_responses(referenced=True))
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[-1]["method"], "PATCH")
        self.assertTrue(result["guards"]["referenced"]["overridden"])

    def test_update_refuses_when_reference_check_fails(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  [(200, json.dumps(_stored_record())), (500, "boom")])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "reference_check_failed")
        self.assertEqual(result["override"], "--allow-referenced")
        self._assert_no_patch()

    def test_reference_check_failure_overridable(self):
        path = self._payload_file(_builder_payload())
        code, _ = self._call(self.mod.cmd_update,
                             self._update_ns(path, allow_referenced=True),
                             [(200, json.dumps(_stored_record())), (500, "boom"), (200, "{}")])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[-1]["method"], "PATCH")

    def test_update_refuses_slot_removal_and_lists_keys(self):
        # The body drops the stored button — a full-body PATCH would wipe it.
        payload = _builder_payload(buttons=[])
        path = self._payload_file(payload, name="noslots.json")
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  self._update_responses())
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "slot_removal")
        self.assertEqual(result["override"], "--allow-slot-removal")
        self.assertEqual(result["slot_diff"]["removed"], {"buttons": ["cta_button"]})
        self.assertEqual(result["slot_diff"]["added"], {})
        self._assert_no_patch()

    def test_allow_slot_removal_override_proceeds(self):
        path = self._payload_file(_builder_payload(buttons=[]), name="noslots2.json")
        code, result = self._call(self.mod.cmd_update,
                                  self._update_ns(path, allow_slot_removal=True),
                                  self._update_responses())
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[-1]["method"], "PATCH")
        self.assertEqual(result["slot_diff"]["removed"], {"buttons": ["cta_button"]})
        self.assertTrue(result["guards"]["slot_removal"]["overridden"])

    def test_update_reports_added_keys_without_refusing(self):
        payload = _builder_payload()
        payload["texts"] = payload["texts"] + [{"key": "subhead", "index": 3}]
        path = self._payload_file(payload, name="added.json")
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  self._update_responses())
        self.assertEqual(code, 0)
        self.assertEqual(result["slot_diff"]["added"], {"texts": ["subhead"]})
        self.assertEqual(result["slot_diff"]["removed"], {})

    def test_update_slot_diff_covers_every_bucket(self):
        record = _stored_record(
            images=[{"key": "bg"}], buttons=[{"key": "b1"}],
            texts=[{"key": "t1"}], customs=[{"key": "c1"}])
        payload = _builder_payload(images=[], buttons=[], texts=[], customs=[])
        path = self._payload_file(payload, name="allgone.json")
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  self._update_responses(record=record))
        self.assertEqual(code, 1)
        self.assertEqual(result["slot_diff"]["removed"],
                         {"images": ["bg"], "buttons": ["b1"],
                          "texts": ["t1"], "customs": ["c1"]})

    # ---- update --dry-run ----

    def test_dry_run_does_not_patch(self):
        path = self._payload_file(_builder_payload(gameId=GAME_ID))
        code, result = self._call(self.mod.cmd_update, self._update_ns(path, dry_run=True),
                                  self._update_responses())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual([r["method"] for r in self.requests], ["GET", "GET"])
        self._assert_no_patch()
        # would_send is the normalized camelCase body
        self.assertEqual(result["would_send"]["tagsIds"], [])
        self.assertNotIn("gameId", result["would_send"])
        self.assertEqual(result["would_send"]["buttons"][0]["clickActionType"], "open_shop")
        self.assertEqual(result["slot_diff"], {"added": {}, "removed": {}})
        self.assertIn("guards", result)

    def test_dry_run_still_refuses_on_a_failing_guard(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path, dry_run=True),
                                  [(200, json.dumps(_stored_record(status="active")))])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "not_draft")
        self._assert_no_patch()

    # ---- update pre-flight failures ----

    def test_update_preflight_fetch_failure_refuses(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  [(404, json.dumps({"message": "not found"}))])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "preflight_fetch_failed")
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_update_preflight_unexpected_shape_refuses(self):
        path = self._payload_file(_builder_payload())
        code, result = self._call(self.mod.cmd_update, self._update_ns(path),
                                  [(200, json.dumps([1, 2, 3]))])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "unexpected_template_shape")
        self._assert_no_patch()

    # ---- slot helpers ----

    def test_slot_keys_tolerates_malformed_buckets(self):
        keys = self.mod._slot_keys({"images": None, "buttons": [{"noKey": 1}, {"key": "b"}],
                                    "texts": "nonsense"})
        self.assertEqual(keys, {"images": [], "buttons": ["b"], "texts": [], "customs": []})

    def test_slot_diff_both_directions(self):
        diff = self.mod._slot_diff({"buttons": [{"key": "a"}, {"key": "b"}]},
                                   {"buttons": [{"key": "b"}, {"key": "c"}]})
        self.assertEqual(diff["removed"], {"buttons": ["a"]})
        self.assertEqual(diff["added"], {"buttons": ["c"]})

    # ---- has-related ----

    def test_has_related_true_flattened(self):
        # Under Key-Inflection: camel the response key is camelCase.
        code, result = self._call(self.mod.cmd_has_related, argparse.Namespace(id=TEMPLATE_ID),
                                  [(200, json.dumps({"hasRelatedInAppMessages": True}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "GET")
        self.assertEqual(self.requests[0]["url"],
                         f"{DEFAULT_BASE}/{TEMPLATE_ID}/has_related_in_app_messages")
        self.assertTrue(result["has_related"])
        self.assertEqual(result["response"], {"hasRelatedInAppMessages": True})

    def test_has_related_false_flattened(self):
        code, result = self._call(self.mod.cmd_has_related, argparse.Namespace(id=TEMPLATE_ID),
                                  [(200, json.dumps({"hasRelatedInAppMessages": False}))])
        self.assertEqual(code, 0)
        self.assertIn("has_related", result)
        self.assertFalse(result["has_related"])

    def test_has_related_accepts_snake_case_fallback(self):
        # A headerless deployment answers snake_case — still flattened.
        code, result = self._call(self.mod.cmd_has_related, argparse.Namespace(id=TEMPLATE_ID),
                                  [(200, json.dumps({"has_related_in_app_messages": True}))])
        self.assertEqual(code, 0)
        self.assertTrue(result["has_related"])

    def test_has_related_unexpected_shape_omits_flattened_key(self):
        code, result = self._call(self.mod.cmd_has_related, argparse.Namespace(id=TEMPLATE_ID),
                                  [(200, json.dumps({"other": 1}))])
        self.assertEqual(code, 0)
        self.assertNotIn("has_related", result)

    def test_has_related_serializes_http_error(self):
        code, result = self._call(self.mod.cmd_has_related, argparse.Namespace(id=TEMPLATE_ID),
                                  [(500, "boom")])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["response"], "boom")

    # ---- hardcoded production base URL ----

    def test_every_subcommand_hits_production_base_url(self):
        # One supported target, hardcoded — no flag, no env override.
        path = self._payload_file(_builder_payload())
        cases = [
            (["list"], DEFAULT_BASE + "?"),
            (["get", "--id", TEMPLATE_ID], f"{DEFAULT_BASE}/{TEMPLATE_ID}"),
            (["create", "--payload", path], DEFAULT_BASE),
            (["update", "--id", TEMPLATE_ID, "--payload", path], f"{DEFAULT_BASE}/{TEMPLATE_ID}"),
            (["has-related", "--id", TEMPLATE_ID],
             f"{DEFAULT_BASE}/{TEMPLATE_ID}/has_related_in_app_messages"),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.requests = []
                self._main(argv, [(200, json.dumps({"list": []}))])
                url = self.requests[0]["url"]
                if expected.endswith("?"):
                    self.assertTrue(url.startswith(expected), url)
                else:
                    self.assertEqual(url, expected)

    def test_base_url_is_a_plain_module_constant(self):
        self.assertEqual(self.mod.MESSAGE_TEMPLATES_URL, DEFAULT_BASE)
        # no override machinery of any kind
        for gone in ("_base_url", "DEFAULT_MESSAGE_TEMPLATES_URL",
                     "OBSERVED_TEST_MESSAGE_TEMPLATES_URL", "BASE_URL_ENV_VAR"):
            self.assertFalse(hasattr(self.mod, gone), gone)

    # ---- no delete, by design ----

    def test_no_delete_subcommand(self):
        # Deliberate omission: a template with related in-app messages must never
        # be deleted, and the decision was to keep delete out of the tooling.
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            self.mod.main(["delete", "--id", TEMPLATE_ID])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("invalid choice", err.getvalue())

    def test_no_delete_command_function_exists(self):
        self.assertFalse(hasattr(self.mod, "cmd_delete"))

    def test_helper_never_issues_a_delete_verb(self):
        with open(SCRIPT_PATH, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn('"DELETE"', source)
        self.assertNotIn("'DELETE'", source)

    # ---- cross-game guard (--expect-game) ----

    def test_expect_game_mismatch_aborts_create_before_any_request(self):
        path = self._payload_file(_builder_payload())
        self._mock_request([])  # any request would raise IndexError — proves none fired
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["create", "--payload", path, "--expect-game", OTHER_GAME_ID])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "session_game_mismatch")
        self.assertEqual(self.requests, [])

    def test_expect_game_guards_update(self):
        path = self._payload_file(_builder_payload())
        self._mock_request([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["update", "--id", TEMPLATE_ID, "--payload", path,
                           "--expect-game", OTHER_GAME_ID])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.requests, [])

    def test_expect_game_match_proceeds(self):
        path = self._payload_file(_builder_payload())
        code, _ = self._main(["create", "--payload", path, "--expect-game", GAME_ID],
                             [(200, json.dumps({"id": TEMPLATE_ID}))])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[0]["method"], "POST")

    def test_empty_expect_game_aborts(self):
        path = self._payload_file(_builder_payload())
        self._mock_request([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod.main(["create", "--payload", path, "--expect-game", "  "])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "empty_expect_game")

    # ---- credentials / headers ----

    def test_admin_headers_carry_bearer_and_both_game_headers(self):
        headers = self.mod._admin_headers()
        self.assertEqual(headers["Authorization"], "Bearer FAKE_TOKEN")
        self.assertEqual(headers["Game"], GAME_ID)
        self.assertEqual(headers["Game-Id"], GAME_ID)
        self.assertEqual(headers["Key-Inflection"], "camel")

    def test_missing_credentials_exits_2(self):
        os.environ.pop("KINOA_BEARER_TOKEN")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            self.mod._admin_headers()
        self.assertEqual(cm.exception.code, 2)
        result = json.loads(out.getvalue())
        self.assertEqual(result["error"], "missing_credentials")
        self.assertIn("KINOA_BEARER_TOKEN", result["missing"])

    # ---- CLI wiring ----

    def test_main_parses_every_subcommand(self):
        path = self._payload_file(_builder_payload())
        ok = [(200, json.dumps({"list": []}))]
        cases = [
            (["list"], "GET", ok),
            (["get", "--id", TEMPLATE_ID], "GET", ok),
            (["create", "--payload", path], "POST", ok),
            # update's first call is its pre-flight GET (guard ladder), then the
            # has-related probe, then the PATCH
            (["update", "--id", TEMPLATE_ID, "--payload", path], "GET",
             self._update_responses()),
            (["has-related", "--id", TEMPLATE_ID], "GET", ok),
        ]
        for argv, verb, responses in cases:
            with self.subTest(argv=argv):
                self.requests = []
                code, _ = self._main(argv, responses)
                self.assertEqual(code, 0)
                self.assertEqual(self.requests[0]["method"], verb)

    def test_subcommand_required(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            self.mod.main([])


if __name__ == "__main__":
    unittest.main()
