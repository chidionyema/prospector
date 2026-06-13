"""Load the verbatim prompt files (Part 10). Prompts are the IP and live as plain
.md files in prompts/ so they can be tuned without touching code (golden-set in CI)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """name without extension, e.g. 'verdict'. Splits SYSTEM:/USER: sections."""
    return (PROMPTS_DIR / f"{name}.md").read_text()


def split_system_user(raw: str) -> tuple[str, str]:
    """Prompt files are written as 'SYSTEM: ...\\nUSER: ...'. Returns (system, user)."""
    sys_part, _, user_part = raw.partition("USER:")
    system = sys_part.replace("SYSTEM:", "", 1).strip()
    user = user_part.strip()
    return system, user


def render(name: str, **kwargs) -> tuple[str, str]:
    """Load a prompt and substitute {placeholders} in the USER section."""
    system, user = split_system_user(load_prompt(name))
    for k, v in kwargs.items():
        user = user.replace("{" + k + "}", str(v))
    return system, user
