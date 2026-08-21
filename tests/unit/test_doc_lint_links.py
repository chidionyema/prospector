"""A deep link either lands on the claim it cites, or it is a lie with a footnote.

`docs/RESEARCH_INDEX.md` is the founder's "all research in one place", and its whole value is
that its pointers land. A link whose file moved, or whose target heading was reworded, still
reads as a citation and takes the reader nowhere — the same class of rot as ENG-6, which is
what `scripts/doc_lint.py` already exists to compile away.

This test is a hard zero, not a ratchet. The repo measured 531 links and 0 broken on
2026-08-21, so there is no backlog to burn down and nothing to suppress. A ceiling here would
only be somewhere to hide the next break.

Three of the four cases below are slug rules this instrument got WRONG first, each time by
reporting a link that resolves as broken. A checker that cries wolf gets switched off, so the
rules are pinned rather than trusted.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "scripts"))

import doc_lint  # noqa: E402


def test_every_deep_link_in_the_repo_resolves():
    findings, tally = doc_lint.check_links()
    assert findings == [], "\n".join(
        f"{f['file']}:{f['line']}: {f['kind']}: {f['detail']}" for f in findings)
    # A tally of zero everywhere would pass the assertion above while grading nothing.
    assert tally["ok"] > 100, f"the checker found almost no links to grade: {tally}"


def test_an_intra_word_underscore_survives_the_slug():
    """GitHub keeps `cta_text`; only DELIMITER underscores are emphasis.

    Stripping every underscore alongside `*` and `~` reported
    `docs/TEMPLATE_FIRST_COPY.md#b-dead-cta_text-has-no-consumer` as broken when it resolves.
    """
    assert doc_lint.anchor_slug("B. Dead: cta_text has no consumer") == \
        "b-dead-cta_text-has-no-consumer"


def test_a_delimiter_underscore_is_still_emphasis():
    """The other half of the same rule. Removing it would be over-correcting."""
    assert doc_lint.anchor_slug("_why_ it matters") == "why-it-matters"


def test_a_spaced_em_dash_leaves_two_hyphens():
    """GitHub hyphenates EACH whitespace character and does not collapse runs.

    The em dash is dropped as punctuation, leaving two spaces, so the slug carries a double
    hyphen. Collapsing whitespace runs reported 8 correct anchors in `README.md` as broken.
    """
    assert doc_lint.anchor_slug("The model chains — the moat vs. the cheap stuff") == \
        "the-model-chains--the-moat-vs-the-cheap-stuff"


def test_a_link_inside_an_inline_code_span_is_not_a_link():
    """`[text](url)` in prose is a markdown EXAMPLE, not navigation.

    Two of these in `docs/HANDOFF_PACK_CONTENTS_REVIEW.md` were reported as a missing file
    called `url`.
    """
    line = "Write it as `[text](url)`, never as [text](docs/RUNBOOKS.md)."
    blanked = doc_lint._INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
    hrefs = [href for _text, href in doc_lint._MD_LINK.findall(blanked)]
    assert hrefs == ["docs/RUNBOOKS.md"]
    # And the length is preserved, so a reported column still points at the right character.
    assert len(blanked) == len(line)


def test_link_findings_never_enter_the_ratchet_baseline():
    """`--links` is a separate mode on purpose.

    Folding it into `lint()` would move every per-file count in `docs/doc_lint_baseline.json`
    at once, so `test_doc_lint_never_increases.py` would fail for a reason that has nothing to
    do with doc rot, and one burn-down queue would become two.
    """
    link_kinds = {"missing_link_target", "missing_anchor"}
    assert {f["kind"] for f in doc_lint.lint()} & link_kinds == set()
