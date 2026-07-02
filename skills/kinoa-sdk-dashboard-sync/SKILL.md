---
name: kinoa-sdk-dashboard-sync
description: Use when a game integrated via the Kinoa Unity SDK needs its game events, player fields, and feature settings mirrored onto the Kinoa Dashboard — a kinoa-dashboard-manifest.json is present in the project (produced by the /kinoa SDK skill, Phase 7 hand-off), or the developer asks to "sync events/fields/feature-settings to the dashboard", "register the SDK integration on Kinoa Dashboard", "run the dashboard sync", or to re-import/re-seed a feature-settings default configuration's data ("reseed <setting-key>" — the scoped reseed run). NOT for API-integrated games (use kinoa-api-integration) and NOT for generating any game code — this skill only creates/publishes/activates Dashboard entities via the kinoa-dashboard-event, kinoa-dashboard-player-fields, and kinoa-dashboard-feature-settings helpers.
argument-hint: [path/to/kinoa-dashboard-manifest.json | reseed <setting-key> [--csv PATH]]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob AskUserQuestion
---

# Kinoa SDK Dashboard Sync

Mirrors an SDK-integrated game's locally-defined Kinoa entities (game events, player fields, feature settings) onto the Kinoa Dashboard. Input is the **manifest** the `/kinoa` SDK integration skill writes at the project root; output is dashboard state + a machine-readable **sync result** the SDK skill (or the developer) can audit.

This is the SDK-mode counterpart of the `kinoa-sync-*-integration` workflows. It does **no discovery in game code** (the manifest already carries the inventory) and **never generates or edits application code**.

## Scoped run — `reseed <setting-key>` (re-import a default config's data)

Trigger: `reseed <setting-key>` in `$ARGUMENTS`, or a natural-language ask ("re-import / re-seed the seed for `<key>`", "reload the default config data from my CSV"). Runs ONLY the data re-import for one setting's **default** configuration — no manifest regeneration, no planner, no other surfaces. Typical uses: recovery after a `422 invalid bundle key` seed failure (once the Bundles are fixed/created), or refreshing the default config after the developer updated their data CSV.

1. **Order: read the manifest's `game_id` (or confirm it with the developer via `AskUserQuestion` when no `kinoa-dashboard-manifest.json` is present) → fire `phase-start --phase "Phase 7 — dashboard sync (plugin, reseed)"` — the FIRST action after that id is known (hard rule 9) → THEN the session preflight** as in Phase 1 steps 3-4 (session.env / kinoa-init / cross-game guard). The expected game id for `--expect-game` = that same manifest/confirmed id.
2. **Resolve the target** (read-only): `list-settings` → match the key **byte-for-byte** (a case-variant match → stop and surface it, same rule as the planner); missing → stop: *"no such setting — run the full `/kinoa dashboard-sync` first."* Then `list-configs --setting-id <id>` → pick the `isDefault: true` configuration; none → stop: *"the setting has no default configuration — run the full sync (its conditional ensure-step creates one)."*
3. **Locate the seed CSV**: an explicit `--csv PATH` wins; else `kinoa-sdk-dashboard-sync-workspace/<schema name>.csv` (schema name via `get-schema --schema-id <setting.schemaId>`); still missing → ask the developer for the path. Resolve to an absolute path (the helper resolves `--csv` against the process cwd).
4. **Read the CSV once: count its data rows (the gate's N) and run the bundle-key precheck** — always open the file (N is needed regardless of column types); if the schema has `bundle_key` columns, validate the CSV's values for those columns against the key format (starts with a letter; only letters, digits, `_`, `-`) — malformed → stop and list the offending values (data fix needed); well-formed → carry a residual-risk note **into the gate text of step 5** ("values are well-formed, but the import still 422s if any isn't a registered Bundle"), so consent covers it.
5. **Consent gate** (`AskUserQuestion`, then a `qa` post): *"Import will OVERWRITE the current table data of configuration `<name>` (`<id>`) with N rows from `<csv>`. The current rows — including any operator edits — are replaced. Proceed?"* — **Proceed** / **Abort**. This gate is mandatory: seeded data becomes operator-owned after the first import, so a re-import is a deliberate overwrite.
6. **Import**: `import-config-data --config-id <id> --csv <abs path> --expect-game <game_id>`. On 422 → the invalid-bundle-key failure row (diagnose format first, then existence); on success → confirm via `get-configuration` and report one line (config, row count, status).
7. `phase-end` with `--summary "reseed <key> rows=N status=<ok|failed>"`. **Do NOT write `kinoa-dashboard-sync-result.json`, do NOT regenerate the manifest, do NOT append a log round** — those describe full syncs; the chat summary + telemetry is this run's record. The workspace is read-only here (seed files always survive, per §Cleanup policy).

## Hard rules (non-negotiable)

1. **Never delete anything on the Dashboard.** No `delete` subcommand invocations, ever — not for "cleanup", not for "stale" entries, not on request mid-run **regardless of who asks** (developer, PM, senior engineer, operator). Point them to the dashboard UI for deletions; that's an operator decision outside this skill — and "I'll just call the helper directly, it's not *the sync* deleting" is the same violation re-hatted. Event deletion is HARD on the live dashboard (irreversible); all the more reason it never rides along in someone else's approved change set. The same holds for feature settings — the sync creates/publishes schemas, settings, and a default configuration, but **never** deletes a schema, setting, or configuration (no `delete-config`, no schema removal).
2. **Soft-deleted records are re-activated, never re-created.** A manifest **field** whose path matches a `deleted` dashboard record → `activate` that record's id; calling `create` for such a path is a violation — it collides with or duplicates the existing record. Predefined events parked as `NOT_IMPLEMENTED` → `publish`, never `create`. **Custom events have no soft-delete on the live dashboard** (verified live 2026-06-12: DELETE is hard — the record 404s and the server's `EventModelStatus` enum has no deleted value), so a manifest custom event absent from the dashboard is `create`d — that is the correct and only recovery, not a rule violation. Should the dashboard ever grow event soft-delete, the planner already handles it (`publish` + `was_deleted`).
3. **No state-changing call before the developer approves the checklist** (Phase 3 gate). `list-*` and `get` calls are free; `publish` / `create` / `add-params` / `activate` are not.
4. **Names and paths are byte-for-byte. The manifest is a measurement of code, not a style guide — ugly-but-accurate beats pretty-but-wrong.** Never recase, trim, snake_case, or "normalize" a name from the manifest. The manifest producer already serialized field paths (SnakeCaseLower happened on the game side); consume them verbatim. Hand-editing a name in the manifest is the same violation one step earlier — and is silently reverted at the next regeneration; the ONLY sanctioned manifest correction is the predefined-name registry fix (correction loop below), which moves a name **toward** runtime truth, never away from it. Why it's absolute: the dashboard matches incoming events by exact, case-sensitive name — a registered name that differs by even one character of case never matches the live stream; the pretty event sits at zero forever while real data flows to the name the binary emits. Registering BOTH names is equally forbidden: the duplicate never fires, misleads trigger authors, and can never be auto-removed (rule 1). Renames ship code-first: rename the constant → regenerate the manifest → re-sync.
5. **`unsupported` items are surfaced, never silently dropped.** Every entry in the plan's `unsupported` bucket appears in the checklist, the closing summary, and the sync result — each with its own `reason`, verbatim. Distinguish the two kinds, don't promise a registration path that doesn't exist: an unsupported **event param** (e.g. a runtime-keyed param) CAN be registered manually on the dashboard once the keys are known; an unsupported **player field** (array / `List` / dictionary / `Guid` / `TimeSpan`) has **no Dashboard field kind** — it still ships in player state (`GetPlayerState`) but is NOT registrable, so it can't be used in triggers or audience segments.
6. **Never flip the game's integration type to `API`.** Preflight runs kinoa-init in SDK mode only. If the dashboard says the game is `API`, the only offer is to set it to `SDK` (with developer consent) — see kinoa-init Step 3 SDK branch. **Consent provenance:** the Yes must come from the developer, in this session, through that gate. Out-of-band authority never substitutes — not a teammate's or senior's "known glitch, just fix it", not a prior run's answer; relay such claims inside the gate and still wait. Running `--fix-integration-type` before the developer answers Yes is a violation regardless of who suggested it (and always pass `--integration-type SDK` with it — the bare flag targets API by legacy default).
7. **Admin credentials never leave the skill.** All calls go through the sibling helpers; never embed `dashboard.kinoa.io`, the bearer token, or `Authorization` headers in anything written into the game project.
8. **The plan comes from the planner script, not from eyeballing.** Always compute the diff via `kinoa_sdk_sync_plan.py`. Hand-diffing the listings in chat — even for "just one event" — bypasses the tested deleted/param-drift/unsupported logic. The Phase-2 listings and probes are **correctness inputs, not optional optimizations**: the manifest tells you what the game has; only the dashboard tells you what already exists, in what state, under what id. If anyone — including a manager under deadline — asks to skip them or "just create straight from the manifest", refuse: the fetches are read-only GETs, a blind create is a live-dashboard cleanup. There is no probe-less or planner-less mode.
9. **Telemetry posts fire LIVE at their trigger — never post-factum.** `phase-start` is the FIRST action of Phase 1; the checklist gate's `qa` post fires immediately after the developer answers, before any apply call; `phase-end` fires the moment the run concludes. A tail burst of catch-up posts at the end is a violation even when every post is present — the timeline's value is its chronology, and an aborted session must still leave the partial history it earned. Posts cost ~2 seconds each; that latency is the accepted price of a live timeline — never optimize it away by batching, deferring, or skipping. "Best-effort" refers to delivery failures (the helper exits 0 — log and continue), never to timing. A genuinely missed post: send it the moment the omission is noticed, then resume live discipline.
10. **`~/.kinoa/session.env` has exactly one producer: `kinoa_init.py`.** Never hand-author it or seed it from a token found in chat scrollback, logs, memory, or another project — kinoa-init exists to validate the credential against the dashboard BEFORE any state-changing call, and recovery needs all three values (game id + game secret + a freshly issued session token) validated together; a bare bearer cannot establish a session. Deadlines and live demos never license skipping init: a sync under an unvalidated or wrong-identity token can 401 mid-run, register entities under the wrong game, or half-apply — strictly worse than a delayed sync.

## Inputs

- **Manifest** — first argument, else `./kinoa-dashboard-manifest.json` in the working directory, else `Glob` for `**/kinoa-dashboard-manifest.json` and ask the developer to pick. Never proceed without one; if absent, tell the developer to run `/kinoa --merge` (or `/kinoa dashboard-sync`) in their game project first — do NOT reconstruct an inventory from game code or from `kinoa-integration-log.md`; that's the producer's job.
- **Session** — `~/.kinoa/session.env` via the helpers. If missing or the bearer is rejected (401), route through `kinoa-init` with `--integration-type SDK` (see `${CLAUDE_SKILL_DIR}/../kinoa-init/SKILL.md`). Prefill `--game-id` from the manifest's `game_id` when present so the developer only supplies the session token. **Cross-game guard:** when the manifest carries a `game_id`, it MUST equal `KINOA_GAME_ID` in session.env — a session left over from another game would fetch and APPLY against that other game's dashboard while the plan is computed from this game's manifest. On mismatch, treat the session as missing: route to kinoa-init for the manifest's game; never run a single helper call under another game's id.

### Manifest contract (`schema_version: 2`)

```json
{
  "schema_version": 2,
  "generated_at": "2026-06-11T12:00:00Z",
  "producer": "kinoa-skill",
  "integration_type": "SDK",
  "game_id": "<uuid from KinoaSdkInitService, or null>",
  "sdk_version": "com.kinoa.sdk.core@X.Y.Z",
  "head_sha": "<7-char git sha at generation>",
  "round": 4,
  "events": {
    "predefined_in_use": [
      {"name": "session_start", "transport": "sync",
       "custom_params": [{"name": "verbatim_key", "kind": "number", "extra": null}],
       "source": "Assets/Scripts/Kinoa/Services/KinoaSyncGameEventsService.cs"}
    ],
    "custom": [
      {"name": "verbatim_event_name", "constant": "EventName_X", "send_to_analytics": true,
       "params": [{"name": "verbatim_key", "kind": "string", "extra": null,
                    "csharp_type": "string", "source_ref": "Scripts/Shop.cs:118"}]}
    ],
    "declined": [{"name": "...", "reason": "skipped at coverage gate Round 3"}]
  },
  "player_fields": {
    "predefined_in_use": [{"path": "level", "source": "..."}],
    "custom": [
      {"property": "CustomString", "name": "CustomString", "path": "custom_string",
       "kind": "string", "extra": null, "default_value": null,
       "csharp_type": "string", "source": "Assets/Scripts/Kinoa/Data/CustomPlayerState.cs"}
    ]
  },
  "feature_settings": {
    "schemas": [
      {"name": "WheelOfFortune",
       "fields": [{"name": "prize", "kind": "string", "is_required": true, "source_ref": "..."},
                  {"name": "coins", "kind": "integer", "is_required": true, "source_ref": "..."}],
       "source": "Assets/Scripts/Kinoa/Data/WheelOfFortuneSettings.cs"}
    ],
    "settings": [
      {"key": "WheelOfFortune", "schema_name": "WheelOfFortune", "version": 1,
       "seed_csv": "kinoa-sdk-dashboard-sync-workspace/WheelOfFortune.csv",
       "source": "Assets/Scripts/Kinoa/Controllers/KinoaGameController.cs:139"}
    ]
  },
  "unsupported_by_cli": [
    {"surface": "event_param", "name": "purchase_date", "kind": "<unsupported kind>",
     "reason": "register manually on the dashboard"}
  ]
}
```

Vocabularies (must match the helper CLIs): event param `kind` ∈ `{number, boolean, string, date, enumeration, string_array, number_array}`; player field `kind` ∈ `{number, boolean, string, date, long_string, enumeration, version}`; **feature-settings column `kind` ∈ `{integer, number, string, boolean, bundle_key}`** — the operator's 5 (UI labels Integer/Decimal/String/Boolean/BundleKey); the producer folds everything down to these (`object`/nested/arrays → `string`), so the FS section carries no `unsupported_by_cli` entries. `path` is the already-serialized dashboard field path. `feature_settings.settings[].version` is the numeric schema version the client requests; one schema (`schemas[].name`) may back several settings. `settings[].seed_csv` (optional) points at a gitignored project CSV the producer copied (the developer's data) — the consumer seeds the **default** config from it; absent/missing → empty config, never a sync failure. `declined` entries are informational — never synced.

**The manifest grows behind `schema_version`.** Events and player fields shipped at v1; **feature settings at v2**; future surfaces (`bundles`, `translations`, …) bump it further. The planner reports any section it doesn't recognize in `unknown_manifest_sections` — when non-empty, surface it in the checklist and closing summary as *"this plugin version can't sync `<section>` yet — run `/plugin marketplace update kinoa` and retry, or handle it on the dashboard manually"*. Never silently half-sync a newer manifest.

Reject the manifest (and explain why) when: `schema_version` is unknown, `integration_type` is not `"SDK"` (API-integrated projects belong to `kinoa-api-integration`), or the JSON doesn't parse. The planner enforces the first two as well (exit 2).

## Workspace

All intermediate files go to `kinoa-sdk-dashboard-sync-workspace/` **in the game project root — the directory containing the manifest**; create if absent. Never resolve "working directory" to wherever the session happens to be rooted. **File operations (create the workspace, delete the stale result, delete the workspace at cleanup) go through python one-liners** — e.g. `python -c "import os; os.makedirs('kinoa-sdk-dashboard-sync-workspace', exist_ok=True)"`, `python -c "import shutil; shutil.rmtree('kinoa-sdk-dashboard-sync-workspace')"` — the skill's `allowed-tools` deliberately exclude shell `rm`/`mkdir`. **Ensure the project `.gitignore` covers `kinoa-sdk-dashboard-sync-workspace/` and `kinoa-dashboard-sync-result.json`** — append missing lines, create the file if absent, idempotent (the `/kinoa` producer usually already added them together with the manifest line; standalone plugin invocations ensure their own two lines).

**Cleanup policy:** on `status: completed` **with an empty `failed[]` bucket**, delete the workspace contents — **EXCEPT producer-placed seed files (`<schema>.csv`), which ALWAYS survive cleanup** (delete only the consumer's own artifacts: listings, plan, receipts, `*-verify.json`; keep the directory when seeds remain). The seeds are the recovery material for a still-empty default config (a prior run's failed import, or a future conditional re-seed) — deleting them breaks a recovery path a previous summary may have promised; the producer owns their lifecycle and refreshes them on each FS merge round. Any failed action — e.g. a rejected seed import — keeps the WHOLE workspace as diagnostics, exactly like `partial` runs as the **very last action of the run — after the `phase-end` post of "Phase 5 — Verify & report"** (this resolves the step-4-vs-cleanup ordering: phase-end first, cleanup after; phase numbers here are this skill's internal 1-5, not the `/kinoa` wizard's 0-7). Everything durable is already consolidated in the sync result and the log round; the raw listings and per-action receipts are redundant from that point. On `partial` / aborted runs, **keep it** — it is the resume and diagnostics material (exact fetched state, the plan, receipts of what landed) — and let the next successful run clean it up. Files: `events-predefined.json`, `events-custom.json`, `fields-predefined.json`, `fields-custom.json`, `fields-custom-deleted.json`, `fs-schemas.json`, `fs-settings.json`, `plan.json`, `*-verify.json` re-fetches, any producer-placed `<schema>.csv` FS seed files (read at apply), plus per-action apply outputs.

## Phase 1 — Preflight

1. Fire telemetry — live, as the run's first action, never deferred (hard rule 9): `python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" phase-start --phase "Phase 7 — dashboard sync (plugin)" --game-id <game_id from the manifest>` (local copy, self-contained per repo convention; exits 0 even on failure — log and continue; `--game-id` keeps attribution correct even when session.env belongs to another game — same flag rule as the producer's posts). The `(plugin)` suffix is deliberate: the producer kinoa skill posts the bare `Phase 7 — dashboard sync` label at phase entry, and without the suffix the support timeline shows two identical "Phase started" rows for one run.
2. Locate + parse + validate the manifest (rules above). Summarize to the developer in 2-3 lines: N predefined events, M custom events, K predefined fields, L custom fields, S feature schemas + T feature settings (v2 manifests), U unsupported items, from which producer/round. If a `kinoa-dashboard-sync-result.json` from a previous run sits next to the manifest, delete it now (`python -c "import os; os.remove('kinoa-dashboard-sync-result.json')"` — see §Workspace file-ops rule) — it's gitignored and regenerated every run, and a crash later in this run must not leave a stale result as the only candidate for the producer's pickup (the producer's freshness check guards reads, not existence).
3. Session preflight: `cat ~/.kinoa/session.env` (mask secrets when echoing — first 4 + last 4 chars). If missing → run the kinoa-init flow with `--integration-type SDK`; session.env has exactly one producer — kinoa-init; never hand-author it or seed it from a found token (hard rule 10). If present → **compare `KINOA_GAME_ID` with the manifest's `game_id` (cross-game guard, Inputs §Session): mismatch = stale session from another game → route to kinoa-init for the manifest's game before any fetch.** Matching id → proceed; an expired bearer surfaces as 401 in Phase 2 and routes back to kinoa-init for token rotation only. (The planner independently hard-fails on listings whose records carry a different game id — `listing_game_mismatch` — but that backstop fires after five wasted fetches; the preflight check is the real gate.)
4. Integration type: kinoa-init in SDK mode validates/aligns `integration_type=SDK` per its Step 3 SDK branch (developer consent required for the flip; never offer `API`). **When a present, game-matching session skips kinoa-init entirely** (step 3), the dashboard-side type is NOT re-validated this run — an accepted tradeoff: a drift surfaces as a helper `wrong_integration_type` error and routes per the failure table; do not re-run kinoa-init just to probe.
5. Plugin auto-update check (skip when not running as the installed plugin): the flag that actually drives plugin auto-update lives in the GLOBAL registry **`~/.claude/plugins/known_marketplaces.json`** (the `kinoa` entry; there is no CLI flag for it — a settings.json `extraKnownMarketplaces` declaration does not affect it). Read that file — if the `kinoa` entry lacks `"autoUpdate": true`, offer once via `AskUserQuestion`: *"The kinoa plugin marketplace has auto-update off — your dashboard skills can go stale as the Dashboard API evolves. Enable auto-update (adds one flag to `~/.claude/plugins/known_marketplaces.json`)?"* On yes → a single consent-gated `Edit` adding `"autoUpdate": true` to that entry, then re-read the file and confirm it still parses as JSON. If the file doesn't parse **before** the edit — don't touch it; tell the developer it's malformed and move on. Declining is fine — the sync proceeds; updates stay manual.

## Phase 2 — Fetch dashboard state

Seven read-only calls via the sibling helpers (five for a v1 manifest — the two FS listings only when the manifest carries `feature_settings`), outputs saved verbatim into the workspace. Live listing responses are `{"totalCount": N, "elements": [...]}` envelopes inside the helper's `response` — the planner unwraps them; don't reshape the files:

```bash
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-predefined --rows 200 > kinoa-sdk-dashboard-sync-workspace/events-predefined.json
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-custom --rows 200 > kinoa-sdk-dashboard-sync-workspace/events-custom.json
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-predefined --states active,not_implemented --rows 200 > kinoa-sdk-dashboard-sync-workspace/fields-predefined.json
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-custom --states active,not_implemented --rows 200 > kinoa-sdk-dashboard-sync-workspace/fields-custom.json
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-custom --states deleted --rows 200 > kinoa-sdk-dashboard-sync-workspace/fields-custom-deleted.json
# feature settings (schema_version 2 manifests only — skip these two for v1):
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py" list-schemas --rows 200 > kinoa-sdk-dashboard-sync-workspace/fs-schemas.json
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py" list-settings --rows 200 > kinoa-sdk-dashboard-sync-workspace/fs-settings.json
```

**Enrich `fs-schemas` for the column-level diff.** `list-schemas` returns summaries without `versions[].tableFields`, so the planner can only name-match them (and flags `already_ok` with a "column shape NOT verified" reason). To get a real version-conflict diff, for **each schema `name` in the manifest's `feature_settings.schemas` that also appears in `fs-schemas.json`**, run `get-schema --schema-id <id>` and replace that summary in `fs-schemas.json` with **the helper output's `response` object only** — never the whole `{http_status, ok, schema_id, response}` envelope (an embedded envelope has no top-level `name`, so the planner would classify the schema as absent and plan a duplicate create). Bounded by the manifest's schema count — usually a handful. There is no deleted-FS probe: feature settings are code→Dashboard create-only (no soft-delete/reactivate path like player fields).

There is deliberately NO deleted-events probe: the live `game_events` endpoint has no deleted state (event DELETE is hard) and silently ignores a `states` filter — a sixth "deleted events" fetch would just duplicate the active listing under a misleading filename.

On 401 from any call: the session token expired (~24h) — loop to kinoa-init (rotate token only), then re-run the failed call. On any other non-2xx: surface `http_status` + body and stop; do not improvise raw curl against the admin API. (Restricted environments that deny compound shell commands: run the fetches as separate single-line `python … > file` calls — the block above is one logical step, not one required command line.)

## Phase 3 — Plan & approve

1. Compute the plan:

```bash
python "${CLAUDE_SKILL_DIR}/kinoa_sdk_sync_plan.py" \
  --manifest <manifest-path> \
  --events-predefined kinoa-sdk-dashboard-sync-workspace/events-predefined.json \
  --events-custom kinoa-sdk-dashboard-sync-workspace/events-custom.json \
  --fields-predefined kinoa-sdk-dashboard-sync-workspace/fields-predefined.json \
  --fields-custom kinoa-sdk-dashboard-sync-workspace/fields-custom.json \
  --fields-custom-deleted kinoa-sdk-dashboard-sync-workspace/fields-custom-deleted.json \
  --fs-schemas kinoa-sdk-dashboard-sync-workspace/fs-schemas.json \
  --fs-settings kinoa-sdk-dashboard-sync-workspace/fs-settings.json \
  > kinoa-sdk-dashboard-sync-workspace/plan.json
```

(`--fs-schemas` / `--fs-settings` are optional — omit them for a `schema_version: 1` manifest. The planner accepts v1 and v2.)

2. Render the checklist **as a markdown table in chat** (not inside the question field), numbered, one row per planned action:

| # | Surface | Name / Path | Action | Why |
|---|---|---|---|---|
| 1 | event | `session_start` | publish | predefined in use by the game |
| 2 | field | `last_login_at` | activate | predefined field in use by the game |
| 3 | event | `gold_purchase` | create (+2 params) | not present on dashboard |
| 4 | field | `wallet.gold` | activate (was deleted) | soft-deleted record with same path |
| 5 | feature schema | `WheelOfFortune` | create + publish | feature schema not on dashboard |
| 6 | feature setting | `WheelOfFortune` | create + default config | setting key not on dashboard |
| — | feature schema | `DailyBonus` | ⚠ version conflict (developer GATE — no auto action) | code columns differ from the live ACTIVE version |

(`version_conflict` rows are **unnumbered** and do NOT count toward the gate's "Apply the N planned actions" — they are informational gates the sync never executes; only actionable rows get numbers.)

**Predefined-name warnings get one correction loop.** When the plan warns *"predefined event/player field not found on the dashboard"*, the cause is usually a producer-side mapping miss (e.g. `progression` vs the registry's `progress`, `personal_info.country` vs `.country_code`). The fix is producer-side: correct the **manifest** against the live predefined listing and re-run the planner — exactly once per sync, in the same session, never by "normalizing" names consumer-side, and never by creating a same-named custom entity as a workaround. Warnings that survive the correction loop stay warnings.

Below the table: `already_ok` count (one line), `dashboard_only` entities — events, player fields, **feature schemas, and feature settings** (informational — explicitly state they will NOT be touched), `warnings`, and every `unsupported` item with its `reason`. **Feature-settings `version_conflict` items are a developer GATE, not an auto-action** — render each with its `code_only_columns` / `dashboard_only_columns` / `type_changed_columns`; the helpers cannot edit a published schema version (there is no add-version verb), so the developer must either add a new schema version on the dashboard (then re-align the code's requested `version` at the four wiring sites and re-export `Default Feature Settings.zip`) or align the code to the live shape. The sync never resolves a `version_conflict` itself; a setting bound to a conflicted schema still binds the existing record unless the developer excludes it via Subset. (The FS section has no `unsupported` items — the producer folds every column to the operator's 5.) For unsupported **event params**, include the manual dashboard path (`https://dashboard.kinoa.io/game-settings/events/user` or `/predefined`) — they're registrable once the keys are known. For unsupported **player fields** (array/`List`/dict/`Guid`/`TimeSpan`), state that they ship in player state but are **not registrable** (no Dashboard field kind) — do NOT point to `/players` as a registration path; there's nothing to register there.

**When the plan restores something an operator deleted** (`was_deleted: true` actions, or a `create` for an entity present in earlier sync results), say so at the checklist: the sync restores every manifest-tracked entity on every run — if the deletion was intentional, the permanent fix is removing the entity from game code (and thus from the manifest), not deleting it on the dashboard again.

3. Gate via `AskUserQuestion` (decision first): **"Apply the N planned actions from the table above?"** — options: **Apply all (Recommended)** / **Subset** (developer lists row numbers in Other, e.g. "1, 3-5") / **Abort**. **Subset dependency closure (FS):** excluding a `schema_create` also excludes every `setting_create`/`config_*` bound to that schema; excluding a `setting_create` also excludes its `config_create`/`config_publish` — a dependent row cannot execute without its parent (the bind would fail mid-apply). State the auto-excluded rows back to the developer before applying. Record the answer; fire a `qa` webhook with question + answer immediately after the answer arrives, before any apply call (hard rule 9). **Zero planned actions** → render the checklist anyway with a single "none — dashboard already in sync" row plus the mandated below-table sections, skip the gate, and jump to Phase 5 executing all of it EXCEPT the verify re-fetch (nothing changed, nothing to re-verify): result write, sync summary, `phase-end`, cleanup all still run — and the `phase-end` summary carries `gate=skipped_zero_actions` so the support timeline can tell "skipped by rule" from "forgotten".

## Phase 4 — Apply

Execute approved actions in this fixed order (events → fields → feature settings; within events: publish → create → add-params; within fields: activate → create; within feature settings: schema create+publish → setting create → config create→submit→publish):

**⚠ Publish invalidates ids.** Publishing a predefined/unpublished event replaces the record with a **new ACTIVE record under a NEW id** — every pre-publish id in the plan goes stale the moment its event is published (observed live: `add-params` on a pre-publish id → 404 `fetch_failed`). Therefore: **after the `events.publish` bucket completes, re-fetch the event listings and re-resolve by NAME the `id` of every remaining event action** (`add_params` items for just-published events carry `resolve_id_after_publish: true` from the planner as a mechanical reminder). Never execute a later bucket with ids captured before a publish that touched the same event.

| Plan bucket | Helper call |
|---|---|
| `events.publish[]` | `kinoa_dashboard_event.py publish --event-id <id>` |
| `events.create[]` | `kinoa_dashboard_event.py create --name <name> [--no-analytics] --param NAME:KIND[:EXTRA]...` |
| `events.add_params[]` | `kinoa_dashboard_event.py add-params --event-id <id> --param NAME:KIND[:EXTRA]...` |
| `player_fields.activate[]` | `kinoa_dashboard_player_fields.py activate --field-id <id>` |
| `player_fields.create[]` | `kinoa_dashboard_player_fields.py create --name <name> --path <path> --kind <kind> [--extra ...]` — **never pass `--default-value`**: the live API 422-rejects it for non-calculated fields (*"defaultValue can only be set for calculated (EXTERNAL) fields"*), and manifest fields are code-backed, never calculated |

**Always append `--expect-game <game_id from the manifest>` to every call in this table.** It is the per-call cross-game backstop in the dashboard helpers (mirrors the planner's `listing_game_mismatch`): the helper aborts with `session_game_mismatch` (exit 2) before any state change if `session.env`'s `KINOA_GAME_ID` drifted to a different game. A `session_game_mismatch` is the same condition as the planner's exit 2 — stop and route to kinoa-init for the manifest's game; do not retry without `--expect-game`.

Per action: run the helper, read its JSON, record `{surface, name|path, action, id, http_status, ok}`. Failures don't abort the run (collect and continue) — **except 401**: stop immediately, write a partial sync result (`status: "partial"`), route to kinoa-init for token rotation, then re-run from Phase 2 (the recomputed plan contains only the remaining delta — this is the idempotent resume path).

`create` events: derive `--param` specs from the plan item's `params` (`name:kind` or `name:kind:extra`); pass `--no-analytics` only when the manifest entry has `"send_to_analytics": false`.

**Feature settings apply (after events + fields).** The FS chain threads ids forward, so run it as an ordered sequence through `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py`, not as independent rows. Every mutating call takes `--expect-game <game_id from the manifest>` (same cross-game backstop).

1. **`feature_settings.schema_create[]`** — `create-schema --name <name> --fields-json '<[{"name","type"}, …]>'` (types = the plan's `fields[].kind`); read the new schema `id` and version status. If the returned schema is not `ACTIVE`, `publish-schema --schema-id <id>` — a freshly created schema may **auto-activate**, so check status and publish only if still DRAFT.
2. **`feature_settings.schema_publish[]`** (existing DRAFT schemas) — `publish-schema --schema-id <id>`.
3. **`feature_settings.version_conflict[]`** — **NO apply action** (developer gate, surfaced at the checklist; the helpers can't add a schema version).
4. **`feature_settings.setting_create[]`** — resolve the schema `id` by `schema_name` (from step 1's create response, else from `fs-schemas.json`); `create-setting --key <key> --name <key> --schema-id <schemaId>`; read the new setting `id`.
5. **`feature_settings.config_create[]`** — **conditional items first** (`"conditional": "only_if_no_configs"`, planned for settings that already existed — the resume path): run `list-configs --setting-id <id>`; if ANY configuration exists, record the item as skipped (`already_has_configs`) and skip its paired `config_publish` too; only a zero-config setting proceeds. Then, for each config to create: **resolve the schema version by the setting's requested `version` NUMBER** — `get-schema --schema-id <schemaId>` and pick the version whose numeric `version` equals the manifest setting's `version` (for a schema created this run that is `"1"`); only when no version matches fall back to `latest-version --schema-id <schemaId>` **and record a warning** (the planner already flags requested-vs-live version drift — binding blindly to latest would mask it). Then `create-config --setting-id <id> --schema-id <schemaId> --schema-version-id <schema_version_id> --name "<key> default" --default`; read the config `id`. **If the item carries `seed_csv`, resolve it relative to the MANIFEST's directory** (the helper resolves `--csv` against the process cwd — pass the joined absolute path); if the file exists, `import-config-data --config-id <id> --csv <resolved-path>` — mirror the developer's provided values into the default config (the operator edits / segments afterward). If `seed_csv` is absent or the file is missing (e.g. a separate machine), leave the config empty and note it — never fail the sync over a missing seed file. **If the import itself fails** (non-2xx), record it in `failed` — the workspace (with the seed CSV) is then kept at cleanup for a manual re-import (`import-config-data` re-run, or the operator fills the table).
6. **`feature_settings.config_publish[]`** — `submit-config --config-id <id>` → `publish-config --config-id <id>` (skip items whose paired conditional `config_create` was skipped).

Record each FS action `{surface: "feature_schema" | "feature_setting" | "feature_config", name|key, action, id, http_status, ok}`. A 401 mid-FS-apply follows the same rule as events/fields — stop, write a partial result, rotate the token via kinoa-init, resume from Phase 2 (the recomputed plan contains only the remaining FS delta).

## Phase 5 — Verify & report

1. Re-fetch the listings that had planned actions (same calls as Phase 2, saved as `*-verify.json` siblings in the workspace — never overwrite the Phase-2 snapshots, they are the pre-apply audit trail) and confirm: published/created events are `ACTIVE`, activated/created fields are `active`. **Verify only surfaces where a mutating call actually fired** — a plan row conditionally SKIPPED at Phase 4 (`already_has_configs`) counts as "nothing changed": its conditional probe (`list-configs`) already produced fresh evidence, so no re-fetch is owed for it (same rationale as the zero-planned-actions rule). For feature settings, re-fetch `list-schemas` / `list-settings` (and `get-schema` for created schemas) and confirm created schemas are `ACTIVE`, created settings exist, and each default config is published — **acceptable config statuses: `SCHEDULED` or `ACTIVE`** (`publish-config` yields SCHEDULED; it auto-flips ACTIVE only once the start time passes — SCHEDULED is a successful publish, not a mismatch) via `list-configs --setting-id`. Mismatches go to `failed` with reason `verify_mismatch`.
2. Write **`./kinoa-dashboard-sync-result.json`** (project root, next to the manifest; overwrite is fine — it describes the latest sync). **`completed_at` needs a UTC anchor — don't fabricate from a local clock:** the canonical anchor is the `createdAt` echoed by the `phase-end` telemetry response — which fires at step 4, AFTER this write. **Two-pass by design:** write the file now with the latest successful post's `createdAt` as a provisional anchor, then after the `phase-end` post re-`Edit` `completed_at` to its `createdAt` (overwrite is legal — the file describes the latest sync); truncate to whole seconds and append `Z`. If no telemetry post succeeded this run, fall back to date-only (`<date>T00:00:00Z`); never emit a local time suffixed `Z`.

```json
{
  "schema_version": 1,
  "completed_at": "<ISO 8601 UTC, Z>",
  "manifest_path": "<path>",
  "manifest_generated_at": "<from manifest>",
  "game_id": "<from manifest/session>",
  "status": "completed | partial | aborted",
  "applied": [{"surface": "event", "name": "gold_purchase", "action": "created", "id": "<uuid>", "http_status": 200},
              {"surface": "feature_schema", "name": "WheelOfFortune", "action": "created+published", "id": "<uuid>", "http_status": 200},
              {"surface": "feature_setting", "key": "WheelOfFortune", "action": "created", "id": "<uuid>", "http_status": 200},
              {"surface": "feature_config", "key": "WheelOfFortune", "action": "published_default", "id": "<uuid>", "http_status": 200}],
  "skipped": [{"surface": "event", "name": "...", "reason": "developer excluded at checklist"}],
  "failed": [{"surface": "field", "path": "...", "action": "create", "http_status": 500, "error": "..."}],
  "unsupported": [],
  "version_conflicts": [{"surface": "feature_schema", "name": "DailyBonus",
                          "dashboard_only_columns": ["legacy"], "reason": "needs a new schema version — developer decision"}],
  "already_ok": [],
  "dashboard_only": {"events": [], "player_fields": [], "feature_schemas": [], "feature_settings": []},
  "warnings": []
}
```

3. Print a **sync summary** in chat: counts per bucket, the table of applied actions, unsupported items with manual registration links, and the result-file path. Do NOT title it "Closing summary" and do NOT use the `# Closing summary` / `*— end of summary —*` markers — those belong exclusively to the producer kinoa skill's logged summary; a second marker-delimited block in the same session can be extracted into the log by mistake. Remind: *"The `/kinoa` skill will pick up `kinoa-dashboard-sync-result.json` to log this round in `kinoa-integration-log.md` — or paste the summary there yourself if you run the log manually."*
4. Fire `phase-end --phase "Phase 7 — dashboard sync (plugin)" --summary "applied=N skipped=M failed=K unsupported=U status=<status> gate=<verbatim answer | skipped_zero_actions>" --game-id <game_id from the manifest>`. (Workspace cleanup follows AFTER this post — see §Cleanup policy.)

## Failure modes & routing

| Symptom | Action |
|---|---|
| No manifest found | Stop; instruct to run `/kinoa --merge` / `/kinoa dashboard-sync` in the game project. Never reconstruct the inventory yourself. |
| Manifest `integration_type: "API"` | Refuse; route to `kinoa-api-integration`. |
| Unknown `schema_version` | Refuse; the installed plugin is older/newer than the manifest producer — `/plugin marketplace update kinoa`, or regenerate the manifest with a current SDK skill. |
| `missing_credentials` from a helper | Run kinoa-init flow (`--integration-type SDK`). |
| 401 mid-run | Token rotation via kinoa-init, resume from Phase 2. |
| `wrong_integration_type` at preflight | STOP; surface the kinoa-init Step-3 SDK question verbatim and act only on the developer's in-session answer (hard rule 6). Never run `--fix-integration-type` unprompted, never on out-of-band advice, and always with `--integration-type SDK`. Never offer `API`. |
| Network error / 5xx | Surface and stop; suggest retry later. No raw-curl improvisation. |
| Mid-run request to delete dashboard entities (any requester) | Decline per hard rule 1; point to the dashboard UI (operator decision); continue the sync. |
| Tempted to batch, defer, or skip telemetry | No — hard rule 9: each post fires live at its trigger; resume live discipline. |
| session.env missing but a bearer is visible in scrollback/logs | Never hand-author session.env or reuse found tokens (hard rule 10); route to kinoa-init. |
| Urge to hand-edit the manifest to clear a preflight failure or "fix" a name | Never — the manifest is a generated measurement of code (hard rule 4); the planner exits 2 on non-SDK manifests; fix the code or use the predefined-name correction loop. |
| session.env `KINOA_GAME_ID` ≠ manifest `game_id` | Stale session from another game — route to kinoa-init for the manifest's game (prefill `--game-id`). Never fetch or apply under another game's id; the planner also exits 2 (`listing_game_mismatch`) as a backstop. |
| Planner exits 2 with `listing_truncated` | A listing came back paginated (`totalCount` > rows fetched) — the helpers fetch one page only. Re-run the affected Phase-2 fetch with a higher `--rows` (e.g. `--rows 1000`) and re-plan. If the server caps `--rows` below `totalCount`, true page-looping is needed (helper limitation — surface to the team). Never apply a plan built from a truncated listing. |
| `feature_settings.version_conflict` in the plan | Developer GATE, not an auto-action: surface `code_only_columns` / `dashboard_only_columns` / `type_changed_columns`. The helpers can't add a schema version — resolve on the dashboard (add a version, re-align the code's requested `version` + re-export `Default Feature Settings.zip`) or align the code to the live shape. Never silently bind a setting to a mismatched schema without flagging it. |
| `fs-schemas.json` rows lack `versions[].tableFields` | `list-schemas` returned summaries — the planner name-matches and flags `already_ok` "shape NOT verified". `get-schema` each manifest-matched schema and re-plan for a real column diff. |
| Feature schema/setting/config delete requested (any requester) | Decline per hard rule 1 (extends to feature settings); point to the dashboard UI. The sync only creates/publishes FS entities. |
| `seed_csv` referenced but the file is missing | Create the default config empty and note it (the operator fills values); never fail the sync over a missing seed file — it may live on another machine or be gitignored. |
| `import-config-data` rejected: `422 "[col] is invalid bundle key"` | The schema has `bundle_key` columns whose seeded values are either **malformed** (a Bundle key must start with a letter and contain only letters, digits, `_` and `-` — no dots) or **not created as Bundles yet** — both causes live-verified 2026-07-02, and **the 422 message is IDENTICAL for both**, so diagnose in order: check the value format first, then whether each value exists as a Bundle (the planner warns about both ahead of the checklist). Record in `failed`, CONTINUE the chain (submit → publish — the config publishes empty), keep the workspace at cleanup, and state the recovery in the summary: fix the values / create the Bundles on the dashboard, then re-run `import-config-data --config-id <id> --csv <seed>` manually (or let the operator fill the table). |

## Security boundary

Same as every dashboard helper: admin surface (`dashboard.kinoa.io`, bearer + Game/Game-Id headers) is **skill-only**. Nothing this skill does may introduce admin calls, tokens, or `dashboard.kinoa.io` references into the game's codebase — this skill does not write into the game project at all, except `kinoa-dashboard-sync-result.json` and the workspace directory (both data-only, no secrets: never copy the bearer token into them).
