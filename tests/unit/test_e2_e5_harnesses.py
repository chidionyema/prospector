"""E2/E5 setup harnesses: the properties that would otherwise fail silently.

Both are offline and read-only, so the risk is not that they crash — it is that they produce a
confident number that is an artifact of the harness. Each test here pins one way that already
happened during development:

  * E2 read `cfg.generation.audience_forms` with getattr on what is actually a DICT, got None,
    and printed "audience_forms in config: 0" while flagging all twelve observed personas
    "(not in config)". A reader bug rendering as a data finding.
  * E5 normalised structural_form entropy by the CONFIGURED domain (8) while the corpus holds
    29 distinct values, and printed H_norm = 1.365 — a normalised entropy above 1.
  * E5 constructs the treatment arm by enabling the sampler. If that ever reaches the real
    config object or config.yaml, an experiment harness has silently switched on a production
    generation behaviour.

Zero LLM, zero network.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXP = REPO / "tools" / "experiments"


def _load(stem: str):
    spec = importlib.util.spec_from_file_location(f"_{stem}_under_test", EXP / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def e2(monkeypatch):
    monkeypatch.syspath_prepend(str(EXP))
    return _load("e2_persona_grounding")


@pytest.fixture
def e5(monkeypatch):
    monkeypatch.syspath_prepend(str(EXP))
    return _load("e5_coverage_sampler_entropy")


# --------------------------------------------------------------------------- E2

def test_e2_reads_the_persona_vocabulary_from_a_dict_config(e2):
    """`cfg.generation` is a plain dict. getattr on it returns None and reads as 'not in config'."""
    vocab = e2._config_personas()
    assert len(vocab) >= 8, vocab
    assert "smb_owner" in vocab and "startup_operator" in vocab


def test_e2_refuses_an_empty_vocabulary_rather_than_flagging_every_persona(e2, monkeypatch):
    class _Cfg:
        generation = {}
    monkeypatch.setattr("prospector.config.load_config", lambda *a, **k: _Cfg())
    with pytest.raises(SystemExit) as ei:
        e2._config_personas()
    assert "audience_forms is empty or unreadable" in str(ei.value)


def test_e2_separability_needs_disjoint_intervals(e2):
    wide = e2._wilson_row(1, 5)      # 20%, enormous interval
    narrow = e2._wilson_row(20, 100)  # 20%, tight
    assert not e2._separable(wide, narrow)
    assert e2._separable(e2._wilson_row(90, 100), e2._wilson_row(2, 100))
    # A zero denominator is never separable from anything — that is the E1 lesson, here.
    assert not e2._separable(e2._wilson_row(0, 0), e2._wilson_row(90, 100))


def test_e2_sample_size_grows_as_the_effect_shrinks(e2):
    near = e2._n_per_arm(0.065, 0.047)   # the observed class contrast
    far = e2._n_per_arm(0.30, 0.05)
    assert near > far > 0
    assert e2._n_per_arm(0.05, 0.05) is None, "no effect => no finite sample size"


# --------------------------------------------------------------------------- E5

def test_e5_normalised_entropy_never_exceeds_one(e5):
    """The H_norm=1.365 defect: the domain must cover what was observed."""
    counts = {f"v{i}": 10 for i in range(29)}
    assert e5._normalised(counts, 8) > 1.0, "the buggy normalisation, kept as the contrast"
    assert e5._normalised(counts, max(8, len(counts))) == pytest.approx(1.0, abs=1e-9)
    assert e5._normalised({"a": 100, "b": 1}, 13) < 0.3


def test_e5_batches_for_is_the_inverse_of_min_detectable(e5):
    sd = 0.161
    n = e5._batches_for(sd, 0.10)
    assert e5._min_detectable(sd, n) <= 0.10
    assert e5._min_detectable(sd, n - 1) > 0.10, "off by one: n is not the SMALLEST sufficient"
    assert e5._batches_for(0.0, 0.1) is None


def test_e5_never_writes_the_live_sampler_flag(e5):
    """A harness that flips coverage_sampler.enabled has changed production generation."""
    from prospector.config import load_config

    before_flag = (load_config().coverage_sampler or {}).get("enabled")
    before_yaml = (REPO / "config.yaml").read_bytes()

    out = e5.run(["--trials", "50"])

    after = load_config().coverage_sampler or {}
    assert after.get("enabled") == before_flag is False
    assert (REPO / "config.yaml").read_bytes() == before_yaml, "config.yaml was rewritten"
    assert out["headline"]["enabled_on_disk"] is False
    # The control arm is what runs today: with the flag off, plan_cells must stay inert.
    assert out["headline"]["control_cells"] == 0


def test_e5_reports_whether_the_treatment_arm_engages(e5):
    """The inert-arm question is answered before any batch is scheduled, not after three."""
    out = e5.run(["--trials", "50"])
    h = out["headline"]
    assert isinstance(h["treatment_engages"], bool)
    if h["treatment_engages"]:
        assert h["treatment_cells"] > 0
        cells = out["engagement"]["cells"]
        assert cells and all(isinstance(c, dict) and c for c in cells)
    else:
        # An inert arm must arrive with a diagnosis, never as a bare False.
        assert out["engagement"]["failure"] or out["coverage_report"]


def test_e5_design_verdict_is_not_runnable_when_the_arm_is_inert(e5, monkeypatch):
    import prospector.coverage as C
    monkeypatch.setattr(C, "plan_cells", lambda *a, **k: [])
    out = e5.run(["--trials", "50"])
    assert out["headline"]["treatment_engages"] is False
    assert out["headline"]["design_runnable"] is False


def test_e5_entropy_of_a_degenerate_axis_is_zero(e5):
    assert e5._shannon({"only": 500}) == 0.0
    assert e5._shannon({}) == 0.0
    assert e5._shannon({"a": 1, "b": 1}) == pytest.approx(math.log2(2))
