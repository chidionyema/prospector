# Platform independence, migration and disaster recovery

> **The build spec is `docs/GOLD_STANDARD_SPEC.md`.** This file is the requirements and the
> evidence — what must be true and what proves it. That file is the thing to build: twelve
> components, their interfaces, and the six slices that land them, each closed by a drill.
> Founder, 2026-08-21: *"you need to get faster ad have aplan to deliver gold standard super
> fast"*, *"you need to breakit downto spec"*.

**Headline requirement, in the founder's words: platform independence.** Everything below serves it.
A component is platform independent when a committed file describes it, an adapter moves it, a drill
has already moved it, and losing the platform costs a DNS edit rather than a rebuild.

**This document guides the architecture of the project.** It is not a migration checklist that gets
consumed and thrown away. When a design decision and this page disagree, this page wins, and the
decision gets changed or this page gets amended with the reasoning. Two rules follow from that and
bind new work: **nothing may be built that only one platform can run**, and **nothing holds state
that is not a file we can copy**.

> **START AT §10 AND §11 IF YOU ARE NEW, OR IF YOU ARE LOST.** Added 2026-08-20, because the
> founder said *"i dont have a wwhole stack or architectuure or platfon plan. i dont knoww what th
> eplatfornwill look like when we are done"* and *"we qre just stuck and nocler guidanc"*.
> **§10 is the target platform** — ten planes, one contract each, and what "done" looks like in a
> paragraph. **§11 is the requirements register** — 41 functional and 14 non-functional
> requirements, each with the drill that proves it and the deliverable that builds it. §0–§9 grade
> what is broken; §10–§11 say what we are building. When they disagree, §10 and §11 win.
> **§12 answers how much of this can sensibly move to Kubernetes, and §13 names the final
> tooling** — the two questions the founder asked on 2026-08-20 that nothing here answered.
>
> **§10 and §11 are published as the [GOLD STAR PLAN](https://claude.ai/code/artifact/ef6fe784-7f6c-4981-85cd-37dfbe40b696), dated
> 20 August 2026 and adopted by the founder as the target** — *"this is perfect ... this is what we
> are working toward, label it gold star plan and date"*. The page also answers two things this
> document did not: how much of the estate can sensibly move to Kubernetes, plane by plane, and the
> tooling we standardise on. That page renders THIS document; when they differ, this document is
> right and the page gets republished at the same URL. It is linked from `README.md` and
> `docs/ESTATE_MAP.md` so a session that loses its context can find it from any door into the
> repo.


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

### 0.4 The gaps graded against the eight requirements

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
refinements of the existing set; they are a different deliverable, and pretending otherwise is
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
| Adapters | `deploy/targets/{fly,laptop,sshdocker,k8s}.sh` | four written; `fly.sh` flyctl shim landed 2026-08-19 (PR #388); `k8s.sh` 2026-08-20, and every adapter is now graded against the verb list by `tests/unit/test_every_deploy_target_implements_the_contract.py` |
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

## 3. The fifteen gaps, stated as what breaks today

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

### M13 — A staging environment, with the laptop as the emergency fallback. **P1, M**

**Founder, 2026-08-19:** *"when setting u staging env, also setup laptop as energency fallback"* —
said in the same breath as *"prod is canonical, we need a way to keep local in sync"*, and the two
are one requirement, not two.

**Breaks today.** There is no staging environment at all. Every change is proved in production or
not proved. And the laptop, which held the whole estate until 2026-08-18, is now neither: it is not
production, and nothing keeps it current enough to become production if Fly is lost. It holds a
store 277,000 ledger lines and 654 dossiers behind, with a 42-hour-stale heartbeat (issue #454).
A fallback that has not been fed is a fallback that will not start.

**Story.** One environment to prove a change in before customers meet it, and one machine that can
take over if the platform under production disappears — and they are the same build, because a
staging environment that continuously restores production's state IS a warm fallback, and a warm
fallback that nobody exercises IS the thing that fails the drill.

**Done when.**

1. A `staging` target exists in `deploy/targets/` and a committed compose/fly file describes it.
   Nothing in it is hand-made.
2. Staging is fed by a **restore from production's backup**, on a schedule — not by a copy of a
   copy. That makes the restore drill (M4) and the staging refresh the same job, so the drill runs
   continuously instead of quarterly, and staging's freshness is the receipt that the backup works.
3. The **laptop is a declared fallback target** with the same adapter, the same restore feed, and a
   documented promotion path: one command that makes it serve, plus the DNS edit (M9).
4. A probe FAILS when the fallback's state is older than an agreed RPO. Staleness must be loud.
   Prose was the only thing asserting there was one store, and prose cannot fail.

**Costs.** M. Most of the machinery is M4's restore path and M3's adapter; this is a third target
and a schedule, not a new mechanism. Depends on **M4**, **M11** and the sync built for #454.

**What it is NOT.** It is not a second live engine. Two engines keep two spend ledgers and can spend
twice the daily cap (see M12). The fallback is COLD-to-WARM: fed, provable, and started by a
decision, never automatically.

---

### M14 — Nothing has ever been put under load. **P1, M**

**Founder, 2026-08-20:** *"stress testing"*, in the same breath as chaos and security, and under
*"a low nintennace stack wheere everyhting works and slef heals"*.

**Breaks today.** There is no load generator in this estate. Measured 2026-08-20: no locust, no k6,
no wrk, no vegeta, no artillery, and no hand-rolled concurrency harness anywhere in the tree. The
two files whose names suggest otherwise are not that — `scripts/load_gate.py` decides whether THIS
MACHINE is currently fit to produce a trustworthy test result, and `tools/corpus/load.py` loads a
text corpus. Both are useful and neither generates load. This paragraph replaces an earlier claim
in §6 that named them as stress-testing assets; that claim came from a filename search and was
wrong.

So every capacity number the estate has ever quoted is an inference from single-request timings.
Nobody knows what the storefront does at 50 concurrent buyers, what the engine does when the moat
is asked for 16 verdicts at once on a benched brain, or where the Fly volume's IO ceiling is. The
one place this was measured — `minimax_concurrency` at 16/16 with zero 429s — was measured against
a provider, not against our own machine.

**Story.** Know the ceiling before a customer finds it. The number that matters is not "how fast is
one request", it is "at what concurrency does the thing that earns money start refusing people, and
what breaks first when it does".

**Done when.**

1. One load profile per earning path, committed: the storefront's browse-to-buy, and the engine's
   verdict lane. Not a synthetic benchmark — the real endpoints with real payload shapes.
2. Each profile prints a **saturation point**: the concurrency at which p95 leaves its agreed band,
   plus what the box was doing while it ran (`load_gate.py` already prints exactly that, and this
   is the right use of it).
3. A run against **staging, never production** — which makes M14 depend on M13.
4. The result is a committed number with a date, not a claim. It goes stale, and a stale capacity
   number is re-measured rather than re-quoted.

**Costs.** M. The generator is off-the-shelf; the work is defining the profiles and having somewhere
safe to point them. Depends on **M13**.

**What it is NOT.** It is not a performance optimisation project. The deliverable is a known ceiling
and a known first failure, not a faster number.

---

### M15 — Nothing attacks this system. **P1, M**

**Founder, 2026-08-20:** *"secitory etsing"*.

**Breaks today, and this one is partly covered — say which part.** Static analysis and dependency
advisories DO run in CI: `bandit` and `dep_advisory` (`.github/workflows/ci.yml:595,679`, with
scripts at `.github/scripts/`), and `npm audit --audit-level=high` on both web apps
(`ci.yml:1028,1158`). `docs/ARCHITECTURE_SECURITY_BASELINE.md` Part 3 records the posture and Part
3's "Open findings" lists what is known. `docs/personas/security.md` is 768 lines of review
standard.

What is missing is anything that **attacks the running system**. Every control above reads source
or a dependency manifest. Measured 2026-08-20: no secret scanner in CI (no gitleaks, no
trufflehog), so a committed credential is caught by a human or not at all; nothing exercises
authentication or authorisation against a live endpoint; nothing tries to buy something it should
not be able to buy; and the fulfilment fence — the thing standing between a payment and delivery —
has never been probed by anything other than its own unit tests.

**Story.** A reviewer reading the code and an attacker holding a request are not the same test, and
the second one is the one a customer's money depends on.

**Done when.**

1. **Secret scanning in CI**, on every push and on the whole history once. It is the cheapest item
   here and the only one that catches a mistake already made.
2. **The money path is probed from outside**: an unauthenticated request to every fulfilment
   endpoint, a request for someone else's order, a price tampered in flight. Each asserts a refusal
   with the right status, against staging.
3. **The published surface is enumerated** — every endpoint the internet can reach, generated from
   the app rather than typed — so "what is exposed" is a probe and not a paragraph.
4. **Findings have owners and dates**, appended to `ARCHITECTURE_SECURITY_BASELINE.md` Part 3 rather
   than to a new document.

**Costs.** M, and item 1 is S on its own and should not wait for the rest. Depends on **M13** for
items 2 and 3, because probing production for authorisation holes is the one test that must never
run against real buyers.

**What it is NOT.** It is not a penetration test of a third party's infrastructure, and it is not a
compliance exercise. It is our own surface, attacked by us, on a machine we own.

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

- **Five of the gaps stop being things we build** — M1, M2, M4, M6 and M10 all have an
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

### 5.2 Revisited 2026-08-21 — the eleven tools were picked before Kubernetes was the answer

Founder, 2026-08-21: *"so nay need to revisit tooling"*, *"ad see if justificitos still hold"*,
*"againlook t open source also and see anyhing we can use"*, *"reliable"*, *"trusted"*.

§5 and §5.1 picked eleven tools for an estate that ran on a laptop and on Fly. §10.4 then made a
Kubernetes cluster the place both of those move to. Nobody read the two sections together. Reading
them together drops two tools, shrinks two more, and adds one that does more of the work than any
of the eleven.

**The contradiction, in the document itself.** Line 865 says Dagu replaces all 31 launchd jobs.
Line 1612 says a Kubernetes `CronJob` replaces the launchd jobs one for one. Both cannot be the
plan. This is measured from the file, not argued.

**1. Velero is the change that matters, and it did not exist as an option when §5 was written.**
It backs up a whole cluster — the running things, the settings, and the disks — and restores it
into a *different* cluster. That is the 30-minute move, done by a tool instead of by us. Broadcom
gave it to the Cloud Native Computing Foundation on 11 March 2026. It is filed at the foundation's
lowest tier because the paperwork is three months old, not because the tool is: it has been the
usual way to back up a Kubernetes cluster for years, under its old name Heptio Ark.
*What it changes:* requirement D-P1.5, the ten-plane bring-up, stops being eleven hand-written
steps and becomes one restore, plus proof.
*What it does not do:* it copies a SQLite file the same wrong way we do today. Point 3 below.

**2. Dagu is dropped. Use `CronJob`.** Dagu was picked to replace 31 laptop jobs. Once those jobs
run on a cluster, `CronJob` already does it, with history and retries, and there is nothing extra
to install, learn or keep patched. A search for how Dagu behaves in production in 2026 returns
nothing to read — that is the answer to *"trusted"*. If we later need one job to wait on another,
the trusted choice is Argo Workflows, which is a graduated foundation project and whose scheduled
jobs are built to behave like `CronJob`.

**3. restic and Litestream both stand, and Velero does not replace either.** Velero copies a disk;
it cannot make a live SQLite file safe to copy, which is the exact fault §5.1 point 3 already
names in the Hermes database. Litestream keeps the money database continuously copied. restic
keeps a copy that survives the cluster being gone, and its `check --read-data` opens the backup
instead of grading the file — the reason it beat Kopia stands unchanged.

**4. Two shrink, because the cluster does most of their job.** s6-overlay was chosen to keep
processes alive inside a container; on a cluster that is the cluster's own job, so it is needed
only where a container really must run two things. Gatus was chosen to check nine endpoints;
the cluster checks its own, so Gatus is kept only for what the cluster cannot see — the public
website, from outside. Healthchecks stays as the dead-man's switch: nothing inside a cluster can
tell you the cluster stopped.

**5. Secrets: SOPS with age still stands, and it is now better supported than when it was picked.**
SOPS is a foundation project and age is a first-class way to encrypt with it. The popular
alternative, the External Secrets Operator, needs a hosted secret manager to read from — we have
none, the founder has rejected cloud key services by name, and adding one is a monthly bill and a
new dependency. So: no change.

**6. No change to** Steampipe (still the only answer to *"probe and audit any systen"*), octoDNS,
Vector, OpenTofu (still parked until a second provider hurts), mise with a uv lock, Pumba and
Toxiproxy, or Playwright.

**Net: eleven tools become nine, and one of the nine is new.** Out: Dagu, s6-overlay as a general
rule. In: Velero. Reduced in scope: Gatus.

**Nothing here is settled until a drill proves it.** The claim that has to be tested first is
Velero's: restore this estate into a second, empty cluster and run each plane's own check against
it. Until that has run green, Velero is a decision on paper, which §5.1 already says is not an
improvement.

Sources: [Velero](https://velero.io/) ·
[Broadcom donates Velero to CNCF, InfoQ, 2026-05](https://www.infoq.com/news/2026/05/broadcom-velero-cncf/) ·
[Velero at CNCF](https://www.cncf.io/projects/velero/) ·
[Argo Workflows scheduled workflows](https://argo-workflows.readthedocs.io/en/latest/cron-workflows/) ·
[Kubernetes secrets in 2026: ESO, Sealed Secrets, SOPS, Vault](https://sanj.dev/post/kubernetes-secrets-management-comparison/)

---

## 6. The delivery plan

> Phases 0–6 below are the REQUIREMENT order. The BUILD order is six slices in
> `docs/GOLD_STANDARD_SPEC.md` §5, thin end-to-end first, and it is the one to work to.

Founder, 2026-08-20: *"i need to see a detailed pla of how you are going to deliver this project.
this is a sassive transfornation proect and our buniess is dependent on the success of this
endeavorur"*, *"nission cuticl"*.

### 6.0 How this plan is built, and how to read it

One rule governs the shape of it: **every phase ends in a drill that either goes green or goes red,
and the drill is the definition of done.** Not a document, not a review, not a claim in a reply. A
phase is finished when a named command exits 0 on a machine that is not this laptop, and leaves a
receipt something else can grade. This is the only structure that survives a session dropping
mid-phase, which is the normal case here.

Read it as: **what we cannot lose (Phase 0) → what we have (1) → can we get it back (2) → can we
see it (3) → can we move it (4) → does it hold when attacked (5) → the thirty minutes (6).**
The order is not preference. Each phase is the precondition of the next: you cannot move an estate
you have not inventoried, you cannot trust a move you cannot observe, and you cannot claim thirty
minutes for something you have never timed.

**Sizes are S (an afternoon), M (a day or two), L (a week).** They are estimates and each one is
re-stated as a measurement once the work is done.

### 6.1 Phase 0 — the data survives the machine. **B0. IN PROGRESS.**

Nothing else in this plan means anything if the catalogue is gone, because every later phase is a
way of *rebuilding from a copy*.

| Item | State | Proof |
|---|---|---|
| Nightly local snapshot | running | `store/backup.log` |
| Offsite copy to R2 | running | `[program:offsite-backup]` in `deploy/engine/supervisord.conf` |
| Weekly drill that pulls from R2 and grades it | **landed 2026-08-20**, never run live | `deploy/engine/offsite_drill.sh`, commit `e53e265b` |
| The restore contract itself | **fixed 2026-08-20** | commit `5db638e2` — ETag is the only fatal check |
| Signing key escrowed off every code tree | done | `~/.prospector/escrow/`, mode 400 |
| Signing key escrowed **off the machine** | **open, founder's action** | P3 on the register |
| **The encrypted secret store committed to `origin/main`** | **NOT DONE — and it was believed done.** `git ls-tree -r origin/main -- deploy/` has no `.age` file; the only copies are four automatic *"snapshot of uncommitted work"* commits on no branch | F-44. Founder's action: git history cannot be un-published |
| **`.env` present and every symlink to it live** | **restored 2026-08-21** after being missing, with 31 dead links across 114 trees | `find`-based census, re-run: 33 resolving, 0 dead |

**Exit:** one live run of `deploy/engine/offsite_drill.sh` on `prospector-engine` exits 0 and writes
a receipt. Until that run exists, the drill is proved by test and not by use, and this phase stays
open. **Next command:** wait for the weekly timer, or trigger it by hand on the machine.

**Second exit condition, added 2026-08-21:** the secret store is decryptable **from `origin/main`**
into a scratch tree and every name in `deploy/secrets.required` is present. Today that command
cannot be run at all, because the file is not on the branch. A backup that survives only inside an
automatic snapshot is not a backup; it is a near miss that has already been cashed once.

### 6.2 Phase 1 — know what we have. **M1, M9, M11. P0.**

Three inventories exist and none of them meet, so no one can answer "what is running" without
reading three lists and reconciling them by hand. Everything downstream needs this answer.

| Step | Gap | Size | Exit — the command that goes green |
|---|---|---|---|
| Commit the DNS zone, diff it daily | M9(a) | S | a committed zone file, and a scheduled diff that goes red on drift |
| One inventory across all ten resource classes | M1 | M | one probe prints every resource; a test fails when a class is unclaimed |
| Every datastore named, with its size and its backup | M11 | M | the table is generated, not typed |
| **One inventory of every configuration value, not just secrets** | F-41 | M | a probe prints every runtime value and where it is declared; today it is spread over **six kinds of place** — 261 env-ish files in 114 trees, 6 Fly `[env]` blocks, `config.yaml`, 25 launchd plists, 7 Actions variables, 13 Fly apps |
| **A drift check that fails when a value differs from its declared home** | F-42 | M | the probe run against every target exits non-zero on the first disagreement |

DNS goes first because it is the only entry on the risk register with **no substitute**: lose the
zone and there is nothing to restore it from. It is an afternoon.

**Exit:** the inventory probe is the single answer to "what does this estate consist of", and a test
refuses a new resource class that nothing claims.

### 6.3 Phase 2 — prove we can get it back. **M4, M2, M6. P0.**

Phase 1 says what exists. This phase proves each of those things can be rebuilt from nothing.

| Step | Gap | Size | Exit |
|---|---|---|---|
| Restore drill per datastore, on a schedule | M4, M6 D1/D3 | M | each drill writes a receipt; a stale receipt fires an alert |
| Bootstrap a new machine from the repo plus one secret | M2 | M | a clean box serves after one documented sequence |
| D4 — "my laptop died" | M6 D4 | M | the bootstrap is the drill; it is timed |

**M2 is blocked on open decision 1** (where secrets live so a new machine can fetch them). That
decision is the founder's and it is on the critical path of the whole programme, because B2's thirty
minutes cannot include a manual secret hunt.

**Exit:** every datastore in the M11 table has a dated green restore receipt, and a new machine has
been brought up once, timed.

### 6.4 Phase 3 — see it, in real time. **M5, M10, #355. P0 for the alert bus.**

Founder, 2026-08-20: *"our notiong nand elerting is poor ll round"*, and the target,
*"a low nintennace stack wheere everyhting works and slef heals and is obvered realtine reparing"*.

This phase is currently the weakest in the estate and it is the one that makes every other phase
observable. `docs/STACK_AUDIT.md` already named it: *"many bespoke observers and no dead-man's
switch"*. Issue #355 names the live defect.

| Step | Size | Exit |
|---|---|---|
| One alert bus that leaves the machine | S | an alert raised on `prospector-engine` reaches a phone |
| Silence detection — a job that stops running is itself an alarm | S | Healthchecks, decided 2026-08-19, not landed |
| Endpoint reachability | S | Gatus, decided 2026-08-19, not landed |
| Logs that outlive the platform that wrote them | M10, M | logs from a destroyed machine are still readable |
| The Continuity panel — drive all of this from the dashboard | M5, M | B4 and B5 met |

**Exit and the proposed rule:** *a rail that cannot go red where a human sees it is not a rail.*
Testable, which is the point — a test asserts every alert key has a reachable off-machine sink in
the environment the code is actually running in, so this cannot silently regress to a file again.
Measured 2026-08-20: 18 critical `moat_blind` alerts sat in a file, none delivered.

### 6.5 Phase 4 — move it. **M3, M12, M13, Hermes. P0/P1.**

| Step | Gap | Size | Exit |
|---|---|---|---|
| `fly scale count 2` on the shop front | M12 | S | the shop stops being one machine |
| Storefront adapter, so the money path can leave | M3 | L | the money path has the three adapters the engine has |
| Staging, with the laptop as emergency fallback | M13 | M | a cutover is rehearsed somewhere that is not production |
| Hermes: cut over or destroy | decision 3 | — | founder's call, task #74 |

**M3 is the largest single item in the programme and it is P0**, because today only the engine can
leave Fly. The money path cannot, which means B6 is half-met and a provider failure takes the
revenue with it.

### 6.6 Phase 5 — break it on purpose. **M7, M8, plus two gaps that do not exist yet. P1.**

Founder, 2026-08-20: *"wwe also have the chose testing"*, *"stress testing"*, *"secitory etsing"*.

| Discipline | Home today | Action |
|---|---|---|
| Chaos | **M7**, with a done-when and three scenarios | build it; tooling decided (Pumba, Toxiproxy) |
| End-to-end | **M8** | build it; Playwright is already in the repo |
| Stress and load | **M14**, written 2026-08-20 | build it. There is **no** load generator in the estate — `scripts/load_gate.py` grades machine fitness and `tools/corpus/load.py` loads text; neither makes load |
| Security | **M15**, written 2026-08-20 | build it. bandit, dep_advisory and `npm audit` already run in CI; nothing attacks the running system, and there is no secret scanner |

Two of the four disciplines the founder named had no owner in the gap list. **M14 and M15 are now
written** (§3). Neither is as cheap as it first looked: the stress assets I named from a filename
search turned out to be a machine-fitness probe and a corpus loader, so M14 starts from nothing;
M15 starts from more than nothing, because static analysis and dependency advisories already run.

**Exit:** `tests/chaos/` holds one scenario per named risk, each asserting the *observable*
consequence rather than the internal state; a load run has a published number; a security pass has
findings with owners.

### 6.7 Phase 6 — the thirty minutes. **B1–B8. The acceptance test.**

The whole programme exists to pass one drill, and the drill is the founder's own sentence:

> thirty minutes, the whole stack, driven from the ops dashboard, no downtime the customer can see,
> nothing in use missed, and it works for a project that is not prospector.

It is graded as eight separate results, not one verdict, so a partial pass is legible:

| | Graded by |
|---|---|
| B1 completeness | the Phase 1 inventory: every class present at the destination |
| B2 thirty minutes | a stopwatch on the drill, published |
| B3 zero downtime | the shop front probed throughout; any non-200 is a fail |
| B4 from the dashboard | the drill is started from the console, not a terminal |
| B5 real-time progress | the console shows each step as it happens |
| B6 destination-agnostic | run once against a provider that is not Fly |
| B7 reusable | run once against a project that is not prospector |
| B8 probe and audit | the inventory is discovered, not hand-written |

**Nothing in this phase is new work.** If Phases 1–5 are done, Phase 6 is running the drill and
publishing the eight numbers. If it fails, the failing letter names the phase that was not finished.

### 6.8 How this is tracked, so nothing is lost when a session drops

Founder, 2026-08-20: *"we ned trackinng etrene"*, *"eep linking so contet neevr gets nissed f
session drops"*, and *"probbly need to autonnate this so i ont eep repeating nyself"*.

Four mechanisms, and each one is a file rather than a memory:

1. **This document is the plan of record.** §3 holds the gaps, §6 holds the phases, §8 is the ledger
   of what actually shipped with its commit. A session that drops mid-phase is recovered by reading
   §6 for the phase and §8 for the last receipt.
2. **One issue per gap**, so work cannot be started twice by two sessions that cannot see each
   other. Live examples: #355 alerting, #454 store sync, #74 Hermes.
3. **Every shipped item gets a ledger line with its commit**, in §8. A claim with no commit is not a
   delivery.
4. **Founder directives are captured automatically**, by `~/.claude/scripts/directive-capture.py`,
   a `UserPromptSubmit` hook that appends every prompt to `~/.claude/directives/<project>.jsonl`,
   read back with `python3 ~/.claude/scripts/directives.py --grep <word>`. **Measured 2026-08-20:
   it is capturing, and it is dropping.** 3,848 entries total and 426 today, but none of this
   session's directives are in it, and what it does hold is diluted with peer messages, task
   notifications and the engine's own model prompts. That defect is why the founder is still
   repeating himself, and it is tracked as part of Phase 3 — a capture rail that silently drops is
   the same class as an alert rail that silently drops.

**Cross-links, so a dropped session finds the rest of the context:** `docs/PLATFORM_DIRECTIVES.md`
and `docs/FOUNDER_NOTES.md` hold his standing instructions; `docs/decisions/0003-migration-and-dr-rulings.md`
holds rulings D1–D7 for this programme; `docs/STACK_AUDIT.md` measures what is running;
`docs/ENGINE_MIGRATION_PROGRAM.md` covers the engine's own move, and its Status line is stale —
it still reads "NOT STARTED" although the engine has run on Fly since 2026-08-18;
`docs/ARCHITECTURE_SECURITY_BASELINE.md` is the security baseline Phase 5 will attack;
`docs/SECRETS_PROGRAM.md` Part 6 is the key risk register that Phase 2's open decision resolves;
§9 of this document holds the founder's notes from 2026-08-20 verbatim.

### 6.9 What is on the critical path, and what only the founder can clear

| Blocker | Blocks | Owner |
|---|---|---|
| Where secrets live so a new machine can fetch them (decision 1) | M2, and therefore B2 | **founder** |
| Which second provider we prove portability against (decision 2) | M3, D5, and therefore B6 | **founder** |
| Hermes: cut over or destroy (decision 3) | §4 of this document | **founder** |
| DNS: move the zone or keep GoDaddy (decision 5) | M9(c) | **founder** |
| `claude_cli` not logged in on the Fly container | the engine's moat is blind right now | **founder** |
| MiniMax token plan limit reached | same | **founder** |

Everything not in that table is mine, and none of it needs asking.

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
6. **~~Which store is canonical?~~ DECIDED 2026-08-19.** Founder: *"prod is canonical, we need a
   way to keep local in sync"*. `/data/store` on the Fly volume is the source of truth; the laptop
   copy is a replica and the emergency fallback (**M13**). What remains is build, not decision:
   a sync down, and a probe that fails when a reader's store is not the store production writes.
   Tracked on issue #454. `CLAUDE.md` and the `where-production-runs` skill are corrected.
7. **Store API redundancy.** A second machine needs the SQLite write to move to one primary, or a
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
| 2026-08-20 | §10 | the target platform: ten planes, one contract each, and what done looks like | this document; counts re-measured from the tables, not asserted |
| 2026-08-20 | §11 | the requirements register: 38 functional, 14 non-functional, each with its drill and deliverable | 3 proven, 11 built-never-run, 34 not started, 4 blocked |
| 2026-08-20 | F-08a | new requirement: a copy is not a backup until it is proven complete against its SOURCE | `~/.prospector/standby/prospector.jsonl` measured at 25,296,896 bytes, 6.2% of the 407,981,598-byte source, and every truncating sync logged as a success. Register now 39 functional + 14 non-functional = 53; 3 / 11 / 35 / 4 |
| 2026-08-20 | §12 | how much of the estate can sensibly move to k8s, plane by plane: 2 whole, 5 half, 3 not at all | adapter read at `deploy/targets/k8s.sh`; `docker-desktop` live in `kubectl config get-contexts` |
| 2026-08-20 | F-08a | first completeness measurement taken against a real copy: the R2 ledger object is **99.88% of the live source**, and the shortfall is append lag, not truncation | gzip trailer ISIZE 413,570,301 B vs `wc -c` 414,063,171 B on `prospector-engine`; ledger measured appending at 437 B/s over 120s, so a 492,870 B gap is ~19 min of appends against a ~16 min old snapshot |
| 2026-08-21 | F-39, F-40 | **full portability to Kubernetes, not compute alone, on cloud AND on-prem** — added on founder instruction as future-plan requirements, with §12.1 costing the gap plane by plane | §12's measured today is 2 planes whole / 5 half / 3 not at all; the five halves are what F-39 buys. Register now **41 functional + 14 non-functional = 55; 3 / 11 / 37 / 4**, recounted by command, not asserted |
| 2026-08-24 | F-51, F-52, F-53, F-54 | **the standards stop being ours to remember.** Six of seven hand-written Kyverno policies retired to the upstream library pinned at a commit; staging and production overlays added; four CI gates added that grade the BUILT output. Founder: *"not write custon scripts for production cluster"*, *"we dont eforce stadard adbest practices"*, *"staging and prod cluster"* | `kubectl kustomize deploy/k8s/overlays/production \| grep -c '^kind: ClusterPolicy'` = **26**, all Enforce, 0 Audit. Every gate proved both ways before commit. Register now **60 functional + 15 non-functional = 75; 5 proven / 14 built-never-run / 51 not started / 5 blocked**, counted by script, not asserted. Neither cluster exists |
| 2026-08-20 | §13 | the final tooling named — 7 decided, 4 proposed, 4 things deliberately not adopted | `command -v` sweep on this laptop: helm, sops, restic, rclone, ansible, kind, k3d absent |
| 2026-08-20 | §10.4 | the k8s adapter question answered: nothing calls it, it has never run, and a free local cluster exists | `kubectl config get-contexts` → `docker-desktop` |
| 2026-08-20 | F-07 | **the first off-machine restore this estate has ever completed** — the R2 catalogue index pulled down, decompressed and opened read-only | `db/prospector-2026-08-20.db.gz`, 975,480 B → 3,100,672 B; `PRAGMA integrity_check` = `ok`; 1 table, `dossiers`, **3,608 rows**. Second angle from `prospector-engine` itself: `LIVE_ROWS 3608` — exact agreement. F-07 stays ○: one source restored by hand is not "every backup, by a machine, scheduled" |
| 2026-08-20 | P5 / #355 | the engine can page the founder from a container — in-repo Telegram sender, no `$HOME` dependency | commit `47212af5`; 18 tests, 5 mutations caught |

---

## 9. Notes — the standard the founder set, 2026-08-20

Captured as notes, in his words, at the moment he set them. Nothing here is designed yet. Each
note says where the work already has a home, or that it has none, so that the next session can
tell a decided thing from an undecided one.

**The bar.** *"this is once in a lifetine ooprtunity"*, *"we cant do repeat this project"*, *"so
needs nainun craft"*, *"to ahcive gight level goals"*, *"seanless evryting"*. Read together: there
is no second attempt, so a thing built twice is a thing that cost the estate its one run at this.
This is the reason the programme prefers extending a mechanism over adding one, and the reason a
guard is repaired rather than relaxed when a change blinds it.

**The target stack.** *"a low nintennace stack wheere everyhting works and slef heals and is
obvered realtine reparing"*. Four properties, and they are not the same property:

| Property | What it means here | Where it stands |
|---|---|---|
| Low maintenance | no step that needs a human on a schedule | 31 launchd jobs today; Dagu decided, not landed |
| Works | the money path and the engine both serve | shop measured 200; engine moat blind, founder-blocked |
| Self-heals | the system corrects itself with no agent involved | partial: half-open probes, DEFER + resume, breakers |
| Observed in real time, repairing | a human sees it go red, and something acts | **the weakest of the four — see the alerting note** |

Self-healing already has a precedent to copy rather than invent: `health.py` half-open probes let
exactly one caller re-test a benched brain, so recovery is automatic and costs one call. The gap is
not the pattern. It is that the pattern is applied to brains and to almost nothing else.

**Alerting — researched, decided, not landed.** The founder: *"our notiong nand elerting is poor ll
round"*, *"did we research this"*. Yes, and the audit's own sentence is his complaint:
`docs/STACK_AUDIT.md` — *"the estate has many bespoke observers and no dead-man's switch"*.
Decided 2026-08-19: Healthchecks for job liveness, Gatus for endpoint reachability, both on
`prospector-engine`. Neither has landed. Issue #355 is open and names the live defect: the sink is
a file in `$HOME` and the Fly container has no `$HOME/.hermes`, so `alerts.py` has five sinks and
none of them reach a human. Measured 2026-08-20: 18 `moat_blind` criticals in
`store/scheduler/alerts.jsonl`, none delivered.

**Proposed rule, for the founder to accept or reject.** *A rail that cannot go red where a human
sees it is not a rail.* Every alert leaves the machine through one bus, and a job that stops
running triggers silence-detection rather than merely failing to log. It is testable, which is the
point: a test can assert every key in `TELEGRAM_KEYS` has a reachable off-machine sink in the
environment the code is running in, so this cannot regress into a file again.

**Testing the founder named, and where each one lives.**

| Kind | His words | Home today |
|---|---|---|
| Chaos | *"chaos testing and eend to end tests also"* | **M7**, with a done-when and three starting scenarios. Tooling decided: Pumba, Toxiproxy |
| End-to-end | same | **M8** — no proof today that a buyer can buy. Playwright already in the repo |
| Stress / load | *"stress testing"* | **NO GAP OWNS THIS.** Assets exist and are unclaimed: `scripts/load_gate.py`, `tools/corpus/load.py`. k6 was considered in §5 and deferred |
| Security | *"secitory etsing"* | **NO GAP OWNS THIS.** `docs/ARCHITECTURE_SECURITY_BASELINE.md` measures state; nothing attacks it. `docs/personas/security.md` exists |

Two of the four had no owner when this note was written. **M14 (stress) and M15 (security) were
written into §3 the same day.** M14 starts from nothing — there is no load generator in the estate,
and the two files a filename search suggested were assets turn out to be a machine-fitness probe
and a corpus loader. M15 starts from more than nothing: bandit, dep_advisory and `npm audit`
already run in CI, so what is missing is anything that attacks the system while it is running.

**Tracking.** *"we ned trackinng etrene"*, and earlier *"dont lose track of your project work"*,
*"you re not tracing context"*. The rule that follows: a thread that is not on disk does not
survive a compaction, so the ledger in §8 and the gap list in §3 are the record, and a session's
own context is not. Every shipped item gets a ledger line with its receipt, and anything parked
gets the four lines LAW 16 requires — the question, what was established, the next command, and
why it was put down.

---

## 10. The target platform — what it looks like when this is done

Founder, 2026-08-20, verbatim: *"i dont have a wwhole stack or architectuure or platfon plan. i
dont knoww what th eplatfornwill look like when we are done. this si a standadisation,
cosilidaation porject also"*, and *"we qre just stuck and nocler guidanc"*, and *"fightong low
level fires a;l dat"*.

He is right, and §0–§9 above are the evidence. They grade what is BROKEN. Nothing in this document
said what the finished thing IS, so every session picked up whichever gap was loudest and the
programme reads as a fire queue. This section is the target. §11 is the register of requirements
that reaches it. Neither existed before 2026-08-20.

### 10.1 The one idea

**Ten planes. Each plane has exactly one contract, one implementation per provider, and one drill
that proves it.** A plane is swappable when a new provider means writing one adapter against a
written contract, and nothing else in the estate learns the provider's name.

That is already true for exactly one plane — compute — and it is why compute is the only part of
this estate that can currently move. `deploy/PORTABILITY.md` writes down eleven verbs,
`deploy/targets/*.sh` implements them per provider,
`tests/unit/test_every_deploy_target_implements_the_contract.py` fails if an adapter drops a verb,
and `scripts/engine_failover.py:731` DISCOVERS the adapter list from the filesystem so no second
list can drift. Four adapters exist, and nothing outside that directory contains the word
`kubectl`, `fly` or `launchctl`.

**The whole programme is: do to the other nine planes what was already done to compute.** Not ten
different designs. One pattern, applied ten times.

### 10.2 The ten planes, and the state of each

| # | Plane | What it carries | The contract that makes it swappable | Today |
|---|---|---|---|---|
| **P1** | **Compute** | engine, consumer, CI runners, searxng | `deploy/PORTABILITY.md` — 11 verbs, 4 adapters | **done in shape, unproven in use.** Only `fly` has ever run. §10.4 |
| **P2** | **State** | catalogue, ledger, dossiers, packs, scheduler files | `config.store_root()` is the single resolver | **partial** — one resolver, no named datastore list, no proven restore (M4, M11) |
| **P3** | **Secrets** | provider keys, bot tokens, the signing key, Stripe | none written | **absent** — `docs/SECRETS_PROGRAM.md` has a risk register, no contract, no fetch path (M2) |
| **P4** | **Identity** | mumchimp.com, DNS, TLS, the Stripe account | `deploy/dns/mumchimp.com.zone` exists; no verb set | **manual** — the one plane with no substitute (M9) |
| **P5** | **Observability** | logs, alerts, metrics, the tick digest | alert keys are declared; log shipping is not | **partial** — alerts reach a phone since #355; logs die with the box (M10) |
| **P6** | **Work** | schedules, drains, backups, rotations, watchdogs | 5 launchd plists + `deploy/engine/periodic.sh` | **two implementations, no contract** — laptop plists and container cron share no definition |
| **P7** | **Money** | Stripe, prices, the fulfilment fence | `bridge.py` mints price and catalogue row together | **locked to one provider** — no adapter (M3). Largest single item |
| **P8** | **Delivery** | commit → gate → CI → image → release | POPDD gate + `.github/workflows` + `t_release` | **works, single-provider** — GitHub Actions only |
| **P9** | **Control** | the ops console: every button a human presses | `prospector/ops/console_api.py` | **partial** — per-task buttons, no continuity panel (M5, B4, B5) |
| **P10** | **Knowledge** | runbooks, decisions, the estate map, this document | none | **the consolidation problem.** 79 files in `docs/`. §10.5 |

### 10.3 What "done" looks like, in one paragraph a person can hold

One console page lists every plane and its current provider. Beside each is a green tick a machine
put there, from a drill that ran this week. Changing any plane's provider is: write the adapter,
run the drill, press the button. The thirty-minute move is that page, ten times, with the order and
the dependencies already encoded — not ten terminals and a person remembering. Every number on it
comes from a probe, never from a document. A new laptop is: clone, fetch secrets, run the probe,
and the page goes green.

### 10.4 The k8s adapter — answering the direct question

Founder, 2026-08-20: *"the k8's adapter how is it being used?"*

**It is not being used. Nothing calls it, and it has never run.** The measured state:

- `deploy/targets/k8s.sh`, 269 lines, implements all twelve verbs (`t_name t_preflight t_provision
  t_secrets t_release t_start t_stop t_exec t_put t_pack t_logs t_health`). Written 2026-08-20 in
  answer to your earlier question, by copying the shape of `sshdocker.sh`.
- It is already a legal destination with no further wiring, because `deploy_targets()`
  (`scripts/engine_failover.py:731`) globs `deploy/targets/*.sh` rather than holding a list, and
  `deploy/decommission.sh:35` sources by the same convention. `deploy/cutover.sh --to k8s` resolves
  today.
- What grades it is `tests/unit/test_every_deploy_target_implements_the_contract.py`, and that test
  grades **shape, not behaviour**: every verb present, spelled the way `deploy/PORTABILITY.md`
  spells it. It cannot tell whether any verb works.
- It covers k3s, k0s, MicroK8s, kind, EKS and GKE identically, because the adapter only ever talks
  to `kubectl`.

**The cheap thing nobody has done:** `kubectl` is installed on this laptop and there is a live
context, `docker-desktop`. A real k8s drill costs nothing and needs no cloud account. That is
deliverable **D-P1.3** in §11, and it is the fastest way to turn P1 from shape into proof.

**What k8s does NOT solve, and must not be adopted for:** it is a compute substrate, so it touches
P1 and nothing else. It gives no secrets contract, no state restore, no DNS verb, no money adapter.
`docs/STACK_AUDIT.md` §5 already ruled that the eleven-verb contract stays and neither Kamal nor
Nomad gets adopted; k8s joined that contract instead of replacing it, which is why choosing it
later costs one environment variable rather than a migration.

### 10.5 Standardisation and consolidation — the part that was never named

Founder: *"this si a standadisation, cosilidaation porject also"*. It is now a first-class goal
with its own requirements (N-09..N-12 in §11), and here is the measurement that justifies it.

**`docs/` holds 79 markdown files.** Four are runbooks under three different names
(`docs/RUNBOOKS.md`, `docs/CI_DEBUG_RUNBOOK.md`, `docs/AMBITION_LANES_RUNBOOK.md`,
`store_platform/GO_LIVE_RUNBOOK.md`). At least nine are dated snapshots never folded back
(`NEXT_MOVE_2026-08-14/15/17`, `ENGINE_AUDIT_2026-08-10`, `BRANCH_CLEANUP_2026-08-09/17`, others).
Platform architecture is spread across `PLATFORM_MANIFESTO.md`, `PLATFORM_KERNEL_PLAN.md`,
`PLATFORM_PORTABILITY_AUDIT.md`, `STACK_AUDIT.md`, `RELIABILITY_ARCHITECTURE.md`,
`ARCHITECTURE_SECURITY_BASELINE.md` and this file.

That is the mechanism behind *"we qre just stuck"* and *"fightong low level fires a;l dat"*. With no
single place that says what the platform is, a session opens the loudest document and works the
loudest gap. Seventy-nine documents is not a documentation problem, it is the absence of a spine — and
the fix is not deletion, it is **one spine plus a rule about where a new fact may land** (N-11).

Three duplications outside `docs/` that the same rule has to reach: two job definitions with no
shared contract (P6 above), two alert senders that had to be reconciled by hand for #355, and three
estate inventories that never meet (M1).

---

## 11. The requirements register — functional, non-functional, and the deliverables that satisfy them

Founder, 2026-08-20, verbatim: *"you entioned hernes, are you aware that is not just hernes, its
the whole progran platfron/stack autontio/portability/nigration/ and inprovenents. i dont even thik
you have conpiled a;l functinal and non functionals into deliverables"*, then *"so isecrets
nangents"*, then *"ops integratios, runbbos docunettion"*.

He was right that it had not been compiled. §0 held eight acceptance criteria in his words and §3
held fifteen gaps in mine, and neither is a requirements register: a gap says what is broken, not
what the system must do. This section is the register. It is the contract for the programme —
everything in §6 delivers a row here, and a row with no deliverable is a hole stated out loud
rather than a hole nobody noticed.

**Hermes is one consumer of P3 and P6, not a subsystem of its own.** The correction is taken: the
scope is the whole platform and stack. Hermes appears in this register only where it holds
credentials (F-09) and jobs (F-18), same as any other component.

### 11.1 How to read a row

Every requirement has an **ID**, a **statement in the imperative**, the **drill that proves it**
(not a document that claims it), and the **deliverable** that builds it. A requirement is met when
its drill has run green **and is scheduled**, never when someone has written that it works. That
rule is why the Today column in §10.2 is mostly "unproven" rather than "done": four of the ten
planes have code that has never been executed against the thing it exists to control.

`Ph` is the phase in §6. `St` is state: **✅** proven by a drill that runs, **◐** built but never
run, **○** not started, **⛔** blocked on a decision in §7.

### 11.2 Functional requirements — what the platform must DO

#### P1 Compute

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-01 | Every runtime component moves to any provider by writing one adapter against `deploy/PORTABILITY.md`, and nothing else in the estate learns the provider's name | contract test + a real move | D-P1.1 | 4 | ◐ |
| F-02 | A whole move runs end to end with no human in a terminal | one recorded cutover | D-P1.2, D-P9.2 | 4 | ○ |
| F-03 | The old provider is decommissioned only after the new one is proven serving | `deploy/decommission.sh` refuses without proof | D-P1.4 | 4 | ◐ |
| F-39 | **THE WHOLE STACK MOVES, not compute alone.** Every one of the ten planes has a deliverable on the target substrate — state, secrets, identity and DNS, observability, jobs, the money path, delivery, control and the knowledge base — with no Fly-specific and no laptop-specific piece left behind. Founder, 2026-08-21: *"the whole stack"* | the ten-plane bring-up: **each plane's own drill run on the new substrate**, not merely a pod that starts. A move where the engine serves and the jobs, the alerts or the money path did not come with it is a failed move, not a partial one | D-P1.5 | 6 | ○ |
| F-40 | **The same manifests bring the estate up on AWS, on GCP, on Fly and ON-PREMISES**, with no per-substrate fork. Founder, 2026-08-21: *"this gold standard can be ported to any provider... provider agnostic... even onprem also"* | the bring-up run on a managed cloud cluster and on an on-premises cluster, and the two rendered manifest sets diffed to empty | D-P1.6 | 6 | ○ |
| F-04 | At least two substrates are proven, not one | a drill on k8s and on sshdocker | D-P1.3 | 4 | ○ |
| F-45 | **REPEATABLE: the same command run twice from nothing produces the same estate.** Founder, 2026-08-24: *"fully autonated and repetable"*. A bring-up that works once is a lucky run; the requirement is that it works the second time on a machine that has never seen it, with no step a person remembers to do | `deploy/rehearse_cluster.sh down && deploy/rehearse_cluster.sh all` twice in succession, and the two runs' resource inventories diffed to empty. A drill that passes only on a warm machine fails this row | D-P1.7 | 1 | ○ |
| F-46 | **EXHAUSTIVE CHAOS: every failure class is injected and survived, and the list is countable rather than "we tested some failures".** Founder, 2026-08-24: *"ehaustive chaos testing"*. A chaos suite that only kills pods proves the one failure Kubernetes was always going to handle | each F-46x row below passes in one scheduled run, and the run publishes how many classes were injected against how many exist | D-P1.8 | 2 | ○ |
| F-46a | **Process loss** — a workload is killed and the substrate restores it without a human, to a measured recovery time | `deploy/rehearse_cluster.sh heal`, which times `--for=condition=Available` on the deployment rather than on a pod name | D-P1.8 | 1 | ◐ |
| F-46b | **Node loss** — a node is removed while serving and the work is rescheduled inside the stated RTO | drain and delete a node mid-request, measure the gap in a continuous probe | D-P1.8 | 2 | ○ |
| F-46c | **Disk exhaustion** — a volume fills and the money rail refuses rather than writing a truncated ledger | fill the volume to 100% under load and require a refusal, not a partial write. Shares F-08a's truncation logic | D-P1.8 | 2 | ○ |
| F-46d | **Network partition** — the store and the workload are severed and nothing double-writes on rejoin | partition, write to both sides, rejoin, and require exactly one writer's rows to survive | D-P1.8 | 3 | ○ |
| F-46e | **Poisoned deploy** — a manifest that would break serving is refused before it lands, or rolled back automatically after it does | push a deliberately broken image tag and require the previous version to still be serving at the end | D-P1.8, D-P8.3 | 2 | ○ |
| F-47 | **The substrate refuses work that breaks the estate's standards, and admits work that does not.** A fence proven only in the refusing direction has never been shown safe to install — LAW 38 grades a guard that blocks correct work as an outage, not a false positive | `deploy/rehearse_cluster.sh policy`: the refusals the policy set must make and the admissions it must not block, both halves in the same run, and the run fails if either half fails. **Now 26 policies, not 7** — see F-51 | D-P1.9 | 1 | ◐ |
| F-51 | **THE STANDARDS ARE SOMEBODY ELSE'S TO MAINTAIN, not ours to remember.** Founder, 2026-08-24: *"not write custon scripts for production cluster"*, *"never reinvent the wheel"*, *"reserch what always works"*. Six of seven hand-written Kyverno policies restated something the Kyverno project already publishes; keeping them meant maintaining a private fork of a public standard, and it also meant the estate never got the rules it had not thought of | `kubectl kustomize deploy/k8s/overlays/production \| grep -c '^kind: ClusterPolicy'` returns **26**, of which 24 are upstream at a pinned SHA and 2 are estate-specific. `deploy/k8s/policies/RETIRED.md` maps each retired rule to its replacement. **Measured 2026-08-24** | D-P1.9 | 1 | ✅ |
| F-52 | **THE STANDARD IS ENFORCED, NOT WRITTEN DOWN.** Founder, 2026-08-24: *"we dont eforce stadard adbest practices... we need to be ready fron day 0"*. A written standard is a thing people agree with and then work around at 2am. Each gate grades the BUILT output, never the source, because kustomize patches and remote bases mean the file on disk is not what reaches the cluster | `.github/workflows/k8s-manifests.yml`: every policy enforces and none audits; staging and production enforce identical policy; the namespace carries PSA `restricted`; every remote kustomize resource is pinned to a commit SHA. **Each proved BOTH ways locally before it was committed** — the identical-policy gate refused a softened build and a build with a policy removed; the pinning gate refused `?ref=main` and was rescoped after it wrongly refused this repo's own `repoURL` | D-P1.9 | 1 | ✅ |
| F-53 | **TWO CLUSTERS, ONE MANIFEST SET, AND IDENTICAL POLICY IN BOTH.** Founder, 2026-08-24: *"and we need staging also"*, *"staging and prod cluster"*. A namespace is not an environment: it shares an API server, a scheduler and every cluster-scoped policy with the thing it is meant to be rehearsing. A staging cluster with softer rules admits manifests production refuses, which converts a caught problem into an outage — the one failure staging exists to prevent | `deploy/k8s/overlays/{staging,production}` both build, and the CI gate diffs their policy sets to empty. **The manifests are proved; NEITHER CLUSTER EXISTS.** Both are rented boxes, which is money leaving the account and the founder's decision under LAW 5. See M13 | D-P1.2 | 1 | ◐ |
| F-54 | **PROMOTION IS A COMMIT, AND THERE IS NO OTHER PATH.** CI builds an image tagged with the commit SHA, never a moving tag, because you cannot roll back to a tag that moves. Argo CD syncs staging with nobody deploying; promotion to production edits one image tag in `overlays/production`, which makes the git history the deployment audit log | `deploy/k8s/argocd/applicationset.yaml` with `selfHeal: true` and `prune: true`, plus Argo Rollouts for the canary. **Nothing here has run.** Depends on F-53 | D-P8.1 | 1 | ○ |

#### P2 State

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-05 | Every datastore in the estate is named in one machine-readable inventory, generated by a probe | probe output diffed against reality | D-P2.1 (M11) | 1 | ○ |
| F-06 | Every named datastore is backed up off-machine on a schedule, and a missed backup alerts | the weekly drill + a `backup_stale` alert key | D-P2.2 | 0 | ◐ |
| F-07 | Every backup has been restored at least once into a scratch location, by a machine | restore drill, scheduled | D-P2.3 (M4) | 2 | ○ |
| F-08 | State moves with compute inside the same cutover, to a stated RPO | cutover drill measures bytes and lag | D-P2.4 | 4 | ○ |
| F-08a | **Every copy of a money file is proven COMPLETE against its source before it is allowed to replace the previous copy** — size equal to the source, and the format opened and read, never a byte count | the truncation drill: cut a transfer mid-file and require the copy to be refused | D-P2.5 | 0 | ○ |

#### P3 Secrets and configuration — a first-class plane, at the founder's instruction

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-09 | Every secret in use is named in one inventory: what it is, who issues it, who consumes it, where it lives, when it was last rotated | probe enumerates consumers from source, not by hand | D-P3.1 | 1 | ○ |
| F-10 | A new machine fetches every secret it needs without a human reading a value out of anything | new-laptop drill from a clean clone | D-P3.2 (M2) | 2 | ⛔ |
| F-11 | A secret is rotated in one action, everywhere it is consumed, with the old one revoked | rotation drill on one low-risk key | D-P3.3 | 2 | ○ |
| F-12 | No secret can reach git, a log line, argv or shell history — refused by a machine, not by care | a guard in the commit gate + a test | D-P3.4 | 1 | ◐ |
| F-13 | The signing key has an off-machine escrow with a tested restore | restore the key from escrow into a scratch tree | D-P3.5 | 0 | ◐ |
| F-41 | **Every configuration value the estate reads at runtime is named in one inventory**, generated by a probe from source — not only secrets, but endpoints, flags and tuning knobs | probe output diffed against a live dump of every target | D-P3.6 | 1 | ○ |
| F-42 | **No runtime value is defined in two places.** One value, one declared home, rendered outward to every target | a drift probe that fails when a target's live value differs from its declared home | D-P3.7 | 1 | ○ |
| F-43 | **A new environment receives its complete non-secret configuration in the same one command that fetches its secrets** — new laptop, new cluster, new provider, no human reading a value | the new-laptop drill from a clean clone (shares F-10's drill) | D-P3.2 (M2) | 2 | ⛔ |
| F-44 | **The encrypted secret store is committed and proven restorable from `origin/main`**, so no secret depends on an uncommitted working file surviving on one disk | decrypt from `origin/main` into a scratch tree and diff the NAME list against `deploy/secrets.required` | D-P3.7 | 0 | ○ |

`docs/SECRETS_PROGRAM.md` holds the risk register R-K1..R-K5 and stays the detail. This register
holds the requirement and the deliverable; the two are cross-linked and must not restate each other.

#### P4 Identity — domain, DNS, TLS, accounts

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-14 | DNS is declared as a file in the repo and applied by a verb, never typed into a web console | apply the zone to a test subdomain | D-P4.1 (M9) | 1 | ◐ |
| F-15 | A DNS cutover is one command with a stated TTL cost, and is reversible | drill on a test subdomain, timed | D-P4.2 | 4 | ○ |
| F-16 | TLS is issued and renewed with no human | expiry probe + renewal drill | D-P4.3 | 3 | ○ |
| F-17 | Registrar, account recovery and billing owner are recorded with a tested recovery path | a person completes the path once | D-P4.4 | 1 | ⛔ |

#### P5 Observability

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-18 | Every alert that matters reaches a human off the machine that raised it | one real alert lands on the founder's phone | D-P5.1 (#355) | 3 | ◐ |
| F-19 | Every declared alert key has a reachable sink — a rail that cannot go red where a human sees it is not a rail | `test_every_telegram_key_has_a_reachable_sink` | D-P5.1 | 3 | ✅ |
| F-20 | Logs are shipped off the machine that made them and survive its destruction | destroy a machine, read its last hour | D-P5.2 (M10) | 3 | ○ |
| F-21 | One probe answers "is the platform serving" across all ten planes | the probe, run on a schedule | D-P5.3 | 3 | ○ |
| F-22 | The migration itself is observable step by step while it runs | live progress in the console during a drill | D-P9.2 (B5) | 3 | ○ |

#### P6 Work — jobs and schedules

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-23 | Every scheduled job is declared once, in one format, and rendered per substrate — launchd, cron, k8s CronJob | one declaration renders all three; a test diffs them | D-P6.1 | 2 | ○ |
| F-24 | A job that stops running raises an alert without anyone noticing it stopped | kill a job, wait for the alert | D-P6.2 | 3 | ○ |
| F-25 | Jobs move with the compute in the same cutover | cutover drill checks every job is running on the far side | D-P6.3 | 4 | ○ |

#### P7 Money

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-26 | The payment provider sits behind an adapter of the same shape as compute | a second adapter exists, even if unused | D-P7.1 (M3) | 4 | ⛔ |
| F-27 | A buyer completes a purchase end to end on whichever substrate is serving | synthetic purchase drill (M8) | D-P7.2 | 5 | ○ |
| F-28 | The fulfilment fence cannot be crossed by a price and a catalogue row that disagree | `bridge.py` mints both; test pins it | — | — | ✅ |

#### P8 Delivery

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-29 | A commit reaches production with no human step after review | a merge that lands in the running image | D-P8.1 | 3 | ◐ |
| F-30 | The running image names the commit it was built from | `/app/GIT_SHA`, read by `scripts/live_checkout.py` | — | — | ✅ |
| F-31 | The pipeline itself can move to another CI provider | render the pipeline for a second provider | D-P8.2 | 5 | ○ |
| F-48 | **DEPLOYMENTS: the declared state in git is what runs, and the substrate reasserts it without being asked.** Founder, 2026-08-24: *"with deploynents also"*. F-29 gets a commit to production once; this row is the standing property that it stays there | change a live resource by hand and require it to be reverted with no human step, timed. This is Argo CD `selfHeal: true`, chosen over Flux because it also ships a UI a stranger can open | D-P8.3 | 2 | ○ |
| F-49 | **A deploy that would stop the shop serving does not stop the shop serving.** The rollback is automatic and the previous version keeps taking money throughout | the F-46e poisoned-deploy drill, measured from the customer's side rather than from the cluster's | D-P8.3 | 2 | ○ |
| F-50 | **No human has credentials to deploy by hand**, so the pipeline is the only path and cannot be bypassed under pressure at 2am | no kubeconfig with write access exists outside the deploy identity, proven by a probe that tries and is refused | D-P8.4 | 4 | ○ |

#### P9 Control — the ops console

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-32 | Every operation in this document has a console button; no runbook step is terminal-only | audit: every runbook step maps to a button | D-P9.1 (M5, B4) | 3 | ○ |
| F-33 | A running migration shows live per-step progress, elapsed and remaining | watch a drill from the console | D-P9.2 (B5) | 3 | ○ |
| F-34 | The console probes and audits an arbitrary system, not only prospector | point it at Hermes and get a plane table | D-P9.3 (B7, B8) | 6 | ○ |

#### P10 Knowledge — runbooks, docs, ops integrations

| ID | Requirement | Proven by | Deliverable | Ph | St |
|---|---|---|---|---|---|
| F-35 | One spine document names the platform and every other document is reachable from it | a link check that fails on an orphan doc | D-P10.1 | 1 | ○ |
| F-36 | Every runbook step is either executable or names the exact command that is | a linter over the runbooks | D-P10.2 | 2 | ○ |
| F-37 | Every third-party integration is named with its owner, credential, blast radius and substitute | the integration inventory, probe-generated | D-P10.3 | 1 | ○ |
| F-38 | A fact lives in exactly one document, and the rule is enforced | duplicate-claim check in the gate | D-P10.4 (N-11) | 2 | ○ |

### 11.3 Non-functional requirements — how well

| ID | Requirement | The number | Proven by | St |
|---|---|---|---|---|
| N-01 | **Speed** — the whole move completes inside the founder's window | **30 minutes**, wall clock, measured | timed drill (B2) | ○ |
| N-02 | **Availability** — no customer-visible downtime during a move | **0 failed requests** across the cutover | synthetic buyer during the drill (B3) | ○ |
| N-03 | **Durability** — bounded data loss | **RPO ≤ 15 min, RTO ≤ 30 min** (proposed, needs your ruling) | restore drill measures both | ⛔ |
| N-04 | **Self-healing** — components recover without a human | every failure class has a named recovery, or is alerted | chaos drill (M7) | ○ |
| N-05 | **Low maintenance** — routine operation needs no agent | **0 manual steps/week** in steady state | count them for four weeks | ○ |
| N-06 | **Security** — least privilege, no secret in the clear, every access auditable | 0 secrets in git/logs/argv; every key has an owner | the F-12 guard + the secrets probe | ◐ |
| N-07 | **Cost** — bounded and measured, no orphaned resources | spend ledger + a zero-orphan sweep | `docs/COST_PROGRAM.md` measurements | ◐ |
| N-08 | **Reusability** — nothing prospector-shaped in the migration tooling | it runs against Hermes unmodified (B7) | D-P9.3 drill | ○ |
| N-09 | **Standardisation** — one contract per plane, ten contracts total | 10/10 planes have a written contract; today **1** | count in §10.2 | ○ |
| N-10 | **Consolidation** — no two implementations of one capability | today: 2 job systems, 2 alert senders, 3 inventories | duplicate audit, scheduled | ○ |
| N-11 | **One place per fact** — a fact lives in one document | today **79** documents, no spine | D-P10.1, D-P10.4 | ○ |
| N-12 | **Auditability** — every claim on the console comes from a probe, never from a document | 0 hand-written status strings | the console's own test | ◐ |
| N-13 | **Provability under stress** — load, chaos and security testing exist and run | the three suites, scheduled | M14, M15, M7 | ○ |
| N-14 | **Portability breadth** — more than one destination is proven, and the set is not a shortlist the estate is comfortable with | **≥ 2 substrates** with a green drill before the bar is met, and the target set is **AWS, GCP, Fly, on-premises**; today **1** | D-P1.3 | ○ |
| N-15 | **Config sprawl** — configuration lives in one declared place per value, not scattered across checkouts, deploy files and consoles | **0 drifted keys**; today the census is **261 env-ish files across 114 trees**, 6 `[env]` blocks in Fly configs, 43 top-level keys in `config.yaml`, 25 launchd plists with their own environment, 7 GitHub Actions variables and 13 Fly apps holding their own secret sets | the F-42 drift probe | ○ |

### 11.4 Coverage — what this register makes visible

Counting the rows above: **45 functional and 15 non-functional requirements — 60 in all. 3 are
proven. 11 are built but never run. 41 are not started. 5 are blocked on a decision only you can
make** (§7). Counted by command, never asserted — and the command carries no line range, because
the last one went stale the first time a row was inserted above it:
`grep -cE '^\| F-' docs/MIGRATION_AND_DR_PROGRAM.md` and the same for `N-`.

Three of those blocks stop whole planes rather than single deliverables, which is why they are the
most valuable thing you can clear:

1. **Where secrets live so a new machine can fetch them** blocks F-10, and F-10 blocks the entire
   new-laptop path. Cloud KMS is ruled out by name, so the shortlist is: an encrypted file in a
   private repo with the age key in escrow; a password-manager CLI; or Fly/provider secrets plus
   one bootstrap credential held off-machine.
2. **Which second provider proves portability** blocks F-04 and N-14. The free answer is already on
   this laptop: `docker-desktop` k8s, which costs nothing and needs no account.
3. **RPO and RTO** (N-03) are unset, and every backup and restore deliverable is graded against
   numbers that do not exist yet.

**The first drill instrument exists, and it is nearly free.** F-08a asks whether a copy is complete
against its SOURCE. For any gzipped copy that is one ranged GET of four bytes: the last four bytes
of a gzip stream are ISIZE, the uncompressed length as a little-endian uint32, so the copy's true
size is readable without downloading or decompressing it. Against the live source size from
`fly ssh console -a prospector-engine -C "wc -c /data/store/prospector.jsonl"` that is two angles
that fail differently — one number written by gzip on the Fly box at compress time, one read from
the filesystem now.

Run on 2026-08-20 against `prospector-backup/ledger/prospector-2026-08-20.jsonl.gz`: ISIZE
413,570,301 B against a live source of 414,063,171 B, so the off-Fly copy holds **99.88%** of the
money file. The 492,870 B shortfall is append lag — the ledger measured appending at 437 B/s over a
120s window, which puts 492,870 B at about nineteen minutes of writes against a snapshot roughly
sixteen minutes old. A truncation does not look like this; the broken standby copy the same day was
6.2% of its source.

This does not turn F-08a green. The requirement is that a short copy is REFUSED, and nothing refuses
one yet; a measurement that has to be run by hand is an instrument, not a drill. What it does settle
is that the money file has a real off-Fly copy today, written under dated keys by
`scripts/backup_store.py:450` so a truncation cannot overwrite the good ones.

**And the restore side is no longer theoretical.** Until 2026-08-20 every restore claim in this
programme rested on `scripts/restore_drill.py` passing against a LOCAL backup directory — which
proves the parser, not the survival of the estate. The first pull from off-machine storage ran that
day: `db/prospector-2026-08-20.db.gz` fetched from R2 (975,480 bytes), decompressed to 3,100,672
bytes, opened through a `file:...?mode=ro` URI so the copy could not be mutated by reading it.
`PRAGMA integrity_check` returned `ok`. It holds one table, `dossiers`, with **3,608 rows**.

The second angle is what makes it a proof rather than a reading: `prospector-engine` was asked the
same question about its own live database and answered `LIVE_ROWS 3608`. Two instruments that fail
differently — a gzip stream written to R2 at snapshot time, and a live SQLite count taken now over
the network — agree exactly.

**F-07 stays ○ anyway, and that is the point of the glyph.** What ran was one source, restored once,
by hand, by me. The requirement says every backup, by a machine, on a schedule. The distance between
"it worked when I did it" and "it works when nobody does it" is the whole of this programme.

### 11.5 The rule that keeps this register honest

A requirement is met when its drill has run green **and is scheduled**. Not when the code exists,
not when a test passes on shape, not when a document says so. Eleven of the rows above are `◐` —
built and never run — and that column is the whole reason the programme felt like progress while
the bar stayed unmet.

---

## 12. How much of this can sensibly move to Kubernetes

Founder question, 2026-08-20: *"questios neeeds answered how easy to nove everything or as nuch as
nakes sese to k8's"*.

"Move to k8s" is ten questions wearing one name, so the answer is plane by plane. Kubernetes is a
compute substrate with an ecosystem attached. It absorbs some planes whole, half-absorbs others,
and has no opinion at all about three.

| Plane | Absorbed | What k8s gives | What stays ours |
|---|---|---|---|
| P1 Compute | **fully** | Deployment, Service, image pull. `deploy/targets/k8s.sh` already generates its own manifests inline (`t_provision`, `t_start`) — no Helm, no chart to maintain. | Nothing. The one plane k8s answers end to end. |
| P2 State | half | A PersistentVolumeClaim holds `store/`. The adapter asks for `ReadWriteOnce` deliberately, which is also what holds one writer on the ledger. | Backup, offsite copy, restore. A PVC is a disk, not a backup. |
| P3 Secrets | half | A `Secret` delivers `KEY=VALUE` into the pod, loaded via `--from-env-file` so no value reaches `ps` or a history file. | The hard half: a k8s Secret is base64, not encryption, and it does not say where secrets live so a NEW machine can fetch them. Still blocked on the founder. |
| P4 Identity | half | Real ground: ingress for routing, cert-manager for TLS issue and renewal, external-dns to write records where the registrar has an API. | The registrar account, the domain, and the recovery path to both. |
| P5 Observability | mostly | The largest single win: a stack that already knows how to scrape pods, replacing hand-rolled shipping and scraping. | Paging a human. Already solved in-repo (`prospector/scheduler/telegram_sender.py`) and needs no cluster. |
| P6 Work | **fully** | `CronJob` replaces the launchd plists one for one, with history and retries. The long-running tick stays a Deployment. | Nothing structural. |
| P7 Money | **not at all** | Nothing. The payment provider is a third party reached over HTTPS from wherever compute sits. | All of it. Portability here is `bridge.py`'s own contract. |
| P8 Delivery | half | The storefront is a container, so it runs as a Deployment. | The domain and edge in front (P4) and the catalogue state (P2). |
| P9 Control | half | The console runs as a workload. Nothing more. | Every button. The console is only as portable as the verbs it calls. k8s does not make a missing verb appear. |
| P10 Knowledge | **not at all** | Nothing. Runbooks and docs live in git. | All of it. |

**Two planes move whole, five move half, three do not move at all — and the half left behind is the
expensive half every time.** k8s absorbs compute and scheduled work completely and takes a real
bite out of observability and TLS. It does nothing for the three questions actually blocking this
programme: where secrets live so a new machine can fetch them, who can recover the domain, and how
state is restored. Adopting it does not shorten §11.

**What that makes it worth: a portability proof, not a production migration.** A second substrate
genuinely unlike Fly is the cheapest way to find out whether the eleven-verb contract is real or
only well-written, and `kubectl config get-contexts` shows `docker-desktop` live on this laptop, so
the proof costs nothing and needs no account. That is deliverable **D-P1.3** and it turns the first
`◐` in §11 into a `✅`.

### 12.1 Full portability, not just compute — the founder's additional requirement

Founder, 2026-08-21: *"full protabui;ity? not just conpute"*, *"cloud and onpren"*, *"as additonal
requirent"*, *"for future plans"*. Recorded as **F-39** and **F-40** in §11.2. This subsection says
what the words cost, because the table above is a statement about today and the requirement is a
statement about the target.

The table above is the honest current answer and it is **compute-mostly**: two planes whole, five
half, three not at all. F-39 says that is not the target. The gap is not a Kubernetes gap — it is
the five halves and the three noes, and k8s has no opinion about any of them. What each one needs:

| Plane | The half k8s does not carry | What F-39 requires us to build |
|---|---|---|
| P2 State | a PVC is a disk, not a backup | the backup, offsite copy and **restore** run as `CronJob`s in the cluster, proving themselves there — not from a laptop |
| P3 Secrets | a `Secret` is base64, and it does not say where secrets come FROM | a bootstrap path a NEW cluster can pull from with one credential. **Still blocked on you** (§7) |
| P4 Identity | the registrar account and the recovery path | external-dns plus a written, drilled registrar recovery — the account is not a manifest |
| P5 Observability | paging a human | already solved in-repo and cluster-independent; it just has to be wired into the cluster's own alerting |
| P8 Delivery | the domain and the edge in front | follows P4; the storefront container itself is trivial |
| P9 Control | every button | each console verb must exist in the repo. **k8s does not make a missing verb appear** |
| P7 Money | everything | `bridge.py`'s own contract. A third party over HTTPS is equally reachable from anywhere, which is why this plane is portable already |
| P10 Knowledge | everything | git. Portable by construction |

**F-40 is the part that is easy to state and easy to get wrong.** "Cloud and on-prem" is not two
deployments, it is *one* set of manifests that must not fork. The three places a fork always starts:
storage class names, load-balancer and ingress class, and how a `Secret` is populated. If those are
parameters the drill is honest; if they are two files, we have two platforms wearing one name and
the contract has quietly failed.

**Cost, so the decision is a decision.** On-prem needs no account and can be proven free on
`docker-desktop` or a spare box. A managed cloud cluster is an **operational** cost, not a one-off:
roughly $70–100 a month for a small managed control plane plus nodes, before storage and egress.
Under LAW 14 that number has to be worth paying, and today it buys a portability proof we can get
most of for nothing locally. **My recommendation: prove F-39 on the free local cluster first,
because the ten-plane bring-up is where the real work is, and only rent a cloud cluster to close
F-40 once the on-prem half is green.** That way the meter starts on the last step, not the first.

**What I would not do: run a self-managed control plane on the laptop as production.** It replaces
one single point of failure with a more complicated one, and a control plane needs its own backups,
upgrades and on-call. If we take this route it is a managed cluster, and only once the planes k8s
cannot help with are already closed.

---

## 13. The final tooling — the decision, closing §5's analysis

Founder, 2026-08-20: *"no netion of finalaa tooling"*. §5 lists candidates. This section names the
choice. One tool per layer, nothing chosen twice. **Decided** means code in the repo uses it today.
**Proposed** means it is waiting on the founder, and the alternative is named so the choice is a
choice rather than a default.

| Layer | Tool | Status | Why this one |
|---|---|---|---|
| Portability contract | our own eleven verbs, plain `sh` | decided | `deploy/PORTABILITY.md`, four adapters, one contract test. No framework is smaller than a shell function, and nothing outside `deploy/targets/` knows a provider's name. |
| Container build | Docker, one Dockerfile per service | decided | Every adapter builds the same image from the repo root, so the artifact on Fly is the artifact anywhere else. |
| Production host | Fly | decided 2026-08-18 | Running there since the cutover. Stays production until a second substrate has actually been drilled. |
| Second substrate | Kubernetes via `kubectl`, **no Helm** | proposed | The adapter writes its own manifests, so a chart would be a second place for the same truth to live. Free to prove on `docker-desktop`. |
| Infrastructure as code | none for the engine | proposed | `terraform` is installed and nothing in the repo uses it. The engine is eleven verbs, not a resource graph. Revisit only for DNS records and account scaffolding — a different problem, and §5 already parks it as OpenTofu-later. |
| Secrets at rest | `sops` + `age`, key escrowed off-machine | proposed · **blocks P3** | `age` is installed and already signs receipts here. Cloud KMS is ruled out by the founder. Alternative is a password-manager CLI; either way one bootstrap credential must exist off this laptop. |
| Backup and restore | `restic` to object storage | proposed | Free, encrypted, deduplicating, and it verifies its own snapshots — which matters more than the copy, because an unverified backup is a belief. Alternative `rclone` copies but does not verify. |
| Paging | Telegram, in-repo sender | decided 2026-08-20 | Commit `47212af5`. The previous sink was a file on this laptop, which is the wrong place for the alert that says this laptop is gone. |
| CI | GitHub Actions, self-hosted runners behind a variable | decided | Every job reads `CI_RUNS_ON` with a hosted fallback, so the fleet moves or dies without touching a workflow file. |
| Language and gate | Python 3.14, `uv`, `ruff`, `pytest` | decided | In use and enforced by the commit gate. Written down so nobody re-opens it. |
| Ops surface | the repo's own console | decided | The rule outranks the tool: no behaviour may exist only in a provider's dashboard. A button is a verb in the repo or it is not a button. |

**Four things are deliberately absent, and that is the point of writing this down: no Helm, no
Terraform for the engine, no service mesh, no hosted observability vendor.** Each adds a second
place for the same truth to live, and every measurement in this programme says duplication is what
has been costing us — not missing tools.

Measured on this laptop 2026-08-20, so the proposals are honest about what still needs installing:
`kubectl`, `docker`, `fly`, `terraform`, `age`, `gh`, `uv`, `ruff`, `pytest`, `node` are present.
`helm`, `sops`, `restic`, `rclone`, `ansible`, `kind`, `k3d` are not.
