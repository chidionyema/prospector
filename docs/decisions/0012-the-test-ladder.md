# 0012 — Tests are written on a ladder, cheapest rung first

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** nothing. Narrows the testing half of
  [0002](0002-engine-runtime-and-engineering-standards.md). Related:
  [0009](0009-strangler-sequencing.md), [0011](0011-sourceref-is-minted-by-the-fetch-path.md).
- **Question it answers:** the engine is about to be redesigned around
  [0004](0004-unit-of-work-is-candidate-check.md). What happens to 8,303 tests written against the
  shape it is leaving?

---

## The measurement first

Taken 2026-08-22 in this worktree, on branch `docs/the-engine-architecture-and-its-decisions`.

| what | number | command |
|---|---|---|
| tests collected | **8,303** | `.venv/bin/python -m pytest tests/ --collect-only -q` |
| `test_*.py` files | **543** | `grep -rl "" --include="test_*.py" .` less `.venv`/`node_modules` |
| of those, under `tests/unit/` | **444** (82%) | same, cut on the top directory |
| under `tests/invariants/` | **7** | `ls tests/invariants/` |
| Python files using `hypothesis` | **0** | `grep -rl "from hypothesis import\|import hypothesis"` |
| Python tests named `test_incident_*` | **0** | `grep -rl "def test_incident" tests/` |
| Rust `proptest!` blocks | **1** | `engine-rs/crates/prospector-core/src/decision.rs:180` |

So four-fifths of the suite is in the directory the policy targets, and the two rungs that survive
a rewrite are the two the estate has almost none of.

## The decision

**Always use the cheapest rung that can express the guarantee. Descend only when the rung above
genuinely cannot.**

| rung | form | what it buys | cost |
|---|---|---|---|
| 1 | types | the failure becomes unrepresentable | zero tests, zero runs, zero maintenance |
| 2 | property tests | one test, thousands of cases, survives a rewrite | a few lines each |
| 3 | differential replay | the old implementation is the oracle | one assertion over a corpus |
| 4 | incident tests | one per real bug, named for it | one test per incident, written once |
| 5 | evals, deterministic graders | probabilistic output judged mechanically | a grader per eval |
| 6 | LLM-as-judge | genuinely subjective quality | money per run, and drift |
| 7 | production oracles | deploy-verify, health, canary, alerts | already built |

### The rule an agent applies

Before writing any test, ask in order. Can this be a **type**? Make it unrepresentable instead. Can
this be a **property**? Write one property, not ten examples. Is this a **rewrite**? Write a
differential case against the old path. Is this a **real bug that occurred**? Write one incident
test, named for it. If none apply, the test is probably not worth writing — say so in the PR and
move on.

### What gets deleted

Example-based unit tests of orchestration and implementation detail. Any test whose name describes
a function rather than a rule. Mocks of our own internals, which test the mock. Anything
self-healing: a test that rewrites itself to match new code always agrees, which removes the
oracle. With agents writing the code as well, that is a closed loop with no external check.

### The seven properties this engine wants

Not yet written. Recorded here so the list is not re-derived.

```
forall candidate: any refuted check          => never reaches publish
forall verdict:   provisional                => never listed
forall price:     one PriceDecision          => catalogue row and provider price agree
forall passage:   select_passage output      => is a substring of the fetched body
forall pack:      every Claim in the IR      => appears in both PDF and HTML renders
forall config:    a market override          => never mutates a gate, threshold or weight
forall ledger:    sum of leased budget       => never exceeds daily_cap_usd
```

### Per component

| component | rungs that carry it |
|---|---|
| Rust kernel | 1 types, 2 properties, 3 differential against Python |
| retrieval / extract | 2 properties, 3 fixtures. No invariants, so no unit tests |
| pack layer | 1 IR types (ADR 0010, 0011), 2 render-parity property, 4 |
| verdict / moat | 5 deterministic evals on the golden set, 4 |
| Store API (.NET) | 1 nullable + analyzers, 3 HTTP traffic replay, 7 |
| Next surfaces | 7 deploy-verify, Playwright smoke only. No unit tests |
| agent estate | evidence gate, incident corpus as eval data |

## Where it is enforced

- `~/.claude/AGENTS.md`, section **How to test** — every session, every repo, loaded every turn.
- `.claude/skills/ship-a-pr/SKILL.md` step 3 — the PR author states the rung.
- `.claude/agents/receipt-auditor.md` finding class 5 — a machine reader that has never seen the
  reasoning looks for tests that assert structure rather than a rule. This is the part that is a
  guard rather than a note.

## What is already true, and what the design got wrong

**Right, and verified.** `FixtureProvider` exists at `prospector/retrieval.py:1115`, so rung 3 has
a deterministic retrieval source today. The golden set exists at `tests/test_golden_set.py` and is
already an eval suite with mechanical grading — a `MockOperator` plus fixtures, discriminating
PASS from KILL. Rung 7 exists: `.github/workflows/deploy-web.yml:196` calls
`scripts/rollback_now.py store-web` when the site does not serve. `proptest` is already a
workspace dependency and is already used once, at
`engine-rs/crates/prospector-core/src/decision.rs:180`, on exactly the shape the policy asks for —
it encodes an invariant a Python comment had been asking the next author to preserve by hand.

**The corpus is reachable but is not in this checkout.** The design says "3,608 dossiers, 189
packs" as though the replay corpus were on hand. `sqlite3 store/prospector.db "select count(*) from
dossiers"` in this worktree returns **0**. The 3,608 rows are the live `prospector-engine` volume,
and a copy is in R2 — `docs/MIGRATION_AND_DR_PROGRAM.md:1301` records that copy being pulled down,
decompressed and opened read-only on 2026-08-20, `PRAGMA integrity_check` = `ok`, 3,608 rows,
agreeing with `LIVE_ROWS 3608` from the engine itself. Two angles, so the number is sound. But the
differential harness has a precondition the design does not name: restore the corpus first. That
restore has been done once by hand and is not yet scheduled.

**The 189 packs figure is unverified.** It appears in no document in this repo and no local
directory holds packs. Not disputed, just not measured. Do not cite it until it is.

## Risk

The policy can be used to argue against a test that should exist. "None of the four apply" is a
sentence anyone can write. The check on it is the same as everywhere else: the PR body has to say
which rung and why, and the receipt-auditor reads the diff without the author's reasoning.

The second risk is that pruning happens before the replacements exist. Rungs 1 to 4 are thin here
today — 0 hypothesis properties, 0 incident-named tests, 1 proptest block. Deleting implementation
tests now would remove cover with nothing underneath it. Hence the sequencing below: prune is step
five, not step one.

## Sequencing (founder's, recorded as given)

1. Adopt the policy. Costs nothing, stops the bleeding immediately. **Done in this commit.**
2. Write the seven properties. The rewrite-proof core.
3. Build the differential harness over the dossier corpus. Precondition for any Rust work.
4. Formalise the golden set as the eval suite with deterministic graders.
5. Then prune, with rungs 1 to 4 in place. Coverage of invariants must not drop; coverage of lines
   may.
6. Traffic replay on the Store API when checkout is next touched.

Steps 2 to 6 are not started and are not authorised by this ADR. They are work items.

## Endpoint

A few dozen properties, a differential harness, one eval suite, an incident test per real bug, and
a suite that shrinks when the engine is rewritten instead of blocking it.
