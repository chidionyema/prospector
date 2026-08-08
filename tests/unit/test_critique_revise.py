"""G8 critique -> revise: the non-lossy invariant, pinned in code not in the prompt.

The defect these tests exist to prevent is specific and has already happened once. On
2026-07-02 the refine wave wiped whole batches because the model returned fewer ideas than
it was given. The code was made non-lossy; the PROMPT still said "Drop the weak/obvious
ones", so the ideas the model judged weakest were the ones that came back UNREFINED. Every
test below asserts on a model that misbehaves in a specific way — drops, reorders, rewords,
duplicates, returns a wrapper, raises — and pins that the output still has one candidate per
input, each one either revised or its own original.
"""
from __future__ import annotations

import json

import pytest

from prospector.critique import _axes_brief, _by_idx, _unwrap, critique_revise
from prospector.models import Candidate


class _Cfg:
    """Minimal stand-in for Config: critique_revise only reads these two attributes."""

    def __init__(self, enabled=True, weights=None):
        self.generation = {"critique_revise": {"enabled": enabled}}
        self.weights = weights if weights is not None else {
            "defensibility": 0.25, "pain_acuity": 0.20, "money_provability": 0.20,
            "automatability": 0.15, "distribution": 0.15, "build_feasibility": 0.05}


class _Gen:
    """Operator stub returning a scripted reply per call, in order."""

    name = "stub"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def complete_json(self, system, user, temperature=0.0, **kw):
        self.calls.append((system, user, temperature))
        if not self._replies:
            raise AssertionError("complete_json called more times than the test scripted")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _cands(n=3):
    return [Candidate(title=f"Idea {i}", one_liner=f"A one liner for idea {i}",
                      hypothesis=f"Hypothesis {i}", who_pays=f"Payer {i}",
                      why_now=f"Why now {i}", tags={"audience": "smb_owner",
                                                    "seed_kind": "signal"},
                      structural_form=f"form_{i}", ambition_tier="smb", market="uk")
            for i in range(n)]


def _crit(idxs):
    return [{"idx": i, "weakest_axis": "defensibility", "critique": f"crit {i}"} for i in idxs]


def _rev(idxs):
    return [{"idx": i, "title": f"Revised {i}", "one_liner": f"Revised one liner {i}",
             "hypothesis": f"Revised hypothesis {i}", "who_pays": f"Revised payer {i}",
             "why_now": f"Revised why now {i}"} for i in idxs]


# ---------------------------------------------------------------------------
# The invariant: length is preserved, whatever the model does
# ---------------------------------------------------------------------------

def test_happy_path_revises_every_candidate():
    gen = _Gen([_crit([0, 1, 2]), _rev([0, 1, 2])])
    out = critique_revise(_cands(3), gen, _Cfg())
    assert len(out) == 3
    assert [c.title for c in out] == ["Revised 0", "Revised 1", "Revised 2"]
    assert len(gen.calls) == 2, "exactly one critique call and one revise call"


def test_a_model_that_drops_an_idea_keeps_that_idea_unchanged():
    """The 2026-07-02 shape. Idea 1 is omitted from the revision array entirely."""
    gen = _Gen([_crit([0, 1, 2]), _rev([0, 2])])
    out = critique_revise(_cands(3), gen, _Cfg())
    assert len(out) == 3
    assert [c.title for c in out] == ["Revised 0", "Idea 1", "Revised 2"]


def test_a_model_that_drops_an_idea_MID_ARRAY_does_not_shift_the_mapping():
    """Position-based matching would hand idea 1 the revision written for idea 2.

    This is the reason `idx` is echoed rather than trusting order: the array
    [rev-for-0, rev-for-2] has rev-for-2 sitting at position 1.
    """
    gen = _Gen([_crit([0, 1, 2]), _rev([0, 2])])
    out = critique_revise(_cands(3), gen, _Cfg())
    assert out[2].title == "Revised 2", "the revision must follow its idx, not its position"
    assert out[1].title == "Idea 1"


def test_a_reworded_title_still_maps_because_matching_is_by_idx_not_title():
    """Rewording the title IS the point of a revision, so title-matching cannot work."""
    revs = [{"idx": 0, "title": "Something completely different",
             "one_liner": "Nothing like the original"}]
    gen = _Gen([_crit([0]), revs])
    out = critique_revise(_cands(1), gen, _Cfg())
    assert len(out) == 1
    assert out[0].title == "Something completely different"


def test_reordered_output_is_reordered_back_by_idx():
    gen = _Gen([_crit([0, 1, 2]), list(reversed(_rev([0, 1, 2])))])
    out = critique_revise(_cands(3), gen, _Cfg())
    assert [c.title for c in out] == ["Revised 0", "Revised 1", "Revised 2"]


def test_a_duplicated_idx_takes_the_first_and_is_deterministic():
    revs = [{"idx": 0, "title": "First copy"}, {"idx": 0, "title": "Second copy"}]
    gen = _Gen([_crit([0, 1]), revs])
    out = critique_revise(_cands(2), gen, _Cfg())
    assert out[0].title == "First copy"
    assert out[1].title == "Idea 1"


def test_an_out_of_range_idx_is_ignored_rather_than_crashing():
    revs = [{"idx": 99, "title": "Ghost"}, {"idx": 0, "title": "Revised 0"}]
    gen = _Gen([_crit([0, 1]), revs])
    out = critique_revise(_cands(2), gen, _Cfg())
    assert [c.title for c in out] == ["Revised 0", "Idea 1"]


def test_a_revision_with_an_empty_title_keeps_the_original():
    gen = _Gen([_crit([0]), [{"idx": 0, "title": "   ", "one_liner": "x"}]])
    out = critique_revise(_cands(1), gen, _Cfg())
    assert out[0].title == "Idea 0"


# ---------------------------------------------------------------------------
# Failure modes: an outage costs sharpening, never candidates
# ---------------------------------------------------------------------------

def test_a_raising_critique_call_returns_the_originals():
    originals = _cands(3)
    out = critique_revise(originals, _Gen([RuntimeError("quota")]), _Cfg())
    assert out is originals


def test_a_raising_revise_call_returns_the_originals():
    originals = _cands(3)
    out = critique_revise(originals, _Gen([_crit([0, 1, 2]), RuntimeError("quota")]), _Cfg())
    assert out is originals


def test_an_empty_critique_response_stops_before_the_revise_call():
    """A revision prompted with no critique is an untargeted reword — the pass we replaced."""
    originals = _cands(2)
    gen = _Gen([[]])
    out = critique_revise(originals, gen, _Cfg())
    assert out is originals
    assert len(gen.calls) == 1, "the second call must not be paid for"


def test_critiques_that_are_all_empty_strings_stop_before_the_revise_call():
    gen = _Gen([[{"idx": 0, "critique": ""}, {"idx": 1, "critique": "  "}]])
    originals = _cands(2)
    out = critique_revise(originals, gen, _Cfg())
    assert out is originals
    assert len(gen.calls) == 1


def test_the_gate_off_is_a_no_op_that_pays_for_nothing():
    originals = _cands(3)
    gen = _Gen([])
    out = critique_revise(originals, gen, _Cfg(enabled=False))
    assert out is originals
    assert gen.calls == []


def test_an_empty_input_is_a_no_op():
    gen = _Gen([])
    assert critique_revise([], gen, _Cfg()) == []
    assert gen.calls == []


# ---------------------------------------------------------------------------
# What a revision may and may not change
# ---------------------------------------------------------------------------

def test_the_categorical_axes_belong_to_the_run_not_to_the_rewrite():
    """A revision moving an idea between lanes would invalidate the quota it was
    generated under and the min_composite bar it is judged by."""
    revs = [{"idx": 0, "title": "Revised 0", "structural_form": "hijacked",
             "ambition_tier": "venture", "market": "us"}]
    gen = _Gen([_crit([0]), revs])
    out = critique_revise(_cands(1), gen, _Cfg())
    assert (out[0].structural_form, out[0].ambition_tier, out[0].market) == \
        ("form_0", "smb", "uk")


def test_tags_merge_with_the_original_as_the_base_so_run_stamps_survive():
    """audience and seed_kind are stamped by the run; a model that echoes tags back
    incompletely must not be able to erase them."""
    revs = [{"idx": 0, "title": "Revised 0", "tags": {"extra": "added"}}]
    gen = _Gen([_crit([0]), revs])
    out = critique_revise(_cands(1), gen, _Cfg())
    assert out[0].tags["audience"] == "smb_owner"
    assert out[0].tags["seed_kind"] == "signal"
    assert out[0].tags["extra"] == "added"


def test_the_revision_records_what_it_acted_on_and_what_it_replaced():
    gen = _Gen([_crit([0]), _rev([0])])
    out = critique_revise(_cands(1), gen, _Cfg())
    hist = out[0].refinement_history
    assert len(hist) == 1
    entry = hist[0]
    assert entry["action"] == "critique_revise"
    assert entry["weakest_axis"] == "defensibility"
    assert entry["critique"] == "crit 0"
    assert entry["before"]["title"] == "Idea 0"


def test_an_unrevised_candidate_gains_no_history_entry():
    gen = _Gen([_crit([0, 1]), _rev([0])])
    out = critique_revise(_cands(2), gen, _Cfg())
    assert len(out[0].refinement_history) == 1
    assert out[1].refinement_history == []


def test_only_critiqued_candidates_are_sent_to_be_revised():
    gen = _Gen([_crit([0, 2]), _rev([0, 2])])
    out = critique_revise(_cands(3), gen, _Cfg())
    _, revise_user, _ = gen.calls[1]
    sent = json.loads(revise_user[revise_user.index("["):revise_user.rindex("]") + 1])
    assert sorted(o["idx"] for o in sent) == [0, 2]
    assert out[1].title == "Idea 1"


# ---------------------------------------------------------------------------
# The prompt cannot drift from the scorer
# ---------------------------------------------------------------------------

def test_the_axes_brief_is_rendered_from_config_weights_heaviest_first():
    brief = _axes_brief(_Cfg())
    names = [ln.split("(")[0].strip("- ").strip() for ln in brief.splitlines()[1:]]
    assert names[0] == "defensibility", "the heaviest axis must lead"
    assert "weight 0.25" in brief
    assert set(names) == {"defensibility", "pain_acuity", "money_provability",
                          "automatability", "distribution", "build_feasibility"}


def test_a_reweighting_changes_the_brief_without_a_code_change():
    """The 2026-06-25 re-weighting moved defensibility .15 -> .25. A hardcoded copy of
    the axes here would have left the critic tuned to the old formula indefinitely."""
    before = _axes_brief(_Cfg(weights={"defensibility": 0.15, "pain_acuity": 0.20}))
    after = _axes_brief(_Cfg(weights={"defensibility": 0.25, "pain_acuity": 0.20}))
    assert before.splitlines()[1].startswith("- pain_acuity")
    assert after.splitlines()[1].startswith("- defensibility")


def test_an_axis_with_no_hint_still_renders_rather_than_vanishing():
    brief = _axes_brief(_Cfg(weights={"a_brand_new_axis": 0.4}))
    assert "a_brand_new_axis" in brief


def test_no_weights_renders_nothing_rather_than_a_dangling_header():
    assert _axes_brief(_Cfg(weights={})) == ""


def test_the_critique_prompt_carries_the_axes_and_the_lane_directive():
    gen = _Gen([_crit([0]), _rev([0])])
    critique_revise(_cands(1), gen, _Cfg(), lane_directive="LANE: side hustle")
    system, user, temp = gen.calls[0]
    assert "defensibility (weight 0.25)" in system
    assert "LANE: side hustle" in system
    assert "{score_axes}" not in system and "{lane_directive}" not in system
    assert "Idea 0" in user
    assert temp == pytest.approx(0.4)


def test_the_revise_prompt_carries_the_critique_and_no_stray_placeholders():
    gen = _Gen([_crit([0]), _rev([0])])
    critique_revise(_cands(1), gen, _Cfg(), lane_directive="LANE: side hustle")
    system, user, temp = gen.calls[1]
    assert "crit 0" in user
    assert "defensibility" in user
    assert "{lane_directive}" not in system and "{style_guide}" not in system
    assert temp == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_unwrap_accepts_a_bare_list_and_every_known_wrapper_key():
    assert _unwrap([{"a": 1}]) == [{"a": 1}]
    for key in ("critiques", "revisions", "opportunities", "candidates", "results", "items"):
        assert _unwrap({key: [{"a": 1}]}) == [{"a": 1}]
    assert _unwrap({"unheard_of_key": [{"a": 1}]}) == [{"a": 1}], "fall back to any list"
    assert _unwrap("not json at all") == []
    assert _unwrap(None) == []


def test_by_idx_falls_back_to_position_only_when_idx_is_unusable():
    items = [{"title": "a"}, {"idx": "not a number", "title": "b"}]
    got = _by_idx(items, 2)
    assert got[0]["title"] == "a"
    assert got[1]["title"] == "b"


def test_by_idx_skips_non_dict_elements():
    assert _by_idx(["a string", {"idx": 1, "t": 1}], 2) == {1: {"idx": 1, "t": 1}}


# ---------------------------------------------------------------------------
# Wiring into the wave: the gate decides WHICH pass runs, never whether one does
# ---------------------------------------------------------------------------

def _wire_cfg(enabled):
    from prospector.config import Config, Thresholds
    return Config(
        generation={
            "candidates_per_signal": 2, "max_per_call": 2, "max_rounds": 1,
            "refinement_enabled": True,
            "structural_forms": ["local_service", "micro_ecommerce"],
            "audience_forms": ["retiree_cohort"],
            "operator_archetype": "", "archetypes": {},
            "critique_revise": {"enabled": enabled},
        },
        thresholds=Thresholds(confidence_floor=0.6, min_composite_to_pass=2.0),
    )


class _WireOp:
    """Records which refinement prompt it was handed, and answers each in kind."""

    model_version = "stub"
    name = "stub"

    def __init__(self):
        self.seen = []

    def embed(self, t):
        return []

    def complete_json(self, system, user, temperature=0.7):
        low = (system + " " + user).lower()
        if "write one specific" in low:                     # critique_system.md
            self.seen.append("critique")
            return [{"idx": 0, "weakest_axis": "defensibility", "critique": "clonable"},
                    {"idx": 1, "weakest_axis": "defensibility", "critique": "clonable"}]
        if "act on the critique" in low:                    # revise_system.md
            self.seen.append("revise")
            return [{"idx": 0, "title": "Sharpened Thin", "one_liner": "now concrete"},
                    {"idx": 1, "title": "Sharpened Substantive", "one_liner": "now concrete"}]
        if "critique and repair" in low:                    # refine_system.md
            self.seen.append("refine")
            return [{"title": "Refined Substantive Idea",
                     "one_liner": "This idea has been refined with more detail and edge",
                     "why_now": "2024 regulatory change plus API", "tags": {},
                     "automatability": 0.8, "weak_monetisation": False}]
        self.seen.append("generate")
        return [
            {"title": "Thin", "one_liner": "x", "why_now": "now", "tags": {},
             "automatability": 0.5, "weak_monetisation": False},
            {"title": "A Substantive Business Idea With Detail",
             "one_liner": "This idea has enough text detail to be worth refining",
             "why_now": "2024 regulatory change", "tags": {},
             "automatability": 0.7, "weak_monetisation": False},
        ]


def test_the_gate_off_leaves_todays_refine_pass_exactly_where_it_was():
    from prospector.generate import generate
    op = _WireOp()
    generate(op, _wire_cfg(False), signal_text="test", k=2)
    assert "refine" in op.seen
    assert "critique" not in op.seen and "revise" not in op.seen


def test_the_gate_on_replaces_the_refine_pass_rather_than_stacking_on_it():
    """Stacking would re-introduce the anti-targeting G8 exists to remove: refine's prompt
    leaves the ideas it judges weakest unrefined, which is exactly the set a critique pass
    is for."""
    from prospector.generate import generate
    op = _WireOp()
    result = generate(op, _wire_cfg(True), signal_text="test", k=2)
    assert "critique" in op.seen and "revise" in op.seen
    assert "refine" not in op.seen
    # The thin candidate is INCLUDED, not skipped: "too short to refine" was a heuristic for
    # a pass that could drop things, and a two-word candidate is the clearest case for a
    # critique. It survives either way — nothing is killed at generation time.
    assert any("Thin" in c.title for c in result), \
        f"the thin candidate must survive, got {[c.title for c in result]}"


def _wire_cfg_no_refinement(enabled):
    cfg = _wire_cfg(enabled)
    cfg.generation["refinement_enabled"] = False
    return cfg


def test_g8_still_fires_when_the_old_refine_pass_is_switched_off():
    """The shipped `config.yaml:730` sets `refinement_enabled: false`.

    G8's gate was originally placed AFTER that early return, which made critique->revise
    unreachable on the only configuration that actually runs — a dead lever that every
    unit test missed because they all set `refinement_enabled: True`. The two flags name
    different mechanisms: one turns off the lossy refine pass, the other opts in to
    critique->revise. Found by `tools/experiments/g_generation_ab.py --fixture`, which
    measured the G8 arm costing exactly what baseline cost.
    """
    from prospector.generate import generate
    op = _WireOp()
    generate(op, _wire_cfg_no_refinement(True), signal_text="test", k=2)
    assert "critique" in op.seen and "revise" in op.seen, \
        f"G8 must not inherit refinement_enabled; saw {op.seen}"
    assert "refine" not in op.seen


def test_switching_refinement_off_with_g8_off_still_pays_for_neither_pass():
    """The converse, so the fix cannot be read as "G8 quietly re-enabled refinement"."""
    from prospector.generate import generate
    op = _WireOp()
    generate(op, _wire_cfg_no_refinement(False), signal_text="test", k=2)
    assert op.seen == [] or "refine" not in op.seen, \
        f"refinement_enabled: false must still buy nothing, saw {op.seen}"
    assert "critique" not in op.seen and "revise" not in op.seen
