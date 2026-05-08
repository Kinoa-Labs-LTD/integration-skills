---
name: kinoa-dashboard-event
description: Pure admin-API wrapper for Kinoa game_event definitions on the dashboard side. List predefined and custom events, fetch a single event, publish a predefined event, create custom events with parameters, and soft-delete events. Use whenever the user wants to inspect or directly manipulate event definitions in the Kinoa dashboard (without going through the full integration workflow). The orchestration skill kinoa-sync-event-integration delegates to this skill for all dashboard operations.
argument-hint: [list-predefined | list-custom | get | publish | create | delete] [args]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill is a thin CLI wrapper around the Kinoa **admin** event API on `dashboard.kinoa.io`. It does **not** orchestrate any workflow — for the discover-diff-apply integration flow, use `kinoa-sync-event-integration`, which delegates here for every admin call.

The helper script `kinoa_dashboard_event.py` is self-contained — no imports from sibling skills.

Requires `KINOA_BEARER_TOKEN` and `KINOA_GAME_ID` in `~/.kinoa/session.env`. If missing, the helper returns `error: missing_credentials` — set up Kinoa credentials first.

## Subcommands

```
python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" list-predefined [--rows N]
    GET https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=PREDEFINED

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" list-custom [--rows N]
    GET https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=USER

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" get --event-id UUID
    GET https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>
    Returns the full event record incl. game_event_parameters.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" publish --event-id UUID
    Two-step: GET the event, then PUT the same body to /game_events/<id>/publish.
    Flips status NOT_IMPLEMENTED → ACTIVE.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" create --name NAME [--no-analytics] [--param NAME:KIND[:EXTRA]]...
    POST https://dashboard.kinoa.io/gamemetaapi/api/game_events
    KIND ∈ {number, boolean, string, enumeration, string_array, number_array}.
    For enumeration, EXTRA is the comma-separated allowed values.
    Kinoa auto-adds system params device_id, time, time_ms.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" delete --event-id UUID
    DELETE https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>
    Soft delete (returns 200; record state becomes "deleted").
```

Every subcommand prints a single JSON object: `{ http_status, ok, response | request_body, ...context }`.

## Security boundary

This skill calls `dashboard.kinoa.io` with `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID). **Skill-only / admin** — never embed these calls or the bearer token in application runtime code. App code uses `gate.kinoa.io` with the public `game: <secret>` header (see Postman collection at `../kinoa-api-integration/references/postman-collection.json`).

## When to use

- Direct admin tasks (e.g., "publish event X by id", "list active custom events", "delete a stale custom event").
- Invoked by `kinoa-sync-event-integration` for every admin step in the discover-diff-apply workflow.
- Useful for debugging integration problems by inspecting event records directly.

For anything beyond a single admin call (discovery, generating `KinoaEvents`, computing the diff, deciding the player_state strategy, running the test scenario), use `kinoa-sync-event-integration` instead.
