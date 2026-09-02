"""Offline unit tests for skills/kinoa-inapp-template-from-image/generate_confirm_page.py.

Two layers, mirroring the split used elsewhere in this suite:

* `ConfirmPageGeneratorTests` — pure Python. The generator makes no network calls
  and reads no credentials; these pin the self-contained HTML, the data: URI
  image embedding (sniffed from magic bytes, not the extension) and the CLI's
  error paths.
* `ConfirmPageInteractionTests` — drives the REAL generated page in jsdom the way
  a developer would (typing char-by-char across re-renders, flipping selects,
  clicking) and asserts on the page's own `exportJson()` hand-back. Skips cleanly
  when Node or the jsdom package is missing:

      cd tests/page-harness && npm install   # one-time, installs jsdom locally

Run from the repo root:

    python -m unittest discover tests -v
"""

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "plugin", "skills", "kinoa-inapp-template-from-image")
SCRIPT_PATH = os.path.join(SKILL_DIR, "generate_confirm_page.py")
BUILDER_PATH = os.path.join(SKILL_DIR, "inapp_template_build.py")
HARNESS_DIR = os.path.join(REPO_ROOT, "tests", "page-harness")
JSDOM = os.path.join(HARNESS_DIR, "node_modules", "jsdom")

# 1x1 transparent PNG. Used both as a legitimate image and — renamed .jpg — to
# prove the generator sniffs the format instead of trusting the extension.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# Covers every bucket plus the three report channels that must never be dropped:
# an unknown role (unmapped), a client-rendered region (timer) and a role the
# picture cannot disambiguate (soft_billing_old_price -> needs_confirmation).
ANALYSIS = {
    "schema_version": "1.0",
    "source_image": {"path": "mockup.png", "width": 720, "height": 900},
    "template": {"suggested_name": "Spring Offer", "suggested_key": "spring_offer"},
    "feature": {"type": "standard", "confidence": 0.9},
    "unsupported": [{"what": "animated confetti burst", "why": "templates carry static art only"}],
    "elements": [
        {"role": "background_image", "bbox": {"x": 0.1, "y": 0.05, "w": 0.8, "h": 0.8},
         "confidence": 0.95},
        {"role": "close_button", "bbox": {"x": 0.82, "y": 0.04, "w": 0.08, "h": 0.06},
         "observed_text": "X"},
        {"role": "header", "bbox": {"x": 0.2, "y": 0.12, "w": 0.6, "h": 0.06},
         "observed_text": "HEADER"},
        {"role": "soft_billing_old_price", "bbox": {"x": 0.3, "y": 0.6, "w": 0.2, "h": 0.04},
         "observed_text": "$9.99"},
        {"role": "cta_button", "bbox": {"x": 0.3, "y": 0.7, "w": 0.4, "h": 0.08},
         "observed_text": "GET IT $4.99"},
        {"role": "info_button", "bbox": {"x": 0.08, "y": 0.06, "w": 0.06, "h": 0.05},
         "observed_text": "i",
         "custom_fields": [{"key": "glyph", "kind": "image", "name": "Glyph"}]},
        {"role": "timer", "bbox": {"x": 0.4, "y": 0.8, "w": 0.2, "h": 0.03},
         "observed_text": "02:14:00"},
        {"role": "fine_print", "bbox": {"x": 0.15, "y": 0.88, "w": 0.7, "h": 0.03}},
        {"role": "sparkle_thing", "bbox": {"x": 0.05, "y": 0.5, "w": 0.1, "h": 0.1},
         "observed_text": "???"},
        {"role": "toggle_custom", "suggested_key": "show_banner", "kind": "boolean",
         "suggested_name": "Show Banner"},
    ],
}

GAME_ID = "de0162c2-fe47-11ef-9654-68bc06a03806"

# jsdom driver. Loads the page, exposes a handful of user-level helpers, then
# evaluates the test's own snippet and prints its return value as JSON.
RUNNER_JS = r"""
const fs = require("fs");
const { JSDOM } = require(process.argv[2]);
const dom = new JSDOM(fs.readFileSync(process.argv[3], "utf-8"),
                      { runScripts: "dangerously", pretendToBeVisual: true });
const w = dom.window, d = dom.window.document;

function byFid(fid) {
  const el = d.querySelector('[data-fid="' + fid + '"]');
  if (!el) throw new Error("no element with data-fid " + fid);
  return el;
}
// Type one character at a time, re-querying after every keystroke: each input
// event re-renders the whole list, so this is the loop that would expose a
// focus/caret regression.
function typeInto(fid, text) {
  let el = byFid(fid);
  el.focus();
  el.value = "";
  el.dispatchEvent(new w.Event("input", { bubbles: true }));
  for (const ch of text) {
    el = byFid(fid);
    el.value = el.value + ch;
    el.dispatchEvent(new w.Event("input", { bubbles: true }));
  }
  return byFid(fid);
}
function setSelect(fid, value) {
  const el = byFid(fid);
  el.value = value;
  el.dispatchEvent(new w.Event("change", { bubbles: true }));
  return el;
}
function setMulti(fid, values) {
  const el = byFid(fid);
  [...el.options].forEach(o => { o.selected = values.indexOf(o.value) >= 0; });
  el.dispatchEvent(new w.Event("change", { bubbles: true }));
  return el;
}
function click(fid) {
  byFid(fid).dispatchEvent(new w.Event("click", { bubbles: true }));
}
function uidOf(selector) {
  const el = d.querySelector(selector);
  if (!el) throw new Error("no row matching " + selector);
  return el.dataset.uid;
}
// Rows are read-only until the pencil opens them (merge-plan doctrine), so most
// interactions start by opening the row(s) they touch.
function openRow(uid) { click("ed-" + uid); }
function openFirst(bucket) { const uid = uidOf("#elements .row.b-" + bucket); openRow(uid); return uid; }
function openAll() {
  [...d.querySelectorAll(".row")].map(r => r.dataset.uid).forEach(uid => {
    const b = d.querySelector('[data-fid="ed-' + uid + '"]');
    if (b && !b.disabled && b.textContent.indexOf("edit") >= 0) {
      b.dispatchEvent(new w.Event("click", { bubbles: true }));
    }
  });
}
// jsdom lays nothing out, so getBoundingClientRect() reports zeros — the page
// refuses to compute coordinates from that (it would write NaN into state).
// Placement tests stub a square stage and then drive real mouse/pointer events.
function stubStage(size) {
  const n = size || 1000;
  const st = d.getElementById("stage");
  st.getBoundingClientRect = () => ({ left: 0, top: 0, width: n, height: n,
                                      right: n, bottom: n, x: 0, y: 0 });
  return n;
}
// jsdom lays nothing out, so each row gets a synthetic rect (top = i*h) and the
// real pointer-drag path can then be driven end to end.
function stubRows(h) {
  h = h || 40;
  const rows = [...d.querySelectorAll("#elements .row")];
  rows.forEach((row, i) => {
    row.getBoundingClientRect = () => ({ top: i * h, bottom: (i + 1) * h, height: h,
                                         left: 0, right: 500, width: 500,
                                         x: 0, y: i * h });
  });
  return rows.map(r => r.dataset.uid);
}
function mouse(el, type, x, y) {
  el.dispatchEvent(new w.MouseEvent(type, { clientX: x, clientY: y, bubbles: true }));
}
function fidOf(selector) {
  const el = d.querySelector(selector);
  if (!el) throw new Error("no element matching " + selector);
  return el.dataset.fid;
}
const H = {
  typeInto, setSelect, setMulti, click, byFid, fidOf, uidOf, openRow, openFirst, openAll,
  stubStage, stubRows, mouse, stage: () => d.getElementById("stage"),
  rowUids: () => [...d.querySelectorAll("#elements .row")].map(r => r.dataset.uid),
  setActions: (uid, actions) => {
    const prefix = "act-" + uid + "-";
    const names = [...d.querySelectorAll('[data-fid^="' + prefix + '"]')]
      .map(el => el.dataset.fid.slice(prefix.length));
    names.forEach(a => {
      const el = d.querySelector('[data-fid="' + prefix + a + '"]');
      const want = actions.indexOf(a) >= 0;
      if (el && el.checked !== want) {
        el.checked = want;
        el.dispatchEvent(new w.Event("change", { bubbles: true }));
      }
    });
  },
  uidOfKey: k => [...d.querySelectorAll(".row")].find(
    r => r.textContent.indexOf(k) >= 0).dataset.uid,
  box: u => d.querySelector('#overlay .box[data-uid="' + u + '"]'),
  bboxOf: u => JSON.parse(w.exportJson()).corrections.missed
    .concat(JSON.parse(w.exportJson()).corrections.adjusted)[0],
  addRow: (bucket, key) => {
    click("add-" + bucket);
    const uid = [...d.querySelectorAll("#elements .row.b-" + bucket)].pop().dataset.uid;
    typeInto(uid + "-key", key);
    typeInto(uid + "-name", key);
    openRow(uid);          // ✓ done — collapse it again
    return uid;
  },
  counter: () => d.getElementById("counter").textContent,
  envelope: () => JSON.parse(w.exportJson()),
  exported: () => JSON.parse(w.exportJson()).payload,
  gated: () => ({ download: d.getElementById("download").disabled,
                  copy: d.getElementById("copy").disabled }),
  tick: (fid, on) => { const el = byFid(fid); el.checked = on;
                       el.dispatchEvent(new w.Event("change", { bubbles: true })); return el; },
  raw: () => w.exportJson(),
  status: () => ({ cls: d.getElementById("status").className,
                   text: d.getElementById("status").textContent }),
  has: (sel) => !!d.querySelector(sel),
  count: (sel) => d.querySelectorAll(sel).length,
  text: (sel) => { const e = d.querySelector(sel); return e ? e.textContent : null; },
  values: (sel) => [...d.querySelectorAll(sel)].map(e => e.value),
};

let value;
try {
  value = new Function("w", "d", "H", process.argv[4])(w, d, H);
} catch (err) {
  console.log(JSON.stringify({ ok: false, error: String((err && err.stack) || err) }));
  process.exit(3);
}
console.log(JSON.stringify({ ok: true, value: value === undefined ? null : value }));
"""


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_result(analysis=None, game_id=GAME_ID):
    """Exactly what `inapp_template_build.py build` prints, produced in-process."""
    builder = _load_module(BUILDER_PATH, "inapp_template_build_under_test")
    payload, report = builder.build_payload(json.loads(json.dumps(analysis or ANALYSIS)),
                                            game_id=game_id)
    validation = builder.validate_payload(payload)
    return {"ok": validation["ok"], "payload": payload, "report": report, "validation": validation}


class _PageCase(unittest.TestCase):
    """Shared plumbing: generate a page from a build result into a temp dir."""

    def setUp(self):
        self.mod = _load_module(SCRIPT_PATH, "generate_confirm_page_under_test")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def _run(self, build=None, extra_args=(), name="page.html"):
        build_path = self._write("build.json", build if build is not None else _build_result())
        out_path = os.path.join(self.tmp.name, name)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.mod.main(["--build", build_path, "--out", out_path, "--no-open",
                                  *extra_args])
        return code, json.loads(buf.getvalue()), out_path


class ConfirmPageGeneratorTests(_PageCase):
    def test_generates_self_contained_page(self):
        code, result, out_path = self._run()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertFalse(result["opened_in_browser"])  # --no-open
        html = _read(out_path)
        # A confirmation page has to work offline, from file://, forever.
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        for token in ("__KINOA_DATA__", "__KINOA_CONSTS__", "__KINOA_IMAGE__", "__KINOA_CSS__"):
            self.assertNotIn(token, html)
        for marker in ("spring_offer", "background_image", "cta_button", "show_banner"):
            self.assertIn(marker, html)

    def test_embedded_json_parses(self):
        _, _, out_path = self._run()
        data, consts, image = self._embedded(out_path)
        self.assertEqual(sorted(data),
                         ["generated_at", "image_fingerprint", "payload", "report", "validation"])
        self.assertIsNone(data["image_fingerprint"])   # no image on this fixture
        self.assertRegex(data["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(consts["buckets"], self.mod.BUCKETS)
        self.assertEqual(image, "")  # no image on this fixture

    def _embedded(self, out_path):
        import re
        html = _read(out_path)
        out = []
        for var in ("DATA", "C", "IMAGE_SRC"):
            m = re.search(r"^var %s = (.*);$" % var, html, re.M)
            self.assertIsNotNone(m, "missing embedded var " + var)
            out.append(json.loads(m.group(1)))
        return out

    def test_page_is_stamped_for_the_hand_back(self):
        _, result, out_path = self._run()
        self.assertRegex(result["page_generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        html = _read(out_path)
        self.assertIn(result["page_generated_at"], html)
        # The download filename carries a timestamp so a stale hand-back is visible.
        self.assertIn('"kinoa-inapp-template-"', html)
        self.assertIn('+ "-" + stamp + ".json"', html)

    def test_overlay_hit_testing_rules_are_present(self):
        # A full-bleed background box must not swallow clicks: labels are inert and
        # the whole overlay goes click-through while placement mode is active.
        _, _, out_path = self._run()
        html = _read(out_path)
        self.assertIn(".box .tag { pointer-events: none;", html)
        self.assertIn("#overlay.placing .box { pointer-events: none; }", html)
        # operator decision: the cluster reads place, done, remove — now enforced
        # by child order inside .row-actions, which owns the right alignment.
        self.assertIn(".row-actions { margin-left: auto; display: flex; "
                      "gap: 0.35rem; align-items: center; }", html)
        self.assertNotIn(".box.hl { box-shadow: 0 0 0 3px #ffd33d; z-index: 5; }", html)

    def test_add_buttons_use_the_bucket_palette(self):
        _, _, out_path = self._run()
        html = _read(out_path)
        self.assertIn(".add-cluster button.add-el { border-color: currentColor; }", html)
        self.assertIn(".add-cluster button.add-el:hover { background: #f6f8fa; }", html)
        # the hues are the very ones the legend swatches and the overlay boxes use
        for bucket, hex_ in (("images", "#0969da"), ("buttons", "#8250df"),
                             ("texts", "#bc4c00"), ("customs", "#1b7c83")):
            self.assertIn(".b-%s { color: %s; }" % (bucket, hex_), html)
            self.assertIn('<i style="background:%s"></i>' % hex_, html)   # legend swatch

    def test_stepper_visibility_rules_are_in_css(self):
        _, _, out_path = self._run()
        html = _read(out_path)
        self.assertIn(".row button.move { display: none; }", html)
        self.assertIn(".row.steppers-on button.move { display: inline-block; }", html)
        self.assertIn(".drop-line { height: 0; border-top: 2px solid #1f883d;", html)
        self.assertIn(".row .drag { cursor: grab;", html)

    def test_small_button_size_is_container_free(self):
        # These rules used to be scoped to `.grid > …`, so a button that was not a
        # direct child of a .grid (the custom-field ✕) fell back to the base size
        # and rendered larger than done/edit.
        _, _, out_path = self._run()
        html = _read(out_path)
        self.assertIn("button.pencil, button.remove, button.move {\n"
                      "  padding: 0.15rem 0.6rem; font-size: 0.85rem; }", html)
        # operator decision: no place BUTTON exists — the badge is the trigger
        self.assertNotIn("button.place", html)
        self.assertIn(".badge.place-badge { cursor: pointer; }", html)
        # operator decision: hover is a flat tint, never a border/ring
        self.assertIn(".badge.place-badge:hover { background: #f6f8fa; }", html)
        self.assertNotIn("place-badge:hover { box-shadow", html)
        self.assertIn("button.remove { color: #c0392b; }", html)
        # the per-button margin chain is gone entirely: a hidden or absent button
        # used to break the auto-margin hand-off and set the cluster adrift
        for dead in (".grid > button.pencil", ".grid > button.place", ".grid > button.remove",
                     ".grid > button.move {", ".grid > button.move.first",
                     ".grid > button.add-el"):
            self.assertNotIn(dead, html)
        self.assertIn(".row-actions { margin-left: auto;", html)
        # breathing room on BOTH sides: the summary above, the first row below
        self.assertIn(".add-cluster { display: flex; flex-wrap: wrap; gap: 0.35rem;\n"
                      "  margin-top: 0.5rem; margin-bottom: 1rem; }", html)

    def test_custom_field_add_button_layout_rules(self):
        # The button used to be an inline-block whose margin-top the line box
        # swallowed, letting a freshly added row ride over it.
        _, _, out_path = self._run()
        html = _read(out_path)
        self.assertIn(".cf-block .cf-rows { display: block; }", html)
        self.assertIn(".cf-block .cf-add { display: block; margin-top: 0.5rem; }", html)
        self.assertNotIn('add.style.marginTop', html)   # no inline band-aid left

    def test_payload_preview_is_collapsed_by_default(self):
        # The raw payload is debug material: it ships behind a native disclosure.
        _, _, out_path = self._run()
        html = _read(out_path)
        self.assertIn('<details class="card" id="preview-box">', html)
        self.assertIn("Payload that will be registered", html)
        # Author styles (.grid{display:flex}) override the UA's [hidden] rule —
        # the stylesheet must pin [hidden]{display:none !important} or the
        # feature panels stay visible in a real browser (jsdom can't catch this).
        self.assertIn("[hidden] { display: none !important; }", html)
        self.assertNotIn('id="preview-box" open', html)
        self.assertIn("details.card > summary", html)   # styled, not a bare marker

    def test_export_controls_live_in_the_footer(self):
        # House doctrine (merge-plan): the export pair sits in a fixed dark footer
        # with the counter and the undo hint; the top of the page is for editing.
        _, _, out_path = self._run()
        html = _read(out_path)
        footer = html[html.index("<footer>"):html.index("</footer>")]
        for marker in ('id="download"', 'id="copy"', 'id="counter"', "Ctrl+Z undo"):
            self.assertIn(marker, footer)
        self.assertNotIn('class="toolbar"', html)     # no sticky top toolbar any more
        header = html[html.index("<header>"):html.index("</header>")]
        self.assertIn("Confirm the in-app template", header)
        self.assertIn("footer { position: fixed", html)
        # Editing controls stay in the body, not the footer.
        self.assertNotIn('id="tpl-name"', footer)
        self.assertIn('id="tpl-name"', html)

    def test_image_inlined_as_data_uri(self):
        img = os.path.join(self.tmp.name, "mockup.png")
        with open(img, "wb") as f:
            f.write(PNG_BYTES)
        code, result, out_path = self._run(extra_args=["--image", img])
        self.assertEqual(code, 0)
        self.assertTrue(result["image_embedded"])
        self.assertEqual(result["image_source"], os.path.abspath(img))
        _, _, image = self._embedded(out_path)
        self.assertTrue(image.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(image.split(",", 1)[1]), PNG_BYTES)

    def test_fingerprint_hashes_the_bytes_not_the_name(self):
        # A PNG named .jpg still fingerprints as the same bytes, and the CLI
        # echoes the hash so the skill can log what the corrections attach to.
        img = os.path.join(self.tmp.name, "lying.jpg")
        with open(img, "wb") as f:
            f.write(PNG_BYTES)
        _, result, out_path = self._run(extra_args=["--image", img])
        self.assertEqual(result["image_sha256"], hashlib.sha256(PNG_BYTES).hexdigest())
        data, _, _ = self._embedded(out_path)
        self.assertEqual(data["image_fingerprint"]["filename"], "lying.jpg")
        self.assertEqual(data["image_fingerprint"]["sha256"], result["image_sha256"])
        self.assertEqual([data["image_fingerprint"]["width"],
                          data["image_fingerprint"]["height"]], [1, 1])

    def test_magic_bytes_beat_the_extension(self):
        # A PNG named .jpg must still be embedded, and as image/png.
        img = os.path.join(self.tmp.name, "lying.jpg")
        with open(img, "wb") as f:
            f.write(PNG_BYTES)
        _, result, out_path = self._run(extra_args=["--image", img])
        self.assertTrue(result["image_embedded"])
        _, _, image = self._embedded(out_path)
        self.assertTrue(image.startswith("data:image/png;base64,"))

    def test_non_image_rejected_despite_png_name(self):
        fake = os.path.join(self.tmp.name, "notreally.png")
        with open(fake, "w", encoding="utf-8") as f:
            f.write("this is text, not a picture")
        code, result, _ = self._run(extra_args=["--image", fake])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "unsupported_image")

    def test_renders_without_any_image(self):
        code, result, out_path = self._run()
        self.assertEqual(code, 0)
        self.assertFalse(result["image_embedded"])
        self.assertIsNone(result["image_source"])
        html = _read(out_path)
        self.assertIn('var IMAGE_SRC = "";', html)

    def test_image_falls_back_to_source_image_path(self):
        # report.source_image.path is resolved relative to the build file too.
        with open(os.path.join(self.tmp.name, "mockup.png"), "wb") as f:
            f.write(PNG_BYTES)
        _, result, _ = self._run()
        self.assertTrue(result["image_embedded"])
        self.assertEqual(os.path.basename(result["image_source"]), "mockup.png")

    def test_missing_image_is_an_error(self):
        code, result, _ = self._run(extra_args=["--image", os.path.join(self.tmp.name, "nope.png")])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "image_not_found")

    def test_rejects_non_build_json(self):
        code, result, _ = self._run(build={"resources": []})
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "missing_payload")

    def test_rejects_invalid_json(self):
        path = os.path.join(self.tmp.name, "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.mod.main(["--build", path, "--out",
                                  os.path.join(self.tmp.name, "x.html"), "--no-open"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(buf.getvalue())["error"], "invalid_json")

    def test_report_channels_reach_the_page(self):
        _, _, out_path = self._run()
        data, _, _ = self._embedded(out_path)
        report = data["report"]
        self.assertEqual([u["role"] for u in report["unmapped"]], ["sparkle_thing"])
        self.assertEqual([c["role"] for c in report["client_rendered"]], ["timer"])
        self.assertEqual([n["role"] for n in report["needs_confirmation"]],
                         ["soft_billing_old_price"])
        self.assertIn("billing", report["needs_confirmation"][0]["question"])

    def test_vocabulary_mirrors_the_builder(self):
        # The page's selects and its live validation must agree with the builder,
        # or the developer can author a payload the builder then rejects.
        builder = _load_module(BUILDER_PATH, "inapp_template_build_vocab")
        self.assertEqual(self.mod.CLICK_ACTIONS, list(builder.CLICK_ACTIONS))
        self.assertEqual(self.mod.ITEM_BEARING_ACTIONS, list(builder.ITEM_BEARING_ACTIONS))
        self.assertEqual(self.mod.KINDS, list(builder.KINDS))
        self.assertEqual(self.mod.FIELD_KINDS, list(builder.FIELD_KINDS))
        self.assertEqual(self.mod.FEATURE_TYPES, list(builder.FEATURE_TYPES))
        self.assertEqual(self.mod.BUCKETS, list(builder.BUCKETS))
        self.assertEqual(self.mod.ELEMENT_KEY_RE, builder.KEY_RE.pattern)
        self.assertEqual(self.mod.TEMPLATE_KEY_RE, builder.TEMPLATE_KEY_RE.pattern)
        self.assertEqual(self.mod.TEMPLATE_DESCRIPTION_MAX, builder.TEMPLATE_DESCRIPTION_MAX)
        # Feature seeds must match what the builder emits for an empty detection.
        public = lambda b: {k: v for k, v in b.items() if not k.startswith("_")}
        self.assertEqual(self.mod.MISSION_DEFAULTS, public(builder._mission_feature({})))
        self.assertEqual(self.mod.MILESTONE_DEFAULTS, public(builder._milestone_feature({})))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
@unittest.skipUnless(os.path.isdir(JSDOM),
                     "jsdom not installed — run `npm install` in tests/page-harness")
class ConfirmPageInteractionTests(_PageCase):
    def setUp(self):
        super().setUp()
        self.runner = os.path.join(self.tmp.name, "runner.js")
        with open(self.runner, "w", encoding="utf-8") as f:
            f.write(RUNNER_JS)

    def _with_image(self):
        """report.source_image.path resolves next to the build file, so dropping the
        PNG in the temp dir is what makes the overlay render."""
        with open(os.path.join(self.tmp.name, "mockup.png"), "wb") as f:
            f.write(PNG_BYTES)

    def drive(self, script, build=None):
        """Run `script` inside the generated page; return whatever it returns."""
        _, _, page = self._run(build=build)
        proc = subprocess.run(["node", self.runner, JSDOM, page, script],
                              capture_output=True, text=True)
        if proc.returncode != 0 and not proc.stdout.strip():
            self.fail("node failed: %s" % proc.stderr[-2000:])
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        if not out["ok"]:
            self.fail("page script raised: %s" % out["error"])
        return out["value"]

    # ---- export contract -------------------------------------------------
    def test_export_is_an_envelope_around_the_create_body(self):
        got = self.drive("""
            const env = H.envelope();
            return { env: Object.keys(env), keys: Object.keys(env.payload), raw: H.raw(),
                     corrections: env.corrections,
                     // leak check runs over the payload alone: "confirmed_at" legitimately
                     // contains "confirm" at envelope level
                     body: JSON.stringify(env.payload),
                     confirmed: env.confirmed_at, stamped: env.page_generated_at };
        """)
        self.assertEqual(got["env"], ["confirmed_at", "page_generated_at", "corrections", "payload"])
        # a freshly built page has corrected nothing yet, but the arrays are always there
        self.assertEqual(got["corrections"], {"source_image": None, "missed": [],
                                              "adjusted": [], "excluded": []})
        self.assertRegex(got["confirmed"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertRegex(got["stamped"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(got["keys"], ["name", "key", "description", "gameId",
                                       "images", "buttons", "texts", "customs",
                                       "featureType", "features", "tagsIds"])
        for leaked in ("bbox", "report", "validation", "unmapped", "client_rendered",
                       "needs_confirmation", "observed_text", "confidence", "uid",
                       "\"role\"", "confirm"):
            self.assertNotIn(leaked, got["body"], "%s leaked into the payload" % leaked)

    def test_indexes_are_dense_across_all_buckets(self):
        got = self.drive("""
            const p = H.exported();
            const flat = [].concat(p.images, p.buttons, p.texts, p.customs);
            return { idx: flat.map(e => e.index), keys: flat.map(e => e.key) };
        """)
        # Dense and unique over the whole template — NOT sorted within a bucket:
        # the global sequence interleaves buckets, so image #1 can follow text #0.
        self.assertEqual(sorted(got["idx"]), list(range(len(got["idx"]))))
        self.assertEqual(got["keys"][0], "background_image")   # payload shape unchanged

    def test_reindex_follows_an_added_row(self):
        got = self.drive("""
            H.addRow("images", "extra_art");
            const p = H.exported();
            const flat = [].concat(p.images, p.buttons, p.texts, p.customs);
            return { idx: flat.map(e => e.index), images: p.images.map(e => e.key),
                     added: p.images.find(e => e.key === "extra_art").index };
        """)
        self.assertEqual(sorted(got["idx"]), list(range(len(got["idx"]))))
        # a page-added row lands at the END of the global sequence
        self.assertEqual(got["added"], len(got["idx"]) - 1)
        self.assertEqual(got["images"], ["background_image", "extra_art"])

    def test_rows_have_no_bucket_select(self):
        # Re-bucketing was removed on purpose: it rewrote an element's shape
        # silently and told the corpus nothing. Un-tick + add is the flow now.
        got = self.drive("""
            H.openAll();
            return { buckets: H.count('[data-fid$="-bucket"]'),
                     selects: [...d.querySelectorAll(".row select")].map(
                       s => s.dataset.fid.replace(/^e\\d+-/, "")),
                     keys: H.count('.row [data-fid^="e"][data-fid$="-key"]') };
        """)
        self.assertEqual(got["buckets"], 0)
        self.assertNotIn("bucket", got["selects"])
        self.assertGreater(got["keys"], 0)      # the rest of the editor is intact

    def test_export_round_trips_through_the_builder(self):
        payload = self.drive("return H.envelope().payload;")
        builder = _load_module(BUILDER_PATH, "inapp_template_build_roundtrip")
        self.assertEqual(builder.validate_payload(payload), {"ok": True, "errors": [], "warnings": []})

    # ---- select-first, gate, undo ----------------------------------------
    def test_unticking_a_row_excludes_it_without_deleting_it(self):
        got = self.drive("""
            const row = [...d.querySelectorAll("#elements .row.b-texts")][0];
            const uid = row.dataset.uid;
            H.openRow(uid);
            const key = H.byFid(uid + "-key").value;
            const name = H.byFid(uid + "-name").value;
            H.openRow(uid);                       // ✓ done — back to read-only
            H.tick("inc-" + uid, false);
            const off = {
              keys: H.exported().texts.map(e => e.key),
              idx: [].concat(H.exported().images, H.exported().buttons,
                             H.exported().texts, H.exported().customs).map(e => e.index),
              dimmed: d.querySelector('.row[data-uid="' + uid + '"]').classList.contains("excluded"),
              rowStillThere: !!d.querySelector('.row[data-uid="' + uid + '"]'),
              indexCell: d.querySelector('.row[data-uid="' + uid + '"] .badge').textContent,
              listSummary: H.text("#elements-summary"),
              gated: H.gated(),
              // an excluded row cannot be opened — it ships nothing
              pencilOff: H.byFid("ed-" + uid).disabled,
              summary: d.querySelector('.row[data-uid="' + uid + '"]').textContent };
            H.tick("inc-" + uid, true);
            H.openRow(uid);
            const back = { keys: H.exported().texts.map(e => e.key),
                           dimmed: d.querySelector('.row[data-uid="' + uid + '"]').classList.contains("excluded"),
                           // the row keeps every field it had — nothing was destroyed
                           nameKept: H.byFid(uid + "-name").value };
            return { key, name, off, back };
        """)
        self.assertNotIn(got["key"], got["off"]["keys"])
        self.assertEqual(sorted(got["off"]["idx"]), list(range(len(got["off"]["idx"]))))
        self.assertTrue(got["off"]["dimmed"])
        self.assertTrue(got["off"]["rowStillThere"])
        self.assertEqual(got["off"]["indexCell"], "excluded")  # no index badge
        self.assertIn("2 of 3 texts", got["off"]["listSummary"])
        self.assertTrue(got["off"]["pencilOff"])
        self.assertIn(got["key"], got["off"]["summary"])       # data still on the page
        self.assertFalse(got["off"]["gated"]["download"])      # still exportable
        self.assertIn(got["key"], got["back"]["keys"])         # re-ticking restores
        self.assertFalse(got["back"]["dimmed"])
        self.assertEqual(got["back"]["nameKept"], got["name"])

    def test_excluded_row_keeps_its_overlay_box_greyed(self):
        self._with_image()
        got = self.drive("""
            const row = [...d.querySelectorAll("#elements .row.b-texts")][0];
            const uid = row.dataset.uid;
            const before = H.count("#overlay .box.excluded");
            H.tick("inc-" + uid, false);
            const off = { excluded: H.count("#overlay .box.excluded"),
                          label: d.querySelector('#overlay .box.excluded .tag').textContent,
                          joined: !!d.querySelector('#overlay .box[data-uid="' + uid + '"]') };
            H.tick("inc-" + uid, true);
            return { before, off, after: H.count("#overlay .box.excluded") };
        """)
        self.assertEqual(got["before"], 0)
        self.assertEqual(got["off"]["excluded"], 1)
        self.assertIn("excluded", got["off"]["label"])
        self.assertTrue(got["off"]["joined"])   # bbox<->row join survives
        self.assertEqual(got["after"], 0)

    def test_proposed_rows_have_no_destructive_remove(self):
        got = self.drive("""
            const before = { removes: H.count('[data-fid^="rm-"]'),
                             incs: H.count("input.inc") };
            H.click("add-texts");
            const rows = [...d.querySelectorAll("#elements .row.b-texts")];
            const added = rows[rows.length - 1];
            const after = { removes: H.count('[data-fid^="rm-"]'),
                            onAdded: !!added.querySelector('[data-fid^="rm-"]'),
                            opensEditing: !!added.querySelector('[data-fid^="e"][data-fid$="-key"]') };
            H.click("rm-" + added.dataset.uid);
            after.rowsAfterRemoval = H.count("#elements .row.b-texts");
            return { before, after };
        """)
        self.assertEqual(got["before"]["removes"], 0)    # nothing proposed is deletable
        self.assertEqual(got["before"]["incs"], 8)       # every row has a checkbox
        self.assertEqual(got["after"]["removes"], 1)     # only the page-added row
        self.assertTrue(got["after"]["onAdded"])
        self.assertTrue(got["after"]["opensEditing"])    # a fresh row opens ready to type
        self.assertEqual(got["after"]["rowsAfterRemoval"], 3)

    def test_export_is_gated_while_invalid(self):
        got = self.drive("""
            const clean = H.gated();
            const uid = H.openFirst("images");
            const opened = { gated: H.gated(), counter: H.counter() };
            const fid = uid + "-key";
            H.typeInto(fid, "Bad Key");
            const broken = { gated: H.gated(), status: H.status(), counter: H.counter(),
                             preview: d.getElementById("preview").textContent.length > 0 };
            H.typeInto(fid, "bg_art");
            const fixedOpen = H.gated();
            H.openRow(uid);                                  // ✓ done
            return { clean, opened, broken, fixedOpen, fixed: H.gated() };
        """)
        self.assertFalse(got["clean"]["download"])
        # an open editor alone blocks the export (merge-plan's completeness rule)
        self.assertTrue(got["opened"]["gated"]["download"])
        self.assertIn("finish editing 1 row(s)", got["opened"]["counter"])
        self.assertTrue(got["broken"]["gated"]["download"])
        self.assertTrue(got["broken"]["gated"]["copy"])
        self.assertIn("fix to enable export", got["broken"]["status"]["text"])
        self.assertIn("validation error(s)", got["broken"]["counter"])
        self.assertTrue(got["broken"]["preview"])   # preview stays visible
        self.assertTrue(got["fixedOpen"]["download"])   # still open for editing
        self.assertFalse(got["fixed"]["download"])
        self.assertFalse(got["fixed"]["copy"])

    def test_excluding_an_invalid_row_unblocks_the_export(self):
        got = self.drive("""
            const uid = H.openFirst("images");
            H.typeInto(uid + "-key", "Bad Key");
            const broken = { gated: H.gated(), errors: H.text("#live-errors") };
            H.tick("inc-" + uid, false);
            return { broken, excluded: { gated: H.gated(), status: H.status(),
                                         images: H.exported().images.length } };
        """)
        self.assertTrue(got["broken"]["gated"]["download"])
        self.assertFalse(got["excluded"]["gated"]["download"])
        self.assertEqual(got["excluded"]["status"]["cls"], "ok")
        self.assertEqual(got["excluded"]["images"], 0)

    def test_undo_and_redo_a_field_edit_and_an_exclusion(self):
        got = self.drive("""
            // Read names off the export, not the DOM: rewinding far enough also
            // closes the row (editing is part of the snapshot), so the input is gone.
            const nameNow = () => (H.exported().texts.find(e => e.key === "header") || {}).name;
            const uid = H.openFirst("texts");
            const fid = uid + "-name";
            const original = nameNow();
            H.typeInto(fid, "Renamed Header");
            const edited = nameNow();
            H.tick("inc-" + uid, false);
            const excluded = H.exported().texts.length;

            w.undo();                                  // undo the exclusion
            const afterUndo1 = { texts: H.exported().texts.length,
                                 ticked: H.byFid("inc-" + uid).checked };
            for (let i = 0; i < 30; i++) w.undo();     // undo the rename, char by char
            const afterUndo2 = nameNow();
            for (let i = 0; i < 30; i++) w.redo();     // ... and forward again
            const afterRedo = { name: nameNow() || null, texts: H.exported().texts.length };
            return { original, edited, excluded, afterUndo1, afterUndo2, afterRedo };
        """)
        self.assertEqual(got["edited"], "Renamed Header")
        self.assertEqual(got["excluded"], 2)
        self.assertEqual(got["afterUndo1"]["texts"], 3)   # exclusion undone
        self.assertTrue(got["afterUndo1"]["ticked"])
        self.assertEqual(got["afterUndo2"], got["original"])
        self.assertIsNone(got["afterRedo"]["name"])      # excluded again, so absent
        self.assertEqual(got["afterRedo"]["texts"], 2)

    def test_undo_restores_the_header_and_feature_panel(self):
        got = self.drive("""
            const feat = d.getElementById("tpl-feature");
            feat.value = "milestone"; feat.dispatchEvent(new w.Event("change", {bubbles:true}));
            const on = { features: H.exported().features,
                         hidden: d.getElementById("fp-milestone").hidden };
            w.undo();
            return { on: on, features: H.exported().features,
                     select: d.getElementById("tpl-feature").value,
                     hidden: d.getElementById("fp-milestone").hidden };
        """)
        self.assertEqual(sorted(got["on"]["features"]), ["milestone"])
        self.assertFalse(got["on"]["hidden"])
        self.assertEqual(got["features"], {})     # back to standard
        self.assertEqual(got["select"], "standard")
        self.assertTrue(got["hidden"])

    # ---- read-only rows, pencil mode -------------------------------------
    def test_rows_start_read_only(self):
        got = self.drive("""
            return { rows: H.count(".row"),
                     inputs: H.count(".row input[type=text]"),
                     selects: H.count(".row select"),
                     pencils: H.count('[data-fid^="ed-"]'),
                     incs: H.count("input.inc"),
                     firstRow: d.querySelector("#elements .row.b-texts").textContent,
                     gated: H.gated(), counter: H.counter() };
        """)
        self.assertEqual(got["rows"], 8)
        self.assertEqual(got["inputs"], 0)      # nothing editable until the pencil
        self.assertEqual(got["selects"], 0)
        self.assertEqual(got["pencils"], 8)
        self.assertEqual(got["incs"], 8)
        self.assertIn("header", got["firstRow"])          # read-only summary
        # facts, minus the dashboard-side ones (header is built nullable:false)
        self.assertIn("required", got["firstRow"])
        self.assertNotIn("textLimit", got["firstRow"])
        self.assertFalse(got["gated"]["download"])
        self.assertIn("to register:", got["counter"])

    def test_pencil_opens_and_closes_a_row(self):
        got = self.drive("""
            const uid = H.uidOf("#elements .row.b-texts");
            const closed = { label: H.byFid("ed-" + uid).textContent,
                             inputs: H.count('.row[data-uid="' + uid + '"] input[type=text]') };
            H.openRow(uid);
            const open = { label: H.byFid("ed-" + uid).textContent,
                           inputs: H.count('.row[data-uid="' + uid + '"] input[type=text]'),
                           gated: H.gated(), counter: H.counter() };
            H.openRow(uid);
            const again = { label: H.byFid("ed-" + uid).textContent,
                            inputs: H.count('.row[data-uid="' + uid + '"] input[type=text]'),
                            gated: H.gated() };
            return { closed, open, again };
        """)
        self.assertIn("edit", got["closed"]["label"])
        self.assertEqual(got["closed"]["inputs"], 0)
        self.assertIn("done", got["open"]["label"])
        self.assertGreaterEqual(got["open"]["inputs"], 3)
        self.assertTrue(got["open"]["gated"]["download"])       # open editor blocks export
        self.assertIn("finish editing 1 row(s)", got["open"]["counter"])
        self.assertIn("edit", got["again"]["label"])
        self.assertEqual(got["again"]["inputs"], 0)
        self.assertFalse(got["again"]["gated"]["download"])

    def test_invalid_row_force_opens_and_stays_open(self):
        build = _build_result()
        build["payload"]["texts"][0]["key"] = "Bad Key"   # as if the build were edited
        got = self.drive("""
            const row = [...d.querySelectorAll("#elements .row.b-texts")].find(
              r => r.querySelector('[data-fid$="-key"]'));
            const uid = row.dataset.uid;
            const onLoad = { opened: true, label: H.byFid("ed-" + uid).textContent,
                             invalid: row.classList.contains("invalid"),
                             gated: H.gated() };
            H.openRow(uid);                       // try to close while still invalid
            const stillOpen = H.count('.row[data-uid="' + uid + '"] input[type=text]') > 0;
            H.typeInto(uid + "-key", "header_fixed");
            const afterFix = { open: H.count('.row[data-uid="' + uid + '"] input[type=text]') > 0,
                               gated: H.gated() };
            H.openRow(uid);                       // ✓ done now works
            return { onLoad, stillOpen, afterFix, closed: H.gated() };
        """, build=build)
        self.assertIn("done", got["onLoad"]["label"])   # force-opened on load
        self.assertTrue(got["onLoad"]["invalid"])
        self.assertTrue(got["onLoad"]["gated"]["download"])
        self.assertTrue(got["stillOpen"])               # cannot be collapsed while invalid
        self.assertTrue(got["afterFix"]["open"])        # sticky until ✓ done
        self.assertTrue(got["afterFix"]["gated"]["download"])
        self.assertFalse(got["closed"]["download"])

    # ---- payload preview, feature isolation ------------------------------
    def test_feature_select_speaks_product_names_but_exports_wire_values(self):
        # operator decision: label "feature", options none/missions/milestones;
        # option VALUES stay standard/mission/milestone (the wire contract).
        got = self.drive("""
          const opts = [...d.querySelectorAll('#tpl-feature option')]
                        .map(o => [o.value, o.textContent]);
          const sel = d.getElementById('tpl-feature');
          sel.value = 'milestone';
          sel.dispatchEvent(new w.Event('change', { bubbles: true }));
          return { opts: opts, exported: H.exported().featureType,
                   label: d.getElementById('tpl-feature').previousElementSibling.textContent };
        """)
        self.assertEqual(got["opts"], [["standard", "none"], ["mission", "missions"], ["milestone", "milestones"]])
        self.assertEqual(got["exported"], "milestone")
        self.assertEqual(got["label"], "feature")

    def test_payload_preview_toggles_and_stays_current(self):
        got = self.drive("""
            const box = d.getElementById("preview-box");
            const closed = { open: box.open, summary: box.querySelector("summary").textContent,
                             content: d.getElementById("preview").textContent };
            // edits land in the <pre> even while the disclosure is shut
            const uid = H.openFirst("images");
            H.typeInto(uid + "-name", "Backdrop");
            H.openRow(uid);
            const whileClosed = { open: box.open,
                                  // confirmed_at is stamped per call, so compare the stable part
                                  current: JSON.stringify(JSON.parse(
                                    d.getElementById("preview").textContent).payload)
                                    === JSON.stringify(H.envelope().payload),
                                  hasEdit: d.getElementById("preview").textContent.indexOf("Backdrop") >= 0,
                                  gated: H.gated() };
            box.open = true;
            return { closed, whileClosed, opened: box.open,
                     content: d.getElementById("preview").textContent };
        """)
        self.assertFalse(got["closed"]["open"])
        self.assertIn("Payload that will be registered", got["closed"]["summary"])
        self.assertIn('"payload"', got["closed"]["content"])   # rendered even when shut
        self.assertFalse(got["whileClosed"]["open"])
        self.assertTrue(got["whileClosed"]["current"])
        self.assertTrue(got["whileClosed"]["hasEdit"])
        self.assertFalse(got["whileClosed"]["gated"]["download"])  # gate ignores the preview
        self.assertTrue(got["opened"])
        self.assertIn("Backdrop", got["content"])

    def test_feature_fields_are_isolated_per_type(self):
        got = self.drive("""
            const feat = d.getElementById("tpl-feature");
            const mp = d.getElementById("fp-mission"), ml = d.getElementById("fp-milestone");
            function pick(v) { feat.value = v; feat.dispatchEvent(new w.Event("change", {bubbles:true})); }
            const std = { mission: mp.hidden, milestone: ml.hidden, features: H.exported().features,
                          raw: JSON.stringify(H.exported().features) };
            pick("mission");
            const mission = { mission: mp.hidden, milestone: ml.hidden,
                              keys: Object.keys(H.exported().features),
                              block: Object.keys(H.exported().features.mission),
                              raw: JSON.stringify(H.exported().features) };
            pick("milestone");
            const milestone = { mission: mp.hidden, milestone: ml.hidden,
                                keys: Object.keys(H.exported().features),
                                block: Object.keys(H.exported().features.milestone),
                                raw: JSON.stringify(H.exported().features) };
            return { std, mission, milestone };
        """)
        self.assertTrue(got["std"]["mission"])
        self.assertTrue(got["std"]["milestone"])
        self.assertEqual(got["std"]["features"], {})
        self.assertEqual(got["std"]["raw"], "{}")

        self.assertFalse(got["mission"]["mission"])
        self.assertTrue(got["mission"]["milestone"])
        self.assertEqual(got["mission"]["keys"], ["mission"])
        self.assertNotIn("limit", got["mission"]["block"])       # milestone-only field
        self.assertNotIn("milestone", got["mission"]["raw"])

        self.assertFalse(got["milestone"]["milestone"])
        self.assertTrue(got["milestone"]["mission"])
        self.assertEqual(got["milestone"]["keys"], ["milestone"])
        self.assertIn("limit", got["milestone"]["block"])
        for mission_only in ("maxPlacements", "minPlacements", "maxSetsCount", "minSetsCount"):
            self.assertNotIn(mission_only, got["milestone"]["raw"])

    def test_feature_stash_never_leaks_into_the_export(self):
        got = self.drive("""
            const feat = d.getElementById("tpl-feature");
            function pick(v) { feat.value = v; feat.dispatchEvent(new w.Event("change", {bubbles:true})); }
            function edit(id, val) { const el = d.getElementById(id); el.value = val;
              el.dispatchEvent(new w.Event("input", {bubbles:true})); }

            pick("mission");
            edit("fp-maxPlacements", "7");
            const mission = H.raw();

            pick("milestone");
            edit("fp-limit", "9");
            const milestone = { raw: H.raw(), features: H.exported().features };

            // the hidden panel's input must not be able to reach the payload
            edit("fp-maxPlacements", "42");
            const afterHiddenEdit = { raw: H.raw(), features: H.exported().features };

            pick("standard");
            const std = { raw: H.raw(), features: H.exported().features };

            pick("mission");   // stash brings 7 back, page-side only
            const backToMission = { maxPlacements: H.exported().features.mission.maxPlacements,
                                    keys: Object.keys(H.exported().features) };
            return { mission, milestone, afterHiddenEdit, std, backToMission };
        """)
        self.assertIn('"maxPlacements": 7', got["mission"])
        # after the flip, nothing mission-shaped survives in the hand-back
        self.assertNotIn("maxPlacements", got["milestone"]["raw"])
        self.assertEqual(got["milestone"]["features"], {"milestone": {
            "key": "main_progressbar", "name": "Main Progressbar", "limit": 9}})
        self.assertNotIn("maxPlacements", got["afterHiddenEdit"]["raw"])
        self.assertEqual(got["afterHiddenEdit"]["features"], got["milestone"]["features"])
        self.assertEqual(got["std"]["features"], {})
        for leaked in ("mission", "milestone", "limit", "maxPlacements"):
            self.assertNotIn(leaked, got["std"]["raw"].split('"features"')[1])
        self.assertEqual(got["backToMission"]["maxPlacements"], 7)
        self.assertEqual(got["backToMission"]["keys"], ["mission"])

    # ---- corrections: mockup fingerprint ---------------------------------
    def test_corrections_carry_a_fingerprint_of_the_mockup(self):
        self._with_image()
        got = self.drive("""
            return { fp: H.envelope().corrections.source_image,
                     // the picture itself must never ride along
                     raw: H.raw().indexOf("base64") };
        """)
        self.assertEqual(got["fp"], {"sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
                                     "width": 1, "height": 1, "filename": "mockup.png"})
        self.assertEqual(got["raw"], -1)

    def test_fingerprint_is_null_without_a_mockup(self):
        got = self.drive("return H.envelope().corrections.source_image;")
        self.assertIsNone(got)

    # ---- geometry corrections on DETECTED boxes --------------------------
    def test_moving_a_detected_box_is_reported_as_adjusted(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.uidOfKey("cta_button");
            const payload0 = JSON.stringify(H.envelope().payload);
            const before = H.envelope().corrections;
            H.mouse(H.box(uid), "pointerdown", 400, 700);
            H.mouse(d, "pointermove", 500, 750);
            H.mouse(d, "pointerup", 500, 750);
            const after = { corrections: H.envelope().corrections,
                            payload: JSON.stringify(H.envelope().payload),
                            solid: !H.box(uid).classList.contains("placed"),
                            movable: H.box(uid).classList.contains("movable") };
            w.undo();
            const undone = { corrections: H.envelope().corrections,
                             payload: JSON.stringify(H.envelope().payload) };
            return { payload0, before, after, undone };
        """)
        self.assertEqual(got["before"]["adjusted"], [])
        adj = got["after"]["corrections"]["adjusted"]
        self.assertEqual(len(adj), 1)
        self.assertEqual([adj[0]["key"], adj[0]["bucket"]], ["cta_button", "buttons"])
        self.assertEqual(adj[0]["original_bbox"], {"x": 0.3, "y": 0.7, "w": 0.4, "h": 0.08})
        self.assertAlmostEqual(adj[0]["bbox"]["x"], 0.4, places=6)
        self.assertAlmostEqual(adj[0]["bbox"]["y"], 0.75, places=6)
        self.assertEqual([adj[0]["bbox"]["w"], adj[0]["bbox"]["h"]], [0.4, 0.08])
        self.assertEqual(got["after"]["corrections"]["missed"], [])   # not a page-added row
        self.assertTrue(got["after"]["solid"])      # dashed stays reserved for hand-placed
        self.assertTrue(got["after"]["movable"])
        # geometry never reaches the template
        self.assertEqual(got["after"]["payload"], got["payload0"])
        # one undo restores both the geometry and the adjusted flag
        self.assertEqual(got["undone"]["corrections"]["adjusted"], [])
        self.assertEqual(got["undone"]["payload"], got["payload0"])

    def test_resizing_clamps_to_the_image_and_a_minimum_size(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.uidOfKey("header");
            // drag the SE corner far past the bottom-right corner of the image
            H.mouse(H.byFid("rz-se-" + uid), "pointerdown", 700, 180);
            H.mouse(d, "pointermove", 5000, 5000);
            H.mouse(d, "pointerup", 5000, 5000);
            const grown = H.envelope().corrections.adjusted[0].bbox;

            // now crush it with the same corner
            H.mouse(H.byFid("rz-se-" + uid), "pointerdown", 1000, 1000);
            H.mouse(d, "pointermove", -5000, -5000);
            H.mouse(d, "pointerup", -5000, -5000);
            const crushed = H.envelope().corrections.adjusted[0].bbox;

            // NW corner keeps the opposite edges pinned
            H.mouse(H.byFid("rz-nw-" + uid), "pointerdown", 0, 0);
            H.mouse(d, "pointermove", -5000, -5000);
            H.mouse(d, "pointerup", -5000, -5000);
            const nw = H.envelope().corrections.adjusted[0].bbox;
            const z = { small: Number(H.box(uid).style.zIndex),
                        bg: Number(H.box(H.uidOfKey("background_image")).style.zIndex) };
            return { grown, crushed, nw, z };
        """)
        g = got["grown"]
        self.assertAlmostEqual(g["x"] + g["w"], 1.0, places=6)   # clamped at the right edge
        self.assertAlmostEqual(g["y"] + g["h"], 1.0, places=6)
        c = got["crushed"]
        self.assertAlmostEqual(c["w"], 0.02, places=6)           # min span, never inverted
        self.assertAlmostEqual(c["h"], 0.02, places=6)
        n = got["nw"]
        self.assertEqual([n["x"], n["y"]], [0, 0])               # grew up-left to the corner
        # the corner opposite the grabbed one never moves
        self.assertAlmostEqual(n["x"] + n["w"], c["x"] + c["w"], places=6)
        self.assertAlmostEqual(n["y"] + n["h"], c["y"] + c["h"], places=6)
        self.assertGreater(got["z"]["small"], got["z"]["bg"])    # z-order follows the new area

    def test_a_jiggle_below_the_threshold_is_not_a_move(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.uidOfKey("cta_button");
            const texts = H.uidOfKey("header");
            H.tick("inc-" + texts, false);          // one real, undoable step
            H.mouse(H.box(uid), "pointerdown", 400, 700);
            H.mouse(d, "pointermove", 401, 701);     // 2px of travel
            H.mouse(d, "pointerup", 401, 701);
            const after = { adjusted: H.envelope().corrections.adjusted,
                            excluded: H.envelope().corrections.excluded.length };
            w.undo();                                // must undo the EXCLUSION
            return { after, undone: H.envelope().corrections.excluded.length };
        """)
        self.assertEqual(got["after"]["adjusted"], [])   # no geometry change
        self.assertEqual(got["after"]["excluded"], 1)
        self.assertEqual(got["undone"], 0)               # the jiggle pushed no undo step

    def test_excluded_vision_rows_ship_as_false_positives(self):
        got = self.drive("""
            const uid = H.uidOfKey("soft_billing_old_price");
            H.tick("inc-" + uid, false);
            return { excluded: H.envelope().corrections.excluded,
                     texts: H.envelope().payload.texts.map(e => e.key) };
        """)
        self.assertEqual(got["excluded"], [{"key": "soft_billing_old_price", "bucket": "texts",
                                            "role": "soft_billing_old_price"}])
        self.assertNotIn("soft_billing_old_price", got["texts"])

    # ---- global index ordering -------------------------------------------
    def _builder_indexes(self, build):
        return {(b, el["key"]): el["index"]
                for b in self.mod.BUCKETS for el in build["payload"][b]}

    def test_indexes_reproduce_the_builders_reading_order(self):
        # index IS the dashboard constructor's display order, and production
        # templates interleave buckets — exporting bucket-grouped indexes would
        # silently reshuffle the pop-up.
        build = _build_result()
        expected = self._builder_indexes(build)
        by_index = [b for (b, _k), i in sorted(expected.items(), key=lambda kv: kv[1])]
        # the fixture must genuinely interleave, or this test proves nothing
        self.assertNotEqual(by_index, sorted(by_index, key=self.mod.BUCKETS.index))

        got = self.drive("return H.exported();", build=build)
        actual = {(b, el["key"]): el["index"]
                  for b in self.mod.BUCKETS for el in got[b]}
        self.assertEqual(actual, expected)

    def test_up_and_down_step_through_the_global_sequence(self):
        got = self.drive("""
            const order = () => {
              const p = H.exported();
              return [].concat(p.images, p.buttons, p.texts, p.customs)
                .sort((a, b) => a.index - b.index).map(e => e.key);
            };
            const before = order();
            const first = H.uidOfKey(before[0]), second = H.uidOfKey(before[1]);
            const last = H.uidOfKey(before[before.length - 1]);
            const ends = { upAtStart: H.byFid("mv-up-" + first).disabled,
                           downAtStart: H.byFid("mv-dn-" + first).disabled,
                           downAtEnd: H.byFid("mv-dn-" + last).disabled,
                           upAtEnd: H.byFid("mv-up-" + last).disabled };
            H.click("mv-up-" + second);
            const afterUp = order();
            const badge = d.querySelector('.row[data-uid="' + second + '"] .badge').textContent;
            H.click("mv-dn-" + last);            // disabled -> no-op
            const afterNoop = order();
            H.click("mv-dn-" + second);          // back where it started
            return { before, ends, afterUp, badge, afterNoop, restored: order() };
        """)
        b = got["before"]
        self.assertTrue(got["ends"]["upAtStart"])     # nothing above the first
        self.assertFalse(got["ends"]["downAtStart"])
        self.assertTrue(got["ends"]["downAtEnd"])     # nothing below the last
        self.assertFalse(got["ends"]["upAtEnd"])
        self.assertEqual(got["afterUp"], [b[1], b[0]] + b[2:])
        self.assertEqual(got["badge"], "#0")         # the badge follows the move
        self.assertEqual(got["afterNoop"], got["afterUp"])   # a disabled ↓ changes nothing
        self.assertEqual(got["restored"], b)

    def test_a_move_steps_past_an_element_of_another_bucket(self):
        got = self.drive("""
            // the payload carries no bucket field — an element's bucket IS the
            // array it sits in, so tag while flattening
            const order = () => {
              const p = H.exported();
              const tagged = [];
              ["images", "buttons", "texts", "customs"].forEach(
                b => (p[b] || []).forEach(e => tagged.push({ b: b, e: e })));
              return tagged.sort((x, y) => x.e.index - y.e.index).map(x => x.b + ":" + x.e.key);
            };
            const before = order();
            // global #1 is an image sitting between two buttons in the fixture
            const uid = H.uidOfKey("background_image");
            const posBefore = [...d.querySelectorAll("#elements .row")]
              .findIndex(r => r.dataset.uid === uid);
            const bucketBefore = d.querySelector('.row[data-uid="' + uid + '"]')
              .className;
            H.click("mv-up-" + uid);
            const after = order();
            const row = d.querySelector('.row[data-uid="' + uid + '"]');
            return { before, after, posBefore, bucketBefore,
                     posAfter: [...d.querySelectorAll("#elements .row")]
                       .findIndex(r => r.dataset.uid === uid),
                     bucketAfter: row.className,
                     bucketBadge: [...row.querySelectorAll(".badge")]
                       .map(b => b.textContent).join(","),
                     bucketsUnchanged: H.exported().images.some(e => e.key === "background_image"),
                     badge: row.querySelector(".badge").textContent };
        """)
        self.assertEqual(got["before"][0], "buttons:close_button")
        self.assertEqual(got["before"][1], "images:background_image")
        # they swap across bucket lines in the global sequence
        self.assertEqual(got["after"][0], "images:background_image")
        self.assertEqual(got["after"][1], "buttons:close_button")
        # the row physically moves up in the one flat list…
        self.assertEqual(got["posBefore"], 1)
        self.assertEqual(got["posAfter"], 0)
        # …and keeps its bucket identity on the row itself (accent + badge)
        self.assertIn("b-images", got["bucketBefore"].split())
        self.assertIn("b-images", got["bucketAfter"].split())
        self.assertIn("image", got["bucketBadge"].split(","))
        self.assertTrue(got["bucketsUnchanged"])
        self.assertEqual(got["badge"], "#0")

    def test_moves_step_over_excluded_rows(self):
        got = self.drive("""
            const order = () => {
              const p = H.exported();
              return [].concat(p.images, p.buttons, p.texts, p.customs)
                .sort((a, b) => a.index - b.index).map(e => e.key);
            };
            const before = order();                       // [close, background, info, ...]
            const skipped = H.uidOfKey(before[1]);
            H.tick("inc-" + skipped, false);
            const excluded = { hasMoves: H.has('[data-fid="mv-up-' + skipped + '"]'),
                               badge: d.querySelector('.row[data-uid="' + skipped + '"] .badge')
                                        .textContent,
                               order: order() };
            const third = H.uidOfKey(before[2]);
            H.click("mv-up-" + third);                    // hops over the excluded row
            return { before, excluded, after: order() };
        """)
        b = got["before"]
        self.assertFalse(got["excluded"]["hasMoves"])     # no position, no stepper
        self.assertEqual(got["excluded"]["badge"], "excluded")
        self.assertEqual(got["excluded"]["order"], [b[0]] + b[2:])
        # the third element swaps with the FIRST, skipping the excluded second
        self.assertEqual(got["after"], [b[2], b[0]] + b[3:])

    def test_undo_reverts_a_move(self):
        got = self.drive("""
            const order = () => {
              const p = H.exported();
              return [].concat(p.images, p.buttons, p.texts, p.customs)
                .sort((a, b) => a.index - b.index).map(e => e.key);
            };
            const before = order();
            H.click("mv-dn-" + H.uidOfKey(before[0]));
            const moved = order();
            w.undo();
            return { before, moved, undone: order() };
        """)
        self.assertNotEqual(got["moved"], got["before"])
        self.assertEqual(got["undone"], got["before"])

    def test_rows_show_neither_the_vision_role_nor_confidence(self):
        # operator decision: role is internal vocabulary and confidence is build
        # telemetry — neither belongs on a row. Both still travel in the data.
        got = self.drive("""
            H.openAll();
            const rows = [...d.querySelectorAll("#elements .row")].map(r => r.textContent).join(" ");
            const uid = H.uidOfKey("show_banner");
            H.tick("inc-" + uid, false);
            const excludedTexts = H.uidOfKey("soft_billing_old_price");
            H.tick("inc-" + excludedTexts, false);
            return { rows: rows, corrections: H.envelope().corrections.excluded,
                     warnings: H.text("#build-notes") };
        """)
        # show_banner's role is `toggle_custom` — a role that is NOT its key, so
        # it is the honest discriminator between "role rendered" and "key rendered"
        self.assertNotIn("toggle_custom", got["rows"])
        self.assertNotIn("confidence", got["rows"])
        self.assertNotIn("0.95", got["rows"])
        # …but the role still reaches the corpus feedback
        self.assertEqual(sorted((c["key"], c["role"]) for c in got["corrections"]),
                         [("show_banner", "toggle_custom"),
                          ("soft_billing_old_price", "soft_billing_old_price")])

    def test_row_actions_live_in_one_right_aligned_container(self):
        got = self.drive("""
            const uid = H.rowUids()[0];
            H.click("idx-" + uid);                       // reveal the steppers
            const row = d.querySelector('.row[data-uid="' + uid + '"]');
            const cluster = row.querySelector(".row-actions");
            const addUid = H.addRow("images", "extra_art");   // a row with 📍 and ✕ too
            const full = d.querySelector('.row[data-uid="' + addUid + '"] .row-actions');
            return { exists: !!cluster,
                     isSpan: cluster.tagName.toLowerCase(),
                     inHeadGrid: cluster.parentNode.classList.contains("grid"),
                     lastChild: cluster.parentNode.lastElementChild === cluster,
                     order: [...cluster.children].map(c => c.dataset.fid.replace(/-e\d+$/, "")),
                     fullOrder: [...full.children].map(
                       c => c.dataset.fid.replace(/-?e\d+$/, "").replace(/-$/, "")),
                     buttonsOutside: [...row.querySelectorAll(".grid > button")].length };
        """)
        self.assertTrue(got["exists"])
        self.assertEqual(got["isSpan"], "span")
        self.assertTrue(got["inHeadGrid"])       # the container is what sits in the .grid
        self.assertTrue(got["lastChild"])
        self.assertEqual(got["order"], ["mv-up", "mv-dn", "ed"])
        # operator-mandated order, all inside the container: ↑ ↓ → done → remove
        self.assertEqual(got["fullOrder"], ["mv-up", "mv-dn", "ed", "rm"])
        self.assertEqual(got["buttonsOutside"], 0)   # no action button loose in the row grid

    def test_add_cluster_sits_on_its_own_line_under_the_summary(self):
        got = self.drive("""
            const head = d.getElementById("elements-head");
            const cluster = d.getElementById("elements-add");
            const summary = d.getElementById("elements-summary");
            return { lines: [...head.children].map(c => c.className),
                     clusterIsOwnLine: cluster.parentNode === head,
                     summaryLineIsFirst: head.firstElementChild.contains(summary),
                     clusterAfterSummary: head.firstElementChild !== cluster
                       && head.lastElementChild === cluster,
                     buttons: [...cluster.children].map(b => b.dataset.fid),
                     labels: [...cluster.children].map(b => b.textContent),
                     classes: [...cluster.children].map(b => b.className) };
        """)
        self.assertEqual(got["lines"], ["grid", "add-cluster"])   # summary line, then adds
        self.assertTrue(got["clusterIsOwnLine"])
        self.assertTrue(got["summaryLineIsFirst"])
        self.assertTrue(got["clusterAfterSummary"])
        self.assertEqual(got["buttons"], ["add-images", "add-buttons", "add-texts",
                                          "add-customs"])   # fids unchanged
        self.assertEqual(got["labels"], ["＋ image", "＋ button", "＋ text", "＋ custom element"])
        # operator decision: each add button wears its bucket's category colour
        self.assertEqual(got["classes"], ["ghost tiny add-el b-images",
                                          "ghost tiny add-el b-buttons",
                                          "ghost tiny add-el b-texts",
                                          "ghost tiny add-el b-customs"])

    # ---- reorder: drag and on-demand steppers -----------------------------
    def test_drag_handle_only_on_included_rows(self):
        got = self.drive("""
            const uids = H.rowUids();
            const before = { handles: H.count('[data-fid^="drag-"]'), rows: uids.length };
            H.tick("inc-" + uids[1], false);
            return { before,
                     after: { handles: H.count('[data-fid^="drag-"]'),
                              onExcluded: H.has('[data-fid="drag-' + uids[1] + '"]') },
                     glyph: H.byFid("drag-" + uids[0]).textContent,
                     cls: H.byFid("drag-" + uids[0]).className };
        """)
        self.assertEqual(got["before"]["handles"], got["before"]["rows"])
        self.assertEqual(got["after"]["handles"], got["before"]["rows"] - 1)
        self.assertFalse(got["after"]["onExcluded"])   # excluded rows are not draggable
        self.assertEqual(got["glyph"], "⠿")
        self.assertIn("drag", got["cls"].split())

    def test_steppers_are_hidden_until_the_index_badge_is_clicked(self):
        got = self.drive("""
            const uid = H.rowUids()[1];
            const row = () => d.querySelector('.row[data-uid="' + uid + '"]');
            const before = { on: row().classList.contains("steppers-on"),
                             inDom: H.has('[data-fid="mv-up-' + uid + '"]') };
            H.click("idx-" + uid);
            const shown = { on: row().classList.contains("steppers-on"),
                            others: H.count(".row.steppers-on") };
            H.click("idx-" + uid);                       // toggles back off
            const off = row().classList.contains("steppers-on");
            H.click("idx-" + uid);
            // a click anywhere else puts them away again
            d.getElementById("elements").dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
            return { before, shown, off, afterOutsideClick: H.count(".row.steppers-on") };
        """)
        self.assertFalse(got["before"]["on"])
        self.assertTrue(got["before"]["inDom"])    # the fid contract survives the hiding
        self.assertTrue(got["shown"]["on"])
        self.assertEqual(got["shown"]["others"], 1)    # only one row at a time
        self.assertFalse(got["off"])
        self.assertEqual(got["afterOutsideClick"], 0)

    def test_steppers_hide_after_a_move(self):
        got = self.drive("""
            const uid = H.rowUids()[1];
            H.click("idx-" + uid);
            const before = H.count(".row.steppers-on");
            H.click("mv-up-" + uid);
            return { before, after: H.count(".row.steppers-on") };
        """)
        self.assertEqual(got["before"], 1)
        self.assertEqual(got["after"], 0)

    def test_pointer_drag_reorders_the_flat_list(self):
        got = self.drive("""
            const order = () => {
              const p = H.exported();
              return [].concat(p.images, p.buttons, p.texts, p.customs)
                .sort((a, b) => a.index - b.index).map(e => e.key);
            };
            H.stubRows(40);
            const uids = H.rowUids();
            const before = { order: order(), dom: uids.slice(0, 3) };
            const dragged = uids[0];

            H.mouse(H.byFid("drag-" + dragged), "pointerdown", 10, 20);
            H.mouse(d, "pointermove", 10, 30);          // under the threshold-crossing move
            const during = { dragging: H.count(".row.dragging"),
                             indicator: H.has("#drop-indicator") };
            H.mouse(d, "pointermove", 10, 95);          // past row #2's midpoint (80..120 -> 100)
            const mid = { indicator: H.has("#drop-indicator") };
            H.mouse(d, "pointerup", 10, 95);
            const after = { order: order(), dom: H.rowUids().slice(0, 3),
                            indicator: H.has("#drop-indicator"),
                            dragging: H.count(".row.dragging") };
            w.undo();
            return { before, during, mid, after,
                     undone: { order: order(), dom: H.rowUids().slice(0, 3) } };
        """)
        self.assertTrue(got["during"]["dragging"])       # the row dims while dragging
        self.assertTrue(got["during"]["indicator"])      # drop line appears
        self.assertTrue(got["mid"]["indicator"])
        # the dragged row physically moved down in the DOM and in the sequence
        self.assertNotEqual(got["after"]["dom"], got["before"]["dom"])
        self.assertEqual(got["after"]["dom"][0], got["before"]["dom"][1])
        self.assertEqual(got["after"]["order"][1], got["before"]["order"][0])
        self.assertFalse(got["after"]["indicator"])      # cleaned up on drop
        self.assertEqual(got["after"]["dragging"], 0)
        # one undo step per drop
        self.assertEqual(got["undone"]["order"], got["before"]["order"])
        self.assertEqual(got["undone"]["dom"], got["before"]["dom"])

    def test_a_drag_below_the_threshold_does_not_reorder(self):
        got = self.drive("""
            H.stubRows(40);
            const uids = H.rowUids();
            H.mouse(H.byFid("drag-" + uids[0]), "pointerdown", 10, 20);
            H.mouse(d, "pointermove", 10, 22);           // 2px
            H.mouse(d, "pointerup", 10, 22);
            return { dom: H.rowUids(), same: JSON.stringify(uids) === JSON.stringify(H.rowUids()),
                     indicator: H.has("#drop-indicator") };
        """)
        self.assertTrue(got["same"])
        self.assertFalse(got["indicator"])

    def test_drop_index_computation_skips_excluded_rows(self):
        # The geometry-free core, driven directly: DOM order == state order, and
        # only included rows are drop targets.
        got = self.drive("""
            const boxes = [
              { uid: "a", idx: 0, included: true,  mid: 20 },
              { uid: "b", idx: 1, included: false, mid: 60 },   // excluded
              { uid: "c", idx: 2, included: true,  mid: 100 },
              { uid: "d", idx: 3, included: true,  mid: 140 }
            ];
            const at = y => w.dropIndexFromBoxes("a", y, boxes);
            return { top: at(0), overExcluded: at(70), overC: at(95),
                     belowC: at(120), end: at(200) };
        """)
        self.assertEqual(got["top"], 2)          # first included target below the pointer
        self.assertEqual(got["overExcluded"], 2)  # the excluded row is not a target
        self.assertEqual(got["overC"], 2)
        self.assertEqual(got["belowC"], 3)
        self.assertEqual(got["end"], 4)           # past everything -> append

    # ---- template header: view / edit ------------------------------------
    def test_template_header_starts_in_view_mode(self):
        got = self.drive("""
            const edit = d.getElementById("tpl-edit");
            return { hidden: edit.hidden,
                     inputsAreInside: ["tpl-name", "tpl-key", "tpl-desc", "tpl-feature",
                                       "fp-mission", "fp-milestone"]
                       .every(id => edit.contains(d.getElementById(id))),
                     name: H.text("#tpl-view-name"), key: H.text("#tpl-view-key"),
                     feature: H.text("#tpl-view-feature"),
                     desc: H.has("#tpl-view-desc"),
                     pencil: H.byFid("tpl-ed").textContent,
                     pencilCls: H.byFid("tpl-ed").className,
                     cluster: H.byFid("tpl-ed").parentNode.className,
                     clusterLast: d.getElementById("tpl-head").lastElementChild
                                  === H.byFid("tpl-ed").parentNode,
                     pencilInside: H.byFid("actions-cluster-tpl").contains(H.byFid("tpl-ed")),
                     gated: H.gated(), counter: H.counter() };
        """)
        self.assertTrue(got["hidden"])              # nothing editable until the pencil
        self.assertTrue(got["inputsAreInside"])     # incl. the feature-config panel
        self.assertEqual(got["name"], "Spring Offer")
        self.assertEqual(got["key"], "spring_offer")
        self.assertEqual(got["feature"], "none")    # product label, not "standard"
        self.assertFalse(got["desc"])               # empty description renders nothing
        self.assertIn("edit", got["pencil"])
        self.assertEqual(got["pencilCls"], "ghost pencil")   # same class/scale as rows
        # …and the same right-aligned container treatment as a row cluster
        self.assertEqual(got["cluster"], "row-actions")
        self.assertTrue(got["clusterLast"])
        self.assertTrue(got["pencilInside"])
        self.assertFalse(got["gated"]["download"])
        self.assertNotIn("finish editing", got["counter"])

    def test_template_pencil_opens_and_closes(self):
        got = self.drive("""
            H.click("tpl-ed");
            const open = { hidden: d.getElementById("tpl-edit").hidden,
                           label: H.byFid("tpl-ed").textContent,
                           view: H.has("#tpl-view-name"),
                           gated: H.gated(), counter: H.counter() };
            H.typeInto("tpl-desc", "seasonal pack");
            H.click("tpl-ed");
            const closed = { hidden: d.getElementById("tpl-edit").hidden,
                             label: H.byFid("tpl-ed").textContent,
                             desc: H.text("#tpl-view-desc"),
                             gated: H.gated(),
                             payload: H.exported().description };
            return { open, closed };
        """)
        self.assertFalse(got["open"]["hidden"])
        self.assertIn("done", got["open"]["label"])
        self.assertFalse(got["open"]["view"])       # the read-only summary steps aside
        self.assertTrue(got["open"]["gated"]["download"])
        self.assertIn("finish editing 1 row(s)", got["open"]["counter"])
        self.assertTrue(got["closed"]["hidden"])
        self.assertIn("edit", got["closed"]["label"])
        self.assertEqual(got["closed"]["desc"], "seasonal pack")   # now it renders
        self.assertFalse(got["closed"]["gated"]["download"])
        self.assertEqual(got["closed"]["payload"], "seasonal pack")

    def test_invalid_template_key_forces_the_header_open(self):
        build = _build_result()
        build["payload"]["key"] = "9bad"
        got = self.drive("""
            const onLoad = { hidden: d.getElementById("tpl-edit").hidden,
                             label: H.byFid("tpl-ed").textContent,
                             bad: H.byFid("tpl-key").classList.contains("bad"),
                             gated: H.gated(), errors: H.text("#live-errors") };
            H.click("tpl-ed");                       // cannot be collapsed while invalid
            const stillOpen = d.getElementById("tpl-edit").hidden;
            H.typeInto("tpl-key", "spring_offer");
            const afterFix = { hidden: d.getElementById("tpl-edit").hidden, gated: H.gated() };
            H.click("tpl-ed");                       // ✓ done works now
            return { onLoad, stillOpen, afterFix, closed: H.gated() };
        """, build=build)
        self.assertFalse(got["onLoad"]["hidden"])    # force-opened on load
        self.assertIn("done", got["onLoad"]["label"])
        self.assertTrue(got["onLoad"]["bad"])
        self.assertTrue(got["onLoad"]["gated"]["download"])
        self.assertIn("must match", got["onLoad"]["errors"])
        self.assertFalse(got["stillOpen"])           # hidden === false, i.e. still open
        self.assertFalse(got["afterFix"]["hidden"])  # sticky until ✓ done
        self.assertTrue(got["afterFix"]["gated"]["download"])
        self.assertFalse(got["closed"]["download"])

    def test_over_long_template_description_is_an_error(self):
        build = _build_result()
        build["payload"]["description"] = "x" * 51
        got = self.drive("""
            const onLoad = { hidden: d.getElementById("tpl-edit").hidden,
                             errors: H.text("#live-errors"), gated: H.gated() };
            H.typeInto("tpl-desc", "short enough");
            H.click("tpl-ed");
            return { onLoad, fixed: { gated: H.gated(), hidden: d.getElementById("tpl-edit").hidden } };
        """, build=build)
        self.assertFalse(got["onLoad"]["hidden"])       # forced open by the length error
        self.assertIn("exceeds the server limit of 50 chars", got["onLoad"]["errors"])
        self.assertTrue(got["onLoad"]["gated"]["download"])
        self.assertFalse(got["fixed"]["gated"]["download"])
        self.assertTrue(got["fixed"]["hidden"])

    def test_view_mode_shows_the_feature_counts_inline(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["feature"] = {"type": "milestone", "detected": {"milestone_count": 13}}
        got = self.drive("""
            const view = H.text("#tpl-view-feature");
            const panelHidden = d.getElementById("tpl-edit").hidden;
            H.click("tpl-ed");
            const editing = { panelShown: !d.getElementById("tpl-edit").hidden,
                              milestone: !d.getElementById("fp-milestone").hidden,
                              mission: d.getElementById("fp-mission").hidden,
                              limit: d.getElementById("fp-limit").value };
            d.getElementById("fp-limit").value = "4";
            d.getElementById("fp-limit").dispatchEvent(new w.Event("input", {bubbles:true}));
            H.click("tpl-ed");
            return { view, panelHidden, editing, after: H.text("#tpl-view-feature") };
        """, build=_build_result(analysis))
        # no menus were derived from this mockup, so the badge says where they come from
        self.assertEqual(got["view"], "milestones · max 13 · CTA on dashboard")  # operator wording: max milestones
        self.assertTrue(got["panelHidden"])       # config panel only in edit mode
        self.assertTrue(got["editing"]["panelShown"])
        self.assertTrue(got["editing"]["milestone"])
        self.assertTrue(got["editing"]["mission"])
        self.assertEqual(got["editing"]["limit"], "13")
        self.assertEqual(got["after"], "milestones · max 4 · CTA on dashboard")   # summary follows the edit

    # ---- custom FIELDS vs custom ELEMENTS --------------------------------
    def test_custom_elements_are_named_as_elements_not_fields(self):
        got = self.drive("""
            H.openAll();
            return { add: H.byFid("add-customs").textContent,
                     summary: H.text("#elements-summary"),
                     counter: H.counter(),
                     rowBadge: [...d.querySelectorAll(".row.b-customs .badge")]
                       .map(b => b.textContent).join(","),
                     hint: H.count(".cf-hint") };
        """)
        self.assertIn("custom element", got["add"])
        self.assertIn("custom element", got["summary"])
        self.assertIn("custom elements", got["counter"])
        self.assertIn("custom element", got["rowBadge"].split(","))
        self.assertNotIn("Custom fields", got["summary"])

    def test_all_small_buttons_share_the_sized_classes(self):
        got = self.drive("""
            const uid = H.openFirst("images");
            H.click("cfadd-" + uid);                      // a page-added custom field
            const cfrm = [...d.querySelectorAll('[data-fid^="cfrm-"]')].pop();
            const cls = sel => [...d.querySelectorAll(sel)].map(b => b.className);
            const SIZED = ["pencil", "remove", "move"];
            const sized = b => SIZED.some(c => b.classList.contains(c));
            const buttons = [...d.querySelectorAll(".row button, #tpl-head button")]
              .filter(b => b.dataset.fid && !/^(add-|cfadd-)/.test(b.dataset.fid));
            return { cfRemove: cfrm.className,
                     cfRemoveInGrid: cfrm.parentNode.classList.contains("grid"),
                     moves: cls('[data-fid^="mv-"]'),
                     pencils: cls('[data-fid^="ed-"]').slice(0, 1),
                     header: H.byFid("tpl-ed").className,
                     unsized: buttons.filter(b => !sized(b)).map(b => b.dataset.fid) };
        """)
        # the ✕ on a custom field carries .remove, so the container-free rule sizes it
        self.assertIn("remove", got["cfRemove"].split())
        self.assertTrue(got["cfRemoveInGrid"])
        for cls in got["moves"]:
            self.assertIn("move", cls.split())
        self.assertIn("pencil", got["pencils"][0].split())
        self.assertIn("pencil", got["header"].split())
        # nothing in a row or the header cluster is left at the base button size
        self.assertEqual(got["unsized"], [])

    def test_field_kinds_and_element_kinds_are_not_cross_wired(self):
        got = self.drive("""
            H.openAll();
            const elUid = H.uidOfKey("show_banner");
            const fieldUid = d.querySelector('#elements .row.b-texts [data-fid^="cf"][data-fid$="-kind"]')
              .dataset.fid.replace("-kind", "");
            const opts = fid => [...H.byFid(fid).options].map(o => o.value);
            return { element: opts(elUid + "-kind"), field: opts(fieldUid + "-kind") };
        """)
        self.assertEqual(got["element"], self.mod.KINDS)          # no image on an element
        self.assertNotIn("image", got["element"])
        self.assertEqual(got["field"], self.mod.FIELD_KINDS)      # image belongs to fields
        self.assertIn("image", got["field"])

    def test_custom_field_can_be_added_and_edited_on_any_element(self):
        got = self.drive("""
            const uid = H.openFirst("images");
            const before = H.exported().images[0].customFields;
            H.click("cfadd-" + uid);
            const cf = [...d.querySelectorAll('.row[data-uid="' + uid + '"] '
              + '[data-fid^="cf"][data-fid$="-key"]')].pop().dataset.fid.replace("-key", "");
            const blocked = H.gated();                    // keyless field is invalid
            H.typeInto(cf + "-key", "overlay_tint");
            H.typeInto(cf + "-name", "Overlay Tint");
            H.setSelect(cf + "-kind", "image");
            H.typeInto(cf + "-default", "tint.png");
            H.typeInto(cf + "-desc", "art swap");
            const chk = H.byFid(cf + "-nullable");
            chk.checked = false;
            chk.dispatchEvent(new w.Event("change", { bubbles: true }));
            const hardRemove = H.has('[data-fid="cfrm-' + cf + '"]');
            const inclusionBox = H.has('[data-fid="cfinc-' + cf + '"]');
            H.openRow(uid);                               // ✓ done
            return { before, blocked, gated: H.gated(),
                     fields: H.exported().images[0].customFields,
                     hardRemove, inclusionBox };
        """)
        self.assertEqual(got["before"], [])
        self.assertTrue(got["blocked"]["download"])   # a keyless field blocks the export
        self.assertFalse(got["gated"]["download"])
        self.assertEqual(got["fields"], [{"key": "overlay_tint", "kind": "image",
                                          "name": "Overlay Tint", "nullable": False,
                                          "description": "art swap",
                                          "defaultValue": "tint.png"}])
        self.assertTrue(got["hardRemove"])     # page-added fields get a ✕ …
        self.assertFalse(got["inclusionBox"])  # … not an include checkbox

    def test_builder_fields_are_excluded_not_deleted(self):
        got = self.drive("""
            const uid = H.uidOfKey("header");
            H.openRow(uid);
            const cf = d.querySelector('.row[data-uid="' + uid + '"] '
              + '[data-fid^="cfinc-"]').dataset.fid.replace("cfinc-", "");
            const before = H.exported().texts[0].customFields.map(f => f.key);
            H.tick("cfinc-" + cf, false);
            const off = { fields: H.exported().texts[0].customFields,
                          stillEditable: H.has('[data-fid="' + cf + '-key"]'),
                          hardRemove: H.has('[data-fid="cfrm-' + cf + '"]') };
            H.tick("cfinc-" + cf, true);
            const back = H.exported().texts[0].customFields.map(f => f.key);
            return { before, off, back };
        """)
        self.assertEqual(got["before"], ["text_color"])
        self.assertEqual(got["off"]["fields"], [])        # omitted from the payload
        self.assertTrue(got["off"]["stillEditable"])      # data kept on the page
        self.assertFalse(got["off"]["hardRemove"])        # builder fields are never deletable
        self.assertEqual(got["back"], ["text_color"])

    def test_duplicate_field_key_is_per_element(self):
        got = self.drive("""
            const uid = H.uidOfKey("header");
            const other = H.uidOfKey("fine_print");
            H.openRow(uid);
            H.click("cfadd-" + uid);
            const cf = [...d.querySelectorAll('.row[data-uid="' + uid + '"] '
              + '[data-fid^="cf"][data-fid$="-key"]')].pop().dataset.fid.replace("-key", "");
            H.typeInto(cf + "-key", "text_color");        // clashes within this element
            const dup = { status: H.status(), errors: H.text("#live-errors"),
                          gated: H.gated() };
            H.typeInto(cf + "-key", "Bad Key");
            const badPattern = H.text("#live-errors");
            H.typeInto(cf + "-key", "shadow_color");
            H.openRow(uid);
            const fixed = { status: H.status(), gated: H.gated(),
                            keys: H.exported().texts[0].customFields.map(f => f.key) };

            // the SAME key on a different element is perfectly fine
            H.openRow(other);
            H.click("cfadd-" + other);
            const cf2 = [...d.querySelectorAll('.row[data-uid="' + other + '"] '
              + '[data-fid^="cf"][data-fid$="-key"]')].pop().dataset.fid.replace("-key", "");
            H.typeInto(cf2 + "-key", "shadow_color");
            H.openRow(other);
            return { dup, badPattern, fixed, status: H.status(), gated: H.gated() };
        """)
        self.assertEqual(got["dup"]["status"]["cls"], "bad")
        self.assertIn("used twice on this element", got["dup"]["errors"])
        self.assertTrue(got["dup"]["gated"]["download"])
        self.assertIn("must match ^[a-z][a-z0-9_]*$", got["badPattern"])
        self.assertEqual(got["fixed"]["keys"], ["text_color", "shadow_color"])
        # shadow_color now exists on BOTH elements — legal, each element is its own scope
        self.assertEqual(got["status"]["cls"], "ok")
        self.assertFalse(got["gated"]["download"])

    def test_field_enum_values_and_undo(self):
        got = self.drive("""
            const uid = H.openFirst("buttons");
            H.click("cfadd-" + uid);
            const cf = [...d.querySelectorAll('.row[data-uid="' + uid + '"] '
              + '[data-fid^="cf"][data-fid$="-key"]')].pop().dataset.fid.replace("-key", "");
            H.typeInto(cf + "-key", "shape");
            const before = { enumShown: H.has('[data-fid="' + cf + '-enum"]') };
            H.setSelect(cf + "-kind", "enumeration");
            const on = { enumShown: H.has('[data-fid="' + cf + '-enum"]'),
                         warned: H.text("#live-errors"), gated: H.gated() };
            H.typeInto(cf + "-enum", "round, square");
            H.openRow(uid);
            const filled = { field: H.exported().buttons[0].customFields.pop(),
                             gated: H.gated() };
            for (let i = 0; i < 40; i++) w.undo();
            return { before, on, filled, undone: H.exported().buttons[0].customFields };
        """)
        self.assertFalse(got["before"]["enumShown"])
        self.assertTrue(got["on"]["enumShown"])
        # an empty enumeration warns but never blocks
        self.assertIn("enumeration with no enumValues", got["on"]["warned"])
        self.assertTrue(got["on"]["gated"]["download"])   # blocked only by the open editor
        self.assertEqual(got["filled"]["field"], {"key": "shape", "kind": "enumeration",
                                                  "name": "", "nullable": True,
                                                  "description": "", "defaultValue": "",
                                                  "enumValues": "round, square"})
        self.assertFalse(got["filled"]["gated"]["download"])
        self.assertEqual(got["undone"], [])              # undo walks the field edits back

    # ---- overlay hit testing --------------------------------------------
    def test_boxes_stack_smallest_on_top(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const z = k => {
              const uid = [...d.querySelectorAll(".row")].find(
                r => r.textContent.indexOf(k) >= 0).dataset.uid;
              return Number(d.querySelector('#overlay .box[data-uid="' + uid + '"]').style.zIndex);
            };
            const bg = z("background_image"), close = z("close_button"), cta = z("cta_button");

            // a hand-placed box is small, so it must stack above the background too
            const uid = H.addRow("images", "extra_art");
            H.click("place-" + uid);
            H.mouse(H.stage(), "click", 500, 500);
            const placed = Number(
              d.querySelector('#overlay .box[data-uid="' + uid + '"]').style.zIndex);
            return { bg, close, cta, placed,
                     client: Number(d.querySelector("#overlay .box.client").style.zIndex) };
        """)
        # background covers 64% of the image, the controls a few percent each
        self.assertLess(got["bg"], got["close"])
        self.assertLess(got["bg"], got["cta"])
        self.assertLess(got["close"], 1000)
        self.assertLess(got["bg"], got["placed"])
        self.assertGreater(got["client"], got["bg"])

    def test_hover_resolves_to_the_small_box_over_a_large_one(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uidOfKey = k => [...d.querySelectorAll(".row")].find(
              r => r.textContent.indexOf(k) >= 0).dataset.uid;
            const bgUid = uidOfKey("background_image"), ctaUid = uidOfKey("cta_button");
            const box = u => d.querySelector('#overlay .box[data-uid="' + u + '"]');
            const row = u => d.querySelector('.row[data-uid="' + u + '"]');

            // the CTA sits geometrically inside the background box
            box(ctaUid).dispatchEvent(new w.Event("mouseenter", { bubbles: false }));
            const onCta = { cta: row(ctaUid).classList.contains("hl"),
                            bg: row(bgUid).classList.contains("hl"),
                            ctaBox: box(ctaUid).classList.contains("hl"),
                            over: Number(box(ctaUid).style.zIndex) > Number(box(bgUid).style.zIndex) };
            box(ctaUid).dispatchEvent(new w.Event("mouseleave", { bubbles: false }));
            const off = row(ctaUid).classList.contains("hl");
            return { onCta, off };
        """)
        self.assertTrue(got["onCta"]["cta"])
        self.assertTrue(got["onCta"]["ctaBox"])
        self.assertFalse(got["onCta"]["bg"])    # the background is never co-highlighted
        self.assertTrue(got["onCta"]["over"])
        self.assertFalse(got["off"])

    def test_placement_reaches_the_stage_over_the_background_box(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.addRow("texts", "over_bg");
            const before = d.getElementById("overlay").classList.contains("placing");
            H.click("place-" + uid);
            const during = { overlay: d.getElementById("overlay").classList.contains("placing"),
                             stage: H.stage().classList.contains("placing") };
            // 400,400 sits well inside background_image (0.1..0.9 x 0.05..0.85)
            H.mouse(H.stage(), "click", 400, 400);
            const after = { overlay: d.getElementById("overlay").classList.contains("placing"),
                            placements: H.envelope().corrections.missed };

            // Esc also restores interactivity
            H.click("place-" + uid);
            const reopened = d.getElementById("overlay").classList.contains("placing");
            d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            return { before, during, after, reopened,
                     afterEsc: d.getElementById("overlay").classList.contains("placing"),
                     dragStillWorks: (function () {
                       const box = d.querySelector('#overlay .box[data-uid="' + uid + '"]');
                       H.mouse(box, "pointerdown", 400, 400);
                       H.mouse(d, "pointermove", 450, 400);
                       H.mouse(d, "pointerup", 450, 400);
                       return H.envelope().corrections.missed[0].bbox.x;
                     })() };
        """)
        self.assertFalse(got["before"])
        self.assertTrue(got["during"]["overlay"])   # boxes are click-through
        self.assertTrue(got["during"]["stage"])
        self.assertFalse(got["after"]["overlay"])   # restored after the drop
        bbox = got["after"]["placements"][0]["bbox"]
        self.assertAlmostEqual(bbox["x"], 0.29, places=6)   # the click reached the stage
        self.assertAlmostEqual(bbox["y"], 0.365, places=6)
        self.assertEqual([bbox["w"], bbox["h"]], [0.22, 0.07])
        self.assertTrue(got["reopened"])
        self.assertFalse(got["afterEsc"])           # restored after Esc
        self.assertAlmostEqual(got["dragStillWorks"], 0.34, places=6)

    # ---- manual placement (page-side feedback only) ----------------------
    def test_only_page_added_rows_offer_placement(self):
        self._with_image()
        got = self.drive("""
            const detected = { chips: H.count('[data-fid^="place-"]'),
                               text: H.text("#elements .row.b-texts") };
            const uid = H.addRow("texts", "extra_line");
            const row = d.querySelector('.row[data-uid="' + uid + '"]');
            return { detected: detected,
                     added: { chip: row.textContent, hasBadge: H.has('[data-fid="place-' + uid + '"]'),
                              label: H.byFid("place-" + uid).textContent,
                              uid: uid, cls: H.byFid("place-" + uid).className,
                              tag: H.byFid("place-" + uid).tagName.toLowerCase(),
                              title: H.byFid("place-" + uid).title,
                              inHead: !H.byFid("place-" + uid).closest(".row-actions"),
                              buttons: H.count(".row button.place"),
                              boxes: H.count("#overlay .box.placed") },
                     buttons: H.count('[data-fid^="place-"]') };
        """)
        self.assertEqual(got["detected"]["chips"], 0)      # vision rows untouched
        self.assertNotIn("not placed", got["detected"]["text"])
        self.assertIn("not placed", got["added"]["chip"])
        self.assertTrue(got["added"]["hasBadge"])
        self.assertEqual(got["added"]["label"], "not placed")
        # operator decision: a clickable BADGE, not a button, and it lives with the
        # other badges rather than in the action cluster
        self.assertEqual(got["added"]["tag"], "span")
        self.assertIn("place-badge", got["added"]["cls"].split())
        self.assertIn("click to place on the mockup", got["added"]["title"])
        self.assertTrue(got["added"]["inHead"])
        self.assertEqual(got["added"]["buttons"], 0)
        self.assertEqual(got["added"]["boxes"], 0)
        self.assertEqual(got["buttons"], 1)               # only the page-added row

    def test_clicking_the_mockup_places_a_default_box(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.addRow("texts", "extra_line");
            H.click("place-" + uid);
            const mode = { hint: H.text("#place-hint"), hinted: !d.getElementById("place-hint").hidden,
                           crosshair: H.stage().classList.contains("placing") };
            H.mouse(H.stage(), "click", 500, 300);
            const box = d.querySelector('#overlay .box[data-uid="' + uid + '"]');
            const placed = { bbox: H.envelope().corrections.missed[0].bbox,
                             dashed: box.classList.contains("placed"),
                             bucketColoured: box.classList.contains("b-texts"),
                             label: box.querySelector(".tag").textContent,
                             chip: d.querySelector('.row[data-uid="' + uid + '"]').textContent,
                             label2: H.byFid("place-" + uid).textContent,
                             title2: H.byFid("place-" + uid).title,
                             modeOff: H.stage().classList.contains("placing"),
                             hintHidden: d.getElementById("place-hint").hidden };
            // bidirectional hover, exactly like a detected element
            box.dispatchEvent(new w.Event("mouseenter", { bubbles: false }));
            placed.rowLit = d.querySelector('.row[data-uid="' + uid + '"]').classList.contains("hl");
            placed.boxLit = box.classList.contains("hl");

            // a click near the corner clamps into bounds
            H.click("place-" + uid);
            H.mouse(H.stage(), "click", 5, 995);
            placed.clamped = H.envelope().corrections.missed[0].bbox;
            return { mode, placed };
        """)
        self.assertIn("place extra_line", got["mode"]["hint"])
        self.assertTrue(got["mode"]["hinted"])
        self.assertTrue(got["mode"]["crosshair"])
        # 22% x 7% default, centred on the click point
        self.assertEqual(got["placed"]["bbox"], {"x": 0.39, "y": 0.265, "w": 0.22, "h": 0.07})
        self.assertTrue(got["placed"]["dashed"])
        self.assertTrue(got["placed"]["bucketColoured"])
        # the overlay label carries no "(placed)" suffix by operator decision —
        # hand placement is signalled by the dashed box style alone
        self.assertNotIn("(placed)", got["placed"]["label"])
        self.assertIn("placed", got["placed"]["chip"])
        self.assertEqual(got["placed"]["label2"], "placed")
        self.assertIn("click to re-place", got["placed"]["title2"])
        self.assertFalse(got["placed"]["modeOff"])
        self.assertTrue(got["placed"]["hintHidden"])
        self.assertTrue(got["placed"]["rowLit"])
        self.assertTrue(got["placed"]["boxLit"])
        clamped = got["placed"]["clamped"]
        self.assertEqual(clamped["x"], 0)                     # clamped at the left edge
        self.assertAlmostEqual(clamped["y"], 0.93, places=6)  # and at the bottom
        self.assertEqual([clamped["w"], clamped["h"]], [0.22, 0.07])

    def test_escape_cancels_placement_mode(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.addRow("texts", "extra_line");
            H.click("place-" + uid);
            const on = { crosshair: H.stage().classList.contains("placing"),
                         hinted: !d.getElementById("place-hint").hidden };
            d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            const off = { crosshair: H.stage().classList.contains("placing"),
                          hinted: !d.getElementById("place-hint").hidden };
            H.mouse(H.stage(), "click", 500, 300);   // a stray click must not place
            return { on, off, placements: H.envelope().corrections.missed,
                     boxes: H.count("#overlay .box.placed") };
        """)
        self.assertTrue(got["on"]["crosshair"])
        self.assertTrue(got["on"]["hinted"])
        self.assertFalse(got["off"]["crosshair"])
        self.assertFalse(got["off"]["hinted"])
        self.assertEqual(got["placements"], [])
        self.assertEqual(got["boxes"], 0)

    def test_dragging_a_placed_box_is_one_undoable_step(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const uid = H.addRow("texts", "extra_line");
            H.click("place-" + uid);
            H.mouse(H.stage(), "click", 500, 300);
            const placed = H.envelope().corrections.missed[0].bbox;

            const box = () => d.querySelector('#overlay .box[data-uid="' + uid + '"]');
            H.mouse(box(), "pointerdown", 500, 300);
            H.mouse(d, "pointermove", 600, 400);
            const midDrag = H.envelope().corrections.missed[0].bbox;
            H.mouse(d, "pointerup", 600, 400);
            const dragged = H.envelope().corrections.missed[0].bbox;

            w.undo();
            const undone = H.envelope().corrections.missed[0].bbox;
            w.undo();
            const unplaced = H.envelope().corrections.missed.length;
            return { placed, midDrag, dragged, undone, unplaced };
        """)
        self.assertEqual(got["placed"], {"x": 0.39, "y": 0.265, "w": 0.22, "h": 0.07})
        self.assertEqual(got["midDrag"]["x"], 0.49)          # live while dragging
        self.assertEqual(got["dragged"], {"x": 0.49, "y": 0.365, "w": 0.22, "h": 0.07})
        self.assertEqual(got["undone"], got["placed"])       # the whole drag is one step
        self.assertEqual(got["unplaced"], 0)                 # and the placement itself is another

    def test_corrections_ride_beside_an_unchanged_payload(self):
        self._with_image()
        got = self.drive("""
            H.stubStage(1000);
            const before = JSON.stringify(H.envelope().payload);
            const uid = H.addRow("texts", "extra_line");
            const withRow = JSON.stringify(H.envelope().payload);
            H.click("place-" + uid);
            H.mouse(H.stage(), "click", 500, 300);
            const placedPayload = JSON.stringify(H.envelope().payload);
            const placements = H.envelope().corrections.missed;

            // excluding the row drops it from BOTH the payload and the feedback
            H.tick("inc-" + uid, false);
            const excluded = { placements: H.envelope().corrections.missed,
                               falsePositives: H.envelope().corrections.excluded,
                               texts: H.envelope().payload.texts.length,
                               boxGreyed: !!d.querySelector('#overlay .box.excluded[data-uid="' + uid + '"]') };
            H.tick("inc-" + uid, true);

            // hard-removing the row removes its box outright
            H.click("rm-" + uid);
            const removed = { placements: H.envelope().corrections.missed,
                              boxes: H.count("#overlay .box.placed"),
                              payload: JSON.stringify(H.envelope().payload) };
            return { before, withRow, placedPayload, placements, excluded, removed };
        """)
        # the payload never learns about geometry
        self.assertEqual(got["withRow"], got["placedPayload"])
        self.assertEqual(got["placements"], [{"key": "extra_line", "bucket": "texts",
                                              "bbox": {"x": 0.39, "y": 0.265, "w": 0.22, "h": 0.07}}])
        self.assertEqual(got["excluded"]["placements"], [])   # included rows only
        self.assertEqual(got["excluded"]["falsePositives"], [])  # not a model mistake
        self.assertEqual(got["excluded"]["texts"], 3)
        self.assertTrue(got["excluded"]["boxGreyed"])
        self.assertEqual(got["removed"]["placements"], [])
        self.assertEqual(got["removed"]["boxes"], 0)
        self.assertEqual(got["removed"]["payload"], got["before"])

    def test_placement_is_offered_only_when_a_mockup_exists(self):
        got = self.drive("""
            const uid = H.addRow("texts", "extra_line");
            const badge = H.byFid("place-" + uid);
            badge.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
            return { clickable: badge.classList.contains("place-badge"),
                     title: badge.title,
                     hint: !d.getElementById("place-hint").hidden,
                     placements: H.envelope().corrections.missed };
        """)
        self.assertFalse(got["clickable"])     # no image embedded in this fixture
        self.assertIn("no mockup image", got["title"])
        self.assertFalse(got["hint"])          # clicking it does nothing
        self.assertEqual(got["placements"], [])

    # ---- live validation -------------------------------------------------
    def test_bad_key_pattern_is_flagged(self):
        got = self.drive("""
            H.openFirst("images");
            const fid = H.fidOf('#elements .row.b-images input[data-fid^="e"][data-fid$="-key"]');
            const after = H.typeInto(fid, "Bad Key");
            return { status: H.status(), value: after.value, bad: after.classList.contains("bad"),
                     focus: d.activeElement.dataset.fid, fid: fid,
                     errors: H.text("#live-errors") };
        """)
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertEqual(got["value"], "Bad Key")           # no keystrokes eaten
        self.assertEqual(got["focus"], got["fid"])          # focus survives re-render
        self.assertTrue(got["bad"])
        self.assertIn("^[a-z][a-z0-9_]*$", got["errors"])

    def test_valid_key_clears_the_error(self):
        got = self.drive("""
            H.openFirst("images");
            const fid = H.fidOf('#elements .row.b-images input[data-fid^="e"][data-fid$="-key"]');
            H.typeInto(fid, "Bad Key");
            H.typeInto(fid, "bg_art");
            return { status: H.status(), keys: H.exported().images.map(e => e.key) };
        """)
        self.assertEqual(got["status"]["cls"], "ok")
        self.assertEqual(got["keys"], ["bg_art"])

    def test_duplicate_key_within_a_bucket_is_flagged(self):
        got = self.drive("""
            H.openAll();
            const keys = [...d.querySelectorAll(
              '#elements .row.b-texts input[data-fid^="e"][data-fid$="-key"]')];
            const first = keys[0].value, fid = keys[1].dataset.fid;
            H.typeInto(fid, first);
            const dup = { status: H.status(), rows: H.count("#elements .row.b-texts.invalid"),
                          errors: H.text("#live-errors") };
            H.typeInto(fid, "fine_print_v2");
            dup.after = H.status();
            return dup;
        """)
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertIn("duplicate key", got["errors"].lower())
        self.assertEqual(got["rows"], 2)  # both offenders flagged, not just the second
        self.assertEqual(got["after"]["cls"], "ok")

    def test_button_without_click_actions_is_invalid(self):
        got = self.drive("""
            H.openAll();
            const uid = H.uidOfKey("close_button");
            H.setActions(uid, []);
            const bad = { status: H.status(), errors: H.text("#live-errors"),
                          exported: H.exported().buttons[0].clickActionType,
                          flagged: !!d.querySelector('[data-fid="actions-' + uid + '"].bad') };
            H.setActions(uid, ["close"]);
            bad.after = H.status();
            return bad;
        """)
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertIn("clickActionType", got["errors"])
        self.assertEqual(got["exported"], [])   # never silently repaired
        self.assertTrue(got["flagged"])
        self.assertEqual(got["after"]["cls"], "ok")

    # ---- conditional controls -------------------------------------------
    def test_required_items_count_only_for_item_bearing_actions(self):
        got = self.drive("""
            H.openAll();
            const uid = H.uidOfKey("close_button");
            const before = { shown: H.has('[data-fid$="-items"]'),
                             exported: "requiredItemsCount" in H.exported().buttons[0] };
            H.setActions(uid, ["collect_resource"]);
            const collect = { shown: H.has('[data-fid$="-items"]'),
                              value: H.exported().buttons[0].requiredItemsCount };
            H.setActions(uid, ["promise_rewards"]);
            const promise = { shown: H.has('[data-fid$="-items"]') };
            H.setActions(uid, ["close"]);
            const closed = { shown: H.has('[data-fid$="-items"]'),
                             exported: "requiredItemsCount" in H.exported().buttons[0] };
            return { before, collect, promise, closed };
        """)
        self.assertFalse(got["before"]["shown"])
        self.assertFalse(got["before"]["exported"])
        self.assertTrue(got["collect"]["shown"])
        self.assertEqual(got["collect"]["value"], 1)
        self.assertTrue(got["promise"]["shown"])
        self.assertFalse(got["closed"]["shown"])
        self.assertFalse(got["closed"]["exported"])

    def test_enum_values_only_for_enumeration_kind(self):
        got = self.drive("""
            H.openAll();
            const fid = H.fidOf('#elements .row.b-customs select[data-fid^="e"][data-fid$="-kind"]');
            const before = { shown: H.has('#elements .row.b-customs [data-fid^="e"][data-fid$="-enum"]'),
                             exported: "enumValues" in H.exported().customs[0] };
            H.setSelect(fid, "enumeration");
            H.typeInto(H.fidOf('#elements .row.b-customs [data-fid^="e"][data-fid$="-enum"]'), "a, b, c");
            const on = { shown: H.has('#elements .row.b-customs [data-fid^="e"][data-fid$="-enum"]'),
                         value: H.exported().customs[0].enumValues };
            H.setSelect(H.fidOf('#elements .row.b-customs select[data-fid^="e"][data-fid$="-kind"]'), "boolean");
            const off = { shown: H.has('#elements .row.b-customs [data-fid^="e"][data-fid$="-enum"]'),
                          exported: "enumValues" in H.exported().customs[0],
                          def: H.exported().customs[0].defaultValue };
            return { before, on, off };
        """)
        self.assertFalse(got["before"]["shown"])
        self.assertFalse(got["before"]["exported"])
        self.assertTrue(got["on"]["shown"])
        self.assertEqual(got["on"]["value"], "a, b, c")
        self.assertFalse(got["off"]["shown"])
        self.assertFalse(got["off"]["exported"])
        self.assertIs(got["off"]["def"], False)   # boolean default coerced, not "false"

    def test_click_actions_read_as_a_multi_select_group(self):
        got = self.drive("""
            H.openAll();
            const uid = H.uidOfKey("close_button");
            const chips = [...d.querySelectorAll('[data-fid="actions-' + uid + '"] .chip')];
            const before = { count: chips.length,
                             checkboxes: chips.filter(c => c.querySelector("input[type=checkbox]")).length,
                             selects: H.count('[data-fid$="-actions"] select'),
                             caption: H.text("#actions-caption-" + uid) };
            // check several out of menu order — the export must come back in menu order
            H.setActions(uid, ["show_ad", "close", "custom"]);
            const picked = { actions: H.exported().buttons.find(e => e.key === "close_button").clickActionType,
                             on: [...d.querySelectorAll('[data-fid="actions-' + uid + '"] .chip.on')]
                                   .map(c => c.textContent.trim()),
                             ctaShown: H.has('[data-fid="' + uid + '-cta"]') };
            return { before, picked };
        """)
        self.assertEqual(got["before"]["count"], len(self.mod.CLICK_ACTIONS))
        self.assertEqual(got["before"]["checkboxes"], len(self.mod.CLICK_ACTIONS))
        self.assertEqual(got["before"]["selects"], 0)     # no dropdown pretending to be single
        self.assertIn("select all that apply", got["before"]["caption"])
        # menu order, not click order
        self.assertEqual(got["picked"]["actions"], ["close", "custom", "show_ad"])
        self.assertEqual(sorted(got["picked"]["on"]), ["close", "custom", "show_ad"])
        self.assertTrue(got["picked"]["ctaShown"])        # 'custom' still reveals the names

    def test_text_limit_is_not_editable_anywhere(self):
        # operator decision: textLimit is dashboard-side — the page neither shows
        # it in the read-only facts nor offers an input, for buttons or texts.
        got = self.drive("""
            H.openAll();
            const summaries = [...d.querySelectorAll(".row")].map(r => r.textContent).join(" ");
            const raw = JSON.stringify(H.exported());
            return { limitInputs: H.count('[data-fid$="-limit"]'),
                     limitLines: H.count('[id^="limit-line-"]'),
                     mentions: summaries.indexOf("textLimit"),
                     hasTextLimit: raw.indexOf("textLimit"),
                     hasSize: raw.indexOf('"size"'),
                     hasBackgroundImg: raw.indexOf("backgroundImg") };
        """)
        self.assertEqual(got["limitInputs"], 0)   # fp-limit is a feature field, not this
        self.assertEqual(got["limitLines"], 0)
        self.assertEqual(got["mentions"], -1)     # not in the facts line either
        # operator decision: a field neither shown here nor required by the API is
        # never invented — this build carried none, so none ship
        self.assertEqual(got["hasTextLimit"], -1)
        self.assertEqual(got["hasSize"], -1)
        self.assertEqual(got["hasBackgroundImg"], -1)

    def test_build_supplied_geometry_fields_pass_through(self):
        # …but anything the build DID carry rides along byte-identical.
        analysis = json.loads(json.dumps(ANALYSIS))
        for el in analysis["elements"]:
            if el["role"] == "header":
                el["text_limit"] = 40
            if el["role"] == "close_button":
                el["text_limit"] = 12
        build = _build_result(analysis)
        build["payload"]["images"][0]["size"] = {"width": 640, "height": 480, "maxSize": 900}
        build["payload"]["buttons"][0]["backgroundImg"] = {"width": 1, "height": 2, "maxSize": 3}
        got = self.drive("""
            const p = H.exported();
            return { texts: p.texts.map(e => [e.key, e.textLimit === undefined ? null : e.textLimit]),
                     buttons: p.buttons.map(e => [e.key, e.textLimit === undefined ? null : e.textLimit]),
                     size: p.images[0].size || null,
                     bg: p.buttons.find(e => e.key === "close_button").backgroundImg || null,
                     otherHasSize: "size" in p.images[0] };
        """, build=build)
        self.assertEqual(dict(got["texts"])["header"], 40)             # analysis-supplied
        self.assertIsNone(dict(got["texts"])["fine_print"])            # not supplied -> absent
        self.assertEqual(dict(got["buttons"])["close_button"], 12)
        self.assertIsNone(dict(got["buttons"])["cta_button"])
        self.assertEqual(got["size"], {"width": 640, "height": 480, "maxSize": 900})
        self.assertEqual(got["bg"], {"width": 1, "height": 2, "maxSize": 3})

    def test_clearing_a_numeric_field_does_not_snap_back(self):
        # Numerics are held as raw text while typing: coercing per keystroke made
        # a cleared field jump to the default, so "select all, type 42" produced
        # 25542 instead of 42.
        got = self.drive("""
            H.openAll();
            const uid = H.uidOfKey("close_button");
            H.setActions(uid, ["collect_resource"]);        // reveals requiredItemsCount
            const fid = uid + "-items";
            const el = H.byFid(fid);
            el.focus(); el.value = ""; el.dispatchEvent(new w.Event("input", {bubbles:true}));
            const cleared = { shown: H.byFid(fid).value,
                              exported: H.exported().buttons[0].requiredItemsCount };
            H.typeInto(fid, "42");
            return { cleared: cleared, typed: H.exported().buttons[0].requiredItemsCount };
        """)
        self.assertEqual(got["cleared"]["shown"], "")
        self.assertEqual(got["cleared"]["exported"], 1)     # default only at export time
        self.assertEqual(got["typed"], 42)

    def test_feature_numbers_are_coerced_at_export(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["feature"] = {"type": "milestone", "detected": {"milestone_count": 5}}
        got = self.drive("""
            const el = d.getElementById("fp-limit");
            el.value = ""; el.dispatchEvent(new w.Event("input", {bubbles:true}));
            const cleared = H.exported().features.milestone.limit;
            el.value = "9"; el.dispatchEvent(new w.Event("input", {bubbles:true}));
            return { cleared: cleared, typed: H.exported().features.milestone.limit };
        """, build=_build_result(analysis))
        self.assertEqual(got["cleared"], 1)   # falls back, never ships ""
        self.assertEqual(got["typed"], 9)

    def test_text_nullable_is_editable(self):
        got = self.drive("""
            H.openAll();
            const chk = H.byFid(H.fidOf(
              '#elements .row.b-texts [data-fid^="e"][data-fid$="-nullable"]'));
            chk.checked = !chk.checked;
            chk.dispatchEvent(new w.Event("change", { bubbles: true }));
            const t = H.exported().texts.find(e => e.key === "header");
            return { nullable: t.nullable, hasLimit: "textLimit" in t };
        """)
        self.assertTrue(got["nullable"])   # header is built nullable:false, toggled on
        self.assertFalse(got["hasLimit"])  # nothing invented one on the way through

    # ---- feature type ----------------------------------------------------
    def test_feature_type_switching(self):
        got = self.drive("""
            const std = { features: H.exported().features,
                          missionHidden: d.getElementById("fp-mission").hidden,
                          milestoneHidden: d.getElementById("fp-milestone").hidden };
            const feat = d.getElementById("tpl-feature");
            function pick(v) { feat.value = v; feat.dispatchEvent(new w.Event("change", {bubbles:true})); }

            pick("mission");
            const mission = { block: H.exported().features,
                              missionHidden: d.getElementById("fp-mission").hidden,
                              milestoneHidden: d.getElementById("fp-milestone").hidden };
            const mp = d.getElementById("fp-maxPlacements");
            mp.value = "7"; mp.dispatchEvent(new w.Event("input", {bubbles:true}));
            mission.edited = H.exported().features.mission.maxPlacements;

            pick("milestone");
            const milestone = { block: H.exported().features,
                                missionHidden: d.getElementById("fp-mission").hidden,
                                milestoneHidden: d.getElementById("fp-milestone").hidden };

            pick("standard");
            const backToStd = { features: H.exported().features, raw: H.raw() };

            pick("mission");
            const restored = H.exported().features.mission.maxPlacements;
            return { std, mission, milestone, backToStd, restored };
        """)
        self.assertEqual(got["std"]["features"], {})
        self.assertTrue(got["std"]["missionHidden"])
        self.assertTrue(got["std"]["milestoneHidden"])

        self.assertEqual(sorted(got["mission"]["block"]), ["mission"])
        self.assertEqual(got["mission"]["block"]["mission"]["key"], "missions")
        self.assertEqual(got["mission"]["block"]["mission"]["maxPlacements"], 3)
        self.assertFalse(got["mission"]["missionHidden"])
        self.assertTrue(got["mission"]["milestoneHidden"])
        self.assertEqual(got["mission"]["edited"], 7)

        self.assertEqual(sorted(got["milestone"]["block"]), ["milestone"])
        self.assertEqual(got["milestone"]["block"]["milestone"]["limit"], 3)
        self.assertFalse(got["milestone"]["milestoneHidden"])
        self.assertTrue(got["milestone"]["missionHidden"])

        self.assertEqual(got["backToStd"]["features"], {})
        self.assertIn('"features": {}', got["backToStd"]["raw"])
        self.assertEqual(got["restored"], 7)   # the edited block survives the detour

    def _mission_build(self, **detected):
        analysis = json.loads(json.dumps(ANALYSIS))
        base = {"mission_count": 4, "set_count": 2}
        base.update(detected)
        analysis["feature"] = {"type": "mission", "detected": base}
        return _build_result(analysis)

    def test_mission_layout_toggle_round_trips(self):
        got = self.drive("""
            H.click("tpl-ed");
            const sel = d.getElementById("fp-missionLayout");
            const before = { value: sel.value,
                             options: [...sel.options].map(o => o.value),
                             exported: H.exported().features.mission.missionLayout };
            sel.value = "sequential"; sel.dispatchEvent(new w.Event("change", {bubbles:true}));
            const after = { value: d.getElementById("fp-missionLayout").value,
                            exported: H.exported().features.mission.missionLayout };
            w.undo();
            return { before, after, undone: H.exported().features.mission.missionLayout };
        """, build=self._mission_build())
        self.assertEqual(got["before"]["options"], ["parallel", "sequential"])
        self.assertEqual(got["before"]["value"], "parallel")
        self.assertEqual(got["before"]["exported"], "parallel")
        self.assertEqual(got["after"]["exported"], "sequential")
        self.assertEqual(got["undone"], "parallel")

    def test_progress_bar_control_writes_both_contract_shapes(self):
        got = self.drive("""
            H.click("tpl-ed");
            const bar = () => d.getElementById("fp-progressBar");
            const wrap = () => d.getElementById("fp-maxMilestones-wrap");
            const shownByDefault = { value: bar().value, maxShown: !wrap().hidden,
                                     block: H.exported().features.mission.progressBar };
            // type a cap
            const mm = d.getElementById("fp-maxMilestones");
            mm.value = "7"; mm.dispatchEvent(new w.Event("input", {bubbles:true}));
            const capped = H.exported().features.mission.progressBar;
            // turn it off
            bar().value = "hide"; bar().dispatchEvent(new w.Event("change", {bubbles:true}));
            const off = { block: H.exported().features.mission.progressBar,
                          maxShown: !wrap().hidden };
            // and back on — the cap it remembers comes back with it
            bar().value = "show"; bar().dispatchEvent(new w.Event("change", {bubbles:true}));
            return { shownByDefault, capped, off, on: H.exported().features.mission.progressBar };
        """, build=self._mission_build(milestone_count=5))
        self.assertEqual(got["shownByDefault"]["value"], "show")
        self.assertTrue(got["shownByDefault"]["maxShown"])
        self.assertEqual(got["shownByDefault"]["block"],
                         {"display": "show_for_all_sets_combined",
                          "completionBarCta": ["collect_resource"], "maxMilestones": 5})
        self.assertEqual(got["capped"]["maxMilestones"], 7)
        # off => the contract's other shape, CTA list emptied
        self.assertEqual(got["off"]["block"],
                         {"display": "dont_show_at_all", "completionBarCta": []})
        self.assertFalse(got["off"]["maxShown"])   # the cap input hides with it
        self.assertEqual(got["on"], {"display": "show_for_all_sets_combined",
                                     "completionBarCta": ["collect_resource"],
                                     "maxMilestones": 7})

    def test_mission_panel_exposes_only_the_vision_knobs(self):
        got = self.drive("""
            H.click("tpl-ed");
            const panel = d.getElementById("fp-mission");
            return { selects: [...panel.querySelectorAll("select")].map(e => e.id),
                     inputs: [...panel.querySelectorAll("input")].map(e => e.id).filter(Boolean),
                     multi: panel.querySelectorAll("select[multiple]").length,
                     ctaGroups: [...panel.querySelectorAll(".chips")].map(e => e.dataset.fid),
                     text: panel.textContent,
                     note: H.text("#fp-note") };
        """, build=self._mission_build())
        self.assertEqual(got["selects"], ["fp-missionLayout", "fp-progressBar"])
        self.assertEqual(got["inputs"], ["fp-minPlacements", "fp-maxPlacements",
                                         "fp-minSetsCount", "fp-maxSetsCount",
                                         "fp-maxMilestones"])
        self.assertEqual(got["multi"], 0)          # chips, never a multi-select
        # the ONE menu that is actually sent is editable here…
        self.assertEqual(got["ctaGroups"], ["fp-completionCta"])
        # …and the dashboard-only knobs stay out
        for dashboard_only in ("activeProgressCta", "completionBarCta",
                               "customFields", "scope", "showActiveProgress"):
            self.assertNotIn(dashboard_only, got["text"], dashboard_only)
        self.assertIn("configured on the dashboard", got["note"])

    def test_mission_counts_are_grouped_dashboard_style(self):
        got = self.drive("""
            H.click("tpl-ed");
            const panel = d.getElementById("fp-mission");
            const groups = [...panel.querySelectorAll(".fp-group")].map(g => ({
              label: g.querySelector(".fp-group-label")
                     ? g.querySelector(".fp-group-label").textContent : null,
              labelTitle: g.querySelector(".fp-group-label")
                     ? g.querySelector(".fp-group-label").title : null,
              subLabels: [...g.querySelectorAll(".muted")].map(m => m.textContent),
              inputs: [...g.querySelectorAll("input")].map(i => i.id)
            }));
            return { groups: groups, lines: panel.children.length,
                     oldLabels: panel.textContent.indexOf("maxPlacements") };
        """, build=self._mission_build())
        missions, sets, rest, ctas = got["groups"]
        self.assertEqual(missions["label"], "Number of Missions")
        self.assertIn("mission slots will be visible", missions["labelTitle"])
        self.assertEqual(missions["inputs"], ["fp-minPlacements", "fp-maxPlacements"])
        self.assertEqual(missions["subLabels"], ["Number of Missions", "min", "max"])

        self.assertEqual(sets["label"], "Number of Mission Sets")
        self.assertIn("sets (groups of missions) are allowed", sets["labelTitle"])
        self.assertEqual(sets["inputs"], ["fp-minSetsCount", "fp-maxSetsCount"])
        self.assertEqual(sets["subLabels"], ["Number of Mission Sets", "min", "max"])

        self.assertEqual(rest["inputs"], ["fp-maxMilestones"])   # layout/bar line
        # the cap's label and input get the same 0.6rem gap as the .grid lines
        self.assertIn("#fp-maxMilestones-wrap:not([hidden]) { display: inline-flex; "
                      "gap: 0.6rem;", _read(self._run()[2]))
        self.assertEqual(set(ctas["inputs"]), {""})   # CTA chips carry data-fids, not ids
        self.assertEqual(got["lines"], 4)   # counts, sets, layout/bar, completion CTA
        self.assertEqual(got["oldLabels"], -1)   # per-field labels are gone

    def test_mission_completion_cta_chips_round_trip(self):
        got = self.drive("""
            H.click("tpl-ed");
            const group = () => d.querySelector('[data-fid="fp-completionCta"]');
            const chip = a => d.querySelector('[data-fid="fp-cta-completionCta-' + a + '"]');
            const tick = (a, on) => { const c = chip(a); c.checked = on;
              c.dispatchEvent(new w.Event("change", { bubbles: true })); };
            const built = { selected: H.exported().features.mission.completionCta,
                            chips: group().querySelectorAll(".chip").length,
                            title: group().title,
                            label: group().parentNode.querySelector(".muted").textContent };
            // pick out of menu order — the export comes back in menu order
            tick("show_ad", true); tick("collect_resource", true);
            const picked = H.exported().features.mission.completionCta;
            tick("close", false); tick("show_ad", false); tick("collect_resource", false);
            const empty = { exported: H.exported().features.mission.completionCta,
                            status: H.status(), errors: H.text("#live-errors"),
                            gated: H.gated(),
                            flagged: !!d.querySelector('[data-fid="fp-completionCta"].bad') };
            tick("collect_resource", true);
            return { built, picked, empty, fixed: H.status() };
        """, build=self._mission_build())
        self.assertEqual(got["built"]["selected"], ["close"])   # builder fallback
        self.assertEqual(got["built"]["chips"], len(self.mod.CLICK_ACTIONS))
        self.assertIn("once the mission is completed", got["built"]["title"])
        self.assertEqual(got["built"]["label"], "Mission Completion CTA")
        self.assertEqual(got["picked"], ["close", "collect_resource", "show_ad"])
        # the API requires the menu, so an empty one is an error, not an empty array
        self.assertEqual(got["empty"]["exported"], [])
        self.assertEqual(got["empty"]["status"]["cls"], "bad")
        self.assertIn("Mission Completion CTA needs at least one action",
                      got["empty"]["errors"])
        self.assertTrue(got["empty"]["gated"]["download"])
        self.assertTrue(got["empty"]["flagged"])
        self.assertEqual(got["fixed"]["cls"], "ok")

    def _milestone_build(self, **detected):
        analysis = json.loads(json.dumps(ANALYSIS))
        base = {"milestone_count": 6}
        base.update(detected)
        analysis["feature"] = {"type": "milestone", "detected": base}
        return _build_result(analysis)

    def test_milestone_cta_menus_always_render(self):
        # operator refinement: a developer who knows the CTAs is not "inventing"
        # them, so both menus are always editable — derived or not.
        derived = self.drive("""
            H.click("tpl-ed");
            return { groups: [...d.querySelectorAll('#fp-milestone-ctas .chips')]
                       .map(g => g.dataset.fid),
                     labels: [...d.querySelectorAll('#fp-milestone-ctas .muted')]
                       .map(m => m.textContent).filter(t => t.indexOf("CTA") >= 0),
                     titles: [...d.querySelectorAll('#fp-milestone-ctas .chips')]
                       .map(g => g.title),
                     hints: H.count('#fp-milestone-ctas [data-fid$="-hint"]'),
                     features: H.exported().features.milestone,
                     badge: (H.click("tpl-ed"), H.text("#tpl-view-feature")) };
        """, build=self._milestone_build(main_actions=["close", "show_ad"],
                                         milestone_actions=["collect_resource"]))
        self.assertEqual(derived["groups"], ["fp-mainActionTypes", "fp-milestonesActionTypes"])
        self.assertEqual(derived["labels"], ["Active Progress CTA", "Milestone Completion CTA"])
        self.assertIn("during their progression towards milestones", derived["titles"][0])
        self.assertIn("upon reaching a milestone", derived["titles"][1])
        self.assertEqual(derived["hints"], 0)      # both are filled, so no hint
        self.assertEqual(derived["features"], {"key": "main_progressbar",
                                               "name": "Main Progressbar", "limit": 6,
                                               "mainActionTypes": ["close", "show_ad"],
                                               "milestonesActionTypes": ["collect_resource"]})
        self.assertNotIn("CTA on dashboard", derived["badge"])

        undetected = self.drive("""
            H.click("tpl-ed");
            return { groups: [...d.querySelectorAll('#fp-milestone-ctas .chips')]
                       .map(g => g.dataset.fid),
                     chips: H.count("#fp-milestone-ctas .chip"),
                     hints: [...d.querySelectorAll('#fp-milestone-ctas [data-fid$="-hint"]')]
                       .map(h => h.textContent),
                     oldNote: H.has("#fp-milestone-cta-note"),
                     keys: Object.keys(H.exported().features.milestone),
                     raw: JSON.stringify(H.exported().features),
                     badge: (H.click("tpl-ed"), H.text("#tpl-view-feature")) };
        """, build=self._milestone_build())
        # the groups are there even though the mockup showed nothing
        self.assertEqual(undetected["groups"], ["fp-mainActionTypes", "fp-milestonesActionTypes"])
        self.assertEqual(undetected["chips"], 2 * len(self.mod.CLICK_ACTIONS))
        self.assertEqual(undetected["hints"],
                         ["nothing selected — you'll choose on the dashboard"] * 2)
        self.assertFalse(undetected["oldNote"])   # the standalone note is gone
        # empty stays valid and simply ships no key
        self.assertEqual(undetected["keys"], ["key", "name", "limit"])
        for absent in ("mainActionTypes", "milestonesActionTypes"):
            self.assertNotIn(absent, undetected["raw"])
        self.assertIn("CTA on dashboard", undetected["badge"])

    def test_selecting_an_undetected_milestone_menu_adds_the_key(self):
        got = self.drive("""
            H.click("tpl-ed");
            const tick = (k, a, on) => {
              const c = d.querySelector('[data-fid="fp-cta-' + k + '-' + a + '"]');
              c.checked = on; c.dispatchEvent(new w.Event("change", { bubbles: true }));
            };
            const before = { keys: Object.keys(H.exported().features.milestone),
                             status: H.status() };
            // pick out of menu order — the export normalises to menu order
            tick("mainActionTypes", "show_ad", true);
            tick("mainActionTypes", "close", true);
            const picked = { menu: H.exported().features.milestone.mainActionTypes,
                             hints: H.count('[data-fid="fp-mainActionTypes-hint"]'),
                             otherStillEmpty:
                               "milestonesActionTypes" in H.exported().features.milestone,
                             status: H.status() };
            tick("mainActionTypes", "show_ad", false);
            tick("mainActionTypes", "close", false);
            const cleared = { keys: Object.keys(H.exported().features.milestone),
                              hints: H.count('[data-fid="fp-mainActionTypes-hint"]'),
                              status: H.status() };
            return { before, picked, cleared };
        """, build=self._milestone_build())
        self.assertEqual(got["before"]["keys"], ["key", "name", "limit"])
        self.assertEqual(got["before"]["status"]["cls"], "ok")   # empty is valid here
        self.assertEqual(got["picked"]["menu"], ["close", "show_ad"])
        self.assertEqual(got["picked"]["hints"], 0)      # hint disappears once picked
        self.assertFalse(got["picked"]["otherStillEmpty"])
        self.assertEqual(got["picked"]["status"]["cls"], "ok")
        # clearing it again drops the key and brings the hint back
        self.assertEqual(got["cleared"]["keys"], ["key", "name", "limit"])
        self.assertEqual(got["cleared"]["hints"], 1)
        self.assertEqual(got["cleared"]["status"]["cls"], "ok")

    def test_emptying_a_derived_menu_drops_the_key(self):
        got = self.drive("""
            H.click("tpl-ed");
            const tick = (k, a, on) => {
              const c = d.querySelector('[data-fid="fp-cta-' + k + '-' + a + '"]');
              c.checked = on; c.dispatchEvent(new w.Event("change", { bubbles: true }));
            };
            const before = H.exported().features.milestone;
            tick("mainActionTypes", "close", false);
            tick("mainActionTypes", "show_ad", false);
            const emptied = { features: H.exported().features.milestone,
                              stillEditable: H.has('[data-fid="fp-mainActionTypes"]'),
                              status: H.status(), gated: H.gated() };
            tick("mainActionTypes", "billing", true);
            return { before, emptied, back: H.exported().features.milestone };
        """, build=self._milestone_build(main_actions=["close", "show_ad"]))
        self.assertEqual(got["before"]["mainActionTypes"], ["close", "show_ad"])
        # back to "the dashboard chooses" — the key is gone, not an empty array
        self.assertNotIn("mainActionTypes", got["emptied"]["features"])
        self.assertTrue(got["emptied"]["stillEditable"])   # the group stays on the page
        self.assertEqual(got["emptied"]["status"]["cls"], "ok")   # milestone menus are optional
        self.assertEqual(got["back"]["mainActionTypes"], ["billing"])

    def test_feature_flip_keeps_cta_menus_out_of_the_other_type(self):
        got = self.drive("""
            const feat = d.getElementById("tpl-feature");
            const pick = v => { feat.value = v; feat.dispatchEvent(new w.Event("change", {bubbles:true})); };
            const mission = H.raw();
            pick("milestone");
            const milestone = { raw: H.raw(), features: H.exported().features };
            pick("standard");
            const std = H.exported().features;
            pick("mission");
            return { mission, milestone, std,
                     backToMission: H.exported().features.mission.completionCta };
        """, build=self._mission_build(completion_actions=["collect_resource"]))
        self.assertIn('"completionCta"', got["mission"])
        # the stash keeps mission's menu page-side; it must not leak into milestone
        self.assertNotIn("completionCta", got["milestone"]["raw"])
        self.assertEqual(sorted(got["milestone"]["features"]), ["milestone"])
        self.assertEqual(got["std"], {})
        self.assertEqual(got["backToMission"], ["collect_resource"])

    def test_mission_controls_carry_the_dashboard_wording(self):
        # operator request: hover help lifted from the live dashboard UI, on the
        # label AND the control so either one explains itself.
        got = self.drive("""
            H.click("tpl-ed");
            const t = id => d.getElementById(id).title;
            const labelTitle = id => d.getElementById(id).previousElementSibling.title;
            const feat = d.getElementById("tpl-feature");
            return { placements: t("fp-maxPlacements"), placementsLabel: labelTitle("fp-maxPlacements"),
                     minPlacements: t("fp-minPlacements"),
                     sets: t("fp-maxSetsCount"), setsLabel: labelTitle("fp-maxSetsCount"),
                     minSets: t("fp-minSetsCount"),
                     layout: t("fp-missionLayout"), layoutLabel: labelTitle("fp-missionLayout"),
                     bar: t("fp-progressBar"), barLabel: labelTitle("fp-progressBar"),
                     maxMilestones: t("fp-maxMilestones"),
                     maxMilestonesLabel: labelTitle("fp-maxMilestones"),
                     featureSelect: feat.title,
                     missionOption: [...feat.options].find(o => o.value === "mission").title };
        """, build=self._mission_build())
        for key in ("placements", "placementsLabel", "minPlacements"):
            self.assertIn("mission slots will be visible", got[key], key)
        for key in ("sets", "setsLabel", "minSets"):
            self.assertIn("sets (groups of missions) are allowed", got[key], key)
        for key in ("layout", "layoutLabel"):
            self.assertIn("Parallel: all placements in a set are active at the same time",
                          got[key], key)
            self.assertIn("Sequential: placements unlock one at a time", got[key], key)
            self.assertIn("Sub-missions", got[key], key)
        for key in ("bar", "barLabel"):
            self.assertIn("visually tracked via a progress bar", got[key], key)
        for key in ("maxMilestones", "maxMilestonesLabel"):
            self.assertIn("Maximum number of milestones on the combined progress bar",
                          got[key], key)
        # the closed select mirrors the active option's description
        self.assertIn("task-based challenges with goals, rewards, and CTAs",
                      got["missionOption"])
        self.assertEqual(got["featureSelect"], got["missionOption"])

    def test_milestone_limit_carries_the_dashboard_wording(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["feature"] = {"type": "milestone", "detected": {"milestone_count": 6}}
        got = self.drive("""
            H.click("tpl-ed");
            const el = d.getElementById("fp-limit");
            return { input: el.title, label: el.previousElementSibling.title,
                     featureSelect: d.getElementById("tpl-feature").title };
        """, build=_build_result(analysis))
        self.assertIn("number of milestones the progress bar supports", got["input"])
        self.assertEqual(got["label"], got["input"])
        self.assertEqual(got["featureSelect"], "")   # only missions has dashboard copy

    def test_mission_view_badge_summarises_the_knobs(self):
        got = self.drive("""
            const plain = H.text("#tpl-view-feature");
            H.click("tpl-ed");
            const sel = d.getElementById("fp-missionLayout");
            sel.value = "sequential"; sel.dispatchEvent(new w.Event("change", {bubbles:true}));
            H.click("tpl-ed");
            const sequential = H.text("#tpl-view-feature");
            H.click("tpl-ed");
            const bar = d.getElementById("fp-progressBar");
            bar.value = "hide"; bar.dispatchEvent(new w.Event("change", {bubbles:true}));
            H.click("tpl-ed");
            return { plain, sequential, noBar: H.text("#tpl-view-feature") };
        """, build=self._mission_build(milestone_count=5))
        # parallel is the default, so it is not spelled out
        self.assertEqual(got["plain"], "missions · 1–4 slots · 2 sets · bar ≤5")
        self.assertEqual(got["sequential"], "missions · 1–4 slots · 2 sets · sequential · bar ≤5")
        self.assertEqual(got["noBar"], "missions · 1–4 slots · 2 sets · sequential")

    def test_mission_build_carries_its_block(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["feature"] = {"type": "mission", "detected": {"mission_count": 4, "set_count": 2}}
        got = self.drive("""
            return { features: H.exported().features,
                     hidden: d.getElementById("fp-mission").hidden,
                     maxPlacements: d.getElementById("fp-maxPlacements").value };
        """, build=_build_result(analysis))
        self.assertEqual(got["features"]["mission"]["maxPlacements"], 4)
        self.assertEqual(got["features"]["mission"]["maxSetsCount"], 2)
        self.assertFalse(got["hidden"])
        self.assertEqual(got["maxPlacements"], "4")

    # ---- report channels on the page ------------------------------------
    def test_unmapped_is_rendered_and_never_dropped(self):
        got = self.drive("""
            return { notes: H.text("#build-notes"),
                     raw: d.querySelector("#build-notes pre").textContent,
                     payload: H.raw() };
        """)
        self.assertIn("Unmapped (1)", got["notes"])
        self.assertIn("sparkle_thing", got["notes"])
        self.assertIn("unknown role", got["notes"])
        self.assertIn("sparkle_thing", got["raw"])          # the raw element is shown
        self.assertNotIn("sparkle_thing", got["payload"])   # but never registered

    def test_needs_confirmation_is_rendered(self):
        got = self.drive("""
            return { notes: H.text("#build-notes"),
                     rowNote: H.text(".row .confirm-note"),
                     noteCount: H.count(".row .confirm-note"),
                     stillInPayload: H.exported().texts.some(e => e.key === "soft_billing_old_price") };
        """)
        self.assertIn("Needs your confirmation (1)", got["notes"])
        self.assertIn("texts.soft_billing_old_price", got["notes"])
        self.assertIn("billing", got["notes"])
        self.assertEqual(got["noteCount"], 1)
        self.assertIn("Confirm:", got["rowNote"])
        self.assertTrue(got["stillInPayload"])  # flagged for a decision, not removed

    def test_build_warnings_are_rendered(self):
        analysis = json.loads(json.dumps(ANALYSIS))
        analysis["elements"].append({"role": "cta_button", "suggested_key": "mystery",
                                     "observed_text": "zzz", "confidence": 0.2})
        got = self.drive("return H.text('#build-notes');", build=_build_result(analysis))
        self.assertIn("Build warnings", got)
        self.assertIn("low detection confidence", got)

    def test_client_rendered_regions_are_shown_but_not_editable(self):
        self._with_image()
        # source_image.path resolves next to the build file, so the overlay renders.
        got = self.drive("""
            return { list: H.text("#cr-list"),
                     boxes: H.count("#overlay .box"),
                     client: H.count("#overlay .box.client"),
                     rows: H.count(".row"),
                     payload: H.raw() };
        """)
        self.assertIn("timer", got["list"])
        self.assertEqual(got["client"], 1)
        self.assertEqual(got["boxes"], 8)   # 7 elements with a bbox + 1 client-rendered
        self.assertEqual(got["rows"], 8)    # show_banner has no bbox but still gets a row
        self.assertNotIn("timer", got["payload"])

    # ---- add / remove ----------------------------------------------------
    def test_add_and_remove_elements(self):
        got = self.drive("""
            H.click("add-texts");
            const added = { status: H.status(), rows: H.count("#elements .row.b-texts"),
                            errors: H.text("#live-errors") };
            const fid = [...d.querySelectorAll(
              '#elements .row.b-texts input[data-fid^="e"][data-fid$="-key"]')].pop().dataset.fid;
            H.typeInto(fid, "extra_line");
            const uid = [...d.querySelectorAll("#elements .row.b-texts")].pop().dataset.uid;
            const nameFid = fid.replace("-key", "-name");
            H.typeInto(nameFid, "Extra Line");
            added.afterNaming = H.status();
            added.exported = H.exported().texts.map(e => e.key);

            H.click("rm-" + uid);
            added.afterRemoval = { rows: H.count("#elements .row.b-texts"),
                                   keys: H.exported().texts.map(e => e.key),
                                   status: H.status() };
            return added;
        """)
        self.assertEqual(got["status"]["cls"], "bad")   # a keyless new row is invalid
        self.assertEqual(got["rows"], 4)  # 3 proposed + 1 page-added
        self.assertEqual(got["afterNaming"]["cls"], "ok")
        self.assertIn("extra_line", got["exported"])
        self.assertEqual(got["afterRemoval"]["rows"], 3)
        self.assertNotIn("extra_line", got["afterRemoval"]["keys"])
        self.assertEqual(got["afterRemoval"]["status"]["cls"], "ok")

    def test_standard_exports_empty_features_and_tags(self):
        got = self.drive("""
            return { features: H.exported().features, tags: H.exported().tagsIds, raw: H.raw() };
        """)
        self.assertEqual(got["features"], {})        # the create contract, not null
        self.assertEqual(got["tags"], [])
        self.assertIn('"tagsIds": []', got["raw"])

    def test_tags_ids_are_passed_through(self):
        build = _build_result()
        build["payload"]["tagsIds"] = [7, 9]
        got = self.drive("return H.exported().tagsIds;", build=build)
        self.assertEqual(got, [7, 9])

    def test_custom_cta_names_shown_only_for_the_custom_action(self):
        got = self.drive("""
            H.openAll();
            const row = [...d.querySelectorAll("#elements .row.b-buttons")].find(
              r => r.querySelector('[data-fid$="-cta"]'));
            const ctaFid = row.querySelector('[data-fid$="-cta"]').dataset.fid;
            const uid = row.dataset.uid;
            const built = { shown: H.has('[data-fid$="-cta"]'), value: H.byFid(ctaFid).value,
                            exported: H.exported().buttons.find(e => e.key === "info_button").customCtaNames };

            // drop 'custom' -> the input disappears and the names stop shipping
            H.setActions(uid, ["close"]);
            const off = { shown: H.has('[data-fid$="-cta"]'),
                          exported: "customCtaNames" in H.exported().buttons.find(e => e.key === "info_button"),
                          status: H.status(), warn: H.text("#live-errors") };

            // put it back and rename
            H.setActions(uid, ["custom", "close"]);
            H.typeInto(ctaFid, "Rules, Help");
            const back = { exported: H.exported().buttons.find(e => e.key === "info_button").customCtaNames,
                           status: H.status() };
            return { built, off, back };
        """)
        self.assertTrue(got["built"]["shown"])
        self.assertEqual(got["built"]["value"], "Info")
        self.assertEqual(got["built"]["exported"], ["Info"])
        self.assertFalse(got["off"]["shown"])
        self.assertFalse(got["off"]["exported"])
        # names kept in the page state but not offered -> warning, not an error
        self.assertEqual(got["off"]["status"]["cls"], "warn")
        self.assertIn("customCtaNames present", got["off"]["warn"])
        self.assertEqual(got["back"]["exported"], ["Rules", "Help"])
        self.assertEqual(got["back"]["status"]["cls"], "ok")

    def test_custom_action_without_names_is_an_error(self):
        got = self.drive("""
            H.openAll();
            const row = [...d.querySelectorAll("#elements .row.b-buttons")].find(
              r => r.querySelector('[data-fid$="-cta"]'));
            const ctaFid = row.querySelector('[data-fid$="-cta"]').dataset.fid;
            const el = H.byFid(ctaFid);
            el.focus(); el.value = ""; el.dispatchEvent(new w.Event("input", {bubbles:true}));
            const bad = { status: H.status(), errors: H.text("#live-errors"),
                          rowFlagged: H.count("#elements .row.b-buttons.invalid"),
                          exported: H.exported().buttons.find(e => e.key === "info_button").customCtaNames };
            H.typeInto(ctaFid, "Info");
            bad.after = H.status();
            return bad;
        """)
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertIn("requires a non-empty customCtaNames", got["errors"])
        self.assertEqual(got["rowFlagged"], 1)
        self.assertEqual(got["exported"], [])     # never silently repaired
        self.assertEqual(got["after"]["cls"], "ok")

    def test_image_kind_custom_field_is_accepted(self):
        got = self.drive("""
            return { status: H.status(),
                     prov: [...d.querySelectorAll(".row table.sub")].map(e => e.textContent).join(" | "),
                     exported: H.exported().buttons.find(e => e.key === "info_button").customFields };
        """)
        self.assertEqual(got["status"]["cls"], "ok")   # 'image' is a valid customField kind
        self.assertIn("glyph", got["prov"])
        self.assertEqual(got["exported"][0]["kind"], "image")

    def test_unsupported_mechanics_are_surfaced(self):
        got = self.drive("return H.text('#build-notes');")
        self.assertIn("Not expressible as a template (1)", got)
        self.assertIn("animated confetti burst", got)

    def test_template_header_fields_reach_the_payload(self):
        got = self.drive("""
            H.click("tpl-ed");                     // ✎ edit on the header card
            H.typeInto("tpl-name", "Autumn Offer");
            H.typeInto("tpl-key", "autumn_offer");
            H.typeInto("tpl-desc", "seasonal pack");
            const ok = H.exported();
            H.typeInto("tpl-key", "9bad");
            return { ok: ok, status: H.status(),
                     bad: d.getElementById("tpl-key").classList.contains("bad") };
        """)
        self.assertEqual(got["ok"]["name"], "Autumn Offer")
        self.assertEqual(got["ok"]["key"], "autumn_offer")
        self.assertEqual(got["ok"]["description"], "seasonal pack")
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertTrue(got["bad"])

    def test_game_id_absent_when_the_build_had_none(self):
        got = self.drive("return Object.keys(H.exported());",
                         build=_build_result(game_id=None))
        self.assertNotIn("gameId", got)


if __name__ == "__main__":
    unittest.main()
