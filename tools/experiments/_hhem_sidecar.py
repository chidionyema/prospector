#!/usr/bin/env python3
"""HHEM scorer — runs ONLY under the python3.12 sidecar interpreter, never the project venv.

Why a second process at all: the project venv is CPython 3.14.6 on macOS x86_64. There is no
`cp314` torch wheel, and torch dropped macOS x86_64 entirely after 2.2, so HHEM cannot be
imported in-process no matter how the dependency is spelled. The sidecar
`/tmp/prospector-ml-venv/bin/python3.12` already carries torch 2.2.2 + transformers 4.57.6.
This is the same two-process shape as the pi-bridge, and for the same reason: the environment,
not the code, is what has to change.

Contract (deliberately file-in / file-out, NOT stdin/stdout): torch and transformers both write
progress bars and UserWarnings, and at least one of them lands on stdout depending on the
terminal. A JSON payload sharing stdout with a warning is a parse error waiting to happen, so the
payload never touches a stream.

    python3.12 _hhem_sidecar.py <input.json> <output.json>

    input.json  : {"pairs": [[premise, hypothesis], ...], "batch_size": 16}
    output.json : {"ok": true, "scores": [float, ...], "model": "...", "seconds": float}
                  or {"ok": false, "error": "..."} — an exception is reported, never raised into
                  a caller that would read a truncated file.

Zero network by default: the caller sets HF_HUB_OFFLINE=1, and the model is already in
~/.cache/huggingface/hub/models--vectara--hallucination_evaluation_model. Zero tokens, zero paid
API calls: HHEM is a local 184M-parameter cross-encoder.

This file starts with `_` so `runner.py discover()` does not try to import it — importing it in
the project venv would fail on `import torch`, which is the whole point.
"""
from __future__ import annotations

import json
import sys
import time

MODEL_ID = "vectara/hallucination_evaluation_model"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: _hhem_sidecar.py <input.json> <output.json>", file=sys.stderr)
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    try:
        with open(in_path) as fh:
            payload = json.load(fh)
        pairs = [(str(p), str(h)) for p, h in payload["pairs"]]
        batch_size = int(payload.get("batch_size") or 16)

        import os as _os

        import torch

        # Measured 2026-08-07: the default run pinned ~108% CPU on a 12-thread box, i.e. one
        # core, and took ~1.7s per 1500-char pair. Torch does not always pick up the core count
        # through this model's custom `predict`, so it is set explicitly. This changes speed
        # only — the scores are identical, which the caller's on-disk score cache would expose
        # immediately if it were not true.
        threads = int(_os.environ.get("HHEM_THREADS") or _os.cpu_count() or 1)
        torch.set_num_threads(max(1, threads))

        from transformers import AutoModelForSequenceClassification

        t0 = time.time()
        model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_ID, trust_remote_code=True)
        load_s = time.time() - t0

        # Length-sorted batching. `predict` pads every batch to its longest member, so a batch
        # mixing a 40-char passage with a 1500-char one pays the 1500-char cost on both. Sorting
        # by length before batching removes most of that padding; the original order is restored
        # by index, so the returned list still lines up with the caller's `pairs`.
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        t1 = time.time()
        scored: dict[int, float] = {}
        with torch.inference_mode():
            for i in range(0, len(order), batch_size):
                chunk = order[i:i + batch_size]
                for idx, val in zip(chunk, model.predict([pairs[j] for j in chunk])):
                    scored[idx] = float(val)
        scores = [scored[i] for i in range(len(pairs))]
        result = {
            "ok": True,
            "scores": scores,
            "model": MODEL_ID,
            "n": len(scores),
            "load_seconds": round(load_s, 2),
            "predict_seconds": round(time.time() - t1, 2),
            "torch_threads": torch.get_num_threads(),
            "python": sys.version.split()[0],
        }
    except Exception as exc:  # reported as data; the caller must never see a half-written file
        import traceback
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc()}
    tmp = out_path + ".partial"
    with open(tmp, "w") as fh:
        json.dump(result, fh)
    import os
    os.replace(tmp, out_path)          # atomic: a reader never sees a truncated payload
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
