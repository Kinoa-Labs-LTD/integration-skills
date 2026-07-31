# Changelog

All notable changes to the `kinoa-dashboard` plugin.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/spec/v2.0.0.html). Consumers receive an update **only when `version` in [`plugin/.claude-plugin/plugin.json`](plugin/.claude-plugin/plugin.json) changes** — bump it (and add an entry here) as the final commit of every release PR, then tag the release commit on `main` as `vX.Y.Z`.

## [1.0.0] — 2026-07-31

First pinned version. Everything below previously shipped unversioned (every `main` commit was a release).

### Added
- API-integration workflows (`kinoa-api-integration` orchestrator): credential setup (`kinoa-init`), player-fields sync, open-session runtime helper, event sync, feature-settings sync, resource-template registration, CSV→schema inference (`kinoa-csv-schema-infer`).
- Dashboard admin CLIs: `kinoa-dashboard-event`, `kinoa-dashboard-player-fields`, `kinoa-dashboard-feature-settings`, `kinoa-dashboard-resource-template`.
- SDK-mode dashboard sync (`kinoa-sdk-dashboard-sync`): consumes `kinoa-dashboard-manifest.json`, mirrors events / player fields / feature settings / resource templates onto the Dashboard; never deletes dashboard entities.
- Offline unit-test suite (`tests/`), including the boilerplate-consistency drift guard for the duplicated helper boilerplate.
