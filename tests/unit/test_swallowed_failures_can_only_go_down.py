"""A ratchet on the bug class that has cost this engine more than any other.

THE CLASS. A layer catches a failure and returns something that looks like an answer:
`except Exception: return []`, `if not isinstance(data, dict): data = {}`, a fallback chain
that quietly serves the next provider.  The system is built never to crash, so it never
crashes — it reports a plausible empty instead.  A swallowed failure has no stack trace and
no red test.  It has a normal-looking dossier.  That is why every instance of it has been
found in PRODUCTION.

WHAT IT DID, measured 2026-08-15.  Three layers in a row destroyed one MiniMax verdict:
`_extract_json` parsed strict (a literal newline in the model's rationale raised), its
Strategy 2 scanned `[`…`]` before `{`…`}` and returned the CITATIONS ARRAY, and
`verdict_for` coerced that unreadable shape to `{}` below the `except`, so nothing deferred.
Out came `unverifiable, conf 0.0, rationale ""` — and the golden promotion gate recorded
that MiniMax answers without reasons.  It doesn't.  We threw its answer away and wrote down
that it was silent, in the very measurement that decides whether this engine can run
without Claude Code.

At least twenty-two memory files describe this same class as if each were its own incident
(`a-swallowed-outage-returns-empty-it-does-not-raise`,
`empty-artifacts-are-a-swallowed-prose-operator-outage`,
`web-calls-counter-was-structurally-zero`, `a-saturated-metric-prints-as-a-confident-null`,
`learning-exa-silent-grounding-outage`, …).  It is one bug that keeps being rediscovered.

WHY A RATCHET AND NOT A BAN.  Returning `[]` is often correct — a search that genuinely
found nothing really does return `[]`.  The defect is never the empty value; it is that the
CALLER cannot tell "nothing matched" from "it broke".  No lint rule can decide that, and a
blanket ban would be ignored within a week.  A ratchet can: the count may fall freely and
may not rise without a human editing the baseline in the same commit, where a reviewer sees
it.  `tools/audit_swallow_sites.py` carries the tiering rules and the evidence for each.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "tools" / "audit_swallow_sites.py"
BASELINE = Path(__file__).with_name("swallow_ratchet_baseline.json")


def _audit() -> list[dict]:
    """Run the auditor as the tool, not as an import.

    `preflight-must-be-the-gates-own-command`: a gate that re-implements what it checks can
    pass while the real command fails. This shells out to the same script a human runs.
    """
    proc = subprocess.run(
        [sys.executable, str(AUDIT), "--json"],
        cwd=str(REPO), capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, (
        f"the swallow auditor itself failed (exit {proc.returncode}):\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def sites() -> list[dict]:
    return _audit()


def test_the_auditor_still_finds_the_defect_it_was_written_for(sites):
    """Prove the probe fires before trusting what it reports.

    A ratchet whose measuring instrument silently returns nothing reads as "zero swallowed
    failures" — which would be this exact bug class, in the tool built to detect it. So
    assert the instrument is alive: it must find a non-trivial number of sites overall, and
    it must still classify the two shapes it was calibrated on.
    """
    assert len(sites) > 50, (
        f"the auditor found only {len(sites)} sites across prospector/ — it is almost "
        "certainly broken or scanning the wrong path, not the codebase suddenly being clean")
    tiers = {s["tier"] for s in sites}
    assert tiers >= {1, 2, 3}, (
        f"the auditor produced only tiers {sorted(tiers)}; its classifier is not running")


def test_tier1_swallowed_failures_never_increase(sites):
    """THE RATCHET. Per FILE, so a regression names the file instead of a number.

    Tier 1 = a broad `except` handing back the same value the success path can return, with
    no failure flag reaching the caller. Nothing downstream can distinguish it from a real
    answer.

    If this fails on a file you touched: do not edit the baseline to make it green. Read
    `tools/audit_swallow_sites.py`'s contract and apply the fix ladder — propagate a typed
    error, or carry the failure in the return value, or (best-effort paths only) narrow the
    `except` and log at ERROR. Editing the baseline up is a decision to ship a failure the
    caller cannot see, and it belongs in a commit message where someone will read it.
    """
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["tier1_by_file"]
    current: dict[str, int] = {}
    for s in sites:
        if s["tier"] == 1:
            current[s["file"]] = current.get(s["file"], 0) + 1

    regressions = {f: (baseline.get(f, 0), n) for f, n in current.items()
                   if n > baseline.get(f, 0)}
    assert not regressions, (
        "new tier-1 swallowed failures — the caller cannot tell these from a real empty "
        "answer:\n" + "\n".join(
            f"  {f}: {was} -> {now}" for f, (was, now) in sorted(regressions.items()))
        + "\n\nRun: .venv/bin/python tools/audit_swallow_sites.py --tier 1")


def test_the_escape_hatch_stays_rare_and_stays_argued(sites):
    """The waiver is the part of this gate most likely to eat it.

    `# swallow-ok: <why>` at the site demotes a tier-1 finding to tier 3, because the fix
    ladder's step 3 is a real ending for a best-effort path and the auditor grades on
    except-breadth, which cannot see "best-effort by contract". The failure mode is obvious:
    waive twenty sites and the ratchet reads green over the same bug class it was built for.

    So the waivers are themselves ratcheted, and a waiver whose reason is too short to be a
    reason at all is REJECTED by the auditor (it keeps its tier and shows up in `notes`).
    Raising this number is a deliberate act that a reviewer sees in the diff, next to the
    code and next to the argument for it.
    """
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    waived = [s for s in sites if s.get("waiver")]
    rejected = [s for s in waived if s["waiver"].startswith("REJECTED")]
    assert not rejected, (
        "a `# swallow-ok:` marker with no real reason behind it:\n  " + "\n  ".join(
            f"{s['file']}:{s['line']} {s['func']} — {s['waiver']}" for s in rejected))
    assert len(waived) <= baseline["waivers"], (
        f"{len(waived)} waived swallow sites, baseline {baseline['waivers']}. Each waiver is "
        "a decision to keep a failure the caller cannot distinguish; adding one is fine and "
        "must be visible. Raise the baseline in the SAME commit as the waiver.\n  " +
        "\n  ".join(f"{s['file']}:{s['line']} {s['func']}" for s in waived))


def test_the_crown_jewel_path_holds_no_tier1_swallows(sites):
    """A floor, not a ratchet, on the files the whole engine's verdicts flow through.

    Retrieval and the verdict brain are where a swallowed failure becomes a KILL on a real
    idea — the outcome the project rule "an exception is never evidence; a failed call
    DEFERS" exists to prevent. Everywhere else a ratchet is enough; here the number is zero
    and stays zero.
    """
    protected = {
        "prospector/verify.py",
        "prospector/operator.py",
        "prospector/claude_cli.py",
        "prospector/gemini_cli.py",
        "prospector/health.py",
    }
    offenders = [f"{s['file']}:{s['line']} {s['func']} -> {s['returns']}"
                 for s in sites if s["tier"] == 1 and s["file"] in protected]
    assert not offenders, (
        "a tier-1 swallowed failure on the verdict path — this is how our own outage "
        "becomes a candidate's KILL:\n  " + "\n  ".join(offenders))
