# The in-app instance — what the client actually receives

Companion to [`template-model.md`](template-model.md). A **template** is the
skeleton an operator builds on; an **in-app** is the configured instance the
game client receives at runtime. Things absent from the template model are
often configured at this layer — judging a mockup against the template model
alone produces false gaps.

**Provenance.** Six real instance payloads (E2E fixtures covering One CTA,
Monster v2, milestones, missions, multi-feature-config, score-by-event-field)
plus the Kinoa Unity SDK's runtime models and Alt e2e suites
(`KinoaMessagingServiceTests` — 74 tests, `KinoaMissionsInAppsTests` — 10).

## Envelope (around the template-derived content)

One root key `in_app`. Beyond `data` (the content), the envelope carries the
campaign machinery — none of it exists at template level:

`name`, `order` (inbox priority), `scheduling.start_time_ms/end_time_ms`,
`trigger_type` (`event | flow | push | manual`), `uuid` (delivery instance) vs
`message_id` (campaign — the `in_app_id` used by analytics events),
`countdown_timer { is_visible, end_timestamp (s), extra_life_time }` — **this is
where the template model's "Timer" client-rendered zone gets its config**,
`lobby_icon { content, content_type, placement, is_in_app_trigger, text, score }`,
`placement { id }`, `capping` (total / eligibility / recurrent / cooldown /
session-cooldown), eligibility (`original`/`actual`), `is_inbox_message`,
`extra[]` (operator key/values — values always strings), A/B distribution,
audiences/filters, `progression_score { current, previous, total }`,
`feature_settings` / `feature_configurations` / `bundle_resources` (below),
`security_data.checksum`, `sequence_data`.

## How template slots are filled (`data`)

`data = { template: "custom", template_key, images{}, buttons{}, texts{}, customs{}, feature? }`

- Buckets are **maps keyed by the template element key**. A hidden/unfilled
  slot is simply **absent** — there is no visibility flag. `index`, `name`,
  `textLimit`, `canBeHidden` are not re-sent; the client re-derives them from
  the template.
- **Images**: `{ content, content_type, custom_fields{} }` with `content_type ∈
  web_url | addressable | local_path | text` — the operator picks the delivery
  channel, not just a URL. `text` on a button background means "render this
  label instead of art". `content_type` is NOT validated against `content`.
- **Buttons** — the biggest transform: the template's `clickActionType[]`
  *menu* collapses to one `click_config.action`. Per-action payload:
  `link` (deep_link/web_link), `price_resources[]` (soft_billing),
  `packages { ios/android_package_id + *_discount_package_id }` (billing — the
  discount pair drives the client-rendered strike-through price),
  `resources[]` (granted items). The SDK also parses the tenth action
  **`custom` (+ `cta_name`)**, and the dashboard template contract confirms it:
  a template button offers `custom` in its menu and carries `customCtaNames` —
  the standard way to express info/rules/preview controls the client implements.
- **Texts**: `{ content, custom_fields{} }`; `text_color`/`badge_color` arrive
  exactly as the template's custom fields promise.
- **Customs**: `{ value, custom_fields{} }` — loosely typed on the wire
  (`"42"` vs `42` both observed); the client must coerce.
- **Resource objects** (`resource_key`, `amount`, `expiration`, `body`) appear
  in six positions with inconsistent key sets; `body` is a JSON-encoded
  *string* (empty = literal `"null"` in most positions, real `null` in
  `bundle_resources`).

## Features layer at instance level

`data.feature.type` is **plural** (`"missions"` / `"milestones"`); a standard
template emits no `feature` key at all.

**Milestones** (single ladder): `steps[] { score, status (closed→reached→
collected), button, custom_fields }` + `progress`/`previous_progress`
(cumulative, never reset by reaching a step) + `active_progress_button` (morphs
into the final step's CTA once the last step is reached). Collect = zero-based
indices; final-claim on an eligibility-capped in-app **resets the same instance**
(the repeat mechanism).

**Missions**: `mission_state { current_set_number, active_set_progress,
previous_set_progress, progress_bar_state, layout }`. Per mission:
`row_number, placement_number (lane), sub_mission_number (step in lane),
mission_text ("[]" placeholder = goal, client substitutes), current_score,
goal_score, progress_bar_score (contribution to the shared bar), status,
progression_cta, completion_cta, google/apple_package_id (per-mission purchase
gating), processed_resources[], custom_fields`. Sub-missions chain: the server
activates the next as soon as the previous is *reached* (independent of
collection); locked rows are **absent**, not padlocked. Common missions
(`placement_number: null`) appear after all lanes complete.
`progress_bar_state { total_score, milestones[] }` is a **sibling of the sets —
one shared cross-set bar by construction; there is no per-set bar** (the set
object has no score field). The wire carries `layout: "parallel"` (and a
`chain_progress: null` sibling), but the SDK model does not parse either —
display arrangement is effectively resolved server-side into this fixed
structure.

Progress sources (all server-computed; the payload carries only results):
event counts, event **parameter values** (`bind_with_event_parameter`), with
player-state fields selecting the *band*, not driving the score.

## Placeholder bands — per-player content variance

One in-app + one template returns **different values for every element** by
player-state band (texts, image URLs, package ids, reward amounts, reward
bodies). A mockup showing "the same popup tuned per segment" is ONE template +
ONE in-app with bands — not several templates, not `unsupported`.

**How the operator authors it** (dashboard mechanics): typing
`${placeholder_key}` instead of a literal value into ANY input while
configuring the in-app makes a values table appear on a later step. Each row
of that table supplies the placeholder's value for one segment, and rows are
segmented by Player State field filters — e.g. with a `Level` filter:
`Level:From 0, Level:To 10 → Image X`; `Level:From 11, Level:To 100 → Image Y`.
The client then receives the already-resolved value for its band (plus the
matching filter echo under `configuration_filters`).

## Embedded feature settings

An in-app can inline resolved feature-settings rows (`feature_settings[]` with
`$type: "<SchemaName>_v<version>"`) or manual `feature_configurations[]`
(mutually exclusive), plus `bundle_resources{}` pre-resolving `bundle_key`
columns — no separate `gate.kinoa.io/featureset` round-trip for offer-bound
configs, and no checksum protocol on this path.

## Consumer beware (observed sharp edges)

Mixed timestamp units (ms and s in one record, only `*_ms`/`*_seconds` names
advertise it); duplicated envelope keys (`configuration_filters`/
`configured_filters`, `ab_test(s)_distribution`); template camelCase vs
instance snake_case; `featureType` singular vs `feature.type` plural;
milestone steps serialized differently standalone vs inside missions; store
package naming observed **inverted** in fixtures (`IosPackageID` holding the
discount id); analytics events carry only `in_app_id`/`uuid`/`name` — no
per-button attribution.
