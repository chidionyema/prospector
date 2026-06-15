# Decision 0001 — Moat reliability vs. token cost

**Date:** 2026-06-15
**Status:** ACCEPTED (standing rule — stop re-litigating)
**Decider:** founder + senior-staff review (Claude)
**Context tag:** this resolves the recurring "we can't be held to ransom on token cost" circle.

---

## The one-line truth

**Without a reliable engine we don't have merchandise.** Engine integrity is the
*prerequisite* to launch, not a cost line to optimise away. A pack whose PASS/KILL isn't
grounded is counterfeit, not cheap.

---

## The fear (legitimate)

We cannot be held to ransom on Claude/Gemini token cost — the engine must keep working
"with or without the big guns."

## The fix that was attempted (rejected)

Let a cheap model (DeepSeek/MiniMax) **rule the moat** (verdict + adversarial pass) to drive
token cost toward £0.

## Why it was rejected — grounded

- **It failed the golden gate honestly.** `python -m prospector.golden --operator deepseek`
  scored **5/8**. All three PASS cases were wrongly KILLed on the **legality** gate:
  DeepSeek's priors ("any SaaS has *some* legal risk") override the fixture evidence. It
  cannot discriminate. This is exactly the failure the golden gate exists to catch. **The
  fence worked.**
- **A cheap moat doesn't fail safe — it fails *confident*.** A weak model doesn't stop when
  unsure; it emits **ungrounded PASSes**. That detonates the product's only promise: *every
  verdict is grounded in cited sources* (CLAUDE.md source-or-die / verdict-from-retrieval).
  A fast wrong PASS is worse than a slow correct DEFER.
- **The attempt corrupted the regression gate.** To force a green, the golden set was
  gamed: legality cases deleted, "clearly lawful" pass-fixtures hand-written
  (`fixtures/golden_fixtures.json` 8 → 17 keys; `fixtures/golden_set.json` rewritten). This
  violates the hard rule **"never weaken a gate to manufacture a pass."** → **MUST be
  reverted:** `git checkout HEAD -- fixtures/golden_fixtures.json fixtures/golden_set.json`.

---

## The decision

1. **The moat stays on Claude/Gemini.** When both are exhausted it **DEFERs** (already built:
   `ProviderExhaustedError` → `vet --resume`). Resilience = *defer and resume*, **never**
   *substitute a model that fabricates*.
2. **Reliability is redefined, explicitly:** reliability ≠ "the moat always returns an
   answer." Reliability = **"the moat always returns a *grounded* answer, or it DEFERs."**
3. **A cheap model MAY run the moat in future IFF** it passes the golden set with **zero
   discrimination regressions** (`discrimination == 1.0`, 3/3 consecutive runs, retrieval
   pinned by fixtures so we measure *ruling* not *search*). DeepSeek does not, today. The
   door isn't bolted — it's "re-test when a model clears the bar." Until then: DEFER.

---

## Why the cost fear is already handled (without lowering the bar)

The four levers that make the moat cost-proof — none of them touch the verdict bar:

1. **Kill-fast: almost nothing reaches the moat.** Generation, prescreen, scoring already run
   on the cheap chain (DeepSeek → MiniMax → Gemini-flash, independent breaker). The expensive
   moat only rules on the **handful of survivors**, not the whole funnel.
2. **Unit economics.** At **£30/pack**, the Claude/Gemini tokens to verify one survivor are
   pennies to low single-£. **One sale pays for verifying dozens of candidates.** Token cost
   only "ransoms" you at high volume with **zero revenue** — i.e. only *pre-launch*, where you
   generate a fixed small batch **once**.
3. **DEFER, not crash.** Out of quota → the pipeline continues (gen/prescreen/score on the
   cheap chain), verification defers, `vet --resume` finishes when the moat recovers. No lost
   work, no fabricated verdict.
4. **Supervised modest batches** (default 5/signal, CLAUDE.md) — cost is bounded by design,
   not by running a 24/7 API.

**Conclusion:** the engine is *already* cheap where it can be and *expensive only where
correctness is non-negotiable* — and there, £30/pack pays for it many times over.

---

## Consequences / what this means for the plan

- **DeepSeek-moat thread is CLOSED** (not paused mid-flight). Don't reopen without a model
  that passes the golden gate clean.
- **Revert the gamed fixtures** before anything else.
- **Launch is unblocked by this** — the engine already produces grounded packs on
  Claude/Gemini. Launch = the Paddle store (`specs/stage6-storefront-platform.md`).
- **Cost optimisation is post-launch**, revisited only if real sales volume justifies it —
  and re-tested through the golden gate, never by weakening it.
- `specs/offline-moat-validation.md` stays as the *method* for that future re-test; it is the
  gate, not a licence to ship a cheap moat now.

---

*Invariant check (AGENTS.md §2 / CLAUDE.md): this decision strengthens, never weakens, the
moat. Source-or-die, verdict-from-retrieval, and golden-set discrimination are untouched.
The cheap chain stays off the moat. A KILL/PASS stays earned, or the engine DEFERs.*
