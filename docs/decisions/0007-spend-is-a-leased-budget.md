# 0007 — Spend is a leased budget, not a checked ceiling

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** nothing. Related: [0005](0005-postgres-is-the-queue.md), and the SQLite row lease
  established in [0002](0002-engine-runtime-and-engineering-standards.md).
- **Question it answers:** `spend.daily_cap_usd` is enforced by reading the ledger and comparing.
  What happens when there is more than one worker?

---

## The decision

**Reserve before the call, settle after.**

```sql
create table budget_leases (
  id uuid primary key, worker_id text not null,
  candidate_id uuid not null, check_kind check_kind not null,
  usd_reserved numeric not null, expires_at timestamptz not null,
  settled_usd numeric                       -- null until the check finishes
);
```

The cap is enforced against `sum(reserved where unsettled) + sum(settled today)` **in the same
transaction that grants the next lease**.

## Why

**Today's design races the moment there are two workers.** `prospector/spend.py:19-20` holds a cap
and `.check()` raises above it; it is wired at `prospector/run.py:1713` and reads the day's metered
sum from the ledger. Two workers read the same sum, both see room, both spend. With one worker this
has been correct. It stops being correct on the first `fly scale count 2`, and it fails by
overspending, silently, on the one axis this company cannot afford to be wrong about
(`AGENTS.md` LAW 14).

**A lease expires, so a dead worker returns its money** with no reaper process and no operator step.

**It makes the scaling dial honest.** "Raise the cap, add workers" is then a true sentence rather
than a hope, and cost-per-PASS from the observability design says whether raising it is worth doing.

## The alternative

**Keep the checked ceiling and serialise spend behind a lock.** It is correct and it makes the spend
check a global bottleneck on the hot path of every check. A lease is the same safety without the
serialisation, and it is a pattern already in this codebase.

## What already exists, and what this is not

`prospector/store.py:585 claim()` is a compare-and-swap lease with dead-owner reclaim, 22 tests, and
one test that runs sixteen concurrent workers at a single row. **It leases rows.** This leases
money. The two do not replace each other; this is the same pattern applied to the second shared
resource, which is why it needs no new mechanism to be invented.

## What it does not fix

`daily_cap_usd` counts metered API dollars only. Claude Code CLI burn is structurally invisible to
it (`config.yaml:2891`, `prospector/claude_cli.py:158`) and remains so under leasing. That is a
known hole, recorded here so leasing is not mistaken for closing it.
