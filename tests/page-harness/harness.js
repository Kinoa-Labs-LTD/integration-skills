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
  check("events: existing row echoed verbatim", deepEq(echoed, exEv),
        JSON.stringify({ echoed, exEv }));

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
  check("events: gate reopens once name valid", !gateBlocked(w), counter);
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
        w.document.getElementById("counter").textContent.includes("1 events"),
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
  const pcb = [...w.document.querySelectorAll("#events input.inc")]
    .find(c => c.title === "include this param");
  pcb.checked = false; pcb.dispatchEvent(new w.Event("change", { bubbles: true }));
  check("events: unticked param renders a dim left-out line",
        !!rowByText(w, "events", "left out of the plan"));
  const planR = exportPlan(w);
  const rfr = planR.events.find(e => e.name === "race_finished");
  check("events: unticked param absent from hand-back", rfr && rfr.params.length === 0,
        JSON.stringify(rfr));
  check("events: unticked param never blocks the gate", !gateBlocked(w));
  const pcb2 = [...w.document.querySelectorAll("#events input.inc")]
    .find(c => c.title === "include this param");
  pcb2.checked = true; pcb2.dispatchEvent(new w.Event("change", { bubbles: true }));
  const planR2 = exportPlan(w);
  const rfr2 = planR2.events.find(e => e.name === "race_finished");
  check("events: reticked param returns intact without page-local flags",
        rfr2 && rfr2.params.length === 1 && !("included" in rfr2.params[0]), JSON.stringify(rfr2));

  // ---- system-named param = VALID candidate, different route (never blocks)
  const pn = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i2 => i2.placeholder === "param_name");
  const oldName = pn.value;
  typeInto(w, pn.dataset.fid, "level");
  check("events: system-named param does NOT block the export", !gateBlocked(w));
  check("events: system badge + base-class route note shown",
        [...w.document.querySelectorAll("#events .badge")].some(b => b.textContent === "system")
        && w.document.body.textContent.includes("rides the base class"));
  const planS = exportPlan(w);
  const evS = planS.events.find(e => (e.params || []).some(p2 => p2.name === "level"));
  check("events: system param exports system_field: true",
        evS && evS.params.find(p2 => p2.name === "level").system_field === true,
        JSON.stringify(evS));
  typeInto(w, w.document.querySelector('#events input[placeholder="param_name"]').dataset.fid, oldName);
  const planS2 = exportPlan(w);
  const evS2 = planS2.events.find(e => (e.params || []).some(p2 => p2.name === oldName));
  check("events: renaming off the reserved list drops the marker",
        evS2 && !("system_field" in evS2.params.find(p2 => p2.name === oldName)),
        JSON.stringify(evS2));
  clickPencil(w, "events", "GameStateService.cs:130");  // collapse back (expanded row: name lives in the input, match by source)

  // ---- predefined-name editability: renaming away from the registry downgrades to user
  const nm = [...w.document.querySelectorAll("#events input[type=text]")]
    .find(i => i.value === "install");
  check("events: predefined-tagged new row has an editable name input", !!nm);
  typeInto(w, nm.dataset.fid, "my_install_report");
  const plan6 = exportPlan(w);
  const mi = plan6.events.find(e => e.name === "my_install_report");
  check("events: renamed off-registry row exports kind custom", mi && mi.kind === "custom",
        JSON.stringify(mi));
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
  check("fields: gate reopens after resolving path dup", !gateBlocked(w));

  // charset: space+punct is red
  typeInto(w, second.dataset.fid, "My Field!");
  check("fields: non-identifier name blocks export", gateBlocked(w));
  typeInto(w, second.dataset.fid, "WalletGems");

  // acronym snake preview parity: XPBonus -> xp_bonus
  typeInto(w, second.dataset.fid, "XPBonus");
  check("fields: acronym-aware snake preview (xp_bonus)",
        w.document.querySelector("#player_fields").textContent.includes("path: xp_bonus"));
  typeInto(w, second.dataset.fid, "WalletGems");

  // stale-path clear: renaming re-derives the registration path
  const lr = rowByText(w, "player_fields", "LastRaceAt");
  clickPencil(w, "player_fields", "LastRaceAt");
  const lrInput = [...w.document.querySelectorAll("#player_fields input[type=text]")]
    .find(i => i.value === "LastRaceAt");
  typeInto(w, lrInput.dataset.fid, "LastRaceTime");
  const planP = exportPlan(w);
  const lrOut = planP.player_fields.find(f => f.name === "LastRaceTime");
  check("fields: rename clears the measured path (re-derived from the new name)",
        lrOut && !("path" in lrOut), JSON.stringify(lrOut));
  check("fields: preview follows the new name",
        w.document.querySelector("#player_fields").textContent.includes("path: last_race_time"));
  typeInto(w, w.document.querySelector('#player_fields input[type=text][value=""]') ? lrInput.dataset.fid : lrInput.dataset.fid, "LastRaceAt");

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
  check("fs: explicit re-pick reopens the gate", !gateBlocked(w));

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
  check("fs: unticking the dangling setting too reopens the gate", !gateBlocked(w));
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
  check("resources: enum-member default passes", !gateBlocked(w));

  // number default validation
  const kindSel2 = [...w.document.querySelectorAll("#resources select")].pop();
  setSelect(w, kindSel2, "number");
  check("resources: stale enum default on number turns red (kind toggle)", gateBlocked(w));
  typeInto(w, w.document.querySelector('#resources input[placeholder="default"]').dataset.fid, "42");
  check("resources: numeric default passes", !gateBlocked(w));
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
