"""C3 — the `price_comparables` moat check: turn retrieved pages into CITED price anchors.

Why this exists. `verify.py` has always retrieved willingness-to-pay pages (the
`payer_solvency` confirm template is literally ``"{q} budget willingness to pay ROI"``) and
then thrown the quantitative content away — the verdict call classifies solvency and the
numbers on those pages are discarded. Every batch that ran without this check paid for
anchor evidence and binned it. This check keeps it.

What it is NOT. It is not a kill gate and cannot become one (`models.PRICING_CHECK`, guarded
in `kill_filter.is_hard_fail` and in `verify._verify_inner`'s run order). "No comparable
price found on the open web" is a statement about the web, not about the idea. It is also not
a price recommendation: it reports what the passages say buyers already pay, and
`pricing.price_for` decides — separately, deterministically, and only when explicitly
enabled — whether that evidence is strong enough to move a rung.

The rails, in the order they fire, because this feeds the money path:

1. **Synthesised sources are stripped** before the model sees them, exactly as in
   `verdict_for` — a price "found" in a cheap model's self-synthesis is not retrieval.
2. **Citation must resolve** to a source_id in the retrieved set.
3. **The number must literally appear in the cited passage** (`_appears_in`). This is the
   rail the LLM cannot talk its way past: it catches a plausible-looking £99 attributed to a
   page that never mentions 99, which no amount of prompt discipline reliably prevents.
4. **Sanity bounds** discard market sizes and funding rounds that survived as "prices".
5. **FX is declared, never guessed.** An anchor converts to pence only if config declares a
   rate for its currency. An unconvertible anchor is kept as readable evidence and is never
   eligible to move a price — a made-up exchange rate is an unsourced number on the money
   path, which is the one thing source-or-die exists to prevent.

Everything discarded lands in `ComparablesResult.rejected` with its reason. A rail that
drops evidence silently is indistinguishable from a rail that never ran.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from .config import Config
from .errors import GroundingInfrastructureError, ProviderExhaustedError
from .models import CHECKS, Candidate, ComparablesResult, PriceAnchor, PRICING_CHECK, Source
from .operator import Operator
from .prompts import render
from .retrieval import SearchProvider
from .telemetry import logger, track_latency
from .trimming import RATIONALE_MAX, clip_to_sentence
from .audit import audit


# Queries aimed at PRICE PAGES, not at the market. "{q} pricing plans cost per month" hits
# a vendor's own pricing page; "{q} market size" hits an analyst press release whose numbers
# are not prices. The templates are deterministic on purpose — a price page is found by
# naming the thing and the word "pricing", and an LLM query-gen call here buys nothing.
_COMPARABLE_TEMPLATES: list[str] = [
    "{q} pricing how much does it cost",
    "{q} price per month subscription plans",
    "{q} course OR template OR toolkit price",
]

CADENCES = ("one_off", "monthly", "annual", "unknown")

# Below this a "price" is noise (a 0, a "from $1" teaser fragment, a stray page number);
# above it, it is almost certainly a contract value, a salary, or a market size that the
# model mislabelled. Both bounds are in GBP pence, applied AFTER conversion.
DEFAULT_MIN_ANCHOR_PENCE = 100          # £1
DEFAULT_MAX_ANCHOR_PENCE = 500_000      # £5,000

# Passage budget for the extraction call. Prices sit in a sentence, not a treatise, and a
# long passage is where a mislabelled market size hides.
PASSAGE_TRUNCATE = 600


def comparables_config(cfg: Config) -> dict[str, Any]:
    """The `listing.pricing.comparables` block, with every default filled in.

    Tolerates the block being absent entirely: this check must not become the reason a
    config written before it existed fails to load.
    """
    pricing = (cfg.listing or {}).get("pricing") or {}
    raw = pricing.get("comparables") or {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "queries": list(raw.get("queries") or _COMPARABLE_TEMPLATES),
        "fx_to_gbp": {str(k).upper(): float(v)
                      for k, v in (raw.get("fx_to_gbp") or {"GBP": 1.0}).items()},
        "cadence_eligible": [str(c) for c in (raw.get("cadence_eligible") or ["one_off"])],
        "min_anchor_pence": int(raw.get("min_anchor_pence", DEFAULT_MIN_ANCHOR_PENCE)),
        "max_anchor_pence": int(raw.get("max_anchor_pence", DEFAULT_MAX_ANCHOR_PENCE)),
        "min_anchors": int(raw.get("min_anchors", 3)),
        "min_domains": int(raw.get("min_domains", 2)),
        "rung_adjust_enabled": bool(raw.get("rung_adjust_enabled", False)),
    }


def comparables_queries(cand: Candidate, cfg: Config, n: int = 3) -> list[str]:
    """Deterministic price-page queries for this candidate."""
    from .verify import _keywords
    base = _keywords(cand, k=6)
    tmpl = comparables_config(cfg)["queries"]
    return [t.format(q=base) for t in tmpl][:max(1, n)]


def _appears_in(amount: float, text: str) -> bool:
    """Does `amount` literally occur in `text`?

    This is the rail that makes an anchor a transcription rather than an assertion. It is
    deliberately strict about neighbouring digits: 49 must not match inside 149, 49.99, or
    4,900 — those are different prices, and a near-miss match would launder a fabricated
    number into a "cited" one, which is worse than no anchor at all.

    Thousands separators in the passage are normalised away first, so a passage reading
    "£1,299" matches an amount of 1299.
    """
    if amount <= 0:
        return False
    haystack = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text or "")
    forms: set[str] = {f"{amount:g}", f"{amount:.2f}"}
    if float(amount).is_integer():
        forms |= {str(int(amount)), f"{int(amount)}.0", f"{int(amount)}.00"}
    for form in forms:
        # Not preceded by a digit or a decimal point (blocks 149 / 1.49 matching 49),
        # not followed by a digit or by a decimal fraction (blocks 49.99 matching 49).
        if re.search(rf"(?<![\d.]){re.escape(form)}(?!\d|\.\d)", haystack):
            return True
    return False


def to_pence_gbp(amount: float, currency: str, fx_to_gbp: dict[str, float]) -> Optional[int]:
    """Convert to GBP pence using a CONFIG-DECLARED rate, or return None.

    None is the honest answer for a currency nobody declared a rate for. Inventing one puts
    an unsourced number on the money path; keeping the anchor unconverted keeps it readable
    in the dossier while barring it from moving a price.
    """
    rate = fx_to_gbp.get((currency or "").upper())
    if rate is None:
        return None
    return int(round(amount * float(rate) * 100))


def _reject(rejected: list[dict[str, Any]], raw: Any, reason: str) -> None:
    rejected.append({"raw": raw if isinstance(raw, dict) else str(raw), "reason": reason})


@track_latency(name="price_comparables_extract")
def extract_anchors(op: Operator, cand: Candidate, sources: list[Source],
                    cfg: Config) -> ComparablesResult:
    """Ask the moat brain to transcribe prices from `sources`, then verify every one.

    The model is the *finder*; this function is the *auditor*, and the auditor does not
    trust the finder. Nothing the model returns reaches the result without surviving the
    citation, literal-appearance, and bounds rails.
    """
    conf = comparables_config(cfg)
    from .verify import _market_vars, _served_is_provisional, _served_provider

    live = [s for s in sources
            if not str(getattr(s, "url", "")).startswith("synthesized://")]
    if not live:
        return ComparablesResult(
            degraded=True,
            rationale="No retrieved passages; no price anchors (graceful degradation).")

    passages = "\n".join(f"[{s.source_id}] {s.text[:PASSAGE_TRUNCATE]}" for s in live)
    system, user = render("price_comparables",
                          candidate_json=json.dumps(cand.to_dict()),
                          check_name=PRICING_CHECK,
                          check_question=CHECKS[PRICING_CHECK],
                          **_market_vars(cfg, for_moat=True))
    user = user.replace("{for each: [source_id] (url, published_at) text}", passages)
    user += f"\n\nPassages:\n{passages}"

    try:
        data = op.complete_json(system, user, temperature=0.0)
    except ProviderExhaustedError:
        # Every brain is out. This check is evidence-only, so an outage must not defer or
        # kill the candidate — it just produces no anchors, and the pack prices at its rung.
        logger.warning("price_comparables: all brains exhausted; no anchors this run",
                       extra={"candidate_id": getattr(cand, "candidate_id", None)})
        return ComparablesResult(sources=live, degraded=True,
                                 rationale="Verdict brain unavailable; no anchors extracted.")
    except Exception as e:
        logger.error(f"price_comparables extraction failed: {e}")
        return ComparablesResult(sources=live, degraded=True,
                                 rationale="Extraction call failed; no anchors extracted.")

    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {}) if data else {}
    if not isinstance(data, dict):
        data = {}

    by_id = {s.source_id: s for s in live}
    anchors: list[PriceAnchor] = []
    rejected: list[dict[str, Any]] = []

    for raw in (data.get("anchors") or []):
        if not isinstance(raw, dict):
            _reject(rejected, raw, "not an object")
            continue
        try:
            amount = float(raw.get("amount"))
        except (TypeError, ValueError):
            _reject(rejected, raw, "amount is not a number")
            continue
        source_id = str(raw.get("source_id") or "")
        src = by_id.get(source_id)
        if src is None:
            _reject(rejected, raw, "source_id does not match any retrieved passage")
            continue
        if not _appears_in(amount, src.text):
            _reject(rejected, raw,
                    f"amount {amount:g} does not appear in the cited passage "
                    f"(fabricated or mis-cited)")
            continue
        currency = str(raw.get("currency") or "").upper()
        cadence = str(raw.get("cadence") or "unknown").lower()
        if cadence not in CADENCES:
            cadence = "unknown"
        pence = to_pence_gbp(amount, currency, conf["fx_to_gbp"])
        if pence is not None and not (conf["min_anchor_pence"] <= pence
                                      <= conf["max_anchor_pence"]):
            _reject(rejected, raw,
                    f"{pence}p is outside the sane price band "
                    f"[{conf['min_anchor_pence']}, {conf['max_anchor_pence']}] — "
                    f"likely a market size, contract value, or salary")
            continue
        anchors.append(PriceAnchor(amount=amount, currency=currency, cadence=cadence,
                                   what=str(raw.get("what") or "")[:200],
                                   source_id=source_id, url=src.url,
                                   amount_pence_gbp=pence))

    if rejected:
        logger.warning(
            "price_comparables: dropped %d/%d proposed anchors (%s)",
            len(rejected), len(rejected) + len(anchors),
            "; ".join(sorted({str(r["reason"]).split(" (")[0] for r in rejected}))[:300],
            extra={"candidate_id": getattr(cand, "candidate_id", None)})

    return ComparablesResult(
        anchors=anchors, rejected=rejected, sources=live,
        rationale=clip_to_sentence(str(data.get("rationale", "")), RATIONALE_MAX),
        provider=_served_provider(op), provisional=_served_is_provisional(op))


@track_latency(name="price_comparables")
def run_price_comparables(op: Operator, search: SearchProvider, cfg: Config,
                          cand: Candidate,
                          pooled_sources: Optional[list[Source]] = None) -> ComparablesResult:
    """Retrieve price pages, pool them with passages the vet already paid for, extract.

    `pooled_sources` are the passages the six checks already fetched — chiefly
    `payer_solvency`'s willingness-to-pay pages, which is where the discarded quantitative
    content lived. Reusing them is the whole cost argument for this check: the marginal
    spend is a few price-page searches plus one extraction call, not a fresh vet.

    A retrieval outage here is not a deferral. This check is evidence-only: no anchors means
    the pack prices at its ladder rung, which is what it does today anyway.
    """
    r = cfg.retrieval
    queries = comparables_queries(cand, cfg)
    audit("verify_search", check=PRICING_CHECK,
          candidate_id=getattr(cand, "candidate_id", None),
          invoked_from="price_comparables.run_price_comparables")

    fetched: list[Source] = []
    n_failed = 0
    for q in queries:
        try:
            fetched.extend(search.search(q, k=r.results_per_query,
                                         max_chars=r.max_passage_chars))
        except GroundingInfrastructureError:
            raise  # circuit breaker: all providers dead — the caller halts the run
        except Exception as e:
            n_failed += 1
            logger.error(f"price_comparables search failed for {q!r}: {e}")

    seen: set[str] = set()
    uniq: list[Source] = []
    for s in list(fetched) + list(pooled_sources or []):
        if s.source_id not in seen:
            seen.add(s.source_id)
            uniq.append(s)

    if not uniq:
        logger.info("price_comparables: no passages (searches failed=%d); no anchors",
                    n_failed)
        return ComparablesResult(
            queries=queries, degraded=True,
            rationale="No passages retrieved; no price anchors (evidence-only check).")

    result = extract_anchors(op, cand, uniq, cfg)
    result.queries = queries
    audit("verify_search", check=PRICING_CHECK,
          candidate_id=getattr(cand, "candidate_id", None),
          queries=queries, queries_n=len(queries), n_failed=n_failed,
          passages_n=len(uniq), anchors_n=len(result.anchors),
          anchors_rejected_n=len(result.rejected),
          retrieval_failed=False, short_circuit_empty=False)
    logger.info("price_comparables: %d anchor(s) kept, %d rejected, from %d passage(s)",
                len(result.anchors), len(result.rejected), len(uniq))
    return result


def anchors_from_tags(cand: Candidate) -> list[PriceAnchor]:
    """Rehydrate the anchors `verify()` stashed on the candidate.

    Anchors travel on `candidate.tags` (the same side channel `artifacts` and `marketing`
    already use) rather than in the return signature of `verify()`, because they are
    evidence about the pack, not a verdict about the idea — and anything appended to
    `checks` becomes visible to `kill_filter.apply_gates` and the pass-ceiling logic, which
    must never see this check.

    Anything malformed is dropped rather than raised on: this runs on the publish path, and
    a corrupt tag must not be able to stop a vetted pack going live.
    """
    raw = (getattr(cand, "tags", None) or {}).get("price_comparables") or {}
    out: list[PriceAnchor] = []
    for a in (raw.get("anchors") or []):
        if not isinstance(a, dict):
            continue
        try:
            out.append(PriceAnchor(
                amount=float(a.get("amount")),
                currency=str(a.get("currency") or ""),
                cadence=str(a.get("cadence") or "unknown"),
                what=str(a.get("what") or ""),
                source_id=str(a.get("source_id") or ""),
                url=str(a.get("url") or ""),
                amount_pence_gbp=(None if a.get("amount_pence_gbp") is None
                                  else int(a["amount_pence_gbp"])),
            ))
        except (TypeError, ValueError):
            continue
    return out


def eligible_anchors(anchors: list[PriceAnchor], cfg: Config) -> list[PriceAnchor]:
    """The subset an automated price move is allowed to rest on.

    Two filters, both narrowing and both deliberate. Cadence: a £30/month SaaS seat is not
    comparable to a one-off pack, and the multiplier that would make it comparable is a
    commercial judgement, not a fact — so only cadences config names are eligible (default:
    `one_off` alone). Currency: only anchors with a config-declared FX rate carry a pence
    value at all.
    """
    conf = comparables_config(cfg)
    ok = set(conf["cadence_eligible"])
    return [a for a in anchors
            if a.amount_pence_gbp is not None and a.cadence in ok]


def anchor_evidence(anchors: list[PriceAnchor], cfg: Config) -> Optional[dict[str, Any]]:
    """Summarise eligible anchors into a decision input, or None if too thin to use.

    The thresholds (`min_anchors`, `min_domains`) are the bar for "this is evidence, not an
    anecdote". Domains are counted distinctly because three prices scraped from one vendor's
    own pricing page are one data point wearing three hats.

    The median is used rather than the mean: one mislabelled £4,999 enterprise tier that
    slipped past the bounds rail would drag a mean across a rung boundary, and the whole
    point of a rung is that crossing it is a deliberate act.
    """
    conf = comparables_config(cfg)
    elig = eligible_anchors(anchors, cfg)
    if len(elig) < conf["min_anchors"]:
        return None
    from urllib.parse import urlparse
    domains = {urlparse(a.url).netloc.replace("www.", "").lower()
               for a in elig if a.url}
    if len(domains) < conf["min_domains"]:
        return None
    pences = sorted(int(a.amount_pence_gbp) for a in elig)
    mid = len(pences) // 2
    median = pences[mid] if len(pences) % 2 == 1 else (pences[mid - 1] + pences[mid]) // 2
    return {
        "median_pence": median,
        "n": len(pences),
        "domains": sorted(domains),
        "citations": [a.source_id for a in elig],
    }
