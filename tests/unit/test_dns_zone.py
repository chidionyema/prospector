"""The DNS drill has to fail on drift, and must not fail on anything else.

`docs/ESTATE_CONTINUITY_PLAN.md` R5 rates the registrar as the one unrecoverable loss on the
register: every exit path in that document ends in "repoint DNS" and none of them said to what.
`scripts/dns_zone.py` is the committed answer, and this is what keeps it honest.

Nothing here touches the network. `live()` is substituted, so a DNS outage cannot turn this red
and a broken checker cannot hide behind one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# `scripts/` is not a package, so the checker has to be imported by path. The insert must happen
# before the import, which is what the noqa below is for.
sys.path.insert(0, str(ROOT / "scripts"))

import dns_zone  # noqa: E402  # isort: skip


APEX = ("mumchimp.com", "A", "193.123.184.22")
DMARC = ("_dmarc.mumchimp.com", "TXT",
         '"v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:support@mumchimp.com;"')
SPF = ("mumchimp.com", "TXT", '"v=spf1 include:_spf.google.com include:spf.mailjet.com ~all"')


def write_zone(tmp_path, records, monkeypatch):
    """Point the module at a throwaway zone directory holding exactly `records`."""
    monkeypatch.setattr(dns_zone, "ZONE_DIR", tmp_path)
    (tmp_path / "estate.zone").write_text(dns_zone.render("mumchimp.com", set(records)))


def test_a_semicolon_inside_a_value_is_not_a_comment(tmp_path, monkeypatch):
    """The regression that shipped once already, on 2026-08-19.

    `committed()` used to strip from the first ';' anywhere on the line. DMARC and SPF values are
    semicolon-separated, so the committed copy of a DMARC record was truncated to `"v=DMARC1` --
    and then read as drift against the live record it was written from, on every run, forever. A
    drill that cries wolf every day is a drill nobody reads on the day it is right.
    """
    write_zone(tmp_path, {DMARC, SPF, APEX}, monkeypatch)
    assert dns_zone.committed("mumchimp.com") == {DMARC, SPF, APEX}


def test_whole_line_comments_are_still_skipped(tmp_path, monkeypatch):
    write_zone(tmp_path, {APEX}, monkeypatch)
    path = tmp_path / "estate.zone"
    path.write_text("; a header line\n;\n" + path.read_text())
    assert dns_zone.committed("mumchimp.com") == {APEX}


def test_check_is_clean_when_live_matches_committed(tmp_path, monkeypatch, capsys):
    write_zone(tmp_path, {APEX, DMARC}, monkeypatch)
    monkeypatch.setattr(dns_zone, "live", lambda z, labels: {APEX, DMARC})
    assert dns_zone.main(["--check", "--zone", "mumchimp.com"]) == 0
    assert "no drift" in capsys.readouterr().out


def test_a_vanished_record_is_drift(tmp_path, monkeypatch, capsys):
    """The failure that matters most: somebody deleted a record and nobody knows."""
    write_zone(tmp_path, {APEX, DMARC}, monkeypatch)
    monkeypatch.setattr(dns_zone, "live", lambda z, labels: {APEX})
    assert dns_zone.main(["--check", "--zone", "mumchimp.com"]) == 1
    out = capsys.readouterr().out
    assert "GONE" in out and "_dmarc.mumchimp.com" in out


def test_an_added_record_is_also_drift(tmp_path, monkeypatch, capsys):
    """Symmetric on purpose. An MX that appeared is someone else's mail server."""
    write_zone(tmp_path, {APEX}, monkeypatch)
    monkeypatch.setattr(dns_zone, "live",
                        lambda z, labels: {APEX, ("mumchimp.com", "MX", "5 evil.example.com.")})
    assert dns_zone.main(["--check", "--zone", "mumchimp.com"]) == 1
    assert "APPEARED" in capsys.readouterr().out


def test_a_ttl_change_is_not_drift():
    """Lowering the TTL before a cutover is in the runbook, so it must not read as a change.

    Both lines below are the same record at different TTLs. If TTL were part of the key, the
    drill would go red on the exact day of a planned migration -- the day it is most likely to
    be dismissed as noise.
    """
    long_ttl = ["mumchimp.com.\t3600\tIN\tA\t193.123.184.22"]
    short_ttl = ["mumchimp.com.\t60\tIN\tA\t193.123.184.22"]
    assert dns_zone.parse(long_ttl) == dns_zone.parse(short_ttl) == {APEX}


def test_no_committed_zone_is_a_failure_not_a_pass(tmp_path, monkeypatch):
    """An absent file must not read as "nothing to compare, all good"."""
    monkeypatch.setattr(dns_zone, "ZONE_DIR", tmp_path)
    monkeypatch.setattr(dns_zone, "live", lambda z, labels: {APEX})
    assert dns_zone.main(["--check", "--zone", "mumchimp.com"]) == 1


def test_cannot_measure_is_its_own_exit_code(tmp_path, monkeypatch):
    """Exit 2, never 0. Same rule as `scripts/fly_estate_probe.py::live_apps`: a probe that
    passes when it could not measure is worse than no probe at all."""
    write_zone(tmp_path, {APEX}, monkeypatch)

    def boom(zone, labels):
        raise RuntimeError("cannot find the authoritative nameservers for mumchimp.com")

    monkeypatch.setattr(dns_zone, "live", boom)
    assert dns_zone.main(["--check", "--zone", "mumchimp.com"]) == 2


def test_live_refuses_to_report_an_empty_zone(monkeypatch):
    monkeypatch.setattr(dns_zone, "nameservers", lambda z: ["ns03.domaincontrol.com"])
    monkeypatch.setattr(dns_zone, "_dig", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="refusing to report an empty zone"):
        dns_zone.live("mumchimp.com", ("",))


def test_the_committed_mumchimp_zone_is_real():
    """The file in the repo must parse, and must carry the records the shop front depends on.

    Without this the whole drill could be green against an empty or malformed file.
    """
    records = dns_zone.committed("mumchimp.com")
    assert APEX in records
    names = {(n, t) for n, t, _ in records}
    for want in (("mumchimp.com", "MX"), ("www.mumchimp.com", "A"),
                 ("api.mumchimp.com", "A"), ("_dmarc.mumchimp.com", "TXT")):
        assert want in names, f"{want} missing from the committed zone"


def test_labels_for_covers_every_committed_name(tmp_path, monkeypatch):
    """A record on a label nobody asks about is a record whose deletion is invisible."""
    write_zone(tmp_path, {APEX, ("mail.mumchimp.com", "CNAME", "ghs.google.com.")}, monkeypatch)
    assert "mail" in dns_zone.labels_for("mumchimp.com")
    assert "" in dns_zone.labels_for("mumchimp.com")
