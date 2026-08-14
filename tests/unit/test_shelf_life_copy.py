"""P7: the shelf life the pack advertised was an internal cron stamp.

`reverify_due_at` is `created_at + 30 days` (`run.py:813`). It exists to tell the decay sweep
when to look at a live PASS again (`decay.py:145`, driven from
`scheduler/run_scheduled.py:714`). It was never a statement to a buyer — but the footer printed
it as **"Evidence goes stale after: 2026-08-31T00:41:12.904331+00:00"**, which a buyer reads as
a warranty with a cliff. Buy on day 28 and the document you paid £49.99 for tells you it has
three days left, in a timestamp shaped like a log line.

The capability behind it is real and better than the promise: the sweep re-runs the same hard
gates, and a re-vet that fails one queues the pack for withdrawal
(`decay.py::_queue_unlist`; live receipts in `store/scheduler/pending_unlist.done.jsonl`). A
re-vet that could not look (DEFER) leaves the live PASS untouched by design. So the fix is to
print what the engine actually does, on a date a human can read.
"""
from prospector import dossier as dz
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

DUE = "2026-08-31T00:41:12.904331+00:00"


def _dossier(reverify=DUE):
    checks = [
        CheckResult(
            check_name="pain_reality", verdict=Verdict.SUPPORTED, confidence=0.7,
            rationale="Fleets file the reclaim by hand.", citations=["s1"],
            sources=[Source(source_id="s1", url="https://www.gov.uk/x", text="p")],
        )
    ]
    return Dossier(
        candidate=Candidate(title="A thing", one_liner="It does a thing."),
        checks=checks, decision=Decision.PASS, reason="ok", reverify_due_at=reverify,
        created_at="2026-08-01T00:00:00+00:00",
    )


def test_the_pack_never_tells_a_buyer_their_evidence_expires():
    md = dz.render_markdown(_dossier())
    lowered = md.lower()
    assert "goes stale after" not in lowered
    assert "expires" not in lowered


def test_the_date_is_the_next_check_not_a_deadline_and_is_readable():
    md = dz.render_markdown(_dossier())
    assert "- **Next evidence check:** 2026-08-31" in md
    # The raw ISO stamp is a log line, not a date in a document someone paid for.
    assert DUE not in md


def test_the_footer_states_the_policy_the_engine_actually_runs():
    """Re-check on a cadence, and withdraw from sale on a failed re-check. Both are real:
    `run_decay_sweep` is wired at `scheduler/run_scheduled.py:714`, and `_queue_unlist`
    (`decay.py:83`) has written live rows to `store/scheduler/pending_unlist.done.jsonl`."""
    md = dz.render_markdown(_dossier())
    assert "every 30 days" in md
    assert "not a date this stops being true" in md
    assert "off sale" in md


def test_a_pack_with_no_sla_stamp_says_nothing_about_freshness():
    """Silence beats an invented promise: no stamp, no claim."""
    md = dz.render_markdown(_dossier(reverify=None))
    assert "Next evidence check" not in md
    assert "every 30 days" not in md


def test_an_unparseable_stamp_is_printed_rather_than_dropped():
    assert dz._date_only("whenever") == "whenever"
    assert dz._date_only("2026-08-31") == "2026-08-31"
    assert dz._date_only(None) == ""
