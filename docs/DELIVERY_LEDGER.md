# Delivery ledger

Append-only. One row per thing that actually shipped, with the measurement that proves it and
what it cost. Newest last.

This file exists because delivery was being reported in **prose, in a chat session** — which
evaporates at `/clear`. The same failure already has a memory file
(`a-spec-that-lives-only-in-a-transcript.md`) and a programme doc
(`docs/SITE_SPEC_PROGRAM.md`) written for exactly this reason; this is the same fix applied to
achievements and spend rather than to a spec.

## The two rules this file obeys

1. **A row is history, not status.** A row records what was true at merge time and is never
   edited afterwards. It is not evidence that anything is still working today.
2. **Live state is a command, never a row here.** For what is running, what it is costing
   right now, and whether the shelf is intact, run the probe — it reads numbers off disk and
   outranks this file, every memory and every doc:

   ```
   bash ~/.claude/projects/-Users-chidionyema-Documents-code-prospector/.state-probe
   ```

   Spend has two separate meters and they are not interchangeable:
   - **billed $** — real money, metered API calls, capped by `spend.daily_cap_usd`, read from
     the durable ledger `store/prospector.jsonl`. Never hand-parse it (memory:
     `never-hand-parse-the-spend-ledger.md`).
   - **CLI usage $** — Claude Code subscription-equivalent. Uncapped and NOT billed. It is the
     larger number by two orders of magnitude and it is the one that misleads: quoting it as
     "spend" overstates cost ~440× on the day below.

## Ledger

| merged (UTC) | PR | what shipped | measured — the receipt | billed $ | notes |
|---|---|---|---|---|---|
| 2026-08-08 08:00 | [#137](https://github.com/chidionyema/prospector/pull/137) | §3 design system on the storefront (`tokens.css` to main) | — (no probe recorded at merge time) | — | superseded the "founder decided against the §3 split" note that was still in the handoff |
| 2026-08-08 08:17 | [#138](https://github.com/chidionyema/prospector/pull/138) | E2/E3/E5/E6b/E18 harnesses, corpus freezing, blocker probe | — | — | engine only; touched nothing under `store_platform/` |
| 2026-08-08 08:22 | [#139](https://github.com/chidionyema/prospector/pull/139) | HHEM pair (E15/E17), E12 adversarial, L1 corpus reuse, Q4B2 | — | — | engine only |
| 2026-08-08 08:34 | [#140](https://github.com/chidionyema/prospector/pull/140) | **axe floor cleared on the storefront** | `verify-a11y.mjs` exit 0 — `dlitem`+`definition-list` 24→0, `color-contrast` 7→0, `link-name` 4→0, `heading-order` 8→0, over 8 routes × 2 viewports on a **built** tree | $0.00 | CI: dotnet/guard/nextjs/python all pass. Two prior diagnoses corrected by measurement (see §7 of the audit doc) |

### Day totals, 2026-08-08

Read off the state probe at 08:23 UTC, before the F-001/F-005 work:

- **billed: $0.39** of a $20.00 daily cap (engine, metered API)
- **CLI usage: $173.26**, uncapped, subscription-equivalent, **not billed**

The gap between those two numbers is the whole reason both are recorded. `$173.26` is not
money that left the account.

## What is NOT in this ledger, and why

Open findings live in `docs/DESIGN_UX_AUDIT_PROGRAM.md` §5, not here — a ledger of achievements
that also lists intentions is how "fix in flight" ends up read as "fixed". F-001 carried exactly
that label for a day while its branch had zero commits.
