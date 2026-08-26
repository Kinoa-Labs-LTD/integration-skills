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
function fidOf(selector) {
  const el = d.querySelector(selector);
  if (!el) throw new Error("no element matching " + selector);
  return el.dataset.fid;
}
const H = {
  typeInto, setSelect, setMulti, click, byFid, fidOf,
  exported: () => JSON.parse(w.exportJson()),
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
        self.assertEqual(sorted(data), ["payload", "report", "validation"])
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
        self.assertEqual(self.mod.DEFAULT_IMAGE_SIZE, builder.DEFAULT_IMAGE_SIZE)
        self.assertEqual(self.mod.DEFAULT_BUTTON_BG, builder.DEFAULT_BUTTON_BG)
        self.assertEqual(self.mod.DEFAULT_TEXT_LIMIT, builder.DEFAULT_TEXT_LIMIT)
        # Feature seeds must match what the builder emits for an empty detection.
        self.assertEqual(self.mod.MISSION_DEFAULTS, builder._mission_feature({}))
        self.assertEqual(self.mod.MILESTONE_DEFAULTS, builder._milestone_feature({}))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
@unittest.skipUnless(os.path.isdir(JSDOM),
                     "jsdom not installed — run `npm install` in tests/page-harness")
class ConfirmPageInteractionTests(_PageCase):
    def setUp(self):
        super().setUp()
        self.runner = os.path.join(self.tmp.name, "runner.js")
        with open(self.runner, "w", encoding="utf-8") as f:
            f.write(RUNNER_JS)

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
    def test_export_is_only_the_create_body(self):
        got = self.drive("return { keys: Object.keys(H.exported()), raw: H.raw() };")
        self.assertEqual(got["keys"], ["name", "key", "description", "gameId",
                                       "images", "buttons", "texts", "customs",
                                       "featureType", "features", "tagsIds"])
        for leaked in ("bbox", "report", "validation", "unmapped", "client_rendered",
                       "needs_confirmation", "observed_text", "confidence", "uid",
                       "\"role\"", "confirm"):
            self.assertNotIn(leaked, got["raw"], "%s leaked into the payload" % leaked)

    def test_indexes_are_dense_across_all_buckets(self):
        got = self.drive("""
            const p = H.exported();
            const flat = [].concat(p.images, p.buttons, p.texts, p.customs);
            return { idx: flat.map(e => e.index), keys: flat.map(e => e.key) };
        """)
        self.assertEqual(got["idx"], list(range(len(got["idx"]))))
        # Display order is bucket by bucket, so the first index belongs to images.
        self.assertEqual(got["keys"][0], "background_image")

    def test_reindex_follows_a_bucket_move(self):
        got = self.drive("""
            H.setSelect(H.fidOf('#bucket-customs .row select[data-fid$="-bucket"]'), "images");
            const p = H.exported();
            const flat = [].concat(p.images, p.buttons, p.texts, p.customs);
            return { idx: flat.map(e => e.index),
                     images: p.images.map(e => e.key), customs: p.customs.length };
        """)
        self.assertEqual(got["idx"], list(range(len(got["idx"]))))
        self.assertEqual(got["images"], ["background_image", "show_banner"])
        self.assertEqual(got["customs"], 0)

    def test_export_round_trips_through_the_builder(self):
        payload = self.drive("return H.exported();")
        builder = _load_module(BUILDER_PATH, "inapp_template_build_roundtrip")
        self.assertEqual(builder.validate_payload(payload), {"ok": True, "errors": [], "warnings": []})

    # ---- bucket switching ------------------------------------------------
    def test_bucket_switch_rewrites_the_shape(self):
        got = self.drive("""
            const fid = H.fidOf('#bucket-texts .row select[data-fid$="-bucket"]');
            H.setSelect(fid, "customs");
            const moved = H.exported().customs.find(e => e.key === "header");
            // and back again — the text-only fields must be restored, not lost
            const back = H.fidOf('#bucket-customs .row select[data-fid$="-bucket"]');
            H.setSelect(back, "texts");
            const returned = H.exported().texts.find(e => e.key === "header");
            return { moved: moved, returned: returned };
        """)
        moved, returned = got["moved"], got["returned"]
        self.assertEqual(sorted(moved), ["canBeHidden", "customFields", "defaultValue",
                                         "description", "index", "key", "kind", "name",
                                         "nullable"])
        self.assertEqual(moved["kind"], "string")       # bucket default
        self.assertEqual(moved["defaultValue"], "")     # bucket default
        self.assertEqual(returned["textLimit"], 255)
        self.assertIn("nullable", returned)
        self.assertNotIn("kind", returned)

    def test_bucket_switch_into_buttons_seeds_button_defaults(self):
        got = self.drive("""
            H.setSelect(H.fidOf('#bucket-images .row select[data-fid$="-bucket"]'), "buttons");
            return H.exported().buttons.find(e => e.key === "background_image");
        """)
        self.assertEqual(got["clickActionType"], ["close"])
        self.assertEqual(got["textLimit"], 255)
        self.assertEqual(got["backgroundImg"], {"width": 10000, "height": 10000, "maxSize": 10000})
        self.assertNotIn("size", got)

    # ---- live validation -------------------------------------------------
    def test_bad_key_pattern_is_flagged(self):
        got = self.drive("""
            const fid = H.fidOf('#bucket-images .row input[data-fid$="-key"]');
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
            const fid = H.fidOf('#bucket-images .row input[data-fid$="-key"]');
            H.typeInto(fid, "Bad Key");
            H.typeInto(fid, "bg_art");
            return { status: H.status(), keys: H.exported().images.map(e => e.key) };
        """)
        self.assertEqual(got["status"]["cls"], "ok")
        self.assertEqual(got["keys"], ["bg_art"])

    def test_duplicate_key_within_a_bucket_is_flagged(self):
        got = self.drive("""
            const keys = [...d.querySelectorAll('#bucket-texts .row input[data-fid$="-key"]')];
            const first = keys[0].value, fid = keys[1].dataset.fid;
            H.typeInto(fid, first);
            const dup = { status: H.status(), rows: H.count("#bucket-texts .row.invalid"),
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
            const fid = H.fidOf('#bucket-buttons select[data-fid$="-actions"]');
            H.setMulti(fid, []);
            const bad = { status: H.status(), errors: H.text("#live-errors"),
                          exported: H.exported().buttons[0].clickActionType };
            H.setMulti(H.fidOf('#bucket-buttons select[data-fid$="-actions"]'), ["close"]);
            bad.after = H.status();
            return bad;
        """)
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertIn("clickActionType", got["errors"])
        self.assertEqual(got["exported"], [])   # never silently repaired
        self.assertEqual(got["after"]["cls"], "ok")

    def test_hand_back_buttons_stay_enabled_while_invalid(self):
        got = self.drive("""
            H.typeInto(H.fidOf('#bucket-images .row input[data-fid$="-key"]'), "Bad Key");
            return { status: H.status(),
                     download: d.getElementById("download").disabled,
                     copy: d.getElementById("copy").disabled,
                     preview: d.getElementById("preview").textContent.length > 0 };
        """)
        self.assertEqual(got["status"]["cls"], "bad")
        self.assertFalse(got["download"])
        self.assertFalse(got["copy"])
        self.assertTrue(got["preview"])

    # ---- conditional controls -------------------------------------------
    def test_required_items_count_only_for_item_bearing_actions(self):
        got = self.drive("""
            const fid = H.fidOf('#bucket-buttons select[data-fid$="-actions"]');
            const before = { shown: H.has('[data-fid$="-items"]'),
                             exported: "requiredItemsCount" in H.exported().buttons[0] };
            H.setMulti(fid, ["collect_resource"]);
            const collect = { shown: H.has('[data-fid$="-items"]'),
                              value: H.exported().buttons[0].requiredItemsCount };
            H.setMulti(H.fidOf('#bucket-buttons select[data-fid$="-actions"]'), ["promise_rewards"]);
            const promise = { shown: H.has('[data-fid$="-items"]') };
            H.setMulti(H.fidOf('#bucket-buttons select[data-fid$="-actions"]'), ["close"]);
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
            const fid = H.fidOf('#bucket-customs select[data-fid$="-kind"]');
            const before = { shown: H.has('#bucket-customs [data-fid$="-enum"]'),
                             exported: "enumValues" in H.exported().customs[0] };
            H.setSelect(fid, "enumeration");
            H.typeInto(H.fidOf('#bucket-customs [data-fid$="-enum"]'), "a, b, c");
            const on = { shown: H.has('#bucket-customs [data-fid$="-enum"]'),
                         value: H.exported().customs[0].enumValues };
            H.setSelect(H.fidOf('#bucket-customs select[data-fid$="-kind"]'), "boolean");
            const off = { shown: H.has('#bucket-customs [data-fid$="-enum"]'),
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

    def test_button_text_limit_is_editable(self):
        got = self.drive("""
            const fid = H.fidOf('#bucket-buttons .row [data-fid$="-limit"]');
            H.typeInto(fid, "42");
            const b = H.exported().buttons.find(e => e.key === "close_button");
            return { limit: b.textLimit, other: H.exported().buttons.find(e => e.key === "cta_button").textLimit };
        """)
        self.assertEqual(got["limit"], 42)
        self.assertEqual(got["other"], 255)   # untouched button keeps the built value

    def test_clearing_a_numeric_field_does_not_snap_back(self):
        # Numerics are held as raw text while typing: coercing per keystroke made
        # a cleared field jump to the default, so "select all, type 42" produced
        # 25542 instead of 42.
        got = self.drive("""
            const fid = H.fidOf('#bucket-texts .row [data-fid$="-limit"]');
            const el = H.byFid(fid);
            el.focus(); el.value = ""; el.dispatchEvent(new w.Event("input", {bubbles:true}));
            const cleared = { shown: H.byFid(fid).value,
                              exported: H.exported().texts[0].textLimit };
            H.typeInto(fid, "42");
            return { cleared: cleared, typed: H.exported().texts[0].textLimit };
        """)
        self.assertEqual(got["cleared"]["shown"], "")
        self.assertEqual(got["cleared"]["exported"], 255)   # default only at export time
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

    def test_text_nullable_and_limit_are_editable(self):
        got = self.drive("""
            H.typeInto(H.fidOf('#bucket-texts .row [data-fid$="-limit"]'), "80");
            const chk = H.byFid(H.fidOf('#bucket-texts .row [data-fid$="-nullable"]'));
            chk.checked = !chk.checked;
            chk.dispatchEvent(new w.Event("change", { bubbles: true }));
            const t = H.exported().texts.find(e => e.key === "header");
            return { limit: t.textLimit, nullable: t.nullable };
        """)
        self.assertEqual(got["limit"], 80)
        self.assertTrue(got["nullable"])   # header is built nullable:false, toggled on

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
        img = os.path.join(self.tmp.name, "mockup.png")
        with open(img, "wb") as f:
            f.write(PNG_BYTES)
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
            const added = { status: H.status(), rows: H.count("#bucket-texts .row"),
                            errors: H.text("#live-errors") };
            const fid = [...d.querySelectorAll('#bucket-texts .row input[data-fid$="-key"]')].pop().dataset.fid;
            H.typeInto(fid, "extra_line");
            const nameFid = fid.replace("-key", "-name");
            H.typeInto(nameFid, "Extra Line");
            added.afterNaming = H.status();
            added.exported = H.exported().texts.map(e => e.key);

            const removeFid = fid.replace("-key", "-remove");
            H.click(removeFid);
            added.afterRemoval = { rows: H.count("#bucket-texts .row"),
                                   keys: H.exported().texts.map(e => e.key),
                                   status: H.status() };
            return added;
        """)
        self.assertEqual(got["status"]["cls"], "bad")   # a keyless new row is invalid
        self.assertEqual(got["rows"], 4)
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
            const row = [...d.querySelectorAll("#bucket-buttons .row")]
              .find(r => r.textContent.indexOf("info_button") >= 0)
              || [...d.querySelectorAll("#bucket-buttons .row")].find(
                   r => r.querySelector('[data-fid$="-cta"]'));
            const ctaFid = row.querySelector('[data-fid$="-cta"]').dataset.fid;
            const actionsFid = row.querySelector('select[data-fid$="-actions"]').dataset.fid;
            const built = { shown: H.has('[data-fid$="-cta"]'), value: H.byFid(ctaFid).value,
                            exported: H.exported().buttons.find(e => e.key === "info_button").customCtaNames };

            // drop 'custom' -> the input disappears and the names stop shipping
            H.setMulti(actionsFid, ["close"]);
            const off = { shown: H.has('[data-fid$="-cta"]'),
                          exported: "customCtaNames" in H.exported().buttons.find(e => e.key === "info_button"),
                          status: H.status(), warn: H.text("#live-errors") };

            // put it back and rename
            H.setMulti(actionsFid, ["custom", "close"]);
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
            const row = [...d.querySelectorAll("#bucket-buttons .row")].find(
              r => r.querySelector('[data-fid$="-cta"]'));
            const ctaFid = row.querySelector('[data-fid$="-cta"]').dataset.fid;
            const el = H.byFid(ctaFid);
            el.focus(); el.value = ""; el.dispatchEvent(new w.Event("input", {bubbles:true}));
            const bad = { status: H.status(), errors: H.text("#live-errors"),
                          rowFlagged: H.count("#bucket-buttons .row.invalid"),
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
                     prov: [...d.querySelectorAll(".row .prov")].map(e => e.textContent).join(" | "),
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
