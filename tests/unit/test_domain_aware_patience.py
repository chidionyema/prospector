"""Test for Domain-Aware Patience (tiered timeouts in retrieval.py)."""
from __future__ import annotations

import urllib.request
from prospector.retrieval import _resolve, _RESOLVE_TIMEOUT, _HIGH_AUTHORITY_TIMEOUT

def test_resolve_uses_longer_timeout_for_high_authority(monkeypatch):
    recorded_timeouts = []
    
    def mock_urlopen(req, timeout):
        recorded_timeouts.append(timeout)
        # Just return something that looks like a response
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            url = req.full_url
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    # 1. High authority domain (list match)
    _resolve("https://www.ft.com/content/abc")
    assert recorded_timeouts[-1] == _HIGH_AUTHORITY_TIMEOUT
    
    # 2. High authority domain (TLD match .gov)
    _resolve("https://data.gov/dataset/xyz")
    assert recorded_timeouts[-1] == _HIGH_AUTHORITY_TIMEOUT
    
    # 3. High authority domain (TLD match .edu)
    _resolve("https://mit.edu/research")
    assert recorded_timeouts[-1] == _HIGH_AUTHORITY_TIMEOUT

    # 4. High authority domain (TLD match .int)
    _resolve("https://who.int/news")
    assert recorded_timeouts[-1] == _HIGH_AUTHORITY_TIMEOUT
    
    # 5. Regular domain
    _resolve("https://example.com/foo")
    assert recorded_timeouts[-1] == _RESOLVE_TIMEOUT
    
    # 6. Manual override
    _resolve("https://example.com/bar", timeout=99.0)
    assert recorded_timeouts[-1] == 99.0
