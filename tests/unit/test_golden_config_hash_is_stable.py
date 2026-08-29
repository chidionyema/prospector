"""A golden run's `config_hash` must identify the CONFIG, not the process that wrote it.

Until 2026-08-20 `golden.py` computed it with the builtin `hash()`, which Python salts per
process via PYTHONHASHSEED. The field was therefore a process id wearing a config's name: the
same brain produced a different hash on every invocation, so nothing could ever ask "was this
score measured on the engine we are running now?" and get a true answer.

Measured over the 77 stored records in a worktree's `store/golden_runs/`: 51 distinct
`config_hash` values, clustering in groups of three — one group per `--runs 3` invocation, which
is one group per PROCESS.

This test runs in a SUBPROCESS on purpose. An in-process comparison passes trivially even with
the salted `hash()`, because the salt is fixed for the life of an interpreter — so the obvious
version of this test would have graded nothing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SNIPPET = (
    "import sys; sys.path.insert(0, {root!r});"
    "from prospector.golden import _config_fingerprint as f;"
    "print(f('[\\'minimax\\', \\'claude_cli\\']', 'model-a', 'model-fast'))"
)


def _hash_in_fresh_process(seed: str) -> str:
    root = str(REPO_ROOT)
    out = subprocess.run(
        [sys.executable, "-c", _SNIPPET.format(root=root)],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
    )
    return out.stdout.strip()


def test_config_hash_is_identical_under_different_hash_seeds():
    seen = {_hash_in_fresh_process(seed) for seed in ("0", "1", "12345")}
    assert len(seen) == 1, (
        f"config_hash changed with PYTHONHASHSEED: {sorted(seen)}. It is salted per process, "
        "so it identifies the run rather than the config."
    )
    only = seen.pop()
    assert only and only != "None", "fingerprint produced nothing"


def test_config_hash_separates_two_different_brains():
    from prospector.golden import _config_fingerprint

    a = _config_fingerprint("['minimax']", "m", "f")
    b = _config_fingerprint("['claude_cli']", "m", "f")
    assert a != b, "two different operators must not share a config_hash"


def test_config_hash_is_not_a_python_int():
    """The old format was `str(hash(...))` — a signed 19-digit int. Old records stay readable
    and stay distinguishable from new ones, which is how a consumer can tell them apart."""
    from prospector.golden import _config_fingerprint

    value = _config_fingerprint("['minimax']", "m", "f")
    assert not value.lstrip("-").isdigit(), f"still an int-shaped hash: {value}"
    assert len(value) == 12, f"expected a 12-char digest, got {value!r}"
