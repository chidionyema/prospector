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


def _phrase_spans(phrase, text):
    from prospector.voice_gate.deny import _compile_phrase

    r = _compile_phrase(phrase)
    return [m.span(1) for m in r.finditer(text)]


def test_phrase_respects_word_boundaries_and_hyphens():
    # guards mirror register_lint `(?<![\w-])…(?![\w-])`, re-expressed DFA-safe.
    assert _phrase_spans("seamless", "integrates seamlessly") == []  # inside a word
    assert _phrase_spans("seamless", "fully-seamless-and-clean") == []  # hyphenated join
    assert _phrase_spans("seamless", "coseamlessd") == []
    assert _phrase_spans("seamless", "a seamless integration") == [(2, 10)]  # real, guards-free


def test_phrase_spans_are_guards_free():
    # lead/trail boundary chars never enter the reported span (parity with Rust inner-group).
    assert _phrase_spans("a testament to", "This is a testament to it all.") == [(8, 22)]
    assert _phrase_spans("look no further", "then look no further for answers") == [(5, 20)]


def test_phrase_case_insensitive_and_whitespace_run():
    assert _phrase_spans("double down", "DOUBLE DOWN on this?") == [(0, 11)]
    assert _phrase_spans("it is worth noting that", "it is  worth\nnoting that x") == [(0, 24)]
    assert _phrase_spans("moving forward", "moving forward, we cut.") == [(0, 14)]


def test_phrase_whitespace_run_inside_phrase_includes_run_len():
    # `\s+` in the compile takes any single whitespace run between words; the group span then
    # covers it, like the Rust inner group. Compare to the single-space form to prove length
    # tracks the run (position-preserving for the byte/char-base-agnostic oracle).
    ph = "moving forward"
    one = _phrase_spans(ph, "moving forward, now.")[0]
    two = _phrase_spans(ph, "moving   forward, now.")[0]
    assert (two[1] - two[0]) - (one[1] - one[0]) == 2  # two extra spaces stay inside the span
    assert _phrase_spans(ph, "moving	forward, now.")[0] == one  # tab run also matches


def test_phrase_apostrophe_curly_equality_at_same_position():
    # straight and curly forms both fire, and the span's substring is the phrase itself
    # (span/base-agnostic so a whitespace-tolerant oracle and the Rust byte gate agree).
    for apos in ("'", "\u2018", "\u2019"):
        text = f"the child{apos}s seamless claim is odd."
        spans = _phrase_spans("child's", text)
        assert spans == [(4, 4 + len("child's"))], (apos, spans, text)


def test_phrase_findings_rule_dispatch_ignores_absent_pattern():
    # a phrase: entry must never be misread as a pattern: rule and vice-versa.
    from prospector.voice_gate.deny import _compile

    pr = _compile({"id": "P1", "phrase": "seamless", "message": "m"})
    assert pr.is_phrase and pr.re.pattern.startswith("(?:^|[^\\w-])")
    pa = _compile({"id": "R1", "pattern": "no passage shows", "message": "m"})
    assert not pa.is_phrase
