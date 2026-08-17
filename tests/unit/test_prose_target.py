"""The measured human target, and the four fences that keep it safe in production.

WHAT THIS REPLACED. `register_lint` carried two numbers nobody had measured: a sentence may
run to 25 words, and it may carry two commas. Both came from `prompts/style/voice.md`. The
measurement in `docs/PROSE_CORPUS_PROGRAM.md` compared 766 of our documents against 270
Financial Ombudsman final decisions and found the 25-word rule STRICTER than professional
English in the same genre — a human breaks it in 31% of sentences, the human 95th percentile
is 52%, and our rate is 52%. The rule was flagging normal writing.

The fences these tests pin:
  1. the target is a committed file, and the shipped one loads;
  2. lint time does no network I/O;
  3. a target measured with a different tokeniser is REFUSED, not read;
  4. an unarmed measure can never produce a finding;
  5. one measuring implementation, so the target-builder and the linter cannot drift;
  6. an unreadable target is SAID OUT LOUD, because a check that reports nothing looks
     exactly like a pack that passed.
"""
from __future__ import annotations

import json

import pytest

from prospector import prose_target
from prospector.prose_measure import TOKENISER_VERSION, document_measures
from prospector.register_lint import check_register, register_metrics

# Deliberately unlike the human corpus on every armed measure: compound stacking, three
# comma-clauses a sentence, a semicolon, and not one hedge.
STACKED = ("The front-door key-safe re-siting programme, which the panel considered at "
           "length, was, in the circumstances, mis-handled; the firm, having reviewed its "
           "own file, disagreed. ") * 40

# Ordinary prose: short sentences, few commas, no compounds, plain repeated words.
PLAIN = ("The firm sent the letter in March. It seems the customer did not receive it. "
         "The adviser says she posted it. I think the account was closed by then. "
         "The bank paid the money back. The customer asked for interest. ") * 40


def test_the_shipped_target_loads_and_is_the_committed_artifact():
    """Fence 1. Not a fixture, not a fetch — the file that ships in the wheel."""
    assert prose_target.TARGET_PATH.exists(), prose_target.TARGET_PATH
    t = prose_target.load_target()
    assert str(t["tokeniser_version"]) == TOKENISER_VERSION
    assert t["corpus"]["human"]["documents"] >= 200
    assert t["corpus"]["ours"]["documents"] >= 200


def test_lint_does_no_network_io():
    """Fence 2. The corpora are gitignored and never shipped; grading reads one JSON file.

    Sockets are broken for the duration, so any fetch — a corpus download, a model call, a
    telemetry ping — fails the test rather than passing silently in CI where the network is
    up.
    """
    import socket

    def no_sockets(*a, **k):
        raise AssertionError("lint attempted network I/O")

    real = socket.socket
    socket.socket = no_sockets
    try:
        m = register_metrics({"a.md": PLAIN})
    finally:
        socket.socket = real
    assert m["prose_measures"], "nothing was measured"
    assert m["human_register_error"] == ""


def test_a_target_measured_with_another_tokeniser_is_refused(tmp_path):
    """Fence 3. Reading it anyway would compare two tokenisers and call the difference a
    style defect. The target must be re-measured, not reinterpreted."""
    raw = json.loads(prose_target.TARGET_PATH.read_text())
    raw["tokeniser_version"] = "not-this-one"
    p = tmp_path / "prose_target.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(prose_target.TargetUnreadable) as exc:
        prose_target.load_target(p)
    assert "tokeniser version" in str(exc.value)


def test_a_malformed_target_raises_rather_than_grading_against_nothing(tmp_path):
    p = tmp_path / "prose_target.json"
    p.write_text("{oh no")
    with pytest.raises(prose_target.TargetUnreadable):
        prose_target.load_target(p)
    p2 = tmp_path / "empty.json"
    p2.write_text('{"tokeniser_version": "1"}')
    with pytest.raises(prose_target.TargetUnreadable):
        prose_target.load_target(p2)


def test_an_unarmed_measure_can_never_produce_a_finding():
    """Fence 4, and the whole reason arming exists.

    Every measure is handed a value far outside its human interval. Only the armed ones may
    come back. `long_sentence_rate` is the one that matters: it is the rule that used to be
    enforced, our corpus sits inside the human range on it, and it must stay silent however
    extreme the document.
    """
    target = prose_target.load_target()
    absurd = {name: float(spec["p95"]) * 100 + 1000 for name, spec in target["measures"].items()}
    reported = {f["measure"] for f in prose_target.grade(absurd)}
    armed = set(prose_target.armed_measures())
    assert reported == armed
    assert "long_sentence_rate" not in reported
    assert "clause_load_mean" not in reported


def test_the_armed_set_is_the_six_we_measured():
    """A change to this set is a re-measurement, not an edit. If this fails, either the
    corpora moved or someone hand-edited the target; both need `--write-target` re-run."""
    assert set(prose_target.armed_measures()) == {
        "heavy_sentence_rate",
        "hedges_per_1k",
        "mattr",
        "punct_comma_per_1k",
        "punct_semicolon_per_1k",
        "punct_hyphen_per_1k",
    }


def test_every_armed_measure_is_form_never_subject_matter():
    """The founder's carve-out, mechanically. We adopt how a human builds a sentence; we do
    not adopt what they write about. Every armed measure is a count of punctuation, sentence
    shape, or a closed-class function-word list — none can carry a topic."""
    for name in prose_target.armed_measures():
        assert (name.startswith("punct_")
                or name in {"heavy_sentence_rate", "mattr", "hedges_per_1k"}), name


def test_the_linter_measures_a_document_the_way_the_target_was_built():
    """Fence 5. ONE implementation, not two implementations plus an agreement test: both
    sides call `prose_measure.document_measures`. This pins that `register_metrics` has not
    grown a second copy."""
    from prospector.register_lint import measurable_prose
    direct = document_measures(measurable_prose(PLAIN))
    via_lint = register_metrics({"a.md": PLAIN})["prose_measures"]
    for k, v in via_lint.items():
        assert round(direct[k], 3) == pytest.approx(v, abs=1e-9), k


def test_prose_far_outside_the_human_range_is_reported():
    m = register_metrics({"a.md": STACKED})
    outside = {f["measure"] for f in m["human_register"]}
    assert {"punct_comma_per_1k", "punct_hyphen_per_1k", "heavy_sentence_rate"} <= outside


def test_plain_prose_is_not_reported_for_over_punctuating():
    """The check must not fire on writing that already reads plainly. If it does, it is a
    style preference wearing a measurement's clothes.

    Stated per SIDE on purpose. `PLAIN` has no hyphens and no semicolons at all, which is
    below the human 5th percentile and is reported as such — a human writes the occasional
    compound. What must never happen is plain prose being told it over-punctuates.
    """
    m = register_metrics({"a.md": PLAIN})
    above = {f["measure"] for f in m["human_register"] if f["side"] == "above"}
    assert not (above & {"punct_comma_per_1k", "punct_hyphen_per_1k", "heavy_sentence_rate"})


def test_the_actuator_defaults_to_advisory_and_is_the_only_thing_that_blocks():
    """Same contract as every other rate in this file: measure always, block only when an
    operator sets the knob. `listing.human_register_block` is false in config.yaml."""
    m = register_metrics({"a.md": STACKED})
    assert m["human_register"], "fixture no longer trips the check"
    off = check_register({"a.md": STACKED}, metrics=m)
    on = check_register({"a.md": STACKED}, human_register_block=True, metrics=m)
    assert [p for p in off if p["check"] == "human_register"]
    assert not [p for p in off if p["check"] == "human_register" and p["severity"] == "error"]
    assert [p for p in on if p["check"] == "human_register" and p["severity"] == "error"]


def test_short_prose_is_measured_but_never_blocked_on():
    """Below `MIN_WORDS_FOR_RATES` every rate in this file is noise, and this one is no
    different — MATTR is not even defined under one 100-token window."""
    problems = check_register({"a.md": "Two commas, here, only."}, human_register_block=True)
    assert not [p for p in problems if p["check"] == "human_register"]


def test_an_unreadable_target_is_said_out_loud(monkeypatch, tmp_path):
    """Fence 6. A missing target must not strand the shelf, and it must not read as a clean
    pack either. This is the failure mode the whole programme exists to stop: a check that
    reports nothing looks exactly like a check that found nothing."""
    monkeypatch.setattr(prose_target, "TARGET_PATH", tmp_path / "gone.json")
    m = register_metrics({"a.md": STACKED})
    assert m["human_register"] == []
    assert "not readable" in m["human_register_error"]
    problems = check_register({"a.md": STACKED}, metrics=m)
    said = [p for p in problems if p["check"] == "human_register"]
    assert said and "not measured against the human corpus" in said[0]["detail"]


def test_the_report_carries_the_measures_whether_or_not_anything_is_outside():
    """The baseline accrues on every pack. A threshold may only ever be set from numbers
    seen on live packs — the lesson of the house-spec knobs, all of which are still 0.0."""
    m = register_metrics({"a.md": PLAIN})
    for key in ("punct_comma_per_1k", "mattr", "hedges_per_1k", "heavy_sentence_rate"):
        assert key in m["prose_measures"], key
    json.dumps(m)  # the report is written to <id>.lint.json


def test_the_advice_only_covers_armed_measures_and_both_sides_of_each():
    """Advice on an unarmed measure is advice the measurement did not earn. And a measure
    with advice for one side only tells a writer to fix the opposite defect: "split the
    sentence" is wrong counsel for a document with no commas in it."""
    assert set(prose_target.ADVICE) == set(prose_target.armed_measures())
    for measure, sides in prose_target.ADVICE.items():
        assert set(sides) == {"above", "below"}, measure
        assert prose_target.advice_for(measure, "above")
        assert prose_target.advice_for(measure, "below")
    assert prose_target.advice_for("long_sentence_rate", "above") == ""


def test_the_advice_follows_the_side_the_document_fell_off():
    stacked = [p["detail"] for p in check_register({"a.md": STACKED})
               if p["check"] == "human_register" and "punct_comma" in p["detail"]]
    assert stacked and "Split the sentence" in stacked[0]
    plain = [p["detail"] for p in check_register({"a.md": PLAIN})
             if p["check"] == "human_register" and "punct_hyphen" in p["detail"]]
    assert plain and "no hyphens at all" in plain[0]
