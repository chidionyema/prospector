# Branch cleanup — 2026-08-09

Restore any branch with: `git branch <name> <sha>` then `git push origin <name>`.
Nothing here is lost: every tip SHA is recorded, and the objects survive in the repo.

Deletion rule: a branch is deleted only when `git merge-tree --write-tree origin/main <branch>`
yields a tree **byte-identical to main's** — merging it would change no file. Commit COUNTS and
`git cherry` patch-ids both overstate this: `ship/money-rail-ops` reports 7 commits not in main
and a three-dot diff calls it "14 files, 975 insertions", yet its merged tree equals main's
exactly. Rebased commits get new patch-ids; the content had already landed.

main at time of cleanup: `6125430656e0f5d76164df8c862b2af6c8c1cfcc`

## Deleted — merged tree identical to main

| branch | tip | last commit |
|---|---|---|
| `docs/ledger-2026-08-08` | `96864a7` | 2026-08-08 |
| `feat/generation-quality-tier12` | `05d0644` | 2026-08-08 |
| `fix-api-deploy-config` | `cff8f1e` | 2026-08-01 |
| `fix-api-image-editorconfig` | `3c44812` | 2026-08-01 |
| `fix-email-webbaseurl-config` | `c16f667` | 2026-08-01 |
| `fix-node-modules-symlink` | `58fba75` | 2026-08-01 |
| `fix/copy-register-leak` | `463c35e` | 2026-08-08 |
| `fix/declare-bundle-bonus-files` | `493e90c` | 2026-08-08 |
| `fix/em-dash-price-viewed` | `40c180a` | 2026-08-05 |
| `fix/nodash-third-copy` | `7063f12` | 2026-08-08 |
| `fix/pack-copy-documents-not-files` | `1353d35` | 2026-08-08 |
| `fix/pack-page-brainstorm-middle-grounds` | `becb758` | 2026-08-08 |
| `fix/packmark-lead-card-axis` | `b078d41` | 2026-08-08 |
| `og-image-tracing-fix` | `d93691a` | 2026-08-01 |
| `ship/money-rail-ops` | `7a86ed2` | 2026-07-31 |
