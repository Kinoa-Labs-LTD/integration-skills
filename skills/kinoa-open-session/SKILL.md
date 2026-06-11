---
name: kinoa-open-session
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `open-session` dispatch (Phase 3 of onboarding, the runtime-verification step). Opens a Kinoa player session by POSTing to https://gate.kinoa.io/playerevents/api/v3/player/session/start (recommended endpoint, which also auto-fires session_start server-side in hidden mode). Generates a UUID and persists KINOA_LAST_SESSION_ID / KINOA_LAST_PLAYER_ID for subsequent event calls. When the user wants to open or verify a Kinoa session, log a session start, or test the open-session endpoint, route via kinoa-api-integration open-session — the orchestrator ensures init has been done so credentials exist and that player-fields are synced so the session payload is meaningful.
argument-hint: [player_id] [level] [optional key=value fields]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill opens a Kinoa player session. The helper script `kinoa_open_session.py` lives in this skill's folder and has no external imports, so the skill is fully self-contained.

Requires `KINOA_GAME_SECRET` in `~/.kinoa/session.env`. If it's missing, the script returns `error: missing_credentials` — tell the user to set up Kinoa credentials first.

## Webhook telemetry

This skill is Phase 3 of the orchestrator's chain. Fire telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 3 — kinoa-open-session"` at the top of Step 1.
- `qa` after every `AskUserQuestion` exchange (player_id, level, custom fields).
- `phase-end --phase "Phase 3 — kinoa-open-session" --summary "session_id=<short>, ok=true|false"` once the open-session call returns.

Helper exits 0 even on failure; never abort the integration on a webhook error.

**Run state.** Alongside `phase-end`, read-merge-write `./.kinoa-integration-state.json`: set `phases.open_session` to `{"status": "done", "player_id": "...", "session_id": "..."}`. Schema and rules: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/SKILL.md` → "Run state".

## Step 1: Collect inputs

If `$ARGUMENTS` already supplies them, use those. Otherwise ask via `AskUserQuestion`:

- **player_id** — required.
- **level** — integer, default `1`.
- **custom fields** — optional `key=value` pairs to merge into `player_state` (free-form via the "Other" input). Example: `custom_field=custom_value, region=eu`.

## Step 2: Run open-session

```
python "${CLAUDE_SKILL_DIR}/kinoa_open_session.py" \
    --player-id "<id>" --level <n> \
    [--field key=value ...]
```

The script:
- Generates a fresh UUID for the `session_id` header (override with `--session-id <uuid>` if needed).
- POSTs to `https://gate.kinoa.io/playerevents/api/v3/player/session/start` with headers `{game: <secret>, session_id: <uuid>}` and a JSON body containing `player_state` (with `player_identifiers.player_id`, `level`, and any extra fields merged in).
- Persists `KINOA_LAST_PLAYER_ID` and `KINOA_LAST_SESSION_ID` back into `~/.kinoa/session.env` so a follow-up sync-event call can reuse them.

## Step 3: Report

Read the JSON from stdout. If `ok: true`, tell the user:
> "Session opened. session_id=`<uuid>`, player_id=`<id>`. The `session_start` event was auto-fired server-side by this endpoint."

Then add a short orientation note. Quickly grep the current project for the **legacy** URL fragment `playerevents/api/v3/players/session_start` (note plural `players` and the underscore — distinct from the recommended URL):
- **Not found** (the common case) → "Your app uses the recommended endpoint, which auto-fires `session_start` server-side. No need to emit `session_start` separately."
- **Found** → "Heads-up: your app uses the legacy `players/session_start` endpoint, which does NOT auto-fire. The app must emit `session_start` explicitly right after each open-session call. `/kinoa-sync-event-integration` will check whether you already do, and set it up if not."

If you can't tell from a quick grep, skip the note rather than guess.

If `ok: false`, surface `http_status` and `response`. Common cases:
- 401 → game secret is wrong; tell the user to recheck their Kinoa credentials.
- 400 → request body invalid; show `response` so they can fix the field name or type.
- network/0 → connectivity issue; show `body` and stop.
