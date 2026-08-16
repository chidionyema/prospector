"""`tools/retitle_catalogue.py` — the parts that stand between a bad draft and the live shelf.

The tool rewrites copy on packs that are already on sale, so the interesting behaviour is not
"does it call the model" but what it does with what the model returns: every draft goes
through the real publish-path checks, and a pack that never converges must be skipped rather
than truncated. All of it runs against a stub operator — no network, no CLI.

The title is asked for as ONE field. Until 2026-08-13 it was assembled here from `name` and
`does`, because the format was `Name, what it does` and a model could not be trusted with the
separator. The format no longer has a name in it (`pack_linter.check_title`), so there is
nothing to assemble and the composer is gone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from prospector.pack_linter import TITLE_MAX_CHARS, check_title  # noqa: E402

retitle = pytest.importorskip("retitle_catalogue")


class StubOp:
    """Returns each queued payload in turn; records the prompts it was given."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.users = []

    def complete_json(self, system, user, temperature=0.0):
        self.users.append(user)
        return self.payloads.pop(0) if self.payloads else {}


ROW = {
    "id": "pack1",
    "title": "The Retention Release Engine — a tool for subcontractors",
    "oneLine": "Chases the retention main contractors hold back after practical completion.",
    "headline": "Get the retention released",
    "cardLine": "",
    "whoPays": "subcontractors",
    "sector": "construction",
    "market": "uk",
}

# The headline has to survive the pack's OWN claim checks, because `propose` grades every
# draft with them. It originally read "the last 5 percent of every job", which trips two
# real rules at once: 'every' is in `_CLAIM_ABSOLUTES`, and '5' is a figure ROW's copy never
# states. A fixture that cannot pass the gate under test makes the tool look broken when the
# tool is the only thing behaving.
GOOD = {"title": "Retention chasing for subbies",
        "headline": "You stop writing off the last of the job",
        "card_line": "Retention chased without a solicitor"}

#: 83 chars, and the shape a rejection must survive: too long, but truthful.
LONG_TITLE = "Retention chasing for building subcontractors owed money after practical completion"


def _propose(payloads, needs=None, row=None, **kw):
    op = StubOp(payloads)
    fields, trail, notes = retitle.propose(
        op, row or ROW, max_chars=kw.pop("max_chars", TITLE_MAX_CHARS),
        attempts=kw.pop("attempts", 3), needs=needs or {"title": ["too long"]})
    return fields, trail, op, notes


# --- the title arrives as one field and is punctuated in house style ---------------------

def test_a_dash_smuggled_into_the_title_is_removed_by_nodash():
    # The same `nodash` the publish path runs, for the same reason: 68 of 72 live listings
    # once carried an em dash into the catalogue because nothing between the model and the
    # column removed it.
    out = retitle._clean("Retention chasing — for subbies")
    assert "—" not in out and "–" not in out


def test_a_trailing_full_stop_is_dropped_without_spending_a_second_draft():
    fields, trail, _, _ = _propose([dict(GOOD, title="Retention chasing for subbies.")])
    assert fields["title"] == "Retention chasing for subbies"
    assert "accepted" in trail[0]


# --- which lines are actually defective -------------------------------------------------

def test_a_row_whose_copy_is_sound_is_left_alone_entirely():
    # The headline was "You stop writing off the last of the job" until 2026-08-16, when
    # `assess` began running the shelf-voice rules. It is second person — copy aimed at the
    # subcontractor rather than at the person deciding whether to run this business — so the
    # fixture for "sound copy" was itself an example of the defect the founder named that
    # day. Rewritten third person; the assertion it exists to make is unchanged.
    row = dict(ROW, title="Retention chasing for building subcontractors",
               headline="The last of the job stops being written off",
               cardLine="Retention chased without a solicitor")
    assert retitle.assess(row) == {}


def test_an_empty_card_line_is_a_defect_on_its_own():
    # 12 of the 48 live rows have none, which leaves the shelf card to speak for itself.
    # ROW's own title is a legacy one and defective in its own right, so it is replaced
    # here: this test is about the card line being enough on its own.
    row = dict(ROW, title="Retention chasing for building subcontractors")
    assert list(retitle.assess(row)) == ["cardLine"]


def test_a_headline_that_repeats_the_title_is_a_defect():
    row = dict(ROW, headline=ROW["title"], cardLine="Retention chased")
    assert "headline" in retitle.assess(row)


def test_a_headline_that_is_a_truncated_copy_of_the_title_is_the_same_defect():
    # 2 of the 48 live rows hold a prefix of their own title here.
    row = dict(ROW, headline=ROW["title"][:40], cardLine="Retention chased")
    assert "headline" in retitle.assess(row)


@pytest.mark.parametrize("headline", ["", "   "])
def test_an_empty_headline_is_a_defect(headline):
    row = dict(ROW, headline=headline, cardLine="Retention chased")
    assert "headline" in retitle.assess(row)


def test_an_over_length_card_line_is_a_defect():
    row = dict(ROW, cardLine="x" * 61)
    assert "cardLine" in retitle.assess(row)


def test_a_card_line_that_claims_a_place_the_pack_never_names_is_a_defect():
    row = dict(ROW, cardLine="Retention chased across Scotland")
    assert any("scotland" in w.lower() for w in retitle.assess(row)["cardLine"])


def test_the_lines_under_repair_are_not_used_as_evidence_that_the_repair_is_truthful():
    # 13 live headlines are verbatim copies of their title. If the headline counted as a
    # source, a title would be checked against itself and every claim would look supported.
    row = dict(ROW, headline="Recovers 40% in Scotland", cardLine="Recovers 40% in Scotland")
    assert "oneLine" in retitle._CLAIM_SOURCE_FIELDS
    for field in ("title", "headline", "cardLine"):
        assert field not in retitle._CLAIM_SOURCE_FIELDS
    assert "40" not in " ".join(retitle._claim_sources(row))


@pytest.mark.parametrize("headline,title,echo", [
    ("Chases retention", "Chases retention", True),
    ("Chases retention", "Chases retention for you", True),      # title extends headline
    ("Chases retention for you", "Chases retention", True),      # headline extends title
    ("You stop writing off the last 5 percent", "Chases retention", False),
    ("", "Chases retention", False),
])
def test_title_echo_is_prefix_in_either_direction(headline, title, echo):
    assert retitle._is_title_echo(headline, title) is echo


# --- punctuation is repaired without spending a model call ------------------------------

def test_a_dash_in_prose_that_is_not_being_rewritten_is_fixed_deterministically():
    row = dict(ROW, oneLine="Chases retention — after practical completion.")
    fixes = retitle.dash_repairs(row)
    assert "—" not in fixes["oneLine"]


def test_prose_with_no_dash_is_not_touched_at_all():
    # A no-op rewrite would still be a PATCH, and a PATCH is a change to a live row.
    assert retitle.dash_repairs(ROW) == {}


def test_dash_repair_changes_punctuation_and_not_wording():
    row = dict(ROW, proofPoint="Recovered £4,000 — on average.")
    assert retitle.dash_repairs(row)["proofPoint"].replace(", ", " ").split() == \
        "Recovered £4,000 on average.".split()


# --- every draft goes through the real publish-path checks ------------------------------

def test_an_accepted_title_satisfies_the_same_check_the_publish_gate_runs():
    fields, trail, _, _ = _propose([GOOD])
    assert fields == {"title": GOOD["title"]}
    assert check_title(fields["title"]) == []
    assert "accepted" in trail[0]


def test_only_the_defective_lines_are_returned_so_sound_copy_is_left_alone():
    # This tool repairs a catalogue; it does not re-author one.
    fields, _, _, _ = _propose([GOOD], needs={"cardLine": ["empty"]})
    assert list(fields) == ["cardLine"]


def test_an_over_length_draft_is_rejected_and_re_asked_with_the_breach_verbatim():
    fields, trail, op, _ = _propose([dict(GOOD, title=LONG_TITLE), GOOD])
    assert fields["title"] == GOOD["title"]
    assert "rejected" in trail[0] and "accepted" in trail[1]
    assert "REJECTED" in op.users[1]
    # The count, verbatim: a vague "too long" gets a draft one character shorter.
    assert str(len(LONG_TITLE)) in op.users[1]


def test_a_draft_that_invents_a_figure_is_rejected_not_merely_noted():
    fields, trail, _, _ = _propose(
        [dict(GOOD, title="40% retention chasing for subbies"), GOOD])
    assert fields["title"] == GOOD["title"]
    assert "40" in trail[0]


def test_a_headline_that_still_echoes_the_proposed_title_is_rejected():
    fields, trail, _, _ = _propose(
        [dict(GOOD, headline=GOOD["title"]), GOOD],
        needs={"title": ["x"], "headline": ["empty"]})
    assert fields["headline"] == GOOD["headline"]
    assert "repeats the title" in trail[0]


def test_a_headline_is_graded_against_the_new_title_not_the_broken_one():
    # Otherwise a good headline is rejected for echoing a title that is about to be deleted.
    row = dict(ROW, headline="", title="You stop writing off the last 5 percent of every job")
    fields, trail, _, _ = _propose([GOOD], row=row,
                                   needs={"title": ["x"], "headline": ["empty"]})
    assert fields is not None and "accepted" in trail[0]


def test_a_pack_that_never_converges_is_skipped_not_truncated():
    over = dict(GOOD, title=LONG_TITLE)
    fields, trail, op, _ = _propose([over, over, over])
    assert fields is None
    assert len(trail) == 3 and all("rejected" in t for t in trail)
    assert len(op.users) == 3


def test_a_non_dict_response_is_re_asked_rather_than_crashing():
    fields, trail, _, _ = _propose([["not", "a", "dict"], GOOD])
    assert fields["title"] == GOOD["title"]
    assert "operator returned list" in trail[0]


def test_an_empty_field_is_re_asked_rather_than_written_to_the_live_row():
    fields, trail, _, _ = _propose([dict(GOOD, title=""), GOOD])
    assert fields["title"] == GOOD["title"]
    assert "empty" in trail[0]


def test_max_chars_is_honoured_so_a_narrower_run_is_actually_narrower():
    fields, _, _, _ = _propose([GOOD, dict(GOOD, title="Retention for subbies")],
                               max_chars=25)
    assert fields["title"] == "Retention for subbies"


def test_a_word_the_source_never_uses_is_reported_and_does_not_block():
    # The judgement a machine cannot make: fair paraphrase, or a quiet narrowing? It reaches
    # the reviewer as a NAMED word rather than as two paragraphs to diff by eye.
    fields, _, _, notes = _propose([GOOD])
    assert fields is not None
    assert any("subbies" in n for n in notes)


# --- the dossier write-back, without which a republish reverts everything ---------------

def _dossier(tmp_path, pack_id="pack1", title="Old title"):
    d = tmp_path / "dossiers"
    d.mkdir(parents=True)
    p = d / f"{pack_id}.pass.json"
    p.write_text(json.dumps({
        "candidate": {"title": title, "one_liner": "x"},
        # An unmodelled key: these files are the audit trail for verdicts ruled by earlier
        # engine versions, and a round-trip through models.Dossier would drop it silently.
        "legacy_field_no_dataclass_models": {"kept": True},
    }, indent=2), encoding="utf-8")
    return p


def test_the_dossier_title_is_updated_so_a_republish_does_not_revert_the_rewrite(tmp_path):
    # bridge._update_catalog sources the catalogue title from candidate.title, so patching
    # only the live row would be undone by the next republish — silently, and at an
    # unpredictable time.
    p = _dossier(tmp_path)
    assert retitle._write_dossier_title(tmp_path, "pack1", "New, and better") == ""
    assert json.loads(p.read_text())["candidate"]["title"] == "New, and better"


def test_the_write_back_preserves_keys_the_current_dataclasses_do_not_model(tmp_path):
    p = _dossier(tmp_path)
    retitle._write_dossier_title(tmp_path, "pack1", "New, and better")
    doc = json.loads(p.read_text())
    assert doc["legacy_field_no_dataclass_models"] == {"kept": True}
    assert doc["candidate"]["one_liner"] == "x"


def test_a_missing_dossier_returns_a_warning_naming_the_republish_risk(tmp_path):
    (tmp_path / "dossiers").mkdir()
    note = retitle._write_dossier_title(tmp_path, "absent", "New, and better")
    assert "republish" in note.lower()


def test_a_dossier_without_a_candidate_object_warns_rather_than_inventing_one(tmp_path):
    d = tmp_path / "dossiers"
    d.mkdir()
    (d / "pack1.pass.json").write_text(json.dumps({"verdicts": []}), encoding="utf-8")
    note = retitle._write_dossier_title(tmp_path, "pack1", "New, and better")
    assert "republish" in note.lower()
    assert "candidate" not in json.loads((d / "pack1.pass.json").read_text())


def test_a_plan_out_file_fed_to_from_plan_is_refused_rather_than_mis_keyed(tmp_path, monkeypatch,
                                                                          capsys):
    """The two plan formats are both three tab-separated columns, so the wrong flag parses
    cleanly and writes silently.

    `--plan-out` emits id/field/value; `--from-plan` reads id/before/after and keys by id alone,
    taking the LAST column. On 2026-08-14 a --plan-out file went to --from-plan and every
    pack's final line — a headline or a card line — was written into its live TITLE: ten of
    fourteen rows wrong, two of them past the 60-char cap, under a report reading
    "patched: 14, failed: 0". Nothing downstream could catch it, because each individual write
    was exactly what it was told to do. The parse is the only place the two can be told apart.
    """
    plan = tmp_path / "plan.tsv"
    plan.write_text("abc123\ttitle\tSomething for someone\n"
                    "abc123\tcardLine\tDoes the thing\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["retitle_catalogue.py", "--dry-run", "--from-plan", str(plan)])
    assert retitle.main() == 2
    err = capsys.readouterr().err
    assert "--from-lines" in err, "the refusal must name the flag that IS correct"


def test_a_genuine_before_after_plan_still_parses(tmp_path, monkeypatch, capsys):
    """The other half: the guard keys on a field NAME in column 2, so it must not reject a real
    id/before/after plan, whose column 2 is prose. Without this, the fix above would read as
    working while having simply disabled the flag.
    """
    plan = tmp_path / "plan.tsv"
    plan.write_text("abc123\tOld title, with a name\tSomething for someone\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["retitle_catalogue.py", "--dry-run", "--from-plan", str(plan)])
    monkeypatch.setattr(retitle, "_fetch_catalogue", lambda *_a, **_k: [])
    # 1 = "no rows to process", i.e. it got past the parse and on to the catalogue.
    assert retitle.main() == 1
    assert "approved plan       : 1 titles" in capsys.readouterr().out
