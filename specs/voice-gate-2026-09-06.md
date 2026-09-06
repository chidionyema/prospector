# Voice Gate — full engineering specification

**Status:** v1 spec, ready to build on founder's go. Companion to `docs/proposals/2026-09-06-voice-gate.md` (v2, commits `dfda2944`, `f10fdf1f`).
**Date:** 2026-09-06 · **Convention:** file:line references are as measured this date; re-verify before each edit.

---

## 0. Contract

One gate grades every string a customer can read. Publication of any artefact that fails is impossible, in every lane. Deterministic checks first (zero variance, <$0), local 1B SLM semantic check second ($0), constrained rewrite third, quarantine last. Frontier models only on low confidence or explicit escalation.

Success is defined per phase in §12 as commands that must exit 0 (LAW 33). Empirical proof rule applies: a phase is not done on a green test alone — the verification column names the live artefact that must show the result.

## 1. Definitions

- **Lane** — a register contract. Three ship in v1: `pack`, `storefront`, `evidence-export`. A fourth, `client:<name>`, is reserved by the schema and activated in phase 4.
- **Grade target** — one named string field (e.g. `entries[].reason`, `title`, `oneLiner`). The gate grades targets, never blobs.
- **Verdict** — `PASS` | `FAIL` | `QUARANTINE`. FAIL means Tier 1 or high-confidence Tier 2 refusal; QUARANTINE means rewrite attempts exhausted.
- **Finding** — `{rule_id, lane, field, span, detail, tier}`; machine-readable, one per defect.
- **Confidence** — Tier 2's top-1 logit probability. Below threshold ⇒ escalate, never guess.

## 2. `voice-policy.yaml` — the single source of truth

Location: `prospector/voice_policy.yaml` (packaged with the repo; products mount their own). Schema:

```yaml
version: 1
lanes:
  evidence-export:            # engine → storefront data blobs (the open lane)
    description: "Research artefacts rendered as customer copy"
    deny_patterns:            # Tier 1, regex DFA, case-insensitive
      - id: EE1
        pattern: '\b(SUPPORTED|REFUTED|PARTIALLY SUPPORTED|UNVERIFIED)\b'
        message: "verdict label is engine scaffolding, not copy"
      - id: EE2
        pattern: '\bpassages?\b'
        message: "research-mode reference to evidence passages"
      - id: EE3
        pattern: '\b(the strongest case (for|against)|premortem|adversarial review)\b'
        message: "internal diligence framing"
      - id: EE4
        pattern: '^\s*\d+\s+[a-z0-9.-]+\.(com|org|uk|net)\s*$'   # "1 acas.org.uk"
        message: "numbered citation line in prose"
      - id: EE5
        pattern: '\b(no (passage|evidence) (shows|provides|establishes)|appears open in these passages)\b'
        message: "hedged research-speak"
    inherit: [storefront]     # plus everything the storefront lane enforces
  storefront:
    rules: [R1, R2, R4, R5, R6, R8, R9, R10, Q1, Q2, Q3, DASH, ID-LEAK, HEDGE]
  pack:
    rules: [ALL, GRAMMAR]     # today's pack lane, unchanged semantics
rules:
  R1:  {name: sentence_length, source: prose_target.json#measures, severity: error}
  R2:  {name: clause_load,     source: prose_target.json#measures, severity: error}
  R9:  {name: banned_register, source: prospector/register_lint.py lexicon, severity: error,
        note: "one lexicon, one rule id; Vale Register.yml deleted in phase 3"}
  DASH:    {name: house_dashes,     source: copy_lint.check_house_dashes, severity: error}
  ID-LEAK: {name: identifier_leak,  source: copy_lint.check_identifier_leak + is_prose_artifact, severity: error}
  HEDGE:   {name: abstraction_hedging, source: copy_lint.check_abstraction_and_hedging, severity: warning}
  # R4,R5,R6,R8,R10,Q1-Q3 map 1:1 from house_style.py; GRAMMAR = copy_lint.check_grammar (harper), pack lane only
tier2:
  model: "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
  fallback_model: "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
  confidence_floor: 0.80       # below → frontier escalation
  frontier_alias: "cheap"      # LiteLLM alias, estate policy
  max_prompt_exemplars: 6
tier3:
  max_iterations: 2
  preserve: [numbers, named_entities, urls, dates]   # enforced by pack_linter numeric/citation checks
```

Rule migration is a move, not a rewrite: each entry names the existing function that owns the logic today. `content_contract.py` remains the pack-lane field→rule→repair registry and now reads rule metadata from this file.

## 3. Gate API

Service: `idp/platform/voice-gate/server.py` (FastAPI, stdlib-only deps beyond fastapi/uvicorn; binds 127.0.0.1 per R20; OTLP to estate collector per LAW 50). During phases 0–3 it runs beside the engine as a local process; the estate deployment lands with the catalog entity in phase 1.

```
POST /v1/grade
  req:  {lane, field, text, context?: {artefact, run_id}}
  resp: {verdict, findings: [Finding], tier_reached, confidence?, latency_ms, policy_version}
  errors: 400 schema · 422 unknown lane · 503 Tier-2 unavailable AND policy.tier2.required

POST /v1/rewrite
  req:  {lane, field, text, findings}
  resp: {verdict, text, iterations, preserved_ok: bool, findings_remaining}
  invariant: preserved_ok=false ⇒ verdict=QUARANTINE, never a mutated fact

GET /v1/health   → {tier1: ok, tier2: ok|down|disabled, policy_version}
GET /v1/metrics  → Prometheus text (names in §9)
```

Batch mode: `POST /v1/grade` accepts `{items: [...]}` (max 500) for CI and export-script use; one verdict per item, artefact fails if any item is not PASS.

Fail-closed rule (zero-trust-boundary.md): Tier 2 unreachable ⇒ evidence-export and storefront lanes FAIL CLOSED (a gate that cannot run its semantic check does not wave prose through); pack lane degrades to Tier-1-only with a warning receipt, preserving today's behaviour.

## 4. Where it lives: platform in idp, voice in the product

Per the headline rule (one platform; a product never carries its own copy of a platform layer), Voice Gate splits in two:

**`idp/platform/voice-gate/` — the capability (one of it, for the whole estate).**

| file | responsibility | source of logic |
|---|---|---|
| `policy.py` | load/validate any product's `voice-policy.yaml`, version hash | new |
| `tier1.py` | deterministic checks over a grade target | prospector's register_lint, house_style, copy_lint, pack_linter, prose_target — lifted here; prospector imports from the platform, never the reverse |
| `tier2.py` | llama.cpp client, prompt build, logit confidence | new; exemplars ship per product policy |
| `tier3.py` | bounded rewrite, fact-preservation re-check | shelf_copy_repair core, moved |
| `server.py` | API, batching, OTLP telemetry, 127.0.0.1 bind (R20) | new |
| `quarantine.py` | jsonl queue + receipts | pattern from pack_linter receipts |
| `catalog/` | Backstage entity + STANDARDS.md row ("Content governance") alongside the Observability and Identity rows in `crew/docs/STANDARDS.md` | new |

**`prospector` — the product's voice and its wiring (nothing else).** `voice-policy.yaml` (mumchimp's brand voice is a product asset), lane definitions, Tier-2 exemplars harvested from the ombudsman corpus and kill-log history, and the boundary call sites (§7). The product onboards onto the platform service; it does not embed a second engine. hermes-v2 and any future product onboard the same way: one policy file each, zero new code.

**Resale consequence:** the phase-4 product image is built from `idp/platform/voice-gate/`; a client mounts their own policy file. That is the offer — the platform capability is the product, mumchimp is tenant zero.

Migration order (no big-bang delete — founder review note): phase 1 lifts the four linters into `idp/platform/voice-gate/tier1.py` with prospector importing them, phase 3 deletes Vale YAMLs and the duplicated rule tables once the pack-lane suite is green against the platform import. `prompts/style/voice.md` stays (prompts still help) but is generated from the policy file so prose and enforcement cannot drift.

## 5. Tier 2 — local SLM classifier

- Runtime: `llama-server` (llama.cpp, ARM NEON / Metal on dev hardware): `-m <model> --threads 2 --ctx-size 1024 --port 8081`. Estate runs it beside the engine; phase 4 ships it inside the product image.
- Task shape: single-token verdict. Prompt (few-shot, ≤6 exemplars, lane-tagged) ends `Verdict (0=lane-correct, 1=register-leak):` and the server is queried with `n_predict=1`, `logprobs=top`. Verdict = argmax token; confidence = its probability.
- Exemplars: ombudsman decisions (human register, label 0 for storefront-adjacent genres) + confirmed leaks from `kill-log.json` history (label 1) + graded pack prose. Selected per lane, fixed set committed under `prospector/voice_gate/exemplars/`.
- Confidence < 0.80 ⇒ frontier call on the `cheap` alias with the same prompt; that verdict is authoritative and is appended to the fine-tune candidates jsonl.
- Fine-tune path (post-v1 hook): when candidates ≥ 2,000, evaluate a LoRA; no v1 dependency.

### Golden sample and benchmark (the honesty gate)

- 100 strings: 50 known leaks (harvested from current `kill-log.json`/`sample-report.json` and pack history), 50 confirmed-good copy (live .tsx copy, post-scrub exports, ombudsman-normalised prose). Lane-tagged. Human-labelled: two crew labels + founder spot-check of 20.
- Harness: `tools/voice_gate_benchmark.py` → agreement rate, per-lane precision/recall, P50/P99 latency, fallback rate. Committed results json; CI re-runs on policy or model change.
- **Acceptance: ≥95% agreement, ≥90% recall on leak class, P99 ≤ 250 ms on dev hardware (the 15–30 ms ARM figure is re-measured on the phase-4 OCI target; until measured it is a target, not a claim).** Miss ⇒ ship Tier-1 + frontier fallback and iterate; the leak stays closed.

## 6. Tier 3 — rewrite

- Mode A (local infill): GBNF-constrained generation pinning every number, named entity, URL and date from the source string; output re-graded through Tier 1+2; `preserved_ok` computed by re-running pack_linter's numeric/citation extractors and diffing sets.
- Mode B (frontier): estate LiteLLM alias for our lanes; product lanes use the client's key (BYOK) — zero token liability to us.
- Cap: 2 iterations, then QUARANTINE with full findings receipt.

## 7. Boundary integrations (exact insertion points)

| Boundary | Change | Verified at |
|---|---|---|
| `tools/make_sample_report.py` | grade `report` dict's prose fields (`title, oneLiner, whoPays, whyNow, premortem, adversarial, checks[].prose`) via batch `/v1/grade`, lane `evidence-export`; non-PASS ⇒ exit 1, no write | `main()` line 248, before `json.dump` line 258; `OUT` line 22 |
| `tools/make_kill_log.py` | same, fields `entries[].title, oneLiner, reason` | `main()` line 261, before `json.dump` line 311 |
| pack publish path | repoint `bridge.py:26-29` imports and `run.py:686` `check_shelf_copy` at the gate's Tier-1 API (identical ruleset) | existing pack-lane tests must pass unchanged |
| Store.Web CI | new `scripts/lint-copy.mjs`: walks `src/data/*.json` + page copy, batch-grades, non-PASS ⇒ exit 1; wired into `verify` in `package.json` (currently `typecheck && lint && lint:css`) as `&& lint:copy` | `package.json` scripts block |
| repo CI | benchmark + adversarial fixture job | `.github/workflows` (idp `main_verdict_gate` rules apply) |
| future Medusa/CMS | same endpoint; documented, not built | — |

## 8. Phase 0 — scrub procedure (the day-one fix)

1. Land the gate check in both export scripts first (they refuse dirty output from now on).
2. Regenerate: for `entries[].reason` and sample-report check prose, apply Tier-3 Mode B once per failing string, offline, receipts per string; where rewrite confidence is low, the entry's prose is replaced by the human-written gate label already on the page (`gateLabel`) plus a link — losing a paragraph beats shipping engine-speak.
3. Rebuild Store.Web; verification: counts in §12 phase 0 row + read the rendered `/how-it-works` HTML and quote one formerly-leaking section now reading as copy (empirical proof rule).

## 9. Telemetry (LAW 50)

OTLP to the estate collector. Metrics: `voicegate_grades_total{lane,verdict,tier}`, `voicegate_tier2_confidence` (histogram), `voicegate_fallback_total`, `voicegate_quarantine_depth`, `voicegate_latency_ms{tier}` (histogram), `voicegate_policy_version` (gauge). Coverage proof is a backend query: rendered-string counts graded per artefact vs total — never a file scan. Catalog entity for the service lands in idp with the phase-1 PR.

## 10. Quarantine & review

`store/voice_gate_quarantine.jsonl` — one row per item: `{ts, lane, field, text, findings, iterations, artefact, run_id}`. Surfaced in the existing ops console next to pack_linter refusals (same repair affordance). Weekly digest; depth alert at >20.

## 11. Testing

- Unit: per-rule fixtures (bad/good pairs, mirroring idp AGENTS.md gate convention) under `tests/voice_gate/`.
- Adversarial CI: a fixture JSON containing a planted leak (`SUPPORTED … passages …`) must fail `lint:copy`; green run proves the wall (LAW 22/45).
- Golden benchmark as §5; policy or model change without benchmark run ⇒ CI red.
- Idempotency: two export runs over one store ⇒ byte-identical JSON (repo generator rule).
- Regression: full pack-lane suite unchanged after repoint.

## 12. Phases, verification, rollback

| Phase | Verify command(s) | Live proof | Rollback |
|---|---|---|---|
| 0 (½d) | `grep -c -iE "passage|SUPPORTED" src/data/kill-log.json src/data/sample-report.json` → 0; both export scripts exit 1 on a planted-leak fixture | rendered `/how-it-works` HTML quoted | revert two scripts + regenerate JSONs from store |
| 1 (2–3d) | `pytest tests/voice_gate tests/invariants -q` green; policy hash logged on publish | one pack published through gate path, receipt shown | flag `VOICE_GATE_ENABLED=0` restores direct calls |
| 2 (2–3d) | `python tools/voice_gate_benchmark.py` → agreement ≥95%, leak recall ≥90%; latency printed | 24 h of grades with fallback rate <10% | tier2.required=false ⇒ Tier-1+frontier |
| 3 (2d) | `npm run verify` fails on planted fixture, green on main; Vale YAMLs deleted | CI run URL (LAW 22) | revert PR |
| 4 (3–5d) | `docker run` image <2 GB; second policy grades sample corpus; receipts | image digest + audit API output | n/a (new artefact) |

## 13. Open decisions (defaults chosen; founder may override)

1. **Golden-sample labelling** — default: crew labels all 100, founder spot-checks 20 (one sitting, 15 minutes, LAW 54: he is client zero, not the labeller).
2. **Native port language for phase 4** — default: Rust (regex DFA + ARM64 maturity); Go acceptable, chosen at phase 4 kickoff.
3. **Tier-2 requiredness** — default: required for `evidence-export`/`storefront` (fail-closed), advisory for `pack` v1.

## 14. Explicitly out of scope (v1)

Medusa/mumchimp-medusa CMS wiring; fine-tuning (hook only); E-SLM estate routing (own plan after phase 2); any change to pack generation prompts beyond generating `voice.md` from policy; multi-language.
