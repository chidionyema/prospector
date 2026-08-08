#!/usr/bin/env python3
"""Project-venv side of the HHEM bridge: shell out to the 3.12 sidecar, get scores back.

See `_hhem_sidecar.py` for why this cannot be an import. This half does three things and nothing
else: locate the sidecar interpreter, refuse loudly if it is gone, and cache scores on disk so a
re-run of E15/E17 is free.

The refusal matters more than the call. If the sidecar has been wiped from /tmp the honest output
is "the instrument is missing", never a silently-degraded lexical fallback dressed up as a
groundedness measurement. `SidecarMissing` is raised and the experiment stops.

NEVER pip-install into the sidecar. A previous `numpy<2` pin broke transformers there outright;
the environment is verified working and is treated as read-only.
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
SIDECAR_PYTHON = Path(os.environ.get("PROSPECTOR_ML_PYTHON",
                                     "/tmp/prospector-ml-venv/bin/python3.12"))
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


def require_sidecar() -> dict:
    status = sidecar_status()
    if not status["exists"]:
        raise SidecarMissing(
            f"{SIDECAR_PYTHON} is gone. HHEM cannot run in the project venv "
            f"(python {sys.version.split()[0]}; no cp314 torch wheel, and torch dropped macOS "
            "x86_64 after 2.2). Recreate the sidecar deliberately — this experiment will NOT "
            "install anything.")
    if not status["script_exists"]:
        raise SidecarMissing(f"{SIDECAR_SCRIPT} is missing")
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
