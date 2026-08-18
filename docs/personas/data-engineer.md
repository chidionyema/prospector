# The platform for the data engineer

Where every byte lives, what shape it is, and how you get it back after something goes wrong.

## The one rule that governs all of it

**There is exactly one canonical store**, and it is pinned by an environment variable rather than
inferred:

```
PROSPECTOR_STORE_DIR=/Users/chidionyema/Documents/code/prospector/store
```

That variable is set on both launchd plists. The engine runs on Fly; the canonical store did not
move with it.

The trap this exists to prevent is worth stating plainly, because it cost twenty minutes of split
state on 2026-08-17. **A store path derived from `__file__` follows the CODE, not the store.** Four
constants did exactly that, so provider health marks, the retrieval cache and the scheduler audit
trail were written beside the newly-moved code while the ledger went to the canonical store. A daemon
writing one health file while a probe reads another can never see a provider recover.

`config.store_root()` is the one resolver. Never write `Path(__file__).parent.parent / "store"`.

## The stores, by size and by shape

Measured on the canonical store:

| Path | Shape | Size / count | What it is |
|---|---|---|---|
| `store/prospector.jsonl` | Append-only JSONL | **258 MB** | The ledger. Runs, spend events, timings. The basis of the daily spend cap |
| `store/dossiers/` | One JSON file per verdict | **190 MB, 2931 files** | Every check, confidence, source and ruling provider. `*.kill.json` for kills |
| `store/prospector.db` | SQLite, one table `dossiers` | 2.6 MB, **2995 rows** | The queryable form of the same verdicts |
| `store/listings/` | JSON | 488 KB, 119 files | What was published |
| `store/listings_archive/` | JSON | — | Superseded listings |
| `store/claims/`, `store/citation_archive.json` | JSON | — | Citations archived at vet time, so a source that rots is still auditable |
| `store/scheduler/` | Mixed | — | `PAUSE`, `PAUSE_GENERATION`, alerts, audit trail, consumer logs |
| `store/provider_health*.json` + `.lock` | JSON | — | Which brains are benched, and until when. Two files: trusted and non-critical |
| `store/generation_metrics.jsonl` | JSONL | — | Generation counters |
| `store/run_metrics.db`, `store/self_modifications.db` | SQLite | 28 KB, 24 KB | Run metrics and self-modification log |
| `store/_cache/` | Files | — | Retrieval cache |
| `store/catalog.sqlite3` | — | **0 bytes** | A leftover. Point nothing at it |

Three files on Fly volumes are separate stores and are **not** in the table above:

- `prospector-store-api` on `store_data` (974M) — the sellable catalogue, orders, entitlements. Typed
  metadata columns, not a JSON blob.
- `prospector-hermes` on `hermes_state` (2.9G) — the operator surface's own databases.
- `prospector-engine` on `prospector_store` (20G, 4% used) — the engine's container-local data.

## Formats, and why they are these formats

Nothing here is a managed database, and that is a portability decision rather than an oversight. JSONL
and SQLite are both readable with no server, restorable with a file copy, and moveable to any provider
in one transfer. See [architect.md](architect.md) for the portability contract this serves.

The trade-off is real: a 258 MB JSONL ledger has no index, and every calibration number in
`config.yaml` was derived by hand-replaying dossier files. **The single highest-value data
engineering task available here is aggregating the 2931-file dossier corpus into something
queryable**, because it is the richest dataset in the estate and nothing consumes it in bulk.

## Backup and recovery

- `com.prospector.backup` is a launchd job on the laptop. `store/backup.log` and
  `store/offsite_backup.log` are its records, and the offsite backup can be started from the ops
  console Engine page.
- Point-in-time `.bak` files exist beside the live databases —
  `prospector.db.pre-tombstone-20260806T004905Z.bak`, `provider_health.json.bak-2026-08-17`. They are
  hand-made before risky operations, not scheduled.
- `prospector.ops.undo` snapshots before every console action that writes locally. It covers
  everything a `local` tool writes and **the local half only** of an `external` one.

**Two gaps you should know about.** First, `~/.config/prospector/age-key.txt` has no copy anywhere
off this laptop. Second, `~/Documents` is iCloud-synced with Optimize Storage, and on 2026-08-18 disk
pressure caused eviction of that tree — the canonical store lives inside it. `rsync -a --update`
restores without clobbering newer local files.

## SQLite traps that have bitten here

- **`with sqlite3.connect(...)` does not close the connection.** It manages the transaction only. A
  WAL left checkpointed-but-open is how a database file copy comes out inconsistent.
- WAL and SHM files (`*.db-wal`, `*.db-shm`) are part of the database. Copy them or checkpoint first.
  A `.dockerignore` that excluded them shipped a container with a database missing its recent writes.
- A lock file that cannot be read **is not a free lock**
  (`tests/unit/test_an_unreadable_lock_is_not_a_free_lock.py`).

## Reading it safely

The store is live. Open it read-only:

```bash
.venv/bin/python -c "
import sqlite3
c = sqlite3.connect('file:store/prospector.db?mode=ro', uri=True)
print(c.execute('select count(*) from dossiers').fetchone())
"
```

Never run pytest against the canonical store — the suite writes to `store/` and `storage/`, which is
also why those paths must never be staged wholesale in a worktree.

## What to read next

- [analyst.md](analyst.md) — what the numbers in these files mean.
- [ESTATE_MAP.md](../ESTATE_MAP.md) §6 — the same table with the connective tissue.
- [sre-on-call.md](sre-on-call.md) — recovery under pressure.
