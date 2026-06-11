#!/usr/bin/env python3
"""Generate an HTML sync report for kinoa-sync-event-integration.

Reads a JSON payload describing the four event buckets plus the critical-
events callout, writes a self-contained HTML file the developer can open
in a browser.

Usage:
    cat report.json | python generate_report.py --output report.html
    python generate_report.py --input report.json --output report.html

Input JSON shape (all keys required, lists may be empty):

{
  "generated_at":           "2026-05-08T14:23:00Z",
  "game_id":                "<uuid>",
  "kinoa_events_path":      "<path or empty>",
  "player_state_strategy":  "FULL" | "DIFF",
  "session_start_auto_fires": true | false,
  "critical_events": [
    {"name", "integrated": true|false, "note"}, ...
  ],
  "predefined_integrated":     [{"name", "status", "params", "note"}, ...],
  "predefined_not_integrated": [{"name", "status", "params", "note"}, ...],
  "custom_integrated":         [{"name", "params", "note"}, ...],
  "custom_not_integrated":     [{"name", "params", "note"}, ...]
}

`params` is a list of objects: {"name", "kind", "system": bool, "extra"?}.
- For most kinds the rendered cell is `name:kind, name:kind, ...`
- For `kind == "enumeration"`, the allowed values from `extra` are shown in
  parens: `tier:enumeration(bronze,silver,gold)`
- System params (Kinoa predefined) and custom params (operator-added) are
  rendered together in one comma-separated list. The order follows the input.

The "note" field is a short human-readable status. The skill is responsible
for picking the wording (e.g., "newly published", "auto-fired by server",
"skipped by developer"). Critical events are flagged with ⭐ in their bucket
rows automatically by this script, based on the `critical_events` list.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import webbrowser
from typing import Any

CRITICAL_EVENT_NAMES = {"session_start", "payment", "watch_ad", "install"}


def _format_param(p: dict[str, Any]) -> str:
    name = str(p.get("name", ""))
    kind = str(p.get("kind", ""))
    extra = p.get("extra")
    if kind == "enumeration" and extra:
        # `extra` is typically a comma-separated string from the dashboard API,
        # but accept a list as well.
        if isinstance(extra, list):
            values = ",".join(str(v) for v in extra)
        else:
            values = str(extra)
        return f"{name}:{kind}({values})"
    return f"{name}:{kind}"


def _format_params(params: list[dict[str, Any]] | None) -> str:
    if not params:
        return "—"
    return ", ".join(_format_param(p) for p in params)


def _row(field: dict[str, Any], include_status: bool = False) -> str:
    name = str(field.get("name", ""))
    star = "⭐ " if name in CRITICAL_EVENT_NAMES else ""
    name_html = f"{star}{html.escape(name)}"
    status = html.escape(str(field.get("status", "")))
    params_text = _format_params(field.get("params"))
    params_cell = html.escape(params_text)
    note = html.escape(str(field.get("note", "")))
    status_cell = f"<td class='status'>{status}</td>" if include_status else ""
    return (
        "<tr>"
        f"<td class='name'>{name_html}</td>"
        f"{status_cell}"
        f"<td class='params'><code>{params_cell}</code></td>"
        f"<td class='note'>{note}</td>"
        "</tr>"
    )


def _section(title: str, css_class: str, fields: list[dict[str, Any]], include_status: bool = False) -> str:
    count = len(fields)
    if not fields:
        body = "<p class='empty'>None.</p>"
    else:
        status_header = "<th>Status</th>" if include_status else ""
        rows = "\n".join(_row(f, include_status=include_status) for f in fields)
        body = (
            "<table>"
            "<thead><tr>"
            "<th>Name</th>"
            f"{status_header}"
            "<th>Parameters</th>"
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


def _critical_section(critical: list[dict[str, Any]]) -> str:
    """Render the critical-events callout. Red when any are missing, green otherwise."""
    missing = [e for e in critical if not e.get("integrated", False)]
    all_good = not missing

    rows = []
    for e in critical:
        name = html.escape(str(e.get("name", "")))
        integrated = e.get("integrated", False)
        badge = (
            "<span class='badge ok'>integrated</span>"
            if integrated
            else "<span class='badge bad'>NOT integrated</span>"
        )
        note = html.escape(str(e.get("note", "")))
        rows.append(
            f"<tr><td class='name'><strong>{name}</strong></td><td>{badge}</td><td class='note'>{note}</td></tr>"
        )

    callout = (
        "<p class='callout-good'>All four critical events are integrated. Kinoa's calculated properties "
        "(ad-revenue analytics, install attribution, monetization / LTV / ARPU, session lifecycle) "
        "will populate correctly.</p>"
        if all_good
        else (
            "<p class='callout-bad'>"
            "<strong>One or more critical events are not integrated.</strong> "
            "Kinoa's calculated properties depend on these — without them, "
            "ad-revenue analytics, install attribution, monetization (LTV/ARPU), "
            "and session lifecycle metrics simply cannot be computed. "
            "Please prioritize the rows marked NOT integrated below."
            "</p>"
        )
    )

    css_class = "critical critical-ok" if all_good else "critical critical-bad"

    table = (
        "<table>"
        "<thead><tr><th>Event</th><th>Status</th><th>Note</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )

    return (
        f"<section class='{css_class}'>"
        "<h2>Critical events</h2>"
        f"{callout}"
        f"{table}"
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

/* Critical events: red when any missing, green when all integrated */
section.critical { border-width: 2px; }
section.critical-bad {
  border-color: #cf222e;
  border-left: 6px solid #cf222e;
  background: #ffebe9;
}
section.critical-bad h2 { color: #82071e; }
section.critical-ok {
  border-color: #2da44e;
  border-left: 6px solid #2da44e;
  background: #dafbe1;
}
section.critical-ok h2 { color: #116329; }
.callout-bad { color: #82071e; margin: 0.5rem 0 1rem 0; }
.callout-good { color: #116329; margin: 0.5rem 0 1rem 0; }
.badge { padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }
.badge.ok { background: #2da44e; color: white; }
.badge.bad { background: #cf222e; color: white; }

.empty { color: #57606a; font-style: italic; margin: 0; }
table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eaeef2; }
th { background: #f6f8fa; font-weight: 600; font-size: 0.9rem; }
section.critical-bad th { background: #ffd8d4; }
section.critical-ok th { background: #b4f0c0; }
td.status { color: #57606a; font-size: 0.9rem; }
td.params { font-size: 0.85rem; max-width: 520px; }
td.params code {
  background: #f6f8fa;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  word-break: break-word;
  display: inline-block;
  line-height: 1.6;
}
td.note { color: #1f2328; font-size: 0.9rem; }
"""


def render(payload: dict[str, Any]) -> str:
    generated_at = html.escape(str(payload.get("generated_at", "")))
    game_id = html.escape(str(payload.get("game_id", "")))
    events_path = html.escape(str(payload.get("kinoa_events_path", "")))
    strategy = html.escape(str(payload.get("player_state_strategy", "")))
    auto_fires = bool(payload.get("session_start_auto_fires", True))

    critical = payload.get("critical_events") or []
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

    auto_fires_label = "auto-fires session_start" if auto_fires else "explicit session_start emit"

    sections = "\n".join(
        [
            _critical_section(critical),
            _section("Predefined events — integrated", "integrated", pre_in, include_status=True),
            _section("Predefined events — NOT integrated", "not-integrated", pre_out, include_status=True),
            _section("Custom events — integrated", "integrated", cust_in),
            _section("Custom events — NOT integrated", "not-integrated", cust_out),
        ]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kinoa Event Integration Report</title>
<style>{CSS}</style>
</head>
<body>
<h1>Kinoa Event Integration Report</h1>
<p class="meta">
  Generated <code>{generated_at}</code>
  &middot; game <code>{game_id}</code>
  {f"&middot; KinoaEvents <code>{events_path}</code>" if events_path else ""}
  {f"&middot; player_state strategy <code>{strategy}</code>" if strategy else ""}
  &middot; session-open <code>{auto_fires_label}</code>
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
