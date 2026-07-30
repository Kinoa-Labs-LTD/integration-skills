---
name: kinoa-dashboard-player-fields
description: Pure admin-API wrapper for Kinoa player_field definitions on the dashboard side, plus the public get-player-state read for verification. List predefined and custom fields, activate predefined fields, create custom fields, soft-delete fields, fetch a player's full state. Use whenever the user wants to inspect or directly manipulate player-field definitions in the Kinoa dashboard. The orchestration skill kinoa-sync-player-fields-integration delegates to this skill for all dashboard operations.
argument-hint: [list-predefined | list-custom | activate | create | delete | get-player-state] [args]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill is a thin CLI wrapper around the Kinoa **admin** player-field API on `dashboard.kinoa.io`, plus the public player-state read on `gate.kinoa.io`. It does **not** orchestrate any workflow — for the discover-diff-apply integration flow, use `kinoa-sync-player-fields-integration`, which delegates here for every admin call.

The helper script `kinoa_dashboard_player_fields.py` is self-contained.

Requires `KINOA_BEARER_TOKEN`, `KINOA_GAME_ID`, and (for `get-player-state`) `KINOA_GAME_SECRET` in `~/.kinoa/session.env`.

## Subcommands

```
python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_player_fields.py" list-predefined [--states active,not_implemented] [--rows N]
    GET https://dashboard.kinoa.io/gamemetaapi/api/player_fields?types=PREDEFINED

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_player_fields.py" list-custom [--states active] [--rows N]
    GET https://dashboard.kinoa.io/gamemetaapi/api/player_fields?types=USER

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_player_fields.py" activate --field-id UUID
    PATCH https://dashboard.kinoa.io/gamemetaapi/api/player_fields/<id>/ACTIVATE
    Flips a predefined field state from not_implemented → active. Also re-activates
    a soft-deleted USER field — for deleted fields, activate instead of create
    (create would collide or duplicate the path).

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_player_fields.py" create --name NAME --path PATH --kind KIND [--extra ...] [--description ...] [--default-value ...] [--app-version ...] [--calculated]
    POST https://dashboard.kinoa.io/gamemetaapi/api/player_fields
    KIND ∈ {number, boolean, string, date, long_string, enumeration, version}.
    For enumeration, --extra is the comma-separated allowed values.
    NOTE: --default-value is only valid together with --calculated (EXTERNAL
    fields). On a normal (non-calculated) field the live API rejects it with
    HTTP 422 "defaultValue can only be set for calculated (EXTERNAL) fields" —
    so for code-backed game fields omit it (the SDK-sync flow never passes it).

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_player_fields.py" delete --field-id UUID
    DELETE https://dashboard.kinoa.io/gamemetaapi/api/player_fields/<id>
    Soft delete (returns 204; field state becomes "deleted").
    MANDATORY confirmation before running: ask via AskUserQuestion, naming the
    resolved field id AND its name/path (soft delete — recoverable by activate).
    Proceed only on an explicit Yes from this session — even when the request
    already said "delete X", the confirmation validates the *resolved id*.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_player_fields.py" get-player-state --player-id ID
    GET https://gate.kinoa.io/playerevents/api/v3/player-state?player_id=ID
    Public API (uses game-secret header, not session token). Returns full player state for verification.
```

Every subcommand prints a single JSON object: `{ http_status, ok, response | request_body, ...context }`.

**Cross-game backstop (`--expect-game UUID`)** — accepted by every *mutating* subcommand (`activate`, `create`, `delete`). When passed, the helper aborts with `error: session_game_mismatch` (exit 2) *before* any state change unless `session.env`'s `KINOA_GAME_ID` equals the given UUID — guarding against a stale session from another game. Mirrors the SDK-sync planner's `listing_game_mismatch` check. Orchestrators should always pass the intended/manifest game id; omitting it preserves the previous behavior.

## Security boundary

`list-predefined` / `list-custom` / `activate` / `create` / `delete` call `dashboard.kinoa.io` with `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID) — **skill-only / admin**. Never embed these calls in application runtime code.

`get-player-state` calls `gate.kinoa.io` with `game: <secret>` (public). This is the same surface application code uses for player-state reads, so it's a faithful end-to-end check.

## When to use

- Direct admin tasks (e.g., "activate field X by id", "list deleted custom fields").
- Invoked by `kinoa-sync-player-fields-integration` for every admin step (API-integration mode).
- Invoked by `kinoa-sdk-dashboard-sync` for every player-field operation when mirroring an SDK-integrated game's manifest onto the dashboard (SDK mode).
- Useful for debugging by inspecting field records or player state directly.

For anything beyond a single admin call (discovery, generating `KinoaPlayerState`, computing the diff, running the test scenario), use `kinoa-sync-player-fields-integration` (API mode) or `kinoa-sdk-dashboard-sync` (SDK mode) instead.
