// Deterministic interaction harness for the merge-plan page: loads the REAL generated
// HTML in jsdom and drives it the way a user would (typing char-by-char, clicking,
// re-querying focused inputs across re-renders), then asserts on window.exportJson().
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const results = [];
function check(name, cond, detail) {
  results.push({ name, pass: !!cond, detail: cond ? "" : String(detail || "") });
}

// Order-insensitive deep equality: hand-back is JSON — key order is not semantic
// (normalize seeds defaults first, so the state row's key order differs from payload).
function canon(x) {
  if (Array.isArray(x)) return x.map(canon);
  if (x && typeof x === "object")
    return Object.fromEntries(Object.keys(x).sort().map(k => [k, canon(x[k])]));
  return x;
}
function deepEq(a, b) { return JSON.stringify(canon(a)) === JSON.stringify(canon(b)); }

function loadPage(file) {
  const html = fs.readFileSync(file, "utf-8");
  const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true });
  return dom.window;
}

// Type text into the input identified by data-fid, one character at a time,
// re-querying after every keystroke (each input event re-renders the whole page).
function typeInto(w, fid, text, { append = false } = {}) {
  let el = w.document.querySelector(`[data-fid="${fid}"]`);
  if (!el) throw new Error("no input with fid " + fid);
  if (!append) {
    el.value = "";
    el.dispatchEvent(new w.Event("input", { bubbles: true }));
    el = w.document.querySelector(`[data-fid="${fid}"]`);
  }
  for (const ch of text) {
    el = w.document.querySelector(`[data-fid="${fid}"]`);
    if (!el) throw new Error("input " + fid + " vanished mid-typing");
    el.value = el.value + ch;
    el.dispatchEvent(new w.Event("input", { bubbles: true }));
  }
  return w.document.querySelector(`[data-fid="${fid}"]`);
}

function setSelect(w, sel, value) {
  sel.value = value;
  sel.dispatchEvent(new w.Event("change", { bubbles: true }));
}

function exportPlan(w) { return JSON.parse(w.exportJson()); }
// Select-first helpers: rows collapse when valid — the pencil opens them; the checkbox
// includes/excludes without deleting.
function rowByText(w, sectionId, matchText) {
  const needles = Array.isArray(matchText) ? matchText : [matchText];
  return [...w.document.querySelectorAll(`#${sectionId} .row`)]
    .find(d => needles.every(n => d.textContent.includes(n)));
}
function clickPencil(w, sectionId, matchText) {
  const row = rowByText(w, sectionId, matchText);
  const b = row && row.querySelector("button.pencil");
  if (!b) throw new Error("no pencil on row " + matchText);
  b.click();
}
function setCheckbox(w, sectionId, matchText, val) {
  const row = rowByText(w, sectionId, matchText);
  const cb = row && row.querySelector("input.inc");
  if (!cb) throw new Error("no checkbox on row " + matchText);
  cb.checked = val;
  cb.dispatchEvent(new w.Event("change", { bubbles: true }));
}
function gateBlocked(w) { return w.document.getElementById("download").disabled; }
// Open editors block the export by design (2026-08-04) — mid-edit checks assert the
// absence of VALIDATION errors instead; gate asserts belong to collapsed states.
function valErrs(w) { return w.document.querySelectorAll("input.bad, select.bad").length; }
function findRowInput(w, sectionId, placeholder, nth = 0) {
  const hits = [...w.document.querySelectorAll(`#${sectionId} input[type=text]`)]
    .filter(i => i.placeholder === placeholder);
  return hits[nth];
}

// ---------------------------------------------------------------- events page
function testEvents(file) {
  const w = loadPage(file);
  const before = exportPlan(w);
  // existing rows echoed verbatim (payload row 1 is existing)
  const payload = JSON.parse(fs.readFileSync(file, "utf-8").match(/const DATA = (\{[\s\S]*?\});\n/)[1]);
  const exEv = payload.events.find(e => e.existing);
  const echoed = before.events.find(e => e.id === exEv.id);
  const { proposed_params: _pp, ...exCore } = exEv;
  const { proposed_params: _pe, ...echoedCore } = echoed;
  check("events: existing row measured part echoed verbatim", deepEq(echoedCore, exCore),
        JSON.stringify({ echoedCore, exCore }));

  // ---- same-name existing pair (predefined + custom level_up) is legal code reality:
  // both render, neither reds, both ship; a NEW row taking the name still reds.
  const luRows = [...w.document.querySelectorAll("#events .row")]
    .filter(d => d.textContent.includes("level_up"));
  check("events: both same-name existing rows render", luRows.length >= 2, luRows.length);
  const luBadges = luRows.map(d => [...d.querySelectorAll(".badge")].map(b => b.textContent).join("|"));
  check("events: existing custom keeps its measured kind badge (user, not predefined)",
        luBadges.some(t => t.includes("user")) && luBadges.some(t => t.includes("predefined")),
        JSON.stringify(luBadges));
  check("events: same-name existing pair adds no validation error", valErrs(w) === 0);
  const luEcho = before.events.filter(e => e.name === "level_up").map(e => e.kind).sort();
  check("events: both same-name existing rows ship in the hand-back",
        deepEq(luEcho, ["custom", "predefined"]), JSON.stringify(luEcho));
  // ---- existing rows are measurements: a system-named param keeps its measured kind
  const slRow = before.events.find(e => e.name === "start_level");
  check("events: existing system-named param kind ships verbatim (no coercion)",
        slRow && slRow.params[0].kind === "string", JSON.stringify(slRow));
  check("events: existing system param shows the route warning",
        [...w.document.querySelectorAll("#events .row")].some(d =>
          d.textContent.includes("start_level")
          && d.textContent.includes("reserved system name measured as a custom param")));
  w.document.getElementById("add-event").click();
  const luInp = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i => i.placeholder === "event_name" && i.value === "");
  typeInto(w, luInp.dataset.fid, "level_up");
  check("events: new row duplicating an existing name blocks the export", gateBlocked(w));
  check("events: duplicate-vs-existing tooltip names the duplicate",
        [...w.document.querySelectorAll("#events input.bad")]
          .some(i => i.value === "level_up" && (i.title || "").includes("duplicate event name")));
  const luProbe = [...w.document.querySelectorAll("#events .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "level_up")
               && d.querySelector("button.pencil"));

  // ---- ✕ remove: only page-added rows are deletable (measured/existing keep checkboxes)
  check("events: page-added row renders a remove button", !!luProbe.querySelector("button.remove"));
  check("events: measured candidate has no remove button",
        !rowByText(w, "events", "race_finished").querySelector("button.remove"));
  check("events: existing row has no remove button",
        !rowByText(w, "events", "session_start").querySelector("button.remove"));
  luProbe.querySelector("button.remove").click();
  check("events: removing the page-added row clears its errors", valErrs(w) === 0);
  check("events: removed row is gone from the DOM",
        ![...w.document.querySelectorAll("#events input[type=text]")].some(i => i.value === "level_up"));
  // _pageNew never ships in the hand-back
  w.document.getElementById("add-event").click();
  const stInp = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i => i.placeholder === "event_name" && i.value === "");
  typeInto(w, stInp.dataset.fid, "probe_strip");
  const stRow = exportPlan(w).events.find(e => e.name === "probe_strip");
  check("events: exported page-added row carries no page-local flags",
        stRow && !("_pageNew" in stRow) && !("editing" in stRow) && !("included" in stRow),
        JSON.stringify(stRow));
  [...w.document.querySelectorAll("#events .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "probe_strip"))
    .querySelector("button.remove").click();

  // ---- proposed additions (2026-08-04, ✎/done mechanic): discovered additions open
  // the row in edit mode with params born TICKED; done collapses (ticked stay visible,
  // marked); untick drops the key; dup vs the measured part still reds.
  let ssRow = rowByText(w, "events", "session_start");
  check("events: row with discovered additions opens in edit mode",
        (ssRow.querySelector("button.pencil") || {}).textContent === "✓ done");
  check("events: an open editor blocks the export", gateBlocked(w));
  check("events: the counter names the open-editor reason",
        w.document.getElementById("counter").textContent.includes("open for editing"));
  check("events: proposals header rendered", ssRow.textContent.includes("proposed additions"));
  check("events: live-registry header line rendered",
        w.document.getElementById("events").textContent
          .includes("checked against the live dashboard: " + payload.predefined_wire_names.length
            + " predefined / " + payload.debug_wire_names.length + " debug / "
            + payload.custom_event_registry.length + " custom event names"));
  const ppCb = ssRow.querySelector("input.inc");
  check("events: discovered addition born ticked", !!ppCb && ppCb.checked);
  const ppRow = before.events.find(e => e.name === "session_start");
  check("events: ticked addition ships clean under proposed_params",
        ppRow && deepEq(ppRow.proposed_params,
                        [{ name: "session_source", kind: "string", extra: "" }]),
        JSON.stringify(ppRow && ppRow.proposed_params));
  ssRow.querySelector("button.pencil").click();
  ssRow = rowByText(w, "events", "session_start");
  check("events: done collapses the additions editor", !ssRow.querySelector("input.inc"));
  check("events: collapsed row keeps the ticked addition visible, marked",
        ssRow.textContent.includes("session_source") && ssRow.textContent.includes("addition"));
  clickPencil(w, "events", "session_start");
  const ppCb2 = rowByText(w, "events", "session_start").querySelector("input.inc");
  ppCb2.checked = false; ppCb2.dispatchEvent(new w.Event("change", { bubbles: true }));
  check("events: unticked addition leaves no proposed_params key",
        !("proposed_params" in exportPlan(w).events.find(e => e.name === "session_start")));
  // manual ＋ param on an existing row (edit mode only): dup vs measured reds
  check("events: no additions editor on a collapsed clean row",
        ![...rowByText(w, "events", "start_level").querySelectorAll("button")]
          .some(b => b.textContent === "＋ param"));
  clickPencil(w, "events", "start_level");
  [...rowByText(w, "events", "start_level").querySelectorAll("button")]
    .find(b => b.textContent === "＋ param").click();
  const npInp = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i2 => i2.placeholder === "param_name" && i2.value === "");
  typeInto(w, npInp.dataset.fid, "level");
  check("events: addition duplicating a measured param blocks the export", gateBlocked(w));
  const slCb2 = [...rowByText(w, "events", "start_level").querySelectorAll("input.inc")].pop();
  slCb2.checked = false; slCb2.dispatchEvent(new w.Event("change", { bubbles: true }));
  check("events: unticking the dup addition clears its error", valErrs(w) === 0);
  rowByText(w, "events", "start_level").querySelector("button.pencil").click();
  rowByText(w, "events", "session_start").querySelector("button.pencil").click();
  check("events: confirming every editor with done unblocks the export", !gateBlocked(w));
  // hand-added params are deletable (✕); discovery params keep checkbox-only
  clickPencil(w, "events", "race_finished");
  let rfRow = rowByText(w, "events", "GameStateService.cs:130");
  check("events: discovery param has no ✕", rfRow.querySelectorAll("button.remove").length === 0);
  [...rfRow.querySelectorAll("button")].find(b => b.textContent === "＋ param").click();
  rfRow = rowByText(w, "events", "GameStateService.cs:130");
  check("events: hand-added param renders ✕", rfRow.querySelectorAll("button.remove").length === 1);
  rfRow.querySelector("button.remove").click();
  rfRow = rowByText(w, "events", "GameStateService.cs:130");
  check("events: deleted hand-added param is gone and its error with it",
        rfRow.querySelectorAll('input[placeholder="param_name"]').length === 1 && valErrs(w) === 0);
  rfRow.querySelector("button.pencil").click();

  // add event, leave name empty -> gate blocks
  w.document.getElementById("add-event").click();
  check("events: empty new-name blocks export", gateBlocked(w));

  // type a debug wire name -> row collapses, counter excludes it, export strips params
  const nameInput = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i => i.placeholder === "event_name" && i.value === "");
  const fid = nameInput.dataset.fid;
  typeInto(w, fid, "feature_settings_download");
  check("events: debug-tagged row collapses param editor",
        w.document.body.textContent.includes("params are not applicable"));
  const counter = w.document.getElementById("counter").textContent;
  const nNew = payload.events.filter(e => !e.existing).length; // page-added row is debug -> excluded
  check("events: counter excludes debug rows", counter.includes(`${nNew} events`), counter);
  check("events: no validation errors once the name is valid", valErrs(w) === 0, counter);
  const plan1 = exportPlan(w);
  const dbg = plan1.events.find(e => e.name === "feature_settings_download");
  check("events: debug row exports kind debug with params stripped",
        dbg && dbg.kind === "debug" && Array.isArray(dbg.params) && dbg.params.length === 0,
        JSON.stringify(dbg));

  // retype to a predefined wire name -> badge + kind normalized
  typeInto(w, fid, "payment");
  const plan2 = exportPlan(w);
  const pay = plan2.events.find(e => e.id === dbg.id);
  check("events: predefined reclassification exports kind predefined",
        pay && pay.kind === "predefined", JSON.stringify(pay));
  check("events: predefined badge rendered",
        [...w.document.querySelectorAll("#events .badge")].some(b => b.textContent === "predefined"));

  // SDK-automatic under SDK integration: params locked note
  typeInto(w, fid, "install");
  check("events: SDK-automatic row collapses under SDK integration",
        w.document.body.textContent.includes("not redefinable in an SDK integration"));
  const plan3 = exportPlan(w);
  const inst = plan3.events.find(e => e.id === dbg.id);
  check("events: SDK-automatic exports no params", inst && inst.params.length === 0, JSON.stringify(inst));

  // ---- select-first: untick the payload's race_finished row
  setCheckbox(w, "events", "race_finished", false);
  const plan4 = exportPlan(w);
  check("events: unticked row absent from hand-back", !plan4.events.some(e => e.name === "race_finished"));
  check("events: counter drops the unticked row",
        w.document.getElementById("counter").textContent.includes("2 events"),
        w.document.getElementById("counter").textContent);
  check("events: unticked row stays alive (dimmed, not deleted)",
        !!rowByText(w, "events", "race_finished"));
  setCheckbox(w, "events", "race_finished", true);
  const plan5 = exportPlan(w);
  const rf = plan5.events.find(e => e.name === "race_finished");
  check("events: reticked row returns with params intact",
        rf && rf.params.length === 1 && !("included" in rf), JSON.stringify(rf));

  // ---- param include-checkbox (unified mechanic): untick leaves a dim line; never ships
  clickPencil(w, "events", "race_finished");
  const pcb = [...rowByText(w, "events", "GameStateService.cs:130")
    .querySelectorAll("input.inc")].find(c => c.title === "include this param");
  pcb.checked = false; pcb.dispatchEvent(new w.Event("change", { bubbles: true }));
  check("events: unticked param renders a dim left-out line",
        !!rowByText(w, "events", "left out of the plan"));
  const planR = exportPlan(w);
  const rfr = planR.events.find(e => e.name === "race_finished");
  check("events: unticked param absent from hand-back", rfr && rfr.params.length === 0,
        JSON.stringify(rfr));
  check("events: unticked param carries no validation error", valErrs(w) === 0);
  const pcb2 = [...rowByText(w, "events", "GameStateService.cs:130")
    .querySelectorAll("input.inc")].find(c => c.title === "include this param");
  pcb2.checked = true; pcb2.dispatchEvent(new w.Event("change", { bubbles: true }));
  const planR2 = exportPlan(w);
  const rfr2 = planR2.events.find(e => e.name === "race_finished");
  check("events: reticked param returns intact without page-local flags",
        rfr2 && rfr2.params.length === 1 && !("included" in rfr2.params[0]), JSON.stringify(rfr2));

  // ---- system-named param = VALID candidate, different route (never blocks)
  const pn = [...rowByText(w, "events", "GameStateService.cs:130")
    .querySelectorAll("input[type=text]")].find(i2 => i2.placeholder === "param_name");
  const oldName = pn.value;
  // level is settable on EVERY event (CustomEventData : ExtendedGameEventData, SDK fix
  // 2026-07-31) — the system route is universal
  typeInto(w, pn.dataset.fid, "level");
  check("events: system-named param is NOT a validation error", valErrs(w) === 0);
  check("events: system badge + base-class route note shown",
        [...w.document.querySelectorAll("#events .badge")].some(b => b.textContent === "system")
        && w.document.body.textContent.includes("rides the base class"));
  check("events: system param kind is a fixed label, not a select",
        w.document.body.textContent.includes("number (fixed)"));
  const planS = exportPlan(w);
  const evS = planS.events.find(e => !e.existing && (e.params || []).some(p2 => p2.name === "level"));
  check("events: system param exports system_field: true",
        evS && evS.params.find(p2 => p2.name === "level").system_field === true,
        JSON.stringify(evS));
  check("events: system param kind coerced to the canonical type",
        evS && evS.params.find(p2 => p2.name === "level").kind === "number",
        JSON.stringify(evS));
  typeInto(w, [...rowByText(w, "events", "GameStateService.cs:130")
    .querySelectorAll('input[placeholder="param_name"]')][0].dataset.fid, oldName);
  const planS2 = exportPlan(w);
  const evS2 = planS2.events.find(e => !e.existing && (e.params || []).some(p2 => p2.name === oldName));
  check("events: renaming off the reserved list drops the marker",
        evS2 && !("system_field" in evS2.params.find(p2 => p2.name === oldName)),
        JSON.stringify(evS2));
  clickPencil(w, "events", "GameStateService.cs:130");  // collapse back (expanded row: name lives in the input, match by source)

  // ---- duplicate tooltip names the duplicate, not the length limit
  w.document.getElementById("add-event").click();
  const dupInp = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i2 => i2.placeholder === "event_name" && i2.value === "");
  typeInto(w, dupInp.dataset.fid, "race_finished");
  const dupBad = [...w.document.querySelectorAll("#events input.bad")]
    .find(i2 => i2.value === "race_finished");
  check("events: duplicate tooltip names the duplicate",
        dupBad && (dupBad.title || "").includes("duplicate event name"),
        dupBad ? dupBad.title : "no red dup input");
  // drop the probe row via its checkbox
  const dupRow = [...w.document.querySelectorAll("#events .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i2 => i2.value === "race_finished")
               && d.querySelector("button.pencil"));
  const dupCb = dupRow.querySelector("input.inc");
  dupCb.checked = false; dupCb.dispatchEvent(new w.Event("change", { bubbles: true }));

  // ---- predefined-name editability: renaming away from the registry downgrades to user
  const nm = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i => i.value === "install");
  check("events: predefined-tagged new row has an editable name input", !!nm);
  typeInto(w, nm.dataset.fid, "my_install_report");
  const plan6 = exportPlan(w);
  const mi = plan6.events.find(e => e.name === "my_install_report");
  check("events: renamed off-registry row exports kind custom", mi && mi.kind === "custom",
        JSON.stringify(mi));


  // ---- events ADOPT route (2026-08-05): same-name dashboard custom
  check("events: adopt candidate shows the on-dashboard badge",
        [...rowByText(w, "events", "DailyBonus.cs:41").querySelectorAll(".badge")]
          .some(b => b.textContent === "on dashboard"));
  check("events: collapsed adopt row hints at uncovered dashboard params",
        rowByText(w, "events", "DailyBonus.cs:41").textContent
          .includes("+1 dashboard param not sent by your code"));
  clickPencil(w, "events", "DailyBonus.cs:41");
  const dbRow2 = rowByText(w, "events", "DailyBonus.cs:41");
  check("events: uncovered dashboard params render read-only, covered ones only once",
        dbRow2.textContent.includes("also on the dashboard")
        && dbRow2.textContent.includes("bonus_day")
        && !dbRow2.textContent.includes("wires into the existing dashboard event")
        && !dbRow2.textContent.includes("streak")   // covered param lives in the input only
        && [...dbRow2.querySelectorAll("input[type=text]")].some(i2 => i2.value === "streak"));
  check("events: local param matching a dashboard param carries the registered chip",
        [...dbRow2.querySelectorAll("span")].some(s2 => (s2.title || "").includes("will NOT re-add")));
  check("events: registered param kind pinned — select only for new params",
        dbRow2.textContent.includes("(fixed)")
        && [...dbRow2.querySelectorAll("select")].length === 1);
  typeInto(w, [...dbRow2.querySelectorAll("input[type=text]")]
    .find(i2 => i2.value === "streak").dataset.fid, "streak_x");
  const dbRow2b = rowByText(w, "events", "DailyBonus.cs:41");
  check("events: renaming a registered param unpins its type",
        !dbRow2b.textContent.includes("(fixed)")
        && [...dbRow2b.querySelectorAll("select")].length === 2);
  typeInto(w, [...dbRow2b.querySelectorAll("input[type=text]")]
    .find(i2 => i2.value === "streak_x").dataset.fid, "streak");
  const dbRow2c = rowByText(w, "events", "DailyBonus.cs:41");
  const dbName = [...dbRow2c.querySelectorAll("input[type=text]")].find(i2 => i2.value === "daily_bonus");
  typeInto(w, dbName.dataset.fid, "daily_bonus_v2");
  check("events: renaming opts out of adoption",
        ![...rowByText(w, "events", "DailyBonus.cs:41").querySelectorAll(".badge")]
          .some(b => b.textContent === "on dashboard"));
  typeInto(w, [...rowByText(w, "events", "DailyBonus.cs:41").querySelectorAll("input[type=text]")]
    .find(i2 => i2.value === "daily_bonus_v2").dataset.fid, "daily_bonus");
  rowByText(w, "events", "DailyBonus.cs:41").querySelector("button.pencil").click();

  // ---- Dashboard->Code orphans (2026-08-05): registry entity with no page row
  check("events: orphan is not exported while unticked",
        !exportPlan(w).events.some(e => e.name === "push_opt_in"));
  check("events: orphan card starts collapsed with the count visible",
        w.document.getElementById("events-card").textContent.includes("no code carrier (1)")
        && ![...w.document.querySelectorAll("#events-card .orphans input.inc")].length);
  w.document.querySelector("#events-card .orphans strong").parentElement.click();
  check("events: expanded orphan card lists the dashboard-only event",
        w.document.getElementById("events-card").textContent.includes("push_opt_in"));
  const orCb = [...w.document.querySelectorAll("#events-card .orphans input.inc")]
    .find(c => (c.title || "").includes("generate the code carrier"));
  orCb.checked = true; orCb.dispatchEvent(new w.Event("change", { bubbles: true }));
  const orRow = exportPlan(w).events.find(e => e.name === "push_opt_in");
  check("events: ticked orphan ships with the marker and dashboard params",
        orRow && orRow.dashboard_orphan === true && orRow.existing === false
        && deepEq(orRow.params, [{ name: "channel", kind: "string", extra: "" }]),
        JSON.stringify(orRow));
  const orCb2 = [...w.document.querySelectorAll("#events-card .orphans input.inc")]
    .find(c => (c.title || "").includes("generate the code carrier"));
  orCb2.checked = false; orCb2.dispatchEvent(new w.Event("change", { bubbles: true }));
  // collapse back after the probe
  w.document.querySelector("#events-card .orphans strong").parentElement.click();
  check("events: orphan card collapses back to its header",
        ![...w.document.querySelectorAll("#events-card .orphans input.inc")].length);

  // ---- ⌘Z / Ctrl+Z: whole-state undo survives re-renders (native stacks die)
  const zKey = extra => new w.KeyboardEvent("keydown",
    Object.assign({ key: "z", metaKey: true, bubbles: true, cancelable: true }, extra));
  const evRowCount = () => w.document.querySelectorAll("#events .row").length;
  const zBase = evRowCount();
  w.document.getElementById("add-event").click();
  const zInp = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i2 => i2.placeholder === "event_name" && i2.value === "");
  typeInto(w, zInp.dataset.fid, "zz");
  w.document.dispatchEvent(zKey({}));
  check("undo: last keystroke reverted",
        [...w.document.querySelectorAll("#events input[type=text]")].some(i2 => i2.value === "z"));
  w.document.dispatchEvent(zKey({}));
  w.document.dispatchEvent(zKey({}));
  check("undo: row-add undone", evRowCount() === zBase);
  w.document.dispatchEvent(zKey({ shiftKey: true }));
  check("redo: row-add restored", evRowCount() === zBase + 1);
  w.document.dispatchEvent(zKey({}));
  check("undo: clean baseline restored", evRowCount() === zBase);
  return w;
}

// ---------------------------------------------------------------- fields page
function testFields(file) {
  const w = loadPage(file);
  const payload = JSON.parse(fs.readFileSync(file, "utf-8").match(/const DATA = (\{[\s\S]*?\});\n/)[1]);
  const exF = payload.player_fields.find(f => f.existing);
  const plan0 = exportPlan(w);
  const echoed = plan0.player_fields.find(f => f.id === exF.id);
  check("fields: existing row echoed verbatim (incl. description/path)",
        deepEq(echoed, exF), JSON.stringify({ echoed, exF }));

  // snake-path dup: WalletGold vs Wallet_Gold both -> wallet_gold
  w.document.getElementById("add-field").click();
  let inp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, inp.dataset.fid, "WalletGold");
  w.document.getElementById("add-field").click();
  inp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, inp.dataset.fid, "Wallet_Gold");
  check("fields: snake-path collision turns red and blocks export", gateBlocked(w));
  const reds = [...w.document.querySelectorAll("#player_fields input.bad")];
  check("fields: BOTH colliding rows are red", reds.length >= 2, reds.length);

  // resolve by renaming the second
  const second = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "Wallet_Gold");
  typeInto(w, second.dataset.fid, "WalletGems");
  check("fields: resolving the path dup clears the errors", valErrs(w) === 0);

  // charset: space+punct is red
  typeInto(w, second.dataset.fid, "My Field!");
  check("fields: non-identifier name blocks export", gateBlocked(w));
  typeInto(w, second.dataset.fid, "WalletGems");

  // acronym snake preview parity: XPBonus -> xp_bonus
  typeInto(w, second.dataset.fid, "XPBonus");
  check("fields: acronym-aware snake path auto-derivation (xp_bonus)",
        [...w.document.querySelectorAll("#player_fields input[type=text]")]
          .some(i => i.value === "xp_bonus"));
  typeInto(w, second.dataset.fid, "WalletGems");

  // stale-path clear: renaming re-derives the registration path
  const lr = rowByText(w, "player_fields", "LastRaceAt");
  clickPencil(w, "player_fields", "LastRaceAt");
  const lrInput = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "LastRaceAt");
  typeInto(w, lrInput.dataset.fid, "LastRaceTime");
  const planP = exportPlan(w);
  const lrOut = planP.player_fields.find(f => f.name === "LastRaceTime");
  check("fields: rename re-derives the shipped path from the new name",
        lrOut && lrOut.path === "last_race_time", JSON.stringify(lrOut));
  check("fields: path input follows the new name",
        [...w.document.querySelectorAll("#player_fields input[type=text]")]
          .some(i => i.value === "last_race_time"));
  // manual path override ships in the hand-back; a name edit resets it back to auto
  const pIn = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "last_race_time");
  // select-all + replace (one input event) — clearing char-by-char would snap back to auto
  pIn.value = "race.finished_at";
  pIn.dispatchEvent(new w.Event("input", { bubbles: true }));
  const planOv = exportPlan(w);
  const ov = planOv.player_fields.find(f => f.name === "LastRaceTime");
  check("fields: manual path override ships", ov && ov.path === "race.finished_at",
        JSON.stringify(ov));
  check("fields: dotted override with mismatched segments blocks the export", gateBlocked(w));
  const nIn = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "LastRaceTime");
  typeInto(w, nIn.dataset.fid, "LastRaceTime2");
  const planOv2 = exportPlan(w);
  const ov2 = planOv2.player_fields.find(f => f.name === "LastRaceTime2");
  check("fields: editing the name resets the override back to the auto-derived path",
        ov2 && ov2.path === "last_race_time2", JSON.stringify(ov2));
  typeInto(w, [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "LastRaceTime2").dataset.fid, "LastRaceAt");
  typeInto(w, w.document.querySelector('#player_fields input[type=text][value=""]') ? lrInput.dataset.fid : lrInput.dataset.fid, "LastRaceAt");

  // ---- leaf/object path conflict: Wallet.Gold + Wallet.Gold.Price both red
  w.document.getElementById("add-field").click();
  let ncInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, ncInp.dataset.fid, "Wallet.Gold");
  w.document.getElementById("add-field").click();
  ncInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, ncInp.dataset.fid, "Wallet.Gold.Price");
  check("fields: leaf/object path conflict blocks the export", gateBlocked(w));
  check("fields: leaf/object explanation shown",
        [...w.document.querySelectorAll("#player_fields input.bad")]
          .some(i => (i.title || "").includes("leaf/object conflict")));
  typeInto(w, [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "Wallet.Gold.Price").dataset.fid, "Wallet.GoldPrice");
  check("fields: restructuring resolves the conflict", valErrs(w) === 0);
  // clean up the two probe rows via ✕ (page-added rows are deletable)
  for (const nm of ["Wallet.Gold", "Wallet.GoldPrice"]) {
    const row = [...w.document.querySelectorAll("#player_fields .row")]
      .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === nm));
    row.querySelector("button.remove").click();
  }
  // string producer ids must not break the add-row counter (id: null regression)
  w.document.getElementById("add-field").click();
  const sidRow = exportPlan(w).player_fields.find(f => f.source === "added on page" && !f.name);
  check("fields: page-added row gets a numeric non-null id despite string payload ids",
        sidRow && typeof sidRow.id === "number" && isFinite(sidRow.id), JSON.stringify(sidRow));
  [...w.document.querySelectorAll("#player_fields .row")]
    .filter(d => d.querySelector("button.remove"))
    .forEach(d => {
      const inp = [...d.querySelectorAll("input[type=text]")];
      if (inp.length && inp.every(i => !i.value)) d.querySelector("button.remove").click();
    });

  // page-added row ships the DERIVED path explicitly (no manual override needed)
  w.document.getElementById("add-field").click();
  const dpInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, dpInp.dataset.fid, "InitialDeviceOS");
  const dpRow = exportPlan(w).player_fields.find(f => f.name === "InitialDeviceOS");
  check("fields: page-added row exports its derived path",
        dpRow && dpRow.path === "initial_device_os", JSON.stringify(dpRow));
  [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "InitialDeviceOS"))
    .querySelector("button.remove").click();

  // ---- Dashboard->Code orphan (fields): VIP tier -> property derivation on tick
  w.document.querySelector("#fields-card .orphans strong").parentElement.click();
  check("fields: expanded orphan card lists the dashboard-only field",
        w.document.getElementById("fields-card").textContent.includes("VIP tier"));
  const pfOr = [...w.document.querySelectorAll("#fields-card .orphans .grid")]
    .find(g2 => g2.textContent.includes("VIP tier")).querySelector("input.inc");
  pfOr.checked = true; pfOr.dispatchEvent(new w.Event("change", { bubbles: true }));
  const pfOrRow = exportPlan(w).player_fields.find(f => f.path === "vip_tier");
  check("fields: ticked orphan ships marker + derived property + dashboard attrs",
        pfOrRow && pfOrRow.dashboard_orphan === true && pfOrRow.property === "VIPTier"
        && pfOrRow.kind === "number" && pfOrRow.existing === false, JSON.stringify(pfOrRow));
  const pfOr2 = [...w.document.querySelectorAll("#fields-card .orphans .grid")]
    .find(g2 => g2.textContent.includes("VIP tier")).querySelector("input.inc");
  pfOr2.checked = false; pfOr2.dispatchEvent(new w.Event("change", { bubbles: true }));
  w.document.querySelector("#fields-card .orphans strong").parentElement.click();

  // "on dashboard" ADOPT route: badge + pinned kind + read-only description; the
  // hand-back carries dashboard_field: true and the dashboard's description.
  w.document.getElementById("add-field").click();
  const adInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, adInp.dataset.fid, "TransactionCount");
  // external namespace: type badge replaces "new field", red with its own message
  w.document.getElementById("add-field").click();
  const exInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, exInp.dataset.fid, "BucketFoo");
  const exRow = [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "BucketFoo"));
  const exPath = [...exRow.querySelectorAll("input[type=text]")].find(i => i.value === "bucket_foo");
  // one-shot set: clearing first would snap the override back to the derived path
  exPath.value = "calculated_fields.foo";
  exPath.dispatchEvent(new w.Event("input", { bubbles: true }));
  check("fields: external namespace shows the external type badge and reds",
        [...w.document.querySelectorAll("#player_fields .badge")]
          .some(b => b.textContent === "external")
        && [...w.document.querySelectorAll("#player_fields input.bad")]
          .some(i => (i.title || "").includes("external field namespace")));
  [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "BucketFoo"))
    .querySelector("button.remove").click();
  // existing rows carry the type lamp: user customs vs predefined_in_use base writes
  check("fields: existing custom row shows already-in-code + user",
        (() => {
          const bs = [...rowByText(w, "player_fields", "EpisodeNumber").querySelectorAll(".badge")]
            .map(b => b.textContent);
          return bs.includes("already in code") && bs.includes("user");
        })());
  check("fields: predefined_in_use row shows already-in-code + predefined",
        (() => {
          const row = [...w.document.querySelectorAll("#player_fields .row")]
            .find(d => d.textContent.includes("KinoaGameEventBuildingService.cs:125"));
          const bs = row ? [...row.querySelectorAll(".badge")].map(b => b.textContent) : [];
          return bs.includes("already in code") && bs.includes("predefined");
        })());
  check("fields: live-registry header line rendered",
        w.document.getElementById("player_fields").textContent
          .includes("checked against the live dashboard: 1 predefined / 1 calculated / 2 custom"));
  // collapse the adopt probe: the badge must survive the select-first view
  rowByText(w, "player_fields", "wires a code carrier").querySelector("button.pencil").click();
  check("fields: adopt badge visible on the COLLAPSED row",
        [...rowByText(w, "player_fields", "transaction_count").querySelectorAll(".badge")]
          .some(b => b.textContent === "on dashboard"));
  clickPencil(w, "player_fields", "transaction_count");
  check("fields: adopt head carries the badge pair in one row",
        (() => {
          const adRow2 = [...w.document.querySelectorAll("#player_fields .row")]
            .find(d => [...d.querySelectorAll("input[type=text]")]
              .some(i => i.value === "TransactionCount"));
          const hs = [...adRow2.querySelectorAll(".badge")].map(b => b.textContent);
          return hs.includes("on dashboard") && hs.includes("user") && !hs.includes("new field");
        })());
  check("fields: adopt row shows the on-dashboard badge + pinned kind",
        [...w.document.querySelectorAll("#player_fields .badge")]
          .some(b => b.textContent === "on dashboard")
        && w.document.getElementById("player_fields").textContent.includes("number (fixed)"));
  check("fields: adopt row shows the dashboard description read-only",
        w.document.getElementById("player_fields").textContent
          .includes("description (dashboard): Total number of IAP transactions."));
  check("fields: adopt row is valid (name taken-check exempted by the path match)",
        valErrs(w) === 0);
  const adRow = exportPlan(w).player_fields.find(f => f.name === "TransactionCount");
  check("fields: adopt row ships dashboard_field + pinned kind + dashboard description",
        adRow && adRow.dashboard_field === true && adRow.kind === "number"
        && adRow.description === "Total number of IAP transactions.",
        JSON.stringify(adRow));
  // editing the path opts OUT of adoption (dashboard field is never renamed)
  const adPath = [...rowByText(w, "player_fields", "wires a code carrier")
    .querySelectorAll("input[type=text]")].find(i => i.value === "transaction_count");
  typeInto(w, adPath.dataset.fid, "transaction_count_v2");
  check("fields: editing the path opts out of adoption",
        ![...w.document.querySelectorAll("#player_fields .badge")]
          .some(b => b.textContent === "on dashboard"));
  [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "TransactionCount"))
    .querySelector("button.remove").click();

  // spaced display name: property derives PascalCase, path snake, all three ship
  w.document.getElementById("add-field").click();
  const spInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, spInp.dataset.fid, "Skin color");
  check("fields: spaced name is valid and shows the C# preview",
        valErrs(w) === 0 && [...w.document.querySelectorAll("#player_fields code")]
          .some(c => c.textContent === "SkinColor"));
  const spRow = exportPlan(w).player_fields.find(f => f.name === "Skin color");
  check("fields: spaced name ships name + property + path",
        spRow && spRow.property === "SkinColor" && spRow.path === "skin_color",
        JSON.stringify(spRow));
  [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "Skin color"))
    .querySelector("button.remove").click();

  // platform-reserved path (static plugin list): red offline-proof, ✕ cleans up
  w.document.getElementById("add-field").click();
  const rsInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, rsInp.dataset.fid, "TimeZone");
  check("fields: platform-reserved path turns red",
        [...w.document.querySelectorAll("#player_fields input.bad")]
          .some(i => (i.title || "").includes("RESERVED by the platform")));
  check("fields: platform-reserved path blocks via validation", valErrs(w) > 0);
  check("fields: static-reserved-only hit has NO type tag (kind unknown)", (() => {
    const probe = [...w.document.querySelectorAll("#player_fields .row")]
      .find(d => [...d.querySelectorAll("input[type=text]")].some(i2 => i2.value === "TimeZone"));
    return !!probe && ![...probe.querySelectorAll(".badge")]
      .some(b => ["calculated", "predefined"].includes(b.textContent));
  })());
  [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "TimeZone"))
    .querySelector("button.remove").click();

  check("fields: page-added probes fully removed via ✕",
        ![...w.document.querySelectorAll("#player_fields input[type=text]")]
          .some(i => ["Wallet.Gold", "Wallet.GoldPrice"].includes(i.value)));

  // ---- dashboard field registry: predefined path = valid + activate route
  w.document.getElementById("add-field").click();
  let regInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.placeholder === "Wallet.Gold" && i.value === "");
  typeInto(w, regInp.dataset.fid, "Level");
  check("fields: predefined dashboard path is NOT an error", valErrs(w) === 0);
  check("fields: description input hidden for a predefined match",
        ![...w.document.querySelectorAll("#player_fields input[type=text]")]
          .some(i => i.placeholder === "description (optional)" &&
                     i.closest(".row") && i.closest(".row").textContent.includes("predefined")));
  check("fields: predefined badge + fixed kind shown",
        [...w.document.querySelectorAll("#player_fields .badge")].some(b => b.textContent === "predefined")
        && w.document.querySelector("#player_fields").textContent.includes("number (fixed)"));
  const planFR = exportPlan(w);
  const lvl = planFR.player_fields.find(f => f.name === "Level");
  check("fields: predefined field exports marker + pinned kind",
        lvl && lvl.predefined_field === true && lvl.kind === "number", JSON.stringify(lvl));
  // calculated path = red
  typeInto(w, [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "Level").dataset.fid, "DaysSinceInstall");
  check("fields: calculated dashboard path blocks the export", gateBlocked(w));
  check("fields: calculated match shows its type tag next to the error",
        [...w.document.querySelectorAll("#player_fields .badge")]
          .some(b => b.textContent === "calculated"));

  // taken name (different path) = red
  typeInto(w, [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "DaysSinceInstall").dataset.fid, "Level2");
  check("fields: recovery to a free name clears the error", valErrs(w) === 0);
  // the textual path preview is gone (path lives in an input) — find the row by its input
  const l2row = [...w.document.querySelectorAll("#player_fields .row")]
    .find(d => [...d.querySelectorAll("input[type=text]")].some(i => i.value === "Level2"));
  const l2cb = l2row.querySelector("input.inc");
  l2cb.checked = false; l2cb.dispatchEvent(new w.Event("change", { bubbles: true }));

  // description authored on page ships in export
  const descInp = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .filter(i => i.placeholder === "description (optional)").pop();
  typeInto(w, descInp.dataset.fid, "hard currency");
  const plan1 = exportPlan(w);
  const gems = plan1.player_fields.find(f => f.name === "WalletGems");
  check("fields: page-authored description exported", gems && gems.description === "hard currency",
        JSON.stringify(gems));
  return w;
}

// ---------------------------------------------------------------- fs page
function testFs(file) {
  const w = loadPage(file);
  const payload = JSON.parse(fs.readFileSync(file, "utf-8").match(/const DATA = (\{[\s\S]*?\});\n/)[1]);
  const plan0 = exportPlan(w);
  // existing settings echoed verbatim (multi-version state preserved: v2 and v3 keys)
  for (const st of payload.feature_settings.settings.filter(s => s.existing)) {
    const out = plan0.feature_settings.settings.find(o => o.id === st.id);
    check(`fs: existing key ${st.key} version untouched (v${st.version})`,
          out && out.version === st.version, JSON.stringify(out));
  }
  check("fs: multi-version info note rendered",
        w.document.body.textContent.includes("valid for backward compatibility"));

  // new setting: bound schema's version exported (BoosterEconomy payload version = 3)
  const promo = plan0.feature_settings.settings.find(o => o.key === "BoosterEconomy_Promo");
  check("fs: new key inherits the schema's highest wired version",
        promo && String(promo.version) === "3", JSON.stringify(promo));

  // rename a NEW schema -> its bound settings turn red "(missing: old)", export blocked
  clickPencil(w, "feature_settings", "RaceRewards");
  const schemaName = [...w.document.querySelectorAll("#feature_settings input[type=text]")]
    .find(i => i.value === "RaceRewards");
  typeInto(w, schemaName.dataset.fid, "RaceRewardsV2");
  check("fs: schema rename does NOT auto-follow — export blocked", gateBlocked(w));
  check("fs: dangling binding shows (missing: RaceRewards)",
        w.document.body.textContent.includes("(missing: RaceRewards)"));
  // explicit re-pick resolves
  const sel = [...w.document.querySelectorAll("#feature_settings select")]
    .find(s => [...s.options].some(o => o.textContent.includes("missing")));
  setSelect(w, sel, "RaceRewardsV2");
  check("fs: explicit re-pick clears the dangling error", valErrs(w) === 0);

  // ---- select-first: unticking a schema pulls it from the plan; bound settings go red
  clickPencil(w, "feature_settings", "new schema");  // "done" -> collapse (single new schema in fixture)
  setCheckbox(w, "feature_settings", ["new schema", "RaceRewardsV2"], false);
  check("fs: unticked schema -> bound setting auto-expands red, gate blocked", gateBlocked(w));
  check("fs: dangling text names the unticked schema",
        w.document.body.textContent.includes("(missing: RaceRewardsV2)"));
  const planX = exportPlan(w);
  check("fs: unticked schema absent from hand-back",
        !planX.feature_settings.schemas.some(x => x.name === "RaceRewardsV2"));
  setCheckbox(w, "feature_settings", ["new setting", "(missing: RaceRewardsV2)"], false);
  check("fs: unticking the dangling setting too clears the error", valErrs(w) === 0);
  const planY = exportPlan(w);
  check("fs: unticked setting absent from hand-back",
        !planY.feature_settings.settings.some(x => x.key === "RaceRewards"));
  check("fs: no page-local flags leak into hand-back",
        planY.feature_settings.schemas.every(x => !("included" in x) && !("editing" in x)));
  return w;
}

// ---------------------------------------------------------------- resources page
function testResources(file) {
  const w = loadPage(file);
  const payload = JSON.parse(fs.readFileSync(file, "utf-8").match(/const DATA = (\{[\s\S]*?\});\n/)[1]);
  const exR = payload.resources.find(r => r.existing);
  const plan0 = exportPlan(w);
  const echoed = plan0.resources.find(r => r.id === exR.id);
  check("resources: existing row echoed verbatim",
        deepEq(echoed, exR), JSON.stringify({ echoed, exR }));

  // add resource + field; type enum values CHAR BY CHAR including commas
  w.document.getElementById("add-res").click();
  const keyInp = [...w.document.querySelectorAll("#resources input[type=text]")]
    .find(i => i.placeholder === "legendary_sword" && i.value === "");
  typeInto(w, keyInp.dataset.fid, "magic_shield");
  const nameInp = [...w.document.querySelectorAll("#resources input[type=text]")]
    .find(i => i.placeholder === "Legendary Sword" && i.value === "");
  typeInto(w, nameInp.dataset.fid, "Magic Shield");
  const addFieldBtn = [...w.document.querySelectorAll("#resources button")]
    .find(b => b.textContent === "＋ field");
  addFieldBtn.click();
  const fInp = [...w.document.querySelectorAll("#resources input[type=text]")]
    .find(i => i.placeholder === "field_name" && i.value === "");
  typeInto(w, fInp.dataset.fid, "rarity");
  const kindSel = [...w.document.querySelectorAll("#resources select")].pop();
  setSelect(w, kindSel, "enumeration");
  const enumInp = [...w.document.querySelectorAll("#resources input[type=text]")]
    .find(i => i.placeholder === "a, b, c");
  const after = typeInto(w, enumInp.dataset.fid, "common, rare, epic");
  check("resources: commas survive char-by-char typing", after.value === "common, rare, epic", after.value);
  const plan1 = exportPlan(w);
  const shield = plan1.resources.find(r => r.key === "magic_shield");
  check("resources: enum values parsed correctly",
        JSON.stringify(shield.fields[0].enumeration_values) === JSON.stringify(["common", "rare", "epic"]),
        JSON.stringify(shield.fields[0]));
  check("resources: _enumRaw never ships", !("_enumRaw" in shield.fields[0]), JSON.stringify(shield.fields[0]));
  check("resources: no required key authored on the page", !("required" in shield.fields[0]),
        JSON.stringify(shield.fields[0]));

  // ':' in enum values / default / field name blocks export
  typeInto(w, w.document.querySelector('#resources input[placeholder="a, b, c"]').dataset.fid, "a:b", {});
  check("resources: ':' in enum values blocks export", gateBlocked(w));
  typeInto(w, w.document.querySelector('#resources input[placeholder="a, b, c"]').dataset.fid, "common, rare");
  const defInp = [...w.document.querySelectorAll("#resources input[type=text]")]
    .find(i => i.placeholder === "default");
  typeInto(w, defInp.dataset.fid, "epic");
  check("resources: default outside enum values blocks export", gateBlocked(w));
  typeInto(w, w.document.querySelector('#resources input[placeholder="default"]').dataset.fid, "rare");
  check("resources: enum-member default passes", valErrs(w) === 0);

  // number default validation
  const kindSel2 = [...w.document.querySelectorAll("#resources select")].pop();
  setSelect(w, kindSel2, "number");
  check("resources: stale enum default on number turns red (kind toggle)", gateBlocked(w));
  typeInto(w, w.document.querySelector('#resources input[placeholder="default"]').dataset.fid, "42");
  check("resources: numeric default passes", valErrs(w) === 0);
  const plan2 = exportPlan(w);
  const shield2 = plan2.resources.find(r => r.key === "magic_shield");
  check("resources: enum values stripped for non-enum kind at export",
        JSON.stringify(shield2.fields[0].enumeration_values) === "[]", JSON.stringify(shield2.fields[0]));
  return w;
}

// ------------------------------------------------------- version-mismatch page
function testMismatch(file) {
  const w = loadPage(file);
  check("mismatch: export disabled", gateBlocked(w));
  const btn = w.document.getElementById("add-event");
  if (btn) {
    check("mismatch: add buttons disabled", btn.disabled);
    btn.click(); btn.click();
  }
  const banners = w.document.querySelectorAll("#vm-banner");
  check("mismatch: banner rendered exactly once", banners.length === 1, banners.length);
  return w;
}

// ---------------------------------------------------------------- run
const dir = process.argv[2];
testEvents(path.join(dir, "e2e-events.html"));
testFields(path.join(dir, "e2e-fields.html"));
testFs(path.join(dir, "e2e-fs.html"));
testResources(path.join(dir, "e2e-resources.html"));
testMismatch(path.join(dir, "e2e-mismatch.html"));

const failed = results.filter(r => !r.pass);
for (const r of results) console.log((r.pass ? "PASS" : "FAIL") + "  " + r.name + (r.pass ? "" : "  :: " + r.detail));
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
