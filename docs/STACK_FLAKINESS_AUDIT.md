# Stack re-audit — flakiness, risk, security, compliance

**2026-08-19.** Founder directive, this session: *"dont want flaky solutions ... never go for flaky
solutions and ensure reaudit across the stack now o flakiness, we have enough data, tooling is ok,
docuennt so not lost but i need justifications alo outputted before final decsion"*, then *"we doni
also eed risk assessenet and ecuroty assesssnet icluded"* and *"conplaince also"*.

This document re-grades what [`STACK_AUDIT.md`](STACK_AUDIT.md) accepted. It adds no new research —
the founder said the data is enough and the tooling is settled. It applies one new test to what we
already decided, and it prints the argument before the decision every time.

The test is [`PLATFORM_MANIFESTO.md` L11](PLATFORM_MANIFESTO.md). A solution is FLAKY if it depends
on the thing it protects, can fail silently, has nothing measuring it, or moves the single point of
failure instead of removing it.

---

## 0. Headline

Nine things were graded. **Two are SOUND, four are FLAKY, three are UNPROVEN.** One of the four is
not a proposal at all: it is already merged and has never worked.

| # | Solution | Grade | The one-line reason |
|---|---|---|---|
| S1 | CI autoscaler | **FLAKY — proven dead** | Merged. 40 of 40 runs failed to start. It has never run once |
| S2 | Healthchecks on `prospector-engine` | **FLAKY** | A dead-man's switch dies with the machine it watches |
| S3 | Dagu on `prospector-engine` | **FLAKY** | 31 jobs move from one laptop to one Fly machine |
| S4 | The agent guards in `~/.claude/scripts` | **FLAKY** | 22 scripts, in no repository, on one laptop |
| S5 | Two datastores, Postgres plus SQLite | **UNPROVEN** | Neither restore path has ever been drilled |
| S6 | The 30-minute migration bar | **UNPROVEN** | Nothing runs a clock, so nothing can pass or fail |
| S7 | "Reusable for any project" | **UNPROVEN** | Every probe we have is prospector-shaped |
| S8 | Runner secret hygiene | **SOUND** | Only a scoped PAT reaches a runner; values never in argv |
| S9 | Storefront legal pages | **SOUND** | `privacy.tsx`, `terms.tsx`, `refund.tsx` are live pages |

Nothing here is a new build. Every fix below is either a sequencing change, a one-line guard, or a
line moved from "done" back to "not done".

**Those nine are the ones that had evidence.** Section 12 is the complete register: all
**thirty-nine** solutions proposed anywhere in this programme, graded the same way. Its headline is
that **thirteen of the fifteen tools picked are not installed and three appear nowhere in the
repository**, so most of the register is UNPROVEN by L11 test 3 rather than by opinion.

---

## 1. Exhibit A — the autoscaler has never run

This is the worked example the new law is written against, and it was found while looking for
something else.

**What we believed.** `.github/workflows/ci-autoscale.yml` sizes the Fly runner pool to the queue.
It was written with a careful comment explaining why it runs on `ubuntu-latest` and not on a
self-hosted runner, it was reviewed, and it was merged to `main`.

**What is true.** Measured 2026-08-19:

```
gh run list --workflow ci-autoscale.yml --limit 40 --json event
  -> [{"e":"push","n":35}]        # 35 runs, every one triggered by push
  -> workflow_job runs in last 40: 0

gh api .../actions/runs/32272034267 --jq .conclusion    -> "failure"
gh api .../actions/runs/32272034267/jobs --jq .total_count -> 0
gh run view 32272034267
  -> "X This run likely failed because of a workflow file issue."
```

Zero jobs, on every run, on every run I checked. The workflow never got as far as executing a step,
so `deploy/runners.sh autoscale` has never been called by CI.

**Why.** The file's only trigger is:

```yaml
on:
  workflow_job:
    types: [queued, completed]
```

`workflow_job` is a webhook event. It is not one of the events that can trigger a workflow. GitHub
therefore rejects the file, and records a failed run against it on every push instead.

**The three failure modes, all four L11 tests, in one artefact.**

1. It failed silently. A red run on a workflow nobody watches, on somebody else's branch, reads as
   noise. Thirty-five of them did.
2. Nothing measured it. There is no counter of "machines started by the scaler", so zero looked the
   same as working.
3. It was written down as done. `STACK_AUDIT.md` reasons about pool cost as if scaling happens.
4. It cost us a wrong diagnosis. Earlier this session I traced a killed CI job to this workflow and
   was wrong, because the workflow cannot run. **That inference is withdrawn.** What stopped machine
   `80e9e0ef100dd8` at 15:46:39Z, 70 seconds into PR #425's `python` job, is still unidentified, and
   the machine has since been destroyed, so its event log is gone with it.

**Justification for the fix.** The class is "a workflow that can never run, failing in a way that
reads as noise". A memory file does not close it, because the next invalid workflow will be written
by a different agent in a different session. A machine can refuse it: `actionlint` parses every
workflow file and rejects an unknown trigger, and it is one CI step.

**Decision — taken, in this commit.** The class is closed with a guard, not a note:
`tests/unit/test_workflow_triggers_are_real_events.py` parses every workflow file and fails if any
`on:` key is not an event GitHub accepts as a trigger. It runs in the python lane every branch
already has to pass, so it reaches every agent, and it handles the YAML 1.1 trap where a bare `on:`
key parses as the boolean `True` — a reader that misses that passes every file vacuously, which is
the same defect wearing a different hat. This is preferred to an `actionlint` CI step because it
needs no new workflow and no new tool in the image.

`ci-autoscale.yml` is now `on: workflow_dispatch`. That makes the file valid and stops the false red
runs while changing no automatic behaviour — the scaler did not run before and does not run now.

**Decision — NOT taken, and it is the founder's.** What should start the scaler automatically. A
`schedule:` cron is simple but GitHub delays crons by 5–15 minutes under load, so the pool lags the
queue. `workflow_run:` on the CI workflow is prompt but reacts to runs rather than jobs, so it
cannot see per-job queueing. The third option is to keep a fixed floor and delete the workflow. Each
has a different monthly cost, so it is a spending decision, not an engineering one.

---

## 2. S2 — Healthchecks on the machine it watches

**Justification.** `STACK_AUDIT.md` §9.2 decided Healthchecks and Dagu run on `prospector-engine`,
on the grounds of no new app and no new provider. Both grounds are good. The placement is not. A
dead-man's switch exists to fire when a machine stops reporting. If it runs on that machine, the
machine stopping also stops the thing that would have told us. This is L11 test 1 exactly, and it
fails the only scenario it was bought for.

The constraint "no new provider" is what forces the bad placement, so the options are:

| Option | Adds a provider? | Survives the engine dying? | Cost |
|---|---|---|---|
| a. Self-host Healthchecks on `prospector-engine` | no | **no** | zero, and it does not work |
| b. healthchecks.io hosted free tier | yes, one | yes | £0, 20 checks |
| c. A scheduled GitHub Actions job that probes the engine | no, GitHub is already load-bearing | yes | free minutes, 5–15 min cron lag |
| d. Self-host on a second Fly machine | no | yes, unless Fly is the outage | ~£3/month |

**Decision — recommended, founder to confirm:** option (c) for the dead-man's switch, because it
removes the dependency without adding a provider, and GitHub is already a hard dependency of this
estate. Option (b) if a 5–15 minute cron lag is judged too slow. Option (a) is withdrawn either way.
Task #97 already exists for this; this section is its argument.

---

## 3. S3 — Dagu moves the single point of failure

**Justification.** 31 launchd jobs on one laptop become 31 Dagu jobs on one Fly machine. That is a
real improvement: declared, versioned, restartable, and off a machine that the founder closes at
night. It is not redundancy, and the risk is that it gets written down as if it were, which is L11
test 4.

Second-order effect, per LAW 2: with 31 jobs on one machine, a single Dagu misconfiguration or a
full disk stops backups, drains, repairs and reports at the same time, and the failures arrive
together and look like an estate-wide incident rather than one host.

**Decision — proceed, with three conditions stated as part of the decision, not as follow-up.**

1. The Continuity panel and every doc record it as "one machine, not redundant".
2. Every job is idempotent and re-runnable, so a missed window self-heals on the next tick rather
   than needing a person.
3. S2 lands first. Dagu on one machine with no off-box watcher is strictly worse than launchd on a
   laptop the founder can see.

Task #95 stands, gated behind #97.

---

## 4. S4 — the guards live on one laptop, in no repository

**This is the finding with the widest blast radius and it was not in the audit at all.**

Measured 2026-08-19:

```
ls ~/.claude/scripts/*.py | wc -l   -> 22
cd ~/.claude && git rev-parse --is-inside-work-tree
  -> fatal: not a git repository
```

**Justification.** LAW 0 says a guard must reach every agent, and the mechanism it names is "a hook
in `~/.claude/scripts/`". Those 22 files are the enforcement layer of the whole way of working:
`push-pr-fence.py`, `dupe-work-fence.py`, `rule-guard.py`, `hang-guard.py`, `idle-guard.py`,
`directive-capture.py` and the rest. They are on one laptop, under no version control, with no
backup, and no test.

Three consequences, in order:

1. **First order.** A guard edited badly is unrecoverable, and a guard deleted is silently gone. No
   diff, no history, no review.
2. **Second order.** The founder has said he has a new laptop. A fresh machine gets zero guards, and
   the failure is silent: agents simply stop being refused, and the estate reverts to the behaviour
   each guard was written to stop. Nothing announces it.
3. **Third order.** The migration bar (B1) claims the whole stack moves in thirty minutes. The way
   of working does not move at all. It is not in the inventory, not in the backup, and not in the
   bootstrap.

**Decision.** The guards become tracked files with a bootstrap installer, and `M2` (task #82) owns
it. Concretely: the scripts move into the repo under `scripts/claude_guards/` — where
`idle-guard.py` already lives, so the pattern exists — and the bootstrap symlinks or copies them
into `~/.claude/scripts/`. A probe asserts each hook named in `settings.json` resolves to a file
that exists. This is an extension of a mechanism we already have, not a new one.

Confirmed while writing this: `~/.claude/settings.json` names a `SessionStart` hook that runs
`git show origin/main:scripts/checkout_currency.py`, and that path does not exist on `origin/main`.
The hook has been failing at every session start. Same class, already live.

---

## 5. S5 — two datastores, and the sequencing that de-flakes it

**Justification.** The two-datastore decision (`STACK_AUDIT.md` §9.4 and §9.5) is sound on its
merits and I am not reopening it. The flakiness is in the ORDER. Today the estate has one datastore
whose restore has never been proven. Task #93 makes that two datastores whose restore has never been
proven, and #94 (Litestream) and #80 (restore drill) are both still open. Doubling an unproven
surface before proving any of it is how a backup programme ends up with more paths and no more
confidence.

**Decision.** #80 runs as a scheduled, passing drill on the SQLite path before #93 starts. Not
documented — running, on a schedule, with a failure that pages. The drill is the cheaper half and it
is the half that makes the second datastore safe to add.

---

## 6. S6 and S7 — the two bars nothing measures

**Justification, S6.** The bar is thirty minutes to move the whole stack with no customer downtime,
proven from the ops dashboard. There is no clock anywhere in the estate that starts when a migration
starts. Until one exists, every row in the B1–B8 table is an opinion, including the ones that say
"not met". L11 test 3.

**Decision, S6.** The drill writes a duration. A migration drill that does not record start, end and
the outcome of each verb is not a drill, it is a rehearsal nobody scored. Until it has run once, the
bar is reported as UNMEASURED, never as MET or as a percentage.

**Justification, S7.** "Reusable for any project" has no carrier. Every probe, script and query we
have is prospector-shaped: it knows our app names, our store path, our launchd labels. A claim of
reusability that has never been pointed at a second system is untested by construction.

**Decision, S7.** The proof is running the same inventory and the same adapter verbs against a
second target that is not prospector. `hermes` is the obvious candidate; it is already a separate
estate with its own apps. Until that runs, B8 is UNMET and is reported that way. Task #98 owns it.

---

## 7. Risk assessment

Likelihood is judged over the next ninety days. Impact is what a customer or the founder sees.

| # | Risk | Likelihood | Impact | Grade | Owner |
|---|---|---|---|---|---|
| R1 | Money path is one SQLite file on one Fly volume (`vol_4ql6dzwjylqeygnr`, 1 GB, lhr, one machine). Every deploy is a window where the shop cannot take money | medium | **critical** — lost orders, lost entitlements | open | #93 |
| R2 | No restore has ever been proven, on either datastore | low to need it | **critical** — unbounded data loss | open | #80, #94 |
| R3 | `prospector-engine` holds `STRIPE_LIVE_API_KEY` and `FLY_API_TOKEN` | low | **critical** — see §8 | open | new |
| R4 | Two DNS records at TTL 3600 | certain, on any move | high — one hour of the thirty-minute budget, before anything else | open | #99, #77 |
| R5 | Secrets have no restore path. They exist only in Fly and in `.env` on one laptop | low | **critical** — a lost Fly org is unrecoverable | open | #82 |
| R6 | Agent guards on one un-versioned laptop | **certain on a new machine** | high — silent loss of every rule | open | §4, #82 |
| R7 | CI runners execute repository code | low — the repo is PRIVATE (`gh repo view` → `PRIVATE`), so no outsider can open a PR | medium | accepted | — |
| R8 | No internal record of processing, retention schedule or DSAR path | medium | high — regulatory, see §9 | open | #13 |
| R9 | The autoscaler is dead and nothing noticed for at least 3.5 hours of pushes | already happened | low — cost only | open | §1 |
| R10 | Backup dead since 17 Aug with no alert (D1) | already happened | high | open | #92 |

**The pattern across R1–R6:** every one of them is a thing that is fine until the day it is not, and
on that day there is no second path. That is the same shape as the flakiness test, applied to
infrastructure rather than to proposals.

---

## 8. Security assessment

Measured with secret NAMES only. No value was read or printed.

**Finding SEC-1 — blast radius on `prospector-engine`.** `fly secrets list -a prospector-engine`
names, among others: `STRIPE_LIVE_API_KEY`, `FLY_API_TOKEN`, `CONTROL_CENTER_PASSWORD`,
`STORE_INTERNAL_API_KEY`, `PROSPECTOR_ENTITLEMENTS_API_KEY`, `R2_SECRET_ACCESS_KEY`.

The engine runs model-generated content and fetches arbitrary pages from the open web. It holds a
token that can destroy every app in the Fly organisation, including the money path, and a live
Stripe key. Least privilege is not met.

*Justification for the fix:* `FLY_API_TOKEN` is on the engine so the engine can act on Fly. A Fly
deploy token scoped to a single app does the same job with a fraction of the reach. `STRIPE_LIVE_API_KEY`
needs a check before anything moves: if the engine only reads price data, a restricted key with read
scope replaces it; if it writes, it should be calling `Store.Api` instead of Stripe directly.

**Decision — proposed:** scope the Fly token to one app, and audit what the engine does with the
Stripe key before replacing it. Neither is done in this document; both are filed. **Rotation of the
two secrets printed into a transcript (task #38) is still outstanding and predates this.**

**Finding SEC-2 — good, and worth keeping.** `deploy/runners.sh:150-151` sends a CI runner only
`GITHUB_RUNNER_PAT` and `RUNNER_LABELS`, with the reason written in the file. Secret values are piped
on stdin, never passed as arguments (`deploy/runners.sh:52-53`), so nothing lands in `ps` output or a
shell history file. This is the standard the rest of the estate should be measured against.

**Finding SEC-3 — no `pull_request_target` anywhere** (`git grep -ln pull_request_target --
.github/workflows` returns nothing). That is the trigger that runs a fork's code with repository
secrets. Its absence is the correct state.

**Finding SEC-4 — repository secrets are `FLY_API_TOKEN`, `FLY_API_TOKEN_API`, `FLY_API_TOKEN_ENGINE`.**
Two are app-scoped by name. The unscoped `FLY_API_TOKEN` is UNPROVEN: the check is
`fly tokens list` against the org, comparing scope, and it has not been run.

**Not assessed, and named so nobody reads silence as a pass:** MFA on the Fly and GitHub accounts;
key rotation ages; R2 bucket policy and whether offsite backups are encrypted at rest with a key
that is not in the same account; the auth guards on all 53 API endpoints (task #40, still open).

---

## 9. Compliance assessment

The estate sells a digital product to buyers in the UK, US and EU, so UK GDPR applies as controller,
and card payment brings PCI DSS into scope at some level.

**What exists, verified.** The storefront has real legal pages: `store_platform/src/Store.Web/src/pages/privacy.tsx`,
`terms.tsx` and `refund.tsx`, rendered through `components/LegalDoc.tsx`. An earlier draft of this
section said there was no privacy policy. That was wrong, and checking is what corrected it.

**Personal data held.** Buyer email on the order (`Order.BuyerEmail`, joined to the account email in
`Auth/AccountOrdersEndpoints.cs:20`), account emails (`Auth/AuthEndpoints.cs`), and Google sign-in
identifiers (`Authentication__Google__ClientId` / `ClientSecret` on `prospector-store-api`).

**Processors we send personal data to**, from the secret names on the money app: Stripe (payments),
Mailjet (`MAILJET_API_KEY`, `MAILJET_FROM_EMAIL` — delivery email), Cloudflare R2 (artifacts),
Google (sign-in), Fly.io (hosting). GitHub is a processor for operational data.

**Gap C-1 — no internal compliance record.** `ls docs | grep -iE "privacy|gdpr|complian|security|retention|dpa"`
returns nothing. A public privacy page is the customer-facing half. The controller-facing half does
not exist: no Article 30 record of processing, no retention schedule, no documented DSAR route, no
breach-notification runbook against the 72-hour clock, no processor/DPA register. Task #13 covers
retention only, and is pending.

*Justification:* of these, the retention schedule and the DSAR route are the two that bind
day-to-day engineering, because they decide what the backups may keep and for how long — and we are
about to add Litestream and restic, which will replicate personal data into two more places. Writing
the retention schedule AFTER building continuous replication means retrofitting deletion across
every replica.

**Decision:** the retention schedule (#13) is written before #94 (Litestream) ships, and it names,
per datastore and per bucket, what is kept and for how long. The Article 30 record and the DSAR
route follow it in the same document. This is a sequencing decision, and it costs nothing today.

**Gap C-2 — PCI scope is UNPROVEN, and this one matters.** `StripeProvider.cs:345` sets
`options.UiMode = "embedded"`, so this is Stripe embedded Checkout rendered inside our own page via
Stripe.js, not a redirect to a Stripe-hosted URL. No card data touches our servers, which is the
important part. Whether that places us in SAQ A or the stricter SAQ A-EP depends on how the acquirer
treats an embedded Checkout iframe, and I will not assert either from memory.

*The exact check:* confirm against Stripe's own PCI guidance for embedded Checkout and, if the
answer is not unambiguous, ask the acquirer. Until answered, this document records the scope as
UNDETERMINED, never as "SAQ A, we are fine".

**Gap C-3 — UK consumer law on digital content.** The refund page exists; whether it states the
cancellation-right waiver required for immediate digital delivery is a content question this audit
did not read. Named so it is not lost.

---

## 10. What changes, in order

Nothing below is a new system. Every line is a sequencing change or a one-line guard.

1. ~~A guard so an unrunnable workflow is refused.~~ **Done in this commit** —
   `tests/unit/test_workflow_triggers_are_real_events.py`. Closes the S1 class.
2. Decide what triggers the autoscaler: cron, `workflow_run`, or delete it. It is manual-only today.
3. S2 before S3: the off-box dead-man's switch lands before 31 jobs move onto one Fly machine.
4. The 22 agent guards become tracked files with an installer, and a probe asserts every hook in
   `settings.json` resolves. Fix the `checkout_currency.py` hook in the same pass.
5. #80, the restore drill, runs green on a schedule before #93 starts the Postgres move.
6. The retention schedule (#13) is written before Litestream (#94) replicates personal data further.
7. The migration drill records a duration. Until it has, the thirty-minute bar reads UNMEASURED.
8. Point the inventory at a second, non-prospector estate. Until then B8 reads UNMET.
9. Scope the engine's Fly token to one app; audit its use of the live Stripe key.

## 12. Every solution proposed, graded

Sections 1 to 6 graded the nine solutions that had evidence behind them. The founder asked to see
**all** of them. This is the complete register: every solution proposed anywhere in the migration
and stack work, each graded against the four L11 tests, with its adoption state measured rather
than assumed.

**The headline of this section is the adoption column.** Of the fifteen tools picked in the
research pass, **thirteen are not installed on this machine and three of them appear nowhere in the
repository at all**. Measured 2026-08-19:

```
steampipe ABSENT   cloudquery ABSENT   mise ABSENT      litestream ABSENT
restic    ABSENT   dagu       ABSENT   vector ABSENT    tofu       ABSENT
sops      ABSENT   pumba      ABSENT   toxiproxy ABSENT psql       ABSENT
uv        /Users/chidionyema/.local/bin/uv          age  /usr/local/bin/age
terraform /usr/local/bin/terraform     <- note: the PICK was OpenTofu, not Terraform

rg -il 'healthchecks.io|hc-ping|dagu|litestream' over the repo  ->  no matches
```

So the honest grade for most of the register is UNPROVEN, and that is not a criticism of the picks.
It is L11 test 3 applied consistently: **nothing measures them, because none of them has been run
here even once.** A pick made from documentation is a hypothesis about this estate, not a solution
in it.

### 12a. Shipped or merged — graded on evidence

| # | Solution | State | Grade | Justification |
|---|---|---|---|---|
| S1 | CI autoscaler | merged | **FLAKY, proven dead** | Section 1. `on: workflow_job` is not a trigger. 40 of 40 runs never started |
| S8 | Runner secret hygiene | live | **SOUND** | Only `GITHUB_RUNNER_PAT` and `RUNNER_LABELS` reach a runner app; values piped, never in argv (`deploy/runners.sh:52,150`) |
| S9 | Storefront legal pages | live | **SOUND** | `privacy.tsx`, `terms.tsx`, `refund.tsx` render |
| P1 | DNS zone committed and diffed daily (M9) | PR #397 open | **UNPROVEN** | The zone is exported and diffed. Nothing yet fails when the diff is non-empty, and the two 3600s TTLs are still live (task #99) |
| P2 | Guards as PreToolUse hooks | live, unversioned | **FLAKY** | Section 4. They work; they exist in exactly one place and no repository |

### 12b. Decided by the founder, not yet built

| # | Solution | Grade | Justification |
|---|---|---|---|
| P3 | Postgres for the money path (#93) | **UNPROVEN** | The decision is right and the reason is recorded. It adds a datastore whose restore has never been drilled, so it inherits S5 until #80 runs |
| P4 | SQLite stays for the engine | **UNPROVEN** | Same. The cost accepted was two backup paths and two drills; zero drills exist |
| P5 | Dagu on `prospector-engine` (#95) | **FLAKY** | Section 3 |
| P6 | Healthchecks on `prospector-engine` (#95) | **FLAKY** | Section 2. Superseded by #97 |
| P7 | Delete the dead scripts in a second pass | **SOUND** | Report mode first, delete only what has been confirmed run. The sequencing is the safety |

### 12c. The fifteen tool picks — all UNPROVEN, each with the specific thing to check first

Every one of these came from a single research pass. Not one has been run against this estate. The
right next action for each is not "adopt", it is the one cheap test named in the last column.

| # | Pick | For | Grade | The first thing that would prove or kill it here |
|---|---|---|---|---|
| T1 | Steampipe | M1 inventory | **UNPROVEN** | Does a Fly.io plugin exist? Fly is our largest resource class. If not, the pick misses the point of M1 |
| T2 | CloudQuery | M1 later | **UNPROVEN** | Deferred by design. Nothing to check until drift history is wanted |
| T3 | mise | M2 toolchain | **UNPROVEN** | Bootstrap paradox: `mise bootstrap` needs mise. What installs mise on a bare machine, and is that step in the repo? |
| T4 | uv | M2 Python lock | **UNPROVEN** | Installed and used, but `origin/main` has **no `uv.lock`, no `pyproject.toml`, no `.python-version`** — only `requirements.txt` and `requirements-local.txt`. So the lock M2 depends on does not exist yet |
| T5 | Litestream | #94, RPO to seconds | **UNPROVEN** | Replication is silent by design. What alerts when it stops? Without that it is S2 again in another costume |
| T6 | restic | offsite | **UNPROVEN** | Same silence question, plus: restore one file from it, timed, before trusting it |
| T7 | Dagu | 31 launchd jobs | **FLAKY** | Section 3. Design fault, not adoption doubt |
| T8 | Healthchecks.io | drill and job alerting | **FLAKY** | Section 2, if it runs on the machine it watches. SOUND if it runs anywhere else |
| T9 | s6-overlay replacing supervisord | container supervision | **SOUND design, UNPROVEN here** | The strongest pick in the list, and it is measurable now: `deploy/engine/supervisord.conf` runs **seven** programs in one container (`scheduler`, `consumer`, `watchdog`, `backup`, `offsite-backup`, `restore-drill`, `ops-console`). supervisord stays up when one dies, so the machine reads healthy with a dead daemon inside. That is exactly the silent-failure class |
| T10 | SOPS + age | secrets in git | **UNPROVEN, with a real hole** | The age private key cannot live in the repo it protects, so a new laptop must obtain it some other way. **Until that path is written down, SOPS does not solve the migration bar, it relocates it.** This is the single most important unanswered question in M2 |
| T11 | octoDNS | DNS as code (#99) | **UNPROVEN** | Needs a working GoDaddy API credential. Prove a no-op plan against live DNS before any apply |
| T12 | OpenTofu | IaC | **UNPROVEN, and drifting** | The pick was OpenTofu. What is installed on this machine is **Terraform**. Nothing has been written in either |
| T13 | Vector to Loki or OpenObserve | M10 logs (#84) | **SOUND design, UNPROVEN here** | Shipping logs off the platform that made them is exactly what the 30-minute bar needs. Unchosen: Loki or OpenObserve, and where it runs — if it runs on `prospector-engine` it is S2 again |
| T14 | Pumba, Toxiproxy | M7 chaos | **UNPROVEN** | Chaos tooling is worthless before the drills exist. Correct order: #80 and #81 first |
| T15 | Playwright synthetic buy | M8 (#88) | **UNPROVEN** | Two Playwright files exist on `origin/main`. Nothing runs one on a schedule, so nothing proves a buyer can buy |

### 12d. The M-series gaps as a programme

| Gap | Task | Grade | Justification |
|---|---|---|---|
| M1 inventory | #78 | **UNPROVEN** | Depends on T1 |
| M2 bootstrap | #82 | **FLAKY as scoped** | It cannot succeed while the guards are unversioned (section 4) and the secret restore path is unwritten (T10). Both are prerequisites, not details |
| M3 money-path adapter | #86 | **UNPROVEN** | Not started |
| M4 backup proof | #80 | **UNPROVEN** | The keystone. Everything about the 30-minute bar is a wish until this runs a clock |
| M5 Continuity panel | #85 | **UNPROVEN** | A panel showing unmeasured state would be worse than no panel. Sequence after M4 |
| M6 five drills | #81 | **UNPROVEN** | Depends on T7 and T8, both FLAKY as placed |
| M7 chaos | #87 | **UNPROVEN** | See T14 |
| M8 end-to-end buy | #88 | **UNPROVEN** | See T15 |
| M9 DNS | #77 | **UNPROVEN** | PR #397 open, TTLs unchanged |
| M10 logs | #84 | **UNPROVEN** | See T13 |
| M11 datastores named | #79 | **UNPROVEN** | Naming them is cheap and unblocks M4. Do it first |
| M12 redundancy verdict | #83 | **UNPROVEN** | S3 says the answer for the engine today is "none" |

### 12e. What this register changes

Three things, and none of them is a new build.

1. **M11 (#79) and M4 (#80) come first**, before any tool is installed. Naming every datastore and
   timing one real restore is the measurement that turns eleven UNPROVEN rows into graded ones.
2. **T10, the age key path, is a blocker on M2**, not a detail inside it. Write it down before
   adopting SOPS.
3. **Each tool gets its one cheap test before adoption**, from the last column above. A pick that
   fails its test costs an afternoon now instead of a migration later.

---

## 11. Ledger

| Date | What | Evidence |
|---|---|---|
| 2026-08-19 | Re-audit taken. 9 solutions graded: 2 SOUND, 4 FLAKY, 3 UNPROVEN | this document |
| 2026-08-19 | Autoscaler proven never to have run | 35 push-triggered runs, 0 jobs, 0 `workflow_job` runs |
| 2026-08-19 | Earlier inference that the autoscaler killed a CI job WITHDRAWN | the workflow cannot execute |
| 2026-08-19 | L11 "No flaky solutions" added to the manifesto | `docs/PLATFORM_MANIFESTO.md` |
| 2026-08-19 | S1 class closed by a guard; `ci-autoscale.yml` made valid, manual-only | `tests/unit/test_workflow_triggers_are_real_events.py`, 13 passed |
| 2026-08-19 | Section 12 added: the complete register of all 39 proposed solutions, graded | 13 of 15 picked binaries ABSENT; `rg` finds no reference to dagu, litestream or healthchecks; `origin/main` has no `uv.lock`; `supervisord.conf` runs 7 programs in one container |
