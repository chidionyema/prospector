# Post-mortem: ~2 weeks of zero PASS yield (resolved 2026-06-28)

## Summary
For ~2 weeks Prospector generated candidates around the clock and produced **0 PASS** — every
batch came back 87–94% `unverifiable` and 100% `KILL` on `min_composite`. The cause was **not**
generation quality and **not** retrieval infrastructure. It was a single localized bug: a
**silent fallback to a broken query generator**. Fixed and proven the same day.

## Impact
- 0 PASS across all batches for ~2 weeks; days of compute and operator spend with no usable output.
- Misdiagnosed twice (PASS-gate laxness; then "generation mints ungroundable ideas") because the
  symptom (high `unverifiable`) is shared by several root causes. Only reading the *actual queries
  issued* settled it.

## Root cause (proven, with evidence)
1. `config.yaml: llm_query_gen: true` — intended path is an LLM decomposing each idea into
   real-world search queries.
2. `verify.py` ran that batched query-gen on `query_op` = the **fast tier** (deepseek→minimax).
3. The fast tier timed out continuously — ledger `store/prospector.jsonl` 2026-06-28 05:05–05:07Z:
   `"MiniMax call failed: The read operation timed out … all brains exhausted/failed"`. Audit shows
   **0** successful query-gen events.
4. On failure `precomputed_queries` stayed empty, so **all six checks** (all listed in
   `template_checks`) fell back to `_templated_queries`.
5. `_templated_queries` builds **word-salad**: a truncated product fragment + abstract check-jargon.
   Proven from `store/dossiers/cf960cb605aeb045.kill.json` (CouncilTaxBand):
   - `payer_solvency → "postcode-level data flags properties whose VOA budget cuts OR cannot afford OR insolvency"`
   - `incumbency → "postcode-level data flags properties whose VOA incumbent market leader dominant competitor"`
   Such queries retrieve junk → `unverifiable` → composite ≈ 0 → `KILL`.

**The evidence existed; the query was garbage.** That same candidate's `pain_reality` search still
surfaced the IFS paper *"Revaluation and reform: bringing council tax into the 21st century"* and a
MoneySavingExpert thread from a real overpaying retiree — the moat just couldn't use them.

## Why it ran 2 weeks looking healthy
The fallback was designed to *"never hard-fail" (graceful degradation)*. Instead it degraded
**silently** to a 100%-garbage path while batches completed, dossiers rendered, and costs logged —
everything *looked* fine. **A silent soft-fail that runs for days is worse than a loud crash.**
There was no invariant on query *quality* and no alert on template-fallback rate. Unit tests stay
green because they mock retrieval, so they never exercised real query strings ("pytest green ≠
done" — the gap was never closed for query-gen).

## Fix (shipped 2026-06-28, `prospector/verify.py` ~589)
Any check the fast tier fails to answer is re-generated on the **reliable brain `op`** *before* it
can degrade to a template. A query string is **not** a verdict, so using `op` for query-gen does
not touch the moat (verdicts still come only from `op` reading retrieved passages). The garbage
template now fires only if **both** brains are down.

## Proof (same idea, before vs after)
| | Before (word-salad queries) | After (fix) |
|---|---|---|
| Composite | 1.80 | **2.50** (+0.70) |
| Grounded checks | ~0/6 | **7 of 8 SUPPORTED** |
| pain_reality / distribution / route_to_market / legality | unverifiable | **SUPPORTED** |

Live audit confirms the query transformation, e.g. `incumbency` query went from
`"…VOA incumbent market leader dominant competitor"` to `"council tax band check apps existing
services UK"`; `distribution` to `"reach UK retirees online channels Over50s Saga audience"`.

Still a KILL (2.50 < 2.6 bar) — but now an **honest grounded near-miss**, killed legitimately on
`payer_solvency` (can't prove retirees will pay), not on blind junk.

## Second bottleneck (found 2026-06-28, after the query fix): unreachable PASS gate for smb/side_hustle
Once the query fix let candidates clear composite, a **second** structural blocker surfaced — latent
for the whole 2-week window because nothing had ever reached it.

- **Bug:** `dossier.py:99` hardcoded the publish gate's moat-critical checks as
  `("value_durability", "incumbency")`. But the `smb` and `side_hustle` lanes **deliberately do not
  run those checks** (config.yaml:186-188 side_hustle *"value_durability/incumbency are OFF"*;
  config.yaml:256-281 smb runs `pain_reality/currency/route_to_market/claims_verifiable` +
  hard-gates, neither moat check present). So `moat_grounded` was **always 0** → every smb/side_hustle
  candidate that cleared composite was KILLed on `moat_ungrounded`, citing checks the lane never ran.
  **Two of four active lanes could never PASS, by construction.**
- **Proof:** Martyn's Law (smb) cleared composite at **2.95** but KILLed `moat_ungrounded`; its real
  honest gaps were `payer_solvency`/`route_to_market` unverifiable (UK hospitality closures = a real
  negative on payer health), which the gate never even named.
- **Fix:** the publish-critical check set is now **lane-declared** —
  `cfg.thresholds.moat_critical_checks` (config.py Thresholds, default `[value_durability, incumbency]`
  for venture/default; smb→`[payer_solvency]`, side_hustle→`[buyer_intent]`,
  growth→`[payer_solvency, distribution]`). `dossier.py` reads it. This does **not** loosen
  source-or-die — it still requires the lane's *decisive dimension* to be grounded in fetched
  evidence; it just stops demanding evidence the lane was designed never to produce. 49 gate unit
  tests green; venture/default unchanged (golden-set safe).

## ★ FIRST PASS IN ~2 WEEKS (2026-06-28, both fixes live)
Candidate **"Done-for-you Amazon PPC & listing-optimisation agency for UK private-label sellers"**
(smb lane, dossier `store/dossiers/1990c975d0a46ea8.pass.json`):
- **DECISION: PASS — composite 3.1500; ALL 8 checks grounded-SUPPORTED; survived adversarial.**
- `payer_solvency → SUPPORTED` (conf 0.43), grounded in real UK seller P&L (r/AmazonFBA May-2026
  breakdown) + ad-cost-inflation evidence — the exact check that KILLed every prior candidate.
- Not a lowered bar: composite 3.15 ≫ 2.6, every query on-topic, every verdict cited. The PASS path
  fires end-to-end on honest evidence. Martyn's Law (2.95) still correctly KILLs on ungrounded payer —
  the gate fix removes a spurious blocker, it does not manufacture passes.

## Status & follow-ups
- ✅ Both fixes shipped and proven on the `vet` path: query-gen reliable-brain backstop (`verify.py`)
  AND lane-aware publish gate (`config.py`/`dossier.py`/`config.yaml`). First PASS produced (above).
- ✅ Query fix proven; daemon restarted 2026-06-28 (pid 15362→24751) to load it. NOTE: the daemon
  must be restarted AGAIN to pick up the gate fix (it was changed after the restart).
- ⚠️ **Calibration watch:** two independent groundable ideas (MTD 2.55, council-tax 2.50) both land
  just under the 2.6 bar, both failing on consumer `payer_solvency`. Next test: a B2B idea with an
  obvious payer, to confirm the PASS path fires cleanly. Do NOT lower the bar to manufacture a PASS.
- ☐ Harden the fallback: rewrite `_templated_queries` to query the pain/domain noun-phrase, not
  product-wrapper + jargon.
- ☐ Kill silent failure: alert + DEFER (not blind-KILL) when a live batch used the template
  fallback for >X% of checks.
- ☐ Close the test gap: an integration/invariant test asserting query *quality* (a real check on a
  known-groundable fixture must yield SUPPORTED), not just mocked retrieval.
- ☐ Commit (currently uncommitted; founder fence).
