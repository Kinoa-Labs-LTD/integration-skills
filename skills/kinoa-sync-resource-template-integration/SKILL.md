---
name: kinoa-sync-resource-template-integration
description: Internal sub-skill of kinoa-api-integration — do NOT trigger directly. Invoked as the orchestrator's `sync-resource-template-integration` dispatch. Owns the resource-registration workflow: discover which sellable / awardable items (resources — NOT internal currency) the game defines, propose them on an INTERACTIVE HTML confirmation page the developer edits (rename, retype, delete proposals, add missed ones), then register the confirmed list on the Kinoa dashboard as resource templates (create DRAFT → activate) by delegating admin calls to kinoa-dashboard-resource-template, generate a KinoaResources data class of the confirmed keys, and verify. When the user wants to register game resources / sellable items / prize items with Kinoa, mirror shop or reward catalogues, generate KinoaResources, or sync resource templates, route via kinoa-api-integration sync-resource-template-integration.
argument-hint: [optional: app source path]
allowed-tools: Bash(python *) Bash(cat *) Read Write Edit Glob Grep AskUserQuestion
---

This skill is the **integration / code-side** half of the resources pair. It owns the discover → confirm → sync → verify workflow but does no admin API calls itself; for every admin call it delegates to the sibling skill `kinoa-dashboard-resource-template` (whose helper wraps the bundles admin API on `gate.kinoa.io/bundle/`). When both skills are installed as siblings under `~/.claude/skills/`, the relative path `${CLAUDE_SKILL_DIR}/../kinoa-dashboard-resource-template/kinoa_dashboard_resource_template.py` resolves correctly.

Requires `KINOA_BEARER_TOKEN` and `KINOA_GAME_ID` in `~/.kinoa/session.env`. If missing, the dashboard helper returns `error: missing_credentials` — tell the user to run `/kinoa-init` first.

## What a "resource" is (and is not)

A **resource** is any item that can be **sold or awarded as a prize** — weapons, armor, boosters, chests, cosmetics, event rewards, IAP goods. It is registered on Kinoa as a **resource template**: a typed definition with a `name`, a `resourceKey`, a lifecycle `status` (`DRAFT → ACTIVE → DEPRECATED`), an optional `description`, and typed `fields` (parameters). Resources are **not internal/soft currency** (gold, gems, energy) — those are modelled elsewhere (player fields), so do not propose currency counters as resources.

## Security boundary — admin vs runtime

| Surface | Host | Auth | Caller |
|---|---|---|---|
| **Admin** | `gate.kinoa.io/bundle/resource-templates` | `Authorization: Bearer <token>` + `Game-Id: <uuid>` | **Skill only.** Delegated to `kinoa-dashboard-resource-template` for list / create / update / activate / deprecate. |
| **Runtime** | `gate.kinoa.io/bundle/public/resource-templates` | `game: <secret>` | **App code** (not touched here — in this integration resources are registered admin-side only). |

`gate.kinoa.io` hosts **both** surfaces for bundles; what makes a call admin is the **bearer token**, not the host. Never emit code into the application that carries an `Authorization: Bearer` header or the session token — the generated `KinoaResources` is a **pure data class** (key constants + field metadata), never an API call. This mirrors the hard rule for `KinoaEvents` / `KinoaPlayerState`.

## Webhook telemetry

This skill is **Phase 6** of the orchestrator's chain and has its own four inner phases. Fire telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 6.<n> — <heading>"` when entering each inner phase (e.g. `"Phase 6.1 — Discover candidate resources"`, `"Phase 6.3 — Confirm and sync resource templates"`).
- `phase-end --phase "Phase 6.<n> — <heading>" --summary "<one-line outcome>"` once each inner phase completes (counts of created / activated / updated / skipped, or "skipped by developer").
- `qa` after every `AskUserQuestion` exchange (nothing-found fallback in 6.1, file-path/paste hand-back in 6.3.3, apply approvals, test-framework choice in 6.4).

Helper exits 0 even on failure; never abort the workflow on a webhook error.

**Run state.** On start, read `./.kinoa-integration-state.json` if present — if `phases.resource_templates` records finished inner phases, resume from the first unfinished one. Alongside every inner `phase-end`, read-merge-write the file's `phases.resource_templates` entry: `status`, `service_root` (MONOREPO), `kinoa_resources_path` (6.2), `confirmed_resources` (the final list from 6.3.3, by key), `registered` (ids + keys + status created/activated in 6.3.4), `report` (6.3.6). Schema and rules: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/run-state.md`. Conversation context is not the durable source of truth — the state file is.

**Integration registry.** Alongside every state-file write, update `KINOA-INTEGRATION.md` next to it (bootstrap from the template in `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/integration-registry.md` if missing): rewrite the "Resources" section under `## Modules` to the current state (service, `KinoaResources` path, registered keys + status) and append a dated entry to `## History` describing what this run changed. Append-only — never rewrite old History entries.

**Architecture & service scope.** Read `KINOA_ARCHITECTURE` from `~/.kinoa/session.env` (default `SINGLE`; semantics: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/architecture-modes.md`) before Phase 6.1:

- `MONOREPO` — ask which service directory owns the resource/shop catalogue (offer candidate dirs found via Glob). Scope 6.1 discovery and the generated `KinoaResources` to that `service_root`.
- `MULTI_REPO` — the current repo is the service. Resource templates are game-wide dashboard entities, so on start read the central index `~/.kinoa/<game_id>/services.json`; if another service already registered resources, list them and avoid re-proposing duplicates. At every module-level `phase-end`, update this service's entry (`modules.resource_templates`, `last_sync`).

The skill works in four phases. Drive each to completion with the developer before moving on.

---

## Phase 6.1 — Discover candidate resources

Use `Glob` and `Grep` to find where the game defines sellable / awardable items. Look broadly, because every game names these differently:

- **Shop / store / IAP catalogues** — files or classes named `shop`, `store`, `iap`, `product`, `catalog`, `offer`, `pack`, `bundle`. Product id lists, price tables, SKU definitions.
- **Reward / prize tables** — `reward`, `prize`, `loot`, `drop`, `chest`, `crate`, `gift`, `daily`, `battlepass`, `season`. Loot tables, reward configs, quest/achievement payouts.
- **Item definitions** — `item`, `equipment`, `gear`, `weapon`, `skin`, `cosmetic`, ScriptableObjects, enums of item ids, data files (JSON/CSV/asset) listing items and their attributes.

For each candidate capture: a human **name**, a proposed **resourceKey** (slug of the id/name, must match `^[a-zA-Z][a-zA-Z0-9_-]*$`), a short **description**, the **source** location (`path:line` — provenance the developer can verify), and the **fields** (parameters) you can infer from the item's attributes (e.g. an item with `attack`, `rarity`, `tradable` → number / enumeration / boolean fields).

**Exclude internal currency.** Gold/gems/energy counters are player state, not resources — don't propose them. If unsure whether something is a resource or currency, keep it but flag it so the developer can drop it on the confirmation page.

**Do NOT ask the developer to confirm the findings in the terminal.** The interactive confirmation page (6.3.3) **is** the review step — it can rename, retype, drop, and add resources, so a terminal `AskUserQuestion` before it ("register these N items?") is a redundant gate that must never replace or precede the page. When discovery finds candidates — even from an unusual source (achievements, quest payouts) or with low confidence — carry them straight into 6.2 → 6.3 and let the developer edit them on the page; flag doubtful ones in their `description` so they're easy to drop there. The **only** case where you stop and ask via `AskUserQuestion` is when discovery found **nothing at all** — then ask the developer to point you at the item/shop/reward definitions (or to confirm the game genuinely has no resources, which skips the phase).

---

## Phase 6.2 — Generate the candidate list and scaffold KinoaResources

1. Build the in-memory **candidate list**: an array of resource objects `{name, resourceKey, description, source, fields:[{name, field_type, required, default?, enumeration_values?, description?}]}`. Field types are `number`, `string`, `boolean`, `date`, `enumeration` (for enumeration, populate `enumeration_values` from the values you saw in code).

2. **Scaffold an empty `KinoaResources` data class** in the app (in `MONOREPO`, under the chosen `service_root`), mirroring the language/style of the existing `KinoaEvents` / `KinoaPlayerState` if present. It is a **pure data class** — key constants and, optionally, field metadata — with **no API calls** and no bearer token. You'll fill in the confirmed keys in 6.3.5. Example (C#):

   ```csharp
   // Kinoa resource keys — generated by kinoa-sync-resource-template-integration.
   // Pure data: the resource CATALOGUE lives on the Kinoa dashboard; this class
   // only holds the keys so game code can reference them without magic strings.
   // Never add API calls or an Authorization header here.
   public static class KinoaResources
   {
       // filled in Phase 6.3.5
   }
   ```

Record `kinoa_resources_path` in run state.

---

## Phase 6.3 — Confirm and sync resource templates

### 6.3.1 Fetch existing resource templates

```
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-resource-template/kinoa_dashboard_resource_template.py" list --rows 200 --statuses DRAFT,ACTIVE,DEPRECATED
```

**`--statuses` is mandatory here** — the server's DEFAULT listing (no `--statuses`) EXCLUDES DEPRECATED templates (live-verified 2026-07-23); without it a retired key looks absent, the diff proposes 🔵 CREATE instead of 🟠 REVIEW, and the create then 422s with "key already exists". The response is `{ http_status, ok, response: { totalCount, elements: [...] } }` (verified live 2026-07-09). **Truncation guard:** if `totalCount > elements.length`, re-run with `--rows <totalCount or more>` before building the map — a truncated listing misclassifies existing keys as 🔵 CREATE and produces duplicate DRAFTs (whose only cleanup is the hard delete). Each element has `id`, `name`, `key`, `status`, `fields`, `availableActions`. `status` comes back **lowercase** in the JSON (`draft`/`active`/`deprecated`) — compare it case-insensitively; the `--statuses` filter accepts either case. Build a map `key → {id, status}` of what's already on the dashboard.

### 6.3.2 Compute the diff

Match each candidate to the dashboard by `resourceKey` (case-insensitive):

- **key not on dashboard** → 🔵 **CREATE** — will create a DRAFT then activate.
- **key present, status `ACTIVE`** → ✅ already registered. Mark `existing: true`; propose an **update** only if the candidate's fields differ from the dashboard's (surface the diff so the developer decides).
- **key present, status `DRAFT`** → 🟡 **ACTIVATE** (and update fields if changed) — someone started it but never published.
- **key present, status `DEPRECATED`** → 🟠 **REVIEW** — the template was retired. Don't silently revive it; surface it so the developer can rename the candidate's key, clone the deprecated one, or drop it. There is no un-deprecate endpoint.

**Enumeration fields on read-back (verified live 2026-07-09).** When you create a field with `enumeration_values`, the server stores the values as a separate *enumeration entity* and returns that field with `enumeration_id` set and `enumeration_values: null` — the inline values are not echoed. So when diffing a candidate's enumeration field (which carries `enumeration_values`) against the dashboard's version (which carries `enumeration_id`, values null), do **not** treat the null as "values changed/removed". Compare on `enumeration_id` presence / the enumeration's own values, not on the inline `enumeration_values` list — otherwise every re-run proposes a spurious update.

Carry the `existing` flag and dashboard `status` into the candidate objects — they feed the confirmation page (which renders "on dashboard" vs "new" badges).

### 6.3.3 Build the interactive confirmation page — the human-in-the-loop step

This is the load-bearing approval step. Instead of a terminal checklist, the developer reviews and **edits** the proposed resources in a browser, then hands the confirmed list back. Assemble the candidates JSON (schema below) and render the page:

```bash
echo '<candidates-json>' | python "${CLAUDE_SKILL_DIR}/generate_confirm_page.py" \
    --output ./kinoa-resources-confirm-<YYYYMMDD-HHMMSS>.html
```

Candidates JSON schema:

```json
{
  "generated_at":  "<ISO 8601 UTC>",
  "game_id":       "<KINOA_GAME_ID>",
  "existing_keys": ["<keys already on the dashboard>"],
  "resources": [
    {"name", "resourceKey", "description", "source", "existing": true|false,
     "fields": [{"name", "field_type", "required", "default"?, "enumeration_values"?, "description"?}]}
  ]
}
```

The script writes a **self-contained** HTML page and auto-opens it in the developer's browser (`{"ok": true, "output": "...", "opened_in_browser": true|false}`). If `opened_in_browser` is `false` (headless), surface the absolute path. On the page the developer can:

- edit any name / key / description / parameter (with live `resourceKey` validation — regex + duplicate detection);
- **remove** proposals that aren't real sellable/awardable resources;
- **add** resources (and parameters) the scan missed;
- **Download** the confirmed JSON (button → `kinoa-resources-confirmed-<page timestamp>.json`) **or Copy** it to the clipboard.

The page **cannot write to the filesystem** (browser sandbox), so ask the developer, via `AskUserQuestion`, to hand the confirmed list back one of two ways:

- **Downloaded file** → they give you the path (in `~/Downloads`, named `kinoa-resources-confirmed-<page timestamp>.json`); `Read` it.
- **Copied JSON** → they paste it into the chat; parse it directly.

Suggest `.gitignore`-ing `kinoa-resources-confirm-*.html` and `kinoa-resources-confirmed-*.json` — local artifacts, not source.

The confirmed JSON has the shape:

```json
{"confirmed_at": "<iso>", "page_generated_at": "<iso — echo of the page's generated_at>",
 "resources": [{"name", "resourceKey", "description", "existing", "fields": [...]}]}
```

**Freshness gate — reject a stale hand-back.** Before using the confirmed list, check `page_generated_at` equals the `generated_at` this run stamped into the candidates payload it piped to `generate_confirm_page.py` (earlier in this step). A mismatch (or a missing `page_generated_at` alongside an old `confirmed_at`) means the developer handed back a file exported from an **earlier run's** page — e.g. last week's un-suffixed download still sitting in `~/Downloads`. Don't apply it: say which run it came from and ask them to re-export from the page that's open now.

**This confirmed list is the canonical set** — only these resources get registered, exactly as edited. Re-validate every `resourceKey` against `^[a-zA-Z][a-zA-Z0-9_-]*$` and for duplicates before applying (the helper will also reject bad keys, but catching it here is friendlier). If any are invalid, show which and ask the developer to fix them (re-open the page or correct inline).

### 6.3.4 Apply — register the confirmed resources

Re-fetch the dashboard listing (6.3.1) so ids/status are fresh, then for each confirmed resource execute in order. Always pass `--expect-game <game_id>` on mutating calls — the game id recorded in `.kinoa-integration-state.json` at run start (not a fresh session.env read: this catches a session.env another terminal's `/kinoa-init` swapped mid-run).

After each call read the JSON and branch on the failure kind:

- `ok == false` with a real HTTP status (4xx/5xx) — surface `http_status` + `response` and ask whether to retry, skip, or stop. **Exception — 401:** the session token has expired; don't offer a blind retry — collect a fresh token via `/kinoa-init`, then resume (already-registered ids are in the state file).
- `http_status: 0` or no JSON (network error / timeout) — **ambiguous: the server may have applied the request.** Never retry a `create` blind; re-run `list` first and retry only if the key is absent (a duplicate DRAFT's only cleanup is the hard delete).

- 🔵 **CREATE** (key not on dashboard):
  1. Create as DRAFT, passing the confirmed fields as one JSON array (preserves per-field `required` / `default` / `enumeration_values` / `description` that a `--field` spec can't carry):
     ```
     python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-resource-template/kinoa_dashboard_resource_template.py" create \
         --name "<name>" --key "<resourceKey>" --description "<description>" \
         --fields-json '<fields array>' --expect-game <game_id>
     ```
  2. Read the new `id` from the response, then activate:
     ```
     python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-resource-template/kinoa_dashboard_resource_template.py" activate \
         --id <id> --expect-game <game_id>
     ```
  (Skip the activate only if the developer explicitly wants it left as a DRAFT for later review.)

- 🟡 **ACTIVATE** (key present, DRAFT): update fields first if they changed (`update --id <id> --fields-json ... --expect-game <game_id>`), then `activate --id <id> --expect-game <game_id>`.

- ✅ **already ACTIVE**: if the confirmed fields differ, `update --id <id> --fields-json '<fields>' --expect-game <game_id>`; otherwise no call.

- 🟠 **DEPRECATED**: do nothing automatically — follow the developer's 6.3.2 decision (rename+create, `clone`, or drop).

Never call `delete` in this workflow — it is a hard, DRAFT-only, operator-initiated action reserved for `kinoa-dashboard-resource-template` in its own session.

After the loop, summarize: created, activated, updated, skipped, failed.

### 6.3.5 Fill in KinoaResources

Populate the `KinoaResources` scaffold from 6.2 with the confirmed keys — one constant per registered resource, named after the key. Keep it pure data. Example:

```csharp
public static class KinoaResources
{
    public const string LegendarySword = "legendary_sword";
    public const string GoldChest      = "gold_chest";
}
```

Only include resources that were actually registered (or already ACTIVE). Skipped/deprecated ones don't go in.

### 6.3.6 Generate the registration report

Produce a read-only HTML record of the run (distinct from the confirmation page). Assemble from data in hand — the confirmed list, the dashboard listing, and what 6.3.4 actually applied:

```json
{
  "generated_at":         "<ISO 8601 UTC>",
  "game_id":              "<KINOA_GAME_ID>",
  "kinoa_resources_path": "<path from 6.2>",
  "service_root":         "<monorepo service dir or empty>",
  "created":   [{"name", "key", "status", "fields", "note"}, ...],
  "activated": [{"name", "key", "status", "fields", "note"}, ...],
  "updated":   [{"name", "key", "status", "fields", "note"}, ...],
  "unchanged": [{"name", "key", "status", "fields", "note"}, ...],
  "skipped":   [{"name", "key", "status", "fields", "note"}, ...]
}
```

`fields` is a list of `{"name","field_type","required"?,"enumeration_values"?}`. Render and save to the project cwd:

```bash
echo '<json>' | python "${CLAUDE_SKILL_DIR}/generate_report.py" --output ./kinoa-resource-registration-report-<ts>.html
```

The script auto-opens it in the browser; if `opened_in_browser` is `false`, surface the absolute path. Suggest `.gitignore`-ing `kinoa-resource-registration-report-*.html`.

### Review loop

Ask via `AskUserQuestion` whether to register more resources now. **Yes** → re-run 6.3.1 → 6.3.6 (a fresh confirmation page each time). **No** → proceed to Phase 6.4. Don't loop without asking.

---

## Phase 6.4 — Verify

Confirm the registration actually took, two ways:

1. **Dashboard read-back** — for a couple of the registered resources, `get --id <id>` (or `list --statuses ACTIVE`) via the helper and check the `status` is `ACTIVE` and the fields match what the developer confirmed.

2. **Code check** — make sure `KinoaResources` compiles / is referenced correctly in the app. If the game already uses resource keys as magic strings, offer to replace a couple of call sites with the new `KinoaResources` constants and run the app's build/test to prove it wires up. Prefer exercising the app's own build over a synthetic check — it proves the keys line up with how the game actually addresses items.

Report a short summary: how many resources are ACTIVE on the dashboard, where `KinoaResources` lives, and anything left in DRAFT / DEPRECATED / skipped for the developer to follow up.
