#!/usr/bin/env python3
"""
Kinoa Sync Events — manage Kinoa game_event definitions: list predefined and
custom events, fetch a single event, publish predefined events, create custom
events with their parameters, and soft-delete events.

Self-contained. Reads bearer token and game id from ~/.kinoa/session.env
(written by kinoa-init).

Subcommands:
  list-predefined [--rows N]
      GET https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=PREDEFINED
  list-custom [--rows N]
      GET https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=USER
  get --event-id UUID
      GET https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>
  publish --event-id UUID
      Two-step: GET the event, then PUT the same body to /game_events/<id>/publish.
      Flips status from NOT_IMPLEMENTED → ACTIVE.
  create --name NAME [--no-analytics] [--param NAME:KIND[:EXTRA]]...
      POST https://dashboard.kinoa.io/gamemetaapi/api/game_events
      Custom event creation. Each --param adds a non-system parameter.
      KIND: number, boolean, string, enumeration, string_array, number_array.
      For enumeration, EXTRA is comma-separated allowed values.
  delete --event-id UUID
      DELETE https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>

Allowed parameter kinds for custom event creation: number, boolean, string,
enumeration, string_array, number_array.
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

GAME_EVENTS_URL = "https://dashboard.kinoa.io/gamemetaapi/api/game_events"

ALLOWED_PARAM_KINDS = (
    "number",
    "boolean",
    "string",
    "enumeration",
    "string_array",
    "number_array",
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


def _list_events(types, rows):
    params = {
        "page": "0",
        "rows": str(rows),
        "sortBy": "updated_at",
        "order": "desc",
        "types": types,
    }
    qs = urllib.parse.urlencode(params)
    status, raw = _request("GET", f"{GAME_EVENTS_URL}?{qs}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_list_predefined(args):
    return _list_events("PREDEFINED", args.rows)


def cmd_list_custom(args):
    return _list_events("USER", args.rows)


def cmd_get(args):
    status, raw = _request("GET", f"{GAME_EVENTS_URL}/{args.event_id}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_publish(args):
    # Step 1: fetch the full event record.
    get_status, get_raw = _request("GET", f"{GAME_EVENTS_URL}/{args.event_id}", headers=_admin_headers())
    if not (200 <= get_status < 300):
        print(json.dumps({
            "error": "fetch_failed",
            "http_status": get_status,
            "body": _parse_json(get_raw) or get_raw,
            "event_id": args.event_id,
        }, indent=2))
        return 1
    event = _parse_json(get_raw)
    if not isinstance(event, dict):
        print(json.dumps({
            "error": "unexpected_event_shape",
            "raw": get_raw[:500],
        }, indent=2))
        return 1

    # Step 2: PUT to /publish with the full event body.
    put_status, put_raw = _request(
        "PUT",
        f"{GAME_EVENTS_URL}/{args.event_id}/publish",
        headers=_admin_headers(),
        body=event,
    )
    parsed = _parse_json(put_raw) or put_raw
    print(json.dumps({
        "http_status": put_status,
        "ok": 200 <= put_status < 300,
        "event_id": args.event_id,
        "event_name": event.get("name"),
        "previous_status": event.get("status"),
        "response": parsed,
    }, indent=2))
    return 0 if 200 <= put_status < 300 else 1


def _parse_param_spec(spec):
    """
    Parse "name:kind[:extra]" → dict suitable for game_event_parameters.
    Examples:
      'amount:number'                       → {name, kind: number, system: False}
      'tier:enumeration:bronze,silver,gold' → {name, kind: enumeration, extra: 'bronze,silver,gold', system: False}
    """
    parts = spec.split(":", 2)
    if len(parts) < 2:
        raise ValueError(f"expected NAME:KIND[:EXTRA], got: {spec!r}")
    name, kind = parts[0], parts[1]
    if kind not in ALLOWED_PARAM_KINDS:
        raise ValueError(f"kind must be one of {ALLOWED_PARAM_KINDS}, got {kind!r}")
    extra = parts[2] if len(parts) == 3 else ""
    if kind == "enumeration" and not extra:
        raise ValueError(f"enumeration kind requires EXTRA values, e.g. {name}:enumeration:v1,v2")
    out = {"name": name, "kind": kind, "system": False}
    if extra:
        out["extra"] = extra
    return out


def cmd_create(args):
    try:
        params = [_parse_param_spec(s) for s in args.param or []]
    except ValueError as e:
        print(json.dumps({"error": "invalid_param", "message": str(e)}, indent=2))
        return 2

    body = {
        "name": args.name,
        "system": False,
        "p2pEventParameters": [],
        "gameEventParameters": [],
        "send_to_analytics": not args.no_analytics,
        "game_event_parameters": params,
    }
    status, raw = _request("POST", GAME_EVENTS_URL, headers=_admin_headers(), body=body)
    parsed = _parse_json(raw) or raw
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "request_body": body,
        "response": parsed,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_delete(args):
    status, raw = _request("DELETE", f"{GAME_EVENTS_URL}/{args.event_id}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "event_id": args.event_id,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_dashboard_event", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_lp = sub.add_parser("list-predefined", help="GET predefined game_events.")
    p_lp.add_argument("--rows", type=int, default=100, help="Page size. Default: 100.")
    p_lp.set_defaults(func=cmd_list_predefined)

    p_lc = sub.add_parser("list-custom", help="GET USER (custom) game_events.")
    p_lc.add_argument("--rows", type=int, default=100, help="Page size. Default: 100.")
    p_lc.set_defaults(func=cmd_list_custom)

    p_get = sub.add_parser("get", help="GET a single event by id (full record incl. parameters).")
    p_get.add_argument("--event-id", required=True)
    p_get.set_defaults(func=cmd_get)

    p_pub = sub.add_parser("publish", help="Publish a predefined event (status NOT_IMPLEMENTED → ACTIVE).")
    p_pub.add_argument("--event-id", required=True)
    p_pub.set_defaults(func=cmd_publish)

    p_cre = sub.add_parser("create", help="POST a custom (USER) event.")
    p_cre.add_argument("--name", required=True)
    p_cre.add_argument(
        "--no-analytics",
        action="store_true",
        help="Set send_to_analytics=false. Default true.",
    )
    p_cre.add_argument(
        "--param",
        action="append",
        default=[],
        help="Custom parameter, repeatable. Format: NAME:KIND[:EXTRA]. EXTRA is required for enumeration.",
    )
    p_cre.set_defaults(func=cmd_create)

    p_del = sub.add_parser("delete", help="DELETE a game_event by id.")
    p_del.add_argument("--event-id", required=True)
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
