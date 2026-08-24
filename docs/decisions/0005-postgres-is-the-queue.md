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

## The risk, and it is larger than "one failure domain"

One Postgres is one failure domain, and the drill that restores it has to exist before the engine
depends on it (`docs/MIGRATION_AND_DR_PROGRAM.md` section 11).

**A second angle sharpens this and it is not comfortable.**
`docs/INFRA_DR_AND_PLATFORM_ANALYSIS_2026-08-22.md`, written independently and merged the same day,
counts **eleven distinct Fly Managed Postgres incidents in six months** (2026-04-10, 04-27, 05-16,
06-11, 08-01, 08-04/05, 08-20, plus MPG degradation inside the 07-20 and 08-19 incidents), and
records that on **2026-08-01 existing clusters kept serving while their backups silently lagged**.
Its verdict: "Fly Managed Postgres is the weakest component in the whole record."

That does not overturn this decision — the alternative datastores are worse on every axis and adding
a second one makes the failure domain bigger, not smaller. It changes what has to be true before the
engine depends on it:

1. **The off-Fly verified copy is a precondition, not a nice-to-have.** `scripts/backup_store.py`
   already writes a daily verified copy to Cloudflare R2 and `scripts/restore_drill.py` already
   restores from it weekly, unattended, recording `took_s`. Postgres must be inside that same
   backup and drill before it holds anything the engine cannot rebuild.
2. **Backup lag must be measured, not trusted.** The 2026-08-01 failure mode was a healthy cluster
   with stale backups. A dashboard saying "backed up" is a shape, not the content.
3. **"Postgres or R2, nothing in between" survives, and R2 is the durable half.** Bodies and
   deliverables live in R2 (ADR 0008), which is already off-Fly. Postgres holds state that can be
   rebuilt from R2 plus the append-only ledger; it should not become the only copy of anything.

That analysis also records that the engine store today is **903 MB of files with no Postgres in the
engine path at all**. This decision puts one there. That is a real increase in operational surface
and it is the price of N workers.
