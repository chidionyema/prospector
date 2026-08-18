# The platform for the data engineer

**What this is.** Every byte the system keeps: every file in `store/`, every database with its
schema and row count, who writes it, who reads it, how fast it grows, what is backed up, and which
rows are already broken. Measured 2026-08-18 on this machine. Every number below carries the
command that produced it.

**Read this if** you are adding a table, changing a schema, chasing a disk-full alarm, restoring
from a backup, or trying to work out why the index and the tree disagree.

**The headline, first.** The store is **691 MB** and grows about **10.6 MB a day**. The ledger alone
is **258 MB in 907,977 lines** and has never been rotated. **189 index rows point at dossier files
that do not exist**, and one of them crashed the backup job with a `FileNotFoundError`. The last
successful backup was **2026-08-17 09:38** — 28 hours before this measurement. The restore drill
exists and **has never been run**.

Siblings: [security.md](security.md) for who can reach this data;
[legal-privacy.md](legal-privacy.md) for what of it is personal;
[sre-on-call.md](sre-on-call.md) for the alarms. The factual spine is
[../ESTATE_MAP.md](../ESTATE_MAP.md).

---

## 1. The complete `store/` inventory

```
du -sh store        →  691M
```

Every entry over 4 KB, from `du -sh store/* | sort -h`. Sizes are as measured this session.

### 1.1 The big four — 96% of the store

| Path | Size | Entries | Format | Writer | Readers |
|---|---|---|---|---|---|
| `store/prospector.jsonl` | **258 M** | 907,977 lines | newline-delimited JSON log records | `telemetry.route_logs_to_file` from every process | `scheduler/guard.py:132`, `report.py:184,608`, `adaptive.py:87`, `scheduler/status.py:96` |
| `store/dossiers/` | **190 M** | 2,931 entries | one JSON file per candidate | `store.py` on every vet | `run.py`, `publish/`, `pack_linter.py`, `restore_drill.py` |
| `store/_cache/` | **172 M** | 33,845 files | retrieval cache envelopes | `retrieval.py:46` | `retrieval.py` only |
| `store/scheduler/` | **54 M** | 30 entries | logs + JSONL trails | the daemon, the consumer, the watchdog | `scheduler/status.py`, ops console |

`store/scheduler/audit/` alone is **45 M** of the 54 M (`du -sh store/scheduler/*`).

### 1.2 Databases

| Path | Size (bytes) | Tables | Rows | Journal mode |
|---|---|---|---|---|
| `store/prospector.db` | 2,600,960 | `dossiers` | **2,995** | wal |
| `store/run_metrics.db` | 28,672 | `run_metrics` | **20** | wal |
| `store/self_modifications.db` | 24,576 | `modifications` | **12** | wal |
| `store/catalog.sqlite3` | **0** | *(none)* | 0 | delete |

`store/catalog.sqlite3` is a **zero-byte file with no tables, in `delete` journal mode, and no code
anywhere references its name** — `rg -n "catalog.sqlite3" --glob '*.py' --glob '*.cs' --glob '*.json' .`
returns nothing. It is dead. Deleting it is safe and it should go. Gap D9.

Each WAL database carries a `-wal` and a `-shm` sidecar. All three `-wal` files measure 0 B right
now, which means every writer has checkpointed. The three `-shm` files are 32 K each. **A restore
that copies only the `.db` and drops the `-wal` loses any uncheckpointed transaction** — `sqlite3
<db> ".backup"` or the `mode=ro` snapshot used by `restore_drill.py` is the correct way to copy one,
never `cp`.

### 1.3 The JSON side-stores

| Path | Bytes | Entries | Shape | Writer |
|---|---|---|---|---|
| `store/lint_url_cache.json` | 398,990 | **2,914** | `{url: {status, note, ts}}` | `bridge.py:1123` |
| `store/citation_archive.json` | 292,421 | **1,260** | `{url: {memento, ts}}` | `store.py:279` → `bridge.py:1037` |
| `store/incumbent_cache.json` | ~120 K | — | incumbency lookups | verify path |
| `store/provider_health.json` | ~4 K | — | dead marks, moat chain | `health.py:36` |
| `store/provider_health_noncritical.json` | ~4 K | — | dead marks, non-critical chain | `health.py:42` |
| `store/exhausted_families.json` | ~4 K | — | permanently-exhausted families | `health.py` |
| `store/retired_passes.json` | ~8 K | — | passes withdrawn from sale | `tools/retire_rotted_passes.py` |

Counts measured with
`python3 -c "import json;print(len(json.load(open('store/<file>'))))"`.

**The two health files are physically separate on purpose.** `health.py:38-42` states the invariant:
a non-critical provider going dead must never blind the moat, and vice versa. Same class, two files.
Merging them would let a DeepSeek outage stop verdicts.

### 1.4 The rest of `store/`, by directory

| Path | Size | What it is |
|---|---|---|
| `store/numeric_citation_shadow/` | 4.6 M | shadow-mode output of the numeric-citation checker |
| `store/control_center/` | 1.5 M | ops console run state |
| `store/prescreen_shadow/` | 1.2 M | shadow-mode prescreen comparisons |
| `store/pricing/` | 600 K | pricing ladder decisions |
| `store/golden_runs/` | 580 K | golden-set regression outputs |
| `store/listings/` | 488 K | published listing JSON |
| `store/markets/` | 376 K | per-market config and probe state |
| `store/runs/` | 280 K | per-run records |
| `store/ops/` | 160 K | ops surface state |
| `store/listings_archive/` | 80 K | superseded listings |
| `store/launch/` | 12 K | launch checklist state |
| `store/claims/`, `store/inflight/` | 0 B | empty directories |

### 1.5 Loose logs and JSONL at the top level

`store/generation_metrics.jsonl` (100 K), `store/retitle_log.jsonl` (80 K),
`store/shelf_copy_log.jsonl` (4 K), `store/load_samples.jsonl` (4 K), plus ten `.log` files from
one-off golden and validation runs (`_golden_deep.log`, `_canary_k3.log`,
`_lastrun_resilience100.log`, `run_mtd.log`, `run_repair.log`, `validation_run.log`,
`golden_live.log` 20 K, `golden_claude.log` 52 K, `golden_fixmode.log` 60 K).

**These are one-shot artefacts sitting in the durable state directory.** None is read by running
code. They should live under a `store/_scratch/` that the backup skips. Gap D8.

### 1.6 Hand-made database snapshots

```
ls -l store/*.bak
-rw-r--r--  1,261,568   6 Aug 07:39  store/prospector.db.pre-audience.bak
-rw-r--r--    942,080  30 Jul 17:44  store/prospector.db.pre-market.bak
-rw-r--r--  1,216,512   6 Aug 01:49  store/prospector.db.pre-tombstone-20260806T004905Z.bak
```

Three copies a human made by hand before three schema changes. `backup_store.py:430-433` names them
explicitly as the reason the index went into the automated backup: "Until 2026-08-07 this file was
in the backup ONLY as ad-hoc migration copies somebody made by hand before a schema change." They
are now redundant with the daily R2 copy and are 3.4 MB of dead weight.

`.gitignore:47-52` was extended specifically because `store/*.db` does not match
`prospector.db.pre-market.bak`. Two extra lines, `store/*.db.*` and `store/*.bak`.

---

## 2. Every schema, dumped

### 2.1 `store/prospector.db` — the catalogue index

`sqlite3 store/prospector.db ".schema"`:

```sql
CREATE TABLE dossiers (
    candidate_id    TEXT PRIMARY KEY,
    title           TEXT,
    decision        TEXT,
    gate_fired      TEXT,
    composite       REAL,
    created_at      TEXT,
    reverify_due_at TEXT,
    path            TEXT
, one_liner TEXT, ambition_tier TEXT, structural_form TEXT, provisional INTEGER DEFAULT 0,
  dense_reward REAL, adversarial_confidence REAL, persona TEXT,
  retrieval_degraded INTEGER DEFAULT 0, market TEXT, tombstone TEXT, audience TEXT,
  seed_kind TEXT, lease_owner TEXT, lease_until REAL);

CREATE INDEX idx_decision        ON dossiers(decision);
CREATE INDEX idx_reverify        ON dossiers(reverify_due_at);
CREATE INDEX idx_ambition_tier   ON dossiers(ambition_tier);
CREATE INDEX idx_structural_form ON dossiers(structural_form);
CREATE INDEX idx_dense_reward    ON dossiers(dense_reward);
CREATE INDEX idx_persona         ON dossiers(persona);
CREATE INDEX idx_market          ON dossiers(market);
CREATE INDEX idx_audience        ON dossiers(audience);
CREATE INDEX idx_seed_kind       ON dossiers(seed_kind);
CREATE INDEX idx_lease_until     ON dossiers(lease_until);
```

**Read the schema text, not just the columns.** Everything after `path TEXT` is on one line because
it arrived through `ALTER TABLE ADD COLUMN`. That is the migration story of this table written into
its own definition: eight original columns, fourteen added since. Each addition is nullable or has a
`DEFAULT`, which is the only way `ADD COLUMN` works in SQLite without a rewrite.

Column meanings that are not obvious:

| Column | What it carries |
|---|---|
| `path` | absolute path to the dossier JSON. Absolute, so it does not survive a move of the store — see §6.2 |
| `tombstone` | why the row has no file: `dossier_missing`, `quarantined_ungrounded`, or empty |
| `provisional` | 1 if the ruling brain was outside `moat_primary()` |
| `retrieval_degraded` | 1 if the verdict was reached on degraded evidence |
| `lease_owner`, `lease_until` | the drain lease. Two workers cannot re-vet the same row |
| `reverify_due_at` | when this row becomes drainable again |
| `dense_reward`, `adversarial_confidence` | scoring inputs |

`idx_lease_until` exists because the drain's first query is "which rows are unleased and due". Ten
indexes on 2,995 rows is generous; the table is small enough that it does not matter.

### 2.2 `store/run_metrics.db`

```sql
CREATE TABLE run_metrics (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT NOT NULL UNIQUE,
    timestamp            TEXT NOT NULL,
    yield_rate           REAL NOT NULL DEFAULT 0.0,
    kill_rate_by_gate    TEXT NOT NULL DEFAULT '{}',
    diversity_score      REAL NOT NULL DEFAULT 0.0,
    health_score         REAL NOT NULL DEFAULT 0.0,
    health_sub_scores    TEXT NOT NULL DEFAULT '{}',
    candidates_generated INTEGER NOT NULL DEFAULT 0,
    candidates_passed    INTEGER NOT NULL DEFAULT 0,
    lane                 TEXT DEFAULT '',
    active_changes       TEXT DEFAULT '[]'
);
CREATE INDEX idx_run_metrics_ts ON run_metrics(timestamp DESC);
```

**20 rows.** `kill_rate_by_gate`, `health_sub_scores` and `active_changes` are JSON blobs in TEXT
columns — queryable only through `json_extract` or in Python. That is a deliberate trade: the shape
of a gate map changes as gates are added, and a real column per gate would need a migration each
time.

### 2.3 `store/self_modifications.db`

```sql
CREATE TABLE modifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id       TEXT NOT NULL UNIQUE,
    timestamp       TEXT NOT NULL,
    component       TEXT NOT NULL,
    field           TEXT NOT NULL,
    old_value       TEXT NOT NULL,
    new_value       TEXT NOT NULL,
    trigger_signal  TEXT NOT NULL DEFAULT '',
    expected_effect TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    measured_effect TEXT DEFAULT NULL,
    rolled_back_at  TEXT DEFAULT NULL
);
CREATE INDEX idx_modifications_ts     ON modifications(timestamp DESC);
CREATE INDEX idx_modifications_status ON modifications(status);
```

**12 rows.** The schema is well designed for its job: `old_value` and `new_value` make every change
reversible, `expected_effect` is recorded *before* the outcome, and `measured_effect` is nullable so
an unmeasured change is visibly unmeasured rather than assumed good.

**`measured_effect` being nullable is the honest part and also the risk.** A table of twelve
self-modifications where most `measured_effect` are `NULL` is a record of changes made and never
graded. The check: `sqlite3 store/self_modifications.db "SELECT status, measured_effect IS NULL,
COUNT(*) FROM modifications GROUP BY 1,2;"`

### 2.4 The store API's database — not here

The store API keeps its own SQLite on a Fly volume, not in this tree.
`store_platform/src/Store.Api/Program.cs:26`:

```csharp
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
                       ?? "Data Source=store.db";
```

Its schema is EF Core migrations under `store_platform/src/Store.Catalog/Migrations/`, and the
field-by-field content is documented in [legal-privacy.md](legal-privacy.md) §1.1. **These two data
estates never share a process, a file or a backup job.** The engine store is the research corpus;
the API database is the money. They are backed up by two different scripts to two different places
(§7).

---

## 3. `store/prospector.jsonl` — the ledger

### 3.1 What it actually is

It is **not** a domain event stream. It is the Python logging output of every process, routed to a
file as JSON records. `scheduler/guard.py:15`: "`run_scheduled` calls
`route_logs_to_file(<store>/prospector.jsonl)`".

Head of file, measured:

```json
{"timestamp": "2026-06-15 00:46:11,080", "level": "INFO", "name": "prospector",
 "message": "Starting signal pipeline", "phase": "signal_pipeline"}
```

Tail of file, measured:

```json
{"timestamp": "2026-08-18 13:58:36,919", "level": "INFO", "name": "prospector",
 "message": "Completed run_check", "event": "latency", "operation": "run_check",
 "latency_ms": 11.27, "status": "success", "candidate_id": "09825c75cbc4c101", "phase": "vetting"}
```

**Five keys are on every one of the 907,977 lines**: `timestamp`, `level`, `name`, `message`,
`phase`. Everything else is optional.

### 3.2 Measured totals

Full streaming parse, `python3` over every line:

```
LINES 907977   BAD 0   BYTES 270,339,022
FIRST_TS 2026-06-15 00:46:11,080
LAST_TS  2026-08-18 13:58:36,919
```

**Zero unparseable lines in 907,977.** That is the `jsonl_atomic` single-`O_APPEND`-write design
working — see §5.1.

### 3.3 By level

| Level | Count | Share |
|---|---|---|
| INFO | 772,369 | 85.1% |
| ERROR | **70,707** | **7.8%** |
| WARNING | 63,945 | 7.0% |
| CRITICAL | **964** | 0.1% |

**70,707 ERROR lines and 964 CRITICAL lines.** Nobody is reading them. An error rate of 7.8% in a
durable log means the log has stopped being an alarm and become background noise. Gap D5.

### 3.4 By phase

| Phase | Count |
|---|---|
| `vetting` | 546,792 |
| `main` | 320,876 |
| `signal_pipeline` | 39,140 |
| `decay_loop` | 1,049 |
| `testing` | **617** |

**617 lines carry `phase: "testing"`.** The test suite has written into the production ledger. The
design note at `jsonl_atomic.py` closes with the reason this must not happen: "Paths are ARGUMENTS,
never module state: nothing here binds a store path at import, which is the defect that let pytest
reach the production audit log and durable ledger." Those 617 lines are the fossil of that defect.
They are harmless now and they are proof the trap was real. Gap D6.

### 3.5 By `event`, where an `event` key exists

`rg -o '"event": ?"[a-z_.]+"' store/prospector.jsonl | sort | uniq -c`, cross-checked against the
full parse:

| `event` | Count |
|---|---|
| *(no `event` key)* | 469,930 |
| `latency` | **396,437** |
| `spend` | **33,553** |
| `listing_page` | 1,710 |
| `teaser_social` | 1,577 |
| `launch_email` | 1,563 |
| `seo_preview` | 1,431 |
| `build_spec` | 590 |
| `gtm_plan` | 569 |
| `ops_plan` | 568 |
| `financial_model` | 49 |

**Eleven distinct values. Two of them are 96% of the tagged lines.** `latency` is instrumentation;
`spend` is the one that governs money. The eight content events are the artifact renderers.

`financial_model` at **49** against `listing_page` at **1,710** is a 35:1 ratio. Either financial
models are generated for a tiny subset by design, or that renderer is mostly failing. The check:
`rg -o '"event": ?"financial_model"[^\n]*"status": ?"[a-z]+"' store/prospector.jsonl | sort | uniq -c`.

### 3.6 Key frequency — what the ledger can answer

| Key | Lines carrying it |
|---|---|
| `timestamp`, `level`, `name`, `message`, `phase` | 907,977 (all) |
| `candidate_id` | 556,574 |
| `event` | 429,990 |
| `status` | 396,460 |
| `operation`, `latency_ms` | 396,437 |
| `error` | **98,041** |
| `retries_allowed` | 76,831 |
| `session_id` | 70,378 |
| `query` | 70,066 |
| `web` | 65,381 |
| `input`, `output` | 51,224 each |
| `provider` | 50,051 |
| `amount_usd` | 33,553 |
| `model` | 32,137 |
| `check` | 30,000 |
| `verdict`, `confidence` | 22,436 each |
| `cached` | 20,717 |
| `cost_usd` | 19,520 |
| `stage` | 13,855 |
| `priced` | 13,147 |
| `attempt` | 13,026 |

`candidate_id` on 556,574 lines is what makes the ledger useful: you can reconstruct everything that
happened to one candidate with a single grep.

`cached` on 20,717 lines against `web` on 65,381 gives a rough cache-hit picture. `cost_usd` on
19,520 and `amount_usd` on 33,553 are the two money keys — and `amount_usd` is the one the spend
guard sums.

### 3.7 The spend guard is the only sanctioned reader

`prospector/ops/spend.py:9` states it: "**There is exactly ONE reader of
`store/prospector.jsonl`.** `scheduler/guard.py`". `guard.py:149` names the rule
`never-hand-parse-the-spend-ledger` and says a hand-rolled sum over the file is the wrong way to get
today's spend.

The reason is at `guard.py:447` and `guard.py:250`: the ledger "reached 157 MB and `evaluate()`
measured 108s". **It is 258 MB now — 64% larger than at the point that was recorded as a
problem.** If `evaluate()` scaled linearly it is now around 175s. That is a spend guard that takes
nearly three minutes to answer "may I generate", on a daemon whose tick interval is measured in
minutes. Gap D1.

### 3.8 Growth

```
270,339,022 bytes over 2026-06-15 00:46 → 2026-08-18 13:58 = 64.55 days
  = 4.19 MB/day
  = 14,067 lines/day
```

At this rate: **1.53 GB/year for the ledger alone.** No rotation exists. There is no `logrotate`
config, no size cap in `route_logs_to_file`, and the backup uploads a dated gzip of the whole file
every day — so R2 storage grows quadratically with time, not linearly. Gap D1.

The one rotation that has happened anywhere in `store/` was manual and only on a scheduler log:
`store/scheduler/launchd.err.log.20260816T115822Z.gz`, 3.3 M.

---

## 4. `store/dossiers/` — the product

### 4.1 Naming and counts

```
ls store/dossiers | wc -l          → 2931 entries (2929 files + 2 subdirectories)
```

| Suffix | Count | What it is |
|---|---|---|
| `<id>.kill.json` | **2,698** | a candidate that failed a hard gate |
| `<id>.lint.json` | **123** | the pack linter's persisted receipt for a pass |
| `<id>.pass.json` | **108** | a candidate that cleared every gate |
| `quarantine_ungrounded/` | 9 files, 164 K | moved out when found ungrounded |
| `retired/` | 30 files, 2.0 M | passes withdrawn from sale |

`<id>` is a 16-hex-character candidate id, e.g. `00030c91b200cd01`. It is content-addressed, so the
same candidate always lands on the same filename.

**2,698 kills to 108 passes is a 25:1 ratio.** That is the filter working as designed — "A KILL with
a cited reason is first-class" — and it is why the kill files, not the pass files, dominate the disk.

**`.lint.json` at 123 versus `.pass.json` at 108.** There are more lint receipts than passes. The
extra 15 are lint runs against candidates that were later retired or re-vetted to kill. The lint
receipt is not deleted when its subject stops passing. That is a small orphan class of its own.

### 4.2 Field structure

`.pass.json` and `.kill.json` are **the same shape**. Measured with
`python3 -c "import json,glob; print(list(json.load(open(sorted(glob.glob('store/dossiers/*.kill.json'))[0])).keys()))"`:

```
['candidate', 'ambition_tier', 'decision', 'gate_fired', 'reason', 'checks',
 'adversarial', 'score', 'model_version', 'provider_chain', 'created_at',
 'reverify_due_at', 'provisional', 'dense_reward', 'sources']
```

Identical for `.pass.json`. **The only difference between the two files is the value of `decision`
and whether `gate_fired` is populated.** The suffix is a convenience for globbing, not a different
format. Anything that treats `.kill.json` as a reduced record is wrong.

Each element of `checks` carries:

```
['check_name', 'verdict', 'confidence', 'rationale', 'citations', 'sources',
 'queries', 'query_source', 'degraded', 'retrieval_failed', 'provider', 'provisional']
```

**`degraded` and `retrieval_failed` are the two fields that separate a real finding from an
outage.** A check with `retrieval_failed: true` contributed nothing to the gates
(`kill_filter.py:34-35`). Any analysis over this corpus that ignores those two booleans will count
our own downtime as evidence — which is exactly the failure preserved in
`store/dossiers/2102bacc6dd75cf9.kill.json`, a KILL whose seven checks all read
`unverifiable, conf 0.0, "Verdict call failed; fail-safe."`

`provider` and `provisional` per check are the audit trail for the trust fence: which brain ruled
this specific check, and was it inside `moat_primary()`.

`.lint.json` is a different shape entirely:

```
['ok', 'checked_at', 'ruleset', 'market', 'urls_checked', 'grammar_rate_per_1k',
 'repetition_findings', 'sections_graded', 'readability_grade', 'house_spec',
 'human_register', 'problems', 'pack_complete', 'completeness_problems',
 'bundle_missing', 'bundle_stubs', 'unverified_claims']
```

**This file is the answer to "is this pack good enough to sell", already computed and on disk.**
Re-running the linter to find out is paying twice for an answer that is already written down.

### 4.3 Index statistics

All from `sqlite3 store/prospector.db`:

| Query | Result |
|---|---|
| `SELECT decision, COUNT(*) GROUP BY 1` | `kill` 2,842 · `pass` 108 · `defer` 45 |
| `SELECT provisional, COUNT(*) GROUP BY 1` | `0` 2,994 · `1` **1** |
| `SELECT retrieval_degraded, COUNT(*) GROUP BY 1` | `0` 2,969 · `1` **26** |
| `SELECT tombstone, COUNT(*) GROUP BY 1` | `''` 2,806 · `dossier_missing` **180** · `quarantined_ungrounded` **9** |
| `SELECT MIN(created_at), MAX(created_at)` | `2026-06-13T18:48:45Z` → `2026-08-18T00:27:35Z` |

Gate breakdown, `SELECT gate_fired, COUNT(*) GROUP BY 1 ORDER BY 2 DESC`:

| Gate | Count |
|---|---|
| `moat_ungrounded` | **1,042** |
| `min_composite` | 753 |
| `incumbency` | 271 |
| `source_or_die` | 256 |
| `value_durability` | 202 |
| *(empty — passed or deferred)* | 162 |
| `adversarial_decisive` | 154 |
| `payer_solvency` | 60 |
| `legality` | 30 |
| `distribution` | 22 |
| `currency` | 14 |
| `route_to_market` | 13 |
| `pain_reality` | 9 |
| `buyer_intent` | 7 |

**`moat_ungrounded` at 1,042 is 35% of every row.** The single most common outcome in this database
is "we could not get evidence", not "we assessed it and it failed". That is a retrieval-quality
number, not a filter-quality number, and it is the biggest signal in the table.

**`decision = kill` is 2,842 but only 2,698 `.kill.json` files exist** — a 144-file shortfall,
consistent with the 180 `dossier_missing` tombstones. §6.1.

### 4.4 Size per dossier

```
190 MB / 2,806 live files = ~69 KB per dossier
```

At 45.9 new rows/day (2,995 rows over 65.2 days), that is **3.2 MB/day** of dossiers, or **1.15
GB/year**.

---

## 5. Write paths, concurrency and locking

### 5.1 JSONL: single `O_APPEND` write, no lock

`prospector/jsonl_atomic.py` is the only sanctioned appender for every `.jsonl` trail under
`store/scheduler/`. Its header is the clearest piece of concurrency reasoning in the repo and it is
worth knowing rather than rediscovering.

**Why not tmp+rename**, from `jsonl_atomic.py:8-24`, in three facts:

1. These are append-only logs with **concurrent writers**. `ticks.jsonl` is written by the live
   daemon *and*, at a measured **59.6 rows/hour**, by a one-shot driver in the Hermes estate.
   `audit/<day>.jsonl` is written by the daemon, backfills, and every manual CLI run at once.
2. tmp+rename means read-whole-file, append, rename over. **Every line another process appended
   between your read and your rename is silently deleted.**
3. `os.replace` swaps the inode. A peer holding an open `O_APPEND` descriptor keeps writing into the
   now-unlinked old inode, so its lines vanish too.

**Why a single `O_APPEND` write is safe**, from `:26-35`: POSIX XSH 2.9.7 requires that with
`O_APPEND` the offset moves to EOF and the write happens with no intervening modification. Darwin
and Linux implement that under the inode lock. Two appenders can never overwrite each other or
interleave byte ranges.

**The one residual risk is handled explicitly**: a short write (ENOSPC, EFBIG, EINTR) raises
`TornAppendError` and **deliberately does not retry the remainder** — retrying under `O_APPEND`
re-seeks to the current EOF, so a peer's complete line can land between the two fragments, turning
one torn record into two corrupt ones. One damaged line is the bounded outcome.

**What the format cannot do**, from `:52-56`: bare NDJSON has no framing, so a mid-file short write
costs the damaged record and merges it with its successor. Fixing that needs a length prefix or a
checksum, which would break every existing reader including external ones.

**Measured result: 0 bad lines in 907,977** (§3.2). The design holds.

`fcntl` is imported at `jsonl_atomic.py:57` — so a lock exists for the paths that need one, but the
append primitive itself does not rely on it.

### 5.2 SQLite: two traps, both already paid for

**Trap one — `with conn` does not close the connection.** `prospector/store.py:104-121`:

> This used to `return` a bare `sqlite3.Connection`. Every one of the call sites below already
> wrote `with self._connect() as conn:` — which reads like a resource manager but is not one:
> `sqlite3.Connection.__exit__` commits or rolls back the transaction and deliberately leaves the
> connection OPEN. So each call leaked two descriptors (the db and its WAL) for the process's
> lifetime.
>
> Measured 2026-08-06: **200 `has_dossier()` calls leaked 201 fds, monotonic.**

It went unnoticed because every caller was O(1) per run. `run.drain_survey` was the first O(rows)
caller and it took the daemon past launchd's **256-fd default inside four seconds of starting** —
`[Errno 24] Too many open files` writing `heartbeat.json`, which made the drainable count
unavailable, which correctly-but-uselessly suppressed generation.

The fix is `_connect` as a `@contextmanager` (`store.py:103`): inner `with conn:` preserves the
commit/rollback semantics every call site relied on, and `finally: conn.close()` closes either way.

**Trap two — `PRAGMA journal_mode` is not covered by `timeout`.** `store.py:127-145`:

> `timeout=10.0` above does NOT cover this statement, which is the whole defect: SQLite documents
> that changing the journal mode while another connection has the database open "returns
> SQLITE_BUSY immediately without invoking the busy handler". So the one statement here that needs
> a retry is precisely the one the timeout cannot help.

Symptom: `sqlite3.OperationalError: database is locked` out of `Store.__init__`, i.e. out of
`import prospector.api` (`api.py:22` builds a module-level `Store`). Found 2026-08-15 when
`pytest.ini` began running under `-n auto`: **four xdist workers importing
`tests/integration/test_api.py` at once, two losing the WAL conversion, so two workers collected the
file and two did not, and xdist aborted the whole run with "Different tests were collected between
gw2 and gw3".** That reads as a broken test suite. It is a real concurrency defect in the store,
and the live daemon, the CLI and the API all open this same database.

The fix reads the mode first (a shared lock, always safe) and only attempts the conversion when it
is not already `wal`. Journal mode is a durable property of the *file*, so once any connection has
converted it, every later connection reads `wal` and never contends again. The `except
sqlite3.OperationalError: pass` is narrow on purpose — the only thing lost is an optimisation
another connection is already applying.

### 5.3 Lock files

`store/provider_health.lock` and `store/provider_health_noncritical.lock` (both 0 B) guard the two
health files. `store/scheduler/drain_attempts.lock` guards the drain counter. These are real
`fcntl` locks, not advisory markers.

`prospector/claim_lock.py:126` notes its path is "taken from the cfg (which honours
PROSPECTOR_STORE_DIR) and there is deliberately NO" fallback — a lock in the wrong store is not a
lock.

### 5.4 The lease columns

`dossiers.lease_owner` and `dossiers.lease_until` (with `idx_lease_until`) are how two drain workers
avoid re-vetting the same row. This is database-level mutual exclusion, and it is the right choice:
a file lock cannot coordinate two processes on two different machines, and the index is the only
thing both see.

---

## 6. Data quality: what is already broken

### 6.1 189 index rows have no file

Measured two ways this session.

```python
# forward: does every indexed path exist?
index rows: 2995   path missing on disk: 180

# reverse: does every file have a row?
dossier files: 2806   unindexed: 0   indexed-but-no-file: 189
```

The two numbers differ by 9 because the 9 `quarantined_ungrounded` rows point at files that were
*moved* into `store/dossiers/quarantine_ungrounded/` rather than deleted. So:

- **180** rows tombstoned `dossier_missing` — the file is genuinely gone.
- **9** rows tombstoned `quarantined_ungrounded` — the file moved to the quarantine subdirectory,
  and the index path was not updated.
- **0** files on disk without an index row. The index is a superset, never a subset. Good.

**The tombstone column is doing its job**: every missing file is *labelled* missing. This is not
silent corruption. But 189 of 2,995 rows (6.3%) resolve to nothing, and the `path` column still
holds the old absolute path in all 189 cases.

**Find them:**

```bash
sqlite3 store/prospector.db \
  "SELECT candidate_id, tombstone, path FROM dossiers WHERE tombstone != '';"
```

### 6.2 The orphans crashed the backup

`store/backup.log` carries the proof:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '/Users/chidionyema/Documents/code/prospector/store/dossiers/d0dc386eb8f7934f.defer.json'
```

The backup job iterated the index, tried to upload a file the index promised, and died. **A data
quality problem became a backup outage.** This is the single best argument for cleaning up §6.1:
the orphans are not inert.

Note the suffix — `.defer.json`. A fourth suffix that no longer exists anywhere in
`store/dossiers/` (§4.1 found only `.kill`, `.pass`, `.lint`). Defer rows are now held in the index
without a file at all, and 45 rows have `decision = 'defer'`.

### 6.3 `path` is stored absolute

Sampled from the orphan query:

```
('592a9f095cc42974', '/Users/chidionyema/Documents/code/prospector/store/dossiers/592a9f095cc42974.kill.json')
```

**Every `path` value is an absolute path rooted at this machine's home directory.** Move the store,
restore it into a different directory, or run from the `prospector-live` checkout with
`PROSPECTOR_STORE_DIR` pointed elsewhere, and every one of the 2,995 paths is wrong.

The mitigating fact is that the path is derivable: `store_root() / "dossiers" / f"{id}.{suffix}.json"`.
Nothing *needs* the stored value. But `restore_drill.py` assertion 4 resolves index rows to restored
files, and it works only because the drill restores into a scratch directory and rewrites the root.

**Storing a store-relative path would remove the whole class.** Gap D3.

### 6.4 The `-shm` files are 32 K with 0-byte WALs

Not a defect, but worth knowing: a 0-byte `-wal` with a live `-shm` means the last writer
checkpointed cleanly and the shared-memory index is still mapped. If you ever see a **large `-wal`
that never shrinks**, a reader is holding a snapshot open and blocking checkpoint — that is the
`with conn` leak (§5.2) coming back.

---

## 7. Backups

### 7.1 What exists

| Job | Script | Schedule | Target | Covers |
|---|---|---|---|---|
| Engine store | `scripts/backup_store.py` | daily 03:40, `ops/launchd/com.prospector.backup.json` | Cloudflare R2 | `store/dossiers/*.json`, `store/prospector.jsonl`, `store/prospector.db`, a repo bundle |
| Money and keys | `scripts/offsite_backup.py` | separate job | offsite | store API SQLite, DataProtection key ring |
| Restore drill | `scripts/restore_drill.py` | **never scheduled, never run** | scratch dir | proves the above |

The launchd plist runs the script through a receipt wrapper:

```json
"ProgramArguments": [
  ".../.venv/bin/python", "/Users/chidionyema/.hermes/scripts/launchd_receipt.py",
  "--label", "com.prospector.backup", "--",
  ".../.venv/bin/python", ".../scripts/backup_store.py"
],
"StartCalendarInterval": { "Hour": 3, "Minute": 40 }
```

### 7.2 Why the script fails loudly

`backup_store.py:19-26` explains why it does not reuse `bridge.R2Uploader`:

> R2Uploader is deliberately silent: it returns False rather than raising, and no-ops entirely when
> unconfigured, so a missing credential can never stop a pack from selling. That is right for the
> publish path and exactly wrong here. **A backup that "succeeds" by doing nothing is worse than no
> backup, because you stop looking.**

And `:28-33`: "Uploading is not backing up. This re-downloads a random sample of what it just wrote
plus the whole ledger object, and compares SHA-256 against the local file."

The origin story, `:7-17`: on 2026-07-31 the store held 1,153 dossiers and a 295,563-line ledger,
`tmutil destinationinfo` said "No destinations configured", the repo path was not in iCloud or
Dropbox, and both files were gitignored. **"Not in git" had quietly become "not anywhere".**

### 7.3 What the log says

Last ten runs, from `tail -20 store/backup.log`:

```
STORE_BACKUP PASS dossiers=1875 uploaded=219 unchanged=1656 verified=8/8 ledger=...2026-08-10... db=...2026-08-10...
STORE_BACKUP PASS dossiers=2002 uploaded=163 unchanged=1839 verified=8/8 ledger=...2026-08-11... db=...2026-08-11...
STORE_BACKUP PASS dossiers=2016 uploaded=25  unchanged=1991 verified=8/8 ledger=...2026-08-13... db=...2026-08-11...
STORE_BACKUP PASS dossiers=2099 uploaded=189 unchanged=1910 verified=8/8 ledger=...2026-08-14... db=...2026-08-14...
STORE_BACKUP PASS dossiers=2152 uploaded=131 unchanged=2021 verified=8/8 ledger=...2026-08-15... db=...2026-08-15...
STORE_BACKUP PASS dossiers=2364 uploaded=254 unchanged=2110 verified=8/8 ledger=...2026-08-16... db=...2026-08-16...
STORE_BACKUP PASS dossiers=2579 uploaded=521 unchanged=2058 verified=8/8 ledger=...2026-08-17... db=...2026-08-16... mirror=repo/2026-08-17T083751Z.bundle bytes=15576077
```

Earlier in the same log, two consecutive failures:

```
STORE_BACKUP NOTE endpoint unreachable after 9 attempt(s) in 180s:
  URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>
STORE_BACKUP UNREACHABLE R2 endpoint did not answer within the wait budget; nothing was
  uploaded. This is a network failure, not a data failure — the next scheduled run retries
  from the same local state.
```

**That message is correct and well written.** It distinguishes a network failure from a data
failure, and says what happens next. It is the standard other failure messages in this estate should
meet.

### 7.4 Three live problems in the backup

**(a) No backup has run in 28 hours.**

```
ls -l store/backup.log   →   15472  17 Aug 09:38
date -u                  →   Tue 18 Aug 2026 13:40:41 UTC
launchctl list | grep prospector.backup   →   -   0   com.prospector.backup
```

The job is loaded and its last exit status is 0, but nothing has been appended to the log since
2026-08-17 09:38. The 03:40 slot on 2026-08-18 produced no line. The most likely cause is a sleeping
laptop, since `StartCalendarInterval` on a sleeping Mac fires at wake rather than at the missed
time — but the last run also fired at 08:37, not 03:40, which is consistent with that. **Whatever
the cause, there is currently a day of dossiers and a day of ledger with exactly one copy.** Gap D2.

**(b) The database object name lags the ledger object name.**

On the 2026-08-13 run: `ledger=...2026-08-13... db=...2026-08-11...`.
On the 2026-08-17 run: `ledger=...2026-08-17... db=...2026-08-16...`.

The mechanism is in the code. `backup_store.py:439-442`:

```python
day = datetime.datetime.fromtimestamp(
    DB.stat().st_mtime, datetime.timezone.utc
).strftime("%Y-%m-%d")
db_key = f"{DB_PREFIX}{DB.stem}-{day}.db.gz"
```

**The object is named after the database file's mtime.** In WAL mode, writes go to `prospector.db-wal`
and the main `.db` file's mtime only advances at checkpoint. So the key can name a day-old date
while the content is current. The content is fine — the risk is that a restore picks the wrong
object believing the name, and that two runs on different days can collide onto one key and
overwrite each other.

**Fix: name the object after the run's own date, not the file's mtime.** The ledger already does
this correctly by accident, because an append-only file's mtime is always now. One-line change.
Gap D4.

**(c) The backup dies on an orphan.** §6.2.

### 7.5 The restore drill: excellent, and never run

`scripts/restore_drill.py` is the strongest piece of ops engineering in this tree. Its opening
sentence, `:2`: **"R4 — the restore drill. A backup nobody has ever restored is not a backup."**

What it asserts, from `:8-18`:

1. the restored SQLite index opens and passes `PRAGMA integrity_check`;
2. its per-table row counts match the live source, within the concurrent-write window;
3. every dossier in the live source is present in the restore — **by membership, not by count**,
   since a supplied backup payload is cumulative and keeps what the source deleted;
4. a random sample of index rows resolves to a restored file that parses as JSON and carries the
   `candidate_id` the row claims;
5. index and tree agree: every non-tombstoned row has a file, and orphan files are counted.

**Assertion 5 is the check that would have caught §6.1.**

It is read-only with respect to production (`:21-27`): the live store is opened
`file:...?mode=ro` for two independent reasons — the daemon is writing concurrently and must not be
locked out, and a probe that can mutate the thing it probes is worse than no probe. `_guard_dest()`
refuses any destination inside `store/` or `storage/`.

It handles concurrency rather than wishing it away (`:29-35`): the source is censused **before and
after** the snapshot, and the restored count must land inside that window. When nothing wrote,
before == after and the assertion is exact equality. When something did, **the drill says so instead
of silently widening its own tolerance.**

It needs zero network and zero LLM calls (`:52-54`), deliberately: "a drill that needs the network
cannot run when the network is the thing that broke."

**And it has never been run.**

```
grep -c "RESTORE_DRILL" store/backup.log   →   0
ls -l store/*drill*                        →   (nothing)
rg -l "restore_drill" store/ ops/          →   (nothing)
```

No receipt on disk, no launchd job, no line in any log. **The restore procedure is therefore
untested. The restore capability is a hypothesis.** Gap D2.

### 7.6 The restore procedure, as written

```bash
# Full restore from R2 into a directory you name
.venv/bin/python scripts/backup_store.py --restore /path/to/recovery

# Prove the remote matches local, touching nothing
.venv/bin/python scripts/backup_store.py --verify-only

# Prove a restore actually reconstitutes a working store
.venv/bin/python scripts/restore_drill.py --keep
.venv/bin/python scripts/restore_drill.py --backup /path/to/recovery
```

`--backup DIR` accepts what a real recovery hands you: a directory holding `prospector.db` and/or a
`dossiers/` subdirectory, or a flat pile of `*.json` — which is exactly the shape
`backup_store.py --restore DIR` produces (`restore_drill.py:44-47`).

**Run the drill. It costs nothing, it needs no network, and it converts a belief into a receipt.**

---

## 8. `PROSPECTOR_STORE_DIR`, `store_root()`, and the `__file__` trap

### 8.1 The one resolver

`prospector/config.py:15-31`:

```python
def store_root() -> Path:
    override = os.environ.get("PROSPECTOR_STORE_DIR", "").strip()
    return Path(override) if override else REPO_ROOT / "store"
```

The docstring is the incident report:

> A constant anchored to `__file__` instead resolves to the store inside whichever checkout the code
> was loaded FROM, which ties the location of the state to the location of the code.
>
> That is not theoretical. On 2026-08-17 production moved off the shared developer checkout onto a
> dedicated one pinned to origin/main, with PROSPECTOR_STORE_DIR set so state would stay put. The
> provider health marks, the retrieval cache and the scheduler audit trail moved with the code
> anyway, because each was a `__file__` constant. **Live state was split across two directories for
> 20 minutes: the ledger in one, the dead-provider marks in the other.**

**Why that specific split is dangerous:** the health file records which brains are benched. A daemon
writing one copy while a probe reads another can never see a provider recover.

### 8.2 The four constants that had the trap, and their fixes

| Constant | File:line | Now |
|---|---|---|
| Retrieval cache | `prospector/retrieval.py:46` | `CACHE_DIR = store_root() / "_cache"` |
| Moat health marks | `prospector/health.py:36` | `HEALTH_PATH = store_root() / "provider_health.json"` |
| Non-critical health marks | `prospector/health.py:42` | `NONCRITICAL_HEALTH_PATH = store_root() / "provider_health_noncritical.json"` |
| Scheduler audit trail | `prospector/audit.py:139-142` | `_AUDIT_DIR = Path(os.environ.get("PROSPECTOR_AUDIT_DIR") or store_root() / "scheduler" / "audit")` |

Each carries a comment at the site explaining why. `retrieval.py:44-45`: "the cache belongs to the
store, not to the checkout the code was loaded from." `health.py:34-35`: "a dead-provider mark must
land in the store the rest of the run uses."

`audit.py:133-138` draws the distinction that matters: the `cli_governor` slot root is **deliberately**
cwd- and `__file__`-independent because that ceiling must bind across every checkout on the machine.
The audit log is per-**store** data, so it follows the store. **Same word, two correct answers,
depending on whether the thing is machine-scoped or store-scoped.**

### 8.3 Where the pins are

```
ops/launchd/com.prospector.scheduler.json:5
ops/launchd/com.prospector.consumer.json:5
    "PROSPECTOR_STORE_DIR": "/Users/chidionyema/Documents/code/prospector/store"
```

Both production plists pin the canonical store. `scripts/live_checkout.py:194` reads that value back
out of the plist and `:214` prints a mismatch against the expected path. **The probe checks the pin,
so a drifted plist is visible without reading the plist by hand.**

### 8.4 A second `store_root()` exists

`prospector/paths.py:66-69` defines its own:

```python
def store_root() -> Path:
    """The runtime state root, honouring `PROSPECTOR_STORE_ROOT` then `PROSPECTOR_REPO_ROOT`."""
    override = os.environ.get(STORE_ROOT_ENV)
    return Path(override) if override else repo_root() / "store"
```

**It reads a different environment variable.** `config.store_root()` honours
`PROSPECTOR_STORE_DIR`; `paths.store_root()` honours `PROSPECTOR_STORE_ROOT` (then
`PROSPECTOR_REPO_ROOT`). The production plists set only `PROSPECTOR_STORE_DIR`.

**So any caller of `paths.store_root()` or `paths.store_path()` ignores the production pin and falls
back to `repo_root()/store`.** Production runs from
`/Users/chidionyema/Documents/code/prospector-live`, so `paths.store_root()` resolves there to
`prospector-live/store`. That is **not** the canonical store.

This is the 2026-08-17 trap with a different variable name. It has not fired because nothing on the
production path calls it — `rg -n "from .paths import|paths.store_path" prospector/` is the check
that would confirm the blast radius. **Treat this as a live landmine until that check is run.**
Gap D7.

### 8.5 Three `__file__`-derived paths remain

```
rg -n "Path(__file__).*store" --glob '*.py' .
tests/unit/test_console_tools_run.py:141
tests/unit/test_console_tools_run.py:326
tools/meta_shape_monitor.py:314
```

The two test hits resolve to `store_platform/` source, not to `store/`, and are fine.
**`tools/meta_shape_monitor.py:314` is not:**

```python
db = str(Path(__file__).resolve().parent.parent / "store" / "prospector.db")
```

That is the exact pattern the incident banned. Run from the live checkout it opens
`prospector-live/store/prospector.db`, which does not exist. It is a tool rather than a daemon, so
the blast radius is a wrong report rather than split state — but it should be `config.store_root() /
"prospector.db"`. One-line fix. Gap D7.

---

## 9. Growth, projected from measurement

| Component | Now | Rate | One year |
|---|---|---|---|
| `store/prospector.jsonl` | 258 M | **4.19 MB/day** | **1.53 GB** |
| `store/dossiers/` | 190 M | **3.2 MB/day** (69 KB × 45.9 rows/day) | **1.15 GB** |
| `store/_cache/` | 172 M | not dated — see below | — |
| `store/scheduler/` | 54 M | not measured separately | — |
| `store/prospector.db` | 2.6 M | 45.9 rows/day, ~870 B/row | ~14 MB |
| **Total `store/`** | **691 M** | **~10.6 MB/day** | **~3.9 GB** |

Method: total store size divided by the ledger's own 64.55-day span. That understates the daily rate
slightly, because some of the 691 MB predates 2026-06-15 — treat 10.6 MB/day as a floor.

**`store/_cache/` is the one I cannot project.** 33,845 files, 172 MB, average 5.3 KB. There is no
date range on the directory as a whole and no eviction visible in `retrieval.py`. The check:
`find store/_cache -newermt '2026-08-11' | wc -l` gives the last week's additions, and
`rg -n "ttl|TTL|max_age|evict" prospector/retrieval.py` says whether anything ever removes one.
**HYPOTHESIS: nothing evicts it.** The cache entry format (`retrieval.py:48-51`) is a v2 envelope
`{"v", "fetched_at", "sources"}` so that **TTL is judged on the recorded fetch time rather than on
mtime alone** — that is a staleness check on read, not a deletion. A cache that is never deleted
from grows without bound.

**Disk is not the binding constraint. Read time is.** The spend guard already measured 108s on a
157 MB ledger (§3.7). At 1.53 GB the same scan is around 17 minutes.

---

## 10. Migrations: how a schema change is made here

### 10.1 The engine store — by hand

There is no migration framework. `store.py::_init_db` creates the table if absent, and every column
after the eighth arrived via `ALTER TABLE ADD COLUMN` (visible in the schema text, §2.1).

The procedure that has actually been used, evidenced by the three `.bak` files:

1. Copy the database aside: `cp store/prospector.db store/prospector.db.pre-<change>.bak`.
2. Add the column with a `DEFAULT` or as nullable.
3. Backfill in Python.
4. Add an index if it will be filtered on.

**Constraints SQLite imposes that shape this:**

- `ADD COLUMN` cannot add a `NOT NULL` column without a default, cannot add a `PRIMARY KEY` or
  `UNIQUE` column, and cannot add a generated `STORED` column.
- Dropping or renaming a column requires a full table rewrite on older SQLite. The rewrite pattern
  is create-new, copy, drop-old, rename — and it holds a write lock for the whole operation, which
  will time out a running daemon.
- **A migration must not run while the daemon is running.** `store/scheduler/PAUSE` is the correct
  way to stop it first.

**What would break a migration today:** the 189 orphan rows (§6.1). Any migration that iterates rows
and touches their files hits the same `FileNotFoundError` that killed the backup.

### 10.2 The store API — EF Core

`store_platform/src/Store.Catalog/Migrations/` holds versioned migrations applied on startup. That
side has a real framework, a model snapshot, and generated up/down SQL. It is the better of the two
and the engine store would benefit from something equivalent — though at 2,995 rows and one table,
a framework would be more machinery than the problem needs.

---

## 11. Invariants

| # | Invariant | Enforced by | What breaks when it goes |
|---|---|---|---|
| D-I1 | One store, resolved one way | `config.store_root()` | State splits across checkouts; a benched provider never recovers (2026-08-17) |
| D-I2 | Moat and non-critical health marks are separate files | `health.py:36,42` | A DeepSeek outage blinds the moat |
| D-I3 | JSONL is appended with a single `O_APPEND` write, never tmp+rename | `jsonl_atomic.py` | Concurrent writers silently delete each other's lines |
| D-I4 | A short JSONL write is not retried | `jsonl_atomic.py:36-42` | One torn record becomes two corrupt ones |
| D-I5 | `_connect` closes the connection | `store.py:103,157` | fd exhaustion at 256; the daemon stops in four seconds |
| D-I6 | `journal_mode` is read before it is set | `store.py:146` | `database is locked` at import under xdist |
| D-I7 | The index is a superset of the tree, never a subset | tombstone column | An unindexed dossier is invisible to every query |
| D-I8 | A missing dossier is labelled, not silently absent | `tombstone` | Silent data loss |
| D-I9 | The spend ledger is read by exactly one reader | `ops/spend.py:9`, `guard.py` | Hand-parsed sums disagree with the guard; the cap is unenforceable |
| D-I10 | A backup that does nothing must fail loudly | `backup_store.py:19-26` | You stop looking |
| D-I11 | The restore drill never writes inside `store/` | `restore_drill.py::_guard_dest` | A probe corrupts what it probes |
| D-I12 | The drill opens production `mode=ro` | `restore_drill.py:21-24` | It locks out the daemon it is measuring |

---

## 12. Gaps and debt

| # | Gap | Evidence | Fix | Cost |
|---|---|---|---|---|
| **D1** | **The ledger has no rotation.** 258 MB, 907,977 lines, growing 4.19 MB/day. The spend guard scans all of it; it measured 108s at 157 MB | §3.7, §3.8, `guard.py:250,447` | Roll daily, keep 30 days uncompressed, gzip the rest. The guard only ever needs today's rows | **1 day** |
| **D2** | **The restore drill has never run**, and no backup has run in 28 hours | §7.4a, §7.5 | Add a launchd job for the drill, weekly. It needs no network. Then investigate the missed 03:40 slot | **2 hours** for the job; the drill itself is written |
| **D3** | **189 index rows point at files that do not exist**, and one crashed the backup | §6.1, §6.2 | A reconcile script: for each `tombstone != ''`, null the `path`. For `quarantined_ungrounded`, repoint at the subdirectory. Make the backup skip tombstoned rows | **Half a day** |
| **D4** | **Backup object names come from the database file's mtime**, which in WAL mode lags | §7.4b, `backup_store.py:439-442` | Name from the run's own UTC date | **10 minutes** |
| **D5** | **70,707 ERROR and 964 CRITICAL lines in the ledger, unread** | §3.3 | Tabulate the top error messages, fix the top three, then alarm on the rest | **1 day** to triage |
| **D6** | **617 ledger lines carry `phase: "testing"`** — pytest has written to production state | §3.4, `jsonl_atomic.py` closing note | A conftest fixture that fails any test whose store path resolves outside `tmp_path` | **Half a day** |
| **D7** | **A second `store_root()` reads a different env var** (`paths.py:66`), and `tools/meta_shape_monitor.py:314` still derives the db path from `__file__` | §8.4, §8.5 | Make `paths.store_root()` delegate to `config.store_root()`; fix the one tool | **2 hours** |
| **D8** | **Ten one-shot `.log` files and three hand-made `.bak` snapshots sit in the durable store** and are backed up daily | §1.5, §1.6 | Move scratch to `store/_scratch/`, exclude it from the backup, delete the `.bak` trio | **1 hour** |
| **D9** | **`store/catalog.sqlite3` is a zero-byte file no code references** | §1.2 | Delete it | **1 minute** |
| **D10** | **`store/_cache/` has no eviction.** 33,845 files, 172 MB, and the TTL is a read-time staleness check, not a deletion | §9 | An LRU sweep by `fetched_at` with a size cap | **Half a day** |
| **D11** | **`dossiers.path` is absolute**, so 2,995 rows are wrong after any move or restore | §6.3 | Store store-relative, resolve on read | **2 hours**, plus a backfill |
| **D12** | **The engine store has no migration framework** and no forward/back scripts | §10.1 | A `store/migrations/NNN_*.py` convention with a `schema_version` row. Only worth it at the next schema change | **1 day**, deferrable |

**Order: D4 (10 min), D9 (1 min), D2 (2 h), D3 (half a day), D1 (1 day).** D4 and D9 are free. D2
turns the restore from a belief into a receipt. D3 unblocks the backup. D1 is the one with a
deadline attached, because the guard's scan time grows with the file.

---

## 13. How to change any of this safely

1. **Stop the daemon before any schema change.** `store/scheduler/PAUSE` halts the whole tick,
   generation and drain together. A migration holding a write lock against a running daemon will
   time out one or the other.
2. **Snapshot before, with `.backup`, not `cp`.** `sqlite3 store/prospector.db ".backup
   store/prospector.db.pre-<change>.bak"` captures the WAL. `cp` does not.
3. **`ADD COLUMN` nullable or with a `DEFAULT`, then backfill.** SQLite will not let you do
   otherwise without a table rewrite.
4. **Never write a store path derived from `__file__`.** `config.store_root()` is the one resolver.
   If you need a path at module level, call it there.
5. **Never append to a JSONL trail by hand.** Use `prospector.jsonl_atomic.append_jsonl`. Every
   other method deletes concurrent writers' lines.
6. **Never sum the spend ledger by hand.** `scheduler/guard.py` is the only reader
   (`ops/spend.py:9`).
7. **Never open the store database without the `_connect` contextmanager.** A bare `with conn:`
   leaks two descriptors per call.
8. **Run the restore drill after any change to the backup or the schema.** It is read-only, needs no
   network, and it is the only thing that checks index and tree agree.
9. **A new column that will be filtered on needs an index.** The table is small now; the ledger
   was small once too.

---

## 14. Where to look next

- [security.md](security.md) — who can reach this data, and the secret inventory.
- [legal-privacy.md](legal-privacy.md) — which of these bytes are personal data, and the retention
  gap.
- [sre-on-call.md](sre-on-call.md) — the alarms that fire when disk or the daemon goes.
- [ops.md](ops.md) — the console buttons that touch the store.
- [../ESTATE_MAP.md](../ESTATE_MAP.md) — the factual spine.

### Commands that answer a data question live

```bash
# Where is the store, really?
python3 -c "from prospector.config import store_root; print(store_root())"

# Total, and the big four
du -sh store && du -sh store/prospector.jsonl store/dossiers store/_cache store/scheduler

# Index health in one query
sqlite3 store/prospector.db "
  SELECT decision, COUNT(*) FROM dossiers GROUP BY 1;
  SELECT tombstone, COUNT(*) FROM dossiers GROUP BY 1;
  SELECT retrieval_degraded, COUNT(*) FROM dossiers GROUP BY 1;"

# Orphans, both directions
python3 - <<'PY'
import sqlite3, glob, os
c = sqlite3.connect("file:store/prospector.db?mode=ro", uri=True)
ids = {r[0] for r in c.execute("SELECT candidate_id FROM dossiers")}
fids = {os.path.basename(f).split(".")[0]
        for f in glob.glob("store/dossiers/*.kill.json") + glob.glob("store/dossiers/*.pass.json")}
print("index", len(ids), "files", len(fids),
      "unindexed", len(fids - ids), "no-file", len(ids - fids))
PY

# Ledger: size, span, error rate
wc -l store/prospector.jsonl && ls -l store/prospector.jsonl
head -1 store/prospector.jsonl | cut -c1-80 && tail -1 store/prospector.jsonl | cut -c1-80
rg -o '"level": ?"[A-Z]+"' store/prospector.jsonl | sort | uniq -c

# Everything that happened to one candidate
rg '"candidate_id": ?"<id>"' store/prospector.jsonl

# Is the backup current? Has the drill ever run?
ls -l store/backup.log && tail -3 store/backup.log
grep -c RESTORE_DRILL store/backup.log

# Prove a restore works (read-only, no network)
.venv/bin/python scripts/restore_drill.py --keep
```
