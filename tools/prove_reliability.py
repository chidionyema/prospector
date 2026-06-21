#!/usr/bin/env python3
"""Prove the moat + daemon are RELIABLE — with runtime artifacts, not passing assertions.

The failure that burned us (2026-06-21) was silent: a dead EXA_API_KEY made
`ExaSearchProvider` return [] instead of raising, the FallbackSearchProvider read [] as
"searched, found nothing, success" and never failed over, and every check came back
`unverifiable` for HOURS with no alert. Unit tests pass in isolation; this harness drives the
REAL classes end-to-end and prints a PASS/FAIL receipt for each reliability claim. Exits nonzero
if any claim fails — so it can gate a deploy.

    python -m tools.prove_reliability          # or: python tools/prove_reliability.py

Claims:
  R1  Live grounding         real provider chain returns cited passages for a real query
  R2  Failover on death      a RAISING exa falls over to the next provider (the durable fix)
  R3  Outage => DEFER         all-providers-down makes run_check retrieval_failed (re-vet), not a
                              hollow confident verdict masquerading as evidence
  R4  Alert path live         a real bad tick writes a real alert to alerts.jsonl + ALERT.txt
  R5  Watchdog catches death  a stale/missing heartbeat makes the watchdog emit CRITICAL (rc=1)
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

# Allow running as a bare script (python tools/prove_reliability.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prospector.config import load_config
from prospector.errors import ProviderExhaustedError
from prospector.models import Candidate, Verdict
from prospector.retrieval import (ExaSearchProvider, FallbackSearchProvider,
                                  SearchProvider, make_provider)
from prospector.scheduler import alerts as alerts_mod
from prospector.scheduler import run_scheduled as rs
from prospector import verify as verify_mod

_RESULTS: list[tuple[str, bool, str]] = []


def record(claim: str, ok: bool, detail: str) -> None:
    _RESULTS.append((claim, ok, detail))
    mark = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    print(f"  [{mark}] {claim}: {detail}")


class _Down(SearchProvider):
    """A provider that is DOWN — every call raises, like a real outage."""
    def __init__(self, name="down"):
        self.name, self.calls = name, 0
    def search(self, query, k=4, max_chars=1500):
        self.calls += 1
        raise RuntimeError(f"{self.name} transport error (simulated outage)")


class _Live(SearchProvider):
    """A backup provider that is healthy and returns one grounded passage."""
    def __init__(self):
        self.calls = 0
    def search(self, query, k=4, max_chars=1500):
        from prospector.models import Source
        self.calls += 1
        return [Source.make(url="https://example.com/backup",
                            text="backup provider grounded passage", query=query)]


def r1_live_grounding(cfg) -> None:
    """The real configured chain (exa first) must return cited passages right now."""
    try:
        provider = make_provider(cfg)
        srcs = provider.search("UK SME cloud accounting software market size", k=3)
        grounded = [s for s in srcs if (s.text or "").strip() and str(s.url).startswith("http")]
        ok = len(grounded) >= 1
        detail = (f"{len(grounded)} cited passage(s); e.g. {grounded[0].url}"
                  if ok else f"NO grounded passages (got {len(srcs)} raw) — moat is dark")
        record("R1 live grounding", ok, detail)
    except Exception as e:
        record("R1 live grounding", False, f"chain raised: {type(e).__name__}: {e}")


def r2_failover_on_death(cfg, monkeypatch_exa) -> None:
    """A RAISING exa must fall over to the next provider (was: returned [] -> silent stop)."""
    monkeypatch_exa()  # poison exa_py.Exa so ExaSearchProvider.search() raises
    exa = ExaSearchProvider()
    backup = _Live()
    fb = FallbackSearchProvider([("exa", exa), ("backup", backup)])
    try:
        out = fb.search("any query", k=2)
        ok = len(out) >= 1 and backup.calls == 1
        detail = (f"exa raised -> failed over to backup ({len(out)} passage); chain stayed grounded"
                  if ok else f"did NOT fail over (out={len(out)}, backup.calls={backup.calls})")
        record("R2 failover on death", ok, detail)
    except Exception as e:
        record("R2 failover on death", False, f"chain raised instead of failing over: {e}")


def r3_outage_defers(cfg) -> None:
    """All providers down: run_check must DEFER (retrieval_failed), not emit a hollow verdict."""
    down_chain = FallbackSearchProvider([("exa", _Down("exa")), ("brave", _Down("brave"))])
    cand = Candidate(title="Reliability probe idea",
                     hypothesis="A probe candidate used only to exercise the outage path.",
                     who_pays="nobody (probe)")
    check_name = (cfg.retrieval.template_checks or ["pain_reality"])[0]
    try:
        # op is never reached: zero passages short-circuits before the verdict LLM call.
        res = verify_mod.run_check(op=object(), search=down_chain, cfg=cfg,
                                   cand=cand, check_name=check_name)
        ok = (res.retrieval_failed and res.verdict == Verdict.UNVERIFIABLE
              and res.confidence == 0.0)
        detail = (f"outage -> retrieval_failed={res.retrieval_failed}, verdict={res.verdict.name}, "
                  f"conf={res.confidence} (will DEFER + re-vet, not a false ruling)"
                  if ok else
                  f"outage NOT flagged as deferrable: retrieval_failed={res.retrieval_failed}, "
                  f"verdict={res.verdict.name}, conf={res.confidence}")
        record("R3 outage => DEFER", ok, detail)
    except ProviderExhaustedError:
        # Equally valid: the moat refused to rule rather than fabricate one.
        record("R3 outage => DEFER", True, "outage raised ProviderExhaustedError -> caller DEFERs")
    except Exception as e:
        record("R3 outage => DEFER", False, f"unexpected error: {type(e).__name__}: {e}")


def r4_alert_path_live() -> None:
    """A real zero-yield tick must land in the real alert sinks (not just the pure classifier)."""
    with tempfile.TemporaryDirectory() as td:
        cfg = types.SimpleNamespace(store_dir=td)
        tick = {"allowed": True, "dry_run": False, "error": None,
                "result": {"dossiers": 5, "passes": 0}, "ts": "2026-06-21T00:00:00+00:00"}
        rs._emit_tick_alerts(cfg, tick)
        jsonl = Path(td) / "scheduler" / "alerts.jsonl"
        alert_txt = Path(td) / "scheduler" / "ALERT.txt"
        body = jsonl.read_text() if jsonl.exists() else ""
        ok = "zero_yield" in body and alert_txt.exists()
        detail = ("zero_yield alert written to alerts.jsonl + ALERT.txt (real sinks fired)"
                  if ok else f"alert NOT delivered (jsonl exists={jsonl.exists()})")
        record("R4 alert path live", ok, detail)


def r5_watchdog_catches_death() -> None:
    """A missing heartbeat must make the watchdog return 1 and emit a CRITICAL alert."""
    with tempfile.TemporaryDirectory() as td:
        cfg = types.SimpleNamespace(store_dir=td)
        rc = rs._run_watchdog(cfg)  # no heartbeat at all => daemon is down
        jsonl = Path(td) / "scheduler" / "alerts.jsonl"
        body = jsonl.read_text() if jsonl.exists() else ""
        ok = rc == 1 and "critical" in body.lower() and "DOWN" in body
        detail = ("missing heartbeat -> rc=1 + CRITICAL 'daemon DOWN' alert"
                  if ok else f"watchdog did not flag death (rc={rc})")
        record("R5 watchdog catches death", ok, detail)


def _make_exa_poisoner():
    """Return a fn that replaces exa_py.Exa with one whose .search raises (no real network)."""
    import exa_py

    class _BoomExa:
        def __init__(self, *a, **k):
            pass
        def search(self, *a, **k):
            raise RuntimeError("401 unauthorized (simulated dead EXA_API_KEY)")

    def poison():
        exa_py.Exa = _BoomExa
    return poison


def main() -> int:
    print("=" * 72)
    print("PROSPECTOR RELIABILITY PROOF — driving real classes, not unit stubs")
    print("=" * 72)
    cfg = load_config()
    print(f"  config: provider chain = {cfg.retrieval.provider}")
    print()

    # R1 must run against the UNPOISONED exa, before R2 poisons the module.
    r1_live_grounding(cfg)
    r2_failover_on_death(cfg, _make_exa_poisoner())
    r3_outage_defers(cfg)
    r4_alert_path_live()
    r5_watchdog_catches_death()

    print()
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    total = len(_RESULTS)
    allgreen = passed == total
    banner = "\033[32m" if allgreen else "\033[31m"
    print(f"{banner}RELIABILITY: {passed}/{total} claims proven\033[0m")
    if not allgreen:
        print("  Failing claims:")
        for claim, ok, detail in _RESULTS:
            if not ok:
                print(f"    - {claim}: {detail}")
    return 0 if allgreen else 1


if __name__ == "__main__":
    raise SystemExit(main())
