#!/usr/bin/env python3
"""Builds the five fixture pages the jsdom interaction harness drives.

Payloads are PINNED (registries are a 2026-07-29 live snapshot — they are test
fixtures, not a mirror of the backend; the vocab-drift detector owns freshness).
Usage: python3 make_fixtures.py <output-dir>
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GENERATOR = os.path.join(HERE, "..", "..", "plugin", "skills", "kinoa-sdk-dashboard-sync",
                         "generate_merge_plan_page.py")

PREDEFINED = ["collect_milestones", "collected_resource", "in_app_click", "in_app_close",
              "in_app_impression", "in_game_purchase", "install", "level_up", "payment",
              "player_update", "progress", "progress_milestones", "reach_milestone",
              "reset_milestones", "reset_player_state", "session_start", "social_connect",
              "social_disconnect", "social_post", "tutorial", "watch_ad"]
DEBUG = ["ab_test_group_assigned", "backend_feature_settings_download",
         "backend_translations_download", "error", "feature_settings_download",
         "feature_settings_get_checksum", "feature_settings_get_local",
         "feature_settings_smart_request", "feature_settings_smart_response",
         "in_app_created", "in_app_eligibility", "in_app_generated", "in_app_inbox_cleared",
         "in_app_inbox_cleared_by_operator", "in_app_inbox_deleted",
         "in_app_inbox_instance_deleted", "in_app_instance_update",
         "in_app_instance_update_by_client", "in_app_received", "in_app_send", "in_app_use",
         "in_apps_inbox_received", "inbox_message_replace", "inbox_messages_remove",
         "offline_events_sent", "operator_changed_state", "push_clicked",
         "received_flow_action", "reminder_in_app", "slow_request", "tick",
         "translations_download", "translations_get_local", "translations_smart_request",
         "translations_smart_response", "web_socket_closed", "web_socket_error",
         "web_socket_opened"]
SDK_AUTOMATIC = ["install", "player_update", "collect_milestones", "progress_milestones",
                 "reach_milestone", "reset_milestones"]
GAME = "c1093f5a-6660-11f1-8e1e-43e865e3481f"
TS = "2026-07-28T22:00:00Z"

PAGES = {
    "e2e-events.html": {
        "payload_version": 1, "generated_at": TS, "game_id": GAME,
        "integration_type": "SDK", "predefined_wire_names": PREDEFINED,
        "debug_wire_names": DEBUG, "sdk_automatic_wire_names": SDK_AUTOMATIC,
        "events": [
            {"id": 1, "kind": "predefined", "name": "session_start", "existing": True,
             "source": "KinoaGameController.cs:41", "params": [],
             "proposed_params": [{"name": "session_source", "kind": "string", "extra": ""}]},
            {"id": 2, "kind": "custom", "name": "race_finished", "existing": False,
             "source": "GameStateService.cs:130",
             "params": [{"name": "position", "kind": "number", "extra": ""}]},
            # Same-name existing pair — a custom mirror colliding with the predefined
            # wire name is legal code reality (demo-a EventName_FakeLevelUpCustom).
            {"id": 3, "kind": "predefined", "name": "level_up", "existing": True,
             "source": "AnalyticsEventListener.cs:58", "params": []},
            {"id": 4, "kind": "custom", "name": "level_up", "existing": True,
             "source": "AnalyticsEventListener.cs:352", "params": []},
            # System-named param measured with a NON-canonical kind on a read-only row:
            # the page must ship it verbatim (no retype) and show the route warning.
            {"id": 5, "kind": "custom", "name": "start_level", "existing": True,
             "source": "AnalyticsEventListener.cs:81",
             "params": [{"name": "level", "kind": "string", "extra": ""}]}]},
    "e2e-fields.html": {
        "payload_version": 1, "generated_at": TS, "game_id": GAME,
        "registries_source": "live",
        "dashboard_field_registry": {
            "predefined": [{"path": "level", "kind": "number"}],
            "calculated": [{"path": "days_since_install", "kind": "number"}],
            "custom_paths": ["transaction_count"],
            "custom_fields": [{"path": "transaction_count", "kind": "number",
                               "name": "TransactionCount",
                               "description": "Total number of IAP transactions."}],
            "names": ["Level", "Days since install", "TransactionCount"]},
        "player_fields": [
            # String ids on purpose: producers mint "pf-ex-1"-style ids; the page's
            # add-row counter must stay numeric-robust (id: null regression, demo-b).
            {"id": "pf-ex-1", "name": "EpisodeNumber", "kind": "number", "extra": "", "existing": True,
             "source": "CustomPlayerState.cs:18", "path": "episode_number",
             "description": "current episode"},
            {"id": "pf-new-1", "name": "LastRaceAt", "kind": "date", "extra": "", "existing": False,
             "source": "GameStateService.cs:77", "path": "last_race_at"}]},
    "e2e-fs.html": {
        "payload_version": 1, "generated_at": TS, "game_id": GAME,
        "feature_settings": {
            "schemas": [
                {"id": 1, "name": "BoosterEconomy", "existing": True, "version": 3,
                 "source": "BoosterEconomySettings.cs",
                 "columns": [{"name": "sku", "kind": "bundle_key"},
                             {"name": "price", "kind": "integer"}]},
                {"id": 2, "name": "RaceRewards", "existing": False,
                 "source": "RewardConfig.cs:22",
                 "columns": [{"name": "coins", "kind": "integer"}]}],
            "settings": [
                {"id": 10, "key": "BoosterEconomy", "schema_name": "BoosterEconomy",
                 "version": 2, "existing": True, "source": "KinoaGameController.cs:139"},
                {"id": 13, "key": "BoosterEconomy_Legacy", "schema_name": "BoosterEconomy",
                 "version": 3, "existing": True, "source": "LegacyBoosterLoader.cs:58"},
                {"id": 11, "key": "BoosterEconomy_Promo", "schema_name": "BoosterEconomy",
                 "version": 3, "existing": False, "source": "added on page"},
                {"id": 12, "key": "RaceRewards", "schema_name": "RaceRewards", "version": 1,
                 "existing": False, "source": "RewardConfig.cs:22"}]}},
    "e2e-resources.html": {
        "payload_version": 1, "generated_at": TS, "game_id": GAME,
        "resources": [
            {"id": 1, "name": "Police Booster", "key": "police", "existing": True,
             "description": "In-game booster granted as a prize.", "source": "RewardType.cs:10",
             "fields": [{"name": "duration_sec", "field_type": "number", "default": "30",
                         "enumeration_values": [], "description": "active time"}]}]},
    "e2e-mismatch.html": {
        "payload_version": 2, "generated_at": TS, "game_id": GAME,
        "events": [{"id": 1, "kind": "custom", "name": "x", "existing": False, "params": []}]},
}


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for fname, payload in PAGES.items():
        proc = subprocess.run(
            [sys.executable, GENERATOR, "--output", os.path.join(out_dir, fname), "--no-open"],
            input=json.dumps(payload), capture_output=True, text=True)
        result = json.loads(proc.stdout)
        if not result.get("ok"):
            raise SystemExit(f"{fname}: generator failed: {proc.stdout} {proc.stderr}")
        print(fname, "ok")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, ".fixtures"))
