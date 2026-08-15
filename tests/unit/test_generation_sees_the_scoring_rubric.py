"""Generation must be shown the rubric it will be scored against.

MEASURED, 331 scored dossiers since 2026-08-01 (`store/dossiers/*.json`): `build_feasibility`
is the HIGHEST axis at 3.14/5 while `money_provability` is 1.65 and `defensibility` 1.69 —
45% of the composite weight between them — and 270 of the 331 died on `min_composite`. The
ideas were buildable and unfundable.

The cause was that `prompts/score.md` names all six axes and `prompts/generate.md` names ZERO;
`prompts/generate_system.md` never says "money_provability" or "willing to pay" in 161 lines.
Generation was graded on a rubric it had never seen.

Three ways the fix could be INERT, all pinned here:

1. The directive could name the axes but not the two that actually bind.
2. It could hardcode the axes, so the 2026-06-25-style re-weighting (defensibility .15 -> .25)
   would steer the scorer and leave generation tuned to the old formula, silently. It must be
   a pure function of `cfg.weights`.
3. It could break the two call sites that render "generate" without new kwargs
   (`run.py`, `tests/unit/test_moat_discipline.py`). Hence the append-in-Python shape, and
   hence the empty-weights case must return "" so those paths stay byte-identical.
"""
from __future__ import annotations

from types import SimpleNamespace

from prospector.config import load_config
from prospector.generate import _scoring_directive


def test_it_names_the_two_axes_the_corpus_actually_dies_on():
    out = _scoring_directive(load_config())
    assert "money_provability" in out
    assert "defensibility" in out
    # Naming them is not enough: the whole finding is that ideas are BUILDABLE and unfundable,
    # so the directive has to demand an existing budget line, not a hypothetical willingness.
    assert "ALREADY pays from today" in out
    assert "ACCUMULATES" in out


def test_it_is_rendered_from_cfg_weights_not_hardcoded():
    """A re-weighting must change what generation optimises for on the same day it changes
    what the scorer measures."""
    heavy_money = _scoring_directive(
        SimpleNamespace(weights={"money_provability": 0.9, "defensibility": 0.1}))
    heavy_def = _scoring_directive(
        SimpleNamespace(weights={"money_provability": 0.1, "defensibility": 0.9}))
    assert heavy_money.index("money_provability") < heavy_money.index("defensibility")
    assert heavy_def.index("defensibility") < heavy_def.index("money_provability")
    assert "weight 0.90" in heavy_money and "weight 0.90" in heavy_def


def test_an_axis_added_to_config_reaches_generation_without_a_code_change():
    """A weight with no hint still renders by name — a new axis must not silently vanish from
    the brief the way it vanished from this one."""
    out = _scoring_directive(SimpleNamespace(weights={"regulatory_tailwind": 0.5}))
    assert "regulatory_tailwind" in out


def test_no_weights_means_no_suffix_at_all():
    """The directive is appended to an already-rendered prompt. Returning anything here on a
    weightless Config (test doubles, `run.py`'s bare render) would change prompts that this
    change is not entitled to touch."""
    assert _scoring_directive(SimpleNamespace(weights={})) == ""
    assert _scoring_directive(SimpleNamespace()) == ""


def test_the_directive_is_not_already_in_the_static_prompt_files():
    """If it were, the append would be a duplicate rather than the fix — and the measurement
    above (generate.md names zero axes) would be stale."""
    from prospector.prompts import PROMPTS_DIR

    for name in ("generate.md", "generate_system.md"):
        text = (PROMPTS_DIR / name).read_text()
        assert "money_provability" not in text, (
            f"{name} now names the axis statically; the config-rendered directive is the "
            "single source and a second copy can drift from cfg.weights")
