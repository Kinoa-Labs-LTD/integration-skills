#!/usr/bin/env python3
"""Developer preview: render a whole batch of in-app-template builds as one browsable gallery.

NOT part of the shipped plugin — this lives in dev/ and exists so a human can run
one command and *see* what `kinoa-inapp-template-from-image` produces across a
corpus of real mockups, instead of reading sixteen JSON files.

    python3 dev/preview_gallery.py --runs <dir> [--out <dir>] [--no-open]

`--runs` points at a directory holding one subdirectory per example, each with
the two files a corpus run leaves behind:

    <runs>/<slug>/analysis.json   the vision pass
    <runs>/<slug>/build.json      exactly what `inapp_template_build.py build` printed

For every example the tool shells out to the real `generate_confirm_page.py`
(the shipped one — never a copy) to produce `<out>/<slug>/confirm.html`, then
writes `<out>/index.html`: a card per example, sorted so the mockups with the
most `unsupported` mechanics come first, because "Kinoa cannot express this"
is the finding this corpus exists to surface.

A half-written corpus is the normal case, not an error: subdirectories with no
`build.json`, an unparseable one, or a missing mockup are skipped with a reason
in the stdout JSON and never crash the run.

Self-contained output, same rules as the shipped pages: thumbnails are inlined
as data: URIs, there is no external CSS/JS/font/image and no network call. PNG
thumbnails are downscaled in pure Python (zlib + a box filter, then quantised to
5 bits per channel) so the gallery stays a few megabytes instead of a hundred;
anything that is not a plain 8-bit non-interlaced PNG is embedded as-is.

Prints exactly one JSON object on stdout.
"""

from __future__ import annotations

import argparse
import base64
import glob
import html
import json
import os
import pathlib
import struct
import subprocess
import sys
import time
import webbrowser
import zlib
from typing import Any

BUCKETS = ("images", "buttons", "texts", "customs")
BUCKET_LABELS = {"images": "img", "buttons": "btn", "texts": "txt", "customs": "cst"}
FEATURE_TYPES = ("standard", "mission", "milestone")

DEFAULT_THUMB_WIDTH = 320
# At most this many samples per axis when box-averaging a source block. Three is
# already visually indistinguishable from a full box filter at thumbnail scale
# and keeps a pure-Python resample under a second per image.
MAX_SAMPLES = 3
# Thumbnails are quantised to this many bits per channel before re-encoding.
# Without a JPEG encoder in the stdlib these PNGs are the whole page weight, and
# 32 levels per channel is invisible at 320px while cutting the file ~3x.
DEFAULT_THUMB_BITS = 5

PNG_SIG = b"\x89PNG\r\n\x1a\n"
IMAGE_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


# --------------------------------------------------------------------------
# PNG: decode -> box downscale -> encode. Pure stdlib, no Pillow.
# --------------------------------------------------------------------------


def _sniff_mime(head: bytes) -> str | None:
    for magic, mime in IMAGE_MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _png_chunks(blob: bytes):
    i = 8
    n = len(blob)
    while i + 8 <= n:
        length = int.from_bytes(blob[i:i + 4], "big")
        tag = blob[i + 4:i + 8]
        yield tag, blob[i + 8:i + 8 + length]
        i += 12 + length


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> list[bytearray] | None:
    """Undo the per-scanline PNG filters. Returns one bytearray per row."""
    rows: list[bytearray] = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        if pos + 1 + stride > len(raw):
            return None
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        else:
            return None
        rows.append(line)
        prev = line
    return rows


def _to_rgb_rows(rows, width, color_type, palette, trns):
    """Normalise decoded rows to 3- or 4-channel rows. Returns (rows, channels)."""
    if color_type == 2:
        return rows, 3
    if color_type == 6:
        return rows, 4
    if color_type == 0:
        out = []
        for line in rows:
            r = bytearray(width * 3)
            for x in range(width):
                v = line[x]
                r[x * 3] = r[x * 3 + 1] = r[x * 3 + 2] = v
            out.append(r)
        return out, 3
    if color_type == 4:
        out = []
        for line in rows:
            r = bytearray(width * 4)
            for x in range(width):
                v = line[x * 2]
                r[x * 4] = r[x * 4 + 1] = r[x * 4 + 2] = v
                r[x * 4 + 3] = line[x * 2 + 1]
            out.append(r)
        return out, 4
    if color_type == 3:
        if not palette:
            return None, 0
        entries = len(palette) // 3
        alpha = trns or b""
        has_alpha = bool(alpha)
        ch = 4 if has_alpha else 3
        out = []
        for line in rows:
            r = bytearray(width * ch)
            for x in range(width):
                idx = line[x]
                if idx >= entries:
                    idx = 0
                r[x * ch] = palette[idx * 3]
                r[x * ch + 1] = palette[idx * 3 + 1]
                r[x * ch + 2] = palette[idx * 3 + 2]
                if has_alpha:
                    r[x * ch + 3] = alpha[idx] if idx < len(alpha) else 255
            out.append(r)
        return out, ch
    return None, 0


def _box_downscale(rows, width, height, ch, out_w, out_h):
    """Average each source block into one output pixel (up to MAX_SAMPLES per axis)."""
    x_samples = []
    for ox in range(out_w):
        x0 = (ox * width) // out_w
        x1 = max(x0 + 1, ((ox + 1) * width) // out_w)
        step = max(1, (x1 - x0) // MAX_SAMPLES)
        xs = list(range(x0, x1, step))[:MAX_SAMPLES] or [x0]
        x_samples.append([x * ch for x in xs])

    out = bytearray(out_w * out_h * ch)
    rng_ch = range(ch)
    for oy in range(out_h):
        y0 = (oy * height) // out_h
        y1 = max(y0 + 1, ((oy + 1) * height) // out_h)
        step = max(1, (y1 - y0) // MAX_SAMPLES)
        src = [rows[y] for y in list(range(y0, y1, step))[:MAX_SAMPLES]] or [rows[y0]]
        base = oy * out_w * ch
        for ox in range(out_w):
            offsets = x_samples[ox]
            n = len(src) * len(offsets)
            o = base + ox * ch
            for c in rng_ch:
                total = 0
                for line in src:
                    for xo in offsets:
                        total += line[xo + c]
                out[o + c] = total // n
    return out


def _encode_png(pix: bytearray, width: int, height: int, ch: int) -> bytes:
    stride = width * ch
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type None — the payload is already tiny.
        raw += pix[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2 if ch == 3 else 6, 0, 0, 0)
    return (PNG_SIG
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _quantize_table(bits: int) -> bytes:
    """256-byte translation table snapping each channel to 2**bits evenly-spread levels."""
    levels = (1 << bits) - 1
    return bytes(round(round(v * levels / 255) * 255 / levels) for v in range(256))


def png_thumbnail(blob: bytes, max_width: int, bits: int = DEFAULT_THUMB_BITS) -> bytes | None:
    """Downscale a PNG to `max_width`. None when the file is not a shape we decode."""
    if not blob.startswith(PNG_SIG):
        return None
    ihdr = b""
    idat = bytearray()
    palette = b""
    trns = None
    try:
        for tag, data in _png_chunks(blob):
            if tag == b"IHDR":
                ihdr = data
            elif tag == b"IDAT":
                idat += data
            elif tag == b"PLTE":
                palette = data
            elif tag == b"tRNS":
                trns = data
            elif tag == b"IEND":
                break
    except Exception:
        return None
    if len(ihdr) < 13 or not idat:
        return None

    width, height, depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", ihdr[:13])
    if depth != 8 or comp != 0 or filt != 0 or interlace != 0:
        return None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if not channels or width <= 0 or height <= 0:
        return None
    if width <= max_width:
        return None  # already small enough — embed the original bytes

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    rows = _unfilter(raw, height, width * channels, channels)
    if rows is None:
        return None
    rows, ch = _to_rgb_rows(rows, width, color_type, palette, trns)
    if not rows:
        return None

    out_w = max(1, max_width)
    out_h = max(1, round(height * out_w / width))
    pix = _box_downscale(rows, width, height, ch, out_w, out_h)
    if 1 <= bits < 8:
        pix = bytearray(pix.translate(_quantize_table(bits)))

    if ch == 4 and all(pix[i] == 255 for i in range(3, len(pix), 4)):
        # Fully opaque after averaging — drop the alpha plane, it is 25% of the file.
        rgb = bytearray(out_w * out_h * 3)
        for i in range(out_w * out_h):
            rgb[i * 3:i * 3 + 3] = pix[i * 4:i * 4 + 3]
        pix, ch = rgb, 3
    return _encode_png(pix, out_w, out_h, ch)


def thumbnail_data_uri(path: str, max_width: int, bits: int = DEFAULT_THUMB_BITS) -> tuple[str | None, int]:
    """(data: URI, bytes) for a mockup, downscaling PNGs. (None, 0) when unusable."""
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        return None, 0
    mime = _sniff_mime(blob[:16])
    if not mime:
        return None, 0
    if mime == "image/png":
        try:
            small = png_thumbnail(blob, max_width, bits)
        except Exception:
            small = None
        if small:
            blob = small
    return "data:" + mime + ";base64," + base64.b64encode(blob).decode("ascii"), len(blob)


# --------------------------------------------------------------------------
# Corpus discovery
# --------------------------------------------------------------------------


def read_json(path: str) -> tuple[Any, str | None]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"unreadable: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON (half-written?): {exc}"


def load_slug_index(runs_dir: str, explicit: str | None) -> dict[str, dict[str, str]]:
    """slug -> {game, offer}, harvested from whatever corpus index sits nearby.

    The batch files a corpus run is driven from carry the human names ("COIN
    MASTER" / "Season Madness"); the run directories only carry slugs. Purely a
    nicety — every lookup degrades to the slug.
    """
    index: dict[str, dict[str, str]] = {}
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    else:
        parent = os.path.dirname(os.path.abspath(runs_dir))
        for base in (runs_dir, parent):
            candidates.extend(sorted(glob.glob(os.path.join(base, "batch_*.json"))))
            candidates.extend(sorted(glob.glob(os.path.join(base, "*index*.json"))))
    for path in candidates:
        data, err = read_json(path)
        if err:
            continue
        rows = data if isinstance(data, list) else []
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    rows = value
                    break
        for row in rows:
            if isinstance(row, dict) and row.get("slug"):
                index.setdefault(str(row["slug"]), {
                    "game": str(row.get("game") or ""),
                    "offer": str(row.get("offer") or ""),
                })
    return index


def titleize(slug: str) -> str:
    return slug.replace("_", " ").strip().title() or slug


def collect(runs_dir: str, out_dir: str, index: dict[str, dict[str, str]]):
    """Walk the runs directory. Returns (examples, skipped)."""
    examples, skipped = [], []
    out_abs = os.path.abspath(out_dir)
    for name in sorted(os.listdir(runs_dir)):
        path = os.path.join(runs_dir, name)
        if not os.path.isdir(path) or name.startswith("."):
            continue
        if os.path.abspath(path) == out_abs:
            continue  # our own output, when --out lands inside --runs

        build, err = read_json(os.path.join(path, "build.json"))
        if err or not isinstance(build, dict) or not isinstance(build.get("payload"), dict):
            skipped.append({"slug": name, "reason": err or "build.json carries no payload object"})
            continue
        analysis, _ = read_json(os.path.join(path, "analysis.json"))
        analysis = analysis if isinstance(analysis, dict) else {}

        report = build.get("report") or {}
        payload = build.get("payload") or {}
        validation = build.get("validation") or {}
        source = report.get("source_image") or analysis.get("source_image") or {}
        image = source.get("path") or ""
        if image and not os.path.isabs(image):
            image = os.path.join(path, image)
        meta = index.get(name, {})

        tpl = analysis.get("template") or {}
        counts = report.get("counts") or {}
        examples.append({
            "slug": name,
            "dir": os.path.abspath(path),
            "game": meta.get("game") or "",
            "offer": meta.get("offer") or payload.get("name") or tpl.get("suggested_name") or titleize(name),
            "key": payload.get("key") or "",
            "description": payload.get("description") or tpl.get("description") or "",
            "feature_type": report.get("feature_type") or payload.get("featureType") or "standard",
            "counts": {b: int(counts.get(b) or len(payload.get(b) or [])) for b in BUCKETS},
            "element_count": int(report.get("element_count") or 0),
            "unsupported": [u for u in (report.get("unsupported") or []) if isinstance(u, dict)],
            "needs_confirmation": len(report.get("needs_confirmation") or []),
            "unmapped": len(report.get("unmapped") or []),
            "client_rendered": len(report.get("client_rendered") or []),
            "warnings": len(report.get("warnings") or []) + len(validation.get("warnings") or []),
            "errors": list(validation.get("errors") or []),
            "image": image if image and os.path.isfile(image) else "",
            "build_path": os.path.join(os.path.abspath(path), "build.json"),
        })
    return examples, skipped


# --------------------------------------------------------------------------
# Confirm-page generation (delegated to the shipped helper — never a copy)
# --------------------------------------------------------------------------


def default_generator() -> str:
    here = pathlib.Path(__file__).resolve().parent
    return str(here.parent / "plugin" / "skills" / "kinoa-inapp-template-from-image" / "generate_confirm_page.py")


def render_confirm(generator: str, example: dict[str, Any], out_dir: str) -> dict[str, Any]:
    target_dir = os.path.join(out_dir, example["slug"])
    os.makedirs(target_dir, exist_ok=True)
    out_html = os.path.join(target_dir, "confirm.html")
    cmd = [sys.executable, generator, "--build", example["build_path"], "--out", out_html, "--no-open"]
    if example["image"]:
        cmd += ["--image", example["image"]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001 — a broken example must not kill the batch
        return {"ok": False, "error": f"generator failed to run: {exc}"}
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        result = {}
    if proc.returncode != 0 or not result.get("ok"):
        return {"ok": False, "error": result.get("error") or (proc.stderr.strip()[-300:] or f"exit {proc.returncode}")}
    return {"ok": True, "path": out_html, "bytes": result.get("bytes"), "image_embedded": bool(result.get("image_embedded"))}


# --------------------------------------------------------------------------
# The gallery page
# --------------------------------------------------------------------------

CSS = """
:root {
  --bg:#ffffff; --fg:#1f2328; --mut:#57606a; --line:#d0d7de; --subtle:#f6f8fa;
  --card:#ffffff; --accent:#0969da;
  --danger:#cf222e; --danger-fg:#82071e; --danger-soft:#ffebe9; --danger-line:#ff8182;
  --warn:#bf8700; --warn-fg:#7d4e00; --warn-soft:#fff8c5; --warn-line:#d4a72c;
  --ok:#1a7f37; --ok-fg:#116329; --ok-soft:#dafbe1;
  --images:#0969da; --buttons:#8250df; --texts:#bc4c00; --customs:#1b7c83;
  --shadow:0 1px 2px rgba(31,35,40,.10), 0 3px 8px rgba(31,35,40,.06);
  --thumb-bg:#eef1f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0d1117; --fg:#e6edf3; --mut:#9198a1; --line:#30363d; --subtle:#161b22;
    --card:#161b22; --accent:#4493f8;
    --danger:#f85149; --danger-fg:#ff7b72; --danger-soft:#2a1517; --danger-line:#6e2c30;
    --warn:#d29922; --warn-fg:#e3b341; --warn-soft:#241c10; --warn-line:#6b4c17;
    --ok:#3fb950; --ok-fg:#56d364; --ok-soft:#11261a;
    --images:#4493f8; --buttons:#a371f7; --texts:#ec8e2c; --customs:#39c5cf;
    --shadow:0 1px 2px rgba(1,4,9,.6), 0 3px 10px rgba(1,4,9,.4);
    --thumb-bg:#0b0e13;
  }
}
* { box-sizing: border-box; }
html { color-scheme: light dark; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--fg); line-height: 1.5;
  max-width: 1500px; margin: 0 auto; padding: 2rem 1.5rem 4rem;
}
a { color: var(--accent); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85em;
  background: var(--subtle); border: 1px solid var(--line); border-radius: 5px; padding: 0.05rem 0.3rem; }

header.top { border-bottom: 1px solid var(--line); padding-bottom: 1.1rem; margin-bottom: 1.4rem; }
h1 { font-size: 1.6rem; margin: 0 0 0.3rem; letter-spacing: -0.01em; }
.sub { color: var(--mut); font-size: 0.9rem; margin: 0; }
.sub code { background: transparent; border: 0; padding: 0; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.7rem; margin-bottom: 0.9rem; }
.stat { border: 1px solid var(--line); border-radius: 10px; padding: 0.65rem 0.8rem;
  background: var(--card); box-shadow: var(--shadow); }
.stat .k { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--mut); }
.stat .v { font-size: 1.55rem; font-weight: 650; line-height: 1.25; font-variant-numeric: tabular-nums; }
.stat .n { font-size: 0.76rem; color: var(--mut); }
.stat.alarm { border-color: var(--danger-line); background: var(--danger-soft); }
.stat.alarm .v, .stat.alarm .k { color: var(--danger-fg); }
.stat.caution { border-color: var(--warn-line); background: var(--warn-soft); }
.stat.caution .v, .stat.caution .k { color: var(--warn-fg); }

.split { border: 1px solid var(--line); border-radius: 10px; padding: 0.7rem 0.85rem;
  background: var(--card); box-shadow: var(--shadow); margin-bottom: 1.4rem; }
.split .k { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--mut);
  margin-bottom: 0.45rem; }
.bar { display: flex; height: 0.6rem; border-radius: 999px; overflow: hidden; background: var(--subtle); }
.bar span { display: block; }
.bar .f-standard { background: var(--accent); }
.bar .f-mission { background: var(--buttons); }
.bar .f-milestone { background: var(--texts); }
.barkeys { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; margin-top: 0.5rem; font-size: 0.82rem; color: var(--mut); }
.barkeys i { width: 0.65rem; height: 0.65rem; border-radius: 3px; display: inline-block; margin-right: 0.3rem; vertical-align: -1px; }

.note { border: 1px solid var(--line); border-left: 4px solid var(--warn); background: var(--warn-soft);
  color: var(--warn-fg); border-radius: 8px; padding: 0.6rem 0.85rem; font-size: 0.87rem; margin-bottom: 1.4rem; }
.note ul { margin: 0.35rem 0 0 1.1rem; padding: 0; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.1rem; }
.card { border: 1px solid var(--line); border-radius: 12px; background: var(--card);
  box-shadow: var(--shadow); overflow: hidden; display: flex; flex-direction: column; }
.card .accentbar { height: 4px; background: var(--line); }
.card.risk .accentbar { background: var(--danger); }
.card.clean .accentbar { background: var(--ok); }
.card.dead .accentbar { background: var(--mut); }

.thumb { display: block; background: var(--thumb-bg); border-bottom: 1px solid var(--line);
  height: 260px; position: relative; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: contain; display: block; }
.thumb .missing { display: flex; height: 100%; align-items: center; justify-content: center;
  color: var(--mut); font-size: 0.85rem; text-align: center; padding: 1rem; }
.thumb .open { position: absolute; right: 0.5rem; bottom: 0.5rem; font-size: 0.72rem;
  background: var(--card); border: 1px solid var(--line); color: var(--fg);
  border-radius: 999px; padding: 0.12rem 0.55rem; opacity: 0.9; }
a.thumb:hover .open { background: var(--accent); border-color: var(--accent); color: #fff; }

.body { padding: 0.75rem 0.9rem 0.9rem; display: flex; flex-direction: column; gap: 0.55rem; flex: 1; }
.eyebrow { font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--mut); }
h2.title { font-size: 1.02rem; margin: 0; line-height: 1.3; }
h2.title a { text-decoration: none; color: inherit; }
h2.title a:hover { text-decoration: underline; }
.keyline { font-size: 0.8rem; color: var(--mut); display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }

.badge { font-size: 0.72rem; font-weight: 600; border-radius: 999px; padding: 0.08rem 0.5rem;
  border: 1px solid currentColor; }
.badge.f-standard { color: var(--accent); }
.badge.f-mission { color: var(--buttons); }
.badge.f-milestone { color: var(--texts); }

.pills { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.pill { font-size: 0.74rem; border: 1px solid var(--line); border-radius: 999px;
  padding: 0.1rem 0.5rem; display: inline-flex; gap: 0.3rem; align-items: baseline; color: var(--mut); }
.pill b { font-variant-numeric: tabular-nums; color: var(--fg); }
.pill.p-images { border-color: var(--images); } .pill.p-images b { color: var(--images); }
.pill.p-buttons { border-color: var(--buttons); } .pill.p-buttons b { color: var(--buttons); }
.pill.p-texts { border-color: var(--texts); } .pill.p-texts b { color: var(--texts); }
.pill.p-customs { border-color: var(--customs); } .pill.p-customs b { color: var(--customs); }
.pill.zero { opacity: 0.5; }

.flags { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.flag { font-size: 0.74rem; border-radius: 6px; padding: 0.1rem 0.45rem; border: 1px solid var(--line); color: var(--mut); }
.flag.warn { background: var(--warn-soft); border-color: var(--warn-line); color: var(--warn-fg); }
.flag.bad { background: var(--danger-soft); border-color: var(--danger-line); color: var(--danger-fg); }

.unsup { border: 1px solid var(--danger-line); background: var(--danger-soft); border-radius: 9px;
  padding: 0.5rem 0.6rem; }
.unsup .head { display: flex; align-items: baseline; gap: 0.5rem; color: var(--danger-fg); }
.unsup .n { font-size: 1.45rem; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.unsup .lbl { font-size: 0.78rem; font-weight: 600; }
.unsup .lead { font-size: 0.79rem; margin-top: 0.35rem; color: var(--fg);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.unsup details { margin-top: 0.4rem; }
.unsup summary { cursor: pointer; font-size: 0.76rem; color: var(--danger-fg); }
.unsup ul { margin: 0.4rem 0 0; padding-left: 1.05rem; font-size: 0.79rem; color: var(--fg); }
.unsup li { margin-bottom: 0.4rem; }
.unsup li .why { color: var(--mut); display: block; margin-top: 0.1rem; }
.unsup-none { font-size: 0.78rem; color: var(--ok-fg); background: var(--ok-soft);
  border: 1px solid var(--ok); border-radius: 9px; padding: 0.35rem 0.6rem; }

.errs { font-size: 0.78rem; color: var(--danger-fg); background: var(--danger-soft);
  border: 1px solid var(--danger-line); border-radius: 8px; padding: 0.4rem 0.6rem; }
.errs ul { margin: 0.25rem 0 0; padding-left: 1.05rem; }
.foot { margin-top: auto; padding-top: 0.35rem; font-size: 0.78rem; }
.mut { color: var(--mut); }
footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line);
  color: var(--mut); font-size: 0.82rem; }
"""


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def stat_tile(label: str, value: Any, note: str = "", cls: str = "") -> str:
    return (f'<div class="stat {cls}"><div class="k">{e(label)}</div>'
            f'<div class="v">{e(value)}</div>'
            + (f'<div class="n">{e(note)}</div>' if note else "")
            + "</div>")


def render_card(ex: dict[str, Any]) -> str:
    unsupported = ex["unsupported"]
    n_unsup = len(unsupported)
    errors = ex["errors"]
    link = ex.get("confirm_href")

    if n_unsup:
        state = "risk"
    elif errors or not link:
        state = "dead" if not link else "risk"
    else:
        state = "clean"

    if ex.get("thumb"):
        inner = f'<img src="{ex["thumb"]}" alt="{e(ex["offer"])} mockup" loading="lazy">'
    else:
        inner = f'<div class="missing">no mockup embedded<br><span class="mut">{e(ex["image"] or "source_image.path missing")}</span></div>'
    thumb_inner = inner + ('<span class="open">open confirm page &rarr;</span>' if link else "")
    thumb = (f'<a class="thumb" href="{e(link)}" target="_blank" rel="noopener">{thumb_inner}</a>'
             if link else f'<div class="thumb">{thumb_inner}</div>')

    title = e(ex["offer"])
    title_html = f'<a href="{e(link)}" target="_blank" rel="noopener">{title}</a>' if link else title

    pills = "".join(
        f'<span class="pill p-{b}{"" if ex["counts"][b] else " zero"}"><b>{ex["counts"][b]}</b>{BUCKET_LABELS[b]}</span>'
        for b in BUCKETS
    )

    flags = []
    if ex["needs_confirmation"]:
        flags.append(f'<span class="flag warn">{ex["needs_confirmation"]} needs confirmation</span>')
    if ex["unmapped"]:
        flags.append(f'<span class="flag bad">{ex["unmapped"]} unmapped</span>')
    if errors:
        flags.append(f'<span class="flag bad">{len(errors)} validation error(s)</span>')
    if ex["warnings"]:
        flags.append(f'<span class="flag">{ex["warnings"]} warning(s)</span>')
    if ex["client_rendered"]:
        flags.append(f'<span class="flag">{ex["client_rendered"]} client-rendered</span>')
    flags_html = f'<div class="flags">{"".join(flags)}</div>' if flags else ""

    if n_unsup:
        items = "".join(
            f'<li>{e(u.get("what"))}'
            + (f'<span class="why">{e(u.get("why"))}</span>' if u.get("why") else "")
            + "</li>"
            for u in unsupported
        )
        # The first `what` is shown outright (clamped): a number alone tells the
        # reviewer nothing, and the disclosure below carries the full list.
        lead = e(unsupported[0].get("what"))
        more = f" &middot; +{n_unsup - 1} more" if n_unsup > 1 else ""
        unsup_html = (
            '<div class="unsup"><div class="head">'
            f'<span class="n">{n_unsup}</span>'
            '<span class="lbl">mechanic(s) Kinoa cannot express</span></div>'
            f'<div class="lead">{lead}</div>'
            f'<details><summary>all {n_unsup} in full, with the reason each one does not fit{more}</summary>'
            f'<ul>{items}</ul></details></div>'
        )
    else:
        unsup_html = '<div class="unsup-none">Nothing flagged unsupported &mdash; the mockup fits the template model.</div>'

    errs_html = ""
    if errors:
        errs_html = ('<div class="errs"><b>Build invalid</b><ul>'
                     + "".join(f"<li>{e(x)}</li>" for x in errors[:6]) + "</ul></div>")

    foot = (f'<div class="foot"><a href="{e(link)}" target="_blank" rel="noopener">Open interactive confirm page</a>'
            f' <span class="mut">&middot; {ex["element_count"]} element(s)</span></div>'
            if link else
            f'<div class="foot mut">No confirm page: {e(ex.get("confirm_error") or "not generated")}</div>')

    eyebrow = e(ex["game"] or ex["slug"])
    feature = ex["feature_type"] if ex["feature_type"] in FEATURE_TYPES else "standard"

    return f"""<article class="card {state}">
  <div class="accentbar"></div>
  {thumb}
  <div class="body">
    <div>
      <div class="eyebrow">{eyebrow}</div>
      <h2 class="title">{title_html}</h2>
    </div>
    <div class="keyline"><span class="badge f-{feature}">{e(feature)}</span><code>{e(ex["key"] or "no key")}</code></div>
    <div class="pills">{pills}</div>
    {flags_html}
    {unsup_html}
    {errs_html}
    {foot}
  </div>
</article>"""


def render_index(examples, skipped, runs_dir, thumb_width) -> str:
    total_elements = sum(x["element_count"] for x in examples)
    total_unsup = sum(len(x["unsupported"]) for x in examples)
    total_conf = sum(x["needs_confirmation"] for x in examples)
    total_unmapped = sum(x["unmapped"] for x in examples)
    total_errors = sum(len(x["errors"]) for x in examples)
    with_unsup = sum(1 for x in examples if x["unsupported"])
    features = {t: sum(1 for x in examples if x["feature_type"] == t) for t in FEATURE_TYPES}
    feat_total = sum(features.values()) or 1

    stats = "".join([
        stat_tile("Examples", len(examples), f"{with_unsup} with unsupported mechanics"),
        stat_tile("Elements proposed", total_elements, "across all four buckets"),
        stat_tile("Unsupported", total_unsup, "mechanics Kinoa cannot express",
                  "alarm" if total_unsup else ""),
        stat_tile("Needs confirmation", total_conf, "kept, but a human must decide",
                  "caution" if total_conf else ""),
        stat_tile("Unmapped", total_unmapped, "dropped from the payload",
                  "alarm" if total_unmapped else ""),
        stat_tile("Validation errors", total_errors, "builds that would not register",
                  "alarm" if total_errors else ""),
    ])

    bar = "".join(
        f'<span class="f-{t}" style="width:{features[t] * 100.0 / feat_total:.4g}%"></span>'
        for t in FEATURE_TYPES if features[t]
    )
    keys = "".join(
        f'<span><i class="f-{t}" style="background:var(--{ {"standard": "accent", "mission": "buttons", "milestone": "texts"}[t] })"></i>'
        f'{t} &middot; <b>{features[t]}</b></span>'
        for t in FEATURE_TYPES
    )

    skipped_html = ""
    if skipped:
        rows = "".join(f"<li><code>{e(s['slug'])}</code> &mdash; {e(s['reason'])}</li>" for s in skipped)
        skipped_html = (f'<div class="note"><b>{len(skipped)} subdirectory(ies) skipped</b> '
                        "&mdash; a corpus still being written looks exactly like this."
                        f"<ul>{rows}</ul></div>")

    cards = "\n".join(render_card(x) for x in examples)
    if not cards:
        cards = '<p class="mut">No examples with a readable <code>build.json</code> were found.</p>'

    generated = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinoa &mdash; in-app template preview gallery</title>
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <h1>In-app template preview gallery</h1>
  <p class="sub">{len(examples)} mockup(s) read by the vision pass, built by <code>inapp_template_build.py</code>,
  rendered with the shipped <code>generate_confirm_page.py</code>.
  Click a thumbnail to open that example's interactive confirmation page in a new tab.</p>
  <p class="sub">Corpus <code>{e(runs_dir)}</code> &middot; thumbnails downscaled to {thumb_width}px
  &middot; generated {e(generated)} &middot; nothing on this page calls the network.</p>
</header>

<section class="stats">{stats}</section>

<section class="split">
  <div class="k">Feature type across the corpus</div>
  <div class="bar">{bar}</div>
  <div class="barkeys">{keys}</div>
</section>

{skipped_html}

<section class="grid">
{cards}
</section>

<footer>
  Sorted by unsupported count, descending &mdash; the interesting end of the corpus first.
  <code>unsupported</code> is what the mockup does that the Kinoa template model cannot express;
  <code>needs confirmation</code> stays in the payload until a human answers the question;
  <code>unmapped</code> never made it into the payload at all.
  Developer tool (<code>dev/preview_gallery.py</code>) &mdash; not part of the shipped plugin.
</footer>
</body>
</html>
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", required=True, help="Directory of per-example run directories.")
    parser.add_argument("--out", help="Where to write index.html + <slug>/confirm.html "
                                      "(default: <runs>_gallery next to the runs directory).")
    parser.add_argument("--generator", help="Path to generate_confirm_page.py "
                                            "(default: the one in plugin/skills/kinoa-inapp-template-from-image).")
    parser.add_argument("--index", help="Corpus index JSON carrying slug/game/offer, for nicer titles.")
    parser.add_argument("--thumb-width", type=int, default=DEFAULT_THUMB_WIDTH,
                        help=f"Thumbnail width in px (default {DEFAULT_THUMB_WIDTH}).")
    parser.add_argument("--thumb-bits", type=int, default=DEFAULT_THUMB_BITS,
                        help=f"Bits per colour channel in the thumbnails, 8 = no quantisation "
                             f"(default {DEFAULT_THUMB_BITS}).")
    parser.add_argument("--no-open", action="store_true", help="Do not open the gallery in a browser.")
    args = parser.parse_args(argv)

    runs_dir = os.path.abspath(args.runs)
    if not os.path.isdir(runs_dir):
        print(json.dumps({"ok": False, "error": "runs_dir_not_found", "runs": runs_dir}, indent=2))
        return 2
    out_dir = os.path.abspath(args.out) if args.out else runs_dir.rstrip(os.sep) + "_gallery"
    generator = args.generator or default_generator()
    if not os.path.isfile(generator):
        print(json.dumps({"ok": False, "error": "generator_not_found", "generator": generator}, indent=2))
        return 2

    started = time.time()
    index = load_slug_index(runs_dir, args.index)
    examples, skipped = collect(runs_dir, out_dir, index)
    os.makedirs(out_dir, exist_ok=True)

    per_example = []
    for ex in examples:
        result = render_confirm(generator, ex, out_dir)
        if result["ok"]:
            ex["confirm_href"] = f'{ex["slug"]}/confirm.html'
            ex["confirm_bytes"] = result.get("bytes")
        else:
            ex["confirm_href"] = ""
            ex["confirm_error"] = result["error"]
        thumb, thumb_bytes = (thumbnail_data_uri(ex["image"], max(64, args.thumb_width),
                                                 min(8, max(1, args.thumb_bits)))
                              if ex["image"] else (None, 0))
        ex["thumb"] = thumb
        per_example.append({
            "slug": ex["slug"],
            "game": ex["game"],
            "offer": ex["offer"],
            "key": ex["key"],
            "feature_type": ex["feature_type"],
            "counts": ex["counts"],
            "element_count": ex["element_count"],
            "unsupported": len(ex["unsupported"]),
            "needs_confirmation": ex["needs_confirmation"],
            "unmapped": ex["unmapped"],
            "validation_errors": len(ex["errors"]),
            "thumbnail_bytes": thumb_bytes,
            "confirm_page": os.path.join(out_dir, ex["slug"], "confirm.html") if ex["confirm_href"] else None,
            "status": "ok" if ex["confirm_href"] else "confirm_page_failed",
            "error": ex.get("confirm_error"),
        })

    # The interesting end of the corpus first.
    examples.sort(key=lambda x: (-len(x["unsupported"]), -x["unmapped"], -x["needs_confirmation"], x["slug"]))
    per_example.sort(key=lambda x: (-x["unsupported"], -x["unmapped"], -x["needs_confirmation"], x["slug"]))

    page = render_index(examples, skipped, runs_dir, max(64, args.thumb_width))
    out_index = os.path.join(out_dir, "index.html")
    try:
        with open(out_index, "w", encoding="utf-8") as fh:
            fh.write(page)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "unwritable_output", "detail": str(exc)}, indent=2))
        return 2

    opened = False
    if not args.no_open:
        try:
            opened = webbrowser.open(pathlib.Path(out_index).as_uri())
        except Exception:
            opened = False

    print(json.dumps({
        "ok": True,
        "runs": runs_dir,
        "output": out_index,
        "output_dir": out_dir,
        "generator": generator,
        "index_bytes": len(page.encode("utf-8")),
        "elapsed_seconds": round(time.time() - started, 2),
        "counts": {
            "examples": len(examples),
            "confirm_pages": sum(1 for x in per_example if x["status"] == "ok"),
            "skipped": len(skipped),
            "elements": sum(x["element_count"] for x in examples),
            "unsupported": sum(len(x["unsupported"]) for x in examples),
            "needs_confirmation": sum(x["needs_confirmation"] for x in examples),
            "unmapped": sum(x["unmapped"] for x in examples),
            "validation_errors": sum(len(x["errors"]) for x in examples),
            "feature_types": {t: sum(1 for x in examples if x["feature_type"] == t) for t in FEATURE_TYPES},
        },
        "skipped": skipped,
        "examples": per_example,
        "opened_in_browser": opened,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
