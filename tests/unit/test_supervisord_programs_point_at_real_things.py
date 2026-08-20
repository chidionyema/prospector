"""Every scheduled job inside the engine image must point at something that exists.

WHY THIS FILE EXISTS. `deploy/engine/supervisord.conf` is the only scheduler production
has. A typo in one `command=` line does not fail a build, does not fail a deploy and does
not fail a health check: supervisord starts the program, the shell says "No such file or
directory", supervisord restarts it, and the job is dead forever while every other signal
stays green. `restore-drill` is the precedent for a job that was written, wired into a
screen, and scheduled nowhere. This is the same class one step later - scheduled, and
pointing at nothing.

What this can and cannot prove. It reads the repo, so it proves a path is present in the
source tree the Dockerfile copies with `COPY . /app`. It cannot prove the file is
executable inside the image or that the command succeeds. Those need the image; this
needs a checkout, and it catches the typo, which is the failure that actually happens.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONF = REPO / "deploy" / "engine" / "supervisord.conf"
DOCKERFILE = REPO / "deploy" / "engine" / "Dockerfile"

# Paths a command may name that are NOT in the source tree, each with the reason it is
# absent. Anything not listed here has to exist on disk, so a new unexplained binary
# fails this test instead of failing silently in production.
BUILT_IN_THE_IMAGE = {
    # deploy/engine/Dockerfile:92-93 copies the Next.js build output and node_modules
    # from the `console` stage over the top of the `COPY . /app` tree. Neither is
    # committed, so neither can be checked from a checkout.
    "node_modules/next/dist/bin/next": "built by the console stage, not committed",
}


def _programs() -> dict[str, str]:
    """Return {program name: command line} for every [program:*] block."""
    text = CONF.read_text()
    out: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        header = re.match(r"^\[program:([^\]]+)\]\s*$", line)
        if header:
            current = header.group(1)
            continue
        if current and line.startswith("command="):
            out[current] = line[len("command=") :].strip()
            current = None
    return out


PROGRAMS = _programs()


def test_the_parser_actually_found_the_programs():
    """A guard that iterates an empty list passes and proves nothing.

    Every check below is parametrised over PROGRAMS. If the parser breaks - a renamed
    section syntax, a `command` split over continuation lines - pytest reports a row of
    passes over zero items. This is the only test here that is not parametrised, and it
    is the one that makes the rest mean something.
    """
    headers = re.findall(r"^\[program:([^\]]+)\]\s*$", CONF.read_text(), re.M)
    assert headers, f"no [program:*] sections parsed out of {CONF}"
    assert sorted(PROGRAMS) == sorted(headers), (
        "a [program:*] section has no command= line, or the parser dropped one: "
        f"headers={sorted(headers)} parsed={sorted(PROGRAMS)}"
    )


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_every_path_a_program_names_exists(name: str):
    """Resolve every token that looks like a path, and require it to be real."""
    missing = []
    for token in shlex.split(PROGRAMS[name]):
        if token.startswith("-") or "/" not in token:
            continue
        if token.startswith("/usr/local/bin/"):
            # Installed by the Dockerfile, checked separately below.
            continue
        if token in BUILT_IN_THE_IMAGE:
            continue
        # deploy/engine/Dockerfile:68 is `COPY . /app`, so /app IS this repo root inside
        # the image. An absolute /app path is checkable here, not an exception.
        relative = token[len("/app/") :] if token.startswith("/app/") else token
        if relative.startswith("/"):
            missing.append(token)
        elif not (REPO / relative).exists():
            missing.append(token)
    assert not missing, (
        f"[program:{name}] names {missing}, which is not in the source tree and is not "
        "listed in BUILT_IN_THE_IMAGE with a reason. supervisord will restart this "
        "program forever and no other signal will go red."
    )


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_every_python_module_a_program_runs_is_importable_from_disk(name: str):
    """`python -m a.b.c` fails at runtime, not at build time. Resolve it here instead."""
    tokens = shlex.split(PROGRAMS[name])
    for i, token in enumerate(tokens):
        if token != "-m" or i + 1 >= len(tokens):
            continue
        module = tokens[i + 1]
        stem = REPO / Path(*module.split("."))
        assert stem.with_suffix(".py").exists() or (stem / "__init__.py").exists(), (
            f"[program:{name}] runs `python -m {module}` and neither {stem}.py nor "
            f"{stem}/__init__.py exists"
        )


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_every_helper_under_usr_local_bin_is_installed_by_the_dockerfile(name: str):
    """A `/usr/local/bin/*.sh` that no COPY line installs is a program that never starts.

    The path is absolute, so nothing in the repo makes it true. Only a line in
    deploy/engine/Dockerfile does.
    """
    dockerfile = DOCKERFILE.read_text()
    for token in shlex.split(PROGRAMS[name]):
        if not token.startswith("/usr/local/bin/"):
            continue
        base = Path(token).name
        if base == "python":
            # deploy/engine/Dockerfile:99 sets PROSPECTOR_PYTHON to it; it ships with
            # the python base image rather than being copied in.
            continue
        assert (REPO / "deploy" / "engine" / base).exists(), (
            f"[program:{name}] runs {token} but deploy/engine/{base} does not exist"
        )
        assert re.search(rf"^COPY\s+deploy/engine/{re.escape(base)}\s+{re.escape(token)}\s*$",
                         dockerfile, re.M), (
            f"[program:{name}] runs {token} but no COPY line in deploy/engine/Dockerfile "
            f"installs it there. It will not exist in the image."
        )


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_every_periodic_interval_is_a_positive_whole_number_of_seconds(name: str):
    """periodic.sh passes argument 1 straight to `sleep`.

    deploy/engine/periodic.sh runs under `set -uo pipefail`, not `-e`, and a bad `sleep`
    argument does not stop the loop - it makes it spin. `sleep 300s` is not portable and
    `sleep five_minutes` busy-loops the container. The interval is a number or the job is
    a CPU leak.
    """
    tokens = shlex.split(PROGRAMS[name])
    for i, token in enumerate(tokens):
        if not token.endswith("/periodic.sh"):
            continue
        assert i + 1 < len(tokens), f"[program:{name}] calls periodic.sh with no interval"
        interval = tokens[i + 1]
        assert interval.isdigit() and int(interval) > 0, (
            f"[program:{name}] passes `{interval}` to periodic.sh as its sleep interval; "
            "it must be a positive whole number of seconds"
        )


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_every_receipt_key_is_a_bare_label_not_a_path(name: str):
    """receipt.sh writes `$PROSPECTOR_STORE_DIR/ops/receipts/<key>.json`.

    deploy/engine/receipt.sh does `cat > "$OUT/$KEY.json.tmp"`. A key containing a slash
    writes into a directory that mkdir never created, the redirect fails, and - because
    every failure in receipt.sh is deliberately swallowed so that observing a job can
    never fail it - the job keeps passing while its receipt silently never appears.
    """
    tokens = shlex.split(PROGRAMS[name])
    for i, token in enumerate(tokens):
        if not token.endswith("/receipt.sh"):
            continue
        assert i + 1 < len(tokens), f"[program:{name}] calls receipt.sh with no key"
        key = tokens[i + 1]
        assert "/" not in key, (
            f"[program:{name}] passes `{key}` to receipt.sh as its receipt key; a key "
            "with a slash writes to a directory receipt.sh never creates, and the "
            "failure is swallowed"
        )


def test_the_health_watch_program_is_the_one_that_asks_production_if_it_is_alive():
    """The specific wiring this file was written alongside, pinned by name.

    Everything above is generic. This is the one row that must not quietly disappear:
    before it existed, nothing on this estate ever made an HTTP request to production.
    """
    assert "health-watch" in PROGRAMS, (
        "[program:health-watch] is gone; nothing asks production whether it is serving"
    )
    command = PROGRAMS["health-watch"]
    assert "scripts/service_health.py" in command, command
    assert "/periodic.sh 300 " in command, (
        f"health-watch must run every 300s; its command is {command!r}"
    )
