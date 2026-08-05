# Input validation map — merge-plan page (all 4 entities)

Snapshot 2026-08-05 (audit of `generate_merge_plan_page.py`). Classification:
- **dashboard-real** — mirrors a confirmed server/dashboard constraint (keep; later source from the backend),
- **page-mechanics** — needed for the page/export contract itself (keep),
- **INVENTED** — a constraint the dashboard does NOT enforce (candidates for removal; over-forbidding legal data is the harm).

Status of invented rules: the resources `:`-family (#4 default, #5 enum values `:`/`=`, #6 description) is fully REMOVED 2026-08-05 (user order); module-14 doc-block grammar hardened in the same batch (`values=` named token + rejoin rule).
The rest are pending user decision — see the notes column.


## events

| Input | Rule | Message | Class |
|---|---|---|---|
| event name (new rows) | !String(r.name).trim() — empty name | the event name is required | page-mechanics |
| event name (new rows) | dup(r.name) — case-insensitive duplicate among shipped rows on the page (dupNames, line 717) | duplicate event name on this page | page-mechanics |
| event name (new rows) | String(r.name).length > 30 (plus maxlength=30 attribute at line 907) | maximum 30 characters | dashboard-real |
| event param name | !String(p.name).trim() — empty param name | the param name is required | page-mechanics |
| event param name | pdup(p.name) — duplicate among included params of this event (measured + proposed, line 972) | duplicate param name on this event | page-mechanics |
| event param name | String(p.name).length > 30 (maxlength=30 at line 1033) | maximum 30 characters | dashboard-real |
| event param kind | !EVENT_PARAM_KINDS.includes(p.kind) — kind outside [number, boolean, string, date, enumeration, string_array, number_array]; kindSelect renders a red '(unsuppor | (unsupported: <value>) / (choose kind) shown as red select option | dashboard-real |
| event param enumeration values (extra) | p.kind === 'enumeration' && !String(p.extra).trim() | an enumeration needs at least one value | dashboard-real |
| event param enumeration values (extra) | enumValuesTooLong(p.extra) — any comma-separated value trimmed length > 50 (function lines 751-753) | each value must be 50 characters or less | dashboard-real |
| event param kind for reserved system names (device_id/level/place/success/time/time_ms/wifi) | SYSTEM_PARAM_KINDS[name] !== undefined -> kind is force-coerced (lines 338-341, 1030-1032) and rendered as a disabled pinnedKind select (lines 1041-1042); on ex | the type is pinned by the event's built-in field — it must match the dashboard exactly / reserved system name measured a | dashboard-real |
| event param kind for params already on the adopted dashboard event | dashHit (same-name param exists in CUSTOM_EVENT_REGISTRY entry) -> p.kind is overwritten with the dashboard kind (line 1069) and rendered as a disabled pinnedKi | the type is pinned by the dashboard param — the sync never mutates existing params; rename if you mean a NEW param with  | dashboard-real |

## player_fields

| Input | Rule | Message | Class |
|---|---|---|---|
| field name | !String(r.name).trim() — empty name | the field name is required | page-mechanics |
| field name | dup(r.name) — case-insensitive duplicate among shipped page rows | duplicate field name on this page | page-mechanics |
| field name / derived path | !frPredef && pathDup(r) — the derived-or-overridden registered path occurs on more than one shipped row (pathCount map, lines 1153-1159); also flags the path in | another field registers the SAME path — rename one (the registered snake path must be unique) / duplicate registered pat | dashboard-real |
| field name + path (registry check) | FR_CALC[pathOf(r)] !== undefined — path matches a CALCULATED dashboard field from the live registry (row gate line 662; inputs lines 1227, 1286) | this path is a CALCULATED dashboard field — computed server-side, the game cannot write it; rename if you meant a differ | dashboard-real |
| field name + path (reserved namespace) | reservedFieldPath(pathOf(r)) — exact or prefix match against plugin-shipped RESERVED_PLAYER_FIELD_PATHS snapshot (function lines 264-266; applies only when no F | this path is RESERVED by the platform (base player-state namespace) — the server refuses the create ('path is reserved') | dashboard-real |
| path (external namespace message branch) | String(pathOf(r)).startsWith('calculated_fields.') — message-only branch inside firstBad for the reserved/calculated rules (not an independent bad condition) | external field namespace (calculated_fields.*) — values arrive from the data bucket; the game cannot register fields her | dashboard-real |
| field name (dashboard name uniqueness) | fieldTakenName(r, pathOf) — lowercased name in FR_NAMES while the path matches neither a predefined nor an existing custom field (function lines 631-637; row ga | this name is already taken on the dashboard (names are unique across ALL statuses); rename | dashboard-real |
| field name (shape) | !FIELD_NAME_RE.test(name) — regex at line 401: dot-separated segments of [A-Za-z_][A-Za-z0-9_]* with optional single spaces between tokens (row gates lines 654/ | letters, digits, _ and single spaces between tokens; dot-separated segments (spaces stay in the dashboard Name — the C#  | **INVENTED** |
| field name | String(r.name).length > 30 (maxlength=30 at line 1225) | maximum 30 characters | dashboard-real |
| registered path | pathOf(r).length > 100 (name input line 1229, path input line 1285) | the registered snake path must be unique and 100 characters or less / ... maximum 100 characters | dashboard-real |
| registered path (charset) | !FIELD_PATH_RE.test(pathOf(r)) — regex at line 409: ^[A-Za-z][A-Za-z0-9_\-]*(\.[A-Za-z0-9_\-]+)*$ (row gate line 665; path input line 1285) | letter first; letters, digits, _, - and dot separators; unique across existing fields; maximum 100 characters | dashboard-real |
| path override vs name (segment mapping) | pathSegMismatch(r, pathOf) — pathOf(r).split('.').length !== propOf(r).split('.').length (function lines 644-648; row gate line 665; path input line 1286) | the override maps per-segment onto the property chain — segment counts must match (nesting depth comes from nested prope | **INVENTED** |
| registered path (leaf/object conflict) | pathNodeConflict(path, allPaths) — another shipped field's path sits strictly inside this one or vice versa (function lines 640-643; row gate line 666; path inp | leaf/object conflict: another field's path sits inside this one (Wallet.Gold vs Wallet.Gold.Price — Gold cannot be a val | dashboard-real |
| field kind | !FIELD_KINDS.includes(r.kind) — outside [number, boolean, string, date, long_string, enumeration, version]; red '(unsupported)' select option (kindSelect lines  | (unsupported: <value>) / (choose kind) shown as red select option | dashboard-real |
| field kind (pinned on registry hits) | FR_PREDEF[path] or FR_CUSTOM[path].kind present -> r.kind is overwritten with the registry kind and rendered as a disabled pinnedKind select (lines 1252-1254, 1 | the kind is pinned by the dashboard's predefined field / the kind is pinned by the existing dashboard field | dashboard-real |
| field enumeration values (extra) | r.kind === 'enumeration' && (!String(r.extra).trim() \|\| enumValuesTooLong(r.extra)) (row gate line 669; input line 1330) | an enumeration needs at least one value / each value must be 50 characters or less | dashboard-real |

## feature_settings

| Input | Rule | Message | Class |
|---|---|---|---|
| schema name | !String(r.name).trim() — empty | the schema name is required | page-mechanics |
| schema name | sdup(r.name) — duplicate among shipped schemas on the page | duplicate schema name on this page | page-mechanics |
| schema name | String(r.name).length > 255 (maxlength=255 at line 1401) | maximum 255 characters | dashboard-real |
| schema columns (count) | noColumns — !(r.columns \|\| []).length flags the schema NAME input red (row gate line 674 requires at least one included column) | Schema should contain minimum 1 column (server rule) | dashboard-real |
| schema column name | !String(c.name).trim() — empty | the column name is required | page-mechanics |
| schema column name | cdup(c.name) — duplicate among included columns of this schema | duplicate column name in this schema | page-mechanics |
| schema column name (reserved namespace) | isReservedFsColumn(c.name) — lowercased trimmed name starts with 'filter:' OR raw name contains '<' (function lines 755-758; row gate line 677; input line 1451) | filters are configuration-level (IncludeFilters readers), not schema columns — the operator picks them on the configurat | dashboard-real |
| schema column name | String(c.name).length > 100 (maxlength=100 at line 1450) | maximum 100 characters | dashboard-real |
| schema column kind | !FS_COLUMN_KINDS.includes(c.kind) — outside [integer, number, string, boolean, bundle_key]; red '(unsupported)' select (kindSelect used at line 1458) | (unsupported: <value>) / (choose kind) shown as red select option | dashboard-real |
| setting key | !String(r.key).trim() — empty | the setting key is required | page-mechanics |
| setting key | kdup(r.key) — duplicate among shipped setting keys on the page | duplicate setting key on this page | page-mechanics |
| setting key | String(r.key).length > 100 (maxlength=100 at line 1515) | maximum 100 characters | dashboard-real |
| setting schema binding (dropdown) | !r.schema_name \|\| !schemaNames.includes(r.schema_name) — bound schema absent or unticked; dropdown renders a red '(missing: X)' / '(choose a schema)' / '(no s | (missing: <name>) / (choose a schema) / (no schemas defined above) | dashboard-real |

## resources

| Input | Rule | Message | Class |
|---|---|---|---|
| resource key | !RESOURCE_KEY_RE.test(r.key) — regex ^[a-zA-Z][a-zA-Z0-9_-]*$ (constant line 133; row gate line 681; input line 1605) | letter first; letters, digits, _ and - only | dashboard-real |
| resource key | dup(r.key) — duplicate key among shipped resources on the page | duplicate resource key on this page | page-mechanics |
| resource key | String(r.key).length > 100 (maxlength=100 at line 1604; row gate line 682) | maximum 100 characters | dashboard-real |
| resource name | !String(r.name).trim() — empty (row gate line 683) | the resource name is required | page-mechanics |
| resource name | ndup(r.name) — duplicate display name among shipped resources on the page | duplicate resource name on this page (the server also enforces uniqueness across ALL statuses, incl. DEPRECATED) | page-mechanics |
| resource name | String(r.name).length > 100 (maxlength=100 at line 1614) | maximum 100 characters | dashboard-real |
| resource description | String(r.description).length > 100 (maxlength=100 at line 1623; row gate line 684) | maximum 100 characters | dashboard-real |
| resource field name | !RES_FIELD_NAME_RE.test(f.name) — regex ^[a-zA-Z][a-zA-Z0-9_-]*$ (constant line 730; row gate line 688; input line 1652; note: empty name fails this regex too,  | letter first; letters, digits, _ and - only (the name is a JSON body key and a code doc-block token) | **INVENTED** |
| resource field name | fdup(f.name) — duplicate among included fields of this resource (line 1629; row gate line 688) | duplicate field name on this resource | page-mechanics |
| resource field name | String(f.name).length > 100 (maxlength=100 at line 1651; row gate line 689) | maximum 100 characters | dashboard-real |
| resource field type | !RESOURCE_FIELD_TYPES.includes(f.field_type) — outside [number, string, boolean, date, enumeration]; red '(unsupported)' select (kindSelect used at line 1660; r | (unsupported: <value>) / (choose kind) shown as red select option | dashboard-real |
| resource field DEFAULT value | resDefaultBad(f): d.includes(':') — a colon ANYWHERE in the default of ANY field_type (incl. string, where it is the ONLY check); predicate at line 738, input w | ':' is not representable in the code doc-block carrier | **INVENTED** |
| resource field DEFAULT value (number type) | resDefaultBad: f.field_type === 'number' && !/^-?\d+(\.\d+)?$/.test(d.trim()) (line 741) | must match the field type (number/boolean/date) | dashboard-real |
| resource field DEFAULT value (boolean type) | resDefaultBad: f.field_type === 'boolean' && !/^(true\|false)$/i.test(d.trim()) (line 742) | must match the field type (number/boolean/date) | dashboard-real |
| resource field DEFAULT value (enumeration type) | resDefaultBad: f.field_type === 'enumeration' && !(f.enumeration_values \|\| []).includes(d.trim()) (line 743) | the default must be one of the enumeration values | dashboard-real |
| resource field enumeration values | resEnumBad: !vals.length — no enumeration values (line 733; row gate line 691) | an enumeration needs at least one value | dashboard-real |
| resource field enumeration values | resEnumBad: vals.some(v => v.includes(':') \|\| v.includes('=')) — any value containing ':' OR '=' (line 733) | comma-separated; ':' and '=' are not representable in the code doc-block carrier | **INVENTED** |
| resource field description | String(f.description).includes(':') — colon anywhere in the per-field description (input bad at line 1682; row gate line 693) | ':' is not representable in the code doc-block carrier | **INVENTED** |

## shared

| Input | Rule | Message | Class |
|---|---|---|---|
| any kind/type select (all entities) | kindSelect: value not in the closed vocabulary renders a selected red option '(unsupported: <value>)' or '(choose kind)' with class 'bad' (lines 513-517) | (unsupported: <value>) / (choose kind) | page-mechanics |
| export gate (Download / Copy buttons) | document.querySelectorAll('input.bad, select.bad').length > 0 disables both buttons (lines 466-475) | N validation error(s) — fix to enable export | page-mechanics |
| export gate (open editors) | any included row with editing === true across all five lists blocks export (lines 470-475) | N row(s) open for editing — tap ✓ done to confirm | page-mechanics |
| whole page (payload version) | DATA.payload_version > PAYLOAD_VERSION (page supports 1) -> banner injected, download/copy/add buttons disabled, render aborted (lines 299-301, 437-451) | This page is OLDER than the payload (payload_version N > supported 1) — export is disabled; update the kinoa-dashboard p | page-mechanics |
| producer payload (Python side, row ids) | len(ids) != len(set(ids)) or any id is None across events/player_fields/feature_settings(schemas+settings)/resources -> exit 2, page not generated (lines 1899-1 | every row needs a unique non-null id across all sections | page-mechanics |
| producer payload (Python side, JSON shape) | json.loads fails or payload is not a dict -> exit 2 with {ok:false, error:'invalid_json'\|'invalid_payload'} (lines 1890-1898) | invalid_json: <parser message> / expected a JSON object | page-mechanics |

## Invented rules — analysis

| # | Rule | Verdict |
|---|---|---|
| 1 | fields: name shape `FIELD_NAME_RE` (letters/digits/_/single spaces, dot segments) | KEEP for now — not a dashboard mirror but load-bearing for the page contract: the Name derives the C# property chain byte-for-byte. Reclassify as page-mechanics. |
| 2 | fields: path override segment-count match | KEEP — pure code-carrier mechanics ([JsonPropertyName] per segment); without it the implementation strategy breaks. Reclassify as page-mechanics. |
| 3 | resources: field name charset `RES_FIELD_NAME_RE` | RELAX candidate — JSON body keys are unrestricted server-side; the charset came from the doc-block grammar + key-charset analogy. Needs backend confirmation before relaxing. |
| 4 | resources: `:` in DEFAULT value | REMOVED 2026-08-05 — dashboard stores plain values; `ratio 1:2` is legal. |
| 5 | resources: `:`/`=` in enum values | REMOVED 2026-08-05 — module-14 grammar hardened the same day (`values=` named token + rejoin rule), so the carrier now represents `:`/`=` in values. |
| 6 | resources: `:` in field description | REMOVED 2026-08-05 (user order). |

Follow-ups resolved 2026-08-05:
- module-14 carrier grammar hardened (`values=` named token; rejoin rule closes `:` inside
  values/default/desc; legacy positional enum form still parse-accepted). Residual
  unrepresentables: a comma inside a single enum value; the token-lookalike rejoin corner.
- planner verified: absent default/description/enum-values are carried "verbatim when
  present" and never diffed (readback cannot confirm extras) — an absent default is a
  no-op, never a clear; no perpetual-diff risk from page-authored `:` values.
- execution layer safe: the sync workflow passes fields via `--fields-json` (JSON array),
  not the positional `--field NAME:TYPE:...` CLI form.
