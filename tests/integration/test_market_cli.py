"""Market CLI end-to-end: the readiness gate and cross-market replication (spec D2/D5/Gate).

These drive the real argument parsing and dispatch, because the gate is only worth
anything if it actually refuses at the command line.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The interpreter running these tests, not a hardcoded .venv path: CI installs with
# `uv pip install --system` (.github/workflows/ci.yml) so there is no .venv there at all,
# and the subprocess needs the same dependencies the parent already imported. Locally
# sys.executable IS .venv/bin/python, so this is the previous behaviour plus CI.
PY = sys.executable


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    """Point every store read/write in this module — parent process AND the CLI
    subprocesses `_run` spawns — at a scratch directory.

    These tests assert on the presence or absence of store/markets/<code>/READINESS.json.
    Against the real store that is a race with the operator: a live `markets probe us`
    writes that file, and `test_open_refuses_a_not_ready_artifact` unlinks it in its
    teardown, so the suite both failed spuriously and destroyed a real artifact. The
    env var is read by Config.store_dir, so the subprocess inherits the redirect.
    """
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "store"))


def _run(*args: str, expect_ok: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run([PY, "-m", "prospector.run", *args],
                          cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    if expect_ok:
        assert proc.returncode == 0, f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return proc


# ---------------------------------------------------------------------------
# The gate refuses
# ---------------------------------------------------------------------------

def test_markets_list_shows_status_per_market():
    """Status is asserted on the market's OWN line. The previous form was
    `"us" in out and "closed" in out`, which passed on any output containing some
    closed market anywhere — it would not have noticed `us` opening."""
    out = _run("markets", "list").stdout
    status = {line.split()[0]: line for line in out.splitlines() if line.split()}
    assert "open" in status["uk"]
    assert "open" in status["us"]
    assert "closed" in status["nigeria"]


def test_running_a_closed_market_is_refused():
    proc = _run("generate", "--market", "nigeria", "--candidates", "1",
                expect_ok=False)
    assert proc.returncode == 2
    assert "is closed, not open" in proc.stderr
    assert "markets probe" in proc.stderr


def test_opening_without_a_probe_is_refused():
    proc = _run("markets", "open", "--market", "us", expect_ok=False)
    assert proc.returncode == 2
    assert "no readiness probe" in proc.stderr


def test_unknown_market_is_refused_loudly():
    proc = _run("vet", "--title", "T", "--market", "atlantis", expect_ok=False)
    assert proc.returncode != 0
    assert "atlantis" in (proc.stderr + proc.stdout)


def test_open_market_is_permitted():
    """The default market runs without any market flag ceremony."""
    proc = _run("markets", "show", "--market", "uk")
    assert "uk" in proc.stdout


# ---------------------------------------------------------------------------
# Opening requires a CURRENT probe
# ---------------------------------------------------------------------------

def test_open_refuses_a_readiness_artifact_from_a_different_config(tmp_path):
    """A probe that measured another configuration must not open a market."""
    from prospector import markets as mk
    from prospector.config import load_config

    cfg = load_config()
    r = mk.Readiness(
        market="us", verdict="ready", measured_at="2026-07-30T00:00:00Z",
        config_fingerprint="deadbeefdeadbeef",  # not the current config
        n_candidates=6,
        metrics={"grounding_rate": 1.0, "authority_rate": 1.0,
                 "discrimination": 1.0, "pass_rate": 0.5, "defer_rate": 0.0},
        bars=mk.DEFAULT_BARS, failures=[], outcomes=[])

    path = mk.readiness_path(cfg, "us")
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    backup = path.read_text() if existed else None
    path.write_text(json.dumps(r.__dict__, indent=2))
    try:
        proc = _run("markets", "open", "--market", "us", expect_ok=False)
        assert proc.returncode == 2
        assert "different configuration" in proc.stderr
    finally:
        if backup is not None:
            path.write_text(backup)
        else:
            path.unlink(missing_ok=True)


def test_open_refuses_a_not_ready_artifact():
    from prospector import markets as mk
    from prospector.config import load_config

    cfg = load_config()
    r = mk.evaluate(cfg, "us", [
        mk.ProbeOutcome(title="a", expected="pass", actual="kill",
                        grounded_checks=0, total_checks=6,
                        authority_sources=0, total_sources=4),
        mk.ProbeOutcome(title="b", expected="kill", actual="kill",
                        grounded_checks=0, total_checks=6,
                        authority_sources=0, total_sources=4),
    ])
    assert not r.ready
    path = mk.save_readiness(cfg, r)
    try:
        proc = _run("markets", "open", "--market", "us", expect_ok=False)
        assert proc.returncode == 2
        assert "NOT READY" in proc.stderr
        assert "Do NOT lower the bar" in proc.stderr
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------

def test_replicate_into_a_closed_market_is_refused():
    proc = _run("replicate", "--from", "uk", "--market", "nigeria", "--dry-run",
                expect_ok=False)
    assert proc.returncode == 2
    assert "is closed, not open" in proc.stderr


def test_replicate_refuses_the_same_source_and_target():
    proc = _run("replicate", "--from", "uk", "--market", "uk", "--dry-run",
                expect_ok=False)
    assert proc.returncode == 2
    assert "nothing to replicate" in proc.stderr


# ---------------------------------------------------------------------------
# Config toggling
# ---------------------------------------------------------------------------

def test_close_then_open_rewrites_only_that_market(tmp_path):
    """`markets close/open` edits one status line and leaves comments intact."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(textwrap.dedent("""\
        operator: mock
        # a comment that must survive
        markets:
          default: uk
          uk:
            label: "United Kingdom"
            status: open
          us:
            label: "United States"
            status: closed
    """))
    proc = _run("--config", str(cfg_path), "markets", "close", "--market", "uk")
    assert "now closed" in proc.stdout

    text = cfg_path.read_text()
    assert "# a comment that must survive" in text
    import yaml
    data = yaml.safe_load(text)
    assert data["markets"]["uk"]["status"] == "closed"
    assert data["markets"]["us"]["status"] == "closed"  # untouched


def test_status_rewrite_refuses_rather_than_editing_a_sibling(tmp_path):
    """A market with no `status:` line must fail loudly. The dangerous alternative is a
    scan that runs on past the end of the block and opens the NEXT market instead."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(textwrap.dedent("""\
        operator: mock
        markets:
          default: uk
          uk:
            label: "United Kingdom"
            status: open
          ng:
            label: "Nigeria"
          us:
            label: "United States"
            status: closed
    """))
    proc = _run("--config", str(cfg_path), "markets", "open", "--market", "ng",
                expect_ok=False)
    assert proc.returncode != 0

    import yaml
    data = yaml.safe_load(cfg_path.read_text())
    assert data["markets"]["us"]["status"] == "closed"
    assert data["markets"]["uk"]["status"] == "open"


def test_a_closed_market_is_refused_even_when_it_arrives_from_config(tmp_path):
    """The gate must bind to the market actually in force. `--market` is only one way
    to select one; `markets.default:` is the other, and it must not be the soft route
    into an unproven jurisdiction."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(textwrap.dedent("""\
        operator: mock
        markets:
          default: us
          us:
            label: "United States"
            status: closed
    """))
    proc = _run("--config", str(cfg_path), "generate", "--candidates", "1",
                expect_ok=False)
    assert proc.returncode == 2
    assert "is closed, not open" in proc.stderr
