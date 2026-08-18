"""The console's own log has to be readable from the console.

On 2026-08-18 every tab in the portal rendered blank at once. The cause was an expired session,
but nothing recorded it, and `fly logs --no-tail` returns 100 lines — about four minutes of a
generating daemon. The evidence was gone before the fault was reported.

The Next.js routes write `store/ops/console_events.jsonl`; this view is how an operator reads it
without a shell. These tests pin the reading, not the writing (the writing is pinned in
`store_platform/src/Ops.Console/tests/console-log.test.ts`).
"""
import json

import pytest

from prospector.ops import console_api


class _Cfg:
    """Just enough config for `_store_ops_dir`."""

    def __init__(self, root):
        self.store_dir = str(root)


@pytest.fixture()
def ops_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSPECTOR_STORE_DIR", str(tmp_path))
    d = tmp_path / "ops"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(ops_dir, *rows):
    (ops_dir / "console_events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_a_missing_log_is_not_an_error(ops_dir):
    """No file means nothing has gone wrong, which the panel says in words. It must not raise:
    a read view that throws renders as a broken console, and the console is what is being
    diagnosed at that moment."""
    out = console_api._read_console_log(_Cfg(ops_dir.parent), {})
    assert out["present"] is False
    assert out["rows"] == []
    assert out["total"] == 0


def test_the_newest_line_is_first(ops_dir):
    """The operator is looking for what just happened, not for what happened first."""
    _write(
        ops_dir,
        {"at": "2026-08-18T14:00:00Z", "kind": "read_refused", "view": "money"},
        {"at": "2026-08-18T14:00:01Z", "kind": "read_refused", "view": "queue"},
        {"at": "2026-08-18T14:02:00Z", "kind": "signed_in", "who": "1.2.3.4"},
    )
    out = console_api._read_console_log(_Cfg(ops_dir.parent), {})
    assert [r["kind"] for r in out["rows"]] == ["signed_in", "read_refused", "read_refused"]
    assert out["total"] == 3


def test_the_blank_tab_signature_is_countable(ops_dir):
    """A burst of refusals across several views at one moment IS the expired session. The tally
    is what lets a panel say that without the operator counting rows by eye."""
    _write(
        ops_dir,
        *[
            {"at": "2026-08-18T14:00:00Z", "kind": "read_refused", "view": v,
             "error_kind": "unauthenticated"}
            for v in ("status", "money", "queue", "data", "runs")
        ],
        {"at": "2026-08-18T14:02:00Z", "kind": "signed_in", "who": "1.2.3.4"},
    )
    out = console_api._read_console_log(_Cfg(ops_dir.parent), {})
    assert out["kinds"] == {"read_refused": 5, "signed_in": 1}


def test_a_torn_line_costs_that_line_and_nothing_else(ops_dir):
    """A crash mid-append leaves half a line. Raising on it would hand the operator an empty
    panel in exactly the situation the log exists for."""
    p = ops_dir / "console_events.jsonl"
    p.write_text(
        json.dumps({"at": "2026-08-18T14:00:00Z", "kind": "read_failed", "view": "money"})
        + "\n"
        + '{"at": "2026-08-18T14:00:01Z", "kind": "read_fai'
        + "\n"
        + json.dumps({"at": "2026-08-18T14:00:02Z", "kind": "signed_in"})
        + "\n",
        encoding="utf-8",
    )
    out = console_api._read_console_log(_Cfg(ops_dir.parent), {})
    assert out["unreadable_lines"] == 1
    assert [r["kind"] for r in out["rows"]] == ["signed_in", "read_failed"]


def test_the_limit_bounds_the_answer_but_not_the_count(ops_dir):
    """The panel asks for 50; the operator still needs to know there are 900."""
    _write(ops_dir, *[{"at": "2026-08-18T14:00:00Z", "kind": "read_failed", "view": f"v{i}"}
                      for i in range(120)])
    out = console_api._read_console_log(_Cfg(ops_dir.parent), {"limit": 10})
    assert len(out["rows"]) == 10
    assert out["total"] == 120


def test_the_view_is_reachable_by_name(ops_dir):
    """It has to be in the registry or the console cannot ask for it at all."""
    assert console_api.READS["console_log"] is console_api._read_console_log
