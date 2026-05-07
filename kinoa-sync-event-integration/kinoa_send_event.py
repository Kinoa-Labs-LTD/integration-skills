#!/usr/bin/env python3
"""
Kinoa Send Sync Event — POST /playerevents/api/v3/sync-event?player_id=…

Self-contained. Reads game secret from ~/.kinoa/session.env (written by
kinoa-init). Defaults --player-id and --session-id to KINOA_LAST_PLAYER_ID /
KINOA_LAST_SESSION_ID (set by kinoa-open-session).

Usage:
  python kinoa_send_event.py --name EVENT [--player-id ID] [--session-id SID]
                             [--system-param key=value]...
                             [--param key=value]...
                             [--player-state key=value]...

  --system-param   Goes directly into event_data (top-level). Use for predefined
                   parameters whose definition has system: true on the Kinoa side.
  --param          Goes into event_data.custom_params (nested). Use for params
                   the operator added on top of the predefined event (system: false),
                   or for events with no predefined schema.
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

SYNC_EVENT_URL = "https://gate.kinoa.io/playerevents/api/v3/sync-event"


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


def _parse_kv_pairs(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected key=value, got: {item!r}")
        k, v = item.split("=", 1)
        out[k] = v
    return out


def _require_credentials():
    if not os.environ.get("KINOA_GAME_SECRET"):
        print(json.dumps({
            "error": "missing_credentials",
            "missing": ["KINOA_GAME_SECRET"],
            "hint": "Run /kinoa-init first.",
        }, indent=2))
        sys.exit(2)


def main(argv):
    parser = argparse.ArgumentParser(
        prog="kinoa_send_event",
        description="Send a Kinoa sync event.",
    )
    parser.add_argument("--name", required=True, help="Event name.")
    parser.add_argument("--player-id", help="Defaults to KINOA_LAST_PLAYER_ID.")
    parser.add_argument("--session-id", help="Defaults to KINOA_LAST_SESSION_ID.")
    parser.add_argument(
        "--system-param",
        action="append",
        default=[],
        help="Predefined (system) param: goes directly into event_data. Repeatable. Format: key=value.",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Operator-added (custom) param: goes into event_data.custom_params. Repeatable. Format: key=value.",
    )
    parser.add_argument(
        "--player-state",
        action="append",
        default=[],
        help="event.player_state entry, repeatable. Format: key=value.",
    )
    args = parser.parse_args(argv)

    _require_credentials()
    game_secret = os.environ["KINOA_GAME_SECRET"]

    player_id = args.player_id or os.environ.get("KINOA_LAST_PLAYER_ID")
    session_id = args.session_id or os.environ.get("KINOA_LAST_SESSION_ID")
    if not player_id or not session_id:
        print(json.dumps({
            "error": "missing_player_or_session",
            "hint": "Pass --player-id and --session-id, or run /kinoa-open-session first.",
        }, indent=2))
        return 2

    event_data = {"name": args.name, "session_id": session_id}
    event_data.update(_parse_kv_pairs(args.system_param))
    custom = _parse_kv_pairs(args.param)
    if custom:
        event_data["custom_params"] = custom

    body = {"event": {"event_data": event_data}}
    player_state = _parse_kv_pairs(args.player_state)
    if player_state:
        body["event"]["player_state"] = player_state

    qs = urllib.parse.urlencode({"player_id": player_id})
    status, raw = _request(
        "POST",
        f"{SYNC_EVENT_URL}?{qs}",
        headers={"game": game_secret},
        body=body,
    )

    result = {
        "http_status": status,
        "player_id": player_id,
        "session_id": session_id,
        "event_name": args.name,
        "response": _parse_json(raw) or raw,
        "ok": 200 <= status < 300,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
