# dev/ — developer tooling & corpus (not shipped)

Nothing under `dev/` is part of the `kinoa-dashboard` plugin — the marketplace
entry points at `plugin/` only. This tree exists for developing and evaluating
`kinoa-inapp-template-from-image`.

## Layout

**Committed** (safe to distribute — the marketplace clones the whole repo to
client machines):

| Path | What |
|---|---|
| `preview_gallery.py` | Renders a browsable gallery of confirm pages from a directory of runs — the review/feedback vehicle: run the skill against real popups, point this at the runs, share the self-contained HTML. |
| `corpus/one-cta/` | The canonical fixture: Kinoa's own One CTA tip image + its golden analysis. The portable eval cases reference the image path — do not move it. A build.json is derived on demand: `inapp_template_build.py build --analysis …`. |

**Local-only** (git-ignored — derived from third-party games' offer designs;
lives only on the maintainer's machine):

| Path | What |
|---|---|
| `corpus/manifest.json` + `corpus/index_corpus.py` | Index of the real-offer mockup corpus (75 offers / 185 PNGs, 8 games) under `~/Documents/Kinoa/InAppTemplates/…`, and the script that rebuilds it. |
| `corpus/runs/<slug>/` | 16 completed vision-pass results (`analysis.json` + `build.json`), one simple + one complex offer per game. |
| `corpus/triage-notes.md` | Raw findings from the first corpus run; everything durable was distilled into the skill's references and evals. |
| `corpus/gallery/` | **Generated.** Regenerate any time: |

```bash
python3 dev/preview_gallery.py --runs dev/corpus/runs --out dev/corpus/gallery
```

## Extending the corpus

The 16 runs cover 2 offers per game. To analyse more, batch the remaining
manifest entries and run the Phase 2 prompt from
`plugin/skills/kinoa-inapp-template-from-image/SKILL.md` against each offer
(cheap model tier is fine — the analyses in `runs/` came from Sonnet), then
re-run the gallery. Keep `analysis.json`/`build.json` pairs in `runs/<slug>/`.
