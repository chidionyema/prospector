#!/usr/bin/env python3
"""DNS is the one thing with no substitute. This keeps a committed copy of it and diffs it daily.

`docs/ESTATE_CONTINUITY_PLAN.md` R5 rates the registrar as the single unrecoverable loss on the
register, and then leaves it there. There was no committed copy of the zone, so a deleted record or
a lost GoDaddy account meant nobody knew what the records had been. Every exit path in that
document ends in "repoint DNS" and none of them said to what.

Two modes, and neither writes to DNS:

    dns_zone.py --export        print the live zone in the committed format
    dns_zone.py --check         diff live DNS against deploy/dns/<zone>.zone, exit 1 on drift

`--check` is the drill. It is deliberately symmetric: a record that appeared is drift and a record
that vanished is drift, because the failure being caught is "something changed and nobody knows".

**It asks the AUTHORITATIVE nameservers, not the local resolver.** A resolver answers from cache,
so a record deleted five minutes ago still resolves and the drill passes on a zone that is already
broken.

**It raises rather than reporting an empty zone.** A probe that passes when it cannot measure is
worse than no probe — the same rule `scripts/fly_estate_probe.py::live_apps` follows.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZONE_DIR = ROOT / "deploy" / "dns"

# The names checked even when the committed file does not mention them. Without this a DELETED
# record would simply stop being compared, which is the drift that matters most.
BASE_LABELS = ("", "www", "api", "_dmarc")
TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "CAA", "NS")


def _dig(server: str, name: str, rtype: str, timeout: int = 20) -> list[str]:
    p = subprocess.run(
        ["dig", "+noall", "+answer", "+time=5", "+tries=2", f"@{server}", name, rtype],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(f"dig {name} {rtype} @{server} failed: {p.stderr.strip()}")
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def nameservers(zone: str) -> list[str]:
    """The authoritative servers, from the parent. Empty means we cannot measure -- raise."""
    p = subprocess.run(["dig", "+short", "+time=5", "+tries=2", "NS", zone],
                       capture_output=True, text=True, timeout=30, check=False)
    hosts = sorted(h.rstrip(".") for h in p.stdout.split() if h.strip())
    if not hosts:
        raise RuntimeError(f"cannot find the authoritative nameservers for {zone}")
    return hosts


def parse(lines: list[str]) -> set[tuple[str, str, str]]:
    """dig answer lines -> {(name, type, value)}. TTL is deliberately NOT part of the key.

    A TTL change is a routine operational act (lowering it before a cutover is in the runbook).
    Treating it as drift would make the drill cry wolf on the exact day it matters most.
    """
    out: set[tuple[str, str, str]] = set()
    for line in lines:
        parts = line.split(None, 4)
        if len(parts) < 5 or parts[2] != "IN":
            continue
        name, rtype, value = parts[0].rstrip("."), parts[3], parts[4].strip()
        out.add((name, rtype, " ".join(value.split())))
    return out


def live(zone: str, labels: tuple[str, ...]) -> set[tuple[str, str, str]]:
    server = nameservers(zone)[0]
    found: set[tuple[str, str, str]] = set()
    for label in labels:
        name = zone if not label else f"{label}.{zone}"
        for rtype in TYPES:
            found |= parse(_dig(server, name, rtype))
    if not found:
        raise RuntimeError(f"no records at all for {zone} -- refusing to report an empty zone")
    return found


def zone_path(zone: str) -> Path:
    return ZONE_DIR / f"{zone}.zone"


def _rel(path: Path) -> str:
    """A path for a human to read, that cannot raise.

    `Path.relative_to` throws when the path is not under ROOT, and both callers are error and
    success MESSAGES. A message formatter that can raise turns "no committed zone" (exit 1,
    actionable) into an uncaught traceback, which is the one outcome nobody can act on.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def render(zone: str, records: set[tuple[str, str, str]]) -> str:
    head = [
        f"; {zone} -- the committed copy of the zone.",
        ";",
        "; Regenerate:  .venv/bin/python scripts/dns_zone.py --export --zone " + zone,
        "; Check drift: .venv/bin/python scripts/dns_zone.py --check  --zone " + zone,
        ";",
        "; TTLs are not recorded on purpose. Lowering a TTL before a cutover is a routine act and",
        "; must not read as drift. See docs/MIGRATION_AND_DR_PROGRAM.md M9.",
        "",
    ]
    width = max((len(n) for n, _, _ in records), default=20) + 2
    body = [f"{n:<{width}} {t:<6} {v}" for n, t, v in sorted(records)]
    return "\n".join(head + body) + "\n"


def committed(zone: str) -> set[tuple[str, str, str]]:
    path = zone_path(zone)
    if not path.exists():
        return set()
    out: set[tuple[str, str, str]] = set()
    for line in path.read_text().splitlines():
        # A comment is a WHOLE line starting with ';'. Stripping from the first ';' anywhere would
        # truncate every DMARC and SPF record, because their values are semicolon-separated -- and
        # the truncated copy then reads as drift against itself, forever.
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        parts = line.split(None, 2)
        if len(parts) == 3:
            out.add((parts[0], parts[1], " ".join(parts[2].split())))
    return out


def labels_for(zone: str) -> tuple[str, ...]:
    """Everything the committed file mentions, plus the base set."""
    names = {n for n, _, _ in committed(zone)}
    labels = set(BASE_LABELS)
    for n in names:
        labels.add("" if n == zone else n[: -(len(zone) + 1)] if n.endswith("." + zone) else n)
    return tuple(sorted(labels))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zone", default="mumchimp.com")
    ap.add_argument("--export", action="store_true", help="print the live zone, do not compare")
    ap.add_argument("--check", action="store_true", help="diff live against the committed file")
    ap.add_argument("--write", action="store_true", help="with --export, write the file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    zone = args.zone
    try:
        found = live(zone, labels_for(zone))
    except Exception as exc:  # noqa: BLE001 -- cannot measure is its own exit code
        print(f"CANNOT ESTABLISH DNS for {zone}: {exc}", file=sys.stderr)
        return 2

    if args.export or not args.check:
        text = render(zone, found)
        if args.write:
            ZONE_DIR.mkdir(parents=True, exist_ok=True)
            zone_path(zone).write_text(text)
            print(f"wrote {_rel(zone_path(zone))}  ({len(found)} records)")
        else:
            print(text, end="")
        return 0

    want = committed(zone)
    if not want:
        print(f"NO COMMITTED ZONE at {_rel(zone_path(zone))} -- run --export --write",
              file=sys.stderr)
        return 1
    appeared, vanished = sorted(found - want), sorted(want - found)
    if args.json:
        print(json.dumps({"zone": zone, "records": len(found),
                          "appeared": appeared, "vanished": vanished}, indent=2))
    else:
        print(f"{zone}: {len(found)} live records, {len(want)} committed")
        for n, t, v in vanished:
            print(f"  GONE      {n} {t} {v}")
        for n, t, v in appeared:
            print(f"  APPEARED  {n} {t} {v}")
        if not appeared and not vanished:
            print("  no drift")
    return 1 if (appeared or vanished) else 0


if __name__ == "__main__":
    sys.exit(main())
