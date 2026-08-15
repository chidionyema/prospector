"""A call that BROKE must not look like a call that found nothing.

Every case below pins the same distinction, in the four places the 2026-08-15 swallow audit
found it collapsed inside this module group. The shape of each test is deliberate: it runs the
BROKEN path and the LEGITIMATELY-EMPTY path through the same function and asserts the caller
can tell them apart. A test that only asserted "the broken path returns []" would pass against
the defect itself.
"""
from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# generate.py — a generation batch that raised vs a wave with no ideas
# ---------------------------------------------------------------------------
class _Op:
    """An operator whose JSON call is scripted by the test."""

    name = "minimax"
    model = "m"

    def __init__(self, exc: Exception | None = None, payload=None):
        self._exc = exc
        self._payload = payload if payload is not None else {"opportunities": []}

    def complete_json(self, *a, **k):
        if self._exc is not None:
            raise self._exc
        return self._payload

    def complete(self, *a, **k):
        return self.complete_json(*a, **k)


class TestAFailedGenerationBatchIsNotABarrenWave:
    """DEFECT (`generate.py:491`): a batch that threw returned the same `[]` as a batch the
    model had nothing to say for, so a broken generation call was recorded as a thin wave and
    the signal was never saved for `generate --resume`. Zero-yield has been root-caused six
    times in this engine on exactly that ambiguity."""

    def test_a_batch_that_raises_is_flagged_to_the_caller(self, cfg):
        from prospector.generate import generate

        diag: dict = {}
        out = generate(_Op(exc=ValueError("bad json")), cfg, signal_text="", k=2,
                       gen_op=_Op(exc=ValueError("bad json")), diagnostics=diag)

        assert out == []
        assert diag.get("batch_failures", 0) >= 1, (
            "a generation call that raised must reach the caller's sink")
        assert any("bad json" in e for e in diag.get("batch_errors", []))

    def test_a_wave_that_simply_produced_nothing_is_not_flagged(self, cfg):
        """THE DISCRIMINATOR. Same empty return, and the sink must stay clean."""
        from prospector.generate import generate

        diag: dict = {}
        out = generate(_Op(payload={"opportunities": []}), cfg, signal_text="", k=2,
                       gen_op=_Op(payload={"opportunities": []}), diagnostics=diag)

        assert out == []
        assert not diag.get("batch_failures"), (
            "a model with no ideas is not a failure and must not be reported as one")
        assert not diag.get("chain_exhausted")


class TestALaneThatDiedIsNotALaneWithNoIdeas:
    """DEFECT (`generate.py:877`): one lane raising wrote `[]` into its result slot and logged
    at WARNING. With a sibling lane producing survivors, run.py's aggregate `if not candidates`
    could not see it."""

    def test_a_lane_that_raises_is_flagged_while_a_quiet_lane_is_not(self, monkeypatch):
        from prospector import generate as gen_mod

        def _fake_generate(op, lane_cfg, **kwargs):
            if getattr(lane_cfg, "tier", "") == "broken":
                raise RuntimeError("lane blew up")
            return []

        monkeypatch.setattr(gen_mod, "generate", _fake_generate)
        cfg = SimpleNamespace(for_lane=lambda t: SimpleNamespace(tier=t))

        diag: dict = {}
        out = gen_mod.generate_multilane(
            object(), cfg, lanes=["broken", "quiet"], diagnostics=diag)

        assert out == []
        assert diag.get("lane_failures") == 1, "exactly the lane that raised is reported"
        assert any("lane blew up" in e for e in diag.get("batch_errors", []))


# ---------------------------------------------------------------------------
# run.py — a signal that could not be queued is not a signal that was queued
# ---------------------------------------------------------------------------
class TestALostSignalIsNeverSilent:
    """DEFECT (`run.py:1096/1106`): `_save_pending_signal` returns None on a failed write and
    every caller discarded it, so "signal saved for `generate --resume`" printed either way."""

    def test_a_failed_queue_write_logs_the_signal_text_at_critical(self, monkeypatch, caplog):
        from prospector import run as run_mod

        monkeypatch.setattr(run_mod, "_save_pending_signal", lambda *a, **k: None)
        with caplog.at_level(logging.CRITICAL):
            assert run_mod._save_pending_signal_or_shout("carer rota chaos", object()) is None
        assert any(r.levelno >= logging.CRITICAL and "carer rota chaos" in r.getMessage()
                   for r in caplog.records), (
            "the only surviving copy of a lost signal is the log line")

    def test_a_successful_queue_write_shouts_nothing(self, monkeypatch, caplog):
        from pathlib import Path

        from prospector import run as run_mod

        monkeypatch.setattr(run_mod, "_save_pending_signal", lambda *a, **k: Path("/tmp/x.json"))
        with caplog.at_level(logging.CRITICAL):
            assert run_mod._save_pending_signal_or_shout("s", object()) == Path("/tmp/x.json")
        assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]

    def test_run_signal_saves_the_signal_when_a_batch_merely_FAILED(self):
        """Source-level, like the partial-exhaustion guard beside it: the surrounding path is a
        full signal pipeline that cannot run offline. The assertion is that the branch exists,
        keys off the new sink, and reaches the same saver."""
        import inspect

        from prospector import run as run_mod

        src = inspect.getsource(run_mod.run_signal)
        assert '_gen_diag.get("batch_failures")' in src
        i = src.index('_gen_diag.get("batch_failures")')
        assert "_save_pending_signal" in src[i:i + 900]


class TestAnUnreadableCatalogueIsNotAnEmptyOne:
    """DEFECT (`run.py:2600`): any exception from `markets_present()` printed a table of zeros —
    a confident count — for a catalogue nobody could read."""

    @staticmethod
    def _cfg():
        return SimpleNamespace(
            default_market="uk",
            markets={"uk": {}, "us": {}, "default": {}},
            market_config=lambda c: {"label": c.upper()},
            market_status=lambda c: "open",
        )

    def _run(self, monkeypatch, capsys, present):
        from prospector import run as run_mod

        monkeypatch.setattr(run_mod, "Store",
                            lambda cfg: SimpleNamespace(markets_present=present))
        run_mod._cmd_markets(SimpleNamespace(markets_action="list"), self._cfg(), None)
        return capsys.readouterr()

    def test_a_broken_catalogue_prints_a_question_mark_not_a_zero(self, monkeypatch, capsys):
        def _boom():
            raise sqlite3.OperationalError("database disk image is malformed")

        out = self._run(monkeypatch, capsys, _boom)
        assert "?" in out.out and "unreadable" in out.err

    def test_a_genuinely_empty_catalogue_still_prints_zero(self, monkeypatch, capsys):
        out = self._run(monkeypatch, capsys, dict)
        assert "0" in out.out and "unreadable" not in out.err


# ---------------------------------------------------------------------------
# pack_data.py — "no price anchor exists" is a finding; a crash is not
# ---------------------------------------------------------------------------
class TestABrokenAnchorReadIsNotAnAbsenceOfAnchors:
    """DEFECT (`pack_data.py:768`): a crash reading the stashed anchors returned `[]`, and the
    comparables artifact then told the buyer no anchor was found — a claim about the web made
    out of our own failure."""

    def test_a_crash_propagates_instead_of_asserting_no_anchors(self, monkeypatch):
        from prospector import pack_data, price_comparables

        def _boom(_cand):
            raise TypeError("anchors_from_tags refactored")

        monkeypatch.setattr(price_comparables, "anchors_from_tags", _boom)
        with pytest.raises(TypeError):
            pack_data._anchors_for(SimpleNamespace(tags={}))

    def test_a_candidate_with_no_anchors_still_yields_an_empty_list(self, monkeypatch):
        from prospector import pack_data, price_comparables

        monkeypatch.setattr(price_comparables, "anchors_from_tags", lambda _c: [])
        assert pack_data._anchors_for(SimpleNamespace(tags={})) == []

    def test_a_dossier_whose_sources_raise_does_not_read_as_sourceless(self):
        from prospector import pack_data

        class _Dossier:
            @property
            def all_sources(self):
                raise RuntimeError("index unavailable")

        with pytest.raises(RuntimeError):
            pack_data._sources_for(_Dossier())
        assert pack_data._sources_for(SimpleNamespace(all_sources=[])) == []


# ---------------------------------------------------------------------------
# denylist.py / artifacts.py — the quiet ones
# ---------------------------------------------------------------------------
class TestTheDenylistSaysSoWhenItBreaks:
    """DEFECT (`denylist.py:167`): every failure logged at WARNING and returned `[]`, which is
    also what "no family qualifies" returns."""

    @staticmethod
    def _cfg(tmp_path):
        return SimpleNamespace(
            generation={"denylist": {"enabled": True, "min_family_size": 3,
                                     "refresh_every_kills": 25, "max_families": 12}},
            store_dir=str(tmp_path),
        )

    def test_a_broken_store_is_logged_at_error_with_a_traceback(self, tmp_path, caplog):
        """The empty list STAYS — the module may never raise into generation
        (tests/unit/test_denylist.py:233) — so the log level is the whole distinction."""
        from prospector import denylist

        class _Store:
            def all(self, **k):
                raise sqlite3.OperationalError("no such table: dossiers")

        with caplog.at_level(logging.WARNING):
            assert denylist.refresh_families(_Store(), self._cfg(tmp_path)) == []
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "a lost denial list must be an ERROR, not a WARNING in the chatter"
        assert errors[0].exc_info, "and it must carry the traceback that names the cause"

    def test_a_store_with_no_families_logs_no_error(self, tmp_path, caplog):
        """THE DISCRIMINATOR: the same `[]`, and nothing above INFO."""
        from prospector import denylist

        class _Store:
            def all(self, **k):
                return []

        with caplog.at_level(logging.WARNING):
            assert denylist.refresh_families(_Store(), self._cfg(tmp_path)) == []
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


class TestACurrencyRuleThatBrokeIsNotAMarketlessCandidate:
    """DEFECT (`artifacts.py:897`): a broad except made a failure in the linter's currency table
    indistinguishable from "this candidate declares no market" — and the pack is then refused at
    publish for a symbol the generator was never told to use."""

    def test_a_broken_lookup_propagates(self, monkeypatch, cfg):
        from prospector import artifacts, pack_linter

        monkeypatch.setattr(pack_linter, "expected_currency",
                            lambda m: (_ for _ in ()).throw(TypeError("table changed")))
        with pytest.raises(TypeError):
            artifacts._currency_rule(cfg, SimpleNamespace(market="uk"))

    def test_an_unmapped_market_is_still_a_quiet_empty_rule(self, cfg):
        from prospector import artifacts

        assert artifacts._currency_rule(cfg, SimpleNamespace(market="atlantis")) == ""
        assert artifacts._currency_rule(cfg, SimpleNamespace(market="")) == ""
