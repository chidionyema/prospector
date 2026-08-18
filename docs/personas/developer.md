# Developer

**What this is.** The complete path from a fresh clone to a merged change in Prospector: the
environment, the worktree, the local gate, the test runner, CI, and the traps that have cost real
sessions here.
**Read this if** you are about to edit Python, TypeScript or C# in this repo and you want the
change to land instead of bouncing.
**Sibling seats:** [principal-developer.md](principal-developer.md) (health of the engineering
system), [qa-test-engineer.md](qa-test-engineer.md) (how quality is verified and how it has lied),
[README.md](README.md) (all twenty seats), [../ESTATE_MAP.md](../ESTATE_MAP.md) (the factual
spine).

---

## 0. Provenance of every number in this document

Everything below was measured on **2026-08-18** against the worktree
`.../scratchpad/wt-estate`, which sits at `192aa0e4` on branch `docs/estate-map`, a descendant of
`main` at `c3cb68b`. That tree is clean (`git status --porcelain | wc -l` → `1`, this file).

Check it yourself before trusting any line here:

```bash
git rev-parse --short HEAD          # 192aa0e4
git status --porcelain | wc -l      # 1
```

**Why a clean worktree and not the main checkout.** The main checkout
`/Users/chidionyema/Documents/code/prospector` carried **132 modified or deleted tracked files**
at the time of writing. Measuring there gives wrong answers twice over. `grep` fails on
tracked-but-deleted files (`grep: tests/unit/test_inflight.py: No such file or directory`), and
its `.github/workflows/ci.yml` is a **stale 449-line sharded copy** that is not what CI runs. The
committed 766-line version is authoritative. The two full suite runs in §5.3 make the difference
concrete: the clean worktree is green, the dirty checkout has 26 failures.

---

## 1. The shape of the repo

Measured with `git ls-files '*.<ext>' | wc -l` and `... | xargs cat | wc -l`:

| Language | Tracked files | Lines |
|---|---:|---:|
| Python (`.py`) | 666 | 177,725 |
| C# (`.cs`) | 197 | 31,804 |
| TypeScript React (`.tsx`) | 153 | 31,564 |
| TypeScript (`.ts`) | 173 | 24,957 |
| Markdown (`.md`) | 200 | 47,679 |
| Shell (`.sh`) | 44 | 4,380 |
| YAML (`.yaml`) | 7 | 2,955 |
| SQL | 0 | 0 |

Python is 70% of the source. There is no SQL: catalogue state is JSON on disk under `store/`, and
the storefront's data lives in the .NET service.

The top-level map, and what each thing is:

| Path | What it is |
|---|---|
| `prospector/` | The engine. Candidate generation, the moat (verification), pricing, publishing. |
| `prospector/scheduler/` | The unattended daemon. `run_scheduled.py` is the tick. |
| `prospector/ops/` | The read/write model behind the Ops Console gateway. |
| `store_platform/src/Store.Api/` | .NET 9 catalogue and payments API. |
| `store_platform/src/Store.Web/` | Next.js storefront (mumchimp.com). |
| `store_platform/src/Ops.Console/` | Next.js admin console. |
| `store_platform/src/Store.Tests/` | xUnit suite for the API. |
| `tests/` | The pytest suite, 383 test files. |
| `scripts/` | 42 operational and gate scripts. |
| `tools/` | One-off and backfill drivers. |
| `docs/` | Programme specs and these persona documents. |
| `store/` | **Runtime state, tracked.** Dossiers, listings, ledger, scheduler alerts. |
| `ops/` | launchd plists, retired-term config, automations. |
| `.lux/` | The POPDD gate's hook, keys and signed receipts. |

`store/` and `storage/` are tracked **and** written by the test suite. Stage paths explicitly;
never stage everything at once. See §11.

---

## 2. Day one: the environment

### 2.1 Python

```bash
.venv/bin/python -V      # Python 3.14.6
```

CI pins the same major/minor: `.github/workflows/ci.yml:116` sets `PYTHON_VERSION: "3.14"`.

**There is no `pyproject.toml` and no `setup.py`.** Dependencies come from two plain files:

- `requirements.txt` — 116 lines, the real dependency set. CI hashes it to key the shared venv
  (`ci.yml:419`: `KEY="py${PYTHON_VERSION}-$(shasum -a 256 requirements.txt | cut -c1-16)"`).
- `requirements-local.txt` — 18 lines, three sibling repos installed from the filesystem:
  `lux-popdd @ file:../popdd-py`, `lux-spec @ file:../lux-spec-py`,
  `lux-spec-cli @ file:../lux-spec-cli`. Only `run_v2.py` and `scripts/popdd_verify.py` need them.
  If those sibling directories are absent, installing that file fails and the gate cannot run; the
  rest of the repo is fine.

Because there is no editable install, the package is found via `pytest.ini:12` `pythonpath = .`.
The comment there is worth reading (`pytest.ini:2-11`): without it, every invocation died at
`tests/conftest.py:5` with `ModuleNotFoundError: No module named 'prospector'` — a failure that
reads like a broken suite and is a missing path.

### 2.2 Node

```bash
node -v                  # v26.3.0   (this machine)
```

CI pins **Node 22** in all five workflows that touch JavaScript:

```
.github/workflows/ci.yml:634            node-version: "22"
.github/workflows/ci.yml:702            node-version: "22"
.github/workflows/deploy-engine.yml:68  node-version: "22"
.github/workflows/deploy-web.yml:82     node-version: "22"
.github/workflows/e2e-live-smoke.yml:58 node-version: "22"
```

Local Node is four majors ahead of CI. That gap has not bitten yet, but it means "it builds on my
machine" is not evidence about CI. HYPOTHESIS: a Node-26-only API would pass locally and fail the
`nextjs` job. The check that would confirm it: `nvm use 22 && npm ci && npm run build` in
`store_platform/src/Store.Web/`.

Two separate npm projects, two separate `node_modules`, two separate lockfiles:
`store_platform/src/Store.Web/` and `store_platform/src/Ops.Console/`. No workspace root ties
them. A lane cannot `cd` to two directories, which is why the gate has separate `web` and
`console` lanes (`scripts/popdd_verify.py:256`, `:290`).

### 2.3 .NET

`.github/workflows/ci.yml:117` sets `DOTNET_VERSION: "9.0"`, consumed at `ci.yml:581`.

### 2.4 Secrets

**Key names only. Never print values, never commit `.env`.**

`.env` lives in the main checkout and is symlinked into every worktree by
`scripts/setup_worktree.sh:134`. The keys currently present, by name:

| Group | Keys |
|---|---|
| Model providers | `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `OPENROUTER_API_KEY`, `STANDARDCOMPUTE_API_KEY` |
| Retrieval | `EXA_API_KEY` |
| Payments | `STRIPE_API_KEY`, `STRIPE_LIVE_API_KEY`, `STRIPE_LIVE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `Stripe__ApiKey`, `Stripe__WebhookSecret` |
| Storefront and API wiring | `STORE_API_URL`, `STORE_INTERNAL_API_KEY`, `PROSPECTOR_ENTITLEMENTS_API_KEY`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL` |
| Object storage | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` |
| Infra and console | `FLY_API_TOKEN`, `CONTROL_CENTER_PASSWORD` |

Three of these are dead weight: `GEMINI_API_KEY` (no `gemini` key in `config.yaml`),
`STANDARDCOMPUTE_API_KEY` (adapter deleted 2026-08-15), and `ANTHROPIC_API_KEY` (the paid `claude`
tier was deleted with its adapter on 2026-08-15). They are listed because they are on disk, not
because anything reads them.

**The suite must never see the live payment keys.** `tests/conftest.py:207-255`
(`_no_live_payment_credentials`) is an autouse fixture that deletes `STRIPE_API_KEY`,
`STRIPE_LIVE_API_KEY` and `STORE_INTERNAL_API_KEY` from the environment **and** sets
`PROSPECTOR_DISABLE_DOTENV=1`. Both halves are needed: `prospector.run._load_dotenv` (`run.py:2444`)
re-reads the keys off disk, so stripping the environment alone is not enough. See
[qa-test-engineer.md](qa-test-engineer.md) §5 for the incident that produced this fixture — on
2026-08-07 the suite created real Stripe products.

---

## 3. Worktrees

**One session, one worktree.** This checkout is routinely shared by two concurrent Claude
sessions. They share one `.git/index`. `git worktree add` succeeds even while that index is
locked, which is the point.

Right now `git worktree list` reports **42 registered worktrees, 22 of them `prunable`**. That is
debt, not design — see [principal-developer.md](principal-developer.md) §8.

### 3.1 The only correct way to make one

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree
```

`git worktree add` alone produces a tree that **looks** complete and is not. Each gap fails by
accusing something else.

### 3.2 `scripts/setup_worktree.sh`, section by section

183 lines. `set -euo pipefail` at `:61`. It resolves the shared git directory at `:68` with
`git rev-parse --path-format=absolute --git-common-dir` — never by reading `.git` as a directory,
because in a linked worktree `.git` is a **file** containing `gitdir:`.

| Lines | What it does | The symptom if you skip it |
|---|---|---|
| 80-90 | Copies `.lux/keys/agent.pem` from the main checkout | The POPDD hook runs, then fails for want of a signing key. Reads as a **gate violation**, not a missing file. |
| 97-119 | For each of `store_platform/src/Store.Web` and `store_platform/src/Ops.Console`, `cp -Rc` clones `node_modules` (APFS copy-on-write) | Turbopack rejects **any** symlink that leaves the project root, same filesystem or not. A symlinked `node_modules` fails the build with a path error that names a module, not the link. |
| 122-131 | Symlinks `.venv` | `.lux/hooks/pre-commit:67` pins `.venv/bin/python` relative to cwd, so commits die with `POPDD gate BLOCKED` over a missing interpreter. |
| 134-144 | Symlinks `.env` | Every MiniMax tier benches with `ProviderExhaustedError: All operators in ('minimax', 'minimax_m27') unavailable — check API keys and credentials`. Reads as a provider outage. |
| 147-160 | CoW-clones `store/dossiers store/listings store/runs store/golden_runs` | Tests that read fixture dossiers fail as if the data were wrong. |
| 173-174 | Documents the pipe-to-`tail` trap in its own header | — |

That last line is worth quoting, because it is the cheapest bug in the repo to hit:

```
* `npm run build | tail` reports the exit code of `tail`, not of the build. Capture the
  build's own status first:  npm run build > /tmp/build.log 2>&1; echo "exit=$?"
```

### 3.3 Skip `node_modules` for a Python-only change

The `cp -Rc` clone is the slow part of setup (over 5 minutes). The web lane never runs on a diff
that contains no web files (`lanes_for`, `popdd_verify.py:316`), so a Python-only worktree does not
need it.

---

## 4. The local gate

### 4.1 Is it on right now?

**No.** Measured 2026-08-18:

```bash
$ git -C /Users/chidionyema/Documents/code/prospector config --get core.hooksPath
(unset)
$ ls -la "$(git -C /Users/chidionyema/Documents/code/prospector rev-parse --path-format=absolute --git-path hooks)"
-rwxr-xr-x  post-commit
lrwxr-xr-x  pre-commit.DISABLED-2026-08-14 -> ../../.lux/hooks/pre-commit
-rwxr-xr-x  pre-commit.sample
-rwxr-xr-x  pre-push
-rwxr-xr-x  pre-push.sample
$ test -e .git/hooks/pre-commit && echo PRESENT || echo ABSENT
ABSENT
```

No `pre-commit` file, `core.hooksPath` unset. **`git commit` runs no proof gate.** Run it yourself
before you push.

**Use `--path-format=absolute`.** `git rev-parse --git-path hooks` returns a *relative* path.
Running it with `-C <other-repo>` and then `ls` that result resolves it against **your** cwd, not
the other repo's. That produced `ls: .git/hooks: Not a directory` in this very session, because the
cwd was a worktree where `.git` is a file.

### 4.2 `core.hooksPath` overrides everything

When `core.hooksPath` is set, `.git/hooks/` is inert **as a directory**. Anything written there is
never read. That is why moving `.git/hooks/pre-commit` aside on 2026-08-14 did nothing while
`core.hooksPath` was set to `.git/hooks-active` (set 2026-08-15 18:57, since unset). A session on
2026-08-16 lost time to a commit that failed with only "exit code 1" while the doc said no gate
could have refused it.

Turn it on. The target must be **absolute**, because the link lives in a directory shared by every
worktree via the common git dir:

```bash
ln -sfn "$(dirname "$(cd "$(git rev-parse --git-common-dir)" && pwd -P)")/.lux/hooks/pre-commit" \
        "$(git rev-parse --git-path hooks)/pre-commit"
```

Turn it off: `rm "$(git rev-parse --git-path hooks)/pre-commit"`.

### 4.3 What the hook does

`.lux/hooks/pre-commit`, 90 lines:

- `:63` `cd "$(git rev-parse --show-toplevel)"`
- `:67` `VERIFY_CMD="${POPDD_VERIFY_CMD:-.venv/bin/python scripts/popdd_verify.py --staged}"`
- `:69` `if sh -c "$VERIFY_CMD"` — the gate's exit status is the commit's fate.

The whole run happens **inside** `git commit`, which holds `.git/index.lock` for its duration.

### 4.4 `scripts/popdd_verify.py`

677 lines. The map:

| Line | Symbol | What it is |
|---|---|---|
| 67 | `ROOT` | Repo root, resolved from `__file__`. |
| 86 | `TEST_TIMEOUT_SECONDS` | `int(os.environ.get("POPDD_TEST_TIMEOUT", "2400"))` — the per-step ceiling. |
| 93 | `DRAIN_TIMEOUT_SECONDS = 30` | How long to collect output after killing a timed-out process group. |
| 97 | `SOURCE_EXTS` | `.py .ts .tsx .js .jsx .mjs .cjs .cs .csproj .css` — a file with one of these that matches no lane **blocks the commit**. |
| 112 | `WEB_EXTS` | `.ts .tsx .js .jsx .mjs .cjs .json .css` |
| 127 / 135 | `OPS_REL`, `CONSOLE_REL` | Both are `"store_platform/src/Ops.Console/"`. Identical strings. See §4.6. |
| 138-139 | `ENGINE_CONFIGS`, `ENGINE_DIRS` | `("config.yaml",)` and `("prospector/scheduler/",)` |
| 150-215 | `_parse_pytest`, `_parse_vitest`, `_parse_dotnet`, `_parse_engine` | Extract counts for the receipt. **The verdict comes from the exit code, never the counts.** |
| 234-312 | `LANES` | The five lanes. |
| 313 | `LANE_ORDER` | `("engine", "console", "web", "dotnet", "python")` — cheapest first. |
| 316 | `lanes_for(paths)` | Pure classifier. No I/O, so the gate's own tests can assert the map. |
| ~344 | `scope_ruff(lane, paths)` | Narrows ruff to the staged `.py` files. |
| 351 | `staged_paths()` | `git diff --cached --name-only` |
| 361 / 391 | `_gate_lock_path`, `single_flight` | One gate run per tree. |
| 475 | `_run_step` | `start_new_session=True`, kill by `os.killpg`, bounded drain. |
| 537 | `run_lane` | Runs the steps, stops on the first non-zero. |
| 611 | `main` | Entry point. |

### 4.5 The five lanes

| Lane | Label | Steps | cwd | Preflight |
|---|---|---|---|---|
| `engine` | import + dry-run tick + budget ratio | `scripts/verify_engine_change.sh` | root | that script exists |
| `console` | tsc --noEmit + vitest (Ops.Console) | `npm run typecheck`, `npm test` | `Ops.Console/` | `node_modules` |
| `web` | tsc --noEmit + vitest (Store.Web) | `npm run typecheck`, `npm test` | `Store.Web/` | `node_modules` |
| `dotnet` | Store.Tests | `dotnet test <proj> --nologo -v q` | root | — |
| `python` | ruff + pytest suite | `ruff check --output-format concise`, `pytest -q --tb=no -rf` | root | — |

`engine` leads at roughly 15s, so a change that stops the daemon completing a tick is reported
before anything spends 175s on pytest.

`scripts/verify_engine_change.sh` (114 lines) runs four checks:

1. `import prospector.scheduler.run_scheduled`
2. `ruff check prospector/scheduler prospector/config.py`
3. `timeout 180 python -m prospector.scheduler.run_scheduled --once --dry-run --config config.yaml`
   (skippable with `--no-tick`)
4. `scripts/gen_budget_guard.py --config config.yaml`

`--dry-run` is what makes step 3 safe to run from a commit hook against production state: it
evaluates the guards and the generation plan and stops, spending no provider budget and writing no
candidates. It cannot prove yield, and the script says so in its own output rather than letting a
green lane imply it.

### 4.6 How `lanes_for` classifies

`popdd_verify.py:316`. Two rules matter:

- `_is_engine_path` is checked **outside** the `elif` chain, so `prospector/scheduler/*.py` selects
  **both** `engine` and `python`. The suite proves the code; the dry-run tick proves the daemon can
  still complete one.
- A `.cs` or `.csproj` file selects **both** `dotnet` and `python`, because
  `tests/test_facets.py:141` reads `PackFacets.cs` as source text.

**Defect found, unfixed.** `popdd_verify.py:334-339`:

```python
elif path.startswith(WEB_REL) and ext in WEB_EXTS:
    lanes.add("web")
elif path.startswith(OPS_REL) and ext in WEB_EXTS:
    lanes.add("ops")
```

`OPS_REL` and `CONSOLE_REL` are the **same string** (`popdd_verify.py:127`, `:135`), and the
`console` branch is checked first. The `ops` branch is therefore unreachable. It is also broken if
reached: `"ops"` is not a key in `LANES` and not in `LANE_ORDER`, so `run_lane` would `KeyError`.
Cost to fix: delete two lines.

### 4.7 `scope_ruff` — read this before you blame `main`

The worktree's `popdd_verify.py` adds `scope_ruff(lane, paths)`, which appends
`--force-exclude <staged .py files>` to the ruff step when the caller knows the paths (that is,
`--staged`, which is what the hook uses). Repo-wide ruff remains the fallback.

This exists because repo-wide ruff **grades files the committer never opened**. `main` itself
carried 12 ruff errors until `2b38ca3` cleared them, and a worktree on an older base failed the
gate until it rebased. The docstring says it plainly: "The person who has to fix it is never the
person the gate stopped."

Today the repo-wide count is small but non-zero:

```bash
$ .venv/bin/python -m ruff check --output-format concise; echo "exit=$?"
prospector/ops/readmodel.py:175:5: I001 [*] Import block is un-sorted or un-formatted
scripts/estate_map.py:36:21: F401 [*] `pathlib.Path` imported but unused
scripts/estate_map.py:198:17: E741 Ambiguous variable name: `l`
scripts/estate_map.py:209:19: E741 Ambiguous variable name: `l`
Found 4 errors.
exit=1
```

Four errors, three of them in a script added on this branch. Without `scope_ruff`, those four would
block every commit in every worktree.

`ruff.toml` selects a deliberately narrow set: `line-length = 100`, `target-version = "py312"`,
`[lint] select = ["E4","E7","E9","F","I"]`. It excludes `.venv`, `store`, `storage`, `graphify-out`,
`store_platform`, `**/node_modules`, and one experiment directory. E402 is ignored per-file for
`tools/*.py`, `scripts/*.py` and `tests/**/*.py`.

### 4.8 `single_flight` and the wedge

`popdd_verify.py:391`. One gate run per tree; a second invocation inside a second is refused.
Pinned by `tests/unit/test_popdd_gate_cannot_wedge.py`.

`_run_step` (`:475`) launches each step with `start_new_session=True` and kills the **process
group** on timeout, then drains the pipes for at most 30s. That is the fix for the specific hang
that blocked three sessions on 2026-08-14: an orphan holding the inherited pipe write end kept the
gate waiting forever. Bounded now at roughly 7.5 minutes rather than the 49 minutes measured then.

### 4.9 Run it without committing

```bash
.venv/bin/python scripts/popdd_verify.py --staged
```

This is the correct preflight. It runs the same lanes and writes the same receipt, and it does not
hold `.git/index.lock`.

---

## 5. The test runner

### 5.1 `pytest.ini`

69 lines, four settings, and 60 lines of reasoning. The settings:

```ini
pythonpath = .
testpaths = tests
addopts = -n auto --dist loadfile
tmp_path_retention_policy = failed
```

**Note the line number.** `addopts` is at **`pytest.ini:52`**. `CLAUDE.md` cites `pytest.ini:42`,
which is inside the comment block. Cite `:52`.

### 5.2 What `-n auto --dist loadfile` implies for you

- **You cannot disable xdist with `-p no:xdist`.** `addopts` always passes `-n` and `--dist`, so
  disabling the plugin gives `error: unrecognized arguments: -n --dist`. To run serially, use
  **`-n 0`**. xdist honours it and the run goes back in-process, so `--pdb`, `-s` and
  `breakpoint()` work.
- **`loadfile`, not the default `load`.** Every test in a file stays on one worker. This suite has
  process-global state that is real production behaviour, not a smell: `operator._MOAT_PRIMARY` is
  written by `config.load_config` and read by every trust decision
  (`prospector/operator.py:1362-1396`). Splitting a file across workers turns that into reds that
  reproduce nowhere, which is the expensive kind of flake: it accuses the component instead of the
  harness.
- **Never assert wall-clock duration.** `test_a_huge_page_is_selected_in_reasonable_time` used
  `time.monotonic()`, passed serially and at 8 workers, and failed at 12 on identical code — purely
  from being descheduled. It measures `time.process_time()` now (`pytest.ini:39-44`). Any new
  timing assertion must measure CPU, or parallelism makes it a coin toss and the fix looks like
  "raise the budget".
- **`tmp_path_retention_policy = failed`** deletes a passing test's `tmp_path` immediately. The
  default (`all` plus retention 3) accumulated eight session roots under `$TMPDIR/pytest-of-<user>/`,
  two holding 4,296 and 3,339 directories. A wedged gate run showed 9m48s of CPU against 66m of
  wall clock in `os_scandir`/`os_unlink`/`os_stat`, before a single test ran. It reported
  `step 'pytest' exceeded 2400s`, which reads as a slow suite and is not one.

### 5.3 Measured suite size and time

```bash
$ .venv/bin/python -m pytest --collect-only -q -n 0 | tail -1
5047 tests collected in 80.26s (0:01:20)
```

383 test files. `grep -hE '^\s*def test_'` across them counts 4,361 definitions; the gap to 5,047
is `@pytest.mark.parametrize` and class methods.

Per directory (`git ls-files "tests/<d>/test_*.py" | wc -l`):

| Directory | Test files |
|---|---:|
| `tests/unit` | 302 |
| `tests/scheduler` | 25 |
| `tests/` (top level) | 16 |
| `tests/ops` | 11 |
| `tests/invariants` | 7 |
| `tests/behavioural` | 6 |
| `tests/integration` | 3 |
| `tests/faults` | 3 |
| `tests/sim` | 1 |

**Two full runs, same command, same machine, same afternoon.** This pair is the single most useful
receipt in this document.

Clean worktree at `192aa0e4`:

```
5041 passed, 6 skipped in 1059.41s (0:17:39)
.venv/bin/python -m pytest -q --tb=no -p no:warnings  1442.04s user 206.31s system 151% cpu 18:11.19 total
```

Main checkout, 132 dirty files:

```
26 failed, 4853 passed, 4 skipped in 1289.94s (0:21:29)
.venv/bin/python -m pytest -q --tb=no -p no:warnings  1591.10s user 285.73s system 143% cpu 21:45.71 total
```

Two conclusions, both load-bearing:

1. **The suite fits the gate's ceiling.** 1,059s against 2,400s is **44%**. The "~3185s serially,
   so the gate cannot pass" figure that circulated in `CLAUDE.md` was prose, not a measurement, and
   `addopts` means nothing runs serially anyway.
2. **The 26 failures are the dirty tree, not the code.** By file:

| Count | File |
|---:|---|
| 8 | `tests/unit/test_publish_path_retries_empty_artifacts.py` |
| 7 | `tests/unit/test_shell_portability.py` |
| 4 | `tests/unit/test_tick_budget_rails.py` |
| 1 each | `test_swallowed_failures_can_only_go_down.py`, `test_doc_lint_never_increases.py`, `test_suite_is_machine_independent.py`, `tests/scheduler/test_run_scheduled.py`, `tests/scheduler/test_drain_is_supervised.py` |

Several of those are **ratchet tests** — they compare the current tree against a committed baseline
(`docs/doc_lint_baseline.json`, the swallowed-failure count). A dirty tree fails them by
construction. Before you debug a red suite, run `git status`.

---

## 6. CI

`.github/workflows/ci.yml`, **766 lines**, eight jobs. Seven workflows exist in total: `ci.yml`,
`cancel-ci-on-pr-close.yml`, `deploy-api.yml`, `deploy-engine.yml`, `deploy-web.yml`,
`e2e-live-smoke.yml`, `escape-hatch-drill.yml`.

### 6.1 Triggers, concurrency, env

```yaml
# ci.yml:111
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
```

Pushes to a branch cancel their predecessors; pushes to `main` do not, so the record of what `main`
actually proved is never destroyed by the next push.

```yaml
# ci.yml:115
env:
  PYTHON_VERSION: "3.14"
  DOTNET_VERSION: "9.0"
  PYTEST_XDIST_AUTO_NUM_WORKERS: "3"
```

`PYTEST_XDIST_AUTO_NUM_WORKERS: "3"` caps what `-n auto` resolves to on the runner. It was chosen
for four concurrent python jobs on one box.

### 6.2 Two runner pools

| Pool | Expression | Jobs |
|---|---|---|
| heavy | `${{ vars.CI_HEAVY_RUNS_ON \|\| vars.CI_RUNS_ON \|\| 'ubuntu-latest' }}` | `python`, `engine`, `dotnet` |
| light | `${{ vars.CI_LIGHT_RUNS_ON \|\| vars.CI_RUNS_ON \|\| 'ubuntu-latest' }}` | `changes`, `guard`, `nextjs`, `ops-console`, `ci-ok` |

The double fallback means a repo with neither variable set still runs on GitHub-hosted runners.

`scripts/ci_capacity.py` (run by the `guard` job) checks the contract in
`ops/config/ci_capacity.yaml` three ways: every job is assigned to exactly one pool and its
`runs-on` reads that pool's variable; the widest concurrent `heavy` jobs fit in
`cpus - reserved_cpus`, with each declared width read back out of `ci.yml`; and with `--live`, the
runners actually registered on GitHub carry the pool labels in the declared numbers. Its own header
says why it exists: every previous fix for "CI is unreliable on this box" was a constant tuned to
one observed mix, and nothing compared the constants to each other.

### 6.3 The jobs

| Line | Job | Runner | Timeout | Gate |
|---:|---|---|---:|---|
| 150 | `changes` | light | 5 | — |
| 267 | `guard` | light | — | `if: github.event_name == 'pull_request'` |
| 339 | `python` | heavy | 40 | `needs.changes.outputs.python == 'true'` |
| 488 | `engine` | heavy | 30 | `needs.changes.outputs.python == 'true'` |
| 569 | `dotnet` | heavy | 30 | `needs.changes.outputs.dotnet == 'true'` |
| 616 | `nextjs` | light | 40 | `needs.changes.outputs.web == 'true'` |
| 686 | `ops-console` | light | 40 | `needs.changes.outputs.console == 'true'` |
| 748 | `ci-ok` | light | 5 | `if: always()` |

### 6.4 `changes` — how skipping works, and why it fails open

`ci.yml:150`. It emits four boolean outputs: `python`, `dotnet`, `web`, `console`. Every heavy job
hangs off one of them.

Two properties matter:

1. **It fails open.** If the path filter cannot be computed, the outputs default to `true` and
   everything runs. A filter that failed closed would silently skip the lane that proves the
   change.
2. **A `.github/` diff runs Python unconditionally**, plus only the lanes the workflow diff names.
   Editing the workflow must not be able to switch off the job that would have caught the edit.

### 6.5 `python` — unsharded, and why

`ci.yml:339-487`, `timeout-minutes: 40`.

It builds a **content-addressed shared venv**:

```bash
KEY="py${PYTHON_VERSION}-$(shasum -a 256 requirements.txt | cut -c1-16)"   # ci.yml:419
uv venv --relocatable --python "${PYTHON_VERSION}" "$TMP"                  # ci.yml:424
```

`--relocatable` because the venv is built in a temp directory and then landed at its final path
with `mv -n`. `mv -n` (no-clobber) makes two concurrent jobs racing to build the same key safe: the
loser's copy is discarded, not merged. The job then verifies with `python -c 'import pytest'` —
proving the venv is usable, not merely present.

The suite selection is explicit rather than by directory:

```bash
files=$(git ls-files 'tests' | grep -E '(^|/)test_[^/]+\.py$' \
        | grep -v -e 'tests/test_ui_theme\.py$' -e 'tests/test_golden_set\.py$')
count=$(printf '%s\n' "$files" | grep -c . || true)
if [ "$count" -eq 0 ]; then echo "::error::collected no test files — the pattern is wrong"; exit 1; fi
python -m pytest -q $files -n 6 --tb=short -p no:warnings
```

The `count -eq 0` check guards against the worst CI lie in this repo: **pytest exits 0 when it
collects nothing.** A pattern typo would otherwise produce a green job that ran zero tests.

`tests/test_golden_set.py` is excluded from the main run and given its own step:
`python -m pytest tests/test_golden_set.py -v --tb=short`. That is the mixed-sector discrimination
gate, and it gets its own verdict line so a regression there cannot be lost in a 5,000-test summary.

**The job is UNSHARDED.** Commit `01a5b7e1` — "ci: stop sharding the python suite, it made the lane
produce nothing (#274)" — removed the shards. If you are reading a 449-line sharded `ci.yml`, you
are reading the main checkout's dirty working tree, not what runs.

### 6.6 `guard` — pull requests only

`ci.yml:267`. Three scripts:

- `scripts/guard_protected_deletions.py`
- `scripts/doc_lint.py --check --against "origin/${{ github.base_ref }}"`
- `scripts/ci_capacity.py`

`doc_lint.py` is a compiler for prose. Three checks, each because that shape of rot has happened
here: a referenced path that does not exist (`RUN.md` sent readers to a moved module); a referenced
path that exists and is **empty** (`prospector/publish.py` is a 0-byte stub, so a doc naming it
reads correct to grep and is useless to run); and a provider named as current that `config.yaml`
does not select (`RUN.md:95` said the moat was "Claude+Gemini" weeks after the `gemini` key was
gone). A line carrying `doc-lint-ok` is exempt, and whole files can be exempt in `HISTORICAL_FILES`
— the incidents are the reasoning behind the current rules, so the check must not ban discussing a
retired provider.

### 6.7 `ci-ok` — the single required check

`ci.yml:748`. `needs: [changes, guard, python, engine, dotnet, nextjs, ops-console]`,
`if: always()`. It treats **`success` or `skipped`** as pass.

This is the mechanism that makes path filtering safe as a branch-protection rule. Only `ci-ok` needs
to be required. A skipped `dotnet` job on a Python-only PR is a pass, not a pending check that never
resolves.

### 6.8 The live storefront smoke

`.github/workflows/e2e-live-smoke.yml`, 80 lines. It is deliberately **not** a job in `ci.yml`.

- Triggers: `workflow_run` on "Deploy Store.Web" `completed`, `schedule: cron "0 7 * * *"`, and
  `workflow_dispatch`.
- Job guard (`:42`):
  `github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'`.
- `concurrency: group: e2e-live-smoke, cancel-in-progress: false`.
- Runs `npm run test:e2e` with `WEB_BASE_URL: ${{ vars.WEB_BASE_URL || 'https://mumchimp.com' }}`.
- Uploads `playwright-report/` with `if: always()`, 7-day retention.

The header explains both halves. It used to run on `push: main` alongside everything else; once
Store.Web started deploying from that same push, Playwright raced the Fly rolling update, so a green
run proved the **old** image worked. And the daily schedule is not belt-and-braces: the storefront
breaks without anyone committing — the two unbuyable packs found on 2026-07-31 were a data and
config fault with no commit behind them.

`playwright.config.ts` (19 lines): `testDir: './e2e'`, `timeout: 30_000`, `expect.timeout: 10_000`,
`fullyParallel: false`, `retries: 0`, chromium only. Four specs: `discovery.spec.ts`,
`kill-log.spec.ts`, `seo.spec.ts`, `storefront.spec.ts`.

---

## 7. Two end-to-end traces

### 7.1 Trace A — a one-line change in `prospector/scheduler/run_scheduled.py`

| Hop | Where | What happens |
|---|---|---|
| 1 | your shell | `git worktree add --detach ../wt-fix HEAD && ./scripts/setup_worktree.sh ../wt-fix` |
| 2 | `scripts/setup_worktree.sh:80-160` | agent.pem copied, `.venv` and `.env` symlinked, store fixtures cloned. `node_modules` skipped if the change has no web files. |
| 3 | your editor | edit the line |
| 4 | `git add -- <path>` | stages the path |
| 5 | `popdd_verify.py:351` | `staged_paths()` → `["prospector/scheduler/run_scheduled.py"]` |
| 6 | `popdd_verify.py:325` | `_is_engine_path` matches `ENGINE_DIRS` → adds `engine`; it sits outside the elif chain, so `ext == ".py"` also adds `python` |
| 7 | `popdd_verify.py:313` | `LANE_ORDER` puts `engine` first |
| 8 | `popdd_verify.py:537` | `run_lane("engine")` → `scripts/verify_engine_change.sh` → import, ruff on the scheduler package, a 180s dry-run tick, the budget-ratio guard. About 15s. |
| 9 | `popdd_verify.py:344` | `scope_ruff` narrows the python lane's ruff to that one file |
| 10 | `popdd_verify.py:537` | `run_lane("python")` → ruff (seconds) then the full pytest suite (1,059s clean) under the 2,400s ceiling at `:86` |
| 11 | `.lux/receipts/` | a signed receipt is written; `.lux/keys/agent.pem` is what signs it |
| 12 | `git push` and `gh pr create` | |
| 13 | `ci.yml:150` | `changes` sees a `.py` path → `python=true`, `dotnet=false`, `web=false`, `console=false` |
| 14 | `ci.yml:339` and `:488` | `python` and `engine` run on the heavy pool; `dotnet`, `nextjs`, `ops-console` are **skipped** |
| 15 | `ci.yml:267` | `guard` runs (it is a PR): protected deletions, doc lint against `origin/main`, CI capacity |
| 16 | `ci.yml:748` | `ci-ok` sees success or skipped across all seven → green |
| 17 | squash merge | one commit on `main`; see §11 for the commit-list trap |
| 18 | `.git/hooks/post-commit` | rebuilds the graphify graph with `PYTHONHASHSEED=0`, skipped during rebase, merge and cherry-pick |
| 19 | production | **nothing happens.** See §7.3. |

### 7.2 Trace B — a change to `store_platform/src/Ops.Console/src/pages/index.tsx`

| Hop | Where | What happens |
|---|---|---|
| 1 | `popdd_verify.py:333` | `path.startswith(CONSOLE_REL)` and `.tsx in WEB_EXTS` → adds `console`. The `web` and `ops` branches are `elif`, so neither fires. |
| 2 | `popdd_verify.py:290` | The `console` lane's `preflight` requires `Ops.Console/node_modules`. Absent → the lane is BLOCKED and the commit refused, rather than passing unproven. This is why `setup_worktree.sh` must run. |
| 3 | `popdd_verify.py:537` | `npm run --silent typecheck`, then `npm test --silent`, cwd `Ops.Console/` |
| 4 | `_parse_vitest` (`:167`) | reads the counts for the receipt; the verdict is still the exit code |
| 5 | `ci.yml:150` | `changes` → `console=true`, everything else false |
| 6 | `ci.yml:686` | `ops-console` runs on the **light** pool, Node 22, 40-minute timeout |
| 7 | `ci.yml:748` | `python`, `engine`, `dotnet`, `nextjs` all skipped; `ci-ok` counts skipped as pass |

The `console` lane exists because of a real defect: on 2026-08-16 `daemon.restart` was live in the
Python gateway and missing from the browser allowlist, so an operator pressed a button that 404'd.
`store_platform/src/Ops.Console/tests/act.test.ts` now checks the two lists agree.

### 7.3 The hop that is not there: merging does not deploy the engine

**Production does not run from this checkout.** The scheduler and consumer run from
`/Users/chidionyema/Documents/code/prospector-live`, a checkout kept detached at `origin/main`.
Merging to `main` does not move it.

```bash
.venv/bin/python scripts/live_checkout.py            # daemon cwd, live HEAD vs origin/main, secrets
.venv/bin/python scripts/live_checkout.py --update   # roll production forward and restart
```

Both are Ops Console buttons. `--update` refuses a live checkout with local code changes: it must
stay a clean mirror of `main`, so a fix reaches production through a PR, not an edit on the box.

Why it exists: on 2026-08-17 production was running from this shared developer checkout on whatever
branch a session had left it on — `integrate/minimax-into-main`, 75 commits behind `origin/main`,
executing 17-hour-old code. The only way to see that was `lsof` on the pid.

`PROSPECTOR_STORE_DIR` on both launchd plists pins the catalogue, ledger, dossiers and scheduler
files back to `/Users/chidionyema/Documents/code/prospector/store`. There is exactly one store.
**Never write `Path(__file__).parent.parent / "store"`.** Four constants did, and for twenty minutes
the provider health marks, the retrieval cache and the scheduler audit trail were written beside the
new code while the ledger went to the canonical store. `config.store_root()` is the one resolver.

---

## 8. The numbers

| Number | Value | Command |
|---|---:|---|
| Tracked Python files | 666 | `git ls-files '*.py' \| wc -l` |
| Python lines | 177,725 | `git ls-files '*.py' \| xargs cat \| wc -l` |
| Test files | 383 | `git ls-files 'tests/**/test_*.py' 'tests/test_*.py' \| wc -l` |
| Tests collected | 5,047 | `pytest --collect-only -q -n 0` |
| `def test_` definitions | 4,361 | `... \| xargs grep -hE '^\s*def test_' \| wc -l` |
| Collection time alone | 80.26s | same |
| Full suite, clean tree | 1,059.41s / 18m11s wall | `time pytest -q --tb=no -p no:warnings` |
| Full suite, dirty tree | 1,289.94s / 21m45s wall, 26 failed | same, main checkout |
| Gate per-step ceiling | 2,400s | `popdd_verify.py:86` |
| Clean suite as % of ceiling | 44% | 1059.41 / 2400 |
| vitest test files | 98 | `git ls-files '*.test.ts' '*.test.tsx' '*.test.mts'` |
| vitest `it(` / `test(` calls | 938 | `... \| xargs grep -hcE "^\s*(it\|test)\(" \| paste -sd+ \| bc` |
| xUnit `[Fact]` / `[Theory]` | 309 | `git ls-files 'store_platform/src/Store.Tests/*.cs' \| xargs grep -hE '^\s*\[(Fact\|Theory)' \| wc -l` |
| Store.Tests `.cs` files | 41 | `git ls-files 'store_platform/src/Store.Tests/*.cs' \| wc -l` |
| Playwright specs | 4 | `git ls-files 'store_platform/src/Store.Web/e2e/*'` |
| Repo-wide ruff errors | 4 | `.venv/bin/python -m ruff check --output-format concise` |
| `ci.yml` lines | 766 | `wc -l < .github/workflows/ci.yml` |
| Registered worktrees | 42, 22 prunable | `git worktree list` |
| Commits on this branch | 726 | `git rev-list --count HEAD` |

---

## 9. Failure modes

Every row here has happened in this repo.

| Symptom | Root cause | Fix |
|---|---|---|
| `git commit` fails with only "exit code 1", and the docs say no gate is installed | `core.hooksPath` was set, so `.git/hooks-active/pre-commit` ran and `.git/hooks/` was inert | `git config --get core.hooksPath` first, always. Never trust prose about the gate. |
| Commit blocked by ruff findings in a file you never opened | ruff ran repo-wide | `scope_ruff` (`popdd_verify.py:344`) narrows it under `--staged`. If you are on an older base, rebase. |
| `POPDD gate BLOCKED` over a missing interpreter | worktree has no `.venv`; `.lux/hooks/pre-commit:67` pins `.venv/bin/python` relative to cwd | `./scripts/setup_worktree.sh <path>` |
| Gate runs, then fails as a "gate violation" | `.lux/keys/agent.pem` is untracked and absent | same script, `:80-90` |
| Turbopack fails on a module path | `node_modules` was symlinked; Turbopack rejects any symlink leaving the project root | `cp -Rc` APFS clone, `setup_worktree.sh:109` |
| `ProviderExhaustedError: All operators in ('minimax','minimax_m27') unavailable` in a worktree | no `.env` — git does not carry secrets | symlink it, `setup_worktree.sh:134` |
| A failed build reads as `exit 0` | `npm run build \| tail` reports **tail's** status | `npm run build > /tmp/b.log 2>&1; echo "exit=$?"` |
| Gate reports `step 'pytest' exceeded 2400s` and nothing is slow | pytest was unlinking 4,296+ stale tmp directories before running a test | `tmp_path_retention_policy = failed` (`pytest.ini:69`) |
| A test passes at 8 workers and fails at 12 | it asserted wall-clock duration | measure `time.process_time()`, never `time.monotonic()` |
| `error: unrecognized arguments: -n --dist` | you passed `-p no:xdist`, but `addopts` still injects them | use `-n 0` |
| Suite red on 26 tests you did not touch | dirty tree; ratchet tests grade the tree against a committed baseline | `git status`; measure in a clean worktree |
| `grep: tests/unit/test_inflight.py: No such file` | file is tracked but deleted in the working tree | measure in a clean worktree |
| `ls: .git/hooks: Not a directory` | `git -C <other> rev-parse --git-path hooks` returns a **relative** path that resolved against your cwd, where `.git` is a worktree file | `--path-format=absolute` |
| Engine ran 17-hour-old code while `main` was green | production runs from `prospector-live`, not this checkout | `scripts/live_checkout.py` |
| Provider health marks written where a probe cannot read them | a store path derived from `__file__` follows the code | `config.store_root()` |
| CI green on a job that ran zero tests | pytest exits 0 on zero collected | the `count -eq 0` guard in `ci.yml`'s python job |
| Playwright red on a good deploy | the smoke raced the Fly rolling update | `workflow_run` ordering plus the success guard, `e2e-live-smoke.yml:42` |
| `unbounded recursive grep` refused by a hook | `grep -r` walks 169,226 files here and ignores `.gitignore` | `git ls-files ... \| xargs grep`, or `rg` |

---

## 10. Invariants

| Invariant | Where it lives | What breaks when it goes |
|---|---|---|
| Every source file in a commit is claimed by some lane | `SOURCE_EXTS` (`popdd_verify.py:97`) plus `lanes_for` | A file type nobody covers commits unproven. `.tsx` did exactly that for months when the old hook matched `\.(py\|ts\|js\|cs)$`; **183** Store.Web files committed ungated. |
| `config.yaml` and `prospector/scheduler/` select the engine lane | `ENGINE_CONFIGS`/`ENGINE_DIRS` (`:138`) | `9089ebc` changed daemon behaviour with a YAML-only diff, printed "nothing to prove", and the engine produced nothing for 21 consecutive ticks. See [principal-developer.md](principal-developer.md) §6. |
| The verdict comes from the exit code, never from parsed counts | `run_lane` (`:537`) | `dotnet test` prints a summary and can still exit non-zero; trusting the counts inverts the verdict. |
| One test file, one xdist worker | `--dist loadfile` (`pytest.ini:52`) | `operator._MOAT_PRIMARY` splits across processes; phantom reds that reproduce nowhere. |
| The suite never holds live payment credentials | `tests/conftest.py:207-255` | Real Stripe products get created. It happened on 2026-08-07. |
| `ci-ok` treats skipped as pass | `ci.yml:748` | Branch protection blocks every PR that legitimately skips a lane. |
| `changes` fails open | `ci.yml:150` | A broken filter silently skips the lane that would have caught the change. |
| There is exactly one `store/` | `PROSPECTOR_STORE_DIR` on both plists; `config.store_root()` | Two stores; a daemon writes one health file while a probe reads another, and a recovered provider is never seen. |
| Production is a clean mirror of `main` | `scripts/live_checkout.py --update` refuses a dirty live checkout | Fixes reach production by hand-editing a box, and `main` stops describing what runs. |

---

## 11. How to change it safely

**Adding a dependency.** Edit `requirements.txt`. That changes the CI venv key (`ci.yml:419`), so
the next run rebuilds it once and every subsequent run reuses it. Do not add to
`requirements-local.txt` unless the package genuinely lives in a sibling directory.

**Adding a test.** Put it under `tests/unit/` unless it needs the scheduler, the ops read model, or
a fixture tree. Name it as a sentence — see [qa-test-engineer.md](qa-test-engineer.md) §9 for the
convention and a worked example. If it asserts a duration, use `time.process_time()`.

**Adding a lane to the gate.** Add a `Lane` to `LANES` (`popdd_verify.py:234`), add its key to
`LANE_ORDER` (`:313`) in cost order, add the classification branch in `lanes_for` (`:316`), and add
a case to `tests/unit/test_popdd_gate_lanes.py`. `lanes_for` is pure, so the test needs no suite
run. **Check `LANE_ORDER` contains your key** — the dead `"ops"` branch at `:337` is what happens
when it does not.

**Adding a CI job.** It must (a) hang off a `changes` output, (b) declare a pool via
`vars.CI_HEAVY_RUNS_ON` or `vars.CI_LIGHT_RUNS_ON`, (c) be added to `ci-ok`'s `needs`, and (d) be
declared in `ops/config/ci_capacity.yaml`. `scripts/ci_capacity.py` fails the `guard` job if any of
those is missing. A job absent from `ci-ok`'s `needs` is a job whose failure does not block a merge.

**Changing `config.yaml`.** It selects the engine lane, so the gate runs a dry-run tick. That tick
proves a tick still *completes*; it does not prove yield. A generation-shaped change needs a forward
measurement — see §6 of [principal-developer.md](principal-developer.md).

**Stage explicit paths.** `store/` and `storage/` are tracked runtime state that pytest writes to.
Staging the whole tree captures another process's test output. Use `git add -- path/one path/two`.

**Never merge onto a red `main`.** A failing `main` makes every subsequent PR's CI ambiguous: you
cannot tell whether the red is yours. Fix `main` first; `fix(ci): make main green — register two
tools, correct three doc paths, argue two swallows (#277)` is what that looks like.

**The squash-merge commit-list trap.** A squash merge collapses N commits into one.
`git log --oneline main` afterwards shows one line, not N, so counting commits on `main`
undercounts the work, and any script reconciling "PRs merged" against "commits on main" will
disagree. Read the PR number in the squash subject, for example `(#286)`, not the commit count.

**Preflight, do not commit and see.** `git commit` holds `.git/index.lock` for the whole gate run.
Use `.venv/bin/python scripts/popdd_verify.py --staged` instead.

**Go to a worktree on the first gate refusal.** Three sequential 15-minute gate runs in a shared
checkout cost a whole session. Isolate immediately.

---

## 12. Open gaps and debt

| Gap | Evidence | Cost to close |
|---|---|---|
| The local gate is **off** | `test -e .git/hooks/pre-commit` → ABSENT; `core.hooksPath` unset | One symlink (§4.2). The stated blocker was that the suite cannot fit the ceiling; measured, it is 44% of it. This is a decision, not work. |
| Dead `"ops"` branch in `lanes_for` | `popdd_verify.py:334-339`; `OPS_REL == CONSOLE_REL`; `"ops"` not in `LANES`/`LANE_ORDER` | Delete two lines, add one assertion to `test_popdd_gate_lanes.py`. About 15 minutes. |
| Duplicate fixture in `tests/conftest.py` | `_isolate_usage_wall` defined at `:48` **and** `:181`; the second shadows the first, so `:48-69` is dead code | Delete the dead definition after checking the two bodies agree. About 30 minutes. |
| `popdd_verify.py:128-131` states the wrong number | The comment says `9089ebc` raised `candidates_per_signal` **"5 → 50"**. `git show 9089ebc -- config.yaml` shows `-  candidates_per_signal: 20` / `+  candidates_per_signal: 50`. The same comment puts the barren window at "11:23–15:57Z"; `store/scheduler/alerts.jsonl` puts the last of the 18 criticals at **16:26:46Z**. | A two-word edit. The larger risk is that a code comment is the only place that incident is written down. |
| `CLAUDE.md` cites `pytest.ini:42` | `addopts` is at `pytest.ini:52`; `:42` is inside a comment | One-character edit. `doc_lint.py` checks paths, not line numbers. |
| 22 prunable worktrees registered | `git worktree list` | `git worktree prune`, but it is a write, so it needs an explicit decision. |
| Local Node is v26.3.0; CI pins 22 | `node -v` against five workflow pins | Install Node 22 locally, or accept that local builds are not evidence about CI. |
| The `nextjs` CI job runs typecheck and build but **not** `npm test` | `popdd_verify.py:257-260` says so explicitly | 938 vitest assertions have no enforcement point once the local gate is off. Adding `npm test` to `ci.yml:616` is a few lines; the reason it is not there is runner time. |
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `STANDARDCOMPUTE_API_KEY` still in `.env` | no config selects any of them | Removing them is safe and reduces the blast radius of a leak. Minutes. |
| `requirements-local.txt` depends on three sibling checkouts by relative path | `lux-popdd @ file:../popdd-py` and two others | A clone without those siblings cannot install the gate's own dependencies. Publishing or vendoring them is roughly a day. |

---

## 13. Where to look next

```bash
# What is actually installed and where
git rev-parse --short HEAD; git status --porcelain | wc -l
git config --get core.hooksPath
ls -la "$(git rev-parse --path-format=absolute --git-path hooks)"
.venv/bin/python -V; node -v

# Preflight a change without committing
.venv/bin/python scripts/popdd_verify.py --staged

# The runner
.venv/bin/python -m pytest --collect-only -q -n 0 | tail -1
.venv/bin/python -m pytest tests/unit/test_popdd_gate_lanes.py -n 0 -q

# The engine, without spending anything
scripts/verify_engine_change.sh --no-tick
.venv/bin/python -m prospector.scheduler.run_scheduled --once --dry-run --config config.yaml

# What production is running
.venv/bin/python scripts/live_checkout.py

# CI contracts
python3 scripts/ci_capacity.py
python3 scripts/doc_lint.py --list
```

| File | Why |
|---|---|
| `pytest.ini` | 69 lines, four settings, and the reasoning for each. |
| `scripts/popdd_verify.py` | The gate. Read `LANES` (`:234`) and `lanes_for` (`:316`) first. |
| `scripts/setup_worktree.sh` | The header names five traps and the misleading symptom of each. |
| `.github/workflows/ci.yml` | 766 lines. Read `changes` (`:150`) and `ci-ok` (`:748`). |
| `tests/conftest.py` | Eleven autouse fixtures, all of them fences. |
| `ruff.toml` | Why the rule set is narrow. |
| `../ESTATE_MAP.md` | The factual spine of the estate. |
| `../../CLAUDE.md` | Project operating rules. Treat every status sentence in it as a lead to verify, not fact. |
