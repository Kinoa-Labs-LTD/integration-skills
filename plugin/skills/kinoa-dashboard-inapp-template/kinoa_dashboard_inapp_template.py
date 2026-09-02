#!/usr/bin/env python3
"""
Kinoa Dashboard In-App Templates — manage Kinoa *in-app message templates*
(`message_templates`): the reusable skeletons behind in-app pop-ups (offers,
bundles, milestone chases, mission boards). A template declares SLOTS —
`images`, `buttons`, `texts`, `customs` — plus a `featureType`
(standard / mission / milestone) and its matching `features` block. Operators
then fill those slots in and ship many in-app messages from one template.

List templates, fetch one, create a draft, update one, and check whether a
template is still referenced by in-app messages. There is deliberately NO
delete subcommand — see below.

Self-contained: no imports from sibling skills. Reads the bearer token and
game id from ~/.kinoa/session.env (written by kinoa-init).

Base https://dashboard.kinoa.io/api/message_templates — the only supported
target, hardcoded like every other kinoa-dashboard-* helper's host (there is no
environment override). `{base}` below stands for that URL.

Key case — the `Key-Inflection: camel` header (LOAD-BEARING, NEVER REMOVE):
  The API inflects key case PER REQUEST. With no header it speaks snake_case
  (`click_action_type`, `text_limit`, `feature_type`, `tags_ids`); with
  `Key-Inflection: camel` it speaks camelCase (`clickActionType`, `textLimit`,
  `featureType`, `tagsIds`) — request bodies AND responses alike. (The variant
  `X-Key-Inflection` does nothing.) The Kinoa dashboard UI sends the header,
  which is why every browser capture is camelCase.

  This helper PINS `Key-Inflection: camel` on every request (_admin_headers), so
  one single form runs end to end: the builder's payload, the bodies posted
  here, the responses read back, and every reference doc in this repo are all
  camelCase. Payloads therefore pass through BYTE-FOR-BYTE — no case conversion
  happens anywhere in this helper.

  WARNING — this is why the header is load-bearing: drop it and the API flips
  to snake_case, a camelCase body is then parsed by a snake-expecting
  deserializer, and every case-differing field is SILENTLY DROPPED. The call
  returns 200 while the data is gone: a create whose buttons end up with no
  clickActionType at all. That was the real cause of the "silent drop" seen
  before the header was understood. Never remove it, and never hand-convert a
  payload to compensate.

GET /{id} returns the FULL stored record — buttons with clickActionType,
  textLimit, customFields, canBeHidden, backgroundImg, requiredItemsCount;
  texts with customFields. Nothing is trimmed. A record that reads back LOOKING
  sparse was written by a request that lacked the header, so those fields were
  never stored. Still prefer the confirmed payload file as the source of truth
  for updates: it is the canonical copy the builder / confirm page / validator
  understand, and it is the safe base when the stored record itself is
  incomplete (a legacy draft created without the header).

Tip images — TWO DIFFERENT TRANSPORTS (verified live on production):
  * A URL is an ordinary field: `tipImageUrl` as a plain string in the JSON
    create/update body is accepted and stored. Use --tip-image-url; it costs no
    extra call.
  * A BLOB IS NOT ACCEPTED THROUGH JSON — raw base64 and a data: URI both 500.
    The working path is a SECOND, image-only request: PATCH {base}/{id} with
    Content-Type: multipart/form-data carrying exactly ONE part —
      Content-Disposition: form-data; name="tip_image_blob"; filename="<name>"
      Content-Type: image/<ext>
      <raw bytes>
    Note the part name stays snake_case (`tip_image_blob`) even though
    Key-Inflection: camel rides along — multipart field names are not inflected.
    That PATCH is PARTIAL: it updates only the image and leaves the template
    body (buttons, texts, …) untouched. Use --tip-image-file; the content type
    comes from the file's MAGIC BYTES (png/jpeg/gif/webp), not its extension,
    and anything else is refused before a single HTTP call goes out.
  The upload fires only after the main create/update SUCCEEDED, and its outcome
  is reported as `tip_image: {mode, http_status, ok, ...}` next to the main
  result. A failed upload never masks a successful main call — the top-level
  `ok` and the exit code track the MAIN call, so check `tip_image.ok` too.

Security boundary — ADMIN surface, skill-only:
  Auth is Authorization: Bearer <token> + Game: <uuid> + Game-Id: <uuid> —
  the same admin-tier credentials as the other kinoa-dashboard-* helpers.
  NEVER embed these calls or the bearer token in application runtime code:
  the session token is admin-tier and must not ship in a game binary, config,
  or runtime request. Rendering an in-app message at runtime is the SDK's job,
  on the public surface with a game secret — this helper never touches it.

Subcommands (each makes ONE HTTP call and prints ONE JSON object:
{ http_status, ok, response | request_body, ...context }):

  list [--page N] [--rows N] [--sort-by F] [--sort-direction asc|desc]
       [--status draft|active ...]
      GET {base}?page=1&rows=20&sort_by=updated_at&sort_direction=desc
      Returns { "list": [ ...template records... ], ... }. --status is
      repeatable and emits `status[]=<value>` per value; whenever ANY --status
      is given the request also carries `selectedFilters[]=status`, which is
      what the dashboard sends to switch the status filter on (the values alone
      are ignored without it). Brackets are sent literally, matching the
      observed dashboard traffic.

  get --id ID
      GET {base}/<id> — the full stored record in snake_case: all four slot
      buckets with their config (click_action_type, text_limit, custom_fields,
      …), feature_type, features, status, game_id, timestamps. A record created
      with a camelCase body reads back looking sparse because those fields were
      never stored — that is the silent drop, not a trimmed response.

  create --payload FILE|-  [--tip-image-url URL | --tip-image-file PATH]
         [--expect-game UUID]
      POST {base} — creates the template. Server-side it lands as
      status "draft" with its own id/createdAt. The payload is the create body
      produced by
      `kinoa-inapp-template-from-image/inapp_template_build.py build`
      (name, key, description, images, buttons, texts, customs, featureType,
      features, optionally gameId/tagsIds) — camelCase, which is exactly what
      goes on the wire under Key-Inflection: camel. The only changes are the
      contract normalizations (_normalize_payload — tagsIds defaulted to [], a
      null `features` on a "standard" template sent as {}, gameId stripped);
      every other key and value passes through byte-for-byte. The body sent is
      echoed as `request_body` in the output.

  update --id ID --payload FILE|-  [--allow-referenced] [--allow-slot-removal]
         [--tip-image-url URL | --tip-image-file PATH] [--dry-run]
         [--expect-game UUID]
      PATCH {base}/<id> — FULL-BODY REPLACE semantics despite the verb: send a
      complete template body, not a sparse diff, or the omitted slots are lost.
      Same normalizations as create, no case conversion. Prefer the LOCAL
      PAYLOAD FILE as the source of truth — edit it and re-send. A `get` body is
      complete enough to edit and PATCH back, but may itself be incomplete if
      the template was written without the Key-Inflection header.

      DELIBERATELY MULTI-CALL — pre-flight GET + has-related probe + PATCH —
      because a full-body replace can silently wipe slots and a referenced
      template can break live campaigns. The guard ladder, first failure wins:
        1. system: true              -> REFUSE, no override (Kinoa's own).
        2. status != "draft"         -> REFUSE, no override. Update is a
           draft-only operation; active templates evolve via the Dashboard,
           where their dependencies are visible.
        3. availableActions omits "update" -> REFUSE, no override (the server's
           own permission signal; an active non-system template offers
           show/clone/deprecate/export_to_game/hide instead).
        4. in-app messages reference it -> REFUSE unless --allow-referenced.
           An inconclusive probe refuses the same way.
        5. the body drops stored element keys -> REFUSE unless
           --allow-slot-removal. The per-bucket added/removed keys are ALWAYS
           reported, refusal or not.
      --dry-run runs the whole ladder and prints
      { ok, dry_run, guards, slot_diff, tip_image_plan, would_send } without
      PATCHing — tip_image_plan says which image action WOULD happen (mode,
      file, size) and no image bytes are sent either.
      A --tip-image-file upload runs only after the guards passed AND the main
      PATCH succeeded.
      Refusals are serialized, never raised:
      { ok: false, reason, detail, override: "<flag>"|null, ... }, exit 1.

  has-related --id ID
      GET {base}/<id>/has_related_in_app_messages ->
      { hasRelatedInAppMessages: bool } under Key-Inflection: camel (the
      snake_case spelling is accepted as a fallback). Note the ROUTE stays
      snake_case — only payload keys inflect. True means live or historical in-app
      messages still point at this template, so its shape is load-bearing:
      changing or retiring it breaks them. The output adds a flattened
      `has_related` for easy scripting.

NO DELETE — BY DESIGN:
  The server exposes a DELETE route; this helper does not, and must not grow
  one. A template with related in-app messages must never be deleted (that
  orphans every message built from it), and the operator decision was to keep
  delete out of the tooling entirely rather than gate it behind a prompt.
  `has_related_in_app_messages` is the server-side blocker signal that makes
  the risk concrete — but even a template with no relations is not deletable
  from here. Removal is a dashboard-UI / backend-operator action, taken
  deliberately outside this tooling.

Cross-game backstop: every MUTATING subcommand (create, update) accepts
--expect-game UUID and aborts with error=session_game_mismatch (exit 2) unless
session.env's KINOA_GAME_ID equals it — guarding against a stale session from
another game creating a template on the WRONG game's dashboard.
"""

import argparse
import json
import os
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request

SESSION_DIR = os.path.expanduser("~/.kinoa")
SESSION_ENV_PATH = os.path.join(SESSION_DIR, "session.env")

MESSAGE_TEMPLATES_URL = "https://dashboard.kinoa.io/api/message_templates"

# Tip-image magic bytes -> content type. A blob is NOT accepted through the JSON
# body (raw base64 and data: URIs both 500) — it goes as a separate multipart
# PATCH, so the content type has to be sniffed here.
TIP_IMAGE_FIELD = "tip_image_blob"
TIP_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")

# The four slot buckets a template declares. Used by the update slot-loss guard:
# a key that exists in the stored record but not in the new body is a WIPE.
SLOT_BUCKETS = ("images", "buttons", "texts", "customs")

# Lifecycle values the dashboard's list filter offers. The server owns the
# lifecycle; the helper never sets `status` on a create (it lands as draft).
ALLOWED_LIST_STATUSES = ("draft", "active")


def _load_session_env():
    if not os.path.exists(SESSION_ENV_PATH):
        return
    with open(SESSION_ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key and key not in os.environ:
                os.environ[key] = value


_load_session_env()


REQUEST_TIMEOUT_SECONDS = 30


def _request(method, url, headers=None, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, raw
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason} — the request may still have been applied server-side; re-check (list/get) before retrying a mutation"
    except TimeoutError as e:
        return 0, f"Timeout: {e} — the request may still have been applied server-side; re-check (list/get) before retrying a mutation"


def _parse_json(raw):
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


BLOB_KEYS = ("tipImageBlob", "tip_image_blob")


def _summarize_blobs(obj):
    """Replace stored image blobs with a short summary, recursively.

    The server echoes the full record on every write, and a template with a tip
    image carries ~114KB of base64 in `tipImageBlob`. Emitting that verbatim is
    hostile to terminals and transcripts alike, and it is never the thing the
    operator is reading. Everything else survives untouched, so `id`, `status`
    and the slot buckets stay usable — including for the code that reads `id`
    out of a create response.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in BLOB_KEYS and isinstance(v, str):
                out[k] = f"<blob: {len(v)} chars>"
            else:
                out[k] = _summarize_blobs(v)
        return out
    if isinstance(obj, list):
        return [_summarize_blobs(v) for v in obj]
    return obj


def _response_body(raw):
    """Parsed JSON body, or the raw string when the body isn't JSON. The
    `is not None` check matters: a valid-but-falsy body ({}, [], 0, false)
    must stay parsed, not be swapped for its raw string.

    Image blobs are summarized on the way out — see _summarize_blobs. This is
    the single choke point every subcommand's echoed response passes through,
    the tip_image sub-result included."""
    parsed = _parse_json(raw)
    return _summarize_blobs(parsed) if parsed is not None else raw


def _admin_headers():
    """Admin auth for the dashboard API: bearer + BOTH game headers. `Game` and
    `Game-Id` carry the same UUID — different Kinoa controllers read different
    ones, so every admin helper sends both.

    Plus `Key-Inflection: camel`, which is LOAD-BEARING and must never be
    removed: it pins the API's per-request key case to camelCase for bodies AND
    responses, matching the builder payload and every reference doc. Without it
    the API speaks snake_case, a camelCase body hits a snake-expecting
    deserializer, and every case-differing field is silently dropped on a 200.
    This header is why no case conversion exists in this helper. (It is unique
    to this endpoint family — hence a deliberate divergence from the sibling
    helpers' _admin_headers, which is not in the boilerplate drift set.)"""
    bearer = os.environ.get("KINOA_BEARER_TOKEN")
    game_id = os.environ.get("KINOA_GAME_ID")
    missing = [k for k, v in (("KINOA_BEARER_TOKEN", bearer), ("KINOA_GAME_ID", game_id)) if not v]
    if missing:
        print(json.dumps({
            "error": "missing_credentials",
            "missing": missing,
            "hint": "Run /kinoa-init first.",
        }, indent=2))
        sys.exit(2)
    return {
        "Authorization": f"Bearer {bearer}",
        "Game": game_id,
        "Game-Id": game_id,
        # Never drop this — see the docstring. 200 + silent data loss.
        "Key-Inflection": "camel",
    }


def _guard_expected_game(args):
    """Cross-game backstop. Mirrors kinoa_dashboard_resource_template's check:
    when the caller passes --expect-game, it must equal the game the session
    credentials point at (KINOA_GAME_ID). A stale session.env left over from
    ANOTHER game would otherwise create or rewrite a template on the WRONG
    game's dashboard. Fatal, before any state-changing call. Read-only and
    flagless calls are unaffected."""
    expected = getattr(args, "expect_game", None)
    if expected is None:
        return
    expected = expected.strip()
    if not expected:
        print(json.dumps({
            "error": "empty_expect_game",
            "hint": "--expect-game was passed but empty (unset shell variable?). "
                    "Pass the literal game UUID recorded at run start.",
        }, indent=2))
        sys.exit(2)
    session_game = (os.environ.get("KINOA_GAME_ID") or "").strip()
    if expected.lower() != session_game.lower():
        print(json.dumps({
            "error": "session_game_mismatch",
            "expected_game": expected,
            "session_game": session_game or None,
            "hint": "session.env points at a different game than --expect-game. "
                    "Re-run /kinoa-init for the intended game before retrying.",
        }, indent=2))
        sys.exit(2)


def _read_payload(path):
    """Load the template body from a file or '-' (stdin).
    Returns (payload_dict_or_None, error_dict_or_None)."""
    try:
        if path == "-":
            raw = sys.stdin.read()
        else:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
    except OSError as e:
        return None, {"error": "payload_read_failed", "path": path, "message": str(e)}
    parsed = _parse_json(raw)
    if parsed is None:
        return None, {"error": "invalid_payload_json", "path": path,
                      "message": "payload must be a JSON object (template create body)"}
    if not isinstance(parsed, dict):
        return None, {"error": "invalid_payload", "path": path,
                      "message": "payload must be a JSON object, not a list or scalar"}
    return parsed, None


def _normalize_payload(payload):
    """Bring a builder payload in line with the create/update contract. This is
    the ONLY reshaping the helper does — under Key-Inflection: camel the payload
    already speaks the wire's language, so no case conversion happens and every
    other key/value passes through byte-for-byte.
    Returns a NEW dict (the caller's payload is never mutated):

    1. `tagsIds` is always present — the dashboard sends [] when no tag is
       attached, and its absence is not worth risking a 4xx over.
    2. `features: null` on a "standard" template becomes {} — the builder emits
       null (its own documented invariant), but the create contract carries an
       empty object. Non-standard feature types keep their `features.<type>`
       block untouched.
    3. `gameId` (and the snake spelling) is STRIPPED — the server derives the
       game from the Game-Id header and stamps its own gameId onto the response.
       Sending one invites a mismatch between body and header.

    Every lookup accepts BOTH spellings — camelCase is canonical, but a
    snake_case body (read back from a headerless call) normalizes identically
    rather than growing a duplicate key.
    """
    body = dict(payload)
    body.pop("gameId", None)
    body.pop("game_id", None)
    tags_key = next((k for k in ("tagsIds", "tags_ids") if k in body), None)
    if tags_key is None:
        body["tagsIds"] = []
    elif body[tags_key] is None:
        body[tags_key] = []
    feature_type = body.get("featureType", body.get("feature_type"))
    if feature_type == "standard" and body.get("features") is None:
        body["features"] = {}
    return body


def _request_bytes(method, url, headers=None, data=None):
    """Raw-bytes sibling of _request, for the multipart tip-image upload.

    Deliberately a SEPARATE function: _request is shared boilerplate that must
    stay textually identical across every helper in this repo (the drift guard
    in tests/test_boilerplate_consistency.py asserts it), and it always
    JSON-encodes its body. This one sends bytes with a caller-set Content-Type.
    """
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, raw
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"
    except TimeoutError as e:
        return 0, f"Timeout: {e}"


def _sniff_image_type(data):
    """Content type from magic bytes, or None when it is not a supported image.
    The server needs a real image/* part type, and a mislabelled extension is a
    routine mistake (a PNG named .jpg), so the bytes decide — never the name."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _resolve_tip_image(args):
    """Validate the tip-image request BEFORE any HTTP happens.
    Returns (plan_or_None, error_dict_or_None). A plan is either
    {mode: "url", url} or {mode: "blob", path, filename, content_type, data}."""
    url = getattr(args, "tip_image_url", None)
    path = getattr(args, "tip_image_file", None)
    if url:
        return {"mode": "url", "url": url}, None
    if not path:
        return None, None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, {"error": "tip_image_read_failed", "path": path, "message": str(e)}
    content_type = _sniff_image_type(data)
    if content_type is None:
        return None, {
            "error": "unsupported_tip_image_type",
            "path": path,
            "message": f"tip image must be one of {list(TIP_IMAGE_TYPES)} "
                       "(detected from magic bytes, not the file extension)",
        }
    return {"mode": "blob", "path": path, "filename": os.path.basename(path),
            "content_type": content_type, "data": data}, None


def _upload_tip_image(template_id, plan):
    """The image-only follow-up: PATCH {base}/{id} as multipart/form-data with a
    SINGLE part named `tip_image_blob`. The part name stays snake_case even
    though Key-Inflection: camel rides along — multipart field names are not
    inflected. This is a PARTIAL patch: it touches only the image and leaves the
    template body (buttons, texts, …) untouched."""
    boundary = "----KinoaTipImage" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{TIP_IMAGE_FIELD}"; '
        f'filename="{plan["filename"]}"\r\n'
        f'Content-Type: {plan["content_type"]}\r\n\r\n'
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = _admin_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    status, raw = _request_bytes(
        "PATCH", f"{MESSAGE_TEMPLATES_URL}/{template_id}",
        headers=headers, data=head + plan["data"] + tail)
    return {
        "mode": "blob",
        "filename": plan["filename"],
        "content_type": plan["content_type"],
        "bytes": len(plan["data"]),
        "http_status": status,
        "ok": 200 <= status < 300,
        "response": _response_body(raw),
    }


def _tip_image_plan_summary(plan):
    """What a --dry-run reports instead of doing the upload."""
    if plan is None:
        return None
    if plan["mode"] == "url":
        return {"mode": "url", "url": plan["url"],
                "detail": "tipImageUrl would be injected into the JSON body"}
    return {"mode": "blob", "path": plan["path"], "filename": plan["filename"],
            "content_type": plan["content_type"], "bytes": len(plan["data"]),
            "detail": "would be uploaded as a separate image-only multipart PATCH"}


def _slot_keys(record):
    """{bucket: [element keys]} for the four slot buckets of a template body or
    a stored record. Missing/malformed buckets read as empty, never raise."""
    out = {}
    for bucket in SLOT_BUCKETS:
        items = record.get(bucket) if isinstance(record, dict) else None
        keys = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("key") is not None:
                    keys.append(item["key"])
        out[bucket] = keys
    return out


def _slot_diff(current, new_body):
    """Per-bucket added/removed element keys going from the STORED record to the
    NEW body. `removed` is the dangerous direction: PATCH is a full-body
    replace, so a stored key absent from the body is silently wiped."""
    cur, new = _slot_keys(current), _slot_keys(new_body)
    removed, added = {}, {}
    for bucket in SLOT_BUCKETS:
        gone = [k for k in cur[bucket] if k not in new[bucket]]
        fresh = [k for k in new[bucket] if k not in cur[bucket]]
        if gone:
            removed[bucket] = gone
        if fresh:
            added[bucket] = fresh
    return {"added": added, "removed": removed}


def _refuse(reason, detail, override=None, **extra):
    """Serialize a guard refusal — never raise. `override` names the flag that
    would allow it, or is null when the guard is absolute."""
    out = {"ok": False, "reason": reason, "detail": detail, "override": override}
    out.update(extra)
    print(json.dumps(out, indent=2))
    return 1


def _field(record, camel, snake):
    """Read a field in either inflection. camelCase is what comes back under
    Key-Inflection: camel; snake is the headerless fallback."""
    if camel in record:
        return record[camel]
    return record.get(snake)


def cmd_list(args):
    params = [
        ("page", str(args.page)),
        ("rows", str(args.rows)),
        ("sort_by", args.sort_by),
        ("sort_direction", args.sort_direction),
    ]
    statuses = [s for s in (args.status or []) if s]
    if statuses:
        # `status[]` values alone do nothing — the dashboard turns the filter on
        # with selectedFilters[]=status, so the two always travel together.
        params.append(("selectedFilters[]", "status"))
        for s in statuses:
            params.append(("status[]", s))
    # safe="[]" keeps the brackets literal, byte-for-byte with the observed
    # dashboard request (percent-encoded would also decode, but don't diverge).
    qs = urllib.parse.urlencode(params, safe="[]")
    status, raw = _request("GET", f"{MESSAGE_TEMPLATES_URL}?{qs}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "response": _response_body(raw),
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def cmd_get(args):
    status, raw = _request("GET", f"{MESSAGE_TEMPLATES_URL}/{args.id}", headers=_admin_headers())
    print(json.dumps({
        "http_status": status,
        "ok": 200 <= status < 300,
        "id": args.id,
        "response": _response_body(raw),
    }, indent=2))
    return 0 if 200 <= status < 300 else 1


def _apply_tip_image(image, main_status, main_ok, main_response, template_id=None):
    """Post-process the tip image after the main JSON call.

    url mode needs no extra call (the field rode along in the body). blob mode
    fires the image-only multipart PATCH, but only when the main call SUCCEEDED
    — there is nothing to attach an image to otherwise. A failed upload is
    reported here and never masks the successful main call: the caller's overall
    `ok` stays the main call's.
    """
    if image is None:
        return None
    if image["mode"] == "url":
        return {
            "mode": "url",
            "url": image["url"],
            "http_status": main_status,
            "ok": main_ok,
            "detail": "tipImageUrl sent inline in the JSON body — no extra call",
        }
    if not main_ok:
        return {"mode": "blob", "ok": False, "http_status": None,
                "detail": "skipped — the main call did not succeed"}
    resolved = template_id
    if resolved is None and isinstance(main_response, dict):
        resolved = main_response.get("id")
    if not resolved:
        return {"mode": "blob", "ok": False, "http_status": None,
                "detail": "skipped — could not resolve the template id from the response"}
    return _upload_tip_image(resolved, image)


def cmd_create(args):
    payload, err = _read_payload(args.payload)
    if err:
        print(json.dumps(err, indent=2))
        return 2
    # Tip-image validation happens BEFORE any HTTP: an unreadable or non-image
    # file must not leave a created template behind.
    image, err = _resolve_tip_image(args)
    if err:
        print(json.dumps(err, indent=2))
        return 2
    body = _normalize_payload(payload)
    if image is not None and image["mode"] == "url":
        body["tipImageUrl"] = image["url"]
    status, raw = _request("POST", MESSAGE_TEMPLATES_URL, headers=_admin_headers(), body=body)
    response = _response_body(raw)
    main_ok = 200 <= status < 300
    out = {
        "http_status": status,
        "ok": main_ok,
        "request_body": body,
        "response": response,
    }
    tip = _apply_tip_image(image, status, main_ok, response, template_id=None)
    if tip is not None:
        out["tip_image"] = tip
    print(json.dumps(out, indent=2))
    # The exit code tracks the MAIN call — a template was created either way.
    # Check tip_image.ok separately for the image.
    return 0 if main_ok else 1


def cmd_update(args):
    """Guarded full-body update. Deliberately MULTI-CALL (pre-flight GET +
    has-related probe + PATCH): PATCH is a full-body replace, so an incomplete
    body silently wipes slots, and a referenced template breaks live campaigns.
    Precedent for a multi-call helper subcommand: kinoa_dashboard_resource_
    template's update (GET + merged PUT).

    The guard ladder, in order — the first failure refuses and stops:
      1. system:true          -> absolute refusal (Kinoa's own templates)
      2. status != draft      -> absolute refusal (draft-only operation)
      3. availableActions     -> absolute refusal when it omits "update"
      4. referenced by in-apps-> refusal unless --allow-referenced
      5. slot removal         -> refusal unless --allow-slot-removal
    --dry-run runs the whole ladder and reports what WOULD be sent, without
    the PATCH.
    """
    payload, err = _read_payload(args.payload)
    if err:
        print(json.dumps(err, indent=2))
        return 2
    image, err = _resolve_tip_image(args)
    if err:
        print(json.dumps(err, indent=2))
        return 2
    body = _normalize_payload(payload)
    if image is not None and image["mode"] == "url":
        body["tipImageUrl"] = image["url"]

    # ---- pre-flight: the stored record is what the guards judge against ----
    get_status, get_raw = _request(
        "GET", f"{MESSAGE_TEMPLATES_URL}/{args.id}", headers=_admin_headers())
    if not (200 <= get_status < 300):
        return _refuse("preflight_fetch_failed",
                       "could not read the template before updating it",
                       id=args.id, http_status=get_status,
                       response=_response_body(get_raw))
    current = _parse_json(get_raw)
    if not isinstance(current, dict):
        return _refuse("unexpected_template_shape",
                       "the by-id response was not a JSON object",
                       id=args.id, raw=get_raw[:500])

    name = current.get("name")
    status_value = current.get("status")
    system = current.get("system")
    actions = _field(current, "availableActions", "available_actions")
    guards = {}

    # 1. system templates are Kinoa's own — no override, ever.
    guards["system"] = {"value": system, "passed": system is not True}
    if system is True:
        return _refuse("system_template",
                       "system templates are Kinoa's own — never updated from tooling",
                       id=args.id, name=name, guards=guards)

    # 2. draft-only: an active template evolves via the Dashboard, where its
    #    dependencies are visible.
    is_draft = isinstance(status_value, str) and status_value.lower() == "draft"
    guards["status"] = {"value": status_value, "passed": is_draft}
    if not is_draft:
        return _refuse("not_draft",
                       "update is a draft-only operation; active templates evolve via the "
                       "Dashboard where dependencies are visible",
                       id=args.id, name=name, guards=guards)

    # 3. the server's own permission signal.
    actions_ok = not (isinstance(actions, list) and "update" not in actions)
    guards["available_actions"] = {"value": actions, "passed": actions_ok}
    if not actions_ok:
        return _refuse("update_not_available",
                       "the server's availableActions for this template does not include "
                       "\"update\"",
                       id=args.id, name=name, guards=guards)

    # 4. referenced by in-app messages -> overridable refusal.
    rel_status, rel_raw = _request(
        "GET", f"{MESSAGE_TEMPLATES_URL}/{args.id}/has_related_in_app_messages",
        headers=_admin_headers())
    rel_parsed = _response_body(rel_raw)
    referenced = None
    if isinstance(rel_parsed, dict):
        referenced = _field(rel_parsed, "hasRelatedInAppMessages",
                            "has_related_in_app_messages")
    if not (200 <= rel_status < 300) or not isinstance(referenced, bool):
        guards["referenced"] = {"value": None, "passed": bool(args.allow_referenced),
                                "overridden": bool(args.allow_referenced)}
        if not args.allow_referenced:
            return _refuse("reference_check_failed",
                           "could not determine whether in-app messages build on this "
                           "template; refusing rather than risk breaking live campaigns",
                           override="--allow-referenced", id=args.id, name=name,
                           http_status=rel_status, response=rel_parsed, guards=guards)
    else:
        allowed = (not referenced) or bool(args.allow_referenced)
        guards["referenced"] = {"value": referenced, "passed": allowed,
                                "overridden": bool(referenced and args.allow_referenced)}
        if referenced and not args.allow_referenced:
            return _refuse("template_referenced",
                           "in-app messages already build on this template — changing its "
                           "shape can break live campaigns",
                           override="--allow-referenced", id=args.id, name=name,
                           guards=guards)

    # 5. slot loss: the wipe scenario. Always reported, both directions.
    diff = _slot_diff(current, body)
    slots_ok = (not diff["removed"]) or bool(args.allow_slot_removal)
    guards["slot_removal"] = {"removed": diff["removed"], "passed": slots_ok,
                              "overridden": bool(diff["removed"] and args.allow_slot_removal)}
    if diff["removed"] and not args.allow_slot_removal:
        return _refuse("slot_removal",
                       "the new body drops element keys the stored template still has; "
                       "PATCH is a full-body replace, so they would be wiped",
                       override="--allow-slot-removal", id=args.id, name=name,
                       slot_diff=diff, guards=guards)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "id": args.id,
            "name": name,
            "guards": guards,
            "slot_diff": diff,
            "tip_image_plan": _tip_image_plan_summary(image),
            "would_send": body,
        }, indent=2))
        return 0

    status, raw = _request(
        "PATCH", f"{MESSAGE_TEMPLATES_URL}/{args.id}", headers=_admin_headers(), body=body)
    main_ok = 200 <= status < 300
    out = {
        "http_status": status,
        "ok": main_ok,
        "id": args.id,
        "name": name,
        "guards": guards,
        "slot_diff": diff,
        "request_body": body,
        "response": _response_body(raw),
    }
    # The image-only PATCH runs only after the guards passed AND the main PATCH
    # succeeded.
    tip = _apply_tip_image(image, status, main_ok, out["response"], template_id=args.id)
    if tip is not None:
        out["tip_image"] = tip
    print(json.dumps(out, indent=2))
    return 0 if main_ok else 1


def cmd_has_related(args):
    status, raw = _request(
        "GET", f"{MESSAGE_TEMPLATES_URL}/{args.id}/has_related_in_app_messages", headers=_admin_headers())
    parsed = _response_body(raw)
    out = {
        "http_status": status,
        "ok": 200 <= status < 300,
        "id": args.id,
        "response": parsed,
    }
    if isinstance(parsed, dict):
        # camelCase is what comes back under Key-Inflection: camel; the
        # snake_case spelling is the headerless form, kept as a fallback.
        for spelling in ("hasRelatedInAppMessages", "has_related_in_app_messages"):
            if isinstance(parsed.get(spelling), bool):
                out["has_related"] = parsed[spelling]
                break
    print(json.dumps(out, indent=2))
    return 0 if 200 <= status < 300 else 1


def main(argv):
    parser = argparse.ArgumentParser(prog="kinoa_dashboard_inapp_template", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument("--expect-game", default=None,
                       help="Cross-game backstop: abort unless session.env's KINOA_GAME_ID equals this UUID.")

    p_list = sub.add_parser("list", help="GET the template list (paged).")
    p_list.add_argument("--page", type=int, default=1, help="Page number (1-based). Default: 1.")
    p_list.add_argument("--rows", type=int, default=20, help="Page size. Default: 20.")
    p_list.add_argument("--sort-by", default="updated_at", help="Sort field. Default: updated_at.")
    p_list.add_argument("--sort-direction", default="desc", choices=("asc", "desc"),
                        help="Sort direction. Default: desc.")
    p_list.add_argument("--status", action="append", default=[], choices=ALLOWED_LIST_STATUSES,
                        help="Status filter, repeatable (draft/active). Adds selectedFilters[]=status.")
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="GET one template by id (full record).")
    p_get.add_argument("--id", required=True)
    p_get.set_defaults(func=cmd_get)

    p_cre = sub.add_parser("create", parents=[guard],
                           help="POST a new template from a builder payload (lands as draft).")
    p_cre.add_argument("--payload", required=True,
                       help="Path to the template create body JSON, or '-' for stdin.")
    p_cre.set_defaults(func=cmd_create)

    p_upd = sub.add_parser("update", parents=[guard],
                           help="PATCH a template with a FULL body (replace semantics).")
    p_upd.add_argument("--id", required=True)
    p_upd.add_argument("--payload", required=True,
                       help="Path to the FULL template body JSON, or '-' for stdin.")
    p_upd.add_argument("--allow-referenced", action="store_true",
                       help="Override the guard that refuses when in-app messages already "
                            "build on this template.")
    p_upd.add_argument("--allow-slot-removal", action="store_true",
                       help="Override the guard that refuses when the new body drops element "
                            "keys the stored template still has.")
    p_upd.add_argument("--dry-run", action="store_true",
                       help="Run every guard and report the slot diff + the body that would "
                            "be sent, without PATCHing.")
    p_upd.set_defaults(func=cmd_update)

    for p_img in (p_cre, p_upd):
        tip = p_img.add_mutually_exclusive_group()
        tip.add_argument("--tip-image-url", default=None,
                         help="Set tipImageUrl inline in the JSON body (no extra call).")
        tip.add_argument("--tip-image-file", default=None,
                         help="Attach a tip image from disk. Sent AFTER the main call as a "
                              "separate image-only multipart PATCH (a blob is rejected by the "
                              "JSON body). png/jpeg/gif/webp, detected from magic bytes.")

    p_rel = sub.add_parser("has-related",
                           help="GET whether in-app messages still reference this template.")
    p_rel.add_argument("--id", required=True)
    p_rel.set_defaults(func=cmd_has_related)

    args = parser.parse_args(argv)
    _guard_expected_game(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
