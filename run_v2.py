"""V2 Pipeline Runner — wires the v2 modules to real operators."""
from __future__ import annotations

import time
from pathlib import Path

from popdd_agent import PopddAgent  # POPDD proof trail (estate Phase 1, 2026-06-26)
from prospector.config import load_config
from prospector.domain.primitives import CandidateJourney
from prospector.operator import _build_operator
from prospector.pipeline.generator import generate_candidates
from prospector.pipeline.middleware import TribunalMiddleware
from prospector.pipeline.verifier import run_moat


def _sign_run_receipt(results: dict, n_specs: int) -> None:
    """Sign this DeepSeek run's outcome into the POPDD chain (.lux/receipts/).

    Forward proof for R5 ("POPDD demonstrably runs on prospector/DeepSeek"): every
    run leaves a signed, hash-chained record of what it produced. Best-effort — a
    receipt failure must never break the run, so all errors are swallowed loudly.
    """
    try:
        root = Path(__file__).resolve().parent
        agent = PopddAgent.at_path(root)
        agent.sign_generic(
            action="deepseek-run:complete",
            target="prospector:deepseek-run",
            **{
                "verdict": "PASS" if results.get("PASS", 0) > 0 else "NONE",
                "model": "deepseek",
                "candidates": n_specs,
                "passed": results.get("PASS", 0),
                "pivot": results.get("PIVOT", 0),
                "kill": results.get("KILL", 0),
            },
        )
        chain = agent.verify_chain()
        print(f"\n🔏 POPDD receipt signed (chain valid: {chain['valid']}) → .lux/receipts/")
    except Exception as e:  # never let proof-keeping break the run
        print(f"\n⚠️  POPDD receipt NOT signed: {e}")

# ── LLM call adapters ────────────────────────────────────────────────────

def make_llm_caller(kind: str, fast: bool = False):
    """Build a callable (system, user) -> str using the configured operator."""
    cfg = load_config()
    op = _build_operator(kind, cfg, fast=fast)

    def call(system: str, user: str) -> str:
        return op._raw(system, user, 0.7)

    # Attach metadata for diagnostics.
    call._name = op.name  # type: ignore[attr-defined]
    return call


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()
    print(f"Operator chain: {cfg.operator}")
    print(f"Store dir:      {cfg.store_dir}")
    print("Ledger:         storage/durable_ledger.md")
    print()

    # ── Step 1: Generate candidates with ledger amnesia cure ──────────
    gen_llm = make_llm_caller("deepseek", fast=True)
    print(f"Generator: {gen_llm._name}")  # type: ignore[attr-defined]

    structural_forms = ["vertical_tool", "productized_service"]
    target_audiences = ["smb_owner", "freelancer_creative"]

    print(f"Generating {len(structural_forms)}×{len(target_audiences)} = "
          f"{len(structural_forms)*len(target_audiences)} candidates...")
    t0 = time.time()

    specs = generate_candidates(
        signal_text="AI tools for UK small businesses under £50/month",
        structural_forms=structural_forms,
        target_audiences=target_audiences,
        llm_call=gen_llm,
        k_per_form_audience=1,
    )

    gen_elapsed = time.time() - t0
    print(f"  Generated {len(specs)} candidates in {gen_elapsed:.1f}s")
    for s in specs:
        print(f"    [{s.id}] {s.core_concept_prose[:80]}...")
    print()

    if not specs:
        print("No candidates generated — aborting.")
        return

    # ── Step 2: Verify each candidate through the v2 Moat ──────────────
    moat_llm = make_llm_caller("deepseek", fast=False)
    print(f"Verifier: {moat_llm._name}")  # type: ignore[attr-defined]
    tribunal = TribunalMiddleware()

    results = {"PASS": 0, "PIVOT": 0, "KILL": 0}
    for i, spec in enumerate(specs):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(specs)}] Vetting: {spec.core_concept_prose[:70]}...")
        journey = CandidateJourney(spec_id=spec.id)
        t0 = time.time()

        try:
            contract = run_moat(spec, journey, moat_llm, tribunal=tribunal)
            verdict = contract.verdict_declaration
            elapsed = time.time() - t0
            status = verdict.status
            results[status] = results.get(status, 0) + 1

            print(f"  Verdict: {status}  ({elapsed:.1f}s)")
            if status == "KILL" and verdict.new_ledger_law:
                print(f"  Law:     {verdict.new_ledger_law[:100]}")
            elif status == "PIVOT" and verdict.pivot_payload:
                print(f"  Axis:    {verdict.pivot_payload.axis}")
                print(f"  Prompt:  {verdict.pivot_payload.generator_prompt[:100]}")
            print(f"  Adversarial: {contract.adversarial_attack[:120]}")

            # Show gates
            gates = contract.gate_evaluations
            for gate_name, gate_obj in [
                ("Legality", gates.gate_1_legality),
                ("PayerSolvency", gates.gate_2_payer_solvency),
                ("Distribution", gates.gate_3_distribution),
                ("Incumbency", gates.gate_4_incumbency),
                ("ValueDurability", gates.gate_5_value_durability),
            ]:
                flaw = "💀" if gate_obj.fatal_flaw else "✓"
                short = (
                    getattr(gate_obj, "differentiation_proof", "")
                    or getattr(gate_obj, "regulatory_body", "")
                    or getattr(gate_obj, "existing_line_item_budget", "")
                    or getattr(gate_obj, "unpaid_acquisition_wedge", "")
                    or getattr(gate_obj, "why_not_a_vitamin", "")
                )
                if short and short != "SHORT_CIRCUITED":
                    print(f"    {flaw} {gate_name}: {str(short)[:80]}")
                else:
                    print(f"    {flaw} {gate_name}: SHORT_CIRCUITED")

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR after {elapsed:.1f}s: {e}")
            results["KILL"] = results.get("KILL", 0) + 1

    # ── Step 3: Report ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"  PASS:  {results.get('PASS', 0)}")
    print(f"  PIVOT: {results.get('PIVOT', 0)}")
    print(f"  KILL:  {results.get('KILL', 0)}")
    print(f"  Total: {sum(results.values())}")

    # Show ledger growth
    # A tracked repo artifact, so it moves with the CODE, not with the store. It was read
    # relative to the working directory, so it silently read nothing from anywhere else.
    ledger = Path(__file__).resolve().parent / "storage" / "durable_ledger.md"
    if ledger.exists():
        laws = [ln for ln in ledger.read_text().splitlines() if ln.strip().startswith("*")]
        print(f"  Ledger laws: {len(laws)}")
        for law in laws[-5:]:
            print(f"    {law.strip()[:100]}")

    # ── Step 4: Sign the run into the POPDD proof chain ───────────────
    _sign_run_receipt(results, len(specs))


if __name__ == "__main__":
    main()
