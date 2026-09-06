# QA / Test Engineer

**What this is.** A complete audit of how quality is verified in this estate: every suite, every
runner, every fixture that keeps the network out, the CI job matrix, and the eight documented
occasions when a green result was a lie.
**Read this if** you are writing a test here, diagnosing a red suite, or deciding whether a green
check means anything.
**Sibling seats:** [developer.md](developer.md) (setup and the local gate),
[principal-developer.md](principal-developer.md) (health of the engineering system),
[README.md](README.md) (all twenty seats), [../ESTATE_MAP.md](../ESTATE_MAP.md) (the factual spine).

---

## 0. Provenance

Measured **2026-08-18** in the clean worktree `.../scratchpad/wt-estate` at `192aa0e4` on branch
`docs/estate-map`, a descendant of `main` at `c3cb68b`. Every number below has its command inline.
Two full suite runs were executed for this document; their outputs are quoted verbatim in §6.

---

## 1. The complete test inventory

### 1.1 Four runners

| Runner | What it tests | Count | Where | How it runs |
|---|---|---:|---|---|
| pytest | The Python engine | **5,047 tests in 383 files** | `tests/` | `.venv/bin/python -m pytest` |
| vitest | Store.Web + Ops.Console | **938 calls in 98 files** | `store_platform/src/{Store.Web,Ops.Console}` | `npm test` |
| xUnit | Store.Api | **309 `[Fact]`/`[Theory]` in 41 files** | `store_platform/src/Store.Tests/` | `dotnet test` |
| Playwright | The live storefront | **4 specs** | `store_platform/src/Store.Web/e2e/` | `npm run test:e2e` |

Commands:

```bash
git ls-files 'tests/**/test_*.py' 'tests/test_*.py' | wc -l                     # 383
.venv/bin/python -m pytest --collect-only -q -n 0 | tail -1                     # 5047 tests in 80.26s
git ls-files 'tests' | xargs grep -hE '^\s*def test_' | wc -l                   # 4361
git ls-files '*.test.ts' '*.test.tsx' '*.test.mts' | wc -l                      # 98 files, 938 it()/test()
git ls-files 'store_platform/src/Store.Tests/**/*.cs' | xargs grep -hE '^\s*\[(Fact|Theory)' | wc -l   # 309
```

**5,047 collected but only 4,361 `def test_` definitions.** The gap of 686 is parametrisation —
`@pytest.mark.parametrize` expands one definition into many collected tests.
`tests/unit/test_shell_portability.py` is the clearest case: one test body parametrised over
`flock`, `free`, `ionice`, `lsb_release`, `pidof`, `setsid`, `taskset`.

**Collection alone takes 80.26 seconds.** That is 7.6% of a fast full run before a single assertion
executes. It is import cost across 383 files, and it is why `pytest -k` is not a cheap way to run one
test — the collection is paid regardless.

### 1.2 pytest, by directory

Counted with `git ls-files "tests/<dir>/test_*.py" | wc -l` per directory:

| Directory | Files | What lives there |
|---|---:|---|
| `tests/unit/` | 302 | The bulk. One file per invariant, named as a sentence. |
| `tests/scheduler/` | 25 | Tick behaviour, drain supervision, budget rails. |
| `tests/` (top level) | 16 | Cross-cutting: golden set, UI theme, machine independence, publish. |
| `tests/ops/` | 11 | Console API, runs, money read models. |
| `tests/invariants/` | 7 | Properties that must hold across the whole system. |
| `tests/behavioural/` | 6 | End-to-end behaviour of the pipeline. |
| `tests/integration/` | 3 | Multi-component. |
| `tests/faults/` | 3 | Injected failures. |
| `tests/sim/` | 1 | Simulation. |

**79% of test files are in `tests/unit/`.** The name is misleading — many of them shell out to git,
read tracked files, or run a linter over the repo. §5 covers what that costs.

### 1.3 vitest, by location

`git ls-files '*.test.ts' '*.test.tsx' | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn`:

| Files | Location |
|---:|---|
| 58 | `store_platform/src/Store.Web/src/__tests__/` |
| 25 | `store_platform/src/Store.Web/src/lib/__tests__/` |
| 12 | `store_platform/src/Ops.Console/tests/` |
| 1 | `store_platform/src/Store.Web/src/components/marketing/__tests__/` |
| 1 | `store_platform/src/Store.Web/src/components/waitlist/__tests__/` |
| 1 | `store_platform/src/Store.Web/src/lib/seo/__tests__/` |

**The 86 Store.Web vitest files have no CI enforcement point.** `scripts/popdd_verify.py:257-260`
states it in a code comment: "The storefront proof CI itself does NOT fully run: ci.yml's `nextjs` job
runs typecheck + build but never `npm test`, so these 523 vitest tests have no other enforcement
point." The comment's count (523) is the file's own historical number; the live figure is 938 calls
across 98 files including Ops.Console. Either way the conclusion holds, and it is worse than the
comment says, because the local gate that was the only enforcement point is currently **off** (§4.1).

### 1.4 Playwright

Four specs in `store_platform/src/Store.Web/e2e/`, all against a live URL:
`discovery.spec.ts`, `kill-log.spec.ts`, `seo.spec.ts`, `storefront.spec.ts`.

`store_platform/src/Store.Web/playwright.config.ts`, all 19 lines of it:

| Setting | Value | Consequence |
|---|---|---|
| `testDir` | `'./e2e'` | Only the four specs. |
| `timeout` | `30_000` | Per test. |
| `expect.timeout` | `10_000` | Per assertion. |
| `fullyParallel` | `false` | Serial. Four specs against one live site do not race. |
| `retries` | `0` | **No retry masking.** A flake is a failure. |
| `reporter` | `[['list']]` | Line per test, readable in CI logs. |
| `baseURL` | `process.env.WEB_BASE_URL \|\| 'http://localhost:3000'` | Defaults local, CI sets live. |
| projects | chromium only | One engine. Firefox and WebKit are untested. |

`retries: 0` is the notable choice, and it is the right one. A retry turns a flaky test green and
throws away the signal that something is timing-sensitive.

---

## 2. Fixtures, mocks and how the network is kept out

### 2.1 `tests/conftest.py` — eleven autouse fixtures

309 lines. Every fixture is autouse, so they apply to all 5,047 tests without any test opting in.
That is deliberate: a fence a test can forget to request is not a fence.

The most important one, `_no_live_payment_credentials` (`tests/conftest.py:207-255`):

```python
for key in ("STRIPE_API_KEY", "STRIPE_LIVE_API_KEY", "STORE_INTERNAL_API_KEY"):
    monkeypatch.delenv(key, raising=False)
monkeypatch.setenv("PROSPECTOR_DISABLE_DOTENV", "1")
```

Its docstring records why it exists, and it is the sharpest cautionary tale in the repo. On
**2026-08-07 the test suite created real products in a live Stripe account.** `test_publish.py`
patched `requests.post`. `StripeProvisioner` does not use `requests` — it uses the Stripe SDK
(`self._stripe.Product.create(...)`, `prospector/bridge.py:1284`). The mock was on the wrong
transport, so it intercepted nothing. And deleting the environment variable was not enough on its own,
because `prospector.run._load_dotenv` (`prospector/run.py:2444`) re-reads the keys straight off disk —
hence `PROSPECTOR_DISABLE_DOTENV=1` in the same fixture.

**Two separate lessons in one fixture:** mock at the boundary the code actually crosses, and an env
var is not a fence when something re-reads the file.

**Known defect:** `_isolate_usage_wall` is defined **twice**, at `tests/conftest.py:48` and again at
`:181`. Python binds the second, so lines 48-69 are dead code. It is harmless today because both
definitions do the same job, but it is a trap: editing the first one has no effect and the change
appears to do nothing. Cost to fix: delete the dead block, about thirty minutes with a suite run.

### 2.2 Offline retrieval

`CLAUDE.md` states the design: `retrieval.py` provides "live fetch, caching, per-provider circuit
breakers; fixtures for offline test." The chain is `[ddg, exa, claude_cli]` (`config.yaml`
`retrieval.provider`). Tests use the fixture path, so no test hits DuckDuckGo or Exa.

The guard for the *failure* behaviour of that chain is `tests/unit/test_failover.py:58-72`:

```
test_exa_transport_error_raises_not_empty
```

Its docstring: a bad `EXA_API_KEY` or transport error must **propagate** so the chain fails over, and
must not be swallowed into `[]`. An empty list is read by the chain as "found nothing, success", which
halts failover. That is how a dead Exa silently zeroed grounding and made every check `unverifiable`.
Sibling guard: `test_dead_exa_fails_over_to_live_provider()`.

### 2.3 What still needs a live service

| Suite | Needs | Consequence if absent |
|---|---|---|
| Playwright e2e | A reachable `WEB_BASE_URL` (live site or `npm run dev`) | Every spec fails on connection refused. Not runnable in the local gate. |
| `tests/test_golden_set.py` | A configured verdict brain | **Excluded from the CI python job's file list** and run as its own step so its verdict is not buried. |
| `tests/test_ui_theme.py` | — | Also excluded from the CI python job's file list. See §5.8. |
| dotnet integration tests | An in-memory host; no external service | Fine offline. |

Both exclusions are made by the `grep -v` in the CI python job's file-selection step, quoted in
full in §3.3.

### 2.4 The tests that read the tree

A distinct category, and the source of most ambiguous reds. These do not mock anything; they run a
real tool over the real working tree:

| Test | Reads | Fails when |
|---|---|---|
| `tests/unit/test_retired_terms.py::test_this_repo_is_clean_of_every_retired_term` | every tracked file | any file names a retired term outside its allow-list |
| `tests/unit/test_doc_lint_never_increases.py::test_no_doc_gets_less_accurate_than_its_baseline` | every doc + `docs/doc_lint_baseline.json` | a doc gains a finding |
| `tests/unit/test_swallowed_failures_can_only_go_down.py` | every source file | a new bare `except: pass` appears |
| `tests/test_suite_is_machine_independent.py` | the suite itself | a test hardcodes a machine-specific path |
| `tests/unit/test_shell_portability.py` | every shell script | a script uses a Linux-only binary |
| `tests/unit/test_popdd_gate_lanes.py` | git config and the hooks dir | the gate's lane map is wrong |

These are the only enforcement for their rules, so they earn their place. But they make the suite
**non-hermetic by construction**, and §6.2 shows a live failure caused by nothing but a concurrent
editor.

---

## 3. The CI job matrix

`.github/workflows/ci.yml`, 766 lines on the branch under audit. Note that `main` at `c3cb68b` carries
a 534-line version and the main checkout's dirty tree carries a stale 449-line *sharded* version. The
sharding was removed by `01a5b7e1` — "ci: stop sharding the python suite, it made the lane produce
nothing (#274)". If you are reading a sharded `ci.yml`, you are reading a dead file.

### 3.1 The jobs

| Job | Line | Pool | Timeout | Runs when |
|---|---:|---|---:|---|
| `changes` | 150 | light | 5 | always |
| `guard` | 267 | light | — | **pull requests only** |
| `python` | 339 | heavy | 40 | `needs.changes.outputs.python == 'true'` |
| `engine` | 488 | heavy | 30 | engine paths changed |
| `dotnet` | 569 | heavy | 30 | dotnet paths changed |
| `nextjs` | 616 | light | 40 | web paths changed |
| `ops-console` | 686 | light | 40 | console paths changed |
| `ci-ok` | 748 | light | 5 | `always()` |

Pools resolve as `${{ vars.CI_HEAVY_RUNS_ON || vars.CI_RUNS_ON || 'ubuntu-latest' }}` and the light
equivalent — two self-hosted pools with a hosted fallback, so a fork with no variables still runs.

Global settings:

```yaml
concurrency:                                     # :111
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
env:                                             # :115
  PYTHON_VERSION: "3.14"                         # :116
  DOTNET_VERSION: "9.0"                          # :117
  PYTEST_XDIST_AUTO_NUM_WORKERS: "3"             # :118
```

`cancel-in-progress` is **false on `main`** and true on branches. A push to `main` must always
complete; a branch push may cancel its predecessor. That asymmetry is correct and worth preserving:
cancelling a `main` run leaves you unable to say whether `main` is green.

### 3.2 The `changes` job, and how skipping works safely

`changes` (`:150`) runs a path filter and emits one boolean output per lane. Every downstream job
gates on its own output. Two properties make this safe:

1. **It fails open.** If the filter itself errors, the outputs are `true` and every lane runs. A path
   filter that failed closed would skip proof silently — the change would appear proven when nothing
   ran.
2. **`ci-ok` treats `skipped` as pass** (`:748`, `needs: [changes, guard, python, engine, dotnet,
   nextjs, ops-console]`, `if: always()`). `ci-ok` is the **single required check** on branch
   protection. Without the skipped-is-pass rule, every PR that legitimately touches only Python would
   block forever on a `dotnet` job that never ran.

The combination is the whole design: `ci-ok` is the only thing branch protection knows about, so
adding a job requires adding it to `ci-ok`'s `needs` list or it is decorative.

### 3.3 The python job, step by step

**Venv, content-addressed and shared** (`ci.yml:419-` onward):

```bash
KEY="py${PYTHON_VERSION}-$(shasum -a 256 requirements.txt | cut -c1-16)"
uv venv --relocatable --python "${PYTHON_VERSION}" "$TMP"
# ... install ...
mv -n "$TMP" "$SHARED/$KEY"       # -n: never clobber a concurrent builder
python -c 'import pytest'          # verify the landed venv actually works
```

Three deliberate choices. `--relocatable` because the venv is built at `$TMP` and used at
`$SHARED/$KEY`, and a non-relocatable venv hardcodes its build path into every shebang. `mv -n` because
two jobs on the same self-hosted box can build the same key simultaneously and the loser must not
half-overwrite the winner. And the `import pytest` check because a venv that landed but is broken
would otherwise fail later, in a step that accuses the tests.

**Suite selection, with a zero-collected guard:**

```bash
files=$(git ls-files 'tests' | grep -E '(^|/)test_[^/]+\.py$' \
        | grep -v -e 'tests/test_ui_theme\.py$' -e 'tests/test_golden_set\.py$')
count=$(printf '%s\n' "$files" | grep -c . || true)
if [ "$count" -eq 0 ]; then echo "::error::collected no test files — the pattern is wrong"; exit 1; fi
python -m pytest -q $files -n 6 --tb=short -p no:warnings
```

**That `count -eq 0` check is a guard against a documented lie.** See §5.9.

**The golden gate is its own step:**

```bash
python -m pytest tests/test_golden_set.py -v --tb=short
```

Separate, `-v`, so the discrimination verdict is a visible line rather than a dot in a 5,000-test
stream. `CLAUDE.md` states the rule it enforces: "Golden-set regression gates all changes."

### 3.4 The `guard` job

Runs three checks, all PR-only:

| Script | Checks |
|---|---|
| `scripts/guard_protected_deletions.py` | a protected file was not deleted |
| `scripts/doc_lint.py --check --against "origin/${{ github.base_ref }}"` | docs do not point at missing/empty paths, and do not name a retired provider as current |
| `scripts/ci_capacity.py` | `ops/config/ci_capacity.yaml` agrees with `ci.yml` |

`scripts/ci_capacity.py`'s header states the general problem it solves: "Every previous fix for 'CI is
unreliable on this box' was a constant tuned to one observed mix... nothing compared the constants to
each other." It checks three things: that every job names one pool and reads that pool's variable; that
the widest heavy jobs fit `cpus - reserved_cpus`, with widths read back out of `ci.yml` rather than
restated; and, with `--live`, that the registered runners match.

**`guard` being PR-only is a real gap.** A direct push to `main` receives none of these three checks.

### 3.5 The live smoke workflow

`.github/workflows/e2e-live-smoke.yml`, 80 lines:

```yaml
on:
  workflow_run: { workflows: ["Deploy Store.Web"], types: [completed] }
  schedule: [{ cron: "0 7 * * *" }]
  workflow_dispatch:
concurrency: { group: e2e-live-smoke, cancel-in-progress: false }
```

Guard at `:42`:

```yaml
if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'
```

`WEB_BASE_URL: ${{ vars.WEB_BASE_URL || 'https://mumchimp.com' }}` at `:71`. Report uploaded
`if: always()`, retained 7 days.

**The header records why the trigger changed.** It used to run on `push: main` and raced the Fly
rolling update, so a green result proved the **old** image was fine. The `workflow_run` trigger waits
for the deploy to finish. The daily cron exists because breakage can arrive with **no commit behind
it** — on 2026-07-31 two packs became unbuyable with nothing pushed.

`cancel-in-progress: false` matters here: cancelling a live smoke leaves the site's status unknown.

### 3.6 What fails loudly versus silently

| Loud | Silent |
|---|---|
| pytest failure — job red, `ci-ok` red | vitest for Store.Web — **never runs in CI** |
| dotnet failure — exit code checked | ruff — **no CI step at all** |
| zero test files collected — explicit `::error::` and `exit 1` | `guard` on a push to `main` — job simply does not exist for that event |
| golden set — its own step, `-v` | a job added to `ci.yml` but not to `ci-ok`'s `needs` |
| Playwright — `retries: 0`, report uploaded | a `workflow_run` smoke whose upstream deploy was cancelled — the guard skips it, and a skip reads as pass |

---

## 4. Running the suites

### 4.1 Locally

```bash
.venv/bin/python -m pytest -q --tb=no -p no:warnings          # full, parallel
.venv/bin/python -m pytest -q -n 0 tests/unit/test_failover.py # one file, serial
.venv/bin/python -m pytest --collect-only -q -n 0 | tail -1    # count only
```

**Use `-n 0`, never `-p no:xdist`.** `pytest.ini:52` sets `addopts = -n auto --dist loadfile`, so
disabling the plugin leaves the flags with nothing to consume them:

```
error: unrecognized arguments: -n --dist
```

**`--dist loadfile` is a correctness requirement, not a speed tuning.** `pytest.ini`'s own comments
explain it: `config.load_config` writes `operator._MOAT_PRIMARY` process-globally, and every trust
decision reads it (`prospector/operator.py:1362-1396`). Splitting one file's tests across workers lets
one test's config land in another test's process. Keep the whole file on one worker.

`pytest.ini` also carries a second hard-won setting:

```ini
tmp_path_retention_policy = failed      # :69
```

The default retained tmp dirs from every run. Eight session roots accumulated, two of them holding
**4,296 and 3,339 directories**. A subsequent run spent **9m48s of CPU against 66m of wall clock** in
`os_scandir`/`os_unlink`/`os_stat` before a single test executed, and reported as
`step 'pytest' exceeded 2400s`. The symptom accused the test suite; the cause was directory cleanup.

Other suites:

```bash
cd store_platform/src/Store.Web    && npm test
cd store_platform/src/Ops.Console  && npm test
cd store_platform                  && dotnet test
cd store_platform/src/Store.Web    && WEB_BASE_URL=https://mumchimp.com npm run test:e2e
```

### 4.2 Through the gate

```bash
.venv/bin/python scripts/popdd_verify.py --staged     # preflight, no commit
```

Five lanes (`scripts/popdd_verify.py:234`), ordered cheapest-first at `:313`:

```python
LANE_ORDER = ("engine", "console", "web", "dotnet", "python")
```

`TEST_TIMEOUT_SECONDS = int(os.environ.get("POPDD_TEST_TIMEOUT", "2400"))` at `:86`.

**The gate is currently not installed:**

```bash
$ git config --get core.hooksPath
(unset)
$ test -e .git/hooks/pre-commit && echo PRESENT || echo ABSENT
ABSENT
```

So `git commit` runs no tests at all. Full detail in [developer.md](developer.md) §4 and
[principal-developer.md](principal-developer.md) §3.1.

---

## 5. The eight ways green has lied

Each of these happened here. Each has a guard now. The pattern across all eight is worth stating
before the list: **a green result is a claim about what ran, and every one of these was a case where
less ran than the green implied.**

### 5.1 The gate itself exited 0 without proving anything

**What was green:** `git commit` succeeded and printed a gate line.
**What was actually broken:** the old `.git/hooks/pre-commit` selected files with
`\.(py|ts|js|cs)$`. That regex does not match `.tsx`. Every React page in the storefront is `.tsx`.
**All 183 tracked Store.Web `.ts`/`.tsx` files committed ungated, for months.**
**Evidence:** `tests/unit/test_popdd_gate_lanes.py:4-8` — "The gate is the thing that decides whether
anything else is proven, so it is the one file whose defects are invisible: it fails by printing
'nothing to prove' and exiting 0."
**The guard:** `test_a_tsx_page_selects_the_web_lane()`, plus `WEB_EXTS` at `scripts/popdd_verify.py:112`
and `lanes_for` at `:316` written as a **pure function** so it can be asserted without running a suite.

**Related unfixed defect, found this session.** `scripts/popdd_verify.py:334-339`:

```python
elif path.startswith(OPS_REL) and ext in WEB_EXTS:
    lanes.add("ops")
```

This branch is unreachable — `OPS_REL == CONSOLE_REL` and the console branch is tested first — and
`"ops"` is not a key in `LANES` (`:234`) or in `LANE_ORDER` (`:313`). If it ever were reached it
would raise `KeyError`. Cost to close: delete two lines.

### 5.2 `dotnet test` exited 0 while tests failed

**What was green:** the shell's exit status after `dotnet test`.
**What was actually broken:** failing tests. `dotnet test` does not reliably signal failure through its
exit code alone.
**The guard:** the gate parses the summary line as well as checking the status.
`scripts/popdd_verify.py:188-199`, `_parse_dotnet`, reads
`"Passed!  - Failed:     0, Passed:   265, Skipped: 0, Total: 265"` with
`re.search(r"Failed:\s+(\d+),\s+Passed:\s+(\d+)", stdout)`, and `run_lane()` at `:595` checks the exit
code too. **Both, not either.** A parser alone would be fooled by a crash that printed no summary; an
exit code alone was already proven insufficient.

### 5.3 A pipe to `tail` reported `tail`'s exit status

**What was green:** `npm run build 2>&1 | tail` → `exit 0`.
**What was actually broken:** the build. `tail` succeeded; the build did not. In a pipeline the shell
reports the **last** command's status.
**Evidence and guard:** `scripts/setup_worktree.sh:173-174`, printed at the end of every worktree
setup, verbatim:

```
`npm run build | tail` reports the exit code of `tail`, not of the build.
Capture the build's own status first:  npm run build > /tmp/build.log 2>&1; echo "exit=$?"
```

This one generalises to every `cmd | tail` and `cmd | grep` in this repo, including the ones you write
to keep tool output small. Capture `$?` before the pipe, or use `set -o pipefail`.

### 5.4 A single-file regression guard reported green

**What was green:** a set-comparison test over the bundle's declared entries.
**What was actually broken:** markdown files were still reaching the buyer. The founder's words, on
2026-08-15: "i dont like md files at all, we are not selling to developers." The existing assertion
compared sets in a way that implied the property without asserting it, so it stayed green while the
observable behaviour was wrong.
**The guard:** `tests/unit/test_bundle_declared_entries.py:167-178`,
`class TestNoMarkdownReachesTheBuyer` — the observable property gets **its own explicit assertion**
rather than being a consequence of a set comparison elsewhere.
**The general rule:** if a property matters to a human, assert that property by name. Do not rely on
it falling out of another assertion.

### 5.5 A mock on the wrong transport hid a live API call

**What was green:** `test_publish.py`, which patched `requests.post`.
**What was actually broken:** `StripeProvisioner` calls the Stripe SDK, not `requests`
(`self._stripe.Product.create(...)`, `prospector/bridge.py:1284`). The patch intercepted nothing. **On
2026-08-07 the test suite created real products in a live Stripe account.**
**The guard:** `tests/conftest.py:207-255`, autouse, deletes `STRIPE_API_KEY`, `STRIPE_LIVE_API_KEY`
and `STORE_INTERNAL_API_KEY`, and sets `PROSPECTOR_DISABLE_DOTENV=1` because
`prospector.run._load_dotenv` (`prospector/run.py:2444`) re-reads them off disk.

**The same defect class, in the other direction:** `tests/unit/test_failover.py:58-72`,
`test_exa_transport_error_raises_not_empty`. A transport error swallowed into `[]` reads to the chain
as "found nothing, success", halting failover — which is how a dead Exa silently zeroed grounding.
Sibling: `test_dead_exa_fails_over_to_live_provider()`.

**Rule:** mock at the boundary the code actually crosses, and prove the mock is load-bearing by making
the unmocked path fail loudly.

### 5.6 A superset sample masked a severity-dependent check

**What was green:** `test_index_html_reads_in_the_reading_order()`, driven by a thin dossier fixture.
**What was actually broken:** the ordering assertion only covered the sections that thin dossier
happened to produce — **eleven of fourteen**. `BUNDLE_READING_ORDER` is "the superset, not a contract"
(`prospector/bridge.py:344`), so a fixture missing a field silently removes that section from the
assertion.
**Evidence:** `tests/unit/test_bundle_index_html.py:62-77`.
**The guard:** a `_rich_dossier()` fixture that gives each of three guards the field it asks for, so
the ordering assertion covers all fourteen sections.
**The general rule:** when a list is a superset, an assertion driven by a sample proves only the
sample. State the expected count, or drive from a fixture that is complete by construction.

### 5.7 A fixture with the wrong character proved nothing

**What was green:** the pack linter's house-dash check.
**What was actually broken:** two live packs (`13d41ccee9e96e2d`, `3e72d5a5f1a60068`) were held off the
shelf for an em-dash in `headline` **that never reached the storefront**. The catalogue's house-dash
rule was applied by `_normalise_catalog_payload` **after** the pack lint ran, so the linter graded a
value the buyer never receives. The same string passed as `title` (normalised at its call site) and
failed as `headline` (not normalised). One string, two verdicts.
**Evidence:** `tests/unit/test_bridge_house_dash_and_idempotency.py:3-8, 38-41`.
**The guard:** `test_a_headline_that_ships_clean_no_longer_fails_the_house_dash_check()`.
**The general rule, and it is the most valuable one here:** a check must grade **the bytes the
consumer receives**. The same defect class produced `fix(ops-status): grade SRC-6 against origin/main,
not the local index (#283)`, `fix(doc-lint): stop grading engine output against the git index (#267)`
and `fix(lint): grade the title and the listing page against the pack, not the shelf card (#285)`.
Four occurrences in four different tools.

### 5.8 A UI test that is only advisory

**What is green:** `tests/test_ui_theme.py::test_inject_theme_does_not_raise`.
**What it actually proves:** nothing. `tests/test_ui_theme.py:31-37`, the entire body:

```python
pass  # structural test — covered by test_theme_css_is_non_trivial_string
```

It cannot fail unless import fails. And `tests/test_ui_theme.py` is **excluded from the CI python job's
file list** (§2.3), so even that much does not run in CI.
**Why it is tolerated:** UI is moving, and a strict UI assertion that goes red on every visual change
gets deleted or ignored. Advisory is an honest state.
**The guard:** honesty. The comment names the test that carries the real assertion
(`test_theme_css_is_non_trivial_string`). The failure mode to avoid is an advisory test that **looks**
authoritative.

### 5.9 (bonus, measured this session) pytest exits 0 when it collects nothing

**What would be green:** `pytest -q <no files>` → `no tests ran`, exit 0 in some invocations, and a
CI step that only checks the exit code reports success.
**What is actually broken:** the file-selection pattern.
**The guard, live in `ci.yml`:**

```bash
count=$(printf '%s\n' "$files" | grep -c . || true)
if [ "$count" -eq 0 ]; then echo "::error::collected no test files — the pattern is wrong"; exit 1; fi
```

The guard sits in the job that builds the file list by `git ls-files` + `grep -E`, which is exactly the
place a pattern can silently match nothing. Verify it yourself by breaking the pattern locally and
watching the step fail with the `::error::` line rather than passing.

---

## 6. The numbers

### 6.1 Suite timing, measured twice

Identical command, identical clean tree, back to back on 2026-08-18:

```bash
time .venv/bin/python -m pytest -q --tb=no -p no:warnings
```

| Run | Verdict | pytest wall | shell wall | CPU |
|---|---|---:|---:|---:|
| 1 | `5041 passed, 6 skipped` | 1,059.41s (17m39s) | 18m11.19s | 151% |
| 2 | `2 failed, 5039 passed, 6 skipped` | 770.67s (12m50s) | 13m04.47s | 164% |

**A 37% timing swing on identical code**, from box contention alone. Any capacity constant fitted to a
single suite timing is fitted to noise. That is precisely the argument in `scripts/ci_capacity.py`'s
header, and why `PYTEST_XDIST_AUTO_NUM_WORKERS: "3"` (`ci.yml:118`) is a declared contract.

Against the gate's ceiling (`scripts/popdd_verify.py:86`, 2,400s): **44% and 32%**. The claim that "the
suite cannot fit the ceiling" is retired by measurement.

**On the dirty main checkout, same command:**

```
26 failed, 4853 passed, 4 skipped in 1289.94s (0:21:29)
```

Failures by file: 8 `test_publish_path_retries_empty_artifacts.py`, 7 `test_shell_portability.py`,
4 `test_tick_budget_rails.py`, and one each in `test_swallowed_failures_can_only_go_down.py`,
`test_doc_lint_never_increases.py`, `test_suite_is_machine_independent.py`,
`tests/scheduler/test_run_scheduled.py`, `tests/scheduler/test_drain_is_supervised.py`.

**Do not diagnose a red suite in a dirty tree.** 26 failures there, 0 in the clean worktree, on the
same commit lineage.

### 6.2 A flake caught in the act

Run 1 green, run 2 red, no code change between them. The two failures:

```
FAILED tests/unit/test_retired_terms.py::test_this_repo_is_clean_of_every_retired_term
FAILED tests/unit/test_doc_lint_never_increases.py::test_no_doc_gets_less_accurate_than_its_baseline
```

Diagnosed in one command:

```bash
$ .venv/bin/python -m ops.automations.retired_terms
FINDINGS: 2 line(s) name a retired term.
  docs/personas/content-management.md:231  [<retired term>]
  docs/personas/content-management.md:236  [<retired term>]
```

(The term itself is redacted here. `docs/personas/` is not on the `allow:` list in
`ops/config/retired_terms.yaml`, so writing it literally in this file would trip the very guard
this section is about. Run the command to see it.)

**Cause: a concurrent session writing a different document in the same worktree, between the two
runs.** Neither failure is a code defect. Both tests are correct and did their job.

This is the working definition of the non-hermetic category from §2.4. Three consequences:

1. **A red on one of those six tests is ambiguous** until you check whether the tree changed. The
   diagnosis is always to run the underlying tool directly (`ops.automations.retired_terms`,
   `scripts/doc_lint.py --json`) — it names the file and line in one line of output.
2. **"One session, one worktree" is a testing rule, not just a git rule.** Sharing a tree makes the
   suite's verdict a function of what someone else is typing.
3. **The value is still worth the cost.** `ops/config/retired_terms.yaml` holds exactly one live term
   — a retired payment provider, removed 2026-08-16, with a long `allow:` prefix list covering EF migrations,
   `MoneyRailConfigGateTests.cs`, `MoneyRailStatusTests.cs`, `tests/test_engine_bridge.py`, the
   declaration and its own test, `docs/archive/`, `docs/decisions/`, `specs/` and several named docs.
   That separation — business facts in YAML, engine in Python, history explicitly allowed — is the
   right shape and worth copying.

### 6.3 Other measured facts

Toolchain versions are in [developer.md](developer.md) §2. The QA-specific numbers:

| Fact | Value | Command |
|---|---|---|
| Collection time | 80.26s | `pytest --collect-only -q -n 0` |
| ruff, repo-wide | exit 1, **4 errors** | `.venv/bin/python -m ruff check` |
| doc-lint findings | **57 across 15 files** | `scripts/doc_lint.py --json` |

The four live ruff errors:

```
prospector/ops/readmodel.py:175:5   I001 Import block is un-sorted or un-formatted
scripts/estate_map.py:36:21         F401 `pathlib.Path` imported but unused
scripts/estate_map.py:198:17        E741 Ambiguous variable name: `l`
scripts/estate_map.py:209:19        E741 Ambiguous variable name: `l`
```

**Nothing currently blocks on these.** `ci.yml` has no ruff step, and the local gate is off. Two of
the four are auto-fixable (`--fix`).

---

## 7. Coverage

**There is no coverage measurement in this repo. Stated plainly, with the check:**

```bash
grep -i cov requirements.txt          # no match
git ls-files '.github/workflows/*.yml' | xargs grep -il 'coverage\|--cov'   # no match
git ls-files | grep -i '\.coveragerc\|coverage\.xml'                        # no match
```

No `pytest-cov`, no `--cov` flag anywhere, no `.coveragerc`, no coverage report artefact.

What exists instead is **density**: 4,361 test definitions over 666 Python source files, 6.5 per file.
That is a count of tests, not a measure of lines exercised. Nobody can currently say which of the
177,725 Python lines run under test.

**Where the gap probably bites, as a hypothesis with its check.** The three largest source files are
`prospector/run.py` (4,470 lines), `prospector/scheduler/run_scheduled.py` (2,916) and
`prospector/ops/console_api.py` (2,862), and the single longest function is
`prospector/bridge.py:683 publish_pass` at **874 lines** — the money rail's entry point.
HYPOTHESIS: `publish_pass` has branch coverage well below the file average, because its tests are
contract tests over its rendered output rather than tests of its branches. The check that settles it:

```bash
.venv/bin/pip install pytest-cov
.venv/bin/python -m pytest -q --cov=prospector --cov-report=term-missing -n 0 \
  tests/unit/test_bundle_declared_entries.py tests/unit/test_bundle_index_html.py
```

Cost to add coverage measurement: about an hour. Cost to act on the number: unbounded, which is why
the honest recommendation is to measure it once on the four money-adjacent files rather than adopt a
repo-wide coverage gate.

---

## 8. Flakiness and timing sensitivity

### 8.1 Known timing-sensitive tests

`pytest.ini`'s comments name one by name and record its fix:

> `test_a_huge_page_is_selected_in_reasonable_time` used `time.monotonic()`. It passed at 8 workers and
> **failed at 12** on identical code. It now uses `time.process_time()`.

**The rule that generalises:** under `-n auto` the worker count varies with the machine, so wall-clock
budgets vary with contention. A test that asserts "fast enough" must measure **CPU time**, not wall
time, or it is measuring the box.

The 37% run-to-run swing in §6.1 is the same phenomenon at suite scale.

### 8.2 The six tree-reading tests

Listed in §2.4. These are the ones that go red for reasons outside the diff. They are not flaky in the
usual sense — they are perfectly deterministic given a tree — but the tree is shared.

### 8.3 The slow parts

| Cost | Where | Why |
|---|---:|---|
| 80.26s | collection | 383 files imported before anything runs |
| variable, up to minutes | any tree-reading test | shells out to git or walks every tracked file |
| 9m48s CPU (worst observed) | tmp cleanup | fixed by `tmp_path_retention_policy = failed` (`pytest.ini:69`) |
| 1,059s / 771s | the full suite | see §6.1 |

To find the slowest tests on your box:

```bash
.venv/bin/python -m pytest -q --durations=25 --tb=no -p no:warnings 2>&1 | tail -30
```

### 8.4 The e2e stance

`retries: 0` and `fullyParallel: false` (§1.4). A red e2e is a red e2e. The suite runs against a live
site, so a retry that turns red into green hides an intermittent production fault.

---

## 9. Failure modes

| Symptom | Root cause | Fix |
|---|---|---|
| `error: unrecognized arguments: -n --dist` | `-p no:xdist` disabled the plugin that consumes `addopts` (`pytest.ini:52`) | Use `-n 0` |
| Suite red on 20+ tests, all unrelated | Running in the dirty main checkout | Run in a clean worktree (`scripts/setup_worktree.sh`) |
| `test_this_repo_is_clean_of_every_retired_term` red | Some file names a retired term; often another session's edit | `.venv/bin/python -m ops.automations.retired_terms` names file and line |
| `test_no_doc_gets_less_accurate_than_its_baseline` red | A doc gained a finding | `scripts/doc_lint.py --json`; fix the doc, do not edit the baseline |
| `step 'pytest' exceeded 2400s` with no slow test | tmp dir accumulation (8 roots, 4,296 dirs) | `pytest.ini:69` fixes it; clear stale roots if you predate it |
| A timing test passes on one box, fails on another | Wall-clock budget under variable `-n auto` | Measure `time.process_time()` |
| Build "passes" with `\| tail` | Pipeline reports `tail`'s status | Capture `$?` before the pipe, or `set -o pipefail` |
| `git commit` runs no tests | The gate is uninstalled | `test -e .git/hooks/pre-commit`; see [developer.md](developer.md) §4 |

---

## 10. Invariants a test in this repo must respect

| Invariant | Why | What breaks without it |
|---|---|---|
| One test file stays on one xdist worker | `config.load_config` writes `operator._MOAT_PRIMARY` globally (`operator.py:1362-1396`); 175 modules import `prospector.config` | Reds that reproduce nowhere and accuse the component |
| Timing assertions use CPU time | Worker count varies with the box | Parallelism turns correctness into a coin toss |
| Mocks sit on the boundary the code crosses | `bridge.py:1284` uses the Stripe SDK, not `requests` | Live API calls from the suite |
| A swallowed error is never a success value | An empty list reads as "found nothing, success" | Silent grounding outage |
| The exit code is checked **and** the output parsed | §5.2 | A failing suite reported as passing |
| Zero collected is an error, not a pass | §5.9 | Green CI proving nothing |
| Advisory tests say so in the body | `test_ui_theme.py:31-37` | A no-op test read as coverage |
| Ratchets, not absolutes, for legacy debt | 57 doc-lint findings exist today | Either an unachievable gate that gets disabled, or unmeasured growth |
| No live credential is reachable from a test | `conftest.py:207-255`, autouse | Real money moves |

---

## 11. How to write a test that fits this repo

### 11.1 The conventions, measured

Over all 4,361 test names:

| Property | Count | Share |
|---|---:|---:|
| Starts with an article (`test_a_`, `test_an_`, `test_the_`) | 1,802 | 41.3% |
| Contains `_is_not_` | 200 | 4.6% |
| Contains `_never_` | 221 | 5.1% |
| Five or more words | 3,884 | 89.1% |
| Mean words per name | 7.5 | — |

**Names are sentences.** Real examples:

```
test_a_failed_call_is_not_an_empty_answer
test_the_failed_brain_is_dropped_even_when_it_is_not_first_in_the_quality_chain
test_a_candidate_a_later_run_finished_is_not_counted_against_the_run_that_died
test_the_lines_under_repair_are_not_used_as_evidence_that_the_repair_is_truthful
```

**File names are sentences too:**

```
tests/unit/test_a_swallowed_bug_is_not_a_missing_measurement.py
tests/unit/test_a_rail_that_cannot_read_its_own_input_must_not_fail_open.py
tests/unit/test_a_newline_in_a_rationale_lost_the_whole_verdict.py
```

The point is diagnostic. When `test_a_failed_call_is_not_an_empty_answer` goes red, the name is the
bug report.

The 200 `_is_not_` names are one family pinning one defect class: a failure coerced into a benign
empty value. That class produced `store/dossiers/2102bacc6dd75cf9.kill.json` — a KILL on
`min_composite` whose seven checks all read `unverifiable, conf 0.0, "Verdict call failed;
fail-safe."`. A candidate killed by our own outage, in a dossier that reads as fully reasoned. The fix
was `retrieval_failed=True` (`prospector/verify.py:365`) firing the DEFER gate
(`prospector/verify.py:693`).

### 11.2 A worked example, from a real file

`tests/unit/test_retired_terms.py` is the model to copy. Its structure:

**1. The docstring states why the test exists, in one sentence with a citation:**

> "A guard that has only ever been seen to pass is not known to work
> (`docs/OPS_AUTOMATION_PRINCIPLES.md` R4)."

**2. It proves the guard fires, using a synthetic term.** The file uses `acmepay`, not the live
retired term. A test asserting on the live term would pass for the wrong reason — the repo is
already clean of it, so a
broken checker would look correct. A synthetic term in a synthetic repo forces the checker to actually
detect something.

**3. It builds its own repo.** A `_git_repo` helper creates a temporary git repo with known content, so
the assertions do not depend on the real tree.

**4. Each test is one sentence, one property:**

```
test_fires_on_the_broken_state
test_matches_regardless_of_case
test_an_allowed_path_is_history_not_a_finding
test_an_allow_prefix_does_not_exempt_a_sibling_path
test_a_clean_repo_is_ok
test_this_repo_is_clean_of_every_retired_term
```

Note the split: five tests prove the **mechanism** in a controlled repo, and exactly one applies it to
the **real tree**. That separation is what makes a red actionable — if only the last one is red, the
tree changed; if any of the first five are red, the checker broke.

Note also `test_an_allow_prefix_does_not_exempt_a_sibling_path`. The allow-list is prefix-based, so
`docs/archive/` must not exempt `docs/archive-notes.md`. That is the kind of edge a prefix match gets
wrong, and it has its own named test.

### 11.3 The checklist

1. **Name it as a sentence** describing the property, not the function. Five words or more.
2. **Put the incident in the docstring**, with a `file:line` or an artefact path.
3. **Prove the mechanism on synthetic data first**, then apply it to the real thing in a separate test.
4. **Assert the observable property explicitly.** Do not let it fall out of another assertion (§5.4).
5. **Grade the bytes the consumer receives**, not an intermediate representation (§5.7).
6. **Mock at the boundary the code crosses**, and prove the mock is load-bearing (§5.5).
7. **Use CPU time for any speed assertion** (§8.1).
8. **Add the file to `tests/unit/`** unless it is scheduler, ops, invariant, behavioural, integration,
   fault or simulation work.
9. **Run it serially once** (`-n 0`) and in parallel once. A test that only passes one way is a bug.
10. **If it must read the tree, say so in the docstring**, so a future red is diagnosed in seconds.

---

## 12. Open gaps and debt

| Gap | Evidence | Cost to close |
|---|---|---|
| 938 vitest assertions have no CI enforcement | `popdd_verify.py:257-260`; no `npm test` in the `nextjs` job | 3 lines in `ci.yml` + one timing measurement + a `ci_capacity.yaml` update |
| The local gate is uninstalled | `test -e .git/hooks/pre-commit` → ABSENT | One symlink + the decision to pay ~17 min per commit |
| ruff has no enforcement anywhere | 4 live errors, nothing red | One CI step |
| No coverage measurement | no `pytest-cov`, no `--cov`, no `.coveragerc` | ~1 hour to measure; §7 recommends scoping it to money-adjacent files |
| `guard` is PR-only | `ci.yml:269` | One line; expect an initial red from the 57 existing findings |
| Duplicate `_isolate_usage_wall` fixture | `conftest.py:48` and `:181`; the first is dead | ~30 min |
| Unreachable `"ops"` lane branch | `popdd_verify.py:334-339`; would `KeyError` if reached | Delete 2 lines |
| Suite is non-hermetic | §6.2, a live failure | Not fixable; enforce one-session-one-worktree |
| `test_ui_theme.py` is advisory **and** CI-excluded | `test_ui_theme.py:31-37`, `ci.yml` grep exclusion | Either give it a real assertion or delete it |

---

## 13. Where to look next

```bash
# Is anything actually enforcing quality right now?
git config --get core.hooksPath; test -e .git/hooks/pre-commit && echo GATE_ON || echo GATE_OFF
.venv/bin/python -m ruff check --output-format concise | tail -3
.venv/bin/python -m ops.automations.retired_terms
.venv/bin/python scripts/doc_lint.py --json | tail -5

# Run (full, then slowest 25, then the gate without committing)
.venv/bin/python -m pytest -q --tb=no -p no:warnings
.venv/bin/python scripts/popdd_verify.py --staged
```

| File | Why |
|---|---|
| `pytest.ini` | 69 lines, most of them comments recording incidents. Read it before changing any flag. |
| `tests/conftest.py` | Eleven autouse fences. The Stripe one is the sharpest lesson in the repo. |
| `scripts/popdd_verify.py` | The gate. Lanes at `:234`, order at `:313`, timeout at `:86`, dotnet parser at `:188`. |
| `.github/workflows/ci.yml` | The job matrix. `changes` at `:150`, `ci-ok` at `:748`. |
| `.github/workflows/e2e-live-smoke.yml` | Why post-deploy triggers beat push triggers. |
| `tests/unit/test_retired_terms.py` | The model for a new test file. |
| `store_platform/src/Store.Web/playwright.config.ts` | 19 lines, every one a decision. |
| [developer.md](developer.md) | Setup, worktrees, the gate, CI, and the traps that cost time. |
| [principal-developer.md](principal-developer.md) | Enforced versus written down; the 9089ebc incident at full depth. |
| [../ESTATE_MAP.md](../ESTATE_MAP.md) | The factual spine. |
