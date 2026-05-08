---
name: kinoa-api-integration
description: Umbrella orchestrator for integrating an application with the Kinoa Player Events API end-to-end from Claude Code. Dispatches to one of six sub-skills — credential setup (init), player-state sync (sync-player-fields-integration), session debug helper (open-session), event sync (sync-event-integration), and the two dashboard admin wrappers (dashboard-player-fields, dashboard-event). Also accepts `all` to run the full onboarding sequence (init → player fields → open-session → events). Use whenever the user wants to integrate with Kinoa, set up the Kinoa API, onboard application code with Kinoa, run the full onboarding flow, sync the player model or events with the Kinoa dashboard, open a player session, publish or create event/field definitions, or perform any Kinoa admin task — even when they don't name a specific subcommand. Do NOT use for unrelated player-tracking or analytics platforms (Mixpanel, Amplitude, GameAnalytics, etc.) — this is Kinoa-specific.
argument-hint: [all | init | sync-player-fields-integration | dashboard-player-fields | open-session | sync-event-integration | dashboard-event] [extra args]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit AskUserQuestion
---

This is the **orchestrator** for the Kinoa API integration. It dispatches to one of six sub-skills based on the first token in `$ARGUMENTS`. The sub-skills come in two flavors:

- **Workflow skills** drive multi-step processes (init, sync-*-integration, open-session).
- **Dashboard skills** are pure admin-API wrappers; the integration skills delegate to them. They're also independently invokable for direct admin tasks.

| Subcommand                          | Sub-skill folder                          | Slash command                            | Purpose |
|-------------------------------------|-------------------------------------------|------------------------------------------|---------|
| `init`                              | `../kinoa-init/`                          | `/kinoa-init`                            | Phase 0 — capture game ID + tokens (integration type is hardcoded to API), validate against the Kinoa admin API. |
| `sync-player-fields-integration`    | `../kinoa-sync-player-fields-integration/`| `/kinoa-sync-player-fields-integration`  | Phase 1 (workflow) — discover the app's player class, generate `KinoaPlayerState`, diff app fields against Kinoa, drive activations / creations / verification by delegating to `kinoa-dashboard-player-fields`. |
| `dashboard-player-fields`           | `../kinoa-dashboard-player-fields/`       | `/kinoa-dashboard-player-fields`         | Helper — pure admin CLI wrapper for player-field defs (list / activate / create / delete) plus public `get-player-state`. Used by Phase 1; also invokable directly. |
| `open-session`                      | `../kinoa-open-session/`                  | `/kinoa-open-session`                    | Phase 2 — open a player session via `/player/session/start`. Implementing open-session in app runtime is also a prerequisite for Phase 3 (auto-fires `session_start`). |
| `sync-event-integration`            | `../kinoa-sync-event-integration/`        | `/kinoa-sync-event-integration`          | Phase 3 (workflow) — discover events the app emits, generate `KinoaEvents`, diff against Kinoa, drive publishes / creations / verification by delegating to `kinoa-dashboard-event`. Owns the runtime test helper (`kinoa_send_event.py`) used in Phase D. |
| `dashboard-event`                   | `../kinoa-dashboard-event/`               | `/kinoa-dashboard-event`                 | Helper — pure admin CLI wrapper for game-event defs (list / get / publish / create / delete). Used by Phase 3; also invokable directly. |

Each sub-skill is **fully self-contained** — its own Python helper script lives in its folder, with no imports from sibling skills. This skill (`kinoa-api-integration`) holds only the orchestration prompt, the Postman reference, and the install guide. Other future skills can import any one of the sub-skills in isolation.

## How to dispatch

The user may invoke this skill with an explicit subcommand token, or they may describe what they want in plain English. Handle both.

### Step 1 — Resolve a subcommand

**Case A: explicit token in `$ARGUMENTS`.** First token is one of:

| Token | Meaning |
|---|---|
| `all` | Run the full onboarding sequence (see Step 3 below). |
| `init` | Capture credentials + validate project. |
| `sync-player-fields-integration` | Player-class → `KinoaPlayerState` workflow. |
| `dashboard-player-fields` | Direct admin tools for player-field defs. |
| `open-session` | Open a player session (debug/verify helper). |
| `sync-event-integration` | App-events → `KinoaEvents` workflow. |
| `dashboard-event` | Direct admin tools for event defs. |

If the token matches, use it. Pass remaining tokens through as `$ARGUMENTS` to the sub-skill.

**Case B: no/unknown token but the request describes a task.** Map intent → subcommand using this table before falling back to a question:

| User says (paraphrased)… | Dispatch to |
|---|---|
| "set up Kinoa", "configure credentials", "wire up Kinoa for this project", "I have a bearer token / game id" | `init` |
| "integrate Kinoa", "onboard this app with Kinoa", "do the full integration", "everything from scratch" | `all` |
| "sync the player model", "mirror player fields", "generate KinoaPlayerState", "what custom player fields do we need" | `sync-player-fields-integration` |
| "list / activate / create / delete a player field", "inspect player_state for a player", "what fields does player X have" | `dashboard-player-fields` |
| "open a session for player X", "start a Kinoa session", "test the open-session endpoint" | `open-session` |
| "sync events", "mirror app events", "generate KinoaEvents", "which events should we publish" | `sync-event-integration` |
| "publish event X", "create a custom event", "delete a stale event", "list our events" | `dashboard-event` |

**Case C: still ambiguous.** Ask via `AskUserQuestion`. Offer the workflow steps first, dashboard helpers as a second group:
- "Init — set up Kinoa credentials and validate the project."
- "Sync player fields — mirror the app's player model into Kinoa and verify."
- "Open session — start a player session (verification helper)."
- "Sync events — mirror the app's emitted events into Kinoa and verify."
- "All — run the full onboarding sequence end-to-end."
- "Dashboard player fields — direct admin tools for player-field defs."
- "Dashboard event — direct admin tools for event defs."

### Step 2 — For a single subcommand, read and follow its SKILL.md

Read with the `Read` tool, then execute its steps. Pass through any remaining `$ARGUMENTS` tokens.

| Subcommand | Path |
|---|---|
| `init` | `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md` |
| `sync-player-fields-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-player-fields-integration/SKILL.md` |
| `dashboard-player-fields` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/SKILL.md` |
| `open-session` | `${CLAUDE_SKILL_DIR}/../kinoa-open-session/SKILL.md` |
| `sync-event-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-event-integration/SKILL.md` |
| `dashboard-event` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/SKILL.md` |

When all sub-skills are installed as siblings under `~/.claude/skills/` (see `HOW-TO.md`), these paths resolve correctly.

### Step 3 — `all`: run the full onboarding sequence

When the subcommand is `all`, drive the four-phase chain below. Treat each phase as a hand-off: complete it fully, summarize what changed, and confirm with the developer before moving to the next phase. If any phase fails (auth error, validation mismatch, developer rejection), stop and surface the error — do not silently advance.

1. **Phase 0 — `kinoa-init`.** Read `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md` and follow it. Verify `~/.kinoa/session.env` ends with `ok: true`. Capture `KINOA_INTEGRATION_TYPE` for later — the event sync phase branches on it.
2. **Phase 1 — `kinoa-sync-player-fields-integration`.** Drive the player-fields workflow to completion. After Phase D verification, summarize: how many fields activated / created / verified.
3. **Phase 2 — `kinoa-open-session`.** Run it once with a real player_id chosen by the developer. This both verifies the endpoint and (in API + direct-endpoint projects) seeds the auto-fired `session_start` so the next phase has data to inspect. Hand off `KINOA_LAST_PLAYER_ID` / `KINOA_LAST_SESSION_ID` (already persisted by the helper) to Phase 3.
4. **Phase 3 — `kinoa-sync-event-integration`.** Drive the event workflow. Phase A's `SESSION_START_AUTO_FIRES` branch will read `KINOA_INTEGRATION_TYPE` and decide whether `session_start` is auto-published (🔄) or must be wired as an explicit emission (🔁). After Phase D, summarize the run.

After the chain completes, print a one-line summary per phase plus any items the developer skipped (so they can re-run individual subcommands later).

## End-to-end flow (the `all` sequence, expanded)

A first-time integration runs through these four phases. The `all` subcommand drives them automatically; the developer can also invoke each as a standalone slash command.

1. `/kinoa-init` — collect credentials (integration type is hardcoded to `API`), validate against `dashboard.kinoa.io`, persist to `~/.kinoa/session.env`.
2. `/kinoa-sync-player-fields-integration` — discover the app's player class, generate `KinoaPlayerState`, drive the diff & apply (delegates each admin call to `kinoa-dashboard-player-fields`), verify.
3. `/kinoa-open-session` — verify the open-session endpoint works against this project. **Important nuance**: this helper always hits `gate.kinoa.io/playerevents/api/v3/player/session/start` directly, which always auto-fires `session_start` server-side. That tells you the *endpoint* is wired up — but it does NOT mean the app's runtime path will auto-fire. Whether the app's runtime path auto-fires depends on whether it calls this exact endpoint (API integrations may or may not; SDK integrations definitely do not).
4. `/kinoa-sync-event-integration` — discover events the app emits, generate `KinoaEvents`, decide `session_start` handling per the `SESSION_START_AUTO_FIRES` branch, drive publishes / creations (delegates each admin call to `kinoa-dashboard-event`), verify. Phase D includes a runtime test send via the local `kinoa_send_event.py` helper.

`kinoa-dashboard-player-fields` and `kinoa-dashboard-event` aren't usually invoked directly during a fresh integration — they're called by the integration skills above. Use them directly when you need a one-off admin operation (e.g., "publish event X by id" or "delete a stale custom field") without running the full workflow.

Each sub-skill is also independently invokable with its own slash command — the orchestrator makes the full sequence discoverable from one entry point.

## Reference

- Postman collection: `references/postman-collection.json` (the source export the user provided).
- Endpoints used:
  - Admin: `GET / POST https://dashboard.kinoa.io/gamemetaapi/api/game-settings`
  - Session start (new): `POST https://gate.kinoa.io/playerevents/api/v3/player/session/start`
  - Sync event: `POST https://gate.kinoa.io/playerevents/api/v3/sync-event?player_id=…`

Installation and how to obtain the two tokens are documented in `HOW-TO.md`.
