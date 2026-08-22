# 0005 — Postgres is the queue, the state, the ledger and the cache index

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** the pgmq and Upstash Redis rows of `docs/ENGINE_RUST_REWRITE_SPEC.md` section 1.
  Related: [0004](0004-unit-of-work-is-candidate-check.md), [0007](0007-spend-is-a-leased-budget.md),
  [0008](0008-shared-content-addressed-fetch-cache.md).
- **Question it answers:** the engine needs a durable work queue, shared state, a spend ledger and a
  cache index across N workers. How many pieces of infrastructure is that?

---

## The decision

**One. `SELECT ... FOR UPDATE SKIP LOCKED` against the same Postgres that holds the state.** No
pgmq, no Redis, no Temporal, no Kubernetes.

## Why

- **The queue and the state it drives are the same rows**, so a claim is joinable with everything
  the worker needs and the two can never disagree about where a candidate is.
- **One thing to back up, one thing to restore, one thing to query.** `docs/MIGRATION_AND_DR_PROGRAM.md`
  grades every plane by whether a drill proves it recoverable; each additional datastore is another
  plane that needs its own drill.
- **`SKIP LOCKED` is not exotic.** It has run production queues for a decade and it is a row lock,
  not a service.
- **Redis is not durable.** It was proposed for rate limits, the search cache and brain slot locks.
  The search cache belongs in Postgres and R2 (ADR 0008); a lock whose loss is silent is worse than
  the filesystem `flock` we already use (`prospector/claude_cli.py:282-293`).
- **pgmq is an extension for something a `select` already does.** The message and the state would be
  two rows that can drift.

## The alternatives

| Option | Why not |
|---|---|
| **pgmq** | An extension, a second representation of "there is work", and no join to the state |
| **Redis** | Not durable; a second datastore; a second DR drill; solves nothing Postgres does not |
| **Temporal** | A distributed system to operate. ADR 0004 removes the need it answers |
| **Keep SQLite** | Single writer. The whole point is N workers. It stays as the source for the shadow (`migrations/0001_dossiers.sql`) until parity is green |

## What already exists

`migrations/0001_dossiers.sql` is the live SQLite `dossiers` table transcribed column for column
into Postgres, with `lease_owner` and `lease_until` already present, and
`scripts/dual_write_parity.py` grades the shadow. That is step 2 of ADR 0009 begun, and it was
deliberately a transcription rather than an improvement so that a mismatch is unambiguous.

## The risk

One Postgres is one failure domain. Fly Postgres restore is the drill that has to exist before the
engine depends on it — that drill is a requirement in `docs/MIGRATION_AND_DR_PROGRAM.md` section 11
and it is not optional here.
