# Voice Gate — the rest: execution spec for phases 1–4 and the hand-off packages

**Status:** v1, 2026-09-06 · **Base:** `specs/voice-gate-2026-09-06.md` (phases + safety case), PR #819 (phase 0 merged-candidate). **Portal work is specced separately:** idp `docs/specs/2026-09-06-portal-100.md` (crew#883); only its Voice-Gate touchpoint (lane 7) appears here.
**Owner key:** ARCH = architect session (domain knowledge), CON = contractor (no domain knowledge; brief in §6), FND = founder.

---

## 1. Phase 1 — conformance harness (ARCH, hours)

Prove the Rust gate reproduces the Python oracle before it earns anything (spec §15 mechanism 6: prove-then-switch).

### 1.1 Corpus match-set diff
- **Corpus:** the 2026-08-08 measured corpus (312,886 words of engine prose — locate under `tools/experiments/` or regenerate via the same script) + live `src/data/*.json` + 100 most recent pack documents from `publish/bundles`.
- **Harness:** `tools/voice_gate_corpus_diff.py` — for every policy pattern (EE1–EE5 first, then R9 lexicon): compute the match span set over the corpus with Python `re`; call the Rust gate's `/v1/grade` batch endpoint with the same strings; compare findings (rule_id, span) set-for-set.
- **Output:** `store/voice_gate/corpus-diff.json` — per rule: `{pattern, python_matches, rust_matches, diff_examples[]}`; exit 1 on any non-empty diff.
- **Done when:** diff empty over the full corpus; committed receipt.

### 1.2 Differential fuzzing
- `tests/voice_gate/test_differential.py` (hypothesis): strategies mutate real storefront/pack strings — dash insertion, banned-token injection (sampled from the R9 lexicon), entity swaps (£↔$, name permutation), whitespace/case noise — assert Python-oracle verdict == Rust verdict on every generated string. 10k cases in CI (seconds at DFA speed).
- **Done when:** green in CI; any disagreement triaged to a rule-semantics inventory entry.

### 1.3 Golden sample vs oracle
- The §5 golden sample (100 strings) run through BOTH runtimes; verdict table committed; this is also the Tier-2 benchmark baseline.
- **Done when:** 100/100 agreement printed in the receipt.

## 2. Phase 2 — Tier 2 semantic classifier (ARCH + CON, 1 day parallel)

### 2.1 Golden sample production (CON brief B1 + ARCH review)
- **Source pools:** 50 leaks — harvested from pre-scrub `kill-log-examples.json` (git history), pre-scrub `sample-report.json` (git show HEAD~N), pack history; 50 clean — live `.tsx` copy, post-scrub exports, ombudsman-normalised prose.
- **Format:** `prospector/voice_gate/golden.jsonl` — `{id, lane, text, label: leak|clean, source}`.
- **Protocol:** two independent labels per string; disagreements → ARCH; FND spot-checks 20 (one 15-minute sitting).
- **Done when:** 100/100 double-labelled, inter-labeler agreement ≥95% before ARCH resolution.

### 2.2 Engine benchmark (CON brief B2)
- **Env:** OCI Ampere A1 (2 core, 12 GB) or the closest available ARM64 shape; ubuntu 22.04+; nothing estate-specific.
- **Models:** `Llama-3.2-1B-Instruct-Q4_K_M.gguf`, `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` (HF).
- **Measure:** single-token verdict latency (prompt in §2.3) via (a) llama.cpp `llama-server` logprobs, (b) candle reference binary; report P50/P99/P999, RSS, load time, per model × engine.
- **Deliverable:** `benchmarks/tier2-arm64-<date>.json` + raw logs; **the winner is picked on this receipt, not on reputation** (spec §15).

### 2.3 Tier-2 integration (ARCH)
- Prompt (lane-tagged, ≤6 exemplars from golden pool, ends `Verdict (0=lane-correct, 1=register-leak):`), `n_predict=1`, top-1 logprob = confidence; <0.80 → frontier alias `cheap` (same prompt), verdict authoritative, appended to `finetune-candidates.jsonl`.
- Wired into the Rust service behind the existing `/v1/grade` (`tier_reached`/`confidence` fields already in the §3 schema); `spawn_blocking` for inference; mmap model load.
- **Done when (benchmark gate):** ≥95% agreement with human labels, ≥90% leak recall, P99 printed from the receipt; fallback rate <10% over 24h of grades.

## 3. Phase 3 — cutover and the storefront lane (ARCH, same day as four greens)

1. `VOICE_GATE_IMPL=rust` on the export scripts (env flag already specced §15.9) and pack path.
2. **Store.Web `scripts/lint-copy.mjs`** (new): walks `src/data/*.json` (every prose leaf, walker semantics) + page copy strings; batch-grades via the gate; kills reasons graded post-`plainEnglish` output (the serve seam — reuse `src/lib/plainEnglish.ts`); exit 1 on any FAIL. Wired into `npm run verify`.
3. Vale retirement: delete `styles/Mumchimp/*.yml` + `.vale.ini` after lint:copy green on main; `.github/workflows` adversarial fixture job (planted leak must fail).
4. **Done when:** planted-leak fixture fails CI; main green; Vale files gone in the same PR.

## 4. Phase 4 — the product (ARCH design + CON build, 3–5 days)

1. **GLiNER fact-lock (Tier 3, built by B5, ARCH reviews):** `ort` (ONNX Runtime Rust) + `gliner-small-v2` (~150 MB); extract `{entities, dates, money, urls}` pre-rewrite; rewrite (Mode A local infill / Mode B BYOK frontier); post-check: extracted sets must match source, else `preserved_ok=false` ⇒ QUARANTINE (never a mutated fact).
2. **Extism WASM plugins (built by B5, ARCH reviews):** `POST /v1/plugins` mounts a client `.wasm` rule pack (deterministic Tier-1 additions); sandboxed; policy file references plugin rule ids. The resale differentiator — clients extend without disclosing IP.
3. **Image:** multi-arch (`linux/arm64`, `linux/amd64`) distroless build (brief B3); `docker run` → `/v1/health` green; RSS ≤ 2 GB hard, ~650 MB target **measured on the OCI shape** (B2 env).
4. **Audit API:** `GET /v1/receipts?since=` — every grade/rewrite/quarantine with policy version hash; the enterprise receipt.
5. **Catalog + standards row:** idp Backstage entity for the service; "Content governance" row in `crew/docs/STANDARDS.md`; OTLP metrics already specced (§9 of the main spec).
6. **Done when:** a second "client" policy grades a foreign corpus via the image with full receipts; OCI envelope numbers printed.

## 5. E-SLM — estate small-model routing (ARCH, own plan after phase 2)

Verdict-shaped engine tasks (`classify.py`, `prescreen*.py`, `admissibility.py`, `kill_filter.py`) route local-first (Tier-2 runtime, single-token pattern), frontier on low confidence. Same conformance discipline: 7-day shadow receipt vs current LiteLLM verdicts, $/pack delta measured against existing receipts. **Admission condition:** Voice Gate phase 2 green — the pattern is proven once before it is generalised (spec §16).

## 6. Hand-off briefs (copy-paste to contractor/consultant)

**B1 — Golden-sample labelling (CON).** You get: two source pools (paths), the labelling sheet, the two definitions ("leak" = engine/research register — verdict labels, "passages", diligence framing, citation lines, hedge scaffolding; "clean" = customer copy). You produce: 100 double-labelled rows in the given JSONL shape, disagreements flagged. No estate access needed; the pools are two files.

**B2 — SLM benchmark, split in two (CON).** B2a (engine decision, any ARM64 — a Mac or Linux ARM box is fine, NO OCI needed): download the two named GGUFs, run the supplied 50-string prompt set through llama.cpp server and the candle reference binary, `n_predict=1`, logprobs on; report P50/P99/RSS/load-time per model × engine. Lands day 1. B2b (product envelope proof): same protocol on the OCI Ampere A1 shape; the enterprise receipt. Lands in parallel. Pure ops; no estate code.

**B5 — GLiNER + Extism skeleton (CON).** In `idp/platform/voice-gate` (existing Rust crate): (a) `src/facts.rs` — GLiNER-small-v2 via the `ort` ONNX crate, `extract(text) -> {entities, dates, money, urls}` with unit fixtures; (b) `src/plugins.rs` — Extism host: mount a `.wasm` rule pack, invoke `grade(text) -> findings_json`, sandboxed, one example plugin + test. Behind cargo feature flags `facts`/`plugins`; no API changes; `cargo test --all-features` green. Given: the crate path and spec §4/§6 contracts.

**B3 — Image packaging (CON).** Given the crate path and this spec's Dockerfile review notes (distroless, non-root, `target-cpu=neoverse-n1`, dep-cache layer, model-less image — models mounted at runtime), produce the multi-arch Dockerfile + GitHub Actions build/publish workflow to ghcr. Acceptance: `docker run` prints `/v1/health` green on both architectures.

**B4 — Portal plumbing (CON, crew#883 lanes 4/6).** Playwright visual-regression over the six founder pages (animations off, structure-level assertions only — R53) + Lighthouse budgets (LCP ≤2.5 s) wired into idp CI. Given: the idp repo paths and the two lane clauses from `docs/specs/2026-09-06-portal-100.md`.

## 7. What stays with ARCH (never handed off)

Policy rules and lexicon; the corpus-diff oracle; Tier-2 exemplars and prompt; pack-lane semantics; sign-off on every green; anything touching money, identity, or the store of record (founder fence).

## 8. Critical path

PR #819 merge (FND) → 1.1+1.2+1.3 (hours) ∥ B1+B2 start today (CON) → phase 2 integration (1 day) → phase 3 (same day) → phase 4 (B3+B4 ∥ ARCH) → E-SLM plan. Every step has its green named above; nothing waits on time, only on proof.

## 9. The compression (founder 2026-09-06, revised same day): Tier 2 is the product — it stays

**Founder override of the earlier deferral note: "we are building enterprise level product not regex."** Correct, and the spec now says so plainly: a gate whose only net is a lexicon is a linter, and the market already has linters. The semantic classifier is what separates the product from Vale-with-a-YAML — the phase-0 evidence (47/47 lexical) describes today's leaks from OUR engine; client deployments grading arbitrary generators will see register failures no lexicon anticipates. Tier 2 is on the critical path, full stop.

**Where the compression legitimately comes from: parallelism, not deletion.** Every domain-free package starts today, in parallel; the serial chain shrinks to what actually depends on what.

| Day | ARCH (only domain work) | Parallel (contractor/consultant, briefs §6) | FND |
|---|---|---|---|
| 1 | corpus diff + fuzz (hours); exemplar selection from golden pools | B1 golden-sample labelling starts; B2 ARM64 benchmark env starts; B3 image; B5 GLiNER+Extism skeleton; idp fire briefs F1–F4 | merge #819 → deploy (site clean tonight) |
| 2 | Tier-2 integration (prompt, logit confidence, frontier fallback) | B1 labels land; B2 latency receipt lands; review cycles | 15-min sitting: the five |
| 3 | benchmark gate: ≥95% agreement / ≥90% leak recall / P99 printed; four greens → flip flag; lint:copy; Vale deleted (phase 3) | portal fires verified green | — |
| 4–5 | audit API + standards row + catalog entity; E-SLM shadow receipt | image both archs with receipts; portal lanes 4–6 via B4 | UAT: the five |

Gate shipped WITH the semantic layer: **day 3**. Product image with receipts: **day 5**. Naive serial was ~15 days; the parallel plan lands in 5 with nothing specced removed. The benchmark gate (≥95% agreement) is what proves Tier 2 — that was always the honesty mechanism, and it stays.
