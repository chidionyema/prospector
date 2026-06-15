# MiniMax task spec — Generation variety (one-shot)

You are implementing **generation-side variety** changes only. This is a precise,
self-contained spec. Make exactly the edits below, then run the acceptance gate.

## HARD GUARDRAILS (violating any = task failed)
1. **Generation only.** DO NOT touch verification, grounding, or scoring: leave
   `verify.py`, `kill_filter.py`, `score.py`, `retrieval.py`, and the `hard_gates`,
   `thresholds`, `weights` blocks in `config.yaml` completely unchanged.
2. **DO NOT weaken, reorder, or rename any gate.** No gate logic changes at all.
3. **DO NOT edit `prospector/operator.py`** — another process owns it right now.
   Editing it will cause a collision.
4. **DO NOT change** `models.py`, the failover chain, or any test file.
5. Preserve every existing comment and the wave/fan-out/dedup logic in `generate.py`
   exactly — you are only THREADING a new value through it, not restructuring it.

## ACCEPTANCE GATE (must pass before you are done)
- Run: `.venv/bin/python -m pytest tests/ -q` → **all tests pass** (baseline: 163 passed).
- If ANY edit to `generate.py` makes a test fail, **revert `generate.py` to its original
  content** and report exactly which step failed. Do not leave it broken. (The other
  files — prompts/config — are low risk; the risk is only in `generate.py`.)
- Do NOT run the golden set or judge idea quality — that is done separately by Claude.

---

## CHANGE 1 — Concrete anti-obvious counterexamples (prompt only, zero code)
**File:** `prompts/generate_system.md`
**Find this paragraph** (the abstract ANTI-OBVIOUS RULE):
```
ANTI-OBVIOUS RULE: ban consensus plays. If an idea is the first thing a smart
operator would think of, it is too obvious — push further until genuinely non-obvious,
then state in one phrase WHY it is non-obvious. Each idea must name a *specifically
nameable* payer (e.g. "regional letting agents", not "consumers"/"SMEs").
```
**Replace it with:**
```
ANTI-OBVIOUS RULE: ban consensus plays. If your idea matches any of these CONSENSUS
shapes for its signal type, it is too obvious — push further until genuinely non-obvious,
then state in one phrase WHY it is non-obvious:
  - Regulatory/compliance signal → NOT a compliance dashboard, filing tool, audit
    tracker, or "AI for compliance" wrapper.
  - Lending/credit signal → NOT a credit-scoring tool, lending marketplace, or rate
    comparison site.
  - Tax signal → NOT an accounting SaaS, tax-filing tool, or bookkeeping app.
  - Insurance/risk signal → NOT a broker, price comparison, or claims-management tool.
  - Data-access/portability signal → NOT a generic "central registry / data hub / rating".
If your idea would appear as a category on G2.com or Capterra, it is TOO OBVIOUS — go again.
Each idea must name a *specifically nameable* payer (e.g. "regional letting agents",
not "consumers"/"SMEs").
```

---

## CHANGE 2 — Audience/persona axis (the high-impact variety lever)
All ideas currently target institutional B2B buyers. Add a SECOND orthogonality axis —
WHO the idea is for — rotated alongside the structural form.

### 2a. `config.yaml` — add an `audience_forms` list under `generation:`
Insert this block inside the `generation:` section, immediately AFTER the
`structural_forms:` list and BEFORE `archetypes:` (do not touch anything else):
```yaml
  # AUDIENCE axis (second orthogonality dimension). structural_forms vary HOW value is
  # captured; audience_forms vary WHO is served. Rotated alongside form so each call owns
  # a distinct (form × audience) cell — breaks the institutional-B2B monoculture.
  audience_forms:
    - retiree_cohort          # 60+, capital + time + health anxiety
    - gen_z_worker            # 18-27, gig/digital-native, low savings
    - smb_owner               # 1-20 employee owner-operator
    - primary_carer           # parents/guardians of children or elderly
    - public_sector_worker    # nurses, teachers, civil servants
    - manual_tradesperson     # construction, logistics, hospitality
    - freelancer_creative     # designers, writers, consultants
    - squeezed_middle         # 35-55, dual-income, asset-rich cash-poor
```

### 2b. `prompts/generate.md` — add an audience slot
**Find this line:**
```
  STRUCTURAL FORM for THIS batch (the BUSINESS SHAPE every idea here MUST take): {structural_form}
```
**Add immediately BELOW it:**
```
  AUDIENCE this batch serves (a SPECIFIC human/buyer with a name, budget, daily problem — NOT "consumers"/"SMEs"/"a company"): {audience_persona}
```

### 2c. `prospector/generate.py` — thread `audience` through (4 precise edits)
The risk lives here. Make EXACTLY these four edits; change nothing else.

**Edit i** — after the `operator_constraints = ...` block (just before the
`# FIX #5:` comment), add the audiences list. Find:
```python
    operator_constraints = " ".join(
        s for s in (str(arche_cfg.get("binding", "")).strip(),
                    str(arche_cfg.get("forbid", "")).strip()) if s)
```
Insert AFTER it:
```python
    # Second orthogonality axis: the audience/persona this batch is built for.
    audiences = [str(a).strip() for a in (gen_cfg.get("audience_forms") or []) if str(a).strip()]
```

**Edit ii** — `_one_call` gains an `audience` parameter and passes it to render. Find:
```python
    def _one_call(form: str, lens: str, ask: int, avoid: str, seed: str) -> list[Candidate]:
        system, user = render(
            "generate", signal_text=signal_text, sector=sector, strategy_lens=lens,
            structural_form=form or "any feasible form", operator_constraints=operator_constraints,
            exploration_level=exploration_level, target_qualities=target_qualities,
```
Replace with:
```python
    def _one_call(form: str, lens: str, audience: str, ask: int, avoid: str, seed: str) -> list[Candidate]:
        system, user = render(
            "generate", signal_text=signal_text, sector=sector, strategy_lens=lens,
            structural_form=form or "any feasible form", operator_constraints=operator_constraints,
            audience_persona=(audience or "(any specifically-nameable buyer)"),
            exploration_level=exploration_level, target_qualities=target_qualities,
```

**Edit iii** — `_assign` returns a triple (form, lens, audience). Find:
```python
        def _assign(i: int) -> tuple[str, str]:
            form = forms[(offset + i) % len(forms)] if forms else ""
            return form, lenses[i % len(lenses)]
```
Replace with:
```python
        def _assign(i: int) -> tuple[str, str, str]:
            form = forms[(offset + i) % len(forms)] if forms else ""
            # stride by wave so the form↔audience pairing shifts each wave (matrix coverage)
            audience = audiences[(wave - 1 + i) % len(audiences)] if audiences else ""
            return form, lenses[i % len(lenses)], audience
```

**Edit iv** — the two CALL SITES that unpack `_assign` and call `_one_call`.
Site A, inside `_fan_out._go`. Find:
```python
                def _go(i: int) -> tuple[str, list[Candidate]]:
                    form, lens = _assign(i)
                    return form, _one_call(form, lens, ask, avoid, f"{wave}.{i + 1}")
```
Replace with:
```python
                def _go(i: int) -> tuple[str, list[Candidate]]:
                    form, lens, audience = _assign(i)
                    return form, _one_call(form, lens, audience, ask, avoid, f"{wave}.{i + 1}")
```
Site B, the wave-1 canary. Find:
```python
            f0, l0 = _assign(0)
            batches = [(f0, _one_call(f0, l0, ask, avoid, f"{wave}.1"))]
```
Replace with:
```python
            f0, l0, a0 = _assign(0)
            batches = [(f0, _one_call(f0, l0, a0, ask, avoid, f"{wave}.1"))]
```

That is the complete `generate.py` change — one new variable, one new parameter,
one widened tuple, two updated call sites. The dedup/wave logic is untouched.

---

## CHANGE 3 — Diversify discovered signals off the regulatory monoculture (prompt only)
**File:** `prompts/discover.md`
Every discovered signal is currently a regulatory/compliance change, which funnels all
downstream ideas into B2B-compliance. Add a per-batch signal-class QUOTA. Add this
paragraph to the USER section of the prompt (near where it asks for N signals):
```
SIGNAL-CLASS QUOTA (enforce across the batch): at MOST half of the signals may be
regulatory/compliance changes. The REST must come from these non-regulatory classes —
spread across at least three of them: technology inflection, demographic/behavioral
shift, supply-chain dislocation, price shock, expiring patent, platform-policy change.
Do NOT return an all-regulatory batch.
```
Do not change `discover.py` logic.

---

## CHANGE 4 — MiniMax generation model → chat model (one line)
Generation needs creative divergence (temperature 0.9), so use MiniMax's CHAT model,
not the reasoning model.
**File:** `prospector/run.py`  **Find:**
```python
        gen_op = _build_operator("minimax", cfg, fast=False)
```
**Replace with:**
```python
        gen_op = _build_operator("minimax", cfg, fast=True)  # chat model (abab6.5s-chat) for creative divergence
```
(Do NOT edit `operator.py` to achieve this — the `fast=True` flag already selects the
chat model. `operator.py` is owned by another process.)

---

## When done
1. `.venv/bin/python -m pytest tests/ -q` → all pass.
2. Report: which of Changes 1–4 you applied, and confirm the test count is unchanged.
3. Hand back to Claude for the golden-set re-run (do not run it yourself).
