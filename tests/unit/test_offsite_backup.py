"""The offsite-backup automation, proved on the BROKEN state as well as the clean one.

A backup monitor that has only ever been seen to say "fresh" is not known to work
(`docs/OPS_AUTOMATION_PRINCIPLES.md` R4). The dangerous failure is specific and it is tested
here: a storage outage must NOT read as "no backup exists", and "no backup exists" must NOT
read as clean.

No network. The storage client is a stub, and the sources are throwaway files.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ops.automations.offsite_backup import (
    EXIT_FINDINGS,
    EXIT_OK,
    EXIT_UNKNOWN,
    CannotEstablish,
    Source,
    _expand,
    check,
    load_declaration,
    main,
    run,
    take_backup,
    verify_copy,
)

SOURCE = Source(name="money-db", key="money-db/store.db", fetch=["true"], verify="sqlite")


class FakeStorage:
    """An S3-compatible client, as much of one as the engine touches."""

    def __init__(self, objects: list[dict] | None = None, *, list_raises: bool = False):
        self.objects = objects or []
        self.list_raises = list_raises
        self.uploaded: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def get_paginator(self, _name: str):
        outer = self

        class _Paginator:
            def paginate(self, Bucket: str, Prefix: str):  # noqa: N803 - boto3's own casing
                if outer.list_raises:
                    raise RuntimeError("storage endpoint returned 503")
                yield {"Contents": [o for o in outer.objects if o["Key"].startswith(Prefix)]}

        return _Paginator()

    def upload_file(self, local: str, bucket: str, key: str, ExtraArgs=None):  # noqa: N803
        self.uploaded.append((local, key))

    def delete_object(self, Bucket: str, Key: str):  # noqa: N803
        self.deleted.append(Key)


def _obj(key: str, age_hours: float, size: int = 1024) -> dict:
    return {
        "Key": key,
        "Size": size,
        "LastModified": datetime.now(timezone.utc) - timedelta(hours=age_hours),
    }


def _sqlite_file(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.execute("create table orders (id integer primary key)")
    connection.execute("insert into orders (id) values (1)")
    connection.commit()
    connection.close()
    return path


def _declaration(tmp_path: Path, **overrides) -> Path:
    body = {
        "storage": {
            "endpoint": "https://example.invalid",
            "access_key_env": "TEST_KEY_ID",
            "secret_key_env": "TEST_KEY_SECRET",
            "bucket": "backup-bucket",
            "prefix": "offsite/",
        },
        "max_age_hours": 24,
        "sources": [{"name": "money-db", "key": "money-db/store.db", "fetch": ["true"]}],
    }
    body.update(overrides)
    path = tmp_path / "decl.yaml"
    path.write_text(json.dumps(body), encoding="utf-8")  # JSON is valid YAML
    return path


# --- the monitor fires on the broken state -----------------------------------------------

def test_no_copy_at_all_is_a_finding():
    report = check(FakeStorage([]), "backup-bucket", "offsite/", [SOURCE])

    assert report[0]["fresh"] is False
    assert "no offsite copy exists at all" in report[0]["what"]


def test_a_stale_copy_is_a_finding():
    storage = FakeStorage([_obj("offsite/money-db/store-20260810T000000Z.db", age_hours=72)])
    report = check(storage, "backup-bucket", "offsite/", [SOURCE])

    assert report[0]["fresh"] is False
    assert "72.0h old" in report[0]["what"]


def test_a_fresh_copy_is_clean():
    storage = FakeStorage([_obj("offsite/money-db/store-20260816T000000Z.db", age_hours=2)])
    report = check(storage, "backup-bucket", "offsite/", [SOURCE])

    assert report[0]["fresh"] is True
    assert report[0]["age_hours"] == pytest.approx(2.0, abs=0.1)


def test_the_newest_copy_decides_not_the_oldest():
    storage = FakeStorage([
        _obj("offsite/money-db/store-20260801T000000Z.db", age_hours=300),
        _obj("offsite/money-db/store-20260816T000000Z.db", age_hours=1),
    ])
    report = check(storage, "backup-bucket", "offsite/", [SOURCE])

    assert report[0]["fresh"] is True
    assert report[0]["copies"] == 2


def test_another_sources_copies_do_not_count_as_this_ones():
    # Both live under the same prefix. A prefix match that is not source-scoped would let a
    # fresh key ring stand in for a missing database.
    storage = FakeStorage([_obj("offsite/data-protection-keys/keyring-20260816T000000Z.tgz", 1)])
    report = check(storage, "backup-bucket", "offsite/", [SOURCE])

    assert report[0]["fresh"] is False


# --- an outage is never reported as an answer ---------------------------------------------

def test_a_storage_outage_is_unknown_not_missing_backup():
    """The trap this test exists for: list_objects_v2 failing returns nothing, and nothing
    looks exactly like "you have no backups" — the loudest finding the tool can print."""
    with pytest.raises(CannotEstablish) as caught:
        check(FakeStorage(list_raises=True), "backup-bucket", "offsite/", [SOURCE])

    assert "could not list" in str(caught.value)


def test_a_missing_declaration_is_unknown_never_clean(tmp_path):
    result = run(tmp_path / "does-not-exist.yaml")

    assert result["status"] == "unknown"
    assert "not found" in result["reason"]


def test_a_declaration_with_no_sources_is_unknown(tmp_path):
    result = run(_declaration(tmp_path, sources=[]))

    assert result["status"] == "unknown"


def test_missing_credentials_are_unknown_and_named_not_printed(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_KEY_ID", raising=False)
    monkeypatch.setenv("TEST_KEY_SECRET", "shhh-this-is-the-secret-value")
    result = run(_declaration(tmp_path))

    assert result["status"] == "unknown"
    assert "TEST_KEY_ID" in result["reason"]
    assert "shhh-this-is-the-secret-value" not in json.dumps(result)


def test_an_unset_env_reference_is_unknown_not_an_empty_string():
    # "https://.example" is a plausible-looking nowhere. Fail closed instead.
    with pytest.raises(CannotEstablish):
        _expand("https://${DEFINITELY_NOT_SET_ANYWHERE}.example")


# --- a copy only counts once it has been opened -------------------------------------------

def test_an_empty_fetch_is_not_a_backup(tmp_path):
    empty = tmp_path / "store.db"
    empty.touch()

    with pytest.raises(CannotEstablish, match="fetched nothing"):
        verify_copy(empty, "sqlite")


def test_a_torn_sqlite_copy_is_rejected(tmp_path):
    torn = tmp_path / "store.db"
    torn.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)

    with pytest.raises(CannotEstablish):
        verify_copy(torn, "sqlite")


def test_a_good_sqlite_copy_passes(tmp_path):
    verify_copy(_sqlite_file(tmp_path / "store.db"), "sqlite")


def test_an_unknown_verify_kind_is_unknown_not_a_pass(tmp_path):
    with pytest.raises(CannotEstablish, match="unknown verify kind"):
        verify_copy(_sqlite_file(tmp_path / "store.db"), "vibes")


# --- taking a backup ----------------------------------------------------------------------

def test_a_failed_fetch_uploads_nothing(tmp_path):
    storage = FakeStorage()
    source = Source(name="money-db", key="money-db/store.db",
                    fetch=["sh", "-c", "echo nope >&2; exit 3"], verify="sqlite")

    with pytest.raises(CannotEstablish, match="exited 3"):
        take_backup(storage, "backup-bucket", "offsite/", source)
    assert storage.uploaded == []


def test_a_fetch_that_produces_a_bad_file_uploads_nothing(tmp_path):
    storage = FakeStorage()
    source = Source(name="money-db", key="money-db/store.db",
                    fetch=["sh", "-c", "printf garbage > {dest}"], verify="sqlite")

    with pytest.raises(CannotEstablish):
        take_backup(storage, "backup-bucket", "offsite/", source)
    assert storage.uploaded == []


def test_a_good_fetch_is_verified_then_uploaded_under_a_dated_key(tmp_path):
    storage = FakeStorage()
    seed = _sqlite_file(tmp_path / "seed.db")
    source = Source(name="money-db", key="money-db/store.db",
                    fetch=["cp", str(seed), "{dest}"], verify="sqlite")

    receipt = take_backup(storage, "backup-bucket", "offsite/", source)

    assert len(storage.uploaded) == 1
    key = storage.uploaded[0][1]
    assert key.startswith("offsite/money-db/store-") and key.endswith(".db")
    assert receipt["bytes"] > 0 and len(receipt["sha256"]) == 64


def test_pruning_keeps_the_newest_and_deletes_the_rest(tmp_path):
    old = [_obj(f"offsite/money-db/store-2026080{n}T000000Z.db", 100 - n) for n in range(1, 6)]
    storage = FakeStorage(old)
    seed = _sqlite_file(tmp_path / "seed.db")
    source = Source(name="money-db", key="money-db/store.db",
                    fetch=["cp", str(seed), "{dest}"], verify="sqlite", keep=2)

    take_backup(storage, "backup-bucket", "offsite/", source)

    # Five stored, keep 2 -> the three oldest go. The new upload is not in the fake's listing,
    # which is the conservative direction: the tool never prunes on a count it invented.
    assert len(storage.deleted) == 3
    assert "offsite/money-db/store-20260805T000000Z.db" not in storage.deleted


# --- the interface ------------------------------------------------------------------------

def test_a_missing_source_key_is_unknown(tmp_path):
    path = _declaration(tmp_path, sources=[{"name": "money-db", "fetch": ["true"]}])

    with pytest.raises(CannotEstablish, match="needs `name:` and `key:`"):
        load_declaration(path)


def test_exit_codes_are_distinct(tmp_path, monkeypatch, capsys):
    # 0 fresh, 1 stale or missing, 2 could not establish. A caller that cannot tell
    # "unknown" from "clean" is the whole defect this exit code exists to prevent.
    assert main(["--config", str(tmp_path / "missing.yaml")]) == EXIT_UNKNOWN

    import ops.automations.offsite_backup as engine

    monkeypatch.setattr(engine, "storage_client",
                        lambda _s: (FakeStorage([]), "backup-bucket", "offsite/"))
    assert main(["--config", str(_declaration(tmp_path))]) == EXIT_FINDINGS

    fresh = FakeStorage([_obj("offsite/money-db/store-20260816T000000Z.db", age_hours=1)])
    monkeypatch.setattr(engine, "storage_client", lambda _s: (fresh, "backup-bucket", "offsite/"))
    assert main(["--config", str(_declaration(tmp_path))]) == EXIT_OK


def test_json_mode_carries_what_the_console_renders(tmp_path, monkeypatch, capsys):
    import ops.automations.offsite_backup as engine

    fresh = FakeStorage([_obj("offsite/money-db/store-20260816T000000Z.db", age_hours=1)])
    monkeypatch.setattr(engine, "storage_client", lambda _s: (fresh, "backup-bucket", "offsite/"))
    main(["--json", "--config", str(_declaration(tmp_path))])

    payload = json.loads(capsys.readouterr().out)
    for key in ("automation", "status", "checked", "findings", "ran_at", "probe"):
        assert key in payload, f"the console renders {key}"
    assert payload["automation"] == "offsite_backup"


def test_the_live_declaration_parses():
    """The live declaration. It is the only thing standing between a Fly account loss and
    every record of who bought what."""
    repo = Path(__file__).resolve().parents[2]
    decl = load_declaration(repo / "ops" / "config" / "offsite_backup.yaml")

    names = {source.name for source in decl.sources}
    assert "money-db" in names, "the money database must be declared"
    money = next(s for s in decl.sources if s.name == "money-db")
    assert money.verify == "sqlite", "a database copy nobody opened is a file, not a backup"
