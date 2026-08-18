# The platform for the principal developer

Your question is the uncomfortable one: **which of our stated invariants are actually enforced, and
which are only written down?** Prose drifts. A test does not.

## How this codebase encodes intent

Test files here are named as sentences that state the invariant, not as `test_module.py`. A sample
from `tests/unit/`:

```
test_a_failed_call_is_not_an_empty_answer.py
test_an_exhausted_brain_is_not_an_empty_discovery.py
test_a_rail_that_cannot_read_its_own_input_must_not_fail_open.py
test_a_swallowed_bug_is_not_a_missing_measurement.py
test_an_unreadable_file_is_not_an_empty_one.py
test_a_stale_verdict_is_re_gated.py
test_claude_is_never_on_the_noncritical_chain.py
```

369 test files, roughly 5000 tests. Each of those names is a defect that shipped once. Reading the
directory listing is the fastest way to learn what has gone wrong here, and it is faster than reading
any document, including this one.

The recurring theme is one failure class: **an absence being silently converted into a zero.** An
unreadable file becomes an empty file. A failed call becomes an empty answer. A failed grade becomes
a zero. Every one of those reads as a healthy system with nothing to report.

## What is enforced, and by what

| The invariant | Enforced by | Strength |
|---|---|---|
| A verdict may only be ruled finally by a declared brain | `operator.is_provisional_provider` (`operator.py:1451`) + `run.py:864` | Code, at the decision point |
| A failed call defers, never kills | `verify.py:365` → `verify.py:693` | Code, plus a named test |
| Price and Stripe cannot drift | `prospector/bridge.py` — one `PriceDecision` writes both | Structural. There is no second path |
| `price_comparables` cannot kill | Barred in `kill_filter.is_hard_fail` **and** in verify's run order | Two places, deliberately |
| Claude is never on the non-critical chain | `_noncritical_order` strips it at the point the chain is BUILT | Structural, plus `test_claude_is_never_on_the_noncritical_chain.py` |
| A tool cannot be invisible to the operator | `tests/unit/test_console_tools_run.py` fails by filename | Test |
| Protected files cannot be silently deleted | `scripts/guard_protected_deletions.py`, CI job `guard` | Required check |
| Mixed-sector discrimination cannot regress | `tests/test_golden_set.py`, CI job `python` shard 0 | Required check |
| Engine config cannot change unnoticed | CI job `engine`, on **every** pull request, no paths filter | Required check |
| Every job passed or was skipped | CI job `ci-ok` | Required check |
| Docs cannot cite paths that do not exist | `scripts/doc_lint.py` | Lint, git-tracked paths only |
| The suite does not depend on this machine | `tests/test_suite_is_machine_independent.py` | Test |
| The commit gate cannot wedge | `tests/unit/test_popdd_gate_cannot_wedge.py` | Test |

## What is only written down

Be honest about these when someone asks what protects them.

- **`CLAUDE.md` is the operating contract and nothing enforces it.** Proof discipline, plain English,
  answer-first, budget mode, one round trip per intent — all convention.
- **The local commit gate is optional and has been off in both directions.** As last measured,
  `core.hooksPath` is unset and `.git/hooks/` holds only `pre-commit.DISABLED-2026-08-14` and
  `pre-commit.sample`. There is no `pre-commit` file, so `git commit` runs no gate. CI is the real
  fence; the `engine` job exists precisely because a local hook can be uninstalled, bypassed with
  `--no-verify`, or never installed at all. That is not hypothetical: commit `9089ebc` on 2026-08-13
  raised `candidates_per_signal` 5 → 50, nothing checked it, and every tick afterwards force-exited
  at the 3h deadline mid-generation. **The engine produced nothing for 21 consecutive ticks and the
  founder found it by asking.**
- **"Everything changeable is ops-driven"** is a design goal. Some things still need a config edit.
- **The persona and estate documents you are reading now.** They are prose. They cite commands and
  `file:line` refs so you can check them, but nothing fails when they go stale except `doc_lint` on
  paths.

## The architectural rules that are load-bearing

**Config is the deployment interface.** Swapping operators requires no code change, only
`config.yaml`. The `moat_primary` roster was a hardcoded frozenset until 2026-08-15 and that was the
one tier knob needing a source edit and a daemon re-exec to move — which is what made a cheap brain's
throughput unusable at any concurrency. Promotion is a config line plus the golden gate, never a
patch.

**Creativity lives in generation, constraint lives in verification.** Nothing is killed at generation
time. All gates are downstream.

**Two loops never merge.** Demand tunes what to offer; truth vetoes what may ship.

**Determinism where a buyer reads.** All sixteen `pack_*.py` renderers are model-free on purpose. A
model in a renderer makes the same pack render differently twice.

**A rail with exceptions is not a rail.** `PAUSE` halts generation and drain together. The half-stops
are separate, named files.

## Where I would put the next unit of rigour

Stated as opinion, with the reason, not as fact:

1. **The store has no schema contract between Python and the two TypeScript consumers.** Three
   console crashes in one day were all hand-written types disagreeing with hand-written views.
   Generating the ops console types from the Python view functions would delete that entire failure
   class. This is the highest-value structural change available.
2. **The dossier corpus is the most valuable dataset here and nothing aggregates it.** Every
   calibration number in `config.yaml` was derived by hand-replaying files.
3. **`~/.config/prospector/age-key.txt` has no off-machine copy.** That is a single point of total
   loss and it is not an engineering problem, it is a five-minute one.

## What to read next

- [architect.md](architect.md) — seams and the portability contract.
- [qa-test-engineer.md](qa-test-engineer.md) — the ways green has lied here.
- `docs/SYSTEM_SPECIFICATION.md`, `docs/DECOUPLING_PROGRAM.md`.
