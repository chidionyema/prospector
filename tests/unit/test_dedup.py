"""Regression tests for near-duplicate detection (Part 3).

The live catalogue accumulated 4 "retiree garden harvest" variants + 2 "probate
clear-out" variants that were the SAME idea reworded. They all passed the
char-ratio dedup because difflib.SequenceMatcher is blind to reworded titles
(max pair ratio 0.75, well under the 0.85 bar). These tests pin the second
(token-overlap) signal so that regression can never ship again, AND pin that
genuinely distinct ideas are NOT collapsed.
"""
from prospector.dedup import dedup, is_near_duplicate, _token_overlap
from prospector.models import Candidate


# The exact live titles that exposed the flaw, plus the distinct ideas that must survive.
RETIREE_GARDEN = [
    "Retiree's Garden-to-Table Harvest Service",
    "Retiree's Garden Legacy Service",
    "Retiree Garden Harvest Share",
    "Retiree's Garden Harvest Club: Hyperlocal Produce Broker",
]
PROBATE = [
    "Probate Property Clear-Out Agent",
    "The Probate Locker Clear-Out Agent",
]
DISTINCT = [
    "The Garden Office Power Broker",          # garden offices, NOT retiree gardening
    "The Vet's Fee Extractor",
    "The Solo Builder's Warranty Audit",
    "The Tradie's Time-Capture Agent",
]


def _cands(titles):
    return [Candidate(title=t) for t in titles]


def test_char_ratio_alone_misses_reworded_same_idea():
    """The exact failure mode: char ratio never fires on the reworded cluster."""
    for a in RETIREE_GARDEN:
        for b in RETIREE_GARDEN:
            if a != b:
                # char-only (token signal disabled) lets every pair through.
                assert not is_near_duplicate(a, b, token_threshold=None)


def test_token_signal_catches_the_retiree_garden_cluster():
    """With the token signal on, the 4 reworded variants collapse to one."""
    unique, dropped = dedup(_cands(RETIREE_GARDEN), catalogue_titles=[])
    assert len(unique) == 1, [c.title for c in unique]
    assert len(dropped) == 3


def test_token_signal_catches_the_probate_cluster():
    unique, dropped = dedup(_cands(PROBATE), catalogue_titles=[])
    assert len(unique) == 1, [c.title for c in unique]
    assert len(dropped) == 1


def test_distinct_ideas_are_never_collapsed():
    """The whole catalogue: distinct ideas + Garden Office must all survive."""
    titles = DISTINCT + ["Retiree's Garden Legacy Service"]  # one garden idea in the mix
    unique, _ = dedup(_cands(titles), catalogue_titles=[])
    kept = {c.title for c in unique}
    for t in DISTINCT:
        assert t in kept, f"distinct idea wrongly dropped: {t!r}"


def test_cross_batch_dedup_against_catalogue():
    """A reworded variant of something already in the catalogue is dropped."""
    catalogue = ["Retiree's Garden-to-Table Harvest Service"]
    unique, dropped = dedup(_cands(["Retiree Garden Harvest Share"]), catalogue)
    assert unique == []
    assert len(dropped) == 1


def test_garden_office_is_not_a_retiree_garden_dupe():
    """The one genuinely-different 'garden' idea must read as distinct."""
    assert _token_overlap(
        "The Garden Office Power Broker",
        "Retiree's Garden Legacy Service",
    ) < 0.34


def test_token_threshold_none_restores_char_only_behaviour():
    """Opt-out path (used by the kill fast-path) keeps strict char matching."""
    unique, dropped = dedup(_cands(RETIREE_GARDEN), catalogue_titles=[],
                            token_threshold=None)
    assert len(unique) == 4  # char ratio alone drops nothing
    assert dropped == []
