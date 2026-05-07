---
name: kinoa-init
description: Initialize Kinoa credentials for the current session. Asks for the integration type (API or SDK), the internal game UUID, the game secret, and the bearer token; persists them to ~/.kinoa/session.env; validates the project's integration_type against dashboard.kinoa.io; and offers to switch it to the requested type if it doesn't match. Use whenever the user wants to start a Kinoa session, set up Kinoa credentials, or wire up Kinoa for a project.
argument-hint: [optional: integration_type=… game_id=… game_secret=… bearer=…]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill captures four values, persists them, and validates the project against Kinoa's admin API. The helper script `kinoa_init.py` lives in this skill's folder and has no external imports, so the skill is fully self-contained.

## Step 1: Collect four values

If `$ARGUMENTS` or the conversation already contains them, reuse those values and skip to Step 2.

Otherwise ask via `AskUserQuestion`:

- **Integration type** — "Which integration mode is this project using?" Options: `API` or `SDK`. The skill validates the project's actual integration_type against this choice. Pick `API` for direct HTTP integration; pick `SDK` if the game is using a Kinoa SDK.
- **Game ID (UUID)** — "What is the internal game UUID for this project?" Found in the Kinoa dashboard URL when viewing the project (a UUID like `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`). This is *different* from the game secret — the dashboard admin API rejects requests without it.
- **Game secret** — "Paste the game secret from Kinoa → Integration menu." (used as the `game` header on the public Player Events API.)
- **Bearer token** — "Paste the bearer token from Kinoa → Integration menu."

Free-text values come through the "Other" input on each question.

## Step 2: Run init

```
python "${CLAUDE_SKILL_DIR}/kinoa_init.py" \
    --integration-type "<API|SDK>" \
    --game-id "<game_uuid>" \
    --game-secret "<game_secret>" \
    --bearer-token "<bearer_token>"
```

The script:
- Writes `~/.kinoa/session.env` with `KINOA_INTEGRATION_TYPE`, `KINOA_GAME_ID`, `KINOA_GAME_SECRET`, `KINOA_BEARER_TOKEN` (mode `0600`).
- Calls `GET https://dashboard.kinoa.io/gamemetaapi/api/game-settings` with headers `Authorization: Bearer <bearer_token>` and `Game-Id: <game_uuid>`.
- Compares the returned `integration_type` against the requested one.
- Prints a JSON object with `http_status`, `integration_type` (actual), `expected_integration_type`, `ok`, and on failure a `reason`.

## Step 3: Interpret the result

Read the JSON. Branch:

- `ok: true` (status 200, integration_type matches expected) → "Init complete — project's integration_type is `<X>` as requested." Continue to Step 4.
- `reason: "unauthorized"` (401/403) → tell the user the bearer token was rejected; ask them to recheck it in the Integration menu and re-run init. Stop.
- `reason: "not_found"` (404) → tell the user Kinoa returned 404 — the bearer probably belongs to a different project, or the Game-Id is wrong. Stop.
- `reason: "wrong_integration_type"` → ask via `AskUserQuestion`:
  > "Your project's integration_type is `<actual>` but you requested `<expected>`. Switch the project to `<expected>` now?"
  - Yes → re-run the same command with `--fix-integration-type`. Read the new JSON; if `ok: true` continue, otherwise surface the error.
  - No → stop.
- `reason: "network_error"` → show the `body` field, ask the user to check connectivity. Stop.
- Any other non-2xx → surface `http_status` and `body` for diagnosis.

## Step 4: Print export commands

Print four lines so the user can paste them into a separate shell if needed:

```
export KINOA_INTEGRATION_TYPE=<API|SDK>
export KINOA_GAME_ID=<game_uuid>
export KINOA_GAME_SECRET=<game_secret>
export KINOA_BEARER_TOKEN=<bearer_token>
```

The skill itself doesn't need them in the parent shell — every Kinoa skill reads `~/.kinoa/session.env` automatically.
