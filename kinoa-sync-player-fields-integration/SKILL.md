---
name: kinoa-sync-player-fields-integration
description: Synchronize the application's player model with Kinoa — the integration/code-side half of the player-fields pair. Discover the existing player class in the app code, generate a KinoaPlayerState class mirroring it, then orchestrate a sync against Kinoa (activating predefined, creating custom) by delegating every admin call to the sibling kinoa-dashboard-player-fields skill. Includes a test scenario verifying every field appears in the returned player_state. Use whenever the user wants to onboard application code with Kinoa, generate KinoaPlayerState, sync player fields with the dashboard, or verify the integration end-to-end.
argument-hint: [optional: app source path]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This skill is the **integration / code-side** half of the player-fields pair. It owns the discover → generate → diff → apply → verify workflow but does no admin API calls itself; for every admin call it delegates to the sibling skill `kinoa-dashboard-player-fields` (whose helper `kinoa_dashboard_player_fields.py` wraps the bearer-token API on `dashboard.kinoa.io` plus the public `get-player-state` read on `gate.kinoa.io`). When both skills are installed as siblings under `~/.claude/skills/`, the relative path `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py` resolves correctly.

Requires `KINOA_BEARER_TOKEN`, `KINOA_GAME_ID`, and `KINOA_GAME_SECRET` in `~/.kinoa/session.env`. If any are missing, the dashboard helper returns `error: missing_credentials` — tell the user to set up Kinoa credentials first.

## Security boundary — what the skill calls vs. what app code calls

This skill makes calls against **two distinct surfaces**, and they must not be confused:

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin / dashboard API** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game-Id: <uuid>` | **Skill only.** Delegated to `kinoa-dashboard-player-fields` (CLI: `python ../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py ...`) for list, activate, create, delete, plus the public-API `get-player-state` read used during verification. |
| **Public Player Events API** | `gate.kinoa.io`, `pevents.kinoa.io`, `featureset.kinoa.io` | `game: <game_secret>` (no bearer) | **App code.** Runtime calls from the application — open session, send events, fetch player state, etc. The Postman collection at `../kinoa-api-integration/references/postman-collection.json` is the canonical spec. |

**Hard rule when generating code into the application:** never emit code that calls `dashboard.kinoa.io` or sends an `Authorization: Bearer` header. The bearer token is admin-tier and must not ship in application binaries, configs, or runtime calls. If a Phase asks you to add code to the app, only use endpoints from the Postman collection (game-secret header).

When `Phase D` verifies the integration, the skill itself calls `gate.kinoa.io/playerevents/api/v3/player-state` with the public game-secret header — same surface the app uses, so it's a faithful end-to-end check.

The skill works in four phases. Drive each phase to completion with the developer before moving to the next; they are sequential and each builds on the previous.

---

## Phase A — Discover the application's player class

1. Use `Glob` and `Grep` to find candidate classes representing the player model. Scan for: class names like `Player`, `PlayerState`, `User`, `UserState`, `Profile`, `GameProfile`, and for source files containing fields like `player_id` / `playerId`. Search the project root the user names (default: current working directory).
2. If multiple candidates emerge, present them via `AskUserQuestion` and let the developer pick.
3. Read the chosen file. Extract every field declared on the player class:
   - **name** (as written in source)
   - **type** (the language type — `int`, `String`, `bool`, custom class, etc.)
   - **path** (dot-separated path from class root — for nested classes, descend into them; e.g., a field `country` inside a `PersonalInfo profile` member becomes path `profile.country`)
4. Detect the file's naming convention (camelCase vs snake_case) by sampling existing field names. Use this convention when generating any new code.

If you cannot identify a single player class with confidence, stop and ask the developer to point you to the right file. Do not guess.

---

## Phase B — Generate `KinoaPlayerState`

1. Propose a path for the new class file. Default: same directory/package as the existing player class, file name `KinoaPlayerState.<ext>` matching the language. Confirm with the developer via `AskUserQuestion` (option to override path/name).
2. Write the class:
   - One field: a `player_id` whose type matches the existing player's `player_id` (or its closest analogue).
   - Mirror the existing player's naming convention.
   - **Empty body otherwise** — fields will be added in Phase C as the developer approves them.
3. Save the file with `Write`.

`KinoaPlayerState` is a **pure data class** — fields only, no methods that call Kinoa. The application's existing integration code (or new code following the Postman collection) is responsible for serializing this class onto session-start / sync-event payloads using the public `gate.kinoa.io` endpoints with the game-secret header. Do not embed admin/bearer endpoints in this class or anywhere else in app code.

---

## Phase C — Sync field definitions with Kinoa

### C.1 Fetch existing field definitions

Two calls — predefined (system) and custom (USER) — so the diff knows about both kinds of fields already in Kinoa:

```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-predefined
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" list-custom
```

Each response is `{ http_status, ok, response: { totalCount, elements: [...] } }`. Elements have at least `id`, `name`, `path`, `kind`, `state`, and (for `kind: enumeration`) `extra` with comma-separated allowed values.

`list-custom` defaults to `state: active` only (excludes soft-deleted fields). For predefined fields the relevant states are `active` and `not_implemented`.

### C.2 Compute the diff

For every predefined element, classify by comparing its `path` to the paths in `KinoaPlayerState`:

- `state == "active"` and path **NOT** present in `KinoaPlayerState` → 🟠 **WARNING** — Kinoa believes this field is implemented but the app code doesn't produce it. Either it's set elsewhere in the codebase Claude didn't read, or the active state is stale. Surface to the developer for review.
- `state == "not_implemented"` and path **IS** present in `KinoaPlayerState` → 🟢 **READY TO ACTIVATE** — call activate.
- `state == "not_implemented"` and path **NOT** in `KinoaPlayerState` → 🟡 **RECOMMEND IMPLEMENTING** — propose adding to `KinoaPlayerState`, then activate.

For every active **custom (USER)** field whose path is **NOT** in `KinoaPlayerState` → 🟣 **IMPLEMENT EXISTING CUSTOM** — Kinoa already has this user-defined field in active state. Some prior developer (or another team) created it; the current code base just doesn't read/write it yet. Propose adding it to `KinoaPlayerState` so the app produces values for it. No POST is needed (the field already exists in Kinoa); just code-side mirroring.

For every `KinoaPlayerState` field whose path is **not** among the predefined or active custom elements → 🔵 **CREATE CUSTOM** — propose a POST to register the new field with Kinoa.

If a `KinoaPlayerState` path matches an existing active custom field → ✅ **ALREADY CUSTOM** — already wired up on both sides, no action needed.

### C.3 Present the checklist

Show a numbered list grouped by severity. Each row: icon, action, name, path, kind. Example:

```
1. 🟢 Activate         — Level (number) at path: level
2. 🟡 Implement        — Country code (enumeration) at path: personal_info.country_code
3. 🟠 Predefined warn  — Last event time (date) is active in Kinoa but missing in your KinoaPlayerState
4. 🟣 Implement custom — vip_tier (number) at path: vip_tier — already an active custom field in Kinoa, mirror it in code
5. 🔵 Create custom    — gold_balance (number) at path: wallet.gold
```

Ask the developer which actions to apply: comma-separated indices, `all`, or `none`.

### C.4 Apply approved actions

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
  1. Confirm the kind with the developer. **Allowed kinds: `number`, `boolean`, `string`, `enumeration`, `version`.** Anything else must be remapped to one of these.
  2. For `enumeration`, ask for allowed values as comma-separated string (`v1,v2,v3`).
  3. Run:
     ```
     python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" create \
         --name "<name>" --path "<path>" --kind <kind> [--extra "v1,v2"] \
         [--description "<desc>"] [--default-value "<value>"]
     ```

After the loop completes, summarize: how many activated, how many created, how many failed.

---

## Phase D — Test scenario

The goal: confirm the application can populate every `KinoaPlayerState` field through Kinoa and read it back. The honest test is to run the developer's own integration code — that is, the code that calls Kinoa's public Player Events API with `KinoaPlayerState` as the source of `player_state`.

1. Tell the developer:
   > "Run the code path in your application that opens a Kinoa session and populates `KinoaPlayerState` for a known player. Use a unique test player_id (e.g., `kinoa_sync_test_<short-uuid>`) so you can identify it later. Confirm here when the session has been opened."
2. Once the developer confirms, ask for the test `player_id` they used.
3. Pull the resulting state:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" get-player-state --player-id <id>
   ```
   This GETs `https://gate.kinoa.io/playerevents/api/v3/player-state?player_id=<id>` with the public `game: <secret>` header. The response body holds the player's full state.
4. For every field in `KinoaPlayerState`, walk its dot-path through the response (start at `response.player_state`; if absent, fall back to `response`). Report:
   - ✅ **Found** — path resolved to a non-null value. Show the value.
   - ❌ **Missing** — path doesn't resolve, or resolved to `null`. Likely cause: the application code didn't populate it, or activation hasn't propagated yet.
5. End with a one-line summary: `<n>/<total> KinoaPlayerState fields verified in Kinoa.` If anything is missing, recommend re-running Phase C to verify activations and rechecking that the application code actually sets the field on the session payload, then retry the test.

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
  - `dashboard.kinoa.io/gamemetaapi/...` → `Authorization: Bearer <bearer>` + `Game-Id: <uuid>`.
  - `gate.kinoa.io/playerevents/...` → `game: <game_secret>`.
- Allowed kinds for custom field creation: `number`, `boolean`, `string`, `enumeration`, `version`.
- Predefined fields may use additional kinds (`date`, `long_string`); the skill reads them but does not create new fields with those kinds.
- The `delete` subcommand is available for cleanup after test runs but is not part of the main sync workflow — call it only when explicitly asked.
