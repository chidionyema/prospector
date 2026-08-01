"""Tests that the kill-log generator strips AI-tell dashes from rendered text.

The kill-log is published on the storefront; em-dashes and en-dashes are the most
universally recognised AI writing signature. They are added by the LLM at generation
time and again by the verdict brain, and they have no purpose other than the model's
own sentence rhythm. The kill-log is supposed to read like a human analyst's
rejection note, not a model output, so the dashes are stripped at publish time.

The same `nodash()` pattern is already used by tools/make_sample_report.py for the
PASS sample report; this test pins the equivalent behaviour for the kill-log.

If the kill-log ever regains em-dashes or en-dashes in published output, this test
fails. That is the gate.
"""
from __future__ import annotations

import json
import importlib
from pathlib import Path

import pytest


EM = "\u2014"
EN = "\u2013"


def _kill_dossier(*, title: str, one_liner: str, reason: str) -> dict:
    """A synthetic kill dossier that cites one source so the citation can resolve."""
    return {
        "gate_fired": "incumbency",
        "reason": (
            f"Gate 'incumbency' fired — {reason} "
            "(0123456789abcdef) end of sentence."
        ),
        "candidate": {
            "title": title,
            "one_liner": one_liner,
        },
        "checks": [
            {
                "sources": [
                    {
                        "source_id": "0123456789abcdef",
                        "url": "https://example.com/evidence",
                    }
                ]
            }
        ],
        "created_at": "2026-07-30T00:00:00+00:00",
    }


# ─────────────────────────────── helpers ─────────────────────────────────────

class TestNodash:
    """`nodash()`: the cosmetic normaliser. Em/en-dash → comma. Compound words kept."""

    def test_em_dash_with_spaces_becomes_comma(self):
        from tools.make_kill_log import nodash
        assert nodash(f"Brand {EM} Description") == "Brand, Description"

    def test_en_dash_with_spaces_becomes_comma(self):
        from tools.make_kill_log import nodash
        assert nodash(f"Brand {EN} Description") == "Brand, Description"

    def test_hyphen_in_compound_word_is_preserved(self):
        # "out-of-hours" must NOT be split; the regex only matches surrounding whitespace.
        from tools.make_kill_log import nodash
        assert nodash("out-of-hours") == "out-of-hours"

    def test_multiple_dashes_all_replaced(self):
        from tools.make_kill_log import nodash
        assert nodash(f"A {EM} B {EM} C") == "A, B, C"

    def test_empty_string(self):
        from tools.make_kill_log import nodash
        assert nodash("") == ""

    def test_none_safe(self):
        from tools.make_kill_log import nodash
        assert nodash(None) == ""

    def test_collapses_internal_whitespace(self):
        from tools.make_kill_log import nodash
        assert nodash("foo   bar  baz") == "foo bar baz"


# ────────────────────────────── _clean_reason unit ──────────────────────────

class TestCleanReasonWithNodash:
    """`_clean_reason` strips engine prefixes, inline citation hashes, and now dashes."""

    def test_strips_gate_fired_prefix(self):
        from tools.make_kill_log import _clean_reason
        result = _clean_reason(
            f"Gate 'incumbency' fired {EM} The passages show things."
        )
        assert not result.startswith("Gate")
        assert result.startswith("The passages")

    def test_strips_inline_hash(self):
        from tools.make_kill_log import _clean_reason
        result = _clean_reason(
            "Tenants get an app (0123456789abcdef) that does the thing."
        )
        assert "(0123456789" not in result
        assert "0123456789abcdef" not in result
        assert "does the thing" in result

    def test_em_dash_in_body_is_replaced(self):
        from tools.make_kill_log import _clean_reason
        result = _clean_reason(
            f"providers {EM} National Testing, UKAS ISO 17025 pendulum testers."
        )
        assert EM not in result
        assert "National Testing" in result
        assert "UKAS ISO 17025" in result
        assert "providers, National Testing" in result


# ─────────────────────────────── build() integration ─────────────────────────

class TestBuildDashes:
    """End-to-end: the published JSON must not contain em/en-dashes anywhere."""

    @pytest.fixture
    def corpus_dir(self, tmp_path, monkeypatch) -> Path:
        """Synthesise a tiny store/dossiers/ with one kill and chdir there."""
        dossiers = tmp_path / "store" / "dossiers"
        dossiers.mkdir(parents=True)
        (dossiers / "01.kill.json").write_text(
            json.dumps(
                _kill_dossier(
                    title=f"AssessAid {EM} the carer's assessment pack",
                    one_liner=f"Out-of-hours tool {EN} between shifts",
                    reason=(
                        "the UK leisure-centre space is already served "
                        f"by multiple nationwide providers {EM} National Testing, "
                        "UKAS ISO 17025 pendulum testers, and Slip Safety "
                        "marketing HSE-endorsed pendulum testing directly at "
                        "leisure centres."
                    ),
                )
            )
        )
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def _build(self):
        from tools import make_kill_log
        # Re-import fresh so the cwd override takes effect on the module's `glob` calls.
        importlib.reload(make_kill_log)
        return make_kill_log.build(limit=10)

    def test_no_em_dash_in_published_entries(self, corpus_dir):
        payload = self._build()
        assert payload["entries"], "fixture produced no entries"
        for entry in payload["entries"]:
            for field in ("title", "oneLiner", "reason"):
                assert EM not in entry[field], (
                    f"em-dash leaked into {field!r}: {entry[field]!r}"
                )

    def test_no_en_dash_in_published_entries(self, corpus_dir):
        payload = self._build()
        assert payload["entries"], "fixture produced no entries"
        for entry in payload["entries"]:
            for field in ("title", "oneLiner", "reason"):
                assert EN not in entry[field], (
                    f"en-dash leaked into {field!r}: {entry[field]!r}"
                )

    def test_url_citation_still_resolves(self, corpus_dir):
        """The dash cleanup must not break citation resolution."""
        payload = self._build()
        assert any(e["citations"] for e in payload["entries"]), (
            "expected at least one resolved citation"
        )

    def test_compound_words_preserved(self, corpus_dir):
        payload = self._build()
        one_liners = [e["oneLiner"] for e in payload["entries"]]
        assert any("out-of-hours" in s.lower() for s in one_liners), (
            "compound word 'out-of-hours' must be preserved"
        )

    def test_reason_factual_content_preserved(self, corpus_dir):
        payload = self._build()
        reason = payload["entries"][0]["reason"]
        # Dash-normalised facts must still be present unchanged.
        assert "National Testing" in reason
        assert "UKAS ISO 17025" in reason
        assert "leisure centres" in reason
