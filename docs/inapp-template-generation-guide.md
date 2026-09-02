# Generating In-App Templates from Design Mockups

## What this module does

Hand this module a designer's mockup of an in-app pop-up — a special offer, a
bundle, a milestone chase, a mission board — and it produces a ready-to-configure
**in-app template** on your Kinoa Dashboard. The whole run happens inside Claude
Code with the Kinoa plugin installed: you point at an image, review what was
detected, confirm it, and the template is registered.

Kinoa splits every pop-up into two layers, and the split is the reason this
module exists:

| Layer | Owned by | Created how often | Contains |
|---|---|---|---|
| **Template** | Developer | Once per layout | *Slots* — a background image, a headline, one main CTA and the set of actions it may perform |
| **In-app (campaign)** | Operator / LiveOps | Many per template | The actual content — art URLs, copy, prices, rewards, schedule, triggers, audiences, capping, per-segment values |

A template holds no copy, no art, no prices and no schedule. It is the reusable
skeleton a developer integrates once; from then on LiveOps ships campaign after
campaign on top of it with no further development work. So the goal of a run is
**not** "one template per mockup" — it is the smallest set of templates that
covers your designs, which is why existing templates are checked first and reuse
is proposed whenever one already fits. Each run delivers a template registered as
a **draft** on the Dashboard, plus a local JSON copy of its shape.

## Prerequisites

**1. Claude Code with the Kinoa plugin.** Two commands, run once per machine:

```bash
claude plugin marketplace add Kinoa-Labs-LTD/integration-skills
claude plugin install kinoa-dashboard@kinoa
```

Restart Claude Code afterwards. Commands are namespaced with the plugin name,
e.g. `/kinoa-dashboard:kinoa-inapp-template-from-image`. For automatic updates,
open `/plugin` → **Marketplaces** → `kinoa` → **Enable auto-update**.

**2. Kinoa credentials.** Take the **game ID**, **game secret** and a **session
token** from your Kinoa Dashboard under **Integration**, and configure them once
with `/kinoa-dashboard:kinoa-api-integration init`. If your game is integrated
through the Kinoa Unity SDK rather than the direct API, say so — the init step
validates the game's integration type and needs to know it is an SDK game. The
session token is short-lived — roughly **24 hours**; when it expires, Dashboard
calls fail with `401` and you re-run `init` with a fresh token.

**3. A mockup image.** PNG or JPEG (GIF and WebP also work), given as a local
file **or a URL** — a link to the image on your wiki, CDN or file share works as
well as a path; it is downloaded for the analysis. Finished art and abstract
wireframes are both valid — if a wireframe's boxes are labelled ("Background",
"Header", "CTA"), those labels are read as the element roles.

## How to run it

```
/kinoa-dashboard:kinoa-inapp-template-from-image path/to/mockup.png --name "Summer Bundle"
/kinoa-dashboard:kinoa-inapp-template-from-image https://wiki.example.com/mockups/summer-bundle.png
```

`--name` is optional. What happens next:

**1. The image is read.** One image produces one template. If you supply several,
one is chosen as the structural source; true alternate states of the same pop-up
serve as corroboration, while a *different layout* of the same offer (a compact
banner for a shop row) is reported separately — a template is one fixed layout.

**2. The mockup is decomposed** into elements — **Images**, **Buttons**,
**Texts** and **Custom Elements** — and a **feature type** is chosen:
`standard` (no progression), `mission` (a list of discrete tasks) or `milestone`
(one progress bar with checkpoints and a prize per checkpoint). For mission and
milestone templates the progression's own CTA menus (what a completed task or a
reached checkpoint lets the operator offer) are read off the art when the
buttons are legible — a "Claim" button becomes `collect_resource`, a price
becomes `billing`. When nothing is legible, nothing is invented. Display order,
element keys and slot defaults are all derived deterministically, so the same
mockup always yields the same structure.

**3. Your existing templates are checked first.** If one already covers the
design, reuse is proposed — with a mapping telling the operator which existing
slot carries which part of your mockup. Kinoa's boxed **One CTA** template covers
most single-CTA offers, so a plain "buy this bundle" mockup routinely needs no new
template at all. Partial matches are listed with their missing elements.

**4. You review and confirm.** When a new template is warranted, an interactive
HTML page opens: the mockup with a labelled box per detected element on one side,
the editable structure on the other. Rename elements, change their type, move
them between buckets, correct click actions, delete wrong guesses, add whatever
was missed. Mission and milestone templates additionally show pickers for the
progression CTA menus, pre-selected with whatever was read off the art. What
you see on the page is the whole structure: a field is either visible there or
required by the API — nothing else is silently added. Anything uncertain is
flagged for your decision — a low-confidence detection, or a struck-through
price that could be either a real text slot or a client-rendered one. Nothing
is created before you confirm.

Your corrections on the page — elements the analysis missed, boxes you moved,
false positives you un-ticked — are recorded to improve future detection. Only
the corrections and a fingerprint of the image travel; the mockup itself never
leaves your machine.

**5. The template is created as a draft**, and you get its `id`, the element count
per bucket, the feature type and anything still flagged. The mockup itself is
attached as the template's **tip image** — its face in the Dashboard constructor,
so operators picking a template see the design it came from (say so if you'd
rather skip that). The confirmed payload is written next to the mockup as JSON —
keep it in your project as the canonical copy of the template's shape and the
base for any later revision.

Two deliberate boundaries:

- **Templates stay in `draft`.** Activation belongs to the operator, in the
  Dashboard under *Game Settings → In-Apps*, as part of configuring the actual
  in-app on top of the template. `draft` is this workflow's finished state, not
  an unfinished one.
- **Nothing is ever deleted.** The tooling exposes no delete for templates at
  all (see the FAQ).

## What maps and what doesn't

### Client-rendered zones — recognised, deliberately not slots

Four things look like elements on a mockup but are drawn by the game client once
the operator configures the campaign. They are reported so you can see they were
noticed, and kept out of the template — creating slots for them produces
duplicate fields nobody can fill.

| Zone | Where it really comes from |
|---|---|
| Resource area | Appears automatically once resources are attached to the CTA |
| Price before sale (strike-through) | Automatic when a pre-discount store package is configured |
| Countdown timer | Made visible by the operator in the campaign's trigger step |
| Grand prize area | Milestone only — echoes the final milestone's reward |

### Handled at the in-app configuration layer

These patterns look impossible to express as slots, but they are configured on
the in-app rather than the template — so they are **not** reported as gaps:

| Pattern on the mockup | Configured as |
|---|---|
| Several tasks, each with its own progress bar | Per-mission current/goal scores |
| Steps in a lane that unlock in sequence | Sub-mission chains; locked rows simply aren't sent yet |
| One combined bar across all task sets | The shared cross-set progress bar |
| A paid task among free ones | Per-mission purchase gating with its own store packages |
| A ladder the player can run again | Eligibility capping — the final claim resets the instance |
| "Same pop-up, different numbers or art per segment" | Placeholders — type `${placeholder_key}` into any input while configuring the in-app, then fill the per-segment values table (rows filtered by Player State fields, e.g. `Level: 0–10 → Image X`, `Level: 11–100 → Image Y`). One template, one in-app. |
| An info / rules / preview control (an "i" button) | The `custom` click action with a named CTA the client implements |
| Progress totals hidden from the player | A client rendering choice; the data always ships |

### True gaps — reported honestly, and the rest still builds

| Pattern | Why it doesn't fit |
|---|---|
| A repeating card group used as chrome (a rolling or serpentine chain of deals inside the pop-up) | Slots are singular, named fields; only the mission/milestone layer has real arrays |
| A dual-track ladder (a free lane and a paid lane, tier by tier) | Each step has exactly one button and one reward set; there is no second parallel column |
| Layout variants of the same offer per placement (full panel + compact banner) | One layout per template — two layouts means two templates and two in-apps |
| A progress bar per task *set* | Bars exist per mission and across all sets, not per set |
| One purchase that retroactively unlocks all accrued rewards | Completion actions are strictly per mission |

Anything in this list is named explicitly, and the portable remainder of the
mockup — background, header, CTA, close button, fine print — is still built.
Complex offers routinely produce a few such entries. Where a repeating group
dominates the screen the template captures only the chrome around it; a single
card is never cherry-picked as a "representative" slot, since that would
fabricate a field the operator cannot use.

### Shop screens are out of scope

A scrollable multi-SKU storefront — a shop tab, a merchant grid — is not an
in-app. Kinoa has no shop feature: the app builds its own shop UI, optionally
driven by dynamic content from **Feature Settings**, which is a separate module
unrelated to in-apps. If your mockup turns out to be a shop screen, the module
says so and stops rather than modelling it as a template.

## The element model in brief

Every template is four buckets of slots:

| Bucket | What it holds |
|---|---|
| **Images** | Art slots the operator fills with a URL — background, product, prizes. Art is never uploaded into the template. |
| **Buttons** | Interactive controls, each carrying the set of click actions it may perform. |
| **Texts** | Copy slots the operator types into. Each carries a text-colour setting; badge-style texts also carry a background colour. |
| **Custom Elements** | Typed operator knobs that are none of the above — `string`, `numeric`, `boolean` or `enumeration` (e.g. "show the resource area", "how many items"). |

Most slots can be marked hideable, so an operator may switch them off per
campaign; the main CTA cannot be hidden.

**Click actions.** A button's action list is the **menu the operator chooses
from**, not one wired action — which is why a single main CTA usually carries
several:

`close`, `show_ad`, `billing` (real money), `soft_billing` (in-game currency),
`collect_resource`, `deep_link` (navigate inside the game), `web_link`,
`promise_rewards`, `update_app_version`, and `custom`.

`custom` is how client-implemented behaviour is expressed: the button also
carries one or more CTA names (for example `Info`) and your client implements the
named behaviour — the right answer for info, rules and preview controls.

Because the list is a menu, generosity beats precision: a generic CTA offering
every relevant action is correct, while a narrow list guessed from a label
silently limits what operators can ever configure on that button.

**Text substitution.** `<br>` in operator copy is a line break; `<#>` is a
substitution token — the discount percentage in a price-cut badge (`<#>% OFF`),
or the score icon in milestone copy. **One hard limit:** a template's own
`description` may not exceed **50 characters** (element descriptions are uncapped).

## Template reuse

One template is meant to serve many in-apps, so reuse is checked before anything
new is proposed. Each of your existing templates is compared against the mockup
and classified:

- **Reuse** — every detected element has a compatible slot and nothing unhideable
  is left over. You confirm, and no template is created at all; instead you get a
  mapping of which existing slot carries which part of the mockup, so the operator
  can configure the campaign immediately.
- **Partial** — most of the mockup fits and the missing elements are named. You
  choose between extending a draft copy of that template and creating a new one.
- **No match** — the flow proceeds to a new template.

**Accept reuse** when the differences are content, not structure — art, copy,
prices, reward amounts, per-segment numbers. All of that belongs to the in-app.
**Mint a new template** when the structure differs: another progression model
(standard vs mission vs milestone), a genuinely different layout, or elements with
no compatible slot anywhere.

Fewer templates is better: every new one is a shape someone has to maintain — and
one that live campaigns may come to depend on.

## FAQ and troubleshooting

**A Dashboard call failed with `401`.** Your session token expired — it lasts
about 24 hours. Fetch a new one from Dashboard → **Integration**, re-run
`/kinoa-dashboard:kinoa-api-integration init`, then re-run the template command.
Nothing else needs redoing.

**My mockup is a shop screen — can I still get a template?** No, and that is the
right answer: a shop is your app's own UI, not an in-app pop-up, and Kinoa has no
shop feature. To make its content remotely configurable, look at **Feature
Settings** — a separate module.

**Something was flagged as unsupported. Is my integration broken?** No.
Everything that mapped is built and works normally. A flagged mechanic simply has
no representation in the template or campaign layers, so your client implements it
itself — or you reshape the design so it falls inside what the platform expresses,
for instance turning a hand-drawn chain of deals into a mission feature.

**Can I delete a template?** Not from this tooling, by design: deleting one
orphans every in-app message built from it, historical ones included. Removal is a
deliberate Dashboard action, taken only when nothing references the template — and
the tooling can tell you whether a template still has related in-app messages
before you change or retire it.

**The Dashboard highlights CTA fields in red when I open my milestone template.**
That is intended, not a defect. Progression CTA menus are only filled in when
they could be read off your mockup; when they couldn't, the choice is left to
the operator rather than guessed — and the Dashboard marks the decision still
to be made ("At least one CTA must be selected") on the template's first save.
Mission templates always carry at least `close` as the completion CTA, because
the API requires one there.

**Why is my template still a draft?** Because that is this workflow's finished
state. Activation happens in the Dashboard (*Game Settings → In-Apps*) when the
operator configures the first in-app on top of the template, so activation and the
campaign that needs it are decided together.

**The review page — how do I hand the result back?** The page runs in your browser
and cannot write to disk, so it offers **Download JSON** or **Copy to clipboard**.
Use either and say which one you used; the confirmed structure is read back in and
re-validated before anything is created.

**I need to change a template after it was created.** Make the change in the
Kinoa Dashboard (*Game Settings → In-Apps*), not by editing JSON: the Dashboard
shows you the template's dependencies — whether in-app messages already build on
it — before you touch anything. A change that drops a slot can break live
campaigns as surely as a delete would, and the Dashboard is where that risk is
visible. The local JSON written next to your mockup remains useful as the record
of what was generated.

**Can I run this without Kinoa credentials?** The analysis, review page and JSON
payload work offline — useful for sizing up a design before a game is set up.
Registering the draft on the Dashboard is the only step that needs credentials.
