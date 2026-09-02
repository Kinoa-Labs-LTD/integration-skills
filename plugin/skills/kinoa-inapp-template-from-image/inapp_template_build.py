#!/usr/bin/env python3
"""Deterministic builder: layout-analysis JSON -> Kinoa in-app template payload.

This helper makes NO network calls and reads NO credentials. It is the
deterministic half of `kinoa-inapp-template-from-image`: the vision pass
(a model looking at the mockup) produces a *layout analysis*, and this file
turns that analysis into a well-formed template payload — assigning indexes,
slugifying keys, inferring click actions, and filling the per-element defaults
observed in Kinoa's production templates.

Everything policy-ish lives here on purpose: the model decides *what is on the
picture*, this file decides *what the JSON looks like*. That split keeps the
output stable across models and makes the rules unit-testable.

Subcommands
-----------
  roles      Print the role vocabulary (feed this into the vision prompt).
  schema     Print the layout-analysis JSON contract.
  build      Analysis -> template payload.
  validate   Check a payload against the template model.
  match      Analysis vs existing templates -> reuse verdicts.

Every subcommand prints exactly one JSON object on stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------
# Template model constants (derived from Kinoa's production templates)
# --------------------------------------------------------------------------

CLICK_ACTIONS = (
    "close",
    "collect_resource",
    "billing",
    "custom",
    "web_link",
    "deep_link",
    "show_ad",
    "promise_rewards",
    "update_app_version",
    "soft_billing",
)

# Buttons carrying these actions also carry a requiredItemsCount.
ITEM_BEARING_ACTIONS = ("collect_resource", "promise_rewards")

KINDS = ("string", "numeric", "boolean", "enumeration")

# customFields (attached to any element) additionally support image-valued
# fields; custom ELEMENTS do not — the dashboard constrains them to KINDS.
FIELD_KINDS = KINDS + ("image",)

FEATURE_TYPES = ("standard", "mission", "milestone")

MISSION_FIELD_SCOPES = ("PER_MISSION", "PER_SET", "PER_PROGRESS_BAR", "PER_MILESTONE")

BUCKETS = ("images", "buttons", "texts", "customs")

# Operator decision (2026-08-31): a field is either visible on the confirm
# page or required by the API — otherwise it is NOT emitted at all. The old
# invented defaults (textLimit 255, size {10000,10000,16000}, backgroundImg
# {10000,10000,10000}) are gone: the create API accepts elements without
# textLimit / size / backgroundImg (verified live), and operators set them on
# the dashboard when they need them.

# Server-enforced (observed 422 on create): the TEMPLATE-level description is
# capped at 50 chars. Element descriptions are not — the observed PATCH
# carried ~90-char element descriptions.
TEMPLATE_DESCRIPTION_MAX = 50

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TEMPLATE_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


# --------------------------------------------------------------------------
# Role vocabulary
# --------------------------------------------------------------------------
# A role is what the thing *is* on the mockup. The bucket is which template
# collection it lands in. Anything the vision pass cannot place gets reported
# as unmapped rather than silently guessed.

ROLES = {
    # ---- images -----------------------------------------------------------
    "background_image": {
        "bucket": "images",
        "name": "Background Image",
        "hint": "The full-bleed artwork behind the whole offer panel. Hiding it puts the rest of the pop-up in dark mode.",
    },
    "product_image": {
        "bucket": "images",
        "name": "Product Image",
        "hint": "The pack / chest / bundle artwork being sold.",
    },
    "resource_image": {
        "bucket": "images",
        "name": "Resource Image",
        "hint": "Icon of a granted currency or item (coins, gems, energy).",
    },
    "character_image": {
        "bucket": "images",
        "name": "Character Image",
        "hint": "Hero, mascot or character art.",
    },
    "decoration_image": {
        "bucket": "images",
        "name": "Decoration Image",
        "hint": "Ribbon, glow, confetti, frame — purely ornamental art.",
    },
    "logo_image": {
        "bucket": "images",
        "name": "Logo Image",
        "hint": "Game or event logo lockup.",
    },
    "badge_image": {
        "bucket": "images",
        "name": "Badge",
        "hint": "Informative art badge such as 'Time Limited' or 'Today Only'.",
    },
    "bar_image": {
        "bucket": "images",
        "name": "Bar Image",
        "hint": "Milestone only: the progress-bar artwork, the so-called fake resource.",
    },
    "score_icon_image": {
        "bucket": "images",
        "name": "Score Icons Image",
        "hint": "Milestone only: the icon sitting at the left end of the progress bar.",
    },
    "prize_image": {
        "bucket": "images",
        "name": "Prizes",
        "hint": "Milestone only: the reward art at a milestone. Multiple rewards collapse into a chest.",
    },
    # ---- texts ------------------------------------------------------------
    "header": {
        "bucket": "texts",
        "name": "Header",
        "nullable": False,
        "hint": "The largest headline of the offer.",
    },
    "upper_text": {
        "bucket": "texts",
        "name": "Upper Text",
        "hint": "Secondary line directly under or above the header.",
    },
    "body_text": {
        "bucket": "texts",
        "name": "Body Text",
        "hint": "Descriptive paragraph explaining the offer.",
    },
    "bottom_text": {
        "bucket": "texts",
        "name": "Bottom Text",
        "hint": "Line sitting under the main content, above the fine print.",
    },
    "fine_print": {
        "bucket": "texts",
        "name": "Fine Print",
        "hint": "Small legal / disclaimer line, usually at the very bottom.",
    },
    "price_text": {
        "bucket": "texts",
        "name": "Price Text",
        "hint": "The price the player pays.",
    },
    "soft_billing_old_price": {
        "bucket": "texts",
        "name": "Soft Billing Price Before Sale",
        "needs_confirmation": (
            "A struck-through price is only a real text element when the offer is SOFT billing, "
            "where the operator types the old price by hand. When the offer bills through a store "
            "package id, the client renders the struck price itself — that is the client-rendered "
            "role 'price_before_sale'. The image alone cannot tell these apart: confirm which "
            "billing mode this offer uses."
        ),
        "hint": (
            "Struck-through original price typed by the operator. ONLY for soft-billing offers — "
            "for store-billed offers use the client-rendered role 'price_before_sale' instead."
        ),
    },
    "price_cut_badge": {
        "bucket": "texts",
        "name": "Price Cut Badge",
        "hint": "Discount tag, e.g. '70% OFF'. Leave text empty — the client computes it.",
    },
    "resource_badge": {
        "bucket": "texts",
        "name": "Resource Badge",
        "extra_fields": ["badge_color"],
        "hint": "Small badge stating what extra the player gets, e.g. 'x3 MORE'.",
    },
    "value_badge": {
        "bucket": "texts",
        "name": "Value Badge",
        "extra_fields": ["badge_color"],
        "hint": (
            "Value-multiplier ribbon — '240% VALUE', 'x3', '10x Value'. Operator-typed text; "
            "distinct from price_cut_badge, whose number the client computes from the discount."
        ),
    },
    "label_text": {
        "bucket": "texts",
        "name": "Label",
        "hint": "Any other standalone caption that is not one of the above.",
    },
    # ---- buttons ----------------------------------------------------------
    "cta_button": {
        "bucket": "buttons",
        "name": "CTA",
        "can_be_hidden": False,
        "actions": ["close", "show_ad", "billing", "collect_resource", "deep_link", "soft_billing"],
        "hint": "The primary call to action. Offer the full action menu unless the mockup is explicit.",
    },
    "close_button": {
        "bucket": "buttons",
        "name": "Close",
        "actions": ["close"],
        "hint": "The 'X' / dismiss control, usually a corner circle.",
    },
    "purchase_button": {
        "bucket": "buttons",
        "name": "Purchase Button",
        "actions": ["billing"],
        "hint": "Buys with real money — shows a hard-currency price.",
    },
    "soft_purchase_button": {
        "bucket": "buttons",
        "name": "Soft Purchase Button",
        "actions": ["soft_billing"],
        "hint": "Buys with in-game currency — price shown with a game currency icon.",
    },
    "collect_button": {
        "bucket": "buttons",
        "name": "Collect Button",
        "actions": ["collect_resource"],
        "hint": "'Claim' / 'Collect' — grants a resource for free.",
    },
    "ad_button": {
        "bucket": "buttons",
        "name": "Watch Ad Button",
        "actions": ["show_ad"],
        "hint": "Rewarded-video CTA — play glyph or 'Watch' wording.",
    },
    "link_button": {
        "bucket": "buttons",
        "name": "Link Button",
        "actions": ["web_link"],
        "hint": "Opens an external URL.",
    },
    "deep_link_button": {
        "bucket": "buttons",
        "name": "Internal Link Button",
        "actions": ["deep_link"],
        "hint": "Navigates somewhere inside the game.",
    },
    "update_button": {
        "bucket": "buttons",
        "name": "Update App Button",
        "actions": ["update_app_version"],
        "hint": "Sends the player to the store listing to update.",
    },
    "secondary_button": {
        "bucket": "buttons",
        "name": "Secondary Button",
        "actions": ["close", "deep_link"],
        "hint": "A lesser CTA — 'No thanks', 'Maybe later', 'More info'.",
    },
    "info_button": {
        "bucket": "buttons",
        "name": "Info Button",
        "actions": ["custom", "close"],
        "custom_cta_names": ["Info"],
        "hint": (
            "An 'i' / '?' control that opens rules or a reward preview. Maps to the 'custom' "
            "click action with customCtaNames (e.g. 'Info') — the game client implements the "
            "named CTA's behaviour."
        ),
    },
    "progress_bar_button": {
        "bucket": "buttons",
        "name": "Progress Bar",
        "can_be_hidden": False,
        "actions": ["close", "collect_resource", "deep_link", "show_ad"],
        "hint": "Milestone only: the bar itself is clickable and carries CTA actions before and after the chase.",
    },
    # ---- customs ----------------------------------------------------------
    "toggle_custom": {
        "bucket": "customs",
        "kind": "boolean",
        "name": "Toggle",
        "default": False,
        "hint": "An operator switch for an optional area of the layout.",
    },
    "count_custom": {
        "bucket": "customs",
        "kind": "numeric",
        "name": "Count",
        "default": 0,
        "hint": "A number the operator sets — item count, multiplier, duration.",
    },
    "color_custom": {
        "bucket": "customs",
        "kind": "string",
        "name": "Color",
        "default": "",
        "hint": "A colour or other free-form string knob.",
    },
    "variant_custom": {
        "bucket": "customs",
        "kind": "enumeration",
        "name": "Variant",
        "default": "",
        "hint": "A choice between named layout / behaviour variants.",
    },
}

# Regions the client renders by itself once the operator configures the pop-up.
# They look like elements on a mockup, so the vision pass is told to report
# them — but they must never reach the payload, or the template ends up with
# duplicate, unfillable slots.
CLIENT_RENDERED = {
    "resource_area": "Appears automatically once resources are attached to the CTA in Kinoa.",
    "price_before_sale": "Rendered struck-through by the client when a pre-discount package id is set.",
    "timer": "Rendered by the client when the operator makes the timer visible in the trigger step.",
    "grand_prize_area": "Milestone only: the client shows the final milestone reward in its own area.",
}

# Text elements carry a colour knob in every production template; Resource
# Badge additionally carries its background colour.
TEXT_DEFAULT_FIELDS = {
    "text_color": {"kind": "string", "name": "Text Color", "defaultValue": "#FFFFFF"},
    "badge_color": {"kind": "string", "name": "Badge Color", "defaultValue": ""},
}

# Wording seen on a control -> the click action it implies. Checked longest
# first so 'watch ad' wins over 'watch'. Lowercased substring match.
ACTION_WORDING = (
    ("update", "update_app_version"),
    ("watch ad", "show_ad"),
    ("watch video", "show_ad"),
    ("free", "show_ad"),
    ("collect", "collect_resource"),
    ("claim", "collect_resource"),
    ("grab", "collect_resource"),
    ("buy", "billing"),
    ("purchase", "billing"),
    ("get it", "billing"),
    ("learn more", "web_link"),
    ("more info", "web_link"),
    ("shop", "deep_link"),
    ("go to", "deep_link"),
    ("no thanks", "close"),
    ("maybe later", "close"),
    ("close", "close"),
)

# Currency marks that make a control a real-money purchase.
HARD_CURRENCY = ("$", "€", "£", "¥", "usd", "eur", "usd$")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _slug(text, fallback="element"):
    """Lowercase snake_case key that satisfies KEY_RE."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(text or "")).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    if not s or not s[0].isalpha():
        s = f"{fallback}_{s}".strip("_") if s else fallback
    return s


def _unique(key, taken):
    if key not in taken:
        taken.add(key)
        return key
    n = 2
    while f"{key}_{n}" in taken:
        n += 1
    out = f"{key}_{n}"
    taken.add(out)
    return out


def _reading_order(elements):
    """Sort top-to-bottom, then left-to-right, on the normalised bbox.

    Elements without a bbox keep their declared order but sort last, so a
    partial analysis still produces a stable payload.
    """

    def sort_key(pair):
        i, el = pair
        box = el.get("bbox") or {}
        y = box.get("y")
        x = box.get("x")
        if y is None or x is None:
            return (1, 0.0, 0.0, i)
        # Round to a coarse band so items on the same visual row group together.
        return (0, round(float(y), 2), float(x), i)

    return [el for _, el in sorted(enumerate(elements), key=sort_key)]


def _infer_actions(role, observed_text, explicit):
    """Click actions for a button: explicit > wording > role default."""
    if explicit:
        valid = [a for a in explicit if a in CLICK_ACTIONS]
        if valid:
            return valid, "explicit"

    text = (observed_text or "").lower()
    if text:
        for needle, action in ACTION_WORDING:
            if needle in text:
                # 'buy' with no hard-currency mark is more likely soft billing.
                if action == "billing" and not any(c in text for c in HARD_CURRENCY):
                    return ["soft_billing"], "wording"
                return [action], "wording"
        if any(c in text for c in HARD_CURRENCY):
            return ["billing"], "price-mark"

    default = ROLES.get(role, {}).get("actions")
    if default:
        return list(default), "role-default"
    return ["close"], "fallback"


# --------------------------------------------------------------------------
# Element builders
# --------------------------------------------------------------------------


def _custom_fields(raw):
    """Normalise the customFields array attached to any element."""
    out = []
    taken = set()
    for cf in raw or []:
        kind = cf.get("kind") if cf.get("kind") in FIELD_KINDS else "string"
        key = _unique(_slug(cf.get("key") or cf.get("name"), "custom_field"), taken)
        field = {
            "key": key,
            "kind": kind,
            "name": cf.get("name") or key.replace("_", " "),
            "nullable": bool(cf.get("nullable", True)),
            "description": cf.get("description") or "",
            "defaultValue": cf.get("defaultValue", ""),
        }
        if kind == "enumeration":
            field["enumValues"] = cf.get("enumValues") or ""
        out.append(field)
    return out


def _build_image(el, key, index, spec):
    node = {
        "key": key,
        "name": el.get("suggested_name") or spec.get("name") or key.replace("_", " ").title(),
        "index": index,
        "description": el.get("notes") or "",
        "canBeHidden": bool(el.get("can_be_hidden", spec.get("can_be_hidden", True))),
        "customFields": _custom_fields(el.get("custom_fields")),
    }
    return node


def _build_button(el, key, index, spec):
    actions, source = _infer_actions(el.get("role"), el.get("observed_text"), el.get("click_action_types"))
    node = {
        "key": key,
        "name": el.get("suggested_name") or spec.get("name") or key.replace("_", " ").title(),
        "index": index,
        "description": el.get("notes") or "",
        "canBeHidden": bool(el.get("can_be_hidden", spec.get("can_be_hidden", True))),
        "customFields": _custom_fields(el.get("custom_fields")),
        "clickActionType": actions,
    }
    if "text_limit" in el:  # only when the analysis explicitly carries one
        node["textLimit"] = int(el["text_limit"])
    if any(a in ITEM_BEARING_ACTIONS for a in actions):
        node["requiredItemsCount"] = int(el.get("required_items_count", 1))
    if "custom" in actions:
        names = el.get("custom_cta_names") or spec.get("custom_cta_names") or ["Custom"]
        node["customCtaNames"] = [str(n) for n in names if str(n).strip()]
    node["_actionSource"] = source
    return node


def _text_fields(el, spec):
    """Text elements get their colour knobs unless the analysis already set them."""
    fields = _custom_fields(el.get("custom_fields"))
    present = {f["key"] for f in fields}
    wanted = ["text_color"] + list(spec.get("extra_fields") or [])
    for name in wanted:
        if name in present:
            continue
        proto = TEXT_DEFAULT_FIELDS[name]
        fields.append(
            {
                "key": name,
                "kind": proto["kind"],
                "name": proto["name"],
                "nullable": True,
                "description": "",
                "defaultValue": proto["defaultValue"],
            }
        )
    return fields


def _build_text(el, key, index, spec):
    node = {
        "key": key,
        "name": el.get("suggested_name") or spec.get("name") or key.replace("_", " ").title(),
        "index": index,
        "nullable": bool(el.get("nullable", spec.get("nullable", True))),
        "description": el.get("notes") or "",
        "canBeHidden": bool(el.get("can_be_hidden", spec.get("can_be_hidden", True))),
        "customFields": _text_fields(el, spec),
    }
    if "text_limit" in el:
        node["textLimit"] = int(el["text_limit"])
    return node


def _build_custom(el, key, index, spec):
    kind = el.get("kind") or spec.get("kind") or "string"
    if kind not in KINDS:
        kind = "string"
    node = {
        "key": key,
        "kind": kind,
        "name": el.get("suggested_name") or spec.get("name") or key.replace("_", " ").title(),
        "index": index,
        "nullable": bool(el.get("nullable", True)),
        "description": el.get("notes") or "",
        "canBeHidden": bool(el.get("can_be_hidden", spec.get("can_be_hidden", True))),
        "customFields": _custom_fields(el.get("custom_fields")),
        "defaultValue": el.get("default_value", spec.get("default", "")),
    }
    if kind == "enumeration":
        node["enumValues"] = el.get("enum_values") or ""
    return node


BUILDERS = {
    "images": _build_image,
    "buttons": _build_button,
    "texts": _build_text,
    "customs": _build_custom,
}


# --------------------------------------------------------------------------
# Feature blocks
# --------------------------------------------------------------------------


def _detected_actions(detected, key):
    """CTA actions the vision pass read off the mockup, filtered to the vocabulary."""
    raw = detected.get(key) or []
    return [a for a in raw if a in CLICK_ACTIONS]


def _mission_feature(detected):
    placements = int(detected.get("mission_count") or 3)
    sets = int(detected.get("set_count") or 1)
    # Vision-derivable knobs (live dashboard contract): padlocked/greyed steps
    # on the mockup mean sequential unlocking; a visible combined bar means the
    # progress bar is shown, and its milestone markers give maxMilestones.
    layout = detected.get("layout") if detected.get("layout") in ("parallel", "sequential") else "parallel"
    if detected.get("progress_bar") is False:
        progress_bar = {"display": "dont_show_at_all", "completionBarCta": []}
    else:
        progress_bar = {
            "display": "show_for_all_sets_combined",
            "completionBarCta": ["collect_resource"],
        }
        if detected.get("milestone_count"):
            progress_bar["maxMilestones"] = max(int(detected["milestone_count"]), 1)
    # Lean per live probes (2026-08-31): completionCta + progressBar are
    # API-required (422 without them); activeProgressCta / description /
    # customFields are optional AND the dashboard saves cleanly without them —
    # the operator adds an active-progress CTA via the UI checkbox if wanted.
    completion = _detected_actions(detected, "completion_actions")
    block = {
        "key": "missions",
        "name": "Missions",
        "missionLayout": layout,
        "progressBar": progress_bar,
        # API-required. Mockup-derived when the vision pass could read the
        # task/claim controls; the neutral ["close"] fallback otherwise — the
        # build report warns so the operator sets the real menu on the
        # dashboard.
        "completionCta": completion or ["close"],
        "maxPlacements": max(placements, 1),
        "maxSetsCount": max(sets, 1),
        "minPlacements": 1,
        "minSetsCount": 1,
    }
    block["_completion_fallback"] = not completion
    return block


def _milestone_feature(detected):
    limit = int(detected.get("milestone_count") or 3)
    # Operator decision (2026-08-31): CTA menus are sent ONLY when the vision
    # pass derived them from the mockup (the bar's main button; claim buttons
    # on markers). Blanket defaults are wrong; omitted menus are fine for the
    # create API, and the dashboard highlights them red on save — that red is
    # the intended UX for "operator, choose consciously".
    block = {
        "key": "main_progressbar",
        "name": "Main Progressbar",
        "limit": max(limit, 1),
    }
    main = _detected_actions(detected, "main_actions")
    marks = _detected_actions(detected, "milestone_actions")
    if main:
        block["mainActionTypes"] = main
    if marks:
        block["milestonesActionTypes"] = marks
    return block


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def build_payload(analysis, game_id=None, name=None, key=None, description=None):
    """Turn a layout analysis into a template payload + a build report."""
    warnings = []
    unmapped = []

    tpl = analysis.get("template") or {}
    tpl_name = name or tpl.get("suggested_name") or "Untitled Template"
    tpl_key = key or tpl.get("suggested_key") or _slug(tpl_name, "template")
    if not TEMPLATE_KEY_RE.match(tpl_key):
        fixed = _slug(tpl_key, "template")
        warnings.append(f"template key {tpl_key!r} is not a valid identifier; using {fixed!r}")
        tpl_key = fixed

    feature = analysis.get("feature") or {}
    feature_type = feature.get("type") or "standard"
    if feature_type not in FEATURE_TYPES:
        warnings.append(f"unknown feature type {feature_type!r}; falling back to 'standard'")
        feature_type = "standard"

    buckets = {b: [] for b in BUCKETS}
    taken_keys = {b: set() for b in BUCKETS}
    client_rendered = []
    needs_confirmation = []
    trace = []
    index = 0

    for el in _reading_order(analysis.get("elements") or []):
        role = el.get("role")
        if role in CLIENT_RENDERED:
            client_rendered.append({"role": role, "reason": CLIENT_RENDERED[role], "bbox": el.get("bbox")})
            continue
        spec = ROLES.get(role)
        if spec is None:
            unmapped.append({"role": role, "reason": "unknown role", "element": el})
            continue
        bucket = el.get("bucket") or spec["bucket"]
        if bucket not in BUCKETS:
            unmapped.append({"role": role, "reason": f"unknown bucket {bucket!r}", "element": el})
            continue

        el_key = _unique(_slug(el.get("suggested_key") or role, bucket[:-1]), taken_keys[bucket])
        node = BUILDERS[bucket](el, el_key, index, spec)

        source = node.pop("_actionSource", None)
        if source in ("fallback",):
            warnings.append(f"button {el_key!r}: no click action could be inferred, defaulted to 'close'")
        if spec.get("needs_confirmation"):
            needs_confirmation.append({"key": el_key, "bucket": bucket, "role": role, "question": spec["needs_confirmation"]})
        if el.get("confidence") is not None and float(el["confidence"]) < 0.5:
            warnings.append(f"{bucket[:-1]} {el_key!r}: low detection confidence ({el['confidence']})")

        buckets[bucket].append(node)
        trace.append(
            {
                "index": index,
                "bucket": bucket,
                "key": el_key,
                "role": role,
                "bbox": el.get("bbox"),
                "observed_text": el.get("observed_text"),
                "confidence": el.get("confidence"),
            }
        )
        index += 1

    tpl_description = description or tpl.get("description") or ""
    if len(tpl_description) > TEMPLATE_DESCRIPTION_MAX:
        warnings.append(
            f"template description truncated to {TEMPLATE_DESCRIPTION_MAX} chars (server limit)"
        )
        tpl_description = tpl_description[:TEMPLATE_DESCRIPTION_MAX].rstrip()

    payload = {
        "name": tpl_name,
        "key": tpl_key,
        "description": tpl_description,
        "images": buckets["images"],
        "buttons": buckets["buttons"],
        "texts": buckets["texts"],
        "customs": buckets["customs"],
        "featureType": feature_type,
        # The observed create contract sends {} for a standard template
        # (older GET records return null — the validator accepts both).
        "features": {},
        "tagsIds": [],
    }
    if game_id:
        payload["gameId"] = game_id

    if feature_type == "mission":
        mission_block = _mission_feature(feature.get("detected") or {})
        if mission_block.pop("_completion_fallback", False):
            warnings.append(
                "mission completionCta not derivable from the mockup — sent the neutral "
                "['close'] (API requires the field); set the real menu on the dashboard"
            )
        payload["features"] = {"mission": mission_block}
    elif feature_type == "milestone":
        milestone_block = _milestone_feature(feature.get("detected") or {})
        for menu in ("mainActionTypes", "milestonesActionTypes"):
            if menu not in milestone_block:
                warnings.append(
                    f"milestone {menu} not derivable from the mockup — omitted; the dashboard "
                    "will require a conscious choice on save"
                )
        payload["features"] = {"milestone": milestone_block}

    # Mechanics the mockup shows but the template model cannot express. These
    # are never a build failure — the portable part still ships — but they must
    # reach the developer, because they are the gap between the design and what
    # Kinoa will actually render.
    unsupported = []
    for item in analysis.get("unsupported") or []:
        if isinstance(item, dict) and item.get("what"):
            unsupported.append(
                {"what": item["what"], "why": item.get("why") or "", "bbox": item.get("bbox")}
            )

    if not payload["buttons"]:
        warnings.append("no buttons detected — a template with no CTA is almost certainly incomplete")
    if not payload["images"]:
        warnings.append("no images detected — most offers carry at least a background image")

    report = {
        "counts": {b: len(payload[b]) for b in BUCKETS},
        "element_count": index,
        "feature_type": feature_type,
        "warnings": warnings,
        "unmapped": unmapped,
        "client_rendered": client_rendered,
        "needs_confirmation": needs_confirmation,
        "unsupported": unsupported,
        "elements": trace,
        "source_image": analysis.get("source_image") or {},
    }
    return payload, report


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


def validate_payload(payload):
    errors = []
    warnings = []

    if not payload.get("name"):
        errors.append("name is required")
    if len(payload.get("description") or "") > TEMPLATE_DESCRIPTION_MAX:
        errors.append(f"description exceeds the server limit of {TEMPLATE_DESCRIPTION_MAX} chars")
    tpl_key = payload.get("key") or ""
    if not TEMPLATE_KEY_RE.match(tpl_key):
        errors.append(f"key {tpl_key!r} must match {TEMPLATE_KEY_RE.pattern}")

    feature_type = payload.get("featureType")
    if feature_type not in FEATURE_TYPES:
        errors.append(f"featureType must be one of {list(FEATURE_TYPES)}, got {feature_type!r}")

    features = payload.get("features")
    if feature_type == "standard":
        if features not in (None, {}):
            errors.append("featureType 'standard' must carry features: {} (or null)")
    else:
        if not isinstance(features, dict) or feature_type not in features:
            errors.append(f"featureType {feature_type!r} requires features.{feature_type}")

    seen_index = {}
    for bucket in BUCKETS:
        items = payload.get(bucket)
        if not isinstance(items, list):
            errors.append(f"{bucket} must be a list")
            continue
        keys = set()
        for item in items:
            key = item.get("key")
            if not key or not KEY_RE.match(key):
                errors.append(f"{bucket}: key {key!r} must match {KEY_RE.pattern}")
            elif key in keys:
                errors.append(f"{bucket}: duplicate key {key!r}")
            else:
                keys.add(key)

            idx = item.get("index")
            if not isinstance(idx, int):
                errors.append(f"{bucket}.{key}: index must be an integer")
            elif idx in seen_index:
                errors.append(f"index {idx} used twice ({seen_index[idx]} and {bucket}.{key})")
            else:
                seen_index[idx] = f"{bucket}.{key}"

            field_keys = set()
            for cf in item.get("customFields") or []:
                if cf.get("kind") not in FIELD_KINDS:
                    errors.append(f"{bucket}.{key}: custom field kind {cf.get('kind')!r} invalid")
                fk = cf.get("key")
                if fk in field_keys:
                    errors.append(f"{bucket}.{key}: duplicate custom field key {fk!r}")
                elif fk:
                    field_keys.add(fk)
                if cf.get("kind") == "enumeration" and not (cf.get("enumValues") or "").strip():
                    warnings.append(f"{bucket}.{key}.{fk}: enumeration custom field without enumValues")

            if bucket == "buttons":
                actions = item.get("clickActionType")
                if not isinstance(actions, list) or not actions:
                    errors.append(f"buttons.{key}: clickActionType must be a non-empty list")
                else:
                    for a in actions:
                        if a not in CLICK_ACTIONS:
                            errors.append(f"buttons.{key}: unknown click action {a!r}")
                    needs_items = any(a in ITEM_BEARING_ACTIONS for a in actions)
                    if needs_items and "requiredItemsCount" not in item:
                        warnings.append(f"buttons.{key}: {ITEM_BEARING_ACTIONS} usually carry requiredItemsCount")
                    if "custom" in actions and not item.get("customCtaNames"):
                        errors.append(f"buttons.{key}: action 'custom' requires a non-empty customCtaNames")
                    if item.get("customCtaNames") and "custom" not in actions:
                        warnings.append(f"buttons.{key}: customCtaNames present but 'custom' is not offered")

            if bucket == "customs" and item.get("kind") not in KINDS:
                errors.append(f"customs.{key}: kind {item.get('kind')!r} invalid")

    if seen_index:
        expected = set(range(len(seen_index)))
        if set(seen_index) != expected:
            warnings.append("indexes are not a dense 0..N-1 range")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# --------------------------------------------------------------------------
# match — reuse an existing template instead of minting a new one
# --------------------------------------------------------------------------
# One template is meant to serve many in-apps: if a game already has a
# template whose slots cover everything the mockup needs (the boxed
# one_cta_predefined usually does for single-CTA offers), the right deliverable
# is "configure an in-app on template X", not a new template. The matcher is
# deterministic: same analysis + same templates -> same verdicts.

MATCH_PARTIAL_THRESHOLD = 0.5  # below this coverage a template is a "no"


def _analysis_needs(analysis):
    """Distill the analysis into matchable needs, one per real element."""
    needs = []
    skipped = []
    for el in analysis.get("elements") or []:
        role = el.get("role")
        if role in CLIENT_RENDERED:
            continue
        spec = ROLES.get(role)
        if spec is None:
            skipped.append(role)
            continue
        bucket = el.get("bucket") or spec["bucket"]
        need = {
            "role": role,
            "bucket": bucket,
            "key_hint": _slug(el.get("suggested_key") or role, bucket[:-1]),
        }
        if bucket == "buttons":
            actions, source = _infer_actions(role, el.get("observed_text"), el.get("click_action_types"))
            need["actions"] = actions
            # A specific inference (wording/explicit) is a hard requirement;
            # a role-default menu just means "the operator will pick one".
            need["actions_strict"] = source in ("explicit", "wording", "price-mark")
        if bucket == "customs":
            kind = el.get("kind") or spec.get("kind") or "string"
            need["kind"] = kind if kind in KINDS else "string"
        needs.append(need)
    return needs, skipped


def _slot_score(need, slot):
    """Compatibility score of one need against one free template slot.
    None = incompatible; higher = better."""
    score = 0
    if need["key_hint"] == slot.get("key"):
        score += 10
    if need["bucket"] == "buttons":
        menu = slot.get("clickActionType") or []
        overlap = [a for a in need["actions"] if a in menu]
        if need["actions_strict"]:
            if len(overlap) != len(need["actions"]):
                return None
        elif not overlap:
            return None
        score += len(overlap)
    if need["bucket"] == "customs":
        if need["kind"] != slot.get("kind"):
            return None
        score += 1
    return score


def match_templates(analysis, templates):
    """Score every template as a reuse candidate for this analysis."""
    needs, skipped = _analysis_needs(analysis)
    feature_type = (analysis.get("feature") or {}).get("type") or "standard"
    if feature_type not in FEATURE_TYPES:
        feature_type = "standard"

    results = []
    for tpl in templates:
        key = tpl.get("key") or "<unknown>"
        entry = {
            "template_key": key,
            "template_id": tpl.get("id"),
            "template_status": tpl.get("status"),
        }
        if not all(isinstance(tpl.get(b), list) for b in BUCKETS):
            entry.update(verdict="no", reason="summary record — fetch the full template via `get` before matching")
            results.append(entry)
            continue
        if (tpl.get("featureType") or "standard") != feature_type:
            entry.update(
                verdict="no",
                reason=f"feature type mismatch: mockup needs {feature_type!r}, template is {tpl.get('featureType')!r}",
            )
            results.append(entry)
            continue

        free = {b: list(tpl.get(b) or []) for b in BUCKETS}
        mapping, missing = [], []
        for need in needs:
            best, best_score = None, -1
            for slot in free[need["bucket"]]:
                score = _slot_score(need, slot)
                if score is not None and score > best_score:
                    best, best_score = slot, score
            if best is None:
                missing.append({"role": need["role"], "bucket": need["bucket"]})
            else:
                free[need["bucket"]].remove(best)
                mapping.append({"role": need["role"], "bucket": need["bucket"], "slot": best["key"]})

        # Slots the mockup does not use are free to leave unconfigured — unless
        # the template forbids hiding them, in which case they will render
        # anyway and the design will not look like the mockup. Old records
        # sometimes omit canBeHidden entirely and the omission is ambiguous
        # (the boxed One CTA omits it on both its un-hideable CTA and its
        # hideable background) — surface those as a warning, not a veto.
        leftover_required = []
        leftover_unknown = []
        for b in BUCKETS:
            for s in free[b]:
                if s.get("canBeHidden") is False:
                    leftover_required.append({"bucket": b, "slot": s["key"]})
                elif "canBeHidden" not in s:
                    leftover_unknown.append({"bucket": b, "slot": s["key"]})
        unused = sum(len(free[b]) for b in BUCKETS) - len(leftover_required) - len(leftover_unknown)

        coverage = (len(mapping) / len(needs)) if needs else 1.0
        if not missing and not leftover_required:
            verdict = "reuse"
        elif coverage >= MATCH_PARTIAL_THRESHOLD:
            verdict = "partial"
        else:
            verdict = "no"
        entry.update(
            verdict=verdict,
            coverage=round(coverage, 3),
            mapping=mapping,
            missing=missing,
            leftover_required_slots=leftover_required,
            leftover_unknown_hideability=leftover_unknown,
            unused_optional_slots=unused,
        )
        results.append(entry)

    rank = {"reuse": 0, "partial": 1, "no": 2}
    results.sort(key=lambda r: (rank[r["verdict"]], -(r.get("coverage") or 0.0)))
    best = results[0] if results and results[0]["verdict"] != "no" else None
    return {
        "needs_count": len(needs),
        "skipped_roles": skipped,
        "feature_type": feature_type,
        "results": results,
        "best": best,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _read_json(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _emit(obj, out=None):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def cmd_roles(args):
    grouped = {b: {} for b in BUCKETS}
    for role, spec in ROLES.items():
        entry = {"hint": spec["hint"]}
        if spec["bucket"] == "texts":
            entry["default_custom_fields"] = ["text_color"] + list(spec.get("extra_fields") or [])
        if "needs_confirmation" in spec:
            entry["ambiguous"] = spec["needs_confirmation"]
        if "actions" in spec:
            entry["default_click_actions"] = spec["actions"]
        if "custom_cta_names" in spec:
            entry["default_custom_cta_names"] = spec["custom_cta_names"]
        if "kind" in spec:
            entry["kind"] = spec["kind"]
        grouped[spec["bucket"]][role] = entry
    _emit(
        {
            "schema_version": SCHEMA_VERSION,
            "roles_by_bucket": grouped,
            "client_rendered_roles": CLIENT_RENDERED,
            "click_action_types": list(CLICK_ACTIONS),
            "custom_kinds": list(KINDS),
            "custom_field_kinds": list(FIELD_KINDS),
            "feature_types": list(FEATURE_TYPES),
            "mission_field_scopes": list(MISSION_FIELD_SCOPES),
        }
    )
    return 0


def cmd_schema(args):
    _emit(
        {
            "schema_version": SCHEMA_VERSION,
            "description": "Layout analysis produced by the vision pass and consumed by `build`.",
            "shape": {
                "schema_version": "1.0",
                "source_image": {"path": "str", "width": "int", "height": "int"},
                "template": {"suggested_name": "str", "suggested_key": "str", "description": "str"},
                "feature": {
                    "type": "standard | mission | milestone",
                    "confidence": "0.0-1.0",
                    "evidence": "str — what on the image justifies this",
                    "detected": {
                        "mission_count": "int (mission only)",
                        "set_count": "int (mission only)",
                        "layout": "mission only: 'sequential' when steps render locked/padlocked, else 'parallel'",
                        "progress_bar": "mission only: false when NO combined bar is visible on the mockup",
                        "milestone_count": "int (milestone; for mission = markers on the combined bar -> maxMilestones)",
                        "completion_actions": "mission: CTA actions readable on task/claim controls (list of click actions)",
                        "main_actions": "milestone: actions readable on the bar's main CTA during progression",
                        "milestone_actions": "milestone: actions readable on marker/claim buttons",
                    },
                },
                "elements": [
                    {
                        "role": "one of the keys from `roles`",
                        "suggested_key": "snake_case, optional — derived from role when absent",
                        "suggested_name": "human label, optional",
                        "bbox": {"x": "0..1", "y": "0..1", "w": "0..1", "h": "0..1"},
                        "observed_text": "text visible on the element, optional",
                        "click_action_types": ["buttons only, optional — overrides inference"],
                        "kind": "customs only: string|numeric|boolean|enumeration",
                        "confidence": "0.0-1.0",
                        "notes": "becomes the element description",
                    }
                ],
                "unsupported": [
                    {
                        "what": "the mechanic you can see, in the designer's terms",
                        "why": "which part of the Kinoa template model cannot express it",
                        "bbox": "optional, where it sits on the image",
                    }
                ],
            },
            "notes": [
                "bbox is normalised to the image, origin top-left.",
                "Indexes are assigned by `build` in reading order — never send them.",
                "Unknown roles are reported under report.unmapped, never dropped silently.",
                "`unsupported` is for mechanics the model cannot express at all — a serpentine "
                "deal chain, a hidden-count sequence, a minigame. Do not force these into "
                "elements; name them here and let the portable part of the mockup build.",
                "`unsupported` entries may come from a textual brief as well as the image — "
                "backend mechanics (price escalation, eligibility cohorts) have no bbox; omit it.",
                "When a milestone/mission count is deliberately hidden from the player, OMIT "
                "detected.*_count rather than fabricate a number — the builder defaults sanely.",
            ],
        }
    )
    return 0


def cmd_build(args):
    analysis = _read_json(args.analysis)
    payload, report = build_payload(
        analysis,
        game_id=args.game_id,
        name=args.name,
        key=args.key,
        description=args.description,
    )
    validation = validate_payload(payload)
    _emit({"ok": validation["ok"], "payload": payload, "report": report, "validation": validation}, args.out)
    return 0 if validation["ok"] else 1


def cmd_validate(args):
    payload = _read_json(args.payload)
    result = validate_payload(payload)
    _emit(result)
    return 0 if result["ok"] else 1


def cmd_match(args):
    analysis = _read_json(args.analysis)
    raw = _read_json(args.templates)
    templates = raw.get("list") if isinstance(raw, dict) else raw
    if not isinstance(templates, list):
        _emit({"ok": False, "error": "--templates must be a JSON array of full template records (or a {list: []} wrapper)"})
        return 1
    result = match_templates(analysis, templates)
    result["ok"] = True
    _emit(result, args.out)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("roles", help="Print the role vocabulary for the vision prompt.").set_defaults(func=cmd_roles)
    sub.add_parser("schema", help="Print the layout-analysis contract.").set_defaults(func=cmd_schema)

    p_build = sub.add_parser("build", help="Layout analysis -> template payload.")
    p_build.add_argument("--analysis", required=True, help="Path to the analysis JSON, or '-' for stdin.")
    p_build.add_argument("--game-id", help="Game UUID to stamp onto the payload.")
    p_build.add_argument("--name", help="Override the template name.")
    p_build.add_argument("--key", help="Override the template key.")
    p_build.add_argument("--description", help="Override the template description.")
    p_build.add_argument("--out", help="Also write the result to this path.")
    p_build.set_defaults(func=cmd_build)

    p_val = sub.add_parser("validate", help="Validate a template payload.")
    p_val.add_argument("--payload", required=True, help="Path to the payload JSON, or '-' for stdin.")
    p_val.set_defaults(func=cmd_validate)

    p_match = sub.add_parser("match", help="Score existing templates as reuse candidates for an analysis.")
    p_match.add_argument("--analysis", required=True, help="Path to the analysis JSON, or '-' for stdin.")
    p_match.add_argument("--templates", required=True, help="JSON array of FULL template records (fetch each via the dashboard helper's `get`).")
    p_match.add_argument("--out", help="Also write the result to this path.")
    p_match.set_defaults(func=cmd_match)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
