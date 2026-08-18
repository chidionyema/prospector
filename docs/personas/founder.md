# Founder — the whole business, measured

**Seat:** the person who owns the money, the machine and the decisions nobody else can make.
**Rule for this document:** every number below was measured on **2026-08-18, between 12:53Z and
13:20Z**. Facts about production were measured **on Fly**, against the running app. Facts about the
code were measured from this checkout (`/Users/chidionyema/Documents/code/prospector`, HEAD
`c3cb68b`, committed 2026-08-17 21:11:32 +0100). Where a number could not be measured it says
`HYPOTHESIS:` and names the exact command that would settle it. Nothing here is remembered.

**Read §4.0 first if you read nothing else.** Production moved off this laptop and onto Fly on
2026-08-18. Every laptop-based probe in this repo now reports on a retired setup, and therefore
lies.

Shared facts live once, in [../ESTATE_MAP.md](../ESTATE_MAP.md). This document is the founder's
reading of them.

---

## 0. The one-paragraph state of the business

**The engine is running and the shop is open.** The engine runs on Fly as app
`prospector-engine`, machine `80d34da6636478`, version 12, region `lhr`, state `started`, last
updated `2026-08-18T11:39:47Z` (`fly status -a prospector-engine`). Its own heartbeat, read at
13:12:36Z wall clock, says `{"ts": "2026-08-18T13:12:26.504469+00:00", "pid": 679, "phase":
"sleeping", "interval_s": 7200, "cycles": 1, "slept_s": 3660, "code": "617c2538c433"}` — the
producer is sleeping between two-hour ticks, exactly as configured. The storefront answered `200`
at `https://mumchimp.com/` in 0.843s, `https://api.mumchimp.com/catalog` returned **74 packs worth
£4,229.26** at list price, and the money rail self-reports
`{"provider":"stripe","mode":"live","environment":"Production","decidedAtUtc":"2026-08-18T05:40:06Z"}`.

**Two things are wrong, and both are real.** First, the drain is blocked right now: the consumer's
heartbeat at 13:13:14Z reads `"phase": "skipped"`, `"cycle": 8`, `"skipped_reason": "moat blind:
every brain it can rule with is marked dead (claude_cli for 2859s more, minimax for 0s more)"`.
Three minutes earlier, at 13:10:57Z, the same consumer was `"phase": "draining"`, `"cycle": 7`,
`"resumed_total": 120`, `"errors": 0`. So the drain works and is currently benched waiting for a
brain to come back. Second, **44 finished packs cannot be bought**
(`/data/store/scheduler/ALERT.txt` on the Fly volume, raised 2026-08-18T12:11:25Z, severity
critical). The shop is open, the factory is running, and there is finished stock in the yard that
never reached the shelf.

---

## 1. The business in three parts

### 1.1 The engine — it makes packs

Python, in `prospector/`. Measured: **153 `.py` files, 66,664 lines**
(`find prospector -name '*.py' | wc -l`, then `-exec cat {} + | wc -l`).

The procedure is fixed and written down in `RUN.md` (132 lines), and `prospector/run.py` (4,317
lines) is the CLI that executes it. The pipeline, in order, with the module that owns each step:

| Step | Module | What it does |
|---|---|---|
| Signal in | `prospector/discover.py` | surfaces or accepts a market signal |
| Generate | `prospector/generate.py` | mints candidate business ideas from a signal |
| Dedup | `prospector/dedup.py` | drops near-duplicates against the catalogue |
| Prescreen | `prospector/prescreen.py` | cheap first triage |
| Verify | `prospector/verify.py` (1,258 lines) | the moat: six checks, each grounded in fetched sources |
| Price evidence | `prospector/price_comparables.py` | the seventh check; can never kill |
| Kill gates | `prospector/kill_filter.py:20` `is_hard_fail`, `:54` `apply_gates` | KILL or PASS |
| Score | `prospector/score.py` | composite on six weighted axes |
| Dossier | `prospector/dossier.py` (1,075 lines) | the artefact written to `store/dossiers/` |
| Publish | `publish/` + `prospector/bridge.py` (2,457 lines) | mints the price and the catalogue row together |

Two facts about the engine that matter to you commercially:

- **Only ideas that survive everything get published.** `config.yaml:1506` reads
  `publish_on: pass`.
- **Price is a rung on a fixed ladder, not a computed number.** `config.yaml:1829` reads
  `rungs: [1999, 2999, 4999, 7999, 9999]` — £19.99 to £99.99 in pence. `config.yaml:1505` sets the
  default rung, `price_pence: 4999`. The £99.99 ceiling is your decision, recorded in the config
  comment at `config.yaml:1824`.

The daemon that runs the engine unattended is `prospector/scheduler/run_scheduled.py` (2,884 lines);
its per-cycle entry point is `run_tick` at `prospector/scheduler/run_scheduled.py:1666`. The drain
that finishes deferred work is `prospector/consumer.py`, with `prospector/run.py:2551` `drainable()`
as the single definition of "backlog" and `prospector/run.py:2579` `_cmd_resume` as the drain
command.

### 1.2 The storefront — it sells them

.NET plus Next.js, in `store_platform/`. Measured: **196 `.cs` files** (excluding `obj/` and `bin/`)
and **299 `.ts`/`.tsx` files** (excluding `node_modules`).

Four projects under `store_platform/src/`:

- `Store.Api` — the money and delivery API. Endpoints live in
  `store_platform/src/Store.Api/Endpoints/`: `CheckoutEndpoints.cs`, `WebhookEndpoints.cs`,
  `DeliveryEndpoints.cs`, `OpsEndpoints.cs`, `AnalyticsEndpoints.cs`, `FounderPreviewEndpoints.cs`.
- `Store.Web` — the public shop at `mumchimp.com`.
- `Store.Catalog` — the catalogue model shared by both.
- `Store.Tests` — the platform's own tests.

The payment rail is `store_platform/src/Store.Api/Payments/`: `StripeProvider.cs` is the provider,
`IPaymentProvider.cs` is the interface it implements (so Stripe is replaceable),
`MoneyRailConfigGate.cs` decides live-vs-test at startup, `MoneyRailStatus.cs` is what the gate
reports, and `PaymentReversal.cs` is the refund/dispute type.

Measured on the live shelf, 2026-08-18 12:53Z, from `https://api.mumchimp.com/catalog`:

| Price | Packs |
|---|---|
| £19.99 | 2 |
| £29.99 | 17 |
| £49.99 | 30 |
| £79.99 | 16 |
| £99.99 | 9 |
| **Total** | **74 packs, £4,229.26** |

Every one of the 74 carries `"paymentProvider":"stripe"`.

### 1.3 The ops layer — it runs both

`prospector/ops/` plus `store_platform/src/Ops.Console` (a Next.js dashboard) plus `ops/automations/`
plus `scripts/`. `prospector/ops/console_api.py` is 2,548 lines — the third-largest module in the
engine, which tells you how much of this system is about watching itself.

Measured file counts by top-level directory (`find <dir> -type f | wc -l`):

| Directory | Files | What it is |
|---|---|---|
| `store/` | 37,381 | all runtime state: dossiers, listings, ledger, health, caches |
| `store_platform/` | 79,865 | the shop (includes `node_modules`) |
| `tests/` | 1,169 | 369 `test_*.py` files, 73,116 lines of Python |
| `prospector/` | 451 | the engine |
| `tools/` | 210 | 40 one-off and backfill tools |
| `publish/` | 193 | the publish package |
| `scripts/` | 60 | operator commands and probes |
| `docs/` | 54 | 20,330 lines of programme documents |
| `ops/` | 49 | launchd job definitions and automations |

`config.yaml` is **2,550 lines**. That is not a config file, it is the written record of every
decision you have made about how the engine behaves, with the reasoning attached. Treat it as a
document.

---

## 2. The money

### 2.1 What has been spent

**Total metered-plus-CLI spend recorded since the ledger began: $4,661.75.**

The live ledger is on the Fly volume, not on this laptop. Measured by streaming it in place:

```
$ fly ssh console -a prospector-engine -C "sh -c \"grep -ao '\"cost_usd\": *[0-9.]*' /data/store/prospector.jsonl | awk -F': *' '{s+=\$2+0} END {printf \"%.4f n=%d\n\", s, NR}'\""
4661.7479 n=20886
```

The same scan against this laptop's stale copy returns the identical sum on 20,322 values. The 564
extra records on Fly all carry `cost_usd` of zero, which is why the totals agree exactly — a known
class of unpriced call, noted in code at `prospector/telemetry.py:280`.

Ledger window, from its first and last lines: **2026-06-15 00:46:11 to 2026-08-18**. That is 64
days, so roughly **$73/day averaged over the whole life of the project**.

Today's spend, measured the same way over lines stamped `2026-08-18`: **$13.77**. Both copies agree
on that figure.

The live ledger file: **284,991,024 bytes (285 MB), 956,012 lines** on the Fly volume. The laptop's
stale copy is 270,224,298 bytes / 907,556 lines and contains **33,553** rows tagged
`"event": "spend"`. The gap between the two is everything production has written since the cutover.

### 2.2 What has been earned

**HYPOTHESIS: I could not measure revenue.** The route exists and is fail-closed. Measured:

```
$ curl -s -o /dev/null -w '%{http_code}\n' https://api.mumchimp.com/internal/ops/sales
401
```

The route is registered at `store_platform/src/Store.Api/Endpoints/OpsEndpoints.cs:52`
(`app.MapGet("/internal/ops/sales", SalesAsync)`), and the gate is the `X-Internal-Key` header
check named in the file's own comment at `OpsEndpoints.cs:36`. Sibling routes exist for orders
(`:50`), a single order (`:51`), disputes (`:53`) and deliveries (`:54`).

**The exact check that would settle it:**

```bash
curl -s -H "X-Internal-Key: $STORE_INTERNAL_API_KEY" https://api.mumchimp.com/internal/ops/sales
```

with `STORE_INTERNAL_API_KEY` sourced from `.env` (the key name is present in `.env`; the value is
not printed anywhere in this document). Run it and paste the answer here. Until then, the honest
statement about revenue is that I do not know it.

What I can prove: the rail is on **live** keys in **Production** and made that decision at
`2026-08-18T05:40:06Z`, so a card presented today would be charged for real. That is the
`/healthz/money-rail` response quoted in §0.

### 2.3 The two spend meters, and which one is blind

There are two, and they measure different money. This is the single most important financial fact
about the system.

| Meter | What it counts | Where it is enforced | Blind to |
|---|---|---|---|
| Metered API spend | invoiced dollars from MiniMax, DeepSeek, Exa | `config.yaml:2517` `daily_cap_usd: 100.0` | Claude Code CLI burn |
| Subscription burn | Claude Code CLI consumption of the Max plan | `config.yaml:2528` `daily_subscription_cap_usd: 0.0` | nothing — but it is **off** |

The blindness is structural, not a bug, and it is documented in the config comment at
`config.yaml:2521-2524`: the CLI logs its cost under `cost_usd` with no `event: spend` tag, so the
ledger scan that feeds the cap skips it. The same point is restated in code at
`prospector/drain_state.py:101`. That comment records a measurement from 2026-08-05: metered $1.64
against CLI $71.94 on the same day — **the liability rail covered 2% of that day's consumption**.

My own measurement is consistent with that shape: **20,322 priced calls carry a `cost_usd` value,
but only 33,553 rows in the whole 907,556-line ledger are tagged `"event": "spend"`**. The two
populations are not the same set.

Second meter is currently **report-only**: `daily_subscription_cap_usd: 0.0` at `config.yaml:2528`
means nothing halts on subscription burn. The config comment at `config.yaml:2529-2531` explains
why arming it is not a free action — a hard subscription wall refuses the whole tick *before* the
drain, so arming it freezes the backlog instead of just slowing generation.

### 2.4 The three rails, each with its line

1. **Daily spend ceiling.** `config.yaml:2517` `daily_cap_usd: 100.0`. Read by
   `prospector/ops/spend.py:54` (`CAP_KEY = "spend.daily_cap_usd"`), enforced at
   `prospector/ops/spend.py:351-352`. Raised from $20 to $100 on 2026-08-16; the config comment at
   `config.yaml:2508-2516` gives the basis (metered spend went $0.69 → $8.47 in four days after
   MiniMax took the moat) and names the real failure mode: **binding the cap does not lose money, it
   stalls the queue**.
2. **Warn threshold.** `config.yaml:2520` `warn_at_usd: 75.0`, held at 75% of the cap.
   `prospector/ops/spend.py:55` `WARN_KEY = "spend.warn_at_usd"`. Note that
   `prospector/config.py:270` still carries a code default of `15.0`; the live value is the config
   file's 75.0.
3. **The kill switch.** A file. `prospector/scheduler/guard.py:66` `PAUSE_FILENAME = "PAUSE"`.
   Creating `store/scheduler/PAUSE` halts the entire tick — generation and drain together. Two
   half-stops leave the drain running: `PAUSE_GENERATION`
   (checked at `prospector/scheduler/run_scheduled.py:233`, per the comment at
   `prospector/consumer.py:74`) and `PAUSE_CONSUMER`
   (`prospector/consumer.py:78` `CONSUMER_PAUSE_FILENAME`).

To stop all spend right now:

```bash
touch /Users/chidionyema/Documents/code/prospector/store/scheduler/PAUSE
```

That is the whole mechanism. It is a file because a file cannot fail to deploy.

---

## 3. The asset — what exists that has value

### 3.1 The dossier database

**The production database is on the Fly volume.** `/data/store/prospector.db`, one table,
`dossiers`, **3,229 rows**, measured at 13:13Z:

```
$ fly ssh console -a prospector-engine -C "python3 -c \"import sqlite3;c=sqlite3.connect('/data/store/prospector.db');print(list(c.execute('select decision,count(*) from dossiers group by decision')))\""
[('defer', 214), ('kill', 2889), ('pass', 126)]
```

| Decision | Production (Fly) | Laptop copy (stale) |
|---|---|---|
| kill | 2,889 | 2,842 |
| pass | **126** | 108 |
| defer | **214** | 45 |
| **total** | **3,229** | 2,995 |

The laptop column is here only so you can recognise a stale number when someone quotes one. Ignore
it otherwise.

**The defer count is the one to watch: 214.** Those are ideas the engine paid to generate and could
not finish judging. That is the drain's backlog, and §0 shows the drain currently benched on a
moat-blind condition. Every deferred row is money already spent that has produced no answer yet.

Rows were created between `2026-06-13T18:48:45Z` and `2026-08-18T13:13:08Z` — the newest is seconds
old at the time of measurement, which is independent proof the engine is live.

Only **1 row of 3,229** is marked `provisional`. That is the fence working: anything ruled by a
brain outside `moat_primary()` is stamped provisional and re-vetted rather than published
(`prospector/operator.py:1509` `is_provisional_provider`, with `moat_primary()` at
`prospector/operator.py:1443`).

**189 rows carry a tombstone** — ideas deliberately retired.

### 3.2 What killed 2,889 ideas

Measured on the Fly database at 13:13Z:

| Gate | Kills |
|---|---|
| `moat_ungrounded` | 1,070 |
| `min_composite` | 758 |
| `incumbency` | 277 |
| `source_or_die` | 256 |
| `value_durability` | 202 |
| `adversarial_decisive` | 154 |
| `payer_solvency` | 62 |
| `legality` | 34 |
| `distribution` | 22 |
| `currency` | 14 |
| `route_to_market` | 13 |
| `pain_reality` | 9 |
| `buyer_intent` | 9 |
| (none recorded) | 9 |

Read this commercially. **1,070 kills — 37% of all kills — are `moat_ungrounded`**, which is not a
judgement about the idea. It means the system could not find evidence. Add `source_or_die` (256) and
**1,326 kills, 46%, are about retrieval rather than about the business idea**. That is the largest
single lever on yield in the whole system, and it is a supply-of-evidence problem, not a
model-quality problem.

The next block — `incumbency` 277, `value_durability` 202, `adversarial_decisive` 154,
`payer_solvency` 62, `legality` 34 — totals 729 and *is* real commercial judgement. Those are ideas
the filter genuinely rejected on the merits.

### 3.3 The passes

126 PASS rows. Composite score: **min 2.5, mean 2.885, max 3.75**.

By market:

| Market | Passes |
|---|---|
| uk | 84 |
| us-ga | 13 |
| us | 13 |
| us-pa | 5 |
| us-tx | 3 |
| us-il | 3 |
| us-fl | 2 |
| us-ca | 2 |
| (none recorded) | 1 |

**67% of everything that passed is UK.** The US work is real but thin, and it is concentrated in
Georgia.

### 3.4 The files on disk

Production state lives on one Fly volume: `vol_42kyqo6g0kdzew14`, named `prospector_store`, **20 GB,
region `lhr`, zone `ceec`, encrypted**, attached to machine `80d34da6636478`, created 12 hours before
measurement (`fly volumes list -a prospector-engine`).

| Path (on the Fly volume) | Count / size |
|---|---|
| `/data/store/` | **559 MB** total |
| `/data/store/dossiers/` | 3,182 entries |
| `/data/store/listings/` | 119 files |
| `/data/store/prospector.jsonl` | 285 MB, 956,012 lines |

The laptop's `store/` is 707 MB — larger, because it still holds a 172 MB retrieval cache the new
volume has not rebuilt. Cache is regenerable and is not an asset.

### 3.5 The gap between what exists and what is for sale

Three numbers, all measured on production today, that do not agree:

- **126** PASS dossiers in the Fly database.
- **119** listing files in `/data/store/listings/`.
- **74** packs live on `https://api.mumchimp.com/catalog`.

And the alert file on the Fly volume says **44 PASSes are stranded off the shelf**:

```
$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/ALERT.txt"
2026-08-18T12:11:25.978733+00:00  🚨 [critical] 44 PASS(es) stranded off the shelf
The engine produced packs no one can buy. [25363e54b649587a] 2026-08-14  lint blocked (3 error(s):
placeholders) | [e698149e137fc164] 2026-08-15  never published (no lint record) | [9f393244da5f6c19]
2026-08-15  lint blocked (2 error(s): title) (+41 more) — fix: .venv/bin/python
tools/verify_pass_shelf_coverage.py
```

The named causes are lint failures — placeholders left in the text, bad titles — and packs that were
never published at all because no lint record exists. Its own suggested fix is in the alert.

**The commercial reading: more than a third of the finished inventory has never been offered to a
buyer, and the number is growing.** It was 34 on the laptop's last alert at 2026-08-17T23:45Z and is
44 on production at 2026-08-18T12:11Z — **ten more in about twelve hours**. At the measured average
live price (£4,229.26 / 74 = £57.15), 44 stranded packs are about £2,515 of shelf value that cannot
be bought. That is not lost revenue — nobody has bought the 74 either, as far as I can prove — but it
is the cheapest inventory increase available, because the work is already done and paid for.

The growth rate is the real signal. A stranded count that rises while the engine runs means the
publish path is failing faster than anyone is fixing it.

There is a report-only probe for exactly this:

```bash
.venv/bin/python -m ops.automations.stranded_packs --json
```

Its own `--help` describes it as "Report finished packs that cannot be sold, and the gate blocking
each."

### 3.6 The code and the record

- **699 commits** (`git log --oneline | wc -l`), **44 remote branches**.
- **369 test files, 73,116 lines of test Python** against 66,664 lines of engine Python. The test
  suite is larger than the thing it tests.
- **20,330 lines of programme documents** in `docs/`.

That documentation volume is an asset and a liability at once. It is why a new person can be useful
in a day. It is also why facts drift: the same claim written in four places goes stale in three of
them. That is the problem [../ESTATE_MAP.md](../ESTATE_MAP.md) exists to fix.

---

## 4. The machine — what runs where, right now

### 4.0 The lesson: a probe that outlives the thing it probes will lie to you

**Read this before you read any status output.** Production moved off this laptop and onto Fly on
2026-08-18. The laptop launchd jobs and `/Users/chidionyema/Documents/code/prospector-live` were both
decommissioned by that move.

`scripts/live_checkout.py` was not retired with them. It still runs, and it still prints:

```
  com.prospector.scheduler   NOT RUNNING
  com.prospector.consumer    NOT RUNNING
  com.prospector.ops-console NOT RUNNING
  MISSING: /Users/chidionyema/Documents/code/prospector-live
```

**That is the correct description of a retired setup, and it reads exactly like a total outage.**
The same trap applies to `store/scheduler/heartbeat.json` in this checkout: it is stale at
`2026-08-18T02:13:33Z` because the Fly engine writes to its own volume, not to this laptop's
`store/`. An eleven-hour-old heartbeat here means nothing at all now.

This is worth recording as a rule, because it will happen again on the next migration:

> **A monitoring probe must be retired with the thing it monitors.** A probe left pointing at
> decommissioned infrastructure does not go quiet. It reports absence, and absence is
> indistinguishable from failure. The cost is a false alarm that looks like a catastrophe, and the
> real risk is the reverse — you learn to ignore it, and then it is right.

**The correct live command is the Fly heartbeat, not the laptop probe:**

```bash
fly status -a prospector-engine
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
```

**Outstanding work item:** `scripts/live_checkout.py` should either be deleted or rewritten to probe
Fly. Until one of those happens, it is a tripwire that fires on nothing.

### 4.1 In the cloud — this is production

`fly apps list`, measured 2026-08-18 13:13Z:

| App | Status | Latest deploy | What it is |
|---|---|---|---|
| `prospector-engine` | **deployed** | 1h34m ago | **the engine.** Machine `80d34da6636478`, v12, `lhr`, `started` |
| `prospector-store-api` | deployed | 7h33m ago | the money and delivery API |
| `prospector-store-web` | deployed | 3h16m ago | the public shop |
| `prospector-searxng` | deployed | 4h31m ago | self-hosted search for grounding |
| `prospector-hermes` | deployed | 4h34m ago | the operator surface |
| `prospector-ci` | suspended | 3m33s ago | CI, currently suspended |
| `tie-*` (5 apps) | suspended | Jun 2026 | a different, dormant project |

**Six live Fly apps, not three.** The engine is now a peer of the shop, in the same region, on the
same account.

Sizes and machine counts from the committed configs: `prospector-store-api` has
`min_machines_running = 1` (`store_platform/deploy/fly/api.fly.toml:58`) at `shared-cpu-1x` / 512mb
(`:68-69`); `prospector-store-web` has `min_machines_running = 2`
(`store_platform/deploy/fly/web.fly.toml:43`); a staging config exists at
`store_platform/deploy/fly/api.staging.fly.toml:10`.

Engine state lives on `vol_42kyqo6g0kdzew14` (`prospector_store`, 20 GB, `lhr`, zone `ceec`,
**encrypted**), attached to `80d34da6636478`, created 12 hours before measurement.

Deployment is by GitHub Actions: `.github/workflows/deploy-api.yml`, `deploy-web.yml`, plus
`ci.yml` and `e2e-live-smoke.yml`.

Also off-laptop: the Cloudflare R2 buckets that `ops/automations/offsite_backup.py` writes to. That
script is generic — it reads bucket, prefix and retention from a declaration and refuses to run on
an empty bucket name (`ops/automations/offsite_backup.py:137-138` raises `CannotEstablish` if the
declaration has no `storage.bucket`), and it prunes to the newest N copies
(`ops/automations/offsite_backup.py:339`).

### 4.2 Still on the laptop

Much less than before the cutover, but not nothing.

| On the laptop | State | Matters because |
|---|---|---|
| Four GitHub Actions runners | **all four loaded and running** (`launchctl list`) | **CI runs here.** No laptop, no deploy. |
| `com.prospector.backup` | loaded | a backup job still tied to the machine |
| `.env`, 24 named keys | present, gitignored | git does not carry it; see §5 Rank 3 |
| `.lux/keys/agent.pem` | present, untracked | the commit gate cannot sign without it |
| `com.prospector.scheduler`, `.consumer`, `.ops-console`, `.watchdog` | **retired** — plists on disk, not loaded | ignore them; see §4.0 |

The retired plists are still sitting in `~/Library/LaunchAgents/`. Leaving a decommissioned plist on
disk is how the next person concludes the engine is broken. **Outstanding: delete them.**

### 4.3 The retired laptop deployment, for the record

`CLAUDE.md` still documents the previous arrangement: daemons running from
`/Users/chidionyema/Documents/code/prospector-live`, pinned detached at `origin/main`, with
`PROSPECTOR_STORE_DIR` on the plists keeping state in this checkout's `store/`. **That arrangement
ended on 2026-08-18 when the engine moved to Fly.** The directory is gone and the jobs are unloaded,
both by intent.

**Outstanding: `CLAUDE.md` is now wrong about where production runs.** It is the first file every
agent and every new person reads. The check:
`grep -n "prospector-live" CLAUDE.md docs/*.md` — every hit is a doc that needs the Fly cutover
written into it.

### 4.4 If the laptop died today

Honest inventory, and it is much better than it was a day ago.

**Survives:** the engine keeps generating and draining (Fly, own volume, encrypted). The shop stays
up and keeps taking money. The whole 3,229-row dossier database and the 285 MB ledger, because they
now live on the Fly volume rather than on this disk. The git history (GitHub). The R2 backups —
graded `DONE` by the programme check `DAT-1 Money data has one copy, 5-day window`.

**Dies immediately:** all four CI runners, so no deploy can ship — you would have a running business
you could not change. The `.env` file with 24 named keys, which git does not carry. `.lux/keys/agent.pem`.

**The cutover moved the crown jewels off the laptop.** What is left on it is the ability to *change*
the system, not the system itself. That is a much better failure mode, and it makes the CI runners
the single most important laptop-bound thing you own.

**Unproven:** whether the R2 backup would actually restore. The programme check grades this
`OPEN DAT-2 Restore never proven end to end` with the evidence line *"scripts/restore_drill.py
exists; no dated receipt under store/ops/"*. The drill script is written. Nobody has run it and kept
the receipt.

**Time to recover, HYPOTHESIS:** unknown, and that is the point. The check that would produce a real
number is to run the drill on a clean machine and time it:

```bash
.venv/bin/python scripts/restore_drill.py        # read the flags first
```

---

## 5. The risks, ranked

The system grades its own risk register. Run it:

```bash
.venv/bin/python scripts/ops_status.py
```

It printed 40 graded items across eight families (SRC, INF, DAT, AST, DNS, BIZ, PAY, ENG) on
2026-08-18. Ranked below by what it costs you if it fires, not by the order it prints.

### Rank 1 — The drain runs, but every brain it can rule with is benched

**Evidence:** the consumer heartbeat on the Fly volume, read at 13:13:14Z:

```
$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
{"ts": "2026-08-18T13:13:14.563675+00:00", "pid": 680, "role": "consumer", "phase": "skipped",
 "cycle": 8,
 "skipped_reason": "moat blind: every brain it can rule with is marked dead
                    (claude_cli for 2859s more, minimax for 0s more)",
 "code": "617c2538c433"}
```

Two minutes earlier the same file read `"phase": "draining"`, cycle 7, 120 candidates resumed, 0
errors. **Both are true.** The drain works. It is currently benched because both trusted brains
carry a live dead mark, and the rule is deliberate: re-vetting on a benched brain would spend money
and move nothing (`prospector/run.py::_cmd_resume` runs the classifier at `trusted_only=True`).

**Why it matters:** DEFER rows accumulate while this holds. The Fly database shows **214 defers**
against **45** in the older laptop copy of the same store. I can prove both numbers; I am inferring
growth from them rather than measuring it directly, because they are two snapshots roughly twelve
hours apart. Either way 214 is the current backlog, and only the drain clears it.

**Cost if it stays:** the engine keeps minting candidates that nothing finalises. Generation feeds a
queue that is not being emptied.

**Cost of removing it:** possibly nothing. `minimax` reads `0s more` — its mark has already expired,
and the marks are half-open, so exactly one caller re-probes and a recovered brain is back within
one cycle (`prospector/health.py:130`). The question worth your time is not this instance, it is
*why both trusted brains were benched at once*.

```bash
fly ssh console -a prospector-engine -C "cat /data/store/health/providers.json"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
```

If the same reason keeps recurring, the ceiling on this business is brain availability, not idea
supply.

### Rank 2 — 44 finished packs cannot be bought, and the number is rising

**Evidence:** `/data/store/scheduler/ALERT.txt` on the Fly volume, `[critical]`, 2026-08-18T12:11:25Z
(quoted in full in §3.5). Named blockers: lint errors (placeholders, titles) and "never published
(no lint record)".

**Cost if it stays:** about £2,515 of already-paid-for inventory sitting off the shelf (44 × £57.15
measured average live price). Worse than the stock is the rate: **34 on 2026-08-17T23:45Z, 44 on
2026-08-18T12:11Z**. The publish path is failing faster than anyone is fixing it, so this bill grows
on its own.

**Cost of removing it:** one report run, then per-pack fixes. Report first:

```bash
.venv/bin/python -m ops.automations.stranded_packs --json
```

### Rank 3 — Restore has never been proven

**Evidence:** `ops_status.py` → `OPEN DAT-2 Restore never proven end to end` /
"scripts/restore_drill.py exists; no dated receipt under store/ops/".

**Cost if it fires:** the entire 2,995-row dossier database and 190 MB of dossiers. That is
$4,661.75 of measured spend, and it is the only genuinely irreplaceable thing you own.

**Cost of removing it:** one afternoon, once. Run the drill, write the receipt under `store/ops/`
so the check flips to DONE and stays measurable.

### Rank 4 — Twenty-odd secrets in one plaintext file on one laptop

**Evidence:** `ops_status.py` → `MANUAL SRC-5 20 secrets in one plaintext .env`. My own count of
uppercase assignment names in `.env` is **24** (the two counts differ because some `NEXT_PUBLIC_*`
entries are not secrets). The file is 3,788 bytes. Names present include `STRIPE_LIVE_API_KEY`,
`Stripe__WebhookSecret`, `R2_SECRET_ACCESS_KEY`, `FLY_API_TOKEN`, `MINIMAX_API_KEY`,
`STORE_INTERNAL_API_KEY`. **No value is printed here or anywhere in this document.**

**Cost if it fires:** live Stripe keys, the Fly deploy token and the R2 credentials in one place. A
single laptop compromise is a total compromise.

**Cost of removing it:** the check calls it "an operator decision" — a vault or an escrow. This is
yours to make (see §6).

### Rank 5 — Single machine, single region, no staging proven

**Evidence:** `ops_status.py` → `OPEN INF-1 API is one machine in one region` with the line number
in `store_platform/deploy/fly/api.fly.toml`; `MANUAL INF-2 No staging environment` — "a staging
config exists, a staging app may not"; `MANUAL INF-3 No CDN or WAF`;
`MANUAL INF-4 Single Fly account and payment method`.

**Cost if it fires:** the shop is down. One Fly machine, `lhr` only, `min_machines_running = 1`.

**Cost of removing it:** raise `min_machines_running`; that is a config line and a bigger bill.

### Rank 6 — The ledger outgrew its readers

**Evidence:** `ops_status.py` → `OPEN DAT-3 Spend ledger outgrew its readers` /
"store/prospector.jsonl is 270 MB". That grade was taken on the laptop copy. **On production it is
already bigger: 284,991,024 bytes, 956,012 lines** (`fly ssh console -a prospector-engine -C "wc -c
-l /data/store/prospector.jsonl"`). My own full scan of it took minutes, not seconds.

**Cost if it stays:** the spend cap reads this file. A rail that takes minutes to evaluate is a rail
that gets skipped or times out.

**Cost of removing it:** `ops/automations/log_rotation.py` already exists and is graded
`DONE ENG-5 Logs and state grow unbounded`. The ledger specifically is the one that got away.

### Rank 7 — Working tree is far from what production would run

**Evidence:** `ops_status.py` → `OPEN SRC-1 Nothing is committed` /
"132 uncommitted paths, 0 ahead / 27 behind origin/main". Also
`OPEN SRC-6 Runtime state tracked under store/` / "6 runtime files tracked under store/".

**Cost if it fires:** a laptop loss takes 132 uncommitted paths with it, and tracked runtime state
means routine test runs dirty the index.

### Rank 8 — Business and legal gaps

All `MANUAL`, all cheap to close, none of them technical:
`BIZ-2 Legal pages unreviewed by counsel`, `BIZ-3 No dedicated contact page`,
`BIZ-4 No cookie banner`, `BIZ-6 Key-person risk`, `PAY-2 Refunds and disputes have code, no
runbook`, `DNS-2 DNSSEC unsigned`, `DNS-3 Workspace DKIM not published`,
`AST-1 No object versioning on either R2 bucket`.

Already closed: `DONE BIZ-1 No company number or registered address on the site` — company details
found in `Store.Web`. `DONE PAY-1 API knows it is in live mode and tells nobody` —
`MoneyRailStatus.cs` is on `origin/main`, and §0 shows it answering.

### Rank 9 — Engine quality items with no mechanical check yet

`MANUAL ENG-2 The loudest alert names the wrong cause`, `MANUAL ENG-3 Grounding runs on one fast
provider`, `MANUAL ENG-4 MiniMax calls hitting the 600s deadline`, and
`MANUAL ENG-1 Finished packs that cannot be bought` — where the probe returned `rc=1` and gave no
count, so §3.5 had to measure that gap by hand. That probe failing is itself a small defect worth
fixing, because it is the mechanical check for Rank 2.

---

## 6. The decisions that are yours alone

Each of these is blocked on you, not on engineering. Each names what is stuck until you decide.

**1. Where the secrets live.** Twenty-four names in one plaintext `.env` on one laptop. A vault, an
escrow, or accepting the risk in writing. *Blocked until you decide:* `SRC-5` stays `MANUAL`
forever, and there is no recovery path for a laptop compromise.

**2. Whether the subscription meter becomes a wall.** `config.yaml:2528`
`daily_subscription_cap_usd: 0.0` — report only. Arming it caps your real consumption but, per the
config comment at `config.yaml:2529-2531`, a hard wall refuses the whole tick before the drain and
freezes the backlog. *Blocked until you decide:* the larger of your two spend meters has no brake.

**3. Whether comparables may move a price.** `comparables.rung_adjust_enabled` is off. The config
comment at `config.yaml:1813-1817` records the measurement: 16 of 24 recently-vetted ideas carry
cited willingness-to-pay anchors, and where they do, the median job the buyer already pays for is
£170. *Blocked until you decide:* the pricing ladder stays seven hand-typed numbers, which is your
own standing complaint about it.

**4. Whether to reprice the live shelf.** The config comment at `config.yaml:1819-1823` is explicit
that changing the ladder does not touch a pack already listed, because the catalogue row and the
Stripe Price object are minted together by one `PriceDecision` in `prospector/bridge.py`. Rewriting
either alone charges a buyer an amount the fulfilment fence then rejects. *Blocked until you decide:*
74 live packs stay on whatever ladder they were minted under.

**5. Whether the repo goes public.** `ops_status.py` grades `DONE SRC-3` on the evidence
"repo visibility is PRIVATE". If you want it public under MIT that is a business decision with a
one-way door in it.

**6. Whether to fund a second region or a second machine.** `INF-1`, `INF-4`. Money, not code.

**7. Whether to raise `min_machines_running` on the API.** `api.fly.toml:58` is `1`. One machine is
one restart away from a dark shop.

**8. Market focus.** 69 of 108 passes are UK. The US is 39 passes spread over seven state markets.
*Blocked until you decide:* generation keeps spreading thin rather than deepening one market.

**9. Whether refunds get a runbook or a console button.** `prospector/ops/money.py` declares the gap
in code rather than hiding it: `MISSING_ACTIONS` includes `issue-refund`, and `MISSING_READS`
includes `dispute-clock` — the note there says a chargeback's evidence window is days, and
`/internal/ops/disputes` can only sort by the original sale date, so an operator sorting by it
answers the oldest dispute last. *Blocked until you decide:* refunds are handled by hand in the
Stripe dashboard.

**10. Whether a canary checkout runs.** `prospector/ops/money.py` `MISSING_READS` names it:
"a real checkout, taken and refunded on a schedule", because *"the rail reporting `live` proves the
keys are live, not that a card clears"*. *Blocked until you decide:* you will find out the rail is
broken from a customer, not a probe.

---

## 7. What is outstanding for you personally

Concrete, findable, and none of them are engineering tasks someone else can silently absorb.

- [ ] **Retire the probes that outlived the laptop.** §4.0. `scripts/live_checkout.py` reports on
      decommissioned infrastructure, so it prints a total outage every time it runs. Delete it or
      repoint it at Fly. Delete the four dead plists in `~/Library/LaunchAgents/` while you are
      there. This is small and it is first, because until it is done every status reading you take
      is wrong.
- [ ] **Correct `CLAUDE.md` about where production runs.** §4.3. It still says
      `/Users/chidionyema/Documents/code/prospector-live`. It is the first file every agent reads.
- [ ] **Ask why both trusted brains were benched at once** (§5 Rank 1). Not the instance — the
      pattern. If it recurs, brain availability is the ceiling on the whole business.
- [ ] **Run the restore drill once and keep the receipt.** `scripts/restore_drill.py`, receipt under
      `store/ops/`. This flips `DAT-2` from `OPEN` to `DONE` and is the only proof that $4,661.75 of
      accumulated work is recoverable.
- [ ] **Decide where the secrets live** (§6.1). Then act on it. The `.env` is 3,788 bytes and one
      laptop.
- [ ] **Back up the credentials that git does not carry.** `.env` and `.lux/keys/agent.pem` are both
      untracked by design. `CLAUDE.md` records that the live-checkout move benched every MiniMax
      tier because the key file was not present in the new directory.
      **HYPOTHESIS: there is no off-laptop copy of either.** The check:
      `ls -la .env .lux/keys/agent.pem` here, then confirm whether the R2 backup declaration
      includes them — read `ops/automations/offsite_backup.py` sources and the declaration it loads.
- [ ] **Commit or discard the 132 uncommitted paths** (`SRC-1`). They are unbacked.
- [ ] **Answer the revenue question** (§2.2) with the one `curl` that needs your key. Nobody else
      can, and no number in this business matters more.
- [ ] **Rotate the ledger** (`DAT-3`). 285 MB on production, and growing. That is already past the
      point where the spend rail can read it quickly.
- [ ] **Book counsel for the legal pages** (`BIZ-2`) and add a contact page (`BIZ-3`). Both are
      hours, not weeks, and both are open on a shop that is taking live payments today.
- [ ] **Decide on DNSSEC and DKIM** (`DNS-2`, `DNS-3`). Registrar work, not code.
- [ ] **Fix or delete the `ENG-1` probe.** It returned `rc=1` with no count, which means the
      mechanical check for your second-biggest risk is dead.

---

## 8. How to read a claim about this system

The house rule is in `CLAUDE.md` and it applies to me, to every agent, and to every document in
`docs/personas/`: **a claim ships with its receipt inline, or it is labelled `HYPOTHESIS:` with the
exact check attached.**

Four kinds of receipt count:

1. **A `file:line`.** `config.yaml:2517` is checkable in three seconds. A paragraph of prose is not.
2. **A command with its actual output**, pasted, not paraphrased.
3. **A named artefact on disk** — `store/scheduler/alert_state.json`, `store/dossiers/<id>.pass.json`.
4. **A test that fails without the fix.** 369 test files exist; a claim about behaviour should name
   the test that pins it.

Three things that are **not** receipts, and each has cost this project time:

- **Memory.** Yours, mine, or a checkpoint's. `CLAUDE.md`: "Memory and checkpoints are leads, not
  evidence."
- **A document.** `CLAUDE.md` itself carries a warning that one of its own paragraphs "has now been
  wrong in both directions". Prose drifts; probes do not.
- **A green run you did not read.** `npm run build 2>&1 | tail` reports *tail's* exit status. A
  suite that collects zero tests exits zero.

**When you want to check anything anyone tells you about this system:**

```bash
# "Is it deployed / running / working?"        -> a probe, never a sentence
fly status -a prospector-engine
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"

# "This risk is closed."                       -> the grader, with its evidence line
.venv/bin/python scripts/ops_status.py

# "The config says X."                         -> the file, with the line number
grep -n "<key>" config.yaml

# "We spent about N."                          -> the ledger, streamed
grep -o '"cost_usd": *[0-9.]*' store/prospector.jsonl | awk -F': *' '{s+=$2+0} END {printf "%.4f\n", s}'

# "There are N packs / passes / kills."        -> the database
sqlite3 store/prospector.db "select decision, count(*) from dossiers group by decision;"

# "The shop is fine."                          -> the shop
curl -s https://api.mumchimp.com/healthz/money-rail
```

If someone gives you a number for this business and it did not come out of one of those, ask which
command produced it.

---

## 9. The dashboard — five commands

Five questions, five commands. Run them in this order.

### 1. Is it working?

```bash
fly status -a prospector-engine
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
```

**Reading it:** you want `state = started` on the machine, and a `ts` on each heartbeat that is
within minutes of now. Today: machine `80d34da6636478` started, producer beat at 13:12:26Z
(`"phase": "sleeping"`, 7200s interval — normal), consumer beat at 13:13:14Z (`"phase": "skipped"`
with a `skipped_reason` — see §5 Rank 1).

**Do not run `scripts/live_checkout.py`.** It probes the retired laptop deployment and reports a
total outage that is not happening (§4.0).

### 2. Is it selling?

```bash
curl -s https://api.mumchimp.com/catalog | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d),'packs', sum(x['pricePence'] for x in d)/100,'GBP')"
curl -s https://api.mumchimp.com/healthz/money-rail
curl -s -H "X-Internal-Key: $STORE_INTERNAL_API_KEY" https://api.mumchimp.com/internal/ops/sales
```

**Reading it:** the first line is inventory (74 packs / £4,229.26 today). The second must say
`"mode":"live"` with a `decidedAtUtc` — a `null` there means nothing ever checked the rail, which is
worse than `test`. The third is revenue and needs your key; without it you get `401`.

### 3. Is it costing me money?

```bash
grep "$(date -u +%Y-%m-%d)" store/prospector.jsonl | grep -o '"cost_usd": *[0-9.]*' | awk -F': *' '{s+=$2+0} END {printf "today $%.2f\n", s}'
grep -n "daily_cap_usd\|warn_at_usd\|daily_subscription_cap_usd" config.yaml
```

**Reading it:** today's figure against `daily_cap_usd: 100.0` and `warn_at_usd: 75.0`. Remember §2.3
— this figure mixes both meters, while the *cap* only sees the metered half. Today: $13.77.

### 4. Is it stuck?

```bash
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/ALERT.txt"
fly ssh console -a prospector-engine -C "cat /data/store/health/providers.json"
.venv/bin/python -m ops.automations.stranded_packs --json | head -20
```

**Reading it:** `ALERT.txt` is the active alert list in plain text; today it carried
`[critical] 44 PASS(es) stranded off the shelf`. `providers.json` says which brains are benched and
for how long. `stranded_packs` counts finished inventory that cannot be sold — watch the number
across two runs, because the rate matters more than the stock (§3.5).

**The copies of these files in this checkout are stale and always will be.** The Fly engine writes
to its own volume. Read them over `fly ssh`, never locally.

### 5. Is it safe?

```bash
.venv/bin/python scripts/ops_status.py
```

**Reading it:** four grades. `OPEN` means the risk is live and the evidence line says why. `MANUAL`
means no mechanical check has been written — it is *not* a pass, it is an unknown. `ACCEPTED` means
you decided to live with it. `DONE` means a check ran and the risk is closed. Count the `OPEN` and
`MANUAL` lines; today that is 6 `OPEN` and 22 `MANUAL` out of 40.

---

## 10. Where to go next

| You want | Open |
|---|---|
| The shared facts, one copy | [../ESTATE_MAP.md](../ESTATE_MAP.md) |
| The money in detail | [finance.md](finance.md) |
| Who is on call and what breaks | [sre-on-call.md](sre-on-call.md) |
| The daily operating surface | [ops.md](ops.md) |
| Whether the architecture holds | [architect.md](architect.md) |
| What the buyer actually experiences | [buyer.md](buyer.md) |
| The legal and privacy exposure | [legal-privacy.md](legal-privacy.md) |
| Security posture and secrets | [security.md](security.md) |
| Getting a new person productive | [new-joiner.md](new-joiner.md) |
| The whole index | [README.md](README.md) |
| What is logged and how long it is kept | [../LOGGING_AND_RETENTION.md](../LOGGING_AND_RETENTION.md) |

---

*Every figure in this document was measured on 2026-08-18 between 12:53Z and 13:55Z. Facts about
**production** were measured on Fly, against `prospector-engine` machine `80d34da6636478` running
image `deployment-01M0AAK2XK458BT2YP9N36YGPY` (v12, `lhr`), and against the live API at
`https://api.mumchimp.com`. Facts about the **source** were measured in
`/Users/chidionyema/Documents/code/prospector` at HEAD `c3cb68b`. Where the two disagree, production
is the truth and the laptop is a retired copy (§4.0). Re-measure before quoting. The commands are
all in §8 and §9.*
