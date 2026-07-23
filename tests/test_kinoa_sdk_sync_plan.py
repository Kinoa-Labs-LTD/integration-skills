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


def _fs_manifest(schemas=(), settings=()):
    return _manifest(schema_version=2,
                     feature_settings={"schemas": list(schemas), "settings": list(settings)})


def _res_manifest(resources=()):
    return _manifest(schema_version=3, resources=list(resources))


def _live_template(key, fields=(), status="active", template_id=None, name=None):
    """A resource-template listing element. `fields` = [(name, field_type), ...].
    The live listing returns status lowercase (draft/active/deprecated)."""
    return {
        "id": template_id or f"rt-{key}",
        "key": key,
        "name": name or key,
        "status": status,
        "fields": [{"name": n, "field_type": t} for n, t in fields],
    }


def _live_schema(name, fields, status="ACTIVE", version="1", schema_id=None):
    """A get-schema-shaped live record. `fields` = [(name, type), ...]."""
    return {
        "id": schema_id or f"sch-{name}",
        "name": name,
        "status": status,
        "versions": [{
            "id": f"ver-{name}",
            "version": version,
            "status": "ACTIVE",
            "tableFields": [{"name": n, "type": t} for n, t in fields],
        }],
    }


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def _plan(self, manifest, ev_predef=(), ev_custom=(), ev_deleted=(),
              pf_predef=(), pf_custom=(), pf_deleted=(), fs_schemas=(), fs_settings=()):
        return self.mod.build_plan(manifest, list(ev_predef), list(ev_custom), list(ev_deleted),
                                   list(pf_predef), list(pf_custom), list(pf_deleted),
                                   list(fs_schemas), list(fs_settings))

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
        # Future producers will add surfaces (bundles, translations, ...) — an older planner must
        # report them, never half-sync silently. feature_settings is now a KNOWN section.
        manifest = _manifest(bundles=[], translations={})
        plan = self._plan(manifest)
        self.assertEqual(plan["unknown_manifest_sections"], ["bundles", "translations"])

    def test_known_sections_are_not_flagged_unknown(self):
        plan = self._plan(_manifest())
        self.assertEqual(plan["unknown_manifest_sections"], [])
        # feature_settings (schema_version 2) is recognized, never flagged unknown.
        self.assertEqual(self._plan(_fs_manifest())["unknown_manifest_sections"], [])


class FeatureSettingsPlanTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()

    def _plan(self, schemas=(), settings=(), fs_schemas=(), fs_settings=()):
        m = _fs_manifest(schemas, settings)
        return self.mod.build_plan(m, [], [], [], [], [], [], list(fs_schemas), list(fs_settings))

    # ---- schemas ----

    def test_schema_absent_planned_as_create(self):
        plan = self._plan(schemas=[{"name": "DailyBonusSettings",
                                    "fields": [{"name": "day", "kind": "integer"}]}])
        fsp = plan["feature_settings"]
        self.assertEqual([s["name"] for s in fsp["schema_create"]], ["DailyBonusSettings"])
        self.assertEqual(fsp["version_conflict"], [])
        self.assertEqual(fsp["already_ok"], [])
        # fields are carried for create-schema, normalized to the operator 5
        self.assertEqual(fsp["schema_create"][0]["fields"][0], {"name": "day", "kind": "integer", "isRequired": True})

    def test_schema_present_matching_fields_already_ok(self):
        plan = self._plan(
            schemas=[{"name": "Wof", "fields": [{"name": "prize", "kind": "string"},
                                                {"name": "coins", "kind": "integer"}]}],
            fs_schemas=[_live_schema("Wof", [("prize", "string"), ("coins", "integer")])])
        fsp = plan["feature_settings"]
        self.assertEqual([s["name"] for s in fsp["already_ok"]], ["Wof"])
        self.assertEqual(fsp["schema_create"], [])
        self.assertEqual(fsp["version_conflict"], [])

    def test_schema_present_differing_fields_version_conflict(self):
        plan = self._plan(
            schemas=[{"name": "Wof", "fields": [{"name": "prize", "kind": "string"},
                                                {"name": "coins", "kind": "integer"}]}],
            fs_schemas=[_live_schema("Wof", [("prize", "string"), ("coins", "integer"),
                                             ("extra", "string")])])
        fsp = plan["feature_settings"]
        self.assertEqual(fsp["schema_create"], [])
        self.assertEqual(len(fsp["version_conflict"]), 1)
        self.assertEqual(fsp["version_conflict"][0]["dashboard_only_columns"], ["extra"])

    def test_draft_schema_single_bucket_never_also_already_ok(self):
        # ENTITY status drives the publish plan; a schema planned for publish must NOT also
        # appear in already_ok (one bucket per schema — the shape verdict rides in the reason).
        plan = self._plan(
            schemas=[{"name": "Wof", "fields": [{"name": "prize", "kind": "string"}]}],
            fs_schemas=[_live_schema("Wof", [("prize", "string")], status="DRAFT")])
        fsp = plan["feature_settings"]
        self.assertEqual([s["name"] for s in fsp["schema_publish"]], ["Wof"])
        self.assertIn("matching column shape", fsp["schema_publish"][0]["reason"])
        self.assertIn("ENTITY", fsp["schema_publish"][0]["reason"])
        self.assertEqual([s for s in fsp["already_ok"] if s.get("name") == "Wof"], [])

    def test_draft_schema_with_shape_conflict_publish_plus_conflict(self):
        plan = self._plan(
            schemas=[{"name": "Wof", "fields": [{"name": "prize", "kind": "string"}]}],
            fs_schemas=[_live_schema("Wof", [("prize", "string"), ("extra", "integer")], status="DRAFT")])
        fsp = plan["feature_settings"]
        self.assertEqual([s["name"] for s in fsp["schema_publish"]], ["Wof"])
        self.assertIn("version_conflict", fsp["schema_publish"][0]["reason"])
        self.assertEqual([s["name"] for s in fsp["version_conflict"]], ["Wof"])
        self.assertEqual([s for s in fsp["already_ok"] if s.get("name") == "Wof"], [])

    def test_schema_present_draft_planned_as_publish(self):
        plan = self._plan(
            schemas=[{"name": "Wof", "fields": [{"name": "prize", "kind": "string"}]}],
            fs_schemas=[_live_schema("Wof", [("prize", "string")], status="DRAFT")])
        self.assertEqual([s["name"] for s in plan["feature_settings"]["schema_publish"]], ["Wof"])

    def test_schema_summary_listing_without_fields_not_verified(self):
        # A list-schemas summary row (no versions[].tableFields) can't be field-diffed → already_ok
        # with an explicit "shape NOT verified" reason, never a phantom conflict.
        plan = self._plan(
            schemas=[{"name": "Wof", "fields": [{"name": "prize", "kind": "string"}]}],
            fs_schemas=[{"id": "s1", "name": "Wof", "status": "ACTIVE"}])
        ok = plan["feature_settings"]["already_ok"]
        self.assertEqual([s["name"] for s in ok], ["Wof"])
        self.assertIn("NOT verified", ok[0]["reason"])
        self.assertEqual(plan["feature_settings"]["version_conflict"], [])

    def test_forgiving_fold_avoids_false_conflict(self):
        # code `string` vs live `date`/`long_string`, and code `integer` vs live `long`, fold to the
        # same operator-5 kind on both sides → NOT a conflict (the producer maps down identically).
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "d", "kind": "string"},
                                              {"name": "n", "kind": "integer"}]}],
            fs_schemas=[_live_schema("S", [("d", "date"), ("n", "long")])])
        self.assertEqual([s["name"] for s in plan["feature_settings"]["already_ok"]], ["S"])
        self.assertEqual(plan["feature_settings"]["version_conflict"], [])

    def test_real_type_change_is_conflict(self):
        # code `integer` vs live `number` for the same column → distinct operator-5 kinds → conflict.
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "x", "kind": "integer"}]}],
            fs_schemas=[_live_schema("S", [("x", "number")])])
        vc = plan["feature_settings"]["version_conflict"]
        self.assertEqual(len(vc), 1)
        self.assertEqual(vc[0]["type_changed_columns"], ["x"])

    # ---- settings + default config ----

    def test_setting_absent_creates_setting_and_default_config(self):
        plan = self._plan(settings=[{"key": "DailyBonus", "schema_name": "DailyBonus",
                                     "version": 1}])
        fsp = plan["feature_settings"]
        self.assertEqual([s["key"] for s in fsp["setting_create"]], ["DailyBonus"])
        self.assertEqual([c["setting_key"] for c in fsp["config_create"]], ["DailyBonus"])
        self.assertTrue(fsp["config_create"][0]["default"])
        self.assertIsNone(fsp["config_create"][0]["seed_csv"])  # no seed_csv provided → empty default config
        self.assertEqual([c["setting_key"] for c in fsp["config_publish"]], ["DailyBonus"])

    def test_bundle_key_seed_dependency_warns(self):
        # Live-verified 2026-07-02: import 422s when a bundle_key column's values aren't Bundles yet.
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "sku", "kind": "bundle_key"},
                                              {"name": "coins", "kind": "integer"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 1,
                       "seed_csv": "kinoa-sdk-dashboard-sync-workspace/S.csv"}])
        warns = [w for w in plan["feature_settings"]["warnings"] if "bundle_key_columns" in w]
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]["bundle_key_columns"], ["sku"])
        # no seed_csv → no warning (nothing to import)
        plan2 = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "sku", "kind": "bundle_key"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 1}])
        self.assertEqual([w for w in plan2["feature_settings"]["warnings"] if "bundle_key_columns" in w], [])

    def test_config_create_carries_seed_csv(self):
        plan = self._plan(settings=[{"key": "DailyBonus", "schema_name": "DailyBonus", "version": 1,
                                     "seed_csv": "kinoa-sdk-dashboard-sync-workspace/DailyBonus.csv"}])
        cc = plan["feature_settings"]["config_create"]
        self.assertEqual(cc[0]["seed_csv"], "kinoa-sdk-dashboard-sync-workspace/DailyBonus.csv")

    def test_setting_present_already_ok_conditional_config(self):
        # Resume path (C8): an existing setting gets a CONDITIONAL config ensure-step —
        # a prior partial run may have created the setting but died before its default config.
        plan = self._plan(settings=[{"key": "DailyBonus", "schema_name": "S", "version": 1}],
                          fs_settings=[{"id": "set1", "key": "DailyBonus"}])
        fsp = plan["feature_settings"]
        self.assertEqual(fsp["setting_create"], [])
        self.assertEqual([s["key"] for s in fsp["already_ok"] if s.get("surface") == "setting"], ["DailyBonus"])
        self.assertEqual(len(fsp["config_create"]), 1)
        self.assertEqual(fsp["config_create"][0]["conditional"], "only_if_no_configs")
        self.assertEqual(fsp["config_publish"][0]["conditional"], "only_if_no_configs")

    def test_new_setting_config_is_unconditional(self):
        plan = self._plan(settings=[{"key": "K", "schema_name": "S", "version": 1}])
        cc = plan["feature_settings"]["config_create"]
        self.assertEqual(len(cc), 1)
        self.assertNotIn("conditional", cc[0])

    def test_dangling_schema_name_warns(self):
        # Setting bound to a schema that is neither in the manifest nor live → unexecutable bind.
        plan = self._plan(settings=[{"key": "K", "schema_name": "Ghost", "version": 1}])
        warns = [w for w in plan["feature_settings"]["warnings"] if "dangling" in w.get("reason", "")]
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]["schema_name"], "Ghost")

    def test_duplicate_schema_names_and_setting_keys_warn_once(self):
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "a", "kind": "integer"}]},
                     {"name": "S", "fields": [{"name": "b", "kind": "string"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 1},
                      {"key": "K", "schema_name": "S", "version": 1}])
        fsp = plan["feature_settings"]
        self.assertEqual(len(fsp["schema_create"]), 1)
        self.assertEqual(len(fsp["setting_create"]), 1)
        self.assertTrue(any("duplicate schema name" in w.get("reason", "") for w in fsp["warnings"]))
        self.assertTrue(any("duplicate setting key" in w.get("reason", "") for w in fsp["warnings"]))

    def test_new_schema_with_nondefault_version_warns(self):
        # Schema created this run starts at version 1 — requesting version 3 = VERSION_NOT_FOUND.
        plan = self._plan(schemas=[{"name": "S", "fields": [{"name": "a", "kind": "integer"}]}],
                          settings=[{"key": "K", "schema_name": "S", "version": 3}])
        warns = [w for w in plan["feature_settings"]["warnings"]
                 if "created this run" in w.get("reason", "")]
        self.assertEqual(len(warns), 1)

    def test_filter_and_placeholder_columns_dropped_with_warning(self):
        # Filters are configuration-level; unreplaced "<PlayerField>" scaffolds are junk. Both
        # excluded from the schema plan, surfaced as a warning — never silently created.
        plan = self._plan(schemas=[{"name": "S", "fields": [
            {"name": "coins", "kind": "integer"},
            {"name": "filter: Level", "kind": "number"},
            {"name": "filter: <PlayerField>:from", "kind": "number"}]}])
        create = plan["feature_settings"]["schema_create"][0]
        self.assertEqual([f["name"] for f in create["fields"]], ["coins"])
        drop = [w for w in plan["feature_settings"]["warnings"] if "dropped_columns" in w]
        self.assertEqual(len(drop), 1)
        self.assertEqual(sorted(drop[0]["dropped_columns"]),
                         ["filter: <PlayerField>:from", "filter: Level"])

    def test_live_filter_columns_ignored_in_shape_diff(self):
        # A live schema polluted with filter columns must not force a version_conflict when the
        # code's data columns match.
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "coins", "kind": "integer"}]}],
            fs_schemas=[_live_schema("S", [("coins", "integer"), ("filter: Level", "number")])])
        self.assertEqual([s["name"] for s in plan["feature_settings"]["already_ok"]], ["S"])
        self.assertEqual(plan["feature_settings"]["version_conflict"], [])

    def test_schema_case_collision_warns(self):
        plan = self._plan(schemas=[{"name": "wheeloffortune", "fields": [{"name": "a", "kind": "string"}]}],
                          fs_schemas=[_live_schema("WheelOfFortune", [("a", "string")])])
        fsp = plan["feature_settings"]
        self.assertTrue(any("case-collision" in w.get("reason", "") for w in fsp["warnings"]))
        # byte-for-byte: still planned as create (advisory, developer decides at the checklist)
        self.assertEqual([s["name"] for s in fsp["schema_create"]], ["wheeloffortune"])

    def test_setting_key_case_collision_warns(self):
        plan = self._plan(settings=[{"key": "dailybonus", "schema_name": "S", "version": 1}],
                          fs_settings=[{"id": "s1", "key": "DailyBonus", "schemaId": "x"}])
        fsp = plan["feature_settings"]
        self.assertTrue(any("case-collision" in w.get("reason", "") and w.get("dashboard_key") == "DailyBonus"
                            for w in fsp["warnings"]))

    def test_existing_setting_bound_to_different_schema_warns(self):
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "a", "kind": "string"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 1}],
            fs_schemas=[_live_schema("S", [("a", "string")], schema_id="sch-right")],
            fs_settings=[{"id": "set1", "key": "K", "schemaId": "sch-WRONG"}])
        warns = [w for w in plan["feature_settings"]["warnings"]
                 if "different schema" in w.get("reason", "")]
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]["live_schema_id"], "sch-WRONG")

    def test_setting_version_mismatch_with_live_schema_warns(self):
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "x", "kind": "integer"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 2}],
            fs_schemas=[_live_schema("S", [("x", "integer")], version="1")])
        warns = [w for w in plan["feature_settings"]["warnings"] if w.get("key") == "K"]
        self.assertEqual(len(warns), 1)
        self.assertEqual((warns[0]["requested_version"], warns[0]["live_active_version"]), (2, "1"))

    def test_setting_version_match_no_warning(self):
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "x", "kind": "integer"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 1}],
            fs_schemas=[_live_schema("S", [("x", "integer")], version="1")])
        self.assertEqual([w for w in plan["feature_settings"]["warnings"] if w.get("key") == "K"], [])

    # ---- dashboard_only + safety ----

    def test_dashboard_only_fs_schema_and_setting(self):
        plan = self._plan(
            fs_schemas=[_live_schema("OperatorSchema", [("a", "string")])],
            fs_settings=[{"id": "s1", "key": "OperatorKey"}])
        self.assertEqual([s["name"] for s in plan["dashboard_only"]["feature_schemas"]], ["OperatorSchema"])
        self.assertEqual([s["key"] for s in plan["dashboard_only"]["feature_settings"]], ["OperatorKey"])

    def test_fs_plan_never_contains_delete(self):
        plan = self._plan(
            schemas=[{"name": "S", "fields": [{"name": "x", "kind": "integer"}]}],
            settings=[{"key": "K", "schema_name": "S", "version": 1}],
            fs_schemas=[_live_schema("Other", [("a", "string")])],
            fs_settings=[{"id": "s1", "key": "OtherKey"}])
        self.assertNotIn("delete", json.dumps(plan["feature_settings"]).lower())

    # ---- helpers ----

    def test_fs_normalize_kind_folds_to_operator_five(self):
        n = self.mod._fs_normalize_kind
        self.assertEqual(n("integer"), "integer")
        self.assertEqual(n("long"), "integer")
        self.assertEqual(n("number"), "number")
        self.assertEqual(n("boolean"), "boolean")
        self.assertEqual(n("bundle_key"), "bundle_key")
        for t in ("string", "long_string", "date", "version", "enumeration", "object", "weird", ""):
            self.assertEqual(n(t), "string")

    def test_fs_fields_map_none_without_versions(self):
        self.assertIsNone(self.mod._fs_fields_map({"name": "S", "status": "ACTIVE"}))

    def test_fs_fields_map_prefers_active_version(self):
        rec = {"name": "S", "versions": [
            {"version": "1", "status": "ARCHIVED", "tableFields": [{"name": "old", "type": "string"}]},
            {"version": "2", "status": "ACTIVE", "tableFields": [{"name": "new", "type": "integer"}]}]}
        self.assertEqual(self.mod._fs_fields_map(rec), {"new": "integer"})


class ResourcesPlanTests(unittest.TestCase):
    """KING-21960 diff matrix for resource templates (manifest schema_version 3)."""

    def setUp(self):
        self.mod = _load_module()

    def _plan(self, resources=(), live=()):
        plan = self.mod.build_plan(_res_manifest(resources),
                                   [], [], [], [], [], [], [], [], list(live))
        return plan["resources"], plan

    # ---- create ----

    def test_absent_key_planned_as_create_with_fields_passthrough(self):
        rp, plan = self._plan(resources=[{
            "name": "Legendary Sword", "key": "legendary_sword", "description": "Boss reward.",
            "fields": [
                {"name": "attack", "field_type": "number", "required": True, "default": 100},
                {"name": "rarity", "field_type": "enumeration",
                 "enumeration_values": ["common", "rare", "epic"]},
            ]}])
        self.assertEqual([c["key"] for c in rp["create"]], ["legendary_sword"])
        create = rp["create"][0]
        self.assertEqual(create["name"], "Legendary Sword")
        self.assertEqual(create["description"], "Boss reward.")
        self.assertEqual(create["fields"][0],
                         {"name": "attack", "field_type": "number", "required": True, "default": 100})
        self.assertEqual(create["fields"][1]["enumeration_values"], ["common", "rare", "epic"])
        self.assertFalse(create["fields"][1]["required"])  # required defaults to False
        self.assertEqual(rp["activate"], [])
        self.assertEqual(rp["field_conflict"], [])
        self.assertEqual(rp["warnings"], [])

    def test_create_name_defaults_to_key(self):
        rp, _ = self._plan(resources=[{"key": "gold_chest", "fields": []}])
        self.assertEqual(rp["create"][0]["name"], "gold_chest")

    def test_field_default_and_description_optional_passthrough(self):
        # A field is minimally {name, type}; default and description are OPTIONAL —
        # carried verbatim when present, never invented when absent.
        rp, _ = self._plan(resources=[{
            "key": "sword",
            "fields": [{"name": "attack", "field_type": "number"},
                       {"name": "element", "field_type": "string",
                        "description": "Damage element", "default": "fire"}]}])
        bare, rich = rp["create"][0]["fields"]
        self.assertEqual(bare, {"name": "attack", "field_type": "number", "required": False})
        self.assertNotIn("default", bare)
        self.assertNotIn("description", bare)
        self.assertEqual(rich["description"], "Damage element")
        self.assertEqual(rich["default"], "fire")

    # ---- ACTIVE ----

    def test_active_matching_fields_already_ok(self):
        rp, _ = self._plan(
            resources=[{"key": "sword", "fields": [{"name": "attack", "field_type": "number"}]}],
            live=[_live_template("sword", [("attack", "number")], status="active")])
        self.assertEqual([r["key"] for r in rp["already_ok"]], ["sword"])
        self.assertEqual(rp["create"], [])
        self.assertEqual(rp["field_conflict"], [])

    def test_active_status_compared_case_insensitively(self):
        rp, _ = self._plan(
            resources=[{"key": "sword", "fields": [{"name": "attack", "field_type": "number"}]}],
            live=[_live_template("sword", [("attack", "number")], status="ACTIVE")])
        self.assertEqual([r["key"] for r in rp["already_ok"]], ["sword"])

    def test_active_shape_drift_is_field_conflict_gate_not_update(self):
        # KING-22096: a live ACTIVE template may back live bundles/prizes — never edited
        # unattended; same discipline as the FS version_conflict gate.
        rp, _ = self._plan(
            resources=[{"key": "sword", "fields": [{"name": "attack", "field_type": "number"},
                                                   {"name": "element", "field_type": "string"}]}],
            live=[_live_template("sword", [("attack", "string"), ("weight", "number")])])
        self.assertEqual(rp["create"], [])
        self.assertEqual(rp["update"], [])
        self.assertEqual(rp["activate"], [])
        self.assertEqual(rp["already_ok"], [])
        vc = rp["field_conflict"]
        self.assertEqual(len(vc), 1)
        self.assertEqual(vc[0]["code_only_fields"], ["element"])
        self.assertEqual(vc[0]["dashboard_only_fields"], ["weight"])
        self.assertEqual(vc[0]["type_changed_fields"], ["attack"])

    # ---- DRAFT ----

    def test_draft_matching_fields_planned_as_activate(self):
        rp, _ = self._plan(
            resources=[{"key": "sword", "fields": [{"name": "attack", "field_type": "number"}]}],
            live=[_live_template("sword", [("attack", "number")], status="draft")])
        self.assertEqual([r["key"] for r in rp["activate"]], ["sword"])
        self.assertEqual(rp["update"], [])
        self.assertEqual(rp["create"], [])
        self.assertEqual(rp["field_conflict"], [])

    def test_draft_shape_drift_planned_as_update_then_activate(self):
        # A DRAFT is unpublished and mutable (usually a prior partial run's leftover) —
        # fields are updated first, then activated; never a conflict gate.
        rp, _ = self._plan(
            resources=[{"key": "sword", "fields": [{"name": "attack", "field_type": "number"}]}],
            live=[_live_template("sword", [("attack", "string")], status="draft")])
        self.assertEqual([r["key"] for r in rp["update"]], ["sword"])
        self.assertEqual([f["name"] for f in rp["update"][0]["fields"]], ["attack"])
        self.assertEqual([r["key"] for r in rp["activate"]], ["sword"])
        self.assertEqual(rp["field_conflict"], [])

    # ---- DEPRECATED (KING-22096) ----

    def test_deprecated_never_reactivated_even_with_matching_fields(self):
        rp, _ = self._plan(
            resources=[{"key": "old_skin", "fields": [{"name": "tier", "field_type": "number"}]}],
            live=[_live_template("old_skin", [("tier", "number")], status="deprecated")])
        self.assertEqual(rp["create"], [])
        self.assertEqual(rp["update"], [])
        self.assertEqual(rp["activate"], [])
        self.assertEqual(rp["field_conflict"], [])
        warns = [w for w in rp["warnings"] if w.get("key") == "old_skin"]
        self.assertEqual(len(warns), 1)
        self.assertIn("DEPRECATED", warns[0]["reason"])
        self.assertIn("never reactivates", warns[0]["reason"])

    def test_deprecated_with_shape_drift_still_only_warns_and_notes_drift(self):
        rp, _ = self._plan(
            resources=[{"key": "old_skin", "fields": [{"name": "tier", "field_type": "number"}]}],
            live=[_live_template("old_skin", [("tier", "string")], status="deprecated")])
        warns = [w for w in rp["warnings"] if w.get("key") == "old_skin"]
        self.assertEqual(len(warns), 1)
        self.assertIn("fields also differ", warns[0]["reason"])
        self.assertEqual(rp["field_conflict"], [])

    # ---- validation (KING-22098 consumer backstop) ----

    def test_invalid_key_warns_and_plans_nothing(self):
        rp, _ = self._plan(resources=[{"key": "9bad.key", "fields": []}])
        self.assertEqual(rp["create"], [])
        warns = [w for w in rp["warnings"] if w.get("key") == "9bad.key"]
        self.assertEqual(len(warns), 1)
        self.assertIn("invalid resource key", warns[0]["reason"])

    def test_duplicate_manifest_keys_warn_once_first_planned(self):
        rp, _ = self._plan(resources=[{"key": "sword", "fields": []},
                                      {"key": "sword", "fields": []}])
        self.assertEqual(len(rp["create"]), 1)
        self.assertTrue(any("duplicate resource key" in w.get("reason", "") for w in rp["warnings"]))

    def test_name_collision_with_live_template_warns_still_creates(self):
        # Live-verified 2026-07-23: template-NAME uniqueness is enforced across ALL statuses
        # (a DEPRECATED record still holds its name) — a create under a taken name 422s.
        # The planner warns ahead; the create stays planned (advisory).
        rp, _ = self._plan(
            resources=[{"name": "Legendary Sword", "key": "sword_v2", "fields": []}],
            live=[_live_template("sword", status="deprecated", name="Legendary Sword")])
        warns = [w for w in rp["warnings"] if "name collision" in w.get("reason", "")]
        self.assertEqual(len(warns), 1)
        self.assertEqual((warns[0]["dashboard_key"], warns[0]["dashboard_status"]),
                         ("sword", "deprecated"))
        self.assertEqual([c["key"] for c in rp["create"]], ["sword_v2"])

    def test_no_name_collision_warning_for_own_record(self):
        # The same name on the SAME key is the normal match path — never a name collision.
        rp, _ = self._plan(
            resources=[{"name": "Gold Chest", "key": "gold_chest", "fields": []}],
            live=[_live_template("gold_chest", status="active", name="Gold Chest")])
        self.assertEqual([w for w in rp["warnings"] if "name collision" in w.get("reason", "")], [])
        self.assertEqual([r["key"] for r in rp["already_ok"]], ["gold_chest"])

    def test_case_collision_with_live_key_warns_still_creates(self):
        rp, _ = self._plan(resources=[{"key": "gold_chest", "fields": []}],
                           live=[_live_template("Gold_chest", status="active")])
        self.assertTrue(any("case-collision" in w.get("reason", "") and
                            w.get("dashboard_key") == "Gold_chest" for w in rp["warnings"]))
        self.assertEqual([c["key"] for c in rp["create"]], ["gold_chest"])

    def test_unsupported_field_type_goes_to_unsupported_create_proceeds(self):
        rp, plan = self._plan(resources=[{
            "key": "sword",
            "fields": [{"name": "attack", "field_type": "number"},
                       {"name": "loot_table", "field_type": "object"}]}])
        self.assertEqual([f["name"] for f in rp["create"][0]["fields"]], ["attack"])
        uns = [u for u in plan["unsupported"] if u.get("surface") == "resource_field"]
        self.assertEqual(len(uns), 1)
        self.assertEqual((uns[0]["owner"], uns[0]["name"], uns[0]["kind"]),
                         ("sword", "loot_table", "object"))

    def test_enumeration_without_values_warns_but_field_kept(self):
        rp, _ = self._plan(resources=[{
            "key": "sword", "fields": [{"name": "rarity", "field_type": "enumeration"}]}])
        self.assertEqual([f["name"] for f in rp["create"][0]["fields"]], ["rarity"])
        self.assertTrue(any("enumeration field without enumeration_values" in w.get("reason", "")
                            for w in rp["warnings"]))

    def test_live_enumeration_readback_shape_no_false_conflict(self):
        # Verified live 2026-07-09: on read-back an enumeration field carries enumeration_id
        # with enumeration_values null — the diff compares field_type only, so a re-run must
        # NOT flag a spurious conflict.
        live = _live_template("sword", status="active")
        live["fields"] = [{"name": "rarity", "field_type": "enumeration",
                           "enumeration_id": "en-1", "enumeration_values": None}]
        rp, _ = self._plan(
            resources=[{"key": "sword",
                        "fields": [{"name": "rarity", "field_type": "enumeration",
                                    "enumeration_values": ["common", "rare"]}]}],
            live=[live])
        self.assertEqual([r["key"] for r in rp["already_ok"]], ["sword"])
        self.assertEqual(rp["field_conflict"], [])

    def test_unrecognized_live_status_warns_no_action(self):
        rp, _ = self._plan(resources=[{"key": "sword", "fields": []}],
                           live=[_live_template("sword", status="archived")])
        self.assertEqual(rp["create"], [])
        self.assertEqual(rp["activate"], [])
        self.assertTrue(any("unrecognized resource template status" in w.get("reason", "")
                            for w in rp["warnings"]))

    # ---- dashboard_only + safety ----

    def test_dashboard_only_lists_active_manifest_absent_templates_only(self):
        _, plan = self._plan(
            resources=[{"key": "sword", "fields": []}],
            live=[_live_template("sword", status="active"),
                  _live_template("operator_item", status="active"),
                  _live_template("operator_draft", status="draft"),
                  _live_template("operator_retired", status="deprecated")])
        self.assertEqual([r["key"] for r in plan["dashboard_only"]["resources"]], ["operator_item"])

    def test_resources_plan_never_contains_delete(self):
        rp, plan = self._plan(
            resources=[{"key": "sword", "fields": [{"name": "a", "field_type": "string"}]}],
            live=[_live_template("sword", [("b", "number")], status="active"),
                  _live_template("stale_draft", status="draft"),
                  _live_template("retired", status="deprecated")])
        self.assertNotIn("delete", json.dumps(plan["resources"]).lower())

    def test_resources_not_flagged_unknown_section(self):
        _, plan = self._plan(resources=[{"key": "sword", "fields": []}])
        self.assertEqual(plan["unknown_manifest_sections"], [])

    def test_key_regex_and_field_type_vocab_match_helper(self):
        # RESOURCE_KEY_RE / RESOURCE_FIELD_TYPES must equal the helper's constants, or the
        # planner could plan creates the helper CLI rejects. Parsed via ast — no module
        # import, so the helper's import-time session.env read never fires.
        import ast

        def _const(name):
            path = os.path.join(REPO_ROOT, "skills", "kinoa-dashboard-resource-template",
                                "kinoa_dashboard_resource_template.py")
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == name:
                            return ast.literal_eval(node.value)
            raise AssertionError(f"{name} not found in {path}")

        self.assertEqual(set(self.mod.RESOURCE_FIELD_TYPES), set(_const("ALLOWED_FIELD_TYPES")))
        self.assertEqual(self.mod.RESOURCE_KEY_RE, _const("RESOURCE_KEY_RE"))


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

    def test_main_accepts_v2_manifest_with_feature_settings(self):
        manifest = _manifest(schema_version=2, feature_settings={
            "schemas": [{"name": "DailyBonusSettings", "fields": [{"name": "day", "kind": "integer"}]}],
            "settings": [{"key": "DailyBonus", "schema_name": "DailyBonusSettings", "version": 1}]})
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", empty, "--events-custom", empty,
                                  "--fields-predefined", empty, "--fields-custom", empty,
                                  "--fs-schemas", empty, "--fs-settings", empty])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())
        self.assertEqual([s["name"] for s in plan["feature_settings"]["schema_create"]], ["DailyBonusSettings"])
        self.assertEqual([s["key"] for s in plan["feature_settings"]["setting_create"]], ["DailyBonus"])
        self.assertEqual(plan["unknown_manifest_sections"], [])

    def test_main_accepts_v3_manifest_with_resources(self):
        manifest = _res_manifest([{"name": "Legendary Sword", "key": "legendary_sword",
                                   "fields": [{"name": "attack", "field_type": "number"}]},
                                  {"key": "gold_chest", "fields": []}])
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        rt = self._write("rt.json", self._listing(
            [_live_template("gold_chest", status="active")]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", empty, "--events-custom", empty,
                                  "--fields-predefined", empty, "--fields-custom", empty,
                                  "--resources", rt])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())
        self.assertEqual([c["key"] for c in plan["resources"]["create"]], ["legendary_sword"])
        self.assertEqual([r["key"] for r in plan["resources"]["already_ok"]], ["gold_chest"])
        self.assertEqual(plan["unknown_manifest_sections"], [])

    def test_main_rejects_v3_manifest_without_resources_listing(self):
        # Resources in the manifest but no --resources listing → planning would mistake
        # "not fetched" for "absent" and plan duplicate DRAFT creates (whose only cleanup
        # is the operator-facing HARD delete). Fail closed.
        manifest = _res_manifest([{"key": "sword", "fields": []}])
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", empty, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "missing_resources_listing")

    def test_main_allows_empty_resources_section_without_listing(self):
        manifest = _res_manifest([])
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", empty, "--events-custom", empty,
                                  "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(code, 0)

    def test_main_rejects_v2_manifest_without_fs_listings(self):
        # FS content in the manifest but no --fs-schemas/--fs-settings → planning would mistake
        # "not fetched" for "nothing on the dashboard" and create duplicates. Fail closed.
        manifest = _manifest(schema_version=2, feature_settings={
            "schemas": [{"name": "S", "fields": [{"name": "a", "kind": "integer"}]}],
            "settings": [{"key": "K", "schema_name": "S", "version": 1}]})
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--manifest", manifest_path,
                               "--events-predefined", empty, "--events-custom", empty,
                               "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "missing_fs_listings")

    def test_main_allows_empty_fs_section_without_listings(self):
        # A v2 manifest whose feature_settings is EMPTY needs no FS listings.
        manifest = _manifest(schema_version=2, feature_settings={"schemas": [], "settings": []})
        manifest_path = self._write("m.json", manifest)
        empty = self._write("e.json", self._listing([]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(["--manifest", manifest_path,
                                  "--events-predefined", empty, "--events-custom", empty,
                                  "--fields-predefined", empty, "--fields-custom", empty])
        self.assertEqual(code, 0)

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
