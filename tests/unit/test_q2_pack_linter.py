"""Q2 pack linter — the deterministic quality floor on the publish path.

Covers each check in prospector/pack_linter.py against the EXACT line formats
artifacts._render_financial_model emits (the arithmetic regexes are format-coupled by
design: the renderer computes from exact floats and prints rounded operands, so each
re-check carries a rounding-aware tolerance), plus the listing_gate seam in bridge.py —
lint_ok must be able to veto is_listed on its own.
"""
from __future__ import annotations

import json

import pytest
import requests as real_requests

from prospector import pack_linter
from prospector.artifacts import _render_financial_model
from prospector.bridge import listing_gate
from prospector.pack_linter import (
    CURRENCY_BY_MARKET,
    check_arithmetic,
    check_currency,
    check_sections,
    check_truncation,
    check_urls,
    expected_currency,
    lint_pack,
    symbol_for_currency,
)

# A financial model in exactly the renderer's format, arithmetic all correct.
# (payback 100/44 = 2.27 prints as ~2.3 — inside the display-rounding tolerance.)
GOOD_FIN = """## Financial Model

### Revenue
- **Month 1:** £50 × 10 customers = **£500**
- **Month 12:** £50 × 120 customers = **£6,000**
- **Growth (M1→M12):** 12.0×

### Gross Margin: **88%** (COGS: 12% of revenue)
- **Per customer/month:** £44.00

### Payback Period
- **~2.3 months** (CAC £100 / gross margin £44.00/month)

### Customer Lifetime Value (CLV)
- ~**£1,000** (ARPU £50 / 5.0% monthly churn)

### LTV:CAC Ratio
- 10.0
"""


# ---------------------------------------------------------------------------
# expected_currency / currency check
# ---------------------------------------------------------------------------

def test_expected_currency_prefix_matching():
    assert expected_currency("uk") == "£"
    assert expected_currency("uk-sc") == "£"
    assert expected_currency("US") == "$"
    assert expected_currency("de") is None
    assert expected_currency("") is None


def test_currency_wrong_symbol_in_financial_model_is_error():
    probs = check_currency(GOOD_FIN, "", "us")  # £ amounts in a US pack
    assert any(p["severity"] == "error" and p["check"] == "currency" for p in probs)


def test_currency_clean_uk_pack_passes():
    assert check_currency(GOOD_FIN, "Sells for £49.", "uk") == []


def test_currency_listing_copy_wrong_only_is_error_mixed_is_warning():
    wrong_only = check_currency("", "Charge $99/month.", "uk")
    assert [p["severity"] for p in wrong_only] == ["error"]
    mixed = check_currency("", "£49 here vs $99 in the US market.", "uk")
    assert [p["severity"] for p in mixed] == ["warning"]


def test_currency_unknown_market_never_blocks():
    assert check_currency(GOOD_FIN, "$99", "de") == []


# ---------------------------------------------------------------------------
# Anti-drift: the renderer writes money with the same table the linter checks
# ---------------------------------------------------------------------------

def test_config_currency_hint_resolves_to_the_symbol_the_linter_expects():
    """A market's declared currency_hint and the linter's expectation cannot drift.

    _render_financial_model prints with symbol_for_currency(currency_hint); check_currency
    rules with CURRENCY_BY_MARKET. If someone edits config.yaml's hint without the table,
    every pack in that market silently registers UNLISTED — so pin the join here.
    """
    from prospector.config import load_config

    cfg = load_config()
    markets = getattr(cfg, "markets", None) or {}
    assert markets, "config declares no markets"
    for code, expected in CURRENCY_BY_MARKET.items():
        hint = (markets.get(code) or {}).get("currency_hint")
        assert hint, f"market {code!r} declares no currency_hint"
        assert symbol_for_currency(hint) == expected, (code, hint)


def test_a_us_render_clears_the_us_currency_check():
    """The fail-closed state Q2 created: a $ render must lint clean in a US pack."""
    assumptions = {
        "monthly_price": 50.0,
        "target_customers_month_1": 10,
        "target_customers_month_12": 120,
        "estimated_cac_gbp": 100.0,
        "cost_of_goods_pct": 12.0,
        "estimated_monthly_churn_pct": 5.0,
    }
    text = _render_financial_model(assumptions, [], currency=symbol_for_currency("USD"))
    assert "$" in text and "£" not in text
    assert check_currency(text, "Sells for $49.", "us") == []
    assert check_sections(text) == []
    assert check_arithmetic(text) == []


# ---------------------------------------------------------------------------
# Arithmetic re-check
# ---------------------------------------------------------------------------

def test_arithmetic_correct_model_has_no_problems():
    assert check_arithmetic(GOOD_FIN) == []


@pytest.mark.parametrize("broken, fragment", [
    ("- **Month 1:** £50 × 10 customers = **£999**", "Month 1"),
    ("- **Growth (M1→M12):** 3.0×", "Growth"),
    ("### Gross Margin: **80%** (COGS: 12% of revenue)", "Gross margin"),
    ("- ~**£880** (ARPU £50 / 5.0% monthly churn)", "CLV"),
    ("- **~9.9 months** (CAC £100 / gross margin £44.00/month)", "Payback"),
])
def test_arithmetic_each_broken_line_is_caught(broken, fragment):
    # Swap exactly one correct line for its corrupted counterpart, keep the rest intact.
    replacements = {
        "Month 1": ("- **Month 1:** £50 × 10 customers = **£500**", broken),
        "Growth": ("- **Growth (M1→M12):** 12.0×", broken),
        "Gross margin": ("### Gross Margin: **88%** (COGS: 12% of revenue)", broken),
        "CLV": ("- ~**£1,000** (ARPU £50 / 5.0% monthly churn)", broken),
        "Payback": ("- **~2.3 months** (CAC £100 / gross margin £44.00/month)", broken),
    }
    good_line, broken_line = replacements[fragment]
    text = GOOD_FIN.replace(good_line, broken_line)
    assert text != GOOD_FIN, "test bug: replacement did not apply"
    probs = check_arithmetic(text)
    assert any(p["check"] == "arithmetic" and fragment in p["detail"] for p in probs), probs


def test_arithmetic_rounding_tolerance_not_a_false_positive():
    # price 49.5 renders as £50 (:,.0f); true revenue 495 prints alongside the rounded
    # operand — |50*10 − 495| = 5 must stay inside the 0.5*cust+1 band, not flag.
    text = GOOD_FIN.replace(
        "- **Month 1:** £50 × 10 customers = **£500**",
        "- **Month 1:** £50 × 10 customers = **£495**",
    )
    assert not any("Month 1" in p["detail"] for p in check_arithmetic(text))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def test_sections_all_present_and_empty_model_skipped():
    assert check_sections(GOOD_FIN) == []
    assert check_sections("") == []  # emptiness is validate_pack's finding, not ours


def test_sections_missing_revenue_is_error():
    probs = check_sections(GOOD_FIN.replace("### Revenue", "### Rev"))
    assert any("### Revenue" in p["detail"] for p in probs)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_truncation_ellipsis_mid_word_is_error():
    for ell in ("…", "..."):
        probs = check_truncation(
            {"oneLine": (f"Best applicat{ell}", "Best application for landlords")})
        assert len(probs) == 1 and probs[0]["check"] == "truncation", (ell, probs)


def test_truncation_ellipsis_at_word_boundary_is_fine():
    assert check_truncation(
        {"oneLine": ("Best app…", "Best app for landlords")}) == []


def test_truncation_hard_slice_at_cap_mid_word_is_error():
    src = "a" * 139 + "bcdef more words"
    probs = check_truncation({"headline": (src[:140], src)}, caps={"headline": 140})
    assert len(probs) == 1 and probs[0]["where"] == "headline"


def test_truncation_under_cap_and_empty_are_fine():
    assert check_truncation(
        {"headline": ("short and complete", "short and complete"),
         "subhead": ("", "anything")},
        caps={"headline": 140, "subhead": 280}) == []


# ---------------------------------------------------------------------------
# URL check (network stubbed at requests.head; DEFER philosophy on transients)
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, code):
        self.status_code = code

    def close(self):
        pass


def test_urls_dead_is_error_transient_is_warning(monkeypatch):
    # `get` is scripted too because a 404 is no longer taken on a HEAD's word: since
    # 2026-08-09 `_probe_url` confirms with GET (a server can refuse HEAD with 404 on a live
    # page) and then tries the slash-toggled variant. Genuinely dead means dead on all three.
    def fake_head(url, **kw):
        if "dead" in url:
            return _Resp(404)
        raise real_requests.ConnectTimeout("boom")

    def fake_get(url, **kw):
        if "dead" in url:
            return _Resp(404)
        raise real_requests.ConnectTimeout("boom")

    monkeypatch.setattr(pack_linter.requests, "head", fake_head)
    monkeypatch.setattr(pack_linter.requests, "get", fake_get)
    probs, n = check_urls({"gtm_plan": "see https://x.test/dead and https://x.test/slow"})
    assert n == 2
    by_sev = {p["severity"] for p in probs}
    assert by_sev == {"error", "warning"}
    assert any("HTTP 404" in p["detail"] for p in probs)


def test_urls_cache_prevents_reprobe_and_bounds_hold(monkeypatch, tmp_path):
    calls = []

    def fake_head(url, **kw):
        calls.append(url)
        return _Resp(200)

    monkeypatch.setattr(pack_linter.requests, "head", fake_head)
    cache = tmp_path / "url_cache.json"
    texts = {"ops_plan": "https://x.test/a https://x.test/a https://x.test/b"}
    probs1, n1 = check_urls(texts, cache_path=cache)
    probs2, n2 = check_urls(texts, cache_path=cache)
    assert (probs1, probs2) == ([], [])
    assert n1 == n2 == 2          # deduped
    assert len(calls) == 2        # second pass fully served from cache
    assert json.loads(cache.read_text())  # cache persisted


def test_urls_max_urls_bounds_probing(monkeypatch):
    calls = []

    def fake_head(url, **kw):
        calls.append(url)
        return _Resp(200)

    monkeypatch.setattr(pack_linter.requests, "head", fake_head)
    many = " ".join(f"https://x.test/{i}" for i in range(50))
    _, n = check_urls({"build_spec": many}, max_urls=5)
    assert n == 5 and len(calls) == 5


# ---------------------------------------------------------------------------
# lint_pack — the report contract
# ---------------------------------------------------------------------------

def _report(fin=GOOD_FIN, copy="Sells for £49.", market="uk", **kw):
    return lint_pack(
        artifacts={"financial_model": fin},
        listing_copy=copy,
        listing_texts={"oneLine": ("Complete line", "Complete line")},
        market=market,
        **kw,
    )


def test_lint_pack_clean_is_ok_and_json_serializable():
    report = _report()
    assert report["ok"] is True and report["problems"] == []
    json.dumps(report)  # the receipt written next to the dossier must serialize


def test_lint_pack_error_flips_ok_warning_does_not():
    assert _report(market="us")["ok"] is False  # £ model in a US pack
    mixed = _report(copy="£49 here vs $99 abroad.")
    assert mixed["ok"] is True
    assert any(p["severity"] == "warning" for p in mixed["problems"])


def test_lint_pack_urls_off_by_default_makes_no_network_calls(monkeypatch):
    def boom(*a, **kw):  # any probe attempt fails the test
        raise AssertionError("network call with check_urls_enabled off")

    monkeypatch.setattr(pack_linter.requests, "head", boom)
    report = _report(fin=GOOD_FIN + "\nSource: https://x.test/cite")
    assert report["ok"] is True and report["urls_checked"] == 0


# ---------------------------------------------------------------------------
# The bridge seam: lint_ok vetoes is_listed on its own
# ---------------------------------------------------------------------------

def test_listing_gate_lint_ok_is_a_veto():
    base = dict(uploaded=True, pack_complete=True, priced=True, bundle_complete=True)
    assert listing_gate(lint_ok=True, **base) is True
    assert listing_gate(lint_ok=False, **base) is False


@pytest.mark.parametrize("fence", ["uploaded", "pack_complete", "priced",
                                   "bundle_complete", "lint_ok"])
def test_listing_gate_every_fence_is_independent(fence):
    kwargs = dict(uploaded=True, pack_complete=True, priced=True,
                  bundle_complete=True, lint_ok=True)
    kwargs[fence] = False
    assert listing_gate(**kwargs) is False
