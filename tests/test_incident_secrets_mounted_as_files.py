"""The engine must read a credential that is mounted as a file, and must refuse a partial set.

RUNG 4 (incident), per the test ladder in `~/AGENTS.md`. The incident is 2026-08-24: a box started
carrying none of its 24 settings while the deploy script reported success, and the symptom arrived
hours later and in another subsystem as "All operators unavailable - check API keys". Every `raises`
case below is that incident in one of its shapes.

`test_any_name_and_value_survives_the_round_trip` is the rung-2 property — one behaviour, a table of
cases that a refactor cannot invalidate — written as a loop because `hypothesis` is not installed in
this repo (measured 2026-08-24: `ModuleNotFoundError`). It is a property in substance and a loop in
form, and adding a dependency for it was not worth it.

There is deliberately no test that `prospector/__init__.py` calls the loader by asserting on an
import. That would grade the shape of the import rather than the behaviour, and it would pass on the
day the call is moved somewhere too late to matter. `test_the_package_import_populates_the_env`
starts a real subprocess with the variable set and asks the resulting process what it can read,
which is the same question the container asks.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from prospector.file_secrets import ENV_VAR, load_secrets_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

# Nothing here is a real credential. These are the byte patterns real ones take.
NOT_A_REAL_SECRET = "sk-test-0000000000000000"


@pytest.fixture
def secrets_dir(tmp_path, monkeypatch):
    """A mounted secrets directory, with the variable set and the process env restored after.

    The whole point of `load_secrets_dir` is to mutate `os.environ`, and `tests/conftest.py:172`
    fails any test that leaks a variable into the rest of the worker — correctly, and it caught
    this file first. `monkeypatch` cannot know in advance which names a test's fixture files will
    set, so the snapshot is taken here and restored wholesale.
    """
    before = dict(os.environ)
    d = tmp_path / "secrets"
    d.mkdir()
    monkeypatch.setenv(ENV_VAR, str(d))
    yield d
    os.environ.clear()
    os.environ.update(before)


def test_a_mounted_file_becomes_an_environment_variable(secrets_dir, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    (secrets_dir / "MINIMAX_API_KEY").write_text(NOT_A_REAL_SECRET)

    assert load_secrets_dir() == ("MINIMAX_API_KEY",)
    assert os.environ["MINIMAX_API_KEY"] == NOT_A_REAL_SECRET


def test_the_file_wins_over_an_existing_environment_variable(secrets_dir, monkeypatch):
    """A rotation that does not take effect is the hardest failure to see."""
    monkeypatch.setenv("STRIPE_API_KEY", "the-stale-one")
    (secrets_dir / "STRIPE_API_KEY").write_text("the-rotated-one")

    load_secrets_dir()
    assert os.environ["STRIPE_API_KEY"] == "the-rotated-one"


def test_any_name_and_value_survives_the_round_trip(secrets_dir):
    """One trailing newline is dropped. Nothing else about the value is touched."""
    cases = {
        "SIMPLE": "abc",
        "TRAILING_NEWLINE": "abc\n",
        "INTERNAL_NEWLINES": "-----BEGIN KEY-----\nline2\nline3\n",
        "LEADING_SPACE": "  abc",
        "TRAILING_SPACE": "abc  ",
        "EQUALS_AND_QUOTES": 'a=b"c\'d',
        "UNICODE": "paßwort-éè",
        "EMPTY": "",
        "LOOKS_LIKE_A_COMMENT": "# not a comment, a value",
        "_LEADING_UNDERSCORE": "ok",
        "D1GITS_AFTER_FIRST": "ok",
    }
    for name, value in cases.items():
        (secrets_dir / name).write_text(value, encoding="utf-8")

    assert load_secrets_dir() == tuple(sorted(cases))
    for name, value in cases.items():
        expected = value[:-1] if value.endswith("\n") else value
        assert os.environ[name] == expected, name


def test_kubernetes_symlink_farm_is_read_and_its_machinery_is_not(secrets_dir):
    """A projected Secret volume is `..data` plus per-key symlinks into it, not plain files."""
    real = secrets_dir / "..2026_08_24_09_11_02.123456789"
    real.mkdir()
    (real / "EXA_API_KEY").write_text(NOT_A_REAL_SECRET)
    (secrets_dir / "..data").symlink_to(real, target_is_directory=True)
    (secrets_dir / "EXA_API_KEY").symlink_to(secrets_dir / "..data" / "EXA_API_KEY")

    assert load_secrets_dir() == ("EXA_API_KEY",)
    assert os.environ["EXA_API_KEY"] == NOT_A_REAL_SECRET


def test_unset_variable_loads_nothing_and_raises_nothing(monkeypatch):
    """Every laptop, every test run, every CI job. Opting in is what setting the variable means."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert load_secrets_dir() == ()


def test_a_missing_directory_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "never-mounted"))
    with pytest.raises(RuntimeError, match="not a directory"):
        load_secrets_dir()


def test_an_empty_directory_refuses_to_start(secrets_dir):
    """A mount that exists and holds nothing looks exactly like success to everything downstream."""
    with pytest.raises(RuntimeError, match="empty directory"):
        load_secrets_dir()


def test_a_name_no_shell_could_read_refuses_to_start(secrets_dir):
    """`os.environ["A.B"]` is settable from Python and unreachable from a shell."""
    (secrets_dir / "STRIPE.API.KEY").write_text(NOT_A_REAL_SECRET)
    with pytest.raises(RuntimeError, match="not a legal environment variable name"):
        load_secrets_dir()


def test_an_unreadable_file_refuses_to_start(secrets_dir):
    """Half a credential set is the incident. It must not be survivable."""
    (secrets_dir / "GOOD_KEY").write_text(NOT_A_REAL_SECRET)
    bad = secrets_dir / "BINARY_KEY"
    bad.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(RuntimeError, match="could not be read as UTF-8"):
        load_secrets_dir()


def test_no_secret_value_ever_reaches_an_exception_message(secrets_dir):
    """LAW 21. Naming a secret is fine; printing it is not, and a traceback is printed."""
    (secrets_dir / "ILLEGAL.NAME").write_text(NOT_A_REAL_SECRET)
    with pytest.raises(RuntimeError) as caught:
        load_secrets_dir()
    assert NOT_A_REAL_SECRET not in str(caught.value)

    binary = secrets_dir / "ILLEGAL.NAME"
    binary.unlink()
    (secrets_dir / "BINARY_KEY").write_bytes(NOT_A_REAL_SECRET.encode() + b"\xff")
    with pytest.raises(RuntimeError) as caught:
        load_secrets_dir()
    assert NOT_A_REAL_SECRET not in str(caught.value)
    # `raise ... from None` on purpose: the chained UnicodeDecodeError prints the offending bytes.
    assert caught.value.__cause__ is None


def test_the_package_import_populates_the_env(tmp_path):
    """The container's question, asked the container's way: a fresh process, then what can it read?

    Asserting that `prospector/__init__.py` contains a call would grade the shape. This grades the
    outcome, so it still fails if the call is moved somewhere that runs too late.
    """
    d = tmp_path / "secrets"
    d.mkdir()
    (d / "TELEGRAM_BOT_TOKEN").write_text(NOT_A_REAL_SECRET)

    env = {**os.environ, ENV_VAR: str(d)}
    env.pop("TELEGRAM_BOT_TOKEN", None)
    out = subprocess.run(
        [sys.executable, "-c", "import prospector, os; print(os.environ['TELEGRAM_BOT_TOKEN'])"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == NOT_A_REAL_SECRET


def test_a_broken_mount_stops_the_process_at_import(tmp_path):
    """CrashLoopBackOff on the first second beats "All operators unavailable" three hours later."""
    env = {**os.environ, ENV_VAR: str(tmp_path / "never-mounted")}
    out = subprocess.run(
        [sys.executable, "-c", "import prospector"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode != 0
    assert "not a directory" in out.stderr
