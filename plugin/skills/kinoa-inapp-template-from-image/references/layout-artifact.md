# The layout artifact — `<template_key>.layout.json`

The geometry deliverable of `kinoa-inapp-template-from-image`. A template
payload carries no coordinates (the dashboard API has none), but downstream
tooling — first consumer: the In-app Prefab Generation Skill, which builds the
pop-up's UI on a Unity scene — needs to know where every element literally sits
on the design. That knowledge ships as this separate, versioned artifact,
written next to `<template_key>.template.json` after the developer confirms the
structure. This document is the contract; it is written to be readable on its
own by the consumer's author.

## Shape

```json
{
  "schema_version": "1.0",
  "template_key": "journey_offer",
  "source_image": { "width": 434, "height": 964, "sha256": "…", "path": "…" },
  "coordinates": { "space": "normalized", "origin": "top-left" },
  "elements": [
    {
      "key": "header",
      "bucket": "texts",
      "index": 0,
      "role": "header",
      "bbox": { "x": 0.08, "y": 0.10, "w": 0.68, "h": 0.07 },
      "observed_text": "Journey Offer",
      "confidence": 0.95
    },
    {
      "key": "fine_print",
      "bucket": "texts",
      "index": 7,
      "role": "",
      "bbox": null,
      "unplaced": true
    }
  ],
  "client_rendered": [
    { "role": "timer", "bbox": { "x": 0.28, "y": 0.185, "w": 0.34, "h": 0.04 } }
  ],
  "feature": { "type": "mission", "area_bbox": { "x": 0.06, "y": 0.30, "w": 0.88, "h": 0.55 } }
}
```

## Semantics

- **`elements[].key` joins 1:1 with the template's element keys** — the local
  `<template_key>.template.json`, or the dashboard record when the layout was
  derived for an existing template. Layout and template are two views of the
  same confirmed structure; the validator enforces the join both ways.
- **`index`** is the global reading order across all four buckets, identical to
  the template's own `index`.
- **`bbox`** is normalized to the source image: `x`/`y`/`w`/`h` in `[0, 1]`,
  origin top-left. Multiply by `source_image.width`/`height` for pixels — the
  original file is not required for the conversion.
- **`bbox: null` + `"unplaced": true`** — the element's position is undecided
  (it exists in the template but was never located on the image or placed by
  the developer). Flagged, never silently dropped: the consumer decides where
  it goes.
- **`hand_placed`** (optional, true) — the box was drawn by the developer on
  the confirmation page, not detected by the vision pass. **`adjusted`**
  (optional, true) — the vision box was moved/resized by the developer.
- **`client_rendered`** zones (timer, resource area, price-before-sale, grand
  prize area) are drawn by the game client once the campaign is configured.
  They are listed so the consumer reserves screen space for them; they are NOT
  template elements and must not become slots or UI stubs the operator is asked
  to fill.
- **`feature.area_bbox`** (optional; mission/milestone) marks the region the
  progression UI (task list / progress bar) occupies on the mockup. Absent when
  the vision pass could not bound it.
- **`source_image.sha256`** fingerprints the exact image the boxes were drawn
  against — compare it before rendering a layout over a different export of
  the same design.

## Precision promise

Boxes are vision-derived and developer-adjusted on the confirmation page. They
express **layout intent** — anchoring, proportions, relative placement — not
pixel-perfect measurements. Overlaps are legitimate (a badge over the
background art). There is no explicit per-element z-order: images sit behind,
buttons/texts/badges in front, ties resolved by reading order (`index`).

## How it is produced

Path A — mockup → new template (the normal flow): the confirmation page's
hand-back envelope carries a `geometry` block; the builder turns it into the
artifact and cross-validates against the confirmed payload:

```bash
python inapp_template_build.py layout --envelope confirmed.json \
    --analysis analysis.json --out <template_key>.layout.json
```

Path B — an existing dashboard template with a valid tip image: the record is
fetched, its tip image analyzed, and `remap` gates the pair (every detected
element must land on a declared slot — a stale or unrelated image fails with a
mismatch report, and no layout is derived from it). The gate is structural, not
semantic: an image of a *different* design with the same element skeleton
passes it — catching that is what the confirmation-page overlay (and the
developer's eyes) are for. Its output is
page-compatible; after the developer confirms, the same `layout` call above
produces the artifact with the record's own keys.

```bash
python inapp_template_build.py remap --record record.json \
    --analysis tip_analysis.json --out build_for_page.json
```

`layout --build build_result.json` also works without a confirmation round —
the geometry is then the raw vision pass, and the output carries an explicit
warning saying so. Use it for previews and tooling, not for the hand-off
artifact.

## Validation

`inapp_template_build.py validate --payload <template>.json --layout <template>.layout.json`
checks the artifact: coordinate convention, bbox ranges, unique elements, the
1:1 key join, index equality, and `template_key` match.
