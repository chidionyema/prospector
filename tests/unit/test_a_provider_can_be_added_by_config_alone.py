"""Adding a model provider must be a config.yaml block, and a declared brain must stay untrusted.

WHAT THIS FILE EXISTS TO STOP. Until this change, adding one model provider to the engine took
roughly 85 hardcoded edits across 12 files: an adapter class, a `_build_operator` branch, a name
in `prospector/tiers.py::BUILDABLE_TIERS`, a `model_defaults` field, console knobs, health-file
keys, and a test for each. The cost of that is not the typing. It is that every one of those
edits is a place the next provider can be added HALF — a tier the config accepts and the factory
cannot build, or a factory branch no UI offers — and both failures read as "unknown operator" at
2am rather than as a missing line.

`prospector/providers.py` replaces the 85 edits with one declaration block. These tests are what
stops that regressing, in three directions:

  1. THE PARSER IS THE GATE. A declared provider is operator-supplied text that becomes a live
     HTTP client. Every rejection in `parse_declared` is tested here, one case per rule, and each
     one must NAME the offending value — an error that says "invalid providers block" sends the
     operator to read 40 lines of YAML instead of one.
  2. A REMOVED TIER STAYS REMOVED. `claude`, `cursor_cli` and `standardcompute` were each deleted
     with their adapter and each left an explicit ValueError in `_build_operator` carrying the
     date and the reason. A config-declared block must not become the back door that resurrects
     one silently under the same name.
  3. THE TRUST FENCE HOLDS. `test_a_declared_provider_is_never_trusted_to_rule_finally` is the
     most important test in this file. A declared provider is a stranger: an operator typed a URL
     into a YAML file. If it silently landed inside `moat_primary()` it could rule a verdict
     FINALLY, and a PASS on an unverified verdict publishes a £49 deliverable. The fence is
     `operator.is_provisional_provider`, and it must answer True for any name that is not in
     `moat_primary()`.

Nothing here performs a network call, and one test proves that by breaking the socket.
"""
from __future__ import annotations

import urllib.request

import pytest

from prospector import operator as op
from prospector import providers
from prospector.errors import ProviderExhaustedError
from prospector.tiers import BUILDABLE_TIERS

# A name that is not a built-in, not removed, and shaped legally. Used by nearly every test here.
DECLARED_NAME = "acme_llm"
FULL_MODEL = "acme-full-v1"
FAST_MODEL = "acme-fast-v1"
KEY_ENV = "ACME_LLM_API_KEY"


#: Sentinel for "this key is ABSENT from the row", which is a different case from "this key is
#: blank" and has its own rejection rule.
_ABSENT = object()


def _row(**over) -> dict:
    """One legal declaration row, with the field under test overridden."""
    row = {
        "base_url": "https://api.acme.example/v1",
        "api_key_env": KEY_ENV,
        "model": FULL_MODEL,
    }
    row.update(over)
    return {k: v for k, v in row.items() if v is not _ABSENT}


def _block(name: str = DECLARED_NAME, **over) -> dict:
    return {name: _row(**over)}


class _FakeConfig:
    """The smallest object `_build_operator` reads.

    Mirrors `tests/unit/test_component_models.py`'s idiom of driving the factory with a config
    rather than a mock, but built by hand instead of `load_config()`: this file must not depend
    on whether the live `config.yaml` happens to declare a provider block today. The three
    attributes are exactly what the factory touches — `model_defaults` (read via `getattr`),
    `component_models` (read by `operator.component_pin`), and `providers` (the new block).
    """

    def __init__(self, providers_block: dict | None = None):
        self.providers = providers_block or {}
        self.model_defaults = None
        self.component_models = {}


# --------------------------------------------------------------------------- parsing: the happy path


def test_a_minimal_declared_block_parses_and_the_defaults_land():
    """If a default drifts, every provider declared without that field silently changes behaviour.

    `max_tokens` and `timeout_s` are the two that bite: a truncated completion and a hung call
    both look like a bad model rather than a changed default.
    """
    parsed = providers.parse_declared(_block())
    assert set(parsed) == {DECLARED_NAME}
    p = parsed[DECLARED_NAME]
    assert p.name == DECLARED_NAME
    assert p.base_url == "https://api.acme.example/v1"
    assert p.api_key_env == KEY_ENV
    assert p.model == FULL_MODEL
    assert p.fast_model == ""
    assert p.max_tokens == 8192
    assert p.timeout_s == 300


def test_an_absent_provider_block_is_an_empty_mapping_and_not_an_error():
    """Every existing config.yaml in the estate has no `providers:` key.

    If the parser raised on `None` this change would be a migration, not a feature: every
    checkout, plist and deployed image would fail at startup on a block it never had.
    """
    assert providers.parse_declared(None) == {}
    assert providers.parse_declared({}) == {}


def test_declared_fields_override_every_default():
    parsed = providers.parse_declared(
        _block(fast_model=FAST_MODEL, max_tokens=512, timeout_s=30))
    p = parsed[DECLARED_NAME]
    assert (p.fast_model, p.max_tokens, p.timeout_s) == (FAST_MODEL, 512, 30)


# --------------------------------------------------------------------------- parsing: every rejection

# (case id, raw block, needles that MUST appear in the message)
#
# The needles are the point of this table. A parser that rejects correctly with the message
# "invalid providers block" is a parser that costs the operator a bisect of their own YAML, so
# each case demands the offending VALUE (or the field it belongs to) in the text.
_REJECTIONS = [
    ("raw_is_not_a_mapping", ["not", "a", "mapping"], ("mapping",)),
    ("row_is_not_a_mapping", {DECLARED_NAME: ["not", "a", "mapping"]},
     (DECLARED_NAME, "mapping")),
    ("name_has_a_capital", _block("Acme_LLM"), ("Acme_LLM",)),
    ("name_has_a_hyphen", _block("acme-llm"), ("acme-llm",)),
    ("name_starts_with_a_digit", _block("9acme"), ("9acme",)),
    ("name_shadows_a_builtin_tier", _block("minimax"), ("minimax",)),
    ("name_resurrects_a_removed_tier", _block("cursor_cli"), ("cursor_cli",)),
    ("base_url_missing", _block(base_url=_ABSENT), ("base_url",)),
    ("base_url_is_not_http", _block(base_url="ftp://api.acme.example/v1"),
     ("base_url", "ftp://api.acme.example/v1")),
    ("api_key_env_missing", _block(api_key_env=_ABSENT), ("api_key_env",)),
    ("api_key_env_is_lowercase", _block(api_key_env="acme_llm_api_key"),
     ("api_key_env", "acme_llm_api_key")),
    ("model_is_blank", _block(model="   "), ("model",)),
    ("max_tokens_is_zero", _block(max_tokens=0), ("max_tokens", "0")),
    ("max_tokens_is_not_an_int", _block(max_tokens="8192"), ("max_tokens", "8192")),
    ("timeout_s_is_negative", _block(timeout_s=-5), ("timeout_s", "-5")),
    ("timeout_s_is_not_an_int", _block(timeout_s="300"), ("timeout_s", "300")),
]


@pytest.mark.parametrize("raw, needles",
                         [pytest.param(r, n, id=i) for i, r, n in _REJECTIONS])
def test_an_illegal_declaration_raises_and_the_message_names_the_offending_value(raw, needles):
    """A provider block is operator-typed text that becomes a live HTTP client.

    Every rule here exists because the alternative is worse than a crash: a bad `base_url`
    scheme is a request that leaves the machine unencrypted, a lowercase `api_key_env` is a
    credential that is never found so the tier fails at every call, and a name that shadows a
    built-in silently replaces the brain the moat is standing on.
    """
    with pytest.raises(ValueError) as exc:
        providers.parse_declared(raw)
    msg = str(exc.value)
    for needle in needles:
        assert needle in msg, f"{needle!r} missing from {msg!r}"


def test_no_declared_name_may_shadow_any_built_in_tier():
    """Asked of the real table, so adding a tier to `BUILDABLE_TIERS` extends this test for free.

    A shadowing name is the worst failure mode available here: `operator: [minimax]` keeps
    loading, keeps building, and rules verdicts on whatever URL the config block named.
    """
    assert BUILDABLE_TIERS, "the built-in tier table is empty; this test would prove nothing"
    for builtin in BUILDABLE_TIERS:
        with pytest.raises(ValueError) as exc:
            providers.parse_declared(_block(builtin))
        assert builtin in str(exc.value)


@pytest.mark.parametrize("removed", providers.REMOVED_TIERS)
def test_a_removed_tier_cannot_be_resurrected_by_declaring_it(removed):
    """`claude`, `cursor_cli` and `standardcompute` were each deleted WITH their adapter.

    Each left an explicit ValueError in `_build_operator` carrying the date and the reason,
    precisely so a stale config.yaml or plist fails loudly at startup instead of building a
    chain one brain shorter than it reads. A declaration block must not be the door that lets
    the name back in under new management.
    """
    with pytest.raises(ValueError) as exc:
        providers.parse_declared(_block(removed))
    assert removed in str(exc.value)


@pytest.mark.parametrize("removed", providers.REMOVED_TIERS)
def test_the_built_in_removal_error_still_fires_even_when_a_block_declares_the_name(removed):
    """The parser is not the only fence, because a fake or hand-built config bypasses it.

    `_build_operator` must check the removed names BEFORE it consults `cfg.providers`. If the
    declared branch is placed first, a config carrying the name gets a live HTTP client instead
    of the error that names the date and the replacement.
    """
    cfg = _FakeConfig({removed: providers.DeclaredProvider(
        name=removed,
        base_url="https://api.acme.example/v1",
        api_key_env=KEY_ENV,
        model=FULL_MODEL,
    )})
    with pytest.raises(ValueError) as exc:
        op._build_operator(removed, cfg, fast=False, component=None)
    msg = str(exc.value)
    assert removed in msg
    assert "removed" in msg.lower(), (
        "the removal error must say the tier was REMOVED and why; an `unknown operator` here "
        f"loses the date and the replacement: {msg!r}")


# --------------------------------------------------------------------------- the tier table


def test_buildable_tiers_contains_every_built_in_and_the_declared_names():
    """One list of tier names, or a UI offers a tier the factory cannot build.

    That is the exact defect `BUILDABLE_TIERS` was written for: the Control Center's operator
    selector offered `["", "mock", "claude"]` while the live roster was `[minimax, claude_cli]`.
    A declared provider that is absent here is invisible to every dropdown that reads it.
    """
    builtins_only = providers.buildable_tiers()
    for name in BUILDABLE_TIERS:
        assert name in builtins_only, f"{name} is buildable but missing from buildable_tiers()"
    assert DECLARED_NAME not in builtins_only

    declared = providers.parse_declared(_block())
    with_declared = providers.buildable_tiers(declared)
    assert DECLARED_NAME in with_declared
    for name in BUILDABLE_TIERS:
        assert name in with_declared, "declaring a provider must not drop a built-in tier"


# --------------------------------------------------------------------------- the adapter


def test_the_adapter_refuses_to_construct_without_its_credential(monkeypatch):
    """A missing key must fail at CONSTRUCTION, not at the first call.

    Constructing without a key builds a tier that looks alive to every chain that holds it and
    is a guaranteed failure paid before every call — the exact "a dead brain must leave a trace"
    defect. `ProviderExhaustedError` is the type the health layer benches on, so this is what
    turns a keyless tier into a benched tier instead of a per-call outage.
    """
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.raises(ProviderExhaustedError) as exc:
        op.OpenAICompatibleOperator(
            name=DECLARED_NAME,
            base_url="https://api.acme.example/v1",
            api_key_env=KEY_ENV,
            model=FULL_MODEL,
        )
    assert KEY_ENV in str(exc.value), "the error must name the env var the operator has to set"


def test_a_blank_credential_is_treated_as_an_absent_one(monkeypatch):
    """An empty env var is the shape a half-written `.env` produces, and it authenticates nothing."""
    monkeypatch.setenv(KEY_ENV, "   ")
    with pytest.raises(ProviderExhaustedError):
        op.OpenAICompatibleOperator(
            name=DECLARED_NAME,
            base_url="https://api.acme.example/v1",
            api_key_env=KEY_ENV,
            model=FULL_MODEL,
        )


def _build_adapter(**over):
    kwargs = {
        "name": DECLARED_NAME,
        "base_url": "https://api.acme.example/v1",
        "api_key_env": KEY_ENV,
        "model": FULL_MODEL,
    }
    kwargs.update(over)
    return op.OpenAICompatibleOperator(**kwargs)


def test_with_its_credential_set_it_constructs_and_reports_the_model_it_will_call(monkeypatch):
    """`name` and `model_version` are what every dossier, ledger row and health mark record.

    If they do not carry the model, an audit of which brain ruled a verdict answers with the
    provider only — and two models behind one provider are indistinguishable after the fact.
    """
    monkeypatch.setenv(KEY_ENV, "not-a-real-credential")
    built = _build_adapter()
    assert DECLARED_NAME in built.name
    assert FULL_MODEL in built.name
    assert FULL_MODEL in built.model_version


def test_cheap_selects_the_fast_model_and_falls_back_to_the_full_one(monkeypatch):
    """`fast_model` is optional, so `cheap=True` must degrade to the full model, never to blank.

    A blank model name is not an error at construction; it is a 400 from the vendor on the first
    call, which reads as an outage rather than as a missing config line.
    """
    monkeypatch.setenv(KEY_ENV, "not-a-real-credential")

    with_fast = _build_adapter(fast_model=FAST_MODEL, cheap=True)
    assert FAST_MODEL in with_fast.model_version
    assert FULL_MODEL not in with_fast.model_version

    without_fast = _build_adapter(cheap=True)
    assert FULL_MODEL in without_fast.model_version

    not_cheap = _build_adapter(fast_model=FAST_MODEL, cheap=False)
    assert FULL_MODEL in not_cheap.model_version
    assert FAST_MODEL not in not_cheap.model_version


# --------------------------------------------------------------------------- the factory


def test_the_factory_builds_a_declared_provider_from_config_alone(monkeypatch):
    """THE WHOLE POINT: no branch in `_build_operator`, no name in `BUILDABLE_TIERS`, no adapter.

    If this fails, adding a provider is a source edit again, and the ~85-edit path is back.
    """
    monkeypatch.setenv(KEY_ENV, "not-a-real-credential")
    declared = providers.parse_declared(_block(fast_model=FAST_MODEL))
    cfg = _FakeConfig(declared)

    built = op._build_operator(DECLARED_NAME, cfg, fast=False, component=None)
    assert isinstance(built, op.OpenAICompatibleOperator)
    assert FULL_MODEL in built.model_version

    fast = op._build_operator(DECLARED_NAME, cfg, fast=True, component=None)
    assert FAST_MODEL in fast.model_version, "`fast=True` must reach the adapter's cheap switch"


def test_an_undeclared_name_is_still_an_unknown_operator(monkeypatch):
    """The declared branch must not swallow the error that catches a typo in `operator:`."""
    monkeypatch.setenv(KEY_ENV, "not-a-real-credential")
    cfg = _FakeConfig(providers.parse_declared(_block()))
    with pytest.raises(ValueError) as exc:
        op._build_operator("acme_typo", cfg, fast=False, component=None)
    assert "acme_typo" in str(exc.value)


# --------------------------------------------------------------------------- the trust fence


def test_a_declared_provider_is_never_trusted_to_rule_finally(monkeypatch):
    """THE MOST IMPORTANT TEST IN THIS FILE.

    A declared provider is a stranger: an operator typed a base URL and a model name into a YAML
    file. `moat_primary()` is the only set that may rule FINALLY, and anything outside it is
    stamped `provisional`, never publishes on PASS (`run.py:864`), and is auto re-vetted. If a
    config-declared brain silently landed inside that set, a PASS it ruled would publish a £49
    deliverable on an unverified verdict, and nothing downstream would know to re-check it.

    `is_provisional_provider` is conservative by construction — an unknown name is provisional,
    not trusted — and this test pins that it stays that way for a name that arrives from config.
    """
    monkeypatch.setenv(KEY_ENV, "not-a-real-credential")
    declared = providers.parse_declared(_block())
    cfg = _FakeConfig(declared)

    assert DECLARED_NAME not in op.moat_primary(), (
        "declaring a provider in config.yaml must not enrol it in the trusted verdict set")
    assert op.is_provisional_provider(DECLARED_NAME) is True

    built = op._build_operator(DECLARED_NAME, cfg, fast=False, component=None)
    assert op.is_provisional_provider(built.name.split("/")[0]) is True


def test_the_fence_is_about_the_roster_and_not_about_being_declared():
    """The fence must key on `moat_primary()` membership, never on "did this come from config".

    Pinning it the other way pins the ROSTER: MiniMax was outside the trusted set until
    2026-08-15 and inside it after, on receipts. A test that hardcodes a brand is testing
    yesterday's roster rather than the fence.
    """
    for trusted in op.moat_primary():
        assert op.is_provisional_provider(trusted) is False
    assert op.is_provisional_provider("") is True


# --------------------------------------------------------------------------- no network, ever


def test_declaring_and_building_a_provider_performs_no_request(monkeypatch):
    """A unit suite that can reach the internet is a unit suite whose result depends on the wifi.

    Every adapter in `prospector/operator.py` calls out through `urllib.request.urlopen`, so
    breaking that one symbol breaks every path to the network. Construction and inspection must
    survive it; only an actual completion call may need it.
    """
    def _no_network(*a, **kw):
        raise AssertionError("a test performed a network call")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setenv(KEY_ENV, "not-a-real-credential")

    declared = providers.parse_declared(_block(fast_model=FAST_MODEL))
    assert providers.buildable_tiers(declared)
    cfg = _FakeConfig(declared)
    built = op._build_operator(DECLARED_NAME, cfg, fast=False, component=None)
    assert built.name and built.model_version
    assert op.is_provisional_provider(DECLARED_NAME) is True
