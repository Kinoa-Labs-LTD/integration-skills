#!/usr/bin/env python3
"""
Kinoa CSV Schema Infer — read a CSV's header row and sample values, infer a
Kinoa feature-schema column type per column, and emit a ready-to-POST SchemaDto
(or a review table). Pure parser — no network, no credentials.

This is the bridge for the "new schema from a CSV" branch of
kinoa-sync-feature-settings-integration: the developer drops a CSV, this infers
types, and the result pipes straight into
`kinoa-dashboard-feature-settings create-schema`.

Kinoa column types (com.kinoa.featuressettings…SchemaColumnType):
  integer, number, long, boolean, string, long_string, bundle_key, date,
  enumeration, version, object

Inference, evaluated per column over its non-empty cells (first match wins):
  boolean      every cell in {true,false,yes,no} (case-insensitive)
  integer      every cell a whole number within signed 32-bit range
  long         every cell a whole number, some outside 32-bit range
  number       every cell numeric with a fractional part
  version      every cell like 1.0.0 (>= two dots)
  date         every cell an ISO date / datetime (YYYY-MM-DD[...])
  object       every cell a JSON object/array ({…} or […])
  long_string  text whose longest cell exceeds 255 chars
  string       fallback
Low-cardinality text columns are flagged as enumeration candidates in the review
(but kept as `string`, since a schema field carries no allowed-value list — the
developer can override with --type col=enumeration if they want the label).

Subcommands:
  infer --csv PATH [--name NAME] [--delimiter ,] [--sample N]
        [--required all|none|nonempty] [--type COL=TYPE ...] [--emit full|body|fields]
      Analyze the CSV. --emit:
        full   (default) review object: {name,row_count,fields,schema_body,review}
        body   only the SchemaDto (pipe into create-schema)
        fields only the tableFields array (pipe into create-schema --fields-json)
"""

import argparse
import csv
import io
import json
import re
import sys

SCHEMA_COLUMN_TYPES = (
    "integer", "number", "long", "boolean", "string", "long_string",
    "bundle_key", "date", "enumeration", "version", "object",
)

INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1
BOOL_TOKENS = {"true", "false", "yes", "no"}
VERSION_RE = re.compile(r"^\d+(?:\.\d+){2,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?")
LONG_STRING_THRESHOLD = 255
ENUM_MAX_DISTINCT = 12


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def _looks_json(s):
    s = s.strip()
    return len(s) >= 2 and ((s[0] == "{" and s[-1] == "}") or (s[0] == "[" and s[-1] == "]"))


def infer_type(values):
    """Infer a SchemaColumnType from a column's non-empty string cells."""
    cells = [v.strip() for v in values if v is not None and v.strip() != ""]
    if not cells:
        return "string"

    if all(c.lower() in BOOL_TOKENS for c in cells):
        return "boolean"

    if all(_is_int(c) for c in cells):
        nums = [int(c) for c in cells]
        if all(INT32_MIN <= n <= INT32_MAX for n in nums):
            return "integer"
        return "long"

    if all(VERSION_RE.match(c) for c in cells):
        return "version"

    # numeric with a fractional part (pure ints already handled above)
    if all(_is_float(c) for c in cells):
        return "number"

    if all(DATE_RE.match(c) for c in cells):
        return "date"

    if all(_looks_json(c) for c in cells):
        return "object"

    if max(len(c) for c in cells) > LONG_STRING_THRESHOLD:
        return "long_string"

    return "string"


def _read_rows(path, delimiter):
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", newline="") as fh:
            text = fh.read()
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader]
    return rows


def _parse_type_overrides(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected COL=TYPE, got {item!r}")
        col, _, typ = item.partition("=")
        col, typ = col.strip(), typ.strip().lower()
        if typ not in SCHEMA_COLUMN_TYPES:
            raise ValueError(f"type must be one of {SCHEMA_COLUMN_TYPES}, got {typ!r}")
        out[col] = typ
    return out


def cmd_infer(args):
    try:
        overrides = _parse_type_overrides(args.type)
    except ValueError as e:
        print(json.dumps({"error": "invalid_type_override", "message": str(e)}, indent=2))
        return 2

    try:
        rows = _read_rows(args.csv, args.delimiter)
    except FileNotFoundError:
        print(json.dumps({"error": "file_not_found", "path": args.csv}, indent=2))
        return 2

    if not rows:
        print(json.dumps({"error": "empty_csv", "path": args.csv}, indent=2))
        return 2

    header = [h.strip() for h in rows[0]]
    data_rows = rows[1:]
    sample = data_rows if args.sample <= 0 else data_rows[: args.sample]

    fields, review = [], []
    for idx, col in enumerate(header):
        col_values = [r[idx] if idx < len(r) else "" for r in data_rows]
        sample_values = [r[idx] if idx < len(r) else "" for r in sample]
        nonempty = [v for v in col_values if v is not None and v.strip() != ""]

        inferred = infer_type(sample_values)
        chosen = overrides.get(col, inferred)

        distinct = sorted({v.strip() for v in nonempty})
        enum_candidate = (
            chosen == "string"
            and 0 < len(distinct) <= ENUM_MAX_DISTINCT
            and len(nonempty) >= 2 * len(distinct)
        )

        if args.required == "all":
            is_required = True
        elif args.required == "none":
            is_required = False
        else:  # nonempty: required iff the column has no blanks in the data
            is_required = len(nonempty) == len(col_values) and len(col_values) > 0

        fields.append({
            "name": col,
            "type": chosen,
            "isRequired": is_required,
            "level": 1,
            "order": idx,
        })
        note = []
        if col in overrides:
            note.append(f"overridden from inferred '{inferred}'")
        if enum_candidate:
            note.append(f"enumeration candidate ({len(distinct)} distinct) — override with --type {col}=enumeration if desired")
        review.append({
            "column": col,
            "inferred_type": inferred,
            "chosen_type": chosen,
            "distinct": len(distinct),
            "samples": distinct[:5],
            "isRequired": is_required,
            "note": "; ".join(note) or None,
        })

    schema_name = args.name or "ImportedSchema"
    schema_body = {
        "name": schema_name,
        "description": None,
        "versions": [{
            "version": "1",
            "order": 0,
            "useRanges": False,
            "tableFields": fields,
            "tableColumns": [],
            "tableFilters": [],
        }],
    }

    if args.emit == "body":
        print(json.dumps(schema_body, indent=2))
    elif args.emit == "fields":
        print(json.dumps(fields, indent=2))
    else:
        print(json.dumps({
            "name": schema_name,
            "csv": args.csv,
            "row_count": len(data_rows),
            "column_count": len(header),
            "fields": fields,
            "schema_body": schema_body,
            "review": review,
        }, indent=2))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_csv_schema_infer", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("infer", help="Infer a feature-schema from a CSV's headers + sample values.")
    p.add_argument("--csv", required=True, help="Path to the CSV, or '-' for stdin.")
    p.add_argument("--name", default="", help="Schema name (default: ImportedSchema).")
    p.add_argument("--delimiter", default=",", help="CSV delimiter. Default: ','.")
    p.add_argument("--sample", type=int, default=200, help="Max data rows to sample for inference (0 = all). Default: 200.")
    p.add_argument("--required", choices=("all", "none", "nonempty"), default="nonempty",
                   help="isRequired policy. 'nonempty' (default): required iff the column has no blank cells.")
    p.add_argument("--type", action="append", default=[],
                   help="Override an inferred type: COL=TYPE. Repeatable.")
    p.add_argument("--emit", choices=("full", "body", "fields"), default="full",
                   help="full (review, default) | body (SchemaDto for create-schema) | fields (tableFields array).")
    p.set_defaults(func=cmd_infer)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
