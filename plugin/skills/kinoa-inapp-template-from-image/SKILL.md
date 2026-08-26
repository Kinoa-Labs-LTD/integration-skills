---
name: kinoa-inapp-template-from-image
description: Turns a client-supplied mockup of an in-app pop-up (offer, bundle, milestone chase, mission board) into a Kinoa in-app template structure. Reads the image, decomposes it into the template's four element types — Image, Button, Text, Custom Element — picks the feature type (standard / mission / milestone), infers click actions, and emits the create-ready template JSON after the developer confirms it on an interactive HTML page. Use whenever someone wants to build a Kinoa in-app template from a design, screenshot, or Figma export — "make a template out of this mockup", "what elements does this offer screen need", "generate the in-app JSON from this picture". NOT for app-code integration (that is kinoa-api-integration) and NOT for resource templates / sellable items (that is kinoa-sync-resource-template-integration).
argument-hint: [path/to/mockup.png] [--name "Template name"]
allowed-tools: Bash(python *) Read Write Edit Glob Grep AskUserQuestion Agent
---

# In-app template from an image

A Kinoa **in-app template** is the reusable skeleton of a pop-up. The developer
integrates it once; operators then fill it in and ship many campaigns from it
with no further dev work. A template declares *slots*, not content:

| Bucket | What it is |
|---|---|
| `images` | Art slots the operator fills with a URL — background, product, prizes. |
| `buttons` | Interactive controls, each with the set of click actions it may perform. |
| `texts` | Copy slots the operator types into. |
| `customs` | Typed operator knobs (`string` / `numeric` / `boolean` / `enumeration`) that are not directly one of the above. |

On top of that a template carries a **feature type** — `standard`, `mission`,
or `milestone` — which decides whether it also gets a progression model.

This skill turns a picture of such a pop-up into that structure. It **never**
touches game code; the deliverable is a validated JSON payload, registered as
a DRAFT template on the dashboard via the `kinoa-dashboard-inapp-template`
helper (see *Phase 5*).

Read [`references/template-model.md`](references/template-model.md) for the full
field-by-field model before doing anything non-obvious.

---

## Phase 1 — Ingest

1. Resolve the image path from the argument. If none was given, ask for one —
   do not go hunting through the filesystem for "some mockup".
2. Confirm the file exists and is a PNG/JPEG/GIF/WebP. Note its pixel size:

   ```bash
   python "${CLAUDE_SKILL_DIR}/inapp_template_build.py" roles
   ```

   also prints the role vocabulary you will need in Phase 2 — run it now and
   keep the output.
3. If the developer supplied several images, **glance at every one before
   choosing** the structural source. Siblings are not reliably alternate states
   of the same pop-up: in real exports they are often a *different layout* of
   the same offer (a compact banner for the shop row or the out-of-moves
   screen), or an unrelated screen that landed in the same folder. Pick the one
   that shows the primary pop-up, treat true alternate states as corroboration,
   record other *layouts* under `unsupported` ("compact variant exists — a
   template is one fixed layout"), and ignore unrelated screens. One image →
   one template.

## Phase 2 — Analyse the image

This is the only step that needs vision. **Delegate it to a subagent** — it
keeps the transcript small and the analysis reproducible:

> Spawn one agent, hand it the image path and the `roles` output, and require
> it to return *only* the layout-analysis JSON. Its exact contract is
> `python "${CLAUDE_SKILL_DIR}/inapp_template_build.py" schema`.

Whoever performs the pass follows the same checklist, in this order:

1. **Find the panel.** The pop-up rarely fills the canvas — locate its bounds
   first, and express every later bbox relative to the whole image anyway
   (normalised 0..1, origin top-left).
2. **Background.** Is there full-bleed art behind the panel? → `background_image`.
3. **Copy hierarchy, top to bottom.** Largest headline → `header`. The line
   under or above it → `upper_text`. A descriptive paragraph → `body_text`. A
   line low in the panel → `bottom_text`. Small legal text at the very bottom →
   `fine_print`.
4. **Badges and prices.** A discount tag ("70% OFF") → `price_cut_badge`; leave
   `observed_text` empty-ish, because the client computes the number and
   substitutes it into `<#>% OFF`. A "x3 MORE"-style flash → `resource_badge`.
   A live price → `price_text`.

   A **struck-through price is a trap**: it is a real text element
   (`soft_billing_old_price`) only when the offer bills in *soft* currency and
   the operator types the old price by hand. When the offer bills through a
   store package id, the client draws the struck price itself and the correct
   answer is the client-rendered `price_before_sale`. Nothing in the picture
   separates the two. **Default to `price_before_sale`**, and only choose
   `soft_billing_old_price` when the CTA is clearly soft-currency (a gem/coin
   icon on the button, a price with no `$`/`€`). The builder flags the choice
   under `report.needs_confirmation` either way — ask the developer at Phase 4.
5. **Controls.** Every tappable thing: the corner "X" → `close_button`; the
   dominant one → `cta_button`; anything lesser → `secondary_button` or the
   specific role that matches its wording. Record `observed_text` verbatim —
   click-action inference reads it.

   Do **not** strain to pick a specific button role. `purchase_button` /
   `soft_purchase_button` / `ad_button` / `collect_button` are for controls whose
   wording or iconography makes the action unmistakable. When the label is just
   "CTA", or the mockup is a wireframe with no copy, use plain `cta_button` — it
   carries the full action menu, which is exactly what Kinoa's own production
   template does. A generic role with every action is correct; a specific role
   guessed wrong silently narrows what operators can ever configure.
6. **Progression.** A horizontal bar with checkpoint markers and prizes along
   it → milestone. A list of discrete tasks with individual states → mission.
7. **Art.** Remaining pictures: `product_image`, `resource_image`,
   `character_image`, `logo_image`, `badge_image`, `decoration_image`.

   Production art is usually **welded** — the mascot rides the product, the
   character is baked into the background scene. When you cannot tell whether
   layers are separable, use **one** image slot with the most encompassing role
   (usually `background_image`) instead of inventing layers the game engine may
   not have. A stylised **wordmark** ("COIN FRENZY!" in flame letters) sits on
   the header/logo boundary: if the copy would change per campaign it must be a
   `header` text slot; if it is brand art, `logo_image`. **When unsure, prefer
   `header`** — a wrong `header` degrades gracefully (the slot can be hidden and
   art shown instead), a wrong `logo_image` locks operators out of ever editing
   the copy.
8. **Operator knobs.** If part of the layout is plainly optional ("show the
   resource area or not", "how many items"), propose a custom element.

### Client-rendered zones — recognise, do not create

Some things that look like elements are drawn by the game client once the
operator configures the campaign. Report them with their real role so they show
up on the confirmation page, and the builder will keep them out of the payload:

`resource_area`, `price_before_sale`, `timer`, `grand_prize_area`.

Inventing template slots for these produces duplicate, unfillable fields — this
is the single most common way to get the structure wrong.

### Mechanics Kinoa cannot express — check both layers first

A template is only half the system: the configured **in-app instance** layers
scheduling, triggers, eligibility, per-player content bands, chosen click
actions and all mission/milestone progress state on top of it. Before writing
an `unsupported` entry, check the **capability map** in
[`references/template-model.md`](references/template-model.md) (backed by
[`references/inapp-instance-model.md`](references/inapp-instance-model.md)) —
these mockup patterns look impossible at template level but are handled at the
instance layer, and must NOT go to `unsupported`:

- per-task progress bars (each mission ships `current_score`/`goal_score`);
- sequential unlock of steps in a lane (sub-mission chains);
- a paid task among free ones (per-mission billing + package ids);
- a repeatable ladder (eligibility reset);
- "same popup, different numbers per player segment" (placeholder bands —
  one template, one in-app);
- hidden totals (all scores ship; concealing them is client rendering).

What genuinely does not fit either layer: repeating card groups as chrome
(rolling deal chains inside a pop-up, outside the features layer), dual-track
free+paid ladders, layout variants per placement, per-set bars, shared
retroactive unlock. (Info/tooltip controls are NOT a gap — the `custom` click
action + `customCtaNames` covers them; use the `info_button` role.)

**A shop screen is not an in-app.** A scrollable multi-SKU storefront (a shop
tab, a merchant grid) is a different surface entirely: Kinoa has no shop
feature — the app builds its own shop UI, optionally driven by Feature
Settings for dynamic content, which is a separate module unrelated to in-apps.
When the mockup turns out to be a shop screen, say so and stop — do not model
it as a template, do not cherry-pick one SKU, do not file it under
`unsupported` as if it were a missing template capability. **Do not force these into elements.** Name
each one under `unsupported`:

```json
{ "what": "serpentine chain of 6 visible deals shown as chrome, not missions",
  "why": "images/buttons/texts are singular named slots; only the features layer has arrays",
  "bbox": { "x": 0.1, "y": 0.3, "w": 0.8, "h": 0.4 } }
```

Then build the portable remainder anyway — background, header, CTA, close,
fine print almost always map cleanly. A partial template plus an honest list of
what did not fit is a useful result; a template that pretends to cover a
mechanic it cannot is not. Expect complex offers to yield several `unsupported`
entries, and say so plainly in the hand-off.

When a **repeating group** dominates the screen — a grid of SKU cards, a chain
of deal cards, a two-lane reward ladder — the group goes into `unsupported` as
one entry and the template captures only the chrome around it. Do **not**
cherry-pick one card as a "representative" element: that fabricates a slot the
operator cannot actually use. Chrome-only is the correct outcome there, not a
failure. On field runs against shipped-game offers, roughly half came out this
way.

Mine the **textual brief** too, when one accompanies the image: purchase-history
price escalation, cohort eligibility, hidden deal counts live in the text and
nowhere on the canvas. They become `unsupported` entries without a `bbox`.

### Picking the feature type

| Evidence on the image | `feature.type` |
|---|---|
| One progress bar, markers along it, a prize per marker, "12/50"-style counters, a score icon at the left end | `milestone` |
| A list of separate tasks, each with its own tick / progress, optionally grouped into sets, plus one combined bar | `mission` |
| Neither | `standard` |

For `milestone` count the markers into `feature.detected.milestone_count`; for
`mission` count the rows into `mission_count` and the groups into `set_count`.
Milestone scores in Kinoa are **aggregated**, not per-step: markers at 50 / 100 /
170 mean the bar shows 0/50, then 0/50, then 0/70.

### Two mechanical rules

- **Overlap.** Badges and stickers routinely overlap what they annotate. Order
  elements by the **top edge** of the bbox, then by the left edge — never by
  visual "importance". The builder applies the same rule, so an analysis that
  follows it round-trips unchanged.
- **Wireframes.** Clients often send an abstract wireframe whose boxes are
  labelled with their own role names rather than real art and copy. That is a
  perfectly good input: read the labels as the role, put the label text in
  `observed_text`, and size the background bbox to the panel outline. Do not
  lower confidence just because the art is missing.

Set an honest `confidence` per element. Anything below 0.5 gets flagged for the
developer rather than quietly shipped.

## Phase 3 — Build the payload

```bash
python "${CLAUDE_SKILL_DIR}/inapp_template_build.py" build \
  --analysis analysis.json \
  --game-id "$KINOA_GAME_ID" \
  --name "Summer Bundle" \
  --out build_result.json
```

The builder is deterministic and owns every policy decision: reading-order
index assignment (dense, unique across all four buckets), key slugification and
de-duplication, per-bucket defaults, the `Text Color` custom field every text
slot carries, click-action inference, and the feature block. Re-running it on
the same analysis always yields the same payload.

### Reuse before create

One template is meant to serve many in-apps. Before proposing a new template,
check whether an existing one already covers the mockup — the boxed
`one_cta_predefined` covers most single-CTA offers out of the box:

```bash
# fetch the game's templates (list, then get each full record into one array)
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py" list
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py" get --id <id>   # per template
python "${CLAUDE_SKILL_DIR}/inapp_template_build.py" match \
  --analysis analysis.json --templates game_templates.json
```

The matcher is deterministic: per template it returns `reuse` (every element
has a compatible slot, no un-hideable slot left over), `partial` (coverage ≥
0.5 with named `missing` elements), or `no` — plus the element→slot `mapping`.
Matching requires FULL records (a list summary has no button detail).

- **`reuse`** → put the choice to the developer via AskUserQuestion (reuse vs
  new template anyway). On reuse, the deliverable changes: write
  `<template_key>.reuse.json` — the chosen `template_key`/`template_id` and the
  element→slot mapping — and STOP: no confirm page, no create. The operator
  configures the in-app on that template in the dashboard; the mapping file
  tells them which slot carries which part of the mockup.
- **`partial`** → show the developer what is missing and offer the choice:
  create the new template as usual, or reuse anyway (configure what fits; the
  missing pieces stay client-side). Evolving an existing template is a
  Dashboard operation — where its dependencies are visible — never an API
  edit from this workflow.
- **`no` everywhere** → proceed to Phase 4 as usual.

Read `report.warnings`, `report.unmapped`, `report.needs_confirmation` and
`validation` before moving on. **Never drop an `unmapped` entry silently** —
surface each one to the developer. `needs_confirmation` holds the questions the
image genuinely cannot answer (currently the struck-price case): put each one to
the developer at Phase 4 rather than picking for them.

`$KINOA_GAME_ID` comes from `~/.kinoa/session.env` if a Kinoa session was set
up. It is optional here; the payload is valid without it.

## Phase 4 — Confirm with the developer

```bash
python "${CLAUDE_SKILL_DIR}/generate_confirm_page.py" \
  --build build_result.json --image mockup.png --out confirm.html
```

This opens an interactive page: the mockup with a labelled box per detected
element on one side, the editable structure on the other. The developer renames,
retypes, moves elements between buckets, fixes click actions, deletes wrong
guesses and adds whatever was missed.

The browser cannot write to disk, so the page hands the result back two ways —
a **Download JSON** button, or **Copy to clipboard**. Ask which they used, then
read the confirmed payload back in. Do not proceed on the un-confirmed payload:
a vision pass is a proposal, not a verdict.

Re-validate whatever comes back:

```bash
python "${CLAUDE_SKILL_DIR}/inapp_template_build.py" validate --payload confirmed.json
```

## Phase 5 — Register on the dashboard

Write the confirmed payload next to the mockup as
`<template_key>.template.json`, then create the draft by delegating to the
dashboard helper (co-installed sibling):

```bash
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py" \
  create --payload <template_key>.template.json
```

The server answers with the full record and `status: "draft"` — report the new
template `id` back to the developer, together with element counts per bucket,
the feature type, and anything the confirmation page left flagged.

**Templates stay in `draft` by decision.** Activation is deliberately out of
this tooling's scope: the operator activates the template on the dashboard
(*Game Settings → In-Apps*) as part of configuring the actual in-app on top of
it. Do not attempt to activate from here and do not treat `draft` as an
unfinished state — it is this workflow's finished deliverable.

**Once the draft exists, changes to it belong to the Dashboard** (*Game
Settings → In-Apps*) — the operator sees the template's dependencies there
(whether in-apps already build on it) before touching anything. Do not offer
to revise a created template by editing and re-sending JSON; the workflow's
job ends at the created draft. The helper's `update` exists for explicit
operator-initiated admin tasks, not as a revision loop. **Never delete** — the helper deliberately
exposes no delete; a template with related in-app messages must never be
removed (`has-related` reports that signal).

If the developer only wants the JSON, stop after writing the file — creating
the draft is the default, not an obligation.

---

## Hard rules

1. **No direct API calls.** Both local helpers are offline; every admin call
   (create/update/list) is delegated to `kinoa-dashboard-inapp-template`, the
   same way other workflows delegate to their dashboard helpers. Read
   `~/.kinoa/session.env` only via `kinoa_init.py show` — never `cat` (that
   would print the admin bearer token into the transcript). Never emit
   dashboard calls or bearer tokens into generated game code.
2. **The developer confirms before anything is final.** Phase 4 is not optional.
3. **Client-rendered zones never become elements.** See the list above.
4. **`unmapped` and low-confidence detections are always surfaced.**
5. **Indexes are assigned by the builder**, never by the analysis and never by
   hand — they must stay dense and unique across all four buckets.
6. **`featureType: "standard"` ⇒ `features: null`.** Any other feature type
   requires its matching `features.<type>` block.
7. **One image, one template.** Do not merge several mockups into one structure.
