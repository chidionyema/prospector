"""`deploy/secrets.sh set` must accept the value on stdin.

The usage line used to read `set KEY VALUE` and that was the only form. A value passed as an
argument is visible to `ps` for every process on the box, and an interactive shell appends it
to its history file, so a live Stripe key typed once outlives the terminal it was typed in.

These tests run against a THROWAWAY store in a temp directory. They never read, write or
decrypt the real `deploy/secrets.env.age`, and they never assert on a value -- only on its
length, so a failure message cannot leak one.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRETS_SH = REPO_ROOT / "deploy" / "secrets.sh"

# No `needs_tool("age")`, and deliberately no `skipif(shutil.which(...))` either. The fixture
# below puts FAKE `age` and `age-keygen` on PATH, so this file needs no binary installed and
# runs identically on a laptop and a CI runner. Two reasons that is the better design here and
# not a dodge:
#   1. A real `age` would make the CI job need a `brew install age` step, and CI is another
#      session's lane. A test that forces an edit outside your lane is a test that does not land.
#   2. The fake records the argv it was called with, which lets the last test below assert the
#      thing this whole change is about -- that the secret value never reaches a command line --
#      and no amount of real encryption could prove that.
# What is NOT covered: that `age` itself encrypts correctly. That is age's job, not ours.

# `age-keygen -o FILE` writes a key; `age-keygen -y FILE` prints a public key.
_FAKE_KEYGEN = """#!/bin/sh
if [ "$1" = "-y" ]; then echo "age1fakerecipient"; exit 0; fi
if [ "$1" = "-o" ]; then printf 'AGE-SECRET-KEY-1FAKE\n' > "$2"; exit 0; fi
exit 64
"""

# `age -r PUB -o OUT` copies stdin to OUT; `age -d -i KEY FILE` copies FILE out. Every argv it
# is called with is appended to $FAKE_ARGV_LOG, which is what the argv test reads.
_FAKE_AGE = """#!/bin/sh
echo "$@" >> "$FAKE_ARGV_LOG"
if [ "$1" = "-d" ]; then cat "$4"; exit 0; fi
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac
done
[ -n "$out" ] || exit 64
cat > "$out"
"""


@pytest.fixture
def store(tmp_path):
    """A key, an empty store and fake age binaries that exist only for this test."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("age", _FAKE_AGE), ("age-keygen", _FAKE_KEYGEN)):
        f = bin_dir / name
        f.write_text(body)
        f.chmod(0o755)

    key = tmp_path / "key.txt"
    subprocess.run([str(bin_dir / "age-keygen"), "-o", str(key)], check=True)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PROSPECTOR_AGE_KEY"] = str(key)
    env["PROSPECTOR_SECRETS_FILE"] = str(tmp_path / "s.age")
    env["FAKE_ARGV_LOG"] = str(tmp_path / "argv.log")
    return env


def _set(env, key, value=None, *, stdin=None):
    argv = ["bash", str(SECRETS_SH), "set", key]
    if value is not None:
        argv.append(value)
    return subprocess.run(
        argv, env=env, input=stdin, capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


def _lengths(env):
    """Every key in the throwaway store, mapped to its value's LENGTH. Never the value."""
    out = subprocess.run(
        ["age", "-d", "-i", env["PROSPECTOR_AGE_KEY"], env["PROSPECTOR_SECRETS_FILE"]],
        env=env, capture_output=True, text=True, check=True,
    ).stdout
    pairs = (line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {k: len(v) for k, v in pairs}


def test_a_value_on_stdin_is_stored(store):
    r = _set(store, "FAKE_B", stdin="stdin-form-no-newline")
    assert r.returncode == 0, r.stderr
    assert _lengths(store)["FAKE_B"] == len("stdin-form-no-newline")


def test_stdin_without_a_trailing_newline_still_works(store):
    """`printf %s` emits no newline, so `read` returns non-zero having filled the variable.

    Under `set -e` that killed the script before any check could run, and it printed nothing
    at all -- exit 1 and silence. Both halves are asserted here because the silent form is
    the one that wastes an afternoon.
    """
    r = _set(store, "FAKE_B", stdin="no-newline-here")
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    assert _lengths(store)["FAKE_B"] == len("no-newline-here")


def test_the_positional_form_still_works(store):
    """Removing it would push people back to editing the plaintext by hand, which is worse."""
    r = _set(store, "FAKE_A", "positional-form")
    assert r.returncode == 0, r.stderr
    assert _lengths(store)["FAKE_A"] == len("positional-form")


def test_empty_stdin_is_refused_with_a_reason(store):
    r = _set(store, "FAKE_D", stdin="")
    assert r.returncode != 0
    assert "no value on stdin" in r.stderr, r.stderr


def test_the_usage_line_offers_the_stdin_form(store):
    """A safe path nobody is told about is not a safe path."""
    r = subprocess.run(
        ["bash", str(SECRETS_SH), "nosuchverb"],
        env=store, capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert "set KEY [VALUE]" in r.stderr, r.stderr
    assert "stdin" in r.stderr, r.stderr



def test_the_value_never_reaches_a_command_line(store):
    """The point of the whole change, asserted directly rather than by inspection.

    `ps` shows argv to every process on the box and an interactive shell appends argv to its
    history file, so a value that reaches a command line outlives the terminal it was typed in.
    The fake `age` logs every argv it is handed; the secret must appear in none of them.
    """
    secret = "canary-value-must-not-appear-in-argv"
    r = _set(store, "FAKE_C", stdin=secret)
    assert r.returncode == 0, r.stderr
    logged = Path(store["FAKE_ARGV_LOG"]).read_text()
    assert secret not in logged, "the value was passed to a subprocess as an argument"
    assert _lengths(store)["FAKE_C"] == len(secret)
