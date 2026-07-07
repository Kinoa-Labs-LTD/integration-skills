#!/usr/bin/env python3
"""
Kinoa Init — capture credentials, persist to ~/.kinoa/session.env, and validate
the project against the Kinoa admin API.

Integration type defaults to API (direct API integration). Pass
--integration-type SDK for games integrated via the Kinoa Unity SDK — the
dashboard skills then only mirror entities onto the Dashboard; the game's
client integration stays SDK and is never affected by these admin calls.

Self-contained. Prints a single JSON object on stdout describing the result.

Usage:
  python kinoa_init.py --game-id GAME_UUID
                       --game-secret SECRET
                       --bearer-token TOKEN
                       [--integration-type {API,SDK}]
                       [--architecture {SINGLE,MONOREPO,MULTI_REPO}]
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
ALLOWED_INTEGRATION_TYPES = ("API", "SDK")
DEFAULT_INTEGRATION_TYPE = "API"
ALLOWED_ARCHITECTURES = ("SINGLE", "MONOREPO", "MULTI_REPO")


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
        description="Capture Kinoa credentials and validate the project (API or SDK integration).",
    )
    parser.add_argument("--game-id", required=True, help="Internal game UUID from the Kinoa dashboard.")
    parser.add_argument("--game-secret", required=True)
    parser.add_argument("--bearer-token", required=True)
    parser.add_argument(
        "--integration-type",
        choices=ALLOWED_INTEGRATION_TYPES,
        default=None,
        help="Expected integration_type of the game. API = direct API integration (default); "
             "SDK = game integrated via the Kinoa Unity SDK (dashboard skills only mirror entities).",
    )
    parser.add_argument(
        "--architecture",
        choices=ALLOWED_ARCHITECTURES,
        default=None,
        help="How the client's codebase is laid out: SINGLE app (default flow), MONOREPO of "
             "services, or MULTI_REPO where each service is its own checkout. Persisted as "
             "KINOA_ARCHITECTURE so every workflow scopes discovery/state the same way. "
             "Omit to leave any previously stored value untouched.",
    )
    parser.add_argument(
        "--fix-integration-type",
        action="store_true",
        help="If the project's integration_type doesn't match --integration-type, POST to switch it. "
             "The flip direction IS the --integration-type value — SDK flows must pass "
             "--integration-type SDK explicitly; a bare --fix-integration-type targets API "
             "(legacy API-mode form) and emits a warning.",
    )
    args = parser.parse_args(argv)
    integration_type_explicit = args.integration_type is not None
    expected_type = args.integration_type or DEFAULT_INTEGRATION_TYPE

    env_values = {
        "KINOA_INTEGRATION_TYPE": expected_type,
        "KINOA_GAME_ID": args.game_id,
        "KINOA_GAME_SECRET": args.game_secret,
        "KINOA_BEARER_TOKEN": args.bearer_token,
    }
    if args.architecture:
        env_values["KINOA_ARCHITECTURE"] = args.architecture
    _save_session_env(env_values)

    result = {"saved": True, "session_env_path": SESSION_ENV_PATH}
    if args.fix_integration_type and not integration_type_explicit:
        # The flip direction silently falls back to API — in an SDK flow that papers over
        # the mismatch instead of fixing it (validates "ok", persists API into session.env).
        result["integration_type_defaulted"] = True
        result["warning"] = (
            "fix-integration-type invoked without an explicit --integration-type: "
            f"targeting the default ({DEFAULT_INTEGRATION_TYPE}). Pass --integration-type "
            "explicitly (API or SDK) to confirm the flip direction; SDK flows in particular "
            "MUST pass --integration-type SDK or they silently re-target API."
        )
    validation = validate_game_settings(args.bearer_token, args.game_id, expected_type)
    result.update(validation)

    if args.fix_integration_type and validation.get("reason") == "wrong_integration_type":
        update = set_integration_type(args.bearer_token, args.game_id, expected_type)
        result["fix_attempted"] = True
        result["fix_http_status"] = update["http_status"]
        if 200 <= update["http_status"] < 300:
            recheck = validate_game_settings(args.bearer_token, args.game_id, expected_type)
            result.update(recheck)
            result["fix_succeeded"] = recheck["ok"]
        else:
            result["fix_succeeded"] = False

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
