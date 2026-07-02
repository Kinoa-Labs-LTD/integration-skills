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
SUPPORTED_MANIFEST_VERSIONS = (1, 2)  # 2 adds the feature_settings section

EVENT_PARAM_KINDS = ("number", "boolean", "string", "date", "enumeration", "string_array", "number_array")
FIELD_KINDS = ("number", "boolean", "string", "date", "long_string", "enumeration", "version")
# Feature-settings column kinds the OPERATOR can actually use (the FS UI dropdown). API values are
# lowercase. create-schema itself is looser — it accepts the full 11-value SchemaColumnType verbatim
# (a backend gap, live-probed 2026-06-26: no server-side type validation), so the producer maps every
# column down to these 5, and we fold live schema types through the same map before diffing so a code
# `string` never false-conflicts with a live `date`/`long_string` column.
FS_COLUMN_KINDS = ("integer", "number", "string", "boolean", "bundle_key")

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
    "events", "player_fields", "feature_settings", "unsupported_by_cli",
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


def _fs_normalize_kind(t):
    """Fold any column type to the operator's 5 FS kinds. The producer already maps to these;
    live schemas created elsewhere may carry finer SchemaColumnType values — folding both sides
    the same way stops a code `string` from false-conflicting with a live `date`/`long_string`."""
    t = (t or "").strip().lower()
    if t in ("integer", "long"):
        return "integer"
    if t in ("number", "decimal", "float", "double"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t in ("bundle_key", "bundlekey"):
        return "bundle_key"
    return "string"  # string, long_string, date, version, enumeration, object, arrays, unknown


def _fs_latest_version(record):
    """The schema's ACTIVE version (else the highest-numbered), or None."""
    versions = record.get("versions") or []
    if not versions:
        return None
    active = [v for v in versions if str(v.get("status") or "").strip().lower() == "active"]
    pool = active or versions

    def _vnum(v):
        try:
            return int(str(v.get("version")))
        except (TypeError, ValueError):
            return v.get("order") or 0

    return max(pool, key=_vnum)


def _fs_fields_map(record):
    """{normalized name: normalized FS kind} from a schema's active/latest version, or None when
    the listing carries no version fields (a summary-only list-schemas row — can't field-diff)."""
    ver = _fs_latest_version(record)
    if not ver or ver.get("tableFields") is None:
        return None
    out = {}
    for f in ver.get("tableFields") or []:
        if isinstance(f, dict) and f.get("name"):
            out[_norm(f["name"])] = _fs_normalize_kind(f.get("type"))
    return out


def build_plan(manifest, ev_predef, ev_custom, ev_custom_deleted, pf_predef, pf_custom, pf_custom_deleted,
               fs_schemas=None, fs_settings=None):
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "manifest_schema_version": manifest.get("schema_version"),
        "integration_type": manifest.get("integration_type"),
        "events": {"publish": [], "create": [], "add_params": [], "already_ok": [], "warnings": []},
        "player_fields": {"activate": [], "create": [], "already_ok": [], "warnings": []},
        "feature_settings": {"schema_create": [], "schema_publish": [], "setting_create": [],
                             "config_create": [], "config_publish": [], "version_conflict": [],
                             "already_ok": [], "warnings": []},
        "unsupported": list(manifest.get("unsupported_by_cli") or []),
        "dashboard_only": {"events": [], "player_fields": [], "feature_schemas": [], "feature_settings": []},
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

    # --- Feature settings: schemas (by name) + settings (by key) + default configs ---
    fs = manifest.get("feature_settings") or {}
    fsp = plan["feature_settings"]
    fs_schemas_by_name = _index_by(fs_schemas or [], "name")
    fs_settings_by_key = _index_by(fs_settings or [], "key")
    manifest_schema_names = set()
    manifest_setting_keys = set()
    creating_schema_names = set()
    live_active_version_by_schema = {}
    bundle_key_columns_by_schema = {}

    def _is_filter_or_placeholder(field_name):
        # Filters are configuration-level constructs (tableFilters bound to Player Fields), never
        # schema columns; and an unreplaced "<PlayerField>" scaffold is producer junk either way.
        n = (field_name or "")
        return n.startswith("filter: ") or "<" in n

    for sch in fs.get("schemas") or []:
        name = _norm(sch.get("name"))
        if not name:
            continue
        if name in manifest_schema_names:
            fsp["warnings"].append({
                "name": name,
                "reason": "duplicate schema name in the manifest — only the first entry is planned; "
                          "check the producer's suffix-strip rule for a class-name collision",
            })
            continue
        manifest_schema_names.add(name)
        want_fields, dropped = [], []
        for f in (sch.get("fields") or []):
            if _is_filter_or_placeholder(f.get("name")):
                dropped.append(f.get("name"))
                continue
            want_fields.append({"name": f.get("name"), "kind": _fs_normalize_kind(f.get("kind")),
                                "isRequired": f.get("is_required", True)})
        bk = [f["name"] for f in want_fields if f["kind"] == "bundle_key"]
        if bk:
            bundle_key_columns_by_schema[name] = bk
        if dropped:
            fsp["warnings"].append({
                "name": name, "dropped_columns": dropped,
                "reason": "filter-prefixed / placeholder properties are IncludeFilters readers, not schema "
                          "columns — excluded from the schema plan (filters are configuration-level, chosen "
                          "by the operator); the producer should not have emitted them",
            })
        live = fs_schemas_by_name.get(name)
        if live is None:
            ci = next((k for k in fs_schemas_by_name if k.lower() == name.lower() and k != name), None)
            if ci is not None:
                fsp["warnings"].append({
                    "name": name, "dashboard_name": ci,
                    "reason": "case-collision: manifest schema name matches a live schema except for case — "
                              "names are byte-for-byte; creating it would register a near-duplicate schema",
                })
            creating_schema_names.add(name)
            fsp["schema_create"].append({
                "name": name, "fields": want_fields,
                "reason": "feature schema not present on the dashboard — create, then publish if it is not auto-ACTIVE",
            })
            continue
        ver = _fs_latest_version(live)
        if ver is not None and ver.get("version") is not None:
            live_active_version_by_schema[name] = ver.get("version")
        item = {"name": name, "id": live.get("id"), "current_status": live.get("status")}
        live_fields = _fs_fields_map(live)
        if live_fields is not None:
            live_fields = {k: v for k, v in live_fields.items() if not _is_filter_or_placeholder(k)}
        if live_fields is None:
            fsp["already_ok"].append(dict(item,
                reason="feature schema exists — column shape NOT verified (no version fields in the listing); "
                       "fetch get-schema to confirm the columns match the code before relying on it"))
        else:
            want_map = {_norm(f["name"]): f["kind"] for f in want_fields}
            if want_map == live_fields:
                fsp["already_ok"].append(dict(item, reason="feature schema exists with matching column shape"))
            else:
                fsp["version_conflict"].append(dict(item,
                    code_only_columns=sorted(k for k in want_map if k not in live_fields),
                    dashboard_only_columns=sorted(k for k in live_fields if k not in want_map),
                    type_changed_columns=sorted(k for k in want_map if k in live_fields and want_map[k] != live_fields[k]),
                    reason="code column shape differs from the live ACTIVE schema version — the helpers cannot edit a "
                           "published version; needs a developer-approved NEW schema version, after which the code's "
                           "requested version at the four wiring sites must be re-aligned and Default Feature Settings.zip re-exported"))
        status = str(live.get("status") or "").strip().lower()
        if status and status != "active":
            fsp["schema_publish"].append(dict(item, reason="feature schema exists but is not ACTIVE — publish"))

    for st in fs.get("settings") or []:
        key = _norm(st.get("key"))
        if not key:
            continue
        if key in manifest_setting_keys:
            fsp["warnings"].append({
                "key": key,
                "reason": "duplicate setting key in the manifest — only the first entry is planned",
            })
            continue
        manifest_setting_keys.add(key)
        schema_name = _norm(st.get("schema_name"))
        version = st.get("version")
        # Dangling binding: a setting whose schema is neither in the manifest-created set nor live
        # can never resolve a schemaId at apply — the plan would be unexecutable for this key.
        if schema_name and schema_name not in creating_schema_names \
                and schema_name not in fs_schemas_by_name and schema_name not in manifest_schema_names:
            fsp["warnings"].append({
                "key": key, "schema_name": schema_name,
                "reason": "dangling schema_name: no schema with this name exists in the manifest or on the "
                          "dashboard — the setting cannot be bound; fix the producer's schemas[] section",
            })
        # Version-number sanity. A schema created THIS run starts at version "1"; an existing schema
        # must carry a live version matching the requested number, else runtime gets VERSION_NOT_FOUND.
        if schema_name in creating_schema_names and version is not None and str(version) != "1":
            fsp["warnings"].append({
                "key": key, "schema_name": schema_name, "requested_version": version,
                "reason": "the schema is being created this run, so its only version will be 1 — the code "
                          "requests a different version and would get VERSION_NOT_FOUND at runtime",
            })
        live_ver = live_active_version_by_schema.get(schema_name)
        if live_ver is not None and version is not None and str(live_ver) != str(version):
            fsp["warnings"].append({
                "key": key, "schema_name": schema_name,
                "requested_version": version, "live_active_version": live_ver,
                "reason": "the code requests a schema version that is not the live ACTIVE version — runtime would get "
                          "VERSION_NOT_FOUND; align the code's version or publish the matching schema version",
            })
        # Bundle dependency: seeded bundle_key values must (1) match the Bundle-key FORMAT — start
        # with a letter, then only letters/digits/_/- (no dots) — and (2) exist as Bundles; the
        # whole CSV import 422s otherwise (live-verified 2026-07-02: 'Import Failed: Line: 1.
        # [sku] is invalid bundle key'). Warn ahead of the checklist.
        bk_cols = bundle_key_columns_by_schema.get(schema_name)
        if bk_cols and st.get("seed_csv"):
            fsp["warnings"].append({
                "key": key, "schema_name": schema_name, "bundle_key_columns": bk_cols,
                "reason": "the seed import will be REJECTED (422 invalid bundle key) unless every value in "
                          "these columns is a valid Bundle key (starts with a letter; only letters, digits, "
                          "_ and -; no dots) AND already exists as a Bundle on the dashboard — fix/create "
                          "the Bundles first, or expect an empty default config + a manual re-import",
            })
        live = fs_settings_by_key.get(key)
        if live is not None:
            # Binding sanity: the live setting may point at a DIFFERENT schema than the code expects.
            live_schema = fs_schemas_by_name.get(schema_name)
            live_bound = _norm(live.get("schemaId") or live.get("schema_id"))
            if live_schema is not None and live_bound and _norm(live_schema.get("id")) != live_bound:
                fsp["warnings"].append({
                    "key": key, "schema_name": schema_name,
                    "live_schema_id": live_bound, "expected_schema_id": live_schema.get("id"),
                    "reason": "the live setting is bound to a different schema than the code's schema_name — "
                              "reconcile on the dashboard (the helpers cannot re-bind a setting)",
                })
            fsp["already_ok"].append({"surface": "setting", "key": key, "id": live.get("id"),
                                      "reason": "feature setting key already exists"})
            # Resume path: a prior partial run may have created the setting but died before its default
            # configuration was created/published. Conditional item — the executor first runs
            # list-configs for this setting and SKIPS when any configuration already exists.
            fsp["config_create"].append({
                "setting_key": key, "schema_name": schema_name, "default": True,
                "seed_csv": st.get("seed_csv"), "conditional": "only_if_no_configs",
                "reason": "existing setting — ensure a default configuration exists (create+seed only if the "
                          "setting has zero configurations; otherwise skip)",
            })
            fsp["config_publish"].append({
                "setting_key": key, "conditional": "only_if_no_configs",
                "reason": "publish the default configuration only if it was created by the conditional step above",
            })
            continue
        fsp["setting_create"].append({
            "key": key, "schema_name": schema_name, "version": version,
            "reason": "feature setting key not present — create (binds the schema by id)",
        })
        fsp["config_create"].append({
            "setting_key": key, "schema_name": schema_name, "default": True,
            "seed_csv": st.get("seed_csv"),
            "reason": "new setting — create a default configuration and seed it from the developer's CSV "
                      "(seed_csv, mirrored values; operator edits afterward), or empty when no seed_csv",
        })
        fsp["config_publish"].append({
            "setting_key": key,
            "reason": "publish the default configuration (submit -> publish) so the key resolves at runtime",
        })

    for name, record in fs_schemas_by_name.items():
        if name not in manifest_schema_names:
            plan["dashboard_only"]["feature_schemas"].append({"name": name, "id": record.get("id")})
    for key, record in fs_settings_by_key.items():
        if key not in manifest_setting_keys:
            plan["dashboard_only"]["feature_settings"].append({"key": key, "id": record.get("id")})
        ci = next((k for k in manifest_setting_keys if k.lower() == key.lower() and k != key), None)
        if ci is not None:
            fsp["warnings"].append({
                "key": ci, "dashboard_key": key,
                "reason": "case-collision: manifest setting key matches a live setting except for case — "
                          "keys are byte-for-byte; creating it would register a near-duplicate setting the "
                          "runtime never resolves for the code's key",
            })

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
    parser.add_argument("--fs-schemas", default=None,
                        help="Live feature schemas (list-schemas, ideally enriched with get-schema "
                             "records so versions[].tableFields are present for the column diff).")
    parser.add_argument("--fs-settings", default=None, help="Live feature settings (list-settings).")
    args = parser.parse_args(argv)

    manifest = _load_json(args.manifest, "manifest")
    # A v2 manifest with FS content but NO live FS listings would make the planner mistake
    # "not fetched" for "nothing on the dashboard" and plan duplicate creates. Fail closed.
    fs_section = manifest.get("feature_settings") or {}
    if (fs_section.get("schemas") or fs_section.get("settings")) and not (args.fs_schemas and args.fs_settings):
        _fail("missing_fs_listings",
              "the manifest carries feature_settings but --fs-schemas/--fs-settings listings were not "
              "supplied — fetch list-schemas and list-settings first (planning without them would plan "
              "duplicate creates against a dashboard that already has these entities)")
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
        "fs-schemas": _extract_items(_load_json(args.fs_schemas, "fs-schemas"), "fs-schemas") if args.fs_schemas else [],
        "fs-settings": _extract_items(_load_json(args.fs_settings, "fs-settings"), "fs-settings") if args.fs_settings else [],
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
        listings["fs-schemas"],
        listings["fs-settings"],
    )
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
