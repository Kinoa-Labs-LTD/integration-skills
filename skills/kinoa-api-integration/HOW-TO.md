# kinoa-api-integration — Setup Guide

## Layout

```
integration-skills/
├── kinoa-api-integration/                       ← orchestrator (this folder)
│   ├── SKILL.md
│   ├── HOW-TO.md                                ← you are here
│   ├── evals/
│   └── references/
├── kinoa-init/                                  ← Phase 1 (self-contained)
│   ├── SKILL.md
│   └── kinoa_init.py
├── kinoa-sync-player-fields-integration/        ← Phase 2 workflow (no helper)
│   └── SKILL.md   ← delegates admin calls to kinoa-dashboard-player-fields
├── kinoa-dashboard-player-fields/               ← admin CLI wrapper for Phase 2
│   ├── SKILL.md
│   └── kinoa_dashboard_player_fields.py
├── kinoa-open-session/                          ← Phase 3 (self-contained)
│   ├── SKILL.md
│   └── kinoa_open_session.py
├── kinoa-sync-event-integration/                ← Phase 4 workflow (with local runtime helper)
│   ├── SKILL.md   ← delegates admin calls to kinoa-dashboard-event
│   └── kinoa_send_event.py   ← runtime test helper used by Phase 4 (mirrors what the app does at runtime)
├── kinoa-dashboard-event/                       ← admin CLI wrapper for Phase 4
│   ├── SKILL.md
│   └── kinoa_dashboard_event.py
├── kinoa-sync-feature-settings-integration/     ← Phase 5 workflow (optional; with HTML report)
│   ├── SKILL.md   ← delegates admin calls to kinoa-dashboard-feature-settings, CSV inference to kinoa-csv-schema-infer
│   └── generate_report.py
├── kinoa-dashboard-feature-settings/            ← admin CLI wrapper for Phase 5 (schemas/settings/configs + runtime get-config)
│   ├── SKILL.md
│   └── kinoa_dashboard_feature_settings.py
└── kinoa-csv-schema-infer/                       ← utility — CSV → feature-schema type inference (no API)
    ├── SKILL.md
    └── kinoa_csv_schema_infer.py
```

The split between `*-integration` (workflow) and `kinoa-dashboard-*` (admin CLI wrapper) keeps each role single-purpose: the integration skill owns the discover→diff→apply prompts, the dashboard skill owns one HTTP call per subcommand. Integration skills delegate admin calls via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-*/...`, so both must be installed as siblings.

Each sub-skill ships its own Python helper and has no cross-skill imports — you can install one sub-skill in isolation if a future skill only needs that one piece. The orchestrator skill bundles them together for convenience but is not required for the sub-skills to work on their own.

## Install all skills globally

**Recommended — register via the project's `.claude/settings.json`** (the only way auto-update is ON from the start; Claude Code prompts to add the marketplace and install the plugin on the next session in that project):

```json
{
  "extraKnownMarketplaces": {
    "kinoa": {
      "source": { "source": "github", "repo": "Kinoa-Labs-LTD/integration-skills" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": { "kinoa-dashboard@kinoa": true }
}
```

**Quick CLI alternative** — registers the marketplace **without** auto-update (third-party marketplaces default to off):

```bash
claude plugin marketplace add Kinoa-Labs-LTD/integration-skills
claude plugin install kinoa-dashboard@kinoa
```

After a CLI add, enable updates via `/plugin` → **Marketplaces** → `kinoa` → **Enable auto-update**.

Plugin-installed skills are namespaced: `/kinoa-dashboard:kinoa-api-integration`, `/kinoa-dashboard:kinoa-init`, etc.

**Alternative — symlinks.** From the repo root (it must be your working directory — `$PWD` becomes the absolute symlink target):

```bash
mkdir -p ~/.claude/skills
for d in "$PWD"/skills/*/; do
  ln -sfn "$d" ~/.claude/skills/"$(basename "$d")"
done
```

Restart Claude Code; the skills become available as slash commands in any project: `/kinoa-api-integration`, `/kinoa-init`, `/kinoa-sync-player-fields-integration`, `/kinoa-dashboard-player-fields`, `/kinoa-open-session`, `/kinoa-sync-event-integration`, `/kinoa-dashboard-event`, `/kinoa-sync-feature-settings-integration`, `/kinoa-dashboard-feature-settings`, `/kinoa-csv-schema-infer`.

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
| **Admin / dashboard** | `dashboard.kinoa.io` | `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same UUID) | **Skill only**, during integration setup. Used by `kinoa-init` (validate project) and the dashboard helpers (`kinoa-dashboard-player-fields`, `kinoa-dashboard-event`) which the workflow skills (`kinoa-sync-*-integration`) delegate to. The session token is admin-tier and must never ship in application binaries, configs, or runtime calls. |
| **Public Player Events API** | `gate.kinoa.io`, `pevents.kinoa.io`, `gate.kinoa.io/featureset` | `game: <game_secret>` (no bearer) | **Application runtime code.** Open session, send events, read player state. The Postman collection at `references/postman-collection.json` is the canonical spec — it deliberately contains only public hosts. |

When `kinoa-sync-player-fields-integration` writes code into your application (e.g., `KinoaPlayerState`), or `kinoa-sync-event-integration` writes `KinoaEvents`, the result is a pure data class. The application's existing integration code is responsible for the runtime API calls using the game-secret header.

## Get your two tokens

Both tokens come from the **Integration** screen in the Kinoa dashboard.

1. Log in at <https://dashboard.kinoa.io>.
2. In the left sidebar, click **Integration**.
3. Copy:
   - **Game secret** — used as the `game` header on the public Player Events API. Identifies your game to `gate.kinoa.io`.
   - **Session token** — used as `Authorization: Bearer …` against `dashboard.kinoa.io/gamemetaapi/api/game-settings`. Identifies your project for admin actions.

Keep both private — they grant write access to your Kinoa project.

## First run

In any Claude Code session:

```
/kinoa-api-integration init
```

(or call the sub-skill directly with `/kinoa-init`.)

The skill prompts for three values (integration type is always `API` — hardcoded, no longer asked):

- **game ID** — internal game UUID (from the Kinoa dashboard URL when viewing the project).
- **game secret** — public Player Events API auth.
- **session token** — admin API auth.

It then validates them by calling `GET dashboard.kinoa.io/gamemetaapi/api/game-settings`. On success it writes the values to `~/.kinoa/session.env` (mode `0600`); every other Kinoa skill (`/kinoa-sync-player-fields-integration`, `/kinoa-dashboard-player-fields`, `/kinoa-open-session`, `/kinoa-sync-event-integration`, `/kinoa-dashboard-event`) reads from that file automatically.

If your project's `integration_type` is not `API`, the skill offers to switch it for you (`POST` to the same endpoint with `{"integrationType": "API"}`).

## Where credentials live

- **`~/.kinoa/session.env`** — `KEY=VALUE` lines, owned by you, mode `0600`. The Python helper loads it at import time so every subcommand sees the same values.
- The skill never writes to `~/.zshrc` or any other shell config. After `init`, the skill prints `export …` lines you can paste into any external shell that needs the same credentials.

## Resetting

To clear the saved credentials:

```bash
rm ~/.kinoa/session.env
```

Re-run `/kinoa-init` to set them again.
