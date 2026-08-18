# The platform for finance

Two meters, one of them blind. That is the whole finance story here, and it is worth understanding
before anything else.

## What you can pull today

```bash
.venv/bin/python -m prospector.ops.spend      # today's split against the cap
.venv/bin/python tools/spend_today.py         # the same number, terser
.venv/bin/python -m prospector.run report     # catalogue, metrics and cost together
```

The ops console has a `/spend` screen backed by the same code, so nobody has to shell in.

## Cost of goods: what it costs to make one pack

The engine calls language models to generate candidates, write search queries, rule verdicts, and
write pack sections. Those calls are the marginal cost of a pack, and they come from two very
different places.

**Metered, invoiced, and governed.** MiniMax and DeepSeek bill per token to a real account. Every
such call writes a spend event to `store/prospector.jsonl`, the persistent ledger. The daily ceiling
is `config.yaml:2516 daily_cap_usd: 100.0` with a warning at `warn_at_usd: 75.0` — deliberately 75%
of the cap, because a warning at 15% fires every day and stops being a warning.

The raise from $20 to $100 on 2026-08-16 has a measured basis, not a vibe: metered spend ran
$0.69 (08-11) → $1.05 → $4.08 → $8.47 (08-15), roughly 8x in four days, after MiniMax took over the
verdict work and after the producer and consumer were split so the drain bills continuously rather
than once per tick.

**Subscription, uninvoiced, and invisible to the rail.** Claude Code CLI usage is covered by a
subscription. It logs its own cost under `cost_usd` with no `event: spend` tag, so the ledger scan
that enforces the cap does not see it. Measured 2026-08-05: metered $1.64 against CLI $71.94. **The
liability rail governed 2% of that day's consumption.** There is a knob for it —
`config.yaml daily_subscription_cap_usd` — and it is deliberately set to `0.0`, meaning report only.

Why it is off is the interesting part, and it is a finance argument rather than an engineering one.
A hard subscription cap refuses the whole tick, including the drain. A frozen backlog does not save
that spend — **it defers it.** Every unresolved row still owes a full re-vet later. So arming the
hard cap converts today's cost into tomorrow's cost plus a stalled pipeline. A soft cap
(`daily_subscription_soft_cap_usd`, also `0.0`) exists for exactly this: above it, a tick skips
generation and drains only, so backlog goes down while it is engaged and it releases itself at
midnight.

**The lever with the largest measured effect is not any of those.** Measured 2026-08-06: ~79% of
spend is re-reading resident context, not thinking. Six claims proven by one script emitting six
receipts cost one sixth of six separate calls. The model default is a flat 40% on every rate.
Delegating search work is a 2-4% lever. If cost is the question, `docs/COST_PROGRAM.md` is the
document, and it holds every measurement including the retired ones.

## Revenue

One rail, one entry point. `prospector/bridge.py` mints the Stripe Price and writes the catalogue row
from a single `PriceDecision`, so the price a buyer is charged and the price the catalogue shows
cannot disagree. This is not a style preference: a drift charges the buyer successfully and then
fails the fulfilment fence, so you have taken money and delivered nothing.

Price is a **rung**, not a computed number. `config.yaml listing.pricing` declares the ladder, and a
segment (ambition tier × market) selects a rung. Retrieved price comparables can move it at most one
rung, and only when `comparables.rung_adjust_enabled` is on — which is **off** by default.
Otherwise the catalogue would re-price itself the day a feature merged.

Price history is queryable: `GET /internal/catalog/{id}/price-history` on the store API answers who
moved a price and when.

Fulfilment and entitlement live behind `/checkout`, `/webhooks/{provider}`, `/orders/{token}` and
`/download/{token}`. Exactly one outbox row per entitlement is the idempotency guard.

## The traps that have cost real money or real hours

| Trap | What happens |
|---|---|
| Idempotency keys **expire**; they are not permanent dedup | A retry after expiry can double-charge |
| A queued script publishes on timeout | The publish went out after you thought it had failed |
| A checkout-session scan that ignores `status` | 168 sessions counted as live that had expired |
| A price change breaks fulfilment | The catalogue took the fallback while the rail took the decision — that is why `bridge.py` exists |
| Fly usage is a separate bill from model spend | Neither `ops.spend` nor the cap sees hosting |

## What is not built

- No accounting integration. No invoices, no P&L, no revenue recognition. The numbers above are
  operational counters, not books.
- Hosting cost is not in any dashboard. Fly bills separately and nothing pulls it in.
- There is no forecast. `ops.spend` shows today against the cap; a projected hit-time was specified
  in the ops console programme but read the live screen before assuming it shipped.

## What to read next

- `docs/COST_PROGRAM.md` — every cost lever and its measurement.
- [analyst.md](analyst.md) — the funnel numbers and how much to trust them.
- [ESTATE_MAP.md](../ESTATE_MAP.md) §6 — where state lives, which is where the ledger lives.
