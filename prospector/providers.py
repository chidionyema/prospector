"""Config-declared model providers: `config.yaml providers:` instead of a source edit.

WHY THIS MODULE EXISTS. Adding one model provider took ~85 hardcoded edits across 12 files and
a new branch in the `if kind ==` switch at `operator._build_operator`. Nearly every one of those
edits was the same shape — an OpenAI-compatible `/chat/completions` endpoint with a bearer key —
so the work was typing, not design, and each retyping was a chance to get one of the 85 wrong.
A provider that speaks that shape is now a block in `config.yaml`, parsed here and built by
`operator.OpenAICompatibleOperator`.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. Declaring a provider does NOT make it trusted. Trust
is `operator.moat_primary()` and nothing else: a declared provider that rules a verdict without
being named in `moat_primary:` is stamped `provisional`, never publishes on PASS, and is
re-vetted. Adding a brain to the estate and promoting it to rule the £49 deliverable stay two
separate decisions, because they carry two different risks.

It imports NOTHING from `prospector.operator` at module level — operator imports this, so a
module-level import back would be a cycle. Anything needed from there is imported inside a
function.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

#: Tier names that were deleted along with their adapters. `_build_operator` raises an explicit
#: ValueError for each, naming the date and the reason, so a stale config fails loudly instead of
#: silently building a chain one brain shorter than it reads. A `providers:` block must not be
#: able to bring one back under the same name: the resurrected tier would answer to the old name
#: with none of the old behaviour, and every config, plist and dossier that names it would look
#: correct while meaning something different.
REMOVED_TIERS: tuple[str, ...] = ("claude", "cursor_cli", "standardcompute")

#: A tier name has to be usable as a config key, a health-mark key and a dossier `provider`
#: field, so it is restricted to the shape every built-in name already has.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: An env var name, i.e. the NAME of the key, never the key itself. Nothing in this file, in
#: `config.yaml`, or in a dossier ever holds the secret; the adapter reads it from the process
#: environment at construction.
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class DeclaredProvider:
    """One provider declared in `config.yaml providers:`.

    Frozen because `_build_operator` may run on several threads and a mutable row shared by
    every construction is a race waiting for a reason to matter.
    """
    name: str
    base_url: str
    api_key_env: str
    model: str
    #: The cheap/structured model, used when `_build_operator` is called with `fast=True`.
    #: Blank => the full model serves both, which is what a single-model provider wants.
    fast_model: str = ""
    max_tokens: int = 8192
    timeout_s: int = 300


def _positive_int(row: dict, key: str, name: str, default: int) -> int:
    """Read an optional positive-int field, refusing anything that would wedge a call.

    A `timeout_s` of 0 or a negative `max_tokens` does not fail at declaration — it fails
    mid-run, on a live candidate, as a provider error that reads like the provider's fault.
    """
    if key not in row or row[key] is None:
        return default
    value = row[key]
    # bool is an int subclass, and `timeout_s: true` is a typo, not a duration.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"providers.{name}.{key} must be a positive integer, got {value!r}. "
            "A non-positive value does not fail here; it fails mid-run as a provider error "
            "that reads like the provider's fault.")
    return value


def parse_declared(raw: dict | None) -> dict[str, DeclaredProvider]:
    """Validate the `providers:` block into {name: DeclaredProvider}. `{}` when absent.

    Every rejection raises here, at load, rather than being dropped: a provider that is
    declared, saved and displayed but never built is the exact failure this block exists to
    end, and it is invisible from the config file.
    """
    from .tiers import BUILDABLE_TIERS  # cheap, imports nothing

    # `providers:` absent, or present with no value, is the normal case and means "none".
    # Anything else that is not a mapping is a shape error and is refused: a list of provider
    # blocks has no names, and the name is the whole point.
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"config `providers:` must be a mapping of provider name -> settings, got "
            f"{type(raw).__name__}. A list has no names, and the name is what `operator:` and "
            "`moat_primary:` refer to.")

    out: dict[str, DeclaredProvider] = {}
    for raw_name, row in raw.items():
        name = str(raw_name).strip()
        if not isinstance(row, dict):
            raise ValueError(
                f"providers.{name} must be a mapping of settings (base_url, api_key_env, "
                f"model, ...), got {type(row).__name__}.")
        if not _NAME_RE.match(name):
            raise ValueError(
                f"providers: invalid provider name {raw_name!r}. Expected lowercase letters, "
                "digits and underscores, starting with a letter (the shape every built-in tier "
                "name already has). The name is used as a config key, a health-mark key and the "
                "`provider` field of every dossier it rules.")
        if name in BUILDABLE_TIERS:
            raise ValueError(
                f"providers.{name} shadows the built-in tier {name!r}. The declaration would "
                "win silently — the same config line would mean a different brain than it did "
                "yesterday, with no error anywhere — so it is refused. Pick another name.")
        if name in REMOVED_TIERS:
            raise ValueError(
                f"providers.{name} resurrects a REMOVED tier. `_build_operator` raises a "
                "deliberate error for that name, giving the date it was removed and why; a "
                "config block must not undo it. The revived tier would answer to the old name "
                "with none of the old behaviour. Pick another name.")

        base_url = str(row.get("base_url") or "").strip()
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(
                f"providers.{name}.base_url must be an http:// or https:// URL, got "
                f"{row.get('base_url')!r}. It is the OpenAI-compatible root — the adapter "
                "appends `/chat/completions` to it.")

        api_key_env = str(row.get("api_key_env") or "").strip()
        if not _ENV_RE.match(api_key_env):
            raise ValueError(
                f"providers.{name}.api_key_env must be the NAME of an environment variable "
                f"(e.g. ACME_API_KEY), got {row.get('api_key_env')!r}. Keys are read from the "
                "environment; config.yaml is committed and must never hold the secret itself.")

        model = str(row.get("model") or "").strip()
        if not model:
            raise ValueError(
                f"providers.{name}.model is required. There is no house default for a provider "
                "the engine has never met, and an empty model reaches the endpoint as a request "
                "for nothing.")

        out[name] = DeclaredProvider(
            name=name,
            base_url=base_url.rstrip("/"),
            api_key_env=api_key_env,
            model=model,
            fast_model=str(row.get("fast_model") or "").strip(),
            max_tokens=_positive_int(row, "max_tokens", name, 8192),
            timeout_s=_positive_int(row, "timeout_s", name, 300),
        )
    return out


def buildable_tiers(declared: dict | None = None) -> tuple[str, ...]:
    """Every tier name `_build_operator` can construct: the built-ins plus declared names.

    Read this instead of `tiers.BUILDABLE_TIERS` anywhere a NAME is being validated. A
    validator that knows only the built-ins refuses a valid config, which is the worse of the
    two failures: the engine will not start at all, and the message blames the config.
    """
    from .tiers import BUILDABLE_TIERS

    return tuple(BUILDABLE_TIERS) + tuple(sorted(declared or {}))


# The declared block, installed process-wide by `config.load_config`, for the validators that
# hold no Config. `operator._coerce_moat_primary` is called with a bare list of names — from
# `$PROSPECTOR_MOAT_PRIMARY` there is no Config anywhere in the call — and it has to be able to
# tell a declared name from a typo. Same pattern, and the same reason, as `set_moat_primary`
# and `set_minimax_concurrency`: written on EVERY load, so an absent key resets it and one
# process loading a fixture config cannot poison the next load.
_DECLARED: dict[str, DeclaredProvider] = {}
_DECLARED_LOCK = threading.Lock()


def set_declared(declared: dict[str, DeclaredProvider] | None) -> dict[str, DeclaredProvider]:
    """Install the declared block process-wide. Called by `config.load_config`."""
    global _DECLARED
    with _DECLARED_LOCK:
        _DECLARED = dict(declared or {})
        return _DECLARED


def installed_declared() -> dict[str, DeclaredProvider]:
    """The declared block installed by the last `load_config`. `{}` before any load."""
    with _DECLARED_LOCK:
        return dict(_DECLARED)
