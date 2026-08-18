"""How often each content rule is breached, per rule and per day.

P6 of `docs/CONTENT_CONTRACT_PROGRAM.md`, and the thing P5 and C2 are both waiting on. A rule
cannot be promoted from shadow to blocking on an opinion. It is promoted when its breach rate has
held at zero for long enough, and that sentence is only actionable if somebody is counting.

**Nothing new is written.** The counts were already on disk. Every pack the publish gate grades
leaves a `store/dossiers/<id>.lint.json` receipt carrying `problems`, and each problem carries the
name of the check that raised it. 123 receipts on 2026-08-17, 10,704 findings between them. This
module reads them. Adding a second recorder beside a receipt that already exists is how two
numbers for one fact get onto a dashboard, and the older one is usually the one people trust.

The split that matters is BLOCKING vs SHADOW, and it is not a property of the receipt. It is a
property of the live config: the same `house_quote` finding refuses a pack when
`house_spec_block_quotes` is on and is a note in a file when it is off. `content_contract`
answers that, from the config, so this module never restates a switch.

Two limits, stated because a rate quoted without them is misleading:

  * A receipt exists per pack GRADED, not per pack generated. A candidate that never reached the
    gate is not in the denominator. `coverage()` reports the receipt count so a caller can say so.
  * `checked_at` is when the pack was linted, not when it was generated. A backfill re-lints old
    packs and lands them all on one day. `by_day` is a grading rate, and it is named for that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from prospector import config as _config
from prospector import content_contract

#: A lint receipt per pack, written beside its dossier by the publish gate.
RECEIPT_GLOB = "*.lint.json"


def receipts_dir(cfg: Any = None) -> Path:
    """Where the lint receipts live.

    Resolved through `config.store_root()` rather than from `__file__`. A store path derived from
    the code's own location follows the CODE, which on 2026-08-17 split live state across two
    directories for twenty minutes.
    """
    store = getattr(cfg, "store_dir", None) if cfg is not None else None
    return Path(store or _config.store_root()) / "dossiers"


@dataclass
class RuleBreaches:
    """One rule's record across every receipt read."""

    check: str
    #: Total findings. One pack can raise the same check many times.
    findings: int = 0
    #: Packs in which the check was raised at least once. This is the number a rate is built on.
    packs: int = 0
    #: Findings the gate treats as fatal, given the live config.
    errors: int = 0
    #: Findings recorded but not acted on.
    warnings: int = 0
    #: True when the live config lets this rule refuse a pack.
    blocking: bool = False
    #: What the contract says fixes it, degraded to what the console can actually do.
    repair: str = content_contract.MANUAL
    #: `YYYY-MM-DD` -> packs in which it was raised that day.
    by_day: dict[str, int] = field(default_factory=dict)

    def rate(self, graded: int) -> Optional[float]:
        """Share of graded packs raising this check, or None when nothing was graded.

        None, never 0.0. A rule with no evidence and a rule with a clean record are the opposite
        of each other, and P5 promotes on the second one. Collapsing them into 0.0 would promote
        a rule that has never run.
        """
        return (self.packs / graded) if graded else None

    def as_dict(self, graded: int) -> dict[str, Any]:
        return {
            "check": self.check,
            "findings": self.findings,
            "packs": self.packs,
            "errors": self.errors,
            "warnings": self.warnings,
            "blocking": self.blocking,
            "repair": self.repair,
            "rate": self.rate(graded),
            "by_day": dict(sorted(self.by_day.items())),
        }


def read_receipts(cfg: Any = None, *, directory: Optional[Path] = None) -> list[dict]:
    """Every readable lint receipt. A torn or absent file is skipped, never raised.

    A dashboard that 500s because one receipt was half-written during a read is worse than a
    dashboard one pack short.
    """
    d = directory or receipts_dir(cfg)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(d.glob(RECEIPT_GLOB)):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _day(receipt: Mapping[str, Any]) -> str:
    stamp = str(receipt.get("checked_at") or "")
    return stamp[:10] if len(stamp) >= 10 else "unknown"


def tally(
    receipts: Iterable[Mapping[str, Any]],
    *,
    listing_cfg: Optional[Mapping[str, Any]] = None,
) -> dict[str, RuleBreaches]:
    """Fold receipts into one record per check.

    `listing_cfg` is the live `listing:` block. Omitting it does NOT mean "nothing is enforced" —
    it means the declared defaults, which is what a process with no config actually runs. `title`
    reads as blocking, `house_quote` as shadow. Pinned by
    `test_an_absent_config_falls_back_to_the_declared_default`.
    """
    blocking = content_contract.blocking_checks(listing_cfg or {})
    out: dict[str, RuleBreaches] = {}
    for receipt in receipts:
        day = _day(receipt)
        seen_here: set[str] = set()
        for problem in (receipt.get("problems") or []):
            if not isinstance(problem, Mapping):
                continue
            check = str(problem.get("check") or "").strip()
            if not check:
                continue
            rec = out.get(check)
            if rec is None:
                rec = out[check] = RuleBreaches(
                    check=check,
                    blocking=check in blocking,
                    repair=content_contract.console_repair_for_check(check),
                )
            rec.findings += 1
            if str(problem.get("severity")) == "error":
                rec.errors += 1
            else:
                rec.warnings += 1
            if check not in seen_here:
                seen_here.add(check)
                rec.packs += 1
                rec.by_day[day] = rec.by_day.get(day, 0) + 1
    return out


def clean_streak(rec: Optional[RuleBreaches], days: Iterable[str]) -> int:
    """Consecutive most-recent grading days on which this rule was never raised.

    The number P5 promotes on. `days` is the days on which ANY pack was graded, so a weekend with
    no runs does not read as a clean weekend — a rule cannot earn credit on a day nothing was
    checked.
    """
    streak = 0
    for day in sorted(days, reverse=True):
        if rec is not None and rec.by_day.get(day):
            break
        streak += 1
    return streak


def breach_report(cfg: Any = None, *, directory: Optional[Path] = None) -> dict[str, Any]:
    """The whole picture, in the shape the ops console renders.

    `shadow` is the interesting half: rules that are already grading and already producing
    findings, with nobody acting on them. `ready_to_promote` is P5's precondition — the console
    still does the promoting, because switching a rule on is an operator decision, not a cron
    job's. `never_observed` is held separate from it on purpose; see the note at that line.
    """
    listing_cfg = getattr(cfg, "listing", None)
    if not isinstance(listing_cfg, dict):
        listing_cfg = {}
    receipts = read_receipts(cfg, directory=directory)
    graded = len(receipts)
    records = tally(receipts, listing_cfg=listing_cfg)

    days_graded = sorted({_day(r) for r in receipts})
    declared = [r.check for r in content_contract.RULES]
    blocking = content_contract.blocking_checks(listing_cfg)

    rows = [records[c].as_dict(graded) for c in sorted(records, key=lambda c: -records[c].packs)]
    # A declared rule with no finding at all still belongs on the page. Its absence from the
    # receipts is the fact somebody is waiting for, and a table that only lists what broke can
    # never show it.
    silent = [
        RuleBreaches(check=c, blocking=c in blocking,
                     repair=content_contract.console_repair_for_check(c)).as_dict(graded)
        for c in declared if c not in records
    ]

    shadow_rows = [r for r in rows + silent if not r["blocking"]]

    # A RULE THAT NEVER RAN LOOKS EXACTLY LIKE A RULE WITH A CLEAN RECORD, and promoting the
    # first one is how a rule nobody has ever seen fire becomes a gate on the money path. The
    # receipts do not say which checks executed, only which raised something, so the two are not
    # distinguishable from a zero. They are separated here rather than merged into one flattering
    # number: `ready_to_promote` needs evidence the rule runs — at least one finding somewhere in
    # the history — plus a clean streak across every graded day. `never_observed` is the other
    # bucket, and it is a question for a human, not a candidate for promotion.
    observed = set(records)
    ready = [
        r["check"] for r in shadow_rows
        if r["check"] in observed
        and clean_streak(records.get(r["check"]), days_graded) >= len(days_graded) > 0
    ]
    never_observed = sorted(r["check"] for r in shadow_rows if r["check"] not in observed)

    return {
        "graded_packs": graded,
        "days_graded": days_graded,
        "rules": rows + silent,
        "blocking": [r for r in rows + silent if r["blocking"]],
        "shadow": shadow_rows,
        "ready_to_promote": sorted(ready),
        "never_observed": never_observed,
        "undeclared": sorted(set(records) - set(declared)),
        "coverage": coverage(graded),
    }


def coverage(graded: int) -> dict[str, Any]:
    """What the numbers above can and cannot see.

    Quoted on the panel, not buried here. A rate over a denominator nobody stated is the defect
    shape this repo has hit before: `ops/metrics.py` carries the same warning about
    `batch_diagnostics.jsonl` accounting for 1,228 of 2,376 catalogue rows.
    """
    return {
        "receipts": graded,
        "note": ("One receipt per pack the publish gate GRADED. A candidate that never reached "
                 "the gate is not counted, so these are rates over graded packs, not over "
                 "everything generated. `by_day` is keyed on when a pack was linted, not when "
                 "it was written: a re-lint backfill lands on one day."),
    }


def _totals(records: Mapping[str, RuleBreaches]) -> tuple[int, int]:
    return (sum(r.findings for r in records.values()),
            sum(r.packs for r in records.values()))
