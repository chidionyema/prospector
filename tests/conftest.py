"""Shared fixtures for the prospector test suite."""
from __future__ import annotations

import os

import pytest

from prospector.config import Config, load_config

# Variables pytest itself owns and rewrites around every test. PYTEST_CURRENT_TEST carries the
# node id AND the phase, so it reads "…(setup)" at the start of a test and "…(teardown)" at the
# end — a difference on every single test, which would make the guard below fire 5852 times and
# mean nothing. Measured 2026-08-19: with this set empty, every test in the suite errored.
_PYTEST_OWNED_ENV = frozenset({"PYTEST_CURRENT_TEST"})


def _env_snapshot() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _PYTEST_OWNED_ENV}


def pytest_runtest_setup(item):
    """Record the environment before anything in this test has touched it.

    A plain hook rather than a wrapper: pytest calls this before the item's fixtures are set up,
    which is exactly the moment wanted.
    """
    item._prospector_env_before = _env_snapshot()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Restore os.environ after every test, and fail the test that left it changed.

    WHAT THIS PREVENTS. A leaked environment variable poisons every LATER test in the same xdist
    worker, and the victim is what fails. On 2026-08-19 nine tests failed on the CI runner and
    passed on every developer box, in two files (`test_exemplar_eligibility.py`,
    `test_lint_receipt_survives_revet.py`) that had not changed. The variable was
    PROSPECTOR_STORE_DIR, and `Config.store_dir` gives it precedence over `cfg.store["dir"]` —
    which is the exact redirect those tests use to point the store at `tmp_path`. With the
    variable set, the redirect is silently ignored and the tests read somebody else's store.
    Setting it by hand reproduced six of the nine failures on the same assertions.

    It was CI-only because `pytest.ini` runs `-n auto --dist loadfile`: the worker count follows
    the CPU count, so which files share a process differs between the runner and a laptop. A
    defect invisible on every developer box is the kind that needs a machine, not a rule.

    WHY A HOOK AND NOT AN AUTOUSE FIXTURE. This was first written as a fixture declared at the top
    of this file, on the theory that first-set-up means last-torn-down. Measured: it fired on a
    test whose only env write was `monkeypatch.setenv`, because monkeypatch's undo ran AFTER that
    fixture's teardown. Fixture ordering is not something to reason about here. Every fixture
    finalizer, monkeypatch included, runs inside `pytest_runtest_teardown`, so a wrapper around
    that hook is last by construction.

    The restore happens before the failure is raised, so the leaking test is named and the tests
    after it still run against a clean environment. A failure raised in teardown is reported as an
    ERROR against that test rather than a FAILURE — the body already ran — which is why the guard
    test asserts on "1 error".
    """
    try:
        return (yield)
    finally:
        before = getattr(item, "_prospector_env_before", None)
        after = _env_snapshot()
        if before is not None and after != before:
            added = sorted(k for k in after if k not in before)
            removed = sorted(k for k in before if k not in after)
            changed = sorted(k for k in before if k in after and before[k] != after[k])
            keep = {k: v for k, v in os.environ.items() if k in _PYTEST_OWNED_ENV}
            os.environ.clear()
            os.environ.update(before)
            os.environ.update(keep)
            parts = []
            if added:
                parts.append("set " + ", ".join(added))
            if changed:
                parts.append("changed " + ", ".join(changed))
            if removed:
                parts.append("unset " + ", ".join(removed))
            raise AssertionError(
                "this test leaked the environment to every later test in its worker: "
                + "; ".join(parts)
                + ". Use the `monkeypatch` fixture (monkeypatch.setenv / delenv), which restores "
                "the variable itself. A raw `os.environ[...] = ...` survives the test, and the "
                "test that fails next is not this one."
            )



@pytest.fixture(autouse=True)
def _no_grammar_binary(monkeypatch):
    """Keep the external grammar binary out of the suite.

    `copy_lint.grammar_findings` shells out to `harper-cli`, `pack_linter.lint_pack` calls it
    (`pack_linter.py:1461`) and `bridge.publish_pass` calls that (`bridge.py:1031`) — so every
    publish-shaped test pays for it. Measured 2026-08-17 over the 69 publish-heavy tests:
    476.4s with the binary installed, 404.7s with `harper_path()` returning None. 72 seconds,
    15% of that set, for a result none of those tests reads.

    This does not stub the check out. `grammar_findings` returns None when the binary is
    absent (`copy_lint.py:389`), which is its fail-open contract and the path every machine
    without harper-cli already takes — including CI, until CI moved onto this Mac on
    2026-08-16 and started paying for a tool the founder happens to have installed. A suite
    whose runtime depends on which optional binaries are on the box is the same defect class
    as one whose colour depends on it.

    No opt-out is needed. Every test that asserts anything about grammar already replaces
    `harper_path` or `grammar_findings` itself (`test_copy_lint.py:176`, `:184`,
    `test_a_swallowed_bug_is_not_a_missing_measurement.py:142`), and a monkeypatch in a test
    body is applied after this one, so it wins.
    """
    import prospector.copy_lint as CL
    monkeypatch.setattr(CL, "harper_path", lambda: None)


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
def _isolate_usage_wall(tmp_path, monkeypatch):
    """Point the usage-wall marker at a per-test temp file, in BOTH directions.

    READ leak, observed 2026-08-08. `run_claude_cli` preflights the wall and raises before it
    ever spawns the subprocess (`claude_cli.py:268-273`). The marker is a shared ESTATE file
    (`~/.hermes/state/claude_usage_limit.json`) that Otto and this daemon both write, so its
    contents depend on what the machine did in the last hour. `test_claude_cli_failure_reason.py
    ::test_exhaustion_on_stdout_retires_the_brain_instead_of_retrying` asserts one subprocess
    attempt was made; it passed all day and then failed with `assert 0 == 1` immediately after a
    live E1 run tripped the wall, because the preflight short-circuited the very code path under
    test. A test whose colour depends on the estate's last hour is not a test.

    WRITE leak, same file. `usage_wall.observe()` writes the marker, so any test exercising a
    CLI-exhaustion path could bench the SHARED subscription for Otto and the daemon machine-wide
    — the same defect class as the suite that called Stripe for real. Fence the PATH, not each
    call site, so a new test cannot opt out by accident.

    setenv is sufficient: `marker_path()` (usage_wall.py:72) reads the env var per call, and the
    module documents the override as existing for tests only.
    """
    monkeypatch.setenv("PROSPECTOR_USAGE_WALL_MARKER", str(tmp_path / "usage_wall.json"))


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
def _isolate_generation_artifacts(tmp_path, monkeypatch):
    """Redirect the G1 diversity receipts and the G3 exhausted-family cache off the
    production store.

    Eighth instance of this file's recurring leak, and it needed no store fixture to
    happen: `tests/unit/test_blue_sky.py` builds a REAL Config with `load_config()`,
    whose `store_dir` IS the repo's own `store/`, and hands it a stub store. Generation
    then resolves `<store_dir>/exhausted_families.json` and writes it — measured before
    this fixture existed: a clean `store/` grew an untracked
    `store/exhausted_families.json` carrying `built_at_kill_count: 0` on every
    `pytest tests/unit` run, i.e. a denial list built from an EMPTY stub store, sitting
    in the exact path the daemon reads before generating.

    setenv is sufficient: `diversity.generation_artifact_dir()` reads the env var per
    call, so nothing is bound at import."""
    monkeypatch.setenv("PROSPECTOR_GENERATION_ARTIFACT_DIR",
                       str(tmp_path / "generation_artifacts"))


@pytest.fixture(autouse=True)
def _isolate_usage_wall(tmp_path, monkeypatch):
    """Point the estate-wide usage-wall marker at a per-test path.

    `usage_wall.py:51` already declares `PROSPECTOR_USAGE_WALL_MARKER` "overridable for
    tests ONLY" — but nothing set it, so the suite read
    `~/.hermes/state/claude_usage_limit.json`, a marker written by whichever of Otto or
    this daemon last hit the shared subscription. `run_claude_cli` preflights on it
    (claude_cli.py:267), so while a REAL wall is up the preflight raises before
    `_attempt_claude_cli` is reached and every test that counts CLI attempts fails.

    Measured 2026-08-08 01:04, with a live marker reading `capacity returns 01:16:08,
    observed by prospector-cli`: test_fast_fail_exhaustion and
    test_claude_cli_failure_reason failed `assert 0 == 1`, and the same
    behavioural+scheduler command gave `33 failed` and then `246 passed` twenty minutes
    apart with no code change between them. The suite was measuring the estate's quota,
    not the code.

    Writing matters as much as reading: `usage_wall.observe()` (usage_wall.py:180)
    writes that same shared path atomically, so a test exercising the record path would
    have benched OTTO for the cooldown. Tests that mean to exercise the marker
    monkeypatch this env var themselves, which runs after this fixture and wins."""
    monkeypatch.setenv("PROSPECTOR_USAGE_WALL_MARKER",
                       str(tmp_path / "usage_wall" / "claude_usage_limit.json"))


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
    for key in ("STRIPE_API_KEY", "STRIPE_LIVE_API_KEY",
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


@pytest.fixture(autouse=True)
def _no_live_incumbent_seed(monkeypatch):
    """Stub G2's retrieval so no test can put a live web search on the generation path.

    `generation.incumbent_seed.enabled` is TRUE in config.yaml, and a dozen unit tests build a
    real Config via `load_config()` and call `generate()` (e.g.
    tests/unit/test_generation_cross_run_memory.py:32). Without this fence, any of them that
    passes a signal_text or sector would issue real DuckDuckGo/Exa queries during pytest —
    the same class of defect as the audit log, the durable ledger and the usage wall before it,
    and it would additionally make those tests flaky on network weather.

    Only `_fetch_brief` is stubbed, so the gate, the topic derivation and the cache logic all
    still run for real. tests/unit/test_landscape.py monkeypatches over this fixture, which
    wins because it is applied after."""
    from prospector import landscape
    monkeypatch.setattr(landscape, "_fetch_brief", lambda cfg, icfg, topic: "")


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
