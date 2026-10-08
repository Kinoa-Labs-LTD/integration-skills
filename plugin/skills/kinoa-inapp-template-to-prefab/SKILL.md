---
name: kinoa-inapp-template-to-prefab
description: Visualises a Kinoa in-app template as a Unity uGUI prefab inside the developer's open Unity Editor — fetches the template structure from the Dashboard by id, probes the game's existing popup prefabs for UI conventions, positions every slot from the layout artifact (`<template_key>.layout.json`) of kinoa-inapp-template-from-image — an existing one, or one that skill derives from the template's tip image — generates the prefab plan plus a C# view that binds InAppMessage data and wires every button's click action, and builds the prefab through the connected Unity MCP server. Use when someone wants "a prefab for this in-app template", "visualise template X in Unity", "generate the popup view for the one_cta template", or "turn the dashboard in-app template into a Unity popup". Requires a running Unity MCP. NOT for creating the template itself (that is kinoa-inapp-template-from-image) and NOT for SDK integration of messaging services (that is the /kinoa skill shipped in the SDK).
argument-hint: [--template-id <uuid>] [--layout-artifact <template_key>.layout.json | --build build_result.json] [--prefabs <Name.prefab>,...]
allowed-tools: Bash(python *) Bash(mkdir *) Bash(mv *) Bash(cp *) Read Write Edit Glob Grep AskUserQuestion Skill ToolSearch
---

# In-app template → Unity prefab

A Kinoa **in-app template** declares slots (`images`, `buttons`, `texts`,
`customs`) and a `featureType`. The game client renders a configured in-app
by filling those slots from an `InAppMessage`. This skill produces that
client piece for one template: a **prefab** laid out like the mockup, and a
**view script** that binds the message and routes every button click.

It never calls the Dashboard itself (template reads go through the sibling
`kinoa-dashboard-inapp-template` helper) and never writes network code into
the game: remote images, store prices and resource icons go through
`KinoaInAppHooks` delegates the game assigns.

Read [`references/prefab-plan-schema.md`](references/prefab-plan-schema.md)
(the plan JSON the Editor builder consumes) and
[`references/generated-code-contract.md`](references/generated-code-contract.md)
(what the generated view / hooks expose) before doing anything non-obvious.

Working files go to `.kinoa-inapp-prefab/<template_key>/` at the Unity project
root (suggest `.gitignore`-ing it). Generated code goes to
`Assets/Kinoa/InApps/` unless the developer names another folder.

---

## Phase 1 — Preflight

### 1.1 Unity MCP is running (hard gate)

Follow [`references/unity-mcp-capabilities.md`](references/unity-mcp-capabilities.md):
`ToolSearch` for `unity`, classify the server, call its liveness probe.
No Unity MCP tools, or a probe that cannot reach the Editor ⇒ **stop**. Say
which of the three supported servers to install, and that the Unity project
must be open with the MCP bridge started. Do not continue to a "plan only"
mode unless the developer explicitly asks for it — Phase 6 cannot run without
Unity, and a plan nobody can build is not the deliverable.

### 1.2 Kinoa session + SDK project

```bash
python "${CLAUDE_SKILL_DIR}/../kinoa-init/kinoa_init.py" show
```

Needs `KINOA_GAME_ID` and a bearer. Missing ⇒ run `/kinoa-init --integration-type SDK`
first, then come back. **Never `cat ~/.kinoa/session.env`** — the admin token
would land in the transcript.

Confirm the open project is SDK-integrated: `Packages/manifest.json` lists
`com.kinoa.sdk.core`, or `Packages/com.kinoa.sdk.core/` exists. The generated
view binds `Kinoa.Data.Messaging.InApp.*` types; without the SDK it cannot
compile ⇒ stop and point at the `/kinoa` skill.

### 1.3 Resolve the template

`--template-id` given ⇒ use it. Otherwise list and ask:

```bash
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py" list
```

Offer up to four templates in `AskUserQuestion` (name · key · status ·
`inAppsCount`). Then fetch the full record. The folder name needs the template
`key`, which is only known once the record is read, so fetch to a temporary
name first:

```bash
mkdir -p .kinoa-inapp-prefab
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py" get --id <id> > .kinoa-inapp-prefab/template_<id>.json
```

Read `response.key` from that file, then create the per-template folder and
move the record into it:

```bash
mkdir -p .kinoa-inapp-prefab/<key>
mv .kinoa-inapp-prefab/template_<id>.json .kinoa-inapp-prefab/<key>/template_record.json
```

From here on, `.kinoa-inapp-prefab/<key>/` exists — every later step that
writes there (Phase 2 `--out`, the Phase 3 layout artifact copy, Phase 4
`--out`) relies on it.

A record whose buttons have no `clickActionType` is **sparse** (written without
the `Key-Inflection` header — see the helper's SKILL.md). Say so; the prefab
will still build, but click menus are unknown and the operator must PATCH the
full body before shipping.

### 1.4 Facade detection

`Grep` for `class KinoaUiService` and `class KinoaInAppTemplateConstants`
under `Assets/`. Found ⇒ `facade=present`, record the facade's `namespace`
line and both file paths. Not found ⇒ `facade=absent` (the view raises a
`ButtonClicked` event and leaves a routing TODO).

## Phase 2 — Reference popups

**Greenfield** (the game has no pop-up prefabs, or the developer has none to
point at): skip `probe-style` and omit `--style` in Phase 4. The planner then
defaults to legacy `Text`, a 1080-wide frame (height from the mockup aspect,
else 1920), and no font / close-button sprite (the builder falls back to
Unity's built-in Arial and leaves the close button without a sprite). Ask the developer one question —
**legacy Text or TextMeshPro?** (legacy is the safe default on projects without
`Unity.TextMeshPro`). Only if they choose TextMeshPro, write a one-line style
file with the Write tool and pass it as `--style` in Phase 4 — the file
`.kinoa-inapp-prefab/<key>/style_probe.json` with the content:

```json
{"text_system": "tmp"}
```

(`plan` accepts a partial style dict; missing keys take the defaults above.)
Then go to Phase 3.

Otherwise, ask for the names of the game's existing pop-up prefabs. Pre-fill the question
with up to four candidates from
`Glob Assets/**/*.prefab` whose name matches `popup|dialog|modal|window|offer|panel`
(case-insensitive), plus "Other" for a path. Then:

```bash
python "${CLAUDE_SKILL_DIR}/inapp_prefab_plan.py" probe-style --prefab <A.prefab> --prefab <B.prefab> --assets-root Assets --out .kinoa-inapp-prefab/<key>/style_probe.json
```

Report what the probe found — text system (legacy `Text` vs TextMeshPro),
font asset, panel size, close-button sprite, base popup classes. `text_system`
`unknown` ⇒ ask which to use (legacy is the safe default on 2021/2022 projects
without `Unity.TextMeshPro`). The generated prefab follows these conventions;
the base popup class is **reported, not inherited** — the view derives from
`MonoBehaviour` and exposes `Closed`, so the game's popup manager wraps it.

## Phase 3 — Layout source

The layout comes from the sibling skill `kinoa-inapp-template-from-image`. Its
geometry deliverable is **`<template_key>.layout.json`**, the layout artifact
(contract: [`../kinoa-inapp-template-from-image/references/layout-artifact.md`](../kinoa-inapp-template-from-image/references/layout-artifact.md)).
Every element there carries the template's own key, bucket and index, a
normalized top-left bbox (or `bbox: null` + `unplaced`), plus the
client-rendered zones, the source image size and, for mission/milestone
templates, `feature.area_bbox`. Ask which source to use (one question,
recommended first):

- **A — An existing `<template_key>.layout.json` (recommended).** The developer
  created this template with `kinoa-inapp-template-from-image` and kept the
  artifact it writes next to `<template_key>.template.json`. Ask for its path
  and copy it to `.kinoa-inapp-prefab/<key>/<key>.layout.json`.
- **B — Derive the artifact from the template's tip image.** The template
  already lives on the dashboard but nobody has its layout. Before delegating,
  show the developer the record's tip-image reference — `tipImageUrl` when it
  was attached as a link, or the uploaded image when `tipImageUrl` is null and
  `tipImageBlob` is set (a `get` shows it as `<blob: N chars>`) — and get a yes:
  it is read from a Dashboard record, not typed by them, and the sibling skill
  materialises it with the helper's `tip-image` (url first, then blob).
  Then invoke the sibling skill — `kinoa-dashboard:kinoa-inapp-template-from-image`
  when installed as the plugin, `kinoa-inapp-template-from-image` under the
  legacy symlink install — and ask for the layout of this existing template,
  giving it the template id; that is its *path B*. It fetches the record,
  analyses the tip image, gates the pair with `remap`, lets the developer
  confirm on its page, and writes `<template_key>.layout.json` with the
  record's own keys next to the image. Copy that file to
  `.kinoa-inapp-prefab/<key>/<key>.layout.json`. `remap` fails closed when the
  tip image does not match the template (a stale or unrelated image): then
  there is **no** layout. Surface the mismatch report and offer D or a
  different mockup. Never position slots from an image that failed the gate.
- **C — No artifact, but the from-image run's files exist.**
  - **The confirmed envelope was kept** (the confirmation page's hand-back):
    have the sibling's builder turn it into the artifact, then continue as A:

    ```bash
    python "${CLAUDE_SKILL_DIR}/../kinoa-inapp-template-from-image/inapp_template_build.py" layout \
      --envelope <confirmed.json> --out .kinoa-inapp-prefab/<key>/<key>.layout.json
    ```

    Add `--analysis <analysis.json>` if the developer kept it; it fills the
    source image path and the feature area.
  - **Only `build_result.json` exists:** plan from it with `--build` (Phase 4,
    option C). Its geometry is the raw, unconfirmed vision pass — say so in the
    hand-off.
- **D — No layout.** Every slot lands in the `Unplaced` container; the plan
  report says so. Offer this only when A–C are impossible.

**Fingerprint check (A and C).** When the artifact's `source_image.sha256` is
non-null and the developer has the mockup file at hand, compare before
planning (B just analysed the tip image itself, so it needs no check):

```bash
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <mockup.png>
```

A different hash means the boxes were drawn against another export of the
design — say so and ask whether to continue.

## Phase 4 — Plan

Options A, B and C-with-envelope — from the layout artifact:

```bash
python "${CLAUDE_SKILL_DIR}/inapp_prefab_plan.py" plan \
  --template .kinoa-inapp-prefab/<key>/template_record.json \
  --layout-artifact .kinoa-inapp-prefab/<key>/<key>.layout.json \
  --style .kinoa-inapp-prefab/<key>/style_probe.json \
  --out .kinoa-inapp-prefab/<key>/<key>.inapp-plan.json
```

The artifact joins its template 1:1 on `(bucket, key)`, and the planner
holds it to that:

- A `template_key` that is not this template's key is refused
  (`error: layout_template_mismatch`, exit 2) — the wrong file; ask for the
  right one. A missing `template_key`, out-of-range or zero-size element
  boxes, or another coordinate convention are refused as `unreadable_input`.
- `report.warnings` names every template slot with no artifact entry, every
  duplicate entry, and every element whose `index` or the feature type
  disagrees with the record — usually an artifact that predates a template
  edit. Artifact entries the template does not have go to `unmapped_layout`.
- `feature.area_bbox` positions the mission task list, or the milestone bar
  when no `bar_image` element was placed, instead of default anchors — only
  when the artifact's feature type matches the template's.

Option C without an envelope — from `build_result.json`:

```bash
python "${CLAUDE_SKILL_DIR}/inapp_prefab_plan.py" plan \
  --template .kinoa-inapp-prefab/<key>/template_record.json \
  --build <build_result.json> \
  --style .kinoa-inapp-prefab/<key>/style_probe.json \
  --out .kinoa-inapp-prefab/<key>/<key>.inapp-plan.json
```

Option D (no layout): omit `--layout-artifact` and `--build`. Greenfield
(Phase 2): omit `--style`. Optional on every variant: `--image-size 1080x1920`
(overrides the aspect read from the layout source) and
`--out-dir Assets/Kinoa/InApps`. `--style` accepts the `probe-style --out`
file as-is.

Read `report` and show it: `layout_source` (which kind positioned the plan),
`unplaced` slots, `estimated_positions` (zones and feature UIs placed at
defaults), `unmapped_layout`, `client_zones` that will be built,
`needs_developer`, and every entry of `warnings` (including slot renames made
to avoid name clashes and artifact/template disagreements).

The planner removes the overlaps between top-level texts, buttons and zones
that it can remove safely, and reports the rest. The panel spans every
positioned element, including the CTA, timer or fine print that sit below the
background art on most mockups, so nothing is squeezed onto the panel edge.
Then:

- Estimated nodes (default anchors, the `Unplaced` container) move to the
  nearest free space.
- Two placed boxes that only graze each other are trimmed to meet halfway.
- Intended overlays are kept as drawn and listed in `report.overlays`. These
  are a box mostly inside another, like a price on the CTA, or anything on a
  container (task list, milestone bar, resource area). Badges are exempt
  entirely.
- A substantial partial overlap is left as drawn, with a warning.

Show the developer `report.layout_adjustments` (every move or trim, with
before and after anchors) and every overlap warning. A trim or a warning
usually means the vision pass drew a box too large; the developer fixes it on
the from-image confirmation page or in the prefab. Art is built behind
controls and copy and never takes clicks.

### Hooks — find the game's methods, never write them

The view needs three things the SDK does not provide. For each, `Grep` the
game for candidates, then ask the developer which method to wire (options:
the candidates found, or **"leave a TODO"** — the default when nothing fits):

| Hook | Grep for | Required shape |
|---|---|---|
| image loader (`KinoaInAppHooks.LoadSpriteFromUrl`) | `Task<Sprite>`, `DownloadHandlerTexture`, `LoadSprite`, `GetTexture(` | `static Task<Sprite> M(string url)` |
| store price (`ResolveStorePrice`) | `localizedPriceString`, `LocalizedPrice`, `ProductMetadata` | `static string M(InAppStorePackages p, bool usePreSalePackage)` |
| resource icon (`ResolveResourceIcon`) | `GetIcon(`, `IconFor`, `Sprite Get(` | `static Sprite M(string resourceKey)` |

Read the chosen method before wiring it. If its shape differs (instance
method, other parameters), do **not** adapt it from here — leave the TODO and
say what adapter the developer needs. **Never write a download method
yourself**, even when nothing is found: the TODO + runtime warning is the
correct outcome.

## Phase 5 — Generate

```bash
python "${CLAUDE_SKILL_DIR}/inapp_prefab_plan.py" generate \
  --plan .kinoa-inapp-prefab/<key>/<key>.inapp-plan.json \
  --project-root <unity project root> \
  --facade present|absent [--facade-namespace <ns>] \
  [--image-loader Ns.Class.Method] [--price-resolver ...] [--resource-icon-resolver ...]
```

Every run writes the view, the plan copy and `Editor/KinoaInAppPrefabBuilder.cs`
(tool-owned — always refreshed). `Shared/KinoaInAppHooks.cs` and
`Shared/KinoaInAppItemView.cs` are **user-owned**: written only when absent,
and kept untouched afterwards (`--force-shared` rewrites them). Surface every
entry of the output's `warnings` — notably a hook option (`--image-loader`,
`--price-resolver`, `--resource-icon-resolver`) that was **not applied**
because the existing `KinoaInAppHooks.cs` was kept: tell the developer to
assign it in that file, or confirm a `--force-shared` re-run.

`view_exists` ⇒ confirm with the developer, then re-run with `--overwrite`.
`shared_text_system_mismatch` ⇒ the project already has shared files for the
other text system: keep the existing one (re-run `plan` with the matching
`text_system` in `style_probe.json`) rather than forcing with `--force-shared`.
`forbidden_content` ⇒ a generated file would contain a banned token
(`UnityWebRequest`, `Bearer`, …): fix the input (usually a hook method name or
namespace), never edit the output.

When `facade=present`, show the `constant` and `allowlist_arm` snippets and
ask before applying them with `Edit` to `KinoaInAppTemplateConstants.cs` and
`KinoaUiService.IsKnownCustomTemplateKey` (one constant, one switch arm —
exactly what the SDK's module 06 prescribes). **The arm is load-bearing:** the
sample `KinoaUiService.HandleInAppButtonClickAsync` only routes templates whose
key passes `IsKnownCustomTemplateKey`, so until the constant and arm are
applied, **every click on the generated view is ignored**. Say this in the
question. The `create_game_inapp` snippet is **hand-off only**: wiring
`CreateGameInApp` is the `/kinoa messaging --merge` flow's job and may already
route through a popup manager.

## Phase 6 — Build in Unity

1. **Refresh + compile** via the server's refresh tool (table in
   [`references/unity-mcp-capabilities.md`](references/unity-mcp-capabilities.md)).
   Wait for the compile to finish, then read the console with the
   server's console tool and look for `error CS`. Errors in generated files ⇒
   fix the generator input (wrong facade namespace, TMP missing → legacy),
   re-run `generate --overwrite`, repeat. Never patch generated C# by hand.
   An error in a kept `Shared/*.cs` file is not fixed by `--overwrite`; after
   confirming with the developer (those files hold their edits), re-run with
   `--force-shared`.
2. **Build the prefab**: run the menu item
   `Tools/Kinoa/In-Apps/Build Prefabs From Plans` (or call
   `Kinoa.InApps.Editor.KinoaInAppPrefabBuilder.BuildAll` through the server's
   reflection/method tool).
3. **Read the report** from disk: take `plan_path` from `generate`'s output
   and replace `.inapp-plan.json` with `.build-report.json` (by default
   `Assets/Kinoa/InApps/<Pascal>/<key>.build-report.json`, but it follows
   `--out-dir`) → `ok: true`,
   `fields_missing: []`, `errors: []`. `view class not found` ⇒ compile had not
   finished; refresh again and rebuild. `fields_missing` ⇒ the view and the plan
   are out of step; re-run `generate --overwrite` and rebuild.
4. **Verify the asset**: `Glob` the `prefab_path`; optionally inspect it with
   the server's GameObject/prefab inspection tool.

## Phase 7 — Hand-off

Summarise, in this order: prefab path · view class · fields assigned ·
**every `TODO(kinoa-prefab)` with `path:line`** (from `generate`'s `todos`) ·
`warnings` from `generate` and `plan` · unplaced slots and estimated positions ·
snippets shown but not applied (if the developer declined the facade constant +
allowlist arm, say plainly that clicks on the view are ignored until they are
applied) · next steps (assign the hooks in the game's bootstrap; wire
`CreateGameInApp` via `/kinoa messaging --merge`; activate the template on the
Dashboard when the first in-app is configured). Say plainly what was verified
in Unity and what was not. State these facts every time:

- **Rebuilding overwrites hand edits.** The Editor builder rebuilds the prefab
  from the plan; changes made to the prefab by hand are lost on the next build.
  Change the plan (or the layout source) and rebuild instead.
- **The builder works in the open scene.** `BuildAll` builds the prefab through
  the open scene, so Unity may prompt to save the current scene (or leave it
  dirty). Tell the developer before they run it, or when you ran it.
- **`MissionText` may be a template.** A mission-row text can carry a
  placeholder (the SDK demo replaces `"[]"` with the goal score); the game side
  must substitute it — the generated view shows the Dashboard text as-is.
- **Editor asmdef.** If the output folder sits under a game assembly
  definition, the `Editor/` subfolder needs its own Editor-only asmdef, or its
  `UnityEditor` references break player builds.
- **Player state on events.** The generated click / close / impression events
  use the non-PlayerState overloads. A game that sends player state with its
  events should add it.

## Telemetry

Repo-wide rules ([`../kinoa-api-integration/references/telemetry.md`](../kinoa-api-integration/references/telemetry.md)):
`phase-start` / `phase-end` for Phases 1–7 via
`${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`, `qa` after
every `AskUserQuestion`. Disclose once per run. Failures never abort.

## Hard rules

1. **No Unity MCP, no run.** The prefab is built by the Editor through the
   bridge; the skill never hand-writes `.prefab` YAML. With no Unity MCP
   (none configured, or the Editor unreachable) deliver **nothing that pretends
   to be the prefab**: no hand-written YAML, no stand-in Editor script for the
   developer to run "once a Unity MCP is attached", no plan-only run — unless
   the developer **explicitly asks** for plan-only. Stop and give the
   install/start guidance from Phase 1.1.
2. **Dashboard reads go through `kinoa-dashboard-inapp-template`.** The
   helper here is offline; nothing in it or in generated code calls
   `dashboard.kinoa.io` or carries a bearer. Read credentials only via
   `kinoa_init.py show`.
3. **Never write a download method.** Remote images, store prices and
   resource icons are game-supplied delegates on `KinoaInAppHooks`; the skill
   finds and wires existing methods or leaves `TODO(kinoa-prefab)`.

   | Rationalization | Reality |
   |---|---|
   | "The developer asked for the download in the view" | The hook is how it gets wired; ask which existing method to use, else leave the TODO. The request does not override the rule. |
   | "There is no image cache yet; one can replace this later" | `KinoaInAppHooks.LoadSpriteFromUrl` IS the replacement point; a stopgap downloader becomes the cache nobody replaces. |
   | "It is just one UnityWebRequest" | `generate` refuses any generated file containing `UnityWebRequest` (`forbidden_content`); the game's own loader owns caching, auth and threading. |
   | "We need this today" | The TODO + runtime warning ships today; the view works the moment the hook is assigned. |

4. **Generated files are regenerated, not patched.** Fix the plan or the
   generator input and re-run `generate --overwrite`. The exception is a
   compile error inside a kept `Shared/*.cs` file: `--overwrite` does **not**
   rewrite those (they are user-owned), so the fix needs `--force-shared` —
   confirm with the developer first, because those files hold their edits.
5. **Facade edits are limited to the constant + allowlist arm**, each behind
   an `AskUserQuestion`. `RouteByClickConfigAsync` TODOs and `CreateGameInApp`
   are never edited from here.
6. **Client-rendered zones are positions, not slots.** They never become
   template elements; the view fills them from the message.
7. **Every unplaced slot, estimated position and TODO is surfaced** in the
   hand-off. Nothing is dropped silently.
