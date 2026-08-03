#!/usr/bin/env python3
"""
Kinoa Open Session — POST /playerevents/api/v3/player/session/start.

Self-contained. Reads game secret from ~/.kinoa/session.env (written by
kinoa-init). Generates a UUID for the session_id header, persists last
player_id and session_id back to the same file so a follow-up sync event
can reuse them.

Usage:
  python kinoa_open_session.py --player-id ID [--level N] [--session-id UUID]
                               [--field key=value]...
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

SESSION_DIR = os.path.expanduser("~/.kinoa")
SESSION_ENV_PATH = os.path.join(SESSION_DIR, "session.env")

SESSION_START_URL = "https://gate.kinoa.io/playerevents/api/v3/player/session/start"


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


def _save_session_env(values):
    os.makedirs(SESSION_DIR, exist_ok=True)
    existing = {}
    if os.path.exists(SESSION_ENV_PATH):
        with open(SESSION_ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                if k:
                    existing[k] = v
    existing.update(values)
    # Atomic replace: a concurrent reader never sees a truncated file.
    tmp_path = SESSION_ENV_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, SESSION_ENV_PATH)


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
        prog="kinoa_open_session",
        description="Open a Kinoa player session.",
    )
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--session-id", help="Override; default is a fresh UUID.")
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        help="Extra player_state field, repeatable. Format: key=value.",
    )
    args = parser.parse_args(argv)

    _require_credentials()
    game_secret = os.environ["KINOA_GAME_SECRET"]
    session_id = args.session_id or str(uuid.uuid4())

    player_state = {
        "player_identifiers": {"player_id": args.player_id},
        "level": args.level,
    }
    player_state.update(_parse_kv_pairs(args.field))

    status, raw = _request(
        "POST",
        SESSION_START_URL,
        headers={"game": game_secret, "session_id": session_id},
        body={"player_state": player_state},
    )

    ok = 200 <= status < 300
    # Persist the ids only for a session that actually opened — a 401/failed
    # call must not leave phantom KINOA_LAST_* values for Phases 4/5 to trust.
    if ok:
        _save_session_env({
            "KINOA_LAST_PLAYER_ID": args.player_id,
            "KINOA_LAST_SESSION_ID": session_id,
        })

    result = {
        "http_status": status,
        "session_id": session_id,
        "player_id": args.player_id,
        "response": _parse_json(raw) or raw,
        "ok": ok,
        "last_ids_persisted": ok,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
