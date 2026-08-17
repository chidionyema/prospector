"""Human register coverage — every lint record carries the block the dashboard reads.

Generic engine. It knows nothing about this business: the store path, the document types and
the shape of a dossier all come from the declaration file (default
`ops/config/human_register.yaml`). See `docs/OPS_AUTOMATION_PRINCIPLES.md` for the contract
this implements.

What it is for. `pack_linter.lint_pack` writes a `human_register` block into each
`<id>.lint.json`. That block shipped after every pack on disk had already been linted, so no
record carries one and the panel that reads it draws nothing. The block is pure measurement
over text (`register_lint.register_metrics`), so the gap can be closed by re-measuring the
prose already on disk. No model call, no network, no generation cycle.

Interface (the standard shape, `OPS_AUTOMATION_PRINCIPLES.md` R2):

    python -m ops.automations.human_register                 # read-only, human output
    python -m ops.automations.human_register --json          # what the console calls
    python -m ops.automations.human_register --fix           # write the missing blocks
    python -m ops.automations.human_register --config PATH   # a different declaration

Exit codes: 0 clean, 1 findings, 2 could not establish (missing config, no store, PyYAML
absent, the measurement function unimportable).

A finding is a lint record that is MISSING the block and whose prose is still on disk, which
is exactly the set `--fix` can close. A record whose dossier is gone, or whose dossier holds no
prose, cannot be measured by anything: it is counted and named under `unmeasurable` rather than
reported as a finding, because a red line nobody can act on is how a check stops being read.
Prose sitting OUTSIDE the human range is not a finding either. That is the generator's
business; this automation only guarantees the number exists to look at, and reports the tally
under `summary`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - the declaration format is YAML by design
    yaml = None  # type: ignore[assignment]

AUTOMATION = "human_register"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNKNOWN = 2

BLOCK_KEY = "human_register"


@dataclass
class Finding:
    where: str
    what: str

    def as_dict(self) -> dict[str, str]:
        return {"where": self.where, "what": self.what}


@dataclass
class Declaration:
    """The business facts. Everything startup-specific lives here, never in the code."""

    store_dir: str = "store/dossiers"
    lint_glob: str = "*.lint.json"
    dossier_suffixes: tuple[str, ...] = (".pass.json", ".kill.json", ".defer.json")
    prose_types: tuple[str, ...] = ()
    artifacts_path: tuple[str, ...] = ("candidate", "tags", "artifacts")
    extras: dict[str, Any] = field(default_factory=dict)


class CannotEstablish(Exception):
    """The check could not run. Reported as `unknown`, never as clean."""


def load_declaration(path: Path) -> Declaration:
    if yaml is None:
        raise CannotEstablish("PyYAML is not installed, so the declaration cannot be read")
    if not path.is_file():
        raise CannotEstablish(f"declaration not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CannotEstablish(f"declaration is not valid YAML: {exc}") from exc

    store_dir = raw.get("store_dir")
    if not store_dir:
        raise CannotEstablish(f"declaration names no `store_dir:`: {path}")
    prose_types = raw.get("prose_types") or []
    if not isinstance(prose_types, list) or not prose_types:
        raise CannotEstablish(f"declaration lists no `prose_types:`: {path}")
    suffixes = raw.get("dossier_suffixes") or []
    if not isinstance(suffixes, list) or not suffixes:
        raise CannotEstablish(f"declaration lists no `dossier_suffixes:`: {path}")
    artifacts_path = raw.get("artifacts_path") or []
    if not isinstance(artifacts_path, list) or not artifacts_path:
        raise CannotEstablish(f"declaration names no `artifacts_path:`: {path}")

    return Declaration(
        store_dir=str(store_dir),
        lint_glob=str(raw.get("lint_glob") or "*.lint.json"),
        dossier_suffixes=tuple(str(s) for s in suffixes),
        prose_types=tuple(str(t) for t in prose_types),
        artifacts_path=tuple(str(p) for p in artifacts_path),
    )


def repo_root(start: Path) -> Path:
    """The git root. Asked of git, never assembled from `.git` as a path: in a worktree
    `.git` is a FILE containing a gitdir pointer, so anything treating it as a directory
    reports the wrong answer in exactly the checkout we do merges in."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start, capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise CannotEstablish(f"not a git repository (or git is unavailable): {start}") from exc
    return Path(out.stdout.strip())


def _measurer():
    """The engine's own measurement, imported late so `--help` does not need the package."""
    try:
        from prospector.register_lint import register_metrics
    except Exception as exc:  # pragma: no cover - import shape depends on the checkout
        raise CannotEstablish(
            f"prospector.register_lint.register_metrics is not importable: {exc}"
        ) from exc
    return register_metrics


def _pack_id(lint_path: Path) -> str:
    """`<id>.lint.json` -> `<id>`. Cut at the FIRST dot: an id never contains one, and the
    suffix chain does."""
    name = lint_path.name
    cut = name.find(".")
    return name[:cut] if cut > 0 else name


def _dig(doc: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(key)
    return doc


def _corpus(dossier: dict[str, Any], decl: Declaration) -> dict[str, str]:
    arts = _dig(dossier, decl.artifacts_path) or {}
    if not isinstance(arts, dict):
        return {}
    return {
        t: arts[t] for t in decl.prose_types
        if isinstance(arts.get(t), str) and arts[t].strip()
    }


def scan(decl: Declaration, root: Path, fix: bool = False) -> dict[str, Any]:
    """Read-only unless `fix` is set. Returns findings plus the counts behind them."""
    store = root / decl.store_dir
    if not store.is_dir():
        raise CannotEstablish(f"store directory not found: {store}")

    register_metrics = _measurer() if fix else None

    findings: list[Finding] = []
    unmeasurable: list[Finding] = []
    checked = 0
    covered = 0
    written = 0
    outside = 0
    per_measure: Counter[str] = Counter()

    for lint_path in sorted(store.glob(decl.lint_glob)):
        checked += 1
        rel = f"{decl.store_dir}/{lint_path.name}"
        try:
            report = json.loads(lint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unmeasurable.append(Finding(where=rel, what=f"lint record unreadable: {exc}"))
            continue
        if not isinstance(report, dict):
            unmeasurable.append(Finding(where=rel, what="lint record is not an object"))
            continue

        if isinstance(report.get(BLOCK_KEY), dict):
            covered += 1
            block = report[BLOCK_KEY]
            if block.get("outside"):
                outside += 1
                for item in block["outside"]:
                    if isinstance(item, dict) and item.get("measure"):
                        per_measure[item["measure"]] += 1
            continue

        pid = _pack_id(lint_path)
        dossier_path = next(
            (store / f"{pid}{suffix}" for suffix in decl.dossier_suffixes
             if (store / f"{pid}{suffix}").is_file()),
            None,
        )
        if dossier_path is None:
            unmeasurable.append(Finding(
                where=rel,
                what="no dossier on disk for this id, so the prose cannot be re-measured",
            ))
            continue
        try:
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unmeasurable.append(Finding(where=rel, what=f"dossier unreadable: {exc}"))
            continue

        corpus = _corpus(dossier, decl)
        if not corpus:
            unmeasurable.append(Finding(
                where=rel,
                what=f"dossier holds none of {', '.join(decl.prose_types)}, so there is "
                     "no prose to measure",
            ))
            continue

        if not fix:
            findings.append(Finding(
                where=rel,
                what=f"no `{BLOCK_KEY}` block; {len(corpus)} prose document(s) on disk are "
                     "measurable, so --fix can close this",
            ))
            continue

        try:
            metrics = register_metrics(corpus)  # type: ignore[misc]
        except Exception as exc:
            unmeasurable.append(Finding(where=rel, what=f"measurement failed: {exc}"))
            continue

        report[BLOCK_KEY] = {
            "measures": metrics["prose_measures"],
            "outside": metrics["human_register"],
            "error": metrics["human_register_error"],
            # Provenance, so a backfilled block is never read as a fresh lint.
            "backfilled": True,
            "corpus": "prose_artifacts",
            "backfilled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        # Write through a temp file in the same directory, then rename. A truncating write that
        # dies half way leaves an empty file, which reads as a missing record rather than a
        # corrupt one and is a whole afternoon to diagnose.
        tmp = lint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(lint_path)
        written += 1
        covered += 1
        if metrics["human_register"]:
            outside += 1
            for item in metrics["human_register"]:
                if isinstance(item, dict) and item.get("measure"):
                    per_measure[item["measure"]] += 1

    return {
        "findings": findings,
        "unmeasurable": unmeasurable,
        "checked": checked,
        "summary": {
            "lint_records": checked,
            "carrying_the_block": covered,
            "written": written,
            "unmeasurable": len(unmeasurable),
            "outside_the_human_range": outside,
            "per_measure": dict(per_measure.most_common()),
        },
    }


def run(config_path: Path, start: Path, fix: bool = False) -> dict[str, Any]:
    ran_at = datetime.now(timezone.utc).isoformat()
    probe = f"python -m ops.automations.{AUTOMATION} --config {config_path}"
    try:
        decl = load_declaration(config_path)
        root = repo_root(start)
        result = scan(decl, root, fix=fix)
    except CannotEstablish as exc:
        return {
            "automation": AUTOMATION,
            "status": "unknown",
            "reason": str(exc),
            "checked": 0,
            "findings": [],
            "ran_at": ran_at,
            "probe": probe,
        }

    findings = result["findings"]
    return {
        "automation": AUTOMATION,
        "status": "findings" if findings else "ok",
        "checked": result["checked"],
        "fixed": fix,
        "findings": [f.as_dict() for f in findings],
        "unmeasurable": [f.as_dict() for f in result["unmeasurable"]],
        "summary": result["summary"],
        "ran_at": ran_at,
        "probe": probe,
    }


def _default_config(start: Path) -> Path:
    try:
        return repo_root(start) / "ops" / "config" / f"{AUTOMATION}.yaml"
    except CannotEstablish:
        return Path("ops") / "config" / f"{AUTOMATION}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fix", action="store_true",
                        help="write the missing blocks (default: report only)")
    parser.add_argument("--config", type=Path, default=None, help="declaration file")
    args = parser.parse_args(argv)

    start = Path.cwd()
    config_path = args.config or _default_config(start)
    result = run(config_path, start, fix=args.fix)

    if args.json:
        print(json.dumps(result, indent=2))
        return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]

    if result["status"] == "unknown":
        print(f"UNKNOWN: {result['reason']}")
        return EXIT_UNKNOWN

    s = result["summary"]
    mode = "FIX" if args.fix else "REPORT ONLY"
    print(f"human register coverage ({mode})")
    print(f"  lint records         : {s['lint_records']}")
    print(f"  carrying the block   : {s['carrying_the_block']}")
    if args.fix:
        print(f"  written this run     : {s['written']}")
    print(f"  unmeasurable         : {s['unmeasurable']}")
    print(f"  outside human range  : {s['outside_the_human_range']}")
    for measure, count in s["per_measure"].items():
        print(f"     {measure:24s} {count}")

    if result["status"] == "ok":
        print(f"\nOK: every measurable lint record carries a `{BLOCK_KEY}` block.")
    else:
        print(f"\nFINDINGS: {len(result['findings'])} lint record(s) carry no "
              f"`{BLOCK_KEY}` block and could.")
        for item in result["findings"][:20]:
            print(f"  {item['where']}  {item['what']}")
        if len(result["findings"]) > 20:
            print(f"  ... and {len(result['findings']) - 20} more")
        print("\nRe-run with --fix to write them. It costs no model call.")

    if result["unmeasurable"]:
        print(f"\nUnmeasurable ({len(result['unmeasurable'])}) — the source prose is gone, so "
              "nothing can measure these. Not counted as findings:")
        for item in result["unmeasurable"][:10]:
            print(f"  {item['where']}  {item['what']}")
        if len(result["unmeasurable"]) > 10:
            print(f"  ... and {len(result['unmeasurable']) - 10} more")

    return {"ok": EXIT_OK, "findings": EXIT_FINDINGS, "unknown": EXIT_UNKNOWN}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
