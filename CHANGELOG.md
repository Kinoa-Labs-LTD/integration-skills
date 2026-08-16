# Changelog

All notable changes to the `kinoa-dashboard` plugin.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/spec/v2.0.0.html). Consumers receive an update **only when `version` in [`plugin/.claude-plugin/plugin.json`](plugin/.claude-plugin/plugin.json) changes** — bump it (and add an entry here) as the final commit of every release PR, then tag the release commit on `main` as `vX.Y.Z`.

## [Unreleased]

### Added
- Auto-pagination for every listing endpoint across the four dashboard helpers (`kinoa-dashboard-event`, `kinoa-dashboard-player-fields`, `kinoa-dashboard-feature-settings`, `kinoa-dashboard-resource-template`). `--rows` is now the page size, not a global limit: when the server reports more records (`totalCount`) than one page holds, the next pages are fetched and merged, so the printed `response` always carries the full listing. The output gains `pages_fetched`, plus `truncated: true` when the merge had to stop early (a no-progress page before `totalCount`, or the page-safety cap) and `count_mismatch: true` when it assembled more elements than the final `totalCount` (overlapping/shifting page windows); a non-2xx page fails closed (`ok: false` + `failed_page`) — a partial merge is never presented as complete. `kinoa-dashboard-resource-template list` keeps a legacy single-page mode via an explicit `--page N`.

### Changed
- The SDK sync planner's `listing_truncated` fail-closed exit is now a backstop: with auto-paginating helpers, a `totalCount`/`elements` gap signals a stale or hand-assembled listing file, and the guidance is to re-run the fetch, not to raise `--rows`. The planner additionally honors the helper's own flags — a listing carrying `truncated: true` / `count_mismatch: true` exits 2 with `listing_unreliable`.
- Workflow SKILL.md truncation guards rewritten accordingly (player-fields, events, feature-settings, resource-templates syncs + SDK dashboard sync troubleshooting).

## [1.0.0] — 2026-07-31

First pinned version. Everything below previously shipped unversioned (every `main` commit was a release).

### Added
- API-integration workflows (`kinoa-api-integration` orchestrator): credential setup (`kinoa-init`), player-fields sync, open-session runtime helper, event sync, feature-settings sync, resource-template registration, CSV→schema inference (`kinoa-csv-schema-infer`).
- Dashboard admin CLIs: `kinoa-dashboard-event`, `kinoa-dashboard-player-fields`, `kinoa-dashboard-feature-settings`, `kinoa-dashboard-resource-template`.
- SDK-mode dashboard sync (`kinoa-sdk-dashboard-sync`): consumes `kinoa-dashboard-manifest.json`, mirrors events / player fields / feature settings / resource templates onto the Dashboard; never deletes dashboard entities.
- Offline unit-test suite (`tests/`), including the boilerplate-consistency drift guard for the duplicated helper boilerplate.
