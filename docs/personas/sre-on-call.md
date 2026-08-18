# The platform for SRE / on-call

It is red. What is broken, how much does it matter, and what do you actually do.

## Triage in one line

**Making can stop for a day and nobody notices. Selling cannot stop for a minute.**

| Symptom | Severity | Why |
|---|---|---|
| `mumchimp.com` down | **P0** | Nobody can buy |
| `api.mumchimp.com/catalog` down | **P0** | Storefront is empty; checkout dead |
| Checkout or webhook failing | **P0** | Money taken, nothing delivered |
| Engine not generating | **P2** | Backlog grows. No customer sees it |
| Ops console down | **P2** | You are blind, but nothing is broken |
| Hermes down | **P3** | Operator convenience |
| A brain benched | **P3** | The chain has a fallback; check it is not permanent |

## First command, always

```bash
.venv/bin/python scripts/estate_map.py
```

It prints three states per line: `ok`, `FAIL`, and `?`. **`?` means "could not ask", and that is not
the same as fine.** Collapsing those two is the most common observability bug in this estate.

Then, if the engine is the problem:

```bash
.venv/bin/python scripts/live_checkout.py     # is production running the code you think it is
.venv/bin/python scripts/ops_status.py
```

## The probes that will lie to you at 3am

Memorise this table. Every row has cost someone real time.

| Probe | The lie | What to do instead |
|---|---|---|
| `GET /health` on the store API | **There is no such route.** A 404 comes from a perfectly healthy machine | `GET /catalog`. That is the Fly health check |
| `DEPLOY_RC=0` plus HTTP 200 | Does not prove the deploy carries your change | Grep the built chunk on the machine |
| `fly auth whoami` | Passes on a dead token | Try an actual operation |
| macOS `ps` / `launchctl` probes | Report a false pass | Check for a pid, then check the pid's cwd |
| `cmd 2>&1 \| tail` | Reports **tail's** exit status | Capture the status before any pipe |
| A green CI check | May never have run. `runner_name == ""` | Look at the run, not the badge |
| A launchd job "loaded" | Loaded is not running | `estate_map.py` distinguishes them |
| An estate probe's green fence line | Is not evidence on its own | Read what it measured |
| A staleness section that compares nothing | Reports fresh because it never compared | Check it has two values |

Two more that are specific and have each burned a session:

- **A deploy of `main` silently reverts a hand-deploy.** One fix was live at 09:45 and gone by 10:12.
  If a fix vanished, look for a deploy, not for a bug.
- **Production does not run from the developer checkout.** It runs from
  `/Users/chidionyema/Documents/code/prospector-live`, detached at `origin/main`. On 2026-08-17 the
  daemon was running 17-hour-old code from a branch a session had left behind, and the only way to see
  it was `lsof` on the pid. That is now `scripts/live_checkout.py`.

## The levers you have

**Stop the pipeline.** Three, and they are not interchangeable:

```
store/scheduler/PAUSE               # everything: generation AND the drain
store/scheduler/PAUSE_GENERATION    # generation only; the drain keeps paying down backlog
schedule.backlog_cap                # automatic, self-releasing
```

`PAUSE` is total on purpose — a rail with exceptions is not a rail. But reach for
`PAUSE_GENERATION` first unless you need the drain stopped too, because **stopping the treadmill
also stops the only thing paying it down.** A frozen backlog does not save that cost, it defers it:
every unresolved row still owes a full re-vet.

**Roll production forward.**

```bash
.venv/bin/python scripts/live_checkout.py --update    # rolls to origin/main and restarts
```

It refuses a live checkout with local code changes. That is deliberate: fixes reach production
through a merged pull request, not through an edit on the box.

**Undo a console action.** `prospector.ops.undo` covers everything a `local` tool wrote, and **the
local half only** of an `external` one. A tool that touched Stripe or the live shelf cannot be fully
undone, and the preview says so before you run it.

## Understanding "a brain is down"

Provider failures are classified once, by one shared tested function:

- **Transient** (429, 503, 529, `overloaded_error`) → benched 60s.
- **Permanent** (402, credit balance, spend or usage allowance) → benched 1 hour. Permanent wins ties.

The mark is **half-open**: exactly one caller machine-wide re-probes, so a brain that recovers in 90
seconds is back in 90 seconds. State is in `store/provider_health.json` and
`store/provider_health_noncritical.json`, with lock files beside them.

Two rules that decide what the daemon does about it:

- **Generation is skipped only when EVERY configured verdict brain is benched** — trusted or
  provisional. One live brain of any tier is enough. It logs `moat_blind` and applies an escalating
  5m/10m/20m retry rather than the normal 2h cadence.
- **The drain stays trusted-only.** Re-vetting a provisional row on a provisional brain re-stamps it
  provisional: the row does not move and the money is spent.

## Recovery

State is SQLite and JSONL on volumes — no managed database, nothing to fail over. Recovery is a
restart plus, if needed, a file restore.

- Fly restarts a crashed machine. There is one machine per app except the storefront, which has two.
- `com.prospector.backup` runs on the laptop; the offsite backup can be started from the console.
- Point-in-time `.bak` files sit beside the live databases.
- **WAL and SHM files are part of the database.** Checkpoint or copy them together.
- **`~/Documents` is iCloud-synced with Optimize Storage** and the canonical store lives inside it.
  Files have been evicted under disk pressure. `rsync -a --update` restores without clobbering newer
  local files.

## When you cannot fix it

Two things are outside your reach and should be escalated rather than worked around: a founder
decision (the roster, the caps, no new infrastructure), and anything requiring the un-backed-up
`~/.config/prospector/age-key.txt`.

## What to read next

- [ops.md](ops.md) — the day-to-day version of this.
- [ESTATE_MAP.md](../ESTATE_MAP.md) §10 — the full "probes that lie" table.
- [data-engineer.md](data-engineer.md) — what you are restoring.
