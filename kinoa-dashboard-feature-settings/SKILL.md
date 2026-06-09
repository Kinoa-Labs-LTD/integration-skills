---
name: kinoa-dashboard-feature-settings
description: Pure admin-API wrapper for the Kinoa feature-settings domain on the dashboard side — schemas, settings, and configurations — plus the public runtime read used for verification. List/get/create/publish schemas, resolve a schema's latest version, create settings that bind a runtime key to a schema, create configurations and import their CSV data, mark-as-default, publish, manage test players, and run the public features-configurations fetch for a player. Use whenever the user wants to inspect or directly manipulate feature-settings definitions (schemas/settings/configurations) in the Kinoa dashboard without the full integration workflow. The orchestration skill kinoa-sync-feature-settings-integration delegates to this skill for all dashboard operations.
argument-hint: [list-schemas | get-schema | latest-version | create-schema | publish-schema | create-setting | create-config | import-config-data | mark-config-default | publish-config | add-test-players | test-config | get-config | ...] [args]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

# Kinoa Dashboard — Feature Settings

A thin, self-contained CLI over the Kinoa **feature-settings** admin API
(`dashboard.kinoa.io/featuresettingsapi`), plus the one public runtime read on
`featureset.kinoa.io`. Every subcommand makes one HTTP call and prints one JSON
object: `{ http_status, ok, response | request_body, …context }`. HTTP errors are
serialized, never raised — so the caller can branch on `ok`/`http_status`.

This skill holds **no workflow logic**. It's the admin surface that
`kinoa-sync-feature-settings-integration` (Phase 5) delegates to. It's also handy
on its own for one-off admin tasks ("create a schema", "publish that config",
"check what player X resolves").

## The three resources

Feature settings stack up in a fixed shape — internalize it before touching the
commands, because every argument follows from it:

```
SCHEMA  (typed columns, status DRAFT→ACTIVE)
  └─ VERSION  (version "1", "2", … — newest = largest number; has tableFields[])
SETTING (key + name, binds ONE schema by schemaId; no version, no status)
  └─ CONFIGURATION (data rows for ONE schema version; lifecycle DRAFT→IN_REVIEW→SCHEDULED→ACTIVE)
```

At runtime the app asks for a **setting `key`** + a **schema `version` number**
and gets back the matching configuration's data. So the chain to a working
runtime read is: create+publish a schema → create a setting on it → create a
configuration (bound to a version), load its data, publish it → fetch by key.

## Auth boundary (load-bearing)

| Surface | Host | Auth |
|---|---|---|
| Admin (every subcommand except `get-config`) | `dashboard.kinoa.io/featuresettingsapi` | `Authorization: Bearer` + `Game` + `Game-Id` |
| Runtime (`get-config` only) | `featureset.kinoa.io` | `game: <game_secret>` (no bearer) |

`get-config` deliberately uses the public game-secret auth because it exercises
the exact path the shipped application uses. Never emit bearer-carrying code into
an application — that's an admin token.

## Setup

The helper auto-loads `~/.kinoa/session.env`. Run `/kinoa-init` first. A `401`
from an admin call means the session token expired (~24h) — re-run `/kinoa-init`
with a fresh token.

```bash
python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_feature_settings.py" <subcommand> [args]
```

## Subcommands

### Schemas
| Command | Call | Notes |
|---|---|---|
| `list-schemas [--rows N]` | `GET /schemas` | summaries |
| `active-schemas-meta` | `GET /schemas/active/meta` | id+name of ACTIVE schemas — use to let a user pick |
| `get-schema --schema-id ID` | `GET /schemas/{id}` | full record incl. `versions[].tableFields` |
| `latest-version --schema-id ID` | derived | prints `{schema_version_id, version}` — the newest version (max numeric `version`); this is what a configuration binds to |
| `create-schema …` | `POST /schemas` | creates a **DRAFT**; see below |
| `publish-schema --schema-id ID` | `POST /schemas/{id}/publish` | DRAFT → ACTIVE |

**Creating a schema** — two forms:

- *Full body* (preferred in the workflow): pipe a complete `SchemaDto` produced by
  `kinoa-csv-schema-infer` into `--body-file` or stdin.
  ```bash
  python .../kinoa_csv_schema_infer.py infer --csv boosters.csv --name BoostersConfig \
    | python .../kinoa_dashboard_feature_settings.py create-schema
  ```
- *Inline* (quick manual use): give `--name` plus a `tableFields` array. `order`,
  `level` (default 1), and `isRequired` (default true) are filled in for you.
  ```bash
  python .../kinoa_dashboard_feature_settings.py create-schema --name BoostersConfig \
    --fields-json '[{"name":"id","type":"integer"},{"name":"label","type":"string"}]'
  ```

Column types: `integer, number, long, boolean, string, long_string, bundle_key,
date, enumeration, version, object`.

### Settings
| Command | Call | Notes |
|---|---|---|
| `list-settings [--rows N]` | `GET /settings` | |
| `get-setting --setting-id ID` | `GET /settings/{id}` | |
| `create-setting --key K --name N --schema-id ID [--description D]` | `POST /settings` | `key` is the runtime lookup key (e.g. `BoostersConfig`); the setting holds only `schemaId` — no version, no status |

### Configurations
| Command | Call | Notes |
|---|---|---|
| `list-configs --setting-id ID` | `GET /settings/{id}/configurations` | |
| `get-configuration --config-id ID` | `GET /configurations/{id}` | |
| `create-config --setting-id ID --schema-id ID --schema-version-id ID --name N [--default] [--priority N]` | `POST /configurations` | creates a **DRAFT** with no data; auto-builds the required `tableColumns` (one per schema field) and sends `status DRAFT`; `--default` makes it resolve for any player; ids come from `get-schema` / `latest-version` |
| `import-config-data --config-id ID --csv PATH` | `PUT /configurations/{id}/import` | multipart CSV upload; header row must match the schema field names |
| `submit-config --config-id ID` | `PATCH …` status→`IN_REVIEW` | required before publish — lifecycle is **DRAFT → IN_REVIEW → SCHEDULED** |
| `mark-config-default --config-id ID` | `PATCH …/mark-as-default` | promotes an **already-published** (SCHEDULED/ACTIVE/PAUSED) config to default; rejects a DRAFT — for a fresh config use `create-config --default` instead |
| `publish-config --config-id ID` | `POST …/publish` | IN_REVIEW → SCHEDULED (then auto-ACTIVE once the start time passes; visible at runtime after a short propagation lag) |
| `add-test-players --config-id ID --player-id ID …` | `POST …/test-players` | let specific players resolve a not-yet-public config |
| `test-config --config-id ID --player-id ID` | `GET …/test/{playerId}` | admin-side resolve (data + filters), no runtime needed |
| `delete-config --config-id ID` | `DELETE /configurations/{id}` | |

### Runtime read
| Command | Call | Notes |
|---|---|---|
| `get-config --setting-key K --player-id ID --version V [--checksum VAL ...] [--checksum-only] [--include-filters] [--get-default]` | `POST featureset.kinoa.io/features-configurations` | the real runtime call; `--version` is effectively required; response `settings[].status` is `OK` / `KEY_NOT_FOUND` / `VERSION_NOT_FOUND` / `DEFAULT_NOT_FOUND`, plus a `checksum`. `getDefault` is false in normal use (omit `--get-default`). **Checksum caching:** pass the checksum(s) the client holds via `--checksum`; the response returns only the settings whose checksum CHANGED (unchanged ones are omitted — the client reuses its cache). |

## Typical one-off sequence

Stand up a working config and confirm a player resolves it:

```bash
H="${CLAUDE_SKILL_DIR}/kinoa_dashboard_feature_settings.py"
# 1. schema (DRAFT → ACTIVE)
python "$H" create-schema --name BoostersConfig --fields-json '[{"name":"id","type":"integer"},{"name":"reward","type":"number"}]'
python "$H" publish-schema --schema-id <SCHEMA_ID>
# 2. binding + version
python "$H" create-setting --key BoostersConfig --name "Boosters" --schema-id <SCHEMA_ID>
python "$H" latest-version --schema-id <SCHEMA_ID>          # → schema_version_id, version
# 3. configuration: create (default) → load data → submit → publish
python "$H" create-config --setting-id <SETTING_ID> --schema-id <SCHEMA_ID> --schema-version-id <VER_ID> --name "v1 defaults" --default
python "$H" import-config-data --config-id <CONFIG_ID> --csv boosters.csv
python "$H" submit-config --config-id <CONFIG_ID>     # DRAFT → IN_REVIEW
python "$H" publish-config --config-id <CONFIG_ID>    # IN_REVIEW → SCHEDULED → ACTIVE
# 4. verify exactly as the app would (allow a few seconds / retry — the runtime caches briefly)
python "$H" get-config --setting-key BoostersConfig --version 1 --player-id <PLAYER_ID>
# 4b. checksum delta — pass the checksum from step 4; unchanged settings drop out of the response
python "$H" get-config --setting-key BoostersConfig --version 1 --player-id <PLAYER_ID> --checksum <checksum>
```

Lifecycle that the chain encodes (learned the hard way, validated live):
**schema** DRAFT→ACTIVE (`publish-schema`); **configuration** DRAFT→IN_REVIEW
(`submit-config`)→SCHEDULED (`publish-config`)→ACTIVE (auto, once start time passes).
A config must carry one `tableColumn` per schema field (handled by `create-config`),
and either be `--default` or carry segmentation to leave DRAFT. The runtime read
requires the `version`; expect a brief cache lag before a freshly-published config
resolves.

## Conventions

- One subcommand → one HTTP call → one JSON object on stdout. Branch on `ok`.
- Non-2xx is reported, not thrown; missing creds exit `2` with a `kinoa-init` hint.
- Helper is self-contained (duplicated `_load_session_env`/`_request`/… by
  design) so it installs in isolation. Don't extract a shared module.
