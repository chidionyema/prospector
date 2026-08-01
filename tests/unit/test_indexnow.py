"""IndexNow submission: it must be silent when unconfigured and harmless when it fails.

The reason this file leans so hard on the failure paths: `submit` is called from inside
`EngineBridge._update_catalog`, immediately after a pack has been successfully published. Any
exception escaping it would turn a completed publish into a reported failure, and the engine
would then republish a pack that is already live. So "never raises" is the property under test,
not a nicety.
"""

import pytest

from prospector import indexnow


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("INDEXNOW_KEY", "STORE_SITE_URL", "NEXT_PUBLIC_SITE_URL"):
        monkeypatch.delenv(var, raising=False)


def configure(monkeypatch, key="k123", site="https://mumchimp.com"):
    monkeypatch.setenv("INDEXNOW_KEY", key)
    monkeypatch.setenv("STORE_SITE_URL", site)


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def capture_post(monkeypatch, status_code=200):
    """Replace requests.post and record what would have been sent."""
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["url"] = url
        sent["payload"] = json
        return _Response(status_code)

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


def test_unconfigured_is_a_silent_no_op(monkeypatch):
    # The state every developer machine and CI runner is in. It must not error, and it must not
    # reach the network — so no `requests.post` is patched here: a call would be a real request.
    assert indexnow.is_configured() is False
    assert indexnow.submit(["https://mumchimp.com/pack/abc"]) is False
    assert indexnow.submit_pack("abc") is False


def test_key_without_site_url_does_not_submit(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "k123")
    assert indexnow.is_configured() is False
    assert indexnow.submit_pack("abc") is False


def test_malformed_site_url_is_refused(monkeypatch):
    # A bare hostname has no scheme, so it cannot be compared against submitted URLs and would
    # produce a `keyLocation` no engine can fetch. Refuse rather than submit something broken.
    monkeypatch.setenv("INDEXNOW_KEY", "k123")
    monkeypatch.setenv("STORE_SITE_URL", "mumchimp.com")
    assert indexnow.is_configured() is False


def test_submits_the_pack_url_and_the_catalogue(monkeypatch):
    configure(monkeypatch)
    sent = capture_post(monkeypatch)

    assert indexnow.submit_pack("fbd10d6bdfcd5e31") is True
    assert sent["url"] == indexnow.ENDPOINT
    assert sent["payload"] == {
        "host": "mumchimp.com",
        "key": "k123",
        # The ownership proof the web app serves at this exact path — see
        # Store.Web/src/pages/indexnow-key.txt.tsx.
        "keyLocation": "https://mumchimp.com/indexnow-key.txt",
        "urlList": [
            "https://mumchimp.com/pack/fbd10d6bdfcd5e31",
            "https://mumchimp.com",
        ],
    }


def test_trailing_slash_on_site_url_does_not_double_up(monkeypatch):
    configure(monkeypatch, site="https://mumchimp.com/")
    sent = capture_post(monkeypatch)

    indexnow.submit_pack("abc")
    assert sent["payload"]["urlList"][0] == "https://mumchimp.com/pack/abc"
    assert sent["payload"]["keyLocation"] == "https://mumchimp.com/indexnow-key.txt"


def test_off_host_urls_are_dropped_not_submitted(monkeypatch):
    # The endpoint rejects the whole batch if any URL is on another host. Filtering keeps the
    # valid ones rather than losing every URL to one bad entry.
    configure(monkeypatch)
    sent = capture_post(monkeypatch)

    assert indexnow.submit(
        ["https://mumchimp.com/pack/a", "https://example.com/pack/b"]
    ) is True
    assert sent["payload"]["urlList"] == ["https://mumchimp.com/pack/a"]


def test_a_batch_of_only_off_host_urls_sends_nothing(monkeypatch):
    configure(monkeypatch)
    sent = capture_post(monkeypatch)

    assert indexnow.submit(["https://example.com/pack/b"]) is False
    assert sent == {}


def test_202_counts_as_accepted(monkeypatch):
    # "Accepted, key validation pending" — we did our part.
    configure(monkeypatch)
    capture_post(monkeypatch, status_code=202)
    assert indexnow.submit_pack("abc") is True


def test_403_is_reported_as_failure_not_raised(monkeypatch):
    # 403 means the served key file and INDEXNOW_KEY disagree. Worth logging loudly, but the
    # publish it rides on has already succeeded.
    configure(monkeypatch)
    capture_post(monkeypatch, status_code=403)
    assert indexnow.submit_pack("abc") is False


def test_a_network_failure_never_escapes(monkeypatch):
    # THE property. If this raises, a published pack is reported as unpublished and republished.
    configure(monkeypatch)

    def exploding_post(*args, **kwargs):
        raise ConnectionError("dns is down")

    import requests

    monkeypatch.setattr(requests, "post", exploding_post)
    assert indexnow.submit_pack("abc") is False
