# integration-skills

Kinoa marketplace + the `kinoa-dashboard` plugin.

- `plugin/` — the DISTRIBUTED plugin (marketplace entry points here; nothing outside it ships).
- `tests/` — dev-only: unit suite + jsdom interaction harness (`python3 -m unittest discover tests`).
- `.claude-plugin/marketplace.json` — the marketplace manifest.
- Versioning: consumers update **only when `version` in `plugin/.claude-plugin/plugin.json` is bumped** (never set it in `marketplace.json` — `plugin.json` silently wins). Bump + `CHANGELOG.md` entry = final commit of a release PR; tag the release commit `vX.Y.Z`.

Dev cache substitution: `rsync -a --delete --exclude .git plugin/ ~/.claude/plugins/cache/kinoa/kinoa-dashboard/*/`
