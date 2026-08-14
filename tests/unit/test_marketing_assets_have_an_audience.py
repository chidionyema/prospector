"""P6: the four marketing assets were four drafts of one paragraph, labelled in thread order.

The founder's reading of `8d5e24fbe6c1f5d3`: "The section headed **Launch Email** contains a
product description. The section headed **Listing Page** opens with `Subject:`. The labels
are swapped." They were not swapped — they were arbitrary. `prompts/content_gen.md` carried

    Type: {one of: listing_page | teaser_social | seo_preview | launch_email}

which is not a placeholder (`prompts.render` substitutes `{type}` by literal `str.replace`),
so all four threads sent an IDENTICAL prompt and `artifacts._gen_one_content` stamped the
type onto whichever draft returned.

Census over the 557 dossiers on disk carrying marketing (2026-08-14): 177 of 177
`launch_email` pieces had no `Subject:` line; 19 dossiers carried a piece selling OUR pack.
"""
from prospector import marketing_assets as ma
from prospector.pack_linter import check_marketing
from prospector.prompts import render


def _errors(problems):
    return [p for p in problems if p["severity"] == "error"]


def _warnings(problems):
    return [p for p in problems if p["severity"] == "warning"]


# --- the root cause: the model was never told which of the four to write -----------------

def test_the_prompt_tells_the_model_which_asset_it_is_writing():
    """The whole defect in one assertion. Every other fix here is downstream of it."""
    _, user = render("content_gen", candidate_json="{}", claims_json="[]",
                     type="launch_email", currency_rule="")
    assert "Type: launch_email" in user


def test_two_asset_types_do_not_get_the_same_prompt():
    kw = dict(candidate_json="{}", claims_json="[]", currency_rule="")
    _, email = render("content_gen", type="launch_email", **kw)
    _, social = render("content_gen", type="teaser_social", **kw)
    assert email != social


def test_the_prompt_names_the_reader_of_each_business_facing_piece():
    """A type name alone would not have fixed it: the model has to know WHO reads it."""
    _, user = render("content_gen", candidate_json="{}", claims_json="[]",
                     type="launch_email", currency_rule="")
    assert "FROM THE BUSINESS TO ITS FIRST CUSTOMERS" in user
    assert "Never mention this pack" in user


def test_the_generator_and_the_renderer_read_one_type_list():
    """A local list in `artifacts` is how the generator, the heading and the gate came to
    disagree about what a `launch_email` is."""
    from prospector.artifacts import ASSET_TYPES as generated

    assert generated == ma.ASSET_TYPES
    for t in ma.ASSET_TYPES:
        assert t in ma.LABELS


# --- the heading a buyer reads -----------------------------------------------------------

def test_the_heading_is_the_reader_not_our_enum():
    """It shipped `## Seo Preview` — an internal enum, title-cased, in a £49.99 product."""
    head, who = ma.heading_for("seo_preview")
    assert head == "Search listing"
    assert "search result" in who


def test_an_unknown_type_still_gets_a_heading_but_no_invented_reader():
    head, who = ma.heading_for("podcast_ad")
    assert head == "Podcast Ad" and who == ""


# --- the gate ----------------------------------------------------------------------------

def test_copy_selling_our_pack_blocks_the_pack():
    problems = check_marketing([
        {"type": "launch_email",
         "copy": "Subject: hello\n\nHere is a new opportunity pack. Open the pack to see."},
    ])
    assert _errors(problems), "pack-voice copy in the business's own launch email"


def test_the_listing_page_may_still_talk_about_the_pack():
    """The listing_page IS our storefront copy: the same words are correct there. A gate
    that fired on it would be teaching the generator to stop describing what we sell."""
    assert check_marketing([
        {"type": "listing_page", "copy": "Inside this pack: the plan, the sources, the costs."},
    ]) == []


def test_a_business_that_genuinely_sells_a_pack_is_not_flagged():
    """`the pack` alone would fire on real candidates — a launch pack for NHS nurses is on
    the catalogue. The gate matches phrases only OUR reader could be the subject of."""
    assert check_marketing([
        {"type": "launch_email",
         "copy": "Subject: your reclaim pack\n\nYour launch pack is ready. The pack ships "
                 "on Friday and includes everything you asked for."},
    ]) == []


def test_a_listing_page_that_opens_with_a_subject_line_is_an_email_under_the_wrong_heading():
    problems = check_marketing([
        {"type": "listing_page",
         "copy": "Subject: A printed picture book that stars one child\n\nHere is what it is."},
    ])
    assert _errors(problems)


def test_an_email_without_a_subject_line_warns_rather_than_unlisting_the_corpus():
    """177 of 177 on disk carry this defect, and only regeneration can clear it — an error
    would unlist every pack we have over something a republish cannot fix."""
    problems = check_marketing([
        {"type": "launch_email", "copy": "This business prints personalised picture books."},
    ])
    assert _warnings(problems) and not _errors(problems)


def test_a_subject_line_buried_in_the_body_is_not_a_subject_line():
    problems = check_marketing([
        {"type": "launch_email",
         "copy": "We wrote to every parent.\n\nSubject: the one we sent last week."},
    ])
    assert _warnings(problems)


def test_an_empty_piece_is_not_this_checks_finding():
    """`validate_pack` owns emptiness; two reports of one defect is noise in the receipt."""
    assert check_marketing([{"type": "launch_email", "copy": "  "}]) == []


def test_the_lint_actually_runs_this_check():
    """A check nobody calls is the failure mode this whole programme exists for."""
    from prospector.pack_linter import lint_pack

    report = lint_pack(
        artifacts={}, listing_copy="", listing_texts={}, market="uk",
        marketing=[{"type": "seo_preview", "copy": "Open the pack to see the plan."}])
    assert any(p["check"] == "marketing_audience" for p in report["problems"])
    assert report["ok"] is False
