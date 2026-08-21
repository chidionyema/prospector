"""The engine's stop budget must be big enough for the shutdown the image asks for.

Found 2026-08-21. `deploy/engine/fly.toml` set neither `kill_signal` nor `kill_timeout`, so
Fly used its defaults: SIGINT, then SIGKILL five seconds later. PID 1 in that image is
supervisord, which forwards the signal to eleven programs and waits for each one. The
graceful path could not finish inside five seconds, so every deploy ended by force-killing
the whole microVM.

That is not a tidiness problem. `store/prospector.jsonl` is the spend ledger the daily cap
is computed from, and it is written by a stdlib logging handler that flushes to the OS and
never calls fsync. When a microVM is killed the page cache is never synced, but the inode
size has already grown past the data that reached disk, so the filesystem hands back NUL
bytes for the missing extent. Measured on the restored R2 copy: 43 NUL holes, each one
immediately followed by a `consumer: starting` line. Zero on 16-17 August, 15 in 18 starts
on the 21st.

These assertions are about the RELATIONSHIP between two files that are edited by different
people for different reasons. Raising a `stopwaitsecs` past Fly's budget silently restores
the original defect, and nothing else in the suite would notice.
"""
from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLY = ROOT / "deploy" / "engine" / "fly.toml"
SUPERVISORD = ROOT / "deploy" / "engine" / "supervisord.conf"

_DURATION = re.compile(r"^\s*(\d+)\s*(ms|s|m|h)\s*$")
_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def _seconds(value: str) -> float:
    """Fly writes durations as a number plus a unit. Nothing else is accepted here, because
    a bare `45` is a value Fly rejects at deploy time and a test that tolerates it lets a
    broken config reach the point where the deploy fails instead of the commit."""
    match = _DURATION.match(str(value))
    assert match, f"{value!r} is not a Fly duration like '45s'"
    return int(match.group(1)) * _UNITS[match.group(2)]


@pytest.fixture(scope="module")
def fly() -> dict:
    return tomllib.loads(FLY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def supervisord() -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser()
    parser.read_string(SUPERVISORD.read_text(encoding="utf-8"))
    return parser


def test_the_machine_is_given_an_explicit_stop_budget(fly):
    """Absent means five seconds, and five seconds is the defect."""
    assert "kill_timeout" in fly, (
        "deploy/engine/fly.toml sets no kill_timeout, so Fly SIGKILLs the machine five "
        "seconds after the stop signal -- shorter than this image's own shutdown"
    )
    assert _seconds(fly["kill_timeout"]) > 5.0, (
        "a kill_timeout of five seconds or less is the Fly default written out longhand"
    )


def test_the_stop_signal_is_the_one_the_consumer_catches(fly):
    """`prospector/consumer.py` installs its handler on SIGTERM and SIGINT. Fly's default is
    SIGINT; naming SIGTERM here matches supervisord's own default stopsignal for children, so
    one signal travels the whole way down."""
    assert fly.get("kill_signal") == "SIGTERM", fly.get("kill_signal")


def test_the_consumer_is_told_how_to_stop(supervisord):
    section = "program:consumer"
    assert supervisord.has_section(section), "the consumer program is gone from supervisord.conf"
    assert supervisord.get(section, "stopsignal", fallback=None) == "TERM"
    assert supervisord.getint(section, "stopwaitsecs", fallback=0) >= 10, (
        "supervisord's default stopwaitsecs is 10; the drain pass needs more than that"
    )


def test_a_shelling_out_program_takes_its_children_with_it(supervisord):
    """The drain runs subprocesses. Without these, supervisord signals only the parent and a
    child keeps the ledger open after supervisord believes the program has stopped."""
    section = "program:consumer"
    assert supervisord.getboolean(section, "stopasgroup", fallback=False)
    assert supervisord.getboolean(section, "killasgroup", fallback=False)


def test_no_program_asks_for_longer_than_fly_will_wait(fly, supervisord):
    """The relationship that matters. Fly's budget is for the WHOLE machine, so any single
    program allowed to outlast it puts the microVM back on the SIGKILL path."""
    budget = _seconds(fly["kill_timeout"])
    over = {
        name.split(":", 1)[1]: supervisord.getint(name, "stopwaitsecs")
        for name in supervisord.sections()
        if name.startswith("program:") and supervisord.get(name, "stopwaitsecs", fallback=None)
        and supervisord.getint(name, "stopwaitsecs") >= budget
    }
    assert not over, (
        f"these programs may take at least Fly's whole {budget:.0f}s stop budget, so the "
        f"machine is SIGKILLed while they are still shutting down: {over}"
    )
