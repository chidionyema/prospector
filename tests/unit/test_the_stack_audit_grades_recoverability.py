"""The stack audit must ask what could NOT be recovered, not only what is running.

Written 2026-08-20, the day the estate came within one cleanup of destroying the only signing
key that verifies its tracked receipts. The daily audit graded production, CI, deploys, launchd
jobs, workflows, enforcement and worktree drift that morning and said nothing about it, because
every collector in it asked "is this running" and none asked "could we get this back".

These tests pin the recovery question itself. They do not pin the estate's current answer -- the
number of working keys is allowed to change, and should. What may not change is that the audit
keeps asking, keeps telling an unfinished search apart from an empty one, and keeps its hands off
the key material.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "process_audit.py"


def _load():
    spec = importlib.util.spec_from_file_location("process_audit_recov", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["process_audit_recov"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pa():
    return _load()


def test_the_recovery_collector_is_wired_into_the_audit(pa):
    """It must run in main(), not merely exist.

    A collector nobody calls grades nothing, and grades nothing SILENTLY -- which is the exact
    shape of the defect this file was written after.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "def grade_recoverability" in src
    assert '_section("recoverability", grade_recoverability)' in src, (
        "grade_recoverability exists but nothing calls it, so the audit is back to grading "
        "liveness only")


def test_an_unfinished_search_is_not_reported_as_an_empty_one(pa, monkeypatch):
    """A `find` that times out must not read as 'this Mac cannot sign at all'.

    Measured: an unpruned find over either code root timed out at 25s and returned zero keys.
    Zero keys is the loudest alarm this collector has, so without this distinction the audit
    would have screamed every day on an estate holding 78 key files.
    """
    monkeypatch.setattr(pa, "_agent_keys", lambda: ([], ["/some/root"]))
    rows = pa.grade_recoverability()
    assert any(r[0] == pa.WARN and "could not finish searching" in r[2] for r in rows)
    assert not any(r[0] == pa.BAD for r in rows), (
        "an unfinished search must not produce a BAD row -- it proved nothing either way")


def test_an_empty_search_that_DID_finish_is_a_real_alarm(pa, monkeypatch):
    """The other half. No keys, search complete, is a genuine emergency and must be BAD."""
    monkeypatch.setattr(pa, "_agent_keys", lambda: ([], []))
    rows = pa.grade_recoverability()
    assert any(r[0] == pa.BAD for r in rows)


def test_a_single_working_key_inside_a_worktree_is_BAD(pa, monkeypatch, tmp_path):
    """One key, in a directory cleanups are built to remove, is the estate's worst case."""
    key = tmp_path / "wt" / ".claude" / "worktrees" / "agent-x" / ".lux" / "keys" / "agent.pem"
    key.parent.mkdir(parents=True)
    key.write_text("k")
    monkeypatch.setattr(pa, "_agent_keys", lambda: ([key], []))
    monkeypatch.setattr(pa, "_verifies_tracked_seeds", lambda p: True)
    rows = pa.grade_recoverability()
    assert any(r[1] == "signing key location" and r[0] == pa.BAD for r in rows)
    assert any("escrow" in r[1] and r[0] == pa.BAD for r in rows), (
        "a key with no copy outside a code tree has no restore path and must say so")


def test_two_working_keys_are_survivable_and_grade_OK(pa, monkeypatch, tmp_path):
    """The collector must be able to report good news, or nobody will believe its bad news."""
    keys = []
    for n in ("a", "b"):
        k = tmp_path / n / ".lux" / "keys" / "agent.pem"
        k.parent.mkdir(parents=True)
        k.write_text(n)          # distinct bytes -> distinct digests
        keys.append(k)
    monkeypatch.setattr(pa, "_agent_keys", lambda: (keys, []))
    monkeypatch.setattr(pa, "_verifies_tracked_seeds", lambda p: True)
    rows = pa.grade_recoverability()
    assert any(r[1] == "signing keys" and r[0] == pa.OK for r in rows)


def test_identical_copies_are_verified_once_not_once_per_file(pa, monkeypatch, tmp_path):
    """78 files, 23 distinct keys. Verifying per file multiplies a daily job's cost for nothing."""
    keys = []
    for n in range(5):
        k = tmp_path / str(n) / ".lux" / "keys" / "agent.pem"
        k.parent.mkdir(parents=True)
        k.write_text("same bytes everywhere")
        keys.append(k)
    calls: list[Path] = []

    def counting(p):
        calls.append(p)
        return True

    monkeypatch.setattr(pa, "_agent_keys", lambda: (keys, []))
    monkeypatch.setattr(pa, "_verifies_tracked_seeds", counting)
    pa.grade_recoverability()
    assert len(calls) == 1, f"verified {len(calls)} times for 5 byte-identical copies"


def test_the_probe_identifies_a_key_by_digest_and_never_by_value(pa, tmp_path):
    """It must never read, log or return key material -- only a digest of it."""
    k = tmp_path / "agent.pem"
    k.write_bytes(b"super secret bytes")
    d = pa._digest(k)
    assert d == hashlib.sha256(b"super secret bytes").hexdigest()[:12]
    assert "super secret" not in d and len(d) == 12


def test_a_copy_in_a_SIBLING_code_tree_is_not_escrow(pa):
    """Escrow is a question about location, and code trees all die in the same sweep.

    The first version asked "outside a worktree and outside ROOT", which counted
    ~/Documents/code/signalengine/.lux/keys/agent.pem as an escrow copy. That tree is deleted by
    exactly the sweep the escrow exists to survive, so the probe would have reported the estate
    protected on the strength of a copy that dies at the same moment as every other one.
    """
    sibling = pa.CODE_ROOTS[0] / "signalengine" / ".lux" / "keys" / "agent.pem"
    assert pa._is_escrowed(sibling) is False

    other_clone = pa.CODE_ROOTS[1] / "prospector" / ".lux" / "keys" / "agent.pem"
    assert pa._is_escrowed(other_clone) is False


def test_a_worktree_copy_is_not_escrow(pa):
    wt = pa.CODE_ROOTS[0] / "prospector" / ".claude" / "worktrees" / "agent-x" / ".lux" / "keys" / "agent.pem"
    assert pa._is_escrowed(wt) is False


def test_the_escrow_location_counts_as_escrow(pa):
    """And it is outside every code root, which is the property that makes it escrow."""
    assert pa._is_escrowed(pa.ESCROW_DIR / "agent.pem") is True
    assert not any(str(r) in str(pa.ESCROW_DIR) for r in pa.CODE_ROOTS)


def test_the_probe_can_SEE_the_escrow_copy(pa, tmp_path, monkeypatch):
    """A probe that cannot see the escrow reports "no escrow" however correct the estate is.

    The escrow copy is not under `.lux/keys/`, and it is deliberately nowhere near a code tree,
    so neither the search roots nor the path pattern reach it. It has to be added explicitly, and
    a guard that can never go green is worse than no guard.
    """
    escrow = tmp_path / "escrow"
    escrow.mkdir()
    (escrow / "agent.pem").write_bytes(b"x" * 64)
    monkeypatch.setattr(pa, "ESCROW_DIR", escrow)
    monkeypatch.setattr(pa, "CODE_ROOTS", (tmp_path / "nowhere",))
    keys, _unfinished = pa._agent_keys()
    assert (escrow / "agent.pem") in keys


def test_the_one_key_row_states_the_COPY_COUNT_and_does_not_overstate(pa, tmp_path, monkeypatch):
    """The row said "delete it and the commit gate is gone estate-wide with no way back".

    The key had 42 copies when that sentence was written, so no single delete could do it.
    Overstating a real risk is not a safe error: it is the version a reader checks once,
    disproves, and then discounts the rest of the row. This asserts on the row the grader
    EMITS, never on the source text -- a guard that greps its own file grades the comment
    explaining the fix as though it were the defect.
    """
    root = tmp_path / "code"
    a = root / "wt-one" / ".lux" / "keys" / "agent.pem"
    b = root / "wt-two" / ".lux" / "keys" / "agent.pem"
    for f in (a, b):
        f.parent.mkdir(parents=True)
        f.write_bytes(b"k" * 64)

    monkeypatch.setattr(pa, "CODE_ROOTS", (root,))
    monkeypatch.setattr(pa, "ESCROW_DIR", tmp_path / "no-escrow-here")
    monkeypatch.setattr(pa, "_agent_keys", lambda: ([a, b], []))
    monkeypatch.setattr(pa, "_verifies_tracked_seeds", lambda k: True)

    rows = pa.grade_recoverability()
    keyrow = next(r for r in rows if r[1] == "signing keys")

    # Two files, one distinct key, so the row must say two copies -- not "delete it and it is
    # gone", which is what the deduped version could not help saying.
    assert "2 copies" in keyrow[2]
    assert "0 of them outside every code tree" in keyrow[2]
    assert any(r[1] == "key escrow" and r[0] == pa.BAD for r in rows)


def test_an_escrowed_copy_flips_the_escrow_row_to_OK(pa, tmp_path, monkeypatch):
    """And the probe must be able to go green, or it is not a guard, it is a permanent alarm."""
    root = tmp_path / "code"
    intree = root / "wt-one" / ".lux" / "keys" / "agent.pem"
    intree.parent.mkdir(parents=True)
    intree.write_bytes(b"k" * 64)
    escrow = tmp_path / "escrow"
    escrow.mkdir()
    (escrow / "agent.pem").write_bytes(b"k" * 64)

    monkeypatch.setattr(pa, "CODE_ROOTS", (root,))
    monkeypatch.setattr(pa, "ESCROW_DIR", escrow)
    monkeypatch.setattr(pa, "_agent_keys", lambda: ([intree, escrow / "agent.pem"], []))
    monkeypatch.setattr(pa, "_verifies_tracked_seeds", lambda k: True)

    rows = pa.grade_recoverability()
    assert any(r[1] == "key escrow" and r[0] == pa.OK for r in rows)
    assert not any(r[1] == "signing key location" for r in rows)
