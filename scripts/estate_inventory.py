#!/usr/bin/env python3
"""One inventory of every resource this business depends on.

Three lists used to answer "what unattended work does this business run, and where?" and none
of them met: `scripts/fly_estate_probe.py` knew about Fly, `ops/launchd/*.json` knew about the
laptop, `.github/workflows/*.yml` knew about scheduled CI. A resource in the seam between them
ran undescribed for a day and nothing said so.

This joins them, and adds the classes no list held at all: DNS, datastores, object storage,
TLS certificates, secrets, log sinks, the payment integration.

Two rules make the answer trustworthy:

  * A resource is DISCOVERED from the running world, never from the declaration. Every
    discoverer reads a provider API, `launchctl`, or a committed file that is *not* this
    declaration. A tool that reads its own answer sheet cannot find a surprise.

  * A describing file counts only when it is on `origin/main`. A resource described by an
    uncommitted file is exactly the failure being caught: it exists on one laptop and dies
    with it. Same choice `fly_estate_probe.py` makes at `described_apps()`.

Secret VALUES are never read and never printed. The secret class inventories NAMES.

Reusable for another project: the classes below are generic, the estate is not. Everything
project-specific -- which apps, which domains, which repo -- lives in the declaration file.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DECLARATION = REPO / "ops" / "config" / "estate_resources.yaml"
DEFAULT_REF = "origin/main"
TIMEOUT = 40

# The ten classes, from `docs/MIGRATION_AND_DR_PROGRAM.md` M1. Generic on purpose: they are
# the classes any business has, not the resources this one happens to own.
CLASSES = (
    "compute",
    "datastore",
    "object_storage",
    "dns",
    "tls_certificate",
    "secret",
    "log_sink",
    "scheduled_job",
    "payment_integration",
    "ci_runner",
)

UNKNOWN = "?"


@dataclass(frozen=True)
class Found:
    """A resource seen in the running world."""

    cls: str
    name: str
    where: str
    last_run: str = "—"

    @property
    def key(self) -> str:
        return f"{self.cls}:{self.name}"


@dataclass
class Row:
    """A found resource joined to what the repo says about it."""

    found: Found
    described_by: str | None = None
    restore: str | None = None
    problem: str | None = None
    admitted: str | None = None


@dataclass
class Sweep:
    """What one discoverer came back with."""

    rows: list[Found] = field(default_factory=list)
    blind: str | None = None  # set when the class could not be probed at all


# ─────────────────────────────── running commands ────────────────────────────────


def _run(cmd: list[str], *, timeout: int = TIMEOUT) -> tuple[int, str]:
    """Run a command, never raise. Returns (returncode, stdout)."""
    if shutil.which(cmd[0]) is None:
        return 127, ""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""
    return proc.returncode, proc.stdout


def _run_json(cmd: list[str], *, timeout: int = TIMEOUT) -> list | dict | None:
    code, out = _run(cmd, timeout=timeout)
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def tracked_paths(ref: str = DEFAULT_REF) -> set[str] | None:
    """Every path committed on `ref`. None when the ref cannot be read at all."""
    code, out = _run(["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", ref])
    if code != 0:
        return None
    return {line.strip() for line in out.splitlines() if line.strip()}


# ───────────────────────────────── discoverers ───────────────────────────────────
#
# Each returns a Sweep. `blind` is set -- and rows left empty -- when the class could not be
# probed, which is a different answer from "probed, found nothing" and is reported as such.


def discover_compute(cfg: dict) -> Sweep:
    apps = _fly_apps(cfg)
    if apps is None:
        return Sweep(blind="`fly apps list` did not answer")
    return Sweep([Found("compute", a["Name"], f"fly/{a.get('Status') or 'unknown'}") for a in apps])


def discover_datastore(cfg: dict) -> Sweep:
    apps = _fly_apps(cfg)
    if apps is None:
        return Sweep(blind="`fly apps list` did not answer, so no app could be asked for volumes")
    rows: list[Found] = []
    for app in sorted(a["Name"] for a in apps):
        vols = _run_json(["fly", "volumes", "list", "-a", app, "--json"])
        if vols is None:
            return Sweep(blind=f"`fly volumes list -a {app}` did not answer")
        for v in vols:
            rows.append(
                Found("datastore", f"{app}/{v['name']}", f"fly/{v['region']} {v['size_gb']}GB")
            )
    return Sweep(rows)


def discover_object_storage(cfg: dict) -> Sweep:
    """R2 buckets. Needs credentials in the environment; their VALUES are never printed."""
    account = os.environ.get("R2_ACCOUNT_ID")
    key = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (account and key and secret):
        return Sweep(blind="R2 credentials are not in this environment (names only: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY)")
    try:
        import boto3  # noqa: PLC0415 - optional dependency, only needed on this path
    except ImportError:
        return Sweep(blind="boto3 is not installed in this interpreter")
    try:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name="auto",
        )
        buckets = client.list_buckets().get("Buckets", [])
    except Exception as exc:  # noqa: BLE001 - any failure means "could not look"
        return Sweep(blind=f"R2 refused the listing: {type(exc).__name__}")
    return Sweep([Found("object_storage", b["Name"], "cloudflare-r2") for b in buckets])


def discover_dns(cfg: dict) -> Sweep:
    """One resource per zone we own. The record-level diff is `scripts/dns_zone.py` (M9)."""
    domains = cfg.get("owns", {}).get("domains") or []
    # `${ESTATE_ZONE}` in the declaration is the estate's DNS zone, declared once in the platform
    # (crew#796). A missing zone is an error here, never an empty zone that reads as "nothing owned".
    domains = [d.replace("${ESTATE_ZONE}", os.environ["ESTATE_ZONE"]) if "${ESTATE_ZONE}" in d else d
               for d in domains]
    return Sweep([Found("dns", d, "godaddy") for d in domains])


def discover_tls_certificate(cfg: dict) -> Sweep:
    apps = _fly_apps(cfg)
    if apps is None:
        return Sweep(blind="`fly apps list` did not answer, so no app could be asked for certs")
    rows: list[Found] = []
    for app in sorted(a["Name"] for a in apps):
        certs = _run_json(["fly", "certs", "list", "-a", app, "--json"])
        if certs is None:
            return Sweep(blind=f"`fly certs list -a {app}` did not answer")
        for c in certs:
            rows.append(
                Found("tls_certificate", c["hostname"], f"fly/{app}", _day(c.get("updated_at")))
            )
    return Sweep(rows)


def discover_secret(cfg: dict) -> Sweep:
    """NAMES only. This function must never read or print a secret value."""
    apps = _fly_apps(cfg)
    if apps is None:
        return Sweep(blind="`fly apps list` did not answer, so no app could be asked for secrets")
    rows: list[Found] = []
    for app in sorted(a["Name"] for a in apps):
        secrets = _run_json(["fly", "secrets", "list", "-a", app, "--json"])
        if secrets is None:
            return Sweep(blind=f"`fly secrets list -a {app}` did not answer")
        for s in secrets:
            rows.append(Found("secret", f"{app}/{s['name']}", "fly"))
    repo = cfg.get("owns", {}).get("github_repo")
    if repo:
        gh = _run_json(["gh", "secret", "list", "-R", repo, "--json", "name"])
        if gh is None:
            return Sweep(blind=f"`gh secret list -R {repo}` did not answer")
        for s in gh:
            rows.append(Found("secret", f"github/{s['name']}", "github-actions"))
    return Sweep(rows)


def discover_log_sink(cfg: dict) -> Sweep:
    """List the log trees that EXIST on the engine, not the ones a config file says exist.

    The earlier version of this read `ops/config/log_rotation.yaml` -- the same file the join
    then grades the answer against. That check can never fail: every sink it finds is described
    by construction. A log tree that exists on the volume and is in nobody's rotation config is
    the one that fills a 20GB disk at 3am, and it is invisible to a tool that reads the config.
    """
    app = (cfg.get("owns") or {}).get("log_host_app")
    if not app:
        return Sweep(blind="log_sink: owns.log_host_app names no app to look in")
    code, out = _run(
        ["fly", "ssh", "console", "-a", app, "-C",
         "sh -lc 'find /data/logs -maxdepth 2 -type f -name \"*.log\" -o -maxdepth 2 -type f -name \"*.jsonl\" 2>/dev/null | head -60'"],
        timeout=60,
    )
    if code != 0:
        return Sweep(blind=f"log_sink: could not reach {app} to list /data/logs (exit {code})")
    rows = [
        Found("log_sink", line.strip(), f"fly/{app}")
        for line in out.splitlines()
        if line.strip().startswith("/")
    ]
    return Sweep(rows=rows)


def discover_scheduled_job(cfg: dict) -> Sweep:
    """Three schedulers, one class: launchd here, supervisord on the engine, GitHub cron."""
    rows: list[Found] = []

    prefixes = tuple(cfg.get("owns", {}).get("launchd_prefixes") or [])
    if prefixes:
        code, out = _run(["launchctl", "list"])
        if code != 0:
            return Sweep(blind="`launchctl list` did not answer")
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            label = parts[2].strip()
            if label.startswith(prefixes):
                rows.append(Found("scheduled_job", f"launchd/{label}", "laptop", f"exit={parts[1]}"))

    for conf in cfg.get("owns", {}).get("supervisord_configs") or []:
        path = REPO / conf
        if not path.exists():
            return Sweep(blind=f"{conf} is not on this machine")
        for prog in sorted(set(re.findall(r"^\[program:([A-Za-z0-9_-]+)\]", path.read_text(encoding="utf-8"), re.M))):
            rows.append(Found("scheduled_job", f"supervisord/{prog}", conf.split("/")[1]))

    workflows = REPO / ".github" / "workflows"
    if workflows.is_dir():
        for wf in sorted(workflows.glob("*.yml")):
            body = wf.read_text(encoding="utf-8")
            if re.search(r"^\s*schedule:", body, re.M) and re.search(r"^\s*-\s*cron:", body, re.M):
                rows.append(Found("scheduled_job", f"workflow/{wf.name}", "github-actions"))

    return Sweep(rows)


def discover_payment_integration(cfg: dict) -> Sweep:
    """Stripe webhook endpoints. Needs the live key; its value is never printed."""
    key_name = cfg.get("owns", {}).get("stripe_key_env") or "STRIPE_LIVE_API_KEY"
    if not os.environ.get(key_name):
        return Sweep(blind=f"the Stripe key is not in this environment (name only: {key_name})")
    try:
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        req = urllib.request.Request(  # noqa: S310 - fixed https host
            "https://api.stripe.com/v1/webhook_endpoints?limit=100",
            headers={"Authorization": f"Bearer {os.environ[key_name]}"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - any failure means "could not look"
        return Sweep(blind=f"Stripe refused the listing: {type(exc).__name__}")
    return Sweep(
        [Found("payment_integration", e["url"], f"stripe/{e.get('status', '?')}") for e in payload.get("data", [])]
    )


def discover_ci_runner(cfg: dict) -> Sweep:
    app = cfg.get("owns", {}).get("ci_app")
    if not app:
        return Sweep()
    machines = _run_json(["fly", "machines", "list", "-a", app, "--json"])
    if machines is None:
        return Sweep(blind=f"`fly machines list -a {app}` did not answer")
    # A pool, not a list of machines. Runner machines are created and destroyed by the hour and
    # carry generated names, so naming one in a declaration guarantees the declaration is wrong
    # by tomorrow. The durable resource is the pool: app plus process group.
    pools: dict[tuple[str, str], list[dict]] = {}
    for m in machines:
        group = (m.get("config") or {}).get("metadata", {}).get("fly_process_group") or "app"
        pools.setdefault((app, group), []).append(m)
    rows = []
    for (a, group), members in sorted(pools.items()):
        regions = ",".join(sorted({m.get("region", "?") for m in members}))
        started = sum(1 for m in members if m.get("state") == "started")
        rows.append(
            Found(
                "ci_runner",
                f"{a}/{group}",
                f"fly/{regions} {started}/{len(members)} started",
                _day(max((m.get("updated_at") or "") for m in members)),
            )
        )
    return Sweep(rows)


DISCOVERERS = {
    "compute": discover_compute,
    "datastore": discover_datastore,
    "object_storage": discover_object_storage,
    "dns": discover_dns,
    "tls_certificate": discover_tls_certificate,
    "secret": discover_secret,
    "log_sink": discover_log_sink,
    "scheduled_job": discover_scheduled_job,
    "payment_integration": discover_payment_integration,
    "ci_runner": discover_ci_runner,
}

# Every class has a discoverer, and the two lists cannot drift apart unnoticed.
assert tuple(DISCOVERERS) == CLASSES, "DISCOVERERS and CLASSES disagree"


# ──────────────────────────────────── helpers ────────────────────────────────────


_FLY_CACHE: dict[str, list | None] = {}


def _fly_apps(cfg: dict) -> list[dict] | None:
    """Owned Fly apps. Cached: five discoverers want the same list, Fly is asked once."""
    if "apps" not in _FLY_CACHE:
        apps = _run_json(["fly", "apps", "list", "--json"])
        _FLY_CACHE["apps"] = apps
    apps = _FLY_CACHE["apps"]
    if apps is None:
        return None
    prefixes = tuple(cfg.get("owns", {}).get("fly_app_prefixes") or [])
    if not prefixes:
        return list(apps)
    return [a for a in apps if a.get("Name", "").startswith(prefixes)]


def _day(stamp: str | None) -> str:
    """An ISO timestamp trimmed to its date, which is the resolution anyone reads."""
    if not stamp or len(stamp) < 10:
        return "—"
    return stamp[:10]


def _yaml_paths_under(text: str, section: str) -> list[str]:
    """The `path:` values inside one top-level YAML section.

    Deliberately not a YAML parse: this reads a file whose comments carry the reasoning, and
    a line scan keeps the dependency list of this script empty.
    """
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if re.match(rf"^{re.escape(section)}:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            break
        if inside:
            m = re.match(r"^\s*-\s*path:\s*(\S.*?)\s*$", line)
            if m:
                out.append(m.group(1))
    return out


def load_declaration(path: Path) -> dict:
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover - PyYAML is a hard dependency of this repo
        raise SystemExit("PyYAML is required to read the declaration") from None
    if not path.exists():
        raise SystemExit(f"declaration not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ──────────────────────────────────── the join ───────────────────────────────────


def _lookup(table: dict, key: str) -> dict | None:
    """Exact key first, then the most specific glob. A declaration may cover a family of
    resources -- 16 launchd jobs, 79 secrets -- but only through a form that stays per-resource:
    see `described_by_template` and `names_listed_in` below. A glob never waves anything through."""
    if key in table:
        return table[key]
    matches = [(pat, val) for pat, val in table.items() if "*" in pat and fnmatch.fnmatch(key, pat)]
    if not matches:
        return None
    return max(matches, key=lambda kv: len(kv[0].rstrip("*")))[1]


def _leaf(name: str) -> str:
    """The part of a resource name that varies within a family: the label, the file, the key."""
    return name.rsplit("/", 1)[-1]


def _file_lists(path: str, needle: str, mode: str = "exact", ref: str = DEFAULT_REF) -> bool | None:
    """Does the committed file at `path` actually account for `needle`?

    This is what makes a family declaration stricter than one hand-written entry per resource
    rather than looser. `deploy/secrets.required` is the file a move reads to learn what the
    engine cannot boot without; a secret that is set on the app but absent from that file is
    exactly the one that makes a new provider come up broken.

    exact -- the name is a line of its own, or the KEY of a `KEY=value` line. Both forms are
    one-name-per-line files. A bare substring match would let a mention inside a comment count
    as a description, which is how a source scan ends up grading prose.
    glob  -- some line of the file, read as a shell glob, matches the name. This is for
    `ops/config/log_rotation.yaml`, which describes log trees by pattern rather than by name.

    Returns None when the file cannot be read, so "I could not check" never reads as "fine".
    """
    code, out = _run(["git", "-C", str(REPO), "show", f"{ref}:{path}"])
    if code != 0:
        return None
    for raw in out.splitlines():
        line = raw.strip().lstrip("-").strip().strip('"\'')
        if not line or line.startswith("#"):
            continue
        if mode == "glob":
            token = line.split(":", 1)[1].strip().strip('"\'') if ":" in line and "/" not in line.split(":", 1)[0] else line
            if "/" in token and fnmatch.fnmatch(needle, token):
                return True
        else:
            if line == needle or line.split("=", 1)[0].strip() == needle:
                return True
    return False


def cited_issues(cfg: dict) -> set[int]:
    """Every issue number the declaration cites as the owner of a gap."""
    nums: set[int] = set()

    def take(entry: object) -> None:
        if isinstance(entry, dict) and str(entry.get("issue", "")).strip().isdigit():
            nums.add(int(entry["issue"]))

    for entry in (cfg.get("admitted_gaps") or {}).values():
        take(entry)
    for entry in (cfg.get("admitted_blind_classes") or {}).values():
        take(entry)
    for entry in (cfg.get("resources") or {}).values():
        if isinstance(entry, dict):
            take(entry.get("restore_gap"))
    return nums


def issue_states(nums: set[int]) -> dict[int, str | None]:
    """Ask the tracker what state each cited issue is in. None means it could not be read.

    An admission is a promise that somebody owns the gap, and the promise is worth nothing
    once the issue is closed. Nothing checked that until 2026-08-21, when all six numbers in
    the declaration turned out to be closed and five of them were CSS or copy tickets -- one
    of them, an em-dash fix, was excusing the only record of who bought what.
    """
    states: dict[int, str | None] = {}
    for n in sorted(nums):
        try:
            out = subprocess.run(
                ["gh", "issue", "view", str(n), "--json", "state", "-q", ".state"],
                capture_output=True, text=True, timeout=20, cwd=REPO,
            )
        except (OSError, subprocess.SubprocessError):
            states[n] = None
            continue
        states[n] = out.stdout.strip().upper() or None if out.returncode == 0 else None
    return states


def stale_citation(num: object, states: dict[int, str | None]) -> str | None:
    """Why this citation cannot excuse anything, or None when it can.

    Every branch that is not a live open issue returns a reason. There is deliberately no
    silent fall-through: an unreadable tracker must cost the same as a closed issue, because
    the alternative is an excuse that quietly survives whatever it was waiting on.
    """
    if num is None or not str(num).strip().isdigit():
        return f"it names {num!r}, which is not an issue number"
    n = int(num)
    if n not in states:
        return f"issue #{n} was not checked"
    state = states[n]
    if state is None:
        return f"issue #{n} could not be read"
    if state != "OPEN":
        return f"issue #{n} is {state.lower()}, so nothing owns this gap"
    return None


def reconcile(found: list[Found], cfg: dict, committed: set[str] | None,
              states: dict[int, str | None]) -> list[Row]:
    """Join what is running to what the repo says about it.

    `committed` is every path on the ref. None means the ref could not be read, in which case
    no path can be confirmed and every row says so rather than passing by default.
    """
    resources = cfg.get("resources") or {}
    gaps = cfg.get("admitted_gaps") or {}
    rows: list[Row] = []
    for f in sorted(found, key=lambda x: (CLASSES.index(x.cls), x.name)):
        row = Row(found=f)
        entry = _lookup(resources, f.key)
        gap = _lookup(gaps, f.key)
        if gap:
            why = stale_citation(gap.get("issue"), states)
            if why:
                row.problem = f"admission does not hold: {why}"
            else:
                row.admitted = str(gap.get("why", "")).strip()
                row.problem = f"admitted gap (issue #{gap.get('issue', '?')})"
            rows.append(row)
            continue
        if not entry:
            row.problem = "undescribed: no entry in the declaration"
            rows.append(row)
            continue
        # A family entry describes each member by its OWN file, so a new member with no file
        # is undescribed even though the family is declared.
        template = entry.get("described_by_template")
        row.described_by = template.format(name=_leaf(f.name)) if template else entry.get("described_by")
        row.restore = entry.get("restore")
        listed_in = entry.get("names_listed_in")
        if not row.described_by:
            row.problem = "undescribed: the entry names no describing file"
        elif listed_in and committed is not None and listed_in in committed:
            match_mode = entry.get("match", "exact")
            probe = f.name if match_mode == "glob" else _leaf(f.name)
            found_in_file = _file_lists(listed_in, probe, match_mode)
            if found_in_file is False:
                row.problem = f"undescribed: {probe} is not accounted for in {listed_in}"
            elif found_in_file is None:
                row.problem = f"could not read {listed_in} on {DEFAULT_REF}"
        if row.problem:
            pass
        elif committed is None:
            row.problem = f"could not read {DEFAULT_REF}, so no describing file could be confirmed"
        elif row.described_by not in committed:
            row.problem = f"described_by is not on {DEFAULT_REF}: {row.described_by}"
        elif row.restore == "not_applicable":
            # Derived output, not state. A log file is rebuilt by the job that writes it, so a
            # restore command here would be a fiction. The entry must say why.
            why = entry.get("restore_why")
            row.restore = f"n/a — {why}" if why else None
            if not why:
                row.problem = "restore is not_applicable with no restore_why"
        elif not row.restore:
            # A restore_gap excuses ONLY this column. The describing checks above still ran and
            # still failed if they were going to, which is what catches the 17th launchd job
            # someone adds with no JSON beside it.
            rgap = entry.get("restore_gap")
            why = stale_citation(rgap.get("issue"), states) if rgap else "there is none"
            if rgap and not why:
                row.restore = f"admitted gap (issue #{rgap.get('issue', '?')})"
                row.admitted = str(rgap.get("why", "")).strip()
            elif rgap:
                row.problem = f"no restore command, and the admission does not hold: {why}"
            else:
                row.problem = "no restore command"
        rows.append(row)
    return rows


def stale_entries(rows: list[Row], cfg: dict) -> list[str]:
    """Declared resources that nothing found. Reported, never fatal: a class the run was
    blind to would otherwise turn every one of its entries into a false alarm."""
    seen = {r.found.key for r in rows}
    stale = []
    for k in (cfg.get("resources") or {}):
        # A family entry is a pattern, so it never equals a discovered key. Ask whether it
        # matched anything instead; the literal comparison reported all ten patterns as stale.
        hit = any(fnmatch.fnmatch(x, k) for x in seen) if "*" in k else k in seen
        if not hit:
            stale.append(k)
    return sorted(stale)


# ──────────────────────────────────── output ─────────────────────────────────────


def render(rows: list[Row], blind: dict[str, str], stale: list[str]) -> str:
    headers = ("NAME", "CLASS", "WHERE", "DESCRIBED BY", "RESTORE", "LAST")
    table = [
        (
            r.found.name,
            r.found.cls,
            r.found.where,
            r.described_by or (r.problem or "—"),
            (r.restore or "—"),
            r.found.last_run,
        )
        for r in rows
    ]
    widths = [max(len(h), *(len(t[i]) for t in table)) if table else len(h) for i, h in enumerate(headers)]
    widths[4] = min(widths[4], 46)
    out = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(),
        "  ".join("─" * widths[i] for i in range(len(headers))),
    ]
    for t in table:
        cells = [t[i][: widths[i]].ljust(widths[i]) for i in range(len(headers))]
        out.append("  ".join(cells).rstrip())

    problems = [r for r in rows if r.problem and not r.admitted]
    out.append("")
    counts = {c: sum(1 for r in rows if r.found.cls == c) for c in CLASSES}
    out.append("Per class: " + ", ".join(f"{c}={counts[c]}" + ("?" if c in blind else "") for c in CLASSES))
    if blind:
        out.append("")
        out.append(f"COULD NOT LOOK ({len(blind)} of {len(CLASSES)} classes) — these counts are not zero, they are unknown:")
        for cls, why in sorted(blind.items()):
            out.append(f"  {cls}: {why}")
    if stale:
        out.append("")
        out.append(f"DECLARED BUT NOT FOUND ({len(stale)}) — a leftover entry, or a class this run was blind to:")
        for key in stale:
            out.append(f"  {key}")
    if problems:
        out.append("")
        out.append(f"UNDESCRIBED ({len(problems)}):")
        for r in problems:
            out.append(f"  {r.found.key}: {r.problem}")
    admitted = [r for r in rows if r.admitted]
    if admitted:
        out.append("")
        out.append(f"ADMITTED GAPS ({len(admitted)}) — known, ticketed, not yet closed:")
        # Grouped by reason. Printed per row, sixty-three admitted resources repeat the same
        # five paragraphs sixty-three times and the section stops being read at all.
        groups: dict[str, list[str]] = {}
        for r in admitted:
            groups.setdefault(f"{r.problem or 'restore admitted'} — {r.admitted}", []).append(r.found.key)
        for why, keys in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            out.append(f"  {len(keys)}x {why}")
            head = ", ".join(keys[:4])
            out.append(f"       {head}{f', and {len(keys) - 4} more' if len(keys) > 4 else ''}")
    out.append("")
    out.append(
        f"{len(rows)} resources, {len(problems)} undescribed, {len(admitted)} admitted, "
        f"{len(blind)} classes not probed."
    )
    return "\n".join(out)


def verdict(rows: list[Row], blind: dict[str, str], cfg: dict,
             states: dict[int, str | None]) -> int:
    """Non-zero when anything is undescribed, or when a class could not be probed and that
    blindness is not itself admitted. A silent hole must cost the same as a loud one."""
    if any(r.problem and not r.admitted for r in rows):
        return 1
    admitted_blind = cfg.get("admitted_blind_classes") or {}
    for cls in blind:
        entry = admitted_blind.get(cls)
        if not isinstance(entry, dict) or stale_citation(entry.get("issue"), states):
            return 1
    return 0


def sweep(cfg: dict, only: tuple[str, ...] = CLASSES) -> tuple[list[Found], dict[str, str]]:
    found: list[Found] = []
    blind: dict[str, str] = {}
    for cls in only:
        result = DISCOVERERS[cls](cfg)
        if result.blind:
            blind[cls] = result.blind
        found.extend(result.rows)
    return found, blind


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--declaration", type=Path, default=DEFAULT_DECLARATION)
    ap.add_argument("--ref", default=DEFAULT_REF, help="the ref a describing file must be on")
    ap.add_argument("--class", dest="only", action="append", choices=CLASSES,
                    help="probe one class only; repeatable")
    ap.add_argument("--json", action="store_true", help="machine-readable, for the console")
    ap.add_argument("--out", metavar="PATH", default=None,
                    help="also write the JSON report here, atomically. A scheduled run cannot "
                         "just redirect stdout: launchd APPENDS to StandardOutPath, so the file "
                         "would grow into concatenated reports that no reader can parse.")
    args = ap.parse_args(argv)

    cfg = load_declaration(args.declaration)
    found, blind = sweep(cfg, tuple(args.only) if args.only else CLASSES)
    committed = tracked_paths(args.ref)
    states = issue_states(cited_issues(cfg))
    rows = reconcile(found, cfg, committed, states)
    stale = stale_entries(rows, cfg) if not args.only else []

    report = {
            "resources": [
                {
                    "name": r.found.name, "class": r.found.cls, "where": r.found.where,
                    "described_by": r.described_by, "restore": r.restore,
                    "last_run": r.found.last_run, "problem": r.problem, "admitted": r.admitted,
                }
                for r in rows
            ],
            "blind": blind,
            "declared_but_not_found": stale,
            "undescribed": sum(1 for r in rows if r.problem and not r.admitted),
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True))
        tmp.replace(out)   # atomic, so a reader never catches half a report

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(rows, blind, stale))
    return verdict(rows, blind, cfg, states)


if __name__ == "__main__":
    sys.exit(main())
