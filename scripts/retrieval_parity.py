#!/usr/bin/env python3
"""Grade the Rust retrieval port against the Python it replaces, on live pages.

WHY THIS EXISTS. `engine-rs/crates/prospector-retrieval` is a port of the cheap path in
`prospector/retrieval.py:fetch_page`. Unit tests pin the shapes; they cannot tell you that the
two implementations return the same string on a real page, because the interesting divergences
are not in the extraction logic at all. The first one found here was the body cut: the Python
reads with `iter_content(8192)` and breaks on the first chunk that reaches `max_bytes`, so it
keeps 401,408 bytes; a plain `.take(400_000)` in Rust keeps 400,000, truncates the markup 1,408
bytes earlier, and the extracted text ends one word short. On
en.wikipedia.org/wiki/Rust_(programming_language) that was an 8-character diff in 30,771 --
invisible to every unit test, and exactly the kind of drift a cutover must not carry.

WHAT IT COMPARES. The FULL extracted text, before `select_passage` windows it. Comparing the
1500-char window would hide any divergence past the window, which is most of the page.

THE EXIT CODE IS THE VERDICT. 0 when every URL agrees, 1 when any disagrees, 2 when the harness
could not run. It prints the first disagreement per URL with surrounding context, because
"they differ" is not a finding and "they differ HERE" is.

    scripts/retrieval_parity.py --binary engine-rs/target/release/prospector-retrieval

NETWORK. This talks to the live web on purpose, so it is not a CI test and never will be: a
lane that fails when gov.uk is slow teaches everyone to ignore it.
"""
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_URLS = REPO / "tests" / "fixtures" / "retrieval_parity_urls.txt"
DEFAULT_BINARY = REPO / "engine-rs" / "target" / "release" / "prospector-retrieval"

#: `fetch_page` windows its result to `max_chars`. Ask for more than any page holds so the
#: window is a no-op and what comes back is the whole extraction.
NO_WINDOW = 10**9


def read_urls(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def python_text(url: str, timeout_s: float) -> str | None:
    """What `prospector/retrieval.py` extracts, with the passage window opened all the way."""
    from prospector.retrieval import fetch_page

    text, _published = fetch_page(url, timeout_s=timeout_s, max_chars=NO_WINDOW)
    return text


def rust_text(binary: Path, url: str, timeout_s: float) -> tuple[str | None, str | None]:
    """What the Rust binary extracts, and its refusal reason when it returns no page."""
    proc = subprocess.run([str(binary), url], capture_output=True, text=True,
                          timeout=timeout_s * 4, check=False)
    if proc.returncode != 0:
        return None, f"binary exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, f"binary printed no JSON: {proc.stdout.strip()[:200]!r}"
    return payload.get("text"), payload.get("error")


def first_disagreement(py: str, rs: str) -> str:
    """The first opcode where the two strings part, with enough context to name the cause."""
    matcher = difflib.SequenceMatcher(None, py, rs, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        return (f"    at python offset {i1} of {len(py)}: {tag}\n"
                f"      python: {py[i1:i2][:120]!r}\n"
                f"      rust:   {rs[j1:j2][:120]!r}\n"
                f"      before: {py[max(0, i1 - 80):i1][-80:]!r}")
    return "    (no differing opcode, but the strings compare unequal)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--urls", type=Path, default=DEFAULT_URLS)
    ap.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--url", action="append", default=[],
                    help="grade this URL instead of the corpus; repeatable")
    args = ap.parse_args()

    if not args.binary.exists():
        print(f"FATAL: no Rust binary at {args.binary}\n"
              f"       cargo build --release -p prospector-retrieval", file=sys.stderr)
        return 2

    urls = args.url or read_urls(args.urls)
    if not urls:
        print(f"FATAL: no URLs in {args.urls}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(REPO))
    disagreed = 0
    for url in urls:
        py = python_text(url, args.timeout)
        rs, err = rust_text(args.binary, url, args.timeout)
        if py == rs:
            shape = "no page" if py is None else f"{len(py)} chars"
            print(f"  agree   {shape:>12}  {url}")
            continue
        disagreed += 1
        print(f"  DIFFER  {url}")
        print(f"    python: {'no page' if py is None else str(len(py)) + ' chars'}")
        print(f"    rust:   {'no page' if rs is None else str(len(rs)) + ' chars'}"
              + (f"  ({err})" if err else ""))
        if py is not None and rs is not None:
            print(first_disagreement(py, rs))

    total = len(urls)
    if disagreed:
        print(f"\nPARITY FAILED: {disagreed} of {total} URL(s) disagree")
        return 1
    print(f"\nPARITY OK: {total} URL(s) extract identically in both implementations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
