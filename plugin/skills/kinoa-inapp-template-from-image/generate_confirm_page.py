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

What comes out is ONLY the template create body — name, key, description,
gameId (when the build stamped one), images/buttons/texts/customs, featureType,
features (`{}` for a standard template) and tagsIds. The report, the validation block, the bboxes and the build trace stay
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
import json
import os
import pathlib
import sys
import webbrowser
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
BUCKET_LABELS = {
    "images": "Images",
    "buttons": "Buttons",
    "texts": "Texts",
    "customs": "Custom fields",
}
DEFAULT_IMAGE_SIZE = {"width": 10000, "height": 10000, "maxSize": 16000}
DEFAULT_BUTTON_BG = {"width": 10000, "height": 10000, "maxSize": 10000}
DEFAULT_TEXT_LIMIT = 255

ELEMENT_KEY_RE = "^[a-z][a-z0-9_]*$"
TEMPLATE_KEY_RE = "^[a-zA-Z][a-zA-Z0-9_]*$"

# Seeds used when the developer switches featureType to a type the build did
# not produce. Mirrors _mission_feature({}) / _milestone_feature({}).
MISSION_DEFAULTS = {
    "key": "missions",
    "name": "Missions",
    "description": "",
    "progressBar": {
        "display": "show_for_all_sets_combined",
        "completionBarCta": ["collect_resource"],
    },
    "customFields": [],
    "completionCta": ["close", "collect_resource", "billing", "web_link", "deep_link", "show_ad"],
    "maxPlacements": 3,
    "maxSetsCount": 1,
    "minPlacements": 1,
    "minSetsCount": 1,
    "activeProgressCta": ["close", "web_link", "deep_link", "show_ad"],
}
MILESTONE_DEFAULTS = {
    "key": "main_progressbar",
    "name": "Main Progressbar",
    "limit": 3,
    "description": "",
    "mainActionTypes": list(CLICK_ACTIONS),
    "milestonesActionTypes": list(CLICK_ACTIONS),
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


def image_data_uri(path: str) -> str | None:
    """Read an image and return it as a data: URI, or None if unusable."""
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        return None
    mime = _sniff_mime(blob[:16])
    if not mime:
        return None
    return "data:" + mime + ";base64," + base64.b64encode(blob).decode("ascii")


def resolve_image(build: dict[str, Any], image_arg: str | None, build_path: str | None) -> tuple[str | None, str | None]:
    """Return (data_uri, resolved_path). Both None when there is no image."""
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
    for cand in candidates:
        if not os.path.isfile(cand):
            continue
        uri = image_data_uri(cand)
        if uri:
            return uri, os.path.abspath(cand)
    return None, None


CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1500px; margin: 2rem auto; padding: 0 1.5rem;
  color: #1f2328; line-height: 1.5;
}
h1 { margin-bottom: 0.25rem; font-size: 1.5rem; }
h2 { font-size: 1.05rem; margin: 0 0 0.5rem; }
h3 { font-size: 0.95rem; margin: 0 0 0.4rem; }
.meta { color: #57606a; font-size: 0.9rem; margin-bottom: 1rem; }
.meta code { background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 4px; }
.intro { background: #ddf4ff; border: 1px solid #54aeff; border-left: 4px solid #0969da;
  border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1rem; font-size: 0.92rem; }
.intro ul { margin: 0.4rem 0 0 1.1rem; padding: 0; }

.toolbar { position: sticky; top: 0; z-index: 20; background: #ffffffee; backdrop-filter: blur(4px);
  display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap;
  padding: 0.75rem 0; margin-bottom: 1rem; border-bottom: 1px solid #d0d7de; }
button { font: inherit; cursor: pointer; border-radius: 6px; border: 1px solid #d0d7de;
  background: #f6f8fa; padding: 0.4rem 0.8rem; }
button:hover { background: #eaeef2; }
button.primary { background: #1f883d; border-color: #1a7f37; color: #fff; }
button.primary:hover { background: #1a7f37; }
button.ghost { background: transparent; }
button.danger { color: #cf222e; border-color: #ffcecb; }
button.danger:hover { background: #ffebe9; }
button.tiny { padding: 0.15rem 0.45rem; font-size: 0.8rem; }
.spacer { flex: 1; }
#status { font-size: 0.88rem; padding: 0.3rem 0.6rem; border-radius: 6px; }
#status.ok { background: #dafbe1; color: #116329; }
#status.warn { background: #fff8c5; color: #7d4e00; }
#status.bad { background: #ffebe9; color: #82071e; }

.panel { border: 1px solid #d0d7de; border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 1rem; }
.panel.bad { border-color: #ff8182; background: #fff8f8; border-left: 4px solid #cf222e; }
.panel.warn { border-color: #d4a72c; background: #fffdf0; border-left: 4px solid #bf8700; }
.panel ul { margin: 0.3rem 0 0 1.1rem; padding: 0; font-size: 0.88rem; }
.panel pre { background: #f6f8fa; border-radius: 6px; padding: 0.5rem; overflow-x: auto;
  font-size: 0.78rem; margin: 0.3rem 0 0; }
.mut { color: #57606a; font-size: 0.82rem; }

label { display: block; font-size: 0.78rem; color: #57606a; margin-bottom: 0.15rem; }
input[type=text], input[type=number], textarea, select { font: inherit; width: 100%;
  padding: 0.3rem 0.45rem; border: 1px solid #d0d7de; border-radius: 6px; background: #fff; }
select[multiple] { height: auto; min-height: 5.5rem; }
input.bad, select.bad { border-color: #cf222e; background: #fff5f5; }
.err { color: #cf222e; font-size: 0.78rem; margin-top: 0.2rem; }

.head-grid { display: grid; grid-template-columns: 2fr 1.4fr 1fr; gap: 0.6rem; }
.head-grid .wide { grid-column: 1 / -1; }
.fpanel { margin-top: 0.7rem; padding-top: 0.7rem; border-top: 1px dashed #d0d7de;
  display: grid; grid-template-columns: repeat(4, minmax(90px, 1fr)); gap: 0.6rem; }
.fpanel[hidden] { display: none; }

.cols { display: grid; grid-template-columns: minmax(300px, 34%) 1fr; gap: 1.25rem; align-items: start; }
.cols.no-image { grid-template-columns: 1fr; }
@media (max-width: 980px) { .cols { grid-template-columns: 1fr; } }
.mockup-col { position: sticky; top: 4.5rem; }
.stage { position: relative; display: block; border: 1px solid #d0d7de; border-radius: 8px;
  overflow: hidden; background: #f6f8fa; }
.stage img { display: block; width: 100%; height: auto; }
#overlay { position: absolute; inset: 0; }
.box { position: absolute; border: 2px solid #0969da; border-radius: 3px; cursor: pointer; }
.box .tag { position: absolute; top: -0.05rem; left: -0.05rem; transform: translateY(-100%);
  font-size: 0.62rem; line-height: 1.25; padding: 0 0.25rem; border-radius: 3px;
  color: #fff; background: #0969da; white-space: nowrap; }
.box.b-images { border-color: #0969da; } .box.b-images .tag { background: #0969da; }
.box.b-buttons { border-color: #8250df; } .box.b-buttons .tag { background: #8250df; }
.box.b-texts { border-color: #bc4c00; } .box.b-texts .tag { background: #bc4c00; }
.box.b-customs { border-color: #1b7c83; } .box.b-customs .tag { background: #1b7c83; }
.box.client { border-style: dashed; border-color: #8c959f; opacity: 0.75; cursor: default; }
.box.client .tag { background: #8c959f; }
.box.hl { box-shadow: 0 0 0 3px #ffd33d; z-index: 5; }
.legend { font-size: 0.78rem; color: #57606a; margin-top: 0.5rem; display: flex;
  flex-wrap: wrap; gap: 0.5rem 0.9rem; }
.legend i { width: 0.7rem; height: 0.7rem; display: inline-block; border-radius: 2px;
  margin-right: 0.25rem; vertical-align: -1px; }
.cr-list { font-size: 0.8rem; color: #57606a; margin-top: 0.6rem; }
.cr-list li { margin-bottom: 0.2rem; }

.bucket { border: 1px solid #d0d7de; border-radius: 10px; padding: 0.8rem 0.9rem; margin-bottom: 1rem; }
.bucket > .bhead { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
.bucket > .bhead .dot { width: 0.7rem; height: 0.7rem; border-radius: 2px; display: inline-block; }
.row { border: 1px solid #eaeef2; border-left: 4px solid #d0d7de; border-radius: 8px;
  padding: 0.55rem 0.7rem; margin-bottom: 0.55rem; background: #fff; }
.row.b-images { border-left-color: #0969da; }
.row.b-buttons { border-left-color: #8250df; }
.row.b-texts { border-left-color: #bc4c00; }
.row.b-customs { border-left-color: #1b7c83; }
.row.invalid { background: #fff8f8; border-color: #ffcecb; }
.row.hl { box-shadow: 0 0 0 3px #ffd33d; }
.row .r1 { display: grid; grid-template-columns: 2.6rem 1.4fr 1.6fr 8.5rem 5.5rem 2.2rem; gap: 0.5rem;
  align-items: end; }
.row .r2 { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 0.5rem; margin-top: 0.45rem;
  align-items: end; }
.row .idx { font-size: 0.8rem; color: #57606a; background: #f6f8fa; border-radius: 6px;
  text-align: center; padding: 0.3rem 0; }
.row .chk { display: flex; align-items: center; gap: 0.35rem; font-size: 0.82rem; padding-bottom: 0.35rem; }
.row .chk input { width: auto; }
.row .confirm-note { font-size: 0.8rem; margin-top: 0.4rem; padding: 0.35rem 0.5rem;
  background: #fff8c5; border: 1px solid #d4a72c; border-radius: 6px; color: #7d4e00; }
.row .prov { font-size: 0.75rem; color: #57606a; margin-top: 0.35rem; }
.row .prov code { background: #f6f8fa; padding: 0.05rem 0.3rem; border-radius: 4px; }
@media (max-width: 1180px) {
  .row .r1 { grid-template-columns: 2.2rem 1fr 1fr; }
  .row .r2 { grid-template-columns: 1fr 1fr; }
}

#preview { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; padding: 0.75rem;
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
<h1>Confirm the in-app template</h1>
<p class="meta" id="meta"></p>

<div class="intro">
  This structure was read off the mockup by a vision pass and shaped by the deterministic builder.
  <strong>Nothing is sent anywhere from this page.</strong> Check every box on the picture against the
  row next to it, then:
  <ul>
    <li>Fix keys, names, descriptions and per-element settings.</li>
    <li>Move an element to another <strong>bucket</strong> if it was filed wrong &mdash; its fields are rewritten to that bucket's shape.</li>
    <li><strong>Remove</strong> what isn't a real slot, <strong>add</strong> what the pass missed.</li>
    <li>When happy, <strong>Download</strong> the payload (and give the skill the file path) or <strong>Copy</strong> it into the chat.</li>
  </ul>
  Dashed grey boxes are <strong>client-rendered</strong> regions: the client draws them itself, so they are
  deliberately <em>not</em> template elements. They are shown only so you can confirm nothing was wrongly dropped.
</div>

<div class="toolbar">
  <button class="primary" id="download">&#11015; Download template JSON</button>
  <button id="copy">&#9109; Copy JSON</button>
  <span class="spacer"></span>
  <span id="status" class="ok">Ready</span>
</div>

<div id="build-notes"></div>
<div id="live-errors"></div>

<div class="panel">
  <h2>Template</h2>
  <div class="head-grid">
    <div>
      <label for="tpl-name">Name</label>
      <input type="text" id="tpl-name" placeholder="Summer Offer">
    </div>
    <div>
      <label for="tpl-key">Key</label>
      <input type="text" id="tpl-key" placeholder="summer_offer">
    </div>
    <div>
      <label for="tpl-feature">Feature type</label>
      <select id="tpl-feature"></select>
    </div>
    <div class="wide">
      <label for="tpl-desc">Description</label>
      <input type="text" id="tpl-desc" placeholder="What this pop-up is for">
    </div>
  </div>
  <div class="fpanel" id="fp-mission" hidden>
    <div><label for="fp-maxPlacements">maxPlacements</label><input type="number" id="fp-maxPlacements" min="1"></div>
    <div><label for="fp-maxSetsCount">maxSetsCount</label><input type="number" id="fp-maxSetsCount" min="1"></div>
    <div><label for="fp-minPlacements">minPlacements</label><input type="number" id="fp-minPlacements" min="1"></div>
    <div><label for="fp-minSetsCount">minSetsCount</label><input type="number" id="fp-minSetsCount" min="1"></div>
  </div>
  <div class="fpanel" id="fp-milestone" hidden>
    <div><label for="fp-limit">limit</label><input type="number" id="fp-limit" min="1"></div>
  </div>
  <div class="mut" id="fp-note"></div>
</div>

<div class="cols" id="cols">
  <div class="mockup-col" id="mockup-col">
    <div class="stage" id="stage">
      <img id="mockup" alt="mockup">
      <div id="overlay"></div>
    </div>
    <div class="legend">
      <span><i style="background:#0969da"></i>images</span>
      <span><i style="background:#8250df"></i>buttons</span>
      <span><i style="background:#bc4c00"></i>texts</span>
      <span><i style="background:#1b7c83"></i>customs</span>
      <span><i style="background:#8c959f"></i>client-rendered (not a slot)</span>
    </div>
    <div class="cr-list" id="cr-list"></div>
  </div>
  <div id="elements"></div>
</div>

<h2 style="margin-top:1.5rem">Payload that will be registered</h2>
<p class="mut">Select and copy this block if the buttons above are blocked by your browser.</p>
<pre id="preview"></pre>

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

function clone(v) { return v === undefined ? null : JSON.parse(JSON.stringify(v)); }
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
function normalizeElement(bucket, el) {
  var t = TRACE[bucket + "\\u0000" + (el.key || "")] || null;
  var c = CONFIRM[bucket + "\\u0000" + (el.key || "")] || null;
  return {
    uid: "e" + (++uidSeq),
    bucket: bucket,
    confirm: c ? c.question : "",
    key: el.key || "",
    name: el.name || "",
    description: el.description || "",
    canBeHidden: el.canBeHidden !== false,
    customFields: clone(el.customFields || []) || [],
    bbox: t && t.bbox ? t.bbox : null,
    role: t ? (t.role || "") : "",
    observedText: t ? (t.observed_text || "") : "",
    confidence: t && t.confidence != null ? t.confidence : null,
    size: clone(el.size) || clone(C.defaults.imageSize),
    backgroundImg: clone(el.backgroundImg) || clone(C.defaults.buttonBg),
    textLimit: num(el.textLimit, C.defaults.textLimit),
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
C.buckets.forEach(function (b) {
  (P[b] || []).forEach(function (el) { state.elements.push(normalizeElement(b, el)); });
});

// ---- export -------------------------------------------------------------
function orderedElements() {
  // Display order: bucket by bucket, rows in the order they are shown.
  var out = [];
  C.buckets.forEach(function (b) {
    state.elements.forEach(function (e) { if (e.bucket === b) out.push(e); });
  });
  return out;
}

function indexMap() {
  var m = {};
  orderedElements().forEach(function (e, i) { m[e.uid] = i; });
  return m;
}

function coerceDefault(e) {
  if (e.kind === "boolean") return String(e.defaultValue) === "true";
  if (e.kind === "numeric") {
    var n = Number(e.defaultValue);
    return e.defaultValue === "" || isNaN(n) ? 0 : n;
  }
  return String(e.defaultValue);
}

function elementOut(e, index) {
  var key = String(e.key).trim();
  var name = String(e.name).trim();
  var desc = String(e.description);
  if (e.bucket === "images") {
    return { key: key, name: name, size: clone(e.size), index: index, description: desc,
             canBeHidden: !!e.canBeHidden, customFields: clone(e.customFields) };
  }
  if (e.bucket === "buttons") {
    var out = { key: key, name: name, index: index, textLimit: num(e.textLimit, C.defaults.textLimit),
                description: desc, canBeHidden: !!e.canBeHidden, customFields: clone(e.customFields),
                backgroundImg: clone(e.backgroundImg), clickActionType: e.clickActionType.slice() };
    if (needsItems(e)) out.requiredItemsCount = num(e.requiredItemsCount, 1);
    // The names are what the game client switches on, so they ship only while
    // the 'custom' action is actually offered.
    if (hasCustomAction(e)) out.customCtaNames = ctaNameList(e);
    return out;
  }
  if (e.bucket === "texts") {
    return { key: key, name: name, index: index, nullable: !!e.nullable,
             textLimit: num(e.textLimit, C.defaults.textLimit), description: desc,
             canBeHidden: !!e.canBeHidden, customFields: clone(e.customFields) };
  }
  var custom = { key: key, name: name, kind: e.kind, index: index, nullable: !!e.nullable,
                 description: desc, canBeHidden: !!e.canBeHidden,
                 customFields: clone(e.customFields), defaultValue: coerceDefault(e) };
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
  var idx = 0;
  C.buckets.forEach(function (b) {
    body[b] = state.elements.filter(function (e) { return e.bucket === b; })
      .map(function (e) { return elementOut(e, idx++); });
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
  var out = clone(state.features);
  if (!out || typeof out !== "object") return out;
  Object.keys(FEATURE_NUMERICS).forEach(function (t) {
    if (!out[t]) return;
    FEATURE_NUMERICS[t].forEach(function (k) {
      if (k in out[t]) out[t][k] = num(out[t][k], 1);
    });
  });
  return out;
}

function exportJson() { return JSON.stringify(buildTemplate(), null, 2); }
window.exportJson = exportJson;
window.buildTemplate = buildTemplate;

// ---- validation (mirrors inapp_template_build.validate_payload) ---------
function validate() {
  var body = buildTemplate();
  var errors = [];
  var warnings = [];
  var rowErrors = {};
  function rowErr(uid, msg) { rowErrors[uid] = rowErrors[uid] ? rowErrors[uid] + " " + msg : msg; }

  if (!body.name) errors.push("Template name is required.");
  if (!TPL_KEY_RE.test(body.key || "")) errors.push("Template key " + JSON.stringify(body.key) + " must match " + C.templateKeyRe);
  if (C.featureTypes.indexOf(body.featureType) < 0) errors.push("Unknown feature type " + JSON.stringify(body.featureType) + ".");
  if (body.featureType === "standard") {
    if (body.features && Object.keys(body.features).length) {
      errors.push("featureType 'standard' must carry features: {}.");
    }
  } else if (!body.features || typeof body.features !== "object" || !body.features[body.featureType]) {
    errors.push("featureType '" + body.featureType + "' requires features." + body.featureType + ".");
  }

  C.buckets.forEach(function (b) {
    var seen = {};
    state.elements.filter(function (e) { return e.bucket === b; }).forEach(function (e) {
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
      (e.customFields || []).forEach(function (cf) {
        // customFields accept 'image' on top of the four element kinds.
        if (C.fieldKinds.indexOf(cf.kind) < 0) {
          errors.push(b + "." + k + ": custom field " + JSON.stringify(cf.key) + " has invalid kind " + JSON.stringify(cf.kind) + ".");
        }
      });
    });
  });

  return { errors: errors, warnings: warnings, rowErrors: rowErrors,
           count: state.elements.length };
}

// ---- static panels ------------------------------------------------------
function listPanel(title, items, cls, renderItem) {
  if (!items || !items.length) return null;
  var d = document.createElement("div");
  d.className = "panel " + cls;
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
function boxEl(bbox, cls, label) {
  var d = document.createElement("div");
  d.className = "box " + cls;
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
  (REPORT.client_rendered || []).forEach(function (cr) {
    if (!cr.bbox) return;
    ov.appendChild(boxEl(cr.bbox, "client", "client: " + cr.role));
  });
  state.elements.forEach(function (e) {
    if (!e.bbox) return;
    var b = boxEl(e.bbox, "b-" + e.bucket, "#" + idx[e.uid] + " " + (e.key || "(no key)"));
    b.dataset.uid = e.uid;
    b.addEventListener("mouseenter", function () { highlight(e.uid, true); });
    b.addEventListener("mouseleave", function () { highlight(e.uid, false); });
    b.addEventListener("click", function () {
      var row = document.querySelector('.row[data-uid="' + e.uid + '"]');
      if (row && row.scrollIntoView) row.scrollIntoView({ block: "center" });
    });
    ov.appendChild(b);
  });
}

function highlight(uid, on) {
  var box = document.querySelector('.box[data-uid="' + uid + '"]');
  var row = document.querySelector('.row[data-uid="' + uid + '"]');
  if (box) box.classList.toggle("hl", on);
  if (row) row.classList.toggle("hl", on);
}

// ---- element rows -------------------------------------------------------
function labeled(text, node, cls) {
  var wrap = document.createElement("div");
  if (cls) wrap.className = cls;
  var lab = document.createElement("label");
  lab.textContent = text;
  wrap.appendChild(lab);
  wrap.appendChild(node);
  return wrap;
}

function textInput(value, fid, oninput, opts) {
  opts = opts || {};
  var inp = document.createElement("input");
  inp.type = opts.number ? "number" : "text";
  inp.value = value == null ? "" : value;
  if (opts.placeholder) inp.placeholder = opts.placeholder;
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
  var wrap = document.createElement("div");
  wrap.className = "chk";
  var inp = document.createElement("input");
  inp.type = "checkbox";
  inp.checked = !!checked;
  inp.dataset.fid = fid;
  inp.addEventListener("change", function (ev) { onchange(ev.target.checked); });
  var lab = document.createElement("span");
  lab.textContent = text;
  wrap.appendChild(inp);
  wrap.appendChild(lab);
  return wrap;
}

function switchBucket(e, target) {
  // Rewrite to the target bucket's shape: fields that bucket never had are
  // seeded with its defaults, the shared ones (key/name/description/
  // canBeHidden/customFields) carry over untouched.
  e.bucket = target;
  if (target === "images" && !e.size) e.size = clone(C.defaults.imageSize);
  if (target === "buttons") {
    if (!e.backgroundImg) e.backgroundImg = clone(C.defaults.buttonBg);
    if (!e.clickActionType || !e.clickActionType.length) e.clickActionType = ["close"];
    if (!e.textLimit) e.textLimit = C.defaults.textLimit;
  }
  if (target === "texts" && !e.textLimit) e.textLimit = C.defaults.textLimit;
  if (target === "customs" && C.kinds.indexOf(e.kind) < 0) e.kind = "string";
}

function elementRow(e, index, err) {
  var row = document.createElement("div");
  row.className = "row b-" + e.bucket + (err ? " invalid" : "");
  row.dataset.uid = e.uid;
  row.addEventListener("mouseenter", function () { highlight(e.uid, true); });
  row.addEventListener("mouseleave", function () { highlight(e.uid, false); });

  var r1 = document.createElement("div");
  r1.className = "r1";

  var idx = document.createElement("div");
  idx.className = "idx";
  idx.title = "Index is assigned on export — it is not editable.";
  idx.textContent = "#" + index;
  r1.appendChild(labeled(" ", idx));

  r1.appendChild(labeled("Key", textInput(e.key, e.uid + "-key", function (v) {
    e.key = v; refresh();
  }, { placeholder: "header_text", bad: !!(err && err.indexOf("Key") >= 0) })));

  r1.appendChild(labeled("Name", textInput(e.name, e.uid + "-name", function (v) {
    e.name = v; refresh();
  }, { placeholder: "Header" })));

  r1.appendChild(labeled("Bucket", selectInput(C.buckets, e.bucket, e.uid + "-bucket", function (v) {
    switchBucket(e, v); refresh();
  })));

  r1.appendChild(checkbox("canBeHidden", e.canBeHidden, e.uid + "-hidden", function (v) {
    e.canBeHidden = v; refresh();
  }));

  var rm = document.createElement("button");
  rm.className = "danger tiny";
  rm.textContent = "\\u2715";
  rm.title = "Remove this element";
  rm.dataset.fid = e.uid + "-remove";
  rm.addEventListener("click", function () {
    state.elements = state.elements.filter(function (x) { return x !== e; });
    refresh();
  });
  r1.appendChild(labeled(" ", rm));
  row.appendChild(r1);

  var r2 = document.createElement("div");
  r2.className = "r2";
  r2.appendChild(labeled("Description", textInput(e.description, e.uid + "-desc", function (v) {
    e.description = v; refresh();
  })));

  if (e.bucket === "buttons") {
    r2.appendChild(labeled("Click actions", selectInput(C.clickActions, e.clickActionType,
      e.uid + "-actions", function (v) { e.clickActionType = v; refresh(); }, { multiple: true })));
    // Numeric fields hold the RAW string while being typed and are coerced at
    // export — coercing on every keystroke would snap a cleared field back to
    // the default and make it impossible to retype.
    r2.appendChild(labeled("textLimit", textInput(e.textLimit, e.uid + "-limit", function (v) {
      e.textLimit = v; refresh();
    }, { number: true })));
    if (needsItems(e)) {
      r2.appendChild(labeled("requiredItemsCount", textInput(e.requiredItemsCount, e.uid + "-items",
        function (v) { e.requiredItemsCount = v; refresh(); }, { number: true })));
    }
    if (hasCustomAction(e)) {
      r2.appendChild(labeled("customCtaNames", textInput(e.customCtaNames, e.uid + "-cta",
        function (v) { e.customCtaNames = v; refresh(); },
        { placeholder: "Info, Rules", bad: !!(err && err.indexOf("CTA name") >= 0) })));
    }
  } else if (e.bucket === "texts") {
    r2.appendChild(labeled("textLimit", textInput(e.textLimit, e.uid + "-limit", function (v) {
      e.textLimit = v; refresh();
    }, { number: true })));
    r2.appendChild(checkbox("nullable", e.nullable, e.uid + "-nullable", function (v) {
      e.nullable = v; refresh();
    }));
  } else if (e.bucket === "customs") {
    r2.appendChild(labeled("kind", selectInput(C.kinds, e.kind, e.uid + "-kind", function (v) {
      e.kind = v; refresh();
    })));
    if (e.kind === "boolean") {
      r2.appendChild(labeled("defaultValue", selectInput(["false", "true"],
        String(e.defaultValue) === "true" ? "true" : "false", e.uid + "-default",
        function (v) { e.defaultValue = v; refresh(); })));
    } else {
      r2.appendChild(labeled("defaultValue", textInput(e.defaultValue, e.uid + "-default",
        function (v) { e.defaultValue = v; refresh(); },
        { number: e.kind === "numeric" })));
    }
    if (e.kind === "enumeration") {
      r2.appendChild(labeled("enumValues", textInput(e.enumValues, e.uid + "-enum", function (v) {
        e.enumValues = v; refresh();
      }, { placeholder: "a, b, c" })));
    }
  }
  row.appendChild(r2);

  if (err) {
    var ediv = document.createElement("div");
    ediv.className = "err";
    ediv.textContent = err;
    row.appendChild(ediv);
  }

  if (e.confirm) {
    var cdiv = document.createElement("div");
    cdiv.className = "confirm-note";
    cdiv.innerHTML = "<b>Confirm:</b> " + esc(e.confirm);
    row.appendChild(cdiv);
  }

  var bits = [];
  if (e.role) bits.push("role <code>" + esc(e.role) + "</code>");
  if (e.observedText) bits.push("text &ldquo;" + esc(e.observedText) + "&rdquo;");
  if (e.confidence != null) bits.push("confidence " + esc(e.confidence));
  if ((e.customFields || []).length) {
    bits.push((e.customFields.length) + " custom field(s): " +
      e.customFields.map(function (cf) { return "<code>" + esc(cf.key) + "</code>"; }).join(", "));
  }
  if (!e.bbox) bits.push("<b>no box on the mockup</b>");
  if (bits.length) {
    var prov = document.createElement("div");
    prov.className = "prov";
    prov.innerHTML = bits.join(" &middot; ");
    row.appendChild(prov);
  }
  return row;
}

function newElement(bucket) {
  var e = normalizeElement(bucket, {});
  e.bbox = null;
  e.canBeHidden = true;
  return e;
}

function renderElements(idx, rowErrors) {
  var host = document.getElementById("elements");
  var active = document.activeElement;
  var fid = active && active.dataset ? active.dataset.fid : null;
  var selStart = fid && "selectionStart" in active ? active.selectionStart : null;
  var selEnd = fid && "selectionEnd" in active ? active.selectionEnd : null;
  host.innerHTML = "";

  C.buckets.forEach(function (b) {
    var sec = document.createElement("div");
    sec.className = "bucket";
    sec.id = "bucket-" + b;

    var head = document.createElement("div");
    head.className = "bhead";
    var dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = C.bucketColors[b];
    head.appendChild(dot);
    var h = document.createElement("h3");
    var mine = state.elements.filter(function (e) { return e.bucket === b; });
    h.textContent = C.bucketLabels[b] + " (" + mine.length + ")";
    head.appendChild(h);
    sec.appendChild(head);

    mine.forEach(function (e) { sec.appendChild(elementRow(e, idx[e.uid], rowErrors[e.uid])); });
    if (!mine.length) {
      var empty = document.createElement("div");
      empty.className = "mut";
      empty.textContent = "Nothing in this bucket.";
      sec.appendChild(empty);
    }

    var add = document.createElement("button");
    add.className = "ghost tiny";
    add.dataset.fid = "add-" + b;
    add.textContent = "\\uff0b Add " + C.bucketLabels[b].toLowerCase().replace(/s$/, "");
    add.addEventListener("click", function () { state.elements.push(newElement(b)); refresh(); });
    sec.appendChild(add);
    host.appendChild(sec);
  });

  if (fid) {
    var el = host.querySelector('[data-fid="' + fid + '"]');
    if (el) {
      el.focus();
      if (selStart !== null && "setSelectionRange" in el) {
        try { el.setSelectionRange(selStart, selEnd); } catch (err) { /* number inputs */ }
      }
    }
  }
}

// ---- feature panel ------------------------------------------------------
// Feature blocks are stashed as the developer flips the selector, so a detour
// through 'standard' (which must serialise features: null) does not throw away
// the block the builder produced.
var featuresStash = state.features && typeof state.features === "object" ? clone(state.features) : {};

function syncFeaturePanel() {
  var t = state.featureType;
  if (state.features && typeof state.features === "object") {
    Object.keys(state.features).forEach(function (k) { featuresStash[k] = clone(state.features[k]); });
  }
  document.getElementById("fp-mission").hidden = t !== "mission";
  document.getElementById("fp-milestone").hidden = t !== "milestone";
  var note = document.getElementById("fp-note");
  if (t === "standard") {
    state.features = {};
    note.textContent = "standard — the payload carries features: {}.";
    return;
  }
  state.features = {};
  state.features[t] = featuresStash[t]
    ? clone(featuresStash[t])
    : clone(t === "mission" ? C.missionDefaults : C.milestoneDefaults);
  var f = state.features[t];
  if (t === "mission") {
    ["maxPlacements", "maxSetsCount", "minPlacements", "minSetsCount"].forEach(function (k) {
      document.getElementById("fp-" + k).value = f[k];
    });
    note.textContent = "mission — the rest of features.mission (progress bar, CTA sets) is kept as built.";
  } else {
    document.getElementById("fp-limit").value = f.limit;
    note.textContent = "milestone — mainActionTypes / milestonesActionTypes are kept as built.";
  }
}

// ---- refresh ------------------------------------------------------------
function refresh() {
  var v = validate();
  var idx = indexMap();
  renderElements(idx, v.rowErrors);
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

  var st = document.getElementById("status");
  if (v.errors.length) {
    st.className = "bad";
    st.textContent = v.errors.length + " problem(s) — payload is invalid";
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
    o.value = t; o.textContent = t;
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
  document.getElementById("fp-limit").addEventListener("input", function (ev) {
    if (!state.features || !state.features.milestone) return;
    state.features.milestone.limit = ev.target.value;
    refresh();
  });

  document.getElementById("download").addEventListener("click", function () {
    var blob = new Blob([exportJson()], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "kinoa-inapp-template-" + (String(state.key).trim() || "template") + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
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

  renderBuildNotes();
  renderClientRendered();
  syncFeaturePanel();
  refresh();
})();

function flash(msg) {
  var el = document.getElementById("status");
  var cls = el.className;
  el.className = "ok";
  el.textContent = msg;
  setTimeout(function () { el.className = cls; refresh(); }, 1500);
}
</script>
</body>
</html>
"""


def render(payload: dict[str, Any], image_data_uri: str | None = None) -> str:
    """Render the confirmation page for one `inapp_template_build build` result."""
    data = {
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
        "bucketColors": {"images": "#0969da", "buttons": "#8250df",
                         "texts": "#bc4c00", "customs": "#1b7c83"},
        "defaults": {"imageSize": DEFAULT_IMAGE_SIZE, "buttonBg": DEFAULT_BUTTON_BG,
                     "textLimit": DEFAULT_TEXT_LIMIT},
        "elementKeyRe": ELEMENT_KEY_RE,
        "templateKeyRe": TEMPLATE_KEY_RE,
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

    data_uri, image_path = resolve_image(build, args.image, build_path)
    if args.image and not data_uri:
        print(json.dumps({"ok": False, "error": "unsupported_image",
                          "image": os.path.abspath(args.image),
                          "hint": "Expected png, jpeg, gif or webp (detected from the magic bytes)."}))
        return 2

    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(build_path)) if build_path else os.getcwd(),
        "inapp-template-confirm.html")
    html_doc = render(build, data_uri)
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
        "bytes": len(html_doc),
        "image_embedded": bool(data_uri),
        "image_source": image_path,
        "element_count": (build.get("report") or {}).get("element_count"),
        "build_valid": bool((build.get("validation") or {}).get("ok")),
        "opened_in_browser": opened,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
