#!/usr/bin/env python3
"""Generate the INTERACTIVE in-app-template confirmation page for
kinoa-inapp-template-from-image.

This is the human-in-the-loop step of the workflow. A vision pass reads the
mockup, `inapp_template_build.py build` turns that reading into a template
payload, and this file renders the result *next to the picture it came from*:
the mockup on the left with one overlay box per proposed element, the editable
element list on the right. The developer fixes what the machine got wrong —
renames keys, moves an element into another bucket, adds what was missed,
removes what isn't real — and only then is anything registered on Kinoa.

The page makes NO network calls and reads NO credentials; the image is inlined
as a data: URI so the file is self-contained and can be mailed around. Because
a browser cannot write to the developer's filesystem, the confirmed payload is
handed back three ways, exactly like the resource-confirmation page does:
a **Download JSON** button, a **Copy** button, and a visible <pre> block the
developer can select by hand.

The hand-back is stamped: `{"confirmed_at", "page_generated_at", "corrections",
"payload"}`. `corrections` is page-side feedback for the analysis corpus — what
the human fixed about what the model saw: `missed` (rows added and placed here),
`adjusted` (vision boxes moved/resized, final + `original_bbox`) and `excluded`
(vision rows un-ticked — false positives), plus `source_image`: a fingerprint
(`sha256`, `width`, `height`, `filename`; null with no image) that makes a
correction joinable to the exact mockup without ever carrying the picture.
None of it is part of the template, which has no coordinates.
Inside `payload` is ONLY the template create body — name, key, description,
gameId (when the build stamped one), images/buttons/texts/customs, featureType,
features (`{}` for a standard template) and tagsIds. Elements the developer
unticks stay on the page but never reach `payload`; nothing is ever deleted
except rows added on the page itself. The report, the validation block, the bboxes and the build trace stay
in the page; they are review aids, not part of the API body.

Usage:
    python generate_confirm_page.py --build build_result.json \\
        [--image mockup.png] [--out page.html] [--no-open]

`--build` takes exactly what `inapp_template_build.py build` prints:

{
  "ok": true,
  "payload":    {"name","key","description","gameId"?,"images","buttons","texts",
                 "customs","featureType","features","tagsIds"},
  "report":     {"counts","element_count","feature_type","warnings","unmapped",
                 "client_rendered":[{"role","reason","bbox"}],
                 "needs_confirmation":[{"key","bucket","role","question"}],
                 "unsupported":[{"what","why","bbox"}],
                 "elements":[{"index","bucket","key","role","bbox","observed_text",
                              "confidence"}],
                 "source_image":{"path","width","height"}},
  "validation": {"ok","errors","warnings"}
}

`report.elements` is the trace that joins a payload element (bucket + key) to
its normalised bbox on the mockup — that join is what lets the page draw the
overlay. When `--image` is omitted the page falls back to
`report.source_image.path` (resolved relative to the build file too); with no
readable image it renders fine, just without the overlay panel.

Note on the implementation: the page body below is a plain string with
`__KINOA_*__` tokens rather than an f-string. The sibling pages use f-strings,
but their JS is smaller — doubling every brace across this much script is a bug
farm, and the token swap keeps the JS copy-pasteable into a browser console.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import sys
import webbrowser
from datetime import datetime, timezone
from typing import Any

# --------------------------------------------------------------------------
# Template vocabulary. Deliberately duplicated from inapp_template_build.py:
# helpers in this repo never import each other, so the constants are mirrored
# by hand. Keep the two files in step when the model changes.
# --------------------------------------------------------------------------

CLICK_ACTIONS = [
    "close",
    "collect_resource",
    "billing",
    "custom",
    "web_link",
    "deep_link",
    "show_ad",
    "promise_rewards",
    "update_app_version",
    "soft_billing",
]
ITEM_BEARING_ACTIONS = ["collect_resource", "promise_rewards"]
KINDS = ["string", "numeric", "boolean", "enumeration"]
FIELD_KINDS = KINDS + ["image"]
FEATURE_TYPES = ["standard", "mission", "milestone"]
BUCKETS = ["images", "buttons", "texts", "customs"]
# Singular names: they label ONE row's bucket badge and the add buttons, where
# the plural section headers used to do the job.
BUCKET_BADGES = {
    "images": "image",
    "buttons": "button",
    "texts": "text",
    "customs": "custom element",
}
BUCKET_LABELS = {
    "images": "Images",
    "buttons": "Buttons",
    "texts": "Texts",
    "customs": "Custom elements",
}
# operator decision: no invented defaults. textLimit / size / backgroundImg are
# neither shown on this page nor required by the API, so the page never mints
# them — it only passes through what the build actually carried.

# Mirrors inapp_template_build.TEMPLATE_DESCRIPTION_MAX (server limit).
TEMPLATE_DESCRIPTION_MAX = 50

ELEMENT_KEY_RE = "^[a-z][a-z0-9_]*$"
TEMPLATE_KEY_RE = "^[a-zA-Z][a-zA-Z0-9_]*$"

# Seeds used when the developer switches featureType to a type the build did
# not produce. Mirrors _mission_feature({}) / _milestone_feature({}).
MISSION_DEFAULTS = {
    "key": "missions",
    "name": "Missions",
    "missionLayout": "parallel",
    "progressBar": {
        "display": "show_for_all_sets_combined",
        "completionBarCta": ["collect_resource"],
    },
    # the API-required fallback; mockup-derived menus arrive via the build
    "completionCta": ["close"],
    "maxPlacements": 3,
    "maxSetsCount": 1,
    "minPlacements": 1,
    "minSetsCount": 1,
}
MILESTONE_DEFAULTS = {
    "key": "main_progressbar",
    "name": "Main Progressbar",
    "limit": 3,
    # operator decision: CTA menus ship only when derived from the mockup —
    # a page-seeded milestone block carries none (the dashboard demands the
    # choice on save)
}

# Magic-byte sniffing: the extension lies often enough that trusting it would
# produce a data: URI the browser refuses to decode.
IMAGE_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def _sniff_mime(head: bytes) -> str | None:
    for magic, mime in IMAGE_MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _read_image(path: str) -> tuple[bytes | None, str | None]:
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        return None, None
    mime = _sniff_mime(blob[:16])
    return (blob, mime) if mime else (None, None)


def image_data_uri(path: str) -> str | None:
    """Read an image and return it as a data: URI, or None if unusable."""
    blob, mime = _read_image(path)
    if not mime:
        return None
    return "data:" + mime + ";base64," + base64.b64encode(blob).decode("ascii")


def _pixel_size(blob: bytes, mime: str) -> tuple[int, int] | None:
    """Dimensions straight out of the file header (PNG/GIF — the cheap cases)."""
    if mime == "image/png" and len(blob) >= 24:
        return (int.from_bytes(blob[16:20], "big"), int.from_bytes(blob[20:24], "big"))
    if mime == "image/gif" and len(blob) >= 10:
        return (int.from_bytes(blob[6:8], "little"), int.from_bytes(blob[8:10], "little"))
    return None


def image_fingerprint(path: str, declared: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Joinability metadata for the corrections feedback — never the image itself.

    The bytes are hashed so a correction can be joined back to the exact mockup
    it was drawn on; the image is deliberately NOT carried (it is client IP, and
    the telemetry channel rejects blobs).
    """
    blob, mime = _read_image(path)
    if not mime:
        return None
    size = _pixel_size(blob, mime) or (
        (declared or {}).get("width"), (declared or {}).get("height"))
    return {"sha256": hashlib.sha256(blob).hexdigest(),
            "width": size[0], "height": size[1],
            "filename": os.path.basename(path)}


def resolve_image(build: dict[str, Any], image_arg: str | None,
                  build_path: str | None) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Return (data_uri, resolved_path, fingerprint). All None when there is no image."""
    candidates: list[str] = []
    if image_arg:
        candidates.append(image_arg)
    else:
        declared = ((build.get("report") or {}).get("source_image") or {}).get("path")
        if declared:
            candidates.append(declared)
            if build_path:
                # Analyses usually carry the image path relative to wherever the
                # vision pass ran, which is normally next to the build output.
                candidates.append(os.path.join(os.path.dirname(os.path.abspath(build_path)), declared))
    declared = ((build.get("report") or {}).get("source_image") or {})
    for cand in candidates:
        if not os.path.isfile(cand):
            continue
        uri = image_data_uri(cand)
        if uri:
            return uri, os.path.abspath(cand), image_fingerprint(cand, declared)
    return None, None, None


CSS = """
/* Visual language is shared with the SDK merge-plan page: same tokens, cards,
   rows, badges, buttons and fixed dark footer. Light-only by design (a `light
   dark` scheme flips control text over our fixed light surfaces). */
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0;
       background: #f6f8fa; color: #1f2328; }
header { padding: 1.2rem 1.5rem 0; max-width: 1320px; margin: 0 auto; }
header .bar { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 0.9rem 1.2rem; }
h1 { font-size: 1.25rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.05rem; margin: 0 0 0.5rem; }
h3 { font-size: 0.98rem; margin: 0; }
main { max-width: 1320px; margin: 0 auto; padding: 0.75rem 1.5rem 5rem; }
.card { background: #fff; border: 1px solid #d0d7de; border-radius: 8px;
        padding: 1rem 1.2rem; margin-top: 1rem; }
.card.bad { border-color: #ff8182; border-left: 4px solid #cf222e; }
.card.warn { border-color: #d4a72c; border-left: 4px solid #bf8700; }
.card ul { margin: 0.3rem 0 0 1.1rem; padding: 0; font-size: 0.88rem; }
.card pre { background: #f6f8fa; border-radius: 6px; padding: 0.5rem; overflow-x: auto;
            font-size: 0.78rem; margin: 0.3rem 0 0; }
.muted { color: #57606a; font-size: 0.86rem; }
details.card > summary { cursor: pointer; font-size: 1.05rem; font-weight: 600;
  list-style: none; }
details.card > summary::marker, details.card > summary::-webkit-details-marker { display: none; }
details.card > summary::before { content: "▸ "; color: #57606a; }
details.card[open] > summary::before { content: "▾ "; }
code { background: #f6f8fa; padding: 0.05rem 0.3rem; border-radius: 4px; }

[hidden] { display: none !important; } /* .grid's display:flex would otherwise beat the UA [hidden] rule */
.grid { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; }
.row { border: 1px solid #e6e8eb; border-radius: 6px; padding: 0.6rem 0.8rem; margin: 0.55rem 0; }
/* Select-first: an unticked row stays alive but dimmed — this page has no
   destructive drop for a proposal the vision pass produced. */
.row.excluded { opacity: 0.45; }
.row.invalid { border-color: #ffcecb; background: #fff8f8; }
.row.hl { box-shadow: 0 0 0 3px #ffd33d; }
.row.b-images { border-left: 3px solid #0969da; }
.row.b-buttons { border-left: 3px solid #8250df; }
.row.b-texts { border-left: 3px solid #bc4c00; }
.row.b-customs { border-left: 3px solid #1b7c83; }
.row .confirm-note { font-size: 0.82rem; margin-top: 0.4rem; padding: 0.3rem 0.5rem;
  background: #fff8c5; border: 1px solid #d4a72c; border-radius: 6px; color: #7d4e00; }

input[type=text], input[type=number], select { font: inherit; padding: 0.3rem 0.45rem;
  border: 1px solid #d0d7de; border-radius: 6px; background: #fff; color: #1f2328; }
select[multiple] { min-height: 5.4rem; }
input.bad, select.bad { border-color: #cf222e; background: #fff5f5; }
input.inc { width: 1.05rem; height: 1.05rem; accent-color: #1f883d; }
.chips { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.25rem; }
.chip { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.8rem;
  border: 1px solid #d0d7de; border-radius: 999px; padding: 0.1rem 0.55rem; background: #fff;
  cursor: pointer; }
.chip input { accent-color: #1f883d; margin: 0; }
.chip.on { border-color: #1f883d; color: #1a7f37; }
.chips.bad { outline: 1px solid #cf222e; outline-offset: 2px; border-radius: 8px; }
.badge { display: inline-block; font-size: 0.72rem; padding: 0.1rem 0.5rem; border-radius: 999px;
         border: 1px solid currentColor; white-space: nowrap; }
.b-images { color: #0969da; } .b-buttons { color: #8250df; }
.b-texts { color: #bc4c00; } .b-customs { color: #1b7c83; }
.b-new { color: #1a7f37; } .b-idx { color: #57606a; } .b-client { color: #8c959f; }

button { font: inherit; padding: 0.35rem 0.8rem; border-radius: 6px; cursor: pointer;
         border: 1px solid #d0d7de; background: #fff; color: #1f2328; }
button.ghost { border-style: dashed; }
button.primary { background: #1f883d; border-color: #1f883d; color: #fff; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
/* SIZE is container-free on purpose: these rules used to be scoped to
   `.grid > …`, so the moment a button sat anywhere other than a direct child of
   a .grid (the custom-field ✕) it fell back to the base button size and rendered
   larger than done/edit. Anything with these classes is small, wherever it sits.
   Positioning is the .row-actions container's job, not the buttons'. */
button.pencil, button.remove, button.move {
  padding: 0.15rem 0.6rem; font-size: 0.85rem; }
button.remove { color: #c0392b; }

/* The row's action buttons live in ONE flex container that owns the right
   alignment. The old per-button `margin-left: auto` chain broke the moment a
   button was hidden or absent (a display:none ↑ contributes no auto margin),
   which is what set the cluster adrift. A container cannot drift. */
.row-actions { margin-left: auto; display: flex; gap: 0.35rem; align-items: center; }
/* Steppers are the precision fallback: hidden until the #N badge is clicked, so
   a 20-row list is not a wall of arrows. */
.row button.move { display: none; }
.row.steppers-on button.move { display: inline-block; }
.badge.idx { cursor: pointer; }
/* operator decision: placement is triggered by the badge itself — the page's
   badge-as-handle grammar (like #N revealing the steppers). No place button. */
.badge.place-badge { cursor: pointer; }
/* operator decision: NO border/ring on hover — cursor plus a flat tint only */
.badge.place-badge:hover { background: #f6f8fa; }
.row .drag { cursor: grab; color: #8c959f; user-select: none; touch-action: none;
  font-size: 0.95rem; letter-spacing: -1px; }
.row.dragging { opacity: 0.55; }
.drop-line { height: 0; border-top: 2px solid #1f883d; margin: 0.15rem 0; }
/* the add cluster is its own line under the summary, left-aligned */
.fp-group + .fp-group { margin-top: 0.35rem; }
#fp-maxMilestones-wrap:not([hidden]) { display: inline-flex; gap: 0.6rem;
  align-items: center; }
.fp-group-label { font-weight: 600; }
.add-cluster { display: flex; flex-wrap: wrap; gap: 0.35rem;
  margin-top: 0.5rem; margin-bottom: 1rem; }
/* operator decision: each add button wears its bucket's category colour — the
   same b-<bucket> hues as the overlay boxes, the legend swatches and the row
   accents, so the mapping reads instantly. Ghost style is kept; the colour
   comes from the b-<bucket> class via currentColor. */
.add-cluster button.add-el { border-color: currentColor; }
.add-cluster button.add-el:hover { background: #f6f8fa; }
table.sub { width: 100%; border-collapse: collapse; margin-top: 0.4rem; }
table.sub td { padding: 0.15rem 0.3rem; font-size: 0.85rem; }
table.sub tr.cf-off td { opacity: 0.5; text-decoration: line-through; }
.cf-block { margin-top: 0.5rem; padding-top: 0.45rem; border-top: 1px dashed #d0d7de; }
.cf-block .cf-rows { display: block; }
.cf-row { margin-top: 0.35rem; }
/* The button used to be an inline-block sitting on an anonymous line of its own:
   its margin-top was absorbed by the line box, and a freshly added field row
   could ride over it. As a block it gets its own box, so it always lands BELOW
   the rows with real breathing room, at any field count. */
.cf-block .cf-add { display: block; margin-top: 0.5rem; }
.tpl-name { font-weight: 600; font-size: 1.02rem; }

footer { position: fixed; bottom: 0; left: 0; right: 0; background: #1f2328; color: #fff;
         padding: 0.7rem 1.5rem; display: flex; gap: 1rem; align-items: center; z-index: 30; }
footer .grow { flex: 1; }
footer .muted { color: #b1bac4; }
#status { font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 999px;
          border: 1px solid currentColor; }
#status.ok { color: #7ee787; } #status.warn { color: #f2cc60; } #status.bad { color: #ffa198; }
#flash { margin-left: 0.5rem; font-size: 0.86rem; }

/* Page-specific: the mockup overlay, styled in the same language. */
.cols { display: grid; grid-template-columns: minmax(300px, 34%) 1fr; gap: 1rem; align-items: start; }
.cols.no-image { grid-template-columns: 1fr; }
@media (max-width: 1080px) { .cols { grid-template-columns: 1fr; } }
.mockup-col { position: sticky; top: 1rem; }
.stage { position: relative; display: block; border: 1px solid #d0d7de; border-radius: 6px;
         overflow: hidden; background: #f6f8fa; }
.stage img { display: block; width: 100%; height: auto; }
.stage.placing { cursor: crosshair; }
.stage.placing #overlay { cursor: crosshair; }
.legend i.dash { background: transparent !important; border: 1px dashed #57606a; }
#overlay { position: absolute; inset: 0; }
.box { position: absolute; border: 2px solid #0969da; border-radius: 3px; cursor: pointer; }
/* A label sticks out above its box, so it must never take the pointer for the
   area it visually covers. */
.box .tag { pointer-events: none;
  position: absolute; top: -0.05rem; left: -0.05rem; transform: translateY(-100%);
  font-size: 0.62rem; line-height: 1.25; padding: 0 0.25rem; border-radius: 3px;
  color: #fff; background: #0969da; white-space: nowrap; }
.box.b-images { border-color: #0969da; } .box.b-images .tag { background: #0969da; }
.box.b-buttons { border-color: #8250df; } .box.b-buttons .tag { background: #8250df; }
.box.b-texts { border-color: #bc4c00; } .box.b-texts .tag { background: #bc4c00; }
.box.b-customs { border-color: #1b7c83; } .box.b-customs .tag { background: #1b7c83; }
/* Hand-placed boxes stay in their bucket colour but go dashed, so "the developer
   put this here" reads at a glance next to the vision pass's solid boxes. */
.box.placed { border-style: dashed; }
.box.client, .box.excluded { border-style: dashed; border-color: #8c959f; opacity: 0.6; }
.box.client .tag, .box.excluded .tag { background: #8c959f; }
.box.hl { box-shadow: 0 0 0 3px #ffd33d; }
.box.movable { cursor: move; }
.box .handle { position: absolute; width: 8px; height: 8px; background: #fff;
  border: 1px solid currentColor; border-radius: 2px; }
.box .handle.nw { left: -4px; top: -4px; cursor: nwse-resize; }
.box .handle.ne { right: -4px; top: -4px; cursor: nesw-resize; }
.box .handle.sw { left: -4px; bottom: -4px; cursor: nesw-resize; }
.box .handle.se { right: -4px; bottom: -4px; cursor: nwse-resize; }
/* While placing, the whole overlay is click-through: the stage must receive the
   click even where a full-bleed background box covers the image. */
#overlay.placing .box { pointer-events: none; }
.legend { margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.4rem 0.8rem; }
.legend i { width: 0.7rem; height: 0.7rem; display: inline-block; border-radius: 2px;
  margin-right: 0.25rem; vertical-align: -1px; }
.cr-list { margin-top: 0.6rem; }
.cr-list li { margin-bottom: 0.2rem; }
#preview { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 0.75rem;
  font-size: 0.78rem; max-height: 26rem; overflow: auto; white-space: pre; }
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinoa &mdash; Confirm in-app template</title>
<style>__KINOA_CSS__</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>Confirm the in-app template</h1>
    <div class="muted" id="meta"></div>
    <div class="muted" style="margin-top:0.45rem">
      This structure was read off the mockup by a vision pass and shaped by the deterministic
      builder. <b>Nothing is sent anywhere from this page.</b> Check every box on the picture
      against the row next to it &middot; tick the elements to register (unticked rows are left
      out &mdash; nothing is deleted) &middot; <b>&#9998; edit</b> opens a row, <b>&#10003; done</b>
      closes it &middot; <b>&#65291;</b> adds what the pass missed. Keys and names ship
      byte-for-byte onto the Dashboard.
    </div>
    <div class="muted" style="margin-top:0.45rem">
      Dashed grey boxes are <b>client-rendered</b> regions: the client draws them itself, so they
      are deliberately not template elements &mdash; they are shown only so you can confirm nothing
      was wrongly dropped. Prefer chat? Ask the assistant for edits ("rename X to Y") and it will
      refresh this page for your final tick-and-download.
    </div>
  </div>
</header>
<main>
<div id="build-notes"></div>
<div id="live-errors"></div>

<div class="card" id="tpl-card">
  <div class="grid" id="tpl-head"></div>
  <div id="tpl-edit" hidden>
  <div class="grid" style="margin-top:0.5rem">
    <span class="muted">name</span>
    <input type="text" id="tpl-name" size="24" placeholder="Summer Offer">
    <span class="muted">key</span>
    <input type="text" id="tpl-key" size="20" placeholder="summer_offer">
    <span class="muted">feature</span>
    <select id="tpl-feature"></select>
  </div>
  <div class="grid" style="margin-top:0.5rem">
    <span class="muted">description</span>
    <input type="text" id="tpl-desc" size="60" placeholder="What this pop-up is for">
  </div>
  <div id="fp-mission" hidden style="margin-top:0.5rem">
    <div class="grid fp-group">
      <span class="muted fp-group-label" title="How many mission slots will be visible to the user on screen (e.g. min 1, max 10).">Number of Missions</span>
      <span class="muted" title="How many mission slots will be visible to the user on screen (e.g. min 1, max 10).">min</span><input type="number" id="fp-minPlacements" min="1" size="4" title="How many mission slots will be visible to the user on screen (e.g. min 1, max 10).">
      <span class="muted" title="How many mission slots will be visible to the user on screen (e.g. min 1, max 10).">max</span><input type="number" id="fp-maxPlacements" min="1" size="4" title="How many mission slots will be visible to the user on screen (e.g. min 1, max 10).">
    </div>
    <div class="grid fp-group">
      <span class="muted fp-group-label" title="How many sets (groups of missions) are allowed for this template (e.g. min 1, max 7).">Number of Mission Sets</span>
      <span class="muted" title="How many sets (groups of missions) are allowed for this template (e.g. min 1, max 7).">min</span><input type="number" id="fp-minSetsCount" min="1" size="4" title="How many sets (groups of missions) are allowed for this template (e.g. min 1, max 7).">
      <span class="muted" title="How many sets (groups of missions) are allowed for this template (e.g. min 1, max 7).">max</span><input type="number" id="fp-maxSetsCount" min="1" size="4" title="How many sets (groups of missions) are allowed for this template (e.g. min 1, max 7).">
    </div>
    <div class="grid fp-group">
      <span class="muted" title="Controls how placements behave inside a set. Parallel: all placements in a set are active at the same time — the user can progress on any placement, in any order. Sequential: placements unlock one at a time — the current placement must be completed to unlock the next; the client receives upcoming placements as locked previews. Sub-missions (the chain inside a single placement) work the same in both modes.">layout</span><select id="fp-missionLayout" title="Controls how placements behave inside a set. Parallel: all placements in a set are active at the same time — the user can progress on any placement, in any order. Sequential: placements unlock one at a time — the current placement must be completed to unlock the next; the client receives upcoming placements as locked previews. Sub-missions (the chain inside a single placement) work the same in both modes."></select>
      <span class="muted" title="Controls whether mission progression is visually tracked via a progress bar.">progress bar</span><select id="fp-progressBar" title="Controls whether mission progression is visually tracked via a progress bar."></select>
      <span id="fp-maxMilestones-wrap" hidden>
        <span class="muted" title="Maximum number of milestones on the combined progress bar.">maxMilestones</span><input type="number" id="fp-maxMilestones" min="1" size="4" title="Maximum number of milestones on the combined progress bar.">
      </span>
    </div>
    <div class="fp-group" id="fp-mission-ctas"></div>
  </div>
  <div id="fp-milestone" hidden style="margin-top:0.5rem">
  <div class="grid fp-group">
    <span class="muted" title="The number of milestones the progress bar supports.">max milestones</span><input type="number" id="fp-limit" min="1" size="4" title="The number of milestones the progress bar supports.">
  </div>
    <div class="fp-group" id="fp-milestone-ctas"></div>
  </div>
  <div class="muted" id="fp-note" style="margin-top:0.4rem"></div>
  </div>
</div>

<div class="cols" id="cols">
  <div class="mockup-col" id="mockup-col">
    <div class="card">
      <h2>Mockup</h2>
      <div class="stage" id="stage">
        <img id="mockup" alt="mockup">
        <div id="overlay"></div>
      </div>
      <div class="muted" id="place-hint" hidden style="margin-top:0.4rem"></div>
      <div class="legend muted">
        <span><i style="background:#0969da"></i>images</span>
        <span><i style="background:#8250df"></i>buttons</span>
        <span><i style="background:#bc4c00"></i>texts</span>
        <span><i style="background:#1b7c83"></i>customs</span>
        <span><i style="background:#8c959f"></i>client-rendered / excluded</span>
        <span><i class="dash"></i>placed by hand (dashed, bucket colour)</span>
      </div>
      <div class="cr-list muted" id="cr-list"></div>
    </div>
  </div>
  <div class="card" id="elements-card">
    <div id="elements-head"></div>
    <div id="elements"></div>
  </div>
</div>

<details class="card" id="preview-box">
  <!-- operator decision: no "(debug)" suffix here — do not restore it -->
  <summary>Payload that will be registered</summary>
  <div class="muted" style="margin-top:0.4rem">
    Select and copy this block if the footer buttons are blocked by your browser. It refreshes
    with every edit, open or closed.
  </div>
  <pre id="preview"></pre>
</details>
</main>
<footer>
  <div class="grow"><span id="counter"></span> <span id="status" class="ok">Ready</span></div>
  <button id="download" class="primary">&#11015; Download template</button>
  <button id="copy">Copy JSON</button>
  <span class="muted">&#8984;Z / Ctrl+Z undo &middot; &#8679;&#8984;Z / Ctrl+Y redo</span>
  <span id="flash"></span>
</footer>
<script>
"use strict";
var DATA = __KINOA_DATA__;
var C = __KINOA_CONSTS__;
var IMAGE_SRC = __KINOA_IMAGE__;

var P = DATA.payload || {};
var REPORT = DATA.report || {};
var BUILD_VALIDATION = DATA.validation || {};
var KEY_RE = new RegExp(C.elementKeyRe);
var TPL_KEY_RE = new RegExp(C.templateKeyRe);

// operator decision: the UI speaks product names (none / missions /
// milestones); option VALUES stay the wire vocabulary (standard / mission /
// milestone) — the payload contract is untouched.
var FEATURE_LABELS = { standard: "none", mission: "missions", milestone: "milestones" };
// operator request: dashboard wording as hover help on the feature options.
var FEATURE_HINTS = {
  mission: "Missions let you define task-based challenges with goals, rewards, and CTAs "
         + "across one or more sets (e.g., daily tasks or event quests)."
};

function clone(v) { return v === undefined ? null : JSON.parse(JSON.stringify(v)); }
// Select-first: `included` gates the export, it never removes data.
function inc(e) { return e.included !== false; }
function esc(s) {
  var d = document.createElement("span");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
function num(v, fallback) {
  var n = parseInt(v, 10);
  return isNaN(n) ? fallback : n;
}

// ---- trace: bucket+key -> where the element sits on the mockup ----------
var TRACE = {};
(REPORT.elements || []).forEach(function (t) { TRACE[t.bucket + "\\u0000" + t.key] = t; });

// Roles the picture cannot disambiguate. The builder keeps them in the payload
// but flags the question — the developer answers it here, on the row.
var CONFIRM = {};
(REPORT.needs_confirmation || []).forEach(function (n) { CONFIRM[n.bucket + "\\u0000" + n.key] = n; });

var uidSeq = 0;

// Every element carries the fields of ALL FOUR buckets in page state; export
// emits only the ones its current bucket needs. That is what makes a bucket
// switch lossless in both directions (switch away and back, nothing is lost)
// while still writing that bucket's defaults for fields it never had.
var fieldSeq = 0;

// A CUSTOM FIELD is a typed field attached to ANY element via customFields —
// a different entity from a custom ELEMENT (a standalone row in the customs
// bucket). Fields accept the extra 'image' kind; custom elements do not.
function normalizeCustomField(raw, pageNew) {
  raw = raw || {};
  return {
    _uid: "cf" + (++fieldSeq),
    _pageNew: !!pageNew,
    included: raw.included !== false,
    key: raw.key || "",
    kind: C.fieldKinds.indexOf(raw.kind) >= 0 ? raw.kind : "string",
    name: raw.name || "",
    nullable: raw.nullable !== false,
    description: raw.description || "",
    defaultValue: raw.defaultValue === undefined || raw.defaultValue === null
      ? "" : raw.defaultValue,
    enumValues: raw.enumValues === undefined || raw.enumValues === null
      ? "" : raw.enumValues
  };
}

function normalizeElement(bucket, el) {
  var t = TRACE[bucket + "\\u0000" + (el.key || "")] || null;
  var c = CONFIRM[bucket + "\\u0000" + (el.key || "")] || null;
  return {
    uid: "e" + (++uidSeq),
    bucket: bucket,
    included: el.included !== false,
    _pageNew: false,
    confirm: c ? c.question : "",
    key: el.key || "",
    name: el.name || "",
    description: el.description || "",
    canBeHidden: el.canBeHidden !== false,
    customFields: (el.customFields || []).map(function (cf) {
      return normalizeCustomField(cf, false);
    }),
    bbox: t && t.bbox ? clone(t.bbox) : null,
    // What the vision pass reported, kept so an adjustment can ship as a delta.
    _origBbox: t && t.bbox ? clone(t.bbox) : null,
    _adjusted: false,
    role: t ? (t.role || "") : "",
    observedText: t ? (t.observed_text || "") : "",
    confidence: t && t.confidence != null ? t.confidence : null,
    // operator decision: absent stays absent — these are never invented here.
    size: el.size ? clone(el.size) : null,
    backgroundImg: el.backgroundImg ? clone(el.backgroundImg) : null,
    textLimit: el.textLimit === undefined || el.textLimit === null ? null : el.textLimit,
    nullable: el.nullable !== false,
    clickActionType: Array.isArray(el.clickActionType) && el.clickActionType.length
      ? el.clickActionType.slice() : ["close"],
    // Held as a comma-separated string while editing (same idiom as enumValues)
    // and split back into a list on export.
    customCtaNames: Array.isArray(el.customCtaNames) ? el.customCtaNames.join(", ")
      : (el.customCtaNames || ""),
    requiredItemsCount: num(el.requiredItemsCount, 1),
    kind: C.kinds.indexOf(el.kind) >= 0 ? el.kind : "string",
    defaultValue: el.defaultValue === undefined || el.defaultValue === null ? "" : el.defaultValue,
    enumValues: el.enumValues === undefined || el.enumValues === null ? "" : el.enumValues
  };
}

var state = {
  name: P.name || "",
  key: P.key || "",
  description: P.description || "",
  hasGameId: Object.prototype.hasOwnProperty.call(P, "gameId") && !!P.gameId,
  gameId: P.gameId || "",
  featureType: C.featureTypes.indexOf(P.featureType) >= 0 ? P.featureType : "standard",
  features: clone(P.features),
  tagsIds: Array.isArray(P.tagsIds) ? P.tagsIds.slice() : [],
  elements: []
};
// The global sequence IS the builder's reading order: production templates
// interleave buckets (header, upper text, badge, CTA, price cut, close, fine
// print) and `index` is what the dashboard constructor renders by. Loading
// bucket by bucket would silently re-group it.
(function loadElements() {
  var flat = [];
  C.buckets.forEach(function (b) {
    (P[b] || []).forEach(function (el) { flat.push({ bucket: b, el: el }); });
  });
  flat.sort(function (a, b2) {
    var ai = typeof a.el.index === "number" ? a.el.index : Number.MAX_SAFE_INTEGER;
    var bi = typeof b2.el.index === "number" ? b2.el.index : Number.MAX_SAFE_INTEGER;
    return ai - bi;
  });
  flat.forEach(function (item) {
    state.elements.push(normalizeElement(item.bucket, item.el));
  });
})();

// ---- export -------------------------------------------------------------
// The global sequence: state.elements in its own order. Rows are still shown
// grouped by bucket, so a bucket's #N badges are legitimately non-contiguous.
function orderedElements(includedOnly) {
  return state.elements.filter(function (e) { return !includedOnly || inc(e); });
}

// Excluded rows get no index at all — the exported indexes stay a dense
// 0..N-1 over what actually ships.
function indexMap() {
  var m = {};
  orderedElements(true).forEach(function (e, i) { m[e.uid] = i; });
  return m;
}

function coerceValue(kind, value) {
  if (kind === "boolean") return String(value) === "true";
  if (kind === "numeric") {
    var n = Number(value);
    return value === "" || isNaN(n) ? 0 : n;
  }
  return String(value);
}

function coerceDefault(e) { return coerceValue(e.kind, e.defaultValue); }

// Select-first applies to custom fields too: an unticked field keeps its data on
// the page and is simply absent from the payload.
function customFieldsOut(e) {
  return (e.customFields || []).filter(function (cf) { return cf.included !== false; })
    .map(function (cf) {
      var out = { key: String(cf.key).trim(), kind: cf.kind, name: cf.name,
                  nullable: !!cf.nullable, description: cf.description,
                  defaultValue: coerceValue(cf.kind, cf.defaultValue) };
      if (cf.kind === "enumeration") out.enumValues = String(cf.enumValues);
      return out;
    });
}

function elementOut(e, index) {
  var key = String(e.key).trim();
  var name = String(e.name).trim();
  var desc = String(e.description);
  if (e.bucket === "images") {
    var img = { key: key, name: name, index: index, description: desc,
                canBeHidden: !!e.canBeHidden, customFields: customFieldsOut(e) };
    if (e.size) img.size = clone(e.size);          // passthrough only
    return img;
  }
  if (e.bucket === "buttons") {
    var out = { key: key, name: name, index: index,
                description: desc, canBeHidden: !!e.canBeHidden, customFields: customFieldsOut(e),
                clickActionType: e.clickActionType.slice() };
    if (e.backgroundImg) out.backgroundImg = clone(e.backgroundImg);   // passthrough only
    if (e.textLimit !== null && e.textLimit !== "") out.textLimit = num(e.textLimit, 0);
    if (needsItems(e)) out.requiredItemsCount = num(e.requiredItemsCount, 1);
    // The names are what the game client switches on, so they ship only while
    // the 'custom' action is actually offered.
    if (hasCustomAction(e)) out.customCtaNames = ctaNameList(e);
    return out;
  }
  if (e.bucket === "texts") {
    var txt = { key: key, name: name, index: index, nullable: !!e.nullable,
                description: desc, canBeHidden: !!e.canBeHidden,
                customFields: customFieldsOut(e) };
    if (e.textLimit !== null && e.textLimit !== "") txt.textLimit = num(e.textLimit, 0);
    return txt;
  }
  var custom = { key: key, name: name, kind: e.kind, index: index, nullable: !!e.nullable,
                 description: desc, canBeHidden: !!e.canBeHidden,
                 customFields: customFieldsOut(e), defaultValue: coerceDefault(e) };
  if (e.kind === "enumeration") custom.enumValues = String(e.enumValues);
  return custom;
}

function needsItems(e) {
  return e.clickActionType.some(function (a) { return C.itemBearing.indexOf(a) >= 0; });
}

function hasCustomAction(e) { return e.clickActionType.indexOf("custom") >= 0; }

function ctaNameList(e) {
  return String(e.customCtaNames).split(",").map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length; });
}

function buildTemplate() {
  var body = { name: String(state.name).trim(), key: String(state.key).trim(),
               description: String(state.description) };
  if (state.hasGameId) body.gameId = state.gameId;
  // Indexes come from the GLOBAL sequence; the four arrays are just the payload's
  // shape, not the ordering.
  var idx = indexMap();
  C.buckets.forEach(function (b) {
    body[b] = state.elements.filter(function (e) { return e.bucket === b && inc(e); })
      .map(function (e) { return elementOut(e, idx[e.uid]); });
  });
  body.featureType = state.featureType;
  // The create contract sends {} for a standard template — not null.
  body.features = state.featureType === "standard" ? {} : featuresOut();
  body.tagsIds = Array.isArray(state.tagsIds) ? state.tagsIds.slice() : [];
  return body;
}

// The feature panel keeps raw strings too; coerce the numeric knobs here.
var FEATURE_NUMERICS = { mission: ["maxPlacements", "maxSetsCount", "minPlacements", "minSetsCount"],
                         milestone: ["limit"] };

function featuresOut() {
  // Strict isolation: the fields belong to exactly one type (maxPlacements /
  // minPlacements / maxSetsCount / minSetsCount -> mission, limit -> milestone,
  // standard -> nothing), so only the ACTIVE type's block is ever serialised.
  // featuresStash keeps the other type's values page-side for a flip back —
  // it must never reach the payload.
  var t = state.featureType;
  if (t === "standard") return {};
  var block = clone((state.features || {})[t]);
  if (!block || typeof block !== "object") return {};
  (FEATURE_NUMERICS[t] || []).forEach(function (k) {
    if (k in block) block[k] = num(block[k], 1);
  });
  // An emptied milestone menu goes back to "the dashboard chooses": the key is
  // dropped, never shipped as an empty array.
  ["mainActionTypes", "milestonesActionTypes"].forEach(function (k) {
    if (Array.isArray(block[k]) && !block[k].length) delete block[k];
  });
  // maxMilestones is nested in progressBar and optional: an empty field means
  // "no cap", so the key is dropped rather than coerced to a number.
  if (block.progressBar && "maxMilestones" in block.progressBar) {
    var raw = block.progressBar.maxMilestones;
    // A hidden bar has no cap in the contract, and an empty field means "no cap".
    if (raw === "" || raw === null || raw === undefined
        || block.progressBar.display === "dont_show_at_all") {
      delete block.progressBar.maxMilestones;
    } else {
      block.progressBar.maxMilestones = num(raw, 1);
    }
  }
  var out = {};
  out[t] = block;
  return out;
}

// House hand-back contract: both established pages stamp their export, so a
// stale file handed back to the skill is detectable.
// Geometry NEVER enters the template payload — templates have no coordinates.
// It rides alongside as feedback for the analysis corpus: "the pass missed this
// element, and here is where it actually sits".
function correctionsOut() {
  var missed = [], adjusted = [], excluded = [];
  var source = DATA.image_fingerprint || null;
  state.elements.forEach(function (e) {
    var key = String(e.key).trim();
    if (!inc(e)) {
      // Un-ticked vision rows are the model's false positives. An un-ticked row
      // the developer added here says nothing about the model, so it is skipped.
      if (!e._pageNew) excluded.push({ key: key, bucket: e.bucket, role: e.role || "" });
      return;
    }
    if (e._pageNew) {
      if (e.bbox) missed.push({ key: key, bucket: e.bucket, bbox: clone(e.bbox) });
      return;
    }
    if (e._adjusted && e.bbox) {
      adjusted.push({ key: key, bucket: e.bucket, bbox: clone(e.bbox),
                      original_bbox: clone(e._origBbox) });
    }
  });
  return { source_image: source, missed: missed, adjusted: adjusted, excluded: excluded };
}

function buildEnvelope() {
  return { confirmed_at: new Date().toISOString(),
           page_generated_at: DATA.generated_at || "",
           corrections: correctionsOut(),
           payload: buildTemplate() };
}

function exportJson() { return JSON.stringify(buildEnvelope(), null, 2); }
window.exportJson = exportJson;
window.buildTemplate = buildTemplate;

// ---- validation (mirrors inapp_template_build.validate_payload) ---------
function validate() {
  var body = buildTemplate();
  var errors = [];
  var warnings = [];
  var rowErrors = {};
  var fieldErrors = {};
  function rowErr(uid, msg) { rowErrors[uid] = rowErrors[uid] ? rowErrors[uid] + " " + msg : msg; }
  function fieldErr(uid, msg) {
    fieldErrors[uid] = fieldErrors[uid] ? fieldErrors[uid] + " " + msg : msg;
  }

  // Template-level errors are tracked apart: they are what force the header
  // card open, exactly as a row error forces its row open.
  var tplErrors = [];
  if (!body.name) tplErrors.push("Template name is required.");
  if (!TPL_KEY_RE.test(body.key || "")) tplErrors.push("Template key " + JSON.stringify(body.key) + " must match " + C.templateKeyRe);
  if (String(body.description || "").length > C.templateDescriptionMax) {
    tplErrors.push("Template description exceeds the server limit of "
      + C.templateDescriptionMax + " chars.");
  }
  if (body.featureType === "mission" && body.features && body.features.mission
      && !(body.features.mission.completionCta || []).length) {
    tplErrors.push("Mission Completion CTA needs at least one action.");
  }
  if (C.featureTypes.indexOf(body.featureType) < 0) tplErrors.push("Unknown feature type " + JSON.stringify(body.featureType) + ".");
  if (body.featureType === "standard") {
    if (body.features && Object.keys(body.features).length) {
      tplErrors.push("featureType 'standard' must carry features: {}.");
    }
  } else if (!body.features || typeof body.features !== "object" || !body.features[body.featureType]) {
    tplErrors.push("featureType '" + body.featureType + "' requires features." + body.featureType + ".");
  }
  tplErrors.forEach(function (m) { errors.push(m); });

  C.buckets.forEach(function (b) {
    var seen = {};
    // An excluded row ships nothing, so it can never block the export.
    state.elements.filter(function (e) { return e.bucket === b && inc(e); }).forEach(function (e) {
      var k = String(e.key).trim();
      if (!k) { rowErr(e.uid, "Key is required."); errors.push(b + ": an element has no key."); }
      else if (!KEY_RE.test(k)) {
        rowErr(e.uid, "Key must match " + C.elementKeyRe);
        errors.push(b + ": key " + JSON.stringify(k) + " must match " + C.elementKeyRe);
      } else if (seen[k]) {
        rowErr(e.uid, "Duplicate key in this bucket.");
        rowErr(seen[k], "Duplicate key in this bucket.");
        errors.push(b + ": duplicate key " + JSON.stringify(k) + ".");
      } else { seen[k] = e.uid; }
      if (!String(e.name).trim()) rowErr(e.uid, "Name is required.");
      if (b === "buttons") {
        if (!e.clickActionType || !e.clickActionType.length) {
          rowErr(e.uid, "Pick at least one click action.");
          errors.push("buttons." + k + ": clickActionType must be a non-empty list.");
        }
        if (hasCustomAction(e) && !ctaNameList(e).length) {
          rowErr(e.uid, "Action 'custom' needs at least one CTA name.");
          errors.push("buttons." + k + ": action 'custom' requires a non-empty customCtaNames.");
        }
        if (!hasCustomAction(e) && String(e.customCtaNames).trim()) {
          warnings.push("buttons." + k + ": customCtaNames present but 'custom' is not offered — "
            + "they will not be exported.");
        }
      }
      if (b === "customs" && C.kinds.indexOf(e.kind) < 0) {
        rowErr(e.uid, "Unknown kind.");
        errors.push("customs." + k + ": kind " + JSON.stringify(e.kind) + " is invalid.");
      }
      // Custom fields validate per ELEMENT: two elements may reuse a field key,
      // one element may not. Kinds here include 'image' (unlike custom elements).
      var seenField = {};
      (e.customFields || []).forEach(function (cf) {
        if (cf.included === false) return;
        var fk = String(cf.key || "").trim();
        var where = b + "." + k + ": custom field ";
        if (!fk) {
          fieldErr(cf._uid, "Key is required.");
          rowErr(e.uid, "A custom field needs a key.");
          errors.push(where + "has no key.");
        } else if (!KEY_RE.test(fk)) {
          fieldErr(cf._uid, "Key must match " + C.elementKeyRe);
          rowErr(e.uid, "A custom field key is invalid.");
          errors.push(where + JSON.stringify(fk) + " must match " + C.elementKeyRe);
        } else if (seenField[fk]) {
          fieldErr(cf._uid, "Duplicate key on this element.");
          fieldErr(seenField[fk], "Duplicate key on this element.");
          rowErr(e.uid, "Duplicate custom field key.");
          errors.push(where + JSON.stringify(fk) + " is used twice on this element.");
        } else {
          seenField[fk] = cf._uid;
        }
        if (C.fieldKinds.indexOf(cf.kind) < 0) {
          fieldErr(cf._uid, "Unknown kind.");
          errors.push(where + JSON.stringify(fk) + " has invalid kind "
            + JSON.stringify(cf.kind) + ".");
        }
        if (cf.kind === "enumeration" && !String(cf.enumValues).trim()) {
          warnings.push(where + JSON.stringify(fk)
            + " is an enumeration with no enumValues — the operator will have nothing to pick.");
        }
      });
    });
  });

  return { errors: errors, warnings: warnings, rowErrors: rowErrors,
           fieldErrors: fieldErrors, templateErrors: tplErrors,
           count: state.elements.length };
}

// ---- static panels ------------------------------------------------------
function listPanel(title, items, cls, renderItem) {
  if (!items || !items.length) return null;
  var d = document.createElement("div");
  d.className = "card " + cls;
  var h = document.createElement("h2");
  h.textContent = title + " (" + items.length + ")";
  d.appendChild(h);
  var ul = document.createElement("ul");
  items.forEach(function (it) {
    var li = document.createElement("li");
    if (renderItem) renderItem(li, it); else li.textContent = String(it);
    ul.appendChild(li);
  });
  d.appendChild(ul);
  return d;
}

function renderBuildNotes() {
  var host = document.getElementById("build-notes");
  host.innerHTML = "";
  // Needs-confirmation gets the same prominence as unmapped: the element IS in
  // the payload, but keeping it is a decision only the developer can make.
  var confirmPanel = listPanel("Needs your confirmation", REPORT.needs_confirmation || [], "bad",
    function (li, n) {
      li.innerHTML = "<b>" + esc(n.bucket) + "." + esc(n.key) + "</b> (role <code>" + esc(n.role)
        + "</code>) &mdash; " + esc(n.question);
    });
  if (confirmPanel) {
    confirmPanel.querySelector("h2").innerHTML =
      "Needs your confirmation (" + (REPORT.needs_confirmation || []).length
      + ") &mdash; kept in the payload; remove the row if the answer says so";
    host.appendChild(confirmPanel);
  }
  // Unmapped next and never collapsed: an element the builder could not place
  // is the one thing on this page that silently loses data if ignored.
  var unmapped = listPanel("Unmapped &mdash; NOT in the payload, add them by hand if they are real slots",
    REPORT.unmapped || [], "bad", function (li, u) {
      li.innerHTML = "<b>" + esc(u.role == null ? "(no role)" : u.role) + "</b> &mdash; " + esc(u.reason || "");
      var pre = document.createElement("pre");
      pre.textContent = JSON.stringify(u.element || u, null, 2);
      li.appendChild(pre);
    });
  if (unmapped) {
    unmapped.querySelector("h2").innerHTML =
      "Unmapped (" + (REPORT.unmapped || []).length + ") &mdash; NOT in the payload";
    host.appendChild(unmapped);
  }
  var unsup = listPanel("Not expressible as a template", REPORT.unsupported || [], "warn",
    function (li, u) {
      li.innerHTML = "<b>" + esc(u.what) + "</b>" + (u.why ? " &mdash; " + esc(u.why) : "");
    });
  if (unsup) {
    unsup.querySelector("h2").innerHTML =
      "Not expressible as a template (" + (REPORT.unsupported || []).length
      + ") &mdash; the mockup shows it, the model cannot carry it";
    host.appendChild(unsup);
  }
  var verr = listPanel("Build validation errors", BUILD_VALIDATION.errors || [], "bad");
  if (verr) host.appendChild(verr);
  var warn = (REPORT.warnings || []).concat(BUILD_VALIDATION.warnings || []);
  var wp = listPanel("Build warnings", warn, "warn");
  if (wp) host.appendChild(wp);
}

function renderClientRendered() {
  var host = document.getElementById("cr-list");
  var items = REPORT.client_rendered || [];
  if (!items.length) { host.innerHTML = ""; return; }
  var html = "<b>Client-rendered regions (" + items.length + ")</b><ul>";
  items.forEach(function (cr) {
    html += "<li><code>" + esc(cr.role) + "</code> &mdash; " + esc(cr.reason) + "</li>";
  });
  host.innerHTML = html + "</ul>";
}

// ---- overlay ------------------------------------------------------------
// Stacking is by AREA, smallest on top: a full-bleed background box would
// otherwise swallow every hover and click aimed at the elements inside it.
function areaZ(bbox) {
  var area = Math.max(0, Math.min(1, (bbox.w || 0) * (bbox.h || 0)));
  return Math.max(1, 1000 - Math.round(area * 1000));
}

function boxEl(bbox, cls, label) {
  var d = document.createElement("div");
  d.className = "box " + cls;
  d.style.zIndex = areaZ(bbox);
  d.style.left = (bbox.x * 100) + "%";
  d.style.top = (bbox.y * 100) + "%";
  d.style.width = (bbox.w * 100) + "%";
  d.style.height = (bbox.h * 100) + "%";
  var tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = label;
  d.appendChild(tag);
  return d;
}

function renderOverlay(idx) {
  var ov = document.getElementById("overlay");
  if (!ov || !IMAGE_SRC) return;
  ov.innerHTML = "";
  ov.classList.toggle("placing", !!PLACING);
  (REPORT.client_rendered || []).forEach(function (cr) {
    if (!cr.bbox) return;
    ov.appendChild(boxEl(cr.bbox, "client", "client: " + cr.role));
  });
  state.elements.forEach(function (e) {
    if (!e.bbox) return;
    var byHand = !!e._pageNew;
    var label = (inc(e) ? "#" + idx[e.uid] : "excluded") + (e.key ? " " + e.key : "")
      + ""; // operator decision: no "(placed)" suffix on overlay labels — dashed style alone signals hand placement
    var b = boxEl(e.bbox, "b-" + e.bucket + (inc(e) ? "" : " excluded") + (byHand ? " placed" : ""),
                  label);
    b.dataset.uid = e.uid;
    if (inc(e)) {
      b.classList.add("movable");
      b.title = "drag to move, corners to resize — geometry is page-side feedback, "
              + "it never enters the template";
      b.addEventListener("pointerdown", function (ev) {
        beginDrag(e.uid, ev.clientX, ev.clientY, null);
        if (ev.preventDefault) ev.preventDefault();
      });
      ["nw", "ne", "sw", "se"].forEach(function (corner) {
        var h = document.createElement("div");
        h.className = "handle " + corner;
        h.dataset.fid = "rz-" + corner + "-" + e.uid;
        h.addEventListener("pointerdown", function (ev) {
          // The corner owns the gesture: without this the box would also
          // start a move and the two would fight.
          if (ev.stopPropagation) ev.stopPropagation();
          if (ev.preventDefault) ev.preventDefault();
          beginDrag(e.uid, ev.clientX, ev.clientY, corner);
        });
        b.appendChild(h);
      });
    }
    b.addEventListener("mouseenter", function () { highlight(e.uid, true); });
    b.addEventListener("mouseleave", function () { highlight(e.uid, false); });
    b.addEventListener("click", function () {
      var row = document.querySelector('.row[data-uid="' + e.uid + '"]');
      if (row && row.scrollIntoView) row.scrollIntoView({ block: "center" });
    });
    ov.appendChild(b);
  });
}

// ---- manual placement (page-side only) ----------------------------------
var PLACE_W = 0.22, PLACE_H = 0.07;   // default drop size, fraction of the image
var PLACING = null;                   // uid awaiting a click on the mockup
var DRAG = null;                      // {uid, x0, y0, bbox} while dragging a box
var DRAGGING = false;                 // suppresses per-pixel undo snapshots

function elementByUid(uid) {
  return state.elements.filter(function (e) { return e.uid === uid; })[0] || null;
}

function clamp01(v, span) {
  var max = 1 - span;
  return v < 0 ? 0 : (v > max ? (max < 0 ? 0 : max) : v);
}

function stageRect() {
  var st = document.getElementById("stage");
  if (!st || !st.getBoundingClientRect) return null;
  var r = st.getBoundingClientRect();
  // jsdom (and a not-yet-laid-out image) report zeros — a divide by zero would
  // write NaN coordinates into state.
  if (!r || !r.width || !r.height) return null;
  return r;
}

function startPlacing(uid) {
  PLACING = uid;
  var e = elementByUid(uid);
  var hint = document.getElementById("place-hint");
  var stage = document.getElementById("stage");
  var ov = document.getElementById("overlay");
  if (stage) stage.classList.add("placing");
  if (ov) ov.classList.add("placing");
  if (hint) {
    hint.hidden = false;
    hint.textContent = "click on the mockup to place "
      + ((e && e.key) || "this element") + " — Esc cancels";
  }
}

function cancelPlacing() {
  PLACING = null;
  var hint = document.getElementById("place-hint");
  var stage = document.getElementById("stage");
  var ov = document.getElementById("overlay");
  if (stage) stage.classList.remove("placing");
  if (ov) ov.classList.remove("placing");
  if (hint) { hint.hidden = true; hint.textContent = ""; }
}

// One click drops a default-size box centred on the point, clamped into bounds.
function placeAt(uid, clientX, clientY) {
  var r = stageRect();
  var e = elementByUid(uid);
  if (!r || !e) { cancelPlacing(); return; }
  var nx = (clientX - r.left) / r.width - PLACE_W / 2;
  var ny = (clientY - r.top) / r.height - PLACE_H / 2;
  e.bbox = { x: clamp01(nx, PLACE_W), y: clamp01(ny, PLACE_H), w: PLACE_W, h: PLACE_H };
  cancelPlacing();
  refresh();
}
window.placeAt = placeAt;

var DRAG_THRESHOLD = 4;   // px of travel before a hover becomes a drag
var MIN_SPAN = 0.02;      // smallest box, fraction of the image

function bboxEq(a, b) {
  if (!a || !b) return a === b;
  return ["x", "y", "w", "h"].every(function (k) { return Math.abs(a[k] - b[k]) < 1e-9; });
}

function beginDrag(uid, clientX, clientY, corner) {
  var e = elementByUid(uid);
  if (!e || !e.bbox || !stageRect()) return;
  DRAG = { uid: uid, x0: clientX, y0: clientY, bbox: clone(e.bbox),
           corner: corner || null, active: false };
}

// Corner resize: move the two edges the grabbed corner owns, clamp both into the
// image, then hold the box at MIN_SPAN so it can never collapse or invert.
function resizedBox(box, corner, dx, dy) {
  var left = box.x, top = box.y, right = box.x + box.w, bottom = box.y + box.h;
  if (corner.indexOf("w") >= 0) left = Math.min(Math.max(0, left + dx), right - MIN_SPAN);
  if (corner.indexOf("e") >= 0) right = Math.max(Math.min(1, right + dx), left + MIN_SPAN);
  if (corner.indexOf("n") >= 0) top = Math.min(Math.max(0, top + dy), bottom - MIN_SPAN);
  if (corner.indexOf("s") >= 0) bottom = Math.max(Math.min(1, bottom + dy), top + MIN_SPAN);
  return { x: left, y: top, w: right - left, h: bottom - top };
}

function moveDrag(clientX, clientY) {
  if (!DRAG) return;
  var r = stageRect();
  var e = elementByUid(DRAG.uid);
  if (!r || !e) return;
  if (!DRAG.active) {
    var travel = Math.abs(clientX - DRAG.x0) + Math.abs(clientY - DRAG.y0);
    if (travel < DRAG_THRESHOLD) return;   // a jiggle is not an edit
    DRAG.active = true;
  }
  var dx = (clientX - DRAG.x0) / r.width;
  var dy = (clientY - DRAG.y0) / r.height;
  e.bbox = DRAG.corner
    ? resizedBox(DRAG.bbox, DRAG.corner, dx, dy)
    : { x: clamp01(DRAG.bbox.x + dx, DRAG.bbox.w),
        y: clamp01(DRAG.bbox.y + dy, DRAG.bbox.h),
        w: DRAG.bbox.w, h: DRAG.bbox.h };
  // A drag is ONE undoable step: snapshots are suppressed until pointerup.
  DRAGGING = true;
  refresh();
}

function endDrag() {
  if (!DRAG) return;
  var e = elementByUid(DRAG.uid);
  var moved = DRAG.active;
  DRAG = null;
  DRAGGING = false;
  if (!moved) return;   // nothing changed, so nothing to snapshot
  // Derived, not latched: dragging a box back onto its original geometry stops
  // counting as an adjustment, and an undo restores the flag with the bbox.
  if (e && !e._pageNew) e._adjusted = !bboxEq(e.bbox, e._origBbox);
  refresh();   // pushes the single post-drag snapshot
}

function highlight(uid, on) {
  var box = document.querySelector('.box[data-uid="' + uid + '"]');
  var row = document.querySelector('.row[data-uid="' + uid + '"]');
  if (box) box.classList.toggle("hl", on);
  if (row) row.classList.toggle("hl", on);
}

// ---- element rows -------------------------------------------------------
function lab(text) {
  var sp = document.createElement("span");
  sp.className = "muted";
  sp.textContent = text;
  return sp;
}

function badge(text, cls, title) {
  var b = document.createElement("span");
  b.className = "badge " + (cls || "");
  b.textContent = text;
  if (title) b.title = title;
  return b;
}

function textInput(value, fid, oninput, opts) {
  opts = opts || {};
  var inp = document.createElement("input");
  inp.type = opts.number ? "number" : "text";
  inp.value = value == null ? "" : value;
  if (opts.placeholder) inp.placeholder = opts.placeholder;
  if (opts.size) inp.size = opts.size;
  if (opts.bad) inp.classList.add("bad");
  inp.dataset.fid = fid;
  inp.addEventListener("input", function (ev) { oninput(ev.target.value); });
  return inp;
}

function selectInput(values, current, fid, onchange, opts) {
  opts = opts || {};
  var sel = document.createElement("select");
  sel.dataset.fid = fid;
  if (opts.multiple) { sel.multiple = true; sel.size = Math.min(values.length, 6); }
  if (opts.bad) sel.classList.add("bad");
  values.forEach(function (v) {
    var o = document.createElement("option");
    o.value = v;
    o.textContent = v;
    if (opts.multiple) { if (current.indexOf(v) >= 0) o.selected = true; }
    else if (v === current) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", function (ev) {
    if (opts.multiple) {
      onchange(Array.prototype.filter.call(ev.target.options, function (o) { return o.selected; })
        .map(function (o) { return o.value; }));
    } else { onchange(ev.target.value); }
  });
  return sel;
}

function checkbox(text, checked, fid, onchange) {
  var wrap = document.createElement("label");
  wrap.className = "muted";
  var inp = document.createElement("input");
  inp.type = "checkbox";
  inp.checked = !!checked;
  inp.dataset.fid = fid;
  inp.addEventListener("change", function (ev) { onchange(ev.target.checked); });
  wrap.appendChild(inp);
  wrap.appendChild(document.createTextNode(" " + text));
  return wrap;
}

// Pencil doctrine: a row is READ-ONLY until opened, and an invalid row is
// force-open (and stays open — 'editing' is sticky) until ✓ done is tapped.
// An excluded row never opens: it ships nothing.
function expandedRow(e, err) {
  var open = inc(e) && (e.editing === true || !!err);
  if (open) e.editing = true;
  return open;
}

// One step through the GLOBAL sequence: swap with the nearest INCLUDED
// neighbour, which may sit in another bucket. Excluded rows are stepped over —
// they carry no index, so they are not positions in the sequence.
function moveNeighbour(e, dir) {
  var seq = state.elements;
  var i = seq.indexOf(e);
  if (i < 0) return -1;
  var j = i + dir;
  while (j >= 0 && j < seq.length && !inc(seq[j])) j += dir;
  return (j >= 0 && j < seq.length) ? j : -1;
}

function moveElement(e, dir) {
  var j = moveNeighbour(e, dir);
  if (j < 0) return;
  var i = state.elements.indexOf(e);
  state.elements[i] = state.elements[j];
  state.elements[j] = e;
  STEPPERS = {};        // the arrows did their job — back out of the way
  refresh();            // one snapshot per move
}

// ---- reorder by dragging the row ---------------------------------------
// UI state, page-side: which rows currently show their steppers.
var STEPPERS = {};
var ROW_DRAG = null;   // {uid, y0, active}

// Pure: given the rendered row boxes (DOM order == state order) and a pointer Y,
// which state index should the dragged element land BEFORE? Excluded rows are
// not drop targets, exactly as they are not steps for ↑/↓.
function dropIndexFromBoxes(uid, clientY, boxes) {
  var targets = boxes.filter(function (b) { return b.included && b.uid !== uid; });
  for (var n = 0; n < targets.length; n++) {
    if (clientY < targets[n].mid) return targets[n].idx;
  }
  return boxes.length ? boxes[boxes.length - 1].idx + 1 : 0;
}
window.dropIndexFromBoxes = dropIndexFromBoxes;

function rowBoxes() {
  var out = [];
  var rows = document.querySelectorAll("#elements .row");
  Array.prototype.forEach.call(rows, function (row) {
    var e = elementByUid(row.dataset.uid);
    if (!e) return;
    var r = row.getBoundingClientRect ? row.getBoundingClientRect() : null;
    out.push({ uid: row.dataset.uid, idx: state.elements.indexOf(e), included: inc(e),
               mid: r ? r.top + r.height / 2 : 0 });
  });
  return out;
}

function moveTo(e, insertBefore) {
  var arr = state.elements;
  var i = arr.indexOf(e);
  if (i < 0) return false;
  var j = insertBefore > i ? insertBefore - 1 : insertBefore;
  if (j === i) return false;
  arr.splice(i, 1);
  arr.splice(j, 0, e);
  return true;
}
window.moveRowTo = function (uid, insertBefore) {
  var e = elementByUid(uid);
  if (e && moveTo(e, insertBefore)) refresh();
};

function dropIndicator() {
  var el = document.getElementById("drop-indicator");
  if (!el) {
    el = document.createElement("div");
    el.id = "drop-indicator";
    el.className = "drop-line";
  }
  return el;
}

function clearDropIndicator() {
  var el = document.getElementById("drop-indicator");
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

function beginRowDrag(uid, clientY) {
  ROW_DRAG = { uid: uid, y0: clientY, active: false };
}

function moveRowDrag(clientY) {
  if (!ROW_DRAG) return;
  if (!ROW_DRAG.active) {
    if (Math.abs(clientY - ROW_DRAG.y0) < DRAG_THRESHOLD) return;
    ROW_DRAG.active = true;
    var row = document.querySelector('.row[data-uid="' + ROW_DRAG.uid + '"]');
    if (row) row.classList.add("dragging");
  }
  var boxes = rowBoxes();
  var at = dropIndexFromBoxes(ROW_DRAG.uid, clientY, boxes);
  ROW_DRAG.at = at;
  // Show where it would land: a line between the rows.
  var host = document.getElementById("elements");
  var ind = dropIndicator();
  var before = null;
  for (var n = 0; n < boxes.length; n++) {
    if (boxes[n].idx === at) {
      before = document.querySelector('.row[data-uid="' + boxes[n].uid + '"]');
      break;
    }
  }
  if (before) host.insertBefore(ind, before); else host.appendChild(ind);
}

function endRowDrag() {
  if (!ROW_DRAG) return;
  var drag = ROW_DRAG;
  ROW_DRAG = null;
  clearDropIndicator();
  var row = document.querySelector('.row[data-uid="' + drag.uid + '"]');
  if (row) row.classList.remove("dragging");
  if (!drag.active || drag.at === undefined) return;
  var e = elementByUid(drag.uid);
  if (e && moveTo(e, drag.at)) {
    STEPPERS = {};
    refresh();   // one snapshot per drop
  }
}

function moveButton(e, dir) {
  var b = document.createElement("button");
  b.className = "ghost move";
  b.dataset.fid = (dir < 0 ? "mv-up-" : "mv-dn-") + e.uid;
  b.textContent = dir < 0 ? "↑" : "↓";
  b.title = dir < 0 ? "move one step earlier in the template order (index)"
                    : "move one step later in the template order (index)";
  b.disabled = moveNeighbour(e, dir) < 0;
  b.addEventListener("click", function () { moveElement(e, dir); });
  return b;
}

function rowHead(e, index, expanded) {
  var g = document.createElement("div");
  g.className = "grid";

  // Drag to reorder — pointer events, so it works on touch too.
  if (inc(e)) {
    var handle = document.createElement("span");
    handle.className = "drag";
    handle.dataset.fid = "drag-" + e.uid;
    handle.textContent = "⠿";
    handle.title = "drag to reorder — the index follows the position";
    handle.addEventListener("pointerdown", function (ev) {
      beginRowDrag(e.uid, ev.clientY);
      if (ev.preventDefault) ev.preventDefault();
    });
    g.appendChild(handle);
  }

  var cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "inc";
  cb.checked = inc(e);
  cb.dataset.fid = "inc-" + e.uid;
  cb.title = "include in the template (unticked = left out, nothing is deleted)";
  cb.addEventListener("change", function (ev) { e.included = ev.target.checked; refresh(); });
  g.appendChild(cb);

  var idxBadge = badge(index === undefined ? "excluded" : "#" + index, "b-idx",
    index === undefined ? "excluded rows carry no index"
                        : "click to show the move controls — the index itself is not editable");
  if (index !== undefined) {
    idxBadge.classList.add("idx");
    idxBadge.dataset.fid = "idx-" + e.uid;
    idxBadge.addEventListener("click", function () {
      var on = !STEPPERS[e.uid];
      STEPPERS = {};
      if (on) STEPPERS[e.uid] = true;
      refresh();
    });
  }
  g.appendChild(idxBadge);
  g.appendChild(badge(C.bucketBadges[e.bucket] || e.bucket, "b-" + e.bucket));
  if (e._pageNew) {
    g.appendChild(badge("added here", "b-new"));
    // operator decision: the placement badge IS the trigger — clicking it enters
    // placement mode (or re-places). The old 📍 button is gone; the fid stays.
    var placeBadge = badge(e.bbox ? "placed" : "not placed",
                           e.bbox ? "b-" + e.bucket : "b-idx");
    placeBadge.dataset.fid = "place-" + e.uid;
    if (!IMAGE_SRC) {
      placeBadge.title = "no mockup image on this page";
    } else {
      placeBadge.classList.add("place-badge");
      placeBadge.title = e.bbox
        ? "click to re-place; drag the box to move it"
        : "click to place on the mockup";
      placeBadge.addEventListener("click", function () { startPlacing(e.uid); });
    }
    g.appendChild(placeBadge);
  }

  var code = document.createElement("code");
  // operator decision: no "(no key)" / "(unnamed)" placeholder tags — render
  // nothing when the value is absent (live validation flags the missing key).
  if (e.key) code.textContent = e.key;
  g.appendChild(code);
  if (e.name) g.appendChild(lab(e.name));
  // operator decision: the vision ROLE is never rendered on a row — it is
  // internal vocabulary ("toggle_custom", "cta_button"). It stays in state and
  // still ships in corrections.excluded.

  var ed = document.createElement("button");
  ed.className = "ghost pencil";
  ed.dataset.fid = "ed-" + e.uid;
  ed.textContent = expanded ? "✓ done" : "✎ edit";
  ed.title = expanded ? "collapse (stays open while the row has errors)"
                      : "open the row for editing";
  ed.disabled = !inc(e);
  ed.addEventListener("click", function () { e.editing = !expanded; refresh(); });
  // One container holds every action button, so the cluster stays put whatever
  // is hidden or missing inside it.
  var actions = document.createElement("span");
  actions.className = "row-actions";
  actions.dataset.fid = "actions-cluster-" + e.uid;

  // Only an included row has a position in the sequence to step through. The
  // buttons stay in the DOM (their data-fid contract is stable); CSS hides them
  // until the #N badge is clicked.
  if (inc(e)) {
    actions.appendChild(moveButton(e, -1));
    actions.appendChild(moveButton(e, 1));
  }
  // operator decision: the cluster reads ↑ ↓ → done → remove. Placement left the
  // cluster for good — it lives on the badge; do not reintroduce a place button.
  actions.appendChild(ed);

  // ✕ exists only for rows created on this page: they carry no vision data, so
  // there is nothing to lose. Proposed rows use the checkbox instead.
  if (e._pageNew) {
    var rm = document.createElement("button");
    rm.className = "ghost remove";
    rm.dataset.fid = "rm-" + e.uid;
    rm.textContent = "✕ remove";
    rm.title = "delete this row — available only for rows added on this page "
             + "(proposed elements use the checkbox instead)";
    rm.addEventListener("click", function () {
      state.elements = state.elements.filter(function (x) { return x !== e; });
      refresh();
    });
    actions.appendChild(rm);
  }
  g.appendChild(actions);
  return g;
}

function rowFacts(e) {
  var facts = [];
  if (e.bucket === "buttons") {
    // operator decision: textLimit is not surfaced on the page (dashboard-side)
    facts.push("actions: " + (e.clickActionType.join(", ") || "none"));
    if (needsItems(e)) facts.push("items " + e.requiredItemsCount);
    if (hasCustomAction(e)) facts.push("CTA names: " + (e.customCtaNames || "(none)"));
  } else if (e.bucket === "texts") {
    // operator decision: textLimit is not surfaced on the page (dashboard-side)
    facts.push(e.nullable ? "nullable" : "required");
  } else if (e.bucket === "customs") {
    facts.push(e.kind);
    facts.push("default " + JSON.stringify(coerceDefault(e)));
    if (e.kind === "enumeration") facts.push("values: " + (e.enumValues || "(none)"));
  } else {
    facts.push("image slot");
  }
  facts.push(e.canBeHidden ? "can be hidden" : "always shown");
  if (e.observedText) facts.push("“" + e.observedText + "”");
  // operator decision: no per-row confidence text — the low-confidence signal
  // lives in the build-warnings panel at the top of the page.
  if (!e.bbox) facts.push("no box on the mockup");
  return facts;
}

function customFieldsTable(e) {
  if (!(e.customFields || []).length) return null;
  var t = document.createElement("table");
  t.className = "sub";
  // Built with the DOM API on purpose: an innerHTML string here needs a nested
  // quoted class attribute, which is exactly the escaping trap that breaks the
  // whole <script> when the page template is a plain Python string.
  e.customFields.forEach(function (cf) {
    var tr = document.createElement("tr");
    if (cf.included === false) tr.className = "cf-off";
    var c1 = document.createElement("td");
    var code = document.createElement("code");
    code.textContent = cf.key;
    c1.appendChild(code);
    var c2 = document.createElement("td");
    c2.textContent = cf.kind;
    var c3 = document.createElement("td");
    c3.textContent = cf.name || "";
    var c4 = document.createElement("td");
    c4.className = "muted";
    c4.textContent = cf.defaultValue === undefined || cf.defaultValue === null
      ? "" : String(cf.defaultValue);
    tr.appendChild(c1); tr.appendChild(c2); tr.appendChild(c3); tr.appendChild(c4);
    t.appendChild(tr);
  });
  return t;
}

function rowSummary(e) {
  var g = document.createElement("div");
  g.className = "grid";
  g.appendChild(lab(rowFacts(e).join(" · ")));
  if (e.description) g.appendChild(lab("— " + e.description));
  return g;
}

function rowEditor(e, err, fieldErrors) {
  var wrap = document.createElement("div");

  var g1 = document.createElement("div");
  g1.className = "grid";
  g1.style.marginTop = "0.45rem";
  g1.appendChild(lab("key"));
  g1.appendChild(textInput(e.key, e.uid + "-key", function (v) { e.key = v; refresh(); },
    { placeholder: "header_text", size: 20, bad: !!(err && err.indexOf("Key") >= 0) }));
  g1.appendChild(lab("name"));
  g1.appendChild(textInput(e.name, e.uid + "-name", function (v) { e.name = v; refresh(); },
    { placeholder: "Header", size: 18, bad: !!(err && err.indexOf("Name") >= 0) }));
  // No bucket select by design: re-bucketing is a destructive shape rewrite and
  // it told the corpus nothing. The sanctioned correction is to un-tick the wrong
  // proposal (-> corrections.excluded) and add a row in the right bucket (-> missed).
  g1.appendChild(checkbox("canBeHidden", e.canBeHidden, e.uid + "-hidden", function (v) {
    e.canBeHidden = v; refresh();
  }));
  wrap.appendChild(g1);

  var g2 = document.createElement("div");
  g2.className = "grid";
  g2.style.marginTop = "0.45rem";
  g2.appendChild(lab("description"));
  g2.appendChild(textInput(e.description, e.uid + "-desc", function (v) {
    e.description = v; refresh();
  }, { size: 34 }));

  if (e.bucket === "texts") {
    g2.appendChild(checkbox("nullable", e.nullable, e.uid + "-nullable", function (v) {
      e.nullable = v; refresh();
    }));
  } else if (e.bucket === "customs") {
    g2.appendChild(lab("kind"));
    g2.appendChild(selectInput(C.kinds, e.kind, e.uid + "-kind", function (v) {
      e.kind = v; refresh();
    }));
    g2.appendChild(lab("defaultValue"));
    if (e.kind === "boolean") {
      g2.appendChild(selectInput(["false", "true"],
        String(e.defaultValue) === "true" ? "true" : "false", e.uid + "-default",
        function (v) { e.defaultValue = v; refresh(); }));
    } else {
      g2.appendChild(textInput(e.defaultValue, e.uid + "-default", function (v) {
        e.defaultValue = v; refresh();
      }, { number: e.kind === "numeric", size: 12 }));
    }
    if (e.kind === "enumeration") {
      g2.appendChild(lab("enumValues"));
      g2.appendChild(textInput(e.enumValues, e.uid + "-enum", function (v) {
        e.enumValues = v; refresh();
      }, { placeholder: "a, b, c", size: 18 }));
    }
  }
  wrap.appendChild(g2);

  if (e.bucket === "buttons") {
    wrap.appendChild(actionsBlock(e, err));
    if (hasCustomAction(e)) {
      var gc = editorLine();
      gc.appendChild(lab("customCtaNames"));
      gc.appendChild(textInput(e.customCtaNames, e.uid + "-cta", function (v) {
        e.customCtaNames = v; refresh();
      }, { placeholder: "Info, Rules", size: 18,
           bad: !!(err && err.indexOf("CTA name") >= 0) }));
      wrap.appendChild(gc);
    }
    if (needsItems(e)) {
      var gi = editorLine();
      // Numeric inputs hold the RAW string while being typed and are coerced at
      // export — coercing on every keystroke would snap a cleared field back to
      // the default and make it impossible to retype.
      gi.appendChild(lab("requiredItemsCount"));
      gi.appendChild(textInput(e.requiredItemsCount, e.uid + "-items", function (v) {
        e.requiredItemsCount = v; refresh();
      }, { number: true, size: 4 }));
      wrap.appendChild(gi);
    }
  }
  // operator decision: textLimit is NOT editable on this page, for buttons or
  // texts — operators set limits on the dashboard. The builder's value still
  // ships untouched (see elementOut); it is simply not exposed here.
  wrap.appendChild(customFieldsBlock(e, fieldErrors));
  return wrap;
}

function customFieldRow(e, cf, err) {
  var g = document.createElement("div");
  g.className = "grid cf-row";

  if (cf._pageNew) {
    // Added here, so there is nothing of the builder's to lose.
    var rm = document.createElement("button");
    rm.className = "ghost remove";
    rm.dataset.fid = "cfrm-" + cf._uid;
    rm.textContent = "✕";
    rm.title = "delete this custom field — available only for fields added on this page";
    rm.addEventListener("click", function () {
      e.customFields = e.customFields.filter(function (x) { return x !== cf; });
      refresh();
    });
    g.appendChild(rm);
  } else {
    var inc2 = document.createElement("input");
    inc2.type = "checkbox";
    inc2.className = "inc";
    inc2.checked = cf.included !== false;
    inc2.dataset.fid = "cfinc-" + cf._uid;
    inc2.title = "include this custom field (unticked = left out, nothing is deleted)";
    inc2.addEventListener("change", function (ev) {
      cf.included = ev.target.checked;
      refresh();
    });
    g.appendChild(inc2);
  }

  g.appendChild(lab("key"));
  g.appendChild(textInput(cf.key, cf._uid + "-key", function (v) { cf.key = v; refresh(); },
    { placeholder: "text_color", size: 16, bad: !!(err && err.indexOf("Key") >= 0) }));
  g.appendChild(lab("name"));
  g.appendChild(textInput(cf.name, cf._uid + "-name", function (v) { cf.name = v; refresh(); },
    { placeholder: "Text Color", size: 14 }));
  g.appendChild(lab("kind"));
  // FIELD kinds — 'image' belongs here and NOT on a custom element.
  g.appendChild(selectInput(C.fieldKinds, cf.kind, cf._uid + "-kind", function (v) {
    cf.kind = v; refresh();
  }, { bad: !!(err && err.indexOf("kind") >= 0) }));
  g.appendChild(lab("default"));
  if (cf.kind === "boolean") {
    g.appendChild(selectInput(["false", "true"],
      String(cf.defaultValue) === "true" ? "true" : "false", cf._uid + "-default",
      function (v) { cf.defaultValue = v; refresh(); }));
  } else {
    g.appendChild(textInput(cf.defaultValue, cf._uid + "-default", function (v) {
      cf.defaultValue = v; refresh();
    }, { number: cf.kind === "numeric", size: 10 }));
  }
  if (cf.kind === "enumeration") {
    g.appendChild(lab("enumValues"));
    g.appendChild(textInput(cf.enumValues, cf._uid + "-enum", function (v) {
      cf.enumValues = v; refresh();
    }, { placeholder: "a, b, c", size: 16 }));
  }
  g.appendChild(lab("description"));
  g.appendChild(textInput(cf.description, cf._uid + "-desc", function (v) {
    cf.description = v; refresh();
  }, { size: 18 }));
  g.appendChild(checkbox("nullable", cf.nullable, cf._uid + "-nullable", function (v) {
    cf.nullable = v; refresh();
  }));

  if (err) {
    var e2 = document.createElement("div");
    e2.className = "muted";
    e2.style.color = "#cf222e";
    e2.textContent = err;
    g.appendChild(e2);
  }
  return g;
}

// Every element in every bucket can carry custom fields, so the editor is not
// bucket-specific.
function customFieldsBlock(e, fieldErrors) {
  var wrap = document.createElement("div");
  wrap.className = "cf-block";
  // operator decision: no "custom fields" label, no hint line, no "none on
  // this element." placeholder — the ＋ custom field button alone is the
  // section chrome.
  // Rows stack as block-level entries in their own container; the button is a
  // sibling AFTER that container, never competing with a row for the same line.
  var rows = document.createElement("div");
  rows.className = "cf-rows";
  (e.customFields || []).forEach(function (cf) {
    rows.appendChild(customFieldRow(e, cf, (fieldErrors || {})[cf._uid]));
  });
  wrap.appendChild(rows);

  var add = document.createElement("button");
  // operator request: breathing room above the button — now a CSS rule
  // (.cf-block .cf-add), not an inline style the line box could swallow.
  add.className = "ghost tiny cf-add";
  add.dataset.fid = "cfadd-" + e.uid;
  // operator decision: label reads "＋ custom field", matching the add cluster
  add.textContent = "＋ custom field";
  add.title = "attach a typed field to this element";
  add.addEventListener("click", function () {
    e.customFields.push(normalizeCustomField({}, true));
    refresh();
  });
  wrap.appendChild(add);
  return wrap;
}

function editorLine() {
  var g = document.createElement("div");
  g.className = "grid";
  g.style.marginTop = "0.45rem";
  return g;
}

// clickActionType is the MENU the operator later picks from, so several entries
// are the norm — it has to read as multi-select, not as a one-of dropdown.
// One chip component for every CTA menu on the page — element click actions and
// the feature panel's mission/milestone menus all read the same way.
function chipGroup(opts) {
  var wrap = editorLine();
  wrap.style.display = "block";
  var head = document.createElement("div");
  head.className = "grid";
  var label = lab(opts.label);
  if (opts.title) label.title = opts.title;
  head.appendChild(label);
  wrap.appendChild(head);

  if (opts.caption) {
    var cap = document.createElement("div");
    cap.className = "muted";
    if (opts.captionId) cap.id = opts.captionId;
    cap.textContent = opts.caption;
    wrap.appendChild(cap);
  }

  var chips = document.createElement("div");
  chips.className = "chips" + (opts.selected.length ? "" : (opts.badWhenEmpty ? " bad" : ""));
  chips.dataset.fid = opts.fid;
  if (opts.title) chips.title = opts.title;
  C.clickActions.forEach(function (action) {
    var on = opts.selected.indexOf(action) >= 0;
    var chip = document.createElement("label");
    chip.className = "chip" + (on ? " on" : "");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = on;
    cb.dataset.fid = opts.chipFid(action);
    cb.addEventListener("change", function (ev) { opts.onToggle(action, ev.target.checked); });
    chip.appendChild(cb);
    chip.appendChild(document.createTextNode(action));
    chips.appendChild(chip);
  });
  wrap.appendChild(chips);
  if (opts.emptyHint && !opts.selected.length) {
    var hint = document.createElement("div");
    hint.className = "muted";
    hint.dataset.fid = opts.fid + "-hint";
    hint.textContent = opts.emptyHint;
    wrap.appendChild(hint);
  }
  return wrap;
}

// Rebuilt from the menu each time, so every list follows menu order.
function withAction(list, action, on) {
  var picked = {};
  (list || []).forEach(function (a) { picked[a] = true; });
  if (on) { picked[action] = true; } else { delete picked[action]; }
  return C.clickActions.filter(function (a) { return picked[a]; });
}

function actionsBlock(e, err) {
  return chipGroup({
    label: "click actions",
    caption: "actions the operator can choose from when configuring the in-app — "
           + "select all that apply",
    captionId: "actions-caption-" + e.uid,
    fid: "actions-" + e.uid,
    chipFid: function (a) { return "act-" + e.uid + "-" + a; },
    selected: e.clickActionType,
    badWhenEmpty: true,
    onToggle: function (action, on) {
      e.clickActionType = withAction(e.clickActionType, action, on);
      refresh();
    }
  });
}



function elementRow(e, index, err, expanded, fieldErrors) {
  var row = document.createElement("div");
  row.className = "row b-" + e.bucket + (err ? " invalid" : "") + (inc(e) ? "" : " excluded")
    + (STEPPERS[e.uid] ? " steppers-on" : "");
  row.dataset.uid = e.uid;
  row.addEventListener("mouseenter", function () { highlight(e.uid, true); });
  row.addEventListener("mouseleave", function () { highlight(e.uid, false); });

  row.appendChild(rowHead(e, index, expanded));
  row.appendChild(expanded ? rowEditor(e, err, fieldErrors) : rowSummary(e));

  if (err) {
    var ediv = document.createElement("div");
    ediv.className = "muted";
    ediv.style.color = "#cf222e";
    ediv.textContent = err;
    row.appendChild(ediv);
  }
  if (e.confirm) {
    var cdiv = document.createElement("div");
    cdiv.className = "confirm-note";
    cdiv.innerHTML = "<b>Confirm:</b> " + esc(e.confirm);
    row.appendChild(cdiv);
  }
  if (!expanded) {
    var cft = customFieldsTable(e);
    if (cft) row.appendChild(cft);
  }
  return row;
}

function newElement(bucket) {
  var e = normalizeElement(bucket, {});
  e.bbox = null;
  e.canBeHidden = true;
  e._pageNew = true;   // page-local: gates the ✕, never exported
  e.editing = true;    // a fresh row opens ready to type, like merge-plan's ＋
  return e;
}

function elementsSummary() {
  // One line replaces the per-bucket section headers.
  var totalInc = state.elements.filter(inc).length;
  var parts = C.buckets.map(function (b) {
    var mine = state.elements.filter(function (e) { return e.bucket === b; });
    var kept = mine.filter(inc).length;
    var label = C.bucketBadges[b] + (kept === 1 ? "" : "s");
    return kept + (kept === mine.length ? "" : " of " + mine.length) + " " + label;
  });
  var head = totalInc === state.elements.length
    ? totalInc + " element" + (totalInc === 1 ? "" : "s")
    : totalInc + " of " + state.elements.length + " elements";
  return head + " — " + parts.join(" · ");
}

function renderElementsHead() {
  var head = document.getElementById("elements-head");
  head.innerHTML = "";

  var line = document.createElement("div");
  line.className = "grid";
  var h = document.createElement("h2");
  h.textContent = "Elements";
  h.style.margin = "0";
  line.appendChild(h);
  var sum = lab(elementsSummary());
  sum.id = "elements-summary";
  line.appendChild(sum);
  head.appendChild(line);

  // Per-bucket sections are gone, so the add controls live here — on their own
  // line under the summary. The data-fid contract (add-<bucket>) is unchanged.
  var cluster = document.createElement("div");
  cluster.className = "add-cluster";
  cluster.id = "elements-add";
  C.buckets.forEach(function (b) {
    var add = document.createElement("button");
    add.className = "ghost tiny add-el b-" + b;   // bucket-coloured, see CSS
    add.dataset.fid = "add-" + b;
    add.textContent = "＋ " + C.bucketBadges[b];
    add.title = "add a " + C.bucketBadges[b] + " at the end of the template order";
    add.addEventListener("click", function () { state.elements.push(newElement(b)); refresh(); });
    cluster.appendChild(add);
  });
  head.appendChild(cluster);
}

// ONE flat list in global index order: ↑/↓ visibly relocate the row, which is
// the whole point of the badge number. Bucket identity rides on each row (colour
// accent + bucket badge) instead of on a section header.
function renderElements(idx, rowErrors, fieldErrors) {
  var host = document.getElementById("elements");
  var active = document.activeElement;
  var fid = active && active.dataset ? active.dataset.fid : null;
  var selStart = fid && "selectionStart" in active ? active.selectionStart : null;
  var selEnd = fid && "selectionEnd" in active ? active.selectionEnd : null;
  host.innerHTML = "";
  var openCount = 0;

  renderElementsHead();
  state.elements.forEach(function (e) {
    var expanded = expandedRow(e, rowErrors[e.uid]);
    if (expanded) openCount += 1;
    host.appendChild(elementRow(e, idx[e.uid], rowErrors[e.uid], expanded, fieldErrors));
  });
  if (!state.elements.length) host.appendChild(lab("No elements yet."));

  if (fid) {
    var el = host.querySelector('[data-fid="' + fid + '"]');
    if (el) {
      el.focus();
      if (selStart !== null && "setSelectionRange" in el) {
        try { el.setSelectionRange(selStart, selEnd); } catch (err2) { /* number inputs */ }
      }
    }
  }
  return openCount;
}

// ---- feature panel ------------------------------------------------------
// Feature blocks are stashed as the developer flips the selector, so a detour
// through 'standard' (which must serialise features: {}) does not throw away
// the block the builder produced.
var featuresStash = state.features && typeof state.features === "object" ? clone(state.features) : {};

function syncFeaturePanel(seed) {
  var t = state.featureType;
  if (seed === false) { fillFeatureInputs(); return; }
  if (state.features && typeof state.features === "object") {
    Object.keys(state.features).forEach(function (k) { featuresStash[k] = clone(state.features[k]); });
  }
  if (t === "standard") {
    state.features = {};
    fillFeatureInputs();
    return;
  }
  state.features = {};
  state.features[t] = featuresStash[t]
    ? clone(featuresStash[t])
    : clone(t === "mission" ? C.missionDefaults : C.milestoneDefaults);
  fillFeatureInputs();
}

// Dashboard wording for the feature-panel CTA menus.
var CTA_TITLES = {
  completionCta: "Define which CTA(s) are available once the mission is completed. "
               + "Most common: Collect Resource, Internal Link, or Close.",
  mainActionTypes: "Set up the call-to-action options available to the user during their "
                 + "progression towards milestones",
  milestonesActionTypes: "Set up the call-to-action options available to the user upon "
                       + "reaching a milestone"
};
var CTA_LABELS = {
  completionCta: "Mission Completion CTA",
  mainActionTypes: "Active Progress CTA",
  milestonesActionTypes: "Milestone Completion CTA"
};
// operator refinement: the milestone menus are ALWAYS editable — a developer who
// knows the CTAs is not "inventing" them. Empty simply means the dashboard picks.
var CTA_EMPTY_HINT = "nothing selected — you'll choose on the dashboard";

// operator decision: whatever is SENT is visible and editable here. A menu the
// builder did not derive is NOT offered for editing — the page never invents one.
function renderFeatureChips(hostId, keys, badWhenEmpty, emptyHint) {
  var host = document.getElementById(hostId);
  if (!host) return;
  host.innerHTML = "";
  var t = state.featureType;
  var f = (state.features || {})[t] || {};
  keys.forEach(function (key) {
    host.appendChild(chipGroup({
      label: CTA_LABELS[key],
      title: CTA_TITLES[key],
      fid: "fp-" + key,
      chipFid: function (a) { return "fp-cta-" + key + "-" + a; },
      selected: f[key] || [],
      badWhenEmpty: !!badWhenEmpty,
      emptyHint: emptyHint,
      onToggle: function (action, on) {
        var block = (state.features || {})[state.featureType];
        if (!block) return;
        block[key] = withAction(block[key], action, on);
        fillFeatureInputs();
        refresh();
      }
    }));
  });
}

// DOM-only: show the right panel and mirror whatever state currently holds.
// A restore must never re-seed from the stash, or an undo would clobber the
// very block it is restoring.
function fillFeatureInputs() {
  var t = state.featureType;
  var feat = document.getElementById("tpl-feature");
  if (feat) feat.title = FEATURE_HINTS[t] || "";
  document.getElementById("fp-mission").hidden = t !== "mission";
  document.getElementById("fp-milestone").hidden = t !== "milestone";
  var note = document.getElementById("fp-note");
  if (t === "standard") {
    // operator decision: no note text for standard — keep the panel silent
    note.textContent = "";
    return;
  }
  var f = (state.features || {})[t] || {};
  if (t === "mission") {
    ["maxPlacements", "maxSetsCount", "minPlacements", "minSetsCount"].forEach(function (k) {
      document.getElementById("fp-" + k).value = f[k] === undefined ? "" : f[k];
    });
    document.getElementById("fp-missionLayout").value = f.missionLayout || "parallel";
    var pb = f.progressBar || {};
    var shown = pb.display && pb.display !== "dont_show_at_all";
    document.getElementById("fp-progressBar").value = shown ? "show" : "hide";
    document.getElementById("fp-maxMilestones-wrap").hidden = !shown;
    document.getElementById("fp-maxMilestones").value =
      pb.maxMilestones === undefined ? "" : pb.maxMilestones;
    // operator decision: the panel is a LIGHT version of the dashboard — only the
    // knobs a mockup can actually show. CTAs and scoped custom fields are
    // dashboard-only and pass through as built.
    note.textContent = "mission — Active Progress CTA and scoped custom fields are configured on the dashboard.";
    renderFeatureChips("fp-mission-ctas", ["completionCta"], true);
  } else {
    document.getElementById("fp-limit").value = f.limit === undefined ? "" : f.limit;
    // Both menus are always offered; an empty one is valid and simply ships no
    // key (see featuresOut) — the dashboard then demands the choice.
    renderFeatureChips("fp-milestone-ctas",
                       ["mainActionTypes", "milestonesActionTypes"], false, CTA_EMPTY_HINT);
    // operator decision: no note — the chips themselves say everything now
    note.textContent = "";
  }
}

// ---- undo / redo --------------------------------------------------------
// Re-renders destroy the browser's native per-input undo stack, so the page
// keeps a whole-state history: one snapshot per render (char-level), cap 200.
var UNDO = [], REDO = [], RESTORING = false;

function restoreSnap(snap) {
  var d = JSON.parse(snap);
  Object.keys(d).forEach(function (k) { state[k] = d[k]; });
  RESTORING = true;
  syncHeaderInputs();
  refresh();
  RESTORING = false;
}

document.addEventListener("keydown", function (ev) {
  var k = String(ev.key || "").toLowerCase();
  if (k === "escape" && PLACING) { cancelPlacing(); return; }
  if (!(ev.metaKey || ev.ctrlKey) || ev.altKey) return;
  if (k === "z" && !ev.shiftKey) {
    ev.preventDefault();
    if (UNDO.length > 1) { REDO.push(UNDO.pop()); restoreSnap(UNDO[UNDO.length - 1]); }
  } else if ((k === "z" && ev.shiftKey) || k === "y") {
    ev.preventDefault();
    if (REDO.length) { var snap = REDO.pop(); UNDO.push(snap); restoreSnap(snap); }
  }
});
window.undo = function () {
  if (UNDO.length > 1) { REDO.push(UNDO.pop()); restoreSnap(UNDO[UNDO.length - 1]); }
};
window.redo = function () {
  if (REDO.length) { var snap = REDO.pop(); UNDO.push(snap); restoreSnap(snap); }
};

// The header inputs live outside the re-rendered list, so an undo has to push
// the restored state back into them by hand.
function syncHeaderInputs() {
  document.getElementById("tpl-name").value = state.name;
  document.getElementById("tpl-key").value = state.key;
  document.getElementById("tpl-desc").value = state.description;
  document.getElementById("tpl-feature").value = state.featureType;
  syncFeaturePanel(false);
}

// ---- template header: view / edit ---------------------------------------
// Mode is UI, not data: it stays out of the undo snapshots (the field values
// inside it are already part of state and ride the stack as usual).
var HEADER_EDITING = false;

function featureSummary() {
  var t = state.featureType;
  var label = FEATURE_LABELS[t] || t;
  var f = (state.features || {})[t] || {};
  if (t === "milestone") {
    var mbits = [];
    // operator decision: UI says "max milestones", wire field stays `limit`
    if (f.limit !== undefined && f.limit !== "") mbits.push("max " + f.limit);
    var hasMenus = ["mainActionTypes", "milestonesActionTypes"].some(function (k) {
      return (f[k] || []).length;
    });
    if (!hasMenus) mbits.push("CTA on dashboard");
    return mbits.length ? label + " · " + mbits.join(" · ") : label;
  }
  if (t === "mission") {
    var bits = [];
    var minP = f.minPlacements, maxP = f.maxPlacements;
    if (minP !== undefined && minP !== "" && maxP !== undefined && maxP !== "") {
      bits.push(minP + "–" + maxP + " slots");
    } else if (maxP !== undefined && maxP !== "") {
      bits.push(maxP + " slots");
    }
    if (f.maxSetsCount !== undefined && f.maxSetsCount !== "" && String(f.maxSetsCount) !== "1") {
      bits.push(f.maxSetsCount + " sets");
    }
    // layout only when it deviates from the parallel default
    if (f.missionLayout === "sequential") bits.push("sequential");
    var pbar = f.progressBar || {};
    if (pbar.display && pbar.display !== "dont_show_at_all") {
      bits.push(pbar.maxMilestones ? "bar ≤" + pbar.maxMilestones : "bar");
    }
    return bits.length ? label + " · " + bits.join(" · ") : label;
  }
  return label;
}

function renderTemplateHeader(v) {
  // Sticky, like an invalid row: a template-level error re-opens the card and
  // keeps it open until the values are fixed.
  if ((v.templateErrors || []).length) HEADER_EDITING = true;
  var open = HEADER_EDITING;

  var head = document.getElementById("tpl-head");
  head.innerHTML = "";
  var h = document.createElement("h2");
  h.textContent = "Template";
  h.style.margin = "0";
  head.appendChild(h);

  if (!open) {
    var name = document.createElement("span");
    name.className = "tpl-name";
    name.id = "tpl-view-name";
    name.textContent = state.name;
    head.appendChild(name);

    var code = document.createElement("code");
    code.id = "tpl-view-key";
    code.textContent = state.key;
    head.appendChild(code);

    var b = badge(featureSummary(), "b-idx");
    b.id = "tpl-view-feature";
    head.appendChild(b);

    // operator decision territory: an empty description renders NOTHING —
    // no placeholder, no dash.
    if (String(state.description).trim()) {
      var d2 = lab(state.description);
      d2.id = "tpl-view-desc";
      head.appendChild(d2);
    }
  }

  var ed = document.createElement("button");
  ed.className = "ghost pencil";
  ed.id = "tpl-pencil";
  ed.dataset.fid = "tpl-ed";
  ed.textContent = open ? "✓ done" : "✎ edit";
  ed.title = open ? "collapse (stays open while the template has errors)"
                  : "open the template header for editing";
  ed.addEventListener("click", function () {
    HEADER_EDITING = !open;
    refresh();
  });
  var actions = document.createElement("span");
  actions.className = "row-actions";
  actions.dataset.fid = "actions-cluster-tpl";
  actions.appendChild(ed);
  head.appendChild(actions);

  document.getElementById("tpl-edit").hidden = !open;
  return open;
}

// ---- footer counter -----------------------------------------------------
function renderCounter(v, openRows) {
  // Unticked rows are out of the template — they never count as work.
  var parts = C.buckets.map(function (b) {
    return state.elements.filter(function (e) { return e.bucket === b && inc(e); }).length
      + " " + C.bucketLabels[b].toLowerCase();
  });
  var txt = "to register: " + parts.join(" · ");
  if (v.errors.length) {
    txt += "  ·  " + v.errors.length + " validation error(s) — fix to enable export";
  }
  if (openRows > 0) {
    txt += "  ·  finish editing " + openRows + " row(s) — tap ✓ done to confirm";
  }
  document.getElementById("counter").textContent = txt;
}

// ---- refresh ------------------------------------------------------------
function refresh() {
  if (!RESTORING && !DRAGGING) {
    var snap = JSON.stringify(state);
    if (!UNDO.length || UNDO[UNDO.length - 1] !== snap) {
      UNDO.push(snap);
      if (UNDO.length > 200) UNDO.shift();
      REDO.length = 0;
    }
  }
  var v = validate();
  var idx = indexMap();
  var openRows = renderElements(idx, v.rowErrors, v.fieldErrors);
  if (renderTemplateHeader(v)) openRows += 1;   // an open header blocks export too
  renderOverlay(idx);

  var host = document.getElementById("live-errors");
  host.innerHTML = "";
  var panel = listPanel("This payload is INVALID &mdash; fix before registering", v.errors, "bad");
  if (panel) {
    panel.querySelector("h2").innerHTML =
      "This payload is INVALID (" + v.errors.length + ") &mdash; fix before registering";
    host.appendChild(panel);
  }
  var wpanel = listPanel("Worth a look", v.warnings, "warn");
  if (wpanel) host.appendChild(wpanel);

  document.getElementById("tpl-key").classList.toggle("bad", !TPL_KEY_RE.test(String(state.key).trim()));
  document.getElementById("tpl-name").classList.toggle("bad", !String(state.name).trim());

  // Hard gate: an invalid payload must never become a hand-back, and an open
  // editor is an unfinished edit (✓ done is the completeness signal — a
  // half-typed key is often perfectly valid, so validity alone can't see it).
  // The <pre> preview stays visible either way.
  var blocked = v.errors.length > 0 || openRows > 0;
  document.getElementById("download").disabled = blocked;
  document.getElementById("copy").disabled = blocked;
  renderCounter(v, openRows);

  var st = document.getElementById("status");
  if (v.errors.length) {
    st.className = "bad";
    st.textContent = v.errors.length + " problem(s) — fix to enable export";
  } else if (!v.count) {
    st.className = "warn";
    st.textContent = "No elements — an empty template is almost certainly wrong";
  } else if (v.warnings.length) {
    st.className = "warn";
    st.textContent = v.count + " element(s), " + v.warnings.length + " warning(s)";
  } else {
    st.className = "ok";
    st.textContent = v.count + " element(s) ready";
  }
  document.getElementById("preview").textContent = exportJson();
}

// ---- wiring -------------------------------------------------------------
(function init() {
  var si = REPORT.source_image || {};
  document.getElementById("meta").innerHTML =
    "Built from <code>" + esc(si.path || "(unknown image)") + "</code>"
    + (si.width ? " (" + esc(si.width) + "&times;" + esc(si.height) + ")" : "")
    + " &middot; " + esc(REPORT.element_count == null ? "?" : REPORT.element_count) + " element(s)"
    + " &middot; page generated " + esc(DATA.generated_at || "")
    + " &middot; feature type <code>" + esc(REPORT.feature_type || state.featureType) + "</code>"
    + (state.hasGameId ? " &middot; game <code>" + esc(state.gameId) + "</code>" : "");

  var img = document.getElementById("mockup");
  if (IMAGE_SRC) {
    img.src = IMAGE_SRC;
  } else {
    document.getElementById("cols").classList.add("no-image");
    document.getElementById("mockup-col").style.display = "none";
  }

  var feat = document.getElementById("tpl-feature");
  C.featureTypes.forEach(function (t) {
    var o = document.createElement("option");
    o.value = t; o.textContent = FEATURE_LABELS[t] || t;
    if (FEATURE_HINTS[t]) o.title = FEATURE_HINTS[t];
    if (t === state.featureType) o.selected = true;
    feat.appendChild(o);
  });
  feat.addEventListener("change", function (ev) {
    state.featureType = ev.target.value;
    syncFeaturePanel();
    refresh();
  });

  var nameEl = document.getElementById("tpl-name");
  var keyEl = document.getElementById("tpl-key");
  var descEl = document.getElementById("tpl-desc");
  nameEl.value = state.name; keyEl.value = state.key; descEl.value = state.description;
  nameEl.dataset.fid = "tpl-name"; keyEl.dataset.fid = "tpl-key"; descEl.dataset.fid = "tpl-desc";
  nameEl.addEventListener("input", function (ev) { state.name = ev.target.value; refresh(); });
  keyEl.addEventListener("input", function (ev) { state.key = ev.target.value; refresh(); });
  descEl.addEventListener("input", function (ev) { state.description = ev.target.value; refresh(); });

  ["maxPlacements", "maxSetsCount", "minPlacements", "minSetsCount"].forEach(function (k) {
    document.getElementById("fp-" + k).addEventListener("input", function (ev) {
      if (!state.features || !state.features.mission) return;
      state.features.mission[k] = ev.target.value;
      refresh();
    });
  });
  var layoutSel = document.getElementById("fp-missionLayout");
  ["parallel", "sequential"].forEach(function (v) {
    var o = document.createElement("option");
    o.value = v; o.textContent = v;
    layoutSel.appendChild(o);
  });
  layoutSel.addEventListener("change", function (ev) {
    if (!state.features || !state.features.mission) return;
    state.features.mission.missionLayout = ev.target.value;
    refresh();
  });

  var barSel = document.getElementById("fp-progressBar");
  [["show", "show"], ["hide", "don't show"]].forEach(function (pair) {
    var o = document.createElement("option");
    o.value = pair[0]; o.textContent = pair[1];
    barSel.appendChild(o);
  });
  barSel.addEventListener("change", function (ev) {
    if (!state.features || !state.features.mission) return;
    // The two shapes are fixed by the live contract: hiding the bar clears the
    // completion CTA list, showing it restores the collect_resource CTA.
    var keep = state.features.mission.progressBar || {};
    state.features.mission.progressBar = ev.target.value === "show"
      ? { display: "show_for_all_sets_combined", completionBarCta: ["collect_resource"] }
      : { display: "dont_show_at_all", completionBarCta: [] };
    // The cap survives an off/on cycle in page state; featuresOut() strips it
    // from the hidden shape so the exported contract stays exact.
    if (keep.maxMilestones !== undefined && keep.maxMilestones !== "") {
      state.features.mission.progressBar.maxMilestones = keep.maxMilestones;
    }
    syncFeaturePanel(false);
    refresh();
  });

  document.getElementById("fp-maxMilestones").addEventListener("input", function (ev) {
    if (!state.features || !state.features.mission) return;
    var pb = state.features.mission.progressBar;
    if (!pb || pb.display === "dont_show_at_all") return;
    pb.maxMilestones = ev.target.value;
    refresh();
  });

  document.getElementById("fp-limit").addEventListener("input", function (ev) {
    if (!state.features || !state.features.milestone) return;
    state.features.milestone.limit = ev.target.value;
    refresh();
  });

  document.getElementById("download").addEventListener("click", function () {
    if (document.getElementById("download").disabled) return;
    var blob = new Blob([exportJson()], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    // Timestamped so a stale file from an earlier run can't be handed back by mistake.
    var t = new Date();
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    var stamp = t.getFullYear() + pad(t.getMonth() + 1) + pad(t.getDate()) + "-"
      + pad(t.getHours()) + pad(t.getMinutes()) + pad(t.getSeconds());
    a.download = "kinoa-inapp-template-" + (String(state.key).trim() || "template")
      + "-" + stamp + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    flash("Downloaded — hand the file path back to the skill");
  });

  document.getElementById("copy").addEventListener("click", function () {
    var text = exportJson();
    function done() { flash("Copied — paste it into the chat"); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else { fallback(); }
    function fallback() {
      // file:// often blocks the async clipboard API.
      var ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (e) { /* user selects the <pre> instead */ }
      ta.remove();
      done();
    }
  });

  var stage = document.getElementById("stage");
  if (stage) {
    stage.addEventListener("click", function (ev) {
      if (!PLACING) return;
      placeAt(PLACING, ev.clientX, ev.clientY);
    });
  }
  document.addEventListener("pointermove", function (ev) {
    moveDrag(ev.clientX, ev.clientY);
    moveRowDrag(ev.clientY);
  });
  document.addEventListener("pointerup", function () { endDrag(); endRowDrag(); });

  // Clicking away puts the steppers back out of sight.
  document.addEventListener("click", function (ev) {
    if (!Object.keys(STEPPERS).length) return;
    var t = ev.target;
    if (t && t.closest && (t.closest('[data-fid^="idx-"]') || t.closest("button.move"))) return;
    STEPPERS = {};
    refresh();
  });

  renderBuildNotes();
  renderClientRendered();
  syncFeaturePanel();
  refresh();
})();

function flash(msg) {
  var el = document.getElementById("flash");
  el.textContent = msg;
  setTimeout(function () { el.textContent = ""; }, 4000);
}
</script>
</body>
</html>
"""


def render(payload: dict[str, Any], image_data_uri: str | None = None,
           generated_at: str | None = None,
           image_fingerprint: dict[str, Any] | None = None) -> str:
    """Render the confirmation page for one `inapp_template_build build` result."""
    data = {
        # Baked at page-build time and echoed into every hand-back as
        # page_generated_at — that is how a stale file gets spotted.
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Fingerprint only — the corrections feedback must be joinable to the
        # mockup without ever carrying the mockup.
        "image_fingerprint": image_fingerprint,
        "payload": payload.get("payload") or {},
        "report": payload.get("report") or {},
        "validation": payload.get("validation") or {},
    }
    consts = {
        "clickActions": CLICK_ACTIONS,
        "itemBearing": ITEM_BEARING_ACTIONS,
        "kinds": KINDS,
        "fieldKinds": FIELD_KINDS,
        "featureTypes": FEATURE_TYPES,
        "buckets": BUCKETS,
        "bucketLabels": BUCKET_LABELS,
        "bucketBadges": BUCKET_BADGES,
        "bucketColors": {"images": "#0969da", "buttons": "#8250df",
                         "texts": "#bc4c00", "customs": "#1b7c83"},
        "elementKeyRe": ELEMENT_KEY_RE,
        "templateKeyRe": TEMPLATE_KEY_RE,
        "templateDescriptionMax": TEMPLATE_DESCRIPTION_MAX,
        "missionDefaults": MISSION_DEFAULTS,
        "milestoneDefaults": MILESTONE_DEFAULTS,
    }
    # "</" would close the <script> early — the standard escape for JSON in HTML.
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    consts_json = json.dumps(consts, ensure_ascii=False).replace("</", "<\\/")
    image_json = json.dumps(image_data_uri or "")

    html = PAGE.replace("__KINOA_CSS__", CSS)
    html = html.replace("__KINOA_DATA__", data_json)
    html = html.replace("__KINOA_CONSTS__", consts_json)
    html = html.replace("__KINOA_IMAGE__", image_json)
    return html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", required=True,
                        help="Path to the JSON printed by `inapp_template_build.py build`, or '-' for stdin.")
    parser.add_argument("--image", help="Mockup to embed as a data: URI. "
                                        "Defaults to report.source_image.path when readable.")
    parser.add_argument("--out", help="Path to write the HTML page "
                                      "(default: inapp-template-confirm.html next to --build).")
    parser.add_argument("--no-open", action="store_true",
                        help="Suppress auto-opening the page in the default browser (default: open).")
    args = parser.parse_args(argv)

    build_path = None if args.build == "-" else args.build
    try:
        if build_path is None:
            raw = sys.stdin.read()
        else:
            with open(build_path, encoding="utf-8") as fh:
                raw = fh.read()
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "unreadable_build", "detail": str(exc)}))
        return 2
    try:
        build = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": "invalid_json", "detail": str(exc)}))
        return 2

    if not isinstance(build, dict) or not isinstance(build.get("payload"), dict):
        print(json.dumps({"ok": False, "error": "missing_payload",
                          "hint": "Pass the full object printed by `inapp_template_build.py build` "
                                  "(it carries payload + report + validation)."}))
        return 2

    if args.image and not os.path.isfile(args.image):
        print(json.dumps({"ok": False, "error": "image_not_found", "image": args.image}))
        return 2

    data_uri, image_path, fingerprint = resolve_image(build, args.image, build_path)
    if args.image and not data_uri:
        print(json.dumps({"ok": False, "error": "unsupported_image",
                          "image": os.path.abspath(args.image),
                          "hint": "Expected png, jpeg, gif or webp (detected from the magic bytes)."}))
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(build_path)) if build_path else os.getcwd(),
        "inapp-template-confirm.html")
    html_doc = render(build, data_uri, generated_at=stamp, image_fingerprint=fingerprint)
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html_doc)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "unwritable_output", "detail": str(exc)}))
        return 2

    abs_path = os.path.abspath(out)
    opened = False
    if not args.no_open:
        try:
            # as_uri() percent-encodes spaces & co — a raw f"file://{path}" breaks
            # for checkouts under directories like "My Games".
            opened = webbrowser.open(pathlib.Path(abs_path).as_uri())
        except Exception:
            opened = False

    print(json.dumps({
        "ok": True,
        "output": abs_path,
        "page_generated_at": stamp,
        "bytes": len(html_doc),
        "image_embedded": bool(data_uri),
        "image_source": image_path,
        "image_sha256": (fingerprint or {}).get("sha256"),
        "element_count": (build.get("report") or {}).get("element_count"),
        "build_valid": bool((build.get("validation") or {}).get("ok")),
        "opened_in_browser": opened,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
