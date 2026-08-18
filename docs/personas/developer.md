# The platform for the developer

How to get a change from your head into production without breaking anything, and which traps will
waste your afternoon if nobody warns you.

## The languages and where they live

| Area | Stack | Path |
|---|---|---|
| Engine | Python 3.14 | `prospector/`, `scripts/`, `tools/` |
| Store API | C# / .NET 9 | `store_platform/src/Store.Api/` |
| Storefront | Next.js / TypeScript | `store_platform/src/Store.Web/` |
| Ops console | Next.js / TypeScript | `store_platform/src/Ops.Console/` |
| Operator surface | Python | `~/.hermes` (separate repo) |

## Start here, every time

**One session, one worktree.** This checkout is shared by concurrent sessions, and they share one
`.git/index`. Work in your own tree:

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree
```

The setup script is not a convenience. `git worktree add` produces a tree that **looks** complete and
is not, and each gap fails by accusing something else:

- `node_modules` **cannot be symlinked** — Turbopack rejects any symlink leaving the project root,
  same filesystem or not. The script uses `cp -Rc`, an APFS copy-on-write clone. It is ~665 MB and
  takes over 30 seconds, so start it and go do something else.
- `.lux/keys/agent.pem` is untracked, so the commit gate runs and then fails for want of a signing
  key. It reads as a gate violation.
- `.venv` is absent while the hook pins `.venv/bin/python` relative to cwd, so commits die with
  `POPDD gate BLOCKED` over a missing interpreter.
- `store/` and `storage/` are **tracked runtime state that pytest writes to**. Never stage every file
  in a worktree. Name the paths you changed.

For a Python-only change you can skip `node_modules` entirely — the web lane does not run on a diff
with no web files.

## Running the checks

```bash
.venv/bin/pytest -q                                   # ~5000 tests, parallel
.venv/bin/python scripts/popdd_verify.py --staged      # the full gate, without committing
cd store_platform/src/Ops.Console && npm run typecheck && npx vitest run
cd store_platform/src/Store.Api && dotnet test
```

`pytest.ini:42` sets `addopts = -n auto --dist loadfile`, so nothing runs serially. Two real
timings: on clean `main`, 1.7s of ruff plus 445.5s of pytest (3925 passed, 3 skipped) against the
2400s ceiling at `scripts/popdd_verify.py:86`. On a merged tree while four CI jobs shared the box,
1281s (4612 passed, 3 skipped). Both pass. **If you are about to repeat a timing from this
paragraph, time it again** — the suite grows and the ceiling does not.

Anything that can exceed ~30 seconds should be started in the background while you do the next
thing. Waiting on a run you are not reading is dead time.

## The commit gate

Whether a gate is installed is a **command, not a paragraph**, and this has been documented wrongly
in both directions:

```bash
git config --get core.hooksPath          # if set, THAT directory wins, not .git/hooks
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

`core.hooksPath` overrides the hooks directory entirely, so moving `.git/hooks/pre-commit` aside does
nothing while it is set. That cost a session on 2026-08-16: a commit failed with only "exit code 1"
while the docs said no gate could have refused it. The gate had refused it, on one test out of 4124.

Two things the gate depends on that fail by accusing something else. **ruff runs repo-wide**
(`scripts/popdd_verify.py:166`), so one unformatted file anywhere walls every commit in every
worktree — including a worktree sitting on an older base. And the gate runs inside the hook, so
`git commit` holds `.git/index.lock` for the whole run.

## CI

`.github/workflows/ci.yml`. Jobs: `changes` (decides what runs), `guard` (protected files),
`python` (3 shards plus the golden-set regression gate), `engine`, `dotnet`, `nextjs`,
`ops-console`, and `ci-ok`, which fails unless every job either passed or was skipped.

Runners are self-hosted, selected by `runs-on: ${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}`. Those
minutes are free. **Do not delete `CI_RUNS_ON`** — that flips every job to GitHub-hosted and starts a
bill. Emergency lever only.

A squash-merged pull request leaves its original commits looking unmerged: `origin/main..<branch>`
still lists them, because the squash created a new commit. Verify content, not the commit list:
`git show origin/main:<file> | grep`.

**Never merge while a check is queued or in progress.**

## Shipping

Push the branch, open the pull request, and set auto-merge **in the same command block**. A pushed
branch with nobody looking at it is invisible work, and a hand-deploy is silently reverted by the
next deploy of `main`. Only a merge makes a change stick.

## Traps, ranked by how much time they have cost

| Trap | The fix |
|---|---|
| `cmd 2>&1 \| tail` reports **tail's** status | Capture the real exit code before any pipe |
| In a worktree `.git` is a **file**, not a directory | Ask git: `git rev-parse --git-path hooks`, `--git-common-dir` |
| An inherited `GIT_DIR` beats `git -C <path>` | `env -u GIT_DIR git -C <path> …` |
| `pytest` exits 0 when it collects nothing | Check the collected count |
| `dotnet test` reports exit 0 while failing | Read the summary line |
| The shell is zsh; it does not word-split unquoted vars | Wrap loops and list scripts in `bash -c` |
| Recursive `grep` skips nothing and reads 169k files | Use `rg` |
| `~/Documents` is iCloud-synced with Optimize Storage | Files can be evicted. `rsync -a --update` restores |
| `float()` on a `MagicMock` returns 1.0 | Your assertion passed on nothing |
| A TypeScript type that promises non-null | Three console crashes in one day were all this. `tsc` cannot catch a type that lies about the wire |

## What to read next

- [senior-developer.md](senior-developer.md) — which mechanism already exists before you write one.
- [qa-test-engineer.md](qa-test-engineer.md) — what green means and where green lies.
- `docs/WAYS_OF_WORKING.md`, and the root `CLAUDE.md`, which is the operating contract.
