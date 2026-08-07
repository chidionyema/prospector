#!/usr/bin/env python3
"""Rewrite every em-dash and en-dash in the storefront source to natural punctuation.

The kill-log data-layer fix (tools/make_kill_log.py) removed them from the kill-log
JSON; this script does the same job for every committed .tsx source file under
store_platform/src/Store.Web/src/{pages,components}/.

Idempotent. Run again after a rewrite and nothing changes the second time.

Usage:
  python tools/site_wide_dash_cleanup.py            # dry-run report
  python tools/site_wide_dash_cleanup.py --apply   # write changes
"""
from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path

EM = "\u2014"
EN = "\u2013"

ROOT = Path("store_platform/src/Store.Web/src")
ROOTS = ("pages", "components", "lib")

# Order matters: more specific patterns first.
REPLACEMENTS: list[tuple[str, str, str]] = [
    # 1. Numeric ranges with an en-dash: "585–660px", "£15k–£80k". Comments only in our
    #    corpus, but the rule itself is safe everywhere; "100–200" reads as a range.
    (r"(\d)\u2013(\d)", r"\1 to \2", "en-dash range (digit\u2013digit)"),

    # 2. Em-dash followed by a newline + indent: "Brand \u2014\n  description". The drop
    #    is two characters: the em-dash and the trailing space. The newline+indent stays.
    (r"\s\u2014\n", ",\n", "em-dash before newline"),

    # 3. Em-dash at end of line (no trailing whitespace): "Market Limited</strong> \u2014"
    (r"\u2014\n", ",\n", "em-dash at end of line"),

    # 4. Em-dash followed by a closing quote/bracket: "Brand \u2014\""
    (r"\s\u2014([\"'\)])", r",\1", "em-dash before closing quote"),

    # 5. Em-dash preceded by an opening quote/bracket: "(\u2014 Brand)"
    (r"([\"'\(])\u2014\s", r"\1", "em-dash after opening quote"),

    # 6. Em-dash that closes a sentence on a non-quoted line (the most common case).
    (r"\s\u2014\s", ", ", "em-dash with surrounding spaces"),

    # 7. En-dash with surrounding whitespace.
    (r"\s\u2013\s", ", ", "en-dash with surrounding spaces"),

    # 8. Em-dash on a line by itself (e.g., a comment dash)
    (r"^\u2014\s*", "", "em-dash at start of line"),
]

# Pattern for ranges like "100\u2013200" (digit-digit) that the regex above catches; this
# is a fallback for non-numeric ranges if needed.
RANGE_DIGIT = re.compile(r"(\d)\u2013(\d)")


def transform(text: str) -> tuple[str, int]:
    """Apply every replacement in order; return (new_text, num_changes)."""
    changes = 0
    for pattern, replacement, _label in REPLACEMENTS:
        new_text, n = re.subn(pattern, replacement, text)
        if n:
            changes += n
            text = new_text
    return text, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Without this, just report the count.")
    args = parser.parse_args()

    files = sorted(
        sum(
            (
                glob.glob(str(ROOT / sub / "**" / "*.tsx"), recursive=True)
                + glob.glob(str(ROOT / sub / "**" / "*.ts"), recursive=True)
                for sub in ROOTS
            ),
            [],
        )
    )

    total_changes = 0
    total_files = 0
    for path in files:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text, n = transform(text)
        if n == 0:
            continue
        total_changes += n
        total_files += 1
        if args.apply:
            p.write_text(new_text, encoding="utf-8")
        else:
            print(f"  {n:>3} changes: {path}")

    if args.apply:
        print(f"rewrote {total_changes} em/en-dash(es) across {total_files} file(s)")
    else:
        print(f"dry-run: would rewrite {total_changes} em/en-dash(es) across {total_files} file(s)")
        print("re-run with --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
