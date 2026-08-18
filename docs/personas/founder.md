# The platform for the founder

You are accountable for the whole thing. Nobody else will tell you it is broken.

Your interest is narrow and it does not change: **is it earning, is it about to break, and what is
the single next thing.** Everything below is arranged around those three.

## The 60-second read

```bash
.venv/bin/python scripts/estate_map.py --quick     # is anything down
.venv/bin/python -m prospector.ops.spend           # what today has cost
.venv/bin/python -m prospector.ops.metrics         # what the engine produced
```

Or open the ops console at `https://prospector-engine.fly.dev/`. The header badge now says which
estate you are looking at: `prospector-engine · 80d34d · lhr` is production, and anything reading
`this laptop — NOT production` in red is not.

## What the business actually is

Three things, and only one of them earns.

1. **The engine makes packs.** It takes a signal, generates candidate business ideas, and puts each
   through seven evidence checks. Anything that survives becomes a research pack. The rule that
   makes the packs worth money is `source-or-die`: every factual claim cites a retrievable source
   or is marked unverifiable. A KILL is not an opinion, it is cited disconfirming evidence.
2. **The storefront sells them.** `mumchimp.com`, backed by `api.mumchimp.com`. This is the only
   part that touches money.
3. **The operator surface runs both.** The ops console, Hermes on Telegram, and about 76 tools
   under `scripts/` and `tools/`.

**Making can stop for a day and nobody notices. Selling cannot stop for a minute.** That asymmetry
is the whole basis of how you should triage anything red.

## Where your money goes and comes from

**Out.** Two separate meters, and only one of them has a rail.

- Metered API spend (MiniMax, DeepSeek) is real invoiced money. The ceiling is
  `config.yaml:2516 daily_cap_usd: 100.0`, raised from 20 on 2026-08-16 because measured spend went
  $0.69 → $8.47 in four days once MiniMax took the moat.
- Claude Code CLI burn is subscription-equivalent and **the cap structurally cannot see it**. The CLI
  logs cost with no `event: spend` tag, so the ledger scan skips it. Measured 2026-08-05: metered
  $1.64, CLI $71.94. The rail covered 2% of the day's consumption
  (`config.yaml:2524-2532`).
- Hosting: six Fly apps plus five `tie-*` apps kept on purpose.

Binding the cap does not save money. It **stalls the queue** — the guard blocks, the consumer sleeps
300s, and it resumes at midnight. The failure mode is silent backlog growth, not overspend.

**In.** Stripe, through `prospector/bridge.py`. One `PriceDecision` mints the Stripe Price and writes
the catalogue row together, so the two cannot drift. A drift charges the buyer and then fails the
fulfilment fence, which is the worst outcome available.

## The decisions that are yours alone

These are recorded because they keep getting re-proposed:

- **No hosted inference beyond the subscription, and no buying Anthropic credits.** Stated plainly:
  "not going to happen".
- **No new cloud infrastructure.** No EC2. "too many moving parts".
- **CI stays on self-hosted runners.** Those minutes are free. Deleting `CI_RUNS_ON` flips every job
  to GitHub-hosted and starts a bill — emergency lever only.
- **Everything business-critical leaves the laptop**, with zero customer downtime, and the whole
  stack stays portable across laptop, Fly, and any other provider.
- **MiniMax leads the verdict chain and is trusted-final** (`config.yaml:58,81`). Promoted on three
  consecutive golden runs at discrimination 1.00 (9/9). Do not revert on one bad run.
- **Autonomous generation, no human in the loop**, behind exactly two rails: the daily spend cap and
  the filesystem kill switch `store/scheduler/PAUSE`.
- **Everything that can change is changed by the operator, not by an edit.** Config, not code.

## What is still on the laptop, and why that is a risk

Run `scripts/estate_map.py` for the current answer. As last measured: **9 of 18 declared launchd jobs
have a pid, and all 4 GitHub Actions runners are still local.** The two open pieces of work are
Hermes (R7) and the runners (R8). Until those land, closing the laptop degrades the operator surface
and stops CI. It does **not** stop the storefront or the engine — those moved to Fly on 2026-08-18
with 5m40s of downtime.

One item needs you personally, and no automation can do it: **`~/.config/prospector/age-key.txt` is
not backed up anywhere off this laptop.** Losing it loses the ability to read encrypted state.

## How to read a claim from anyone, including me

The house rule exists because an asserted design caused real damage. Every statement of fact ships
with its proof inline — a `file:line`, command output, or a runnable check — or it is labelled
`HYPOTHESIS:` with the exact check that would settle it. Comparisons are claims too: "better" and
"faster" are banned as bare words.

**If a reply tells you something is done and does not show you the receipt, it is not done.**

## What to read next

- [ESTATE_MAP.md](../ESTATE_MAP.md) — how the parts connect, and §10 "Probes that lie".
- [finance.md](finance.md) — the cost model in detail.
- [product-manager.md](product-manager.md) — what the buyer actually receives.
- `docs/LAUNCH_OPS_PROGRAM.md` — the tracked production automation programme, which is the remit.
