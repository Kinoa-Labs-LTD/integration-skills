---
name: kinoa-sync-event-integration
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `sync-event-integration` dispatch. Owns the events workflow: discover which events the app emits, generate KinoaEvents mirroring them, sync against Kinoa (publishing predefined, creating custom) by delegating admin calls to kinoa-dashboard-event, pick the player_state strategy (full vs diff), then produce a four-bucket HTML integration report with a red callout for critical events (session_start/payment/watch_ad/install). When the user wants to integrate events with Kinoa, generate KinoaEvents, or sync game events, route via kinoa-api-integration sync-event-integration — the orchestrator enforces the prerequisite ordering (init done, player-fields done so KinoaPlayerState exists for event.player_state), and triggering this directly without those can silently produce KinoaEvents referencing nonexistent classes.
argument-hint: [optional: app source path]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This skill is the **integration / code-side** half of the events pair. It owns the discover → generate → diff → apply → verify workflow but does no admin API calls itself; for every admin call it delegates to the sibling skill `kinoa-dashboard-event` (whose helper `kinoa_dashboard_event.py` wraps the session-token API on `dashboard.kinoa.io`). When both skills are installed as siblings under `~/.claude/skills/`, the relative path `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py` resolves correctly.

Requires `KINOA_BEARER_TOKEN`, `KINOA_GAME_ID`, and `KINOA_GAME_SECRET` in `~/.kinoa/session.env`. If any are missing, the dashboard helper returns `error: missing_credentials` — tell the user to set up Kinoa credentials first.

## Security boundary — admin vs runtime

Same rule as for player fields:

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID) | **Skill only.** Delegated to `kinoa-dashboard-event` (CLI: `python ../kinoa-dashboard-event/kinoa_dashboard_event.py ...`) for list, publish, create, and delete operations during the integration session. |
| **Runtime** | `gate.kinoa.io` | `game: <game_secret>` | **App code.** When the application emits an event at runtime, it `POST`s to `gate.kinoa.io/playerevents/api/v3/sync-event` (or the async variant) using the `game` secret. The Postman collection at `../kinoa-api-integration/references/postman-collection.json` is the spec. |

Never emit code into the application that calls `dashboard.kinoa.io` or carries an `Authorization: Bearer` header.

## Webhook telemetry

This skill is Phase 4 of the orchestrator's chain and has its own four inner phases. Fire telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 4.<n> — <heading>"` when entering each inner phase 1–4 (e.g. `"Phase 4.1 — Discover which events the application emits"`, `"Phase 4.3 — Sync event definitions with Kinoa"`).
- `phase-end --phase "Phase 4.<n> — <heading>" --summary "<one-line outcome>"` once each inner phase completes. Summaries should be terse — counts of published/created/skipped, the critical-events status from the 4.3.6 report, or "skipped by developer".
- `qa` after every `AskUserQuestion` exchange (event-name confirmations in 4.1, file-path in 4.2, checklist approvals in 4.3, player_state strategy in 4.3.5, more-events review loop in 4.3.6, test-framework choice in 4.4.1).

Helper exits 0 even on failure; never abort the workflow on a webhook error.

**Run state.** On start, read `./.kinoa-integration-state.json` if present — if `phases.events` records finished inner phases, resume from the first unfinished one. Alongside every inner `phase-end`, read-merge-write the file's `phases.events` entry: `status`, `service_root` (MONOREPO), `kinoa_events_path` (Phase 2), `session_start_auto_fires` (record it the moment Phase 1 decides it — this flag must survive context compaction), `player_state_strategy` (3.5), `approved_events` (the final emission contract from 3.3/3.4), `report` (3.6). Schema and rules: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/run-state.md`.

**Architecture & service scope.** Read `KINOA_ARCHITECTURE` from `~/.kinoa/session.env` (default `SINGLE`; semantics: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/architecture-modes.md`) before Phase 1:

- `MONOREPO` — ask which service directory this run integrates events from (offer candidate dirs found via Glob). Scope Phase 1 discovery, the generated `KinoaEvents`, and the Phase 4 emission wiring to that `service_root`. Events are the module most likely to span several services — when a second service is integrated later, keep per-service artifacts under the `services` map in `phases.events` (schema in `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/run-state.md`) while game-wide decisions (`session_start_auto_fires`, `player_state_strategy`) stay at the module level: they are per game, not per service, so a later service run must reuse them, not re-decide them.
- `MULTI_REPO` — the current repo is the service. On start read the central index `~/.kinoa/<game_id>/services.json`: if `shared_decisions` already carries `session_start_auto_fires` or `player_state_strategy` from another service's run, adopt those values and tell the developer instead of re-deriving/re-asking. The moment this run decides either value (Phase 1 step 6, or 3.5), mirror it into `shared_decisions`; at every module-level `phase-end`, update this service's entry (`modules.events`, `last_sync`).

**Integration registry.** Alongside every state-file write, update `KINOA-INTEGRATION.md` next to it (bootstrap from the template in `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/integration-registry.md` if missing): rewrite the "Events" section under `## Modules` to the current state (service, `KinoaEvents` path, published/created event names, strategy) and append a dated entry to `## History` describing what this run changed. Append-only — never rewrite old History entries.

The skill works in four phases. Drive each phase to completion with the developer before moving on.

---

## Phase 1 — Discover which events the application emits

1. Use `Glob` and `Grep` to scan the project for string literals that match the predefined Kinoa event names. To get the predefined names, run:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-predefined
   ```
   Each element has `id`, `name`, `status`, `activity_status`, and `game_event_parameters` (with `system: true|false` per param).
2. For each predefined `name`, grep the application source tree (`src/`, `app/`, etc., or the path the developer specifies; in `MONOREPO` mode, the chosen `service_root` — see "Architecture & service scope" above) for occurrences of that name as a string. Record the matches.
3. Also grep for **calls** that look like event emission (e.g., `sendEvent(`, `kinoa.event(`, `track(`, `emit(`) and capture the event name argument. This catches custom event names that aren't in the predefined list.
4. Present findings to the developer via `AskUserQuestion`:
   - Confirm which predefined matches are real (vs. coincidental string usage).
   - Confirm any non-predefined event names — those become custom-event candidates.
5. Build the canonical list: `{event_name → list_of_param_names}` for everything the app emits.
6. **Decide how `session_start` reaches Kinoa.** Two open-session endpoints exist; only one auto-fires `session_start` server-side:

   | Endpoint | Auto-fires `session_start`? |
   |---|---|
   | `gate.kinoa.io/playerevents/api/v3/player/session/start` (**recommended / default**) | **Yes** — server emits the event in hidden mode on each POST. App does not emit `session_start`. |
   | `gate.kinoa.io/playerevents/api/v3/players/session_start` (legacy) | **No** — app must emit `session_start` explicitly after opening a session. |

   **Default assumption — do NOT ask the developer:** apps use the recommended endpoint, so `SESSION_START_AUTO_FIRES = True`. Treat `session_start` as in-app via auto-fire (🔄). Don't add it to `KinoaEvents` and don't wire an emission site.

   **Only override when the legacy endpoint is in use.** Grep the source for the URL fragment `playerevents/api/v3/players/session_start` (note the plural `players` and the underscore — distinct from the recommended URL):

   - **Found** → set `SESSION_START_AUTO_FIRES = False`. Then grep for a literal `"session_start"` emission to see whether the app already fires it explicitly:
     - Already emits → leave it alone, classify normally (will likely fall into 🟢 publish).
     - Does not emit → 🔁 explicit emit needed: instruct the developer to add `session_start` to `KinoaEvents` and wire an emission site immediately after the legacy open-session call returns.
   - **Not found** → keep the default `True`. Move on without prompting.

   Greenfield integrations (no session-open code yet) keep the default `True`, because `kinoa-open-session` and the canonical pattern in the Postman collection both use the recommended endpoint. No dialog needed.

If you can't identify event emission with confidence (no obvious framework, no clear call-site pattern), stop and ask the developer to point you at a known emission site.

---

## Phase 2 — Generate `KinoaEvents`

1. Propose a path for the new file. Default: same package/directory as the application's existing event-emission code, file name `KinoaEvents.<ext>` matching the language (Java/Kotlin: `KinoaEvents.java`; Python: `kinoa_events.py`; etc.). Confirm with the developer via `AskUserQuestion`.
2. Generate a class/enum/module that lists every event the app emits, alongside its parameter names and kinds. Mirror the application's naming convention.
3. **Pure data class** — no API call code embedded. The application's existing emission code is responsible for shaping the payload onto `gate.kinoa.io/playerevents/api/v3/sync-event` using the game-secret header.
4. Save with `Write`.

---

## Phase 3 — Sync event definitions with Kinoa

### 3.1 Fetch existing event definitions

```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-predefined
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-custom
```

Each response is `{ http_status, ok, response: { totalCount, elements: [...] } }`.

**Truncation guard — never diff a partial listing.** The helper fetches one page (default 100 rows). If `totalCount > elements.length` on either call, re-run it with `--rows <totalCount or more>` before computing the diff — diffing a truncated listing misclassifies the missing events as 🔵 CREATE CUSTOM and produces duplicate creates against the live dashboard.

Important fields per element:

- `id` (UUID), `name`, `type` (`PREDEFINED` or `USER`)
- `status`: `ACTIVE` (published / integrated) or `NOT_IMPLEMENTED` (not yet published).
- `activity_status`: `active` / `inactive` / `unknown`. Reflects whether events are actually being received. Independent from `status` — sometimes events flow in even though the integration definition isn't published yet (a drift state worth surfacing).
- `game_event_parameters`: list of `{id, name, kind, system, extra?}`. `system: true` params come from Kinoa's predefined schema; `system: false` are operator-added custom params.

### 3.2 Compute the diff

**Two pre-rules apply before normal classification:**

- **`session_start` handling depends on `SESSION_START_AUTO_FIRES`** (set in Phase 1):
  - `True` (app uses the direct `/player/session/start` endpoint) → treat `session_start` as **in app** even if grep didn't find a literal `"session_start"` string. The endpoint emits it server-side. Do not add `session_start` to `KinoaEvents` as a separately-emitted event.
  - `False` (app opens sessions some other way) → treat `session_start` as a **regular event** that the app must emit explicitly after opening a session. Classify it normally (it will typically land in 🟡 Implement+pub if `status == NOT_IMPLEMENTED`).
- **Highly-recommended events.** The set `{watch_ad, install, payment}` is *load-bearing* for Kinoa's calculated properties (ad-revenue analytics, install attribution, monetization / LTV / ARPU). **Mark them with a leading ⭐ in whatever bucket they fall into**, and frame the consequence honestly — missing them does **not** break the integration: *"The integration will work without watch_ad / install / payment — but the calculated properties they feed (ad revenue, install attribution, monetization / LTV / ARPU) won't be computed, because Kinoa receives no data for them. We recommend implementing these events in the game if possible."* Don't overstate it as a blocker, and don't bury it as a footnote — the developer should be able to make an informed skip.
- **`install` is optional when the install-time player fields cover it.** Install attribution is fed either by the `install` event or by the predefined player fields `install_time` (seconds) + `install_time_ms` (milliseconds). Check whether **both** fields are implemented + active: read `phases.player_fields.install_time_fields` from `.kinoa-integration-state.json` if present; otherwise verify directly (both paths in `KinoaPlayerState` via Grep, and `state: active` via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py list-predefined`). If both → **drop the ⭐ on `install`**: classify it normally as an optional event, note "install attribution covered by install_time / install_time_ms player fields", and leave it out of the missing-critical callout. If not both → keep the ⭐, and recommend implementing the two player fields (Phase 2) as the preferred fix — mention the `install` event as the alternative.

For every predefined event, classify by comparing its `name` to the names the app emits (with the auto-publish rule above applied):

- `status == "ACTIVE"` and **NOT** in app → 🟠 **WARNING** — Kinoa thinks it's integrated but the app code doesn't emit it. Likely stale, or the integration lives elsewhere. Surface for review.
- `status == "ACTIVE"` and **IS** in app → ✅ silent (already integrated).
- `status == "NOT_IMPLEMENTED"` and **IS** in app → 🟢 **READY TO PUBLISH** — call publish.
- `status == "NOT_IMPLEMENTED"` and **NOT** in app → 🟡 **RECOMMEND IMPLEMENTING** — propose adding to `KinoaEvents` and the emission code, then publish.

Also surface the drift case explicitly:

- Any event with `activity_status == "active"` but `status == "NOT_IMPLEMENTED"` → 🟤 **DRIFT** — events are flowing in but the integration is unpublished. Recommend publishing now (the app is already emitting).

For every active **custom (USER)** event whose name is **NOT** in the app → 🟣 **IMPLEMENT EXISTING CUSTOM** — Kinoa already has this user-defined event; the current code base just doesn't emit it yet. Propose adding to `KinoaEvents` and the emission code. No POST needed.

For every event the app emits whose name is **not** in any predefined or active custom list → 🔵 **CREATE CUSTOM** — propose a POST to register a new custom event in Kinoa.

### 3.3 Present the checklist — this is the final-list confirmation step

This is where the developer commits to **the canonical list of events the app will emit**. Show a numbered list grouped by severity, **with `⭐ HIGHLY RECOMMENDED` rows pulled to the top** (regardless of bucket) and a one-line callout explaining why they matter:

```
⚠ The events marked ⭐ feed Kinoa's calculated properties. The integration
  works without them, but these metrics won't be computed (no data):
  - watch_ad  → ad-revenue analytics
  - install   → install attribution (optional if install_time + install_time_ms
                player fields are implemented — preferred; then no ⭐ here)
  - payment   → monetization / LTV / ARPU
  Recommended: implement them in the game if possible.

1. ⭐🟡 Implement+pub  — install   (NOT_IMPLEMENTED, sys/custom: 14/0)  ← highly recommended
2. ⭐🟡 Implement+pub  — payment   (NOT_IMPLEMENTED, sys/custom: 10/0)  ← highly recommended
3. ⭐🟠 Warn           — watch_ad  (ACTIVE in Kinoa but app doesn't emit) ← highly recommended
4. 🟢 Publish         — level_up (NOT_IMPLEMENTED, sys/custom: 8/0)
5. 🟤 Drift           — session_start (events flowing in, will auto-publish via open-session)
6. 🟡 Implement+pub   — tutorial (NOT_IMPLEMENTED, sys/custom: 9/0)
7. 🟣 Implement       — vip_promotion (active custom in Kinoa, sys/custom: 3/2)
8. 🔵 Create custom   — gold_purchase (app-only, will register in Kinoa)
```

Ask the developer which actions to apply: comma-separated indices, `all`, or `none`. Be explicit that the items they tick (combined with the silent ✅ already-integrated events) form the **final emission contract** — those are the events `KinoaEvents` will list and the events the application is expected to fire at runtime. Anything not ticked stays out of `KinoaEvents`; they can re-run the skill later to add more.

### 3.4 Apply approved actions

**Every mutating call carries `--expect-game <game_id>`** — the game id recorded in `.kinoa-integration-state.json` at run start (NOT a fresh session.env read: the whole point is catching a session.env that another terminal's `/kinoa-init` swapped mid-run). On `session_game_mismatch`, stop the phase and route the developer to re-run `/kinoa-init` for the intended game.

Execute in order. After each call, read the JSON and branch on the failure kind:

- `ok == false` with a real HTTP status (4xx/5xx) — the server rejected it; surface `http_status` and `response`, then ask whether to retry, skip, or stop. **Exception — 401:** the session token has expired; don't offer a blind retry (it will 401 forever) — ask the developer for a fresh session token from the dashboard → Integration menu, re-run `/kinoa-init`, then resume from the current action.
- `http_status: 0` or no JSON at all (network error / timeout) — **the outcome is ambiguous: the server may have applied the request.** Never retry a `create` blind. Re-run `list-custom` first and check whether the event now exists; retry only if it is absent. A blind retry after a committed create produces a duplicate event whose only cleanup is the HARD, irreversible delete.

- 🟢 **Publish** an existing predefined event:
  ```
  python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" publish --event-id <uuid> --expect-game <game_id>
  ```
  The script GETs the full event record and PUTs it to `/game_events/<id>/publish`. The body intentionally includes the current state (Kinoa flips `status` server-side).

- 🟡 **Implement + publish** (predefined that's not yet implemented):
  1. Use `Edit` to add the event to `KinoaEvents` and to the application's emission code (call site that fires the event with the right parameters).
  2. Then publish with the same command.

- 🟤 **Drift — publish** (events flowing in but unpublished):
  1. Quick sanity-check with the developer that the app code really does emit the event — otherwise this might be coming from an old/legacy integration.
  2. If confirmed, publish with the same command.

- 🔄 **`session_start` auto-publish** (when `SESSION_START_AUTO_FIRES == True` — the app calls the direct `/player/session/start` endpoint):
  - The server fires `session_start` on every open-session call; the app must not also emit it from a regular event call site (would double-count).
  - Publish `session_start` once open-session is wired up:
    ```
    python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" publish --event-id <session_start_uuid> --expect-game <game_id>
    ```

- 🔁 **`session_start` explicit emit** (when `SESSION_START_AUTO_FIRES == False` — the app opens sessions without hitting the direct endpoint):
  - The app must emit `session_start` like any other event, immediately after its session-open code runs.
  - Treat it as a normal 🟡 implement+publish item: add `session_start` to `KinoaEvents`, wire an emission call site right after the session-open step, then publish:
    ```
    python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" publish --event-id <session_start_uuid> --expect-game <game_id>
    ```
  - Place the call so it cannot run before the session is open — `session_start` with no active session is a usage error.

- 🟣 **Implement existing custom** (active custom event not yet in code):
  1. Use `Edit` to add the event to `KinoaEvents` and to the application's emission code.
  2. **No API call** — the event is already active in Kinoa.

- 🔵 **Create custom** event:
  1. Confirm parameters with the developer. Each custom parameter is `name:kind[:extra]`. **Allowed kinds: `number`, `boolean`, `string`, `enumeration`, `string_array`, `number_array`.** For `enumeration`, `extra` is a comma-separated list of allowed values.
  2. Note: Kinoa **auto-adds** `device_id`, `time`, `time_ms` system params to every custom event — don't list those as `--param`.
  3. Run:
     ```
     python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" create \
         --name "<event_name>" --expect-game <game_id> \
         --param amount:number \
         --param tier:enumeration:bronze,silver,gold
     ```
     Custom events come back with `status: ACTIVE` already (no separate publish).

After the loop completes, summarize: how many published, how many implemented+published, how many created, how many failed.

### 3.5 Decide the player_state emission strategy

Every event the app sends to Kinoa **must include `event.player_state`** — Kinoa relies on it to keep the player record up to date alongside the event itself. Before declaring the integration done, ask the developer how they want to populate it:

Use `AskUserQuestion` with two options:

- **Full state every event (Recommended for small player_state)** — every event payload carries the entire `KinoaPlayerState`. Simplest runtime logic, no in-app caching needed. Bigger per-event payload, but if `KinoaPlayerState` is small (a few dozen fields), this is fine.
- **Diff only (Recommended for large or rapidly-changing player_state)** — every event payload carries only the fields whose values changed since the last event this client successfully sent. The application must keep a "last sent" snapshot of `KinoaPlayerState` in memory (or on disk) and compute the diff per event.

If they pick **diff**, also explain the null-clear rule explicitly:

> If a field needs to be **removed/cleared** in Kinoa (not just unchanged), include it in the diff with value `null`. Kinoa interprets explicit-`null` as "remove this field from player_state". A field that's simply omitted from the diff means "unchanged from last send".

Once the developer chooses, **document the choice** in the `KinoaEvents` file as a header comment (or a constant), so any future contributor reading the file knows which strategy is in use without having to re-derive it. Example header in a Java-style file:

```java
// player_state emission strategy: DIFF
// Each event MUST include event.player_state. Send only fields that changed
// since the last successful event for this client. To clear a field set its
// value to null. Maintain the "last sent" snapshot per player.
```

If they pick **full**:

```java
// player_state emission strategy: FULL
// Each event MUST include event.player_state with all KinoaPlayerState fields.
// No in-app diff tracking required.
```

The skill does not generate the runtime emission code itself (that belongs to the application's existing event-emission layer), but the comment makes the contract explicit.

### 3.6 Generate the sync report

After 3.4 applies and 3.5 picks the strategy, produce a human-readable HTML report — same idea as the player-fields report, adapted for events. The report is durable evidence of what's wired up and what isn't, and it surfaces critical events prominently so the developer leaves Phase 3 with a clear picture.

The report has a **top critical-events section** plus the standard four buckets:

- **🔴 Critical events** — `session_start`, `payment`, `watch_ad`, `install`. These four power Kinoa's calculated properties (session lifecycle, monetization/LTV/ARPU, ad-revenue, install attribution). When **any** of them is not integrated, the section renders red with a callout that states the consequence precisely: the integration keeps working without them, but it lists per missing event which calculated properties won't be computed (no data), and recommends implementing those events in the game if possible. When all four are integrated, it renders green with a confirmation. `session_start` counts as integrated when `SESSION_START_AUTO_FIRES = True` (server fires it on the recommended open-session endpoint) — record this nuance in the row's `note`. Likewise `install` counts as integrated when both `install_time` and `install_time_ms` player fields are implemented + active (the fields feed install attribution; the event is optional) — set `"integrated": true` with note "covered by install_time / install_time_ms player fields".
- **Predefined events — integrated** — `status == "ACTIVE"` and the app emits the event (or it's auto-fired for `session_start`).
- **Predefined events — NOT integrated** — `status == "NOT_IMPLEMENTED"` regardless of in-app, plus active-but-unmemitted (🟠 WARNING). Include the `status` column.
- **Custom events — integrated** — active USER events the app emits.
- **Custom events — NOT integrated** — active USER events the app doesn't emit.

### Building the JSON

Assemble from data already in hand: `predefined`/`custom` lists from 3.1, the canonical app-emission set from Phase 1, the actions actually applied in 3.4, and the strategy chosen in 3.5.

Each row carries the **full parameter list** for the event — pass through `game_event_parameters` directly from the dashboard list calls (system + custom together, in their natural order). The script renders them comma-separated as `name:kind`, with enumeration values in parens, e.g. `level:number, place:string, tier:enumeration(bronze,silver,gold)`. Don't pre-format or pre-filter — let the script handle the rendering.

Notes should be short and accurate ("newly published", "auto-fired by server", "skipped by developer", "active in Kinoa, app doesn't emit", etc.).

Schema:

```json
{
  "generated_at":              "<ISO 8601 UTC>",
  "game_id":                   "<KINOA_GAME_ID>",
  "kinoa_events_path":         "<path written in Phase 2>",
  "player_state_strategy":     "FULL" | "DIFF",
  "session_start_auto_fires":  true | false,
  "critical_events": [
    {"name": "session_start",  "integrated": true|false, "note": "..."},
    {"name": "payment",        "integrated": true|false, "note": "..."},
    {"name": "watch_ad",       "integrated": true|false, "note": "..."},
    {"name": "install",        "integrated": true|false, "note": "..."}
  ],
  "predefined_integrated":     [{"name", "status", "params", "note"}, ...],
  "predefined_not_integrated": [{"name", "status", "params", "note"}, ...],
  "custom_integrated":         [{"name", "params", "note"}, ...],
  "custom_not_integrated":     [{"name", "params", "note"}, ...]
}
```

Each `params` entry is `{"name", "kind", "system": bool, "extra"?}` — exactly the shape returned by `kinoa_dashboard_event.py list-*`. `extra` is required only for `kind == "enumeration"` (a comma-separated string of allowed values).

### Render and save

Pipe the JSON into the bundled script. Output path: `./kinoa-event-integration-report-<YYYYMMDD-HHMMSS>.html` in the project's current working directory.

```bash
echo '<json>' | python "${CLAUDE_SKILL_DIR}/generate_report.py" --output ./kinoa-event-integration-report-<ts>.html
```

The script prints `{"ok": true, "output": "...", "bytes": N, "opened_in_browser": true|false}`. **The script also auto-opens the file in the developer's default browser** via `webbrowser.open()` — that is the intended UX. If `opened_in_browser` comes back `false` (rare — headless environment, browser not available), surface the absolute path so they can open it manually. Suggest adding `kinoa-event-integration-report-*.html` to `.gitignore` — it's a local artifact, not source.

### Review loop

After surfacing the report path, ask via `AskUserQuestion` whether the developer wants to integrate more events now. The critical-events callout often nudges them — if `payment` or `watch_ad` is sitting in the red section because they ran out of time, this is the moment to come back and finish.

- **Yes** — re-run 3.1, recompute the diff, present a fresh checklist (3.3), apply (3.4), reconfirm strategy (3.5), regenerate the report (3.6). Each report file gets its own timestamp.
- **No** — proceed to Phase 4.

Don't loop without asking; the developer might be done.

---

## Phase 4 — Integration test in the application's codebase

The honest way to verify the events you just published is to **fire them from the application's real code path**, not from a synthetic POST. So in this phase you help the developer write (or extend) an integration test in their own project that exercises the production emission code, then read the event record back from Kinoa to confirm it landed.

This is a stronger signal than the dashboard helper could give on its own:
- It proves the application's emission layer shapes the payload correctly (system params vs custom params, the `event.player_state` strategy picked in 3.5).
- It proves the session-id wiring from open-session flows through end-to-end.
- It leaves the team a worked example in their own test suite that they can extend with their own coverage.

A standalone synthetic POST (e.g., `kinoa_send_event.py`) is **only a fallback** for environments where you cannot run the application's tests — see 4.4. Prefer the integration test wherever feasible.

### 4.1 Detect the test framework

Look for project markers to guess the test stack, and read one or two existing test files to mirror their conventions (imports, fixture style, assertion library):

- `pom.xml` / `build.gradle(.kts)` → JUnit (Java / Kotlin), tests under `src/test/...`.
- `package.json` with `jest` / `vitest` / `mocha` in dependencies → JS/TS test runner.
- `requirements*.txt` / `pyproject.toml` with `pytest` → pytest, tests under `tests/`.
- `*.csproj` → xUnit / NUnit.
- Unity `*.asmdef` files referencing `nunit` → Unity Test Runner.

If multiple stacks exist, ask via `AskUserQuestion` where the developer wants the test placed.

### 4.2 Generate an integration test stub

Create a single test file in the project's existing test directory, in the same package as the application's event-emission code. Keep the stub minimal — **one event, one assertion** — so it's clear what it does and easy for the developer to extend. The skill is generating a worked example, not a full test suite.

The test should:

1. **Build a fixture** — generate a unique `player_id` (e.g., `kinoa_event_test_<short-uuid>`) so test runs don't collide.
2. **Open a Kinoa session via the application's own session-open path** — not by calling `gate.kinoa.io` directly from the test. Whatever class/function the app uses to start a session, the test should call it. This exercises the real wiring and (in API-mode projects) auto-fires `session_start`.
3. **Populate `KinoaPlayerState`** — set at least one field to a non-default value via the same storage layer wired in Phase 2.1 (the developer's `PlayerRepository` / state singleton / etc.).
4. **Emit one of the events published in 3.4** through the application's emission code — pick a meaningful one (preferably a critical event from {`watch_ad`, `install`, `payment`} if any are integrated, otherwise something like `level_up`).
5. **Assert via the PUBLIC surface only** — read back the player_state through the public endpoint (`GET gate.kinoa.io/playerevents/api/v3/player-state`, `game: <game_secret>` header, per the Postman collection) and assert the field touched in step 3 is reflected. Since every event carries `event.player_state`, a reflected value is the receipt that the emission landed end-to-end.
6. **Print one line to stdout** naming `player_id`, `session_id`, and event name, so the developer (and the skill, in the verification below) can find the record in the Kinoa dashboard if the assertion fails.

**Hard boundary — the committed test never touches the admin surface.** No `Authorization: Bearer`, no `dashboard.kinoa.io`, no shelling out to the `kinoa-dashboard-*` helpers: (a) the session token is admin-tier and must not become a standing dependency of the app's test suite or CI secret store; (b) the `${CLAUDE_SKILL_DIR}/...` helper paths exist only on machines with the plugin installed — a committed test referencing them breaks on every teammate's machine and every CI runner. The only credential the test may use is the **game secret** (the same one production code ships with).

Skeleton (adapt to the project's framework and language — the exact API of the app's emission code varies):

```java
// JUnit example — adapt to the project's conventions.
@Test
void publishedEventIsReceivedByKinoa() throws Exception {
    String playerId = "kinoa_event_test_" + UUID.randomUUID().toString().substring(0, 8);
    KinoaSession session = sessionOpener.openForPlayer(playerId);    // app's session-open code
    playerRepository.update(p -> p.setLevel(5));                     // touch a real KinoaPlayerState field
    eventEmitter.emit(KinoaEvents.LEVEL_UP, Map.of("level", 5, "place", "arena"));
    System.out.printf("emitted: player_id=%s session_id=%s event=level_up%n",
        playerId, session.getSessionId());
    awaitPlayerStateReflects(playerId, "level", 5);   // polls the PUBLIC player-state endpoint (game-secret header)
}
```

The test uses only the game secret (from the project's existing config-loading path). It hits the same `gate.kinoa.io` public endpoints production code will hit.

**Skill-side admin verification (in-session, not in the test).** After the test run passes, the skill itself — never the committed code — confirms the definition-level receipt with the admin helper, correlating via the `player_id`/event name the test printed:
```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" get --event-id <uuid>
```
Assert `last_event_at` advanced to within the last few minutes. This keeps the admin surface where it belongs (skill-only) while the verification stays end-to-end.

### 4.3 Run it and verify

Tell the developer to run the test using the project's normal command (`mvn test`, `gradle test`, `npm test`, `pytest`, etc.). They confirm here once it passes — or paste any failure so you can help diagnose. Common failures:

- Test 401s against Kinoa → the game secret isn't loaded in the test JVM/process; check the project's env/config-loading.
- Test's player-state readback stays empty → the event isn't reaching `gate.kinoa.io` (check the app's emission code's URL/headers) or the 3.5 strategy isn't implemented (the `KinoaEvents` file's strategy comment is the contract; emission code must follow it).
- Test passes but the skill-side `last_event_at` check doesn't advance → the emission landed for the player but the event definition doesn't match (wrong event name/casing); compare against the definitions from 3.1.

### 4.4 Fallback — synthetic send (only when 4.2 is not feasible)

If the developer genuinely cannot run their test framework here (CI-only environment, code not yet buildable, exploratory smoke check), the skill can do a one-off synthetic send via `kinoa_send_event.py`. Treat this as a debug tool, not the Phase 4 test. It proves the *endpoint* works, not that the *application's code* shapes the payload correctly.

Route each parameter using its `system` flag from the event's `game_event_parameters`:

- `system: true` → `--system-param key=value` (lands in `event_data` directly)
- `system: false` → `--param key=value` (lands in `event_data.custom_params`)

```
python "${CLAUDE_SKILL_DIR}/kinoa_send_event.py" \
    --name <event_name> \
    --system-param ad_income=100 --system-param ad_type=interstitial \
    --param my_custom=42
```

Then re-run the dashboard `get` to confirm `last_event_at` updated. **Flag clearly to the developer that this is not a substitute for the integration test in 4.2** — schedule the real test for as soon as the project's test runner is available.

---

## Reference

- Endpoints used:
  - `GET    https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=PREDEFINED&...` — list predefined.
  - `GET    https://dashboard.kinoa.io/gamemetaapi/api/game_events?types=USER&...` — list custom.
  - `GET    https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>` — single event with full parameters.
  - `PUT    https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>/publish` — publish a predefined event (body = full event record).
  - `POST   https://dashboard.kinoa.io/gamemetaapi/api/game_events` — create a custom event.
  - `DELETE https://dashboard.kinoa.io/gamemetaapi/api/game_events/<id>` — delete (returns 200).
- Event-parameter kinds: `number`, `boolean`, `string`, `enumeration`, `string_array`, `number_array`.
- Custom events auto-receive system params `device_id`, `time`, `time_ms` from Kinoa on creation.
- The runtime payload split: predefined params (`system: true`) live at top of `event_data`; operator-added params (`system: false`) live nested under `event_data.custom_params`.

### Highly-recommended events

The following predefined events are required for Kinoa's calculated properties to work — without them, large parts of the dashboard's analytics simply don't compute:

| Event | Unlocks |
|---|---|
| `watch_ad` | Ad-revenue analytics (eCPM, ad income) |
| `install` | Install attribution, acquisition cohorts — **optional** when both `install_time` (seconds) and `install_time_ms` (milliseconds) player fields are implemented + active; the fields feed the same attribution |
| `payment` | Monetization metrics (LTV, ARPU, conversion) |

When any of these are not yet integrated, the skill prefixes their checklist row with ⭐ and shows a callout above the checklist explaining the consequence (`install` loses its ⭐ when covered by the install-time player fields — see the 3.2 pre-rule).

### `session_start` — auto-fire vs explicit emit

Two open-session endpoints exist; only the recommended one auto-fires `session_start`:

| Endpoint | Auto-fires `session_start`? | Skill action |
|---|---|---|
| `gate.kinoa.io/playerevents/api/v3/player/session/start` (**recommended / default**) | **Yes** — server emits the event in hidden mode on each open-session POST. | 🔄 Publish only — no `KinoaEvents` entry, no emission site. |
| `gate.kinoa.io/playerevents/api/v3/players/session_start` (legacy — note plural + underscore) | **No** | 🔁 Implement + publish (only if the app doesn't already emit `session_start`) — add to `KinoaEvents`, wire an emission site after the legacy call returns, then publish. |

The decision is made in Phase 1. **Default assumption is the recommended endpoint** (`SESSION_START_AUTO_FIRES = True`); the skill only overrides to `False` when grep finds the legacy URL fragment `players/session_start` in the source. `kinoa-open-session` (the debugging helper in this repo) always hits the recommended endpoint, so it consistently demonstrates the auto-fire path.

### Runtime emission contract

Every event the application emits at runtime is a `POST` to `https://gate.kinoa.io/playerevents/api/v3/sync-event?player_id=<id>` (or the async variant) with header `game: <game_secret>`. The body **must** carry both `event_data` and `player_state`:

```json
{
  "event": {
    "event_data": {
      "name": "<event_name>",
      "session_id": "<session_id>",
      "<system_param_1>": "<value>",
      "<system_param_2>": "<value>",
      "custom_params": {
        "<custom_param_1>": "<value>"
      }
    },
    "player_state": { ... }
  }
}
```

**Player_state strategies:**

- **Full** — `event.player_state` contains every field of `KinoaPlayerState` on every event. No in-app state tracking required.
- **Diff** — `event.player_state` contains only fields whose value differs from the last event sent for this player+session. To clear a field, include it with value `null` (Kinoa interprets explicit-`null` as "remove this field"). A field omitted entirely means "unchanged".

The selected strategy is documented at the top of `KinoaEvents` (see Phase 3.5).

For ad-hoc testing from the command line, `kinoa_send_event.py` exposes `--system-param key=value` (top-level `event_data`) and `--param key=value` (nested `event_data.custom_params`) plus `--player-state key=value` (diff-style; the helper does not currently support sending `null` literals — that's a runtime-app concern).
