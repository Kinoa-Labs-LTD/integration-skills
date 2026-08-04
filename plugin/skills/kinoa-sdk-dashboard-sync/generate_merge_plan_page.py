#!/usr/bin/env python3
"""Generate the INTERACTIVE merge-plan page for the /kinoa SDK skill's Phase 6 (--merge).

The authoring gate for the code-emitted surfaces: BEFORE any integration code is
generated, the developer reviews and EDITS what will be implemented — event
names + params, player fields + kinds, feature-settings schemas/keys/columns —
exactly the way the resources confirmation page authors the resources
catalogue. Editing is legitimate here because the code carrier does not exist
yet; once the approved plan lands in code, the code is the source of truth and
renames ship code-first (the manifest measures it byte-for-byte).

Rows the game code ALREADY implements arrive with "existing": true and render
READ-ONLY (edit those code-first); only new proposals are editable.

The page can't write to the filesystem (browser sandbox); the developer hands
the confirmed plan back via Download (JSON file) or Copy (paste in chat).

Usage:
    cat plan.json | python generate_merge_plan_page.py --output merge-plan.html
    python generate_merge_plan_page.py --input plan.json --output merge-plan.html

Input JSON shape (sections may be empty or omitted):

{
  "generated_at": "<ISO 8601 UTC>",
  "game_id":      "<uuid or null>",
  "integration_type": "SDK" | "API"  (default "SDK"),
  "predefined_wire_names":    ["session_start", "payment", "install", "..."],
  "debug_wire_names":         ["feature_settings_download", "tick", "..."],
  "sdk_automatic_wire_names": ["install", "player_update", "reach_milestone", "..."],
  "events": [
    {"id": 1, "kind": "custom"|"predefined", "name": "gold_purchase", "existing": false,
     "source": "Scripts/Shop.cs:118", "note": "purchase flow",
     "params": [{"name": "amount", "kind": "number", "extra": ""}]}
  ],
  "player_fields": [
    {"id": 20, "name": "Wallet.Gold", "kind": "number", "extra": "", "existing": false,
     "source": "Scripts/Model/Player/Wallet.cs:12", "note": "",
     "path": "wallet.gold", "description": ""}
  ],
                 ("path" = the registered snake path from the manifest — the dup check
                  honors [JsonPropertyName] overrides; "description" is OPTIONAL and
                  SDK-producer-only: measured from the C# XML-doc summary, editable on
                  new rows, forwarded to the create call — absent key stays absent)
  "feature_settings": {
    "schemas":  [{"id": 40, "name": "BoosterEconomy", "existing": false,
                  "source": "booster_economy.csv", "version": 3,
                  "columns": [{"name": "sku", "kind": "bundle_key", "is_required": true}]}],
                 ("version" on EXISTING schemas = the HIGHEST version wired in code across
                  the sibling keys (keys wired at different versions of one schema are a
                  VALID backward-compat state — older published versions stay resolvable);
                  new settings bound to that schema display and export it — new schemas
                  are always v1)
    "settings": [{"id": 41, "key": "BoosterEconomy", "schema_name": "BoosterEconomy",
                  "version": 1, "existing": false, "source": "..."}]
  },
     (FS mirrors the manifest/domain: SCHEMAS own the columns — one schema may back
      several setting KEYS, which only reference a schema by name via a dropdown.
      A pre-split flat feature_settings ARRAY is tolerated and converted on load.
      is_required is ALWAYS true — no dashboard UI control exists; the key is kept
      in the contract deliberately until the API drops it from the SchemaDto)
  "resources": [
    {"id": 60, "name": "Legendary Sword", "key": "legendary_sword", "existing": false,
     "description": "Boss reward.", "source": "Model/Enums/RewardType.cs:10", "note": "",
     "fields": [{"name": "attack", "field_type": "number",
                 "default": "100", "enumeration_values": [], "description": ""}]}
  ]
}

A merge run fires this page PER MODULE as its walk reaches each surface — the
payload then carries just that section, and the page RENDERS ONLY THE SECTIONS
PRESENT in the payload (omit a key entirely to hide its card, add button
included); /kinoa resources thus yields a resources-only page. The page is
light-themed by design (no dark variant — see the CSS note).

The exported plan echoes the same shape plus stamps:

{"confirmed_at": "<iso>", "page_generated_at": "<echo of generated_at>",
 "payload_version": <echo, absent input = 1>,
 "events": [...], "player_fields": [...], "feature_settings": [...], "resources": [...]}

(existing rows are echoed verbatim; the skill implements only "existing": false
rows, exactly as edited.)

Event registries (optional keys; live-sourced from the server taxonomy, module-13
tables as fallback): a row named like a PREDEFINED event is live-tagged
"predefined" (name stays editable unless the row arrived kind="predefined") and
exported kind="predefined" — the producer extends the existing predefined builder
(overload + AddCustomParameter) instead of creating a custom mirror. A row named
like a DEBUG event is tagged "debug", exported kind="debug", and skipped at
implementation (emitted by the SDK/backend itself). SDK-AUTOMATIC predefined names
(install, player_update, *_milestones) keep the predefined tag, but under
integration_type "SDK" their param editor is disabled (the SDK composes them; an
API integration may extend their params). Keys absent -> no tagging (older
producers); the sync planner's live-listing collision warning remains the backstop.

Exit: prints {"ok": true, "output": "<abs path>", "opened_in_browser": bool}.
No network, no credentials.

PAYLOAD COMPATIBILITY CONTRACT (the SDK skill builds the payload at ITS version;
this page auto-updates via the plugin — the two ends skew, so):
  1. The page TOLERATES absent optional keys and IGNORES unknown keys — it must
     never crash on an older producer's payload (render sensible defaults).
  2. The hand-back shape is APPEND-ONLY: never rename or remove an export key,
     never flip a default's meaning. The freeze test pins the key names.
  3. Breaking changes go through PAYLOAD_VERSION only: the producer stamps
     "payload_version" (absent = 1); a payload NEWER than this page refuses
     loudly (banner + export disabled — update the plugin). New authoring
     CONTROLS render only when the payload opts in — an old producer must
     never receive hand-back keys it can't honor (a control the producer
     ignores is a UI promise the code breaks silently).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import webbrowser

# Kind vocabularies — MUST stay equal to kinoa_sdk_sync_plan.py's constants
# (EVENT_PARAM_KINDS / FIELD_KINDS / FS_COLUMN_KINDS / RESOURCE_FIELD_TYPES /
# RESOURCE_KEY_RE); tests enforce the parity.
EVENT_PARAM_KINDS = ["number", "boolean", "string", "date", "enumeration", "string_array", "number_array"]
FIELD_KINDS = ["number", "boolean", "string", "date", "long_string", "enumeration", "version"]
FS_COLUMN_KINDS = ["integer", "number", "string", "boolean", "bundle_key"]
RESOURCE_FIELD_TYPES = ["number", "string", "boolean", "date", "enumeration"]
RESOURCE_KEY_RE = r"^[a-zA-Z][a-zA-Z0-9_-]*$"
# The dashboard auto-attaches these to every event; an operator param with the same
# name silently DISPLACES the system column (planner constant — parity-tested).
SYSTEM_EVENT_PARAM_NAMES = ["device_id", "level", "place", "success", "time", "time_ms", "wifi"]
# The reserved set splits by ROUTE (SDK internals, verified 2026-07-29/30): base-class
# properties the game sets vs values the SDK composes itself. Union == the reserved list.
SYSTEM_BASE_PROP_PARAM_NAMES = ["level", "place", "success"]
SYSTEM_AUTO_PARAM_NAMES = ["device_id", "time", "time_ms", "wifi"]
assert sorted(SYSTEM_BASE_PROP_PARAM_NAMES + SYSTEM_AUTO_PARAM_NAMES) == SYSTEM_EVENT_PARAM_NAMES
# Canonical kinds pinned by the SDK base classes (live-read 2026-07-30: GameEventData /
# ExtendedGameEventData property types) — the page LOCKS the type for system params.
SYSTEM_PARAM_KINDS = {"device_id": "string", "level": "number", "place": "string",
                      "success": "boolean", "time": "number", "time_ms": "number",
                      "wifi": "boolean"}
assert sorted(SYSTEM_PARAM_KINDS) == SYSTEM_EVENT_PARAM_NAMES
# Bump ONLY on a breaking payload/hand-back change (contract clause 3).
PAYLOAD_VERSION = 1

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinoa — Merge Plan</title>
<style>
/* Light-only by design: with `light dark` the UA flips button/control text colors in
   dark mode while our fixed backgrounds stay light -> invisible button labels. */
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ font: 15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0;
       background: #f6f8fa; color: #1f2328; }}
header {{ padding: 1.2rem 1.5rem 0; max-width: 1120px; margin: 0 auto; }}
header .bar {{ background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 0.9rem 1.2rem; }}
h1 {{ font-size: 1.25rem; margin: 0 0 0.25rem; }}
h2 {{ font-size: 1.05rem; margin: 0 0 0.5rem; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 0.75rem 1.5rem 5rem; }}
.card {{ background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem 1.2rem; margin-top: 1rem; }}
.muted {{ color: #57606a; font-size: 0.86rem; }}
.row {{ border: 1px solid #e6e8eb; border-radius: 6px; padding: 0.6rem 0.8rem; margin: 0.55rem 0; }}
.row.locked {{ opacity: 0.75; }}
.grid {{ display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; }}
input[type=text], select {{ font: inherit; padding: 0.3rem 0.45rem; border: 1px solid #d0d7de; border-radius: 6px;
       background: #fff; color: #1f2328; }}
input.bad, select.bad {{ border-color: #cf222e; background: #fff5f5; }}
input.warnp {{ border-color: #bf8700; }}
.badge {{ display: inline-block; font-size: 0.72rem; padding: 0.1rem 0.5rem; border-radius: 999px;
         border: 1px solid currentColor; white-space: nowrap; }}
.b-existing {{ color: #57606a; }} .b-new {{ color: #1a7f37; }} .b-predef {{ color: #0969da; }} .b-debug {{ color: #bf8700; }} .b-user {{ color: #8250df; }} .b-system {{ color: #0e7490; }}
button {{ font: inherit; padding: 0.35rem 0.8rem; border-radius: 6px; cursor: pointer;
         border: 1px solid #d0d7de; background: #fff; color: #1f2328; }}
button.ghost {{ border-style: dashed; }}
button.primary {{ background: #1f883d; border-color: #1f883d; color: #fff; }}
button.del {{ color: #cf222e; }}
/* Select-first (user decision 2026-07-29): unticked rows stay alive but dimmed —
   no destructive drop exists; the pencil pins right like the old drop did. */
.row.excluded {{ opacity: 0.45; }}
table.sub tr.removedp td {{ opacity: 0.5; }}
table.sub tr.removedp code {{ text-decoration: line-through; }}
input.inc {{ width: 1.05rem; height: 1.05rem; accent-color: #1f883d; }}
.grid > button.pencil {{ margin-left: auto; padding: 0.15rem 0.6rem; font-size: 0.85rem; }}
.grid > button.remove {{ margin-left: 0.35rem; padding: 0.15rem 0.6rem; font-size: 0.85rem; color: #c0392b; }}
table.sub button.remove {{ color: #c0392b; padding: 0 0.45rem; font-size: 0.85rem; }}
table.sub {{ width: 100%; border-collapse: collapse; margin-top: 0.4rem; }}
table.sub td {{ padding: 0.15rem 0.3rem; }}
footer {{ position: fixed; bottom: 0; left: 0; right: 0; background: #1f2328; color: #fff;
         padding: 0.7rem 1.5rem; display: flex; gap: 1rem; align-items: center; }}
footer .grow {{ flex: 1; }}
#flash {{ margin-left: 0.5rem; }}
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>Merge plan — approve what gets implemented</h1>
    <div class="muted">
      Game <code>{game_id}</code> · generated {generated_at} ·
      tick the candidates to implement (unticked rows are left out — nothing is deleted),
      ✎ opens a row for editing, ＋ adds missed entries.
      Rows already in code are read-only — edit those code-first (the code is the source of truth).
      Names ship byte-for-byte into your code and, later, onto the Dashboard.
    </div>
    <div class="muted" style="margin-top:0.45rem">
      This page is <b>optional</b>. Prefer chat? Either <b>ask the assistant for edits</b>
      ("rename X to Y") — it applies the naming conventions and refreshes this page for your
      final tick-and-download — or say <b>"continue in chat"</b> to close this tab and finish
      the whole review there.
    </div>
  </div>
</header>
<main>
  <div class="card" id="events-card"><h2>Events</h2><div id="events"></div>
    <button class="ghost" id="add-event">＋ Add event</button></div>
  <div class="card" id="fields-card"><h2>User fields</h2><div id="player_fields"></div>
    <button class="ghost" id="add-field">＋ Add field</button></div>
  <div class="card" id="fs-card"><h2>Feature settings</h2><div id="feature_settings"></div></div>
  <div class="card" id="res-card"><h2>Resources (Dashboard resource templates)</h2><div id="resources"></div>
    <button class="ghost" id="add-res">＋ Add resource</button></div>
</main>
<footer>
  <div class="grow" id="counter"></div>
  <button id="download" class="primary">⬇ Download plan</button>
  <button id="copy">Copy plan</button>
  <span id="flash"></span>
</footer>
<script>
const DATA = {data_json};
const EVENT_PARAM_KINDS = {event_param_kinds};
const FIELD_KINDS = {field_kinds};
const FS_COLUMN_KINDS = {fs_column_kinds};
const RESOURCE_FIELD_TYPES = {resource_field_types};
const RESOURCE_KEY_RE = new RegExp({resource_key_re});
const SYSTEM_EVENT_PARAM_NAMES = {system_event_param_names};
const SYSTEM_BASE_PROP_PARAM_NAMES = {system_base_prop_param_names};
const SYSTEM_AUTO_PARAM_NAMES = {system_auto_param_names};
const SYSTEM_PARAM_KINDS = {system_param_kinds};
// Registries travel IN THE PAYLOAD (optional keys, contract clause 1) — sourced live from
// the server taxonomy (type=PREDEFINED / type=DEBUG listings) with the /kinoa module-13
// tables as offline fallback. Absent keys -> no live tagging (the sync planner's
// live-listing collision warning stays the backend-fresh backstop).
//   predefined_wire_names — ALL type=PREDEFINED names (incl. SDK-automatic ones like install)
//   debug_wire_names      — type=DEBUG telemetry (feature_settings_download, ...);
//                           never sent from app code, the row is skipped.
//   sdk_automatic_wire_names — the PREDEFINED subset emitted by the SDK itself (install,
//                           player_update, *_milestones): tagged predefined, but under an
//                           SDK integration their params are NOT redefinable (API may extend).
const PREDEFINED_EVENT_WIRE_NAMES = DATA.predefined_wire_names || [];
const DEBUG_WIRE_NAMES = DATA.debug_wire_names || DATA.sdk_debug_wire_names || [];
const SDK_AUTOMATIC_WIRE_NAMES = DATA.sdk_automatic_wire_names || [];
const INTEGRATION_TYPE = DATA.integration_type || "SDK";
const REGISTRIES_SOURCE = DATA.registries_source || "";  // "live" | "fallback" | absent
// Dashboard field registry (optional, live-sourced like the event registries) — the
// server reserves predefined/calculated paths and enforces NAME uniqueness across
// ALL statuses ("path is reserved" / "name has already been taken").
const FIELD_REGISTRY = DATA.dashboard_field_registry || {{}};
const FR_PREDEF = {{}};
(FIELD_REGISTRY.predefined || []).forEach(e => {{ if (e && e.path) FR_PREDEF[e.path] = e.kind || ""; }});
const FR_CALC = {{}};
(FIELD_REGISTRY.calculated || []).forEach(e => {{ if (e && e.path) FR_CALC[e.path] = e.kind || ""; }});
const FR_CUSTOM_PATHS = new Set(FIELD_REGISTRY.custom_paths || []);
const FR_NAMES = new Set((FIELD_REGISTRY.names || []).map(n => String(n).trim().toLowerCase()));
const PAYLOAD_VERSION = {payload_version};
const DATA_VERSION = DATA.payload_version || 1;
const VERSION_MISMATCH = DATA_VERSION > PAYLOAD_VERSION;

// FS is authored as TWO lists mirroring the manifest/domain: schemas (column shapes —
// one schema may back several keys) and settings (runtime keys, each binding ONE schema
// via a dropdown). This kills the same-schema-different-columns ambiguity by construction.
// Tolerance (contract clause 1): a pre-split FLAT array payload is converted on the fly.
function normalizeFs(v) {{
  if (!v) return {{schemas: [], settings: []}};
  if (Array.isArray(v)) {{
    const schemas = [], settings = [], seen = new Set();
    v.forEach(r => {{
      const sn = r.schema_name || r.key || "";
      if (sn && !seen.has(sn)) {{ seen.add(sn);
        schemas.push({{id: r.id, name: sn, existing: !!r.existing, source: r.source,
                      version: r.version, columns: r.columns || []}}); }}
      settings.push({{id: (r.id || 0) + 100000, key: r.key, schema_name: sn,
                     version: r.version || 1, existing: !!r.existing, source: r.source, note: r.note}});
    }});
    return {{schemas: schemas, settings: settings}};
  }}
  return {{schemas: (v.schemas || []).map(x => ({{columns: [], ...x}})),
          settings: (v.settings || []).slice()}};
}}

const state = {{
  events: (DATA.events || []).map(x => ({{params: [], ...x}})),
  player_fields: (DATA.player_fields || []).slice(),
  feature_settings: normalizeFs(DATA.feature_settings),
  resources: (DATA.resources || []).map(x => ({{fields: [], ...x}})),
}};
// System-kind coercion applies to PROPOSAL rows only: an existing row is a read-only
// MEASUREMENT — its kind ships verbatim even when a system-named param was measured
// with a non-canonical kind (the row shows a route warning instead; a live run had
// silently retyped level string->number on Start/Finish, 2026-08-03).
state.events.forEach(r => {{ if (r.existing) return; (r.params || []).forEach(p => {{
  const t = String(p.name || "").trim();
  if (SYSTEM_PARAM_KINDS[t] !== undefined) p.kind = SYSTEM_PARAM_KINDS[t];
}}); }});
// Proposed additions (user decision 2026-08-04): an existing EVENT row may carry
// evidence-backed NEW-param proposals. Unlike the measured part they are editable,
// born UNTICKED, and ship only when ticked (append-only key proposed_params) — the
// implementation routes them through module 04's State-2 builder extension.
state.events.forEach(r => {{
  if (!(r.proposed_params || []).length) return;
  r.editing = true;  // discovered additions open the row in edit mode (user 2026-08-04)
  r.proposed_params.forEach(p => {{
    p._proposed = true;
    p.included = p.included !== false;  // born ticked; ✓ done confirms, untick drops
    const t = String(p.name || "").trim();
    if (SYSTEM_PARAM_KINDS[t] !== undefined) p.kind = SYSTEM_PARAM_KINDS[t];
  }});
}});
// Producers may mint STRING row ids ("pf-ex-1") — the contract requires unique
// non-null, not numeric. Count the max over NUMERIC ids only; string ids once drove
// this to NaN and a page-added row shipped id: null (demo-b, 2026-08-03).
let nextId = 1 + Math.max(0, ...[...state.events, ...state.player_fields,
  ...state.feature_settings.schemas, ...state.feature_settings.settings,
  ...state.resources].map(r => (typeof r.id === "number" && isFinite(r.id)) ? r.id : 0));

// A section exists on this page ONLY if its key is PRESENT in the payload — a scoped/module
// run (e.g. /kinoa resources) sends just its own section, and the page must not show (or
// allow adding to) surfaces the run is not authoring.
const CARD_IDS = {{events: "events-card", player_fields: "fields-card",
  feature_settings: "fs-card", resources: "res-card"}};
const SECTIONS_PRESENT = Object.keys(CARD_IDS).filter(k => DATA[k] != null);
Object.keys(CARD_IDS).forEach(k => {{
  if (DATA[k] == null) document.getElementById(CARD_IDS[k]).style.display = "none";
}});

function esc(s) {{ const d = document.createElement("span"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }}

// A row's EFFECTIVE kind: typing a registry wire name into a custom row live-reclassifies it —
// the predefined badge appears and the export carries kind="predefined" (the producer then
// extends the existing predefined builder instead of creating a custom mirror). The name stays
// editable for such rows (only payload-declared predefined rows lock their name).
function isPredefName(n) {{ return PREDEFINED_EVENT_WIRE_NAMES.includes(String(n || "").trim().toLowerCase()); }}
function isDebugName(n) {{ return DEBUG_WIRE_NAMES.includes(String(n || "").trim().toLowerCase()); }}
function isSdkAutomatic(n) {{ return SDK_AUTOMATIC_WIRE_NAMES.includes(String(n || "").trim().toLowerCase()); }}
function effectiveKind(r) {{
  // Existing rows are MEASUREMENTS — their kind ships from code and is never
  // re-tagged by registry name (a custom mirror may legally collide with a
  // predefined wire name; a live run badged both level_up rows "predefined").
  if (r.existing) return r.kind || "custom";
  if (r.kind === "debug" || r.kind === "sdk" || isDebugName(r.name)) return "debug";
  if (r.kind === "predefined" || isPredefName(r.name)) return "predefined";
  return r.kind || "custom";
}}
// Mirrors .NET JsonNamingPolicy.SnakeCaseLower (the producer's registered-path
// derivation): acronym runs split before their last capital — XPBonus -> xp_bonus,
// HTTPServer -> http_server, MaxHP -> max_hp. Dots (nested paths) pass through.
function snake(s) {{ return String(s || "").replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
  .replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase(); }}
// Field NAME must be a dot-separated C# property chain — it ships byte-for-byte
// into code as identifiers (resource keys already get the same class of rule).
const FIELD_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;
// Registered-path charset (server rule): letter first; letters, digits, _, -, dots.
const FIELD_PATH_RE = /^[A-Za-z][A-Za-z0-9_\-]*(\.[A-Za-z0-9_\-]+)*$/;

// Re-render destroys every node — remember the focused input and caret so
// live-validated typing doesn't drop focus.
function render() {{
  if (VERSION_MISMATCH) {{
    if (!document.getElementById("vm-banner")) {{
      document.querySelector("header .bar").insertAdjacentHTML("beforeend",
        '<div id="vm-banner" style="color:#cf222e;font-weight:600;margin-top:0.4rem">' +
        "This page is OLDER than the payload (payload_version " + DATA_VERSION +
        " > supported " + PAYLOAD_VERSION + ") — export is disabled; update the kinoa-dashboard " +
        "plugin and re-run.</div>");
    }}
    // The whole page is refused, not just the export — add buttons would mutate
    // state that never renders (and each click used to stack another banner).
    ["download", "copy", "add-event", "add-field", "add-res"].forEach(id => {{
      const b = document.getElementById(id); if (b) b.disabled = true;
    }});
    return;
  }}
  const active = document.activeElement;
  const focusId = active && active.dataset ? active.dataset.fid : null;
  const selStart = focusId && "selectionStart" in active ? active.selectionStart : null;
  renderEvents(); renderFields(); renderFs(); renderResources(); renderCounter();
  // ANY visible validation error blocks the export — an invalid plan must never
  // become a hand-back (user rule 2026-07-28).
  const errs = document.querySelectorAll("input.bad, select.bad").length;
  // ✓ done is the COMPLETENESS signal: a half-typed name is often perfectly valid
  // (race_fin mid-typing), so validity alone can't see an unfinished edit. Any open
  // editor on any surface blocks the export until confirmed (user decision 2026-08-04).
  const openRows = [...state.events, ...state.player_fields,
    ...state.feature_settings.schemas, ...state.feature_settings.settings,
    ...state.resources].filter(r => r.editing === true && inc(r)).length;
  document.getElementById("download").disabled = errs > 0 || openRows > 0;
  document.getElementById("copy").disabled = errs > 0 || openRows > 0;
  if (errs > 0) {{
    document.getElementById("counter").textContent +=
      "  \u00b7  " + errs + " validation error(s) — fix to enable export";
  }}
  if (openRows > 0) {{
    document.getElementById("counter").textContent +=
      "  \u00b7  " + openRows + " row(s) open for editing — tap \u2713 done to confirm";
  }}
  if (focusId) {{
    const el = document.querySelector('[data-fid="' + focusId + '"]');
    if (el) {{ el.focus(); if (selStart != null && "setSelectionRange" in el) el.setSelectionRange(selStart, selStart); }}
  }}
}}

function textInput(value, fid, oninput, opts = {{}}) {{
  const inp = document.createElement("input");
  inp.type = "text"; inp.value = value || ""; inp.dataset.fid = fid;
  if (opts.placeholder) inp.placeholder = opts.placeholder;
  if (opts.size) inp.size = opts.size;
  if (opts.maxlength) inp.maxLength = opts.maxlength;
  if (opts.bad) inp.className = "bad";
  else if (opts.warn) inp.className = "warnp";
  // The validation hint shows only while the input is actually red/amber — a healthy
  // field's hover reveals just its full value (user feedback 2026-07-28).
  const hoverTitle = [(opts.bad || opts.warn) ? opts.title : "", value ? String(value) : ""]
    .filter(Boolean).join("\n");
  if (hoverTitle) inp.title = hoverTitle;
  inp.addEventListener("input", e => {{ oninput(e.target.value); render(); }});
  return inp;
}}

function kindSelect(kinds, value, onchange, fid) {{
  const sel = document.createElement("select");
  if (fid) sel.dataset.fid = fid;
  // A value outside the closed vocabulary (absent, or producer drift tolerated by
  // contract clause 1) must be an explicit red choice — the browser would otherwise
  // DISPLAY the first option while the state and export keep the stale value.
  if (!kinds.includes(value)) {{
    const o = document.createElement("option"); o.value = "";
    o.textContent = value ? "(unsupported: " + value + ")" : "(choose kind)";
    o.selected = true; sel.appendChild(o); sel.className = "bad";
  }}
  kinds.forEach(k => {{ const o = document.createElement("option"); o.value = k; o.textContent = k;
    if (k === value) o.selected = true; sel.appendChild(o); }});
  sel.addEventListener("change", e => {{ onchange(e.target.value); render(); }});
  return sel;
}}

function head(row, label, opts = {{}}) {{
  const div = document.createElement("div"); div.className = "grid";
  if (!row.existing) {{
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.className = "inc";
    cb.dataset.fid = "inc-" + (row.id || Math.abs(JSON.stringify(row).length));
    cb.checked = inc(row); cb.title = "include in the plan (unticked = left out, nothing is deleted)";
    cb.addEventListener("change", e => {{ row.included = e.target.checked; render(); }});
    div.appendChild(cb);
  }}
  const badge = document.createElement("span");
  badge.className = "badge " + (row.existing ? "b-existing" : "b-new");
  // Events existing rows carry a proposals section — the flat "edit code-first"
  // wording would contradict it (user question 2026-08-04).
  badge.textContent = row.existing
    ? (row.params !== undefined ? "already in code" : "already in code — edit code-first")
    : label;
  if (row.existing && row.params !== undefined) {{
    badge.title = "measured part is read-only (edit code-first); ✎ opens the additions "
                + "editor — ticked additions ship via a builder extension";
  }}
  div.appendChild(badge);
  const ek = row.params !== undefined ? effectiveKind(row) : row.kind;
  if (ek === "predefined") {{
    const b = document.createElement("span"); b.className = "badge b-predef"; b.textContent = "predefined";
    b.title = "predefined Kinoa event — wired via the game's existing builder (e.g. PaymentEventData); " +
              "params attach as custom_params. It will NOT be created as a separate user event.";
    div.appendChild(b);
  }} else if (ek === "debug") {{
    const b = document.createElement("span"); b.className = "badge b-debug"; b.textContent = "debug";
    b.title = "debug telemetry — emitted by the SDK/backend itself, never sent from app code; " +
              "there is nothing to implement, this row will be skipped.";
    div.appendChild(b);
  }} else if (ek === "custom" && row.params !== undefined) {{
    const b = document.createElement("span"); b.className = "badge b-user"; b.textContent = "user";
    b.title = "user event — the game's own event, sent from app code; created on the dashboard " +
              "with type USER.";
    div.appendChild(b);
  }}
  if (row.source) {{
    const s = document.createElement("span"); s.className = "muted"; s.textContent = row.source;
    div.appendChild(s);
  }}
  const pencilShown = opts.collapsible && inc(row)
    && (!row.existing || opts.existingEditable === true);
  if (pencilShown) {{
    const ed = document.createElement("button"); ed.className = "ghost pencil";
    ed.dataset.fid = "ed-" + (row.id || "");
    ed.textContent = opts.expanded ? "✓ done" : "✎ edit";
    ed.title = opts.expanded ? "collapse (stays open while the row has errors)" : "open the row for editing";
    ed.addEventListener("click", () => {{ row.editing = !opts.expanded; render(); }});
    div.appendChild(ed);
  }}
  // ✕ only for rows created by this page session's "+ add" buttons (_pageNew is
  // page-local and never ships) — measured candidates keep checkbox semantics, and a
  // round-tripped row loses deletability by design (user decision 2026-08-03).
  if (row._pageNew && !row.existing && opts.onRemove) {{
    const rm = document.createElement("button"); rm.className = "ghost remove";
    rm.dataset.fid = "rm-" + (row.id || "");
    rm.textContent = "✕ remove";
    rm.title = "delete this row — available only for rows just added on this page "
             + "(measured candidates use the checkbox instead)";
    if (!pencilShown) rm.style.marginLeft = "auto";
    rm.addEventListener("click", opts.onRemove);
    div.appendChild(rm);
  }}
  return div;
}}

// Select-first: the checkbox is the primary decision. `included` / `editing` are
// page-local flags — they never ship in the hand-back (stripLocal at export).
const inc = r => r.included !== false;

// A row may render COLLAPSED only while it is valid — a hidden red input would blind
// the export gate (the exact bug class fixed for debug-collapsed params). These
// predicates mirror the expanded inputs' bad-conditions.
function eventRowInvalid(r, dup) {{
  if (!r.existing
      && (!String(r.name || "").trim() || dup(r.name) || String(r.name || "").length > 30)) return true;
  const ek = effectiveKind(r);
  if (ek === "debug" || (ek === "predefined" && isSdkAutomatic(r.name) && INTEGRATION_TYPE === "SDK")) return false;
  const live = ((r.params || []).concat(r.proposed_params || []))
    .filter(p => p.included !== false);
  const pdup = dupIn(live, "name");
  return live.some(p =>
    !String(p.name || "").trim() || pdup(p.name) || String(p.name || "").length > 30
    || !EVENT_PARAM_KINDS.includes(p.kind)
    || (p.kind === "enumeration" && (!String(p.extra || "").trim() || enumValuesTooLong(p.extra))));
}}
function fieldTakenName(r, pathOf) {{
  // Name taken on the dashboard by a DIFFERENT field (same-path matches are handled
  // as predefined/existing routes, not collisions).
  const n = String(r.name || "").trim().toLowerCase();
  return !!n && FR_NAMES.has(n)
    && FR_PREDEF[pathOf(r)] === undefined && !FR_CUSTOM_PATHS.has(pathOf(r));
}}
// A registered path is a LEAF — no other field's path may sit strictly inside it
// (Wallet.Gold vs Wallet.Gold.Price: Gold cannot be a value and an object at once).
function pathNodeConflict(path, allPaths) {{
  return !!path && allPaths.some(o => o !== path
    && (o.startsWith(path + ".") || path.startsWith(o + ".")));
}}
function pathSegMismatch(r, pathOf) {{
  // A dotted override maps PER-SEGMENT onto the property chain ([JsonPropertyName]
  // per segment) — nesting depth comes from nested properties, never from the string.
  return pathOf(r).split(".").length !== String(r.name || "").trim().split(".").length;
}}
function fieldRowInvalid(r, dup, pathDup, pathOf, nodeConf) {{
  if (FR_PREDEF[pathOf(r)] !== undefined) {{
    // predefined dashboard field: valid candidate; only name-shape rules apply
    return !String(r.name || "").trim() || dup(r.name)
      || !FIELD_NAME_RE.test(String(r.name || "").trim()) || String(r.name || "").length > 30;
  }}
  return !String(r.name || "").trim() || dup(r.name) || pathDup(r)
    || FR_CALC[pathOf(r)] !== undefined || fieldTakenName(r, pathOf)
    || !FIELD_NAME_RE.test(String(r.name || "").trim())
    || !FIELD_PATH_RE.test(pathOf(r)) || pathSegMismatch(r, pathOf)
    || (nodeConf && nodeConf(r))
    || String(r.name || "").length > 30 || pathOf(r).length > 100
    || !FIELD_KINDS.includes(r.kind)
    || (r.kind === "enumeration" && (!String(r.extra || "").trim() || enumValuesTooLong(r.extra)));
}}
function fsSchemaRowInvalid(r, sdup) {{
  const cols = (r.columns || []).filter(c => c.included !== false);
  if (!String(r.name || "").trim() || sdup(r.name) || String(r.name || "").length > 255
      || !cols.length) return true;
  const cdup = dupIn(cols, "name");
  return cols.some(c =>
    !String(c.name || "").trim() || cdup(c.name) || isReservedFsColumn(c.name)
    || String(c.name || "").length > 100 || !FS_COLUMN_KINDS.includes(c.kind));
}}
function resRowInvalid(r, dup, ndup) {{
  if (!RESOURCE_KEY_RE.test(String(r.key || "")) || dup(r.key)
      || String(r.key || "").length > 100) return true;
  if (!String(r.name || "").trim() || ndup(r.name) || String(r.name || "").length > 100) return true;
  if (String(r.description || "").length > 100) return true;
  const liveF = (r.fields || []).filter(f => f.included !== false);
  const fdup = dupIn(liveF, "name");
  return liveF.some(f =>
    !RES_FIELD_NAME_RE.test(String(f.name || "")) || fdup(f.name)
    || String(f.name || "").length > 100
    || !RESOURCE_FIELD_TYPES.includes(f.field_type)
    || (f.field_type === "enumeration" && resEnumBad(f))
    || resDefaultBad(f)
    || String(f.description || "").includes(":"));
}}
function fsSettingRowInvalid(r, kdup, schemaNames) {{
  return !String(r.key || "").trim() || kdup(r.key) || String(r.key || "").length > 100
    || !r.schema_name || !schemaNames.includes(r.schema_name);
}}
// Expanded iff: new + included + (explicitly editing OR invalid — red must stay visible).
// STICKY: an auto-expanded (invalid) row is stamped editing=true, so fixing the last
// error never collapses it mid-typing (focus theft / truncated input); only the
// explicit "done" collapses — and an invalid row just re-expands.
function expandedRow(r, invalidFn, allowExisting) {{
  const open = (allowExisting === true || !r.existing) && inc(r)
    && (r.editing === true || invalidFn());
  if (open) r.editing = true;
  return open;
}}

// The bad-predicates OR several conditions; the tooltip must name the one that
// actually fired (a duplicate used to show "maximum 30 characters").
function firstBad(pairs, fallback) {{
  for (const pr of pairs) if (pr[0]) return pr[1];
  return fallback;
}}

function dupNames(rows, key) {{
  const seen = new Map();
  rows.forEach(r => {{ const n = String(r[key] || "").trim().toLowerCase();
    seen.set(n, (seen.get(n) || 0) + 1); }});
  return n => n && seen.get(String(n).trim().toLowerCase()) > 1;
}}

function dupIn(items, key) {{ return dupNames(items || [], key); }}

// Resource-field carrier rules (module 14 doc-block grammar): tokens split on ':',
// so ':' in a name/default/description is unrepresentable in KinoaResources.cs;
// enum values also reject '=' (the values token is "the comma-bearing token without
// a '='"). Names double as JSON body keys — resource-key charset applies.
const RES_FIELD_NAME_RE = /^[a-zA-Z][a-zA-Z0-9_-]*$/;
function resEnumBad(f) {{
  const vals = f.enumeration_values || [];
  return !vals.length || vals.some(v => v.includes(":") || v.includes("="));
}}
function resDefaultBad(f) {{
  const d = String(f.default || "");
  if (!d) return false;
  if (d.includes(":")) return true;
  const t = f.field_type;
  if (t === "number") return !/^-?\d+(\.\d+)?$/.test(d.trim());
  if (t === "boolean") return !/^(true|false)$/i.test(d.trim());
  if (t === "enumeration") return !(f.enumeration_values || []).includes(d.trim());
  return false;
}}

// FS reserved column namespace: "filter: ..." props are IncludeFilters READERS (configuration-
// level, bound to Player Fields at config-fill time) and "<...>" is unreplaced scaffold — the
// planner drops both from schema plans, so authoring them here would promise a column that
// never materializes. Mirror of the planner's _is_filter_or_placeholder.
// Enumeration values: each value must be 50 characters or less (backend-confirmed).
function enumValuesTooLong(csv) {{
  return String(csv || "").split(",").some(x => x.trim().length > 50);
}}

function isReservedFsColumn(n) {{
  const t = String(n || "").trim().toLowerCase();
  return t.startsWith("filter:") || String(n || "").includes("<");
}}

function renderEvents() {{
  const host = document.getElementById("events"); host.innerHTML = "";
  if (REGISTRIES_SOURCE === "fallback") {{
    host.insertAdjacentHTML("beforeend",
      '<div class="muted" style="margin:0.2rem 0 0.4rem">\u26a0 event registries come from the ' +
      "SDK's offline tables (live listings unavailable at generation) — live tagging may be " +
      'incomplete: a backend-added predefined/debug event may show here as "user".</div>');
  }}
  const dup = dupNames(state.events.filter(r => r.existing || inc(r)), "name");
  state.events.forEach((r, i) => {{
    const expanded = expandedRow(r, () => eventRowInvalid(r, dup), true);
    const div = document.createElement("div");
    // The locked tint dims the additions editor too — an existing row in ✎ edit mode
    // renders untinted (user 2026-08-04); collapsed keeps the dim.
    div.className = "row" + (r.existing && !expanded ? " locked" : "")
      + (!r.existing && !inc(r) ? " excluded" : "");
    div.appendChild(head(r, "new event", {{collapsible: true, expanded: expanded,
      existingEditable: true,
      onRemove: () => {{ state.events.splice(state.events.indexOf(r), 1); render(); }}}}));
    if (!r.existing && !expanded) {{
      const cg = document.createElement("div"); cg.className = "grid";
      const ek = effectiveKind(r);
      // The summary mirrors the HAND-BACK, not the raw state: debug / SDK-composed rows
      // ship params: [], so listing their params here would misrepresent the plan.
      const skipNote = ek === "debug"
        ? " <span class=\"muted\">skipped at implementation (SDK/backend telemetry)</span>"
        : (ek === "predefined" && isSdkAutomatic(r.name) && INTEGRATION_TYPE === "SDK")
          ? " <span class=\"muted\">params composed by the SDK (not redefinable)</span>" : "";
      cg.innerHTML = "<code>" + esc(r.name || "(unnamed)") + "</code>" + skipNote;
      if (r.note) cg.insertAdjacentHTML("beforeend", " <span class=\"muted\">" + esc(r.note) + "</span>");
      div.appendChild(cg);
      // Same read-only table an existing row shows — collapsed and existing are the
      // same kind of view (user feedback 2026-07-29), so they read the same.
      if (!skipNote && (r.params || []).filter(p => p.included !== false).length) {{
        const ct = document.createElement("table"); ct.className = "sub";
        (r.params || []).filter(p => p.included !== false).forEach(p => {{
          const sys = SYSTEM_EVENT_PARAM_NAMES.includes(String(p.name || "").trim());
          const tr = document.createElement("tr");
          tr.innerHTML = "<td><code>" + esc(p.name) + "</code>" +
            (sys ? ' <span class="badge b-system">system</span>' : "") + "</td><td>" +
            esc(p.kind) + "</td><td>" + esc(p.kind === "enumeration" ? (p.extra || "") : "") + "</td>";
          ct.appendChild(tr);
        }});
        div.appendChild(ct);
      }}
      host.appendChild(div); return;
    }}
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "<code>" + esc(r.name) + "</code>";
    }} else {{
      // The name is editable even on predefined-tagged NEW rows: renaming it away from
      // the registry live-downgrades the row to a user event (badge follows) — the
      // symmetric twin of typing a registry name into a user row.
      g.appendChild(textInput(r.name, "e" + i + "-name",
        v => {{ r.name = v; if (r.kind === "predefined" && !isPredefName(v)) r.kind = "custom"; }},
        {{placeholder: "event_name", size: 28, maxlength: 30,
          bad: !String(r.name || "").trim() || dup(r.name) || String(r.name || "").length > 30,
          title: firstBad([
            [!String(r.name || "").trim(), "the event name is required"],
            [dup(r.name), "duplicate event name on this page"],
          ], "maximum 30 characters")}}));
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    // Debug-tagged rows get NO param editor: nothing will be implemented for them
    // (the row is skipped), so authoring params would be a dead-end promise. State is
    // preserved — rename away from the debug name and the params (and editor) return.
    if (effectiveKind(r) === "debug") {{
      const note = document.createElement("div"); note.className = "muted";
      note.textContent = "debug telemetry (emitted by the SDK/backend) — params are not applicable; this row will be skipped at implementation.";
      div.appendChild(note);
      host.appendChild(div);
      return;
    }}
    // SDK-automatic PREDEFINED (install, player_update, *_milestones): the tag stays
    // predefined, but under an SDK integration the SDK itself composes these events —
    // their params are NOT redefinable from game code (an API integration may extend them,
    // so the editor stays for INTEGRATION_TYPE === "API").
    if (effectiveKind(r) === "predefined" && isSdkAutomatic(r.name) && INTEGRATION_TYPE === "SDK") {{
      const note = document.createElement("div"); note.className = "muted";
      note.textContent = "sent automatically by the SDK — its params are not redefinable in an SDK integration (API integrations may extend them).";
      div.appendChild(note);
      host.appendChild(div);
      return;
    }}
    const tbl = document.createElement("table"); tbl.className = "sub";
    const allParams = (r.params || [])
      .concat(r.existing ? (r.proposed_params = r.proposed_params || []) : []);
    const pdup = dupIn(allParams.filter(p => p.included !== false), "name");
    let propHeaderDone = false;
    allParams.forEach((p, j) => {{
      if (p._proposed && !expanded && p.included === false) return;
      if (p._proposed && !propHeaderDone) {{
        propHeaderDone = true;
        const hr = document.createElement("tr");
        hr.innerHTML = '<td colspan="4" class="muted">＋ proposed additions — found near the '
          + 'call sites but NOT wired in code; unticked = not implemented, ticked ships via '
          + 'a builder extension</td>';
        tbl.appendChild(hr);
      }}
      const tr = document.createElement("tr");
      const td = t => {{ const c = document.createElement("td"); c.appendChild(t); return c; }};
      if (!r.existing || (p._proposed && expanded)) {{
        const pcb = document.createElement("input"); pcb.type = "checkbox"; pcb.className = "inc";
        pcb.checked = p.included !== false; pcb.title = "include this param";
        pcb.addEventListener("change", e => {{ p.included = e.target.checked; render(); }});
        tr.appendChild(td(pcb));
        if (p.included === false) {{
          tr.className = "removedp";
          tr.insertAdjacentHTML("beforeend", "<td><code>" + esc(p.name || "(unnamed)") +
            "</code></td><td>" + esc(p.kind) + "</td><td class=\"muted\">left out of the plan</td>");
          tbl.appendChild(tr);
          return;
        }}
      }}
      if (r.existing && p._proposed && !expanded) {{
        // ✓ done view: the confirmed addition reads like a measured param, marked.
        tr.innerHTML = "<td><code>" + esc(p.name)
          + '</code> <span class="badge b-new">addition</span></td><td>' + esc(p.kind)
          + "</td><td>" + esc(p.kind === "enumeration" ? (p.extra || "") : "") + "</td>";
        tbl.appendChild(tr);
        return;
      }}
      if (r.existing && !p._proposed) {{
        const sysEx = SYSTEM_EVENT_PARAM_NAMES.includes(String(p.name || "").trim());
        tr.innerHTML = "<td><code>" + esc(p.name) + "</code>" +
          (sysEx ? ' <span class="badge b-system">system</span>' : "") +
          "</td><td>" + esc(p.kind) + "</td><td>" +
          (sysEx
            ? '<span class="muted">reserved system name measured as a custom param — the '
              + 'server refuses registering it; canonical kind '
              + esc(SYSTEM_PARAM_KINDS[String(p.name || "").trim()] || "") + ', canonical route: '
              + (SYSTEM_BASE_PROP_PARAM_NAMES.includes(String(p.name || "").trim())
                 ? "the event's base-class field (SetLevel/SetPlace/Success)"
                 : "composed by the SDK — remove the custom param")
              + ". Fix code-first.</span>"
            : esc(p.extra || "")) + "</td>";
      }} else {{
        // A reserved system name is a VALID candidate — the value just takes a different
        // ROUTE (base-class property or SDK-composed) and is never registered as a custom
        // param (the server refuses those names). Renaming is only for the case where the
        // name matches but the MEANING differs (user decision 2026-07-30).
        const sysHit = SYSTEM_EVENT_PARAM_NAMES.includes(String(p.name || "").trim());
        tr.appendChild(td(textInput(p.name, "e" + i + "-p" + j,
          v => {{ p.name = v;
                 const t = String(v || "").trim();
                 if (SYSTEM_PARAM_KINDS[t] !== undefined) p.kind = SYSTEM_PARAM_KINDS[t]; }},
          {{placeholder: "param_name", size: 20, maxlength: 30,
            bad: !String(p.name || "").trim() || pdup(p.name) || String(p.name || "").length > 30,
            title: firstBad([
              [!String(p.name || "").trim(), "the param name is required"],
              [pdup(p.name), "duplicate param name on this event"],
            ], "maximum 30 characters")}})));
        if (sysHit) {{
          // The type is PINNED by the base class — no select for system params.
          const kk = document.createElement("span"); kk.className = "muted";
          kk.textContent = p.kind + " (fixed)";
          kk.title = "the type is pinned by the event's built-in field — it must match the dashboard exactly";
          tr.appendChild(td(kk));
        }}
        if (sysHit) {{
          const sysCell = document.createElement("span");
          const sb = document.createElement("span"); sb.className = "badge b-system";
          sb.textContent = "system";
          sb.title = "reserved by system parameters — already built into every event; rename " +
                     "(e.g. time -> race_duration) ONLY if you mean a different concept";
          sysCell.appendChild(sb);
          const sn = document.createElement("span"); sn.className = "muted";
          // The ROUTE branches by integration type: the SDK carries these via the base
          // class / composes them itself; an API integration supplies the values
          // directly in the event body (user decision 2026-07-30).
          sn.textContent = INTEGRATION_TYPE === "API"
            ? " built-in system field — your integration supplies its value directly in the event body; never registered as a custom param"
            : (SYSTEM_BASE_PROP_PARAM_NAMES.includes(String(p.name || "").trim())
               ? " built-in event field — the value rides the base class (SetLevel/SetPlace/Success); no dashboard registration"
               : " composed by the SDK automatically — nothing to implement");
          sysCell.appendChild(sn);
          tr.appendChild(td(sysCell));
        }}
        // Enum-values input shows ONLY while kind === enumeration, but the VALUE is
        // preserved on kind changes (discovery-found candidates must survive a toggle);
        // the EXPORT strips it for non-enumeration kinds instead.
        if (!sysHit) tr.appendChild(td(kindSelect(EVENT_PARAM_KINDS, p.kind, v => p.kind = v, "e" + i + "-p" + j + "-k")));
        if (!sysHit && p.kind === "enumeration") {{
          tr.appendChild(td(textInput(p.extra, "e" + i + "-p" + j + "-x", v => p.extra = v,
            {{placeholder: "a, b, c", size: 18,
              bad: !String(p.extra || "").trim() || enumValuesTooLong(p.extra),
              title: firstBad([
                [!String(p.extra || "").trim(), "an enumeration needs at least one value"],
              ], "each value must be 50 characters or less")}})));
        }}
        if (p._pNew) {{
          const rm = document.createElement("button"); rm.className = "ghost remove";
          rm.textContent = "✕";
          rm.title = "delete this param — available only for params just added on this page "
                   + "(discovered params use the checkbox instead)";
          rm.addEventListener("click", () => {{
            const list = p._proposed ? r.proposed_params : r.params;
            list.splice(list.indexOf(p), 1); render();
          }});
          tr.appendChild(td(rm));
        }}
      }}
      tbl.appendChild(tr);
    }});
    div.appendChild(tbl);
    if (!r.existing) {{
      const add = document.createElement("button"); add.className = "ghost"; add.textContent = "＋ param";
      add.addEventListener("click", () => {{ r.params.push({{name: "", kind: "string", extra: "", _pNew: true}}); render(); }});
      div.appendChild(add);
    }} else if (expanded) {{
      const add = document.createElement("button"); add.className = "ghost";
      add.textContent = "＋ param";
      add.title = "add a NEW param to this already-wired event — implemented as a builder "
                + "extension; the value source is confirmed at a wiring gate";
      add.addEventListener("click", () => {{ (r.proposed_params = r.proposed_params || [])
        .push({{name: "", kind: "string", extra: "", included: true, _proposed: true, _pNew: true}}); render(); }});
      div.appendChild(add);
    }}
    host.appendChild(div);
  }});
}}

function renderFields() {{
  const host = document.getElementById("player_fields"); host.innerHTML = "";
  const shipped = state.player_fields.filter(r => r.existing || inc(r));
  const dup = dupNames(shipped, "name");
  const pathCount = new Map();
  const pathOf = r => String(r.path || "").trim() || snake(String(r.name || "").trim());
  shipped.forEach(r => {{
    const p = pathOf(r);
    if (p) pathCount.set(p, (pathCount.get(p) || 0) + 1);
  }});
  const pathDup = r => {{ const p = pathOf(r); return !!p && pathCount.get(p) > 1; }};
  const allPaths = shipped.map(pathOf).filter(Boolean);
  const nodeConf = r => pathNodeConflict(pathOf(r), allPaths);
  state.player_fields.forEach((r, i) => {{
    const expanded = expandedRow(r, () => fieldRowInvalid(r, dup, pathDup, pathOf, nodeConf));
    const div = document.createElement("div");
    div.className = "row" + (r.existing ? " locked" : "") + (!r.existing && !inc(r) ? " excluded" : "");
    div.appendChild(head(r, "new field", {{collapsible: true, expanded: expanded,
      onRemove: () => {{ state.player_fields.splice(state.player_fields.indexOf(r), 1); render(); }}}}));
    if (!r.existing && !expanded) {{
      const cg = document.createElement("div"); cg.className = "grid";
      cg.innerHTML = "<code>" + esc(r.name || "(unnamed)") + "</code> <span class=\"muted\">" +
        esc(r.kind) + (r.kind === "enumeration" && r.extra ? " (" + esc(r.extra) + ")" : "") +
        " · → path: " + esc(pathOf(r)) +
        (r.description ? " · " + esc(r.description) : "") + "</span>";
      if (r.note) cg.insertAdjacentHTML("beforeend", " <span class=\"muted\">" + esc(r.note) + "</span>");
      div.appendChild(cg); host.appendChild(div); return;
    }}
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "<code>" + esc(r.name) + "</code> <span class=\"muted\">" + esc(r.kind) + "</span>";
    }} else {{
      // Renaming re-derives the registration: the producer-measured `path` was a
      // measurement of the OLD name ([JsonPropertyName] incl.) — clear it so the dup
      // gate, preview and hand-back all follow the new name instead of a stale pair.
      const frPredef = FR_PREDEF[pathOf(r)] !== undefined;
      const frCalc = FR_CALC[pathOf(r)] !== undefined;
      const frTaken = fieldTakenName(r, pathOf);
      g.appendChild(textInput(r.name, "f" + i, v => {{ r.name = v; delete r.path; }},
        {{placeholder: "Wallet.Gold", size: 26, maxlength: 30,
          bad: !String(r.name || "").trim() || dup(r.name) || (!frPredef && pathDup(r))
               || frCalc || frTaken
               || !FIELD_NAME_RE.test(String(r.name || "").trim())
               || String(r.name || "").length > 30 || (!frPredef && pathOf(r).length > 100),
          title: firstBad([
            [frCalc, "this path is a CALCULATED dashboard field — computed server-side, "
                     + "the game cannot write it; rename if you meant a different value"],
            [frTaken, "this name is already taken on the dashboard (names are unique "
                      + "across ALL statuses); rename"],
            [!String(r.name || "").trim(), "the field name is required"],
            [dup(r.name), "duplicate field name on this page"],
            [!frPredef && pathDup(r), "another field registers the SAME path — rename one "
                                      + "(the registered snake path must be unique)"],
            [!FIELD_NAME_RE.test(String(r.name || "").trim()),
             "must be a dot-separated C# property chain (letters, digits, _)"],
            [String(r.name || "").length > 30, "maximum 30 characters"],
          ], "the registered snake path must be unique and 100 characters or less")}}));
      if (frPredef) {{
        const b = document.createElement("span"); b.className = "badge b-predef";
        b.textContent = "predefined";
        b.title = "built-in dashboard player field — the sync ACTIVATES it (never creates); "
                  + "the value is set via the SDK's own state route (module 02)";
        g.appendChild(b);
        if (FR_PREDEF[pathOf(r)]) {{
          r.kind = FR_PREDEF[pathOf(r)];
          const kk = document.createElement("span"); kk.className = "muted";
          kk.textContent = r.kind + " (fixed)";
          kk.title = "the kind is pinned by the dashboard's predefined field";
          g.appendChild(kk);
        }} else {{
          g.appendChild(kindSelect(FIELD_KINDS, r.kind, v => r.kind = v, "f" + i + "-k"));
        }}
      }} else {{
        g.appendChild(kindSelect(FIELD_KINDS, r.kind, v => r.kind = v, "f" + i + "-k"));
      }}
      // Path is a first-class input: auto-derived from the name (editing the name
      // resets it); a manual edit stores an override — the implementation carries it
      // as [JsonPropertyName] on the property. Checked against the registry too.
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">\u2192 path</span>");
      g.appendChild(textInput(pathOf(r), "f" + i + "-p",
        v => {{ const t = String(v || "").trim();
               if (!t || t === snake(String(r.name || "").trim())) delete r.path;
               else r.path = t; }},
        {{placeholder: "wallet.gold", size: 18,
          bad: !frPredef && (!FIELD_PATH_RE.test(pathOf(r)) || pathOf(r).length > 100
               || pathDup(r) || frCalc || pathSegMismatch(r, pathOf) || nodeConf(r)),
          title: firstBad([
            [frCalc, "this path is a CALCULATED dashboard field — computed server-side; "
                     + "pick another path or rename"],
            [!frPredef && pathDup(r), "duplicate registered path — another field (incl. "
                                      + "existing ones) already uses it"],
          ], frCalc ? "" : nodeConf(r)
                   ? "leaf/object conflict: another field's path sits inside this one "
                     + "(Wallet.Gold vs Wallet.Gold.Price — Gold cannot be a value AND an "
                     + "object); restructure as sibling leaves (Wallet.Gold.Amount + "
                     + "Wallet.Gold.Price)"
                 : pathSegMismatch(r, pathOf)
                   ? "the override maps per-segment onto the property chain — segment counts "
                     + "must match (nesting depth comes from nested properties: name "
                     + "Wallet.Gold can map to wallet.gold_amount, not to a deeper path)"
                   : "letter first; letters, digits, _, - and dot separators; unique "
                     + "across existing fields; maximum 100 characters")}}));
      if (!frPredef && FR_CUSTOM_PATHS.has(pathOf(r))) {{
        const ex = document.createElement("span"); ex.className = "muted";
        ex.textContent = "already registered on the dashboard — the sync will activate/skip, not create";
        g.appendChild(ex);
      }}
      if (!frPredef && r.kind === "enumeration") {{
        g.appendChild(textInput(r.extra, "f" + i + "-x", v => r.extra = v,
          {{placeholder: "a, b, c", size: 16,
            bad: !String(r.extra || "").trim() || enumValuesTooLong(r.extra),
            title: firstBad([
              [!String(r.extra || "").trim(), "an enumeration needs at least one value"],
            ], "each value must be 50 characters or less")}}));
      }}
      if (!frPredef && !frCalc) {{
        g.appendChild(textInput(r.description, "f" + i + "-d", v => r.description = v,
          {{placeholder: "description (optional)", size: 24}}));
      }}
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    host.appendChild(div);
  }});
}}

function renderFs() {{
  const host = document.getElementById("feature_settings"); host.innerHTML = "";
  const fs = state.feature_settings;
  const sdup = dupNames(fs.schemas.filter(r => r.existing || inc(r)), "name");
  const kdup = dupNames(fs.settings.filter(r => r.existing || inc(r)), "key");
  // Unticked schemas leave the plan — settings bound to them go red "(missing)" so the
  // by-construction binding guarantee survives select-first.
  const schemaNames = fs.schemas.filter(x => x.existing || inc(x))
    .map(x => String(x.name || "")).filter(Boolean);
  const shippedSchemas = fs.schemas.filter(x => x.existing || inc(x));
  const newSchemas = new Set(shippedSchemas.filter(x => !x.existing).map(x => String(x.name || "")));

  host.insertAdjacentHTML("beforeend",
    '<div class="muted" style="margin:0.2rem 0 0.4rem"><b>Schemas</b> — column shapes; ONE schema may back several setting keys (columns are defined here once)</div>');
  fs.schemas.forEach((r, i) => {{
    const expanded = expandedRow(r, () => fsSchemaRowInvalid(r, sdup));
    const div = document.createElement("div");
    div.className = "row" + (r.existing ? " locked" : "") + (!r.existing && !inc(r) ? " excluded" : "");
    div.appendChild(head(r, "new schema", {{collapsible: true, expanded: expanded,
      onRemove: () => {{ fs.schemas.splice(fs.schemas.indexOf(r), 1); render(); }}}}));
    if (!r.existing && !expanded) {{
      const cg = document.createElement("div"); cg.className = "grid";
      cg.innerHTML = "schema <code>" + esc(r.name || "(unnamed)") + "</code>";
      if (r.note) cg.insertAdjacentHTML("beforeend", " <span class=\"muted\">" + esc(r.note) + "</span>");
      div.appendChild(cg);
      const ct = document.createElement("table"); ct.className = "sub";
      (r.columns || []).filter(c => c.included !== false).forEach(c => {{
        const tr = document.createElement("tr");
        tr.innerHTML = "<td><code>" + esc(c.name) + "</code></td><td>" + esc(c.kind) + "</td>";
        ct.appendChild(tr);
      }});
      div.appendChild(ct); host.appendChild(div); return;
    }}
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "schema <code>" + esc(r.name) + "</code>";
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">schema</span>");
      // Server rules (backend-confirmed 2026-07-28): a schema must contain minimum
      // 1 column; the name is capped at 255 characters. A zero-column schema flags the
      // name input, which also blocks the export via the global validation gate.
      // Renaming a schema deliberately does NOT auto-rebind its settings: they turn red
      // "(missing: old)" and the developer explicitly re-picks or restores the old name —
      // the export stays blocked until resolved (user decision 2026-07-28).
      const noColumns = !(r.columns || []).length;
      g.appendChild(textInput(r.name, "ss" + i, v => r.name = v,
        {{placeholder: "SchemaName", size: 22, maxlength: 255,
          bad: !String(r.name || "").trim() || sdup(r.name)
               || String(r.name || "").length > 255 || noColumns,
          title: firstBad([
            [noColumns, "Schema should contain minimum 1 column (server rule)"],
            [!String(r.name || "").trim(), "the schema name is required"],
            [sdup(r.name), "duplicate schema name on this page"],
          ], "maximum 255 characters")}}));
      // A NEW schema always wires as version 1 (module 07) — shown, never editable.
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">v1 (new schemas always start at 1)</span>");
    }}
    // Two keys wired at DIFFERENT versions of one schema is a VALID state (older
    // published versions stay resolvable for backward compatibility of old game builds)
    // — surfaced as information only; new keys inherit the highest wired version.
    const wiredVersions = [...new Set(fs.settings
      .filter(st => st.existing && String(st.schema_name || "") === String(r.name || "") && st.version != null)
      .map(st => String(st.version)))];
    if (wiredVersions.length > 1) {{
      const mv = document.createElement("span"); mv.className = "muted";
      mv.textContent = "wired at multiple versions in code (v" + wiredVersions.join(", v") +
        ") — valid for backward compatibility; new keys inherit the highest";
      g.appendChild(mv);
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    const tbl = document.createElement("table"); tbl.className = "sub";
    const cdup = dupIn((r.columns || []).filter(c => c.included !== false), "name");
    (r.columns || []).forEach((c, j) => {{
      const tr = document.createElement("tr");
      const td = t => {{ const x = document.createElement("td"); x.appendChild(t); return x; }};
      if (!r.existing) {{
        // Checkbox trial (FS): unticked column stays as a dim line — nothing is deleted.
        const ccb = document.createElement("input"); ccb.type = "checkbox"; ccb.className = "inc";
        ccb.checked = c.included !== false; ccb.title = "include this column";
        ccb.addEventListener("change", e => {{ c.included = e.target.checked; render(); }});
        tr.appendChild(td(ccb));
        if (c.included === false) {{
          tr.className = "removedp";
          tr.insertAdjacentHTML("beforeend", "<td><code>" + esc(c.name || "(unnamed)") +
            "</code></td><td>" + esc(c.kind) + "</td><td class=\"muted\">left out of the plan</td>");
          tbl.appendChild(tr);
          return;
        }}
      }}
      if (r.existing) {{
        tr.innerHTML = "<td><code>" + esc(c.name) + "</code></td><td>" + esc(c.kind) + "</td>";
      }} else {{
        const reserved = isReservedFsColumn(c.name);
        tr.appendChild(td(textInput(c.name, "ss" + i + "-c" + j, v => c.name = v,
          {{placeholder: "column", size: 20, maxlength: 100,
            bad: !String(c.name || "").trim() || cdup(c.name) || reserved
                 || String(c.name || "").length > 100,
            title: firstBad([
              [reserved, "filters are configuration-level (IncludeFilters readers), not schema columns — the operator picks them on the configuration table; unreplaced <placeholders> are scaffold"],
              [!String(c.name || "").trim(), "the column name is required"],
              [cdup(c.name), "duplicate column name in this schema"],
            ], "maximum 100 characters")}})));
        tr.appendChild(td(kindSelect(FS_COLUMN_KINDS, c.kind, v => c.kind = v, "s" + i + "-c" + j + "-k")));
        if (c.kind === "bundle_key") {{
          const h = document.createElement("span"); h.className = "muted";
          h.textContent = "values must be existing Bundle keys (letter first; letters, digits, _, -)";
          tr.appendChild(td(h));
        }}
        // No required checkbox for FS columns: the dashboard UI has no such control (a
        // SchemaDto artifact, checked 2026-07-28) and no sync logic reads it — the export
        // always carries is_required: true; the key is kept DELIBERATELY until the API
        // side drops it from the DTO.
        c.is_required = true;
      }}
      tbl.appendChild(tr);
    }});
    div.appendChild(tbl);
    if (!r.existing) {{
      const add = document.createElement("button"); add.className = "ghost"; add.textContent = "＋ column";
      add.addEventListener("click", () => {{ r.columns.push({{name: "", kind: "string", is_required: true}}); render(); }});
      div.appendChild(add);
    }}
    host.appendChild(div);
  }});
  const addS = document.createElement("button"); addS.className = "ghost"; addS.textContent = "＋ Add schema";
  addS.addEventListener("click", () => {{
    fs.schemas.push({{id: nextId++, name: "", existing: false, columns: [], editing: true,
                     _pageNew: true, source: "added on page"}});
    render();
  }});
  host.appendChild(addS);

  host.insertAdjacentHTML("beforeend",
    '<div class="muted" style="margin:0.8rem 0 0.4rem"><b>Settings (keys)</b> — the runtime download keys; each binds ONE schema from the list above</div>');
  fs.settings.forEach((r, i) => {{
    const expanded = expandedRow(r, () => fsSettingRowInvalid(r, kdup, schemaNames));
    const div = document.createElement("div");
    div.className = "row" + (r.existing ? " locked" : "") + (!r.existing && !inc(r) ? " excluded" : "");
    div.appendChild(head(r, "new setting", {{collapsible: true, expanded: expanded,
      onRemove: () => {{ fs.settings.splice(fs.settings.indexOf(r), 1); render(); }}}}));
    if (!r.existing && !expanded) {{
      const cg = document.createElement("div"); cg.className = "grid";
      const bound = shippedSchemas.find(x => String(x.name || "") === String(r.schema_name || ""));
      cg.innerHTML = "key <code>" + esc(r.key || "(unnamed)") + "</code> <span class=\"muted\">schema " +
        esc(r.schema_name || "—") + " · v" +
        esc(newSchemas.has(r.schema_name) ? 1 : ((bound && bound.version) || r.version || 1)) + "</span>";
      if (r.note) cg.insertAdjacentHTML("beforeend", " <span class=\"muted\">" + esc(r.note) + "</span>");
      div.appendChild(cg); host.appendChild(div); return;
    }}
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "key <code>" + esc(r.key) + "</code> · schema <code>" + esc(r.schema_name) +
                    "</code> · v" + esc(r.version);
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">key</span>");
      // Server rules (backend-confirmed 2026-07-28): key capped at 100 characters;
      // a setting cannot exist without a schema (the dropdown below enforces that —
      // its red state blocks the export via the global validation gate).
      g.appendChild(textInput(r.key, "sk" + i, v => r.key = v,
        {{placeholder: "FeatureKey", size: 20, maxlength: 100,
          bad: !String(r.key || "").trim() || kdup(r.key) || String(r.key || "").length > 100,
          title: firstBad([
            [!String(r.key || "").trim(), "the setting key is required"],
            [kdup(r.key), "duplicate setting key on this page"],
          ], "maximum 100 characters")}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">schema</span>");
      // Schema is a REFERENCE, not free text — pick from the schemas defined above
      // (kills dangling schema_name and shape redefinition by construction).
      const sel = document.createElement("select");
      sel.dataset.fid = "fss" + i + "-schema";
      const missing = !r.schema_name || !schemaNames.includes(r.schema_name);
      if (!schemaNames.length || missing) {{
        const o = document.createElement("option"); o.value = "";
        o.textContent = r.schema_name ? "(missing: " + r.schema_name + ")"
          : (schemaNames.length ? "(choose a schema)" : "(no schemas defined above)");
        o.selected = true; sel.appendChild(o); sel.className = "bad";
      }}
      schemaNames.forEach(n => {{
        const o = document.createElement("option"); o.value = n; o.textContent = n;
        if (n === r.schema_name) o.selected = true; sel.appendChild(o);
      }});
      sel.addEventListener("change", e => {{ r.schema_name = e.target.value; render(); }});
      g.appendChild(sel);
      const v = document.createElement("span"); v.className = "muted";
      const boundSchema = shippedSchemas.find(x => String(x.name || "") === String(r.schema_name || ""));
      v.textContent = newSchemas.has(r.schema_name)
        ? "v1 (new schema)"
        : (boundSchema && boundSchema.version
           ? "v" + boundSchema.version + " (the schema's newest wired version)"
           : "v" + (r.version || 1) + " (from code wiring)");
      g.appendChild(v);
    }}
    // Live many-keys-one-schema indicator — recomputed on every render, so it follows
    // the dropdown (a static payload note here would go stale the moment the user edits).
    const sharers = fs.settings.filter(x => x !== r && x.schema_name
      && String(x.schema_name) === String(r.schema_name || ""));
    if (sharers.length) {{
      const sh = document.createElement("span"); sh.className = "muted";
      sh.textContent = "shared schema — also used by: " + sharers.map(x => x.key || "(unnamed)").join(", ");
      g.appendChild(sh);
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    host.appendChild(div);
  }});
  const addK = document.createElement("button"); addK.className = "ghost"; addK.textContent = "＋ Add setting (key)";
  addK.addEventListener("click", () => {{
    fs.settings.push({{id: nextId++, key: "", schema_name: schemaNames[0] || "", version: 1,
                      editing: true, existing: false, _pageNew: true, source: "added on page"}});
    render();
  }});
  host.appendChild(addK);
}}

function renderResources() {{
  const host = document.getElementById("resources"); host.innerHTML = "";
  const dup = dupNames(state.resources.filter(r => r.existing || inc(r)), "key");
  const ndup = dupNames(state.resources.filter(r => r.existing || inc(r)), "name");
  state.resources.forEach((r, i) => {{
    const expanded = expandedRow(r, () => resRowInvalid(r, dup, ndup));
    const div = document.createElement("div");
    div.className = "row" + (r.existing ? " locked" : "") + (!r.existing && !inc(r) ? " excluded" : "");
    div.appendChild(head(r, "new resource", {{collapsible: true, expanded: expanded,
      onRemove: () => {{ state.resources.splice(state.resources.indexOf(r), 1); render(); }}}}));
    if (!r.existing && !expanded) {{
      const cg = document.createElement("div"); cg.className = "grid";
      cg.innerHTML = "<code>" + esc(r.key || "(unnamed)") + "</code> <span class=\"muted\">" +
        esc(r.name || "") + ((r.fields || []).length ? "" : " · key-only") + "</span>";
      if (r.note) cg.insertAdjacentHTML("beforeend", " <span class=\"muted\">" + esc(r.note) + "</span>");
      div.appendChild(cg);
      if ((r.fields || []).filter(f => f.included !== false).length) {{
        const ct = document.createElement("table"); ct.className = "sub";
        (r.fields || []).filter(f => f.included !== false).forEach(f => {{
          const tr = document.createElement("tr");
          tr.innerHTML = "<td><code>" + esc(f.name) + "</code></td><td>" + esc(f.field_type) +
            "</td><td>" + esc((f.enumeration_values || []).join(", ") || f.default || "") + "</td>";
          ct.appendChild(tr);
        }});
        div.appendChild(ct);
      }}
      host.appendChild(div); return;
    }}
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "<code>" + esc(r.key) + "</code> <span class=\"muted\">" + esc(r.name) + "</span>";
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">key</span>");
      g.appendChild(textInput(r.key, "r" + i + "-key", v => r.key = v,
        {{placeholder: "legendary_sword", size: 22, maxlength: 100,
          bad: !RESOURCE_KEY_RE.test(String(r.key || "")) || dup(r.key)
               || String(r.key || "").length > 100,
          title: firstBad([
            [dup(r.key), "duplicate resource key on this page"],
            [!RESOURCE_KEY_RE.test(String(r.key || "")),
             "letter first; letters, digits, _ and - only"],
          ], "maximum 100 characters")}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">name</span>");
      g.appendChild(textInput(r.name, "r" + i + "-name", v => r.name = v,
        {{placeholder: "Legendary Sword", size: 22, maxlength: 100,
          bad: !String(r.name || "").trim() || ndup(r.name) || String(r.name || "").length > 100,
          title: firstBad([
            [!String(r.name || "").trim(), "the resource name is required"],
            [ndup(r.name), "duplicate resource name on this page (the server also enforces "
                           + "uniqueness across ALL statuses, incl. DEPRECATED)"],
          ], "maximum 100 characters")}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">description</span>");
      g.appendChild(textInput(r.description, "r" + i + "-desc", v => r.description = v,
        {{placeholder: "optional", size: 26, maxlength: 100,
          bad: String(r.description || "").length > 100, title: "maximum 100 characters"}}));
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    const tbl = document.createElement("table"); tbl.className = "sub";
    const fdup = dupIn((r.fields || []).filter(f => f.included !== false), "name");
    (r.fields || []).forEach((f, j) => {{
      const tr = document.createElement("tr");
      const td = t => {{ const x = document.createElement("td"); x.appendChild(t); return x; }};
      if (!r.existing) {{
        const fcb = document.createElement("input"); fcb.type = "checkbox"; fcb.className = "inc";
        fcb.checked = f.included !== false; fcb.title = "include this field";
        fcb.addEventListener("change", e => {{ f.included = e.target.checked; render(); }});
        tr.appendChild(td(fcb));
        if (f.included === false) {{
          tr.className = "removedp";
          tr.insertAdjacentHTML("beforeend", "<td><code>" + esc(f.name || "(unnamed)") +
            "</code></td><td>" + esc(f.field_type) + "</td><td class=\"muted\">left out of the plan</td>");
          tbl.appendChild(tr);
          return;
        }}
      }}
      if (r.existing) {{
        tr.innerHTML = "<td><code>" + esc(f.name) + "</code></td><td>" + esc(f.field_type) +
          "</td><td>" + esc((f.enumeration_values || []).join(", ") || f.default || "") + "</td>";
      }} else {{
        tr.appendChild(td(textInput(f.name, "r" + i + "-f" + j, v => f.name = v,
          {{placeholder: "field_name", size: 16, maxlength: 100,
            bad: !RES_FIELD_NAME_RE.test(String(f.name || "")) || fdup(f.name)
                 || String(f.name || "").length > 100,
            title: firstBad([
              [fdup(f.name), "duplicate field name on this resource"],
              [!RES_FIELD_NAME_RE.test(String(f.name || "")),
               "letter first; letters, digits, _ and - only (the name is a JSON body key "
               + "and a code doc-block token)"],
            ], "maximum 100 characters")}})));
        tr.appendChild(td(kindSelect(RESOURCE_FIELD_TYPES, f.field_type, v => f.field_type = v, "r" + i + "-f" + j + "-k")));
        tr.appendChild(td(textInput(f.default, "r" + i + "-f" + j + "-d", v => f.default = v,
          {{placeholder: "default", size: 10, bad: resDefaultBad(f),
            title: firstBad([
              [String(f.default || "").includes(":"),
               "':' is not representable in the code doc-block carrier"],
              [f.field_type === "enumeration",
               "the default must be one of the enumeration values"],
            ], "must match the field type (number/boolean/date)")}})));
        if (f.field_type === "enumeration") {{
          const enumRaw = f._enumRaw !== undefined ? f._enumRaw : (f.enumeration_values || []).join(", ");
          tr.appendChild(td(textInput(enumRaw, "r" + i + "-f" + j + "-e",
            v => {{ f._enumRaw = v;
                   f.enumeration_values = v.split(",").map(x => x.trim()).filter(Boolean); }},
            {{placeholder: "a, b, c", size: 16, bad: resEnumBad(f),
              title: firstBad([
                [!(f.enumeration_values || []).length, "an enumeration needs at least one value"],
              ], "comma-separated; ':' and '=' are not representable in the code "
                 + "doc-block carrier")}})));
        }}
        tr.appendChild(td(textInput(f.description, "r" + i + "-f" + j + "-fd", v => f.description = v,
          {{placeholder: "field description", size: 16,
            bad: String(f.description || "").includes(":"),
            title: "':' is not representable in the code doc-block carrier"}})));
      }}
      tbl.appendChild(tr);
    }});
    div.appendChild(tbl);
    if (!r.existing) {{
      const add = document.createElement("button"); add.className = "ghost"; add.textContent = "＋ field";
      add.addEventListener("click", () => {{
        r.fields.push({{name: "", field_type: "string", default: "",
                       enumeration_values: [], description: ""}});
        render();
      }});
      div.appendChild(add);
    }}
    host.appendChild(div);
  }});
}}

function renderCounter() {{
  // Unticked rows are out of the plan — they never count as work to implement.
  const news = s => s.filter(r => !r.existing && inc(r)).length;
  const labels = {{events: "events", player_fields: "fields",
    feature_settings: "feature settings", resources: "resources"}};
  const parts = SECTIONS_PRESENT.map(k => {{
    if (k === "events") {{
      // debug-tagged rows are skipped at implementation (the row itself says so)
      return state.events.filter(r => !r.existing && inc(r) && effectiveKind(r) !== "debug").length + " events";
    }}
    if (k === "feature_settings") {{
      const fs = state.feature_settings;
      return news(fs.schemas) + " fs schemas \u00b7 " + news(fs.settings) + " fs keys";
    }}
    return news(state[k]) + " " + labels[k];
  }});
  document.getElementById("counter").textContent = "to implement: " + parts.join(" \u00b7 ");
}}

document.getElementById("add-event").addEventListener("click", () => {{
  state.events.push({{id: nextId++, kind: "custom", name: "", existing: false, params: [],
                    editing: true, _pageNew: true, source: "added on page"}});
  render();
}});
document.getElementById("add-field").addEventListener("click", () => {{
  state.player_fields.push({{id: nextId++, name: "", kind: "string", description: "",
                             editing: true, existing: false, _pageNew: true, source: "added on page"}});
  render();
}});
document.getElementById("add-res").addEventListener("click", () => {{
  state.resources.push({{id: nextId++, name: "", key: "", description: "", editing: true, existing: false,
    _pageNew: true, fields: [], source: "added on page"}});
  render();
}});

function exportJson() {{
  // Enum values live in state across kind toggles (so switching back restores them),
  // but the EXPORT carries them only for enumeration kinds — a stale list never ships.
  const cleanParam = p => {{
    const {{included, _pNew, ...rest}} = p;
    return rest.kind === "enumeration" ? rest : {{...rest, extra: ""}};
  }};
  const cleanField = f => {{
    const {{_enumRaw, included, ...rest}} = f;
    return rest.field_type === "enumeration" ? rest : {{...rest, enumeration_values: []}};
  }};
  // Select-first: unticked rows are simply absent from the hand-back (same semantics
  // as the old drop); the page-local flags never ship.
  const keep = r => r.existing || inc(r);
  const stripLocal = r => {{ const {{included, editing, _enumRaw, _pageNew, ...rest}} = r; return rest; }};
  return JSON.stringify({{
    confirmed_at: new Date().toISOString(),
    page_generated_at: DATA.generated_at,
    payload_version: DATA_VERSION,
    events: state.events.filter(keep).map(r => {{
      if (r.existing) {{
        // Measured part echoes verbatim; ticked proposals ship under proposed_params
        // (append-only key — older consumers ignore it). No ticked proposals -> key absent.
        const {{proposed_params, ...rest}} = r;
        const ticked = (proposed_params || []).filter(p => p.included === true).map(p => {{
          const {{_proposed, ...c}} = cleanParam(p);
          return SYSTEM_EVENT_PARAM_NAMES.includes(String(c.name || "").trim())
            ? {{...c, system_field: true}} : c;
        }});
        // stripLocal here too: auto edit-mode stamps editing:true on these rows.
        return stripLocal(ticked.length ? {{...rest, proposed_params: ticked}} : rest);
      }}
      const ek = effectiveKind(r);
      const collapsed = ek === "debug" ||
        (ek === "predefined" && isSdkAutomatic(r.name) && INTEGRATION_TYPE === "SDK");
      return stripLocal({{...r, kind: ek,
        params: collapsed ? [] : (r.params || []).filter(p => p.included !== false).map(p => {{
          const c = cleanParam(p);
          // Append-only marker (contract clause 2): the implementation routes these via
          // the base class / SDK and NEVER registers them as custom params.
          return SYSTEM_EVENT_PARAM_NAMES.includes(String(p.name || "").trim())
            ? {{...c, system_field: true}} : c;
        }})}});
    }}),
    player_fields: state.player_fields.filter(keep).map(r => {{
      if (r.existing) return r;  // echoed verbatim — the row is a measurement of code
      const out = stripLocal(r.kind === "enumeration" ? {{...r}} : {{...r, extra: ""}});
      const p = String(r.path || "").trim() || snake(String(r.name || "").trim());
      // The path the developer SAW (derived or overridden) ships explicitly — the page
      // is the approval gate; a hand-back without it made the consumer re-derive and
      // hid the approved value (demo-b InitialDeviceOS, 2026-08-03).
      out.path = p;
      // Append-only marker: the sync ACTIVATES the dashboard's predefined field —
      // implementation takes the module-02 SDK-state route, never a custom create.
      if (FR_PREDEF[p] !== undefined) out.predefined_field = true;
      return out;
    }}),
    feature_settings: {{schemas: state.feature_settings.schemas.filter(keep)
        .map(r => r.existing ? r : stripLocal({{...r,
          columns: (r.columns || []).filter(c => c.included !== false)
            .map(c => {{ const {{included, ...cc}} = c; return cc; }})}})),
      settings: state.feature_settings.settings.filter(keep).map(st => {{
        if (st.existing) return st;  // echoed verbatim — keys wired at older live versions stay so
        // keep-filtered: an unticked new schema must not shadow a same-named existing
        // one (it would wrongly resolve version 1 for the bound setting).
        const sch = state.feature_settings.schemas.filter(keep).find(
          x => String(x.name || "") === String(st.schema_name || ""));
        const ver = sch ? (sch.existing ? (sch.version || st.version || 1) : 1)
                        : (st.version || 1);
        return stripLocal({{...st, version: ver}});
      }})}},
    resources: state.resources.filter(keep).map(r => {{
      if (r.existing) return r;  // echoed verbatim — the row is a measurement of code
      return stripLocal({{...r, fields: (r.fields || []).filter(f => f.included !== false).map(cleanField)}});
    }}),
  }}, null, 2);
}}
function flash(msg) {{
  const el = document.getElementById("flash");
  el.textContent = msg; setTimeout(() => el.textContent = "", 4000);
}}
document.getElementById("download").addEventListener("click", () => {{
  const stamp = (DATA.generated_at || "").replace(/[:]/g, "-");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([exportJson()], {{type: "application/json"}}));
  a.download = "kinoa-merge-plan-confirmed-" + stamp + ".json";
  document.body.appendChild(a); a.click(); a.remove();
  flash("Downloaded — hand the file path back to the skill");
}});
document.getElementById("copy").addEventListener("click", async () => {{
  try {{ await navigator.clipboard.writeText(exportJson()); flash("Copied — paste it into the chat"); }}
  catch (e) {{
    const ta = document.createElement("textarea"); ta.value = exportJson();
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    flash("Copied — paste it into the chat");
  }}
}});
render();
</script>
</body>
</html>
"""


def build_page(payload):
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return PAGE_TEMPLATE.format(
        game_id=payload.get("game_id") or "—",
        generated_at=payload.get("generated_at") or "—",
        data_json=data_json,
        event_param_kinds=json.dumps(EVENT_PARAM_KINDS),
        field_kinds=json.dumps(FIELD_KINDS),
        fs_column_kinds=json.dumps(FS_COLUMN_KINDS),
        resource_field_types=json.dumps(RESOURCE_FIELD_TYPES),
        resource_key_re=json.dumps(RESOURCE_KEY_RE),
        system_event_param_names=json.dumps(SYSTEM_EVENT_PARAM_NAMES),
        system_base_prop_param_names=json.dumps(SYSTEM_BASE_PROP_PARAM_NAMES),
        system_auto_param_names=json.dumps(SYSTEM_AUTO_PARAM_NAMES),
        system_param_kinds=json.dumps(SYSTEM_PARAM_KINDS),
        payload_version=json.dumps(PAYLOAD_VERSION),
    )


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="Path to JSON input. If omitted, read stdin.")
    parser.add_argument("--output", required=True, help="Path of the HTML file to write.")
    parser.add_argument("--no-open", action="store_true", help="Skip opening the browser.")
    args = parser.parse_args(argv)

    raw = open(args.input, encoding="utf-8").read() if args.input else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid_json", "message": str(e)}, indent=2))
        return 2
    if not isinstance(payload, dict):
        print(json.dumps({"ok": False, "error": "invalid_payload",
                          "message": "expected a JSON object"}, indent=2))
        return 2
    ids = []
    for section in ("events", "player_fields", "feature_settings", "resources"):
        val = payload.get(section)
        if isinstance(val, dict):  # feature_settings split shape: {schemas, settings}
            for sub in ("schemas", "settings"):
                ids += [r.get("id") for r in val.get(sub) or []]
        else:
            ids += [r.get("id") for r in val or []]
    if len(ids) != len(set(ids)) or any(i is None for i in ids):
        print(json.dumps({"ok": False, "error": "invalid_rows",
                          "message": "every row needs a unique non-null id across all sections"},
                         indent=2))
        return 2

    out = pathlib.Path(args.output).resolve()
    out.write_text(build_page(payload), encoding="utf-8")
    opened = False
    if not args.no_open:
        try:
            opened = webbrowser.open("file://" + str(out))
        except Exception:
            opened = False
    print(json.dumps({"ok": True, "output": str(out), "opened_in_browser": bool(opened)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
