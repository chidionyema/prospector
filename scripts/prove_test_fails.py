#!/usr/bin/env python3
"""Prove a test can fail, and refuse to report a mutation check that never mutated anything.

WHY THIS EXISTS. A new test is worth nothing until it has been seen red. The ritual is to break
the code the test guards, run the test, and check it goes red — and that ritual failed twice in
one session on 2026-08-19, in two different ways, both of which looked like a clean pass:

  1. The patch did not apply. The indent assumed by the edit was wrong, `str.index` raised, the
     shell carried on, and the "mutant" run graded the unmutated file. 17 passed, reported as
     proof.
  2. The patch applied to one of two occurrences. `sed -i '' 's/x/y/'` without `g` replaced the
     first `router.query.open` on a line that held two, so the file still read the query string
     and the fence still passed. Reported as "the fence is vacuous", which it was not.

Both failures produce the same output as a genuinely vacuous test, so a human reading the terminal
cannot tell the three cases apart. This tool can: it counts the occurrences before, asserts they
are gone after, and INVERTS the exit code, so a mutation the command survives is the failure.

    scripts/prove_test_fails.py \\
        --file src/pages/docs.tsx --replace 'router.query.open' --with 'router.query.openX' \\
        -- npx vitest run tests/pages.test.ts

Exit 0 means: the mutation applied, and the command went red because of it. Files are restored
whether it passes, fails or crashes.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", action="append", required=True, type=Path,
                        help="file to mutate; repeat with matching --replace/--with")
    parser.add_argument("--replace", action="append", required=True,
                        help="exact text to replace, every occurrence")
    parser.add_argument("--with", action="append", required=True, dest="replacement",
                        help="what to put there instead")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="after `--`, the command that must go red")
    args = parser.parse_args(argv)

    command = [a for a in args.command if a != "--"]
    if not command:
        print("prove_test_fails: no command given after `--`", file=sys.stderr)
        return 2
    if not (len(args.file) == len(args.replace) == len(args.replacement)):
        print("prove_test_fails: --file, --replace and --with must be given the same number "
              "of times, in matching order", file=sys.stderr)
        return 2

    originals: dict[Path, str] = {}
    try:
        for path, old, new in zip(args.file, args.replace, args.replacement):
            text = path.read_text(encoding="utf-8")
            hits = text.count(old)
            if hits == 0:
                # The exact failure mode 1 above. A mutation that does not apply is not a
                # mutation, and reporting the run that follows it is reporting nothing.
                print(f"prove_test_fails: {path} does not contain {old!r}. Nothing was mutated, "
                      f"so nothing was proven.", file=sys.stderr)
                return 2
            originals.setdefault(path, text)
            mutated = text.replace(old, new)
            # Failure mode 2: a partial replacement leaves the guarded behaviour intact.
            if old in mutated:
                print(f"prove_test_fails: {old!r} still appears in {path} after replacing it. "
                      f"The replacement contains the original.", file=sys.stderr)
                return 2
            path.write_text(mutated, encoding="utf-8")
            print(f"mutated {path}: {hits} occurrence(s) of {old!r} -> {new!r}")

        print(f"running: {' '.join(command)}")
        result = subprocess.run(command)
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")
            print(f"restored {path}")

    if result.returncode == 0:
        print("\nFAILED TO PROVE: the mutation applied and the command still passed. The test "
              "does not guard what you think it guards.", file=sys.stderr)
        return 1
    print(f"\nPROVEN: the command exited {result.returncode} with the mutation in place, and "
          f"every file was restored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
