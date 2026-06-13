---
name: kinoa-dashboard-event
description: Pure admin-API wrapper for Kinoa game_event definitions on the dashboard side. List predefined and custom events, fetch a single event, publish a predefined event, create custom events with parameters, add parameters to existing events, and delete events (HARD delete — irreversible). Use whenever the user wants to inspect or directly manipulate event definitions in the Kinoa dashboard (without going through the full integration workflow). The orchestration skills kinoa-sync-event-integration (API mode) and kinoa-sdk-dashboard-sync (SDK mode) delegate to this skill for all dashboard operations.
argument-hint: [list-predefined | list-custom | get | publish | create | add-params | delete] [args]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill is a thin CLI wrapper around the Kinoa **admin** event API on `dashboard.kinoa.io`. It does **not** orchestrate any workflow — for the discover-diff-apply integration flow, use `kinoa-sync-event-integration`, which delegates here for every admin call.

The helper script `kinoa_dashboard_event.py` is self-contained — no imports from sibling skills.

Requires `KINOA_BEARER_TOKEN` and `KINOA_GAME_ID` in `~/.kinoa/session.env`. If missing, the helper returns `error: missing_credentials` — set up Kinoa credentials first.

## Subcommands

```
python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" list-predefined [--rows N] [--states s1,s2]
    GET https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=PREDEFINED

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" list-custom [--rows N] [--states s1,s2]
    GET https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=USER
    --states adds selectedFilters=states&states=... NOTE (verified live
    2026-06-12): the game_events endpoint IGNORES this filter — events have no
    deleted state. Retained for forward-compat only; soft-delete probing
    applies to player fields, not events.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" get --event-id UUID
    GET https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>
    Returns the full event record incl. game_event_parameters.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" publish --event-id UUID
    Two-step: GET the event, then PUT the same body to /game_events/<id>/publish.
    Flips status NOT_IMPLEMENTED → ACTIVE (predefined events).
    NOTE: publishing replaces the record under a NEW id — re-resolve ids from a
    fresh listing before any further operation on the same event.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" create --name NAME [--no-analytics] [--param NAME:KIND[:EXTRA]]...
    POST https://dashboard.kinoa.io/gamemetaapi/api/game_events
    KIND ∈ {number, boolean, string, date, enumeration, string_array, number_array}.
    For enumeration, EXTRA is the comma-separated allowed values.
    Kinoa auto-adds system params device_id, time, time_ms.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" add-params --event-id UUID --param NAME:KIND[:EXTRA]...
    Two-step: GET the full event record, append the new non-system parameters to
    game_event_parameters (names already present are skipped, reported under
    skipped_existing), PUT the merged record back to /game_events/<id>.
    Works on USER events and on PREDEFINED events (operator params on predefined).

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_event.py" delete --event-id UUID
    DELETE https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>
    HARD delete, irreversible (verified live 2026-06-12): the record is gone
    for good — GET returns 404, no listing shows it, the only recovery is
    create under a new id. (Player-field delete is soft; event delete is NOT.)
    Never invoke from within a sync/orchestration run (kinoa-sdk-dashboard-sync
    hard rule 1; kinoa-sync-event-integration never deletes either) — dedicated
    operator-initiated admin sessions only, after listing and confirming each id.
```

Every subcommand prints a single JSON object: `{ http_status, ok, response | request_body, ...context }`.

## Security boundary

This skill calls `dashboard.kinoa.io` with `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID). **Skill-only / admin** — never embed these calls or the session token in application runtime code. App code uses `gate.kinoa.io` with the public `game: <secret>` header (see Postman collection at `../kinoa-api-integration/references/postman-collection.json`).

## When to use

- Direct admin tasks (e.g., "publish event X by id", "list active custom events", "delete a stale custom event" — delete ONLY as an operator-initiated task in its own session, never mid-sync; it is a hard, irreversible delete).
- Invoked by `kinoa-sync-event-integration` for every admin step in the discover-diff-apply workflow (API-integration mode).
- Invoked by `kinoa-sdk-dashboard-sync` for every event operation when mirroring an SDK-integrated game's manifest onto the dashboard (SDK mode).
- Useful for debugging integration problems by inspecting event records directly.

For anything beyond a single admin call (discovery, generating `KinoaEvents`, computing the diff, deciding the player_state strategy, running the test scenario), use `kinoa-sync-event-integration` (API mode) or `kinoa-sdk-dashboard-sync` (SDK mode) instead.
