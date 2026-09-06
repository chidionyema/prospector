#!/usr/bin/env python3
"""E-107 stage 2 — run our verdict head against human labels.

Runs under the engine venv (it imports prospector). Reads the sample written by
e107_sample.py; writes one JSON line per (pair, arm) as it goes, so a killed run
resumes instead of re-paying for the calls it already made.

WHAT IS BEING MEASURED, exactly, so nobody over-reads the number:
  the verdict BRAIN and the grounding DISCIPLINE — "rule only from the passage,
  silence means unverifiable" — against 200 pairs a human labelled. It is NOT
  the six-check polarity logic in prompts/verdict.md; that logic is about
  pain_reality / incumbency / payer_solvency and has no counterpart in a public
  set. The atom under all six checks is "does this passage support this claim",
  and that atom is what this scores.

THE TWO ARMS, and why there are two:
  trunc600 — the document cut to VERDICT_PASSAGE_TRUNCATE = 600 chars
             (verify.py:777), which is what the engine ships today.
  full     — the whole document.
  Everything else is identical: same model, same prompt, same temperature, same
  pairs. Measured on this sample, 177 of 200 documents (88.5%) are longer than
  600 chars and the median is 1932. So the difference between these two columns
  is the price the engine is paying for that truncation, in verdict accuracy,
  and nothing else can be confused for it.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

OUT = os.path.expanduser("~/.local/share/prospector-evalsets/e107")
SAMPLE = os.path.join(OUT, "sample.jsonl")

TRUNCATE = 600  # must equal verify.py VERDICT_PASSAGE_TRUNCATE; asserted below.

SYSTEM = """You are a ruthless, evidence-bound analyst. Rule ONLY from the passage
provided. No prior knowledge. If the passage does not address the claim, verdict
is "unverifiable". NEVER "supported" without a passage that directly supports it.
Cite the source_ids you relied on. Confident wrongness is the worst outcome.

VERDICT AXIOM:
  "supported"    = the passage AFFIRMS the claim.
  "refuted"      = the passage NEGATES the claim.
  "unverifiable" = the passage does not address the claim.

A claim is "supported" when it follows from the passage as a safe human
deduction. Do not demand that the passage restate the claim word for word.
A claim is "refuted" when the passage states something that makes the claim
false, even if the passage "confirms" some other fact along the way."""

USER = """Claim: {claim}

Passages:
[{sid}] {doc}

Output ONLY: {{"verdict":"supported|refuted|unverifiable","confidence":0.0,
 "rationale":"<=2 sentences, grounded strictly in the cited passage","citations":["source_id",...]}}
`rationale` is REQUIRED and must be non-empty. Write it as ONE LINE."""


def _load_done(path):
    done = set()
    if not os.path.exists(path):
        return done
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue  # a half-written last line from a killed run
            done.add((r["pair_id"], r["arm"]))
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="pairs to run (0 = all). Use a small number to price it first.")
    ap.add_argument("--arms", default="trunc600,full")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(OUT, "results.jsonl"))
    # PIN THE BRAIN. The engine chain fails over, so an unpinned run would score
    # whichever provider happened to have quota at that second and report one number
    # for a mixture. A benchmark whose subject changes mid-run is not a benchmark.
    ap.add_argument("--operator", default="",
                    help="override cfg.operator with a single named tier, e.g. claude_cli")
    args = ap.parse_args()

    from prospector.config import load_config
    from prospector.operator import make_operator
    from prospector import verify as V

    # The whole point of the trunc600 arm is that it matches what ships. If the
    # engine's constant moves, this benchmark is measuring a width the engine no
    # longer uses, and it must fail rather than quietly report a stale number.
    assert V.VERDICT_PASSAGE_TRUNCATE == TRUNCATE, (
        f"verify.py VERDICT_PASSAGE_TRUNCATE is {V.VERDICT_PASSAGE_TRUNCATE}, "
        f"this harness assumes {TRUNCATE} — update the arm and re-run.")

    cfg = load_config()
    if args.operator:
        cfg.operator = [args.operator]
    op = make_operator(cfg)
    # This run is SERIAL and no flag changes that. prospector/claude_cli.py:90 sets
    # MAX_CLAUDE_CLI = 1 on a founder directive of 2026-08-20 ("1 claude cli, not 4"), and
    # _clamped refuses any larger value, from config or from PROSPECTOR_CLAUDE_CONCURRENCY.
    # The governor is machine-wide (prospector/cli_governor.py), so --workers only decides how
    # many threads queue for the one slot. Measured 2026-08-21: p50 21.6s per call, ~28.5s end
    # to end, so 400 calls takes about 3 hours. Budget for that rather than tuning it.
    print(f"operator chain: {cfg.operator}  -> {getattr(op, 'name', type(op).__name__)}")

    pairs = [json.loads(l) for l in open(SAMPLE) if l.strip()]
    if args.limit:
        pairs = pairs[:args.limit]
    arms = [a for a in args.arms.split(",") if a]
    done = _load_done(args.out)
    todo = [(p, a) for p in pairs for a in arms if (p["pair_id"], a) not in done]
    print(f"{len(pairs)} pairs x {len(arms)} arms = {len(pairs) * len(arms)} calls; "
          f"{len(done)} already on disk; {len(todo)} to run")
    if not todo:
        return 0

    fh = open(args.out, "a")
    lock = __import__("threading").Lock()
    counter = {"n": 0, "err": 0}

    def one(job):
        pair, arm = job
        doc = pair["doc"]
        text = doc[:TRUNCATE] if arm == "trunc600" else doc
        sid = pair["pair_id"].replace("e107-", "s")
        t0 = time.time()
        rec = {"pair_id": pair["pair_id"], "arm": arm, "label": pair["label"],
               "source_dataset": pair["source_dataset"],
               "doc_chars": len(doc), "sent_chars": len(text)}
        try:
            data = op.complete_json(SYSTEM, USER.format(claim=pair["claim"], sid=sid,
                                                        doc=text), temperature=0.0)
            if isinstance(data, list):
                data = next((x for x in data if isinstance(x, dict)), None)
            if not isinstance(data, dict):
                raise ValueError(f"reply parsed to {type(data).__name__}")
            v = str(data.get("verdict", "unverifiable")).strip().lower()
            if v not in ("supported", "refuted", "unverifiable"):
                v = "unverifiable"
            cites = [str(c) for c in (data.get("citations") or [])]
            # source-or-die, exactly as verify.py:613 does it: `supported` with no
            # valid citation is not grounded, so it is downgraded. Leaving this out
            # would benchmark a laxer engine than the one that runs.
            cites = [c for c in cites if c == sid]
            if v == "supported" and not cites:
                v = "unverifiable"
                rec["downgraded_no_citation"] = True
            rec.update(verdict=v, cited=bool(cites),
                       llm_confidence=data.get("confidence"),
                       rationale=str(data.get("rationale", ""))[:400],
                       provider=getattr(op, "served_provider", lambda: None)()
                       if callable(getattr(op, "served_provider", None)) else None,
                       ok=True)
        except Exception as e:  # a failed CALL is not evidence; record it as a failure
            rec.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        rec["secs"] = round(time.time() - t0, 2)
        with lock:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            counter["n"] += 1
            if not rec["ok"]:
                counter["err"] += 1
            if counter["n"] % 20 == 0:
                print(f"  {counter['n']}/{len(todo)} done, {counter['err']} failed calls",
                      flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(one, todo))
    fh.close()
    print(f"DONE {counter['n']} calls in {time.time() - t0:.0f}s, "
          f"{counter['err']} failed -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
