# Decoupling programme — generation runs continuously, verdicts run on a schedule

> Tracked spec. Founder directive, 2026-08-15: *"we should always be generating decoupldd fron
> verifiction and verdict, generaton cn run continuously and the rest can happen on schedule"* /
> *"the current architecture is too coupled and brittle"* / *"we should never get to hours"*.
>
> Read this before touching `run_signal` or the scheduler tick. Append results HERE, not to
> `CLAUDE.md`. Sibling specs: `docs/COST_PROGRAM.md`, `docs/GRAPHIFY_ENFORCEMENT_SPEC.md`,
> `docs/SITE_SPEC_PROGRAM.md`.

## Status ledger

| Stage | What it proves | State |
|---|---|---|
| 0 — Measure the loss | A number for "candidates destroyed per force-exit" | **not started** |
| 1 — Spool, write-only | Every candidate exists on disk before it is judged | **not started** |
| 2 — Consumer, read-only | A spooled candidate vets to the same dossier | **not started** |
| 3 — Cut the wire | A force-exit during generation loses zero candidates | **not started** |
| 4 — Continuous generation | Spool depth stays bounded over 24h | **not started** |

Landed already (2026-08-15, this is the mitigation, **not** the fix): generation's three nested
unbounded joins are now bounded by `deadline_mono` — `prospector/generate.py::_budget_left`,
`_fan_out`, `generate_multilane`, pinned by `tests/unit/test_generation_cannot_eat_the_whole_tick.py`
including a falsifier that restores the pre-fix `as_completed(timeout=None)` call and asserts it
hangs. That stops generation eating a tick. It does not decouple anything.

---

## 1. The defect, in one sentence

**A candidate has no representation on disk until it has a verdict**, so the process that generates
it must also be the process that judges it, inside one tick, under one deadline.

Proof, not assertion:

- `prospector/store.py:210` — `def save(self, dossier: Dossier) -> Path:` is the only save. Its
  argument is a **Dossier**, which by construction already carries a decision. There is no
  `save_candidate`, no candidate spool, no queue file.
- `prospector/run.py:900` — `run_signal` is one in-memory pipeline: `generate` (`:1109`) → `dedup`
  (`:1169`) → `prescreen` (`:1215`) → `select_diverse_candidates` (`:1254`) → `vet_candidate`
  (`:1295`). Every hand-off is a Python object. Nothing is durable until `store.save` runs inside
  `vet_candidate` (`run.py:862`), i.e. *after* the verdict.
- `prospector/scheduler/run_scheduled.py:901` — the daemon's entire unattended batch is **one**
  `run_signal(...)` call.
- `prospector/scheduler/run_scheduled.py:1052` — `os._exit(2)`. The 3-hour deadline
  (`_TICK_HARD_DEADLINE_S`, `:939`) does not cancel a phase; it kills the process so launchd
  relaunches it.

Consequence, observed three times in `store/scheduler/ticks.jsonl`
(2026-08-13T15:54, 2026-08-14T17:48, 2026-08-14T21:21):

```
tick_hard_deadline: exceeded 10800s during generation (batch=15); force-exited for relaunch
```

Every candidate generated in those three hours was in memory. `os._exit(2)` took all of them, plus
the drain, the decay/SLA sweep, artifacts and publish that were queued behind generation.

### The tell that we already knew

`run_scheduled.py:855-876` orders the drain **before** generation, and says why in its own comment:

> *"a backlogged candidate is cheaper to finish than a new one is to create (generation and prescreen
> are already spent on it), and the tick's hard deadline can force-exit mid-tick — whatever runs
> second is what gets dropped."*

That is phase ordering used as armour against our own architecture. We are choosing which half of
the daemon to sacrifice. A spool removes the choice.

---

## 2. Where the wire gets cut

**Cut after `dedup`.** Generation's job ends at: signal → `generate` → `dedup` → durable spool write.
Everything after (`prescreen`, `select_diverse_candidates`, `verify`, `kill_filter`, `score`,
`dossier`, `publish`) belongs to the consumer.

Why there, and the trade-off named honestly:

- `dedup` (`dedup.py`) is **pure-local** — `difflib.SequenceMatcher` + token Jaccard, no network, no
  model. It cannot hang, so it cannot make generation unbounded. It is also the thing that stops the
  spool filling with the same idea forty times.
- `prescreen` is an **LLM call** on the non-critical chain. It can hang and it can be down
  independently of the moat. Anything that can hang must be on the consumer side of the spool, or
  "generation runs continuously" is a lie the first time MiniMax stalls.
- The cost of cutting here: the spool holds candidates that prescreen would have rejected, so it
  holds more rows than the minimum. That is the correct direction to be wrong — spool rows are cheap
  (a JSON object); a stalled generator is not.

**The spool row must carry, not just the candidate:** the ambition tier/lane, **the market it was
generated under**, the config fingerprint, and `created_at`. The market is load-bearing —
`run_scheduled.py:876`'s comment already establishes that re-vetting under a different market
"would change the question it is being asked", which is why the drain keeps `active_market` while
only new batches rotate. A spool row vetted an hour later by another process must be asked its own
question.

**Mechanism, using what already exists — no new infrastructure.** `prospector/claim_lock.py` and
`prospector/jsonl_atomic.py` are in the repo. One file per candidate under `store/spool/`,
content-addressed (the same key discipline as `store/listings_archive/`), claimed by atomic rename
with a **lease that expires**, so a consumer killed mid-vet returns its row to the queue instead of
stranding it. States: `pending → claimed(lease) → done(dossier written)`.

Out of scope by project rule: no Redis, no Celery, no broker. *"No hosted service / no API-key calls
beyond this repo."* The spool is files in `store/`.

---

## 3. What this actually buys (beyond not losing work)

1. **The moat preflight stops suppressing generation.** Today `_moat_blind_reason`
   (`run_scheduled.py:465`) skips the whole tick when every verdict brain is dead, and that is
   correct *today* because generating into a blind moat mints work nobody can finish. With a spool it
   is no longer correct: a moat outage is precisely when you want to keep generating, because the
   spool drains the moment a brain returns. This is a behavioural gain, not a refactor.
2. **Backpressure gets an honest meter.** `schedule.backlog_cap` and `run.drainable()` watch
   *post-verdict* rows — candidates that already cost a verdict run. Spool depth is the number that
   actually says "generation is outrunning verification", measured before the money is spent.
3. **Two failure domains instead of one.** A retrieval outage stops verdicts and leaves generation
   running. A generation-chain outage stops generation and leaves the spool draining. Today either
   one stops the tick.
4. **k=50 becomes a scheduling problem, not a deadline problem.** Generation can be restarted,
   parallelised across processes, and paced, without any of it holding a vetting budget.
5. **One deadline becomes several honest ones.** `_TICK_HARD_DEADLINE_S` is one 3-hour number
   covering unrelated work. After the cut: generation bounds itself (landed), and verification bounds
   per candidate.

---

## 4. The ways this goes wrong (design these in, do not discover them)

- **The spool becomes a landfill.** Verification is measured slower than generation
  (`operator_complete_json` 41.5s avg × 50052 calls). Continuous producer + scheduled consumer with
  no admission rail = the disk fills. **Generation must pause on spool depth.** This is
  `backlog_cap`, moved onto the right meter. Non-negotiable; ship it in the same stage as continuous
  generation, never after.
- **A spooled candidate ages.** An idea generated under one signal, market and config, vetted a week
  later, was judged against a different world. Needs an explicit TTL, and expiry must be **logged and
  counted**, never a silent drop — a silently discarded spool row is exactly the swallowed-failure
  class this repo just spent a day removing (`tests/unit/test_swallowed_failures_can_only_go_down.py`).
- **Dedup must also see the spool.** Today dedup compares a candidate against the catalogue. With a
  spool there is a third population — *generated but unjudged*. Miss it and the same idea is vetted
  three times at 41.5s a call.
- **Two writers on one store.** Continuous generation plus scheduled verification means concurrent
  processes on `store/`. Write the concurrency tests **first**; `claim_lock.py` exists but its
  guarantees under two live daemons are not currently pinned by a test.
- **Every per-tick counter changes meaning.** "candidates this tick" spans two processes after the
  cut. The tick digest must report spool depth, admit rate and drain rate, or this lands us back in
  the `counters lie` memory cluster (`web-calls-counter-was-structurally-zero`,
  `a-saturated-metric-prints-as-a-confident-null`).

**Fences that do not move:** `MOAT_PRIMARY` / `is_provisional_provider` (`operator.py:1071`) — a
spool consumer still may not finalise on a provisional brain; source-or-die;
verdict-from-retrieval-only; publish-only-on-PASS; PAUSE halts the whole tick. The spool holds
**unjudged candidates only** — it is never a cache of verdicts.

---

## 5. Stages, each with the proof that closes it

**Stage 0 — measure the loss.** Instrument the tick to record, at force-exit, how many candidates
were in memory and unjudged. *Proof: a number for "work destroyed per force-exit".* We cannot state
it today, which is why the 3-hour breach has been discussed as a latency problem rather than a data
loss problem.

**Stage 1 — spool, write-only (shadow).** Generation writes every post-dedup candidate to the spool
**and** continues to vet in-process exactly as now. Zero behaviour change. *Proof: over N ticks,
spool row count == candidates vetted, and the dossiers are unchanged.*

**Stage 2 — consumer, read-only.** A `vet --spool` command that claims and vets spool rows, run by
hand. *Proof: a spool row vetted by the consumer produces the same dossier as the in-process path for
the same candidate.* This is where a market/config-fingerprint bug surfaces, and it surfaces
cheaply.

**Stage 3 — cut the wire.** `run_signal` stops vetting; the generation pass ends at the spool write;
a separate scheduled pass drains the spool. *Proof: `kill -9` the generator mid-run, then count the
spool — zero candidates lost.* That is the assertion the whole programme exists for, and it must be
demonstrated on the before-state too (kill the current daemon mid-generation, show the loss).

**Stage 4 — continuous generation.** Generation becomes its own long-running process with the
spool-depth admission rail. *Proof: spool depth stays under cap across 24h, and generation completes
ticks while every verdict brain is dead-marked.*

---

## 6. What NOT to do

- Do not start at Stage 3. The spool's schema is wrong on the first attempt (market, lane, config
  fingerprint, TTL), and Stage 1 is where that costs nothing.
- Do not remove `_TICK_HARD_DEADLINE_S` as part of this. It is the backstop against a hang we have
  not diagnosed yet; it stops being *load-bearing* at Stage 3, not before.
- Do not treat the 2026-08-15 generation-budget fix as this programme. It bounds a phase. It does not
  make a candidate durable, and durability is the whole point.
