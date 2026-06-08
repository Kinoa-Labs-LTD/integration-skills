#!/usr/bin/env python3
"""Generate an HTML integration report for kinoa-sync-feature-settings-integration.

Reads a JSON payload describing the feature-settings integration outcome —
schema, setting, configuration, the generated facade, and the end-to-end runtime
verification — and writes a self-contained HTML file the developer can open.

Usage:
    cat report.json | python generate_report.py --output report.html
    python generate_report.py --input report.json --output report.html

Input JSON shape (lists/objects may be empty; missing keys render gracefully):

{
  "generated_at":  "2026-06-04T14:23:00Z",
  "game_id":       "<uuid>",
  "facade_path":   "<path to the generated FeatureSettingsFacade or empty>",
  "verification": {
    "player_id": "<uuid>", "setting_key": "BoostersConfig", "version": "1",
    "runtime_status": "OK" | "KEY_NOT_FOUND" | "VERSION_NOT_FOUND" | "DEFAULT_NOT_FOUND",
    "resolved": true|false, "row_count": 3, "note": "..."
  },
  "schema": {
    "id": "...", "name": "BoostersConfig", "status": "ACTIVE", "version": "1",
    "source": "existing" | "csv",
    "fields": [{"name": "id", "type": "integer", "isRequired": true}, ...]
  },
  "setting":       {"id": "...", "key": "BoostersConfig", "name": "Boosters"},
  "configuration": {"id": "...", "name": "v1 defaults", "status": "SCHEDULED",
                    "is_default": true, "schema_version": "1", "row_count": 3,
                    "test_players": ["..."]},
  "next_steps": ["...", "..."]
}

The verification block drives the top callout: green when `resolved` is true and
`runtime_status == "OK"`, red otherwise — the integration is only "done" when a
player actually resolves the config through the public runtime endpoint.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import webbrowser
from typing import Any


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def _verification_section(v: dict[str, Any]) -> str:
    resolved = bool(v.get("resolved", False)) and str(v.get("runtime_status", "")).upper() == "OK"
    player = _esc(v.get("player_id"))
    key = _esc(v.get("setting_key"))
    version = _esc(v.get("version"))
    status = _esc(v.get("runtime_status"))
    rows = _esc(v.get("row_count"))
    note = _esc(v.get("note"))

    if resolved:
        callout = (
            "<p class='callout-good'>The configuration resolves end-to-end. A real "
            "<code>POST featureset.kinoa.io/features-configurations</code> for this player returned "
            "the published config — exactly the path the shipped application takes.</p>"
        )
        css = "critical critical-ok"
    else:
        callout = (
            "<p class='callout-bad'><strong>The runtime fetch did not return the configuration.</strong> "
            f"Setting status came back <code>{status or '—'}</code>. Until this reads <code>OK</code>, the "
            "application will not see the config. Check: schema published (ACTIVE), configuration published "
            "(SCHEDULED), marked default (or the player is a test player), and the setting key + version match.</p>"
        )
        css = "critical critical-bad"

    table = (
        "<table><tbody>"
        f"<tr><th>Player</th><td><code>{player or '—'}</code></td></tr>"
        f"<tr><th>Setting key</th><td><code>{key or '—'}</code></td></tr>"
        f"<tr><th>Version</th><td><code>{version or '—'}</code></td></tr>"
        f"<tr><th>Runtime status</th><td><code>{status or '—'}</code></td></tr>"
        f"<tr><th>Rows returned</th><td>{rows or '—'}</td></tr>"
        + (f"<tr><th>Note</th><td>{note}</td></tr>" if note else "")
        + "</tbody></table>"
    )
    return f"<section class='{css}'><h2>End-to-end verification</h2>{callout}{table}</section>"


def _fields_table(fields: list[dict[str, Any]]) -> str:
    if not fields:
        return "<p class='empty'>No fields.</p>"
    rows = "".join(
        "<tr>"
        f"<td class='name'>{_esc(f.get('name'))}</td>"
        f"<td><code>{_esc(f.get('type'))}</code></td>"
        f"<td>{'required' if f.get('isRequired') else 'optional'}</td>"
        "</tr>"
        for f in fields
    )
    return (
        "<table><thead><tr><th>Field</th><th>Type</th><th>Required</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _schema_section(s: dict[str, Any]) -> str:
    if not s:
        return ""
    source = str(s.get("source", "")).lower()
    source_label = {"existing": "reused an existing schema", "csv": "created from CSV"}.get(source, source)
    meta = (
        f"<p class='sub'>name <code>{_esc(s.get('name'))}</code> "
        f"&middot; status <code>{_esc(s.get('status'))}</code> "
        f"&middot; version <code>{_esc(s.get('version'))}</code>"
        + (f" &middot; {_esc(source_label)}" if source_label else "")
        + f" &middot; id <code>{_esc(s.get('id'))}</code></p>"
    )
    return f"<section class='block'><h2>Schema</h2>{meta}{_fields_table(s.get('fields') or [])}</section>"


def _setting_section(s: dict[str, Any]) -> str:
    if not s:
        return ""
    body = (
        "<table><tbody>"
        f"<tr><th>Key (runtime)</th><td><code>{_esc(s.get('key'))}</code></td></tr>"
        f"<tr><th>Name</th><td>{_esc(s.get('name'))}</td></tr>"
        f"<tr><th>Id</th><td><code>{_esc(s.get('id'))}</code></td></tr>"
        "</tbody></table>"
    )
    return f"<section class='block'><h2>Setting</h2>{body}</section>"


def _configuration_section(c: dict[str, Any]) -> str:
    if not c:
        return ""
    testers = c.get("test_players") or []
    testers_cell = ", ".join(_esc(t) for t in testers) if testers else "—"
    body = (
        "<table><tbody>"
        f"<tr><th>Name</th><td>{_esc(c.get('name'))}</td></tr>"
        f"<tr><th>Status</th><td><code>{_esc(c.get('status'))}</code></td></tr>"
        f"<tr><th>Default</th><td>{'yes' if c.get('is_default') else 'no'}</td></tr>"
        f"<tr><th>Schema version</th><td><code>{_esc(c.get('schema_version'))}</code></td></tr>"
        f"<tr><th>Data rows</th><td>{_esc(c.get('row_count'))}</td></tr>"
        f"<tr><th>Test players</th><td>{testers_cell}</td></tr>"
        f"<tr><th>Id</th><td><code>{_esc(c.get('id'))}</code></td></tr>"
        "</tbody></table>"
    )
    return f"<section class='block'><h2>Configuration</h2>{body}</section>"


def _next_steps_section(steps: list[str]) -> str:
    if not steps:
        return ""
    items = "".join(f"<li>{_esc(s)}</li>" for s in steps)
    return f"<section class='block'><h2>Next steps</h2><ul>{items}</ul></section>"


CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1000px; margin: 2rem auto; padding: 0 1.5rem; color: #1f2328; line-height: 1.5; }
h1 { margin-bottom: 0.25rem; }
.meta { color: #57606a; font-size: 0.9rem; margin-bottom: 2rem; }
.meta code, .sub code, td code, th code { background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 4px; }
.sub { color: #57606a; font-size: 0.9rem; margin: 0 0 0.75rem 0; }
section { margin-bottom: 2rem; padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid #d0d7de; }
section h2 { margin-top: 0; font-size: 1.15rem; }
section.block { border-left: 4px solid #0969da; }
section.critical { border-width: 2px; }
section.critical-bad { border-color: #cf222e; border-left: 6px solid #cf222e; background: #ffebe9; }
section.critical-bad h2 { color: #82071e; }
section.critical-ok { border-color: #2da44e; border-left: 6px solid #2da44e; background: #dafbe1; }
section.critical-ok h2 { color: #116329; }
.callout-bad { color: #82071e; margin: 0.5rem 0 1rem 0; }
.callout-good { color: #116329; margin: 0.5rem 0 1rem 0; }
.empty { color: #57606a; font-style: italic; margin: 0; }
table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eaeef2; vertical-align: top; }
thead th { background: #f6f8fa; font-weight: 600; font-size: 0.9rem; }
tbody th { width: 180px; color: #57606a; font-weight: 600; font-size: 0.9rem; }
td.name { font-weight: 600; }
ul { margin: 0.5rem 0; padding-left: 1.25rem; }
li { margin: 0.25rem 0; }
"""


def render(payload: dict[str, Any]) -> str:
    generated_at = _esc(payload.get("generated_at"))
    game_id = _esc(payload.get("game_id"))
    facade_path = _esc(payload.get("facade_path"))

    sections = "\n".join(filter(None, [
        _verification_section(payload.get("verification") or {}),
        _schema_section(payload.get("schema") or {}),
        _setting_section(payload.get("setting") or {}),
        _configuration_section(payload.get("configuration") or {}),
        _next_steps_section(payload.get("next_steps") or []),
    ]))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kinoa Feature Settings Integration Report</title>
<style>{CSS}</style>
</head>
<body>
<h1>Kinoa Feature Settings Integration Report</h1>
<p class="meta">
  Generated <code>{generated_at}</code>
  &middot; game <code>{game_id}</code>
  {f"&middot; facade <code>{facade_path}</code>" if facade_path else ""}
</p>
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
