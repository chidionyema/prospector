"""The unlist queue: nothing is dropped, and nothing is retired that was not done.

`tools/unlist_killed.py` drains the queue `decay._queue_unlist` writes to when a re-vet turns
a published PASS into a KILL. Losing an entry here means a pack the engine has killed stays on
sale — the exact condition found by hand on 2026-08-06, when 4 re-vetted KILLs were still
selling because nothing drained this file at all.

The queue was then emptied with `QUEUE.write_text("")` (§23.6), which loses every entry that
arrived during the `fly ssh` round-trip. These tests pin the replacement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import unlist_killed as uk  # noqa: E402

from prospector import paths  # noqa: E402
from prospector.jsonl_atomic import append_jsonl, read_jsonl  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.STORE_ROOT_ENV, str(tmp_path))
    (tmp_path / "scheduler").mkdir(parents=True)
    return tmp_path


def _entry(cid: str) -> dict:
    return {"candidate_id": cid, "title": f"pack {cid}", "gate_fired": "value_durability"}


def test_commit_retires_what_was_processed(store):
    for cid in ("aaa", "bbb"):
        append_jsonl(uk._queue(), _entry(cid))

    entries = uk._read_queue()
    assert uk._commit(entries) == 2

    assert read_jsonl(uk._queue()) == []
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa", "bbb"]


def test_an_entry_queued_during_the_unlist_survives_the_commit(store, capsys):
    """The lost update, in the order it actually happens.

    `_read_queue` → the API round-trip (decay appends here) → `_commit`. The new entry was never
    processed, so it must still be queued afterwards; it must NOT appear in the done log.
    """
    append_jsonl(uk._queue(), _entry("aaa"))
    entries = uk._read_queue()

    append_jsonl(uk._queue(), _entry("late"))     # decay.py, mid-round-trip

    uk._commit(entries)

    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["late"]
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa"]
    assert "1 entry(s) arrived while unlisting" in capsys.readouterr().out


def test_the_old_truncating_commit_would_have_dropped_it(store):
    """Same sequence, old code. Kept so the fix is measured against a demonstrated loss."""
    append_jsonl(uk._queue(), _entry("aaa"))
    uk._read_queue()
    append_jsonl(uk._queue(), _entry("late"))
    uk._queue().write_text("", encoding="utf-8")

    assert read_jsonl(uk._queue()) == []          # "late" is gone, unprocessed and untraceable


def test_read_queue_does_not_empty_the_queue(store):
    """The unlist only succeeds after the API confirms it. A read that consumed the queue
    would lose everything whenever the API was unreachable."""
    append_jsonl(uk._queue(), _entry("aaa"))
    assert len(uk._read_queue()) == 1
    assert len(uk._read_queue()) == 1


# ---------------------------------------------------------------------------
# The actuator. Patched at the transport, never at `_unlist_one` — stubbing the function
# under test would leave the request itself (route, key header, payload, reason) unpinned,
# and the route is the whole reason this file changed: the previous actuator shelled out to
# a `sqlite3` binary that had stopped existing in the production image.
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def api(monkeypatch):
    """Give `main()` credentials and a fake transport; record every request it makes."""
    monkeypatch.setattr(uk, "_load_dotenv", lambda: None)   # never read the real .env
    monkeypatch.setenv("STORE_INTERNAL_API_KEY", "test-key")
    monkeypatch.setenv("STORE_API_URL", "https://api.test")

    calls: list[dict] = []
    responses: list = []

    def _patch(self, url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return responses.pop(0) if responses else _Resp(payload={"isListed": False})

    monkeypatch.setattr(uk.requests.Session, "patch", _patch)
    return type("Api", (), {"calls": calls, "responses": responses})


def test_a_successful_run_retires_the_queue(store, monkeypatch, api, capsys):
    append_jsonl(uk._queue(), _entry("aaa"))
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 0
    assert read_jsonl(uk._queue()) == []
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa"]

    assert len(api.calls) == 1
    call = api.calls[0]
    assert call["url"] == "https://api.test/internal/catalog/aaa/listing"
    assert call["headers"]["X-Internal-Key"] == "test-key"
    # Safe in one direction only: this script may never list a pack.
    assert call["json"]["isListed"] is False
    # The API rejects an empty reason, and an unexplained withdrawal is unauditable anyway.
    assert "value_durability" in call["json"]["reason"]


def test_a_200_that_did_not_actually_unlist_is_a_failure(store, monkeypatch, api):
    """The old script's equivalent bug: it read back `aaa|1` and had to notice. A 200 is the
    API saying it heard us, not that the row moved — so the body is what counts."""
    append_jsonl(uk._queue(), _entry("aaa"))
    api.responses.append(_Resp(payload={"isListed": True}))
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 1
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["aaa"]
    assert not uk._done().exists()


def test_a_failed_run_leaves_the_queue_intact(store, monkeypatch, api, capsys):
    """An HTTP failure must leave the entry queued: a pack the engine has killed is still
    taking money until this succeeds, so the only safe default is to try again."""
    append_jsonl(uk._queue(), _entry("aaa"))
    api.responses.append(_Resp(status=503, text="upstream unavailable"))
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 1
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["aaa"]
    assert not uk._done().exists()
    assert "still queued and possibly still selling" in capsys.readouterr().err


def test_a_404_retires_the_entry(store, monkeypatch, api):
    """Not in the catalogue means nothing is selling, which is the state we wanted. Leaving
    it queued would make the drain permanently red and hide the entries that do matter."""
    append_jsonl(uk._queue(), _entry("aaa"))
    api.responses.append(_Resp(status=404, text="not found"))
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 0
    assert read_jsonl(uk._queue()) == []
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa"]


def test_one_failure_does_not_strand_its_neighbours(store, monkeypatch, api):
    """The 2026-08-09 queue had 8 entries. A single bad row must not hold the other 7 on sale."""
    for cid in ("aaa", "bbb", "ccc"):
        append_jsonl(uk._queue(), _entry(cid))
    api.responses.extend([_Resp(payload={"isListed": False}),
                          _Resp(status=500, text="boom"),
                          _Resp(payload={"isListed": False})])
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 1
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["bbb"]
    assert [e["candidate_id"] for e in read_jsonl(uk._done())] == ["aaa", "ccc"]


def test_a_missing_key_fails_loud_and_changes_nothing(store, monkeypatch, api):
    """Silently doing nothing is exactly how the sqlite3 breakage survived for days."""
    append_jsonl(uk._queue(), _entry("aaa"))
    monkeypatch.delenv("STORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])

    assert uk.main() == 1
    assert api.calls == []
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["aaa"]


def test_dry_run_touches_nothing(store, monkeypatch, api, capsys):
    append_jsonl(uk._queue(), _entry("aaa"))
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py", "--dry-run"])

    assert uk.main() == 0
    assert api.calls == [], "--dry-run reached the live catalogue"
    assert [e["candidate_id"] for e in read_jsonl(uk._queue())] == ["aaa"]
    assert "would unlist aaa" in capsys.readouterr().out


def test_an_empty_queue_is_not_an_error(store, monkeypatch, api):
    monkeypatch.setattr(sys, "argv", ["unlist_killed.py"])
    assert uk.main() == 0
    assert api.calls == []
