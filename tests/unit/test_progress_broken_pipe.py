"""progress._emit must not abort a run when the parent closed the pipe."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import prospector.progress as progress


def test_emit_swallows_broken_pipe(monkeypatch):
    monkeypatch.setattr(progress, "_QUIET", False)

    def _boom(*_a, **_k):
        raise BrokenPipeError()

    monkeypatch.setattr("builtins.print", _boom)
    # Must not raise — CC parent dying mid-run must not kill generate.
    progress._emit("generated 20 candidates")
    assert progress._QUIET is True


def test_emit_swallows_epipe(monkeypatch):
    monkeypatch.setattr(progress, "_QUIET", False)

    def _boom(*_a, **_k):
        raise OSError(32, "Broken pipe")

    monkeypatch.setattr("builtins.print", _boom)
    progress._emit("still going")
    assert progress._QUIET is True
