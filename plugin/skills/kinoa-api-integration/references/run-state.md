# Run state (resume support) — canonical schema + merge rules

A full integration outlives a single conversation context. Every workflow therefore persists its decisions to **`.kinoa-integration-state.json`** — the durable source of truth for "where are we and what was decided", surviving context compaction and session restarts. Location by mode: `SINGLE` and `MULTI_REPO` → the project/repo root the run happens in; `MONOREPO` → the monorepo root (one file shared by all services). Mode semantics: `architecture-modes.md` in this folder.

Rules (apply in every sub-skill):

- **Read on start.** If the file exists and its `game_id` matches `KINOA_GAME_ID`, summarize the recorded progress to the developer and resume from the first unfinished phase instead of restarting. If `game_id` differs, ask before overwriting. In `MULTI_REPO`, also read the central index to see what other services already integrated.
- **Update on every `phase-end`.** Whenever you fire the `phase-end` webhook, also read-merge-write this file: update only your own phase's entry, never drop the others'. Update the registry (`KINOA-INTEGRATION.md` — see `integration-registry.md` in this folder) and — in `MULTI_REPO` — the central index in the same breath.
- **Record decisions and created resource ids, not narration.** Statuses are `in_progress | done | skipped`.
- Suggest adding `.kinoa-integration-state.json` to the project's `.gitignore` (alongside the report HTMLs). `KINOA-INTEGRATION.md` is the opposite — it should be committed.
- **Version the dialect.** Always write `"schema_version": 1` at the top level. (Do not confuse it with `phases.feature_settings.schema_version`, which is the Kinoa *feature schema's* version number — an unrelated field that happens to share the name.) The plugin auto-updates between sessions, so a resumed run may read a state file written by an older plugin commit; on an unknown/higher `schema_version`, or a file that doesn't parse as JSON at all, don't guess — summarize what's recoverable (from `KINOA-INTEGRATION.md` and the Dashboard), tell the developer, and rebuild the entry rather than silently misreading it. A missing `schema_version` means "written before versioning" — treat as version 1.
- **Authority on conflict.** When stores disagree, **this state file wins** for decisions and per-phase progress (`architecture`, `session_start_auto_fires`, `player_state_strategy`, created ids). `~/.kinoa/session.env` is connection identity (credentials) plus a machine-global *default* for `architecture` — it is shared by every project on the machine, so a per-project value in this file always overrides it. `KINOA-INTEGRATION.md` and the MULTI_REPO central index are derived views — rebuild them from this file (and the Dashboard), never the reverse, except when this file is lost entirely.

```json
{
  "schema_version": 1,
  "game_id": "<KINOA_GAME_ID>",
  "architecture": "SINGLE | MONOREPO | MULTI_REPO",
  "service": "<this repo's service name — MULTI_REPO only>",
  "updated_at": "<ISO 8601 UTC>",
  "phases": {
    "init":             {"status": "done"},
    "player_fields":    {"status": "done", "service_root": "<MONOREPO only>",
                         "kinoa_player_state_path": "...",
                         "install_time_fields": "both|ms_only|seconds_only|none",
                         "report": "..."},
    "open_session":     {"status": "done", "service_root": "<MONOREPO only>",
                         "player_id": "...", "session_id": "..."},
    "events":           {"status": "in_progress", "service_root": "<MONOREPO only>",
                         "kinoa_events_path": "...",
                         "session_start_auto_fires": true, "player_state_strategy": "FULL|DIFF",
                         "approved_events": ["..."], "report": "..."},
    "feature_settings": {"status": "skipped", "service_root": "<MONOREPO only>",
                         "schema_id": "...", "schema_version": "...",
                         "setting_id": "...", "setting_key": "...", "config_id": "...",
                         "facade_path": "...", "report": "..."},
    "resource_templates": {"status": "skipped", "service_root": "<MONOREPO only>",
                         "kinoa_resources_path": "...",
                         "confirmed_resources": ["<resourceKey>"],
                         "registered": [{"id": "...", "key": "...", "status": "ACTIVE|DRAFT"}],
                         "report": "..."}
  }
}
```

**MONOREPO, same module in several services.** When a module (typically events — several services each emit their own) is integrated from more than one service, nest the per-service artifacts under a `services` map keyed by service root, keeping game-wide decisions at the module level:

```json
"events": {
  "status": "in_progress",
  "session_start_auto_fires": true,
  "player_state_strategy": "DIFF",
  "services": {
    "services/analytics-svc": {"status": "done", "kinoa_events_path": "...",
                               "approved_events": ["..."], "report": "..."},
    "services/shop-svc":      {"status": "in_progress"}
  }
}
```
