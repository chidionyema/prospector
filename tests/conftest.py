"""Shared fixtures for the prospector test suite."""
from __future__ import annotations

import pytest

from prospector.config import Config, load_config


@pytest.fixture(autouse=True)
def _isolate_provider_health(tmp_path, monkeypatch):
    """Point the shared provider-health singleton at a per-test temp file.

    The persisted health layer (health.py) is process-wide state read/written by the
    failover chains. Without isolation, one test marking a provider exhausted would
    leak into later tests AND pollute the real store/provider_health.json. Each test
    gets a fresh, empty, throwaway health file."""
    import prospector.health as H
    monkeypatch.setattr(H, "_DEFAULT",
                        H.ProviderHealth(tmp_path / "provider_health.json"))


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path, monkeypatch):
    """Redirect the append-only audit log at a per-test temp dir.

    Without this, any test that exercises a search provider or the brain chain appends
    real-looking rows to store/scheduler/audit/<today>.jsonl — the file we read to decide
    what the daemon actually did. That is not a cosmetic leak: on 2026-07-31 six
    `brain_fallthrough` rows carrying fixture values ("served": "b",
    "last_err": "gemini cli exhausted...") sat in the production log at test-run pids and
    read exactly like a live moat failure.

    Patched on the module attribute, not the env var: audit.py binds _AUDIT_DIR at import
    (audit.py:66), so setenv alone is a no-op for an already-imported module."""
    import prospector.audit as A
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PROSPECTOR_AUDIT_DIR", str(audit_dir))
    monkeypatch.setattr(A, "_AUDIT_DIR", audit_dir)


@pytest.fixture(autouse=True)
def _isolate_price_rationale(tmp_path, monkeypatch):
    """Write D3 price-rationale records (price_rationale.py) under a per-test temp root.

    The bridge writes one on every publish, and several tests drive that path. Without
    this, a test run files fabricated derivation records into store/pricing/rationale/ —
    the directory `PricePatchRequest.RationaleRef` points at for real, live prices. Same
    class of leak as the audit log above, on the money rail instead of the run log."""
    monkeypatch.setenv("PROSPECTOR_RATIONALE_ROOT", str(tmp_path / "rationale_root"))


@pytest.fixture(autouse=True)
def _isolate_durable_ledger(tmp_path, monkeypatch):
    """Redirect the durable ledger (storage/durable_ledger.md) at a per-test temp file.

    The Tribunal's 4th check appends a `LAW:` line on every KILL that carries one
    (middleware.TribunalMiddleware._commit_law). Unfenced, that wrote fixture laws straight
    into the production ledger: 1196 of them were already committed on HEAD by 2026-08-06,
    lines like "LAW: Do not generate concepts related to abc123 after multiple failed wedge
    pivots." This is worse than the audit-log leak it resembles, because the ledger is not a
    log — moat_prompts._load_ledger feeds its last 15 laws into both the generator and the
    verifier prompt as "concepts mathematically proven to fail", so test junk becomes a
    standing ban on what the engine may propose.

    setenv is sufficient here, unlike _isolate_audit_log above: middleware resolves the path
    per call in default_ledger_path() rather than binding a module constant at import."""
    monkeypatch.setenv("PROSPECTOR_LEDGER_PATH", str(tmp_path / "durable_ledger.md"))


@pytest.fixture(autouse=True)
def _isolate_numeric_citation_shadow(tmp_path, monkeypatch):
    """Redirect the numeric-citation shadow log at a per-test temp dir.

    Fifth instance of the same leak, and the only one caught by its own canary rather
    than by reading production state after the fact: `numeric_citation.enabled` flipped
    to `true` (config.yaml:1065, founder 2026-08-07), and the very next suite run wrote
    118 rows stamped `"provider": "mock"` into
    store/numeric_citation_shadow/shadow-2026-08.jsonl. Every test that drives a check
    through a `load_config()` cfg logs a row, and that file is the corpus we read to
    decide whether the observer is worth promoting out of shadow mode — fixture figures
    in it would bias exactly the measurement it exists to produce.

    setenv is sufficient: resolve_log_path() resolves per call and reads the env var
    itself (numeric_citation.py:551), so nothing is bound at import."""
    monkeypatch.setenv("PROSPECTOR_NUMERIC_CITATION_LOG_DIR",
                       str(tmp_path / "numeric_citation_shadow"))


@pytest.fixture(autouse=True)
def _isolate_prescreen_shadow(tmp_path, monkeypatch):
    """Redirect the E6 prescreen-prefilter shadow log at a per-test temp dir.

    Seventh instance, and it had already happened when this fixture was written:
    `prescreen_prefilter.shadow_mode` flipped to true (config.yaml:1036) and the only
    rows store/prescreen_shadow/shadow-2026-08.jsonl ever held were 80 scorings of ONE
    fixture candidate — "Novel fintech approach for micro-farmers",
    tests/behavioural/test_prescreen_preserves_novelty.py:28. Not a biased corpus: a
    corpus that was 100% fixture, in the file E6's ship/kill decision reads.

    That the leak is invisible is the point. `prescreen.py:173` calls `record_shadow`
    on every prescreen, shadow rows are log-only by construction, so nothing fails and
    no test turns red — the damage lands in a measurement taken weeks later.

    setenv is sufficient: resolve_log_path() resolves per call and reads the env var
    itself (prescreen_prefilter.py:415), so nothing is bound at import."""
    monkeypatch.setenv("PROSPECTOR_PRESCREEN_SHADOW_LOG_DIR",
                       str(tmp_path / "prescreen_shadow"))


@pytest.fixture(autouse=True)
def _no_live_payment_credentials(monkeypatch):
    """Strip money-rail credentials from os.environ for every test.

    Sixth instance of this file's recurring leak, and the first one that left the machine.
    On 2026-08-07 three tests in tests/behavioural/test_publish.py failed with a REAL Stripe
    idempotency error carrying a real request id — `Keys for idempotent requests can only be
    used with the same parameters they were first used with ...
    'prospector-product-af1647af560711a1'`. The suite had been calling Stripe over the network
    and creating products there; the collision only surfaced once the product's parameters
    drifted, so the calls had been succeeding silently before that.

    Two things had to line up, and the second is why patching more mocks would not have fixed
    it. `EngineBridge` builds a live provisioner from the environment at bridge.py:281
    (`StripeProvisioner(self.stripe_api_key) if self.stripe_api_key else None`), and
    test_publish.py patches `requests.post` — but StripeProvisioner does not use requests. It
    uses the Stripe SDK (`self._stripe.Product.create(...)`, bridge.py:1284), which carries its
    own HTTP client and sails straight past that patch. Every one of those tests passes in
    isolation and fails in-suite, because in isolation the environment happens to be clean.

    So the fence is on the credential, not on the transport: with no key, bridge.py:281 yields
    None and the money rail cannot be reached however a future test mocks (or forgets to mock)
    the wire. `.env` in this repo carries STRIPE_LIVE_API_KEY as well as the test key, and
    `_select_stripe_key` (bridge.py:293) prefers the live one whenever the store URL is not
    local — so the same leak against a non-local store would have reached live Stripe, not the
    sandbox. That is the reason this is fenced rather than tidied.

    Deleting rather than blanking: bridge.py tests truthiness, and `patch.dict` in
    tests/test_engine_bridge.py sets these keys inside the test body — i.e. after this fixture
    runs — so the key-selection tests keep working exactly as written.

    THE ENVIRONMENT WAS ONLY HALF THE DOOR (found 2026-08-07, proven by repro). Deleting these
    keys is not sufficient on its own, because `prospector.run._load_dotenv` (:2444) reads `.env`
    and `~/.config/llm/secrets.sh` off DISK and fills any key that is *absent* from os.environ —
    and a key this fixture just deleted is, by construction, absent. Measured: strip both Stripe
    keys, call `_load_dotenv()` once, and both are resident again, the live one included
    (`sk_live`, 107 chars). Three tools call it (`tools/reprice_live_packs.py:87`,
    `tools/publish_passes.py:115`, `tools/price_history.py:159`), and two tests had already
    neutralised it by hand (`test_price_history_tool.py:155`,
    `test_publish_reuse_artifacts.py:46`) — per-test patches for a hole that wanted one central
    fence.

    So the guard below closes the file route as well. It is also why "the key was resident at no
    test boundary" was never evidence of safety: a credential read from disk at call time is
    never at a boundary."""
    for key in ("STRIPE_API_KEY", "STRIPE_LIVE_API_KEY", "PADDLE_API_KEY",
                "STORE_INTERNAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PROSPECTOR_DISABLE_DOTENV", "1")


@pytest.fixture(autouse=True)
def _no_live_grounding_probe(monkeypatch):
    """Stub the per-tick grounding probe to "healthy" unless a test says otherwise.

    `_generation_suppressed` gained a CAUSAL gate on 2026-08-06 (`_grounding_degraded_reason`),
    and it works by issuing a real search against the live retrieval chain. That is correct in
    the daemon and wrong in a unit test twice over: it puts a network call on the path of every
    test that touches a tick, and — because it fails closed — a test cfg built from
    `SimpleNamespace` makes `make_provider` raise, which would silently flip every pre-existing
    generation assertion from "generated" to "suppressed" for a reason that has nothing to do
    with what the test is pinning.

    Defaulting to healthy keeps those tests testing what they were written to test. The gate's
    own tests (tests/scheduler/test_grounding_gate.py) monkeypatch over this fixture, which
    wins because it is applied after."""
    from prospector.scheduler import run_scheduled as rs
    monkeypatch.setattr(rs, "_probe_grounding_once", lambda cfg, timeout_s: ("", None))


@pytest.fixture
def cfg() -> Config:
    """Load real config from config.yaml (fixture mode wired by individual tests)."""
    c = load_config()
    # Tests that need fixture retrieval set c.retrieval.provider themselves;
    # this fixture just provides a clean config base.
    return c


@pytest.fixture
def fixture_cfg(cfg: Config) -> Config:
    """Config with retrieval provider set to 'fixture' and cache disabled."""
    cfg.retrieval.provider = "fixture"
    cfg.retrieval.cache = False
    return cfg
