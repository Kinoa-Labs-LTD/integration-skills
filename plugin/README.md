# integration-skills

Claude Code sub-skills that integrate a game or application with the **[Kinoa](https://kinoa.io)** platform — credentials, player-state model, session lifecycle, event registry, feature settings, and verification — driven entirely from inside Claude Code.

There are two consumption modes:

- **API integration** — the app talks to Kinoa's public API directly. Full onboarding workflows generate data classes, sync definitions to the dashboard, and verify end-to-end.
- **SDK dashboard sync** — the game is integrated via the Kinoa Unity SDK; these skills only mirror its entities onto the Dashboard. No app code is generated or touched.

> **Not** a general analytics integration. This is Kinoa-specific and does not cover Mixpanel, Amplitude, GameAnalytics, etc.

---

## What's in the box

This repo doubles as a **Claude Code plugin marketplace** ([`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)) exposing a single plugin — **`kinoa-dashboard`** — that bundles every skill under [`skills/`](skills/). Installing the plugin makes all 13 skills available at once.

---

## Install

### Recommended — plugin marketplace

```bash
claude plugin marketplace add Kinoa-Labs-LTD/integration-skills   # or /plugin marketplace add … in-session
claude plugin install kinoa-dashboard@kinoa
```

Plugin-installed skills are invoked **namespaced**:

```
/kinoa-dashboard:kinoa-api-integration
/kinoa-dashboard:kinoa-sdk-dashboard-sync
/kinoa-dashboard:kinoa-init
…
```

Notes:

- **Auto-update is off by default.** A CLI add registers the marketplace with auto-update disabled (third-party default). Turn it on via `/plugin` → **Marketplaces** → `kinoa` → **Enable auto-update**, or add `"autoUpdate": true` to the `kinoa` entry under `extraKnownMarketplaces` in `~/.claude/settings.json`. With it on, every session start re-fetches the plugin to the latest `main` commit.
- **No version field — every commit is a version.** The plugin manifest sets no `version`; the commit SHA doubles as the integrity checksum. Marketplaces registered with `autoUpdate: true` pull the latest `main` on session start.
- **Private-repo access** for auto-update uses `GITHUB_TOKEN` / `GH_TOKEN`.
- **Pre-wiring game projects:** a game project can pre-register the marketplace via its own `.claude/settings.json` → `extraKnownMarketplaces` (with `"autoUpdate": true`) + `enabledPlugins`.

### Alternative — legacy symlink install

For setups without the plugin system. Run from the repo root of this checkout (`$PWD` must be absolute — symlink targets need it):

```bash
mkdir -p ~/.claude/skills
for d in "$PWD"/skills/*/; do
  ln -sfn "$d" ~/.claude/skills/"$(basename "$d")"
done
```

Restart Claude Code after either method.

Full walkthrough (token acquisition, layout, troubleshooting): [`skills/kinoa-api-integration/HOW-TO.md`](skills/kinoa-api-integration/HOW-TO.md).

---

## Quick start

### API integration (typical flow)

```
/kinoa-api-integration all      # runs the full sequence, or run each phase individually:
```

1. `/kinoa-init` — capture game ID + tokens, validate against the Kinoa admin API.
2. `/kinoa-sync-player-fields-integration` — generate `KinoaPlayerState`, diff vs Kinoa, apply.
3. `/kinoa-open-session` — verify the runtime session-open call.
4. `/kinoa-sync-event-integration` — generate `KinoaEvents`, drive publishes/creations, verify.
5. `/kinoa-sync-feature-settings-integration` *(optional)* — build/activate a schema, create a setting + config, generate a `FeatureSettingsFacade`, verify a player resolves the config at runtime.
6. `/kinoa-sync-resource-template-integration` *(optional)* — discover sellable / prize items, confirm them on an interactive page, register as resource templates, generate `KinoaResources`, verify.

### SDK dashboard sync

For games integrated via the Kinoa Unity SDK. The `/kinoa` SDK skill writes a `kinoa-dashboard-manifest.json` at the game project root; then:

```
/kinoa-sdk-dashboard-sync
```

It mirrors the manifest's events and player fields onto the Dashboard — never generates app code, never deletes dashboard entities.

---

## Skills reference

The 13 skills split by **flavor**: an **orchestrator** dispatches; **workflow** skills (`kinoa-sync-*`) drive discover → generate → sync → verify but make no API calls; **dashboard helpers** (`kinoa-dashboard-*`) are pure admin-API CLI wrappers; plus **utility**, **runtime**, and **setup** pieces.

| Skill | Flavor | Purpose |
|---|---|---|
| [`kinoa-api-integration`](skills/kinoa-api-integration/) | Orchestrator | API-mode entry point. Dispatches subcommands, or `all` for the full onboarding sequence. |
| [`kinoa-sdk-dashboard-sync`](skills/kinoa-sdk-dashboard-sync/) | Orchestrator (SDK) | SDK-mode entry point. Consumes `kinoa-dashboard-manifest.json`, plans a diff, mirrors events + player fields to the Dashboard. |
| [`kinoa-init`](skills/kinoa-init/) | Setup | Capture game UUID / secret / session token, persist to `~/.kinoa/session.env`, validate against the admin API. |
| [`kinoa-sync-player-fields-integration`](skills/kinoa-sync-player-fields-integration/) | Workflow | Discover the app's player class, generate `KinoaPlayerState`, sync player fields, emit an HTML report. |
| [`kinoa-dashboard-player-fields`](skills/kinoa-dashboard-player-fields/) | Dashboard helper | Admin CLI for `player_field` definitions + the public get-player-state read. |
| [`kinoa-open-session`](skills/kinoa-open-session/) | Runtime | Open/verify a player session; auto-fires `session_start` server-side; persists last session/player id. |
| [`kinoa-sync-event-integration`](skills/kinoa-sync-event-integration/) | Workflow | Discover emitted events, generate `KinoaEvents`, sync (publish predefined / create custom), pick player_state strategy, emit report. |
| [`kinoa-dashboard-event`](skills/kinoa-dashboard-event/) | Dashboard helper | Admin CLI for `game_event` definitions (list, get, publish, create, add-params, delete). |
| [`kinoa-sync-feature-settings-integration`](skills/kinoa-sync-feature-settings-integration/) | Workflow | Build/activate a schema, create setting + config, generate `FeatureSettingsFacade`, verify runtime resolution. |
| [`kinoa-dashboard-feature-settings`](skills/kinoa-dashboard-feature-settings/) | Dashboard helper | Admin CLI for schemas / settings / configurations + the public features-configurations read. |
| [`kinoa-sync-resource-template-integration`](skills/kinoa-sync-resource-template-integration/) | Workflow | Discover sellable / prize items (resources — not currency), confirm them on an interactive HTML page, register as resource templates (create DRAFT → activate), generate `KinoaResources`, verify. |
| [`kinoa-dashboard-resource-template`](skills/kinoa-dashboard-resource-template/) | Dashboard helper | Admin CLI for resource-template definitions (list, get, create, update, activate, deprecate, clone, delete — HARD + DRAFT-only). |
| [`kinoa-csv-schema-infer`](skills/kinoa-csv-schema-infer/) | Utility | Pure parser: CSV header + samples → a Kinoa feature-schema (`SchemaDto`). No network, no credentials. |

Dashboard helpers aren't usually invoked directly during a fresh integration — the workflows delegate to them. Use them directly for one-off admin tasks ("publish event X", "delete a stale custom field", "publish a configuration").

---

## Architecture

Player-fields, events, feature-settings, and resources each split along **two axes**:

- a **workflow skill** (`kinoa-sync-*-integration`) that drives discover → generate → sync → verify but makes **no API calls**, and
- a **dashboard helper** (`kinoa-dashboard-<X>`) that is a pure admin-API CLI wrapper.

Workflows delegate every admin call to their sibling helper via `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-<X>/kinoa_dashboard_<X>.py`, so siblings must be co-installed (the plugin ships the whole `skills/` tree together, so this always holds).

**Python helpers are self-contained** — no cross-skill imports, no shared library. Boilerplate is deliberately duplicated so any sub-skill can be installed in isolation. Each helper auto-loads `~/.kinoa/session.env` at import; each subcommand makes one HTTP call and prints one JSON object. HTTP errors are serialized to stdout, never raised.

**Architecture modes** (`kinoa-init` asks up front, persists `KINOA_ARCHITECTURE`): **SINGLE** (one app), **MONOREPO** (services under one root; each workflow scopes to its `service_root`), **MULTI_REPO** (each service is its own checkout; state + registry per repo, mirrored to a machine-local central index).

For the canonical, load-bearing details see [`CLAUDE.md`](CLAUDE.md) and [`skills/kinoa-api-integration/SKILL.md`](skills/kinoa-api-integration/SKILL.md).

---

## Security boundary (load-bearing)

There are **two distinct API surfaces**. Mixing them up is a security mistake.

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `dashboard.kinoa.io`; **also** `gate.kinoa.io/bundle` (resource templates) | `Authorization: Bearer <token>` + `Game` / `Game-Id` headers | Skills only — `kinoa-init` and the `kinoa-dashboard-*` helpers. |
| **Runtime / public** | `gate.kinoa.io`, `pevents.kinoa.io`, `gate.kinoa.io/featureset`, `gate.kinoa.io/bundle/public/*` | `game: <game_secret>` (no bearer) | App runtime code, incl. the generated `FeatureSettingsFacade`. |

> **`gate.kinoa.io` hosts both surfaces for the bundles service.** The resource-template *admin* routes (`gate.kinoa.io/bundle/resource-templates`) are bearer-secured and skill-only; the *public* routes (`gate.kinoa.io/bundle/public/...`) use the game secret. What makes a call admin is the **bearer token**, not the host — so the hard rule below applies to bundle admin calls too.

**Hard rule when generating code into the application** (`KinoaPlayerState`, `KinoaEvents`, …): never emit code that calls `dashboard.kinoa.io` or carries `Authorization: Bearer`. The session token is admin-tier and must not ship in app binaries, configs, or runtime calls. Generated artifacts are **pure data classes** — no embedded API calls. The one exception is the generated `FeatureSettingsFacade`, which makes a runtime call with the **game-secret** header only.

Canonical runtime API spec: [`skills/kinoa-api-integration/references/postman-collection.json`](skills/kinoa-api-integration/references/postman-collection.json) (public hosts only).

---

## Stored state

- **`~/.kinoa/session.env`** (mode `0600`) — integration type, architecture, game id/secret, bearer token, last player/session id. Session tokens are ~24h JWTs; on a 401 from an admin endpoint, grab a fresh token from the dashboard and re-run `/kinoa-init`.
- **`.kinoa-integration-state.json`** (per project/monorepo root) — machine-readable run state and decisions. Resumes an interrupted or compacted session. Suggest `.gitignore`-ing it.
- **`KINOA-INTEGRATION.md`** — human-readable integration registry, **committed to git**: which modules are integrated, from which service, with which artifacts, plus an append-only `## History` log.

---

## Development & testing

**Unit tests (offline)** — from the repo root, no credentials or network:

```bash
python -m unittest discover tests
```

Covers the helper CLIs and the sync planner with mocked HTTP. Run after any change to a `kinoa_*.py` helper.

**Evals (skill behavior)** — cases live in [`skills/kinoa-api-integration/evals/evals.json`](skills/kinoa-api-integration/evals/evals.json). Run via the `skill-creator` harness, or invoke any helper directly against a real Kinoa project — every CLI is independently usable.

Run-artifact directories (`kinoa-api-integration-workspace/`, `kinoa-sdk-dashboard-sync-workspace/`) are gitignored — **do not commit them**.

---

## Reference

- [`CLAUDE.md`](CLAUDE.md) — canonical, load-bearing rules for the whole repo
- [`skills/kinoa-api-integration/SKILL.md`](skills/kinoa-api-integration/SKILL.md) — API-mode orchestrator dispatcher
- [`skills/kinoa-sdk-dashboard-sync/SKILL.md`](skills/kinoa-sdk-dashboard-sync/SKILL.md) — SDK-mode dashboard sync
- [`skills/kinoa-api-integration/HOW-TO.md`](skills/kinoa-api-integration/HOW-TO.md) — install, token acquisition, walkthrough
- [`skills/kinoa-api-integration/references/postman-collection.json`](skills/kinoa-api-integration/references/postman-collection.json) — runtime API spec
- Each sub-skill's own `SKILL.md` documents its specific phases / subcommands / branches

---

*License: UNLICENSED — © Kinoa Labs LTD.*
