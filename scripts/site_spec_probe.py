#!/usr/bin/env python3
"""Probe the live state of the mumchimp.com site spec.

`docs/SITE_SPEC_PROGRAM.md` carries a status ledger. Until now that ledger was PROSE, updated by
hand at the end of a session, and it drifted in both directions within a day of being written:

  - §6.6 said "Cause-of-death taxonomy visualisation not built." It was built. `kill-log.tsx`
    renders "How ideas die", a per-gate bar chart off live `byGate` data, and had done for some
    time. A session reading the ledger would have rebuilt a thing that already existed.
  - §2 was marked done and green while `kill-log.json` row 392 still published a raw confidence
    float, because every rule required the digits ADJACENT to the word and a single `(` slipped
    between them.

Both are the same failure: status asserted in a sentence instead of derived from the tree. This
script is the fix required by the global rule "state is a probe, not a paragraph". It re-derives
each item from disk and then CROSS-CHECKS the ledger against what it found, so the doc cannot
quietly disagree with the code.

    python3 scripts/site_spec_probe.py            # table + exit 1 on any drift
    python3 scripts/site_spec_probe.py --section 2

Exit codes:  0 = ledger and tree agree.  1 = at least one item drifted or failed.

Deliberately dependency-free and read-only. It must be runnable from a cold checkout by an agent
that has just been told "read the spec before touching the storefront", with nothing installed.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "store_platform" / "src" / "Store.Web"
SRC = WEB / "src"
SPEC = REPO / "docs" / "SITE_SPEC_PROGRAM.md"
KILL_LOG = SRC / "data" / "kill-log.json"

PASS, FAIL, NOT_STARTED = "PASS", "FAIL", "NOT STARTED"


@dataclass
class Result:
    status: str
    receipt: str
    details: list[str] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────────────────────


def _strip_comments(text: str) -> str:
    """Blank out comments, preserving newlines so line numbers survive.

    Every probe below that asserts "X is GONE" has to do this. These files document what they
    replaced, by name and by value -- `noArbitraryHex.test.ts` explains the exact hex it banned,
    `index.tsx` names the section it gave up in three separate docblocks. Matching the rationale
    makes a probe fail on its own documentation and teaches the next author to delete the
    explanation rather than keep the guarantee.
    """
    text = re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text)
    text = re.sub(r"\{/\*[\s\S]*?\*/\}", lambda m: re.sub(r"[^\n]", " ", m.group()), text)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def _source_files(*, suffixes=(".tsx", ".ts"), skip_tests=True) -> list[Path]:
    out = []
    for path in SRC.rglob("*"):
        if path.suffix not in suffixes or not path.is_file():
            continue
        parts = path.parts
        if skip_tests and ("__tests__" in parts or path.name.endswith(".test.ts")):
            continue
        if "node_modules" in parts:
            continue
        out.append(path)
    return out


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run a command, returning (exit code, combined output).

    `capture_output` rather than a pipe on purpose: `cmd | tail` reports TAIL's exit status, which
    is how a failing build reads as exit 0. The real status is captured before anything truncates.
    """
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out: {' '.join(cmd)}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ── §1  data integrity: one source of truth per number ───────────────────────────────────────

# The figures that were hand-typed and contradicted each other across five pages. `78`, `81`,
# `56`, `57` are NOT probed: they are ordinary small integers that appear legitimately as pixel
# values, array indices and weights, so grepping them produces noise that trains the reader to
# ignore this probe. The four-and-five-digit engine counts have no innocent explanation.
HAND_TYPED = ("1285", "1331", "1412", "1168", "1364")


def probe_data_integrity() -> Result:
    offenders = []
    for path in _source_files():
        stripped = _strip_comments(path.read_text(encoding="utf8"))
        for lineno, line in enumerate(stripped.splitlines(), 1):
            for number in HAND_TYPED:
                # Word-bounded, so `1168` does not match inside `21168` or a hex colour. The
                # bare-substring version of this class of check once benched a live provider.
                if re.search(rf"(?<![\d.]){number}(?![\d.])", line):
                    rel = path.relative_to(REPO)
                    offenders.append(f"{rel}:{lineno}  {line.strip()[:90]}")
    if offenders:
        return Result(FAIL, f"{len(offenders)} hand-typed engine count(s)", offenders)
    return Result(PASS, f"no hand-typed {'/'.join(HAND_TYPED)} outside comments")


# ── §2  publish pass: the four-field scan the spec says to re-run by hand ─────────────────────

FIELDS = ("title", "oneLiner", "gateLabel", "reason")

# Detectors written INDEPENDENTLY of `prospector/plain_text.py`. A probe that imports the code it
# grades only proves the code is self-consistent; row 392 was self-consistent and wrong.
DEFECTS: list[tuple[str, re.Pattern[str]]] = [
    # Exactly 16 hex chars, at least one digit, word-bounded -- so `defaced`/`facade` cannot match.
    ("hex ids", re.compile(r"\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{16}\b")),
    ("empty citations", re.compile(r"\(\s*,[\s,]*\)")),
    ("truncation", re.compile(r"(\.\.\.|…)\s*$")),
    # BOTH spellings. The adjacent form was covered from the start; the parenthesised form is the
    # one that shipped to production with the suite green.
    ("confidence floats", re.compile(r"conf(?:idence)?\s*(?:is\s*|of\s*)?\(?\s*[01]\.\d+", re.I)),
    ("denylist", re.compile(r"\bbroke\s+bod(?:y|ies)\b", re.I)),
]


def probe_publish_pass() -> Result:
    if not KILL_LOG.exists():
        return Result(FAIL, f"missing {KILL_LOG.relative_to(REPO)}")
    data = json.loads(KILL_LOG.read_text(encoding="utf8"))
    entries = data if isinstance(data, list) else data.get("entries", [])
    if not entries:
        # Vacuity guard. An empty list scores zero on every defect class and would report a
        # flawless publish pass over nothing at all.
        return Result(FAIL, "kill-log.json parsed to zero entries -- probe would be vacuous")

    hits: list[str] = []
    counts = {name: 0 for name, _ in DEFECTS}
    for i, entry in enumerate(entries):
        for field_name in FIELDS:
            value = entry.get(field_name)
            if not isinstance(value, str):
                continue
            for name, pattern in DEFECTS:
                match = pattern.search(value)
                if match:
                    counts[name] += 1
                    hits.append(f"row {i} .{field_name}  [{name}]  ...{match.group()[:40]}...")
    scanned = f"{len(entries)} entries x {len(FIELDS)} fields"
    if hits:
        summary = ", ".join(f"{n} {c}" for n, c in counts.items() if c)
        return Result(FAIL, f"{scanned}: {summary}", hits)
    return Result(PASS, f"{scanned}: all {len(DEFECTS)} defect classes 0")


# ── §5.2  vocabulary: one name per thing ─────────────────────────────────────────────────────

RETIRED = {
    "catalog": r"\bcatalog\b",  # en_GB: catalogue
    "shot": r"\bshot\b",
    "grounded": r"\bgrounded\b",
    "gauntlet": r"\bgauntlet\b",
    "dossier": r"\bdossiers?\b",
}
# Generated engine data and the API's own field names are out of scope: the vocabulary rule is
# about what the SITE says, and renaming a wire field is a different, breaking change.
VOCAB_SKIP = re.compile(r"/data/|/types/api|\.d\.ts$")


# §5.2 is a rule about the site's VOCABULARY -- what a reader sees -- not about identifiers.
#
# The first run of this probe reported 44 hits and the ledger said 0. Both were wrong in different
# ways. 12 were real: "dossier" is reader-facing on eight surfaces including /how-it-works and the
# post-purchase checklist. The other 32 were `/catalog` API routes, a `catalog: Pack[]` prop, a
# `#catalog` anchor and `console.error` strings -- renaming any of which is either a breaking wire
# change or pure churn, and none of which a buyer ever reads.
#
# So the probe reads PROSE: JSX text and sentence-shaped string literals. The narrowing is scoped
# on a principle rather than tuned until green -- and the check on that claim is that §5.2 stays
# FAIL after it, on the 12 that genuinely count.
# Sentence-shaped string literals, and JSX text nodes.
#
# Both are matched over the WHOLE FILE rather than line by line, with DOTALL. A line-scoped version
# of this reported 4 of the 12 real hits: JSX prose wraps across lines, and a text node that
# follows an interpolation starts at `}` rather than at `>`, so `{report.title}, the verification
# dossier` was invisible to it. Under-reporting is the worse failure of the two -- an over-eager
# probe gets argued with, a blind one gets believed.
# Quoted strings, matching the LANGUAGE: `'` and `"` cannot span newlines in JavaScript, only
# backticks can. The first cut allowed newlines in all three under re.S, so an apostrophe in JSX
# prose ("every pack's sources") opened a span that ran through the next 40 lines of code until it
# found another quote. That is where `; } } return out as T;` came from.
_PROSE_STRING = re.compile(r"""(['"])((?:(?!\1)[^\\\n]|\\.){20,}?)\1|`((?:[^`\\]|\\.){20,}?)`""", re.S)

# Two JSX text-node shapes, and the terminators matter:
#   >text<   or  >text{   -- a text node following a tag
#   }text<                -- a text node following an interpolation, e.g. `{title}, the QA report`
# A single combined `[>}]...[<{]` was tried and is WRONG: `}`-to-`{` also spans ordinary code, so
# `; } } export function Gauntlet({` scored as prose and the probe reported 30 where 12 were real.
# The `}`-started form must end at a TAG, which is what makes it a text node rather than a block.
_JSX_TEXT = (re.compile(r">([^<>{}]{10,}?)[<{]", re.S), re.compile(r"}([^<>{}]{10,}?)<", re.S))

# Strings the reader never sees, keyed off the line they sit on. Renaming an API route is a
# breaking wire change and renaming a thrown Error's message is churn; neither is vocabulary.
_NOT_READER_FACING = re.compile(r"console\.|^\s*import\b|new Error\(|throw ")

# A span carrying one of these is code, whatever shape it matched in. `;` is deliberately NOT here:
# it is a code signal but it is also every HTML entity, and `&ldquo;Packs&rdquo;` in terms.tsx is
# one of the real hits. `=` alone is enough to separate them.
_CODE_SMELL = re.compile(r"className=|=>|\w+\s*=\s*[({\[\"']|React\.|export |const |function ")


def probe_vocabulary() -> Result:
    offenders = []
    for path in _source_files():
        if VOCAB_SKIP.search(path.as_posix()):
            continue
        src = _strip_comments(path.read_text(encoding="utf8"))
        # offset -> line number, so a whole-file match can still be reported as file:line.
        line_starts = [0]
        for ch in re.finditer(r"\n", src):
            line_starts.append(ch.end())
        lines = src.splitlines()

        spans: list[tuple[int, str]] = []
        for m in _PROSE_STRING.finditer(src):
            # group 2 = the '/" body, group 3 = the backtick body; exactly one is set.
            body, start = (m.group(2), m.start(2)) if m.group(2) is not None else (m.group(3), m.start(3))
            spans.append((start, body))
        # JSX text only in `.tsx`. Applied to `.ts` the `>...<` form matches TypeScript generics --
        # `Promise<Pack[]>` and friends -- and reported `export async function fetchCatalog():` as
        # reader-facing copy.
        if path.suffix == ".tsx":
            for pattern in _JSX_TEXT:
                spans += [(m.start(1), m.group(1)) for m in pattern.finditer(src)]

        def line_of(offset: int) -> int:
            return bisect.bisect_right(line_starts, offset)

        for offset, text in spans:
            flat = " ".join(text.split())
            # A path or fragment is not prose even when it is long: '/catalog/waitlist'.
            if " " not in flat or flat.startswith(("/", "#")) or _CODE_SMELL.search(flat):
                continue
            if _NOT_READER_FACING.search(lines[line_of(offset) - 1] if line_of(offset) <= len(lines) else ""):
                continue
            for word, pattern in RETIRED.items():
                # Reported at the line the TERM sits on, not the line the SPAN opens on. Prose
                # wraps, so the first cut pointed at a bare `>` two lines above the word and read
                # as a false positive. A probe you have to go hunting from is one you stop running.
                for hit in re.finditer(pattern, text, re.I):
                    lineno = line_of(offset + hit.start())
                    offenders.append(f"{path.relative_to(REPO)}:{lineno}  [{word}]  {flat[:80]}")

    # De-duplicate: a string literal inside a JSX attribute is matched by both extractors.
    offenders = sorted(set(offenders))
    if offenders:
        return Result(FAIL, f"{len(offenders)} retired term(s) in reader-facing copy", offenders)
    return Result(PASS, f"0 reader-facing instances of {'/'.join(RETIRED)}")


# ── §5.3 / §6  the suites that own their own proof ───────────────────────────────────────────


def probe_ownership() -> Result:
    code, out = _run(["npx", "vitest", "run", "src/__tests__/factOwnership.test.ts"], WEB)
    match = re.search(r"Tests\s+(\d+) passed", out)
    if code == 0 and match:
        return Result(PASS, f"factOwnership.test.ts {match.group(1)} passed")
    return Result(FAIL, "factOwnership.test.ts failed", out.strip().splitlines()[-12:])


def probe_source_chip() -> Result:
    code, out = _run(["npx", "vitest", "run", "src/__tests__/sourceChipIsTheOnlyOne.test.ts"], WEB)
    match = re.search(r"Tests\s+(\d+) passed", out)
    if code == 0 and match:
        return Result(PASS, f"one <SourceChip>; guard {match.group(1)} passed")
    return Result(FAIL, "a surface hand-rolls its own source link", out.strip().splitlines()[-14:])


def probe_typecheck() -> Result:
    code, out = _run(["npx", "tsc", "--noEmit"], WEB)
    if code == 0:
        return Result(PASS, "tsc --noEmit 0 errors")
    return Result(FAIL, f"tsc exit {code}", out.strip().splitlines()[-12:])


def probe_taxonomy() -> Result:
    """§6.6's cause-of-death visualisation, asserted as DATA-DRIVEN, not merely present.

    The ledger called this "not built" while it had been shipped, which is the drift this whole
    script exists to catch. But "the section exists" is too weak a probe to be worth trusting: a
    chart of hardcoded numbers would satisfy it and would violate §1 (one source per number) at the
    same time. So this checks three things -- the labelled section, the `.map(` over a derived
    `distribution`, and that bar widths come from a live count -- and any one of them going missing
    reports FAIL rather than quietly narrowing what ✅ means.
    """
    src = (WEB / "src" / "pages" / "kill-log.tsx").read_text(encoding="utf-8")
    missing = [
        name
        for name, pattern in (
            ('section aria-labelledby="distribution-heading"', r'aria-labelledby="distribution-heading"'),
            ("distribution.map over derived data", r"\{distribution\.map\("),
            ("bar width from a live count", r"d\.count\s*/\s*distributionMax"),
            ("published/unpublished legend", r"d\.published\s*\?"),
        )
        if not re.search(pattern, src)
    ]
    if missing:
        return Result(FAIL, f"taxonomy chart incomplete: {len(missing)} marker(s) missing", missing)
    line = next(
        (i for i, ln in enumerate(src.splitlines(), 1) if 'id="distribution-heading"' in ln), 0
    )
    return Result(PASS, f'"How ideas die" chart, live byGate data (kill-log.tsx:{line})')


def _globals_css() -> str:
    return (WEB / "src" / "styles" / "globals.css").read_text(encoding="utf-8")


def probe_motion() -> Result:
    """§3.5 motion — the easing and the reduced-motion floor, which are the falsifiable half.

    §3.5 names four tokens. Three of its VALUES already ship under different names, so a probe that
    grepped for `--t-micro` would report "not started" on a site that already animates at 120ms on
    §3.5's exact curve. What is genuinely checkable is the curve and the accessibility floor §3.5
    calls non-negotiable; the signature resolve sequence is a feature, tracked separately, and a
    token file with no animation behind it would be dead weight.
    """
    css = _globals_css()
    checks = {
        "§3.5 easing curve": r"cubic-bezier\(0\.2,\s*0,\s*0,\s*1\)",
        "120ms micro duration": r"--transition-fast:\s*all\s*0\.12s",
        "reduced-motion catch-all": r"prefers-reduced-motion:\s*reduce[\s\S]{0,400}?\*,\s*\*::before,\s*\*::after",
        "reduced motion reaches view transitions": r"::view-transition-group\(\*\)",
    }
    missing = [name for name, pattern in checks.items() if not re.search(pattern, css)]
    if missing:
        return Result(FAIL, f"{len(missing)} motion floor(s) missing", missing)
    return Result(PASS, "easing + 120ms + reduced-motion floor (resolve sequence: not built)")


def probe_view_transitions() -> Result:
    """§7's transitions half. The LCP half is unmeasured and says so."""
    css = _globals_css()
    if not re.search(r"@view-transition\s*\{\s*navigation:\s*auto", css):
        return Result(NOT_STARTED, "no @view-transition rule in globals.css")
    named = _run(["git", "grep", "-l", "viewTransitionName", "--", "src"], WEB)[1].split()
    if not named:
        return Result(FAIL, "@view-transition declared but nothing claims a name", [])
    return Result(PASS, f"cross-doc view transitions live; {len(named)} file(s) name an element (LCP unmeasured)")


def probe_not_started(label: str):
    def _probe() -> Result:
        return Result(NOT_STARTED, label)

    return _probe


# ── the ledger cross-check ───────────────────────────────────────────────────────────────────

PROBES = {
    "1": ("Data integrity", probe_data_integrity),
    "2": ("Publish pass", probe_publish_pass),
    "3": ("Design system", probe_not_started("superseded by brand v3 -- see ledger note")),
    "4a": ("Source chip", probe_source_chip),
    "4b": ("QA row / glyph strip", probe_not_started("still per-surface; 5 QA-row shapes")),
    "3.5": ("Motion floor", probe_motion),
    "5.2": ("Vocabulary", probe_vocabulary),
    "5.3": ("Ownership map", probe_ownership),
    "6.1": ("Pages typecheck", probe_typecheck),
    "6.6": ("Kill-log taxonomy", probe_taxonomy),
    "6.7": ("Intent search", probe_not_started("skills picker not merged into one intent input")),
    "7": ("View transitions", probe_view_transitions),
}

# How a ledger glyph maps onto what the probe is allowed to report.
LEDGER_EXPECTS = {"✅": {PASS}, "🟡": {PASS, FAIL, NOT_STARTED}, "❌": {NOT_STARTED, FAIL}}


def read_ledger() -> dict[str, str]:
    """Map section id -> status glyph, read from the ledger table in the spec."""
    if not SPEC.exists():
        return {}
    ledger = {}
    for line in SPEC.read_text(encoding="utf8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        section = cells[0]
        # `4a` / `4b` as well as `4` and `5.2`: a spec section splits when the work does, and the
        # first cut of this pattern silently skipped the split rows -- which, combined with a `?`
        # counting as agreement, meant two whole programme items reported nothing at all.
        if not re.fullmatch(r"\d+(\.\d+)?[a-z]?", section):
            continue
        glyph = next((g for g in LEDGER_EXPECTS if g in cells[3]), None)
        if glyph:
            ledger[section] = glyph
    return ledger


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", help="probe one section only, e.g. 2 or 5.3")
    ap.add_argument("--verbose", action="store_true", help="print every offending line, not the first 10")
    args = ap.parse_args()

    ledger = read_ledger()
    sections = [args.section] if args.section else list(PROBES)
    if args.section and args.section not in PROBES:
        print(f"no probe for §{args.section}; known: {', '.join(PROBES)}", file=sys.stderr)
        return 2

    print(f"── SITE SPEC PROBE ── {SPEC.relative_to(REPO)}\n")
    print(f"{'§':<5} {'ITEM':<20} {'LEDGER':<7} {'PROBE':<11} RECEIPT")
    print("─" * 100)

    drifted: list[str] = []
    for section in sections:
        label, probe = PROBES[section]
        result = probe()
        glyph = ledger.get(section, "?")
        # A probe with no ledger row is DRIFT, not agreement. The first cut treated `?` as "no
        # opinion, carry on", and §4a/§4b -- two live programme items -- printed `?` and passed.
        # The whole contract of this script is that the doc and the tree are tied together; a row
        # the parser cannot see is the tie being quietly cut, which is the failure it exists to
        # catch, so it must never be the quiet case.
        agree = result.status in LEDGER_EXPECTS.get(glyph, set())
        mark = " " if agree else ("  <-- NO LEDGER ROW" if glyph == "?" else "  <-- DRIFT")
        print(f"{section:<5} {label:<20} {glyph:<7} {result.status:<11} {result.receipt}{mark}")
        shown = result.details if args.verbose else result.details[:3]
        for detail in shown:
            print(f"        {detail}")
        # Never truncate silently. A capped list with no note reads as "that was all of them",
        # which is how a 44-hit failure gets reported and acted on as a 10-hit failure.
        if len(shown) < len(result.details):
            print(f"        ... {len(result.details) - len(shown)} more (--verbose for all)")
        if not agree:
            says = "has NO row in the ledger table" if glyph == "?" else f"says {glyph}"
            drifted.append(f"§{section}: ledger {says}, tree says {result.status} ({result.receipt})")

    print()
    if drifted:
        print("LEDGER DRIFT -- the doc and the tree disagree. Fix the tree, or fix the ledger:")
        for line in drifted:
            print(f"  - {line}")
        return 1
    print("Ledger agrees with the tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
