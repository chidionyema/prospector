"""Every deploy/targets/*.sh implements the whole contract, and the doc lists every one of them.

An adapter is only ever exercised during a platform move. `deploy/cutover.sh` sources it, and by
the packing phase the engine is stopped and customers are waiting. A verb an adapter forgot shows
up as `command not found` inside that window, on the one code path with no cheap retry. Nothing
graded the adapters before this file: `deploy/targets/k8s.sh` was written by copying the shape of
`sshdocker.sh` by eye, which is exactly how the fifth one will lose a verb.

The verb list is READ OUT of `deploy/PORTABILITY.md` rather than typed here, so the document that
tells a person what to implement is the same list the machine grades against. A verb added to one
and not the other fails here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TARGETS_DIR = REPO / "deploy" / "targets"
PORTABILITY = REPO / "deploy" / "PORTABILITY.md"

# `t_start / t_stop` share one line in the doc, so the verbs are collected as tokens rather than
# per line. Anything of the shape t_<lowercase> inside the contract's fenced block counts.
_VERB = re.compile(r"\bt_[a-z_]+\b")


def _contract_verbs() -> set[str]:
    block = re.search(
        r"```\n(t_name.*?)```", PORTABILITY.read_text(encoding="utf-8"), re.DOTALL
    )
    assert block, f"no fenced verb block starting at t_name in {PORTABILITY}"
    return set(_VERB.findall(block.group(1)))


def _adapters() -> list[Path]:
    return sorted(TARGETS_DIR.glob("*.sh"))


VERBS = _contract_verbs()
ADAPTERS = _adapters()
IDS = [p.name for p in ADAPTERS]


def test_the_contract_names_verbs():
    """Vacuity guard. Every test below iterates VERBS; an empty parse would pass them all."""
    assert len(VERBS) >= 12, f"parsed only {sorted(VERBS)} out of {PORTABILITY}"


def test_there_is_more_than_one_adapter():
    """Vacuity guard. One adapter, or none, and the parametrised tests below grade nothing."""
    assert len(ADAPTERS) >= 4, f"found {IDS} in {TARGETS_DIR}"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_the_adapter_implements_every_verb(adapter: Path):
    body = adapter.read_text(encoding="utf-8")
    defined = {
        m.group(1) for m in re.finditer(r"^\s*(t_[a-z_]+)\s*\(\)", body, re.MULTILINE)
    }
    missing = sorted(VERBS - defined)
    assert not missing, (
        f"{adapter.name} does not define {missing}. deploy/cutover.sh calls every verb in "
        f"deploy/PORTABILITY.md, with the engine already stopped."
    )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_the_adapter_parses(adapter: Path):
    """`bash -n` on every adapter. A syntax error here is only ever found mid-cutover."""
    done = subprocess.run(
        ["bash", "-n", str(adapter)], capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0, f"{adapter.name}: {done.stderr.strip()}"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_the_adapter_refuses_to_run_as_a_script_and_do_nothing(adapter: Path):
    """Running an adapter file rather than sourcing it defines every function, falls off the end
    and exits 0 — a silent success that deploys nothing. Measured 2026-08-18: three consecutive
    `bash fly.sh t_release` calls exited 0 with no output while `fly releases` never moved off v3.
    Every adapter carries the dispatch guard that turns that into a real call."""
    body = adapter.read_text(encoding="utf-8")
    assert 'BASH_SOURCE[0]}" = "${0}"' in body, (
        f"{adapter.name} has no `if [ \"${{BASH_SOURCE[0]}}\" = \"${{0}}\" ]` dispatch block, so "
        f"`bash {adapter.name} t_release` exits 0 having deployed nothing"
    )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_the_adapter_is_named_in_the_portability_doc(adapter: Path):
    """An adapter nobody documented is one nobody knows they can move to."""
    doc = PORTABILITY.read_text(encoding="utf-8")
    assert f"deploy/targets/{adapter.name}" in doc, (
        f"{adapter.name} exists but deploy/PORTABILITY.md never mentions it"
    )


def test_the_doc_names_no_adapter_that_is_missing():
    """And the reverse: a documented escape hatch whose file was deleted or renamed reads as an
    option we have, right up until the move."""
    doc = PORTABILITY.read_text(encoding="utf-8")
    named = set(re.findall(r"deploy/targets/([a-z0-9_]+\.sh)", doc))
    missing = sorted(n for n in named if not (TARGETS_DIR / n).exists())
    assert not missing, f"deploy/PORTABILITY.md offers {missing}, which are not on disk"


def _manifests(adapter: Path) -> str:
    """The YAML the adapter applies, with its prose stripped out.

    Reading the whole file would grade the COMMENTS: k8s.sh explains at length why RollingUpdate
    is wrong, and a scan of the raw text finds that explanation and calls it a defect. Same trap
    as memory `a-source-scan-that-reads-comments-grades-the-prose`. Only the heredoc bodies are
    manifest."""
    body = adapter.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<<YAML\n(.*?)\nYAML\n", body, re.DOTALL))


def test_the_kubernetes_adapter_cannot_run_two_engines():
    """The single-instance rule is a money fence: two engines keep two spend ledgers and can each
    spend the full daily cap (deploy/PORTABILITY.md item 1, EDGE-1 in
    docs/ENGINE_MIGRATION_PROGRAM.md).

    Kubernetes is the one platform whose DEFAULT breaks it. A Deployment defaults to
    `strategy: RollingUpdate`, which starts the replacement pod before terminating the old one, so
    two engines run on every release until the handover completes. Only `Recreate` holds the rule,
    and it is one word — exactly the kind of line a later edit drops without noticing."""
    yaml = _manifests(TARGETS_DIR / "k8s.sh")
    assert yaml.strip(), "no <<YAML heredoc found in k8s.sh — the manifest scan graded nothing"
    assert re.search(r"^\s*replicas:\s*1\s*$", yaml, re.MULTILINE), "no `replicas: 1` in k8s.sh"
    assert re.search(r"strategy:\s*\n\s*type:\s*Recreate", yaml), (
        "k8s.sh does not pin `strategy: type: Recreate`, so a release runs two engines at once"
    )
    assert "RollingUpdate" not in yaml, "k8s.sh sets RollingUpdate in a manifest"


def test_the_kubernetes_ports_are_not_published_to_the_internet():
    """deploy/PORTABILITY.md item 6: 8601 and 8611 are private-network only, no public IP. A
    Service of type LoadBalancer or NodePort puts both admin dashboards on the open internet."""
    yaml = _manifests(TARGETS_DIR / "k8s.sh")
    assert "type: ClusterIP" in yaml, "k8s.sh Service is not ClusterIP"
    for public in ("LoadBalancer", "NodePort", "hostPort", "Ingress"):
        assert public not in yaml, f"k8s.sh manifest exposes the engine with {public}"


# --- the second half of the class: everything that ENUMERATES the adapters ------------------
#
# Writing the adapter is not the whole job. On 2026-08-20 `deploy/targets/k8s.sh` was written and
# `deploy/cutover.sh --to k8s` worked immediately, because cutover.sh resolves a side by looking
# for the file. Two other callers had memorised the three names instead, so the ops console and
# `engine_failover.py switch` both refused `k8s` with the adapter sitting on disk beside them —
# and the founder's bar is that the migration is driven FROM the dashboard.

ENUMERATORS = (
    REPO / "scripts" / "engine_failover.py",
    REPO / "prospector" / "ops" / "console_api.py",
)

# `fly` and `laptop` are the two failover SIDES and appear throughout these files for reasons that
# have nothing to do with the adapter list — the active-side marker, the standby sync, the drain.
# Any OTHER adapter name appearing as a string literal is someone writing the list down again.
FAILOVER_SIDES = {"fly", "laptop"}


@pytest.mark.parametrize("path", ENUMERATORS, ids=[p.name for p in ENUMERATORS])
def test_the_target_list_is_not_typed_out_a_second_time(path: Path):
    others = {p.stem for p in ADAPTERS} - FAILOVER_SIDES
    assert others, "vacuity: every adapter on disk is also a failover side, so this grades nothing"
    body = path.read_text(encoding="utf-8")
    typed = sorted(n for n in others if f'"{n}"' in body or f"'{n}'" in body)
    assert not typed, (
        f"{path.name} names {typed} as a string literal. The platform list is discovered from "
        f"deploy/targets/*.sh by engine_failover.deploy_targets(); a second copy goes stale the "
        f"next time an adapter lands."
    )


def test_the_failover_script_offers_every_adapter_on_disk():
    """The console validates `engine.switch` against `engine_failover.py targets --json`, so this
    is the list an operator can actually pick from in the dashboard."""
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "engine_failover.py"), "targets", "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr.strip()[:400]
    assert sorted(json.loads(done.stdout)) == sorted(p.stem for p in ADAPTERS)
