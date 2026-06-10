---
name: kinoa-sync-feature-settings-integration
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `sync-feature-settings-integration` dispatch (Phase 5, after init → player-fields → open-session → events). Owns the feature-settings workflow: discover the schema (reuse an existing one by id/link, or infer a new one from a CSV via kinoa-csv-schema-infer), activate it, create a setting bound to it, create a test configuration and load its data, mark-as-default and publish, generate a single FeatureSettingsFacade in the app that fetches the config for a player from gate.kinoa.io/featureset, then verify end-to-end that the previously-created player resolves the config — covered by tests with mocked HTTP. Delegates every dashboard call to kinoa-dashboard-feature-settings. When the user wants to integrate feature settings / feature schema / remote config with Kinoa, build a feature-schema from a CSV, or wire a feature-settings facade into their app, route via kinoa-api-integration sync-feature-settings-integration — the orchestrator enforces the prerequisite ordering (init/player-fields/open-session/events done, so credentials and a real player exist).
argument-hint: [optional: app source path]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This skill is the **integration / code-side** of the feature-settings pair. It
owns the discover → generate → sync → verify workflow but makes **no admin API
calls itself**; for every dashboard call it delegates to the sibling skill
`kinoa-dashboard-feature-settings` (helper `kinoa_dashboard_feature_settings.py`),
and for CSV type-inference it delegates to `kinoa-csv-schema-infer`. When the
skills are installed as siblings under `~/.claude/skills/`, these relative paths
resolve:

```
${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py
${CLAUDE_SKILL_DIR}/../kinoa-csv-schema-infer/kinoa_csv_schema_infer.py
```

## Prerequisites

This is **Phase 5** — the last link in the chain. It assumes init (credentials),
player-fields, open-session, and events are already done, because:

- The dashboard helper needs `KINOA_BEARER_TOKEN` + `KINOA_GAME_ID`, and the
  runtime verification needs `KINOA_GAME_SECRET` — all from `~/.kinoa/session.env`.
- Verification reuses a **real player**. `kinoa-open-session` persists
  `KINOA_LAST_PLAYER_ID`; this skill uses it (or mints a fresh UUID if absent).

Before starting, confirm credentials resolve by listing schemas:
```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py" list-schemas
```
A `missing_credentials` or `401` means init wasn't run (or the ~24h token expired)
— tell the user to run `/kinoa-init` and stop.

## The three-resource model (internalize this)

```
SCHEMA  (typed columns, status DRAFT→ACTIVE)
  └─ VERSION  (number "1","2",… — newest = largest number; carries tableFields[])
SETTING (runtime `key` + name, binds ONE schema by schemaId)
  └─ CONFIGURATION (data rows for ONE schema version; lifecycle DRAFT→IN_REVIEW→SCHEDULED→ACTIVE)
```

The app fetches by **setting key + schema version number** and gets the matching
configuration's rows. So every phase below is a step along: build+activate schema
→ bind a setting → create+fill+publish a configuration → fetch by key.

## Scoped runs — execute just one step

The full Phase 5 (schema → setting → configuration → facade → verify) is the
default, but the developer may want **only one slice**. Detect this from the
request (and from a scope token in `$ARGUMENTS`, e.g. `schema-from-csv`) and run
just that slice, then stop — don't push them through the rest.

- **`schema-from-csv` — create a schema from a CSV, nothing else.** This is the
  most common scoped run. Do **only**:
  1. Phase 5.1b — infer types from the CSV via `kinoa-csv-schema-infer`, show the
     review table, take any `--type` overrides.
  2. `create-schema` (from the inferred body) then `publish-schema` (DRAFT→ACTIVE),
     delegating to `kinoa-dashboard-feature-settings`.
  3. Report the new schema id + version and **stop**. No setting, no configuration,
     no facade, no test. Offer — but don't assume — that they can run the full
     Phase 5 later to wire a setting/config/facade on top of this schema.

  The whole step is two delegated calls; it needs only `KINOA_BEARER_TOKEN` +
  `KINOA_GAME_ID` (no game secret, since nothing runtime happens):
  ```bash
  CSV=<path>; NAME=<SchemaName>
  INFER="${CLAUDE_SKILL_DIR}/../kinoa-csv-schema-infer/kinoa_csv_schema_infer.py"
  H="${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py"
  python "$INFER" infer --csv "$CSV" --name "$NAME" --emit body [--type col=type ...] \
    | python "$H" create-schema          # → capture response.id
  python "$H" publish-schema --schema-id <id>
  ```

- Other slices follow the same idea: run the requested sub-steps (e.g. "just
  create a setting on schema X", "just publish configuration Y") by delegating the
  matching `kinoa-dashboard-feature-settings` subcommands, and skip the phases the
  developer didn't ask for. The full chain below is the guide for what each slice
  entails.

When the developer wants the **whole** integration, ignore this section and run
Phase 5.1 → 5.5 in order.

## Security boundary — admin vs runtime

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io/featuresettingsapi` | `Authorization: Bearer` + `Game` + `Game-Id` | **Skill only.** Delegated to `kinoa-dashboard-feature-settings`. |
| **Runtime** | `gate.kinoa.io/featureset` | `game: <game_secret>` | **App code.** The generated `FeatureSettingsFacade` POSTs to `gate.kinoa.io/featureset/features-configurations` with the game-secret header. |

**Hard rule:** the `FeatureSettingsFacade` you generate must call **only**
`gate.kinoa.io/featureset` with the `game` secret. Never emit code that hits
`dashboard.kinoa.io` or carries `Authorization: Bearer` — that's an admin token
and must not ship in an application.

## Webhook telemetry

This skill is Phase 5 of the orchestrator's chain with its own inner phases. Fire
telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 5.<n> — <heading>"` on entering each inner phase.
- `phase-end --phase "Phase 5.<n> — <heading>" --summary "<one-line outcome>"` on completion (terse counts: schema id, setting key, config status, runtime verify result, or "skipped by developer").
- `qa` after every `AskUserQuestion` exchange (schema source in 5.1, type overrides, facade path/naming in 5.2, key/name confirmation, test-data confirmation, test-framework choice in 5.5).

The helper exits 0 even on failure; never abort the workflow on a webhook error.

Drive each phase to completion with the developer before moving on.

---

## Phase 5.1 — Discover the schema

A feature schema can either already exist in the dashboard, or be created fresh
from a CSV the developer has. Ask which via `AskUserQuestion`:

- **Reuse an existing schema** — the developer has a schema id or a dashboard link.
- **Create from a CSV** — the developer has a CSV whose headers are the fields and
  whose rows are sample/seed data.

### 5.1a — Existing schema

1. Get the id. If the developer pastes a **dashboard link**
   (e.g. `…/feature-settings/schemas/<uuid>` or a URL with `?schemaId=<uuid>`),
   extract the UUID from the path/query. If unsure which segment is the id, run
   `active-schemas-meta` and match by name with the developer.
2. Fetch and show it:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py" get-schema --schema-id <id>
   ```
   Present the fields (`versions[].tableFields` → name:type) and confirm this is
   the right schema.
3. If `status != "ACTIVE"`, publish it in 5.3 (a setting can bind it but only an
   ACTIVE schema serves at runtime). Note the status now.

### 5.1b — New schema from CSV

1. Ask for the CSV path. Run the inference utility and show the **review table**:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-csv-schema-infer/kinoa_csv_schema_infer.py" infer --csv <path> --name <SchemaName>
   ```
   Walk the developer through `review[]` — each column's `inferred_type`,
   `samples`, and any `enumeration candidate` note. Inference is a starting point;
   the developer owns the final types.
2. Collect corrections and re-run with overrides as needed, e.g.
   `--type sku=bundle_key --type tier=enumeration`. (A schema field carries no
   allowed-value list, so `enumeration` only changes the label.)
3. Hold onto the CSV path — it doubles as the **seed data** for the test
   configuration in 5.3. The actual schema is POSTed in 5.3 (so create + publish
   land together with the rest of the apply step). Keep the inferred `--emit body`
   output ready.

In both branches, end 5.1 with: a schema name, its field list, and either an
existing schema id (+status) or the inferred create-schema body.

---

## Phase 5.2 — Generate the `FeatureSettingsFacade`

Generate **one** developer-facing class in the application — the
`FeatureSettingsFacade` — that hides the runtime HTTP and hands back typed config.
A single facade is the deliberate shape (per the integration's naming): one place
the rest of the app calls, e.g. `featureSettings.get("BoostersConfig")`.

1. **Discover the app's conventions.** Glob/Grep for where existing Kinoa code
   lives (`KinoaPlayerState`, `KinoaEvents` from earlier phases) and mirror its
   language, package, and naming (`FeatureSettingsFacade.java` / `.kt` /
   `feature_settings_facade.py` / `FeatureSettingsFacade.cs`, etc.). Adjust the
   class name to the project's casing if it differs. Propose the path via
   `AskUserQuestion`.
2. **The facade does exactly one network thing** — `POST` to
   `https://gate.kinoa.io/featureset/features-configurations` with header
   `game: <game_secret>` and body:
   ```json
   { "settings": [ { "key": "<settingKey>", "version": "<n>", "getDefault": false,
                     "checksums": [ "<last-known-checksum-or-omitted>" ] } ],
     "playerId": "<playerId>" }
   ```
   - **`getDefault` is `false`** — that is normal client usage; a published default
     config still resolves. Don't send `true`.
   - It parses the response `settings[0]` → `{ status, configurationName, data: [ {col: value} ], checksum, … }`
     and returns the `data` rows (or an empty/typed result when `status != "OK"`).
   - Expose a small, clear surface, e.g. `get(settingKey, playerId)` → list of typed
     row records (a record mirroring the schema fields, name + Kinoa type → language
     type) so callers get `row.reward()` not `row.get("reward")`.
3. **Checksum caching — this is the point of the facade, not an extra.** The
   facade keeps a client-side cache per `(settingKey, version)` of the last
   `{checksum, rows}` it received (in memory, or persisted like the player-state
   store from Phase 2). On each call:
   - send the cached `checksum` in the request's `checksums` (omit on first call);
   - when the config is **unchanged**, the server replies with the setting still
     present, `status: "OK"`, **`data: null`**, and the **same `checksum`** echoed
     back — return the cached rows. When it **changed**, the setting carries fresh
     `data` + a new `checksum`: update the cache and return the new rows. (Verified
     live — the unchanged signal is `data == null`, NOT the setting being dropped
     from `settings[]`.)
   This makes repeat fetches cheap (no data payload when nothing changed) and is the
   contract the backend is built around — implement it, don't just fetch fresh
   every time. Sketch:
   ```
   resolve(key, version, playerId):
     cached = cache[(key, version)]              # {checksum, rows} or null
     body = { settings: [ { key, version, getDefault: false,
                            checksums: cached ? [cached.checksum] : [] } ],
              playerId }
     resp = POST gate.kinoa.io/featureset/features-configurations (game header)
     s = resp.settings.firstWhere(key, version)
     if s == null or s.status != "OK": return cached?.rows ?? emptyTyped()
     if s.data == null: return cached?.rows ?? emptyTyped()   # unchanged -> cache
     cache[(key, version)] = { checksum: s.checksum, rows: parse(s.data) }
     return cache[(key, version)].rows
   ```
4. **Keep config out of the binary.** The game secret comes from the app's
   existing config/secret mechanism (the same place open-session/events read it) —
   **do not** hardcode it. Read the secret from wherever the app already keeps it.
5. **Map types** schema→language: `integer/long`→int/long, `number`→double/float,
   `boolean`→bool, `string/long_string/version/date/bundle_key`→string,
   `object`→a parsed JSON object/map. Document any lossy mapping in a comment.
6. Save with `Write`. The facade is runtime code — pure of any admin/bearer call.

---

## Phase 5.3 — Sync: stand up schema → setting → configuration

Delegate every call to `kinoa-dashboard-feature-settings`. After each, read the
JSON; if `ok == false`, surface `http_status` + `response` and ask whether to
retry, skip, or stop. Let `H` =
`${CLAUDE_SKILL_DIR}/../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py`.

1. **Schema** (5.1b only — skip if reusing an existing ACTIVE schema):
   ```
   python .../kinoa_csv_schema_infer.py infer --csv <path> --name <SchemaName> --emit body [--type ...] \
     | python "$H" create-schema
   python "$H" publish-schema --schema-id <new_id>
   ```
   (5.1a: if the existing schema was `DRAFT`, publish it now.)
2. **Resolve the latest version** — a configuration binds to a version UUID, not a
   number:
   ```
   python "$H" latest-version --schema-id <schema_id>
   ```
   Capture `schema_version_id` and the human `version` number.
3. **Setting** — binds a runtime key to the schema. Confirm the `key` with the
   developer (default to the schema name; it's what the app passes to the facade):
   ```
   python "$H" create-setting --key <RuntimeKey> --name "<Display name>" --schema-id <schema_id>
   ```
4. **Configuration** — create a **default** DRAFT, then load data:
   ```
   python "$H" create-config --setting-id <setting_id> --schema-id <schema_id> --schema-version-id <version_id> --name "v1 defaults" --default
   python "$H" import-config-data --config-id <config_id> --csv <path>
   ```
   `create-config` fetches the schema to auto-build the required `tableColumns`
   (one per field — the backend rejects a config whose columns don't cover the
   fields) and sends `status DRAFT`. `--default` is the chosen visibility path: the
   config resolves for any player with `getDefault:true`, and a default config needs
   no segmentation to leave DRAFT.
   **Seed data:** 5.1b already has a CSV. For 5.1a (existing schema, no CSV),
   generate a minimal seed CSV — header row = schema field names, one row of
   placeholder values typed per field — show it to the developer to edit, then
   import it. A configuration with no data resolves to empty rows, which makes the
   verification in 5.5 inconclusive.
5. **Submit + publish** — the lifecycle is **DRAFT → IN_REVIEW → SCHEDULED**
   (→ auto-ACTIVE once the start time passes); `/publish` only accepts an
   IN_REVIEW config, so submit first:
   ```
   python "$H" submit-config  --config-id <config_id>   # DRAFT → IN_REVIEW
   python "$H" publish-config --config-id <config_id>    # IN_REVIEW → SCHEDULED
   ```
   (Alternative visibility: instead of `--default`, scope to a specific player with
   `add-test-players --config-id <id> --player-id <id>` before submit/publish; note
   that choice for 5.5. `mark-config-default` is for promoting an *already-published*
   config and rejects a DRAFT — prefer `create-config --default` here.)

Summarize: schema id/status, version, setting key/id, config id/status/default.

---

## Phase 5.4 — Generate the integration report

Produce a self-contained HTML report — durable evidence of what got wired and
whether it resolves end-to-end. Assemble the JSON from data already in hand
(schema/setting/config from 5.3, facade path from 5.2, and the runtime verify
result once 5.5 runs — generate the report *after* 5.5 so the verification block
is populated).

Schema:
```json
{
  "generated_at":  "<ISO 8601 UTC>",
  "game_id":       "<KINOA_GAME_ID>",
  "facade_path":   "<path written in 5.2>",
  "verification":  {"player_id","setting_key","version","runtime_status","resolved","row_count","note"},
  "schema":        {"id","name","status","version","source","fields":[{"name","type","isRequired"}]},
  "setting":       {"id","key","name"},
  "configuration": {"id","name","status","is_default","schema_version","row_count","test_players":[...]},
  "next_steps":    ["..."]
}
```

The `verification` block drives the top callout — green only when a real runtime
fetch returned the config (`resolved` true and `runtime_status == "OK"`). Render:

```bash
echo '<json>' | python "${CLAUDE_SKILL_DIR}/generate_report.py" --output ./kinoa-feature-settings-integration-report-<YYYYMMDD-HHMMSS>.html
```

The script prints `{"ok", "output", "bytes", "opened_in_browser"}` and auto-opens
the file. If `opened_in_browser` is `false` (headless), surface the absolute path.
Suggest adding `kinoa-feature-settings-integration-report-*.html` to `.gitignore`.

---

## Phase 5.5 — Verify end-to-end + cover with tests

The honest proof is: the **previously-created player resolves the configuration
through the same runtime path the app uses** — `gate.kinoa.io/featureset`. Do it twice:
once live (a smoke check), once as a repeatable test in the app's suite with the
HTTP mocked.

### 5.5.1 Live smoke check

Use the real player from open-session (`KINOA_LAST_PLAYER_ID`; mint a fresh UUID
if absent — a published default config resolves for any player):
```
python "$H" get-config --setting-key <RuntimeKey> --version <n> --player-id <player_id>
```
Always pass `--version` — omitting it yields `VERSION_NOT_FOUND`. Do **not** pass
`--get-default` (getDefault is false in normal use). Confirm
`response.settings[0].status == "OK"`, `data` carries the rows, and note the
returned `checksum`. Then prove the checksum delta — repeat the call passing that
checksum:
```
python "$H" get-config --setting-key <RuntimeKey> --version <n> --player-id <player_id> --checksum <checksum>
```
Since nothing changed, the setting comes back with `status:"OK"` and **`data: null`**
(the same `checksum` echoed) — not dropped from `settings[]`. That `data: null` is
the "unchanged" signal the facade's cache relies on.

**Expect a brief propagation lag.** A freshly published config can take a few
seconds before the runtime serves it — the first `get-config` may return
`DEFAULT_NOT_FOUND` even though everything is correct. Retry a few times (a few
seconds apart) before treating it as a failure. To confirm it's only a lag (not a
real misconfig), cross-check with the admin resolve, which bypasses the runtime
cache:
```
python "$H" test-config --config-id <config_id> --player-id <player_id>
```
If `test-config` returns the rows but `get-config` still doesn't, it's the cache —
keep retrying. If `get-config` stays non-OK after the lag, walk the chain:
schema ACTIVE? config went DRAFT→IN_REVIEW→SCHEDULED (submit then publish)? default
(or player a test player)? key + version correct? Record the result for 5.4.

### 5.5.2 Integration test with mocked HTTP

Detect the test framework (`pom.xml`/`build.gradle`→JUnit, `package.json`+jest/
vitest→JS, `pyproject.toml`/`pytest`→pytest, `*.csproj`→xUnit/NUnit, Unity asmdef→
Unity Test Runner). Read one existing test to mirror conventions. If ambiguous,
ask where to place it.

Generate **one** focused test on the `FeatureSettingsFacade` that:

1. **Mocks the runtime HTTP** so the test is deterministic and offline — stub the
   `POST gate.kinoa.io/featureset/features-configurations` response with a canned body
   shaped like the real one (status `OK`, a `data` array of rows matching the
   schema fields). Use the project's usual HTTP-mock (WireMock/MockWebServer,
   `nock`/`msw`, `responses`/`respx`, `HttpMessageHandler` stub, etc.).
2. **Calls the facade** the way an app feature would: `facade.get("<RuntimeKey>", playerId)`.
3. **Asserts** the facade parsed the rows into the typed model — at least one field
   value equals what the mock returned (e.g. `assertEquals(2.5, rows.get(0).reward())`).
   Also assert the request the facade sent carried the `game` header and the right
   `{key, version, playerId}` body with `getDefault:false` — that proves the facade
   builds the call correctly.
4. **Covers the checksum cache** — enqueue a second response in the real
   "nothing changed" shape (the setting present with `status:"OK"`, **`data: null`**,
   and the same `checksum` echoed back), call the facade again, and assert it
   (a) sent the stored `checksum` in the second request's `checksums`, and (b) still
   returned the cached rows. This is the behavior the backend is built around, so
   it's worth pinning.
5. **Prints one line** with the setting key + player id so a failure is traceable.

Skeleton (adapt to the project's framework/language):
```java
// JUnit + MockWebServer example — adapt to the project's conventions.
@Test
void facadeResolvesConfigForPlayerAndCachesByChecksum() throws Exception {
    // 1st fetch: full config + a checksum
    server.enqueue(new MockResponse().setBody("""
      {"settings":[{"request":{"key":"BoostersConfig","version":"1"},"status":"OK",
        "configurationName":"v1 defaults","data":[{"id":1,"reward":2.5}],"checksum":"abc123"}]}"""));
    // 2nd fetch: unchanged → setting present, status OK, data null, same checksum
    server.enqueue(new MockResponse().setBody("""
      {"settings":[{"request":{"key":"BoostersConfig","version":"1"},"status":"OK",
        "data":null,"checksum":"abc123"}]}"""));

    var facade = new FeatureSettingsFacade(server.url("/").toString(), GAME_SECRET);

    List<BoostersRow> first = facade.get("BoostersConfig", "player-123");
    assertEquals(2.5, first.get(0).reward());
    var req1 = server.takeRequest();
    assertNotNull(req1.getHeader("game"));               // game-secret auth, not bearer

    List<BoostersRow> second = facade.get("BoostersConfig", "player-123");
    assertEquals(2.5, second.get(0).reward());           // served from cache, unchanged
    var req2 = server.takeRequest();
    assertTrue(req2.getBody().readUtf8().contains("abc123"));  // sent the stored checksum
}
```

Optionally add a second, **live** test (no mock, real credentials, hitting
`gate.kinoa.io/featureset`) guarded so it's skipped in CI without secrets — it mirrors
5.5.1 but lives in the suite. Keep the mocked test as the primary one: it runs
anywhere and pins the facade's parsing + request shape.

### 5.5.3 Run it

Have the developer run the suite (`mvn test`, `gradle test`, `npm test`, `pytest`,
…). They confirm green here, or paste failures to diagnose. Common ones:

- Mock not intercepting → the facade's base URL isn't injectable; make the host a
  constructor/config param (as in the skeleton) so tests can point it at the mock.
- Live test 401/`KEY_NOT_FOUND` → credentials/visibility, same chain as 5.5.1.
- Rows parse empty → the config had no data (re-check the 5.3 import step).

Then regenerate/finalize the 5.4 report with the verification result filled in.

---

## Reference — endpoints used (via the dashboard helper)

Admin (`https://dashboard.kinoa.io/featuresettingsapi`):
- `GET  /schemas`, `GET /schemas/active/meta`, `GET /schemas/{id}` — list / pick / fetch.
- `POST /schemas` — create (DRAFT). `POST /schemas/{id}/publish` — DRAFT → ACTIVE.
- `POST /settings` — create (key + name + schemaId; no version, no status).
- `POST /configurations` — create (DRAFT; helper auto-builds tableColumns, `--default` sets isDefault). `PUT /configurations/{id}/import` — load CSV data.
- `PATCH /configurations/{id}` status→IN_REVIEW (`submit-config`), then `POST /configurations/{id}/publish` (IN_REVIEW → SCHEDULED → auto-ACTIVE).
- `PATCH /configurations/{id}/mark-as-default` (promote a published config), `POST /configurations/{id}/test-players`, `GET /configurations/{id}/test/{playerId}` — scoped visibility / admin resolve.

Runtime (`https://gate.kinoa.io/featureset`, public game-secret auth — the facade + verify):
- `POST /features-configurations` — body `{settings:[{key,version,getDefault:false,checksums:[…]}], playerId}`; response `settings[].status` ∈ `OK / KEY_NOT_FOUND / VERSION_NOT_FOUND / DEFAULT_NOT_FOUND`, with `data` rows + a `checksum`. Send the client's held checksums; an unchanged config comes back with `status:"OK"` + `data:null` (same checksum echoed → reuse the cache), a changed one with fresh `data` + a new `checksum`. `getDefault` is false in normal use.

Schema column types: `integer, number, long, boolean, string, long_string,
bundle_key, date, enumeration, version, object`.
