# The gold standard — build spec

> Founder, 2026-08-21: *"you need to get faster ad have aplan to deliver gold standard super
> fast"*, then *"you need to breakit downto spec"*.
>
> This is the build spec. `docs/MIGRATION_AND_DR_PROGRAM.md` holds the 60 requirements and the
> evidence; this file holds the *thing to build*: twelve components, their interfaces, and the
> order that makes each one provable on the day it lands.
>
> Every claim about what exists today was measured on `origin/main` on 2026-08-21 and carries a
> `file:line`. Re-measure before trusting any of it.

---

## 1. The bar, cut into seven numbers

> `docs/PLATFORM_ENGINEERING_PRINCIPLES.md` is the outside view of this bar: ten principles
> from the published discipline (CNCF, DORA, Team Topologies, AWS Well-Architected, Google DiRT),
> each naming the clause below that it steers. It also carries two proposed clauses this table
> does not have — an RPO and a source-is-gone scenario — which are in §7 below awaiting a ruling.

Founder, 2026-08-19, verbatim:

> *"if i have 30 ninutes to nigrate the wwhole stack, donain, third party deps/ donain ,
> everything running in this nachine because i also have a new laptop, so engine, hernes, jobs,
> and evertything on fly to another onpren or cloud provider, i should not epericne ny downtine
> and get this seanlessly done fron ops dashboard and prove and see realtine progress. this is
> the bar, even things like logs, etc nothing beig used can be nissed out, and this has to be
> resuable for any project not just prospector etc, should be able to probe and audit any systen
> and get this done."*

Five clauses, each with a number a drill can fail on:

| # | Clause | The number | How it is measured |
|---|--------|-----------|--------------------|
| A1 | 30 minutes | wall clock from "go" to "verified", **≤ 1800s** | the runner stamps `t_start` and `t_verified`; the drill fails over budget |
| A2 | the whole stack | **0 resources left behind**, across all 10 classes | the probe runs at both ends; the diff must be empty |
| A3 | no downtime | **0s customer-visible**, background pause **≤ 120s** | a prober hits the public endpoints every 250ms through the whole run and counts non-200s |
| A4 | from the dashboard, real-time | started from a console page, **no step ≥ 5s without an event** | the event stream is the progress bar; a gap is a defect |
| A5 | reusable, any project | **0 product names** anywhere under `kit/` | `test_kit_names_no_product.py` greps `kit/` for every declared product's names |
| A6 | fully operational, ready to sell | **1 synthetic purchase completes** at the target, inside the same 1800s | the drill buys something in test mode end to end: DNS, TLS, storefront, checkout, webhook, catalogue row |
| A7 | scales to n projects | **1 declaration file per project, 0 code changes** to add the second | the drill runs the kit against a second declaration |

**A3 needs one ruling from you and it is the only thing in this spec that does.** See §7.

### 1.1 The three scenarios that define done

Founder, 2026-08-21: *"scenarios to cosider if i had to nove to eks tonorrow gold standard can i
do it, if i had to nove to snaller less known platforn or onpren can i do it fron ops dashboad,
seanless ly in 0 niutes and be fully operational ready to sell ?"*

These are the goals. The programme is finished when all three go green from the dashboard, inside
1800s, ending in a completed purchase. Three rather than one, because each stresses something the
other two cannot reach.

| | Scenario | What it stresses that the others do not | The adapter it proves | Where it will hurt |
|---|---|---|---|---|
| **G1** | **EKS tomorrow** — managed Kubernetes at a hyperscaler | An image registry that is not the platform's own (ECR); cloud identity as a precondition to every other step; a `StorageClass` and a claim instead of a mounted directory; the cluster's own DNS in front of ours | `deploy/targets/k8s.sh` (269 lines) | The adapter has only ever met small clusters. Identity and the registry are two auth surfaces it has never touched, and both fail at minute 2, not minute 20 — so the plan compiler must check them in `plan`, not discover them in `move`. |
| **G2** | **A smaller, less known platform** — a VPS, Hetzner, OVH, anything with no adapter worth writing | There is no provider API at all. Only SSH and Docker. Everything the platform used to give free — TLS termination, a private network, a secret store, log collection, health checks — is now ours to supply | `deploy/targets/sshdocker.sh` (90 lines) | This is the lowest common denominator, and therefore the real test of portability. If the bar is met here it is met everywhere. |
| **G3** | **On-premises** — our own hardware | Possibly no public address and a router in the way; TLS with no cloud DNS API to answer the challenge; backups must physically leave the building; power and disks become our problem | `sshdocker` plus a DNS-01 path through the registrar | The certificate is the trap. Without a platform to terminate TLS, the challenge has to be answered at the domain registrar, which is a third party we re-point rather than a resource we move. |

**A hyperscaler is not a lock-in problem and EKS is legal.** `deploy/PORTABILITY.md:127` refuses a
managed **database**, not managed compute. G1 is a supported destination; G2 and G3 are what stop
it becoming the only one.

### 1.2 Ready to sell — the clause that stops "it is up" counting as "it works"

A6 exists because every other clause can pass while the business cannot take money. Pods can be
running, the probe diff can be empty, and a shopper still meets an expired certificate, or a
payment webhook still pointing at the machine we just left.

**One check covers all of it: complete a purchase at the target, in test mode, before the clock
stops.** That single transaction exercises DNS, TLS, the storefront, the API, the database, the
payment integration's webhook, and the catalogue write — in the order a customer meets them. It
cannot pass while any of those is still pointing at the old home.

### 1.3 Move, re-point, rebuild — three verbs, not one

The plan compiler must know which of these each resource needs, because the failure modes differ
and only one of them is a copy.

| Kind | What it means | Examples | The risk |
|------|---------------|----------|----------|
| **Move** | Bytes travel; the target must end up holding what the source held | the engine store, the storefront database, object storage | Silent partial copy. Answered by a manifest checked at both ends — `scripts/store_migrate.py` already does this. |
| **Re-point** | Nothing travels. A **third party** is holding a pointer at us and must be told the new address | Stripe webhook endpoints, DNS records, the registrar, alert destinations, log shipping | Forgetting one. Nothing breaks at cutover; it breaks at the next event, hours later. This is the class that "nothing being used can be missed out" is really about. |
| **Rebuild** | Nothing travels and nothing is told; the thing is made again from a declaration | containers, TLS certificates, scheduled jobs, CI runners | Drift between the declaration and what was actually running. Answered by the probe running at **both** ends and diffing. |

`scripts/estate_inventory.py:289` already discovers the hardest re-point case — it lists Stripe's
webhook endpoints from Stripe's own API rather than from our declaration, which is the only way
to find one nobody wrote down.

## 2. What already exists, measured

The estate is much closer to this than the requirement count suggests. Two working halves exist
and nothing joins them.

| Piece | Lines | What it does | What it does NOT do |
|-------|-------|--------------|---------------------|
| `scripts/estate_inventory.py` | 683 | Probes the **running world** for 10 resource classes — compute, datastore, object storage, DNS, TLS, secret, log sink, scheduled job, payment integration, CI runner (`:48`, discoverers `:137`–`:311`). Emits JSON (`:672`). Refuses to read its own declaration as truth. | Never produces a *plan*. It is a census, not a work list. |
| `deploy/cutover.sh` | 153 | Moves the engine between platforms in 8 ordered phases (`:89`–`:147`), resumable with `--from-phase` (`:41`), and restarts the source on failure rather than pressing on. | Moves **one class**: compute plus its volume. Knows nothing of DNS, the storefront, jobs, logs or payments. |
| `deploy/targets/{fly,k8s,laptop,sshdocker}.sh` | 269 (k8s) | Four substrates behind one verb contract of twelve functions (`deploy/PORTABILITY.md:44`–`:54`). Adding a substrate costs one file. | The contract describes *a place to run a container*. There is no contract for moving a DNS zone or a database. |
| `scripts/store_migrate.py` | 451 | `plan` / `pack` / `verify` for the engine's store, with a sha256 manifest shared by both ends. | Engine store only. |
| `scripts/restore_drill.py` | 584 | Restores the R2 backup end to end and asserts five properties with receipts. | Proves a *backup*, not a *move*. Different question, as its own docstring says. |

**The join is the product.** `cutover.sh` should not carry a hardcoded phase list. It should
execute a plan compiled from what the probe found, one class adapter per class.

### 2.1 Decoupling — measured, not assumed

Founder, 2026-08-21: *"so a lot of out tooling needs decoupling fron prospector"*, *"prospector
first"*, *"but can be used for ay project"*, *"as a conpany we cn have other producs"*, *"can
scale to supprt n projects"*.

The instinct is right and the size of the job is smaller than it looks. Measured on `origin/main`,
2026-08-21 — reproduce with `rg -c -i prospector <file>`:

| Tool | lines | `prospector` hits | imports the package | hardcoded absolute paths | Verdict |
|------|------:|------------------:|--------------------:|-------------------------:|---------|
| `scripts/estate_inventory.py` | 683 | **0** | 0 | 0 | **Already kit.** Takes a declaration (`:42`) and reads every project fact from it (`:187`–`:371`). |
| `deploy/cutover.sh` | 153 | 6 | 0 | 0 | Kit after the names lift. |
| `deploy/secrets.sh` | 160 | 4 | 0 | 0 | Kit after the names lift. |
| `deploy/targets/sshdocker.sh` | 90 | 7 | 0 | 0 | Kit after the names lift. |
| `deploy/targets/fly.sh` | 185 | 10 | 0 | 0 | Kit after the names lift. |
| `deploy/targets/k8s.sh` | 269 | 14 | 0 | 0 | Kit after the names lift. |
| `deploy/targets/laptop.sh` | 161 | 14 | 0 | 2 | Kit after the names lift. |
| `scripts/store_migrate.py` | 451 | 11 | 0 | 0 | Kit; the class adapter for one datastore shape. |
| `scripts/restore_drill.py` | 584 | 8 | 1 | 0 | Kit after the one import moves behind the declaration. |
| `scripts/engine_failover.py` | 803 | 25 | **2** | 3 | **Stays prospector's.** It knows about spend ledgers and moat brains. Not kit, and pretending otherwise would drag the engine's business rules into every future product. |
| `scripts/live_checkout.py` | 830 | 15 | 0 | 6 | **Stays prospector's.** Same reason. |

**The finding: 0 of the hits in the kit column are couplings to prospector's *logic*. They are
app and path NAMES** — `prospector-engine`, `store/`, `.prospector/ACTIVE`. A name is exactly what
a declaration parameterises, which is why the probe already scores zero: it was written that way
from the start.

So decoupling is one mechanical job — lift names into the declaration — plus one judgement call,
which is refusing to lift the two tools that encode prospector's own rules.

### 2.2 How it scales to n projects

One kit, one declaration per project, nothing else per project.

```
  kit/                          <- names no product; A5 is a test over this tree
    probe/                      <- estate_inventory.py, already clean
    migrate/plan.py             <- C1
    migrate/run.py              <- C2
    classes/*.sh                <- C3, C6..C9
    targets/*.sh                <- exists: fly, k8s, sshdocker, laptop
  projects/
    prospector.yaml             <- the first tenant, and the only one today
    <next-product>.yaml         <- adding this is the whole cost of product two
```

The declaration already has a working shape — `estate_inventory.py` reads `owns:` for domains,
the repository, the log host, launchd prefixes, supervisord configs, the Stripe key name, the CI
app and the Fly app prefixes (`:187`–`:371`). It grows two blocks: `targets:` (which substrates
this product may live on, and their credentials by name) and `classes:` (per class, which adapter
and what its verify means).

**Three rules keep it honest as products are added:**

1. **The kit never reads a project name.** A5's test greps `kit/` for every product's own names
   and fails on a hit. This is the only thing standing between one kit and four forks of it.
2. **A project is added by writing a declaration, never by editing the kit.** If product two needs
   a kit change, that change is a missing *capability*, and it lands as a class or target adapter
   that product one also gets.
3. **Secrets are per project and never shared.** One declaration names its own secret set;
   `deploy/secrets.required` becomes `projects/<name>.secrets.required`.

**Prospector first, and that is a sequencing decision rather than a design one.** The kit is built
against one real product so that the seams are proven by use instead of guessed at. Product two is
the test of A7, and §5 puts it in the last slice for exactly that reason.

## 3. Architecture — three layers and one stream

```
  estate_inventory.py  ──►  plan compiler  ──►  runner  ──►  class adapters ──► target adapters
     (what exists)          (what moves,        (does it,      (how a DNS       (fly | k8s |
                             in what order)      resumably)     zone moves)      sshdocker | laptop)
                                                    │
                                                    └──►  event stream (JSONL)  ──►  console page
```

Nothing new is invented at the bottom two layers. The target adapters exist and stay as they
are. The class adapters are new and copy the shape of the target adapters exactly, because that
contract has already survived four substrates.

### 3.1 The plan — the one new data structure

The compiler turns a probe report into an ordered list of steps. This is the whole interface
between "what we have" and "what we do", and it is the file a human reads before pressing go.

Shape only — every number below is illustrative, and the real ones come from the probe:

```json
{
  "plan_id": "2026-08-21T02:14:07Z",
  "from": "fly", "to": "sshdocker",
  "budget_s": 1800,
  "steps": [
    { "id": "secret/prospector-engine", "class": "secret", "resource": "prospector-engine",
      "adapter": "kit/classes/secret.sh", "needs": [],
      "downtime": "zero", "budget_s": 60, "bytes": 0,
      "verify": "every name in deploy/secrets.required is present at the target" },
    { "id": "datastore/store", "class": "datastore", "resource": "store",
      "adapter": "kit/classes/datastore.sh", "needs": ["secret/prospector-engine"],
      "downtime": "stop", "budget_s": 420, "bytes": 0,
      "verify": "scripts/store_migrate.py verify against the pack manifest" }
  ]
}
```

Rules the compiler enforces, each one a test:

1. **Every resource the probe found appears in exactly one step, or in a `skipped` list with a
   reason.** A resource that silently vanishes between census and plan is clause A2 failing
   quietly. This is the check that makes "nothing being used can be missed out" mechanical.
2. **`needs` is a directed acyclic graph and the runner honours it.** Secrets before anything
   that authenticates. Datastore before the compute that opens it. DNS last, because DNS is the
   switch.
3. **`budget_s` sums to no more than `budget_s` at the top**, along the critical path rather
   than in total, since independent steps run at once.
4. **`downtime` is one of `zero` | `brief` | `stop`** and the drill in §5 holds each to it.

### 3.2 The class adapter contract

Five verbs, on the model of the target adapters' twelve (`deploy/PORTABILITY.md:44`–`:54`). Every class implements all five; a verb
it cannot honour exits 78 (`EX_CONFIG`) with a reason, and the compiler refuses to build a plan
containing it rather than discovering it at minute 20.

| Verb | Contract |
|------|----------|
| `plan <resource>` | print size, row count, expected seconds, downtime class. Read-only. |
| `provision <resource>` | make the empty thing at the target. Idempotent. |
| `move <resource>` | copy the content and print a manifest. Idempotent, resumable. |
| `verify <resource>` | prove the target matches the source. Exit non-zero is the rollback trigger. |
| `rollback <resource>` | put the source back in charge. Must work with the target half-built. |

### 3.3 The event stream

The runner appends one JSON line per state change to `store/migrations/<plan_id>.jsonl`, and
that file is the *only* progress mechanism. The console tails it; so does CI; so does a terminal.
One writer, three readers, nothing to keep in step.

```json
{"t":"2026-08-21T02:14:31.412Z","step":"datastore/store","state":"moving","pct":41,"msg":"1.6 MB of 3.9 MB"}
```

A step that emits nothing for 5s fails clause A4. That is a hard rule in the runner, not a
guideline: every long verb streams progress or it is not finished.

## 4. The twelve components

Ordered by the slice that needs them. **A path in the File column with no waiver comment is BUILT and on main; the rest are
still to be built**, and the slice that creates each one is named in §5. "Done when" is always a
drill that goes green, never a file that exists.

| C | Component | File | Done when |
|---|-----------|------|-----------|
| C1 | **Plan compiler** | `kit/migrate/plan.py` | It compiles a plan from a real probe report, and a test proves every found resource is either in a step or in `skipped` with a reason. Refuses a plan whose adapter cannot honour a verb, rather than finding out at minute 20. |
| C2 | **Runner** | `kit/migrate/run.py` | It executes a plan, honours `needs`, resumes with `--from-step`, rolls back on a failed `verify`, and emits an event per transition. |
| C3 | **Class adapter: compute** | `kit/classes/compute.sh` | It wraps the existing `deploy/cutover.sh` unchanged. Proves the contract fits what already works before six more are written to it. |
| C4 | **Console page + live progress** | `prospector/ops/migration_view.py` | A page picks a project and a target, starts a run, shows a bar per step and the clock, and offers rollback. |  <!-- doc-lint-ok: the File column names what slice S1 builds; the path is the deliverable, not a claim it is there -->
| C5 | **The drill and the clock** | `.github/workflows/migration-drill.yml` | A scheduled real migration, timed, with a downtime prober; red over 1800s or over any step's downtime class. |  <!-- doc-lint-ok: the File column names what slice S6 builds; the path is the deliverable, not a claim it is there -->
| C6 | **Class adapter: secret + config** | `kit/classes/secret.sh` | A new target gets every name in the project's secret list in one command. This is D8 landing, and it unblocks every other class. |  <!-- doc-lint-ok: the File column names what slice S2 builds; the path is the deliverable, not a claim it is there -->
| C7 | **Class adapter: datastore** | `kit/classes/datastore.sh` | Engine store via `store_migrate.py`; storefront via `pg_dump`/`pg_restore` per the D6 ruling. Row counts equal at both ends. |  <!-- doc-lint-ok: the File column names what slice S3 builds; the path is the deliverable, not a claim it is there -->
| C8 | **Class adapters: DNS + TLS** | `kit/classes/{dns,tls}.sh` | Health-gated flip with the TTL pre-lowered, and a rollback that flips back. Includes the DNS-01 path through the registrar, which is what G3 needs and no platform supplies. |  <!-- doc-lint-ok: the File column names what slice S4 builds; the path is the deliverable, not a claim it is there -->
| C9 | **Class adapters: the rest** | `kit/classes/{scheduled_job,log_sink,object_storage,payment_integration}.sh` | The probe's diff at both ends is empty — clause A2. `payment_integration` is a **re-point**, not a move. |  <!-- doc-lint-ok: the File column names what slice S6 builds; the path is the deliverable, not a claim it is there -->
| C10 | **Project declaration + validator** | `kit/projects/schema.py`, `kit/projects/prospector.yaml` | A declaration is validated before a run starts, and a missing block fails at second 0 with the name of what is missing. This is the A7 seam. |
| C11 | **The sell-path prober** | `kit/verify/can_we_sell.py` | It completes a test-mode purchase against a named base URL and asserts the catalogue row and the webhook delivery that follow. Red until all of DNS, TLS, storefront, API, database and payments point at the target. |  <!-- doc-lint-ok: the File column names what slice S5 builds; the path is the deliverable, not a claim it is there -->
| C12 | **The names lift, and the test that holds it** | `kit/` tree + `tests/unit/test_kit_names_no_product.py` | Every name in the table at §2.1 has moved into a declaration, and the test fails on any product name appearing under `kit/`. Clause A5 becomes mechanical instead of a promise. |

## 5. Delivery order — six slices, each one provable

Thin end to end first. The whole bar is demonstrated on one class before any class is done
properly, because a deep vertical proves nothing about the clock, the dashboard or the rollback.

| Slice | Components | The drill that closes it | Clauses | Scenario |
|-------|-----------|--------------------------|---------|----------|
| **S1 — the thin wire** | C1, C2, C3, C4, C10, C12 | Move the engine `fly → sshdocker` and back, started from the console, with a live bar and a stopwatch. | A1, A4 on one class; A5 by test | G2 in miniature |
| **S2 — credentials travel** | C6 | A new empty target gets every required secret in one command, and the engine starts there. | unblocks all of A2 | all three |
| **S3 — the data** | C7 | Engine store and storefront Postgres both move; row counts equal at both ends. | A1 under real bytes — the long pole | all three |
| **S4 — no downtime** | C8 | A prober hits the public endpoints every 250ms through a full storefront cutover and records 0 non-200s. | A3 | G3 needs the registrar path |
| **S5 — ready to sell** | C11 | A test-mode purchase completes at the target inside the same 1800s. | **A6** | all three |
| **S6 — nothing missed, everywhere** | C9, C5 | Probe at both ends, diff empty. Then the scenario matrix: G1, G2 and G3 each green, on a schedule. | A2, and A1 becomes permanent | **G1, G2, G3** |

**S7 is the proof of A7 and it is cheap if the kit was built honestly:** write a declaration for a
second product and run the kit against it. If it needs a code change under `kit/`, C12's test
should already have failed, and the change is a missing capability that product one also gets.

**The scenario matrix is the finish line, not a bonus.** G1 exercises cloud identity and a
registry; G2 exercises having no provider API at all; G3 exercises TLS and DNS with no platform
behind them. A kit that passes one of the three is not portable, it is adapted.

## 6. What we are deliberately NOT building, so this stays fast

Each of these is a place the programme could sink a week and not move a clause.

- **No new config server.** D8 already ruled: a git repo of plain files, secret values encrypted
  inline with SOPS and age. C6 is a shell script over `deploy/secrets.sh`, not a service.
- **No new progress system.** One JSONL file, three readers (§3.3).
- **No new substrate.** Four target adapters exist and the contract has survived all four.
- **No rewrite of `cutover.sh`.** C3 wraps it. It is 153 lines that already order the dangerous
  operations correctly and restart the source on failure; that ordering was paid for.
- **No managed anything.** `deploy/PORTABILITY.md:127` and the D6 ruling both bind here: the
  storefront's Postgres is self-hosted, or it cannot travel.
- **No orchestrator.** `docs/STACK_AUDIT.md` §5 already refused Kamal and Nomad. The runner is a
  Python file that shells out to adapters.

## 7. The three things that need your ruling

A3 was the only one when this file was written. Research into the published platform-engineering
discipline on 2026-08-21 added two more; both are argued in full in
`docs/PLATFORM_ENGINEERING_PRINCIPLES.md` Part 3.

### 7.1 Clause A3 — what may pause

**Clause A3 has two readings and they cost very differently.**

`deploy/cutover.sh:12` stops the engine on the source before packing the state, on purpose: two
engines running at once keep two spend ledgers and can spend twice the daily cap. So the engine
today has a deliberate stop, of minutes.

- **Reading 1 — customer-visible only.** The storefront, the domain and the payment path never
  drop a request. The engine, a background batch nobody is watching, may pause for a bounded
  window. **Cost: S4 only has to cover DNS, web and the API.**
- **Reading 2 — literally nothing pauses.** The engine keeps ticking through the move. That
  needs a lease so both ends can run with only one of them ticking, plus a ledger that is safe to
  write from two places. **Cost: roughly a slice of its own, and it touches the money path.**

**Recommendation: reading 1, with the engine's pause budgeted at 120s and measured by the drill.**
Nobody experiences a paused batch; a shopper experiences a dropped request. Reading 2 buys a
number that only a machine can see, and it buys it in the one part of the system where a bug
spends money twice. If you want reading 2 later, the lease is additive and the plan does not
change shape — the engine step's `downtime` moves from `stop` to `zero` and nothing else moves.

### 7.2 Proposed clause A8 — the RPO, with a number

Every clause in §1 is about time or completeness. None is about **loss**. AWS Well-Architected
REL13 treats recovery time and recovery point as two independent numbers, and a plan carrying only
one of them is half a plan.

Measured 2026-08-21: `RPO` and `RTO` appear **0 times** across `docs/`, `kit/`, `scripts/` and
`deploy/` on `origin/main`. The only number acting as an RPO is `max_age_hours: 24`
(`ops/config/offsite_backup.yaml:26`), which the money database inherits because its own source
block sets no override.

So the position today is: for a **planned** migration the effective RPO is 0, because the cutover
recopies after the source stops. For an **unplanned** one it is **up to 24 hours of orders**. Those
two numbers are a day apart and only the second was ever written down, in a config file, as a
monitor threshold rather than as a business decision.

**Recommendation: adopt A8 at 24 hours for now, and say so out loud rather than leaving it
implicit.** Tightening it is a real cost — it means the order database stops being a file on one
volume — and that cost belongs to the storefront-Postgres work already on the record, not here.

### 7.3 Proposed scenario G4 — the source is gone

G1, G2 and G3 differ in where we are going. None differs in what we still have: all three assume a
readable source. Two angles say the kit cannot execute the other case. The datastore adapter (on
PR #585, not yet on main) packs from `$FROM`, so a dead source yields no seed; and the target contract itself defines
`t_pack` as *"pack this platform's store, for when it is the SOURCE of a move"*
(`deploy/PORTABILITY.md:40`) — there is no verb for a source that is gone.

The programme is called migration **and DR** and currently builds the first half.

**Recommendation: add G4 — Fly unreachable, only the offsite bucket and the declarations as
inputs, same 1800s, same completed purchase at the end.** `scripts/restore_drill.py` already does
this for the engine store and is the seed of it; what it does not cover is everything else.

## 8. Speed — how this gets built fast

The programme has been producing documents faster than it has been producing drills. The change:

1. **A slice is not done until a drill is green.** No component ships on the strength of a file
   existing; §4's "done when" column is the only definition.
2. **Thin before deep.** S1 touches every layer and one class. It is the slice that finds the
   architectural mistakes, and it finds them on day one rather than at S5.
3. **Six of the twelve components are shell adapters against a contract that already works.** They
   are parallel and independent once C1 and C2 exist, which is what makes the back half fast.
4. **The probe was the expensive part and it is already written.** 683 lines, ten classes,
   discovering from the running world rather than from a declaration.
