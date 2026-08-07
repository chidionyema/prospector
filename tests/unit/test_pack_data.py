"""Unit tests for `prospector.pack_data` — register items F1–F4.

Each test is a receipt for one claim in the register:

* F1 — the six-axis scorecard, the Python financial model and the price comparables all
  reach the buyer as JSON and CSV, and every comparable row carries its URL and the literal
  cited passage (source-or-die on a shipped artifact).
* F2 — the radar is well-formed SVG with six labelled axes and their score values, drawn
  without matplotlib.
* F3 — the XLSX outputs are LIVE ``=``-formulas over the input cells, not baked values.
* F4 — the PDF path returns ``None`` instead of raising when Chrome is missing or fails.

Plus the two properties the whole module is supposed to have: byte-for-byte determinism,
and being inert unless ``pack_data.enabled`` is switched on.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from prospector import pack_data
from prospector.models import (
    Candidate,
    CheckResult,
    Decision,
    Dossier,
    PriceAnchor,
    ScoreResult,
    Source,
    Verdict,
)

# The config block under test, built inline: config.py / config.yaml are owned elsewhere and
# `settings()` is required to read through getattr with defaults.
WEIGHTS = {
    "pain_acuity": 0.20,
    "money_provability": 0.20,
    "automatability": 0.15,
    "distribution": 0.15,
    "defensibility": 0.25,
    "build_feasibility": 0.05,
}

ASSUMPTIONS = {
    "monthly_price": 49,
    "target_customers_month_1": 20,
    "target_customers_month_12": 200,
    "estimated_cac_gbp": 300,
    "estimated_clv_gbp": 1200,
    "estimated_monthly_churn_pct": 5,
    "cost_of_goods_pct": 20,
    "overhead_month_1_gbp": 2000,
    "sales_cycle_months": 1,
    "payback_months": 6,
    "assumptions": ["TAM of 100k firms is an assumption — unverified"],
    "weaknesses": ["Churn is a guess"],
}


def _cfg(**pack_data_block):
    return SimpleNamespace(weights=dict(WEIGHTS), pack_data=dict(pack_data_block))


@pytest.fixture
def source() -> Source:
    return Source(
        source_id="src-1",
        url="https://example.com/pricing",
        text="Teams pay £49 per month for the Pro plan, billed annually.",
    )


@pytest.fixture
def dossier(source) -> Dossier:
    cand = Candidate(title="Test Biz", one_liner="A test biz")
    cand.tags["price_comparables"] = {
        "anchors": [
            {"amount": 49.0, "currency": "GBP", "cadence": "monthly",
             "what": "Pro plan seat", "source_id": "src-1",
             "url": "https://example.com/pricing", "amount_pence_gbp": 4900},
            # No URL: evidence we cannot re-cite, so it must be quarantined, not rendered.
            {"amount": 99.0, "currency": "USD", "cadence": "monthly",
             "what": "Rival plan", "source_id": "missing", "url": ""},
        ]
    }
    check = CheckResult(check_name="pain_reality", verdict=Verdict.SUPPORTED,
                        confidence=0.9, rationale="Verified.", sources=[source])
    score = ScoreResult(
        scores={"pain_acuity": 4, "money_provability": 3, "automatability": 5,
                "distribution": 2, "defensibility": 4, "build_feasibility": 5},
        justification={ax: f"because {ax}" for ax in WEIGHTS},
        composite=3.65,
    )
    return Dossier(candidate=cand, decision=Decision.PASS, checks=[check], score=score,
                   created_at="2026-08-07T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_settings_default_off_on_a_config_without_the_block():
    """A Config that predates the `pack_data` block must read as disabled, not crash."""
    conf = pack_data.settings(SimpleNamespace())
    assert conf["enabled"] is False
    assert conf["formats"] == pack_data.DEFAULT_FORMATS
    assert conf["chrome_path"] == pack_data.DEFAULT_CHROME_PATH


def test_settings_reads_the_block():
    conf = pack_data.settings(_cfg(enabled=True, formats=["json"], chrome_path="/bin/false"))
    assert conf["enabled"] is True
    assert conf["formats"] == ("json",)
    assert conf["chrome_path"] == "/bin/false"


# ---------------------------------------------------------------------------
# F1 — scorecard
# ---------------------------------------------------------------------------

def test_scorecard_carries_score_weight_and_weighted_contribution(dossier):
    card = pack_data.scorecard(dossier.score, WEIGHTS)
    assert card["score_available"] is True
    assert [r["axis"] for r in card["axes"]] == list(pack_data.SCORE_AXES)
    pain = next(r for r in card["axes"] if r["axis"] == "pain_acuity")
    assert (pain["score"], pain["weight"], pain["weighted_contribution"]) == (4.0, 0.2, 0.8)
    # 4*.20 + 3*.20 + 5*.15 + 2*.15 + 4*.25 + 5*.05 = 3.70, recomputed from the axes here
    # rather than trusted: the fixture's ScoreResult STATES 3.65, and the artifact reports
    # both so a buyer can see when a stored composite disagrees with its own axes.
    assert card["composite_recomputed"] == 3.7
    assert card["composite"] == 3.65
    assert card["composite_max"] == 5.0


def test_scorecard_without_a_score_reports_unavailable_not_zeros():
    """A KILL is never scored. Rendering six zeros would be a dossier-shaped lie."""
    card = pack_data.scorecard(None, WEIGHTS)
    assert card["score_available"] is False
    assert card["axes"] == []


def test_scorecard_csv_has_a_row_per_axis_plus_a_composite(dossier):
    text = pack_data.scorecard_csv(pack_data.scorecard(dossier.score, WEIGHTS))
    lines = text.strip().split("\n")
    assert lines[0] == "axis,label,score,max_score,weight,weighted_contribution"
    assert len(lines) == 1 + len(pack_data.SCORE_AXES) + 1
    assert lines[-1] == "composite,Composite,3.65,5.0,,3.7"


# ---------------------------------------------------------------------------
# F1 — financial model
# ---------------------------------------------------------------------------

def test_financial_model_computes_the_outputs_in_python():
    model = pack_data.financial_model(ASSUMPTIONS)
    out = model["outputs"]
    assert out["revenue_month_1"] == 49 * 20            # 980
    assert out["revenue_month_12"] == 49 * 200          # 9800
    assert out["growth_multiple_m1_m12"] == 10.0
    assert out["gross_margin_pct"] == 80.0
    assert out["gross_margin_per_customer"] == 39.2     # 49 * 80 / 100
    assert out["month_1_cogs"] == 196.0                 # 980 * 20%
    assert out["month_1_gross_profit"] == 784.0
    assert out["month_1_net"] == -1216.0                # 784 - 2000
    assert out["customer_lifetime_value"] == 1200.0     # stated wins
    assert model["derived"]["customer_lifetime_value"] == 980.0   # 49 / 5%
    assert out["ltv_cac_ratio"] == 4.0                  # 1200 / 300
    assert model["assumptions"] == ASSUMPTIONS["assumptions"]


def test_financial_model_is_none_safe_on_a_partial_model():
    model = pack_data.financial_model({"monthly_price": 49})
    assert model["outputs"]["revenue_month_1"] is None
    assert model["outputs"]["gross_margin_pct"] is None
    assert model["inputs"]["monthly_price"] == 49.0


def test_financial_csv_labels_inputs_and_outputs():
    text = pack_data.financial_csv(pack_data.financial_model(ASSUMPTIONS))
    assert text.startswith("section,key,label,value\n")
    assert "input,monthly_price,Monthly price,49.0" in text
    assert "output,revenue_month_1,\"Revenue, month 1\",980.0" in text
    assert "weakness,,,Churn is a guess" in text


# ---------------------------------------------------------------------------
# F1 — comparables (the ones currently fetched and discarded)
# ---------------------------------------------------------------------------

def test_comparables_carry_url_and_the_literal_cited_snippet(dossier):
    from prospector.price_comparables import anchors_from_tags
    payload = pack_data.comparables(anchors_from_tags(dossier.candidate),
                                    dossier.all_sources)
    assert payload["count"] == 1
    row = payload["anchors"][0]
    assert row["amount"] == 49.0
    assert row["url"] == "https://example.com/pricing"
    # The snippet must be the passage itself, verbatim — not a paraphrase.
    assert row["cited_snippet"] == (
        "Teams pay £49 per month for the Pro plan, billed annually.")


def test_comparables_quarantine_an_anchor_with_no_url(dossier):
    from prospector.price_comparables import anchors_from_tags
    payload = pack_data.comparables(anchors_from_tags(dossier.candidate),
                                    dossier.all_sources)
    assert [u["amount"] for u in payload["unsourced"]] == [99.0]
    assert payload["unsourced"][0]["reason"] == "no source URL on the anchor"
    assert 99.0 not in [r["amount"] for r in payload["anchors"]]


def test_comparables_snippet_window_is_config_driven():
    anchor = PriceAnchor(amount=1.0, currency="GBP", cadence="monthly", what="x",
                         source_id="s", url="https://e.com")
    src = Source(source_id="s", url="https://e.com", text="A" * 900)
    payload = pack_data.comparables([anchor], [src], snippet_chars=10)
    assert payload["anchors"][0]["cited_snippet"] == "A" * 10


def test_comparables_csv_header_includes_the_proof_columns(dossier):
    from prospector.price_comparables import anchors_from_tags
    text = pack_data.comparables_csv(
        pack_data.comparables(anchors_from_tags(dossier.candidate), dossier.all_sources))
    assert text.split("\n")[0].endswith("source_id,url,cited_snippet")


# ---------------------------------------------------------------------------
# F2 — radar SVG
# ---------------------------------------------------------------------------

def test_radar_svg_is_well_formed_and_labels_every_axis(dossier):
    card = pack_data.scorecard(dossier.score, WEIGHTS)
    svg = pack_data.radar_svg(card, title="Test Biz")
    root = ET.fromstring(svg)                      # parses => well-formed XML
    assert root.tag.endswith("svg")
    texts = [(t.text or "") for t in root.iter() if t.tag.endswith("text")]
    for axis in pack_data.SCORE_AXES:
        assert axis.replace("_", " ").title() in texts
    assert any("4.0/5" in t for t in texts)        # a score value is drawn
    assert any("Composite 3.65" in t for t in texts)
    # Readable on white: an explicit white ground, not an inherited one.
    assert 'fill="#ffffff"' in svg
    # F2's constraint: no plotting dependency.
    assert "matplotlib" not in svg


def test_radar_svg_without_a_score_says_so_instead_of_drawing_a_zero_hexagon():
    svg = pack_data.radar_svg(pack_data.scorecard(None, WEIGHTS))
    ET.fromstring(svg)
    assert "Not scored" in svg
    assert "<polygon" not in svg


def test_radar_geometry_puts_the_first_axis_at_twelve_oclock(dossier):
    """The polar maths is the whole implementation, so pin one vertex exactly."""
    card = pack_data.scorecard(dossier.score, WEIGHTS)
    conf = pack_data.DEFAULT_RADAR
    size, margin = float(conf["size"]), float(conf["margin"])
    centre = size / 2.0
    radius = size / 2.0 - margin
    expected_y = centre - radius * (4.0 / 5.0)     # pain_acuity = 4 of 5, straight up
    svg = pack_data.radar_svg(card)
    polygon = svg.split('fill-opacity="0.22"')[0].rsplit('<polygon points="', 1)[1]
    first = polygon.split(" ")[0].split('"')[0]
    x, y = (float(v) for v in first.split(","))
    assert x == pytest.approx(centre, abs=0.01)
    assert y == pytest.approx(expected_y, abs=0.01)


# ---------------------------------------------------------------------------
# F3 — XLSX with live formulas
# ---------------------------------------------------------------------------

def test_financial_xlsx_writes_live_formulas(tmp_path):
    openpyxl = pytest.importorskip("openpyxl",
                                   reason="openpyxl not installed in this venv yet")
    out = str(tmp_path / "financial_model.xlsx")
    assert pack_data.financial_xlsx(pack_data.financial_model(ASSUMPTIONS), out,
                                    title="Test Biz") == out

    wb = openpyxl.load_workbook(out)               # formulas, not cached values
    ws = wb.active
    cells = {(c.row, c.column): c.value for row in ws.iter_rows() for c in row}
    labels = {v: r for (r, col), v in cells.items() if col == 1 and isinstance(v, str)}

    # Inputs are literal numbers the buyer can edit.
    assert cells[(labels["Monthly price"], 2)] == 49.0
    assert cells[(labels["Customers, month 1"], 2)] == 20.0

    # Outputs are '=' formulas that REFERENCE those input cells, not baked numbers.
    rev1 = cells[(labels["Revenue, month 1"], 2)]
    assert isinstance(rev1, str) and rev1.startswith("=")
    price_ref = f"B{labels['Monthly price']}"
    cust_ref = f"B{labels['Customers, month 1']}"
    assert rev1 == f"={price_ref}*{cust_ref}"
    assert cells[(labels["Gross margin"], 2)] == f"=100-B{labels['Cost of goods (COGS)']}"
    for label in ("Revenue, month 12", "Gross margin per customer / month",
                  "Payback period", "LTV:CAC ratio", "Month 1 net"):
        assert str(cells[(labels[label], 2)]).startswith("=")


def test_financial_xlsx_returns_none_when_openpyxl_is_missing(tmp_path, monkeypatch, caplog):
    """Not-installed is a logged gap, never an exception on the publish path."""
    monkeypatch.setattr(pack_data, "_openpyxl", None)
    assert pack_data.financial_xlsx(pack_data.financial_model(ASSUMPTIONS),
                                    str(tmp_path / "x.xlsx")) is None


def test_financial_xlsx_returns_none_on_an_unwritable_path(tmp_path):
    pytest.importorskip("openpyxl", reason="openpyxl not installed in this venv yet")
    assert pack_data.financial_xlsx(pack_data.financial_model(ASSUMPTIONS),
                                    str(tmp_path / "no-such-dir" / "x.xlsx")) is None


# ---------------------------------------------------------------------------
# F4 — PDF
# ---------------------------------------------------------------------------

def test_render_pdf_returns_none_when_chrome_is_absent(tmp_path):
    assert pack_data.render_pdf("<html><body>hi</body></html>",
                                str(tmp_path / "pack.pdf"),
                                chrome_path="/nope/Google Chrome") is None


def test_render_pdf_returns_none_when_chrome_fails(tmp_path):
    """/bin/false exists and exits 1: the failure path must be a return, not a raise."""
    assert pack_data.render_pdf("<html><body>hi</body></html>",
                                str(tmp_path / "pack.pdf"),
                                chrome_path="/bin/false") is None


def test_render_pdf_returns_none_on_empty_html(tmp_path):
    assert pack_data.render_pdf("", str(tmp_path / "pack.pdf")) is None


@pytest.mark.skipif(not os.path.exists(pack_data.DEFAULT_CHROME_PATH),
                    reason="Google Chrome is not installed at the default path")
def test_render_pdf_prints_the_pack_html(tmp_path):
    """Chrome writes the PDF and then HANGS, so this also proves we wait on the file.

    Measured Chrome 151.0.7922.72 / macOS 14.5: `timeout 45 <chrome> --headless
    --print-to-pdf` returns rc=124 with "8205 bytes written to file" already logged. The
    60s budget here would not be enough if render_pdf waited for the process to exit.
    """
    out = str(tmp_path / "pack.pdf")
    assert pack_data.render_pdf(
        "<html><head><title>Pack</title></head><body><h1>Pack</h1></body></html>",
        out, timeout_s=60) == out
    with open(out, "rb") as fh:
        assert fh.read(5) == b"%PDF-"


# ---------------------------------------------------------------------------
# Assembly, determinism and the default-off fence
# ---------------------------------------------------------------------------

def test_build_text_artifacts_emits_the_seven_files(dossier):
    out = pack_data.build_text_artifacts(dossier, _cfg(enabled=True),
                                         financial_assumptions=ASSUMPTIONS)
    assert sorted(out) == [
        "comparables.csv", "comparables.json", "financial.csv", "financial.json",
        "scorecard.csv", "scorecard.json", "scorecard_radar.svg",
    ]
    assert '"composite": 3.65' in out["scorecard.json"]
    assert "https://example.com/pricing" in out["comparables.json"]


def test_formats_config_selects_which_files_are_emitted(dossier):
    out = pack_data.build_text_artifacts(dossier, _cfg(enabled=True, formats=["json"]),
                                         financial_assumptions=ASSUMPTIONS)
    assert sorted(out) == ["comparables.json", "financial.json", "scorecard.json"]


def test_artifacts_are_byte_identical_across_runs(dossier):
    """Same dossier in, byte-identical artifacts out — no clock, no set iteration."""
    cfg = _cfg(enabled=True)
    first = pack_data.build_text_artifacts(dossier, cfg, financial_assumptions=ASSUMPTIONS)
    second = pack_data.build_text_artifacts(dossier, cfg, financial_assumptions=ASSUMPTIONS)
    assert first == second
    for name, text in first.items():
        assert text.encode() == second[name].encode(), name


def test_artifacts_for_bundle_is_inert_by_default(dossier):
    assert pack_data.artifacts_for_bundle(dossier, _cfg()) == {}
    assert pack_data.artifacts_for_bundle(dossier, SimpleNamespace()) == {}
    assert pack_data.artifacts_for_bundle(dossier, None) == {}


def test_artifacts_for_bundle_emits_when_enabled(dossier):
    out = pack_data.artifacts_for_bundle(dossier, _cfg(enabled=True),
                                         financial_assumptions=ASSUMPTIONS)
    assert "scorecard_radar.svg" in out


def test_write_artifacts_writes_files_to_disk(dossier, tmp_path):
    written = pack_data.write_artifacts(dossier, _cfg(enabled=True), str(tmp_path),
                                        financial_assumptions=ASSUMPTIONS)
    assert len(written) == 7
    for name, path in written.items():
        assert os.path.getsize(path) > 0, name


def test_write_artifacts_skips_binaries_that_cannot_be_produced(dossier, tmp_path):
    """A missing xlsx/pdf is an absent key, never an exception."""
    written = pack_data.write_artifacts(
        dossier,
        _cfg(enabled=True, formats=["json", "xlsx", "pdf"], chrome_path="/bin/false"),
        str(tmp_path), financial_assumptions=ASSUMPTIONS, pack_html="<html></html>")
    assert pack_data.PACK_PDF not in written
    assert "scorecard.json" in written


# ---------------------------------------------------------------------------
# The artifacts.py wire-in
# ---------------------------------------------------------------------------

def test_generate_artifacts_is_unchanged_when_pack_data_is_off():
    from prospector.artifacts import generate_artifacts
    from prospector.operator import MockOperator

    op = MockOperator(router=lambda system, user: {"type": "build_spec", "content": "x" * 50})
    out = generate_artifacts(op, Candidate(title="T", one_liner="o"), [], cfg=_cfg())
    assert set(out) == {"build_spec", "gtm_plan", "ops_plan", "financial_model"}


def test_generate_artifacts_adds_the_data_files_when_pack_data_is_on():
    from prospector.artifacts import generate_artifacts
    from prospector.operator import MockOperator

    def router(system: str, user: str):
        if "financial_model" in user:
            return dict(ASSUMPTIONS)
        return {"type": "build_spec", "content": "x" * 50}

    op = MockOperator(router=router)
    out = generate_artifacts(op, Candidate(title="T", one_liner="o"), [],
                             cfg=_cfg(enabled=True))
    assert "scorecard.json" in out and "financial.json" in out
    # The assumptions captured from the LLM reach the data file (they used to be discarded).
    assert '"revenue_month_1": 980.0' in out["financial.json"]


def test_generate_artifacts_without_a_score_reports_unavailable():
    """The pre-fix behaviour, pinned: no score in => an honest `score_available: false`.

    This is the state every published pack shipped in before §27.2 item 4 — the publish path
    calls generate_artifacts BEFORE build_dossier, so there was never a score to render.
    """
    import json as _json

    from prospector.artifacts import generate_artifacts
    from prospector.operator import MockOperator

    op = MockOperator(router=lambda system, user: {"type": "build_spec", "content": "x" * 50})
    out = generate_artifacts(op, Candidate(title="T", one_liner="o"), [],
                             cfg=_cfg(enabled=True))
    card = _json.loads(out["scorecard.json"])
    assert card["score_available"] is False
    assert card["axes"] == []


def test_generate_artifacts_score_kwarg_populates_the_scorecard():
    """§27.2 item 4: passing `score` puts the six axes into the bundle's scorecard.

    Without this the buyer's scorecard.json is a `score_available: false` placeholder even
    on a PASS that was fully scored.
    """
    import json as _json

    from prospector.artifacts import generate_artifacts
    from prospector.operator import MockOperator

    score = ScoreResult(
        scores={"pain_acuity": 4, "money_provability": 3, "automatability": 5,
                "distribution": 2, "defensibility": 4, "build_feasibility": 5},
        justification={ax: f"because {ax}" for ax in WEIGHTS},
        composite=3.65,
    )
    op = MockOperator(router=lambda system, user: {"type": "build_spec", "content": "x" * 50})
    out = generate_artifacts(op, Candidate(title="T", one_liner="o"), [],
                             cfg=_cfg(enabled=True), score=score)
    card = _json.loads(out["scorecard.json"])
    assert card["score_available"] is True
    assert {a["axis"] for a in card["axes"]} == set(WEIGHTS)
    assert card["composite"] == 3.65
