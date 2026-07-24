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
  "events": [
    {"id": 1, "kind": "custom"|"predefined", "name": "gold_purchase", "existing": false,
     "source": "Scripts/Shop.cs:118", "note": "purchase flow",
     "params": [{"name": "amount", "kind": "number", "extra": ""}]}
  ],
  "player_fields": [
    {"id": 20, "name": "Wallet.Gold", "kind": "number", "extra": "", "existing": false,
     "source": "Scripts/Model/Player/Wallet.cs:12", "note": ""}
  ],
  "feature_settings": [
    {"id": 40, "schema_name": "BoosterEconomy", "key": "BoosterEconomy", "version": 1,
     "existing": false, "source": "booster_economy.csv", "note": "",
     "columns": [{"name": "sku", "kind": "bundle_key", "is_required": true}]}
  ],
  "resources": [
    {"id": 60, "name": "Legendary Sword", "key": "legendary_sword", "existing": false,
     "description": "Boss reward.", "source": "Model/Enums/RewardType.cs:10", "note": "",
     "fields": [{"name": "attack", "field_type": "number", "required": true,
                 "default": "100", "enumeration_values": [], "description": ""}]}
  ]
}

A merge run fires this page PER MODULE as its walk reaches each surface — the
payload then carries just that section (the others empty/omitted); /kinoa
resources renders the resources-only page the same way.

The exported plan echoes the same shape plus stamps:

{"confirmed_at": "<iso>", "page_generated_at": "<echo of generated_at>",
 "payload_version": <echo, absent input = 1>,
 "events": [...], "player_fields": [...], "feature_settings": [...], "resources": [...]}

(existing rows are echoed verbatim; the skill implements only "existing": false
rows, exactly as edited.)

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
:root {{ color-scheme: light dark; }}
* {{ box-sizing: border-box; }}
body {{ font: 15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0;
       background: #f6f8fa; color: #1f2328; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #0d1117; color: #e6edf3; }}
  .card, header .bar {{ background: #161b22 !important; border-color: #30363d !important; }}
  .muted {{ color: #8b949e !important; }}
  .row {{ border-color: #30363d !important; }}
  input[type=text], select {{ background: #0d1117; color: #e6edf3; border-color: #30363d; }}
}}
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
input[type=text], select {{ font: inherit; padding: 0.3rem 0.45rem; border: 1px solid #d0d7de; border-radius: 6px; }}
input.bad {{ border-color: #cf222e; background: #fff5f5; }}
input.warnp {{ border-color: #bf8700; }}
.badge {{ display: inline-block; font-size: 0.72rem; padding: 0.1rem 0.5rem; border-radius: 999px;
         border: 1px solid currentColor; white-space: nowrap; }}
.b-existing {{ color: #57606a; }} .b-new {{ color: #1a7f37; }} .b-predef {{ color: #0969da; }}
button {{ font: inherit; padding: 0.35rem 0.8rem; border-radius: 6px; cursor: pointer;
         border: 1px solid #d0d7de; background: #fff; }}
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
  <div class="card" id="fs-card"><h2>Feature settings</h2><div id="feature_settings"></div>
    <button class="ghost" id="add-fs">＋ Add feature setting</button></div>
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
const PAYLOAD_VERSION = {payload_version};
const DATA_VERSION = DATA.payload_version || 1;
const VERSION_MISMATCH = DATA_VERSION > PAYLOAD_VERSION;

const state = {{
  events: (DATA.events || []).map(x => ({{params: [], ...x}})),
  player_fields: (DATA.player_fields || []).slice(),
  feature_settings: (DATA.feature_settings || []).map(x => ({{columns: [], ...x}})),
  resources: (DATA.resources || []).map(x => ({{fields: [], ...x}})),
}};
let nextId = 1 + Math.max(0, ...[...state.events, ...state.player_fields,
  ...state.feature_settings, ...state.resources].map(r => r.id || 0));

function esc(s) {{ const d = document.createElement("span"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }}
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
  if (row.kind === "predefined") {{
    const b = document.createElement("span"); b.className = "badge b-predef"; b.textContent = "predefined";
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
        tr.appendChild(td(kindSelect(EVENT_PARAM_KINDS, p.kind, v => p.kind = v)));
        const extra = textInput(p.extra, "e" + i + "-p" + j + "-x", v => p.extra = v,
          {{placeholder: "a, b, c", size: 18, bad: p.kind === "enumeration" && !String(p.extra || "").trim()}});
        if (p.kind !== "enumeration") extra.disabled = true;
        tr.appendChild(td(extra));
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
      const fex = textInput(r.extra, "f" + i + "-x", v => r.extra = v,
        {{placeholder: "a, b, c", size: 16,
          bad: r.kind === "enumeration" && !String(r.extra || "").trim()}});
      if (r.kind !== "enumeration") fex.disabled = true;
      g.appendChild(fex);
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
  const dup = dupNames(state.feature_settings, "key");
  state.feature_settings.forEach((r, i) => {{
    const div = document.createElement("div"); div.className = "row" + (r.existing ? " locked" : "");
    div.appendChild(head(r, "new feature setting", () => state.feature_settings.splice(i, 1)));
    const g = document.createElement("div"); g.className = "grid";
    if (r.existing) {{
      g.innerHTML = "key <code>" + esc(r.key) + "</code> · schema <code>" + esc(r.schema_name) +
                    "</code> · v" + esc(r.version);
    }} else {{
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">key</span>");
      g.appendChild(textInput(r.key, "s" + i + "-key", v => r.key = v,
        {{placeholder: "FeatureKey", size: 20, bad: !String(r.key || "").trim() || dup(r.key)}}));
      g.insertAdjacentHTML("beforeend", "<span class=\"muted\">schema</span>");
      g.appendChild(textInput(r.schema_name, "s" + i + "-schema", v => r.schema_name = v,
        {{placeholder: "SchemaName", size: 20, bad: !String(r.schema_name || "").trim()}}));
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
        tr.innerHTML = "<td><code>" + esc(c.name) + "</code></td><td>" + esc(c.kind) +
          (c.is_required === false ? "" : " · required") + "</td>";
      }} else {{
        tr.appendChild(td(textInput(c.name, "s" + i + "-c" + j, v => c.name = v,
          {{placeholder: "column", size: 20, bad: !String(c.name || "").trim() || cdup(c.name)}})));
        tr.appendChild(td(kindSelect(FS_COLUMN_KINDS, c.kind, v => c.kind = v)));
        // FS columns default REQUIRED (helper/planner default isRequired=true).
        const req = document.createElement("input"); req.type = "checkbox";
        req.checked = c.is_required !== false; req.title = "required";
        req.addEventListener("change", e => {{ c.is_required = e.target.checked; }});
        tr.appendChild(td(req));
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
        const ev = textInput((f.enumeration_values || []).join(", "), "r" + i + "-f" + j + "-e",
          v => f.enumeration_values = v.split(",").map(x => x.trim()).filter(Boolean),
          {{placeholder: "a, b, c", size: 16,
            bad: f.field_type === "enumeration" && !(f.enumeration_values || []).length}});
        if (f.field_type !== "enumeration") ev.disabled = true;
        tr.appendChild(td(ev));
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
  document.getElementById("counter").textContent =
    "to implement: " + news(state.events) + " events · " + news(state.player_fields) +
    " fields · " + news(state.feature_settings) + " feature settings · " +
    news(state.resources) + " resources";
}}

document.getElementById("add-event").addEventListener("click", () => {{
  state.events.push({{id: nextId++, kind: "custom", name: "", existing: false, params: [], source: "added on page"}});
  render();
}});
document.getElementById("add-field").addEventListener("click", () => {{
  state.player_fields.push({{id: nextId++, name: "", kind: "string", existing: false, source: "added on page"}});
  render();
}});
document.getElementById("add-fs").addEventListener("click", () => {{
  state.feature_settings.push({{id: nextId++, key: "", schema_name: "", version: 1, existing: false,
    columns: [], source: "added on page"}});
  render();
}});
document.getElementById("add-res").addEventListener("click", () => {{
  state.resources.push({{id: nextId++, name: "", key: "", description: "", existing: false,
    fields: [], source: "added on page"}});
  render();
}});

function exportJson() {{
  return JSON.stringify({{
    confirmed_at: new Date().toISOString(),
    page_generated_at: DATA.generated_at,
    payload_version: DATA_VERSION,
    events: state.events,
    player_fields: state.player_fields,
    feature_settings: state.feature_settings,
    resources: state.resources,
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
    ids = [r.get("id") for section in ("events", "player_fields", "feature_settings", "resources")
           for r in payload.get(section) or []]
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
