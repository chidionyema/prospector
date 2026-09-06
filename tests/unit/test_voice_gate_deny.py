"""Phase-0 deny gate: bad/good pairs per rule, enum-field exclusion, excision."""

from prospector.voice_gate.deny import excise, findings_for, grade_fields

EE = "evidence-export"


def test_ee1_verdict_label_is_engine_scaffolding():
    assert findings_for("Do incumbents own the space?\nSUPPORTED\nThe niche is open.")
    assert not findings_for("The niche is open and rivals are fragmented.")


def test_ee2_passage_speak():
    assert findings_for("No passage shows a funded rival.")
    assert not findings_for("No funded rival showed up in our research.")


def test_ee3_diligence_framing():
    assert findings_for("The strongest case against this idea is cost.")
    assert not findings_for("The biggest risk is acquisition cost.")


def test_ee4_numbered_citation_line():
    assert findings_for("Sources checked:\n1 acas.org.uk\n2 iwgb.org.uk")
    assert not findings_for("Acas offers broad free advice, not a specialist appeal engine.")


def test_ee5_hedged_research_speak():
    assert findings_for("No evidence establishes affordability for this group.")
    assert findings_for("The niche therefore appears open in these passages.")


def test_enum_fields_are_never_graded():
    # The phase-0 boundary decision: gate: "SUPPORTED" is structured data, not prose.
    assert grade_fields({"gate": "SUPPORTED", "gateLabel": "SUPPORTED", "verdict": "REFUTED"}) == {}
    assert grade_fields({"reason": "SUPPORTED"}) != {}


def test_excise_drops_only_dirty_sentences():
    text = "UK tribunal cases confirm the problem persists. No passage shows a dominant incumbent. Acas covers general advice only."
    clean, dropped = excise(text)
    assert "tribunal" in clean and "Acas covers" in clean
    assert dropped == ["No passage shows a dominant incumbent."]
    assert not findings_for(clean)


def test_excise_all_dirty_returns_empty():
    clean, dropped = excise("No passage shows anything. SUPPORTED.")
    assert clean == "" and len(dropped) == 2
