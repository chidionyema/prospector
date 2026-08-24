"""The ML sidecar an experiment depends on must not live somewhere the OS deletes.

Incident 2026-08-20 (E-100, docs/ENGINE_100X_PROGRAM.md). Every published HHEM experiment
(E15, E17) ends with a line saying "reproduce with `runner.py run E15 --limit 350`". That command
shells out to a python3.12 interpreter carrying torch and transformers, and its default location
was `/tmp/prospector-ml-venv`. macOS cleared /tmp. The interpreter went with it, so the published
reproduce command was false and NOTHING said so — the receipts still read as reproducible, and the
failure would only surface the next time somebody tried to re-run the experiment.

The class is: **a published measurement whose instrument is stored somewhere ephemeral.** The fix
is not "remember to rebuild it" — it is that a default which can evaporate fails this test.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXPERIMENTS = REPO / "tools" / "experiments"


def _hhem_module(monkeypatch):
    """Import tools/experiments/_hhem.py with no env override in force."""
    monkeypatch.delenv("PROSPECTOR_ML_PYTHON", raising=False)
    monkeypatch.syspath_prepend(str(EXPERIMENTS))
    sys.modules.pop("_hhem", None)
    return importlib.import_module("_hhem")


def test_sidecar_default_is_not_ephemeral(monkeypatch):
    """The preferred sidecar location must survive a reboot and a /tmp sweep."""
    hhem = _hhem_module(monkeypatch)
    preferred = hhem._SIDECAR_CANDIDATES[0]
    assert not str(preferred).startswith("/tmp/"), (
        f"sidecar default {preferred} is under /tmp; the OS deletes it and every published "
        "HHEM reproduce command silently becomes false")
    assert not str(preferred).startswith("/var/folders/"), (
        f"sidecar default {preferred} is under the macOS per-user temp dir, which is also swept")
    assert str(preferred).startswith(str(Path.home())), (
        f"sidecar default {preferred} is not under $HOME")


def test_resolver_prefers_the_durable_path_when_both_exist(monkeypatch, tmp_path):
    """A leftover /tmp sidecar must never win over the durable one."""
    hhem = _hhem_module(monkeypatch)
    durable, ephemeral = tmp_path / "durable" / "python3.12", tmp_path / "eph" / "python3.12"
    for p in (durable, ephemeral):
        p.parent.mkdir(parents=True)
        p.write_text("#!/bin/sh\n")
    monkeypatch.setattr(hhem, "_SIDECAR_CANDIDATES", (durable, ephemeral))
    assert hhem._resolve_sidecar_python() == durable


def test_resolver_falls_back_to_a_later_candidate_when_only_it_exists(monkeypatch, tmp_path):
    hhem = _hhem_module(monkeypatch)
    durable, ephemeral = tmp_path / "durable" / "python3.12", tmp_path / "eph" / "python3.12"
    ephemeral.parent.mkdir(parents=True)
    ephemeral.write_text("#!/bin/sh\n")
    monkeypatch.setattr(hhem, "_SIDECAR_CANDIDATES", (durable, ephemeral))
    assert hhem._resolve_sidecar_python() == ephemeral


def test_resolver_names_the_durable_path_when_nothing_exists(monkeypatch, tmp_path):
    """With no sidecar at all, the error must point a rebuild at the durable location."""
    hhem = _hhem_module(monkeypatch)
    durable, ephemeral = tmp_path / "durable" / "python3.12", tmp_path / "eph" / "python3.12"
    monkeypatch.setattr(hhem, "_SIDECAR_CANDIDATES", (durable, ephemeral))
    assert hhem._resolve_sidecar_python() == durable


def test_env_override_beats_both_candidates(monkeypatch):
    hhem = _hhem_module(monkeypatch)
    monkeypatch.setenv("PROSPECTOR_ML_PYTHON", "/somewhere/else/python3.12")
    assert hhem._resolve_sidecar_python() == Path("/somewhere/else/python3.12")


def test_a_missing_sidecar_raises_rather_than_degrading(monkeypatch, tmp_path):
    """Never a lexical fallback dressed up as a groundedness score."""
    hhem = _hhem_module(monkeypatch)
    monkeypatch.setattr(hhem, "SIDECAR_PYTHON", tmp_path / "absent" / "python3.12")
    with pytest.raises(hhem.SidecarMissing) as exc:
        hhem.require_sidecar()
    assert "will NOT" in str(exc.value) and "install anything" in str(exc.value)


def test_no_experiment_stores_a_durable_venv_under_tmp():
    """Estate-wide: the same mistake in any other experiment fails here too."""
    offenders = []
    for path in sorted(EXPERIMENTS.glob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or '"""' in stripped:
                continue
            if '"/tmp/' not in line and "'/tmp/" not in line:
                continue
            if "venv" in line or "/bin/python" in line:
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "an interpreter or venv defaulted under /tmp — the OS deletes it and the experiment's "
        "published reproduce command becomes false:\n  " + "\n  ".join(offenders))
