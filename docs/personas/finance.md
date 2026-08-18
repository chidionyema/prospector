# Finance

**What this is.** The complete money picture of the Prospector estate from both sides: every rail
that spends, every rail that earns, what each one can and cannot see, and the arithmetic that joins
them.
**Read this if** you need to know what a month costs, what a pack sells for and why, where a
number came from, or which meter is lying to you.
**Do not read this to learn how to run the daemon.** That is [`ops.md`](./ops.md). This file assumes
the machine runs and asks what it costs.

Every claim below carries a `file:line`, a config key with its line number, or a command with the
output it actually produced. **Everything measured was measured on 2026-08-18 on this machine**
unless a date is stated. Where a number could not be proved, the line starts with `HYPOTHESIS:` and
names the check that would settle it.

Siblings worth reading instead of duplicating them here:

- [`../ESTATE_MAP.md`](../ESTATE_MAP.md) — what runs and where. This file assumes it.
- [`../COST_PROGRAM.md`](../COST_PROGRAM.md) — the tracked cost programme. Every lever, every
  retired number. **Append measurements there, not here.**
- [`analyst.md`](./analyst.md) — the funnel and whether a number can be trusted.
- [`product-manager.md`](./product-manager.md) — what the money buys: the pack, the funnel, the
  lanes. The revenue side of this file stops at the price; that file starts at the product.
- [`ops.md`](./ops.md) — the buttons that change the numbers below.
- [`buyer.md`](./buyer.md) — the same money path from the other side of the counter.

---

## 0. The answer in six numbers

Every one of these was produced by a command in this document. None is an estimate.

| Question | Number | Where §|
|---|---|---|
| Real invoiced money spent, all time | **$120.64** across 33,553 ledger rows | §4.1 |
| Subscription-equivalent burn, all time | **$4,546.72** across 19,520 ledger rows | §4.1 |
| Share of consumption the liability cap can see | **2.6%** | §4.2 |
| Cost to vet one candidate (2026-08-04..18, n=1,823) | **$0.0273** metered, **$1.87** subscription-equivalent | §7.1 |
| Cost to produce one sellable pack (same window, 75 PASS) | **$0.66** metered, **$45.44** subscription-equivalent | §7.2 |
| Mean price of a pack on the live shelf (74 rows) | **£57.15** | §5.6 |

The headline: **the metered rail is real but tiny; the subscription rail is 37x larger and has no
ceiling armed.** A pack costs roughly $46 of model time to produce and lists at roughly $77. That
margin is real only if the pack sells, and there is **no sales figure in this document** because
this repo holds no receipt of one — see §7.4.

---

## 1. Complete inventory: the cost side

### 1.1 The `spend:` config block, key by key

`config.yaml:2506` opens the block. Every key, its live value, and what it actually does:

| Key | Line | Live value | Enforced? | What it governs |
|---|---|---|---|---|
| `spend.daily_cap_usd` | `config.yaml:2517` | `100.0` | **YES** | Hard stop. Metered API dollars only. Raised 20.0 → 100.0 on 2026-08-16. |
| `spend.warn_at_usd` | `config.yaml:2520` | `75.0` | report only | Soft warning at 75% of cap. Held at 75% deliberately; a warn at 15% of cap fires daily and stops being a warning. |
| `spend.daily_subscription_cap_usd` | `config.yaml:2528` | `0.0` | **NO — 0 = off** | Hard wall on Claude Code CLI burn. Never armed. |
| `spend.daily_subscription_soft_cap_usd` | `config.yaml:2541` | `0.0` | **NO — 0 = off** | Soft version: skips generation, keeps the drain running. Never armed. |

The two subscription keys are different mechanisms and the difference is the whole point.
`daily_subscription_cap_usd` refuses the **entire tick**, and `run_tick` returns on `not can_run`
**before** the drain — so arming it freezes the backlog. `config.yaml:2529-2535` records why that is
worse than not arming it: a frozen backlog does not save the spend, it defers it, because every
unresolved row still owes a full re-vet. `daily_subscription_soft_cap_usd` stops digging and keeps
resolving, so the backlog goes **down** while it is engaged and it releases itself at midnight.

Two adjacent rails that also stop spend, documented in full in [`ops.md`](./ops.md):

| Rail | Where read | Effect |
|---|---|---|
| `store/scheduler/PAUSE` | `prospector/scheduler/guard.py:66` (`PAUSE_FILENAME`), checked in `evaluate()` at `guard.py:347` | Halts the whole tick, generation **and** drain |
| `store/scheduler/PAUSE_GENERATION` | `prospector/scheduler/run_scheduled.py` (`_GENERATION_PAUSE_FILENAME`) | Halts generation only; the drain keeps paying the backlog down |

### 1.2 The ledger

One file. It is the only durable record of spend.

```
$ wc -lc store/prospector.jsonl
  907556 270224298 store/prospector.jsonl
```

907,556 rows, 270,224,298 bytes (258 MiB). One JSON object per line.

`prospector/scheduler/guard.py:6-16` states why the ledger and not in-process telemetry: the daemon
and every per-tick subprocess may be a fresh process whose in-memory counter is ~0, which would make
the cap never fire. Reading the on-disk ledger is correct across restarts.

Row shape, by `event` tag, measured over the whole file:

| `event` | Rows | Carries | Counted by the cap? |
|---|---|---|---|
| *(absent)* | 477,687 | — | no |
| `latency` | 396,316 | timings | no |
| `spend` | **33,553** | `amount_usd`, `provider`, `phase`, `stage`, `priced` | **YES** |
| *(absent, but carries `cost_usd`)* | **19,520** | `cost_usd` — the Claude Code CLI's own billed figure | **NO** |

The last two rows are the entire story of §1.3. A verbatim `spend` row:

```json
{"timestamp": "2026-06-15 00:48:42,120", "level": "INFO", "name": "prospector",
 "message": "Spend accumulated", "event": "spend", "amount_usd": 0.01,
 "total_usd": 0.01, "phase": "signal_pipeline"}
```

**Trap, and it cost me a wrong number in this session.** The money field is `amount_usd`, not
`cost_usd`. Summing `cost_usd` over `event == "spend"` rows returns **exactly $0.00** — the two key
names never co-occur. My first scan reported `total metered spend USD 0.0000 over 33553 spend rows`
before I read a row. Memory `never-hand-parse-the-spend-ladger` records the same class of mistake.
Use the production reader (§1.6), not a hand-written parser.

### 1.3 What is metered and what is invisible

`prospector/scheduler/guard.py:21-45` is the canonical statement and it is worth reading in the
source. The short version:

- The cap counts **only** rows tagged `event: "spend"`. They are emitted by
  `prospector/telemetry.py:305-317`, and only when the provider has a non-zero entry in the pricing
  table — i.e. metered API providers billed in real dollars.
- The Claude Code CLI is not one of them. `claude_cli.py:_record_claude_usage` logs the CLI's billed
  figure under `cost_usd` on a row **with no `event` key at all**, so `guard.py`'s loop skips every
  one.

Measured over the whole ledger today:

| Leg | Total | Rows | Share |
|---|---|---|---|
| Metered (`event: spend`, `amount_usd`) | **$120.6410** | 33,553 | **2.6%** |
| Subscription-equivalent (`cost_usd`, untagged) | **$4,546.72** | 19,520 | **97.4%** |

`guard.py:29-34` records the same measurement made on 2026-08-05, when it was $1.64 against $71.94 —
the rail bounded 2% of the day's model consumption while the probe printed `$1.64 of $20.00`.
Sixteen days later the ratio has not moved.

**This is not a broken liability rail, and the distinction matters for how you read the cap.** CLI
usage runs inside the Claude Code subscription (CLAUDE.md: "no hosted service / no API-key calls
beyond this repo"), so `cost_usd` there is an API-equivalent estimate, not invoiced money. Folding it
into `daily_cap_usd` would halt the daemon within about two hours of every day for spend that is
never billed (`guard.py:36-39`). The defect that was fixed was **reporting a 2% number as if it were
100%**; the guard now measures and reports both legs (`guard.py:399-404`).

### 1.4 Per-provider price table

Two tables exist and only one is usually consulted.

**Fallback, in code** — `prospector/telemetry.py:186-196`, USD per 1M tokens:

| Provider | Input | Output | `telemetry.py` line |
|---|---|---|---|
| `claude` | 3.00 | 15.00 | :187 |
| `deepseek` | 0.27 | 1.10 | :188 |
| `minimax` | 0.30 | 0.30 | :189 (flat rate, M2.7/M3) |
| `minimax_m27` | 0.30 | 0.30 | :194 |
| `ollama` | 0.00 | 0.00 | :195 |
| `mock` | 0.00 | 0.00 | :196 |

`claude_cli` is **deliberately absent** from this table. `telemetry.py:293-294` names the test that
pins it: `tests/unit/test_scheduler_resume_drain.py::test_pricing_claude_cli_would_arm_the_metered_cap`.
Adding a rate for `claude_cli` would newly and wrongly count subscription burn as metered spend and
halt the daemon on money nobody invoices.

**Canonical, in config** — `config.yaml`'s `pricing:` block, consumed through
`telemetry.get_price(provider, cfg)` at `telemetry.py:295`. Only a caller that passes `cfg` gets the
config-aware path. `telemetry.py:284-291` records that today **there is no such caller**: the only
one was `standardcompute`, removed 2026-08-15. The branch survives as the contract any new metered
provider must use.

**The receipt that this mattered.** `standardcompute` was once the head of `run.py`'s non-critical
chain and had no entry in `PRICING`, so every call priced at $0. On disk right now:

```
standardcompute/standardcompute  $   0.0000    1017 rows
```

1,017 metered calls that could never move `daily_cap_usd`'s sum no matter how many were made. That
is ENGINE_AUDIT_2026-08-10 HIGH finding 4, still visible in the ledger as a permanent scar.

`telemetry.py:295-303` is the fix: a provider missing from `cfg.pricing` now **warns loudly** and
logs the spend event at $0 rather than dropping it, so the only way to silence it is to enter a real
rate.

### 1.5 The operator roster — who spends, and on what authority

| Config key | Line | Live value | Metered? | Role |
|---|---|---|---|---|
| `operator` | `config.yaml:58` | `[minimax, claude_cli]` | minimax yes, claude_cli no | The moat verdict chain |
| `moat_primary` | `config.yaml:81` | `[minimax, claude_cli]` | — | Who may rule FINALLY |
| `noncritical_operator` | `config.yaml:136` | `[minimax, minimax_m27]` | yes | Generation, prescreen, score |
| `artifact_operator` | `config.yaml:145` | `[claude_cli, minimax]` | subscription first | Pack prose |
| `marketing_operator` | `config.yaml:157` | `[minimax, claude_cli]` | cheap first | Shelf copy |
| `minimax_concurrency` | `config.yaml:401` | `8` | — | Process-global semaphore; measured clean at 16/16, zero 429s |

Model ids: `config.yaml:201` `deepseek: "deepseek-v4-pro"`, `:202` `minimax: "MiniMax-M3"`,
`:203` `minimax_m27: "MiniMax-M2.7"`.

Adapter classes, all in `prospector/operator.py`:

| Class | Line | Base URL | Key env var | Model default |
|---|---|---|---|---|
| `Operator` (ABC) | :291 | — | — | — |
| `GeminiOperator` | :390 | google genai SDK | `GEMINI_API_KEY` (:397) | `gemini-2.0-flash` (:393) |
| `MiniMaxOperator` | :592 | `https://api.minimax.io/v1` (:657) | `MINIMAX_API_KEY` (:663) | `MiniMax-M3` (:672) / `MiniMax-M2.7` (:673) |
| `DeepSeekOperator` | :849 | `https://api.deepseek.com/v1` (:872) | `DEEPSEEK_API_KEY` (:876) | `deepseek-chat` (:883) |
| `OpenRouterOperator` | :970 | `https://openrouter.ai/api/v1` (:998) | `OPENROUTER_API_KEY` (:1006) | rotating |
| `OllamaOperator` | :1269 | `http://localhost:11434/v1` (:1277) | — (local) | `qwen2.5-coder:7b` (:1283) |
| `MockOperator` | :1341 | — | — | zero spend |
| `FallbackOperator` | :1516 | — | — | chain + circuit breaker |

The trust fence, which is a **cost** control as much as a quality one:
`operator.py:1443` `moat_primary()`, `:1405` `MOAT_PRIMARY_DEFAULT = frozenset({"claude_cli"})`,
`:1509` `is_provisional_provider(name) -> name not in moat_primary()`. Anything outside the set that
rules is stamped `provisional`, never publishes on PASS, and is **auto re-vetted** — which means a
provisional verdict costs the money twice. That is an accepted cost (founder directive 2026-08-08),
not an oversight; the arithmetic is in the project CLAUDE.md.

### 1.6 Readers — never hand-parse the ledger

| Tool | Path | What it prints |
|---|---|---|
| Production reader | `prospector/scheduler/guard.py:108` `SchedulerGuard` | `scan_today()` → `(metered, subscription, newest_day)`; `spend_by_day()` for a window |
| Spend view | `prospector/ops/spend.py:299` `spend_view(cfg)` | Both legs, projections, per-tier and per-role split |
| CLI | `tools/spend_today.py` | Today against the cap. Registered as a console button at `prospector/ops/console_api.py:2250`, route `/spend` |
| Standing $/vetted receipt | `tools/experiments/w02_standing_receipt.py` | $/vetted over a window, both legs |
| Console | `prospector/ops/console_api.py:342` | `warn_at_usd` on the money page |
| Config surface | `prospector/ops/console_api.py:1182`, `:1186` | `spend.daily_cap_usd` and `spend.warn_at_usd` editable from the console, group `money` |

Key constants in `prospector/ops/spend.py`: `:54` `CAP_KEY`, `:55` `WARN_KEY`, `:56`
`SUBSCRIPTION_CAP_KEY`, `:61` `MIN_ELAPSED_H = 1.0`, `:68`
`SUBSCRIPTION_TIERS = frozenset({"claude_cli"})`.

---

## 2. How it actually works, path A: one dollar from a model call to the daily cap

Nine hops. Every one is a `file:line`.

| # | Hop | Where |
|---|---|---|
| 1 | An adapter completes a call and knows its token counts | `prospector/operator.py:592` (`MiniMaxOperator`) or `:849` (`DeepSeekOperator`) |
| 2 | It calls `record_usage(...)` with provider, tokens, phase, stage | `prospector/telemetry.py` |
| 3 | Token counters accumulate per provider | `telemetry.py:270-274` |
| 4 | The rate is resolved — **config first if `cfg` was passed**, module table otherwise | `telemetry.py:295` `get_price(root_provider, cfg=cfg)` |
| 5 | Cost is computed: `in*rate_in/1e6 + out*rate_out/1e6` | `telemetry.py:296` |
| 6 | An unpriced provider **warns** rather than silently vanishing | `telemetry.py:299-303` |
| 7 | A row is appended with `"event": "spend"` and `"amount_usd": cost` | `telemetry.py:305-317` |
| 8 | The row lands in `store/prospector.jsonl` via `route_logs_to_file` | `guard.py:14-16` |
| 9 | Next tick, `SchedulerGuard._scan` sums today's bucket and `evaluate()` rules | `guard.py:244-284`, `:346` |

**Where hop 9 refuses to run at all.** `evaluate()` has four exits, in this order:

| Order | Condition | Line | Reason string |
|---|---|---|---|
| 1 | `PAUSE` file present | `guard.py:353-354` | `paused: <path> present` |
| 2 | **Clock is behind the ledger** | `guard.py:355-386` | `clock is behind the ledger: today reads X but this store already has rows dated Y` |
| 3 | `spend >= daily_cap_usd` | `guard.py:388-390` | `daily cap reached: $X >= $100.00` |
| 4 | `sub_cap > 0 and subscription >= sub_cap` | `guard.py:392-397` | `daily subscription cap reached … (subscription-equivalent, not billed)` |
| — | otherwise | `guard.py:399-404` | `ok: $X of $100.00 spent today (+$Y subscription-equivalent, uncapped)` |

Exit 2 is the one nobody expects and it is a **money** gate, not a clock gate. `guard.py:357-372`
records the incident: with `today=1970-01-01` the live ledger reports `$0.0000` and `can_run=True` —
that is not a degraded cap, it is no cap. `store/scheduler/ticks.jsonl` carries 110 ticks spanning
1970-01-01..03, all reporting `$0.0000 of $20.00 spent today`. The guard now refuses to generate
rather than spend behind a dead rail.

`guard.py:373-377` states the limit honestly: **only backwards skew is detectable.** A clock set
forward zeroes the window just as effectively and nothing on this machine can refute it. That gap
needs a trusted time source and the gate deliberately does not pretend to cover it.

**The scan is incremental, and that is a money property.** `guard.py:68-85`: a checkpoint at
`store/scheduler/spend_scan.cache.json` (`SCAN_CACHE_FILENAME`, `:70`) holds byte offsets and 30 days
of per-day totals (`_SCAN_CACHE_DAYS = 30`, `:77`). `_HEAD_PROBE_BYTES = 4096` (`:81`) fingerprints
the ledger head — if it changes, the file was rotated and every cached offset is meaningless, so the
scan resets. `PROSPECTOR_GUARD_FULL_SCAN=1` (`:85`) bypasses the cache entirely, because a money rail
must always have a way to get the uncached figure without editing code.

**Overshoot is bounded and intended.** `guard.py:18-19`: the ceiling is a pre-run check, so a single
in-flight batch can overshoot by at most one batch's worth of spend, bounded by
`schedule.batch_size` (`config.yaml:2353`, live value **50**).

---

## 3. How it actually works, path B: a price from candidate to charged card to delivered file

Fourteen hops across two languages and three services.

### 3.1 Engine side — the price is decided exactly once

| # | Hop | Where |
|---|---|---|
| 1 | A PASS dossier reaches the publish routine | `prospector/bridge.py:683` `EngineBridge.publish_pass` |
| 2 | Content gates run: pack complete, bundle complete, lint, claims | `bridge.py:683-1255` |
| 3 | **Dry-run exits HERE, before any money object exists** | `bridge.py:1256-1272` |
| 4 | The price is decided **once** | `bridge.py:1284` `price = price_for(...)` |
| 5 | The source count passed in is the same integer the row publishes as `sourceCount` | `bridge.py:1290-1294`, via `_trust_fields` |
| 6 | The rung is chosen and logged with its rationale | `bridge.py:1296-1300` |
| 7 | A provider Product is minted | `bridge.py:1400-1404` |
| 8 | A provider Price is minted **from that same decision** | `bridge.py:1407-1416` (`amount_pence=price.price_pence`, `usd_cents=price.price_usd_cents`) |
| 9 | The deliverable is uploaded to R2, content-addressed by SHA-256 | `bridge.py:1444-1450` (`packs/{id}/{hash}.zip`) |
| 10 | Sellability: a `price_stub_*` id means **publish UNLISTED** | `bridge.py:1466-1471` |
| 11 | The catalogue row is written from the **same** `PriceDecision` | `bridge.py:2147-2175` (`providerPriceId` at `:2171`, price at `:2173`) |
| 12 | A listing receipt lands on disk | `publish/publish.py:85` `_write_listing` → `store/listings/<id>.json` |

**Why steps 4, 8 and 11 must be one decision.** `bridge.py:1274-1280` states it: the fulfilment
fence compares what the buyer paid against the catalogue's floor. A provider Price minted at one
number and a catalogue row written at another is a pack that **charges correctly and then refuses to
deliver**. Both read the single `price` variable, so drift is structurally impossible rather than
merely unlikely.

`bridge.py:1560` `_resolve_money_rail` is the second half of the same property: it keeps a pack that
is already on sale on the exact price it sells at. `bridge.py:1571-1576` names the defect it closed —
`publish_pass` used to mint a new provider Product and Price on every republish while
`Store.Api/Program.cs:490` updated `ProviderPriceId` unconditionally, re-pointing a live pack at a
fresh Stripe object.

Step 3's placement is deliberate and load-bearing: `bridge.py:1256-1262` says returning on that line
is what makes "a dry run cannot mint an orphan" a property of control flow rather than of a caller
remembering a flag. `config.yaml:2378-2381` relies on it — the daemon's re-gate rehearsal calls no
model and mints nothing.

### 3.2 Store side — the buyer pays and receives

| # | Hop | Where |
|---|---|---|
| 13 | The storefront fetches the catalogue | `store_platform/src/Store.Web/src/pages/index.tsx:2316` |
| 14 | The API serves it | `store_platform/src/Store.Api/Program.cs:258` (`MapGet("/catalog")`), DTO projected at `:283-326` |
| 15 | A row is rendered | `store_platform/src/Store.Web/src/components/discovery/PackRow.tsx:45` |
| 16 | Product page fetches detail | `Store.Web/src/pages/pack/[id].tsx:1728` → `Program.cs:332` |
| 17 | Checkout opens a session | `Store.Api/Endpoints/CheckoutEndpoints.cs:147` |
| 18 | Stripe Checkout Session created | `Store.Api/Payments/StripeProvider.cs:317` |
| 19 | The line item uses the pack's `ProviderPriceId` | `StripeProvider.cs:408` — `Price = line.ProviderPriceId` |
| 20 | Webhook received | `Store.Api/Endpoints/WebhookEndpoints.cs:13` |
| 21 | Signature verified | `WebhookEndpoints.cs:34` |
| 22 | Fulfilment invoked | `WebhookEndpoints.cs:56` |
| 23 | **THE FULFILMENT FENCE** | `Store.Api/Services/FulfilmentService.cs:133`, comparison at `:141` |
| 24 | Download link issued, presigned, 5-minute TTL | `Store.Api/Endpoints/DeliveryEndpoints.cs:19` (`DownloadUrlTtl = TimeSpan.FromMinutes(5)`), `:258` |

Hop 23 is where the whole engine-side discipline is cashed in:

```csharp
// FulfilmentService.cs:141
return item.AmountPence < floor ? $"{item.ProductId} (paid {item.AmountPence} < floor {floor} {currency})" : null;
```

The floor comes from `Store.Catalog/Domain/Pack.cs:82` `EffectiveFloorMinorUnits(currency, now)`,
which is **per-currency and never converted** — `FulfilmentService.cs:17` says a payment is judged in
the currency it was charged in. A pack with no USD floor cannot be billed in USD at all. That is why
`PriceDecision.price_usd_cents` returning `None` is safe rather than a gap
(`prospector/pricing.py:55-62`).

Price changes are attributable: `Store.Catalog/Domain/PackPriceHistory.cs:21` records them, written
at `Program.cs:1191`, read at `Program.cs:1311` and `:1347`, served by `GetPackPriceHistory`
(`Program.cs:1409`). `Program.cs:1263` states the purpose — a sale can be attributed to the price the
buyer was actually shown. `Program.cs:556` names the failure it closed: a price change that left no
trace, no history row, no floor move, `changeCount` still 0.

Rate limiting on the money path: `Store.Api/Infrastructure/RateLimitPolicy.cs:48`
`DefaultPermitPerMinute = 120`, `:51` `DefaultWaitlistPermitPerMinute = 5`, fixed-window with
`QueueLimit = 0` at `:84-91`, registered at `Program.cs:228`.

---

## 4. The numbers, and the command that produced each

### 4.1 All-time spend, both legs

```bash
python3 -c "
import json,collections
sp=0.0; sub=0.0; n=0; m=0
for line in open('store/prospector.jsonl'):
    r=json.loads(line)
    if r.get('event')=='spend': sp+=float(r.get('amount_usd') or 0); n+=1
    elif 'cost_usd' in r: sub+=float(r.get('cost_usd') or 0); m+=1
print(f'metered \${sp:.4f} / {n} rows;  subscription \${sub:.2f} / {m} rows')"
```

```
metered $120.6410 / 33553 rows;  subscription $4546.72 / 19520 rows
```

### 4.2 Metered spend by provider, all time

| Provider (as tagged in the ledger) | USD | Rows |
|---|---:|---:|
| `minimax/MiniMax-M3` | 47.8779 | 17,196 |
| `deepseek/deepseek-v4-pro` | 41.0944 | 11,337 |
| *(no `provider` field)* | 30.4600 | 3,046 |
| `deepseek/deepseek-chat` | 0.9254 | 755 |
| `minimax/MiniMax-M2.7` | 0.2525 | 56 |
| `gemini/gemini-2.5-flash` | 0.0307 | 92 |
| `gemini/gemini-2.5-flash-lite` | 0.0002 | 3 |
| `minimax` (bare) | 0.0000 | 51 |
| `standardcompute/standardcompute` | **0.0000** | **1,017** |
| **Total** | **120.6410** | **33,553** |

Three findings sit in that table and none is cosmetic:

1. **$30.46 across 3,046 rows carries no provider tag** — 25% of all metered spend is
   unattributable. `telemetry.py:311` sets `"provider": provider`, so these rows predate that field.
   You cannot answer "which brain cost us the most" for a quarter of the money.
2. **`standardcompute` made 1,017 calls at $0.00.** The audit scar of §1.4.
3. **`gemini` spent real money** ($0.0309 across 95 rows) despite the project CLAUDE.md stating
   "Gemini is gone (no `gemini` key in `config.yaml`)". The adapter still exists at
   `operator.py:390`. The spend is historic, not current — HYPOTHESIS: no gemini row is newer than
   the config removal. Check: filter the ledger for `provider` starting `gemini` and print
   `max(timestamp)`.

### 4.3 Metered spend by day, last 16 days with data

| Day | Metered | Rows |
|---|---:|---:|
| 2026-08-01 | $6.0308 | 1,156 |
| 2026-08-02 | $1.6379 | 317 |
| 2026-08-04 | $0.7809 | 233 |
| 2026-08-05 | $1.6400 | 370 |
| 2026-08-06 | $4.4618 | 1,002 |
| 2026-08-07 | $1.0456 | 137 |
| 2026-08-08 | $1.3578 | 136 |
| 2026-08-09 | $0.5900 | 59 |
| 2026-08-10 | $1.3856 | 140 |
| 2026-08-11 | $0.6925 | 172 |
| 2026-08-13 | $1.0520 | 1,236 |
| 2026-08-14 | $4.0817 | 655 |
| 2026-08-15 | $8.4681 | 1,718 |
| 2026-08-16 | **$12.9062** | 5,012 |
| 2026-08-17 | $10.3311 | 4,441 |
| 2026-08-18 (partial) | $1.0147 | 498 |

Peak day is **$12.91 against a $100.00 cap — 12.9% of the ceiling.** `config.yaml:2508-2516`
justified the 20 → 100 raise on an 8x rise in four days; that trend did not continue. At the current
peak the cap has **7.7x of headroom** and cannot bind. It is a liability ceiling, not a control.

### 4.4 Subscription burn by day

| Day | Subscription-equivalent | Rows |
|---|---:|---:|
| 2026-08-06 | **$693.07** | 2,789 |
| 2026-08-07 | $417.66 | 1,974 |
| 2026-08-08 | $461.04 | 2,171 |
| 2026-08-09 | $188.11 | 1,384 |
| 2026-08-10 | $419.13 | 2,284 |
| 2026-08-11 | $114.80 | 572 |
| 2026-08-13 | $155.53 | 866 |
| 2026-08-14 | $294.85 | 1,039 |
| 2026-08-15 | $258.89 | 732 |
| 2026-08-16 | $241.10 | 735 |
| 2026-08-17 | $78.16 | 214 |
| 2026-08-18 (partial) | $13.77 | 45 |

`docs/COST_PROGRAM.md:137` independently records **$927.00** for 2026-08-06 from the Claude Code
transcripts, against $693.07 from this ledger. The two measure different populations — the transcript
audit sees every session on the machine, the engine ledger sees only what routed through
`route_logs_to_file`. **Do not add them.** `COST_PROGRAM.md:150-153` lists retired numbers that must
never be quoted: `$1,749.36/day`, `$654.22/day`, `14,398 priced requests`, `$1,765.71`.

The trend is the important part: **$693 → $78 per day over eleven days**, tracking the Opus → Sonnet
default change that `COST_PROGRAM.md:39` prices at 0.601x on every rate.

### 4.5 The cost levers, from the tracked programme

`docs/COST_PROGRAM.md:32` opens §1. Verbatim status, `COST_PROGRAM.md:39-46`:

| # | Lever | Measured value | Status |
|---|---|---|---|
| L1 | Default model Opus → Sonnet | 0.601x steady state = **39.9%**; $344.51/day | **CONFIGURED, NOT LIVE** |
| L2 | Session floor (CLAUDE.md ×2 + MEMORY.md) | 18,294 tok = 41% of every prompt; $0.0055/warm req | PARTIAL |
| L3 | Batching (one round-trip per intent) | headroom ≈ 2,947 requests/day | MEASURED, unenforced |
| L4 | Delegating recon to haiku subagents | ceiling ~4.7% of spend | LIVE |
| L5 | `pi_execute` dispatch | dispatch is unmetered | LIVE, opt-in |
| L6 | Daemon cold-cache gap | $0.2650/req vs $0.0937/req interactive | **UNPINNED** |
| L7 | Dead `ANTHROPIC_API_KEY` in inherited env | outranks the subscription | **NOT CLEARED** |
| L8 | Graphify as a context substitute | injection capped 700 tok; saving **REFUTED** at n=3 | ENFORCED, cost-neutral |

**L1 is the single largest lever in the estate and it is one word on one line.** The global CLAUDE.md
says to verify rather than trust it:

```bash
grep -n '"model"' ~/.claude/settings.json
```

L6 is the one that should worry a finance reader: the daemon pays **2.8x** the interactive rate per
request and the cause is not established. `COST_PROGRAM.md:44` records that the obvious explanation
(fresh cwd per call, memory `fresh-cwd-per-cli-call-pays-cold-cache.md`) is **REFUTED** —
`WorkingDirectory` is stable. At the subscription volumes in §4.4, closing L6 is worth more than
every other lever except L1.

---

## 5. Complete inventory: the revenue side

### 5.1 The ladder, top to bottom

Price is a **rung on a fixed array**, never a computed number. `prospector/pricing.py:3-6` states the
reason: a continuous function produces £63.41 and nobody can say why.

`config.yaml:1829`:

```yaml
rungs: [1999, 2999, 4999, 7999, 9999]
```

| Rung index | Pence | £ | Reached by (tier ladder) | Reached by (depth ladder) |
|---:|---:|---:|---|---|
| 0 | 1999 | £19.99 | — | fewer than 25 cited sources |
| 1 | 2999 | £29.99 | `side_hustle` (`config.yaml:1899`) | 25–29 sources |
| 2 | 4999 | £49.99 | `smb` (`:1900`), **and the unclassified default** (`:1888`) | 30–34 sources |
| 3 | 7999 | £79.99 | `growth` (`:1901`) | 35–44 sources |
| 4 | 9999 | £99.99 | `venture` (`:1902`) — the ceiling | 45+ sources |

The ceiling is a founder decision, 2026-08-15: "i dont think we should have inventory over 99.99"
(`config.yaml:1824-1828`). The £149.99 and £199.99 rungs were **deleted, not merely unused**, so
nothing can route back onto them. That is why `tier_rung_index.venture` had to move 5 → 4 rather than
be silently clamped by `pricing.py:328` — leaving it at 5 would have produced the right price by
accident while config claimed a rung that no longer exists.

### 5.2 The depth bands — the selector that actually runs

`config.yaml:1860`:

```yaml
source_count_bands: [25, 30, 35, 45]
```

Exactly `len(rungs) - 1` strictly-increasing lower edges, or `pricing.py:118` `_usable_bands` refuses
them **loudly** and the tier ladder takes over. Three separate rejections, each naming the rule it
broke: not a list of integers (`pricing.py:135-138`), wrong length (`:140-144`), not strictly
increasing (`:146-149`). `pricing.py:121-123` explains why loud: a malformed band list that quietly
fell back would re-introduce the price inversion while every rationale still read as though depth had
priced the pack.

`pricing.py:153-157` `_band_index` is a sum of edges cleared, so it is **non-decreasing in
`source_count` by construction**. `tests/unit/test_pricing_monotonic.py` pins that property over the
full live range.

When `source_count` is supplied and bands are declared, `pricing.py:260-298` returns outright.
`pricing.py:198-202` states why that exclusivity is deliberate: any second input breaks monotonicity,
because two packs with the same count would sit on different rungs and some pair sorted by depth
would run backwards again. Tier and market stay in the rationale as context, never as arithmetic.

Anchors are explicitly barred from moving a depth rung. `pricing.py:266-272` logs when
`rung_adjust_enabled` is on and anchors are present, then ignores them. `pricing.py:254-258`:
a per-pack ±1 nudge is precisely what re-introduces the inversion.

Bands apply to **unclassified** packs too, unlike the tier ladder's market offset
(`pricing.py:204-205`): a tier is a judgement we may not have made; a source count is a fact about
the pack in hand.

### 5.3 The tier ladder — the fallback

Reached only when the caller does not know the source count. `pricing.py:22-24` names the one such
caller: `verify._check_question`, which asks during the moat, long before a dossier exists.

| Input | Config line | Value |
|---|---|---|
| `default_rung_index` | `config.yaml:1888` | `2` → 4999 |
| `tier_rung_index.side_hustle` | `:1899` | 1 |
| `tier_rung_index.smb` | `:1900` | 2 |
| `tier_rung_index.growth` | `:1901` | 3 |
| `tier_rung_index.venture` | `:1902` | 4 |
| `market_rung_offset.uk` | `:1909` | 0 |
| `market_rung_offset.us` | `:1910` | +1 |

`market` is the jurisdiction the **opportunity** lives in, not the buyer's locale
(`config.yaml:1904-1907`). An offset keeps every output on the ladder; a multiplier would not.

Three safety clamps, all `max(0, min(last_idx, ...))`: `pricing.py:305` (unclassified), `:328`
(base), `:330` (base + offset). `pricing.py:324-327` explains: `tier_rung_index` is read from config,
so a typo like `side_hustle: 99` is a **data edit**, and an unclamped read when building the
rationale would turn that into an `IndexError` on the publish path.

An unclassified pack ignores market entirely (`pricing.py:300-320`): market is not evidence for a
pack we cannot classify.

If no ladder is declared at all, `pricing.py:226-243` holds at `listing.price_pence`
(`config.yaml:1505` = `4999`) rather than raising. `pricing.py:220-225`: this function is on the
publish path, so a config that predates the ladder must degrade to today's behaviour, not take
publishing down.

### 5.4 The USD ladder, and a live defect in it

`config.yaml:1876`:

```yaml
usd_rungs: [2499, 3999, 6999, 10999, 13999, 19999, 26999]
```

Read by `pricing.py:160` `_usd_at(pricing, rung_idx)` at the **same rung position**, never converted
(`pricing.py:161-168`). `config.yaml:1866-1875` gives the reason: a price converted at charge time
makes the charged amount depend on which rate the process happened to read, so a buyer who paid
exactly the price they were shown gets refused by the fulfilment fence whenever the rate moved.

**The defect.** `rungs` has **5** elements; `usd_rungs` has **7**. `config.yaml:1826-1827` states
"This shortens the array from 7 to 5, and every index below is an index into THIS array" — the GBP
array was cut and the USD array was not. `_usd_at` guards with `0 <= rung_idx < len(usd_rungs)`
(`pricing.py:171`), and `rung_idx` is already clamped to `0..4`, so **indices 5 and 6 ($199.99 and
$269.99) are unreachable dead config.**

| Rung | GBP | USD declared | Implied USD/GBP | vs H.10 1.3498 |
|---:|---:|---:|---:|---:|
| 0 | £19.99 | $24.99 | 1.250 | −7.4% |
| 1 | £29.99 | $39.99 | 1.333 | −1.2% |
| 2 | £49.99 | $69.99 | 1.400 | +3.7% |
| 3 | £79.99 | $109.99 | 1.375 | +1.9% |
| 4 | £99.99 | $139.99 | 1.400 | +3.7% |
| **5** | **—** | **$199.99** | **unreachable** | — |
| **6** | **—** | **$269.99** | **unreachable** | — |

All five live rungs sit inside the ±7% band `config.yaml:1868-1869` claims. Rung 0 is at the very
edge at −7.4%, marginally outside it.

**Severity: cosmetic today, a trap tomorrow.** Nothing is mispriced now. But a future edit that adds a
sixth GBP rung silently activates `$199.99`, which nobody has approved and which breaches the £99.99
ceiling in dollars. The fix is one line — truncate `usd_rungs` to 5 elements — and the test that
would catch the class is a length assertion in `tests/unit/`.

Prices are recorded, not merely computed. `prospector/price_rationale.py:104` `build_record`,
`:142` `write_rationale`, `:76` `ladder_snapshot`, `:72` `_digest`. `config.yaml:1883`
`ladder_version: L1-ladder-2026-08-09-charm` is a **label, not the truth** — the record also carries
the rung numbers and a `fingerprint` digest over them, and the fingerprint is what proves which
ladder actually ran. Records live under `store/pricing/rationale/`.

### 5.5 C3 `price_comparables` — the evidence-only seventh check

`prospector/price_comparables.py`, 459 lines. It retrieves what buyers demonstrably already pay.

**It can never kill.** `models.py:107` `PRICING_CHECK = "price_comparables"`, barred structurally in
`kill_filter.is_hard_fail` and in verify's run order rather than by config omission
(`models.py`, comment following `:107`) — because a config edit is a data change that never passes
review as code. `price_comparables.py:9` restates it. The reasoning: "no price page on the open web"
is a fact about the web, not the idea.

| Key | Line | Value | Effect |
|---|---|---|---|
| `comparables.enabled` | `config.yaml:1922` | `true` | Retrieve and extract anchors |
| `comparables.rung_adjust_enabled` | `config.yaml:1927` | **`false`** | Let anchors move a rung. **OFF.** |
| `comparables.queries` | `config.yaml:1942-1945` | 3 templates | See below |
| `comparables.fx_asof` | `config.yaml:1972` | `"2026-08-07"` | Staleness is visible |
| `comparables.fx_source` | `config.yaml:1973` | `"US Federal Reserve H.10, release 2026-08-12"` | Retrievable, dated |
| `comparables.fx_to_gbp` | `config.yaml:1974-1977` | GBP 1.0, USD 0.74085, EUR 0.85635 | Declared, never inferred |
| `comparables.cadence_eligible` | `config.yaml:1982` | `["one_off"]` | Only one-off anchors may move a rung |
| `comparables.min_anchor_pence` | `config.yaml:1986` | `100` | Below £1 is noise |
| `comparables.max_anchor_pence` | `config.yaml:1987` | `500000` | Above £5,000 is a contract value or a market size |
| `comparables.min_anchors` | `config.yaml:1991` | `3` | The bar for "evidence" not "anecdote" |
| `comparables.min_domains` | `config.yaml:1992` | `2` | Three prices off one vendor's page are one data point wearing three hats |

The queries (`config.yaml:1943-1945`):

```yaml
- "{q} pricing how much does it cost"
- "{q} one-off fee fixed price one time purchase"
- "{q} course OR template OR toolkit price"
```

The middle one used to read `"{q} price per month subscription plans"`. `config.yaml:1935-1941`
records the measurement that killed it: **of 361 accepted anchors, 200 were discarded for
`cadence != one_off`** — the largest single loss, ahead of the 47 lost to a missing USD rate. A third
of the retrieval budget was manufacturing the one cadence the gate throws away.

The FX map held **GBP alone** until 2026-08-13. `config.yaml:1955-1962`: of 361 anchors across 116
packs, **146 (40%) were USD and every one carried `amount_pence_gbp: null`**. That interacted badly
with `market_rung_offset: {us: 1}` — a US-market pack was charged one rung more on a taxonomy rule
while the system was structurally unable to read a single US price page as evidence for or against
it.

`config.yaml:1963-1970` is explicit that these rates **go stale and must never bill a buyer**. They
convert *evidence* against a ladder whose narrowest gap is +50% (1999 → 2999), so a few percent of
drift cannot move a rung on its own.

Code path: `price_comparables.py:73` `comparables_config`, `:111` `comparables_queries`,
`:119` `_appears_in` (**every anchor must appear literally in the passage it cites**), `:178`
`to_pence_gbp`, `:196` `extract_anchors`, `:297` `run_price_comparables`, `:383` `anchors_from_tags`,
`:416` `eligible_anchors`, `:431` `anchor_evidence`, threshold check at `:444`.

If `rung_adjust_enabled` were turned on, `pricing.py:72` `_anchor_adjustment` applies three limits
(`pricing.py:79-90`): **one rung maximum**, it must **clear the neighbouring rung outright** (not
"closer to it"), and **never on an unclassified pack**.

**Measured today: the evidence side is producing nothing.**

```bash
python3 -c "
import json,glob
p=n=0
for fp in glob.glob('store/dossiers/*.json'):
    try: d=json.load(open(fp))
    except: continue
    t=(d.get('candidate') or {}).get('tags') or []
    a=[x for x in t if isinstance(x,str) and x.startswith('price_anchor')]
    if a: p+=1; n+=len(a)
print('dossiers carrying price_anchor tags:',p,'anchors:',n)"
```

```
dossiers carrying price_anchor tags: 0 anchors: 0
```

**Zero, across 2,929 dossiers.** `comparables.enabled` is `true` and `anchors_from_tags`
(`price_comparables.py:383`) reads anchors off candidate tags, so either the tag prefix differs from
`price_anchor` or C3 is not running on the current path. The config comments cite 361 anchors across
116 packs as measured on 2026-08-13, so anchors existed then. **HYPOTHESIS: the anchors are stored
under a different tag key or in a sidecar, not on `candidate.tags`.** Check:
`rg -n "price_anchor|anchors_from_tags" prospector/ | head` and read `price_comparables.py:383-414`
for the exact prefix it parses. Until that resolves, treat "16 of 24 recently-vetted ideas carry
cited willingness-to-pay anchors" (`config.yaml:1815-1817`) as **unverified on today's disk**.

### 5.6 What the shelf actually costs, measured live

```bash
curl -s https://api.mumchimp.com/catalog | python3 -c "..."
```

74 rows. Price distribution:

| Price | Rows | Mean `sourceCount` |
|---:|---:|---:|
| 1999 (£19.99) | 2 | 19.5 |
| 2999 (£29.99) | 17 | 36.4 |
| 4999 (£49.99) | 30 | 31.1 |
| 7999 (£79.99) | 16 | 39.8 |
| 9999 (£99.99) | 9 | 36.6 |

- Gross if every row sold exactly once: **422,926p = £4,229.26**
- Mean price: **5,715p = £57.15**
- `sourceCount`: n=74, min 16, p20 26, **median 34**, p80 42, max 51, mean 34.5

**The inversion the depth bands were built to remove is still on the live shelf.** £29.99 packs cite
a mean of **36.4** sources; £49.99 packs cite **31.1**. The cheaper tier is deeper. Measured against
the declared bands:

```
live rows on the declared depth ladder: 26 on-band, 48 off-band
repricing the whole shelf onto source_count_bands is worth 17000p = GBP 170.00
adjacent pairs sorted by sourceCount where the dearer pack cites fewer: 18 of 73
```

**48 of 74 live rows (65%) are not on the ladder config declares.** The 18-of-73 inversion count is
*identical* to the "18 of 58" recorded at `config.yaml:1846` on 2026-08-15 — the shelf has grown by
16 rows and the inversion has not been touched.

This is expected, not a bug: `pricing.py` prices at **listing time**. `config.yaml:1849-1852` and
`bridge.py:1560` `_resolve_money_rail` both keep a live pack on the price it sells at, because
rewriting a catalogue row or a Stripe Price alone charges a buyer an amount the fulfilment fence then
rejects. Bringing the shelf onto the bands is a **separate, deliberate repricing operation** worth
**+£170.00** at today's counts. `config.yaml:1852` estimated **−£330** on 2026-08-15 against 59 rows;
the sign has flipped as newer, deeper packs listed. That is a finance decision nobody has taken.

---

## 6. FinOps: what the estate actually costs to run

### 6.1 Fly.io

Three apps, all `shared-cpu-1x` / `512mb`, all `auto_stop_machines = false`:

| App | Config | Region | Min machines | VM |
|---|---|---|---:|---|
| `prospector-store-api` | `store_platform/deploy/fly/api.fly.toml:20` | `lhr` (`:22`) | 1 (`:58`) | `shared-cpu-1x`, 512mb (`:67-69`) |
| `prospector-store-web` | `store_platform/deploy/fly/web.fly.toml` | — | **2** (`:43`) | `shared-cpu-1x`, 512mb (`:58-60`) |
| `prospector-store-api-staging` | `store_platform/deploy/fly/api.staging.fly.toml:10` | — | 1 (`:40`) | `shared-cpu-1x`, 512mb (`:49-51`) |

**Four always-on machines.** None can scale to zero, and each refusal is documented:

- `api.fly.toml:52-54`: SQLite is a **single-writer** store, so the API must run exactly one machine.
  Never scale the count above 1.
- `api.fly.toml:59-61`: always-on because **Stripe webhooks must reach a live machine**. A cold start
  loses a payment notification.
- `web.fly.toml:35-41`: two warm machines and `auto_stop_machines` off as of 2026-08-15.

Persistent volume: `api.fly.toml:49-51`, `store_data` mounted at `/data`, holding `store.db`.

**HYPOTHESIS: monthly Fly cost.** I did not run a billing command, so I will not put a figure here.
Check, in order:

```bash
fly billing show
fly platform vm-sizes                      # the rate card for shared-cpu-1x
fly volumes list -a prospector-store-api   # the volume GB actually provisioned
fly scale show -a prospector-store-api -a prospector-store-web
```

Four `shared-cpu-1x`/512mb machines plus one small volume is the smallest paid shape Fly offers for
this topology. The staging API is the only one of the four that could be stopped without a design
change; that is a 25% cut on the machine line, available today.

### 6.2 CI — free, and provably so

CI runs on our own Mac. GitHub-hosted runner minutes are metered; **self-hosted minutes are not
metered at all, including on a private repo** (`docs/CI_RUNNER.md:36-38`).

The wiring is a repo variable, not code (`.github/workflows/ci.yml:3-20`):

```yaml
runs-on: ${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}
```

Every job. Seven occurrences: `ci.yml:77, 135, 162, 271, 320, 363, 434`.

Live value:

```bash
$ gh variable list
CI_HEAVY_RUNS_ON   heavy         2026-08-18T01:40:01Z
CI_LIGHT_RUNS_ON   self-hosted   2026-08-18T04:25:17Z
CI_RUNS_ON         self-hosted   2026-08-17T23:37:53Z
CI_UV_CACHE_DIR    /Users/chidionyema/.cache/uv
CI_VENV_ROOT       /Users/chidionyema/.cache/ci-venvs
```

**`CI_RUNS_ON = self-hosted`. GitHub Actions minutes cost is $0.** Moving back is one
`gh variable delete CI_RUNS_ON`, no commit, no review.

Why it moved (`ci.yml:8-13`, `docs/CI_RUNNER.md:19-33`): on 2026-08-16 GitHub stopped starting jobs
entirely — "The job was not started because recent account payments have failed or your spending
limit needs to be increased." Five jobs, zero steps, no logs, conclusion `failure`, on every PR at
once. `gh run view --log-failed` returned nothing, which reads like a passing run rather than a
refused one. The message is only visible on the check-run annotation.

**The cost did not vanish, it moved onto the laptop.** CI minutes are now laptop CPU-hours and
electricity, and they contend with the daemon for the same machine. The project CLAUDE.md records the
gate's own measured cost: **1.7s of ruff plus 445.5s of pytest (3,925 passed, 3 skipped)** on clean
`main`, and **1,281.41s (4,612 passed, 3 skipped)** on a merged tree while four CI jobs shared the
box. That is 21 minutes of one Mac, per gate run.

Also note `gh variable list` prints `STRIPE_LIVE_PUBLISHABLE_KEY` in full. That is a publishable key
and safe by design, but see [`security.md`](./security.md) — the same command shape prints secrets in
other repos, and memory `minting-a-token-with-and-prints-it-in-full.md` records the incident class.

### 6.3 The laptop

The engine runs here. Project CLAUDE.md, "Where production runs": the scheduler and consumer run from
`/Users/chidionyema/Documents/code/prospector-live`, a checkout kept detached at `origin/main`.
launchd jobs in `deploy/`:

| Job | Plist |
|---|---|
| Scheduler | `deploy/com.prospector.scheduler.plist` |
| Consumer | `deploy/com.prospector.consumer.plist` |
| Watchdog | `deploy/com.prospector.watchdog.plist` |
| Log rotation | `deploy/com.prospector.log-rotation.plist` |
| Offsite backup | `deploy/com.prospector.offsite-backup.plist` |

**Marginal cash cost: electricity only.** No hosted inference, no rented compute — that is the
project CLAUDE.md's "no hosted service" constraint, and it is why §4.1's metered leg is only $120
all time.

The real laptop cost is **contention**, and it has a receipt. Memory
`lowpriorityio-starves-an-io-bound-job.md`: `LowPriorityIO` produced 0.54s of CPU across 21 minutes.
A job that cannot get I/O does not save money, it stalls the queue.

### 6.4 Storage

```bash
$ du -sh store publish/bundles graphify-out; wc -c store/prospector.jsonl
 707M	store
  27M	publish/bundles
 322M	graphify-out
270224298 store/prospector.jsonl
```

| Store | Size | Where | Cash cost |
|---|---:|---|---|
| `store/` (catalogue, dossiers, ledger, cache) | **707 MB** | laptop | $0 |
| ├─ `store/prospector.jsonl` | 258 MB | laptop | $0 — **36% of `store/` is one log file** |
| `publish/bundles/` (189 pack zips) | 27 MB | laptop | $0 |
| `graphify-out/` | 322 MB | laptop | $0 |
| R2 pack objects | not measured | Cloudflare R2 | see below |
| Fly volume `store_data` | not measured | Fly | see §6.1 |

R2 config, `.env.example:73-76`: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
`R2_BUCKET=prospector-packs`. A **separate** offsite backup bucket at `.env.example:77-81`,
`R2_BACKUP_BUCKET`, target for `scripts/backup_store.py`.

Objects are content-addressed (`bridge.py:1444-1448`, key `packs/{id}/{hash}.zip`) so a republish
writes a **new** object and never overwrites content an existing buyer is entitled to. **That means
R2 storage grows monotonically with every republish and nothing prunes it.** At 189 bundles averaging
143 KB, the current footprint is small; the growth rate is what to watch.

**HYPOTHESIS: R2 is inside the free tier.** R2 charges for storage and Class A/B operations but not
egress. Check: `wrangler r2 bucket list` and the Cloudflare dashboard's R2 usage page.

### 6.5 What a month costs — the honest assembly

| Line | Monthly | Basis |
|---|---:|---|
| Metered model spend | **~$100** | $49.81 over 14 days (§7.1) → ~$107/30d. Against a $3,000/month implied cap. |
| Subscription (Claude Code plan) | **fixed plan fee** | $3,408 of *equivalent* burn over 14 days is **not** an invoice. §1.3. |
| Fly.io, 4 machines + volume | **HYPOTHESIS** | §6.1, `fly billing show` |
| Cloudflare R2 | **HYPOTHESIS, likely $0** | §6.4 |
| GitHub Actions | **$0** | §6.2, proven |
| Laptop | **electricity** | §6.3 |
| Stripe | **% of revenue** | §7.4 |

**The one line that matters:** metered model spend is the only variable cash cost that scales with
production, it runs at roughly **$100/month**, and it is capped at **$3,000/month** by a ceiling that
has never come within 8x of binding.

---

## 7. Unit economics

### 7.1 Cost to vet one candidate

Window 2026-08-04 to 2026-08-18. Dossiers counted by `created_at` from `store/dossiers/*.json`;
spend summed from the ledger by local calendar day.

| Day | Dossiers | Metered | $/vetted | Subscription | $/vetted |
|---|---:|---:|---:|---:|---:|
| 2026-08-05 | 25 | $1.6400 | $0.0656 | $71.94 | $2.88 |
| 2026-08-06 | 180 | $4.4618 | $0.0248 | $693.07 | $3.85 |
| 2026-08-07 | 95 | $1.0456 | $0.0110 | $417.66 | $4.40 |
| 2026-08-08 | 144 | $1.3578 | $0.0094 | $461.04 | $3.20 |
| 2026-08-09 | 141 | $0.5900 | $0.0042 | $188.11 | $1.33 |
| 2026-08-10 | 132 | $1.3856 | $0.0105 | $419.13 | $3.18 |
| 2026-08-11 | 29 | $0.6925 | $0.0239 | $114.80 | $3.96 |
| 2026-08-13 | 68 | $1.0520 | $0.0155 | $155.53 | $2.29 |
| 2026-08-14 | 56 | $4.0817 | $0.0729 | $294.85 | $5.27 |
| 2026-08-15 | 50 | $8.4681 | $0.1694 | $258.89 | $5.18 |
| 2026-08-16 | 348 | $12.9062 | $0.0371 | $241.10 | $0.69 |
| 2026-08-17 | 527 | $10.3311 | $0.0196 | $78.16 | $0.15 |
| 2026-08-18 | 28 | $1.0147 | $0.0362 | $13.77 | $0.49 |
| **Window** | **1,823** | **$49.81** | **$0.0273** | **$3,408.05** | **$1.87** |

`docs/COST_PROGRAM.md:248-249` records the first baseline of this measurement, 2026-08-07..13 over
577 dossiers: **metered $0.0088/vetted, subscription-equivalent $2.82/vetted**. Today's window is
metered **3.1x higher** and subscription **34% lower** — MiniMax took the moat, so work moved from
the free-at-point-of-use rail onto the metered one. That is the trade the promotion bought.

`COST_PROGRAM.md:243-247` names the standing tool so nobody writes a second parser:
`tools/experiments/w02_standing_receipt.py`, reading `SchedulerGuard.spend_by_day()`.

### 7.2 Cost to produce one sellable pack

```
window 2026-08-04..18: 1823 dossiers, 75 PASS = 4.11%
```

| Input | Value | Source |
|---|---:|---|
| Dossiers in window | 1,823 | §7.1 |
| PASS in window | 75 | command above |
| PASS rate | **4.11%** | 75 / 1,823 |
| Metered in window | $49.81 | §7.1 |
| Subscription in window | $3,408.05 | §7.1 |

Arithmetic:

```
metered per sellable pack      = 49.8079 / 75 = $0.664
subscription per sellable pack = 3408.05 / 75 = $45.44
combined per sellable pack                    = $46.10
```

**A sellable pack costs $0.66 of invoiced money and $45.44 of subscription-equivalent model time.**

The dominant term is the 4.11% PASS rate, not the per-call price. **Every candidate that dies still
costs full price** — the 24 candidates killed for each one that ships are 96% of the bill. Halving the
model rate saves $23 a pack; doubling the PASS rate saves the same $23 and produces twice as many
packs. See [`product-manager.md`](./product-manager.md) §on kill gates for where the 96% goes.

### 7.3 Against the price

| Line | Value | Source |
|---|---:|---|
| Mean live shelf price | £57.15 | §5.6 |
| USD at H.10 GBP→USD 1.3498 | **$77.14** | `config.yaml:1959` |
| Cost to produce (combined) | **−$46.10** | §7.2 |
| **Gross before fees and infra** | **+$31.04 (40%)** | |
| Cost to produce (invoiced only) | −$0.66 | §7.2 |
| **Gross on cash costs only** | **+$76.48 (99%)** | |

**Both numbers are true and they answer different questions.** The 99% figure is the cash margin: if
the Claude Code subscription is a fixed monthly fee you pay regardless, a pack sale is nearly pure
contribution. The 40% figure is the margin at replacement cost: if that work had to be bought at API
rates, four packs in ten pay for the estate.

**HYPOTHESIS: Stripe takes 1.5% + 20p on UK cards**, which on a £57.15 sale is ~£1.06 (1.9%). I found
**no fee constant anywhere in `store_platform/src/Store.Api/Payments/`** — `rg -n "fee|Fee"` over that
directory returns nothing. The fee is therefore invisible to this codebase and can only be read from
the Stripe dashboard. Check: Stripe Dashboard → Balance → Fees, or
`stripe balance_transactions list --limit 10`.

### 7.4 The number this document does not have

**There is no revenue receipt in this repo.**

`store/listings/*.json` records what was *published*, not what was *sold*. A verbatim listing:

```json
{"candidate_id": "08b22037fc2afc07",
 "title": "PanelPack — the fixed-fee pack that gets your relative's care package restored…",
 "market": "uk", "verified_at": "2026-08-06T07:21:05.061086+00:00",
 "published_via": "EngineBridge", "catalog": true}
```

No price field. All 119 listing files parse; **all 119 have `price_pence: None`** because the key does
not exist. The price lives in the Store's SQLite catalogue and in Stripe, not here.

`store_platform/src/Store.Api/Endpoints/OpsEndpoints.cs:10` is the operator surface for "orders,
revenue and the delivery outbox", and `:30` carries the warning that decides how to read any figure
from it: **"Summing Orders to get revenue reports money the shop never received."** An Order row is
not a payment.

To get a real revenue number:

```bash
# The shop's own view (needs the ops key)
curl -s -H "X-Ops-Key: $OPS_KEY" https://api.mumchimp.com/ops/orders

# The only authority on money received
stripe balance_transactions list --limit 100
```

Until one of those is run and recorded, **every margin figure in §7.3 is a per-unit rate, not a
result.** `docs/DELIVERY_LEDGER.md` is where a real one should be appended.

---

## 8. Failure modes

Each row has happened here or is pinned by a test or a comment naming the incident.

| # | Symptom | Root cause | Fix | Receipt |
|---|---|---|---|---|
| 1 | Probe prints `$1.64 of $20.00` while the day really consumed $73 | The cap counts only `event: spend` rows; Claude CLI logs `cost_usd` with no `event` key | Report both legs, always | `guard.py:21-45`, measured 2026-08-05 |
| 2 | A metered provider's calls sum to $0.00 no matter how many are made | Provider absent from `PRICING` and the config-aware path never called | `get_price(cfg=cfg)` + a loud warn on an unpriced provider | `telemetry.py:284-303`; the scar: 1,017 `standardcompute` rows at $0.00 |
| 3 | 110 ticks report `$0.0000 of $20.00 spent today` | Clock behind the ledger; the cap sums a day with no rows | Refuse to generate when `today < newest_ledger_day` | `guard.py:355-386`, `store/scheduler/ticks.jsonl` dated 1970-01-01..03 |
| 4 | Spend sums to exactly $0.00 with no error | Hand-written parser read `cost_usd` on `event: spend` rows; the field is `amount_usd` | Use `SchedulerGuard`, never a fresh parser | Reproduced this session, §1.2; memory `never-hand-parse-the-spend-ledger` |
| 5 | Arming the subscription cap freezes the backlog | `run_tick` returns on `not can_run` **before** the drain | Use `daily_subscription_soft_cap_usd`, which drains and self-releases | `config.yaml:2529-2541`, defect `0efe40e` |
| 6 | Buyer is charged, then fulfilment refuses to deliver | Provider Price and catalogue row minted from different numbers | One `PriceDecision` feeds both | `bridge.py:1274-1280`, fence at `FulfilmentService.cs:141` |
| 7 | A republish re-points a live pack at a fresh Stripe object | `publish_pass` minted unconditionally; `Program.cs:490` updated `ProviderPriceId` unconditionally | `_resolve_money_rail` reuses the existing rail | `bridge.py:1560-1576`, commit `b1ac6b0b` |
| 8 | Six packs listed but unbuyable; buy button returns HTTP 500 | `store_payments.active_provider` unset → default rail with no key → `price_stub_*` ids | Explicit `active_provider: stripe`; refuse to LIST a stub id | `config.yaml:2001`, `bridge.py:1466-1471`, config comment at `:1994-1999` |
| 9 | A price moved with no trace: no history row, no floor move, `changeCount` 0 | Price mutated without a `PackPriceHistory` write | `PATCH .../price` refuses a change with no `Reason` | `Program.cs:556`, `:1191`; `pricing.py:44-48` |
| 10 | Price runs backwards against the only number a buyer can see | `ambition_tier` selected the rung and is invisible on the page | `source_count_bands`, monotonic by construction | `pricing.py:11-27`; still live on 48 of 74 rows, §5.6 |
| 11 | A malformed band list silently re-introduces the inversion | Bad config fell through to the tier ladder while rationales still said "depth" | `_usable_bands` refuses LOUDLY, naming the rule broken | `pricing.py:118-150` |
| 12 | `IndexError` on the publish path from a config typo | `tier_rung_index: {side_hustle: 99}` read unclamped when building the rationale | Clamp before use, not only when adding | `pricing.py:324-330` |
| 13 | A pack is minted with no USD price and it fails silently | `price_usd_cents` is an `Optional` default; the depth branch never set it | Set it on every branch; the fence refuses USD without a floor | `pricing.py:275-285` (comment names the omission), `:285` |
| 14 | 40% of retrieved price anchors carry `amount_pence_gbp: null` | `fx_to_gbp` held GBP only; USD anchors could never be evidence | Declare USD and EUR from a dated H.10 release | `config.yaml:1955-1970` |
| 15 | A third of the price-retrieval budget buys anchors the gate discards | Query asked for monthly plans; `cadence_eligible` admits `one_off` alone | Re-aim the query at one-off pricing | `config.yaml:1935-1945`; 200 of 361 anchors lost |
| 16 | Every PR goes red with zero steps and no logs | GitHub refused to start jobs over billing; visible only on the check-run annotation | `CI_RUNS_ON=self-hosted` | `ci.yml:8-13`, `docs/CI_RUNNER.md:19-33` |
| 17 | A build failure reads as `exit 0` | `npm run build 2>&1 \| tail` reports **tail's** status | Capture the build's own status before any pipe | project CLAUDE.md |
| 18 | Numeric comparison in a shell report is wrong | `awk`/shell compare as STRINGS unless an operand is numeric | Coerce with `+0` and re-run before quoting any threshold count | global CLAUDE.md, incident 2026-08-06 |

---

## 9. Invariants

Each is a rule, the place it is enforced, and what happens the day it breaks.

| # | Invariant | Enforced at | Consequence if broken |
|---|---|---|---|
| I1 | **One `PriceDecision` mints the provider Price AND the catalogue row.** | `bridge.py:1284` → `:1407` → `:2147` | Buyer is charged and then refused delivery. `FulfilmentService.cs:141`. |
| I2 | **Price is a rung on a declared array, never a computed number.** | `pricing.py:226` (rungs read from config), no arithmetic anywhere in the module | £63.41 appears on the shelf and nobody can say why. `pricing.py:3-6`. |
| I3 | **A dry run cannot mint an orphan money object.** | `bridge.py:1256-1272`, placed before `price_for` | Every rehearsal leaks a Stripe Product. The daemon re-gates packs continuously (`config.yaml:2370-2381`). |
| I4 | **`price_comparables` can never kill.** | `kill_filter.is_hard_fail` and verify's run order, **structurally**, not by config omission | An absent price page kills a good idea. `models.py:107`, `price_comparables.py:9`. |
| I5 | **Every price anchor appears literally in the passage it cites.** | `price_comparables.py:119` `_appears_in` | An unsourced number lands on the money path. Source-or-die. |
| I6 | **FX is declared with a dated source, never inferred.** | `config.yaml:1972-1977` | A guessed rate becomes an unsourced number on the money path. |
| I7 | **FX never bills a buyer.** USD prices are declared rungs, not conversions. | `pricing.py:160-173` `_usd_at` | The charged amount depends on which rate the process read; the fence rejects a buyer who paid what they were shown. `config.yaml:1866-1875`. |
| I8 | **A pack with a `price_stub_*` id must not be LISTED.** | `bridge.py:1466-1471` | A live buy button returns HTTP 500. Six packs shipped this way before 2026-07-31. |
| I9 | **A pack with no deliverable in R2 must not be LISTED.** | `bridge.py:1451-1457`, enforced server-side too | Sale with nothing to deliver. |
| I10 | **Retrieving pricing evidence and acting on it are two switches.** | `comparables.enabled` (`config.yaml:1922`) vs `rung_adjust_enabled` (`:1927`) | The catalogue re-prices itself the day a feature merges. |
| I11 | **The daily cap counts invoiced money only.** | `telemetry.py:305-317` emits only for priced providers; `claude_cli` deliberately unpriced | The daemon halts within two hours daily for money nobody invoices. `guard.py:36-39`. |
| I12 | **A dead spend rail stops generation; it never waves it through.** | `guard.py:355-386` (clock gate) | Unattended generation with no ceiling. Project CLAUDE.md forbids it. |
| I13 | **Price is monotonic non-decreasing in `sourceCount` at listing time.** | `pricing.py:153-157`, pinned by `tests/unit/test_pricing_monotonic.py` | The dearer pack cites less; the price cannot be intuited from the page. |
| I14 | **A price change carries a stated Reason and a history row.** | `Program.cs:1191`, `pricing.py:44-48` | A moved price is indistinguishable from a bug. `Program.cs:556`. |
| I15 | **The API runs exactly one machine.** | `api.fly.toml:52-54` | SQLite is single-writer. Two machines corrupt the catalogue. |

---

## 10. How to change it safely

### 10.1 Moving a price rung

1. **Read `config.yaml:1790-1828` first.** The comment block is the decision history, including two
   reverted edits and the founder's standing objection that the array is "silly, predictable and
   unscientific".
2. Edit `rungs` (`config.yaml:1829`). **If you change its length, change `usd_rungs`
   (`config.yaml:1876`) to match** — see the §5.4 defect. Also check every index that points into it:
   `default_rung_index` (`:1888`), `tier_rung_index` (`:1898-1902`), `source_count_bands` must stay at
   `len(rungs) - 1` edges (`:1860`).
3. Bump `ladder_version` (`config.yaml:1883`). It is a label, but a stale one misattributes a price.
4. **Understand what you have and have not changed.** You changed the price of packs listed *from now
   on*. You did **not** change one live row — `bridge._resolve_money_rail` keeps a pack on sale at the
   price it sells at (`bridge.py:1560`).
5. Run the gate.

**The test that catches a mistake:** `tests/unit/test_pricing_monotonic.py` pins that price is
non-decreasing in `sourceCount` across the full live range. `pricing.py:156` names it. A band edit
that breaks monotonicity fails there and nowhere else.

Also run `tests/unit/test_payer_solvency_price.py`, which exercises the hand-built-config degradation
path (`pricing.py:228-232`, finding #20).

### 10.2 Repricing the live shelf

**This is not a config edit.** `config.yaml:1849-1852` and `pricing.py` docstrings both say so. It
requires, for each pack:

1. A new provider Price object (the old one keeps existing buyers whole).
2. `PATCH /internal/catalog/{id}/price` with a stated `Reason` (`Program.cs:1191`).
3. A `PackPriceHistory` row, which is what lets a later sale be attributed to the price the buyer was
   shown (`Program.cs:1263`).
4. A floor move, or the fulfilment fence refuses the new amount (`Pack.cs:82`).

Worth **+£170.00** at today's counts (§5.6). `Store.Tests/Endpoints/PriceHistoryTests.cs:11` is the
test that covers the reader.

### 10.3 Changing a spend cap

Two routes, and the console is the intended one:

- **Console:** the key is registered at `prospector/ops/console_api.py:1182` (`spend.daily_cap_usd`)
  and `:1186` (`spend.warn_at_usd`), group `money`. Founder directive: everything changeable is
  ops-driven.
- **Config:** `config.yaml:2517` / `:2520`. Requires a daemon restart to take effect.

Before raising a cap, run the projection rather than guessing:

```bash
.venv/bin/python tools/spend_today.py
.venv/bin/python -m prospector.ops.spend      # spend_view: both legs, projected hit time
```

`prospector/ops/spend.py:110` `_project` needs `MIN_ELAPSED_H = 1.0` (`:61`) of elapsed day before it
will project — an hour of data is the minimum that produces a meaningful rate.

**Never arm `daily_subscription_cap_usd` (`config.yaml:2528`) as a first move.** It freezes the
backlog. Arm `daily_subscription_soft_cap_usd` (`:2541`) instead, set **below** the hard cap or the
hard wall fires first and takes the drain with it.

### 10.4 Adding a metered provider

1. Add the adapter in `prospector/operator.py` and register it in `_build_operator`.
2. **Add a rate under `config.yaml`'s `pricing:` block.** Without it every call prices at $0 and the
   cap cannot see the provider — failure mode 2.
3. **Pass `cfg` to `record_usage`.** Only a caller that does gets the config-aware path
   (`telemetry.py:284-291`). Without it you silently take the module fallback.
4. Decide whether it may rule finally. `config.yaml:81` `moat_primary`. If it is outside that set,
   every verdict it produces is `provisional` and is **paid for twice** (`operator.py:1509`).
5. Confirm `errors.looks_exhausted` classifies its exhaustion messages, or a dead brain is retried
   forever (project CLAUDE.md, "A dead brain must leave a trace").

### 10.5 The gate

There is **no pre-commit hook installed in this checkout** as of 2026-08-17. Verify, never assume:

```bash
git config --get core.hooksPath                        # set => THAT directory wins
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

Run it yourself, and preflight without committing:

```bash
.venv/bin/python scripts/popdd_verify.py --staged
```

Ceiling is 2400s (`scripts/popdd_verify.py:86`). Ruff runs **repo-wide**
(`scripts/popdd_verify.py:166`), so one unformatted file anywhere walls every commit in every
worktree.

---

## 11. Open gaps and debt

Ordered by what it costs to close.

| # | Gap | Evidence | Cost to close |
|---|---|---|---|
| G1 | **`usd_rungs` has 7 elements, `rungs` has 5.** Indices 5–6 are unreachable dead config that a future GBP rung would silently activate at $199.99. | `config.yaml:1876` vs `:1829`; `pricing.py:171` clamp | **10 minutes.** Truncate the array; add a length assertion beside `test_pricing_monotonic.py`. |
| G2 | **48 of 74 live rows are off the declared price ladder**, and the £29.99 tier is deeper than the £49.99 tier. | §5.6, `config.yaml:1841-1847` | **A repricing operation, ~£170 of upside.** §10.2. Half a day of careful work; it touches live money. |
| G3 | **Zero `price_anchor` tags on 2,929 dossiers** while `comparables.enabled: true`. C3 spends retrieval budget every survivor and no evidence is reachable on disk. | §5.5 command | **1 hour to diagnose.** Read `price_comparables.py:383-414`, find the real tag key, then decide whether C3 is running at all. |
| G4 | **$30.46 across 3,046 metered rows carries no provider tag** — 25% of all spend is unattributable. | §4.2 | **Nothing, going forward** (`telemetry.py:311` fixed it). The history is unrecoverable. Say "since 2026-XX" on any per-provider claim. |
| G5 | **No revenue figure exists anywhere in this repo.** Every margin in §7.3 is a rate, not a result. | §7.4, `OpsEndpoints.cs:30` | **30 minutes** — run `stripe balance_transactions list`, append a row to `docs/DELIVERY_LEDGER.md`. This is the highest-value item here. |
| G6 | **L6: the daemon pays 2.8x the interactive rate per request and the cause is UNPINNED.** The obvious explanation is refuted. | `COST_PROGRAM.md:44` | **Unknown — that is the problem.** At §4.4's volumes it is the largest unexplained line in the estate. |
| G7 | **L1 (Opus → Sonnet, 39.9%) is CONFIGURED, NOT LIVE.** | `COST_PROGRAM.md:39`; verify with `grep -n '"model"' ~/.claude/settings.json` | **One word**, plus a process relaunch — `settings.json` is read once at process start, so `/clear` does not apply it. |
| G8 | **No Fly or R2 cost figure.** Two of the estate's five cost lines are HYPOTHESIS. | §6.1, §6.4 | **15 minutes.** `fly billing show`; Cloudflare R2 usage page. |
| G9 | **Stripe fees are invisible to this codebase.** `rg -n "fee\|Fee"` over `Store.Api/Payments/` returns nothing. | §7.3 | **1 hour** to record actual fees per transaction from `balance_transactions` into the delivery ledger. |
| G10 | **`store/prospector.jsonl` is 258 MB and grows unbounded.** It is 36% of `store/`. `SchedulerGuard`'s checkpoint keeps the scan cheap, but rotation resets it (`guard.py:79-81`). | §6.4, `guard.py:68-85` | **Already partly built** — `deploy/com.prospector.log-rotation.plist` exists. Confirm it covers this file and that rotation does not blind the cap. |
| G11 | **R2 objects are content-addressed and nothing prunes them.** Every republish writes a new object forever. | `bridge.py:1444-1448` | **Design decision, not a bug** — old objects keep existing buyers whole. Needs a retention policy tied to entitlement expiry, not a delete script. |
| G12 | **A clock set FORWARD defeats the daily cap and nothing can detect it.** | `guard.py:373-377`, stated openly | Needs a trusted time source. **Low priority** — the cap has 7.7x headroom (§4.3), so it is not the binding control today. |
| G13 | **`daily_cap_usd: 100.0` is 7.7x above the peak day.** It is a liability ceiling, not a control. The real brake (OPS_CONSOLE_PROGRAM R15, spend-vs-cap with projected hit time) is what `config.yaml:2514-2516` says should govern. | §4.3 | Check whether R15 shipped: `rg -n "R15" docs/OPS_CONSOLE_PROGRAM.md`. |

---

## 12. Where to look next

**Commands, in the order a finance question usually arrives.**

```bash
# What is being spent right now, both legs
.venv/bin/python tools/spend_today.py
.venv/bin/python -m prospector.ops.spend

# $/vetted over a window, from the production reader
.venv/bin/python tools/experiments/w02_standing_receipt.py

# Is the estate healthy enough for any of this to mean anything
bash ~/.claude/projects/-Users-chidionyema-Documents-code-prospector/.state-probe
.venv/bin/python scripts/live_checkout.py

# The live shelf, its prices and its depth
curl -s https://api.mumchimp.com/catalog | python3 -m json.tool | head -60

# The only authority on money received
stripe balance_transactions list --limit 100

# Infrastructure cost
fly billing show
gh variable get CI_RUNS_ON        # self-hosted => Actions minutes are $0
```

**Files, by question.**

| Question | Path |
|---|---|
| What may be spent | `config.yaml:2506-2541` |
| What was spent | `store/prospector.jsonl` — **read it with `SchedulerGuard`, not by hand** |
| Who decides a tick may spend | `prospector/scheduler/guard.py` |
| How a dollar becomes a ledger row | `prospector/telemetry.py:270-320` |
| What a provider costs | `prospector/telemetry.py:186-196` + `config.yaml`'s `pricing:` block |
| Which brains are on the roster | `config.yaml:58, 81, 136, 145, 157` |
| How a price is chosen | `prospector/pricing.py` — 354 lines, read it whole |
| The declared ladder | `config.yaml:1788-1992` |
| Evidence for a price | `prospector/price_comparables.py` |
| Where price becomes money | `prospector/bridge.py:683-1530` |
| Where money becomes a file | `store_platform/src/Store.Api/Services/FulfilmentService.cs`, `Endpoints/DeliveryEndpoints.cs` |
| Who moved a price | `store_platform/src/Store.Catalog/Domain/PackPriceHistory.cs`, `Program.cs:1311` |
| Infrastructure shape | `store_platform/deploy/fly/*.toml`, `deploy/*.plist` |
| Where CI runs and why | `docs/CI_RUNNER.md`, `.github/workflows/ci.yml:1-20` |
| The cost programme | `docs/COST_PROGRAM.md` — **append measurements here** |
| What shipped and what it cost | `docs/DELIVERY_LEDGER.md` |

**Personas.** [`product-manager.md`](./product-manager.md) for what the money buys.
[`analyst.md`](./analyst.md) for whether a funnel number can be trusted.
[`ops.md`](./ops.md) for the buttons. [`founder.md`](./founder.md) for the one-page version.
[`../ESTATE_MAP.md`](../ESTATE_MAP.md) for the shape of the whole thing.

---

*Every number in this document was measured on 2026-08-18 unless dated otherwise. If a figure here
disagrees with a command you just ran, the command is right — fix this file.*
