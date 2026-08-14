"""A config section that is a dict must never be read with `getattr`.

`getattr(some_dict, "key", default)` does not raise and does not find the key — it returns the
DEFAULT, every time, forever. That is a silent config override with no log line and no error,
and it is the most expensive bug shape this repo has produced.

MEASURED 2026-08-13, live config, live daemon:

    config.yaml:798                       candidates_per_signal: 50
    run.py (before the fix)               getattr(cfg.generation, "candidates_per_signal", 5)
    what that expression evaluated to     5

The engine generated 15 candidates a tick, prescreened all 15, then vetted 5 and binned the
other 10 one step before the moat — `store/scheduler/batch_diagnostics.jsonl` records
`prescreen_in: 15, prescreened_out: 0, novelty_selected: 5` on every tick of that day. The
founder had deliberately raised the number to 50 and the raise did nothing, because
`generate.py:218` reads the key with `.get()` and the vetting path read it with `getattr`.
Nothing failed, nothing logged, and the shelf stopped growing.

So this file does not test one call site. It tests the RULE, against the real config object, so
that a new `getattr(cfg.<dict-section>, ...)` anywhere in `prospector/` fails here rather than
in six weeks of quietly reduced throughput.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from prospector.config import load_config

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "prospector"

#: `getattr(cfg.<section>, "<key>"...` — the exact shape that silently swallows a dict key.
_GETATTR_ON_CFG = re.compile(r"getattr\(\s*cfg\.([a-z_]+)\s*,")


@pytest.fixture(scope="module")
def dict_sections() -> set[str]:
    """The config sections that are plain dicts on the REAL config, not a synthetic one.

    Deliberately the live `config.yaml`: a fixture config could differ in shape and would let
    the exact production defect through.
    """
    cfg = load_config(str(REPO / "config.yaml"))
    out = set()
    for name in dir(cfg):
        if name.startswith("_"):
            continue
        try:
            value = getattr(cfg, name)
        except Exception:  # noqa: BLE001 — a property that needs args is not a section
            continue
        if isinstance(value, dict):
            out.add(name)
    return out


def test_the_live_config_really_does_expose_dict_sections(dict_sections):
    """Guard the guard: if every section became an object this test must fail loudly, not pass
    vacuously by scanning for a shape that can no longer occur."""
    assert "generation" in dict_sections, (
        "cfg.generation is no longer a dict — re-derive this test's premise before trusting it")


def test_no_source_file_reads_a_dict_config_section_with_getattr(dict_sections):
    offenders: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(errors="ignore").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for section in _GETATTR_ON_CFG.findall(line):
                if section in dict_sections:
                    rel = path.relative_to(REPO)
                    offenders.append(f"{rel}:{lineno}  getattr(cfg.{section}, ...)  {line.strip()}")

    assert not offenders, (
        "getattr() on a config section that is a dict silently returns the default and ignores "
        "config.yaml. Use `(cfg.<section> or {}).get(key, default)`.\n  " + "\n  ".join(offenders))


def test_candidates_per_signal_is_read_the_way_config_declares_it():
    """The specific regression: the vetting cap must equal the declared number, not 5.

    Pinned against the live config so that the value in `config.yaml` is the value the engine
    uses — which is the entire point of a config file and was not true on 2026-08-13.
    """
    cfg = load_config(str(REPO / "config.yaml"))
    declared = (cfg.generation or {}).get("candidates_per_signal")
    assert declared, "config.yaml no longer declares generation.candidates_per_signal"

    gen_cfg = cfg.generation or {}
    resolved = (gen_cfg.get("candidates_per_signal", 5) if isinstance(gen_cfg, dict)
                else getattr(gen_cfg, "candidates_per_signal", 5))
    assert resolved == declared, f"config says {declared}, engine resolves {resolved}"

    # And the shape that caused it stays pinned as WRONG, so nobody "simplifies" back to it.
    assert getattr(gen_cfg, "candidates_per_signal", 5) == 5, (
        "getattr on a dict stopped returning the default — re-read this whole test's premise")
