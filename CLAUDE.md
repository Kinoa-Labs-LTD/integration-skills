# integration-skills

Claude Code sub-skills that integrate a game/application with the **Kinoa** platform — credentials, player-state model, session lifecycle, event registry, verification — driven from inside Claude Code. Two consumption modes: **API integration** (the app talks to Kinoa's public API directly; full onboarding workflows) and **SDK dashboard sync** (the game is integrated via the Kinoa Unity SDK; these skills only mirror its entities onto the Dashboard — no app code is generated or touched).

## Distribution & install

The repo doubles as a **Claude Code plugin marketplace** ([`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)) with a single plugin **`kinoa-dashboard`** exposing every skill under `skills/`. Plugin-installed skills are invoked namespaced: `/kinoa-dashboard:kinoa-api-integration`, `/kinoa-dashboard:kinoa-sdk-dashboard-sync`, etc.

```bash
claude plugin marketplace add Kinoa-Labs-LTD/integration-skills   # or /plugin marketplace add … in-session
claude plugin install kinoa-dashboard@kinoa
```

A CLI add registers the marketplace with auto-update **off** (third-party default) — turn it on via `/plugin` → **Marketplaces** → `kinoa` → **Enable auto-update**, or add `"autoUpdate": true` to the `kinoa` entry under `extraKnownMarketplaces` in `~/.claude/settings.json` (the CLI add already created that entry). With it on, every session start re-fetches the plugin to the latest `main` commit.

No `version` field is set in the plugin manifest — **every git commit is a new plugin version** (the commit SHA doubles as the integrity checksum); marketplaces registered with `autoUpdate: true` pull the latest on session start. Game projects can pre-wire the marketplace via `.claude/settings.json` → `extraKnownMarketplaces` (with `"autoUpdate": true`) + `enabledPlugins` (the `/kinoa` SDK skill's dashboard-sync phase sets this up). Private-repo access for auto-update uses `GITHUB_TOKEN`/`GH_TOKEN`.

Legacy symlink install (no plugin system) still works:

```bash
# run from the repo root of this checkout ($PWD must be absolute — symlink targets need it)
mkdir -p ~/.claude/skills
for d in "$PWD"/skills/*/; do
  ln -sfn "$d" ~/.claude/skills/"$(basename "$d")"
done
```

Restart Claude Code. Walkthrough: [`skills/kinoa-api-integration/HOW-TO.md`](skills/kinoa-api-integration/HOW-TO.md). API-mode dispatcher: [`skills/kinoa-api-integration/SKILL.md`](skills/kinoa-api-integration/SKILL.md). SDK-mode entry: [`skills/kinoa-sdk-dashboard-sync/SKILL.md`](skills/kinoa-sdk-dashboard-sync/SKILL.md).

---

## Architecture

Player-fields, events, and feature-settings each split along two axes — a workflow skill (`kinoa-sync-*-integration`) that drives discover → generate → sync → verify but makes no API calls, and a dashboard helper (`kinoa-dashboard-<X>`) that's a pure admin-API CLI wrapper. Workflows delegate every admin call via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-<X>/kinoa_dashboard_<X>.py`; siblings must be co-installed.

Plus standalone pieces:

- `kinoa-init` — credential capture + project validation (`--integration-type API|SDK`; API default).
- `kinoa-open-session` — runtime helper mirroring `POST /player/session/start` (auto-fires `session_start` server-side).
- `kinoa-csv-schema-infer` — pure-parser utility turning a CSV into a feature-schema (used by the feature-settings workflow; no API calls).
- `kinoa-api-integration` — API-mode orchestrator dispatching `/kinoa-api-integration <subcommand>` (or `all` for end-to-end).
- `kinoa-sdk-dashboard-sync` — SDK-mode workflow: consumes `kinoa-dashboard-manifest.json` (written by the `/kinoa` SDK skill in the game project), plans the diff via its pure planner `kinoa_sdk_sync_plan.py`, and mirrors events + player fields onto the Dashboard via the `kinoa-dashboard-*` helpers. Never generates app code, never deletes dashboard entities; soft-deleted records are re-published/re-activated, not re-created.

```
kinoa-init                                (Phase 1 — setup; SDK-sync preflight)
kinoa-sync-player-fields-integration      (Phase 2 — workflow)  ─┐
kinoa-dashboard-player-fields             (Phase 2 — admin CLI) ─┘ delegates
kinoa-open-session                        (Phase 3 — runtime helper)
kinoa-sync-event-integration              (Phase 4 — workflow)  ─┐
kinoa-dashboard-event                     (Phase 4 — admin CLI) ─┘ delegates
kinoa-sync-feature-settings-integration   (Phase 5 — workflow)  ─┐ delegates (admin)
kinoa-dashboard-feature-settings          (Phase 5 — admin CLI) ─┘
kinoa-csv-schema-infer                     (Phase 5 — utility, no API) ← also delegated to by Phase 5
kinoa-api-integration                     (orchestrator — API mode)
kinoa-sdk-dashboard-sync                  (SDK mode — delegates to kinoa-dashboard-event + kinoa-dashboard-player-fields)

**Phase numbers:** Outer phases (1 → 5) name the orchestrator's chain (init / player-fields / open-session / events / feature-settings; Phase 5 optional). The player-fields and events workflows number their internal phases 1 → 4 (Discover → Generate → Sync → Test), with sub-steps written `<phase>.<step>` (e.g., `3.5`, `4.2`). The feature-settings workflow instead prefixes its inner phases with the outer number: 5.1 Discover → 5.2 Generate → 5.3 Sync → 5.4 Verify → 5.5 Report (e.g., `5.4.2`). Always refer to phases by number, never by letter.
```

## Typical integration flow

1. `/kinoa-init` — capture game ID + tokens, validate against Kinoa admin API.
2. `/kinoa-sync-player-fields-integration` — generate `KinoaPlayerState`, diff vs Kinoa, apply.
3. `/kinoa-open-session` — verify the runtime session-open call.
4. `/kinoa-sync-event-integration` — generate `KinoaEvents`, drive publishes/creations, run Phase 4.
5. `/kinoa-sync-feature-settings-integration` *(optional)* — build/activate a schema (reuse or infer from CSV), create a setting + test config, generate a `FeatureSettingsFacade`, verify a player resolves the config at runtime.

Dashboard helpers aren't usually invoked directly during a fresh integration — workflows delegate. Use them directly for one-off admin tasks (e.g., "publish event X", "delete a stale custom field", "publish a configuration").

---

## Security boundary (load-bearing)

Two distinct API surfaces. **Mixing them up is a security mistake.**

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io` (`/gamemetaapi`, `/featuresettingsapi`) | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both same UUID) | Skill only — `kinoa-init` and the `kinoa-dashboard-*` helpers. |
| **Runtime / public** | `gate.kinoa.io`, `pevents.kinoa.io`, `gate.kinoa.io/featureset` | `game: <game_secret>` (no bearer) | App runtime code (incl. the generated `FeatureSettingsFacade`, which calls `gate.kinoa.io/featureset`). [`kinoa-api-integration/references/postman-collection.json`](kinoa-api-integration/references/postman-collection.json) is the canonical spec — public hosts only. |

**Hard rule when generating code into the application** (`KinoaPlayerState`, `KinoaEvents`, etc.): never emit code that calls `dashboard.kinoa.io` or carries `Authorization: Bearer`. The session token is admin-tier and must not ship in app binaries, configs, or runtime calls. Generated artifacts are **pure data classes** — no API calls embedded. The app's own emission code (or new code following the Postman collection) handles runtime calls with the game-secret header.

---

## Conventions for sub-skills

**Folder layout**: `skills/kinoa-<role>/SKILL.md` (required) plus optional `kinoa_<role>.py`. Everything under `skills/` ships in the `kinoa-dashboard` plugin; sibling references (`${CLAUDE_SKILL_DIR}/../kinoa-<other>/…`) keep working because the whole `skills/` tree is installed together.

**Frontmatter**:

```yaml
---
name: kinoa-<role>
description: <one paragraph — what it does AND when it should trigger>
argument-hint: [<expected args>]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---
```

**Python helpers are self-contained** — no imports from sibling folders, no shared library. Boilerplate (`_load_session_env`, `_request`, `_parse_json`, `_parse_kv_pairs`) is **deliberately duplicated** so any sub-skill can be installed in isolation. Don't extract a shared module. Each helper auto-loads `~/.kinoa/session.env` at import; each subcommand makes one HTTP call and prints one JSON object: `{ http_status, ok, response | request_body, …context }`. HTTP errors are caught and serialized — never raised onto stdout.

**Workflow skills follow Phase 1 → 2 → 3 → 4**: 1 discover (Glob/Grep), 2 generate empty data class, 3 sync (3.1 fetch defs, 3.2 diff, 3.3 checklist for approval, 3.4 apply, 3.5 player_state strategy [events only], 3.6 generate HTML integration report), 4 integration test in the application's codebase.

**Adding a new sub-skill**: create the folder, decide flavor (workflow / dashboard helper / utility / runtime helper / setup), update the orchestrator's dispatcher table, update [`HOW-TO.md`](kinoa-api-integration/HOW-TO.md) and [`evals.json`](kinoa-api-integration/evals/evals.json), re-run the install loop. Runtime helpers belong **inside** the workflow skill that uses them, not as standalone slash commands (per the consolidation that folded `kinoa-send-event` into `kinoa-sync-event-integration`).

---

## Stored session state

`~/.kinoa/session.env` (mode `0600`) holds:

```
KINOA_INTEGRATION_TYPE  = API | SDK   (API = api-integration workflows; SDK = dashboard-sync for SDK games)
KINOA_GAME_ID           = <uuid>
KINOA_GAME_SECRET       = <secret>
KINOA_BEARER_TOKEN      = <jwt — admin auth>
KINOA_LAST_PLAYER_ID    = <set by kinoa-open-session>
KINOA_LAST_SESSION_ID   = <set by kinoa-open-session>
```

Session tokens expire (~24h JWT). On a 401 from any admin endpoint, ask the user to grab a fresh session token from the Kinoa dashboard → Integration menu and re-run `/kinoa-init`.

## Per-project run state

Workflows persist progress and decisions to `./.kinoa-integration-state.json` in the project being integrated (suggest `.gitignore`-ing it, like the report HTMLs). Each workflow reads it on start — to resume after an interrupted or compacted session — and read-merge-writes its own phase entry whenever it fires a `phase-end` webhook. Canonical schema + merge rules live in [`kinoa-api-integration/SKILL.md`](kinoa-api-integration/SKILL.md) → "Run state". Conversation context is NOT the durable source of truth for decisions like `SESSION_START_AUTO_FIRES`, the player_state strategy, or created resource ids — the state file is.

---

## Domain rules

**Highly-recommended events** — the set `{watch_ad, install, payment}` is required for Kinoa's calculated properties (ad-revenue analytics, install attribution, monetization / LTV / ARPU). The event sync skill flags these with ⭐ in the 3.3 checklist regardless of bucket, with a callout explaining the consequence of leaving them unintegrated.

**`session_start` — auto-fire vs explicit emit** *(API-integration workflows; SDK games handle session lifecycle inside the Kinoa SDK)*. Two open-session endpoints exist; only one auto-fires:

| Endpoint | Auto-fires? | `SESSION_START_AUTO_FIRES` | Action |
|---|---|---|---|
| `.../playerevents/api/v3/player/session/start` (**recommended / default**) | Yes (hidden mode) | `True` | 🔄 publish only — no `KinoaEvents` entry, no emission site. |
| `.../playerevents/api/v3/players/session_start` (legacy — plural + underscore) | No | `False` | 🔁 implement + publish (only if app doesn't already emit) — add to `KinoaEvents`, wire emission after the legacy call. |

**Default is `True`.** Phase 1 does NOT ask the developer up front — it assumes the recommended endpoint and only overrides to `False` when grep finds the legacy URL fragment `players/session_start` in the source. Greenfield projects keep the default.

**`player_state` emission strategy** — every event must include `event.player_state`. Two strategies, picked at 3.5:

- **Full** — every event carries the entire `KinoaPlayerState`. Simpler runtime, larger payloads.
- **Diff** — only fields whose value changed since last sent. To clear a field, include it with value `null` (explicit-`null` = "remove"; omitted = unchanged). Requires a "last sent" snapshot per player.

The chosen strategy is documented as a header comment in the generated `KinoaEvents` file.

**Runtime emission contract**:

```json
{
  "event": {
    "event_data": {
      "name": "<event_name>",
      "session_id": "<session_id>",
      "<system_param_1>": "<value>",
      "custom_params": { "<custom_param_1>": "<value>" }
    },
    "player_state": { … }
  }
}
```

Predefined params (Kinoa marks `system: true`) sit at the top of `event_data`. Operator-added params (`system: false`) nest under `event_data.custom_params`. The local `kinoa_send_event.py` helper (Phase 4) exposes both via `--system-param key=value` and `--param key=value`.

**Feature-settings (Phase 5) — three nested resources.** A **schema** (typed columns; status `DRAFT → ACTIVE` via `POST /schemas/{id}/publish`) owns **versions** (numbered `"1"`, `"2"`, …; newest = largest number — used by the `latest-version` helper). A **setting** binds a runtime `key` to one `schemaId` (no version, no status). A **configuration** holds the data rows for one schema version under a setting and has its own lifecycle: **`DRAFT → IN_REVIEW` (PATCH `/status`, `submit-config`) → `SCHEDULED` (`POST /configurations/{id}/publish`) → auto-`ACTIVE`** once the start time passes. A config must carry one `tableColumn` per schema field (the `create-config` helper builds these from the schema) and must be `--default` or carry segmentation to leave DRAFT. At runtime the app fetches by **setting key + schema version number** (version is required) at `POST gate.kinoa.io/featureset/features-configurations` (response `settings[].status` ∈ `OK / KEY_NOT_FOUND / VERSION_NOT_FOUND / DEFAULT_NOT_FOUND`, plus a `checksum`); expect a brief propagation lag after publish. `getDefault` is **false** in normal client usage (a published default still resolves). The client should keep a per-(key,version) **checksum cache**: send the held `checksums` in the request, and an unchanged config returns status OK with `data: null` (same checksum echoed); a changed one returns fresh `data` + a new checksum. The client reuses its cache on data:null. The generated `FeatureSettingsFacade` implements this caching, not a fetch-every-time call. The Phase 5 default visibility path is **`create-config --default` → submit → publish** (any player with `getDefault:true` resolves it; `mark-as-default` only promotes an already-published config). The generated `FeatureSettingsFacade` is the only generated artifact that *does* make a (runtime, game-secret) API call — never a `dashboard.kinoa.io`/bearer call. Column types: `integer, number, long, boolean, string, long_string, bundle_key, date, enumeration, version, object`.

---

## SDK dashboard sync (Phase 7 of the SDK skill)

For games integrated via the Kinoa Unity SDK, the `/kinoa` skill (shipped inside `com.kinoa.sdk.core`) writes **`kinoa-dashboard-manifest.json`** at the game project root — a versioned, machine-readable inventory of the entities the integration uses. `kinoa-sdk-dashboard-sync` consumes it: preflight (kinoa-init `--integration-type SDK`) → fetch dashboard state (incl. `--states deleted` probes) → deterministic plan (`kinoa_sdk_sync_plan.py`) → developer-approved checklist → apply via the dashboard helpers → **`kinoa-dashboard-sync-result.json`** back into the project. Load-bearing rules: never delete dashboard entities; soft-deleted records are re-published (events) / re-activated (fields), never re-created; names/paths byte-for-byte; `unsupported` and `unknown_manifest_sections` are always surfaced, never silently dropped. Events and player fields are the first synced surfaces — the manifest schema is designed to grow (feature settings, bundles, translations, …) behind `schema_version`.

## Testing

**Unit tests (offline)**: `python -m unittest discover tests` from the repo root — covers the helper CLIs (`kinoa_init`, `kinoa_dashboard_event`, `kinoa_dashboard_player_fields`) and the sync planner with mocked HTTP; no credentials, no network. Run them after ANY change to a `kinoa_*.py` helper.

**Evals (skill behavior)**: [`skills/kinoa-api-integration/evals/evals.json`](skills/kinoa-api-integration/evals/evals.json) holds the eval cases. Run via the `anthropic-skills:skill-creator` harness (spawns with-skill + baseline subagents per case, generates a review HTML), or invoke any helper directly against a real Kinoa project — every CLI is independently usable. `kinoa-api-integration-workspace/` holds run artifacts; **do not commit it**.

## File index

- [`skills/kinoa-api-integration/SKILL.md`](skills/kinoa-api-integration/SKILL.md) — API-mode orchestrator dispatcher
- [`skills/kinoa-sdk-dashboard-sync/SKILL.md`](skills/kinoa-sdk-dashboard-sync/SKILL.md) — SDK-mode dashboard sync (manifest contract, phases, hard rules)
- [`skills/kinoa-api-integration/HOW-TO.md`](skills/kinoa-api-integration/HOW-TO.md) — install, token acquisition, walkthrough
- [`skills/kinoa-api-integration/references/postman-collection.json`](skills/kinoa-api-integration/references/postman-collection.json) — runtime API spec (public hosts only)
- [`skills/kinoa-api-integration/evals/evals.json`](skills/kinoa-api-integration/evals/evals.json) — eval cases
- [`tests/`](tests/) — offline unit tests for the python helpers
- Each sub-skill's `SKILL.md` documents its specific phases / subcommands / branches
