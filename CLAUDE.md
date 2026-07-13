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

**`main` is the live release channel — treat it as release-only.** Because auto-updating consumers pull the latest `main` at session start, anything pushed there is live in customer sessions within minutes, with no pin or rollback. Develop on branches; merge to `main` only after `python -m unittest discover tests` passes and the change is meant to ship. Never push test/experiment commits (e.g. "autoUpdate test.") to `main`.

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

Player-fields, events, feature-settings, and resources each split along two axes — a workflow skill (`kinoa-sync-*-integration`) that drives discover → generate → sync → verify but makes no API calls, and a dashboard helper (`kinoa-dashboard-<X>`) that's a pure admin-API CLI wrapper. Workflows delegate every admin call via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-<X>/kinoa_dashboard_<X>.py`; siblings must be co-installed.

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
kinoa-sync-resource-template-integration  (Phase 6 — workflow)  ─┐ delegates (admin)
kinoa-dashboard-resource-template         (Phase 6 — admin CLI) ─┘
kinoa-api-integration                     (orchestrator — API mode)
kinoa-sdk-dashboard-sync                  (SDK mode — delegates to kinoa-dashboard-event + kinoa-dashboard-player-fields)

**Phase numbers:** Outer phases (1 → 6) name the orchestrator's chain (init / player-fields / open-session / events / feature-settings / resources; Phases 5 and 6 optional). The player-fields and events workflows number their internal phases 1 → 4 (Discover → Generate → Sync → Test), with sub-steps written `<phase>.<step>` (e.g., `3.5`, `4.2`). The feature-settings workflow instead prefixes its inner phases with the outer number: 5.1 Discover → 5.2 Generate → 5.3 Sync → 5.4 Verify → 5.5 Report (e.g., `5.4.2`); the resources workflow likewise: 6.1 Discover → 6.2 Generate → 6.3 Confirm+Sync → 6.4 Verify (e.g., `6.3.3`). Always refer to phases by number, never by letter.
```

## Typical integration flow

1. `/kinoa-init` — capture game ID + tokens, validate against Kinoa admin API.
2. `/kinoa-sync-player-fields-integration` — generate `KinoaPlayerState`, diff vs Kinoa, apply.
3. `/kinoa-open-session` — verify the runtime session-open call.
4. `/kinoa-sync-event-integration` — generate `KinoaEvents`, drive publishes/creations, run Phase 4.
5. `/kinoa-sync-feature-settings-integration` *(optional)* — build/activate a schema (reuse or infer from CSV), create a setting + test config, generate a `FeatureSettingsFacade`, verify a player resolves the config at runtime.
6. `/kinoa-sync-resource-template-integration` *(optional)* — discover sellable/prize items (resources, not currency), confirm/edit them on an interactive HTML page, register as resource templates (create DRAFT → activate), generate `KinoaResources`, verify.

Dashboard helpers aren't usually invoked directly during a fresh integration — workflows delegate. Use them directly for one-off admin tasks (e.g., "publish event X", "delete a stale custom field", "publish a configuration").

---

## Security boundary (load-bearing)

Two distinct API surfaces. **Mixing them up is a security mistake.**

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io` (`/gamemetaapi`, `/featuresettingsapi`); **also** `gate.kinoa.io/bundle/resource-templates` (bundles admin) | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both same UUID; bundles reads only `Game-Id`) | Skill only — `kinoa-init` and the `kinoa-dashboard-*` helpers. |
| **Runtime / public** | `gate.kinoa.io`, `pevents.kinoa.io`, `gate.kinoa.io/featureset`, `gate.kinoa.io/bundle/public/*` | `game: <game_secret>` (no bearer) | App runtime code (incl. the generated `FeatureSettingsFacade`, which calls `gate.kinoa.io/featureset`). [`kinoa-api-integration/references/postman-collection.json`](kinoa-api-integration/references/postman-collection.json) is the canonical spec — public hosts only. |

**`gate.kinoa.io` fronts both surfaces.** Player-events / featureset / bundle-public routes are game-secret; the bundle **admin** routes (`gate.kinoa.io/bundle/resource-templates`, used by `kinoa-dashboard-resource-template`) are bearer-secured and skill-only. What makes a call admin is the **bearer**, not the host — don't assume "gate.kinoa.io ⇒ public".

**Hard rule when generating code into the application** (`KinoaPlayerState`, `KinoaEvents`, `KinoaResources`, etc.): never emit code that calls `dashboard.kinoa.io`, carries `Authorization: Bearer`, or hits the bundle admin routes. The session token is admin-tier and must not ship in app binaries, configs, or runtime calls. Generated artifacts are **pure data classes** — no API calls embedded. The app's own emission code (or new code following the Postman collection) handles runtime calls with the game-secret header.

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

**Python helpers are self-contained** — no imports from sibling folders, no shared library. Boilerplate (`_load_session_env`, `_save_session_env`, `_request`, `_parse_json`, `_parse_kv_pairs`) is **deliberately duplicated**; don't extract a shared module. The honest invariant is *co-installed siblings, no cross-folder Python imports* — skills do reference each other at the prompt level (workflow → dashboard-helper delegation, telemetry via `../kinoa-api-integration/kinoa_webhook.py`, `references/` reads), and the whole `skills/` tree always installs together, so "installable in isolation" holds only for the Python files, not the skills. The duplication is kept safe by `tests/test_boilerplate_consistency.py` (textual identity across copies + `timeout=` on every `urlopen`) — after editing boilerplate in one helper, re-copy it everywhere. Each helper auto-loads `~/.kinoa/session.env` at import; each subcommand makes one HTTP call and prints one JSON object: `{ http_status, ok, response | request_body, …context }`. HTTP errors are caught and serialized — never raised onto stdout.

**Workflow skills follow Phase 1 → 2 → 3 → 4**: 1 discover (Glob/Grep), 2 generate empty data class, 3 sync (3.1 fetch defs, 3.2 diff, 3.3 checklist for approval, 3.4 apply, 3.5 player_state strategy [events only], 3.6 generate HTML integration report), 4 integration test in the application's codebase.

**Adding a new sub-skill**: create the folder, decide flavor (workflow / dashboard helper / utility / runtime helper / setup), update the orchestrator's dispatcher table, update [`HOW-TO.md`](kinoa-api-integration/HOW-TO.md), [`evals.json`](kinoa-api-integration/evals/evals.json), and [`README.md`](README.md) (skills table + any flow/architecture change), re-run the install loop. Runtime helpers belong **inside** the workflow skill that uses them, not as standalone slash commands (per the consolidation that folded `kinoa-send-event` into `kinoa-sync-event-integration`).

---

## Stored session state

`~/.kinoa/session.env` (mode `0600`) holds:

```
KINOA_INTEGRATION_TYPE  = API | SDK   (API = api-integration workflows; SDK = dashboard-sync for SDK games)
KINOA_ARCHITECTURE      = SINGLE | MONOREPO | MULTI_REPO   (set by kinoa-init Step 0; SINGLE default)
KINOA_GAME_ID           = <uuid>
KINOA_GAME_SECRET       = <secret>
KINOA_BEARER_TOKEN      = <jwt — admin auth>
KINOA_LAST_PLAYER_ID    = <set by kinoa-open-session>
KINOA_LAST_SESSION_ID   = <set by kinoa-open-session>
```

Session tokens expire (~24h JWT). On a 401 from any admin endpoint, ask the user to grab a fresh session token from the Kinoa dashboard → Integration menu and re-run `/kinoa-init`.

## Architecture modes (microservices)

A client may integrate each Kinoa module (player fields, events, feature settings, session-open) from a different service. `kinoa-init` asks up front how the codebase is laid out and persists `KINOA_ARCHITECTURE`: **SINGLE** (one app — classic flow), **MONOREPO** (services under one root; each workflow asks which `service_root` its module lives in and scopes discovery + generated artifacts to it; one state file + registry at the repo root), **MULTI_REPO** (each service is its own checkout = the service; state + registry per repo). In MULTI_REPO, game-wide decisions (`session_start_auto_fires`, `player_state_strategy`, feature-settings resource ids) and the per-service module map are mirrored to the machine-local central index **`~/.kinoa/<game_id>/services.json`** so a workflow in one repo sees what other services' runs already decided. Canonical semantics: [`skills/kinoa-api-integration/references/architecture-modes.md`](skills/kinoa-api-integration/references/architecture-modes.md).

## Per-project run state & integration registry

Workflows persist progress and decisions to `.kinoa-integration-state.json` (project root in SINGLE/MULTI_REPO, monorepo root in MONOREPO; suggest `.gitignore`-ing it, like the report HTMLs). Each workflow reads it on start — to resume after an interrupted or compacted session — and read-merge-writes its own phase entry whenever it fires a `phase-end` webhook. Canonical schema + merge rules live in [`skills/kinoa-api-integration/references/run-state.md`](skills/kinoa-api-integration/references/run-state.md). Conversation context is NOT the durable source of truth for decisions like `SESSION_START_AUTO_FIRES`, the player_state strategy, or created resource ids — the state file is.

Alongside the machine state lives **`KINOA-INTEGRATION.md`** — the human-readable integration registry, **committed to git** (unlike the state file): what modules are integrated, from which service, with which artifacts, plus an append-only `## History` change log (one dated entry per completed phase/sync run). Every state-file write updates the registry in the same breath. Template + rules: [`skills/kinoa-api-integration/references/integration-registry.md`](skills/kinoa-api-integration/references/integration-registry.md).

---

## Domain rules

**Highly-recommended events** — the set `{watch_ad, install, payment}` feeds Kinoa's calculated properties (ad-revenue analytics, install attribution, monetization / LTV / ARPU). The event sync skill flags these with ⭐ in the 3.3 checklist regardless of bucket. The framing is deliberate: missing them does **not** break the integration — the checklist callout and the HTML reports state that everything wired up keeps working, but the calculated properties fed by the missing events/fields won't be computed (no data), and recommend implementing them in the game if possible. Same rule for predefined player fields left `not_implemented` (player-fields report callout).

**Install-time player fields & the `install` event** — install attribution is fed either by the `install` event or by the predefined player fields `install_time` (Unix epoch **seconds**) + `install_time_ms` (same instant in **milliseconds**). `install_time_ms` is **mandatory**; `install_time` is implemented alongside it (derive one from the other, captured once at first launch and persisted). The player-fields workflow pulls both to the top of its 3.3 checklist (❗/⭐) and records the outcome in the state file (`phases.player_fields.install_time_fields`). When **both** are implemented + active, the `install` event is **optional**: the event sync drops its ⭐, notes the coverage, and counts `install` as integrated in the report's critical-events section.

**Deletion confirmation** — before ANY delete against the dashboard (player-field `delete` — soft; event `delete` — HARD, irreversible; `delete-config`), always confirm via `AskUserQuestion` with the resolved resource id + human name and the delete semantics; proceed only on an explicit Yes from this session. Canonical wording: [`skills/kinoa-api-integration/SKILL.md`](skills/kinoa-api-integration/SKILL.md) (intro) + each dashboard helper's delete doc.

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

**Resources (Phase 6) — the bundles resource-template catalogue.** A **resource** is any item that can be **sold or awarded as a prize** (gear, chests, boosters, cosmetics) — explicitly **not** internal/soft currency (that's player state). Registered as a **resource template** on the bundles service: `name`, `resourceKey` (`^[a-zA-Z][a-zA-Z0-9_-]*$`), lifecycle `status` **`DRAFT → ACTIVE → DEPRECATED`** (create defaults to DRAFT; `POST /{id}/activate` publishes; `POST /{id}/deprecate` retires — there is no un-deprecate), optional `description` and `body` map, and typed `fields` (`number, string, boolean, date, enumeration`; enumerations carry `enumeration_values`). Admin host is `gate.kinoa.io/bundle/resource-templates` (bearer + Game-Id — skill-only despite the `gate.kinoa.io` host). **`delete` is HARD and DRAFT-only** — the server returns `409 CONFLICT` for ACTIVE/DEPRECATED templates (deprecate those instead); a DRAFT delete is irreversible. The workflow **never deletes**; delete is an operator-initiated `kinoa-dashboard-resource-template` task in its own session, gated by the standard `AskUserQuestion` confirmation. The Phase 6 human-in-the-loop step is unique: instead of a terminal checklist, `generate_confirm_page.py` renders an **interactive HTML page** where the developer edits/removes/adds the proposed resources, then hands the confirmed JSON back (Download-file path or Copy-paste) — the browser can't write to disk. The generated `KinoaResources` is a **pure data class** of confirmed keys (no API calls, no bearer) — same hard rule as `KinoaEvents`/`KinoaPlayerState`.

---

## SDK dashboard sync (Phase 7 of the SDK skill)

For games integrated via the Kinoa Unity SDK, the `/kinoa` skill (shipped inside `com.kinoa.sdk.core`) writes **`kinoa-dashboard-manifest.json`** at the game project root — a versioned, machine-readable inventory of the entities the integration uses. `kinoa-sdk-dashboard-sync` consumes it: preflight (kinoa-init `--integration-type SDK`) → fetch dashboard state (incl. `--states deleted` probes) → deterministic plan (`kinoa_sdk_sync_plan.py`) → developer-approved checklist → apply via the dashboard helpers → **`kinoa-dashboard-sync-result.json`** back into the project. Load-bearing rules: never delete dashboard entities; soft-deleted records are re-published (events) / re-activated (fields), never re-created; names/paths byte-for-byte; `unsupported` and `unknown_manifest_sections` are always surfaced, never silently dropped. Events and player fields are the first synced surfaces — the manifest schema is designed to grow (feature settings, bundles, translations, …) behind `schema_version`.

**Known gap (pending an SDK-skill update — that folder is currently change-frozen):** `kinoa-sdk-dashboard-sync/SKILL.md` still instructs `cat ~/.kinoa/session.env` with manual masking in its preflight, contradicting the repo-wide rule (use `kinoa_init.py show`; never `cat` — the plaintext admin token lands in the transcript before masking can apply). When the SDK skill is next revised, align it with kinoa-init Step 1.

## Testing

**Unit tests (offline)**: `python -m unittest discover tests` from the repo root — covers the helper CLIs (`kinoa_init`, `kinoa_open_session`, `kinoa_dashboard_event`, `kinoa_dashboard_player_fields`, `kinoa_dashboard_feature_settings`, `kinoa_dashboard_resource_template`, `kinoa_csv_schema_infer`), the sync planner, and the webhook with mocked HTTP; no credentials, no network. `tests/test_boilerplate_consistency.py` is the drift guard for the duplicated helper boilerplate: it asserts `_load_session_env` / `_save_session_env` / `_request` / `_parse_json` stay textually identical across copies and every `urlopen` carries a `timeout` — when you edit boilerplate in one helper, re-copy it to all of them or this test fails. Run the suite after ANY change to a `kinoa_*.py` helper.

**Evals (skill behavior)**: [`skills/kinoa-api-integration/evals/evals.json`](skills/kinoa-api-integration/evals/evals.json) holds the eval cases. Run via the `anthropic-skills:skill-creator` harness (spawns with-skill + baseline subagents per case, generates a review HTML), or invoke any helper directly against a real Kinoa project — every CLI is independently usable. `kinoa-api-integration-workspace/` holds run artifacts; **do not commit it**.

## File index

- [`README.md`](README.md) — human-facing repo entry point (plugin overview, install, skills table, architecture, security boundary). **Keep it current** whenever skills, install steps, architecture, or the security boundary change.
- [`skills/kinoa-api-integration/SKILL.md`](skills/kinoa-api-integration/SKILL.md) — API-mode orchestrator dispatcher
- [`skills/kinoa-api-integration/references/`](skills/kinoa-api-integration/references/) — canonical cross-cutting convention docs read on demand by the orchestrator and every sub-skill: `telemetry.md`, `architecture-modes.md` (incl. the MULTI_REPO central index), `run-state.md`, `integration-registry.md`
- [`skills/kinoa-sync-resource-template-integration/SKILL.md`](skills/kinoa-sync-resource-template-integration/SKILL.md) — resource-registration workflow (discover → interactive confirm → register → verify); `generate_confirm_page.py` (interactive editor) + `generate_report.py`
- [`skills/kinoa-dashboard-resource-template/SKILL.md`](skills/kinoa-dashboard-resource-template/SKILL.md) — resource-template admin CLI (bundles service on `gate.kinoa.io/bundle`)
- [`skills/kinoa-sdk-dashboard-sync/SKILL.md`](skills/kinoa-sdk-dashboard-sync/SKILL.md) — SDK-mode dashboard sync (manifest contract, phases, hard rules)
- [`skills/kinoa-api-integration/HOW-TO.md`](skills/kinoa-api-integration/HOW-TO.md) — install, token acquisition, walkthrough
- [`skills/kinoa-api-integration/references/postman-collection.json`](skills/kinoa-api-integration/references/postman-collection.json) — runtime API spec (public hosts only)
- [`skills/kinoa-api-integration/evals/evals.json`](skills/kinoa-api-integration/evals/evals.json) — eval cases
- [`tests/`](tests/) — offline unit tests for the python helpers
- Each sub-skill's `SKILL.md` documents its specific phases / subcommands / branches
