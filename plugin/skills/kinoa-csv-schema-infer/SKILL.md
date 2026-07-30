---
name: kinoa-csv-schema-infer
description: Pure-parser utility that turns a CSV into a Kinoa feature-schema body. Reads the header row and sample values, infers a Kinoa column type per column (integer, number, long, boolean, string, long_string, date, version, object, enumeration, bundle_key), and emits a ready-to-POST SchemaDto (or a review table / tableFields array). No network, no credentials — this skill only analyzes and emits JSON; it never creates anything on the dashboard. Use when the user wants to infer column types from a CSV or generate the SchemaDto body. When they want the schema actually created and published in Kinoa, route via kinoa-api-integration schema-from-csv (the scoped Phase 5 run), which delegates here for the inference step. The workflow skill kinoa-sync-feature-settings-integration delegates to this for the "new schema from CSV" branch.
argument-hint: [infer --csv PATH --name NAME [--emit full|body|fields] [--type COL=TYPE]]
allowed-tools: Bash(python *) Bash(cat *) Read AskUserQuestion
---

# Kinoa CSV → Feature Schema

Reads a CSV's headers and sample rows and infers a Kinoa **feature-schema**:
which column is an `integer`, which is a `version`, which is a `date`, and so on.
It is a deterministic parser — **no HTTP, no `session.env`** — so it's safe to run
on any file and its output is reproducible.

It exists so the "I have a CSV, make a schema" path stays one clean step: infer →
pipe into `kinoa-dashboard-feature-settings create-schema`.

```bash
python "${CLAUDE_SKILL_DIR}/kinoa_csv_schema_infer.py" infer --csv PATH --name NAME [options]
```

## What it infers

Per column, over its non-empty cells, first match wins:

| Type | Rule |
|---|---|
| `boolean` | every cell ∈ {true, false, yes, no} (case-insensitive) |
| `integer` | every cell a whole number within signed 32-bit range |
| `long` | every cell a whole number, some beyond 32-bit |
| `version` | every cell like `1.0.0` (two or more dots) |
| `number` | every cell numeric with a fractional part |
| `date` | every cell an ISO date/datetime (`YYYY-MM-DD…`) |
| `object` | every cell a JSON object/array (`{…}` / `[…]`) |
| `long_string` | text whose longest cell exceeds 255 chars |
| `string` | fallback |

Why "first match wins" and not something cleverer: the order encodes specificity.
`1.0.0` is a version, not a number; a pure integer column is `integer`, not the
broader `number`. The thresholds (32-bit cutoff, 255-char long-string, the
date/version regexes) mirror how the backend's `SchemaColumnType` actually
coerces values, so what you infer is what the dashboard will accept.

Low-cardinality text columns are surfaced as **enumeration candidates** in the
review but kept as `string` — a schema field row carries no allowed-value list, so
forcing `enumeration` only changes the label. If the developer wants it, override
explicitly with `--type col=enumeration`.

## Options

| Flag | Meaning |
|---|---|
| `--csv PATH` | the CSV, or `-` for stdin |
| `--name NAME` | schema name (default `ImportedSchema`) |
| `--delimiter ,` | field delimiter |
| `--sample N` | max data rows sampled for inference (0 = all; default 200) |
| `--required all\|none\|nonempty` | `isRequired` policy. `nonempty` (default): a column is required iff it has no blank cells |
| `--type COL=TYPE` | override one column's type (repeatable) — for the cases inference can't see, e.g. `--type sku=bundle_key` |
| `--emit full\|body\|fields` | `full` (default) = review object; `body` = bare `SchemaDto` to pipe into `create-schema`; `fields` = bare `tableFields` array |

## Output shapes

- `--emit full` → `{ name, csv, row_count, column_count, fields[], schema_body{}, review[] }`.
  Show `review[]` to the developer — one row per column with `inferred_type`,
  `chosen_type`, `distinct`, `samples`, and any `note` — so they can sanity-check
  and correct before anything hits the API.
- `--emit body` → just the `SchemaDto`. This is the create-schema contract:
  ```bash
  python .../kinoa_csv_schema_infer.py infer --csv boosters.csv --name BoostersConfig --emit body \
    | python ../kinoa-dashboard-feature-settings/kinoa_dashboard_feature_settings.py create-schema
  ```
- `--emit fields` → just the `tableFields` array, for
  `create-schema --fields-json "$(…)"`.

## Recommended flow when used directly

1. Run `--emit full` and present the `review` table to the developer.
2. Collect any corrections and re-run with `--type COL=TYPE` overrides (and
   `--name`). Inference is a starting point, not a verdict — the developer owns
   the final types.
3. Re-emit with `--emit body`. That JSON is this skill's deliverable. If the
   developer also wants the schema created + published on the dashboard, hand
   off to the `schema-from-csv` scoped run of
   `kinoa-sync-feature-settings-integration` (which drives the
   `create-schema` / `publish-schema` admin calls) — don't drive them from here.
