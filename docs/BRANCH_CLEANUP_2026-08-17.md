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

## Deleted on origin — merged tree identical to main

Restore with: `git push origin <sha>:refs/heads/<name>`. The objects are still in
this clone, so a deleted remote branch is one push from being back.
No branch that headed an OPEN pull request is in this table.

| branch | tip | last commit |
|---|---|---|
| `feat/p0-r1-e1-v1` | `df0a0bd` | 2026-08-07 |
| `fix/durable-ledger-fence` | `90b4c65` | 2026-08-07 |
| `fix/kill-log-smoke-selectors` | `f1ccd0d` | 2026-08-07 |
| `ship/site-spec-3-storefront` | `0555434` | 2026-08-08 |
| `ship/engine-experiments` | `41d3477` | 2026-08-08 |
| `ship/hhem-experiments` | `c408d0f` | 2026-08-08 |
| `fix/audit-lcp-instrument-and-shelf-duplicate` | `0841b8e` | 2026-08-08 |
| `chore/noncritical-chain-standardcompute-first` | `11cbab8` | 2026-08-08 |
| `fix/header-logo-refresh` | `743d264` | 2026-08-09 |
| `feat/engine-guard-scan-steering-digest` | `8edff52` | 2026-08-10 |
| `fix/storefront-numbers-reconcile` | `c8e6ed0` | 2026-08-13 |
| `fix/storefront-header-logo-filter-jump` | `2e82240` | 2026-08-14 |
| `fix/catalog-market-patch-door` | `c269599` | 2026-08-14 |
| `fix/cap-the-lead-multiple` | `f52062c` | 2026-08-15 |
| `feat/faithfulness-shadow-hhem` | `5e79448` | 2026-08-15 |
| `fix/specimen-plain-english` | `2ca08cb` | 2026-08-15 |
| `fix/pack-first-week-copy` | `a4841f9` | 2026-08-15 |
| `fix/money-provability-job-level` | `f32ba3b` | 2026-08-15 |
| `fix/audience-tile-alignment` | `f376251` | 2026-08-15 |
| `fix/sample-e2e-anchor` | `991c70e` | 2026-08-15 |
| `fix/fab-shelf-foot-e2e` | `6c2713c` | 2026-08-15 |
| `fix/unban-leverage-ecosystem` | `b3a90b4` | 2026-08-15 |
| `fix/funnel-label-fits-its-slab` | `326f68c` | 2026-08-16 |
| `fix/hero-right-column` | `4d005d4` | 2026-08-16 |
| `fix/shelf-copy-voice` | `6afa6cc` | 2026-08-16 |
| `backup/live-2026-08-16` | `3c74750` | 2026-08-16 |
| `pr/pack-pdf-anchor-doc-lint-repo-mirror` | `67a4ff2` | 2026-08-16 |
| `pr/shelf-copy-glossary` | `891ec96` | 2026-08-17 |
| `ops/dev-loop-speedups` | `413b260` | 2026-08-17 |
| `docs/ci-runner` | `3e3e0ed` | 2026-08-17 |
| `fix/thumbnail-scale-identity` | `e6c78be` | 2026-08-17 |
| `ci/seed-action-archive-cache` | `feefead` | 2026-08-17 |
| `fix/doc-lint-grades-runtime-output` | `5a3cadd` | 2026-08-17 |
| `feat/prune-branches` | `ab91aad` | 2026-08-17 |
| `ci/one-python-job` | `e47e688` | 2026-08-17 |
| `fix/live-checkout-force` | `c5d579e` | 2026-08-17 |
| `fix/main-green-2026-08-17` | `7fe75af` | 2026-08-17 |
| `salvage/live-checkout-rollforward` | `d5bf76e` | 2026-08-17 |
| `ops/backup-job-from-console` | `a43cd8f` | 2026-08-17 |
| `chore/untrack-runtime-state-2` | `63d91bf` | 2026-08-17 |
