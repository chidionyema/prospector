"""`is_denied` was made 1.7x cheaper on 2026-08-21. This file is the proof it still answers the same.

`shareable_files()` spent 1,561 ms of its 1,688 ms inside `is_denied` — 2,208 paths against 39
globs, up to three `fnmatch` calls each. The patterns are now compiled once at import instead of
being re-looked-up per call.

A speed-up to a security fence is only acceptable with an equivalence proof, because the failure
mode is silent: a pattern that stops matching does not raise, it hands over a credential. So this
file keeps the ORIGINAL implementation, verbatim, and asserts the two agree on every path in the
repo plus the escapes that a naive matcher gets wrong.
"""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

import pytest

from prospector.ops.share import DENY_GLOBS, is_denied

REPO_ROOT = Path(__file__).resolve().parents[2]


def is_denied_reference(rel: str) -> str:
    """The pre-2026-08-21 implementation, unchanged. The thing the fast one must agree with."""
    low = (rel or "").lower().lstrip("/")
    if not low or "\x00" in rel:
        return "not a path"
    base = low.rsplit("/", 1)[-1]
    for pat in DENY_GLOBS:
        low_pat = pat.lower()
        if fnmatch.fnmatch(low, low_pat):
            return pat
        if "/" not in low_pat and fnmatch.fnmatch(base, low_pat):
            return pat
        if low_pat.endswith("/*") and low.startswith(low_pat[:-1]):
            return pat
    return ""


#: Paths chosen because each one is a way a cheaper matcher could differ: case, a basename match
#: under a directory, a directory pattern nested deeper than one level, an empty or null name,
#: and a pattern (`**/node_modules/*`) whose prefix rule can never fire.
ADVERSARIAL = [
    "", "   ", "/", "/.env", "a\x00b", ".ENV", "Deploy/App.ENV", "keys/id_rsa",
    "store", "store/a", "store/a/b/c", "x/node_modules/y/z", "A/.Next/build/x",
    "foo.PEM", "a/b/secrets.YAML", ".git", ".git/config", "sub/.git/config", "..",
    "../.env", "docs/LINKS.md", "prospector/ops/share.py", "x.pyc", "__pycache__/a/b.py",
    ".lux/keys/agent.pem", "id_ed25519", "deep/nested/id_ed25519.pub",
]


@pytest.mark.parametrize("rel", ADVERSARIAL)
def test_the_compiled_fence_agrees_on_every_known_escape(rel):
    assert is_denied(rel) == is_denied_reference(rel)


def test_the_compiled_fence_agrees_on_every_path_in_this_repo():
    """The broad angle. The parametrised cases above are the ones we thought of."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - depends on the checkout
        pytest.skip("git cannot answer in this checkout")
    if out.returncode != 0:  # pragma: no cover - depends on the checkout
        pytest.skip("git cannot answer in this checkout")
    paths = out.stdout.split()
    assert paths, "git answered with zero files, so this test would prove nothing"
    disagreements = [p for p in paths if is_denied(p) != is_denied_reference(p)]
    assert not disagreements, f"the compiled fence changed its answer for: {disagreements[:10]}"


def test_the_compiled_table_covers_every_glob():
    """A pattern added to DENY_GLOBS without rebuilding the table would never match anything."""
    from prospector.ops.share import _DENY_COMPILED

    assert tuple(entry[0] for entry in _DENY_COMPILED) == DENY_GLOBS
