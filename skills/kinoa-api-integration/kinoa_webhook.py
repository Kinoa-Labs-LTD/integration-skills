#!/usr/bin/env python3
"""Kinoa Agent Webhook — post phase + Q&A telemetry to the Client Support Tool.

POSTs to https://client-support-tool.kinoa.io/api/kinoa-agent-hooks/prompt
with body { gameId, prompt, lastQuestion }. The receiving service stores it
so the support team can replay an integration session afterwards.

Three subcommands map intent to the prompt / lastQuestion fields:

  phase-start --phase "<label>" [--note "<extra>"]
      Marks the beginning of a phase. prompt="Phase started: <label>" and
      lastQuestion="" (or --note appended after the label).

  phase-end --phase "<label>" [--summary "<text>"]
      Marks the end of a phase. prompt="Phase ended: <label> — <summary>"
      and lastQuestion="".

  qa --question "<text>" --answer "<text>"
      Records a question + the developer's answer. prompt=<answer>,
      lastQuestion=<question>.

Reads KINOA_GAME_ID from ~/.kinoa/session.env. If the file is missing or
KINOA_GAME_ID is empty, the helper prints a JSON error and **exits 0** —
the webhook is supplementary telemetry; a missing or unreachable receiver
must never abort an integration run.

Self-contained — no imports from sibling skill folders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

SESSION_DIR = os.path.expanduser("~/.kinoa")
SESSION_ENV_PATH = os.path.join(SESSION_DIR, "session.env")

WEBHOOK_URL = "https://client-support-tool.kinoa.io/api/kinoa-agent-hooks/prompt"
TIMEOUT_SECONDS = 5


def _load_session_env() -> None:
    """Load ~/.kinoa/session.env into os.environ if present. Silent on missing."""
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


def _post(payload: dict) -> dict:
    """POST the payload. Returns a result dict — never raises."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return {"ok": 200 <= status < 300, "http_status": status, "response": parsed}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return {"ok": False, "http_status": e.code, "error": "http_error", "body": raw}
    except urllib.error.URLError as e:
        return {"ok": False, "error": "network_error", "detail": str(e.reason)}
    except Exception as e:
        return {"ok": False, "error": "unexpected_error", "detail": str(e)}


def _send(prompt: str, last_question: str) -> dict:
    """Build the payload, send it, and return a result dict suitable for stdout."""
    _load_session_env()
    game_id = os.environ.get("KINOA_GAME_ID", "").strip()
    if not game_id:
        return {
            "ok": False,
            "skipped": True,
            "error": "missing_game_id",
            "detail": (
                "KINOA_GAME_ID is not set in ~/.kinoa/session.env. "
                "Webhook skipped — integration run continues normally."
            ),
        }
    payload = {
        "gameId": game_id,
        "prompt": prompt or "",
        "lastQuestion": last_question or "",
    }
    result = _post(payload)
    result["sent"] = {
        "gameId": game_id,
        # Trim long fields so the stdout log stays readable; the server has the full text.
        "prompt": payload["prompt"][:200] + ("…" if len(payload["prompt"]) > 200 else ""),
        "lastQuestion": payload["lastQuestion"][:200] + ("…" if len(payload["lastQuestion"]) > 200 else ""),
    }
    return result


def _cmd_phase_start(args) -> dict:
    suffix = f" — {args.note}" if args.note else ""
    prompt = f"Phase started: {args.phase}{suffix}"
    return _send(prompt, "")


def _cmd_phase_end(args) -> dict:
    suffix = f" — {args.summary}" if args.summary else ""
    prompt = f"Phase ended: {args.phase}{suffix}"
    return _send(prompt, "")


def _cmd_qa(args) -> dict:
    return _send(args.answer, args.question)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("phase-start", help="Mark a phase as started.")
    p_start.add_argument("--phase", required=True, help='Phase label, e.g. "Phase 1 — kinoa-init".')
    p_start.add_argument("--note", default="", help="Optional extra context appended to the prompt.")
    p_start.set_defaults(handler=_cmd_phase_start)

    p_end = sub.add_parser("phase-end", help="Mark a phase as ended.")
    p_end.add_argument("--phase", required=True, help="Phase label.")
    p_end.add_argument("--summary", default="", help="One-line summary of what happened.")
    p_end.set_defaults(handler=_cmd_phase_end)

    p_qa = sub.add_parser("qa", help="Record a question and the developer's answer.")
    p_qa.add_argument("--question", required=True, help="The question asked.")
    p_qa.add_argument("--answer", required=True, help="The developer's response.")
    p_qa.set_defaults(handler=_cmd_qa)

    args = parser.parse_args()
    result = args.handler(args)
    print(json.dumps(result))
    # Exit 0 even on failure: telemetry must never abort the integration run.
    return 0


if __name__ == "__main__":
    sys.exit(main())
