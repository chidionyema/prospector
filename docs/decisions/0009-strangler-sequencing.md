# 0009 — Build it as a strangler; the golden set is the oracle

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** the "no big bang, no downtime" migration of `docs/ENGINE_RUST_REWRITE_SPEC.md`
  section 5, which named the goal without naming the order. Related: all of 0004-0008.
- **Question it answers:** in what order, and what makes each step safe to stop at?

---

## The decision

**Four steps, each shipping value alone, each reversible.**

| # | Step | Ships when | Risk to correctness |
|---|---|---|---|
| 1 | Retrieval + extract as a Rust crate behind PyO3 | it matches the Python on fixtures and on live pages | zero — graded both ways |
| 2 | The Postgres schema and the (candidate, check) queue, with the **Python** pipeline writing to it | dual-write parity is green | zero — nothing reads Postgres until it agrees |
| 3 | The kernel — verdicts, gates, trust, price — in Rust, both implementations on the golden set | they agree on every dossier | this is the real step |
| 4 | Workers, then decommission `run.py` | the funnel query matches the old diagnostics | bounded by step 3 |

**Each step is a separate founder go.** This ADR records the order, not permission to run it.

## Why this order

- **Step 1 first because it has no invariants.** The interface is four functions and the layer is
  the highest-CPU one. If Rust turns out to be wrong in these hands, this is where that is cheapest
  to discover.
- **Step 2 before any logic moves.** Checkpointing and the funnel-as-SQL arrive while the pipeline
  is still Python, so the benefit lands before the risk does.
- **Step 3 last among the rewrites**, because it is the only step where a disagreement is a wrong
  verdict rather than a slow one.
- **Step 4 is deletion**, and deletion only after the replacement has been running.

## The oracle, which is the point

8,431 tests and the golden set are usually counted as the cost of a rewrite. Run against both
implementations they are a **differential oracle** — the thing that makes step 3 survivable. Two
independent implementations that agree is exactly the two-angle standard (`AGENTS.md` LAW 15), and
the prize is not theoretical: grading the step-1 port found a live Latin-1 decode defect in the
Python that no test could see.

## Evidence the shape works

Steps 1 and 2 have both begun and neither was a rewrite:

- **Step 1**: `engine-rs/crates/prospector-retrieval` and `scripts/retrieval_parity.py`, open as a
  pull request; it fixed a Python bug before replacing anything.
- **Step 2**: `migrations/0001_dossiers.sql` and `scripts/dual_write_parity.py`, merged. The
  migration is a column-for-column transcription of the live SQLite schema on purpose, because a
  shadow that improves the schema cannot prove a mismatch is not its own fault.

## The alternative

**A big bang rewrite.** Months owning two systems, with the bug surface being the disagreement
between them, and no step at which stopping leaves something better than before. Refused.

## The failure mode this design has

**A strangler that stalls between steps is worse than either end state**, because two systems have
to be kept correct. The guard is that each step ships value standing alone: if step 3 never starts,
step 2 still delivered checkpointing and the funnel query, and step 1 still delivered throughput and
a bug fix.
