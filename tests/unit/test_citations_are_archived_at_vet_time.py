"""A citation must be snapshotted while the page is still alive — i.e. at vet time.

WHAT THIS COST, MEASURED
------------------------
`archive_sources` ran in exactly one place, `prospector/bridge.py:813`, on the PUBLISH path.
A pack is routinely published weeks or months after it was vetted, and the Internet Archive
cannot snapshot a page that has already gone. So publish-time archiving preserved only the
citations that did not need preserving.

Measured 2026-08-13 over every pack the lint gate was holding off the live storefront:

    dead cited URLs across blocked packs : 16
      ...that DO have a Wayback memento  :  4   (pre-existing captures `_lookup` found —
                                                 not snapshots this engine ever took)
      ...with no archive at all          : 12

`pack_linter` is already built to accept a memento in place of a dead link and downgrade the
error to a warning (`pack_linter.py:854-861`). It had nothing to accept. 16 of the 19 lint
failures blocking the shelf were dead URLs, and the storefront sat at 50 listed packs.

The defect shape is the one that recurs in this repo: the safeguard ran where the damage was
MEASURED, not where the evidence was CREATED.

These tests pin the three properties that make the fix real rather than nominal: it happens
BEFORE the dossier is serialised (otherwise it sets a field nobody reads), it does not charge
the archive for verdicts that can never list, and it can never cost us a ruled verdict.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from prospector.config import Config
from prospector.models import Candidate, Decision, Dossier
from prospector.store import Store


def _cfg(tmp_path: Path, **listing) -> Config:
    base = {"archive_citations": True, "archive_at_vet": True, "archive_at_vet_max_urls": 12}
    base.update(listing)
    return Config(operator=["mock"], store={"dir": str(tmp_path / "store")}, listing=base)


def _dossier(decision: Decision, cid: str = "arch_test_001") -> Dossier:
    cand = Candidate(title="Archive At Vet", one_liner="pin the seam", why_now="testing")
    cand.candidate_id = cid
    cand.tags = {}
    return Dossier(
        candidate=cand, decision=decision, gate_fired=None, reason="test", checks=[],
        adversarial=None, score=None, model_version="test",
        created_at="2026-08-13T00:00:00Z", reverify_due_at=None, provider_chain="test",
    )


def test_a_pass_dossier_is_archived_BEFORE_its_json_is_written(tmp_path, monkeypatch):
    """Ordering is the whole point: `archive_sources` sets `Source.archived_url` in place.

    Archiving after serialisation would populate a field that never reaches disk — the same
    ordering constraint `bridge.py` documents against `_create_bundle`. The spy records
    whether the dossier JSON already existed when it was called; if the fix is real, it did
    not.
    """
    import prospector.archive as archive_mod

    seen: dict = {}
    target = tmp_path / "store" / "dossiers" / "arch_test_001.pass.json"

    def spy(sources, **kw):
        seen["called"] = True
        seen["json_existed_at_call_time"] = target.exists()
        seen["max_urls"] = kw.get("max_urls")
        return 0

    monkeypatch.setattr(archive_mod, "archive_sources", spy)

    store = Store(_cfg(tmp_path))
    path = store.save(_dossier(Decision.PASS))

    assert seen.get("called"), "a PASS dossier was saved without archiving its citations"
    assert seen["json_existed_at_call_time"] is False, (
        "archiving ran AFTER the dossier was serialised — the memento it mints can never "
        "reach disk, which makes the whole call decorative")
    assert path.exists()
    assert seen["max_urls"] == 12, (
        "the vet-time archive must use its own bound (`archive_at_vet_max_urls`); it runs "
        "inside the daemon tick, where wall-clock is a live complaint")


def test_a_kill_dossier_does_not_pay_the_archive(tmp_path, monkeypatch):
    """A KILL can never list, so archiving its citations buys nothing and costs tick time."""
    import prospector.archive as archive_mod

    calls = []
    monkeypatch.setattr(archive_mod, "archive_sources", lambda s, **kw: calls.append(1) or 0)

    store = Store(_cfg(tmp_path))
    store.save(_dossier(Decision.KILL, cid="arch_test_kill"))

    assert calls == [], "a KILL dossier was charged to the Internet Archive for no benefit"


def test_an_archive_failure_never_loses_the_verdict(tmp_path, monkeypatch):
    """The Internet Archive being down is our convenience failing, not a reason to lose a ruling.

    `archive_sources` does not raise by contract. This pins the belt-and-braces catch, so a
    future change to that contract cannot start destroying verdicts.
    """
    import prospector.archive as archive_mod

    def boom(sources, **kw):
        raise RuntimeError("web.archive.org returned 503")

    monkeypatch.setattr(archive_mod, "archive_sources", boom)

    store = Store(_cfg(tmp_path))
    path = store.save(_dossier(Decision.PASS, cid="arch_test_boom"))

    assert path.exists(), "an archiving failure destroyed a ruled verdict"


@pytest.mark.parametrize("off", [{"archive_citations": False}, {"archive_at_vet": False}])
def test_either_switch_turns_it_off(tmp_path, monkeypatch, off):
    """Two switches, both honoured: the master one shared with the publish path, and its own.

    Guard-the-guard — without this the tests above would still pass if the flags were ignored
    and archiving were unconditional.
    """
    import prospector.archive as archive_mod

    calls = []
    monkeypatch.setattr(archive_mod, "archive_sources", lambda s, **kw: calls.append(1) or 0)

    store = Store(_cfg(tmp_path, **off))
    store.save(_dossier(Decision.PASS, cid="arch_test_off"))

    assert calls == [], f"archiving ran despite {off}"


def test_the_live_config_actually_switches_this_on():
    """The behaviour above is worthless if config.yaml leaves it off.

    Pins the deployed value, so turning it off becomes a deliberate, visible act rather than
    something a merge can do quietly.
    """
    from prospector.config import load_config

    listing = load_config().listing
    assert isinstance(listing, dict)
    assert listing.get("archive_citations") is True, "citation archiving is off in config.yaml"
    assert listing.get("archive_at_vet") is True, (
        "vet-time archiving is off in config.yaml — publish-time archiving alone is what let "
        "12 of 16 dead citations reach the lint gate with no durable copy")
