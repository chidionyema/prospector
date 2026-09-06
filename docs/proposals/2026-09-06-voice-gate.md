# Voice Gate — one enforcement point for every word a customer reads

**Status:** proposal, awaiting founder acceptance. Nothing here is built.
**Date:** 2026-09-06 · **Author:** crew session · **Scope:** prospector engine → mumchimp storefront content quality

---

## 1. What the engine and storefront actually do today (mapped, with proof)

### The pipeline

```
prospector engine (Python, ~/Documents/code/prospector)
  ├─ generates packs: dossier, card, lede, offer, checklist ...  (prospector/pack_*.py)
  ├─ publishes them: bridge.py → store/prospector.db → publish/bundles
  └─ exports marketing data: tools/make_kill_log.py, tools/make_sample_report.py
         ↓  (verbatim copy, ZERO quality gates — verified below)
storefront (Next.js, store_platform/src/Store.Web)
  ├─ hardcoded page copy in .tsx                      ← Vale lane (styles/Mumchimp, 6 rules)
  ├─ src/data/kill-log.json      (501 KB, engine prose) ← NO GATE
  ├─ src/data/sample-report.json (25 KB, engine prose)  ← NO GATE
  └─ getStaticProps renders those blobs verbatim into /how-it-works, /kill-log, /sample
```

### The controls that exist — eight of them, in three lanes

| # | Control | Where | What it checks |
|---|---------|-------|----------------|
| 1 | `prompts/style/voice.md` | generation prompt | register rules as prompt instructions |
| 2 | `register_lint.py` | pack lane | R1 sentence length, R2 clause load, R9 banned register |
| 3 | `house_style.py` | pack lane | R4,R5,R6,R8,R10,Q1–3 ("what Vale cannot check") |
| 4 | `prose_target.py` + `data/prose_target.json` | pack lane | measured human bands from 766 engine docs vs 270 FOS ombudsman decisions |
| 5 | `copy_lint.py` | publish path | house-voice floor (dashes in titles, etc.) |
| 6 | `pack_linter.py` | publish path | Q2 floor: $ in UK pack, arithmetic, truncation, dead citations |
| 7 | `content_contract.py` + `shelf_copy_repair.py` | publish path | rule registry; LLM rewrite of failing lines |
| 8 | Vale + `styles/Mumchimp/*.yml` (6 rules) | storefront .tsx/docs | dashes, semicolons, sentence length, vague quantity, orphan clause, R9 lexicon |

### The leak, proved

The founder's example from https://mumchimp.com/how-it-works ("Do incumbents already own the space? … No passage shows…") is engine research prose rendered verbatim:

- `kill-log.json` contains **243** occurrences of "passage" and ships verdict scaffolding to the storefront.
- `sample-report.json` contains **10** occurrences of "SUPPORTED"/"passages".
- `tools/make_kill_log.py` and `tools/make_sample_report.py` contain **no reference to any lint, register, house-style or prose check** (grep, 2026-09-06). The export lane is open.
- Vale never sees these files: no npm script or `.vale.ini` transform covers `src/data/*.json`.

## 2. Critique — why eight controls still leak

1. **The defect was treated as a rule problem; it is a boundary problem.** Every fix added a checker *inside* one lane. Nobody put a gate on the lane that carries the most damaging prose — the engine→storefront data export. The leak is not a missing rule; it is a missing wall.
2. **Enforcement is scattered; `content_contract.py`'s own docstring says so:** "a rule's three facts … live in three different places, connected by nothing but someone remembering." Eight modules, two languages, three lanes, each with its own severity model and repair path. That is the maintenance burden and inconsistency the founder describes.
3. **Prompt-level control was measured and failed.** `register_lint.py` docstring: the rules were "live, injected, and did not hold." A prompt instruction is evaluated by the same process that produces the error.
4. **Token-match linters measured themselves out of the job.** The 2026-08-08 trial of write-good/proselint over 312,886 words produced 12,524 findings, 95.7% noise (`.vale.ini` comment). What remains is a handful of high-signal deterministic rules — necessary, not sufficient. "This paragraph is research-diligence prose, not storefront copy" is a *semantic* judgement no regex class can make.
5. **The ombudsman corpus calibrated the wrong thing for this defect.** It tuned sentence-length bands for pack prose. It never defined the target register for *marketing* prose, and never classified *evidence record* (internal) vs *customer copy* (external). The how-it-works page renders an internal artefact as if it were copy — conceptually fine, but the artefact's scaffolding (verdict labels, "the passages show") came with it.

## 3. Research — how the industry solves this

The mature category is **content governance / AI output firewalling**: one enforcement layer between any generator and any surface, policy held as data, deterministic checks first, model judgement second, audit trail on every decision.

| Option | Verdict |
|---|---|
| **Acrolinx** | Deepest brand-voice governance, but seat-priced enterprise SaaS for human writers in editors. Not an API gate for a machine catalogue; not resellable as our capability. |
| **Writer.com** | API exists, but per-token SaaS: our corpus leaves the estate, and we cannot offer it to clients as *our* capability. |
| **Markup AI / ZeroDrift** | Right shape ("content guardian agents", "one enforcement layer between AI output and delivery"). Same objections: external SaaS, not portable, not ours to sell. |
| **Vale (OSS)** | Good deterministic engine, token-match only; stock rule packs measured at 95.7% noise here. A component, not the answer. |

The consistent architecture across all credible sources (and the one LAW 43 + LAW 19 point to): **a self-hosted gate service, voice policy as versioned data, deterministic layer + semantic layer + bounded repair loop, admission control at every publication boundary, full audit trail.** Buy nothing; the hard intellectual property — the measured rules, the lexicon, the corpus bands, the repair loop — already exists in this repo, scattered across the eight modules above. The build is consolidation, not invention.

## 4. The proposal: Voice Gate

One service. Every string a customer can read must pass it. Nothing publishes around it.

```
                         ┌──────────────────────────────┐
 pack publish path ─────►│                              │
 kill-log/sample export ─►│         VOICE GATE           │──► PASS → publish
 Store.Web build (CI) ───►│  grade · classify · rewrite  │──► QUARANTINE → human queue
 future CMS/Medusa ──────►│                              │
                         └──────────────────────────────┘
                          policy = ONE versioned data file
```

1. **Voice profile as data.** One YAML (`voice-policy.yaml`, versioned, in git): rule ids (same R-numbers as HOUSE_WRITING_SPEC), severities, banned lexicon, measured bands from `prose_target.json`, and — new — **lane declarations**: `pack`, `storefront`, `evidence-export`, each with its own register contract. The evidence-export lane explicitly forbids engine scaffolding: verdict labels (`SUPPORTED`, `REFUTED`), "passage(s)", "the strongest case against", numbered citations in prose, hedged research-speak. Replaces today's duplicated Python/Vale rule definitions with one source both consume.
2. **The gate service.** `POST /grade {text, lane, field}` → verdict + itemised findings; `POST /rewrite` → fact-preserving repair, max 2 iterations, else quarantine. Three layers in order: **deterministic** (the existing Python checks — register_lint, house_style, copy_lint, pack_linter — refactored to read the policy file, <50 ms, zero variance); **semantic** (a few-shot LLM classifier: "is this the right register for this lane?" trained on the ombudsman corpus + graded engine prose — this is what catches today's leak); **repair** (existing `shelf_copy_repair` moved behind the gate). Provider-agnostic via LiteLLM, traces to the estate collector (LAW 50, LAW 34).
3. **Admission at every boundary, including the open one.** (a) pack publish path: repoint existing checks at the gate — behaviour preserved, one enforcer; (b) **`make_kill_log.py` / `make_sample_report.py` call the gate and refuse to export failing prose — this closes the live leak**; (c) Store.Web CI step grades `src/data/*.json` + `.tsx` copy through the gate API, replacing Vale; (d) future Medusa/CMS writes go through the same endpoint.
4. **Measurement.** Coverage (% of rendered strings gate-graded — provable by query, not file scan), score trend per lane, quarantine depth, repair success rate. Reported to the collector; a storefront cannot deploy below threshold.
5. **Enterprise capability.** The gate is product-agnostic: one voice profile per client, API + CI bot + audit trail, self-hosted (LAW 19). This is the "Acrolinx for machine-generated catalogues" shape — the thing buyers at diligence ask for and the thing we can sell.

## 5. Build plan (after acceptance)

| Phase | Deliverable | Done when |
|---|---|---|
| 0 — stop the bleed (½ day) | Gate check wired into `make_kill_log.py`/`make_sample_report.py`; scrub + regenerate live JSONs | "passage"/"SUPPORTED" count in `src/data/*.json` = 0; how-it-works reads as copy |
| 1 — consolidate (2–3 days) | `voice-policy.yaml`; the four Python linters read it; gate service with `/grade` deterministic layer | one rule definition per id; existing pack-lane tests green |
| 2 — semantic layer (2 days) | few-shot register classifier + bounded rewrite loop | graded set: ≥95% agreement with human labels on a 100-string golden sample |
| 3 — boundaries (2 days) | publish path repointed; Store.Web CI step replaces Vale | CI fails on an injected off-register fixture; green on main |
| 4 — productise (3 days) | per-client profiles, audit API, coverage metrics to collector | a second "client" profile grades a sample corpus via API with full receipts |

**Cost:** mostly consolidation of code that exists; semantic layer runs on the cheap alias; ~$0 marginal per grade at current volume.

## 6. What this is not

- Not another linter in the engine. Not a ninth module.
- Not Vale-with-more-rules (measured: 95.7% noise).
- Not Acrolinx/Writer (seat-priced SaaS, corpus leaves the estate, not ours to sell).
- Not a prompt change (measured: does not hold).

## 7. Acceptance

Say go and phase 0 lands first: the live pages stop showing research prose the same day, then the gate is built underneath. The risk in one sentence: the semantic classifier needs a graded golden sample to tune against, and phase 2's agreement target is where the honest work sits — phases 0–1 are mechanical and carry no judgement risk.
