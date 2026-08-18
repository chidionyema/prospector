# Engine Migration Programme — get the business off this laptop

Status: **AUDIT COMPLETE, PLAN DRAFTED, NOT STARTED.**
Branch: `audit/fly-migration`. Measured 2026-08-17 22:30–23:40 UTC.
Extends `docs/LAUNCH_OPS_PROGRAM.md` §1 KEY-1, §3 migration playbooks, §4 P4. Read that first.

Every number below has a receipt in the line that carries it. Anything I could not prove is
marked **HYPOTHESIS** with the exact command that settles it. Nothing here is asserted from memory.

---

## 0. The three corrections to the brief

The brief said "migrate the engine, storefront, listings, ops dashboard and possibly Hermes".
Three of those premises are wrong, and getting them right shrinks the job.

**1. The storefront is already on Fly.** `fly apps list` (2026-08-17 22:31Z):

| App | Machines | Region | Volume | Deployed |
|---|---|---|---|---|
| `prospector-store-api` | 1 × shared-cpu-1x, 512 MB | lhr | `store_data` 1 GB, encrypted | 3h48m ago |
| `prospector-store-web` | 2 × shared-cpu-1x, 512 MB | lhr | none (stateless) | 3h21m ago |

Receipts: `fly status -a prospector-store-api`, `fly scale show`, `fly volumes list`.
24 secrets already set on the API (`fly secrets list`): R2, Stripe, Mailjet, JWT, Google OAuth.
Deploy is already automated: `.github/workflows/deploy-api.yml` and `deploy-web.yml` via
`superfly/flyctl-actions`, config in `store_platform/deploy/fly/api.fly.toml`.

**Nothing buyer-facing needs to move.** `mumchimp.com` does not touch the laptop. DNS, TLS,
Stripe, R2 delivery and the catalogue API are all off-box already. That drops the buyer-facing
risk of this migration close to zero — *provided* the ops console stays private (§4, EDGE-9).

**2. What is actually on the laptop** — `launchctl list`, 2026-08-17 22:31Z:

| Group | Jobs | In scope? |
|---|---|---|
| Engine | `com.prospector.scheduler` (pid 67664), `.consumer` (67733) | **YES — the whole point** |
| Ops surfaces | `.ops-console` (67737, Next.js), `.control-center` (43798, Streamlit) | **YES — they read the same store** |
| Engine rails | `.watchdog` (15 min), `.backup`, `.offsite-backup`, `.live-update` (60 s) | **YES — each needs a Fly-native replacement or a decision to drop** |
| CI | 4 × `actions.runner.chidionyema-prospector.mumchimp-mac{,-2,-3,-4}` | **YES, and FIRST — see §5 P0** |
| Hermes | 10 × `ai.hermes.*` (coordinator, gateway, otto-server, rsi, watchdog, …) | **NO — recommend out of scope, §3** |

All four prospector daemons run from `/Users/chidionyema/Documents/code/prospector-live` with
`PROSPECTOR_STORE_DIR` pinned back to `…/prospector/store` (read from the installed plists via
`plutil`). Ops console binds `-H 100.93.240.113` — a Tailscale address, not public.

**3. The blocker is not infrastructure. It is the brain.** See §1. Solve that first or the rest
is wasted work.

---

## 1. BLOCKER — the engine's lead brain is a subscription binary that lives on this Mac

`prospector/claude_cli.py:367` runs the LLM call as a subprocess:

```
subprocess.run([CLAUDE_BIN, "-p", prompt, "--output-format", "json"], …)
```

`CLAUDE_BIN` defaults to `"claude"` (`claude_cli.py:35`). Two comments in that file state the
constraint plainly: `:191` — *"The headless `claude -p` CLI must authenticate via the Claude Code
SUBSCRIPTION (OAuth), not a metered API key"*; `:44` — *"auth lives in `~/.claude`"*.

Where `claude_cli` sits in the roster today (`config.yaml`):

| Line | Key | Value | What breaks without it |
|---|---|---|---|
| 58 | `operator` | `[minimax, claude_cli]` | Moat loses its only fallback brain |
| 81 | `moat_primary` | `[minimax, claude_cli]` | Trusted-final set becomes single-brain |
| 136 | `noncritical_operator` | `[minimax, minimax_m27]` | unaffected |
| **145** | **`artifact_operator`** | **`[claude_cli, minimax]`** | **Pack prose — what buyers read — loses its LEAD** |
| 157 | `marketing_operator` | `[minimax, claude_cli]` | Marketing copy loses its fallback |

The state probe reports **$78.16/day of Claude CLI usage, UNCAPPED** — that is subscription value,
not billed spend. Move to Fly and that becomes either zero or a metered bill.

**There is no fourth option. Pick one:**

| Option | Cost | Risk | Status |
|---|---|---|---|
| **A. `CLAUDE_CODE_OAUTH_TOKEN` in the container** | £0 if it draws on the plan | ToS: running a personal subscription on a server is a founder call, not mine | **HYPOTHESIS** — see proof below |
| **B. Metered `ANTHROPIC_API_KEY`** | Replaces ~$78/day of subscription value with a real bill | None technically; it is a pure cost decision | `.env` already holds a 110-char `ANTHROPIC_API_KEY`. **Unproven whether it is live or funded** |
| **C. Drop `claude_cli`, run MiniMax-only** | £0 | Moat becomes single-brain — one MiniMax outage stops all verdicts. Pack prose loses its lead author. Contradicts the "a dead brain must leave a trace" failover design | Config-only change; `moat_primary()` is already config-declared |

**Proof for A, ~20 minutes, do this before anything else:**
```bash
claude setup-token                                  # mints a long-lived token
docker run --rm -e CLAUDE_CODE_OAUTH_TOKEN=… node:22 \
  sh -c 'npm i -g @anthropic-ai/claude-code && claude -p "say PONG" --output-format json'
# then check claude.ai/settings/usage: did it draw on the PLAN or on extra usage?
```
Related trap already recorded: reading the Keychain OAuth cred and sending it as a raw Bearer to
`api.anthropic.com` returns *"Third-party apps now draw from your extra usage, not your plan
limits"* (HTTP 400). That is a **different** mechanism from `CLAUDE_CODE_OAUTH_TOKEN` driving the
binary — do not assume the result carries over, in either direction. Measure it.

**Proof for B, 2 minutes:** a `/models` probe proves the key is valid, *not* that it has balance.
Send one real 10-token completion and read the billing response.

**This is a founder decision and it gates every other phase.** I will not pick it.

---

## 2. Rule conflict — RESOLVED 2026-08-18, the rule is dead

`CLAUDE.md` used to forbid this outright: *"the engine runs locally or within your Claude Code
subscription. No hosted inference, no infrastructure beyond your own server."*

Founder, 2026-08-18: **"forget about CLAUDE.md, that was in the past, this is a commercial business
running off a laptop."** The rule was written for a side project; the laptop is now the risk, not
the hosted infrastructure. `CLAUDE.md:43` has been rewritten on this branch to say so, with the
date and the reason, so no future session re-raises it as a blocker.

**All three brain options in §1 are therefore open on their merits** — cost and reliability only,
no rule argument. What survives from the old rule, because it was the load-bearing half: the repo
stays the complete system. No behaviour may live only in a console, a dashboard or a provider
account, and a fresh clone plus an env file must still run the whole engine. That is exactly what
P7's second adapter proves.

## 3. Hermes — recommend OUT OF SCOPE, explicitly

`~/.hermes` is a separate estate with its own 10 launchd jobs. Its whole purpose is to drive
Claude Code as an agent; it is coupled to the interactive subscription *harder* than the engine is.
Migrating it means migrating the thing that most needs a human-authenticated session on a
human's machine.

One coupling leaks into the engine and must be fixed regardless (**EDGE-15**):
`prospector/usage_wall.py:54` defaults its marker to `~/.hermes/state/claude_usage_limit.json`.
In a container that path does not exist, so the usage wall silently never engages and the engine
hammers a spent subscription with no brake. That is a one-line fix with a fail-safe default, and
it belongs in P1 whether or not Hermes ever moves.

---

## 4. Edge cases and order effects — the part that bites

Ranked by what they cost if missed.

| # | Edge case | Why it bites | Mitigation |
|---|---|---|---|
| **EDGE-1** | **Two engines running at once forks the ledger.** The daily spend cap reads `store/prospector.jsonl`. Fork it and each side sees half the spend — you can spend **2× the $100 cap** and neither rail notices. | Money | Cutover is **stop → copy → start**, never blue/green. `store/scheduler/PAUSE` is the existing primitive and halts the whole tick. |
| **EDGE-2** | **Two engines double-publish to one Store.Api.** `bridge.py` mints the Stripe Price *and* the catalogue row in one `PriceDecision`. Two writers = duplicate listings against live Stripe. | Money, buyer-facing | Same as EDGE-1. Never both. This is why there is no shadow-write phase. |
| **EDGE-3** | **The 255 MB ledger is container-hostile.** `store/prospector.jsonl` is 255 MB (`ls -l`), cold read measured 108 s (DAT-3, open). A health check that touches it will fail a fresh machine. | Cutover fails on first boot | **Rotate the ledger BEFORE the move**, not after. DAT-3 is already an open item; this promotes it to a dependency. |
| **EDGE-4** | **Store paths derived from `__file__` follow the CODE, not the store.** This has already happened once here: four constants split provider-health marks and the retrieval cache away from the canonical ledger for twenty minutes. A container changes the code path again. | Silent split-brain; a benched provider never observed recovering | Gate the deploy on a grep: no `Path(__file__)…/"store"` anywhere. `config.store_root()` is the one resolver. |
| **EDGE-5** | **`fcntl.flock` (`claim_lock.py:27`) works on a Fly volume but never across machines.** | Corruption if ever scaled | Pin the engine app to **exactly 1 machine**, same constraint the API already documents in `api.fly.toml:52`. Write it in the toml comment. |
| **EDGE-6** | **Deploy = SIGTERM mid-tick.** A SIGKILLed vet has already destroyed candidates here: no dossier, no index row, 10 of 12 gone. `store/inflight/` + `_recover_orphans` exists to catch it. | Silent work loss on every deploy | Prove `_recover_orphans` survives a **container** restart (volume persists, PID namespace does not) before first cutover. |
| **EDGE-7** | **Two watchdogs fight.** `com.prospector.watchdog` SIGKILLs a wedged daemon every 15 min. Fly has its own health-check restart policy. | Restart loop | Pick one. Recommend Fly's, and drop the launchd watchdog on the Fly side only. |
| **EDGE-8** | **`live_checkout.py --update` becomes a lie.** The self-deploy rail is `git pull + launchctl restart`; on Fly it is `fly deploy`. The console button that says "roll production forward" would silently do nothing. | Operator acts on a false control | Rewire the action, or delete the button. A control that does nothing is worse than a missing one. |
| **EDGE-9** | **The ops console goes from Tailscale-only to public.** It binds `100.93.240.113` today. Its `ACTIONS` table includes `daemon.restart`, `config.set`, `shelf.publish_pending`, `routing.set_moat_primary`. Auth is one shared `CONTROL_CENTER_PASSWORD`. | Internet-facing admin panel over the money rail | **BLOCKER for the console phase.** Either Fly private networking + Tailscale on the machine, or do the auth work first. Not a public app with a password. |
| **EDGE-10** | **The offsite backup must run from exactly one side.** It writes dated keys to R2 and is the failback path. Both sides running interleaves two divergent stores into one prefix. | Backup becomes unrestorable | Move the job with the engine; disable on the laptop at cutover. |
| **EDGE-11** | **Outbound IP changes.** Any provider allowlist keyed to the home IP (MiniMax, Exa, Stripe restricted keys) breaks the moment the engine is elsewhere. | Total engine outage on cutover, looks like an auth bug | Check each provider's IP restrictions before cutover. 10 minutes. |
| **EDGE-12** | **CI runs on the machine you are insuring against.** 4 self-hosted runners on this Mac. If the laptop is the disaster, you cannot deploy the fix. | Cannot recover | **Do this first.** `runs-on: ${{ vars.CI_RUNS_ON \|\| 'ubuntu-latest' }}` — unsetting one repo variable moves all 12 workflows to GitHub-hosted. One line. |
| **EDGE-13** | **The Fly volume repeats DAT-1.** A volume is one copy in one zone; `store_data` snapshots default to 5-day retention. The engine store is 691 MB / 36,692 files. | Same single-copy risk you already have on the money DB | Keep the R2 offsite backup as the real durability layer. The volume is not a backup. |
| **EDGE-14** | **The restore has never been proven, in either direction.** `scripts/restore_drill.py` exists and prints PASS/FAIL; DAT-2 records no dated receipt of a run. | A backup nobody restored is a hypothesis | **Prove restore BOTH ways before cutover**: laptop → Fly volume, and Fly volume → laptop. This is the gate, not a nice-to-have. |
| **EDGE-15** | **`usage_wall` marker points at `~/.hermes`.** See §3. | Engine hammers a spent subscription with no brake | Env var with a fail-safe default. |
| **EDGE-16** | **`store/.cli_slots/` lock directory.** If `claude_cli` survives (Option A/B), its concurrency slots must live on the **volume**, not an image layer, or the governor resets every deploy. | Concurrency cap silently lifts | Confirm it resolves under `store_root()`. |
| **EDGE-17** | **MiniMax being primary already covers the verdict path — but not pack prose.** Measured on disk: `config.yaml:58` `operator: [minimax, claude_cli]` and `:81` `moat_primary: [minimax, claude_cli]`, so MiniMax both leads and rules finally; losing `claude_cli` costs the moat its fallback, not the line. `:136` `noncritical_operator` never had it. **The one exception is `:145` `artifact_operator: [claude_cli, minimax]` — claude_cli LEADS**, and that is the pack prose buyers read. So an account event under Option A degrades one thing that ships to customers, and it does it at the same moment as every Claude Code session on this laptop, because it is the same subscription. | Pack prose silently drops to the fallback author; no verdict impact | **One line, decided before cutover, not during an outage:** either flip `:145` to `[minimax, claude_cli]` and accept MiniMax prose as the norm, or leave claude_cli leading and accept that pack quality is what an account event costs. Do not leave it undecided — the failover is automatic and silent either way. Verdicts need no change. |

---

## 5. Delivery plan — phases, user stories, estimates

Estimates are engineer-days for one focused operator, and assume the §1 decision is already made.
Phases are ordered so that **every phase leaves the business no worse off than it started**.

### P0 — Get the laptop out of the recovery path (0.5 d) — *start today, no decision needed*

> **As the founder**, I want CI and deploys to survive the laptop dying, so that I can ship the fix
> for the outage that killed it.

1. Set repo variable `CI_RUNS_ON` to `ubuntu-latest` (or unset it — that is already the fallback in
   all 12 workflows). Disable the 4 self-hosted runners.
2. Prove one API deploy end-to-end from GitHub-hosted CI.
3. Push a `--mirror` of the repo to a second remote (SRC-4, already open, HIGH).

**Done when:** `deploy-api.yml` goes green on a hosted runner and `git ls-remote` on the mirror
matches `origin/main`.

### P1 — Make the engine runnable on Linux from a fresh clone (2 d) — *needs the §1 decision*

> **As the founder**, I want the engine to start on any Linux box from a clone and an env file, so
> that the host is a choice rather than a fact.

1. Kill the absolute paths: `scripts/live_checkout.py:29-30`, `tools/experiments/e11_confidence_floor.py:22`,
   `tools/l8_ab.sh:25`. Root comes from an env var.
2. `usage_wall.py:54` — marker path from env, fail-safe default (EDGE-15).
3. Guard against EDGE-4: a test that fails on any `Path(__file__)`-derived store path.
4. `Dockerfile.engine` — Python 3.14, the venv, `config.yaml`, entrypoint that selects
   `scheduler` / `consumer` / `watchdog` by argument.
5. Implement the §1 decision in `config.yaml` and, for Option A/B, in the image.
6. macOS-only code (`launchd_plists.py`, `plutil`, `osascript` alerts) degrades to a no-op off
   macOS rather than erroring.

**Done when:** `docker run` produces one complete tick against a scratch store, on this machine,
with the daemons still running untouched.

### P2 — State: rotate, move, and prove the restore both ways (1.5 d)

> **As the founder**, I want to move 691 MB of engine state and be able to move it back, so that
> cutover is reversible.

1. Rotate `store/prospector.jsonl` (EDGE-3, DAT-3). Ledger readers must still see history.
2. `scripts/store_migrate.py` — copy `store/` to/from a target, verify by count and by
   `PRAGMA integrity_check` on the 4 sqlite dbs, print `STORE_MIGRATE PASS/FAIL`.
3. **Run `restore_drill.py` for real and commit the dated receipt** (closes DAT-2).
4. Run the drill in the reverse direction: Fly volume → laptop.

**Done when:** two dated receipts on disk, both PASS, one per direction.

### P3 — Engine on Fly, shadowed, laptop still authoritative (1 d)

> **As the founder**, I want to watch the Fly engine do a full tick before it owns anything.

1. `deploy/engine/fly.toml` — 1 machine, `min_machines_running = 1`, `auto_stop_machines = false`,
   volume `engine_data` → `/data`, `PROSPECTOR_STORE_DIR=/data/store`. **HYPOTHESIS on size:**
   measured RSS today is scheduler 19 MB + consumer 32 MB + console 31 MB + control-center 10 MB
   ≈ 92 MB at rest, so `shared-cpu-4x` (4 cores / 1 GB) should fit and `performance-1x` (1 core /
   2 GB) is the safe fallback. Confirm under a real tick with `fly machine status`, not from this line.
2. `fly secrets set` for every key in `.env` (SRC-5 — this also gets the secrets off one laptop).
3. Boot it with `store/scheduler/PAUSE` **armed** and `PAUSE_GENERATION` set. It drains nothing,
   publishes nothing, writes nothing to the live catalogue.
4. Run one tick against a **copy** of the store, on a throwaway volume, and diff the dossiers it
   produces against the laptop's for the same signal.

**Done when:** a Fly tick produces a dossier that matches the laptop's shape, with zero writes to
the live store and zero calls to `bridge.py`.

### P4 — Cutover (0.5 d) — *stop, copy, start; a 30-minute window*

> **As the founder**, I want a cutover I can abort at any point and be back where I started.

1. Check provider IP allowlists (EDGE-11).
2. `touch store/scheduler/PAUSE` on the laptop; wait for both daemons to reach `sleeping`.
3. `launchctl bootout` the 4 engine jobs — **do not delete the plists** (they are the failback).
4. `store_migrate.py` laptop → Fly volume; verify.
5. Remove `PAUSE` on Fly. Watch one full tick.
6. **Abort criterion, decided in advance:** if the first Fly tick does not produce a dossier within
   one interval, re-arm PAUSE on Fly, `launchctl bootstrap` the laptop jobs, and stop. The store
   has not moved, only been copied.

**Done when:** the state probe reads a Fly daemon pid, a fresh beat, and a non-zero last batch.

### P5 — Ops console and control-center follow the engine (2 d)

> **As the founder**, I want to operate the engine from the console after it moves, without
> exposing an admin panel to the internet.

The console cannot be split from the engine: `Ops.Console/src/lib/ops.ts:41-50` requires
`PROSPECTOR_PYTHON` and spawns `python -m prospector.ops.console_api` with `cwd: repoRoot()`.
That design rule is **correct and must be kept** — no TypeScript computes an engine number — so
the console moves *onto the engine machine* as a second process, not into its own app.

1. Second process in `engine.fly.toml` (`[processes]`), same image, same `/data` volume.
2. **EDGE-9 is a blocker here:** private networking + Tailscale on the Fly machine, or real auth
   before it is reachable. Not a public URL with one shared password.
3. Rewire or delete the `live_checkout --update` action (EDGE-8).
4. Control-center (Streamlit, port 8601) — same treatment, or retire it if the console supersedes it.

**Unlock worth naming:** `ADMIN_CONSOLE_PROGRAM.md §1` says putting the console on `mumchimp.com`
is a different programme *because the engine's state lives on the Mac*. This phase removes that
objection.

**Done when:** every console action works against the Fly engine, and the console is not reachable
from the public internet.

### P6 — The laptop becomes a cold, proven standby (1 d)

> **As the founder**, I want the laptop off to save resources but able to serve production again
> within an hour.

1. Plists stay installed, jobs stay `bootout`. Document the two commands that revive them.
2. The R2 offsite backup runs from Fly only (EDGE-10); the laptop's copy is disabled, not deleted.
3. **Failback drill, dated receipt:** pull the newest R2 copy to the laptop, `bootstrap` the jobs,
   confirm one tick, then reverse. This is the only thing that makes "failover" a fact rather than
   a plan.
4. Turn off the Hermes jobs that exist only to feed the engine — **decide this deliberately**, it
   is a separate estate (§3).

**Done when:** a dated failback receipt exists and the laptop is idle.

### P7 — Prove the migration is repeatable (1 d)

> **As the founder**, I want moving off Fly to be a config change, not a project.

A portability claim with one implementation is untested. So:

1. `deploy/` gets a thin contract: one Dockerfile, one env manifest, one volume spec, one restore
   script — and a **per-provider adapter** holding only the four provider-specific verbs:
   *create volume · set secrets · deploy · schedule*.
2. `deploy/fly/` is adapter one. **Write `deploy/compose/` as adapter two** (plain VPS, docker
   compose + systemd timer) and boot the engine under it locally. It never has to be deployed —
   writing it is what proves the seam is real.
3. Apply the same discipline to the storefront: §3 of the ops programme already names 9 hardcoded
   `fly.dev` and 6 hardcoded `mumchimp.com` references as the tax. Move them to config in this phase.

**Done when:** the engine boots under `deploy/compose/` with no source edits, and the only diff
between adapters is the four verbs.

---

## 6. Estimate

**Revised 2026-08-17 23:5x on founder instruction: "9.5 days makes no sense, we need to get it
done tonight."** He is right that the number answered the wrong question. 9.5 days was the FULL
programme — engine, console, control-center, a second provider adapter and two proven failback
drills. **Getting the ENGINE off this laptop is a much smaller job**, and the phases below split
cleanly into what genuinely fits in one night and what does not.

### Tonight — the engine only (~4.5–5 hours)

| # | Step | Time | Notes |
|---|---|---|---|
| 1 | **Brain decision** (§1) | 5 min | **Option B or C only.** Option A needs a ToS call you should not make at midnight. |
| 2 | Unset `CI_RUNS_ON` | 5 min | All 12 workflows already fall back to `ubuntu-latest`. Removes the laptop from the deploy path. |
| 3 | `Dockerfile.engine` + kill the 4 absolute paths + `usage_wall` env var | 90 min | `live_checkout.py:29-30`, `e11_confidence_floor.py:22`, `l8_ab.sh:25`, `usage_wall.py:54`. macOS-only code no-ops off macOS. |
| 4 | `docker run` one tick against a scratch store, locally | 30 min | The gate on everything after it. If this fails, stop — nothing has changed yet. |
| 5 | Fly app + volume + `fly secrets set` from `.env` | 30 min | 1 machine, `min_machines_running = 1`, `auto_stop_machines = false`. |
| 6 | Copy `store/` (691 MB) to the volume, verify counts + `PRAGMA integrity_check` | 30 min | |
| 7 | Boot **PAUSEd**, run one shadow tick against a **copy** | 30 min | Zero writes to the live catalogue, zero `bridge.py` calls. |
| 8 | Cutover: PAUSE laptop → wait for `sleeping` → `launchctl bootout` → unpause Fly | 20 min | Plists stay installed. |
| 9 | Watch one real tick, then stop for the night | 30 min | |

**Hard abort, decided now:** if step 4 or step 7 fails, stop. Nothing has moved — the store was
copied, not migrated, and the laptop jobs are untouched. If step 9's tick produces no dossier
within one interval, re-arm PAUSE on Fly and `launchctl bootstrap` the laptop jobs. Rollback is
two commands and the store is still authoritative on the laptop until step 8.

**Two edge cases from §4 that can bite tonight and have no shortcut:**
- **EDGE-3** — `store/prospector.jsonl` is 255 MB with a 108 s cold read. If the container's first
  boot touches it under a health check, step 7 fails. Mitigation tonight: no health check on the
  ledger; rotation stays a daylight job.
- **EDGE-11** — outbound IP changes. Check MiniMax / Exa / Stripe for IP allowlists **before**
  step 8, not after. 10 minutes, and it looks like an auth bug if missed.

### Deferred to daylight — REVISED 23:58, nothing is deferred

Founder: *"all needs doing tonight, get creative and find a way."* He is right, and my two-day
console estimate was the wrong shape. It priced **building real auth**. The job does not need real
auth tonight, because the access model that already works can be carried over as-is.

| Was deferred | Creative unblock | Real time |
|---|---|---|
| **Console (EDGE-9 public admin panel), 2.0 d** | **Give the machine no public IP at all.** Omit `[http_service]` from `engine.fly.toml`. The console then has no internet surface whatsoever, and the founder reaches it with `fly proxy 3000:3000` — a WireGuard tunnel from his laptop to the machine. Same private-only posture as the Tailscale bind it has today (`-H 100.93.240.113`), zero auth code, zero exposure. Tailscale-in-the-image is the fallback if a stable address is wanted later. | **20 min** |
| **Restore proof (DAT-2 / EDGE-14), 1.0 d** | **The cutover IS the laptop→Fly drill** — copy, boot, verify a tick. For the reverse, `scripts/restore_drill.py` already exists and already prints `RESTORE_DRILL PASS/FAIL`; run it into a scratch dir and commit the dated receipt. The day was for building tooling that is already built. | **30 min, both directions** |
| **Ledger rotation (DAT-3 / EDGE-3), 0.5 d** | **Do not rotate tonight. Avoid the trigger.** The 255 MB / 108 s cold read only bites if something reads it on boot. Put no ledger read in the health check and measure the first cold read once inside the container. Rotation stays a real job, just not a blocking one. | **0 min** |
| **Second provider adapter, 1.0 d** | **The image is the portability.** Once `Dockerfile.engine` exists, `deploy/compose/docker-compose.yml` is ~20 lines against the same image plus a systemd timer. Boot it locally once and the seam is proven. | **20 min** |
| **Control-center (Streamlit), included above** | Second process on the same machine, same image, same `/data`. Reached the same way, `fly proxy 8601:8601`. | **15 min** |
| **Laptop as *proven* standby, 1.0 d** | The failback drill is the reverse restore above, plus `launchctl bootstrap` and one tick. | **20 min** |
| **Hermes** | Still out of scope (§3) — it is a separate estate whose whole job is driving an interactive Claude session. Not a time estimate; a scope line. | — |

### The night, in order — ~6 hours

Ordered so the abort point comes **before** anything irreversible, and every step is a command
with a verdict line.

| # | Step | Time | Verdict line |
|---|---|---|---|
| 1 | **Brain decision** (§1) — B or C | 5 m | `config.yaml` diff |
| 2 | Unset `CI_RUNS_ON`; disable the 4 self-hosted runners | 5 m | `deploy-api.yml` green on a hosted runner |
| 3 | `Dockerfile.engine`; kill 4 absolute paths; `usage_wall` env var; macOS code no-ops off macOS | 90 m | image builds |
| 4 | **`docker run` one full tick against a scratch store, locally** | 30 m | **ABORT GATE — one dossier written, or stop** |
| 5 | `deploy/compose/docker-compose.yml`, boot it once locally | 20 m | second adapter proven |
| 6 | Fly app + volume + `fly secrets set` from `.env`; **no `[http_service]`** | 30 m | `fly status` |
| 7 | Copy `store/` 691 MB to the volume; counts + `PRAGMA integrity_check` | 30 m | `STORE_MIGRATE PASS` |
| 8 | Boot **PAUSEd**; shadow tick against a **copy** | 30 m | **ABORT GATE — dossier matches the laptop's shape** |
| 9 | Check MiniMax / Exa / Stripe IP allowlists (EDGE-11) | 10 m | no allowlist, or updated |
| 10 | **Cutover**: PAUSE laptop → wait `sleeping` → `launchctl bootout` → unpause Fly | 20 m | state probe reads a Fly pid |
| 11 | Console + control-center as processes 2 and 3; `fly proxy` | 35 m | every console action works |
| 12 | Reverse restore drill + `launchctl bootstrap` + one tick + stop again | 30 m | `RESTORE_DRILL PASS`, dated receipt |

**Rollback, at every step up to 10:** the store was **copied**, never moved. The plists stay
installed. Two commands put the laptop back in charge.

**So the honest shape: the whole estate stops needing this laptop tonight, and the laptop becomes
a standby that has actually been tested rather than one assumed to work.** The one thing that is
still genuinely a plan rather than a fact until step 12 runs is the failback — which is exactly
why it is step 12 and not a daylight job.

---

## 7. What I would do first, if you want one thing

**Answer §1 (5 minutes) and I start at step 2.** Everything from step 2 to step 4 is
brain-agnostic — the Dockerfile and the path fixes are the same whichever option you pick — so the
only thing your answer changes is two lines of `config.yaml` and which secret the image gets. If
you want me moving before you decide, say so and I will build through step 4 and stop there.

---

## 8. Verification commands (this doc must not go stale)

```bash
# What is actually running, and where
launchctl list | grep -E 'prospector|hermes|actions.runner'
fly apps list && fly status -a prospector-store-api
.venv/bin/python scripts/live_checkout.py

# The engine's own state
~/.claude/projects/-Users-chidionyema-Documents-code-prospector/.state-probe
ls -l store/prospector.jsonl                 # EDGE-3: is the ledger still 255 MB?

# The gates this plan adds
python3 scripts/restore_drill.py             # must print RESTORE_DRILL PASS, dated
grep -rn 'Path(__file__)' --include='*.py' | grep store   # EDGE-4: must be empty
```

---

## 9. Open, needing you

1. **§1 — which brain option?** REDUCED 2026-08-18, and it is no longer a blocker.
   Option C works today: the founder directive "we cant be depedint on claude code, it has to be
   a option only" is implemented (PR #303), so no chain leads with `claude_cli` and the engine
   runs on a container with no Claude auth at all. Option B also turns out to need no purchase —
   `ANTHROPIC_API_KEY` is present and set in `.env` (108 chars), which contradicts the "no
   ANTHROPIC_API_KEY in this estate" line in `CLAUDE.md`. **Unverified: whether that key has
   any balance.** Option A stays the only one needing the 20-minute proof and a ToS call.
2. ~~**EDGE-17 — `artifact_operator:145`**~~ **DECIDED AND SHIPPED 2026-08-18, PR #303.** It is
   `[minimax, claude_cli]`. Claude stays second, reached as the shelf-copy escalation target.
   Reordering it alone would have made that escalation inert — both prose chains then lead with
   `minimax`, so the rewrite would have run on the brain that had just failed the publish bar —
   so `run.py::_escalation_order` now drops the failed brain from the escalation chain.
3. **EDGE-9 — private networking, or do the console auth work before P5?**
4. **§3 — confirm Hermes is out of scope for this programme.**

---

## 10. Dependency map — what runs here, what it needs, where it goes

Added 2026-08-18. §4 lists the ways the migration can bite; this is the inventory it bites.
Measured, not recalled: `launchctl list`, `PlistBuddy` on each plist, `lsof -iTCP -sTCP:LISTEN`,
and the `.env` key census. Re-run the commands in §8 before trusting any row.

### 10.1 The eight prospector jobs

Every one of them runs code from **`prospector-live`** and writes state into
**`prospector/store`**. Two directories, one state. That split is deliberate (`CLAUDE.md`, "Where
production runs") and it is the single most important fact for the cutover: moving the code does
not move the store, and moving the store does not move the code.

| launchd label | what it runs | needs | goes where |
|---|---|---|---|
| `com.prospector.scheduler` | `prospector.scheduler.run_scheduled --daemon --interval 7200` | store, MiniMax key, Exa key, outbound web | **Fly.** This is the engine. |
| `com.prospector.consumer` | `prospector.run consume --publish` | store, `api.mumchimp.com`, `STORE_INTERNAL_API_KEY`, Stripe live key | **Fly**, same machine. It publishes, so it touches money. |
| `com.prospector.watchdog` | `run_scheduled --watchdog` | store | **Fly.** Restarts a stalled tick; useless on a machine that is off. |
| `com.prospector.backup` | `scripts/backup_store.py` | store, R2 keys | **Fly.** EDGE-10: must run from exactly one side. |
| `com.prospector.offsite-backup` | `ops.automations.offsite_backup --fix` | store, R2 keys | **Fly**, same reason. |
| `com.prospector.live-update` | `scripts/live_checkout.py --unattended` | git, the `prospector-live` checkout | **Dies at cutover.** It exists to roll a laptop checkout forward. On Fly, a deploy is the update. |
| `com.prospector.control-center` | `streamlit … app.py` on **`100.93.240.113:8601`** | store on local disk | **Blocked — see 10.3.** Reads the store as a filesystem. |
| `com.prospector.ops-console` | `next start -H 100.93.240.113 -p 8611` | store on local disk, `api.mumchimp.com` | **Blocked — see 10.3.** Same problem. |

### 10.2 What else is on this box

- **Four GitHub Actions runners** (`mumchimp-mac`, `-2`, `-3`, `-4`), all online and busy.
  This bullet used to say the problem was "already solved", because `gh variable delete
  CI_RUNS_ON` sends every job to GitHub's hosted machines in one command. **That was wrong, and
  the founder said so:** *"either to flip CI no why would you do this? we have hosted runner and
  github is billing us"*. Hosted minutes are metered, and on 2026-08-16 they stopped entirely
  when a payment failed — five jobs, zero steps, no logs. Deleting the variable is an emergency
  lever, not the migration. The runners move for real: **§10.6**.
- **Eight Hermes jobs** (`ai.hermes.*`: coordinator, gateway, otto-server, rsi, watchdog,
  keepawake, idle-engine, runaway-reaper). §3 recommends these stay put. They do not read the
  prospector store.
- **A local `dotnet` on `127.0.0.1:55664`** — a development Store.Api. Production is
  `api.mumchimp.com` on Fly and is unaffected.

### 10.3 The dashboards — DECIDED AND BUILT, 2026-08-18

**The problem was:** the two admin dashboards read the store as a local directory and bind to a
Tailscale address on this Mac — `100.93.240.113:8601` (control center) and `100.93.240.113:8611`
(ops console). Move the store to a Fly volume and both keep rendering a store that has stopped
changing, without complaint. A stale dashboard reads as a quiet business.

**Founder decision, 2026-08-18:** *"they need to move to fly, nothing business critical can run
off this laptop."* Both move into the engine image. No API read path, no second app.

Built:

- `deploy/engine/Dockerfile` gains a `console` build stage that runs `npm ci && npm run build` in
  `store_platform/src/Ops.Console`, and copies `.next` and `node_modules` into the final image.
  `PROSPECTOR_PYTHON` and `PROSPECTOR_ROOT` are set to the container's paths, keeping the same
  variable names the launchd plist used so the console's own code needs no change.
- `deploy/engine/supervisord.conf` gains `control-center` (streamlit, priority 60) and
  `ops-console` (`next start`, priority 70). `streamlit>=1.40` was already at
  `requirements.txt:61`, so the control centre needed no new dependency.
- Both bind `0.0.0.0`, not loopback. The app has **no public IP** (`fly.toml` has no
  `[http_service]`), so the only route in is the private network:
  `fly proxy 8601:8601 8611:8611 -a prospector-engine`. Binding `127.0.0.1` would have broken
  that, because `fly proxy` reaches the machine's private address rather than its loopback. On a
  plain Docker host the equivalent fence is publishing to `127.0.0.1` on the host, which
  `deploy/targets/sshdocker.sh` does.
- `CONTROL_CENTER_PASSWORD` joins the secrets the cutover carries, and `deploy/cutover.sh` warns
  if it is absent rather than starting an unauthenticated console.

### 10.3b The dependency that was hiding behind it — the money database backup

Found while mapping this, and worth more than the dashboards were.

The only backup of the storefront's SQLite database — orders, entitlements, grant tokens — runs
as a **launchd job on this laptop** (`ops/config/offsite_backup.yaml:29-49`), reaching into Fly
with `fly ssh sftp` and writing `money-db/store.db` to R2. It also backs up the ASP.NET data
protection key ring, without which a restored database hands every buyer a broken download link.

**Switching the laptop off after a successful migration would have switched that backup off too,
and nothing would have said so.** Measured healthy the same night:

```
$ .venv/bin/python ops/automations/offsite_backup.py --config ops/config/offsite_backup.yaml
OK   money-db: 5.8h old
OK   data-protection-keys: 5.8h old
```

`offsite-backup` was already a supervisord program, but the container had no `flyctl` and no Fly
token, so the money-db source would have failed after the move. Both fixed: the Dockerfile
installs `flyctl`, and `FLY_API_TOKEN` joins the carried secrets with a loud warning in
`deploy/cutover.sh` when it is missing. Full risk picture: `docs/ESTATE_CONTINUITY_PLAN.md`.

### 10.4 Secrets — 20 keys, and which the engine actually needs

All 20 are present and non-empty in `.env`. Git does not carry it; on the laptop the live
checkout symlinks back to this one, and on Fly each becomes a `fly secrets set`.

**Needed by the engine on Fly:** `MINIMAX_API_KEY`, `EXA_API_KEY`, `STORE_INTERNAL_API_KEY`,
`STORE_API_URL`, `STRIPE_LIVE_API_KEY`, `PROSPECTOR_ENTITLEMENTS_API_KEY`, and the four R2 keys
(`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`) for the backup job.

**Not needed:** `GEMINI_API_KEY` (no config selects Gemini), `STANDARDCOMPUTE_API_KEY` (adapter
deleted 2026-08-15), `DEEPSEEK_API_KEY` and `OPENROUTER_API_KEY` (no chain in `config.yaml`
names them). Carrying a dead key to a new host is how a dead tier gets quietly revived.

**`ANTHROPIC_API_KEY` is set** — see §9 item 1. Balance unverified.

### 10.5 Outbound — must be reachable from Fly, or the tick does nothing

`api.minimax.io` (the brain), `html.duckduckgo.com` and the Exa API (grounding),
`api.mumchimp.com` (publishing), Stripe, and the R2 endpoint
(`<account>.r2.cloudflarestorage.com`). All public HTTPS, no allowlisting, nothing that depends
on being on this network. **This is the part of the migration with no hidden dependency.**

### 10.6 The CI runners — BUILT 2026-08-18

**Founder, 2026-08-18:** *"as part of our migration don't forget our github hosted runners
also"*, and earlier, *"even our runners could move to fly also"*.

**Measured before building anything:**

```
$ gh api repos/chidionyema/prospector/actions/runners --jq '.runners[] | "\(.name)\t\(.status)\t\(.os)\t\(.busy)"'
mumchimp-mac    online  macOS   true
mumchimp-mac-2  online  macOS   true
mumchimp-mac-3  online  macOS   true
mumchimp-mac-4  online  macOS   true

$ gh variable list | grep CI_RUNS_ON
CI_RUNS_ON      self-hosted     2026-08-17T23:37:53Z
```

All four are launchd jobs under `~/actions-runner*` on this laptop. Closing the lid stops CI
for the whole repository. Same problem as the engine, same answer.

**Why a Linux container and not a macOS one.** `.github/workflows/ci.yml:16-18` records that the
jobs are OS-portable — no `apt-get`, no `sudo`, no docker, no service containers. Every
toolchain arrives through an action that fetches its own copy, and the python job deliberately
uses `uv venv` rather than the system interpreter (`ci.yml:190-208`) after `setup-python` failed
on the Macs with `mkdir: /Users/runner: Permission denied`. So the image installs **no language
runtimes at all**: it installs what those actions need in order to unpack and run what they
download.

**Built:**

| File | What it is |
|---|---|
| `deploy/runner/Dockerfile` | Ubuntu 24.04 + the pinned `actions/runner` tarball. The one non-obvious dependency is `libicu74`: the runner agent is itself a .NET program and refuses to start without ICU, failing as "Couldn't find a valid ICU package" rather than as a missing command. |
| `deploy/runner/entrypoint.sh` | Asks GitHub for a registration token at every start, registers `--ephemeral`, runs one job, exits. Deregisters on the way out through a trap. |
| `deploy/runner/fly.toml` | `prospector-ci`, no public IP, `restart policy = always`, `shared-cpu-4x` / 8 GB. |
| `deploy/runners.sh` | `up N` / `down` / `status` / `laptop-off` / `laptop-on`. |

**Why ephemeral.** A long-lived runner carries the last job's `node_modules`, `.venv`, `obj/`
and half-written `store/` into the next one. On the Macs `_work/prospector/prospector` is a
permanent directory, and "green on runner 2, red on runner 4" was a real symptom. A container
that exits after one job cannot carry state forward. The cost is a fresh checkout per job, and
`actions/cache` absorbs most of it because the caches live in GitHub's cache service.

**The integration is one label.** The runners come up carrying `self-hosted`, which is exactly
what `vars.CI_RUNS_ON` asks for. Nothing in `.github/` changes. Jobs go to whichever runner is
free, Fly or Mac, so the two fleets coexist — and that coexistence *is* the migration: bring the
Fly runners up, watch `runners.sh status` show them taking jobs, then `runners.sh laptop-off`.

`laptop-off` refuses to run while no non-macOS runner is online. `runs-on: self-hosted` does not
fall back to GitHub-hosted; with no runners the jobs queue forever and report nothing, which is
the same silent failure mode as a stale dashboard.

**Credential.** The container needs a fine-grained PAT with `Administration: read and write` on
this one repository, and nothing else. That single permission can add and remove runners; it
cannot read code, push, or reach another repo. It is deliberately **not** the money keys: a
runner executes code from every pull request, including one an outsider opened.
`deploy/runners.sh up` refuses to start without `GITHUB_RUNNER_PAT` and prints the exact
settings page and permission to use.

**Portability, same contract as the engine.** `PROSPECTOR_RUNNER_TARGET` names an adapter in
`deploy/targets/`. The image calls no platform API — a runner makes only outbound calls, so
moving it is `fly deploy` becoming `docker run` and nothing else.

## 11. Cutover log — the five attempts and what each one fixed

Every defect below was found by running the cutover, not by reading it. Each is now fixed in the
script, so a repeat run cannot hit it again. Attempts 2, 3 and 4 failed with the engine already
stopped, which is why every fix moves the check EARLIER.

| # | Time | Failed at | Cause | Fix |
|---|------|-----------|-------|-----|
| 1 | 02:27 | phase 3, build | `failed to calculate checksum ... "/requirements.txt": not found` — the docker build context was `deploy/`, but every `COPY` in the engine Dockerfile is repo-root-relative | `REPO_ROOT` in `deploy/targets/fly.sh`; `fly deploy "$REPO_ROOT" --config .../fly.toml` |
| 2 | 02:30 | phase 5, pack | `can't open file '.../prospector/scripts/store_migrate.py'` — the adapter read its TOOLS from the main checkout, where the new script does not exist | `TOOLS` in `deploy/targets/laptop.sh`, plus a `t_preflight` check so a missing tool fails in phase 1 |
| 3 | 02:36 | phase 5, pack | `store_migrate.py: error: unrecognized arguments: --store` | parent parser with `default=argparse.SUPPRESS`, so `--store` works on both sides of the subcommand |
| 4 | 02:40 | phase 6, ship | `Error: app prospector-engine has no started VMs` — `fly scale count 1` returns when the machine is CREATED, and the next command is `fly ssh console` | `t_start` polls `fly machines list` until `state=started`, up to 10 minutes, and dumps the logs if it never gets there |
| 5 | 02:44 | phase 6, verify | `STORE_MIGRATE VERIFY FAIL — 3 wrong size`, `ledger_lines 906950 -> 906967`. The copy was good; the manifest was not. It was built by a stat-and-hash pass BEFORE the tar, and a 0.5 GiB tree takes four minutes to compress, so it described a store 17 ledger lines older than the tarball | `cmd_pack` hashes the bytes as `tarfile` writes them (`_HashingReader`) and derives the census from what was archived, so the tarball proves itself by construction |
| 5b | 02:46 | the cause of 5 | A generation run started three minutes AFTER phase 4 reported "no writers live" and appended to `prospector.jsonl`. One stop-and-check cannot see something that comes back after the check | `t_stop` now does three rounds of bootout, `pkill`, `pkill -9`, a 10s settle, then looks again, and calls the store quiet only when a round finds nothing to do |

Downtime from each failure was bounded by the rollback, which restarted all seven launchd jobs
every time: 6s on attempt 2, 3m35s on attempt 4. No customer data was lost and no state was
deleted — the packed tarball is kept at `$TMPDIR/prospector-cutover` on every path.

**The runner image had one of the same class.** `actions/runner` 2.328.0 ships an
`installdependencies.sh` that asks apt for `libicu72`, which does not exist on Ubuntu 24.04. The
build died with `E: Unable to locate package libicu72`, which reads like a broken base image.
`deploy/runner/Dockerfile` installs the 24.04 equivalents itself and does not run that script.
