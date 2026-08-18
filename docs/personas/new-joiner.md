# New joiner — day one to productive

**Seat:** you just got access. You have not written a line yet.
**Rule for this document:** every number and path below was measured on **2026-08-18** on this
laptop, from `/Users/chidionyema/Documents/code/prospector` at HEAD `c3cb68b`. Where something could
not be proven it says `HYPOTHESIS:` with the exact check. Re-measure before you quote any of it.

Shared facts live once, in [../ESTATE_MAP.md](../ESTATE_MAP.md).

---

## 1. What the company does, in five sentences

An engine reads a market signal, invents business ideas from it, and then tries to kill each one
using only evidence it fetched from the live web. Ideas that survive seven checks get scored,
written up as a research pack, priced on a fixed ladder, and published to a shop at
`mumchimp.com`. A buyer pays once, through Stripe, and gets the pack. The engine runs unattended on
a schedule behind two rails — a daily spend cap and a filesystem kill switch — because there is no
human in the loop. Measured today, 2,995 ideas have been through the filter, 108 passed, and 74 are
on the shelf for £4,229.26 in total.

**The two things that make this codebase unusual:** every verdict must cite a source it actually
fetched, and every claim anyone makes about the system must carry a `file:line` or a command's
output. Both are enforced by tests, not by good intentions.

---

## 2. The one command that shows you the estate

```bash
cd /Users/chidionyema/Documents/code/prospector
.venv/bin/python scripts/ops_status.py
```

It grades 40 risk items across eight families and prints one line of evidence for each. Real output
from 2026-08-18, abridged:

```
  OPEN     SRC-1   Nothing is committed
                   132 uncommitted paths, 0 ahead / 27 behind origin/main
  DONE     SRC-3   Repo public under MIT
                   repo visibility is PRIVATE
  OPEN     INF-1   API is one machine in one region
                   min_machines_running = 1 in store_platform/deploy/fly/api.fly.toml
  OPEN     DAT-2   Restore never proven end to end
                   scripts/restore_drill.py exists; no dated receipt under store/ops/
  MANUAL   ENG-3   Grounding runs on one fast provider
                   no mechanical check written yet
  DONE     PAY-1   API knows it is in live mode and tells nobody
                   store_platform/src/Store.Api/Payments/MoneyRailStatus.cs is on origin/main
```

**How to read the four grades.** They are not a pass/fail pair.

| Grade | Means | What you do |
|---|---|---|
| `DONE` | a mechanical check ran and the risk is closed | nothing |
| `OPEN` | a mechanical check ran and the risk is live | the evidence line tells you where |
| `MANUAL` | **no check has been written yet** | this is an *unknown*, not a pass |
| `ACCEPTED` | someone decided to live with it, on the record | leave it alone |

The families are `SRC` (source control), `INF` (infrastructure), `DAT` (data), `AST` (assets),
`DNS`, `BIZ` (business/legal), `PAY` (payments), `ENG` (engine). Today's tally: 6 `OPEN`, 22
`MANUAL`, 4 `DONE`, 8 `ACCEPTED`.

**The second command you will use every day** answers "is the engine actually running". **The
engine runs on Fly, not on this laptop** — it moved there on 2026-08-18 — so the command is:

```bash
fly status -a prospector-engine
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
```

Real output from 2026-08-18 13:12Z:

```
Machines
PROCESS  ID              VERSION  REGION  STATE    LAST UPDATED
app      80d34da6636478  12       lhr     started  2026-08-18T11:39:47Z

{"ts": "2026-08-18T13:12:26.504469+00:00", "pid": 679, "phase": "sleeping",
 "interval_s": 7200, "cycles": 1, "code": "617c2538c433"}
```

You want `state = started` and a heartbeat `ts` within minutes of now.

**Now the trap, and it is the first one that will fool you.** There is another probe in this repo:

```bash
.venv/bin/python scripts/live_checkout.py   # DO NOT TRUST THIS
```

It prints `NOT RUNNING` three times and `MISSING:
/Users/chidionyema/Documents/code/prospector-live`. That is not an outage. It is the correct
description of the **laptop deployment that was retired on 2026-08-18**, by a probe that was not
retired with it. The same applies to `store/scheduler/heartbeat.json` in this checkout: it is hours
stale because the Fly engine writes to its own volume, not to this disk.

The general lesson, which is worth carrying to your next job as well: **a monitoring probe must be
retired with the thing it monitors.** A probe left pointing at decommissioned infrastructure does
not go quiet — it reports absence, and absence looks exactly like failure.

---

## 3. The map of the code

Measured with `find <dir> -type f | wc -l` and, for Python, `find <dir> -name '*.py' -exec cat {} + | wc -l`.

| Directory | Files | Python lines | What lives there |
|---|---|---|---|
| `prospector/` | 451 | 66,664 | **the engine.** 153 `.py` modules. Start here. |
| `store_platform/` | 79,865 | — | **the shop.** 196 `.cs`, 299 `.ts`/`.tsx` (excluding `node_modules`/`obj`/`bin`) |
| `tests/` | 1,169 | 73,116 | 369 `test_*.py` files. Larger than the engine it tests. |
| `store/` | 37,381 | — | **runtime state, 707 MB.** Never commit anything here. |
| `tools/` | 210 | 20,369 | 40 backfill and one-off tools |
| `publish/` | 193 | 259 | the publish package (the top-level one is real; `prospector/publish.py` is a stub) |
| `scripts/` | 60 | 8,592 | operator commands, probes, the commit gate |
| `docs/` | 54 | — | 20,330 lines of programme documents |
| `ops/` | 49 | 1,583 | launchd job definitions + `ops/automations/` |
| `specs/` | 47 | — | design specs |
| `prompts/` | 28 | — | prompt templates |
| `signals/` | 25 | — | saved market signals, including `signals/pending/` for resume |
| `fixtures/` | 5 | — | offline retrieval fixtures for tests |
| `deploy/` | 5 | — | deployment helpers |
| `graphify-out/` | 4,658 | — | generated knowledge-graph output. Ignore it; do not grep it. |

Plus `config.yaml` at the root: **2,550 lines**. It is not a settings file. It is the written record
of every behavioural decision with the reasoning attached. Read the comment above a key before you
change the key.

### 3.1 The engine's ten modules that matter

The eleven largest, by `find prospector -name '*.py' -exec wc -l {} + | sort -rn`:

| Lines | Module | Role |
|---|---|---|
| 4,317 | `prospector/run.py` | the CLI. Orchestrates the eight steps in `RUN.md`. |
| 2,884 | `prospector/scheduler/run_scheduled.py` | the unattended daemon. `run_tick` at `:1666`. |
| 2,548 | `prospector/ops/console_api.py` | what the ops dashboard reads |
| 2,511 | `prospector/retrieval.py` | web fetching, caching, per-provider circuit breakers |
| 2,457 | `prospector/bridge.py` | the money rail's entry point |
| 2,147 | `prospector/pack_linter.py` | grades a finished pack before it may be listed |
| 1,791 | `prospector/operator.py` | the swappable brain. `moat_primary()` at `:1443`. |
| 1,465 | `prospector/artifacts.py` | builds the pack's contents |
| 1,258 | `prospector/verify.py` | **the moat.** The seven checks. |
| 1,216 | `prospector/config.py` | typed config loading |
| 1,075 | `prospector/dossier.py` | composes the dossier artefact |

Two more that are small and load-bearing: `prospector/kill_filter.py` (the deterministic gates,
`is_hard_fail` at `:20`, `apply_gates` at `:54`) and `prospector/models.py` (573 lines — the
contracts: `Verdict` at `:25`, `Candidate` at `:170`, `Dossier` at `:452`).

### 3.2 The shop's four projects

Under `store_platform/src/`:

- **`Store.Api`** — the money and delivery API, deployed to Fly as `prospector-store-api`
  (`store_platform/deploy/fly/api.fly.toml:20`). Routes in
  `store_platform/src/Store.Api/Endpoints/`: `CheckoutEndpoints.cs`, `WebhookEndpoints.cs`,
  `DeliveryEndpoints.cs`, `OpsEndpoints.cs`, `AnalyticsEndpoints.cs`, `FounderPreviewEndpoints.cs`.
  Payments in `store_platform/src/Store.Api/Payments/`: `StripeProvider.cs`, `IPaymentProvider.cs`,
  `MoneyRailConfigGate.cs`, `MoneyRailStatus.cs`, `PaymentReversal.cs`.
- **`Store.Web`** — the public shop, Fly app `prospector-store-web`
  (`store_platform/deploy/fly/web.fly.toml:12`).
- **`Store.Catalog`** — the shared catalogue model.
- **`Ops.Console`** — a Next.js dashboard, run locally under launchd.
- **`Store.Tests`** — the platform test suite.

---

## 4. Setup, from a clean machine

Do these in order. Each step names the failure you get if you skip it, because in this repo every
one of those failures blames the wrong thing.

### Step 1 — Clone and pick your working directory

```bash
git clone git@github.com:chidionyema/prospector.git
cd prospector
```

**Skip it and:** nothing works. Obvious. The non-obvious part is below.

### Step 2 — Do NOT work directly in a shared checkout

This checkout is often used by two sessions at once. They share one `.git/index`. A `git commit` in
one wedges the other.

```bash
git worktree add --detach ../my-worktree <ref>
./scripts/setup_worktree.sh ../my-worktree
```

**Skip `setup_worktree.sh` and** you get a tree that *looks* complete and is not. The script's own
header (`scripts/setup_worktree.sh:5-38`) documents four traps it fixes and one it only warns about,
each of which fails by accusing something else:

1. **`node_modules` is absent and cannot be symlinked.** Turbopack rejects any symlink leaving the
   project root: `TurbopackInternalError: Symlink [project]/node_modules is invalid, it points out
   of the filesystem root`. The script uses `cp -Rc` (APFS copy-on-write), so 665 MB costs seconds.
2. **`.lux/keys/agent.pem` is untracked**, so the commit gate runs but cannot sign. Reads as a gate
   violation.
3. **`.venv` is absent**, and the hook pins the interpreter relative to cwd
   (`.lux/hooks/pre-commit:67`). Commits die with `sh: .venv/bin/python: No such file or directory`
   followed by `POPDD gate BLOCKED this commit` — which reads as a failed proof, not a missing
   interpreter. A symlink is fine here; `node_modules` is the odd one out.
4. **`store/` and `storage/` are tracked runtime state** that pytest writes to. The script cannot fix
   this; it just tells you. **Never `git add -A` in a worktree.**
5. **`.env` and the engine's own state are gitignored**, so a worktree gets neither.

### Step 3 — Python

`.venv/bin/python --version` on this machine reports **Python 3.14.6**.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # 116 lines
.venv/bin/pip install -r requirements-local.txt  # 18 lines
```

**Skip it and:** every script fails at `.venv/bin/python: No such file or directory`, and the commit
gate reports `POPDD gate BLOCKED` for the same reason (see trap 3 above).

### Step 4 — Credentials

`.env` is gitignored and lives only on the founder's laptop. It carries 24 named keys including
`MINIMAX_API_KEY`, `EXA_API_KEY`, `STRIPE_LIVE_API_KEY`, `R2_SECRET_ACCESS_KEY`, `FLY_API_TOKEN`,
`STORE_INTERNAL_API_KEY`. **Never print a value, never commit one, never paste one into a chat.**

**Skip it and:** you get a confusing provider failure rather than a missing-key error. The recorded
example is in `CLAUDE.md`: moving the daemons to a new checkout with no `.env` produced
`ProviderExhaustedError: All operators in ('minimax', 'minimax_m27') unavailable — check API keys
and credentials`. The keys were fine. The file was not there.

### Step 5 — Confirm the gate is or is not installed

```bash
git config --get core.hooksPath          # if set, THAT directory wins, not .git/hooks
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

**Skip it and:** you will guess wrong in both directions. `CLAUDE.md` records that this exact
confusion cost a session on 2026-08-16 — a commit failed with only "exit code 1" while the docs said
no gate could have refused it. It had refused it, on one test out of 4,124.

Never read `<root>/.git/…` as a directory. In a worktree `.git` is a **file** containing `gitdir:`.
Ask git: `git rev-parse --git-path hooks`, `git rev-parse --git-common-dir`.

### Step 6 — Run the gate by hand before you trust anything

```bash
.venv/bin/python scripts/popdd_verify.py --staged
```

It runs in lanes chosen by what you staged (`scripts/popdd_verify.py:234` `LANES`): `.py` gets ruff
plus pytest, `.cs`/`.csproj` gets dotnet *and* python, `.tsx` gets the web lane. The hard timeout is
`TEST_TIMEOUT_SECONDS` at `scripts/popdd_verify.py:86`, default **2400s**, raised from 600 on
2026-08-13.

**Two traps in the gate itself, both in `scripts/popdd_verify.py:235-241`:** ruff runs **repo-wide**
with no path arguments, so one unformatted file anywhere walls every commit in every worktree. And
the step loop breaks on a non-zero exit, so ruff's status alone blocks the commit.

### Step 7 — Prove the suite runs

```bash
.venv/bin/python -m pytest -q tests/unit -x
```

`pytest.ini:42` sets `addopts = -n auto --dist loadfile`, so it is parallel by default. That
parallelism found a real defect and can create one: a test that asserts a *duration* must measure
`time.process_time()`, not `time.monotonic()`, or being descheduled makes it a coin toss. The
comment recording that incident is in `pytest.ini` itself.

**Skip it and:** you find out your environment is broken inside a 40-minute commit instead of a
2-minute check.

---

## 5. Your first change, end to end

A worked walkthrough. The example: you have been asked to lower the price warn threshold.

### 5.1 Find the truth, not the doc

```bash
grep -n "warn_at_usd" config.yaml prospector/config.py prospector/ops/spend.py
```

Real output today shows three different places: `config.yaml:2520` is `75.0`, `prospector/config.py:270`
carries a code default of `15.0`, and `prospector/ops/spend.py:55` names the key. **The live value is
the config file's.** Finding that disagreement *before* editing is the whole job.

### 5.2 Branch, in a worktree

```bash
git worktree add --detach ../wt-warn origin/main
./scripts/setup_worktree.sh ../wt-warn
cd ../wt-warn
git switch -c fix/warn-threshold
```

### 5.3 Make the smallest change that works

Edit the config line. Then edit the comment above it to say *why*, with your measurement. In this
repo a config change without a reasoned comment will be sent back.

### 5.4 Find the test that pins it, or write one

```bash
ls tests/ops/test_spend.py tests/scheduler/test_spend_by_day.py
.venv/bin/python -m pytest -q tests/ops/test_spend.py tests/scheduler/test_spend_by_day.py
```

Test names here are sentences describing the defect, not the function. Real examples from
`tests/unit/`: `test_a_failed_call_is_not_an_empty_answer.py`,
`test_a_swallowed_bug_is_not_a_missing_measurement.py`,
`test_an_unreadable_file_is_not_an_empty_one.py`,
`test_minimax_429_is_backpressure_not_a_verdict.py`. Follow that convention. The name should state
the wrong belief the test kills.

### 5.5 Run the gate before you commit

```bash
.venv/bin/python scripts/popdd_verify.py --staged
```

Do this *before* `git commit`, not instead of it. The gate runs inside the hook, which holds
`.git/index.lock` for the whole run — bounded at roughly 7.5 minutes now, but it was 49 minutes once
and blocked three sessions on 2026-08-14 (recorded in `CLAUDE.md`).

### 5.6 Commit

```bash
git add config.yaml tests/ops/test_spend.py     # never `git add -A`
git commit
```

Commit subject style, from `CLAUDE.md` and visible in real history
(`git log -1 --format='%s'` today: `fix(deploy): roll the ops console forward with the code, and
report its build age (#286)`): say what changed and where. No aphorisms, no dramatic reveals.

### 5.7 Push and open the PR

```bash
git push -u origin fix/warn-threshold
gh pr create --fill
```

CI runs on four self-hosted runners **on the founder's laptop** (launchd jobs
`actions.runner.chidionyema-prospector.mumchimp-mac{,-2,-3,-4}`, all four confirmed running today).
If the laptop is asleep, your PR does not get checked. That is not a bug you can fix from your seat;
it is a fact to plan around.

Workflows that will run: `.github/workflows/ci.yml`, and `deploy-api.yml` / `deploy-web.yml` /
`e2e-live-smoke.yml` depending on what you touched.

### 5.8 Read the green before you believe it

Two ways a green run lies, both recorded in `CLAUDE.md`:

- `npm run build 2>&1 | tail` reports **tail's** exit status. Capture the build's own status before
  any pipe.
- pytest exits **zero** when it collects nothing. Check the collected count, not just the exit code.

### 5.9 Merge

Squash-merge to `main`. Then, if the change affects what production runs, production has to be
rolled forward separately — see §6.4.

---

## 6. The five rules that will trip you up

Each of these exists because of a specific incident. Knowing the incident is what makes the rule
stick.

### 6.1 A claim without a receipt is not a claim

**The rule:** every factual statement — in a PR, a comment, a doc, a chat reply — carries a
`file:line`, a command with its real output, or a named artefact. If you cannot prove it, write
`HYPOTHESIS:` and the exact check that would settle it.

**The incident:** `CLAUDE.md` opens with it — "a design that was asserted, not proven, caused real
damage", and trust was withdrawn estate-wide on 2026-06-22. The same file later warns that one of
its *own* paragraphs "has now been wrong in both directions", which is why it now carries commands
instead of prose for the things that change.

**What it means in practice:** comparisons are claims too. "faster", "more reliable", "strictly
better" are banned as bare words. Name the concrete scenario where A breaks and B does not, with a
test that distinguishes them.

### 6.2 State is a probe, never a sentence

**The rule:** the live answer to "is it done / deployed / working?" is a command. Do not write it in
a doc and do not remember it.

**The incident:** a roadmap said a feature was live while the process ran 32-hour-old code. More
recently, `store/scheduler/alert_state.json` carries an alert from 2026-08-16T13:21:51Z whose message
is exactly this failure: *"com.prospector.scheduler was not loaded, so KeepAlive could not relaunch
the daemon and every 'launchd will restart it' line in the log was false."*

**What it means in practice:** before you claim anything is running, run `fly status -a
prospector-engine` and read the heartbeat on the volume, then quote the line. And make sure the
probe you are quoting still points at the thing that is live — see §2, where a probe left over from
the retired laptop deployment reports a total outage every time anyone runs it.

### 6.3 A failed call is not evidence — it defers

**The rule:** when a verdict call raises — quota, bad JSON, a crashed adapter — the candidate is
**deferred**, not killed. `prospector/verify.py:365` sets `retrieval_failed=True`, which fires the
DEFER gate at `prospector/verify.py:693`.

**The incident:** before 2026-08-06 it did not. `store/dossiers/2102bacc6dd75cf9.kill.json` is a real
KILL on `min_composite` whose seven checks all read `unverifiable, conf 0.0, "Verdict call failed;
fail-safe."` — a business idea killed by our own outage, in a dossier that reads as fully reasoned.

**What it means in practice:** never let an exception become a finding. The honest verdict on an
unevaluated check is "come back to it".

### 6.4 Production does not run from the checkout you are editing

**The rule:** editing a branch here cannot change what production executes. A fix reaches production
by merging to `main` and deploying. **Production is the Fly app `prospector-engine`** (machine
`80d34da6636478`, region `lhr`, deployed from an image, with its own 20 GB volume for `store/`).

**This rule has now had three homes in three days, which is itself the lesson.** Until 2026-08-16
the daemons ran from this shared developer checkout, on whatever branch a session had left it on. On
2026-08-17 that was `integrate/minimax-into-main`, 75 commits behind `origin/main`, so the daemon
executed 17-hour-old code — and the only way to see that was to run `lsof` on the pid by hand. The
fix on 2026-08-17 was a second checkout, `/Users/chidionyema/Documents/code/prospector-live`, pinned
detached at `origin/main`. **On 2026-08-18 that was superseded again: the engine moved to Fly, and
both the `prospector-live` checkout and the laptop launchd jobs were decommissioned.**

`CLAUDE.md` still describes the 2026-08-17 arrangement. It is out of date, and correcting it is an
open task. **Believe the Fly command, not the paragraph.**

**A second trap inside the same rule:** a store path derived from `__file__` follows the **code**,
not the store. Four constants did that, so provider health marks, the retrieval cache and the audit
trail were written beside the new code while the ledger went to the canonical store.
`config.store_root()` is the one resolver now. **Never write
`Path(__file__).parent.parent / "store"`.**

**Where it stands today:** the Fly cutover made this rule sharper, not softer. Production now runs
a built image, so there is no branch on a box to drift at all — but there is also no way to hotfix
it in place. Everything goes through `main`.

### 6.5 Only the declared brains may rule finally

**The rule:** `config.yaml moat_primary:` names the only providers allowed to rule a verdict
finally. Anything outside that set that rules gets stamped `provisional`, never publishes on PASS,
and is automatically re-vetted. The fence is `prospector/operator.py:1509`
`is_provisional_provider`, reading `moat_primary()` at `prospector/operator.py:1443`, defaulting to
`MOAT_PRIMARY_DEFAULT` at `prospector/operator.py:1405`.

**Evidence that it works:** of 2,995 dossier rows measured today, exactly **1** is marked
`provisional`.

**What it means in practice:** the roster is config, not code. A test that hardcodes "minimax =
untrusted" is pinning the roster, not the fence, and will be wrong the next time the roster moves.

---

## 7. Vocabulary

Every internal term, with the code that implements it.

**Signal** — a market input the engine generates ideas from. Saved under `signals/`; failed ones
land in `signals/pending/` for `generate --resume`. Surfaced by `prospector/discover.py`.

**Candidate** — one generated business idea, before any judgement.
`prospector/models.py:170` `class Candidate`. Carries `ambition_tier` (`models.py:185`) and a
`market` that is hierarchical, e.g. `us` or `us-tx` (`models.py:187`).

**Verdict** — the outcome of one grounded check. `prospector/models.py:25` `class Verdict(str, Enum)`.
Three states matter: supported, unverifiable, and the DEFER path.

**Dossier** — the artefact holding a candidate plus every verdict, source and cost.
`prospector/models.py:452` `class Dossier`, composed by `prospector/dossier.py` (1,075 lines),
written to `store/dossiers/<id>.kill.json` or `<id>.pass.json`, and indexed in the `dossiers` table
of `store/prospector.db` (2,995 rows today).

**Pack** — the thing a buyer actually receives: the rendered research document. Built by
`prospector/artifacts.py` and the eight `prospector/pack_*.py` renderers (`pack_html.py`,
`pack_pdf.py`, `pack_card.py`, `pack_table.py`, `pack_bear_case.py`, `pack_checklist.py`,
`pack_offer.py`, `pack_reference.py`, plus `pack_linter.py` which grades it). The renderers are
deliberately model-free.

**Listing** — the publish record for a pack. One JSON file per pack in `store/listings/` (119 files
today), each carrying `candidate_id`, `title`, `market`, `verified_at`, `published_via`, `catalog`.
Retired ones move to `store/listings_archive/` (20 files).

**Bundle** — the packaged, content-addressed set of pack files delivered to a buyer. Handled in
`prospector/pack_manifest.py` and `tools/backfill_bundle_html.py`; delivery keys are
content-addressed, which is why the ops risk register grades `ACCEPTED AST-4 Delivery keys are
content-addressed`.

**Moat** — the verification stage: the six checks plus the price check, end to end, on a trusted
brain, with kill-fast short-circuiting. `prospector/verify.py` (1,258 lines). It raises
`ProviderExhaustedError` when it is down, so callers defer rather than guess.

**Moat-primary** — the set of providers allowed to rule finally.
`prospector/operator.py:1443` `moat_primary()`, declared by `config.yaml moat_primary:`.

**Lane** (ambition lane) — the ambition tier an idea is generated into. Measured across all 2,995
dossiers today: `smb` 599, `side_hustle` 440, `growth` 438, `venture` 334, and 1,184 rows with no
tier recorded. The lane weights are in `config.yaml` around `:604`; the config comment there is
explicit that to hold `venture` down you change the **weight**, not `batch_size`.

The word "lane" is overloaded — it also means a commit-gate lane
(`scripts/popdd_verify.py:234` `LANES`, mapping staged file types to python/dotnet/web test runs).
Context tells you which.

**Rung** — a price. Price is never a computed number; it is an index into a fixed array.
`config.yaml:1829` `rungs: [1999, 2999, 4999, 7999, 9999]` (pence). Default rung at
`config.yaml:1505` `price_pence: 4999`. Logic in `prospector/pricing.py`; the anchor adjustment that
can move it at most one rung is `prospector/pricing.py:72` `_anchor_adjustment`, and it is off by
default.

**Gate** — a deterministic kill check. `prospector/kill_filter.py:20` `is_hard_fail`,
`prospector/kill_filter.py:54` `apply_gates`. The gates that actually fired, counted today across
2,842 kills: `moat_ungrounded` 1,042, `min_composite` 753, `incumbency` 271, `source_or_die` 256,
`value_durability` 202, `adversarial_decisive` 154, `payer_solvency` 60, `legality` 30,
`distribution` 22, `currency` 14, `route_to_market` 13, `pain_reality` 9, `buyer_intent` 7.

**Drain** — re-vetting deferred and provisional rows once the moat recovers. The definition of what
counts as drainable is one function, `prospector/run.py:2551` `drainable()`; the command is
`prospector/run.py:2579` `_cmd_resume`; the always-on process is `prospector/consumer.py`. The drain
is trusted-only on purpose: re-vetting a provisional row on a provisional brain just re-stamps it
provisional and spends the money for nothing.

**Tick** — one cycle of the unattended daemon.
`prospector/scheduler/run_scheduled.py:1666` `run_tick`. Generation volume per tick is
`config.yaml:2353` `batch_size: 50`.

**Provisional** — a verdict ruled by a brain outside `moat_primary()`. It never publishes on PASS
and is automatically re-vetted. `prospector/operator.py:1509` `is_provisional_provider`. One row of
2,995 carries it today.

**Defer** — the honest non-answer. A check that could not be evaluated (exception, quota, bad JSON)
returns `retrieval_failed=True` (`prospector/verify.py:365`) and fires the DEFER gate
(`prospector/verify.py:693`). 45 rows are in `defer` today.

**PAUSE / PAUSE_GENERATION / PAUSE_CONSUMER** — filesystem kill switches under `store/scheduler/`.
`PAUSE` halts the whole tick (`prospector/scheduler/guard.py:66`). The two half-stops leave the drain
running: `PAUSE_GENERATION` (checked at `prospector/scheduler/run_scheduled.py:233`) and
`PAUSE_CONSUMER` (`prospector/consumer.py:78`).

**Stranded pass** — a PASS that finished but never reached the shelf. **44 on production** at
2026-08-18T12:11Z (`/data/store/scheduler/ALERT.txt` on the Fly volume, key `stranded_passes` in
`alert_state.json`), up from 34 twelve hours earlier. Reported by
`.venv/bin/python -m ops.automations.stranded_packs --json`.

**POPDD gate** — the pre-commit verification run. `scripts/popdd_verify.py`, timeout
`scripts/popdd_verify.py:86`, lanes at `:234`.

---

## 8. Who to ask about what

Each of these is a document in this directory, written as a total audit from that seat.

| Question | Ask |
|---|---|
| What is the business, what does it cost, what is at risk | [founder.md](founder.md) |
| Where is the money, what was spent, what was earned | [finance.md](finance.md) |
| It is 3am and something is down | [sre-on-call.md](sre-on-call.md) |
| How do I run the daily operating surface | [ops.md](ops.md) |
| Why is the system shaped this way | [architect.md](architect.md) |
| How do I hold a large change together | [principal-developer.md](principal-developer.md) |
| How do I make a non-trivial change safely | [senior-developer.md](senior-developer.md) |
| How do I make a change at all | [developer.md](developer.md) |
| What is tested, what is not, what lies | [qa-test-engineer.md](qa-test-engineer.md) |
| Where does the data live and how does it move | [data-engineer.md](data-engineer.md) |
| Which model rules what, and why | [machine-learning-engineer.md](machine-learning-engineer.md) |
| What are the numbers actually saying | [analyst.md](analyst.md) |
| What are we building next and why | [product-manager.md](product-manager.md) |
| What does the pack say and who wrote it | [content-management.md](content-management.md) |
| How does anyone find the shop | [growth-marketing.md](growth-marketing.md) |
| What does the buyer see and feel | [buyer.md](buyer.md) |
| A customer has a problem | [support.md](support.md) |
| Are we legal, are we compliant | [legal-privacy.md](legal-privacy.md) |
| Where are the secrets and who can reach them | [security.md](security.md) |
| The shared facts, in one place | [../ESTATE_MAP.md](../ESTATE_MAP.md) |
| What gets logged and for how long | [../LOGGING_AND_RETENTION.md](../LOGGING_AND_RETENTION.md) |
| The whole index and a routing table | [README.md](README.md) |

---

## 9. Day one checklist

- [ ] `.venv/bin/python scripts/ops_status.py` — read all 40 lines, note the `MANUAL` count.
- [ ] `fly status -a prospector-engine` then
      `fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"` — is the
      engine running today? (Do **not** use `scripts/live_checkout.py`; see §2.)
- [ ] `sqlite3 store/prospector.db "select decision, count(*) from dossiers group by decision;"` —
      see the real shape of the asset.
- [ ] `curl -s https://api.mumchimp.com/catalog | head -c 400` — see what a buyer sees.
- [ ] Read `RUN.md` (132 lines). It is the procedure the whole engine implements.
- [ ] Read `CLAUDE.md` at the repo root. It is the rulebook, and it is enforced.
- [ ] Skim `config.yaml` — not to memorise it, but to see that the comments carry the reasoning.
- [ ] `.venv/bin/python -m pytest -q tests/unit -x` — prove your environment works.
- [ ] Make a worktree with `./scripts/setup_worktree.sh` and run the gate once with nothing staged,
      so the first time you see it is not inside a real commit.

---

*Every figure and path in this document was measured on 2026-08-18 from
`/Users/chidionyema/Documents/code/prospector` at HEAD `c3cb68b`. The system changes daily. When a
number here disagrees with a command, the command is right — fix this document.*
