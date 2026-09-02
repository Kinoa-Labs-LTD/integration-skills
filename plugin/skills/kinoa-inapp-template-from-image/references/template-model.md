# The Kinoa in-app template model

Canonical field reference for `kinoa-inapp-template-from-image`.

**Sources.** This document describes the Kinoa message-templates API and the
in-app template model as they run in production. It is built from:

- **live production calls** — the full CRUD contract and routes, the
  `Key-Inflection` wire format, create for all three feature types, the
  50-char `description` limit, the element model as stored and read back,
  and template matching against the boxed `one_cta_predefined`;
- **production template records** — `One CTA Template`, `Monster v2`,
  `Monster milestones template`, `Mission v1_2` — for field shapes;
- the ***Integration guideline*** wiki page for product semantics; such
  statements are marked **(wiki)** throughout.

Keep this document in step with the platform: when the API grows or changes,
update it from the same kinds of sources.

---

## Top-level record

```json
{
  "name": "One CTA Template",
  "key": "one_cta_predefined",
  "description": "",
  "gameId": "<uuid>",
  "tipImageBlob": "<base64 png | null>",
  "tipImageUrl": "<url | null>",
  "images": [], "buttons": [], "texts": [], "customs": [],
  "featureType": "standard",
  "features": {}
}
```

`features` on a standard template: the **create/update contract sends `{}`**;
older GET records return `null`. Accept both when reading. Create bodies also
carry `tagsIds: []`.

Server-owned, never sent on create: `id`, `createdAt`, `updatedAt`, `status`,
`authorId`, `updatedAuthorId`, `system`, `hidden`, `deprecationReason`,
`availableActions`.

| Field | Notes |
|---|---|
| `key` | Observed values are snake_case, but `Monster_v2` proves uppercase is accepted. The builder emits `^[a-zA-Z][a-zA-Z0-9_]*$`. |
| `tipImageBlob` / `tipImageUrl` | The template's face in the dashboard. **Verified contract:** `tipImageUrl` goes as a plain string in the JSON body; a blob is NOT accepted via JSON (500) — it is uploaded by a separate image-only `PATCH {base}/{id}` with `multipart/form-data`, single part `tip_image_blob` (binary, snake_case field name even under Key-Inflection), which leaves the rest of the record untouched. The workflow attaches the source mockup here by default. |
| `status` | Observed only as `"active"`. No DRAFT/ACTIVE/DEPRECATED ladder has been seen — do not assume the resource-template lifecycle applies here. |
| `availableActions` | Observed: `show`, `clone`, `deprecate`, `export_to_game`, `hide`. The `system` template omits `deprecate`/`export_to_game`. |

## The four element buckets

Every element carries `key`, `name`, `index`, `description`, `customFields`.

### `index` — one sequence, not four

In `Mission v1_2` and `Monster milestones template`, `index` is **unique across
all four buckets** (0..14 with no repeats). `One CTA Template` violates this —
`images[0].index == 0` and `customs[0].index == 0` — but it is the oldest,
`system: true` record. The builder assigns a dense, globally unique 0..N-1 in
reading order, which satisfies both readings. Order is display order.

### `canBeHidden`

Whether the operator may switch the slot off. **(wiki)** The Main CTA
explicitly *cannot* be hidden; the Background Image *can*, and hiding it puts
the rest of the pop-up into dark mode. Absent in the oldest records, which
should be read as `false`.

### `images`

```json
{ "key": "background_image", "name": "Background Image", "index": 0,
  "size": { "width": 10000, "height": 10000, "maxSize": 16000 },
  "description": "", "canBeHidden": true, "customFields": [] }
```

`size` is optional — create accepts an image without it and the echo carries
none (verified live 2026-08-31); operators set real dimensions on the
dashboard. **The generator never invents it.** **(wiki)** Art is supplied by
the operator as a **URL**, never uploaded into the template.

### `buttons`

```json
{ "key": "cta", "name": "CTA", "index": 4, "textLimit": 255,
  "description": "", "canBeHidden": false, "customFields": [],
  "backgroundImg": { "width": 10000, "height": 10000, "maxSize": 10000 },
  "clickActionType": ["close", "show_ad", "billing", "collect_resource", "deep_link", "soft_billing"],
  "requiredItemsCount": 1 }
```

`clickActionType` is the **menu of actions the operator may choose from**, not
a single wired action — hence the six-entry array on a single CTA.
`requiredItemsCount` appears only alongside `collect_resource` and
`promise_rewards`. `textLimit` and `backgroundImg` are optional (create
accepts buttons without them, verified live) — **the generator never invents
them**; a field is either confirmed on the page or set by the operator on the
dashboard.

### `texts`

```json
{ "key": "header", "name": "Header", "index": 1, "nullable": false,
  "textLimit": 255, "description": "", "canBeHidden": true,
  "customFields": [ { "key": "text_color", "kind": "string", "name": "Text color",
                      "nullable": false, "description": "", "defaultValue": "#FFFFFF" } ] }
```

**(wiki)** Every text element carries a hex `Text Color` custom field; the
Resource Badge additionally carries `Badge BG color`. The builder extends the
same pattern to `value_badge` (a corpus-driven role): badge-style text roles
carry `badge_color` alongside `text_color` — see `default_custom_fields` in the
`roles` output for the authoritative per-role list. `<br>` in operator copy
is a line break. `<#>` is a substitution token — the discount percentage in the
Price Cut Badge (`<#>% OFF`), the score icon in milestone copy.

### `customs`

Typed operator knobs that are none of the above.

```json
{ "key": "show_resource_area", "kind": "boolean", "name": "Show Resource Area",
  "index": 0, "nullable": true, "description": "", "canBeHidden": true,
  "customFields": [], "defaultValue": false }
```

`kind` ∈ `string`, `numeric`, `boolean`, `enumeration`. Enumerations carry
`enumValues` as a **comma-separated string** (`"next,back,to first,to last"`)
and sometimes an `enumerationId` UUID referencing a shared enumeration — the
builder never invents those ids.

### `customFields` (on any element)

`kind` here additionally allows **`image`** (custom *elements* stay
constrained to the four KINDS — the dashboard states "supported types:
enumeration, string, boolean, numeric"). Shape: `key`, `kind`, `name`, `nullable`,
`description`, `defaultValue`, plus `enumValues` / `enumerationId` for
enumerations. Mission features additionally use `scope` ∈ `PER_MISSION`,
`PER_SET`, `PER_PROGRESS_BAR`, `PER_MILESTONE`.

## Click actions

| Value | Meaning **(wiki)** |
|---|---|
| `close` | Dismiss the pop-up. Items may be shown but are not granted. |
| `show_ad` | Play a rewarded ad, then grant the configured items. Closing early re-opens the pop-up. |
| `billing` | Real-money purchase; price comes from the store package id. Failure returns the player to the offer. |
| `soft_billing` | In-game-currency purchase. Insufficient balance routes to a currency offer, then back to this one. |
| `collect_resource` | Grant the configured items outright. |
| `deep_link` | Navigate inside the game — open shop, open screen X, start level. |
| `web_link` | Open an external URL. Implied by the wiki's business cases; it has no row in the wiki's button table but is present in the JSON. |
| `promise_rewards` | Present in the JSON records; absent from the wiki. |
| `update_app_version` | Present in the JSON records; absent from the wiki. |
| `custom` | Client-defined CTA. The button additionally carries **`customCtaNames`** (e.g. `["Info"]`); the game client implements the named behaviour. Verified end-to-end via the dashboard POST/PATCH contract — this is how info/rules/preview controls are expressed. |

## Feature types

`featureType` ∈ `standard` | `mission` | `milestone`. `standard` ⇒
`features: null`; otherwise `features.<type>` must be present.

### `milestone`

```json
{ "milestone": { "key": "main_progressbar", "name": "Main Progressbar",
  "limit": 3, "description": "",
  "mainActionTypes": [ …all nine click actions… ],
  "milestonesActionTypes": [ …all nine click actions… ] } }
```

`limit` is the number of milestones the template supports. Feature-level
`customFields` here carry **no `scope`** (unlike missions' PER_MISSION /
PER_SET) — live capture 2026-08-31.

**CTA menus — required-ness verified live (API + UI, 2026-08-31):**
`mainActionTypes`/`milestonesActionTypes` are optional for the create API
(200 without them; nothing substituted server-side) but the dashboard refuses
to SAVE without them ("At least one CTA must be selected"). The generator
therefore sends them **only when derived from the mockup** (the bar's main
button; claim buttons on markers) and otherwise omits them — the red highlight
on the dashboard is the intended "operator chooses consciously" flow. Mission
`completionCta` + `progressBar` are hard-required by the API (422:
"missing required keys: completion_cta, progress_bar"); `completionCta` is
mockup-derived with a neutral `["close"]` fallback (flagged in the build
report). `activeProgressCta` and `missionLayout` are optional; the server
stores no defaults for them. **(wiki)** Scores
are **aggregated, not per-step**: markers at 50 / 100 / 170 display as 0/50,
0/50, 0/70. The bar always starts at 0. One reward shows directly; two or more
collapse into a client-provided chest with a tooltip. The last milestone's
reward is echoed in a client-rendered grand-prize area.

### `mission`

```json
{ "mission": { "key": "missions", "name": "Missions", "description": "",
  "progressBar": { "display": "show_for_all_sets_combined",
                   "completionBarCta": ["collect_resource"] },
  "customFields": [],
  "completionCta": ["close","collect_resource","billing","web_link","deep_link","show_ad"],
  "activeProgressCta": ["close","web_link","deep_link","show_ad"],
  "maxPlacements": 10, "maxSetsCount": 7, "minPlacements": 1, "minSetsCount": 1 } }
```

Live-verified additions (dashboard PATCH captures, 2026-08-27):
**`missionLayout` ∈ `parallel` | `sequential`** is a template-level field —
parallel activates every placement in a set at once; sequential unlocks
placements one at a time (the client receives upcoming ones as locked
previews). `progressBar.display` has (at least) two values:
`show_for_all_sets_combined` (with `completionBarCta` and an optional
**`maxMilestones`** number) and **`dont_show_at_all`** (empty
`completionBarCta`). Feature-level `customFields` carry `scope` `PER_MISSION`
or `PER_SET` (live-verified; fields OUTSIDE the feature are implicitly global —
same value on every row). The dashboard UI also sends `showActiveProgressCTA`
and per-field `id`/`new`/`index` junk in requests — the server strips them;
never rely on them. `enumValues` are normalised on write ("Apple, orange" →
"Apple,orange") and enumerations get server-assigned `enumerationId`s.

## Client-rendered zones — never template elements

**(wiki)** These appear on mockups but the game client draws them once the
operator configures the campaign. Creating slots for them yields duplicate,
unfillable fields:

| Zone | Why |
|---|---|
| Resource Area | Appears automatically once resources are attached to the CTA. |
| Price Before Sale | Struck-through automatically when a pre-discount package id is set. Distinct from the *Soft Billing* price-before-sale, which **is** a real text element. |
| Timer | Rendered when the operator makes it visible in the trigger step. |
| Grand Prize area | Milestone only — echoes the final milestone's reward. |

## Template vs in-app instance — two layers, one popup

A **template** declares slots; an **in-app instance** is the configured
campaign the client receives (see [`inapp-instance-model.md`](inapp-instance-model.md)).
Scheduling, triggers, eligibility, capping, the timer, the lobby icon, the
chosen click action, per-player content bands, mission/milestone progress
state — all of that lives at the instance layer. **Judging a mockup against
the template model alone produces false gaps**; the first version of this
table made exactly that mistake.

## Capability map (verified against instance payloads + SDK e2e tests)

Field runs against 16 real offers from 8 shipped casual games surfaced these
patterns. Verdicts below are cross-checked against six real instance payloads
and the Kinoa Unity SDK's Alt e2e suites — not just the template records.

**Covered by the platform (do NOT report as `unsupported`):**

| Pattern seen on mockups | Where it is handled |
|---|---|
| Per-task progress bars (N missions, each with its own fill) | Instance: every mission carries `current_score` / `goal_score`; e2e-asserted. |
| Sequential unlock of steps in a lane | Sub-mission chains (`sub_mission_number`): the server activates the next step when the previous is *reached*. Locked rows are absent from the payload, so a padlock is a client rendering of template knowledge, not data. |
| Combined progress bar across all sets | `mission_state.progress_bar_state` (one shared bar, cumulative milestone thresholds). |
| Per-mission purchase gating (a paid task among free ones) | `completion_cta: billing` + per-mission `google/apple_package_id`. |
| Repeatable milestone ladder ("run it again") | Eligibility capping: final claim resets the same instance, `eligibility.original` times. |
| "Same popup, different numbers/art per player segment" | Placeholder bands: one template + one in-app, per-band element values. Not a variant, not unsupported. |
| Struck-through store price | `packages.*_discount_package_id` pair → client renders the strike-through. |
| Countdown timer visibility | `countdown_timer.is_visible` on the instance envelope. |
| Info/preview control ("i" / "?" opening rules in place) | The `custom` click action + `customCtaNames` on the button (verified in the dashboard POST/PATCH contract); the client implements the named CTA. The `info_button` role maps to it directly. |
| Hidden totals (deal/milestone counts concealed from the player) | Not a platform concern: all scores ship up front; concealment is a client rendering choice. The *analysis* still omits unknown counts rather than fabricating them. |

**True gaps (template + instance + SDK all lack them):**

| Pattern | Frequency in the corpus sample | What is missing |
|---|---|---|
| **Repeating card group as chrome** — serpentine/rolling deal chains inside a pop-up, outside the features layer | recurring | `data.images/buttons/texts/customs` are keyed maps of singular slots; features (`steps[]`, `active_missions[]`) are the only real arrays. No generic "repeat this element N times". |
| *(out of scope, not a gap)* **Shop screens / multi-SKU grids** | ~a third of the corpus "offers" were actually shop screens | A shop is not an in-app at all — there is no shop feature in Kinoa; the app implements its own shop UI. Feature Settings can drive dynamic shop content, but that is a separate module unrelated to in-apps and templates. A shop-screen mockup should be recognised and declined as out of scope, not modelled as a template. |
| **Dual-track reward ladder** (free lane + paid lane, tier by tier) | 2 of 16 | `progress_bar_state` is singular; each step/milestone has exactly one `button` and one `resources[]`. No second parallel reward column. |
| **Layout variants per placement** — full panel and compact banner of the same offer | 5 of 16 | `placement` is a slot id, not a variant selector; one `template_key` per in-app record. Two layouts = two templates + two in-apps. |
| **Per-set progress bar** | 1 of 16 | The set object (`active_set_progress`) has no score field; only per-mission and cross-set bars exist. |
| **Shared retroactive unlock** — one purchase unlocks all accrued rewards | 1 of 16 | `completion_cta` is strictly per-mission; `finished_common_submissions_rows` exists but is never populated or consumed anywhere. |

## API — the dashboard CRUD

Verified live against production
(`https://dashboard.kinoa.io/api/message_templates`). Admin
surface: bearer + Game/Game-Id headers, wrapped by the
`kinoa-dashboard-inapp-template` helper.

| Route | Notes |
|---|---|
| `GET /api/message_templates?page&rows&sort_by&sort_direction&selectedFilters[]=status&status[]=…` | Paged list, filterable by `draft`/`active`. |
| `GET /api/message_templates/{id}` | Full record. |
| `POST /api/message_templates` | Create → returns the record with `status: "draft"`. |
| `PATCH /api/message_templates/{id}` | Full-body update. |
| `GET /api/message_templates/{id}/has_related_in_app_messages` | `{"hasRelatedInAppMessages": bool}` — the delete blocker signal. |
| `DELETE /api/message_templates/{id}` | Exists server-side. **Deliberately NOT exposed by the helper** — a template with related in-apps must never be deleted, and delete stays out of the tooling entirely. |

**Wire format (verified live): one case everywhere — camelCase — held in
place by the `Key-Inflection: camel` header.** The API inflects key case per
request: without the header it speaks snake_case, with it camelCase in both
directions (the dashboard UI always sends it, which is why browser captures
are camelCase). The `kinoa-dashboard-inapp-template` helper pins the header on
every call, so builder payloads, wire traffic, responses and every reference
record in this document share a single canonical camelCase — **no key
conversion exists anywhere in the toolchain**. The header is load-bearing: a
camelCase body sent WITHOUT it is parsed by a snake-expecting deserializer and
every case-differing field is silently dropped (200 with data loss); a record
created that way reads back *looking* trimmed — the fields were never stored.
Keep the confirmed payload file as the source of truth for updates. Server
limits observed live: template `description` ≤ 50 chars (422 otherwise;
element descriptions are not capped).

Lifecycle observed so far: `draft` → `active`. A draft's `availableActions`
(list response) are `show, update, clone, destroy, activate, export_to_game` —
so promotion is the **`activate`** action — deliberately NOT exposed by the
tooling: templates are left in `draft` and the operator activates on the
dashboard while configuring the in-app. Hard delete is `destroy`
(likewise not exposed). The list also
carries **`inAppsCount`** per template — the numeric twin of the has-related
delete-blocker check — plus `buttonsCount` / `imagesCount` / `textsCount` /
`hasImage` and `author` / `updatedAuthor` objects. `enumValues` are normalised
server-side (`"Apple, Orange"` → `"Apple,Orange"` + a server-assigned
`enumerationId`). The dashboard manages templates under *Game Settings →
In-Apps*; campaigns under *Communication → In-App*.

## Runtime instrumentation **(wiki)**

Templates are observable through predefined events that all carry `in_app_id`:
`in_app_impression`, `in_app_click`, `in_app_close`, `collected_resource`, and
`watch_ad` / `payment`. Kinoa also emits `inApp-received` / `inApp-sent` debug
events. Pop-ups queue in a **virtual inbox** until the player reaches a place
the game allows one to show.
