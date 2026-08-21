"""The daemon must notice when a pack that was blocked stops being blocked.

`_unlist_pass` pulls a pack off sale the moment a re-vet kills it. Nothing did the reverse.
No tick step re-read an UNLISTED pass, so a pack blocked by a rule that has since been fixed
stayed off the shelf permanently — `tools/verify_pass_shelf_coverage.py:14` records the cost in
one sentence: "Twenty-four had been published UNLISTED and forgotten."

`_regate_pass` is that counterpart. Three properties it must hold, and each is a test below:

1. It selects on the RULES, not on mtime. A linter edit touches no dossier, so every receipt
   stays newer than its pack and mtime freshness says "current" forever.
2. It lists nothing. The rehearsal refreshes a verdict on disk; putting a pack back on sale
   takes money and stays a deliberate act.
3. It self-drains. A re-gate stamps the current ruleset whatever the verdict, so a pack that is
   still blocked drops out of the selection too and the queue converges to empty.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from prospector.pack_linter import RULESET_VERSION
from prospector.scheduler import run_scheduled as rs


class _Cfg:
    def __init__(self, store_dir, **schedule):
        self.store_dir = store_dir
        self.schedule = schedule


def _pack(store: Path, cid: str, receipt: dict | None):
    (store / "dossiers").mkdir(parents=True, exist_ok=True)
    (store / "dossiers" / f"{cid}.pass.json").write_text(json.dumps({"decision": "pass"}))
    if receipt is not None:
        (store / "dossiers" / f"{cid}.lint.json").write_text(json.dumps(receipt))


class TestTheSelectionIsAboutTheRules(unittest.TestCase):
    def test_a_retired_ruleset_is_picked_up(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "a" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            picked = rs._stale_verdicts(_Cfg(str(store)), 10)
            self.assertEqual([p.name for p in picked], ["a" * 16 + ".pass.json"])

    def test_a_pack_nobody_ever_gated_is_picked_up(self):
        """Nine of seventeen republishable PASSes were in this state on 2026-08-09."""
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "b" * 16, None)
            self.assertEqual(len(rs._stale_verdicts(_Cfg(str(store)), 10)), 1)

    def test_a_current_verdict_is_left_alone(self):
        """This is the self-draining property: still-blocked packs drop out too."""
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "c" * 16, {"ok": False, "ruleset": RULESET_VERSION})
            _pack(store, "d" * 16, {"ok": True, "ruleset": RULESET_VERSION})
            self.assertEqual(rs._stale_verdicts(_Cfg(str(store)), 10), [])

    def test_a_retired_verdict_outranks_one_nobody_ever_wrote(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "0" * 16, None)                                     # sorts first
            _pack(store, "z" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            picked = rs._stale_verdicts(_Cfg(str(store)), 1)
            self.assertEqual([p.name for p in picked], ["z" * 16 + ".pass.json"])

    def test_the_bound_is_honoured(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            for i in range(5):
                _pack(store, f"{i}" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            self.assertEqual(len(rs._stale_verdicts(_Cfg(str(store)), 2)), 2)

    def test_an_unreadable_receipt_is_re_gated_rather_than_trusted(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "e" * 16, None)
            (store / "dossiers" / ("e" * 16 + ".lint.json")).write_text("{ truncated")
            self.assertEqual(len(rs._stale_verdicts(_Cfg(str(store)), 10)), 1)


class TestTheStepIsBounded(unittest.TestCase):
    def test_on_by_default(self):
        """ON, because a knob defaulted to off means the stored verdicts stay wrong until
        somebody remembers it — the exact failure this whole change exists to remove."""
        self.assertGreater(rs._regate_per_tick(_Cfg("/nowhere")), 0)

    def test_the_shipped_config_agrees_with_the_code_default(self):
        """A config comment that argues for 2 while the file says 0 is how this drifts."""
        import yaml
        root = Path(__file__).resolve().parents[2]
        shipped = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(shipped["schedule"]["regate_unlisted_per_tick"],
                         rs._REGATE_PER_TICK_DEFAULT)

    def test_a_nonsense_value_falls_back_to_the_default(self):
        self.assertEqual(rs._regate_per_tick(_Cfg("/nowhere", regate_unlisted_per_tick="lots")),
                         rs._REGATE_PER_TICK_DEFAULT)

    def test_zero_still_switches_it_off(self):
        self.assertEqual(rs._regate_per_tick(_Cfg("/nowhere", regate_unlisted_per_tick=0)), 0)

    def test_the_default_batch_fits_the_tool_s_own_concurrency(self):
        """The bound and the fan-out have to be sized together.

        A tick batch costs about `ceil(n / width)` packs of wall clock, not `n`, because
        `publish_passes` gates concurrently on a dry run. Ask for many more than it can gate at
        once and the tick pays for the extra rounds serially — which is what 2-at-a-time and a
        one-at-a-time gate cost before either number was measured.

        `width` is processes TIMES threads, not threads alone. Threads by themselves measured 4x
        against a promised 10x, because a gate is partly Python work and the GIL serialises it.
        """
        import tools.publish_passes as pp
        self.assertLessEqual(rs._REGATE_PER_TICK_DEFAULT, pp._DRY_RUN_PROCS * pp._DRY_RUN_JOBS)

    def test_the_timeout_covers_the_default_batch_with_headroom(self):
        """~124s/pack measured 2026-08-17. One round of the pool, plus room for a slow pack."""
        import math

        import tools.publish_passes as pp
        width = pp._DRY_RUN_PROCS * pp._DRY_RUN_JOBS
        rounds = math.ceil(rs._REGATE_PER_TICK_DEFAULT / width)
        self.assertGreater(rs._REGATE_TIMEOUT_S, 124 * rounds * 2)

    def test_zero_runs_nothing(self):
        with mock.patch.object(rs, "_stale_verdicts") as stale:
            self.assertIsNone(rs._regate_pass(_Cfg("/nowhere"), 0))
        stale.assert_not_called()

    def test_nothing_stale_runs_nothing(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "f" * 16, {"ok": True, "ruleset": RULESET_VERSION})
            self.assertIsNone(rs._regate_pass(_Cfg(str(store)), 5))


class TestItRehearsesAndListsNothing(unittest.TestCase):
    """The whole point of the asymmetry: unlisting unattended can only cost a sale, listing
    unattended takes money from a buyer."""

    def _run(self, store: Path, n: int = 5):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="gate -> ok", stderr="")
            out = rs._regate_pass(_Cfg(str(store)), n)
        return out, run

    def test_the_subprocess_is_a_dry_run(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "a" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            _, run = self._run(store)
            argv = run.call_args[0][0]
            self.assertIn("--dry-run", argv)
            self.assertTrue(argv[1].endswith("tools/publish_passes.py"), argv[1])
            self.assertNotIn("--all", argv)      # only the stale packs, never the catalogue

    def test_it_reports_which_packs_now_clear_the_gate(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "a" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            # The rehearsal is what rewrites the receipt; the mock stands in for it.
            with mock.patch("subprocess.run") as run:
                def _rehearse(*_a, **_k):
                    (store / "dossiers" / ("a" * 16 + ".lint.json")).write_text(
                        json.dumps({"ok": True, "ruleset": RULESET_VERSION}))
                    return mock.Mock(returncode=0, stdout="gate -> ok", stderr="")
                run.side_effect = _rehearse
                out = rs._regate_pass(_Cfg(str(store)), 5)
            self.assertEqual(out["clears_the_gate"], ["a" * 16])
            self.assertEqual(out["regated"], 1)

    def test_a_still_blocked_pack_is_not_reported_as_sellable(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "a" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            out, _ = self._run(store)
            self.assertEqual(out["clears_the_gate"], [])

    def test_a_failed_rehearsal_never_costs_the_tick(self):
        with TemporaryDirectory() as tmp:
            store = Path(tmp)
            _pack(store, "a" * 16, {"ok": False, "ruleset": "a-retired-ruleset"})
            with mock.patch("subprocess.run", side_effect=OSError("no interpreter")):
                out = rs._regate_pass(_Cfg(str(store)), 5)
            self.assertIn("error", out)


class TestTheToolRunsWithoutTheCallersHelp(unittest.TestCase):
    """A tick step shells out. `python tools/publish_passes.py` must therefore work with no
    PYTHONPATH, from any cwd.

    Measured 2026-08-17: it did not. Run as a script, python puts `tools/` on sys.path and not
    the repo root, so the first programmatic caller died in 0.96s on `ModuleNotFoundError: No
    module named 'prospector'` and the tick recorded it as a re-gate failure. Every human
    invocation exported PYTHONPATH, so nothing had ever caught it.
    """

    def test_it_imports_from_a_foreign_cwd_with_no_pythonpath(self):
        import subprocess
        import sys as _sys

        tool = Path(__file__).resolve().parents[2] / "tools" / "publish_passes.py"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run([_sys.executable, str(tool)], capture_output=True, text=True,
                              cwd="/", env=env, timeout=120)
        self.assertNotIn("ModuleNotFoundError", proc.stderr, proc.stderr[-400:])
        self.assertEqual(proc.returncode, 2, "no-args should print usage and return 2")


class TestTheProcessFanOutCannotMint(unittest.TestCase):
    """Splitting the gate across processes is what makes a re-gate finish in minutes. It is also
    the one place this tool could accidentally run the MONEY path several times at once, so the
    two properties below are the fence, and they live in the child's argv where they are
    checkable rather than in a comment.
    """

    def _children(self, paths, **kw):
        import tools.publish_passes as pp
        with mock.patch("subprocess.Popen") as popen:
            popen.return_value = mock.Mock(wait=mock.Mock(return_value=0))
            pp._fan_out_across_processes(paths, procs=kw.pop("procs", 3), jobs=kw.pop("jobs", 2),
                                         force_regate=kw.pop("force_regate", False),
                                         cheap=kw.pop("cheap", False))
        return [c[0][0] for c in popen.call_args_list]

    def test_every_child_is_a_dry_run(self):
        for argv in self._children([f"p{i}.pass.json" for i in range(6)]):
            self.assertIn("--dry-run", argv)

    def test_no_child_can_split_again(self):
        """Without this the split is recursive and one call becomes 64 processes."""
        for argv in self._children([f"p{i}.pass.json" for i in range(6)]):
            self.assertIn("--procs=1", argv)

    def test_every_pack_is_gated_exactly_once(self):
        paths = [f"p{i}.pass.json" for i in range(7)]
        handed = [a for argv in self._children(paths) for a in argv if a.endswith(".pass.json")]
        self.assertEqual(sorted(handed), sorted(paths))

    def test_it_never_starts_more_processes_than_there_is_work(self):
        self.assertEqual(len(self._children(["p0.pass.json"], procs=8)), 1)

    def test_the_child_is_told_not_to_fan_out_again_by_env_too(self):
        import tools.publish_passes as pp
        with mock.patch("subprocess.Popen") as popen:
            popen.return_value = mock.Mock(wait=mock.Mock(return_value=0))
            pp._fan_out_across_processes(["a.pass.json", "b.pass.json"], procs=2, jobs=1,
                                         force_regate=False, cheap=False)
        self.assertEqual(popen.call_args_list[0][1]["env"][pp._CHILD_ENV], "1")


class TestItRidesWithTheUnlistDrain(unittest.TestCase):
    def test_it_runs_even_when_the_decay_sweep_is_off(self):
        """Switching one step off must not strand the other — the same rule the drain has."""
        cfg = _Cfg("/nowhere", regate_unlisted_per_tick=3)
        with mock.patch.object(rs, "_unlist_pass", return_value=None), \
             mock.patch.object(rs, "_regate_pass", return_value={"regated": 3}) as regate:
            out = rs._decay_pass(cfg, 0)
        regate.assert_called_once_with(cfg, 3)
        self.assertEqual(out["regated"], {"regated": 3})


if __name__ == "__main__":
    unittest.main()
