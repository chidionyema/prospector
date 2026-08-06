# Prospector Operating Rules

**Source-or-die:** every factual claim and quantitative figure must cite a retrievable source or be marked `unverifiable`. No unsourced numbers ship, ever.

**Verdict-from-retrieval-only:** the model rules solely from passages it actually fetched via web search or fixture. No prior knowledge. Silence (no matching passage) → `unverifiable`, never `supported`.

**The filter is universal:** same six checks (pain_reality, value_durability, incumbency, payer_solvency, distribution, legality) apply to any business, any sector, any scale, by the same bar.

**Kill-fast:** stop at the first hard fail. Evaluate the cheapest decisive gates first; don't burn research budget on ideas already dead.

**A KILL with a cited reason is first-class:** render a dossier for every KILL, not just passes. The receipt that the filter is real and grounded is the kill log.

**Publish only on PASS:** only ideas that clear all hard gates and survive adversarial review go to the catalogue. A KILL blocks publication entirely.

**Follow RUN.md:** every run (on-demand vet, scheduled batch, signal intake) executes the eight steps in RUN.md exactly. The procedure is the guarantee.

**Use web tools for grounding:** every check is grounded in real fetched pages. The retrieval chain is `[ddg, exa, claude_cli]` (`config.yaml retrieval.provider`) — free DuckDuckGo first, Exa second, Claude Code's own web search as the always-available backstop. Gemini is gone: there is no `gemini` key anywhere in `config.yaml`. Verdicts are ruled only by a trusted moat brain — `MOAT_PRIMARY = {claude_cli, claude, cursor_cli}` (`prospector/operator.py:875`). DeepSeek/MiniMax are reserved for non-critical generation and triage ONLY; when one of them serves a verdict because the moat was exhausted, the ruling is stamped `provisional`, never publishes on PASS, and is auto re-vetted (`prospector/operator.py:878 is_provisional_provider`).

**Write every run to store/:** capture input (signal or candidate), all verdicts + sources, the kill gate if applicable, cost, and timing. This log is the audit trail and the basis for learning.

**Run bounded batches inside the usage allowance:** batch size is modest (default 5 candidates per signal). Generation may run continuously and unattended (founder decision, 2026-06-20: no human in the loop) via `prospector/scheduler/` — but ONLY behind the automated backstop that replaces human supervision: a daily spend ceiling (`spend.daily_cap_usd`, read from the persistent `store/prospector.jsonl` ledger) and a filesystem kill switch (`store/scheduler/PAUSE`). Those two automated rails are the liability backstop; unattended generation without them is forbidden. When batches bump the Claude Code usage cap, fund the API operator.

**No hosted service / no API-key calls beyond this repo:** the entire engine runs locally or within your Claude Code subscription. No external LLM calls, no hosted inference, no infrastructure beyond your own server. This repo is the complete system.

## Architecture

The engine is composed of pluggable modules:

- **config.py** — loads operator, model, retrieval, thresholds, weights, generation strategy; no hardcoded values
- **models.py** — data classes for Candidate, Verdict, Claim, Dossier, Pack; the contracts
- **operator.py** — swappable brain (Claude, Cursor CLI, DeepSeek, MiniMax, Mock); routes calls to the active model. `MOAT_PRIMARY` (`operator.py:875`) is the trusted set that may rule a verdict; DeepSeek and MiniMax sit in tiered non-critical chains for generation, prescreen, and scoring. If one of them rules because the moat is exhausted, the result is stamped `provisional` and re-vetted, never finalised.
- **retrieval.py** — the grounding chain `[ddg, exa, claude_cli]` (live page fetch, caching, per-provider circuit breakers); fixture support for offline test. `GeminiGroundingProvider` still exists in the file but no config selects it.
- **prompts.py** — loads and renders the prompts (generate, prescreen, query_gen, verdict, adversarial, score, content_gen, claim_check, price_comparables)
- **generate.py** — entry point for generation; divergent candidate creation from signals
- **dedup.py** — embed-match against existing catalogue; drop near-duplicates
- **prescreen.py** — first triage gate (fast, cheap, preservation of novelty)
- **verify.py** — the moat: runs the lane's checks end-to-end (query gen → fetch → verdict) on a MOAT_PRIMARY brain; kill-fast short-circuit. Tracks provider_chain and per-check provider for audit. Raises ProviderExhaustedError when the moat is down so callers can DEFER and resume.
- **price_comparables.py** — the seventh check, and the only evidence-only one: on a candidate that survived every gate, it extracts CITED prices buyers already pay from retrieved price pages. It can never kill (barred in `kill_filter.is_hard_fail` and in verify's run order) — "no price page on the open web" is a fact about the web, not the idea. Every anchor must appear literally in the passage it cites; FX is config-declared, never inferred.
- **pricing.py** — the L1 price ladder: segment (ambition_tier × market) → a rung on a fixed ladder declared in `config.yaml listing.pricing`, never a computed continuous number. Comparables can move it at most one rung, and only when `comparables.rung_adjust_enabled` is on (default off).
- **kill_filter.py** — deterministic gates; KILL or PASS verdict
- **score.py** — ranks survivors on six axes; composite = Σ(score × weight)
- **dossier.py** — composing primary + secondary artifacts; rendering to JSON
- **store.py** — local catalogue state; reading/writing dossiers and listings
- **publish.py** — publish stub; on PASS, write listing JSON + print syndication intent
- **bridge.py** — the money rail's entry point: mints the provider Price object and writes the catalogue row. One `PriceDecision` feeds both, so the minted price and the catalogue price cannot drift (a drift charges the buyer and then fails the fulfilment fence).
- **run.py** — CLI entry point; orchestrates the eight-step procedure in RUN.md. Builds the tiered non-critical chain `_NONCRITICAL_ORDER = (claude_cli, minimax)` (`run.py:177`) for generation/prescreen/score. Handles moat exhaustion with DEFER + `vet --resume`. Persists failed signals to `signals/pending/` for `generate --resume`.

## Key constraints

- **Engine is deterministic on config.** Swapping operators (Claude Code → API) requires no code change; only config.yaml changes.
- **Every verdict is grounded in cited sources.** A KILL is not the model's opinion; it is grounded in evidence the operator can see.
- **Golden-set regression gates all changes.** Part 13B acceptance tests block ship if a prompt change causes a regression on mixed-sector discrimination.
- **Creativity lives in generation; constraint lives in verification.** Nothing is killed at generation time; all gates (pre-screen, verify, kill-filter) are downstream.
- **Two loops never merge.** Sales metrics (demand) tune what to offer; truth metrics (grounding integrity, golden-set discrimination) veto what may ship. Demand never overrides truth.
- **Non-critical chains run behind their own breaker, and never rule a verdict.** Generation, prescreen, and scoring run on `claude_cli → minimax` (`run.py:177`), behind a completely independent health file and circuit breaker. If every tier fails, the chain raises ProviderExhaustedError — it never silently promotes itself into ruling. The signal is saved for `generate --resume`. Founder directive 2026-08-06 put claude_cli at the head, so a MOAT_PRIMARY brain now serves non-critical work: deepseek was measured at HTTP 402 Payment Required and cursor_cli at its usage limit, leaving every generation/prescreen/score call to minimax — which is non-deterministic on structured routing calls even at temperature 0 (4 of 6 candidates returned a different tier across 3 repeat runs). The absolute rule is unchanged and is about VERDICTS, not tiers: DeepSeek/MiniMax never rule as trusted-final, and `is_provisional_provider` (`operator.py:878`) enforces it.
- **A dead brain must leave a trace.** A fallback chain that works hides its own degradation — the run succeeds, so nothing looks wrong, while the head of the chain is a guaranteed failure paid before every call. Permanence is classified by one shared, tested function (`errors.looks_exhausted`), which every metered adapter uses; only a `ProviderExhaustedError` reaches `_health.mark_exhausted`, so a failure that classifier misses is retried forever. 402/"payment required" was missing from it until 2026-08-06.
- **Moat exhaustion = DEFER, not crash.** When every MOAT_PRIMARY brain is exhausted, the signal pipeline continues (generation/prescreen/score run on the non-critical chain), verification defers, and `vet --resume` picks up when the moat recovers.
- **Price is a rung, and evidence and action are separate decisions.** `price_comparables` retrieves cited willingness-to-pay anchors on by default; letting them move a price is a second, explicitly-enabled switch. Retrieving evidence and acting on it must never be the same config flag — that is how a catalogue re-prices itself the day a feature merges.
