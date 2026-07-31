# Storefront work — where every piece actually lives

Written 2026-07-31. **This file is a map, not a status.** It says where work lives, not whether it
is deployed. For deployed state, run the probe; for merge state, run:

    gh pr list --repo chidionyema/prospector --state open

The reason this file exists: storefront work had spread across three open PRs, one local branch,
and one uncommitted working tree, and the commit log actively misled about which was which. Reading
`git log` gave the wrong answer three times in a row. The commands below are the ones that gave the
right answer.

## The trap: commit count is not content

`store-analytics-2026-07-31` reads as **6 commits ahead of main**. Five of them are already shipped:
`main` carries `106387a store: … (#6)`, a **squash** merge, so the individual commits it replaced
still look unmerged by ancestry.

    git log --oneline origin/main..store-analytics-2026-07-31   # 6 commits  -> MISLEADING
    git diff --stat origin/main...store-analytics-2026-07-31    # 31 files   -> MISLEADING (merge-base)
    git diff --stat origin/main  store-analytics-2026-07-31     # 13 files   -> the truth

**Use the two-dot form against a squash-merged history.** Three-dot diffs from the merge base, which
is before the squash, so it re-reports work that already shipped.

## Shipped

`106387a (#6)` — honest failure states, the £1 delivery probe, first-party analytics,
hidden-from-catalogue. Plus `ec8b954 (#5)` Dependabot, `a547fc8 (#4)` filters + deploy + smoke.

## Open PRs

| PR | Branch | Contains |
|---|---|---|
| **#10** | `consolidate-storefront` | **Supersedes #7, #8, #9** — all three merged into one deploy |
| #7 | `analytics-no-device-storage` | Drops the sessionStorage visitor id; server-side dedup replaces `trackOnce`. Migration `DropAnalyticsSessionId`. |
| #8 | `sitemap-pack-urls` | `sitemap.xml` gains `/sample` + one entry per live pack |
| #9 | `waitlist-second-placement` | Waitlist placement on `/sample`; consent wording centralised |
| — | `rescue-delivery-verifier` | `verify_delivery.py` + its `.gitignore` rule (see below). **Prepared, not yet committed** — blocked by the POPDD chain artifact described under "Known pre-existing failures". |
| #3 | dependabot js-yaml | Failing checks, untouched |

#7, #8 and #9 touch **disjoint files** and all three pairs merge clean — which is why bundling them
was safe. Reproduce:

    { git diff --name-only origin/main origin/analytics-no-device-storage
      git diff --name-only origin/main origin/sitemap-pack-urls
      git diff --name-only origin/main origin/waitlist-second-placement; } | sort | uniq -d
    # no output = zero overlap

If #10 merges, close #7, #8 and #9 — do not merge them as well.

## What was stranded, and why it nearly vanished

`verify_delivery.py` was committed to `store-analytics-2026-07-31` and then **left out** of the PR
that carried the rest of that branch. It existed on one local branch and nowhere else; deleting the
branch would have lost it with no trace. PR #11 rescues it.

Its `.gitignore` rule travels with it and is **not** cosmetic: `.delivery-proof/` holds live
entitlement grant tokens, which are bearer credentials for a paid download. The script without the
rule invites committing them.

Check for this class of problem — files committed on a branch but absent from its PR:

    git diff --name-only origin/main store-analytics-2026-07-31
    git diff --name-only origin/main origin/analytics-no-device-storage
    # anything in the first list and not the second is in no PR

## Not in git at all

The shared tree `/Users/chidionyema/Documents/code/prospector` (on `store-analytics-2026-07-31`)
holds uncommitted work belonging to whoever is working there — an ops/reconciliation feature:
`OPERATIONS.md`, `scripts/storeops`, `data/reconcile-exceptions.json`,
`tests/unit/test_reconcile_exceptions.py`, plus modified `reconcile_orders.py`,
`verify_delivery.py`, `build_probe_content.py` and four root docs. `storeops` and `OPERATIONS.md`
are **not on main**.

This is the highest-risk category on the page: it exists only as files on one disk. It is not mine
to commit, and `git add -A` in that tree is a hazard, not a shortcut.

## The deploy gap — the thing most likely to bite

**`deploy-web.yml` is the only workflow that deploys anything, and it deploys the web app only**
(`store_platform/src/Store.Web/**` → `deploy_web.sh`). There is an `api.fly.toml`, but no workflow
and no `deploy_api.sh` reference it.

    grep -l "flyctl deploy" .github/workflows/*.yml   # deploy-web.yml, and only that

So **merging API changes does not deploy them.** Concretely, for #7/#10: merging ships
`analytics.ts` (which deletes the client-side `trackOnce` localStorage dedup) while leaving the
unique index that replaces it unapplied until someone deploys the API by hand. Request-shape skew
is safe by design — `System.Text.Json` drops unmapped members, so older bundles still post fine —
but dedup **coverage** is not: a reloaded success page can double-count `checkout_completed` until
the API ships. Analytics only; no money path.

Anything touching `Store.Api` or `Store.Catalog` needs a deliberate API deploy. Migrations run at
startup via `MigrateAsync`, so the deploy is when the schema changes.

## Known pre-existing failures — do not attribute these to new work

- `npm run lint` — 2 errors on `main`: `pages/pack/[id].tsx:63` (setState in effect) and
  `lib/__tests__/stripeReachable.test.ts:41` (`@ts-expect-error`).
- `StorageWiringTests.Download_url_honours_a_custom_ttl` — timing flake. Asserts the presigned
  `X-Amz-Expires` is within one second (`actual == expected || actual == expected - 1`), but the
  full suite under load loses two, giving `598, expected 600`. Passes 3/3 in isolation. Worth
  widening the tolerance; it is not a regression.
- The POPDD pre-commit gate runs the **full pytest suite** on any staged `.py/.ts/.js/.cs` and
  caches nothing, so commits touching source take minutes. In a fresh worktree it fails with
  `sh: .venv/bin/python: No such file or directory` — the venv lives in the primary checkout.
  Point it at the real one rather than reaching for `--no-verify`:

      export POPDD_VERIFY_CMD="/Users/chidionyema/Documents/code/prospector/.venv/bin/python scripts/popdd_verify.py"

  Do not symlink `.venv` into a worktree: `.gitignore` has `.venv/` with a trailing slash, which
  does not match a symlink, so it lands untracked-but-unignored and one `git add -A` from committed.

  Worse, the gate cannot pass in a fresh worktree **even when the suite is green**. `.lux/` is
  gitignored, so a new worktree mints its own POPDD identity and its own receipt chain, and the
  chain fails signature validation from its very first entry. Verdict and cause, read-only:

      .venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); from popdd_agent import PopddAgent; print(PopddAgent.at_path('.').verify_chain())"
      # primary  -> {'valid': True,  'total': 57}
      # worktree -> {'valid': False, 'total': 5, 'broken_at': 0, 'reason': 'signature invalid at 0'}

  So a worktree commit touching `.py/.ts/.js/.cs` runs the full suite for minutes, reports
  `Test verdict: PASS (932 passed, 0 failed)` and `Chain valid: False`, and is blocked anyway.
  Do not "fix" this by deleting receipts or re-signing — that is the tampering the chain exists to
  detect. Either commit source from the primary checkout, or make the decision to override
  explicitly and say so.

## The worktree hazard that actually bit

A shell's working directory persists between commands. One `cd` into the primary checkout — made
for an unrelated read-only check — silently redirected every later `git` command there, including
`git reset`, `rm`, and `git checkout <branch>`. The primary checkout is the shared one, with
another agent's uncommitted work in it.

Nothing was lost, for one reason only: that agent had **committed** at 15:04 (`b9731c7`), so a
mixed reset could not reach content, and the deleted file was tracked in that commit. That is luck,
not safety.

**Address every worktree explicitly — `git -C <path> …` — and never rely on the shell's cwd when
more than one checkout of this repo exists.** Recovery, if it happens again: `git reflog` gives the
branch you were on before the switch; `git fsck --unreachable | awk '$2=="blob"{print $3}'` finds
blobs orphaned by a reset, and `git cat-file -p <blob>` reads them back.

## Worktrees in play

    prospector                        store-analytics-2026-07-31  (shared, uncommitted work — leave alone)
    prospector-sitemap-worktree       sitemap-pack-urls
    prospector-waitlist-worktree      waitlist-second-placement
    prospector-consolidate-worktree   consolidate-storefront / rescue-delivery-verifier

Clean up with `git worktree remove <path>` once the PRs land.
