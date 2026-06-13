"""Offline unit tests for skills/kinoa-sdk-dashboard-sync/kinoa_sdk_sync_plan.py.

Pure planner — no network by design. Run from the repo root:

    python -m unittest discover tests -v
"""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-sdk-dashboard-sync", "kinoa_sdk_sync_plan.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_sdk_sync_plan_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest(**overrides):
    base = {
        "schema_version": 1,
        "integration_type": "SDK",
        "events": {
            "predefined_in_use": [],
            "custom": [],
            "declined": [],
        },
        "player_fields": {
            "predefined_in_use": [],
            "custom": [],
        },
        "unsupported_by_cli": [],
    }
    base.update(overrides)
    return base


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def _plan(self, manifest, ev_predef=(), ev_custom=(), ev_deleted=(),
              pf_predef=(), pf_custom=(), pf_deleted=()):
        return self.mod.build_plan(manifest, list(ev_predef), list(ev_custom), list(ev_deleted),
                                   list(pf_predef), list(pf_custom), list(pf_deleted))

    # ---- events: predefined ----

    def test_predefined_event_not_implemented_planned_as_publish(self):
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{"name": "session_start", "transport": "sync"}]
        plan = self._plan(manifest, ev_predef=[{"id": "e1", "name": "session_start",
                                                "status": "NOT_IMPLEMENTED", "game_event_parameters": []}])
        self.assertEqual([e["name"] for e in plan["events"]["publish"]], ["session_start"])
        self.assertEqual(plan["events"]["create"], [])

    def test_predefined_event_active_is_already_ok(self):
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{"name": "install"}]
        plan = self._plan(manifest, ev_predef=[{"id": "e1", "name": "install", "status": "ACTIVE"}])
        self.assertEqual(plan["events"]["publish"], [])
        self.assertEqual([e["name"] for e in plan["events"]["already_ok"]], ["install"])

    def test_predefined_event_missing_on_dashboard_warns(self):
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{"name": "no_such_event"}]
        plan = self._plan(manifest)
        self.assertEqual([w["name"] for w in plan["events"]["warnings"]], ["no_such_event"])

    def test_predefined_event_missing_custom_params_planned_as_add_params(self):
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{
            "name": "payment",
            "custom_params": [{"name": "pack_id", "kind": "string"},
                              {"name": "level", "kind": "number"}],
        }]
        record = {"id": "e9", "name": "payment", "status": "ACTIVE",
                  "game_event_parameters": [{"name": "level", "kind": "number"}]}
        plan = self._plan(manifest, ev_predef=[record])
        add = plan["events"]["add_params"]
        self.assertEqual(len(add), 1)
        self.assertEqual(add[0]["id"], "e9")
        self.assertEqual([p["name"] for p in add[0]["params"]], ["pack_id"])

    # ---- events: custom ----

    def test_custom_event_absent_planned_as_create(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "gold_purchase",
                                         "params": [{"name": "amount", "kind": "number"}]}]
        plan = self._plan(manifest)
        self.assertEqual([e["name"] for e in plan["events"]["create"]], ["gold_purchase"])
        self.assertTrue(plan["events"]["create"][0]["send_to_analytics"])

    def test_deleted_custom_event_planned_as_publish_never_create(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "ftue_step", "params": []}]
        plan = self._plan(manifest, ev_deleted=[{"id": "e7", "name": "ftue_step", "state": "deleted"}])
        self.assertEqual(plan["events"]["create"], [])
        publishes = plan["events"]["publish"]
        self.assertEqual(len(publishes), 1)
        self.assertEqual(publishes[0]["id"], "e7")
        self.assertTrue(publishes[0]["was_deleted"])

    def test_custom_event_listed_unpublished_planned_as_publish_not_create(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "gold_purchase", "params": []}]
        record = {"id": "e9", "name": "gold_purchase", "status": "NOT_IMPLEMENTED"}
        plan = self._plan(manifest, ev_custom=[record])
        self.assertEqual(plan["events"]["create"], [])
        pub = plan["events"]["publish"]
        self.assertEqual(len(pub), 1)
        self.assertEqual(pub[0]["id"], "e9")
        self.assertIn("unpublished", pub[0]["reason"])

    def test_deleted_event_with_param_drift_publishes_and_addparams_with_reresolve(self):
        # Forward-compat branch (live has no deleted events): a soft-deleted event missing a
        # game-used param is published AND gets add_params, flagged to re-resolve its id after
        # publish (publish replaces the record under a new id).
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "ftue_step",
                                         "params": [{"name": "step", "kind": "number"}]}]
        deleted = {"id": "d1", "name": "ftue_step", "state": "deleted", "game_event_parameters": []}
        plan = self._plan(manifest, ev_deleted=[deleted])
        self.assertTrue(plan["events"]["publish"][0]["was_deleted"])
        add = plan["events"]["add_params"]
        self.assertEqual([p["name"] for p in add[0]["params"]], ["step"])
        self.assertTrue(add[0].get("resolve_id_after_publish"))

    def test_custom_event_case_collision_warns_but_still_plans_create(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "coloring_skipped", "params": []}]
        record = {"id": "e5", "name": "Coloring_skipped", "status": "ACTIVE",
                  "game_event_parameters": []}
        plan = self._plan(manifest, ev_custom=[record])
        warnings = plan["events"]["warnings"]
        self.assertTrue(any("case-collision" in w.get("reason", "") and
                            w.get("dashboard_name") == "Coloring_skipped" for w in warnings))
        # The planner stays pure — the warning informs the checklist; create is still planned.
        self.assertEqual([e["name"] for e in plan["events"]["create"]], ["coloring_skipped"])

    def test_system_param_collision_warns_on_create_and_add_params(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "booster_lifecycle",
                                         "params": [{"name": "time", "kind": "date"},
                                                    {"name": "booster_kind", "kind": "string"}]}]
        manifest["events"]["predefined_in_use"] = [{"name": "payment",
                                                    "custom_params": [{"name": "time_ms", "kind": "string"}]}]
        predef = {"id": "e1", "name": "payment", "status": "ACTIVE",
                  "game_event_parameters": [{"name": "device_id", "kind": "string", "system": True}]}
        plan = self._plan(manifest, ev_predef=[predef])
        collisions = [w for w in plan["events"]["warnings"] if "system-param collision" in w.get("reason", "")]
        self.assertEqual(sorted((w["name"], w["param"]) for w in collisions),
                         [("booster_lifecycle", "time"), ("payment", "time_ms")])
        # Advisory only: the create itself still goes ahead byte-for-byte.
        self.assertEqual([e["name"] for e in plan["events"]["create"]], ["booster_lifecycle"])

    def test_custom_field_case_collision_warns(self):
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"name": "Wallet.Gold", "path": "Wallet.gold",
                                                "kind": "number"}]
        record = {"id": "f5", "name": "Wallet.Gold", "path": "wallet.gold", "state": "active",
                  "kind": "number"}
        plan = self._plan(manifest, pf_custom=[record])
        warnings = plan["player_fields"]["warnings"]
        self.assertTrue(any("case-collision" in w.get("reason", "") and
                            w.get("dashboard_path") == "wallet.gold" for w in warnings))

    def test_custom_event_active_with_param_drift_adds_params_only(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "level_up",
                                         "params": [{"name": "level", "kind": "number"},
                                                    {"name": "duration", "kind": "number"}]}]
        record = {"id": "e2", "name": "level_up", "status": "ACTIVE",
                  "game_event_parameters": [{"name": "level", "kind": "number"}]}
        plan = self._plan(manifest, ev_custom=[record])
        self.assertEqual(plan["events"]["create"], [])
        self.assertEqual([e["name"] for e in plan["events"]["already_ok"]], ["level_up"])
        self.assertEqual([p["name"] for p in plan["events"]["add_params"][0]["params"]], ["duration"])

    def test_event_param_with_unsupported_kind_goes_to_unsupported(self):
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "purchase",
                                         "params": [{"name": "ts", "kind": "datetime"}]}]
        plan = self._plan(manifest)
        self.assertEqual(plan["events"]["create"][0]["params"], [])
        self.assertEqual(len(plan["unsupported"]), 1)
        self.assertEqual(plan["unsupported"][0]["name"], "ts")

    # ---- player fields ----

    def test_predefined_field_not_implemented_planned_as_activate(self):
        manifest = _manifest()
        manifest["player_fields"]["predefined_in_use"] = [{"path": "level"}]
        plan = self._plan(manifest, pf_predef=[{"id": "f1", "path": "level", "name": "Level",
                                                "state": "not_implemented"}])
        self.assertEqual([f["path"] for f in plan["player_fields"]["activate"]], ["level"])

    def test_custom_field_absent_planned_as_create(self):
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"property": "CustomString", "path": "custom_string",
                                                "kind": "string", "name": "CustomString",
                                                "default_value": "hello"}]
        plan = self._plan(manifest)
        creates = plan["player_fields"]["create"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["path"], "custom_string")
        self.assertEqual(creates[0]["kind"], "string")
        # The live API 422-rejects defaultValue for non-calculated fields —
        # the planner must never forward it into a create action.
        self.assertNotIn("default_value", creates[0])

    def test_add_params_flagged_when_event_also_published(self):
        # Publishing replaces the record under a NEW id — add_params planned against
        # a pre-publish id must carry the re-resolve flag.
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{
            "name": "payment",
            "custom_params": [{"name": "transaction_id", "kind": "string"}],
        }]
        record = {"id": "e1", "name": "payment", "status": "NOT_IMPLEMENTED",
                  "game_event_parameters": []}
        plan = self._plan(manifest, ev_predef=[record])
        self.assertEqual([e["name"] for e in plan["events"]["publish"]], ["payment"])
        add = plan["events"]["add_params"][0]
        self.assertTrue(add["resolve_id_after_publish"])

    def test_param_drift_detected_on_already_active_predefined(self):
        # An ACTIVE (already-published) predefined event with a missing custom param
        # must still produce an add_params action — "already published" never masks
        # param drift.
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{
            "name": "payment",
            "custom_params": [{"name": "transaction_id", "kind": "string"}],
        }]
        record = {"id": "e1", "name": "payment", "status": "ACTIVE",
                  "game_event_parameters": [{"name": "device_id", "kind": "string", "system": True}]}
        plan = self._plan(manifest, ev_predef=[record])
        self.assertEqual(plan["events"]["publish"], [])
        self.assertEqual([e["name"] for e in plan["events"]["already_ok"]], ["payment"])
        add = plan["events"]["add_params"]
        self.assertEqual(len(add), 1)
        self.assertEqual([p["name"] for p in add[0]["params"]], ["transaction_id"])

    def test_add_params_not_flagged_without_publish(self):
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{
            "name": "payment",
            "custom_params": [{"name": "transaction_id", "kind": "string"}],
        }]
        record = {"id": "e1", "name": "payment", "status": "ACTIVE",
                  "game_event_parameters": []}
        plan = self._plan(manifest, ev_predef=[record])
        self.assertEqual(plan["events"]["publish"], [])
        self.assertNotIn("resolve_id_after_publish", plan["events"]["add_params"][0])

    def test_deleted_custom_field_planned_as_activate_never_create(self):
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"path": "wallet.gold", "kind": "number"}]
        plan = self._plan(manifest, pf_deleted=[{"id": "f5", "path": "wallet.gold", "state": "deleted"}])
        self.assertEqual(plan["player_fields"]["create"], [])
        activates = plan["player_fields"]["activate"]
        self.assertEqual(activates[0]["id"], "f5")
        self.assertTrue(activates[0]["was_deleted"])

    def test_custom_field_unsupported_kind_goes_to_unsupported(self):
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"path": "profile.avatar", "kind": "object"}]
        plan = self._plan(manifest)
        self.assertEqual(plan["player_fields"]["create"], [])
        self.assertEqual(plan["unsupported"][0]["surface"], "player_field")

    def test_string_kind_field_is_registrable_create(self):
        # A Guid-backed field is mapped to kind "string" by the producer; the planner must treat
        # it as a normal registrable field (create), NOT shunt it to unsupported.
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"name": "LastClaimedRewardId",
                                                "path": "last_claimed_reward_id", "kind": "string"}]
        plan = self._plan(manifest)
        self.assertEqual([f["path"] for f in plan["player_fields"]["create"]], ["last_claimed_reward_id"])
        self.assertEqual(plan["unsupported"], [])

    def test_custom_event_colliding_with_predefined_warns_still_creates(self):
        # Producer misclassified a predefined event as custom: warn (advisory), still create
        # byte-for-byte — the developer decides at the checklist.
        manifest = _manifest()
        manifest["events"]["custom"] = [{"name": "session_start", "params": []}]
        predef = {"id": "p1", "name": "session_start", "status": "NOT_IMPLEMENTED"}
        plan = self._plan(manifest, ev_predef=[predef])
        self.assertTrue(any("PREDEFINED" in w.get("reason", "") for w in plan["events"]["warnings"]))
        self.assertEqual([e["name"] for e in plan["events"]["create"]], ["session_start"])

    def test_custom_field_colliding_with_predefined_warns(self):
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"name": "Level", "path": "level", "kind": "number"}]
        predef = {"id": "pf1", "name": "Level", "path": "level", "state": "active", "kind": "number"}
        plan = self._plan(manifest, pf_predef=[predef])
        self.assertTrue(any("PREDEFINED" in w.get("reason", "") for w in plan["player_fields"]["warnings"]))

    def test_custom_field_kind_drift_warns_still_already_ok(self):
        # Game now defines wallet.gold as a number, dashboard still has it as string (active).
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"path": "wallet.gold", "kind": "number"}]
        record = {"id": "f1", "path": "wallet.gold", "state": "active", "kind": "string"}
        plan = self._plan(manifest, pf_custom=[record])
        drift = [w for w in plan["player_fields"]["warnings"] if "kind drift" in w.get("reason", "")]
        self.assertEqual(len(drift), 1)
        self.assertEqual((drift[0]["manifest_kind"], drift[0]["dashboard_kind"]), ("number", "string"))
        # Still already_ok (presence holds; the helpers can't change kind anyway).
        self.assertEqual([f["path"] for f in plan["player_fields"]["already_ok"]], ["wallet.gold"])

    def test_custom_field_matching_kind_no_drift_warning(self):
        manifest = _manifest()
        manifest["player_fields"]["custom"] = [{"path": "wallet.gold", "kind": "number"}]
        record = {"id": "f1", "path": "wallet.gold", "state": "active", "kind": "number"}
        plan = self._plan(manifest, pf_custom=[record])
        self.assertEqual([w for w in plan["player_fields"]["warnings"] if "kind drift" in w.get("reason", "")], [])

    def test_planner_kind_vocab_matches_helpers(self):
        # FIELD_KINDS / EVENT_PARAM_KINDS must equal the helpers' allowed sets, or the planner
        # could plan creates the helper CLIs reject (or shunt supported kinds to manual).
        # Parsed via ast — no module import, so the helpers' import-time session.env read never fires.
        import ast

        def _const_set(rel, name):
            path = os.path.join(REPO_ROOT, *rel)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == name:
                            return set(ast.literal_eval(node.value))
            raise AssertionError(f"{name} not found in {path}")

        self.assertEqual(set(self.mod.EVENT_PARAM_KINDS),
                         _const_set(("skills", "kinoa-dashboard-event", "kinoa_dashboard_event.py"),
                                    "ALLOWED_PARAM_KINDS"))
        self.assertEqual(set(self.mod.FIELD_KINDS),
                         _const_set(("skills", "kinoa-dashboard-player-fields", "kinoa_dashboard_player_fields.py"),
                                    "ALLOWED_KINDS"))

    # ---- safety invariants ----

    def test_plan_never_contains_delete_actions(self):
        manifest = _manifest()
        plan = self._plan(manifest,
                          ev_custom=[{"id": "e1", "name": "operator_event", "status": "ACTIVE"}],
                          pf_custom=[{"id": "f1", "path": "operator.field", "state": "active"}])
        as_text = json.dumps(plan)
        self.assertNotIn("delete", as_text.lower())
        self.assertEqual([e["name"] for e in plan["dashboard_only"]["events"]], ["operator_event"])
        self.assertEqual([f["path"] for f in plan["dashboard_only"]["player_fields"]], ["operator.field"])

    def test_manifest_unsupported_passthrough(self):
        manifest = _manifest(unsupported_by_cli=[{"surface": "event_param", "name": "x", "kind": "date"}])
        plan = self._plan(manifest)
        self.assertEqual(len(plan["unsupported"]), 1)

    def test_unknown_manifest_sections_surface_not_silently_ignored(self):
        # Future producers will add surfaces (feature_settings, bundles, ...) —
        # an older planner must report them, never half-sync silently.
        manifest = _manifest(feature_settings={"schemas": []}, bundles=[])
        plan = self._plan(manifest)
        self.assertEqual(plan["unknown_manifest_sections"], ["bundles", "feature_settings"])

    def test_known_sections_are_not_flagged_unknown(self):
        plan = self._plan(_manifest())
        self.assertEqual(plan["unknown_manifest_sections"], [])


class CliContractTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name, payload):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as f:
            json.dump(payload, f)
        return path

    def _listing(self, items):
        # Mirrors the live gamemetaapi listing shape.
        return {"http_status": 200, "ok": True, "response": {"totalCount": len(items), "elements": items}}

    def test_main_rejects_failed_listing_envelope(self):
        # A saved 401/500 helper output (ok:false) must fail closed with listing_fetch_failed,
        # not be mistaken for an empty dashboard.
        manifest_path = self._write("m.json", _manifest())
        empty = self._write("e.json", self._listing([]))
        failed = self._write("f.json", {"http_status": 401, "ok": False,
                                        "response": {"message": "unauthorized"}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", failed, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "listing_fetch_failed")

    def test_main_rejects_truncated_listing(self):
        # totalCount (50) exceeds the returned page (2) → the listing is paginated and only the
        # first page came back. Fail closed so on-later-pages entities aren't mistaken for absent.
        manifest_path = self._write("m.json", _manifest())
        empty = self._write("e.json", self._listing([]))
        truncated = self._write("t.json", {
            "http_status": 200, "ok": True,
            "response": {"totalCount": 50, "elements": [{"id": "a", "name": "x"},
                                                        {"id": "b", "name": "y"}]}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", truncated, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "listing_truncated")

    def test_main_accepts_full_page_when_totalcount_matches(self):
        # Boundary: totalCount == returned count → not truncated, proceeds normally.
        manifest_path = self._write("m.json", _manifest())
        full = self._write("full.json", {
            "http_status": 200, "ok": True,
            "response": {"totalCount": 2, "elements": [{"id": "a", "name": "x"},
                                                       {"id": "b", "name": "y"}]}})
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", full, "--events-custom", empty,
                                  "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(code, 0)

    def test_main_rejects_utf16_listing_with_exit_2(self):
        # PowerShell 5.1 `>` writes UTF-16 LE; reading it as utf-8 must fail closed (exit 2),
        # not traceback. Guards the broadened _load_json except path.
        manifest_path = self._write("m.json", _manifest())
        empty = self._write("e.json", self._listing([]))
        u16 = os.path.join(self.tmp.name, "u16.json")
        with open(u16, "w", encoding="utf-16") as f:
            json.dump(self._listing([]), f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", u16, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "invalid_json")

    def test_extract_items_accepts_live_and_variant_shapes(self):
        mod = self.mod
        live = {"http_status": 200, "ok": True, "response": {"totalCount": 1, "elements": [{"id": "x"}]}}
        variant = {"http_status": 200, "ok": True, "response": {"data": [{"id": "y"}]}}
        bare_list = {"http_status": 200, "ok": True, "response": [{"id": "z"}]}
        self.assertEqual(mod._extract_items(live, "t")[0]["id"], "x")
        self.assertEqual(mod._extract_items(variant, "t")[0]["id"], "y")
        self.assertEqual(mod._extract_items(bare_list, "t")[0]["id"], "z")

    def test_main_rejects_api_manifest(self):
        manifest_path = self._write("m.json", _manifest(integration_type="API"))
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", empty, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "wrong_integration_type")

    def test_main_rejects_unknown_schema_version(self):
        manifest_path = self._write("m.json", _manifest(schema_version=99))
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", empty, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "unsupported_manifest_version")

    def test_main_rejects_listing_from_another_game(self):
        # session.env left over from another game → listings carry that game's id.
        manifest_path = self._write("m.json", _manifest(game_id="aaaaaaaa-1111-1111-1111-111111111111"))
        ep = self._write("ep.json", self._listing(
            [{"id": "e1", "name": "session_start", "status": "ACTIVE",
              "game_id": "bbbbbbbb-2222-2222-2222-222222222222"}]))
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", ep, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "listing_game_mismatch")

    def test_main_accepts_matching_game_id_and_fields_gameId_spelling(self):
        manifest = _manifest(game_id="AAAAAAAA-1111-1111-1111-111111111111")  # case-insensitive match
        manifest["player_fields"]["custom"] = [{"path": "wallet.gold", "kind": "number"}]
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        fc = self._write("fc.json", self._listing(
            [{"id": "f1", "path": "wallet.gold", "state": "active", "kind": "number",
              "gameId": "aaaaaaaa-1111-1111-1111-111111111111"}]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", empty, "--events-custom", empty,
                                  "--fields-predefined", empty, "--fields-custom", fc])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())
        self.assertEqual([f["path"] for f in plan["player_fields"]["already_ok"]], ["wallet.gold"])

    def test_main_end_to_end_plan(self):
        manifest = _manifest()
        manifest["events"]["predefined_in_use"] = [{"name": "session_start"}]
        manifest["events"]["custom"] = [{"name": "gold_purchase",
                                         "params": [{"name": "amount", "kind": "number"}]}]
        manifest["player_fields"]["custom"] = [{"path": "wallet.gold", "kind": "number"}]
        manifest_path = self._write("m.json", manifest)
        ep = self._write("ep.json", self._listing(
            [{"id": "e1", "name": "session_start", "status": "NOT_IMPLEMENTED"}]))
        ec = self._write("ec.json", self._listing([]))
        ecd = self._write("ecd.json", self._listing([]))
        fp = self._write("fp.json", self._listing([]))
        fc = self._write("fc.json", self._listing([]))
        fcd = self._write("fcd.json", self._listing(
            [{"id": "f9", "path": "wallet.gold", "state": "deleted"}]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", ep, "--events-custom", ec,
                                  "--events-custom-deleted", ecd,
                                  "--fields-predefined", fp, "--fields-custom", fc,
                                  "--fields-custom-deleted", fcd])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())
        self.assertEqual([e["name"] for e in plan["events"]["publish"]], ["session_start"])
        self.assertEqual([e["name"] for e in plan["events"]["create"]], ["gold_purchase"])
        self.assertTrue(plan["player_fields"]["activate"][0]["was_deleted"])


if __name__ == "__main__":
    unittest.main()
