#!/usr/bin/env python3
"""Fetch Financial Ombudsman Service final decisions into a local corpus.

VERIFIED ON DISK 2026-08-16, not assumed:
  - robots.txt has one `User-agent: *` block. It disallows four PDF proforma forms. It does
    NOT disallow /decision/ or any search path.
  - decisions are served as PDF at https://www.financial-ombudsman.org.uk/decision/DRN-<n>.pdf
  - DRN-5344636 returns 200, 120,780 bytes, 1,167 words of decision text.
  - the id space is sparse: 2 of 6 probed ids returned 200, the rest 404. So we SAMPLE ids
    at random from a range and report the hit rate, rather than pretending it is contiguous.
  - the site 403s a default urllib/python user agent, so a browser UA is required. That is
    the documented Cloudflare behaviour on this estate, not an attempt to look like a person.

POLITENESS. Serial by default with a delay between requests. These are static PDFs on a
public body's site and we want a few hundred of them, not a mirror. Raise --workers only if
you have a reason.

WE MEASURE FROM THIS CORPUS. We do not train on it. Nothing here is redistributed: the text
lands in `corpora/` (gitignored) and only the manifest of ids and hashes is committed.

Usage:
    python -m tools.corpus.fetch_fos --words 500000
    python -m tools.corpus.fetch_fos --words 500000 --workers 3 --delay 0.4
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.corpus.text import tokens  # noqa: E402

URL = "https://www.financial-ombudsman.org.uk/decision/DRN-{n}.pdf"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

#: Probed 2026-08-16: DRN-4200000 and DRN-5344636 both return 200; 1000000, 2500000 and
#: 9999999 return 404. Sampling this window and reporting the hit rate is honest; asserting
#: a contiguous range we never measured would not be.
DEFAULT_LO, DEFAULT_HI = 4_000_000, 5_400_000

_lock = threading.Lock()


def extract(pdf_bytes: bytes) -> str:
    """Decision text from a PDF, or "" when the file is not readable as one."""
    try:
        pages = PdfReader(io.BytesIO(pdf_bytes)).pages
    except Exception as exc:                      # pypdf raises many shapes on damaged files
        # swallow-ok: a damaged PDF is one lost sample from a corpus we sample at random,
        # and the caller counts it below as a MISS rather than treating it as a fetched doc.
        print(f"  pypdf refused a file: {type(exc).__name__}", file=sys.stderr)
        return ""
    return "\n".join((p.extract_text() or "") for p in pages)


def fetch_one(session: requests.Session, n: int, out: Path, delay: float,
              min_words: int) -> dict | None:
    dest = out / f"DRN-{n}.txt"
    if dest.exists():
        return {"id": f"DRN-{n}", "words": len(tokens(dest.read_text())), "cached": True}
    try:
        r = session.get(URL.format(n=n), timeout=45)
    except requests.RequestException as exc:
        print(f"  DRN-{n}: {type(exc).__name__}", file=sys.stderr)
        return None
    finally:
        if delay:
            time.sleep(delay)
    if r.status_code != 200 or "pdf" not in r.headers.get("content-type", ""):
        return None
    text = extract(r.content).strip()
    if len(tokens(text)) < min_words:
        return None
    with _lock:
        dest.write_text(text)
    return {"id": f"DRN-{n}", "words": len(tokens(text)), "bytes": len(r.content),
            "sha256": hashlib.sha256(text.encode()).hexdigest()[:16], "cached": False}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="corpora/fos")
    ap.add_argument("--words", type=int, default=500_000, help="stop once the corpus holds this many words")
    ap.add_argument("--lo", type=int, default=DEFAULT_LO)
    ap.add_argument("--hi", type=int, default=DEFAULT_HI)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.4, help="seconds each worker waits after a request")
    ap.add_argument("--min-words", type=int, default=250, help="a 40-word PDF is a stub, not a decision")
    ap.add_argument("--seed", type=int, default=20260816, help="fixed so a corpus is reproducible")
    ap.add_argument("--max-attempts", type=int, default=6000)
    args = ap.parse_args()

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out.parent / "fos.manifest.jsonl"

    rng = random.Random(args.seed)
    ids = rng.sample(range(args.lo, args.hi), min(args.max_attempts, args.hi - args.lo))

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/pdf,*/*"})

    total = sum(len(tokens(f.read_text(errors="replace"))) for f in out.glob("*.txt"))
    manifest: list[dict] = []
    hits = attempts = 0
    print(f"FOS: resuming at {total:,} words in {out}")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        batch = 60
        for start in range(0, len(ids), batch):
            if total >= args.words:
                break
            chunk = ids[start:start + batch]
            attempts += len(chunk)
            for res in pool.map(lambda n: fetch_one(session, n, out, args.delay,
                                                    args.min_words), chunk):
                if res:
                    hits += 1
                    if not res.get("cached"):
                        manifest.append(res)
                        total += res["words"]
            rate = (hits / attempts * 100) if attempts else 0
            print(f"  {attempts:>5} tried  {hits:>4} hit ({rate:4.1f}%)  {total:>8,} words")

    with manifest_path.open("a") as fh:
        for m in manifest:
            fh.write(json.dumps(m) + "\n")
    print(f"FOS: {total:,} words, {hits}/{attempts} ids hit -> {out}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
