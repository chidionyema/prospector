#!/usr/bin/env python3
"""Recover the PASS packs that never reached the shelf, and REMEMBER what happened.

`tools/verify_pass_shelf_coverage.py` counts the stranded packs. It cannot say what was
already tried on them, so every session that looks at the number starts from zero, re-runs
the same repair, and pays for the same failure again. Two sessions running at once pay for
it twice. That is what this tool exists to stop.

Every attempt appends one row to `store/ops/pack_recovery.jsonl` — the pack, the route, the
command, the exit code, the failure signature and the outcome. The ledger is append-only
and lives in the canonical store, so a second agent session reads the same history. A pack
whose last row says `unrecoverable` is SKIPPED with its reason printed, and a route that
has failed MAX_ATTEMPTS times with an identical failure signature is promoted to
`unrecoverable` automatically. Re-running this tool after a bad run costs nothing on the
packs that cannot recover.

The route is read from the pack's own lint record, never inferred:

    no lint record         -> audit      run the free deterministic gate to produce one
    bundle missing files   -> rebundle   re-bundle from stored artifacts, no model call
    content incomplete     -> regenerate re-generate the empty artifacts (model calls)
    shelf_copy/title       -> copy       rewrite the one-liner and title (model calls)
    citation_urls          -> citations  archive the dead citations, then re-gate
    currency               -> currency   backfill the pack's currency
    clean, never published -> publish    the money rail; needs --publish

    python tools/recover_stranded_passes.py                  # report: who is stuck and why
    python tools/recover_stranded_passes.py --apply          # repair + re-gate, NO money rail
    python tools/recover_stranded_passes.py --apply --publish  # also mint and list what gates clean
    python tools/recover_stranded_passes.py --routes rebundle,audit --apply
    python tools/recover_stranded_passes.py --forget <pack>  # clear an unrecoverable mark

--apply never touches Stripe, R2 or the catalogue: it repairs and re-runs the deterministic
gate. Listing is a second, explicit `--publish`, for the same reason the gate exit in
`bridge.publish_pass` is placed before `price_for` rather than after it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402
from tools.verify_pass_shelf_coverage import _passes, _shelf_ids  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The ledger follows the STORE, not this file: production runs from a different checkout
# and both must append to the same history (config.store_root, 2026-08-17).
STORE = Path(os.environ.get("PROSPECTOR_STORE_DIR") or store_root())
LEDGER = STORE / "ops" / "pack_recovery.jsonl"
DOSSIERS = STORE / "dossiers"
# The interpreter that is ALREADY running this script, never a path built from the checkout
# layout. `REPO / ".venv" / "bin" / "python"` is a developer-machine assumption: production
# moved into a container on 2026-08-18 where there is no `.venv` at all, so every repair route
# died on `FileNotFoundError: [Errno 2] No such file or directory: '/app/.venv/bin/python'`
# before it ran a single command. The daemon launches this script with its own `sys.executable`
# and a human launches it with the venv's, so `sys.executable` is right in both places and
# cannot drift when the deployment target changes again.
PY = sys.executable

#: A route that fails this many times with an IDENTICAL failure signature is not going to
#: succeed on the next identical run. Three, not one: a provider outage and a torn write
#: both look like a failure and both clear on their own.
MAX_ATTEMPTS = 3

#: Routes that spend money on model calls, so a report can price a run before it starts.
MODEL_ROUTES = {"regenerate", "copy"}

#: The floor on the RE-GATE's own budget, separate from the repair's `--timeout`.
#: A re-gate that does not finish leaves the STALE lint record on disk, so a repair that
#: worked reads as "blocked" and the ledger learns a failure that never happened -- 19 of
#: the first 44 attempts in this ledger were exactly that.
#:
#: Measured 2026-08-17, one pack gated end to end with no pipe: **945 seconds**. The
#: default --timeout of 900 sat just under that, which is why the failures looked random.
#: Most of it was the Internet Archive, and `bridge.publish_pass` no longer mints new
#: captures on a dry run, so this floor is headroom rather than the expected cost.
REGATE_MIN_S = 1800


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reason(text: str) -> str:
    """The last line a human can read, for the ledger.

    These tools log structured JSON to stdout, so the literal last line is usually a log
    record whose useful part is buried in a `message` field. A ledger row that quotes it
    raw is unreadable, which defeats the point of keeping one.
    """
    for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
        if line.startswith("{"):
            try:
                msg = json.loads(line).get("message", "")
            except json.JSONDecodeError:
                continue
            if msg:
                return str(msg)[:200]
            continue
        return line[:200]
    return ""


def _lint(cid: str) -> dict | None:
    try:
        return json.loads((DOSSIERS / f"{cid}.lint.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:                                     # noqa: BLE001 - unreadable == unknown
        return {}


def _signature(lint: dict | None) -> str:
    """A stable name for HOW a pack is failing, so two runs can be compared.

    Not the message text: messages carry counts and ids that change between runs, and a
    signature that changes every run can never accumulate to MAX_ATTEMPTS.
    """
    if lint is None:
        return "no-lint-record"
    if not lint:
        return "lint-unreadable"
    parts = []
    if not lint.get("pack_complete", True):
        parts.append("incomplete")
    if lint.get("bundle_missing"):
        parts.append("bundle")
    checks = sorted({
        str(p.get("check", "?"))
        for p in (lint.get("problems") or [])
        if p.get("severity") == "error"
    })
    parts.extend(checks)
    return ",".join(parts) if parts else "clean"


def _route(lint: dict | None) -> str:
    """The cheapest repair that can move THIS pack, from its own lint record."""
    if lint is None:
        return "audit"
    if not lint:
        return "audit"
    if not lint.get("pack_complete", True):
        return "regenerate"
    if lint.get("bundle_missing"):
        return "rebundle"
    checks = {
        str(p.get("check", "?"))
        for p in (lint.get("problems") or [])
        if p.get("severity") == "error"
    }
    if checks & {"shelf_copy", "title", "title_claim"}:
        return "copy"
    if checks & {"citation_urls", "urls"}:
        return "citations"
    if "currency" in checks:
        return "currency"
    if "placeholders" in checks:
        return "regenerate"
    if checks:
        return "manual"
    return "publish"


def _cmd(route: str, cid: str, publish: bool) -> list[str] | None:
    """The exact command for a route, or None when the route cannot be run unattended."""
    path = str(DOSSIERS / f"{cid}.pass.json")
    if route == "audit":
        return [PY, "-m", "tools.publish_passes", "--dry-run", path]
    if route == "rebundle":
        return [PY, "-m", "tools.publish_passes", "--dry-run", "--reuse-artifacts", path]
    if route == "regenerate":
        # publish_passes only generates on the path that also LISTS: --dry-run implies
        # --reuse-artifacts and never calls a model. So regeneration is money-rail work
        # and waits for --publish rather than pretending a dry run repaired anything.
        return [PY, "-m", "tools.publish_passes", path] if publish else None
    if route == "copy":
        # NOT `sweep_shelf_copy.py`. That tool rewrites one-liners and says so at the split in
        # its own main(): "A row whose ONLY breach is its title is reported and skipped." Its
        # grader is `check_shelf_copy`, which does not carry the title rules, so a
        # title-breached pack made it print `defective: 0` and exit clean. This ledger counted
        # that as a failed attempt and, after three of them, marked the pack unrecoverable —
        # 60 rows by 2026-08-18. `repair_stranded_shelf_lines.py` repairs BOTH lines through
        # `field_write`, graded by the publish gate's own `check_title`.
        return [PY, "tools/repair_stranded_shelf_lines.py", "--fix", "--only", cid,
                "--jobs", "1"]
    if route == "citations":
        # This tool selects by dead URL, not by pack: --dead-only is exactly the set the
        # linter has already blocked, so it repairs the citation packs and nothing else.
        return [PY, "tools/backfill_archived_url.py", "--dead-only", "--apply"]
    if route == "currency":
        return [PY, "-m", "tools.backfill_pack_currency", "--apply", cid]
    if route == "publish":
        if not publish:
            return None
        return [PY, "-m", "tools.publish_passes", "--reuse-artifacts", path]
    return None


# --------------------------------------------------------------------------- ledger


def read_ledger() -> dict[str, list[dict]]:
    """Every recorded attempt, newest last, keyed by pack id."""
    out: dict[str, list[dict]] = {}
    if not LEDGER.exists():
        return out
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue                                      # a torn write is not a verdict
        out.setdefault(str(row.get("pack", "")), []).append(row)
    return out


def append(row: dict) -> None:
    """Append one attempt. O_APPEND on a line under the pipe buffer is atomic enough for
    two sessions writing at once, which is the case this ledger exists for."""
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def tool_of(cmd: str) -> str:
    """The script a recorded command ran, e.g. `sweep_shelf_copy.py`.

    The interpreter path and the pack id differ on every run; the TOOL is the part that makes
    two attempts comparable.
    """
    for part in str(cmd or "").split():
        if part.endswith(".py"):
            return part.rsplit("/", 1)[-1]
        if part.startswith("tools."):                      # `-m tools.publish_passes`
            return part
    return ""


def verdict(history: list[dict], route: str, signature: str,
            tool: str = "") -> tuple[str, str]:
    """(action, why) for a pack, from what the ledger already knows about it.

    action is "run" or "skip". This is the whole point of the tool: a pack that has failed
    the same way MAX_ATTEMPTS times is skipped, and so is one an operator marked dead.

    `tool` is the script the route builds TODAY. Attempts made by a DIFFERENT script are not
    evidence about this one, so they are dropped before the count. On 2026-08-18 the `copy`
    route was moved off `sweep_shelf_copy.py`, which rewrites one-liners and cannot repair a
    title, onto `repair_stranded_shelf_lines.py`, which can. 60 packs in the ledger carried an
    `unrecoverable` mark earned entirely by the old tool printing `defective: 0` three times.
    A mark records that a REPAIR failed; when the repair changes, the mark is stale, and
    without this the fix would be inert for exactly the packs it was written for.
    """
    if not history:
        return "run", ""
    if (history[-1].get("outcome")) == "published":
        # Checked against the WHOLE history, before the tool filter: a pack that reached the
        # shelf is on the shelf whichever tool put it there.
        return "skip", "already published by an earlier run"
    if tool:
        history = [r for r in history
                   if tool_of(r.get("cmd", "")) in ("", tool)]
    if not history:
        return "run", f"every recorded attempt used a different repair than {tool}"
    last = history[-1]
    if last.get("outcome") == "unrecoverable":
        return "skip", f"marked unrecoverable {str(last.get('ts', ''))[:10]}: {last.get('why', '')}"
    same = [
        r for r in history
        if r.get("route") == route and r.get("signature") == signature
        and r.get("outcome") in ("blocked", "failed")
    ]
    if len(same) >= MAX_ATTEMPTS:
        return "skip", (f"{len(same)} identical failures on route {route} "
                        f"(signature {signature}) — nothing new to try")
    return "run", ""


# --------------------------------------------------------------------------- run


def repair(cid: str, route: str, publish: bool, timeout: int) -> dict:
    """Run one pack's route, re-gate it, and return the ledger row (not yet written)."""
    before = _signature(_lint(cid))
    path = str(DOSSIERS / f"{cid}.pass.json")
    cmd = _cmd(route, cid, publish)
    row = {
        "ts": _now(), "pack": cid, "route": route, "signature": before,
        "session": os.environ.get("CLAUDE_SESSION_ID", "")[:8] or "cli",
    }
    if cmd is None:
        row.update(outcome="skipped", why=(
            "needs --publish (money rail)" if route == "publish"
            else "no unattended repair for this blocker — needs a human"))
        return row

    row["cmd"] = " ".join(cmd)
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
        rc, tail = proc.returncode, (proc.stdout + proc.stderr)[-600:]
    except subprocess.TimeoutExpired:
        rc, tail = 124, f"timed out after {timeout}s"
    row["rc"] = rc
    row["secs"] = round(time.time() - started, 1)

    # RE-GATE. A repair tool writes the dossier; only the gate writes the lint record, so
    # without this the ledger would grade every repair against a stale verdict and call a
    # successful rewrite "blocked". The gate is free: no model call, no money rail.
    regate_timed_out = False
    regate_budget = max(timeout, REGATE_MIN_S)
    if route not in ("audit", "publish"):
        try:
            subprocess.run([PY, "-m", "tools.publish_passes", "--dry-run", path],
                           cwd=str(REPO), capture_output=True, text=True,
                           timeout=regate_budget, stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            regate_timed_out = True
            row["regate"] = "timed out"

    after = _signature(_lint(cid))
    row["signature_after"] = after
    if route == "publish" and rc == 0:
        row.update(outcome="published", why="listed")
    elif after == "clean":
        row.update(outcome="gate_clean", why="deterministic gate passes; needs --publish to list")
    elif regate_timed_out and after == before:
        # The verdict was never MEASURED: the repair may have worked and the lint record on
        # disk predates it. Recording this as "blocked" is how a working repair gets counted
        # towards MAX_ATTEMPTS and promoted to unrecoverable. `verdict()` counts only
        # "blocked" and "failed", so "unmeasured" costs the pack nothing and it runs again.
        row.update(outcome="unmeasured",
                   why=f"re-gate did not finish in {regate_budget}s; the lint record on disk "
                       f"is older than the repair, so this attempt proves nothing")
    elif after == before:
        # No movement at all. Count it, and let the ledger decide when to give up.
        prior = [r for r in read_ledger().get(cid, [])
                 if r.get("route") == route and r.get("signature") == before
                 and r.get("outcome") in ("blocked", "failed")]
        if len(prior) + 1 >= MAX_ATTEMPTS:
            row.update(outcome="unrecoverable",
                       why=f"route {route} failed {len(prior) + 1}x with signature {before}: "
                           f"{_reason(tail) or 'rc=%d' % rc}")
        else:
            row.update(outcome="blocked", why=_reason(tail) or f"rc={rc}")
    else:
        row.update(outcome="blocked", why=f"moved {before} -> {after}")
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="run the repairs (no money rail)")
    ap.add_argument("--publish", action="store_true",
                    help="with --apply: also list packs whose gate is clean (mints Stripe)")
    ap.add_argument("--routes", default="", help="comma-separated subset of routes to run")
    ap.add_argument("--only", default="", help="comma-separated pack ids")
    ap.add_argument("--jobs", type=int, default=4, help="packs in flight (default 4)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N packs; the daemon uses this to stay inside its tick")
    ap.add_argument("--timeout", type=int, default=900, help="per-pack seconds")
    ap.add_argument("--forget", default="",
                    help="clear the unrecoverable mark on these pack ids and exit")
    args = ap.parse_args()

    if args.forget:
        for cid in [c.strip() for c in args.forget.split(",") if c.strip()]:
            append({"ts": _now(), "pack": cid, "route": "-", "outcome": "reset",
                    "why": "operator cleared the unrecoverable mark", "session": "cli"})
            print(f"  {cid}: unrecoverable mark cleared")
        return 0

    try:
        shelf = _shelf_ids()
    except Exception as exc:                              # noqa: BLE001
        print(f"shelf unreadable: {type(exc).__name__}: {exc} — cannot tell who is stranded")
        return 2

    wanted = {c.strip() for c in args.only.split(",") if c.strip()}
    routes = {r.strip() for r in args.routes.split(",") if r.strip()}
    ledger = read_ledger()

    plan: list[tuple[str, str, str, str]] = []            # cid, route, action, why
    for cid, _created in _passes(str(REPO)):
        if cid in shelf or (wanted and cid not in wanted):
            continue
        lint = _lint(cid)
        route = _route(lint)
        action, why = verdict(ledger.get(cid, []), route, _signature(lint),
                              tool=tool_of(" ".join(_cmd(route, cid, args.publish) or [])))
        if routes and route not in routes:
            action, why = "skip", f"route {route} not selected"
        plan.append((cid, route, action, why))

    runnable = [p for p in plan if p[2] == "run"]
    if args.limit and len(runnable) > args.limit:
        # Say what was dropped. A capped run that prints only its successes reads as
        # "the backlog is clear" when it is not.
        print(f"limit {args.limit}: running the oldest {args.limit} of {len(runnable)}, "
              f"{len(runnable) - args.limit} left for the next run")
        runnable = runnable[:args.limit]
    print(f"stranded passes: {len(plan)}   runnable now: {len(runnable)}   "
          f"skipped by the ledger: {len(plan) - len(runnable)}")
    by_route: dict[str, int] = {}
    for _cid, route, action, _why in plan:
        by_route[f"{route}{'' if action == 'run' else ' (skipped)'}"] = \
            by_route.get(f"{route}{'' if action == 'run' else ' (skipped)'}", 0) + 1
    for name in sorted(by_route):
        print(f"  {name:24s} {by_route[name]}")
    for cid, route, action, why in plan:
        if action == "skip":
            print(f"  SKIP [{cid}] {route}: {why}")

    if not args.apply:
        cost = sum(1 for _c, r, a, _w in plan if a == "run" and r in MODEL_ROUTES)
        print(f"\nreport only. --apply would run {len(runnable)} pack(s), "
              f"{cost} of them with model calls. Add --publish to list what gates clean.")
        return 1 if plan else 0

    print(f"\nrunning {len(runnable)} pack(s), {args.jobs} in flight")
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(repair, cid, route, args.publish, args.timeout): cid
                   for cid, route, action, _why in runnable}
        for fut in futures:
            row = fut.result()
            append(row)
            rows.append(row)
            print(f"  [{row['pack']}] {row['route']:10s} -> {row['outcome']:14s} {row.get('why', '')[:90]}",
                  flush=True)

    tally: dict[str, int] = {}
    for row in rows:
        tally[row["outcome"]] = tally.get(row["outcome"], 0) + 1
    print("\n== outcomes ==")
    for outcome in sorted(tally):
        print(f"  {outcome:16s} {tally[outcome]}")
    print(f"\nledger: {LEDGER}")
    return 0 if tally.get("published") or tally.get("gate_clean") else 1


if __name__ == "__main__":
    sys.exit(main())
