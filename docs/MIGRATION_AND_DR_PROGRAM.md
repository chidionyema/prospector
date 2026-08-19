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
| Fly inventory | `scripts/fly_estate_probe.py` (PR #390) | shipped 2026-08-19; Fly apps only |
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

**Breaks today.** `scripts/fly_estate_probe.py` sees 11 Fly apps. `ops/launchd/*.json` declares the
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

**Done when.** `scripts/bootstrap_machine.sh` takes a bare macOS or Linux machine to: repo cloned,
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
we have never exported; Hermes' state on the laptop — **no backup at all**; and the provider-health,
retrieval-cache and scheduler files under the store, recoverable only if a restore includes them.

**Story.** *"everything fron dns, logs, everything, db"* · *"this si critial , busines dpeendent
work"*.

**Done when.** The inventory (M1) carries a datastore table listing, for each: where it is, how it is
backed up, its RPO, its RTO, and **the date of its last proven restore**. A datastore whose last
proven restore is blank, or older than its drill cadence, reads red on the console. The Stripe export
is written as a rebuild script — that is what turns R1 from fatal into slow.

**Costs.** M. Most of it is wiring what already runs into one honest table.

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

**HYPOTHESIS, and the exact check.** The founder asked me to *"think and reseach toling on the web"*.
I could not: `WebSearch` is refused by the context guard in this session. So the right-hand column
above is written from knowledge, not from a fetched source, and every entry in it is a **candidate,
not a decision**. The check that confirms or kills each one, to be run at the top of a fresh session:
for each candidate, confirm the licence is OSI-approved, confirm it runs on Linux **and** macOS
without a hosted control plane, and confirm it is maintained — a commit in the last six months. The
left-hand column needs no such check; it is code in this repo.

**What I will not propose.** A hosted control plane of any kind (Terraform Cloud, a SaaS chaos
platform, a managed backup service). Each one re-introduces exactly the dependency this programme
removes, and each is a monthly bill.

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
| 2026-08-19 | M1 (part) | `scripts/fly_estate_probe.py` — Fly apps with no committed config | PR #390; `exit=1`, `prospector-hermes` named |
| 2026-08-19 | M3 (fence) | `deploy/targets/fly.sh` flyctl shim; D3 was red with `fly: command not found` | PR #388; 2 failed → 3 passed |
| 2026-08-19 | — | `docs/ESTATE_MAP.md` Hermes section corrected from asserted to measured | PR #390 |
