"""The backup must survive a wrong local clock.

On 2026-08-06 03:40 com.prospector.backup died on its first call with
RequestTimeTooSkewed and, because launchd's StartCalendarInterval does not
retry, stayed dead. botocore does not handle this for us — measured, not
assumed:

    grep -rl RequestTimeTooSkewed .venv/.../botocore/   -> 0 files
    'RequestTimeTooSkewed' in botocore/data/_retry.json -> False

so there is no retry rule and no clock-correction hook in botocore 1.43.30 in
either retry mode. These tests hold the correction we added in its place.

They are deliberately offline: no credentials, no network, no live clock
skew (see tests/test_suite_is_machine_independent.py). The live end-to-end
proof against the real R2 endpoint is recorded in the commit message.
"""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))

import backup_store  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_botocore_clock():
    """Every test here rebinds a botocore global; put it back or the whole suite drifts."""
    import botocore.auth
    import botocore.compat

    original = botocore.auth.get_current_datetime
    yield
    botocore.auth.get_current_datetime = original
    assert botocore.auth.get_current_datetime is botocore.compat.get_current_datetime


def _sign_and_read_amz_date(offset: float | None) -> str:
    """Sign a throwaway request and return the X-Amz-Date the signer actually used.

    This reads the header off a real SigV4Auth run rather than asserting on our
    own helper, so a patch that fails to reach botocore cannot pass.
    """
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    if offset is not None:
        backup_store._install_clock_offset(offset)
    request = AWSRequest(method="GET", url="https://example.r2.cloudflarestorage.com/b")
    SigV4Auth(Credentials("ak", "sk"), "s3", "auto").add_auth(request)
    return request.headers["X-Amz-Date"]


def _parse(stamp: str) -> datetime.datetime:
    return datetime.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(
        tzinfo=datetime.timezone.utc
    )


def test_installing_an_offset_moves_the_real_signature_timestamp():
    """The rebind must reach botocore.auth, not just our own module."""
    unpatched = _parse(_sign_and_read_amz_date(None))
    patched = _parse(_sign_and_read_amz_date(3600.0))
    drift = (patched - unpatched).total_seconds()
    # Non-vacuous: if _install_clock_offset were a no-op, drift would be ~0.
    assert 3590 <= drift <= 3610, f"offset did not reach the signer (drift={drift}s)"


def test_patching_botocore_compat_instead_would_not_work():
    """Pins WHY we rebind botocore.auth: auth.py imported the name at import time.

    If a future botocore switched to calling botocore.compat.get_current_datetime
    through the module, this test fails and tells the reader the binding moved,
    rather than the backup silently losing its clock correction.
    """
    import botocore.auth
    import botocore.compat

    assert "get_current_datetime" in vars(botocore.auth), (
        "botocore.auth no longer holds its own binding — _install_clock_offset "
        "must be repointed at wherever the signer now reads the clock"
    )
    assert botocore.auth.get_current_datetime is botocore.compat.get_current_datetime


def test_signing_clock_and_measuring_clock_are_the_same_source():
    """A fast system clock must be fully absorbed by the measured offset.

    This is the defect the live probe caught: the signer read datetime.now()
    while _server_time_offset read time.time(). Those agree on a real machine,
    so the bug was invisible in production and only appeared under test — where
    a stale offset survived a later correction.
    """
    fake_skew = 3600.0
    real_time = time.time
    time.time = lambda: real_time() + fake_skew
    try:
        backup_store._install_clock_offset(-fake_skew)
        signed = _parse(_sign_and_read_amz_date(None))
    finally:
        time.time = real_time
    # Signing with (broken system clock - fake_skew) must land back on true now.
    drift = abs((signed - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    assert drift < 30, f"offset is not applied to the same clock it was measured against ({drift}s)"


def test_correct_clock_if_skewed_never_leaves_a_stale_offset(monkeypatch):
    """A small measured skew must still be installed, overwriting any prior offset.

    Returning early without installing made the function's effect depend on what
    had run before it. That is how the live probe ended up signing with a stale
    +3600s after a correction that reported 'clock is fine'.
    """
    monkeypatch.setattr(backup_store, "_server_time_offset", lambda endpoint: 2.0)
    backup_store._install_clock_offset(3600.0)  # a stale, wrong offset is in force
    assert backup_store._correct_clock_if_skewed("https://x") is None  # under tolerance
    signed = _parse(_sign_and_read_amz_date(None))
    drift = abs((signed - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    assert drift < 30, f"the stale +3600s offset survived the correction ({drift}s)"


def test_correct_clock_if_skewed_reports_only_a_real_skew(monkeypatch):
    monkeypatch.setattr(backup_store, "_server_time_offset", lambda endpoint: 2.0)
    assert backup_store._correct_clock_if_skewed("https://x") is None
    monkeypatch.setattr(backup_store, "_server_time_offset", lambda endpoint: 4000.0)
    assert backup_store._correct_clock_if_skewed("https://x") == 4000.0


def test_unmeasurable_clock_is_not_treated_as_a_correction(monkeypatch):
    """No Date header (offline, DNS down) must not install a zero offset silently."""
    monkeypatch.setattr(backup_store, "_server_time_offset", lambda endpoint: None)
    assert backup_store._correct_clock_if_skewed("https://x") is None


def _client_error(code: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code}}, "ListObjectsV2")


def test_retry_on_skew_retries_once_and_succeeds(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setattr(backup_store, "_server_time_offset", lambda endpoint: -3600.0)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise _client_error("RequestTimeTooSkewed")
        return "ok"

    assert backup_store._retry_on_skew(flaky) == "ok"
    assert len(calls) == 2, "must retry exactly once, not loop"


def test_retry_on_skew_does_not_swallow_other_errors(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    calls = []

    def denied():
        calls.append(1)
        raise _client_error("AccessDenied")

    with pytest.raises(Exception) as excinfo:
        backup_store._retry_on_skew(denied)
    assert "AccessDenied" in str(excinfo.value)
    assert len(calls) == 1, "a non-skew error must not be retried"


def test_retry_on_skew_gives_up_when_the_clock_is_unmeasurable(monkeypatch):
    """If we cannot learn the true time, re-raise the original error.

    Retrying with the same bad signature would just fail again and turn one
    clear failure into two confusing ones.
    """
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setattr(backup_store, "_server_time_offset", lambda endpoint: None)
    calls = []

    def skewed():
        calls.append(1)
        raise _client_error("RequestTimeTooSkewed")

    with pytest.raises(Exception) as excinfo:
        backup_store._retry_on_skew(skewed)
    assert "RequestTimeTooSkewed" in str(excinfo.value)
    assert len(calls) == 1


def test_server_time_offset_parses_the_date_header(monkeypatch):
    """Offset comes from the HTTP Date header, including on an error response."""
    import email.utils
    import urllib.request

    class _Resp:
        headers = {"Date": email.utils.formatdate(time.time() + 1234, usegmt=True)}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10: _Resp())
    offset = backup_store._server_time_offset("https://x")
    assert offset is not None and 1224 <= offset <= 1244, offset


def test_server_time_offset_uses_the_date_from_an_http_error(monkeypatch):
    """An unsigned HEAD often 400s; the Date header on that response is still valid."""
    import email.utils
    import urllib.error
    import urllib.request

    headers = {"Date": email.utils.formatdate(time.time() + 500, usegmt=True)}

    def _raise(req, timeout=10):
        raise urllib.error.HTTPError("https://x", 400, "Bad Request", headers, None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    offset = backup_store._server_time_offset("https://x")
    assert offset is not None and 490 <= offset <= 510, offset
