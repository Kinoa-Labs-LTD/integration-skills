# Prefab plan — the JSON contract between the planner and the Editor builder

Produced by `inapp_prefab_plan.py plan`, copied into the project as
`<out_dir>/<Pascal>/<key>.inapp-plan.json`, consumed by
`Editor/KinoaInAppPrefabBuilder.cs` (JsonUtility ⇒ flat, typed, no recursion).

## Top level

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | `"1.0"` | bump when a node field changes meaning |
| `template` | object | `id`, `key`, `name`, `feature_type` (`standard`/`mission`/`milestone`), plus the slot lists the view generator reads (`images`, `texts`, `buttons`, `customs`) |
| `ui` | object | `text_system` (`legacy`/`tmp`), `font_guid`, `tmp_font_guid`, `frame_size` `[w,h]`, `close_sprite_guid`, `dimmer_alpha` |
| `view` | object | `class_name`, `ns` (always `Kinoa.InApps`), `facade`, `facade_namespace` |
| `paths` | object | `out_dir`, `prefab_path`, `view_path`, `plan_path` — all project-relative |
| `nodes` | array | flat GameObject list, parent-before-child order |
| `customs` | array | `{key, kind, default, target_node, target_field}` — **every** template custom is listed. Only a boolean that matches a node (a zone root, or an image/text/button slot) gets `target_node` / `target_field`; non-booleans and unmatched booleans carry `null` targets (read them with `GetCustom<T>`), and an unmatched boolean is also added to `report.needs_developer` |
| `report` | object | `layout_source`, `panel_bbox`, `unplaced`, `estimated_positions`, `layout_adjustments`, `overlays`, `warnings`, `unmapped_layout`, `client_zones`, `needs_developer` |

## Layout sources

`plan` takes at most one layout source; `report.layout_source.kind` records which one positioned the plan.

| Flag | `kind` | Input |
|---|---|---|
| `--layout-artifact` (preferred) | `layout_artifact` | `<template_key>.layout.json` from kinoa-inapp-template-from-image (contract: `../../kinoa-inapp-template-from-image/references/layout-artifact.md`). Schema 1.x, normalized top-left coordinates; customs are skipped; `bbox: null` / `unplaced` elements go to `Unplaced`; `client_rendered[].role` positions the zones; `feature.area_bbox` positions `MissionList`, and `MilestoneBar` when no `bar_image` element was placed, only when the artifact's feature type matches the template's. The join is 1:1 on `(bucket, key)` with no key-only fallback: a `template_key` different from the template's key is refused (`layout_template_mismatch`, exit 2); a missing `template_key`, element or `area_bbox` boxes outside `[0, 1]` or of zero size, and other coordinate conventions are refused as `unreadable_input`; an out-of-range `client_rendered` box is dropped with a warning; template slots with no entry, duplicate entries, and index or feature-type disagreements become `warnings`; entries the template lacks go to `unmapped_layout`. `layout_source` also carries `template_key`, `sha256`, and the `hand_placed` / `adjusted` counts. |
| `--build` | `build_result` | The from-image builder's raw `build_result.json` (`report.elements`, `report.client_rendered`, `report.source_image`), optionally corrected by `--confirmed`. |
| `--layout` (legacy) | `layout_file` | A layout written against `layout-schema`. Kept for compatibility; the skill no longer produces it. |
| none | `null` | Every slot goes to `Unplaced`. |

## Node

| Field | Meaning |
|---|---|
| `name` | unique GameObject name; `parent` names another node or `null` for the prefab root |
| `binding` | `dimmer` · `frame` · `panel` · `image` · `text` · `button` · `button_label` · `zone` · `strike` · `fill` · `markers` · `item_template` · `unplaced` |
| `components` | subset of `Image`, `Button`, `Text`, `HorizontalLayoutGroup`, `VerticalLayoutGroup` (`Text` resolves to legacy or TMP per `ui.text_system`) |
| `field` / `field_type` | the view's `[SerializeField]` to assign; types `GameObject`, `RectTransform`, `Image`, `Button`, `Text`, `KinoaInAppItemView` |
| `anchor_min` / `anchor_max` | uGUI anchors, offsets zero (stretch within the anchors) |
| `size` | `[w,h]` centred fixed size — used instead of anchors (Frame, item templates) |
| `placed` | for slot, zone and feature nodes: `true` only when the position came from a layout source; every such node listed in `report.estimated_positions` has `placed: false` (see below). Chrome nodes (`Dimmer`, `Frame`, `Panel`) and child helpers (button labels, `TimerText`, fills, …) default to `true`; the `Unplaced` container is an estimated position and is `false` |
| `can_be_hidden` | the template slot's `canBeHidden` flag on image / text / button slot nodes (the generated view hides an empty slot only when it is true); `true` on the milestone main button; `false` on every other node |
| `inactive` | node starts disabled (zones, item templates) |
| `key` / `bucket` / `role` | the template slot this node renders |
| `click_actions` / `custom_cta_names` | copied from the template button |
| `sprite_guid` | optional sprite to assign to the node's Image |

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
        ├── MilestoneBar … / MissionList …                                       (feature)
        └── Unplaced          VerticalLayoutGroup — slots with no bbox; starts at the bottom 30 %, may move to free space
```

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
  - **Containers** (`MissionList`, `MilestoneBar`, `ResourceArea`,
    `GrandPrizeArea`) are never trimmed. A box with at least 80 % of its area
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
  0.02 of real height, markers aside. The `Unplaced` container is first sized
  to its rows (88 px each, plus a little padding), growing or shrinking, and
  is never shrunk below that later. With no room left, the node stays and a
  warning names every node it overlaps.
- `MilestoneBar` counts with its markers, one bar height above and below.

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
