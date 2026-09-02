---
name: kinoa-dashboard-inapp-template
description: Pure admin-API wrapper for Kinoa in-app message templates (`message_templates`) — the reusable skeletons behind in-app pop-ups: offers, bundles, milestone chases, mission boards. List templates, fetch one, create a draft from a builder payload, update one with a full body (guarded: draft-only, refuses on referenced templates or slot loss, with a `--dry-run`), and check whether in-app messages still reference it (`has_related_in_app_messages`). There is deliberately NO delete subcommand — a template with related in-app messages must never be deleted, and delete is kept out of this tooling entirely. Use whenever the user wants to inspect or directly manipulate in-app templates on the Kinoa dashboard (without going through the mockup-to-template workflow). The workflow skill kinoa-inapp-template-from-image delegates its Phase 5 create to this helper.
argument-hint: [list|get|create|update|has-related]
allowed-tools: Bash(python *) Read AskUserQuestion
---

This skill is a thin CLI wrapper around the Kinoa **admin** in-app message-template API (`/api/message_templates`). It does **not** orchestrate any workflow — for the image → decompose → confirm → payload flow, use `kinoa-inapp-template-from-image`, which delegates its Phase 5 registration step here.

The helper script `kinoa_dashboard_inapp_template.py` is self-contained — no imports from sibling skills.

All calls go to `https://dashboard.kinoa.io/api/message_templates` — the only supported target, hardcoded in the helper (there is no environment override). `{base}` in the subcommand docs below stands for that URL.

Requires `KINOA_BEARER_TOKEN` and `KINOA_GAME_ID` in `~/.kinoa/session.env`. If missing, the helper returns `error: missing_credentials` — set up Kinoa credentials first with `/kinoa-init`.

## What an in-app template is

An **in-app template** is the reusable skeleton of a pop-up. The developer registers it once; operators then fill it in and ship many in-app messages from it with no further dev work. A template declares **slots**, not content:

| Bucket | What it is |
|---|---|
| `images` | Art slots the operator fills with a URL — background, product, prizes. |
| `buttons` | Interactive controls, each with the set of click actions it may perform. |
| `texts` | Copy slots the operator types into. |
| `customs` | Typed operator knobs (`string` / `numeric` / `boolean` / `enumeration`) that are not one of the above. |

On top of that a template carries a **`featureType`** — `standard`, `mission`, or `milestone` — which decides whether it also gets a progression model in `features`. `standard` templates have no progression block (see the create normalizations below); the other two require a matching `features.<type>`.

A template also has a lifecycle `status` — a create lands as **`draft`**; the dashboard promotes it to `active`. This helper never sets `status` itself: the server owns the lifecycle.

## Key case — the `Key-Inflection: camel` header (load-bearing, never remove)

**The API inflects key case per request.** With no header it speaks `snake_case` (`click_action_type`, `text_limit`, `feature_type`, `tags_ids`); with **`Key-Inflection: camel`** it speaks camelCase (`clickActionType`, `textLimit`, `featureType`, `tagsIds`) — **request bodies and responses alike**. The variant `X-Key-Inflection` does nothing. The Kinoa dashboard UI sends this header, which is why every browser capture is camelCase.

**This helper pins `Key-Inflection: camel` on every request**, so one single form runs end to end: the builder's payload, the bodies posted here, the responses read back, and every reference doc in this repo are all camelCase. Payloads therefore pass through **byte-for-byte** — the helper does **no** case conversion, and you must not hand-convert one either.

⚠️ **Why the header is load-bearing:** drop it and the API flips to snake_case. A camelCase body then meets a snake-expecting deserializer and **every case-differing field is SILENTLY DROPPED** — the call returns `200` while the data is gone (a create whose buttons end up with no `clickActionType` at all). That is exactly the failure that looked like a "silent camelCase drop" before the header was understood. Never remove it; never work around it.

Note the **route** stays snake_case (`/has_related_in_app_messages`) — only payload keys inflect.

## A sparse-looking GET means a headerless write already happened

`get` returns the **full** stored record — buttons with `clickActionType`, `textLimit`, `customFields`, `canBeHidden`, `backgroundImg`, `requiredItemsCount`; texts with `customFields`. Nothing is trimmed.

So when a `get` comes back looking sparse — buttons with nothing but `key`/`name`/`index`/`description` — **that is not a display artifact, it is the record.** Those fields were never stored, because the write that created it lacked the header. Read it as a diagnosis: the fix is to PATCH the full body through this helper, then re-`get` to confirm the config is now there.

**`update` is an explicit operator-initiated admin task, not the normal way to
evolve a template** — once a draft exists, changes are recommended through the
Kinoa Dashboard (*Game Settings → In-Apps*), where the template's dependencies
are visible before anything is touched. When an API update IS explicitly
requested: **the recommended source of truth stays the confirmed payload file** (`<template_key>.template.json`) — not because a `get` body is unusable, but because the payload file is the canonical copy that the builder, the confirmation page, and `inapp_template_build.py validate` all understand, and because it is the safe base when the *stored* record is itself incomplete (a legacy draft written without the header). Editing a `get` body and PATCHing it back is technically fine; just verify it is complete before trusting it as the base.

## Subcommands

```
python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_inapp_template.py" list [--page N] [--rows N] [--sort-by F] [--sort-direction asc|desc] [--status draft|active]...
    GET {base}?page=1&rows=20&sort_by=updated_at&sort_direction=desc
    Returns { "list": [ ...template records... ], ... }. Defaults mirror the
    dashboard's own request: page 1 (1-BASED, unlike the resource-template
    helper's 0-based page), 20 rows, sort_by=updated_at, sort_direction=desc.
    --status is repeatable and emits `status[]=<value>` per value; whenever ANY
    --status is given the request also carries `selectedFilters[]=status` —
    the switch that turns the filter on. The values alone are ignored without
    it, so the two always travel together. Brackets are sent literally,
    matching the observed dashboard traffic.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_inapp_template.py" get --id ID
    GET {base}/<id> — the full stored record in camelCase (Key-Inflection:
    camel): all four slot buckets with their config (clickActionType, textLimit,
    customFields, canBeHidden, …), featureType, features, status, gameId,
    timestamps. A record that reads back sparse was written without the header,
    so those fields were never stored — see the section above.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_inapp_template.py" create --payload FILE|- [--tip-image-url URL | --tip-image-file PATH] [--expect-game UUID]
    POST {base} — creates the template; it lands server-side as status "draft"
    with its own id/createdAt. The payload is the create body produced by
    kinoa-inapp-template-from-image's
    `inapp_template_build.py build` (name, key, description, images, buttons,
    texts, customs, featureType, features, optionally gameId/tagsIds) — in
    camelCase, which is exactly what goes on the wire; the body is passed
    through byte-for-byte apart from the normalizations below. Pass a path, or
    '-' to read the body from stdin.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_inapp_template.py" update --id ID --payload FILE|- [--allow-referenced] [--allow-slot-removal] [--tip-image-url URL | --tip-image-file PATH] [--dry-run] [--expect-game UUID]
    PATCH {base}/<id> — FULL-BODY REPLACE semantics despite the verb. Send a
    complete template body, not a sparse diff, or the omitted slots are lost.
    Prefer the LOCAL PAYLOAD FILE as the source of truth: edit it and re-send —
    it is the canonical copy, and it is safe even when the stored record is
    incomplete. A `get` body can also be edited and PATCHed back (same case, no
    conversion needed); check it is complete first. Same normalizations as
    create. GUARDED and deliberately MULTI-CALL — see the guard ladder below.
    --dry-run runs every guard and prints the slot diff + the body that would be
    sent, without PATCHing.

python "${CLAUDE_SKILL_DIR}/kinoa_dashboard_inapp_template.py" has-related --id ID
    GET {base}/<id>/has_related_in_app_messages ->
    { "hasRelatedInAppMessages": bool } under Key-Inflection: camel (the
    snake_case spelling is accepted as a fallback). The ROUTE stays snake_case —
    only payload keys inflect.
    True means live or historical in-app messages still point at this template,
    so its shape is load-bearing: changing or retiring it breaks them. The
    output adds a flattened `has_related` boolean for easy scripting.
```

### Create / update normalizations (applied before the request fires)

The helper reshapes the builder payload to match the create contract — **no case conversion**, since `Key-Inflection: camel` makes camelCase the wire form — and echoes the result as `request_body` so the operator sees exactly what was sent:

1. **`tagsIds` is always present** — defaulted to `[]` (and a `null` is rewritten to `[]`). The dashboard sends `[]` when no tag is attached.
2. **`features: null` on a `"standard"` template becomes `{}`** — the builder emits `null` (its own documented invariant), but the create contract carries an empty object. Non-`standard` feature types keep their `features.<type>` block untouched, `null` included, so the server's own validation speaks rather than ours.
3. **`gameId` is stripped** (the snake spelling too) — the server derives the game from the `Game-Id` header and stamps its own `gameId` onto the response. Sending one invites a body/header mismatch.

Every other key and value passes through **byte-for-byte**. Each lookup accepts both spellings, so a snake_case body (read back from a headerless call) normalizes identically instead of growing a duplicate key. The caller's payload file is never mutated; normalization returns a new object.

### Output shape

Every subcommand makes **one HTTP call** and prints a single JSON object:

```json
{ "http_status": 200, "ok": true, "response": { … } }                        // list
{ "http_status": 200, "ok": true, "id": "<id>", "response": { … } }          // get
{ "http_status": 200, "ok": true, "request_body": { … }, "response": { … } } // create
{ "http_status": 200, "ok": true, "id": "<id>", "name": "…", "guards": { … }, "slot_diff": { "added": {}, "removed": {} }, "request_body": { … }, "response": { … } } // update
{ "ok": true, "dry_run": true, "id": "<id>", "name": "…", "guards": { … }, "slot_diff": { … }, "would_send": { … } }        // update --dry-run
{ "ok": false, "reason": "slot_removal", "detail": "…", "override": "--allow-slot-removal", "slot_diff": { … } }          // update, refused
{ "http_status": 200, "ok": true, "id": "<id>", "response": { "hasRelatedInAppMessages": false }, "has_related": false } // has-related
```

HTTP errors are caught and serialized — never raised onto stdout. A transport failure (DNS, timeout) comes back as `http_status: 0` with the reason in `response`; treat it as *unknown outcome* and re-check with `list`/`get` before retrying a mutation. Exit codes: `0` on 2xx, `1` on any non-2xx or transport failure, `2` on a local guard failure (missing credentials, unreadable/invalid payload, game mismatch) — where no request is sent at all.

**Cross-game backstop (`--expect-game UUID`)** — accepted by the *mutating* subcommands (`create`, `update`). When passed, the helper aborts with `error: session_game_mismatch` (exit 2) *before* any state change unless `session.env`'s `KINOA_GAME_ID` equals the given UUID — guarding against a stale session from another game creating or rewriting a template on the **wrong** game's dashboard. Orchestrators should always pass the intended game id; omitting it preserves the previous behavior.

## Tip images — two different transports

A template's tip image can arrive two ways, and they are **not** interchangeable. Both flags are available on `create` and `update`, and they are mutually exclusive (argparse enforces it).

| Flag | Transport | Calls |
|---|---|---|
| `--tip-image-url URL` | ordinary JSON field — `tipImageUrl` as a plain string in the create/update body. Verified: 200, stored. | none extra |
| `--tip-image-file PATH` | a **second, image-only** `PATCH {base}/{id}` with `Content-Type: multipart/form-data` | +1 |

⚠️ **A blob cannot go through the JSON body.** Verified on production: raw base64 **and** a `data:` URI both return **500**. Do not retry them, and do not invent a third encoding.

The multipart request carries exactly **one** part:

```
Content-Disposition: form-data; name="tip_image_blob"; filename="<name>"
Content-Type: image/<ext>

<raw bytes>
```

Two details that matter:

- **The part name stays snake_case** (`tip_image_blob`) even though `Key-Inflection: camel` rides along on the same request — multipart field names are not inflected.
- **That PATCH is partial.** It updates only the image; the template body survives untouched (verified: buttons intact afterwards). It is not a full-body replace, unlike the JSON `update`.

The content type is sniffed from the file's **magic bytes** (`png`/`jpeg`/`gif`/`webp`), never from its extension — a PNG named `.jpg` uploads correctly, and a non-image is refused with `unsupported_tip_image_type` **before any HTTP call**, so a bad file can never leave a half-created template behind.

The upload fires only after the main create/update **succeeded** (and, for `update`, after every guard passed). Its outcome is reported alongside the main result:

```json
"tip_image": { "mode": "blob", "filename": "tip.png", "content_type": "image/png", "bytes": 20481, "http_status": 200, "ok": true, "response": { … } }
"tip_image": { "mode": "url", "url": "https://…", "http_status": 200, "ok": true, "detail": "tipImageUrl sent inline in the JSON body — no extra call" }
```

**A failed image upload never masks a successful main call**: the top-level `ok` and the exit code track the **main** call (the template was created/updated either way), so check `tip_image.ok` separately. Under `--dry-run` no image bytes are sent at all — the output carries `tip_image_plan` describing what would happen (mode, file, size).

## `update` guard ladder (load-bearing)

`update` is the one genuinely dangerous subcommand here, for two independent reasons:

- **The wipe scenario.** PATCH is a **full-body replace**. Send a body that is missing a button, and that button is gone from the template — no error, no warning. A hand-trimmed or partially-built body destroys slots.
- **The referenced-template scenario.** Once operators have shipped in-app messages from a template, its shape is load-bearing. Changing or dropping a slot those messages fill breaks **live campaigns**.

So `update` is **deliberately multi-call**: a pre-flight `GET` of the stored record, a `has_related_in_app_messages` probe, and only then the `PATCH`. (Precedent: `kinoa-dashboard-resource-template`'s update is also GET + PUT.) The guards run in order and the first failure refuses:

| # | Guard | Fires when | Override |
|---|---|---|---|
| 1 | `system_template` | the record has `system: true` | **none** — system templates are Kinoa's own, never updated from tooling |
| 2 | `not_draft` | `status` is not `draft` | **none** — update is a draft-only operation; active templates evolve via the Dashboard, where their dependencies are visible |
| 3 | `update_not_available` | `availableActions` is present and omits `"update"` | **none** — the server's own permission signal (an active non-system template offers `show`/`clone`/`deprecate`/`export_to_game`/`hide` instead) |
| 4 | `template_referenced` | in-app messages already build on the template (or the probe is inconclusive → `reference_check_failed`) | `--allow-referenced` |
| 5 | `slot_removal` | the new body drops element keys the stored record still has | `--allow-slot-removal` |

Guards 1–3 are **absolute**: the two override flags do not affect them, by design — a non-draft or system template is simply not updatable from here.

The **slot diff is always reported**, refusal or not: `slot_diff: { added: {bucket: [keys]}, removed: {bucket: [keys]} }` per slot bucket (`images`/`buttons`/`texts`/`customs`). `added` is informational; `removed` is what guard 5 acts on.

Refusals are serialized, never raised — `{ "ok": false, "reason": "<guard>", "detail": "…", "override": "--flag"|null, … }` with a non-zero exit code.

### Confirm with the developer before every update

Before running `update` — **including when `--dry-run` came back clean** — confirm via `AskUserQuestion`, naming the **resolved template id AND name** plus the **slot diff** (which keys would be added and removed), and proceed only on an explicit **Yes from this session**. This is the same convention this repo applies to deletes (see CLAUDE.md, *Deletion confirmation*): even when the request already said "update template X", the confirmation validates the *resolved id* and the *actual diff* — that is what catches a wrong id or an accidentally trimmed body before it lands. The recommended sequence is `--dry-run` → show the diff → `AskUserQuestion` → real run.

## No delete — by design (load-bearing)

The server exposes a DELETE route for `message_templates`. **This helper does not, and must not grow one.**

- A template with related in-app messages **must never be deleted** — deleting it orphans every message built from it.
- `has_related_in_app_messages` is the **server-side blocker signal** that makes the risk concrete: `hasRelatedInAppMessages: true` means live or historical in-app messages still reference the template. Run `has-related` before *any* destructive or shape-changing edit — a full-body `update` that drops a slot is nearly as damaging as a delete when messages depend on that slot.
- The operator decision was to keep delete **out of the tooling entirely**, not to gate it behind a confirmation prompt. Even a template with no relations is not deletable from here.

If a user asks to delete a template: say plainly that this helper has no delete by design, explain the orphaning risk, and offer `has-related` to show what depends on it. Removal is a dashboard-UI / backend-operator action taken deliberately outside this tooling. Do **not** improvise a `curl` DELETE, and do not add the subcommand.

## Security boundary

This skill calls the dashboard admin API with `Authorization: Bearer <token>` + `Game: <uuid>` + `Game-Id: <uuid>` (both headers carry the same game UUID; different Kinoa controllers read different ones) + `Key-Inflection: camel` (see above). This is the **admin** surface — **skill-only**.

**Never emit these calls into game code.** The session token is admin-tier and must not ship in an app binary, config, or runtime request. Rendering an in-app message at runtime is the SDK's job, on the public surface with a game secret — this helper never touches it. Same hard rule as every other `dashboard.kinoa.io` admin call in this repo.

## When to use

- Direct admin tasks: "list draft in-app templates", "show me template `<id>`", "create the template from this confirmed payload", "does anything still use this template?".
- Editing a draft template: run `update --dry-run` first, show the slot diff, confirm via `AskUserQuestion`, then re-run for real.
- Invoked by `kinoa-inapp-template-from-image` for its Phase 5 create, with the payload that skill's builder produced and the developer confirmed.
- Keeping the confirmed payload file next to the project — the canonical copy of a template's shape, and the safe base for a later `update`.
- Useful for debugging a template registration by inspecting the stored record directly — in particular for comparing the `request_body` that was sent against the record the server actually stored.

For anything beyond a single admin call (reading a mockup, decomposing it into slots, running the interactive confirmation page, validating a payload), use `kinoa-inapp-template-from-image` instead.

## Auto-mode invocation discipline

In Claude Code's auto permission mode every Bash call passes a safety classifier that judges the COMMAND TEXT, not the endpoint. Keep helper invocations simple and transparent: **one helper call per Bash invocation** — a plain `python3 <helper> <cmd> ... | python3 -c "..."` pipeline is fine. Do NOT wrap the helper in `for`-loops, heredocs, or multi-file redirect batteries: that shape reads as an opaque network script and gets denied even though the same call passes as a one-liner. Two denial kinds, two responses: *"Stage 2 classifier error … usually transient"* → retry the SAME command; a plain block on a compound command → re-issue as single minimal calls. **A classifier denial is never an offline / expired-token signal** — do not take a fallback path because of one. Durable opt-out: the developer may add a Bash permission allow-rule for the plugin helpers in their Claude Code settings (e.g. `Bash(python3 ~/.claude/plugins/cache/kinoa/kinoa-dashboard/*/skills/*/kinoa_dashboard_*.py *)`).
