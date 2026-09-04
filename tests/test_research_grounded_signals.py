"""The tick generates from researched evidence, and never stops when it cannot.

These grade behaviour through a fake connection: the query the adapter sends, the text it
renders, and what it does when the ledger is unreachable, empty or already used. No live
Postgres, no model call.
"""

from __future__ import annotations

import json

import pytest

from prospector import research_intake


class _Cursor:
    def __init__(self, rows, fail=None):
        self._rows, self._fail = rows, fail
        self.executed = []

    def execute(self, sql, params=None):
        if self._fail:
            raise self._fail
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, rows, fail=None):
        self.cursor_obj = _Cursor(rows, fail)

    def cursor(self):
        return self.cursor_obj


def _row(
    request_id="r1",
    subject="haulage software",
    statement="Operators pay 400 a month",
    sources=None,
    confidence="corroborated",
):
    if sources is None:
        sources = [{"url": "https://example.gov.uk/a", "snapshot_id": "s1"}]
    return (request_id, subject, statement, sources, confidence)


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path / "store"))
    for k in (
        "RESEARCH_LANE",
        "RESEARCH_CLAIM_LIMIT",
        "RESEARCH_MAX_AGE_DAYS",
        "RESEARCH_PG_HOST",
        "RESEARCH_PG_PASSWORD",
    ):
        monkeypatch.delenv(k, raising=False)


def test_the_signal_carries_the_market_the_claims_and_their_sources():
    conn = _Conn(
        [
            _row(),
            _row(
                statement="Two suppliers exist",
                sources=[{"url": "https://example.com/b"}],
                confidence=None,
            ),
        ]
    )
    request_id, text = research_intake.next_signal(conn)
    assert request_id == "r1"
    assert "haulage software" in text
    assert "Operators pay 400 a month" in text
    assert "https://example.gov.uk/a" in text
    assert "https://example.com/b" in text
    # The question is what turns evidence into an idea; without it this is a reading list.
    assert "opportunities" in text.lower()


def test_only_the_asked_lane_and_only_recent_requests_are_queried(monkeypatch):
    monkeypatch.setenv("RESEARCH_LANE", "market-demand")
    monkeypatch.setenv("RESEARCH_MAX_AGE_DAYS", "3")
    conn = _Conn([_row()])
    research_intake.next_signal(conn)
    sql, params = conn.cursor_obj.executed[0]
    assert "status = 'admitted'" in sql
    assert params["lane"] == "market-demand"
    assert params["max_age_days"] == "3"


def test_one_signal_is_one_market_never_two_mixed():
    conn = _Conn(
        [_row(request_id="r1", subject="market one"), _row(request_id="r2", subject="market two")]
    )
    _, text = research_intake.next_signal(conn)
    assert "market one" in text
    assert "market two" not in text


def test_a_market_already_generated_from_is_not_generated_from_twice():
    research_intake.mark_consumed("r1")
    conn = _Conn([_row(request_id="r1")])
    assert research_intake.next_signal(conn) is None

    conn = _Conn([_row(request_id="r1"), _row(request_id="r2", subject="a second market")])
    request_id, text = research_intake.next_signal(conn)
    assert request_id == "r2"
    assert "a second market" in text


def test_claims_are_capped_so_the_market_and_the_question_survive_the_prompt(monkeypatch):
    monkeypatch.setenv("RESEARCH_CLAIM_LIMIT", "2")
    conn = _Conn([_row(statement=f"claim {i}") for i in range(6)])
    _, text = research_intake.next_signal(conn)
    assert "claim 0" in text and "claim 1" in text
    assert "claim 2" not in text


def test_sources_stored_as_json_text_or_a_bare_url_still_reach_the_signal():
    conn = _Conn([_row(sources=json.dumps([{"url": "https://example.org/c"}]))])
    _, text = research_intake.next_signal(conn)
    assert "https://example.org/c" in text

    research_intake.mark_consumed("r1")
    conn = _Conn([_row(request_id="r2", sources=["https://example.org/d"])])
    _, text = research_intake.next_signal(conn)
    assert "https://example.org/d" in text


def test_a_claim_whose_sources_are_unparseable_still_carries_its_statement():
    conn = _Conn([_row(sources=12)])
    _, text = research_intake.next_signal(conn)
    assert "Operators pay 400 a month" in text
    assert "none recorded" in text


def test_no_read_side_configured_means_blue_sky_not_an_exception(caplog):
    assert research_intake.signal_text_or_empty() == ""


def test_an_unreachable_ledger_does_not_stop_the_tick(monkeypatch, caplog):
    monkeypatch.setenv("RESEARCH_PG_HOST", "db.invalid")
    monkeypatch.setenv("RESEARCH_PG_PASSWORD", "not-a-real-password")

    class _Boom:
        @staticmethod
        def connect(*a, **k):
            raise OSError("connection refused")

    monkeypatch.setitem(__import__("sys").modules, "psycopg", _Boom)
    with caplog.at_level("ERROR"):
        assert research_intake.signal_text_or_empty() == ""
    # Degrading silently is how this would rot back to blue-sky unnoticed.
    assert "ledger unreadable" in caplog.text


def test_the_password_never_reaches_the_log(monkeypatch, caplog):
    monkeypatch.setenv("RESEARCH_PG_HOST", "db.invalid")
    monkeypatch.setenv("RESEARCH_PG_PASSWORD", "swordfish-1234")

    class _Boom:
        @staticmethod
        def connect(*a, **k):
            raise OSError("connection refused")

    monkeypatch.setitem(__import__("sys").modules, "psycopg", _Boom)
    with caplog.at_level("DEBUG"):
        research_intake.signal_text_or_empty()
    assert "swordfish-1234" not in caplog.text


def test_the_scheduler_tick_asks_for_a_researched_signal():
    """The wiring itself: the tick must pass the adapter's text, not an empty string.

    Read as source rather than run, because running one tick means a model call. The call site
    is the whole change -- an adapter nothing calls is the defect this closes, arriving again.
    """
    import inspect

    from prospector.scheduler import run_scheduled

    src = inspect.getsource(run_scheduled)
    i = src.index("dossiers = run_signal(")
    call = src[i : i + 60]
    assert 'run_signal("")' not in call, "the tick is still generating blue-sky"
    assert "run_signal(signal" in call
