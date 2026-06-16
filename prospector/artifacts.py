"""Secondary artifacts + claim-check (Part 5).
On PASS, generate build_spec, GTM, ops_plan, financial_model (grounded),
plus claim-checked marketing/listing content.

FIX #13: All artifact and marketing generation calls are now parallelized via
ThreadPoolExecutor, cutting PASS-survivor latency by ~50% (was 8 sequential calls,
now 4 parallel batches).  The fast_op (flash-lite) is used for all generation
calls — these are structured template-filling tasks, not creative generation.

FIX #3: financial_model now outputs structured JSON assumptions (no LLM arithmetic).
Python performs all calculations: Revenue = Price × Customers, Gross Margin,
Payback period, CLV, LTV:CAC ratio.  Eliminates LLM math errors where models
report inconsistent or arithmetically impossible figures.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .models import Candidate, CheckResult, Verdict
from .operator import Operator
from .prompts import render
from .telemetry import logger


# ---------------------------------------------------------------------------
# Financial model arithmetic (FIX #3 — Python, not LLM)
# ---------------------------------------------------------------------------

def _render_financial_model(assumptions: Dict[str, Any],
                             claims: List[Dict[str, Any]]) -> str:
    """Compute and render financial model from structured JSON assumptions.

    FIX #3: all arithmetic is done in Python. The LLM supplies only raw inputs;
    Python computes Revenue, Margin, Payback, CLV, LTV:CAC.  This eliminates
    LLM math errors (e.g. "$1M revenue, $2M costs, called profitable").

    Displays None/missing fields gracefully — a business with no clear price or
    customer target renders a partial model with explicit gaps, not a wrong total.
    """
    price: Optional[float] = assumptions.get("monthly_price")
    cust_m1: Optional[int] = assumptions.get("target_customers_month_1")
    cust_m12: Optional[int] = assumptions.get("target_customers_month_12")
    cac: Optional[float] = assumptions.get("estimated_cac_gbp")
    clv: Optional[float] = assumptions.get("estimated_clv_gbp")
    churn: Optional[float] = assumptions.get("estimated_monthly_churn_pct")
    cog_pct: Optional[float] = assumptions.get("cost_of_goods_pct")
    overhead: Optional[float] = assumptions.get("overhead_month_1_gbp")
    payback: Optional[int] = assumptions.get("payback_months")
    ltv_cac_raw: Optional[float] = assumptions.get("ltv_cac_ratio")
    assumptions_list: List[str] = assumptions.get("assumptions") or []
    weaknesses: List[str] = assumptions.get("weaknesses") or []

    lines: List[str] = ["## Financial Model", ""]

    # --- Revenue ---
    lines.append("### Revenue")
    if price is not None and cust_m1 is not None:
        rev_m1 = price * cust_m1
        lines.append(f"- **Month 1:** £{price:,.0f} × {cust_m1} customers = **£{rev_m1:,.0f}**")
    else:
        lines.append("- Month 1: _(price or customer target not specified)_")

    if price is not None and cust_m12 is not None:
        rev_m12 = price * cust_m12
        lines.append(f"- **Month 12:** £{price:,.0f} × {cust_m12} customers = **£{rev_m12:,.0f}**")
        if cust_m1 and cust_m1 > 0:
            growth = rev_m12 / rev_m1
            lines.append(f"- **Growth (M1→M12):** {growth:.1f}×")
    elif cust_m12 is not None:
        lines.append(f"- Month 12: {cust_m12} customers _(monthly price not specified)_")
    else:
        lines.append("- Month 12: _(targets not specified)_")
    lines.append("")

    # --- Gross margin ---
    if cog_pct is not None:
        gross_margin = 100 - cog_pct
        lines.append(f"### Gross Margin: **{gross_margin:.0f}%** "
                     f"(COGS: {cog_pct:.0f}% of revenue)")
        if price is not None:
            margin_per_customer = price * gross_margin / 100
            lines.append(f"- **Per customer/month:** £{margin_per_customer:,.2f}")
        lines.append("")
    else:
        lines.append("### Gross Margin: _(COGS not specified)_")
        lines.append("")

    # --- Payback ---
    lines.append("### Payback Period")
    if payback is not None:
        lines.append(f"- **{payback} months**")
    elif cac is not None and price is not None and gross_margin is not None:
        margin_pm = price * gross_margin / 100
        if margin_pm > 0:
            calc_payback = cac / margin_pm
            lines.append(f"- **~{calc_payback:.1f} months** (CAC £{cac:,.0f} / "
                         f"gross margin £{margin_pm:,.2f}/month)")
        else:
            lines.append("- Cannot calculate: gross margin per customer is zero or negative")
    elif cac is not None:
        lines.append(f"- CAC: £{cac:,.0f} _(monthly price or margin not specified — cannot compute payback)_")
    else:
        lines.append("- _(not specified)_")
    lines.append("")

    # --- CLV ---
    lines.append("### Customer Lifetime Value (CLV)")
    if clv is not None:
        lines.append(f"- **£{clv:,.0f}**")
    elif churn is not None and churn > 0 and price is not None:
        # Simple CLV = ARPU / monthly churn rate
        calc_clv = price / (churn / 100)
        lines.append(f"- ~**£{calc_clv:,.0f}** (ARPU £{price:,.0f} / {churn:.1f}% monthly churn)")
    elif price is not None:
        lines.append(f"- ARPU: £{price:,.0f}/month _(churn rate not specified)_")
    else:
        lines.append("_(not specified)_")
    lines.append("")

    # --- LTV:CAC ---
    lines.append("### LTV:CAC Ratio")
    if ltv_cac_raw is not None:
        ratio = ltv_cac_raw
    elif clv is not None and cac is not None and cac > 0:
        ratio = clv / cac
    elif churn is not None and cac is not None and cac > 0 and price is not None:
        calc_clv = price / (churn / 100)
        ratio = calc_clv / cac if cac > 0 else None
    else:
        ratio = None

    if ratio is not None:
        if ratio >= 3:
            lines.append(f"- **{ratio:.1f}×** ✅ (>3× healthy SaaS benchmark)")
        elif ratio >= 1:
            lines.append(f"- **{ratio:.1f}×** ⚠️  (positive but below 3× benchmark)")
        else:
            lines.append(f"- **{ratio:.1f}×** ❌  (CAC not recovered — unsustainable)")
    else:
        lines.append("_(cannot compute without CLV and CAC)_")
    lines.append("")

    # --- Month 1 P&L ---
    lines.append("### Month 1 P&L")
    if price is not None and cust_m1 is not None and overhead is not None:
        rev = price * cust_m1
        if cog_pct is not None:
            cogs = rev * cog_pct / 100
            gross = rev - cogs
        else:
            gross = None
        net = (gross or rev) - overhead if gross is not None else None
        lines.append(f"- Revenue: £{rev:,.0f}")
        if cog_pct is not None:
            lines.append(f"- COGS ({cog_pct:.0f}%): £{cogs:,.0f}")
        lines.append(f"- Overhead: £{overhead:,.0f}")
        if net is not None:
            lines.append(f"- **Net: £{net:,.0f}**")
        else:
            lines.append("- Net: _(cannot compute without COGS)_")
    elif overhead is not None:
        lines.append(f"- Overhead: £{overhead:,.0f} _(revenue not specified)_")
    else:
        lines.append("_(not specified)_")
    lines.append("")

    # --- Key assumptions ---
    if assumptions_list:
        lines.append("### Key Assumptions (grounded in verified claims)")
        for a in assumptions_list:
            lines.append(f"- {a}")
        lines.append("")

    # --- Weaknesses ---
    if weaknesses:
        lines.append("### Model Weaknesses")
        for w in weaknesses:
            lines.append(f"- ⚠️  {w}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------

def _validate_artifact_shape(t: str, data: Any) -> Any:
    """Reject wrong-type / empty responses so they trigger a repair turn, not silence.

    Weaker generation models routinely ignore the requested `type` and return the most
    salient schema (the detailed financial_model), or emit prose under a key other than
    "content". Before this guard those landed as data.get("content") == "" — a silent
    empty artifact with no exception, so neither complete_json's repair loop nor the
    operator-chain failover ever fired. Raising ValueError here routes both: complete_json
    re-prompts the same model with the correction, and if it still won't comply the chain
    fails over to the next operator. Passed as complete_json(validate=...).
    """
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object for artifact '{t}', got {type(data).__name__}")
    got_type = data.get("type")
    if got_type and got_type != t:
        raise ValueError(f"wrong artifact type: asked for '{t}', model returned '{got_type}'")
    if t == "financial_model":
        # Structured inputs — just needs to be the dict; Python does the arithmetic.
        return data
    content = str(data.get("content") or "").strip()
    if not content:
        raise ValueError(f"artifact '{t}' has empty 'content' (model produced no body)")
    return data


def _gen_one_artifact(op: Operator, cand_json: str, claims_json: str,
                      t: str) -> tuple[str, str]:
    """Generate one artifact type. Runs in a thread; returns (type, content)."""
    system, user = render("artifacts", candidate_json=cand_json,
                          claims_json=claims_json, type=t)
    data = op.complete_json(system, user, temperature=0.3,
                            validate=lambda d: _validate_artifact_shape(t, d))

    # FIX #3: financial_model returns structured JSON — perform arithmetic in Python.
    if t == "financial_model" and isinstance(data, dict):
        assumptions = data
        # Render to human-readable text
        claims_list = json.loads(claims_json) if claims_json else []
        content = _render_financial_model(assumptions, claims_list)
        return t, content

    # All other types return {type, content}.
    return t, str(data.get("content", ""))


def generate_artifacts(
    op: Operator,
    cand: Candidate,
    checks: List[CheckResult],
    *,
    fast_op: Optional[Operator] = None,
) -> Dict[str, str]:
    """Generate build_spec, gtm_plan, ops_plan, financial_model in parallel.

    FIX #13: parallelizes 4 sequential LLM calls into 1 ThreadPoolExecutor batch.
    FIX #12: routes all calls to fast_op (flash-lite) — these are template-filling
    tasks, not creative generation; flash-lite quality is identical at lower cost.
    FIX #3: financial_model outputs JSON assumptions; Python performs arithmetic.
    """
    _op = fast_op or op

    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    claims_json = json.dumps(claims)
    cand_json = json.dumps(cand.to_dict())

    types = ["build_spec", "gtm_plan", "ops_plan", "financial_model"]
    results: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(types)) as ex:
        futures = {
            ex.submit(_gen_one_artifact, _op, cand_json, claims_json, t): t
            for t in types
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                _, content = future.result()
                results[t] = content
            except Exception as e:
                logger.error(f"Artifact generation failed for {t}: {e}",
                             extra={"type": t, "error": str(e)})
                results[t] = ""

    return results


# ---------------------------------------------------------------------------
# Marketing content + claim check
# ---------------------------------------------------------------------------

def verify_claims(op: Operator, copy: str, claims: List[Dict[str, Any]]) -> bool:
    """Check marketing/listing copy for claim-consistency (Part 5)."""
    system, user = render("claim_check", copy=copy, claims_json=json.dumps(claims))
    try:
        data = op.complete_json(system, user, temperature=0.0)
        return bool(data.get("pass", False))
    except Exception:
        return False


def _gen_one_content(op: Operator, cand_json: str, claims_json: str,
                     claims: List[Dict[str, Any]], t: str) -> Optional[Dict[str, str]]:
    """Generate one marketing piece with one regeneration attempt.

    Returns None if the piece fails claim-check after the regeneration loop.
    Runs in a thread (per content type, so 4 threads max).
    """
    for attempt in range(2):
        system, user = render("content_gen", candidate_json=cand_json,
                              claims_json=claims_json, type=t)
        data = op.complete_json(system, user, temperature=0.7)
        copy = str(data.get("copy", ""))

        if verify_claims(op, copy, claims):
            return {"type": t, "copy": copy}
        logger.debug(f"Content {t} failed claim-check, regenerating (attempt {attempt + 1}/2)",
                     extra={"type": t})

    logger.warning(f"Dropping unverified marketing piece: {t}", extra={"type": t})
    return None


def generate_marketing_content(
    op: Operator,
    cand: Candidate,
    checks: List[CheckResult],
    *,
    fast_op: Optional[Operator] = None,
) -> List[Dict[str, str]]:
    """Generate and claim-check listing_page, teaser_social, seo_preview, launch_email.

    FIX #13: all 4 content types are generated in parallel (4 threads instead of
    sequential).  Each type has its own 2-attempt regeneration loop.  The retry
    loop is INSIDE the thread so threads are independent — a slow regeneration on
    one type does not block the others.  FIX #12: calls route to fast_op.
    """
    _op = fast_op or op

    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    claims_json = json.dumps(claims)
    cand_json = json.dumps(cand.to_dict())

    types = ["listing_page", "teaser_social", "seo_preview", "launch_email"]

    with ThreadPoolExecutor(max_workers=len(types)) as ex:
        futures = {
            ex.submit(_gen_one_content, _op, cand_json, claims_json, claims, t): t
            for t in types
        }
        results: List[Dict[str, str]] = []
        for future in as_completed(futures):
            t = futures[future]
            try:
                piece = future.result()
                if piece:
                    results.append(piece)
            except Exception as e:
                logger.error(f"Marketing content generation failed for {t}: {e}",
                             extra={"type": t, "error": str(e)})

    type_order = {t: i for i, t in enumerate(types)}
    results.sort(key=lambda p: type_order.get(p.get("type", ""), 99))
    return results
