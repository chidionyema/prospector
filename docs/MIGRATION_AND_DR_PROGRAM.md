# Platform independence, migration and disaster recovery

**Headline requirement, in the founder's words: platform independence.** Everything below serves it.
A component is platform independent when a committed file describes it, an adapter moves it, a drill
has already moved it, and losing the platform costs a DNS edit rather than a rebuild.

**This document guides the architecture of the project.** It is not a migration checklist that gets
consumed and thrown away. When a design decision and this page disagree, this page wins, and the
decision gets changed or this page gets amended with the reasoning. Two rules follow from that and
bind new work: **nothing may be built that only one platform can run**, and **nothing holds state
that is not a file we can copy**.

Founder directive, 2026-08-18/19:

> *"id prefer you do the full staakc nigration a d disaster revocer autonated progran and include
> hernes and use as test"* · *"we have jobs, scripst littered all oevr this nahine , fly etc ,
> nigration aaccounts for both"* · *"i can get a new nachine checkout and everything setup
> seanlessly"* · *"i can choose to nove fron fly to another priverder nnd get it done seanlessly"* ·
> *"adnin dashboad fully enbled to support this also"* · *"drills drills drills baby"* ·
> *"chaos testing and eend to end tests also"* · *"free/opensoure"* · *"so ineed a full requirenents
> list ad plsn"* · *"everything fron dns, logs, everything, db, when i sya disadter recovers and
> nigration i nnean it"* · *"this si critial , busines dpeendent work"* · *"and redundancy"* ·
> *"and autonated drills"* · *"full ops visibility and adni"* ·
> *"and platforn independence as headline"* · *"to guide architecture of this project"*

**The acceptance bar, set 2026-08-19, verbatim.** This is what "done" means for the whole
programme, and no part of it is currently met:

> *"if i have 30 ninutes to nigrate the wwhole stack, donain, third party deps/ donain , everything
> running in this nachine because i also have a new laptop, so engine, hernes, jobs, and evertything
> on fly to another onpren or cloud provider, i should not epericne ny downtine and get this
> seanlessly done fron ops dashboard and prove and see realtine progress. this is the bar, even
> things like logs, etc nothing beig used can be nissed out, and this has to be resuable for any
> project not just prospector etc, should be able to probe and audit any systen and get this done."*

Eight requirements come out of that sentence — 30 minutes; domain and third-party dependencies move
too; everything on the laptop moves; everything on Fly moves; zero downtime; driven from the ops
dashboard with real-time provable progress; nothing in use is missed, logs included; reusable for
any project, able to probe and audit any system. The scoreboard against each of the eight is in
[`docs/PLATFORM_DIRECTIVES.md`](PLATFORM_DIRECTIVES.md) §1, along with the three measured physical
blockers: a 3600-second DNS TTL on `www.` and `api.` (an hour of cache, so a 30-minute cutover
cannot work today), a money datastore that is a SQLite file copy, and secrets with no restore path.

**A second directive, said twice and now binding on how this document is read.** The laptop is an
emergency backup, not stack infrastructure, and developer workflow is separate from stack
infrastructure. Only the second column of that split — the things a customer or a scheduled job
notices when they stop — is in scope here. Editors, worktrees, local test runs and the session
guards are re-created on a new machine, never migrated.

**Scope is everything, and the founder said so plainly.** DNS, logs, databases, object storage,
payments, CI, secrets, certificates, the laptop's jobs and the Fly apps. Not the engine, not "the
important bits". If losing it would cost money or time, it is in this programme.

This is the requirements list and the plan. It is a tracked programme: append results here, never to
`CLAUDE.md`.

**Siblings, all of which this programme uses rather than replaces.**
[`deploy/PORTABILITY.md`](../deploy/PORTABILITY.md) — the platform contract and the adapter shape.
[`docs/ESTATE_CONTINUITY_PLAN.md`](ESTATE_CONTINUITY_PLAN.md) — the risk register R1–R8 and the
disaster-recovery targets. [`docs/ENGINE_MIGRATION_PROGRAM.md`](ENGINE_MIGRATION_PROGRAM.md) — the
engine's own move, step by step. [`docs/ESTATE_MAP.md`](ESTATE_MAP.md) — what exists and where.
[`docs/PROCESS_INVENTORY.md`](PROCESS_INVENTORY.md) — the laptop's unattended work.
[`docs/RUNBOOKS.md`](RUNBOOKS.md) — the manual procedures this programme has to automate away.
[`docs/PLATFORM_MANIFESTO.md`](PLATFORM_MANIFESTO.md) — the portability targets and the drill
principle. [`docs/BACKLOG.md`](BACKLOG.md) — the ranked P0 list this programme sits beside.
[`docs/STACK_AUDIT.md`](STACK_AUDIT.md) — **the estate measured and the free/OSS verdict per
cluster.** It answers §5 below; read it before proposing any tool.
[`docs/PLATFORM_DIRECTIVES.md`](PLATFORM_DIRECTIVES.md) — **what the founder has already
decided, verbatim, with dates.** Read it before planning; it is where the 30-minute bar lives.

---

## 0. The eight core requirements, and what they are worth in a real failure

Founder, 2026-08-19, verbatim: *"if i have 30 ninutes to nigrate the wwhole stack, donain, third
party deps/ donain , everything running in this nachine because i also have a new laptop, so engine,
hernes, jobs, and evertything on fly to another onpren or cloud provider, i should not epericne ny
downtine and get this seanlessly done fron ops dashboard and prove and see realtine progress. this
is the bar, even things like logs, etc nothing beig used can be nissed out, and this has to be
resuable for any project not just prospector etc, should be able to probe and audit any systen and
get this done."*

Eight requirements are named in that one sentence. They are the bar, restated so each one can be
graded:

| # | Requirement | His words | Status |
|---|---|---|---|
| **B1** | **Completeness** — nothing in use is missed: domain, third-party deps, logs, secrets, data, jobs | "nothing beig used can be nissed out" | **not met** — three inventories that never meet (M1) |
| **B2** | **Thirty minutes**, end to end | "if i have 30 ninutes" | **unproven** — nothing has ever been timed |
| **B3** | **Zero downtime** for the customer | "i should not epericne ny downtine" | **unproven** — no cutover has been run |
| **B4** | **Driven from the ops dashboard**, not a terminal | "fron ops dashboard" | **not met** — no Continuity panel (M5) |
| **B5** | **Provable, real-time progress** | "prove and see realtine progress" | **not met** |
| **B6** | **Destination-agnostic** — any on-prem or cloud provider | "to another onpren or cloud provider" | **partly** — engine has 3 adapters, money path has none (M3) |
| **B7** | **Reusable for any project**, not prospector-shaped | "not just prospector etc" | **not met** — every artefact is prospector-shaped |
| **B8** | **Probe and audit any system** — discover the estate, don't hand-write it | "should be able to probe and audit any systen" | **not met** |

### 0.1 The precondition nobody wrote down: B0

The eight requirements are all about *moving* the estate. Every one of them assumes the estate still
exists to be moved. That assumption is the requirement, and it is not in the list:

> **B0 — the data survives the machine.** A migration plan is a way of *rebuilding* from a copy. If
> the copy is stale or absent, none of B1–B8 can be attempted at any speed.

**B0 is currently failing.** Measured 2026-08-19:

```
store/backup.log      last STORE_BACKUP PASS = ledger/prospector-2026-08-17.jsonl.gz
                      file mtime 2026-08-17 09:38          -> 2 days, no backup
launchctl list        com.prospector.backup  last_exit=78  (EX_CONFIG, dead at spawn)
store/prospector.jsonl  258 MB, mtime 2026-08-18 18:51     -> newer than any backup of it
prospector-live       HEAD debfe1c, 44 commits behind origin/main
                      scripts/process_audit.py MISSING -> com.prospector.process-audit exit 2
fly logs prospector-engine | grep STORE_BACKUP  -> no lines in the retained buffer
```

The last two lines matter together. `deploy/engine/supervisord.conf` on `origin/main` runs
`[program:backup]` and `[program:offsite-backup]` on Fly, so the intent is that Fly covers this. The
Fly log buffer shows nothing, which is a **lead, not proof** — the buffer is short.

**MEASURED 2026-08-19 16:55 UTC, and it reverses the grade above.** Fly HAS taken over. The receipts
are on the volume, written by `receipt.sh`, and they are the data the log buffer had already lost:

```
fly ssh console -a prospector-engine -C 'supervisorctl status'
  backup          RUNNING   uptime 2:57:28
  offsite-backup  RUNNING   uptime 2:57:28
  restore-drill   RUNNING   uptime 2:57:28

/data/store/ops/receipts/backup_store.py.json
  started_at 1787147677  ended_at 1787147740  duration_s 63  exit_code 0   # 13:55:40 UTC today
/data/store/ops/receipts/restore_drill.py.json
  started_at 1787147677  ended_at 1787147695  duration_s 18  exit_code 0   # 13:54:55 UTC today

/data/store/prospector.jsonl   350 MB  mtime Aug 19 16:51   <- canonical, on Fly
store/prospector.jsonl (laptop) 258 MB  mtime Aug 18 18:51   <- a stale COPY
```

**Corrected grade.** B0 is not failing. The backup ran today and exited 0, and the restore drill ran
today and exited 0. My earlier reading — "if the laptop broke today we lose two days of ledger" —
was wrong, and it was wrong because I graded the estate from the laptop's files while the canonical
store had already moved to the Fly volume. The laptop's dead `com.prospector.backup` (exit 78)
guards a stale copy of a store nothing writes to any more, so **task #92 is not P0**; it is a dead
job to unload (task #19), not a data-loss risk.

What is still UNPROVEN under B0, and what M4/M11 must still close:

- **Completeness.** One backup exiting 0 proves the ledger and the dossiers were written to R2. It
  does not name every datastore. Store.Api's SQLite money DB has no line in any receipt. That is
  M11, and it is still the head of the queue.
- **The restore drill's scope.** `restore_drill.py` exits 0 in 18 seconds. Eighteen seconds is not
  a 350 MB ledger restore, so what it actually proves needs reading before it is counted as B0
  evidence. Graded UNPROVEN, not SOUND.
- **The verifier's verdict is worthless, in the loud direction.** `backup_store.py --verify-only`
  on the engine prints `STORE_BACKUP FAIL ... verified=7/8` because it samples the CURRENT local
  dossier set against R2, so any dossier written since the last run reads as missing
  (`d359676bde96b6b5.defer.json`, mtime 16:13, against a backup that ran at 13:55). **A healthy
  three-hour-old backup and a genuinely broken one print the identical FAIL.** That is L11 test 2
  again: an alarm that is always on is an alarm nobody reads. Tracked as task #109. `backup_store`
  is already touched by open PR #420, so the fix waits on that PR rather than racing it.

### 0.2 How the priority reorders if we lost Fly and the laptop today

The build order and the disaster order are different lists, and the difference is the finding. Under
"Fly is gone and the laptop is dead this morning", six of the eight requirements are about doing the
migration *well*. Only two decide whether it can be done at all.

| Rank | What | Why it sits here |
|---|---|---|
| **1** | **B0 — data survives** | Nothing else is attemptable. Restores the ledger, the store DB, the dossiers, the Stripe reconciliation trail. If this fails the business is gone, not delayed. |
| **2** | **B1 — completeness** | You can only restore what something wrote down. The gap that bites is never the database; it is the DNS record, the webhook secret, the API key with no restore path (M2/T10: the SOPS age private key has no documented recovery). |
| **3** | **B6 — destination-agnostic** | You need somewhere to go. The engine can move (3 adapters). **The money path cannot** — it is SQLite on Fly with no adapter (M3), so the shop stops taking money regardless of how fast the engine moves. |
| **4** | **RTO, not B3** | B3 is *zero* downtime. In a real double failure the downtime already happened. The live question becomes "how many hours until a buyer can buy again", which is a different and more honest target than "seamless". |
| **5** | **B2 — thirty minutes** | Becomes a measurement, not a bar. A number nobody has ever clocked cannot be a constraint. |
| **6** | **B5 — provable progress** | Matters once the restore is running, so you know whether to wait or intervene. Not before. |
| **7** | **B4 — from the ops dashboard** | The dashboard is on the dead laptop or the dead platform. In the real incident you are in a terminal. B4 is a requirement for the *routine* migration, not the emergency one. |
| **8** | **B7 / B8 — reusable, auditable** | These pay off on the *next* project. They cost nothing during the incident and save nothing during it. |

**What that reordering changes about what to build next.** The current M-series sequence leads with
M1 (inventory) and M2 (bootstrap). The disaster ordering says the true head of the queue is
**M11 + M4 — name every datastore and prove one restore** — because they are B0, and B0 is failing
today. Nothing above rank 3 is a tooling decision; all of it is proving that a copy exists and comes
back.

**Second and third order effects of accepting this ordering.** Second order: M2's bootstrap work
(mise, uv, SOPS) drops behind restore drills, which delays "new laptop" readiness — acceptable,
because a new laptop with no data to put on it is not readiness. Third order: the ops console
Continuity panel (M5, B4) slips furthest, so for some weeks the migration remains a terminal
procedure. That must be said out loud rather than discovered later, because B4 is one of the
founder's eight and deferring it is a decision, not an oversight.

### 0.3 The immediate consequence

`P0 — com.prospector.backup fails at spawn (launchd exit 78)` is already tracked, and §0.1 shows it
is **not** P0: it guards a store that is no longer canonical. It gets unloaded (task #19), not fixed.

The consequence that survives the correction is about *grading*, not about that job. Both readings
of B0 today came from a status surface rather than from the data behind it — first the laptop's
`backup.log`, which is a stale file the live job no longer writes; then `fly logs`, whose buffer had
already rotated past the successful run. Both said "nothing is happening". The receipts on the
volume said the opposite, and they are the only durable record either job leaves.

**So the programme gains a rule, and M4 gains a deliverable.** Every scheduled job's verdict must be
readable from a durable artefact with a timestamp and an exit code, not from a log tail. `receipt.sh`
already does this and is already installed; nothing surfaces it. M5's Continuity panel reads receipts
or it is decoration. Until then, the command that answers "did the backup run?" is:

```
fly ssh console -a prospector-engine -C 'cat /data/store/ops/receipts/backup_store.py.json'
```

### 0.4 The twelve gaps graded against the eight requirements

The M-series was written before the bar was stated, so it was never checked against it. Doing that
check is the point of this section, and it finds that **two of the eight requirements have no M at
all**, which no amount of progress on M1–M12 would ever close.

| Req | What it demands | M-series coverage | Grade |
|---|---|---|---|
| **B1** | Everything moves — engine, Hermes, jobs, Fly apps, domain, third-party deps, logs | M1 inventory, M9 DNS, M10 logs, M11 datastores | **PARTIAL.** Third-party accounts are not a class in any M: Stripe, Cloudflare R2, GoDaddy, Telegram, GitHub and the model providers each hold credentials, webhooks and state that no inventory names. |
| **B2** | Thirty minutes | none | **NOT COVERED.** No M starts a clock. M6's drills are the only place one could run, and none of them times the whole cutover. A bar nobody has ever measured against is a wish. |
| **B3** | No downtime | M3 money adapter, M12 redundancy | **PARTIAL.** Both are about *being able* to run elsewhere. Neither covers the cutover itself — draining in flight work, running both sides at once, and the DNS TTL that decides how long the old address keeps taking traffic (M9 records two 3600s TTLs, so today the floor is an hour). |
| **B4** | Driven from the ops dashboard | M5 Continuity panel | **COVERED as scope.** Unbuilt, and §0.2 ranks it last for the emergency and first for the routine migration. Both are true; the doc must not pick one and drop the other. |
| **B5** | Prove it, and see progress live | M5 (partly) | **PARTIAL.** M5 shows progress. Nothing defines the proof: what artefact says a step *succeeded*. §0.3 answers it for jobs — a receipt with a timestamp and an exit code — and that answer should be the migration's too. |
| **B6** | Any destination, on-prem or cloud | M3, plus the engine's three existing adapters | **PARTIAL.** The engine can move. The money path cannot, and the managed-container shape has no adapter at all (task #34). |
| **B7** | Reusable on any project, not just prospector | none | **NOT COVERED.** Every one of M1–M12 is written against this estate's paths, app names and jobs. Nothing in the series produces anything a second project could run. |
| **B8** | Probe and audit any system | none | **NOT COVERED.** M1 is a hand-assembled inventory of what we already know we have. B8 asks for a tool that walks an unfamiliar system and reports what it found — the opposite direction, and the harder one. |

**The finding, stated plainly.** M1–M12 is a good plan for moving *prospector*. The founder asked
for something that moves *any* estate and can audit one it has never seen. B7 and B8 are not
refinements of the existing twelve; they are a different deliverable, and pretending otherwise is
how a programme reports 80% complete against a bar it cannot reach.

**What follows from that, and what does not.** It does not follow that we should stop and build a
generic tool first — B0 is still the head of the queue, and a portable framework with no proven
restore behind it protects nothing. What follows is a constraint on *how* M1–M12 get built: every
one of them lands as a script that takes the estate as input rather than hard-coding it, and reads
its target names from a declared file rather than from the code. That is close to free while
writing, and expensive to retrofit afterwards. **M13 and M14 are therefore added below** rather
than pushed to a later phase, and they are graded honestly as UNSTARTED.

- **M13 — the estate is data, not code.** One declared file names every app, host, datastore, DNS
  zone, third-party account and scheduled job. M1's inventory becomes a *reader* of that file, and
  every other M takes its targets from it. Closes B7. **P1, M.**
- **M14 — a prober that can be pointed at an estate it has never seen.** Walks what it is given —
  a Fly org, a host, a repo, a domain — and emits the same shape M13 declares, so an unknown
  system can be audited and then migrated by the same machinery. Closes B8. **P2, L.**

**Second and third order effects.** Second order: making every M script take its targets as input
costs a little on each one and delays none of them materially. Third order: it forces the estate's
own names out of the code and into a file, which is the same change M2's bootstrap and M9's DNS
work already need — so the three converge rather than compete. The risk to state out loud is that
M14 is genuinely large and unproven, and it is the requirement most likely to be quietly dropped;
it is ranked P2 for exactly that reason, not because it is optional.

---

## 1. Why this exists — the measurement that started it

On 2026-08-19 a probe was written to ask one question: *which Fly apps does no committed file
describe?*

```
$ .venv/bin/python scripts/fly_estate_probe.py
Fly apps running: 11  (5 out of scope)
  ok prospector-ci              deploy/runner/fly.toml
  ok prospector-engine          deploy/engine/fly.toml
  XX prospector-hermes          NOTHING IN origin/main DESCRIBES THIS APP
  ok prospector-searxng         deploy/searxng/fly.toml
  ok prospector-store-api       store_platform/deploy/fly/api.fly.toml
  ok prospector-store-web       store_platform/deploy/fly/web.fly.toml
Described but not running:
     prospector-store-api-staging store_platform/deploy/fly/api.staging.fly.toml
exit=1
```

`prospector-hermes` had been running for a day. It emitted no application logs — only SSH-login
lines. All eleven `ai.hermes.*` launchd jobs were still loaded on the laptop. And
`docs/ESTATE_MAP.md:178` asserted Hermes had moved.

The defect is not "someone forgot". It is structural: **each session works in its own worktree and
cannot see the others, so "I created the app" is knowledge that dies when the session ends.** The
same shape produced 13 worktrees holding 179 commits that no remote had (memory
`thirteen-worktrees-held-commits-no-remote-had.md`).

**The governing rule for everything below**, and the bar every requirement is written against:

> A live resource is migrated only when a committed file describes it, a probe says the old copy is
> gone, and a drill has rebuilt it from nothing. Anything short of all three is a claim, not a
> migration.

---

## 2. What already exists — measured, so nothing here gets rebuilt

Read this before proposing to build any of it (memory
`feedback-check-what-exists-before-proposing-to-build-it.md`).

| Capability | What exists on `origin/main` | State |
|---|---|---|
| Platform contract | `deploy/PORTABILITY.md` — eleven verbs, six platform requirements | written, honoured by the engine |
| Adapters | `deploy/targets/{fly,laptop,sshdocker}.sh` | three written; `fly.sh` flyctl shim landed 2026-08-19 (PR #388) |
| Cutover | `deploy/cutover.sh`, `deploy/decommission.sh` | written, **dry-run never proven** |
| Secrets push | `deploy/secrets.sh`, `deploy/secrets.required` | written; `.env` on this laptop is the source of truth |
| Store move | `scripts/store_migrate.py` (+ `verify`) | written; `verify` is the restore proof |
| Compose substrate | `deploy/compose/` | written; the founder's chosen route "c" |
| Offsite backup | `ops/automations/offsite_backup.py`, `ops/config/offsite_backup.yaml` | running, green, **from the laptop** |
| Fly inventory | `scripts/fly_estate_probe.py` (PR #390) | raised 2026-08-19, **not merged**; Fly apps only |  <!-- doc-lint-ok: lands with PR #390 -->
| Laptop inventory | `ops/launchd/*.json`, `scripts/launchd_plists.py`, `scripts/process_audit.py` | declarations exist; not joined to Fly |
| Estate census | `scripts/estate_census.py`, `scripts/estate_map.py`, `scripts/worktree_census.py` | run by hand |
| Production currency | `scripts/live_checkout.py` (+ `--update`) | shipped, a console button |
| Worktree setup | `scripts/setup_worktree.sh` | works for worktrees, **not for a bare machine** |
| Console registry | `prospector/ops/console_api.py` `TOOLS`, drift test | every tool must be registered or CI reds |

**So this programme is mostly joining, proving and scheduling what is already written.** The genuinely
new build is small: a unified inventory, a committed DNS zone, a machine bootstrap, a log shipper, a
storefront adapter, a drill runner, and the chaos and end-to-end suites.

---

## 3. The twelve gaps, stated as what breaks today

Written in `docs/BACKLOG.md` format. Every item has: **Breaks today** with a number or a `file:line`,
a **Story** in the founder's words, **Done when** as a command someone can run, and **Costs** S/M/L.

---

### M1 — One inventory, or none. Today the estate has three lists that never meet. **P0, M**

**Breaks today.** `scripts/fly_estate_probe.py` (PR #390, open) saw 11 Fly apps when it was run.  <!-- doc-lint-ok: lands with PR #390 -->
`ops/launchd/*.json` declares the
laptop's jobs. `.github/workflows/*.yml` declares scheduled CI work. Nothing joins them, so the
question *"what unattended work does this business run, and where?"* has no answer without three
commands and a person to reconcile them. `prospector-hermes` ran undescribed for a day precisely in
the seam. Not covered by any list at all, and each is business-dependent: **DNS records** (GoDaddy),
**databases** (two SQLite files on two mounted volumes), **object storage** (R2 buckets and their
lifecycle rules), **Stripe** webhooks and their endpoints, **log sinks and their retention**, the
TLS certificates Fly issues for both custom domains, cron entries, and GitHub repository secrets and
environments.

**Story.** *"we have jobs, scripst littered all oevr this nahine , fly etc, nigration aaccounts for
both"*.

**Done when.** `.venv/bin/python scripts/estate_inventory.py` prints **every resource the business
depends on**, in one table — name, class, where it runs, the committed file that describes it, how it
is restored, last successful run — and exits non-zero when anything is undescribed. The classes it
must cover, all of them: compute, datastore, object storage, **DNS**, TLS certificate, secret, log
sink, scheduled job, payment integration, CI runner. It is a console button on `/engine`. A test
proves it fails when a resource of each class is added with no describing file.

**Costs.** M. It is a joiner over four existing readers plus two new ones (cron, GitHub schedules).

**Design note.** The inventory reads from **`origin/main`, not the working tree** — the same choice
`fly_estate_probe.py` makes at `described_apps()`. A resource described only by an uncommitted file
is exactly the failure being caught.

---

### M2 — A new machine cannot be brought up. The secrets have no documented restore path. **P0, M**

**Breaks today.** `scripts/setup_worktree.sh` sets up a *worktree* inside an existing checkout. There
is no path from a bare machine to a working one. Worse, `.env` is the declared source of truth for
every secret (`deploy/PORTABILITY.md`, "Secrets held only in the platform's secret store → `.env` on
this laptop stays the source of truth"). It exists on one laptop and inside an encrypted offsite
backup **whose restore has never been performed**. If this machine dies, the recovery of the money
keys is untested.

**Story.** *"i can get a new nachine checkout and everything setup seanlessly"*.

**Done when.** `scripts/bootstrap_machine.sh` takes a bare macOS or Linux machine to: repo cloned,  <!-- doc-lint-ok: this task's own deliverable, so it does not exist yet -->
`.venv` built, `node_modules` present, `.lux/keys/agent.pem` present, hooks decided, secrets restored,
and `.venv/bin/python scripts/popdd_verify.py --staged` passing. It is idempotent. A drill (M6) runs
it in a clean container and the run is the proof, not the script's existence.

**Costs.** M for the script, S for the drill, and the secret-restore path is the hard half.

**Open decision — needs the founder.** Where do secrets live so that a new machine can fetch them
without a human? Candidates in §5. This is the one requirement that cannot be answered by tooling
alone, because it is a trust decision.

---

### M3 — The money path has no adapter. Only the engine can leave Fly. **P0, L**

**Breaks today.** `deploy/targets/` covers the engine. `prospector-store-api` and
`prospector-store-web` — the only two things that take money — are described by
`store_platform/deploy/fly/*.toml` and deployed by a Fly-specific path.
`docs/ESTATE_CONTINUITY_PLAN.md` §6 marks both "not yet" tested. `prospector-searxng` and
`prospector-ci` are also Fly-only.

The asymmetry is backwards: the portable component is the one whose outage nobody notices (the
engine is supply), and the locked-in component is the one whose hour of downtime stops sales.

**Story.** *"i can choose to nove fron fly to another priverder nnd get it done seanlessly"* and
*"sane approach for everything else even storefront needs migration plan away from fly"*.

**Done when.** `deploy/cutover.sh --component storefront --from fly --to sshdocker --dry-run` parses
and reports every step; and a drill actually stands the storefront up on the second target, serves
`/health`, and is torn down. The storefront's data is already one SQLite file, so the move is a copy
plus a DNS edit — the work is writing it down as verbs, not re-architecting.

**Costs.** L. It is the largest single item and it touches the money path, so it goes behind a drill
before it goes near production.

**Fence.** Lower the DNS TTL before any real move. A long TTL turns a 20-minute switch into half a day
of split traffic (`ESTATE_CONTINUITY_PLAN.md` §6).

---

### M4 — Every backup is a hypothesis. Not one has been restored. **P0, M**

**Breaks today.** `ops/automations/offsite_backup.py` reports green — `money-db: 5.8h old`,
`data-protection-keys: 5.8h old`. Nobody has ever restored either. `ESTATE_CONTINUITY_PLAN.md` §4.4
names the drill and calls it quarterly; it has not run. The store API's backup is a **file pull over
`fly ssh sftp`**, which races SQLite writes, so the copy may be torn and nothing would say so.

There is also the order effect (R1): stopping the laptop's launchd jobs after the engine migration
also stops the only backup of the money database, and the migration would look clean.

**Story.** *"think business risks and disaster recovery as well as migration and redundancy"*.

**Done when.** Three things are true and each is a command. (a) The store API snapshot is taken with
`VACUUM INTO` **inside** the container, then shipped, so it cannot be torn. (b)
`scripts/restore_drill.py` restores last night's engine store to a scratch directory and runs
`scripts/store_migrate.py verify` on it, exiting non-zero on any mismatch. (c) The same script
restores the store API's SQLite plus the `/data/keys` data-protection key ring into a throwaway app
and hits `/health`. Restoring the database without the key ring hands every buyer a broken download —
the drill must prove both together.

**Costs.** M. Targets stay as declared: **RPO 1 hour, RTO 30 minutes** for the money path.

---

### M5 — The console cannot drive any of this. **P1, M**

**Breaks today.** The ops console at https://prospector-engine.fly.dev registers tools in
`prospector/ops/console_api.py` `TOOLS`, and the drift test forces registration. Nothing in the
migration or DR path is registered: not `fly_estate_probe.py` beyond the single button added in
PR #390, not the cutover, not a restore drill, not a bootstrap. So the answer to *"is the estate
described?"* or *"did last night's restore drill pass?"* is an SSH session.

`docs/BACKLOG.md` states the rule this violates: **"If answering a question required someone to SSH
into a box, that is a defect, not an answer."**

**Story.** *"adnin dashboad fully enbled to support this also"*.

**Done when.** `/engine` carries a **Continuity** panel showing, live: the inventory verdict (M1), the
age and result of the last restore drill (M4), the last cutover dry-run result (M3), and the last
chaos run (M7). Read-only buttons run without confirmation; anything that moves production is behind
the console's existing danger flag. The panel reads persisted receipts on the store, never re-runs
work to answer a page load (memory `the-answer-was-already-on-disk-as-a-receipt.md`).

**Costs.** M. The registry and the danger flag already exist; this is a screen plus a receipt reader.

---

### M6 — Drills exist as prose. Nothing runs them. **P0, S each, M total**

**Breaks today.** `ESTATE_CONTINUITY_PLAN.md` §4.4 lists three drills and calls them quarterly.
`PLATFORM_MANIFESTO.md` names portability drills. No scheduler runs any of them, no receipt records
one, and no alert fires when one fails. A drill on a calendar that nobody holds is a wish.

**Story.** *"drills drills drills baby"*.

**Done when.** Five drills run on a schedule, write a receipt to the store, and page on failure:

| Drill | What it proves | Cadence | Cost to run |
|---|---|---|---|
| **D1 cold restore** | last night's engine store restores and verifies | nightly | free |
| **D2 money restore** | store API SQLite + key ring restore, `/health` answers | weekly | free (throwaway app, minutes) |
| **D3 escape hatch** | `cutover.sh --from fly --to sshdocker --dry-run` still parses | weekly | free — already wired in `escape-hatch-drill.yml` |
| **D4 bare machine** | `bootstrap_machine.sh` takes a clean container to a passing gate | weekly | free on the self-hosted runners |
| **D5 full cutover** | the engine actually moves to the second target and back | quarterly, announced | one afternoon |

D3 already exists as a workflow and is where the `fly`/`flyctl` defect was caught — evidence that
scheduled drills find real breakage. The rest follow its shape.

**Costs.** S each. D5 is the only one that needs a window.

**Fence.** A drill that cannot measure must fail, never pass quietly. `fly_estate_probe.py::live_apps`
is the pattern: it raises rather than returning an empty list, because *"a probe that passes when it
cannot measure is worse than no probe"*.

---

### M7 — Nothing has ever been broken on purpose. **P1, M**

**Breaks today.** Every failure mode in the risk register is untested. We do not know what happens
when: the store volume is unmounted, R2 rejects a write, Stripe returns 500, the engine container is
killed mid-write to `store/prospector.jsonl`, the Fly region is unreachable, or two engines start at
once (the money fence, EDGE-1). The last of those is a **correctness** fence worth $100/day, and it
has never been attacked.

**Story.** *"chaos testing and eend to end tests also"*.

**Done when.** `tests/chaos/` holds one scenario per named risk, each running against a throwaway
target rather than production, each asserting the *observable* consequence — an alert fired, a fence
refused, a queue drained on recovery — not merely that nothing crashed. The single-container fence
gets its own scenario: start two, assert the second refuses.

**Costs.** M. Start with the three cheapest and highest-value: kill mid-write, double-start, R2
refuses.

---

### M8 — There is no end-to-end proof that a buyer can buy. **P1, M**

**Breaks today.** The money path is `mumchimp.com → api.mumchimp.com → Stripe → R2`. Unit tests cover
pieces of it. `store_platform/src/Store.Tests/` covers the API. Nothing walks the whole path against
the running system, so "the storefront is up" is inferred from `/health`, not from a purchase.

**Story.** *"chaos testing and eend to end tests also"*.

**Done when.** One scripted journey — browse, buy with a Stripe test card, receive the entitlement,
download the file from R2 — runs on a schedule against production using Stripe **test** mode, and
pages on failure. It is the only probe that can say the business works.

**Costs.** M. The journey is short; the care is in never touching a live key.

**Fence.** Test mode only, and the drill must assert it is in test mode before it starts. A drill that
takes a real payment is a worse defect than the one it was written to catch.

---

### M9 — DNS is the one thing with no substitute, and it is entirely manual. **P0, S**

**Breaks today.** `mumchimp.com` and `api.mumchimp.com` resolve through GoDaddy nameservers
(`ns03/ns04.domaincontrol.com`) to Fly's anycast address `66.241.124.37`.
`ESTATE_CONTINUITY_PLAN.md` R5 rates the registrar as *"Everything. DNS is the one thing with no
substitute."* and then leaves it there. There is no committed copy of the zone, so if a record is
deleted or the account is lost, **nobody knows what the records were**. Every exit path in §6 of that
document ends in "repoint DNS", and none of them says to what.

**Story.** *"everything fron dns, logs, everything, db"* · *"and platforn independence as headline"* —
DNS is where platform independence is actually exercised. It is also the cheapest item on this page
and the only one whose loss is unrecoverable.

**Done when.** Four things. (a) The zone is exported to a committed file
(`deploy/dns/mumchimp.com.zone`) and a drill diffs live DNS against it daily, failing on drift.
(b) The TTL on the records a cutover would move is lowered and recorded, so a switch is minutes not
hours. (c) A DNS provider with an API is chosen so the cutover can edit records rather than a person
doing it under pressure. (d) Registrar account recovery — who holds it, what the second factor is —
is written down where someone other than the founder can act on it.

**Costs.** S for (a) and (b), which are the ones that matter this week. (c) is a decision, in §7.

---

### M10 — Logs die with the platform that made them. **P1, M**

**Breaks today.** `prospector-hermes` was found by the *absence* of logs, and establishing that took
an interactive `fly logs` session. Fly retains logs for a short window and drops them; nothing ships
them anywhere else. `docs/LOGGING_AND_RETENTION.md` declares a policy and
`ops/automations/log_rotation.py` rotates on the laptop, but neither gets Fly's logs off Fly. So an
incident older than that window cannot be investigated at all, and after a cutover the previous
platform's logs are simply gone — which is the worst possible moment to lose them.

**Story.** *"everything fron dns, logs, everything, db"* · *"full ops visibility"*.

**Done when.** Application logs from every component are shipped to storage we own — R2, the same
bucket family as the backups — on a schedule, with a stated retention, and the console can answer
*"show me what this component logged on this date"* without an SSH session. The shipper is a plain job
in the engine image, not a platform feature, so it survives the platform changing. That last clause is
the architectural point: a log pipeline bought from the platform is lock-in wearing an observability
badge.

**Costs.** M. R2 storage for text logs is negligible; the work is the shipper and the reader.

---

### M11 — Every datastore, named, backed up, and proven restorable. **P0, M**

**Breaks today.** The estate holds state in more places than the risk register lists, and only two are
backed up at all. Declared or measured today: `prospector-store-api` SQLite (`/data/store.db`, one
1GB volume, `lhr`, `vol_4ql6dzwjylqeygnr`) plus its `/data/keys` ASP.NET data-protection key ring —
backed up, **never restored**; the engine store (SQLite catalogue plus append-only JSONL, 0.49 GiB,
2,935 dossiers, 906,341 ledger lines) — backed up, **never restored**; R2 — the files buyers download,
somebody else's durability but ours to enumerate; Stripe — an independent ledger of every payment
we have never exported; Hermes' state, now on a Fly volume rather than the laptop — **no backup at all**; and the provider-health,
retrieval-cache and scheduler files under the store, recoverable only if a restore includes them.

**Story.** *"everything fron dns, logs, everything, db"* · *"this si critial , busines dpeendent
work"*.

**Done when.** The inventory (M1) carries a datastore table listing, for each: where it is, how it is
backed up, its RPO, its RTO, and **the date of its last proven restore**. A datastore whose last
proven restore is blank, or older than its drill cadence, reads red on the console. The Stripe export
is written as a rebuild script — that is what turns R1 from fatal into slow.

**Costs.** M. Most of it is wiring what already runs into one honest table.

#### M11 census — measured 2026-08-19, read-only

Every volume on every Fly app, opened and listed. This is the table M11 asks for, at the coverage
it has today. "Last proven restore" is a date only where a drill actually ran and exited 0.

| Datastore | Where | Size | Backed up | Verified how | Last proven restore |
|---|---|---|---|---|---|
| Engine store `/data/store` | `prospector-engine`, vol `prospector_store` 20GB lhr | 701M — `prospector.jsonl` 351MB, `prospector.db` 3.1MB, `run_metrics.db`, `self_modifications.db`, ~15 JSONL logs | `backup_store.py`, daily, R2 `prospector-backup` | drill script | **2026-08-19 13:54 UTC, exit 0** |
| Claude state `/data/state/claude` | same volume | 257M | **NO** — outside every prefix in `backup_store.py` | — | never |
| Money DB `/data/store.db` | `prospector-store-api`, vol `store_data` 1GB lhr | 4,354,048 bytes, mtime Aug 19 17:22 | `offsite_backup` source `money-db`, daily, R2 | `PRAGMA integrity_check` | **never** |
| Data-protection key ring `/data/keys` | same volume | 1000 bytes, one XML key | `offsite_backup` source `data-protection-keys` | non-empty only | **never** |
| Hermes state `/data` | `prospector-hermes`, vol `hermes_state` 3GB lhr | 29M used — `/data/state` 27M, `/data/db` 1.9M (`coordinator.db` + WAL, `kanban.db`, `state.db` + WAL) | **NO** — named in no backup source | — | never |
| Pack files | R2 `prospector-packs` | not enumerated | third party, no export | — | never |
| Payments ledger | Stripe | not enumerated | third party, no export | — | never |

`prospector-store-web`, `prospector-searxng`, `prospector-ci` and `hermes-ci` hold no volumes and
are stateless. The `tie-*` apps are excluded on the founder's instruction.

**What this proves, against the earlier belief.** The money path IS copied off Fly, and that was
not certain before. Run on the engine, `python -m ops.automations.offsite_backup` reports
`OK money-db: 0.0h old` and `OK data-protection-keys: 0.0h old`, and the engine has both
`FLYCTL=/root/.fly/bin/fly` and a token set. The 20GB engine volume holds 701M, so nothing is
close to full.

**Three gaps the census found. One is fixed in this commit.**

1. **The offsite backup wrote no receipt.** `deploy/engine/supervisord.conf` wrapped `backup` and
   `restore-drill` in `receipt.sh` and left `offsite-backup` bare, so the one job that protects the
   money DB reported its verdict only into `fly logs`, which rotate. That is exactly what §0.3
   forbids. **Fixed here:** it now runs under `receipt.sh offsite_backup`, so the verdict lands in
   `/data/store/ops/receipts/offsite_backup.json` with a timestamp and an exit code.
2. **Hermes state has no backup at all.** 29M, so the cost is trivial; what is missing is a fetch
   command that does not tear a live SQLite file. `/data/db` holds three databases with active WAL
   files, so a plain `tar` copies a torn page set. It needs `sqlite3 .backup` or the Python backup
   API run on the machine before the tarball, and that is M4's torn-snapshot work, not a one-line
   config addition. **Not fixed here, deliberately** — a backup that silently restores corrupt is
   worse than a gap you can see.
3. **Every backup lands in one R2 account.** `prospector-backup` holds the money DB, the key ring
   and the engine store. Losing that one account loses every copy of everything. That is L11's first
   flakiness test, a mechanism that depends on a single thing, and it is unaddressed.

**Still true after the census:** no datastore except the engine store has ever been restored. Two
of the seven rows above have a backup nobody has ever read back.

---

### M12 — Redundancy, decided per component rather than assumed. **P1, S–M**

**Breaks today.** `mumchimp.com` runs on **one** machine. `api.mumchimp.com` runs on **one** machine
with **one** volume in **one** region. The engine runs on one container **on purpose** — two engines
keep two spend ledgers and can spend twice the $100/day cap, which is a correctness fence, not a
capacity choice. Nothing on any page distinguishes the deliberate single instance from the accidental
ones, so the estate reads as uniformly fragile when only part of it is.

**Story.** *"and redundancy"*.

**Done when.** Every component in the inventory carries an explicit redundancy verdict — `redundant`,
`single by choice` with the reason, or `single, unfixed` — and the console shows it. Two actions
follow from today's numbers: `fly scale count 2` on `prospector-store-web`, which is stateless, one
command, about $2/month, and it is the shop front; and a recorded decision on the store API, where a
second machine in front of an unbacked-up volume protects against the *less* likely failure.

**Costs.** S for the web scale-out, M for the verdict column. The store API answer is a decision in
§7, not a build.

**The summary from `ESTATE_CONTINUITY_PLAN.md` §5 is still true and still governs the order:** we do
not have a redundancy problem, we have a backup problem. That is why this is M12 and not M1.

---

## 4. Hermes is the test case

The founder asked for Hermes to be *"use[d] as test"*, and it is the right one: it is real,
half-migrated, and nothing depends on it for revenue. Failing the drill on Hermes costs nothing;
failing it on the storefront costs sales.

Hermes exercises every requirement at once:

- **M1** — it is the app the inventory must catch, and it is caught today.
- **M2** — its keys and its submodule are exactly the "new machine" problem in miniature.
- **M3** — it has to leave the laptop, which is a cutover with `laptop` as the source adapter.
- **M4** — it holds small state that must survive the move.
- **M6** — its move is D5 rehearsed on something we can afford to break.

**The Hermes decision is still the founder's** (task #74): commit a config for `prospector-hermes` and
cut over, or destroy the app and cut over later. Either answer is fine and both are cheap. What is not
fine is the current state, which is an app running on Fly that no branch describes while eleven
launchd jobs still run on the laptop.

---

## 5. Tooling — the analysis, and the one check I could not run

**Constraint from the founder: free or open source.** Also binding: no new cloud infrastructure, no
rented EC2, no managed database, and CI stays on the self-hosted Fly runners (deleting `CI_RUNS_ON` is
an emergency lever only).

**Selection criteria, in order.** (1) Does the estate already have something that does this? (2) Is it
free and open source? (3) Does it run on the self-hosted runners and on a bare machine without a
hosted control plane? (4) Does it work identically on laptop, Fly and a plain Linux box — because a
tool that only works on Fly re-creates the lock-in this programme exists to remove?

Criterion (1) is doing most of the work here. The honest finding is that **this estate needs very
little new tooling**: shell adapters, Python probes and the existing console cover four of the eight
gaps outright.

| Need | Use what we have | Candidate if we need more |
|---|---|---|
| Inventory | `fly_estate_probe.py`, `launchd_plists.py`, `process_audit.py`, joined by M1 | none needed |
| Declarative infra | `deploy/compose/` + adapters (founder route "c") | **OpenTofu** later, if a second provider proves painful |
| Machine bootstrap | new `bootstrap_machine.sh` | **mise** for tool versions; **Ansible** only if a second machine appears |
| Secret restore | `.env` + `deploy/secrets.sh` | **age** or **SOPS+age** for an encrypted-in-repo secret file |
| Backup + restore | `store_migrate.py`, `offsite_backup.py` | **restic** if retention/dedup becomes the bottleneck |
| SQLite durability | `VACUUM INTO` (M4) | **Litestream** for continuous replication, if RPO 1h is not enough |
| Chaos | plain `pytest` scenarios against throwaway targets | **Toxiproxy** for network faults; **Pumba** for container kills |
| End-to-end | **Playwright** — already in the repo for the storefront | **k6** only if load, not correctness, becomes the question |
| DNS as a file | nothing today | a plain `dig`-to-zone-file export diffed daily; **octodns** only if the zone grows a provider API |
| Log shipping | `ops/automations/log_rotation.py` + R2, exactly as the backups already do | **Vector** only if a plain shipper stops being enough |
| Log reading | the console (M5/M10) | **Loki** only if grep over R2 objects stops being enough |
| Redundancy | `fly scale count`, and the equivalent adapter verb elsewhere | none needed |
| Scheduling drills | GitHub Actions on the self-hosted runners, like `escape-hatch-drill.yml` | none needed |

**The check has now been run. It is [`docs/STACK_AUDIT.md`](STACK_AUDIT.md), merged as PR #392.**
This section used to carry a HYPOTHESIS marker saying `WebSearch` was refused by the context guard,
so the right-hand column was knowledge rather than a fetched source. That is no longer true, and the
audit's verdicts outrank the table above wherever the two differ. What it changed:

- **Five of the twelve gaps stop being things we build** — M1, M2, M4, M6 and M10 all have an
  existing tool that does the job.
- **Inventory (M1): use Steampipe, do not write one.** The table above says "none needed"; that was
  wrong once the bar became *"probe and audit any systen"* rather than probe this one.
- **Scheduling: Dagu**, replacing all 31 launchd jobs (task #95). Temporal, Windmill and Cronicle
  were considered and rejected, with reasons, in the audit.
- **Liveness: Healthchecks plus Gatus** (task #95), replacing nine bespoke "what's running" scripts.
  The audit's finding on this estate: *many bespoke observers, no dead-man's switch.*
- **Backup: Litestream plus restic** (task #94). Litestream moves from "if RPO 1h is not enough" to
  required, because the 30-minute bar demands zero downtime and copying a live SQLite file is
  downtime by definition.
- **Declarative infra: OpenTofu, not Terraform.** Terraform has been BUSL since August 2023, so
  choosing it to escape lock-in is a contradiction. Also **not Kamal and not Nomad** — the
  eleven-verb adapter contract in `deploy/PORTABILITY.md` already works, and Nomad is BUSL too.
- **Toolchain: mise plus a uv lock.** The audit measured four different Python interpreters in this
  estate and no version pin anywhere.
- **Secrets: SOPS + age. DNS: octoDNS. Logs: Vector into Loki or OpenObserve. Chaos: Pumba and
  Toxiproxy. Supervision: s6-overlay** instead of supervisord.

The licence, portability and maintenance check the old marker described was applied to each of
those. The left-hand column still needs no check; it is code in this repo.

**What I will not propose.** A hosted control plane of any kind (Terraform Cloud, a SaaS chaos
platform, a managed backup service). Each one re-introduces exactly the dependency this programme
removes, and each is a monthly bill.

---

### 5.1 What the research changed, 2026-08-19 — and the one thing that shipped

Founder, this morning: *"the goal of this audit is not to repeat the same mistakes, we need to
improve the state of play also and research better tooling always as we audit"*. Fair. §5 above
picked eleven tools and **not one of them has landed**. A decision on paper is not an improvement.

So: four questions researched today, what each one CHANGED, and the fix that shipped with it.

**1. Litestream is usable now, and it was not before.** Version 0.5.0 (late 2025) replaced the old
WAL-polling design with LTX. The old design made replicating many databases from one process
impractical, which is why the earlier note here read *"if RPO 1 h is not enough"*. It now replicates
hundreds of databases from one process, and its S3-compatible targets explicitly include Cloudflare
R2 — the bucket this estate already pays nothing for.
*Changes:* task #94 moves from speculative to buildable with **no new provider, no new bill and no
new credential**. It reuses `ops/config/offsite_backup.yaml`'s bucket.
*Risk:* a replication stream is not a backup — it faithfully replicates a `DELETE FROM`. It must sit
BESIDE the daily snapshot, never replace it.
*Security:* it needs write access to the backup bucket from the engine container, which already
holds those keys. No new blast radius.
*Compliance:* order and entitlement rows are personal data. Continuous replication means the same
personal data in the same bucket, more often — it does not widen the retention window, which is
still governed by `keep: 30`.
Source: [Litestream](https://litestream.io/).

**2. Borg is disqualified on a fact, not a preference.** Borg requires exclusive access to a
repository, so a laptop, a Fly machine and a future second machine cannot back up into one repo.
That is the whole shape of this estate. Kopia is the faster of the remaining two — community
benchmarks in early 2026 put large restores 20–40% ahead of restic — and it has a web UI and more
backends. **restic wins anyway**, and the justification is today's bug: the failure this estate keeps
having is a verifier that grades a file instead of opening it. restic's `check --read-data`
is part of the core tool, and it supports concurrent backups from several hosts into one repository.
A tool that restores 30% faster is worth less than a tool that tells the truth about whether it can
restore at all.
*Risk:* a repository password. Lose it and every backup is unreadable — this is the same class as
losing the ASP.NET key ring, and it goes wherever that goes (M2, task #82).
*Security:* end-to-end encryption in all three, so the backup provider never sees plaintext orders.
*Compliance:* client-side encryption is what makes an offsite copy of buyer records defensible.
Sources: [restic](https://restic.net/), [Kopia](https://kopia.io/), [BorgBackup](https://www.borgbackup.org/).

**3. The torn-snapshot rule, stated exactly.** `.backup` uses the SQLite Backup API and produces a
byte-faithful copy including free pages. `VACUUM INTO` writes a compacted copy and rewrites every
page. **Both are safe against a live database in WAL mode; a plain file copy is not**, because
recent commits live in the `-wal` file and copying the main file alone loses them silently.
*Changes:* nothing for the money database — `/internal/backup/database` already runs `VACUUM INTO`
before it answers. It names the remaining tear precisely: **Hermes state is fetched by `tar`**, and
`coordinator.db-wal` was 1,388,472 bytes when measured. That is why M4 (task #80) is still open, and
the fix is one endpoint on the Hermes side, not a new tool.
Sources: [SQLite forum: hot backup in WAL mode](https://sqlite.org/forum/forumpost/2ea989bbe9),
[backing up SQLite](https://oneuptime.com/blog/post/2026-03-02-how-to-back-up-sqlite-databases-on-ubuntu/view).

**4. The scheduler is not the thing to land first.** Dagu, Cronicle and supercronic were compared
again, and the finding that matters is negative: **none of the three has native dead-man's-switch
integration**. All of them ping Healthchecks by HTTP from inside the job. So the monitored-job
wrapper is scheduler-independent — which means the estate can get the alerting benefit of task #95
*before* migrating any scheduler, and keep it *after*.
*Changes the order of work.* `deploy/engine/supervisord.conf` already wraps four jobs in
`receipt.sh`. Teaching that one script to ping a check URL converts four unwatched jobs into
monitored ones without adopting Dagu, and survives the Dagu migration unchanged. Task #97 still
stands: the checker must not run on the machine it watches.
Sources: [Dagu](https://github.com/dagucloud/dagu),
[Healthchecks docs](https://healthchecks.io/docs/), [Cronicle](https://deployable.sh/apps/cronicle/).

**And the improvement that actually shipped today, because research on its own is another probe.**
The ASP.NET Data Protection key ring — the thing whose loss makes every grant token and cookie
undecryptable — was graded `verify: nonempty`. A byte count cannot tell a whole key ring from a
download that stopped halfway, and the half-download is the copy you find out about during a
restore. `verify_copy` now has a `tgz` kind that opens the archive and reads its index
(`ops/automations/offsite_backup.py`), the declaration uses it (`ops/config/offsite_backup.yaml`),
and four tests hold it there, including one that grades the declaration so nobody quietly puts
`nonempty` back (`tests/unit/test_offsite_backup.py`). This is the same class as task #109, where
`backup_store --verify-only` fails on a healthy backup: **a verifier that grades the wrong property
is worse than no verifier, because it is believed.**

---

## 6. Sequence

Ordered by what unblocks what, and by the founder's rule that the money path outranks the engine.

1. **M9(a) commit the DNS zone.** One export, one committed file, one daily diff. It is an afternoon,
   and it removes the only unrecoverable loss on the register.
2. **M1 inventory**, across all ten resource classes. Everything else needs to know what exists, and
   it is the cheapest thing that makes the estate legible.
3. **M11 datastore table** and **M4 restore drills (a) and (b).** The largest uncovered risk is R1,
   and the fix is a safe snapshot method plus a proof. Do this **before** any further migration,
   because migration is what breaks it — the order effect in `ESTATE_CONTINUITY_PLAN.md` §4.1.
4. **M6 D1 and D3 on a schedule**, plus the DNS diff from step 1. Three drills in the pattern
   `escape-hatch-drill.yml` already proves works.
5. **M12 `fly scale count 2` on `prospector-store-web`.** One command, and the shop front stops
   being a single machine.
6. **M2 bootstrap**, with **M6 D4** as its proof. This is what makes "my laptop died" survivable.
7. **Hermes decision (#74) and cutover.** The live test of steps 1–6.
8. **M5 console panel** and **M10 log shipping** — the two halves of full ops visibility: receipts
   worth reading, and logs that outlive the platform that wrote them.
9. **M3 storefront adapter**, behind **M6 D2**. Platform independence for the money path.
10. **M7 chaos** and **M8 end-to-end**, starting with the three cheapest scenarios each.

Steps 1–5 reduce real, business-dependent risk this week. Steps 9–10 are what stop it coming back.

---

## 7. Open decisions — these need the founder, not more analysis

Each of these changes what gets built, and no default is safe enough to assume.

1. **Where do secrets live so a new machine can fetch them?** Options: encrypted in the repo with
   `age`/SOPS and one passphrase held by the founder; a password manager the bootstrap reads;
   or a printed/offline copy plus a manual step. The third is honest and cheapest; the first is
   seamless and needs one secret to survive outside the estate. Blocks **M2**.
2. **Which second provider do we prove portability against?** `sshdocker` is written and targets any
   Linux box with Docker and SSH, but proving it needs a box. Options: prove it against the laptop
   (free, honest, but the laptop is what we are leaving); prove it against a cheap VM; or prove only
   the dry-run and accept that. Blocks **M3** and **D5**.
3. **Hermes: cut over or destroy?** (task #74). Blocks §4.
4. **Drill cadence.** The table in **M6** proposes nightly/weekly/quarterly. Weekly costs runner
   minutes we already own; quarterly needs an announced window.
5. **DNS: move the zone to a provider with an API, or keep GoDaddy?** An API makes cutover scriptable
   and the zone diffable without scraping. Staying put is one less account to protect. Blocks
   **M9(c)**.
6. **Store API redundancy.** A second machine needs the SQLite write to move to one primary, or a
   swap to Postgres — which re-introduces a managed database, the first lock-in
   `deploy/PORTABILITY.md` refuses. Recommendation: leave it single, fix the backup, revisit after
   M4. Blocks **M12**.

---

## 8. Ledger

Append here. One line per shipped item, with the receipt.

| Date | Item | What shipped | Receipt |
|---|---|---|---|
| 2026-08-19 | M1 (part) | `scripts/fly_estate_probe.py` — Fly apps with no committed config | PR #390 **open, not merged**; `exit=1`, `prospector-hermes` named |  <!-- doc-lint-ok: lands with PR #390 -->
| 2026-08-19 | M3 (fence) | `deploy/targets/fly.sh` flyctl shim; D3 was red with `fly: command not found` | PR #388; 2 failed → 3 passed |
| 2026-08-19 | — | `docs/ESTATE_MAP.md` Hermes section corrected from asserted to measured | PR #390 |
| 2026-08-19 | M4 (part) | key-ring backup graded by opening the archive, not by its size — new `tgz` verify kind | PR #441; `26 passed` |
| 2026-08-19 | M4 (part) | `verify:` has no default — a source that states no kind, or an unknown kind, is refused when the declaration is read | `29 passed`; mutation-proved (`2 failed` with the default restored) |
