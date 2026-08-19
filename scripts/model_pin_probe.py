#!/usr/bin/env python3
"""Print the model every part of the engine will actually run on.

WHY THIS EXISTS. The ops console had two model-pin knobs, `model` and `model_fast`. Measured
2026-08-19: both were inert. A name-prefix heuristic in `_build_operator` decided which provider
`model:` "belonged to"; the value it computed reached one construction site (`ollama`) whose
prefix list was empty, so the match was always False and the model always None. The console
wrote the value, recorded a history row, showed the new number back, and no call changed. A pin
you cannot SEE arrive is a pin you cannot trust, so this reads the answer the only way that
cannot drift: it BUILDS each operator and asks the object what model it holds.

It never calls a provider and never spends anything — construction only. Tiers whose credential
is absent are reported as such rather than skipped, because "no key" and "no pin" look identical
in a table that omits both.

    .venv/bin/python scripts/model_pin_probe.py
    .venv/bin/python scripts/model_pin_probe.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prospector.config import load_config          # noqa: E402
from prospector import operator as op              # noqa: E402


def _model_of(o) -> str:
    """The model identifier an operator object is holding, whatever it calls the attribute."""
    for attr in ("model", "_model", "_default_model", "_models"):
        v = getattr(o, attr, None)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, (list, tuple)) and v:
            return ", ".join(str(x) for x in v)
    return "(adapter default)"


def probe(cfg) -> list[dict]:
    """One row per (component, provider) the config could build. Construction only."""
    rows: list[dict] = []
    table = getattr(cfg, "component_models", {}) or {}
    for comp in op.COMPONENTS:
        for kind in sorted(table.get(comp, {}) or {}):
            pin = op.component_pin(cfg, comp, kind)
            row = {"component": comp, "provider": kind, "pin": pin or ""}
            try:
                built = op._build_operator(kind, cfg, fast=False, component=comp)
                row["model"] = _model_of(built)
                row["status"] = "built"
            except RuntimeError as e:          # missing credential — a real, reportable state
                row["model"] = "-"
                row["status"] = f"no credential ({str(e)[:60]})"
            except Exception as e:             # noqa: BLE001 — unknown/removed tier
                row["model"] = "-"
                row["status"] = f"{type(e).__name__}: {str(e)[:60]}"
            row["source"] = ("component_models" if pin
                             else "model_defaults" if row["status"] == "built" else "-")
            rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable, for the ops console")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    rows = probe(cfg)
    if args.json:
        print(json.dumps({"rows": rows}, indent=2))
        return 0

    if not rows:
        print("component_models is empty — every chain uses model_defaults.")
        return 0
    w = max(len(r["provider"]) for r in rows)
    print(f"{'component':<12} {'provider':<{w}}  {'model in use':<34} source")
    print("-" * (14 + w + 36 + 18))
    last = None
    for r in rows:
        comp = r["component"] if r["component"] != last else ""
        last = r["component"]
        note = r["model"] if r["status"] == "built" else r["status"]
        print(f"{comp:<12} {r['provider']:<{w}}  {note:<34} {r['source']}")
    print("\nA `model_defaults` source means that slot is blank in component_models. "
          "Set one from the ops console (Config -> Brains) or in config.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
