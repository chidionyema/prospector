#!/usr/bin/env python3
"""Project-venv side of the HHEM bridge: shell out to the 3.12 sidecar, get scores back.

See `_hhem_sidecar.py` for why this cannot be an import. This half does three things and nothing
else: locate the sidecar interpreter, refuse loudly if it is gone, and cache scores on disk so a
re-run of E15/E17 is free.

The refusal matters more than the call. If the sidecar interpreter is gone the honest output is
"the instrument is missing", never a silently-degraded lexical fallback dressed up as a
groundedness measurement. `SidecarMissing` is raised and the experiment stops.

DO NOT casually pip-install into the sidecar; treat it as read-only. The environment is pinned and
verified, and an unplanned upgrade there invalidates every published HHEM number at a stroke.

The sidecar used to live under /tmp. macOS cleared /tmp on 2026-08-20 and destroyed it, which
silently falsified the "reproduce with runner.py run E15" line published in every HHEM receipt --
the experiment could no longer be re-run at all. It now lives under ~/.local/share, which survives
a reboot. E-100, docs/ENGINE_100X_PROGRAM.md.

One prohibition here was measured and found too broad. The old text read "NEVER pip-install into
the sidecar; a previous numpy<2 pin broke transformers there outright." On the 2026-08-20 rebuild
`numpy<2` was REQUIRED: torch 2.2.2 is built against the numpy 1.x C API and emits "Failed to
initialize NumPy: _ARRAY_API not found" under numpy 2.x. Measured after installing numpy 1.26.4 --
transformers 4.57.6 / torch 2.2.2 / numpy 1.26.4, HHEM loaded in 3.78s and scored 4 pairs in 2.96s
(supported 0.868, contradicted 0.0038, identical 0.918, irrelevant 0.0011). The pin is a
requirement of this torch build, not a hazard. What broke the earlier sidecar is not recorded and
was not reproduced.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Searched in order; the FIRST entry is also the fallback when none exists, so the error message
# names the path a rebuild should target. The historical /tmp location is deliberately NOT listed:
# it is the location this whole guard exists to forbid, and anyone who still has a sidecar there
# can point at it with PROSPECTOR_ML_PYTHON.
_SIDECAR_CANDIDATES = (
    Path.home() / ".local/share/prospector-ml-venv/bin/python3.12",
)


def _resolve_sidecar_python() -> Path:
    override = os.environ.get("PROSPECTOR_ML_PYTHON")
    if override:
        return Path(override)
    for cand in _SIDECAR_CANDIDATES:
        if cand.exists():
            return cand
    return _SIDECAR_CANDIDATES[0]


SIDECAR_PYTHON = _resolve_sidecar_python()
SIDECAR_SCRIPT = HERE / "_hhem_sidecar.py"
CACHE_PATH = HERE / "_hhem_score_cache.json"
MODEL_ID = "vectara/hallucination_evaluation_model"


class SidecarMissing(RuntimeError):
    """The HHEM sidecar interpreter is absent or unusable. Stop; do not install anything."""


def sidecar_status() -> dict:
    """A probe, not a paragraph: what is actually on disk right now."""
    status = {"python": str(SIDECAR_PYTHON), "exists": SIDECAR_PYTHON.exists(),
              "script": str(SIDECAR_SCRIPT), "script_exists": SIDECAR_SCRIPT.exists()}
    if not status["exists"]:
        return status
    probe = subprocess.run(
        [str(SIDECAR_PYTHON), "-c",
         "import torch,transformers;print(torch.__version__,transformers.__version__)"],
        capture_output=True, text=True, timeout=180)
    status["probe_rc"] = probe.returncode
    status["versions"] = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
    return status


def require_sidecar(script: Path | None = None) -> dict:
    """Refuse loudly unless the sidecar interpreter AND the script that will run in it both exist.

    `script` defaults to the HHEM sidecar so the original no-argument call site keeps working.
    Other experiments (E101's `_verifier_sidecar.py`) pass their own, because "the interpreter is
    fine but MY script is missing" is a different failure and must say so.
    """
    script = Path(script) if script is not None else SIDECAR_SCRIPT
    status = sidecar_status()
    status["script"] = str(script)
    status["script_exists"] = script.exists()
    if not status["exists"]:
        raise SidecarMissing(
            f"{SIDECAR_PYTHON} is gone. HHEM cannot run in the project venv "
            f"(python {sys.version.split()[0]}; no cp314 torch wheel, and torch dropped macOS "
            "x86_64 after 2.2). Recreate the sidecar deliberately — this experiment will NOT "
            "install anything. Rebuild:\n"
            f"  /usr/local/opt/python@3.12/bin/python3.12 -m venv {SIDECAR_PYTHON.parent.parent}\n"
            f"  {SIDECAR_PYTHON} -m pip install 'torch==2.2.2' 'transformers==4.57.6' "
            "'numpy<2'\n"
            "Then re-run. Any HHEM number published while this was missing is unreproducible.")
    if not status["script_exists"]:
        raise SidecarMissing(f"{script} is missing")
    if status.get("probe_rc") != 0:
        raise SidecarMissing(
            f"sidecar interpreter exists but cannot import torch/transformers (rc="
            f"{status.get('probe_rc')}). Do NOT pip-install into it; a previous numpy<2 pin "
            "broke transformers there outright.")
    return status


def _key(premise: str, hypothesis: str) -> str:
    h = hashlib.sha256()
    h.update(MODEL_ID.encode())
    h.update(b"\x00")
    h.update(premise.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(hypothesis.encode("utf-8", "replace"))
    return h.hexdigest()[:24]


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def score_pairs(pairs: list[tuple[str, str]], batch_size: int = 16,
                use_cache: bool = True, progress: bool = True) -> tuple[list[float], dict]:
    """Score (premise, hypothesis) pairs. Returns (scores, meta).

    A score near 1.0 = the hypothesis is factually consistent with the premise; near 0.0 = it is
    not supported by it. Order of the returned list matches `pairs` exactly.
    """
    status = require_sidecar()
    cache = _load_cache() if use_cache else {}
    keys = [_key(p, h) for p, h in pairs]
    todo_idx = [i for i, k in enumerate(keys) if k not in cache]
    meta = {"sidecar": status, "requested": len(pairs), "cache_hits": len(pairs) - len(todo_idx),
            "model": MODEL_ID}

    if todo_idx:
        if progress:
            print(f"  HHEM: scoring {len(todo_idx)} new pairs via {SIDECAR_PYTHON} "
                  f"({meta['cache_hits']} cached)...", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            fin, fout = Path(tmp) / "in.json", Path(tmp) / "out.json"
            fin.write_text(json.dumps({
                "pairs": [list(pairs[i]) for i in todo_idx], "batch_size": batch_size}))
            env = dict(os.environ)
            # Offline by default: the model is already in the HF cache, and a network fetch is
            # neither needed nor wanted for an audit that claims to be zero-cost.
            env.setdefault("HF_HUB_OFFLINE", "1")
            env.setdefault("TRANSFORMERS_OFFLINE", "1")
            env.setdefault("TOKENIZERS_PARALLELISM", "false")
            proc = subprocess.run(
                [str(SIDECAR_PYTHON), str(SIDECAR_SCRIPT), str(fin), str(fout)],
                capture_output=True, text=True, env=env, timeout=60 * 90)
            if not fout.exists():
                raise SidecarMissing(
                    f"sidecar produced no output (rc={proc.returncode}). "
                    f"stderr tail: {proc.stderr.strip()[-600:]}")
            out = json.loads(fout.read_text())
        if not out.get("ok"):
            raise SidecarMissing(f"sidecar failed: {out.get('error')}")
        for i, s in zip(todo_idx, out["scores"]):
            cache[keys[i]] = s
        meta["sidecar_run"] = {k: out.get(k) for k in
                               ("n", "load_seconds", "predict_seconds", "python", "torch_threads")}
        if use_cache:
            CACHE_PATH.write_text(json.dumps(cache))
    else:
        meta["sidecar_run"] = None

    return [cache[k] for k in keys], meta
