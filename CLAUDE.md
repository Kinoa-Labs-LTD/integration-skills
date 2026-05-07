# integration-skills

Claude Code sub-skills that integrate a game/application's code with the **Kinoa** platform — credential setup, player-state model sync, session lifecycle, event registry, and verification — driven from inside Claude Code.

## Quick install

```bash
mkdir -p ~/.claude/skills
for d in /Users/illia/IdeaProjects/kinoa-github/integration-skills/*/; do
  base=$(basename "$d")
  case "$base" in *-workspace) continue ;; esac
  ln -sfn "$d" ~/.claude/skills/"$base"
done
```

Restart Claude Code. Full walkthrough: [`kinoa-api-integration/HOW-TO.md`](kinoa-api-integration/HOW-TO.md). End-to-end dispatcher reference: [`kinoa-api-integration/SKILL.md`](kinoa-api-integration/SKILL.md).

---

## Architecture (two-axis split)

For both player fields and events, the work splits along two axes:

| Axis | Folder pattern | What it does |
|---|---|---|
| **Workflow** | `kinoa-sync-*-integration` | Multi-phase orchestration: discover app code → generate `KinoaPlayerState` / `KinoaEvents` → diff against Kinoa state → apply approved actions → verify. **Makes no API calls itself** — delegates every admin call to its sibling dashboard helper. |
| **Dashboard helper** | `kinoa-dashboard-*` | Pure admin-API CLI wrapper. One HTTP call per subcommand. Used by the workflow skill above; also independently invokable for one-off admin tasks. |

Cross-skill delegation: workflow skills invoke their helper via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-<X>/kinoa_dashboard_<X>.py`. This works as long as sibling skills are co-installed (the install loop enforces it).

Plus three standalone pieces:

- `kinoa-init` — one-shot credential capture + project validation.
- `kinoa-open-session` — runtime helper mirroring `POST /player/session/start`. Used to verify the open-session call works against a real project; the developer also implements this in their own app code (it auto-fires `session_start` server-side).
- `kinoa-api-integration` — orchestrator that dispatches `/kinoa-api-integration <subcommand>` to the matching sub-skill.

The 7 sub-skills together:

```
kinoa-init                                (Phase 0 — setup)
kinoa-sync-player-fields-integration      (Phase 1 — workflow)  ─┐
kinoa-dashboard-player-fields             (Phase 1 — admin CLI) ─┘ delegates to
kinoa-open-session                        (Phase 2 — runtime helper)
kinoa-sync-event-integration              (Phase 3 — workflow + local kinoa_send_event.py for Phase D)
kinoa-dashboard-event                     (Phase 3 — admin CLI) ← delegates to
kinoa-api-integration                     (orchestrator, no helper)
```

## Typical integration flow

1. `/kinoa-init` — capture integration type + game ID + tokens, validate against Kinoa admin API.
2. `/kinoa-sync-player-fields-integration` — generate `KinoaPlayerState`, diff app fields against Kinoa, drive activations / creations / verification.
3. `/kinoa-open-session` — verify the runtime session-open call. The developer also implements this in app code; doing so auto-fires `session_start`.
4. `/kinoa-sync-event-integration` — generate `KinoaEvents`, drive publishes / creations of game-event defs, run Phase D verification (uses local `kinoa_send_event.py` to fire a test event).

The dashboard helpers (`kinoa-dashboard-player-fields`, `kinoa-dashboard-event`) usually aren't invoked directly during a fresh integration — the workflow skills above delegate to them. Use them directly for one-off admin tasks (e.g., "publish event X by id" or "delete a stale custom field").

---

## Security boundary (load-bearing rule)

Two distinct API surfaces. **Mixing them up is a security mistake.**

| Surface | Host | Auth | Who calls it |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game-Id: <uuid>` | **Skill only**, during integration sessions. Lives in `kinoa-init` and the `kinoa-dashboard-*` helpers. |
| **Runtime / public** | `gate.kinoa.io`, `pevents.kinoa.io`, `featureset.kinoa.io` | `game: <game_secret>` (no bearer) | **Application runtime code.** [`kinoa-api-integration/references/postman-collection.json`](kinoa-api-integration/references/postman-collection.json) is the canonical spec — it intentionally contains only public hosts. |

**Hard rule when the skill generates code into the application** (`KinoaPlayerState`, `KinoaEvents`, etc.): never emit code that calls `dashboard.kinoa.io` or carries an `Authorization: Bearer` header. The bearer is admin-tier and must not ship in application binaries, configs, or runtime calls.

Generated artifacts should be **pure data classes** — no Kinoa API calls embedded. The application's existing emission code (or new code following the Postman collection) is responsible for runtime API calls using the game-secret header.

---

## Conventions for sub-skills

### Folder layout

```
kinoa-<role>/
├── SKILL.md             (required)
└── kinoa_<role>.py      (optional helper)
```

### SKILL.md frontmatter

```yaml
---
name: kinoa-<role>
description: <one paragraph — what it does AND when it should trigger; this is the primary triggering signal>
argument-hint: [<expected args>]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---
```

### Python helper conventions

Every helper is **self-contained** — no imports from sibling skill folders, no shared library. Boilerplate (`_load_session_env`, `_request`, `_parse_json`, `_parse_kv_pairs`) is **deliberately duplicated** across scripts; that's the price of letting any sub-skill be installed in isolation. Don't extract a shared module.

Standard shape:
- Auto-loads `~/.kinoa/session.env` at module import (populates `os.environ`).
- Each subcommand takes flags, makes one HTTP call, prints exactly one JSON object on stdout: `{ http_status, ok, response | request_body, …context }`.
- HTTP errors are caught and serialized to JSON — never raised onto stdout.
- Argparse `prog=` matches the script filename.

### Workflow skills

Workflow SKILL.md files follow a consistent **Phase A → B → C → D** structure:

- **Phase A — Discover** the application's relevant entities (player class, emitted events). Glob/Grep over the source tree.
- **Phase B — Generate** the data class (`KinoaPlayerState` or `KinoaEvents`) starting empty.
- **Phase C — Sync with Kinoa.** Subdivides as: C.1 fetch existing defs (predefined + custom), C.2 compute diff (multi-bucket matrix), C.3 present checklist for developer approval (this IS the final-list confirmation step), C.4 apply approved actions, C.5 (events only) ask about `player_state` emission strategy.
- **Phase D — Test.** The honest test is having the developer run their own app code; the skill verifies via the public API.

### Adding a new sub-skill

1. Create `kinoa-<role>/` with `SKILL.md` (and a Python helper if needed).
2. Decide its flavor: workflow (`*-integration`), dashboard helper (`kinoa-dashboard-*`), runtime helper, or one-off setup.
3. **Runtime helpers should live inside the workflow skill that uses them**, not as standalone slash commands (per the consolidation decision that folded `kinoa-send-event` into `kinoa-sync-event-integration`).
4. Update the orchestrator [`kinoa-api-integration/SKILL.md`](kinoa-api-integration/SKILL.md): dispatcher table, dispatch list, end-to-end flow.
5. Update [`kinoa-api-integration/HOW-TO.md`](kinoa-api-integration/HOW-TO.md): layout diagram.
6. Update [`kinoa-api-integration/evals/evals.json`](kinoa-api-integration/evals/evals.json): add an eval case.
7. Re-run the install loop (or manually `ln -sfn`) to symlink the new sub-skill into `~/.claude/skills/`.

---

## Stored session state

`~/.kinoa/session.env` (mode `0600`) holds:

```
KINOA_INTEGRATION_TYPE  = API | SDK
KINOA_GAME_ID           = <uuid>
KINOA_GAME_SECRET       = <secret>
KINOA_BEARER_TOKEN      = <jwt — admin auth>
KINOA_LAST_PLAYER_ID    = <set by kinoa-open-session>
KINOA_LAST_SESSION_ID   = <set by kinoa-open-session>
```

Bearer tokens expire (~24h JWT). On a 401 from any admin endpoint, ask the user to grab a fresh bearer from Kinoa dashboard → Integration menu and re-run `/kinoa-init`.

---

## Domain rules baked into the skills

### Highly-recommended events

The set `{watch_ad, install, payment}` is **required for Kinoa's calculated properties** to work (ad-revenue analytics, install attribution, monetization / LTV / ARPU). The event sync skill flags these with ⭐ in the C.3 checklist regardless of which diff bucket they fall into, with a callout explaining the consequence of leaving them unintegrated.

### `session_start` auto-fires

`POST .../playerevents/api/v3/player/session/start` (the open-session endpoint) emits the `session_start` event server-side. The event sync skill's Phase A detects whether open-session is implemented in the app code (greps for the URL or SDK markers); if so, treats `session_start` as in-app and uses a dedicated 🔄 auto-publish action — the developer never adds `session_start` as a separate emission site.

### `player_state` emission strategy

Every event the app emits to Kinoa **must** include `event.player_state`. Two strategies, chosen at sync-event-integration Phase C.5:

- **Full** — every event carries the entire `KinoaPlayerState`. Simpler runtime, larger payloads.
- **Diff** — only fields whose value changed since the last successfully sent event. To **clear** a field, include it with value `null` (Kinoa interprets explicit-`null` as "remove"). Field omitted entirely = unchanged. Requires the app to maintain a "last sent" snapshot per player.

The chosen strategy is documented as a header comment in the generated `KinoaEvents` file so future contributors don't have to re-derive it.

### Runtime emission contract

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

Predefined params (where Kinoa marks `system: true`) live at the top of `event_data`. Operator-added params (`system: false`) live nested under `event_data.custom_params`. The local `kinoa_send_event.py` helper (used by Phase D) exposes both via `--system-param key=value` and `--param key=value`.

---

## Testing

[`kinoa-api-integration/evals/evals.json`](kinoa-api-integration/evals/evals.json) holds 6 eval cases covering the integration workflow. To run:

1. Use the `anthropic-skills:skill-creator` skill's harness (spawns one with-skill subagent + one baseline subagent per case, generates a static review HTML viewer).
2. Or invoke any helper directly against a real Kinoa project — every CLI is independently usable.

`kinoa-api-integration-workspace/` holds eval run artifacts (timing, outputs, generated review.html). **Do not commit it.** Add to `.gitignore` when initializing the repo.

---

## File index

- [`kinoa-api-integration/SKILL.md`](kinoa-api-integration/SKILL.md) — orchestrator dispatcher
- [`kinoa-api-integration/HOW-TO.md`](kinoa-api-integration/HOW-TO.md) — install, token acquisition, end-to-end walkthrough
- [`kinoa-api-integration/references/postman-collection.json`](kinoa-api-integration/references/postman-collection.json) — runtime API spec (public hosts only)
- [`kinoa-api-integration/evals/evals.json`](kinoa-api-integration/evals/evals.json) — eval cases
- Each sub-skill's own `SKILL.md` documents its specific phases / subcommands / branches
