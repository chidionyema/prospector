"""jobs.json has concurrent readers by design, so its writer must be atomic.

Measured 2026-08-09: `_save_jobs_to` ended in `path.write_text(...)`, which truncates the file
before writing it. The per-job monitor daemon thread upserts status into that same file
(`runner.py:388`) while the CLI, pytest and the Streamlit cockpit read it, so a reader landing
in the truncation window sees zero bytes. Against a concurrent writer, 1636 of 20000 reads
observed an empty file and 8 observed a partial one.

CI failed on exactly this — `TestLaunchPersist::test_launch_writes_job_to_jobs_json` raised
`json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`, the signature of an
empty string. The production symptom is quieter and worse: `_load_jobs_from` catches
JSONDecodeError and returns `[]`, so a running job simply disappears from the cockpit for a
poll instead of raising anything anyone would see.
"""
from __future__ import annotations

import json
import threading

from prospector.ops import runner

# Big enough that the write cannot plausibly complete between two reads.
_JOBS = [{"job_id": f"j{i}", "argv": ["echo", "x"], "status": "running"} for i in range(200)]


def test_a_concurrent_reader_never_sees_a_truncated_jobs_file(tmp_path):
    path = tmp_path / "jobs.json"
    runner._save_jobs_to(path, _JOBS)

    stop = threading.Event()
    writer_error: list[BaseException] = []

    def writer() -> None:
        try:
            while not stop.is_set():
                runner._save_jobs_to(path, _JOBS)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the assertion below
            writer_error.append(exc)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        bad = 0
        reads = 0
        for _ in range(3000):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                # A rename swapping the inode under an open() is not the defect under test.
                continue
            reads += 1
            try:
                rows = json.loads(text)
            except json.JSONDecodeError:
                bad += 1
                continue
            assert len(rows) == len(_JOBS)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert not writer_error, f"writer thread raised: {writer_error[0]!r}"
    assert reads > 0, "the reader never observed the file at all; the test proved nothing"
    assert bad == 0, f"{bad}/{reads} reads saw a truncated or empty jobs.json"


def test_the_writer_leaves_no_temp_files_behind(tmp_path):
    """An atomic write that litters is a different bug in the same directory.

    Asserted on the `.tmp` suffix rather than on the whole listing, because the package
    conftest redirects `control_center/` and `audit/` into this same tmp_path — a listing
    equality check fails on those and says nothing about the writer.
    """
    path = tmp_path / "jobs.json"
    runner._save_jobs_to(path, _JOBS)
    assert path.exists()
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"scratch files left behind: {leftovers}"
