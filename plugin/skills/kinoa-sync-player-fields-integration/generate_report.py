#!/usr/bin/env python3
"""Generate an HTML sync report for kinoa-sync-player-fields-integration.

Reads a JSON payload describing the four buckets of fields (predefined
integrated / not integrated; custom integrated / not integrated) and
writes a self-contained HTML file the developer can open in a browser.

Usage:
    cat report.json | python generate_report.py --output report.html
    python generate_report.py --input report.json --output report.html

Input JSON shape (all keys required, lists may be empty):

{
  "generated_at":              "2026-05-08T14:23:00Z",
  "game_id":                   "<uuid>",
  "kinoa_player_state_path":   "<path or empty>",
  "predefined_integrated":     [{"name", "path", "kind", "note"}, ...],
  "predefined_not_integrated": [{"name", "path", "kind", "note", "state"}, ...],
  "custom_integrated":         [{"name", "path", "kind", "note"}, ...],
  "custom_not_integrated":     [{"name", "path", "kind", "note"}, ...]
}

The "note" field is a short human-readable status (e.g. "newly activated",
"already active", "skipped by developer"). It's rendered as-is — the skill
is responsible for choosing the wording.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import webbrowser
from typing import Any


def _row(field: dict[str, Any]) -> str:
    name = html.escape(str(field.get("name", "")))
    path = html.escape(str(field.get("path", "")))
    kind = html.escape(str(field.get("kind", "")))
    note = html.escape(str(field.get("note", "")))
    state = field.get("state")
    state_cell = f"<td class='state'>{html.escape(str(state))}</td>" if state else ""
    return (
        "<tr>"
        f"<td class='name'>{name}</td>"
        f"<td class='path'><code>{path}</code></td>"
        f"<td class='kind'>{kind}</td>"
        f"{state_cell}"
        f"<td class='note'>{note}</td>"
        "</tr>"
    )


def _section(title: str, css_class: str, fields: list[dict[str, Any]], include_state: bool = False) -> str:
    count = len(fields)
    if not fields:
        body = "<p class='empty'>None.</p>"
    else:
        state_header = "<th>State</th>" if include_state else ""
        rows = "\n".join(_row(f) for f in fields)
        body = (
            "<table>"
            "<thead><tr>"
            "<th>Name</th><th>Path</th><th>Kind</th>"
            f"{state_header}"
            "<th>Note</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
        )
    return (
        f"<section class='{css_class}'>"
        f"<h2>{html.escape(title)} <span class='count'>({count})</span></h2>"
        f"{body}"
        "</section>"
    )


CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1100px;
  margin: 2rem auto;
  padding: 0 1.5rem;
  color: #1f2328;
  line-height: 1.5;
}
h1 { margin-bottom: 0.25rem; }
.meta { color: #57606a; font-size: 0.9rem; margin-bottom: 2rem; }
.meta code { background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 4px; }
.summary { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }
.summary .card {
  flex: 1 1 220px;
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid #d0d7de;
}
.summary .card .n { font-size: 1.8rem; font-weight: 600; }
.summary .card .label { font-size: 0.85rem; color: #57606a; }
section { margin-bottom: 2rem; padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid #d0d7de; }
section h2 { margin-top: 0; font-size: 1.15rem; }
section h2 .count { color: #57606a; font-weight: 400; font-size: 0.95rem; }
section.integrated { border-left: 4px solid #2da44e; }
section.not-integrated { border-left: 4px solid #bf8700; background: #fff8c5; }
.callout-missing { padding: 0.75rem 1rem; border-radius: 8px; border: 1px solid #bf8700;
  border-left: 4px solid #bf8700; background: #fff8c5; }
section.empty-section { opacity: 0.7; }
.empty { color: #57606a; font-style: italic; margin: 0; }
table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eaeef2; }
th { background: #f6f8fa; font-weight: 600; font-size: 0.9rem; }
td.path code { background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.85rem; }
td.kind, td.state { color: #57606a; font-size: 0.9rem; }
td.note { color: #1f2328; font-size: 0.9rem; }
"""


def render(payload: dict[str, Any]) -> str:
    generated_at = html.escape(str(payload.get("generated_at", "")))
    game_id = html.escape(str(payload.get("game_id", "")))
    state_path = html.escape(str(payload.get("kinoa_player_state_path", "")))

    pre_in = payload.get("predefined_integrated") or []
    pre_out = payload.get("predefined_not_integrated") or []
    cust_in = payload.get("custom_integrated") or []
    cust_out = payload.get("custom_not_integrated") or []

    summary_cards = "".join(
        f"<div class='card'><div class='n'>{len(items)}</div><div class='label'>{label}</div></div>"
        for items, label in [
            (pre_in, "Predefined integrated"),
            (pre_out, "Predefined NOT integrated"),
            (cust_in, "Custom integrated"),
            (cust_out, "Custom NOT integrated"),
        ]
    )

    # Missing predefined fields don't break the integration — but every dashboard
    # feature fed by them (calculated properties, segmentation, analytics) will
    # sit empty. Say so explicitly rather than leaving the yellow bucket mute.
    missing_callout = ""
    if pre_out:
        names = ", ".join(
            f"<code>{html.escape(str(f.get('name', '')))}</code>" for f in pre_out
        )
        missing_callout = (
            "<p class='callout-missing'>"
            "<strong>Some predefined fields are not integrated.</strong> "
            "The integration will keep working without them — but Kinoa receives no data "
            f"for {names}, so any calculated properties, segments, or analytics that rely "
            "on these fields will not be computed. We recommend implementing them in the "
            "game if possible; re-run the player-fields sync afterwards to refresh this report."
            "</p>"
        )

    sections = "\n".join(
        [
            _section("Predefined fields — integrated", "integrated", pre_in),
            _section(
                "Predefined fields — NOT integrated",
                "not-integrated",
                pre_out,
                include_state=True,
            ),
            _section("Custom fields — integrated", "integrated", cust_in),
            _section("Custom fields — NOT integrated", "not-integrated", cust_out),
        ]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kinoa Player Fields Integration Report</title>
<style>{CSS}</style>
</head>
<body>
<h1>Kinoa Player Fields Integration Report</h1>
<p class="meta">
  Generated <code>{generated_at}</code>
  &middot; game <code>{game_id}</code>
  {f"&middot; KinoaPlayerState <code>{state_path}</code>" if state_path else ""}
</p>
<div class="summary">{summary_cards}</div>
{missing_callout}
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
