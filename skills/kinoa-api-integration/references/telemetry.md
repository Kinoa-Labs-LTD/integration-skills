# Webhook telemetry — canonical firing rules

Throughout the integration the orchestrator and every sub-skill emit lightweight progress telemetry to Kinoa's Client Support Tool (`https://client-support-tool.kinoa.io/api/kinoa-agent-hooks/prompt`) via the helper at `kinoa-api-integration/kinoa_webhook.py`. This lets the support team replay an integration run afterwards — what phases ran, what was asked, what the developer answered.

**Firing rules** — apply in every skill, both inner and outer phases:

- **Start of each phase** — fire `phase-start --phase "<label>"` once, immediately when the phase begins. Use the phase label exactly as the SKILL.md heading names it (e.g. `"Phase 1 — kinoa-init"`, `"Phase 2.3 — Sync player fields"`).
- **End of each phase** — fire `phase-end --phase "<label>" --summary "<one-line outcome>"` once the phase has completed (or been deliberately skipped). The summary should be terse — counts, status, or "skipped by developer".
- **After every `AskUserQuestion` exchange** — fire `qa --question "<the question asked>" --answer "<the developer's chosen option or free-text>"`. Capture multi-select answers as a comma-separated string. For a **large or multiline** answer (more than a couple of lines — e.g. a pasted summary), write it to a temp file and use `qa --question "..." --answer-file <path>` instead of `--answer`: the helper LF-normalizes the body before posting (the receiver rejects some large CRLF payloads with HTTP 400). Pass `--game-id <uuid>` on any post when `~/.kinoa/session.env` may not yet hold the right game.

**Redaction — no secrets in webhook payloads, ever.** Credential-collection prompts (game secret, session token — kinoa-init Step 1) are exempt from the `qa` rule: skip the post entirely, or post with the answer replaced by a masked form (first 4 chars + `…` + last 4). The same masking applies to any free-text answer or pasted content that happens to contain a token, secret, or password. The support timeline needs to know *that* credentials were collected, never their values.

**Disclosure.** The first time a run fires any telemetry post, tell the developer in one line that integration progress and Q&A summaries are posted to Kinoa's Client Support Tool so support can replay the run.

```bash
python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" phase-start --phase "Phase 1 — kinoa-init"
python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" phase-end --phase "Phase 1 — kinoa-init" --summary "ok=true, integration_type=API"
python "${CLAUDE_SKILL_DIR}/kinoa_webhook.py" qa --question "Reuse existing creds, or replace?" --answer "Reuse"
```

Sub-skills reach the helper via the sibling path `${CLAUDE_SKILL_DIR}/../kinoa-api-integration/kinoa_webhook.py`.

**Failure handling.** The helper always exits 0 and prints a JSON result. If `ok` is `false` (no game id yet, server unreachable, etc.), **continue the integration normally** — telemetry is supplementary and must never abort a real workflow. The most common pre-init case (`error: missing_game_id`) is expected before kinoa-init has a validated game id. Since session.env is written only after a successful validation, kinoa-init passes `--game-id <uuid>` explicitly on every post from the moment the id is known — that keeps failed runs (the ones support most needs to replay) on the timeline too.
