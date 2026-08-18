# The platform for the QA / test engineer

The question that defines this seat here is not "is it tested". It is **"what does green mean, and
where has green lied"** — because in this estate green has lied in at least eight distinct ways, and
every one of them is now a named test.

## The shape of the suite

- **369 test files, roughly 5000 tests**, Python.
- `pytest.ini:42` sets `addopts = -n auto --dist loadfile`. Nothing runs serially.
- Ops console: 13 vitest files, 115 tests, ~23s.
- Store API: `dotnet test` under `store_platform/src/Store.Tests/`.

Test files are named as sentences stating the invariant. `test_a_failed_call_is_not_an_empty_answer.py`,
`test_an_unreadable_file_is_not_an_empty_one.py`, `test_a_rail_that_cannot_read_its_own_input_must_not_fail_open.py`.
**Reading `ls tests/unit/` is the fastest defect-history lesson available here.** The dominant theme
is one class: an absence silently converted into a zero, which reads as a healthy system with nothing
to report.

## What CI actually gates

`.github/workflows/ci.yml`, eight jobs:

| Job | What it protects |
|---|---|
| `changes` | Decides which lanes run, from the diff |
| `guard` | `scripts/guard_protected_deletions.py` — a protected file cannot vanish quietly |
| `python` | The full suite, sharded 3 ways by file (`file N → shard N mod 3`) |
| — golden gate | `tests/test_golden_set.py` on shard 0. Mixed-sector discrimination cannot regress |
| `engine` | Import, lint, generation budget, and the lane map. **Runs on every pull request, no paths filter** |
| `dotnet` | Store API build and tests |
| `nextjs` | Storefront typecheck, vitest, build |
| `ops-console` | Console typecheck, vitest, build |
| `ci-ok` | Fails unless every job passed or was skipped |

Two design points worth knowing. The shard split is deterministic and **cannot drop a test** — one
`git ls-files` pattern feeds every shard and each file lands in exactly one; if a shard collects
nothing the step **fails loudly rather than passing empty.** And `engine` deliberately has no paths
filter, because a paths filter is one more thing that can be wrong about which files steer the
daemon.

That job exists because of a specific incident. Commit `9089ebc` on 2026-08-13 raised
`generation.candidates_per_signal` from 5 to 50 in `config.yaml`. Nothing checked it: `.yaml` matched
no lane in the local gate, and the main checkout had no `pre-commit` hook installed at all. Every
tick afterwards force-exited at the 3h deadline mid-generation. **The engine produced nothing for 21
consecutive ticks, and the founder found it by asking.** A local hook can be uninstalled, bypassed
with `--no-verify`, or never installed. A required check cannot.

## The eight ways green has lied here

This is the section to read before signing anything off.

| The false green | What actually happened |
|---|---|
| **`pytest` exits 0 when it collects nothing** | A pattern matched no files and the run reported success |
| **`dotnet test` reports exit 0 while failing** | Read the summary line, not the exit code |
| **`cmd 2>&1 \| tail` reports tail's status** | A failed build reads as exit 0. Capture the status before any pipe |
| **A single-file regression guard reported green** | It was measuring one file |
| **A green local suite can be worthless two ways** | Machine-dependent state, and a suite that shells out reads the tree mid-run |
| **A CI check that never ran** | `runner_name == ""` means no runner picked it up. A close/reopen once cancelled in-flight builds and the queue merged nothing |
| **`float()` on a `MagicMock` returns 1.0** | The assertion passed on nothing |
| **A mock on the wrong transport** | Hid a live API call inside a "unit" test |

Two more that are subtler:

- **A redundant mechanism makes a test pin the wrong thing.** When two paths both produce the right
  answer, the test stays green after you delete the one that matters.
- **A superset sample masked a severity-dependent check.** The sample contained the right rows and
  still could not distinguish the case under test.

## Test hygiene rules specific to this repo

- **Never run the suite against the canonical store.** `store/` and `storage/` are tracked runtime
  state that pytest writes to. This is also why you must never stage every file in a worktree.
- **`tests/test_suite_is_machine_independent.py` exists** because a suite that passes only on one
  laptop is not a suite.
- **UI tests are advisory while the UI is moving.** They are deliberately not a hard gate, and
  treating them as one produces churn rather than quality.
- **Storefront end-to-end tests need a live API.** They fail meaninglessly without one.
- **Playwright at one viewport hides mobile.** A fold test that passes locally can fail in CI.
- **Progressive disclosure makes a guard test vacuous** — the element is not in the DOM, so the
  assertion about it passes.
- **A test suite once messaged the founder.** The coordinator's tests exercised a real sender. An
  in-process fence cannot stop a subprocess sender.

## The local gate

`scripts/popdd_verify.py`. Preflight without committing:

```bash
.venv/bin/python scripts/popdd_verify.py --staged
```

Whether it is installed is a **command, not a paragraph**:

```bash
git config --get core.hooksPath          # if set, THAT directory wins
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

Timings, both real: clean `main` measured 1.7s ruff plus 445.5s pytest (3925 passed, 3 skipped)
against the 2400s ceiling at `scripts/popdd_verify.py:86`. A merged tree with four CI jobs sharing
the box measured 1281s (4612 passed, 3 skipped). Both pass. **Time it again before quoting either.**

`ruff` runs repo-wide (`scripts/popdd_verify.py:166`), so one unformatted file anywhere walls every
commit in every worktree.

## The rule

**Never merge while a check is queued or in progress.**

## What to read next

- [developer.md](developer.md) — worktrees, the gate, and shipping.
- [principal-developer.md](principal-developer.md) — enforced versus written down.
- [sre-on-call.md](sre-on-call.md) — the probes that lie in production, which are the same class.
