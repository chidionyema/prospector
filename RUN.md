# Prospector Run Procedure

Every run executes these eight steps in order. The engine is invoked via CLI (run.py); config.yaml governs all parameters.

## Steps 1–8

**1. (Discover) GENERATE** from a signal (or no signal for blue-sky), capped by `candidates_per_signal` in config.yaml.

```bash
# From a signal file
python -m prospector.run signal --file signals/example.txt

# Single on-demand vet
python -m prospector.run vet --title "..." --one_liner "..." --why_now "..."

# Blue-sky (no signal)
python -m prospector.run generate --candidates 10 --exploration 0.7
```

**2. DEDUP vs catalogue.** Embed-match each candidate against existing Dossiers in store/. Drop near-duplicates; mark the existing Dossier for refresh instead.

**3. PRE-SCREEN** — fast, cheap triage. Kill only the obviously dead (no acute pain, no plausibly solvent payer, plain undifferentiated commodity, plainly illegal). When in doubt, pass.

**4. VERIFY** (kill-fast). Per check (`pain_reality`, `value_durability`, `incumbency`, `payer_solvency`, `distribution`, `legality`):
   - Generate disconfirming queries (query_gen.md)
   - Fetch real pages (retrieval.py; Gemini grounding or fixture)
   - Render verdict from passages only (verdict.md; source-or-die)
   - **Stop at first hard fail** (kill-fast short-circuit)

Then run adversarial.md: make the strongest evidence-based case the idea is dead. Record whether the case is decisive.

**5. GATE** (config.yaml hard_gates) → **KILL or PASS**. Render a dossier either way to store/; include verdict, sources, gate that fired (if KILL), and cost.

```bash
# Run steps 1–5 on a single candidate (flagship offline test with mock operator)
python -m prospector.run vet --title "Haulage HMRC fuel-duty PTO rebate" \
  --operator mock --fixtures fixtures/fuel_duty_passages.json
```

**6. (PASS only) Grounded secondary artifacts:**
   - Score on six axes (score.md)
   - Generate build spec, GTM plan, ops plan, financial model
   - Label all assumptions; all benchmarks sourced

Then generate and claim-check marketing content (claim_check.md). Regenerate anything failing the check. **No unsupported claim publishes.**

**7. (PASS only) Run publish/publish.py.** On a PASS, write listing JSON to `store/listings/<candidate_id>.json` with tiers (scout/operator/founder_investor) and print:
```
[PASS] would upsert to own store (Stripe) + syndicate to Gumroad
```
On KILL, do nothing.

**8. Print run summary:**
   - decision (PASS / KILL)
   - gate fired (if KILL)
   - source count
   - estimated cost
   - timing

Example output:
```
=== RUN SUMMARY ===
Candidate: Haulage HMRC fuel-duty PTO rebate
Status: KILL
Gate: value_durability [refuted]
Sources: 3 (hmrc.gov.uk, gov.uk/transport, specialist haulage journal)
Cost: $0.12 USD
Duration: 42 sec
```

## CLI Commands

**Test the full stack with a single offline vet (no API calls):**
```bash
pytest -q
python -m prospector.run vet --title "Haulage HMRC fuel-duty PTO rebate" \
  --operator mock --fixtures fixtures/fuel_duty_passages.json
```

**Run a batch of candidates from a signal (reads GEMINI_API_KEY):**
```bash
python -m prospector.run signal --file signals/example.txt --batch-size 5
```

**Run tests:**
```bash
pytest -q                    # quick unit + behavioural tests
pytest -v tests/unit         # verbose unit tests
pytest -v tests/integration  # API, publish, store tests
```

## Schedule & On-Demand

**On demand:** invoke RUN.md against a signal file or a single `vet` command.

**On schedule (cron):** a daily job invokes:
```bash
python -m prospector.run signal --file signals/$(date +%Y-%m-%d).txt --batch-size 5
```

Keep `batch_size` modest to stay inside your Claude Code usage allowance. Each batch writes a timestamped run log to `store/runs/`.

## Config-driven

All thresholds, model choice, operator, and retrieval strategy live in config.yaml. Changes to the configuration require a golden-set regression test (Part 13B) before they ship.
