"""A POPDD receipt must never be tracked in git, because its signing key never is.

Measured 2026-08-20. Two receipt files entered the repo in `9f043e68` (2026-06-18):
`.lux/receipts/2026-06-17.jsonl` and `.lux/receipts/prospector-test-0.jsonl`. The key that signed
them, `.lux/keys/agent.pem`, is ignored by `.gitignore:92` (`.lux/`) and stays on the machine that
made it. `HmacSigner.load_or_create_key` GENERATES a fresh key in any checkout that lacks one, so
those two files cannot verify in any clone, ever.

That alone would be harmless. The damage is that `PopddAgent.__init__` seeds each new day's chain
from `sorted(receipt_dir.glob("*.jsonl"))[-1]` when today's file does not exist yet, and
`prospector-test-0.jsonl` sorts after every `YYYY-MM-DD.jsonl` name. So every checkout copied those
foreign-signed records into today's file as sequence 0 and 1, `verify_chain()` returned
`signature invalid at 0`, and `scripts/popdd_verify.py:766` (`return 0 if verify["valid"] and ok
else 1`) blocked EVERY commit in EVERY tree — with a green suite printed directly above the block.

The class is: a signed artefact committed without the secret that signs it. It is not detectable by
reading either file; it only shows up as a gate failure that names something else.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    """Run git at the repo root with the caller's GIT_* stripped.

    The suite runs under the pre-commit hook, and a hook exports GIT_DIR, GIT_WORK_TREE and
    GIT_INDEX_FILE into everything it starts. `cwd=` does not override them, so without this the
    listing below would describe whichever repository the environment names.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(
        ("git", *args), cwd=REPO, capture_output=True, text=True, timeout=30, env=env
    )
    return out.stdout.strip() if out.returncode == 0 else ""


def test_no_popdd_receipt_is_tracked() -> None:
    tracked = [line for line in _git("ls-files", ".lux/receipts").splitlines() if line.strip()]
    assert tracked == [], (
        "these POPDD receipts are tracked in git, but their signing key (.lux/keys/agent.pem) is "
        f"not and never can be, so they fail verification in every clone: {tracked}. "
        "Untrack them: git rm --cached " + " ".join(tracked)
    )


def test_the_receipt_directory_is_ignored() -> None:
    """The ignore rule is what keeps the next receipt out. Without it the guard above is a
    one-time cleanup rather than a standing refusal."""
    rc = subprocess.run(
        ("git", "check-ignore", "-q", ".lux/receipts/2026-01-01.jsonl"),
        cwd=REPO,
        capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    ).returncode
    assert rc == 0, ".lux/receipts/ is no longer gitignored; a new receipt can be committed again"
