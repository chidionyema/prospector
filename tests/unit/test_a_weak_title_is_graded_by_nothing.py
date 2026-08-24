"""The publish gate passes the deadest titles in the catalogue and refuses the strongest.

Measured 2026-08-21 over the 119 live catalogue listings. Two instruments, agreeing in the
worst possible way: `headline_craft.devices` finds 43 titles (36.1%) using none of the four
craft devices, and `pack_linter.check_title` — the publish gate — calls those CLEAN while
refusing every one of the six that use all four.

The cause is not an accident of regex. `prompts/retitle.md` instructs the writer "NO PRODUCT
NAME" and "Write a noun phrase", which forbids two of the four devices outright, and
`check_title` enforces a 60-character cap that the crafted form cannot fit inside.

This file pins the grader that was missing, and pins the inversion itself so that fixing the
gate produces a loud, self-explaining failure rather than a silent drift.
"""
from __future__ import annotations

import pytest

from prospector.headline_craft import MIN_DEVICES, devices, grade
from prospector.pack_linter import TITLE_MAX_CHARS, check_title

#: Live catalogue titles, 2026-08-21. All four devices, and the six strongest lines the engine
#: has ever produced.
CRAFTED = [
    "GrossStick — the fixed-fee appeal that wins back your CIS gross payment when HMRC refuses",
    "RetainRelease — the subcontractor's automated retention chaser that forces main "
    "contractors to release the 3-5% they're holding back",
    "Nudge Letter Rebuttal — turns HMRC's child benefit tax bill into a fixed-fee appeal "
    "built on tribunal wins",
]

#: Live catalogue titles, same day. Zero devices: no name, no adversary, no stake, no verb.
DEAD = [
    "Clinical-coding checks for private hospitals",
    "Requirements packages for software product managers",
    "Salesforce Data Cloud activation for Georgia partners",
    "Per-parcel customs broker for direct-to-consumer importers",
]


@pytest.mark.parametrize("title", CRAFTED)
def test_a_crafted_title_uses_every_device(title: str) -> None:
    found = devices(title)
    assert set(found) == {"name", "antagonist", "stake", "verb"}, (
        f"{title!r} is one of the strongest lines in the catalogue and should use all four "
        f"devices; got {found}"
    )
    assert grade(title) == [], f"{title!r} graded weak: {grade(title)}"


@pytest.mark.parametrize("title", DEAD)
def test_a_bare_description_is_graded_weak(title: str) -> None:
    assert devices(title) == [], f"{title!r} should use no craft device; got {devices(title)}"
    why = grade(title)
    assert why, f"{title!r} is a bare service description and must grade weak"
    assert "weak title" in why[0]


def test_a_coined_name_alone_is_not_a_name_device() -> None:
    """The founder's 2026-08-13 complaint — "the title tells me nothing, it feels cryptic".

    A name only counts when a plain descriptor follows it. `FreelanceCaseLaw` is exactly the
    line that produced the ban, and it must not score the device the ban was aimed at.
    """
    assert devices("FreelanceCaseLaw") == []
    assert devices("PlatformAlpha: The Freelancer's Gig Discovery Letter") == []


def test_an_article_opener_is_not_a_product_name() -> None:
    """`The Subbie Brief — the weekly read…` opens on grammar, not a coined name."""
    assert "name" not in devices(
        "The Subbie Brief — the weekly read that shows UK trades how other "
        "subcontractors actually got paid"
    )


def test_a_noun_pileup_is_reported_separately() -> None:
    why = grade(
        "NurseryDebt Bridge — The Primary Carer's Childcare-Provider Insolvency "
        "Fee-Recovery & Placement-Transfer Broker"
    )
    assert any("noun pileup" in w for w in why), why


def test_an_empty_title_is_not_this_graders_error() -> None:
    """Emptiness is `check_title`'s error to raise. Two graders raising it is two receipts."""
    assert grade("") == []
    assert grade("   ") == []


def test_the_floor_is_two_devices() -> None:
    """One device is still weak. Two is not. The floor is where the corpus separates."""
    assert MIN_DEVICES == 2
    one_device = "Requirements packages, paid on commission"          # stake only
    assert len(devices(one_device)) == 1, devices(one_device)
    assert grade(one_device), "a one-device line must still grade weak"

    two_devices = "Retention chaser that wins back the 3% a main contractor is holding"
    assert len(devices(two_devices)) >= 2, devices(two_devices)
    assert grade(two_devices) == [], (
        f"two devices clears the floor; got {grade(two_devices)}"
    )


def test_the_publish_gate_is_inverted_against_craft() -> None:
    """THE FINDING. Delete this test the day the gate stops being inverted, not before.

    If this fails with "the gate no longer refuses", that is GOOD NEWS: someone reconciled
    `check_title` and `prompts/retitle.md` with the craft devices. Read the failure, confirm
    the reconciliation, then delete this test and say so in the commit.
    """
    for title in CRAFTED:
        problems = check_title(title, max_chars=TITLE_MAX_CHARS)
        assert any(p.get("severity") == "error" for p in problems), (
            f"the gate no longer refuses the crafted title {title!r} — if that is deliberate, "
            f"this test has done its job and should be deleted"
        )

    for title in DEAD:
        problems = check_title(title, max_chars=TITLE_MAX_CHARS)
        assert not [p for p in problems if p.get("severity") == "error"], (
            f"the gate now refuses the bare description {title!r} — if that is deliberate, "
            f"this test has done its job and should be deleted"
        )
        assert grade(title), (
            f"{title!r} passes the publish gate and must still grade weak here — that "
            f"disagreement is the whole point of this module"
        )
