#!/usr/bin/env python3
"""ops_state.py — print the live value of every fact §6 of LAUNCH_OPS_PROGRAM.md asserts.

WHY THIS EXISTS. §6 was a list of commands with the answer written beside each one as a
comment: "# SRC-1: 201", "# SRC-3: PUBLIC", "{"listed":62,"registered":146}". Every one of
those was measured once and then rotted. Checked 2026-08-17, four of them were wrong:
uncommitted files 201 -> 37, repo visibility PUBLIC -> PRIVATE, catalog 62/146 -> 68/158,
and the retrieval chain still listed searxng, which no config selects.

A number written next to a command is a claim about the past wearing the clothes of a
measurement. This script runs the commands. The doc points at the script.

Each probe is bounded and independent: a probe that cannot answer prints UNREACHABLE with
its reason and never stops the others. Network probes (fly, gh, whois, dig, the live API)
are skipped unless --network is passed, so the default run is fast and works on a plane.

Usage:
    python3 scripts/ops_state.py               # local probes only
    python3 scripts/ops_state.py --network     # everything
    python3 scripts/ops_state.py --json        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The store is where PROSPECTOR_STORE_DIR says, never where this file sits. A path
# derived from __file__ follows the CODE; production moved off this checkout on
# 2026-08-17 and the state did not. One resolver: prospector.config.store_root().
from prospector.config import store_root  # noqa: E402


def _sh(cmd: list[str], timeout: float = 25.0) -> tuple[int, str]:
    """Run a command, return (exit_code, combined output). Never raises.

    Argument list only, never a shell string. A shell string used to be accepted, and
    exactly one probe used it: `whois <the zone> | grep -iE ...`. That carried two
    defects at once. The shell is a hole nobody needed here, and a pipeline reports the
    exit status of its LAST stage, so a whois that answered fine but matched no line
    returned grep's 1 and the probe printed UNREACHABLE. Filter in Python instead.
    """
    try:
        r = subprocess.run(cmd, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- local probes


def p_src1() -> str:
    code, out = _sh(["git", "status", "--porcelain"])
    if code:
        return "UNREACHABLE: " + out[:120]
    return "%d uncommitted path(s)" % len([ln for ln in out.splitlines() if ln.strip()])


def p_dat3() -> str:
    p = store_root() / "prospector.jsonl"
    if not p.exists():
        return "UNREACHABLE: no store/prospector.jsonl"
    n = p.stat().st_size
    return "%s bytes (%.1f MB)" % (f"{n:,}", n / 1e6)


def p_dat5() -> str:
    p = store_root() / "backup.log"
    if not p.exists():
        return "UNREACHABLE: no store/backup.log"
    lines = [ln for ln in p.read_text(errors="replace").splitlines() if ln.strip()]
    return lines[-1][:160] if lines else "empty"


def _errlog_count(pattern: str) -> str:
    p = store_root() / "scheduler" / "launchd.err.log"
    if not p.exists():
        return "UNREACHABLE: no store/scheduler/launchd.err.log"
    rx = re.compile(pattern)
    n = sum(1 for ln in p.open(errors="replace") if rx.search(ln))
    return "%d line(s) matching %s" % (n, pattern)


def p_eng4() -> str:
    return _errlog_count(r"exceeded \d+s hard deadline")


def p_eng3_402() -> str:
    # Match the provider AND the code. A bare '402' over an unrotated log counts ten days
    # of a provider chain that no longer exists.
    return _errlog_count(r"Exa search error.*402")


def p_eng3_chain() -> str:
    cfg = ROOT / "config.yaml"
    if not cfg.exists():
        return "UNREACHABLE: no config.yaml"
    for ln in cfg.read_text(errors="replace").splitlines():
        if re.match(r"^\s+provider:", ln):
            return ln.strip()
    return "no 'provider:' line found"


def p_moat() -> str:
    cfg = ROOT / "config.yaml"
    if not cfg.exists():
        return "UNREACHABLE: no config.yaml"
    out = []
    for ln in cfg.read_text(errors="replace").splitlines():
        if re.match(r"^\s*(operator|moat_primary|noncritical_operator):", ln):
            out.append(ln.strip())
    return " | ".join(out) or "none declared"


def p_live_checkout() -> str:
    s = ROOT / "scripts" / "live_checkout.py"
    if not s.exists():
        return "UNREACHABLE: no scripts/live_checkout.py"
    py = ROOT / ".venv" / "bin" / "python"
    code, out = _sh([str(py) if py.exists() else sys.executable, str(s)], timeout=60)
    # The last line is the advice ("run with --update"), not the finding. Keep the lines
    # that carry a verdict; a probe that quotes the footer answers nothing.
    # These words are what the probe PRINTS, on either platform. It reported "no verdict line"
    # after the Fly cutover because every word here described the laptop report -- `cwd`, `HEAD`,
    # `secret` -- and the Fly report says "deployed commit" and "machine state" instead.
    keep = [ln.strip() for ln in out.splitlines()
            if re.search(r"PASS|FAIL|BEHIND|AHEAD|HEAD|cwd|missing|secret"
                         r"|deployed commit|machine state|origin/main|^OK:|^  - ", ln, re.I)]
    return (" | ".join(keep[:3])[:200] if keep else "no verdict line") + ("  [exit %d]" % code)


def p_launchd() -> str:
    s = ROOT / "scripts" / "launchd_plists.py"
    if not s.exists():
        return "UNREACHABLE: no scripts/launchd_plists.py"
    code, out = _sh([sys.executable, str(s), "--check"], timeout=60)
    last = [ln for ln in out.splitlines() if ln.strip()]
    return (last[-1][:160] if last else "no output") + ("  [exit %d]" % code)


# -------------------------------------------------------------- network probes


def p_src2() -> str:
    code, out = _sh(["gh", "api", "repos/chidionyema/prospector/rulesets"], timeout=25)
    if code:
        # The repo went private on 2026-08-17, and rulesets on a private repo need GitHub
        # Pro. This is a real gap, not a broken probe: nothing here can now confirm main is
        # protected, so SRC-2 has to be checked by hand in the web UI until the plan changes.
        if "Upgrade to GitHub Pro" in out:
            return "UNREACHABLE: private repo on a free plan — check protection in the web UI"
        return "UNREACHABLE: " + out[:120]
    try:
        rules = json.loads(out)
    except json.JSONDecodeError:
        return "unparsable: " + out[:120]
    if not rules:
        return "NO RULESETS — main is unprotected"
    return ", ".join("%s=%s" % (r.get("name"), r.get("enforcement")) for r in rules)


def p_src3() -> str:
    code, out = _sh(["gh", "repo", "view", "chidionyema/prospector",
                     "--json", "isPrivate,visibility"], timeout=25)
    if code:
        return "UNREACHABLE: " + out[:120]
    try:
        d = json.loads(out)
        return "%s (isPrivate=%s)" % (d.get("visibility"), d.get("isPrivate"))
    except json.JSONDecodeError:
        return out[:120]


def p_inf1() -> str:
    # --json, not the table. The table's columns move between fly versions, and a parser
    # that misses printed "1 machine(s), regions=?" — a shrug dressed as a measurement.
    code, out = _sh(["fly", "status", "--json", "--app", "prospector-store-api"], timeout=45)
    if code:
        return "UNREACHABLE: " + out[:120]
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        return "unparsable fly output: " + out[:100]
    machines = d.get("Machines") or d.get("machines") or []
    regions = sorted({(m.get("region") or m.get("Region") or "?") for m in machines})
    states = sorted({(m.get("state") or m.get("State") or "?") for m in machines})
    return "%d machine(s), regions=%s, state=%s" % (
        len(machines), ",".join(regions) or "?", ",".join(states) or "?")


def p_dat1() -> str:
    code, out = _sh(["fly", "volumes", "list", "--json", "--app", "prospector-store-api"],
                    timeout=45)
    if code:
        return "UNREACHABLE: " + out[:120]
    try:
        vols = json.loads(out)
    except json.JSONDecodeError:
        return "unparsable fly output: " + out[:100]
    if not vols:
        return "NO VOLUMES on prospector-store-api"
    return "; ".join(
        "%s %sGB %s attached=%s" % (v.get("id"), v.get("size_gb"), v.get("region"),
                                    bool(v.get("attached_machine_id")))
        for v in vols)


def p_catalog() -> str:
    code, out = _sh(["curl", "-sS", "--max-time", "20",
                     f"https://api.{os.environ['ESTATE_ZONE']}/catalog/stats"], timeout=25)
    if code:
        return "UNREACHABLE: " + out[:120]
    return out[:160]


#: The whois fields this probe reports. Matched case-insensitively against each line,
#: in Python rather than by piping whois into grep — see `_sh`.
_WHOIS_FIELDS = ("expiry", "registrar:", "name server")


def p_dns1() -> str:
    code, out = _sh(["whois", os.environ["ESTATE_ZONE"]], timeout=30)
    if code:
        return "UNREACHABLE: " + out[:120]
    hits = [ln.strip() for ln in out.splitlines()
            if any(f in ln.lower() for f in _WHOIS_FIELDS)]
    return " | ".join(hits[:4]) or "no match"


def p_dns3() -> str:
    code, out = _sh(["dig", "+short", "TXT", f"google._domainkey.{os.environ['ESTATE_ZONE']}"], timeout=20)
    if code:
        return "UNREACHABLE: " + out[:120]
    return out[:120] or "EMPTY — DKIM not published"


LOCAL = [
    ("SRC-1", "uncommitted paths in this checkout", p_src1),
    ("DAT-3", "spend ledger size", p_dat3),
    ("DAT-5", "last store backup line", p_dat5),
    ("ENG-3", "Exa 402s in the scheduler error log", p_eng3_402),
    ("ENG-3", "retrieval chain declared in config.yaml", p_eng3_chain),
    ("ENG-4", "hard-deadline kills in the scheduler error log", p_eng4),
    ("ENG-7", "operator roster declared in config.yaml", p_moat),
    ("KEY-1", "which commit production runs", p_live_checkout),
    ("OPS-1", "launchd job definitions vs their tracked snapshot", p_launchd),
]

NETWORK = [
    ("SRC-2", "branch protection on main", p_src2),
    ("SRC-3", "repository visibility", p_src3),
    ("INF-1", "API machines and regions", p_inf1),
    ("DAT-1", "the volume holding the catalogue", p_dat1),
    ("AST-1", "live catalogue counts", p_catalog),
    ("DNS-1", "domain registrar and nameservers", p_dns1),
    ("DNS-3", "DKIM record", p_dns3),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--network", action="store_true",
                    help="also run the probes that need the network (fly, gh, dns, api)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    probes = LOCAL + (NETWORK if args.network else [])
    results = []
    for ident, what, fn in probes:
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 — a probe must not stop the others
            value = "UNREACHABLE: %s: %s" % (type(exc).__name__, exc)
        results.append({"id": ident, "what": what, "value": value})

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print("OPS STATE — measured now, in %s" % ROOT)
    if not args.network:
        print("  (local probes only; pass --network for fly, gh, dns and the live API)")
    print()
    for r in results:
        print("%-7s %-46s %s" % (r["id"], r["what"], r["value"]))
    unreachable = [r for r in results if r["value"].startswith("UNREACHABLE")]
    print()
    print("%d probe(s), %d unreachable" % (len(results), len(unreachable)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
