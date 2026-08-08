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
MARKET_PROMPTS_DIR = PROMPTS_DIR / "markets"
STYLE_PROMPTS_DIR = PROMPTS_DIR / "style"

# House voice, held in one place so tone is tuned in one file rather than restated in
# six prompts that then drift apart. `voice` is the buyer-facing spine (generation,
# artifacts, listing copy); `rationale` is its moat-safe sibling — it governs the
# WORDING of a verdict line and is explicit that the ruling itself is untouched.
STYLE_KEYS = {"style_guide": "voice", "rationale_style": "rationale"}

# The market whose flavour the base prompts were originally written in. Used ONLY when a
# config predates Epic D and defines no `markets:` block, so such a config still renders
# exactly the prompts it always did. Any config with markets resolves through its own
# default instead.
_BASELINE_MARKET = "uk"

# Market variables the MOAT may see. Deliberately tiny: the verdict and adversarial
# passes rule from retrieved passages only, so they get the jurisdiction's NAME (to
# disambiguate "notary bond" in Texas from the UK one) and the relevance-judgement
# precedents — never the evidence-landscape prose, which would invite ruling from prior
# knowledge about the market. See specs/multi-market-dimension.md DD6.
MOAT_MARKET_KEYS = ("market_scope", "market_verdict_exemplars")

# Market variables for the non-moat stages (generation, query-gen, prescreen, scoring,
# artifact copy). These may carry rich framing: none of them rules a verdict.
OPEN_MARKET_KEYS = ("market_context", "market_label", "currency_hint",
                    "market_exemplars", "market_batched_exemplars")

ALL_MARKET_KEYS = MOAT_MARKET_KEYS + OPEN_MARKET_KEYS


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


@lru_cache(maxsize=None)
def _fragment(chain: tuple[str, ...], name: str) -> str:
    """First existing `prompts/markets/<code>/<name>.md` along `chain`, else ''.

    Inheritance is why a market can open with one config entry: "us-tx" falls back to
    "us", and a market that never writes its own verdict precedents inherits the default
    market's — those precedents teach RELEVANCE JUDGEMENT, not market facts, so sharing
    them is correct rather than merely convenient.
    """
    for code in chain:
        p = MARKET_PROMPTS_DIR / code / f"{name}.md"
        if p.exists():
            return p.read_text().strip()
    return ""


@lru_cache(maxsize=None)
def _style_text(fname: str) -> str:
    p = STYLE_PROMPTS_DIR / f"{fname}.md"
    return p.read_text().strip() if p.exists() else ""


def style_kwargs() -> dict[str, str]:
    """The house-voice variables, injected into every render.

    Auto-injected rather than passed by each caller on purpose: the market work proved
    that a placeholder depending on call-site discipline eventually ships to a model
    verbatim. These depend on nothing but the files, so there is no reason for a call
    site to be involved at all.
    """
    return {key: _style_text(fname) for key, fname in STYLE_KEYS.items()}


def _fragment_chain(cfg) -> tuple[str, ...]:
    """Market codes to search for prompt fragments, nearest-first."""
    markets = getattr(cfg, "markets", None)
    if not markets:
        return (_BASELINE_MARKET,)
    code = cfg.resolve_market(getattr(cfg, "active_market", "") or None)
    if not code:
        return (_BASELINE_MARKET,)
    parts = code.split("-")
    chain = ["-".join(parts[:i]) for i in range(len(parts), 0, -1)]
    default = cfg.default_market
    if default and default not in chain:
        chain.append(default)
    return tuple(chain)


def market_kwargs(cfg, *, for_moat: bool = False, market: str = "") -> dict[str, str]:
    """The market variables a render site must pass.

    `for_moat=True` returns only MOAT_MARKET_KEYS — the restricted set for the verdict
    and adversarial prompts. Passing the rich set to those prompts would hand the moat
    substantive knowledge about the market, which is exactly the prior-knowledge leak
    that verdict-from-retrieval-only forbids.

    `market` names the market these variables describe. Default "" keeps the previous
    behaviour, the config's ACTIVE market. It exists because generation and linting read
    the market from two different places: generation took it from config (one global
    value per run) while `lint_pack` grades against `candidate.market` (bridge.py:842),
    per pack. With the daemon's active market on `uk`, every US pack was told
    `currency_hint = GBP` and duly wrote `£` into a `us` pack, which the linter then
    refused to list. Three packs failed this way on 2026-08-08 (7a6c07535fd8a998,
    8ce5270ade208070, 8d5e24fbe6c1f5d3). A per-pack override is the whole fix: the
    generator and the grader now read the same field.
    """
    chain = _fragment_chain(cfg)
    block = (cfg.market_config(market or None)
             if getattr(cfg, "markets", None) else {})
    label = str(block.get("label", "") or "")

    # market_scope is derived from the LABEL alone — a name, never a fact. That makes it
    # structurally impossible for the moat's market variable to carry market claims.
    scope = f"Jurisdiction under evaluation: {label}." if label else ""

    moat = {
        "market_scope": scope,
        "market_verdict_exemplars": _fragment(chain, "verdict_exemplars"),
    }
    if for_moat:
        return moat

    # require_subdivision (spec D2.5): a bare parent like "us" with the flag set must
    # still push state/country naming into generation framing. The moat never sees this
    # — only market_scope reaches verdict/adversarial.
    context = str(block.get("market_context", "") or "").strip()
    code = str(block.get("code", "") or "")
    if block.get("require_subdivision") and code and "-" not in code:
        reminder = (
            f"SUBDIVISION REQUIRED: opportunities in {label or code} must name a "
            f"specific sub-jurisdiction (e.g. {code}-xx). Do not leave the claim at "
            f"the bare parent market."
        )
        context = f"{context}\n\n{reminder}".strip() if context else reminder

    return {
        **moat,
        "market_context": context,
        "market_label": label,
        "currency_hint": str(block.get("currency_hint", "") or ""),
        "market_exemplars": _fragment(chain, "query_gen_exemplars"),
        "market_batched_exemplars": _fragment(chain, "query_gen_batched_exemplars"),
    }


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
    # House voice goes in first so an explicit caller value still wins.
    for k, v in {**style_kwargs(), **kwargs}.items():
        system = system.replace("{" + k + "}", str(v))
        user = user.replace("{" + k + "}", str(v))

    # Substitution is a blind str.replace, so a {market_*} placeholder whose call site
    # forgot the kwarg is shipped to the model VERBATIM — a silent quality regression
    # with no error anywhere. Shout about it instead.
    if "{market_" in system or "{market_" in user:
        from .telemetry import logger
        logger.error(
            f"prompt {name!r} rendered with an unsubstituted market placeholder — the "
            f"literal token will reach the model. Pass prompts.market_kwargs(cfg).",
            extra={"prompt": name})

    return system, user
