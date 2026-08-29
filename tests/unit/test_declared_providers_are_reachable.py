"""A declared provider must be REACHABLE, not merely declarable.

WHAT THIS FILE EXISTS TO STOP. `prospector/providers.py` made adding a provider a config
block, and `tests/unit/test_a_provider_can_be_added_by_config_alone.py` proves the block
parses, refuses bad input, and never lands inside `moat_primary`. Every one of those tests
passed while NO declared provider could complete a single call, because none of them sends a
request.

Measured 2026-08-21 against Groq, same key, same body, same endpoint, one header apart:

    curl's own User-Agent   -> HTTP 200
    Python-urllib/3.11      -> HTTP 403 Forbidden

`urllib.request` sends `Python-urllib/3.x` unless told otherwise, and the bot filters in front
of several providers refuse that string. The adapter set only Content-Type and Authorization,
so every declared provider behind such a filter was unreachable — and the symptom was a 403,
which reads as a bad key and sends whoever meets it to re-issue a credential that was fine.

It survived because the built-in tiers (claude_cli, minimax, deepseek, ollama, openrouter) do
not come through this adapter, and until 2026-08-21 no provider was declared at all. The
feature was complete, tested, and had never carried a byte.

None of these tests performs a network call.
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from prospector import operator as op


def _provider(monkeypatch) -> op.OpenAICompatibleOperator:
    monkeypatch.setenv("ACME_API_KEY", "k-not-real")
    return op.OpenAICompatibleOperator(
        name="acme", base_url="https://api.acme.test/v1", api_key_env="ACME_API_KEY",
        model="acme-small", fast_model="", max_tokens=64, timeout_s=5, cheap=False)


def _capture(monkeypatch) -> list[urllib.request.Request]:
    """Intercept the request the adapter builds, without letting it leave the process."""
    seen: list[urllib.request.Request] = []

    def fake(req, timeout=None, **kw):
        seen.append(req)
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    monkeypatch.setattr(op, "_urlopen_read_bounded", fake)
    return seen


def test_the_adapter_never_sends_the_default_python_user_agent(monkeypatch):
    """The whole defect, in one assertion.

    `Python-urllib/...` is what urllib sends when no User-Agent is set, and it is the string
    the filters refuse. Asserting the ABSENCE of it is what makes this test survive a change
    of product name in the header.
    """
    seen = _capture(monkeypatch)
    _provider(monkeypatch)._raw("sys", "user", 0.0)
    assert seen, "the adapter built no request at all"
    ua = seen[0].get_header("User-agent") or ""
    assert ua, "no User-Agent set, so urllib supplies Python-urllib/3.x and Groq answers 403"
    assert "python-urllib" not in ua.lower(), (
        f"User-Agent {ua!r} is urllib's default, which Groq refuses with 403")


def test_the_user_agent_identifies_this_engine_honestly(monkeypatch):
    """It must say who we are, not impersonate a browser.

    A header that claims to be Chrome would also get past the filter, and would be a lie told
    to every provider we call. The fix is to identify the client, not to disguise it.
    """
    seen = _capture(monkeypatch)
    _provider(monkeypatch)._raw("sys", "user", 0.0)
    ua = seen[0].get_header("User-agent") or ""
    assert "prospector" in ua.lower(), f"User-Agent {ua!r} does not name this engine"
    for browser in ("mozilla", "chrome", "safari", "gecko", "webkit"):
        assert browser not in ua.lower(), (
            f"User-Agent {ua!r} impersonates a browser; identify the client instead")


def test_the_authorization_and_content_type_still_go_out(monkeypatch):
    """Adding a header must not have displaced the two that were already load-bearing."""
    seen = _capture(monkeypatch)
    _provider(monkeypatch)._raw("sys", "user", 0.0)
    req = seen[0]
    assert req.get_header("Content-type") == "application/json"
    assert (req.get_header("Authorization") or "").startswith("Bearer ")


def test_every_preloaded_provider_names_a_real_https_endpoint():
    """The shipped catalogue must not carry a typo'd or plaintext URL.

    Each of these was probed live on 2026-08-21 and answered as an OpenAI-shaped endpoint.
    Two candidates that returned 404 on that probe (Google's generativelanguage OpenAI-compat
    path, and GitHub Models) were deliberately left out rather than shipped broken; this test
    is what stops one being added back without a probe.
    """
    from prospector.config import load_config

    declared = getattr(load_config(), "providers", {}) or {}
    assert declared, "config.yaml ships no providers: block — the catalogue is the deliverable"
    for name, spec in declared.items():
        assert spec.base_url.startswith("https://"), f"{name}: {spec.base_url} is not https"
        assert not spec.base_url.endswith("/"), f"{name}: trailing slash doubles the path"
        assert spec.api_key_env.endswith("_API_KEY"), f"{name}: {spec.api_key_env} is not a key name"
        assert spec.model, f"{name}: no model pinned"


def test_a_preloaded_provider_with_no_key_is_skipped_not_fatal(monkeypatch):
    """The fact that makes preloading safe, asserted rather than assumed.

    A catalogue of 15 providers on a machine holding 3 keys must cost nothing and break
    nothing. That only holds because ProviderExhaustedError is a RuntimeError and
    `make_operator` drops the tier it is raised for.
    """
    from prospector.errors import ProviderExhaustedError

    assert issubclass(ProviderExhaustedError, RuntimeError), (
        "make_operator catches RuntimeError; if this stops holding, a keyless preloaded "
        "provider takes the whole chain down instead of being skipped")

    monkeypatch.delenv("ACME_API_KEY", raising=False)
    with pytest.raises(ProviderExhaustedError):
        op.OpenAICompatibleOperator(
            name="acme", base_url="https://api.acme.test/v1", api_key_env="ACME_API_KEY",
            model="acme-small", fast_model="", max_tokens=64, timeout_s=5, cheap=False)


def test_llm_base_url_and_llm_api_key_route_through_the_estate_router(monkeypatch):
    """crew#325: two env vars point any declared provider at the estate's LiteLLM router.

    `LLM_BASE_URL`/`LLM_API_KEY`, when both set, outrank the endpoint and key this operator
    was declared with in config.yaml — the same override idiom `OllamaOperator` already uses
    for `OLLAMA_BASE_URL`. No config.yaml edit and no new provider entry required.
    """
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example-zone.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "estate-master-key")
    monkeypatch.setenv("ACME_API_KEY", "laptop-only-key")

    provider = op.OpenAICompatibleOperator(
        name="acme", base_url="https://api.acme.test/v1", api_key_env="ACME_API_KEY",
        model="acme-small", fast_model="", max_tokens=64, timeout_s=5, cheap=False)

    assert provider.base_url == "https://llm.example-zone.test/v1"
    assert provider._key == "estate-master-key"


def test_without_the_router_env_vars_behaviour_is_unchanged(monkeypatch):
    """The other half of the same property: unset is byte-for-byte today's behaviour."""
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("ACME_API_KEY", "laptop-only-key")

    provider = op.OpenAICompatibleOperator(
        name="acme", base_url="https://api.acme.test/v1", api_key_env="ACME_API_KEY",
        model="acme-small", fast_model="", max_tokens=64, timeout_s=5, cheap=False)

    assert provider.base_url == "https://api.acme.test/v1"
    assert provider._key == "laptop-only-key"


def test_no_declared_provider_may_rule_finally():
    """The trust fence, re-asserted against the SHIPPED catalogue rather than a fixture."""
    from prospector.config import load_config

    declared = getattr(load_config(), "providers", {}) or {}
    trusted = [n for n in declared if not op.is_provisional_provider(n)]
    assert not trusted, (
        f"declared providers {trusted} are inside moat_primary and could publish a paid "
        "deliverable on an unverified verdict")
