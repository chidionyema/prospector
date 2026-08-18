# SRE on call

**What this is.** The 3am document for the Prospector estate: how to tell what is broken, in what
order to care, and the exact command for each failure.
**Read this if** a page is down, a buyer cannot pay, a download fails, the engine stopped producing,
or an alert fired and you do not know what it means.
**Do not read this to learn the control surface.** That is [`ops.md`](./ops.md). This file assumes
you already know where the buttons are and tells you which one to press.

Every claim below carries a `file:line` or a command with its measured output. Everything measured
was measured on **2026-08-18** on this machine unless stated. Where I could not prove something, the
line starts with `HYPOTHESIS:` and names the check.

Siblings: [`ops.md`](./ops.md) — the operator control surface.
Policy: [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) — where logs go and how long
they live. Read it before you go looking for a log that does not exist.
Estate map: [`../ESTATE_MAP.md`](../ESTATE_MAP.md) — **does not exist yet**. Verified:
`ls docs/ESTATE_MAP.md` → `No such file or directory`, and `rg -l "ESTATE_MAP"` over the repo returns
nothing. The link is written so it resolves the day that file lands.

---

## 1. Severity: the asymmetry that decides everything

There are two halves of this business and they have different tolerances.

**Making can stop for a day. Selling cannot stop for a minute.**

That is not a slogan. It is what the code is built to do, and here is the proof.

### The making half is designed to stop safely

The engine has four separate mechanisms whose whole purpose is to stop generating and lose nothing.

| Mechanism | Where it is read | What it does |
|---|---|---|
| `store/scheduler/PAUSE` | `prospector/scheduler/guard.py:66` (`PAUSE_FILENAME`), `:137` (`is_paused`), `:347` and `:364-365` in `evaluate()` | Halts the entire tick, generation and drain |
| `store/scheduler/PAUSE_GENERATION` | `prospector/scheduler/run_scheduled.py:233` (`_GENERATION_PAUSE_FILENAME`), checked at `:634-636` | Halts generation only; the drain keeps paying the backlog down |
| `spend.daily_cap_usd` | `prospector/scheduler/guard.py:388-390` | Stops the tick when today's ledger spend reaches the cap |
| Moat preflight | `prospector/scheduler/run_scheduled.py:1741-1753`, delegating to `prospector/health.py:304-348` | Skips the tick when every verdict brain is marked dead |

When any of these fire, the tick appends a row and returns. Nothing is lost. Work in flight is
picked up again by `vet --resume`, and candidates that could not be ruled are DEFERred rather than
killed — `prospector/verify.py:1134-1151`. The comment at `verify.py:1135-1148` records what
happens when that is wrong: a retrieval outage on a score-only check fell through to `score.py`,
which has no concept of `retrieval_failed`, and the candidate was KILLed on `min_composite`. The
dossier is still on disk at `store/dossiers/2102bacc6dd75cf9.kill.json` — a candidate killed by our
own outage, in a document that reads as fully reasoned.

So the worst case for a stopped engine is: no new packs today. The catalogue already on the shelf
keeps selling. Nobody is charged wrongly. Nothing is deleted.

### The selling half has no such safety

Now the money path. A buyer clicks buy, and the following happens with no human anywhere in it:

| Hop | Where |
|---|---|
| Checkout opened | `store_platform/src/Store.Api/Endpoints/CheckoutEndpoints.cs:24` (single), `:40` (basket) |
| Sellability fence | `CheckoutEndpoints.cs:320` — `.Where(p => ids.Contains(p.Id) && p.IsListed)` |
| Stripe session minted | `CheckoutEndpoints.cs:255-280` |
| Stripe charges the card | Stripe |
| Webhook arrives | `store_platform/src/Store.Api/Endpoints/WebhookEndpoints.cs:13`, handler `:16-80` |
| Entitlement minted | `store_platform/src/Store.Api/Services/FulfilmentService.cs:80-92` |
| Outbox row written | `FulfilmentService.cs:101-107`, same `SaveChangesAsync` as the entitlement |
| Email sent | `store_platform/src/Store.Api/Services/DeliveryDrain.cs` |
| Buyer downloads | `store_platform/src/Store.Api/Endpoints/DeliveryEndpoints.cs:204-266` |

Between "Stripe charges the card" and "buyer downloads" there is no rehearsal, no preview and no
undo. If the API is down when the webhook arrives, Stripe has already taken the money. If the
fulfilment fence refuses the line, the money is still taken: `FulfilmentService.cs:63-64` records
the Order anyway, the item goes to `unfulfilled`, `WebhookEndpoints.cs:62-66` logs
`PAID-WITHOUT-FULFILMENT`, and the buyer's success page shows `status: "unfulfilled"`
(`DeliveryEndpoints.cs:119`). **Nothing retries that automatically.** An operator has to reconcile
it by hand.

And the storefront runs exactly one API machine, because the database is SQLite:

```
store_platform/deploy/fly/api.fly.toml:45-49
# Persistent SQLite catalogue/orders db. SQLite is a SINGLE-WRITER store, so this app must run
# exactly ONE machine — do not scale the count above 1.
[mounts]
  source = "store_data"
  destination = "/data"
```

One machine. One volume. If it is down, every buyer is down, and money is being lost the whole
time.

### The severity table

| Sev | Definition | Examples | Target response |
|---|---|---|---|
| **S1** | Money is being lost or taken wrongly, right now | Storefront 5xx, checkout failing, webhook 5xx, `/healthz/money-rail` reporting `mode: test` in production | Immediate, wake up |
| **S2** | A paid buyer is not getting what they bought | Delivery outbox stuck, downloads 503, `PAID-WITHOUT-FULFILMENT` in the log | Within the hour |
| **S3** | Selling is degraded but working | One pack unlisted wrongly, price drift, slow storefront | Same day |
| **S4** | Making has stopped | Engine not generating, moat blind, provider exhausted, scheduler not loaded | Next working session |
| **S5** | Making is degraded | Zero yield, barren streak, stranded passes | This week |

The reason S4 sits below S3 is the asymmetry above. A day with no new packs costs the packs that
day would have produced. An hour with a broken checkout costs every sale in that hour plus the
buyers who will not come back. Do not invert this because the engine alert is louder — it is louder
because the engine is the half that has alerting at all (§6).

---

## 2. The first five minutes

Run these in order. They are all read-only.

```bash
cd /Users/chidionyema/Documents/code/prospector

# 1. Is the shop alive and taking money in the right mode?
curl -s https://api.mumchimp.com/healthz/money-rail
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' https://mumchimp.com/
curl -s -o /dev/null -w '%{http_code}\n' https://api.mumchimp.com/catalog

# 2. Is the engine alive, and does anything hold it up?
.venv/bin/python -m prospector.ops.console_api read status | head -60

# 3. What is already screaming?
cat store/scheduler/ALERT.txt 2>/dev/null || echo "no active alert banner"
tail -20 store/scheduler/alerts.jsonl

# 4. Which brains are benched?
cat store/provider_health.json
cat store/provider_health_noncritical.json

# 5. Is production running the code you think it is?
.venv/bin/python scripts/live_checkout.py
```

`read status` is the one command that composes everything: heartbeats, launchd supervision, pause
state, provider health, queue, routing and spend — `prospector/ops/console_api.py:149-168`. It
computes no metric of its own (`console_api.py:23-25`), so when it disagrees with a page, the page
is wrong.

---

## 3. Runbooks

Each runbook is: symptom, first command, decision tree, fix, verification.

### 3.1 Storefront down (S1)

**Symptom.** `https://mumchimp.com` returns 5xx, times out, or the browser shows a Fly error page.

**First command.**
```bash
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' https://mumchimp.com/
curl -s -o /dev/null -w '%{http_code}\n' https://mumchimp.com/api/health
fly status --app prospector-store-web
```

**Decision tree.**

- `/api/health` answers 200 but the site does not → the machines are up and Next.js is serving; the
  fault is between the browser and Fly. Check DNS and the certificate. `/api/health` is deliberately
  local-only and never calls Store.Api (`store_platform/src/Store.Web/src/pages/api/health.ts:8-12`),
  so a 200 here says nothing about the API.
- `/api/health` fails on some requests and not others → a machine is unhealthy and still in
  rotation. The readiness check is `store_platform/deploy/fly/web.fly.toml:51-56`: `GET /api/health`
  every 15s, 3s timeout, 10s grace.
- Every request fails → all web machines are down.

**Fix.** The web tier is stateless, so restarting is safe:
```bash
fly machine restart <id> --app prospector-store-web
```
There are **two** warm machines by declaration (`web.fly.toml:41-43`: `auto_stop_machines = false`,
`min_machines_running = 2`), so restarting them one at a time keeps the shop up. If the count has
drifted below two, a "rolling" deploy has nowhere to roll — that is exactly the outage recorded in
`web.fly.toml:35-40`, where one of two machines was STOPPED and replacing the other was a full gap.

**Verification.** Two consecutive 200s at least 20s apart, and `fly status` showing both machines
passing. Cold-start latency is normal on the first hit after a restart; measured on prod on
2026-08-14 at 9.216s cold against 1.118s warm (`web.fly.toml:22-27`).

---

### 3.2 Checkout failing (S1)

**Symptom.** The buy button errors, or Stripe returns the buyer to the site with no order.

**First command.**
```bash
curl -s https://api.mumchimp.com/healthz/money-rail
curl -s -o /dev/null -w '%{http_code}\n' https://api.mumchimp.com/catalog
fly logs --app prospector-store-api | tail -50
```

**Decision tree.** Read `/healthz/money-rail` first. It is served by
`store_platform/src/Store.Api/Program.cs:404-410` and its fields are defined in
`store_platform/src/Store.Api/Payments/MoneyRailStatus.cs`:

| Field | Line | The bad value and what it means |
|---|---|---|
| `decidedAtUtc` | `MoneyRailStatus.cs:31` | **`null` is the emergency.** The startup gate never ran, so nothing checked the money rail at all (`Program.cs:402-403`) |
| `mode` | `MoneyRailStatus.cs:22` | `"test"` in production means real buyers are hitting test keys and no money is arriving |
| `provider` | `MoneyRailStatus.cs:19` | `"unknown"` means the gate did not resolve a provider |
| `environment` | `MoneyRailStatus.cs:25` | Should read `Production` |

If the API returns nothing at all, it did not boot. `MoneyRailConfigGate` is an `IHostedService`
(`store_platform/src/Store.Api/Payments/MoneyRailConfigGate.cs:5-9`) that **throws to refuse boot**
when the money rail is misconfigured. `StartAsync` at `:34-64` runs the guards in order; each
throws `InvalidOperationException` at a named line:

| Guard | Throws at | Refuses when |
|---|---|---|
| `GuardInternalApiKey` | `:289` | The internal key is still `dev-test-key-change-in-production` (`:17`) outside Development |
| `GuardEntitlementsApiKey` | `:312` | Same for the entitlements key (`:22`) |
| Provider recognised | `:45` | `payments:active_provider` is not a known provider |
| Required keys present | `:53` | `Stripe:WebhookSecret` or `Stripe:ApiKey` missing (`:28-32`) |
| `GuardWebhookSecretPlaceholder` | `:337` | The webhook secret is still a placeholder |
| `GuardStripeApiKeyShape` | `:101` | The key is not `sk_live_`/`rk_live_`/`sk_test_`/`rk_test_` |
| `GuardStorefrontUrl` | `:137` | The post-payment redirect target is unset or wrong |
| `GuardEmailWebBaseUrl` | `:171` | The email base URL is unset or loopback (`:175-179`) |
| `GuardR2Config` | `:221` | R2 delivery storage is not configured |

So a refusing API is telling you which line to read in `fly logs`. **A test key in Production is
deliberately NOT fatal** — it is CRITICAL-logged only (`MoneyRailConfigGate.cs:109-116`), because
staging runs `ASPNETCORE_ENVIRONMENT=Production` for parity and would otherwise be unbootable
(`:71-75`). That is why the `/healthz/money-rail` probe exists as a second fence, and why the
deploy workflow fails on it (`Program.cs:400`).

**If the API is up but a specific pack cannot be bought:** the fence is
`CheckoutEndpoints.cs:320` (`p.IsListed`) and `:326-328` (`HasProvisionedPrice`, which rejects a
`price_stub` prefix). A pack with a stub price is refused at `:111-115` — it was never minted on
Stripe. That is a catalogue problem, not an outage: §3.4.

**Fix.** Correct the configuration and redeploy. Never patch it on the machine — the box is not the
source of truth.

**Verification.** `/healthz/money-rail` returns `mode: "live"`, `provider: "stripe"`,
`environment: "Production"` and a non-null `decidedAtUtc`. Then buy something for real, at the
lowest rung, and refund it.

---

### 3.3 Delivery failing (S2)

**Symptom.** A buyer paid and got no email, or the download link 404s / 503s.

**First command.**
```bash
.venv/bin/python -m prospector.ops.console_api read deliveries --arg state=all --arg limit=50
.venv/bin/python -m prospector.ops.console_api read order --arg order_id=<id>
```

Both go through `console_api.py:408-415` and `:391-398`, which call the internal endpoints on
Store.Api. They need `STORE_INTERNAL_API_KEY` in the environment or they refuse with a named error
(`console_api.py:642-644`).

**Decision tree.**

- **Row exists, `sentAtUtc` null, attempts climbing** → the drain is trying and failing. Read
  `lastError` on the row. `DeliveryDrain` is the only sender (`console_api.py:806-808`).
- **Row exists, `sentAtUtc` set, buyer says no email** → it was sent. Check spam, check the address
  on the row. Resend costs the receipt: `deliveries.resend` clears `SentAt`, and the API returns
  `previousSentAt` which the console writes into the intent receipt before the row loses it
  (`console_api.py:816-820`, written at `:875`).
- **No row at all, but the order exists** → fulfilment refused the line. Look for
  `PAID-WITHOUT-FULFILMENT` in the API log (`WebhookEndpoints.cs:62-66`). The gate is
  `FulfilmentService.cs:130-144`, called at `:74`:
  ```csharp
  if (pack.EffectiveFloorMinorUnits(currency, DateTime.UtcNow) is not { } floor)   // :133
      return $"{item.ProductId} (no {currency} price on this pack)";                // :135
  return item.AmountPence < floor
      ? $"{item.ProductId} (paid {item.AmountPence} < floor {floor} {currency})"     // :142
      : null;
  ```
  Two causes: the pack has no price in the buyer's currency, or the amount taken is below the
  floor.
- **Download 503** → the content is not in R2. `DeliveryEndpoints.cs:248-256` logs an error and
  returns 503 when the object is undeliverable.
- **Download 429** → the buyer hit the cap. `DefaultMaxDownloads = 50` at `DeliveryEndpoints.cs:25`,
  enforced at `:229-237`.
- **Download 404/expired** → check `:216-222` (Active-only positive authorisation) and `:224-227`
  (expiry). The presigned URL itself lives 5 minutes (`DeliveryEndpoints.cs:19`), so a link a buyer
  saved and clicked an hour later is expected to fail; they should re-request from the order page.

**Fix.** For a stuck row, `deliveries.resend` through the console. It sends nothing itself; it
resets the one outbox row and lets the drain retry. There is exactly one row per entitlement —
`PendingDeliveries.EntitlementId` is UNIQUE (`StoreDbContext.cs:61`), which is what makes a
duplicate webhook idempotent, and it is why a resend cannot create a second row
(`console_api.py:812-815`). The API refuses with 409 if the entitlement is revoked, i.e. refunded
or disputed (`console_api.py:822`).

For a below-floor payment: this is a manual reconciliation. Decide whether to honour it or refund
it. There is no tool for it today (§8).

**Verification.** Re-read the delivery row and confirm `sentAtUtc` is set and `attempts` stopped
climbing. Ask the buyer.

---

### 3.4 A pack that should be sellable is not (S3)

**Symptom.** The engine passed a pack and no one can buy it.

**First command.**
```bash
.venv/bin/python -m prospector.ops.console_api read shelf
```

`_read_shelf` (`console_api.py:947-1005`) lists every PASS the engine produced that the live shelf
does not carry, with the reason and the console action that repairs it.

**The trap.** The reason it prints is read from `store/dossiers/<id>.lint.json`, a receipt written
when the pack was gated. **A receipt outlives the rules that wrote it.** Editing the linter touches
no dossier, so every receipt stays byte-identical and reads as current forever. On 2026-08-17 five
rules stopped blocking and seven stranded packs became sellable while every receipt on disk still
said "blocked" (`console_api.py:2050-2054`). The reader guards this: `pack_linter.receipt_is_current`
at `console_api.py:982`, and any stale row gets `repair: "shelf.regate"` and
`verdict: "stale — rules changed since"`.

**Fix, in this order.**

1. `shelf.regate` — the safest action on the page and the one to run first. Under `--dry-run` the
   money rail returns at `bridge.py:1261`, before `price_for`: no Stripe Price, no R2 upload, no
   catalogue row (`console_api.py:2038-2057`). It writes only `.lint.json`, which undo covers in
   full. Cost is network — the linter probes each pack's cited URLs, about 124s per pack measured
   2026-08-17 (`console_api.py:2047-2049`).
2. `shelf.repair_copy` — rewrites shelf lines that fail the copy check. The rewrite is re-graded
   before acceptance and may only re-word; every figure and institution must survive
   (`console_api.py:1978-1980`).
3. `shelf.publish_pending` — publishes the passes that were never published. It names dossiers one
   by one and **never `--all`**, because `--all` walks every PASS including the ones already selling
   and re-runs the money rail on rows a buyer can already buy (`console_api.py:1983-1989`).

**If the shelf cannot be read at all**, the reader returns `reachable: false` and `stranded: null`,
not zero (`console_api.py:956-962`), and both publish actions raise rather than proceeding
(`console_api.py:1993-1998`, `:2059-2063`). Unknown is not zero. Fix the connectivity first.

**Verification.** Re-run `read shelf` and confirm the row is gone, then `read catalogue` and confirm
the pack id is in the list.

---

### 3.5 Engine not generating (S4)

**Symptom.** No new candidates. The producer heartbeat is old, or ticks land and do nothing.

**First command.**
```bash
.venv/bin/python -m prospector.ops.console_api read status | head -60
tail -5 store/scheduler/ticks.jsonl
```

**Decision tree.** The tick has six ways to do nothing, and they are ordered. Walk them in the order
`run_tick` does (`prospector/scheduler/run_scheduled.py:1666` onward):

| Order | Gate | Line | Symptom in the tick row |
|---|---|---|---|
| 1 | Guard refusal — PAUSE or spend cap | `:1699-1702` | `ok: false` with a reason; **no alert**, this is intended idle (`alerts.py:424`, `:431-432`) |
| 2 | Usage-wall preflight | `:1719-1729` | Whole tick skipped, drain included; CRITICAL log at `:1724` |
| 3 | Moat preflight | `:1741-1753` | `moat_blind: true`; CRITICAL at `:1746`; alert at `:1751` |
| 4 | `PAUSE_GENERATION` | `:634-636` | Generation suppressed, drain still runs |
| 5 | Grounding rate gate | `:647-649` | Generation suppressed while retrieval is degraded |
| 6 | Backlog cap | `:651-706` | Drain-only |

**Read the tick rows, but read them carefully.** `store/scheduler/ticks.jsonl` is not exclusively
the daemon's. The comment at `run_scheduled.py:115-129` records that an adjacent-estate driver
(`~/.hermes/scripts/prospector-run.sh`) fires `--once --dry-run` into this same production log at
roughly 59.6 rows/hour, while real ticks are about 2.5h apart. **Do not read a raw row count as
daemon activity.** Filter on `pid` and `run_id`, which are stamped at `:133`.

**The backlog cap has deliberately asymmetric failure modes**, and knowing which is which saves an
hour:

- An **unparseable cap fails OPEN** — generation continues unbraked, with `logger.critical` at
  `:678-679` and a CRITICAL alert keyed `backlog_cap_unreadable` at `:681-687`
  (`run_scheduled.py:654-690`).
- An **unmeasurable backlog fails CLOSED** — drain-only (`:693-702`).

Live value on disk: `config.yaml:2354` reads `backlog_cap: 0`, which is off. The rate gate is the
primary brake: `config.yaml:2369` reads `gate_generation_on_grounding: true`.

**Fix.** Whichever gate fired, clear its cause. To resume generation only:
`rm store/scheduler/PAUSE_GENERATION`. To resume everything: `pause.disarm` from the console, which
records who cleared it and why.

**Verification.** Watch two consecutive ticks. The retry cadence after an unproductive tick is 5m →
10m → 20m, capped at the normal interval:
```python
_RETRY_BACKOFF_S = 300                                          # run_scheduled.py:1566
backoff = _RETRY_BACKOFF_S * (2 ** (consecutive - 1))           # :1587
return max(1, min(interval, backoff))                           # :1588
```
The normal interval is 7200s (2h). The reason the backoff exists is measured: the 2026-08-01/02 moat
outage retried flat every 5 minutes for two days — 144 ticks, 131 of them failing
(`run_scheduled.py:1572-1578`).

---

### 3.6 Moat blind (S4)

**Symptom.** `moat_blind` in the tick row and a CRITICAL alert. Nothing is being ruled.

**First command.**
```bash
cat store/provider_health.json
.venv/bin/python -m prospector.ops.console_api read providers
```

**What it means.** Every brain the engine can rule with carries a live dead mark. The check is
`prospector/health.py:304-348`:

```python
return f"moat blind: every brain it can rule with is marked dead ({detail})"   # health.py:348
```

**The asymmetry you must not "fix".** The generation preflight calls it with `trusted_only=False`
(`run_scheduled.py:750-751`), so a tick is skipped only when *every* configured verdict brain, trusted
or provisional, is dead. The drain calls it at the default `trusted_only=True`
(`run_scheduled.py:740-744`). This is deliberate (founder directive 2026-08-08,
`run_scheduled.py:733-738`): re-vetting a `provisional` row on a provisional brain re-stamps it
`provisional`, so the row does not move and the money is spent for nothing.

**The half-open probe, and why you should not poll.** `moat_blind_reason` reads `dead_until()`, the
raw mark, never `is_dead()` (`health.py:330`, `:340`). That matters: `is_dead` at `health.py:136-145`
*consumes* the half-open probe slot:

```python
if self.dead_until(name) is None:
    return False
return not self._claim_probe(name)          # health.py:144-145
```

`_claim_probe` (`health.py:151-197`) takes an `fcntl.flock` on a dedicated lock file (`:175-177`) so
exactly one caller machine-wide gets the re-probe. It was a `threading.Lock` until 2026-08-10, which
let two *processes* both claim it (`health.py:160-170`). **If you write a monitoring script that
calls `is_dead` in a loop, it will eat the probe slot a real verdict call should have had, and a
recovered brain will stay benched.** Read `dead_until` for reporting.

**Fix.**

1. Find out why each brain is marked. The row carries `last_error[:200]` (`health.py:223-226`).
2. If it is a key or a balance, fix that. If it is transient, wait: the mark is 60s
   (`TRANSIENT_EXHAUSTION_S`, `health.py:57`).
3. If a brain is genuinely healthy and wrongly marked, clear it. `Health.clear()` at
   `health.py:234-250` logs a WARNING when it ends a live outage, which is the receipt.
4. If the roster itself is wrong, `routing.set_moat_primary` from the console. It requires
   `acknowledge_moat: true` on top of the confirmation token (`console_api.py:1408-1410`), because
   it decides what can reach the shelf.

Live roster on disk: `config.yaml:58` `operator: [minimax, claude_cli]`, `config.yaml:81`
`moat_primary: [minimax, claude_cli]`.

**Verification.** `read providers` shows no live dead mark, and the next tick does not log
`moat_blind`.

---

### 3.7 Provider exhausted (S4)

**Symptom.** `ProviderExhaustedError` in the log, or a brain benched in `provider_health.json`.

**The classification, in full.** `prospector/errors.py` decides transient versus permanent, and the
decision sets how long the brain is benched.

| Class | Markers | Line | Bench duration |
|---|---|---|---|
| PERMANENT | `_PERMANENT_MARKERS` — `quota_exhausted`, `insufficient_quota`, `credit balance is too low`, `payment required`, `usage limit` | `errors.py:97-107` | `DEFAULT_EXHAUSTION_S = 3600.0` (1 hour), `health.py:52` |
| PERMANENT | HTTP 402 | `errors.py:147` | 1 hour |
| PERMANENT | Allowance regex | `errors.py:128-130` | 1 hour |
| PERMANENT | Vendor upsell prose in a 200 body (`_USED_UP_RE`) | `errors.py:172-174` | 1 hour |
| TRANSIENT | `rate_limit`, `rate limit`, `too many requests`, `overloaded`, `server_busy` | `errors.py:131-138` | `TRANSIENT_EXHAUSTION_S = _MIN_DEAD_S` = 60s, `health.py:57`, `:46` |
| TRANSIENT | HTTP 429, 503, 529 | `errors.py:146` | 60s |

**PERMANENT wins ties** — `classify_exhaustion` at `errors.py:184-197` checks the permanent set
first and returns immediately.

**The word-boundary trap.** These are the two regexes:

```python
_HTTP_TRANSIENT_RE = re.compile(r"\b(429|503|529)\b")     # errors.py:146
_HTTP_PERMANENT_RE = re.compile(r"\b402\b")               # errors.py:147
```

The `\b` anchors are load-bearing and the comment at `errors.py:139-145` says why: a bare substring
match meant `"connection reset after 4291 bytes"` contained `429`, so a live brain was benched for
an hour on a byte count. **If you ever add an HTTP code here, add the word boundaries.** A request
id, a byte count or a token count will otherwise bench a working provider, and the symptom is a
brain that goes dead for exactly one hour at a time with no plausible cause in its error text.

**The allowance regex, and why it is not just "usage limit":**

```python
_ALLOWANCE_LIMIT_RE = re.compile(
    r"\b(spend|usage|monthly|weekly|daily|hourly|session)\s+limit\b"
    r"|\b(?:[0-9]+|five)[-\s]?hour\s+limit\b")             # errors.py:128-130
```

It matches `spend limit` because that is the phrase the Claude CLI actually prints, not `usage
limit`. `"rate limit"` is deliberately excluded and classified TRANSIENT (`errors.py:118`).

**401 is deliberately NOT exhaustion.** `errors.py:175-177` excludes unauthorized on purpose: a bad
credential must fail loudly, not silently fail over to the next brain. If you see repeated 401s,
that is a secret problem, not a capacity problem.

**Escalating re-probe.** Repeat offences widen the gap between probes:
```python
repeat = float(prev.get("dead_until", 0) or 0) > now       # health.py:218
strikes = (int(prev.get("strikes", 0) or 0) + 1) if repeat else 1   # health.py:219
probe_in = min(self._probe_spacing(strikes), dead_for_s)   # health.py:222
```
`_PROBE_AFTER_S = 120.0`, `_PROBE_BACKOFF_MULT = 2.0`, `_MAX_STRIKES = 6` (`health.py:71-73`), so
probe spacing runs 120s to about 2h. Marks are clamped to `[60s, 24h]` (`health.py:46-47`, applied
at `:211`).

**Two health files, on purpose.**
```python
HEALTH_PATH = store_root() / "provider_health.json"                          # health.py:36
NONCRITICAL_HEALTH_PATH = store_root() / "provider_health_noncritical.json"  # health.py:42
```
They are physically independent so a non-critical provider dying can never blind the moat
(`health.py:38-42`). Both resolve through `config.store_root()`, not `__file__` — the comment at
`health.py:34-35` names the reason, and §3.9 below is the incident.

**Fix.** For transient, do nothing; 60s. For permanent, fix the balance or the key, then let the
half-open probe find it, or clear the mark explicitly.

**Verification.** `cat store/provider_health.json` and confirm the row is gone or `dead_until` is in
the past. Do not use `is_dead` to check (see §3.6).

---

### 3.8 Disk full (S1 if it hits the Fly volume, S4 if it hits the mac)

**Symptom.** Writes failing, SQLite errors, the daemon dying with no message.

**First command.**
```bash
df -h /Users/chidionyema/Documents/code/prospector
du -sh /Users/chidionyema/Documents/code/prospector/store
fly volumes list --app prospector-store-api
```

**Measured now, and this is the finding:**

```
$ df -h /Users/chidionyema/Documents/code/prospector | tail -2
Filesystem      Size    Used   Avail Capacity iused ifree %iused  Mounted on
/dev/disk1s1   466Gi   429Gi    17Gi    97%     13M  173M    7%   /System/Volumes/Data
```

**The machine that runs the engine, the ops console and the scheduler is at 97% capacity with 17 GiB
free.** That is an S4 today and becomes an S1 the moment anything on this box is in the money path.

Where it has gone:
```
$ du -sh store/          →  707M
$ du -sh store/* | sort -h | tail -5
  4.6M  store/numeric_citation_shadow
   54M  store/scheduler
  172M  store/_cache
  190M  store/dossiers
  274M  store/prospector.jsonl
```

`store/prospector.jsonl` is 270,224,298 bytes and still growing (`ls -la store/prospector.jsonl`,
timestamp 18 Aug 13:32). **Do not truncate it.** It looks like a log and it is not — it is the
durable spend ledger the daily cap reads. `ops/config/log_rotation.yaml:36-42` names it as
deliberately excluded for exactly this reason: truncating it changes what the spend guard believes
and destroys the audit trail.

**What you may safely reclaim:** `store/_cache` at 172M is the retrieval cache and is
regenerable. `prospector/ops/undo.py:36` excludes it from snapshots (`EXCLUDED = {"_cache"}`) for
the same reason. Undo snapshots themselves are capped at `DEFAULT_KEEP = 12`
(`prospector/ops/undo.py:43`) and pruned by `prune()` at `:155`.

**The Fly side.** The API's SQLite database lives on a single volume — `store_data` mounted at
`/data` (`api.fly.toml:47-49`). `ops/config/offsite_backup.yaml:31-33` records its size as **a
single 1 GB Fly volume in lhr**. If it fills, the shop stops taking orders. There is no alert on
this today (§6, §8).

**Fix.** Run the rotation sweep, then clear the cache:
```bash
.venv/bin/python -m ops.automations.log_rotation          # report
.venv/bin/python -m ops.automations.log_rotation --fix    # rotate what is over its limit
```
Report-before-fix is the contract (`docs/OPS_AUTOMATION_PRINCIPLES.md` P3). Measured today, every
target is under its limit:
```
OK  .../store/scheduler/launchd.err.log: 1.3 MB (limit 10)
OK  .../store/scheduler/consumer.err.log: 0.9 MB (limit 10)
...  exit=0
```
So rotation is not where the 429 GiB went. The disk pressure is elsewhere on the machine, outside
this repo.

**Verification.** `df -h` shows the capacity falling. Set yourself a floor: below 10 GiB free, stop
generating.

---

### 3.9 Production running the wrong code (S1 or S4 depending on which half)

**Symptom.** A fix was merged and the behaviour did not change.

**First command.**
```bash
fly status -a prospector-engine
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
```

**Do NOT run `scripts/live_checkout.py` for this.** It describes a setup that no longer exists.
See §3.10 — it is now the most dangerous probe in the estate.

**Where production actually runs, measured 2026-08-18.** The engine moved to Fly. The laptop
launchd jobs and `/Users/chidionyema/Documents/code/prospector-live` were retired by that move.
Their absence is expected. It is not an incident.

```
$ fly status -a prospector-engine
 app  80d34da6636478  v12  lhr  started

$ fly volumes list -a prospector-engine
 vol_42kyqo6g0kdzew14 │ created │ prospector_store │ 20GB │ lhr │ encrypted
```

The engine is alive. Its own heartbeat says so — re-read at wall clock `2026-08-18T13:15:18Z`:

```
$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
{"ts": "2026-08-18T13:15:26.521057+00:00", "mono": 5739.806007703, "pid": 679,
 "phase": "sleeping", "interval_s": 7200, "cycles": 1, "beat_every_s": 60,
 "slept_s": 3840, "code": "617c2538c433"}
```

**`code` is the commit the process is running.** That field, not a git checkout on a laptop, is
now the answer to "which code is production executing". Compare it against `origin/main`:

```bash
git rev-parse --short origin/main     # compare with the "code" field above
```

**What is still true from the old split.** The two traps below were real and their lessons carry
over to the Fly deployment, because both are about state and secrets following the code.

**Two traps guard the split and both fail by blaming something else.**

1. **Git does not carry secrets.** The live checkout has no `.env` of its own; `.env` and
   `.lux/keys/agent.pem` are symlinks back to the developer checkout. When the move was first made,
   every MiniMax tier benched immediately with
   `ProviderExhaustedError: All operators in ('minimax', 'minimax_m27') unavailable — check API keys
   and credentials`, because the key file was not there. The symptom reads as a provider outage. It
   is a missing file.
2. **A store path derived from `__file__` follows the CODE, not the store.** `config.store_root()`
   is the one resolver:
   ```python
   override = os.environ.get("PROSPECTOR_STORE_DIR", "").strip()   # config.py:30
   return Path(override) if override else REPO_ROOT / "store"      # config.py:31
   ```
   Also read at `config.py:751` (`Config.store_dir`) and at `prospector/paths.py:66` — note there
   are **two** `store_root` definitions in the tree, which is itself worth knowing. The plists pin
   it: `ops/launchd/com.prospector.scheduler.json:5` and
   `ops/launchd/com.prospector.consumer.json:5`. `scripts/live_checkout.py:194` verifies the plist
   matches. The 2026-08-17 incident is recorded in the `store_root()` docstring at `config.py:23-28`:
   for twenty minutes the provider health marks, the retrieval cache and the scheduler audit trail
   were written beside the new code while the ledger went to the canonical store. **A daemon writing
   one health file while a probe reads another can never see a provider recover.**

**Fix.** `.venv/bin/python scripts/live_checkout.py --update` rolls production forward and restarts.
It refuses a live checkout carrying local code changes — it must stay a clean mirror of `main`. A
fix reaches production through a pull request, never through an edit on the box.

**Verification.** Re-run `live_checkout.py` and confirm the live HEAD equals `origin/main`, then
confirm the producer heartbeat advances.

---

### 3.10 A probe that outlived the thing it probes (S2 — it manufactures incidents)

**This is the highest-value entry in this document. Read it before you act on any red probe.**

**Symptom.** `scripts/live_checkout.py` reports disaster:

```
== the checkout the daemons are actually running from ==
  com.prospector.scheduler    NOT RUNNING
  com.prospector.consumer     NOT RUNNING
  com.prospector.ops-console  NOT RUNNING

== is the live checkout on origin/main? ==
  MISSING: /Users/chidionyema/Documents/code/prospector-live
```

**This output is correct and it means nothing is wrong.**

**Root cause.** The engine moved to Fly on 2026-08-18. The laptop launchd jobs and the
`prospector-live` checkout were retired by that move. `scripts/live_checkout.py` still describes
the pre-move world: `LIVE` is hard-coded to `/Users/chidionyema/Documents/code/prospector-live`
at `scripts/live_checkout.py:31`, and `JOBS` at `:33` is the three laptop launchd labels. It
looks for things that are supposed to be gone, does not find them, and reports an outage.

**Why this is dangerous rather than merely wrong.** The obvious remediation for "the scheduler is
NOT RUNNING" is to start the scheduler. On this machine that means bootstrapping
`com.prospector.scheduler` back into launchd. **That daemon must never come back.** It would be a
second producer writing to a store the Fly engine is already writing to, from a checkout that is
not `origin/main`, with a `PROSPECTOR_STORE_DIR` pointing at the laptop's `store/`. You would
manufacture the exact split-brain the Fly migration removed.

There is precedent for someone doing exactly this, recorded in the engine's own alert state:

```json
"supervisor": {"ts": "2026-08-16T13:21:51.324205+00:00", "severity": "critical",
 "title": "Daemon launchd job was missing",
 "message": "com.prospector.scheduler was not loaded ... The watchdog re-bootstrapped it"}
```

The watchdog is built to restart that job. That behaviour was right on 2026-08-16 and is wrong
now.

**First command — what to run instead.**

```bash
fly status -a prospector-engine
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
```

**Decision tree.**

| `fly status` | heartbeat `ts` | Conclusion |
|---|---|---|
| `started` | within ~120s of now | healthy. Ignore `live_checkout.py` entirely. |
| `started` | stale by more than 3× `beat_every_s` | the process is wedged. §3.5. |
| not `started` | — | real outage. This is the S4. |
| — | file missing | the engine has never run on this volume. Escalate. |

**Fix.** Two things, neither of them urgent at 3am:

1. Retire or rewrite `scripts/live_checkout.py` so it probes the Fly engine. Until then it is a
   trap with a green-looking name.
2. Confirm the laptop watchdog cannot re-bootstrap `com.prospector.scheduler`. If
   `com.prospector.watchdog` is still installed, it may do this on its own.

**Verification.** The probe either reports the Fly engine or is gone. A probe that reports on a
decommissioned system is worse than no probe, because it is indistinguishable from a real alarm.

**The general rule.** A probe is a claim about a system. When the system is replaced and the
probe is not, the probe keeps making the claim and the claim is now false. Before acting on any
red probe, ask one question: *does this probe still describe the system we run?* Check the date
of the last change to the probe against the date of the last change to the thing it watches.

---

### 3.11 Deploy wedged (S2)

**Symptom.** A deploy is stuck, or the site is unreachable for the length of every deploy.

**Decision tree.**

- **Web:** a rolling deploy needs somewhere to roll. `web.fly.toml:41-43` declares two warm
  machines. If the count is one, the deploy IS the outage (`web.fly.toml:35-40`). Check
  `fly status --app prospector-store-web` and scale back to two before deploying again.
- **API:** you cannot roll it. `api.fly.toml:45-46` — one machine, because SQLite is single-writer.
  An API deploy is a short hard gap by construction. Deploy it when traffic is low.
- **`flyctl` errors about the Dockerfile path** — read the whole log first. `api.fly.toml:8-15`
  records an incident where CI failed with a not-found Dockerfile path, the path was "fixed" to
  match, and nothing changed, because flyctl had loaded **no config file at all** and was building
  from the app's remote config. The line that says so is `Validating --config path unset--`. Check
  for that before believing the error is about the path.
- **Console:** it is not on Fly. `ops/launchd/com.prospector.ops-console.json` runs
  `next start -H 100.93.240.113 -p 8611` under launchd with `KeepAlive: true` and `RunAtLoad: true`.
  Restarting it is a launchd operation, and the console has a button for the daemons
  (`daemon.restart`, `console_api.py:2081-2120`).

**Verification.** `fly status` clean, and a real request through the front door.

---

### 3.12 CI red and blocking a fix (S3, or S1 if it blocks a money fix)

**Symptom.** You have the fix and the gate will not let it through.

**Decision tree.**

- **Is there even a gate locally?** `CLAUDE.md` has been wrong about this in both directions, so
  check, never read:
  ```bash
  git config --get core.hooksPath          # if set, THAT directory wins, not .git/hooks
  ls -la "$(git rev-parse --git-path hooks)"/pre-commit
  ```
  `core.hooksPath` overrides the hooks directory entirely, so moving `.git/hooks/pre-commit` aside
  does nothing while it is set. That cost a session on 2026-08-16: a commit failed with only "exit
  code 1" while the doc said no gate could have refused it.
- **Preflight without committing:** `.venv/bin/python scripts/popdd_verify.py --staged`.
- **`ruff` runs REPO-WIDE** (`scripts/popdd_verify.py:166`), so one unformatted file anywhere walls
  every commit in every worktree. A worktree on an older base fails ruff until it rebases.
- **Go to a worktree on the FIRST gate refusal**, not the third. `git worktree add --detach
  ../wt <ref>` then `./scripts/setup_worktree.sh ../wt`. The script exists because
  `git worktree add` produces a tree that looks complete and is not: `node_modules` cannot be
  symlinked, `.lux/keys/agent.pem` is untracked, `.venv` is absent, and `store/` is tracked runtime
  state pytest writes to.
- **A pipe hides the verdict.** `npm run build 2>&1 | tail` reports **tail's** exit status. Capture
  the real status before any pipe.

**The escape hatch for an S1.** If the money path is broken and the gate is red on something
unrelated, the founder decides whether to bypass. Not you (§7).

---

## 4. Observability today, honestly

This section is the one to read before you go looking for evidence you assume exists.

### 4.0 The two heartbeats — your only live view of the engine

These now live on the Fly engine, not the laptop. They are the observability you actually have.

```bash
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/heartbeat.json"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/consumer_heartbeat.json"
```

**Producer heartbeat, measured at wall clock `2026-08-18T13:15:18Z`:**

```json
{"ts": "2026-08-18T13:15:26.521057+00:00", "mono": 5739.806007703, "pid": 679,
 "phase": "sleeping", "interval_s": 7200, "cycles": 1, "beat_every_s": 60,
 "slept_s": 3840, "code": "617c2538c433"}
```

| Field | Meaning | A stuck value means |
|---|---|---|
| `ts` | wall clock of the last beat | **the single most important field.** Older than 3× `beat_every_s` = the process is wedged or dead. |
| `mono` | monotonic seconds since start | goes backwards or resets → the process restarted. Immune to clock changes, so trust it over `ts` when comparing two beats. |
| `pid` | process id | changes between reads → it is crash-looping, not running. |
| `phase` | `sleeping`, `starting`, `generating`, `draining` | stuck in `generating` or `draining` past `_WORKING_OVERDUE_S = 7200.0` (`console_api.py:205`) = a hung provider call. Stuck in `starting` = it never got through the preflights. |
| `interval_s` | seconds between ticks (7200 = 2h) | disagrees with the plist/config → it is running old code. |
| `cycles` | completed tick count | not increasing across two reads more than `interval_s` apart = no work is happening. `cycles: 1` after hours is normal only if it started recently. |
| `beat_every_s` | how often it writes this file | sets the staleness threshold. `console_api.py:241`: `stale_after_s = max(every*3.0, 300.0)`. |
| `slept_s` | seconds slept in the current interval | should climb toward `interval_s` and reset. Frozen = wedged mid-sleep. Above `interval_s` = it overslept, check for machine suspend. |
| `code` | **the commit this process is running** | compare against `git rev-parse --short origin/main`. This replaces the old checkout probe. |

`cycles: 1` with `slept_s: 3840` against `interval_s: 7200` reads as: one tick done, 64 minutes
into a 120-minute sleep. Healthy.

**Consumer heartbeat, same read:**

```json
{"ts": "2026-08-18T13:13:14.563675+00:00", "mono": 5607.850634322, "pid": 680,
 "role": "consumer", "phase": "skipped", "cycle": 8,
 "skipped_reason": "moat blind: every brain it can rule with is marked dead
                    (claude_cli for 2859s more, minimax for 0s more)",
 "next_check": 1787059094.563662, "code": "617c2538c433"}
```

| Field | Meaning | A stuck value means |
|---|---|---|
| `role` | always `consumer` | distinguishes the two files if you cat the wrong one |
| `phase` | `draining`, `skipped`, `sleeping` | `skipped` repeatedly = read `skipped_reason`, it is not a fault |
| `cycle` | drain cycles completed | not increasing = the drain is not running |
| `batch` | rows in the current batch | `0` while `phase: draining` = nothing is drainable, not a fault |
| `resumed_total` | rows finalised since start | flat across hours while rows wait = the drain is running and achieving nothing. Usually a benched trusted brain. |
| `errors` | error count this run | any non-zero climb = go to §3.7 |
| `skipped_reason` | why this cycle did nothing | the most useful field in the file when `phase: skipped` |
| `next_check` | unix time of the next attempt | far in the future = it has backed off. Compare with `date +%s`. |

**Worked example from the reading above.** The consumer is `skipped`, not broken. The reason
names both brains and their remaining bench time: `claude_cli for 2859s more, minimax for 0s
more`. `minimax for 0s more` means its mark has just expired, so the next cycle will re-probe it.
Correct action: **wait one cycle.** Restarting the consumer here would consume the half-open
probe slot and prove nothing. This is §3.6, and the runbook there applies.

Note the two `pid` values, 679 and 680: producer and consumer are separate processes on the same
machine.

### 4.0.1 The alert surface on the engine

Three files, same directory. Read all three; each answers a different question.

```bash
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/ALERT.txt"
fly ssh console -a prospector-engine -C "cat /data/store/scheduler/alert_state.json"
fly ssh console -a prospector-engine -C "tail -5 /data/store/scheduler/alerts.jsonl"
```

Measured 2026-08-18:

```
-rw-r--r-- 1 501 staff    502 Aug 18 12:54 /data/store/scheduler/ALERT.txt
-rw-r--r-- 1 501 staff   1150 Aug 18 12:54 /data/store/scheduler/alert_state.json
-rw-r--r-- 1 501 staff 485586 Aug 18 12:54 /data/store/scheduler/alerts.jsonl
```

| File | What it is | Read it when |
|---|---|---|
| `ALERT.txt` | human-readable, **currently active** alerts, rewritten each time. 502 bytes. | first. It is the "what is wrong right now" board. |
| `alert_state.json` | machine state: `_active` map plus a last-fired timestamp per key, used for the 1800s debounce | you need the exact firing time, or to know why an alert is not re-paging |
| `alerts.jsonl` | append-only history, 485,586 bytes | you need "when did this start" or "has this happened before" |

**`ALERT.txt` is a snapshot and `alerts.jsonl` is the history.** An alert that cleared is gone
from the first and permanent in the third. Never conclude "this never happened" from `ALERT.txt`.

**Trap:** `alert_state.json` is written non-atomically (`alerts.py:84`). A crash mid-write can
leave it truncated, which silently un-fires every active alert. If it fails to parse, treat every
alert as unknown, not as clear.

### 4.0.2 Worked example: the stranded-packs alert

This is live right now, and it is the money-losing one.

```
$ fly ssh console -a prospector-engine -C "cat /data/store/scheduler/ALERT.txt"
2026-08-18T12:11:25.978733+00:00  🚨 [critical] 44 PASS(es) stranded off the shelf
The engine produced packs no one can buy. [25363e54b649587a] 2026-08-14  lint blocked
(3 error(s): placeholders) | [e698149e137fc164] 2026-08-15  never published (no lint record) |
[9f393244da5f6c19] 2026-08-15  lint blocked (2 error(s): title) (+41 more)
 — fix: .venv/bin/python tools/verify_pass_shelf_coverage.py

Also unresolved:
  - [critical] Daemon launchd job was missing (2026-08-16T13:21:51.324205+00:00)
```

**What it means.** 44 candidates passed every gate and are not on the shelf. Making worked;
selling did not. By the severity model in §1 this is the sharp end: finished inventory that
cannot be bought.

**The alert carries its own fix command**, which is the standard this estate holds alerts to
(`OPS_AUTOMATION_PRINCIPLES.md` P7: alerts name the cause and the first action):

```bash
.venv/bin/python tools/verify_pass_shelf_coverage.py
```

That is read-only — console tool `d53fc7d46b`, risk `read`. It tells you which PASSes the shelf
does not show. The named causes split into two classes:

| Cause in the message | Meaning | Next step |
|---|---|---|
| `lint blocked (N error(s): placeholders/title)` | the pack failed the pack linter, so publication refused | fix the content; this is working as designed |
| `never published (no lint record)` | it was never even linted | this is the real defect — the pipeline dropped it |

Repair path, after you have read the report: `tools/recover_stranded_passes.py` (`1a7e1ea811`,
read) to see what repair would do, then the publish tools, which are `external` risk — undo
covers the local half only.

**The second active alert is stale.** "Daemon launchd job was missing" fired 2026-08-16, before
the Fly migration. It refers to `com.prospector.scheduler` on the laptop, which is now retired on
purpose. Do not act on it. See §3.10.

### What you CAN see

> **Path note.** Every `store/...` path below now lives at `/data/store/...` on
> `prospector-engine`, reached with `fly ssh console -a prospector-engine -C "cat /data/..."`.
> The `file:line` proofs are unchanged — the code is the same, the volume moved.

| Question | Where | Proof |
|---|---|---|
| Is the producer/consumer alive right now? | `store/scheduler/heartbeat.json`, `consumer_heartbeat.json` | `console_api.py:208-271` |
| Does launchd actually hold each job? | `read status` → `supervisor` | `console_api.py:171-195` |
| What did each tick decide? | `store/scheduler/ticks.jsonl` | `run_scheduled.py:106-140` |
| What alerts are active? | `store/scheduler/ALERT.txt`, `alert_state.json` | `console_api.py:300-324` |
| Which brains are benched, and why? | `store/provider_health.json` | `health.py:36`, `:223-226` |
| Every operator action, including refusals | `store/ops/intents.jsonl` | `console_api.py:595-618`, written by `_record_intent` `:1602-1610` |
| Daily audit of scheduler decisions | `store/scheduler/audit/YYYY-MM-DD.jsonl` — 42 files, 45M | `ls store/scheduler/audit \| wc -l` → `42`; `du -sh` → `45M` |
| Money rail mode | `GET /healthz/money-rail` | `Program.cs:404-410` |
| Order, entitlement, delivery detail | Console `read order` / `read deliveries` | `console_api.py:382-416` |

### What you CANNOT see

This is the honest list. Each line is a question the estate cannot answer today.

1. **Any Store.Api log older than the live `fly logs` buffer.** `fly logs` is a live tail, not a
   store. Nothing in this repo ships those lines anywhere. Proven: `rg -il` across the repo returns
   **zero** files for `loki`, `promtail`, `betterstack`, `logtail`, `papertrail`, `fluentd`,
   `fluent-bit`, `vector.dev` and `syslog`. The four terms that do hit are all false positives —
   `axiom` and `datadog` and `opentelemetry` hit candidate-idea text in `store/*.jsonl` and a
   `package-lock.json`; the only `sentry` hit in source is a comment,
   `store_platform/src/Store.Web/src/components/ErrorBoundary.tsx:32`: *"a real reporter (Sentry) is
   a deferred, founder-gated decision."*
2. **Whether a specific buyer's request reached the API.** There is no correlation id spanning the
   storefront, the API and the engine. You cannot follow one purchase across services.
3. **What the storefront did.** The Next.js web tier logs to Fly's buffer and nowhere else. There is
   no error reporter — see the `ErrorBoundary` comment above.
4. **What the ops console did.** It writes to `/tmp/ops-console.out.log` and
   `/tmp/ops-console.err.log` (`ops/launchd/com.prospector.ops-console.json:21-22`). **`/tmp` is
   cleared by macOS**, so console logs do not survive a reboot. The console's own *actions* are
   durable in `store/ops/intents.jsonl`; its crashes and stack traces are not.
5. **Why the API restarted.** No crash log is retained past the Fly buffer.
6. **Any cross-service question at all.** "The storefront was slow at 14:05 — was the API slow, or
   was the engine saturating the box?" needs three log sources on one timeline. There is no such
   timeline.
7. **Whether an alert was delivered.** The alert is appended locally (`alerts.py:370`); whether
   Telegram actually sent it is not recorded in a way you can query later.

The design that closes items 1, 2, 3, 5 and 6 at zero new cost is in
[`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md).

### The blind spot that bites hardest

**A buyer reports a failed purchase two days ago.** Today you can answer: was there an order row,
was there an entitlement, was there a delivery row, and what did it say. You cannot answer: what did
the API log at the moment the webhook arrived, what status did Stripe get back, and did the request
reach us at all. The first three come from the database through
`console_api.py:382-416`. The last three came from `fly logs` and are gone.

---

## 5. The probes that have lied

Every one of these reported a pass that was not true. They are grouped by the reason.

| Probe | Reported | Why it was wrong | Where |
|---|---|---|---|
| A pid check alone | "alive" | A recycled pid answers yes. `_pid_alive` is `os.kill(pid, 0)` and proves only that *some* process has that number | `console_api.py:274-285` |
| A heartbeat alone | "alive" | Proves the process was alive a minute ago; says nothing about whether anything will restart it. On 2026-08-16 `com.prospector.scheduler` was not loaded into launchd at all, so `KeepAlive` had nothing to keep alive | `console_api.py:171-182` |
| A fixed staleness clock | "dead" | The consumer's `idle_s` (60s) and `blocked_s` (300s) are 5x apart, so one threshold is wrong for at least one. Fixed by measuring against the beat's own `next_check` promise | `console_api.py:243-251` |
| A staleness clock on a working phase | "dead" | One vet measured 4127s against a ~251s median. A 300s clock calls a busy process dead every time the tail happens | `console_api.py:252-262`, `_WORKING_OVERDUE_S = 7200.0` at `:205` |
| `grep -c` over an unrotated log | "97 failures today" | The log had never rotated, so a lifetime count read as a daily one. The real number that day was 8; most of the rest named a provider chain that no longer existed. The wrong number reached a planning document as a blocker | `ops/automations/log_rotation.py:8-13` |
| `store/listings/*.json` glob | the catalogue | 77 files on disk against 59 selling packs. The shelf is the database behind the API, not the local glob | `console_api.py:623-627` |
| A stale `.lint.json` receipt | "blocked" | A receipt outlives the rules that wrote it. Five rules stopped blocking on 2026-08-17 and seven packs became sellable while every receipt still said blocked | `console_api.py:2050-2054` |
| An empty result on an unreachable shelf | "0 stranded" | Unknown is not zero. Now returns `reachable: false` and raises rather than proceeding | `console_api.py:956-962`, `:1993-1998` |
| `read status` on a cold import | wrong roster | A cold `import prospector.operator` answers `moat_primary() == {claude_cli}` while the daemon rules on `[minimax, claude_cli]` | `console_api.py:126-135` |
| Raw `ticks.jsonl` row counts | "the daemon is busy" | An adjacent-estate driver fires `--once --dry-run` into the same log at ~59.6 rows/hour | `run_scheduled.py:115-129` |
| `is_dead()` in a monitor | benched forever | It consumes the half-open probe slot | `health.py:136-145` |
| A substring HTTP match | brain benched 1h | `"connection reset after 4291 bytes"` contains `429` | `errors.py:139-147` |

The pattern is one thing: **an absent measurement rendered as a good one.** When you write a probe,
make the three-state distinction — pass, fail, could-not-establish — and never let the third collapse
into the first. `_supervisor_view` does it correctly: `loaded` is tri-state and `None` means "could
not ask launchctl", which is not the same as "not loaded" (`console_api.py:180-182`).

---

## 6. Alerting: what exists, what does not

Everything is in `prospector/scheduler/alerts.py` (536 lines). There are five sinks and two of them
work reliably.

| # | Sink | Where | State |
|---|---|---|---|
| 1 | `store/scheduler/alerts.jsonl`, always, O_APPEND + fsync | `alerts.py:370` | **Works** |
| 2 | `store/scheduler/ALERT.txt`, the active set | `alerts.py:132-157` | **Works** |
| 3 | macOS desktop notification via `osascript` | `alerts.py:219-230` | Works only if the Mac is awake and in the GUI session |
| 4 | `ALERT_WEBHOOK_URL` POST | `alerts.py:233-248` | **INERT.** The variable is set nowhere in the estate. Every hit is prose — `deploy/com.prospector.watchdog.plist:9,15`, `docs/ENGINE_RELIABILITY_PROGRAM.md:243-245`, `docs/OPS_CONSOLE_PROGRAM.md:750` — or a test's `monkeypatch.delenv` |
| 5 | Telegram via Hermes | `alerts.py:328-350` | **The only off-machine page** |

**The only path that reaches a human away from the laptop depends on a file in a different repo.**
`_HERMES_ALERT_PATH = ~/.hermes/scripts/estate_alert.py` (`alerts.py:268`), loaded by
`importlib.util.spec_from_file_location` at `:309-315`. If it is absent, alerting silently degrades
to a desktop notification on a possibly-sleeping laptop, and the only trace is a `logger.info` at
`:341`.

**Only seven keys page** (`TELEGRAM_KEYS`, `alerts.py:288-291`): `liveness`, `tick_error`,
`zero_yield`, `barren_streak`, `moat_blind`, `stranded_passes`, `consumer_down`. The principle at
`:270-287` is that Telegram is only for states that will not clear without a human, which is why
`moat_deferred`, `moat_provisional` and `barren_generation` deliberately do not page. Debounce is
1800s (`:346`). Under pytest it always returns `None` (`:304-305`), a hard fence added after a test
suite messaged the founder for real (`:331-334`).

Alert conditions are derived per tick in `alerts_for_tick` (`alerts.py:405-535`), worst first:
`tick_error` CRITICAL `:434-437`, `moat_blind` CRITICAL `:439-450`, `barren_streak` CRITICAL at ≥3
`:461-471`, `barren_generation` WARNING `:472-475`, `moat_deferred` CRITICAL `:491-500`,
`moat_provisional` CRITICAL `:501-516`, `zero_yield` WARNING `:517-534`. Guard-skipped ticks — PAUSE
and the spend cap — are explicitly not alerts (`:424`, `:431-432`), because an intended idle is not
a fault.

The watchdog runs every 15 minutes: `ops/launchd/com.prospector.watchdog.json:23` sets
`StartInterval: 900`, invoking `--watchdog` (`:16`).

### What does not exist

1. **No alerting on the money path at all.** `PAID-WITHOUT-FULFILMENT` (`WebhookEndpoints.cs:64`,
   `DeliveryEndpoints.cs:114`) and undeliverable downloads (`DeliveryEndpoints.cs:252`) are
   `LogError` only. Nothing in `store_platform` calls Telegram, Slack or a pager. **The half that
   cannot stop for a minute is the half with no alerting.** That is the single largest gap in this
   document.
2. **No alert on the storefront being down.** Fly's health check will pull a machine from rotation;
   nothing tells a human.
3. **No alert on disk.** Neither the mac at 97% nor the 1 GB Fly volume.
4. **No alert on the API failing to boot.** `MoneyRailConfigGate` throws and the deploy fails, but a
   machine that dies later just stays dead.
5. **`alert_state.json` is written non-atomically** (`alerts.py:84`), so a torn tail resets the whole
   active set (`:70-79`). An alert can silently un-fire.

---

## 7. Escalation, and what is the founder's alone

**Escalate immediately, do not decide yourself:**

| Decision | Why it is not yours |
|---|---|
| Refunding a buyer, or honouring a below-floor payment | Money out. There is no tool and no policy in the repo |
| Changing `moat_primary` | It decides what can reach the shelf. The console demands `acknowledge_moat: true` on top of the token (`console_api.py:1408-1410`) for exactly this reason |
| Changing `spend.daily_cap_usd` | Live at `config.yaml:2517` = `100.0`, warn at `config.yaml:2520` = `75.0`. A cap of `0.0` means NO CAP and the console renders it as disarmed, in red (`console_api.py:1184-1185`) |
| Bypassing the POPDD gate to ship | The gate is the proof discipline |
| Taking the whole catalogue off the shelf | Stops all revenue |
| Paying for anything | There is no budget for a paid log service. That constraint shapes `../LOGGING_AND_RETENTION.md` |
| Adding an error reporter such as Sentry | Explicitly deferred and founder-gated (`ErrorBoundary.tsx:32`) |

**Do it yourself, now, and report with the receipt:**

- Restart a web machine.
- `deliveries.resend` for a stuck row.
- `shelf.regate` — it mints nothing and publishes nothing.
- Clear a provider dead mark you can prove is wrong.
- `rm store/scheduler/PAUSE_GENERATION` when the cause is fixed.
- `pause.arm` when something is actively going wrong. A pause is cheap; a runaway is not. It needs a
  reason, and the console refuses without one — "an unexplained pause reads as a crash"
  (`console_api.py:1335`).

---

## 8. Open gaps and debt

Ordered by what they cost when they bite.

| # | Gap | Cost when it bites | Cost to close |
|---|---|---|---|
| 1 | No alerting on the money path | Silent lost revenue for as long as nobody looks | One PR: call the existing alert rail from `WebhookEndpoints.cs:64` and `DeliveryEndpoints.cs:114`. The rail already exists and is tested |
| 2 | No centralised logs | Every cross-service question is unanswerable after the Fly buffer rolls | See `../LOGGING_AND_RETENTION.md`. Zero new cost, roughly five PRs |
| 3 | Off-machine paging depends on a file in another repo | Alerts silently degrade to a sleeping laptop | One PR: make `alerts.py:309-315` report the missing-Hermes case as a WARNING and surface it on `read status`, so an inert pager is visible |
| 4 | `ALERT_WEBHOOK_URL` is documented and dead | An operator believes a sink exists that does not | One PR: either set it or delete the code and the three prose references |
| 5 | Below-floor payment has no tool | Manual reconciliation, error-prone, on the money path | Medium: a console action that shows the order, the floor and the amount and offers refund or honour |
| 6 | The mac is at 97% capacity | The engine box stops writing, silently | Hours of triage. No code needed |
| 7 | The API volume is 1 GB with no alert | The shop stops taking orders | One PR: add a volume-usage line to the offsite-backup automation, which already talks to that machine |
| 8 | `alert_state.json` is written non-atomically | An alert un-fires silently | One PR: use `prospector/jsonl_atomic.py`, already in the tree and used at `console_api.py:1606-1608` |
| 9 | `scripts/live_checkout.py` probes a decommissioned setup | It reports `NOT RUNNING` and `MISSING:` for things retired on purpose, and the obvious remediation restarts a daemon that must never come back (§3.10) | One PR: point it at `prospector-engine` and compare the heartbeat's `code` field to `origin/main`, or delete it. Highest value per line in this table |
| 10 | No health endpoint on Store.Api besides `/healthz/money-rail`, and none at all on Ops.Console | You cannot ask "is it up" without asking a business question | One PR each |

---

## 9. Where to look next

| You want | Go to |
|---|---|
| The full control surface, every tool and lever | [`ops.md`](./ops.md) |
| Where logs go, how long they live, how to back them up | [`../LOGGING_AND_RETENTION.md`](../LOGGING_AND_RETENTION.md) |
| The contract every ops automation must satisfy | `../OPS_AUTOMATION_PRINCIPLES.md` |
| The console's design and its §7 money-rail flow | `../ADMIN_CONSOLE_PROGRAM.md`, `../OPS_CONSOLE_PROGRAM.md` |
| Existing runbooks in prose | `../RUNBOOKS.md` |
| The production automation programme | `../LAUNCH_OPS_PROGRAM.md` |
| Engine reliability history | `../ENGINE_RELIABILITY_PROGRAM.md` |
| Estate quirks that cost sessions | `../ESTATE_QUIRKS.md` |
| The estate map | [`../ESTATE_MAP.md`](../ESTATE_MAP.md) — not written yet |

### The files worth knowing by heart

| File | Lines | Why |
|---|---|---|
| `prospector/ops/console_api.py` | 2548 | Every read and every action |
| `prospector/scheduler/run_scheduled.py` | 2884 | The tick and every gate on it |
| `prospector/errors.py` | 431 | Transient versus permanent |
| `prospector/health.py` | 348 | Dead marks and the half-open probe |
| `prospector/verify.py` | 1258 | The DEFER gate |
| `prospector/config.py` | 1216 | `store_root()` at `:15-31` |
| `config.yaml` | 2550 | Every knob, with the reason it has that value |
| `scripts/live_checkout.py` | 400 | What production is actually running |

Line counts measured by `wc -l` on 2026-08-18.

### Last word

The three habits that prevent most of the wasted hours in this document:

1. **Run the probe. Do not read the prose.** Including this document. Every command here is
   read-only; run it.
2. **Unknown is not zero.** If a measurement failed, say so. Do not render it as clean.
3. **Selling first.** When two things are broken, fix the one that is taking money.
