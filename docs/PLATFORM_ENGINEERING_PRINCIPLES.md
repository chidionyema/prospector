# Platform engineering principles — the outside discipline, and what it changes here

> Founder, 2026-08-21: *"you need nore research on platforn engineering i think"*, *"and tie into
> our gold standard"*, *"we need pltforn enginerring principles steeting our effots"*.
>
> This file is the **outside** view. `docs/PLATFORM_MANIFESTO.md` is the constitution and its ten
> laws are ours; `docs/GOLD_STANDARD_SPEC.md` is the build spec and its seven numbers are the
> founder's; `docs/OPS_AUTOMATION_PRINCIPLES.md` is the narrower rulebook for a single automation.
> None of them is grounded in the published discipline, and that is the gap this closes.
>
> Every principle below names a **source outside this estate**, the **clause of the bar it
> steers**, and the **command that tests whether we are keeping it**. A principle with no test is
> an opinion, and Part 3 is the part that matters: four things the discipline says we currently
> have wrong, each measured on `origin/main` on 2026-08-21.

---

## Part 0. The four findings, before the theory

If you read nothing else, read these. Each one changes what gets built next.

| | Finding | Measured | What it changes |
|---|---|---|---|
| **F1** | **There is no RPO.** The programme has a recovery *time* number and no recovery *point* number. | `git grep -cIE '\bRPO\b' origin/main -- docs kit scripts deploy` → **0**. Same for `RTO`. The only number acting as one is `max_age_hours: 24` at `ops/config/offsite_backup.yaml:26`. | The declared worst case is **24 hours of orders lost** and nobody has ever said so out loud. Needs clause **A8**, with a number, and a drill that measures it. |
| **F2** | **We drill the planned move and never the unplanned one.** All three gold-standard scenarios assume a live source. Two angles agree. The datastore adapter (on PR #585, not yet on main) calls `t_pack` on `$FROM`, so a dead source produces no seed; and the target contract itself defines `t_pack` as *"pack this platform's store, for when it is the SOURCE of a move"* (`deploy/PORTABILITY.md:40`) — there is no verb at all for a source that is gone. | The programme is called migration **and DR** and only builds the first half. Needs scenario **G4: the source is gone**, whose only legal input is the offsite copy. |
| **F3** | **The progress stream is the highest-value thing in the platform, not a progress bar.** | DORA 2025: the platform capability most correlated with a positive user experience is *clear feedback on the outcome of my tasks*. Our A4 already says no step may go ≥ 5s without an event. | A4 gets built to the same bar as an adapter, with tests, not added afterwards as a console veneer. |
| **F4** | **An adapter that has never run in a drill is not finished.** | **9 of 10** class adapters do not exist on `origin/main`: `kit/classes/` holds `compute.sh` and `MISSING.md`, whose 9 entries name the rest. PR #585 takes it to 3 of 10. **0** end-to-end drills have been run against any of them. | "Done" for the rest means a scheduled drill has executed them, not that the file exists. |

---

## Part 1. The ten principles

### PE1. The platform is a product, and its customers are the agent sessions

The CNCF maturity model puts "as product" at level 3 of its **Investment** aspect, and level 5
overall is *Platform as a Product* — every feature judged on its value to users and its cost in
platform simplicity. Team Topologies says the same in one sentence: platform teams see other
delivery teams as their customers.

Here the customers are unusual and naming them changes the design. They are **the autonomous
sessions working this estate**, plus the founder at the console. A session cannot read a wiki, does
not remember yesterday, and cannot be trained. So every affordance a human customer would get from
documentation, this platform has to get from a refusal, a probe or an event.

- Steers: **A4** (from the dashboard), **A7** (n projects).
- Test: `docs/PLATFORM_MANIFESTO.md` Part 4's automation audit — a step still needing a human is a
  ticket, not a design.
- Source: [CNCF Platform Engineering Maturity Model](https://tag-app-delivery.cncf.io/whitepapers/platform-eng-maturity-model/),
  [Team Topologies — platform engineering](https://teamtopologies.com/platform-engineering).

### PE2. Thinnest viable platform — ten classes is the platform, and the eleventh is a declaration

A TVP is *the smallest set of APIs, documentation and tools* that accelerates the teams building on
it. The balance is explicit in the definition: small enough to stay cheap, large enough to actually
remove work.

Our ten resource classes (`kit/projects/schema.py:46`) are that set. The pressure will always be to
add an eleventh for a thing one project needs. The answer is almost always a **declaration**, not a
class: `kit/projects/<name>.yaml` is where a project's peculiarities go.

- Steers: **A5** (0 product names under `kit/`), **A7**.
- Test: `tests/unit/test_kit_names_no_product.py`; and `§6` of the build spec, the list of what we
  deliberately do not build.
- Source: [Team Topologies — What is a TVP](https://teamtopologies.com/key-concepts-content/what-is-a-thinnest-viable-platform-tvp).

### PE3. Golden path, or the platform is not adopted

The 2026 State of Platform Engineering report puts the failure rate of platform initiatives without
a golden path at 70%. The CNCF **Adoption** ladder is the same idea graded: *erratic* → *extrinsic
push* (people are told to use it) → *intrinsic pull* (people use it because it is the easy way) →
*participatory*.

The honest reading of our own estate: a session migrates a resource by reading a doc and running
commands. That is level 1. The console page that compiles a plan and runs it is the golden path,
and until it exists we are pushing, not pulling.

- Steers: **A4**.
- Test: the measurement is behavioural — does a session that was never told about the console still
  end up using it? Nothing tests this today. That is honest, not comfortable.
- Source: [State of Platform Engineering Vol. 4](https://bex.co/blog/2026/08/06/platform-engineering-report-vol-4-golden-path).

### PE4. Two numbers, not one: RTO and RPO

AWS Well-Architected REL13 defines both. **RTO** is the maximum acceptable delay between
interruption and restoration. **RPO** is the maximum acceptable interval of data loss. They are
independent, they cost different money, and a plan with only one of them is half a plan.

We have an RTO — 1800s, clause A1 — and no RPO at all (F1). See Part 3.

- Steers: a new **A8**.
- Test: the drill has to stamp both; today it stamps one.
- Source: [AWS Well-Architected REL13](https://docs.aws.amazon.com/wellarchitected/2025-02-25/framework/rel-13.html).

### PE5. Pick the DR strategy per resource, and say which one each is on

AWS names four, in ascending cost: **backup and restore**, **pilot light**, **warm standby**,
**multi-site active-active**. Aggressive RTO/RPO buys complexity and money; relaxed targets buy
simplicity.

The useful move for us is that this is a **per-resource** choice, not one strategy for the estate,
and our own classes already imply different answers. The order database wants warm standby and
cannot have it while it is a single-attach SQLite volume. The engine store is genuinely
backup-and-restore and that is correct — a lost hour of dossiers is not a lost hour of orders.

- Steers: `CLASS_DOWNTIME` (`kit/projects/schema.py:64`) — which today records *how visible* a
  pause is, and should also record *which strategy the class is on*.
- Test: none yet.
- Source: [AWS DR strategies](https://aws.amazon.com/blogs/architecture/disaster-recovery-dr-architecture-on-aws-part-i-strategies-for-recovery-in-the-cloud/).

### PE6. Untested recovery is not recovery

Google's DiRT programme has run since 2006 on exactly one premise: controlled failures expose the
dependencies nobody wrote down. Their own account of it is blunt — sometimes assumptions and actual
results are worlds apart, and a bug found during an exercise can leave a service where recovery is
*not automatic, easy, or even documented*.

This is why `scripts/restore_drill.py` (584 lines) is worth more than any document in this repo: it
opens the backup and asserts five properties with receipts. It is also why F4 is a finding rather
than a nicety.

- Steers: the definition of done for the remaining adapters.
- Test: `scripts/restore_drill.py` for the engine store. Nothing equivalent exists per class.
- Source: [Google DiRT](https://www.oreilly.com/library/view/chaos-engineering/9781492043850/ch05.html),
  [Google Cloud — SRE principles for business continuity](https://cloud.google.com/blog/products/management-tools/sre-principles-in-practice-for-business-continuity).

### PE7. Clear feedback on the outcome of a task is the top-ranked capability

DORA's 2025 data found the platform capability most correlated with a positive user experience is
*clear feedback on the outcome of my tasks* — logs, diagnostics and status that let the user
self-serve rather than ask.

Our A4 already encodes this by accident ("no step ≥ 5s without an event"). PE7 says it is not a
nice progress bar; it is the single feature most likely to decide whether this platform is used.

- Steers: **A4**, and the event stream in `§3.3` of the build spec.
- Test: the drill fails on any gap ≥ 5s.
- Source: [DORA — platform engineering capability](https://dora.dev/capabilities/platform-engineering/).

### PE8. Platform quality is the amplifier — this estate is the finding in miniature

DORA 2025's headline is that AI adoption raises throughput **and instability together**, and that
platform quality decides which one you get: with a high-quality platform the effect of AI on
organisational performance is strong and positive; with a low-quality one it is negligible.

This estate is that experiment at n=1. Sessions produce diffs faster than any human team here
could, and every guard in `~/.claude/scripts/` and every gate in `scripts/popdd_verify.py` exists
because instability arrived with the throughput. The research says those guards are not overhead —
they are the thing that converts the throughput into anything at all.

- Steers: the whole working method, and the answer to "why are we spending time on gates".
- Test: `.venv/bin/python scripts/popdd_verify.py --staged`.
- Source: [DORA 2025 via Platform Engineering](https://platformengineering.com/features/dora-2025-ai-wont-save-you-without-a-solid-platform/),
  [IT Revolution on the 2025 report](https://itrevolution.com/articles/ais-mirror-effect-how-the-2025-dora-report-reveals-your-organizations-true-capabilities/).

### PE9. Measure the platform, quantitatively and qualitatively

The CNCF **Measurement** ladder runs *ad hoc* → *consistent collection* → *insights* → *quantitative
and qualitative*. We are good at the quantitative half — every claim in this programme carries a
command — and we have no qualitative half at all, because our users are sessions and nobody has
asked one what was hard.

The cheap version of the missing half: when a session trips over the kit, the trap goes on the
board. That is a user interview conducted by other means.

- Steers: nothing yet. Named so it is not mistaken for solved.
- Source: [CNCF maturity model](https://tag-app-delivery.cncf.io/whitepapers/platform-eng-maturity-model/).

### PE10. Self-service means the platform refuses, rather than the operator remembering

CNCF **Interfaces**: *custom processes* → *standard tooling* → *self-service solutions* →
*integrated services*. The step from level 2 to level 3 is where a runbook becomes a button.

Our version of that step has a specific shape, and it is already load-bearing: the plan compiler
**refuses** rather than warns (`kit/migrate/plan.py:15` — anything that is not a step and not an
admitted skip exits 78, before anything has been stopped or packed). A platform that warns is a
platform whose safety depends on the operator reading. Ours must not.

- Steers: **A2** (0 resources left behind).
- Test: the plan-admits-what-it-cannot-run suite, on PR #563, not yet on main.
- Source: [CNCF maturity model](https://tag-app-delivery.cncf.io/whitepapers/platform-eng-maturity-model/).

---

## Part 2. Where we actually sit on the CNCF model

Scored conservatively, with the evidence. Four levels: Provisional, Operationalized, Scalable,
Optimizing.

| Aspect | Level | Why, measured |
|--------|-------|---------------|
| **Investment** | 2 — dedicated | One session's declared lane is platform migration/DR. Not "as product": no roadmap the customers can read, no feature ever removed on purpose. |
| **Adoption** | 1 — erratic | No golden path yet (PE3). Migration is done by reading a doc and running commands. |
| **Interfaces** | 2 — standard tooling | Four target adapters behind one twelve-function contract (`deploy/PORTABILITY.md:40`); one of ten class adapters exists on main, three once PR #585 lands. Self-service is the console page that does not exist yet. |
| **Operations** | 2 — centrally tracked | 32 launchd plists, an issue per gap, a probe that refuses to read its own declaration as truth. Not level 3 until a fresh machine can install the lot from a declaration (issue #590). |
| **Measurement** | 2/3 — consistent collection, some insight | Every claim carries a command; nothing collects the qualitative half (PE9). |

Nothing here is level 4, and nothing should be pretending to be. The honest summary is
**Operationalized, with Adoption lagging a level behind everything else** — which is the classic
shape the CNCF model warns about, a platform built faster than it is adopted.

---

## Part 3. What the research changes, concretely

### 3.1 A new clause A8 — the RPO, with a number

The bar has seven clauses and every one of them is about *time* or *completeness*. None is about
*loss*. Proposed, for the founder's ruling:

> **A8 — no order is lost.** Worst-case data loss at the target, per resource, ≤ its declared RPO.
> The money database's RPO is the tightest and it is the one that is currently implicit.

Today's honest number is **24 hours** for the order database, because `max_age_hours: 24`
(`ops/config/offsite_backup.yaml:26`) is what makes the monitor go red, and the offsite copy is the
only copy that leaves Fly. For a *planned* migration the effective RPO is 0 — the cutover recopies
after the source stops. For an *unplanned* one it is up to a day of orders.

Those two numbers being 24 hours apart, with only the second one ever written down, is the finding.

### 3.2 A fourth scenario G4 — the source is gone

G1 (EKS), G2 (a small VPS) and G3 (on-prem) all differ in **where we are going**. None of them
differs in **what we still have**. Add:

> **G4 — the source is gone.** Fly is unreachable or the account is closed. The only inputs are the
> offsite bucket and the declarations. Same 1800s, same completed purchase at the end.

This is the scenario the founder's own words cover — *"everything running in this nachine because i
also have a new laptop"* is a machine that may be dead, not politely retired — and it is the one
the kit cannot execute today (F2).

`scripts/restore_drill.py` is the seed of it. What it does not cover is everything that is not the
engine store.

### 3.3 The event stream is promoted to first-class

Not a UI task queued behind the adapters. Same bar, same tests, on the evidence in PE7.

### 3.4 Done, for the remaining adapters, means drilled

An adapter lands with a drill that has run it at least once, or it is not counted. This is PE6
applied to the thing on the critical path right now.

---

## Ledger

| Date | Change |
|------|--------|
| 2026-08-21 | Written. Ten principles, five-aspect self-score, four findings. Sources are all outside this estate. |
