"""Two defects that manufactured dead citations, pinned.

Both were found 2026-08-09 while 12 packs sat unsellable on `citation_urls` errors. Link rot
was real and dominant (12 of 14 citations were genuinely 404 on GET), which is exactly why
these two false positives mattered: they were indistinguishable from the real thing in the
report, so the gate's output could not be trusted as an audit trail.

  1. Both URL extractors excluded ')' from the character class, truncating any URL that
     legitimately contains one.
  2. `_probe_url` sent HEAD and fell back to GET only on 405/501, so a server answering HEAD
     with 404 condemned a live page -- into a 7-day cache.
"""
from __future__ import annotations

from unittest.mock import patch

from prospector import pack_linter
from prospector.copy_lint import extract_urls

# ---------------------------------------------------------------------------
# 1. Extraction
# ---------------------------------------------------------------------------

def test_url_with_balanced_parens_is_not_truncated():
    """The measured case: the stored form 404s, the full form 200s."""
    real = "https://en.wikipedia.org/wiki/Late_Payment_of_Commercial_Debts_(Interest)_Act_1998"
    assert extract_urls(f"see {real} for the statute") == [real]


def test_unmatched_closing_paren_is_still_dropped():
    """The reason the exclusion existed in the first place must keep working."""
    assert extract_urls("(see https://example.com/a)") == ["https://example.com/a"]
    assert extract_urls("(see https://example.com/a).") == ["https://example.com/a"]


def test_sentence_punctuation_trimmed_after_paren():
    assert extract_urls("cited at https://example.com/x," ) == ["https://example.com/x"]
    assert extract_urls("cited at https://example.com/x.") == ["https://example.com/x"]


def test_trailing_slash_is_preserved():
    """Never stripped blindly -- some servers require it. The PROBE toggles it instead."""
    assert extract_urls("https://example.com/a/") == ["https://example.com/a/"]


def test_bare_scheme_is_not_a_url():
    assert extract_urls("https:// and http://") == []


def test_both_extractors_are_the_same_function():
    """A second private copy of this regex is how the two halves of the engine agreed on a
    wrong string: retrieval stored the truncated URL, the linter re-derived the same truncation
    and reported it dead."""
    import inspect

    from prospector import retrieval
    src = inspect.getsource(retrieval._LLMSearchProvider.search)
    assert "extract_urls(text)" in src
    assert "re.findall(r'https?://" not in src


# ---------------------------------------------------------------------------
# 2. Probe
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status): self.status_code = status
    def close(self): pass


def _probe_with(head_status, get_status, alt_status=None):
    """Drive _probe_url with scripted transport results; returns (status, note)."""
    calls = []

    def fake_head(url, **kw):
        calls.append(("head", url))
        return _Resp(head_status)

    def fake_get(url, **kw):
        calls.append(("get", url))
        is_alt = len([c for c in calls if c[0] == "get"]) > 1
        return _Resp(alt_status if is_alt else get_status)

    with patch.object(pack_linter.requests, "head", fake_head), \
         patch.object(pack_linter.requests, "get", fake_get):
        return pack_linter._probe_url("https://example.com/page", 1.0), calls


def test_head_404_with_get_200_is_not_dead():
    """The measured case: mcneilsafetyconsulting.com answers HEAD 404 and GET 200."""
    (status, note), calls = _probe_with(head_status=404, get_status=200)
    assert status == 200
    assert status not in pack_linter._DEAD_STATUSES
    assert [c[0] for c in calls] == ["head", "get"]


def test_dead_on_both_head_and_get_stays_dead():
    """Link rot is the common case and must survive the fix."""
    (status, _), _ = _probe_with(head_status=404, get_status=404, alt_status=404)
    assert status in pack_linter._DEAD_STATUSES


def test_slash_variant_alive_downgrades_to_a_repairable_note():
    (status, note), calls = _probe_with(head_status=404, get_status=404, alt_status=200)
    assert status in pack_linter._DEAD_STATUSES
    assert note.startswith(pack_linter._ALT_ALIVE_NOTE)
    assert calls[-1] == ("get", "https://example.com/page/")


def test_alive_url_costs_exactly_one_request():
    """The GET confirmation must not double the cost of the healthy path."""
    (status, _), calls = _probe_with(head_status=200, get_status=200)
    assert status == 200
    assert calls == [("head", "https://example.com/page")]


def test_unreachable_get_does_not_confirm_a_head_404():
    """If we refuse to trust the HEAD, we cannot then trust it when the GET fails."""
    def fake_head(url, **kw):
        return _Resp(404)

    def fake_get(url, **kw):
        raise pack_linter.requests.RequestException("boom")

    with patch.object(pack_linter.requests, "head", fake_head), \
         patch.object(pack_linter.requests, "get", fake_get):
        status, note = pack_linter._probe_url("https://example.com/page", 1.0)
    assert status is None  # unreachable -> warning, never an error
    assert note == "RequestException"


# ---------------------------------------------------------------------------
# 3. The gate's use of both
# ---------------------------------------------------------------------------

def test_repairable_url_warns_instead_of_blocking(tmp_path):
    """Our own stored string being wrong must not strand a pack whose SOURCE is live."""
    with patch.object(pack_linter, "_probe_url",
                      return_value=(404, pack_linter._ALT_ALIVE_NOTE + "https://x.test/a")):
        problems, n = pack_linter.check_urls({"copy": "see https://x.test/a/"},
                                             cache_path=tmp_path / "c.json")
    assert n == 1
    assert [p["severity"] for p in problems] == ["warning"]
    assert "the source is live" in problems[0]["detail"]


def test_genuinely_dead_url_still_errors(tmp_path):
    with patch.object(pack_linter, "_probe_url", return_value=(404, "")):
        problems, _ = pack_linter.check_urls({"copy": "see https://x.test/a"},
                                             cache_path=tmp_path / "c.json")
    assert [p["severity"] for p in problems] == ["error"]


def test_cache_key_is_versioned(tmp_path):
    """A 7-day TTL over pre-fix verdicts would make the fix look inert on exactly the packs
    it unblocks -- store/lint_url_cache.json really did hold {'status': 404} for a live page."""
    import json
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({
        "https://x.test/a": {"status": 404, "note": "", "ts": 9_999_999_999},
    }))
    with patch.object(pack_linter, "_probe_url", return_value=(200, "")) as probe:
        problems, _ = pack_linter.check_urls({"copy": "see https://x.test/a"},
                                             cache_path=cache)
    assert probe.called, "the stale unversioned entry must not be honoured"
    assert problems == []
