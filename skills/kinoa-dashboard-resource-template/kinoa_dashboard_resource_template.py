#!/usr/bin/env python3
"""
Kinoa Dashboard Resource Templates — manage Kinoa *resource templates* (the
bundles service's catalogue of sellable / awardable items — NOT internal
currency). List templates, fetch one, create a draft, update, activate a
draft to ACTIVE, deprecate an active one, clone, and delete (HARD delete,
DRAFT-only — see below).

Self-contained: no imports from sibling skills. Reads the bearer token and
game id from ~/.kinoa/session.env (written by kinoa-init).

Security boundary — ADMIN surface, skill-only:
  Base https://gate.kinoa.io/bundle/  (the bundles service, reached through
  the gateway). The `resource-templates` routes are bearer-secured admin
  routes: Authorization: Bearer <token> + Game-Id: <uuid>. NEVER embed these
  calls or the bearer token in application runtime code — the runtime/public
  surface for bundles is `public/resource-templates` with a game token, which
  this skill does not touch. gate.kinoa.io hosts BOTH surfaces; what makes a
  call admin is the bearer, not the host.

Subcommands (each makes ONE logical operation and prints ONE JSON object:
{ http_status, ok, response | request_body, ...context }):

  list [--rows N] [--statuses S1,S2] [--name SUBSTR] [--sort-by F] [--order asc|desc]
      GET https://gate.kinoa.io/bundle/resource-templates
      Returns SummaryListDto { total, summaries:[{id,name,key,status,fields,...}] }.
      --statuses filters by lifecycle status (DRAFT, ACTIVE, DEPRECATED);
      repeatable via comma. Use it as the closest analogue to a state probe
      (resource templates have no soft-delete — see delete below).

  get --id UUID
      GET .../resource-templates/<id>  — full ResourceTemplateDto incl. fields.

  create --name NAME --key KEY [--description D] [--status draft|active|deprecated]
         [--body JSON] [--field SPEC ...] [--fields-json JSON]
      POST .../resource-templates — creates a template (defaults to DRAFT so a
      later `activate` publishes it). Provide fields either as repeatable
      --field NAME:TYPE[:EXTRA][:req] specs (quick CLI use) or as a single
      --fields-json array (used by the sync workflow after the developer
      confirms the list on the HTML page). TYPE ∈ number, string, boolean,
      date, enumeration; for enumeration EXTRA is the comma-separated allowed
      values. KEY must match ^[a-zA-Z][a-zA-Z0-9_-]*$.

  update --id UUID [--name] [--key] [--description] [--status] [--body] [--field ...] [--fields-json]
      Two-step: GET the current template, apply only the provided overrides
      (PUT is a full replace, so unspecified fields are preserved from the
      current record), PUT .../resource-templates/<id>.

  activate --id UUID
      POST .../resource-templates/<id>/activate — flips DRAFT -> ACTIVE
      (publishes the template so it can be used in bundles / prizes).

  deprecate --id UUID [--reason TEXT]
      POST .../resource-templates/<id>/deprecate — flips -> DEPRECATED. Use
      this instead of delete for a template that is already ACTIVE.

  clone --id UUID [--key KEY] [--name NAME]
      POST .../resource-templates/<id>/clone — copies an existing template
      (new key/name if given).

  delete --id UUID
      DELETE .../resource-templates/<id>
      HARD delete and DRAFT-ONLY: the server returns 409 CONFLICT ("Cannot
      delete template for this status") for ACTIVE or DEPRECATED templates —
      those must be deprecated, not deleted. A DRAFT delete is irreversible
      (the row and its enumeration are removed); the only recovery is create
      under a new id. Never invoke from within a sync/orchestration run —
      operator-initiated admin sessions only, after listing and confirming the
      resolved id. MANDATORY confirmation before running (the workflow asks via
      AskUserQuestion, naming the resolved id + name and the delete semantics).

Cross-game backstop: every MUTATING subcommand accepts --expect-game UUID and
aborts with error=session_game_mismatch (exit 2) unless session.env's
KINOA_GAME_ID equals it — guarding against a stale session from another game
(here an irreversible HARD delete or a create against the wrong game).
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

RESOURCE_TEMPLATES_URL = "https://gate.kinoa.io/bundle/resource-templates"

ALLOWED_FIELD_TYPES = ("number", "string", "boolean", "date", "enumeration")
ALLOWED_STATUSES = ("draft", "active", "deprecated")
RESOURCE_KEY_RE = r"^[a-zA-Z][a-zA-Z0-9_-]*$"


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


def _request(method, url, headers=None, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
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
    """Bundles admin auth: bearer + Game-Id. Distinct from gamemetaapi, which
    also wants a `Game` header — bundles reads only Game-Id, so we send just
    that to match the resource-templates controller exactly."""
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
    return {"Authorization": f"Bearer {bearer}", "Game-Id": game_id}


def _guard_expected_game(args):
    """Cross-game backstop. Mirrors kinoa_dashboard_event's check: when the
    caller passes --expect-game, it must equal the game the session credentials
    point at (KINOA_GAME_ID). A stale session.env left over from ANOTHER game
    would otherwise mutate the WRONG game's dashboard (here an irreversible HARD
    delete, or a create against the wrong game). Fatal, before any
    state-changing call. Read-only and flagless calls are unaffected."""
    expected = getattr(args, "expect_game", None)
    if not expected:
        return
    session_game = (os.environ.get("KINOA_GAME_ID") or "").strip()
    if expected.strip().lower() != session_game.lower():
        print(json.dumps({
            "error": "session_game_mismatch",
            "expected_game": expected,
            "session_game": session_game or None,
            "hint": "session.env points at a different game than --expect-game. "
                    "Re-run /kinoa-init for the intended game before retrying.",
        }, indent=2))
        sys.exit(2)


def _parse_field_spec(spec):
    """
    Parse "name:type[:extra][:req]" -> a ResourceTemplateDto field object.
    Examples:
      'gold:number'                          -> {name, field_type: number, required: False}
      'title:string:req'                     -> {name, field_type: string, required: True}
      'rarity:enumeration:common,rare,epic'  -> {name, field_type: enumeration, required: False,
                                                  enumeration_values: [common, rare, epic]}
      'rarity:enumeration:common,rare:req'   -> ... required: True
    Trailing 'req'/'required' token marks the field required. For enumeration
    the comma-bearing token is the allowed-values list.
    """
    parts = spec.split(":")
    if len(parts) < 2 or not parts[0]:
        raise ValueError(f"expected NAME:TYPE[:EXTRA][:req], got: {spec!r}")
    name, ftype = parts[0], parts[1]
    if ftype not in ALLOWED_FIELD_TYPES:
        raise ValueError(f"field type must be one of {ALLOWED_FIELD_TYPES}, got {ftype!r}")
    flags = parts[2:]
    required = any(f.lower() in ("req", "required") for f in flags)
    enum_values = None
    for f in flags:
        if f.lower() in ("req", "required"):
            continue
        enum_values = [v.strip() for v in f.split(",") if v.strip()]
        break
    if ftype == "enumeration" and not enum_values:
        raise ValueError(f"enumeration field requires allowed values, e.g. {name}:enumeration:v1,v2")
    field = {"name": name, "field_type": ftype, "required": required}
    if enum_values is not None:
        field["enumeration_values"] = enum_values
    return field


def _collect_fields(args):
    """Build the fields list from --fields-json (takes precedence) or repeatable
    --field specs. Returns (fields_list_or_None, error_dict_or_None)."""
    fields_json = getattr(args, "fields_json", None)
    if fields_json:
        parsed = _parse_json(fields_json)
        if not isinstance(parsed, list):
            return None, {"error": "invalid_fields_json", "message": "--fields-json must be a JSON array of field objects"}
        return parsed, None
    specs = getattr(args, "field", None) or []
    if not specs:
        return None, None
    try:
        return [_parse_field_spec(s) for s in specs], None
    except ValueError as e:
        return None, {"error": "invalid_field", "message": str(e)}


def _parse_body(args):
    """Optional --body JSON object. Returns (body_or_None, error_dict_or_None)."""
    raw = getattr(args, "body", None)
    if not raw:
        return None, None
    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return None, {"error": "invalid_body", "message": "--body must be a JSON object"}
    return parsed, None


def cmd_list(args):
    params = [
        ("page", str(args.page)),
        ("rows", str(args.rows)),
        ("sortBy", args.sort_by),
        ("order", args.order),
    ]
    if args.name:
        params.append(("name", args.name))
    if args.statuses:
        for s in args.statuses.split(","):
            s = s.strip()
            if s:
                params.append(("statuses", s.upper()))
    qs = urllib.parse.urlencode(params)
    status, raw = _request("GET", f"{RESOURCE_TEMPLATES_URL}?{qs}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_get(args):
    status, raw = _request("GET", f"{RESOURCE_TEMPLATES_URL}/{args.id}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_create(args):
    fields, err = _collect_fields(args)
    if err:
        print(json.dumps(err, indent=2))
        return 2
    body_map, err = _parse_body(args)
    if err:
        print(json.dumps(err, indent=2))
        return 2

    payload = {
        "name": args.name,
        "resourceKey": args.key,
        "status": args.status,
        "body": body_map if body_map is not None else {},
        "fields": fields if fields is not None else [],
    }
    if args.description is not None:
        payload["description"] = args.description
    status, raw = _request("POST", RESOURCE_TEMPLATES_URL, headers=_admin_headers(), body=payload)
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "request_body": payload,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_update(args):
    fields, err = _collect_fields(args)
    if err:
        print(json.dumps(err, indent=2))
        return 2
    body_map, err = _parse_body(args)
    if err:
        print(json.dumps(err, indent=2))
        return 2

    # Step 1: fetch the current record — PUT is a full replace, so we merge the
    # provided overrides onto the existing template rather than clobbering it.
    get_status, get_raw = _request("GET", f"{RESOURCE_TEMPLATES_URL}/{args.id}", headers=_admin_headers())
    if not (200 <= get_status < 300):
        print(json.dumps({
            "error": "fetch_failed",
            "http_status": get_status,
            "body": _parse_json(get_raw) or get_raw,
            "id": args.id,
        }, indent=2))
        return 1
    current = _parse_json(get_raw)
    if not isinstance(current, dict):
        print(json.dumps({"error": "unexpected_template_shape", "raw": get_raw[:500]}, indent=2))
        return 1

    merged = dict(current)
    if args.name is not None:
        merged["name"] = args.name
    if args.key is not None:
        merged["resourceKey"] = args.key
    if args.description is not None:
        merged["description"] = args.description
    if args.status is not None:
        merged["status"] = args.status
    if body_map is not None:
        merged["body"] = body_map
    if fields is not None:
        merged["fields"] = fields

    put_status, put_raw = _request("PUT", f"{RESOURCE_TEMPLATES_URL}/{args.id}", headers=_admin_headers(), body=merged)
    print(json.dumps({
        "http_status": put_status,
        "ok": 200 <= put_status < 300,
        "id": args.id,
        "request_body": merged,
        "response": _parse_json(put_raw) or put_raw,
    }, indent=2))
    return 0 if 200 <= put_status < 300 else 1


def cmd_activate(args):
    status, raw = _request("POST", f"{RESOURCE_TEMPLATES_URL}/{args.id}/activate", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "id": args.id,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_deprecate(args):
    body = {"deprecationReason": args.reason} if args.reason is not None else {}
    status, raw = _request("POST", f"{RESOURCE_TEMPLATES_URL}/{args.id}/deprecate", headers=_admin_headers(), body=body)
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "id": args.id,
        "request_body": body,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_clone(args):
    body = {}
    if args.key is not None:
        body["key"] = args.key
    if args.name is not None:
        body["name"] = args.name
    status, raw = _request("POST", f"{RESOURCE_TEMPLATES_URL}/{args.id}/clone", headers=_admin_headers(), body=body)
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "id": args.id,
        "request_body": body,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_delete(args):
    status, raw = _request("DELETE", f"{RESOURCE_TEMPLATES_URL}/{args.id}", headers=_admin_headers())
    parsed = _parse_json(raw)
    out = {
        "http_status": status,
        "ok": 200 <= status < 300,
        "id": args.id,
        "response": parsed if parsed is not None else raw,
    }
    if status == 409:
        out["hint"] = ("Resource templates can only be deleted while DRAFT. This one is "
                       "ACTIVE or DEPRECATED — deprecate it instead of deleting.")
    print(json.dumps(out, indent=2))
    return 0 if 200 <= status < 300 else 1


def _add_field_args(p):
    p.add_argument("--field", action="append", default=[],
                   help="Field, repeatable. Format: NAME:TYPE[:EXTRA][:req]. "
                        "TYPE in {number,string,boolean,date,enumeration}; for enumeration "
                        "EXTRA is comma-separated allowed values; trailing 'req' marks required.")
    p.add_argument("--fields-json", default=None,
                   help="Full fields array as JSON (takes precedence over --field). "
                        "Used by the sync workflow after the developer confirms the HTML list.")
    p.add_argument("--body", default=None, help="Optional template body as a JSON object.")


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_dashboard_resource_template", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument("--expect-game", default=None,
                       help="Cross-game backstop: abort unless session.env's KINOA_GAME_ID equals this UUID.")

    p_list = sub.add_parser("list", help="GET resource templates (summaries).")
    p_list.add_argument("--rows", type=int, default=100, help="Page size. Default: 100.")
    p_list.add_argument("--page", type=int, default=0, help="Page index. Default: 0.")
    p_list.add_argument("--statuses", default=None, help="Comma-separated status filter: DRAFT,ACTIVE,DEPRECATED.")
    p_list.add_argument("--name", default=None, help="Optional name substring filter.")
    p_list.add_argument("--sort-by", default="updated_at", help="Sort field. Default: updated_at.")
    p_list.add_argument("--order", default="desc", choices=("asc", "desc"), help="Sort order. Default: desc.")
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="GET one resource template by id (full record).")
    p_get.add_argument("--id", required=True)
    p_get.set_defaults(func=cmd_get)

    p_cre = sub.add_parser("create", parents=[guard], help="POST a new resource template (defaults to DRAFT).")
    p_cre.add_argument("--name", required=True)
    p_cre.add_argument("--key", required=True, help="resourceKey — must match ^[a-zA-Z][a-zA-Z0-9_-]*$.")
    p_cre.add_argument("--description", default=None)
    p_cre.add_argument("--status", default="draft", choices=ALLOWED_STATUSES,
                       help="Initial status. Default: draft (activate publishes it).")
    _add_field_args(p_cre)
    p_cre.set_defaults(func=cmd_create)

    p_upd = sub.add_parser("update", parents=[guard], help="Update a resource template (GET + merged PUT).")
    p_upd.add_argument("--id", required=True)
    p_upd.add_argument("--name", default=None)
    p_upd.add_argument("--key", default=None, help="resourceKey — must match ^[a-zA-Z][a-zA-Z0-9_-]*$.")
    p_upd.add_argument("--description", default=None)
    p_upd.add_argument("--status", default=None, choices=ALLOWED_STATUSES)
    _add_field_args(p_upd)
    p_upd.set_defaults(func=cmd_update)

    p_act = sub.add_parser("activate", parents=[guard], help="Activate a DRAFT template (DRAFT -> ACTIVE).")
    p_act.add_argument("--id", required=True)
    p_act.set_defaults(func=cmd_activate)

    p_dep = sub.add_parser("deprecate", parents=[guard], help="Deprecate a template (-> DEPRECATED).")
    p_dep.add_argument("--id", required=True)
    p_dep.add_argument("--reason", default=None, help="Optional deprecation reason.")
    p_dep.set_defaults(func=cmd_deprecate)

    p_cln = sub.add_parser("clone", parents=[guard], help="Clone an existing template.")
    p_cln.add_argument("--id", required=True)
    p_cln.add_argument("--key", default=None, help="New resourceKey for the clone.")
    p_cln.add_argument("--name", default=None, help="New name for the clone.")
    p_cln.set_defaults(func=cmd_clone)

    p_del = sub.add_parser("delete", parents=[guard], help="DELETE a DRAFT template (HARD, irreversible).")
    p_del.add_argument("--id", required=True)
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args(argv)
    _guard_expected_game(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
