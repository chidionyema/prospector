# Platform Manifesto

Status: **LAWS ADOPTED. PORTABILITY 60 PERCENT BUILT. AUTOMATION IS THE WEAK HALF.**
Written 2026-08-18. Every number below has the command that produced it on the same line.

This is the constitution. It says what the platform is for, what it is allowed to depend on, and
how an agent is required to work on it. Four other programme docs are the depth:
`docs/ENGINE_MIGRATION_PROGRAM.md`, `docs/LAUNCH_OPS_PROGRAM.md`, `docs/COST_PROGRAM.md`,
`docs/GRAPHIFY_ENFORCEMENT_SPEC.md`. `deploy/PORTABILITY.md` is the engineering contract this
document sets the policy for. Read this one first, then the one that is yours.

Founder, 2026-08-18: *"we really need platform manifesto where we clarify goals, automation, self
healing, little or no human in loop, secure, observable, reliable, stable, free / dirt cheap"* and
*"we have the right idea but poor execution"*. Both halves are in here. The laws are the idea. The
audit in Part 4 is the execution, measured rather than described.

---

## Part 0. The one-paragraph version

We sell packs. The engine that makes them, the store that sells them and the jobs that keep both
alive must run on any Linux box in the world, be movable to another one the same day, cost close
to nothing, heal themselves without waking anybody, and prove every one of those claims on a
schedule rather than in a document. Where a human is still in the loop, that is a defect with a
ticket, not a design.

---

## Part 1. The laws

Ten. Each one is testable, and each names the command that tests it. A law with no test is an
opinion, and this platform has had enough of those.

### L1. Nothing business critical runs on the laptop

The laptop is a development machine and a last-resort target. It is not infrastructure.

- Test: `.venv/bin/python scripts/live_checkout.py` names the machine and the code production is
  actually running.
- Status: **engine and store are off it** (Fly, 2026-08-18). **Hermes is not** — 14 jobs still
  load from `~/Library/LaunchAgents` (`launchctl list | rg -c "hermes|prospector"` = 14).
- The laptop stays a *tested* target, not a forgotten one. `deploy/targets/laptop.sh` is a full
  adapter, which is what makes falling back to it a command rather than a project.

### L2. One artifact, six requirements

The engine is one container image (`deploy/engine/Dockerfile`). A platform must supply exactly six
things: one instance only, a writable directory that survives restart, environment variables,
outbound HTTPS, a way to run a command inside the container, and private access to two ports.

Anything a platform offers beyond those six is lock-in and we do not take it. No managed database,
no platform API called from application code, no hostname baked into the image, no secrets that
live only in one vendor's vault.

- Test: `deploy/PORTABILITY.md` carries the list. The compose file
  (`deploy/compose/docker-compose.yml`, four services: engine, api, web, runner) is the proof that
  the same image boots with nothing but Docker.

### L3. Free, or dirt cheap, and the cost is declared

Default to free. Where money is unavoidable it is a declared line with a ceiling and an automatic
brake, never a surprise on a card.

- Live brakes: `spend.daily_cap_usd` read from the persistent ledger; `store/scheduler/PAUSE` as a
  filesystem kill switch; self-hosted CI runners so CI minutes cost nothing.
- Test: `docs/COST_PROGRAM.md` is the ledger of every lever and every measurement.
- Standing founder constraints, both still in force: do not flip CI to GitHub-hosted runners, and
  do not buy Anthropic credits.

### L4. Open source unless paid is provably cheaper

Not open source as ideology. Open source because a component we can host is a component that
cannot be discontinued, repriced or rate-limited out from under us. SearXNG (`deploy/searxng/`)
over a paid search API is the pattern: we run it, so nobody can take it away.

A paid dependency needs a written reason, a monthly figure, and an exit adapter before it ships.

### L5. Anything that happens more than once a week is a job, not a person

If a human does it twice, it becomes a scheduled job with an owner, a receipt and an alarm. If it
cannot be automated, that is written down as an exception with the reason.

- Test: `ops/config/human_register.yaml` is where the remaining human steps are declared.
- This is the law with the worst compliance today. See Part 4.

### L6. State is a probe, never a paragraph

The live answer to "is it working" is always a command. A document that asserts status is wrong
within a week and nobody notices.

```bash
bash ~/.hermes/scripts/verify_estate.sh          # the whole estate
.venv/bin/python scripts/live_checkout.py        # is production running the code we think it is
.venv/bin/python scripts/ops_status.py           # readiness grades
```

### L7. A rail that is not drilled does not exist

Backups, failover, escape hatches and rollbacks are things you find out are broken on the day you
need them. Every one runs on a schedule, unattended, and fails loudly.

- Live: `.github/workflows/escape-hatch-drill.yml`, Sunday 04:00 UTC. It packs the live store off
  the platform through the adapter's own `t_pack` verb and verifies the payload.
- Receipt that this law is real: the first rehearsal on 2026-08-18 failed four verbs out of ten,
  and every failure was the drill rig rather than the adapter. None of it was visible before the
  drill ran.

### L8. Heal first, page second, dashboard third

In that order. A dashboard that shows a red light nobody is looking at is not observability. An
alert for something the system could have fixed itself is a design failure.

- Today the order is inverted: we have consoles, some alerting, and very little healing. Part 5
  is the plan to invert it back.

### L9. Secrets are declared once, never printed, never in git

One list (`deploy/secrets.required`, 11 entries), one push mechanism (`t_secrets`), one check
(`bash deploy/secrets.sh check`) that fails *before* a machine boots rather than after.

- Receipt that the check earns its place: the move to a live checkout benched every provider with
  `All operators unavailable` because `.env` was simply not there.
- **Outstanding breach**: `PROSPECTOR_ENTITLEMENTS_API_KEY` and `STORE_INTERNAL_API_KEY` were
  printed into a session transcript on 2026-08-18 by a `/proc/<pid>/environ` read. Both need
  rotating. Rotating them is the test that this law is enforced rather than admired.

### L10. Every claim carries a receipt

A `file:line`, command output, or a runnable test, in the same breath as the claim. Otherwise the
claim is labelled HYPOTHESIS with the exact check that would settle it. This applies to humans,
to agents, to commit messages and to this document.

### L11. No flaky solutions

Founder, 2026-08-19: *"dont want flaky solutions ... never go for flaky solutions"*. He said it
after reading five of our own proposals back to us, and he was right about all five.

A solution is FLAKY if any one of these is true. They are the test, and every proposal is graded
against them before it is accepted, not after it is built.

1. **It depends on the thing it protects.** A watcher on the machine it watches dies with it. A
   backup in the same account as the data. A gate that runs inside the process it gates.
2. **It can fail silently.** If the failure looks like success, or like noise, or like somebody
   else's bug, nobody acts on it. Every mechanism must answer: what fails, loudly, and who is told?
3. **Nothing measures it.** A number in a plan is a claim. A target with no clock, a rail with no
   drill, a budget with no meter: those are wishes, and a wish is flaky by construction.
4. **It moves the single point of failure instead of removing it.** Off the laptop and onto one
   Fly machine is progress. It is not redundancy, and it must never be written down as if it were.

**Grade honestly and say so.** SOUND, FLAKY or UNPROVEN, with the evidence. UNPROVEN is an allowed
answer and usually the true one. SOUND without a receipt is not.

**A flaky solution is worse than no solution**, because it also spends the attention that would
have found the real one. The autoscaler is the worked example: written, reviewed, merged, and it
had never once run. See [`docs/STACK_FLAKINESS_AUDIT.md`](STACK_FLAKINESS_AUDIT.md).

**Justification before decision** (same directive, same day: *"i need justifications alo outputted
before final decsion"*). The argument is written out and shown FIRST. The decision line comes after
it and refers to it. A decision presented without its argument cannot be challenged, so it gets
re-litigated every time somebody new reads it.

### L12. Emitting is not observing

Founder, 2026-08-19: *"we log but no cetral place to view"*. And two months earlier, in
`specs/observability-gap-search.md`: *"we cannot be guessing; we must log and observe thoroughly;
we must prevent this from ever happening again."*

**A signal with no consumer is not evidence.** It is the appearance of evidence, which is worse
than nothing, because it stops anyone looking further.

Three instances in this estate, all the same defect:

1. `web_calls=0` — a metric shipped that no provider ever incremented. We then used it to decide
   whether search was working. It was working.
2. launchd jobs exiting non-zero for days. Nothing reads the second column of `launchctl list`, so
   `com.prospector.backup` has been failing with exit 78 unnoticed.
3. Backups graded by the writer's exit code, which proves the job ran and not that bytes landed.

**So when anything emits a signal, name its consumer in the same change.** Who or what reads this,
where does it surface, and what happens when it goes bad? If the answer is "somebody would notice",
there is no consumer and the signal is decoration.

**And prove the consumer by breaking it.** A red that has never been seen red is not known to work
— the negative-fixture standard the test suite already holds itself to, applied to operations.

---

## Part 2. Agent tenets

Founder, 2026-08-18: *"ensure all agents across all sessions bear tenets in mind"*.

These bind every agent in every session, in this repo and outside it. The short form is carried
in `~/.claude/CLAUDE.md` so a session in any project loads them at start. Where a tenet and a
convenience disagree, the tenet wins.

**The long form is [`docs/WAYS_OF_WORKING.md`](WAYS_OF_WORKING.md)**: 25 rules, each one a named
failure the founder has watched recur "dozens of times a day if not hundreds". Read that one when
you want the detail, and `scripts/session_check.py` before you stop working.

### T1. Never make the same mistake twice

An incident is not closed when the symptom stops. It is closed when there is a memory file naming
the trap and, wherever the failure can recur mechanically, a test that fails if it does.

- The mechanism already exists: `~/.claude/projects/<slug>/memory/` with an index in `MEMORY.md`,
  re-injected at session start by `~/.claude/scripts/memory-loop.py`.
- The tenet is the discipline of *writing the file at the moment of the lesson*, not later. Memory
  written later is memory not written.
- A trap that cost time gets `!` in the index. That prefix is the difference between a note and a
  warning.

### T2. Follow the root cause chain to the end

Fix the thing that broke, then ask what let it break, and keep going until the answer is a class
of failure rather than an instance. Stop when the next link is a decision somebody has to make,
and then say so plainly.

Worked example from this estate, four links deep: the ops console showed blank tabs → the console
API returned an error → the read model needed a store DB that was not there → the store path was
derived from `__file__`, so it followed the *code* rather than the *store*. The instance was a
blank tab. The class is "never derive a state path from `__file__`", which is now a rule in
`CLAUDE.md` and a resolver (`config.store_root()`).

Reporting the first link and stopping is the failure mode this tenet exists to kill.

### T3. Get better at getting better

The loop that improves the work is itself work, and it gets measured like anything else. Every
week, at least one of: a rule that stopped a repeat failure, a script that removed a manual step,
a measurement that killed a belief nobody had checked.

The honest state of this tenet today: the self-improvement machinery exists and is largely
write-only. Memory `otto-learning-loops-are-write-only.md` records loops that log what they would
have learned and change nothing. That is the target of Part 4.

### T4. Fix it, do not report it back

A defect found inside work already in progress gets fixed in the same turn. The only things
surfaced unfixed are a founder decision, a permission that is refused, or another session's work.

### T5. Answer first

`DONE:` / `BLOCKED:` / `WORKING:` and one plain sentence, under 150 words above the fold. Evidence
below the line, and only when it changes what happens next.

### T6. Prove it or mark it unproven

No verdict from memory. Memory and checkpoints are leads. Re-verify on disk before stating
anything as current fact. Comparisons are claims: "better" and "faster" need the scenario where
one breaks and the other does not.

### T7. Plain English

Say what happened, in order, in short sentences. No aphorisms as headlines, no dramatic reveals,
no personification. This applies to chat, commits, PR bodies, code comments and docs.

### T8. Never sit and watch a long command

Anything that can exceed thirty seconds starts in the background, and the next independent piece
of work starts immediately. Never poll a backgrounded run.

### T9. One round trip per intent

Before issuing a tool call, ask what else this turn needs and send it in the same call. A
verification chain is one command, not six.

### T10. Nothing is left uncommitted

Work written in a scratchpad worktree gets committed and pushed in the same turn. Founder,
verbatim: *"sorry don't ever do this again, this is irresponsible"*.

---

## Part 3. Portability: what is built, what is missing

The founder asked for a range of targets: on-prem, laptop as last resort, AWS, Azure, GCP, Fly,
DigitalOcean and cheaper players. **The measured position is better than the task list said.** The
substrate is built. What is missing is proof and breadth, not architecture.

### What exists today

| Piece | Where | State |
|---|---|---|
| The contract, six platform requirements | `deploy/PORTABILITY.md` | Written, 108 lines |
| Adapter interface, eleven verbs | `deploy/targets/*.sh` | Built |
| Fly adapter | `deploy/targets/fly.sh` | In production |
| Laptop adapter | `deploy/targets/laptop.sh` | Tested, is the rollback path |
| Any Linux box with Docker and SSH | `deploy/targets/sshdocker.sh` | Built, **never booted in anger** |
| Move between any two targets | `deploy/cutover.sh --from X --to Y` | Built |
| Pure-Docker stack, four services | `deploy/compose/docker-compose.yml` | Built, checked by CI |
| State as a portable tarball with a manifest | `scripts/store_migrate.py` | Built, drilled weekly |
| Secret list and preflight | `deploy/secrets.required`, `deploy/secrets.sh` | Built, 11 entries |
| Weekly escape drill | `.github/workflows/escape-hatch-drill.yml` | Live, Sunday 04:00 UTC |

### The insight that shrinks the job

`sshdocker.sh` is not one target. **It is AWS EC2, Azure VM, Google Compute Engine, a DigitalOcean
droplet, Hetzner, a Mac mini in an office, and a Raspberry Pi**, because all seven are the same
thing: a Linux box with Docker and an SSH login. We do not need seven adapters. We need one more
adapter shape and evidence that the one we have actually boots.

The second shape is the managed container service, where there is no SSH: AWS App Runner or ECS
Fargate, Azure Container Apps, Google Cloud Run. Those need `t_exec` and `t_put` implemented
through the vendor CLI rather than a shell. That is one adapter per vendor, roughly a hundred
lines each, and it is the only real remaining engineering.

### The target matrix, and what each costs

Prices are list prices for the shape the engine needs: one small always-on instance plus a few GB
of persistent disk. They are HYPOTHESIS until a drill produces a bill.

| Target | Adapter needed | Rough monthly | Why it is on the list |
|---|---|---|---|
| Fly.io | `fly.sh`, built | ~$5 | Where production is now |
| Any Linux VPS (Hetzner, OVH, cheap hosts) | `sshdocker.sh`, built | €4 and up | The cheapest credible floor |
| On-prem box (Mac mini, NUC, Pi) | `sshdocker.sh`, built | electricity | No vendor at all. The true escape hatch |
| DigitalOcean droplet | `sshdocker.sh`, built | ~$6 | A named cheap player with a sane API |
| AWS EC2 / Azure VM / GCE | `sshdocker.sh`, built | ~$10 and up | Enterprise credibility, same shape |
| AWS App Runner, Azure Container Apps, Cloud Run | **not built** | scale-to-zero, near free at our volume | No SSH. Needs the second adapter shape |
| Laptop | `laptop.sh`, built | £0 | Last resort only, by L1 |

### The drills, and why they must be free

Founder constraint, verbatim: *"no on real EC2 hardware no"*, *"i didnt authorise that"*. A drill
that needs a rented box runs never, and a drill that runs never proves nothing. So every drill
below runs on hardware we already pay for or on CI minutes that cost nothing.

| Drill | What it proves | Cadence | State |
|---|---|---|---|
| Escape hatch | The state can leave the platform intact | Weekly, Sunday 04:00 UTC | **Live** |
| Compose boot | The image runs with nothing but Docker | Every change, in CI | **Live** |
| Cold restore | A packed tarball unpacks and the engine starts against it | Monthly, in CI | **Not built** |
| Full cutover rehearsal | `cutover.sh --from fly --to sshdocker` end to end, into a local Docker target on the laptop | Monthly | **Not built** |
| Rollback rehearsal | The same command with the ends swapped | Monthly | **Not built** |
| Secret drill | A fresh target filled from the encrypted store alone, no laptop `.env` | Quarterly | **Not built** |

The three "not built" monthly drills are the highest-value portability work outstanding. They cost
CI minutes and a local Docker daemon, and they turn a claim into a receipt.

---

## Part 4. The automation audit, measured

Founder, verbatim: *"we have the right idea but poor execution with hermes agent, autonomous
healing, self improvement, autonomous work, all the claude scripts to improve ways of working, all
founder complaints, all the little tools we have built but don't work"*.

That is correct, and here is the measurement rather than agreement.

| What | Count | Command |
|---|---|---|
| Hermes scripts (`.py` + `.sh`) | **227** | `ls -1 ~/.hermes/scripts/*.py ~/.hermes/scripts/*.sh \| wc -l` |
| Launch agents installed on the laptop | **58** | `ls -1 ~/Library/LaunchAgents \| wc -l` |
| Of those, actually loaded | **14** | `launchctl list \| rg -c "hermes\|prospector"` |
| Plists tracked in this repo | **31** | `ls -1 ops/launchd \| wc -l` |
| Repo files nothing else refers to | **219 of 1567** | `.venv/bin/python scripts/estate_census.py` |

**The ratio is the defect.** 227 scripts and 58 installed jobs, of which 14 run. Four out of five
things built to make the platform autonomous are not running, and nothing in the estate can tell
you which four out of five without the commands above. That is not an automation platform, it is
an automation graveyard with a few survivors.

Three named failure patterns, each with its receipt:

1. **Write-only learning loops.** Memory `otto-learning-loops-are-write-only.md`: loops that record
   what they would have learned and change nothing. A learning system that cannot act is a logger.
2. **Built and unreachable.** Memory `built-and-unreachable-is-the-cockpit-defect-class.md`: a
   feature is finished, and no surface reaches it. The console's dead buttons are the same class.
3. **A warning is not a fence.** Memory `a-warning-fence-is-not-a-fence.md`: guards that warn and
   let the thing happen anyway. The pack linter's advisory rules are the same shape, at scale.

### What to do about it, in order

1. **Census the automation the way we censused the repo.** One read-only script that lists every
   job in the estate, whether it is loaded, when it last ran, whether it produced a receipt, and
   what it claims to do. Report mode first. This is the cheapest possible next step and it makes
   the other four decidable.
2. **Delete on evidence.** Anything that has not run, or ran and produced nothing, for 30 days is
   proposed for deletion in a second, explicit pass. A person decides; the script only measures.
3. **Consolidate the survivors.** The jobs that earn their place move behind one scheduler with
   one log format and one alarm path, rather than 58 plists each with its own conventions.
4. **Make the loops act.** A learning loop either changes a config value, opens a PR, or is
   deleted. Logging an intention is not a third option.
5. **Then, and only then, add more autonomy.** Adding a self-improving agent on top of a graveyard
   makes a bigger graveyard.

---

## Part 5. Observability: heal, page, dashboard

L8 in practice. This is the design the logging, monitoring and alerting work is built to.

**One log format.** Every job, on every host, writes structured lines with the same keys: when,
what job, what run, what happened, and the receipt. A log nobody can join to another log is a
diary.

**One retention policy, enforced by a job.** `ops/config/log_rotation.yaml` exists; the policy that
governs it is not written. Retention that is not enforced is a disk that fills at 3am.

**Three levels, in the order the platform should try them:**

1. **Heal.** The system tries the fix itself: restart the wedged consumer, re-probe the benched
   provider, re-drive the stranded pack. Every heal writes a receipt, so that healing is visible
   rather than a silent mystery. A heal that fires repeatedly is itself an alert.
2. **Page.** Only what a human must decide. Money stopped, data at risk, a customer blocked, or a
   heal that failed twice. This is the level that is broken today: outages are *reported* and
   nobody is *paged* (task 16).
3. **Dashboard.** For understanding after the fact and for trends. It is where you look when you
   already know something is wrong, never how you find out.

**The alert test.** For every alert, two questions must have answers before it ships: what will the
human do when it fires, and why can the system not do that itself? An alert that fails the second
question is a heal that was not written.

---

## Part 6. A daily agent job that moves the platform forward

Founder, verbatim: *"we should have a daily job for claude code to keep pushing us towards our
goals by research and implementing and fixing and optimising etc, not scared to rewrite swathes of
platform or explore tooling or run experiments"*.

The shape that fits the laws above:

- **It reads the ledgers, it does not invent work.** The queue is the status tables in the
  programme docs plus the open task list. The job picks the top unblocked item.
- **It works in an isolated worktree**, so it can never collide with a live session's index.
- **It ends in a pull request, never a push to `main`.** Automerge on green CI already exists, so a
  correct change lands without a human and an incorrect one does not.
- **It is bounded before it starts**: a token ceiling, a wall-clock ceiling, and a hard rule that
  money, identity, contract and migration code are proposed but never merged unattended.
- **It reports one line.** What it picked, what it changed, and the receipt. A daily job that
  writes an essay will not be read by day four.
- **It is drilled like any other rail** (L7): a weekly check that it actually opened a PR. A daily
  job that silently stopped is the exact failure mode this platform keeps producing.

Experiments are explicitly in scope, on one condition: an experiment ends with a measurement that
kills it or promotes it. An experiment that ends with a document is a document.

---

## Part 7. The two things we have not automated at all

### Marketing

Measured: nothing exists. `rg -li "marketing"` across the repo returns docs and unrelated modules,
no pipeline. Every buyer we get today arrives by accident.

The pipeline that fits this platform, in the order it should be built:

1. **Distribution is already half-built and unused.** The engine writes a listing and prints
   syndication intent on PASS. Turning intent into posted content is one job, not a project.
2. **The pack is the marketing asset.** Each pack already contains cited claims and a narrative.
   The extract that becomes a post exists inside the artifact we already generate.
3. **Measure before spending.** No paid channel until an organic one has a measured conversion
   number. L3 applies to marketing before it applies to anything else.
4. **Then close the loop.** Which packs get read, which get bought, which titles get clicked. That
   number feeds generation, which is where the ML belongs.

### Machine learning in the engine

Measured, and thinner than it looks: `prospector/score.py` uses fixed configured weights, and
`prospector/prescreen_prefilter.py` is embedding-based and **wired off in `config.yaml`**. Dedup is
string similarity, not embeddings. There is no learned component in production.

Where learning would actually pay, in order of expected value per pound:

1. **Prescreen.** The cheapest gate sees the most candidates. A learned prefilter that safely drops
   a third of them before any paid call is the single largest cost lever in the engine.
2. **Scoring weights.** Fixed weights are a guess. Sales outcomes are the label. The existing
   two-loop rule protects this: demand tunes what to offer, truth vetoes what may ship, and demand
   never overrides truth.
3. **Title and copy selection.** Which register sells. This needs the marketing loop above to
   exist first, because without outcome data it is a preference, not a model.
4. **Dedup.** String similarity has a known semantic gap (memory `learning-dedup-semantic-gap.md`).

The fence stays: **learning may rank, price within the declared ladder, and filter. It may never
rule a verdict.** A verdict is grounded in cited passages or it does not exist.

---

## Part 8. Status ledger

Append here. Never in `CLAUDE.md`.

| Item | State | Next action | Receipt |
|---|---|---|---|
| The ten laws | Adopted 2026-08-18 | Enforce on every review | this file |
| Agent tenets | Adopted 2026-08-18 | Short form into `~/.claude/CLAUDE.md` so every session loads them | Part 2 |
| Portability substrate | Built | Nothing | `deploy/PORTABILITY.md`, `deploy/targets/*.sh` |
| Escape hatch drill | Live weekly | Watch Sunday runs | `.github/workflows/escape-hatch-drill.yml` |
| Cold restore drill | **Not built** | Build it, monthly, in CI | — |
| Cutover and rollback rehearsal | **Not built** | Build it against a local Docker target | — |
| Managed container adapters (Cloud Run, ACA, App Runner) | **Not built** | One adapter, then the other two are copies | — |
| Automation census | **Not built** | Highest-value next step in Part 4 | 227 scripts, 14 loaded |
| Logging policy | **Not written** | Part 5 is the design; write the policy, then the job | `ops/config/log_rotation.yaml` exists |
| Paging | **Broken** | Outages report, nobody is paged | task 16 |
| Daily agent job | **Not built** | Part 6 is the shape | — |
| Marketing pipeline | **Does not exist** | Step 1 of Part 7 | `rg -li marketing` finds no pipeline |
| Learned prescreen | **Wired off** | Measure the drop rate it could achieve before building | `prescreen_prefilter.py` |
| Secret rotation after the transcript leak | **Outstanding** | Rotate two keys | L9 |
