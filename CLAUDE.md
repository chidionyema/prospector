# Prospector Operating Rules

**Source-or-die:** every factual claim and quantitative figure must cite a retrievable source or be marked `unverifiable`. No unsourced numbers ship, ever.

**Verdict-from-retrieval-only:** the model rules solely from passages it actually fetched via web search or fixture. No prior knowledge. Silence (no matching passage) → `unverifiable`, never `supported`.

**The filter is universal:** same six checks (pain_reality, value_durability, incumbency, payer_solvency, distribution, legality) apply to any business, any sector, any scale, by the same bar.

**Kill-fast:** stop at the first hard fail. Evaluate the cheapest decisive gates first; don't burn research budget on ideas already dead.

**A KILL with a cited reason is first-class:** render a dossier for every KILL, not just passes. The receipt that the filter is real and grounded is the kill log.

**Publish only on PASS:** only ideas that clear all hard gates and survive adversarial review go to the catalogue. A KILL blocks publication entirely.

**Follow RUN.md:** every run (on-demand vet, scheduled batch, signal intake) executes the eight steps in RUN.md exactly. The procedure is the guarantee.

**Use web tools for grounding:** Gemini (default) or Claude retrieval grounds every check in real pages. DeepSeek/Minimax are reserved for feature build-out via aider; they never touch verification verdicts.

**Write every run to store/:** capture input (signal or candidate), all verdicts + sources, the kill gate if applicable, cost, and timing. This log is the audit trail and the basis for learning.

**Run supervised batches inside the usage allowance:** batch size is modest (default 5 candidates per signal) and each batch runs under your watch — not a 24/7 API. When batches bump the Claude Code usage cap, fund the API operator. Supervised operation is the liability backstop.

**No hosted service / no API-key calls beyond this repo:** the entire engine runs locally or within your Claude Code subscription. No external LLM calls, no hosted inference, no infrastructure beyond your own server. This repo is the complete system.

## Architecture

The engine is composed of pluggable modules:

- **config.py** — loads operator, model, retrieval, thresholds, weights, generation strategy; no hardcoded values
- **models.py** — data classes for Candidate, Verdict, Claim, Dossier, Pack; the contracts
- **operator.py** — swappable brain (Gemini, Claude, Mock); routes calls to the active model
- **retrieval.py** — Gemini grounding (query gen, live page fetch, caching); fixture support for offline test
- **prompts.py** — loads and renders the eight prompts (generate, prescreen, query_gen, verdict, adversarial, score, content_gen, claim_check)
- **generate.py** — entry point for generation; divergent candidate creation from signals
- **dedup.py** — embed-match against existing catalogue; drop near-duplicates
- **prescreen.py** — first triage gate (fast, cheap, preservation of novelty)
- **verify.py** — the moat: runs six checks end-to-end (query gen → fetch → verdict); kill-fast short-circuit
- **kill_filter.py** — deterministic gates; KILL or PASS verdict
- **score.py** — ranks survivors on six axes; composite = Σ(score × weight)
- **dossier.py** — composing primary + secondary artifacts; rendering to JSON
- **store.py** — local catalogue state; reading/writing dossiers and listings
- **publish.py** — publish stub; on PASS, write listing JSON + print syndication intent
- **run.py** — CLI entry point; orchestrates the eight-step procedure in RUN.md

## Key constraints

- **Engine is deterministic on config.** Swapping operators (Claude Code → API) requires no code change; only config.yaml changes.
- **Every verdict is grounded in cited sources.** A KILL is not the model's opinion; it is grounded in evidence the operator can see.
- **Golden-set regression gates all changes.** Part 13B acceptance tests block ship if a prompt change causes a regression on mixed-sector discrimination.
- **Creativity lives in generation; constraint lives in verification.** Nothing is killed at generation time; all gates (pre-screen, verify, kill-filter) are downstream.
- **Two loops never merge.** Sales metrics (demand) tune what to offer; truth metrics (grounding integrity, golden-set discrimination) veto what may ship. Demand never overrides truth.
