# 0002 — Keep the engine in Python; fix the bug rate with standards and enforcement

- **Status:** accepted
- **Date:** 2026-08-19
- **Decided by:** founder, on this recommendation
- **Supersedes:** nothing. Related: [0001 — moat reliability vs token cost](0001-moat-reliability-vs-token-cost.md)
- **Question it answers:** the engine keeps producing incidents. Do we rewrite it in another
  stack, or extract the risky part into a typed daemon, or neither?

---

## Summary of the decision

**Neither. We keep the engine in Python and spend the money on engineering standards and their
enforcement instead.**

The rewrite case rested on two beliefs. Both were measured on 2026-08-19 and both are false.

1. *"A typed language would have caught these bugs."* Of the nine incidents recorded on
   2026-08-18 and 2026-08-19, **a type checker would have caught one, and partly caught a
   second.** Seven were environment assumptions, vacuous checks and stale predicates, which no
   type system sees.
2. *"We need a real queue with leases, and Python's is not one."* **It already is one.** The
   lease is an atomic compare-and-swap in SQLite (`prospector/store.py:585-604`), with dead-owner
   reclaim and 22 passing tests, including one that runs sixteen concurrent workers at a single
   row. It landed on 2026-08-16. I asserted otherwise in chat earlier today, before reading it.

What is true is the founder's own sentence: **"python is flakey but we have not tried to set
standards."** That is exactly the state on disk. 64,983 lines of Python across 135 files, and
**no type checker is configured or even installed**. The only static standard we have is a ruff
rule set deliberately narrowed to five families. We have never tested whether Python is the
problem, because we have never set a standard for it to fail.

So the decision is not "Python is fine". It is **"the bug rate is an unenforced-standards problem,
and changing language is the most expensive way to avoid finding that out."**

---

## Background: what actually went wrong

Nine incidents were recorded in two days. This is the honest classification of each against the
question *would a static type system in another language have prevented this?*

| # | Incident | Defect class | Types catch it? |
|---|---|---|---|
| 1 | `doc-rot-ratchet` — every finding baselined, so the gate can never go red | gate that cannot fail | no |
| 2 | `guard-greps-prose` — guard refused correct commands whose *text* looked like paths | wrong predicate | no |
| 3 | `silent-acceptance` — 208 tasks closed on a test that exited 0 and printed nothing | gate that cannot fail | no |
| 4 | `stale-remote-ref` — guard demanded a PR for a branch that no longer exists | stale-state predicate | no |
| 5 | `store-resolver` — live engine wrote listings into the container image layer | environment assumption | no |
| 6 | `warnings-as-blockers` — 93 packs reported blocked by four checks that cannot block | domain not modelled | partly |
| 7 | `launchd-path-inert-gate` — load gate never deferred; `sysctl` is in `/usr/sbin`, launchd's PATH is not | environment assumption | no |
| 8 | `unreachable-status` — 237 tasks in a status that was neither worked nor closed | non-exhaustive enum | **yes** |
| 9 | `unreadable-coordinator` — the main autonomous process wrote a 0-byte log for 60 days | observability | no |

Grouped by class, largest first:

- **A check that cannot fail — 4 of 9** (#1, #3, #7, and #6 in part). This is our single biggest
  defect class and the most dangerous, because every one of them *reported success while doing
  nothing*. No language prevents it.
- **An assumption about the environment — 2 of 9** (#5, #7). PATH, filesystem layout, which box
  the code is on. Caught by running the check where it will run, not by types.
- **A domain with a fixed set of values that was never modelled as one — 2 of 9** (#6, #8).
  **This is the one place typing genuinely pays**, and it is a small, targeted place.
- **Stale-state predicates — 2 of 9** (#2, #4).
- **Observability — 1 of 9** (#9). It is #9 that let #7 and #8 survive for weeks.

---

## The two options that were on the table

### Option A — keep Python, invest in standards and enforcement

Set real standards for the code we have and make machines enforce them, prioritised by the
defect classes above rather than by fashion.

- **Cost:** days, not months. No new language, deploy target, or serialisation boundary.
- **Pays out across the whole estate**, including the .NET storefront and the TypeScript console,
  because the top defect class ("a check that cannot fail") is language-independent.
- **Risk:** standards that are written and not enforced change nothing. This has to be a ratchet
  in CI, not a document.

### Option B — extract the queue, leases and reapers into a separate Go daemon, engine stays Python behind a stable interface

- **Cost:** a second language, a second deployable, a network boundary and a wire format, plus
  the ongoing cost of two runtimes.
- **What it was supposed to buy:** a safe multi-worker queue with visibility timeouts, and a
  typed, long-lived, concurrent process.
- **What it actually buys, measured:** *the queue already exists and is already safe.*
  `Store.claim` is a single-statement compare-and-swap; `_owner_is_gone` reclaims a dead worker's
  row instead of parking it for the full 7200s TTL; `store.leased()` reports what is in flight.
  Option B's headline deliverable is a thing we shipped three days ago.

---

## Why Option A wins, with the receipts

**1. The queue is not the problem.** `prospector/store.py:585-604` is a compare-and-swap in one
UPDATE. `tests/unit/test_queue_lease.py` has 22 tests, including
`test_exactly_one_of_sixteen_concurrent_workers_wins`. Concurrent consumers are safe on one
machine today.

**2. Typing would have caught 1 of 9 incidents.** See the table. Buying a typed runtime to fix an
11% slice of the defect rate, while the 44% slice ("a check that cannot fail") stays untouched,
is spending the whole budget on the wrong class.

**3. The workload is IO-bound, so a faster runtime buys speed we cannot spend.** A vet is minutes
of waiting on provider HTTP. `minimax_concurrency` is 8 (`config.yaml:445`) and measured clean at
16/16 with zero 429s — the ceiling is provider quota, not the interpreter.
*Marked unproven:* this is a judgement from the shape of the workload, not a profile. The
measurement that would overturn it is a profile showing meaningful vet wall-clock in Python CPU
rather than waiting on a socket.

**4. The value is not the code.** It is the prompts, the seven checks, the kill-fast ordering, the
pricing rungs, the scoring weights, and the edge cases bought with incidents — a KILL that was
really our own outage, a substring HTTP match that benched a live brain, a store path derived from
`__file__`. A rewrite re-derives every one of those bugs in a new language, and both CLAUDE.md
files become a list of traps for a codebase that no longer exists.

**5. Scale is a storage decision before it is a language decision.** The next real limit is that
SQLite serves one machine. Going multi-machine forces Postgres — and that is true whether the
daemon around it is Python or Go. Language is not the lever; the store is.

---

## The one thing Option B was right about, and it is already fixed

Option B's instinct — *the long-lived concurrent state-critical part is where the sharp edges are*
— found a real defect today.

Lease owners were minted as `pid:uuid`, and `_owner_is_gone` asked `os.kill(pid, 0)` about them.
That is a question about **our** process table. It was correct only while the code's own stated
premise held: *"every worker in this system runs on this machine — the engine is local by design."*
The engine moved to Fly on 2026-08-18, and task #60 is to run more than one instance. Two machines
draw pids from separate spaces, so machine B asking about machine A's pid usually gets
`ProcessLookupError`, calls a live worker gone, reclaims its row, and puts **two workers on one
candidate** — the double publish the lease exists to prevent.

Fixed on 2026-08-19 in `prospector/run.py`: owners are now `host:pid:uuid` via
`_mint_lease_owner()`, and a foreign host is always treated as alive, so only the TTL frees its
rows. Legacy `pid:uuid` owners keep the old behaviour and age out within one TTL, so the
2026-08-16 dead-worker reclaim does not regress. Five new tests in
`tests/unit/test_queue_lease.py`; the load-bearing one is
`test_every_lease_owner_carries_the_host_that_minted_it`, verified to fail against the old mint
format rather than assumed to.

**That is roughly thirty lines of Python, landed in an afternoon.** It is the clearest available
evidence that the cost of Option B was never necessary to get Option B's benefit.

---

## The standards programme, ordered by measured defect class

Each standard names the incidents it would have prevented. Anything that does not name one does
not go on this list.

### S1 — A gate must prove it can fail *(kills class 1: 4 of 9 incidents)*
Every guard, gate or acceptance check ships with a known-bad fixture that must turn it **red**.
A check whose pass condition is the absence of an error passes when it does nothing.
**Enforcement:** a meta-test that walks the registered guards and fails on any without a paired
negative fixture. This is the highest-value item on the list.
*Would have prevented:* `doc-rot-ratchet`, `silent-acceptance`, `launchd-path-inert-gate`.

### S2 — A fixed set of values is an enum, and every branch over it is exhaustive *(kills class 3: 2 of 9)*
Statuses, verdicts, decisions, severities. Not tuples of strings that two constants must be
manually kept in sync.
**Enforcement:** this is where a type checker earns its place — `Literal`/`Enum` plus an
exhaustiveness assert, on the handful of domain fields, **not** a 65,000-line mypy rollout.
*Would have prevented:* `unreachable-status`, `warnings-as-blockers`.

### S3 — Environment assumptions are asserted, never assumed *(kills class 2: 2 of 9)*
Absolute paths for `/usr/sbin` tools; every store path through `config.store_root()`; host
identity in anything that identifies a process.
**Enforcement:** the existing `test_scripts_do_not_rely_on_launchd_path.py` pattern, extended.
*Would have prevented:* `store-resolver`, `launchd-path-inert-gate`.

### S4 — Long-lived processes are observable by default *(kills class 5: 1 of 9, and it is the one that hides the others)*
Unbuffered stdout, events mirrored to the log, and a probe that reads the output rather than the
process table.
**Enforcement:** `test_long_lived_daemons_are_unbuffered.py` (already landed), plus the
`hermes_selfcheck.py` invariant pattern.
*Would have prevented:* `unreadable-coordinator`.

### S5 — Static typing, incrementally, on a ratchet
Install mypy, run it over an allow-list starting with `models.py`, `store.py` and the lease code
in `run.py`, and ratchet the error count down. Copy the mechanism that already works: `ruff.toml`
pins a deliberately narrow rule set with a written baseline (393 findings, "must go down, never
up"). A gate whose first act is a 700-file autofix is a gate that gets turned off.

### S6 — The ratchet is the enforcement mechanism, everywhere
Every standard above lands as a number in CI that may fall and may not rise. Not a document, not
a review convention. This is the only part of this ADR that is non-negotiable: **a standard that
is not a ratchet is a preference.**

---

## Consequences

- The engine stays Python. The storefront stays .NET. The console stays TypeScript.
- **No rewrite is scheduled, and none should be proposed without the falsifying measurement
  below.**
- Go remains a live option for exactly one future component — a multi-machine queue daemon — and
  only *after* the store moves to Postgres, because that migration is required either way.
- Tasks S1–S6 are added to the backlog and ranked above new feature work until the incident rate
  falls.
- Task #60 (engine scaling) inherits a hard prerequisite: **SQLite serves one machine.** Multiple
  engine instances need Postgres first, not a new language.

## What would change this decision

Stated up front so it can be checked rather than argued:

1. A profile showing a significant share of vet wall-clock in Python CPU rather than waiting on
   IO. That would make the runtime the ceiling and reopen the rewrite case.
2. The standards programme running for 90 days with the incident rate not falling. That would
   mean the diagnosis in this ADR is wrong.
3. A product requirement for more than one machine writing the same store. That forces Postgres —
   and only then is "should this daemon be Go?" a real question.
