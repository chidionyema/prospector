"""The stranded-pack check must fire on the broken state (R4), and must refuse to guess (P6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ops.automations.stranded_packs import CannotEstablish, _pack_id, scan

# The SHIPPED declaration, not a copy of it. Every `scan()` below joins this onto tmp_path, so
# nothing here reads the operator's real store — but a duplicated `"store/dossiers"` literal reads
# to `test_suite_is_machine_independent.py` exactly like a test that does, and it cannot tell the
# two apart. Loading the file the automation itself loads settles that and buys a second thing:
# renaming a key in the yaml now fails these tests instead of leaving them green against a shape
# the automation no longer has.
DECL = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "ops" / "config" / "stranded_packs.yaml")
    .read_text(encoding="utf-8"))


def _store(tmp_path):
    d = tmp_path / "store" / "dossiers"
    d.mkdir(parents=True)
    return d


def _pack(doss, pid: str, *, lint: object = "missing") -> None:
    (doss / f"{pid}.pass.json").write_text("{}")
    if lint != "missing":
        (doss / f"{pid}.lint.json").write_text(json.dumps(lint))


def test_a_pack_with_a_failing_lint_record_is_stranded_and_names_the_rule(tmp_path):
    doss = _store(tmp_path)
    _pack(doss, "aaa", lint={"ok": False, "problems": [{"check": "grammar"},
                                                       {"check": "citation_urls"}]})
    result = scan(tmp_path, DECL)
    assert result["stranded"] == 1
    assert result["blocking_checks"] == {"citation_urls": 1, "grammar": 1}
    assert "grammar" in result["findings"][0]["what"]


def test_a_pack_with_no_lint_record_is_stranded_not_sellable(tmp_path):
    doss = _store(tmp_path)
    _pack(doss, "bbb")
    result = scan(tmp_path, DECL)
    assert result["by_reason"] == {"never_linted": 1}
    assert result["sellable"] == 0


def test_a_clean_pack_is_sellable(tmp_path):
    doss = _store(tmp_path)
    _pack(doss, "ccc", lint={"ok": True, "problems": []})
    result = scan(tmp_path, DECL)
    assert (result["sellable"], result["stranded"]) == (1, 0)


def test_kills_and_defers_are_not_counted_as_stranded_revenue(tmp_path):
    doss = _store(tmp_path)
    _pack(doss, "ddd", lint={"ok": True})
    (doss / "eee.kill.json").write_text("{}")
    (doss / "fff.defer.json").write_text("{}")
    result = scan(tmp_path, DECL)
    assert result["passed"] == 1


def test_the_id_is_the_part_before_the_first_dot():
    """`Path.stem` gives `<id>.pass`, which finds no lint record and strands the whole shelf."""
    assert _pack_id("0a1b2c3d.pass.json") == "0a1b2c3d"
    assert _pack_id("0a1b2c3d.lint.json") == "0a1b2c3d"


def test_a_naming_change_is_unknown_not_a_clean_shelf(tmp_path):
    """Zero matches means the layout moved. Reporting that as 'nothing stranded' is the worst
    possible answer, so it raises instead."""
    doss = _store(tmp_path)
    (doss / "ggg.passed.json").write_text("{}")  # not the declared suffix
    with pytest.raises(CannotEstablish):
        scan(tmp_path, DECL)


def test_a_missing_dossier_directory_is_unknown(tmp_path):
    with pytest.raises(CannotEstablish):
        scan(tmp_path, DECL)


def test_an_unreadable_lint_record_is_stranded_and_says_so(tmp_path):
    doss = _store(tmp_path)
    _pack(doss, "hhh", lint="missing")
    (doss / "hhh.lint.json").write_text("{not json")
    result = scan(tmp_path, DECL)
    assert result["by_reason"] == {"lint_unreadable": 1}
