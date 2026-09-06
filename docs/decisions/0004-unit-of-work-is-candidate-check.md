# 0004 — The unit of work is one check for one candidate

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** nothing. Related: [0005](0005-postgres-is-the-queue.md),
  [0009](0009-strangler-sequencing.md). Changes the unit assumed by
  `docs/ENGINE_RUST_REWRITE_SPEC.md`.
- **Question it answers:** a worker dies part way through vetting a candidate. Six checks of paid
  retrieval are gone. Do we add a workflow engine with checkpointing, or change what a unit of work
  is?

---

## The decision

**Change the unit. A worker advances a candidate by exactly one check, then releases it.** Not
"vet a candidate".

```sql
create table candidates (
  id uuid primary key, state candidate_state not null, next_check check_kind, ...
);
create table check_results (           -- append-only, never updated
  candidate_id uuid, check_kind check_kind,
  verdict verdict not null, confidence numeric, brain text, trusted bool,
  usd_cost numeric, sources jsonb,
  primary key (candidate_id, check_kind)
);
```

## Why, in one line each

- **Checkpointing costs nothing.** The crash loses one check, because the unit is smaller than the
  loss. No Temporal, no journal, no replay.
- **Kill-fast survives.** `next_check` holds one value at a time, so checks stay sequential per
  candidate and cheapest-decisive-first still holds. Parallelism moves across candidates, which is
  where it already was.
- **Resume stops being a code path.** `--resume`, the DEFER drain and provisional re-vet are three
  flows in `prospector/run.py` (4,532 lines) today. Here they are one query: rows with work left.
  The producer/consumer asymmetry documented in `CLAUDE.md` ("the DRAIN stays trusted-only, and that
  asymmetry is deliberate") stays a *predicate on the query*, not a second loop.
- **The funnel becomes SQL.** No diagnostics module and no file walks; the ops console reads the
  rows that drive the machine, so the two cannot disagree.
- **`(candidate_id, check_kind)` is the idempotency key.** A worker that dies after the model
  answered but before the commit loses one call. One that dies after the commit cannot
  double-charge — the insert conflicts.

## The alternative that was rejected

**Keep the candidate as the unit and add checkpointing** (Temporal, or a hand-rolled journal). It
buys the same crash safety and costs a new distributed system to operate, a second source of truth
about where a candidate is, and a vocabulary nobody here uses. The smaller unit gets it for free and
also delivers the funnel query and the resume collapse, which checkpointing does not.

## What it costs, stated plainly

Roughly seven Postgres transactions per candidate instead of one — a claim, an insert and a release
per check. At 1,200 candidates a day that is about 25,000 transactions, which is nothing. At a
hundred times that volume it would need batching. Writing it down so the trade is on the record.

## How we will know it worked

The question "how much paid retrieval did we lose to crashes this week" becomes a query against
`check_results` versus `candidates.attempts`. Today it is unanswerable.
