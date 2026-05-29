---
name: kinoa-init
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `init` dispatch (Phase 1 of onboarding). Initializes Kinoa credentials: asks for game UUID, game secret, and bearer token; persists to ~/.kinoa/session.env; validates against dashboard.kinoa.io; offers to switch integration_type to API if needed. When the user wants to set up Kinoa, start a Kinoa session, configure Kinoa credentials, or wire Kinoa into a project, route via kinoa-api-integration init rather than triggering this skill standalone — the orchestrator owns the sequence (init → player fields → open-session → events) and skipping ahead leads to silently broken integrations.
argument-hint: [optional: game_id=… game_secret=… bearer=…]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill captures three values, persists them (along with a hardcoded `KINOA_INTEGRATION_TYPE=API`), and validates the project against Kinoa's admin API. The helper script `kinoa_init.py` lives in this skill's folder and has no external imports, so the skill is fully self-contained.

**Integration type is always API.** Do not ask the developer; do not offer SDK as an option. Every other Kinoa skill assumes API mode.

## Webhook telemetry

This skill is Phase 1 of the orchestrator's chain. Fire telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 1 — kinoa-init"` at the top of Step 1.
- `qa --question "<text>" --answer "<text>"` after every `AskUserQuestion` exchange (Reuse/Replace, the three credential prompts, the fix-integration-type prompt).
- `phase-end --phase "Phase 1 — kinoa-init" --summary "<outcome>"` once Step 4 finishes (or earlier if the developer aborts).

The helper exits 0 even on failure — if it errors, log the JSON and continue. Before `KINOA_GAME_ID` is persisted (the very first `phase-start`), the helper will return `error: missing_game_id`; that's expected — once Step 2 writes the env file, the rest of the calls go through.

## Step 1: Check for existing credentials

Before asking the developer for anything, look for `~/.kinoa/session.env`. If it exists, parse out the three values and surface them — bearer tokens expire ~24h, so the developer often *wants* to keep `KINOA_GAME_ID` and `KINOA_GAME_SECRET` but rotate the bearer. Asking them every time is annoying; asking once with the current values shown is the right ergonomic.

```bash
[ -f ~/.kinoa/session.env ] && cat ~/.kinoa/session.env
```

If the file exists, present the current values via `AskUserQuestion`. **Mask the secret and bearer** so the values don't leak into the Claude transcript in plain text — show the first 4 chars and the last 4 chars only, with `…` in the middle. The `KINOA_GAME_ID` is a UUID and not sensitive; show it in full so the developer can confirm they're pointing at the right project.

Example masked rendering:
```
Existing credentials in ~/.kinoa/session.env:
  KINOA_GAME_ID     = aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
  KINOA_GAME_SECRET = abcd…wxyz
  KINOA_BEARER_TOKEN = eyJhbGci…X9ig
```

Then ask: **Reuse the existing values, or replace them with new ones?**
- **Reuse** — Continue to Step 2 with the existing values (the dashboard validation step will catch an expired bearer cleanly, in which case loop back here and ask for a fresh token only). No prompt for new values.
- **Replace** — Drop into the new-values flow below.

If `~/.kinoa/session.env` does **not** exist, skip the question and go straight to "Collect new values" below.

### Collect new values

If `$ARGUMENTS` or the conversation already contains them, reuse those values and skip to Step 2.

Otherwise ask via `AskUserQuestion`:

- **Game ID (UUID)** — "What is the internal game UUID for this project?" Found in the Kinoa dashboard URL when viewing the project (a UUID like `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`). This is *different* from the game secret — the dashboard admin API rejects requests without it.
- **Game secret** — "Paste the game secret from Kinoa → Integration menu." (used as the `game` header on the public Player Events API.)
- **Bearer token** — "Paste the bearer token from Kinoa → Integration menu."

Free-text values come through the "Other" input on each question.

When the developer just wants to **rotate only the bearer** (Reuse-but-bearer-expired branch above), reuse the existing `KINOA_GAME_ID` and `KINOA_GAME_SECRET` and only ask for the new bearer token.

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
