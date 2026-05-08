---
name: kinoa-sync-event-integration
description: Synchronize the application's emitted events with Kinoa's game_event registry — the integration/code-side half of the events pair. Discover which events the app code emits, generate a KinoaEvents class mirroring them, then orchestrate a sync against Kinoa (publishing predefined, creating custom) by delegating every admin call to the sibling kinoa-dashboard-event skill. Includes a test scenario verifying events land. Use whenever the user wants to integrate events with Kinoa, set up event tracking in code, generate KinoaEvents, sync game events with the dashboard, or verify event integration end-to-end.
argument-hint: [optional: app source path]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This skill is the **integration / code-side** half of the events pair. It owns the discover → generate → diff → apply → verify workflow but does no admin API calls itself; for every admin call it delegates to the sibling skill `kinoa-dashboard-event` (whose helper `kinoa_dashboard_event.py` wraps the bearer-token API on `dashboard.kinoa.io`). When both skills are installed as siblings under `~/.claude/skills/`, the relative path `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py` resolves correctly.

Requires `KINOA_BEARER_TOKEN`, `KINOA_GAME_ID`, and `KINOA_GAME_SECRET` in `~/.kinoa/session.env`. If any are missing, the dashboard helper returns `error: missing_credentials` — tell the user to set up Kinoa credentials first.

## Security boundary — admin vs runtime

Same rule as for player fields:

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID) | **Skill only.** Delegated to `kinoa-dashboard-event` (CLI: `python ../kinoa-dashboard-event/kinoa_dashboard_event.py ...`) for list, publish, create, and delete operations during the integration session. |
| **Runtime** | `gate.kinoa.io` | `game: <game_secret>` | **App code.** When the application emits an event at runtime, it `POST`s to `gate.kinoa.io/playerevents/api/v3/sync-event` (or the async variant) using the `game` secret. The Postman collection at `../kinoa-api-integration/references/postman-collection.json` is the spec. |

Never emit code into the application that calls `dashboard.kinoa.io` or carries an `Authorization: Bearer` header.

The skill works in four phases. Drive each phase to completion with the developer before moving on.

---

## Phase A — Discover which events the application emits

1. Use `Glob` and `Grep` to scan the project for string literals that match the predefined Kinoa event names. To get the predefined names, run:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-predefined
   ```
   Each element has `id`, `name`, `status`, `activity_status`, and `game_event_parameters` (with `system: true|false` per param).
2. For each predefined `name`, grep the application source tree (`src/`, `app/`, etc., or the path the developer specifies) for occurrences of that name as a string. Record the matches.
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

## Phase B — Generate `KinoaEvents`

1. Propose a path for the new file. Default: same package/directory as the application's existing event-emission code, file name `KinoaEvents.<ext>` matching the language (Java/Kotlin: `KinoaEvents.java`; Python: `kinoa_events.py`; etc.). Confirm with the developer via `AskUserQuestion`.
2. Generate a class/enum/module that lists every event the app emits, alongside its parameter names and kinds. Mirror the application's naming convention.
3. **Pure data class** — no API call code embedded. The application's existing emission code is responsible for shaping the payload onto `gate.kinoa.io/playerevents/api/v3/sync-event` using the game-secret header.
4. Save with `Write`.

---

## Phase C — Sync event definitions with Kinoa

### C.1 Fetch existing event definitions

```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-predefined
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" list-custom
```

Each response is `{ http_status, ok, response: { totalCount, elements: [...] } }`. Important fields per element:

- `id` (UUID), `name`, `type` (`PREDEFINED` or `USER`)
- `status`: `ACTIVE` (published / integrated) or `NOT_IMPLEMENTED` (not yet published).
- `activity_status`: `active` / `inactive` / `unknown`. Reflects whether events are actually being received. Independent from `status` — sometimes events flow in even though the integration definition isn't published yet (a drift state worth surfacing).
- `game_event_parameters`: list of `{id, name, kind, system, extra?}`. `system: true` params come from Kinoa's predefined schema; `system: false` are operator-added custom params.

### C.2 Compute the diff

**Two pre-rules apply before normal classification:**

- **`session_start` handling depends on `SESSION_START_AUTO_FIRES`** (set in Phase A):
  - `True` (app uses the direct `/player/session/start` endpoint) → treat `session_start` as **in app** even if grep didn't find a literal `"session_start"` string. The endpoint emits it server-side. Do not add `session_start` to `KinoaEvents` as a separately-emitted event.
  - `False` (app opens sessions some other way) → treat `session_start` as a **regular event** that the app must emit explicitly after opening a session. Classify it normally (it will typically land in 🟡 Implement+pub if `status == NOT_IMPLEMENTED`).
- **Highly-recommended events.** The set `{watch_ad, install, payment}` is *load-bearing* for Kinoa's calculated properties (ad-revenue analytics, install attribution, monetization / LTV / ARPU). Without these, large parts of the dashboard's analytics simply don't compute. **Mark them with a leading ⭐ in whatever bucket they fall into**, and tell the developer explicitly: *"Without watch_ad / install / payment, Kinoa cannot calculate ad revenue, install attribution, or monetization metrics. These should be prioritized."*

For every predefined event, classify by comparing its `name` to the names the app emits (with the auto-publish rule above applied):

- `status == "ACTIVE"` and **NOT** in app → 🟠 **WARNING** — Kinoa thinks it's integrated but the app code doesn't emit it. Likely stale, or the integration lives elsewhere. Surface for review.
- `status == "ACTIVE"` and **IS** in app → ✅ silent (already integrated).
- `status == "NOT_IMPLEMENTED"` and **IS** in app → 🟢 **READY TO PUBLISH** — call publish.
- `status == "NOT_IMPLEMENTED"` and **NOT** in app → 🟡 **RECOMMEND IMPLEMENTING** — propose adding to `KinoaEvents` and the emission code, then publish.

Also surface the drift case explicitly:

- Any event with `activity_status == "active"` but `status == "NOT_IMPLEMENTED"` → 🟤 **DRIFT** — events are flowing in but the integration is unpublished. Recommend publishing now (the app is already emitting).

For every active **custom (USER)** event whose name is **NOT** in the app → 🟣 **IMPLEMENT EXISTING CUSTOM** — Kinoa already has this user-defined event; the current code base just doesn't emit it yet. Propose adding to `KinoaEvents` and the emission code. No POST needed.

For every event the app emits whose name is **not** in any predefined or active custom list → 🔵 **CREATE CUSTOM** — propose a POST to register a new custom event in Kinoa.

### C.3 Present the checklist — this is the final-list confirmation step

This is where the developer commits to **the canonical list of events the app will emit**. Show a numbered list grouped by severity, **with `⭐ HIGHLY RECOMMENDED` rows pulled to the top** (regardless of bucket) and a one-line callout explaining why they matter:

```
⚠ The events marked ⭐ are required for Kinoa's calculated properties:
  - watch_ad  → ad-revenue analytics
  - install   → install attribution
  - payment   → monetization / LTV / ARPU

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

### C.4 Apply approved actions

Execute in order. After each call, read the JSON; if `ok == false`, surface `http_status` and `response`, then ask whether to retry, skip, or stop.

- 🟢 **Publish** an existing predefined event:
  ```
  python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" publish --event-id <uuid>
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
    python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" publish --event-id <session_start_uuid>
    ```

- 🔁 **`session_start` explicit emit** (when `SESSION_START_AUTO_FIRES == False` — the app opens sessions without hitting the direct endpoint):
  - The app must emit `session_start` like any other event, immediately after its session-open code runs.
  - Treat it as a normal 🟡 implement+publish item: add `session_start` to `KinoaEvents`, wire an emission call site right after the session-open step, then publish:
    ```
    python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" publish --event-id <session_start_uuid>
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
         --name "<event_name>" \
         --param amount:number \
         --param tier:enumeration:bronze,silver,gold
     ```
     Custom events come back with `status: ACTIVE` already (no separate publish).

After the loop completes, summarize: how many published, how many implemented+published, how many created, how many failed.

### C.5 Decide the player_state emission strategy

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

---

## Phase D — Test scenario

The honest test is to run the developer's own code that emits the event (same principle as `kinoa-sync-player-fields-integration` Phase D — the app's runtime is the source of truth for whether parameters are shaped right).

1. Pick one event the developer just published or created.
2. Tell the developer:
   > "Run your code path that emits `<event_name>`. After it fires, come back and confirm here."
3. Verify the event was received by Kinoa:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-event/kinoa_dashboard_event.py" get --event-id <uuid>
   ```
   - `last_event_at` — should be very recent (within seconds of the test fire).
   - `activity_status` — typically transitions to `active` once events are flowing.
4. Optionally also fetch the player's state to confirm any `player_state` updates the event carried:
   ```
   python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-player-fields/kinoa_dashboard_player_fields.py" get-player-state --player-id <test_player>
   ```
5. Report: ✅ confirmed received OR ❌ not received (recommend re-checking the emission code shapes the body correctly — system params at top of `event_data`, custom params nested under `event_data.custom_params`).

If you don't have a way to invoke the app's emission, the skill can do a one-off synthetic send via `kinoa_send_event.py`. Important: when constructing the call, route each parameter using its `system` flag from the event's `game_event_parameters`:

- `system: true` → `--system-param key=value` (lands in `event_data` directly)
- `system: false` → `--param key=value` (lands in `event_data.custom_params`)

```
python "${CLAUDE_SKILL_DIR}/kinoa_send_event.py" \
    --name <event_name> \
    --system-param ad_income=100 --system-param ad_type=interstitial \
    --param my_custom=42
```

Then re-run the `get` to confirm `last_event_at` updated.

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
| `install` | Install attribution, acquisition cohorts |
| `payment` | Monetization metrics (LTV, ARPU, conversion) |

When any of these are not yet integrated, the skill prefixes their checklist row with ⭐ and shows a callout above the checklist explaining the consequence.

### `session_start` — auto-fire vs explicit emit

Two open-session endpoints exist; only the recommended one auto-fires `session_start`:

| Endpoint | Auto-fires `session_start`? | Skill action |
|---|---|---|
| `gate.kinoa.io/playerevents/api/v3/player/session/start` (**recommended / default**) | **Yes** — server emits the event in hidden mode on each open-session POST. | 🔄 Publish only — no `KinoaEvents` entry, no emission site. |
| `gate.kinoa.io/playerevents/api/v3/players/session_start` (legacy — note plural + underscore) | **No** | 🔁 Implement + publish (only if the app doesn't already emit `session_start`) — add to `KinoaEvents`, wire an emission site after the legacy call returns, then publish. |

The decision is made in Phase A. **Default assumption is the recommended endpoint** (`SESSION_START_AUTO_FIRES = True`); the skill only overrides to `False` when grep finds the legacy URL fragment `players/session_start` in the source. `kinoa-open-session` (the debugging helper in this repo) always hits the recommended endpoint, so it consistently demonstrates the auto-fire path.

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

The selected strategy is documented at the top of `KinoaEvents` (see Phase C.5).

For ad-hoc testing from the command line, `kinoa_send_event.py` exposes `--system-param key=value` (top-level `event_data`) and `--param key=value` (nested `event_data.custom_params`) plus `--player-state key=value` (diff-style; the helper does not currently support sending `null` literals — that's a runtime-app concern).
