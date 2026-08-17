#!/usr/bin/env python3
"""Derive the launch-ops programme's status from the repo, not from prose.

    python scripts/ops_status.py              # the table
    python scripts/ops_status.py --fetch      # refresh origin/main first
    python scripts/ops_status.py --agents     # only the other-sessions section
    python scripts/ops_status.py --json       # machine-readable

WHY THIS EXISTS
---------------
`docs/LAUNCH_OPS_PROGRAM.md` §4 carries a hand-typed status column. Nothing writes to it
when work merges, so it drifts the moment anything lands. On 2026-08-17 it showed one row
`RESOLVED` while DAT-1, ENG-5, SRC-2, SRC-4 and PAY-1 were all merged on `origin/main`, and
an agent reading it reported "~26 items, ~22 open" to the founder. The real count is 44.
Both numbers were prose, and prose was the only source there was.

So status is a command now. Each item below carries a CHECK that reads the repo, the live
`origin/main`, or a probe's own output. The doc goes back to being the argument for why an
item matters; this file is the answer to whether it is done.

THE THREE HONEST ANSWERS
------------------------
Every check returns one of:

  DONE     evidence on disk or on origin/main proves the fix shipped
  OPEN     evidence proves it did not
  MANUAL   this needs a human, an external account, or a network call the script will not
           fake. NEVER counted as done. A programme that scores its unknowns as passes is
           the thing this file was written to replace.

`ACCEPTED` is a fourth, and it is the doc's own judgement, not a measurement: the item is
understood and deliberately not being fixed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DONE, OPEN, MANUAL, ACCEPTED = "DONE", "OPEN", "MANUAL", "ACCEPTED"


def sh(*args: str, cwd: Path = ROOT, timeout: int = 60) -> tuple[int, str]:
    """Run a command and hand back (returncode, output). Never raises: a probe that dies
    because a tool is missing must report that, not take the whole table down."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def on_main(path: str, needle: str | None = None) -> tuple[bool, str]:
    """Is this file on `origin/main`, and does it contain `needle`?

    The single most useful question in this file, and the one the 2026-08-17 miscount got
    wrong. A file in the working tree proves nothing: it may be uncommitted, on a branch, or
    in another session's worktree. Only `origin/main` is what actually ships."""
    rc, _ = sh("git", "cat-file", "-e", f"origin/main:{path}")
    if rc != 0:
        return False, f"{path} is not on origin/main"
    if needle is None:
        return True, f"{path} is on origin/main"
    rc, out = sh("git", "show", f"origin/main:{path}")
    if rc != 0:
        return False, f"could not read origin/main:{path}"
    if needle in out:
        return True, f"origin/main:{path} contains {needle!r}"
    return False, f"origin/main:{path} exists but lacks {needle!r}"


def _lines(rc_out: tuple[int, str]) -> int:
    _rc, out = rc_out
    return len([ln for ln in out.splitlines() if ln.strip()])


# ---------------------------------------------------------------------------------------
# The checks. Each returns (status, evidence). Keep them cheap: this must be runnable at
# the start of every session, so nothing here may take minutes or spend money.
# ---------------------------------------------------------------------------------------

def c_src1():
    dirty = _lines(sh("git", "status", "--porcelain"))
    rc, out = sh("git", "rev-list", "--left-right", "--count", "origin/main...HEAD")
    counts = out.split() if rc == 0 else ["?", "?"]
    behind, ahead = (counts + ["?", "?"])[:2]
    ev = f"{dirty} uncommitted paths, {ahead} ahead / {behind} behind origin/main"
    return (DONE if dirty == 0 and ahead == "0" else OPEN), ev


def c_src2():
    rc, out = sh("gh", "api", "repos/chidionyema/prospector/rulesets", timeout=30)
    if rc != 0:
        return MANUAL, "gh unreachable; check the ruleset in the GitHub UI"
    try:
        rules = json.loads(out)
    except json.JSONDecodeError:
        return MANUAL, "ruleset response was not JSON"
    active = [r for r in rules if r.get("enforcement") == "active"]
    return (DONE if active else OPEN), f"{len(active)} active ruleset(s) on the repo"


def c_src3():
    rc, out = sh("gh", "repo", "view", "chidionyema/prospector", "--json", "visibility",
                 timeout=30)
    if rc != 0:
        return MANUAL, "gh unreachable"
    vis = json.loads(out).get("visibility") if out.startswith("{") else "?"
    return (DONE if vis == "PRIVATE" else OPEN), f"repo visibility is {vis}"


def c_src4():
    ok, ev = on_main("scripts/backup_store.py", "def mirror_repo")
    return (DONE if ok else OPEN), ev


def c_src5():
    return MANUAL, "20 secrets in one .env; a vault or escrow is an operator decision"


def c_src6():
    n = _lines(sh("git", "ls-files", "store/"))
    return (DONE if n == 0 else OPEN), f"{n} runtime files tracked under store/"


#: Not at the repo root. The first version of this check looked for `api.fly.toml` there,
#: found nothing and reported MANUAL — a check that cannot find its own file reads exactly
#: like a check that found a problem, which is the failure mode this whole script is for.
API_FLY_TOML = "store_platform/deploy/fly/api.fly.toml"


def c_inf1():
    rc, out = sh("git", "show", f"origin/main:{API_FLY_TOML}")
    m = re.search(r"min_machines_running\s*=\s*(\d+)", out) if rc == 0 else None
    if not m:
        return MANUAL, f"min_machines_running not found in {API_FLY_TOML}"
    n = int(m.group(1))
    return (DONE if n >= 2 else OPEN), f"min_machines_running = {n} in {API_FLY_TOML}"


def c_inf2():
    return MANUAL, "needs `fly apps list`; a staging config exists, a staging app may not"


def c_inf3():
    return MANUAL, "needs a live header fetch of mumchimp.com"


def c_dat1():
    ok, ev = on_main("ops/automations/offsite_backup.py")
    return (DONE if ok else OPEN), ev


def c_dat2():
    hits = sorted(ROOT.glob("store/ops/restore_drill*"))
    if hits:
        return DONE, f"receipt on disk: {hits[-1].relative_to(ROOT)}"
    return OPEN, "scripts/restore_drill.py exists; no dated receipt under store/ops/"


def c_dat3():
    p = ROOT / "store" / "prospector.jsonl"
    if not p.exists():
        return MANUAL, "store/prospector.jsonl absent"
    mb = p.stat().st_size / 1e6
    return (DONE if mb < 100 else OPEN), f"store/prospector.jsonl is {mb:.0f} MB"


def c_eng1():
    """The stranded-pack count, from the probe itself. Never a remembered number.

    The probe lives on `origin/main` and this checkout may be behind it — that is the normal
    state here, not an error. Say so plainly rather than reporting a missing module as if it
    were a finding about the packs."""
    if not (ROOT / "ops" / "automations" / "stranded_packs.py").exists():
        ok, _ev = on_main("ops/automations/stranded_packs.py")
        return MANUAL, ("probe is on origin/main but not in this checkout; "
                        "run it from an up-to-date tree" if ok
                        else "ops/automations/stranded_packs.py is nowhere")
    rc, out = sh(sys.executable, "-m", "ops.automations.stranded_packs", timeout=240)
    m = re.search(r"(\d+)\s+of\s+(\d+)\s+passed packs stranded", out)
    if not m:
        return MANUAL, f"probe gave no count (rc={rc}); run it by hand"
    stranded, total = int(m.group(1)), int(m.group(2))
    return (DONE if stranded == 0 else OPEN), f"{stranded} of {total} passed packs stranded"


def c_eng5():
    ok, ev = on_main("ops/automations/log_rotation.py")
    return (DONE if ok else OPEN), ev


def c_eng6():
    rc, out = sh(sys.executable, "scripts/doc_lint.py", "--check", timeout=180)
    m = re.search(r"(\d+) finding", out)
    n = int(m.group(1)) if m else -1
    return (DONE if n == 0 else OPEN), f"doc_lint reports {n} finding(s)"


def c_pay1():
    ok, ev = on_main("store_platform/src/Store.Api/Payments/MoneyRailStatus.cs")
    return (DONE if ok else OPEN), ev


def c_biz1():
    """A company number on the live site is the whole item. Grep our own copy of it."""
    rc, out = sh("git", "grep", "-lEi", r"company (number|no\.)|registered in england",
                 "origin/main", "--", "store_platform/src/Store.Web")
    return (DONE if rc == 0 and out else OPEN), (
        "company details found in Store.Web" if rc == 0 and out
        else "no company number / registered address in Store.Web — needs the founder")


def c_key1():
    rc, out = sh("git", "grep", "-lF", "/Users/chidionyema", "origin/main", "--", "*.plist")
    n = _lines((rc, out))
    return (OPEN if n else DONE), f"{n} plist(s) carry an absolute /Users/chidionyema path"


#: item -> (check, one-line what-it-is). Items with no mechanical check carry None and are
#: reported MANUAL by name rather than quietly dropped: a table that hides what it cannot
#: measure reads as coverage it does not have.
ITEMS: dict[str, tuple] = {
    "SRC-1": (c_src1, "Nothing is committed"),
    "SRC-2": (c_src2, "Branch protection on main"),
    "SRC-3": (c_src3, "Repo public under MIT"),
    "SRC-4": (c_src4, "One remote, no mirror"),
    "SRC-5": (c_src5, "20 secrets in one plaintext .env"),
    "SRC-6": (c_src6, "Runtime state tracked under store/"),
    "INF-1": (c_inf1, "API is one machine in one region"),
    "INF-2": (c_inf2, "No staging environment"),
    "INF-3": (c_inf3, "No CDN or WAF"),
    "INF-4": (None, "Single Fly account and payment method"),
    "INF-5": (None, "Deploy is Fly-specific in CI"),
    "DAT-1": (c_dat1, "Money data has one copy, 5-day window"),
    "DAT-2": (c_dat2, "Restore never proven end to end"),
    "DAT-3": (c_dat3, "Spend ledger outgrew its readers"),
    "DAT-4": (None, "RPO is 24 hours on engine state"),
    "DAT-5": (None, "Backup coverage good where it exists"),
    "AST-1": (None, "No object versioning on either R2 bucket"),
    "AST-2": (None, "Live entitlement tokens gitignored and unbacked"),
    "AST-3": (None, "store/listings not backed up"),
    "AST-4": (None, "Delivery keys are content-addressed"),
    "DNS-1": (None, "Registrar and DNS split across two vendors"),
    "DNS-2": (None, "DNSSEC unsigned"),
    "DNS-3": (None, "Workspace DKIM not published"),
    "DNS-4": (None, "A-record TTL is 600s"),
    "BIZ-1": (c_biz1, "No company number or registered address on the site"),
    "BIZ-2": (None, "Legal pages unreviewed by counsel"),
    "BIZ-3": (None, "No dedicated contact page"),
    "BIZ-4": (None, "No cookie banner"),
    "BIZ-5": (None, "Content liability covered in writing"),
    "BIZ-6": (None, "Key-person risk"),
    "PAY-1": (c_pay1, "API knows it is in live mode and tells nobody"),
    "PAY-2": (None, "Refunds and disputes have code, no runbook"),
    "PAY-3": (None, "Price change breaks fulfilment if catalogue drifts"),
    "PAY-4": (None, "Stripe automatic tax enabled"),
    "ENG-1": (c_eng1, "Finished packs that cannot be bought"),
    "ENG-2": (None, "The loudest alert names the wrong cause"),
    "ENG-3": (None, "Grounding runs on one fast provider"),
    "ENG-4": (None, "MiniMax calls hitting the 600s deadline"),
    "ENG-5": (c_eng5, "Logs and state grow unbounded"),
    "ENG-6": (c_eng6, "Docs describe a system that no longer exists"),
    "ENG-7": (None, "Two guards are off"),
    "KEY-1": (c_key1, "The engine cannot run anywhere but this Mac"),
    "KEY-2": (None, "Laptop loss costs 24h plus the .env"),
}

#: Graded ACCEPTED in the doc: understood, deliberately not being fixed. Not a measurement,
#: so it is listed separately and never counted as done.
ACCEPTED_IDS = {"DAT-5", "AST-4", "DNS-4", "PAY-3", "PAY-4", "INF-5", "BIZ-5"}


#: A claim is stale after this long. A session that dies holding a claim must not block the
#: item forever, and a claim nobody renews is not a claim — it is an abandoned worktree.
CLAIM_TTL_H = 12


def claims_path() -> Path:
    """The one file every worktree of this repo can see.

    Not a tracked file: 59 worktrees committing to a shared register would conflict on every
    claim, and a claim must cost nothing or nobody makes one. The common git dir is shared by
    every worktree by construction, so it is the natural place for state that is about the
    checkout rather than about the code."""
    rc, out = sh("git", "rev-parse", "--git-common-dir")
    base = Path(out.strip()) if rc == 0 and out.strip() else ROOT / ".git"
    if not base.is_absolute():
        base = ROOT / base
    return base / "ops-claims.jsonl"


def read_claims() -> dict[str, dict]:
    """Who holds what, right now. Last record per item wins; releases drop the item."""
    path = claims_path()
    if not path.exists():
        return {}
    held: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = str(rec.get("id", "")).upper()
        if not item:
            continue
        if rec.get("action") == "release":
            held.pop(item, None)
        else:
            held[item] = rec
    return held


def _age_h(iso: str) -> float:
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


def write_claim(item: str, action: str, note: str = "") -> dict:
    rc, branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    rec = {
        "id": item.upper(),
        "action": action,
        "session": session_tag(),
        "branch": branch.strip() if rc == 0 else "?",
        "cwd": str(ROOT),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }
    path = claims_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def session_tag() -> str:
    """This session's id, the same way scripts/handoff.py derives it.

    The fallback is the CHECKOUT, never a pid: a pid changes on every shell the agent opens,
    so a session would fail to recognise its own claim and refuse to renew it. "One session,
    one worktree" is the working rule here, which makes the worktree the honest identity."""
    for var in ("CLAUDE_SESSION_ID", "CLAUDE_SCRATCHPAD", "TMPDIR"):
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                      os.environ.get(var, ""))
        if m:
            return m.group(0)[:8]
    return ROOT.name[:12]


def claims_report() -> list[str]:
    held = read_claims()
    out = ["WHO HOLDS WHAT (claim before you start; nothing else stops two agents "
           "doing the same item)"]
    if not held:
        out.append("  nothing claimed — every open item is unowned")
        return out
    for item, rec in sorted(held.items()):
        age = _age_h(rec.get("at", ""))
        stale = "  STALE" if age > CLAIM_TTL_H else ""
        note = f" — {rec['note']}" if rec.get("note") else ""
        out.append(f"  {item:<7} {rec.get('session', '?'):<10} {age:5.1f}h ago  "
                   f"{rec.get('branch', '?')[:34]:<34}{stale}{note}")
    return out


def other_agents() -> list[str]:
    """What every OTHER session in this estate is holding.

    Written because nobody was checking. On 2026-08-17 there were 18 Claude processes and
    58 worktrees against one checkout, five PRs open, three of them a day old and untouched
    — and a session could not have told you which of them overlapped its own work."""
    out = ["OPEN PULL REQUESTS"]
    rc, raw = sh("gh", "pr", "list", "--state", "open", "--limit", "50", "--json",
                 "number,title,headRefName,updatedAt,isDraft", timeout=45)
    if rc != 0:
        out.append("  gh unreachable — cannot see other sessions' PRs")
    else:
        try:
            rows = sorted(json.loads(raw), key=lambda r: r["updatedAt"])
        except json.JSONDecodeError:
            rows = []
        for r in rows:
            flag = " [draft]" if r.get("isDraft") else ""
            out.append(f"  #{r['number']:<5} {r['updatedAt'][:16]}  "
                       f"{r['headRefName'][:40]:<40} {r['title'][:52]}{flag}")
        out.append(f"  {len(rows)} open")

    out.append("")
    out.append("LIVE WORKTREES (one per working session)")
    rc, raw = sh("git", "worktree", "list")
    trees = [ln for ln in raw.splitlines() if ln.strip()] if rc == 0 else []
    for ln in trees[:20]:
        out.append(f"  {ln}")
    if len(trees) > 20:
        out.append(f"  ... and {len(trees) - 20} more ({len(trees)} total)")

    out.append("")
    out.append("BRANCHES PUSHED IN THE LAST 3 DAYS (someone is working on these)")
    rc, raw = sh("git", "for-each-ref", "--sort=-committerdate",
                 "--format=%(committerdate:relative)|%(refname:short)", "refs/remotes/origin")
    shown = 0
    for ln in raw.splitlines():
        rel, _, name = ln.partition("|")
        if any(u in rel for u in ("second", "minute", "hour", "day")) and shown < 15:
            out.append(f"  {rel:<18} {name}")
            shown += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="refresh origin/main first")
    ap.add_argument("--agents", action="store_true", help="only the other-sessions section")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--only", default="", help="comma-separated item ids")
    ap.add_argument("--claim", metavar="ID", help="claim an item before starting it")
    ap.add_argument("--release", metavar="ID", help="release an item you are no longer on")
    ap.add_argument("--claims", action="store_true", help="only the claim register")
    ap.add_argument("--note", default="", help="what you are doing to it")
    args = ap.parse_args()

    if args.fetch:
        sh("git", "fetch", "origin", "main", timeout=120)

    if args.claim:
        item = args.claim.upper()
        if item not in ITEMS:
            print(f"{item} is not a programme item; ids are {', '.join(ITEMS)}", file=sys.stderr)
            return 2
        held = read_claims().get(item)
        if held and held.get("session") != session_tag() and _age_h(held.get("at", "")) <= CLAIM_TTL_H:
            print(f"{item} is already held by session {held.get('session')} on branch "
                  f"{held.get('branch')} ({_age_h(held.get('at', '')):.1f}h ago). "
                  f"Pick another item or talk to them.", file=sys.stderr)
            return 1
        rec = write_claim(item, "claim", args.note)
        print(f"claimed {item} as session {rec['session']} on {rec['branch']}")
        return 0

    if args.release:
        rec = write_claim(args.release, "release", args.note)
        print(f"released {rec['id']}")
        return 0

    if args.claims:
        print("\n".join(claims_report()))
        return 0

    if args.agents:
        print("\n".join(claims_report()))
        print()
        print("\n".join(other_agents()))
        return 0

    wanted = {s.strip().upper() for s in args.only.split(",") if s.strip()}
    results = {}
    for item, (check, what) in ITEMS.items():
        if wanted and item not in wanted:
            continue
        if item in ACCEPTED_IDS:
            results[item] = (ACCEPTED, "graded ACCEPTED in the programme doc", what)
        elif check is None:
            results[item] = (MANUAL, "no mechanical check written yet", what)
        else:
            status, ev = check()
            results[item] = (status, ev, what)

    if args.json:
        print(json.dumps({k: {"status": s, "evidence": e, "what": w}
                          for k, (s, e, w) in results.items()}, indent=2))
        return 0

    held = read_claims()
    print("LAUNCH OPS PROGRAMME — derived from the repo, not from the doc\n")
    for item, (status, ev, what) in results.items():
        owner = held.get(item)
        tag = f"  [held by {owner['session']}]" if owner else ""
        print(f"  {status:<9}{item:<7} {what}{tag}")
        print(f"           {'':<7} {ev}")

    tally: dict[str, int] = {}
    for status, _ev, _w in results.values():
        tally[status] = tally.get(status, 0) + 1
    print("\n" + "  ".join(f"{k}: {v}" for k, v in sorted(tally.items())))
    print(f"  TOTAL: {len(results)}")
    manual = [i for i, (s, _e, _w) in results.items() if s == MANUAL]
    if manual:
        print(f"\n  {len(manual)} item(s) have NO mechanical check and are NOT counted as "
              f"done:\n    {', '.join(manual)}")
    print()
    print("\n".join(claims_report()))
    print()
    print("\n".join(other_agents()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
