# Voice Gate — one enforcement point for every word a customer reads

**Status:** v2, awaiting founder acceptance. Nothing here is built.
**Date:** 2026-09-06 · **Author:** crew session · **Scope:** prospector engine → mumchimp storefront content quality

**v2 changes (founder review, same day):** the architecture is now the founder's 3-tier zero-GPU design (native deterministic core → local 1B SLM classifier → constrained/BYOK rewrite); the ombudsman corpus is repositioned as the gate's training data; plain verdicts on "does it solve it" and "is it resellable" are stated in §5; an estate-wide small-LLM routing initiative (E-SLM) is named as a follow-on.

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

The consistent architecture across all credible sources (and the one LAW 43 + LAW 19 point to): **a self-hosted gate, voice policy as versioned data, deterministic layer + semantic layer + bounded repair loop, admission control at every publication boundary, full audit trail.** Buy nothing; the hard intellectual property — the measured rules, the lexicon, the corpus bands, the repair loop — already exists in this repo, scattered across the eight modules above. The build is consolidation, not invention.

Sources: trustradius.com/compare-products/acrolinx-vs-writer-com · zendikt.com/product/acrolinx · slopads.com/blog/enterprise-grammar-tone-enforcement-tools-2026-indepth-comparison-of-the-top-solutions · slatehq.com/blog/ai-content-governance-tools · markup.ai/product · zerodrift.ai/solutions/ai-agents-copilots · rapidapi.com/captainarmoreddude/api/contentforge1 · oleno.ai/blog/implement-a-brand-voice-rule-engine-for-autonomous-content-pipelines · brandlabs.cloud/api-playbook-for-automated-brand-voice-across-channels · blog.trysteakhouse.com/blog/tone-enforcement-architecture-eliminating-generic-ai-syntax-automated-content-pipelines · cyberax.com/ai-playbook/brand-voice-guardrails · oorbyte.com/how-to-build-a-pre-launch-ai-output-audit-pipeline-for-brand · docs.vale.sh · github.com/vale-cli/vale · github.com/tbhb/vale-ai-tells

## 4. The proposal: Voice Gate

One gate. Every string a customer can read must pass it. Nothing publishes around it. The architecture is the founder's 3-tier zero-GPU design — deterministic native core, local small-language-model classifier, invariant-preserving rewrite — which is also what makes the product resellable (§5).

```
 incoming string / agent JSON     from: pack publish · kill-log/sample export · Store.Web CI · future CMS
                │
                ▼
 TIER 1  deterministic core      voice-policy.yaml rules, regex DFA, AST on JSON/MD,
         <1 ms, ~30 MB            reading-grade bands from prose_target.json
                                  ── ~90% of defects stop here
                │ PASS
                ▼
 TIER 2  local SLM classifier    llama.cpp, Llama-3.2-1B / Qwen-2.5-1.5B, Q4_K_M, ~1.2 GB RAM,
         15–30 ms target, $0      SINGLE-TOKEN verdict (0 = lane-correct, 1 = register leak);
                                  top-1 logit doubles as the confidence score
                │ FAIL / LOW-CONFIDENCE
                ▼
 TIER 3  rewrite                 Mode A: constrained local infill (GBNF grammar pins named
                                  entities, dates, figures — no invented facts)
                                  Mode B: frontier API — client's own key for the product
                                  (BYOK), estate LiteLLM alias for us; also the confidence
                                  fallback for Tier 2
                │ still failing after 2 iterations
                ▼
         QUARANTINE → human queue
```

1. **Voice profile as data.** One `voice-policy.yaml`, versioned, in git: rule ids (same R-numbers as HOUSE_WRITING_SPEC), severities, banned lexicon, measured bands from `prose_target.json`, and — new — **lane declarations**: `pack`, `storefront`, `evidence-export`, each with its own register contract. The evidence-export lane explicitly forbids engine scaffolding: verdict labels (`SUPPORTED`, `REFUTED`), "passage(s)", "the strongest case against", numbered citations in prose, hedged research-speak. One source of truth; the eight scattered modules' *rules* move here and their plumbing is deleted.
2. **Tier 1 reuses what is measured, not rewritten.** The existing Python checks (register_lint, house_style, copy_lint, pack_linter) already embody the graded rules; they are consolidated onto the policy file behind one admission call first, and re-implemented natively (Rust/Go, ARM64+amd64) only when the product ships — the language is a packaging decision, not a correctness one.
3. **Tier 2 is trained by the ombudsman work, not instead of it.** The FOS corpus + 766 graded engine documents are the few-shot exemplars and, later, the fine-tune set for the register classifier. The 2026-08 experiment's only mistake was scope: it tuned sentence-length bands when its real value was as labelled human prose. Tier 2 cashes that value.
4. **Admission at every boundary, including the open one.** (a) pack publish path repointed at the gate — behaviour preserved, one enforcer; (b) **`make_kill_log.py` / `make_sample_report.py` call the gate and refuse to export failing prose — this closes the live leak**; (c) Store.Web CI step grades `src/data/*.json` + `.tsx` copy through the same API, replacing Vale; (d) future Medusa/CMS writes go through the same endpoint.
5. **Measurement.** Coverage (% of rendered strings gate-graded — provable by query, not file scan), score trend per lane, quarantine depth, Tier-2 agreement rate, local-vs-fallback ratio. Emitted to the estate collector (LAW 50); a storefront cannot deploy below threshold.

## 5. Verdicts on the founder's four questions

**Does it solve the problem?** Yes — for the one reason the eight previous fixes lacked: it is admission control on the boundary, not advice inside a lane. Every past attempt let prose reach the page around the checker. The residual risk is named honestly: the 1B classifier's accuracy is the load-bearing unknown, so phase 2 carries a benchmark gate (≥95% agreement with human labels on a 100-string golden sample) plus a confidence fallback — low-confidence verdicts escalate to a frontier model. If the 1B misses the target we ship on the fallback and fine-tune; the leak stays closed either way.

**Resellable or constrained to us?** Resellable. Per-seat SaaS (Acrolinx/Writer) cannot walk into a security-reviewed platform team the way an air-gapped, zero-egress, sub-2 GB sidecar can: no GPU, no data leaving their VPC, no per-token bill, no InfoSec review. Packaging: one multi-arch Docker image (`linux/arm64`, `linux/amd64`), policy file per client, audit API. "The 15 ms zero-egress safety sidecar for autonomous agents." What makes it *ours* rather than a diagram anyone can draw is the measured IP already in this repo: the R-lexicon graded on 2,187 dossiers, the human-register bands from the 766-vs-270 corpus measurement, and a live defect corpus (the mumchimp leak itself) as the demo.

**The ombudsman corpus and the other controls, versus this?** Not versus — they are inside it. Rules → `voice-policy.yaml`; bands → Tier 1; corpus → Tier 2's training data; shelf_copy_repair → Tier 3 Mode A. Deleted: only the duplicated plumbing. Nothing measured is thrown away.

**Small LLMs across the estate — money on the table?** Agreed, and bigger than this product. Estate policy already prices ollama at $0 marginal; the missing step is routing the engine's *verdict-shaped* tasks (classify, prescreen, admissibility, kill-filter — all single-token answers) local-first, frontier on low confidence. Named here as **follow-on initiative E-SLM** (same pattern, same benchmark discipline, applied to engine spend) so this proposal does not bloat; it gets its own one-page plan after Voice Gate phase 2 proves the Tier-2 pattern in production.

## 6. Build plan (after acceptance)

| Phase | Deliverable | Done when |
|---|---|---|
| 0 — stop the bleed (½ day) | Assertive check wired into `make_kill_log.py`/`make_sample_report.py` (exit 1 on forbidden scaffolding); scrub + regenerate live JSONs | "passage"/"SUPPORTED" count in `src/data/*.json` = 0; how-it-works reads as copy |
| 1 — consolidate (2–3 days) | `voice-policy.yaml`; the four Python linters read it behind one gate call | one rule definition per id; existing pack-lane tests green |
| 2 — Tier 2 on local SLM (2–3 days) | llama.cpp serving 1B–1.5B Q4_K_M on existing hardware; single-token verdict + logit confidence; golden sample (100 strings, human-labelled); frontier fallback | **benchmark: ≥95% agreement with human labels; P99 latency measured, not assumed** (the 15–30 ms figure is a target to prove, not a claim) |
| 3 — boundaries (2 days) | publish path repointed; Store.Web CI step replaces Vale | CI fails on an injected off-register fixture; green on main |
| 4 — productise (3–5 days) | Tier-1 native port (Rust/Go ARM64), one multi-arch image <2 GB, per-client policy, audit API | a second "client" profile grades a sample corpus via the image with full receipts |
| E-SLM (separate plan) | route engine verdict-shaped tasks local-first | measured $/pack reduction against current LiteLLM receipts |

**Cost:** phases 0–3 run on hardware we already have; Tier 2 is $0 marginal per grade; frontier fallback is pennies at current volume and shrinks as the classifier is tuned. OCI Always Free (Ampere A1, ARM64) is the reference target for the *product* image in phase 4 — proving it runs in 2 GB there is the enterprise demo; our own hosting does not depend on it.

## 7. What this is not

- Not another linter in the engine. Not a ninth module.
- Not Vale-with-more-rules (measured: 95.7% noise).
- Not Acrolinx/Writer (seat-priced SaaS, corpus leaves the estate, not ours to sell).
- Not a prompt change (measured: does not hold).
- Not GPU infrastructure, not per-token SaaS, not a cloud anyone's data must leave for.

## 8. Acceptance

Say go and phase 0 lands first: the live pages stop showing research prose the same day, then the gate is built underneath. The risk in one sentence: the Tier-2 classifier's accuracy is unproven until the phase-2 benchmark, and the plan is shaped so that even its failure leaves the leak closed on the deterministic tier plus frontier fallback — phases 0–1 are mechanical and carry no judgement risk.
