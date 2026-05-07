---
name: kinoa-api-integration
description: Umbrella skill for integrating with the Kinoa Player Events API from Claude Code. The integration is split across two axes — code-side workflows (kinoa-sync-*-integration) and dashboard admin tools (kinoa-dashboard-*) — plus a session runtime helper (kinoa-open-session) and a setup step (kinoa-init). Use whenever the user wants to integrate with Kinoa, set up the Kinoa API, onboard application code with Kinoa, or run the full onboarding + fields + events flow end-to-end.
argument-hint: [init | sync-player-fields-integration | dashboard-player-fields | open-session | sync-event-integration | dashboard-event] [extra args]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit AskUserQuestion
---

This is the **orchestrator** for the Kinoa API integration. It dispatches to one of six sub-skills based on the first token in `$ARGUMENTS`. The sub-skills come in two flavors:

- **Workflow skills** drive multi-step processes (init, sync-*-integration, open-session).
- **Dashboard skills** are pure admin-API wrappers; the integration skills delegate to them. They're also independently invokable for direct admin tasks.

| Subcommand                          | Sub-skill folder                          | Slash command                            | Purpose |
|-------------------------------------|-------------------------------------------|------------------------------------------|---------|
| `init`                              | `../kinoa-init/`                          | `/kinoa-init`                            | Phase 0 — capture integration type + game ID + tokens, validate against the Kinoa admin API. |
| `sync-player-fields-integration`    | `../kinoa-sync-player-fields-integration/`| `/kinoa-sync-player-fields-integration`  | Phase 1 (workflow) — discover the app's player class, generate `KinoaPlayerState`, diff app fields against Kinoa, drive activations / creations / verification by delegating to `kinoa-dashboard-player-fields`. |
| `dashboard-player-fields`           | `../kinoa-dashboard-player-fields/`       | `/kinoa-dashboard-player-fields`         | Helper — pure admin CLI wrapper for player-field defs (list / activate / create / delete) plus public `get-player-state`. Used by Phase 1; also invokable directly. |
| `open-session`                      | `../kinoa-open-session/`                  | `/kinoa-open-session`                    | Phase 2 — open a player session via `/player/session/start`. Implementing open-session in app runtime is also a prerequisite for Phase 3 (auto-fires `session_start`). |
| `sync-event-integration`            | `../kinoa-sync-event-integration/`        | `/kinoa-sync-event-integration`          | Phase 3 (workflow) — discover events the app emits, generate `KinoaEvents`, diff against Kinoa, drive publishes / creations / verification by delegating to `kinoa-dashboard-event`. Owns the runtime test helper (`kinoa_send_event.py`) used in Phase D. |
| `dashboard-event`                   | `../kinoa-dashboard-event/`               | `/kinoa-dashboard-event`                 | Helper — pure admin CLI wrapper for game-event defs (list / get / publish / create / delete). Used by Phase 3; also invokable directly. |

Each sub-skill is **fully self-contained** — its own Python helper script lives in its folder, with no imports from sibling skills. This skill (`kinoa-api-integration`) holds only the orchestration prompt, the Postman reference, and the install guide. Other future skills can import any one of the sub-skills in isolation.

## How to dispatch

1. **Parse the first token of `$ARGUMENTS`.** It should be one of `init`, `sync-player-fields-integration`, `dashboard-player-fields`, `open-session`, `sync-event-integration`, `dashboard-event`.
2. **If empty or unrecognized**, ask the user via `AskUserQuestion` which subcommand to run. Offer the workflow steps first, with the dashboard helpers as a separate group:
   - "Init — set up Kinoa credentials and validate the project."
   - "Sync player fields (integration) — mirror the app's player model into Kinoa and verify."
   - "Open session — start a player session."
   - "Sync events (integration) — mirror the app's emitted events into Kinoa and verify."
   - "Dashboard player fields — direct admin tools for player-field defs."
   - "Dashboard event — direct admin tools for event defs."
3. **Once the subcommand is known, follow the matching sub-skill's `SKILL.md`** by reading it with the `Read` tool and executing its steps. Pass through any remaining `$ARGUMENTS` tokens to the sub-skill.
   - `init`                            → `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md`
   - `sync-player-fields-integration`  → `${CLAUDE_SKILL_DIR}/../kinoa-sync-player-fields-integration/SKILL.md`
   - `dashboard-player-fields`         → `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/SKILL.md`
   - `open-session`                    → `${CLAUDE_SKILL_DIR}/../kinoa-open-session/SKILL.md`
   - `sync-event-integration`          → `${CLAUDE_SKILL_DIR}/../kinoa-sync-event-integration/SKILL.md`
   - `dashboard-event`                 → `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/SKILL.md`

When all four skills are installed as siblings under `~/.claude/skills/` (see `HOW-TO.md`), the relative paths resolve correctly.

## End-to-end flow

A typical first-time integration session looks like:

1. `/kinoa-init` — collect credentials, validate, persist to `~/.kinoa/session.env`.
2. `/kinoa-sync-player-fields-integration` — discover the app's player class, generate `KinoaPlayerState`, drive the diff & apply (delegates each admin call to `kinoa-dashboard-player-fields`), verify.
3. `/kinoa-open-session` — verify the open-session call works against your project. The developer also implements this call in their own app runtime — prerequisite for the next phase since `session_start` is auto-fired by the open-session endpoint.
4. `/kinoa-sync-event-integration` — discover events the app emits, generate `KinoaEvents`, drive publishes / creations (delegates each admin call to `kinoa-dashboard-event`), verify. Phase D includes a runtime test send via the local `kinoa_send_event.py` helper.

`kinoa-dashboard-player-fields` and `kinoa-dashboard-event` aren't usually invoked directly during a fresh integration — they're called by the integration skills above. Use them directly when you need a one-off admin operation (e.g., "publish event X by id" or "delete a stale custom field") without running the full workflow.

Each sub-skill is also independently invokable with its own slash command — the orchestrator makes the full sequence discoverable from one entry point.

## Reference

- Postman collection: `references/postman-collection.json` (the source export the user provided).
- Endpoints used:
  - Admin: `GET / POST https://dashboard.kinoa.io/gamemetaapi/api/game-settings`
  - Session start (new): `POST https://gate.kinoa.io/playerevents/api/v3/player/session/start`
  - Sync event: `POST https://gate.kinoa.io/playerevents/api/v3/sync-event?player_id=…`

Installation and how to obtain the two tokens are documented in `HOW-TO.md`.
