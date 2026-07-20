# Architecture modes (single app vs microservices) — canonical semantics

A client doesn't always integrate Kinoa from one codebase — with a microservice architecture each module (player fields, events, feature settings, session-open) may live in a different service. Phase 1 (`kinoa-init`) asks up front how the project is laid out and persists the answer as `KINOA_ARCHITECTURE` in `~/.kinoa/session.env` and as `architecture` in the run-state file. Every workflow reads the mode before its discovery phase and scopes itself accordingly:

| Mode | Layout | Behavior |
|---|---|---|
| `SINGLE` (default) | One application, one codebase | The classic flow — discover in the project root; state file + registry in the project root. |
| `MONOREPO` | Several services under one repo root | Run from the repo root. Each workflow first asks **which service directory** this module is integrated from (offer candidate dirs found via Glob — `services/*/`, `apps/*/`, `packages/*/`, or whatever the repo uses). Discovery and generated artifacts are scoped to that `service_root`; one shared state file + one registry live at the repo root. |
| `MULTI_REPO` | Each service is its own checkout (own CLAUDE.md) | The current repo **is** the service. On the first run in a repo, confirm the service name (default: the repo folder name) and register it in the central index. State file + registry live in each repo and cover only that repo's modules. |

**Game-wide decisions must survive repo boundaries.** `session_start_auto_fires`, `player_state_strategy`, and the feature-settings resource ids are decided once per game but consumed by workflows possibly running in other repos. In `MULTI_REPO`, mirror each of these into the central index the moment it is decided, and read the index on workflow start — never re-ask a question another service's run already answered; summarize what was found and let the developer object instead.

## Central index (`MULTI_REPO` only) — `~/.kinoa/<game_id>/services.json`

Separate checkouts share no workspace root, so the cross-repo picture lives in `~/.kinoa/` — the one place all repos on a developer's machine already share (`session.env` lives there too):

```json
{
  "game_id": "<KINOA_GAME_ID>",
  "architecture": "MULTI_REPO",
  "updated_at": "<ISO 8601 UTC>",
  "shared_decisions": {
    "session_start_auto_fires": true,
    "player_state_strategy": "FULL|DIFF",
    "feature_settings": {"schema_id": "...", "schema_version": "...",
                         "setting_id": "...", "setting_key": "...", "config_id": "..."}
  },
  "services": {
    "player-service":    {"root": "/abs/path/to/checkout",
                          "modules": {"player_fields": "done", "open_session": "done"},
                          "last_sync": "<ISO 8601 UTC>"},
    "analytics-service": {"root": "/abs/path/to/checkout",
                          "modules": {"events": "in_progress"},
                          "last_sync": "<ISO 8601 UTC>"}
  }
}
```

Read-merge-write with the same discipline as the run-state file: update only your own service's entry and the `shared_decisions` your run actually made; never drop other services' entries. The index is machine-local — another developer's machine won't have it. When it's missing but a repo's `KINOA-INTEGRATION.md` (or the Dashboard itself) shows prior work, rebuild the relevant entries from those sources instead of assuming a fresh start.
