#!/usr/bin/env python3
"""
Kinoa Init — capture credentials, persist to ~/.kinoa/session.env, and validate
the project against the Kinoa admin API.

Integration type is hardcoded to API (the only supported mode).

Self-contained. Prints a single JSON object on stdout describing the result.

Usage:
  python kinoa_init.py --game-id GAME_UUID
                       --game-secret SECRET
                       --bearer-token TOKEN
                       [--fix-integration-type]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

SESSION_DIR = os.path.expanduser("~/.kinoa")
SESSION_ENV_PATH = os.path.join(SESSION_DIR, "session.env")

GAME_SETTINGS_URL = "https://dashboard.kinoa.io/gamemetaapi/api/game-settings"
INTEGRATION_TYPE = "API"


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
    with open(SESSION_ENV_PATH, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    os.chmod(SESSION_ENV_PATH, 0o600)


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


def validate_game_settings(bearer_token, game_id, expected_integration_type):
    status, raw = _request(
        "GET",
        GAME_SETTINGS_URL,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Game": game_id,
            "Game-Id": game_id,
        },
    )
    parsed = _parse_json(raw)
    integration_type = None
    if isinstance(parsed, dict):
        integration_type = parsed.get("integration_type") or parsed.get("integrationType")

    result = {
        "http_status": status,
        "integration_type": integration_type,
        "expected_integration_type": expected_integration_type,
        "ok": status == 200 and integration_type == expected_integration_type,
    }
    if status == 0:
        result["reason"] = "network_error"
        result["body"] = raw
    elif status in (401, 403):
        result["reason"] = "unauthorized"
    elif status == 404:
        result["reason"] = "not_found"
    elif status == 200 and integration_type != expected_integration_type:
        result["reason"] = "wrong_integration_type"
    elif status >= 400:
        result["reason"] = "http_error"
        result["body"] = raw
    return result


def set_integration_type(bearer_token, game_id, integration_type):
    status, raw = _request(
        "POST",
        GAME_SETTINGS_URL,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "Game": game_id,
            "Game-Id": game_id,
        },
        body={"integrationType": integration_type},
    )
    return {"http_status": status, "body": _parse_json(raw) or raw}


def main(argv):
    parser = argparse.ArgumentParser(
        prog="kinoa_init",
        description="Capture Kinoa credentials and validate the project (API integration only).",
    )
    parser.add_argument("--game-id", required=True, help="Internal game UUID from the Kinoa dashboard.")
    parser.add_argument("--game-secret", required=True)
    parser.add_argument("--bearer-token", required=True)
    parser.add_argument(
        "--fix-integration-type",
        action="store_true",
        help="If the project's integration_type isn't API, POST to switch it to API.",
    )
    args = parser.parse_args(argv)

    _save_session_env({
        "KINOA_INTEGRATION_TYPE": INTEGRATION_TYPE,
        "KINOA_GAME_ID": args.game_id,
        "KINOA_GAME_SECRET": args.game_secret,
        "KINOA_BEARER_TOKEN": args.bearer_token,
    })

    result = {"saved": True, "session_env_path": SESSION_ENV_PATH}
    validation = validate_game_settings(args.bearer_token, args.game_id, INTEGRATION_TYPE)
    result.update(validation)

    if args.fix_integration_type and validation.get("reason") == "wrong_integration_type":
        update = set_integration_type(args.bearer_token, args.game_id, INTEGRATION_TYPE)
        result["fix_attempted"] = True
        result["fix_http_status"] = update["http_status"]
        if 200 <= update["http_status"] < 300:
            recheck = validate_game_settings(args.bearer_token, args.game_id, INTEGRATION_TYPE)
            result.update(recheck)
            result["fix_succeeded"] = recheck["ok"]
        else:
            result["fix_succeeded"] = False

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
