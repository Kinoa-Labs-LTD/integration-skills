# In-app → Prefab: Missions Feature Implementation Plan

> **Integration note (2026-10-28).** This plan was written and executed against release 1.1.0 and then integrated on top of the milestone feature (`2026-10-28-inapp-prefab-milestone-feature.md`). It is kept as history; where it disagrees with the code, the code and `references/*.md` win. Two decisions changed in the integration: **D9** — `ProgressBarState` is no longer a bar with a fill and `KinoaInAppItemView` markers (`MissionBar` / `MissionBarFill` / `MissionBarMarkers` / `MissionBarMarker`); it is the milestone ladder (`MissionBarScroll` → `MissionBarViewport` → `MissionBarContent` → `MissionBarStep`, one `KinoaInAppMilestoneStepView` per step by `MilestoneNumber`), and a step claims through the milestone click resolver (close → close, free → `CollectMissionsMilestonesProgress`, paid / ad / link → `KinoaInAppFeatureHooks.RunButtonAction` must return true first; Collect all milestones uses the milestone collect-all rule). **Task 5** — the mission list uses the builder's single scroll chain (`scroll` → `viewport` → `scroll_content`, wired by `WireScrollRects`) with `scroll_axis: "vertical"`; there is no `list_content` binding. The golden view files were re-rendered from the milestone base (6d5deb8).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kinoa-inapp-template-to-prefab` renders a `featureType: mission` template as a full missions pop-up:

- one tab per mission set;
- a scrollable list of mission cards carrying every piece of mission data, each with a dismiss (×) button;
- the combined `ProgressBarState`, rendered and claimed the same way as the milestone feature;
- Reach all, Collect all and Collect all milestones buttons, wired only when the template declares them.

Geometry and colours of the missions UI come from the template's tip image.

**Architecture:** Two skills change.

1. `kinoa-inapp-template-from-image`. Its vision pass (paths A and B) also bounds the missions UI parts (tabs, task list, one representative card and the card's inner parts, combined bar) and samples their colours. The layout artifact carries these as optional `feature.parts` / `feature.row_parts` / `feature.style`, and moves to schema `1.1`, an additive change.
2. `kinoa-inapp-template-to-prefab`.
   - The planner reads that geometry into a mission node tree. The card and tab interiors become plan nodes, positioned and coloured from the artifact. Neutral defaults apply when the artifact has none.
   - Two new user-owned shared views bind the card and tab.
   - The tool-owned Editor builder gains generic bindings plus a wiring pass.
   - The view generator emits the missions logic.

All other in-app rules work as they do for regular in-apps: slots, zones, customs, click routing, hooks, the TODO markers and file ownership.

**Tech Stack:** Python 3 stdlib + `unittest`. Helpers are self-contained and print one JSON object per subcommand. Unity uGUI, with legacy `Text` or TMP through the `KinoaText` alias. Kinoa Unity SDK `Kinoa.Data.Messaging.InApp.Features.Missions` types and the `Kinoa.Messaging` mission calls. `mcp-unity` for the live check.

**Spec:** There is no spec file. The plan comes from two briefs, quoted verbatim.

1. *"create plan to implement missions feature inapp to prefab. for ProgressBarState use similar approach as for milestone feature. For missions it is more complex. Split sets for tabs, in set show missions with all information, you can take a look at MissionDialog code and prefab to use as default missions part look of a prefab. Reach all, collect all add only if such buttons is in template. All other rules same as for regular inapps."*
2. Review round 1: *"Default look should not be inherited from mission dialog prefab in terms of colors and proportion, better to look for a tip image. If needed adjust route b in template to image skill. reach all collect all - use your suggestion. … × button on a card (DeleteMissionsProgress) - add it, a 'collect all bar milestones' button add it if such button exist in template same ruling as in milestone template, and recolouring cards by status - do not add it."*

MissionDialog (`E:\Dev\kinoa-sdk\Assets\Scripts\Dialog\Missions\*.cs`) is the reference for **behaviour only**: which data a card shows, set and tab rules, and button visibility. It is not a reference for look. The data model is in `E:\Dev\kinoa-sdk\KinoaSDK\KinoaCore\Data\Messaging\InApp\Features\Missions\*.cs`. The mission calls are in `Messaging.cs:228-320`.

## Decisions (confirm at review)

| # | Decision |
|---|---|
| D1 | **Feature-action buttons**, detected on `featureType == "mission"` only. Compact a template button's `key`, then its `name`, with `re.sub(r"[^a-z0-9]", "", s.lower())`. Check the rules in this order:<br>1. Contains `collectall` or `claimall`, **and** `milestone`, `bar` or `progress` → `collect_all_milestones`.<br>2. Contains `collectall` or `claimall` → `collect_all`.<br>3. Contains `reachall` → `reach_all`.<br>4. Otherwise it is an ordinary button.<br>When two buttons match the same action, the lower `index` wins and the other stays ordinary with a warning. "Same ruling as milestone" is read as: the button exists only when the template declares it, and it is detected by the same rule as the other two. |
| D2 | **Feature-action buttons bypass `KinoaUiService` routing.** They keep the slot's label and background, and they send `in_app_click` and raise `ButtonClicked`. Then they run their mission call. They are never routed through `ClickConfig`: routing a `collect_resource` config would consume the in-app's eligibility and grant the button's own resources. |
| D3 | Feature-action buttons do not count toward `_wanted_zones`. A `collect_all` with `collect_resource` must not create a `ResourceArea`. |
| D4 | **Tabs:** one tab per set that has at least one non-dismissed `ActiveMissions` entry.<br>• Order and labels: `PreviousSetProgress` first, labelled `Set {n} (prev)`, then `ActiveSetProgress`, labelled `Set {n}`.<br>• After a rebind the selected set stays selected while it is still present; otherwise the active set is selected. |
| D5 | **Card order:** `Reached`, then `Active`, then `Collected`, then anything else; within each group, by `PlacementNumber`. |
| D6 | **Card content:**<br>• placement badge `P{PlacementNumber}`<br>• `MissionText`, shown as-is<br>• `Sub-mission {n}`, hidden when null<br>• status name<br>• progress fill with `{CurrentScore}/{GoalScore}`<br>• reward items from `ProcessedResources`: icon from `ResolveResourceIcon`, plus the amount<br>• action button<br>• dismiss button<br>There is **no status-based recolouring**: colours come from the tip image and stay fixed. |
| D7 | **Card action:**<br>• `Reached` with `CompletionCta != null`: label `Collect`; calls `CollectMissionsProgressAsync` for that row, then `Bind(response.Data)`. The confirmed-collect point carries a `TODO(kinoa-prefab)` naming `mission.CompletionCta` and `mission.ProcessedResources`.<br>• `Active` with `ProgressionCta != null`: label `Go`; raises `MissionCtaClicked` and leaves a `TODO(kinoa-prefab)` plus a warning. The facade cannot route per-row CTAs because they are not template buttons.<br>• Anything else: the action is hidden. |
| D8 | **Card dismiss (×)**, with MissionDialog's rule:<br>• Visible when the row is `Reached` or `Collected`.<br>• Calls `Kinoa.Messaging.DeleteMissionsProgress(Message, setNumber, [row])`, which returns a plain `Response` with no refreshed in-app.<br>• On success the view records `(setNumber, rowNumber)` in `_dismissedRows` and re-renders the set. Dismissed rows are filtered out of cards, tabs and Reach all. |
| D9 | **ProgressBarState works like milestones.**<br>• `MissionBar` gets a fill (`TotalScore / max(step.Score)`), a marker strip, and one `KinoaInAppItemView` marker per step, ordered by `MilestoneNumber`.<br>• Each marker shows the score as its label, the status as its value, and the first reward's icon.<br>• A `Reached` marker claims through `CollectMissionsMilestonesProgress(Message, ActiveSetProgress.SetNumber, [step.RowNumber])`. That call returns results, not a refreshed in-app, so collected rows go into `_collectedBarRows` and the view rebinds.<br>• Built only when `progressBar.display != "dont_show_at_all"`. |
| D10 | **Reach all / Collect all act on the displayed set.**<br>• Collect all is visible only when the set has a `Reached` row; Reach all only when it has a non-dismissed `Active` row.<br>• Collect all milestones is visible while the bar has steps, and interactable only when a `Reached` step has not been collected yet.<br>• Calls: `CollectMissionsProgressAsync` / `ReachMissionsProgress` then `Bind(response.Data)`, and `CollectMissionsMilestonesProgress` for every claimable step.<br>• While any mission call is in flight, every mission control is disabled; it is re-enabled on failure. |
| D11 | **Look comes from the tip image.**<br>• The from-image vision pass bounds `parts` (tabs, one tab, task list, one representative card, combined bar). It also bounds that card's `row_parts` and samples `style` colours as `#RRGGBB`.<br>• The prefab planner turns these into anchors, sizes and `color` on plan nodes.<br>• When the artifact has none of this (an older artifact, or a part that is not visible), it falls back to **neutral defaults**, not MissionDialog: generic proportions in the tables below, white text, translucent white panels, as `KinoaInAppItemView` already uses. `report.mission_geometry` names every defaulted part, and the hand-off offers path B to fix it.<br>• MissionDialog's colours and proportions are used nowhere. |
| D12 | **Shared files:** `Shared/KinoaInAppMissionRowView.cs` and `Shared/KinoaInAppTabView.cs` are user-owned and written only when absent. They are written on **every** `generate`, whatever the feature type, because the always-refreshed builder references their types. |

## Global Constraints

- Helpers are self-contained: stdlib only, no network, no sibling imports, one JSON object per subcommand, exit `0`/`2`. Run `python -m unittest discover tests` after every helper change.
- Generated C# never contains `dashboard.kinoa.io`, `Bearer`, `UnityWebRequest` or `Addressables.Load` (`FORBIDDEN_IN_GENERATED`). Every open item is one `// TODO(kinoa-prefab): …` line.
- File ownership is unchanged:
  - the view and the plan copy are tool-owned (`--overwrite`);
  - `Editor/KinoaInAppPrefabBuilder.cs` is always rewritten;
  - `Shared/*` is user-owned: written when absent, rewritten only with `--force-shared`.
- **Backward compatibility** (memory: *extend, not rewrite*):
  - Standard and milestone views stay byte-identical; a golden test pins this.
  - A layout artifact `1.0` stays valid in both skills.
  - Re-generating in a project with old `Shared/` files must compile.
- The layout artifact goes `1.0` → `1.1`, and the change is additive (`feature.parts` / `row_parts` / `style`). The prefab `plan` `schema_version` stays `"1.0"`; it adds the node fields `feature_action` and `color` and `report.mission_actions` / `report.mission_geometry`.
- The mission `parts` / `row_parts` / `style` are **never template elements**. They feed geometry only, like `area_bbox`; a card is a feature-layer instance, not a slot.
- No version bump and no `plugin.json` edit; bumps happen in the release PR.

## Review Focus

1. **Older artifact or partial geometry.** This covers an artifact `1.0` with only `area_bbox`, `row_parts` without `parts.row`, or an invalid colour. Expected: neutral defaults for exactly the missing parts, each named in `report.mission_geometry.defaulted`, with no refusal. Pinned in Task 3: `test_mission_geometry_falls_back_per_part` and `test_invalid_part_and_colour_degrade_with_warning`.
2. **Partial mission state at runtime.** This covers no previous set, a null active set, empty `ActiveMissions`, a null or empty `ProgressBarState`, or every row dismissed. Expected: render what exists, never throw. Pinned in Task 6 by `test_mission_view_null_guards`. These are text guards only: Task 8 proves compile and build, not live data.
3. **Near-miss button names**, such as `collect_button`, `collect_resources`, `Collect` or `reach_level`. These must stay ordinary buttons routed through the facade. A "Collect all milestones" button must not be taken for Collect all. Pinned in Task 2: `test_mission_action_detection`.
4. **A collect or dismiss that empties the selected set.** Selection must fall back to the active set, not to an empty list. Pinned in Task 6: `test_mission_view_tabs_and_selection`.
5. **Existing project with kept legacy `Shared/` files.** The new shared files must be written next to the kept ones, and they must go through the `shared_text_system_mismatch` guard. Pinned in Task 4: `test_generate_writes_new_shared_files_next_to_kept_ones` and `test_mismatch_guard_covers_mission_shared_files`.

---

## File Structure

- `plugin/skills/kinoa-inapp-template-from-image/`:
  - `inapp_template_build.py`: `cmd_schema`, `build_layout`, `validate_layout`, `LAYOUT_SCHEMA_VERSION`;
  - `SKILL.md`: the Phase 2 missions geometry paragraph, and a path B note;
  - `references/layout-artifact.md`.
- `plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py`:
  - planner: `mission_action`, `_wanted_zones`, `_node`, `layout_from_artifact`, `plan_prefab` panel union, `_add_feature`, reserved names, containers and defaults;
  - shared renderers, `generate_code`, `cmd_generate`;
  - `BUILDER_CS`;
  - view generator: `_bind_calls`, `_fields_block`, `render_view`, `render_zone_methods`, `render_feature_methods` + the `_MISSION_*_CS` blocks.
- New fixtures in `plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/missions/`: `template_missions.json` and `daily_missions.layout.json`.
- Tests: `tests/test_inapp_template_build.py`, `tests/test_inapp_prefab_plan.py`, `tests/test_inapp_prefab_codegen.py`, `tests/golden/`.
- Docs:
  - prefab `references/prefab-plan-schema.md` and `references/generated-code-contract.md`, plus `SKILL.md`;
  - `docs/inapp-template-to-prefab-guide.md` and `docs/inapp-template-generation-guide.md`;
  - `CLAUDE.md` and `CHANGELOG.md`.

---

### Task 1: From-image — missions geometry in the analysis and the layout artifact (schema 1.1)

**Files:**
- Modify: `plugin/skills/kinoa-inapp-template-from-image/inapp_template_build.py` (`LAYOUT_SCHEMA_VERSION` ~1050, `build_layout` ~1076, `validate_layout` ~1191, `cmd_schema` ~1436)
- Modify: `plugin/skills/kinoa-inapp-template-from-image/SKILL.md` (Phase 2 "Picking the feature type" ~194; path B step 3 ~425)
- Modify: `plugin/skills/kinoa-inapp-template-from-image/references/layout-artifact.md`
- Test: `tests/test_inapp_template_build.py` (beside `test_area_bbox_feeds_feature_when_valid` ~1061)

**Interfaces:**
- Analysis input, mission only, all optional. Every bbox is normalized to the image with a top-left origin.
  - `feature.detected.parts`: a dict with the keys `tabs`, `tab`, `task_list`, `row`, `progress_bar` → bbox.
  - `feature.detected.row_parts`: a dict with the keys `placement_badge`, `title`, `sub_mission`, `status`, `progress_track`, `progress_text`, `rewards`, `action_button`, `dismiss_button` → bbox. These describe the same card as `parts.row`.
  - `feature.detected.style`: a dict with the keys `card`, `card_text`, `accent`, `progress_track`, `progress_fill`, `action`, `dismiss`, `tab_text`, `tab_selected`, `bar_track`, `bar_fill` → `#RRGGBB` or `#RRGGBBAA`.
- Produces: the artifact `feature` gains `parts`, `row_parts` and `style` with the same keys, each present only when non-empty after validation. Module constants `MISSION_PARTS`, `MISSION_ROW_PARTS`, `MISSION_STYLE_KEYS` (tuples, the key orders above) and `LAYOUT_SCHEMA_VERSION = "1.1"`.
- Validation is advisory, the same as `area_bbox`:
  - An invalid bbox (`_bbox_problems` error), an invalid colour (not `^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$`) or an unknown key is **dropped with a warning naming it**.
  - `row_parts` without a valid `parts.row` are all dropped, with one warning.
  - `featureType != "mission"` ⇒ the three blocks are ignored, with a warning when present.
- `validate_layout` accepts `schema_version` `"1.0"` and `"1.1"` without a warning.

- [ ] **Step 1: Write the failing tests.**

```python
def _mission_ana(self, **detected):
    ana = copy.deepcopy(self.ana)
    ana["feature"] = {"type": "mission", "detected": dict({"area_bbox": {"x": 0.05, "y": 0.3, "w": 0.9, "h": 0.6}}, **detected)}
    return ana

def test_mission_parts_row_parts_and_style_reach_the_artifact(self):
    ana = self._mission_ana(parts={"tabs": {"x": 0.05, "y": 0.25, "w": 0.9, "h": 0.05},
                                   "row": {"x": 0.05, "y": 0.32, "w": 0.9, "h": 0.12}},
                            row_parts={"title": {"x": 0.12, "y": 0.33, "w": 0.5, "h": 0.04}},
                            style={"card": "#1E2A44", "progress_fill": "#3FD07A"})
    payload, report = build_mod.build_payload(ana)
    layout, rep = build_mod.build_layout(payload, _geometry_for(payload, report), ana)
    self.assertEqual(layout["schema_version"], "1.1")
    self.assertEqual(set(layout["feature"]["parts"]), {"tabs", "row"})
    self.assertEqual(layout["feature"]["row_parts"]["title"], {"x": 0.12, "y": 0.33, "w": 0.5, "h": 0.04})
    self.assertEqual(layout["feature"]["style"], {"card": "#1E2A44", "progress_fill": "#3FD07A"})
    self.assertEqual(rep["errors"], [])

def test_bad_mission_geometry_is_dropped_with_named_warnings(self):
    ana = self._mission_ana(parts={"tabs": {"x": 2, "y": 0, "w": 1, "h": 1}, "shelf": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}},
                            row_parts={"title": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}},
                            style={"card": "navy", "glow": "#FFFFFF"})
    payload, report = build_mod.build_payload(ana)
    layout, rep = build_mod.build_layout(payload, _geometry_for(payload, report), ana)
    for gone in ("parts", "row_parts", "style"):
        self.assertNotIn(gone, layout["feature"])
    for name in ("parts.tabs", "parts.shelf", "row_parts", "style.card", "style.glow"):
        self.assertTrue(any(name in w for w in rep["warnings"]), name)

def test_mission_geometry_ignored_on_other_feature_types(self):
    ana = copy.deepcopy(self.ana)
    ana["feature"] = {"type": "milestone", "detected": {"parts": {"row": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.1}}}}
    payload, report = build_mod.build_payload(ana)
    layout, rep = build_mod.build_layout(payload, _geometry_for(payload, report), ana)
    self.assertNotIn("parts", layout["feature"])
    self.assertTrue(any("mission" in w and "parts" in w for w in rep["warnings"]))

def test_validate_accepts_layout_1_0_and_1_1(self):
    # build any valid layout, set schema_version to "1.0" then "1.1"; validate_layout(...)["warnings"]
    # contains no "schema_version" entry in either case.
```

  Also test `cmd_schema`: its `shape.feature.detected` documents `parts`, `row_parts` and `style`.

- [ ] **Step 2: Run them and confirm they fail.** Run `python -m unittest tests.test_inapp_template_build -v`. Expected: the four new tests FAIL. The existing `test_layout_*` / `schema_version` tests still pass, because they compare against the constant.

- [ ] **Step 3: Implement** the interface above in `build_layout` (after the `area_bbox` block), `validate_layout` and `cmd_schema`. Then update the docs:
  - `layout-artifact.md`: add a `feature` example with all three blocks, a "Missions geometry" semantics paragraph (advisory, never template elements, card colours approximate), and a schema history line (`1.1` adds them additively).
  - `SKILL.md` Phase 2, after the mission counting sentence: *"For `mission` also bound, when visible, the tab strip and one tab, the task list, **one representative card** (the first fully visible one) and the combined bar into `detected.parts`. Bound that same card's inner parts into `detected.row_parts`, and sample their colours as `#RRGGBB` into `detected.style`. Omit anything not visible; never invent. These are geometry for the prefab skill, never template elements."*
  - Path B step 3: *"(includes the missions geometry above — the prefab skill builds the missions UI from it)"*.

- [ ] **Step 4: Run the suite and confirm it passes.** Run `python -m unittest discover tests`. Expected: OK.

- [ ] **Step 5: Commit.** Run `git commit -am "feat(from-image): missions UI geometry and colours in the layout artifact (schema 1.1)"`.

---

### Task 2: Prefab planner — detect the feature-action buttons

**Files:**
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/missions/template_missions.json`
- Modify: `inapp_prefab_plan.py` (`_node` ~436, `_wanted_zones` ~748, `_add_feature` ~829)
- Test: `tests/test_inapp_prefab_plan.py` (new `class TestMissionActions`, which loads the fixture as `MISSIONS`)

**Interfaces:**
- Produces:
  - `mission_action(button: dict) -> str | None`, returning `"reach_all"`, `"collect_all"`, `"collect_all_milestones"` or `None` (D1).
  - Every node gains `"feature_action"` (new kwarg `_node(..., feature_action=None)`).
  - Mission plans get `report["mission_actions"] = {"reach_all": key|None, "collect_all": key|None, "collect_all_milestones": key|None}`.

- [ ] **Step 1: Create the fixture.** Copy `evals/fixtures/one-cta/template_one_cta.json`, then set:
  - `key: "daily_missions"`, `name: "Daily Missions"`, `featureType: "mission"`;
  - `features.mission` = `{key: "missions", name: "Missions", progressBar: {display: "show_for_all_sets_combined", completionBarCta: ["collect_resource"]}, completionCta: ["collect_resource"], activeProgressCta: ["deep_link"], maxPlacements: 10, maxSetsCount: 7, minPlacements: 1, minSetsCount: 1}`;
  - `buttons`: keep `close_button` (index 0) and drop `cta_button`. Add three buttons, all `canBeHidden: true`:

| key | name | index | clickActionType |
|---|---|---|---|
| `collect_all_button` | Collect All | 8 | `["collect_resource"]` |
| `reach_all_button` | Reach All | 9 | `["deep_link"]` |
| `collect_all_milestones_button` | Collect All Milestones | 10 | `["collect_resource"]` |

- [ ] **Step 2: Write the failing tests.**

```python
def test_mission_action_detection(self):
    f = mod.mission_action
    self.assertEqual(f({"key": "collect_all_button", "name": "x"}), "collect_all")
    self.assertEqual(f({"key": "btn_1", "name": "Claim All"}), "collect_all")
    self.assertEqual(f({"key": "reachAll", "name": ""}), "reach_all")
    self.assertEqual(f({"key": "collect_all_milestones", "name": ""}), "collect_all_milestones")
    self.assertEqual(f({"key": "btn_2", "name": "Claim all bar rewards"}), "collect_all_milestones")
    for key, name in (("collect_button", "Collect"), ("collect_resources", "Collect resources"),
                      ("reach_level", "Reach level"), ("cta_button", "CTA")):
        self.assertIsNone(f({"key": key, "name": name}), key)

def test_feature_actions_marked_and_reported(self):
    plan = mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]
    self.assertEqual(_node(plan, "CollectAllButton")["feature_action"], "collect_all")
    self.assertEqual(_node(plan, "ReachAllButton")["feature_action"], "reach_all")
    self.assertEqual(_node(plan, "CollectAllMilestonesButton")["feature_action"], "collect_all_milestones")
    self.assertIsNone(_node(plan, "CloseButton")["feature_action"])
    self.assertEqual(plan["report"]["mission_actions"], {"reach_all": "reach_all_button", "collect_all": "collect_all_button",
                                                         "collect_all_milestones": "collect_all_milestones_button"})

def test_feature_actions_only_on_mission_templates(self):
    t = copy.deepcopy(MISSIONS); t["featureType"] = "standard"; t["features"] = {}
    plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
    self.assertIsNone(_node(plan, "CollectAllButton")["feature_action"])
    self.assertNotIn("mission_actions", plan["report"])

def test_duplicate_feature_action_keeps_lowest_index(self):
    t = copy.deepcopy(MISSIONS)
    t["buttons"].append({"key": "claim_all", "name": "Claim all", "index": 12, "canBeHidden": True,
                         "customFields": [], "clickActionType": ["collect_resource"]})
    plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
    self.assertEqual(plan["report"]["mission_actions"]["collect_all"], "collect_all_button")
    self.assertIsNone(_node(plan, "ClaimAllButton")["feature_action"])
    self.assertTrue(any("claim_all" in w and "collect_all" in w for w in plan["report"]["warnings"]))

def test_feature_action_buttons_do_not_request_zones(self):
    self.assertNotIn("resource_area", mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]["report"]["client_zones"])

def test_collect_all_milestones_needs_a_bar(self):
    t = copy.deepcopy(MISSIONS); t["features"]["mission"]["progressBar"] = {"display": "dont_show_at_all"}
    plan = mod.plan_prefab(t, None, STYLE, {})["plan"]
    self.assertIsNone(plan["report"]["mission_actions"]["collect_all_milestones"])
    self.assertTrue(any("collect_all_milestones_button" in w and "progress bar" in w for w in plan["report"]["warnings"]))
```

- [ ] **Step 3: Run them and confirm they fail.** Run `python -m unittest tests.test_inapp_prefab_plan.TestMissionActions -v`. Expected: FAIL / ERROR.

- [ ] **Step 4: Implement.**
  - `mission_action` follows D1.
  - `_node(..., feature_action=None)` adds `"feature_action"` to every node dict.
  - `_wanted_zones` skips buttons that match on mission templates.
  - In the `_add_feature` mission branch:
    - Walk the `buttons` nodes in template `index` order and set `feature_action` on the first match per action.
    - Warn on duplicates: `"button '%s' also looks like %s; only '%s' is wired — it stays an ordinary button"`.
    - A `collect_all_milestones` match on a template without a bar stays ordinary, with the warning `"button '%s' looks like collect_all_milestones but the template has no progress bar — it stays an ordinary button"`.
    - Write `report["mission_actions"]`.

- [ ] **Step 5: Run the suite and confirm it passes.** Run `python -m unittest discover tests`. Expected: OK.

- [ ] **Step 6: Commit.** Run `git add` on the fixture, helper and test, then `git commit -m "feat(prefab): detect mission reach/collect-all and collect-all-milestones template buttons"`.

---

### Task 3: Prefab planner — mission node tree from the artifact's geometry

**Files:**
- Modify: `inapp_prefab_plan.py`:
  - `layout_from_artifact` ~1185
  - `plan_prefab` panel union ~554
  - `_add_feature` mission branch ~850
  - `RESERVED_*` ~236
  - `_ZONE_DEFAULT_ANCHORS` ~726
  - `_CONTAINERS` / `_INFLATE` ~878
  - `_node`: add `color=None`
- Create: `plugin/skills/kinoa-inapp-template-to-prefab/evals/fixtures/missions/daily_missions.layout.json`. It is an artifact `1.1` for the Task 2 fixture: the `close_button` and three action-button bboxes, `feature.area_bbox`, every `parts`, `row_parts` and `style` key, and `source_image` 1080×1920.
- Test: `tests/test_inapp_prefab_plan.py` (update `test_mission_nodes_with_and_without_bar` ~378 and `test_mission_area_bbox_places_the_task_list` ~607)

**Interfaces:**
- Consumes: the Task 1 artifact keys and the Task 2 `feature_action`.
- `layout_from_artifact` also returns `feature_parts`, `feature_row_parts` and `feature_style`.
  - A bad bbox or colour is dropped, with a warning in `layout["warnings"]`. These blocks never refuse the artifact, unlike `area_bbox`, which still refuses.
  - All three are used only when `feature_type` matches the template's.
- New node field `"color"`: a hex string or `None`. Every node dict carries it.
- `report["mission_geometry"] = {"source": "layout_artifact" | "defaults", "parts": [...], "row_parts": [...], "style": [...], "defaulted": [node names]}`.
- Node tree:
  - Panel-level nodes are positioned by `anchors_from_bbox(part, panel_bbox)`.
  - Card children: `anchors_from_bbox(row_part, parts.row)`.
  - Sizes in px: `[round(bbox.w * frame_w, 1), round(bbox.h * frame_h, 1)]`.
  - Layout warnings already reach `report.warnings` through `_check_artifact_join` (`report["warnings"].extend(layout["warnings"])`).
  - Card-child nodes have `field = None`. Their `role` names the `[SerializeField]` in the shared view (Task 4), and the builder's wiring pass (Task 5) assigns them.

| Node | Parent | binding | components | field / field_type · role | geometry source → neutral default | color |
|---|---|---|---|---|---|---|
| `MissionTabs` | Panel | `zone` | `HorizontalLayoutGroup` | `missionTabsRoot` / `RectTransform` | `parts.tabs` → `([0.05,0.76],[0.95,0.81])` | — |
| `MissionTab` | MissionTabs | `tab_template` | `Image`, `Button` | `missionTabTemplate` / `KinoaInAppTabView` | size from `parts.tab` → `[300,60]`; inactive | `#00000000` |
| `MissionTabLabel` | MissionTab | `tab_part` | `Text` | role `label` · `Text` | `([0,0.15],[1,1])` | `style.tab_text` |
| `MissionTabSelected` | MissionTab | `tab_part` | `Image` | role `selectedMarker` · `GameObject` | `([0.3,0],[0.7,0.06])` | `style.tab_selected` |
| `MissionList` | Panel | `zone` | `[]` (was `VerticalLayoutGroup`) | `missionListRoot` / `RectTransform` | `parts.task_list` → `area_bbox` → default `mission_list` | — |
| `MissionViewport` | MissionList | `scroll` | `[]` | `missionScroll` / `ScrollRect` | stretch | — |
| `MissionRows` | MissionViewport | `list_content` | `VerticalLayoutGroup` | `missionRowsRoot` / `RectTransform` | `([0,1],[1,1])` | — |
| `MissionRow` | MissionRows | `mission_row_template` | `Image` | `missionRowTemplate` / `KinoaInAppMissionRowView` | size from `parts.row` → `[900,180]`; inactive | `style.card` |
| `MissionRowPlacement` | MissionRow | `row_part` | `Image` | — | `row_parts.placement_badge` → `([0.02,0.6],[0.08,0.9])` | `style.accent` |
| `MissionRowPlacementText` | MissionRowPlacement | `row_part` | `Text` | role `placementText` · `Text` | stretch | `style.card_text` |
| `MissionRowTitle` | MissionRow | `row_part` | `Text` | role `titleText` · `Text` | `title` → `([0.1,0.66],[0.75,0.95])` | `style.card_text` |
| `MissionRowSubMission` | MissionRow | `row_part` | `Text` | role `subMissionText` · `Text` | `sub_mission` → `([0.1,0.5],[0.75,0.66])` | `style.card_text` |
| `MissionRowStatus` | MissionRow | `row_part` | `Text` | role `statusText` · `Text` | `status` → `([0.77,0.66],[0.9,0.95])` | `style.card_text` |
| `MissionRowDismiss` | MissionRow | `row_part` | `Image`, `Button` | role `dismissButton` · `Button` | `dismiss_button` → `([0.92,0.72],[0.98,0.95])` | `style.dismiss` |
| `MissionRowDismissLabel` | MissionRowDismiss | `row_part` | `Text` | role `dismissLabel` · `Text` | stretch | `style.card_text` |
| `MissionRowProgress` | MissionRow | `row_part` | `Image` | — | `progress_track` → `([0.1,0.36],[0.75,0.46])` | `style.progress_track` |
| `MissionRowProgressFill` | MissionRowProgress | `fill` | `Image` | role `progressFill` · `Image` | stretch | `style.progress_fill` |
| `MissionRowProgressText` | MissionRow | `row_part` | `Text` | role `progressText` · `Text` | `progress_text` → `([0.77,0.32],[0.9,0.5])` | `style.card_text` |
| `MissionRowRewards` | MissionRow | `row_part` | `HorizontalLayoutGroup` | role `rewardsRoot` · `RectTransform` | `rewards` → `([0.1,0.05],[0.7,0.3])` | — |
| `MissionRowReward` | MissionRowRewards | `item_template` | `[]` | role `rewardTemplate` · `KinoaInAppItemView` | size `[140,48]`; inactive | — |
| `MissionRowAction` | MissionRow | `row_part` | `Image`, `Button` | role `actionButton` · `Button` | `action_button` → `([0.75,0.05],[0.98,0.3])` | `style.action` |
| `MissionRowActionLabel` | MissionRowAction | `row_part` | `Text` | role `actionLabel` · `Text` | stretch | `style.card_text` |
| `MissionBar` | Panel | `zone` | `Image` | `missionBarRoot` / `GameObject` | `parts.progress_bar` → `([0.1,0.86],[0.9,0.89])` | `style.bar_track` |
| `MissionBarFill` | MissionBar | `fill` | `Image` | `missionBarFill` / `Image` | stretch | `style.bar_fill` |
| `MissionBarMarkers` | MissionBar | `markers` | `HorizontalLayoutGroup` | `missionBarMarkersRoot` / `RectTransform` | `([0,-1],[1,2])` | — |
| `MissionBarMarker` | MissionBarMarkers | `item_template` | `[]` | `missionBarMarkerTemplate` / `KinoaInAppItemView` | size `[120,120]`; inactive | — |

  The `MissionBar*` nodes are built only when `display != "dont_show_at_all"`.

  The card-child defaults in the table are the neutral fallback (D11). They are not taken from MissionDialog.

- [ ] **Step 1: Write the failing tests** (`ART` = the new layout fixture loaded via `mod.layout_from_artifact`):

```python
def test_mission_node_tree_shape(self):
    plan = mod.plan_prefab(MISSIONS, None, STYLE, {})["plan"]
    for name, parent, binding in (("MissionTabs", "Panel", "zone"), ("MissionTab", "MissionTabs", "tab_template"),
                                  ("MissionViewport", "MissionList", "scroll"), ("MissionRows", "MissionViewport", "list_content"),
                                  ("MissionRow", "MissionRows", "mission_row_template"), ("MissionRowDismiss", "MissionRow", "row_part"),
                                  ("MissionRowReward", "MissionRowRewards", "item_template"),
                                  ("MissionBarMarker", "MissionBarMarkers", "item_template")):
        n = _node(plan, name)
        self.assertEqual((n["parent"], n["binding"]), (parent, binding), name)
    self.assertEqual(_node(plan, "MissionRowTitle")["role"], "titleText")
    self.assertIsNone(_node(plan, "MissionRowTitle")["field"])
    names = [n["name"] for n in plan["nodes"]]
    self.assertTrue(all(names.index(n["parent"]) < names.index(n["name"]) for n in plan["nodes"] if n["parent"]))
    self.assertTrue({"MissionTabs", "MissionBar"} <= set(mod._CONTAINERS))
    self.assertEqual(plan["report"]["mission_geometry"]["source"], "defaults")

def test_mission_geometry_from_artifact(self):
    plan = mod.plan_prefab(MISSIONS, ART, STYLE, {})["plan"]
    feat = ART_RAW["feature"]
    close = lambda a, b: all(abs(x - y) < 1e-3 for x, y in zip(a, b))   # report.panel_bbox is rounded to 4 places
    self.assertTrue(close(_node(plan, "MissionList")["anchor_min"], mod.anchors_from_bbox(feat["parts"]["task_list"], plan["report"]["panel_bbox"])[0]))
    self.assertEqual(_node(plan, "MissionRowTitle")["anchor_min"], mod.anchors_from_bbox(feat["row_parts"]["title"], feat["parts"]["row"])[0])
    fw, fh = plan["ui"]["frame_size"]
    self.assertEqual(_node(plan, "MissionRow")["size"], [round(feat["parts"]["row"]["w"] * fw, 1), round(feat["parts"]["row"]["h"] * fh, 1)])
    self.assertEqual(_node(plan, "MissionRow")["color"], feat["style"]["card"])
    self.assertEqual(_node(plan, "MissionBarFill")["color"], feat["style"]["bar_fill"])
    self.assertEqual(plan["report"]["mission_geometry"]["defaulted"], [])

def test_mission_geometry_falls_back_per_part(self):
    art = copy.deepcopy(ART_RAW); del art["feature"]["row_parts"]["status"]; del art["feature"]["parts"]["tabs"]
    plan = mod.plan_prefab(MISSIONS, mod.layout_from_artifact(art), STYLE, {})["plan"]
    self.assertEqual(sorted(plan["report"]["mission_geometry"]["defaulted"]), ["MissionRowStatus", "MissionTabs"])
    self.assertEqual(_node(plan, "MissionRowStatus")["anchor_min"], [0.77, 0.66])

def test_invalid_part_and_colour_degrade_with_warning(self):
    art = copy.deepcopy(ART_RAW); art["feature"]["parts"]["row"] = {"x": 2, "y": 0, "w": 1, "h": 1}; art["feature"]["style"]["card"] = "blue"
    layout = mod.layout_from_artifact(art)          # must not raise
    plan = mod.plan_prefab(MISSIONS, layout, STYLE, {})["plan"]
    self.assertIsNone(_node(plan, "MissionRow")["color"])
    self.assertIn("MissionRow", plan["report"]["mission_geometry"]["defaulted"])
    self.assertTrue(any("parts.row" in w for w in plan["report"]["warnings"]))

def test_artifact_1_0_with_area_only_still_places_the_list(self):
    # existing test_mission_area_bbox_places_the_task_list keeps passing unchanged
```

- [ ] **Step 2: Run them and confirm they fail.** Run `python -m unittest tests.test_inapp_prefab_plan -v`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** the table and the interface.
  - Add the `parts` boxes in use to `used_boxes` for the panel union.
  - Add every new name to the `RESERVED_*` sets (Panel-level nodes and fields only; card children are scoped under `MissionRow`, but reserve them anyway so a slot named `MissionRowTitle` cannot clash).
  - Set `_ZONE_DEFAULT_ANCHORS["mission_tabs"]`, and set `mission_bar` to the values in the table.
  - Add `MissionTabs` and `MissionBar` to `_CONTAINERS`, and set `_INFLATE["MissionBar"] = 1.0`.
  - Card children are not flow nodes: their parent is not Panel, so de-overlap ignores them.

- [ ] **Step 4: Run the suite and confirm it passes.** Run `python -m unittest discover tests`. Expected: OK. If a de-overlap test such as `test_mission_and_milestone_estimates_do_not_overlap_silently` changes outcome because of the new defaults, keep its intent and update only the asserted anchors.

- [ ] **Step 5: Commit.** Run `git add` on the helper, the fixture and the test, then `git commit -m "feat(prefab): mission tabs, scroll list, card and bar nodes positioned and coloured from the layout artifact"`.

---

### Task 4: Shared runtime views `KinoaInAppMissionRowView` + `KinoaInAppTabView`

**Files:**
- Modify: `inapp_prefab_plan.py`:
  - new `render_mission_row_view` / `render_tab_view` beside `render_item_view` ~1370
  - `generate_code` ~1822
  - `cmd_generate` `user_owned` ~2510
  - `--force-shared` help ~2627
- Test: `tests/test_inapp_prefab_codegen.py`

**Interfaces:**
- Produces C# in `namespace Kinoa.InApps`. The `[SerializeField]` names equal the Task 3 `role`s.

```
public class KinoaInAppMissionRowView : MonoBehaviour
  fields: KinoaText placementText, titleText, subMissionText, statusText, progressText, actionLabel, dismissLabel;
          Image progressFill; RectTransform rewardsRoot; KinoaInAppItemView rewardTemplate; Button actionButton, dismissButton
  void SetPlacement(int placementNumber)             // "P{n}"
  void SetTitle(string text)
  void SetSubMission(int? number)                    // "Sub-mission {n}"; hides subMissionText when null
  void SetStatus(string text)
  void SetProgress(decimal current, decimal goal)    // fillAmount = goal > 0 ? Clamp01(current/goal) : 0; "{current}/{goal}"
  KinoaInAppItemView AddReward(Sprite icon, string amount)
  void ClearRewards()                                // spawned rewards only, never the template
  void SetAction(string label, UnityAction onClick)  // null label ⇒ hides actionButton
  void SetDismiss(bool visible, UnityAction onClick) // sets dismissLabel to "×" when it is empty
  void SetInteractable(bool interactable)            // action + dismiss

public class KinoaInAppTabView : MonoBehaviour
  fields: KinoaText label; GameObject selectedMarker; Button button
  int SetNumber { get; }
  void Setup(int setNumber, string text, bool selected, UnityAction onClick)
  void SetSelected(bool selected)
  void SetInteractable(bool interactable)
```

- [ ] **Step 1: Write the failing tests.**

```python
def test_file_set(self):   # extend
    for path in (..., "Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs", "Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs"):
        self.assertIn(path, self.files)

def test_mission_shared_views_api(self):
    row = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs"]
    for sig in ("public void SetSubMission(int? number)", "public void SetProgress(decimal current, decimal goal)",
                "public KinoaInAppItemView AddReward(Sprite icon, string amount)",
                "public void SetAction(string label, UnityAction onClick)",
                "public void SetDismiss(bool visible, UnityAction onClick)",
                "[SerializeField] private Button dismissButton;", "[SerializeField] private KinoaInAppItemView rewardTemplate;"):
        self.assertIn(sig, row)
    tab = self.files["Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs"]
    self.assertIn("public void Setup(int setNumber, string text, bool selected, UnityAction onClick)", tab)
    self.assertIn("[SerializeField] private GameObject selectedMarker;", tab)
    for content in (row, tab):
        self.assertIn("using KinoaText = UnityEngine.UI.Text;", content)

def test_generate_writes_new_shared_files_next_to_kept_ones(self): ...
def test_mismatch_guard_covers_mission_shared_files(self): ...
```

  The last two reuse the temp-project scaffolding of the existing `generate` CLI tests. Find it with `grep -n "shared_text_system_mismatch" tests/test_inapp_prefab_codegen.py`.
  - First test: the old `KinoaInAppItemView.cs` and `KinoaInAppHooks.cs` are present ⇒ both new files appear in `written`, the old ones in `skipped`, exit 0.
  - Second test: only `KinoaInAppTabView.cs` is present with the TMP alias, and the plan is legacy ⇒ `error == "shared_text_system_mismatch"` on that path.

- [ ] **Step 2: Run them and confirm they fail.** Run `python -m unittest tests.test_inapp_prefab_codegen -v`. Expected: FAIL.

- [ ] **Step 3: Implement** the renderers, registering them in `generate_code` and in `user_owned`, and name all four shared files in the `--force-shared` help.

- [ ] **Step 4: Run the suite and confirm it passes.** Run `python -m unittest discover tests`. Expected: OK.

- [ ] **Step 5: Commit.** Run `git commit -am "feat(prefab): shared mission card and tab views (user-owned)"`.

---

### Task 5: Editor builder — generic bindings, node colours, view wiring pass

**Files:**
- Modify: `inapp_prefab_plan.py` → `BUILDER_CS` (`PlanNode` ~1451, `ApplyBinding` ~1704, `Resolve` ~1785, and the build loop that assigns fields)
- Test: `tests/test_inapp_prefab_codegen.py`

**Interfaces:**
- `PlanNode` gains `public string color; public string role;`. `role` already exists in the plan JSON; the builder now reads it.
- **Colour:** after the components are added, a non-empty `node.color` parsed with `ColorUtility.TryParseHtmlString` is applied to the node's `Image`, or else to its text component.
  - With no colour, the builder keeps today's defaults (white text, white `Image`).
  - `tab_template` and `mission_row_template` get the neutral `(1,1,1,0.15)` when they have no colour.
- **New `ApplyBinding` cases:**
  - `"scroll"`: `Image` `(0,0,0,0.01)`, `RectMask2D`, `ScrollRect` (`horizontal=false`, `vertical=true`, `Elastic`).
  - `"list_content"`: pivot `(0.5,1)` + `ContentSizeFitter.verticalFit = PreferredSize`.
  - `"tab_template"`: adds `KinoaInAppTabView` + `LayoutElement.preferredWidth = size.x`.
  - `"mission_row_template"`: adds `KinoaInAppMissionRowView` + `LayoutElement.preferredHeight = size.y`.
  - `"tab_part"` / `"row_part"`: graphics get `raycastTarget = false`, except on `Button` nodes.
- **Wiring pass**, after every node is built:
  - Set `ScrollRect.content` to its `list_content` child.
  - For each `tab_template` / `mission_row_template` node, `SetRef` every descendant node's `role` to `Resolve(go, field_type)` on the view component. For tabs, also `SetRef(so, "button", <root Button>)`.
  - An unresolved role appends `"<node>: role '<role>' not assigned"` to the build report's `errors`.
- `Resolve` gains `ScrollRect`, `KinoaInAppTabView`, `KinoaInAppMissionRowView`.

- [ ] **Step 1: Write the failing test.**

```python
def test_builder_knows_mission_bindings(self):
    b = mod.BUILDER_CS
    for s in ('case "scroll":', 'case "list_content":', 'case "tab_template":', 'case "mission_row_template":',
              'case "row_part":', 'case "tab_part":', "public string color;", "public string role;",
              "ColorUtility.TryParseHtmlString(node.color", "AddComponent<RectMask2D>()",
              "ContentSizeFitter.FitMode.PreferredSize", "scroll.content =", 'case "ScrollRect":',
              'case "KinoaInAppTabView":', 'case "KinoaInAppMissionRowView":', "not assigned"):
        self.assertIn(s, b)
    self.assertNotIn("MissionDialog", b)
```

- [ ] **Step 2: Run it and confirm it fails.** Run `python -m unittest tests.test_inapp_prefab_codegen -v`. Expected: FAIL.

- [ ] **Step 3: Implement** the interface above.

- [ ] **Step 4: Run the suite and confirm it passes.** Run `python -m unittest discover tests`. Expected: OK. The compile itself is proven in Task 8.

- [ ] **Step 5: Commit.** Run `git commit -am "feat(prefab): builder bindings, node colours and template wiring for missions"`.

---

### Task 6: View generator — the missions feature

**Files:**
- Modify: `inapp_prefab_plan.py`:
  - `_bind_calls` ~1864: skip nodes with `feature_action`
  - `_fields_block` ~1843: add a `("Missions", ("tab_template", "scroll", "list_content", "mission_row_template"))` group
  - `render_view` ~1892: on mission views, declare `MissionCtaClicked`, the mission state fields, and `using UnityEngine.Events;`
  - `render_zone_methods` ~2403: emit `ResolveIcon` when `ftype == "mission"` too, exactly once
  - replace `_MISSION_CS` / `_MISSION_BAR_CS` and `render_feature_methods` ~2352–2424
- Create: `tests/golden/one_cta_view.cs.txt`, `tests/golden/milestone_view.cs.txt`
- Test: `tests/test_inapp_prefab_codegen.py` (replace `test_mission_feature`; `_mission_plan()` = Task 2 fixture + Task 3 layout fixture)

**Interfaces:**
- Consumes: the Task 3 view fields (`missionTabTemplate`, `missionRowTemplate`, `missionScroll`, `missionBarRoot`, `missionBarFill`, `missionBarMarkerTemplate`), the Task 4 view APIs, and the Task 2 feature-action nodes (`field`, `field + "Label"`, `key`, `can_be_hidden`).
- Produces C#. The bar and feature-action parts are emitted only when their nodes exist.
  - `public event Action<<cls>, InAppMission, InAppClickConfiguration> MissionCtaClicked;`
  - fields `int? _selectedSetNumber`, `string _boundMessageId`, `List<GameObject> _missionRows`, `HashSet<(int setNumber, int rowNumber)> _dismissedRows`, `HashSet<int> _collectedBarRows`, `bool _missionBusy`
  - `private void BindFeature()` and `private void ShowMissionSet(InAppMissionSetProgress set)`
  - `private async Task CollectMissionAsync(KinoaInAppMissionRowView row, int setNumber, InAppMission mission)`
  - `private async Task DismissMissionAsync(int setNumber, InAppMission mission)`
  - `private async Task CollectAllMissionsAsync()`, `private async Task ReachAllMissionsAsync()`, `private async Task CollectAllMissionBarStepsAsync()`
  - `private void BindMissionBar(InAppMissionsProgress state)`
  - `private async Task CollectMissionBarStepAsync(int setNumber, List<InAppMissionsMilestoneStep> steps)`, shared by a single marker and Collect all milestones
  - `private void SetMissionBusy(bool busy)`
  - `private void ApplyMissionActionButton(Button button, KinoaText label, string key, bool canBeHidden, bool show, bool interactable, Func<Task> action)`: label and background as `ApplyButtonSlot` sets them; click → `SendInAppClickEvent` → `ButtonClicked` → `action()` (D2)
  - `private T SpawnMission<T>(T template, List<GameObject> into) where T : Component`
- SDK calls, exact, from `Messaging.cs`:
  - `CollectMissionsProgressAsync(Message, setNumber, rows)` → `Response<InAppMessage>`
  - `ReachMissionsProgress(Message, setNumber, rows)` → `Response<InAppMessage>`
  - `CollectMissionsMilestonesProgress(Message, setNumber, rows)` → `Response<List<InAppMissionsMilestonesResult>>`
  - `DeleteMissionsProgress(Message, setNumber, rows)` → `Response`
- **Failure path:** the milestone pattern: `response == null || !response.IsSuccessful()` (plus `|| response.Data == null` for the data-returning calls) ⇒ log `response?.Error?.Message`, then `SetMissionBusy(false)`. Put `if (this == null) return;` after every `await`.
- **`Bind`:** clears `_dismissedRows` and `_collectedBarRows` when `message.MessageId != _boundMessageId`, before replacing `Message`.
- **Set selection:**

```
target = (_selectedSetNumber == state.PreviousSetProgress?.SetNumber && HasRows(state.PreviousSetProgress) ? state.PreviousSetProgress : null)
         ?? (_selectedSetNumber == state.ActiveSetProgress?.SetNumber ? state.ActiveSetProgress : null)
         ?? state.ActiveSetProgress;
```

- [ ] **Step 1: Capture the goldens.** Before you touch the generator, render the `one_cta` view and the `_milestone_plan()` view from the current code into `tests/golden/`.

- [ ] **Step 2: Write the failing tests.**

```python
def _view(plan): return mod.generate_code(plan, {})["files"][plan["paths"]["view_path"]]

def test_standard_and_milestone_views_unchanged(self):   # golden, byte-for-byte

def test_mission_view_tabs_and_selection(self):
    v = _view(_mission_plan())
    for s in ("state.PreviousSetProgress", '$"Set {set.SetNumber} (prev)"', '$"Set {set.SetNumber}"',
              "_selectedSetNumber", "?? state.ActiveSetProgress", "HasRows("):
        self.assertIn(s, v)

def test_mission_view_cards(self):
    v = _view(_mission_plan())
    for s in ("row.SetPlacement(mission.PlacementNumber);", "row.SetTitle(mission.MissionText);",
              "row.SetSubMission(mission.SubMissionNumber);", "row.SetStatus(mission.Status.ToString());",
              "row.SetProgress(mission.CurrentScore, mission.GoalScore);",
              "row.AddReward(ResolveIcon(resource.ResourceKey), resource.Amount.ToString());",
              "InAppMissionStatus.Reached => 0", "ThenBy(m => m.PlacementNumber)",
              "Kinoa.Messaging.CollectMissionsProgressAsync(Message, setNumber, new List<int> { mission.RowNumber })",
              "MissionCtaClicked?.Invoke(this, mission, mission.ProgressionCta);",
              "%s route mission.ProgressionCta" % mod.TODO, "mission.CompletionCta", "mission.ProcessedResources"):
        self.assertIn(s, v)
    self.assertNotIn(".color =", v.split("ShowMissionSet")[1])   # D6: no status recolouring

def test_mission_view_dismiss(self):
    v = _view(_mission_plan())
    for s in ("Kinoa.Messaging.DeleteMissionsProgress(Message, setNumber, new List<int> { mission.RowNumber })",
              "_dismissedRows.Add((setNumber, mission.RowNumber));",
              "mission.Status == InAppMissionStatus.Reached || mission.Status == InAppMissionStatus.Collected",
              "row.SetDismiss("):
        self.assertIn(s, v)

def test_mission_view_bar_like_milestones(self):
    v = _view(_mission_plan())
    for s in ("state.ProgressBarState", "OrderBy(s => s.MilestoneNumber)", "missionBarFill.fillAmount",
              "Kinoa.Messaging.CollectMissionsMilestonesProgress(Message, setNumber,", "_collectedBarRows.Add(",
              "InAppMilestoneStatus.Reached", "%s apply step.Button.Resources" % mod.TODO):
        self.assertIn(s, v)

def test_mission_view_action_buttons_only_when_in_template(self):
    v = _view(_mission_plan())
    for s in ("Kinoa.Messaging.ReachMissionsProgress(Message,", "private async Task CollectAllMissionsAsync()",
              "private async Task CollectAllMissionBarStepsAsync()",
              'ApplyMissionActionButton(collectAllButton, collectAllButtonLabel, "collect_all_button"',
              'ApplyMissionActionButton(collectAllMilestonesButton, collectAllMilestonesButtonLabel, "collect_all_milestones_button"'):
        self.assertIn(s, v)
    self.assertNotIn("ApplyButton(collectAllButton,", v)      # D2
    t = copy.deepcopy(MISSIONS); t["buttons"] = [b for b in t["buttons"] if b["key"] == "close_button"]
    v2 = _view(_plan(template=t, layout=mod.layout_from_artifact(ART_RAW_WITHOUT_ACTION_BUTTONS)))
    for s in ("ReachMissionsProgress", "CollectAllMissionsAsync", "CollectAllMissionBarStepsAsync", "collectAllButton"):
        self.assertNotIn(s, v2)
    self.assertIn("DeleteMissionsProgress", v2)               # dismiss is always there

def test_mission_view_null_guards(self):
    v = _view(_mission_plan())
    for s in ("var state = feature?.MissionState;", "if (state == null)", "set?.ActiveMissions",
              "bar?.Milestones == null || bar.Milestones.Count == 0", "if (this == null) return;"):
        self.assertIn(s, v)

def test_mission_view_without_bar_has_no_bar_code(self):
    t = copy.deepcopy(MISSIONS); t["features"]["mission"]["progressBar"] = {"display": "dont_show_at_all"}
    v = _view(_plan(template=t, layout=None))
    for s in ("missionBarFill", "CollectMissionsMilestonesProgress"):
        self.assertNotIn(s, v)
```

  `ART_RAW_WITHOUT_ACTION_BUTTONS` is the layout fixture with the three action-button elements removed, so the 1:1 join holds.

- [ ] **Step 3: Run them and confirm they fail.** Run `python -m unittest tests.test_inapp_prefab_codegen -v`. Expected: the mission tests FAIL; the goldens PASS.

- [ ] **Step 4: Implement.** `render_feature_methods(plan)` concatenates:
  - `_MISSION_CS` (tabs, cards, dismiss, card collect, busy state);
  - `_MISSION_BAR_CS`, when a `MissionBar` node exists;
  - one block per `feature_action` node: `_MISSION_COLLECT_ALL_CS`, `_MISSION_REACH_ALL_CS`, `_MISSION_COLLECT_ALL_BAR_CS`.

  Substitute the field, label field, key and canBeHidden from the node.

- [ ] **Step 5: Run the suite and confirm it passes.** Run `python -m unittest discover tests`. Expected: OK, including the goldens and every `FORBIDDEN` check.

- [ ] **Step 6: Commit.** Run `git add` on the helper, the tests and `tests/golden`, then `git commit -m "feat(prefab): missions view — set tabs, mission cards with dismiss, bar claims, feature-action buttons"`.

---

### Task 7: Contracts, workflows and client guides

**Files and edits:**
- `plugin/skills/kinoa-inapp-template-to-prefab/references/prefab-plan-schema.md`:
  - bindings `scroll · list_content · tab_template · tab_part · mission_row_template · row_part`;
  - node fields `feature_action`, `color`, `role` (now read by the builder);
  - `report.mission_actions` / `report.mission_geometry`;
  - the mission subtree in Hierarchy;
  - `MissionTabs` / `MissionBar` in the containers line;
  - artifact `feature.parts` / `row_parts` / `style` in the layout-sources row.
- `references/generated-code-contract.md`: missions per D4–D10, the two shared views (Task 4 API), `MissionCtaClicked`, and the ownership table.
- Prefab `SKILL.md`:
  - **Phase 3:** for a mission template whose artifact has no `feature.parts`, say the missions UI will use neutral default proportions and colours. Offer path B (re-derive from the tip image) before planning.
  - **Phase 4:** read out `report.mission_actions` (which of the three buttons were found) and `report.mission_geometry.defaulted`.
  - **Phase 5:** list the four shared files.
  - **Phase 7:** the hand-off states that feature-action buttons bypass the facade, that dismiss deletes the row's progress on the server, and lists the per-row CTA / bar reward TODOs.
- `docs/inapp-template-to-prefab-guide.md`:
  - the file table;
  - the missions paragraph (~l.143);
  - two troubleshooting lines: *"Collect all / Reach all / Collect all milestones missing → the template has no button whose key or name says so"* and *"mission cards look generic → the layout artifact has no missions geometry; re-derive it from the tip image (from-image path B)"*.
- `docs/inapp-template-generation-guide.md`: one paragraph saying that, for missions, the vision pass also records the UI geometry and colours for the prefab skill.
- `CLAUDE.md`:
  - "In-app template → Unity prefab" paragraph: mission sets → tabs, mission cards (+ dismiss), feature-action buttons only when the template declares them, geometry from the artifact's missions block, the shared views;
  - "In-app templates" paragraph: the artifact now carries the missions geometry.
- `CHANGELOG.md`: add an entry under a top `## [Unreleased]`, creating the heading if needed. No version bump.

- [ ] **Step 1: Make the edits.** Every name must match the code: `mission_actions`, `mission_geometry`, `feature_action`, `KinoaInAppMissionRowView`, `MissionCtaClicked`, `parts`, `row_parts`, `style`.
- [ ] **Step 2: Check for stale text.** Run `grep -rn "one row per .ActiveMissions\|mission rows → .CollectMissionsProgressAsync\|MissionDialog" plugin docs CLAUDE.md`. Expected: no stale hits, and no MissionDialog reference in shipped files.
- [ ] **Step 3: Run the suite.** Run `python -m unittest discover tests`. Expected: OK (`test_inapp_vocabulary_consistency` included).
- [ ] **Step 4: Commit.** Run `git commit -am "docs: missions prefab contract, tip-image geometry, workflows and guides"`.

---

### Task 8: Live verification in Unity (compile + build through `mcp-unity`)

**Files:** none committed. The target is the open Unity project, the `kinoa-sdk` dev project that `mcp-unity` is attached to; its scene is `Assets/Scenes/main.unity`. Generated output goes to `Assets/Kinoa/InAppsMissionCheck/` and is removed at the end.

- [ ] **Step 1: Plan and generate** from the fixtures:
  - Run `python plugin/skills/kinoa-inapp-template-to-prefab/inapp_prefab_plan.py plan --template …/missions/template_missions.json --layout-artifact …/missions/daily_missions.layout.json --out <scratch>/daily_missions.inapp-plan.json --out-dir Assets/Kinoa/InAppsMissionCheck`.
  - Then run `generate --plan <that> --project-root E:/Dev/kinoa-sdk --facade present --facade-namespace <KinoaUiService's namespace there>`.
  - Expected: `ok: true`, `report.mission_geometry.defaulted == []`, and `written` includes the view, the builder and all four shared files.
- [ ] **Step 2: Compile.**
  - Call `mcp__mcp-unity__recompile_scripts`, then `mcp__mcp-unity__get_console_logs` (`logType: error`, `includeStackTrace: false`).
  - Expected: no `error CS` in `InAppsMissionCheck`.
  - On an error: fix the generator (Tasks 4–6), re-run `generate --overwrite --force-shared`, and repeat. Never patch the output.
- [ ] **Step 3: Build.**
  - Call `mcp__mcp-unity__execute_menu_item` with `Tools/Kinoa/In-Apps/Build Prefabs From Plans`.
  - Read `Assets/Kinoa/InAppsMissionCheck/DailyMissions/daily_missions.build-report.json`. Expected: `ok: true`, `fields_missing: []`, `errors: []`; this also proves that no card or tab role went unassigned.
- [ ] **Step 4: Inspect.** Use `mcp__mcp-unity__get_gameobject` on `MissionList/MissionViewport`, `…/MissionRows/MissionRow` and `MissionTabs/MissionTab`. Expected:
  - `ScrollRect.content` is `MissionRows`;
  - every serialized reference on `KinoaInAppMissionRowView` / `KinoaInAppTabView` is non-null;
  - the `MissionRow` `Image` colour equals the fixture's `style.card`;
  - `CollectAllButton`, `ReachAllButton` and `CollectAllMilestonesButton` exist.
- [ ] **Step 5: Clean up and report.**
  - Delete `Assets/Kinoa/InAppsMissionCheck/` and its `.meta`.
  - Reload the scene without saving.
  - Confirm `git -C E:/Dev/kinoa-sdk status` shows nothing from this run.
  - Report what was verified. Runtime binding against a live missions campaign is **not** covered, because it needs a Dashboard missions in-app.

---

## Out of scope

- Status-based recolouring of cards (review round 1: do not add).
- Routing per-row CTAs through `KinoaUiService`: the facade is keyed by template button (D7).
- `[]` placeholder substitution in mission text.
- Showing or editing the missions geometry on the from-image confirmation page. It flows from the analysis into the artifact, like `area_bbox` does today; the developer adjusts it by re-running the vision pass, or in the built prefab.
