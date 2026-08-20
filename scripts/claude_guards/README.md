# The agent estate, mirrored

Every file in this directory except this README is a **copy of a file under `~/.claude`**. It is
here so that the rules and guards this estate is worked by survive a lost laptop, and so a new
machine can be brought up with them rather than without them.

Founder, 2026-08-20: *"~/.claude/ is not a git repo, easy fix is to copy into prospector"*.

| Here | Live |
|---|---|
| `CLAUDE.global.md` | `~/.claude/CLAUDE.md` — the seven laws, and how to work in any repo |
| `settings.json` | `~/.claude/settings.json` — wires 19 hook commands and the status line |
| `*.py`, `*.sh`, `*.json` | `~/.claude/scripts/` — the guards, flat, same filenames |
| `skills/` | `~/.claude/skills/` |

`CLAUDE.md` is renamed to `CLAUDE.global.md` on the way in, and must stay renamed: Claude Code
reads any file called `CLAUDE.md` as instructions scoped to its directory, so a verbatim copy of
the global laws would start governing the repo that is only storing them.

## The three verbs

```bash
scripts/agent_estate_sync.py --check      # compare; exit 1 and say which side has the change
scripts/agent_estate_sync.py --capture    # ~/.claude -> here, after a guard changes on this machine
scripts/agent_estate_sync.py --install    # here -> ~/.claude, to bootstrap a bare machine
```

`--check` exits 0 when there is no `~/.claude` at all, so it is safe on CI and inside a container.
`--install` refuses to overwrite a file that differs unless given `--force`; it names what it kept.

## Two of these files are symlinked, not copied

`~/.claude/scripts/idle-guard.py` and `wire-idle-guard.sh` are **symlinks into this directory** —
they were written here first. `docs/ESTATE_MAP.md` §11 warns not to "repair" those symlinks during
a disk recovery, because replacing one with a stub permanently disables the guard. A symlink reads
as its target's bytes, so `--capture` sees them as already identical and writes nothing.

Do not rename this directory. Both symlinks name it by absolute path.

## What is deliberately not here

`~/.claude` is 7.5 GB. This mirror is 784 KB, because the allow-list in `agent_estate_sync.py`
admits four paths and nothing else. Never mirrored: `.credentials.json` (a live OAuth token),
`projects/` (5.9 GB of transcripts, memory and checkpoints), `telemetry/`, `directives/` (the
founder-message archive, which `scripts/backup_agent_estate.py` found a real GitHub token inside),
`history.jsonl`, `paste-cache/`, `shell-snapshots/`, `plugins/` and every `.bak` file.

Backups of the parts that are *not* here are a different job, and it already exists:
`scripts/backup_agent_estate.py` packs them into a redacted offsite archive.

## Ruff does not lint this directory

`ruff.toml` excludes it, with the reason stated there. The mirror's only guarantee is that the
file here is byte-for-byte the file the hook runs, and that collapses if a formatter rewrites one
side of the comparison.
