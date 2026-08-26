"""The mirror of `~/.claude` in this repo must stay a mirror, and must stay free of credentials.

WHY THIS EXISTS
---------------
`scripts/claude_guards/` carries a copy of the laws and hook scripts that live in `~/.claude`,
because until 2026-08-20 they existed on exactly one disk with no version control. The founder's
instruction was "~/.claude/ is not a git repo, easy fix is to copy into prospector".

A copy has two failure modes, and neither announces itself:

1. It stops matching. `settings.json` names a script that the mirror does not carry, so a machine
   bootstrapped from this repo wires a hook to a file that is not there. The guard does not refuse
   anything and nothing says so -- the estate simply reverts to the behaviour that guard was
   written to stop.
2. It carries something it must not. `scripts/backup_agent_estate.py` found a private key and a
   93-character GitHub token inside this same estate, in paths nobody put them in deliberately.
   The allow-list in `scripts/agent_estate_sync.py` is a claim about PATHS; only reading the bytes
   is a claim about contents.

Everything here is machine-independent on purpose: it reads the mirror in the repo, never
`~/.claude`, so it means the same thing on this laptop, on CI and inside the engine container.
Comparing the mirror against a live estate is `agent_estate_sync.py --check`, which is a different
job because it can only run where an estate exists.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest
from tool_gate import require_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
MIRROR = REPO_ROOT / "scripts" / "claude_guards"
SETTINGS = MIRROR / "settings.json"


def _load_sync():
    path = REPO_ROOT / "scripts" / "agent_estate_sync.py"
    spec = importlib.util.spec_from_file_location("agent_estate_sync", path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sync = _load_sync()


def _hook_commands() -> list[str]:
    """Every shell command settings.json wires, across all hook events and the status line."""
    settings = json.loads(SETTINGS.read_text())
    out: list[str] = []
    for entries in (settings.get("hooks") or {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                if cmd := hook.get("command"):
                    out.append(cmd)
    if cmd := (settings.get("statusLine") or {}).get("command"):
        out.append(cmd)
    return out


def test_the_mirror_carries_the_laws_and_the_settings():
    """The two files that are not scripts. Without either, a bootstrapped machine has no rules."""
    laws = MIRROR / "CLAUDE.global.md"
    assert laws.is_file(), f"{laws} is missing: a new machine would start with no laws at all"
    assert "LAW 1" in laws.read_text(), "CLAUDE.global.md does not carry the numbered laws"
    assert SETTINGS.is_file(), f"{SETTINGS} is missing: nothing would wire the guards"


def test_the_mirror_has_no_file_named_claude_md():
    """Claude Code reads any CLAUDE.md as instructions scoped to its directory.

    A verbatim copy of the GLOBAL laws under that name would start governing this repo, which is
    the exact scope leak `~/.claude/scripts/scope-guard.py` exists to refuse.
    """
    offenders = [p.relative_to(REPO_ROOT) for p in MIRROR.rglob("CLAUDE.md")]
    assert not offenders, f"rename these to CLAUDE.global.md: {offenders}"


def test_every_script_settings_json_names_is_mirrored():
    """A hook naming `~/.claude/scripts/X` needs X in the mirror, or a fresh machine loses it."""
    named = sorted({m for c in _hook_commands() for m in re.findall(r"\.claude/scripts/([\w.-]+)", c)})
    assert named, "parsed no hook scripts out of settings.json -- the parser has drifted"
    missing = [n for n in named if not (MIRROR / n).is_file()]
    assert not missing, (
        f"settings.json wires {missing}, which the mirror does not carry. Run "
        "`scripts/agent_estate_sync.py --capture`, or drop the hook."
    )


def test_every_repo_script_a_hook_names_exists():
    """A hook may also run a script out of THIS repo, and those go missing too.

    Measured 2026-08-20 and recorded as task #101: a SessionStart hook ran
    `git show origin/main:scripts/checkout_currency.py` when that path was not on origin/main, so
    the hook failed at every single session start and nothing reported it.
    """
    named = sorted({m for c in _hook_commands()
                    for m in re.findall(r"(?<!\.claude/)\bscripts/([\w.-]+\.py)\b", c)})
    missing = [n for n in named if not (REPO_ROOT / "scripts" / n).is_file()]
    assert not missing, f"a hook runs scripts/{missing}, which this repo does not carry"


def test_no_mirrored_file_carries_a_secret_shape():
    """Reads the bytes of every mirrored file. Reports the file and the SHAPE, never the value."""
    found = [(p.relative_to(REPO_ROOT), shape)
             for p in sync.mirrored_files() if (shape := sync.secret_shape(p))]
    assert not found, f"credential-shaped strings in the mirror: {found}"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("sk-ant-api03-" + "A" * 40, "Anthropic key"),
        ("token = 'ghp_" + "b" * 36 + "'", "GitHub token"),
        ("AKIA" + "C" * 16, "AWS access key id"),
        ("FLY_API_TOKEN=FlyV1 fm2_abc", "Fly token"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----", "PEM private key"),
        ("xoxb-1234567890-abcdef", "Slack token"),
        ("# a normal comment about sk- prefixes and AKIA naming", None),
        ("import os\nHOME = os.path.expanduser('~')\n", None),
    ],
)
def test_the_secret_scanner_can_fail(tmp_path: Path, body: str, expected: str | None):
    """A scanner that never matches passes every file. These fixtures prove it can say no."""
    f = tmp_path / "candidate.py"
    f.write_text(body)
    assert sync.secret_shape(f) == expected


def test_capture_refuses_to_write_a_file_carrying_a_credential(tmp_path, monkeypatch):
    """The scanner being correct is not the same as the scanner being WIRED."""
    estate = tmp_path / "estate"
    (estate / "scripts").mkdir(parents=True)
    (estate / "CLAUDE.md").write_text("# laws\n")
    (estate / "scripts" / "leaky.py").write_text("TOKEN = 'ghp_" + "d" * 36 + "'\n")
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    monkeypatch.setenv("CLAUDE_HOME", str(estate))
    monkeypatch.setattr(sync, "MIRROR", mirror)

    assert sync.capture() == 2, "capture accepted a file carrying a GitHub token"
    assert list(mirror.iterdir()) == [], (
        "capture wrote files despite refusing: a partial write leaves the clean files tracked and "
        "the refusal invisible on the next run"
    )


def test_capture_then_check_round_trips(tmp_path, monkeypatch):
    """Capture must produce a state that check calls clean, or the gate cries wolf forever."""
    estate = tmp_path / "estate"
    (estate / "scripts").mkdir(parents=True)
    (estate / "skills" / "s").mkdir(parents=True)
    (estate / "CLAUDE.md").write_text("# laws\n")
    (estate / "settings.json").write_text('{"hooks": {}}\n')
    (estate / "scripts" / "guard.py").write_text("print('no')\n")
    (estate / "scripts" / "guard.py.bak").write_text("print('old')\n")
    (estate / "skills" / "s" / "SKILL.md").write_text("# skill\n")
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    monkeypatch.setenv("CLAUDE_HOME", str(estate))
    monkeypatch.setattr(sync, "MIRROR", mirror)

    assert sync.capture() == 0
    assert sync.check() == 0
    assert (mirror / "CLAUDE.global.md").is_file(), "the laws were not renamed on the way in"
    assert not (mirror / "CLAUDE.md").exists()
    assert (mirror / "guard.py").is_file(), "scripts/ must land flat, as the symlinks assume"
    assert not (mirror / "guard.py.bak").exists(), "a .bak snapshot is not the rule that runs"
    assert (mirror / "skills" / "s" / "SKILL.md").is_file()

    (estate / "scripts" / "guard.py").write_text("print('changed')\n")
    assert sync.check() == 1, "check passed while the live copy and the mirror differed"


def test_check_is_quiet_where_there_is_no_estate(tmp_path, monkeypatch):
    """It runs on CI and in the container, where `~/.claude` does not exist. That is not drift."""
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "absent"))
    assert sync.check() == 0


def test_the_plan_refuses_two_sources_for_one_destination(tmp_path, monkeypatch):
    """Silent overwrite is the failure mode a mirror cannot detect in itself.

    If two allow-list rows resolve to one mirrored path, every capture writes whichever came
    second and `--check` reports a clean estate while a file is being lost on every run.
    """
    estate = tmp_path / "estate"
    (estate / "a").mkdir(parents=True)
    (estate / "b").mkdir(parents=True)
    (estate / "a" / "same.py").write_text("1\n")
    (estate / "b" / "same.py").write_text("2\n")
    monkeypatch.setenv("CLAUDE_HOME", str(estate))
    monkeypatch.setattr(sync, "PAIRS", (("a", "."), ("b", ".")))
    with pytest.raises(ValueError, match="two sources map to"):
        sync.plan()


def _tracked_under_mirror() -> list[Path]:
    """What git carries under the mirror, which is what "reached the mirror" means.

    This walked the DISK, and the disk holds things git was never asked to keep: importing any
    guard module writes `scripts/claude_guards/__pycache__/`, and `.gitignore:2` already excludes
    it, so it can never be tracked and never reach another machine. The walk failed anyway, on
    any box where a guard had been imported once -- a red test that named a file nobody added and
    no commit could remove. Grade the index, which is the thing the claim is about.
    """
    git = require_tool("git")
    out = subprocess.run(
        [git, "ls-files", "-z", "--", str(MIRROR.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=60,
    )
    return [Path(entry) for entry in out.stdout.split("\0") if entry]


def test_nothing_the_allow_list_excludes_reached_the_mirror():
    """The allow-list only ever fails by leaving something out -- unless somebody hand-copies."""
    tracked = _tracked_under_mirror()
    assert tracked, "git tracks nothing under the mirror; this test would pass on an empty repo"
    banned = {
        ".credentials.json": "a live OAuth token",
        "history.jsonl": "every command typed at this machine",
    }
    for name, why in banned.items():
        hits = [p for p in tracked if p.name == name]
        assert not hits, f"{hits} must never be tracked: {why}"
    for pattern, why in (("*.bak*", "a snapshot, not the rule that runs"),
                         ("__pycache__", "build output"),
                         ("*.jsonl", "transcript or telemetry data, not a rule")):
        hits = [p for p in tracked if any(fnmatch(part, pattern) for part in p.parts)]
        assert not hits, f"{hits} should not be tracked: {why}"
