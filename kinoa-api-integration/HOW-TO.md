# kinoa-api-integration — Setup Guide

## Layout

```
integration-skills/
├── kinoa-api-integration/                       ← orchestrator (this folder)
│   ├── SKILL.md
│   ├── HOW-TO.md                                ← you are here
│   ├── evals/
│   └── references/
├── kinoa-init/                                  ← Phase 0 (self-contained)
│   ├── SKILL.md
│   └── kinoa_init.py
├── kinoa-sync-player-fields-integration/        ← Phase 1 workflow (no helper)
│   └── SKILL.md   ← delegates admin calls to kinoa-dashboard-player-fields
├── kinoa-dashboard-player-fields/               ← admin CLI wrapper for Phase 1
│   ├── SKILL.md
│   └── kinoa_dashboard_player_fields.py
├── kinoa-open-session/                          ← Phase 2 (self-contained)
│   ├── SKILL.md
│   └── kinoa_open_session.py
├── kinoa-sync-event-integration/                ← Phase 3 workflow (with local runtime helper)
│   ├── SKILL.md   ← delegates admin calls to kinoa-dashboard-event
│   └── kinoa_send_event.py   ← runtime test helper used by Phase D (mirrors what the app does at runtime)
└── kinoa-dashboard-event/                       ← admin CLI wrapper for Phase 3
    ├── SKILL.md
    └── kinoa_dashboard_event.py
```

The split between `*-integration` (workflow) and `kinoa-dashboard-*` (admin CLI wrapper) keeps each role single-purpose: the integration skill owns the discover→diff→apply prompts, the dashboard skill owns one HTTP call per subcommand. Integration skills delegate admin calls via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-*/...`, so both must be installed as siblings.

Each sub-skill ships its own Python helper and has no cross-skill imports — you can install one sub-skill in isolation if a future skill only needs that one piece. The orchestrator skill bundles the four together for convenience but is not required for the sub-skills to work on their own.

## Install all four skills globally

From the repo root:

```bash
mkdir -p ~/.claude/skills
for d in /Users/illia/IdeaProjects/kinoa-github/integration-skills/*/; do
  ln -sf "$d" ~/.claude/skills/$(basename "$d")
done
```

Adjust the source path if your checkout lives elsewhere. Restart Claude Code; the seven skills become available as slash commands in any project: `/kinoa-api-integration`, `/kinoa-init`, `/kinoa-sync-player-fields-integration`, `/kinoa-dashboard-player-fields`, `/kinoa-open-session`, `/kinoa-sync-event-integration`, `/kinoa-dashboard-event`.

To verify:

```bash
ls -la ~/.claude/skills/ | grep kinoa
```

To remove (symlinks only — originals untouched):

```bash
ls ~/.claude/skills/ | grep '^kinoa-' | xargs -I{} rm ~/.claude/skills/{}
```

## Endpoint classification (security boundary)

These skills talk to **two distinct surfaces**. Mixing them up is a security mistake.

| Surface | Host | Auth header | Who calls it |
|---|---|---|---|
| **Admin / dashboard** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game-Id: <uuid>` | **Skill only**, during integration setup. Used by `kinoa-init` (validate project) and the dashboard helpers (`kinoa-dashboard-player-fields`, `kinoa-dashboard-event`) which the workflow skills (`kinoa-sync-*-integration`) delegate to. The bearer token is admin-tier and must never ship in application binaries, configs, or runtime calls. |
| **Public Player Events API** | `gate.kinoa.io`, `pevents.kinoa.io`, `featureset.kinoa.io` | `game: <game_secret>` (no bearer) | **Application runtime code.** Open session, send events, read player state. The Postman collection at `references/postman-collection.json` is the canonical spec — it deliberately contains only public hosts. |

When `kinoa-sync-player-fields-integration` writes code into your application (e.g., `KinoaPlayerState`), or `kinoa-sync-event-integration` writes `KinoaEvents`, the result is a pure data class. The application's existing integration code is responsible for the runtime API calls using the game-secret header.

## Get your two tokens

Both tokens come from the **Integration** screen in the Kinoa dashboard.

1. Log in at <https://dashboard.kinoa.io>.
2. In the left sidebar, click **Integration**.
3. Copy:
   - **Game secret** — used as the `game` header on the public Player Events API. Identifies your game to `gate.kinoa.io`.
   - **Bearer token** — used as `Authorization: Bearer …` against `dashboard.kinoa.io/gamemetaapi/api/game-settings`. Identifies your project for admin actions.

Keep both private — they grant write access to your Kinoa project.

## First run

In any Claude Code session:

```
/kinoa-api-integration init
```

(or call the sub-skill directly with `/kinoa-init`.)

The skill prompts for four values:

- **integration type** — `API` or `SDK` (the mode this project uses).
- **game ID** — internal game UUID (from the Kinoa dashboard URL when viewing the project).
- **game secret** — public Player Events API auth.
- **bearer token** — admin API auth.

It then validates them by calling `GET dashboard.kinoa.io/gamemetaapi/api/game-settings`. On success it writes the values to `~/.kinoa/session.env` (mode `0600`); every other Kinoa skill (`/kinoa-sync-player-fields-integration`, `/kinoa-dashboard-player-fields`, `/kinoa-open-session`, `/kinoa-sync-event-integration`, `/kinoa-dashboard-event`) reads from that file automatically.

If your project's `integration_type` doesn't match the one you requested, the skill offers to switch it for you (`POST` to the same endpoint with `{"integrationType": "<your choice>"}`).

## Where credentials live

- **`~/.kinoa/session.env`** — `KEY=VALUE` lines, owned by you, mode `0600`. The Python helper loads it at import time so every subcommand sees the same values.
- The skill never writes to `~/.zshrc` or any other shell config. After `init`, the skill prints `export …` lines you can paste into any external shell that needs the same credentials.

## Resetting

To clear the saved credentials:

```bash
rm ~/.kinoa/session.env
```

Re-run `/kinoa-init` to set them again.
