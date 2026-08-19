# Stack audit — 2026-08-19

> Founder, 2026-08-19: "this is a chance to get our stack right / audit everything, dont blow
> it". "opportunity to also simplify, consolidate if opportunity arises". "improve, replace
> with oss". "we have way too many things running doing similar things also". "and problems
> already solved better or clearer or more elegantly or more comprehensively". "dont just
> blind migrate / audit". "dont settle, aim for the best and most reliable tooling". "up to
> date". Scope: "engine, ops, dev tooling, every surface that is touched as part of migration
> and disaster recovery both on running on laptop or fly".
>
> This runs BEFORE any more migration work. `docs/MIGRATION_AND_DR_PROGRAM.md` says what to
> build. This says what to **stop** building, what to delete, and what an existing OSS tool
> already does better than the thing we wrote.

## 0. The headline, before anything else

**The store backup has not run since 2026-08-17 09:38 and nothing alerted.** Measured:
`launchctl list` reports `com.prospector.backup` last exit **78**, and
`store/backup.log` — the job's own `StandardOutPath` — has an mtime of `17 Aug 09:38`, two
days stale. Exit 78 is `EX_CONFIG`: launchd could not spawn the job at all, which is why the
log has no error in it.

Proven, not assumed: `launchctl kickstart gui/501/com.prospector.backup` reproduces exit 78
immediately and writes **nothing** to the log, so the failure is at spawn, before the script
runs. Every binary in the plist exists and executes by hand
(`.venv/bin/python --version` -> `Python 3.14.6`, exit 0). **The cause is not yet proven.**
The leading hypothesis is macOS TCC refusing launchd access under `~/Documents`, but
`com.signalengine.daemon` runs a `~/Documents` venv and holds a live pid, which weakens it.
A second candidate: `.venv/pyvenv.cfg` records `executable = .../python@3.14/3.14.4_1/...`
and only `3.14.6` exists in the Cellar, so the venv is stale in its recorded base even though
`bin/python3.14` resolves through `/usr/local/opt`. The check that settles it is
`log show --predicate 'process == "launchd"' --last 1h | grep com.prospector.backup`.

Three jobs report the same status 78: `com.prospector.backup`,
`com.haworks.continuous-review`, `com.haworks.test-coverage`.

We have 31 tracked launchd jobs, a home-grown receipt wrapper on 12 of them, a watchdog, and
an ops console — and a dead backup still went unnoticed for two days. That is the audit's
thesis in one measurement: **the estate has many bespoke observers and no dead-man's
switch.** More bespoke tooling is not the fix.

## 1. Method

Everything below is a measurement, taken 2026-08-19, not a recollection. The commands:

| Question | Command |
|---|---|
| What is tracked | `git ls-files <dir> \| wc -l` |
| What actually runs | `launchctl list` |
| What each job runs | parse `ops/launchd/*.json` -> `ProgramArguments` |
| What is deployed | `fly apps list` |
| Datastores and size | `find store storage -name '*.db' -o -name '*.jsonl'`, `du -sh store` |
| SQLite usage | `git grep -n sqlite3.connect -- '*.py'` |

## 2. The inventory, measured

| Surface | Count | Note |
|---|---:|---|
| `scripts/` | 53 | 44 Python, 9 shell |
| `tools/` | 136 | of which ~60 are `experiments/` (code + committed receipts JSON) |
| `docs/` (excluding archive) | 173 | 39 named PROGRAM / SPEC / AUDIT / PLAN / BRIEF / REVIEW |
| `specs/` | 47 | a second docs tree |
| `ops/launchd/` | 31 | tracked plist definitions |
| `.github/workflows/` | 9 | |
| `deploy/` | 30 | 3 target adapters, 3 Dockerfiles, 3 fly.toml, 5 loose plists |
| `prospector/ops/` | 22 | the console API |
| `sqlite3.connect` call sites | 86 | **but only ~10 are production**: 6 in `prospector/`, 2 in `tools/`, 2 in `ops/`. 42 of the 86 are in tests |
| `store/` on disk | 691 MB | |

**Runtime, measured from the plists: four different Python interpreters.**
`/usr/local/bin/python3`, `/usr/bin/python3`,
`/usr/local/Cellar/python@3.14/3.14.6/.../Python`, plus two project `.venv`s. There is **no
`.python-version`, no `.tool-versions`, no `mise.toml`, no `uv.lock`, no `flake.nix`** in the
repo. The only dependency declarations are `requirements.txt`, `requirements-local.txt` and
three `package.json`.

**Fly apps: 11.** `prospector-engine`, `prospector-store-api`, `prospector-store-web`,
`prospector-ci`, `prospector-searxng`, `prospector-hermes` (deployed, and no branch describes
it), and five `tie-*` (four suspended, `tie-web` deployed). The founder has ruled the `tie-*`
apps stay.

**The tracked launchd inventory has already drifted from the machine.** Loaded on the laptop
but absent from `ops/launchd/`: `com.prospector-control.failover-watch`,
`com.prospector-control.receipt-bridge`, `com.prospector-control.standby-sync`,
`com.prospector.log-rotation`, `com.prospector.process-audit`. Tracked but not loaded:
most of the rest. `~/Library/LaunchAgents/` also holds two `.bak-20260807` files and one
`.RETIRED-2026-08-18`.

Only **one of four** GitHub Actions runner agents is loaded (`mumchimp-mac-4`), and CI runs
on `prospector-ci` on Fly. Three tracked runner plists describe nothing.

## 3. Duplication clusters, and the verdict on each

The rule applied: **replace a cluster of our scripts with an OSS tool only where the tool is
more reliable than what we wrote, not merely more fashionable.** Where our script encodes
estate-specific knowledge that no general tool has, it stays and the OSS tool takes the
generic half.

### C1 — "What is running / is it healthy?" — 9 scripts, 4 docs, 1 wrapper

`estate_census.py`, `estate_map.py`, `process_audit.py`, `ops_status.py`, `ops_state.py`,
`blocker_probe.py`, `live_checkout.py`, `session_check.py`, `worktree_census.py`, plus
`~/.hermes/scripts/verify_estate.sh` and `launchd_receipt.py`. Docs: `ESTATE_MAP.md`,
`PROCESS_INVENTORY.md`, `ESTATE_CONTINUITY_PLAN.md`, `RELIABILITY_ARCHITECTURE.md`.

**Verdict: split the cluster in two, and delete the half a tool does better.**

- *Liveness of scheduled jobs* -> **Healthchecks** (self-hosted, AGPL). Every job pings a URL
  on success; the server alerts when a ping is late. This is precisely the failure that beat
  us today: heartbeat monitors catch jobs that slip away quietly, and external probes do not.
  Healthchecks supports cron and systemd `OnCalendar` schedules with timezones, and records
  job duration, exit code and captured output — which is what `launchd_receipt.py`
  reimplements, worse, with no alerting.
  ([Pi Stack 2026](https://www.pistack.xyz/posts/self-hosted-cron-job-monitoring-healthchecks-uptime-kuma-prometheus-guide-2026/),
  [SelfHostPicks](https://selfhostpicks.com/uptime-kuma-vs-gatus-vs-healthchecks/))
- *Endpoint reachability* -> **Gatus** (config-as-code, one Go binary, endpoints and
  conditions in a YAML file in version control). Preferred over Uptime Kuma here precisely
  because Uptime Kuma's config is click-through state in its own DB — the opposite of
  everything this programme is for.
  ([SelfHostPicks](https://selfhostpicks.com/uptime-kuma-vs-gatus-vs-healthchecks/),
  [futurion.blog](https://futurion.blog/self-hosting-uptime-kuma-vs-healthchecks-io-honest-trade-offs-for-solo-builders/))
- *Estate-specific verdicts* (is the live checkout on `origin/main`, is the moat blind, is a
  pack stranded) -> **stays ours.** No tool knows these.

**Delete after cutover:** `launchd_receipt.py`, `ops_state.py` or `ops_status.py` (one of the
two), and the `ESTATE_MAP` / `PROCESS_INVENTORY` / `ESTATE_CONTINUITY_PLAN` overlap collapses
to one generated page.

### C2 — Scheduling: 31 launchd jobs, laptop-only, undeclared

launchd is the single biggest portability blocker in the estate: it is macOS-only, so **every
one of these 31 jobs has to be rewritten to move machines**, and today the tracked copies have
already drifted from the installed ones.

**Verdict: one scheduler, declared in YAML, that runs the same on the laptop, on Fly and on
any Linux box — Dagu.** One binary, built-in web UI, no external database or message broker,
runs on Linux/macOS, and it schedules "the commands you already run" rather than demanding
they be rewritten as tasks. That last property is why it beats the alternatives here: our jobs
are scripts, and Dagu adds dependencies between jobs, retries, per-step logs and run history
without touching them. ([dagu.sh/compare](https://dagu.sh/compare),
[github.com/dagucloud/dagu](https://github.com/dagucloud/dagu))

Rejected, with the reason:
- **Temporal** — durable, mission-critical *workflow* orchestration with stateful
  long-running workflows. Right tool for a different problem; it wants code written against
  its SDK, and it brings a server plus a database.
  ([Kestra 2026](https://kestra.io/resources/infrastructure/temporal-alternatives))
- **Windmill** — a developer platform for internal tools and UIs on top of scripts. Broader
  than we need, and its value is the UI builder we will not use.
  ([PkgPulse 2026](https://www.pkgpulse.com/guides/temporal-vs-restate-vs-windmill-durable-workflow-2026))
- **Cronicle** — multi-server scheduler with a web UI; viable, but heavier than Dagu with no
  advantage at this size. ([alternativeto](https://alternativeto.net/software/temporal))
- **Plain cron / systemd timers** — portable to Linux but not to macOS, and give us no run
  history, which is half of what we keep rebuilding by hand.

Pairing: Dagu schedules, **Healthchecks watches**. A scheduler that reports its own health is
the shape that failed today.

### C3 — Backup and restore: 4 scripts, 3 launchd jobs, 1 broken

`backup_store.py`, `restore_drill.py`, `store_migrate.py`, `store_audit.py`;
`com.prospector.backup`, `com.prospector.offsite-backup`, `ai.hermes.submodule-backup`.

The current design is a nightly full sync to R2 with a sampled verify — and it has three
measured defects: it is **dead since 17 Aug**; it hit a **torn snapshot**
(`FileNotFoundError` on `store/dossiers/d0dc386eb8f7934f.defer.json` inside `_md5`, i.e. a
dossier deleted mid-run); and its RPO is **24 hours**.

**Verdict: keep `restore_drill.py` — proving a restore is the part no tool does for you — and
replace the copying half.**

- SQLite -> **Litestream** (Apache 2.0). It streams the WAL to S3-compatible storage
  continuously, taking RPO from 24 hours to seconds at 1–3% CPU, and it is explicitly a
  *disaster-recovery* tool rather than a replication one, which is exactly our need.
  ([litestream.io](https://litestream.io/alternatives/),
  [onidel 2025](https://onidel.com/blog/sqlite-replication-vps-2025))
- Dossiers, ledger, repo bundles -> **restic**: content-addressed, deduplicated, encrypted
  snapshots. Its snapshot model also removes the torn-snapshot class, which our hand-rolled
  walk-and-md5 loop cannot.
- **Not LiteFS, not rqlite.** LiteFS is for transparent multi-region distribution and rqlite
  for true HA clustering; both solve availability, and our problem is durability on one
  writer. rqlite additionally cannot do transactions or non-deterministic functions.
  ([rqlite FAQ](https://rqlite.io/docs/faq/), [litestream.io](https://litestream.io/alternatives/))

### C4 — CI and local gates: 9 scripts

`ci-gate.sh`, `ci_local.py`, `popdd_verify.py`, `test_impacted.py`, `load_gate.py`,
`verify_engine_change.sh`, `prove_test_fails.py`, `ci_capacity.py`, `warm_ci_uv_cache.sh`.

**Verdict: consolidate to two, keep them ours.** `popdd_verify.py` is the gate; everything
else is either a wrapper around it or a wrapper around pytest. `prove_test_fails.py` earns its
place (it is the meta-test that a gate can fail — S1). The rest fold in or go. No OSS tool
replaces this: the gate encodes our lanes and our repo-wide ruff rule.

### C5 — Branch and worktree hygiene: 7 scripts

`branch_backlog.py`, `prune_branches.py`, `worktree_census.py`, `worktree_gc.py`,
`guard_dead_branch_push.py`, `guard_protected_deletions.py`, `setup_worktree.sh`.

**Verdict: ours, but collapse to two** — `setup_worktree.sh` (load-bearing, documented in
CLAUDE.md) and one `worktree.py` with `census` / `gc` / `prune` subcommands. `prune_branches.py`
already deleted six git-tracked files once; a single reviewed code path is safer than four.

### C6 — One-shot backfills: 12 scripts, permanently resident

`tools/backfill_*` (9) plus `scripts/backfill_*` (3). Each existed to run once.

**Verdict: delete after confirming each has run.** They are read as live tooling by anyone
auditing the repo, and they inflate every "what does this estate do" answer.

### C7 — `tools/experiments/`: ~60 files including committed receipt JSON

**Verdict: move wholesale to `docs/archive/experiments/` or delete.** The findings that
mattered are already in memory files and programme docs. Committed `*_receipts.json` next to
the script that produced them is a results archive wearing a source tree's clothes.

### C8 — Docs: 173 live files, 39 of them programmes

Twelve cover overlapping ground: `ESTATE_MAP`, `ESTATE_CONTINUITY_PLAN`, `ESTATE_QUIRKS`,
`PROCESS_INVENTORY`, `RELIABILITY_ARCHITECTURE`, `DECOUPLING_PROGRAM`,
`ENGINE_MIGRATION_PROGRAM`, `ENGINE_RELIABILITY_PROGRAM`, `MIGRATION_AND_DR_PROGRAM`,
`INCIDENT_PROCESS`, `PLATFORM_MANIFESTO`, plus three dated `NEXT_MOVE_*.md`.

**Verdict: decisions become ADRs; status becomes generated.** `docs/decisions/0001-*.md`
already exists and is the right home — one decision per file, immutable, superseded rather
than edited. Anything that states *current state* (what runs, what is deployed, what is
backed up) stops being prose and becomes a generated page, because prose state drifts. The
dated `NEXT_MOVE_*` files archive.

### C9 — Estate inventory (M1)

**Verdict: do not write one.** Use **Steampipe** to query live infrastructure as SQL
("what does the infrastructure look like right now?"), and **CloudQuery** only if we later
need persisted history and drift ("what changed, who is out of policy?"). Steampipe is the
right half today: it needs no storage and answers the question M1 actually asks.
([CloudQuery: Steampipe vs CloudQuery](https://www.cloudquery.io/blog/steampipe-vs-cloudquery),
[open source asset inventory 2026](https://www.cloudquery.io/learning-center/open-source-asset-inventory))

### C10 — Toolchain and machine bootstrap (M2)

Four Python interpreters, no version pin, no lockfile. A new machine cannot be reproduced.

**Verdict: `mise` for the toolchain, `uv` for the Python lock.** `mise bootstrap` sets up
users, OS packages, services, Docker Compose projects, git repos, dotfiles, macOS defaults and
LaunchAgents in one command; Nix flakes give stricter parity but a much larger adoption cost.
([mise.jdx.dev/bootstrap](https://mise.jdx.dev/bootstrap.html))

### C11 — Container process supervision

`deploy/engine/supervisord.conf` runs several daemons in one container.

**Verdict: replace supervisord with s6-overlay.** supervisord keeps running when a supervised
process exits, so the container stays "up" with a dead daemon inside — the same silent-death
class as the backup. s6-overlay stops the container when a supervised process exits, which is
what makes the platform's restart policy work.
([ahmet.im](https://ahmet.im/blog/minimal-init-process-for-containers/),
[tonysm.com](https://www.tonysm.com/multiprocess-containers-with-s6-overlay/))

### C12 — Secrets, DNS, IaC, logs, chaos, synthetic checks

Researched previously, unchanged, recorded here so the audit is complete in one place:
**SOPS + age** for secrets in git; **octoDNS** for DNS as code (Python and YAML, matching
`scripts/dns_zone.py` which already exports a committed zone); **OpenTofu** over Terraform
(MPL 2.0, Linux Foundation, native state encryption; Terraform is BSL since Aug 2023);
**Vector** to collect and **Loki** or **OpenObserve** to store logs; **Pumba** for chaos on
containers and **Toxiproxy** for surgical network faults; **Playwright** on a schedule for
the synthetic buy-a-pack proof.

## 4. "Is SQLite even appropriate?"

**Split answer, because there are two different datastores and only one of them is fine.**
Yes for the engine and the research store. **No for the money path** — and the reason is not
size or write rate, it is that SQLite pins the API to one machine, which forbids the
redundancy and the zero-downtime deploys we have already committed to.

Measured on disk today:

| Store | Size | Kind |
|---|---:|---|
| `store/prospector.jsonl` | **258 MB** | append-only JSONL ledger |
| `store/prospector.db` | 2.5 MB | SQLite |
| `store/numeric_citation_shadow/shadow-2026-08.jsonl` | 4.6 MB | JSONL |
| `store/prescheck_shadow/shadow-2026-08.jsonl` | 1.2 MB | JSONL |
| `store/scheduler/ticks.jsonl` | 1.8 MB | JSONL |
| `store/run_metrics.db` | 28 KB | SQLite |
| `store/self_modifications.db` | 24 KB | SQLite |
| `store/catalog.sqlite3` | **0 B** | SQLite, empty — dead file |
| ~13 more `*.jsonl` | 57 KB–469 KB | JSONL |

**The SQLite verdict.** The published limit on SQLite at production scale is concurrency:
unlimited readers, exactly one writer at a time, and WAL lets readers and writers stop
blocking each other without granting concurrent writes — so one busy app process is the real
ceiling. Postgres becomes the right answer above roughly 10,000 writes/second, above ~1 TB, on
network filesystems, or across multiple servers.
([Mako](https://mako.ai/guides/postgresql-vs-sqlite),
[daily.dev](https://daily.dev/blog/sqlite-production-guide-when-how-to-use-beyond-prototyping/),
[goilerplate](https://goilerplate.com/blog/sqlite-vs-postgres-indie-saas))

We are nowhere near any of those. One engine writes; the money fence already forbids a second.
2.5 MB is five orders of magnitude below the size limit. And WAL plus `busy_timeout` is
already set in `prospector/metrics_store.py:37`, `prospector/self_modify.py:44` and
`prospector/store.py:145`. **Moving to Postgres would add a network hop, a second failure
domain and a migration, and buy nothing measurable.**

### 4a. The money path: measured, and the verdict is different

Measured 2026-08-19:

| Fact | Evidence |
|---|---|
| Store.Api persists to SQLite | `Program.cs:26` `?? "Data Source=store.db"`, `:28` `options.UseSqlite(...)`; 9 `UseSqlite` references |
| `prospector-store-api` runs **1 machine** | `fly machines list -a prospector-store-api` |
| on **1 volume, 1 zone** | `vol_4ql6dzwjylqeygnr`, 1 GB, lhr, zone 8169 |
| `prospector-store-web` already runs **2 machines** | stateless, no volume — it scaled; the API cannot follow |
| EF migrations in Store.Api | **0**. Store.Catalog has one `InitialCreate` carrying `Sqlite:Autoincrement` annotations |

Every order, entitlement, identity record and refresh token in the business lives in one
SQLite file, on one volume, attached to one machine, in one zone.

**Three consequences, none of which is about size.**

1. **The API cannot be made redundant.** M12 says "scale the shop front to 2". The web tier
   already is. The API cannot be, because its database is a local file. The datastore choice,
   not a config flag, is what blocks it.
2. **Every API deploy is a gap in taking money.** One machine with an attached volume cannot
   roll: the volume has to move. That contradicts the standing "zero customer downtime"
   constraint.
3. **A zone failure loses orders.** Fly does not replicate between volumes and its own docs
   say a single volume is persistent but not durable — if the drive fails, the data is gone.
   Daily snapshots kept 5 days are a floor, not a strategy.
   ([Fly volumes overview](https://fly.io/docs/volumes/overview/))

**The documented failure mode is ours exactly.** The reported pattern is payment intents
showing succeeded while the order record never reached the database, writes lost to WAL
contention, and overlapping deploys with concurrent SQLite access losing orders despite
successful charges. A well-tuned SQLite app handles 50–100 write transactions per second, and
the recommendation is to migrate for multi-user SaaS that takes payments and mutates state
concurrently. ([ultrathink.art](https://ultrathink.art/blog/sqlite-in-production-lessons),
[RaidFrame 2026](https://raidframe.com/articles/postgres-vs-sqlite-2026))

Litestream, LiteFS and libSQL have removed SQLite's backup, replication and read-scaling
limits — **write concurrency is the one that remains, and it is the one that matters for
payments.** ([RaidFrame 2026](https://raidframe.com/articles/postgres-vs-sqlite-2026))

**Verdict: Postgres for the money path. The target is ONE database, not two.**

Founder challenge, 2026-08-19: "why the insistence on sqlite / what advantage does it give
us?" — and "requires maintaining 2 databases, this is concerning". That is right, and the
first draft of this section was wrong to present "SQLite everywhere else" as a design choice.
It is an interim state, not a target. Running two datastores means two backup paths, two
restore drills, two failure modes and a permanent "which store is this in?" question — which
is the exact duplication this audit exists to kill.

Two corrections to the numbers this document gave, both of which cut toward one database:

- **The migration surface is ~10 production call sites, not 86.** Measured:
  `prospector/` 6 sites in 3 files, `tools/` 2, `ops/` 2. The other 42 are in tests
  (22 files of 355).
- **The engine's data is 99.6% files, not rows.** `store/` is 691 MB, of which
  `prospector.db` is 2.5 MB. Moving those rows to Postgres does not remove a storage
  discipline — the dossiers and the ledger stay on a filesystem either way.

So the two real questions separate cleanly:

| Store | Decision | Why |
|---|---|---|
| Money path (orders, entitlements, identity) | **Postgres, now** | Not about size. One machine, one volume, one zone; the API cannot be made redundant and every deploy is a gap in taking money |
| Engine store (2.5 MB of rows beside 688 MB of files) | **Follow, after the money path is proven on Postgres** | ~10 production call sites. Small, and not what loses orders |

**What SQLite genuinely buys, stated fairly so the trade is visible:** no server to run, patch
or exhaust connections on; 48 test files build a real store from a temp file with no service
in CI (a stated cost constraint here, since CI runs on self-hosted minutes); and `t_pack` in
`deploy/PORTABILITY.md` is a file copy, where Postgres adds a dump and restore step to every
target adapter. Those are real. **They are not worth a second permanent datastore discipline
once Postgres exists anyway** — which is why the engine follows rather than staying behind.

**Sequence, and the reason for it:** move the money path first because it is the one losing
orders; prove Postgres there with a restore drill; then move the engine's 2.5 MB and delete
the second discipline. Doing the engine first would be optimising the store that is not
failing.

- **It does not cost lock-in — it reduces it.** Every provider speaks Postgres and `pg_dump`
  moves it. A managed Postgres is the most portable managed dependency available, and it
  satisfies the no-lock-in constraint better than a file pinned to one Fly volume.
- **The swap is cheap, measured.** Store.Api has **zero** EF migrations; Store.Catalog has one
  `InitialCreate` whose only provider-specific content is `Sqlite:Autoincrement`. EF Core makes
  the provider a configuration change plus regenerated migrations. This is the cheapest it will
  ever be — the cost grows with every order written.
- **Not LiteFS, not rqlite.** LiteFS gives read replicas with a single writer, which does not
  fix deploys or write availability. rqlite cannot do transactions, which is disqualifying for
  an order-plus-entitlement write. ([rqlite FAQ](https://rqlite.io/docs/faq/))
- **Litestream on the money DB is the stopgap, not the fix.** It takes RPO from 24 hours to
  seconds this week. It does not make the API redundant.

**Sequence:** Litestream on both SQLite files now (days, no code change) -> Postgres for
Store.Api (M3, and it makes the money path portable at the same time) -> scale the API to 2.

**What IS wrong, in priority order:**

1. **The 258 MB JSONL ledger.** This is the spend ledger the daily cap is read from. It is
   append-only text with no index, so every cap check is a linear scan of 258 MB, and a torn
   write at the tail has no transaction to roll back. SQLite with WAL is the standard 2026
   answer for exactly this: an event ledger that survives sudden power loss or a process
   crash. ([sqliteforum: event sourcing with SQLite](https://www.sqliteforum.com/p/event-sourcing-with-sqlite))
   **Action: the ledger moves into `prospector.db` as an append-only table; the JSONL becomes
   an export, not the source of truth.** This is the single largest datastore change and it
   makes SQLite *more* central, not less.
2. **`store/catalog.sqlite3` is 0 bytes.** Delete it, or find what expected to write it.
3. **No continuous replication.** One volume, one copy, a 24-hour RPO, and today a 48-hour
   gap. Fly does not replicate between volumes and its own docs are explicit that a single
   volume is persistent but not durable — a drive failure loses the data. Fly takes daily
   snapshots kept 5 days, which is a floor, not a backup strategy.
   ([Fly volumes overview](https://fly.io/docs/volumes/overview/),
   [Fly app availability](https://fly.io/docs/apps/app-availability/))
   **Action: Litestream on every SQLite file.**
4. **~17 JSONL files are ad-hoc schemas with no retention.** The shadow logs already roll
   monthly by filename; the rest do not roll at all.

**DuckDB** is worth exactly one use here and not more: it reads and writes SQLite files
directly, so it is the analysis tool over the ledger, never the store of record.
([DuckDB SQLite extension](https://duckdb.org/docs/lts/core_extensions/sqlite))

## 5. Deployment substrate

The founder chose route (c): Compose substrate plus adapters now, declarative infrastructure
later. `deploy/PORTABILITY.md` already defines eleven adapter verbs with three
implementations (`fly.sh`, `laptop.sh`, `sshdocker.sh`).

**Verdict: keep it. Do not adopt Kamal or Nomad.** Kamal is the strong choice for 1–3 servers
running a single app and would deploy faster, but it replaces an adapter contract we already
have, with a Basecamp-opinionated one that is not more portable. Nomad earns its place at
10–50 services with a mixed workload; we have neither.
([Post-Kubernetes orchestrators 2026](https://www.birjob.com/blog/post-kubernetes-orchestrators-2026),
[Haloy comparison](https://haloy.dev/blog/self-hosted-deployment-tools-compared))

The honest gap is not the orchestrator. It is that **four of eleven Fly apps are the money
path and none of them has a second home that has ever been proven** (M3).

## 6. Defects this audit found, and where each is filed

| # | Defect | Evidence | Status |
|---|---|---|---|
| D1 | Store backup dead since 17 Aug, nothing alerted | `launchctl list` exit 78; `backup.log` mtime 17 Aug 09:38 | P0 — fix now |
| D2 | Torn snapshot during backup | `FileNotFoundError` on a `.defer.json` inside `_md5` | M4 |
| D3 | 5 launchd jobs run on the laptop that no tracked file describes | `launchctl list` vs `ops/launchd/*.json` | M1 |
| D4 | 2 dead `com.haworks.*` jobs still installed, exiting 78 every 6h | the haworks estate was destroyed | delete |
| D5 | 3 of 4 runner plists describe agents that are not loaded; CI runs on Fly | `launchctl list`, `fly apps list` | delete |
| D6 | No toolchain pin anywhere; 4 Python interpreters in the plists | `git ls-files` finds no version file | M2 / C10 |
| D7 | `store/catalog.sqlite3` is 0 bytes | `ls -lh` | delete or explain |
| D8 | `prospector-hermes` is deployed and no branch describes it | `fly apps list` | task #74 |

## 7. The delete list

Nothing here is deleted by this document. Each line is a second, explicit pass, report mode
first, per the standing rule.

- 12 one-shot `backfill_*` scripts, once each is confirmed run
- ~60 files under `tools/experiments/`, to `docs/archive/`
- `~/.hermes/scripts/launchd_receipt.py`, replaced by Healthchecks
- 2 `com.haworks.*` plists and their 2 `.bak-20260807` files
- 3 unloaded GitHub Actions runner plists
- `store/catalog.sqlite3` (0 bytes)
- One of `ops_state.py` / `ops_status.py`
- 5 of the 7 branch/worktree scripts, folded into one
- `NEXT_MOVE_2026-08-14/15/17.md`, to `docs/archive/`

## 8. What this changes about the migration programme

`MIGRATION_AND_DR_PROGRAM.md` proposes twelve gaps to close. This audit does not add a
thirteenth; it says **five of them stop being things we build**:

| Gap | Was | Now |
|---|---|---|
| M1 inventory | write an inventory tool | Steampipe query + generated page |
| M2 bootstrap | write a bootstrap script | `mise bootstrap` + `uv` lock |
| M4 backup proof | fix our sync loop | Litestream + restic; keep `restore_drill.py` |
| M6 drills | five bespoke drills | Dagu schedules them, Healthchecks alerts on silence |
| M10 logs | build shipping | Vector -> Loki/OpenObserve |

M3 (money-path adapter), M7 (chaos), M8 (end-to-end buy), M9 (DNS, shipped), M11
(datastores), M12 (redundancy) stay as written.

## 9. Decisions needed from the founder

1. **Ledger migration.** Move the 258 MB spend ledger from JSONL into `prospector.db`?
   It touches the money rail's daily cap, so it is a founder call, not mine. **OPEN.**
2. **Where Healthchecks and Dagu run.** **DECIDED 2026-08-19: on `prospector-engine`.**
   No new app, no new provider.
3. **Delete passes.** **DECIDED 2026-08-19: delete once each has been confirmed run, and
   update the repo docs in the same pass.** Report mode still runs first.
4. **Postgres for the money path** (section 4a). **DECIDED 2026-08-19: yes.** Founder on
   running orders, entitlements and identity on one SQLite file on one volume: "come on this
   is irresponsible". Tracked as task #93.
5. **One database as the target** (section 4a). Recommendation: yes — the engine follows the
   money path onto Postgres once that is proven, rather than keeping SQLite permanently.
   ~10 production call sites. Founder has stated the concern ("requires maintaining 2
   databases, this is concerning") but has not ruled. **OPEN, and it should be decided after
   Postgres is running and drilled on the money path, not before.**

## 10. Ledger

| Date | What | Evidence |
|---|---|---|
| 2026-08-19 | Audit taken; 12 clusters, 8 defects, 3 decisions | this document |
