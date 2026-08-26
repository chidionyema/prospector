# 0008 — The fetch cache is shared and content-addressed

- **Status:** accepted
- **Date:** 2026-08-22
- **Decided by:** founder
- **Supersedes:** the Upstash Redis cache row of `docs/ENGINE_RUST_REWRITE_SPEC.md` section 1.
  Related: [0005](0005-postgres-is-the-queue.md).
- **Question it answers:** `DiskCache` is per-box. With N workers, do we pay N times for the same
  fetch?

---

## The decision

**No. The cache index moves to Postgres and the bodies to R2, keyed by a hash of the normalised
URL.**

```sql
create table fetch_cache (
  url_hash bytea primary key, fetched_at timestamptz not null,
  status int not null, content_type text,
  body_key text,            -- R2 object; null when the status has no body
  passage_index jsonb       -- pre-extracted windows, so a hit skips extraction too
);
```

## Why this is the biggest lever in the design

Checks converge on the same authority domains constantly — legality on the same regulator, payer
solvency on the same filings, incumbency on the same market reports. Every one of those fetches is
paid once per box today.

**It compounds as volume rises, which is the opposite of how the CPU argument behaves.** A faster
extractor saves a fixed fraction of a fixed cost. A shared cache saves more as the candidate count
grows, because convergence on authority domains grows with it.

**`passage_index` means a hit skips the CPU work as well as the network work**, so it is also the
cheapest speed win available and it needs no language change (`AGENTS.md` LAW 14).

**It is free provenance.** The archived citation body is already in R2 before the pack is built from
it, so "source-or-die" gains an artefact rather than a promise.

## What already exists

`prospector/retrieval.py:2054 DiskCache` is already content-addressed and already cross-tick, with
freshness at `retrieval.cache_ttl_s` (`prospector/config.py:156`). **The design is not new; only its
scope is.** This is a backing-store change to a working component, not a rewrite of caching.

## The alternative

**Redis.** Not durable, a second datastore, a second DR drill, and it cannot hold the bodies anyway
so R2 would still be needed. Postgres plus R2 is one fewer moving part.

## The risk

A shared cache is a shared wrong answer. If a fetch is cached with a bad decode or a truncated body,
every worker gets it. That argues for storing the raw bytes and the content type in R2 and treating
`passage_index` as a derived, discardable column — a bad extraction can then be re-derived without
re-fetching. The Latin-1 defect found by the retrieval port is exactly the failure this guards
against.
