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
