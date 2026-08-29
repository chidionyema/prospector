# Platform portability audit — the state of play, measured

**Status: AUDIT. Nothing here is a decision, and execution has not started.**
Every number below was measured on 2026-08-19 and carries the command that produced it. Where a
thing is unknown it says UNPROVEN, because an unproven claim written as a fact is how this estate
got into the state this document describes.

Companion documents: `docs/PLATFORM_MANIFESTO.md` (the laws, L11 is the flakiness test used to
grade everything here), `docs/STACK_FLAKINESS_AUDIT.md` (the five proposals graded against L11).

---

## 1. What was asked for

Founder, 2026-08-19, verbatim, because a bar re-rendered into my own words is a bar I have
quietly lowered:

> "if i have 30 ninutes to nigrate the wwhole stack, donain, third party deps/ donain , everything
> running in this nachine because i also have a new laptop, so engine, hernes, jobs, and evertything
> on fly to another onpren or cloud provider, i should not epericne ny downtine and get this
> seanlessly done fron ops dashboard and prove and see realtine progress. this is the bar, even
> things like logs, etc nothing beig used can be nissed out, and this has to be resuable for any
> project not just prospector etc, should be able to probe and audit any systen and get this done."

Then, in order, the additions that changed the shape of the work:

- **Two stacks, not one.** "sonethings rin on this nachine is prt of developer workflows, they cant
  rin on a host, so there are 2 parts, developer stack, platforn stack, develoepr stack is part of
  platforn stack but runs on dev nachine, so need to accout for all."
- **Not a lift and shift.** "this is a platforn nodernnissaton, ionnprovennet, onssolisdaaation,
  stralining etc" — and the metric: **"the new stack needs to be 100 tines beter"**.
- **Reflect on what actually hurts.** "you need to reflect on incidents, live bugs, friction, the
  sheer anout of custon tooling, sctips, jobs everythere".
- **Hermes is in scope.** "EVEN THE HERNES AGAINT IS AINCLUDED AS ITS PART OF STACK".
- **Staging.** "currently we deploy to prod withoiut staging env, when is that gin gt change?"
- **A new developer.** "a new dev on new laption howis dev env setup?" … "new dev can seup new
  nachine seanlessly".
- **DevOps is in scope.** "so thibk devops also".
- **It is a business, and it must be sellable.** "we are a startup, i need to be able to sell this
  business and it needs to be packaged up annd portble".
- **Through the dashboard.** "and all by ops dashboad".
- **Forever, not once.** "we need to consider we are stil working on the platforn, so this is not
  one off job need to be portable today tonorrow forever as it grows so need streablined process".
- **Proof, not assertion.** "well tested proved docunented and bullet proof with regular drills"
  … "and chaos tests".
- **And: document it.** "AND I DONT WANT TO REAR THIS, NEEDS DOCUNENETINNG". That is what this
  file is for. It is the thing that stops the next session re-deriving all of it.

**Founder instruction on sequencing, in his words: "you are not ready to start eecution."** He is
right, and §9 says exactly why in measured terms.

---

## 1a. Ownership

Founder, 2026-08-19: **"BETTER YOU HADLE EVERYTING PLATFORNR ELATED"** and **"have one person
accoutable for wholeplatfron"**.

One accountable owner for the whole platform, and that is this seat. It supersedes the earlier
split where the pipeline was left to another session — that split is what produced F10 below, so
the founder's instruction fixes a measured defect and not just a reporting line.

**In scope, all of it:** platform stack, developer stack, CI, Hermes, observability, DNS, secrets,
backups, drills, onboarding, and the ops console surface that drives them.

**What that changes immediately:** F2 (CI) stops being somebody else's problem and becomes a
finding with an owner; F9 (observability) is taken here rather than filed away; and this document
plus `docs/PLATFORM_PROGRESS.md` are the running record, per **"keep notes onn progress"**.

---

## 2. What "100 times better" means, measured

A single 100x number would be a slogan. Broken into dimensions it is arithmetic, and some of these
are genuinely 100x while others are not, which is worth knowing before anything is built.

| # | Dimension | Today (measured 2026-08-19) | Target | Ratio |
|---|---|---|---|---|
| D1 | Migrate the whole stack to a new host | **No procedure exists. Never attempted.** | 30 min, dashboard-driven | not computable from zero — see note |
| D2 | New developer to a working machine | **No single command exists.** 0 of 13 environment-pinning files present (§5, F3) | one command | as above |
| D3 | Hand-maintained operational artifacts | **199** (§4) | ≤ 20 | 10x |
| D4 | Lines of bespoke ops code | **16,637** in `scripts/` + `ops/automations/` | ≤ 3,000 | 5.5x |
| D5 | Places a secret lives | **4+** (laptop `.env`, 15 Fly secrets on one app alone, 3 GitHub secrets, `~/.hermes/`) | 1 source of truth | 4x |
| D6 | Environments between a commit and customers | **1 — production** (§5, F1) | 2 (staging, then prod) | the gap, not a ratio |
| D7 | CI runs on `main` that concluded green, last 48h | **23 of 42 = 55%** (§5, F2) | ≥ 98% | 1.8x |
| D8 | Untracked jobs that would be lost in a move | **6** (36 installed vs 30 tracked) | 0 | absolute |
| D9 | Rehearsed failure modes (drills, chaos) | **0 scheduled restore drills of the full estate; 0 chaos tests** | continuous | absolute |
| D10 | Places you must look to read the logs of one request | **11+ directories on 4+ machines** (§5, F9) | 1 | 11x |
| D11 | Lines of script written to survive the pipeline | **6,505 across 16 files** (§5, F10) | ≤ 500 | 13x |

**Note on D1 and D2.** Neither has a baseline, because neither has ever been done. That is not a
missing measurement, it is the finding: **the two things the bar is actually about are the two
things with no number at all.** The honest first target is not "100x faster", it is "measured
once", and every subsequent claim is a ratio against that first timed run. D1's first measurement
is the M6 drill; until that clock runs, any migration-time claim in any document in this repo is a
wish. This is L11 rule 3.

**Where 100x really does live.** Not in any single row. It is the product of D3 × D5 × D8: a stack
where 199 artifacts become ~20 declared ones, secrets have one source, and nothing is installed
that is not tracked. A move then stops being an act of archaeology and becomes an apply. That is
where a 30-minute migration comes from, and there is no shortcut to it that does not pass through
consolidation first. **This is why the founder's "not a lift and shift" is correct as engineering,
not just as ambition: lifting 199 artifacts to a new host produces 199 artifacts on a new host.**

---

## 3. The stacks — which machine runs what

The founder's correction is the load-bearing one, and it is the thing every previous plan in this
repo got wrong by omission.

### 3a. Platform stack — runs on hosts, must survive losing any machine

| Component | Where today | State it owns | Portable? |
|---|---|---|---|
| Engine (scheduler + consumer) | `prospector-engine` on Fly | `store/` via `PROSPECTOR_STORE_DIR` | container exists; state is the problem |
| Store API | `prospector-store-api` on Fly | `/data/store.db` (SQLite, money) | single volume, single region |
| Store Web | `prospector-store-web` on Fly | none | yes |
| SearXNG | `prospector-searxng` on Fly | none | yes |
| Hermes agent | `prospector-hermes` on Fly | `~/.hermes/`, leader election in R2 | **state is not backed up** — §5 F7 |
| Ops console | Next.js, 21 actions live (§6) | none | yes |
| DNS / domain | registrar, TTLs incl. two at 3600s | — | 3600s TTL is a 1h downtime floor |
| Object storage | R2, buckets `prospector-packs`, `prospector-backup` | packs, backups | account-locked |

8 Fly apps deployed (`fly apps list`). The four `tie-*` apps are on hold by founder instruction
and are excluded from every count in this document.

### 3b. Developer stack — runs on the developer's machine, cannot run on a host

11 launchd jobs matching `prospector|hermes` are loaded on this laptop right now
(`launchctl list`). They are the developer stack: keepawake, idle-engine, lease-guard,
runaway-reaper, standby-sync, failover-watch, receipt-bridge, log-rotation, process-audit,
backup, offsite-backup.

**Two of them are failing right now, and nothing said so:**

```
com.prospector.backup          last exit 78   (EX_CONFIG)
com.prospector.process-audit   last exit 2
```

A non-zero last-exit on a launchd job is invisible unless somebody runs `launchctl list` and reads
the second column. That is the same defect class as the backup exit-code finding fixed earlier
today: **the evidence of health is a number nobody reads.**

### 3c. The third stack nobody named — CI

9 GitHub workflows, plus a self-hosted Fly runner fleet (`prospector-ci`, `hermes-ci`). It is not
the platform stack (customers do not touch it) and not the developer stack (it does not run on the
laptop), and because it belongs to neither, **it has been excluded from every migration plan
written so far**. Selling the business means selling this too: a buyer who gets the product and
not the pipeline cannot ship a fix on day one.

### 3d. The overlap — where a migration silently fails

The founder's phrasing was "develoepr stack is part of platforn stack but runs on dev nachine".
The overlap is real and it is the dangerous part:

- `PROSPECTOR_STORE_DIR` on the Fly plists points at **a path on this laptop**. Production writes
  its ledger and dossiers to a directory on a developer machine.
- `.env` and `.lux/keys/agent.pem` in the live checkout are **symlinks back to this checkout**.
  Git carries no secrets, so the live production checkout has none of its own.
- `com.prospector.backup` — the job that produces the offsite copies — is a **laptop** job.

So: close the laptop, and production's state directory, its secrets and its backups all go with
it. **That is the single most important sentence in this audit.**

---

## 4. The sprawl, counted

| What | Count |
|---|---|
| `scripts/*.py` | 45 |
| `scripts/*.sh` | 8 |
| `ops/automations/*.py` | 6 |
| `tools/*` | 50 |
| `ops/launchd/*.json` | 30 |
| `.github/workflows/*.yml` | 9 |
| `deploy/*` | 17 |
| `~/.claude/scripts/*` (agent guards) | 34 |
| **Total hand-maintained artifacts** | **199** |
| Lines in `scripts/` + `ops/automations/` | **16,637** |

None of this is stupid code. Every one of those files exists because something broke once. That is
exactly the problem: **the estate has been maintained by accretion, and nothing has ever been
retired.** 199 artifacts is not a portability problem you solve by moving them; it is a portability
problem you solve by deleting most of them into three or four declared systems.

---

## 5. Findings, graded

Graded with L11: FLAKY if it depends on the thing it protects, can fail silently, is measured by
nothing, or moves the single point of failure instead of removing it.

**F1 — There is no staging environment. ABSENT.**
`staging` appears in this repo exactly twice, both in comments (`deploy/engine/supervisord.conf:80`
and `:129`), describing a hypothetical second copy of the image. No Fly app, no workflow job, no
config stanza. **Every deploy is a production experiment.** With the money rail in scope, a bad
deploy is a customer being charged wrong, and the only thing standing between a merge and that is
CI — which, per F2, is red 45% of the time. Answer to "when is that going to change": it is the
first thing that changes, because it is a precondition for every drill in §8. A drill that
rehearses on production is not a drill.

**F2 — `main` CI has been red for two days. CONFIRMED, and the founder was right.**
```
2026-08-18   11 success   9 failure   9 cancelled
2026-08-19   12 success  10 failure   8 cancelled
```
23 of 42 concluded runs green = **55%**. One named red test:
`tests/unit/test_ci_runner_loops_without_a_reboot.py::test_a_failed_job_does_not_end_the_fleet`.
The 17 cancelled runs are the separate, already-documented `cancel-in-progress` defect
(memory `every-push-cancels-the-ci-that-would-have-merged-it`). **Ownership changed 2026-08-19**: per §1a this is now
mine, not another session's. The founder's immediate instruction is *"forget the pipipeline for
now"*, so it is not being touched this turn — but it is no longer unowned, and F10 explains why
that distinction matters more than it looks.

**F3 — There is no reproducible development environment. ABSENT, and this is the answer to "how
does a new dev set up a new laptop".**
Checked for, all absent: `Dockerfile` (root), `docker-compose.yml`, `compose.yaml`, `flake.nix`,
`shell.nix`, `.tool-versions`, `.python-version`, `.nvmrc`, `Brewfile`, `.devcontainer`,
`devcontainer.json`, `Makefile`, `justfile`. **Thirteen of thirteen absent.** Five Dockerfiles
exist (`deploy/runner`, `deploy/searxng`, `deploy/engine`, `Store.Web`, `Store.Api`) and every one
is a deploy target, not a dev environment. The only setup script is `scripts/setup_worktree.sh`,
which sets up a *worktree inside an already-working checkout* — it presupposes the machine.

So today a new developer needs, undocumented and in the right order: the right Python, the right
Node, a venv, `requirements.txt`, `npm install`, `.env` (which git does not carry), an
`agent.pem` signing key (untracked), `fly` authenticated, R2 credentials, `gh` authenticated, and
36 launchd plists. **README's Quickstart covers the venv and stops.** The realistic estimate is
days, and it is UNPROVEN because nobody has ever done it and timed it.

This is also the sellability finding. A buyer's first act is putting a new engineer on a new
machine. If that takes days of tribal knowledge, the asset is worth materially less than the code
suggests, and the diligence question "can your team be onboarded?" has no good answer.

**F4 — The automation census. Nine dependencies of the stack live outside every repo, and
the check that watches them was dead. CONFIRMED, measured 2026-08-19.**

F4 was first written as "six installed jobs are tracked nowhere", identity UNPROVEN. The first
measurement said seven and I scoped the finding by LABEL PREFIX — treating `com.chidionyema.*`
and `com.estate.*` as other people's projects. That was wrong, and the founder said so:
*"well these are dependencies costsentinel, graphify-sweep, reflect ... also lux, popdd etc, you
didnt audit properly"*. He is right. `com.chidionyema.graphify-sweep` runs
`~/Documents/code/prospector/scripts/graphify_sweep.py` — it is prospector. A prefix is the SHAPE
of the evidence; what the job executes is its CONTENT. This is the full census, resolved through
the wrapper, of all 36 installed agents.

**Method.** Every `~/Library/LaunchAgents/*.plist` parsed with `plutil`; 8 of them run the real
command after a `--` separator behind `~/.hermes/scripts/launchd_receipt.py`, so the wrapper is
resolved and the TARGET is what is classified; each target's directory asked `git rev-parse
--show-toplevel`. Environment variables were read for KEY NAMES only, never values.

| Where the target lives | Jobs | Which |
|---|---|---|
| `~/.hermes` (own repo, `chidionyema/hermes-config`) | 12 | cockpit, coordinator, gateway, idle-engine, lease-guard, ngrok, otto-server, progress, rsi, runaway-reaper, selfcheck, submodule-backup, watchdog |
| `~/Documents/code/prospector` (this repo) | 5 | consumer, log-rotation, offsite-backup, scheduler, watchdog, **graphify-sweep** |
| `~/Documents/code/prospector-live` (stale checkout) | 4 | backup, live-update, process-audit, ops-console |
| `~/.claude/scripts` (**git repo with no remote**) | 2 | **costsentinel**, **reflect** |
| `~/.prospector/bin` (**not in any repo**) | 3 | failover-watch, standby-sync, receipt-bridge |
| `~/Documents/code/signalengine` | 1 | signalengine daemon |
| genuinely another business | 3 | haworks ×2 (`/usr/local/bin/haworks-*`), tie ×1 |
| third-party vendor | 3 | Adobe, ExpressVPN, Steam |
| macOS binary | 1 | keepawake (`/usr/bin/caffeinate`) |

Seven of these are installed and snapshotted nowhere in `ops/launchd/`: the three
`com.prospector-control.*`, `com.prospector.log-rotation`, `com.prospector.process-audit`,
`ai.hermes.lease-guard`, `ai.hermes.selfcheck`. Four snapshotted jobs are installed nowhere: the
`actions.runner.chidionyema-prospector.mumchimp-mac{,-2,-3,-4}` agents, correctly gone since the
runners moved to Fly (task #6), never removed from the snapshot.

**What counts as the stack, since the laptop does not distinguish.** Founder, 2026-08-19:
*"prospector and hermes agent and the surface area around them is the stack, the dependencies"*.
So the two `ai.hermes.*` jobs above are in scope and must migrate. `com.haworks.*` and
`com.tie.*` are not, and neither are Adobe, ExpressVPN and Steam. Nothing on this machine records
that distinction: 36 agents sit in one flat directory, and the only thing separating a stack job
from somebody else's is the prefix of its label. A migration script that takes "the launchd jobs"
takes four projects, and one that hand-picks them will miss the next one added. The label prefix
is the de-facto namespace, so it should become the declared one.

**F4a — Three copies of our own code run off-repo, each pinned at a different commit.**

| Copy | What runs it | Drift, measured 2026-08-19 |
|---|---|---|
| `~/Documents/code/prospector-live` | 4 laptop jobs incl. the ops console | **44 commits behind `origin/main`** |
| `~/.prospector/bin/engine_failover.frozen.py` | the 3 DR jobs | **514 lines vs 735 on main, 225 different**, 3 commits behind |
| the `prospector-engine` Fly image | production | the only one of the three that is graded |

The frozen failover copy is deliberate, and `deploy/install_failover_watch.sh:14` is right that a
disaster-recovery tool living inside a checkout dies with the checkout. The defect is that
freezing was implemented and re-freezing was not. The watcher running every 60 seconds predates
`#327`, whose subject is *"make grounding, the ops dashboard and the merge queue work after the
Fly cutover"*. **The apparatus that exists to survive this machine does not know the machine
already moved.**

**F4b — Nine dependencies of the stack are in no repository at all.** Each is a thing a new
laptop needs and no clone provides: `~/.prospector/bin/failover` and its frozen engine copy;
`~/.local/bin/graphify`; `/usr/local/bin/node`; the `.lux/keys/agent.pem` signing key; the
Tailscale address `100.93.240.113` that the ops console binds to; `~/.hermes/scripts/launchd_receipt.py`;
the 23 untracked files under `.lux/`; the four vendored Crux DLLs of F11; and the installed
plists themselves.

**F4c — The agent guard scripts are a git repo with no remote.** `~/.claude/scripts` is its own
repository (`2b683ab`), 11 files dirty, **and `git remote -v` is empty**. That directory is where
LAW 0 says every cross-session guard must live — the push fence, the rule guard, the cost
sentinel, `reflect.py` — and two launchd jobs run out of it. It is backed up by nothing and
pushed nowhere.

Worse when read file by file: **six of the eleven were untracked**, and three of those six are
live `PreToolUse` hooks refusing work in every session at the moment they were measured —
`dupe-work-fence.py`, `pr-freeze.py` and `scope-guard.py` — plus `directives.py`, the founder-
directive index. They existed in exactly one place: uncommitted, on one laptop's disk.

**Half-fixed in this pass.** All eleven are now committed (`b95e629`), after a scan for secret-
shaped literals found none. That removes "uncommitted", not "unbacked": `git remote -v` is
still empty, so the repository exists on this machine only. Giving it a remote pushes the
estate's guard machinery to a hosting account and is the founder's call, not mine. Task #100
owns the rest and is the cheapest item in the whole F4 group.

**F4d — LUX is mostly untracked and the POPDD gate is currently switched off.** Of the files
under `.lux/`, **3 are tracked and 23 are not** — the spec registry's receipts and the signing
key. POPDD's code IS tracked (`scripts/popdd_verify.py`, `popdd_agent.py`, two tests), but
measured right now `git config --get core.hooksPath` is unset and there is no `pre-commit` in the
hooks directory, so **the gate refuses nothing on this machine today**. A gate that is off is
indistinguishable from a gate that passes, which is L11 clause 2.

**F4e — The console password sits in a launchd plist in clear text.** `com.prospector.ops-console`
carries `CONTROL_CENTER_PASSWORD` in its `EnvironmentVariables` (name only — the value was never
read). `launchd_plists.py` redacts secret-shaped keys before snapshotting, so the tracked copy is
clean; the installed plist on disk is not. Filed with F5.

**F4f — Two jobs are failing right now, and the detector that would say so was dead.**

- `com.prospector.process-audit`, exit **2**, hourly: `can't open file
  '.../prospector-live/scripts/process_audit.py'`. That file landed on main at 2026-08-19 10:13
  and the live checkout is 44 commits behind.
- `com.prospector.backup`, exit **78** (`EX_CONFIG`); `store/backup.log` ends 2026-08-17 09:38 on
  a `PASS`. Tasks #92 and #109.

`scripts/process_audit.py:700` runs `launchd_plists.py --check` and is its **only** caller in the
estate. Run by hand today it works and exits FAIL with 14 findings. It has been telling nobody,
hourly, since its runner died. The detector was never silent; its runner was dead, and nothing
watches runners.

`--check` could not catch its own runner either. `broken_programs()` validated
`ProgramArguments[0]` — the Python interpreter. Every job here is `python <script>`, so it checked
the one argument that never goes missing, and the missing script sat at index 5. **Fixed in this
pass** (`scripts/launchd_plists.py`, with a regression test built from that plist and proven to
fail against the previous code). *Needs a human:* rolling `prospector-live` forward is the
console's `Update live checkout` button — an agent is refused it.

**What F4 means for the bar.** A 30-minute migration reads the repo and reproduces the stack. On
this machine the repo describes maybe half of it: the schedule lives in `~/Library/LaunchAgents`,
the DR tool in `~/.prospector/bin`, the guards in a remote-less repo under `~/.claude`, the
receipt wrapper in `~/.hermes`, and the running code in a checkout 44 commits stale. Every one of
those is a thing that would simply not exist on the new laptop, and nothing today would tell you
which.

**F5 — Secrets live in at least four places. FLAKY (no source of truth).**
Laptop `.env`; 15 Fly secrets on `prospector-engine` alone; 3 GitHub repo secrets; `~/.hermes/`.
There is no single inventory, so "did we move all the secrets" is not a question that can be
answered — only guessed at. Two rotations are already outstanding from transcript leaks (tasks
#38, #108), which is the direct cost of having no managed store.

**F6 — Nothing is ever rehearsed. ABSENT.**
No scheduled restore drill of the full estate, no chaos test, no failover test. A single
`restore_drill.py` exists for the engine snapshot and is the only rehearsal in the estate. Under
L11 rule 3, every recovery claim in this repo is currently a wish.

**F7 — Hermes state is not backed up. CONFIRMED today.**
The `hermes/` prefix in `prospector-backup` holds exactly one object: `leader.json`, 313 bytes,
leader-election state, rewritten constantly. It backs up nothing. Watching it would have reported
green forever — a false green, the worst grade there is. Hermes is in scope by founder
instruction, so this is a live gap, not a nicety.

**F8 — Fixed today, recorded so the class stays closed.**
`scripts/backup_store.py` writes the engine store's only offsite copy (`ledger/`, `db/`, `repo/`)
and until today nothing graded the result; the evidence was the job's exit code. An exit code says
the job ran, not that bytes landed. `ops/automations/offsite_backup.py` now grades the newest
object under each prefix, and `main()` already returns a non-zero exit that `receipt.sh` records.
10 tests, including the negative fixtures. Commit `7d905dd7`.

**F9 — We log everywhere and can read nothing. ABSENT, and it is the founder's own finding.**

Founder, 2026-08-19: *"right now we dont have proper loggin visibility in store fonrt, engine adin
etc — we log but no cetral place to view, and there is a story for this."* Measured, and it is
worse than "no central place":

*Zero* log **aggregation** is configured anywhere in this estate: nothing ships a log line off the machine that wrote it, to anywhere, ever.

**Correction, 2026-08-19.** This paragraph previously said that searching the tree for `loki`, `grafana`, `datadog`, `sentry`, `opentelemetry`, `otel`, `axiom`, `vector`, `fluentbit`, `betterstack`, `papertrail`, `logtail` returned hits **only** inside `store/scheduler/audit/*.jsonl` and the shadow logs — candidate *business ideas the engine generated about observability companies*, not configuration. That is true of eleven of the twelve terms and false of `opentelemetry`, which I missed because the sweep did not reach `store_platform/`. OpenTelemetry is pinned in `store_platform/Directory.Packages.props:68-71` and ships inside a package Store.Api already references. What survives from the original claim is the part that matters — nothing is *aggregated* — but the estate is closer to it than I wrote, and that changes the plan rather than the verdict. See “what already exists” below. The single real code reference in the whole repo is
`store_platform/src/Store.Web/src/components/ErrorBoundary.tsx:32`:

> `// Surface in the console for now; a real reporter (Sentry) is a deferred, founder-gated decision.`

So the storefront catches every React error and writes it to a browser console nobody is watching.

Where logs actually go, counted from `ops/launchd/*.json` and disk:

| Destination | Jobs | On disk | Survives a laptop swap? |
|---|---|---|---|
| `~/.hermes/logs` | 26 | **71 MB, 2,013 files**, 2026-06-21 → 2026-08-19 | **No** — and F7 proved the R2 `hermes/` prefix backs up nothing |
| `/tmp` | 4 | purged by macOS | **No** — and one of the four is the **ops console itself** |
| `store/scheduler` | 6 | in the store | Only because the store is backed up (F8) |
| `~/Library/Logs/actions.runner.*` | 8 | 35 MB, 402 files | No |
| Fly (engine, API, web, Hermes) | 4 apps | rolling buffer only, no shipping configured | **No** — logs die with the machine |

**Four consequences, none hypothetical.** A customer-facing error in the storefront is recorded
nowhere durable. A question spanning the web, the API and the engine cannot be answered at all,
because the one request identifier that does exist is
born and dies inside the API. Two months of Hermes history exists in
exactly one copy, on the laptop. And the ops console — the surface the founder wants everything
driven from — writes its own logs to a directory macOS deletes on reboot.

**What already exists, measured 2026-08-19, and it changes the plan from build to extend.**

Store.Api is not starting from nothing. It has a correlation id, wired end to end *within itself*:

| Where | What |
|---|---|
| `Program.cs:72` | `builder.Services.AddCorrelationId();` |
| `Program.cs:77` | `http.AddHttpMessageHandler<CorrelationIdHttpClientHandler>();` — every outbound HTTP call carries it |
| `Program.cs:225` | `app.UseCorrelationId();`, with the comment that it must be early "so every log line carries the id" |
| `Common/HttpContextExtensions.cs:11` | `public const string CorrelationIdHeader = "X-Correlation-Id";` |
| same, `:13` | `GetCorrelationId()` — honours an inbound header, falls back to `TraceIdentifier` |
| `Common/Audit/IAuditLogger.cs` | already writes the id into every structured AUDIT line |

The implementation is in `Crux.Observability 1.0.0`, which also drags in
`OpenTelemetry.Instrumentation.AspNetCore`, `.Http`, `.EntityFrameworkCore` and `.Runtime` plus
`OpenTelemetry.Extensions.Hosting` (read from the package's own nuspec). So the API already pays
for OpenTelemetry instrumentation on every build.

**It never switches it on.** `AddOpenTelemetry`, `WithTracing`, `AddOtlpExporter` and
`ActivitySource` appear nowhere in `store_platform/src/Store.Api/`. The package describes itself as
"OpenTelemetry wiring, correlation-id middleware, health checks", but the only extension methods it
exposes are `AddCorrelationId`, `UseCorrelationId`, `AddDbHealthCheck` and `AddDbContextCheck` —
there is no entry point that would activate tracing. (Method: `strings` over
`lib/net9.0/Crux.Observability.dll`. That is indicative, not exhaustive; the confirming step is
reading the assembly metadata, and it is worth doing before anyone plans work around it.)

The three ends that are genuinely absent, each measured with `rg` and no `-r` flag:

| Surface | Correlation id | Evidence |
|---|---|---|
| Store.Web (storefront) | **none** — the browser never sends one | 0 matches in `src/`; the fetch wrappers in `lib/api/client.ts` set only `Content-Type` |
| Ops.Console | **none** | 0 matches in `src/` |
| Engine (`prospector/`) | **none** | 0 matches across the package |

So the honest shape of F9 is narrower and cheaper than "build request tracing": the id exists and
is correct in the middle tier, and the work is to originate it at the browser, accept and log it in
the engine, and pick something that stores the result. A second correlation id must not be built.

**Method note, because it nearly cost a wrong plan.** My first pass at this measurement used
`rg -rn`. In ripgrep `-r` is `--replace`, not `--recursive`: it substituted the literal `n` for
every match, so `CorrelationIdHeader` printed as `"n"` and the engine sweep printed nothing at all.
Read cleanly, the engine result is the same (zero), but it was zero for the wrong reason for an
hour. rg recurses by default. Memory: `rg-dash-r-is-replace-not-recursive.md`.

**The story the founder remembered is real, and it is two months old.**
`specs/observability-gap-search.md` (2026-06-24) diagnoses `web_calls=0` and states the class in
its own words: *"we shipped a metric nobody incremented, and the metric is what we used to decide
whether the search was firing"*, with the founder directive *"we cannot be guessing; we must log
and observe thoroughly; we must prevent this from ever happening again."* It was scoped to search
only, and the generalisation never happened.

**And this is the same defect three times.** The spec's metric nobody incremented (2026-06-24);
launchd jobs whose non-zero exits nobody reads, two of them failing right now (§3b); backups graded
by an exit code that only proved the job ran (F8, fixed today). Same class every time: **a signal
was emitted and nothing consumed it.** Observability here is not a missing vendor, it is a missing
rule — *emitting is not observing, and a signal with no consumer is not evidence.* That belongs in
`PLATFORM_MANIFESTO.md` as a law, because a fourth instance is otherwise certain.

**F10 — We are building scripts to survive our process instead of fixing it. CONFIRMED.**

Founder, 2026-08-19: *"we are building a lot of scrits to ange pipeline and i just wonder if our
proces is broke."* It measures, and the number is worse than the intuition:

```
16 scripts reference gh run / gh workflow / gh pr / actions/runs / workflow_run / runner
6,505 lines of code
```
`branch-pr-guard.py`, `dupe-work-fence.py`, `pr-freeze.py`, `pr-why.py`, `push-pr-fence.py`,
`rule-guard.py`, `tool-drip-guard.py`, `blocker_probe.py`, `ci_fleet_probe.py`, `ci_local.py`,
`popdd_verify.py`, `seed_action_cache.sh`, `site_spec_probe.py`, `verify_engine_change.sh`, and two
more. **6,505 lines is 39% of all bespoke ops code in this estate (16,637), written to work around
a pipeline that is still only 55% green.**

Every one is individually justified — each closed a real incident, and several are mine. That is
what makes it a process finding rather than a code-quality one: **the local decision was correct
every time, and the aggregate is a system nobody can move.** Each guard is load-bearing, so a
migration must carry all 16, which is the opposite of portable.

The pattern is a merge queue rebuilt by hand, badly: `push-pr-fence` serialises pushes,
`dupe-work-fence` allocates work, `pr-freeze` gates merging, `branch-pr-guard` scopes ownership.
GitHub's own merge queue does all four — and per `~/.claude/CLAUDE.md` it is unavailable because
this account gets `403 Upgrade to GitHub Pro` on both `/branches/main/protection` and `/rulesets`.
**So the honest root cause of F10 is a £dozens-per-month plan tier, and the estate has been paying
for it in 6,505 lines of Python instead.** That is a founder decision, not an engineering one
(§10), and it is the cheapest single item in this entire audit.

Grade: **the guards are SOUND individually and the process around them is FLAKY**, by L11 rule 4 —
each one moves the failure rather than removing it.

---

**F11 — Four .NET dependencies are binaries whose source is in another private repo.
CONFIRMED. Blocks selling, not bootstrapping.**

Found while measuring F9, and it is a portability finding rather than an observability one.

Store.Api builds against `Crux.Storage`, `Crux.Resilience` and `Crux.Observability`, and pulls
`Crux.Kernel` transitively. All are vendored into the repo as `.nupkg` files under
`store_platform/local-feed/` and all are git-tracked, together with `store_platform/nuget.config`,
which maps `Crux.*` to that folder by package-source mapping. **A fresh clone therefore builds with
no token and no sibling checkout.** That was deliberate and it works; the comment in `nuget.config`
says so, and `git ls-files` confirms all eight nupkgs are committed.

What is not in the repo is the source. Each package contains `lib/net9.0/*.dll` and nothing else —
no `.cs`, no `.pdb`, no SourceLink. The source is `github.com/chidionyema/crux`, **private**, last
pushed 2026-07-10, and it is **not on this machine**: `nuget.config` names `~/Documents/code/crux`
as the place to rebuild the feed from, and that directory does not exist.

Three consequences.

1. **A defect inside Crux cannot be fixed from this repo.** Not hypothetical — the workaround is
   already written into `Directory.Packages.props:64`. OpenTelemetry advisory GHSA-g94r-2vxg-569j
   arrives through `Crux.Observability 1.0.0`, "which is on the local feed and will not move", so it
   was cleared by pinning the transitive package instead. That answer works for a dependency *of*
   Crux. There is no answer for a defect *in* Crux.
2. **It contradicts the one rule that survived the hosted-inference rewrite.** The project rule is
   that the repo stays the complete system. Four DLLs are the exception. For "packaged up and
   portble", a buyer receives code they cannot rebuild unless the sale includes the crux repo.
3. **Four of the eight vendored packages are unreachable.** `Crux.Idempotency`, `Crux.Identity`,
   `Crux.Notifications` and `Crux.Payments.Stripe` have no `PackageVersion` entry, and central
   package management is on, so nothing can reference them; none is a dependency of the four that
   are used either. They are dead weight — and dead weight named `Payments.Stripe` and `Identity`
   is worse than neutral, because it reads as though the money path sits behind a binary. It does
   not: only three `.cs` files in the whole solution import Crux at all.

**Grade: SOUND on bootstrap, FLAKY on sell-the-business.** A new developer on a new laptop can
build today. Patching and selling are what break.

**Options, for the founder to decide — this is a repo-ownership question, not a technical one.**
Publish the packages to GitHub Packages and keep the vendored feed as the offline fallback (cheap,
keeps the private repo private, but a buyer still needs the repo). Or add crux as a git submodule
or a vendored source drop (makes this repo genuinely complete, at the cost of merging the kernel's
history into the sale). Or build the packages with `<IncludeSymbols>` and SourceLink, which fixes
debugging but not patching. Doing nothing is defensible while the kernel is stable; it stops being
defensible the day an advisory names a Crux package rather than one of its dependencies.

Cheap and independent of that decision: delete the four unreachable nupkgs, or add the
`PackageVersion` lines if they were meant to be used. That is a measurement away from being a
one-line PR and needs no founder input.

**F12 — Our CI falls back to a platform we cannot pay for, and says so in a message that
blames the code. CONFIRMED, measured 2026-08-19.**

The founder asked why the build had been broken two days running. Part of the answer is a finding
in its own right, and it is not a test.

Every job in `ci.yml` is scheduled with
`runs-on: ${{ vars.CI_LIGHT_RUNS_ON || vars.CI_RUNS_ON || 'ubuntu-latest' }}`. When those repo
variables are absent the job goes to GitHub's hosted runners, and **GitHub-hosted Actions minutes
are not payable on this account**. The jobs then fail before running a single step, with:

> The job was not started because recent account payments have failed or your spending limit needs
> to be increased.

Measured across the last 40 failing runs, that happened in exactly one window — runs
`32294852235` (19:46:12Z) and `32295066869` (19:48:33Z) — and the three `CI_*_RUNS_ON` variables
were created at **19:49:40Z**, one minute after the last one. Since then CI has run on the Fly
runners (`runner-8576715b121d68` and siblings) and PR #445's jobs are green. So the window closed
by itself, and nobody wrote down that it had happened.

**What it does NOT explain:** the two days of red. Those runs had runners and ran their steps —
they are real failures, covered by F10 and by `docs/STACK_FLAKINESS_AUDIT.md`. This finding is a
different defect that was hiding inside the same red tick.

**The class:** *a fallback that points at a platform we cannot use*. It is the same shape as F4a's
frozen failover copy — a safety net configured once and never checked against the world it now
lives in. It fails at the worst moment, and its error message accuses the account rather than the
config, so the reader goes to Billing instead of to `runs-on`. Three variables deleted or renamed
puts every branch back into this state with no warning.

**The guard is one line and it is not written**, because the founder parked CI work
(*"forget cicd for now ... revisit it as last step"*). Recorded here so it is not rediscovered: the
`guard` job should assert `vars.CI_RUNS_ON` is non-empty and fail with the real reason. The
alternative — deleting the `|| 'ubuntu-latest'` fallback so an unset variable produces an obviously
invalid label — is smaller still. Task #104 is the nearest home for it.

## 6. What the ops console can already do

The dashboard is not a greenfield. 21 actions are wired today
(`store_platform/src/Ops.Console/src/pages/api/ops/act/[action].ts`): `pause.arm`, `pause.disarm`,
`routing.set_moat_primary`, `drain.reset`, `config.set`, `config.restore`,
`catalogue.set_listing`, `shelf.repair_copy`, `shelf.publish_pending`, `shelf.regate`,
`daemon.restart`, `tools.run`, `tools.undo`, `deliveries.resend`, `engine.switch`, `engine.arm`,
`engine.disarm`, and others.

**The pattern to extend, not replace.** Every action goes through one authenticated POST endpoint
with an actor stamp (`payload.actor = 'ops_console'`). Migration control belongs in that same
endpoint as `migrate.plan`, `migrate.apply`, `migrate.cutover`, `migrate.rollback` — not in a new
surface. The founder's "all by ops dashboad" is therefore cheap in the right design and expensive
in the wrong one. Note also the precedent already set in that file: price writes are *deliberately
refused* at the console with a pointer to `bridge.py`. Dangerous actions get refused, not hidden.

---

## 7. Options — all of them, with the argument

Founder: "ssorry i need tosee all solutions proposed" and "i need justifications alo outputted
before final decsion". **Nothing below is chosen.** The recommendation column is my argument, and
it is the thing to disagree with.

### 7a. How the estate is described

| Option | For | Against | Grade |
|---|---|---|---|
| **Terraform / OpenTofu** | Industry standard; Fly, Cloudflare, Hetzner, R2 all have providers; state file is the inventory the estate has never had; a buyer's engineers already know it | State file is itself state that must be backed up; drift if anyone touches a console | The only option that answers "did we move everything" mechanically |
| **Pulumi** | Real language, so logic is testable | Smaller ecosystem; ties the estate to a company | Viable, weaker on portability of skills |
| **Ansible** | No state file; good at machines | Weak at cloud resources; imperative drift returns | Wrong shape for this estate |
| **Keep bash in `deploy/`** | Zero migration cost | Is the current state, and the current state has no inventory | Rejected by F4 |

### 7b. How jobs are run

| Option | For | Against | Grade |
|---|---|---|---|
| **Dagu** | Single Go binary, YAML DAGs, has a UI, runs anywhere, no database | Small project | Fits "portable today, tomorrow, forever"; replaces launchd *and* supervisord with one declaration |
| **Temporal** | Durable execution, retries,真 observability | Heavy: server + database; large operational surface for a startup | Over-built for 30 jobs |
| **systemd timers** | Boring, universal on Linux | Not on macOS, so the developer stack still needs launchd — two systems again | Fails the two-stack requirement |
| **Keep 30 launchd plists** | Works today | F4: six already untracked; macOS-only; invisible failures (§3b) | Rejected |

### 7c. Developer environment

| Option | For | Against | Grade |
|---|---|---|---|
| **Devcontainer + Dockerfile** | One command; identical to CI; a buyer's engineer is productive in an hour; works on any laptop | Docker Desktop licensing on macOS; slower filesystem | Directly answers F3 and the sellability question |
| **Nix flake** | Genuinely reproducible, no daemon | Steep learning curve; a hiring constraint | Best engineering, worst for onboarding a stranger — which is the actual goal |
| **`mise` / `asdf` + a bootstrap script** | Light, native speed | Pins tool versions only, not system deps | Good complement, not sufficient alone |
| **Document the steps in README** | Cheapest | A documented trap is not a guarded trap | Rejected |

### 7d. Secrets

| Option | For | Against | Grade |
|---|---|---|---|
| **SOPS + age, committed encrypted** | One source of truth, in git, versioned, diffable; no server; works offline; a buyer receives it with the repo | Key custody is a human decision — see §10 | Fits an estate with no server budget |
| **Infisical / Doppler / Vault** | Rotation, audit log, UI | Another service to run or pay for; another thing to migrate | Revisit at team size > 3 |
| **Status quo** | — | F5 | Rejected |

### 7e. Where the platform runs

Founder constraint: no platform lock-in, and the target may be on-prem *or* another cloud.

| Option | For | Against | Grade |
|---|---|---|---|
| **Stay on Fly, make it reproducible** | Least change; keeps today's latency | Does not prove portability; a single-region volume is still a single point of failure | Necessary first step, not the destination |
| **Hetzner as the proving target** | Cheap enough to run a real drill; genuinely different provider, so it proves portability rather than assuming it | New surface to learn | The drill target: if it works to Hetzner it works anywhere |
| **On-prem** | Full control; the founder named it | Hardware, power, network are new failure modes | Deferred until the drill passes to a cloud target |

### 7f. State — the thing that actually decides whether 30 minutes is possible

Two SQLite databases (money at `/data/store.db`, engine catalogue) currently pin the estate to
specific volumes on specific machines.

| Option | For | Against | Grade |
|---|---|---|---|
| **Litestream** (continuous replication to R2) | Keeps SQLite; sub-second RPO; cutover becomes "point the new host at the replica"; no application change | Single-writer discipline must be enforced | Turns migration from a copy into a switch. This is the enabling move for D1 |
| **Managed Postgres** | Multi-writer, mature | A migration inside a migration; re-locks to a provider | Founder already said "postgress spit fone" — revisit later, not now |
| **Copy the file during a maintenance window** | Simple | Downtime, and the bar is zero downtime | Rejected by the bar |

### 7g. Observability — one place to look (F9)

Requirements this must meet, before any vendor is named: it survives losing the laptop; it costs
near nothing at this scale; it takes logs from Fly apps, launchd jobs and the browser alike; it is
not a new single point of failure; and it moves with the estate to any provider.

| Option | For | Against | Grade |
|---|---|---|---|
| **Grafana Cloud free tier** (Loki + Alloy) | 50 GB/mo free, far above this estate's volume; Loki is open source, so self-hosting later is a migration not a rewrite; one query surface for logs and metrics | Vendor account is one more thing to migrate | Best fit for the requirements as stated |
| **Self-hosted Loki + Grafana on Fly** | No vendor at all; fully portable | Another service to run, back up and monitor — and it dies with the region it is in | Right answer later, wrong answer while the estate is this fragile |
| **Better Stack / Axiom** | Excellent ergonomics, generous free tiers | Proprietary query language; weaker exit path | Viable, worse on lock-in |
| **Ship to R2 as JSONL and query with DuckDB** | Zero new infrastructure; uses a bucket we already back up; genuinely free | No live tail, no alerting; a bespoke tool to write — the exact habit F10 names | Rejected on F10 grounds |
| **Status quo** | — | F9 | Rejected |

**Re-weighed 2026-08-19, after measuring what the API already has.** The API already carries
OpenTelemetry instrumentation (through `Crux.Observability`) and a correct `X-Correlation-Id`, and
simply never activates the tracing. That does not change the grade, but it changes the reason: the
question is now which sink to point an OTLP exporter at, not what to build. It strengthens the
first row — Grafana Cloud accepts OTLP natively, so the API side becomes configuration rather than
code — and it strengthens the case against the R2+DuckDB row further, since that one would mean
discarding instrumentation already paid for. It also puts a floor under the exit argument: an OTLP
exporter can be repointed at a self-hosted Loki later by changing an endpoint.

Two parts of this are independent of the vendor choice and should exist whichever way it goes.
**A request identifier that crosses the storefront, the API and the engine.** One third of this
exists and is done well; what is missing is originating the id in the browser's fetch wrappers
(`Store.Web/src/lib/api/client.ts` and its two siblings, which today send only `Content-Type`) and
accepting and logging it in the engine, which has no correlation id anywhere. Extend
`X-Correlation-Id`; do not introduce a second scheme. And **a real error reporter behind
`ErrorBoundary.tsx:32`**, since a customer-visible error currently persists nowhere. Both are
small; neither is done.

**Ops console:** the console renders what the aggregator holds — it does not become a second log
store. Extending the existing action pattern (§6) keeps "all by ops dashboad" cheap.

---

## 8. Proof: drills and chaos, because untested recovery is not recovery

Founder: "well tested proved docunented and bullet proof with regular drills" … "and chaos tests".
This section is what turns every claim above from a wish into a measurement, and it is why
staging (F1) comes first — you cannot rehearse against production.

**Drills — scheduled, timed, with the clock as the pass/fail:**

| Drill | Question it answers | Pass condition |
|---|---|---|
| Restore drill | Do the backup bytes reconstitute a working system? | A store rebuilt from R2 alone passes the suite |
| Migration drill (M6) | The bar itself | Full stack up on the target, timed, ≤ 30 min, zero failed customer requests |
| Secret drill | Can we stand up from the encrypted store alone? | No `.env` on disk anywhere, everything still runs |
| Onboarding drill | F3 | A clean machine to a passing test suite, one command, timed |

**Chaos tests — the failure is injected, and the guard must fire:**

| Injected | Must happen | Grades |
|---|---|---|
| Kill the engine machine mid-run | Work resumes, no candidate lost | the DEFER/resume rails |
| Revoke an R2 credential | Backup fails LOUDLY, receipt non-zero | F8's fix |
| Stop the backup job for 48h | The freshness check goes red | the check committed today |
| Partition Hermes from its leader lock | No split brain | leader election |
| Fill the store volume | Refuses cleanly, does not corrupt | SQLite write path |
| Kill a job mid-write | No torn database | `VACUUM INTO` discipline |

**The rule that makes these worth running: each drill and each chaos test must be seen to FAIL
first.** A check never observed red is a check not known to work — the negative-fixture standard
already used in the estate's tests, applied to infrastructure.

---

## 9. Why execution has not started

The founder's judgement, stated in measured terms so the next session does not relitigate it:

1. **No staging (F1).** The first migration rehearsal would be against production. Not acceptable.
2. **CI is 55% green (F2), and 6,505 lines exist to work around it (F10).** A migration change
   cannot be proved safe before it lands, and a migration must currently carry all 16 guards.
3. **The inventory is incomplete (F4).** Six installed jobs are described nowhere. Migrating an
   estate you have not finished listing is how "nothing beig used" gets missed.
4. **Two of the dimensions in §2 have no baseline (D1, D2).** A 100x claim needs a starting number.
5. **No observability (F9).** A cutover with no central log view cannot be watched while it
   happens, which makes "prove and see realtine progress" impossible by construction. This is the
   one finding that is a hard blocker on the bar itself, not merely on confidence.
6. **Two decisions are genuinely the founder's (§10).**

**Ordering.** Each step exists because the one after it is impossible without it: finish the
inventory (F4) → get state replicating (7f Litestream) so cutover is a switch and not a copy →
staging (F1), which is the first customer of the inventory and the venue for every drill →
declared jobs (7b) and one secret store (7d) → dashboard actions (§6) → then the timed drill (M6),
which produces the first real number for D1.

---

## 10. The one thing that is not mine to decide

**Custody of the age private key** (7d). If secrets are committed encrypted, one key decrypts the
estate. Where it lives — the founder's machine only, a hardware key, split between founder and a
second holder, or escrowed for a buyer — is a business and continuity decision, not an engineering
one, and it changes what gets built. **Everything in §9 except the secret store can proceed without
this answer**, so it is not a blocker on starting; it is a blocker on finishing 7d.

**Second: the GitHub plan tier** (F10). A paid tier restores branch protection, rulesets and the
native merge queue, which is what four of the sixteen guards are hand-rolling. It is the cheapest
line item in this audit and it deletes more code than any refactor proposed here. A spend decision,
so it is recorded and not taken.

---

## 11. Sellability

Recorded because the founder named it and because it changes priorities, not just wording. What a
buyer's technical diligence asks, and what this estate answers today:

| Question | Today | Fixed by |
|---|---|---|
| Can a new engineer be productive quickly? | No — F3, 13 of 13 env files absent | 7c |
| Is the infrastructure described anywhere? | No — 199 artifacts, no inventory | 7a |
| Can it run somewhere other than your accounts? | UNPROVEN — never attempted | 7e + the M6 drill |
| Where are the secrets? | Four places, two outstanding rotations | 7d |
| Has recovery ever been tested? | No — F6 | §8 |
| Can you see what your system is doing? | No — F9, zero aggregation | 7g |
| How much of the code is workarounds? | 39% of ops code works around CI — F10 | F10 + §10 |
| Is the pipeline healthy? | 55% green | F2 (another session) |

Each row is a discount on the asset. That is the commercial case for doing the consolidation
properly rather than lifting and shifting.

---

## 12. How to keep this document honest

It goes stale the moment the estate moves, and a stale audit read as current is worse than none —
the defect this estate has hit repeatedly. So: **every number in §2, §4 and §5 must be reproducible
by a command**, and the intent is that `scripts/` grows one probe that re-measures the table in §2
and fails when a claim here stops being true. Until that probe exists, this document is dated,
says so at the top, and every figure carries the date it was taken.
