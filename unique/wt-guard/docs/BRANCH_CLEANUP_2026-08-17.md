# Branch cleanup — 2026-08-17

Restore any branch with: `git branch <name> <sha>` then `git push origin <name>`.
Nothing here is lost: every tip SHA is recorded, and the objects survive in the repo.

Deletion rule: `git merge-tree --write-tree origin/main <branch>` yielded a tree
**byte-identical to main's** — merging it would change no file. Commit COUNTS and
`git cherry` patch-ids both overstate this; rebased and squash-merged commits get new
patch-ids while the content has already landed.

Written by `scripts/prune_branches.py --fix`. origin/main at time of cleanup:
`4d24ffd71104e1299fc0f12c688cede759cf1d3b`

## Deleted — merged tree identical to main

| branch | tip | last commit |
|---|---|---|
| `store/discovery-search-and-copy-fixes` | `83114dd` | 2026-08-06 |
| `ship/e1-abort-test` | `d8cf90f` | 2026-08-08 |
| `fix/ci-minimax-key` | `f30d89f` | 2026-08-08 |
| `ship/pack-contents-count` | `91c26ae` | 2026-08-08 |
| `ship/integrate-2026-08-09` | `6125430` | 2026-08-09 |
| `wt176/engine-guard-scan-steering-digest` | `8edff52` | 2026-08-10 |
| `merge-tmp` | `d6589ab` | 2026-08-14 |
| `fix/catalog-market-patch-door` | `a7c89bf` | 2026-08-14 |
| `fix/cap-the-lead-multiple` | `f52062c` | 2026-08-15 |
| `feat/faithfulness-shadow-hhem` | `5e79448` | 2026-08-15 |
| `fix/specimen-plain-english` | `2ca08cb` | 2026-08-15 |
| `sync/main-latest` | `0e1e939` | 2026-08-15 |
| `fix/pack-first-week-copy` | `a4841f9` | 2026-08-15 |
| `fix/money-provability-job-level` | `f32ba3b` | 2026-08-15 |
| `fix/audience-tile-alignment` | `f376251` | 2026-08-15 |
| `fix/hero-right-column` | `4d005d4` | 2026-08-16 |
| `feat/back-nav-and-research-grade` | `d3a48c3` | 2026-08-16 |
| `feat/card-sub-copy-budget` | `deb28d3` | 2026-08-16 |
| `pr/pack-pdf-anchor-doc-lint-repo-mirror` | `67a4ff2` | 2026-08-16 |
| `pr/shelf-copy-glossary` | `519ce28` | 2026-08-17 |
| `fix/thumbnail-scale-identity` | `693c494` | 2026-08-17 |
| `ops/dev-loop-speedups` | `034868d` | 2026-08-17 |
| `cp-fix/pack-page-conversion` | `57abd35` | 2026-08-17 |
| `cp-ops/human-register-backfill` | `b7a50ad` | 2026-08-17 |
| `pr248` | `891ec96` | 2026-08-17 |
| `wk-fix/pack-page-conversion` | `edfff0a` | 2026-08-17 |
| `wk-ops/human-register-backfill` | `52bc371` | 2026-08-17 |
| `wk-ops/dev-loop-speedups` | `413b260` | 2026-08-17 |
| `docs/ci-runner` | `3e3e0ed` | 2026-08-17 |
| `fix/doc-lint-grades-runtime-output` | `5a3cadd` | 2026-08-17 |
| `feat/prune-branches` | `ab91aad` | 2026-08-17 |
| `ci/one-python-job` | `e47e688` | 2026-08-17 |
| `fix/live-checkout-force` | `c5d579e` | 2026-08-17 |
| `fix/main-green-2026-08-17` | `7fe75af` | 2026-08-17 |
| `fix/idle-guard-liveness` | `da33cfa` | 2026-08-17 |
| `salvage/live-checkout-rollforward` | `d5bf76e` | 2026-08-17 |
| `ops/backup-job-from-console` | `a43cd8f` | 2026-08-17 |
| `chore/untrack-runtime-state-2` | `63d91bf` | 2026-08-17 |
