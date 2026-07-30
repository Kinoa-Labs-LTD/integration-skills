# integration-skills

Kinoa marketplace + the `kinoa-dashboard` plugin.

- `plugin/` — the DISTRIBUTED plugin (marketplace entry points here; nothing outside it ships).
- `tests/` — dev-only: unit suite + jsdom interaction harness (`python3 -m unittest discover tests`).
- `.claude-plugin/marketplace.json` — the marketplace manifest.

Dev cache substitution: `rsync -a --delete --exclude .git plugin/ ~/.claude/plugins/cache/kinoa/kinoa-dashboard/*/`
