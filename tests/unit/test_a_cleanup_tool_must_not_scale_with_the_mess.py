"""The branch pruner must finish. Its cost may not grow with the number of files it reads.

WHAT HAPPENED. On 2026-08-19 the repo held 118 remote branches ahead of main and nobody could
say how much of it was real unmerged work. `scripts/prune_branches.py --remote` is the estate's
answer to exactly that question, and it was run twice: both runs hit the caller's timeout with an
empty stdout and read as a hang. It was not hanging. `absorbed()` ran `git diff -U0` and
`git show` once PER CHANGED FILE, and the branches that made the backlog big were the ones with
the most files -- `snapshot/2026-08-19/wt-land18-74f4ed5c` alone has 229 changed files and took
23.5s. Measured across all 114 remote branches: 425.1s, against a 300s ceiling.

THE CLASS: a cleanup tool whose cost scales with the mess it exists to clean, so it stops working
exactly when it is finally needed. The rewrite reads every file in two subprocesses instead of two
per file -- 38.4s for the same 114 branches, 11x faster, and byte-identical answers on every one.

This test pins the two things that fix depends on, because both fail silently:
  * the subprocess count must not track the file count;
  * `--no-renames` must stay on the combined diff. One diff per file passes a single pathspec,
    which turns rename detection OFF; one combined diff turns it back ON. On
    `archive/site-build-bundle-2026-08-18` that alone moved the count from 8703 added lines to
    8344. A speed fix that quietly moves the number it reports is not a speed fix.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prune_branches.py"


def _load():
    spec = importlib.util.spec_from_file_location("prune_branches", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _diff_of(n_files: int) -> str:
    """A -U0 diff touching n files, each adding one line long enough to be counted."""
    out = []
    for i in range(n_files):
        out += [f"diff --git a/f{i}.py b/f{i}.py", "--- a/f{i}.py".format(i=i),
                f"+++ b/f{i}.py", "@@ -0,0 +1 @@",
                f"+a_line_long_enough_to_count_{i} = {i}"]
    return "\n".join(out)


def _instrument(mod, monkeypatch, n_files: int) -> list[tuple[str, ...]]:
    """Run absorbed() against a fabricated diff and record every git call it makes."""
    calls: list[tuple[str, ...]] = []

    def fake_git(*args, check: bool = False) -> str:
        calls.append(args)
        if args[0] == "merge-base":
            return "basesha\n"
        if args[0] == "diff":
            return _diff_of(n_files)
        return ""

    class FakeProc:
        # `cat-file --batch` says "missing" for every file, which is the honest answer for a
        # fabricated tree and keeps this test about call COUNT, not about content.
        stdout = b"".join(f"main:f{i}.py missing\n".encode() for i in range(n_files))

    monkeypatch.setattr(mod, "git", fake_git)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: FakeProc())
    mod.absorbed("origin/some-branch")
    return calls


def test_the_git_calls_do_not_multiply_with_the_files(monkeypatch):
    """Ten files and a thousand must cost the same number of subprocesses."""
    small = len(_instrument(_load(), monkeypatch, 10))
    large = len(_instrument(_load(), monkeypatch, 1000))

    assert small == large, (
        f"absorbed() made {small} git calls for 10 files and {large} for 1000. A per-file call "
        f"is what made a --remote report take 425s and get killed before printing anything."
    )


def test_it_is_a_handful_of_calls_not_a_loop(monkeypatch):
    """Pin the absolute number too: 'equal' would also be satisfied by a constant that is huge."""
    calls = _instrument(_load(), monkeypatch, 500)

    assert len(calls) <= 4, (
        f"absorbed() should be one merge-base, one diff and one batched read of main's copies. "
        f"It made {len(calls)}: {calls}"
    )


def test_rename_detection_stays_off_so_the_metric_cannot_drift(monkeypatch):
    """The number this reports must not move because the diff was batched."""
    calls = _instrument(_load(), monkeypatch, 5)
    diffs = [c for c in calls if c and c[0] == "diff"]

    assert diffs, f"absorbed() ran no diff at all: {calls}"
    for c in diffs:
        assert "--no-renames" in c, (
            f"the combined diff must pass --no-renames; one diff per file disabled rename "
            f"detection implicitly, and turning it back on changes the count. Got: {c}"
        )


def test_a_deleted_file_contributes_no_added_lines(monkeypatch):
    """`+++ /dev/null` is a deletion. Its `+` lines belong to no file and must not be counted."""
    mod = _load()
    monkeypatch.setattr(mod, "git", lambda *a, **k: (
        "basesha\n" if a[0] == "merge-base" else
        "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n"
        "+this_line_is_not_really_added = 1\n"))
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: type("P", (), {"stdout": b""})())

    assert mod.absorbed("origin/b") == (0, 0)


def test_runtime_state_is_never_counted(monkeypatch):
    """store/ and signals/ are written by every run and say nothing about whether code landed."""
    mod = _load()
    monkeypatch.setattr(mod, "git", lambda *a, **k: (
        "basesha\n" if a[0] == "merge-base" else
        "diff --git a/store/x.jsonl b/store/x.jsonl\n--- a/store/x.jsonl\n+++ b/store/x.jsonl\n"
        "+a_long_runtime_line_written_by_a_run = 1\n"))
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: type("P", (), {"stdout": b""})())

    assert mod.absorbed("origin/b") == (0, 0)


def test_the_batched_read_survives_a_non_ascii_file():
    """`cat-file --batch` frames objects by BYTE length, so the walk must be done in bytes.

    Decoding the stream first desynchronises the offsets on the first multi-byte character, and
    every file after it is then read from the wrong place -- silently, as plausible-looking text.
    """
    mod = _load()
    first = "héllo — this line has multi-byte characters in it\n"
    second = "plain ascii second file\n"
    blob1, blob2 = first.encode(), second.encode()
    stream = (f"aaa blob {len(blob1)}\n".encode() + blob1 + b"\n"
              + f"bbb blob {len(blob2)}\n".encode() + blob2 + b"\n")

    import unittest.mock as m
    with m.patch.object(mod.subprocess, "run",
                        return_value=type("P", (), {"stdout": stream})()):
        blobs = mod._upstream_blobs(["one.txt", "two.txt"])

    assert blobs["one.txt"] == first
    assert blobs["two.txt"] == second, (
        "the second file was read from the wrong offset — the byte walk was done on decoded text"
    )


def test_a_missing_file_does_not_shift_everything_after_it():
    """main not having a file is normal (the branch adds it). It must not desync the walk."""
    mod = _load()
    blob = b"the content of the file main does have\n"
    stream = b"main:absent.txt missing\n" + f"ccc blob {len(blob)}\n".encode() + blob + b"\n"

    import unittest.mock as m
    with m.patch.object(mod.subprocess, "run",
                        return_value=type("P", (), {"stdout": stream})()):
        blobs = mod._upstream_blobs(["absent.txt", "present.txt"])

    assert "absent.txt" not in blobs
    assert blobs["present.txt"] == blob.decode()


@pytest.mark.parametrize("n", [0, 1, 250])
def test_it_answers_for_the_empty_the_one_and_the_many(monkeypatch, n):
    """The three cases, so a rewrite cannot pass on the middle one alone."""
    mod = _load()
    calls = _instrument(mod, monkeypatch, n)

    assert len(calls) <= 4, f"{n} files cost {len(calls)} git calls"
