# The engine architecture

**Status:** the founder's design of 2026-08-22, fleshed out and measured against what is on disk.
**Supersedes:** `docs/ENGINE_RUST_REWRITE_SPEC.md` (the 2026-08-21 design) on five points, listed
in section 13. That file stays as the record of what was decided a day earlier and why it changed.

**Decisions are recorded separately**, one file per decision, in `docs/decisions/`:

| ADR | Decision |
|---|---|
| [0004](decisions/0004-unit-of-work-is-candidate-check.md) | The unit of work is one check for one candidate |
| [0005](decisions/0005-postgres-is-the-queue.md) | Postgres is the queue, the state, the ledger and the cache index |
| [0006](decisions/0006-rust-in-the-kernel-and-retrieval.md) | Rust in exactly two places; ADR 0002 narrowed, not reversed |
| [0007](decisions/0007-spend-is-a-leased-budget.md) | Spend is a leased budget, not a checked ceiling |
| [0008](decisions/0008-shared-content-addressed-fetch-cache.md) | The fetch cache is shared and content-addressed |
| [0009](decisions/0009-strangler-sequencing.md) | Build it as a strangler; the golden set is the oracle |
| [0010](decisions/0010-the-pack-is-an-ir.md) | The pack is a typed IR compiled to views; two arms of support, not three |
| [0011](decisions/0011-sourceref-is-minted-by-the-fetch-path.md) | A SourceRef can only be minted by the fetch path, never by a model |
| [0012](decisions/0012-the-test-ladder.md) | Tests are written on a ladder, cheapest rung first; the suite shrinks when the engine is rewritten |

**What this document is not.** It is not a plan with dates, and it is not permission to start. The
sequencing in section 12 is the order things must happen in if they happen; each step is a separate
founder go.

---

## 0. Read the arithmetic before the architecture

The design opens with the right question — what actually limits throughput — and the numbers it
carries are close but not right. These are measured on this checkout, 2026-08-22.

| Limit | Design said | Measured | Where |
|---|---|---|---|
| Candidates per tick | 15 | **10** | `config.yaml:2659` `schedule.batch_size: 10` |
| Ticks per day | 12 | **12** | `config.yaml:2672` `schedule.interval_s: 7200` (2h) |
| Ceiling | ~180/day | **120/day** | 10 x 12 |
| Candidates generated per signal | (not given) | **50** | `config.yaml:1393` `candidates_per_signal: 50` |
| Daily spend cap | "the real dial" | **$100.00** | `config.yaml:2887` `spend.daily_cap_usd: 100.0` (the code default is 20.0, `prospector/config.py:279`) |
| Fetch concurrency | 8 workers, threads | **8** | `prospector/retrieval.py:977` default, passed at `:2556` |
| claude_cli concurrency | "1 machine-wide" | machine-wide `LOCK_EX` flock per slot | `prospector/claude_cli.py:282-293` |

`CLAUDE.md` states `candidates_per_signal` 20 and `batch_size` 15. Both are stale; the config is
the answer. That is a defect in `CLAUDE.md` and is fixed in the same change as this document.

**What the arithmetic means for the design.** Ten times the throughput is 1,200 candidates a day.
In the order things break:

1. **Spend.** At today's cost per candidate this is the first wall and it is a dial, not a bug.
   Raising it is a founder decision about money. Everything below it must be able to follow.
2. **Provider quota.** Paid search has a hard credit balance. Self-hosted searxng is the only
   grounding leg we can scale by buying a bigger box rather than more credits.
3. **claude_cli.** Deliberately clamped to one call machine-wide by a filesystem lock. It is a
   backstop, not a scaling leg, and it must stay that way.
4. **Fetch and extract.** Eight Python threads. This is the only genuinely CPU-bound layer and the
   only one where the language choice changes the ceiling.
5. **Verdict latency.** Network-bound. Horizontal only; no language helps.

So the architecture has exactly three jobs: **make spend an explicit, safe dial**; **make
everything under it horizontally scalable**; and **stop paying twice for the same fetch**.

---

## 1. Shape

```
                    +--------------- Postgres ----------------+
                    | candidates | check_results | spend_ledger|
                    | fetch_cache| budget_leases | embeddings  |
                    |        (the queue lives here too)        |
                    +-------------------+---------------------+
                                        | FOR UPDATE SKIP LOCKED
        +--------------+----------------+---------------+--------------+
     worker         worker           worker          worker         worker
   (stateless Rust - scale by adding replicas, no coordination)
        |
        +-- retrieval: Tokio HTTP + streaming extract + passage select   [Rust]
        +-- brains:    HTTP to model APIs, one trait per provider        [Rust]
        +-- packs:     Typst + Askama                                    [Rust]

  R2: deliverables, backups, archived citation bodies (content-addressed)
  OTel Collector -> traces / metrics / logs
  Store API + storefront: unchanged, .NET + Next
```

No Temporal, no Redis, no Kubernetes. One thing to back up, one thing to query, one thing to reason
about. `SELECT ... FOR UPDATE SKIP LOCKED` is a durable work queue and has been one for a decade.

---

## 2. The central choice: the unit of work is (candidate, check)

Not "vet a candidate". **Advance a candidate by one check.** Everything else in this document is
downstream of that sentence. ADR 0004 records it.

### 2.1 The schema

```sql
create type verdict         as enum ('supported', 'refuted', 'unverifiable');
create type check_kind      as enum ('pain_reality', 'value_durability', 'incumbency',
                                     'payer_solvency', 'distribution', 'legality',
                                     'price_comparables');
create type candidate_state as enum ('new', 'screened', 'vetting', 'deferred',
                                     'killed', 'passed', 'published', 'retired');

create table candidates (
  id            uuid primary key,
  state         candidate_state not null,
  next_check    check_kind,                      -- null exactly when state is terminal
  lane          lane   not null,
  market        market not null,
  provisional   boolean not null default false,  -- ruled by an untrusted brain
  lease_owner   text,
  lease_until   timestamptz,
  attempts      int not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index on candidates (state, next_check, lease_until);

create table check_results (          -- append-only; rows are never updated
  candidate_id  uuid        not null references candidates(id),
  check_kind    check_kind  not null,
  verdict       verdict     not null,
  confidence    numeric     not null,
  brain         text        not null,
  trusted       boolean     not null,
  usd_cost      numeric     not null,
  sources       jsonb       not null,
  decided_at    timestamptz not null default now(),
  primary key (candidate_id, check_kind)
);
```

`check_results` is append-only and the primary key is the idempotency key. A worker that dies after
the model answered but before the commit simply loses that one call. A worker that dies after the
commit cannot double-charge, because the insert conflicts.

### 2.2 The state machine

One function owns every transition. It is the first thing written in Rust and the reason the kernel
exists at all.

```
                  +-------------------------- retrieval or brain failed
                  |                                       |
  new --screen--> screened --claim--> vetting --result--> +--> deferred --+
                                          ^               |               |
                                          |               +--> killed     | (drain)
                                          +---------------+               |
                                          |   next_check advances         |
                                          +-------------------------------+
                                                          |
                                          all checks done +--> passed --publish--> published
```

- **`vetting` is a claim, not a phase.** A worker takes the row with `FOR UPDATE SKIP LOCKED`,
  stamps `lease_owner` and `lease_until`, runs exactly one check, writes one `check_results` row,
  advances `next_check`, releases. Nothing else happens inside a lease.
- **Kill-fast is preserved and is now structural.** Checks stay sequential per candidate, cheapest
  decisive first, because `next_check` only ever holds one value. Parallelism is across candidates,
  which is where it already was. A `refuted` on a hard gate sets `state = killed` and
  `next_check = null`; no further money is spent on that row by construction, not by a `break`.
- **`price_comparables` can never kill.** It is evidence-only (`prospector/price_comparables.py`).
  In this design it is not a special case in a filter; it is a check whose `verdict` is simply not
  read by the kill gate. See section 3.1.
- **A failure is not a verdict.** A check that raises writes no `check_results` row at all. It sets
  `state = deferred` and increments `attempts`. This is the same rule as today
  (`prospector/verify.py:365`, DEFER gate at `:693`), enforced by a type instead of a convention.

### 2.3 What falls out for free

- **Checkpointing.** A worker dies mid-check; the row was never written; another worker retries
  that one check. "Six checks of paid retrieval lost on one crash" cannot happen — not because of a
  workflow engine, but because the unit is smaller than the loss.
- **Resume stops being a code path.** `--resume`, the DEFER drain and provisional re-vet are today
  three separate flows in `prospector/run.py` (4,532 lines). Here they are one query: rows whose
  state says work remains. The producer/consumer asymmetry that has to be reasoned about carefully
  today disappears, because there is one loop.
- **Horizontal scale.** Workers are stateless and coordinate only through `SKIP LOCKED`. Scaling is
  `fly scale count 10`.
- **The funnel is a SQL query.** No diagnostics module, no file walks. The ops console becomes six
  queries against the rows that drive the machine, so the console and the engine cannot disagree.

### 2.4 The one thing it costs

Per-check leasing means more round trips to Postgres — one claim, one insert, one release per
check, so roughly 7x the transactions per candidate against today's one-lease-per-candidate. At
1,200 candidates/day that is about 25,000 transactions a day, which is nothing. It would matter at
a hundred times that volume, and it is worth writing down that this is the trade being made.

---

## 3. Where Rust earns it, and where it buys nothing

ADR 0006 records this and narrows ADR 0002 rather than reversing it.

### 3.1 The invariant kernel — types as enforcement

This is the part the incident record argues for, and it is small: on the order of two to three
thousand lines.

```rust
// Polarity is derived once, from the verdict itself. It cannot be configured per check.
pub enum Verdict { Supported, Refuted, Unverifiable }
impl Verdict {
    pub fn kills(self) -> bool { matches!(self, Verdict::Refuted) }
}

// An exception is not a verdict, and cannot be coerced into one.
pub fn run_check(..) -> Result<CheckOutcome, RetrievalFailure>;

// Trust is in the type. `publish` accepts only Trusted, so a provisional ruling
// physically cannot reach the money rail.
pub struct Ruling<P> { verdict: Verdict, confidence: f32, _p: PhantomData<P> }
pub struct Trusted;
pub struct Provisional;
pub fn publish(r: Ruling<Trusted>, p: PriceDecision) -> Listing;   // takes ownership of both

// One decision, one consumer. Moving it makes a second source of truth a compile
// error rather than a test.
pub struct PriceDecision { pence: Pence, rung: RungId }
```

Four recorded incident classes become compile errors: the legality polarity inversion, an exception
counted as evidence, a provisional verdict reaching publication, and price drift between the
provider object and the catalogue row (`prospector/bridge.py` exists today solely to stop that
fourth one by convention).

**What the kernel does not decide.** Which checks exist, their order, which brain rules, the
thresholds and the market config all stay in `config.yaml`. "Who may rule a verdict is CONFIG, not
code" is unchanged. The kernel enforces that a verdict is well-formed and where it may travel, not
what it says.

### 3.2 Retrieval and extraction — the honest performance case

Thousands of concurrent fetches on Tokio with no thread pool; streaming HTML extraction instead of
parse-then-extract; passage windowing and relevance ranking across cores. This is the only layer
whose CPU cost grows with candidate volume, and it is the only layer where Rust wins on measured
merit rather than on preference.

**It is already started.** `engine-rs/crates/prospector-retrieval` ports the cheap path of
`prospector/retrieval.py:fetch_page` and is graded byte-for-byte against the Python by
`scripts/retrieval_parity.py`. Grading it found a live grounding defect the Python had carried for
months: `requests` reports ISO-8859-1 for any `text/*` served without a charset parameter, so every
UTF-8 page served as bare `text/html` was decoded Latin-1 and reached the verdict brain as
mojibake. 32 corrupted characters in 5,504 on one page. Nothing in 8,431 tests could see it,
because mojibake is still well-formed text. A second implementation is an instrument the test suite
is not.

### 3.3 Pack rendering

Typst and Askama instead of `fpdf2` plus font-metric plumbing. Declarative typesetting, real
Unicode, and the whole Latin-1 class of bug stops being reachable.

### 3.4 Where Rust buys nothing

The verdict call is HTTP and JSON — a `Brain` trait with one impl per provider, and structured
output enforced by each API's own schema mode rather than by repair heuristics. Provider quotas and
the spend ceiling are policy, not compute. **Prompts stay as `.md` files outside the binary. They
are content, not code**, and a prompt change must never need a rebuild.

**Python's remaining role: none required.** Keep a PyO3 seam so an irreplaceable library is
reachable, and do not design around it.

---

## 4. The shared fetch cache

`prospector/retrieval.py:2054` already has a content-addressed cross-tick `DiskCache`. It is
per-box. At 120 candidates a day on one machine that is fine; at 1,200 across N workers it means
paying N times for the same fetch of the same authority domain.

```sql
create table fetch_cache (
  url_hash        bytea primary key,   -- sha256 of the normalised URL
  fetched_at      timestamptz not null,
  status          int         not null,
  content_type    text,
  body_key        text,                -- R2 object key; null when status has no body
  passage_index   jsonb                -- pre-extracted windows, so a hit skips extraction too
);
```

Checks converge on the same authority domains constantly — legality on the same regulator, payer
solvency on the same filings. A shared cache turns a repeated fetch into one Postgres lookup, and
because `passage_index` is stored it skips the CPU work as well as the network work.

**This is the biggest single lever on both cost and wall-clock in the whole document, and it
compounds as volume rises** — which is the opposite of how the CPU argument behaves. It is also
free provenance: the archived citation body is already in R2 before the pack is built from it.

Freshness stays a config knob (`retrieval.cache_ttl_s` today, `prospector/config.py:156`).

---

## 5. Spend as a leased budget

Today: read the ledger, sum today's metered dollars, compare to the cap
(`prospector/spend.py:19-20`, wired at `prospector/run.py:1713`). With one worker this is correct.
With two it races — both read the same sum, both decide there is room, both spend.

```sql
create table budget_leases (
  id            uuid primary key,
  worker_id     text        not null,
  candidate_id  uuid        not null,
  check_kind    check_kind  not null,
  usd_reserved  numeric     not null,
  expires_at    timestamptz not null,
  settled_usd   numeric                -- null until the check finishes
);
```

A worker reserves before the call and settles the actual cost after. Leases expire, so a dead
worker returns its money without anyone reaping it. The cap is then enforced against
`sum(reserved where unsettled) + sum(settled today)` in the same transaction that grants the next
lease, which is where the race dies.

**Scaling becomes one honest sentence: raise the cap, add workers.** ADR 0007.

**What already exists (LAW 3).** `prospector/store.py:585 claim()` / `:606 release()` /
`:532 lease_census()` is a working compare-and-swap lease with dead-owner reclaim and 22 tests,
including one that runs sixteen concurrent workers at a single row. It leases **rows**. This
decision leases **money**. The row lease is not replaced by it — it is the same pattern applied to
the second shared resource, and the Postgres version of the row lease is `SKIP LOCKED` plus the
`lease_owner`/`lease_until` columns that `migrations/0001_dossiers.sql` already carries.

---

## 6. Dedup: pgvector, but measure first

Embeddings in pgvector with cosine similarity for near-dupes, keeping the `difflib` + Jaccard path
as a cheap prefilter. `prospector/prescreen_prefilter.py` is embedding-based and deliberately wired
off today; that was a considered choice, not an oversight.

**So run both and compare rather than switching.** Once `check_results` exists the question "how
many semantic clones survived into a paid vet" is a SQL query, and that number decides it. No ADR
yet: this is the one item in the design that should not be decided before it is measured.

---

## 7. Process topology

Five Fly apps, one binary, different flags. No supervisord.

| App | What it does | Scale |
|---|---|---|
| `engine-worker` | drains the queue; all pipeline work | **N replicas — this is the scale dial** |
| `engine-tick` | enqueues generation on a schedule | 1 |
| `engine-ops` | Axum + htmx; reads Postgres and OTel | 1 |
| `searxng` | self-hosted grounding | scale with N |
| `store-api` / `store-web` | .NET + Next | unchanged |

A leak in one cannot take another down. Backups, log rotation and restore drills become cron
machines rather than supervisord programs. The storefront and API are not the engine and are not in
scope.

---

## 8. Observability and tests, from line one

- **Candidate id is the trace id; each check is a span.** Traces come from the same rows that drive
  the machine, so the ops console and the tracing backend cannot disagree — which is the failure
  mode `docs/CI_DEBUG_RUNBOOK.md` exists to survive today.
- **The golden set is the spine.** Fixture-backed retrieval, deterministic, and every invariant gets
  one named test whose name is the incident it came from.
- **Far fewer than 8,431 tests**, because most of that count tests orchestration this structure does
  not have. That is a prediction, not a target: deleting a test to hit a number is a defect.
- **Strict from day one.** `engine-rs/Cargo.toml` already denies `unsafe_code`, `unwrap_used`,
  `expect_used`, `panic`, `indexing_slicing`, `unwrap_in_result`, `todo` and `unimplemented`, with
  clippy `all = deny` and `pedantic = warn`, and no baseline. The 393-finding Python ratchet exists
  because strictness was retrofitted; from zero it costs nothing.

---

## 9. What this design refuses

- **Temporal, Redis, Kubernetes.** Postgres and Fly cover all three at this volume. This reverses
  the 2026-08-21 spec's Upstash Redis line.
- **A model roster of four.** Two brains, both trusted, plus one cold fallback. The roster exists so
  an outage cannot stall the line, not because diversity is a virtue in itself.
- **Files as state.** Postgres or R2, nothing in between.
- **A second pipeline.** There is one loop. Whatever happens to `run_v2.py`, nothing gets a
  successor.
- **Dashboard-only behaviour.** The repo stays the complete system: a fresh clone plus an env file
  runs the whole engine.

---

## 10. What is decided, what is not

**Decided** (ADRs 0004-0009): the unit of work; Postgres as queue, state, ledger and cache index;
Rust in the kernel and in retrieval/extract only; leased budget; the shared fetch cache; strangler
sequencing.

**Not decided, and named so nobody assumes otherwise:**

1. **Whether to start.** Each strangler step is a separate founder go. This document is a
   specification, not a schedule.
2. **pgvector for dedup** — section 6. Measure first.
3. **Raising `daily_cap_usd`** — money leaving the account, and the only real throughput dial.
4. **The fate of `run_v2.py` and `prospector/pipeline/`.** A 1,714-line deletion is staged in a
   working tree and uncommitted, pending a founder decision. Section 9 says no second pipeline; it
   does not say delete this one today.
5. **The check order.** "Cheapest decisive first" is the rule; the actual order and its costs should
   come from `check_results` once that table exists, not from the current hardcoded order.
6. **Two brains rather than four.** Named in section 9, but the live roster is `[minimax,
   claude_cli]` and changing it is a promotion decision with a golden-gate procedure
   (`CLAUDE.md`, "Who may rule a verdict is CONFIG").

---

## 11. Where the existing invariants live

The reference doc's invariants are correct and are the expensive part. This design re-encodes
them; it does not rediscover them. Explicitly, each one and where it lands:

| Invariant (today) | Where it lives here |
|---|---|
| Source-or-die | `check_results.sources` is `not null`; a `Ruling` cannot be built without them |
| Verdict-from-retrieval-only | `run_check` takes passages, not a candidate; there is no prior-knowledge path |
| The filter is universal | `check_kind` is one enum for every lane and market |
| Kill-fast | `next_check` holds one value; `Verdict::kills()` is derived |
| A KILL is first-class | `state = killed` still renders a dossier; the kill log is a query |
| Publish only on PASS | `publish` accepts `Ruling<Trusted>` and only a completed non-killed run mints one |
| An exception is never evidence | a raise writes no `check_results` row; `Result` makes it unrepresentable |
| Provisional never publishes | `Ruling<Provisional>` does not typecheck at `publish` |
| Price is a rung | `PriceDecision { pence, rung }`, moved not copied |
| One store per process | one Postgres DSN per process; no path derived from `__file__` |
| Two loops never merge | sales metrics never write `check_results` |

---

## 12. Sequencing: a strangler with a free oracle

ADR 0009. Not caution — sequencing. Each step ships value alone and each is reversible.

| # | Step | Ships when | Risk to correctness |
|---|---|---|---|
| 1 | **Retrieval + extract** as a Rust crate behind PyO3. Narrow interface (search, fetch, extract, select), no invariants, highest CPU. | it matches the Python on the fixture suite and on live pages | zero — graded both ways |
| 2 | **The Postgres schema and the (candidate, check) queue**, with the *Python* pipeline writing to it. | dual-write parity is green | zero — nothing reads Postgres until it agrees |
| 3 | **The kernel** — verdicts, gates, trust, price — in Rust, both implementations running the golden set until they agree on every dossier. | they agree on every dossier | this is the real step; the oracle is what makes it survivable |
| 4 | **Workers**, then decommission `run.py`. | the funnel query matches the old diagnostics | bounded by step 3 |

Steps 1 and 2 have already begun and neither was a rewrite:

- **Step 1**: `engine-rs/crates/prospector-retrieval` plus `scripts/retrieval_parity.py`, open as a
  pull request. It found a real bug in the Python before it replaced anything.
- **Step 2**: `migrations/0001_dossiers.sql` plus `scripts/dual_write_parity.py`, merged. The
  migration is a deliberate column-for-column transcription of the live SQLite schema, not an
  improved one, because a shadow that reshapes the data cannot prove a mismatch is not its own
  fault.

**8,431 tests stop being the cost of the rewrite and become the differential oracle that makes it
survivable.** That is the second time the suite turns out to be the asset rather than the burden.

---

## 13. What this supersedes in the 2026-08-21 spec

`docs/ENGINE_RUST_REWRITE_SPEC.md` stays on disk as the record of the earlier decision. Five points
changed:

| Point | 2026-08-21 | 2026-08-22 | Why |
|---|---|---|---|
| Queue | pgmq | `FOR UPDATE SKIP LOCKED` | one fewer extension, and the queue is then joinable with the state it drives |
| Unit of work | a candidate | **(candidate, check)** | the checkpointing gap is structural, not a feature to add |
| Brain | Python HTTP server on localhost in the same container | a Rust `Brain` trait per provider | two processes in one container is supervisord under another name; the call is HTTP and JSON either way |
| Cache | Upstash Redis | Postgres `fetch_cache` + R2 bodies | a second datastore for something Postgres does, and Redis is not durable |
| Apps | 4, one of them two processes | 5, one binary, different flags | a leak in one must not take another down |

Unchanged from that spec: the API stays .NET; the ops console is not rewritten; embeddings run on
CPU; Typst for packs; scope is the hot path.

---

## 14. The pack layer: an IR compiled to views

The buyer-facing pack is a separate layer with its own decisions, recorded in
[ADR 0010](decisions/0010-the-pack-is-an-ir.md) and [ADR 0011](decisions/0011-sourceref-is-minted-by-the-fetch-path.md).
`docs/PACK_NARRATIVE_PROGRAM.md` owns what the pack *says*; this owns what it *is*.

**One structure, several views.** The pack is a typed value — sections, claims, figures, citations —
and PDF, HTML, CSV and JSON are pure functions of it. Not prose generated then repaired.

```rust
pub enum Support { Cited(SourceRef), Unverifiable }     // two arms, and only two

pub struct Figure {
    label: String,
    value: Decimal,      // research figures are exact; see below on price
    unit: Unit,
    as_of: NaiveDate,
    source: SourceRef,   // no constructor path exists without one
}
```

**Two arms, not three.** A proposed `Support::VerifiedFact` — true because the model knows it — is
refused. It re-admits prior knowledge into a system whose founding invariant is
verdict-from-retrieval-only, and it fails in the same shape as the legality polarity bug: a
reasonable-looking addition that inverts the rule the type was built to enforce. Cited or
Unverifiable.

**`Unverifiable` is not a configurable blocker.** The same proposal wrote
`Unverifiable // triggers an explicit listing blocker if unallowed`. "If unallowed" is the fence
being smuggled back in as a switch someone can leave off, which is the exact history of programme
doc section 33. Making an unsourced figure unrepresentable is what retires that switch.

**But the section 33 fence stays post-hoc for the VERDICT, and that asymmetry is deliberate.**
`prospector/models.py:318-327` records why: `untraceable_figures` is observed only and must never
demote a verdict, because an absent number is *our* extraction failure and `kill_filter` can hard
fail on an `unverifiable` hard gate — demoting there would let our own bug kill a sound idea. So the
rule is: **a figure that cannot cite cannot be built into a pack; a figure that cannot cite must not
kill a candidate.** Two layers, two rules, and conflating them is a regression either way.

**Decimal for research figures. Price is already exact.** `prospector/pricing.py:64` holds
`price_pence: int`, so the money rail has never had a float. The exposure is in figures a buyer can
check — growth rates, market sizes, inflation assumptions — and those get `Decimal`.

**What ships in the box.** Beyond today's per-file `sha256`
(`prospector/pack_manifest.py:253,269`), two additions:

1. **A manifest hash over the whole set.** `prospector/bridge.py:1484` hashes the zip and uses it as
   the R2 key, but a zip digest moves with compression and entry order. A digest over the sorted
   file list and their content hashes is stable and is what a buyer can quote back.
2. **The archived source snapshots, as files, under `./sources/`.** Today
   `prospector/archive.py:471` stores a Wayback memento URL, best-effort inside a blanket except,
   and the documented worst case is "a pack with no mementos". Shipping the bytes does not depend on
   archive.org accepting a save, cannot 404 later, and works for pages the Internet Archive will not
   take. It turns "we cite sources" into "here are the pages, as they existed, dated" — at
   £2k-£27k a pack that is a product difference, not hygiene.

   **ADR 0008 makes this nearly free**: `fetch_cache.body_key` already puts the fetched bytes in R2
   before anything is built from them, so the snapshot is a copy, not a second fetch.

**Structured output kills parse failures, not fabrication.** It is worth being exact, because
overstating it would cost a real guard. Schema mode guarantees the tokens conform to the shape. It
does not stop a model emitting a `SourceRef` to a URL it never fetched, or a `Decimal` that appears
in no passage. It would retire `json_repair` Strategy 5 (`prospector/operator.py:203,255`) and
nothing more. The guard that closes the remaining gap is ADR 0011.

---

## 15. The test suite the redesign inherits

Full reasoning and the measurements in [ADR 0012](decisions/0012-the-test-ladder.md). Section 8
says what to instrument. This says what to test, and what to stop testing.

The suite has **8,303 tests in 543 files**, and **444 of those files (82%) are under
`tests/unit/`**. Most of them assert the shape of the orchestration that ADR 0004 replaces. They do
not survive the redesign, and rewriting them against the new shape would cost more than the
redesign.

The four incident tests worth keeping unchanged are the ones that assert a rule rather than a
call: legality polarity, latin-1 fonts, HTTP word boundaries, CPU-time budgets. They cost nothing
to keep.

**Always use the cheapest rung that can express the guarantee.**

1. **Types** — the failure becomes unrepresentable. Zero tests. This is where ADR 0010 and 0011
   already put the pack layer.
2. **Property tests** — one test, thousands of cases, and it survives the rewrite because it
   describes behaviour rather than structure. `hypothesis` to `proptest` is near-mechanical, which
   matters when the kernel moves to Rust.
3. **Differential replay** — for any rewrite the oracle is the current implementation. This is the
   same free oracle section 12 already leans on for the strangler, and its precondition is naming:
   the 3,608-dossier corpus is on the live volume and in R2, not in this checkout.
4. **Incident tests** — one per real bug, named for the bug.
5. **Evals with deterministic graders** — for probabilistic output, prefer a mechanical grader over
   a model's opinion. This one is load-bearing here and not a style preference: grading a verdict
   with a model's judgement re-admits prior knowledge, which is the exact invariant the engine
   exists to protect. Six graders that need no judge: does the cited passage contain the claim,
   did the fetched URLs resolve, does every figure carry a `SourceRef`, did kill-fast stop at the
   first refuted check, did cost stay inside the lease, does the golden set still agree.
6. **LLM-as-judge** — subjective quality only. Sampled, reported, never blocking.
7. **Production oracles** — deploy-verify with rollback, health checks, canaries, alerts. Already
   built.

**The seven properties** this engine wants are listed in ADR 0012. They are not written yet.

**What the engine deletes:** example-based unit tests of orchestration, tests named for a function
rather than a rule, mocks of our own internals, and anything self-healing. A test that rewrites
itself to match new code always agrees, which removes the oracle — and with agents writing the code
as well, that is a closed loop with no external check.

**Order.** Adopt the policy, write the properties, build the differential harness, formalise the
golden set, then prune. Pruning first would remove cover with nothing underneath it: the estate has
**0** `hypothesis` properties, **0** tests named `test_incident_*`, and **1** `proptest!` block
today.
