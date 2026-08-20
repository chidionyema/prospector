"""Every receipt the engine container writes must be shipped, and something must grade it.

THE FAILURE THIS EXISTS FOR (measured 2026-08-20)
-------------------------------------------------
Three hand-maintained lists have to agree, and nothing compared them:

  1. `deploy/engine/supervisord.conf` decides which jobs write a receipt onto the Fly volume.
  2. `scripts/engine_failover.py` decides which of those receipts are pulled down to the laptop.
  3. `~/.hermes/capabilities.json` decides which of those are GRADED.

supervisord wrapped four jobs. The shipper named two. So `offsite_backup` and `restore_drill.py`
wrote a receipt every run and nothing ever read it: the offsite backup and the restore drill, the
two jobs whose entire purpose is proving the business can be recovered.

List 2 is gone. `engine_failover.container_receipt_keys()` reads list 1, so those two cannot
disagree any more. This file is what stops list 3 drifting from list 1.

WHAT THIS CANNOT DO
-------------------
`~/.hermes/capabilities.json` is a different repository (chidionyema/hermes-config) and is not
checked out on a CI runner. The coverage test therefore SKIPS where the file is absent, which
means CI does not enforce it and every agent working on this machine does. The parser tests below
have no such dependency and run everywhere, so a broken parser, which would silently ship nothing,
still fails in CI.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SUPERVISORD = REPO / "deploy" / "engine" / "supervisord.conf"
CAPABILITIES = Path.home() / ".hermes" / "capabilities.json"


def _bridge():
    """Import scripts/engine_failover.py by path. It is a script, not an installed module."""
    spec = importlib.util.spec_from_file_location(
        "engine_failover_under_test", REPO / "scripts" / "engine_failover.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- the parser


def test_the_real_conf_yields_every_key_it_wraps():
    """Anti-vacuity. A parser that returns nothing would ship nothing and pass every join test.

    The count is not hardcoded: it is counted a second way, straight out of the file, so adding a
    job does not fail this and deleting the parser's guts does.
    """
    text = SUPERVISORD.read_text(encoding="utf-8")
    by_hand = [
        m.group(1)
        for line in text.splitlines()
        if not line.lstrip().startswith(";")
        for m in [re.search(r"receipt\.sh\s+(\S+)", line)]
        if m
    ]
    assert by_hand, "no receipt.sh-wrapped job in supervisord.conf at all"

    keys = _bridge().container_receipt_keys()
    assert sorted(keys) == sorted(set(by_hand))


def test_a_commented_out_job_writes_no_receipt(tmp_path):
    """The comments in that file discuss the receipt keys BY NAME, so this is not hypothetical."""
    conf = tmp_path / "supervisord.conf"
    conf.write_text(
        "; The receipt.sh key `ghost_job` matches no capability today\n"
        "[program:real]\n"
        "command=/usr/local/bin/receipt.sh real_job python -m thing\n",
        encoding="utf-8")
    assert _bridge().container_receipt_keys(conf) == ("real_job",)


def test_a_key_wrapped_twice_is_fetched_once(tmp_path):
    conf = tmp_path / "supervisord.conf"
    conf.write_text(
        "command=/usr/local/bin/receipt.sh same python -m a\n"
        "command=/usr/local/bin/receipt.sh same python -m b\n"
        "command=/usr/local/bin/receipt.sh other python -m c\n",
        encoding="utf-8")
    assert _bridge().container_receipt_keys(conf) == ("same", "other")


def test_a_missing_conf_returns_nothing_rather_than_raising(tmp_path):
    """The bridge runs unattended every 15 minutes. It must not die on a missing file."""
    assert _bridge().container_receipt_keys(tmp_path / "nope.conf") == ()


# --------------------------------------------------------------------------- the join


@pytest.mark.skipif(not CAPABILITIES.exists(),
                    reason=f"{CAPABILITIES} is in another repository and is not on a CI runner")
def test_every_receipt_the_container_writes_has_a_capability_that_grades_it():
    """The join between the two systems is `observable.script`, matched exactly.

    A receipt nothing grades is worse than no receipt: the job looks instrumented.
    """
    graded = {
        (c.get("observable") or {}).get("script"): c.get("id")
        for c in json.loads(CAPABILITIES.read_text(encoding="utf-8"))["capabilities"]
    }
    produced = _bridge().container_receipt_keys()
    assert produced, "nothing produces a receipt; the parser test above should have caught this"

    ungraded = [k for k in produced if k not in graded]
    assert not ungraded, (
        "these receipt keys are written by deploy/engine/supervisord.conf and no capability in "
        f"{CAPABILITIES} grades them, so the job is instrumented and read by nobody: {ungraded}. "
        "Add a capability with observable.kind 'receipt' and observable.script set to the key."
    )
