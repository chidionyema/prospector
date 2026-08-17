"""The cookie-banner stripper: what it must remove, and what it must never touch.

WHY THIS EXISTS. On 2026-08-16 the live landing page printed a payer-solvency check that ruled
`unverifiable` because "the ASHE earnings tables contain only cookie consent screens with no
actual wage data". The pages were fine. Our extraction stored the banner: `select_passage`
anchors the stored window on query terms, a consent notice contains none, so the anchor fell to
offset 0 and the first 600 chars -- the only chars `verify` shows the brain -- were the cookie
notice. Measured across `store/dossiers/`: 76 of 43,673 stored passages, 12.3% of everything
fetched from ons.gov.uk.

The stripper is heuristic, so the tests that matter most are the ones about restraint: a page
ABOUT cookie law must survive it, and the flag must default off so fixtures and golden-set runs
stay byte-for-byte.
"""
import pytest

from prospector.config import Retrieval
from prospector.retrieval import (
    CONSENT_MAX_REMOVED_SHARE,
    strip_consent_sentences,
)

# The real shape, taken from a stored ons.gov.uk passage: a title, then the banner, then the
# statistics the check was actually looking for.
ASHE = (
    "Annual Survey of Hours and Earnings (ASHE) - Office for National Statistics\n\n"
    "### Cookies on ons.gov.uk\n\n"
    "Cookies are small files stored on your device. "
    "We use some essential cookies to make this website work. "
    "Accept all cookies. Reject additional cookies. Cookie settings.\n\n"
    "Median gross weekly earnings for full-time employees were 728 pounds in April 2025. "
    "Earnings for 18-21 year olds rose 8.1 percent over the year. "
    "The distribution is published in Table 6 of this release. "
    "Estimates are based on a 1 percent sample of employee jobs. "
    "Figures are not seasonally adjusted and cover the pay period including 23 April."
)


def test_banner_leaves_the_read_window_and_the_numbers_stay():
    out = strip_consent_sentences(ASHE)
    assert "Cookies are small files" not in out
    assert "Reject additional cookies" not in out
    assert "Cookie settings" not in out
    # The point of the fix is not tidiness; it is that the evidence reaches the brain.
    assert "728 pounds" in out
    assert "8.1 percent" in out
    assert "Table 6" in out


def test_the_banner_is_out_of_the_window_the_brain_reads():
    """`verify` shows the brain only the first 600 chars of a stored passage. The defect is
    banner text inside that window, so that window is what this asserts on -- not the whole
    passage. Before the fix the head opened with the ONS cookie notice; after it, the head
    opens with the title and goes straight to the earnings."""
    head_before = ASHE[:600]
    head_after = strip_consent_sentences(ASHE)[:600]
    assert "Cookies are small files" in head_before
    assert "Cookies are small files" not in head_after
    assert "Median gross weekly earnings" in head_after


def test_a_page_about_cookie_law_is_returned_unchanged():
    """Restraint. legislation.gov.uk pages on PECR are full of banner vocabulary and are
    exactly the sources a legality check needs. The share guard is what protects them."""
    law = (
        "The Privacy and Electronic Communications Regulations require that we use cookies "
        "only with consent. Regulation 6 states that a person shall not store information. "
        "Cookie settings must be presented before storage occurs."
    )
    assert strip_consent_sentences(law) == law


def test_a_whole_wall_is_returned_unchanged_rather_than_emptied():
    """If a page is nothing but consent boilerplate we hand it back whole. An empty passage
    would read to the brain as a source we fetched and found blank, which is a different and
    worse lie than a source that is visibly a cookie wall."""
    wall = (
        "We use cookies. Accept all cookies. Reject all cookies. "
        "Cookie settings. Manage your cookies."
    )
    assert strip_consent_sentences(wall) == wall


def test_removing_most_of_a_page_is_refused():
    """The share guard, stated as a number so a future edit to the phrase list cannot quietly
    turn the stripper into a shredder."""
    assert 0.0 < CONSENT_MAX_REMOVED_SHARE < 1.0
    mostly_banner = (
        "We use cookies to make this site work. Accept all cookies. Reject additional cookies. "
        "Cookie settings. Manage your cookie preferences. Your privacy choices. "
        "Rates rose."
    )
    assert strip_consent_sentences(mostly_banner) == mostly_banner


@pytest.mark.parametrize("text", ["", None])
def test_empty_input_is_passed_straight_through(text):
    assert strip_consent_sentences(text) == text


def test_the_flag_is_off_in_the_dataclass():
    """Default OFF is what keeps fixtures, golden-set runs and any directly constructed
    `Retrieval()` byte-for-byte identical. config.yaml turns it on for the live engine, and
    the ops console (Parameters -> Retrieval) turns it back off without a source edit."""
    assert Retrieval().strip_consent_banners is False
