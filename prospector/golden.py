"""Golden-set harness (Part 14 step 4, Part 16).

Two distinct gates share this file — do not conflate them:

REGRESSION GATE  (pytest -k golden — runs on every change):
  - Uses MockOperator + fixtures.  Proves prompts/config didn't regress.
  - Unchanged by this spec.  CI stays offline/free.

PROMOTION GATE  (python -m prospector.golden --operator deepseek --runs 3):
  - Uses a real model (deepseek/minimax/etc.) + fixtures.  Retrieval really is pinned
    to the fixture provider ALONE as of 2026-08-15 (retrieval.make_provider); before that
    this line asserted a property the code did not have and every query escalated live.
  - Proves THIS model can rule + run adversarial correctly.
  - Discrimination must reach --min-discrimination (default 1.0) on K=3 consecutive
    runs before the model is cleared to enter the moat chain.  Prefer the RELATIVE bar:
    the incumbent's score on the same fixtures and commit, same day.
  - Audit trail: store/golden_runs/<operator>_<ISO8601>.json

See specs/offline-moat-validation.md for the full promotion protocol.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, load_config, store_root
from .models import Candidate, Dossier
from .operator import Operator, make_operator
from .retrieval import SearchProvider, make_provider
from .run import vet_candidate
from .verify import NO_RATIONALE_RATIONALE

OPERATOR_CHOICES = [
    # `claude_cli` was missing here, which made the incumbent unmeasurable: the only stored
    # claude_cli clearances were from 2026-06-16 (discrimination 0.78) and there was no way
    # to refresh them from this CLI — i.e. the trusted brain could not be re-scored on the
    # same fixtures, on the same day, as the challenger it is compared against. That
    # comparison is the whole point of the gate, so its absence was the gate's own blind spot.
    # `claude` (paid API) and `standardcompute` were removed on 2026-08-15 by founder
    # directive — neither had a key on this estate and neither could construct.
    "claude_cli",
    "minimax", "deepseek", "mock",
]

# Surface check: the dossier must SURFACE the case's key reason. We match a keyword
# SUBSET of the expected phrase against the full evidence (reason + check rationales +
# cited source passages), not an exact substring of the model's paraphrased prose.
_SURFACE_STOP = {"with", "that", "this", "from", "being", "already", "over", "into",
                 "under", "than", "then", "they", "them", "their", "there", "have",
                 "been", "will", "your", "ours", "only", "more", "most", "such"}


def _surfaced(must_surface: str, dossier: Dossier, threshold: float = 0.7) -> bool:
    parts = [dossier.reason or ""]
    for c in dossier.checks:
        if c.rationale:
            parts.append(c.rationale)
        for s in (c.sources or []):
            if getattr(s, "text", None):
                parts.append(s.text)
    text = " ".join(parts).lower()
    toks = {t for t in re.findall(r"[a-z0-9\-]+", must_surface.lower())
            if len(t) >= 4 and t not in _SURFACE_STOP}
    if not toks:
        return True
    hits = sum(1 for t in toks if t in text)
    return hits / len(toks) >= threshold


def _mock_vet_candidate(cand: Candidate, *args, **kwargs) -> Dossier:
    """Deterministic in-process mock for test mode.

    Returns KILL for ideas matching 'haulage' (case 1),
    PASS for all others (case 2).
    Keep in sync with the golden set fixture expectations.

    NOT a MagicMock, which is what this was until 2026-08-15.  A MagicMock answers every
    attribute access with another MagicMock, so the per-case audit record (which reads
    `check.check_name`, `.verdict`, `.confidence`, `.citations`) collected mock objects
    without a murmur and the run died two frames later inside `json.dumps` —
    `TypeError: Object of type MagicMock is not JSON serializable` — with a traceback
    that pointed at the audit writer rather than at the stub.  A real `CheckResult`
    makes a missing field an AttributeError at the read, where it is diagnosable.

    `sources=[]` is deliberate and true: `--mock-vet` skips retrieval entirely, so the
    audit must not show evidence that was never fetched.
    """
    from .models import CheckResult, Decision, Verdict

    is_kill = "haulage" in cand.title.lower()

    class _MockDossier:
        """Explicit, so an attribute this stub does not define fails loudly."""
        def __init__(self):
            self.decision = Decision.KILL if is_kill else Decision.PASS
            self.gate_fired = "value_durability" if is_kill else None
            self.reason = ("value has been legislated away, not durable" if is_kill
                           else "Survived all gates")
            self.checks = [CheckResult(
                check_name="value_durability",
                verdict=Verdict.REFUTED if is_kill else Verdict.SUPPORTED,
                confidence=0.9,
                rationale=("value has been legislated away" if is_kill
                           else "all gates passed"),
                citations=[],
                sources=[],
            )]

    return _MockDossier()


def run_golden_set(
    op: Operator,
    search: SearchProvider,
    cfg: Config,
    golden_set_path: str = "fixtures/golden_set.json",
    verbose: bool = True,
    _vet_fn=None,  # internal: override vet_candidate (for --mock-vet test mode)
    skip_adversarial: bool = False,
    fixtures: dict[str, Any] | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Execute the golden set and return (discrimination_metric, results).

    discrimination = correct_count / scored,  where scored = total - deferred
    correct = decision_match ONLY.

    That "ONLY" is the whole caveat, and it was mis-documented here for as long as this
    docstring existed: it claimed `decision_match AND gate_match AND surfaced`, while
    `passed = decision_match` has been the code since the file was written (HEAD's
    golden.py:143).  The difference is not cosmetic — on the claude_cli run of
    2026-08-15, four of nine cases KILLed on a check other than the labelled `gate` and
    still scored correct, so the reported 1.00 means "separated KILL from PASS nine
    times out of nine", NOT "killed for the reason we said".  `gate_match` and
    `surfaced` are computed, printed per case and stored in the audit record; they do
    not move the number.  A separate `gate accuracy` line reports them in aggregate so
    the weaker claim can never be read as the stronger one.

    `fixtures`: the WHOLE fixture dict. When given, each case is served ONLY the
    passages bound to it by its own `fixture_key`, via a provider built per case —
    see the fixture-namespacing comment in the loop for why fuzzy matching cannot
    be trusted here. `search` is then used only as the fallback for a case with no
    binding, which is a fixture-file hole and is printed as one.
    """
    with open(golden_set_path, "r", encoding="utf-8") as f:
        golden_set = json.load(f)

    results = []
    correct_count = 0
    deferred_count = 0
    total = len(golden_set)

    if verbose:
        print(f"\n[Golden Set] Running {total} cases...\n" + "-" * 60)

    for item in golden_set:
        idea = item["idea"]
        expected_decision_str = item["expected"].lower()  # 'pass' or 'kill'
        expected_gate = item.get("gate")
        must_surface = item.get("must_surface")

        if verbose:
            print(f"CASE: {idea!r}")

        # ONE CASE, ONE FIXTURE NAMESPACE. FixtureProvider matches on the QUERY with
        # `score = overlap / len(key_words)` and `_FIXTURE_MIN_MATCH_RATIO = 0.0`
        # (retrieval.py:51,767), so a SHORT key sharing a single common word outranks the
        # long key that actually describes the case. Measured 2026-08-15: the key
        # `"Construction retention"` scored 1.0 against three of `Construction Statutory
        # Adjudication Arbitrage`'s six check queries and served them the retention case's
        # insolvency passage. Lengthening the key recovered three checks and still left
        # `payer_solvency` and `pain_reality` reading the wrong case's evidence — which is
        # the tell that key-tuning is whack-a-mole, not a fix: the matcher cannot know which
        # CASE is running, and no wording makes it know.
        #
        # The harness does know. Binding each case to its own key by name removes the whole
        # collision class by construction: with one key in the namespace, every query under
        # it returns that case's passages and nothing else can win. It also makes a missing
        # binding LOUD (empty namespace -> zero passages -> the NO EVIDENCE line below)
        # rather than silently scoring a brain on a neighbour's evidence.
        _search = search
        if fixtures is not None:
            _key = item.get("fixture_key")
            _bound = {_key: fixtures[_key]} if _key in fixtures else {}
            if verbose and not _bound:
                print(f"    - NO FIXTURE BINDING: golden case {idea!r} has fixture_key="
                      f"{_key!r}, which is not a key in the fixture file. This case is "
                      f"about to be scored on NO evidence.")
            _search = make_provider(cfg, fixtures=_bound)

        # 1. Run the vet.
        cand = Candidate(title=idea, one_liner="")
        dossier = (_vet_fn or vet_candidate)(cand, op, _search, cfg,
                                              skip_adversarial=skip_adversarial)

        # 2. Extract actuals
        actual_decision = dossier.decision.value.lower()  # 'pass' or 'kill'
        actual_gate = dossier.gate_fired

        # 3. Score the case
        # PASS criterion: correct KILL/PASS decision only.
        # Gate ordering (which gate fires first in kill-fast) and citation verbatim are
        # NOT scored — different models may have different kill-fast orderings even when
        # both reach the right verdict. The surface-text check is informational.
        decision_match = (actual_decision == expected_decision_str)

        gate_match = True
        if expected_gate:
            expected_gates = [g.strip() for g in expected_gate.split("/")]
            gate_match = actual_gate in expected_gates

        surfaced = _surfaced(must_surface, dossier) if must_surface else True

        # A DEFER IS NOT A WRONG ANSWER — IT IS NO ANSWER. The engine's own rule ("an
        # exception is never evidence; a failed call DEFERS", verify.py) had no counterpart
        # in the gate that judges brains: a case the brain never got to rule on scored
        # exactly like a case it ruled wrongly. Measured 2026-08-15: claude_cli hit its
        # usage limit partway through a run (18 `usage limit`, 14 HTTP 429 in the log) and
        # the last three cases deferred, printing `discrimination=0.67 → FAIL`. That number
        # measured OUR outage and read as a verdict on the brain — the same misattribution
        # that made me blame minimax for an unpassable fixture earlier the same night.
        #
        # Deferred cases are counted OUT of the denominator, and any defer at all makes the
        # RUN inconclusive (see `deferred` in the return payload): a discrimination computed
        # over six cases is not comparable with one computed over nine, so it may neither
        # promote a challenger nor fail one.
        # NOT EVERY DEFER IS OUR FAULT, and the difference decides whether the run can
        # conclude anything at all.  `verify` DEFERs on two very different events:
        #   * the provider was exhausted or the transport failed — WE could not ask, so
        #     nothing was measured and nothing may be concluded (excluded, run inconclusive);
        #   * the brain replied with a verdict and NO rationale — it answered, unusably.
        #     That IS a measurement of the brain, and a damning one.
        # Treating the second like the first was a defect I introduced the same morning I
        # added the empty-rationale guard: minimax deferred 2 of 9 cases on empty rationales,
        # both were excluded, and the run went INCONCLUSIVE — so a brain whose failure mode
        # is answering without reasons became structurally unable to fail this gate, and the
        # gate became unable ever to decide on it.  A brain is not protected from its own
        # defect by the fact that the defect makes it unusable.
        _no_reason = [c.check_name for c in (getattr(dossier, "checks", None) or [])
                      if getattr(c, "rationale", "") == NO_RATIONALE_RATIONALE]
        unusable = bool(_no_reason)
        deferred = (actual_decision == "defer") and not unusable
        if deferred:
            deferred_count += 1

        passed = decision_match and not deferred and not unusable
        if passed:
            correct_count += 1

        if verbose:
            status = ("⏸ DEFER" if deferred
                      else ("❌ NO REASON" if unusable
                            else ("✅ PASS" if passed else "❌ FAIL")))
            print(f"  Result: {status}")
            if unusable:
                print(f"    - SCORED WRONG: the brain returned a verdict with no rationale "
                      f"on {', '.join(_no_reason)} — an answer with no reason is not a "
                      f"finding (verify.py), and producing one is the brain's failure, not "
                      f"an outage. Counted against it.")
            if deferred:
                print(f"    - NOT SCORED: the brain never ruled (reason: "
                      f"{str(getattr(dossier, 'reason', '') or '')[:120]}). This case is "
                      f"excluded from the denominator and makes the whole run inconclusive.")
            elif not decision_match:
                print(f"    - Decision mismatch: actual={actual_decision}, expected={expected_decision_str}")
            if not gate_match and not deferred:
                print(f"    - Gate note: fired={actual_gate}, golden expected={expected_gate}")
            if not surfaced and not deferred:
                print(f"    - Surface note: {must_surface!r} not found in dossier")
            # A case with no passages at all is not a measurement of the brain — it is a
            # hole in the fixture file, and it must never be read as a score. `NFT
            # marketplace (generic)` was exactly this on 2026-08-15: a golden-set entry
            # with no fixture key, scored anyway.
            # `not deferred`: a deferred case short-circuits before its checks ever attach
            # passages, so printing this there blames the fixture file for an outage — which
            # it did, on two cases, in the same run that produced the 0.67 above.
            _n_src = sum(len(c.sources or []) for c in (getattr(dossier, "checks", None) or []))
            if _n_src == 0 and not deferred:
                print(f"    - NO EVIDENCE: zero passages reached any check — this case "
                      f"scored a brain on an empty fixture. Add a fixture key for {idea!r}.")
            # `retrieved_by`, NOT `provider` — the stamp is applied by ProviderStamped at
            # the chain boundary (retrieval.make_provider) and the field is called
            # `retrieved_by` (models.py:112). Reading a field that does not exist returns
            # None for every passage, which would have made this guard fire on every case
            # of a correctly-pinned run and never fire on an escaped one.
            _foreign = sorted({getattr(s, "retrieved_by", None) or "?"
                               for c in (getattr(dossier, "checks", None) or [])
                               for s in (c.sources or [])} - {"fixture"})
            if _foreign:
                print(f"    - UNPINNED: passages came from {_foreign}, not the fixtures — "
                      f"this score measures the live web, not the brain.")

        # THE EVIDENCE, not just the score. Until 2026-08-15 this record held six scalars
        # and nothing else, so `store/golden_runs/*.json` contained ZERO urls: a miss was
        # undiagnosable, and there was no way to tell whether a run had even READ the
        # fixtures (it had not — see the pinning fix in retrieval.make_provider). Source-or-die
        # applies to the harness that enforces source-or-die. `provider` is the load-bearing
        # field (`retrieved_by`, models.py:112): it must read "fixture" on every passage of a
        # `--fixtures` run, and anything
        # else means retrieval escaped its pin and the score is unattributable.
        results.append({
            "idea": idea,
            "passed": passed,
            "actual_decision": actual_decision,
            "actual_gate": actual_gate,
            "expected_decision": expected_decision_str,
            "expected_gate": expected_gate,
            "gate_match": gate_match,
            "surfaced": surfaced,
            "deferred": deferred,
            # Distinct from `deferred` on purpose: this case WAS scored, and scored wrong,
            # because the brain answered without a reason. See the split above.
            "unusable": unusable,
            "no_reason_checks": _no_reason,
            "checks": [
                {
                    "check": c.check_name,
                    "verdict": getattr(c.verdict, "value", str(c.verdict)),
                    "confidence": round(float(c.confidence or 0.0), 3),
                    "rationale": (c.rationale or "")[:400],
                    "citations": list(c.citations or []),
                    "degraded": bool(getattr(c, "degraded", False)),
                    "retrieval_failed": bool(getattr(c, "retrieval_failed", False)),
                    "sources": [
                        {
                            "source_id": s.source_id,
                            "url": s.url,
                            "retrieved_by": getattr(s, "retrieved_by", None),
                            "text": (s.text or "")[:300],
                        }
                        for s in (c.sources or [])
                    ],
                }
                for c in (getattr(dossier, "checks", None) or [])
            ],
        })

    # Denominator is the cases the brain actually RULED on. A deferred case is an
    # unanswered question, and dividing by it scores our outage as the brain's error.
    scored = total - deferred_count
    discrimination = correct_count / scored if scored > 0 else 0.0
    if verbose:
        print("-" * 60)
        print(f"[Golden Set] Final Score: {correct_count}/{scored} ({discrimination:.1%})")
        # Reported, never scored — see the docstring. Printed unconditionally so a run
        # that separates KILL from PASS by luck of the wrong gate cannot present itself
        # as a run that reasoned correctly.
        _unusable = [r for r in results if r.get("unusable")]
        if _unusable:
            print(f"[Golden Set] {len(_unusable)} of {total} cases were SCORED WRONG for "
                  f"answering with no rationale: "
                  f"{', '.join(r['idea'][:40] for r in _unusable)}. This is a property of "
                  f"the brain, not of provider availability — it does not make the run "
                  f"inconclusive.")
        _ruled = [r for r in results if not r["deferred"]]
        _gate_ok = sum(1 for r in _ruled if r["gate_match"])
        _surf_ok = sum(1 for r in _ruled if r["surfaced"])
        if _ruled:
            print(f"[Golden Set] Gate accuracy: {_gate_ok}/{len(_ruled)} "
                  f"({_gate_ok / len(_ruled):.0%}) fired on the labelled gate; "
                  f"{_surf_ok}/{len(_ruled)} surfaced the expected reason. "
                  f"NOT part of the score.")
        if deferred_count:
            print(f"[Golden Set] INCONCLUSIVE: {deferred_count} of {total} cases DEFERRED "
                  f"— the brain never ruled on them (quota, transport or a verdict call "
                  f"that returned no reason). A score over {scored} cases is not comparable "
                  f"with one over {total}, so this run may neither promote a challenger nor "
                  f"fail one. Re-run when the provider is live.")
        print()

    return discrimination, results


def _audit_path(operator_name: str, timestamp: str,
                store_dir: str | Path | None = None) -> Path:
    """Return <store_dir>/golden_runs/<operator>_<timestamp>.json.

    Timestamp uses full precision (YYYYMMddTHHMMSSffffff) so rapid consecutive
    runs produce distinct filenames even within the same second.

    `store_dir` exists because `--store-dir` was a WRITE-ONLY FLAG: argparse
    accepted it, `main()` never read `args.store_dir`, and this function hardcoded
    the repo's own `store/`.  Measured consequence 2026-08-15:
    `tests/integration/test_golden_promotion_cli.py` (which cannot redirect what it
    is not offered) wrote eight `mock_*.json` audit records into the PRODUCTION
    `store/golden_runs/`, where `prospector.ops.readers.latest_golden()` reads the
    estate's headline gate score — so a CI test's mock `discrimination=1.0` was
    sitting in front of the real `minimax` 0.667.  A flag that silently does
    nothing is worse than no flag: it reads, in a test, as isolation that was
    never applied.
    """
    root = Path(store_dir) if store_dir is not None else store_root()
    run_dir = root / "golden_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / f"{operator_name}_{timestamp}.json"


def _write_audit(
    operator_name: str, model_version: str, discrimination: float,
    results: list[dict[str, Any]], cfg_hash: str,
    run_index: int, total_runs: int,
    store_dir: str | Path | None = None) -> Path:
    """Write a single-run audit record to <store_dir>/golden_runs/<op>_<ts>.json."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = _audit_path(operator_name, timestamp, store_dir)
    record = {
        "timestamp": timestamp,
        "operator": operator_name,
        "model_version": model_version,
        "discrimination": discrimination,
        "run_index": run_index,
        "total_runs": total_runs,
        "config_hash": cfg_hash,
        "per_case": results,
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the Prospector Golden Set harness.  "
                    "See specs/offline-moat-validation.md for the promotion protocol.")
    parser.add_argument("--golden-set", default="fixtures/golden_set.json",
                        help="Path to golden set JSON")
    parser.add_argument(
        "--fixtures",
        help="Path to fixtures JSON (strongly recommended when using a real operator; "
             "pins retrieval so failures are attributable to the brain, not search variance).")
    parser.add_argument(
        "--operator", choices=OPERATOR_CHOICES,
        help="Override operator (default: from config.yaml).  "
             "For promotion, use --operator deepseek (or minimax) --runs 3.")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of consecutive runs required (promotion requires --runs 3).  "
             "Every run must reach --min-discrimination for the gate to pass.")
    parser.add_argument(
        "--min-discrimination", type=float, default=1.0, metavar="X",
        help="The bar every run must reach (default 1.0).  THE RELATIVE BAR IS THE USEFUL "
             "ONE: pass the INCUMBENT's score, measured on the same fixtures and the same "
             "commit on the same day, e.g. --min-discrimination 0.78.  Rationale: the "
             "absolute 1.0 has never been reached by any brain — claude_cli scored 0.78 on "
             "both 2026-06-16 and 2026-08-15, minimax 0.67 — so it cannot separate a "
             "challenger from the incumbent, which is the only question the gate is asked. "
             "A challenger that matches the trusted brain on identical inputs has earned the "
             "same trust; 1.0 stays the default so nothing loosens silently.")
    parser.add_argument(
        "--store-dir", default=None, metavar="DIR",
        help="Root for audit output; records land in <DIR>/golden_runs/.  "
             "Default: the repo's own store/.  ANY automated run (CI, pytest) must "
             "set this to a temp dir — the cockpit reads the repo store as the "
             "estate's live gate score, so a mock run written there is a fabricated "
             "green on the dashboard.")
    parser.add_argument(
        "--mock-vet", action="store_true",
        help="Test mode: use in-process deterministic mock instead of vet_candidate.  "
             "Skips operator/search setup entirely.  For CI gating tests only.")

    args = parser.parse_args()
    cfg = load_config(args.config)
    bar = float(args.min_discrimination)
    if args.operator:
        cfg.operator = args.operator

    # Stamp timestamp once so a single run writes a coherent record
    op_name = str(cfg.operator[0] if isinstance(cfg.operator, list) else cfg.operator)
    cfg_hash = str(hash((str(cfg.operator), str(cfg.model), str(cfg.model_fast))))

    # --- Mock-vet test mode: skip all operator/search setup ---------------
    if args.mock_vet:
        all_discriminations: list[float] = []
        all_results: list[list[dict[str, Any]]] = []
        for run_idx in range(1, args.runs + 1):
            discrimination, results = run_golden_set(
                None, None, cfg, args.golden_set,
                verbose=True, _vet_fn=_mock_vet_candidate,
                skip_adversarial=True)
            all_discriminations.append(discrimination)
            all_results.append(results)
            path = _write_audit(
                operator_name=op_name, model_version="mock",
                discrimination=discrimination, results=results,
                cfg_hash=cfg_hash, run_index=run_idx, total_runs=args.runs,
                store_dir=args.store_dir)
            glyph = "PASS" if discrimination >= bar else "FAIL"
            print(f"GOLDEN {op_name} [{run_idx}/{args.runs}]: "
                  f"discrimination={discrimination:.2f} "
                  f"({sum(r['passed'] for r in results)}/{len(results)}) → {glyph}")
        all_pass = all(d >= bar for d in all_discriminations)
        agg = sum(all_discriminations) / len(all_discriminations)
        overall = "PASS" if all_pass else "FAIL"
        print(f"\nGOLDEN {op_name} OVERALL: discrimination={agg:.2f} "
              f"({args.runs} runs, all ≥{bar:g}: {all_pass}) → {overall}")
        sys.exit(0 if all_pass else 1)

    # --- Real operator mode (promotion gate) --------------------------------
    # Warn when using a real model without fixture-pinned retrieval
    is_real_operator = args.operator not in (None, "mock")
    if is_real_operator and not args.fixtures:
        print(
            "WARNING: --operator is a real model but --fixtures is not set.  "
            "Live retrieval is in use — a failure could be brain OR search variance.  "
            "Promotion gate requires --fixtures fixtures/golden_fixtures.json.  "
            "Continuing anyway (for convenience during exploration).",
            file=sys.stderr,
        )

    # Setup operator
    try:
        op = make_operator(cfg)
    except RuntimeError as e:
        print(f"ERROR: operator unavailable: {e}", file=sys.stderr)
        sys.exit(1)

    model_version = getattr(op, "model_version", op_name)

    # Setup search (fixture-pinned retrieval for promotion gate)
    search_fixtures = None
    if args.fixtures:
        with open(args.fixtures, "r", encoding="utf-8") as f:
            search_fixtures = json.load(f)

    try:
        search = make_provider(cfg, fixtures=search_fixtures)
    except Exception as e:
        print(f"ERROR: search provider unavailable: {e}", file=sys.stderr)
        sys.exit(1)

    all_discriminations: list[float] = []
    all_results: list[list[dict[str, Any]]] = []
    all_deferred: list[int] = []

    for run_idx in range(1, args.runs + 1):
        # skip_adversarial=True: the golden set tests the six-check logic. The adversarial
        # pass is a separate moat layer that must be validated independently (per
        # specs/offline-moat-validation.md §5). Running it here would override specific
        # gate verdicts with adversarial_decisive, preventing the six-check discrimination
        # metric from measuring what it is designed to measure.
        discrimination, results = run_golden_set(
            op, search, cfg, args.golden_set, verbose=True,
            skip_adversarial=True, fixtures=search_fixtures)

        all_discriminations.append(discrimination)
        all_results.append(results)

        # Per-run audit
        path = _write_audit(
            operator_name=op_name,
            model_version=model_version,
            discrimination=discrimination,
            results=results,
            cfg_hash=cfg_hash,
            run_index=run_idx,
            total_runs=args.runs,
            store_dir=args.store_dir,
        )

        # A run containing ANY deferred case graded neither way. See `deferred` in
        # run_golden_set: the brain did not rule on those cases, so the score is over a
        # smaller denominator and is not comparable with a full run — it may not promote
        # and, more importantly, may not FAIL a challenger. Measured 2026-08-15: an
        # exhausted claude_cli deferred the last three cases and the harness printed
        # `discrimination=0.67 → FAIL`, grading our own usage limit as the brain's error.
        n_deferred = sum(1 for r in results if r.get("deferred"))
        all_deferred.append(n_deferred)

        run_label = f"[{run_idx}/{args.runs}]" if args.runs > 1 else ""
        glyph = ("INCONCLUSIVE" if n_deferred
                 else ("PASS" if discrimination >= bar else "FAIL"))
        print(f"GOLDEN {op_name} {run_label}: discrimination={discrimination:.2f} "
              f"({sum(r['passed'] for r in results)}/{len(results) - n_deferred}) → {glyph}  "
              f"(audit: {path.name})")
        if n_deferred:
            print(f"  {n_deferred} of {len(results)} cases DEFERRED — the provider was not "
                  f"live for this run. Nothing may be concluded about {op_name} from it.")

    # Aggregate verdict
    total_deferred = sum(all_deferred)
    if total_deferred:
        print(f"\nGOLDEN {op_name} OVERALL: INCONCLUSIVE — {total_deferred} deferred case(s) "
              f"across {args.runs} run(s). The brain never ruled on them, so this is a "
              f"measurement of provider availability, not of {op_name}. Re-run when the "
              f"provider is live; do NOT record this as a score.")
        # Exit 2, distinct from a graded failure (1): a caller that treats "not measured"
        # as "measured and failed" is the same misattribution one layer up.
        sys.exit(2)

    all_pass = all(d >= bar for d in all_discriminations)
    agg = sum(all_discriminations) / len(all_discriminations)
    overall = "PASS" if all_pass else "FAIL"
    print(f"\nGOLDEN {op_name} OVERALL: discrimination={agg:.2f} "
          f"({args.runs} runs, all ≥{bar:g}: {all_pass}) → {overall}")

    # Exit: spec §8 — promotion requires EVERY run at or above the bar (see
    # --min-discrimination; default 1.0, but the relative bar is what answers "can this
    # challenger replace the incumbent?").
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
