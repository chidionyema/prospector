#!/usr/bin/env python3
"""Build OUR corpus: the prose this engine actually generates, as a buyer reads it.

Read-only over `store/`. One text file per dossier under `corpora/ours/`, plus a manifest
of ids and hashes so a keyness result can be reproduced without shipping the text.

WHAT COUNTS AS OUR PROSE, and why each field is in or out:
  IN   candidate title, one_liner, hypothesis, who_pays, why_now — the buyer reads all five
  IN   checks[].rationale — the reasoning, the part that most resembles a decision
  IN   adversarial.kill_case — the case against
  OUT  citations, source_ids, urls, queries — machine strings, not writing
  OUT  sources[].text — that is the WEB's prose, not ours. Measuring it would tell us how
       journalists write, which is not the question.

Usage:
    python -m tools.corpus.build_ours --store ../prospector/store --words 500000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.corpus.text import tokens  # noqa: E402

PROSE_FIELDS = ("title", "one_liner", "hypothesis", "who_pays", "why_now")


def document(dossier: dict) -> str:
    """One dossier rendered as the prose it contains, paragraph-separated.

    Paragraph breaks matter: `text.profile` measures paragraph length, so joining these
    with single newlines would report one paragraph per document and make that measure a
    constant.
    """
    parts: list[str] = []
    cand = dossier.get("candidate") or {}
    for f in PROSE_FIELDS:
        v = str(cand.get(f) or "").strip()
        if v:
            parts.append(v if v.endswith((".", "!", "?")) else v + ".")
    for check in dossier.get("checks") or []:
        v = str((check or {}).get("rationale") or "").strip()
        if v:
            parts.append(v)
    adv = dossier.get("adversarial") or {}
    for f in ("kill_case", "risk_summary"):
        v = str(adv.get(f) or "").strip()
        if v:
            parts.append(v)
    for ob in adv.get("objections") or []:
        for f in ("objection", "what_would_have_to_be_true"):
            v = str((ob or {}).get(f) or "").strip()
            if v:
                parts.append(v)
    return "\n\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default="store", help="store/ directory to read dossiers from")
    ap.add_argument("--out", default="corpora/ours")
    ap.add_argument("--words", type=int, default=500_000, help="stop once this many words are written")
    ap.add_argument("--min-words", type=int, default=120,
                    help="skip stubs; a 20-word dossier is a lint artefact, not writing")
    args = ap.parse_args()

    src = Path(args.store).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = sorted((src / "dossiers").glob("*.json"), reverse=True)  # newest ids first
    if not files:
        print(f"NO DOSSIERS under {src / 'dossiers'}", file=sys.stderr)
        return 2

    manifest: list[dict] = []
    total = 0
    skipped_stub = skipped_bad = 0
    for f in files:
        if total >= args.words:
            break
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            # Narrow: a torn write or an unreadable file. Counted and reported below, never
            # silently dropped — a corpus that quietly lost a tenth of its input is a
            # measurement nobody can reproduce.
            skipped_bad += 1
            continue
        text = document(d)
        n = len(tokens(text))
        if n < args.min_words:
            skipped_stub += 1
            continue
        (out / f"{f.stem}.txt").write_text(text)
        manifest.append({"id": f.stem, "words": n, "decision": d.get("decision"),
                         "created_at": d.get("created_at"),
                         "sha256": hashlib.sha256(text.encode()).hexdigest()[:16]})
        total += n

    (out.parent / "ours.manifest.jsonl").write_text(
        "".join(json.dumps(m) + "\n" for m in manifest))
    print(f"OURS: {len(manifest)} documents, {total:,} words -> {out}")
    print(f"  skipped: {skipped_stub} under {args.min_words} words, {skipped_bad} unreadable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
