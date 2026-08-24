"""Incident test: a recipient added to the store must survive the next re-encryption.

The class (SECRETS_PROGRAM.md 3.7): `encrypt_stdin` derived its recipient set from our own
private key alone, so every `secrets.sh set` re-encrypted to one recipient and silently
stripped any other — which made the planned escrow recipient (action S1) decorative. The fix
is `deploy/secrets.recipients`: a committed file the script reads on every encrypt.

These tests use REAL `age`, because the thing under test is who can decrypt the ciphertext,
which a fake cannot prove. They run against a throwaway store and throwaway keypairs in a
temp directory, never the real store or key, and they never assert on a secret value.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRETS_SH = REPO_ROOT / "deploy" / "secrets.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="needs real age: the assertion is about who can decrypt, which a fake cannot show "
    "(the stdin/argv semantics are covered with fakes in test_secrets_set_reads_stdin.py)",
)


def _keygen(path: Path) -> str:
    subprocess.run(["age-keygen", "-o", str(path)], check=True, capture_output=True)
    return subprocess.run(
        ["age-keygen", "-y", str(path)], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def two_identities(tmp_path):
    """Identity A drives the store; identity B is the escrow recipient."""
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    pub_a, pub_b = _keygen(a), _keygen(b)
    env = dict(os.environ)
    env["PROSPECTOR_AGE_KEY"] = str(a)
    env["PROSPECTOR_SECRETS_FILE"] = str(tmp_path / "s.age")
    env["PROSPECTOR_AGE_RECIPIENTS"] = str(tmp_path / "recipients")
    return env, pub_a, pub_b, a, b


def _set(env, key, value):
    return subprocess.run(
        ["bash", str(SECRETS_SH), "set", key],
        env=env,
        input=value,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _keys_readable_by(env, identity: Path):
    r = subprocess.run(
        ["age", "-d", "-i", str(identity), env["PROSPECTOR_SECRETS_FILE"]],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return sorted(line.split("=", 1)[0] for line in r.stdout.splitlines() if "=" in line)


def test_a_listed_recipient_survives_the_next_set(two_identities):
    env, pub_a, pub_b, a, b = two_identities
    Path(env["PROSPECTOR_AGE_RECIPIENTS"]).write_text(f"# escrow\n{pub_a}\n{pub_b}\n")

    assert _set(env, "FAKE_ONE", "v1").returncode == 0
    # The incident is the SECOND write: before the fix it re-encrypted to A alone.
    assert _set(env, "FAKE_TWO", "v2").returncode == 0

    assert _keys_readable_by(env, a) == ["FAKE_ONE", "FAKE_TWO"]
    assert _keys_readable_by(env, b) == ["FAKE_ONE", "FAKE_TWO"]


def test_a_recipients_file_omitting_our_own_key_is_refused(two_identities):
    """Honouring such a file would make this the last `set` this machine can read back."""
    env, pub_a, pub_b, a, b = two_identities
    Path(env["PROSPECTOR_AGE_RECIPIENTS"]).write_text(f"{pub_b}\n")

    r = _set(env, "FAKE_ONE", "v1")
    assert r.returncode != 0
    assert pub_a in r.stderr, r.stderr
    assert not Path(env["PROSPECTOR_SECRETS_FILE"]).exists()


def test_without_a_recipients_file_only_our_own_key_reads_the_store(two_identities):
    """The pre-S5 behaviour, kept on purpose — and the proof the -R path is not vacuous:
    B decrypts in the test above only because the recipients file grants it."""
    env, pub_a, pub_b, a, b = two_identities

    assert _set(env, "FAKE_ONE", "v1").returncode == 0
    assert _keys_readable_by(env, a) == ["FAKE_ONE"]
    assert _keys_readable_by(env, b) is None
