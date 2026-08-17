"""A launchd job must not resolve the store next to the code it runs.

Production runs from a checkout that rolls forward with origin/main. The catalogue, ledger,
dossiers and provider health stay in one canonical store, pinned by PROSPECTOR_STORE_DIR.
When the pin is missing the store follows the code, and the two halves cannot see each other.

Measured 2026-08-17. Four jobs were moved onto the live checkout. One of them,
com.prospector.watchdog, ended up with TWO EnvironmentVariables blocks: a script inserted the
pin at the top of a file that already had a block further down. plistlib keeps the LAST
repeated key and reports nothing, `plutil -lint` said OK, and the pin was dead. The watchdog
then read prospector-live/store/scheduler/heartbeat.json, found nothing, exited 1, and sent a
critical Telegram alert saying the generation daemon had never run -- while it was running.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "launchd_plists.py"

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n')
TAIL = "</dict>\n</plist>\n"


def _plist(label, *, cwd, env_blocks):
    body = ["<key>Label</key><string>com.prospector.%s</string>" % label,
            "<key>WorkingDirectory</key><string>%s</string>" % cwd]
    for block in env_blocks:
        body.append("<key>EnvironmentVariables</key>\n<dict>\n%s\n</dict>" % "\n".join(
            "<key>%s</key><string>%s</string>" % kv for kv in block.items()))
    return HEAD + "\n".join(body) + "\n" + TAIL


def _load():
    spec = importlib.util.spec_from_file_location("launchd_plists", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def lp(tmp_path, monkeypatch):
    if not SCRIPT.exists():
        pytest.skip("scripts/launchd_plists.py is not in this checkout")
    mod = _load()
    monkeypatch.setattr(mod, "LIVE", tmp_path)
    return mod


def _write(lp, label, **kw):
    (lp.LIVE / ("com.prospector.%s.plist" % label)).write_text(_plist(label, **kw))


CANON = "/canonical/prospector/store"
LIVE_CHECKOUT = "/code/prospector-live"


class TestTheStorePinIsChecked:
    def test_a_correctly_pinned_job_is_clean(self, lp):
        """The control: without this, every other case could pass by always faulting."""
        _write(lp, "scheduler", cwd=LIVE_CHECKOUT,
               env_blocks=[{"PROSPECTOR_STORE_DIR": CANON}])
        assert lp.store_pin_faults() == []

    def test_a_missing_pin_is_a_fault(self, lp):
        _write(lp, "watchdog", cwd=LIVE_CHECKOUT, env_blocks=[{"PATH": "/usr/bin"}])
        faults = lp.store_pin_faults()
        assert len(faults) == 1 and "no PROSPECTOR_STORE_DIR" in faults[0]

    def test_no_environment_block_at_all_is_a_fault(self, lp):
        _write(lp, "backup", cwd=LIVE_CHECKOUT, env_blocks=[])
        assert any("no PROSPECTOR_STORE_DIR" in f for f in lp.store_pin_faults())

    def test_a_store_inside_the_jobs_own_checkout_is_a_fault(self, lp):
        """The defect this exists to stop: state that follows the code."""
        _write(lp, "consumer", cwd=LIVE_CHECKOUT,
               env_blocks=[{"PROSPECTOR_STORE_DIR": LIVE_CHECKOUT + "/store"}])
        assert any("inside its own checkout" in f for f in lp.store_pin_faults())

    def test_jobs_disagreeing_on_the_store_is_a_fault(self, lp):
        _write(lp, "scheduler", cwd=LIVE_CHECKOUT,
               env_blocks=[{"PROSPECTOR_STORE_DIR": CANON}])
        _write(lp, "consumer", cwd=LIVE_CHECKOUT,
               env_blocks=[{"PROSPECTOR_STORE_DIR": "/somewhere/else/store"}])
        assert any("disagree on which store" in f for f in lp.store_pin_faults())


class TestARepeatedKeyIsReported:
    def test_two_environment_blocks_are_a_fault_even_though_plistlib_accepts_it(self, lp):
        """The watchdog's actual shape: a pin in a block that the next block deletes."""
        _write(lp, "watchdog", cwd=LIVE_CHECKOUT, env_blocks=[
            {"PROSPECTOR_STORE_DIR": CANON},
            {"PATH": "/usr/bin"},
        ])
        faults = lp.store_pin_faults()
        assert any("appears twice" in f for f in faults), faults
        # And the consequence is caught too: the surviving block has no pin.
        assert any("no PROSPECTOR_STORE_DIR" in f for f in faults), faults

    def test_a_single_block_is_not_reported_as_repeated(self, lp):
        _write(lp, "scheduler", cwd=LIVE_CHECKOUT,
               env_blocks=[{"PROSPECTOR_STORE_DIR": CANON, "PATH": "/usr/bin"}])
        assert lp.store_pin_faults() == []
