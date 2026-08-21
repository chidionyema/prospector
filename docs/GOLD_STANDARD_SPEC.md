# The gold standard — build spec

> Founder, 2026-08-21: *"you need to get faster ad have aplan to deliver gold standard super
> fast"*, then *"you need to breakit downto spec"*.
>
> This is the build spec. `docs/MIGRATION_AND_DR_PROGRAM.md` holds the 60 requirements and the
> evidence; this file holds the *thing to build*: nine components, their interfaces, and the
> order that makes each one provable on the day it lands.
>
> Every claim about what exists today was measured on `origin/main` on 2026-08-21 and carries a
> `file:line`. Re-measure before trusting any of it.

---

## 1. The bar, cut into five numbers

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
| A5 | reusable, any project | **0 lines naming prospector** in the runner | a test greps the runner tree for the project's own names |

**A3 needs one ruling from you and it is the only thing in this spec that does.** See §7.

## 2. What already exists, measured

The estate is much closer to this than the requirement count suggests. Two working halves exist
and nothing joins them.

| Piece | Lines | What it does | What it does NOT do |
|-------|-------|--------------|---------------------|
| `scripts/estate_inventory.py` | 683 | Probes the **running world** for 10 resource classes — compute, datastore, object storage, DNS, TLS, secret, log sink, scheduled job, payment integration, CI runner (`:48`, discoverers `:137`–`:311`). Emits JSON (`:672`). Refuses to read its own declaration as truth. | Never produces a *plan*. It is a census, not a work list. |
| `deploy/cutover.sh` | 153 | Moves the engine between platforms in 8 ordered phases (`:89`–`:147`), resumable with `--from-phase` (`:41`), and restarts the source on failure rather than pressing on. | Moves **one class**: compute plus its volume. Knows nothing of DNS, the storefront, jobs, logs or payments. |
| `deploy/targets/{fly,k8s,laptop,sshdocker}.sh` | 269 (k8s) | Four substrates behind one verb contract of six verbs (`deploy/PORTABILITY.md:21`–`:28`). Adding a substrate costs one file. | The contract describes *a place to run a container*. There is no contract for moving a DNS zone or a database. |
| `scripts/store_migrate.py` | 451 | `plan` / `pack` / `verify` for the engine's store, with a sha256 manifest shared by both ends. | Engine store only. |
| `scripts/restore_drill.py` | 584 | Restores the R2 backup end to end and asserts five properties with receipts. | Proves a *backup*, not a *move*. Different question, as its own docstring says. |

**The join is the product.** `cutover.sh` should not carry a hardcoded phase list. It should
execute a plan compiled from what the probe found, one class adapter per class.

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
      "adapter": "deploy/classes/secret.sh", "needs": [],
      "downtime": "zero", "budget_s": 60, "bytes": 0,
      "verify": "every name in deploy/secrets.required is present at the target" },
    { "id": "datastore/store", "class": "datastore", "resource": "store",
      "adapter": "deploy/classes/datastore.sh", "needs": ["secret/prospector-engine"],
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

Five verbs, on the model of `deploy/PORTABILITY.md:21`. Every class implements all five; a verb
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

## 4. The nine components

Ordered by the slice that needs them. "Done when" is always a drill that goes green, never a
file that exists.

| C | Component | File | Done when |
|---|-----------|------|-----------|
| C1 | **Plan compiler** | `deploy/migrate/plan.py` | It compiles a plan from a real probe report, and a test proves every found resource is either in a step or in `skipped` with a reason. |
| C2 | **Runner** | `deploy/migrate/run.py` | It executes a plan, honours `needs`, resumes with `--from-step`, rolls back on a failed `verify`, and emits an event per transition. |
| C3 | **Class adapter: compute** | `deploy/classes/compute.sh` | It wraps the existing `cutover.sh` unchanged. Proves the contract fits what already works before six more are written to it. |
| C4 | **Console page + live progress** | `prospector/ops/migration_view.py` | A page starts a run, shows a bar per step and the clock, and offers rollback. Registered the same way the other pages are (`prospector/ops/console_api.py`). |
| C5 | **The drill and the clock** | `.github/workflows/migration-drill.yml` | A scheduled real migration, timed, with a downtime prober; red over 1800s or over any step's downtime class. |
| C6 | **Class adapter: secret + config** | `deploy/classes/secret.sh` | A new target gets every name in `deploy/secrets.required` in one command. This is D8 landing, and it unblocks every other class. |
| C7 | **Class adapter: datastore** | `deploy/classes/datastore.sh` | Engine store via `store_migrate.py`; storefront via `pg_dump`/`pg_restore` per the D6 ruling. Verified by row counts at both ends. |
| C8 | **Class adapters: DNS + TLS** | `deploy/classes/{dns,tls}.sh` | Health-gated flip with the TTL pre-lowered, and a rollback that flips back. This is where clause A3 is won or lost. |
| C9 | **Class adapters: the rest** | `deploy/classes/{scheduled_job,log_sink,object_storage,payment_integration}.sh` | The probe's diff at both ends is empty — clause A2. |

## 5. Delivery order — five slices, each one provable

Thin end to end first. The whole bar is demonstrated on one plane before any plane is done
properly, because a deep vertical proves nothing about the clock, the dashboard or the rollback.

| Slice | Components | The drill that closes it | Clauses proved |
|-------|-----------|--------------------------|----------------|
| **S1 — the thin wire** | C1, C2, C3, C4 | Move the engine `fly → sshdocker` and back, started from the console, with a live bar and a stopwatch. | A1, A4 on one class; A5 by construction |
| **S2 — credentials travel** | C6 | A new empty target gets every required secret in one command, and the engine starts there. | unblocks all of A2 |
| **S3 — the data** | C7 | Engine store and storefront Postgres both move, row counts equal at both ends. | A1 under real bytes — the long pole |
| **S4 — no downtime** | C8 | The public prober records 0 non-200s across a full storefront cutover. | A3 |
| **S5 — nothing missed** | C9, C5 | Probe at both ends; diff empty. Drill runs on a schedule and can go red. | A2, and A1 becomes permanent |

**S6 is the proof of clause A5 and it is cheap if S1 was built honestly:** point the probe at a
second project, compile a plan, run it. If it needs a code change, C1 or C2 has prospector in it
and the test in A5 should have caught it.

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

## 7. The one thing that needs your ruling

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

## 8. Speed — how this gets built fast

The programme has been producing documents faster than it has been producing drills. The change:

1. **A slice is not done until a drill is green.** No component ships on the strength of a file
   existing; §4's "done when" column is the only definition.
2. **Thin before deep.** S1 touches every layer and one class. It is the slice that finds the
   architectural mistakes, and it finds them on day one rather than at S5.
3. **Six of the nine components are shell adapters against a contract that already works.** They
   are parallel and independent once C1 and C2 exist, which is what makes the back half fast.
4. **The probe was the expensive part and it is already written.** 683 lines, ten classes,
   discovering from the running world rather than from a declaration.
