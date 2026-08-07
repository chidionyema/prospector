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

from . import facets
from .models import Candidate, CheckResult, Verdict
from .operator import Operator, ParseError, _extract_json
from .prompts import ALL_MARKET_KEYS, market_kwargs, render
from .telemetry import logger, stage as telemetry_stage

# Prose pack bodies: schema is {"type", "content"} where content is markdown.
# cursor_cli often emits the markdown body without the JSON envelope.
_PROSE_ARTIFACT_TYPES = frozenset({"build_spec", "gtm_plan", "ops_plan"})


def _coerce_bare_markdown_artifact(text: str, t: str) -> dict:
    """Wrap a bare-markdown CLI reply into the prose artifact JSON envelope."""
    content = (text or "").strip()
    if not content:
        raise ParseError(f"empty response for artifact '{t}'")
    if content.startswith("```"):
        lines = content.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
        try:
            return _extract_json(content)
        except ParseError:
            pass
    if content.startswith("#") or ("\n## " in content and len(content) >= 400):
        logger.info("Coerced bare-markdown CLI reply into artifact JSON envelope",
                    extra={"type": t, "chars": len(content)})
        return {"type": t, "content": content}
    raise ParseError(f"cannot coerce response into artifact '{t}'")


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
                      t: str, market_vars: Optional[Dict[str, str]] = None
                      ) -> tuple[str, str]:
    """Generate one artifact type. Runs in a thread; returns (type, content)."""
    system, user = render("artifacts", candidate_json=cand_json,
                          claims_json=claims_json, type=t,
                          **(market_vars or {}))
    coerce = ((lambda text: _coerce_bare_markdown_artifact(text, t))
              if t in _PROSE_ARTIFACT_TYPES else None)
    with telemetry_stage("artifacts"):
        data = op.complete_json(system, user, temperature=0.3,
                                validate=lambda d: _validate_artifact_shape(t, d),
                                coerce=coerce)

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
    quality_op: Optional[Operator] = None,
    cfg: Optional[Any] = None,
) -> Dict[str, str]:
    """Generate build_spec, gtm_plan, ops_plan, financial_model in parallel.

    FIX #13: parallelizes 4 sequential LLM calls into 1 ThreadPoolExecutor batch.
    FIX #3: financial_model outputs JSON assumptions; Python performs arithmetic.

    The three PROSE artifacts ARE the £49 deliverable, so they route to ``quality_op``
    (the Gemini CLI -> Claude CLI quality chain) when provided. The financial_model is a
    pure JSON fill that Python turns into arithmetic, so it stays on the cheap ``fast_op``.
    Both fall back to ``op`` (the moat) when their preferred operator isn't supplied.
    """
    cheap_op = fast_op or op
    prose_op = quality_op or op

    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    claims_json = json.dumps(claims)
    cand_json = json.dumps(cand.to_dict())

    types = ["build_spec", "gtm_plan", "ops_plan", "financial_model"]
    results: Dict[str, str] = {}

    # Money figures in the pack must be denominated in the OPPORTUNITY's market currency
    # (a US pack quoting £ is wrong), independently of the £49 the pack itself sells for.
    market_vars = market_kwargs(cfg) if cfg is not None else {k: "" for k in ALL_MARKET_KEYS}

    with ThreadPoolExecutor(max_workers=len(types)) as ex:
        futures = {
            ex.submit(_gen_one_artifact,
                      cheap_op if t == "financial_model" else prose_op,
                      cand_json, claims_json, t, market_vars): t
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

def verify_claims(op: Operator, copy: str, claims: List[Dict[str, Any]]
                  ) -> bool:
    """Check marketing/listing copy for claim-consistency (Part 5)."""
    ok, _ = verify_claims_detail(op, copy, claims)
    return ok


def verify_claims_detail(op: Operator, copy: str, claims: List[Dict[str, Any]]
                         ) -> tuple[bool, List[Dict[str, Any]]]:
    """Like verify_claims, but also returns violation rows for regeneration feedback."""
    system, user = render("claim_check", copy=copy, claims_json=json.dumps(claims))
    try:
        with telemetry_stage("claim_check"):
            data = op.complete_json(system, user, temperature=0.0)
        ok = bool(data.get("pass", False))
        viol = data.get("violations") if isinstance(data.get("violations"), list) else []
        return ok, [v for v in viol if isinstance(v, dict)]
    except Exception:
        return False, []


#: Hard ceiling for the card heading, mirrored in ``prompts/content_gen.md``. Chosen so two
#: cards per row at the storefront's card width render it on one or two lines, never as the
#: 90+ character paragraph the title produces.
CARD_LINE_MAX = 60


def _card_line(raw: str) -> str:
    """The shelf heading, or "" when the operator could not produce a truthful short one.

    Accept-or-drop, never truncate. The only tidying applied is stripping a trailing period
    and collapsing whitespace, neither of which can change a claim.
    """
    line = " ".join(raw.split()).rstrip(".").strip()
    if not line or len(line) > CARD_LINE_MAX:
        if line:
            logger.info(
                "listing card_line discarded: %d chars exceeds the %d limit (%r)",
                len(line),
                CARD_LINE_MAX,
                line,
            )
        return ""
    return line


def _derive_copy(headline: str, subhead: str, what: List[str], proof_point: str) -> str:
    """Assemble the prose body from the structured fields.

    Extracted so the salvage path can RE-derive it after a field is dropped. A derived body
    is a concatenation of its parts, so re-running it is the only thing that keeps a
    discarded claim from reappearing in the prose the storefront actually renders.
    """
    parts = [p for p in (headline, subhead) if p]
    if what:
        parts.append("What you get: " + "; ".join(what))
    if proof_point:
        parts.append(proof_point)
    return "\n\n".join(parts)


def _normalize_listing(data: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a (possibly partial) listing_page response into the structured contract.

    The storefront renders per-pack specifics (headline, what-you-get bullets, the single
    strongest proof point, who pays, effort + time-to-revenue) instead of generic chips, so
    the listing_page is structured rather than a freeform blob. This is tolerant: an operator
    that only returns ``copy`` still yields a valid piece (structured fields empty), and when
    ``copy`` is missing we assemble a prose fallback from the parts. ``copy`` is always set so
    the completeness gate (which checks copy length) and the bundle keep working unchanged.
    """
    # Operators occasionally return a JSON array (e.g. [{...}]) instead of the object, or a
    # bare string. Coerce to the dict the contract expects rather than crashing on .get().
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {})
    elif isinstance(data, str):
        data = {"copy": data}
    elif not isinstance(data, dict):
        data = {}

    def _s(key: str) -> str:
        return str(data.get(key) or "").strip()

    what = [str(x).strip() for x in (data.get("what_you_get") or []) if str(x).strip()][:5]
    effort = _s("effort_tag").lower()
    copy = _s("copy") or _derive_copy(_s("headline"), _s("subhead"), what, _s("proof_point"))
    return {
        "type": "listing_page",
        "copy": copy,
        # The shelf heading. Over-length is DISCARDED rather than truncated: cutting a
        # sentence mid-clause changes what it claims ("not suitable for under-27s" ->
        # "not suitable for"), and a claim nobody made is exactly what this system exists
        # to keep off the storefront. An empty card_line is a correct answer -- the card
        # falls back to the pack title.
        "card_line": _card_line(_s("card_line")),
        "headline": _s("headline"),
        "subhead": _s("subhead"),
        "what_you_get": what,
        "proof_point": _s("proof_point"),
        "who_pays": _s("who_pays"),
        # Legacy. Kept on the wire for one release so nothing that still reads it breaks;
        # it is NOT the source of the `effort` facet below (spec 2.3 — low|medium|high was
        # never defined to mean machine-doability, so mapping it would be a guess).
        "effort_tag": effort if effort in ("low", "medium", "high") else "",
        # Discovery facets, validated against the closed vocabulary. Anything the operator
        # invented is dropped to None here rather than coerced to the nearest member: the
        # storefront routes buyers on these, and a coerced value is a claim nobody made.
        "facets": facets.normalize(data.get("facets")),
        "time_to_first_revenue": _s("time_to_first_revenue"),
        "cta_text": _s("cta_text"),
    }


def _listing_check_text(piece: Dict[str, Any]) -> str:
    """Everything a buyer will SEE on the card, concatenated for the claim-check gate, so
    overstatement in the headline/bullets/proof_point is caught, not just the prose body."""
    # card_line is the FIRST thing a browsing buyer reads and for many it is the only thing,
    # so it is held to the same claim-check bar as the headline. Omitting it here would make
    # the shortest, most-read line on the storefront the one line nobody checked.
    bits = [piece.get("card_line", ""), piece.get("headline", ""), piece.get("subhead", "")]
    bits.extend(piece.get("what_you_get", []) or [])
    bits.extend([piece.get("proof_point", ""), piece.get("copy", "")])
    return "\n".join(b for b in bits if b)


def _salvage_listing(check_op: Operator, piece: Dict[str, Any], claims: List[Dict[str, Any]],
                     *, copy_supplied: bool) -> Optional[Dict[str, Any]]:
    """Re-check a failed listing_page field by field, keeping only the fields that clear.

    ``_listing_check_text`` deliberately checks everything a buyer sees, but it checks it as
    ONE blob under ONE verdict, so a single unverifiable sentence discarded the whole piece.
    Measured 2026-08-06 over 258 non-KILL dossiers: listing_page survived 18 times (7%) —
    the worst of the four marketing pieces and the only one that reaches the storefront.
    Six independent fields each 90% clean clear together ~53% of the time; the blob verdict,
    not the claim bar, is what collapsed the yield.

    This is a salvage path, not a relaxation. Every surviving field has passed the SAME gate
    on the same moat operator, alone instead of in company. A field that violates is dropped,
    never softened, and the prose body is re-derived so a dropped claim cannot reappear in it.

    Returns None when nothing verifiable is left — an empty shell would read as "copy exists"
    to every downstream check while carrying no buyer-facing text.
    """
    fields: List[tuple[str, str]] = [
        (key, piece[key]) for key in ("card_line", "headline", "subhead", "proof_point")
        if piece.get(key)
    ]
    bullets = list(piece.get("what_you_get") or [])
    fields.extend((f"what_you_get[{i}]", b) for i, b in enumerate(bullets))
    # A derived body is its parts re-joined, so checking it again would double-charge the moat
    # for text already being checked. Only an operator-authored body needs its own verdict.
    if copy_supplied and piece.get("copy"):
        fields.append(("copy", piece["copy"]))
    if not fields:
        return None

    with ThreadPoolExecutor(max_workers=min(len(fields), 8)) as ex:
        futures = {ex.submit(verify_claims_detail, check_op, text, claims): label
                   for label, text in fields}
        passed: Dict[str, bool] = {}
        for future in as_completed(futures):
            label = futures[future]
            try:
                passed[label] = future.result()[0]
            except Exception as e:
                # A check that could not run is not a pass. Failing open here would ship the
                # exact unverified copy this gate exists to stop.
                logger.error(f"Listing field claim-check errored, dropping {label}: {e}",
                             extra={"field": label, "error": str(e)})
                passed[label] = False

    salvaged = dict(piece)
    for key in ("card_line", "headline", "subhead", "proof_point"):
        if piece.get(key) and not passed.get(key):
            salvaged[key] = ""
    salvaged["what_you_get"] = [b for i, b in enumerate(bullets)
                               if passed.get(f"what_you_get[{i}]")]

    if not (copy_supplied and passed.get("copy")):
        salvaged["copy"] = _derive_copy(salvaged["headline"], salvaged["subhead"],
                                        salvaged["what_you_get"], salvaged["proof_point"])

    if not salvaged["copy"].strip():
        logger.warning("Listing salvage kept no verifiable field; dropping piece",
                       extra={"type": "listing_page", "fields_checked": len(fields)})
        return None

    dropped = sorted(label for label, ok in passed.items() if not ok)
    logger.warning(
        f"Listing salvaged: kept {len(fields) - len(dropped)}/{len(fields)} fields, "
        f"dropped {dropped}",
        extra={"type": "listing_page", "kept": len(fields) - len(dropped),
               "checked": len(fields), "dropped": dropped},
    )
    return salvaged


def _gen_one_content(gen_op: Operator, check_op: Operator, cand_json: str, claims_json: str,
                     claims: List[Dict[str, Any]], t: str) -> Optional[Dict[str, Any]]:
    """Generate one marketing piece with regeneration that feeds claim-check violations.

    ``gen_op`` drafts the copy (cheap for ancillary pieces, the quality chain for the
    listing_page); ``check_op`` runs the claim-check — always the moat, because a verification
    gate must never be judged by the same cheap model that produced the copy. Returns None if
    the piece fails claim-check after the regeneration loop. Runs in a thread.
    """
    feedback = ""
    # listing_page is required for publish; give it one extra repair turn with violations.
    attempts = 3 if t == "listing_page" else 2
    last_listing: Optional[Dict[str, Any]] = None
    copy_supplied = False
    for attempt in range(attempts):
        system, user = render("content_gen", candidate_json=cand_json,
                              claims_json=claims_json, type=t)
        if feedback:
            user = f"{user}\n\n{feedback}"
        with telemetry_stage("content_gen"):
            data = gen_op.complete_json(system, user, temperature=0.7 if attempt == 0 else 0.3)
        if t == "listing_page":
            piece = _normalize_listing(data)
            last_listing = piece
            # Operators sometimes return a list or a bare string; _normalize_listing coerces
            # those, but only a dict can have carried an authored `copy`.
            copy_supplied = isinstance(data, dict) and bool(str(data.get("copy") or "").strip())
            check_text = _listing_check_text(piece)
        else:
            piece = {"type": t, "copy": str(data.get("copy", ""))}
            check_text = piece["copy"]

        ok, violations = verify_claims_detail(check_op, check_text, claims)
        if ok:
            return piece
        logger.info(
            f"Content {t} failed claim-check, regenerating (attempt {attempt + 1}/{attempts})",
            extra={"type": t, "violations_n": len(violations)})
        feedback = (
            "Your previous draft FAILED claim-check. Rewrite so every factual statement "
            "is supported by the verified claims. Do NOT invent mechanics, tools, prices, "
            "or channels. Empty optional fields are safer than invention. Violations:\n"
            f"{json.dumps(violations, ensure_ascii=False)}"
        )

    # Every repair turn is spent. For listing_page the whole-piece verdict is not the last
    # word: re-check field by field and keep whatever clears on its own, because one
    # unverifiable sentence costing all six fields is what drove survival to 7% (see
    # _salvage_listing). The cheap path above is unchanged — salvage is only ever reached
    # after the single blob check has already failed.
    if t == "listing_page" and last_listing is not None:
        return _salvage_listing(check_op, last_listing, claims, copy_supplied=copy_supplied)

    logger.warning(f"Dropping unverified marketing piece: {t}", extra={"type": t})
    return None


def generate_marketing_content(
    op: Operator,
    cand: Candidate,
    checks: List[CheckResult],
    *,
    fast_op: Optional[Operator] = None,
    quality_op: Optional[Operator] = None,
    check_op: Optional[Operator] = None,
) -> List[Dict[str, Any]]:
    """Generate and claim-check listing_page, teaser_social, seo_preview, launch_email.

    FIX #13: all 4 content types are generated in parallel (4 threads instead of
    sequential).  Each type has its own 2-attempt regeneration loop.  The retry
    loop is INSIDE the thread so threads are independent.

    The listing_page is the storefront copy a buyer reads BEFORE paying, so it routes to
    ``quality_op`` (the Gemini CLI -> Claude CLI chain); the ancillary pieces stay on the
    cheap ``fast_op``. The claim-check gate always runs on ``check_op`` (the moat) — never the
    drafting model. All three fall back to ``op`` when their preferred operator isn't supplied.
    """
    cheap_op = fast_op or op
    quality = quality_op or op
    checker = check_op or op

    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    claims_json = json.dumps(claims)
    cand_json = json.dumps(cand.to_dict())

    types = ["listing_page", "teaser_social", "seo_preview", "launch_email"]

    with ThreadPoolExecutor(max_workers=len(types)) as ex:
        futures = {
            ex.submit(_gen_one_content,
                      quality if t == "listing_page" else cheap_op,
                      checker, cand_json, claims_json, claims, t): t
            for t in types
        }
        results: List[Dict[str, Any]] = []
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
