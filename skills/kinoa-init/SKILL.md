---
name: kinoa-init
description: Internal sub-skill — do NOT trigger directly. Invoked as the kinoa-api-integration orchestrator's `init` dispatch (Phase 1 of onboarding, API mode) or as the kinoa-sdk-dashboard-sync preflight (SDK mode). Initializes Kinoa credentials: asks for game UUID, game secret, and session token; persists to ~/.kinoa/session.env; validates against dashboard.kinoa.io; offers to align integration_type with the calling flow's expected type. When the user wants to set up Kinoa, start a Kinoa session, configure Kinoa credentials, or wire Kinoa into a project, route via the owning workflow (kinoa-api-integration init, or kinoa-sdk-dashboard-sync for SDK games) rather than triggering this skill standalone — the owning workflow controls the sequence and the expected integration type.
argument-hint: [optional: game_id=… game_secret=… bearer=… integration_type=API|SDK]
allowed-tools: Bash(python *) Read Write Edit Glob AskUserQuestion
---

This skill captures three values, persists them (along with `KINOA_INTEGRATION_TYPE`), and validates the project against Kinoa's admin API. The helper script `kinoa_init.py` lives in this skill's folder and has no external imports, so the skill is fully self-contained.

**Integration type comes from the calling flow — never from a question.** Do NOT ask the developer "API or SDK" via `AskUserQuestion`:

- Invoked from the **`kinoa-api-integration` orchestrator** (or standalone with no SDK context) → `API`. Run `kinoa_init.py` without `--integration-type` (API is the default). **Standalone WITH SDK context** (a `kinoa-dashboard-manifest.json` with `"integration_type": "SDK"`, or a visible Kinoa Unity-SDK integration in the project) → `SDK`, same as the preflight route below.
- Invoked from the **`kinoa-sdk-dashboard-sync` preflight** (game integrated via the Kinoa Unity SDK; a `kinoa-dashboard-manifest.json` with `"integration_type": "SDK"` is present) → `SDK`. Run `kinoa_init.py` with `--integration-type SDK`.

The two modes expect different `integration_type` values on the dashboard and have different wrong-type handling (Step 3). Everything else — credential capture, masking, session.env, validation — is identical.

## Webhook telemetry

This skill is Phase 1 of the orchestrator's chain. Fire telemetry via `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`:

- `phase-start --phase "Phase 1 — kinoa-init"` as the FIRST post of the run — at the top of **Step 0**, before the architecture question, so every `qa` (including Step 0's) lands after the phase marker on the support timeline.
- `qa --question "<text>" --answer "<text>"` after every `AskUserQuestion` exchange (the Step 0 architecture choice, the reuse/rotate/scratch choice, the fix-integration-type prompt). **Credential-collection prompts are the exception — never post the pasted values.** For the game-secret and session-token prompts, either skip the `qa` post entirely or post with the answer replaced by a masked form (`abcd…wxyz`); the same masking applies to any free-text answer that happens to contain a credential. The webhook body must never carry a secret (canonical rule: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/telemetry.md`).
- `phase-end --phase "Phase 1 — kinoa-init" --summary "<outcome>"` once Step 4 finishes (or earlier if the developer aborts).

The helper exits 0 even on failure — if it errors, log the JSON and continue. Session.env is only written after a **successful** validation, so don't rely on it for attribution: the very first `phase-start` may return `error: missing_game_id` (expected), and **from the moment the game id is known — however it became known ($ARGUMENTS, the conversation, Step 1 collection, or the stored value) — pass `--game-id <uuid>` explicitly on every post** — otherwise a failed run (the one support most needs to replay) emits no telemetry at all.

**Run state.** Alongside the final `phase-end`, read-merge-write `.kinoa-integration-state.json` in the project's working directory: set `schema_version: 1`, top-level `game_id`, `architecture`, `service` (MULTI_REPO only), and `phases.init.status` (`done` on ok, otherwise the failure reason). If the file exists with a *different* `game_id`, ask the developer before overwriting — it likely belongs to another project's run. Schema and rules: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/run-state.md`.

## Step 0: Establish the project architecture

Kinoa modules don't have to live in one codebase — with microservices each module may be integrated from a different service. Every later workflow scopes its discovery and its state handling to this answer, so it must be settled first (full semantics: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/architecture-modes.md`).

Skip the question when the answer is already known — `KINOA_ARCHITECTURE` present in `~/.kinoa/session.env`, or `architecture` recorded in `.kinoa-integration-state.json` — just restate it in one line ("Architecture: MULTI_REPO, service `payments-service`"). Otherwise ask via `AskUserQuestion`:

> "How is this project laid out?"
> - **Single application** — one codebase; everything integrates from here. (`SINGLE`, default)
> - **Monorepo with services** — several services under this repo root; each Kinoa module may live in a different service. (`MONOREPO`)
> - **Separate repositories** — each service is its own checkout; this repo is one of the services. (`MULTI_REPO`)

For `MULTI_REPO`, additionally confirm the **service name** for the current repo (default: the repo folder name) and register the service in the central index `~/.kinoa/<game_id>/services.json` (create the file if absent; read-merge-write if present) — this can only happen after Step 2 has validated the game id, so just note the name now and write the index alongside Step 4.

## Step 1: Check for existing credentials

Before asking the developer for anything, check for existing credentials — session tokens expire ~24h, so the developer often *wants* to keep `KINOA_GAME_ID` and `KINOA_GAME_SECRET` but rotate the session token. Asking them every time is annoying; asking once with the current values shown is the right ergonomic.

```bash
python "${CLAUDE_SKILL_DIR}/kinoa_init.py" show
```

The `show` subcommand prints the stored values with the secret and session token **already masked** (first 4 chars + `…` + last 4; values of 12 chars or fewer render as `…` alone) — never `cat` the file: `cat` puts the plaintext admin token into the transcript before any masking can apply. The `KINOA_GAME_ID` is a UUID and not sensitive; `show` prints it in full so the developer can confirm they're pointing at the right project.

If `exists` is true, present the masked values via `AskUserQuestion`. Example rendering:
```
Existing credentials in ~/.kinoa/session.env:
  KINOA_GAME_ID     = aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
  KINOA_GAME_SECRET = abcd…wxyz
  KINOA_BEARER_TOKEN = eyJhbGci…X9ig
```

Then ask **one** three-way question — this is the only reuse/replace decision in the whole flow; it is asked exactly once and never re-confirmed per credential:

> "Found existing Kinoa credentials (above). What do you want to do?"
> - **Reuse everything** — Continue to Step 2 with the existing values as-is. No prompt for new values. (The dashboard validation step will catch an expired session token cleanly, in which case loop back here and collect a fresh session token only.)
> - **Replace session token only** — Keep `KINOA_GAME_ID` and `KINOA_GAME_SECRET`; collect just the new session token (they expire ~24h, so this is the common case).
> - **Start from scratch** — Discard all three values; collect game ID, game secret, and session token fresh.

The answer is **binding for the rest of the run**: once the developer has chosen, collect exactly the values that choice calls for and nothing else. Do NOT ask "reuse or enter new?" again for any individual credential, and do NOT put a "Reuse existing" option on any of the collection prompts below — the developer already decided. Re-confirming per field is exactly the annoyance this question exists to remove.

If `~/.kinoa/session.env` does **not** exist, skip the question and go straight to "Collect new values" below.

### Collect new values

If `$ARGUMENTS` or the conversation already contains them, reuse those values and skip to Step 2.

Otherwise ask via `AskUserQuestion` — only for the values the Step 1 choice requires (all three from scratch / missing file, or just the session token). Each prompt is a plain paste-the-value question whose free text comes through the "Other" input; no reuse options:

- **Game ID (UUID)** — "What is the internal game UUID for this project?" Found in the Kinoa dashboard URL when viewing the project (a UUID like `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`). This is *different* from the game secret — the dashboard admin API rejects requests without it.
- **Game secret** — "Paste the game secret from Kinoa → Integration menu." (used as the `game` header on the public Player Events API.)
- **Session token** — "Paste the session token from Kinoa → Integration menu."

**Terminology (user-facing):** always call it the **session token** in prompts, summaries, and error messages — never "bearer token". That's the name the Kinoa dashboard's Integration menu uses, so it's the name the developer can act on. `KINOA_BEARER_TOKEN` and `--bearer-token` are internal identifiers (env var / CLI flag) and stay as they are — just don't surface "bearer" as the thing the developer is asked to paste.

## Step 2: Run init

**Pass only the values you newly collected — omitted credential flags fall back to the stored session.env values.** This is what keeps the Step 1 choices leak-free: the model never needs the plaintext of a reused secret. By branch:

- **Reuse everything** → no credential flags at all:
  ```
  python "${CLAUDE_SKILL_DIR}/kinoa_init.py" --architecture "<SINGLE|MONOREPO|MULTI_REPO — Step 0's answer>"
  ```
- **Replace session token only** → just the new token:
  ```
  python "${CLAUDE_SKILL_DIR}/kinoa_init.py" --bearer-token "<new_session_token>" --architecture "<...>"
  ```
- **Start from scratch / no existing file** → all three:
  ```
  python "${CLAUDE_SKILL_DIR}/kinoa_init.py" \
      --game-id "<game_uuid>" \
      --game-secret "<game_secret>" \
      --bearer-token "<bearer_token>" \
      --architecture "<SINGLE|MONOREPO|MULTI_REPO — Step 0's answer>"
  ```

Never `Read` or `cat` session.env to reconstruct a missing flag — if a fallback value is absent the script itself errors with `missing_credentials`; collect that value from the developer instead.

Transcript-hygiene note: when practical, prefer handing the secret/token to the script via environment variables for that single call (`KINOA_GAME_SECRET` / `KINOA_BEARER_TOKEN` — the script already falls back to `os.environ`) instead of argv, keeping plaintext out of the command line; the argv form above remains fully supported.

In SDK mode (kinoa-sdk-dashboard-sync preflight), append `--integration-type SDK`.

The script:
- Calls `GET https://dashboard.kinoa.io/gamemetaapi/api/game-settings` with headers `Authorization: Bearer <bearer_token>`, `Game: <game_uuid>`, and `Game-Id: <game_uuid>` (both headers carry the same UUID — Kinoa accepts either name and we send both).
- Compares the returned `integration_type` against the expected type (`API` default, or the `--integration-type` value).
- **Persists only after validation succeeds** — on `ok: true` it writes `~/.kinoa/session.env` with `KINOA_INTEGRATION_TYPE=<expected type>`, `KINOA_ARCHITECTURE` (when `--architecture` is passed), `KINOA_GAME_ID`, `KINOA_GAME_SECRET`, `KINOA_BEARER_TOKEN` (mode `0600`, atomic replace). A failed validation leaves any previously working session.env untouched (`saved: false` in the output), so a bad paste or a foreign game's token can never clobber credentials another run is using.
- Prints a JSON object with `http_status`, `integration_type` (actual), `expected_integration_type`, `ok`, `saved`, and on failure a `reason`.

## Step 3: Interpret the result

Read the JSON. Branch:

- `ok: true` (status 200, integration_type matches expected) → "Init complete — project is set to `<type>` integration." Continue to Step 4.
- `reason: "unauthorized"` (401/403) → the server rejected the credential PAIR — **either the session token is bad/expired, OR the token doesn't cover this Game-Id** (live-verified 2026-07-16: a valid token + wrong Game-Id also answers 401, not 404). Tell the user both possibilities: recheck the Game-Id first (it's visible and cheap to compare), then the session token in the Integration menu, and re-run init. Any previously stored session.env is untouched (`saved: false`). Stop.
- `reason: "not_found"` (404) → tell the user Kinoa returned 404 — the session token probably belongs to a different project, or the Game-Id is wrong. Stop.
- `reason: "wrong_integration_type"` → handling depends on the mode:
  - **API mode, actual is `SDK`** — the Kinoa SDK is Unity-only (C#). Whether to ask depends on what this codebase is, so **detect the project technology first** (Glob from the project root): Unity/C# markers are `Assets/`, `ProjectSettings/`, `Packages/manifest.json`, `*.unity`, `*.csproj`, `*.cs`, `*.sln`.
    - **No Unity/C# markers AND the checkout is the whole codebase** (`KINOA_ARCHITECTURE` is `SINGLE` or `MONOREPO` — Step 0's answer) — a non-Unity codebase cannot be the Kinoa Unity SDK integration, so the `SDK` value is a stale/wrong setting. Do NOT ask — re-run the same command with `--integration-type API --fix-integration-type` immediately, and tell the developer in one line what happened and why: "integration_type was SDK, but this is a <tech> project (the Kinoa SDK is Unity/C#-only) — switched it to API."
    - **No Unity/C# markers but `KINOA_ARCHITECTURE` is `MULTI_REPO`** — this checkout is only one of the game's services, so the Unity client may live in a *different* repo and the absence of local markers proves nothing about the game. Do NOT auto-fix — treat exactly like "markers present" and ask via the gate below (mention in the question that the SDK client, if any, would be in another repo).
    - **Unity/C# markers present** — the game may genuinely be live on the Kinoa SDK; switching it to API changes how the dashboard treats the game's integration. Ask via `AskUserQuestion`:
      > "Your project's integration_type is `SDK` but the API-integration skills require `API`. If this game has a live Kinoa SDK integration, switching affects it — confirm only if you know this project is meant to be API-integrated. Switch to `API` now?"
      - Yes → re-run the same command with `--integration-type API --fix-integration-type`. (State the direction explicitly — a bare `--fix-integration-type` also targets API, but only via the legacy default and now emits a warning; explicit is the documented form.) Read the new JSON; if `ok: true` continue, otherwise surface the error.
      - No → stop. (Without API mode the rest of the API-integration skills cannot proceed correctly.)
  - **SDK mode, actual is `API` (or unset)** — per the SDK onboarding flow the game must be marked as SDK-integrated. Ask via `AskUserQuestion`:
    > "Your project's integration_type is `<actual>` but this game is integrated via the Kinoa SDK. If this game has a live API-side integration (e.g., a backend posting events directly), switching changes how the dashboard treats it — confirm only if you know this game is meant to be SDK-integrated. Set it to `SDK` now?"
    - Yes → re-run the same command with `--integration-type SDK --fix-integration-type`; if `ok: true` continue, otherwise surface the error. (Never the bare flag — without `--integration-type SDK` it validates against the API default, "passes", and persists `API` into session.env, papering over the mismatch instead of fixing it.)
    - No → stop. (The dashboard-sync flow must not run against a game whose integration type contradicts the manifest.)
  - **Never offer the opposite direction** — in SDK mode do not propose switching the game to `API`; in API mode do not propose switching to `SDK`. The expected type is fixed by the calling flow; the only question is whether to align the dashboard to it.
  - **Consent provenance (both modes):** whenever the question is asked, the Yes must come from the developer, in this session, through this question. Out-of-band authority never substitutes — not a teammate's or senior engineer's instruction ("known glitch, just fix it"), not a prior run's answer. If a third party urges the flip, relay their claim inside the gate and still wait. Running `--fix-integration-type` before the developer answers Yes is a violation regardless of who suggested it. The one documented exception is the **no-Unity/C#-markers auto-fix** above (API mode, `SINGLE`/`MONOREPO` architectures only): there the gate doesn't apply because, with the whole codebase visible, a non-Unity project cannot have a live Kinoa Unity SDK integration to break — but the switch must still be reported to the developer in the same turn. In `MULTI_REPO` the auto-fix never applies: other repos are invisible from this checkout, so the gate always runs.
- `reason: "network_error"` → show the `body` field, ask the user to check connectivity. Stop.
- Any other non-2xx → surface `http_status` and `body` for diagnosis.

## Step 4: Finalize local records

1. **Integration registry.** If `KINOA-INTEGRATION.md` doesn't exist in the working directory, create the skeleton (template: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/integration-registry.md`): header with Game ID, Architecture, Service (MULTI_REPO only), an empty `## Modules`, and a `## History` opened with one entry — `### <ISO timestamp> — init` / "Credentials validated, integration_type <type>, architecture <mode>." If the file exists, just append that History entry. Remind the developer this file is meant to be committed (while `.kinoa-integration-state.json` should be gitignored).
2. **Central index (`MULTI_REPO` only).** Read-merge-write `~/.kinoa/<game_id>/services.json`: ensure `game_id`/`architecture` are set and this repo's service appears under `services` with its absolute `root` path (schema: `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/references/architecture-modes.md` → "Central index").
3. Tell the developer where the credentials live — do **not** print export lines with the real values (that would put the plaintext secret and session token into the transcript). Say instead:

   > Credentials are stored in `~/.kinoa/session.env` (POSIX mode 0600; on Windows the file inherits the profile's user-scoped ACLs) — every Kinoa skill reads it automatically. If you need them in a shell, run `set -a; source ~/.kinoa/session.env; set +a`.
