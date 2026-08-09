"""§25.6 item 2 — the deterministic numeric-citation check, SHADOW MODE ONLY.

The load-bearing test is `test_check_result_identical_with_shadow_on_and_off`:
it runs the real `verify.run_check` twice over the same scripted operator and
stub search provider, once with `numeric_citation.enabled` off and once on, and
asserts the `CheckResult` is byte-identical (compared as its JSON serialisation,
so a float that merely reprs the same is not enough). A second assertion proves
the identity is not vacuous — the shadow log must show it found an untraceable
figure on that very run.

The other invariant is `test_unsure_is_always_reported_as_supported`: the check
exists to catch fabricated numbers, so every "I cannot tell" path must answer
SUPPORTED. A false violation accuses a rationale of inventing a figure it did
not invent, which is strictly worse than missing one.

No network, no LLM: the operator and the search provider are scripted stubs. No
production store is touched: every test pins `numeric_citation.log_dir` to
`tmp_path`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from prospector import numeric_citation as nc
from prospector import verify as V
from prospector.config import load_config
from prospector.models import Candidate, Source

# --------------------------------------------------------------------------- #
# Helpers — no network, no LLM
# --------------------------------------------------------------------------- #

def _cfg(tmp_path, *, enabled: bool, **over):
    """A real Config with the numeric_citation block pinned at tmp_path.

    Set with `setattr`, never as a constructor kwarg: `config.py` is owned by a
    concurrent session while this lands, so the test must not depend on the field
    existing yet. `settings_from_config` reads it with `getattr(..., {}) or {}`.
    """
    cfg = load_config()
    block = {"enabled": enabled, "shadow_mode": True,
             "log_dir": str(tmp_path / "nc"), **over}
    setattr(cfg, "numeric_citation", block)
    return cfg


def _rows(tmp_path) -> list[dict]:
    out = []
    for p in sorted((tmp_path / "nc").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _srcs(*texts: str) -> list[Source]:
    return [Source(source_id=f"s{i}", url=f"https://example.test/{i}", text=t)
            for i, t in enumerate(texts, start=1)]


def _surfaces(text: str, **kw) -> list[str]:
    return [f.surface for f in nc.extract_figures(text, **kw)]


def _values(text: str, **kw) -> list[float]:
    return [f.value for f in nc.extract_figures(text, **kw)]


# --------------------------------------------------------------------------- #
# 1. Extraction grammar
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("text,surface,value,kind", [
    # currency, with and without a magnitude suffix or a thousands separator
    ("Revenue of £1.2m across the segment", "£1.2m", 1_200_000.0, "currency"),
    ("A one-off $49 fee", "$49", 49.0, "currency"),
    ("The market is €3,400 per seat", "€3,400", 3400.0, "currency"),
    ("Spend reached £5 million last year", "£5 million", 5_000_000.0, "currency"),
    # percentages, sign and spelled
    ("Adoption sits at 12% today", "12%", 12.0, "percent"),
    ("Churn of 12.5 per cent annually", "12.5 per cent", 12.5, "percent"),
    ("Take-up of 40 percent", "40 percent", 40.0, "percent"),
    # plain counts with separators
    ("There are 1,761 registered firms", "1,761", 1761.0, "count"),
    # multipliers
    ("A 3x improvement in throughput", "3x", 3.0, "multiplier"),
    ("Costs fell 2.5 times", "2.5 times", 2.5, "multiplier"),
    # magnitude without currency
    ("4 million households are affected", "4 million", 4_000_000.0, "magnitude"),
    ("A 3bn addressable market", "3bn", 3_000_000_000.0, "magnitude"),
    # units
    ("Serving 5,000 users in the first year", "5,000", 5000.0, "count"),
])
def test_extract_single_figure_formats(text, surface, value, kind):
    figs = nc.extract_figures(text)
    assert len(figs) == 1, [f.surface for f in figs]
    assert (figs[0].surface, figs[0].value, figs[0].kind) == (surface, value, kind)


def test_extract_unit_word_is_recorded_but_not_part_of_the_surface():
    (fig,) = nc.extract_figures("Serving 5,000 users in the first year")
    assert fig.surface == "5,000"
    assert fig.unit == "users"


@pytest.mark.parametrize("text,values", [
    ("Between 10–20 practices adopted it", [10.0, 20.0]),
    ("Prices range £4.99–£9.99 per pack", [4.99, 9.99]),
    ("Budgets of £5 million to £8 million", [5_000_000.0, 8_000_000.0]),
    ("Adoption of 10–20% across the sector", [10.0, 20.0]),
])
def test_extract_ranges_yield_both_endpoints(text, values):
    """A range asserts BOTH numbers, so both must be traceable."""
    assert _values(text) == values


def test_extract_spans_point_at_the_surface_form():
    text = "Revenue of £1.2m across the segment"
    (fig,) = nc.extract_figures(text)
    assert text[fig.start:fig.end] == "£1.2m"


def test_bare_years_ignored_by_default_and_kept_when_configured():
    assert nc.extract_figures("In 2024 the rule changed") == []
    assert _values("In 2024 the rule changed", ignore_years=False) == [2024.0]
    # A year wearing a currency symbol is a PRICE, not a date — never suppressed.
    assert _values("£2024 was charged") == [2024.0]


def test_bare_prose_counting_is_not_a_figure():
    """Under-reaching on bare numbers is the safe direction (module rule 1)."""
    assert nc.extract_figures("2 of the sources agree and three passages differ") == []
    # ... but a separator or a big value makes it a claim.
    assert _values("1,761 firms") == [1761.0]
    assert _values("35000 units") == [35000.0]


def test_min_digits_filters_short_figures():
    assert _values("A 3x improvement", min_digits=1) == [3.0]
    assert nc.extract_figures("A 3x improvement", min_digits=2) == []


def test_figures_are_deduped_by_kind_and_value():
    figs = nc.extract_figures("12% now and 12% next year, plus £12")
    assert [(f.value, f.kind) for f in figs] == [(12.0, "percent"), (12.0, "currency")]


# --------------------------------------------------------------------------- #
# 2. Matching — surface first, then normalised
# --------------------------------------------------------------------------- #

def test_surface_match_is_reported_as_such():
    (fig,) = nc.extract_figures("Uptake of 92% in the sector")
    sup = nc.figure_supported(fig, _srcs("A survey found 92% uptake"))
    assert (sup.supported, sup.match_kind, sup.matched_url) == (
        True, "surface", "https://example.test/1")


@pytest.mark.parametrize("rationale,passage", [
    # separators normalise away in both directions
    ("There are 1,761 firms", "the register lists 1761 firms"),
    ("There are 1761 firms", "the register lists 1,761 firms"),
    # magnitude suffix vs spelled magnitude vs fully expanded digits
    ("Revenue of £1.2m", "generated 1.2 million in revenue"),
    ("Revenue of £1.2m", "generated 1,200,000 in revenue"),
    ("Revenue of £1.2m", "generated 1200000 in revenue"),
    ("Revenue of £1,200,000", "generated 1.2 million in revenue"),
    # percent sign vs spelled percent
    ("Uptake of 12%", "12 per cent of respondents"),
    ("Uptake of 12 per cent", "uptake was 12%"),
    # trailing zeros are the same number
    ("Uptake of 92%", "uptake was 92.0 of the cohort"),
])
def test_normalised_matching(rationale, passage):
    (fig,) = nc.extract_figures(rationale)
    sup = nc.figure_supported(fig, _srcs(passage))
    assert sup.supported, (fig.surface, sup.reason)
    assert sup.match_kind in ("surface", "normalised")


def test_digit_boundaries_35000_does_not_match_inside_135000():
    """The boundary case §25.5 calls out: a lenient matcher must still not be wrong."""
    (fig,) = nc.extract_figures("35000 units shipped")
    sup = nc.figure_supported(fig, _srcs("the plant shipped 135000 units"))
    assert not sup.supported


def test_untraceable_figure_is_reported_unsupported():
    (fig,) = nc.extract_figures("The segment is worth £47,300")
    sup = nc.figure_supported(fig, _srcs("The segment is large and growing quickly"))
    assert (sup.supported, sup.reason) == (False, "not_in_any_cited_passage")


def test_tolerance_defaults_to_exact_and_can_be_relaxed():
    (fig,) = nc.extract_figures("A market of 1,000 firms")
    passages = _srcs("the register lists 1020 firms")
    assert not nc.figure_supported(fig, passages, tolerance=0.0).supported
    relaxed = nc.figure_supported(fig, passages, tolerance=0.05)
    assert (relaxed.supported, relaxed.match_kind) == (True, "tolerance")


def test_matching_honours_the_600_char_prompt_budget():
    """`s.text[:600]` IS the model's whole input; a figure past it was never seen."""
    (fig,) = nc.extract_figures("The segment is worth £47,300")
    passage = ("x" * 700) + " worth 47300 in total"
    assert not nc.figure_supported(fig, _srcs(passage), truncate=600).supported
    assert nc.figure_supported(fig, _srcs(passage), truncate=0).supported


# --------------------------------------------------------------------------- #
# 3. THE safety invariant: unsure => SUPPORTED, never a fabricated violation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("passages,reason", [
    ([], "no_passage_text"),
    (_srcs(""), "no_passage_text"),
    (_srcs("   ", "\n"), "no_passage_text"),
])
def test_unsure_is_always_reported_as_supported(passages, reason):
    """When the checker cannot see the evidence it has found nothing.

    Reporting `unsupported` here would accuse the rationale of inventing a number
    on the strength of our own missing data — a false violation. The flag is on
    the row so the analysis can subtract these, but the verdict is SUPPORTED.
    """
    (fig,) = nc.extract_figures("The segment is worth £47,300")
    sup = nc.figure_supported(fig, passages)
    assert sup.supported is True
    assert sup.unsure is True
    assert sup.match_kind == "unsure"
    assert sup.reason == reason


def test_unsure_figures_do_not_inflate_the_untraceable_rate():
    report = nc.audit_rationale("Worth £47,300 to 1,761 firms", [])
    assert report.figures_n == 2
    assert report.unsupported_n == 0
    assert report.unsure_n == 2
    assert report.untraceable_rate == 0.0


def test_record_shadow_swallows_every_failure(tmp_path):
    """An observer that can raise has changed a verdict by another name."""
    class Exploding:
        check_name = "pain_reality"

        @property
        def rationale(self):
            raise RuntimeError("boom")

    cfg = _cfg(tmp_path, enabled=True)
    assert nc.record_shadow(cfg, Candidate(title="t"), Exploding()) is None


# --------------------------------------------------------------------------- #
# 4. audit_rationale — per-figure verdicts + the aggregate rate
# --------------------------------------------------------------------------- #

def test_audit_rationale_reports_per_figure_verdicts_and_rate():
    passages = _srcs("the register lists 1761 firms",
                     "average spend was 1.2 million last year")
    report = nc.audit_rationale(
        "1,761 firms spending £1.2m, against an invented £47,300 baseline", passages)
    assert report.figures_n == 3
    assert report.unsupported_n == 1
    assert report.untraceable_rate == pytest.approx(1 / 3)
    bad = [s for s in report.supports if not s.supported]
    assert [s.figure.value for s in bad] == [47300.0]
    ok = [s for s in report.supports if s.supported]
    assert {s.matched_url for s in ok} == {"https://example.test/1",
                                           "https://example.test/2"}


def test_audit_rationale_with_no_figures_is_not_100_percent_untraceable():
    report = nc.audit_rationale("Demand is real and buyers exist.", _srcs("anything"))
    assert (report.figures_n, report.untraceable_rate) == (0, 0.0)


# --------------------------------------------------------------------------- #
# 5. Settings + log-path resolution (never production state)
# --------------------------------------------------------------------------- #

def test_settings_defaults_are_off_and_shadow():
    s = nc.settings_from_config(object())
    assert (s.enabled, s.shadow_mode, s.min_digits, s.ignore_years, s.tolerance,
            s.log_dir) == (False, True, 1, True, 0.0, "")


def test_settings_survive_a_garbage_block():
    class C:
        numeric_citation = {"enabled": "yes", "tolerance": "not-a-number"}
    assert nc.settings_from_config(C()).enabled is False  # falls back to defaults


def test_log_dir_default_follows_prospector_store_dir(tmp_path, monkeypatch):
    """Empty log_dir must resolve under `cfg.store_dir`, which honours the env var.

    This is the LAST tier of three, so it has to clear the one above it: conftest's
    autouse `_isolate_numeric_citation_shadow` sets PROSPECTOR_NUMERIC_CITATION_LOG_DIR
    for every test in the suite, which would otherwise shadow the fallback under test."""
    monkeypatch.delenv("PROSPECTOR_NUMERIC_CITATION_LOG_DIR", raising=False)
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "isolated_store"))
    cfg = load_config()
    setattr(cfg, "numeric_citation", {"enabled": True, "log_dir": ""})
    path = nc.resolve_log_path(cfg, nc.settings_from_config(cfg))
    assert path.parent == tmp_path / "isolated_store" / "numeric_citation_shadow"


def test_log_dir_precedence_is_config_then_env_then_store_dir(tmp_path, monkeypatch):
    """Pins all three tiers, because the middle one exists only to fence the test suite.

    An env var that silently outranked an operator's explicit `numeric_citation.log_dir`
    would send production shadow rows wherever a stray export pointed."""
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("PROSPECTOR_NUMERIC_CITATION_LOG_DIR", str(tmp_path / "env"))
    cfg = load_config()

    # Explicit config wins over the env var.
    setattr(cfg, "numeric_citation", {"enabled": True, "log_dir": str(tmp_path / "cfg")})
    assert nc.resolve_log_path(cfg, nc.settings_from_config(cfg)).parent == tmp_path / "cfg"

    # No config value -> the env var, NOT the store dir.
    setattr(cfg, "numeric_citation", {"enabled": True, "log_dir": ""})
    assert nc.resolve_log_path(cfg, nc.settings_from_config(cfg)).parent == tmp_path / "env"

    # Neither -> under the store dir. A blank env var must not count as "set".
    monkeypatch.setenv("PROSPECTOR_NUMERIC_CITATION_LOG_DIR", "   ")
    assert nc.resolve_log_path(cfg, nc.settings_from_config(cfg)).parent == \
        tmp_path / "store" / "numeric_citation_shadow"


# --------------------------------------------------------------------------- #
# 6. THE invariant: the verdict is identical with shadow on and off
# --------------------------------------------------------------------------- #

CHECK = "pain_reality"

_PASSAGES = [
    Source(source_id="p1", url="https://example.test/register",
           text="The register lists 1761 active firms in the sector."),
    Source(source_id="p2", url="https://example.test/spend",
           text="Average annual spend was 1.2 million across the cohort."),
]

# Two traceable figures (1,761 in p1, £1.2m in p2) and one that appears in NO passage
# (£47,300) — so the shadow log has something to find and the identity is not vacuous.
_RATIONALE = ("The register shows 1,761 firms spending £1.2m a year, and a £47,300 "
              "annual budget makes the pain real.")


class ScriptedOp:
    """Deterministic stand-in for the moat brain. Counts calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str, temperature: float = 0.0,
                      retries: int = 2) -> dict:
        self.calls.append(system[:40])
        return {"verdict": "supported", "rationale": _RATIONALE,
                "citations": ["p1", "p2"], "confidence": 0.9}


class StubSearch:
    """Returns the same two passages for any query. No network."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, q: str, k: int = 5, max_chars: int = 2000) -> list[Source]:
        self.queries.append(q)
        return list(_PASSAGES)


def _run(cfg):
    op, search = ScriptedOp(), StubSearch()
    cfg.retrieval.queries_per_check = 0     # deterministic template queries, no LLM gen
    result = V.run_check(op, search, cfg, Candidate(
        title="Register reconciliation for small firms",
        one_liner="Reconciling register filings for small firms",
        candidate_id="cand123"), CHECK)
    return result, op, search


def test_check_result_identical_with_shadow_on_and_off(tmp_path):
    """Shadow mode must be observationally inert on the RESULT."""
    off_result, off_op, off_search = _run(_cfg(tmp_path, enabled=False))
    on_result, on_op, on_search = _run(_cfg(tmp_path, enabled=True))

    # Byte-identical results (JSON, so 0.9 vs 0.9000000001 cannot slip through).
    assert json.dumps(off_result.to_dict(), sort_keys=True) == \
        json.dumps(on_result.to_dict(), sort_keys=True)
    # Same brain calls, same searches: an observer that acted would have changed one.
    assert off_op.calls == on_op.calls
    assert off_search.queries == on_search.queries

    # Not vacuous: with shadow ON the check DID fire and DID find the invented figure.
    rows = _rows(tmp_path)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["check"] == CHECK
    assert row["candidate_id"] == "cand123"
    assert row["shadow_only"] is True
    assert row["untraceable_rate"] > 0.0
    bad = [f for f in row["figures"] if not f["supported"]]
    assert [f["figure"] for f in bad] == [47300.0]
    good = [f for f in row["figures"] if f["supported"]]
    assert {f["matched_url"] for f in good} == {"https://example.test/register",
                                                "https://example.test/spend"}
    assert {"figure", "surface", "supported", "matched_url"} <= set(row["figures"][0])


def test_shadow_disabled_writes_nothing(tmp_path):
    _run(_cfg(tmp_path, enabled=False))
    assert not (tmp_path / "nc").exists()


def test_shadow_log_lands_in_tmp_path_and_never_in_the_real_store(tmp_path):
    """The canary. It fired for real on 2026-08-07 and must keep being able to.

    Rewritten from `not real_store.exists()` to a before/after byte comparison, because
    the arm is now ON in production (config.yaml:1065): the daemon writing rows there is
    the intended behaviour, so mere existence stopped being evidence of anything. What
    must never happen is a TEST adding bytes to it — which is exactly what the old
    assertion caught when 118 rows stamped `"provider": "mock"` appeared in
    store/numeric_citation_shadow/shadow-2026-08.jsonl.
    """
    real_store = Path(load_config().store_dir) / "numeric_citation_shadow"

    def snapshot():
        if not real_store.exists():
            return {}
        return {p.name: p.stat().st_size for p in real_store.glob("*.jsonl")}

    before = snapshot()
    _run(_cfg(tmp_path, enabled=True))
    assert _rows(tmp_path), "no shadow row written to tmp_path"
    assert snapshot() == before, f"tests polluted production state at {real_store}"


# --------------------------------------------------------------------------- #
# 7. Read side
# --------------------------------------------------------------------------- #

def test_summarise_shadow_log_weights_by_figures(tmp_path):
    _run(_cfg(tmp_path, enabled=True))
    log = next((tmp_path / "nc").glob("*.jsonl"))
    summary = nc.summarise_shadow_log(log)
    assert summary["rows"] == 1
    assert summary["figures"] == 3
    assert summary["unsupported"] == 1
    assert summary["untraceable_rate"] == pytest.approx(1 / 3)
    assert summary["by_check"][CHECK]["untraceable_rate"] == pytest.approx(1 / 3)


def test_summarise_missing_log_is_empty_not_an_error(tmp_path):
    assert nc.summarise_shadow_log(tmp_path / "nope.jsonl")["rows"] == 0


# --------------------------------------------------------------------------- #
# 8. The self-reference split (2026-08-08)
#
# The shipped shadow counted OUR OWN list price as an ungrounded claim. That is not
# noise: `verify._check_question` began stating the actual rung to `payer_solvency`
# on 2026-08-06 (§28.3) so the check would stop inventing one, and a checker with no
# self_ref bucket scores that obedience as a fabrication. An enforcement threshold
# calibrated on the lumped rate would therefore tighten every time we told the model
# MORE truth. Measured on the live log the same day: lumped 30.2%, self_ref 18.9%,
# genuinely untraceable 11.3% — which is what q4c's corpus-wide 10.1% is comparable to.
# --------------------------------------------------------------------------- #

_NO_PRICE = "This passage discusses adoption and mentions no monetary figure whatsoever."


def test_our_own_rung_is_self_ref_not_untraceable():
    r = nc.audit_rationale("Buyers at this size clear a £49 report without a purchase order.",
                           _srcs(_NO_PRICE), self_text="landlord compliance pack 4900 49")
    assert r.unsupported_n == 1, "the rung really is in no retrieved passage"
    assert r.self_ref_n == 1
    assert r.untraceable_n == 0, "our own price is not a fabricated claim about the world"
    assert r.supports[0].reason == "self_reference_own_offer_or_rung"


def test_the_split_is_not_vacuous_without_the_haystack():
    """Same rationale, no self_text: the figure must still count as untraceable.

    Without this the test above would pass on a build that classifies EVERYTHING as
    self-referential.
    """
    r = nc.audit_rationale("Buyers at this size clear a £49 report without a purchase order.",
                           _srcs(_NO_PRICE))
    assert (r.self_ref_n, r.untraceable_n) == (0, 1)


def test_a_world_claim_is_never_absorbed_into_self_reference():
    """A number the candidate never states stays untraceable even with a haystack present."""
    r = nc.audit_rationale("The UK has 5.6 million small businesses.", _srcs(_NO_PRICE),
                           self_text="landlord compliance pack 4900 49")
    assert (r.self_ref_n, r.untraceable_n) == (0, 1)


def test_untraceable_rate_keeps_its_old_lumped_meaning():
    """Rows written before the split carry only `untraceable_rate`; it must not move."""
    r = nc.audit_rationale("A £49 report versus the UK's 5.6 million small businesses.",
                           _srcs(_NO_PRICE), self_text="4900 49")
    assert r.untraceable_rate == pytest.approx(2 / 2), "lumped rate is unsupported/figures"
    d = r.to_dict()
    assert d["untraceable_rate_excl_self"] == pytest.approx(1 / 2)
    assert (d["self_ref_n"], d["untraceable_n"]) == (1, 1)


def test_record_shadow_splits_the_rung_the_pipeline_itself_handed_the_model(tmp_path):
    """End to end through the real config: `listing.pricing.rungs` must reach the checker."""
    from types import SimpleNamespace

    cfg = _cfg(tmp_path, enabled=True)
    rung = int((cfg.listing or {})["pricing"]["rungs"][2])          # 4999 pence == £49.99
    # Charm-priced rungs (D1, 2026-08-09) are never whole pounds, so the spoken form the
    # model would actually write is pounds-and-pence, not `rung // 100`.
    assert rung % 100 != 0, f"this test assumes charm-priced (non-whole-pound) rungs, got {rung}"
    spoken = f"{rung // 100}.{rung % 100:02d}"
    result = SimpleNamespace(
        check_name="payer_solvency",
        rationale=f"A £{spoken} report is inside a discretionary budget.",
        sources=_srcs(_NO_PRICE), verdict="supported", provider="claude_cli")
    row = nc.record_shadow(cfg, Candidate(title="t"), result)

    assert row is not None and row["figures_n"] == 1
    assert row["self_ref_n"] == 1, f"the configured rung {rung} never reached the checker"
    assert row["untraceable_n"] == 0
    assert row["untraceable_rate_excl_self"] == 0.0


def test_summarise_counts_pre_split_rows_separately_instead_of_assuming_zero(tmp_path):
    """A legacy row must not be read as "0 self-references" — that blends two statistics.

    Assuming zero is exactly what made the live lumped 38.0% look like it contradicted
    q4c's 10.1% when the two were never the same measurement.
    """
    log = tmp_path / "mixed.jsonl"
    log.write_text(
        json.dumps({"check": "a", "figures_n": 4, "unsupported_n": 2}) + "\n" +
        json.dumps({"check": "b", "figures_n": 6, "unsupported_n": 3,
                    "self_ref_n": 2, "untraceable_n": 1}) + "\n",
        encoding="utf-8")
    s = nc.summarise_shadow_log(log)

    assert s["figures"] == 10 and s["unsupported"] == 5
    assert s["untraceable_rate"] == pytest.approx(5 / 10), "lumped rate spans every row"
    assert s["split_figures"] == 6 and s["unsplit_figures"] == 4
    assert (s["self_ref"], s["untraceable"]) == (2, 1)
    assert s["untraceable_rate_excl_self"] == pytest.approx(1 / 6), "split rate, split rows only"


def test_summarise_reports_no_split_rate_rather_than_a_fake_zero(tmp_path):
    log = tmp_path / "legacy.jsonl"
    log.write_text(json.dumps({"check": "a", "figures_n": 3, "unsupported_n": 1}) + "\n",
                   encoding="utf-8")
    s = nc.summarise_shadow_log(log)
    assert s["untraceable_rate_excl_self"] is None, "None means unmeasured, 0.0 means clean"
