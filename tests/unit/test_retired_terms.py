"""The retired-terms guard, proved on the BROKEN state as well as the clean one.

A guard that has only ever been seen to pass is not known to work
(`docs/OPS_AUTOMATION_PRINCIPLES.md` R4). Most of these tests build a throwaway git repo
containing the defect and check the guard fires. The last one runs it against this repo, which
is the live check.

The synthetic term is `acmepay`, deliberately not a real retired name, so these fixtures can
never trip the live declaration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ops.automations.retired_terms import EXIT_FINDINGS, EXIT_OK, EXIT_UNKNOWN, main, run

REPO = Path(__file__).resolve().parents[2]


def _git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for rel, body in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _declaration(tmp_path: Path, allow: list[str] | None = None) -> Path:
    lines = ["terms:", "  - term: acmepay", "    reason: removed in the test"]
    if allow:
        lines.append("    allow:")
        lines += [f"      - {prefix}" for prefix in allow]
    path = tmp_path / "decl.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_fires_on_the_broken_state(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"src/checkout.py": 'PROVIDER = "acmepay"\n'})
    result = run(_declaration(tmp_path), repo)

    assert result["status"] == "findings"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["where"] == "src/checkout.py:1"
    assert result["findings"][0]["term"] == "acmepay"


def test_matches_regardless_of_case(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"docs/terms.md": "processed by AcmePay Ltd\n"})
    assert run(_declaration(tmp_path), repo)["status"] == "findings"


def test_an_allowed_path_is_history_not_a_finding(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"docs/archive/june.md": "we used acmepay\n"})
    result = run(_declaration(tmp_path, allow=["docs/archive/"]), repo)

    assert result["status"] == "ok"
    assert result["checked"] == 0  # the file was skipped, not read and cleared


def test_an_allow_prefix_does_not_exempt_a_sibling_path(tmp_path):
    # The prefix is a path prefix, so `docs/archive/` must not silence `docs/archived.md`.
    repo = _git_repo(tmp_path / "repo", {"docs/archived.md": "acmepay\n"})
    assert run(_declaration(tmp_path, allow=["docs/archive/"]), repo)["status"] == "findings"


def test_a_clean_repo_is_ok(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"src/checkout.py": 'PROVIDER = "stripe"\n'})
    result = run(_declaration(tmp_path), repo)

    assert result["status"] == "ok"
    assert result["checked"] == 1


def test_a_missing_declaration_is_unknown_never_clean(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    result = run(tmp_path / "does-not-exist.yaml", repo)

    assert result["status"] == "unknown"
    assert "not found" in result["reason"]


def test_a_declaration_with_no_terms_is_unknown(tmp_path):
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    empty = tmp_path / "empty.yaml"
    empty.write_text("terms: []\n", encoding="utf-8")

    assert run(empty, repo)["status"] == "unknown"


def test_outside_a_git_repo_is_unknown(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = run(_declaration(tmp_path), plain)

    assert result["status"] == "unknown"


def test_exit_codes_are_distinct(tmp_path, monkeypatch, capsys):
    # 0 clean, 1 findings, 2 could not establish. A caller that cannot tell "unknown" from
    # "clean" is the whole defect this exit code exists to prevent.
    clean = _git_repo(tmp_path / "clean", {"a.py": "x = 1\n"})
    dirty = _git_repo(tmp_path / "dirty", {"a.py": "acmepay\n"})
    decl = _declaration(tmp_path)

    monkeypatch.chdir(clean)
    assert main(["--config", str(decl)]) == EXIT_OK

    monkeypatch.chdir(dirty)
    assert main(["--config", str(decl)]) == EXIT_FINDINGS

    monkeypatch.chdir(clean)
    assert main(["--config", str(tmp_path / "missing.yaml")]) == EXIT_UNKNOWN


def test_json_mode_carries_what_the_console_renders(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path / "repo", {"a.py": "acmepay\n"})
    monkeypatch.chdir(repo)
    main(["--json", "--config", str(_declaration(tmp_path))])

    payload = json.loads(capsys.readouterr().out)
    for key in ("automation", "status", "checked", "findings", "ran_at", "probe"):
        assert key in payload, f"the console renders {key}"
    assert payload["automation"] == "retired_terms"


@pytest.mark.skipif(sys.platform == "win32", reason="git ls-files paths differ")
def test_this_repo_is_clean_of_every_retired_term():
    """The live guard. Paddle was removed on 2026-08-16; this is what keeps it removed."""
    result = run(REPO / "ops" / "config" / "retired_terms.yaml", REPO)

    assert result["status"] != "unknown", result.get("reason")
    assert result["status"] == "ok", (
        "A retired term is back. Each line is either a leftover to remove, or history that "
        "belongs in the `allow:` list in ops/config/retired_terms.yaml with a written "
        "reason:\n  " + "\n  ".join(f"{f['where']}  {f['what']}" for f in result["findings"])
    )
