#!/usr/bin/env python3
"""
Kinoa Sync Player Fields — manage Kinoa predefined and custom player_field
definitions, plus retrieve the full player_state for verification.

Self-contained. Reads bearer token, game id, and game secret from
~/.kinoa/session.env (written by kinoa-init).

Pagination: every list-* subcommand auto-paginates. --rows is the PAGE SIZE,
not a global limit — when the server reports more records than one page holds
(totalCount), the next pages are requested and merged so the printed response
always carries the FULL listing ({totalCount, elements}). The output gains
pages_fetched, plus truncated:true when the merge had to stop early and
count_mismatch:true when it assembled more elements than the final totalCount
(either flag means: re-run the listing, don't trust it); a non-2xx page instead
fails closed (ok:false + failed_page) — a partial merge is never presented as a
complete listing.

Subcommands:
  list-predefined [--states active,not_implemented] [--rows N]
      GET https://dashboard.kinoa.io/gamemetaapi/api/player_fields (types=PREDEFINED)
  list-custom [--states active] [--rows N]
      GET https://dashboard.kinoa.io/gamemetaapi/api/player_fields (types=USER)
  list-calculated [--states active,not_implemented] [--rows N]
      GET https://dashboard.kinoa.io/gamemetaapi/api/player_fields (types=CALCULATED)
      Server-computed fields (eCPM, session counts, ...). Their paths are RESERVED —
      a custom create on one is refused ("path is reserved"). NOTE: the per-record
      `calculated` boolean is dead (always false, live-verified 2026-08-04) — the
      record's `type` / this types= query is the only reliable marker.
  activate --field-id UUID
      PATCH https://dashboard.kinoa.io/gamemetaapi/api/player_fields/<id>/ACTIVATE
      Flips not_implemented -> active; also the recovery path for soft-deleted
      USER fields: activate the deleted record instead of re-creating.
  create --name N --path P --kind K [--extra ...] [--description ...]
         [--default-value ...] [--app-version ...] [--calculated]
      POST https://dashboard.kinoa.io/gamemetaapi/api/player_fields
      KIND: number, boolean, string, date, long_string, enumeration, version.
  delete --field-id UUID
      DELETE https://dashboard.kinoa.io/gamemetaapi/api/player_fields/<id>
      (soft delete — field state becomes "deleted")
  get-player-state --player-id ID
      GET https://gate.kinoa.io/playerevents/api/v3/player-state?player_id=ID
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

PLAYER_FIELDS_URL = "https://dashboard.kinoa.io/gamemetaapi/api/player_fields"
PLAYER_STATE_URL = "https://gate.kinoa.io/playerevents/api/v3/player-state"

ALLOWED_KINDS = ("number", "boolean", "string", "date", "long_string", "enumeration", "version")


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


REQUEST_TIMEOUT_SECONDS = 30


def _request(method, url, headers=None, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, raw
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason} — the request may still have been applied server-side; re-check (list/get) before retrying a mutation"
    except TimeoutError as e:
        return 0, f"Timeout: {e} — the request may still have been applied server-side; re-check (list/get) before retrying a mutation"


def _parse_json(raw):
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _get_all_pages(url, params, headers):
    """GET a paginated listing page by page and merge the elements.

    `params` is a list of (key, value) query pairs without a page entry — the
    page number is appended here, starting at 0; `rows` in `params` is the
    page size. A first page that is not {"totalCount": int, "elements": list}
    is returned untouched after that single request (legacy single-call).

    Returns output keys for the caller's JSON envelope:
      status         HTTP status of the last request
      response       merged {..., totalCount, elements} | untouched body
      pages_fetched  page requests made
      failed_page    non-2xx page index — caller derives ok:false, the
                     partial merge is discarded
      truncated      merge stopped early (no-progress page or the page cap);
                     totalCount stays server-reported
      count_mismatch merge ended with more elements than totalCount — the
                     listing is unreliable, re-run it instead of diffing
    """
    merged = []
    total = None
    first_body = None
    page = 0
    while True:
        qs = urllib.parse.urlencode(params + [("page", str(page))])
        status, raw = _request("GET", f"{url}?{qs}", headers=headers)
        body = _parse_json(raw)
        body = body if body is not None else raw
        if not (200 <= status < 300):
            return {"status": status, "response": body,
                    "pages_fetched": page + 1, "failed_page": page}
        if page == 0:
            if not (isinstance(body, dict)
                    and isinstance(body.get("totalCount"), int)
                    and isinstance(body.get("elements"), list)):
                return {"status": status, "response": body, "pages_fetched": 1}
            first_body = body
        elements = body.get("elements") if isinstance(body, dict) else None
        if isinstance(elements, list):
            merged.extend(elements)
        # Later pages may report a fresher totalCount (concurrent creates or
        # deletes) — trust the newest value the server sent.
        if isinstance(body, dict) and isinstance(body.get("totalCount"), int):
            total = body["totalCount"]
        page += 1
        if len(merged) >= total:
            break
        # No-progress stop: a page that contributed nothing (empty, missing, or
        # non-list elements — the isinstance matters: a truthy non-list value
        # would otherwise re-request with zero progress until the cap) ends the
        # merge; the page cap is the backstop for servers that keep feeding
        # non-empty pages while inflating totalCount.
        if not (isinstance(elements, list) and elements) or page >= 1000:
            return {"status": status,
                    "response": dict(first_body, totalCount=total, elements=merged),
                    "pages_fetched": page, "truncated": True}
    result = {"status": status,
              "response": dict(first_body, totalCount=total, elements=merged),
              "pages_fetched": page}
    if len(merged) > total:
        result["count_mismatch"] = True
    return result


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


def _guard_expected_game(args):
    """Cross-game backstop. Mirrors kinoa_sdk_sync_plan's listing_game_mismatch
    check: when the caller passes --expect-game, it must equal the game the
    session credentials point at (KINOA_GAME_ID from session.env). A stale
    session.env left over from ANOTHER game would otherwise mutate the WRONG
    game's dashboard. Fatal, before any call — the flag is accepted on every
    subcommand, read-only included. Flagless calls are unaffected."""
    expected = getattr(args, "expect_game", None)
    if expected is None:
        return
    expected = expected.strip()
    if not expected:
        print(json.dumps({
            "error": "empty_expect_game",
            "hint": "--expect-game was passed but empty (unset shell variable?). "
                    "Pass the literal game UUID recorded at run start.",
        }, indent=2))
        sys.exit(2)
    session_game = (os.environ.get("KINOA_GAME_ID") or "").strip()
    if expected.lower() != session_game.lower():
        print(json.dumps({
            "error": "session_game_mismatch",
            "expected_game": expected,
            "session_game": session_game or None,
            "hint": "session.env points at a different game than --expect-game. "
                    "Re-run /kinoa-init for the intended game before retrying.",
        }, indent=2))
        sys.exit(2)


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


def _list_fields(types, states, rows):
    params = [
        ("types", types),
        ("selectedFilters", "states"),
        ("states", states),
        ("order", "desc"),
        ("sortBy", "updated_at"),
        ("rows", str(rows)),
    ]
    result = _get_all_pages(PLAYER_FIELDS_URL, params, _admin_headers())
    status = result.pop("status")
    payload = {"http_status": status, "ok": 200 <= status < 300}
    payload.update(result)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def cmd_list_predefined(args):
    return _list_fields("PREDEFINED", args.states, args.rows)


def cmd_list_custom(args):
    return _list_fields("USER", args.states, args.rows)


def cmd_list_calculated(args):
    return _list_fields("CALCULATED", args.states, args.rows)


def cmd_activate(args):
    url = f"{PLAYER_FIELDS_URL}/{args.field_id}/ACTIVATE"
    status, raw = _request("PATCH", url, headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "field_id": args.field_id,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_create(args):
    if args.kind == "enumeration" and not args.extra:
        print(json.dumps({
            "error": "missing_extra",
            "hint": "enumeration kind requires --extra with comma-separated values, e.g. --extra v1,v2",
        }, indent=2))
        return 2
    body = {
        "name": args.name,
        "path": args.path,
        "kind": args.kind,
        "appVersion": args.app_version,
        "description": args.description,
        "calculated": args.calculated,
        "extra": args.extra,
        "defaultValue": args.default_value,
    }
    status, raw = _request("POST", PLAYER_FIELDS_URL, headers=_admin_headers(), body=body)
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "request_body": body,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_delete(args):
    url = f"{PLAYER_FIELDS_URL}/{args.field_id}"
    status, raw = _request("DELETE", url, headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "field_id": args.field_id,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_get_player_state(args):
    qs = urllib.parse.urlencode({"player_id": args.player_id})
    status, raw = _request("GET", f"{PLAYER_STATE_URL}?{qs}", headers=_public_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "player_id": args.player_id,
        "response": _parse_json(raw) or raw,
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_dashboard_player_fields", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Parent carrying the cross-game backstop, attached to every subcommand
    # (read-only included, so scripted callers can pass it uniformly).
    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument(
        "--expect-game",
        default=None,
        help="Cross-game backstop: abort unless session.env's KINOA_GAME_ID equals this UUID. "
             "Mirrors the SDK-sync planner's game-mismatch check; pass the manifest/intended game id.",
    )

    p_list = sub.add_parser("list-predefined", parents=[guard], help="GET predefined (system) player fields.")
    p_list.add_argument(
        "--states",
        default="active,not_implemented",
        help="Comma-separated states filter. Default: active,not_implemented.",
    )
    p_list.add_argument("--rows", type=int, default=100, help="Page size — every page is fetched and merged (auto-pagination). Default: 100.")
    p_list.set_defaults(func=cmd_list_predefined)

    p_lc = sub.add_parser("list-custom", parents=[guard], help="GET custom (USER) player fields.")
    p_lc.add_argument(
        "--states",
        default="active",
        help="Comma-separated states filter. Default: active (excludes deleted).",
    )
    p_lc.add_argument("--rows", type=int, default=100, help="Page size — every page is fetched and merged (auto-pagination). Default: 100.")
    p_lc.set_defaults(func=cmd_list_custom)

    p_lcalc = sub.add_parser("list-calculated", parents=[guard],
                             help="GET calculated (server-computed) player fields.")
    p_lcalc.add_argument("--states", default="active,not_implemented")
    p_lcalc.add_argument("--rows", type=int, default=200)
    p_lcalc.set_defaults(func=cmd_list_calculated)

    p_act = sub.add_parser("activate", parents=[guard], help="PATCH a predefined field to ACTIVATE.")
    p_act.add_argument("--field-id", required=True, help="Predefined field UUID.")
    p_act.set_defaults(func=cmd_activate)

    p_del = sub.add_parser("delete", parents=[guard], help="DELETE a player field (soft delete).")
    p_del.add_argument("--field-id", required=True, help="Field UUID.")
    p_del.set_defaults(func=cmd_delete)

    p_create = sub.add_parser("create", parents=[guard], help="POST a custom player field.")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--path", required=True, help="Dot-separated path from root, e.g. profile.level.")
    p_create.add_argument("--kind", required=True, choices=ALLOWED_KINDS)
    p_create.add_argument("--extra", default="", help="For enumeration: comma-separated allowed values.")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--default-value", default="")
    p_create.add_argument("--app-version", default="")
    p_create.add_argument("--calculated", action="store_true")
    p_create.set_defaults(func=cmd_create)

    p_state = sub.add_parser("get-player-state", parents=[guard], help="GET full player_state from public API.")
    p_state.add_argument("--player-id", required=True)
    p_state.set_defaults(func=cmd_get_player_state)

    args = parser.parse_args(argv)
    _guard_expected_game(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
