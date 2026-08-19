"""Which finished packs cannot be sold, and the reason for each one.

Why this exists
---------------
A pack that clears every research gate still has to clear a publication gate before a buyer can
see it: it must be uploaded, complete, priced, bundled, lint-clean, and (when the fence is on)
figure-verified. A pack that clears the first and fails the second is *stranded* — the expensive
work is done and the revenue is zero, and nothing anywhere says so. The count was carried in a
person's head and in a programme doc, which is exactly the state `OPS_AUTOMATION_PRINCIPLES.md`
P4 exists to end: state is a probe, never a sentence.

So this answers one question, as a number, on demand: how many finished packs are not sellable,
and which gate is holding each one.

What it does NOT do
-------------------
It never repairs anything and it has no `--fix`. Repair means re-running content generation, which
costs model calls, and P3 plus R8 both say that is a separate, explicitly-invoked job with its cost
printed. This automation is the measurement that tells you whether the repair is worth buying.

It reports only what the local record can prove. Whether a pack is live on the shelf right now is a
question for the storefront, not for this checkout, and a check that guessed would be worse than no
check at all (P6).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTOMATION = "stranded_packs"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN = 2


class CannotEstablish(Exception):
    """Raised when the check cannot tell. Reported as `unknown`, never as clean."""


def _root() -> Path:
    """The CHECKOUT this code was loaded from. Correct for the declaration, and only for it.

    `ops/config/stranded_packs.yaml` ships beside the code and moves with it, so deriving its
    path from `__file__` is right. The STORE does not move with the code, which is why it is
    resolved separately by `_store()` below.
    """
    return Path(__file__).resolve().parents[2]


def _store() -> Path:
    """The store directory: `PROSPECTOR_STORE_DIR`, or `<checkout>/store` when it is unset.

    This probe read `_root() / "store" / "dossiers"` until 2026-08-19. On the engine the code is
    at /app and the store is a mounted volume at /data/store, so it looked in /app/store/dossiers,
    found nothing, and returned `status: unknown, error: no dossier directory`. The one automation
    built to answer "why is finished research not on the shelf" could not answer it in the only
    place the question is asked.

    It is the `__file__` trap CLAUDE.md documents, in a file written after the trap was
    documented. A comment is not a guard, so this resolution now goes through the same
    `config.store_root()` every other module uses, and
    `test_stranded_packs.py::test_the_dossier_dir_follows_the_store_not_the_code` fails if it
    ever goes back.
    """
    from prospector.config import store_root

    return store_root()


def _default_config() -> Path:
    return _root() / "ops" / "config" / f"{AUTOMATION}.yaml"


def load_declaration(path: Path) -> dict[str, Any]:
    """Read the YAML declaration. Every business fact this automation uses comes from here."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment defect, not a finding
        raise CannotEstablish(f"pyyaml is not installed: {exc}") from exc

    if not path.exists():
        raise CannotEstablish(f"no declaration at {path}")
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        raise CannotEstablish(f"declaration at {path} is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise CannotEstablish(f"declaration at {path} is not a mapping")
    return doc


def _pack_id(name: str) -> str:
    """The pack id is the part before the first dot.

    Dossier files are named `<id>.pass.json`, `<id>.kill.json`, `<id>.defer.json` and the lint
    record is `<id>.lint.json`. Reading the id with `Path.stem` yields `<id>.pass`, which then
    looks for `<id>.pass.lint.json` and finds nothing — every pack reads as unlinted and the
    check reports a catastrophe that is not happening. That mistake was made while building this,
    which is why the parsing lives in one named function with a test.
    """
    return name.split(".", 1)[0]


def scan(store: Path, decl: dict[str, Any]) -> dict[str, Any]:
    """Classify every passed pack by the first publication gate it fails.

    `store` is the STORE directory, not the checkout. `dossier_dir` is declared relative to it.
    """
    doss = store / str(decl.get("dossier_dir") or "dossiers")
    if not doss.is_dir():
        raise CannotEstablish(f"no dossier directory at {doss}")

    pass_glob = str(decl.get("pass_glob") or "*.pass.json")
    lint_suffix = str(decl.get("lint_suffix") or ".lint.json")

    passed = sorted(doss.glob(pass_glob))
    if not passed:
        raise CannotEstablish(
            f"no file in {doss} matches {pass_glob!r}; the naming has moved and every pack "
            f"would read as sellable")

    blocked: list[dict[str, Any]] = []
    by_reason: Counter = Counter()
    problem_codes: Counter = Counter()
    sellable = 0

    for path in passed:
        pid = _pack_id(path.name)
        lint = doss / f"{pid}{lint_suffix}"

        if not lint.exists():
            by_reason["never_linted"] += 1
            blocked.append({"where": pid, "what": "no lint record: the publication gate has "
                                                  "never been run on this pack"})
            continue

        try:
            record = json.loads(lint.read_text())
        except Exception as exc:
            by_reason["lint_unreadable"] += 1
            blocked.append({"where": pid, "what": f"lint record will not parse: {exc}"})
            continue

        if record.get("ok"):
            sellable += 1
            continue

        # The linter names its rule in `check`; `code`/`rule` are accepted too so this survives a
        # rename in the linter without going quiet. "unnamed" is deliberately visible rather than
        # silently dropped: a reason we cannot read is a reason nobody will fix.
        #
        # ONLY severity=error, because only an error blocks a sale. Measured 2026-08-17 across
        # 123 lint receipts: 10,546 warnings against 197 errors, NO pack fails on warnings alone,
        # and 47 packs are sellable while carrying warnings. Counting both made this report name
        # house_style, house_quote, human_register and repetition as the top four blockers, each
        # on all 73 stranded packs -- four rules that have never blocked anything. The real list
        # is nine checks led by shelf_copy (42 packs) and placeholders (21). A report that points
        # at the wrong repair is worse than no report: it costs a day fixing prose that was never
        # in the way. Anything without a severity counts, so a linter that stops emitting the
        # field fails loud rather than reporting zero blockers.
        codes = sorted({str(p.get("check") or p.get("code") or p.get("rule") or "unnamed")
                        for p in (record.get("problems") or []) if isinstance(p, dict)
                        and p.get("severity", "error") == "error"})
        for code in codes:
            problem_codes[code] += 1
        by_reason["lint_failed"] += 1
        blocked.append({"where": pid,
                        "what": "lint failed: " + (", ".join(codes) or "no code recorded")})

    return {
        "passed": len(passed),
        "sellable": sellable,
        "stranded": len(blocked),
        "by_reason": dict(by_reason.most_common()),
        "blocking_checks": dict(problem_codes.most_common()),
        "findings": blocked,
    }


def run(config_path: Optional[Path] = None, as_json: bool = False,
        store: Optional[Path] = None) -> int:
    path = Path(config_path) if config_path else _default_config()
    store = Path(store) if store else _store()
    ran_at = datetime.now(timezone.utc).isoformat()
    probe = f"python -m ops.automations.{AUTOMATION}"

    try:
        decl = load_declaration(path)
        result = scan(store, decl)
    except CannotEstablish as exc:
        doc = {"automation": AUTOMATION, "status": "unknown", "checked": None,
               "findings": [], "ran_at": ran_at, "probe": probe, "error": str(exc)}
        print(json.dumps(doc, indent=2) if as_json else f"UNKNOWN — {exc}")
        return EXIT_UNKNOWN

    findings = result.pop("findings")
    status = "findings" if findings else "ok"
    doc = {"automation": AUTOMATION, "status": status, "checked": result["passed"],
           "findings": findings, "ran_at": ran_at, "probe": probe, **result}

    if as_json:
        print(json.dumps(doc, indent=2))
    else:
        print(f"{status.upper()} — {result['stranded']} of {result['passed']} passed packs "
              f"cannot be sold ({result['sellable']} can).")
        for reason, count in result["by_reason"].items():
            print(f"  {count:4d}  {reason}")
        if result["blocking_checks"]:
            print("  blocked by these checks (packs affected):")
            for code, count in result["blocking_checks"].items():
                print(f"    {count:4d}  {code}")

    return EXIT_FINDINGS if findings else EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=f"python -m ops.automations.{AUTOMATION}",
        description="Report finished packs that cannot be sold, and the gate blocking each.")
    ap.add_argument("--json", action="store_true", help="machine-readable; this is what the "
                                                        "console calls")
    ap.add_argument("--config", default=None, help="path to the declaration")
    # A worktree carries the code but not the runtime store, and on the engine the two are on
    # different filesystems entirely. That is a fact about where files are, not about this
    # business, so it is a flag rather than a YAML key.
    ap.add_argument("--store", default=None,
                    help="store directory to measure; defaults to PROSPECTOR_STORE_DIR")
    args = ap.parse_args(argv)
    return run(Path(args.config) if args.config else None, as_json=args.json,
               store=Path(args.store) if args.store else None)


if __name__ == "__main__":
    sys.exit(main())
