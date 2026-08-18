# Principal Developer

**What this is.** An audit of the engineering system itself: how big the codebase is, which rules
are mechanically enforced and which are only written down, what the change-failure record actually
says, where complexity has concentrated, and what to invest in next.
**Read this if** you are accountable for whether this codebase stays changeable, or you are about
to argue for a process change and need the numbers.
**Sibling seats:** [developer.md](developer.md) (day one to first merged change),
[qa-test-engineer.md](qa-test-engineer.md) (how quality is verified and how it has lied),
[README.md](README.md) (all twenty seats), [../ESTATE_MAP.md](../ESTATE_MAP.md) (the factual spine).

---

## 0. Provenance

Measured **2026-08-18** in the clean worktree `.../scratchpad/wt-estate` at `192aa0e4` on branch
`docs/estate-map`, a descendant of `main` at `c3cb68b`. Every command is given inline. Nothing here
was carried from memory.

The main checkout `/Users/chidionyema/Documents/code/prospector` had **132 dirty tracked files** at
the time. Do not measure there. §5 shows what that costs you.

---

## 1. The codebase, measured

### 1.1 Size and language split

```bash
git ls-files '*.py' | wc -l                    # 666
git ls-files '*.py' | xargs cat | wc -l        # 177725
```

| Language | Files | Lines | Share of source lines |
|---|---:|---:|---:|
| Python | 666 | 177,725 | 65.9% |
| Markdown | 200 | 47,679 | 17.7% |
| C# | 197 | 31,804 | 11.8% |
| TypeScript React | 153 | 31,564 | 11.7% |
| TypeScript | 173 | 24,957 | 9.3% |
| Shell | 44 | 4,380 | 1.6% |
| YAML | 7 | 2,955 | 1.1% |

(Shares are of the 269,700 lines above; they exceed 100% only if you double-count, so read them as
relative weights.)

**Markdown is the second-largest artefact in the repo.** 47,679 lines of prose against 177,725 of
Python. That is a 1:3.7 ratio. This is deliberate — the operating rules encode incidents — but it is
also the single largest un-compiled surface in the estate. §3 covers what does and does not check it.

### 1.2 Per-package Python weight

```bash
git ls-files '*.py' | xargs wc -l | sort -rn | head -16
```

| Lines | File |
|---:|---|
| 4,470 | `prospector/run.py` |
| 2,916 | `prospector/scheduler/run_scheduled.py` |
| 2,862 | `prospector/ops/console_api.py` |
| 2,511 | `prospector/retrieval.py` |
| 2,477 | `prospector/bridge.py` |
| 2,147 | `prospector/pack_linter.py` |
| 1,791 | `prospector/operator.py` |
| 1,529 | `prospector/artifacts.py` |
| 1,269 | `prospector/verify.py` |
| 1,224 | `prospector/config.py` |
| 1,106 | `prospector/generate.py` |
| 1,075 | `prospector/dossier.py` |
| 1,021 | `prospector/ops/readers.py` |
| 920 | `prospector/ops/runner.py` |
| 917 | `prospector/ops/runs.py` |

The top five files are 15,236 lines — **8.6% of all Python in 0.75% of the files.**

### 1.3 Tests

| Metric | Value | Command |
|---|---:|---|
| Test files | 383 | `git ls-files 'tests/**/test_*.py' 'tests/test_*.py' \| wc -l` |
| `def test_` definitions | 4,361 | `... \| xargs grep -hE '^\s*def test_' \| wc -l` |
| Tests collected | 5,047 | `pytest --collect-only -q -n 0` |
| Collection time alone | 80.26s | same |
| vitest files / calls | 98 / 938 | `git ls-files '*.test.ts' '*.test.tsx' '*.test.mts'` |
| xUnit `[Fact]`/`[Theory]` | 309 in 41 files | `git ls-files 'store_platform/src/Store.Tests/*.cs' \| xargs grep -hE '^\s*\[(Fact\|Theory)'` |
| Playwright specs | 4 | `git ls-files 'store_platform/src/Store.Web/e2e/*'` |

Total automated assertions across all four runners: **5,047 + 938 + 309 + 4 ≈ 6,298**.

Test-to-source ratio for Python: 4,361 tests against 666 source files is **6.5 tests per file**.
That is high. §4 asks whether they pin the right things.

---

## 2. Where complexity has concentrated

### 2.1 Function length

Measured with an `ast` walk over every tracked `.py` file:

```
total functions: 8607
functions > 100 lines: 104   (1.2%)
functions > 200 lines:  28   (0.33%)
```

The fifteen longest:

| Lines | Location | Function |
|---:|---|---|
| 874 | `prospector/bridge.py:683` | `publish_pass` |
| 661 | `prospector/generate.py:316` | `generate` |
| 639 | `prospector/run.py:1494` | `run_signal` |
| 527 | `prospector/run.py:2687` | `_cmd_resume` |
| 463 | `prospector/bridge.py:1698` | `_create_bundle` |
| 338 | `prospector/dossier.py:738` | `render_markdown` |
| 336 | `prospector/run.py:4131` | `main` |
| 323 | `tools/experiments/e13_proxy_claim_reframe.py:187` | `main` |
| 299 | `tools/publish_passes.py:162` | `main` |
| 284 | `tools/retitle_catalogue.py:415` | `main` |
| 272 | `tools/experiments/l1_corpus_reuse_overlap.py:177` | `run` |
| 267 | `prospector/run.py:1219` | `vet_candidate` |
| 259 | `prospector/golden.py:116` | `run_golden_set` |
| 253 | `prospector/verify.py:1017` | `_verify_inner` |
| 250 | `prospector/verify.py:472` | `verdict_for` |

**`publish_pass` at 874 lines is the money-adjacent one.** `prospector/bridge.py` is described in
`CLAUDE.md` as "the money rail's entry point: one `PriceDecision` mints the provider Price object
AND writes the catalogue row, so the two cannot drift". That coupling is deliberate and correct — a
drift charges the buyer and then fails the fulfilment fence. But it means the single function that
must not drift is also the longest function in the repo, and its length is what makes a review of it
expensive.

### 2.2 Import fan-in

```bash
git ls-files '*.py' | xargs grep -hoE 'from prospector\.[a-z_.]+ import|import prospector\.[a-z_.]+' \
  | sed -E 's/^from //; s/^import //; s/ import$//' | sort | uniq -c | sort -rn | head -12
```

| Importers | Module |
|---:|---|
| 175 | `prospector.config` |
| 153 | `prospector.models` |
| 87 | `prospector.operator` |
| 75 | `prospector.scheduler` |
| 67 | `prospector.retrieval` |
| 61 | `prospector.ops` |
| 46 | `prospector.run` |
| 40 | `prospector.bridge` |
| 37 | `prospector.store` |
| 37 | `prospector.errors` |
| 32 | `prospector.verify` |
| 31 | `prospector.generate` |

`prospector.config` and `prospector.models` are the spine, which is the right shape: configuration
and contracts should be the most-imported things. The concerning entry is **`prospector.run` at 46
importers**. `run.py` is the CLI entry point — 4,470 lines — and 46 modules reach into it. That
inverts the dependency direction: the orchestrator should depend on the library, not the other way
round.

**`prospector.config` has a second property that makes its fan-in load-bearing.** `config.load_config`
writes process-global state: `operator._MOAT_PRIMARY` (`prospector/operator.py:1362-1396`), read by
every trust decision. That is why `pytest.ini:52` must pin `--dist loadfile` — 175 importers of a
module with global side effects cannot be safely split across xdist workers mid-file.

### 2.3 Churn

```bash
git log -300 --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn | head -20
```

| Changes in last 300 commits | File |
|---:|---|
| 53 | `config.yaml` |
| 33 | `store_platform/src/Store.Web/src/pages/index.tsx` |
| 30 | `store_platform/src/Store.Web/src/pages/pack/[id].tsx` |
| 28 | `prospector/run.py` |
| 26 | `store_platform/src/Store.Web/src/pages/kill-log.tsx` |
| 26 | `prospector/config.py` |
| 25 | `prospector/scheduler/run_scheduled.py` |
| 25 | `prospector/pack_linter.py` |
| 24 | `prospector/bridge.py` |
| 23 | `.github/workflows/ci.yml` |
| 21 | `store_platform/src/Store.Web/src/pages/how-it-works.tsx` |
| 21 | `prospector/retrieval.py` |
| 20 | `prospector/operator.py` |
| 19 | `prospector/verify.py` |

**`config.yaml` is the single most-changed file in the repo — 53 changes in 300 commits, once every
5.7 commits.** It is 2,550 lines. It is also, until 2026-08-14, the file the commit gate covered
with **nothing**: `.yaml` is not in `SOURCE_EXTS` (`scripts/popdd_verify.py:97`). §6 is what that
cost.

**`.github/workflows/ci.yml` at 23 changes is the second signal.** CI has been re-tuned roughly once
per 13 commits. `scripts/ci_capacity.py` exists because each of those re-tunes was a constant fitted
to one observed mix, and nothing compared the constants to each other.

The high-churn × high-complexity intersection is exactly four files: `run.py`, `config.py`,
`run_scheduled.py`, `bridge.py`. Those are where a review is worth the most.

---

## 3. Enforced versus written down

This is the central question for this seat. A rule that only lives in prose is a suggestion.

| Rule | Where stated | Mechanically enforced? | By what |
|---|---|---|---|
| Every source file in a commit is proven by some lane | `CLAUDE.md`, `popdd_verify.py:97` | **Not right now** | The hook exists but is **not installed** (§3.1). When installed: `SOURCE_EXTS` + `lanes_for`. |
| Engine config changes run a dry-run tick | `popdd_verify.py:138` | **Not right now** | Same hook. |
| Python must pass ruff | `ruff.toml` | **Partly** | Repo-wide ruff currently reports 4 errors and nothing blocks on them; the `python` CI job does not run ruff. |
| Docs must not point at missing or empty paths | `scripts/doc_lint.py` | **Yes, on PRs** | `ci.yml:267` `guard` job. Never on push to main. |
| Docs must not name a retired provider as current | `scripts/doc_lint.py` check 3 | **Yes, on PRs** | same |
| Retired business terms must not come back | `ops/config/retired_terms.yaml` | **Yes** | `ops/automations/retired_terms.py` + `tests/unit/test_retired_terms.py::test_this_repo_is_clean_of_every_retired_term` |
| Doc accuracy must not regress | `docs/doc_lint_baseline.json` | **Yes** | `tests/unit/test_doc_lint_never_increases.py` — a ratchet |
| Swallowed failures must not increase | — | **Yes** | `tests/unit/test_swallowed_failures_can_only_go_down.py` — a ratchet |
| Protected files must not be deleted | — | **Yes, on PRs** | `scripts/guard_protected_deletions.py` in the `guard` job |
| CI capacity contract holds | `ops/config/ci_capacity.yaml` | **Yes, on PRs** | `scripts/ci_capacity.py` |
| Golden-set discrimination must not regress | `CLAUDE.md` "Golden-set regression gates all changes" | **Yes** | `ci.yml` runs `tests/test_golden_set.py` as its own step with its own verdict line |
| No live payment credentials in tests | — | **Yes** | `tests/conftest.py:207-255` autouse fixture |
| claude_cli is never on the non-critical chain | `CLAUDE.md` | **Yes** | `tests/unit/test_claude_is_never_on_the_noncritical_chain.py`, plus `_noncritical_order` stripping it |
| The suite must be machine-independent | — | **Yes** | `tests/test_suite_is_machine_independent.py` |
| Scripts must be portable to macOS | — | **Yes** | `tests/unit/test_shell_portability.py` (parametrised over `flock`, `free`, `ionice`, `lsb_release`, `pidof`, `setsid`, `taskset`) |
| No markdown reaches the buyer | founder directive 2026-08-15 | **Yes** | `tests/unit/test_bundle_declared_entries.py:167` `TestNoMarkdownReachesTheBuyer` |
| Ops Console action lists agree | — | **Yes** | `store_platform/src/Ops.Console/tests/act.test.ts` |
| Storefront vitest suite passes | `popdd_verify.py:256` | **No** | The `nextjs` CI job runs typecheck and build but **not** `npm test` (stated at `popdd_verify.py:257-260`). With the local gate off, 938 assertions have no enforcement point. |
| One session, one worktree | `CLAUDE.md` | **No** | Convention. 42 worktrees registered, 22 prunable. |
| Never merge onto a red main | `CLAUDE.md` | **No** | Convention. |
| Answer-first reply format, plain English | `CLAUDE.md` | **No** | Convention, for humans and agents. |
| Proof discipline (every claim carries a receipt) | `CLAUDE.md` | **No** | Convention. This document is an attempt to honour it. |
| Production runs a clean mirror of main | `CLAUDE.md` | **Partly** | `scripts/live_checkout.py --update` refuses a dirty live checkout. Nothing forces anyone to run it. |
| There is exactly one `store/` | `CLAUDE.md`, `config.store_root()` | **Partly** | `PROSPECTOR_STORE_DIR` on the plists pins it; a new `Path(__file__)`-derived constant would still slip through. HYPOTHESIS: a grep-based test would catch it. The check that would confirm the gap: `git ls-files '*.py' \| xargs grep -n '__file__.*"store"'`. |

### 3.1 The headline: the local gate is off

```bash
$ git config --get core.hooksPath
(unset)
$ test -e .git/hooks/pre-commit && echo PRESENT || echo ABSENT
ABSENT
$ ls .git/hooks | grep pre-commit
pre-commit.DISABLED-2026-08-14
pre-commit.sample
```

**`git commit` in this estate runs no proof gate.** Not "runs a weak one" — runs none.

The stated reason it was disabled was cost: the suite was believed to take ~3,185s serially against
the gate's 2,400s ceiling (`scripts/popdd_verify.py:86`), so every commit paid ~40 minutes to be
refused. **That number is dead.** Measured today, twice, in the clean worktree with the same command:

```
5041 passed, 6 skipped in 1059.41s (0:17:39)     # run 1
2 failed, 5039 passed, 6 skipped in 770.67s (0:12:50)   # run 2, same tree, same afternoon
```

1,059s and 771s against a 2,400s ceiling — **44% and 32%**. `pytest.ini:52` sets
`addopts = -n auto --dist loadfile`, so nothing has run serially since that line landed. The gate can
pass. Re-arming it is a one-line symlink and a decision, not an engineering project.

The two failures in run 2 are covered in §5. They are not a reason to leave the gate off; they are
the strongest argument for turning it on.

### 3.2 What CI enforces that the gate does not, and vice versa

| Check | Local gate | CI |
|---|---|---|
| ruff | yes (scoped to staged files) | **no** |
| full pytest | yes | yes (unsharded, `-n 6`) |
| golden set | inside pytest | **separate step with its own verdict** |
| dry-run engine tick | yes | yes (`engine` job) |
| Store.Web vitest | yes | **no** |
| Store.Web typecheck + build | yes (typecheck only) | yes (both) |
| Ops.Console vitest | yes | yes |
| dotnet tests | yes | yes |
| doc lint | **no** | yes, PRs only |
| protected deletions | **no** | yes, PRs only |
| CI capacity contract | **no** | yes, PRs only |
| Playwright against live | no | separate workflow, post-deploy and daily |

Two asymmetries worth naming. **ruff has no CI enforcement at all** — if the local gate is off, it is
off everywhere. And **the `guard` job is `if: github.event_name == 'pull_request'`** (`ci.yml:269`),
so a direct push to `main` is never doc-linted. A repo whose docs are 18% of its source lines should
not have its only prose compiler gated on the one event type that bypasses it.

---

## 4. Test quality: what 4,361 tests actually pin

### 4.1 Tests are named as sentences here, and the convention is real

Measured over all 4,361 `def test_` names:

| Property | Count | Share |
|---|---:|---:|
| Starts with an article (`test_a_`, `test_an_`, `test_the_`) | 1,802 | 41.3% |
| Contains `_is_not_` | 200 | 4.6% |
| Contains `_never_` | 221 | 5.1% |
| Five or more words | 3,884 | 89.1% |
| Mean words per name | 7.5 | — |

89% of test names are five words or more, averaging 7.5. These are not `test_foo_returns_bar`.
Twelve of the longest, verbatim:

```
test_a_listing_page_that_opens_with_a_subject_line_is_an_email_under_the_wrong_heading
test_the_shipped_config_turns_the_exclusion_off_while_the_bugged_kills_are_worked_off
test_the_retired_expiry_line_is_rewritten_in_the_document_the_pack_is_rendered_from
test_the_models_own_words_for_i_could_not_work_this_out_are_not_printed_as_a_figure
test_with_no_channel_section_it_names_the_document_rather_than_the_wrong_section
test_the_lines_under_repair_are_not_used_as_evidence_that_the_repair_is_truthful
test_the_fallback_rescues_a_total_extraction_failure_without_readmitting_chrome
test_the_failed_brain_is_dropped_even_when_it_is_not_first_in_the_quality_chain
test_a_failed_claim_check_buys_exactly_one_repair_turn_that_sees_the_violations
test_a_converted_pack_is_a_no_op_and_never_gets_an_empty_reader_written_over_it
test_a_candidate_a_later_run_finished_is_not_counted_against_the_run_that_died
test_the_vetted_to_ruled_loss_is_an_outage_and_is_excluded_from_dropped_total
```

**Assessment: this is the single healthiest thing about the engineering system.** A test named
`test_a_failed_call_is_not_an_empty_answer` states an invariant. When it goes red, the name is the
diagnosis. The 200 `_is_not_` names are a family: they all pin the same class of defect, where a
failure was silently coerced into a benign-looking empty value. That is the defect class that
produced `store/dossiers/2102bacc6dd75cf9.kill.json` — a KILL whose seven checks all read
`unverifiable, conf 0.0, "Verdict call failed; fail-safe."`, a candidate killed by our own outage in
a dossier that reads as fully reasoned.

### 4.2 What they pin, by category

Sampling the 302 files in `tests/unit/` by name, the suite clusters into five kinds:

1. **Failure-is-not-success guards** (~200 files by the `_is_not_` / `_never_` markers).
   `test_a_failed_call_is_not_an_empty_answer.py`, `test_an_exhausted_brain_is_not_an_empty_discovery.py`,
   `test_an_unreadable_file_is_not_an_empty_one.py`, `test_a_failed_grade_is_not_a_zero.py`.
2. **Ratchets** — the tree is graded against a committed baseline.
   `test_doc_lint_never_increases.py`, `test_swallowed_failures_can_only_go_down.py`.
3. **Fences** — a capability the code must not have.
   `test_claude_is_never_on_the_noncritical_chain.py`, `test_dry_run_gate_mints_nothing.py`,
   `test_shell_portability.py`.
4. **Contract tests over rendered output** — `test_bundle_declared_entries.py`,
   `test_bundle_index_html.py`, `test_bridge_house_dash_and_idempotency.py`.
5. **The gate testing itself** — `test_popdd_gate_lanes.py`, `test_popdd_gate_cannot_wedge.py`.

Category 5 deserves a note. `scripts/popdd_verify.py` is the thing that decides whether anything else
is proven, so its defects are invisible: it fails by printing "nothing to prove" and exiting 0. It
did exactly that for months. `tests/unit/test_popdd_gate_lanes.py:4-8` records it: the old
`.git/hooks/pre-commit` matched `\.(py|ts|js|cs)$`, which does not match `.tsx`, so **all 183 tracked
Store.Web `.ts`/`.tsx` files committed ungated.** `lanes_for` is now a pure function precisely so it
can be asserted without running a suite.

### 4.3 The weaknesses

**Weakness 1: the suite reads its own tree.** Several tests shell out to git or read tracked files
from disk (`test_retired_terms.py`, `test_doc_lint_never_increases.py`,
`test_suite_is_machine_independent.py`, `test_shell_portability.py`). They are correct and valuable —
they are the only enforcement for whole categories of rule — but they make the suite **non-hermetic**.
A concurrent session editing a doc turns them red mid-run. §5 has a live example from this session.

**Weakness 2: three of the top five largest source files have no dedicated test file.**
HYPOTHESIS, and the check that settles it:
`for f in run.py bridge.py retrieval.py console_api.py pack_linter.py; do echo "$f: $(git ls-files 'tests' | xargs grep -l "${f%.py}" | wc -l)"; done`.
Coverage of `bridge.publish_pass` in particular is spread across contract tests over its rendered
output rather than concentrated on the 874-line function itself.

**Weakness 3: no coverage measurement exists.** See [qa-test-engineer.md](qa-test-engineer.md) §7.
`requirements.txt` carries no `pytest-cov`, and no workflow computes a coverage number. So "6.5 tests
per source file" is a density figure, not a coverage figure, and nobody can currently say which of
the 177,725 Python lines are exercised.

---

## 5. Change-failure evidence

### 5.1 The commit record

```bash
git rev-list --count HEAD                                  # 726
git log -400 --pretty=%s | sed -E 's/[(:].*//' | sort | uniq -c | sort -rn
```

Over the last 400 commits:

| Count | Prefix | Share |
|---:|---|---:|
| 172 | `fix` | 43.0% |
| 74 | `feat` | 18.5% |
| 19 | `merge` | 4.8% |
| 17 | `docs` | 4.3% |
| 15 | `ci` | 3.8% |
| 8 | `perf` | 2.0% |
| 7 | `test` | 1.8% |
| 7 | `chore` | 1.8% |

**43% of commits are fixes; 18.5% are features. The ratio is 2.3 fixes per feature.**

That number needs care before it becomes a verdict. Two things inflate it honestly: this repo commits
a fix for every incident *with its regression test*, which a repo that quietly patches would not; and
the storefront and CI were both under active repair during this window. Two things it genuinely
indicates: the system is being changed faster than it is being stabilised, and the top-churn files
(§2.3) are the ones absorbing it.

### 5.2 Reverts

```bash
git log --oneline -i --grep='^Revert' | wc -l     # 7
```

Seven in 726 commits, **0.96%**. That is low. But six of the seven are *merge* commits that happen to
contain the word, and only one is a genuine revert:

```
0aaf4fbc revert: landing page layout to stable state (efa863c)
```

So the true revert rate is **1 in 726, 0.14%**. Read that as: this team does not revert, it fixes
forward. Which is consistent with the 43% fix rate — the same defects are being paid for in `fix`
commits rather than `revert` ones.

### 5.3 Fix-of-fix

Searching the last 400 subjects for repair language (`again|still|really|actually|properly|for real|second`)
finds 20. The clearest cases, each of which is a second attempt at ground already covered:

| Commit | Subject | What it re-fixed |
|---|---|---|
| `#272` | `fix(ci): make main green again` | main had been made green before |
| `#283` | `fix(ops-status): grade SRC-6 against origin/main, not the local index` | a status check that read the wrong reference |
| `#267` | `fix(doc-lint): stop grading engine output against the git index` | the same defect class as `#283`, in a different tool |
| `#285` | `fix(lint): grade the title and the listing page against the pack, not the shelf card` | the same defect class again, in a third tool |
| — | `fix(scheduler): budget the tick against the time the drain LEFT, not the whole deadline` | a budget that had already been "fixed" once |
| `#292` | `docs(ops): correct two P0 status lines against what is on disk` | prose that had drifted from the probe |

**There is a pattern here, and it is worth naming as a general lesson: this system keeps grading the
wrong artefact.** `#283` graded the local index instead of `origin/main`. `#267` graded engine output
against the git index. `#285` graded the shelf card instead of the pack. The house-dash incident
graded a value the buyer never receives, because `_normalise_catalog_payload` ran *after* the pack
lint — one string, two verdicts, and two live packs (`13d41ccee9e96e2d`, `3e72d5a5f1a60068`) held off
the shelf by it (`tests/unit/test_bridge_house_dash_and_idempotency.py:3-8`).

Every one of those is the same mistake: **the check ran against a representation of the thing rather
than the thing that ships.** That is the highest-value review question in this codebase. When someone
adds a gate, ask what exact bytes it reads, and whether those are the bytes the consumer receives.

### 5.4 Flakiness, observed live

Two runs of the **identical command in the identical clean tree**, back to back on 2026-08-18:

| Run | Result | Reported | Wall | CPU% |
|---|---|---:|---:|---:|
| 1 | 5041 passed, 6 skipped | 1,059.41s | 18m11s | 151% |
| 2 | **2 failed**, 5039 passed, 6 skipped | 770.67s | 13m04s | 164% |

The two failures:

```
FAILED tests/unit/test_retired_terms.py::test_this_repo_is_clean_of_every_retired_term
FAILED tests/unit/test_doc_lint_never_increases.py::test_no_doc_gets_less_accurate_than_its_baseline
```

**Root cause, confirmed:**

```bash
$ .venv/bin/python -m ops.automations.retired_terms
FINDINGS: 2 line(s) name a retired term.
  docs/personas/content-management.md:231  [<retired term>]
  docs/personas/content-management.md:236  [<retired term>]
```

A **concurrent session writing a different persona document in this same worktree** introduced two
lines naming a retired term, between run 1 and run 2. Both failures are that. Neither is a code
defect.

Three conclusions, all actionable:

1. **The suite is not hermetic, and that is a design choice with a running cost.** Tests that read the
   tree are the only enforcement for retired terms, doc accuracy, shell portability and machine
   independence. Deleting them would be worse. But they mean a red suite in a shared tree is
   ambiguous by construction.
2. **The 27% timing swing (1,059s vs 771s) is machine contention, not the suite.** Any capacity
   decision keyed to a single suite timing is keyed to noise. This is exactly the failure mode
   `scripts/ci_capacity.py` exists to prevent, and it is why `PYTEST_XDIST_AUTO_NUM_WORKERS: "3"`
   (`ci.yml:118`) is a declared contract rather than a tuned constant.
3. **"One session, one worktree" is a real rule with a measured cost for breaking it**, and it is not
   mechanically enforced. Two sessions shared this worktree today and produced a red suite that
   accused two innocent tests.

---

## 6. The incident, at full depth: `9089ebc` and 21 barren ticks

### 6.1 What landed

```bash
$ git show --stat --pretty='%H%n%an%n%ad%n%s' 9089ebc
9089ebcdbde32fa78964eb4520bec91b342471de
Mumchimp Architect
Thu Aug 13 09:58:20 2026 +0100
feat(generation): k=50 — founder directive, and an honest note on what funds it
 config.yaml | 20 +++++++++++++++++++-
 1 file changed, 19 insertions(+), 1 deletion(-)
```

**One file. One YAML file. Nineteen inserted lines, eighteen of them comment.** The functional diff:

```diff
 generation:
-  candidates_per_signal: 20
+  candidates_per_signal: 50
```

The commit message is exemplary. It states what the change is *not* funded by (the free pre-ranker
measures AUC 0.502 out-of-time — chance — over 1,904 labelled dossiers), what it *could* be funded by
but is unmeasured (prescreen is an LLM triage gate, not a free proxy), why it cannot be settled
retrospectively (`store/prescreen_shadow/` holds 288 rows, 258 joinable, with **three** passes among
them, all in the 0.6 bucket while 0.7/0.8/0.9 hold zero — the score is not even monotone with
outcome), and what the forward measurement would be (pass rate per vetted candidate at fixed
`batch_size`, before and after).

It is one of the best commit messages in the repo. **It did not prevent the outage.**

### 6.2 What the gate did

Nothing. `.yaml` is not in `SOURCE_EXTS` (`scripts/popdd_verify.py:97`), and at the time no lane
claimed `config.yaml`. The gate printed "nothing to prove" and exited 0.

The comment that now sits at `popdd_verify.py:128-131` records it — and gets the number wrong. It
says the commit raised `candidates_per_signal` **"5 → 50"**. Git says **20 → 50**. That is a small
error in a comment that is the only place in code where this incident is written down.

### 6.3 What happened next, from `store/scheduler/alerts.jsonl`

The commit landed at **2026-08-13T08:58:20Z** (09:58:20 +0100). The alert file is 480,232 bytes and
holds 120 `barren_streak` rows. Filtered to the two days after:

**2026-08-13** — five criticals, streak 4 through 8:

```
09:37:00Z  produced nothing for 4 ticks in a row
09:46:23Z  5
10:00:46Z  6
10:24:57Z  7
11:05:56Z  8
19:06:09Z  clean tick — {'dossiers': 0, 'resumed': {...}}
```

**2026-08-14** — eighteen consecutive criticals, streak 4 through **21**:

```
11:23:58Z   4          14:05:29Z  14
11:39:25Z   5          14:21:34Z  15
11:54:59Z   6          14:37:41Z  16
12:11:39Z   7          14:53:28Z  17
12:27:12Z   8          15:11:45Z  18
12:42:33Z   9          15:56:55Z  19
12:58:10Z  10          16:13:39Z  20
13:15:10Z  11          16:26:46Z  21
13:33:27Z  12
13:49:47Z  13
```

Then, four hours later:

```
2026-08-14T20:48:25Z  tick_error: tick_hard_deadline: exceeded 10800s during generation
                      (batch=15); force-exited for relaunch
2026-08-14T20:49:29Z  resolved — clean tick
2026-08-15T00:21:51Z  recurred
```

**21 consecutive barren ticks. The last critical is at 16:26:46Z, not 15:57Z as the code comment
says.** Five hours of an unattended money-making daemon producing nothing, plus a tick that ran into
a **three-hour** hard deadline mid-generation and had to be force-exited.

### 6.4 The mechanism

`candidates_per_signal` 20 → 50 raised the work each tick had to do before it produced anything.
`schedule.batch_size` bounds how many candidates reach the paid moat, so k=50 only widened the pool
that selection picks from — but generation itself is not free, and the tick had one deadline shared
across generation and drain. Generation consumed it. The tick force-exited before any dossier landed,
so the tick counted as barren, so the next tick started from scratch and did the same thing.

The commit message anticipated the yield question and answered it honestly. It did not anticipate the
**latency** question, because nothing in the change's own review surface asked it.

### 6.5 The fix, and how long it took

The repairs landed on **2026-08-15**, two days later, in four commits within three hours:

```
15:32:22  a3122763  fix(engine): the tick now stops on its own terms, and keeps what it paid for
15:56:12  02a3aaf2  fix(scheduler): budget the tick against the time the drain LEFT, not the whole deadline
16:19:51  3737278b  perf(drain): the tick's largest consumer was the one phase with no ceiling
18:40:56  0e1e939e  perf(engine): the tick's two unbudgeted phases now have ceilings (#205)
```

and a fifth on 2026-08-16:

```
01:15:48  ffb4eb78  fix(scheduler): the split gated three jobs and the fourth kept the moat's clock
```

Five commits to repair one YAML line. **Mean time to detect: the founder asked why.** Not a monitor,
not a pager — the `barren_streak` alerts were being written to `store/scheduler/alerts.jsonl` the
whole time, 18 of them on the second day, and nothing surfaced them.

### 6.6 The general lessons

1. **A configuration file is code.** `config.yaml` is the most-changed file in the repo (§2.3) and was
   the least-proven. The fix was `ENGINE_CONFIGS = ("config.yaml",)` (`popdd_verify.py:138`) — a named
   catchment, deliberately *not* adding `.yaml` to `SOURCE_EXTS`, because that would make every
   workflow and docs YAML edit uncommittable, and a gate that blocks unrelated work is a gate people
   disable with `--no-verify`.
2. **A change can be fully reasoned about on the wrong axis.** The commit message argued yield
   exhaustively and never mentioned tick latency. The review question that would have caught it:
   *what does this change do to the time the tick needs before it produces its first artefact?*
3. **A gate that proves "the tick completes" is worth more than a gate that proves "the tests pass"**
   for a change like this. That is now what the `engine` lane does — a `--dry-run` tick plus
   `scripts/gen_budget_guard.py --config config.yaml`, the ratio guard that this specific commit
   violated.
4. **An alert nobody reads is not detection.** 18 criticals on day two. The escalation path was a
   human noticing output had stopped.
5. **The one place this incident is recorded in code has the wrong number in it** (§6.2). Incidents
   recorded only in comments rot. This document is the second copy.

---

## 7. Where review is thin

### 7.1 The evidence

- **Squash merges hide the review unit.** 36 of the last 40 commits carry a `(#NNN)` PR reference, so
  the PR process is being used. But a squash collapses N commits into one, so `git log --oneline main`
  shows one line where the review saw N. Any reconciliation of "PRs merged" against "commits on main"
  disagrees, and the per-commit history that would let you bisect a large PR does not exist on `main`.
- **Batch merges are common and large.** Three of the recent subjects are:
  `land: every open pull request, and a capacity contract so CI stops stalling (#312)`,
  `land: all nine open pull requests, plus the queue that stops them going stale (#301)`,
  `salvage: land integrate/minimax-into-main on main and retire the branch (#275)`.
  A commit that lands nine PRs at once is not nine reviews.
- **A queue that cancelled the builds it waited for.** Recorded in project memory: close/reopen
  cancelled in-flight CI, the queue never merged anything, and `runner_name == ""` meant the job never
  ran. The mechanism intended to make merging safer made CI results meaningless for a period.
- **The `guard` job is PR-only** (`ci.yml:269`), so a direct push to `main` gets no doc lint, no
  protected-deletion check and no capacity check.
- **43% fix commits with a 0.14% revert rate** (§5.1, §5.2) means defects are found after merge and
  paid for forward. That is a review-thinness signal, not a virtue.
- **22 of 42 registered worktrees are prunable.** Branch hygiene has no owner.

### 7.2 Three investments, with costs

**Investment 1 — Re-arm the local gate. Cost: one symlink plus one decision. Highest return.**

```bash
ln -sfn "$(dirname "$(cd "$(git rev-parse --git-common-dir)" && pwd -P)")/.lux/hooks/pre-commit" \
        "$(git rev-parse --git-path hooks)/pre-commit"
```

This is the only change that restores ruff enforcement (CI has none), storefront vitest enforcement
(CI has none), and engine dry-run enforcement on every commit rather than every PR. The blocker was a
number that measurement has retired: 1,059s against a 2,400s ceiling.

The honest cost: **every commit pays 17 minutes.** That is real, and it is why this is a decision and
not a fix. Two mitigations exist in the code already — `scope_ruff` narrows ruff to the staged files,
and `LANE_ORDER` puts the 15-second engine lane first. A third would be to add a
`POPDD_FAST=1` path that runs `scripts/test_impacted.py` instead of the full suite for a
single-file diff; that script already exists in `scripts/`. Estimate: half a day to wire, plus the
decision.

**Investment 2 — Make the `guard` job run on push to `main`. Cost: one line.**

Change `ci.yml:269` from `if: github.event_name == 'pull_request'` to also allow pushes, with
`--against` resolving to `HEAD~1` on a push. Doc lint, protected deletions and the capacity contract
then cover the one event type that currently bypasses every one of them. The `land:`-style batch
merges in §7.1 are exactly the commits this would catch.

Risk to name: it will go red on `main` the first time, because there are **57 doc-lint findings today**
(`scripts/doc_lint.py --json`), concentrated in `docs/LOGGING_AND_RETENTION.md` (12),
`docs/OPS_CONSOLE_PROGRAM.md` (8) and `docs/SUBSCRIPTION_PROGRAM.md` (7). The ratchet
(`test_doc_lint_never_increases.py`) already prevents growth; this would only stop the bypass.
Estimate: one line plus a day of baseline cleanup if you want it green rather than ratcheted.

**Investment 3 — Add `npm test` to the `nextjs` CI job. Cost: three lines plus runner time.**

`popdd_verify.py:257-260` states it plainly: "The storefront proof CI itself does NOT fully run:
ci.yml's `nextjs` job runs typecheck + build but never `npm test`". With the local gate off, **938
vitest assertions have no enforcement point anywhere.** That includes the design-contract suites that
read `src/styles/globals.css` as source text, and `__tests__/noHardcodedPrice.test.ts`, which guards
the money surface of the storefront.

The reason it is not there is runner time on the light pool. Measure it before arguing: run
`npm test` in `Store.Web/` and compare against the `nextjs` job's 40-minute timeout. Estimate: three
lines, plus one measurement, plus a capacity-contract update in `ops/config/ci_capacity.yaml`.

---

## 8. Debt register

| Item | Evidence | Cost to close |
|---|---|---|
| Local gate uninstalled | `test -e .git/hooks/pre-commit` → ABSENT | §7.1 |
| ruff has no CI enforcement | no ruff step in `ci.yml`'s python job; 4 findings live today | one step, minutes |
| 938 vitest assertions unenforced | `popdd_verify.py:257-260` | §7.3 |
| `guard` job bypassed on push to main | `ci.yml:269` | §7.2 |
| 57 live doc-lint findings | `scripts/doc_lint.py --json` | ~1 day; ratchet already holds the line |
| `prospector/run.py` at 4,470 lines with 46 importers | §1.2, §2.2 | Extracting the library half from the CLI half is a multi-week refactor with a real regression risk. Do not start it without the golden set green and the gate armed. |
| `bridge.publish_pass` at 874 lines, money-adjacent | §2.1 | Not a candidate for casual refactor. The right first step is characterisation tests around its outputs, ~2 days. |
| 22 prunable worktrees | `git worktree list` | `git worktree prune`; it is a write, so it needs a decision. |
| No coverage measurement | no `pytest-cov` in `requirements.txt` | Adding it is an hour. Acting on the number is the real cost. |
| Suite is non-hermetic | §5.4, live failure | Not a defect to fix. Document it (done, here) and enforce one-session-one-worktree. |
| Incident record lives in a code comment, with a wrong number | `popdd_verify.py:128-131` says "5 → 50"; git says 20 → 50 | Two-word edit; §6 is the durable copy. |
| `CLAUDE.md` cites `pytest.ini:42` | `addopts` is at `:52` | One character. |
| Dead `"ops"` lane branch | `popdd_verify.py:334-339`, unreachable and would `KeyError` | Delete two lines. |
| Duplicate `_isolate_usage_wall` fixture | `tests/conftest.py:48` and `:181`; second shadows the first | Delete the dead one, ~30 min. |

---

## 9. Invariants worth defending

| Invariant | Why it matters | What breaks without it |
|---|---|---|
| One test file, one xdist worker (`pytest.ini:52`) | `config.load_config` writes `operator._MOAT_PRIMARY` process-globally (`operator.py:1362-1396`), and 175 modules import `prospector.config` | Reds that reproduce nowhere and accuse the component instead of the harness |
| Timing assertions measure CPU, not wall clock | `test_a_huge_page_is_selected_in_reasonable_time` passed at 8 workers and failed at 12 on identical code | Parallelism turns correctness tests into coin tosses, and the "fix" is to raise the budget |
| A gate grades the bytes the consumer receives | The house-dash incident graded a value the buyer never sees; `#283`, `#267`, `#285` are the same class | Packs held off the shelf, status lines that read green on the wrong reference |
| A failed call defers, it does not vote | `verify.py:365` sets `retrieval_failed=True`; the DEFER gate is at `verify.py:693` | `2102bacc6dd75cf9.kill.json`: an idea killed by our own outage, in a dossier that reads as fully reasoned |
| The verdict is the exit code, never the parsed counts | `run_lane` (`popdd_verify.py:537`) | `dotnet test` can print a healthy summary and still fail |
| Ratchets, not absolutes, for legacy debt | `test_doc_lint_never_increases.py`, `test_swallowed_failures_can_only_go_down.py` | Either the gate is unachievable and gets disabled, or the debt grows unmeasured |
| Config changes prove a tick still completes | `ENGINE_CONFIGS` (`popdd_verify.py:138`) | §6 |
| `changes` fails open (`ci.yml:150`) | A path filter that fails closed skips the proof silently | Green CI on an unproven change |
| `ci-ok` counts skipped as pass (`ci.yml:748`) | Makes path filtering compatible with branch protection | Every PR that legitimately skips a lane blocks forever |

---

## 10. Where to look next

```bash
# The health question, answered by command
git config --get core.hooksPath; test -e .git/hooks/pre-commit && echo GATE_ON || echo GATE_OFF
.venv/bin/python -m ruff check --output-format concise | tail -3
.venv/bin/python scripts/doc_lint.py --json | python3 -c "import sys,json;print(len(json.load(sys.stdin)['findings']))"
.venv/bin/python -m ops.automations.retired_terms
python3 scripts/ci_capacity.py

# Size, complexity, churn
git ls-files '*.py' | xargs wc -l | sort -rn | head
git log -300 --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn | head
git log -400 --pretty=%s | sed -E 's/[(:].*//' | sort | uniq -c | sort -rn

# The suite
.venv/bin/python -m pytest --collect-only -q -n 0 | tail -1
time .venv/bin/python -m pytest -q --tb=no -p no:warnings

# The incident
git show 9089ebc -- config.yaml
grep -c barren_streak store/scheduler/alerts.jsonl
```

| File | Why |
|---|---|
| `scripts/popdd_verify.py` | The gate, and the only in-code record of the 9089ebc incident. |
| `scripts/ci_capacity.py` | The CI contract, and the clearest statement of why constants drift. |
| `scripts/doc_lint.py` | The prose compiler. Its header is the argument for it. |
| `ops/config/retired_terms.yaml` | Business facts separated from the engine that checks them. A pattern worth copying. |
| `docs/COST_PROGRAM.md` | Every cost lever and measurement, tracked. |
| `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` | Estate-wide graph freshness. |
| `docs/PACK_NARRATIVE_PROGRAM.md` | The buyer-facing renderers and the three gates that graded less than they appeared to. |
| `../ESTATE_MAP.md` | The factual spine. |
| [developer.md](developer.md) | The mechanics this document assesses. |
| [qa-test-engineer.md](qa-test-engineer.md) | The eight ways green has lied here. |
