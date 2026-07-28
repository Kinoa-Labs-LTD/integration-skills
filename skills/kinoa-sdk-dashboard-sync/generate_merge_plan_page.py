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
     "source": "Scripts/Model/Player/Wallet.cs:12", "note": ""}
  ],
  "feature_settings": {
    "schemas":  [{"id": 40, "name": "BoosterEconomy", "existing": false,
                  "source": "booster_economy.csv",
                  "columns": [{"name": "sku", "kind": "bundle_key", "is_required": true}]}],
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
     "fields": [{"name": "attack", "field_type": "number", "required": true,
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
SYSTEM_EVENT_PARAM_NAMES = ["device_id", "time", "time_ms"]
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
.b-existing {{ color: #57606a; }} .b-new {{ color: #1a7f37; }} .b-predef {{ color: #0969da; }} .b-debug {{ color: #bf8700; }}
button {{ font: inherit; padding: 0.35rem 0.8rem; border-radius: 6px; cursor: pointer;
         border: 1px solid #d0d7de; background: #fff; color: #1f2328; }}
button.ghost {{ border-style: dashed; }}
button.primary {{ background: #1f883d; border-color: #1f883d; color: #fff; }}
button.del {{ color: #cf222e; }}
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
      edit names, kinds and params of NEW rows, drop wrong proposals, add missed ones.
      Rows already in code are read-only — those edit code-first (the code is the source of truth).
      Names ship byte-for-byte into your code and, later, onto the Dashboard.
    </div>
  </div>
</header>
<main>
  <div class="card" id="events-card"><h2>Game events</h2><div id="events"></div>
    <button class="ghost" id="add-event">＋ Add event</button></div>
  <div class="card" id="fields-card"><h2>Player fields</h2><div id="player_fields"></div>
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
                      columns: r.columns || []}}); }}
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
let nextId = 1 + Math.max(0, ...[...state.events, ...state.player_fields,
  ...state.feature_settings.schemas, ...state.feature_settings.settings,
  ...state.resources].map(r => r.id || 0));

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
  if (r.kind === "debug" || r.kind === "sdk" || isDebugName(r.name)) return "debug";
  if (r.kind === "predefined" || isPredefName(r.name)) return "predefined";
  return r.kind || "custom";
}}
function snake(s) {{ return String(s || "").replace(/([a-z0-9])([A-Z])/g, "$1_$2").replace(/\./g, ".").toLowerCase(); }}

// Re-render destroys every node — remember the focused input and caret so
// live-validated typing doesn't drop focus.
function render() {{
  if (VERSION_MISMATCH) {{
    document.querySelector("header .bar").insertAdjacentHTML("beforeend",
      '<div style="color:#cf222e;font-weight:600;margin-top:0.4rem">' +
      "This page is OLDER than the payload (payload_version " + DATA_VERSION +
      " > supported " + PAYLOAD_VERSION + ") — export is disabled; update the kinoa-dashboard " +
      "plugin and re-run.</div>");
    document.getElementById("download").disabled = true;
    document.getElementById("copy").disabled = true;
    return;
  }}
  const active = document.activeElement;
  const focusId = active && active.dataset ? active.dataset.fid : null;
  const selStart = focusId && "selectionStart" in active ? active.selectionStart : null;
  renderEvents(); renderFields(); renderFs(); renderResources(); renderCounter();
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
  if (opts.bad) inp.className = "bad";
  else if (opts.warn) inp.className = "warnp";
  if (opts.title) inp.title = opts.title;
  inp.addEventListener("input", e => {{ oninput(e.target.value); render(); }});
  return inp;
}}

function kindSelect(kinds, value, onchange) {{
  const sel = document.createElement("select");
  kinds.forEach(k => {{ const o = document.createElement("option"); o.value = k; o.textContent = k;
    if (k === value) o.selected = true; sel.appendChild(o); }});
  sel.addEventListener("change", e => {{ onchange(e.target.value); render(); }});
  return sel;
}}

function head(row, label, onDrop) {{
  const div = document.createElement("div"); div.className = "grid";
  const badge = document.createElement("span");
  badge.className = "badge " + (row.existing ? "b-existing" : "b-new");
  badge.textContent = row.existing ? "already in code — edit code-first" : label;
  div.appendChild(badge);
  const ek = row.params !== undefined ? effectiveKind(row) : row.kind;
  if (ek === "predefined") {{
    const b = document.createElement("span"); b.className = "badge b-predef"; b.textContent = "predefined";
    b.title = "predefined Kinoa event — wired via the game's existing builder (e.g. PaymentEventData); " +
              "params attach as custom_params. It will NOT be created as a custom event.";
    div.appendChild(b);
  }} else if (ek === "debug") {{
    const b = document.createElement("span"); b.className = "badge b-debug"; b.textContent = "debug";
    b.title = "debug telemetry — emitted by the SDK/backend itself, never sent from app code; " +
              "there is nothing to implement, this row will be skipped.";
    div.appendChild(b);
  }}
  if (row.source) {{
    const s = document.createElement("span"); s.className = "muted"; s.textContent = row.source;
    div.appendChild(s);
  }}
  if (!row.existing) {{
    const del = document.createElement("button"); del.className = "del"; del.textContent = "✕ drop";
    del.addEventListener("click", () => {{ onDrop(); render(); }});
    div.appendChild(del);
  }}
  return div;
}}

function dupNames(rows, key) {{
  const seen = new Map();
  rows.forEach(r => {{ const n = String(r[key] || "").trim().toLowerCase();
    seen.set(n, (seen.get(n) || 0) + 1); }});
  return n => n && seen.get(String(n).trim().toLowerCase()) > 1;
}}

function dupIn(items, key) {{ return dupNames(items || [], key); }}

// FS reserved column namespace: "filter: ..." props are IncludeFilters READERS (configuration-
// level, bound to Player Fields at config-fill time) and "<...>" is unreplaced scaffold — the
// planner drops both from schema plans, so authoring them here would promise a column that
// never materializes. Mirror of the planner's _is_filter_or_placeholder.
function isReservedFsColumn(n) {{
  const t = String(n || "").trim().toLowerCase();
  return t.startsWith("filter:") || String(n || "").includes("<");
}}

function renderEvents() {{
  const host = document.getElementById("events"); host.innerHTML = "";
  const dup = dupNames(state.events, "name");
  state.events.forEach((r, i) => {{
    const div = document.createElement("div"); div.className = "row" + (r.existing ? " locked" : "");
    div.appendChild(head(r, "new event", () => state.events.splice(i, 1)));
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing || r.kind === "predefined") {{
      // Predefined wire names are a fixed registry — never editable, even on new rows.
      g.innerHTML = "<code>" + esc(r.name) + "</code>";
    }} else {{
      g.appendChild(textInput(r.name, "e" + i + "-name", v => r.name = v,
        {{placeholder: "event_name", size: 28, bad: !String(r.name || "").trim() || dup(r.name)}}));
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
    const pdup = dupIn(r.params, "name");
    (r.params || []).forEach((p, j) => {{
      const tr = document.createElement("tr");
      const td = t => {{ const c = document.createElement("td"); c.appendChild(t); return c; }};
      if (r.existing) {{
        tr.innerHTML = "<td><code>" + esc(p.name) + "</code></td><td>" + esc(p.kind) + "</td><td>" + esc(p.extra || "") + "</td>";
      }} else {{
        const sysHit = SYSTEM_EVENT_PARAM_NAMES.includes(String(p.name || "").trim());
        tr.appendChild(td(textInput(p.name, "e" + i + "-p" + j, v => p.name = v,
          {{placeholder: "param_name", size: 20,
            bad: !String(p.name || "").trim() || pdup(p.name), warn: sysHit,
            title: sysHit ? "collides with a dashboard SYSTEM event param — the event will lose its standard " + p.name + " column; rename (e.g. time -> time_of_day)" : ""}})));
        // Enum-values input shows ONLY while kind === enumeration, but the VALUE is
        // preserved on kind changes (discovery-found candidates must survive a toggle);
        // the EXPORT strips it for non-enumeration kinds instead.
        tr.appendChild(td(kindSelect(EVENT_PARAM_KINDS, p.kind, v => p.kind = v)));
        if (p.kind === "enumeration") {{
          tr.appendChild(td(textInput(p.extra, "e" + i + "-p" + j + "-x", v => p.extra = v,
            {{placeholder: "a, b, c", size: 18, bad: !String(p.extra || "").trim()}})));
        }}
        const rm = document.createElement("button"); rm.className = "del"; rm.textContent = "✕";
        rm.addEventListener("click", () => {{ r.params.splice(j, 1); render(); }});
        tr.appendChild(td(rm));
      }}
      tbl.appendChild(tr);
    }});
    div.appendChild(tbl);
    if (!r.existing) {{
      const add = document.createElement("button"); add.className = "ghost"; add.textContent = "＋ param";
      add.addEventListener("click", () => {{ r.params.push({{name: "", kind: "string", extra: ""}}); render(); }});
      div.appendChild(add);
    }}
    host.appendChild(div);
  }});
}}

function renderFields() {{
  const host = document.getElementById("player_fields"); host.innerHTML = "";
  const dup = dupNames(state.player_fields, "name");
  state.player_fields.forEach((r, i) => {{
    const div = document.createElement("div"); div.className = "row" + (r.existing ? " locked" : "");
    div.appendChild(head(r, "new field", () => state.player_fields.splice(i, 1)));
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "<code>" + esc(r.name) + "</code> <span class=\"muted\">" + esc(r.kind) + "</span>";
    }} else {{
      g.appendChild(textInput(r.name, "f" + i, v => r.name = v,
        {{placeholder: "Wallet.Gold", size: 26, bad: !String(r.name || "").trim() || dup(r.name)}}));
      g.appendChild(kindSelect(FIELD_KINDS, r.kind, v => r.kind = v));
      if (r.kind === "enumeration") {{
        g.appendChild(textInput(r.extra, "f" + i + "-x", v => r.extra = v,
          {{placeholder: "a, b, c", size: 16, bad: !String(r.extra || "").trim()}}));
      }}
      const prev = document.createElement("span"); prev.className = "muted";
      prev.textContent = "→ path: " + snake(r.name);
      g.appendChild(prev);
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    host.appendChild(div);
  }});
}}

function renderFs() {{
  const host = document.getElementById("feature_settings"); host.innerHTML = "";
  const fs = state.feature_settings;
  const sdup = dupNames(fs.schemas, "name");
  const kdup = dupNames(fs.settings, "key");
  const schemaNames = fs.schemas.map(x => String(x.name || "")).filter(Boolean);
  const newSchemas = new Set(fs.schemas.filter(x => !x.existing).map(x => String(x.name || "")));

  host.insertAdjacentHTML("beforeend",
    '<div class="muted" style="margin:0.2rem 0 0.4rem"><b>Schemas</b> — column shapes; ONE schema may back several setting keys (columns are defined here once)</div>');
  fs.schemas.forEach((r, i) => {{
    const div = document.createElement("div"); div.className = "row" + (r.existing ? " locked" : "");
    div.appendChild(head(r, "new schema", () => fs.schemas.splice(i, 1)));
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "schema <code>" + esc(r.name) + "</code>";
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">schema</span>");
      g.appendChild(textInput(r.name, "ss" + i, v => r.name = v,
        {{placeholder: "SchemaName", size: 22, bad: !String(r.name || "").trim() || sdup(r.name)}}));
      // A NEW schema always wires as version 1 (module 07) — shown, never editable.
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">v1 (new schemas always start at 1)</span>");
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    const tbl = document.createElement("table"); tbl.className = "sub";
    const cdup = dupIn(r.columns, "name");
    (r.columns || []).forEach((c, j) => {{
      const tr = document.createElement("tr");
      const td = t => {{ const x = document.createElement("td"); x.appendChild(t); return x; }};
      if (r.existing) {{
        tr.innerHTML = "<td><code>" + esc(c.name) + "</code></td><td>" + esc(c.kind) + "</td>";
      }} else {{
        const reserved = isReservedFsColumn(c.name);
        tr.appendChild(td(textInput(c.name, "ss" + i + "-c" + j, v => c.name = v,
          {{placeholder: "column", size: 20,
            bad: !String(c.name || "").trim() || cdup(c.name) || reserved,
            title: reserved ? "filters are configuration-level (IncludeFilters readers), not schema columns — the operator picks them on the configuration table; unreplaced <placeholders> are scaffold" : ""}})));
        tr.appendChild(td(kindSelect(FS_COLUMN_KINDS, c.kind, v => c.kind = v)));
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
        const rm = document.createElement("button"); rm.className = "del"; rm.textContent = "✕";
        rm.addEventListener("click", () => {{ r.columns.splice(j, 1); render(); }});
        tr.appendChild(td(rm));
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
    fs.schemas.push({{id: nextId++, name: "", existing: false, columns: [], source: "added on page"}});
    render();
  }});
  host.appendChild(addS);

  host.insertAdjacentHTML("beforeend",
    '<div class="muted" style="margin:0.8rem 0 0.4rem"><b>Settings (keys)</b> — the runtime download keys; each binds ONE schema from the list above</div>');
  fs.settings.forEach((r, i) => {{
    const div = document.createElement("div"); div.className = "row" + (r.existing ? " locked" : "");
    div.appendChild(head(r, "new setting", () => fs.settings.splice(i, 1)));
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "key <code>" + esc(r.key) + "</code> · schema <code>" + esc(r.schema_name) +
                    "</code> · v" + esc(r.version);
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">key</span>");
      g.appendChild(textInput(r.key, "sk" + i, v => r.key = v,
        {{placeholder: "FeatureKey", size: 20, bad: !String(r.key || "").trim() || kdup(r.key)}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">schema</span>");
      // Schema is a REFERENCE, not free text — pick from the schemas defined above
      // (kills dangling schema_name and shape redefinition by construction).
      const sel = document.createElement("select");
      const missing = r.schema_name && !schemaNames.includes(r.schema_name);
      if (!schemaNames.length || missing) {{
        const o = document.createElement("option"); o.value = r.schema_name || "";
        o.textContent = missing ? "(missing: " + r.schema_name + ")" : "(no schemas defined above)";
        o.selected = true; sel.appendChild(o); sel.className = "bad";
      }}
      schemaNames.forEach(n => {{
        const o = document.createElement("option"); o.value = n; o.textContent = n;
        if (n === r.schema_name) o.selected = true; sel.appendChild(o);
      }});
      sel.addEventListener("change", e => {{ r.schema_name = e.target.value; render(); }});
      g.appendChild(sel);
      const v = document.createElement("span"); v.className = "muted";
      v.textContent = newSchemas.has(r.schema_name)
        ? "v1 (new schema)" : "v" + (r.version || 1) + " (from code wiring)";
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
                      existing: false, source: "added on page"}});
    render();
  }});
  host.appendChild(addK);
}}

function renderResources() {{
  const host = document.getElementById("resources"); host.innerHTML = "";
  const dup = dupNames(state.resources, "key");
  const ndup = dupNames(state.resources, "name");
  state.resources.forEach((r, i) => {{
    const div = document.createElement("div"); div.className = "row" + (r.existing ? " locked" : "");
    div.appendChild(head(r, "new resource", () => state.resources.splice(i, 1)));
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "<code>" + esc(r.key) + "</code> <span class=\"muted\">" + esc(r.name) + "</span>";
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">key</span>");
      g.appendChild(textInput(r.key, "r" + i + "-key", v => r.key = v,
        {{placeholder: "legendary_sword", size: 22,
          bad: !RESOURCE_KEY_RE.test(String(r.key || "")) || dup(r.key)}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">name</span>");
      g.appendChild(textInput(r.name, "r" + i + "-name", v => r.name = v,
        {{placeholder: "Legendary Sword", size: 22,
          bad: !String(r.name || "").trim() || ndup(r.name),
          title: "template NAME is unique on the server across ALL statuses (incl. DEPRECATED)"}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">description</span>");
      g.appendChild(textInput(r.description, "r" + i + "-desc", v => r.description = v,
        {{placeholder: "optional", size: 26}}));
    }}
    if (r.note) {{ const n = document.createElement("span"); n.className = "muted"; n.textContent = r.note; g.appendChild(n); }}
    div.appendChild(g);
    const tbl = document.createElement("table"); tbl.className = "sub";
    const fdup = dupIn(r.fields, "name");
    (r.fields || []).forEach((f, j) => {{
      const tr = document.createElement("tr");
      const td = t => {{ const x = document.createElement("td"); x.appendChild(t); return x; }};
      if (r.existing) {{
        tr.innerHTML = "<td><code>" + esc(f.name) + "</code></td><td>" + esc(f.field_type) +
          (f.required ? " · required" : "") + "</td><td>" +
          esc((f.enumeration_values || []).join(", ") || f.default || "") + "</td>";
      }} else {{
        tr.appendChild(td(textInput(f.name, "r" + i + "-f" + j, v => f.name = v,
          {{placeholder: "field_name", size: 16, bad: !String(f.name || "").trim() || fdup(f.name)}})));
        tr.appendChild(td(kindSelect(RESOURCE_FIELD_TYPES, f.field_type, v => f.field_type = v)));
        const req = document.createElement("input"); req.type = "checkbox"; req.checked = !!f.required;
        req.title = "required";
        req.addEventListener("change", e => {{ f.required = e.target.checked; }});
        tr.appendChild(td(req));
        tr.appendChild(td(textInput(f.default, "r" + i + "-f" + j + "-d", v => f.default = v,
          {{placeholder: "default", size: 10}})));
        if (f.field_type === "enumeration") {{
          tr.appendChild(td(textInput((f.enumeration_values || []).join(", "), "r" + i + "-f" + j + "-e",
            v => f.enumeration_values = v.split(",").map(x => x.trim()).filter(Boolean),
            {{placeholder: "a, b, c", size: 16, bad: !(f.enumeration_values || []).length}})));
        }}
        tr.appendChild(td(textInput(f.description, "r" + i + "-f" + j + "-fd", v => f.description = v,
          {{placeholder: "field description", size: 16}})));
        const rm = document.createElement("button"); rm.className = "del"; rm.textContent = "✕";
        rm.addEventListener("click", () => {{ r.fields.splice(j, 1); render(); }});
        tr.appendChild(td(rm));
      }}
      tbl.appendChild(tr);
    }});
    div.appendChild(tbl);
    if (!r.existing) {{
      const add = document.createElement("button"); add.className = "ghost"; add.textContent = "＋ field";
      add.addEventListener("click", () => {{
        r.fields.push({{name: "", field_type: "string", required: false, default: "",
                       enumeration_values: [], description: ""}});
        render();
      }});
      div.appendChild(add);
    }}
    host.appendChild(div);
  }});
}}

function renderCounter() {{
  const news = s => s.filter(r => !r.existing).length;
  const labels = {{events: "events", player_fields: "fields",
    feature_settings: "feature settings", resources: "resources"}};
  const parts = SECTIONS_PRESENT.map(k => {{
    if (k === "feature_settings") {{
      const fs = state.feature_settings;
      return news(fs.schemas) + " fs schemas \u00b7 " + news(fs.settings) + " fs keys";
    }}
    return news(state[k]) + " " + labels[k];
  }});
  document.getElementById("counter").textContent = "to implement: " + parts.join(" \u00b7 ");
}}

document.getElementById("add-event").addEventListener("click", () => {{
  state.events.push({{id: nextId++, kind: "custom", name: "", existing: false, params: [], source: "added on page"}});
  render();
}});
document.getElementById("add-field").addEventListener("click", () => {{
  state.player_fields.push({{id: nextId++, name: "", kind: "string", existing: false, source: "added on page"}});
  render();
}});
document.getElementById("add-res").addEventListener("click", () => {{
  state.resources.push({{id: nextId++, name: "", key: "", description: "", existing: false,
    fields: [], source: "added on page"}});
  render();
}});

function exportJson() {{
  // Enum values live in state across kind toggles (so switching back restores them),
  // but the EXPORT carries them only for enumeration kinds — a stale list never ships.
  const cleanParam = p => p.kind === "enumeration" ? p : {{...p, extra: ""}};
  const cleanField = f => f.field_type === "enumeration" ? f : {{...f, enumeration_values: []}};
  return JSON.stringify({{
    confirmed_at: new Date().toISOString(),
    page_generated_at: DATA.generated_at,
    payload_version: DATA_VERSION,
    events: state.events.map(r => ({{...r, kind: effectiveKind(r),
      params: (r.params || []).map(cleanParam)}})),
    player_fields: state.player_fields.map(r =>
      r.kind === "enumeration" ? r : {{...r, extra: ""}}),
    feature_settings: state.feature_settings,
    resources: state.resources.map(r => ({{...r, fields: (r.fields || []).map(cleanField)}})),
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
