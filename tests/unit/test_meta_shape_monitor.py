"""V4 meta-shape monitor — unit tests.

The embedding call is injected, so no test needs ollama and none costs a token. One test
DOES hit the real ollama and skips when it is unreachable — a mocked embedder proves the
clustering, not that the model exists. Nothing writes to store/: the fixture index and any
receipt live in tmp_path.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.meta_shape_monitor import (  # noqa: E402
    DEFAULTS,
    MonitorError,
    analyse,
    embed_texts,
    kmeans,
    load_one_liners,
    main,
    monitor_config,
    ollama_available,
)

_SCHEMA = """
CREATE TABLE dossiers (
    candidate_id TEXT PRIMARY KEY,
    decision     TEXT,
    created_at   TEXT,
    one_liner    TEXT
);
"""


def _db(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    p = tmp_path / "prospector.db"
    conn = sqlite3.connect(p)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO dossiers (candidate_id, decision, created_at, one_liner) VALUES (?,?,?,?)",
        [(cid, dec, f"2026-01-{(i % 28) + 1:02d}", txt) for i, (cid, dec, txt) in enumerate(rows)])
    conn.commit()
    conn.close()
    return p


def _blobby_rows(n_big: int, n_small: int) -> list[tuple[str, str, str]]:
    rows = [(f"big{i}", "kill", f"recover money from a bureaucracy, variant {i}")
            for i in range(n_big)]
    rows += [(f"sml{i}", "pass", f"a completely different thing {i}") for i in range(n_small)]
    return rows


def _fake_embed(dim: int = 8, jitter: float = 0.01):
    """Deterministic embedder: one axis per meta-shape, so clusters are known ground truth."""
    def embed(texts):
        out = []
        for t in texts:
            v = np.zeros(dim)
            v[0 if t.startswith("recover money") else 1] = 1.0
            v += jitter * np.asarray([hash((t, j)) % 7 / 7.0 for j in range(dim)])
            out.append(v.tolist())
        return out
    return embed


# ------------------------------------------------------------------------------ config


def test_defaults_land_inert_and_local():
    m = monitor_config(SimpleNamespace())
    assert m["enabled"] is False
    assert m["embed_model"] == "nomic-embed-text"
    assert m["ollama_host"] == "http://localhost:11434"
    assert (m["clusters"], m["alert_top_cluster_share"], m["min_rows"]) == (8, 0.35, 50)


def test_config_block_and_cli_overrides_layer():
    cfg = SimpleNamespace(meta_shape_monitor={"clusters": 5, "min_rows": 10})
    assert monitor_config(cfg)["clusters"] == 5
    assert monitor_config(cfg, {"clusters": 3})["clusters"] == 3
    assert monitor_config(cfg, {"clusters": None})["clusters"] == 5  # unset CLI arg is not a value


# ------------------------------------------------------------------------------- input


def test_load_one_liners_skips_blanks_and_filters_by_decision(tmp_path):
    db = _db(tmp_path, [("a", "pass", "one"), ("b", "kill", "two"),
                        ("c", "kill", "   "), ("d", "kill", "")])
    assert len(load_one_liners(db)) == 2
    assert [cid for cid, _ in load_one_liners(db, decision="pass")] == ["a"]
    assert len(load_one_liners(db, limit=1)) == 1


def test_load_one_liners_is_read_only(tmp_path):
    db = _db(tmp_path, [("a", "pass", "one")])
    load_one_liners(db)
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM dossiers")
    finally:
        conn.close()


def test_missing_index_is_a_monitor_error(tmp_path):
    with pytest.raises(MonitorError, match="no dossier index"):
        load_one_liners(tmp_path / "absent.db")


# -------------------------------------------------------------------------- clustering


def test_kmeans_separates_two_known_blobs():
    rng = np.random.default_rng(0)
    a = np.concatenate([np.ones((30, 1)), 0.01 * rng.normal(size=(30, 7))], axis=1)
    b = np.concatenate([-np.ones((10, 1)), 0.01 * rng.normal(size=(10, 7))], axis=1)
    labels, centers = kmeans(np.vstack([a, b]), 2, seed=0)
    assert centers.shape == (2, 8)
    assert len(set(labels[:30])) == 1 and len(set(labels[30:])) == 1
    assert labels[0] != labels[30]


def test_kmeans_is_deterministic_and_never_returns_more_clusters_than_points():
    X = np.random.default_rng(1).normal(size=(12, 5))
    assert np.array_equal(kmeans(X, 4, seed=7)[0], kmeans(X, 4, seed=7)[0])
    labels, centers = kmeans(X, 50, seed=7)
    assert centers.shape[0] == 12


def test_kmeans_handles_identical_vectors():
    X = np.ones((20, 4))
    labels, centers = kmeans(X, 5, seed=3)
    assert len(labels) == 20 and centers.shape[0] == 5


# ---------------------------------------------------------------------------- analysis


def test_analyse_measures_the_top_cluster_share(tmp_path):
    rows = _blobby_rows(80, 20)
    r = analyse([(cid, txt) for cid, _d, txt in rows], clusters=2, alert_share=0.35,
                min_rows=10, seed=0, embed=_fake_embed())
    assert r["rows"] == 100
    assert r["dim"] == 8
    assert r["clusters"] == 2
    assert r["cluster_sizes"] == [80, 20]
    assert r["top_cluster_share"] == pytest.approx(0.80)
    assert r["alert"] is True
    assert "k-means" in r["method"]
    json.dumps(r)


def test_alert_is_off_when_the_catalogue_is_spread(tmp_path):
    rows = _blobby_rows(50, 50)
    r = analyse([(cid, txt) for cid, _d, txt in rows], clusters=2, alert_share=0.6,
                min_rows=10, seed=0, embed=_fake_embed())
    assert r["top_cluster_share"] == pytest.approx(0.5)
    assert r["alert"] is False


def test_receipt_carries_exemplars_per_cluster():
    rows = [(cid, txt) for cid, _d, txt in _blobby_rows(30, 30)]
    r = analyse(rows, clusters=2, alert_share=0.35, min_rows=10, seed=0,
                exemplars=2, embed=_fake_embed())
    detail = r["clusters_detail"]
    assert len(detail) == 2
    assert all(len(c["exemplars"]) == 2 for c in detail)
    assert all(set(e) == {"candidate_id", "one_liner"} for c in detail for e in c["exemplars"])
    texts = {e["one_liner"] for c in detail for e in c["exemplars"]}
    assert any(t.startswith("recover money") for t in texts)
    assert any(t.startswith("a completely different") for t in texts)


def test_min_rows_refuses_to_report_on_a_thin_catalogue():
    rows = [(f"a{i}", f"text {i}") for i in range(4)]
    with pytest.raises(MonitorError, match="min_rows"):
        analyse(rows, clusters=2, alert_share=0.35, min_rows=50, seed=0, embed=_fake_embed())


def test_a_short_embedder_is_an_error_not_a_silent_truncation():
    rows = [(f"a{i}", f"text {i}") for i in range(10)]
    with pytest.raises(MonitorError, match="vectors for"):
        analyse(rows, clusters=2, alert_share=0.35, min_rows=1, seed=0,
                embed=lambda ts: [[1.0, 0.0] for _ in ts[:-1]])


# ----------------------------------------------------------------------------- the CLI


def test_main_writes_a_receipt_only_when_asked(tmp_path, monkeypatch, capsys):
    import tools.meta_shape_monitor as msm

    db = _db(tmp_path, _blobby_rows(40, 10))
    monkeypatch.setattr(msm, "embed_texts", lambda ts, **kw: _fake_embed()(ts))
    out = tmp_path / "receipt.json"
    rc = main(["--db", str(db), "--clusters", "2", "--min-rows", "10",
               "--out", str(out), "--fail-on-alert"])
    receipt = json.loads(out.read_text())
    assert receipt["top_cluster_share"] == pytest.approx(0.8)
    assert rc == 2, "alerting with --fail-on-alert must be a nonzero exit"
    captured = json.loads(capsys.readouterr().out)
    assert captured["rows"] == 50

    rc = main(["--db", str(db), "--clusters", "2", "--min-rows", "10"])
    assert rc == 0
    assert not (tmp_path / "meta_shape").exists()


def test_main_reports_a_thin_catalogue_as_exit_3(tmp_path, monkeypatch, capsys):
    import tools.meta_shape_monitor as msm

    db = _db(tmp_path, _blobby_rows(3, 2))
    monkeypatch.setattr(msm, "embed_texts", lambda ts, **kw: _fake_embed()(ts))
    assert main(["--db", str(db), "--min-rows", "50"]) == 3
    assert "min_rows" in json.loads(capsys.readouterr().out)["error"]


# --------------------------------------------------------------- the real local model


@pytest.mark.skipif(not ollama_available(), reason="ollama not reachable on localhost:11434")
def test_ollama_embeds_for_real():
    vecs = embed_texts(["a service that recovers overpaid council tax",
                        "a marketplace for second-hand kayaks"],
                       host=DEFAULTS["ollama_host"], model=DEFAULTS["embed_model"])
    assert len(vecs) == 2
    assert len(vecs[0]) == len(vecs[1]) >= 256
    a, b = (np.asarray(v) / np.linalg.norm(v) for v in vecs)
    assert -1.0 <= float(a @ b) <= 1.0
