#!/usr/bin/env python3
"""Generate an HTML registration report for kinoa-sync-resource-template-integration.

Reads a JSON payload describing what happened during a resource-template
registration run and writes a self-contained HTML file the developer can open
in a browser. This is the read-only *record* of the sync — the interactive
confirmation step is a separate page (generate_confirm_page.py).

Usage:
    cat report.json | python generate_report.py --output report.html
    python generate_report.py --input report.json --output report.html

Input JSON shape (all keys optional, lists may be empty):

{
  "generated_at":       "2026-07-09T14:23:00Z",
  "game_id":            "<uuid>",
  "kinoa_resources_path": "<path to generated KinoaResources or empty>",
  "service_root":       "<monorepo service dir or empty>",
  "created":     [{"name", "key", "status", "fields", "note"}, ...],
  "updated":     [{"name", "key", "status", "fields", "note"}, ...],
  "activated":   [{"name", "key", "status", "fields", "note"}, ...],
  "unchanged":   [{"name", "key", "status", "fields", "note"}, ...],
  "skipped":     [{"name", "key", "status", "fields", "note"}, ...]
}

`fields` is a list of {"name","field_type","required"?,"enumeration_values"?}.
Rendered as `name:type, name:type(a|b|c) req`.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import webbrowser
from typing import Any


def _format_field(f: dict[str, Any]) -> str:
    name = str(f.get("name", ""))
    ftype = str(f.get("field_type", ""))
    label = f"{name}:{ftype}"
    if ftype == "enumeration":
        vals = f.get("enumeration_values")
        if isinstance(vals, list) and vals:
            label += "(" + "|".join(str(v) for v in vals) + ")"
    if f.get("required"):
        label += " req"
    return label


def _format_fields(fields: list[dict[str, Any]] | None) -> str:
    if not fields:
        return "—"
    return ", ".join(_format_field(f) for f in fields)


def _row(item: dict[str, Any]) -> str:
    name = html.escape(str(item.get("name", "")))
    key = html.escape(str(item.get("key", item.get("resourceKey", ""))))
    status = html.escape(str(item.get("status", "")))
    fields_cell = html.escape(_format_fields(item.get("fields")))
    note = html.escape(str(item.get("note", "")))
    return (
        "<tr>"
        f"<td class='name'>{name}</td>"
        f"<td class='key'><code>{key}</code></td>"
        f"<td class='status'>{status}</td>"
        f"<td class='params'><code>{fields_cell}</code></td>"
        f"<td class='note'>{note}</td>"
        "</tr>"
    )


def _section(title: str, css_class: str, items: list[dict[str, Any]]) -> str:
    count = len(items)
    if not items:
        body = "<p class='empty'>None.</p>"
    else:
        rows = "\n".join(_row(i) for i in items)
        body = (
            "<table><thead><tr>"
            "<th>Name</th><th>Key</th><th>Status</th><th>Parameters</th><th>Note</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    return (
        f"<section class='{css_class}'>"
        f"<h2>{html.escape(title)} <span class='count'>({count})</span></h2>"
        f"{body}</section>"
    )


CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1100px; margin: 2rem auto; padding: 0 1.5rem; color: #1f2328; line-height: 1.5; }
h1 { margin-bottom: 0.25rem; }
.meta { color: #57606a; font-size: 0.9rem; margin-bottom: 2rem; }
.meta code { background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 4px; }
.summary { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }
.summary .card { flex: 1 1 160px; padding: 1rem; border-radius: 8px; border: 1px solid #d0d7de; }
.summary .card .n { font-size: 1.8rem; font-weight: 600; }
.summary .card .label { font-size: 0.85rem; color: #57606a; }
section { margin-bottom: 2rem; padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid #d0d7de; }
section h2 { margin-top: 0; font-size: 1.15rem; }
section h2 .count { color: #57606a; font-weight: 400; font-size: 0.95rem; }
section.created { border-left: 4px solid #8250df; }
section.activated { border-left: 4px solid #2da44e; }
section.updated { border-left: 4px solid #0969da; }
section.unchanged { border-left: 4px solid #57606a; }
section.skipped { border-left: 4px solid #bf8700; background: #fff8c5; }
.empty { color: #57606a; font-style: italic; margin: 0; }
table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eaeef2; }
th { background: #f6f8fa; font-weight: 600; font-size: 0.9rem; }
td.status { color: #57606a; font-size: 0.9rem; }
td.key code, td.params code { background: #f6f8fa; padding: 0.15rem 0.4rem; border-radius: 4px;
  word-break: break-word; display: inline-block; line-height: 1.6; }
td.params { font-size: 0.85rem; max-width: 480px; }
td.note { font-size: 0.9rem; }
"""


def render(payload: dict[str, Any]) -> str:
    generated_at = html.escape(str(payload.get("generated_at", "")))
    game_id = html.escape(str(payload.get("game_id", "")))
    res_path = html.escape(str(payload.get("kinoa_resources_path", "")))
    service_root = html.escape(str(payload.get("service_root", "")))

    created = payload.get("created") or []
    updated = payload.get("updated") or []
    activated = payload.get("activated") or []
    unchanged = payload.get("unchanged") or []
    skipped = payload.get("skipped") or []

    summary_cards = "".join(
        f"<div class='card'><div class='n'>{len(items)}</div><div class='label'>{label}</div></div>"
        for items, label in [
            (created, "Created"),
            (activated, "Activated"),
            (updated, "Updated"),
            (unchanged, "Unchanged"),
            (skipped, "Skipped"),
        ]
    )

    sections = "\n".join([
        _section("Created (new drafts)", "created", created),
        _section("Activated (DRAFT → ACTIVE)", "activated", activated),
        _section("Updated", "updated", updated),
        _section("Unchanged (already registered)", "unchanged", unchanged),
        _section("Skipped by developer", "skipped", skipped),
    ])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kinoa Resource Registration Report</title>
<style>{CSS}</style>
</head>
<body>
<h1>Kinoa Resource Registration Report</h1>
<p class="meta">
  Generated <code>{generated_at}</code>
  &middot; game <code>{game_id}</code>
  {f"&middot; KinoaResources <code>{res_path}</code>" if res_path else ""}
  {f"&middot; service <code>{service_root}</code>" if service_root else ""}
</p>
<div class="summary">{summary_cards}</div>
{sections}
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="Path to JSON input. If omitted, read stdin.")
    parser.add_argument("--output", required=True, help="Path to write the HTML report.")
    parser.add_argument("--no-open", action="store_true",
                        help="Suppress auto-opening the report in the default browser (default: open).")
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
