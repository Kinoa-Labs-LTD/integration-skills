# Prefab plan — the JSON contract between the planner and the Editor builder

Produced by `inapp_prefab_plan.py plan`, copied into the project as
`<out_dir>/<Pascal>/<key>.inapp-plan.json`, consumed by
`Editor/KinoaInAppPrefabBuilder.cs` (JsonUtility ⇒ flat, typed, no recursion).

## Top level

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | `"1.0"` | bump when a node field changes meaning |
| `template` | object | `id`, `key`, `name`, `feature_type` (`standard`/`mission`/`milestone`), plus the slot lists the view generator reads (`images`, `texts`, `buttons`, `customs`) |
| `ui` | object | `text_system` (`legacy`/`tmp`), `font_guid`, `tmp_font_guid`, `frame_size` `[w,h]`, `close_sprite_guid`, `dimmer_alpha`, `canvas` — the root `Canvas` / `CanvasScaler` settings: `render_mode` (`overlay`/`camera`/`world`), `override_sorting`, `sorting_order`, `scale_mode` (`scale_with_screen_size`/`constant_pixel_size`/`constant_physical_size`), `reference_resolution` `[w,h]`, `match`, `source` (the reference pop-up it was copied from, or `default`) |
| `view` | object | `class_name`, `ns` (always `Kinoa.InApps`), `facade`, `facade_namespace` |
| `paths` | object | `out_dir`, `prefab_path`, `view_path`, `plan_path` — all project-relative |
| `nodes` | array | flat GameObject list, parent-before-child order |
| `customs` | array | `{key, kind, default, target_node, target_field}` — **every** template custom is listed. Only a boolean that matches a node (a zone root, or an image/text/button slot) gets `target_node` / `target_field`; non-booleans and unmatched booleans carry `null` targets (read them with `GetCustom<T>`), and an unmatched boolean is also added to `report.needs_developer` |
| `milestone` | object, milestone templates only | the step-CTA decision: `cta_mode` (`per_step` / `single`), `cta_mode_source` (`override` / `template_cta_count` / `default`), `cta_slots` (template button keys counted as step CTAs), `single_cta` (`{key, button_field, label_field}`; `key` is `null` when the CTA goes onto the generated `MilestoneMainButton`; `null` in `per_step` mode) and `collect_all` (`{key, button_field, label_field, can_be_hidden}` or `null`). An additive block: `schema_version` stays `1.0`. Absent on every other template and on plans written before the scroll ladder |
| `report` | object | `layout_source`, `panel_bbox`, `unplaced`, `estimated_positions`, `layout_adjustments`, `overlays`, `warnings`, `unmapped_layout`, `client_zones`, `needs_developer`, `milestone` (milestone templates: `{cta_mode, cta_mode_source, collect_all}`); mission templates add `mission_actions` and `mission_geometry` (below) |

## Layout sources

`plan` takes at most one layout source; `report.layout_source.kind` records which one positioned the plan.

| Flag | `kind` | Input |
|---|---|---|
| `--layout-artifact` (preferred) | `layout_artifact` | `<template_key>.layout.json` from kinoa-inapp-template-from-image (contract: `../../kinoa-inapp-template-from-image/references/layout-artifact.md`). Schema 1.x, normalized top-left coordinates; customs are skipped; `bbox: null` / `unplaced` elements go to `Unplaced`; `client_rendered[].role` positions the zones; `feature.area_bbox` positions `MissionList` (when `feature.parts.task_list` is absent), and `MilestoneScroll` (the `bar_image` box when no area was drawn), only when the artifact's feature type matches the template's. Artifact `1.1` adds the optional mission-only `feature.parts` (`tabs`, `tab`, `task_list`, `row`, `progress_bar` — the last places the progress-bar ladder's `MissionBarScroll`, so it should bound the bar with its markers and rewards), `feature.row_parts` (inner pieces of the one card in `parts.row`: `placement_badge`, `title`, `sub_mission`, `status`, `progress_track`, `progress_text`, `rewards`, `action_button`, `dismiss_button`) and `feature.style` (`#RRGGBB[AA]` colours: `card`, `card_text`, `accent`, `progress_track`, `progress_fill`, `action`, `dismiss`, `tab_text`, `tab_selected`, `bar_track`, `bar_fill`) — advisory geometry and colours for the missions UI, never template elements; an invalid box, colour or key is dropped with a warning, `row_parts` without a valid `parts.row` are dropped whole, and a `1.0` artifact stays valid (the neutral defaults apply). The join is 1:1 on `(bucket, key)` with no key-only fallback: a `template_key` different from the template's key is refused (`layout_template_mismatch`, exit 2); a missing `template_key`, element or `area_bbox` boxes outside `[0, 1]` or of zero size, and other coordinate conventions are refused as `unreadable_input`; an out-of-range `client_rendered` box is dropped with a warning; template slots with no entry, duplicate entries, and index or feature-type disagreements become `warnings`; entries the template lacks go to `unmapped_layout`. `layout_source` also carries `template_key`, `sha256`, and the `hand_placed` / `adjusted` counts. |
| `--build` | `build_result` | The from-image builder's raw `build_result.json` (`report.elements`, `report.client_rendered`, `report.source_image`), optionally corrected by `--confirmed`. |
| `--layout` (legacy) | `layout_file` | A layout written against `layout-schema`. Kept for compatibility; the skill no longer produces it. |
| none | `null` | Every slot goes to `Unplaced`. |

## Node

| Field | Meaning |
|---|---|
| `name` | unique GameObject name; `parent` names another node or `null` for the prefab root |
| `binding` | `dimmer` · `frame` · `panel` · `image` · `text` · `button` · `button_label` · `zone` · `strike` · `fill` · `item_template` · `scroll` · `viewport` · `scroll_content` · `milestone_step` · `tab_template` · `tab_part` · `mission_row_template` · `row_part` · `unplaced` |
| `components` | subset of `Image`, `Button`, `Text`, `HorizontalLayoutGroup`, `VerticalLayoutGroup`, `ScrollRect`, `RectMask2D`, `ContentSizeFitter` (`Text` resolves to legacy or TMP per `ui.text_system`) |
| `field` / `field_type` | the view's `[SerializeField]` to assign; types `GameObject`, `RectTransform`, `Image`, `Button`, `Text`, `ScrollRect`, `KinoaInAppItemView`, `KinoaInAppMilestoneStepView`, `KinoaInAppTabView`, `KinoaInAppMissionRowView` |
| `anchor_min` / `anchor_max` | uGUI anchors, offsets zero (stretch within the anchors) |
| `size` | `[w,h]` centred fixed size — used instead of anchors (Frame, item templates) |
| `placed` | for slot, zone and feature nodes: `true` only when the position came from a layout source; every such node listed in `report.estimated_positions` has `placed: false` (see below). Chrome nodes (`Dimmer`, `Frame`, `Panel`) and child helpers (button labels, `TimerText`, fills, …) default to `true`; the `Unplaced` container is an estimated position and is `false` |
| `feature_action` | button nodes of a mission template only: `reach_all` · `collect_all` · `collect_all_milestones` when the button is wired to that mission feature action (below), else `null`. The generated view wires such a button to the mission call instead of `KinoaUiService`, and no client zone is built for it |
| `color` | optional `#RRGGBB[AA]` the builder sets on the node's `Image` (card, tab, progress, ladder backdrop … from the artifact's `feature.style`), or on its `Text`; on a `milestone_step` node it tints the step's `Progress` fill instead. `null` keeps the builder default |
| `scroll_axis` | `"vertical"` on the `scroll` and `scroll_content` nodes of a vertical scroll chain (the mission card list), else `null` (horizontal — the ladders, and every plan written before the field existed) |
| `can_be_hidden` | the template slot's `canBeHidden` flag on image / text / button slot nodes (the generated view hides an empty slot only when it is true); `true` on the milestone main button; `false` on every other node |
| `inactive` | node starts disabled (zones, item templates) |
| `key` / `bucket` / `role` | the template slot this node renders. On any descendant of a tab or mission-row template, `role` is the `[SerializeField]` name on that template's shared view (`KinoaInAppTabView` / `KinoaInAppMissionRowView`), which the builder assigns (such nodes may carry no `field`). Only `tab_part` / `row_part` nodes are checked: one whose role cannot be assigned (no such field on the view, or no template above it) is listed in the build report's `errors` |
| `click_actions` / `custom_cta_names` | copied from the template button |
| `sprite_guid` | optional sprite to assign to the node's Image |
| `step_button` | on a `milestone_step` template node only: `MilestoneStep` is `true` in `per_step` mode, where the builder gives the step a `CollectButton` + `CollectLabel`, and `false` in `single` mode, where the step has none and the ready step's button goes onto the single CTA; the mission ladder's `MissionBarStep` is always `true`. `false` everywhere else |

### `placed` and `Unplaced`

For slot, zone and feature nodes, `placed` is true only when the node was
positioned from a layout source (the from-image layout artifact, a build result, or a legacy layout
entry); chrome nodes and child helpers default to `true`, and the `Unplaced`
container is `false`. Every node named in `report.estimated_positions` has
`placed: false`. Two kinds of estimated node exist: slots without a bbox,
which are also moved under the `Unplaced` container, and zones / feature
nodes, which stay under `Panel`. Both start at default anchors and may then
be moved to free space by the de-overlap pass.

## Hierarchy

```
KinoaInApp_<Pascal>           (root, stretch; the view component lives here)
├── Dimmer                    Image, black α 0.6, stretch
└── Frame                     fixed ui.frame_size, centred — the mockup's canvas
    └── Panel                 the union of every positioned box (report.panel_bbox)
        ├── <image slots>     first: art renders behind controls; BackgroundImage at its own bbox (stretch when it has none); never a raycast target
        │                     (images whose key or layout role contains `badge` come after controls, in front of what they annotate)
        ├── <slot nodes>      anchored from bbox, relative to Panel
        ├── <ButtonName>Label stretch child of its button
        ├── TimerZone / PriceBeforeSaleZone / ResourceArea / GrandPrizeArea   (inactive)
        ├── MilestoneScroll …                                                    (milestone feature)
        │   └── MilestoneViewport  →  MilestoneContent  →  MilestoneStep           (milestone: horizontal scroll; the step is an inactive template, cloned per step)
        ├── MilestoneMainButton                                                  (milestone, only when no template button is the single CTA)
        ├── MissionTabs · MissionList · MissionBarScroll …                       (mission feature, below)
        └── Unplaced          VerticalLayoutGroup — slots with no bbox; starts at the bottom 30 %, may move to free space
```

### The scroll chain

Every scrolling list in a plan is the same three-node chain, wired by the
builder's `WireScrollRects` (the `ScrollRect`'s `viewport` and `content`):

| Node | `binding` | `components` |
|---|---|---|
| scroll (child of `Panel`) | `scroll` | `ScrollRect` |
| viewport (stretched) | `viewport` | `Image`, `RectMask2D` |
| content | `scroll_content` | `HorizontalLayoutGroup` or `VerticalLayoutGroup`, `ContentSizeFitter` |

It is horizontal unless the scroll and content nodes carry `scroll_axis:
"vertical"`. The milestone ladder and the mission progress-bar ladder are
horizontal (`scroll_axis` `null`); the mission card list is vertical. Plans
written before `scroll_axis` existed never carry it, so they build exactly as
before.

### Milestone ladder

A milestone template renders its steps as a horizontal scroll:
`MilestoneScroll` (`ScrollRect`, positioned from `feature.area_bbox` or the
`bar_image` box) → `MilestoneViewport` (`Image` + `RectMask2D`, stretched) →
`MilestoneContent` (`HorizontalLayoutGroup` + `ContentSizeFitter`) →
`MilestoneStep` (inactive; a `KinoaInAppMilestoneStepView` with score, reward
icon and amount, a fill, locked / collected marks and, in `per_step` mode, a
collect button). The builder wires the `ScrollRect` to its viewport and
content. `MilestoneScroll` is a container for de-overlap (never trimmed).
`MilestoneMainButton` (the feature's progress button) is added only when no
template button is the single CTA.

A milestone plan must be produced by this version. `generate` refuses one that
has no `milestone` block or no `MilestoneScroll` node (written before the scroll
ladder) with `{"ok": false, "error": "milestone_plan_outdated", ...}` (exit 2,
nothing written) — re-run `plan` for the template.

### `--milestone-cta` and how the mode is chosen

| Flag value | `cta_mode` | `cta_mode_source` |
|---|---|---|
| `per_step` / `single` | as given | `override` |
| `auto` (default), exactly one CTA slot | `single` | `template_cta_count` |
| `auto`, zero or several CTA slots | `per_step` | `default` |

A **CTA slot** is a template button, other than the collect-all one, that
offers an action other than `close` and `custom` (a button with no actions
counts unless its key reads close / dismiss) and whose layout role is not
`info_button`; with a layout source in play, only buttons placed on the tip
image count. An info / rules button is never the CTA; a secondary button with
`close` + `deep_link` still counts. The **collect-all** button is the first
button (lowest `index`) whose key or name matches
`(?:^|[\s_-])(collect|claim|get)[\s_-]*all(?:$|[\s_-])`, case-insensitive
(whole segments: `claim_all`, `Get All` match, `budget_all` does not); further
matches add a warning. `single` with no CTA slot
puts the CTA on `MilestoneMainButton`; `--milestone-cta single` with two or
more slots does the same and warns.

### Mission subtree

A mission template gets this feature subtree under `Panel` instead of the
milestone ladder. Every part node is positioned from the artifact's
`feature.parts` / `row_parts`, and coloured from `feature.style`. Where the
artifact has no box for a part, the node takes a neutral default (no
proportions or colours are taken from any sample).

```
MissionTabs                   zone, HorizontalLayoutGroup (field missionTabsRoot)
└── MissionTab                tab_template, inactive — one spawned per mission set
    ├── MissionTabLabel       tab_part, role label
    └── MissionTabSelected    tab_part, role selectedMarker
MissionList                   scroll, scroll_axis vertical (ScrollRect, field missionScroll)
└── MissionViewport           viewport
    └── MissionRows           scroll_content, scroll_axis vertical — VerticalLayoutGroup + ContentSizeFitter (field missionRowsRoot)
        └── MissionRow        mission_row_template, inactive — the one card template
            ├── MissionRowPlacement (+ MissionRowPlacementText)
            ├── MissionRowTitle · MissionRowSubMission · MissionRowStatus
            ├── MissionRowDismiss (+ MissionRowDismissLabel)
            ├── MissionRowProgress (+ MissionRowProgressFill) · MissionRowProgressText
            ├── MissionRowRewards (+ inactive MissionRowReward item template)
            └── MissionRowAction (+ MissionRowActionLabel)
MissionBarScroll              scroll, horizontal (ScrollRect, field missionBarScroll) — only when progressBar.display is not dont_show_at_all
└── MissionBarViewport        viewport (color: style.bar_track)
    └── MissionBarContent     scroll_content (field missionBarContent)
        └── MissionBarStep    milestone_step, step_button true, inactive (field missionBarStepTemplate; color: style.bar_fill)
```

The progress bar (`ProgressBarState`) is the **milestone ladder**: the same
chain and step template as a milestone template in `per_step` mode, positioned
by `feature.parts.progress_bar` (the `mission_bar` default band otherwise) and
sized by the same step formula. A ladder band shorter than one step (136 px in
the frame) adds a warning naming `MissionBarScroll`. The release's
`MissionBar` / `MissionBarFill` names stay reserved; a mission plan that still
has them, or that predates the tabs / cards (`MissionList` not a `scroll`, no
`MissionTabs`), is refused by `generate` with `mission_plan_outdated` (exit 2,
nothing written) — re-run `plan`.

The card children carry no `field`; each wired one has a `role` naming the
`[SerializeField]` on `KinoaInAppMissionRowView` (`placementText`, `titleText`,
`subMissionText`, `statusText`, `dismissButton`, `dismissLabel`, `progressFill`,
`progressText`, `rewardsRoot`, `rewardTemplate`, `actionButton`, `actionLabel`)
that the builder assigns once every node is built (most are `row_part`
nodes; `MissionRowProgressFill` is a `fill` and `MissionRowReward` an
`item_template`, wired the same way); the tab parts do the same
for `KinoaInAppTabView` (`label`, `selectedMarker`). Anchors of the card's
children are relative to the card (`parts.row`), not the panel.

**`report.mission_actions`** — `{reach_all, collect_all, collect_all_milestones}`,
each the key of the template button wired to that feature action, or `null`.
A button is wired by compacting its key, then its name (lower-case, `a-z0-9`
only): `collectall` / `claimall` with `milestone`, `bar` or `progress` →
`collect_all_milestones`; `collectall` / `claimall` → `collect_all`; `reachall` →
`reach_all`. Only mission templates have them. The lowest template `index` wins
a duplicate; the others stay ordinary buttons with a warning.
`collect_all_milestones` on a template without a bar stays an ordinary button
with a warning. A wired button carries `feature_action` and does not count
toward the client zones.

**`report.mission_geometry`** — `source` (`layout_artifact` when the artifact
carried any of `parts` / `row_parts` / `style`, else `defaults`), the lists of
`parts`, `row_parts` and `style` keys that were used, and `defaulted`: the names
of the nodes whose geometry came from the neutral default because the artifact
had no box for them. Tell the developer when this list is not empty.

## Panel extent and de-overlap

The panel is the union of every box the plan positions: the background art,
every slot, every client-rendered zone and `feature.area_bbox`. Mockups often
put the CTA, timer or fine print below the art; with the art alone as the
panel those boxes would clamp onto its bottom edge and pile up.

After placement, `resolve_overlaps` runs over the top-level flow nodes: texts,
buttons, zones and the `Unplaced` container. Images and anything whose key,
role or name contains `badge` are exempt. Boxes that only touch, within 0.002
anchor units, do not count as overlapping.

- **Placed vs placed:** the overlap is measured as a share of the smaller
  box.
  - **Overlay (≥ 80 %):** kept as drawn and listed in `report.overlays`, for
    example a price inside the CTA.
  - **Containers** (`MissionList`, `MissionTabs`, `MissionBarScroll`,
    `MilestoneScroll`, `ResourceArea`, `GrandPrizeArea`) are never trimmed. A box with at least 80 % of its area
    inside a container is an overlay, for example the resource area on a
    mission task list. When both boxes are containers, the smaller one is
    measured. Any other overlap with a container, such as a resource area
    partly over the CTA, is left as drawn with a warning.
  - **Slop (≤ 35 %):** split along an axis where neither box contains the
    other, the one with the smaller overlap. The cut is at the midpoint of the
    overlap band, with a 0.004 gap. Each box keeps at least 40 % of its
    original extent, else the pair is left and a warning says so.
  - **In between:** left as drawn, with one warning per pair.
- **Estimated (`placed: false`):** the node moves vertically, keeping its x
  span, to the nearest slot that collides with nothing already settled. It
  tries the full height, then half, then a quarter. It never shrinks below
  0.02 of real height. The `Unplaced` container is first sized
  to its rows (88 px each, plus a little padding), growing or shrinking, and
  is never shrunk below that later. With no room left, the node stays and a
  warning names every node it overlaps.

Every change is appended to `report.layout_adjustments` as
`{node, reason: split_overlap | moved_to_free_space | sized_to_rows, with, from, to}`
(anchors), and every move or trim is summarised in `report.warnings`. Anchors
written back are clamped to `[0, 1]`.

## Anchor math

bbox and panel are normalised to the mockup (origin top-left). Relative box
`r = ((x−Px)/Pw, (y−Py)/Ph, w/Pw, h/Ph)`; anchors flip y:
`anchor_min = (r.x, 1−(r.y+r.h))`, `anchor_max = (r.x+r.w, 1−r.y)`, clamped to
`[0,1]`, widened to ≥ 0.01 per axis.

## Naming

`field_name(bucket, key)` = lowerCamel(key) + bucket suffix (`Image`/`Text`/`Button`),
**unless the key, split on non-alphanumerics, has more than one token and its
last token already equals the suffix**. So `background_image → backgroundImage`
(two tokens, last is `image`), but `hero → heroImage`, `context → contextText`
and `text → textText` (single-token keys always get the suffix appended, even
when the key happens to equal or end in the suffix text). `header → headerText`,
`cta → ctaButton`. Node name = the field name in PascalCase.

### Uniqueness

Slot node names and fields are de-duplicated against `RESERVED_NODE_NAMES` and
`RESERVED_FIELDS` — every fixed chrome, zone and feature name (`Dimmer`,
`Frame`, `Panel`, `Unplaced`, `TimerZone`, `TimerText`, …, and the view's
fixed fields such as `dimmer`, `panel`, `timerRoot`, `timerText`) — and against
earlier slots, by appending `2`, `3`, … A warning is recorded in
`report.warnings` for each rename. A button label node is always the **final**
button node name / field plus `Label` (so a renamed button keeps its label in
step).
