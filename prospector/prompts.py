"""Load the verbatim prompt files (Part 10). Prompts are the IP and live as plain
.md files in prompts/ so they can be tuned without touching code (golden-set in CI).

FIX #5 prompt split: generate.md is split into:
  - generate_system.md: static system-level instructions (lens taxonomy, wedge
    taxonomy, structural traps, output format). Loaded once and cached.
  - generate.md: user-side dynamic template (signal, sector, form, k, avoid list).
    Re-evaluated per generation call with variable substitution.
This cuts generate prompt tokens by ~70% (from ~2,500 to ~600 per call) and enables
the system instructions to be cached at the model level.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """name without extension, e.g. 'verdict'. Splits SYSTEM:/USER: sections."""
    return (PROMPTS_DIR / f"{name}.md").read_text()


@lru_cache(maxsize=None)
def _load_system_prompt(name: str) -> str:
    """Load a _system.md file for the static system portion of a split prompt."""
    return (PROMPTS_DIR / f"{name}_system.md").read_text()


def split_system_user(raw: str) -> tuple[str, str]:
    """Prompt files are written as 'SYSTEM: ...\\nUSER: ...'. Returns (system, user)."""
    sys_part, _, user_part = raw.partition("USER:")
    system = sys_part.replace("SYSTEM:", "", 1).strip()
    user = user_part.strip()
    return system, user


def render(name: str, **kwargs) -> tuple[str, str]:
    """Load a prompt and substitute {placeholders} in the USER section.

    FIX #5: if a {name}_system.md file exists, its content is prepended to the system
    section.  This allows the static taxonomy/rules to live in a cached file while
    the user template is re-evaluated per-call with variable substitution.
    """
    # Check for a split prompt: load the system portion from {name}_system.md if it exists.
    try:
        system_static = _load_system_prompt(name)
    except FileNotFoundError:
        system_static = ""

    # Load the normal {name}.md and split its SYSTEM:/USER: sections.
    raw = load_prompt(name)
    system_dynamic, user = split_system_user(raw)

    # Merge: static system (from _system.md) + dynamic system (from .md SYSTEM: block).
    system = "\n\n".join(filter(None, [system_static, system_dynamic]))

    # Substitute placeholders in BOTH sections.  The user section always varies per-call
    # (signal, form, lens, k).  The system section also varies when dynamic variables
    # (e.g. audience_persona / audience_description) are threaded through.
    for k, v in kwargs.items():
        system = system.replace("{" + k + "}", str(v))
        user = user.replace("{" + k + "}", str(v))

    return system, user
