"""A chain whose first brain is dead must SAY so — it must not just quietly answer from the tail.

MEASURED 2026-08-06. One JSON call to every configured brain, `temperature=0.0`::

    deepseek    RuntimeError: DeepSeek call failed: HTTP Error 402: Payment Required
    cursor_cli  ProviderExhaustedError: cursor cli exit 1: ActionRequiredError:
                You've hit your usage limit
    minimax     OK
    claude_cli  OK

`_NONCRITICAL_ORDER` was `(deepseek, cursor_cli, minimax)`, so EVERY generation, prescreen and
score call in production was being served by minimax — the guardrailed emergency tail — after
paying two guaranteed failures first. Nothing raised, nothing logged above INFO, and the run
looked normal from the outside. That is the failure mode of a fallback that works.

Landing on the tail is not neutral. On the classify call at temperature 0.0, minimax returned a
DIFFERENT tier across 3 repeat runs for 4 of 6 candidates (side_hustle vs smb = 2900 vs 4900 on
the L1 ladder), where claude_cli returned the identical answer 18/18.

The specific defect these tests pin: `FallbackOperator._raw` decides permanence with
`hard = isinstance(e, ProviderExhaustedError)`, and the DeepSeek/MiniMax adapters classified
exhaustion with a hand-rolled `"quota" in e or "limit" in e`, which does not match
"402: Payment Required". So a BILLING failure — the most permanent kind there is — was treated
as transient: `mark_exhausted` never ran, deepseek never appeared in
store/provider_health_noncritical.json (cursor_cli, which raises ProviderExhaustedError, was
correctly marked `dead_until` in that same file at that same moment), and the breaker re-probed
a broke account every cooldown_s forever at the head of the chain.
"""
from __future__ import annotations

import pytest

from prospector.errors import ProviderExhaustedError, looks_exhausted
from prospector.operator import FallbackOperator


class _Health:
    """Stand-in for the persisted health file; records what the chain marked dead."""
    def __init__(self):
        self.dead: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        self.cleared: list[str] = []

    def is_dead(self, name): return name in self.dead

    def mark_exhausted(self, name, dead_for_s, *, error=""):
        self.dead[name] = dead_for_s
        self.errors[name] = error

    def clear(self, name): self.cleared.append(name); self.dead.pop(name, None)


def test_the_health_stub_still_matches_the_real_signature():
    """This file's whole point is that a hand-copied double proves the copy, not the code — the
    docstring below says mutation testing already caught one. A double whose signature has
    drifted from ProviderHealth would fail LOUDLY here rather than silently testing a shape the
    production chain no longer calls. (`error=` was added to mark_exhausted on 2026-08-06.)"""
    import inspect
    from prospector.health import ProviderHealth
    for method in ("is_dead", "mark_exhausted", "clear"):
        real = inspect.signature(getattr(ProviderHealth, method))
        fake = inspect.signature(getattr(_Health, method))
        assert list(real.parameters) == list(fake.parameters), (
            f"_Health.{method}{fake} has drifted from ProviderHealth.{method}{real}")


class _Raises:
    def __init__(self, exc): self.exc = exc
    def _raw(self, system, user, temperature): raise self.exc


class _Answers:
    def __init__(self, text="ok"): self.text = text; self.calls = 0
    def _raw(self, system, user, temperature): self.calls += 1; return self.text


# ── the classifier: what counts as "this brain is out of allowance" ──────────

@pytest.mark.parametrize("text", [
    "DeepSeek call failed: HTTP Error 402: Payment Required",
    "HTTP Error 402: Payment Required",
    "Insufficient Balance",
    "You've hit your usage limit",
    "HTTP Error 429: Too Many Requests",
    "Your credit balance is too low",
])
def test_a_spent_account_is_recognised_as_exhaustion(text):
    assert looks_exhausted(text), f"{text!r} would be retried forever as if transient"


@pytest.mark.parametrize("text", [
    "HTTP Error 500: Internal Server Error",
    "timed out",
    "HTTP Error 401: Unauthorized",          # a bad credential must stay LOUD, not be buried
    "context length limit exceeded",         # per-call mistake, not a spent account
])
def test_a_transient_or_configuration_failure_is_not_exhaustion(text):
    assert not looks_exhausted(text), (
        f"{text!r} would hard-trip a healthy brain and hide the real error behind a failover"
    )


# ── the chain: a 402 must be recorded, not silently absorbed ─────────────────

@pytest.mark.parametrize("adapter_name,cls_name", [("deepseek", "DeepSeekOperator"),
                                                   ("minimax", "MiniMaxOperator")])
def test_a_402_from_the_real_adapter_marks_the_brain_dead(monkeypatch, adapter_name, cls_name):
    """The live shape: tier 1 is out of money, the tail answers, and the run looks fine.

    This drives the REAL adapter — its own except-branch classifies the error — by making the
    HTTP layer raise urllib's actual 402. An earlier version of this test hand-copied the
    classifier into a stub `_raw`, so it proved the copy and not the code: restoring the
    adapter's old `"quota" in e or "limit" in e` left it green. Mutation testing caught that;
    the parametrisation over both metered adapters is why the shared classifier is worth having.
    """
    import urllib.error
    import urllib.request
    import prospector.operator as opmod

    def _boom(*a, **kw):
        raise urllib.error.HTTPError("https://api/x", 402, "Payment Required", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(opmod, "_urlopen_read_bounded", _boom, raising=False)

    cls = getattr(opmod, cls_name)
    broke = cls.__new__(cls)                       # no constructor: no key, no network
    broke.name = adapter_name
    broke.model = "x"
    broke._key = "k"
    tail = _Answers("served-by-tail")

    health = _Health()
    chain = FallbackOperator([(adapter_name, broke), ("tail", tail)], health=health)
    assert chain._raw("s", "u", 0.0) == "served-by-tail"   # the run SUCCEEDS — nothing looks wrong
    assert adapter_name in health.dead, (
        "a 402 left no trace in the health file, so nothing could report the chain as degraded "
        "and the broke brain stayed at the head of the chain"
    )
    assert chain.last_served() == "tail"


def test_a_dead_brain_is_skipped_for_free_on_the_next_call():
    """The cost of misclassifying 402: every later call re-pays the failure."""
    health = _Health()
    attempts = {"n": 0}

    class _Counting:
        def _raw(self, system, user, temperature):
            attempts["n"] += 1
            raise ProviderExhaustedError("HTTP Error 402: Payment Required", provider="deepseek")

    tail = _Answers()
    chain = FallbackOperator([("deepseek", _Counting()), ("minimax", tail)], health=health)
    for _ in range(5):
        chain._raw("s", "u", 0.0)
    assert attempts["n"] == 1, "a brain known to be out of money was called again"
    assert tail.calls == 5


def test_a_transient_failure_does_not_mark_the_brain_dead():
    """The other direction: a 500 must not retire a brain that is merely having a bad minute."""
    health = _Health()
    chain = FallbackOperator(
        [("deepseek", _Raises(RuntimeError("HTTP Error 500: Internal Server Error"))),
         ("minimax", _Answers())],
        health=health)
    chain._raw("s", "u", 0.0)
    assert health.dead == {}, "a transient 500 retired the brain into the persisted health file"


def test_a_recovered_brain_clears_its_dead_mark():
    """Otherwise the fix would turn a temporary outage into a permanent demotion."""
    health = _Health()
    healthy = _Answers("primary")
    chain = FallbackOperator([("deepseek", healthy), ("minimax", _Answers("tail"))],
                             health=health)
    health.dead["deepseek"] = 3600.0
    assert chain._raw("s", "u", 0.0) == "tail"      # skipped while marked dead
    health.dead.clear()
    assert chain._raw("s", "u", 0.0) == "primary"   # and used again once the mark is gone
    assert "deepseek" in health.cleared


def test_every_brain_down_raises_rather_than_returning_nothing():
    """Exhaustion must reach the caller as DEFER, never as a silent empty answer."""
    chain = FallbackOperator(
        [("deepseek", _Raises(ProviderExhaustedError("402 payment required", provider="a"))),
         ("minimax", _Raises(ProviderExhaustedError("usage limit", provider="b")))],
        health=_Health())
    with pytest.raises(ProviderExhaustedError):
        chain._raw("s", "u", 0.0)
