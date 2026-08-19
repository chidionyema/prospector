"""Does the repair turn actually move draft two into the human range?

Runs the ENGINE's own loop (`artifacts._gen_one_artifact`) on real candidates, with
`_prose_findings` wrapped so every call is recorded. The loop calls it once per attempt, so
the recorded sequence is [draft-1 findings, draft-2 findings]. Claim-check is off
(`check_op=None`) so the only thing earning the second attempt is the register.

Report only. Writes nothing to store/.
"""
import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prospector import artifacts as A
from prospector.config import load_config
from prospector.models import Candidate
from prospector.operator import _build_operator
from prospector.prompts import ALL_MARKET_KEYS, market_kwargs  # noqa: F401

ap = argparse.ArgumentParser()
ap.add_argument("--packs", type=int, default=3)
ap.add_argument("--types", default="build_spec,gtm_plan,ops_plan")
args = ap.parse_args()

cfg = load_config(str(pathlib.Path(__file__).resolve().parent / "config.yaml"))
op = _build_operator("minimax", cfg, fast=False)
print(f"operator: {type(op).__name__}")

REC = []
_real = A._prose_findings
def _spy(content):
    out = _real(content)
    REC.append(out[0])
    return out
A._prose_findings = _spy

root = pathlib.Path("/Users/chidionyema/Documents/code/prospector/store/dossiers")
files = sorted(root.glob("*.pass.json"))[-args.packs:]
types = [t.strip() for t in args.types.split(",") if t.strip()]

moved = collections.Counter()
rows = []
for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    cand = Candidate.from_dict(d["candidate"])
    claims = [c for c in d.get("checks", []) if c.get("verdict") == "supported"]
    claims_json = json.dumps(A._claims_prompt_view(claims))
    cand_json = json.dumps(A._candidate_prompt_view(cand))
    mv = market_kwargs(cfg, market=getattr(cand, "market", "") or "")
    for t in types:
        REC.clear()
        try:
            _, content, _raw, _v = A._gen_one_artifact(
                op, cand_json, claims_json, t, mv, A._LEGACY_LENGTH_RULE,
                None, claims, True)
        except Exception as exc:
            print(f"FAILED {f.stem} {t}: {exc}")
            continue
        d1 = REC[0] if len(REC) > 0 else None
        d2 = REC[1] if len(REC) > 1 else None
        n1 = len(d1) if d1 is not None else -1
        n2 = len(d2) if d2 is not None else -1
        if n1 == 0:
            verdict = "draft1_already_in_range"
        elif n2 < 0:
            verdict = "no_second_measurement"
        elif n2 == 0:
            verdict = "REPAIRED"
        elif n2 < n1:
            verdict = "improved_not_in_range"
        elif n2 == n1:
            verdict = "unchanged"
        else:
            verdict = "worse"
        moved[verdict] += 1
        m1 = sorted(x["measure"] for x in (d1 or []))
        m2 = sorted(x["measure"] for x in (d2 or []))
        rows.append((f.stem[:8], t, n1, n2, verdict, m1, m2))
        print(f"{f.stem[:8]} {t:12s} draft1={n1} draft2={n2} {verdict}")
        print(f"    d1: {m1}")
        print(f"    d2: {m2}")

print("########## REGISTER REPAIR PROBE")
print(f"documents regenerated: {len(rows)}")
for k, n in moved.most_common():
    print(f"   {k:26s} {n}")
print("########## END")
