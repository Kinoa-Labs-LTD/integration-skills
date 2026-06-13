#!/usr/bin/env python3
"""
Kinoa SDK Dashboard Sync — deterministic action planner.

Pure parser/differ: NO API calls, NO session.env access. Consumes the
kinoa-dashboard-manifest.json produced by the /kinoa SDK integration skill
plus the raw JSON outputs of the kinoa-dashboard-event and
kinoa-dashboard-player-fields list subcommands, and emits an action plan.

The plan NEVER contains delete actions. Soft-deleted dashboard records that
match a manifest entry are planned as publish (events) / activate (fields) —
never as create, which would collide with or duplicate the existing name.

Reality note (verified live 2026-06-12): only PLAYER FIELDS soft-delete on
the current dashboard. Event DELETE is hard (record gone for good; the
server's EventModelStatus enum has no DELETED value), so the
--events-custom-deleted input is normally omitted and the deleted-events
branch is forward-compat: it activates only if the backend ever grows event
soft-delete and a caller feeds a real deleted listing. A hard-deleted custom
event is simply absent from every listing -> planned as create, the correct
and only recovery.

Usage:
  python kinoa_sdk_sync_plan.py --manifest kinoa-dashboard-manifest.json \
      --events-predefined ep.json --events-custom ec.json \
      [--events-custom-deleted ecd.json] \
      --fields-predefined fp.json --fields-custom fc.json \
      [--fields-custom-deleted fcd.json]

Each listing file is the verbatim stdout of the corresponding helper call
({"http_status": ..., "ok": ..., "response": ...}). Prints the plan as a
single JSON object on stdout. Exit codes: 0 plan produced, 2 invalid input.
"""

import argparse
import json
import sys

PLAN_SCHEMA_VERSION = 1
SUPPORTED_MANIFEST_VERSIONS = (1,)

EVENT_PARAM_KINDS = ("number", "boolean", "string", "date", "enumeration", "string_array", "number_array")
FIELD_KINDS = ("number", "boolean", "string", "date", "long_string", "enumeration", "version")

# The dashboard auto-attaches these system params to every event. Verified live
# 2026-06-12: a CREATE carrying a same-named operator param silently DISPLACES the
# system param (the event loses its standard system column); editing a system param
# via PUT fails with an unhandled 500 (system params are shared template rows).
SYSTEM_EVENT_PARAM_NAMES = ("device_id", "time", "time_ms")

# Entity surfaces this planner knows how to sync. The manifest is designed to grow
# (feature settings, bundles, translations, ...) — any other top-level section is
# reported back as unknown so a newer manifest is never silently half-synced.
KNOWN_MANIFEST_KEYS = (
    "schema_version", "generated_at", "producer", "integration_type", "game_id",
    "sdk_version", "head_sha", "round", "project_root",
    "events", "player_fields", "unsupported_by_cli",
)


def _fail(error, message):
    print(json.dumps({"error": error, "message": message}, indent=2))
    sys.exit(2)


def _load_json(path, label):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        _fail("file_not_found", f"{label}: {path}")
    except json.JSONDecodeError as e:
        # PowerShell 5.1 `>` writes UTF-16 LE; reading it as UTF-8 yields garbage JSON.
        # Save listings with `| Out-File -Encoding utf8` (see SKILL.md Phase 2) on Windows.
        _fail("invalid_json", f"{label}: {path}: {e}")
    except UnicodeDecodeError as e:
        _fail("invalid_json", f"{label}: {path}: not UTF-8 (PowerShell `>` writes UTF-16 — "
                              f"use `| Out-File -Encoding utf8`): {e}")
    except OSError as e:
        _fail("file_unreadable", f"{label}: {path}: {e}")


def _extract_items(listing, label):
    """Pull the item list out of a helper listing output, tolerating shape variants."""
    if listing is None:
        return []
    if isinstance(listing, dict):
        http = listing.get("http_status")
        if listing.get("ok") is False or (isinstance(http, int) and not (200 <= http < 300)):
            _fail("listing_fetch_failed",
                  f"{label}: the helper reported a failed fetch (ok={listing.get('ok')}, "
                  f"http_status={http}) — re-run the listing; planning against a failed fetch would "
                  "mistake an empty/error body for 'nothing on the dashboard'")
    payload = listing.get("response", listing) if isinstance(listing, dict) else listing
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # "elements" is the live gamemetaapi shape ({"totalCount": N, "elements": [...]});
        # the rest are tolerated variants.
        for key in ("elements", "data", "items", "content", "rows", "game_events", "player_fields"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                # Pagination guard: the helpers fetch a single page (page=0, --rows N) and
                # never loop. If the server holds more than one page, a truncated listing would
                # make the planner mistake on-later-pages entities for "absent" and plan a
                # duplicate create. totalCount is right here — fail closed when it exceeds what
                # we got, so the developer re-fetches with a higher --rows.
                total = payload.get("totalCount")
                if isinstance(total, int) and total > len(items):
                    _fail("listing_truncated",
                          f"{label}: fetched {len(items)} of {total} records — the listing is "
                          f"paginated and only the first page was returned. Re-fetch with "
                          f"--rows >= {total} (the helpers do not paginate).")
                return items
    _fail("unrecognized_listing_shape", f"{label}: could not find an item list")


def _norm(value):
    return value.strip() if isinstance(value, str) else value


def _item_state(item):
    """Events use status (ACTIVE/NOT_IMPLEMENTED), fields use state (active/...). Normalize lower."""
    raw = item.get("status") or item.get("state") or ""
    return str(raw).strip().lower()


def _index_by(items, key):
    out = {}
    for item in items:
        if isinstance(item, dict) and _norm(item.get(key)):
            out.setdefault(_norm(item[key]), item)
    return out


def _param_names(event_record):
    params = event_record.get("game_event_parameters") or []
    return {_norm(p.get("name")) for p in params if isinstance(p, dict) and p.get("name")}


def _validate_params(params, allowed, owner, unsupported):
    """Split params into CLI-supported and unsupported; never drop silently."""
    ok = []
    for p in params or []:
        kind = (p.get("kind") or "").strip()
        if kind in allowed:
            ok.append({"name": p.get("name"), "kind": kind, "extra": p.get("extra") or None})
        else:
            unsupported.append({
                "surface": "event_param",
                "owner": owner,
                "name": p.get("name"),
                "kind": kind,
                "reason": f"kind '{kind}' is not supported by kinoa_dashboard_event.py — register manually on the dashboard",
            })
    return ok


def build_plan(manifest, ev_predef, ev_custom, ev_custom_deleted, pf_predef, pf_custom, pf_custom_deleted):
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "manifest_schema_version": manifest.get("schema_version"),
        "integration_type": manifest.get("integration_type"),
        "events": {"publish": [], "create": [], "add_params": [], "already_ok": [], "warnings": []},
        "player_fields": {"activate": [], "create": [], "already_ok": [], "warnings": []},
        "unsupported": list(manifest.get("unsupported_by_cli") or []),
        "dashboard_only": {"events": [], "player_fields": []},
        "unknown_manifest_sections": sorted(set(manifest) - set(KNOWN_MANIFEST_KEYS)),
    }

    ev_predef_by_name = _index_by(ev_predef, "name")
    ev_custom_by_name = _index_by(ev_custom, "name")
    ev_deleted_by_name = _index_by(ev_custom_deleted, "name")
    pf_predef_by_path = _index_by(pf_predef, "path")
    pf_custom_by_path = _index_by(pf_custom, "path")
    pf_deleted_by_path = _index_by(pf_custom_deleted, "path")

    events = manifest.get("events") or {}
    fields = manifest.get("player_fields") or {}

    manifest_event_names = set()
    manifest_field_paths = set()

    # --- Predefined events in use: publish NOT_IMPLEMENTED, diff custom params ---
    for entry in events.get("predefined_in_use") or []:
        name = _norm(entry.get("name"))
        if not name:
            continue
        manifest_event_names.add(name)
        record = ev_predef_by_name.get(name)
        if record is None:
            plan["events"]["warnings"].append({
                "name": name,
                "reason": "predefined event not found on the dashboard — check the name or SDK/dashboard version skew",
            })
            continue
        state = _item_state(record)
        item = {"name": name, "id": record.get("id"), "current_status": record.get("status") or record.get("state")}
        if state == "active":
            plan["events"]["already_ok"].append(dict(item, reason="predefined already published"))
        else:
            plan["events"]["publish"].append(dict(item, reason="predefined in use by the game — publish"))
        wanted = _validate_params(entry.get("custom_params"), EVENT_PARAM_KINDS, name, plan["unsupported"])
        missing = [p for p in wanted if _norm(p["name"]) not in _param_names(record)]
        if missing:
            plan["events"]["add_params"].append({
                "name": name, "id": record.get("id"), "params": missing,
                "reason": "custom params used by the game are missing on the predefined event",
            })

    # --- Custom (user) events: create / publish / republish-deleted / param diff ---
    for entry in events.get("custom") or []:
        name = _norm(entry.get("name"))
        if not name:
            continue
        manifest_event_names.add(name)
        params = _validate_params(entry.get("params"), EVENT_PARAM_KINDS, name, plan["unsupported"])
        active_record = ev_custom_by_name.get(name)
        if active_record is not None:
            state = _item_state(active_record)
            item = {"name": name, "id": active_record.get("id"),
                    "current_status": active_record.get("status") or active_record.get("state")}
            if state == "active":
                plan["events"]["already_ok"].append(dict(item, reason="custom event already active"))
            else:
                plan["events"]["publish"].append(dict(item, reason="custom event exists unpublished — publish"))
            missing = [p for p in params if _norm(p["name"]) not in _param_names(active_record)]
            if missing:
                plan["events"]["add_params"].append({
                    "name": name, "id": active_record.get("id"), "params": missing,
                    "reason": "params used by the game are missing on the existing custom event",
                })
            continue
        deleted_record = ev_deleted_by_name.get(name)
        if deleted_record is not None:
            plan["events"]["publish"].append({
                "name": name, "id": deleted_record.get("id"), "current_status": "deleted",
                "was_deleted": True,
                "reason": "soft-deleted custom event with the same name — publish the existing record, do NOT create",
            })
            missing = [p for p in params if _norm(p["name"]) not in _param_names(deleted_record)]
            if missing:
                plan["events"]["add_params"].append({
                    "name": name, "id": deleted_record.get("id"), "params": missing,
                    "reason": "params used by the game are missing on the re-published event",
                })
            continue
        ci_match = next((k for k in list(ev_custom_by_name) + list(ev_deleted_by_name)
                         if k.lower() == name.lower() and k != name), None)
        if ci_match is not None:
            plan["events"]["warnings"].append({
                "name": name, "dashboard_name": ci_match,
                "reason": "case-collision: manifest name matches a live custom event except for case — "
                          "names are byte-for-byte; a hand-normalized manifest would register a dead "
                          "duplicate that never receives events",
            })
        predef_hit = ev_predef_by_name.get(name) or next(
            (ev_predef_by_name[k] for k in ev_predef_by_name if k.lower() == name.lower()), None)
        if predef_hit is not None:
            plan["events"]["warnings"].append({
                "name": name, "dashboard_name": predef_hit.get("name"),
                "reason": "collision with a PREDEFINED dashboard event of the same (or case-variant) name — "
                          "this manifest entry is classified custom; creating it would duplicate the "
                          "predefined record. Re-check the producer's predefined/custom classification.",
            })
        plan["events"]["create"].append({
            "name": name,
            "params": params,
            "send_to_analytics": entry.get("send_to_analytics", True),
            "reason": "custom event not present on the dashboard",
        })

    # --- Predefined player fields in use: activate not_implemented ---
    for entry in fields.get("predefined_in_use") or []:
        path = _norm(entry.get("path"))
        if not path:
            continue
        manifest_field_paths.add(path)
        record = pf_predef_by_path.get(path)
        if record is None:
            plan["player_fields"]["warnings"].append({
                "path": path,
                "reason": "predefined player field not found on the dashboard — check the path",
            })
            continue
        item = {"path": path, "name": record.get("name"), "id": record.get("id"),
                "current_state": record.get("state") or record.get("status")}
        if _item_state(record) == "active":
            plan["player_fields"]["already_ok"].append(dict(item, reason="predefined field already active"))
        else:
            plan["player_fields"]["activate"].append(dict(item, reason="predefined field in use by the game — activate"))

    # --- Custom player fields: create / activate / reactivate-deleted ---
    for entry in fields.get("custom") or []:
        path = _norm(entry.get("path"))
        if not path:
            continue
        manifest_field_paths.add(path)
        kind = (entry.get("kind") or "").strip()
        if kind not in FIELD_KINDS:
            plan["unsupported"].append({
                "surface": "player_field",
                "name": entry.get("property") or path,
                "path": path,
                "kind": kind,
                "reason": f"kind '{kind}' has no Dashboard player-field kind — the value still ships in "
                          "player state (returned by GetPlayerState), but the field is NOT registrable, "
                          "so it cannot be used in triggers or audience segments",
            })
            continue
        active_record = pf_custom_by_path.get(path)
        if active_record is not None:
            rec_kind = (active_record.get("kind") or "").strip()
            if rec_kind and rec_kind != kind:
                plan["player_fields"]["warnings"].append({
                    "path": path, "manifest_kind": kind, "dashboard_kind": rec_kind,
                    "reason": f"kind drift: the game defines '{path}' as '{kind}' but the dashboard has "
                              f"it as '{rec_kind}' — the helpers cannot change a field's kind (no edit "
                              "endpoint); reconcile on the dashboard or align the game code",
                })
            item = {"path": path, "name": active_record.get("name"), "id": active_record.get("id"),
                    "current_state": active_record.get("state") or active_record.get("status")}
            if _item_state(active_record) == "active":
                plan["player_fields"]["already_ok"].append(dict(item, reason="custom field already active"))
            else:
                plan["player_fields"]["activate"].append(dict(item, reason="custom field exists inactive — activate"))
            continue
        deleted_record = pf_deleted_by_path.get(path)
        if deleted_record is not None:
            plan["player_fields"]["activate"].append({
                "path": path, "name": deleted_record.get("name"), "id": deleted_record.get("id"),
                "current_state": "deleted", "was_deleted": True,
                "reason": "soft-deleted custom field with the same path — activate the existing record, do NOT create",
            })
            continue
        ci_match = next((k for k in list(pf_custom_by_path) + list(pf_deleted_by_path)
                         if k.lower() == path.lower() and k != path), None)
        if ci_match is not None:
            plan["player_fields"]["warnings"].append({
                "path": path, "dashboard_path": ci_match,
                "reason": "case-collision: manifest path matches a live custom field except for case — "
                          "paths are byte-for-byte; a hand-normalized manifest would register a dead "
                          "duplicate that never receives state",
            })
        predef_hit = pf_predef_by_path.get(path) or next(
            (pf_predef_by_path[k] for k in pf_predef_by_path if k.lower() == path.lower()), None)
        if predef_hit is not None:
            plan["player_fields"]["warnings"].append({
                "path": path, "dashboard_path": predef_hit.get("path"),
                "reason": "collision with a PREDEFINED dashboard field of the same (or case-variant) path — "
                          "this manifest entry is classified custom; creating it would duplicate the "
                          "predefined record. Re-check the producer's predefined/custom classification.",
            })
        # default_value is deliberately NOT forwarded: the live API 422-rejects it
        # for non-calculated fields, and manifest fields are code-backed, never calculated.
        plan["player_fields"]["create"].append({
            "name": entry.get("name") or entry.get("property") or path,
            "path": path,
            "kind": kind,
            "extra": entry.get("extra") or "",
            "reason": "custom field not present on the dashboard",
        })

    # --- Publishing replaces the record under a NEW id: flag add_params entries whose
    #     target event is also being published this run, so the executor re-resolves the id. ---
    published_names = {_norm(item.get("name")) for item in plan["events"]["publish"]}
    for item in plan["events"]["add_params"]:
        if _norm(item.get("name")) in published_names:
            item["resolve_id_after_publish"] = True

    # --- System-param collision advisory: warn, never block (manifest is byte-for-byte). ---
    for item in plan["events"]["create"] + plan["events"]["add_params"]:
        for p in item.get("params") or []:
            if _norm(p.get("name")) in SYSTEM_EVENT_PARAM_NAMES:
                plan["events"]["warnings"].append({
                    "name": item.get("name"), "param": p.get("name"),
                    "reason": f"system-param collision: '{p.get('name')}' matches a dashboard system "
                              "event param — on create the server silently drops its system column in "
                              "favour of this operator param; on add-params the helper skips it as "
                              "already existing. Rename the param in game code.",
                })

    # --- Informational: dashboard ACTIVE entities the manifest doesn't mention. Never deleted. ---
    for name, record in ev_custom_by_name.items():
        if name not in manifest_event_names and _item_state(record) == "active":
            plan["dashboard_only"]["events"].append({"name": name, "id": record.get("id")})
    for path, record in pf_custom_by_path.items():
        if path not in manifest_field_paths and _item_state(record) == "active":
            plan["dashboard_only"]["player_fields"].append({"path": path, "id": record.get("id")})

    return plan


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_sdk_sync_plan", description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--events-predefined", required=True)
    parser.add_argument("--events-custom", required=True)
    parser.add_argument("--events-custom-deleted", default=None)
    parser.add_argument("--fields-predefined", required=True)
    parser.add_argument("--fields-custom", required=True)
    parser.add_argument("--fields-custom-deleted", default=None)
    args = parser.parse_args(argv)

    manifest = _load_json(args.manifest, "manifest")
    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_VERSIONS:
        _fail("unsupported_manifest_version",
              f"manifest schema_version {manifest.get('schema_version')!r} not in {SUPPORTED_MANIFEST_VERSIONS}")
    if manifest.get("integration_type") != "SDK":
        _fail("wrong_integration_type",
              f"manifest integration_type is {manifest.get('integration_type')!r}, expected 'SDK' — "
              "this planner only serves SDK-integrated games")

    listings = {
        "events-predefined": _extract_items(_load_json(args.events_predefined, "events-predefined"), "events-predefined"),
        "events-custom": _extract_items(_load_json(args.events_custom, "events-custom"), "events-custom"),
        "events-custom-deleted": _extract_items(_load_json(args.events_custom_deleted, "events-custom-deleted"), "events-custom-deleted")
        if args.events_custom_deleted else [],
        "fields-predefined": _extract_items(_load_json(args.fields_predefined, "fields-predefined"), "fields-predefined"),
        "fields-custom": _extract_items(_load_json(args.fields_custom, "fields-custom"), "fields-custom"),
        "fields-custom-deleted": _extract_items(_load_json(args.fields_custom_deleted, "fields-custom-deleted"), "fields-custom-deleted")
        if args.fields_custom_deleted else [],
    }

    # Cross-game backstop: every listing record carries the game it belongs to
    # (events: game_id, fields: gameId). A session.env left over from ANOTHER game
    # would have fetched that other game's records — applying this manifest's plan
    # to it would pollute the wrong dashboard. Fatal, not a warning.
    manifest_game = str(manifest.get("game_id") or "").strip().lower()
    if manifest_game:
        for source, items in listings.items():
            for record in items:
                record_game = str(record.get("game_id") or record.get("gameId") or "").strip().lower()
                if record_game and record_game != manifest_game:
                    _fail("listing_game_mismatch",
                          f"{source} contains records for game {record_game} but the manifest is for "
                          f"game {manifest_game} — the session credentials point at a different game; "
                          "re-run kinoa-init for the manifest's game and re-fetch")

    plan = build_plan(
        manifest,
        listings["events-predefined"],
        listings["events-custom"],
        listings["events-custom-deleted"],
        listings["fields-predefined"],
        listings["fields-custom"],
        listings["fields-custom-deleted"],
    )
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
