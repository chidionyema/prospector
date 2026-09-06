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
    # Narrowed 2026-09-06: the hedge FORMS are banned; a direct absence statement is the
    # kill log's own voice ("No evidence shows parents will pay" is the finding, not a hedge).
    assert findings_for("affordability cannot be determined from the evidence.")
    assert findings_for("the space is not shown to be open.")
    assert findings_for("The niche therefore appears open in these passages.")
    assert not findings_for("No evidence shows parents will pay.")


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


def test_walk_prose_finds_nested_leaves_and_skips_enums_and_urls():
    from prospector.voice_gate.deny import walk_prose

    doc = {
        "title": "Clean title.",
        "verdict": "SUPPORTED",  # enum: never yielded
        "checks": [{"key": "x", "rationale": "No passage shows y. Real sentence here."}],
        "blocks": [
            {
                "type": "items",
                "items": [[{"tag": "strong", "children": ["Heading?"]}, "1 acas.org.uk"]],
            }
        ],
        "chips": [{"label": "acas.org.uk", "url": "https://acas.org.uk"}],
    }
    leaves = {p: t for _p, _k, p, t in walk_prose(doc)}
    assert "$.title" in leaves
    assert "$.verdict" not in leaves  # enum excluded
    assert "$.checks[0].key" not in leaves  # enum excluded
    assert "$.checks[0].rationale" in leaves
    assert "$.blocks[0].items[0][1]" in leaves  # the citation line IS graded prose
    assert "$.blocks[0].items[0][0].children[0]" in leaves  # heading fragment is prose
    assert "$.chips[0].url" not in leaves  # URL excluded
    assert "$.chips[0].label" not in leaves  # bare domain: a citation, not prose
    dirty = [p for _p, _k, p, t in walk_prose(doc) if findings_for(t)]
    assert "$.checks[0].rationale" in dirty and "$.blocks[0].items[0][1]" in dirty
