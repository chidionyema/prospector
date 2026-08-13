"""The ONE definition of the child environment for the headless `claude` CLI.

Why this is a module and not an inline dict comprehension
---------------------------------------------------------
The `claude` binary picks its credentials by PRECEDENCE, and the precedence is not ours to
set: when `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) is present in the process
environment it OUTRANKS the claude.ai subscription login and the CLI bills that key. Ours has
a zero balance, so the call exits 1 printing "Credit balance is too low" on STDOUT.

Measured 2026-08-07 on this machine, same binary, same second:

    $ claude -p "reply with exactly: OK"
    ⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth source is
      set and takes precedence over your claude.ai login
    Credit balance is too low

    $ env -u ANTHROPIC_API_KEY claude -p "reply with exactly: OK"
    OK

The key is VALID and BROKE, which is the trap: `GET /v1/models` answers HTTP 200 (the key
authenticates) while `POST /v1/messages` answers `invalid_request_error: "Your credit balance
is too low"`. A reachability probe therefore PASSES on a key that cannot serve one token —
the same failure mode recorded in memory `models-probe-proves-the-key-not-the-balance.md`.

Where the ambient key comes from (root cause, 2026-08-07)
---------------------------------------------------------
`~/.zshrc:54` sources `~/.config/llm/secrets.sh`, whose line 9 was `export
ANTHROPIC_API_KEY=...`. Grepping the rc files for the VARIABLE name finds nothing — the rc
file names the FILE, not the variable — which is why this survived several audits. The value
is byte-identical in three places (sha256[:12] = dd2afc9b2cf5): `secrets.sh`, the repo `.env`,
and the live process environment.

ANTHROPIC_BASE_URL is stripped too, and that one is NOT about billing
---------------------------------------------------------------------
`ANTHROPIC_BASE_URL` repoints the CLI at a different inference endpoint. If it ever leaked
into the engine's environment, `claude -p` would be answered by whatever sits at that URL
while `MOAT_PRIMARY` still counts the result as trusted — a publishable
verdict served by an untrusted brain. That is precisely the fence `MOAT_PRIMARY` exists to
hold, so the strip is a MOAT-INTEGRITY control, not a cost control, and it must not be
removed on the grounds that "the key is dead anyway".

This is a real configuration in this estate, not a hypothetical: the pi-bridge executor works
by replacing `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` for a whole process so that the
"Claude" brain is actually MiniMax (memory: `pi-bridge-headless-executor.md`). That is fine
for an executor and fatal for a moat.
"""
from __future__ import annotations

import os
from typing import Iterable, Mapping, Optional

# Vars that let something other than the claude.ai subscription answer a `claude -p` call.
# Ordered by what they hijack: credentials, credentials, endpoint.
#
# KEEP THIS THE ONLY DEFINITION. `tests/unit/test_cli_auth.py` asserts no other module in
# prospector/ inlines the same tuple, because a second copy is how one of them drifts.
SUBSCRIPTION_HIJACK_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
)


def subscription_env(base: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """The child environment for any spawn of the `claude` binary.

    A copy of `base` (default: the live environment) with every var in
    SUBSCRIPTION_HIJACK_VARS removed, so the CLI falls through to the claude.ai
    subscription (OAuth, stored in ~/.claude and cwd-independent).

    Everything else is preserved verbatim — PATH, HOME and the other providers' keys are all
    load-bearing for the child, and this is deliberately a DENYLIST, not an allowlist: an
    allowlist here silently breaks the CLI the day it needs a var nobody enumerated.
    """
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k not in SUBSCRIPTION_HIJACK_VARS}


def ambient_hijackers(base: Optional[Mapping[str, str]] = None) -> list[str]:
    """Which hijack vars are set in `base` (default: the live environment).

    Empty list => a bare `claude -p` in this environment authenticates on the subscription.
    Non-empty => a bare `claude -p` is billed to (or routed by) something else. Callers that
    spawn through `subscription_env()` are immune either way; this exists so a PROBE can
    report the ambient state instead of a document asserting it.
    """
    src = os.environ if base is None else base
    return [k for k in SUBSCRIPTION_HIJACK_VARS if src.get(k)]


def describe_ambient_auth(base: Optional[Mapping[str, str]] = None) -> str:
    """One human line for probes and diagnostics. No secrets in the output."""
    found = ambient_hijackers(base)
    if not found:
        return "auth: OK - no hijack vars set; `claude -p` uses the claude.ai subscription"
    return ("auth: HIJACKED - " + ", ".join(found) +
            " set in this environment; a bare `claude -p` will NOT use the subscription "
            "(engine spawns are immune: prospector.cli_auth.subscription_env)")


def _main(argv: Optional[Iterable[str]] = None) -> int:
    """`python -m prospector.cli_auth` — print the ambient verdict, exit 1 if hijacked.

    State is a probe, not a paragraph: this is the command that answers "will the CLI use the
    subscription?", so no doc has to claim it.
    """
    print(describe_ambient_auth())
    return 1 if ambient_hijackers() else 0


if __name__ == "__main__":  # pragma: no cover - trivial CLI shim
    raise SystemExit(_main())
