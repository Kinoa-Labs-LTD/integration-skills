---
name: kinoa-init
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `init` dispatch (Phase 0 of onboarding). Initializes Kinoa credentials: asks for game UUID, game secret, and bearer token; persists to ~/.kinoa/session.env; validates against dashboard.kinoa.io; offers to switch integration_type to API if needed. When the user wants to set up Kinoa, start a Kinoa session, configure Kinoa credentials, or wire Kinoa into a project, route via kinoa-api-integration init rather than triggering this skill standalone — the orchestrator owns the sequence (init → player fields → open-session → events) and skipping ahead leads to silently broken integrations.
argument-hint: [optional: game_id=… game_secret=… bearer=…]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill captures three values, persists them (along with a hardcoded `KINOA_INTEGRATION_TYPE=API`), and validates the project against Kinoa's admin API. The helper script `kinoa_init.py` lives in this skill's folder and has no external imports, so the skill is fully self-contained.

**Integration type is always API.** Do not ask the developer; do not offer SDK as an option. Every other Kinoa skill assumes API mode.

## Step 1: Collect three values

If `$ARGUMENTS` or the conversation already contains them, reuse those values and skip to Step 2.

Otherwise ask via `AskUserQuestion`:

- **Game ID (UUID)** — "What is the internal game UUID for this project?" Found in the Kinoa dashboard URL when viewing the project (a UUID like `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`). This is *different* from the game secret — the dashboard admin API rejects requests without it.
- **Game secret** — "Paste the game secret from Kinoa → Integration menu." (used as the `game` header on the public Player Events API.)
- **Bearer token** — "Paste the bearer token from Kinoa → Integration menu."

Free-text values come through the "Other" input on each question.

## Step 2: Run init

```
python "${CLAUDE_SKILL_DIR}/kinoa_init.py" \
    --game-id "<game_uuid>" \
    --game-secret "<game_secret>" \
    --bearer-token "<bearer_token>"
```

The script:
- Writes `~/.kinoa/session.env` with `KINOA_INTEGRATION_TYPE=API`, `KINOA_GAME_ID`, `KINOA_GAME_SECRET`, `KINOA_BEARER_TOKEN` (mode `0600`).
- Calls `GET https://dashboard.kinoa.io/gamemetaapi/api/game-settings` with headers `Authorization: Bearer <bearer_token>`, `Game: <game_uuid>`, and `Game-Id: <game_uuid>` (both headers carry the same UUID — Kinoa accepts either name and we send both).
- Compares the returned `integration_type` against `API`.
- Prints a JSON object with `http_status`, `integration_type` (actual), `expected_integration_type` (`API`), `ok`, and on failure a `reason`.

## Step 3: Interpret the result

Read the JSON. Branch:

- `ok: true` (status 200, integration_type is `API`) → "Init complete — project is set to API integration." Continue to Step 4.
- `reason: "unauthorized"` (401/403) → tell the user the bearer token was rejected; ask them to recheck it in the Integration menu and re-run init. Stop.
- `reason: "not_found"` (404) → tell the user Kinoa returned 404 — the bearer probably belongs to a different project, or the Game-Id is wrong. Stop.
- `reason: "wrong_integration_type"` → ask via `AskUserQuestion`:
  > "Your project's integration_type is `<actual>` but these skills require `API`. Switch the project to `API` now?"
  - Yes → re-run the same command with `--fix-integration-type`. Read the new JSON; if `ok: true` continue, otherwise surface the error.
  - No → stop. (Without API mode the rest of the skills cannot proceed correctly.)
- `reason: "network_error"` → show the `body` field, ask the user to check connectivity. Stop.
- Any other non-2xx → surface `http_status` and `body` for diagnosis.

## Step 4: Print export commands

Print four lines so the user can paste them into a separate shell if needed:

```
export KINOA_INTEGRATION_TYPE=API
export KINOA_GAME_ID=<game_uuid>
export KINOA_GAME_SECRET=<game_secret>
export KINOA_BEARER_TOKEN=<bearer_token>
```

The skill itself doesn't need them in the parent shell — every Kinoa skill reads `~/.kinoa/session.env` automatically.
