---
name: kinoa-api-integration
description: Umbrella orchestrator for integrating an application with the Kinoa Player Events API end-to-end from Claude Code. Dispatches to one of eleven sub-skills — credential setup (init), player-state sync (sync-player-fields-integration), session debug helper (open-session), event sync (sync-event-integration), feature-settings sync (sync-feature-settings-integration), resource-template registration (sync-resource-template-integration), a CSV→schema utility (csv-schema-infer), and the four dashboard admin wrappers (dashboard-player-fields, dashboard-event, dashboard-feature-settings, dashboard-resource-template). Also accepts `all` to run the full onboarding sequence (init → player fields → open-session → events → feature settings → resources). Use whenever the user wants to integrate with Kinoa, set up the Kinoa API, onboard application code with Kinoa, run the full onboarding flow, sync the player model / events / feature settings with the Kinoa dashboard, register game resources / sellable items / prize items, build a feature schema from a CSV, open a player session, publish or create event/field/config/resource definitions, or perform any Kinoa admin task — even when they don't name a specific subcommand. Do NOT use for unrelated player-tracking or analytics platforms (Mixpanel, Amplitude, GameAnalytics, etc.) — this is Kinoa-specific.
argument-hint: [all | init | sync-player-fields-integration | dashboard-player-fields | open-session | sync-event-integration | dashboard-event | sync-feature-settings-integration | schema-from-csv | dashboard-feature-settings | sync-resource-template-integration | dashboard-resource-template | csv-schema-infer] [extra args]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This is the **orchestrator** for the Kinoa API integration. It dispatches to one of eleven sub-skills based on the first token in `$ARGUMENTS`. The sub-skills come in three flavors:

- **Workflow skills** drive multi-step processes (init, sync-*-integration, open-session).
- **Dashboard skills** are pure admin-API wrappers; the integration skills delegate to them. They're also independently invokable for direct admin tasks.
- **Utilities** are pure local helpers with no API calls (csv-schema-infer turns a CSV into a feature-schema); workflow skills delegate to them.

**Deletion confirmation — applies everywhere.** Before ANY delete against the dashboard (`delete` on player fields or events, `delete-config` on feature settings, `delete` on resource templates), confirm via `AskUserQuestion` — name the exact resource (id **and** human name), state whether the delete is soft (player fields) or **hard and irreversible** (events; resource templates — additionally DRAFT-only), and proceed only on an explicit Yes given in this session. This holds even when the request already said "delete X": the confirmation is about the *resolved id* — "delete the stale field" resolving to the wrong record is exactly the mistake this catches. No batch confirmations for heterogeneous resources; list each id being deleted.

## Cross-cutting conventions (canonical docs in `references/`)

Four conventions apply across the orchestrator and every sub-skill. Their canonical, full definitions live in this skill's `references/` folder — **read the relevant file before acting on the convention**, don't improvise from the summaries below:

- **`references/telemetry.md`** — webhook progress telemetry to Kinoa's Client Support Tool via `${CLAUDE_SKILL_DIR}/kinoa_webhook.py` (siblings: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`). In short: `phase-start` at the start and `phase-end --summary` at the end of every phase, `qa` after every `AskUserQuestion`; the helper always exits 0 — on `ok: false` continue the workflow normally, telemetry never aborts a run. Example: `python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" phase-start --phase "Phase 1 — kinoa-init"`.
- **`references/architecture-modes.md`** — `SINGLE | MONOREPO | MULTI_REPO` layout semantics (`KINOA_ARCHITECTURE` in `~/.kinoa/session.env`), service scoping per workflow, and the `MULTI_REPO` central index `~/.kinoa/<game_id>/services.json` (schema + read-merge-write rules for game-wide decisions crossing repo boundaries).
- **`references/run-state.md`** — `.kinoa-integration-state.json` schema + merge rules: read on start to resume, read-merge-write your own phase entry on every `phase-end`, record decisions and created resource ids. The state file — not conversation context — is the durable source of truth.
- **`references/integration-registry.md`** — `KINOA-INTEGRATION.md` (human-readable, committed to git): template, module sections rewritten in place, append-only `## History`. Updated in the same breath as every state-file write.

## Subcommands

One table — token, where its instructions live, what it does. Each sub-skill is also independently invokable via its own slash command (same name as the folder). All paths resolve when the skills are installed as siblings (see `HOW-TO.md`).

| Token | Read & follow | Purpose |
|---|---|---|
| `all` | Step 3 below | Run the full onboarding sequence: init → player fields → open-session → events → feature settings → resources. |
| `init` | `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md` | Phase 1 — capture game ID + tokens, validate against the Kinoa admin API. Integration type defaults to API; this flow never passes `--integration-type`, so it stays API — `SDK` is reserved for the kinoa-sdk-dashboard-sync flow. |
| `sync-player-fields-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-player-fields-integration/SKILL.md` | Phase 2 (workflow) — discover the app's player class, generate `KinoaPlayerState`, diff app fields against Kinoa, drive activations / creations / verification by delegating to `kinoa-dashboard-player-fields`. |
| `dashboard-player-fields` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/SKILL.md` | Helper — pure admin CLI for player-field defs (list / activate / create / delete) plus public `get-player-state`. |
| `open-session` | `${CLAUDE_SKILL_DIR}/../kinoa-open-session/SKILL.md` | Phase 3 — open a player session via `/player/session/start`. Implementing open-session in app runtime is also a prerequisite for Phase 4 (auto-fires `session_start`). |
| `sync-event-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-event-integration/SKILL.md` | Phase 4 (workflow) — discover events the app emits, generate `KinoaEvents`, diff against Kinoa, drive publishes / creations / verification by delegating to `kinoa-dashboard-event`. Owns the runtime test helper (`kinoa_send_event.py`) used in Phase 4. |
| `dashboard-event` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/SKILL.md` | Helper — pure admin CLI for game-event defs (list / get / publish / create / add-params / delete). |
| `sync-feature-settings-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-feature-settings-integration/SKILL.md` | Phase 5 (workflow, optional) — discover a schema (reuse by id/link or infer from CSV), activate it, create a setting + test configuration, load its data, mark-default & publish, generate a `FeatureSettingsFacade`, verify a player resolves the config at runtime. Delegates admin calls to `kinoa-dashboard-feature-settings` and CSV inference to `kinoa-csv-schema-infer`. |
| `schema-from-csv` | same file — follow its **"Scoped runs"** section for the `schema-from-csv` token; pass the token through in `$ARGUMENTS` | **Scoped run** — only the schema-creation slice of Phase 5: infer types from a CSV, create + publish the schema, stop. No setting, configuration, facade, or test. |
| `dashboard-feature-settings` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/SKILL.md` | Helper — pure admin CLI for feature-settings defs (schemas / settings / configurations: list / create / publish / import / mark-default / test-players) plus the public runtime `get-config`. |
| `sync-resource-template-integration` | `${CLAUDE_SKILL_DIR}/../kinoa-sync-resource-template-integration/SKILL.md` | Phase 6 (workflow, optional) — discover sellable / awardable items (resources — NOT internal currency), let the developer confirm/edit them on an interactive HTML page, register the confirmed list as resource templates (create DRAFT → activate), generate `KinoaResources`, verify. Delegates admin calls to `kinoa-dashboard-resource-template`. |
| `dashboard-resource-template` | `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-resource-template/SKILL.md` | Helper — pure admin CLI for resource-template defs (list / get / create / update / activate / deprecate / clone / delete). `delete` is HARD + DRAFT-only. |
| `csv-schema-infer` | `${CLAUDE_SKILL_DIR}/../kinoa-csv-schema-infer/SKILL.md` | Utility — pure local parser inferring a feature-schema (column types) from a CSV's headers + sample values; emits a ready-to-POST SchemaDto. No API calls. |

The real invariant is **co-installed siblings, no cross-folder Python imports**: every sub-skill's helper script is a single self-contained file (boilerplate deliberately duplicated, guarded by `tests/test_boilerplate_consistency.py`), but the skills *do* reference each other at the prompt level — workflows delegate admin calls to the `kinoa-dashboard-*` helpers, fire telemetry via this skill's `kinoa_webhook.py`, and read this skill's `references/`. The whole `skills/` tree installs together (plugin or symlink loop), so those sibling paths always resolve. This skill (`kinoa-api-integration`) holds only the orchestration prompt, the convention references, the Postman reference, and the install guide.

The dashboard helpers aren't usually invoked directly during a fresh integration — the workflow skills delegate to them. Use them directly for a one-off admin operation (e.g., "publish event X by id", "delete a stale custom field", "publish a configuration") without running the full workflow.

## How to dispatch

The user may invoke this skill with an explicit subcommand token, or they may describe what they want in plain English. Handle both.

### Step 1 — Resolve a subcommand

**Case A: explicit token in `$ARGUMENTS`.** First token matches a row in the Subcommands table above → use it. Pass remaining tokens through as `$ARGUMENTS` to the sub-skill.

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

Read the path from the Subcommands table with the `Read` tool, then execute its steps. Pass through any remaining `$ARGUMENTS` tokens.

### Step 3 — `all`: run the full onboarding sequence

**Before starting the chain, read `references/run-state.md` and `references/architecture-modes.md`** — the chain's resume behavior and its per-mode adaptation depend on them.

Drive the six-phase chain below (Phases 5–6 optional). Treat each phase as a hand-off: complete it fully, summarize what changed, and confirm with the developer before moving to the next phase. If any phase fails (auth error, validation mismatch, developer rejection), stop and surface the error — do not silently advance. Keep `.kinoa-integration-state.json` current as each phase ends so an interrupted `all` run resumes where it stopped.

The chain adapts to the architecture mode:

- **`SINGLE`** — run all phases in the project root, exactly as written.
- **`MONOREPO`** — before each of Phases 2, 4, 5, 6, the workflow asks which service directory that module lives in; different phases may target different services. Phase 3 (open-session) is a network call, not code discovery — just record which service owns session-opening.
- **`MULTI_REPO`** — only the modules that live in the *current* repo can run here. At the start of the chain, ask the developer which modules this service implements, run those phases, and mark the rest as pending-elsewhere. In the final summary, show the cross-repo picture from the central index and tell the developer which repos to run the remaining subcommands from.

1. **Phase 1 — `kinoa-init`.** Read `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md` and follow it. If `~/.kinoa/session.env` already exists, that skill will show the current values and ask **once**: reuse everything, replace just the session token, or start from scratch — pass that choice through and never re-confirm per credential. Verify the run ends with `ok: true`. Capture `KINOA_INTEGRATION_TYPE` for later — the event sync phase branches on it.
2. **Phase 2 — `kinoa-sync-player-fields-integration`.** Drive the player-fields workflow to completion. After the workflow's internal verification step, summarize: how many fields activated / created / verified.
3. **Phase 3 — `kinoa-open-session`.** Run it once with a real player_id chosen by the developer. This both verifies the endpoint and (in API + direct-endpoint projects) seeds the auto-fired `session_start` so the next phase has data to inspect. Hand off `KINOA_LAST_PLAYER_ID` / `KINOA_LAST_SESSION_ID` (already persisted by the helper) to Phase 4. **Important nuance**: this helper always hits `gate.kinoa.io/playerevents/api/v3/player/session/start` directly, which always auto-fires `session_start` server-side. That tells you the *endpoint* is wired up — but it does NOT mean the app's runtime path will auto-fire. Whether the app's runtime path auto-fires depends on whether it calls this exact endpoint (API integrations may or may not; SDK integrations definitely do not).
4. **Phase 4 — `kinoa-sync-event-integration`.** Drive the event workflow. The workflow's internal `SESSION_START_AUTO_FIRES` branch will read `KINOA_INTEGRATION_TYPE` and decide whether `session_start` is auto-published (🔄) or must be wired as an explicit emission (🔁). Phase 4 includes a runtime test send via the workflow's local `kinoa_send_event.py` helper. After the workflow's internal verification step, summarize the run.
5. **Phase 5 — `kinoa-sync-feature-settings-integration`.** This phase is **optional**, so open it with an `AskUserQuestion` that carries an explicit skip option:
   > "Phase 5 — feature settings (remote configuration). Run it?"
   > - **Run feature settings** — the app uses (or wants) remotely configured features.
   > - **Skip** — no remote configuration needed; mark the phase `skipped` and move on.

   Ask about Phase 5 **alone** — do NOT bundle Phase 6 into the same question or mention it as a choice yet; Phase 6 is offered only after Phase 5 is resolved. On Run: drive the feature-settings workflow — discover the schema (reuse by id/link or infer from a CSV via `kinoa-csv-schema-infer`), activate it, create a setting + a test configuration, load its data, mark-default & publish, generate a `FeatureSettingsFacade` in the app, and verify the player resolves the config at runtime (reuses `KINOA_LAST_PLAYER_ID` from Phase 3); after the verification step, summarize the run. On Skip: record `phases.feature_settings.status = "skipped"` in the state file and proceed.
6. **Phase 6 — `kinoa-sync-resource-template-integration`.** **Gate: offer this phase only once Phase 5 is `done` or `skipped`** (this run or per the state file) — never propose or start it while Phase 5 is unresolved or `in_progress`. It is likewise **optional** — open with the same ask-with-skip shape:
   > "Phase 6 — resources (sellable / prize items catalogue). Run it?"
   > - **Run resources** — the game has a shop / reward / item catalogue to mirror.
   > - **Skip** — nothing to register; mark the phase `skipped` and finish the chain.

   On Run: drive the resource-registration workflow — discover sellable / awardable items (resources — NOT internal currency), let the developer confirm/edit the proposed list on an interactive HTML page, register the confirmed resources as resource templates (create DRAFT → activate) via `kinoa-dashboard-resource-template`, generate a `KinoaResources` data class, and verify; after the verification step, summarize the run. On Skip: record `phases.resource_templates.status = "skipped"` and finish.

> **Phase number convention.** Outer phases (the orchestrator's chain) are numbered **1 → 6** in the order init → player-fields → open-session → events → feature-settings → resources. The player-fields and events workflows number their *internal* phases **1 → 4** (Discover → Generate → Sync → Test), with sub-steps written as `<phase>.<step>` (e.g., `3.5`, `4.2`). The feature-settings workflow instead prefixes its inner phases with the outer number: **5.1 → 5.5** (Discover → Generate → Sync → Verify → Report, e.g., `5.4.2`); the resources workflow likewise prefixes with its outer number: **6.1 → 6.4** (Discover → Generate → Confirm+Sync → Verify, e.g., `6.3.3`). Numbers never collide in practice because outer phases always carry a sub-skill name (e.g., "Phase 1 — `kinoa-init`"), while inner phases appear inside a sub-skill's own narrative. Always refer to phases by number, never by letter.

After the chain completes, print a one-line summary per phase plus any items the developer skipped (so they can re-run individual subcommands later).

## Reference

- Convention docs: `references/telemetry.md`, `references/architecture-modes.md`, `references/run-state.md`, `references/integration-registry.md` (see "Cross-cutting conventions" above).
- Postman collection: `references/postman-collection.json` (the source export the user provided). Known discrepancy: the export's feature-configurations request uses the `featureset.kinoa.io` host, while every helper and generated facade in this repo uses `gate.kinoa.io/featureset` (verified working) — when generating runtime code, use `gate.kinoa.io/featureset`.
- Endpoints used:
  - Admin (player fields / events): `GET / POST https://dashboard.kinoa.io/gamemetaapi/api/...`
  - Admin (feature settings): `GET / POST https://dashboard.kinoa.io/featuresettingsapi/{schemas,settings,configurations}`
  - Admin (resource templates): `GET / POST / PUT / DELETE https://gate.kinoa.io/bundle/resource-templates` (bearer + Game-Id — skill-only, despite the `gate.kinoa.io` host)
  - Session start (new): `POST https://gate.kinoa.io/playerevents/api/v3/player/session/start`
  - Sync event: `POST https://gate.kinoa.io/playerevents/api/v3/sync-event?player_id=…`
  - Feature configurations (runtime): `POST https://gate.kinoa.io/featureset/features-configurations`

Installation and how to obtain the two tokens are documented in `HOW-TO.md`.
