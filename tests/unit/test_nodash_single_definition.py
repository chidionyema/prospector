"""`nodash` must have exactly ONE Python definition.

Written after the second de-dup missed a third copy. `tools/make_kill_log.py` was collapsed
onto `prospector.plain_text.nodash` on 2026-08-07, and that read as "the duplication is now
fixed" — but `store_platform/scripts/backfill_pack_telemetry.py` had been carrying its own
since 2026-06-21 and nobody grepped for the definition, only for the one they already knew
about. The stale copy predated two corrections to the shared one, so it silently disagreed
with it on 1701 of 4854 live candidate fields (35.0%), measured 2026-08-08:

    "NHS hospital nursing staff (Band 5-7)"  ->  "(Band 5, 7)"      # a range became a list
    "WitnessPack — A UK gig worker's ..."    ->  "WitnessPack , A"  # missing the tidy step

The first of those is the failure that matters: it states something the source does not, which
on a source-or-die storefront is worse than leaving the dash in. That script writes straight
into the Packs table, so the only thing standing between the divergence and a buyer was that
nobody had run the runbook step recently.

A test that pins the FIXED call sites would not have caught this — the defect was a call site
nobody had thought of. Pinning the DEFINITION COUNT is what makes a fourth copy impossible.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The one legitimate twin is cross-language and cannot be imported away: the storefront needs
# `nodash` at render time in TypeScript. It is pinned separately, below.
TS_TWIN = Path("store_platform/src/Store.Web/src/lib/text.ts")

_DEF = re.compile(r"^def nodash\b", re.M)


def _tracked_python_files() -> list[Path]:
    """Ask git, so .venv / node_modules / build output can never be scanned by accident."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def test_nodash_has_exactly_one_python_definition() -> None:
    definers = []
    for path in _tracked_python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _DEF.search(text):
            definers.append(path.relative_to(ROOT).as_posix())

    assert definers == ["prospector/plain_text.py"], (
        "`nodash` must be defined once, in prospector/plain_text.py, and imported everywhere "
        f"else. Found {len(definers)} definition(s): {definers}. A second copy does not stay "
        "in lock-step; the last one drifted for seven weeks and corrupted a numeric range."
    )


def test_the_typescript_twin_still_carries_the_numeric_range_guard() -> None:
    """The one copy that must exist, pinned on the rule it is most likely to lose.

    `text.ts` cannot import the Python function, so lock-step here is a promise rather than a
    mechanism. The digit-range guard is the rule that was missing from BOTH stale copies, which
    makes it the honest canary: if it disappears from the TypeScript, the storefront has started
    rewriting "Band 5-7" as "Band 5, 7" at render time.
    """
    ts = (ROOT / TS_TWIN).read_text(encoding="utf-8")
    assert "NUMERIC_RANGE" in ts, (
        f"{TS_TWIN} no longer references NUMERIC_RANGE. The TypeScript nodash has fallen out "
        "of lock-step with prospector/plain_text.py:nodash on digit ranges."
    )
    # The guard has to be APPLIED, not merely declared — a dead constant is not a rule.
    assert re.search(r"\.replace\(\s*NUMERIC_RANGE\s*,", ts), (
        f"{TS_TWIN} declares NUMERIC_RANGE but no longer applies it in nodash()."
    )


# --------------------------------------------------------------------------------------
# The backfill writes storefront columns directly. These pin its output on a FIXTURE, never
# on `store/dossiers` — that store is uncommitted, so a test reading it passes on a developer
# checkout and fails in CI on an empty directory, which is exactly how the E1 harness test
# came to be green locally and red on every runner.
# --------------------------------------------------------------------------------------

def _backfill_module():
    path = ROOT / "store_platform/scripts/backfill_pack_telemetry.py"
    spec = importlib.util.spec_from_file_location("_bpt_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# who_pays long enough to cross both the 220 (WhoPays) and 240 (extract) limits, with a real
# sentence end sitting before each so a word-boundary cut has somewhere honest to land.
# NOTE the EN DASH in "1–10". A plain hyphen is inert — neither implementation rewrites it —
# so a fixture written with one makes the range assertion below pass against the very code it
# is supposed to reject. Caught by running this test against the pre-fix module before trusting
# it; an assertion that cannot fail is not a guard.
_LONG_WHO_PAYS = (
    "UK construction subcontractors, sole traders and small firms with 1–10 employees, who "
    "depend on CIS Gross Payment Status to keep 20% to 30% of every invoice out of HMRC's "
    "hands until year end. They pay because losing that status is a cash-flow event. "
    "A secondary payer is the contractor's own accountant, who is blamed for the loss."
)

_FIXTURE = {
    "candidate": {"who_pays": _LONG_WHO_PAYS, "title": "CISGuard — the Band 5-7 case"},
    "checks": [
        {"verdict": "supported", "rationale": "HMRC publishes the compliance test.",
         "sources": [{"url": "https://gov.uk/a"}, {"url": "https://gov.uk/b"}]},
    ],
    "score": {"scores": {"pain_acuity": 4}},
    "created_at": "2026-08-08T00:00:00Z",
}


def test_the_backfill_never_writes_a_mid_word_fragment_to_the_storefront() -> None:
    """A character-count slice puts half a word on a buyer's card.

    The `Who pays.` extract used to be built with a raw `[:240]`, unlike its three siblings,
    which all went through `first_sentence`. Over the 79 PASS dossiers on disk on 2026-08-08
    that produced 68 fragments ending like "...they cut their own paid work to provide care.
    They pa". This pins the boundary, not the length.
    """
    t = _backfill_module().telemetry(_FIXTURE)
    fields = {"WhoPays": t["WhoPays"], "ProofPoint": t["ProofPoint"]}
    for i, s in enumerate(json.loads(t["SampleExtractJson"])):
        fields[f"SampleExtract[{i}]"] = s

    for name, value in fields.items():
        assert value, f"{name} came back empty on a fixture that supplies it"
        assert re.search(r'[.!?)"\']$', value.strip()), (
            f"{name} ends mid-word or mid-clause: {value[-70:]!r}. Truncate on a word "
            "boundary (first_sentence), never with a character-count slice."
        )


def test_the_backfill_reads_ranges_through_the_shared_nodash() -> None:
    """The end-to-end version of the definition-count test above.

    Counting definitions proves there is one implementation; this proves this script actually
    reaches it. "1-10 employees" surviving as a RANGE is the specific thing the private copy
    got wrong, so it is the specific thing worth pinning at the call site.
    """
    mod = _backfill_module()
    from prospector.plain_text import nodash as canonical

    assert mod.nodash is canonical, "the backfill rebound nodash to a local implementation"
    assert "1-10 employees" in mod.telemetry(_FIXTURE)["WhoPays"], (
        "a numeric range was rewritten as a list; the digit-range guard is not being applied"
    )
