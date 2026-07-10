---
name: kinoa-sync-player-fields-integration
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `sync-player-fields-integration` dispatch. Owns the player-fields workflow: discover the app's player class, generate KinoaPlayerState mirroring it, wire local storage (2.1), sync against Kinoa (activating predefined, creating custom) by delegating admin calls to kinoa-dashboard-player-fields, then produce a four-bucket HTML integration report (3.5). When the user wants to onboard app code with Kinoa, generate KinoaPlayerState, or sync player fields, route via kinoa-api-integration sync-player-fields-integration — the orchestrator enforces the init → player-fields → open-session → events order, and triggering this directly without prior init or with events already partly-done can silently corrupt the integration.
argument-hint: [optional: app source path]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This skill is the **integration / code-side** half of the player-fields pair. It owns the discover → generate → diff → apply → verify workflow but does no admin API calls itself; for every admin call it delegates to the sibling skill `kinoa-dashboard-player-fields` (whose helper `kinoa_dashboard_player_fields.py` wraps the session-token API on `dashboard.kinoa.io` plus the public `get-player-state` read on `gate.kinoa.io`). When both skills are installed as siblings under `~/.claude/skills/`, the relative path `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py` resolves correctly.

Requires `KINOA_BEARER_TOKEN`, `KINOA_GAME_ID`, and `KINOA_GAME_SECRET` in `~/.kinoa/session.env`. If any are missing, the dashboard helper returns `error: missing_credentials` — tell the user to set up Kinoa credentials first.

## Security boundary — what the skill calls vs. what app code calls

This skill makes calls against **two distinct surfaces**, and they must not be confused:

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin / dashboard API** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID) | **Skill only.** Delegated to `kinoa-dashboard-player-fields` (CLI: `python ../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py ...`) for list, activate, create, delete, plus the public-API `get-player-state` read used during verification. |
| **Public Player Events API** | `gate.kinoa.io`, `pevents.kinoa.io`, `featureset.kinoa.io` | `game: <game_secret>` (no bearer) | **App code.** Runtime calls from the application — open session, send events, fetch player state, etc. The Postman collection at `../kinoa-api-integration/references/postman-collection.json` is the canonical spec. |

**Hard rule when generating code into the application:** never emit code that calls `dashboard.kinoa.io` or sends an `Authorization: Bearer` header. The session token is admin-tier and must not ship in application binaries, configs, or runtime calls. If a Phase asks you to add code to the app, only use endpoints from the Postman collection (game-secret header).

When `Phase 4` verifies the integration, the skill itself calls `gate.kinoa.io/playerevents/api/v3/player-state` with the public game-secret header — same surface the app uses, so it's a faithful end-to-end check.

## Webhook telemetry

This skill is Phase 2 of the orchestrator's chain and has its own four inner phases. Fire telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 2.<n> — <heading>"` immediately when entering each inner phase 1–4 (use the heading text after the dash, e.g. `"Phase 2.1 — Discover the application's player class"`, `"Phase 2.3 — Sync field definitions with Kinoa"`).
- `phase-end --phase "Phase 2.<n> — <heading>" --summary "<one-line outcome>"` once that inner phase completes. Summaries should be terse — counts, "skipped by developer", or the C.5 report's bucket totals.
- `qa` after every `AskUserQuestion` exchange (file-path confirmation, checklist approvals in 2.3, more-fields review loop in 2.5, custom-kind prompts in 2.3.4, integration-test framework choice in 2.4.1).

Helper exits 0 even on failure; never abort the workflow on a webhook error.

**Run state.** On start, read `./.kinoa-integration-state.json` if present — if `phases.player_fields` records finished inner phases, resume from the first unfinished one instead of redoing work. Alongside every inner `phase-end`, read-merge-write the file's `phases.player_fields` entry: `status`, `service_root` (MONOREPO), `kinoa_player_state_path` (set in Phase 2), `report` (set in 3.5). Schema and rules: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/SKILL.md` → "Run state".

**Architecture & service scope.** Read `KINOA_ARCHITECTURE` from `~/.kinoa/session.env` (default `SINGLE`; semantics: orchestrator SKILL.md → "Architecture modes") before Phase 1:

- `MONOREPO` — ask which service directory owns the player model (offer candidate dirs found via Glob). Scope all Phase 1 discovery and the Phase 2 generated `KinoaPlayerState` to that `service_root`, and record it in the phase entry.
- `MULTI_REPO` — the current repo is the service. On start also read the central index `~/.kinoa/<game_id>/services.json`; if another service already integrated player fields, say so and confirm the developer really wants a second integration from this repo. At every module-level `phase-end`, update this service's entry in the index (`modules.player_fields`, `last_sync`).

**Integration registry.** Alongside every state-file write, update `KINOA-INTEGRATION.md` next to it (bootstrap from the orchestrator's template if missing): rewrite the "Player fields" section under `## Modules` to the current state (service, generated file path, field counts) and append a dated entry to `## History` describing what this run changed (fields activated/created, artifact paths). Append-only — never rewrite old History entries.

The skill works in four phases. Drive each phase to completion with the developer before moving to the next; they are sequential and each builds on the previous.

---

## Phase 1 — Discover the application's player class

1. Use `Glob` and `Grep` to find candidate classes representing the player model. Scan for: class names like `Player`, `PlayerState`, `User`, `UserState`, `Profile`, `GameProfile`, and for source files containing fields like `player_id` / `playerId`. Search the project root the user names (default: current working directory; in `MONOREPO` mode, the chosen `service_root` — see "Architecture & service scope" above).
2. If multiple candidates emerge, present them via `AskUserQuestion` and let the developer pick.
3. Read the chosen file. Extract every field declared on the player class:
   - **name** (as written in source)
   - **type** (the language type — `int`, `String`, `bool`, custom class, etc.)
   - **path** (dot-separated path from class root — for nested classes, descend into them; e.g., a field `country` inside a `PersonalInfo profile` member becomes path `profile.country`)
4. Detect the file's naming convention (camelCase vs snake_case) by sampling existing field names. Use this convention when generating any new code.

If you cannot identify a single player class with confidence, stop and ask the developer to point you to the right file. Do not guess.

---

## Phase 2 — Generate `KinoaPlayerState`

1. Propose a path for the new class file. Default: same directory/package as the existing player class, file name `KinoaPlayerState.<ext>` matching the language. Confirm with the developer via `AskUserQuestion` (option to override path/name).
2. Write the class:
   - One field: a `player_id` whose type matches the existing player's `player_id` (or its closest analogue).
   - Mirror the existing player's naming convention.
   - **Empty body otherwise** — fields will be added in Phase 3 as the developer approves them.
3. Save the file with `Write`.

`KinoaPlayerState` is a **pure data class** — fields only, no methods that call Kinoa. The application's existing integration code (or new code following the Postman collection) is responsible for serializing this class onto session-start / sync-event payloads using the public `gate.kinoa.io` endpoints with the game-secret header. Do not embed admin / session-token endpoints in this class or anywhere else in app code.

### 2.1 Wire up storage on the game side

Kinoa treats the **application as the source of truth** for player state. Kinoa stores what the app sends; it doesn't recompute it. That means there must be exactly one authoritative `KinoaPlayerState` instance the app maintains, updated whenever a field changes, and read on every event payload. Skipping this step is the most common reason fields appear as ❌ Missing in Phase 4 — the activation succeeded server-side but the app never sent a value.

1. **Look for existing player-state storage.** Common patterns: `PlayerRepository`, `PlayerStateManager`, `SaveManager`, a singleton holding the current `Player`. Use `Glob` / `Grep` for these.
   - If found: prefer extending it. Either store a `KinoaPlayerState` alongside the existing model, or add a method (`buildKinoaPlayerState()` / `toKinoaPlayerState()`) that snapshots the existing player-data into a `KinoaPlayerState` on demand. Reusing existing storage avoids state drift between two parallel models.
   - If not found, or the existing model can't cleanly be mapped: generate a minimal store appropriate to the platform. Confirm the platform with the developer first if it isn't obvious from the codebase. Reasonable defaults:
     - **Unity (C#)** → singleton + `JsonUtility` + `PlayerPrefs` or persistent file.
     - **Android (Java/Kotlin)** → singleton + Gson/Moshi + `SharedPreferences` or Room.
     - **iOS (Swift)** → `Codable` + `UserDefaults` or Core Data.
     - **Web (TS/JS)** → module-level singleton + `localStorage`.
     - **Server (any language)** → the existing DB / cache layer, keyed by `player_id`.
2. **Persist across launches** for fields whose value can't be recomputed from gameplay (progression, currency balances, achievements, region/country once chosen). Volatile fields (current session length, last-action timestamp) can live in memory only.
3. **Update sites** — after Phase 3.4 finishes there will be N fields in `KinoaPlayerState`. Tell the developer plainly: each field must be written to storage whenever its in-game value changes. Don't silently inject update calls into gameplay code; surface a checklist so the developer wires them deliberately. The Phase 3.5 report serves as that checklist.

This step adds **no** Kinoa API calls. Storage is purely local; the existing emission code (or code from the Postman collection) reads `KinoaPlayerState` from storage and POSTs it to `gate.kinoa.io` with the game-secret header.

---

## Phase 3 — Sync field definitions with Kinoa

### 3.1 Fetch existing field definitions

Two calls — predefined (system) and custom (USER) — so the diff knows about both kinds of fields already in Kinoa:

```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-predefined
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-custom
```

Each response is `{ http_status, ok, response: { totalCount, elements: [...] } }`. Elements have at least `id`, `name`, `path`, `kind`, `state`, and (for `kind: enumeration`) `extra` with comma-separated allowed values.

`list-custom` defaults to `state: active` only (excludes soft-deleted fields). For predefined fields the relevant states are `active` and `not_implemented`.

### 3.2 Compute the diff

**Pre-rule — install-time fields.** The predefined fields **`install_time`** (Unix epoch **seconds** of the app's first install) and **`install_time_ms`** (the same instant in **milliseconds**) feed Kinoa's install attribution. `install_time_ms` is **mandatory** — every integration must implement and activate it; `install_time` must be implemented alongside it (same instant, two granularities — derive one from the other, don't capture twice). Whatever bucket they classify into, mark `install_time_ms` with a leading ❗ MANDATORY and `install_time` with a leading ⭐, and pull both to the top of the 3.3 checklist. When implementing, capture the timestamp once at first launch and persist it (e.g., first-run guard writing to local storage); every subsequent `player_state` carries the same stored values. **When both fields end up implemented + active, the `install` *event* becomes optional** — Phase 4 (event sync) reads this and drops its ⭐ on `install`; record the outcome in the state file's `player_fields` entry as `"install_time_fields": "both" | "ms_only" | "seconds_only" | "none"`. If the developer skips `install_time_ms`, don't block — but state plainly that a mandatory field is missing (install attribution won't compute) and record it in the report callout.

For every predefined element, classify by comparing its `path` to the paths in `KinoaPlayerState`:

- `state == "active"` and path **NOT** present in `KinoaPlayerState` → 🟠 **WARNING** — Kinoa believes this field is implemented but the app code doesn't produce it. Either it's set elsewhere in the codebase Claude didn't read, or the active state is stale. Surface to the developer for review.
- `state == "not_implemented"` and path **IS** present in `KinoaPlayerState` → 🟢 **READY TO ACTIVATE** — call activate.
- `state == "not_implemented"` and path **NOT** in `KinoaPlayerState` → 🟡 **RECOMMEND IMPLEMENTING** — propose adding to `KinoaPlayerState`, then activate.

For every active **custom (USER)** field whose path is **NOT** in `KinoaPlayerState` → 🟣 **IMPLEMENT EXISTING CUSTOM** — Kinoa already has this user-defined field in active state. Some prior developer (or another team) created it; the current code base just doesn't read/write it yet. Propose adding it to `KinoaPlayerState` so the app produces values for it. No POST is needed (the field already exists in Kinoa); just code-side mirroring.

For every `KinoaPlayerState` field whose path is **not** among the predefined or active custom elements → 🔵 **CREATE CUSTOM** — propose a POST to register the new field with Kinoa.

If a `KinoaPlayerState` path matches an existing active custom field → ✅ **ALREADY CUSTOM** — already wired up on both sides, no action needed.

### 3.3 Present the checklist

Show a numbered list grouped by severity. Each row: icon, action, name, path, kind. Example:

```
⚠ install_time_ms is MANDATORY (install attribution); install_time (seconds)
  belongs with it. With both implemented + active, the install EVENT becomes
  optional in the events phase.

1. ❗🟡 Implement       — Install time ms (number) at path: install_time_ms  ← MANDATORY
2. ⭐🟡 Implement       — Install time (number) at path: install_time
3. 🟢 Activate         — Level (number) at path: level
4. 🟡 Implement        — Country code (enumeration) at path: personal_info.country_code
5. 🟠 Predefined warn  — Last event time (date) is active in Kinoa but missing in your KinoaPlayerState
6. 🟣 Implement custom — vip_tier (number) at path: vip_tier — already an active custom field in Kinoa, mirror it in code
7. 🔵 Create custom    — gold_balance (number) at path: wallet.gold
```

Ask the developer which actions to apply: comma-separated indices, `all`, or `none`.

### 3.4 Apply approved actions

Execute in order. After each call, read the JSON; if `ok == false`, surface `http_status` and `response`, then ask whether to retry, skip, or stop the whole phase.

- 🟢 **Activate** an existing predefined field:
  ```
  python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" activate --field-id <uuid>
  ```

- 🟡 **Implement + activate** (predefined that's not yet implemented):
  1. Use `Edit` to add the field to `KinoaPlayerState` at the right nested path. Preserve the file's naming convention. Keep types reasonable (e.g., Kinoa `kind: number` → app's int/long type, `kind: string` → app's string type, `kind: enumeration` → enum or string with a comment listing allowed values from `extra`).
  2. Then activate via the same command as above.

- 🟣 **Implement existing custom** (active custom field not yet in code):
  1. Use `Edit` to add the field to `KinoaPlayerState` at the matching path. Same type-mapping rules as 🟡. For enumerations, copy the allowed values from `extra` on the existing custom field record so the app's enum stays in sync with Kinoa.
  2. **No API call** — the field is already active in Kinoa. The work is purely code-side mirroring.

- 🔵 **Create custom** field:
  1. Confirm the kind with the developer. **Allowed kinds: `number`, `boolean`, `string`, `date`, `long_string`, `enumeration`, `version`.** Anything else must be remapped to one of these.
  2. For `enumeration`, ask for allowed values as comma-separated string (`v1,v2,v3`).
  3. Run:
     ```
     python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" create \
         --name "<name>" --path "<path>" --kind <kind> [--extra "v1,v2"] \
         [--description "<desc>"] [--default-value "<value>"]
     ```

After the loop completes, summarize: how many activated, how many created, how many failed.

---

## Phase 3.5 — Generate the sync report

Once Phase 3.4 has finished (or has been skipped because nothing needed applying), produce a human-readable HTML report so the developer has a durable record of the sync state. This runs unconditionally — even with zero changes the report is useful as a snapshot of "what's wired up vs. what isn't."

The report has four buckets, mirroring how a developer thinks about the sync afterwards:

1. **Predefined fields — integrated** — every predefined element with `state == "active"` whose `path` appears in `KinoaPlayerState`. Includes both fields activated this run (🟢, 🟡) and any that were already active before. The `note` distinguishes them ("newly activated", "implemented + activated", "already active before this run").
2. **Predefined fields — NOT integrated** — every predefined element with `state == "not_implemented"` (regardless of `KinoaPlayerState`), plus any `state == "active"` predefined whose path is **not** in `KinoaPlayerState` (the 🟠 warning case). Include the `state` column so the developer can tell them apart. The `note` should explain the situation: "skipped by developer", "recommended but skipped", or "active in Kinoa but missing in code (warning)". When this bucket is non-empty, the report script renders a callout above the sections stating the consequence honestly: the integration keeps working without these fields, but calculated properties / segments / analytics that rely on them won't be computed (no data), and implementing them in the game is recommended if possible.
3. **Custom fields — integrated** — every active USER field whose `path` appears in `KinoaPlayerState`. Includes 🔵 newly created, 🟣 mirrored-from-existing, and ✅ already-in-sync. The `note` distinguishes them.
4. **Custom fields — NOT integrated** — every active USER field whose `path` is **not** in `KinoaPlayerState` and the developer didn't approve mirroring. These are dashboard-only custom fields the app currently ignores.

### Building the JSON

Assemble the payload from data already in hand:
- `predefined` and `custom` element lists from 3.1.
- The set of `KinoaPlayerState` paths from Phase 1 (re-read the file if it was edited in 3.4).
- The list of actions actually applied in 3.4 (whether each succeeded), so notes are accurate.

Schema:

```json
{
  "generated_at": "<ISO 8601 UTC>",
  "game_id": "<KINOA_GAME_ID>",
  "kinoa_player_state_path": "<path written in Phase 2>",
  "predefined_integrated":     [{"name", "path", "kind", "note"}, ...],
  "predefined_not_integrated": [{"name", "path", "kind", "state", "note"}, ...],
  "custom_integrated":         [{"name", "path", "kind", "note"}, ...],
  "custom_not_integrated":     [{"name", "path", "kind", "note"}, ...]
}
```

### Render and save

Pipe the JSON into the bundled script. Output path: `./kinoa-player-fields-integration-report-<YYYYMMDD-HHMMSS>.html` in the project's current working directory (timestamped so repeated syncs don't clobber each other).

```bash
echo '<json>' | python "${CLAUDE_SKILL_DIR}/generate_report.py" --output ./kinoa-player-fields-integration-report-<ts>.html
```

The script prints `{"ok": true, "output": "...", "bytes": N, "opened_in_browser": true|false}`. **The script also auto-opens the file in the developer's default browser** via `webbrowser.open()` — that is the intended UX, so the developer can review the report immediately without copy-pasting paths. If `opened_in_browser` comes back `false` (rare — headless environment, browser not available), surface the absolute path so they can open it manually. If the project has a `.gitignore`, suggest they add `kinoa-player-fields-integration-report-*.html` to it — the report is a local artifact, not source.

### Review loop

Once the developer has had a chance to look at the report, ask via `AskUserQuestion` whether they want to integrate more fields now. The four-bucket layout often surfaces things the developer didn't think to add on the first pass — predefined fields they skipped, custom fields sitting in the dashboard from a previous teammate's work, or new custom fields they realize they need.

- **Yes** — re-run 3.1 (lists may have changed if anyone else has been editing the dashboard), recompute the diff in 3.2, present a fresh checklist in 3.3, apply in 3.4, regenerate the report in 3.5. The previous report file stays on disk; the new one gets a new timestamp.
- **No** — proceed to Phase 4.

Don't loop without asking. The developer might be done, and the report itself is the durable answer to "what's still missing."

---

## Phase 4 — Integration test in the application's codebase

The goal: confirm the application can populate every `KinoaPlayerState` field through Kinoa and read it back. The honest way to do this is from the application's real code path, expressed as an **integration test in the project's own test suite** — not from a synthetic POST.

The application is Kinoa's source of truth for player state (see Phase 2.1). An integration test running through the project's storage layer, session-open code, and emission layer proves the whole chain works end-to-end, and leaves the team a worked example in their own tests that they can extend.

### 4.1 Detect the test framework

Look for project markers to guess the test stack, and skim one or two existing test files to mirror their conventions:

- `pom.xml` / `build.gradle(.kts)` → JUnit (Java / Kotlin), tests under `src/test/...`.
- `package.json` with `jest` / `vitest` / `mocha` in dependencies → JS/TS test runner.
- `requirements*.txt` / `pyproject.toml` with `pytest` → pytest, tests under `tests/`.
- `*.csproj` → xUnit / NUnit.
- Unity `*.asmdef` files referencing `nunit` → Unity Test Runner.

If multiple stacks exist, ask via `AskUserQuestion` where the developer wants the test placed.

### 4.2 Generate the integration test

Create one test file in the project's existing test directory, alongside the existing tests for the player-state code. Keep it minimal: one player, one session, one assertion per field. The test should:

1. **Build a fixture** — generate a unique `player_id` (e.g., `kinoa_player_test_<short-uuid>`).
2. **Open a Kinoa session via the application's own session-open path** — not by calling `gate.kinoa.io` directly from the test.
3. **Populate `KinoaPlayerState`** with a non-default value for every field synced in Phase 3, using the storage layer wired in Phase 2.1 (`PlayerRepository` / state singleton / etc.).
4. **Trigger whatever the application normally does to send state to Kinoa** — typically the next event emission, or a periodic sync. The test exercises the real call path.
5. **Read back the player state via the public API** and assert every field arrived:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" get-player-state --player-id <id>
   ```
   This GETs `https://gate.kinoa.io/playerevents/api/v3/player-state?player_id=<id>` with the public `game: <secret>` header. The response body holds the player's full state.
6. **Print one line to stdout** naming `player_id` and `session_id` so the developer can find the record in the Kinoa dashboard if the assertion fails.

Skeleton (adapt to the project's framework):

```java
@Test
void allKinoaPlayerStateFieldsLandInKinoa() throws Exception {
    String playerId = "kinoa_player_test_" + UUID.randomUUID().toString().substring(0, 8);
    KinoaSession session = sessionOpener.openForPlayer(playerId);
    playerRepository.update(p -> p.setLevel(7).setProfile(new PersonalInfo("US")));
    sender.flush();  // whatever the app does to push state
    System.out.printf("populated: player_id=%s session_id=%s%n", playerId, session.getSessionId());
    assertPlayerStateFieldsPresent(playerId, "level", "personal_info.country_code");
}
```

For each field in `KinoaPlayerState`, the assertion helper walks its dot-path through the response (start at `response.player_state`; if absent, fall back to `response`) and reports:

- ✅ **Found** — path resolved to a non-null value. Show the value.
- ❌ **Missing** — path doesn't resolve, or resolved to `null`. Likely causes: the application code didn't populate it, activation hasn't propagated yet, or the storage layer wired in 2.1 isn't being flushed before the test reads.

### 4.3 Run it and verify

Tell the developer to run the test using the project's normal command (`mvn test`, `gradle test`, `npm test`, `pytest`, etc.). They confirm here once it passes — or paste any failure so you can help diagnose. End with a one-line summary: `<n>/<total> KinoaPlayerState fields verified in Kinoa.`

If anything is missing, recommend re-running Phase 3 to verify activations, re-checking that the application code actually writes the field to storage and pushes it on the session payload, then retry the test.

---

## Reference

- Endpoints used:
  - `GET    https://dashboard.kinoa.io/gamemetaapi/api/player_fields?types=PREDEFINED&...` — list predefined.
  - `GET    https://dashboard.kinoa.io/gamemetaapi/api/player_fields?types=USER&...` — list custom.
  - `PATCH  https://dashboard.kinoa.io/gamemetaapi/api/player_fields/<id>/ACTIVATE` — activate predefined.
  - `POST   https://dashboard.kinoa.io/gamemetaapi/api/player_fields` — create custom.
  - `DELETE https://dashboard.kinoa.io/gamemetaapi/api/player_fields/<id>` — soft delete (sets `state: deleted`, returns 204).
  - `GET    https://gate.kinoa.io/playerevents/api/v3/player-state?player_id=<id>` — fetch full state.
- Headers:
  - `dashboard.kinoa.io/gamemetaapi/...` → `Authorization: Bearer <session_token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same game UUID).
  - `gate.kinoa.io/playerevents/...` → `game: <game_secret>`.
- Allowed kinds for custom field creation: `number`, `boolean`, `string`, `date`, `long_string`, `enumeration`, `version`.
- The `delete` subcommand is available for cleanup after test runs but is not part of the main sync workflow — call it only when explicitly asked, and even then confirm first via `AskUserQuestion` (resolved field id + name/path, soft-delete semantics), proceeding only on an explicit Yes from this session.
