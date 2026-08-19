"""The gateway's fences, tested where they live.

Every fence in this console is enforced in Python, in `dispatch`, and NOT in the web handler. That
is the property under test: a caller who reaches the engine some other way — the CLI, a future
Telegram surface, a script — hits the same refusal.

Nothing here writes to the real store. `_record_intent` and `_store_ops_dir` are redirected to
tmp_path, because a test suite that appends to `store/ops/intents.jsonl` puts fiction in the
operator's audit log, which this repo has done before to the durable ledger and the audit log.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from prospector.ops import console_api as api


@pytest.fixture(autouse=True)
def _no_production_writes(tmp_path, monkeypatch):
    """Send every intent receipt to tmp_path. Also proves the log path is a single choke point."""
    ops = tmp_path / "ops"
    ops.mkdir()
    monkeypatch.setattr(api, "_store_ops_dir", lambda cfg: ops)
    return ops


@pytest.fixture
def cfg():
    return api._cfg(None)


# --------------------------------------------------------------------------- #
# The envelope
# --------------------------------------------------------------------------- #
def test_every_response_is_dated():
    """Founder requirement: every screen states when its data was read. It cannot if the
    gateway does not date the read."""
    doc, code = api.dispatch(["views"])
    assert code == 0
    assert isinstance(doc["as_of"], float)
    assert doc["as_of_iso"].endswith("Z")
    assert doc["contract"] == api.CONTRACT_VERSION


def test_an_unknown_view_is_a_bad_request_not_a_crash():
    doc, code = api.dispatch(["read", "no_such_view"])
    assert code == 2
    assert doc["ok"] is False
    assert doc["error_kind"] == "UnknownView"
    # The error names the alternatives, so an operator is not left guessing.
    assert "status" in doc["error"]


def test_read_failure_reports_the_reason_and_never_empty_data(monkeypatch):
    """A swallowed outage returns `[]` and reads as 'nothing to show'. This one raises."""
    def boom(cfg, args):
        raise RuntimeError("the ledger is unreadable")

    monkeypatch.setitem(api.READS, "spend", boom)
    doc, code = api.dispatch(["read", "spend"])
    assert code == 1
    assert doc["ok"] is False
    assert doc["data"] is None
    assert "unreadable" in doc["error"]


# --------------------------------------------------------------------------- #
# The confirmation fence
# --------------------------------------------------------------------------- #
def test_a_write_without_a_token_is_refused_and_returns_the_preview():
    doc, code = api.dispatch([
        "act", "pause.arm",
        "--payload", json.dumps({"scope": "generation", "reason": "testing the fence"}),
    ])
    assert code == 4
    assert doc["error_kind"] == "ConfirmationRequired"
    # The refusal hands back the preview AND a usable token, so the operator's next step is one
    # click rather than a second round trip.
    assert doc["data"]["preview"] is True
    assert len(doc["data"]["confirm"]) == 20


def test_the_refusal_is_recorded(_no_production_writes):
    api.dispatch([
        "act", "pause.arm",
        "--payload", json.dumps({"scope": "generation", "reason": "testing the fence"}),
    ])
    rows = [json.loads(x) for x in
            (_no_production_writes / "intents.jsonl").read_text().splitlines() if x.strip()]
    assert rows, "a refused write must leave a trace; a log of successes cannot explain a quiet day"
    assert rows[-1]["applied"] is False
    assert "confirmation" in rows[-1]["refused"]


def test_a_token_is_bound_to_its_action(cfg):
    payload = {"scope": "generation", "reason": "x"}
    for_arm = api._valid_tokens(cfg, "pause.arm", payload)[0]
    for_disarm = api._valid_tokens(cfg, "pause.disarm", payload)[0]
    assert for_arm != for_disarm


def test_a_token_is_bound_to_its_arguments(cfg):
    a = api._valid_tokens(cfg, "pause.arm", {"scope": "generation", "reason": "x"})[0]
    b = api._valid_tokens(cfg, "pause.arm", {"scope": "all", "reason": "x"})[0]
    assert a != b, "a token for 'pause generation' must not confirm 'pause everything'"


def test_a_token_ignores_the_nonce_and_the_actor(cfg):
    """The token commits to what the operator was SHOWN. The nonce makes the write idempotent and
    is minted per attempt; binding it would force a fresh preview for every retry."""
    base = {"scope": "generation", "reason": "x"}
    assert (api._valid_tokens(cfg, "pause.arm", base)[0]
            == api._valid_tokens(cfg, "pause.arm", {**base, "nonce": "n1", "actor": "web"})[0])


def test_a_token_expires(cfg, monkeypatch):
    payload = {"scope": "generation", "reason": "x"}
    old = api._valid_tokens(cfg, "pause.arm", payload)[0]
    real = time.time
    monkeypatch.setattr(api.time, "time", lambda: real() + 3 * api.CONFIRM_TTL_S)
    assert old not in api._valid_tokens(cfg, "pause.arm", payload)


def test_the_previous_window_still_confirms(cfg, monkeypatch):
    """A preview read slowly must still be confirmable, or the console refuses the operator for
    reading carefully."""
    payload = {"scope": "generation", "reason": "x"}
    real = time.time
    old = api._valid_tokens(cfg, "pause.arm", payload)[0]
    monkeypatch.setattr(api.time, "time", lambda: real() + api.CONFIRM_TTL_S)
    assert old in api._valid_tokens(cfg, "pause.arm", payload)


def test_preview_writes_nothing(monkeypatch):
    calls = []

    def spy(cfg, payload, preview):
        calls.append(preview)
        return {"ok": True}

    monkeypatch.setitem(api.ACTIONS, "pause.arm", spy)
    doc, code = api.dispatch(["act", "pause.arm", "--payload", "{}", "--preview"])
    assert code == 0
    assert calls == [True], "preview must never call the action in write mode"
    assert doc["data"]["preview"] is True


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
def test_price_writes_are_refused_by_name_with_a_reason():
    """Refused BY NAME, not by absence. '404 unknown action' reads as a missing feature; this
    says why it will not exist."""
    doc, code = api.dispatch(["act", "catalogue.set_price",
                              "--payload", json.dumps({"id": "x", "pence": 100})])
    assert code == 3
    assert doc["error_kind"] == "RefusedByDesign"
    assert "bridge.py" in doc["error"]


def test_no_action_can_reach_a_price():
    assert not [a for a in api.ACTIONS if "price" in a or "reprice" in a]


def test_the_destructive_index_tool_runs_only_behind_a_snapshot():
    """This test used to assert `index.reconcile` was refused outright. The fence changed on
    2026-08-16 (founder directive: "we just need rollback to be safe not to hide actions").
    Refusing the button never stopped the deletion; it moved the deletion to a terminal, where
    nothing took a snapshot and nothing wrote a receipt. So the tool now runs from the console,
    and what this pins is the path it must take: no action by that name, a catalogued tool that
    declares it writes, and a run that is refused until a token confirms the preview."""
    doc, code = api.dispatch(["act", "index.reconcile", "--payload", "{}"])
    assert code == 2, "the old action name must not resolve to anything"
    assert "index.reconcile" not in api.ACTIONS

    tool = [t for t in api.TOOLS if t["path"] == "scripts/reconcile_orphan_index.py"]
    assert tool, "the tool must stay in the inventory, not vanish with the refusal"
    tool = tool[0]
    assert tool["run"] is True
    assert tool["writes"] is True

    doc, code = api.dispatch(["act", "tools.run",
                              "--payload", json.dumps({"id": tool["id"], "reason": "orphans"})])
    assert code == 4
    assert doc["error_kind"] == "ConfirmationRequired"
    preview = doc["data"]
    assert preview["path"] == "scripts/reconcile_orphan_index.py"
    assert "snapshot" in preview["snapshot"]
    assert preview["command"], "the preview must name the exact command it would run"


# --------------------------------------------------------------------------- #
# Catalogue: the one non-price write
# --------------------------------------------------------------------------- #
def test_set_listing_uses_only_the_listing_endpoint(monkeypatch):
    """Re-POSTing a pack to /internal/catalog with IsListed=false goes through an UPSERT that
    assigns ProviderProductId and ProviderPriceId from the request unconditionally — so an
    unlisting done that way nulls the pack's Stripe ids. This action may only touch the bit."""
    seen = []

    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        seen.append((method, path, body))
        if path.startswith("/catalog/"):
            return {"status": 200, "body": {"id": "abc", "title": "A pack"}, "url": path}
        if "price-history" in path:
            return {"status": 200, "body": {"changeCount": 0}, "url": path}
        return {"status": 200, "body": {"ok": True}, "url": path}

    monkeypatch.setattr(api, "_store_call", fake_call)
    cfg = api._cfg(None)
    receipt = api._act_catalogue_listing(
        cfg, {"id": "abc", "listed": False, "reason": "citations rotted"}, False)

    writes = [(m, p) for m, p, _ in seen if m != "GET"]
    assert writes == [("PATCH", "/internal/catalog/abc/listing")]
    assert receipt["applied"] is True
    body = [b for m, p, b in seen if m == "PATCH"][0]
    assert set(body) == {"IsListed", "Reason"}, "the body must not carry a price or a provider id"


def test_set_listing_refuses_an_unexplained_delisting():
    cfg = api._cfg(None)
    with pytest.raises(ValueError, match="reason"):
        api._act_catalogue_listing(cfg, {"id": "abc", "listed": False}, True)


def test_the_catalogue_is_read_from_the_route_that_exists(monkeypatch):
    """`/v1/catalog` does not exist. The public routes are `/catalog` and `/catalog/{id}`
    (Store.Api Program.cs:255, :329). An invented path 404s and reads as an outage."""
    seen = []

    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        seen.append(path)
        return {"status": 200, "body": [], "url": path}

    monkeypatch.setattr(api, "_store_call", fake_call)
    api._read_catalogue(api._cfg(None), {})
    assert seen == ["/catalog"]


def test_a_withdrawn_pack_is_distinguished_from_a_missing_one(monkeypatch):
    """`GET /catalog/{id}` 404s on an unlisted pack on purpose. Pairing it with the internal
    price-history status is the only way to tell 'withdrawn' from 'no such id' — and telling an
    operator 'already off the shelf' when they typed the id wrong is a lie."""
    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        if "price-history" in path:
            return {"status": 200, "body": {"changeCount": 2}, "url": path}
        return {"status": 404, "body": "", "url": path, "http_error": True}

    monkeypatch.setattr(api, "_store_call", fake_call)
    out = api._read_pack(api._cfg(None), {"id": "abc"})
    assert out["listed"] is False
    assert out["exists"] is True
    assert "OFF the shelf" in out["listed_note"]


def test_a_pack_that_does_not_exist_says_so(monkeypatch):
    def fake_call(method, path, *, body=None, internal=False, timeout=20.0):
        return {"status": 404, "body": "", "url": path, "http_error": True}

    monkeypatch.setattr(api, "_store_call", fake_call)
    out = api._read_pack(api._cfg(None), {"id": "nope"})
    assert out["exists"] is False


def test_an_unreachable_store_raises_rather_than_reporting_an_empty_shelf(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("could not reach the store API")

    monkeypatch.setattr(api, "_store_call", boom)
    with pytest.raises(RuntimeError):
        api._read_catalogue(api._cfg(None), {})


# --------------------------------------------------------------------------- #
# The tool inventory
# --------------------------------------------------------------------------- #
def test_every_listed_tool_the_repo_OWNS_is_on_disk():
    """The table is hand-kept, so it can go stale. `exists` is measured, and this is the check
    that the map still matches the territory.

    SCOPED TO THE REPO ON 2026-08-19, AND THE SCOPE IS THE POINT. This guard used to assert on
    every row. The catalogue then gained its first row outside the checkout — the Hermes
    self-check, at `~/.hermes/scripts/hermes_selfcheck.py` — and the guard went red on CI while
    passing on the laptop, because the laptop has that file and a runner does not. A repo test
    can only grade what the repo ships. Anything else is a fact about one machine, and asserting
    it here turns someone else's push red for a file they never touched.

    So the rule, and it is the same rule `tests/test_suite_is_machine_independent.py` exists to
    enforce: EXISTENCE IS ONLY ASSERTABLE INSIDE THE REPO. An out-of-repo row still gets graded,
    just on the half the repo controls — that the resolver expanded it to an absolute path
    instead of silently hanging it off the repo root, which was the actual bug underneath.
    """
    root = api._repo_root()
    owned, foreign = [], []
    for t in api.TOOLS:
        resolved = api._tool_on_disk(root, t["path"])
        (foreign if not str(resolved).startswith(str(root)) else owned).append((t, resolved))

    out = api._read_tools(api._cfg(None), {})
    by_path = {t["path"]: t for t in out["tools"]}
    missing = [t["path"] for t, _ in owned if not by_path[t["path"]]["exists"]]
    assert missing == [], "catalogued tools the repo ships but does not have"

    for t, resolved in foreign:
        assert resolved.is_absolute(), (
            f"{t['id']}: {t['path']} resolved to {resolved} — an out-of-repo row that is not "
            "absolute was joined to the repo root, which is the defect this scoping hides "
            "if the resolver ever regresses"
        )


def test_money_rail_tools_say_in_the_preview_that_undo_cannot_reach_stripe():
    """These tools were `run=False` until 2026-08-16. They are runnable now, and the safety is
    no longer the refusal — it is that the operator is told, before confirming, exactly what a
    rollback will and will not undo. A Stripe Price minted from this machine cannot be taken
    back by restoring store/, so the preview has to say so in words."""
    money = [t for t in api.TOOLS if t["danger"] and "MONEY RAIL" in t["danger"]]
    assert money, "the price tools must be inventoried, not hidden"
    assert all(t["risk"] == "external" for t in money), \
        "a tool that reaches Stripe is external risk, whatever else it does locally"
    assert all(t["undo_covers"] == "the local half only" for t in money)

    doc, code = api.dispatch(["act", "tools.run",
                              "--payload", json.dumps({"id": money[0]["id"], "reason": "x"})])
    assert code == 4
    assert doc["error_kind"] == "ConfirmationRequired"
    assert "THIS REACHES OFF THIS MACHINE" in doc["data"]["note"]
    assert doc["data"]["undo_covers"] == "the local half only"


def test_destructive_tools_are_never_runnable():
    assert all(t["run"] is False for t in api.TOOLS
               if t["danger"] and "DESTRUCTIVE" in t["danger"])


def test_no_tool_is_runnable_from_the_web_at_all():
    """The console executes exactly one command: this gateway. `run` marks what the console
    COVERS, not a shell-out; if that ever becomes an executor, this test is the alarm."""
    doc, code = api.dispatch(["actions"])
    assert code == 0
    assert not [a for a in doc["data"]["available"] if a.startswith("tool.")]


# --------------------------------------------------------------------------- #
# The stranded shelf
# --------------------------------------------------------------------------- #
class _FakeSurvey:
    """Stands in for `tools/verify_pass_shelf_coverage.py`."""

    def __init__(self, shelf=("live",), passes=(), why=None):
        # Deliberately not `self._passes` — that name would shadow the `_passes` METHOD the
        # gateway calls, and the failure reads as "'list' object is not callable" in production
        # code that is fine.
        self._shelf, self._rows, self._why_map = set(shelf), list(passes), why or {}

    def _shelf_ids(self):
        return self._shelf

    def _passes(self, _root):
        return self._rows

    def _why(self, _root, cid):
        return self._why_map.get(cid, "never published (no lint record)")


def test_an_unreachable_shelf_is_unknown_never_zero_stranded(monkeypatch):
    """Reporting 0 stranded because the network failed is the same defect as an empty default
    reading as 'clean'. The revenue gap must never be understated by an outage."""
    class _Dead(_FakeSurvey):
        def _shelf_ids(self):
            raise TimeoutError("the catalogue did not answer")

    monkeypatch.setattr(api, "_shelf_survey_module", lambda: _Dead())
    out = api._read_shelf(None, {})
    assert out["reachable"] is False
    assert out["stranded"] is None, "unknown must not render as a confident zero"
    assert "did not answer" in out["reason"]


def test_the_blocking_checks_are_the_named_lint_checks_only(monkeypatch):
    """A loose word match read 'error(s)' and '(no lint record)' as check names and reported a
    check called 's'. The checks come from the one place the tool prints them."""
    survey = _FakeSurvey(
        shelf={"onshelf"},
        passes=[("a1", "2026-08-14T00:00:00"), ("onshelf", "2026-08-14T00:00:00")],
        why={"a1": "lint blocked (2 error(s): shelf_copy, title_claim)"},
    )
    monkeypatch.setattr(api, "_shelf_survey_module", lambda: survey)
    out = api._read_shelf(None, {})
    assert out["stranded"] == 1, "a pack already on the shelf is not stranded"
    assert out["rows"][0]["checks"] == ["shelf_copy", "title_claim"]
    assert "s" not in out["rows"][0]["checks"]


def test_every_stranded_pack_names_the_repair_that_fixes_it(monkeypatch):
    survey = _FakeSurvey(
        shelf=set(),
        passes=[("a1", "d"), ("a2", "d"), ("a3", "d")],
        why={"a1": "lint blocked (1 error(s): shelf_copy)",
             "a2": "never published (no lint record)",
             "a3": "lint blocked (1 error(s): citation_urls)"},
    )
    monkeypatch.setattr(api, "_shelf_survey_module", lambda: survey)
    rows = {r["id"]: r["repair"] for r in api._read_shelf(None, {})["rows"]}
    assert rows["a1"] == "shelf.repair_copy"
    assert rows["a2"] == "shelf.publish_pending"
    # Named `manual` rather than silently folded into a repairable class: offering a button that
    # cannot fix it is worse than saying no tool fixes it.
    assert rows["a3"] == "manual"
    for action in ("shelf.repair_copy", "shelf.publish_pending"):
        assert action in api.ACTIONS


@pytest.fixture()
def readable_shelf(monkeypatch):
    """A shelf the console can read, because these two tests are about the CONFIRM GATE.

    `shelf.publish_pending` names the dossiers it will publish, so its preview reads the shelf
    first, and `_pending_publish_paths` RAISES when the shelf is unreachable — deliberately, so
    an outage can never render as "nothing needs publishing". Under pytest there is no store
    database, so that raise fired inside `dispatch`, was caught by the outer handler, and both
    tests saw exit 1 (`OperationalError: unable to open database file`) where they expected the
    gate's exit 4. They were failing on the absence of a database, not on the fence they exist
    to pin. Stubbing the survey is the same trick the shelf-reader tests above already use.
    """
    survey = _FakeSurvey(
        shelf=set(),
        passes=[("a1", "2026-08-14T00:00:00"), ("a2", "2026-08-14T00:00:00")],
        why={"a1": "lint blocked (1 error(s): shelf_copy)",
             "a2": "never published (no lint record)"},
    )
    monkeypatch.setattr(api, "_shelf_survey_module", lambda: survey)
    return survey


def test_a_shelf_repair_cannot_be_run_in_one_step(readable_shelf):
    """The repairs call a model and rewrite live copy. They go through the same preview-then-
    confirm gate as every other write; there is no one-step path."""
    for action in ("shelf.repair_copy", "shelf.publish_pending"):
        doc, code = api.dispatch([
            "act", action, "--payload", json.dumps({"reason": "unblock the shelf"}),
        ])
        assert code == 4, f"{action} was applied without a confirmation"
        assert doc["error_kind"] == "ConfirmationRequired"


def test_a_shelf_repair_preview_runs_nothing(monkeypatch, readable_shelf):
    """A preview that actually ran the repair would rewrite live copy for someone who only
    wanted to look."""
    def _boom(*a, **k):
        raise AssertionError("a preview must not spawn the repair tool")

    monkeypatch.setattr(api.subprocess, "run", _boom)
    for action in ("shelf.repair_copy", "shelf.publish_pending"):
        doc, code = api.dispatch([
            "act", action, "--payload", json.dumps({"reason": "looking"}),
        ])
        assert code == 4
        assert doc["data"]["moat_affecting"] is False


# --------------------------------------------------------------------------- #
# A tool outside this checkout
#
# Found 2026-08-19 by `test_every_listed_tool_is_on_disk`, which is the one check in this file
# that measures the territory rather than the map. The catalogue gained its first `~`-rooted row
# on 2026-08-19 (the Hermes self-check). `root / "~/.hermes/..."` is `<repo>/~/.hermes/...`, so
# the console called the tool missing and the run action refused it — a button that could not
# have worked on any day since it was registered.
# --------------------------------------------------------------------------- #
def test_a_home_rooted_tool_resolves_outside_the_repo():
    """The resolver, directly. `root / rel` is the defect and it fails silently."""
    root = Path("/somewhere/else/prospector")
    out = api._tool_on_disk(root, "~/.hermes/scripts/hermes_selfcheck.py")

    assert str(out).startswith(str(Path.home())), f"still joined to the repo root: {out}"
    assert "~" not in str(out)
    assert api._tool_on_disk(root, "scripts/doc_lint.py") == root / "scripts/doc_lint.py", (
        "a repo-relative row must still resolve against the repo"
    )


def test_a_home_rooted_command_is_expanded_before_the_child_runs():
    """The child runs without a shell, so nothing else will expand it.

    The exists check and the argv build are two separate sites reading the same string. Fixing
    one and not the other gives a button that passes its preflight and then dies with
    'No such file or directory'.
    """
    tool = {"command": "/usr/local/bin/python3 ~/.hermes/scripts/hermes_selfcheck.py",
            "purpose": "the self-check"}
    argv = api._tool_argv(tool, {})

    assert not any(a.startswith("~") for a in argv), argv
    assert argv[-1] == str(Path.home() / ".hermes/scripts/hermes_selfcheck.py")


def test_a_browser_supplied_value_is_never_tilde_expanded():
    """Expansion happens on the CATALOGUED command, before substitution. A value the caller sent
    is data, and turning `~` in it into a real home directory would be this module deciding what
    a caller's string means."""
    tool = {"command": "/usr/local/bin/python3 scripts/doc_lint.py --path <p>",
            "purpose": "doc lint"}
    argv = api._tool_argv(tool, {"p": "~/secrets"})

    assert argv[-1] == "~/secrets", argv


# --- Every heartbeat record carries a reason -------------------------------------------------
#
# The console's front page renders `Producer: ${why} · Consumer: ${why}` as the incident headline.
# `_heartbeats` set `why` in only two of its four branches, so a stale beat that HAD promised a
# wake time fell through with the field absent -- and the operator read the literal word
# "undefined" at the top of the page, during an incident, in the largest type on the screen.
#
# Seen live on 2026-08-19: "Producer: generating -- ... Consumer: undefined".
#
# This test is parameterised over the branches rather than pinning the one that broke, because the
# class of failure is "a new branch forgets it".


def _hb_dir(monkeypatch, tmp_path):
    """Point `_heartbeats` at a scratch scheduler directory."""
    from prospector.scheduler import paths as _paths

    sched = tmp_path / "scheduler"
    sched.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_paths, "scheduler_dir", lambda cfg: sched)
    return sched


@pytest.mark.parametrize(
    "beat,label",
    [
        (None, "no heartbeat file at all"),
        ({"pid": 1, "ts": 0, "phase": "sleeping", "next_check": 1.0}, "stale, and it promised a wake time"),
        ({"pid": 1, "ts": 0, "phase": "sleeping"}, "stale, with no promise"),
        ({"pid": 1, "ts": 0, "phase": "generating"}, "a working phase, which promises nothing"),
        ({"pid": 1, "phase": "sleeping"}, "a beat with no timestamp"),
        ({"pid": 1, "ts": None, "phase": "waiting", "beat_every_s": 60}, "a null timestamp"),
        ("{ not json", "a file that is not JSON"),
    ],
)
def test_every_heartbeat_branch_reports_a_reason(monkeypatch, tmp_path, beat, label):
    sched = _hb_dir(monkeypatch, tmp_path)
    if beat is not None:
        body = beat if isinstance(beat, str) else json.dumps(beat)
        for name in ("heartbeat.json", "consumer_heartbeat.json"):
            (sched / name).write_text(body)

    out = api._heartbeats(object())

    for role, rec in out.items():
        why = rec.get("why")
        assert isinstance(why, str) and why.strip(), f"{role} has no `why` when {label}: {rec!r}"
        # A reason that renders "None" or "undefined" is the same defect wearing a different word.
        assert "None" not in why, f"{role} printed a None into its reason when {label}: {why}"
        assert "undefined" not in why, f"{role} printed undefined when {label}: {why}"


def test_a_duration_never_prints_none(monkeypatch):
    """`_hb_dur` is the only place a raw number becomes words. It is fed `None` in real life."""
    assert "None" not in api._hb_dur(None)
    assert api._hb_dur(45) == "45s"
    assert api._hb_dur(600) == "10m"
    assert api._hb_dur(7200) == "2h"
    assert api._hb_dur(200_000) == "2d"


def test_no_heartbeat_shape_can_produce_a_missing_reason(monkeypatch, tmp_path):
    """The guard above enumerates the branches that exist TODAY. This one does not.

    The founder's question was what happens when a new branch is added. A parameterised list of
    seven known shapes answers that badly: a new branch is reached by a new INPUT shape, and a new
    input shape is exactly what an enumerated list does not have. So this sweeps the product of
    every field `_heartbeats` reads, including the values that are absent, null, zero and the
    wrong type, and asserts the one property that must hold whatever branch runs: the record
    carries a sentence, and the sentence does not contain a placeholder word.

    A new branch that forgets `why` fails here without anyone remembering to add a case.
    """
    sched = _hb_dir(monkeypatch, tmp_path)
    now = time.time()
    ABSENT = object()

    pids = [ABSENT, None, 0, 1, 999_999_999]
    stamps = [ABSENT, None, 0, now, now - 999_999, "not-a-number"]
    phases = [ABSENT, None, "", "sleeping", "generating", "draining", "a phase nobody wrote yet"]
    promises = [ABSENT, None, 0, now + 100, now - 999_999, "soon"]
    # "fast" is not decoration: a non-numeric cadence raised an uncaught ValueError and
    # blanked the whole incident page. The sweep is where that now fails.
    cadences = [ABSENT, None, 0, 60, "60", "fast"]

    checked = 0
    for pid in pids:
        for ts in stamps:
            for phase in phases:
                for promised in promises:
                    for every in cadences:
                        body = {}
                        for key, val in (("pid", pid), ("ts", ts), ("phase", phase),
                                         ("next_check", promised), ("beat_every_s", every)):
                            if val is not ABSENT:
                                body[key] = val
                        text = json.dumps(body)
                        for name in ("heartbeat.json", "consumer_heartbeat.json"):
                            (sched / name).write_text(text)

                        out = api._heartbeats(object())
                        checked += 1
                        for role, rec in out.items():
                            why = rec.get("why")
                            assert isinstance(why, str) and why.strip(), (
                                f"{role} reported no reason for {text}: {rec!r}")
                            for placeholder in ("None", "undefined", "NaN"):
                                assert placeholder not in why, (
                                    f"{role} printed {placeholder} for {text}: {why}")

    # If a refactor collapses the sweep to a handful of cases it stops being a sweep, and it would
    # go on passing. The count is part of the assertion.
    assert checked >= 1000, f"the sweep only covered {checked} shapes"
