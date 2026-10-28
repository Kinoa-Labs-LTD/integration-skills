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
CANVAS_SCALER_GUID = "0cd44c1031e13a943bb63640046fad76"  # UnityEngine.UI.CanvasScaler
GRAPHIC_RAYCASTER_GUID = "dc42784cf147c0c48a680349fa168899"  # UnityEngine.UI.GraphicRaycaster
CANVAS_CLASS_ID = "223"                                  # built-in Canvas component
_RENDER_MODES = {"0": "overlay", "1": "camera", "2": "world"}
_SCALE_MODES = {"0": "constant_pixel_size", "1": "scale_with_screen_size", "2": "constant_physical_size"}

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
    rects, monos, canvases = {}, [], {}
    for tag, body in _split_yaml_docs(text):
        if tag == "224":
            rects[(_field(body, "m_GameObject") or "").replace(" ", "")] = body
        elif tag == "114":
            monos.append(body)
        elif tag == CANVAS_CLASS_ID:
            canvases[(_field(body, "m_GameObject") or "").replace(" ", "")] = body

    summary = {"name": os.path.splitext(os.path.basename(path))[0], "legacy_text": 0, "tmp_text": 0,
               "font_guid": None, "tmp_font_guid": None, "root_size": None,
               "close_sprite_guid": None, "root_scripts": [], "unresolved_root_scripts": [], "canvas": None}

    # Root = the RectTransform whose m_Father is {fileID: 0}.
    root_go_ref = None
    for go_ref, body in rects.items():
        if (_field(body, "m_Father") or "").replace(" ", "") == "{fileID:0}":
            root_go_ref = go_ref
            size = _field(body, "m_SizeDelta") or ""
            m = re.search(r"x:\s*(-?[\d.]+),\s*y:\s*(-?[\d.]+)", size)
            if m:
                x, y = float(m.group(1)), float(m.group(2))
                # Treat zero/negative sizes as None (stretch-anchored roots)
                if x > 0 and y > 0:
                    summary["root_size"] = [x, y]

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
        elif script == CANVAS_SCALER_GUID:
            if go_ref == root_go_ref:
                scaler = _probe_scaler(body)
                summary.setdefault("_scaler", scaler)
        elif script == GRAPHIC_RAYCASTER_GUID:
            if go_ref == root_go_ref:
                summary["_raycaster"] = True
        elif script and go_ref == root_go_ref and script not in (BUTTON_GUID,):
            # Only append resolved class names; track unresolved GUIDs separately
            class_name = meta_index.get(script)
            if class_name:
                summary["root_scripts"].append(class_name)
            else:
                summary["unresolved_root_scripts"].append(script)

    # A canvas on the root of a reference pop-up: its settings are the game's convention for pop-ups.
    canvas_body = canvases.get(root_go_ref) if root_go_ref else None
    if canvas_body is not None:
        scaler = summary.get("_scaler") or {}
        summary["canvas"] = {
            "render_mode": _RENDER_MODES.get((_field(canvas_body, "m_RenderMode") or "0").strip(), "overlay"),
            "override_sorting": (_field(canvas_body, "m_OverrideSorting") or "0").strip() == "1",
            "sorting_order": _int_or(_field(canvas_body, "m_SortingOrder"), 0),
            "scale_mode": scaler.get("scale_mode", "constant_pixel_size"),
            "reference_resolution": scaler.get("reference_resolution"),
            "match": scaler.get("match", 0.5),
            "graphic_raycaster": bool(summary.get("_raycaster")),
            "source": summary["name"],
        }
    summary.pop("_scaler", None)
    summary.pop("_raycaster", None)
    return summary


def _int_or(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _probe_scaler(body):
    out = {"scale_mode": _SCALE_MODES.get((_field(body, "m_UiScaleMode") or "0").strip(), "constant_pixel_size")}
    m = re.search(r"x:\s*(-?[\d.]+),\s*y:\s*(-?[\d.]+)", _field(body, "m_ReferenceResolution") or "")
    if m and float(m.group(1)) > 0 and float(m.group(2)) > 0:
        out["reference_resolution"] = [float(m.group(1)), float(m.group(2))]
    try:
        out["match"] = float((_field(body, "m_MatchWidthOrHeight") or "0.5").strip())
    except ValueError:
        out["match"] = 0.5
    return out


def probe_style(prefab_paths, assets_root):
    meta_index = _meta_guid_index(assets_root) if assets_root and os.path.isdir(assets_root) else {}
    result = {"schema_version": SCHEMA_VERSION, "text_system": "unknown", "font_guid": None,
              "tmp_font_guid": None, "root_size": None, "close_sprite_guid": None,
              "base_classes": [], "prefabs": [], "warnings": [], "canvas": None}
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
        result["canvas"] = result["canvas"] or s.get("canvas")
        for cls in s["root_scripts"]:
            if cls not in result["base_classes"]:
                result["base_classes"].append(cls)
        # Add warnings for unresolved root-script GUIDs
        for guid in s["unresolved_root_scripts"]:
            result["warnings"].append("root script %s in %s not found under assets-root — not reported as a base class" % (guid, s["name"]))
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


# --------------------------------------------------------------------------- naming

_CS_KEYWORDS = {"object", "event", "string", "class", "base", "default", "params", "ref", "out", "in",
                "new", "lock", "fixed", "checked", "operator", "namespace", "internal", "switch", "case"}
_FIELD_SUFFIX = {"images": "Image", "texts": "Text", "buttons": "Button"}
DEFAULT_OUT_DIR = "Assets/Kinoa/InApps"
VIEW_NAMESPACE = "Kinoa.InApps"

RESERVED_NODE_NAMES = {"Dimmer", "Frame", "Panel", "Unplaced", "TimerZone", "TimerText", "PriceBeforeSaleZone",
                       "PriceBeforeSaleText", "PriceBeforeSaleStrike", "ResourceArea", "ResourceItem",
                       "GrandPrizeArea", "GrandPrizeImage", "GrandPrizeText", "MilestoneMainButton", "MilestoneMainButtonLabel",
                       "MilestoneScroll", "MilestoneViewport", "MilestoneContent", "MilestoneStep",
                       "MissionList", "MissionRow", "MissionBar", "MissionBarFill"}
RESERVED_FIELDS = {"dimmer", "panel", "timerRoot", "timerText", "priceBeforeSaleRoot", "priceBeforeSaleText",
                   "resourceAreaRoot", "resourceItemTemplate", "grandPrizeRoot", "grandPrizeImage", "grandPrizeText",
                   "milestoneMainButton", "milestoneMainButtonLabel", "missionListRoot", "missionRowTemplate",
                   "missionBarRoot", "missionBarFill", "milestoneScroll", "milestoneContent", "milestoneStepTemplate"}


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
        # Suffix is already present only if key has multiple tokens and last token matches suffix (case-insensitive)
        parts = [p for p in re.split(r"[^0-9a-zA-Z]+", key or "") if p]
        if len(parts) <= 1 or parts[-1].lower() != suffix.lower():
            # Either single/empty token (always append) or last token doesn't match suffix
            base += suffix
        else:
            # Multiple tokens with last matching suffix (case-insensitive); fix capitalization
            base = base[: -len(suffix)] + suffix
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


def unwrap_style(obj):
    """Accept `probe-style --out` output ({"ok": true, "style": {...}}) or a bare style dict."""
    if isinstance(obj, dict) and isinstance(obj.get("style"), dict):
        return obj["style"]
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
    src = report.get("source_image") or {}
    size = [src["width"], src["height"]] if src.get("width") and src.get("height") else None
    return {"elements": elements, "client_zones": zones, "image_size": size, "source": "build_result"}


def _layout_source(layout):
    """Which kind of layout positioned this plan; recorded in report.layout_source."""
    if not layout:
        return {"kind": None}
    out = {"kind": layout.get("source") or "unknown"}
    if layout.get("source") == "layout_artifact":
        out.update({"template_key": layout.get("template_key"), "sha256": layout.get("sha256"),
                    "hand_placed": layout.get("hand_placed", 0), "adjusted": layout.get("adjusted", 0)})
    return out


def _check_artifact_join(template, layout, report):
    """Enforce the artifact's 1:1 join with its template (warnings + unmapped_layout entries)."""
    if not layout or layout.get("source") != "layout_artifact":
        return
    report["warnings"].extend(layout.get("warnings") or [])
    entries = layout.get("entries") or []
    template_pairs = [(b, slot["key"]) for b in BUCKETS for slot in template.get(b) or [] if slot.get("key")]
    seen = set()
    for pair in entries:
        if pair in seen:
            report["warnings"].append("layout artifact has a duplicate entry for %s.%s; the last one wins" % pair)
        seen.add(pair)
        if pair not in template_pairs:
            entry = {"bucket": pair[0], "key": pair[1]}
            if entry not in report["unmapped_layout"]:
                report["unmapped_layout"].append(entry)
    for pair in template_pairs:
        if pair not in seen:
            report["warnings"].append(
                "template slot %s.%s has no entry in the layout artifact; the artifact may predate a template edit"
                % pair)
    indexes = layout.get("indexes") or {}
    for bucket in _POSITIONED_BUCKETS:
        for slot in template.get(bucket) or []:
            got = indexes.get((bucket, slot.get("key")))
            if got is not None and slot.get("index") is not None and got != slot.get("index"):
                report["warnings"].append(
                    "layout artifact index for %s.%s is %s but the template says %s; the artifact may be stale"
                    % (bucket, slot.get("key"), got, slot.get("index")))
    ftype = layout.get("feature_type")
    expected = template.get("featureType") or "standard"
    if ftype and ftype != expected:
        report["warnings"].append("layout artifact feature type is %r but the template's featureType is %r"
                                  % (ftype, expected))


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
          bucket=None, role=None, click_actions=None, custom_cta_names=None, sprite_guid=None,
          step_button=False):
    return {"name": name, "parent": parent, "binding": binding, "components": components or [],
            "field": field, "field_type": field_type, "anchor_min": anchor_min, "anchor_max": anchor_max,
            "size": size, "placed": placed, "can_be_hidden": can_be_hidden, "inactive": inactive,
            "key": key, "bucket": bucket, "role": role, "click_actions": click_actions or [],
            "custom_cta_names": custom_cta_names or [], "sprite_guid": sprite_guid,
            "step_button": bool(step_button)}


DEFAULT_SORTING_ORDER = 100   # above a typical HUD canvas; align it with the game's pop-up layer


def _plan_canvas(probed, frame_size, report):
    """Canvas / CanvasScaler / GraphicRaycaster settings for the prefab root.

    Copied from a reference pop-up whose root has a canvas, else popup defaults: an overlay canvas
    sorted above the HUD, scaling with the screen at the design's frame size. Either way the
    developer is told to align them: they depend on the game's own UI setup.
    """
    if probed:
        canvas = {
            "render_mode": probed.get("render_mode") or "overlay",
            "override_sorting": bool(probed.get("override_sorting")),
            "sorting_order": int(probed.get("sorting_order") or 0),
            "scale_mode": probed.get("scale_mode") or "scale_with_screen_size",
            "reference_resolution": list(probed.get("reference_resolution") or frame_size),
            "match": float(probed.get("match") if probed.get("match") is not None else 0.5),
            "source": probed.get("source") or "probe",
        }
        note = "copied from %s" % canvas["source"]
    else:
        canvas = {"render_mode": "overlay", "override_sorting": True, "sorting_order": DEFAULT_SORTING_ORDER,
                  "scale_mode": "scale_with_screen_size", "reference_resolution": list(frame_size), "match": 0.5,
                  "source": "default"}
        note = "defaults: overlay, sorting order %d, scale with screen size at %gx%g, match 0.5" % (
            DEFAULT_SORTING_ORDER, frame_size[0], frame_size[1])
    report["needs_developer"].append(
        "the prefab root gets a Canvas, CanvasScaler and GraphicRaycaster (%s); check and align them with your UI "
        "setup, or remove them when the prefab is parented under an existing pop-up canvas" % note)
    if canvas["render_mode"] == "camera":
        report["needs_developer"].append(
            "the canvas render mode is Screen Space - Camera: assign its camera at runtime (the builder cannot)")
    elif canvas["render_mode"] == "world":
        report["needs_developer"].append("the canvas render mode is World Space: position and size it in the scene")
    return canvas


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
              "client_zones": [], "needs_developer": [], "layout_source": _layout_source(layout)}

    layout_key = (layout or {}).get("template_key")
    if layout_key and layout_key != key:
        return {"ok": False, "error": "layout_template_mismatch",
                "detail": "layout artifact is for template %r, not %r; it joins its template 1:1" % (layout_key, key)}
    _check_artifact_join(template, layout, report)

    by_pair, by_key, zone_boxes = _index_layout(layout)
    if not layout or not (layout.get("elements") or layout.get("client_zones")):
        report["warnings"].append("no layout source given — every slot is stacked in the Unplaced container; "
                                  "re-run with --layout-artifact (or --build) to position them")

    is_artifact = (layout or {}).get("source") == "layout_artifact"

    def lookup(bucket, slot_key):
        # The artifact joins on (bucket, key) exactly; older sources may omit the bucket.
        if is_artifact:
            return by_pair.get((bucket, slot_key))
        return by_pair.get((bucket, slot_key)) or by_key.get(slot_key)

    template_keys = {(b, s["key"]) for b in BUCKETS for s in template[b] if s.get("key")}
    if not is_artifact:  # artifacts are checked (both directions) in _check_artifact_join
        for (bucket, lkey), e in by_pair.items():
            if (bucket, lkey) not in template_keys and lkey not in {k for _, k in template_keys}:
                report["unmapped_layout"].append({"bucket": bucket, "key": lkey})
    for zname in (layout or {}).get("client_zones") or []:
        zname = zname.get("zone")
        if zname not in CLIENT_ZONES:
            report["unmapped_layout"].append({"zone": zname})

    # Panel = the union of every box the plan positions: the background art, every slot, every
    # client-rendered zone and the feature area. Elements that sit outside the art on the mockup
    # (a CTA, timer or fine print below it) must stay inside the panel, or their anchors clamp onto
    # the panel edge and pile up on top of each other.
    bg_slot = next((s for s in template["images"] if s.get("key") == "background_image"), None)
    bg_layout = lookup("images", "background_image") if bg_slot else None
    used_boxes = []
    for bucket in ("images", "buttons", "texts"):
        for slot in template[bucket]:
            found = lookup(bucket, slot.get("key")) if slot.get("key") else None
            if found and found.get("bbox"):
                used_boxes.append(found["bbox"])
    wanted_zones = _wanted_zones(template)
    used_boxes.extend(box for zone, box in zone_boxes.items() if zone in wanted_zones)
    feature_area = (layout or {}).get("feature_area")
    if feature_area and (layout or {}).get("feature_type") not in (None, template.get("featureType") or "standard"):
        feature_area = None  # a mission area must not become a milestone bar (the mismatch is already a warning)
    if feature_area:
        used_boxes.append(feature_area)
    panel_bbox = _union(used_boxes) if used_boxes else {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    report["panel_bbox"] = {k: round(float(v), 4) for k, v in panel_bbox.items()}
    full = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

    text_system = style.get("text_system") if style.get("text_system") in ("legacy", "tmp") else "legacy"
    frame_size = _frame_size(style, options)
    ui = {"text_system": text_system, "font_guid": style.get("font_guid"), "tmp_font_guid": style.get("tmp_font_guid"),
          "frame_size": frame_size, "close_sprite_guid": style.get("close_sprite_guid"), "dimmer_alpha": 0.6,
          "canvas": _plan_canvas(style.get("canvas"), frame_size, report)}

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

    taken_names = set(RESERVED_NODE_NAMES)
    taken_fields = set(RESERVED_FIELDS)

    # Art behind, controls and copy in front (the layout contract's z-order): the Editor builder
    # renders siblings in node order, so every image comes first, then buttons/texts by index.
    def _z_group(bucket, slot):
        if bucket != "images":
            return 1                                  # controls and copy
        role = ((lookup(bucket, slot.get("key")) or {}).get("role") or "") if slot.get("key") else ""
        return 2 if "badge" in ((slot.get("key") or "") + " " + role).lower() else 0   # badges overlay; art sits behind

    ordered = sorted(((b, s) for b in ("images", "buttons", "texts") for s in template[b]),
                     key=lambda pair: (_z_group(*pair), pair[1].get("index") is None, pair[1].get("index") or 0))
    for bucket, slot in ordered:
        skey = slot.get("key")
        if not skey:
            continue
        name = node_name(bucket, skey)
        fld = field_name(bucket, skey)

        # For buttons, also check label name/field
        if bucket == "buttons":
            label_name = name + "Label"
            label_fld = fld + "Label"
            needed_names = {name, label_name}
            needed_fields = {fld, label_fld}
        else:
            needed_names = {name}
            needed_fields = {fld}

        # Auto-increment n if any needed name/field is taken
        if needed_names & taken_names or needed_fields & taken_fields:
            n = 2
            while True:
                new_name = name + str(n)
                new_fld = fld + str(n)
                new_label_name = (name + str(n) + "Label") if bucket == "buttons" else None
                new_label_fld = (fld + str(n) + "Label") if bucket == "buttons" else None
                needed_names = {new_name, new_label_name} if bucket == "buttons" else {new_name}
                needed_fields = {new_fld, new_label_fld} if bucket == "buttons" else {new_fld}
                if not (needed_names & taken_names or needed_fields & taken_fields):
                    name = new_name
                    fld = new_fld
                    report["warnings"].append("slot %s.%s renamed to %s/%s to avoid a clash" % (bucket, skey, name, fld))
                    break
                n += 1

        hidden = bool(slot.get("canBeHidden", False))
        lay = lookup(bucket, skey) or {}
        role = lay.get("role")
        if bucket == "images":
            node = _node(name, "Panel", "image", ["Image"], field=fld, field_type="Image",
                         can_be_hidden=hidden, key=skey, bucket=bucket, role=role)
            if skey == "background_image":
                if lay.get("bbox"):
                    node["anchor_min"], node["anchor_max"] = anchors_from_bbox(lay["bbox"], panel_bbox)
                else:
                    node["anchor_min"], node["anchor_max"] = [0.0, 0.0], [1.0, 1.0]
                node["placed"] = bool(lay.get("bbox"))
                nodes.append(node)
            else:
                place(node, lay.get("bbox"), skey)
            taken_names.add(name)
            taken_fields.add(fld)
        elif bucket == "texts":
            node = _node(name, "Panel", "text", ["Text"], field=fld, field_type="Text",
                         can_be_hidden=hidden, key=skey, bucket=bucket, role=role)
            place(node, lay.get("bbox"), skey)
            taken_names.add(name)
            taken_fields.add(fld)
        else:  # buttons
            sprite = ui["close_sprite_guid"] if re.search(r"close|dismiss", skey, re.I) else None
            node = _node(name, "Panel", "button", ["Image", "Button"], field=fld, field_type="Button",
                         can_be_hidden=hidden, key=skey, bucket=bucket, role=role,
                         click_actions=list(slot.get("clickActionType") or []),
                         custom_cta_names=list(slot.get("customCtaNames") or []), sprite_guid=sprite)
            place(node, lay.get("bbox"), skey)
            label_name = name + "Label"
            label_fld = fld + "Label"
            label = _node(label_name, name, "button_label", ["Text"], field=label_fld, field_type="Text",
                          anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0], key=skey, bucket=bucket)
            (nodes if node["placed"] else unplaced_nodes).append(label)
            taken_names.add(name)
            taken_names.add(label_name)
            taken_fields.add(fld)
            taken_fields.add(label_fld)

    if unplaced_nodes:
        nodes.append(_node("Unplaced", "Panel", "unplaced", ["VerticalLayoutGroup"],
                           anchor_min=[0.05, 0.02], anchor_max=[0.95, 0.30], placed=False))
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
    if (template.get("featureType") or "standard") == "milestone":
        layout_has_elements = bool(layout and layout.get("elements"))
        placed_keys = {n["key"] for n in nodes if n.get("binding") == "button" and n.get("placed") and n.get("key")}
        plan["milestone"] = _milestone_cta(template, nodes, layout_has_elements, placed_keys,
                                           options.get("milestone_cta"), report)
    _add_feature(plan, template, by_key, panel_bbox, feature_area)
    # Set placed=False on every node whose name is in estimated_positions
    estimated_node_names = set(report["estimated_positions"])
    for node in plan["nodes"]:
        if node["name"] in estimated_node_names:
            node["placed"] = False
    resolve_overlaps(plan["nodes"], report, panel_px_height=frame_size[1] * float(panel_bbox.get("h") or 1.0))
    if style.get("base_classes"):
        report["needs_developer"].append(
            "existing popup base class(es) %s detected — the generated view derives from MonoBehaviour and exposes a "
            "Closed event; adapt/wrap it in your popup manager rather than editing the generated class"
            % ", ".join(style["base_classes"]))
    return {"ok": True, "plan": plan, "report": report}


ITEM_BEARING_ACTIONS = ("collect_resource", "billing", "soft_billing", "show_ad", "promise_rewards")
CLIENT_ZONES = ("timer", "price_before_sale", "resource_area", "grand_prize_area")
_ZONE_DEFAULT_ANCHORS = {
    "timer": ([0.3, 0.02], [0.7, 0.07]),
    "price_before_sale": ([0.3, 0.26], [0.7, 0.31]),
    "resource_area": ([0.1, 0.35], [0.9, 0.5]),
    "grand_prize_area": ([0.7, 0.55], [0.95, 0.8]),
    "milestone_scroll": ([0.05, 0.3], [0.95, 0.55]),
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


def _wanted_zones(template):
    """The client-rendered zones this template's prefab gets (timer always; the rest by click actions / feature)."""
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
    return wanted


def _add_client_zones(plan, template, zone_boxes, panel_bbox):
    nodes = plan["nodes"]
    wanted = _wanted_zones(template)
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


_COLLECT_ALL_RE = re.compile(r"(?:^|[\s_-])(collect|claim|get)[\s_-]*all(?:$|[\s_-])", re.I)
_CLOSE_KEY_RE = re.compile(r"close|dismiss", re.I)
_NON_CTA_ACTIONS = {"close", "custom"}   # close the pop-up / open info-rules UI: neither collects a step


def _milestone_cta(template, nodes, layout_has_elements, placed_keys, override, report):
    """Decide how a milestone template's step CTA is wired and find its collect-all slot.

    The collect-all slot is the first button (by index) whose key or name reads "collect/claim/get all"
    as whole segments (so "budget_all" does not count).
    A CTA slot is any other button that offers an action other than close / custom (or no actions and
    is not a close button) and whose layout role is not info_button; when a layout is in play only
    buttons drawn on the tip image count. Exactly one CTA slot
    means the template carries a single main CTA ("single"); otherwise each milestone step carries its
    own ("per_step"). An explicit override wins.
    """
    by_key = {n["key"]: n for n in nodes if n.get("binding") == "button" and n.get("key")}
    buttons = sorted((b for b in template.get("buttons") or [] if b.get("key")),
                     key=lambda b: (b.get("index") is None, b.get("index") if b.get("index") is not None else 0))
    matches = [b for b in buttons if _COLLECT_ALL_RE.search(b["key"]) or _COLLECT_ALL_RE.search(b.get("name") or "")]
    collect_all = None
    if matches:
        slot = matches[0]
        node = by_key.get(slot["key"]) or {}
        fld = node.get("field") or field_name("buttons", slot["key"])
        collect_all = {"key": slot["key"], "button_field": fld, "label_field": fld + "Label",
                       "can_be_hidden": bool(slot.get("canBeHidden", False))}
        if len(matches) > 1:
            report["warnings"].append(
                "milestone template has %d collect-all buttons (%s); using %r"
                % (len(matches), ", ".join(m["key"] for m in matches), slot["key"]))
    cta_slots = []
    for b in buttons:
        if collect_all and b["key"] == collect_all["key"]:
            continue
        if (by_key.get(b["key"]) or {}).get("role") == "info_button":
            continue   # info / rules / preview control, never the step CTA
        actions = set(b.get("clickActionType") or [])
        is_cta = bool(actions - _NON_CTA_ACTIONS) if actions else not _CLOSE_KEY_RE.search(b["key"])
        if not is_cta:
            continue
        if layout_has_elements and b["key"] not in placed_keys:
            continue
        cta_slots.append(b["key"])
    if override in ("per_step", "single"):
        mode, source = override, "override"
    elif len(cta_slots) == 1:
        mode, source = "single", "template_cta_count"
    else:
        mode, source = "per_step", "default"
    single_cta = None
    if mode == "single":
        if len(cta_slots) == 1:
            fld = (by_key.get(cta_slots[0]) or {}).get("field") or field_name("buttons", cta_slots[0])
            single_cta = {"key": cta_slots[0], "button_field": fld, "label_field": fld + "Label"}
        else:
            single_cta = {"key": None, "button_field": "milestoneMainButton", "label_field": "milestoneMainButtonLabel"}
            if override and len(cta_slots) >= 2:
                report["warnings"].append(
                    "--milestone-cta single with %d CTA slots: the step CTA goes onto MilestoneMainButton" % len(cta_slots))
    report["milestone"] = {"cta_mode": mode, "cta_mode_source": source,
                           "collect_all": collect_all["key"] if collect_all else None}
    return {"cta_mode": mode, "cta_mode_source": source, "cta_slots": cta_slots,
            "single_cta": single_cta, "collect_all": collect_all}


def _add_milestone_main_button(plan, template, panel_bbox):
    nodes = plan["nodes"]
    amin, amax = _zone_anchors(plan, "MilestoneMainButton", {}, panel_bbox, "milestone_main")
    nodes.append(_node("MilestoneMainButton", "Panel", "button", ["Image", "Button"], field="milestoneMainButton",
                       field_type="Button", anchor_min=amin, anchor_max=amax, can_be_hidden=True,
                       click_actions=list(((template.get("features") or {}).get("milestone") or {}).get("mainActionTypes") or [])))
    nodes.append(_node("MilestoneMainButtonLabel", "MilestoneMainButton", "button_label", ["Text"],
                       field="milestoneMainButtonLabel", field_type="Text", anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))


def _add_feature(plan, template, by_key, panel_bbox, feature_area=None):
    ftype = template.get("featureType") or "standard"
    nodes = plan["nodes"]
    if ftype == "milestone":
        scroll_box = feature_area or (by_key.get("bar_image") or {}).get("bbox")
        amin, amax = _zone_anchors(plan, "MilestoneScroll", {}, panel_bbox, "milestone_scroll", bbox=scroll_box)
        nodes.append(_node("MilestoneScroll", "Panel", "scroll", ["ScrollRect"], field="milestoneScroll",
                           field_type="ScrollRect", anchor_min=amin, anchor_max=amax, placed=bool(scroll_box)))
        nodes.append(_node("MilestoneViewport", "MilestoneScroll", "viewport", ["Image", "RectMask2D"],
                           anchor_min=[0.0, 0.0], anchor_max=[1.0, 1.0]))
        nodes.append(_node("MilestoneContent", "MilestoneViewport", "scroll_content",
                           ["HorizontalLayoutGroup", "ContentSizeFitter"], field="milestoneContent",
                           field_type="RectTransform", anchor_min=[0.0, 0.0], anchor_max=[0.0, 1.0]))
        scroll_px_h = plan["ui"]["frame_size"][1] * panel_bbox["h"] * (amax[1] - amin[1])
        step_h = max(120, round(scroll_px_h - 16))
        step_w = min(260, max(120, round(step_h * 0.75)))
        ms = plan.get("milestone") or {}
        nodes.append(_node("MilestoneStep", "MilestoneContent", "milestone_step", [], field="milestoneStepTemplate",
                           field_type="KinoaInAppMilestoneStepView", size=[step_w, step_h], inactive=True,
                           step_button=ms.get("cta_mode") == "per_step"))
        if not ((ms.get("single_cta") or {}).get("key")):   # a template slot, when there is one, IS the single CTA
            _add_milestone_main_button(plan, template, panel_bbox)
    elif ftype == "mission":
        amin, amax = _zone_anchors(plan, "MissionList", {}, panel_bbox, "mission_list", bbox=feature_area)
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


# --------------------------------------------------------------------------- de-overlap

_FLOW_BINDINGS = ("text", "button", "zone", "scroll", "unplaced")
_OVERLAP_TOL = 0.002     # anchor units; touching edges are not an overlap
_SPLIT_GAP = 0.004       # gap left between two boxes split apart
_MIN_KEEP = 0.4          # a split box keeps at least this share of its ORIGINAL height/width
_OVERLAY_RATIO = 0.8     # overlap >= this share of the smaller box: an intended overlay (price on a CTA)
_SLOP_RATIO = 0.35       # overlap <= this share of the smaller box: vision-edge slop, safe to split
_SCAN_STEP = 0.005
_MIN_SLOT = 0.02         # a moved box is never shrunk below this height
_UNPLACED_ROW_PX = 88.0  # builder: each Unplaced child is 80 px + 8 px spacing
# Nodes that hold other UI (rows, steps, items): never trimmed against what sits on them.
_CONTAINERS = ("MissionList", "MilestoneScroll", "ResourceArea", "GrandPrizeArea")


def _is_flow(node):
    """Top-level texts, buttons and zones take part; images (art may sit under text) and badges
    (designed to overlay what they annotate) do not."""
    if node.get("parent") != "Panel" or node.get("binding") not in _FLOW_BINDINGS:
        return False
    label = ((node.get("key") or "") + " " + (node.get("role") or "") + " " + node["name"]).lower()
    return "badge" not in label


def _box(node):
    """The node's footprint for collision checks — its anchors."""
    x0, y0 = node["anchor_min"]
    x1, y1 = node["anchor_max"]
    return [x0, y0, x1, y1]


def _set_box(node, box):
    """Store a footprint back as anchors."""
    node["anchor_min"] = [round(_clamp01(box[0]), 4), round(_clamp01(box[1]), 4)]
    node["anchor_max"] = [round(_clamp01(box[2]), 4), round(_clamp01(box[3]), 4)]


def _overlap(a, b):
    """(dx, dy) overlap extents of two [x0, y0, x1, y1] boxes."""
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def _collides(a, b, tol=_OVERLAP_TOL):
    dx, dy = _overlap(a, b)
    return dx > tol and dy > tol


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap_ratio(a, b):
    """Overlap area as a share of the smaller box."""
    dx, dy = _overlap(a, b)
    smaller = min(_area(a), _area(b))
    return (max(0.0, dx) * max(0.0, dy)) / smaller if smaller > 0 else 0.0


def _split(a, b, original):
    """Split two partially overlapping boxes along an axis where neither interval contains the other
    (the one with the smaller overlap), at the midpoint of the overlap band. Returns the new (a, b), or
    None when no such axis exists or a box would keep less than _MIN_KEEP of its `original` extent."""
    dx, dy = _overlap(a, b)
    options = []
    for axis, amount in ((1, dy), (0, dx)):
        nested = (a[axis] <= b[axis] and a[axis + 2] >= b[axis + 2]) or (b[axis] <= a[axis] and b[axis + 2] >= a[axis + 2])
        if not nested:
            options.append((amount, axis))
    if not options:
        return None
    _, axis = min(options)
    lo, hi = (a, b) if (a[axis], a[axis + 2]) <= (b[axis], b[axis + 2]) else (b, a)
    band_lo, band_hi = max(lo[axis], hi[axis]), min(lo[axis + 2], hi[axis + 2])
    mid = (band_lo + band_hi) / 2.0
    new_lo, new_hi = list(lo), list(hi)
    new_lo[axis + 2] = mid - _SPLIT_GAP / 2.0
    new_hi[axis] = mid + _SPLIT_GAP / 2.0
    for old, new in ((lo, new_lo), (hi, new_hi)):
        ref = original[id(old)] if id(old) in original else old
        if (new[axis + 2] - new[axis]) < _MIN_KEEP * (ref[axis + 2] - ref[axis]):
            return None
    return (new_lo, new_hi) if lo is a else (new_hi, new_lo)


def _free_slot(box, settled, min_height=_MIN_SLOT):
    """Nearest vertical position (same x span) where `box` collides with nothing settled; tries the
    full height, then half, then a quarter, never below `min_height`. None when there is no room."""
    height = box[3] - box[1]
    tried = set()
    for h in (height, height / 2.0, height / 4.0):
        h = max(h, min(min_height, height))
        if h in tried or h > 1.0:
            continue
        tried.add(h)
        best, best_dist = None, None
        steps = int(round((1.0 - h) / _SCAN_STEP))
        for i in range(steps + 1):
            y0 = min(1.0 - h, i * _SCAN_STEP)
            cand = [box[0], y0, box[2], y0 + h]
            # a moved box gets true clearance, not "within tolerance" — it must never land on the edge case
            if any(_collides(cand, other, tol=1e-6) for other in settled):
                continue
            dist = abs((y0 + h / 2.0) - (box[1] + box[3]) / 2.0)
            if best_dist is None or dist < best_dist:
                best, best_dist = cand, dist
        if best is not None:
            return best
    return None


def resolve_overlaps(nodes, report, panel_px_height=None):
    """Remove the overlaps between top-level texts, buttons and zones that can be removed safely.

    Placed nodes keep their mockup position. Of two that overlap:
      - an overlay (overlap >= 80 % of the smaller box, or a container holding the other) is kept as
        designed and listed in report.overlays;
      - edge slop (overlap <= 35 % of the smaller box) is split at the middle of the overlap;
      - anything in between is left and reported in report.warnings for the developer.
    Estimated nodes (default anchors, the Unplaced container) move to the nearest free vertical slot.
    Every change goes into report.layout_adjustments; nothing moves silently.
    """
    report.setdefault("layout_adjustments", [])
    report.setdefault("overlays", [])
    flow = [n for n in nodes if _is_flow(n) and n.get("anchor_min") and n.get("anchor_max")]
    fixed = [n for n in flow if n.get("placed")]
    movable = [n for n in flow if not n.get("placed")]
    original_box = {n["name"]: _box(n) for n in flow}
    warned = set()

    def warn(key, text):
        if key not in warned:
            warned.add(key)
            report["warnings"].append(text)

    def record(node, before_anchors, reason, other):
        report["layout_adjustments"].append({"node": node["name"], "reason": reason, "with": other,
                                             "from": before_anchors,
                                             "to": [node["anchor_min"], node["anchor_max"]]})

    def anchors(node):
        return [list(node["anchor_min"]), list(node["anchor_max"])]

    for _ in range(3):                      # placed vs placed
        changed = False
        for i, a in enumerate(fixed):
            for b in fixed[i + 1:]:
                ba, bb = _box(a), _box(b)
                if not _collides(ba, bb):
                    continue
                pair = (a["name"], b["name"])
                ratio = _overlap_ratio(ba, bb)
                a_holds, b_holds = a["name"] in _CONTAINERS, b["name"] in _CONTAINERS
                if a_holds or b_holds:
                    # A container holds UI on purpose — but only what lies mostly inside it — and is never
                    # trimmed (a trimmed bar would drift off its art). Two containers: the smaller is "inner".
                    if a_holds and b_holds:
                        inner = ba if _area(ba) <= _area(bb) else bb
                    else:
                        inner = bb if a_holds else ba
                    dx, dy = _overlap(ba, bb)
                    inside = (max(0.0, dx) * max(0.0, dy)) / _area(inner) if _area(inner) > 0 else 0.0
                    if inside < _OVERLAY_RATIO:
                        warn(pair, "%s and %s overlap on the layout; left as drawn (a container is never trimmed) "
                                   "— check the boxes or adjust them in the prefab" % pair)
                        continue
                    ratio = 1.0
                if ratio >= _OVERLAY_RATIO:
                    if list(pair) not in report["overlays"]:
                        report["overlays"].append(list(pair))
                    continue
                if ratio > _SLOP_RATIO:
                    warn(pair, "%s and %s overlap substantially on the layout; left as drawn — check the boxes "
                               "or adjust them in the prefab" % pair)
                    continue
                split = _split(ba, bb, {id(ba): original_box[a["name"]], id(bb): original_box[b["name"]]})
                if split is None:
                    warn(pair, "%s and %s overlap on the layout and cannot be split without losing most of one; "
                               "adjust them in the prefab" % pair)
                    continue
                before_a, before_b = anchors(a), anchors(b)
                _set_box(a, split[0])
                _set_box(b, split[1])
                record(a, before_a, "split_overlap", b["name"])
                record(b, before_b, "split_overlap", a["name"])
                warn(("split",) + pair, "%s and %s overlapped slightly on the layout; both were trimmed to meet halfway"
                     % pair)
                changed = True
        if not changed:
            break

    if panel_px_height:                     # the Unplaced container is sized to its rows, up or down
        for node in movable:
            if node.get("binding") == "unplaced":
                rows = sum(1 for n in nodes if n.get("parent") == node["name"])
                need = min(1.0, max(_MIN_SLOT, rows * _UNPLACED_ROW_PX / float(panel_px_height) + 0.01))
                if abs((node["anchor_max"][1] - node["anchor_min"][1]) - need) > 1e-4:
                    before_anchors = anchors(node)
                    y0 = min(node["anchor_min"][1], 1.0 - need)
                    node["anchor_min"] = [node["anchor_min"][0], round(y0, 4)]
                    node["anchor_max"] = [node["anchor_max"][0], round(y0 + need, 4)]
                    record(node, before_anchors, "sized_to_rows", None)

    settled = [(n["name"], _box(n)) for n in fixed]
    for node in movable:                    # estimated vs everything settled so far
        before = _box(node)
        blockers = [name for name, box in settled if _collides(before, box)]
        if not blockers:
            settled.append((node["name"], before))
            continue
        min_h = _MIN_SLOT
        if node.get("binding") == "unplaced" and panel_px_height:
            rows = sum(1 for n in nodes if n.get("parent") == node["name"])
            min_h = max(min_h, rows * _UNPLACED_ROW_PX / float(panel_px_height))
        before_anchors = anchors(node)
        target = _free_slot(before, [box for _, box in settled], min_height=min_h)
        if target is None:
            warn(("room", node["name"]), "%s has no free space left in the panel and overlaps %s; place it by hand"
                 % (node["name"], ", ".join(blockers)))
            settled.append((node["name"], before))
            continue
        _set_box(node, target)
        settled.append((node["name"], _box(node)))
        record(node, before_anchors, "moved_to_free_space", ", ".join(blockers))
        report["warnings"].append("%s was moved from its default position to free space (it overlapped %s)"
                                  % (node["name"], ", ".join(blockers)))


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


def _check_bbox(bbox, where):
    """None is allowed (no position); otherwise a dict with numeric (non-bool) x, y, w, h."""
    if bbox is None:
        return
    if not isinstance(bbox, dict):
        raise ValueError("%s bbox must be a dict" % where)
    for key in ("x", "y", "w", "h"):
        val = bbox.get(key)
        if val is None or not isinstance(val, (int, float)) or isinstance(val, bool):
            raise ValueError("%s bbox.%s must be numeric (int/float)" % (where, key))


def layout_from_layout_file(layout):
    if not isinstance(layout, dict):
        raise ValueError("layout must be a dict")
    elements_raw = layout.get("elements")
    if elements_raw is not None and not isinstance(elements_raw, list):
        raise ValueError("layout.elements must be a list")
    zones_raw = layout.get("client_zones")
    if zones_raw is not None and not isinstance(zones_raw, list):
        raise ValueError("layout.client_zones must be a list")

    for e in elements_raw or []:
        if not isinstance(e, dict):
            raise ValueError("layout.elements items must be dicts")
        _check_bbox(e.get("bbox"), "layout element")
    for z in zones_raw or []:
        if not isinstance(z, dict):
            raise ValueError("layout.client_zones items must be dicts")
        _check_bbox(z.get("bbox"), "layout zone")

    elements = [{"bucket": e.get("bucket"), "key": e.get("key"), "role": e.get("key"),
                 "bbox": e.get("bbox"), "observed_text": e.get("observed_text")}
                for e in elements_raw or [] if e.get("key")]
    zones = [{"zone": z.get("zone"), "bbox": z.get("bbox")} for z in zones_raw or []]
    src = layout.get("source_image") or {}
    size = [src["width"], src["height"]] if src.get("width") and src.get("height") else None
    return {"elements": elements, "client_zones": zones, "image_size": size, "source": "layout_file"}


# --------------------------------------------------------------------------- layout artifact (from-image)

ARTIFACT_SCHEMA_MAJOR = "1"
_POSITIONED_BUCKETS = ("images", "buttons", "texts")


def _unit_bbox_problem(bbox):
    """None when `bbox` is a usable normalized box, else why not (mirrors the producer's _bbox_problems)."""
    if not isinstance(bbox, dict):
        return "must be an object with x/y/w/h"
    for field in ("x", "y", "w", "h"):
        v = bbox.get(field)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "bbox.%s must be a number" % field
        if not 0 <= float(v) <= 1:
            return "bbox.%s must be within [0, 1] (normalized)" % field
    if float(bbox["w"]) == 0 or float(bbox["h"]) == 0:
        return "bbox w/h must be non-zero"
    return None


def layout_from_artifact(artifact):
    """`<template_key>.layout.json` from kinoa-inapp-template-from-image -> layout.

    Contract: plugin/skills/kinoa-inapp-template-from-image/references/layout-artifact.md.
    Customs carry no geometry for the planner and are skipped; `bbox: null` / `unplaced`
    elements are kept without a box so the planner stacks them in Unplaced.
    """
    if not isinstance(artifact, dict):
        raise ValueError("layout artifact must be a JSON object")
    if "report" in artifact and "coordinates" not in artifact:
        raise ValueError("this looks like a build_result.json, not a layout artifact; pass it with --build")
    template_key = artifact.get("template_key")
    if not isinstance(template_key, str) or not template_key:
        raise ValueError("layout artifact template_key must be a non-empty string; it is the join key to the template")
    version = str(artifact.get("schema_version") or "")
    if version.split(".")[0] != ARTIFACT_SCHEMA_MAJOR:
        raise ValueError("layout artifact schema_version %r is not supported (expected %s.x)"
                         % (artifact.get("schema_version"), ARTIFACT_SCHEMA_MAJOR))
    coords = artifact.get("coordinates") or {}
    if coords.get("space") != "normalized" or coords.get("origin") != "top-left":
        raise ValueError("layout artifact coordinates must be normalized with a top-left origin, got %r" % (coords,))
    elements_raw = artifact.get("elements")
    if not isinstance(elements_raw, list):
        raise ValueError("layout artifact elements must be a list")
    zones_raw = artifact.get("client_rendered") or []
    if not isinstance(zones_raw, list):
        raise ValueError("layout artifact client_rendered must be a list")
    feature = artifact.get("feature") or {}
    if not isinstance(feature, dict):
        raise ValueError("layout artifact feature must be an object")

    elements, indexes, entries, warnings = [], {}, [], []
    hand_placed = adjusted = 0
    for e in elements_raw:
        if not isinstance(e, dict):
            raise ValueError("layout artifact elements must be objects")
        if e.get("bbox") is not None:
            problem = _unit_bbox_problem(e["bbox"])
            if problem:
                raise ValueError("layout artifact element %s.%s: %s" % (e.get("bucket"), e.get("key"), problem))
        if e.get("bucket") and e.get("key"):
            entries.append((e["bucket"], e["key"]))
        hand_placed += 1 if e.get("hand_placed") is True else 0
        adjusted += 1 if e.get("adjusted") is True else 0
        if e.get("bucket") not in _POSITIONED_BUCKETS or not e.get("key"):
            continue
        bbox = None if e.get("unplaced") else e.get("bbox")
        elements.append({"bucket": e["bucket"], "key": e["key"], "role": e.get("role") or None,
                         "bbox": bbox, "observed_text": e.get("observed_text")})
        idx = e.get("index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            indexes[(e["bucket"], e["key"])] = idx
    zones = []
    for z in zones_raw:
        if not isinstance(z, dict):
            raise ValueError("layout artifact client_rendered items must be objects")
        zbox = z.get("bbox")
        if zbox is not None and _unit_bbox_problem(zbox):
            # Zones are advisory (client-rendered): drop the box, keep the zone, say so.
            warnings.append("layout artifact client_rendered %s bbox ignored: %s; the zone gets default anchors"
                            % (z.get("role"), _unit_bbox_problem(zbox)))
            zbox = None
        zones.append({"zone": z.get("role"), "bbox": zbox})
    if feature.get("area_bbox") is not None:
        problem = _unit_bbox_problem(feature["area_bbox"])
        if problem:
            raise ValueError("layout artifact feature.area_bbox: %s" % problem)

    src = artifact.get("source_image") or {}
    size = [src["width"], src["height"]] if src.get("width") and src.get("height") else None
    return {"elements": elements, "client_zones": zones, "image_size": size,
            "source": "layout_artifact", "template_key": template_key,
            "indexes": indexes, "entries": entries, "warnings": warnings,
            "feature_type": feature.get("type"), "feature_area": feature.get("area_bbox"),
            "sha256": src.get("sha256"), "hand_placed": hand_placed, "adjusted": adjusted}


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
        style = unwrap_style(_read_json(args.style)) if args.style else {}
        layout = None
        if args.layout_artifact:
            layout = layout_from_artifact(_read_json(args.layout_artifact))
        elif args.build:
            layout = layout_from_build(_read_json(args.build), _read_json(args.confirmed) if args.confirmed else None)
        elif args.layout:
            layout = layout_from_layout_file(_read_json(args.layout))
        image_size = _parse_size(args.image_size) or (layout or {}).get("image_size")
        result = plan_prefab(template, layout, style, {"image_size": image_size, "out_dir": args.out_dir,
                                                       "milestone_cta": args.milestone_cta})
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        _emit({"ok": False, "error": "unreadable_input", "detail": str(exc)})
        return 2
    if not result["ok"]:
        _emit(result)
        return 2
    out = args.out or ("%s.inapp-plan.json" % result["plan"]["template"]["key"])
    try:
        out_dir = os.path.dirname(out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(result["plan"], fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        _emit({"ok": False, "error": "write_failed", "detail": str(exc)})
        return 2
    _emit({"ok": True, "plan_path": out, "plan": result["plan"], "report": result["report"]}, out=None)
    return 0


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


def render_feature_hooks(options):
    body = _AUTOGEN % "game-supplied delegate for feature (milestone) button actions. Fill the TODO line from YOUR game code; regenerated only with --force-shared."
    body += """using System;
using System.Threading.Tasks;
using Kinoa.Data.Messaging.InApp;
using Kinoa.Data.Messaging.InApp.Templates.Custom;
using UnityEngine;

namespace Kinoa.InApps
{
    /// <summary>
    ///     Delegates the generated feature views (milestones) call for actions the game already owns.
    ///     Kept apart from KinoaInAppHooks so projects generated by an earlier release keep compiling unchanged.
    /// </summary>
    public static class KinoaInAppFeatureHooks
    {
        /// <summary>
        ///     Runs a milestone button's paid / ad / link action (billing, soft_billing, show_ad, deep_link, web_link, ...)
        ///     with the game's own IAP / ads / router; returns true once it completed so the view may collect the step.
        ///     Never grant the reward here - the view collects through Kinoa.
        /// </summary>
"""
    body += _hook_line("Func<InAppMessage, InAppCustomButton, Task<bool>>", "RunButtonAction", options.get("feature_action_runner"),
                       "route button.ClickConfig through your game's click handler and return true when it succeeded, e.g. KinoaInAppFeatureHooks.RunButtonAction = async (message, button) => await MyClickHandler.RunAsync(message, button);")
    body += """
        internal static void WarnMissing(string hook) =>
            Debug.LogWarning($"[KinoaInApp] {hook} is not assigned — see TODO(kinoa-prefab) in KinoaInAppFeatureHooks.cs");
    }
}
"""
    return body


def render_milestone_step_view(text_system):
    return (_AUTOGEN % "shared milestone step view (one row of the milestone ladder). Regenerated only with --force-shared.") + """using Kinoa.Data.Enum;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;
""" + _text_alias(text_system) + """

namespace Kinoa.InApps
{
    public class KinoaInAppMilestoneStepView : MonoBehaviour
    {
        [SerializeField] private KinoaText score;
        [SerializeField] private Image rewardIcon;
        [SerializeField] private KinoaText rewardAmount;
        [SerializeField] private Image progress;
        [SerializeField] private GameObject lockedMark;
        [SerializeField] private GameObject collectedMark;
        [SerializeField] private Button collectButton;
        [SerializeField] private KinoaText collectLabel;

        public void SetScore(string text)
        {
            if (score != null) score.text = text ?? string.Empty;
        }

        public void SetReward(Sprite icon, string amount)
        {
            if (rewardIcon != null)
            {
                rewardIcon.sprite = icon;
                rewardIcon.enabled = icon != null;
            }

            if (rewardAmount != null)
            {
                rewardAmount.text = amount ?? string.Empty;
                rewardAmount.gameObject.SetActive(!string.IsNullOrEmpty(amount));
            }
        }

        public void SetProgress(float amount)
        {
            if (progress != null) progress.fillAmount = Mathf.Clamp01(amount);
        }

        public void SetStatus(InAppMilestoneStatus status)
        {
            if (lockedMark != null) lockedMark.SetActive(status == InAppMilestoneStatus.Closed || status == InAppMilestoneStatus.Unknown);
            if (collectedMark != null) collectedMark.SetActive(status == InAppMilestoneStatus.Collected);
        }

        public void SetCollect(bool visible, bool interactable, string label, UnityAction onClick)
        {
            if (collectButton == null) return;
            collectButton.gameObject.SetActive(visible);
            collectButton.onClick.RemoveAllListeners();
            collectButton.interactable = interactable;
            if (onClick != null) collectButton.onClick.AddListener(onClick);
            if (collectLabel != null) collectLabel.text = label ?? string.Empty;
        }
    }
}
"""


BUILDER_CS = (_AUTOGEN % "generic plan -> prefab builder (Editor only). Tool-owned: rewritten by every generate run.") + r"""using System;
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
        [Serializable] public class PlanUi { public string text_system; public string font_guid; public string tmp_font_guid; public float[] frame_size; public string close_sprite_guid; public float dimmer_alpha; public PlanCanvas canvas; }
        [Serializable] public class PlanCanvas { public string render_mode; public bool override_sorting; public int sorting_order; public string scale_mode; public float[] reference_resolution; public float match; public string source; }
        [Serializable] public class PlanView { public string class_name; public string ns; }
        [Serializable] public class PlanPaths { public string out_dir; public string prefab_path; public string view_path; public string plan_path; }
        [Serializable] public class PlanNode
        {
            public string name; public string parent; public string binding; public string[] components;
            public string field; public string field_type; public float[] anchor_min; public float[] anchor_max; public float[] size;
            public bool placed; public bool can_be_hidden; public bool inactive; public string key; public string bucket; public string sprite_guid;
            public bool step_button;
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
                AddCanvas(root, plan.ui);
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
                WireScrollRects(plan.nodes, byName);

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

        /// <summary>
        ///     Canvas + CanvasScaler + GraphicRaycaster on the prefab root, from plan.ui.canvas (copied from a
        ///     reference pop-up, or pop-up defaults). They depend on the game's UI setup: align them, or remove
        ///     them when the prefab is parented under an existing pop-up canvas (a nested canvas ignores its scaler).
        /// </summary>
        private static void AddCanvas(GameObject root, PlanUi ui)
        {
            var cfg = ui?.canvas;
            if (cfg != null && string.IsNullOrEmpty(cfg.source)) cfg = null;   // plan written before canvas settings existed

            var canvas = root.AddComponent<Canvas>();
            canvas.renderMode = cfg?.render_mode == "camera" ? RenderMode.ScreenSpaceCamera
                : cfg?.render_mode == "world" ? RenderMode.WorldSpace
                : RenderMode.ScreenSpaceOverlay;
            canvas.overrideSorting = cfg == null || cfg.override_sorting;
            canvas.sortingOrder = cfg != null ? cfg.sorting_order : 100;

            var scaler = root.AddComponent<CanvasScaler>();
            if (cfg != null && cfg.scale_mode == "constant_pixel_size")
            {
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPixelSize;
            }
            else if (cfg != null && cfg.scale_mode == "constant_physical_size")
            {
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPhysicalSize;
            }
            else
            {
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                var resolution = cfg?.reference_resolution != null && cfg.reference_resolution.Length == 2
                    ? cfg.reference_resolution : ui?.frame_size;
                if (resolution != null && resolution.Length == 2)
                    scaler.referenceResolution = new Vector2(resolution[0], resolution[1]);
                scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
                scaler.matchWidthOrHeight = cfg != null ? cfg.match : 0.5f;
            }

            root.AddComponent<GraphicRaycaster>();
        }

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
                    if (!go.TryGetComponent<Image>(out var image)) image = go.AddComponent<Image>();
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
                case "ScrollRect":
                {
                    var sr = go.AddComponent<ScrollRect>();
                    sr.horizontal = true; sr.vertical = false;
                    sr.movementType = ScrollRect.MovementType.Clamped;
                    sr.inertia = true;
                    break;
                }
                case "RectMask2D":
                    go.AddComponent<RectMask2D>();
                    break;
                case "ContentSizeFitter":
                {
                    var fitter = go.AddComponent<ContentSizeFitter>();
                    fitter.horizontalFit = ContentSizeFitter.FitMode.PreferredSize;
                    fitter.verticalFit = ContentSizeFitter.FitMode.Unconstrained;
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
            var font = LoadByGuid<Font>(ui?.font_guid);
            text.font = font != null ? font : BuiltinFont();
            text.alignment = TextAnchor.MiddleCenter;
            text.resizeTextForBestFit = true; text.resizeTextMinSize = 10; text.resizeTextMaxSize = 120;
            text.color = Color.white; text.supportRichText = true;
            text.horizontalOverflow = HorizontalWrapMode.Wrap; text.verticalOverflow = VerticalWrapMode.Truncate;
            return text;
        }

        private static Font BuiltinFont()
        {
#if UNITY_2022_2_OR_NEWER
            return Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
#else
            return Resources.GetBuiltinResource<Font>("Arial.ttf");
#endif
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
                case "viewport":
                {
                    var image = go.GetComponent<Image>();
                    image.color = new Color(1f, 1f, 1f, 0f);   // invisible, but a raycast target so the scroll can be dragged
                    image.raycastTarget = true;
                    break;
                }
                case "scroll_content":
                {
                    go.GetComponent<RectTransform>().pivot = new Vector2(0f, 0.5f);
                    // the generic "HorizontalLayoutGroup" component case already added the group: override it, never add a second one
                    var group = go.GetComponent<HorizontalLayoutGroup>();
                    if (group != null)
                    {
                        group.spacing = 12f; group.padding = new RectOffset(8, 8, 8, 8);
                        group.childControlWidth = true; group.childControlHeight = true;
                        group.childForceExpandWidth = false; group.childForceExpandHeight = true;
                    }
                    break;
                }
                case "milestone_step":
                    BuildMilestoneStep(go, ui, node);
                    break;
                case "image":
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
            if (node.parent == "Unplaced")
            {
                var rt = go.GetComponent<RectTransform>();
                rt.anchorMin = new Vector2(0f, 1f);
                rt.anchorMax = new Vector2(1f, 1f);
                rt.pivot = new Vector2(0.5f, 1f);
                rt.sizeDelta = new Vector2(0f, 80f);
                go.AddComponent<LayoutElement>().preferredHeight = 80f;
            }
        }

        private static void BuildItemTemplate(GameObject go, PlanUi ui)
        {
            if (!go.TryGetComponent<Image>(out var background)) background = go.AddComponent<Image>();
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

        /// <summary>
        ///     One milestone step: score, reward icon + amount, progress, locked/collected marks and (per-step CTA only)
        ///     a collect button. Assigns every serialized field of the generated KinoaInAppMilestoneStepView.
        /// </summary>
        private static void BuildMilestoneStep(GameObject go, PlanUi ui, PlanNode node)
        {
            if (!go.TryGetComponent<Image>(out var background)) background = go.AddComponent<Image>();
            background.color = new Color(1f, 1f, 1f, 0.15f);
            background.raycastTarget = true;
            var layout = go.AddComponent<LayoutElement>();
            if (node.size != null && node.size.Length == 2) layout.preferredWidth = node.size[0];
            layout.flexibleHeight = 1f;

            var score = AddText(Child(go, "Score", new Vector2(0.05f, 0.80f), new Vector2(0.95f, 0.98f)), ui);
            var rewardIcon = Child(go, "RewardIcon", new Vector2(0.20f, 0.42f), new Vector2(0.80f, 0.78f)).AddComponent<Image>();
            rewardIcon.preserveAspect = true; rewardIcon.raycastTarget = false;
            var rewardAmount = AddText(Child(go, "RewardAmount", new Vector2(0.05f, 0.30f), new Vector2(0.95f, 0.42f)), ui);
            var progress = Child(go, "Progress", new Vector2(0.05f, 0.25f), new Vector2(0.95f, 0.29f)).AddComponent<Image>();
            progress.type = Image.Type.Filled; progress.fillMethod = Image.FillMethod.Horizontal;
            progress.fillAmount = 0f; progress.raycastTarget = false;
            foreach (var c in new[] { score, rewardAmount }) { var g = c.GetComponent<Graphic>(); if (g != null) g.raycastTarget = false; }

            Button collectButton = null;
            Component collectLabel = null;
            if (node.step_button)
            {
                var buttonGo = Child(go, "CollectButton", new Vector2(0.10f, 0.03f), new Vector2(0.90f, 0.22f));
                var buttonImage = buttonGo.AddComponent<Image>();
                collectButton = buttonGo.AddComponent<Button>();
                collectButton.targetGraphic = buttonImage;
                collectLabel = AddText(Child(buttonGo, "CollectLabel", Vector2.zero, Vector2.one), ui);
                var labelGraphic = collectLabel.GetComponent<Graphic>();
                if (labelGraphic != null) labelGraphic.raycastTarget = false;
            }

            var lockedGo = Child(go, "LockedMark", new Vector2(0f, 0f), new Vector2(1f, 1f));
            var lockedImage = lockedGo.AddComponent<Image>();
            lockedImage.color = new Color(0f, 0f, 0f, 0.45f); lockedImage.raycastTarget = false;
            lockedGo.SetActive(false);
            var collectedGo = Child(go, "CollectedMark", new Vector2(0.60f, 0.75f), new Vector2(0.95f, 0.98f));
            var collectedImage = collectedGo.AddComponent<Image>();
            collectedImage.color = new Color(0.25f, 0.8f, 0.35f, 0.9f); collectedImage.raycastTarget = false;
            collectedGo.SetActive(false);

            var step = go.AddComponent<KinoaInAppMilestoneStepView>();
            var so = new SerializedObject(step);
            SetRef(so, "score", score); SetRef(so, "rewardIcon", rewardIcon); SetRef(so, "rewardAmount", rewardAmount);
            SetRef(so, "progress", progress); SetRef(so, "lockedMark", lockedGo); SetRef(so, "collectedMark", collectedGo);
            if (node.step_button) { SetRef(so, "collectButton", collectButton); SetRef(so, "collectLabel", collectLabel); }
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>Points each ScrollRect at its viewport child and the content grandchild (found by plan parent names).</summary>
        private static void WireScrollRects(PlanNode[] nodes, Dictionary<string, GameObject> built)
        {
            foreach (var scroll in nodes.Where(n => n.binding == "scroll"))
            {
                if (!built.TryGetValue(scroll.name, out var scrollGo) || !scrollGo.TryGetComponent<ScrollRect>(out var rect)) continue;
                var viewport = nodes.FirstOrDefault(n => n.binding == "viewport" && n.parent == scroll.name);
                if (viewport == null || !built.TryGetValue(viewport.name, out var viewportGo)) continue;
                rect.viewport = viewportGo.GetComponent<RectTransform>();
                var content = nodes.FirstOrDefault(n => n.binding == "scroll_content" && n.parent == viewport.name);
                if (content != null && built.TryGetValue(content.name, out var contentGo)) rect.content = contentGo.GetComponent<RectTransform>();
            }
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
                case "ScrollRect": return go.GetComponent<ScrollRect>();
                case "KinoaInAppMilestoneStepView": return go.GetComponent<KinoaInAppMilestoneStepView>();
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


class PlanOutdatedError(ValueError):
    """A milestone plan written before the scroll ladder: there is no view to generate for it."""


def generate_code(plan, options=None):
    options = options or {}
    out_dir = plan["paths"]["out_dir"].rstrip("/")
    text_system = plan["ui"]["text_system"]
    files = {
        "%s/Shared/KinoaInAppHooks.cs" % out_dir: render_hooks(options),
        "%s/Shared/KinoaInAppItemView.cs" % out_dir: render_item_view(text_system),
        "%s/Shared/KinoaInAppFeatureHooks.cs" % out_dir: render_feature_hooks(options),
        "%s/Shared/KinoaInAppMilestoneStepView.cs" % out_dir: render_milestone_step_view(text_system),
        "%s/Editor/KinoaInAppPrefabBuilder.cs" % out_dir: BUILDER_CS,
    }
    files[plan["paths"]["view_path"]] = render_view(plan, options)
    files[plan["paths"]["plan_path"]] = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    return {"files": files, "snippets": render_snippets(plan, options), "report": {"text_system": text_system}}


_CS_FIELD_TYPE = {"Text": "KinoaText"}


def _cs_type(field_type):
    return _CS_FIELD_TYPE.get(field_type, field_type)


def _fields_block(plan):
    groups = [("Frame", ("dimmer", "panel")), ("Images", ("image",)), ("Texts", ("text",)),
              ("Buttons", ("button", "button_label")), ("Client-rendered zones", ("zone", "strike", "item_template", "fill"))]
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

    # Controller ruling R6: boolean customs may target SLOT nodes (Image/Text/Button) or zone roots (GameObject)
    # Slot-target toggles can only HIDE (not re-show); zone-root toggles can hide or show.
    node_by_name = {n["name"]: n for n in plan["nodes"]}
    toggles = []
    for c in plan["customs"]:
        if not c.get("target_field"):
            continue
        target_node = node_by_name.get(c["target_node"])
        if target_node and target_node["field_type"] != "GameObject":
            # For non-GameObject fields (Text, Image, Button, etc.), use ApplySlotToggle (can only hide)
            toggles.append('            ApplySlotToggle("%s", %s != null ? %s.gameObject : null);' % (c["key"], c["target_field"], c["target_field"]))
        else:
            # For GameObject fields (zone roots), use ApplyToggle (can show or hide)
            toggles.append('            ApplyToggle("%s", %s);' % (c["key"], c["target_field"]))

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
        private bool _closed;

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
            if (_closed) return;
            _closed = true;
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

        private void ApplySlotToggle(string customKey, GameObject target)
        {
            if (target == null) return;
            // A slot toggle can only hide: content binding already hid empty slots, and showing one again would render an empty Image or a dead Button.
            if (TryGetCustom<bool>(customKey, out var on) && !on) target.SetActive(false);
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
            var left = TimeSpan.FromSeconds(remaining);
            var clock = left.ToString(@"hh\\:mm\\:ss");
            timerText.text = left.Days > 0 ? $"{left.Days}d {clock}" : clock;
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

_MILESTONE_HEAD_CS = """
        // ------------------------------------------------------------------ milestones feature

        private bool _collecting;
        private int _pendingFocusIndex = -1;   // a focus requested while the view was inactive (Bind before Show)
        private int _pendingFocusCount;

        private void BindFeature()
        {
            var feature = Data.Feature as InAppMilestonesFeature;
            if (milestoneScroll != null) milestoneScroll.gameObject.SetActive(feature != null);
            if (feature == null) return;
            var steps = feature.Steps ?? new List<InAppMilestoneStep>();
            var reached = new List<uint>();   // CollectMilestonesAsync takes 0-based step indexes
            for (var i = 0; i < steps.Count; i++)
                if (steps[i] != null && steps[i].Status == InAppMilestoneStatus.Reached) reached.Add((uint)i);
            if (milestoneStepTemplate != null)
            {
                // ClearSpawned's Destroy only lands at end of frame: hide the old steps now so the layout FocusStep measures holds only the new ones.
                if (milestoneStepTemplate.transform.parent != null)
                    foreach (Transform child in milestoneStepTemplate.transform.parent)
                        if (child != milestoneStepTemplate.transform) child.gameObject.SetActive(false);
                var previous = 0L;
                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    if (step == null) continue;
                    var index = (uint)i;
                    var item = SpawnStep(milestoneStepTemplate);
                    item.SetScore(step.Score.ToString());
                    var resources = step.Button?.Resources;
                    var hasReward = resources != null && resources.Count > 0;
                    item.SetReward(hasReward ? ResolveIcon(resources[0].ResourceKey) : null,
                        hasReward ? (resources.Count == 1 ? resources[0].Amount.ToString() : $"x{resources.Count}") : null);
                    item.SetProgress(StepProgress(feature.Progress, previous, step.Score));
                    item.SetStatus(step.Status);
%(step_collect)s
                    previous = step.Score;
                }
            }
%(after_steps)s%(collect_all)s
            var focus = steps.FindIndex(s => s != null && s.Status == InAppMilestoneStatus.Reached);
            if (focus < 0) focus = steps.FindIndex(s => s != null && s.Status == InAppMilestoneStatus.Closed);
            if (focus < 0) focus = steps.Count - 1;
            FocusStep(focus, steps.Count);
            BindGrandPrize(steps);
        }
"""

_MILESTONE_PER_STEP_COLLECT_CS = """                    item.SetCollect(step.Status != InAppMilestoneStatus.Collected, step.Status == InAppMilestoneStatus.Reached, StepLabel(step.Button),
                        () => OnFeatureButtonClicked("milestone_step_" + index, step.Button, new List<uint> { index }));"""

_MILESTONE_PER_STEP_AFTER_CS = """            ApplyFeatureButton(milestoneMainButton, milestoneMainButtonLabel, feature.ActiveProgressButton, "milestone_main",
                FeatureIndexes(feature.ActiveProgressButton, steps, reached), canBeHidden: true);
"""

_MILESTONE_SINGLE_COLLECT_CS = """                    item.SetCollect(false, false, null, null);   // single CTA: the ready step's button goes onto %(button)s"""

_MILESTONE_SINGLE_AFTER_CS = """            BindSingleCta(feature, steps, reached);
"""

_MILESTONE_SINGLE_CTA_CS = """
        private void BindSingleCta(InAppMilestonesFeature feature, List<InAppMilestoneStep> steps, List<uint> reached)
        {
            if (reached.Count > 0)
                ApplyFeatureButton(%(button)s, %(label)s, steps[(int)reached[0]].Button, "milestone_step_" + reached[0], new List<uint> { reached[0] }, canBeHidden: false);
            else if (feature.ActiveProgressButton != null)
                ApplyFeatureButton(%(button)s, %(label)s, feature.ActiveProgressButton, "milestone_main", new List<uint>(), canBeHidden: false);
%(idle)s        }
"""

_MILESTONE_COLLECT_ALL_CS = """            InAppCustomButton collectAllSlot = null;
            Data.Buttons?.TryGetValue("%(key)s", out collectAllSlot);
            var collectAllIndexes = FeatureIndexes(collectAllSlot, steps, reached);
            ApplyFeatureButton(%(button)s, %(label)s, collectAllSlot, "%(key)s", collectAllIndexes, canBeHidden: %(hidden)s);
            if (%(button)s != null) %(button)s.interactable = collectAllSlot != null && collectAllIndexes.Count > 0;
"""

_MILESTONE_TAIL_CS = """
        private KinoaInAppMilestoneStepView SpawnStep(KinoaInAppMilestoneStepView template)
        {
            var item = Instantiate(template, template.transform.parent);
            item.gameObject.SetActive(true);
            _spawned.Add(item.gameObject);
            return item;
        }

        private static float StepProgress(decimal progress, long previous, long score)
        {
            if (score > previous) return Mathf.Clamp01((float)((progress - previous) / (score - previous)));
            return progress >= score ? 1f : 0f;
        }

        private string StepLabel(InAppCustomButton button)
        {
            var label = button == null ? null : ResolveButtonLabel(button);
            return string.IsNullOrEmpty(label) ? "Collect" : label;
        }

        private void FocusStep(int index, int count)
        {
            _pendingFocusIndex = -1;   // the latest Bind wins over an older pending focus
            if (milestoneScroll == null || count == 0) return;
            if (!isActiveAndEnabled)
            {
                // an inactive hierarchy is not laid out - apply the focus once the view is shown (OnEnable)
                _pendingFocusIndex = index;
                _pendingFocusCount = count;
                return;
            }
            Canvas.ForceUpdateCanvases();
            if (milestoneContent != null) LayoutRebuilder.ForceRebuildLayoutImmediate(milestoneContent);
            milestoneScroll.horizontalNormalizedPosition = count > 1 ? (float)index / (count - 1) : 0f;
        }

        private void OnEnable()
        {
            if (_pendingFocusIndex < 0) return;
            StartCoroutine(ApplyPendingFocusNextFrame());
        }

        private System.Collections.IEnumerator ApplyPendingFocusNextFrame()
        {
            yield return null;   // let the just-activated layout group and content size fitter settle first
            if (_pendingFocusIndex >= 0) FocusStep(_pendingFocusIndex, _pendingFocusCount);
        }

        private void ApplyFeatureButton(Button button, KinoaText label, InAppCustomButton slot, string clickKey, List<uint> indexes, bool canBeHidden)
        {
            ApplyButtonSlot(button, label, clickKey, slot, canBeHidden);
            if (button == null) return;
            if (slot == null)
            {
                if (!canBeHidden)
                {
                    button.onClick.RemoveAllListeners();   // a kept-visible button with no slot this bind: drop the old bind's action
                    button.interactable = false;
                }
                return;
            }
            button.interactable = true;
            if (indexes.Count > 0 && label != null && string.IsNullOrEmpty(label.text)) label.text = StepLabel(slot);   // a collecting CTA never shows blank
            button.onClick.RemoveAllListeners();
            button.onClick.AddListener(() => OnFeatureButtonClicked(clickKey, slot, indexes));
        }

        private void OnFeatureButtonClicked(string clickKey, InAppCustomButton slot, List<uint> indexes)
        {
            if (_collecting) return;
            Kinoa.GameEvents.SendInAppClickEvent(new InAppClickEventData(Message));
            ButtonClicked?.Invoke(this, clickKey, slot?.ClickConfig);
            var config = slot?.ClickConfig;
            if (config is InAppCloseClickConfiguration)
            {
                Close();
                return;
            }
            if (IsFreeClick(config))
            {
                if (indexes.Count > 0) _ = CollectStepsAsync(indexes);
                return;
            }
            _ = RunActionThenCollectAsync(slot, indexes);
        }

        private static bool IsFreeClick(InAppClickConfiguration config) =>
            config == null || config is InAppCollectResourceClickConfiguration || config is InAppPromiseRewardsClickConfiguration;

        // The steps a feature button (main / collect-all) collects depend on its own click config. A free one takes only the
        // reached steps whose own CTA is free too - a paid / ad / link step still needs its own action. A paid / ad / link one
        // takes every reached step: its action runs first (RunButtonAction) and gates them all. Close never collects.
        private static List<uint> FeatureIndexes(InAppCustomButton slot, List<InAppMilestoneStep> steps, List<uint> reached)
        {
            if (!IsFreeClick(slot?.ClickConfig)) return reached;
            var free = new List<uint>();
            foreach (var index in reached)
                if (IsFreeClick(steps[(int)index]?.Button?.ClickConfig)) free.Add(index);
            return free;
        }

        // Paid / ad / link actions (billing, soft_billing, show_ad, deep_link, web_link, ...) run through the game's own
        // handler; the step is collected only once that handler reports success. No handler - no collect.
        private async Task RunActionThenCollectAsync(InAppCustomButton slot, List<uint> indexes)
        {
            if (KinoaInAppFeatureHooks.RunButtonAction == null)
            {
                KinoaInAppFeatureHooks.WarnMissing(nameof(KinoaInAppFeatureHooks.RunButtonAction));
                return;
            }
            bool done;
            _collecting = true;   // one action at a time: a double tap must not start a second purchase
            try { done = await KinoaInAppFeatureHooks.RunButtonAction(Message, slot); }
            catch (Exception e)
            {
                Debug.LogWarning($"[{GetType().Name}] milestone button action failed: {e.Message}");
                return;
            }
            finally { _collecting = false; }
            if (this == null) return;
            if (done && indexes.Count > 0) await CollectStepsAsync(indexes);
        }

        private async Task CollectStepsAsync(List<uint> indexes)
        {
            _collecting = true;
            try
            {
                var steps = (Data.Feature as InAppMilestonesFeature)?.Steps;   // read before the call: a rebind replaces Data
                var response = await Kinoa.Messaging.CollectMilestonesAsync(Message, indexes);
                if (this == null) return;
                if (response == null || !response.IsSuccessful() || response.Data == null)
                {
                    Debug.LogWarning($"[{GetType().Name}] milestone collect failed for steps {string.Join(",", indexes)}: {response?.Error?.Message ?? "no response"}");
                    Bind(Message);
                    return;
                }
                if (response.Data.Collected != null)
                {
                    foreach (var index in response.Data.Collected)
                    {
                        if (steps == null || index >= steps.Count || steps[(int)index]?.Button == null) continue;
                        // %(todo)s apply steps[(int)index].Button.Resources to the player's economy here (same place as KinoaUiService.GrantRewards).
                    }
                }
                if (response.Data.InApp != null)
                {
                    Bind(response.Data.InApp);   // the instance was reset - the server sent a fresh message
                    return;
                }
                if (response.Data.Collected != null && response.Data.Collected.Count > 0)
                    Message.SetMilestonesStatusAsCollected(response.Data.Collected);
                Bind(Message);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[{GetType().Name}] milestone collect failed for steps {string.Join(",", indexes)}: {e.Message}");
                if (this != null) Bind(Message);
            }
            finally
            {
                _collecting = false;
            }
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
"""


def render_milestone_methods(plan):
    """The milestone section of the view: a horizontal ladder of steps, one CTA mode, optional collect-all."""
    ms = plan.get("milestone")
    if not ms or not any(n["name"] == "MilestoneScroll" for n in plan["nodes"]):
        raise PlanOutdatedError("the milestone plan has no milestone block / MilestoneScroll node")
    single = ms.get("cta_mode") == "single" and ms.get("single_cta")
    extra = ""
    if single:
        cta = ms["single_cta"]
        step_collect = _MILESTONE_SINGLE_COLLECT_CS % {"button": cta["button_field"]}
        after_steps = _MILESTONE_SINGLE_AFTER_CS
        if cta.get("key"):
            idle = "            // otherwise the template slot keeps the binding BindButtons gave it\n"
        else:
            idle = "            else if (%(b)s != null)\n                %(b)s.gameObject.SetActive(false);\n" % {"b": cta["button_field"]}
        extra = _MILESTONE_SINGLE_CTA_CS % {"button": cta["button_field"], "label": cta["label_field"], "idle": idle}
    else:
        step_collect = _MILESTONE_PER_STEP_COLLECT_CS
        after_steps = _MILESTONE_PER_STEP_AFTER_CS
    collect_all = ""
    ca = ms.get("collect_all")
    if ca:
        collect_all = _MILESTONE_COLLECT_ALL_CS % {"key": ca["key"], "button": ca["button_field"], "label": ca["label_field"],
                                                   "hidden": "true" if ca.get("can_be_hidden") else "false"}
    head = _MILESTONE_HEAD_CS % {"step_collect": step_collect, "after_steps": after_steps, "collect_all": collect_all}
    return head + extra + _MILESTONE_TAIL_CS % {"todo": TODO}

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
                    var captured = mission;
                    row.SetButton(mission.Status == InAppMissionStatus.Reached, () => _ = CollectMissionAsync(row, set.SetNumber, captured));
                }
            }
%(bar)s        }

        private async Task CollectMissionAsync(KinoaInAppItemView row, int setNumber, InAppMission mission)
        {
            row.SetButton(false, null);
            var response = await Kinoa.Messaging.CollectMissionsProgressAsync(Message, setNumber, new List<int> { mission.RowNumber });
            if (this == null) return;
            if (response == null || !response.IsSuccessful() || response.Data == null)
            {
                Debug.LogWarning($"[{GetType().Name}] mission row {mission.RowNumber} collect failed: {response?.Error?.Message ?? "no response"}");
                row.SetButton(true, () => _ = CollectMissionAsync(row, setNumber, mission));
                return;
            }
            // %(todo)s apply mission.ProcessedResources to the player's economy here (same place as KinoaUiService.GrantRewards).
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
        return render_milestone_methods(plan)
    if ftype == "mission":
        has_bar = any(n["name"] == "MissionBar" for n in plan["nodes"])
        return _MISSION_CS % {"todo": TODO, "bar": _MISSION_BAR_CS if has_bar else ""}
    return ""


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


_HOOK_METHOD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def cmd_generate(args):
    try:
        plan = _read_json(args.plan)
    except (OSError, json.JSONDecodeError) as exc:
        _emit({"ok": False, "error": "unreadable_input", "detail": str(exc)})
        return 2
    options = {"facade": args.facade, "facade_namespace": args.facade_namespace, "image_loader": args.image_loader,
               "price_resolver": args.price_resolver, "resource_icon_resolver": args.resource_icon_resolver,
               "feature_action_runner": args.feature_action_runner}
    for flag, value in (("--image-loader", args.image_loader), ("--price-resolver", args.price_resolver),
                        ("--resource-icon-resolver", args.resource_icon_resolver),
                        ("--feature-action-runner", args.feature_action_runner)):
        if value is not None and not _HOOK_METHOD_RE.fullmatch(value):
            _emit({"ok": False, "error": "invalid_hook_method", "flag": flag, "value": value})
            return 2
    plan["view"]["facade"] = args.facade
    plan["view"]["facade_namespace"] = args.facade_namespace if args.facade == "present" else None
    try:
        out = generate_code(plan, options)
    except PlanOutdatedError as exc:
        _emit({"ok": False, "error": "milestone_plan_outdated",
               "detail": "%s was written before the milestone scroll ladder; re-run `plan` for this template" % args.plan,
               "reason": str(exc)})
        return 2
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

    # Fix 1: Compute exact set of user-owned shared files (only these can be skipped)
    out_dir = plan["paths"]["out_dir"].rstrip("/")
    user_owned = {out_dir + "/Shared/KinoaInAppHooks.cs", out_dir + "/Shared/KinoaInAppItemView.cs",
                  out_dir + "/Shared/KinoaInAppFeatureHooks.cs", out_dir + "/Shared/KinoaInAppMilestoneStepView.cs"}
    builder_path = out_dir + "/Editor/KinoaInAppPrefabBuilder.cs"

    # Check text-system mismatch only for user-owned files
    expected_alias = "TMPro.TMP_Text" if plan["ui"]["text_system"] == "tmp" else "UnityEngine.UI.Text"
    for p in user_owned:
        existing = _existing_alias(os.path.join(root, p))
        if existing and existing != expected_alias and not args.force_shared:
            _emit({"ok": False, "error": "shared_text_system_mismatch", "path": p, "existing": existing,
                   "expected": expected_alias, "override": "--force-shared"})
            return 2

    written, skipped = [], []
    # Track which hook options were supplied for warning collection
    supplied_hooks = {}
    if args.image_loader:
        supplied_hooks["image_loader"] = "--image-loader"
    if args.price_resolver:
        supplied_hooks["price_resolver"] = "--price-resolver"
    if args.resource_icon_resolver:
        supplied_hooks["resource_icon_resolver"] = "--resource-icon-resolver"
    if args.feature_action_runner:
        supplied_hooks["feature_action_runner"] = "--feature-action-runner"

    for path, content in files.items():
        abs_path = os.path.join(root, path)

        # Fix 2: Always write the builder, never skip it
        if path == builder_path:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            written.append(path)
            continue

        # Skip user-owned files if they exist and --force-shared not set
        if path in user_owned and os.path.exists(abs_path) and not args.force_shared:
            skipped.append(path)
            continue

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(path)

    # Fix 3: Build content map for TODO collection, reading disk content for skipped files
    content_for_todos = {}
    for path, content in files.items():
        content_for_todos[path] = content
    for path in skipped:
        abs_path = os.path.join(root, path)
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as fh:
                content_for_todos[path] = fh.read()
        except OSError:
            pass  # If file vanished, use generated content

    # Fix 4: Build warnings for supplied hook options that weren't applied
    warnings = []
    hooks_file = out_dir + "/Shared/KinoaInAppHooks.cs"
    if hooks_file in skipped:
        if "image_loader" in supplied_hooks:
            warnings.append("KinoaInAppHooks.cs already exists — --image-loader was not applied; assign it in the existing file or re-run with --force-shared")
        if "price_resolver" in supplied_hooks:
            warnings.append("KinoaInAppHooks.cs already exists — --price-resolver was not applied; assign it in the existing file or re-run with --force-shared")
        if "resource_icon_resolver" in supplied_hooks:
            warnings.append("KinoaInAppHooks.cs already exists — --resource-icon-resolver was not applied; assign it in the existing file or re-run with --force-shared")

    feature_hooks_file = out_dir + "/Shared/KinoaInAppFeatureHooks.cs"
    if feature_hooks_file in skipped and "feature_action_runner" in supplied_hooks:
        warnings.append("KinoaInAppFeatureHooks.cs already exists — --feature-action-runner was not applied; assign it in the existing file or re-run with --force-shared")

    _emit({"ok": True, "written": written, "skipped": skipped, "snippets": out["snippets"],
           "todos": _collect_todos(content_for_todos), "report": out["report"], "prefab_path": plan["paths"]["prefab_path"],
           "plan_path": plan["paths"]["plan_path"], "menu_item": "Tools/Kinoa/In-Apps/Build Prefabs From Plans",
           "warnings": warnings})
    return 0


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    # One JSON object on stdout, always UTF-8: a Windows console defaults to a legacy code page,
    # which mangles (or cannot encode) the non-ASCII characters in names and warnings.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="inapp_prefab_plan", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe-style", help="Read existing popup prefabs for UI conventions.")
    p.add_argument("--prefab", action="append", required=True, help="Path to a .prefab (repeatable).")
    p.add_argument("--assets-root", default="Assets", help="Folder scanned for *.cs.meta to name scripts.")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_probe_style)

    sub.add_parser("layout-schema", help="Print the tip-image layout contract.").set_defaults(func=cmd_layout_schema)

    p = sub.add_parser("plan", help="Template record + layout source -> prefab plan JSON.")
    p.add_argument("--template", required=True, help="Record from `kinoa_dashboard_inapp_template.py get` (raw output or bare record).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--layout-artifact", default=None,
                     help="<template_key>.layout.json from kinoa-inapp-template-from-image (preferred layout source).")
    src.add_argument("--build", default=None,
                     help="build_result.json from kinoa-inapp-template-from-image (raw vision pass; fallback).")
    src.add_argument("--layout", default=None,
                     help="Legacy: a layout from this skill's own vision pass (see layout-schema).")
    p.add_argument("--confirmed", default=None, help="Confirm-page envelope; its corrections are applied on top of --build.")
    p.add_argument("--style", default=None, help="probe-style output.")
    p.add_argument("--image-size", default=None, help="WxH of the mockup/tip image, e.g. 1080x1920.")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Game-project folder the generated files will live in.")
    p.add_argument("--milestone-cta", choices=("auto", "per_step", "single"), default="auto",
                   help="Milestone templates: step CTA per milestone step or one main CTA (auto = decide from the template's CTA slots).")
    p.add_argument("--out", default=None, help="Where to write the plan (default <key>.inapp-plan.json).")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("generate", help="Plan -> C# files + plan copy under the game project.")
    p.add_argument("--plan", required=True)
    p.add_argument("--project-root", required=True, help="Unity project root (the folder containing Assets/).")
    p.add_argument("--facade", choices=("present", "absent"), default="absent",
                   help="present = the project has KinoaUiService; clicks delegate to HandleInAppButtonClickAsync.")
    p.add_argument("--facade-namespace", default="Core.Services")
    p.add_argument("--image-loader", default=None, help="Fully-qualified static method: Func<string, Task<Sprite>>.")
    p.add_argument("--price-resolver", default=None, help="Fully-qualified static method: Func<InAppStorePackages, bool, string>.")
    p.add_argument("--resource-icon-resolver", default=None, help="Fully-qualified static method: Func<string, Sprite>.")
    p.add_argument("--feature-action-runner", default=None, help="Fully-qualified static method: Func<InAppMessage, InAppCustomButton, Task<bool>> (milestone paid / ad / link button actions).")
    p.add_argument("--force-shared", action="store_true", help="Rewrite the user-owned Shared/ files (KinoaInAppHooks.cs, KinoaInAppItemView.cs, KinoaInAppFeatureHooks.cs, KinoaInAppMilestoneStepView.cs) even if present; the Editor builder is always rewritten.")
    p.add_argument("--overwrite", action="store_true", help="Rewrite the view class if it already exists.")
    p.set_defaults(func=cmd_generate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
