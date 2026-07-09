#!/usr/bin/env python3
"""Generate the INTERACTIVE resource-confirmation page for
kinoa-sync-resource-template-integration.

This is the load-bearing human-in-the-loop step of the workflow. The skill
discovers candidate resources (sellable / awardable items — NOT internal
currency) in the game code and proposes them here; the developer reviews the
list *in a browser*, edits parameters, deletes proposals that aren't real
resources, and adds ones the scan missed. The page can't write to the
developer's filesystem (browser sandbox), so it hands the confirmed list back
two ways — a **Download** button (saves a JSON file the developer points the
skill at) and a **Copy** button (pastes the JSON into the chat). The skill
then feeds that confirmed JSON to kinoa-dashboard-resource-template.

Usage:
    cat candidates.json | python generate_confirm_page.py --output confirm.html
    python generate_confirm_page.py --input candidates.json --output confirm.html

Input JSON shape (lists may be empty):

{
  "generated_at": "2026-07-09T14:23:00Z",
  "game_id":      "<uuid>",
  "existing_keys": ["sword", "gold_chest"],     // keys already on the dashboard
  "resources": [
    {
      "name":        "Legendary Sword",
      "resourceKey": "legendary_sword",
      "description": "Awarded for beating the final boss.",
      "source":      "Assets/Shop/items.json:42",   // provenance hint (optional)
      "existing":    false,                          // already on dashboard?
      "fields": [
        {"name": "attack", "field_type": "number", "required": true,
         "default": 100, "description": "Base attack"},
        {"name": "rarity", "field_type": "enumeration", "required": false,
         "enumeration_values": ["common", "rare", "epic"]}
      ]
    }
  ]
}

The confirmed JSON the developer exports has the shape the sync phase expects:

{
  "confirmed_at": "<iso, stamped by the page at export>",
  "resources": [
    {"name", "resourceKey", "description", "existing", "fields": [
        {"name", "field_type", "required", "default"?, "enumeration_values"?, "description"?}
    ]}
  ]
}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from typing import Any

FIELD_TYPES = ["number", "string", "boolean", "date", "enumeration"]
RESOURCE_KEY_RE = r"^[a-zA-Z][a-zA-Z0-9_-]*$"

CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1150px; margin: 2rem auto; padding: 0 1.5rem;
  color: #1f2328; line-height: 1.5;
}
h1 { margin-bottom: 0.25rem; }
.meta { color: #57606a; font-size: 0.9rem; margin-bottom: 1rem; }
.meta code { background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 4px; }
.intro { background: #ddf4ff; border: 1px solid #54aeff; border-left: 4px solid #0969da;
  border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.25rem; font-size: 0.92rem; }
.intro ul { margin: 0.4rem 0 0 1.1rem; padding: 0; }

.toolbar { position: sticky; top: 0; z-index: 10; background: #ffffffee; backdrop-filter: blur(4px);
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
.spacer { flex: 1; }
#status { font-size: 0.88rem; padding: 0.3rem 0.6rem; border-radius: 6px; }
#status.ok { background: #dafbe1; color: #116329; }
#status.warn { background: #fff8c5; color: #7d4e00; }
#status.bad { background: #ffebe9; color: #82071e; }

.resource { border: 1px solid #d0d7de; border-radius: 10px; padding: 1rem 1.1rem;
  margin-bottom: 1rem; border-left: 4px solid #8250df; }
.resource.existing { border-left-color: #57606a; background: #f6f8fa; }
.resource.invalid { border-left-color: #cf222e; }
.resource .rhead { display: flex; gap: 0.75rem; align-items: flex-start; flex-wrap: wrap; }
.resource .rhead .grow { flex: 1 1 220px; }
label { display: block; font-size: 0.78rem; color: #57606a; margin-bottom: 0.15rem; }
input[type=text], textarea, select { font: inherit; width: 100%; padding: 0.35rem 0.5rem;
  border: 1px solid #d0d7de; border-radius: 6px; background: #fff; }
input.bad { border-color: #cf222e; background: #fff5f5; }
.badge { font-size: 0.72rem; padding: 0.1rem 0.45rem; border-radius: 10px; font-weight: 600; }
.badge.exists { background: #656d76; color: #fff; }
.badge.new { background: #8250df; color: #fff; }
.src { font-size: 0.78rem; color: #57606a; margin-top: 0.35rem; }
.src code { background: #f6f8fa; padding: 0.05rem 0.3rem; border-radius: 4px; }
.err { color: #cf222e; font-size: 0.78rem; margin-top: 0.2rem; }

table.fields { width: 100%; border-collapse: collapse; margin-top: 0.75rem; }
table.fields th, table.fields td { text-align: left; padding: 0.3rem 0.4rem; border-bottom: 1px solid #eaeef2;
  vertical-align: top; }
table.fields th { background: #f6f8fa; font-size: 0.78rem; }
table.fields td.enum-cell input { font-size: 0.85rem; }
.fields-toolbar { margin-top: 0.4rem; }
.mut { color: #57606a; font-size: 0.8rem; }
.chk { display: flex; align-items: center; justify-content: center; }
"""


def render(payload: dict[str, Any]) -> str:
    data = {
        "generated_at": payload.get("generated_at", ""),
        "game_id": payload.get("game_id", ""),
        "existing_keys": payload.get("existing_keys") or [],
        "resources": payload.get("resources") or [],
    }
    # Embed data safely inside a <script> tag.
    data_json = json.dumps(data).replace("</", "<\\/")
    field_types_json = json.dumps(FIELD_TYPES)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinoa — Confirm resources to register</title>
<style>{CSS}</style>
</head>
<body>
<h1>Confirm resources to register</h1>
<p class="meta" id="meta"></p>

<div class="intro">
  These are the <strong>resources</strong> the scan proposes registering on Kinoa — items that can be
  <strong>sold or awarded as prizes</strong> (gear, chests, boosters, cosmetics), <em>not</em> internal currency.
  Nothing is sent anywhere from this page. Review the list, then:
  <ul>
    <li>Edit any name, key, description, or parameter.</li>
    <li><strong>Remove</strong> proposals that aren't really sellable/awardable resources.</li>
    <li><strong>Add</strong> resources the scan missed.</li>
    <li>When happy, <strong>Download</strong> the confirmed JSON (and tell the skill the file path) or <strong>Copy</strong> it into the chat.</li>
  </ul>
</div>

<div class="toolbar">
  <button class="primary" id="download">⬇ Download confirmed JSON</button>
  <button id="copy">⧉ Copy JSON</button>
  <button class="ghost" id="add">＋ Add resource</button>
  <span class="spacer"></span>
  <span id="status" class="ok">Ready</span>
</div>

<div id="resources"></div>

<script>
const INITIAL = {data_json};
const FIELD_TYPES = {field_types_json};
const KEY_RE = /{RESOURCE_KEY_RE}/;
const EXISTING = new Set((INITIAL.existing_keys || []).map(k => String(k).toLowerCase()));

// ---- working state: a plain array of resource objects we mutate in place ----
let state = (INITIAL.resources || []).map(normalizeResource);

function normalizeResource(r) {{
  return {{
    name: r.name || "",
    resourceKey: r.resourceKey || "",
    description: r.description || "",
    source: r.source || "",
    existing: !!r.existing || EXISTING.has(String(r.resourceKey || "").toLowerCase()),
    fields: (r.fields || []).map(normalizeField),
  }};
}}
function normalizeField(f) {{
  return {{
    name: f.name || "",
    field_type: FIELD_TYPES.includes(f.field_type) ? f.field_type : "string",
    required: !!f.required,
    default: (f.default === undefined || f.default === null) ? "" : String(f.default),
    enumeration_values: Array.isArray(f.enumeration_values) ? f.enumeration_values.join(", ")
                        : (f.enumeration_values || ""),
    description: f.description || "",
  }};
}}

const meta = document.getElementById("meta");
meta.innerHTML = "Generated <code>" + esc(INITIAL.generated_at) + "</code> &middot; game <code>"
  + esc(INITIAL.game_id) + "</code>";

function esc(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }}[c]));
}}

// ---- validation ----
function keyErrors() {{
  // returns map index -> error string
  const errs = {{}};
  const seen = {{}};
  state.forEach((r, i) => {{
    const k = (r.resourceKey || "").trim();
    if (!k) {{ errs[i] = "Key is required."; return; }}
    if (!KEY_RE.test(k)) {{ errs[i] = "Key must match ^[a-zA-Z][a-zA-Z0-9_-]*$"; return; }}
    const lk = k.toLowerCase();
    if (seen[lk] !== undefined) {{ errs[i] = "Duplicate key (also resource #" + (seen[lk]+1) + ")."; }}
    else seen[lk] = i;
    if (!r.name.trim()) errs[i] = (errs[i] ? errs[i] + " " : "") + "Name is required.";
  }});
  return errs;
}}

function refreshStatus() {{
  const errs = keyErrors();
  const nErr = Object.keys(errs).length;
  const el = document.getElementById("status");
  if (state.length === 0) {{ el.className = "warn"; el.textContent = "No resources — nothing to register."; }}
  else if (nErr === 0) {{ el.className = "ok"; el.textContent = state.length + " resource(s) ready"; }}
  else {{ el.className = "bad"; el.textContent = nErr + " resource(s) need fixing before export"; }}
  return errs;
}}

// ---- rendering ----
function render() {{
  const errs = refreshStatus();
  const root = document.getElementById("resources");
  root.innerHTML = "";
  state.forEach((r, i) => root.appendChild(resourceCard(r, i, errs[i])));
}}

function field(labelText, value, oninput, opts = {{}}) {{
  const wrap = document.createElement("div");
  if (opts.grow) wrap.className = "grow";
  const lab = document.createElement("label"); lab.textContent = labelText; wrap.appendChild(lab);
  const inp = opts.textarea ? document.createElement("textarea") : document.createElement("input");
  if (!opts.textarea) inp.type = "text";
  inp.value = value;
  if (opts.bad) inp.classList.add("bad");
  if (opts.placeholder) inp.placeholder = opts.placeholder;
  inp.addEventListener("input", e => oninput(e.target.value));
  wrap.appendChild(inp);
  return wrap;
}}

function resourceCard(r, i, err) {{
  const card = document.createElement("div");
  card.className = "resource" + (r.existing ? " existing" : "") + (err ? " invalid" : "");

  const head = document.createElement("div"); head.className = "rhead";
  head.appendChild(field("Name", r.name, v => {{ r.name = v; refreshStatus(); }}, {{grow:true}}));
  const keyBad = err && /[Kk]ey/.test(err);
  head.appendChild(field("Resource key", r.resourceKey, v => {{ r.resourceKey = v; render(); }},
                         {{grow:true, bad:keyBad, placeholder:"legendary_sword"}}));

  const badgeWrap = document.createElement("div");
  const badge = document.createElement("span");
  badge.className = "badge " + (r.existing ? "exists" : "new");
  badge.textContent = r.existing ? "on dashboard" : "new";
  badgeWrap.appendChild(document.createElement("label")).textContent = " ";
  badgeWrap.appendChild(badge);
  head.appendChild(badgeWrap);

  const del = document.createElement("button"); del.className = "danger"; del.textContent = "✕ Remove";
  del.addEventListener("click", () => {{ state.splice(i, 1); render(); }});
  const delWrap = document.createElement("div");
  delWrap.appendChild(document.createElement("label")).textContent = " ";
  delWrap.appendChild(del);
  head.appendChild(delWrap);
  card.appendChild(head);

  card.appendChild(field("Description", r.description, v => {{ r.description = v; }}, {{textarea:true}}));

  if (err) {{ const e = document.createElement("div"); e.className = "err"; e.textContent = err; card.appendChild(e); }}
  if (r.source) {{
    const s = document.createElement("div"); s.className = "src";
    s.innerHTML = "found at <code>" + esc(r.source) + "</code>";
    card.appendChild(s);
  }}

  card.appendChild(fieldsTable(r));
  return card;
}}

function fieldsTable(r) {{
  const wrap = document.createElement("div");
  const table = document.createElement("table"); table.className = "fields";
  table.innerHTML = "<thead><tr><th>Parameter</th><th>Type</th><th>Required</th>"
    + "<th>Allowed values (enum)</th><th>Default</th><th>Description</th><th></th></tr></thead>";
  const tbody = document.createElement("tbody");

  r.fields.forEach((f, j) => {{
    const tr = document.createElement("tr");

    tr.appendChild(td(inputCell(f.name, v => f.name = v, "param_name")));

    const sel = document.createElement("select");
    FIELD_TYPES.forEach(t => {{ const o = document.createElement("option"); o.value = t; o.textContent = t;
      if (t === f.field_type) o.selected = true; sel.appendChild(o); }});
    sel.addEventListener("change", e => {{ f.field_type = e.target.value; render(); }});
    tr.appendChild(td(sel));

    const chk = document.createElement("input"); chk.type = "checkbox"; chk.checked = f.required;
    chk.addEventListener("change", e => f.required = e.target.checked);
    tr.appendChild(td(chk, "chk"));

    const enumTd = td(inputCell(f.enumeration_values, v => f.enumeration_values = v, "a, b, c"), "enum-cell");
    if (f.field_type !== "enumeration") enumTd.querySelector("input").disabled = true;
    tr.appendChild(enumTd);

    tr.appendChild(td(inputCell(f.default, v => f.default = v, "")));
    tr.appendChild(td(inputCell(f.description, v => f.description = v, "")));

    const rm = document.createElement("button"); rm.className = "ghost danger"; rm.textContent = "✕";
    rm.title = "Remove parameter";
    rm.addEventListener("click", () => {{ r.fields.splice(j, 1); render(); }});
    tr.appendChild(td(rm));

    tbody.appendChild(tr);
  }});

  if (r.fields.length === 0) {{
    const tr = document.createElement("tr");
    const cell = document.createElement("td"); cell.colSpan = 7; cell.className = "mut";
    cell.textContent = "No parameters. A resource can be registered with none.";
    tr.appendChild(cell); tbody.appendChild(tr);
  }}

  table.appendChild(tbody); wrap.appendChild(table);

  const addF = document.createElement("button"); addF.className = "ghost"; addF.textContent = "＋ Add parameter";
  addF.addEventListener("click", () => {{
    r.fields.push(normalizeField({{name:"", field_type:"string", required:false}})); render();
  }});
  const ft = document.createElement("div"); ft.className = "fields-toolbar"; ft.appendChild(addF);
  wrap.appendChild(ft);
  return wrap;
}}

function inputCell(value, oninput, placeholder) {{
  const inp = document.createElement("input"); inp.type = "text"; inp.value = value || "";
  if (placeholder) inp.placeholder = placeholder;
  inp.addEventListener("input", e => oninput(e.target.value));
  return inp;
}}
function td(child, cls) {{ const t = document.createElement("td"); if (cls) t.className = cls; t.appendChild(child); return t; }}

// ---- export ----
function buildConfirmed() {{
  return {{
    confirmed_at: new Date().toISOString(),
    resources: state.map(r => {{
      const out = {{
        name: r.name.trim(),
        resourceKey: r.resourceKey.trim(),
        description: r.description.trim(),
        existing: !!r.existing,
        fields: r.fields.filter(f => f.name.trim()).map(f => {{
          const o = {{ name: f.name.trim(), field_type: f.field_type, required: !!f.required }};
          if (String(f.default).trim() !== "") o.default = f.default;
          if (f.description.trim()) o.description = f.description.trim();
          if (f.field_type === "enumeration") {{
            o.enumeration_values = String(f.enumeration_values).split(",").map(s => s.trim()).filter(Boolean);
          }}
          return o;
        }}),
      }};
      return out;
    }}),
  }};
}}

function warnIfInvalid() {{
  const errs = keyErrors();
  const n = Object.keys(errs).length;
  if (n > 0) return confirm(n + " resource(s) still have errors (bad/duplicate keys or missing names). "
    + "Export anyway? The skill will reject invalid keys.");
  return true;
}}

document.getElementById("download").addEventListener("click", () => {{
  if (!warnIfInvalid()) return;
  const blob = new Blob([JSON.stringify(buildConfirmed(), null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "kinoa-resources-confirmed.json";
  document.body.appendChild(a); a.click(); a.remove();
}});

document.getElementById("copy").addEventListener("click", async () => {{
  if (!warnIfInvalid()) return;
  const text = JSON.stringify(buildConfirmed(), null, 2);
  try {{ await navigator.clipboard.writeText(text); flash("Copied to clipboard"); }}
  catch (e) {{
    // Fallback for file:// where the async clipboard API may be blocked.
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta);
    ta.select(); document.execCommand("copy"); ta.remove(); flash("Copied to clipboard");
  }}
}});

document.getElementById("add").addEventListener("click", () => {{
  state.push(normalizeResource({{name:"", resourceKey:"", fields:[]}})); render();
  window.scrollTo(0, document.body.scrollHeight);
}});

function flash(msg) {{
  const el = document.getElementById("status"); const prev = el.textContent; const cls = el.className;
  el.className = "ok"; el.textContent = msg;
  setTimeout(() => {{ el.className = cls; refreshStatus(); }}, 1500);
}}

render();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="Path to JSON input. If omitted, read stdin.")
    parser.add_argument("--output", required=True, help="Path to write the HTML confirmation page.")
    parser.add_argument("--no-open", action="store_true",
                        help="Suppress auto-opening the page in the default browser (default: open).")
    args = parser.parse_args()

    raw = open(args.input).read() if args.input else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": "invalid_json", "detail": str(e)}))
        return 2

    html_doc = render(payload)
    with open(args.output, "w") as f:
        f.write(html_doc)

    abs_path = os.path.abspath(args.output)
    opened = False
    if not args.no_open:
        try:
            opened = webbrowser.open(f"file://{abs_path}")
        except Exception:
            opened = False

    print(json.dumps({"ok": True, "output": abs_path, "bytes": len(html_doc), "opened_in_browser": opened}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
