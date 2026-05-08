# integration-skills

Claude Code sub-skills that integrate a game/application with the **Kinoa** platform — credentials, player-state model, session lifecycle, event registry, verification — driven from inside Claude Code.

## Quick install

```bash
mkdir -p ~/.claude/skills
for d in /Users/illia/IdeaProjects/kinoa-github/integration-skills/*/; do
  base=$(basename "$d")
  case "$base" in *-workspace) continue ;; esac
  ln -sfn "$d" ~/.claude/skills/"$base"
done
```

Restart Claude Code. Walkthrough: [`kinoa-api-integration/HOW-TO.md`](kinoa-api-integration/HOW-TO.md). Dispatcher: [`kinoa-api-integration/SKILL.md`](kinoa-api-integration/SKILL.md).

---

## Architecture

Player-fields and events each split along two axes — a workflow skill (`kinoa-sync-*-integration`) that drives discover → diff → apply → verify but makes no API calls, and a dashboard helper (`kinoa-dashboard-*`) that's a pure admin-API CLI wrapper. Workflows delegate every admin call via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-<X>/kinoa_dashboard_<X>.py`; siblings must be co-installed.

Plus three standalone pieces:

- `kinoa-init` — credential capture + project validation.
- `kinoa-open-session` — runtime helper mirroring `POST /player/session/start` (auto-fires `session_start` server-side).
- `kinoa-api-integration` — orchestrator dispatching `/kinoa-api-integration <subcommand>` (or `all` for end-to-end).

```
kinoa-init                                (Phase 0 — setup)
kinoa-sync-player-fields-integration      (Phase 1 — workflow)  ─┐
kinoa-dashboard-player-fields             (Phase 1 — admin CLI) ─┘ delegates
kinoa-open-session                        (Phase 2 — runtime helper)
kinoa-sync-event-integration              (Phase 3 — workflow + kinoa_send_event.py for Phase D)
kinoa-dashboard-event                     (Phase 3 — admin CLI) ← delegates
kinoa-api-integration                     (orchestrator)
```

## Typical integration flow

1. `/kinoa-init` — capture game ID + tokens, validate against Kinoa admin API.
2. `/kinoa-sync-player-fields-integration` — generate `KinoaPlayerState`, diff vs Kinoa, apply.
3. `/kinoa-open-session` — verify the runtime session-open call.
4. `/kinoa-sync-event-integration` — generate `KinoaEvents`, drive publishes/creations, run Phase D.

Dashboard helpers aren't usually invoked directly during a fresh integration — workflows delegate. Use them directly for one-off admin tasks (e.g., "publish event X" or "delete a stale custom field").

---

## Security boundary (load-bearing)

Two distinct API surfaces. **Mixing them up is a security mistake.**

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both same UUID) | Skill only — `kinoa-init` and `kinoa-dashboard-*` helpers. |
| **Runtime / public** | `gate.kinoa.io`, `pevents.kinoa.io`, `featureset.kinoa.io` | `game: <game_secret>` (no bearer) | App runtime code. [`kinoa-api-integration/references/postman-collection.json`](kinoa-api-integration/references/postman-collection.json) is the canonical spec — public hosts only. |

**Hard rule when generating code into the application** (`KinoaPlayerState`, `KinoaEvents`, etc.): never emit code that calls `dashboard.kinoa.io` or carries `Authorization: Bearer`. The bearer is admin-tier and must not ship in app binaries, configs, or runtime calls. Generated artifacts are **pure data classes** — no API calls embedded. The app's own emission code (or new code following the Postman collection) handles runtime calls with the game-secret header.

---

## Conventions for sub-skills

**Folder layout**: `kinoa-<role>/SKILL.md` (required) plus optional `kinoa_<role>.py`.

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

**Workflow skills follow Phase A → B → C → D**: A discover (Glob/Grep), B generate empty data class, C sync (C.1 fetch defs, C.2 diff, C.3 checklist for approval, C.4 apply, C.5 player_state strategy [events only]), D test against the public API.

**Adding a new sub-skill**: create the folder, decide flavor (workflow / dashboard helper / runtime helper / setup), update the orchestrator's dispatcher table, update [`HOW-TO.md`](kinoa-api-integration/HOW-TO.md) and [`evals.json`](kinoa-api-integration/evals/evals.json), re-run the install loop. Runtime helpers belong **inside** the workflow skill that uses them, not as standalone slash commands (per the consolidation that folded `kinoa-send-event` into `kinoa-sync-event-integration`).

---

## Stored session state

`~/.kinoa/session.env` (mode `0600`) holds:

```
KINOA_INTEGRATION_TYPE  = API   (hardcoded — only supported mode)
KINOA_GAME_ID           = <uuid>
KINOA_GAME_SECRET       = <secret>
KINOA_BEARER_TOKEN      = <jwt — admin auth>
KINOA_LAST_PLAYER_ID    = <set by kinoa-open-session>
KINOA_LAST_SESSION_ID   = <set by kinoa-open-session>
```

Bearer tokens expire (~24h JWT). On a 401 from any admin endpoint, ask the user to grab a fresh bearer from the Kinoa dashboard → Integration menu and re-run `/kinoa-init`.

---

## Domain rules

**Highly-recommended events** — the set `{watch_ad, install, payment}` is required for Kinoa's calculated properties (ad-revenue analytics, install attribution, monetization / LTV / ARPU). The event sync skill flags these with ⭐ in the C.3 checklist regardless of bucket, with a callout explaining the consequence of leaving them unintegrated.

**`session_start` — auto-fire vs explicit emit.** Integration is always **API** mode. Two open-session endpoints exist; only one auto-fires:

| Endpoint | Auto-fires? | `SESSION_START_AUTO_FIRES` | Action |
|---|---|---|---|
| `.../playerevents/api/v3/player/session/start` (**recommended / default**) | Yes (hidden mode) | `True` | 🔄 publish only — no `KinoaEvents` entry, no emission site. |
| `.../playerevents/api/v3/players/session_start` (legacy — plural + underscore) | No | `False` | 🔁 implement + publish (only if app doesn't already emit) — add to `KinoaEvents`, wire emission after the legacy call. |

**Default is `True`.** Phase A does NOT ask the developer up front — it assumes the recommended endpoint and only overrides to `False` when grep finds the legacy URL fragment `players/session_start` in the source. Greenfield projects keep the default.

**`player_state` emission strategy** — every event must include `event.player_state`. Two strategies, picked at C.5:

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

Predefined params (Kinoa marks `system: true`) sit at the top of `event_data`. Operator-added params (`system: false`) nest under `event_data.custom_params`. The local `kinoa_send_event.py` helper (Phase D) exposes both via `--system-param key=value` and `--param key=value`.

---

## Testing

[`kinoa-api-integration/evals/evals.json`](kinoa-api-integration/evals/evals.json) holds the eval cases. Run via the `anthropic-skills:skill-creator` harness (spawns with-skill + baseline subagents per case, generates a review HTML), or invoke any helper directly against a real Kinoa project — every CLI is independently usable. `kinoa-api-integration-workspace/` holds run artifacts; **do not commit it**.

## File index

- [`kinoa-api-integration/SKILL.md`](kinoa-api-integration/SKILL.md) — orchestrator dispatcher
- [`kinoa-api-integration/HOW-TO.md`](kinoa-api-integration/HOW-TO.md) — install, token acquisition, walkthrough
- [`kinoa-api-integration/references/postman-collection.json`](kinoa-api-integration/references/postman-collection.json) — runtime API spec (public hosts only)
- [`kinoa-api-integration/evals/evals.json`](kinoa-api-integration/evals/evals.json) — eval cases
- Each sub-skill's `SKILL.md` documents its specific phases / subcommands / branches
