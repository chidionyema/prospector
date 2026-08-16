"""The shelf line may not open on a pronoun that points at nothing.

The founder named all three defects in the same message (2026-08-16), reading live packs:
"it takes is not a good way to start", "dont like how sentence starts", and — pointing at
the shape to copy — "A tool for UK freelance designers, developers and writers that turns
every out-of-scope client request into a priced, dated change note the client has to answer".

The second-person half of that complaint was already a rule (`check_shelf_copy` #4, live
since 2026-08-13). The OPENER half was checked by nothing, which is how "We handle your
stolen tool insurance claim…" and "It takes a published NHS rota…" reached the live shelf.
"""

from prospector.pack_linter import check_shelf_copy


def _details(line, **kw):
    return [p["detail"] for p in check_shelf_copy({"cardLine": line}, **kw)]


def _openers(line, **kw):
    return [d for d in _details(line, **kw) if "opens on" in d]


class TestBareOpenerIsADefect:
    def test_the_three_lines_the_founder_rejected(self):
        for line in (
            "It takes a published NHS rota and timesheet, applies the worker's contract "
            "terms, and returns the overtime owed.",
            "We handle the stolen tool insurance claim from police report to payout.",
            "This self-serve tool turns a Cal/OSHA citation into a defence.",
        ):
            assert _openers(line), line

    def test_the_line_the_founder_named_as_the_shape_passes(self):
        line = ("A tool for UK freelance designers, developers and writers that turns every "
                "out-of-scope client request into a priced, dated change note the client "
                "has to answer.")
        assert _details(line) == []

    def test_a_pronoun_mid_sentence_has_an_antecedent_and_is_fine(self):
        line = "A fixed-fee appeal service for shop owners, run by the surveyors who built it."
        assert _openers(line) == []

    def test_it_errors_under_the_actuator_and_warns_without_it(self):
        line = "It takes a rota and returns the overtime owed."
        assert [p["severity"] for p in check_shelf_copy({"cardLine": line}, block=True)
                if "opens on" in p["detail"]] == ["error"]
        assert [p["severity"] for p in check_shelf_copy({"cardLine": line})
                if "opens on" in p["detail"]] == ["warning"]

    def test_a_leading_quote_or_bracket_does_not_hide_the_opener(self):
        assert _openers('"We handle the claim from report to payout."')
