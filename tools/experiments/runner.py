#!/usr/bin/env python3
"""L3 — the experiment harness: discover, run, emit receipts, emit a doc block.

E9–E14 were registered in `docs/COMMERCIAL_READINESS_PROGRAM.md` but every one of them was a
hand-run script with a bespoke `main()`. Two consequences, both measured in this directory:
receipt filenames were invented per script, and the programme doc was updated by hand — so the
doc and the receipts could disagree and nothing would notice.

This runner fixes both ends mechanically:

  * DISCOVERY — every module in `tools/experiments/` that exposes the uniform interface is
    registered by its own `NAME`. Modules that do not (the legacy `main()`-only scripts) are
    listed as `unregistered` rather than hidden, so the gap is visible instead of forgotten.
  * RECEIPTS — the runner, not the experiment, decides where the receipt JSON lands
    (`<module_stem>[<suffix>]_receipts.json`), so the naming cannot drift per script.
  * DOC BLOCK — the runner NEVER edits `docs/COMMERCIAL_READINESS_PROGRAM.md`. That file has an
    owner. It writes a dated markdown block to `<module_stem>[<suffix>]_doc_append.md` and prints
    the path, for the doc's owner to paste. A tool that appends to a file another agent owns is
    how two sessions clobber each other's edits.

THE UNIFORM INTERFACE a module must expose to be registered:

    NAME     : str            — the programme id, e.g. "E15". Case-insensitive at the CLI.
    describe(): str           — one line. Optional; falls back to the module docstring's
                                first line.
    run(args): dict           — does the work, may print freely, RETURNS the receipts payload.
                                `args` is the residual argv list after the experiment name.

    Optional:
      DOC_REF   : str         — where in the programme doc this experiment is registered.
      doc_block(receipts): str — override the default markdown renderer.

  Two keys in the returned dict are read by the runner and are conventions, not requirements:
      "headline"         : dict[str, Any] — the numbers that go in the doc block, in order.
      "_receipt_suffix"  : str            — appended to the receipt stem, for scoped re-runs
                                            (matches the existing `_current_moat` convention).

Usage:
    .venv/bin/python tools/experiments/runner.py list
    .venv/bin/python tools/experiments/runner.py describe E15
    .venv/bin/python tools/experiments/runner.py run E15 [experiment args...]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUNNER_STEM = Path(__file__).stem


class ExperimentError(RuntimeError):
    """Raised for a caller-facing failure: unknown name, bad interface, bad return."""


class Experiment:
    """A discovered module plus what the runner needs to know about it."""

    __slots__ = ("name", "stem", "path", "module", "error")

    def __init__(self, name: str, stem: str, path: Path, module: Any = None,
                 error: str | None = None) -> None:
        self.name = name
        self.stem = stem
        self.path = path
        self.module = module
        self.error = error

    @property
    def registered(self) -> bool:
        return self.module is not None and self.error is None

    def describe(self) -> str:
        if self.error:
            return f"UNAVAILABLE: {self.error}"
        fn = getattr(self.module, "describe", None)
        if callable(fn):
            try:
                return str(fn()).strip()
            except Exception as exc:  # a broken describe() must not hide the experiment
                return f"describe() raised {type(exc).__name__}: {exc}"
        doc = (self.module.__doc__ or "").strip().splitlines()
        return doc[0].strip() if doc else "(no description)"

    @property
    def doc_ref(self) -> str:
        return str(getattr(self.module, "DOC_REF", "") or "")


def _load(path: Path) -> Any:
    """Import a file as a throwaway module. Raises on any import-time failure."""
    mod_name = f"_experiment_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered under its private name so a second discovery pass re-imports cleanly and two
    # experiments that share a helper name cannot shadow each other.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def discover(directory: str | os.PathLike[str] | None = None) -> dict[str, Experiment]:
    """Every `*.py` in `directory` that exposes NAME + run(), keyed by upper-cased NAME.

    Files beginning with `_` are helpers, not experiments, and the runner itself is skipped.
    A module that fails to import is NOT silently dropped: it is returned with `.error` set and
    keyed by its file stem, because an experiment that vanished from `list` because of a typo is
    exactly the failure this harness exists to prevent.
    """
    d = Path(directory) if directory is not None else HERE
    found: dict[str, Experiment] = {}
    for path in sorted(d.glob("*.py")):
        if path.name.startswith("_") or path.stem == RUNNER_STEM:
            continue
        try:
            module = _load(path)
        except Exception as exc:
            found[path.stem.upper()] = Experiment(
                path.stem.upper(), path.stem, path, None,
                f"{type(exc).__name__}: {exc}")
            continue
        name = getattr(module, "NAME", None)
        if not isinstance(name, str) or not name.strip():
            continue                                     # legacy main()-only script
        if not callable(getattr(module, "run", None)):
            found[name.strip().upper()] = Experiment(
                name.strip().upper(), path.stem, path, None,
                "exposes NAME but no callable run(args)")
            continue
        found[name.strip().upper()] = Experiment(name.strip().upper(), path.stem, path, module)
    return found


def resolve(name: str, registry: dict[str, Experiment]) -> Experiment:
    """Accept either the programme NAME ('e15') or the file stem ('e15_hhem_groundedness')."""
    key = name.strip().upper()
    if key in registry:
        return registry[key]
    by_stem = {e.stem.upper(): e for e in registry.values()}
    if key in by_stem:
        return by_stem[key]
    known = ", ".join(sorted(registry)) or "(none)"
    raise ExperimentError(f"unknown experiment {name!r}. Known: {known}")


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value)
    return str(value)


def default_doc_block(exp: Experiment, receipts: dict, receipt_path: Path,
                      argv: list[str], run_at: str) -> str:
    """The markdown the doc's OWNER pastes. Deliberately boring and fully sourced."""
    headline = receipts.get("headline")
    lines = [
        f"### {exp.name} — {receipts.get('title') or exp.describe()}",
        "",
        f"_Run {run_at} · `{exp.path.name}`"
        + (f" · registered {exp.doc_ref}" if exp.doc_ref else "") + "_",
        "",
    ]
    if isinstance(headline, dict) and headline:
        for k, v in headline.items():
            lines.append(f"- **{k}**: {_fmt(v)}")
        lines.append("")
    if receipts.get("verdict"):
        lines += [f"**Verdict:** {receipts['verdict']}", ""]
    if receipts.get("population"):
        lines += [f"Population / selection rule: {receipts['population']}", ""]
    limits = receipts.get("limitations") or []
    if limits:
        lines.append("Limitations:")
        lines += [f"- {ln}" for ln in limits]
        lines.append("")
    cmd = " ".join(["tools/experiments/runner.py", "run", exp.name, *argv]).strip()
    lines += [
        f"Receipt: `{_rel(receipt_path)}` — reproduce with `.venv/bin/python {cmd}`",
        "",
    ]
    return "\n".join(lines)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def run_one(name: str, args: list[str] | None = None,
            directory: str | os.PathLike[str] | None = None,
            out_dir: str | os.PathLike[str] | None = None) -> dict:
    """Run one experiment end to end. Returns {receipts_path, doc_append_path, receipts}."""
    args = list(args or [])
    registry = discover(directory)
    exp = resolve(name, registry)
    if not exp.registered:
        raise ExperimentError(f"experiment {exp.name} is not runnable — {exp.error}")

    run_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    receipts = exp.module.run(args)
    if not isinstance(receipts, dict):
        raise ExperimentError(
            f"{exp.name}.run() must return a dict of receipts, got {type(receipts).__name__}")

    suffix = str(receipts.get("_receipt_suffix") or "")
    dest_dir = Path(out_dir) if out_dir is not None else exp.path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = dest_dir / f"{exp.stem}{suffix}_receipts.json"
    doc_path = dest_dir / f"{exp.stem}{suffix}_doc_append.md"

    envelope = dict(receipts)
    envelope.pop("_receipt_suffix", None)
    envelope["_meta"] = {
        "experiment": exp.name,
        "module": exp.path.name,
        "run_at_utc": run_at,
        "argv": args,
        "runner": "tools/experiments/runner.py",
        "python": sys.version.split()[0],
    }
    receipt_path.write_text(json.dumps(envelope, indent=2, default=str))

    renderer = getattr(exp.module, "doc_block", None)
    if callable(renderer):
        block = renderer(envelope)
    else:
        block = default_doc_block(exp, envelope, receipt_path, args, run_at)
    doc_path.write_text(block if block.endswith("\n") else block + "\n")

    return {"receipts_path": receipt_path, "doc_append_path": doc_path, "receipts": envelope}


def _cmd_list(argv: argparse.Namespace) -> int:
    registry = discover(argv.dir)
    registered = {k: v for k, v in registry.items() if v.registered}
    broken = {k: v for k, v in registry.items() if not v.registered}
    print(f"registered experiments ({len(registered)}):")
    for key in sorted(registered):
        e = registered[key]
        print(f"  {e.name:<6} {e.path.name:<38} {e.describe()[:88]}")
    if broken:
        print(f"\nbroken / half-registered ({len(broken)}):")
        for key in sorted(broken):
            print(f"  {key:<6} {broken[key].path.name:<38} {broken[key].error}")
    d = Path(argv.dir) if argv.dir else HERE
    legacy = [p.name for p in sorted(d.glob("*.py"))
              if not p.name.startswith("_") and p.stem != RUNNER_STEM
              and p.stem.upper() not in registry and p.name not in
              {e.path.name for e in registry.values()}]
    if legacy:
        print(f"\nunregistered legacy scripts, main()-only ({len(legacy)}):")
        for n in legacy:
            print(f"  {n}")
    return 0


def _cmd_describe(argv: argparse.Namespace) -> int:
    exp = resolve(argv.name, discover(argv.dir))
    print(f"{exp.name}  ({exp.path.name})")
    if exp.doc_ref:
        print(f"registered: {exp.doc_ref}")
    print(exp.describe())
    if exp.registered and exp.module.__doc__:
        print()
        print(exp.module.__doc__.strip())
    return 0


def _cmd_run(argv: argparse.Namespace) -> int:
    result = run_one(argv.name, argv.rest, argv.dir, argv.out_dir)
    print(f"\nreceipts    -> {_rel(result['receipts_path'])}")
    print(f"doc append  -> {_rel(result['doc_append_path'])}")
    print("(the runner does NOT edit docs/COMMERCIAL_READINESS_PROGRAM.md — paste the block above)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="runner.py", description="Discover and run programme experiments.")
    parser.add_argument("--dir", default=None,
                        help="experiment directory (default: this file's directory)")
    parser.add_argument("--out-dir", default=None,
                        help="where receipts land (default: the experiment's own directory)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list discovered experiments").set_defaults(fn=_cmd_list)
    p_desc = sub.add_parser("describe", help="print one experiment's description")
    p_desc.add_argument("name")
    p_desc.set_defaults(fn=_cmd_describe)
    p_run = sub.add_parser("run", help="run one experiment by NAME or file stem")
    p_run.add_argument("name")
    p_run.add_argument("rest", nargs=argparse.REMAINDER,
                       help="arguments forwarded verbatim to the experiment's run()")
    p_run.set_defaults(fn=_cmd_run)

    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except ExperimentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
