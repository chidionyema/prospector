"""ENGINE_AUDIT_2026-08-10: HIGH findings 5-7 and both MEDIUM-HIGH findings.

One test class per finding. Each states the DEFECT (what shipped) before asserting the fix, so a
future reader can tell what the assertion is buying. Where a test would have been vacuous against
the old code it says so explicitly — a regression guard that passes before the fix guards nothing.

Findings 1-4 are covered by the suite that landed with PR #173; this file is findings 5-9.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time
import types

import pytest

from prospector import drain_state
from prospector import run as run_mod
from prospector.dossier import grounded_support
from prospector.errors import ProviderExhaustedError
from prospector.models import Candidate, CheckResult, Decision, Dossier, Verdict


def _thresholds(**kw):
    base = dict(confidence_floor=0.5, min_supported_confidence=0.5,
                min_supported_to_pass=1,
                moat_critical_checks=["value_durability", "incumbency"])
    base.update(kw)
    return types.SimpleNamespace(**base)


def _cfg(**kw):
    return types.SimpleNamespace(thresholds=_thresholds(**kw))


def _check(name, verdict=Verdict.SUPPORTED, conf=0.9):
    return CheckResult(check_name=name, verdict=verdict, confidence=conf, rationale="r")


# ---------------------------------------------------------------------------
# HIGH #5 — a PASS whose publish step failed must not read as a published PASS
# ---------------------------------------------------------------------------
class TestPublishFailureIsRecorded:
    """DEFECT: `run.vet_candidate` caught a publish failure, logged it to
    store/prospector.jsonl (not the interactive stream) and swallowed it. The dossier came back
    normally, the exit code never changed, and NO field in the dossier or the model schema
    recorded whether `store/listings/<id>.json` was ever written. A batch printed PASS for a
    pack that never listed.
    """

    def _pass_dossier(self):
        cand = Candidate(title="T", one_liner="o")
        cand.candidate_id = "cid-publish-outcome"
        return Dossier(candidate=cand, decision=Decision.PASS, checks=[_check("value_durability")])

    def test_a_raising_publish_is_recorded_as_failed(self, monkeypatch):
        d = self._pass_dossier()
        import publish.publish as pp
        monkeypatch.setattr(pp, "publish", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("store API refused the push")))

        status = run_mod.publish_and_record(d, cfg=object())

        assert status == "failed"
        assert d.publish_status == "failed"
        assert "RuntimeError" in d.publish_error
        assert "store API refused the push" in d.publish_error

    def test_a_publish_that_RETURNS_a_refusal_is_also_failed(self, monkeypatch):
        """The half the old code could not have caught even with a broader `except`.

        `publish()` reports most refusals by RETURN VALUE ({"status": "error"|"skipped"|...}),
        never raising — so "it did not throw" was never evidence that anything was listed.
        """
        import publish.publish as pp
        for refusal in ({"status": "error", "reason": "Invalid dossier type"},
                        {"status": "skipped", "reason": "Decision is kill"},
                        {"status": "dry_run"},
                        {}):
            d = self._pass_dossier()
            monkeypatch.setattr(pp, "publish", lambda *a, _r=refusal, **k: _r)
            assert run_mod.publish_and_record(d, cfg=object()) == "failed", refusal
            assert d.publish_status == "failed"
            assert repr(refusal.get("status", "")) in d.publish_error or "unknown" in d.publish_error

    def test_a_real_publish_is_recorded_as_published(self, monkeypatch):
        d = self._pass_dossier()
        import publish.publish as pp
        monkeypatch.setattr(pp, "publish", lambda *a, **k: {"status": "published"})

        assert run_mod.publish_and_record(d, cfg=object()) == "published"
        assert d.publish_status == "published"
        assert d.publish_error is None

    def test_the_outcome_is_RE_SAVED_so_the_persisted_dossier_carries_it(self, monkeypatch):
        """The record only counts if it survives the process. The dossier is saved BEFORE the
        publish attempt, so without a re-save the field would exist and always be None on disk."""
        d = self._pass_dossier()
        import publish.publish as pp
        monkeypatch.setattr(pp, "publish", lambda *a, **k: {"status": "published"})
        saved: list = []
        store = types.SimpleNamespace(save=saved.append)

        run_mod.publish_and_record(d, cfg=object(), store=store)

        assert saved == [d], "the dossier must be re-saved after the publish attempt"
        assert saved[0].publish_status == "published"

    def test_the_outcome_survives_serialisation(self):
        """A field the dossier JSON drops is a field the audit trail does not have."""
        d = self._pass_dossier()
        d.publish_status = "failed"
        d.publish_error = "RuntimeError: boom"
        out = d.to_dict()
        assert out["publish_status"] == "failed"
        assert out["publish_error"] == "RuntimeError: boom"

        fresh = Dossier(candidate=d.candidate, decision=Decision.PASS)
        assert fresh.to_dict()["publish_status"] is None, \
            "never-attempted must be distinguishable from attempted-and-failed"


# ---------------------------------------------------------------------------
# HIGH #6 — Stripe idempotency key must be able to repeat
# ---------------------------------------------------------------------------
class TestStripeIdempotencyKeyCanRepeat:
    """DEFECT: product metadata carried `"bundle_version": datetime.utcnow().isoformat()`, and
    that whole dict is hashed into `create_product`'s idempotency-key fingerprint. So the key
    differed on EVERY call and could never repeat — the one property the method's own docstring
    promises. A network blip after Stripe accepts create_product but before the client sees the
    response, then a retry, mints a permanently orphaned second product.
    """

    def _cand(self, artifacts=None):
        c = Candidate(title="T", one_liner="o")
        c.candidate_id = "cid-money"
        if artifacts is not None:
            c.tags["artifacts"] = artifacts
        return c

    def test_bundle_version_is_stable_across_calls(self):
        from prospector.bridge import _bundle_version
        cand = self._cand({"a": "one"})
        d = types.SimpleNamespace(created_at="2026-08-10T00:00:00Z")
        assert _bundle_version(d, cand) == _bundle_version(d, cand)

    def test_bundle_version_falls_back_to_a_CONTENT_hash_not_a_clock(self):
        """A dossier with no timestamp (hand-fed, older schema) must still be deterministic —
        and must still CHANGE when the pack content changes, exactly like the `name` and
        `description` already inside that fingerprint."""
        from prospector.bridge import _bundle_version
        d = types.SimpleNamespace(created_at="")
        v1 = _bundle_version(d, self._cand({"exec_summary": "v1"}))
        v2 = _bundle_version(d, self._cand({"exec_summary": "v1"}))
        v3 = _bundle_version(d, self._cand({"exec_summary": "CHANGED"}))
        assert v1 == v2 and v1.startswith("sha256:")
        assert v1 != v3, "different pack content must not reuse a key"

    def test_two_identical_publishes_send_stripe_the_SAME_idempotency_key(self):
        """The end-to-end property, through the real key-building code.

        Against the old wall-clock `bundle_version` this assertion FAILS: the two keys differ,
        which is precisely why a retry minted a duplicate instead of replaying.
        """
        from unittest.mock import MagicMock

        from prospector.bridge import StripeProvisioner, _bundle_version

        cand = self._cand({"exec_summary": "stable"})
        dossier = types.SimpleNamespace(created_at="2026-08-10T00:00:00Z")

        keys = []
        for _ in range(2):
            prov = StripeProvisioner.__new__(StripeProvisioner)
            prov._stripe = MagicMock()
            prov._stripe.Product.create.return_value = MagicMock(id="prod_1")
            prov.create_product(
                name=cand.title, description=cand.one_liner,
                metadata={"dossier_ref": "ref", "candidate_id": cand.candidate_id,
                          "pack_id": cand.candidate_id,
                          "bundle_version": _bundle_version(dossier, cand)},
            )
            keys.append(prov._stripe.Product.create.call_args.kwargs["idempotency_key"])

        assert keys[0] == keys[1], (
            "a replayed publish must reuse the Stripe-side product, not mint an orphan")

    def test_the_wall_clock_is_gone_from_the_metadata_builder(self):
        """Direct guard on the defect itself: the publish path no longer reaches for a clock.

        Comment lines are stripped first — the fix's own comment quotes the old
        `datetime.utcnow().isoformat()` to explain what it replaced, and a guard that trips on
        its own documentation is a guard nobody can keep.
        """
        import inspect

        from prospector import bridge
        code = "\n".join(ln for ln in inspect.getsource(bridge.EngineBridge.publish_pass)
                         .splitlines() if not ln.lstrip().startswith("#"))
        assert "datetime.utcnow()" not in code
        assert "_bundle_version(" in code, "the deterministic derivation must be what runs"


# ---------------------------------------------------------------------------
# HIGH #7 — mid-run generation-chain exhaustion must not read as "fewer candidates"
# ---------------------------------------------------------------------------
class TestGenerationChainExhaustionIsVisible:
    """DEFECT: `_one_call` and `_refine_wave` caught `ProviderExhaustedError` with the same bare
    `except Exception` as a bad-JSON parse. A chain that died PARTWAY through a run was absorbed
    into "fewer/unrefined candidates". `run.py`'s "chain exhausted, signal saved" path keys off
    the AGGREGATE `if not candidates:`, so partial exhaustion skipped `_save_pending_signal`
    entirely and the signal was lost.
    """

    def test_a_generation_batch_that_exhausts_writes_to_the_diagnostics_sink(self, cfg):
        class _Exhausted:
            name = "minimax"
            model = "m"

            def complete_json(self, *a, **k):
                raise ProviderExhaustedError("minimax: monthly spend limit reached")

            def complete(self, *a, **k):
                raise ProviderExhaustedError("minimax: monthly spend limit reached")

        diag: dict = {}
        from prospector.generate import generate
        out = generate(_Exhausted(), cfg, signal_text="", k=2,
                       gen_op=_Exhausted(), diagnostics=diag)

        assert out == [], "no brain answered, so there is nothing to return"
        assert diag.get("chain_exhausted") is True, (
            "exhaustion must be reported to the caller, not absorbed into an empty list")
        assert any("spend limit" in e for e in diag["exhaustion_errors"])

    def test_the_sink_is_optional_and_absent_callers_still_work(self, cfg):
        """Backwards compatibility: `diagnostics` defaults to None and nothing may require it."""
        class _Broken:
            name = "x"
            model = "m"

            def complete_json(self, *a, **k):
                raise ValueError("bad json")

            def complete(self, *a, **k):
                raise ValueError("bad json")

        from prospector.generate import generate
        assert generate(_Broken(), cfg, signal_text="", k=2, gen_op=_Broken()) == []

    def test_run_py_saves_the_signal_on_PARTIAL_exhaustion(self):
        """The consequence the sink exists for.

        Source-level, and deliberately so: the surrounding path is a full signal pipeline that
        cannot run offline, and a test that skips in CI guards nothing. The assertion is that
        the partial-exhaustion branch exists, is keyed on the sink, and calls the same
        `_save_pending_signal` the total-exhaustion branch calls.
        """
        import inspect
        src = inspect.getsource(run_mod.run_signal)
        assert '_gen_diag.get("chain_exhausted")' in src, \
            "run.py must branch on the mid-run exhaustion flag"
        i = src.index('_gen_diag.get("chain_exhausted")')
        assert "_save_pending_signal" in src[i:i + 900], \
            "partial exhaustion must save the signal for `generate --resume`, as total does"


# ---------------------------------------------------------------------------
# MEDIUM-HIGH #1 — one definition of source-or-die, two callers
# ---------------------------------------------------------------------------
class TestPublishBackstopMatchesTheDecisionLayer:
    """DEFECT: `EngineBridge.publish_pass`'s backstop required only `n_supported >= 1` against
    `confidence_floor` and never checked `moat_grounded` at all — weaker than the real gate in
    `dossier.build_dossier`. `tools/publish_offline.py` trusts the `"decision"` string in the
    file it is handed (and `publish_passes.reconstruct` hardcodes `Decision.PASS`), so a dossier
    with one incidental supported check cleared a backstop the real gate KILLs as
    `moat_ungrounded`.
    """

    def test_the_bypass_shape_is_now_refused(self):
        """The exact bypass: supported checks exist, but none is the lane's decisive one."""
        cfg = _cfg()
        checks = [_check("pain_reality"), _check("distribution")]
        n_supported, moat_grounded, moat_checks = grounded_support(checks, cfg)
        assert n_supported == 2, "the old guard's only test passes — that was the bypass"
        assert moat_grounded == 0, "and the requirement it never checked fails"
        assert moat_checks == ("value_durability", "incumbency")

    def test_a_genuinely_grounded_pass_still_clears(self):
        cfg = _cfg()
        n_supported, moat_grounded, _ = grounded_support(
            [_check("pain_reality"), _check("incumbency")], cfg)
        assert n_supported == 2 and moat_grounded == 1

    def test_the_gate_is_LANE_aware_not_hardcoded_to_venture(self):
        """Hardcoding the venture moat once made the smb/side_hustle PASS path structurally
        unreachable. The shared function must read the lane's own decisive checks."""
        cfg = _cfg(moat_critical_checks=["buyer_intent"])
        _, moat_grounded, moat_checks = grounded_support([_check("buyer_intent")], cfg)
        assert moat_checks == ("buyer_intent",) and moat_grounded == 1

    def test_confidence_below_the_floor_is_not_grounded(self):
        cfg = _cfg(min_supported_confidence=0.8)
        n, m, _ = grounded_support([_check("incumbency", conf=0.4)], cfg)
        assert (n, m) == (0, 0)

    def test_a_malformed_check_counts_as_ungrounded_rather_than_raising(self):
        """The bridge's caller may be a dossier rebuilt from stored JSON. Fail closed, not loud."""
        broken = types.SimpleNamespace(check_name="incumbency", verdict=None, confidence="?")
        n, m, _ = grounded_support([broken], _cfg())
        assert (n, m) == (0, 0)

    def test_build_dossier_and_the_bridge_read_the_SAME_function(self):
        """Not "both implement the rule" — literally one definition. A second copy is how the
        two drifted in the first place."""
        import inspect

        from prospector import bridge
        from prospector import dossier as dossier_mod
        assert "grounded_support(checks, cfg)" in inspect.getsource(dossier_mod.build_dossier)
        assert "grounded_support(" in inspect.getsource(bridge.EngineBridge.publish_pass)

    def test_the_bridge_refuses_a_moat_ungrounded_dossier_end_to_end(self):
        from unittest.mock import MagicMock, patch

        from prospector.bridge import EngineBridge

        cfg = MagicMock()
        cfg.thresholds.confidence_floor = 0.5
        cfg.thresholds.min_supported_confidence = 0.5
        cfg.thresholds.min_supported_to_pass = 1
        cfg.thresholds.moat_critical_checks = ["value_durability", "incumbency"]

        b = EngineBridge(cfg)
        b.entitlements_check = MagicMock(return_value=True)

        cand = Candidate(title="Bypass Biz", one_liner="one incidental supported check")
        cand.candidate_id = "cid-bypass"
        d = MagicMock(spec=Dossier)
        d.decision = Decision.PASS
        d.candidate = cand
        d.provisional = False
        d.score = None
        d.adversarial = None
        d.gate_fired = None
        d.reason = "r"
        d.model_version = "m"
        d.created_at = "2026-08-10T00:00:00Z"
        d.checks = [_check("pain_reality")]  # supported, but NOT the lane's decisive check

        with patch("requests.post") as post:
            assert b.publish_pass(d) is False
            post.assert_not_called()


# ---------------------------------------------------------------------------
# MEDIUM-HIGH #2 — the drain attempt ledger's read-modify-write is cross-process racy
# ---------------------------------------------------------------------------
# A cross-process test needs real processes, and `multiprocessing` cannot supply them under
# pytest. spawn's child re-imports `sys.modules["__main__"]` via `_fixup_main_from_path` — and
# `__main__` here is the pytest console script, so the child re-enters pytest and dies in
# spawn.py before running the worker at all. The parent's `_handle_results` thread then blocks
# forever in `connection.recv()`: no error, no output, just a hang. Measured 2026-08-10: this
# ONE test consumed the POPDD gate's entire 1800s ceiling while the other 2875 tests passed in
# 484s, and the gate could only report "step 'pytest' exceeded 1800s" without naming it.
# `subprocess` has no `__main__` to fix up, so it is immune to the start method entirely.
_CHILD_SRC = """
import os, sys, time
sys.path.insert(0, sys.argv[1])
from prospector import drain_state as ds

store_dir, cid, n, ready, go = (
    sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6])

# Import first, THEN signal ready: interpreter startup and the prospector import are seconds of
# jitter, and a barrier released before them would serialise the very contention under test.
open(ready, "w").close()
deadline = time.monotonic() + 60
while not os.path.exists(go):
    if time.monotonic() > deadline:
        raise SystemExit("child never saw the barrier release")
    time.sleep(0.005)

for _ in range(n):
    ds.record_unresolved(store_dir, cid)
"""


class TestDrainLedgerIsCrossProcessSafe:
    """DEFECT: `record_unresolved` was `load() -> +1 -> _write()` with no mutex. Each write is
    crash-atomic on its own, which is a DIFFERENT property: two processes that read `3`
    concurrently both write `4` and one attempt vanishes. Both callers are real and concurrent —
    the daemon's automatic drain and a manual `vet --resume` against the same store.

    A lost increment means a stuck row needs more than `max_resume_attempts` real attempts before
    it leaves the backlog count, quietly re-engaging the generation freeze that "gate on the
    rate, not the stock" exists to avoid. `threading.Lock` cannot fix it (one lock object per
    process) — the same mistake the audit found in `health._claim_probe`.
    """

    def test_concurrent_processes_lose_no_increments(self, tmp_path):
        procs, per_proc = 6, 12
        repo_root = str(pathlib.Path(__file__).resolve().parents[2])
        gate = tmp_path / "barrier"
        gate.mkdir()
        go = gate / "GO"

        children = []
        try:
            for i in range(procs):
                ready = gate / f"ready-{i}"
                children.append((ready, subprocess.Popen(
                    [sys.executable, "-c", _CHILD_SRC, repo_root, str(tmp_path), "cid-race",
                     str(per_proc), str(ready), str(go)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))

            # Every bound here is explicit. A child that dies early fails this loop by name
            # instead of hanging the suite — the whole point of not using a Pool.
            deadline = time.monotonic() + 60
            while not all(r.exists() for r, _ in children):
                dead = [p for _, p in children if p.poll() not in (None, 0)]
                assert not dead, (
                    "child exited before the barrier: "
                    + (dead[0].communicate()[1] or "").strip())
                assert time.monotonic() < deadline, "children never reached the barrier"
                time.sleep(0.01)

            go.touch()  # release all six into the read-modify-write at once
            for _, p in children:
                _out, err = p.communicate(timeout=120)
                assert p.returncode == 0, f"child failed ({p.returncode}): {err.strip()}"
        finally:
            for _, p in children:
                if p.poll() is None:
                    p.kill()

        total = drain_state.load(tmp_path).get("cid-race", 0)
        assert total == procs * per_proc, (
            f"lost {procs * per_proc - total} of {procs * per_proc} increments to the race")

    def test_the_lock_degrades_to_a_no_op_rather_than_crashing(self, tmp_path, monkeypatch):
        """A filesystem or platform without flock must keep the pre-existing (racy) behaviour,
        never take the drain down with it."""
        import builtins
        real_open = builtins.open

        def _no_lockfile(path, *a, **k):
            if str(path).endswith(".lock"):
                raise OSError("no locks on this filesystem")
            return real_open(path, *a, **k)

        monkeypatch.setattr(builtins, "open", _no_lockfile)
        assert drain_state.record_unresolved(tmp_path, "cid-nolock") == 1

    def test_single_process_counting_is_unchanged(self, tmp_path):
        for expected in (1, 2, 3):
            assert drain_state.record_unresolved(tmp_path, "cid-plain") == expected
        drain_state.forget(tmp_path, "cid-plain")
        assert drain_state.load(tmp_path).get("cid-plain", 0) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
