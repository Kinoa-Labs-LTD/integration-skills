# Integration registry — `KINOA-INTEGRATION.md` (human-readable, committed)

The state file (`run-state.md` in this folder) is machine state for resuming; the registry is for people — a reviewer or a newly onboarded developer opens it and sees **what is integrated with Kinoa, how, and what changed over time**. It lives next to the state file and, unlike the state file, **should be committed to git** so the integration picture travels with the repo (and, in `MULTI_REPO`, lets another developer's machine rebuild the central index).

Maintain it in the same breath as the state file: whenever a workflow read-merge-writes its phase entry at a `phase-end`, also update the registry — **rewrite** that module's section under `## Modules` to the new current state, and **append** one entry to `## History` (never edit or delete existing History entries). `kinoa-init` creates the skeleton if the file is absent; any workflow that finds it missing bootstraps it the same way.

Template:

```markdown
# Kinoa Integration Registry

- **Game ID:** `<uuid>`
- **Architecture:** SINGLE | MONOREPO | MULTI_REPO
- **Service:** `<name>` <!-- MULTI_REPO only: the service this repo implements -->

## Modules

### Player fields — done
- **Service:** `services/player-svc` <!-- MONOREPO: service_root; omit in SINGLE -->
- **Generated:** `services/player-svc/src/kinoa/KinoaPlayerState.kt`
- **Summary:** 12 fields active (9 predefined, 3 custom)

### Events — in progress
- …

### Resources — done
- **Service:** `services/shop-svc` <!-- MONOREPO: service_root; omit in SINGLE -->
- **Generated:** `services/shop-svc/Assets/Kinoa/KinoaResources.cs`
- **Summary:** 8 resource templates ACTIVE (6 created, 2 already active); 1 left DRAFT

## History
<!-- append-only, newest last; one entry per completed phase / sync run -->

### 2026-07-06T14:32Z — player_fields (`services/player-svc`)
Activated 9 predefined fields, created 3 custom (`vip_tier`, `guild_id`, `ab_bucket`); generated KinoaPlayerState.

### 2026-07-06T15:10Z — events (`services/analytics-svc`)
Published 3 events, created 2 custom; player_state strategy: DIFF; session_start auto-fires.
```

Keep History entries terse and factual — counts, names, decisions, artifact paths. They are the change log the client asked to be able to audit later; narration belongs in the conversation, not here.
