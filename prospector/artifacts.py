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
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from . import evidence_budget, facets
from .copy_lint import buyer_readable
from .marketing_assets import ASSET_TYPES
from .models import Candidate, CheckResult, Decision, Dossier, Verdict
from .operator import Operator, ParseError, _extract_json
from .pack_linter import symbol_for_currency
from .prompts import ALL_MARKET_KEYS, market_kwargs, render
from .telemetry import logger
from .telemetry import stage as telemetry_stage

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
# Buyer-facing prompt projection (2026-08-08)
# ---------------------------------------------------------------------------

# The artifact prompt used to be handed `json.dumps(cand.to_dict())` and the raw
# CheckResult dicts, so the engine's SCHEMA was the only vocabulary the model had for the
# opportunity — and it echoed that vocabulary into copy the buyer pays for. Measured
# 2026-08-08: 589 occurrences across 51 of 99 packs, e.g. "monthly_price of £12 is
# assumption", "the opportunity's who_pays field", "(source: verified claim
# value_durability)". The last form was COMPELLED by the prompt, which tells the model to
# cite "the verified claim it rests on" while giving it nothing but `check_name` to name
# one with.
#
# The fix is vocabulary, not suppression: every field the writer needs is still there,
# under a label a buyer can read. Labels contain a SPACE, so they also cannot match
# copy_lint's identifier pattern (`[a-z]+(_[a-z0-9]+)+`) — the generator and the publish
# gate therefore agree by construction, not because someone remembered to keep them in
# step. That is the same choke-point property the catalogue normaliser has.
_CANDIDATE_PROMPT_LABELS: Dict[str, str] = {
    "title": "title",
    "one_liner": "summary",
    "hypothesis": "hypothesis",
    "who_pays": "who pays",
    "why_now": "why now",
    "automatability": "automatability",
    "weak_monetisation": "monetisation risk",
    "structural_form": "business form",
    "ambition_tier": "ambition tier",
    "market": "market",
}

# Engine bookkeeping the artifact writer has no use for: `candidate_id` and
# `refinement_history` are internal provenance, and `tags` carries the engine's own
# artifact/comparables payloads — the pack's plumbing, not its subject.
_CANDIDATE_PROMPT_DROP = frozenset({"candidate_id", "refinement_history", "tags"})

_CHECK_PROMPT_LABELS: Dict[str, str] = {
    "pain_reality": "pain reality",
    "value_durability": "value durability",
    "incumbency": "incumbency",
    "payer_solvency": "payer solvency",
    "distribution": "distribution",
    "legality": "legality",
    "price_comparables": "price comparables",
}

# Kept per check: the FINDING. Dropped: `queries`, `query_source`, `degraded`,
# `retrieval_failed`, `provider`, `provisional` — those describe how retrieval went, which
# is audit state the buyer's artifact must never narrate.
_CHECK_PROMPT_KEEP = ("verdict", "confidence", "rationale", "citations", "sources")


def _prompt_label(key: str, table: Dict[str, str]) -> str:
    return table.get(key, str(key).replace("_", " "))


def _candidate_prompt_view(cand: Any) -> Dict[str, Any]:
    """Project a Candidate into buyer-readable keys for prompt injection."""
    raw = cand.to_dict() if hasattr(cand, "to_dict") else dict(cand or {})
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in _CANDIDATE_PROMPT_DROP:
            continue
        if value is None or value == "" or value == [] or value == {}:
            continue
        out[_prompt_label(key, _CANDIDATE_PROMPT_LABELS)] = value
    return out


def _claims_prompt_view(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project verified checks into buyer-readable keys, keeping the finding only.

    `claim` replaces `check_name` deliberately: it is the handle the prompt tells the
    model to cite by, so it has to be a phrase that is correct to print in a pack.
    """
    out: List[Dict[str, Any]] = []
    for c in claims or []:
        item: Dict[str, Any] = {
            "claim": _prompt_label(c.get("check_name", ""), _CHECK_PROMPT_LABELS),
        }
        for key in _CHECK_PROMPT_KEEP:
            value = c.get(key)
            if value is None or value == "" or value == [] or value == {}:
                continue
            item[key.replace("_", " ")] = value
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Financial model arithmetic (FIX #3 — Python, not LLM)
# ---------------------------------------------------------------------------

#: How the business takes money. Everything that divides by a month depends on it, and
#: until 2026-08-14 nothing carried it: `monthly_price` was read as a monthly price for
#: every business on the catalogue. A personalised picture book bought once was modelled
#: as a subscription, and its lifetime value came out of `price / churn` — a churn rate
#: the model had invented because the schema asked for one. Measured across the 68
#: financial models on disk that day: 17 derived a lifetime value that way.
_RECURRING_MODELS = frozenset({
    "subscription", "subscriptions", "saas", "membership", "retainer", "recurring",
    "repeat_purchase", "repeat_purchases", "licence", "license",
})
_ONE_OFF_MODELS = frozenset({
    "one_off", "oneoff", "one_time", "single_purchase", "single_sale", "transactional",
    "product_sale", "product", "commission", "project", "per_project",
})


def revenue_shape(assumptions: Dict[str, Any], churn: Optional[float]) -> str:
    """``"recurring"``, ``"one_off"`` or ``"unknown"`` — never a guess dressed as a fact.

    A declared `revenue_model` wins. Absent one, a stated monthly churn rate is taken as
    the model asserting recurrence, since churn is meaningless otherwise; that inference
    is disclosed in the rendered line rather than hidden. Everything else is `unknown`,
    and `unknown` suppresses every figure whose formula assumes a customer pays again.
    """
    raw = str(assumptions.get("revenue_model") or "").strip().lower()
    raw = re.sub(r"[\s-]+", "_", raw)
    if raw in _RECURRING_MODELS:
        return "recurring"
    if raw in _ONE_OFF_MODELS:
        return "one_off"
    if raw:
        # A model that answered with something we do not recognise ("freemium tiers",
        # "marketplace take rate") has told us it is not simple, not that it is monthly.
        return "unknown"
    return "recurring" if churn else "unknown"


def _render_financial_model(assumptions: Dict[str, Any],
                             claims: List[Dict[str, Any]],
                             currency: str = "£") -> str:
    """Compute and render the financial model from structured JSON assumptions.

    All arithmetic is done in Python. The model supplies only raw inputs; Python computes
    every total, so the class of error where a model writes "£1M revenue, £2M costs,
    profitable" cannot occur here.

    TWO RULES, both added 2026-08-14 after the founder read a shipped pack:

    **A figure we cannot compute is not printed as a gap in the middle of the document.**
    It used to render ``_(not specified)_`` inline, six or seven times in a row on the
    worst packs: measured across the 68 financial models on disk, 23 carried at least one
    and 4 were nothing else — a document titled "Financial Model" containing no number, in
    a £49.99 pack. Missing inputs are now collected and stated once, in plain words, at the
    end. The document says what it could not work out; it does not pretend to a section.

    **A model with no headline is not a document.** With no price or no month-1 target
    there is nothing to compute, so this returns ``""`` and the pack is held back by
    `pack_validation.validate_pack` rather than listed with a hollow file in it.

    `currency` is the symbol for the pack's market, resolved by the caller from that
    market's config-declared `currency_hint` (config.yaml markets.<code>). It was a
    hardcoded £ until the Q2 pack lint began refusing to list a pack whose money symbol
    contradicts its market: a US pack priced in £ is wrong on the storefront whatever the
    numbers say. The `*_gbp` assumption keys keep their legacy names and are read as
    amounts in THIS market's currency — the artifacts prompt is already handed
    `currency_hint` (prompts.py OPEN_MARKET_KEYS), so the model supplies local figures.
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
    repeat: Optional[float] = assumptions.get("repeat_purchases_per_customer")
    assumptions_list: List[str] = assumptions.get("assumptions") or []
    weaknesses: List[str] = assumptions.get("weaknesses") or []

    # No headline, no document. See the docstring.
    if price is None or cust_m1 is None:
        return ""

    shape = revenue_shape(assumptions, churn)
    recurring = shape == "recurring"
    unit = "orders" if shape == "one_off" else "customers"
    one = unit[:-1]
    # The per-unit lines count orders; the acquisition and lifetime lines are about
    # the person. Deriving both from one word produced "what it costs to win a order".
    person = "customer" if shape != "one_off" else "buyer"
    per_month = " a month" if recurring else ""

    # Every input the model did not supply, in the buyer's words, printed once at the end.
    gaps: List[str] = []

    def money(value: float, dp: int = 0) -> str:
        # Sign OUTSIDE the symbol. `f"{currency}{-378:,.0f}"` renders "£-378", which reads
        # as a typo rather than a loss, in the one line where the loss is the finding.
        sign = "-" if value < 0 else ""
        return f"{sign}{currency}{abs(value):,.{dp}f}"

    lines: List[str] = ["## Financial Model", ""]

    # --- Revenue ---
    rev_m1 = price * cust_m1
    lines.append("### What it earns")
    lines.append("")
    lines.append(f"- **Month 1:** {money(price)} × {cust_m1:,} {unit} = **{money(rev_m1)}**")
    if cust_m12 is not None:
        rev_m12 = price * cust_m12
        lines.append(
            f"- **Month 12:** {money(price)} × {cust_m12:,} {unit} = **{money(rev_m12)}**")
        if cust_m1 > 0:
            lines.append(f"- **Growth (M1→M12):** {rev_m12 / rev_m1:.1f}×")
    else:
        gaps.append("Where sales land by month 12. We were given a month-one target and "
                    "no year-one one, so there is no growth line.")
    if shape == "unknown":
        lines.append("")
        lines.append(f"These are {one} counts, not a repeat-purchase promise: nothing here "
                     f"assumes the same {person} buys twice.")
    lines.append("")

    # --- Gross margin ---
    gross_margin: Optional[float] = None
    margin_per_unit: Optional[float] = None
    if cog_pct is not None:
        gross_margin = 100 - cog_pct
        margin_per_unit = price * gross_margin / 100
        lines.append("### What it keeps after costs")
        lines.append("")
        lines.append(f"- **Gross margin: {gross_margin:.0f}%** — making and delivering it "
                     f"costs {cog_pct:.0f}% of what you charge")
        lines.append(f"- **Kept per {one}: {money(margin_per_unit, 2)}**{per_month}")
        lines.append("")
    else:
        gaps.append("What it costs to make and deliver one. Without that there is no margin "
                    "figure, and no profit line below it.")

    # --- Cost of winning a customer, and when it comes back ---
    cost_lines: List[str] = []
    if cac is not None:
        cost_lines.append(f"- **Costs to win one {person}: {money(cac)}**")
    if payback is not None:
        cost_lines.append(f"- **Paid back in: ~{payback} months** — the model's own figure, "
                          f"not ours")
    elif cac is not None and margin_per_unit is not None and margin_per_unit > 0:
        if recurring:
            cost_lines.append(
                f"- **Paid back in: ~{cac / margin_per_unit:.1f} months** "
                f"({money(cac)} to win a customer ÷ {money(margin_per_unit, 2)} kept each month)")
        else:
            sales = cac / margin_per_unit
            if sales <= 1:
                cost_lines.append(
                    f"- **Paid back on the first sale** — winning a buyer costs "
                    f"{money(cac)} and one sale keeps {money(margin_per_unit, 2)}")
            else:
                cost_lines.append(
                    f"- **Not paid back on the first sale** — winning a buyer costs "
                    f"{money(cac)} and one sale keeps only {money(margin_per_unit, 2)}, so "
                    f"it takes {sales:.1f} sales to the same buyer to break even on that spend")
    elif cac is not None and margin_per_unit is not None:
        cost_lines.append("- Each sale loses money before you have paid to win it, so there "
                          "is no payback period to quote.")
    elif cac is None:
        gaps.append("What it costs to win one buyer. That is the number that decides whether "
                    "any of this works, and it was not supplied.")

    if cost_lines:
        lines.append(f"### What it costs to win a {person}")
        lines.append("")
        lines.extend(cost_lines)
        lines.append("")

    # --- What a customer is worth ---
    # Derivation is gated on the revenue shape. `price / churn` is a subscription formula;
    # applying it to a one-off sale is how a £24 book acquired a £480 lifetime value.
    clv_line: Optional[str] = None
    if clv is not None:
        clv_line = f"- **{money(clv)}** over the whole relationship — the model's own figure"
    elif recurring and churn:
        clv = price / (churn / 100)
        inferred = "" if assumptions.get("revenue_model") else (
            " We are treating this as a repeat payment because the model gave a monthly "
            "churn rate, which only means something if customers keep paying.")
        clv_line = (f"- **~{money(clv)}** — they pay {money(price)} a month and about "
                    f"{churn:.1f}% stop each month.{inferred}")
    elif shape == "one_off" and repeat:
        clv = price * repeat
        clv_line = (f"- **~{money(clv)}** — {money(price)} a sale, and the model expects "
                    f"about {repeat:g} sales to the same buyer")
    elif shape == "one_off":
        gaps.append("How often a buyer comes back. This is a one-off sale, so without a "
                    "repeat rate a customer is worth exactly one sale and no more.")
    else:
        gaps.append("Whether buyers pay once or keep paying. Everything about what a "
                    f"{person} is worth over time hangs on it, and it was not stated.")

    if clv_line:
        lines.append(f"### What one {person} is worth")
        lines.append("")
        lines.append(clv_line)
        lines.append("")

    # --- Worth against cost ---
    ratio: Optional[float] = None
    if ltv_cac_raw is not None:
        ratio = ltv_cac_raw
    elif clv is not None and cac:
        ratio = clv / cac
    if ratio is not None:
        if ratio >= 3:
            verdict = "comfortably above the three-to-one most people hold this to"
        elif ratio >= 1:
            verdict = "positive, but under the three-to-one most people hold this to"
        else:
            verdict = "you spend more winning a buyer than you ever get back — as modelled, this does not work"
        lines.append("### Worth against cost")
        lines.append("")
        lines.append(f"- **{ratio:.1f}×** — {verdict}")
        lines.append("")

    # --- Month 1 P&L ---
    if overhead is not None:
        lines.append("### Month one, in and out")
        lines.append("")
        lines.append(f"- In: {money(rev_m1)}")
        if cog_pct is not None:
            cogs = rev_m1 * cog_pct / 100
            lines.append(f"- Cost of making and delivering it ({cog_pct:.0f}%): {money(cogs)}")
            net = rev_m1 - cogs - overhead
            lines.append(f"- Everything else it takes to run: {money(overhead)}")
            lines.append(f"- **Left over: {money(net)}**")
        else:
            lines.append(f"- Everything else it takes to run: {money(overhead)}")
            lines.append("- Left over: not calculable until the cost of making it is known")
        lines.append("")
    else:
        gaps.append("What it costs to keep the lights on in month one — rent, tools, "
                    "software, your own time. Without it there is no profit line.")

    # --- What we could not work out ---
    # This section is the whole point of the change. It replaces the inline `_(not
    # specified)_` bullets that used to sit where a number should be.
    if gaps:
        lines.append("### What we could not work out")
        lines.append("")
        lines.append("Nothing below was invented to fill a gap. Each one needs a number the "
                     "evidence behind this idea did not give us, and each is worth pinning "
                     "down before you commit money:")
        lines.append("")
        for gap in gaps:
            lines.append(f"- {gap}")
        lines.append("")

    # --- Key assumptions ---
    # These two lists are the only FREE TEXT in this artifact — everything above is Python
    # formatting a number. They are also where the schema leaks: the model was asked for a
    # JSON object keyed `estimated_cac_gbp` and then asked to critique it, so it names the
    # key. `buyer_readable` is the choke point that makes that unrepresentable in output.
    if assumptions_list:
        lines.append("### What we assumed")
        lines.append("")
        for a in assumptions_list:
            lines.append(f"- {buyer_readable(str(a))}")
        lines.append("")

    # --- Weaknesses ---
    if weaknesses:
        lines.append("### Where this is weakest")
        lines.append("")
        for w in weaknesses:
            lines.append(f"- {buyer_readable(str(w))}")
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


# What the prompt said before the length contract existed, kept verbatim as the
# actuator-off branch: with `artifacts.enforce_length_budget` false the model must see
# exactly the instruction it has always seen, or "off" would still be a behaviour change
# and the before/after sweep would be measuring two different engines.
_LEGACY_LENGTH_RULE = (
    "Structure each artifact as several titled sections (markdown headings), each with "
    "real substance — never a single block or a heading with one thin line under it."
)


def _gen_one_artifact(op: Operator, cand_json: str, claims_json: str,
                      t: str, market_vars: Optional[Dict[str, str]] = None,
                      length_rule: str = _LEGACY_LENGTH_RULE,
                      check_op: Optional[Operator] = None,
                      claims: Optional[List[Dict[str, Any]]] = None,
                      ) -> tuple[str, str, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Generate one artifact type. Runs in a thread.

    Returns ``(type, content, raw, violations)``. ``raw`` is the financial model's
    structured assumptions dict — the verified INPUTS behind the rendered arithmetic. It
    used to be discarded the moment `_render_financial_model` had run, which is why the
    buyer's bundle could never ship a spreadsheet or a machine-readable financial file
    (register F1/F3). It is ``None`` for every other artifact type.

    ``violations`` is what the claim-check said about the finished prose, and is empty
    when ``check_op`` is None. It is REPORTED, never fatal: dropping an unverified
    marketing piece costs the buyer a tweet, but dropping build_spec costs them the pack,
    so the artifact ships with its violations recorded and the decision to gate on them is
    a separate, config-declared step taken once the live rate is known.
    """
    claims = claims or []
    feedback = ""
    violations: List[Dict[str, Any]] = []
    # One draft, plus one repair turn that is shown exactly what it got wrong. A second
    # repair is not free and the marketing path already measured the second one as the
    # point of diminishing returns (`_gen_one_content` gives its cheap pieces 2 attempts).
    attempts = 2 if (check_op is not None and t in _PROSE_ARTIFACT_TYPES) else 1

    for attempt in range(attempts):
        # The financial_model is a JSON fill whose length is a property of the Python
        # template, not of the model's restraint, so the word contract does not apply.
        system, user = render("artifacts", candidate_json=cand_json,
                              claims_json=claims_json, type=t,
                              length_rule=(length_rule if t in _PROSE_ARTIFACT_TYPES else ""),
                              **(market_vars or {}))
        if feedback:
            user = f"{user}\n\n{feedback}"
        coerce = ((lambda text: _coerce_bare_markdown_artifact(text, t))
                  if t in _PROSE_ARTIFACT_TYPES else None)
        with telemetry_stage("artifacts"):
            data = op.complete_json(system, user, temperature=0.3,
                                    validate=lambda d: _validate_artifact_shape(t, d),
                                    coerce=coerce)

        # FIX #3: financial_model returns structured JSON — arithmetic happens in Python.
        if t == "financial_model" and isinstance(data, dict):
            assumptions = data
            # Render to human-readable text, in the market's own money. The symbol comes
            # from the same config-declared currency_hint the prompt above was given, so
            # the figures and the symbol cannot disagree.
            claims_list = json.loads(claims_json) if claims_json else []
            content = _render_financial_model(
                assumptions, claims_list,
                currency=symbol_for_currency((market_vars or {}).get("currency_hint")),
            )
            return t, content, assumptions, []

        content = str(data.get("content", ""))
        if check_op is None or t not in _PROSE_ARTIFACT_TYPES:
            return t, content, None, []

        # The same verifier that has always guarded the copy we give away, now pointed at
        # the document the buyer pays for. It was never wired here: before 2026-08-14
        # every reference to `verify_claims_detail` sat on the marketing path.
        ok, violations = verify_claims_detail(check_op, content, claims)
        if ok:
            return t, content, None, []
        logger.info(
            f"Artifact {t} failed claim-check (attempt {attempt + 1}/{attempts})",
            extra={"type": t, "violations_n": len(violations)})
        feedback = (
            "Your previous draft FAILED claim-check. Rewrite so every factual statement "
            "is supported by the verified claims. Do not invent tools, prices, channels "
            "or benchmarks. Cutting an unsupported paragraph is always better than "
            "softening it. Violations:\n"
            f"{json.dumps(violations, ensure_ascii=False)}"
        )

    return t, content, None, violations


def generate_artifacts(
    op: Operator,
    cand: Candidate,
    checks: List[CheckResult],
    *,
    fast_op: Optional[Operator] = None,
    quality_op: Optional[Operator] = None,
    cfg: Optional[Any] = None,
    dossier: Optional[Dossier] = None,
    score: Optional[Any] = None,
) -> Dict[str, str]:
    """Generate build_spec, gtm_plan, ops_plan, financial_model in parallel.

    FIX #13: parallelizes 4 sequential LLM calls into 1 ThreadPoolExecutor batch.
    FIX #3: financial_model outputs JSON assumptions; Python performs arithmetic.

    The three PROSE artifacts ARE the £49 deliverable, so they route to ``quality_op``
    (the Gemini CLI -> Claude CLI quality chain) when provided. The financial_model is a
    pure JSON fill that Python turns into arithmetic, so it stays on the cheap ``fast_op``.
    Both fall back to ``op`` (the moat) when their preferred operator isn't supplied.

    ``dossier`` is optional and only feeds the `pack_data` data files (register F1/F2): pass
    the real one and the scorecard carries the six-axis ScoreResult; omit it and a candidate-
    only stand-in is used, which reports ``score_available: false`` rather than inventing
    zeros. It is never consulted for the prose artifacts.

    ``score`` exists because the publish path cannot pass ``dossier``: `run.py` calls this
    BEFORE `build_dossier`, so at that point there is a real ScoreResult but no Dossier to
    hang it on. Passing it here puts the six axes into the stand-in, which is the difference
    between a scorecard and a `score_available: false` placeholder in a bundle the buyer
    paid for. Ignored when ``dossier`` is supplied — the real one already carries its score.
    """
    cheap_op = fast_op or op
    prose_op = quality_op or op

    claims = [c.to_dict() for c in checks if c.verdict == Verdict.SUPPORTED]
    # Projected, not raw: the model must never be handed the engine's own field names.
    claims_json = json.dumps(_claims_prompt_view(claims))
    cand_json = json.dumps(_candidate_prompt_view(cand))

    # How long this pack is allowed to be, derived from the evidence it actually holds.
    # Measured 2026-08-14 over 59 live packs: 6,330 prose words written from 680 words of
    # retrieved passages, a 9.5x inflation, with 78.3% of sentences carrying no figure at
    # all. The model was asked to be "substantial (many paragraphs)" and had nothing left
    # to be substantial ABOUT, so it produced the connective prose that reads as machine
    # writing. The budget removes the reason to pad. It is computed either way so the
    # sweep can report on packs generated before the actuator was switched on.
    budget = evidence_budget.budget_for(checks, cfg)
    length_rule = (
        evidence_budget.length_rule(budget["per_artifact_words"], budget["words"])
        if budget["enforced"] else _LEGACY_LENGTH_RULE
    )
    logger.info(
        "artifact length budget: %s words/artifact from %s words of evidence (enforced=%s)",
        budget["per_artifact_words"], budget["words"], budget["enforced"],
        extra={"budget_words": budget["total_words"], "evidence_words": budget["words"],
               "evidence_sources": budget["sources"], "enforced": budget["enforced"]})

    # The claim-check always runs on the moat `op`, never on the (possibly cheap) writer:
    # a verification gate judged by the same model that produced the copy is not a gate.
    # Same rule `_gen_one_content` has always followed for the marketing pieces.
    claim_check_on = evidence_budget.artifacts_cfg(cfg)["claim_check"]

    types = ["build_spec", "gtm_plan", "ops_plan", "financial_model"]
    results: Dict[str, str] = {}
    unverified: Dict[str, List[Dict[str, Any]]] = {}
    financial_assumptions: Optional[Dict[str, Any]] = None

    # Money figures in the pack must be denominated in the OPPORTUNITY's market currency
    # (a US pack quoting £ is wrong), independently of the £49 the pack itself sells for.
    # The market is the CANDIDATE's, not the config's active one. Without the override the
    # currency hint is whatever market the run happens to be pointed at, while the pack lint
    # grades against `candidate.market` — the mismatch that put `£` in a `us` pack.
    market_vars = (market_kwargs(cfg, market=getattr(cand, "market", "") or "")
                   if cfg is not None else {k: "" for k in ALL_MARKET_KEYS})

    with ThreadPoolExecutor(max_workers=len(types)) as ex:
        futures = {
            ex.submit(_gen_one_artifact,
                      cheap_op if t == "financial_model" else prose_op,
                      cand_json, claims_json, t, market_vars, length_rule,
                      op if claim_check_on else None, claims): t
            for t in types
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                _, content, raw, violations = future.result()
                results[t] = content
                if violations:
                    unverified[t] = violations
                if t == "financial_model" and isinstance(raw, dict):
                    financial_assumptions = raw
            except Exception as e:
                logger.error(f"Artifact generation failed for {t}: {e}",
                             extra={"type": t, "error": str(e)})
                results[t] = ""

    # The measurement that decides whether this becomes a listing gate. Recorded rather
    # than enforced on purpose: the house rollout doctrine is to ship the check, measure
    # the live rate, repair, and only then flip an actuator. A threshold chosen before the
    # sweep is a guess, and this one would be a guess that unlists the catalogue.
    if claim_check_on:
        logger.info(
            "artifact claim-check: %s of %s prose artifacts carry unverified statements",
            len(unverified), len(evidence_budget.PROSE_TYPES),
            extra={"unverified_artifacts": sorted(unverified),
                   "unverified_n": sum(len(v) for v in unverified.values()),
                   "candidate_id": getattr(cand, "candidate_id", "")})

    # Register F1/F2 — the deterministic, zero-LLM data files (scorecard, financial model
    # and price comparables as JSON+CSV, plus the score radar as SVG). Gated on
    # `pack_data.enabled`, which defaults to False, so this is inert until switched on.
    # Wrapped because a data file is a nice-to-have and the £49 prose is not: a failure here
    # must cost the buyer a spreadsheet, never a pack.
    try:
        from . import pack_data as _pack_data
        results.update(_pack_data.artifacts_for_bundle(
            dossier if dossier is not None
            else Dossier(candidate=cand, decision=Decision.PASS, checks=checks, score=score),
            cfg, financial_assumptions=financial_assumptions))
    except Exception as e:
        # Stays broad — a data file is a nice-to-have and the £49 prose is not — but at ERROR
        # with a traceback: this is now where a genuine pack_data bug lands, because the
        # helpers below it no longer answer a crash with an empty price-anchor set.
        logger.exception(f"pack_data artifacts SKIPPED, the bundle ships without them: {e}",
                         extra={"error": str(e)})

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


def _currency_rule(cfg: Optional[Any], cand: Candidate) -> str:
    """The currency instruction for marketing copy, or "" when no market is declared.

    Deliberately quotes the SAME symbol `pack_linter.expected_currency` will grade against,
    imported from the linter rather than restated here. A second copy of the market→symbol
    table is how the generator and the grader drift apart, and that drift is the whole defect
    this exists to close: the pack is refused at publish for a symbol the generator was never
    told to use.
    """
    market = str(getattr(cand, "market", "") or "").strip()
    if cfg is None or not market:
        return ""
    try:
        from .pack_linter import expected_currency
        symbol = expected_currency(market)
    except ImportError as e:
        # An unmapped market already returns None from `expected_currency`
        # (`pack_linter.py:61-66`) — it does not raise — so the only failure this can own is
        # the import itself. Caught broadly, a bug in the linter's table produced `""` here:
        # the generator is told nothing about currency, the linter still grades against the
        # table, and the pack is refused at publish for a symbol nobody asked for. That is the
        # exact drift this function exists to close, so it is logged at ERROR, and anything
        # other than an ImportError now propagates instead of being read as "no market".
        logger.error(f"currency rule unavailable for market {market!r}: {e}",
                     extra={"market": market, "error": str(e)})
        symbol = ""
    if not symbol:
        return ""
    mv = market_kwargs(cfg, market=market)
    label = str(mv.get("market_label", "") or "").strip()
    code = str(mv.get("currency_hint", "") or "").strip()
    where = f" ({label})" if label else ""
    unit = f" ({code})" if code else ""
    # Worded to match `check_currency` (pack_linter.py:79) EXACTLY, because an instruction
    # stricter than the grader is its own defect here: rule (b) above requires figures
    # verbatim from a verified claim, and this repo never infers an FX rate. So a foreign
    # comparable is legitimate — the grader makes it a mere warning when the market's own
    # symbol appears too, and an error only when the buyer never sees their own currency.
    return (
        f"CURRENCY: this opportunity's market is {market}{where}, whose currency is "
        f"{symbol}{unit}. Quoting a foreign-currency figure verbatim from a verified claim is "
        f"fine and often necessary — keep the source's own symbol on it and attribute it to "
        f"that source. But the copy must never be foreign-currency ONLY: whenever you quote "
        f"one, at least one figure in {symbol} must appear alongside it, or the buyer never "
        f"sees their own money. Never convert a figure yourself; quote what the claim says."
    )


def _gen_one_content(gen_op: Operator, check_op: Operator, cand_json: str, claims_json: str,
                     claims: List[Dict[str, Any]], t: str,
                     currency_rule: str = "") -> Optional[Dict[str, Any]]:
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
                              claims_json=claims_json, type=t,
                              currency_rule=currency_rule)
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
    cfg: Optional[Any] = None,
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
    # Projected for the same reason as the artifact path: marketing copy is the MOST
    # buyer-facing prose the engine writes. `claims` below stays raw — the claim-check gate
    # is an internal verdict, not something a buyer ever reads.
    claims_json = json.dumps(_claims_prompt_view(claims))
    cand_json = json.dumps(_candidate_prompt_view(cand))

    # One definition, shared with the renderer that headings them and the lint that grades
    # them: `marketing_assets.ASSET_TYPES`. A local list here is how the generator, the
    # heading and the gate came to disagree about what a `launch_email` even is.
    types = list(ASSET_TYPES)

    # The artifact path has carried a currency hint since Epic D; this one never did, so the
    # model picked a symbol from the copy's implicit context. `lint_pack` grades every piece
    # against `candidate.market`, which is how `8ce5270ade208070` shipped a listing_page whose
    # money was ENTIRELY in € inside a `uk` pack. Derived from the candidate's own market, so
    # generation and grading read one field. Empty when no market is configured: the rule then
    # substitutes to nothing rather than instructing the model in a currency nobody declared.
    currency_rule = _currency_rule(cfg, cand)

    with ThreadPoolExecutor(max_workers=len(types)) as ex:
        futures = {
            ex.submit(_gen_one_content,
                      quality if t == "listing_page" else cheap_op,
                      checker, cand_json, claims_json, claims, t, currency_rule): t
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
