"""Publishing is the one step two workers must never do at once.

WHY THIS FILE EXISTS NOW. Under the tick this was unreachable: one process, one deadline, one
publish loop. The producer/consumer split makes it reachable in three ways at once —
`consume --publish` is DESIGNED to run as more than one worker, a manual `vet --resume
--publish` can run beside a consumer, and a re-publish can race a first publish.

WHY IT IS NOT COVERED BY THE QUEUE LEASE. `store.claim` excludes two consumers from VETTING
one row. Publishing happens AFTER a verdict, from whoever holds the dossier — including a
caller that never took a lease at all. Two mechanisms because there are two things to exclude.

WHY IT IS THE MONEY RAIL. `publish` mints a provider Price and writes the catalogue row
(`bridge.py`), so a double publish is two prices for one pack, and the catalogue then disagrees
with the rail — which charges a buyer and then fails the fulfilment fence
(memory: `the-catalogue-took-the-fallback-the-rail-took-the-decision`, `price-change-breaks-
fulfilment`). It is not idempotent and it cannot be fixed by retrying, so it must be prevented.
"""
from __future__ import annotations

import types

import pytest

from prospector import claim_lock
from prospector import run as run_mod
from prospector.models import Candidate, Decision, Dossier


def _cfg(tmp_path, **claim):
    settings = {"enabled": True, "dir": "", "stale_after_s": 3600}
    settings.update(claim)
    return types.SimpleNamespace(store_dir=tmp_path, claim_lock=settings)


def _dossier(cid="cand-1"):
    return Dossier(
        candidate=Candidate(candidate_id=cid, title=cid, one_liner="x", ambition_tier="micro"),
        decision=Decision.PASS, checks=[], score=None, created_at="2026-08-15T00:00:00+00:00",
    )


class _Store:
    def __init__(self):
        self.saved: list = []

    def save(self, d):
        self.saved.append(getattr(d, "publish_status", None))


def _publisher(monkeypatch, calls, status="published"):
    """Stand in for `publish.publish.publish`, recording every call that reaches it."""
    import sys

    mod = types.ModuleType("publish.publish")

    def _publish(dossier, cfg):
        calls.append(getattr(getattr(dossier, "candidate", None), "candidate_id", "?"))
        return {"status": status}

    mod.publish = _publish
    pkg = sys.modules.get("publish") or types.ModuleType("publish")
    monkeypatch.setitem(sys.modules, "publish", pkg)
    monkeypatch.setitem(sys.modules, "publish.publish", mod)
    return calls


# ---------------------------------------------------------------------------
# The exclusion itself
# ---------------------------------------------------------------------------

def test_a_second_worker_does_not_publish_a_candidate_already_being_published(
        monkeypatch, tmp_path):
    """The whole point. The peer's claim is REAL — taken through the same claim_lock the
    engine uses, not a patched flag — so this fails if the wrap is removed or the purpose
    string drifts."""
    cfg = _cfg(tmp_path)
    calls: list[str] = []
    _publisher(monkeypatch, calls)

    # A peer worker is mid-publish on this candidate.
    peer = claim_lock.for_config(cfg)
    assert peer.claim("cand-1", claim_lock.PUBLISH_PURPOSE) is True

    status = run_mod.publish_and_record(_dossier(), cfg, _Store())

    assert calls == [], "the money step must not run while a peer holds the claim"
    assert status == "skipped_locked"


def test_the_loser_writes_nothing_at_all(monkeypatch, tmp_path):
    """Subtle and load-bearing: the loser must not touch the dossier OR the store.

    The winner is mid-publish holding its own copy of this same row. A `store.save` from the
    loser would overwrite `publish_status='published'` with a status about our own lock — the
    catalogue would then say the pack was never listed while the buyer can buy it, which is the
    same drift class the publish-status field was added to close.
    """
    cfg = _cfg(tmp_path)
    _publisher(monkeypatch, [])
    claim_lock.for_config(cfg).claim("cand-1", claim_lock.PUBLISH_PURPOSE)

    store = _Store()
    d = _dossier()
    run_mod.publish_and_record(d, cfg, store)

    assert store.saved == [], "a refused publish must not write to the store"
    assert d.publish_status is None, "and must not stamp a status on the dossier"


def test_the_claim_is_released_so_the_next_worker_can_publish(monkeypatch, tmp_path):
    """A publish claim that outlived its publish would strand the pack until the stale timer
    expired — an hour by default. `claiming` is a context manager for this reason."""
    cfg = _cfg(tmp_path)
    calls: list[str] = []
    _publisher(monkeypatch, calls)

    assert run_mod.publish_and_record(_dossier(), cfg, _Store()) == "published"
    # Same candidate, second attempt: the first one's claim is gone.
    assert run_mod.publish_and_record(_dossier(), cfg, _Store()) == "published"
    assert calls == ["cand-1", "cand-1"]


def test_the_claim_is_released_when_publishing_RAISES(monkeypatch, tmp_path):
    """The failure path is the one that strands things. `publish_and_record` catches the
    exception itself, but the claim must be freed whichever layer swallows it."""
    import sys
    cfg = _cfg(tmp_path)
    mod = types.ModuleType("publish.publish")

    def _boom(dossier, cfg):
        raise RuntimeError("provisioning died")

    mod.publish = _boom
    monkeypatch.setitem(sys.modules, "publish", sys.modules.get("publish")
                        or types.ModuleType("publish"))
    monkeypatch.setitem(sys.modules, "publish.publish", mod)

    assert run_mod.publish_and_record(_dossier(), cfg, _Store()) == "failed"
    lock = claim_lock.for_config(cfg)
    assert lock.claim("cand-1", claim_lock.PUBLISH_PURPOSE) is True, \
        "a crashed publish must not hold the candidate for an hour"


# ---------------------------------------------------------------------------
# The two claims are different claims
# ---------------------------------------------------------------------------

def test_a_revet_claim_does_not_block_a_publish(monkeypatch, tmp_path):
    """Purpose is part of the key (claim_lock.py:159-166). If it were not, the decay walker's
    re-vet claim would silently block publishing — one shared lock for two unrelated exclusions
    is how a correctness rail becomes a throughput bug."""
    cfg = _cfg(tmp_path)
    calls: list[str] = []
    _publisher(monkeypatch, calls)

    claim_lock.for_config(cfg).claim("cand-1", claim_lock.DEFAULT_PURPOSE)  # "revet"

    assert run_mod.publish_and_record(_dossier(), cfg, _Store()) == "published"
    assert calls == ["cand-1"]


def test_publish_and_revet_purposes_are_distinct_strings():
    """Pinned because a collision is invisible: both claims would still 'work', and the only
    symptom would be publishes and re-vets mysteriously excluding each other."""
    assert claim_lock.PUBLISH_PURPOSE != claim_lock.DEFAULT_PURPOSE


# ---------------------------------------------------------------------------
# Disabled means "as it was", never "nothing may proceed"
# ---------------------------------------------------------------------------

def test_switching_the_rail_off_restores_the_old_behaviour(monkeypatch, tmp_path):
    """`claim_lock.enabled: false` must publish exactly as it did before the rail existed —
    a disabled rail that refuses work is an outage with a config key."""
    cfg = _cfg(tmp_path, enabled=False)
    calls: list[str] = []
    _publisher(monkeypatch, calls)

    assert run_mod.publish_and_record(_dossier(), cfg, _Store()) == "published"
    assert calls == ["cand-1"]


@pytest.mark.parametrize("status", ["error", "skipped", "dry_run", ""])
def test_a_refusal_by_return_value_is_still_recorded_as_failed(monkeypatch, tmp_path, status):
    """The claim wrap must not have changed what the body records. `publish()` reports most
    refusals by RETURN VALUE, not by raising, so 'did not throw' was never evidence."""
    cfg = _cfg(tmp_path)
    _publisher(monkeypatch, [], status=status)

    d = _dossier()
    assert run_mod.publish_and_record(d, cfg, _Store()) == "failed"
    assert d.publish_error and "status=" in d.publish_error
