---
name: kinoa-dashboard-resource-template
description: Pure admin-API wrapper for Kinoa resource templates (the bundles service's catalogue of sellable / awardable items — NOT internal currency). List templates, fetch one, create a draft, update, activate (DRAFT→ACTIVE), deprecate, clone, and delete (HARD delete, DRAFT-only — irreversible). Use whenever the user wants to inspect or directly manipulate resource templates in the Kinoa dashboard (without going through the full registration workflow). The orchestration skill kinoa-sync-resource-template-integration delegates to this skill for every admin operation.
argument-hint: [list | get | create | update | activate | deprecate | clone | delete] [args]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

This skill is a thin CLI wrapper around the Kinoa **admin** resource-template API on the bundles service (`gate.kinoa.io/bundle/`). It does **not** orchestrate any workflow — for the discover → confirm → sync → verify registration flow, use `kinoa-sync-resource-template-integration`, which delegates here for every admin call.

The helper script `kinoa_dashboard_resource_template.py` is self-contained — no imports from sibling skills.

Requires `KINOA_BEARER_TOKEN` and `KINOA_GAME_ID` in `~/.kinoa/session.env`. If missing, the helper returns `error: missing_credentials` — set up Kinoa credentials first with `/kinoa-init`.

## What a "resource" is

A **resource template** is a typed definition of an item that can be **sold or awarded as a prize** — gear, boosters, chests, cosmetics, bundhandable goods. It is explicitly **not** internal/soft currency. Each template has a `name`, a `resourceKey` (`^[a-zA-Z][a-zA-Z0-9_-]*$`), a lifecycle `status` (`DRAFT → ACTIVE → DEPRECATED`), an optional `description`, an optional `body` map, and a list of typed `fields` (parameters) — each with `name`, `field_type` (`number`/`string`/`boolean`/`date`/`enumeration`), `required`, optional `default`, and `enumeration_values` for enumerations.

## Subcommands

```
python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" list [--rows N] [--statuses DRAFT,ACTIVE,DEPRECATED] [--name SUBSTR] [--sort-by F] [--order asc|desc]
    GET https://gate.kinoa.io/bundle/resource-templates
    Returns { totalCount, elements:[{id,name,key,status,fields,...}] } (verified
    live 2026-07-09). NOTE: `order` must be ASC/DESC — the helper uppercases it.
    --statuses is the closest analogue to a state probe (resource templates
    have no soft-delete — see delete).

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" get --id UUID
    GET .../resource-templates/<id> — full ResourceTemplateDto incl. fields.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" create --name NAME --key KEY [--description D] [--status draft] [--body JSON] [--field NAME:TYPE[:EXTRA][:req]]... [--fields-json JSON]
    POST .../resource-templates — creates a template, DRAFT by default so a
    later `activate` publishes it. Provide fields either as repeatable --field
    specs (quick CLI use) or as a single --fields-json array (used by the sync
    workflow after the developer confirms the HTML list). TYPE ∈ number,
    string, boolean, date, enumeration; for enumeration EXTRA is the
    comma-separated allowed values; trailing 'req' marks the field required.
    NOTE (verified live 2026-07-09): the server stores enumeration values as a
    separate entity — on read-back the field carries `enumeration_id` with
    `enumeration_values: null` (the inline values are not echoed).

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" update --id UUID [--name] [--key] [--description] [--status] [--body] [--field ...] [--fields-json]
    Two-step: GET the current template, apply only the provided overrides (PUT
    is a full replace, so unspecified fields are preserved), PUT it back.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" activate --id UUID
    POST .../resource-templates/<id>/activate — DRAFT -> ACTIVE (publishes it).

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" deprecate --id UUID [--reason TEXT]
    POST .../resource-templates/<id>/deprecate — -> DEPRECATED. Use this
    instead of delete for a template that is already ACTIVE.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" clone --id UUID [--key KEY] [--name NAME]
    POST .../resource-templates/<id>/clone — copies an existing template.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_resource_template.py" delete --id UUID
    DELETE .../resource-templates/<id>
    HARD delete, DRAFT-ONLY. The server returns 409 CONFLICT for ACTIVE or
    DEPRECATED templates (deprecate those instead). A DRAFT delete is
    irreversible — the row and its enumeration are removed; the only recovery
    is create under a new id. See the delete rules below.
```

Every subcommand prints a single JSON object: `{ http_status, ok, response | request_body, ...context }`. HTTP errors are caught and serialized — never raised onto stdout.

**Cross-game backstop (`--expect-game UUID`)** — accepted by every *mutating* subcommand (`create`, `update`, `activate`, `deprecate`, `clone`, `delete`). When passed, the helper aborts with `error: session_game_mismatch` (exit 2) *before* any state change unless `session.env`'s `KINOA_GAME_ID` equals the given UUID — guarding against a stale session from another game (here an irreversible HARD delete, or a create against the wrong game). Orchestrators should always pass the intended game id; omitting it preserves the previous behavior.

## Delete rules (load-bearing)

`delete` is a **HARD, irreversible** delete and only works while the template is `DRAFT`:

- **DRAFT** → deleted for good (row + enumeration removed). GET returns 404; recovery = create under a new id.
- **ACTIVE / DEPRECATED** → the server refuses with `409 CONFLICT` ("Cannot delete template for this status"). The helper adds a `hint` pointing at `deprecate`. Do not try to force it.

Because it is hard and unrecoverable, delete must be an **operator-initiated admin task in its own session — never inside a sync/registration run** (`kinoa-sync-resource-template-integration` never deletes). Before running, confirm via `AskUserQuestion`, naming the **resolved id AND name** and stating the delete is hard/irreversible and DRAFT-only. Proceed only on an explicit Yes from this session — even when the request already said "delete X", the confirmation validates the *resolved id*.

## Security boundary

This skill calls the bundles service on `gate.kinoa.io/bundle/resource-templates` with `Authorization: Bearer <token>` + `Game-Id: <uuid>`. This is the **admin** surface — **skill-only**. `gate.kinoa.io` hosts both surfaces for bundles: the app runtime uses `gate.kinoa.io/bundle/public/resource-templates` with a `game: <secret>` token (this skill does not touch it). What makes a call admin is the **bearer token**, not the host — so never embed these calls or the session token in application runtime code, exactly as with `dashboard.kinoa.io` admin calls.

## When to use

- Direct admin tasks (e.g., "list active resource templates", "publish resource template X by id", "deprecate a stale template", "delete a draft template" — delete ONLY as an operator-initiated task in its own session, never mid-sync).
- Invoked by `kinoa-sync-resource-template-integration` for every admin step in the discover → confirm → sync → verify workflow.
- Useful for debugging registration problems by inspecting resource-template records directly.

For anything beyond a single admin call (discovering candidate resources in the game, building the interactive confirmation page, computing the diff, generating `KinoaResources`, running the verification), use `kinoa-sync-resource-template-integration` instead.
