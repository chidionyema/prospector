"""A citation that continues with line numbers only must not be read as a path.

docs/COMMERCIAL_READINESS_PROGRAM.md:865 cites one file and then four more lines in it:

    (`models.py:213`; set at `verify.py:481-493`, persisted at `:527/:534/:553/:561`)

The last span has slashes in it and ends in a line number, which is exactly the shape of a path
claim. doc_lint reported `models.py` correctly and then reported a missing file for the line
list, which names no file at all. The doc was accurate; the linter was wrong, and the only way
to silence it was a waiver on an accurate line.
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "doc_lint", Path(__file__).resolve().parents[2] / "scripts" / "doc_lint.py")
doc_lint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(doc_lint)


@pytest.mark.parametrize("token", [
    ":527/:534/:553/:561",
    ":481-493",
    ":12/:34",
])
def test_a_span_that_opens_with_a_colon_is_never_a_path_claim(token):
    assert doc_lint._is_path_claim(token) is False


@pytest.mark.parametrize("token", [
    "prospector/verify.py:481-493",
    "scripts/doc_lint.py",
    "docs/RUNBOOKS.md:12",
])
def test_a_real_citation_is_still_a_path_claim(token):
    assert doc_lint._is_path_claim(token) is True


def test_the_line_that_produced_this_test_is_clean():
    """The whole point: the estate's own doc must lint clean without a waiver."""
    doc = Path(doc_lint.REPO_ROOT) / "docs" / "COMMERCIAL_READINESS_PROGRAM.md"
    if not doc.exists():                       # pragma: no cover - the doc is committed
        pytest.skip("doc not in this checkout")
    line = doc.read_text(errors="replace").splitlines()[864]
    assert ":527/:534" in line, "line 865 moved; re-point this test at the citation"
    assert "doc-lint-ok" not in line, "the linter was silenced instead of corrected"
    bad = [t for t in doc_lint._CODE_SPAN.findall(line) if doc_lint._is_path_claim(t)
           and doc_lint._resolve(doc_lint._LINE_REF.sub("", t), "docs") is None]
    assert bad == [], f"still read as missing paths: {bad}"


def test_write_baseline_survives_the_day_the_burn_down_finishes(tmp_path, monkeypatch, capsys):
    """An empty baseline is the goal, and it used to crash the tool that writes it.

    `--write-baseline` printed `min(due.values())` unconditionally. With zero findings `due` is
    empty, so the run wrote a correct `{}` and then died on ValueError. The burn-down tool failed
    on exactly the day the burn-down succeeded.
    """
    baseline = tmp_path / "doc_lint_baseline.json"
    # REPO_ROOT moves with the baseline: the summary line prints the path relative to it.
    monkeypatch.setattr(doc_lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(doc_lint, "BASELINE_PATH", baseline)
    monkeypatch.setattr(doc_lint, "lint", lambda: [])
    assert doc_lint.main(["--write-baseline"]) == 0
    assert baseline.read_text().strip() == "{}"
    assert "no deadlines" in capsys.readouterr().out
