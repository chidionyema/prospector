# Prospector

A continuously refreshed catalogue of vetted business opportunities, grounded in current evidence and verified by an automated engine. Sells tiered packs (Scout / Operator / Founder-Investor) self-serve on your own store and via syndication.

**What it does:** sources candidates from signals (demand complaints, cost shocks, regulatory changes, market gaps), vets each through six grounded checks (pain reality, value durability, incumbency, payer solvency, distribution, legality), kills the losers, ranks survivors by automatability and defensibility, grounds the winners with build specs and GTM plans, and publishes only the passes.

**Why it matters:** when production is commoditised by AI, value moves to *judgment* (what's worth building) and *grounding* (proof it's real). Prospector industrialises both — every listing carries sourced evidence, a build spec a dev can execute, and a kill-filter brutal enough to act on without redoing the homework.

## Quickstart

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set your API key:**
   ```bash
   export GEMINI_API_KEY=your-key-here
   ```
   (or copy `.env.example` to `.env` and fill in)

3. **Run a single vet (offline, no API calls):**
   ```bash
   python -m prospector.run vet --title "Haulage HMRC fuel-duty PTO rebate" \
     --operator mock --fixtures fixtures/fuel_duty_passages.json
   ```

4. **Run tests:**
   ```bash
   pytest -q
   ```

5. **Process a signal (generates 5 candidates, vets all):**
   ```bash
   python -m prospector.run signal --file signals/example.txt --batch-size 5
   ```

## Operator & Retrieval Model

The engine plugs two swappable parts:

- **Operator (brain):** Gemini (default, production), Claude (via Claude API), or Mock (for offline testing). Change via `config.yaml` or `PROSPECTOR_OPERATOR` env var.
- **Retrieval (grounding):** Gemini Semantic Search for live evidence, or fixtures for offline test. Every check grounds in real pages; no unsourced claims ship.

Short term: Claude Code runs supervised batches. Long term: swap to an API operator for unattended scale — the tooling never changes.

## Key Docs

- **[CLAUDE.md](CLAUDE.md)** — operating rules: source-or-die, verdict-from-retrieval-only, kill-fast, publish only on pass.
- **[RUN.md](RUN.md)** — the eight-step per-run procedure with concrete CLI commands.
- **[prospector-master-spec.md](prospector-master-spec.md)** — the complete specification: all prompts, golden-set acceptance tests, build roadmap, architecture.

## Architecture

Six modules drive the pipeline:

- **generate.py** — divergent candidate creation (unconstrained, creative)
- **verify.py** — the moat: six grounded checks; source-or-die; kill-fast
- **kill_filter.py** — deterministic gates; KILL or PASS
- **score.py** — ranks survivors; automatability weighted hardest
- **dossier.py** — composes primary + secondary artifacts
- **publish.py** — publishes PASS to own store + syndication (Stripe + Gumroad)

Everything is config-driven; swap operators or retrieval strategy without touching code.

## Success Criteria

- **Grounding integrity:** ≥95% of claims carry resolvable sources; 0 unverifiable quantitative claims published.
- **Filter discrimination:** measured on a fixed golden-set benchmark (Part 13B); must maintain high discrimination across mixed sectors.
- **Freshness:** 0 published Dossiers past their re-verification SLA.
- **Unit economics:** fully-loaded cost per published Dossier < target price ÷ 5.

Every criterion is provable; the test suite in `tests/` automates all of them.

## License

See LICENSE. No API keys in the repo; all configs are local.
