#!/usr/bin/env python3
"""
Kinoa Dashboard Feature Settings — admin-API wrapper for the feature-settings
domain: schemas, settings, and configurations. Plus the public runtime read
(featureset.kinoa.io) used to verify that a player actually resolves a config.

Self-contained. Reads bearer token, game id, and game secret from
~/.kinoa/session.env (written by kinoa-init). Mixing admin (bearer) and runtime
(game secret) auth is intentional: admin subcommands talk to dashboard.kinoa.io,
the single `get-config` read talks to the public featureset.kinoa.io host.

Three resources stack up: a SCHEMA (typed columns) has one or more VERSIONS; a
SETTING binds a runtime `key` to a schema; a CONFIGURATION holds the actual data
rows for one schema version under a setting and has its own lifecycle (DRAFT →
publish). The runtime fetches by setting `key` + schema `version` number.

Subcommands
-----------
Schemas (https://dashboard.kinoa.io/featuresettingsapi/schemas):
  list-schemas [--rows N]
      GET /schemas
  active-schemas-meta
      GET /schemas/active/meta — id+name of ACTIVE schemas, handy for selection.
  get-schema --schema-id UUID
      GET /schemas/{id} — full record incl. versions[].tableFields.
  latest-version --schema-id UUID
      GET /schemas/{id} then print the newest version (max numeric `version`)
      as {schema_version_id, version}. This is the binding a configuration needs.
  create-schema (--body-file PATH | --name NAME [--fields-file PATH | --fields-json JSON] [--description D])
      POST /schemas — creates a DRAFT schema. Pass a full SchemaDto via
      --body-file/stdin (e.g. produced by kinoa-csv-schema-infer), OR build a
      single-version schema from --name + a tableFields JSON array.
  publish-schema --schema-id UUID
      POST /schemas/{id}/publish — DRAFT → ACTIVE. Required before a setting can
      bind it in production.

Settings (https://dashboard.kinoa.io/featuresettingsapi/settings):
  list-settings [--rows N]
      GET /settings
  get-setting --setting-id UUID
      GET /settings/{id}
  create-setting --key KEY --name NAME --schema-id UUID [--description D]
      POST /settings — `key` is the runtime lookup key. No version, no status.

Configurations (https://dashboard.kinoa.io/featuresettingsapi/configurations):
  list-configs --setting-id UUID [--rows N]
      GET /settings/{id}/configurations
  get-configuration --config-id UUID
      GET /configurations/{id}
  create-config --setting-id UUID --schema-id UUID --schema-version-id UUID --name NAME [--default] [--description D] [--priority N]
      POST /configurations — creates a DRAFT configuration with no data yet. Fetches
      the schema to auto-build the required tableColumns (one per field) and sends
      status DRAFT. Pass --default for a config that resolves for any player
      (getDefault); a default config needs no segmentation.
  import-config-data --config-id UUID --csv PATH
      PUT /configurations/{id}/import — multipart upload of the CSV holding the
      data rows (header row must match the schema field names).
  submit-config --config-id UUID
      PATCH status DRAFT → IN_REVIEW (JSON-patch on /status). Required before
      publish: the lifecycle is DRAFT → IN_REVIEW → SCHEDULED.
  mark-config-default --config-id UUID
      PATCH /configurations/{id}/mark-as-default — promote an already-published
      (SCHEDULED/ACTIVE/PAUSED) config to default. For a fresh config prefer
      create-config --default, since mark-as-default rejects a DRAFT config.
  publish-config --config-id UUID
      POST /configurations/{id}/publish — IN_REVIEW → SCHEDULED (then auto-ACTIVE
      once the start time passes; visible at runtime, with a short propagation lag).
  add-test-players --config-id UUID --player-id ID [--player-id ID ...]
      POST /configurations/{id}/test-players — let specific players resolve a
      not-yet-public configuration.
  test-config --config-id UUID --player-id UUID
      GET /configurations/{id}/test/{playerId} — admin-side resolve of the config
      for a player (data + filters), without going through runtime.
  delete-config --config-id UUID
      DELETE /configurations/{id}

Runtime read (https://featureset.kinoa.io, public game-secret auth):
  get-config --setting-key KEY --player-id UUID [--version V] [--get-default]
      POST /features-configurations — exactly what the application does at
      runtime. Returns the resolved config (or status KEY_NOT_FOUND /
      VERSION_NOT_FOUND / DEFAULT_NOT_FOUND). Use to verify the integration.

Schema column types (for --fields-json / kinoa-csv-schema-infer):
  integer, number, long, boolean, string, long_string, bundle_key, date,
  enumeration, version, object
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SESSION_DIR = os.path.expanduser("~/.kinoa")
SESSION_ENV_PATH = os.path.join(SESSION_DIR, "session.env")

BASE = "https://dashboard.kinoa.io/featuresettingsapi"
SCHEMAS_URL = f"{BASE}/schemas"
SETTINGS_URL = f"{BASE}/settings"
CONFIGURATIONS_URL = f"{BASE}/configurations"
FEATURE_CONFIGURATIONS_URL = "https://featureset.kinoa.io/features-configurations"

SCHEMA_COLUMN_TYPES = (
    "integer",
    "number",
    "long",
    "boolean",
    "string",
    "long_string",
    "bundle_key",
    "date",
    "enumeration",
    "version",
    "object",
)


def _load_session_env():
    if not os.path.exists(SESSION_ENV_PATH):
        return
    with open(SESSION_ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key and key not in os.environ:
                os.environ[key] = value


_load_session_env()


def _request(method, url, headers=None, body=None, content_type="application/json"):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Content-Type", content_type)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, raw
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"


def _multipart_put(url, headers, field_name, filename, file_bytes, part_content_type="text/csv"):
    """PUT a single file as multipart/form-data (urllib has no native helper)."""
    boundary = "----KinoaFeatureSettingsBoundaryQ1W2E3R4"
    crlf = b"\r\n"
    body = b"".join([
        f"--{boundary}".encode(), crlf,
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode(), crlf,
        f"Content-Type: {part_content_type}".encode(), crlf, crlf,
        file_bytes, crlf,
        f"--{boundary}--".encode(), crlf,
    ])
    headers = dict(headers)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, raw
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"


def _parse_json(raw):
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _admin_headers():
    bearer = os.environ.get("KINOA_BEARER_TOKEN")
    game_id = os.environ.get("KINOA_GAME_ID")
    missing = [k for k, v in (("KINOA_BEARER_TOKEN", bearer), ("KINOA_GAME_ID", game_id)) if not v]
    if missing:
        print(json.dumps({
            "error": "missing_credentials",
            "missing": missing,
            "hint": "Run /kinoa-init first.",
        }, indent=2))
        sys.exit(2)
    return {"Authorization": f"Bearer {bearer}", "Game": game_id, "Game-Id": game_id}


def _public_headers():
    secret = os.environ.get("KINOA_GAME_SECRET")
    if not secret:
        print(json.dumps({
            "error": "missing_credentials",
            "missing": ["KINOA_GAME_SECRET"],
            "hint": "Run /kinoa-init first.",
        }, indent=2))
        sys.exit(2)
    return {"game": secret}


def _emit(status, **extra):
    payload = {"http_status": status, "ok": 200 <= status < 300}
    payload.update(extra)
    print(json.dumps(payload, indent=2))
    return 0 if 200 <= status < 300 else 1


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
def cmd_list_schemas(args):
    qs = urllib.parse.urlencode({"page": "0", "rows": str(args.rows)})
    status, raw = _request("GET", f"{SCHEMAS_URL}?{qs}", headers=_admin_headers())
    return _emit(status, response=_parse_json(raw) or raw)


def cmd_active_schemas_meta(args):
    status, raw = _request("GET", f"{SCHEMAS_URL}/active/meta", headers=_admin_headers())
    return _emit(status, response=_parse_json(raw) or raw)


def cmd_get_schema(args):
    status, raw = _request("GET", f"{SCHEMAS_URL}/{args.schema_id}", headers=_admin_headers())
    return _emit(status, schema_id=args.schema_id, response=_parse_json(raw) or raw)


def _pick_latest_version(schema):
    """Newest version = the largest numeric `version`. Falls back to max `order`."""
    versions = (schema or {}).get("versions") or []
    if not versions:
        return None

    def sort_key(v):
        raw = v.get("version")
        try:
            return (1, float(raw))
        except (TypeError, ValueError):
            return (0, v.get("order") or 0)

    return max(versions, key=sort_key)


def cmd_latest_version(args):
    status, raw = _request("GET", f"{SCHEMAS_URL}/{args.schema_id}", headers=_admin_headers())
    if not (200 <= status < 300):
        return _emit(status, schema_id=args.schema_id, error="fetch_failed", response=_parse_json(raw) or raw)
    schema = _parse_json(raw)
    latest = _pick_latest_version(schema if isinstance(schema, dict) else {})
    if not latest:
        return _emit(status, schema_id=args.schema_id, error="no_versions", response=schema)
    return _emit(status,
                 schema_id=args.schema_id,
                 schema_name=(schema or {}).get("name"),
                 schema_status=(schema or {}).get("status"),
                 version=latest.get("version"),
                 schema_version_id=latest.get("id"),
                 version_status=latest.get("status"))


def _normalize_fields(fields):
    """Fill in order/level/isRequired defaults so manual callers stay terse."""
    out = []
    for i, f in enumerate(fields):
        out.append({
            "name": f["name"],
            "type": f["type"],
            "isRequired": f.get("isRequired", True),
            "level": f.get("level", 1),
            "order": f.get("order", i),
        })
    return out


def _read_text_arg(path_value, inline_value):
    if path_value:
        with open(path_value, "r") as fh:
            return fh.read()
    if inline_value:
        return inline_value
    # No path, no inline → read stdin if it is piped.
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def cmd_create_schema(args):
    # Path 1: a full SchemaDto provided directly (e.g. from kinoa-csv-schema-infer).
    body_text = _read_text_arg(args.body_file, None)
    if body_text.strip():
        body = _parse_json(body_text)
        if not isinstance(body, dict):
            print(json.dumps({"error": "invalid_body", "hint": "--body-file/stdin must be a JSON object (SchemaDto)."}, indent=2))
            return 2
    else:
        # Path 2: build a single-version schema from --name + tableFields.
        if not args.name:
            print(json.dumps({"error": "missing_name", "hint": "Provide --body-file/stdin (full SchemaDto) or --name plus fields."}, indent=2))
            return 2
        fields_text = _read_text_arg(args.fields_file, args.fields_json)
        fields = _parse_json(fields_text) if fields_text.strip() else []
        if fields is None or not isinstance(fields, list):
            print(json.dumps({"error": "invalid_fields", "hint": "--fields-json/--fields-file must be a JSON array of {name,type,...}."}, indent=2))
            return 2
        body = {
            "name": args.name,
            "description": args.description or None,
            "versions": [{
                "version": "1",
                "order": 0,
                "useRanges": False,
                "tableFields": _normalize_fields(fields),
                "tableColumns": [],
                "tableFilters": [],
            }],
        }
    status, raw = _request("POST", SCHEMAS_URL, headers=_admin_headers(), body=body)
    return _emit(status, request_body=body, response=_parse_json(raw) or raw)


def cmd_publish_schema(args):
    status, raw = _request("POST", f"{SCHEMAS_URL}/{args.schema_id}/publish", headers=_admin_headers())
    return _emit(status, schema_id=args.schema_id, response=_parse_json(raw) or raw)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def cmd_list_settings(args):
    qs = urllib.parse.urlencode({"page": "0", "rows": str(args.rows)})
    status, raw = _request("GET", f"{SETTINGS_URL}?{qs}", headers=_admin_headers())
    return _emit(status, response=_parse_json(raw) or raw)


def cmd_get_setting(args):
    status, raw = _request("GET", f"{SETTINGS_URL}/{args.setting_id}", headers=_admin_headers())
    return _emit(status, setting_id=args.setting_id, response=_parse_json(raw) or raw)


def cmd_create_setting(args):
    body = {
        "key": args.key,
        "name": args.name,
        "description": args.description or None,
        "schemaId": args.schema_id,
    }
    status, raw = _request("POST", SETTINGS_URL, headers=_admin_headers(), body=body)
    return _emit(status, request_body=body, response=_parse_json(raw) or raw)


# --------------------------------------------------------------------------- #
# Configurations
# --------------------------------------------------------------------------- #
def cmd_list_configs(args):
    qs = urllib.parse.urlencode({"page": "0", "rows": str(args.rows)})
    url = f"{SETTINGS_URL}/{args.setting_id}/configurations?{qs}"
    status, raw = _request("GET", url, headers=_admin_headers())
    return _emit(status, setting_id=args.setting_id, response=_parse_json(raw) or raw)


def cmd_get_configuration(args):
    status, raw = _request("GET", f"{CONFIGURATIONS_URL}/{args.config_id}", headers=_admin_headers())
    return _emit(status, config_id=args.config_id, response=_parse_json(raw) or raw)


def _columns_from_fields(fields):
    """Every schema tableField needs exactly one non-filter tableColumn, else the
    backend rejects the config with "Columns are absent ... fields are present"."""
    return [{
        "name": f.get("name"),
        "fieldId": f.get("id"),
        "fieldName": f.get("name"),
        "isFilter": False,
        "order": i,
        "type": f.get("type"),
    } for i, f in enumerate(fields)]


def cmd_create_config(args):
    # Fetch the schema to mirror its version's fields into tableColumns. The
    # backend's validateColumns requires one column per field; validateSegmentation
    # requires status DRAFT (or isDefault) when there's no segmentation.
    s_status, s_raw = _request("GET", f"{SCHEMAS_URL}/{args.schema_id}", headers=_admin_headers())
    if not (200 <= s_status < 300):
        return _emit(s_status, error="schema_fetch_failed", schema_id=args.schema_id,
                     response=_parse_json(s_raw) or s_raw)
    schema = _parse_json(s_raw) or {}
    version = next((v for v in (schema.get("versions") or []) if v.get("id") == args.schema_version_id), None)
    if version is None:
        return _emit(s_status, error="version_not_found", schema_id=args.schema_id,
                     schema_version_id=args.schema_version_id,
                     hint="Run latest-version to get a valid schema_version_id.")
    table_columns = _columns_from_fields(version.get("tableFields") or [])

    body = {
        "name": args.name,
        "description": args.description or None,
        "settingId": args.setting_id,
        "schemaVersionId": args.schema_version_id,
        "status": "DRAFT",
        "priority": args.priority,
        "tableColumns": table_columns,
        "tableFilters": [],
        "isDefault": bool(args.default),
    }
    status, raw = _request("POST", CONFIGURATIONS_URL, headers=_admin_headers(), body=body)
    return _emit(status, request_body=body, response=_parse_json(raw) or raw)


def cmd_import_config_data(args):
    if not os.path.exists(args.csv):
        print(json.dumps({"error": "file_not_found", "path": args.csv}, indent=2))
        return 2
    with open(args.csv, "rb") as fh:
        file_bytes = fh.read()
    url = f"{CONFIGURATIONS_URL}/{args.config_id}/import"
    status, raw = _multipart_put(
        url, _admin_headers(), "file", os.path.basename(args.csv), file_bytes
    )
    return _emit(status, config_id=args.config_id, csv=args.csv, response=_parse_json(raw) or raw)


def cmd_mark_config_default(args):
    # The endpoint consumes application/json-patch+json; the body is unused, so
    # an empty patch document satisfies the content negotiation.
    status, raw = _request(
        "PATCH",
        f"{CONFIGURATIONS_URL}/{args.config_id}/mark-as-default",
        headers=_admin_headers(),
        body=[],
        content_type="application/json-patch+json",
    )
    return _emit(status, config_id=args.config_id, response=_parse_json(raw) or raw)


def cmd_submit_config(args):
    # The status state machine is DRAFT → IN_REVIEW → SCHEDULED. The /publish
    # endpoint only accepts an IN_REVIEW config, so a DRAFT must first be moved to
    # IN_REVIEW via a JSON-patch on /status.
    patch = [{"op": "replace", "path": "/status", "value": "IN_REVIEW"}]
    status, raw = _request(
        "PATCH", f"{CONFIGURATIONS_URL}/{args.config_id}",
        headers=_admin_headers(), body=patch,
        content_type="application/json-patch+json",
    )
    return _emit(status, config_id=args.config_id, response=_parse_json(raw) or raw)


def cmd_publish_config(args):
    status, raw = _request("POST", f"{CONFIGURATIONS_URL}/{args.config_id}/publish", headers=_admin_headers())
    return _emit(status, config_id=args.config_id, response=_parse_json(raw) or raw)


def cmd_add_test_players(args):
    body = list(dict.fromkeys(args.player_id))  # de-dupe, preserve order
    status, raw = _request(
        "POST", f"{CONFIGURATIONS_URL}/{args.config_id}/test-players",
        headers=_admin_headers(), body=body,
    )
    return _emit(status, config_id=args.config_id, player_ids=body, response=_parse_json(raw) or raw)


def cmd_test_config(args):
    url = f"{CONFIGURATIONS_URL}/{args.config_id}/test/{args.player_id}"
    status, raw = _request("GET", url, headers=_admin_headers())
    return _emit(status, config_id=args.config_id, player_id=args.player_id, response=_parse_json(raw) or raw)


def cmd_delete_config(args):
    status, raw = _request("DELETE", f"{CONFIGURATIONS_URL}/{args.config_id}", headers=_admin_headers())
    return _emit(status, config_id=args.config_id, response=_parse_json(raw) or raw)


# --------------------------------------------------------------------------- #
# Runtime read (public)
# --------------------------------------------------------------------------- #
def cmd_get_config(args):
    setting = {"key": args.setting_key, "getDefault": bool(args.get_default)}
    if args.version:
        setting["version"] = args.version
    body = {"settings": [setting], "playerId": args.player_id}
    status, raw = _request("POST", FEATURE_CONFIGURATIONS_URL, headers=_public_headers(), body=body)
    return _emit(status, request_body=body, response=_parse_json(raw) or raw)


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_dashboard_feature_settings", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Schemas
    p = sub.add_parser("list-schemas", help="GET all schemas.")
    p.add_argument("--rows", type=int, default=100)
    p.set_defaults(func=cmd_list_schemas)

    p = sub.add_parser("active-schemas-meta", help="GET id+name of ACTIVE schemas.")
    p.set_defaults(func=cmd_active_schemas_meta)

    p = sub.add_parser("get-schema", help="GET a schema by id (full record).")
    p.add_argument("--schema-id", required=True)
    p.set_defaults(func=cmd_get_schema)

    p = sub.add_parser("latest-version", help="Print the newest version {schema_version_id, version} of a schema.")
    p.add_argument("--schema-id", required=True)
    p.set_defaults(func=cmd_latest_version)

    p = sub.add_parser("create-schema", help="POST a schema (DRAFT). Full body via --body-file/stdin, or --name + fields.")
    p.add_argument("--body-file", help="Path to a full SchemaDto JSON (e.g. from kinoa-csv-schema-infer). '-' or omit to read stdin.")
    p.add_argument("--name", help="Schema name (when not using --body-file).")
    p.add_argument("--description", default="")
    p.add_argument("--fields-file", help="Path to a JSON array of tableFields.")
    p.add_argument("--fields-json", default="", help="Inline JSON array of tableFields: [{\"name\":\"x\",\"type\":\"integer\"}].")
    p.set_defaults(func=cmd_create_schema)

    p = sub.add_parser("publish-schema", help="POST /schemas/{id}/publish (DRAFT → ACTIVE).")
    p.add_argument("--schema-id", required=True)
    p.set_defaults(func=cmd_publish_schema)

    # Settings
    p = sub.add_parser("list-settings", help="GET all settings.")
    p.add_argument("--rows", type=int, default=100)
    p.set_defaults(func=cmd_list_settings)

    p = sub.add_parser("get-setting", help="GET a setting by id.")
    p.add_argument("--setting-id", required=True)
    p.set_defaults(func=cmd_get_setting)

    p = sub.add_parser("create-setting", help="POST a setting binding a runtime key to a schema.")
    p.add_argument("--key", required=True, help="Runtime lookup key, e.g. BoostersConfig.")
    p.add_argument("--name", required=True)
    p.add_argument("--schema-id", required=True)
    p.add_argument("--description", default="")
    p.set_defaults(func=cmd_create_setting)

    # Configurations
    p = sub.add_parser("list-configs", help="GET configurations of a setting.")
    p.add_argument("--setting-id", required=True)
    p.add_argument("--rows", type=int, default=100)
    p.set_defaults(func=cmd_list_configs)

    p = sub.add_parser("get-configuration", help="GET a configuration by id.")
    p.add_argument("--config-id", required=True)
    p.set_defaults(func=cmd_get_configuration)

    p = sub.add_parser("create-config", help="POST a DRAFT configuration (no data yet); auto-builds tableColumns from the schema.")
    p.add_argument("--setting-id", required=True)
    p.add_argument("--schema-id", required=True, help="UUID of the schema (used to mirror its fields into tableColumns).")
    p.add_argument("--schema-version-id", required=True, help="UUID of the schema version (see latest-version).")
    p.add_argument("--name", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--priority", type=int, default=None)
    p.add_argument("--default", action="store_true", help="Set isDefault=true at creation (resolves for any player with getDefault).")
    p.set_defaults(func=cmd_create_config)

    p = sub.add_parser("import-config-data", help="PUT a CSV of data rows into a configuration (multipart).")
    p.add_argument("--config-id", required=True)
    p.add_argument("--csv", required=True, help="Path to the CSV file (header row = schema field names).")
    p.set_defaults(func=cmd_import_config_data)

    p = sub.add_parser("mark-config-default", help="PATCH /configurations/{id}/mark-as-default (config must already be SCHEDULED/ACTIVE/PAUSED).")
    p.add_argument("--config-id", required=True)
    p.set_defaults(func=cmd_mark_config_default)

    p = sub.add_parser("submit-config", help="PATCH status DRAFT → IN_REVIEW (required before publish).")
    p.add_argument("--config-id", required=True)
    p.set_defaults(func=cmd_submit_config)

    p = sub.add_parser("publish-config", help="POST /configurations/{id}/publish (IN_REVIEW → SCHEDULED).")
    p.add_argument("--config-id", required=True)
    p.set_defaults(func=cmd_publish_config)

    p = sub.add_parser("add-test-players", help="POST test players who may resolve a non-public configuration.")
    p.add_argument("--config-id", required=True)
    p.add_argument("--player-id", action="append", required=True, help="Repeatable.")
    p.set_defaults(func=cmd_add_test_players)

    p = sub.add_parser("test-config", help="GET admin-side resolve of a config for a player (data + filters).")
    p.add_argument("--config-id", required=True)
    p.add_argument("--player-id", required=True)
    p.set_defaults(func=cmd_test_config)

    p = sub.add_parser("delete-config", help="DELETE a configuration.")
    p.add_argument("--config-id", required=True)
    p.set_defaults(func=cmd_delete_config)

    # Runtime read
    p = sub.add_parser("get-config", help="POST featureset.kinoa.io — resolve a config for a player (public auth).")
    p.add_argument("--setting-key", required=True)
    p.add_argument("--player-id", required=True)
    p.add_argument("--version", default=None, help="Schema version number, e.g. 1. Effectively required — omitting it yields VERSION_NOT_FOUND.")
    p.add_argument("--get-default", action="store_true", help="Fall back to the default configuration.")
    p.set_defaults(func=cmd_get_config)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
