"""The in-repo Telegram sender, and the fallback that makes it reachable (issue #355).

WHAT THESE PIN. Alerting failed on 2026-08-18 not because the code was wrong but because the only
off-machine sink was a path under `$HOME` that the production container does not have. Every test
here grades the property that failed: an alert key must have a sender behind it on a machine with
no estate installed, the sender's own state must live in the store rather than in `$HOME`, and the
sender must never raise or block the thing that is already handling a failure when it calls.

NOTHING HERE TOUCHES THE NETWORK. `urllib.request.urlopen` is monkeypatched in every test that
gets past the credential check, and the credential fixtures use obvious fakes.
"""
from __future__ import annotations

import logging

import pytest

from prospector.scheduler import alerts, telegram_sender


@pytest.fixture(autouse=True)
def store_in_tmp(tmp_path, monkeypatch):
    """Point the debounce file at a tmp store. Without this a test writes the REAL debounce file
    and can suppress a genuine founder alert for the next 30 minutes — the same defect that put
    the `PYTEST_CURRENT_TEST` fence on `_load_estate_sender`."""
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "store"))
    return tmp_path


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE-TOKEN-NOT-A-REAL-ONE")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "-100999")


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything reaches the network, rather than silently timing out in CI."""
    def boom(*a, **k):  # pragma: no cover - the point is that it is never called
        raise AssertionError("a test tried to open a real connection")
    monkeypatch.setattr(telegram_sender.urllib.request, "urlopen", boom)


# --- the debounce state lives in the store, which is the whole point of issue #355 -------------

def test_debounce_file_is_under_the_store_not_home(store_in_tmp):
    path = telegram_sender._debounce_path()
    assert str(path).startswith(str(store_in_tmp / "store")), path
    # Stated as its own assertion because "under the store" and "not under $HOME" are different
    # claims, and it is the second one that broke production.
    from pathlib import Path
    assert Path.home() not in path.parents


def test_debounce_holds_inside_the_window_and_releases_after(store_in_tmp):
    assert telegram_sender._debounced("k", 300.0) is False
    assert telegram_sender._debounced("k", 300.0) is True
    # A zero window is "no debounce", not "debounce forever".
    assert telegram_sender._debounced("k", 0.0) is False


def test_debounce_fails_open_when_the_state_file_is_corrupt(store_in_tmp):
    """An unreadable debounce file must never be the reason an alert is withheld."""
    path = telegram_sender._debounce_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")
    assert telegram_sender._debounced("k", 300.0) is False


def test_debounce_is_checked_before_dry_run(store_in_tmp, creds, no_network, caplog):
    """Matches Hermes, so a dry run consumes the window exactly as a real send would.

    If a test could dry-run without consuming the window, the debounce state a test observes
    would differ from the one production reaches, and the test would be grading a fiction.
    """
    assert telegram_sender.send_operator_alert("x", debounce_key="k", dry_run=True) is False
    with caplog.at_level(logging.INFO, logger=telegram_sender.__name__):
        telegram_sender.send_operator_alert("x", debounce_key="k", dry_run=True)
    assert "debounced" in caplog.text


# --- trimming ---------------------------------------------------------------------------------

def test_fit_leaves_a_short_message_exactly_alone():
    assert telegram_sender._fit("hello") == "hello"


def test_fit_trims_on_a_line_boundary():
    text = "\n".join(f"line {i}" for i in range(500))
    out = telegram_sender._fit(text, limit=100)
    assert len(out) <= 100
    assert out.endswith("[trimmed]")
    # Every surviving line is whole: a message cut mid-word reads as corruption.
    assert all(ln in text.split("\n") for ln in out[: -len("\n[trimmed]")].split("\n"))


def test_fit_still_trims_a_single_line_longer_than_the_limit():
    """No newline to cut at. The hard slice must win over returning just the marker."""
    out = telegram_sender._fit("x" * 5000, limit=100)
    assert len(out) <= 100
    assert out.count("x") > 50


def test_a_long_alert_is_sent_within_the_api_limit(store_in_tmp, creds, monkeypatch):
    seen = {}

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        seen["body"] = req.data.decode()
        return _Resp()

    monkeypatch.setattr(telegram_sender.urllib.request, "urlopen", fake_urlopen)
    assert telegram_sender.send_operator_alert("\n".join(["a" * 200] * 100)) is True
    import urllib.parse
    text = urllib.parse.parse_qs(seen["body"])["text"][0]
    assert len(text) <= telegram_sender.TELEGRAM_MAX_CHARS


# --- the never-raises contract ----------------------------------------------------------------

def test_missing_credentials_return_false_and_name_the_missing_variable(
    store_in_tmp, monkeypatch, caplog,
):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "-100999")
    with caplog.at_level(logging.WARNING, logger=telegram_sender.__name__):
        assert telegram_sender.send_operator_alert("something is on fire") is False
    # Naming the variable is the deliverable. "Sink unavailable" is what hid this for two days.
    assert "TELEGRAM_BOT_TOKEN" in caplog.text
    assert "TELEGRAM_HOME_CHANNEL" not in caplog.text


def test_a_network_failure_returns_false_and_never_raises(store_in_tmp, creds, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(telegram_sender.urllib.request, "urlopen", boom)
    assert telegram_sender.send_operator_alert("x") is False


def test_the_token_never_reaches_a_log_line(store_in_tmp, creds, monkeypatch, caplog):
    """urllib puts the URL — and therefore the bot token — into its exception text."""
    token = "123456:FAKE-TOKEN-NOT-A-REAL-ONE"

    def boom(*a, **k):
        raise OSError(f"failed opening https://api.telegram.org/bot{token}/sendMessage")

    monkeypatch.setattr(telegram_sender.urllib.request, "urlopen", boom)
    with caplog.at_level(logging.DEBUG, logger=telegram_sender.__name__):
        telegram_sender.send_operator_alert("x")
    assert token not in caplog.text
    assert "OSError" in caplog.text


def test_an_empty_message_is_not_sent(store_in_tmp, creds, no_network):
    assert telegram_sender.send_operator_alert("   \n  ") is False


def test_configured_grades_both_halves(store_in_tmp, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_HOME_CHANNEL", raising=False)
    assert telegram_sender.configured() is False
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert telegram_sender.configured() is False
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "c")
    assert telegram_sender.configured() is True


# --- the fallback: this is the regression for issue #355 --------------------------------------

@pytest.fixture
def unfenced(monkeypatch):
    """Lift the pytest fence, with the real Hermes loader stubbed absent.

    The fence exists to stop a test importing the founder's live `estate_alert.py` and writing his
    debounce file. Stubbing `_load_estate_sender` removes that risk entirely, so lifting the fence
    here is safe and is the only way to grade the fallback the way production reaches it.
    """
    monkeypatch.setattr(alerts, "_under_pytest", lambda: False)
    monkeypatch.setattr(alerts, "_load_estate_sender", lambda: None)


def test_a_machine_with_no_hermes_still_has_a_sender(unfenced):
    """The exact production shape: the Fly container has no `$HOME/.hermes`.

    Before 2026-08-20 this returned None and the engine logged "sink unavailable" at INFO while
    18 criticals went undelivered.
    """
    send = alerts._load_hermes_sender()
    assert send is telegram_sender.send_operator_alert


def test_hermes_wins_where_it_exists(monkeypatch):
    """On the founder's Mac, Hermes holds the credentials and shares one debounce file with every
    other estate alarm, so it must not be displaced by the fallback."""
    monkeypatch.setattr(alerts, "_under_pytest", lambda: False)
    sentinel = object()
    monkeypatch.setattr(alerts, "_load_estate_sender", lambda: sentinel)
    assert alerts._load_hermes_sender() is sentinel


def test_every_telegram_key_has_a_reachable_sink(unfenced, store_in_tmp, monkeypatch):
    """A rail that cannot go red where a human sees it is not a rail.

    `TELEGRAM_KEYS` is the set of states that will NOT clear without a human. If any of them can
    reach `_telegram_push` and find no sender, that key is decorative. This test fails if a key is
    added to the set on a machine where nothing can carry it.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "-100999")
    sent = []
    monkeypatch.setattr(telegram_sender, "send_operator_alert",
                        lambda text, **kw: sent.append((text, kw)) or True)
    monkeypatch.setattr(alerts, "_load_repo_sender",
                        lambda: telegram_sender.send_operator_alert)
    for key in sorted(alerts.TELEGRAM_KEYS):
        alerts._telegram_push({"key": key, "severity": "critical",
                               "title": f"t-{key}", "message": "m"})
    #: `prospector:<key>:<identity digest>` since 2026-08-21 -- see test_debounce_key_is_namespaced.
    assert [":".join(k["debounce_key"].split(":")[:2]) for _, k in sent] == \
        [f"prospector:{k}" for k in sorted(alerts.TELEGRAM_KEYS)]
    assert all(len(k["debounce_key"].split(":")) == 3 for _, k in sent)


def test_a_key_outside_the_set_is_not_pushed(unfenced, store_in_tmp, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "_load_repo_sender",
                        lambda: lambda text, **kw: sent.append(text) or True)
    alerts._telegram_push({"key": "moat_deferred", "severity": "warning",
                           "title": "t", "message": "m"})
    assert sent == []


def test_no_sender_at_all_is_a_warning_not_an_info(store_in_tmp, caplog):
    """Under pytest `_load_hermes_sender` returns None. That path used to log at INFO, which is
    what let two days of undelivered criticals look like ordinary chatter."""
    with caplog.at_level(logging.DEBUG, logger=alerts.__name__):
        alerts._telegram_push({"key": "moat_blind", "severity": "critical",
                               "title": "t", "message": "m"})
    assert any(r.levelno >= logging.WARNING and "sink unavailable" in r.getMessage()
               for r in caplog.records)
