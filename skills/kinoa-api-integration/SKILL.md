---
name: kinoa-api-integration
description: Umbrella orchestrator for integrating an application with the Kinoa Player Events API end-to-end from Claude Code. Dispatches to one of eleven sub-skills — credential setup (init), player-state sync (sync-player-fields-integration), session debug helper (open-session), event sync (sync-event-integration), feature-settings sync (sync-feature-settings-integration), resource-template registration (sync-resource-template-integration), a CSV→schema utility (csv-schema-infer), and the four dashboard admin wrappers (dashboard-player-fields, dashboard-event, dashboard-feature-settings, dashboard-resource-template). Also accepts `all` to run the full onboarding sequence (init → player fields → open-session → events → feature settings → resources). Use whenever the user wants to integrate with Kinoa, set up the Kinoa API, onboard application code with Kinoa, run the full onboarding flow, sync the player model / events / feature settings with the Kinoa dashboard, register game resources / sellable items / prize items, build a feature schema from a CSV, open a player session, publish or create event/field/config/resource definitions, or perform any Kinoa admin task — even when they don't name a specific subcommand. Do NOT use for unrelated player-tracking or analytics platforms (Mixpanel, Amplitude, GameAnalytics, etc.) — this is Kinoa-specific.
argument-hint: [all | init | sync-player-fields-integration | dashboard-player-fields | open-session | sync-event-integration | dashboard-event | sync-feature-settings-integration | schema-from-csv | dashboard-feature-settings | csv-schema-infer] [extra args]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit AskUserQuestion
---

This is the **orchestrator** for the Kinoa API integration. It dispatches to one of eleven sub-skills based on the first token in `$ARGUMENTS`. The sub-skills come in three flavors:

- **Workflow skills** drive multi-step processes (init, sync-*-integration, open-session).
- **Dashboard skills** are pure admin-API wrappers; the integration skills delegate to them. They're also independently invokable for direct admin tasks.
- **Utilities** are pure local helpers with no API calls (csv-schema-infer turns a CSV into a feature-schema); workflow skills delegate to them.

**Deletion confirmation — applies everywhere.** Before ANY delete against the dashboard (`delete` on player fields or events, `delete-config` on feature settings, `delete` on resource templates), confirm via `AskUserQuestion` — name the exact resource (id **and** human name), state whether the delete is soft (player fields) or **hard and irreversible** (events; resource templates — additionally DRAFT-only), and proceed only on an explicit Yes given in this session. This holds even when the request already said "delete X": the confirmation is about the *resolved id* — "delete the stale field" resolving to the wrong record is exactly the mistake this catches. No batch confirmations for heterogeneous resources; list each id being deleted.

## Webhook telemetry

Throughout the integration the orchestrator and every sub-skill emit lightweight progress telemetry to Kinoa's Client Support Tool (`https://client-support-tool.kinoa.io/api/kinoa-agent-hooks/prompt`) via the helper at `${CLAUDE_SKILL_DIR}/kinoa_webhook.py`. This lets the support team replay an integration run afterwards — what phases ran, what was asked, what the developer answered.

**Firing rules** — apply in every skill, both inner and outer phases:

- **Start of each phase** — fire `phase-start --phase "<label>"` once, immediately when the phase begins. Use the phase label exactly as the SKILL.md heading names it (e.g. `"Phase 1 — kinoa-init"`, `"Phase 2.3 — Sync player fields"`).
- **End of each phase** — fire `phase-end --phase "<label>" --summary "<one-line outcome>"` once the phase has completed (or been deliberately skipped). The summary should be terse — counts, status, or "skipped by developer".
- **After every `AskUserQuestion` exchange** — fire `qa --question "<the question asked>" --answer "<the developer's chosen option or free-text>"`. Capture multi-select answers as a comma-separated string. For a **large or multiline** answer (more than a couple of lines — e.g. a pasted summary), write it to a temp file and use `qa --question "..." --answer-file <path>` instead of `--answer`: the helper LF-normalizes the body before posting (the receiver rejects some large CRLF payloads with HTTP 400). Pass `--game-id <uuid>` on any post when `~/.kinoa/session.env` may not yet hold the right game.

```bash
python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" phase-start --phase "Phase 1 — kinoa-init"
python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" phase-end --phase "Phase 1 — kinoa-init" --summary "ok=true, integration_type=API"
python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" qa --question "Reuse existing creds, or replace?" --answer "Reuse"
```

Sub-skills reach the helper via the sibling path `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`.

**Failure handling.** The helper always exits 0 and prints a JSON result. If `ok` is `false` (no game id yet, server unreachable, etc.), **continue the integration normally** — telemetry is supplementary and must never abort a real workflow. The most common pre-init case (`error: missing_game_id`) is expected before kinoa-init's validation completes; phase-start for Phase 1 will skip silently, then phase-end will post once `KINOA_GAME_ID` has been written.

## Architecture modes (single app vs microservices)

A client doesn't always integrate Kinoa from one codebase — with a microservice architecture each module (player fields, events, feature settings, session-open) may live in a different service. Phase 1 (`kinoa-init`) asks up front how the project is laid out and persists the answer as `KINOA_ARCHITECTURE` in `~/.kinoa/session.env` and as `architecture` in the run-state file. Every workflow reads the mode before its discovery phase and scopes itself accordingly:

| Mode | Layout | Behavior |
|---|---|---|
| `SINGLE` (default) | One application, one codebase | The classic flow — discover in the project root; state file + registry in the project root. |
| `MONOREPO` | Several services under one repo root | Run from the repo root. Each workflow first asks **which service directory** this module is integrated from (offer candidate dirs found via Glob — `services/*/`, `apps/*/`, `packages/*/`, or whatever the repo uses). Discovery and generated artifacts are scoped to that `service_root`; one shared state file + one registry live at the repo root. |
| `MULTI_REPO` | Each service is its own checkout (own CLAUDE.md) | The current repo **is** the service. On the first run in a repo, confirm the service name (default: the repo folder name) and register it in the central index. State file + registry live in each repo and cover only that repo's modules. |

**Game-wide decisions must survive repo boundaries.** `session_start_auto_fires`, `player_state_strategy`, and the feature-settings resource ids are decided once per game but consumed by workflows possibly running in other repos. In `MULTI_REPO`, mirror each of these into the central index the moment it is decided, and read the index on workflow start — never re-ask a question another service's run already answered; summarize what was found and let the developer object instead.

### Central index (`MULTI_REPO` only) — `~/.kinoa/<game_id>/services.json`

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

## Run state (resume support)

A full integration outlives a single conversation context. Every workflow therefore persists its decisions to **`.kinoa-integration-state.json`** — the durable source of truth for "where are we and what was decided", surviving context compaction and session restarts. Location by mode: `SINGLE` and `MULTI_REPO` → the project/repo root the run happens in; `MONOREPO` → the monorepo root (one file shared by all services).

Rules (apply in every sub-skill):

- **Read on start.** If the file exists and its `game_id` matches `KINOA_GAME_ID`, summarize the recorded progress to the developer and resume from the first unfinished phase instead of restarting. If `game_id` differs, ask before overwriting. In `MULTI_REPO`, also read the central index to see what other services already integrated.
- **Update on every `phase-end`.** Whenever you fire the `phase-end` webhook, also read-merge-write this file: update only your own phase's entry, never drop the others'. Update the registry (`KINOA-INTEGRATION.md`, below) and — in `MULTI_REPO` — the central index in the same breath.
- **Record decisions and created resource ids, not narration.** Statuses are `in_progress | done | skipped`.
- Suggest adding `.kinoa-integration-state.json` to the project's `.gitignore` (alongside the report HTMLs). `KINOA-INTEGRATION.md` is the opposite — it should be committed.

```json
{
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

## Integration registry — `KINOA-INTEGRATION.md` (human-readable, committed)

The state file is machine state for resuming; the registry is for people — a reviewer or a newly onboarded developer opens it and sees **what is integrated with Kinoa, how, and what changed over time**. It lives next to the state file and, unlike the state file, **should be committed to git** so the integration picture travels with the repo (and, in `MULTI_REPO`, lets another developer's machine rebuild the central index).

Maintain it in the same breath as the state file: whenever a workflow read-merge-writes its phase entry at a `phase-end`, also update the registry — **rewrite** that module's section under `## Modules` to the new current state, and **append** one entry to `## History` (never edit or delete existing History entries). `kinoa-init` creates the skeleton if the file is absent; any workflow that finds it missing bootstraps it the same way.

Template:

```markdown
# Kinoa Integration Registry

- **Game ID:** `<uuid>`
- **Architecture:** SINGLE | MONOREPO | MULTI_REPO
- **Service:** `<name>` <!-- MULTI_REPO only: the service this repo implements -->

## Modules

### Player fields — done
- **Service:** `services/player-svc` <!-- MONOREPO: service_root; omit in SINGLE -->
- **Generated:** `services/player-svc/src/kinoa/KinoaPlayerState.kt`
- **Summary:** 12 fields active (9 predefined, 3 custom)

### Events — in progress
- …

### Resources — done
- **Service:** `services/shop-svc` <!-- MONOREPO: service_root; omit in SINGLE -->
- **Generated:** `services/shop-svc/Assets/Kinoa/KinoaResources.cs`
- **Summary:** 8 resource templates ACTIVE (6 created, 2 already active); 1 left DRAFT

## History
<!-- append-only, newest last; one entry per completed phase / sync run -->

### 2026-07-06T14:32Z — player_fields (`services/player-svc`)
Activated 9 predefined fields, created 3 custom (`vip_tier`, `guild_id`, `ab_bucket`); generated KinoaPlayerState.

### 2026-07-06T15:10Z — events (`services/analytics-svc`)
Published 3 events, created 2 custom; player_state strategy: DIFF; session_start auto-fires.
```

Keep History entries terse and factual — counts, names, decisions, artifact paths. They are the change log the client asked to be able to audit later; narration belongs in the conversation, not here.

| Subcommand                          | Sub-skill folder                          | Slash command                            | Purpose |
|-------------------------------------|-------------------------------------------|------------------------------------------|---------|
| `init`                              | `../kinoa-init/`                          | `/kinoa-init`                            | Phase 1 — capture game ID + tokens (integration type defaults to API; this flow never passes `--integration-type`, so it stays API — `SDK` is reserved for the kinoa-sdk-dashboard-sync flow), validate against the Kinoa admin API. |
| `sync-player-fields-integration`    | `../kinoa-sync-player-fields-integration/`| `/kinoa-sync-player-fields-integration`  | Phase 2 (workflow) — discover the app's player class, generate `KinoaPlayerState`, diff app fields against Kinoa, drive activations / creations / verification by delegating to `kinoa-dashboard-player-fields`. |
| `dashboard-player-fields`           | `../kinoa-dashboard-player-fields/`       | `/kinoa-dashboard-player-fields`         | Helper — pure admin CLI wrapper for player-field defs (list / activate / create / delete) plus public `get-player-state`. Used by Phase 2; also invokable directly. |
| `open-session`                      | `../kinoa-open-session/`                  | `/kinoa-open-session`                    | Phase 3 — open a player session via `/player/session/start`. Implementing open-session in app runtime is also a prerequisite for Phase 4 (auto-fires `session_start`). |
| `sync-event-integration`            | `../kinoa-sync-event-integration/`        | `/kinoa-sync-event-integration`          | Phase 4 (workflow) — discover events the app emits, generate `KinoaEvents`, diff against Kinoa, drive publishes / creations / verification by delegating to `kinoa-dashboard-event`. Owns the runtime test helper (`kinoa_send_event.py`) used in Phase 4. |
| `dashboard-event`                   | `../kinoa-dashboard-event/`               | `/kinoa-dashboard-event`                 | Helper — pure admin CLI wrapper for game-event defs (list / get / publish / create / add-params / delete). Used by Phase 4; also invokable directly. |
| `sync-feature-settings-integration` | `../kinoa-sync-feature-settings-integration/` | `/kinoa-sync-feature-settings-integration` | Phase 5 (workflow) — discover a schema (reuse by id/link or infer from CSV), activate it, create a setting + a test configuration, load its data, mark-default & publish, generate a `FeatureSettingsFacade` in the app, and verify a player resolves the config at runtime (tests with mocked HTTP). Delegates admin calls to `kinoa-dashboard-feature-settings` and CSV inference to `kinoa-csv-schema-infer`. |
| `schema-from-csv`                   | `../kinoa-sync-feature-settings-integration/` | (scoped Phase 5) | **Scoped run** — execute *only* the schema-creation slice of Phase 5: infer types from a CSV (`kinoa-csv-schema-infer`), then create + publish the schema (`kinoa-dashboard-feature-settings`), and stop. No setting, configuration, facade, or test. Use when the developer wants just a published schema from a CSV, not the whole feature-settings integration. Routes to the workflow's "Scoped runs" section with the `schema-from-csv` token. |
| `dashboard-feature-settings`        | `../kinoa-dashboard-feature-settings/`    | `/kinoa-dashboard-feature-settings`      | Helper — pure admin CLI wrapper for feature-settings defs (schemas / settings / configurations: list / create / publish / import / mark-default / test-players) plus the public runtime `get-config`. Used by Phase 5; also invokable directly. |
| `sync-resource-template-integration` | `../kinoa-sync-resource-template-integration/` | `/kinoa-sync-resource-template-integration` | Phase 6 (workflow, **optional**) — discover sellable / awardable items (resources — NOT internal currency), let the developer confirm/edit them on an interactive HTML page, register the confirmed list as resource templates (create DRAFT → activate), generate a `KinoaResources` data class, and verify. Delegates admin calls to `kinoa-dashboard-resource-template`. |
| `dashboard-resource-template`       | `../kinoa-dashboard-resource-template/`   | `/kinoa-dashboard-resource-template`     | Helper — pure admin CLI wrapper for resource-template defs (list / get / create / update / activate / deprecate / clone / delete). `delete` is HARD + DRAFT-only. Used by Phase 6; also invokable directly. |
| `csv-schema-infer`                  | `../kinoa-csv-schema-infer/`              | `/kinoa-csv-schema-infer`                | Utility — pure local parser that infers a feature-schema (column types) from a CSV's headers + sample values and emits a ready-to-POST SchemaDto. Used by Phase 5; also invokable directly. No API calls. |

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
| `sync-feature-settings-integration` | Schema/setting/config → `FeatureSettingsFacade` workflow. |
| `schema-from-csv` | Scoped: infer + create + publish a schema from a CSV, then stop. |
| `dashboard-feature-settings` | Direct admin tools for feature-settings defs. |
| `sync-resource-template-integration` | Discover → confirm → register game resources (sellable / prize items) → `KinoaResources` workflow. |
| `dashboard-resource-template` | Direct admin tools for resource-template defs. |
| `csv-schema-infer` | CSV → feature-schema type inference (local utility, no API). |

If the token matches, use it. Pass remaining tokens through as `$ARGUMENTS` to the sub-skill.

**Case B: no/unknown token but the request describes a task.** Map intent → subcommand using this table before falling back to a question:

| User says (paraphrased)… | Dispatch to |
|---|---|
| "set up Kinoa", "configure credentials", "wire up Kinoa for this project", "I have a session token / game id" | `init` |
| "integrate Kinoa", "onboard this app with Kinoa", "do the full integration", "everything from scratch" | `all` |
| "sync the player model", "mirror player fields", "generate KinoaPlayerState", "what custom player fields do we need" | `sync-player-fields-integration` |
| "list / activate / create / delete a player field", "inspect player_state for a player", "what fields does player X have" | `dashboard-player-fields` |
| "open a session for player X", "start a Kinoa session", "test the open-session endpoint" | `open-session` |
| "sync events", "mirror app events", "generate KinoaEvents", "which events should we publish" | `sync-event-integration` |
| "publish event X", "create a custom event", "delete a stale event", "list our events" | `dashboard-event` |
| "integrate feature settings", "sync feature settings / remote config", "wire up a FeatureSettingsFacade", "set up a config a player can fetch", "do the whole feature-settings integration" | `sync-feature-settings-integration` |
| "create a schema from this CSV (just the schema)", "build and publish a feature schema from my CSV", "make me a feature schema out of shop_items.csv and publish it" — wants the schema created on the dashboard but NOT the rest of the integration | `schema-from-csv` |
| "create / publish a schema" (by hand), "create a setting", "create / publish a configuration", "import config data", "what config does player X resolve" | `dashboard-feature-settings` |
| "register our resources / items", "mirror the shop catalogue", "sync sellable items / prizes into Kinoa", "generate KinoaResources", "what resource templates should we create" | `sync-resource-template-integration` |
| "list / create / activate / deprecate / delete a resource template", "publish resource X", "clone a resource template" | `dashboard-resource-template` |
| "infer column types from this CSV", "turn this CSV into a schema body / SchemaDto" — wants the types/body only, no API call | `csv-schema-infer` |

**Case C: still ambiguous.** Ask via `AskUserQuestion`, in **two tiers** — `AskUserQuestion` allows at most 4 options per question, so never present the subcommands as one flat list (that silently drops the ones past the cap, hiding feature settings and resources). Tier 1 picks the area; tier 2 (when the area has more than one subcommand) picks the exact subcommand.

**Tier 1** — one question, exactly these 4 options:

1. **Full onboarding (all)** — "Run the complete sequence: init → player fields → open session → events → feature settings → resources. Best for a first-time integration of this app." → dispatch `all`.
2. **Core phase** — "Run one core step on this project: init (credentials), sync player fields, open a session, or sync events." → tier 2a.
3. **Feature settings** — "Add remote configuration to this project (works on an already-integrated project): build/activate a schema, create a setting + config, generate a FeatureSettingsFacade — or just publish a schema from a CSV." → tier 2b.
4. **Resources** — "Register the game's sellable / prize items as resource templates and generate KinoaResources (works on an already-integrated project)." → tier 2c.

**Tier 2a — core phase**, exactly these 4 options:
- "Init — set up Kinoa credentials and validate the project." → `init`
- "Sync player fields — mirror the app's player model into Kinoa and verify." → `sync-player-fields-integration`
- "Open session — start a player session (verification helper)." → `open-session`
- "Sync events — mirror the app's emitted events into Kinoa and verify." → `sync-event-integration`

**Tier 2b — feature settings**:
- "Full feature-settings integration — schema + setting + config + FeatureSettingsFacade, verified end-to-end." → `sync-feature-settings-integration`
- "Schema from CSV — just infer types from a CSV and create + publish the schema (no setting/config/facade)." → `schema-from-csv`
- "Dashboard admin — one-off ops on schemas / settings / configurations." → `dashboard-feature-settings`

**Tier 2c — resources**:
- "Full resource integration — discover sellable / prize items, confirm on an interactive page, register as resource templates, generate KinoaResources." → `sync-resource-template-integration`
- "Dashboard admin — one-off ops on resource templates (list / create / activate / deprecate / clone / delete)." → `dashboard-resource-template`

The remaining dashboard helpers (`dashboard-player-fields`, `dashboard-event`) and `csv-schema-infer` are reached via the Case B intent table or an explicit token — if the developer types free text under "Other" at any tier, map it through the Case B table before asking again.

**Adding to an existing project.** Tiers 3 (Feature settings) and 4 (Resources) are the standard way to bolt Phase 5 / Phase 6 onto a project whose core integration is already done. When `.kinoa-integration-state.json` shows `init` (and typically phases 2–4) as `done`, do NOT rerun the earlier phases — reuse the stored credentials (`~/.kinoa/session.env`) and run just the selected workflow, then merge its entry into the existing state file and registry as usual.

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
| `sync-feature-settings-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-feature-settings-integration/SKILL.md` |
| `schema-from-csv` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-feature-settings-integration/SKILL.md` — follow the **"Scoped runs"** section for the `schema-from-csv` token (infer → create-schema → publish-schema, then stop). Pass the token through in `$ARGUMENTS`. |
| `dashboard-feature-settings` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/SKILL.md` |
| `sync-resource-template-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-resource-template-integration/SKILL.md` |
| `dashboard-resource-template` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-resource-template/SKILL.md` |
| `csv-schema-infer` | `${CLAUDE_SKILL_DIR}/../kinoa-csv-schema-infer/SKILL.md` |

When all sub-skills are installed as siblings under `~/.claude/skills/` (see `HOW-TO.md`), these paths resolve correctly.

### Step 3 — `all`: run the full onboarding sequence

When the subcommand is `all`, drive the six-phase chain below (Phase 6 optional). Treat each phase as a hand-off: complete it fully, summarize what changed, and confirm with the developer before moving to the next phase. If any phase fails (auth error, validation mismatch, developer rejection), stop and surface the error — do not silently advance. Keep `.kinoa-integration-state.json` current as each phase ends (see "Run state") so an interrupted `all` run resumes where it stopped.

The chain adapts to the architecture mode (see "Architecture modes"):

- **`SINGLE`** — run all phases in the project root, exactly as written.
- **`MONOREPO`** — before each of Phases 2, 4, 5, 6, the workflow asks which service directory that module lives in; different phases may target different services. Phase 3 (open-session) is a network call, not code discovery — just record which service owns session-opening.
- **`MULTI_REPO`** — only the modules that live in the *current* repo can run here. At the start of the chain, ask the developer which modules this service implements, run those phases, and mark the rest as pending-elsewhere. In the final summary, show the cross-repo picture from the central index and tell the developer which repos to run the remaining subcommands from.

1. **Phase 1 — `kinoa-init`.** Read `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md` and follow it. If `~/.kinoa/session.env` already exists, that skill will show the current values and ask **once**: reuse everything, replace just the session token, or start from scratch — pass that choice through and never re-confirm per credential. Verify the run ends with `ok: true`. Capture `KINOA_INTEGRATION_TYPE` for later — the event sync phase branches on it.
2. **Phase 2 — `kinoa-sync-player-fields-integration`.** Drive the player-fields workflow to completion. After the workflow's internal verification step, summarize: how many fields activated / created / verified.
3. **Phase 3 — `kinoa-open-session`.** Run it once with a real player_id chosen by the developer. This both verifies the endpoint and (in API + direct-endpoint projects) seeds the auto-fired `session_start` so the next phase has data to inspect. Hand off `KINOA_LAST_PLAYER_ID` / `KINOA_LAST_SESSION_ID` (already persisted by the helper) to Phase 4.
4. **Phase 4 — `kinoa-sync-event-integration`.** Drive the event workflow. The workflow's internal `SESSION_START_AUTO_FIRES` branch will read `KINOA_INTEGRATION_TYPE` and decide whether `session_start` is auto-published (🔄) or must be wired as an explicit emission (🔁). After the workflow's internal verification step, summarize the run.
5. **Phase 5 — `kinoa-sync-feature-settings-integration`.** Drive the feature-settings workflow: discover the schema (reuse by id/link or infer from a CSV via `kinoa-csv-schema-infer`), activate it, create a setting + a test configuration, load its data, mark-default & publish, generate a `FeatureSettingsFacade` in the app, and verify the player resolves the config at runtime. Reuses `KINOA_LAST_PLAYER_ID` from Phase 3. This phase is **optional** — only run it if the app uses (or wants) remote feature configuration; skip cleanly if the developer declines. After the verification step, summarize the run.
6. **Phase 6 — `kinoa-sync-resource-template-integration`.** Drive the resource-registration workflow: discover sellable / awardable items (resources — NOT internal currency), let the developer confirm/edit the proposed list on an interactive HTML page, register the confirmed resources as resource templates (create DRAFT → activate) via `kinoa-dashboard-resource-template`, generate a `KinoaResources` data class, and verify. This phase is **optional** — only run it if the game has a shop / reward / item catalogue to mirror; skip cleanly if the developer declines. After the verification step, summarize the run.

> **Phase number convention.** Outer phases (the orchestrator's chain) are numbered **1 → 6** in the order init → player-fields → open-session → events → feature-settings → resources. The player-fields and events workflows number their *internal* phases **1 → 4** (Discover → Generate → Sync → Test), with sub-steps written as `<phase>.<step>` (e.g., `3.5`, `4.2`). The feature-settings workflow instead prefixes its inner phases with the outer number: **5.1 → 5.5** (Discover → Generate → Sync → Verify → Report, e.g., `5.4.2`); the resources workflow likewise prefixes with its outer number: **6.1 → 6.4** (Discover → Generate → Confirm+Sync → Verify, e.g., `6.3.3`). Numbers never collide in practice because outer phases always carry a sub-skill name (e.g., "Phase 1 — `kinoa-init`"), while inner phases appear inside a sub-skill's own narrative. Always refer to phases by number, never by letter.

After the chain completes, print a one-line summary per phase plus any items the developer skipped (so they can re-run individual subcommands later).

## End-to-end flow (the `all` sequence, expanded)

A first-time integration runs through these phases. Phases 1–4 are the core onboarding; Phase 5 (feature settings) and Phase 6 (resources) are optional — Phase 5 only if the app uses remote configuration, Phase 6 only if the game has a shop / reward / item catalogue to mirror. The `all` subcommand drives them automatically; the developer can also invoke each as a standalone slash command.

1. `/kinoa-init` — collect credentials (integration type defaults to `API`; this flow never passes `--integration-type`, so it stays `API`), validate against `dashboard.kinoa.io`, persist to `~/.kinoa/session.env`.
2. `/kinoa-sync-player-fields-integration` — discover the app's player class, generate `KinoaPlayerState`, drive the diff & apply (delegates each admin call to `kinoa-dashboard-player-fields`), verify.
3. `/kinoa-open-session` — verify the open-session endpoint works against this project. **Important nuance**: this helper always hits `gate.kinoa.io/playerevents/api/v3/player/session/start` directly, which always auto-fires `session_start` server-side. That tells you the *endpoint* is wired up — but it does NOT mean the app's runtime path will auto-fire. Whether the app's runtime path auto-fires depends on whether it calls this exact endpoint (API integrations may or may not; SDK integrations definitely do not).
4. `/kinoa-sync-event-integration` — discover events the app emits, generate `KinoaEvents`, decide `session_start` handling per the `SESSION_START_AUTO_FIRES` branch, drive publishes / creations (delegates each admin call to `kinoa-dashboard-event`), verify. Phase 4 includes a runtime test send via the local `kinoa_send_event.py` helper.
5. `/kinoa-sync-feature-settings-integration` *(optional)* — discover a schema (reuse by id/link or infer from a CSV via `kinoa-csv-schema-infer`), activate it, create a setting + test configuration, load its data, mark-default & publish (delegates each admin call to `kinoa-dashboard-feature-settings`), generate a `FeatureSettingsFacade` in the app, and verify a player resolves the config via the public `gate.kinoa.io/featureset` runtime endpoint (covered by tests with mocked HTTP).
6. `/kinoa-sync-resource-template-integration` *(optional)* — discover sellable / awardable items (resources), let the developer confirm/edit them on an interactive HTML page, register the confirmed list as resource templates (create DRAFT → activate, delegating each admin call to `kinoa-dashboard-resource-template`), generate a `KinoaResources` data class, and verify the templates are ACTIVE.

The dashboard helpers (`kinoa-dashboard-player-fields`, `kinoa-dashboard-event`, `kinoa-dashboard-feature-settings`, `kinoa-dashboard-resource-template`) aren't usually invoked directly during a fresh integration — they're called by the integration skills above. Use them directly when you need a one-off admin operation (e.g., "publish event X by id", "delete a stale custom field", "publish a configuration") without running the full workflow.

Each sub-skill is also independently invokable with its own slash command — the orchestrator makes the full sequence discoverable from one entry point.

## Reference

- Postman collection: `references/postman-collection.json` (the source export the user provided).
- Endpoints used:
  - Admin (player fields / events): `GET / POST https://dashboard.kinoa.io/gamemetaapi/api/...`
  - Admin (feature settings): `GET / POST https://dashboard.kinoa.io/featuresettingsapi/{schemas,settings,configurations}`
  - Admin (resource templates): `GET / POST / PUT / DELETE https://gate.kinoa.io/bundle/resource-templates` (bearer + Game-Id — skill-only, despite the `gate.kinoa.io` host)
  - Session start (new): `POST https://gate.kinoa.io/playerevents/api/v3/player/session/start`
  - Sync event: `POST https://gate.kinoa.io/playerevents/api/v3/sync-event?player_id=…`
  - Feature configurations (runtime): `POST https://gate.kinoa.io/featureset/features-configurations`

Installation and how to obtain the two tokens are documented in `HOW-TO.md`.
