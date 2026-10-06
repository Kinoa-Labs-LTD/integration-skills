# kinoa-inapp-template-to-prefab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new plugin skill, `kinoa-inapp-template-to-prefab`, that turns a Kinoa in-app template (fetched from the Dashboard by id) into a working Unity uGUI prefab plus the C# view script that binds an `InAppMessage` to it and wires every button to real click handling — built inside the developer's open Unity Editor through the Unity MCP server.

**Architecture:** Three layers. (1) An offline, deterministic Python helper `inapp_prefab_plan.py` that probes the game's existing popup prefabs for UI conventions, joins the template's slots with a layout source (the `report.elements` bboxes from `kinoa-inapp-template-from-image`'s build result — preferred — or a fresh vision pass over the tip image), and emits a flat **prefab plan JSON** plus generated C# (a per-template `KinoaInApp<Pascal>View` runtime class, a shared `KinoaInAppHooks` static class holding the game-supplied delegates such as the image loader, a shared `KinoaInAppItemView` list-row class, and a generic Editor-only `KinoaInAppPrefabBuilder` that materialises any plan into a `.prefab`). (2) A `SKILL.md` workflow that preflights the Unity MCP + Kinoa session, resolves the template via the sibling `kinoa-dashboard-inapp-template` helper, collects the reference popup prefabs, picks the layout source, runs the planner/generator, and then drives Unity through MCP: refresh → compile gate → run the builder → read its build report. (3) Repo wiring: tests, evals, README/CLAUDE/CHANGELOG, a hand-off pointer in the from-image skill.

**Tech Stack:** Python 3 stdlib only (helpers are self-contained — repo rule), `unittest`; Unity 2021.2+ uGUI (`UnityEngine.UI`), optional TextMeshPro; Kinoa Unity SDK `com.kinoa.sdk.core` 2.23+ (`Kinoa.Messaging`, `Kinoa.GameEvents`, `Kinoa.Data.Messaging.InApp.*`); Unity MCP servers — CoderGamester `mcp-unity`, CoplayDev `unity-mcp`, IvanMurzak `Unity-MCP`.

**Spec:** This plan's "Spec" section below — the request came as a slash-command brief (no separate spec file): *"new skill for in-app template visualisation as prefab on the game client side. 1. checkpoint that the project has Unity MCP running. 2. Kinoa plugin is inited and the id of the Kinoa in-app template to retrieve the structure from the dashboard. 3. names of existing popup game prefabs. 4. one of two options — tip image, or run in-app layout recognition and use its output (preferred). Then build the prefab with scripts and actual business logic for buttons as much as possible. For the downloadable link leave a TODO in code — don't write a download method on your own; ask devs for the method in the current game code."*

## Spec (normative, derived from the brief + repo conventions)

1. **Preflight — Unity MCP.** The skill must verify that a Unity MCP server is connected to this Claude Code session *and* that the Unity Editor behind it is alive, before doing anything else. No MCP ⇒ stop with install guidance (the prefab is built inside the Editor; there is no offline fallback for Phase 6).
2. **Preflight — Kinoa.** `~/.kinoa/session.env` must be initialised (`kinoa_init.py show`, never `cat`). The template id is a required input (argument, or chosen from `kinoa-dashboard-inapp-template list`); the structure is fetched via `kinoa-dashboard-inapp-template get --id` (full camelCase record). The skill makes **no direct HTTP call** of its own.
3. **Reference popups.** Ask for the names/paths of existing popup prefabs (offer Glob-discovered candidates). Probe them for conventions: legacy `Text` vs TextMeshPro, font asset, panel size, close-button sprite, base popup MonoBehaviour. The generated prefab follows those conventions.
4. **Layout source — two options.** (A, preferred) the output of in-app layout recognition: `build_result.json` (+ optional confirmed envelope) from `kinoa-inapp-template-from-image` — its `report.elements[].bbox` positions every slot. (B) the template's tip image (path/URL, or the record's `tipImageUrl`) → a vision pass constrained to the template's slot keys. (C, degraded) no image → stacked fallback layout, loudly flagged.
5. **Build the prefab + scripts with real button logic.** Texts bound from `InAppCustomText.Content` with `text_color`; images from `InAppImage` by content type; buttons labelled from `InAppCustomButton.Label`, each click sends `in_app_click`, a `close` action closes the view, every other action is delegated to `KinoaUiService.HandleInAppButtonClickAsync(message, buttonKey)` when the facade exists in the project (else surfaced through an event + TODO). Impression on show, close event on close. Client-rendered zones (timer, price-before-sale, resource area, grand prize) and feature UIs (milestone bar + markers with `CollectMilestonesAsync`, mission rows with `CollectMissionsProgressAsync`) are generated when the template calls for them.
6. **Image download is never written by the skill.** Remote images go through `KinoaInAppHooks.LoadSpriteFromUrl` — a delegate the game assigns. The skill greps the game for an existing loader, asks the developer which method to use, and either wires the named method or leaves a `// TODO(kinoa-prefab):` with a warning log at runtime. Same pattern for store-price lookup and resource icons.
7. **Repo rules that apply unchanged:** no code calls `dashboard.kinoa.io` / carries a bearer; helpers are self-contained Python with no sibling imports; telemetry via `../kinoa-api-integration/kinoa_webhook.py`; `AskUserQuestion` before any file edit outside the generated folder; unit tests offline; evals per skill; README/CLAUDE/CHANGELOG kept current; **no version bump in this work** (bumps happen in the release PR).

## Global Constraints

- Python helper: stdlib only, `#!/usr/bin/env python3`, one JSON object on stdout per subcommand, exit `0` ok / `2` local guard failure. No network calls at all in `inapp_prefab_plan.py`.
- Generated C# must compile on Unity 2021.2+ with `com.unity.ugui`; `TMPro` referenced only when the probe selected `tmp`. Generated code never contains the strings `dashboard.kinoa.io`, `Bearer`, `UnityWebRequest`, `Addressables.Load`.
- All generated TODOs use the exact marker `TODO(kinoa-prefab):` so the hand-off can `grep` them.
- Skill folder: `plugin/skills/kinoa-inapp-template-to-prefab/`. Frontmatter per CLAUDE.md conventions.
- Unity MCP tool names (verified from each server's docs; the skill detects the flavour via `ToolSearch`):

| Capability | CoderGamester `mcp-unity` (prefix `mcp__mcp-unity__`) | CoplayDev `unity-mcp` (prefix `mcp__unity-mcp__` / `mcp__UnityMCP__`) | IvanMurzak `Unity-MCP` |
|---|---|---|---|
| liveness probe (read-only) | `get_scene_info` | `manage_editor` (action `get_state`) | `editor-application-get-state` |
| refresh / recompile | `recompile_scripts` | `refresh_unity` | `assets-refresh` |
| run a menu item | `execute_menu_item` | `execute_menu_item` | `reflection-method-call` on `Kinoa.InApps.Editor.KinoaInAppPrefabBuilder.BuildAll` |
| read console | `get_console_logs` | `read_console` | `console-get-logs` |
| inspect result | `get_gameobject` / file on disk | `manage_prefabs` / file on disk | `gameobject-find` / file on disk |

- Builder menu item (exact string, used by both the C# attribute and the SKILL.md MCP call): `Tools/Kinoa/In-Apps/Build Prefabs From Plans`.
- Default output root inside the game project: `Assets/Kinoa/InApps/` (overridable with `--out-dir`).

---

## File Structure

**Create (skill):**
- `plugin/skills/kinoa-inapp-template-to-prefab/SKILL.md` — workflow, Phases 1–7.
- `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` — offline helper: `probe-style`, `layout-schema`, `plan`, `generate`.
- `plugin/skills/kinoa-inapp-template-to-prefab/references/unity-mcp-capabilities.md` — the capability table above + detection recipe.
- `plugin/skills/kinoa-inapp-template-to-prefab/references/prefab-plan-schema.md` — the plan JSON contract shared by Python and the C# builder.
- `plugin/skills/kinoa-inapp-template-to-prefab/references/generated-code-contract.md` — public API of the generated view, hooks, item view; TODO marker list.
- `plugin/skills/kinoa-inapp-template-to-prefab/evals/evals.json` + `evals/fixtures/one-cta/{template_one_cta.json, build_result_one_cta.json, OfferPopup.prefab, OfferPopup.prefab.meta, OfferPopup.cs.meta}`.

**Create (tests):**
- `tests/test_inapp_prefab_style_probe.py`
- `tests/test_inapp_prefab_plan.py`
- `tests/test_inapp_prefab_codegen.py`

**Modify:**
- `README.md` — skills table row + architecture line.
- `CLAUDE.md` — architecture list, domain-rules paragraph, file index.
- `CHANGELOG.md` — `[Unreleased] → Added`.
- `plugin/skills/kinoa-inapp-template-from-image/SKILL.md` — Phase 5 hand-off pointer.
- `docs/inapp-template-generation-guide.md` — "Next step: visualise as a Unity prefab" section.

---

### Task 1: Skill skeleton, fixtures, and the MCP capability reference

**Files:**
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/SKILL.md` (frontmatter + one-paragraph intro; body completed in Task 9)
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/references/unity-mcp-capabilities.md`
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/template_one_cta.json`
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/build_result_one_cta.json` (generated by the sibling builder — deterministic)
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/OfferPopup.prefab`, `OfferPopup.prefab.meta`, `Scripts/OfferPopup.cs.meta`
- Test: `tests/test_inapp_prefab_fixtures.py`

**Interfaces:**
- Produces: fixture paths used by every later test: `FIXTURES = plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta`.

- [ ] **Step 1: Write the failing fixture test**

```python
# tests/test_inapp_prefab_fixtures.py
"""Fixture sanity for kinoa-inapp-template-to-prefab. Offline."""
import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")


class TestFixtures(unittest.TestCase):
    def test_template_record_has_all_four_buckets(self):
        with open(os.path.join(FIX, "template_one_cta.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual(rec["key"], "one_cta_offer")
        for bucket in ("images", "buttons", "texts", "customs"):
            self.assertIn(bucket, rec)
        self.assertEqual({b["key"] for b in rec["buttons"]}, {"close_button", "cta_button"})

    def test_build_result_elements_carry_bboxes(self):
        with open(os.path.join(FIX, "build_result_one_cta.json"), encoding="utf-8") as fh:
            br = json.load(fh)
        keys = {e["key"] for e in br["report"]["elements"]}
        self.assertIn("header", keys)
        self.assertTrue(all("bbox" in e for e in br["report"]["elements"]))
        self.assertEqual({c["role"] for c in br["report"]["client_rendered"]},
                         {"resource_area", "price_before_sale", "timer"})

    def test_frontmatter(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            head = fh.read(2000)   # the description paragraph is long
        self.assertTrue(head.startswith("---\nname: kinoa-inapp-template-to-prefab\n"))
        self.assertIn("allowed-tools:", head)
        self.assertIn("ToolSearch", head)

    def test_prefab_fixture_is_legacy_text_with_font(self):
        with open(os.path.join(FIX, "OfferPopup.prefab"), encoding="utf-8") as fh:
            yaml = fh.read()
        self.assertIn("guid: 5f7201a12d95ffc409449d95f23cf332", yaml)   # UnityEngine.UI.Text
        self.assertIn("m_Font: {fileID: 12800000, guid: e7a63bee4e93df34ca0dd3548b336621", yaml)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest tests.test_inapp_prefab_fixtures -v`
Expected: FAIL — `FileNotFoundError` on `template_one_cta.json`.

- [ ] **Step 3: Generate the build-result fixture from the sibling builder**

```bash
mkdir -p plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/Scripts plugin/skills/kinoa-inapp-template-to-prefab/references
python plugin/skills/kinoa-inapp-template-from-image/inapp_template_build.py build \
  --analysis plugin/skills/kinoa-inapp-template-from-image/evals/fixtures/one-cta/analysis_one_cta.json \
  --name "One CTA Offer" --key one_cta_offer \
  --out plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/build_result_one_cta.json
```

Expected: file written; `report.elements` has 9 entries, `report.client_rendered` has 3.

- [ ] **Step 4: Write the template-record fixture (what `get --id` returns, trimmed to the fields the planner reads)**

Derive it from the build result so slot keys match: `python - <<'EOF'` is forbidden in auto mode for network scripts but fine offline; still, keep it a plain file. Write `template_one_cta.json`:

```json
{
  "id": "44444444-4444-4444-4444-444444444444",
  "name": "One CTA Offer",
  "key": "one_cta_offer",
  "description": "",
  "gameId": "11111111-1111-1111-1111-111111111111",
  "status": "draft",
  "tipImageUrl": null,
  "featureType": "standard",
  "features": {},
  "images": [
    {"key": "background_image", "name": "Background Image", "index": 1, "description": "", "canBeHidden": true, "customFields": []}
  ],
  "buttons": [
    {"key": "close_button", "name": "Close", "index": 0, "description": "", "canBeHidden": true, "customFields": [], "clickActionType": ["close"]},
    {"key": "cta_button", "name": "CTA", "index": 7, "description": "", "canBeHidden": false, "customFields": [],
     "clickActionType": ["close", "show_ad", "billing", "collect_resource", "deep_link", "soft_billing"], "requiredItemsCount": 1}
  ],
  "texts": [
    {"key": "header", "name": "Header", "index": 2, "nullable": false, "description": "", "canBeHidden": true,
     "customFields": [{"key": "text_color", "kind": "string", "name": "Text color", "nullable": false, "description": "", "defaultValue": "#FFFFFF"}]},
    {"key": "upper_text", "name": "Upper Text", "index": 3, "nullable": true, "description": "", "canBeHidden": true,
     "customFields": [{"key": "text_color", "kind": "string", "name": "Text color", "nullable": false, "description": "", "defaultValue": "#FFFFFF"}]},
    {"key": "resource_badge", "name": "Resource Badge", "index": 4, "nullable": true, "description": "", "canBeHidden": true,
     "customFields": [{"key": "text_color", "kind": "string", "name": "Text color", "nullable": false, "description": "", "defaultValue": "#FFFFFF"},
                      {"key": "badge_color", "kind": "string", "name": "Badge BG color", "nullable": false, "description": "", "defaultValue": "#FF3B30"}]},
    {"key": "price_cut_badge", "name": "Price Cut Badge", "index": 8, "nullable": true, "description": "", "canBeHidden": true,
     "customFields": [{"key": "text_color", "kind": "string", "name": "Text color", "nullable": false, "description": "", "defaultValue": "#FFFFFF"}]},
    {"key": "fine_print", "name": "Fine Print", "index": 9, "nullable": true, "description": "", "canBeHidden": true,
     "customFields": [{"key": "text_color", "kind": "string", "name": "Text color", "nullable": false, "description": "", "defaultValue": "#FFFFFF"}]}
  ],
  "customs": [
    {"key": "show_resource_area", "kind": "boolean", "name": "Show Resource Area", "index": 5, "nullable": true, "description": "", "canBeHidden": true, "customFields": [], "defaultValue": false}
  ]
}
```

Check the keys against the build result before saving: `python -c "import json;b=json.load(open('plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/build_result_one_cta.json'));print(sorted(e['key'] for e in b['report']['elements']))"` — every key printed must appear in the record (the custom's key may differ in the builder output; if it does, use the builder's key in the record, the record is the source of truth for the test).

- [ ] **Step 5: Write the prefab fixture (minimal legacy-Text popup with a close button and a `Dialog`-style script)**

`OfferPopup.prefab`:

```yaml
%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {fileID: 101}
  - component: {fileID: 102}
  m_Layer: 5
  m_Name: OfferPopup
--- !u!224 &101
RectTransform:
  m_GameObject: {fileID: 100}
  m_Children:
  - {fileID: 201}
  - {fileID: 301}
  m_Father: {fileID: 0}
  m_AnchorMin: {x: 0.5, y: 0.5}
  m_AnchorMax: {x: 0.5, y: 0.5}
  m_SizeDelta: {x: 900, y: 1400}
--- !u!114 &102
MonoBehaviour:
  m_GameObject: {fileID: 100}
  m_Script: {fileID: 11500000, guid: 687bf77fdfbf4f1e86236a31014375b3, type: 3}
--- !u!1 &200
GameObject:
  m_Component:
  - component: {fileID: 201}
  - component: {fileID: 202}
  m_Layer: 5
  m_Name: Title
--- !u!224 &201
RectTransform:
  m_GameObject: {fileID: 200}
  m_Father: {fileID: 101}
--- !u!114 &202
MonoBehaviour:
  m_GameObject: {fileID: 200}
  m_Script: {fileID: 11500000, guid: 5f7201a12d95ffc409449d95f23cf332, type: 3}
  m_FontData:
    m_Font: {fileID: 12800000, guid: e7a63bee4e93df34ca0dd3548b336621, type: 3}
    m_FontSize: 50
--- !u!1 &300
GameObject:
  m_Component:
  - component: {fileID: 301}
  - component: {fileID: 302}
  - component: {fileID: 303}
  m_Layer: 5
  m_Name: CloseButton
--- !u!224 &301
RectTransform:
  m_GameObject: {fileID: 300}
  m_Father: {fileID: 101}
--- !u!114 &302
MonoBehaviour:
  m_GameObject: {fileID: 300}
  m_Script: {fileID: 11500000, guid: fe87c0e1cc204ed48ad3b37840f39efc, type: 3}
  m_Sprite: {fileID: 21300000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
--- !u!114 &303
MonoBehaviour:
  m_GameObject: {fileID: 300}
  m_Script: {fileID: 11500000, guid: 4e29b1a8efbd4b44bb3f3716e73f07ff, type: 3}
```

`OfferPopup.prefab.meta`: `fileFormatVersion: 2\nguid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n`.
`Scripts/OfferPopup.cs.meta`: `fileFormatVersion: 2\nguid: 687bf77fdfbf4f1e86236a31014375b3\n` (this is how the probe resolves the root script guid → class name `OfferPopup` from the `.cs.meta` filename).

- [ ] **Step 6: Write the SKILL.md frontmatter + intro (body filled in Task 9)**

```markdown
---
name: kinoa-inapp-template-to-prefab
description: Visualises a Kinoa in-app template as a Unity uGUI prefab inside the developer's open Unity Editor — fetches the template structure from the Dashboard by id, probes the game's existing popup prefabs for UI conventions, positions every slot from the in-app layout recognition output (preferred) or from the tip image, generates the prefab plan plus a C# view that binds InAppMessage data and wires every button's click action, and builds the prefab through the connected Unity MCP server. Use when someone wants "a prefab for this in-app template", "visualise template X in Unity", "generate the popup view for the one_cta template", or "turn the dashboard in-app template into a Unity popup". Requires a running Unity MCP. NOT for creating the template itself (that is kinoa-inapp-template-from-image) and NOT for SDK integration of messaging services (that is the /kinoa skill shipped in the SDK).
argument-hint: [--template-id <uuid>] [--build build_result.json [--confirmed envelope.json] | --tip-image <path|url>] [--prefabs <Name.prefab>,...]
allowed-tools: Bash(python *) Read Write Edit Glob Grep AskUserQuestion Agent ToolSearch
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
```

- [ ] **Step 7: Write `references/unity-mcp-capabilities.md`**

Content: the capability table from Global Constraints verbatim, plus this detection recipe:

```markdown
## Detecting the connected server

1. `ToolSearch` with query `unity` (max_results 20). Collect every returned tool name.
2. Classify by prefix / name:
   - names containing `mcp-unity__` → **CoderGamester mcp-unity**
   - names `manage_editor`, `refresh_unity`, `read_console` → **CoplayDev unity-mcp**
   - names `assets-refresh`, `console-get-logs`, `reflection-method-call` → **IvanMurzak Unity-MCP**
3. Call the liveness probe for that flavour. A transport error, a timeout, or
   "Unity Editor is not connected" ⇒ the Editor is not running / the bridge is
   down. Stop and tell the developer to open the project in Unity and start the
   MCP bridge (mcp-unity: `Tools/MCP Unity/Server Window → Start Server`).
4. Zero Unity tools found ⇒ no Unity MCP configured. Stop; point at the three
   servers' install docs. There is no offline fallback for Phase 6: the prefab
   is built by Unity, not by hand-written YAML.
```

- [ ] **Step 8: Run the fixture test**

Run: `python -m unittest tests.test_inapp_prefab_fixtures -v`
Expected: 4 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab tests/test_inapp_prefab_fixtures.py
git commit -m "feat(inapp-prefab): skill skeleton, fixtures, Unity MCP capability reference"
```

---

### Task 2: `probe-style` — read the game's existing popup prefabs for UI conventions

**Files:**
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (module header, constants, `probe_style`, CLI skeleton with `probe-style`)
- Test: `tests/test_inapp_prefab_style_probe.py`

**Interfaces:**
- Produces: `probe_style(prefab_paths: list[str], assets_root: str) -> dict` with keys `text_system` (`"legacy"|"tmp"|"unknown"`), `font_guid`, `tmp_font_guid`, `root_size` (`[w,h]` or `None`), `close_sprite_guid`, `base_classes` (list of class names resolved from root MonoBehaviour guids), `prefabs` (list of per-prefab summaries), `warnings`.
- Constants later tasks import: `LEGACY_TEXT_GUID`, `TMP_TEXT_GUID`, `IMAGE_GUID`, `BUTTON_GUID`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inapp_prefab_style_probe.py
"""Offline tests for probe-style (Unity prefab YAML heuristics)."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
HELPER = os.path.join(SKILL, "inapp_prefab_plan.py")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class TestProbeStyle(unittest.TestCase):
    def test_detects_legacy_text_font_root_size_close_sprite_and_base_class(self):
        probe = mod.probe_style([os.path.join(FIX, "OfferPopup.prefab")], FIX)
        self.assertEqual(probe["text_system"], "legacy")
        self.assertEqual(probe["font_guid"], "e7a63bee4e93df34ca0dd3548b336621")
        self.assertIsNone(probe["tmp_font_guid"])
        self.assertEqual(probe["root_size"], [900.0, 1400.0])
        self.assertEqual(probe["close_sprite_guid"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(probe["base_classes"], ["OfferPopup"])
        self.assertEqual(probe["prefabs"][0]["name"], "OfferPopup")

    def test_tmp_wins_when_present(self):
        yaml = ("--- !u!114 &1\nMonoBehaviour:\n  m_Script: {fileID: 11500000, guid: "
                + mod.TMP_TEXT_GUID + ", type: 3}\n  m_fontAsset: {fileID: 11400000, guid: "
                "cccccccccccccccccccccccccccccccc, type: 2}\n")
        path = os.path.join(self._tmp(), "Tmp.prefab")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(yaml)
        probe = mod.probe_style([path], self._tmp())
        self.assertEqual(probe["text_system"], "tmp")
        self.assertEqual(probe["tmp_font_guid"], "cccccccccccccccccccccccccccccccc")

    def test_missing_prefab_is_a_warning_not_a_crash(self):
        probe = mod.probe_style([os.path.join(FIX, "Nope.prefab")], FIX)
        self.assertEqual(probe["text_system"], "unknown")
        self.assertTrue(any("Nope.prefab" in w for w in probe["warnings"]))

    def test_cli_probe_style_prints_json(self):
        out = subprocess.run([sys.executable, HELPER, "probe-style", "--prefab",
                              os.path.join(FIX, "OfferPopup.prefab"), "--assets-root", FIX],
                             capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["style"]["text_system"], "legacy")

    def _tmp(self):
        import tempfile
        if not hasattr(self, "_d"):
            self._d = tempfile.mkdtemp()
        return self._d
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_inapp_prefab_style_probe -v`
Expected: FAIL — `FileNotFoundError` loading `inapp_prefab_plan.py`.

- [ ] **Step 3: Implement the module header, constants, YAML scanner and `probe_style`**

```python
#!/usr/bin/env python3
"""kinoa-inapp-template-to-prefab — offline planner + code generator.

Turns a Kinoa in-app template record (from `kinoa-dashboard-inapp-template get`)
plus a layout source into a flat PREFAB PLAN (JSON, consumed by the generated
Editor builder) and the C# files that bind an InAppMessage to that prefab.

Pure: no network, no Unity. Deterministic: same inputs -> same outputs.

Subcommands:
  probe-style    read existing popup prefabs for UI conventions
  layout-schema  print the contract a vision pass must return (tip-image path)
  plan           template + layout (+ style) -> <key>.inapp-plan.json
  generate       plan -> C# files + plan copy under the game project
"""
import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = "1.0"

# Built-in uGUI / TMP script GUIDs (stable across Unity versions).
LEGACY_TEXT_GUID = "5f7201a12d95ffc409449d95f23cf332"   # UnityEngine.UI.Text
TMP_TEXT_GUID = "f4688fdb7df04437aeb418b961361dc5"      # TMPro.TextMeshProUGUI
IMAGE_GUID = "fe87c0e1cc204ed48ad3b37840f39efc"         # UnityEngine.UI.Image
BUTTON_GUID = "4e29b1a8efbd4b44bb3f3716e73f07ff"        # UnityEngine.UI.Button

_CLOSE_NAME_RE = re.compile(r"close|dismiss|^x$|btn_x|exit", re.I)


def _emit(obj, out=None):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- probe-style

def _split_yaml_docs(text):
    """Yield (class_tag, body) per Unity YAML document ('--- !u!114 &id')."""
    docs = re.split(r"^--- !u!(\d+) &-?\d+.*$", text, flags=re.M)
    # re.split yields [pre, tag1, body1, tag2, body2, ...]
    for i in range(1, len(docs) - 1, 2):
        yield docs[i], docs[i + 1]


def _field(body, name):
    m = re.search(r"^\s*%s:\s*(.+)$" % re.escape(name), body, flags=re.M)
    return m.group(1).strip() if m else None


def _guid_in(value):
    m = re.search(r"guid:\s*([0-9a-f]{32})", value or "")
    return m.group(1) if m else None


def _meta_guid_index(assets_root):
    """Map script guid -> class name by scanning *.cs.meta under assets_root."""
    index = {}
    for root, _dirs, files in os.walk(assets_root):
        for fn in files:
            if not fn.endswith(".cs.meta"):
                continue
            try:
                with open(os.path.join(root, fn), encoding="utf-8", errors="ignore") as fh:
                    m = re.search(r"^guid:\s*([0-9a-f]{32})", fh.read(), flags=re.M)
            except OSError:
                continue
            if m:
                index[m.group(1)] = fn[: -len(".cs.meta")]
    return index


def _probe_one(path, meta_index):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    rects, monos = {}, []
    for tag, body in _split_yaml_docs(text):
        if tag == "224":
            rects[(_field(body, "m_GameObject") or "").replace(" ", "")] = body
        elif tag == "114":
            monos.append(body)

    summary = {"name": os.path.splitext(os.path.basename(path))[0], "legacy_text": 0, "tmp_text": 0,
               "font_guid": None, "tmp_font_guid": None, "root_size": None,
               "close_sprite_guid": None, "root_scripts": []}

    # Root = the RectTransform whose m_Father is {fileID: 0}.
    root_go_ref = None
    for go_ref, body in rects.items():
        if (_field(body, "m_Father") or "").replace(" ", "") == "{fileID:0}":
            root_go_ref = go_ref
            size = _field(body, "m_SizeDelta") or ""
            m = re.search(r"x:\s*(-?[\d.]+),\s*y:\s*(-?[\d.]+)", size)
            if m:
                summary["root_size"] = [float(m.group(1)), float(m.group(2))]

    # GameObject fileID -> m_Name (the '--- !u!1 &<id>' header carries the id).
    go_names_by_ref = {}
    for m in re.finditer(r"^--- !u!1 &(-?\d+)[^\n]*\n(.*?)(?=^--- !u!|\Z)", text, flags=re.M | re.S):
        go_names_by_ref["{fileID:%s}" % m.group(1)] = _field(m.group(2), "m_Name") or ""

    for body in monos:
        go_ref = (_field(body, "m_GameObject") or "").replace(" ", "")
        script = _guid_in(_field(body, "m_Script"))
        if script == LEGACY_TEXT_GUID:
            summary["legacy_text"] += 1
            summary["font_guid"] = summary["font_guid"] or _guid_in(_field(body, "m_Font"))
        elif script == TMP_TEXT_GUID:
            summary["tmp_text"] += 1
            summary["tmp_font_guid"] = summary["tmp_font_guid"] or _guid_in(_field(body, "m_fontAsset"))
        elif script == IMAGE_GUID:
            name = go_names_by_ref.get(go_ref, "")
            if _CLOSE_NAME_RE.search(name) and not summary["close_sprite_guid"]:
                summary["close_sprite_guid"] = _guid_in(_field(body, "m_Sprite"))
        elif script and go_ref == root_go_ref and script not in (BUTTON_GUID,):
            summary["root_scripts"].append(meta_index.get(script, script))
    return summary


def probe_style(prefab_paths, assets_root):
    meta_index = _meta_guid_index(assets_root) if assets_root and os.path.isdir(assets_root) else {}
    result = {"schema_version": SCHEMA_VERSION, "text_system": "unknown", "font_guid": None,
              "tmp_font_guid": None, "root_size": None, "close_sprite_guid": None,
              "base_classes": [], "prefabs": [], "warnings": []}
    legacy = tmp = 0
    for path in prefab_paths:
        if not os.path.isfile(path):
            result["warnings"].append("prefab not found: %s" % path)
            continue
        s = _probe_one(path, meta_index)
        result["prefabs"].append(s)
        legacy += s["legacy_text"]
        tmp += s["tmp_text"]
        result["font_guid"] = result["font_guid"] or s["font_guid"]
        result["tmp_font_guid"] = result["tmp_font_guid"] or s["tmp_font_guid"]
        result["root_size"] = result["root_size"] or s["root_size"]
        result["close_sprite_guid"] = result["close_sprite_guid"] or s["close_sprite_guid"]
        for cls in s["root_scripts"]:
            if cls not in result["base_classes"]:
                result["base_classes"].append(cls)
    if tmp and tmp >= legacy:
        result["text_system"] = "tmp"
    elif legacy:
        result["text_system"] = "legacy"
    if result["text_system"] == "unknown" and result["prefabs"]:
        result["warnings"].append("no Text/TMP components found in the given prefabs; defaulting to legacy Text at plan time")
    return result


def cmd_probe_style(args):
    style = probe_style(args.prefab, args.assets_root)
    _emit({"ok": True, "style": style}, args.out)
    return 0


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(prog="inapp_prefab_plan", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe-style", help="Read existing popup prefabs for UI conventions.")
    p.add_argument("--prefab", action="append", required=True, help="Path to a .prefab (repeatable).")
    p.add_argument("--assets-root", default="Assets", help="Folder scanned for *.cs.meta to name scripts.")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_probe_style)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_inapp_prefab_style_probe -v`
Expected: 4 PASS. If `root_size` is `None`, check the fixture's root RectTransform has `m_Father: {fileID: 0}` and `m_SizeDelta` on separate lines (the regex is line-anchored).

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_style_probe.py
git commit -m "feat(inapp-prefab): probe-style reads popup prefab conventions"
```

---

### Task 3: Planner core — naming, anchors, layout join, panel/frame, unplaced fallback

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (append after `probe_style`, before the CLI)
- Test: `tests/test_inapp_prefab_plan.py`

**Interfaces:**
- Consumes: `probe_style` output shape (Task 2).
- Produces:
  - `pascal(key) -> str`, `camel(key) -> str`, `field_name(bucket, key) -> str`, `node_name(bucket, key) -> str`
  - `anchors_from_bbox(bbox, panel) -> (anchor_min: [x,y], anchor_max: [x,y])`
  - `unwrap_template(obj) -> dict` (accepts a raw `get` output or a bare record)
  - `layout_from_build(build_result, envelope=None) -> {"elements": [...], "client_zones": [...]}` where each element is `{"bucket","key","role","bbox","observed_text"}` and each zone `{"zone","bbox"}`
  - `plan_prefab(template, layout=None, style=None, options=None) -> {"ok": bool, "plan": dict, "report": dict}`; plan keys: `schema_version, template, ui, view, paths, nodes, customs, report`. Node keys: `name, parent, binding, components, field, field_type, anchor_min, anchor_max, size, placed, can_be_hidden, inactive, key, bucket, role, click_actions, custom_cta_names, sprite_guid`.
  - Fixed node names later tasks rely on: `Dimmer` (field `dimmer`, Image), `Frame`, `Panel` (field `panel`, RectTransform), `Unplaced`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inapp_prefab_plan.py
"""Offline tests for the prefab planner (template + layout -> plan JSON)."""
import copy
import importlib.util
import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
HELPER = os.path.join(SKILL, "inapp_prefab_plan.py")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


TEMPLATE = _load("template_one_cta.json")
BUILD = _load("build_result_one_cta.json")
STYLE = {"text_system": "legacy", "font_guid": "e7a63bee4e93df34ca0dd3548b336621", "tmp_font_guid": None,
         "root_size": [900.0, 1400.0], "close_sprite_guid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
         "base_classes": ["OfferPopup"], "prefabs": [], "warnings": []}


def _node(plan, name):
    for n in plan["nodes"]:
        if n["name"] == name:
            return n
    raise AssertionError("node %s missing; have %s" % (name, [n["name"] for n in plan["nodes"]]))


class TestNaming(unittest.TestCase):
    def test_pascal_camel_field(self):
        self.assertEqual(mod.pascal("one_cta_offer"), "OneCtaOffer")
        self.assertEqual(mod.camel("background_image"), "backgroundImage")
        self.assertEqual(mod.field_name("images", "background_image"), "backgroundImage")
        self.assertEqual(mod.field_name("images", "hero"), "heroImage")
        self.assertEqual(mod.field_name("texts", "header"), "headerText")
        self.assertEqual(mod.field_name("buttons", "cta_button"), "ctaButton")
        self.assertEqual(mod.field_name("buttons", "cta"), "ctaButton")
        self.assertEqual(mod.node_name("texts", "fine_print"), "FinePrintText")


class TestAnchors(unittest.TestCase):
    def test_header_relative_to_background_panel(self):
        amin, amax = mod.anchors_from_bbox({"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05},
                                           {"x": 0.2, "y": 0.06, "w": 0.57, "h": 0.7})
        self.assertAlmostEqual(amin[0], 0.1404, places=3)
        self.assertAlmostEqual(amin[1], 0.8571, places=3)
        self.assertAlmostEqual(amax[0], 0.8772, places=3)
        self.assertAlmostEqual(amax[1], 0.9286, places=3)

    def test_clamps_and_keeps_a_minimum_extent(self):
        amin, amax = mod.anchors_from_bbox({"x": -0.5, "y": 0.5, "w": 0.1, "h": 0.0},
                                           {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})
        self.assertEqual(amin[0], 0.0)
        self.assertGreaterEqual(amax[1] - amin[1], 0.01)


class TestLayoutFromBuild(unittest.TestCase):
    def test_elements_and_zones(self):
        layout = mod.layout_from_build(BUILD)
        keys = {(e["bucket"], e["key"]) for e in layout["elements"]}
        self.assertIn(("texts", "header"), keys)
        self.assertIn(("buttons", "cta_button"), keys)
        self.assertEqual({z["zone"] for z in layout["client_zones"]},
                         {"resource_area", "price_before_sale", "timer"})

    def test_envelope_corrections_apply(self):
        envelope = {"corrections": {
            "excluded": [{"key": "fine_print", "bucket": "texts"}],
            "adjusted": [{"key": "header", "bucket": "texts", "bbox": {"x": 0.3, "y": 0.12, "w": 0.4, "h": 0.05},
                          "original_bbox": {"x": 0.28, "y": 0.11, "w": 0.42, "h": 0.05}}],
            "missed": [{"key": "hero_image", "bucket": "images", "bbox": {"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.2}}]}}
        layout = mod.layout_from_build(BUILD, envelope)
        by_key = {e["key"]: e for e in layout["elements"]}
        self.assertNotIn("fine_print", by_key)
        self.assertEqual(by_key["header"]["bbox"]["x"], 0.3)
        self.assertEqual(by_key["hero_image"]["bucket"], "images")


class TestPlanCore(unittest.TestCase):
    def setUp(self):
        self.result = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})
        self.plan = self.result["plan"]

    def test_identity_and_paths(self):
        self.assertTrue(self.result["ok"])
        self.assertEqual(self.plan["view"]["class_name"], "KinoaInAppOneCtaOfferView")
        self.assertEqual(self.plan["view"]["ns"], "Kinoa.InApps")
        self.assertEqual(self.plan["paths"]["prefab_path"],
                         "Assets/Kinoa/InApps/OneCtaOffer/KinoaInApp_OneCtaOffer.prefab")
        self.assertEqual(self.plan["paths"]["plan_path"],
                         "Assets/Kinoa/InApps/OneCtaOffer/one_cta_offer.inapp-plan.json")
        self.assertEqual(self.plan["template"]["key"], "one_cta_offer")
        self.assertEqual(self.plan["template"]["id"], TEMPLATE["id"])

    def test_frame_follows_style_root_size_when_no_image_size(self):
        self.assertEqual(self.plan["ui"]["frame_size"], [900.0, 1400.0])
        self.assertEqual(self.plan["ui"]["text_system"], "legacy")
        self.assertEqual(self.plan["ui"]["font_guid"], STYLE["font_guid"])

    def test_frame_height_follows_image_aspect(self):
        plan = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {"image_size": [1080, 1920]})["plan"]
        self.assertEqual(plan["ui"]["frame_size"], [900.0, 1600.0])

    def test_fixed_chrome_nodes(self):
        dimmer, frame, panel = _node(self.plan, "Dimmer"), _node(self.plan, "Frame"), _node(self.plan, "Panel")
        self.assertEqual(dimmer["field"], "dimmer")
        self.assertEqual(frame["size"], [900.0, 1400.0])
        self.assertEqual(panel["parent"], "Frame")
        self.assertEqual(panel["field_type"], "RectTransform")
        # panel = background_image bbox (x .2 y .06 w .57 h .7) in flipped-y anchors
        self.assertAlmostEqual(panel["anchor_min"][0], 0.2, places=3)
        self.assertAlmostEqual(panel["anchor_min"][1], 0.24, places=3)
        self.assertAlmostEqual(panel["anchor_max"][1], 0.94, places=3)

    def test_background_stretches_the_panel(self):
        bg = _node(self.plan, "BackgroundImage")
        self.assertEqual(bg["parent"], "Panel")
        self.assertEqual(bg["anchor_min"], [0.0, 0.0])
        self.assertEqual(bg["anchor_max"], [1.0, 1.0])
        self.assertEqual(bg["components"], ["Image"])
        self.assertEqual(bg["field"], "backgroundImage")

    def test_text_node_is_placed_from_layout(self):
        header = _node(self.plan, "HeaderText")
        self.assertTrue(header["placed"])
        self.assertEqual(header["components"], ["Text"])
        self.assertEqual(header["field_type"], "Text")
        self.assertAlmostEqual(header["anchor_min"][0], 0.1404, places=3)

    def test_button_node_and_label_child(self):
        cta = _node(self.plan, "CtaButton")
        self.assertEqual(cta["components"], ["Image", "Button"])
        self.assertEqual(cta["click_actions"], TEMPLATE["buttons"][1]["clickActionType"])
        self.assertFalse(cta["can_be_hidden"])
        label = _node(self.plan, "CtaButtonLabel")
        self.assertEqual(label["parent"], "CtaButton")
        self.assertEqual(label["binding"], "button_label")
        self.assertEqual(label["field"], "ctaButtonLabel")
        close = _node(self.plan, "CloseButton")
        self.assertEqual(close["sprite_guid"], STYLE["close_sprite_guid"])

    def test_no_unplaced_when_layout_is_complete(self):
        self.assertEqual(self.plan["report"]["unplaced"], [])
        self.assertNotIn("Unplaced", [n["name"] for n in self.plan["nodes"]])

    def test_fallback_without_layout_stacks_every_slot(self):
        result = mod.plan_prefab(TEMPLATE, None, STYLE, {})
        plan = result["plan"]
        self.assertIn("Unplaced", [n["name"] for n in plan["nodes"]])
        header = _node(plan, "HeaderText")
        self.assertFalse(header["placed"])
        self.assertEqual(header["parent"], "Unplaced")
        self.assertIn("header", plan["report"]["unplaced"])
        self.assertTrue(any("no layout" in w for w in plan["report"]["warnings"]))
        bg = _node(plan, "BackgroundImage")
        self.assertEqual(bg["parent"], "Panel")  # background always stretches the panel

    def test_template_can_be_raw_get_output(self):
        wrapped = {"http_status": 200, "ok": True, "id": TEMPLATE["id"], "response": copy.deepcopy(TEMPLATE)}
        self.assertEqual(mod.unwrap_template(wrapped)["key"], "one_cta_offer")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_plan -v`
Expected: FAIL — `AttributeError: module has no attribute 'pascal'`.

- [ ] **Step 3: Implement naming, anchors, layout join, and the plan core**

Append to `inapp_prefab_plan.py` after `cmd_probe_style`:

```python
# --------------------------------------------------------------------------- naming

_CS_KEYWORDS = {"object", "event", "string", "class", "base", "default", "params", "ref", "out", "in",
                "new", "lock", "fixed", "checked", "operator", "namespace", "internal", "switch", "case"}
_FIELD_SUFFIX = {"images": "Image", "texts": "Text", "buttons": "Button"}
DEFAULT_OUT_DIR = "Assets/Kinoa/InApps"
VIEW_NAMESPACE = "Kinoa.InApps"


def pascal(key):
    parts = [p for p in re.split(r"[^0-9a-zA-Z]+", key or "") if p]
    out = "".join(p[:1].upper() + p[1:] for p in parts) or "Element"
    return ("_" + out) if out[0].isdigit() else out


def camel(key):
    p = pascal(key)
    return p[:1].lower() + p[1:]


def field_name(bucket, key):
    base = camel(key)
    suffix = _FIELD_SUFFIX.get(bucket)
    if suffix:
        if base.lower().endswith(suffix.lower()):
            base = base[: -len(suffix)] + suffix
        else:
            base += suffix
    if base in _CS_KEYWORDS:
        base = "_" + base
    return base


def node_name(bucket, key):
    f = field_name(bucket, key)
    return f[:1].upper() + f[1:]


# --------------------------------------------------------------------------- geometry

def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def anchors_from_bbox(bbox, panel):
    """Normalised image bbox -> uGUI anchors relative to `panel` (also an image bbox).

    uGUI anchors have origin bottom-left; mockup bboxes have origin top-left, so y flips.
    Degenerate boxes are widened to 0.01 so the RectTransform never collapses.
    """
    pw = max(float(panel.get("w", 1.0)), 1e-6)
    ph = max(float(panel.get("h", 1.0)), 1e-6)
    rx = (float(bbox.get("x", 0.0)) - float(panel.get("x", 0.0))) / pw
    ry = (float(bbox.get("y", 0.0)) - float(panel.get("y", 0.0))) / ph
    rw = float(bbox.get("w", 0.0)) / pw
    rh = float(bbox.get("h", 0.0)) / ph
    x0, x1 = _clamp01(rx), _clamp01(rx + rw)
    y_top, y_bottom = _clamp01(ry), _clamp01(ry + rh)
    amin = [x0, _clamp01(1.0 - y_bottom)]
    amax = [x1, _clamp01(1.0 - y_top)]
    for i in (0, 1):
        if amax[i] - amin[i] < 0.01:
            amax[i] = min(1.0, amin[i] + 0.01)
            if amax[i] - amin[i] < 0.01:
                amin[i] = max(0.0, amax[i] - 0.01)
    return [round(amin[0], 4), round(amin[1], 4)], [round(amax[0], 4), round(amax[1], 4)]


def _union(bboxes):
    xs0 = [b["x"] for b in bboxes]
    ys0 = [b["y"] for b in bboxes]
    xs1 = [b["x"] + b["w"] for b in bboxes]
    ys1 = [b["y"] + b["h"] for b in bboxes]
    return {"x": min(xs0), "y": min(ys0), "w": max(xs1) - min(xs0), "h": max(ys1) - min(ys0)}


# --------------------------------------------------------------------------- template + layout inputs

BUCKETS = ("images", "buttons", "texts", "customs")


def unwrap_template(obj):
    """Accept the raw `kinoa_dashboard_inapp_template.py get` output or a bare record."""
    if isinstance(obj, dict) and "response" in obj and isinstance(obj["response"], dict) and "key" in obj["response"]:
        return obj["response"]
    return obj


def _template_problems(template):
    problems = []
    if not isinstance(template, dict):
        return ["template is not an object"]
    if not template.get("key"):
        problems.append("template.key missing")
    for bucket in BUCKETS:
        if not isinstance(template.get(bucket), list):
            problems.append("template.%s missing or not a list" % bucket)
    return problems


def layout_from_build(build_result, envelope=None):
    """`inapp_template_build.py build` output (+ confirm-page envelope) -> layout."""
    report = build_result.get("report") or {}
    elements = []
    for e in report.get("elements") or []:
        elements.append({"bucket": e.get("bucket"), "key": e.get("key"), "role": e.get("role"),
                         "bbox": e.get("bbox"), "observed_text": e.get("observed_text")})
    zones = [{"zone": c.get("role"), "bbox": c.get("bbox")} for c in report.get("client_rendered") or []]
    corrections = (envelope or {}).get("corrections") or {}
    excluded = {(c.get("bucket"), c.get("key")) for c in corrections.get("excluded") or []}
    elements = [e for e in elements if (e["bucket"], e["key"]) not in excluded]
    for adj in corrections.get("adjusted") or []:
        for e in elements:
            if e["key"] == adj.get("key") and (adj.get("bucket") in (None, e["bucket"])) and adj.get("bbox"):
                e["bbox"] = adj["bbox"]
    for miss in corrections.get("missed") or []:
        if miss.get("key") and miss.get("bbox"):
            elements.append({"bucket": miss.get("bucket"), "key": miss["key"], "role": None,
                             "bbox": miss["bbox"], "observed_text": None})
    return {"elements": elements, "client_zones": zones}


def _index_layout(layout):
    by_pair, by_key, zones = {}, {}, {}
    for e in (layout or {}).get("elements") or []:
        if not e.get("bbox"):
            continue
        by_pair[(e.get("bucket"), e.get("key"))] = e
        by_key.setdefault(e.get("key"), e)
    for z in (layout or {}).get("client_zones") or []:
        if z.get("bbox"):
            zones[z.get("zone")] = z["bbox"]
    return by_pair, by_key, zones


# --------------------------------------------------------------------------- plan

def _node(name, parent, binding, components=None, field=None, field_type=None, anchor_min=None,
          anchor_max=None, size=None, placed=True, can_be_hidden=False, inactive=False, key=None,
          bucket=None, role=None, click_actions=None, custom_cta_names=None, sprite_guid=None):
    return {"name": name, "parent": parent, "binding": binding, "components": components or [],
            "field": field, "field_type": field_type, "anchor_min": anchor_min, "anchor_max": anchor_max,
            "size": size, "placed": placed, "can_be_hidden": can_be_hidden, "inactive": inactive,
            "key": key, "bucket": bucket, "role": role, "click_actions": click_actions or [],
            "custom_cta_names": custom_cta_names or [], "sprite_guid": sprite_guid}


def _frame_size(style, options):
    root = (style or {}).get("root_size") or []
    width = float(root[0]) if len(root) == 2 and root[0] else 1080.0
    image_size = (options or {}).get("image_size")
    if image_size and image_size[0]:
        height = round(width * float(image_size[1]) / float(image_size[0]), 1)
    else:
        height = float(root[1]) if len(root) == 2 and root[1] else 1920.0
    return [width, height]


def plan_prefab(template, layout=None, style=None, options=None):
    template = unwrap_template(template)
    options = options or {}
    style = style or {}
    problems = _template_problems(template)
    if problems:
        return {"ok": False, "error": "template_invalid", "problems": problems}

    key = template["key"]
    P = pascal(key)
    out_dir = (options.get("out_dir") or DEFAULT_OUT_DIR).rstrip("/")
    class_name = "KinoaInApp%sView" % P
    prefab_name = "KinoaInApp_%s" % P
    report = {"unplaced": [], "estimated_positions": [], "warnings": [], "unmapped_layout": [],
              "client_zones": [], "needs_developer": []}

    by_pair, by_key, zone_boxes = _index_layout(layout)
    if not layout or not (layout.get("elements") or layout.get("client_zones")):
        report["warnings"].append("no layout source given — every slot is stacked in the Unplaced container; "
                                  "re-run with --build or --layout to position them")

    def lookup(bucket, slot_key):
        return by_pair.get((bucket, slot_key)) or by_key.get(slot_key)

    template_keys = {(b, s["key"]) for b in BUCKETS for s in template[b] if s.get("key")}
    for (bucket, lkey), e in by_pair.items():
        if (bucket, lkey) not in template_keys and lkey not in {k for _, k in template_keys}:
            report["unmapped_layout"].append({"bucket": bucket, "key": lkey})

    # Panel = the background image's bbox, else the union of placed element boxes, else the whole image.
    bg_slot = next((s for s in template["images"] if s.get("key") == "background_image"), None)
    bg_layout = lookup("images", "background_image") if bg_slot else None
    if bg_layout and bg_layout.get("bbox"):
        panel_bbox = bg_layout["bbox"]
    else:
        boxes = [e["bbox"] for e in by_pair.values()]
        panel_bbox = _union(boxes) if boxes else {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    full = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

    text_system = style.get("text_system") if style.get("text_system") in ("legacy", "tmp") else "legacy"
    frame_size = _frame_size(style, options)
    ui = {"text_system": text_system, "font_guid": style.get("font_guid"), "tmp_font_guid": style.get("tmp_font_guid"),
          "frame_size": frame_size, "close_sprite_guid": style.get("close_sprite_guid"), "dimmer_alpha": 0.6}

    panel_min, panel_max = anchors_from_bbox(panel_bbox, full)
    nodes = [
        _node("Dimmer", None, "dimmer", ["Image"], field="dimmer", field_type="Image",
              anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]),
        _node("Frame", None, "frame", [], size=frame_size),
        _node("Panel", "Frame", "panel", [], field="panel", field_type="RectTransform",
              anchor_min=panel_min, anchor_max=panel_max),
    ]
    unplaced_nodes = []

    def place(node, bbox, slot_key):
        if bbox:
            node["anchor_min"], node["anchor_max"] = anchors_from_bbox(bbox, panel_bbox)
            node["placed"] = True
            nodes.append(node)
        else:
            node["placed"] = False
            node["parent"] = "Unplaced"
            report["unplaced"].append(slot_key)
            unplaced_nodes.append(node)

    ordered = sorted(((b, s) for b in ("images", "buttons", "texts") for s in template[b]),
                     key=lambda pair: (pair[1].get("index") is None, pair[1].get("index") or 0))
    for bucket, slot in ordered:
        skey = slot.get("key")
        if not skey:
            continue
        name = node_name(bucket, skey)
        fld = field_name(bucket, skey)
        hidden = bool(slot.get("canBeHidden", False))
        lay = lookup(bucket, skey) or {}
        role = lay.get("role")
        if bucket == "images":
            node = _node(name, "Panel", "image", ["Image"], field=fld, field_type="Image",
                         can_be_hidden=hidden, key=skey, bucket=bucket, role=role)
            if skey == "background_image":
                node["anchor_min"], node["anchor_max"] = [0.0, 0.0], [1.0, 1.0]
                node["placed"] = bool(lay.get("bbox"))
                nodes.append(node)
            else:
                place(node, lay.get("bbox"), skey)
        elif bucket == "texts":
            node = _node(name, "Panel", "text", ["Text"], field=fld, field_type="Text",
                         can_be_hidden=hidden, key=skey, bucket=bucket, role=role)
            place(node, lay.get("bbox"), skey)
        else:  # buttons
            sprite = ui["close_sprite_guid"] if re.search(r"close|dismiss", skey, re.I) else None
            node = _node(name, "Panel", "button", ["Image", "Button"], field=fld, field_type="Button",
                         can_be_hidden=hidden, key=skey, bucket=bucket, role=role,
                         click_actions=list(slot.get("clickActionType") or []),
                         custom_cta_names=list(slot.get("customCtaNames") or []), sprite_guid=sprite)
            place(node, lay.get("bbox"), skey)
            label = _node(name + "Label", name, "button_label", ["Text"], field=fld + "Label", field_type="Text",
                          anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0], key=skey, bucket=bucket)
            (nodes if node["placed"] else unplaced_nodes).append(label)

    if unplaced_nodes:
        nodes.append(_node("Unplaced", "Panel", "unplaced", ["VerticalLayoutGroup"],
                           anchor_min=[0.05, 0.02], anchor_max=[0.95, 0.30]))
        nodes.extend(unplaced_nodes)

    plan = {
        "schema_version": SCHEMA_VERSION,
        "template": {"id": template.get("id"), "key": key, "name": template.get("name"),
                     "feature_type": template.get("featureType") or "standard",
                     "images": [{"key": s["key"], "can_be_hidden": bool(s.get("canBeHidden", False))}
                                for s in template["images"] if s.get("key")],
                     "texts": [{"key": s["key"], "can_be_hidden": bool(s.get("canBeHidden", False)),
                                "custom_fields": [c.get("key") for c in s.get("customFields") or []]}
                               for s in template["texts"] if s.get("key")],
                     "buttons": [{"key": s["key"], "can_be_hidden": bool(s.get("canBeHidden", False)),
                                  "click_actions": list(s.get("clickActionType") or []),
                                  "custom_cta_names": list(s.get("customCtaNames") or [])}
                                 for s in template["buttons"] if s.get("key")],
                     "customs": [{"key": s["key"], "kind": s.get("kind"), "default": s.get("defaultValue")}
                                 for s in template["customs"] if s.get("key")]},
        "ui": ui,
        "view": {"class_name": class_name, "ns": VIEW_NAMESPACE, "facade": None, "facade_namespace": None},
        "paths": {"out_dir": out_dir,
                  "prefab_path": "%s/%s/%s.prefab" % (out_dir, P, prefab_name),
                  "view_path": "%s/%s/%s.cs" % (out_dir, P, class_name),
                  "plan_path": "%s/%s/%s.inapp-plan.json" % (out_dir, P, key)},
        "nodes": nodes,
        "customs": [],
        "report": report,
    }
    _add_client_zones(plan, template, zone_boxes, panel_bbox)
    _add_customs(plan, template)
    _add_feature(plan, template, by_key, panel_bbox)
    if style.get("base_classes"):
        report["needs_developer"].append(
            "existing popup base class(es) %s detected — the generated view derives from MonoBehaviour and exposes a "
            "Closed event; adapt/wrap it in your popup manager rather than editing the generated class"
            % ", ".join(style["base_classes"]))
    return {"ok": True, "plan": plan, "report": report}


def _add_client_zones(plan, template, zone_boxes, panel_bbox):
    """Task 4 fills this in."""


def _add_customs(plan, template):
    """Task 4 fills this in."""


def _add_feature(plan, template, by_key, panel_bbox):
    """Task 4 fills this in."""
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_inapp_prefab_plan -v`
Expected: every test in `TestNaming`, `TestAnchors`, `TestLayoutFromBuild`, `TestPlanCore` PASSES. (The three `_add_*` stubs are intentionally empty; Task 4 replaces them and adds their tests.)

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_plan.py
git commit -m "feat(inapp-prefab): planner core — naming, anchors, layout join, panel/frame, unplaced fallback"
```

---

### Task 4: Planner — client-rendered zones, custom knobs, feature UIs, layout-file path, `plan` + `layout-schema` CLI

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (replace the three stubs; add `layout_from_layout_file`, `LAYOUT_SCHEMA`, `cmd_plan`, `cmd_layout_schema`, CLI wiring)
- Test: `tests/test_inapp_prefab_plan.py` (append classes)

**Interfaces:**
- Produces fixed node/field names the view generator (Tasks 6–7) binds to:

| Node | field | field_type | present when |
|---|---|---|---|
| `TimerZone` / `TimerText` | `timerRoot` / `timerText` | GameObject / Text | always |
| `PriceBeforeSaleZone` / `PriceBeforeSaleText` / `PriceBeforeSaleStrike` | `priceBeforeSaleRoot` / `priceBeforeSaleText` / — | GameObject / Text / — | any button lists `billing` |
| `ResourceArea` / `ResourceItem` | `resourceAreaRoot` / `resourceItemTemplate` | GameObject / KinoaInAppItemView | any button lists an item-bearing action (`collect_resource`, `billing`, `soft_billing`, `show_ad`, `promise_rewards`) |
| `GrandPrizeArea` / `GrandPrizeImage` / `GrandPrizeText` | `grandPrizeRoot` / `grandPrizeImage` / `grandPrizeText` | GameObject / Image / Text | `featureType == milestone` |
| `MilestoneBar` / `MilestoneFill` / `MilestoneMarkers` / `MilestoneMarker` / `MilestoneMainButton` / `MilestoneMainButtonLabel` | `milestoneBarRoot` / `milestoneFill` / `milestoneMarkersRoot` / `milestoneMarkerTemplate` / `milestoneMainButton` / `milestoneMainButtonLabel` | GameObject / Image / RectTransform / KinoaInAppItemView / Button / Text | `featureType == milestone` |
| `MissionList` / `MissionRow` / `MissionBar` / `MissionBarFill` | `missionListRoot` / `missionRowTemplate` / `missionBarRoot` / `missionBarFill` | RectTransform / KinoaInAppItemView / GameObject / Image | `featureType == mission` (bar only unless `progressBar.display == dont_show_at_all`) |

- `plan["customs"]`: `[{"key","kind","default","target_node","target_field"}]` — boolean customs whose key minus a `show_`/`has_`/`display_`/`enable_` prefix matches a node key or zone get a `target_field` (the GameObject-typed field of that node or zone root).
- `layout_from_layout_file(layout) -> {"elements","client_zones"}` for the tip-image path; `LAYOUT_SCHEMA` printed by `layout-schema`.
- CLI: `plan --template F [--build F [--confirmed F] | --layout F] [--style F] [--image-size WxH] [--out-dir D] [--out F]` → prints `{ok, plan_path, plan, report}`; exit 2 on `template_invalid` / unreadable input.

- [ ] **Step 1: Append the failing tests**

```python
ITEM_BEARING = {"collect_resource", "billing", "soft_billing", "show_ad", "promise_rewards"}


def _milestone_template():
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "chase"
    t["featureType"] = "milestone"
    t["features"] = {"milestone": {"key": "main_progressbar", "name": "Main Progressbar", "limit": 3,
                                   "mainActionTypes": ["close"], "milestonesActionTypes": ["collect_resource"]}}
    t["images"].append({"key": "bar_image", "name": "Bar", "index": 10, "canBeHidden": False, "customFields": []})
    return t


def _mission_template(display="show_for_all_sets_combined"):
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "board"
    t["featureType"] = "mission"
    t["features"] = {"mission": {"key": "missions", "name": "Missions",
                                 "progressBar": {"display": display, "completionBarCta": ["collect_resource"]},
                                 "completionCta": ["collect_resource"], "activeProgressCta": ["close"],
                                 "maxPlacements": 10, "maxSetsCount": 7, "minPlacements": 1, "minSetsCount": 1}}
    return t


class TestClientZonesAndCustoms(unittest.TestCase):
    def setUp(self):
        self.plan = mod.plan_prefab(TEMPLATE, mod.layout_from_build(BUILD), STYLE, {})["plan"]

    def test_timer_zone_is_placed_from_layout_and_inactive(self):
        zone = _node(self.plan, "TimerZone")
        self.assertEqual(zone["field"], "timerRoot")
        self.assertEqual(zone["field_type"], "GameObject")
        self.assertTrue(zone["inactive"])
        self.assertTrue(zone["placed"])
        text = _node(self.plan, "TimerText")
        self.assertEqual(text["parent"], "TimerZone")
        self.assertEqual(text["field"], "timerText")

    def test_price_zone_present_because_cta_lists_billing(self):
        zone = _node(self.plan, "PriceBeforeSaleZone")
        self.assertEqual(zone["field"], "priceBeforeSaleRoot")
        strike = _node(self.plan, "PriceBeforeSaleStrike")
        self.assertEqual(strike["components"], ["Image"])
        self.assertEqual(strike["parent"], "PriceBeforeSaleZone")

    def test_resource_area_with_item_template(self):
        area = _node(self.plan, "ResourceArea")
        self.assertEqual(area["components"], ["HorizontalLayoutGroup"])
        item = _node(self.plan, "ResourceItem")
        self.assertEqual(item["binding"], "item_template")
        self.assertEqual(item["field"], "resourceItemTemplate")
        self.assertEqual(item["field_type"], "KinoaInAppItemView")
        self.assertTrue(item["inactive"])

    def test_no_grand_prize_on_standard(self):
        self.assertNotIn("GrandPrizeArea", [n["name"] for n in self.plan["nodes"]])

    def test_boolean_custom_targets_the_resource_area(self):
        customs = {c["key"]: c for c in self.plan["customs"]}
        self.assertEqual(customs["show_resource_area"]["kind"], "boolean")
        self.assertEqual(customs["show_resource_area"]["target_node"], "ResourceArea")
        self.assertEqual(customs["show_resource_area"]["target_field"], "resourceAreaRoot")

    def test_zone_without_layout_gets_default_anchors_and_is_reported(self):
        plan = mod.plan_prefab(TEMPLATE, None, STYLE, {})["plan"]
        timer = _node(plan, "TimerZone")
        self.assertEqual(timer["anchor_min"], [0.3, 0.02])
        self.assertIn("TimerZone", plan["report"]["estimated_positions"])

    def test_no_price_zone_without_billing(self):
        t = copy.deepcopy(TEMPLATE)
        t["buttons"][1]["clickActionType"] = ["close", "deep_link"]
        plan = mod.plan_prefab(t, mod.layout_from_build(BUILD), STYLE, {})["plan"]
        names = [n["name"] for n in plan["nodes"]]
        self.assertNotIn("PriceBeforeSaleZone", names)
        self.assertNotIn("ResourceArea", names)


class TestFeatures(unittest.TestCase):
    def test_milestone_nodes(self):
        layout = mod.layout_from_build(BUILD)
        layout["elements"].append({"bucket": "images", "key": "bar_image", "role": "bar_image",
                                   "bbox": {"x": 0.25, "y": 0.6, "w": 0.5, "h": 0.04}, "observed_text": None})
        plan = mod.plan_prefab(_milestone_template(), layout, STYLE, {})["plan"]
        bar = _node(plan, "MilestoneBar")
        self.assertEqual(bar["field"], "milestoneBarRoot")
        self.assertAlmostEqual(bar["anchor_min"][0], (0.25 - 0.2) / 0.57, places=3)  # follows bar_image
        self.assertEqual(_node(plan, "MilestoneFill")["field_type"], "Image")
        self.assertEqual(_node(plan, "MilestoneMarkers")["components"], ["HorizontalLayoutGroup"])
        marker = _node(plan, "MilestoneMarker")
        self.assertEqual(marker["parent"], "MilestoneMarkers")
        self.assertEqual(marker["field"], "milestoneMarkerTemplate")
        self.assertEqual(_node(plan, "MilestoneMainButtonLabel")["parent"], "MilestoneMainButton")
        self.assertEqual(_node(plan, "GrandPrizeArea")["field"], "grandPrizeRoot")
        self.assertEqual(plan["template"]["feature_type"], "milestone")

    def test_mission_nodes_with_and_without_bar(self):
        plan = mod.plan_prefab(_mission_template(), None, STYLE, {})["plan"]
        self.assertEqual(_node(plan, "MissionList")["field_type"], "RectTransform")
        self.assertEqual(_node(plan, "MissionRow")["field"], "missionRowTemplate")
        self.assertEqual(_node(plan, "MissionBarFill")["field"], "missionBarFill")
        self.assertIn("MissionList", plan["report"]["estimated_positions"])
        plan2 = mod.plan_prefab(_mission_template("dont_show_at_all"), None, STYLE, {})["plan"]
        self.assertNotIn("MissionBar", [n["name"] for n in plan2["nodes"]])


class TestLayoutFile(unittest.TestCase):
    def test_layout_file_elements_and_unknown_keys(self):
        layout = mod.layout_from_layout_file({
            "schema_version": "1.0", "source_image": {"width": 1080, "height": 1920},
            "elements": [{"key": "header", "bbox": {"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.05}},
                         {"key": "bogus", "bucket": "texts", "bbox": {"x": 0.3, "y": 0.5, "w": 0.4, "h": 0.05}}],
            "client_zones": [{"zone": "timer", "bbox": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.03}}]})
        self.assertEqual(layout["elements"][0]["bucket"], None)
        self.assertEqual(layout["image_size"], [1080, 1920])
        plan = mod.plan_prefab(TEMPLATE, layout, STYLE, {})
        self.assertEqual(plan["report"]["unmapped_layout"], [{"bucket": "texts", "key": "bogus"}])
        self.assertTrue(_node(plan["plan"], "HeaderText")["placed"])

    def test_layout_schema_lists_zones(self):
        self.assertEqual(mod.LAYOUT_SCHEMA["shape"]["client_zones"][0]["zone"],
                         "timer | price_before_sale | resource_area | grand_prize_area")


class TestPlanCli(unittest.TestCase):
    def test_plan_cli_writes_file(self):
        import subprocess, sys, tempfile
        out = os.path.join(tempfile.mkdtemp(), "p.json")
        style = os.path.join(tempfile.mkdtemp(), "s.json")
        with open(style, "w", encoding="utf-8") as fh:
            json.dump(STYLE, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", os.path.join(FIX, "template_one_cta.json"),
                              "--build", os.path.join(FIX, "build_result_one_cta.json"), "--style", style,
                              "--image-size", "1080x1920", "--out", out], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["plan"]["ui"]["frame_size"], [900.0, 1600.0])
        self.assertTrue(os.path.isfile(out))

    def test_plan_cli_rejects_invalid_template(self):
        import subprocess, sys, tempfile
        bad = os.path.join(tempfile.mkdtemp(), "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump({"name": "x"}, fh)
        res = subprocess.run([sys.executable, HELPER, "plan", "--template", bad], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)["error"], "template_invalid")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_plan -v`
Expected: the new classes FAIL (`TimerZone` missing, `LAYOUT_SCHEMA` missing, CLI `plan` unknown).

- [ ] **Step 3: Replace the three stubs and add the layout-file path + CLI**

```python
ITEM_BEARING_ACTIONS = ("collect_resource", "billing", "soft_billing", "show_ad", "promise_rewards")
CLIENT_ZONES = ("timer", "price_before_sale", "resource_area", "grand_prize_area")
_ZONE_DEFAULT_ANCHORS = {
    "timer": ([0.3, 0.02], [0.7, 0.07]),
    "price_before_sale": ([0.3, 0.26], [0.7, 0.31]),
    "resource_area": ([0.1, 0.35], [0.9, 0.5]),
    "grand_prize_area": ([0.7, 0.55], [0.95, 0.8]),
    "milestone_bar": ([0.1, 0.3], [0.9, 0.36]),
    "milestone_main": ([0.3, 0.1], [0.7, 0.17]),
    "mission_list": ([0.05, 0.2], [0.95, 0.75]),
    "mission_bar": ([0.1, 0.12], [0.9, 0.17]),
}
_TOGGLE_PREFIX_RE = re.compile(r"^(show|has|display|enable)_")


def _zone_anchors(plan, name, zone_boxes, panel_bbox, default_key, bbox=None):
    box = bbox or zone_boxes.get(default_key)
    if box:
        return anchors_from_bbox(box, panel_bbox)
    plan["report"]["estimated_positions"].append(name)
    amin, amax = _ZONE_DEFAULT_ANCHORS[default_key]
    return list(amin), list(amax)


def _add_client_zones(plan, template, zone_boxes, panel_bbox):
    nodes = plan["nodes"]
    actions = set()
    for b in template["buttons"]:
        actions.update(b.get("clickActionType") or [])
    wanted = ["timer"]
    if "billing" in actions:
        wanted.append("price_before_sale")
    if actions & set(ITEM_BEARING_ACTIONS):
        wanted.append("resource_area")
    if (template.get("featureType") or "standard") == "milestone":
        wanted.append("grand_prize_area")
    plan["report"]["client_zones"] = wanted

    if "timer" in wanted:
        amin, amax = _zone_anchors(plan, "TimerZone", zone_boxes, panel_bbox, "timer")
        nodes.append(_node("TimerZone", "Panel", "zone", [], field="timerRoot", field_type="GameObject",
                           anchor_min=amin, anchor_max=amax, inactive=True, placed="timer" in zone_boxes))
        nodes.append(_node("TimerText", "TimerZone", "text", ["Text"], field="timerText", field_type="Text",
                           anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))
    if "price_before_sale" in wanted:
        amin, amax = _zone_anchors(plan, "PriceBeforeSaleZone", zone_boxes, panel_bbox, "price_before_sale")
        nodes.append(_node("PriceBeforeSaleZone", "Panel", "zone", [], field="priceBeforeSaleRoot",
                           field_type="GameObject", anchor_min=amin, anchor_max=amax, inactive=True,
                           placed="price_before_sale" in zone_boxes))
        nodes.append(_node("PriceBeforeSaleText", "PriceBeforeSaleZone", "text", ["Text"], field="priceBeforeSaleText",
                           field_type="Text", anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))
        nodes.append(_node("PriceBeforeSaleStrike", "PriceBeforeSaleZone", "strike", ["Image"],
                           anchor_min=[0.05, 0.46], anchor_max=[0.95, 0.54]))
    if "resource_area" in wanted:
        amin, amax = _zone_anchors(plan, "ResourceArea", zone_boxes, panel_bbox, "resource_area")
        nodes.append(_node("ResourceArea", "Panel", "zone", ["HorizontalLayoutGroup"], field="resourceAreaRoot",
                           field_type="GameObject", anchor_min=amin, anchor_max=amax, inactive=True,
                           placed="resource_area" in zone_boxes))
        nodes.append(_node("ResourceItem", "ResourceArea", "item_template", [], field="resourceItemTemplate",
                           field_type="KinoaInAppItemView", size=[160.0, 160.0], inactive=True))
    if "grand_prize_area" in wanted:
        amin, amax = _zone_anchors(plan, "GrandPrizeArea", zone_boxes, panel_bbox, "grand_prize_area")
        nodes.append(_node("GrandPrizeArea", "Panel", "zone", [], field="grandPrizeRoot", field_type="GameObject",
                           anchor_min=amin, anchor_max=amax, inactive=True, placed="grand_prize_area" in zone_boxes))
        nodes.append(_node("GrandPrizeImage", "GrandPrizeArea", "image", ["Image"], field="grandPrizeImage",
                           field_type="Image", anchor_min=[0.0, 0.3], anchor_max=[1.0, 1.0]))
        nodes.append(_node("GrandPrizeText", "GrandPrizeArea", "text", ["Text"], field="grandPrizeText",
                           field_type="Text", anchor_min=[0.0, 0.0], anchor_max=[1.0, 0.3]))


_ZONE_ROOT_FIELD = {"timer": ("TimerZone", "timerRoot"), "price_before_sale": ("PriceBeforeSaleZone", "priceBeforeSaleRoot"),
                    "resource_area": ("ResourceArea", "resourceAreaRoot"), "grand_prize_area": ("GrandPrizeArea", "grandPrizeRoot")}


def _add_customs(plan, template):
    node_by_key = {(n.get("bucket"), n.get("key")): n for n in plan["nodes"] if n.get("key") and n["binding"] in ("image", "text", "button")}
    present_nodes = {n["name"] for n in plan["nodes"]}
    for slot in template["customs"]:
        key = slot.get("key")
        if not key:
            continue
        entry = {"key": key, "kind": slot.get("kind"), "default": slot.get("defaultValue"),
                 "target_node": None, "target_field": None}
        if slot.get("kind") == "boolean":
            target = _TOGGLE_PREFIX_RE.sub("", key)
            if target in _ZONE_ROOT_FIELD and _ZONE_ROOT_FIELD[target][0] in present_nodes:
                entry["target_node"], entry["target_field"] = _ZONE_ROOT_FIELD[target]
            else:
                for bucket in ("images", "texts", "buttons"):
                    node = node_by_key.get((bucket, target))
                    if node:
                        entry["target_node"], entry["target_field"] = node["name"], node["field"]
                        break
            if not entry["target_node"]:
                plan["report"]["needs_developer"].append(
                    "boolean custom '%s' has no matching node to toggle — read it via GetCustom<bool>(\"%s\")" % (key, key))
        plan["customs"].append(entry)


def _add_feature(plan, template, by_key, panel_bbox):
    ftype = template.get("featureType") or "standard"
    nodes = plan["nodes"]
    if ftype == "milestone":
        bar_el = by_key.get("bar_image") or {}
        amin, amax = _zone_anchors(plan, "MilestoneBar", {}, panel_bbox, "milestone_bar", bbox=bar_el.get("bbox"))
        nodes.append(_node("MilestoneBar", "Panel", "zone", ["Image"], field="milestoneBarRoot", field_type="GameObject",
                           anchor_min=amin, anchor_max=amax, placed=bool(bar_el.get("bbox"))))
        nodes.append(_node("MilestoneFill", "MilestoneBar", "fill", ["Image"], field="milestoneFill", field_type="Image",
                           anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))
        nodes.append(_node("MilestoneMarkers", "MilestoneBar", "markers", ["HorizontalLayoutGroup"],
                           field="milestoneMarkersRoot", field_type="RectTransform",
                           anchor_min=[0.0, -1.0], anchor_max=[1.0, 2.0]))
        nodes.append(_node("MilestoneMarker", "MilestoneMarkers", "item_template", [], field="milestoneMarkerTemplate",
                           field_type="KinoaInAppItemView", size=[120.0, 120.0], inactive=True))
        amin, amax = _zone_anchors(plan, "MilestoneMainButton", {}, panel_bbox, "milestone_main")
        nodes.append(_node("MilestoneMainButton", "Panel", "button", ["Image", "Button"], field="milestoneMainButton",
                           field_type="Button", anchor_min=amin, anchor_max=amax, can_be_hidden=True,
                           click_actions=list(((template.get("features") or {}).get("milestone") or {}).get("mainActionTypes") or [])))
        nodes.append(_node("MilestoneMainButtonLabel", "MilestoneMainButton", "button_label", ["Text"],
                           field="milestoneMainButtonLabel", field_type="Text", anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))
    elif ftype == "mission":
        amin, amax = _zone_anchors(plan, "MissionList", {}, panel_bbox, "mission_list")
        nodes.append(_node("MissionList", "Panel", "zone", ["VerticalLayoutGroup"], field="missionListRoot",
                           field_type="RectTransform", anchor_min=amin, anchor_max=amax))
        nodes.append(_node("MissionRow", "MissionList", "item_template", [], field="missionRowTemplate",
                           field_type="KinoaInAppItemView", size=[800.0, 140.0], inactive=True))
        mission = (template.get("features") or {}).get("mission") or {}
        display = (mission.get("progressBar") or {}).get("display")
        if display != "dont_show_at_all":
            amin, amax = _zone_anchors(plan, "MissionBar", {}, panel_bbox, "mission_bar")
            nodes.append(_node("MissionBar", "Panel", "zone", ["Image"], field="missionBarRoot", field_type="GameObject",
                               anchor_min=amin, anchor_max=amax))
            nodes.append(_node("MissionBarFill", "MissionBar", "fill", ["Image"], field="missionBarFill",
                               field_type="Image", anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))


# --------------------------------------------------------------------------- tip-image layout path

LAYOUT_SCHEMA = {
    "schema_version": SCHEMA_VERSION,
    "description": "Layout pass over a template's tip image, constrained to the template's slot keys. Consumed by `plan --layout`.",
    "shape": {
        "schema_version": SCHEMA_VERSION,
        "source_image": {"path": "str", "width": "int", "height": "int"},
        "elements": [{"key": "one of the template slot keys given in the prompt (images/buttons/texts)",
                      "bucket": "images | buttons | texts — optional, resolved from the template when absent",
                      "bbox": {"x": "0..1", "y": "0..1", "w": "0..1", "h": "0..1"},
                      "observed_text": "optional", "confidence": "0.0-1.0"}],
        "client_zones": [{"zone": "timer | price_before_sale | resource_area | grand_prize_area",
                          "bbox": {"x": "0..1", "y": "0..1", "w": "0..1", "h": "0..1"}}],
    },
    "notes": [
        "bbox is normalised to the whole image, origin top-left.",
        "Only slot keys that exist on the template may appear; unknown keys are reported under report.unmapped_layout, never dropped silently.",
        "A slot you cannot see on the image is simply omitted — the planner stacks it in the Unplaced container.",
        "Client-rendered zones are positions only: the planner never turns them into template slots.",
    ],
}


def layout_from_layout_file(layout):
    elements = [{"bucket": e.get("bucket"), "key": e.get("key"), "role": e.get("key"),
                 "bbox": e.get("bbox"), "observed_text": e.get("observed_text")}
                for e in layout.get("elements") or [] if e.get("key")]
    zones = [{"zone": z.get("zone"), "bbox": z.get("bbox")} for z in layout.get("client_zones") or []]
    src = layout.get("source_image") or {}
    size = [src["width"], src["height"]] if src.get("width") and src.get("height") else None
    return {"elements": elements, "client_zones": zones, "image_size": size}


def _parse_size(text):
    if not text:
        return None
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", text)
    if not m:
        raise ValueError("--image-size must look like 1080x1920")
    return [int(m.group(1)), int(m.group(2))]


def cmd_layout_schema(args):
    _emit(LAYOUT_SCHEMA)
    return 0


def cmd_plan(args):
    try:
        template = unwrap_template(_read_json(args.template))
        style = _read_json(args.style) if args.style else {}
        layout = None
        if args.build:
            layout = layout_from_build(_read_json(args.build), _read_json(args.confirmed) if args.confirmed else None)
        elif args.layout:
            layout = layout_from_layout_file(_read_json(args.layout))
        image_size = _parse_size(args.image_size) or (layout or {}).get("image_size")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _emit({"ok": False, "error": "unreadable_input", "detail": str(exc)})
        return 2
    result = plan_prefab(template, layout, style, {"image_size": image_size, "out_dir": args.out_dir})
    if not result["ok"]:
        _emit(result)
        return 2
    out = args.out or ("%s.inapp-plan.json" % result["plan"]["template"]["key"])
    _emit({"ok": True, "plan_path": out, "plan": result["plan"], "report": result["report"]}, out=None)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result["plan"], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return 0
```

Wire into `main()` (before `args = parser.parse_args(argv)`):

```python
    sub.add_parser("layout-schema", help="Print the tip-image layout contract.").set_defaults(func=cmd_layout_schema)

    p = sub.add_parser("plan", help="Template record + layout source -> prefab plan JSON.")
    p.add_argument("--template", required=True, help="Record from `kinoa_dashboard_inapp_template.py get` (raw output or bare record).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--build", default=None, help="build_result.json from kinoa-inapp-template-from-image (preferred layout source).")
    src.add_argument("--layout", default=None, help="layout.json from the tip-image vision pass (see layout-schema).")
    p.add_argument("--confirmed", default=None, help="Confirm-page envelope; its corrections are applied on top of --build.")
    p.add_argument("--style", default=None, help="probe-style output.")
    p.add_argument("--image-size", default=None, help="WxH of the mockup/tip image, e.g. 1080x1920.")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Game-project folder the generated files will live in.")
    p.add_argument("--out", default=None, help="Where to write the plan (default <key>.inapp-plan.json).")
    p.set_defaults(func=cmd_plan)
```

- [ ] **Step 4: Run the whole planner test module**

Run: `python -m unittest tests.test_inapp_prefab_plan -v`
Expected: all PASS. Then run `python -m unittest discover tests` — the pre-existing suite must still pass (the new helper has no boilerplate copies, so `test_boilerplate_consistency` is unaffected).

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_plan.py
git commit -m "feat(inapp-prefab): client zones, custom toggles, milestone/mission nodes, layout-file path, plan CLI"
```

---

### Task 5: Code generation — shared files (`KinoaInAppHooks`, `KinoaInAppItemView`, Editor `KinoaInAppPrefabBuilder`)

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (append `generate_code` + the three C# templates)
- Test: `tests/test_inapp_prefab_codegen.py`

**Interfaces:**
- Produces: `generate_code(plan, options) -> {"files": {project_relative_path: content}, "snippets": {...}, "report": {...}}`. This task emits the three shared files; Task 6/7 add the view; Task 8 adds snippets + CLI.
- Options read here: `text_system` comes from `plan["ui"]`; `image_loader`, `price_resolver`, `resource_icon_resolver` (fully-qualified static method names or `None`).
- Shared paths: `{out_dir}/Shared/KinoaInAppHooks.cs`, `{out_dir}/Shared/KinoaInAppItemView.cs`, `{out_dir}/Editor/KinoaInAppPrefabBuilder.cs`.
- C# names other tasks call: `KinoaInAppHooks.LoadSpriteFromUrl : Func<string, Task<Sprite>>`, `KinoaInAppHooks.ResolveStorePrice : Func<InAppStorePackages, bool, string>` (second arg `usePreSalePackage`: `true` reads the `*DiscountPackageID` pair — the pre-sale price shown struck through), `KinoaInAppHooks.ResolveResourceIcon : Func<string, Sprite>`, `KinoaInAppHooks.WarnMissing(string)`; `KinoaInAppItemView.SetLabel/SetValue/SetIcon/SetFill/SetButton(bool, UnityAction)`; `KinoaInAppPrefabBuilder.MenuPath`, `BuildAll() : string`, `BuildFromPlan(string) : BuildReport`, `.build-report.json` beside each plan.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inapp_prefab_codegen.py
"""Offline tests for the C# generator. Assertions are on text: the Unity compile gate runs in Task 11."""
import copy
import importlib.util
import json
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
HELPER = os.path.join(SKILL, "inapp_prefab_plan.py")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

with open(os.path.join(FIX, "template_one_cta.json"), encoding="utf-8") as _fh:
    TEMPLATE = json.load(_fh)
with open(os.path.join(FIX, "build_result_one_cta.json"), encoding="utf-8") as _fh:
    BUILD = json.load(_fh)
STYLE = {"text_system": "legacy", "font_guid": "e7a63bee4e93df34ca0dd3548b336621", "tmp_font_guid": None,
         "root_size": [900.0, 1400.0], "close_sprite_guid": None, "base_classes": [], "prefabs": [], "warnings": []}
FORBIDDEN = ("dashboard.kinoa.io", "Bearer", "UnityWebRequest", "Addressables.Load")


def _plan(template=TEMPLATE, style=STYLE, layout=None):
    layout = mod.layout_from_build(BUILD) if layout is None else layout
    return mod.plan_prefab(template, layout, style, {})["plan"]


class TestSharedFiles(unittest.TestCase):
    def setUp(self):
        self.out = mod.generate_code(_plan(), {})
        self.files = self.out["files"]

    def test_file_set(self):
        for path in ("Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs",
                     "Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs",
                     "Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"):
            self.assertIn(path, self.files)

    def test_no_forbidden_strings_anywhere(self):
        for path, content in self.files.items():
            for bad in FORBIDDEN:
                self.assertNotIn(bad, content, "%s contains %s" % (path, bad))

    def test_hooks_leave_todos_and_null_delegates_by_default(self):
        hooks = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs"]
        self.assertIn("public static Func<string, Task<Sprite>> LoadSpriteFromUrl = null;", hooks)
        self.assertIn("public static Func<InAppStorePackages, bool, string> ResolveStorePrice = null;", hooks)
        self.assertIn("public static Func<string, Sprite> ResolveResourceIcon = null;", hooks)
        self.assertEqual(hooks.count("TODO(kinoa-prefab):"), 3)
        self.assertIn("using Kinoa.Data.Messaging.InApp;", hooks)
        self.assertIn("namespace Kinoa.InApps", hooks)

    def test_hooks_wire_named_methods_when_given(self):
        out = mod.generate_code(_plan(), {"image_loader": "Game.Utils.ImageCache.LoadSpriteAsync",
                                          "price_resolver": "Game.Iap.Store.PriceFor"})
        hooks = out["files"]["Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs"]
        self.assertIn("LoadSpriteFromUrl = Game.Utils.ImageCache.LoadSpriteAsync;", hooks)
        self.assertIn("ResolveStorePrice = Game.Iap.Store.PriceFor;", hooks)
        self.assertIn("ResolveResourceIcon = null;", hooks)
        self.assertEqual(hooks.count("TODO(kinoa-prefab):"), 1)

    def test_item_view_uses_legacy_alias(self):
        item = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs"]
        self.assertIn("using KinoaText = UnityEngine.UI.Text;", item)
        self.assertIn("public void SetButton(bool interactable, UnityAction onClick)", item)
        self.assertIn("[SerializeField] private Image icon;", item)

    def test_item_view_uses_tmp_alias_when_probe_said_tmp(self):
        style = dict(STYLE, text_system="tmp", tmp_font_guid="cccccccccccccccccccccccccccccccc")
        item = mod.generate_code(_plan(style=style), {})["files"]["Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs"]
        self.assertIn("using KinoaText = TMPro.TMP_Text;", item)

    def test_builder_contract(self):
        builder = self.files["Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs"]
        self.assertIn('public const string MenuPath = "Tools/Kinoa/In-Apps/Build Prefabs From Plans";', builder)
        self.assertIn("[MenuItem(MenuPath)]", builder)
        self.assertIn("public static string BuildAll()", builder)
        self.assertIn("public static BuildReport BuildFromPlan(string planPath)", builder)
        self.assertIn('".build-report.json"', builder)
        self.assertIn("PrefabUtility.SaveAsPrefabAsset", builder)
        self.assertIn("namespace Kinoa.InApps.Editor", builder)
        # every plan node key the builder deserialises must exist in the Python node shape
        node = mod._node("X", None, "text")
        for fld in re.findall(r"public (?:string|bool|float\[\]|string\[\]) (\w+);", builder.split("class PlanNode")[1].split("}")[0]):
            self.assertIn(fld, node, "builder reads PlanNode.%s which the planner never writes" % fld)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_codegen -v`
Expected: FAIL — `AttributeError: module has no attribute 'generate_code'`.

- [ ] **Step 3: Implement the shared templates and `generate_code` scaffold**

Append to `inapp_prefab_plan.py` (before the CLI section):

```python
# --------------------------------------------------------------------------- code generation

TODO = "TODO(kinoa-prefab):"
_AUTOGEN = "// <auto-generated>\n//     kinoa-inapp-template-to-prefab — %s\n// </auto-generated>\n"


def _text_alias(text_system):
    return "using KinoaText = %s;" % ("TMPro.TMP_Text" if text_system == "tmp" else "UnityEngine.UI.Text")


def _hook_line(cs_type, name, method, todo):
    if method:
        return "        public static %s %s = %s;\n" % (cs_type, name, method)
    return "        // %s %s\n        public static %s %s = null;\n" % (TODO, todo, cs_type, name)


def render_hooks(options):
    body = _AUTOGEN % "game-supplied delegates. Fill the TODO lines from YOUR game code; regenerated only with --force-shared."
    body += """using System;
using System.Threading.Tasks;
using Kinoa.Data.Messaging.InApp;
using UnityEngine;

namespace Kinoa.InApps
{
    /// <summary>
    ///     Delegates the generated in-app views call for anything the game already owns.
    ///     The Kinoa SDK ships no image downloader, no IAP price lookup and no resource-icon atlas —
    ///     those live in the game, so assign them here (e.g. from your bootstrap scene) instead of
    ///     re-implementing them.
    /// </summary>
    public static class KinoaInAppHooks
    {
        /// <summary>Downloads a remote image (InAppImageContentType.WebUrl) into a Sprite.</summary>
"""
    body += _hook_line("Func<string, Task<Sprite>>", "LoadSpriteFromUrl", options.get("image_loader"),
                       "assign your game's existing image loader, e.g. KinoaInAppHooks.LoadSpriteFromUrl = ImageCache.LoadSpriteAsync; (do not write a new downloader here)")
    body += """
        /// <summary>
        ///     Localized store price for a button's packages. The bool is <c>usePreSalePackage</c>:
        ///     <c>true</c> reads the *DiscountPackageID pair (the pre-sale price the client shows struck through),
        ///     <c>false</c> the regular package (the CTA price).
        /// </summary>
"""
    body += _hook_line("Func<InAppStorePackages, bool, string>", "ResolveStorePrice", options.get("price_resolver"),
                       "assign your IAP layer's localized price lookup, e.g. (packages, preSale) => Store.LocalizedPrice(preSale ? packages.IosDiscountPackageID : packages.IosPackageID);")
    body += """
        /// <summary>Icon for a granted resource, by its Kinoa resourceKey.</summary>
"""
    body += _hook_line("Func<string, Sprite>", "ResolveResourceIcon", options.get("resource_icon_resolver"),
                       "assign your resource-icon lookup, e.g. KinoaInAppHooks.ResolveResourceIcon = ResourceIcons.Get;")
    body += """
        internal static void WarnMissing(string hook) =>
            Debug.LogWarning($"[KinoaInApp] {hook} is not assigned — see TODO(kinoa-prefab) in KinoaInAppHooks.cs");
    }
}
"""
    return body


def render_item_view(text_system):
    return (_AUTOGEN % "shared list-row view (resource items, milestone markers, mission rows). Regenerated only with --force-shared.") + """using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
""" + _text_alias(text_system) + """

namespace Kinoa.InApps
{
    public class KinoaInAppItemView : MonoBehaviour
    {
        [SerializeField] private Image icon;
        [SerializeField] private KinoaText label;
        [SerializeField] private KinoaText value;
        [SerializeField] private Image fill;
        [SerializeField] private Button button;

        public Image Icon => icon;
        public Button Button => button;

        public void SetLabel(string text)
        {
            if (label != null) label.text = text ?? string.Empty;
        }

        public void SetValue(string text)
        {
            if (value == null) return;
            value.text = text ?? string.Empty;
            value.gameObject.SetActive(!string.IsNullOrEmpty(text));
        }

        public void SetIcon(Sprite sprite)
        {
            if (icon == null) return;
            icon.sprite = sprite;
            icon.enabled = sprite != null;
        }

        public void SetFill(float amount)
        {
            if (fill != null) fill.fillAmount = Mathf.Clamp01(amount);
        }

        public void SetButton(bool interactable, UnityAction onClick)
        {
            if (button == null) return;
            button.onClick.RemoveAllListeners();
            button.interactable = interactable;
            if (onClick != null) button.onClick.AddListener(onClick);
        }
    }
}
"""


BUILDER_CS = (_AUTOGEN % "generic plan -> prefab builder (Editor only). Regenerated only with --force-shared.") + r"""using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

namespace Kinoa.InApps.Editor
{
    /// <summary>
    ///     Materialises every <c>*.inapp-plan.json</c> under Assets into a uGUI prefab and wires the
    ///     generated view's serialized fields. Plans are produced by the kinoa-inapp-template-to-prefab
    ///     skill; this class never talks to Kinoa and never needs credentials.
    /// </summary>
    public static class KinoaInAppPrefabBuilder
    {
        public const string MenuPath = "Tools/Kinoa/In-Apps/Build Prefabs From Plans";
        private const string PlanSuffix = ".inapp-plan.json";

        [Serializable] public class Plan { public string schema_version; public PlanTemplate template; public PlanUi ui; public PlanView view; public PlanPaths paths; public PlanNode[] nodes; }
        [Serializable] public class PlanTemplate { public string id; public string key; public string name; public string feature_type; }
        [Serializable] public class PlanUi { public string text_system; public string font_guid; public string tmp_font_guid; public float[] frame_size; public string close_sprite_guid; public float dimmer_alpha; }
        [Serializable] public class PlanView { public string class_name; public string ns; }
        [Serializable] public class PlanPaths { public string out_dir; public string prefab_path; public string view_path; public string plan_path; }
        [Serializable] public class PlanNode
        {
            public string name; public string parent; public string binding; public string[] components;
            public string field; public string field_type; public float[] anchor_min; public float[] anchor_max; public float[] size;
            public bool placed; public bool can_be_hidden; public bool inactive; public string key; public string bucket; public string sprite_guid;
        }
        [Serializable] public class BuildReport
        {
            public bool ok; public string plan_path; public string prefab_path; public string view_class;
            public int nodes_built; public int fields_assigned;
            public List<string> fields_missing = new List<string>();
            public List<string> errors = new List<string>();
        }

        [MenuItem(MenuPath)]
        public static void BuildAllMenu() => Debug.Log(BuildAll());

        /// <summary>Builds every plan. Per-plan reports land beside each plan as <c>&lt;key&gt;.build-report.json</c>.</summary>
        public static string BuildAll()
        {
            var plans = AssetDatabase.FindAssets("t:TextAsset")
                .Select(AssetDatabase.GUIDToAssetPath)
                .Where(p => p.EndsWith(PlanSuffix, StringComparison.OrdinalIgnoreCase))
                .Distinct().OrderBy(p => p).ToList();
            var ok = 0;
            foreach (var plan in plans) if (BuildFromPlan(plan).ok) ok++;
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            var summary = $"[KinoaInAppPrefabBuilder] {ok}/{plans.Count} plan(s) built";
            Debug.Log(summary);
            return summary;
        }

        public static BuildReport BuildFromPlan(string planPath)
        {
            var report = new BuildReport { plan_path = planPath };
            GameObject root = null;
            try
            {
                var plan = JsonUtility.FromJson<Plan>(File.ReadAllText(planPath));
                if (plan == null || plan.nodes == null || plan.paths == null || plan.view == null)
                    throw new InvalidOperationException("plan unreadable or incomplete");
                report.prefab_path = plan.paths.prefab_path;
                report.view_class = plan.view.class_name;

                root = new GameObject(Path.GetFileNameWithoutExtension(plan.paths.prefab_path), typeof(RectTransform));
                Stretch(root.GetComponent<RectTransform>());
                var byName = new Dictionary<string, GameObject> { { "", root } };
                foreach (var node in plan.nodes)
                {
                    var parentName = node.parent ?? "";
                    if (!byName.TryGetValue(parentName, out var parent))
                    {
                        report.errors.Add($"node {node.name}: parent '{parentName}' was not built before it");
                        continue;
                    }
                    var go = new GameObject(node.name, typeof(RectTransform));
                    var rt = go.GetComponent<RectTransform>();
                    rt.SetParent(parent.transform, false);
                    ApplyRect(rt, node);
                    foreach (var component in node.components ?? Array.Empty<string>()) AddComponent(go, component, plan.ui);
                    ApplyBinding(go, node, plan.ui);
                    if (node.inactive) go.SetActive(false);
                    byName[node.name] = go;
                    report.nodes_built++;
                }

                var viewType = FindType(plan.view.class_name, plan.view.ns);
                if (viewType == null)
                {
                    report.errors.Add($"view class {plan.view.ns}.{plan.view.class_name} not found — did the scripts compile?");
                }
                else
                {
                    var view = root.AddComponent(viewType);
                    var so = new SerializedObject(view);
                    foreach (var node in plan.nodes.Where(n => !string.IsNullOrEmpty(n.field)))
                    {
                        if (!byName.TryGetValue(node.name, out var go)) continue;
                        var prop = so.FindProperty(node.field);
                        if (prop == null) { report.fields_missing.Add(node.field); continue; }
                        prop.objectReferenceValue = Resolve(go, node.field_type, plan.ui);
                        report.fields_assigned++;
                    }
                    so.ApplyModifiedPropertiesWithoutUndo();
                }

                Directory.CreateDirectory(Path.GetDirectoryName(plan.paths.prefab_path));
                PrefabUtility.SaveAsPrefabAsset(root, plan.paths.prefab_path, out var saved);
                if (!saved) report.errors.Add("PrefabUtility.SaveAsPrefabAsset reported failure");
                report.ok = saved && report.errors.Count == 0;
            }
            catch (Exception e)
            {
                report.errors.Add(e.ToString());
                report.ok = false;
            }
            finally
            {
                if (root != null) UnityEngine.Object.DestroyImmediate(root);
            }

            var reportPath = planPath.Substring(0, planPath.Length - PlanSuffix.Length) + ".build-report.json";
            File.WriteAllText(reportPath, JsonUtility.ToJson(report, true));
            Debug.Log($"[KinoaInAppPrefabBuilder] {(report.ok ? "OK" : "FAILED")} {planPath} -> {report.prefab_path} " +
                      $"(nodes {report.nodes_built}, fields {report.fields_assigned}, missing {report.fields_missing.Count}, errors {report.errors.Count})");
            return report;
        }

        // ------------------------------------------------------------------ helpers

        private static Type TmpType => Type.GetType("TMPro.TextMeshProUGUI, Unity.TextMeshPro");
        private static bool UseTmp(PlanUi ui) => ui != null && ui.text_system == "tmp" && TmpType != null;

        private static void Stretch(RectTransform rt)
        {
            rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one;
            rt.offsetMin = Vector2.zero; rt.offsetMax = Vector2.zero;
        }

        private static void ApplyRect(RectTransform rt, PlanNode node)
        {
            if (node.size != null && node.size.Length == 2)
            {
                rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
                rt.sizeDelta = new Vector2(node.size[0], node.size[1]);
                rt.anchoredPosition = Vector2.zero;
                return;
            }
            if (node.anchor_min != null && node.anchor_min.Length == 2 && node.anchor_max != null && node.anchor_max.Length == 2)
            {
                rt.anchorMin = new Vector2(node.anchor_min[0], node.anchor_min[1]);
                rt.anchorMax = new Vector2(node.anchor_max[0], node.anchor_max[1]);
                rt.offsetMin = Vector2.zero; rt.offsetMax = Vector2.zero;
                return;
            }
            Stretch(rt);
        }

        private static void AddComponent(GameObject go, string component, PlanUi ui)
        {
            switch (component)
            {
                case "Image":
                    if (go.GetComponent<Image>() == null) go.AddComponent<Image>().color = Color.white;
                    break;
                case "Button":
                {
                    var image = go.GetComponent<Image>() ?? go.AddComponent<Image>();
                    go.AddComponent<Button>().targetGraphic = image;
                    break;
                }
                case "Text":
                    AddText(go, ui);
                    break;
                case "HorizontalLayoutGroup":
                {
                    var g = go.AddComponent<HorizontalLayoutGroup>();
                    g.spacing = 8f; g.childAlignment = TextAnchor.MiddleCenter;
                    g.childControlWidth = false; g.childControlHeight = false;
                    g.childForceExpandWidth = false; g.childForceExpandHeight = false;
                    break;
                }
                case "VerticalLayoutGroup":
                {
                    var g = go.AddComponent<VerticalLayoutGroup>();
                    g.spacing = 8f; g.childAlignment = TextAnchor.UpperCenter;
                    g.childControlWidth = true; g.childControlHeight = false;
                    g.childForceExpandWidth = true; g.childForceExpandHeight = false;
                    break;
                }
                default:
                    Debug.LogWarning($"[KinoaInAppPrefabBuilder] unknown component '{component}' on {go.name}");
                    break;
            }
        }

        private static Component AddText(GameObject go, PlanUi ui)
        {
            if (UseTmp(ui))
            {
                var tmp = go.AddComponent(TmpType);
                var so = new SerializedObject(tmp);
                var fontAsset = LoadByGuid<UnityEngine.Object>(ui.tmp_font_guid);
                if (fontAsset != null) SetRef(so, "m_fontAsset", fontAsset);
                SetBool(so, "m_enableAutoSizing", true);
                SetFloat(so, "m_fontSizeMin", 10f);
                SetFloat(so, "m_fontSizeMax", 120f);
                SetInt(so, "m_HorizontalAlignment", 2);   // HorizontalAlignmentOptions.Center
                SetInt(so, "m_VerticalAlignment", 512);   // VerticalAlignmentOptions.Middle
                so.ApplyModifiedPropertiesWithoutUndo();
                return tmp;
            }
            var text = go.AddComponent<Text>();
            text.font = LoadByGuid<Font>(ui?.font_guid) ?? BuiltinFont();
            text.alignment = TextAnchor.MiddleCenter;
            text.resizeTextForBestFit = true; text.resizeTextMinSize = 10; text.resizeTextMaxSize = 120;
            text.color = Color.white; text.supportRichText = true;
            text.horizontalOverflow = HorizontalWrapMode.Wrap; text.verticalOverflow = VerticalWrapMode.Truncate;
            return text;
        }

        private static Font BuiltinFont()
        {
            try { return Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf"); }
            catch (Exception) { return Resources.GetBuiltinResource<Font>("Arial.ttf"); }
        }

        private static void ApplyBinding(GameObject go, PlanNode node, PlanUi ui)
        {
            switch (node.binding)
            {
                case "dimmer":
                    go.GetComponent<Image>().color = new Color(0f, 0f, 0f, ui != null && ui.dimmer_alpha > 0f ? ui.dimmer_alpha : 0.6f);
                    break;
                case "strike":
                {
                    var image = go.GetComponent<Image>();
                    image.color = Color.white; image.raycastTarget = false;
                    break;
                }
                case "fill":
                {
                    var image = go.GetComponent<Image>();
                    image.type = Image.Type.Filled; image.fillMethod = Image.FillMethod.Horizontal;
                    image.fillAmount = 0f; image.raycastTarget = false;
                    break;
                }
                case "item_template":
                    BuildItemTemplate(go, ui);
                    break;
                case "text":
                case "button_label":
                {
                    var graphic = go.GetComponent<Graphic>();
                    if (graphic != null) graphic.raycastTarget = false;
                    break;
                }
            }
            if (!string.IsNullOrEmpty(node.sprite_guid))
            {
                var image = go.GetComponent<Image>();
                var sprite = LoadByGuid<Sprite>(node.sprite_guid);
                if (image != null && sprite != null) image.sprite = sprite;
            }
            if (node.parent == "Unplaced") go.AddComponent<LayoutElement>().preferredHeight = 80f;
        }

        private static void BuildItemTemplate(GameObject go, PlanUi ui)
        {
            var background = go.GetComponent<Image>() ?? go.AddComponent<Image>();
            background.color = new Color(1f, 1f, 1f, 0.15f);
            var button = go.AddComponent<Button>();
            button.targetGraphic = background;

            var icon = Child(go, "Icon", new Vector2(0.05f, 0.35f), new Vector2(0.35f, 0.95f)).AddComponent<Image>();
            icon.preserveAspect = true; icon.raycastTarget = false;
            var label = AddText(Child(go, "Label", new Vector2(0.4f, 0.5f), new Vector2(0.95f, 0.95f)), ui);
            var value = AddText(Child(go, "Value", new Vector2(0.4f, 0.1f), new Vector2(0.95f, 0.5f)), ui);
            var fill = Child(go, "Fill", new Vector2(0.05f, 0.02f), new Vector2(0.95f, 0.1f)).AddComponent<Image>();
            fill.type = Image.Type.Filled; fill.fillMethod = Image.FillMethod.Horizontal; fill.fillAmount = 0f; fill.raycastTarget = false;
            foreach (var c in new[] { label, value }) { var g = c.GetComponent<Graphic>(); if (g != null) g.raycastTarget = false; }

            var item = go.AddComponent<KinoaInAppItemView>();
            var so = new SerializedObject(item);
            SetRef(so, "icon", icon); SetRef(so, "label", label); SetRef(so, "value", value);
            SetRef(so, "fill", fill); SetRef(so, "button", button);
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static GameObject Child(GameObject parent, string name, Vector2 anchorMin, Vector2 anchorMax)
        {
            var go = new GameObject(name, typeof(RectTransform));
            var rt = go.GetComponent<RectTransform>();
            rt.SetParent(parent.transform, false);
            rt.anchorMin = anchorMin; rt.anchorMax = anchorMax;
            rt.offsetMin = Vector2.zero; rt.offsetMax = Vector2.zero;
            return go;
        }

        private static UnityEngine.Object Resolve(GameObject go, string fieldType, PlanUi ui)
        {
            switch (fieldType)
            {
                case "GameObject": return go;
                case "RectTransform": return go.GetComponent<RectTransform>();
                case "Image": return go.GetComponent<Image>();
                case "Button": return go.GetComponent<Button>();
                case "Text": return UseTmp(ui) ? go.GetComponent(TmpType) : (Component)go.GetComponent<Text>();
                case "KinoaInAppItemView": return go.GetComponent<KinoaInAppItemView>();
                default: return go;
            }
        }

        private static Type FindType(string className, string ns)
        {
            var full = string.IsNullOrEmpty(ns) ? className : ns + "." + className;
            var types = TypeCache.GetTypesDerivedFrom<MonoBehaviour>();
            return types.FirstOrDefault(t => t.FullName == full) ?? types.FirstOrDefault(t => t.Name == className);
        }

        private static T LoadByGuid<T>(string guid) where T : UnityEngine.Object
        {
            if (string.IsNullOrEmpty(guid)) return null;
            var path = AssetDatabase.GUIDToAssetPath(guid);
            return string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<T>(path);
        }

        private static void SetRef(SerializedObject so, string name, UnityEngine.Object value) { var p = so.FindProperty(name); if (p != null) p.objectReferenceValue = value; }
        private static void SetBool(SerializedObject so, string name, bool value) { var p = so.FindProperty(name); if (p != null) p.boolValue = value; }
        private static void SetFloat(SerializedObject so, string name, float value) { var p = so.FindProperty(name); if (p != null) p.floatValue = value; }
        private static void SetInt(SerializedObject so, string name, int value) { var p = so.FindProperty(name); if (p != null) p.intValue = value; }
    }
}
"""


def generate_code(plan, options=None):
    options = options or {}
    out_dir = plan["paths"]["out_dir"].rstrip("/")
    text_system = plan["ui"]["text_system"]
    files = {
        "%s/Shared/KinoaInAppHooks.cs" % out_dir: render_hooks(options),
        "%s/Shared/KinoaInAppItemView.cs" % out_dir: render_item_view(text_system),
        "%s/Editor/KinoaInAppPrefabBuilder.cs" % out_dir: BUILDER_CS,
    }
    files[plan["paths"]["view_path"]] = render_view(plan, options)
    files[plan["paths"]["plan_path"]] = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    return {"files": files, "snippets": render_snippets(plan, options), "report": {"text_system": text_system}}


def render_view(plan, options):
    """Task 6 fills this in."""
    return ""


def render_snippets(plan, options):
    """Task 8 fills this in."""
    return {}
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_inapp_prefab_codegen -v`
Expected: all `TestSharedFiles` tests PASS (the view file is an empty string for now, which has no forbidden strings).

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_codegen.py
git commit -m "feat(inapp-prefab): generate shared hooks, item view and the Editor prefab builder"
```

---

### Task 6: Code generation — the per-template view (fields, Bind, texts/images/buttons/customs, Show/Close, click routing)

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (replace the `render_view` stub)
- Test: `tests/test_inapp_prefab_codegen.py` (append `TestViewStandard`)

**Interfaces:**
- Consumes: plan nodes/fields from Tasks 3–4; `KinoaInAppHooks`, `KinoaInAppItemView` from Task 5.
- Produces the generated class `Kinoa.InApps.KinoaInApp<Pascal>View : MonoBehaviour` with public API: `const string TemplateKey`, `InAppMessage Message {get;}`, `InAppCustomTemplateData Data {get;}`, `event Action<View> Closed`, `event Action<View, string, InAppClickConfiguration> ButtonClicked`, `bool Bind(InAppMessage)`, `void Show()`, `void Close()`, `bool TryGetCustom<T>(string key, out T value)`, `T GetCustom<T>(string key)`.
- Options: `facade` (`"present"` ⇒ clicks delegate to `KinoaUiService.Instance.HandleInAppButtonClickAsync(Message, key)`; anything else ⇒ event + TODO), `facade_namespace` (default `Core.Services`).

- [ ] **Step 1: Append the failing tests**

```python
class TestViewStandard(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()
        self.view = mod.generate_code(self.plan, {})["files"][self.plan["paths"]["view_path"]]

    def test_header_and_identity(self):
        self.assertTrue(self.view.startswith("// <auto-generated>"))
        self.assertIn("namespace Kinoa.InApps", self.view)
        self.assertIn("public class KinoaInAppOneCtaOfferView : MonoBehaviour", self.view)
        self.assertIn('public const string TemplateKey = "one_cta_offer";', self.view)
        self.assertIn("using KinoaText = UnityEngine.UI.Text;", self.view)
        for bad in FORBIDDEN:
            self.assertNotIn(bad, self.view)

    def test_serialized_fields_match_plan(self):
        for node in self.plan["nodes"]:
            if node["field"]:
                cs_type = {"Text": "KinoaText"}.get(node["field_type"], node["field_type"])
                self.assertIn("[SerializeField] private %s %s;" % (cs_type, node["field"]), self.view,
                              "field %s missing" % node["field"])

    def test_bind_covers_every_slot(self):
        self.assertIn('ApplyText(headerText, "header", canBeHidden: true);', self.view)
        self.assertIn('ApplyText(finePrintText, "fine_print", canBeHidden: true);', self.view)
        self.assertIn('ApplyImage(backgroundImage, "background_image", canBeHidden: true);', self.view)
        self.assertIn('ApplyButton(ctaButton, ctaButtonLabel, "cta_button", canBeHidden: false);', self.view)
        self.assertIn('ApplyButton(closeButton, closeButtonLabel, "close_button", canBeHidden: true);', self.view)
        self.assertIn('ApplyToggle("show_resource_area", resourceAreaRoot);', self.view)
        self.assertIn("if (data == null || data.TemplateKey != TemplateKey)", self.view)

    def test_lifecycle_events(self):
        self.assertIn("Kinoa.GameEvents.SendInAppImpressionEvent(new InAppImpressionEventData(Message));", self.view)
        self.assertIn("Kinoa.GameEvents.SendInAppCloseEvent(new InAppCloseEventData(Message));", self.view)
        self.assertIn("Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));", self.view)
        self.assertIn("public event Action<KinoaInAppOneCtaOfferView> Closed;", self.view)

    def test_click_routing_without_facade_leaves_todo(self):
        self.assertIn("if (slot.ClickConfig is InAppCloseClickConfiguration)", self.view)
        self.assertIn("ButtonClicked?.Invoke(this, key, slot.ClickConfig);", self.view)
        self.assertIn("%s route slot.ClickConfig" % mod.TODO, self.view)
        self.assertNotIn("KinoaUiService", self.view)

    def test_click_routing_with_facade(self):
        view = mod.generate_code(self.plan, {"facade": "present", "facade_namespace": "Core.Services"})["files"][self.plan["paths"]["view_path"]]
        self.assertIn("using Core.Services;", view)
        self.assertIn("_ = KinoaUiService.Instance.HandleInAppButtonClickAsync(Message, key);", view)
        self.assertNotIn("%s route slot.ClickConfig" % mod.TODO, view)

    def test_image_loading_goes_through_hooks_only(self):
        self.assertIn("case InAppImageContentType.WebUrl:", self.view)
        self.assertIn("KinoaInAppHooks.LoadSpriteFromUrl == null", self.view)
        self.assertIn("case InAppImageContentType.LocalPath:", self.view)
        self.assertIn("Resources.Load<Sprite>(image.Content)", self.view)
        self.assertIn("%s load the addressable sprite" % mod.TODO, self.view)

    def test_text_color_custom_field(self):
        self.assertIn('TryGetColor(slot.CustomFields, "text_color", out var color)', self.view)
        self.assertIn("ColorUtility.TryParseHtmlString", self.view)

    def test_tmp_alias(self):
        style = dict(STYLE, text_system="tmp", tmp_font_guid="cccccccccccccccccccccccccccccccc")
        plan = _plan(style=style)
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("using KinoaText = TMPro.TMP_Text;", view)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_codegen.TestViewStandard -v`
Expected: FAIL — the view file is empty.

- [ ] **Step 3: Implement `render_view`**

Replace the stub with:

```python
_CS_FIELD_TYPE = {"Text": "KinoaText"}


def _cs_type(field_type):
    return _CS_FIELD_TYPE.get(field_type, field_type)


def _fields_block(plan):
    groups = [("Frame", ("dimmer", "panel")), ("Images", ("image",)), ("Texts", ("text",)),
              ("Buttons", ("button", "button_label")), ("Client-rendered zones", ("zone", "strike", "item_template", "fill", "markers"))]
    emitted, lines = set(), []
    for header, bindings in groups:
        block = []
        for node in plan["nodes"]:
            if node["field"] and node["binding"] in bindings and node["field"] not in emitted:
                emitted.add(node["field"])
                block.append("        [SerializeField] private %s %s;" % (_cs_type(node["field_type"]), node["field"]))
        if block:
            lines.append('        [Header("%s")]' % header)
            lines.extend(block)
            lines.append("")
    for node in plan["nodes"]:  # anything with a field not covered by the groups above
        if node["field"] and node["field"] not in emitted:
            emitted.add(node["field"])
            lines.append("        [SerializeField] private %s %s;" % (_cs_type(node["field_type"]), node["field"]))
    return "\n".join(lines).rstrip() + "\n"


def _bind_calls(plan):
    t = plan["template"]
    by_key = {(n["bucket"], n["key"]): n for n in plan["nodes"] if n.get("key") and n["binding"] in ("image", "text", "button")}
    texts = ['            ApplyText(%s, "%s", canBeHidden: %s);' % (by_key[("texts", s["key"])]["field"], s["key"], "true" if s["can_be_hidden"] else "false")
             for s in t["texts"] if ("texts", s["key"]) in by_key]
    images = ['            ApplyImage(%s, "%s", canBeHidden: %s);' % (by_key[("images", s["key"])]["field"], s["key"], "true" if s["can_be_hidden"] else "false")
              for s in t["images"] if ("images", s["key"]) in by_key]
    buttons = ['            ApplyButton(%s, %sLabel, "%s", canBeHidden: %s);' % (by_key[("buttons", s["key"])]["field"], by_key[("buttons", s["key"])]["field"], s["key"], "true" if s["can_be_hidden"] else "false")
               for s in t["buttons"] if ("buttons", s["key"]) in by_key]
    toggles = ['            ApplyToggle("%s", %s);' % (c["key"], c["target_field"]) for c in plan["customs"] if c.get("target_field")]
    return "\n".join(texts), "\n".join(images), "\n".join(buttons), "\n".join(toggles)


def render_view(plan, options):
    options = options or {}
    cls = plan["view"]["class_name"]
    key = plan["template"]["key"]
    ftype = plan["template"]["feature_type"]
    facade = options.get("facade") == "present"
    facade_ns = options.get("facade_namespace") or "Core.Services"
    node_names = {n["name"] for n in plan["nodes"]}
    has = lambda name: name in node_names  # noqa: E731

    usings = ["using System;", "using System.Collections.Generic;", "using System.Threading.Tasks;",
              "using Kinoa.Data.Enum;", "using Kinoa.Data.Events;", "using Kinoa.Data.Messaging.InApp;",
              "using Kinoa.Data.Messaging.InApp.Templates.Custom;", "using Kinoa.Data.ResourceManagement;"]
    if ftype == "milestone":
        usings += ["using Kinoa.Data.Messaging.InApp.Features;", "using Kinoa.Data.Messaging.InApp.Features.Milestones;"]
    if ftype == "mission":
        usings += ["using Kinoa.Data.Messaging.InApp.Features.Missions;"]
    if facade:
        usings.append("using %s;" % facade_ns)
    usings += ["using UnityEngine;", "using UnityEngine.UI;", _text_alias(plan["ui"]["text_system"])]

    texts, images, buttons, toggles = _bind_calls(plan)
    zone_calls = []
    if has("TimerZone"):
        zone_calls.append("            BindTimer();")
    if has("PriceBeforeSaleZone"):
        zone_calls.append("            BindPriceBeforeSale();")
    if has("ResourceArea"):
        zone_calls.append("            BindResourceArea();")
    feature_call = "            BindFeature();" if ftype in ("milestone", "mission") else ""

    if facade:
        route = ("            _ = KinoaUiService.Instance.HandleInAppButtonClickAsync(Message, key);")
    else:
        route = ("            // %s route slot.ClickConfig (billing / show_ad / collect_resource / deep_link / web_link / soft_billing / custom)\n"
                 "            //   through your game's click handler, then call Kinoa.Messaging.UseInboxMessageEligibilityAsync(Message) once the action is consumed.\n"
                 "            Debug.LogWarning($\"[{GetType().Name}] click on '{key}' ({slot.ClickConfig?.GetType().Name}) is not routed — see TODO(kinoa-prefab)\");") % TODO

    head = _AUTOGEN % ("view for in-app template '%s' (id %s). Regenerate with the skill rather than hand-editing bound fields." % (key, plan["template"].get("id")))
    body = head + "\n".join(usings) + "\n\nnamespace %s\n{\n" % plan["view"]["ns"]
    body += "    /// <summary>Binds an InAppMessage of template '%s' to the prefab %s and routes its buttons.</summary>\n" % (key, plan["paths"]["prefab_path"])
    body += "    public class %s : MonoBehaviour\n    {\n" % cls
    body += '        public const string TemplateKey = "%s";\n\n' % key
    body += _fields_block(plan)
    body += """
        public InAppMessage Message { get; private set; }
        public InAppCustomTemplateData Data { get; private set; }

        /// <summary>Raised right before the view destroys itself.</summary>
        public event Action<%(cls)s> Closed;
        /// <summary>Raised on every button click, before routing — for analytics or custom handling.</summary>
        public event Action<%(cls)s, string, InAppClickConfiguration> ButtonClicked;

        private readonly List<GameObject> _spawned = new List<GameObject>();
        private bool _impressionSent;
        private bool _timerActive;

        // ------------------------------------------------------------------ public API

        /// <summary>Fills every slot from the message. Returns false (and logs) when the message is not this template.</summary>
        public bool Bind(InAppMessage message)
        {
            if (message == null)
            {
                Debug.LogError($"[{nameof(%(cls)s)}] Bind called with a null message");
                return false;
            }
            var data = message.Data as InAppCustomTemplateData;
            if (data == null || data.TemplateKey != TemplateKey)
            {
                Debug.LogError($"[{nameof(%(cls)s)}] expected template '{TemplateKey}', got '{data?.TemplateKey ?? message.Data?.GetType().Name}'");
                return false;
            }
            Message = message;
            Data = data;
            ClearSpawned();
            BindTexts();
            BindImages();
            BindButtons();
            BindClientZones();
%(feature_call)s
            BindCustoms();
            return true;
        }

        /// <summary>Activates the view and sends the in_app_impression event once.</summary>
        public void Show()
        {
            gameObject.SetActive(true);
            if (_impressionSent || Message == null) return;
            _impressionSent = true;
            Kinoa.GameEvents.SendInAppImpressionEvent(new InAppImpressionEventData(Message));
        }

        /// <summary>Sends in_app_close, raises Closed and destroys the view.</summary>
        public void Close()
        {
            if (Message != null) Kinoa.GameEvents.SendInAppCloseEvent(new InAppCloseEventData(Message));
            Closed?.Invoke(this);
            Destroy(gameObject);
        }

        public bool TryGetCustom<T>(string key, out T value)
        {
            value = default;
            if (Data?.Customs == null || !Data.Customs.TryGetValue(key, out var custom) || custom?.Value == null) return false;
            if (custom.Value is T typed) { value = typed; return true; }
            try { value = (T)Convert.ChangeType(custom.Value, typeof(T)); return true; }
            catch (Exception) { return false; }
        }

        public T GetCustom<T>(string key) => TryGetCustom<T>(key, out var value) ? value : default;

        // ------------------------------------------------------------------ slots

        private void BindTexts()
        {
%(texts)s
        }

        private void BindImages()
        {
%(images)s
        }

        private void BindButtons()
        {
%(buttons)s
        }

        private void BindCustoms()
        {
%(toggles)s
        }

        private void BindClientZones()
        {
%(zones)s
        }

        private void ApplyText(KinoaText target, string key, bool canBeHidden)
        {
            if (target == null) return;
            InAppCustomText slot = null;
            Data.Texts?.TryGetValue(key, out slot);
            if (slot == null || string.IsNullOrEmpty(slot.Content))
            {
                if (canBeHidden) target.gameObject.SetActive(false);
                else target.text = string.Empty;
                return;
            }
            target.gameObject.SetActive(true);
            target.text = slot.Content.Replace("<br>", "\\n");
            if (TryGetColor(slot.CustomFields, "text_color", out var color)) target.color = color;
        }

        private static bool TryGetColor(Dictionary<string, object> fields, string key, out Color color)
        {
            color = Color.white;
            return fields != null && fields.TryGetValue(key, out var raw) && raw is string hex
                   && ColorUtility.TryParseHtmlString(hex, out color);
        }

        private void ApplyImage(Image target, string key, bool canBeHidden)
        {
            InAppCustomImage slot = null;
            Data.Images?.TryGetValue(key, out slot);
            ApplyImageContent(target, slot, canBeHidden);
        }

        private void ApplyImageContent(Image target, InAppImage image, bool canBeHidden)
        {
            if (target == null) return;
            if (image == null || string.IsNullOrEmpty(image.Content))
            {
                if (canBeHidden) target.gameObject.SetActive(false);
                return;
            }
            target.gameObject.SetActive(true);
            switch (image.ContentType)
            {
                case InAppImageContentType.LocalPath:
                    target.sprite = Resources.Load<Sprite>(image.Content);
                    break;
                case InAppImageContentType.WebUrl:
                    _ = LoadRemoteSpriteAsync(target, image.Content);
                    break;
                case InAppImageContentType.Addressable:
                    // %(todo)s load the addressable sprite with the game's own Addressables wrapper and assign target.sprite.
                    Debug.LogWarning($"[{GetType().Name}] addressable image '{image.Content}' not loaded — see TODO(kinoa-prefab)");
                    break;
                default:
                    break;
            }
        }

        private async Task LoadRemoteSpriteAsync(Image target, string url)
        {
            if (KinoaInAppHooks.LoadSpriteFromUrl == null)
            {
                KinoaInAppHooks.WarnMissing(nameof(KinoaInAppHooks.LoadSpriteFromUrl));
                return;
            }
            Sprite sprite;
            try { sprite = await KinoaInAppHooks.LoadSpriteFromUrl(url); }
            catch (Exception e)
            {
                Debug.LogWarning($"[{GetType().Name}] image load failed for {url}: {e.Message}");
                return;
            }
            if (this == null || target == null || sprite == null) return;
            target.sprite = sprite;
        }

        private void ApplyButton(Button button, KinoaText label, string key, bool canBeHidden)
        {
            InAppCustomButton slot = null;
            Data.Buttons?.TryGetValue(key, out slot);
            ApplyButtonSlot(button, label, key, slot, canBeHidden);
        }

        private void ApplyButtonSlot(Button button, KinoaText label, string key, InAppCustomButton slot, bool canBeHidden)
        {
            if (button == null) return;
            if (slot == null)
            {
                if (canBeHidden) button.gameObject.SetActive(false);
                return;
            }
            button.gameObject.SetActive(true);
            if (label != null) label.text = ResolveButtonLabel(slot);
            if (slot.BackgroundImage != null && !string.IsNullOrEmpty(slot.BackgroundImage.Content))
                ApplyImageContent(button.GetComponent<Image>(), slot.BackgroundImage, canBeHidden: false);
            button.onClick.RemoveAllListeners();
            button.onClick.AddListener(() => OnButtonClicked(key, slot));
        }

        private static string ResolveButtonLabel(InAppCustomButton slot)
        {
            if (!string.IsNullOrEmpty(slot.Label)) return slot.Label.Replace("<br>", "\\n");
            if (slot.ClickConfig is InAppBillingClickConfiguration && slot.Packages != null)
            {
                if (KinoaInAppHooks.ResolveStorePrice != null) return KinoaInAppHooks.ResolveStorePrice(slot.Packages, false) ?? string.Empty;
                KinoaInAppHooks.WarnMissing(nameof(KinoaInAppHooks.ResolveStorePrice));
            }
            return string.Empty;
        }

        private void OnButtonClicked(string key, InAppCustomButton slot)
        {
            Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));
            ButtonClicked?.Invoke(this, key, slot.ClickConfig);
            if (slot.ClickConfig is InAppCloseClickConfiguration)
            {
                Close();
                return;
            }
%(route)s
        }

        private void ApplyToggle(string customKey, GameObject target)
        {
            if (target == null) return;
            if (TryGetCustom<bool>(customKey, out var on)) target.SetActive(on);
        }

        private KinoaInAppItemView Spawn(KinoaInAppItemView template)
        {
            var item = Instantiate(template, template.transform.parent);
            item.gameObject.SetActive(true);
            _spawned.Add(item.gameObject);
            return item;
        }

        private void ClearSpawned()
        {
            foreach (var go in _spawned) if (go != null) Destroy(go);
            _spawned.Clear();
        }
""" % {"cls": cls, "texts": texts, "images": images, "buttons": buttons, "toggles": toggles,
       "zones": "\n".join(zone_calls), "feature_call": feature_call, "route": route, "todo": TODO}
    body += render_zone_methods(plan)
    body += render_feature_methods(plan)
    body += "    }\n}\n"
    return body


def render_zone_methods(plan):
    """Task 7 fills this in."""
    return ""


def render_feature_methods(plan):
    """Task 7 fills this in."""
    return ""
```

Two notes for the implementer: (1) the `%` formatting means every literal `%` inside the C# text must be written `%%` — there is none in this block, keep it that way (use `string.Format`-free C#); (2) `"\\n"` in the Python source yields `\n` in the C# source, which is what `Replace("<br>", "\n")` needs.

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_inapp_prefab_codegen -v`
Expected: `TestSharedFiles` + `TestViewStandard` PASS. (`test_serialized_fields_match_plan` will fail if any plan node with a field lacks a `[SerializeField]` — the fallback loop in `_fields_block` guarantees coverage; if it fails, a node's `field_type` is not in `{GameObject, RectTransform, Image, Button, Text, KinoaInAppItemView}`.)

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_codegen.py
git commit -m "feat(inapp-prefab): generate the per-template view — binding, lifecycle events, click routing"
```

---

### Task 7: Code generation — client-rendered zones and feature UIs in the view

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (replace `render_zone_methods`, `render_feature_methods`)
- Test: `tests/test_inapp_prefab_codegen.py` (append `TestViewZonesAndFeatures`)

**Interfaces:**
- Consumes the zone/feature fields from Task 4's table and SDK API: `InAppCountdownTimer.IsVisible/IsExpired/EndTimestamp`, `Kinoa.Time.GetUnixTime()`, `InAppStorePackages.AndroidDiscountPackageID/IosDiscountPackageID`, `InAppCustomButton.Resources` (`List<Resource>` with `Amount`, `ResourceKey`), `InAppMilestonesFeature.Progress/Steps/ActiveProgressButton`, `InAppMilestoneStep.Score/Status/Button`, `InAppMilestoneStatus.{Closed,Reached,Collected}`, `Kinoa.Messaging.CollectMilestonesAsync(InAppMessage, List<uint>)` → `Response<InAppMilestonesCollectResult>` (`IsSuccessful()`, `.Data.Collected`, `.Data.InApp`), `InAppMessage.SetMilestonesStatusAsCollected(IEnumerable<uint>)`, `InAppMissionsFeature.MissionState.ActiveSetProgress.{SetNumber, ActiveMissions}`, `InAppMission.{RowNumber, MissionText, CurrentScore, GoalScore, Status}`, `InAppMissionStatus.Reached`, `InAppMissionsProgress.ProgressBarState.{TotalScore, Milestones[].Score}`, `Kinoa.Messaging.CollectMissionsProgressAsync(message, int setNumber, List<int> rowNumbers)` → `Response<InAppMessage>`.

- [ ] **Step 1: Append the failing tests**

```python
def _milestone_plan():
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "chase"
    t["featureType"] = "milestone"
    t["features"] = {"milestone": {"key": "main_progressbar", "limit": 3, "mainActionTypes": ["close"]}}
    return _plan(template=t)


def _mission_plan():
    t = copy.deepcopy(TEMPLATE)
    t["key"] = "board"
    t["featureType"] = "mission"
    t["features"] = {"mission": {"progressBar": {"display": "show_for_all_sets_combined"}, "completionCta": ["collect_resource"]}}
    return _plan(template=t)


class TestViewZonesAndFeatures(unittest.TestCase):
    def test_timer_price_and_resources_on_standard(self):
        plan = _plan()
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("private void BindTimer()", view)
        self.assertIn("timer.IsVisible && !timer.IsExpired", view)
        self.assertIn("Message.CountdownTimer.EndTimestamp - Kinoa.Time.GetUnixTime()", view)
        self.assertIn('ToString(@"hh\\:mm\\:ss")', view)
        self.assertIn("private void BindPriceBeforeSale()", view)
        self.assertIn("packages.AndroidDiscountPackageID", view)
        self.assertIn("KinoaInAppHooks.ResolveStorePrice(packages, true)", view)
        self.assertIn("private void BindResourceArea()", view)
        self.assertIn("item.SetLabel(resource.Amount.ToString());", view)
        self.assertIn("KinoaInAppHooks.ResolveResourceIcon", view)
        self.assertNotIn("BindFeature", view)
        self.assertNotIn("Kinoa.Data.Messaging.InApp.Features", view)

    def test_price_zone_absent_when_no_billing(self):
        t = copy.deepcopy(TEMPLATE)
        t["buttons"][1]["clickActionType"] = ["close", "deep_link"]
        plan = _plan(template=t)
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertNotIn("BindPriceBeforeSale", view)
        self.assertNotIn("BindResourceArea", view)
        self.assertIn("BindTimer();", view)

    def test_milestone_feature(self):
        plan = _milestone_plan()
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("using Kinoa.Data.Messaging.InApp.Features;", view)
        self.assertIn("using Kinoa.Data.Messaging.InApp.Features.Milestones;", view)
        self.assertIn("var feature = Data.Feature as InAppMilestonesFeature;", view)
        self.assertIn("milestoneFill.fillAmount", view)
        self.assertIn("step.Status == InAppMilestoneStatus.Reached", view)
        self.assertIn("Kinoa.Messaging.CollectMilestonesAsync(Message, new List<uint> { index })", view)
        self.assertIn("Message.SetMilestonesStatusAsCollected(response.Data.Collected);", view)
        self.assertIn("if (response.Data.InApp != null)", view)
        self.assertIn('ApplyButtonSlot(milestoneMainButton, milestoneMainButtonLabel, "milestone_main", feature.ActiveProgressButton, canBeHidden: true);', view)
        self.assertIn("private void BindGrandPrize(", view)
        self.assertIn("%s apply the collected step's Button.Resources" % mod.TODO, view)

    def test_mission_feature(self):
        plan = _mission_plan()
        view = mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]
        self.assertIn("using Kinoa.Data.Messaging.InApp.Features.Missions;", view)
        self.assertIn("var feature = Data.Feature as InAppMissionsFeature;", view)
        self.assertIn("row.SetValue($\"{mission.CurrentScore}/{mission.GoalScore}\");", view)
        self.assertIn("mission.Status == InAppMissionStatus.Reached", view)
        self.assertIn("Kinoa.Messaging.CollectMissionsProgressAsync(Message, setNumber, new List<int> { rowNumber })", view)
        self.assertIn("missionBarFill.fillAmount", view)
        self.assertIn("Bind(response.Data);", view)
        t = copy.deepcopy(TEMPLATE)
        t["key"] = "board"
        t["featureType"] = "mission"
        t["features"] = {"mission": {"progressBar": {"display": "dont_show_at_all"}, "completionCta": ["collect_resource"]}}
        plan_no_bar = _plan(template=t)
        view_no_bar = mod.generate_code(plan_no_bar, {})["files"][plan_no_bar["paths"]["view_path"]]
        self.assertNotIn("missionBarFill", view_no_bar)   # the bar fields do not exist on that view — referencing them would not compile
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_codegen.TestViewZonesAndFeatures -v`
Expected: FAIL — `BindTimer` missing.

- [ ] **Step 3: Implement the zone and feature renderers**

```python
_TIMER_CS = """
        // ------------------------------------------------------------------ client-rendered zones

        private void BindTimer()
        {
            _timerActive = false;
            if (timerRoot == null) return;
            var timer = Message.CountdownTimer;
            var show = timer != null && timer.IsVisible && !timer.IsExpired;
            timerRoot.SetActive(show);
            _timerActive = show;
            if (show) UpdateTimerText();
        }

        private void Update()
        {
            if (_timerActive) UpdateTimerText();
        }

        private void UpdateTimerText()
        {
            if (timerText == null || Message?.CountdownTimer == null) return;
            var remaining = Message.CountdownTimer.EndTimestamp - Kinoa.Time.GetUnixTime();
            if (remaining <= 0)
            {
                remaining = 0;
                _timerActive = false;
            }
            timerText.text = TimeSpan.FromSeconds(remaining).ToString(@"hh\\:mm\\:ss");
        }
"""

_PRICE_CS = """
        private void BindPriceBeforeSale()
        {
            if (priceBeforeSaleRoot == null) return;
            var packages = FindBillingButton()?.Packages;
            var hasPreSale = packages != null
                             && (!string.IsNullOrEmpty(packages.AndroidDiscountPackageID) || !string.IsNullOrEmpty(packages.IosDiscountPackageID));
            priceBeforeSaleRoot.SetActive(hasPreSale);
            if (!hasPreSale || priceBeforeSaleText == null) return;
            if (KinoaInAppHooks.ResolveStorePrice == null)
            {
                KinoaInAppHooks.WarnMissing(nameof(KinoaInAppHooks.ResolveStorePrice));
                priceBeforeSaleText.text = string.Empty;
                return;
            }
            priceBeforeSaleText.text = KinoaInAppHooks.ResolveStorePrice(packages, true) ?? string.Empty;
        }

        private InAppCustomButton FindBillingButton()
        {
            if (Data.Buttons == null) return null;
            foreach (var pair in Data.Buttons)
                if (pair.Value?.ClickConfig is InAppBillingClickConfiguration) return pair.Value;
            return null;
        }
"""

_RESOURCES_CS = """
        private void BindResourceArea()
        {
            if (resourceAreaRoot == null) return;
            var resources = FindItemBearingButton()?.Resources;
            var show = resources != null && resources.Count > 0;
            resourceAreaRoot.SetActive(show);
            if (!show || resourceItemTemplate == null) return;
            foreach (var resource in resources)
            {
                var item = Spawn(resourceItemTemplate);
                item.SetLabel(resource.Amount.ToString());
                item.SetValue(string.Empty);
                item.SetIcon(ResolveIcon(resource.ResourceKey));
                item.SetFill(0f);
                item.SetButton(false, null);
            }
        }

        private InAppCustomButton FindItemBearingButton()
        {
            if (Data.Buttons == null) return null;
            foreach (var pair in Data.Buttons)
                if (pair.Value?.Resources != null && pair.Value.Resources.Count > 0) return pair.Value;
            return null;
        }
"""

_RESOLVE_ICON_CS = """
        private static Sprite ResolveIcon(string resourceKey)
        {
            if (KinoaInAppHooks.ResolveResourceIcon != null) return KinoaInAppHooks.ResolveResourceIcon(resourceKey);
            KinoaInAppHooks.WarnMissing(nameof(KinoaInAppHooks.ResolveResourceIcon));
            return null;
        }
"""

_MILESTONE_CS = """
        // ------------------------------------------------------------------ milestones feature

        private void BindFeature()
        {
            var feature = Data.Feature as InAppMilestonesFeature;
            if (milestoneBarRoot != null) milestoneBarRoot.SetActive(feature != null);
            if (feature == null) return;
            var steps = feature.Steps ?? new List<InAppMilestoneStep>();
            var total = steps.Count > 0 ? steps[steps.Count - 1].Score : 0L;
            if (milestoneFill != null) milestoneFill.fillAmount = total > 0 ? Mathf.Clamp01((float)(feature.Progress / total)) : 0f;
            if (milestoneMarkerTemplate != null)
            {
                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    var index = (uint)i;   // CollectMilestonesAsync takes 0-based step indexes
                    var item = Spawn(milestoneMarkerTemplate);
                    item.SetLabel(step.Score.ToString());
                    item.SetValue(step.Status.ToString());
                    item.SetFill(step.Status == InAppMilestoneStatus.Closed ? 0f : 1f);
                    item.SetButton(step.Status == InAppMilestoneStatus.Reached, () => _ = CollectMilestoneAsync(index));
                }
            }
            ApplyButtonSlot(milestoneMainButton, milestoneMainButtonLabel, "milestone_main", feature.ActiveProgressButton, canBeHidden: true);
            BindGrandPrize(steps);
        }

        private void BindGrandPrize(List<InAppMilestoneStep> steps)
        {
            if (grandPrizeRoot == null) return;
            var prize = steps.Count > 0 ? steps[steps.Count - 1].Button?.Resources : null;
            var show = prize != null && prize.Count > 0;
            grandPrizeRoot.SetActive(show);
            if (!show) return;
            if (grandPrizeImage != null) grandPrizeImage.sprite = ResolveIcon(prize[0].ResourceKey);
            if (grandPrizeText != null) grandPrizeText.text = prize.Count == 1 ? prize[0].Amount.ToString() : $"x{prize.Count}";
        }

        private async Task CollectMilestoneAsync(uint index)
        {
            var response = await Kinoa.Messaging.CollectMilestonesAsync(Message, new List<uint> { index });
            if (this == null) return;
            if (response == null || !response.IsSuccessful() || response.Data == null)
            {
                Debug.LogWarning($"[{GetType().Name}] milestone {index} collect failed: {response?.Error?.ToString() ?? "no response"}");
                return;
            }
            // %(todo)s apply the collected step's Button.Resources to the player's economy here (same place as KinoaUiService.GrantRewards).
            if (response.Data.InApp != null)
            {
                Bind(response.Data.InApp);   // the instance was reset — the server sent a fresh message
                return;
            }
            Message.SetMilestonesStatusAsCollected(response.Data.Collected);
            Bind(Message);
        }
""" % {"todo": TODO}

_MISSION_CS = """
        // ------------------------------------------------------------------ missions feature

        private void BindFeature()
        {
            var feature = Data.Feature as InAppMissionsFeature;
            if (missionListRoot != null) missionListRoot.gameObject.SetActive(feature != null);
            if (feature == null) return;
            var set = feature.MissionState?.ActiveSetProgress;
            var missions = set?.ActiveMissions ?? new List<InAppMission>();
            if (missionRowTemplate != null && set != null)
            {
                foreach (var mission in missions)
                {
                    var row = Spawn(missionRowTemplate);
                    row.SetLabel(mission.MissionText);
                    row.SetValue($"{mission.CurrentScore}/{mission.GoalScore}");
                    row.SetFill(mission.GoalScore > 0 ? (float)(mission.CurrentScore / mission.GoalScore) : 0f);
                    var setNumber = set.SetNumber;
                    var rowNumber = mission.RowNumber;
                    row.SetButton(mission.Status == InAppMissionStatus.Reached, () => _ = CollectMissionAsync(setNumber, rowNumber));
                }
            }
%(bar)s        }

        private async Task CollectMissionAsync(int setNumber, int rowNumber)
        {
            var response = await Kinoa.Messaging.CollectMissionsProgressAsync(Message, setNumber, new List<int> { rowNumber });
            if (this == null) return;
            if (response == null || !response.IsSuccessful() || response.Data == null)
            {
                Debug.LogWarning($"[{GetType().Name}] mission row {rowNumber} collect failed: {response?.Error?.ToString() ?? "no response"}");
                return;
            }
            // %(todo)s apply the mission's ProcessedResources to the player's economy here (same place as KinoaUiService.GrantRewards).
            Bind(response.Data);
        }
"""

_MISSION_BAR_CS = """            var bar = feature.MissionState?.ProgressBarState;
            var hasBar = bar?.Milestones != null && bar.Milestones.Count > 0;
            if (missionBarRoot != null) missionBarRoot.SetActive(hasBar);
            if (missionBarFill != null && hasBar)
            {
                var last = bar.Milestones[bar.Milestones.Count - 1].Score;
                missionBarFill.fillAmount = last > 0 ? Mathf.Clamp01((float)(bar.TotalScore / last)) : 0f;
            }
"""


def render_zone_methods(plan):
    names = {n["name"] for n in plan["nodes"]}
    out = ""
    if "TimerZone" in names:
        out += _TIMER_CS
    if "PriceBeforeSaleZone" in names:
        out += _PRICE_CS
    if "ResourceArea" in names:
        out += _RESOURCES_CS
    if "ResourceArea" in names or "GrandPrizeArea" in names:
        out += _RESOLVE_ICON_CS   # shared by the resource area and the milestone grand prize
    return out


def render_feature_methods(plan):
    ftype = plan["template"]["feature_type"]
    if ftype == "milestone":
        return _MILESTONE_CS
    if ftype == "mission":
        has_bar = any(n["name"] == "MissionBar" for n in plan["nodes"])
        return _MISSION_CS % {"todo": TODO, "bar": _MISSION_BAR_CS if has_bar else ""}
    return ""
```

`ResolveIcon` lives in its own block because a milestone template whose buttons carry no item-bearing action still needs it for the grand prize. `FindBillingButton` and `FindItemBearingButton` are each defined in exactly one block, so including every block never duplicates a member.

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_inapp_prefab_codegen -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_codegen.py
git commit -m "feat(inapp-prefab): timer, pre-sale price, resource area, milestone and mission bindings in the view"
```

---

### Task 8: `generate` CLI — write files into the game project, facade detection flag, constants/facade snippets, forbidden-string guard

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py` (replace `render_snippets`, add `FORBIDDEN_IN_GENERATED`, `cmd_generate`, CLI wiring)
- Test: `tests/test_inapp_prefab_codegen.py` (append `TestGenerateCli`)

**Interfaces:**
- CLI: `generate --plan F --project-root DIR [--facade present|absent] [--facade-namespace NS] [--image-loader M] [--price-resolver M] [--resource-icon-resolver M] [--force-shared] [--overwrite]` → prints `{ok, written: [paths], skipped: [paths], snippets: {constant, allowlist_arm, create_game_inapp}, todos: [{path, line, text}], report}`. Exit `2` on: unreadable plan, `view_exists` without `--overwrite`, `shared_text_system_mismatch` without `--force-shared`, or a forbidden string in any generated file (`forbidden_content` — a generator bug, never expected).
- Snippets (strings the SKILL.md applies with `Edit` after approval):
  - `constant`: `        public const string TemplateKey<Pascal> = "<key>";`
  - `allowlist_arm`: `            KinoaInAppTemplateConstants.TemplateKey<Pascal> => true,`
  - `create_game_inapp`: a C# block for `KinoaUiService.CreateGameInApp` showing instantiate → `Bind` → `Show`, using `Resources.Load`-free prefab reference via a `[SerializeField] KinoaInApp<Pascal>View <camel>Prefab;` field.

- [ ] **Step 1: Append the failing tests**

```python
class TestGenerateCli(unittest.TestCase):
    def _run(self, *extra):
        import subprocess, sys, tempfile
        root = tempfile.mkdtemp()
        plan_path = os.path.join(root, "p.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(_plan(), fh)
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, *extra],
                             capture_output=True, text=True)
        return root, res

    def test_writes_files_and_snippets(self):
        root, res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])
        view = os.path.join(root, "Assets", "Kinoa", "InApps", "OneCtaOffer", "KinoaInAppOneCtaOfferView.cs")
        self.assertTrue(os.path.isfile(view))
        self.assertTrue(os.path.isfile(os.path.join(root, "Assets", "Kinoa", "InApps", "Editor", "KinoaInAppPrefabBuilder.cs")))
        self.assertTrue(os.path.isfile(os.path.join(root, "Assets", "Kinoa", "InApps", "OneCtaOffer", "one_cta_offer.inapp-plan.json")))
        self.assertEqual(data["snippets"]["constant"], '        public const string TemplateKeyOneCtaOffer = "one_cta_offer";')
        self.assertEqual(data["snippets"]["allowlist_arm"], "            KinoaInAppTemplateConstants.TemplateKeyOneCtaOffer => true,")
        self.assertIn("KinoaInAppOneCtaOfferView", data["snippets"]["create_game_inapp"])
        self.assertTrue(any(t["text"].startswith("TODO(kinoa-prefab):") for t in data["todos"]))
        self.assertTrue(all(t["path"].endswith(".cs") for t in data["todos"]))

    def test_second_run_refuses_to_overwrite_view_without_flag(self):
        root, res = self._run()
        import subprocess, sys
        plan_path = os.path.join(root, "p.json")
        res2 = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root],
                              capture_output=True, text=True)
        self.assertEqual(res2.returncode, 2)
        self.assertEqual(json.loads(res2.stdout)["error"], "view_exists")
        res3 = subprocess.run([sys.executable, HELPER, "generate", "--plan", plan_path, "--project-root", root, "--overwrite"],
                              capture_output=True, text=True)
        data = json.loads(res3.stdout)
        self.assertTrue(data["ok"])
        self.assertIn("Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs", data["skipped"])  # shared files kept

    def test_shared_text_system_mismatch_is_refused(self):
        root, _ = self._run()
        hooks_dir = os.path.join(root, "Assets", "Kinoa", "InApps", "Shared")
        with open(os.path.join(hooks_dir, "KinoaInAppItemView.cs"), "w", encoding="utf-8") as fh:
            fh.write("using KinoaText = TMPro.TMP_Text;\n")
        import subprocess, sys
        res = subprocess.run([sys.executable, HELPER, "generate", "--plan", os.path.join(root, "p.json"),
                              "--project-root", root, "--overwrite"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(json.loads(res.stdout)["error"], "shared_text_system_mismatch")

    def test_facade_flag_reaches_the_view(self):
        root, res = self._run("--facade", "present", "--facade-namespace", "Game.Kinoa")
        with open(os.path.join(root, "Assets", "Kinoa", "InApps", "OneCtaOffer", "KinoaInAppOneCtaOfferView.cs"), encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn("using Game.Kinoa;", view)
        self.assertIn("HandleInAppButtonClickAsync(Message, key)", view)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_codegen.TestGenerateCli -v`
Expected: FAIL — `generate` is not a known subcommand.

- [ ] **Step 3: Implement snippets, the guard, and `cmd_generate`**

```python
FORBIDDEN_IN_GENERATED = ("dashboard.kinoa.io", "Bearer", "UnityWebRequest", "Addressables.Load")


def render_snippets(plan, options):
    key = plan["template"]["key"]
    P = pascal(key)
    cls = plan["view"]["class_name"]
    cam = camel(key)
    create = (
        "        // In KinoaUiService.CreateGameInApp(InAppMessage inAppMessage, string source, string reason, bool addToDisplayQueue):\n"
        "        //   [SerializeField] private %(cls)s %(cam)sPrefab;   // assign %(prefab)s in the inspector\n"
        "        if (inAppMessage.Data is InAppCustomTemplateData custom && custom.TemplateKey == KinoaInAppTemplateConstants.TemplateKey%(P)s)\n"
        "        {\n"
        "            var view = Instantiate(%(cam)sPrefab, /* your popup layer */ transform);\n"
        "            if (!view.Bind(inAppMessage)) { Destroy(view.gameObject); return; }\n"
        "            view.Closed += v => RemoveGameInApp(inAppMessage.Uuid, nameof(CreateGameInApp), \"closed by player\");\n"
        "            view.Show();\n"
        "            return;\n"
        "        }\n"
    ) % {"cls": cls, "cam": cam, "P": P, "prefab": plan["paths"]["prefab_path"]}
    return {
        "constant": '        public const string TemplateKey%s = "%s";' % (P, key),
        "allowlist_arm": "            KinoaInAppTemplateConstants.TemplateKey%s => true," % P,
        "create_game_inapp": create,
    }


def _collect_todos(files):
    todos = []
    for path, content in files.items():
        if not path.endswith(".cs"):
            continue
        for lineno, line in enumerate(content.splitlines(), 1):
            idx = line.find(TODO)
            if idx >= 0:
                todos.append({"path": path, "line": lineno, "text": line[idx:].strip()})
    return todos


def _existing_alias(path):
    try:
        with open(path, encoding="utf-8") as fh:
            m = re.search(r"using KinoaText = ([\w.]+);", fh.read())
    except OSError:
        return None
    return m.group(1) if m else None


def cmd_generate(args):
    try:
        plan = _read_json(args.plan)
    except (OSError, json.JSONDecodeError) as exc:
        _emit({"ok": False, "error": "unreadable_input", "detail": str(exc)})
        return 2
    options = {"facade": args.facade, "facade_namespace": args.facade_namespace, "image_loader": args.image_loader,
               "price_resolver": args.price_resolver, "resource_icon_resolver": args.resource_icon_resolver}
    plan["view"]["facade"] = args.facade
    plan["view"]["facade_namespace"] = args.facade_namespace if args.facade == "present" else None
    out = generate_code(plan, options)
    files = out["files"]

    for path, content in files.items():
        for bad in FORBIDDEN_IN_GENERATED:
            if path.endswith(".cs") and bad in content:
                _emit({"ok": False, "error": "forbidden_content", "path": path, "token": bad})
                return 2

    root = args.project_root
    view_abs = os.path.join(root, plan["paths"]["view_path"])
    if os.path.exists(view_abs) and not args.overwrite:
        _emit({"ok": False, "error": "view_exists", "path": plan["paths"]["view_path"], "override": "--overwrite"})
        return 2
    shared = [p for p in files if "/Shared/" in p or "/Editor/" in p]
    expected_alias = "TMPro.TMP_Text" if plan["ui"]["text_system"] == "tmp" else "UnityEngine.UI.Text"
    for p in shared:
        existing = _existing_alias(os.path.join(root, p))
        if existing and existing != expected_alias and not args.force_shared:
            _emit({"ok": False, "error": "shared_text_system_mismatch", "path": p, "existing": existing,
                   "expected": expected_alias, "override": "--force-shared"})
            return 2

    written, skipped = [], []
    for path, content in files.items():
        abs_path = os.path.join(root, path)
        if path in shared and os.path.exists(abs_path) and not args.force_shared:
            skipped.append(path)
            continue
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(path)
    _emit({"ok": True, "written": written, "skipped": skipped, "snippets": out["snippets"],
           "todos": _collect_todos(files), "report": out["report"], "prefab_path": plan["paths"]["prefab_path"],
           "plan_path": plan["paths"]["plan_path"], "menu_item": "Tools/Kinoa/In-Apps/Build Prefabs From Plans"})
    return 0
```

CLI wiring in `main()`:

```python
    p = sub.add_parser("generate", help="Plan -> C# files + plan copy under the game project.")
    p.add_argument("--plan", required=True)
    p.add_argument("--project-root", required=True, help="Unity project root (the folder containing Assets/).")
    p.add_argument("--facade", choices=("present", "absent"), default="absent",
                   help="present = the project has KinoaUiService; clicks delegate to HandleInAppButtonClickAsync.")
    p.add_argument("--facade-namespace", default="Core.Services")
    p.add_argument("--image-loader", default=None, help="Fully-qualified static method: Func<string, Task<Sprite>>.")
    p.add_argument("--price-resolver", default=None, help="Fully-qualified static method: Func<InAppStorePackages, bool, string>.")
    p.add_argument("--resource-icon-resolver", default=None, help="Fully-qualified static method: Func<string, Sprite>.")
    p.add_argument("--force-shared", action="store_true", help="Rewrite Shared/ and Editor/ files even if present.")
    p.add_argument("--overwrite", action="store_true", help="Rewrite the view class if it already exists.")
    p.set_defaults(func=cmd_generate)
```

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover tests`
Expected: all PASS (existing + the four new modules).

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/test_inapp_prefab_codegen.py
git commit -m "feat(inapp-prefab): generate CLI — project writes, facade flag, constants/facade snippets, TODO index"
```

---

### Task 9: SKILL.md workflow + the two contract references

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-to-prefab/SKILL.md` (append the body after the intro from Task 1)
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/references/prefab-plan-schema.md`
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/references/generated-code-contract.md`
- Test: `tests/test_inapp_prefab_fixtures.py` (append `TestSkillDoc`)

**Interfaces:**
- Consumes every CLI from Tasks 2–8 and the sibling helpers `kinoa-init/kinoa_init.py show`, `kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py list|get`, `kinoa-api-integration/kinoa_webhook.py`.
- Produces the developer-facing workflow. Phase labels (exact strings for telemetry): `Phase 1 — Preflight`, `Phase 2 — Reference popups`, `Phase 3 — Layout source`, `Phase 4 — Plan`, `Phase 5 — Generate`, `Phase 6 — Build in Unity`, `Phase 7 — Hand-off`.

- [ ] **Step 1: Append the failing doc test**

```python
class TestSkillDoc(unittest.TestCase):
    def test_phases_commands_and_rules_present(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            doc = fh.read()
        for phase in ("## Phase 1 — Preflight", "## Phase 2 — Reference popups", "## Phase 3 — Layout source",
                      "## Phase 4 — Plan", "## Phase 5 — Generate", "## Phase 6 — Build in Unity", "## Phase 7 — Hand-off"):
            self.assertIn(phase, doc)
        for cmd in ("inapp_prefab_plan.py\" probe-style", "inapp_prefab_plan.py\" plan", "inapp_prefab_plan.py\" generate",
                    "inapp_prefab_plan.py\" layout-schema", "kinoa_init.py\" show", "kinoa_dashboard_inapp_template.py\" get"):
            self.assertIn(cmd, doc)
        self.assertIn("Tools/Kinoa/In-Apps/Build Prefabs From Plans", doc)
        self.assertIn("references/unity-mcp-capabilities.md", doc)
        self.assertIn("TODO(kinoa-prefab)", doc)
        self.assertIn("never write", doc.lower())
        self.assertIn("Never `cat ~/.kinoa/session.env`", doc)   # the doc forbids it, never instructs it
        for ref in ("prefab-plan-schema.md", "generated-code-contract.md"):
            self.assertTrue(os.path.isfile(os.path.join(SKILL, "references", ref)))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_fixtures.TestSkillDoc -v`
Expected: FAIL — phases missing.

- [ ] **Step 3: Write the SKILL.md body**

Append to `SKILL.md` (after the intro). Also extend the frontmatter's `allowed-tools` to `Bash(python *) Bash(curl *) Read Write Edit Glob Grep AskUserQuestion Agent ToolSearch` (curl is used only to fetch a tip image URL in Phase 3B).

````markdown
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
`inAppsCount`). Then fetch the full record:

```bash
python "${CLAUDE_SKILL_DIR}/../kinoa-dashboard-inapp-template/kinoa_dashboard_inapp_template.py" get --id <id> > .kinoa-inapp-prefab/<key>/template_record.json
```

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

Ask for the names of the game's existing pop-up prefabs. Pre-fill the question
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

Ask which layout source to use (one question, recommended first):

- **A — In-app layout recognition output (recommended).** The developer ran
  `kinoa-inapp-template-from-image` for this template: ask for the
  `build_result.json` path (and the confirmed envelope, if they kept it). Its
  `report.elements[].bbox` positions every slot and `report.client_rendered`
  positions the timer / price / resource zones. Read `source_image.width/height`
  from the matching `analysis.json` when available → `--image-size WxH`.
- **B — Tip image.** A path or URL, or the record's `tipImageUrl`. A URL is
  fetched with `curl -sSL -o .kinoa-inapp-prefab/<key>/tip.<ext> "<url>"`.
  If the record only carries a `tipImageBlob` (the helper summarises blobs),
  ask the developer for the image file. Then run the vision pass in a
  **subagent** (keeps the transcript small): give it the image path, the slot
  list from the record (bucket · key · name for images/buttons/texts), the
  client-zone names, and the contract from

  ```bash
  python "${CLAUDE_SKILL_DIR}/inapp_prefab_plan.py" layout-schema
  ```

  It returns only `layout.json`. Keys not on the template are reported by the
  planner under `unmapped_layout` — never silently dropped.
- **C — No image.** Every slot lands in the `Unplaced` container; the plan
  report says so. Offer this only when A and B are impossible.

## Phase 4 — Plan

```bash
python "${CLAUDE_SKILL_DIR}/inapp_prefab_plan.py" plan \
  --template .kinoa-inapp-prefab/<key>/template_record.json \
  --build <build_result.json> [--confirmed <envelope.json>]      # option A
  # or: --layout .kinoa-inapp-prefab/<key>/layout.json            # option B
  --style .kinoa-inapp-prefab/<key>/style_probe.json \
  [--image-size 1080x1920] [--out-dir Assets/Kinoa/InApps] \
  --out .kinoa-inapp-prefab/<key>/<key>.inapp-plan.json
```

Read `report` and show it: `unplaced` slots, `estimated_positions` (zones and
feature UIs placed at defaults), `unmapped_layout`, `client_zones` that will
be built, `needs_developer`.

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

Writes the view, the plan copy, and — only when absent — the shared
`KinoaInAppHooks.cs`, `KinoaInAppItemView.cs`, `Editor/KinoaInAppPrefabBuilder.cs`.
`view_exists` ⇒ confirm with the developer, then re-run with `--overwrite`.
`shared_text_system_mismatch` ⇒ the project already has shared files for the
other text system: keep the existing one (re-run `plan` with the matching
`text_system` in `style_probe.json`) rather than forcing.

When `facade=present`, show the `constant` and `allowlist_arm` snippets and
ask before applying them with `Edit` to `KinoaInAppTemplateConstants.cs` and
`KinoaUiService.IsKnownCustomTemplateKey` (one constant, one switch arm —
exactly what the SDK's module 06 prescribes). The `create_game_inapp` snippet
is **hand-off only**: wiring `CreateGameInApp` is the `/kinoa messaging
--merge` flow's job and may already route through a popup manager.

## Phase 6 — Build in Unity

1. **Refresh + compile** via the server's refresh tool (table in the MCP
   reference). Wait for the compile to finish, then read the console with the
   server's console tool and look for `error CS`. Errors in generated files ⇒
   fix the generator input (wrong facade namespace, TMP missing → legacy),
   re-run `generate --overwrite`, repeat. Never patch generated C# by hand.
2. **Build the prefab**: run the menu item
   `Tools/Kinoa/In-Apps/Build Prefabs From Plans` (or call
   `Kinoa.InApps.Editor.KinoaInAppPrefabBuilder.BuildAll` through the server's
   reflection/method tool).
3. **Read the report** from disk:
   `Assets/Kinoa/InApps/<Pascal>/<key>.build-report.json` → `ok: true`,
   `fields_missing: []`, `errors: []`. `view class not found` ⇒ compile had not
   finished; refresh again and rebuild. `fields_missing` ⇒ the view and the plan
   are out of step; re-run `generate --overwrite` and rebuild.
4. **Verify the asset**: `Glob` the `prefab_path`; optionally inspect it with
   the server's GameObject/prefab inspection tool.

## Phase 7 — Hand-off

Summarise, in this order: prefab path · view class · fields assigned ·
**every `TODO(kinoa-prefab)` with `path:line`** (from `generate`'s `todos`) ·
unplaced slots and estimated positions · snippets shown but not applied ·
next steps (assign the hooks in the game's bootstrap; wire `CreateGameInApp`
via `/kinoa messaging --merge`; activate the template on the Dashboard when the
first in-app is configured). Say plainly what was verified in Unity and what
was not.

## Telemetry

Repo-wide rules ([`../kinoa-api-integration/references/telemetry.md`](../kinoa-api-integration/references/telemetry.md)):
`phase-start` / `phase-end` for Phases 1–7 via
`${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`, `qa` after
every `AskUserQuestion`. Disclose once per run. Failures never abort.

## Hard rules

1. **No Unity MCP, no run.** The prefab is built by the Editor through the
   bridge; the skill never hand-writes `.prefab` YAML.
2. **Dashboard reads go through `kinoa-dashboard-inapp-template`.** The
   helper here is offline; nothing in it or in generated code calls
   `dashboard.kinoa.io` or carries a bearer. Read credentials only via
   `kinoa_init.py show`.
3. **Never write a download method.** Remote images, store prices and
   resource icons are game-supplied delegates on `KinoaInAppHooks`; the skill
   finds and wires existing methods or leaves `TODO(kinoa-prefab)`.
4. **Generated files are regenerated, not patched.** Fix the plan or the
   generator input and re-run `generate --overwrite`.
5. **Facade edits are limited to the constant + allowlist arm**, each behind
   an `AskUserQuestion`. `RouteByClickConfigAsync` TODOs and `CreateGameInApp`
   are never edited from here.
6. **Client-rendered zones are positions, not slots.** They never become
   template elements; the view fills them from the message.
7. **Every unplaced slot, estimated position and TODO is surfaced** in the
   hand-off. Nothing is dropped silently.
````

- [ ] **Step 4: Write `references/prefab-plan-schema.md`**

```markdown
# Prefab plan — the JSON contract between the planner and the Editor builder

Produced by `inapp_prefab_plan.py plan`, copied into the project as
`<out_dir>/<Pascal>/<key>.inapp-plan.json`, consumed by
`Editor/KinoaInAppPrefabBuilder.cs` (JsonUtility ⇒ flat, typed, no recursion).

## Top level

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | `"1.0"` | bump when a node field changes meaning |
| `template` | object | `id`, `key`, `name`, `feature_type` (`standard`/`mission`/`milestone`), plus the slot lists the view generator reads (`images`, `texts`, `buttons`, `customs`) |
| `ui` | object | `text_system` (`legacy`/`tmp`), `font_guid`, `tmp_font_guid`, `frame_size` `[w,h]`, `close_sprite_guid`, `dimmer_alpha` |
| `view` | object | `class_name`, `ns` (always `Kinoa.InApps`), `facade`, `facade_namespace` |
| `paths` | object | `out_dir`, `prefab_path`, `view_path`, `plan_path` — all project-relative |
| `nodes` | array | flat GameObject list, parent-before-child order |
| `customs` | array | `{key, kind, default, target_node, target_field}` — boolean knobs that toggle a node |
| `report` | object | `unplaced`, `estimated_positions`, `warnings`, `unmapped_layout`, `client_zones`, `needs_developer` |

## Node

| Field | Meaning |
|---|---|
| `name` | unique GameObject name; `parent` names another node or `null` for the prefab root |
| `binding` | `dimmer` · `frame` · `panel` · `image` · `text` · `button` · `button_label` · `zone` · `strike` · `fill` · `markers` · `item_template` · `unplaced` |
| `components` | subset of `Image`, `Button`, `Text`, `HorizontalLayoutGroup`, `VerticalLayoutGroup` (`Text` resolves to legacy or TMP per `ui.text_system`) |
| `field` / `field_type` | the view's `[SerializeField]` to assign; types `GameObject`, `RectTransform`, `Image`, `Button`, `Text`, `KinoaInAppItemView` |
| `anchor_min` / `anchor_max` | uGUI anchors, offsets zero (stretch within the anchors) |
| `size` | `[w,h]` centred fixed size — used instead of anchors (Frame, item templates) |
| `placed` | false when the position was not derived from a layout source |
| `inactive` | node starts disabled (zones, item templates) |
| `key` / `bucket` / `role` | the template slot this node renders |
| `click_actions` / `custom_cta_names` | copied from the template button |
| `sprite_guid` | optional sprite to assign to the node's Image |

## Hierarchy

```
KinoaInApp_<Pascal>           (root, stretch; the view component lives here)
├── Dimmer                    Image, black α 0.6, stretch
└── Frame                     fixed ui.frame_size, centred — the mockup's canvas
    └── Panel                 anchored to the background_image bbox (or union of boxes)
        ├── BackgroundImage   stretch
        ├── <slot nodes>      anchored from bbox, relative to Panel
        ├── <ButtonName>Label stretch child of its button
        ├── TimerZone / PriceBeforeSaleZone / ResourceArea / GrandPrizeArea   (inactive)
        ├── MilestoneBar … / MissionList …                                       (feature)
        └── Unplaced          VerticalLayoutGroup, bottom 30 % of the panel — slots with no bbox
```

## Anchor math

bbox and panel are normalised to the mockup (origin top-left). Relative box
`r = ((x−Px)/Pw, (y−Py)/Ph, w/Pw, h/Ph)`; anchors flip y:
`anchor_min = (r.x, 1−(r.y+r.h))`, `anchor_max = (r.x+r.w, 1−r.y)`, clamped to
`[0,1]`, widened to ≥ 0.01 per axis.

## Naming

`field_name(bucket, key)` = lowerCamel(key) + bucket suffix (`Image`/`Text`/`Button`)
unless the key already ends with it: `background_image → backgroundImage`,
`header → headerText`, `cta → ctaButton`. Node name = the field name in
PascalCase. Button labels add `Label`.
```

- [ ] **Step 5: Write `references/generated-code-contract.md`**

```markdown
# Generated code — what the game can rely on

All files carry an `<auto-generated>` header. Regenerate with the skill; do not
hand-edit bound fields. Namespace `Kinoa.InApps` (`Kinoa.InApps.Editor` for the builder).

## `KinoaInApp<Pascal>View : MonoBehaviour` (per template)

| Member | Behaviour |
|---|---|
| `const string TemplateKey` | the dashboard key; `Bind` refuses other templates |
| `InAppMessage Message`, `InAppCustomTemplateData Data` | set by `Bind` |
| `bool Bind(InAppMessage)` | fills texts (`Content`, `<br>`→newline, `text_color`), images (by `InAppImageContentType`), buttons (label or store price, background, click), customs (boolean toggles), client zones, feature UI. Returns false + logs on the wrong template |
| `void Show()` | activates; sends `in_app_impression` once |
| `void Close()` | sends `in_app_close`, raises `Closed`, destroys |
| `event Closed`, `event ButtonClicked(view, buttonKey, InAppClickConfiguration)` | integration points for a popup manager / analytics |
| `TryGetCustom<T>(key, out T)`, `GetCustom<T>(key)` | typed access to `customs` values |

Click routing (`OnButtonClicked`): `in_app_click` → `ButtonClicked` → `close`
action closes the view → otherwise `KinoaUiService.Instance.HandleInAppButtonClickAsync(Message, key)`
when generated with `--facade present`, else a `TODO(kinoa-prefab)` + warning.

Client zones: timer counts down from `CountdownTimer.EndTimestamp` against
`Kinoa.Time.GetUnixTime()`; the pre-sale price shows when a `*DiscountPackageID`
is set (text from `ResolveStorePrice(packages, true)`); the resource area lists
the first item-bearing button's `Resources`; the grand prize echoes the last
milestone step's rewards.

Features: milestones fill the bar (`Progress / last step Score`), spawn one
`KinoaInAppItemView` per step, claim `Reached` steps via
`Kinoa.Messaging.CollectMilestonesAsync` (0-based indexes) and rebind; missions
spawn one row per `ActiveMissions` entry, claim `Reached` rows via
`CollectMissionsProgressAsync(message, setNumber, [rowNumber])` and rebind.

## `KinoaInAppHooks` (shared, static)

| Delegate | Signature | Used for |
|---|---|---|
| `LoadSpriteFromUrl` | `Func<string, Task<Sprite>>` | `WebUrl` images |
| `ResolveStorePrice` | `Func<InAppStorePackages, bool usePreSalePackage, string>` | CTA price (`false`), struck pre-sale price (`true`) |
| `ResolveResourceIcon` | `Func<string resourceKey, Sprite>` | resource area, grand prize, markers |

Unassigned delegates log one warning per use (`WarnMissing`). The skill wires
an existing game method when the developer names one; it never writes one.

## `KinoaInAppItemView` (shared)

`SetLabel`, `SetValue` (hides when empty), `SetIcon` (hides when null),
`SetFill(0..1)`, `SetButton(interactable, UnityAction)`. Built by the Editor
builder with children `Icon`, `Label`, `Value`, `Fill` and a root `Button`.

## `KinoaInAppPrefabBuilder` (Editor)

Menu `Tools/Kinoa/In-Apps/Build Prefabs From Plans` → `BuildAll()`; per plan a
`<key>.build-report.json` (`ok`, `nodes_built`, `fields_assigned`,
`fields_missing`, `errors`) beside the plan. Idempotent: rebuilding overwrites
the prefab from the plan.

## Markers and guarantees

- Every open item is a `// TODO(kinoa-prefab): …` line; `generate` lists them.
- Generated code never contains `dashboard.kinoa.io`, `Bearer`,
  `UnityWebRequest` or `Addressables.Load` — the generator refuses to write
  otherwise (`forbidden_content`).
```

- [ ] **Step 6: Run the doc test**

Run: `python -m unittest tests.test_inapp_prefab_fixtures -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab tests/test_inapp_prefab_fixtures.py
git commit -m "docs(inapp-prefab): SKILL.md workflow, plan schema and generated-code contract"
```

---

### Task 10: Evals + repo wiring (CLAUDE.md, CHANGELOG, from-image hand-off, client guide)

**Files:**
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/evals/evals.json`
- Modify: `CLAUDE.md:60-61` (architecture block), the "In-app templates" domain-rules paragraph (`CLAUDE.md:191`), file index (`CLAUDE.md:215-216`)
- Modify: `CHANGELOG.md` (`[Unreleased] → Added`)
- Modify: `plugin/skills/kinoa-inapp-template-from-image/SKILL.md` (end of Phase 5)
- Modify: `docs/inapp-template-generation-guide.md` (new section before FAQ)
- Test: `tests/test_inapp_prefab_fixtures.py` (append `TestRepoWiring`)

- [ ] **Step 1: Append the failing test**

```python
class TestRepoWiring(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_evals_exist_and_cover_the_gates(self):
        with open(os.path.join(SKILL, "evals", "evals.json"), encoding="utf-8") as fh:
            evals = json.load(fh)
        self.assertEqual(evals["skill_name"], "kinoa-inapp-template-to-prefab")
        names = {e["name"] for e in evals["evals"]}
        for needed in ("stops-without-unity-mcp", "never-writes-image-download", "prefers-layout-recognition-output",
                       "no-trigger-for-template-creation"):
            self.assertIn(needed, names)

    def test_claude_md_changelog_and_handoffs(self):
        self.assertIn("kinoa-inapp-template-to-prefab", self._read("CLAUDE.md"))
        self.assertIn("kinoa-inapp-template-to-prefab", self._read("CHANGELOG.md"))
        self.assertIn("kinoa-inapp-template-to-prefab", self._read("plugin", "skills", "kinoa-inapp-template-from-image", "SKILL.md"))
        self.assertIn("Unity prefab", self._read("docs", "inapp-template-generation-guide.md"))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_inapp_prefab_fixtures.TestRepoWiring -v`
Expected: FAIL — evals.json missing.

- [ ] **Step 3: Write `evals/evals.json`**

```json
{
  "skill_name": "kinoa-inapp-template-to-prefab",
  "notes": "Behavioural cases for the template -> Unity prefab skill. Cases that need a live Unity MCP are marked 'live-' and only run on a machine with an open Unity project + bridge; the portable core checks gating and delegation behaviour.",
  "evals": [
    {
      "id": 1,
      "name": "stops-without-unity-mcp",
      "prompt": "Make a Unity prefab for our Kinoa in-app template 44444444-4444-4444-4444-444444444444.",
      "expected_output": "The skill triggers and its FIRST action is the Unity MCP check (ToolSearch for unity tools + a liveness probe). With no Unity MCP connected it STOPS: it names the three supported servers (CoderGamester mcp-unity, CoplayDev unity-mcp, IvanMurzak Unity-MCP), says the project must be open with the bridge started, and does not fall back to hand-writing prefab YAML or to 'plan only' unless the developer explicitly asks.",
      "files": []
    },
    {
      "id": 2,
      "name": "no-trigger-for-template-creation",
      "prompt": "Here is a mockup PNG of our offer popup — build the Kinoa in-app template from it.",
      "expected_output": "kinoa-inapp-template-to-prefab does NOT trigger; the request routes to kinoa-inapp-template-from-image (mockup -> template structure). No Unity MCP check, no prefab plan.",
      "files": []
    },
    {
      "id": 3,
      "name": "prefers-layout-recognition-output",
      "prompt": "Visualise template one_cta_offer as a prefab. We ran the layout recognition earlier and kept build_result.json; the dashboard record also has a tip image.",
      "expected_output": "At Phase 3 the skill recommends option A (the build_result.json from kinoa-inapp-template-from-image) over the tip image, passes it to `inapp_prefab_plan.py plan --build`, and only falls back to the tip-image vision pass if the developer declines or the file is unusable. The plan report (unplaced, estimated_positions, client_zones) is shown before generating.",
      "files": []
    },
    {
      "id": 4,
      "name": "never-writes-image-download",
      "prompt": "Generate the prefab + view for template one_cta_offer. Our game has no image cache yet — just download the background from the URL in the view.",
      "expected_output": "The skill refuses to write a downloader: it explains remote images go through KinoaInAppHooks.LoadSpriteFromUrl, greps the project for an existing loader, asks which method to wire, and when none exists leaves the `TODO(kinoa-prefab)` with a runtime warning. The generated files contain no UnityWebRequest code; the hand-off lists the TODO with file:line.",
      "files": []
    },
    {
      "id": 5,
      "name": "delegated-dashboard-read-and-credential-hygiene",
      "prompt": "Build the prefab for in-app template 44444444-4444-4444-4444-444444444444; credentials are in ~/.kinoa/session.env.",
      "expected_output": "Credentials are read via kinoa_init.py show (never cat). The template record comes from `kinoa_dashboard_inapp_template.py get --id ...`; the skill makes no direct HTTP call. Generated C# contains no dashboard.kinoa.io URL and no bearer token.",
      "files": []
    },
    {
      "id": 6,
      "name": "facade-edits-are-limited-and-gated",
      "prompt": "Generate the view for template one_cta_offer; our project already has KinoaUiService and KinoaInAppTemplateConstants from the Kinoa SDK samples.",
      "expected_output": "The view is generated with --facade present so clicks delegate to KinoaUiService.Instance.HandleInAppButtonClickAsync(Message, key). The skill shows the constant + allowlist-arm snippets and asks before applying them with Edit; it does NOT edit RouteByClickConfigAsync TODOs or CreateGameInApp — the create_game_inapp snippet is handed off for the /kinoa messaging --merge flow.",
      "files": []
    },
    {
      "id": 7,
      "name": "live-compile-gate-and-build-report",
      "prompt": "Unity is open with mcp-unity running. Build the prefab for template one_cta_offer using the fixture build_result and our OfferPopup.prefab as the style reference.",
      "expected_output": "Phase 6 refreshes/recompiles through the MCP, reads the console for `error CS`, runs the menu item 'Tools/Kinoa/In-Apps/Build Prefabs From Plans', then READS the <key>.build-report.json from disk and reports ok/fields_missing/errors truthfully. A failed compile is reported as such — the skill never claims the prefab exists without the report and a Glob hit on the prefab path.",
      "files": []
    }
  ]
}
```

- [ ] **Step 4: Edit CLAUDE.md**

Architecture block — insert after line 61:

```
kinoa-inapp-template-to-prefab            (standalone — Unity: template record → prefab plan → view C# → prefab via Unity MCP; delegates reads to kinoa-dashboard-inapp-template)
```

Domain rules — append this paragraph after the "In-app templates" paragraph (line 191):

```markdown
**In-app template → Unity prefab (standalone skill, SDK games).** `kinoa-inapp-template-to-prefab` renders one template on the client: it fetches the record through `kinoa-dashboard-inapp-template get`, probes the game's existing popup prefabs for conventions (legacy `Text` vs TMP, font, panel size, close sprite — `probe-style`), positions every slot from the from-image skill's `build_result.json` (`report.elements[].bbox`; preferred) or from a vision pass over the tip image constrained to the template's slot keys, and emits a flat **prefab plan JSON** + C#: a per-template `KinoaInApp<Pascal>View` (binds `InAppMessage`, sends impression/click/close events, `close` closes, every other action delegates to `KinoaUiService.HandleInAppButtonClickAsync` when the facade exists), shared `KinoaInAppHooks` (game-supplied delegates for remote images / store price / resource icons — **the skill never writes a downloader**, it wires an existing game method or leaves `TODO(kinoa-prefab)`), shared `KinoaInAppItemView`, and a generic Editor `KinoaInAppPrefabBuilder` that materialises any plan (menu `Tools/Kinoa/In-Apps/Build Prefabs From Plans`, report `<key>.build-report.json`). **A running Unity MCP is a hard gate** (CoderGamester `mcp-unity`, CoplayDev `unity-mcp`, IvanMurzak `Unity-MCP` — detection + capability table in `references/unity-mcp-capabilities.md`); the skill never hand-writes `.prefab` YAML. Client-rendered zones (timer, price-before-sale, resource area, grand prize) and feature UIs (milestone bar/markers → `CollectMilestonesAsync`, mission rows → `CollectMissionsProgressAsync`) are generated as inactive nodes the view fills from the message — never as template slots. Facade edits are limited to the template-key constant + `IsKnownCustomTemplateKey` arm, each gated by `AskUserQuestion`; `CreateGameInApp` wiring stays with the SDK's `/kinoa messaging --merge`.
```

File index — insert after line 216:

```markdown
- [`plugin/skills/kinoa-inapp-template-to-prefab/SKILL.md`](plugin/skills/kinoa-inapp-template-to-prefab/SKILL.md) — template → Unity prefab + view; `inapp_prefab_plan.py` (`probe-style` / `layout-schema` / `plan` / `generate`, offline) + `references/unity-mcp-capabilities.md` + `references/prefab-plan-schema.md` + `references/generated-code-contract.md`
```

Testing section — add `inapp_prefab_plan` to the list of helpers the unit suite covers.

- [ ] **Step 5: Edit CHANGELOG.md**

Under `## [Unreleased] → ### Added`, append:

```markdown
- `kinoa-inapp-template-to-prefab`: visualises a Kinoa in-app template as a Unity uGUI prefab inside the open Editor via the Unity MCP (hard gate; mcp-unity / unity-mcp / Unity-MCP detected by tool name). Probes existing popup prefabs for UI conventions, positions slots from the from-image skill's `build_result.json` (preferred) or a tip-image vision pass, and generates a per-template `KinoaInApp<Pascal>View` (binds `InAppMessage`, lifecycle events, click routing through `KinoaUiService` when present), shared `KinoaInAppHooks` delegates (remote images / store price / resource icons — wired to existing game methods or left as `TODO(kinoa-prefab)`, never a new downloader), `KinoaInAppItemView`, and the Editor `KinoaInAppPrefabBuilder` with per-plan build reports. Offline tests: `test_inapp_prefab_{fixtures,style_probe,plan,codegen}.py`.
```

- [ ] **Step 6: Hand-off pointer in the from-image skill**

Append to the end of `kinoa-inapp-template-from-image/SKILL.md` Phase 5 (before `---` / `## Telemetry`):

```markdown
**Next step for Unity games — visualise it.** Keep `build_result.json` (and
the confirmed envelope): `kinoa-inapp-template-to-prefab` consumes them as its
preferred layout source and builds the prefab + view in the developer's open
Unity Editor. Mention this in the hand-off when the project is a Unity SDK
integration.
```

- [ ] **Step 7: Client guide section**

Insert before `## FAQ and troubleshooting` in `docs/inapp-template-generation-guide.md`:

```markdown
## Next step: a Unity prefab from the template

For games on the Kinoa Unity SDK, a second module turns the registered template
into a working popup: `kinoa-inapp-template-to-prefab`. It reads the template
from the Dashboard, looks at one or two of your existing popup prefabs to copy
their conventions (text system, font, panel size, close button), places every
slot where the mockup had it — reusing the `build_result.json` this module
produced, so keep it — and builds the prefab inside your open Unity Editor
through a Unity MCP server, together with a view script that binds the in-app
message and routes every button. Three things stay yours: how remote images are
downloaded, how store prices are looked up, and where resource icons come from.
The generated code calls hooks for those; the module wires your existing methods
when you point at them and otherwise leaves clearly marked `TODO(kinoa-prefab)`
lines rather than inventing a downloader.
```

- [ ] **Step 8: Run the full suite**

Run: `python -m unittest discover tests`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/evals CLAUDE.md CHANGELOG.md plugin/skills/kinoa-inapp-template-from-image/SKILL.md docs/inapp-template-generation-guide.md tests/test_inapp_prefab_fixtures.py
git commit -m "docs(inapp-prefab): evals, CLAUDE.md/CHANGELOG wiring, from-image hand-off, client guide section"
```

---

### Task 11: Live verification in the SDK dev project (compile gate + real prefab build through mcp-unity)

**Files:**
- No repo changes expected. Temporary files in `E:\Dev\kinoa-sdk` (`Assets/Kinoa/InApps/**`) are removed at the end; nothing is committed there.
- If a defect is found: fix in `inapp_prefab_plan.py` + add the regression test in the matching `tests/test_inapp_prefab_*.py`, then one commit.

**Interfaces:**
- Consumes: the whole CLI; the dev project's `Assets/Prefabs/OneButtonDialog.prefab` (legacy Text, font guid `e7a63bee…`), the demo `KinoaUiService` (namespace `Core.Services`, has `HandleInAppButtonClickAsync`) — so `--facade present` is exercised.
- Prerequisite the executor must confirm with the user before starting: Unity has `E:\Dev\kinoa-sdk` open and the mcp-unity bridge is running (`Tools/MCP Unity/Server Window`). Tool prefix `mcp__mcp-unity__`.

- [ ] **Step 1: Probe style on the real demo prefab**

```bash
python plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py probe-style --prefab /e/Dev/kinoa-sdk/Assets/Prefabs/OneButtonDialog.prefab --assets-root /e/Dev/kinoa-sdk/Assets --out /e/Dev/kinoa-sdk/.kinoa-inapp-prefab/style_probe.json
```

Expected: `text_system: legacy`, `font_guid: e7a63bee4e93df34ca0dd3548b336621`, `base_classes` contains `OneButtonDialog`, `root_size` non-null.

- [ ] **Step 2: Plan from the fixtures**

```bash
python plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py plan --template plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/template_one_cta.json --build plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/one-cta/build_result_one_cta.json --style /e/Dev/kinoa-sdk/.kinoa-inapp-prefab/style_probe.json --image-size 1080x1920 --out /e/Dev/kinoa-sdk/.kinoa-inapp-prefab/one_cta_offer.inapp-plan.json
```

Expected: `ok: true`, `report.unplaced == []`.

- [ ] **Step 3: Generate into the dev project with the facade present**

```bash
python plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py generate --plan /e/Dev/kinoa-sdk/.kinoa-inapp-prefab/one_cta_offer.inapp-plan.json --project-root /e/Dev/kinoa-sdk --facade present --facade-namespace Core.Services
```

Expected: 5 files written under `Assets/Kinoa/InApps/`.

- [ ] **Step 4: Compile gate through the MCP**

Call `mcp__mcp-unity__recompile_scripts`, then `mcp__mcp-unity__get_console_logs` filtered to errors. Expected: zero entries containing `error CS`. Any error in a generated file is a generator defect: record the exact message, fix the template string in `inapp_prefab_plan.py`, add a text assertion for it in `tests/test_inapp_prefab_codegen.py`, re-run `generate --overwrite`, recompile.

- [ ] **Step 5: Build the prefab**

Call `mcp__mcp-unity__execute_menu_item` with `Tools/Kinoa/In-Apps/Build Prefabs From Plans`. Then Read `E:\Dev\kinoa-sdk\Assets\Kinoa\InApps\OneCtaOffer\one_cta_offer.build-report.json`.
Expected: `ok: true`, `fields_missing: []`, `errors: []`, `nodes_built ≥ 20`, `fields_assigned ≥ 14`. Then `mcp__mcp-unity__get_gameobject` is not applicable to a prefab asset; instead Glob `Assets/Kinoa/InApps/OneCtaOffer/KinoaInApp_OneCtaOffer.prefab` and open it in the console log line the builder printed.

- [ ] **Step 6: Milestone + mission variants compile too**

Repeat Steps 2–4 with the two synthetic templates from the tests (`featureType` `milestone` / `mission`, keys `chase` / `board`): write them to `.kinoa-inapp-prefab/` with a tiny Python one-liner that loads the fixture and sets `key`/`featureType`/`features`, plan with no layout (fallback path), generate with `--facade absent`, recompile, check zero `error CS`, build, read both reports.

- [ ] **Step 7: Clean the dev project**

Confirm with the user, then delete `E:\Dev\kinoa-sdk\Assets\Kinoa` (and `Assets/Kinoa.meta`) and `E:\Dev\kinoa-sdk\.kinoa-inapp-prefab`; run `git -C /e/Dev/kinoa-sdk status --porcelain` and expect no entries from this task (the dev project is not touched otherwise). Nothing is committed to kinoa-sdk.

- [ ] **Step 8: Record the outcome**

In the integration-skills PR description (or the final hand-off), state exactly: which Unity version compiled the generated code, that the three variants compiled with zero errors, and the three build reports' `ok` values. If any step could not be run (Unity not open), say so — do not report the compile gate as passed.

- [ ] **Step 9: Commit (only if a defect was fixed)**

```bash
git add plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py tests/
git commit -m "fix(inapp-prefab): <what the Unity compile gate caught>"
```

---

## Self-review (done while writing)

**Spec coverage.** (1) Unity MCP checkpoint → Task 1 reference + Task 9 Phase 1.1 + eval 1. (2) Kinoa inited + template id → Phase 1.2/1.3 via `kinoa_init.py show` and the dashboard helper `get`; `unwrap_template` (Task 3) accepts the helper's raw output. (3) Existing popup prefab names → Phase 2 + `probe-style` (Task 2). (4) Two layout options, recognition preferred → Phase 3 A/B(+C) + `layout_from_build` / `layout_from_layout_file` (Tasks 3–4) + eval 3. (5) Prefab + scripts + real button logic → Tasks 5–8 (view binding, click routing, lifecycle events, zones, milestone/mission claims) + Editor builder; built through MCP in Phase 6, verified live in Task 11. (6) Download link = TODO, ask devs for their method → `KinoaInAppHooks` (Task 5), hooks discovery + question (Phase 4), `FORBIDDEN_IN_GENERATED` guard (Task 8), eval 4. Repo conventions → tests per task, evals + CLAUDE/CHANGELOG/guide (Task 10), telemetry section, no version bump.

**Placeholder scan.** The three `_add_*` stubs in Task 3 and the `render_*` stubs in Tasks 5–6 are explicitly replaced in the next task with full code (listed in that task's Step 3); no "TBD"/"implement later" remains. The generated C# `TODO(kinoa-prefab)` lines are a deliverable of the spec, not plan placeholders.

**Type consistency.** Field names used by the view generator (`timerRoot`, `timerText`, `priceBeforeSaleRoot`, `priceBeforeSaleText`, `resourceAreaRoot`, `resourceItemTemplate`, `grandPrizeRoot/Image/Text`, `milestoneBarRoot`, `milestoneFill`, `milestoneMarkersRoot`, `milestoneMarkerTemplate`, `milestoneMainButton(Label)`, `missionListRoot`, `missionRowTemplate`, `missionBarRoot`, `missionBarFill`, `dimmer`, `panel`) match the Task 4 table and the `_node(...)` calls; `field_type` values match the builder's `Resolve` switch and `_cs_type` mapping; `KinoaInAppItemView` method names match between Task 5 (class) and Task 7 (callers); SDK signatures were verified against `E:\Dev\kinoa-sdk\KinoaSDK\KinoaCore` (`Response<T>.Data/IsSuccessful()/Error`, `CollectMilestonesAsync(InAppMessage, List<uint>)` 0-based, `CollectMissionsProgressAsync(message, int, List<int>)`, `InAppMilestoneStep` in `Kinoa.Data.Messaging.InApp.Features`, enums in `Kinoa.Data.Enum`, `InAppStorePackages` in `Kinoa.Data.Messaging.InApp`, `Kinoa.Time.GetUnixTime()`).

**Known limits stated in the plan:** generated view does not inherit the game's popup base class (reported instead); milestone/mission reward granting is a TODO by design (same boundary the SDK skill draws around `GrantRewards`); the Python `%`-formatted C# blocks must not gain a literal `%`.
