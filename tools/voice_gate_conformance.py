#!/usr/bin/env python3
# ruff: noqa: S310, S311, S603, S607 -- local conformance tool: loopback gate only, repo-local git, seeded fuzz
"""Voice Gate conformance harness — one script, three receipts (spec §9/§1).

Modes:
  diff    corpus match-set diff: Python oracle vs Rust gate over every prose leaf of the
          storefront data + git-history (pre-scrub) versions. Empty diff or the Rust gate
          earns nothing.
  fuzz    differential fuzzing: mutated real strings (dash insertion, banned-token injection,
          entity swaps, whitespace/case noise) must get the SAME verdict from both runtimes.
  golden  golden-sample vs oracle (runs when prospector/voice_gate/golden.jsonl exists —
          B1's deliverable; skips cleanly until then).

Usage: tools/voice_gate_conformance.py {diff|fuzz|golden|all} [--gate http://127.0.0.1:8420]
Receipts land in store/voice_gate/. Exit 1 on any disagreement.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.voice_gate.deny import findings_for, walk_prose  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "store_platform/src/Store.Web/src/data")
RECEIPTS = os.path.join(REPO, "store", "voice_gate")
LANE = "evidence-export"

# Same strip classes as register_lint.py:248-255 and the Rust prose.rs — span-preserving.
_STRIP = [
    re.compile(p, re.S | re.M)
    for p in (
        r"```.*?```",
        r"`[^`\n]+`",
        r"https?://\S+|www\.\S+",
        r"^\s*\|.*\|\s*$",
        r"^\s*>.*$",
        r"^\s{0,3}#{1,6}\s.*$",
    )
]


def prose_only(text: str) -> str:
    out = list(text)
    for rule in _STRIP:
        for m in rule.finditer(text):
            for i in range(m.start(), m.end()):
                if out[i] != "\n":
                    out[i] = " "
    return "".join(out)


def oracle_findings(text: str) -> set[tuple[str, int, int]]:
    return {(h.rule_id, h.start, h.end) for h in findings_for(prose_only(text))}


def corpus_leaves() -> list[tuple[str, str]]:
    """(source_tag, text) for every prose leaf in the live data + pre-scrub git versions."""
    items: list[tuple[str, str]] = []
    for name in sorted(os.listdir(DATA)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(DATA, name), encoding="utf-8") as handle:
            doc = json.load(handle)
        for _p, _k, path, text in walk_prose(doc):
            if len(text) >= 24:
                items.append((f"{name}{path}", text))
    for name in ("sample-report.json", "kill-log-examples.json"):
        try:
            raw = subprocess.run(  # noqa: S603,S607 -- fixed argv, repo-local git only
                ["git", "show", f"HEAD~2:store_platform/src/Store.Web/src/data/{name}"],
                capture_output=True,
                text=True,
                cwd=REPO,
                check=True,
            ).stdout
            for _p, _k, path, text in walk_prose(json.loads(raw)):
                if len(text) >= 24:
                    items.append((f"history:{name}{path}", text))
        except subprocess.CalledProcessError:
            pass
    return items


def rust_grade(gate: str, items: list[tuple[str, str]]) -> dict[str, set[tuple[str, int, int]]]:
    """Batch-grade through the Rust service; map back to source tags."""
    out: dict[str, set[tuple[str, int, int]]] = {}
    for i in range(0, len(items), 400):
        chunk = items[i : i + 400]
        body = json.dumps(
            {"items": [{"lane": LANE, "field": "prose", "text": text} for _tag, text in chunk]}
        ).encode()
        req = urllib.request.Request(
            f"{gate}/v1/grade", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 -- gate arg defaults to loopback
            payload = json.load(resp)
        for (tag, _text), result in zip(chunk, payload["results"], strict=True):
            out[tag] = {
                (f["rule_id"], f["span"]["start"], f["span"]["end"]) for f in result["findings"]
            }
    return out


def mode_diff(gate: str) -> dict:
    leaves = corpus_leaves()
    python_side = {tag: oracle_findings(text) for tag, text in leaves}
    rust_side = rust_grade(gate, leaves)
    diffs = [
        {
            "leaf": tag,
            "python_only": sorted(map(str, python_side[tag] - rust_side.get(tag, set()))),
            "rust_only": sorted(map(str, rust_side.get(tag, set()) - python_side[tag])),
        }
        for tag, _ in python_side.items()
        if python_side[tag] != rust_side.get(tag, set())
    ]
    return {"mode": "diff", "leaves": len(leaves), "diffs": diffs, "ok": not diffs}


def mutate(text: str, rng: random.Random, banned: list[str]) -> str:
    ops = ["dash", "banned", "entity", "case", "space"]
    op = rng.choice(ops)
    if op == "dash":
        pos = rng.randrange(0, max(1, len(text)))
        return text[:pos] + " — " + text[pos:]
    if op == "banned":
        return text + " " + rng.choice(banned)
    if op == "entity":
        return text.replace("£", "$").replace("2026", "2027")
    if op == "case":
        return text.upper() if rng.random() < 0.5 else text.lower()
    return re.sub(r"  +", " ", text.replace(". ", "  "))


def mode_fuzz(gate: str, n: int = 2000, seed: int = 42) -> dict:
    rng = random.Random(seed)  # noqa: S311 -- seeded for reproducible fuzz, not crypto
    leaves = [t for _tag, t in corpus_leaves() if len(t) >= 60]
    rng.shuffle(leaves)
    policy = json.loads(
        json.dumps(
            __import__("yaml").safe_load(
                open(os.path.join(REPO, "prospector/voice_policy.yaml"), encoding="utf-8")
            )
        )
    )
    banned = ["SUPPORTED", "the passages show", "premortem", "1 acas.org.uk"]
    for lane in policy["lanes"].values():
        for p in lane.get("deny_patterns", []):
            banned.append(p["id"])
    cases = []
    for base in leaves[: n // 4]:
        for _ in range(4):
            cases.append(mutate(base, rng, banned))
            if len(cases) >= n:
                break
    python_side = [bool(oracle_findings(c)) for c in cases]
    rust_side = rust_grade(gate, [("fuzz", c) for c in cases])
    rust_verdicts = [
        bool(rust_side.get(("fuzz"), set())) for _ in []
    ]  # placeholder, replaced below
    rust_verdicts = []
    for i in range(0, len(cases), 400):
        chunk = cases[i : i + 400]
        body = json.dumps(
            {"items": [{"lane": LANE, "field": "prose", "text": c} for c in chunk]}
        ).encode()
        req = urllib.request.Request(
            f"{gate}/v1/grade", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 -- gate arg defaults to loopback
            payload = json.load(resp)
        rust_verdicts.extend(r["verdict"] == "FAIL" for r in payload["results"])
    mismatches = [
        {"case": c[:120], "python": p, "rust": r}
        for c, p, r in zip(cases, python_side, rust_verdicts, strict=True)
        if p != r
    ]
    return {
        "mode": "fuzz",
        "cases": len(cases),
        "mismatches": mismatches[:20],
        "mismatch_count": len(mismatches),
        "ok": not mismatches,
    }


def mode_golden(gate: str) -> dict:
    golden = os.path.join(REPO, "prospector/voice_gate", "golden.jsonl")
    if not os.path.exists(golden):
        return {
            "mode": "golden",
            "ok": True,
            "skipped": "golden.jsonl not landed yet (B1 in flight)",
        }
    rows = [json.loads(line) for line in open(golden, encoding="utf-8") if line.strip()]
    python_verdicts = [bool(oracle_findings(r["text"])) for r in rows]
    rust_map = rust_grade(gate, [(r["id"], r["text"]) for r in rows])
    disagree = [
        {
            "id": r["id"],
            "expected": r["label"],
            "python": python_verdicts[i],
            "rust": bool(rust_map.get(r["id"], set())),
        }
        for i, r in enumerate(rows)
        if (r["label"] == "leak") != python_verdicts[i]
        or (r["label"] == "leak") != bool(rust_map.get(r["id"], set()))
    ]
    return {
        "mode": "golden",
        "rows": len(rows),
        "disagreements": disagree,
        "agreement": 1 - len(disagree) / max(1, len(rows)),
        "ok": not disagree,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["diff", "fuzz", "golden", "all"])
    parser.add_argument("--gate", default="http://127.0.0.1:8420")
    parser.add_argument("--cases", type=int, default=2000)
    args = parser.parse_args()

    os.makedirs(RECEIPTS, exist_ok=True)
    modes = ["diff", "fuzz", "golden"] if args.mode == "all" else [args.mode]
    ok = True
    for mode in modes:
        if mode == "diff":
            receipt = mode_diff(args.gate)
        elif mode == "fuzz":
            receipt = mode_fuzz(args.gate, n=args.cases)
        else:
            receipt = mode_golden(args.gate)
        receipt["gate"] = args.gate
        out = os.path.join(RECEIPTS, f"conformance-{mode}.json")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2)
        status = "OK" if receipt["ok"] else "FAIL"
        print(
            f"{status} {mode}: {out} "
            + json.dumps(
                {
                    k: v
                    for k, v in receipt.items()
                    if k in ("leaves", "cases", "mismatch_count", "rows", "agreement", "skipped")
                }
            )
        )
        ok = ok and receipt["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
