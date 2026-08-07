"""`prospector.golden_gen` must be importable and cwd-independent.

The defect this locks down: `golden_gen.py` imported `generate_candidates` from
`prospector.generate`, a name that has never existed in the history of that module
(`git log -S'generate_candidates' -- prospector/generate.py` is empty). So every call
raised ImportError at module import.

It was not dead code. `prospector/control_center/pages/_diagnostics.py` imports
`run_generative_golden` behind the "Run strategic benchmark (paid)" button and catches
`Exception` into `st.error(str(e))`, so a feature that had never once worked presented
as "an error happened this time". README.md advertises it as shipped. Nothing imported
the module at test time, so the whole suite stayed green over it.

The second defect: `golden_path` defaulted to the relative `"fixtures/generative_golden.json"`,
which resolves against the cwd. Streamlit is launched from wherever the operator happens
to be, so the default was correct for exactly one caller.
"""
from __future__ import annotations

import json

import pytest

from prospector.paths import repo_path


def test_the_cockpit_import_path_resolves():
    """The exact import `_diagnostics.py` performs. This alone would have caught it."""
    from prospector.golden_gen import run_generative_golden

    assert callable(run_generative_golden)


def test_the_generate_symbol_it_calls_actually_exists():
    """Guards the class of bug, not the one instance: the callee must be a real export."""
    import prospector.generate as gen
    import prospector.golden_gen as gg

    assert gg.generate is gen.generate


def test_generate_accepts_the_arguments_golden_gen_passes():
    """An importable module can still be wrong at the call site. Bind the real signature."""
    import inspect

    from prospector.generate import generate

    sig = inspect.signature(generate)
    sig.bind_partial(object(), object(), signal_text="s", k=5)  # raises TypeError if wrong


def test_the_fixture_the_default_points_at_exists():
    path = repo_path("fixtures", "generative_golden.json")
    assert path.exists(), path
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert cases and all("signal" in c and "targets" in c for c in cases)


def test_runs_from_an_unrelated_cwd_without_paid_calls(tmp_path, monkeypatch):
    """The cwd-independence proof: chdir away from the repo, then run it end to end.

    `generate` and the professor are stubbed, so this makes no network or CLI call —
    what is under test is the path resolution and the result shape, not the model.
    """
    import prospector.golden_gen as gg

    class _Candidate:
        title = "stub title"

        def to_dict(self):
            return {"title": self.title}

    monkeypatch.setattr(gg, "generate", lambda op, cfg, **kw: [_Candidate()])

    class _Prof:
        def complete_json(self, system, user, temperature=0.0):
            return {"alpha_score": 3.0, "rationale": "stub"}

    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "fixtures").exists()  # the relative default would fail here

    report = gg.run_generative_golden(object(), _Prof(), object())

    assert report["overall_alpha"] == 3.0
    assert report["cases"] and report["cases"][0]["generated"] == ["stub title"]


def test_an_explicit_golden_path_still_wins(tmp_path, monkeypatch):
    """Anchoring the default must not take the override away from callers."""
    import prospector.golden_gen as gg

    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps([{"signal": "sig", "targets": ["t"]}]), encoding="utf-8")

    monkeypatch.setattr(gg, "generate", lambda op, cfg, **kw: [])

    class _Prof:
        def complete_json(self, system, user, temperature=0.0):
            return {"alpha_score": 1.0, "rationale": "r"}

    report = gg.run_generative_golden(object(), _Prof(), object(), golden_path=str(custom))
    assert report["cases"][0]["signal"] == "sig"


def test_the_module_has_no_import_time_side_effects():
    """`__main__` work above the function defs would run on the cockpit's import."""
    import importlib

    import prospector.golden_gen as gg

    importlib.reload(gg)  # must not parse argv, load config, or build an operator


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
