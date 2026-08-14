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

# Rendered by the code under test, not transcribed: `check_arithmetic` is a set of regexes
# over another module's output, and a hand-typed fixture lets those regexes go vacuous the
# day a line is reworded — the checker then passes everything, which is worse than failing.
# (payback 100/44 = 2.27 prints as ~2.3 — inside the display-rounding tolerance.)
GOOD_FIN = _render_financial_model(
    {"revenue_model": "subscription", "monthly_price": 50,
     "target_customers_month_1": 10, "target_customers_month_12": 120,
     "estimated_cac_gbp": 100, "estimated_monthly_churn_pct": 5.0,
     "cost_of_goods_pct": 12, "overhead_month_1_gbp": 200}, [], "£")


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
    ("- **Gross margin: 80%** — making and delivering it costs 12%", "Gross margin"),
    ("- **~£880** — they pay £50 a month and about 5.0% stop each month.", "CLV"),
    ("- **Paid back in: ~9.9 months** (£100 to win a customer ÷ £44.00 kept each month)",
     "Payback"),
])
def test_arithmetic_each_broken_line_is_caught(broken, fragment):
    # Swap exactly one correct line for its corrupted counterpart, keep the rest intact.
    replacements = {
        "Month 1": ("- **Month 1:** £50 × 10 customers = **£500**", broken),
        "Growth": ("- **Growth (M1→M12):** 12.0×", broken),
        "Gross margin": ("- **Gross margin: 88%** — making and delivering it costs 12%",
                         broken),
        "CLV": ("- **~£1,000** — they pay £50 a month and about 5.0% stop each month.",
                broken),
        "Payback": ("- **Paid back in: ~2.3 months** (£100 to win a customer ÷ "
                    "£44.00 kept each month)", broken),
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
    probs = check_sections(GOOD_FIN.replace("### What it earns", "### Rev"))
    assert any("### What it earns" in p["detail"] for p in probs)


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


# ---------------------------------------------------------------------------
# A dead citation with a live archived copy (2026-08-09)
# ---------------------------------------------------------------------------
# `check_urls` had ZERO references to `archived_url`, so publishing a Wayback memento
# alongside every citation unblocked nothing: a 404 was an unconditional publish blocker
# whether or not the evidence was still readable. These pin the downgrade AND its limits.

def _dead_live_probes(monkeypatch, memento_status):
    """Citation URL is 404 on both HEAD and GET; the memento answers `memento_status`."""
    def fake_head(url, **kw):
        return _Resp(200 if "web.archive.org" in url else 404)

    def fake_get(url, **kw):
        if "web.archive.org" in url:
            return _Resp(memento_status)
        return _Resp(404)

    monkeypatch.setattr(pack_linter.requests, "head",
                        lambda url, **kw: _Resp(memento_status)
                        if "web.archive.org" in url else fake_head(url, **kw))
    monkeypatch.setattr(pack_linter.requests, "get", fake_get)


def test_a_dead_citation_with_a_live_memento_warns_instead_of_blocking(monkeypatch):
    _dead_live_probes(monkeypatch, 200)
    memento = "https://web.archive.org/web/20240101/https://x.test/dead"
    probs, _ = check_urls({"gtm_plan": "see https://x.test/dead"},
                          archived={"https://x.test/dead": memento})
    assert [p["severity"] for p in probs] == ["warning"], \
        "a citation whose evidence is still readable must not block the publish"
    assert memento in probs[0]["detail"], "the warning must name the standing-in copy"


def test_a_dead_memento_does_not_excuse_a_dead_citation(monkeypatch):
    """The inverse defect: trusting a stored `archived_url` without probing it would
    manufacture 'the buyer can verify this' from a field nobody checked."""
    _dead_live_probes(monkeypatch, 404)
    probs, _ = check_urls(
        {"gtm_plan": "see https://x.test/dead"},
        archived={"https://x.test/dead": "https://web.archive.org/web/1/https://x.test/dead"})
    assert [p["severity"] for p in probs] == ["error"]


def test_an_unreachable_archive_leaves_the_error_standing(monkeypatch):
    """Asymmetric on purpose: elsewhere an unproven state favours the citation, because the
    cost is condemning a live source. Here it would EXCUSE an unfollowable one."""
    import requests as real_requests

    def fake_head(url, **kw):
        if "web.archive.org" in url:
            raise real_requests.ConnectTimeout("archive down")
        return _Resp(404)

    def fake_get(url, **kw):
        if "web.archive.org" in url:
            raise real_requests.ConnectTimeout("archive down")
        return _Resp(404)

    monkeypatch.setattr(pack_linter.requests, "head", fake_head)
    monkeypatch.setattr(pack_linter.requests, "get", fake_get)
    probs, _ = check_urls(
        {"gtm_plan": "see https://x.test/dead"},
        archived={"https://x.test/dead": "https://web.archive.org/web/1/https://x.test/dead"})
    assert [p["severity"] for p in probs] == ["error"]


def test_a_throttled_memento_is_retried_before_it_is_believed(monkeypatch):
    """Measured 2026-08-13: web.archive.org served 503 for a memento CDX had just named, and
    503 fell through as 'not alive' — so a pack whose evidence WAS archived stayed blocked, and
    17 such refusals sat in `store/lint_url_cache.json`. A throttle is the archive declining to
    answer, not an answer."""
    monkeypatch.setattr(pack_linter.time, "sleep", lambda _s: None)
    seen = []

    def probe(url, **kw):
        if "web.archive.org" not in url:
            return _Resp(404)
        seen.append(url)
        return _Resp(503 if len(seen) < 3 else 200)

    monkeypatch.setattr(pack_linter.requests, "head", probe)
    monkeypatch.setattr(pack_linter.requests, "get", probe)
    memento = "https://web.archive.org/web/20240101/https://x.test/dead"
    probs, _ = check_urls({"gtm_plan": "see https://x.test/dead"},
                          archived={"https://x.test/dead": memento})
    assert [p["severity"] for p in probs] == ["warning"], \
        f"gave up on a memento that answered on the third try: {probs}"


def test_a_slow_memento_gets_more_than_the_citation_budget(monkeypatch):
    """Wayback playback reassembles a stored page; a live 404 answers instantly. Sized for the
    latter, the probe timed the former out and read that as 'not servable' — which is how
    `5e8f3b69369be3a8` stayed blocked with its evidence sitting in the archive."""
    monkeypatch.setattr(pack_linter.time, "sleep", lambda _s: None)
    budgets = []

    def probe(url, **kw):
        if "web.archive.org" not in url:
            return _Resp(404)
        budgets.append(kw.get("timeout"))
        return _Resp(200)

    monkeypatch.setattr(pack_linter.requests, "head", probe)
    monkeypatch.setattr(pack_linter.requests, "get", probe)
    check_urls({"gtm_plan": "see https://x.test/dead"}, timeout_s=5.0,
               archived={"https://x.test/dead": "https://web.archive.org/web/1/x"})
    assert budgets and min(budgets) >= pack_linter._MEMENTO_TIMEOUT_S, \
        f"memento probed on the citation budget: {budgets}"


def test_an_unreachable_memento_is_not_cached_either(tmp_path, monkeypatch):
    """A timeout is our outage, not a verdict on the capture. Caching it would strand the pack
    for `_URL_CACHE_TTL_S` on a network blip."""
    monkeypatch.setattr(pack_linter.time, "sleep", lambda _s: None)

    def probe(url, **kw):
        if "web.archive.org" in url:
            raise real_requests.ReadTimeout("slow playback")
        return _Resp(404)

    monkeypatch.setattr(pack_linter.requests, "head", probe)
    monkeypatch.setattr(pack_linter.requests, "get", probe)
    cache_path = tmp_path / "lint_url_cache.json"
    check_urls({"gtm_plan": "see https://x.test/dead"}, cache_path=cache_path,
               archived={"https://x.test/dead": "https://web.archive.org/web/1/x"})
    written = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    assert not [k for k in written if "web.archive.org" in k], \
        f"cached our own timeout as a verdict: {written}"


def test_a_throttled_memento_is_never_cached_as_dead(tmp_path, monkeypatch):
    """The compounding half: a 503 written into the 7-day URL cache pins our own throttling
    onto the memento long after the archive recovers."""
    monkeypatch.setattr(pack_linter.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pack_linter.requests, "head",
                        lambda url, **kw: _Resp(503 if "web.archive.org" in url else 404))
    monkeypatch.setattr(pack_linter.requests, "get",
                        lambda url, **kw: _Resp(503 if "web.archive.org" in url else 404))
    cache_path = tmp_path / "lint_url_cache.json"
    memento = "https://web.archive.org/web/20240101/https://x.test/dead"
    check_urls({"gtm_plan": "see https://x.test/dead"}, cache_path=cache_path,
               archived={"https://x.test/dead": memento})
    written = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    assert not [k for k in written if "web.archive.org" in k], \
        f"cached a throttle as a verdict: {written}"


def test_no_archived_map_behaves_exactly_as_before(monkeypatch):
    """The regression control: absent mementos, this path is untouched."""
    _dead_live_probes(monkeypatch, 200)
    probs, _ = check_urls({"gtm_plan": "see https://x.test/dead"})
    assert [p["severity"] for p in probs] == ["error"]


# ---------------------------------------------------------------------------
# The title is the marketing headline (2026-08-09)
# ---------------------------------------------------------------------------
# Measured on the 48 live catalogue rows: median title 96.5 chars, 2 of 48 inside the
# 40-60 band, four separators in use, 4 rows with no descriptor at all — while the SAME
# packs carried a card_line of min 40 / median 52.5 / max 60. The short form was always
# writable; `prompts/generate_system.md` just asked for "a short name, then a dash, then
# what it does" and named no length.

_GOOD = "Standstill income cover for beekeepers"  # 38 chars, business-first


def _title_report(title, **kw):
    """lint_pack over a clean pack, varying only the title."""
    return _report(house_fields={"title": title}, **kw)


def _title_details(title, **kw):
    return [p["detail"] for p in _title_report(title, **kw)["problems"]
            if p["check"] == "title"]


def test_a_title_in_the_declared_format_is_clean():
    assert len(_GOOD) <= pack_linter.TITLE_MAX_CHARS
    assert _title_details(_GOOD) == []


def test_a_comma_may_carry_the_revenue_model_instead_of_for():
    # The second accepted shape: when HOW the business earns is the interesting fact, it
    # qualifies the trade after a comma rather than naming the payer with "for".
    assert _title_details("NHS care-fee reclaim service, paid on commission") == []


def test_an_over_length_title_is_reported():
    long = "Statutory standstill income cover for sole-trader beekeepers ordered to " \
           "stop moving their hives"
    assert len(long) > pack_linter.TITLE_MAX_CHARS
    details = _title_details(long)
    assert len(details) == 1
    assert f"exceeds the {pack_linter.TITLE_MAX_CHARS} limit" in details[0]


def test_a_coined_product_name_is_reported():
    # The 2026-08-13 finding, in the founder's words: "the title tells me nothing, it feels
    # cryptic". An intercapped word is the first thing a scanner reads and it means nothing
    # until you already own the pack.
    details = _title_details("SwarmHold, income cover for beekeepers in a standstill")
    assert len(details) == 1
    assert "coined product name 'SwarmHold'" in details[0]


def test_an_initialism_a_reader_already_knows_is_not_a_coined_name():
    # The distinction the check turns on. NHS is all-caps, so it must not match the
    # intercaps pattern — flagging it would block the most informative titles we have.
    assert _title_details("Unpaid-hours audits for NHS doctors and nurses") == []


def test_an_imperative_opener_is_reported():
    # Rejected by the founder on 2026-08-13: "sell/run is overused and too blunt for
    # 149 pack".
    details = _title_details("Sell unpaid-hours audits to NHS doctors")
    assert any("imperative 'sell'" in d for d in details)


def test_a_noun_that_is_also_a_verb_is_not_read_as_an_imperative():
    # "Price", "cover" and "track" open correct titles. A false positive here blocks a good
    # line, which is why the imperative set deliberately excludes them.
    assert _title_details("Price data for UK freelance creatives") == []


def test_an_article_opener_is_reported():
    details = _title_details("The appeal service for refused carers")
    assert any("article 'the'" in d for d in details)


def test_a_title_that_names_no_buyer_is_reported():
    details = _title_details("Unpaid-hours audits")
    assert len(details) == 1
    assert "names no buyer" in details[0]


def test_a_third_person_verb_after_the_comma_is_reported():
    # The dominant live shape on 2026-08-09: "HoursBack, finds the pay …". The comma may
    # qualify the trade; it may not turn the title back into a sentence about the customer.
    details = _title_details("Rota audits, finds the pay your trust has not paid")
    assert any("verb 'finds'" in d for d in details)


def test_the_actuator_is_on_by_default_so_a_breaching_title_cannot_reach_a_buyer():
    # This inverts the 2026-08-09 test that pinned the actuator OFF. That default existed
    # for one stated reason — the rule errored on 46 of 48 live packs, so blocking would
    # have unlisted a catalogue that predated it — under the stated condition "turn it on
    # once the catalogue has been retitled". Met and measured on 2026-08-14: 62/62 live rows
    # re-fetched, 0 flagged by this check.
    #
    # It is a code default rather than a config one because the config-only version was one
    # uncommitted line in a file another session owned: `git checkout config.yaml` would
    # have unbound the gate with no test going red. A gate whose safe state depends on an
    # edit surviving is not a gate.
    report = _title_report("SwarmHold")
    assert report["ok"] is False
    assert any(p["severity"] == "error"
               for p in report["problems"] if p["check"] == "title")


def test_the_actuator_can_still_be_turned_off_but_only_deliberately():
    # The other half, and the one that makes the test above mean something: if `block` had
    # simply been hard-wired, the test above would pass while the operator lost the switch.
    # An explicit false still downgrades every breach to a warning and lets the pack list.
    report = _title_report("SwarmHold", title_block_on_breach=False)
    assert report["ok"] is True
    assert all(p["severity"] == "warning"
               for p in report["problems"] if p["check"] == "title")


def test_the_publish_path_takes_its_default_from_the_linter_not_its_own_literal():
    """The default that actually decides whether a pack lists is bridge.py's, not this
    module's: `publish_pass` reads `listing_cfg.get("title_block_on_breach", <default>)`, so
    a second literal there could disagree with the signature above and nothing would go red
    — the linter's tests would pass while production shipped the other behaviour.

    So the fallback must be the imported NAME, and that is a source-level invariant, which
    is why this reads the source. Asserting it by running `publish_pass` would need a whole
    Dossier and would still only prove the value on the day, not that the two sites are one.
    """
    import ast
    import pathlib

    from prospector import pack_linter
    assert pack_linter.TITLE_BLOCK_ON_BREACH_DEFAULT is True

    src = (pathlib.Path(pack_linter.__file__).parent
           / "bridge.py").read_text(encoding="utf-8")
    fallbacks = [
        node.args[1] for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get" and len(node.args) == 2
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "title_block_on_breach"
    ]
    assert fallbacks, "bridge.py no longer reads title_block_on_breach from the listing config"
    for fb in fallbacks:
        assert isinstance(fb, ast.Name) and fb.id == "TITLE_BLOCK_ON_BREACH_DEFAULT", (
            "bridge.py hard-codes its own default for the title actuator; use the linter's "
            f"constant so the two cannot drift (found {ast.dump(fb)})")


def test_an_empty_title_errors_whatever_the_actuator_says():
    # Not a format opinion: a pack with no title has nothing to sell on any surface.
    report = _title_report("")
    assert report["ok"] is False
    assert [p["detail"] for p in report["problems"] if p["check"] == "title"] == ["empty"]


def test_no_title_in_house_fields_behaves_exactly_as_before():
    assert [p for p in _report()["problems"] if p["check"] == "title"] == []


def test_split_title_takes_the_first_separator_so_a_descriptor_may_contain_commas():
    name, desc = pack_linter.split_title("SwarmHold, income cover, paid weekly")
    assert (name, desc) == ("SwarmHold", "income cover, paid weekly")


def test_split_title_still_reads_a_raw_dash_title():
    # `nodash` rewrites the dash to ", " at publish, so the linter normally sees a comma.
    # It must read the raw form honestly too, or a pre-choke-point title reads as "no
    # descriptor" and the report blames the wrong defect.
    assert pack_linter.split_title("SwarmHold — income cover") == ("SwarmHold", "income cover")
    assert pack_linter.split_title("SwarmHold – income cover") == ("SwarmHold", "income cover")
    assert pack_linter.split_title("SwarmHold - income cover") == ("SwarmHold", "income cover")


def test_a_title_over_length_AND_name_first_reports_both():
    t = "SwarmHold, automated statutory income cover for sole-trader beekeepers"
    assert len(t) > pack_linter.TITLE_MAX_CHARS
    details = [p["detail"] for p in _title_report(t)["problems"] if p["check"] == "title"]
    assert len(details) == 2
    assert any("exceeds the" in d for d in details)
    assert any("coined product name" in d for d in details)


# ---------------------------------------------------------------------------
# The descriptor may only restate what the pack already says (2026-08-09)
# ---------------------------------------------------------------------------
# `prompts/retitle.md` carries a TRUTH RULE. A prompt instruction is a request evaluated by
# the same process that produces the error, so it is not a control. These tests pin the
# control that replaced it.

_SRC = ["Chases the retention main contractors hold back after practical completion.",
        "Get every penny of retention released without a solicitor."]


def _claims(descriptor, sources=_SRC, market="uk", block=False):
    # No name prefix: since 2026-08-13 a title has none, and `check_title_claims` judges the
    # whole string. Prepending "RetainRelease, " here would have every case report the
    # coinage as a word the source never uses, and the assertions would be measuring the
    # fixture rather than the rule.
    return pack_linter.check_title_claims(descriptor, sources, market=market, block=block)


def _hard(problems):
    return [p for p in problems if p["check"] == "title_claim"]


def _soft(problems):
    return [p for p in problems if p["check"] == "title_new_word"]


def test_a_descriptor_that_only_restates_the_source_is_clean():
    assert _claims("chases the retention contractors hold back") == []


def test_a_figure_the_pack_never_states_is_a_hard_claim():
    out = _hard(_claims("recovers 40% of retention"))
    assert len(out) == 1 and "40" in out[0]["detail"]


def test_a_figure_the_pack_does_state_is_not_a_claim():
    assert _hard(_claims("recovers 40% of retention",
                         sources=_SRC + ["Typically 40% of the sum withheld."])) == []


def test_the_declared_market_supports_its_own_name_without_prose():
    # A pack whose market is `uk` IS a UK pack. Requiring the word in the one-liner would
    # make the check fire on a true statement, which is how a check gets switched off.
    assert _hard(_claims("chases retention for UK subcontractors", market="uk")) == []


def test_naming_a_market_the_pack_is_not_in_is_a_hard_claim():
    out = _hard(_claims("chases retention for UK subcontractors", market="us"))
    assert len(out) == 1 and "declared market" in out[0]["detail"]


def test_a_sub_national_place_gets_no_market_credit():
    # "us" -> "Texas" is a narrowing to one state, not a restatement of the market.
    out = _hard(_claims("chases retention for Texas subcontractors", market="us"))
    assert len(out) == 1 and "texas" in out[0]["detail"].lower()


def test_an_institution_the_pack_never_names_is_a_hard_claim():
    out = _hard(_claims("chases retention through the NHS", market="uk"))
    assert len(out) == 1 and "nhs" in out[0]["detail"].lower()


def test_an_absolute_the_pack_never_makes_is_a_hard_claim():
    out = _hard(_claims("guaranteed retention recovery"))
    assert len(out) == 1 and "guaranteed" in out[0]["detail"]


def test_an_absolute_the_pack_does_make_rides_through():
    # The rule is "no NEW claim", not "no strong words": the source says "every penny".
    assert _hard(_claims("gets every penny of retention back")) == []


def test_a_timescale_with_no_digit_is_still_caught():
    out = _hard(_claims("same-day retention recovery"))
    assert len(out) == 1 and "same-day" in out[0]["detail"]


def test_a_proper_noun_the_pack_never_uses_is_a_hard_claim():
    out = _hard(_claims("chases retention under the Construction Act"))
    assert any("Construction" in p["detail"] for p in out)


def test_the_audience_narrowing_that_prompted_this_check_is_reported_not_silent():
    # The live smoke test produced "shows what UK creatives are charging" for a pack whose
    # own copy says freelancers. "creatives" is not a figure, a place or a guarantee, so no
    # hard rule catches it — and a machine cannot rule on whether it is fair paraphrase.
    # It must therefore reach the reviewer as a NAMED word, never as prose to diff by eye.
    src = ["Shows freelancers what their peers are charging, by discipline and region."]
    out = _claims("shows what UK creatives are charging", sources=src, market="uk")
    assert _hard(out) == []
    assert len(_soft(out)) == 1 and "creatives" in _soft(out)[0]["detail"]


def test_a_paraphrase_of_a_word_the_source_inflects_differently_is_not_reported():
    # "charging" in the source supports "charges" in the descriptor; a stemmer that missed
    # this would flood the reviewer with false new words and get itself ignored.
    src = ["Shows freelancers what their peers are charging."]
    assert _soft(_claims("shows what peers charge", sources=src)) == []


def test_the_soft_tier_is_a_warning_even_when_the_actuator_is_on():
    # Blocking a listing on "is this fair paraphrase?" would put a machine in charge of a
    # judgement it cannot make. Only the hard tier escalates.
    src = ["Shows freelancers what their peers are charging."]
    out = _claims("shows what UK creatives are charging", sources=src, block=True)
    assert [p["severity"] for p in _soft(out)] == ["warning"]


def test_the_actuator_promotes_only_the_hard_tier():
    assert [p["severity"] for p in _hard(_claims("guaranteed recovery"))] == ["warning"]
    assert [p["severity"] for p in _hard(_claims("guaranteed recovery", block=True))] == ["error"]


def test_a_title_with_no_separator_is_still_claim_checked():
    # The regression that shipped hidden inside the 2026-08-13 register change. This check
    # used to read only the half after a separator and return [] when there was none — which
    # was safe while every title was `Name, descriptor`, and became a hole the moment the
    # format stopped having a name in it: EVERY correctly-formatted title would have been
    # exempt from the truth rule, on a storefront whose whole claim is source-or-die.
    out = pack_linter.check_title_claims(
        "Guaranteed retention recovery for subcontractors", _SRC, market="uk")
    assert _hard(out), "a business-first title must still answer to the claim rules"


def test_each_offending_token_is_reported_once_not_once_per_rule():
    # "UK" trips both the geography rule and the proper-noun rule.
    out = _hard(_claims("chases UK retention", market="us"))
    assert len(out) == 1


def test_a_title_cased_descriptor_does_not_read_as_a_wall_of_proper_nouns():
    # Capitalisation only signals a proper noun in a string that is otherwise plain prose.
    # In Title Case it signals nothing, and reading it as six claims would flag a true
    # statement — measured on 5 of the 7 live rows this rule fired on before the guard.
    out = _hard(pack_linter.check_title_claims(
        "DLAChild, The Primary Carer's DLA Child Claim Engine", _SRC, market="uk"))
    assert out == []


def test_the_proper_noun_rule_still_applies_to_plain_prose():
    out = _hard(_claims("chases retention under the Construction Act"))
    assert any("Construction" in p["detail"] for p in out)


def test_a_sentence_opening_verb_is_not_read_as_a_proper_noun():
    # "See what your peers charge" — 'See' is capitalised by grammar. Measured on the 48 live
    # rows this exempted 'See' (x3) and 'Run' (x2), every one an opening verb of a headline.
    out = _hard(pack_linter.check_claims(
        "See what your peers charge", ["shows what peers charge"],
        market="uk", where="headline"))
    assert out == []


def test_a_capital_after_a_full_stop_is_also_exempt():
    out = _hard(pack_linter.check_claims(
        "Chases retention. Recovers it too.", ["chases retention and recovers it"],
        market="uk", where="headline"))
    assert out == []


def test_a_proper_noun_mid_sentence_is_still_caught():
    out = _hard(pack_linter.check_claims(
        "See what the Construction Act says", ["shows what the rules say"],
        market="uk", where="headline"))
    # `d["detail"]`, not `d`: a finding is a dict, so `"Construction" in d` asks whether it is
    # a KEY and is always False — the assertion could never fail for the right reason, and the
    # linter it guards was working the whole time.
    assert any("Construction" in d["detail"] for d in out)
