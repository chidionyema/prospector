#!/usr/bin/env python3
"""V4 — the meta-shape monitor: make "78 niches, one shape" a NUMBER.

COMMERCIAL_READINESS_PROGRAM.md:11 asserts the catalogue is "78 niches inside ONE meta-shape".
That is an eyeball verdict. This job turns it into a measurement: embed every catalogue
one-liner with a LOCAL model, cluster them, and report the share of the catalogue sitting in
the single largest cluster. Above `alert_top_cluster_share` it alerts.

Costs zero tokens and touches no API:
  * embeddings  ollama `nomic-embed-text` over HTTP on localhost (stdlib urllib, dim 768)
  * clustering  spherical k-means by hand in numpy — L2-normalised vectors, k-means++ init
                (seeded, so the receipt is replayable), Lloyd iterations to convergence.
                scikit-learn is NOT a dependency of this repo and is not added here.
  * input       `store/prospector.db` opened READ-ONLY (`mode=ro`); it is production state.
  * output      a JSON receipt on stdout. Nothing is written unless `--out`/`log_dir` says so.

    python tools/meta_shape_monitor.py                     # whole dossier catalogue
    python tools/meta_shape_monitor.py --decision pass     # only what can publish
    python tools/meta_shape_monitor.py --clusters 8 --out /tmp/meta_shape.json

Exit codes: 0 ok (or alerting, unless --fail-on-alert), 2 alert with --fail-on-alert,
3 could not run (ollama unreachable, too few rows, no DB).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "embed_model": "nomic-embed-text",
    "ollama_host": "http://localhost:11434",
    "clusters": 8,
    "alert_top_cluster_share": 0.35,
    "min_rows": 50,
    "log_dir": "",
}


class MonitorError(RuntimeError):
    """Could not produce a measurement (as opposed to producing a bad one)."""


def monitor_config(cfg: Any = None, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """`cfg.meta_shape_monitor` merged over the defaults. A Config predating V4 is fine."""
    out = dict(DEFAULTS)
    out.update(dict(getattr(cfg, "meta_shape_monitor", {}) or {}))
    out.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return out


# ------------------------------------------------------------------------------ input


def load_one_liners(
    db_path: Path | str,
    *,
    decision: str = "",
    limit: int = 0,
) -> list[tuple[str, str]]:
    """(candidate_id, one_liner) for rows carrying text. READ-ONLY connection."""
    p = Path(db_path)
    if not p.exists():
        raise MonitorError(f"no dossier index at {p}")
    sql = ("SELECT candidate_id, one_liner FROM dossiers "
           "WHERE one_liner IS NOT NULL AND trim(one_liner) <> ''")
    params: list[Any] = []
    if decision:
        sql += " AND lower(trim(coalesce(decision,''))) = ?"
        params.append(decision.strip().lower())
    sql += " ORDER BY coalesce(created_at,'') DESC, rowid DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [(str(cid), str(txt).strip()) for cid, txt in rows if str(txt).strip()]


# ------------------------------------------------------------------------- embeddings


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — localhost only
        return json.loads(resp.read().decode("utf-8"))


def embed_texts(
    texts: Sequence[str],
    *,
    host: str = DEFAULTS["ollama_host"],
    model: str = DEFAULTS["embed_model"],
    timeout: float = 120.0,
    batch: int = 32,
) -> list[list[float]]:
    """Embed with ollama. Tries the batch `/api/embed`, falls back to `/api/embeddings`."""
    host = host.rstrip("/")
    out: list[list[float]] = []
    for i in range(0, len(texts), max(1, batch)):
        chunk = list(texts[i:i + max(1, batch)])
        try:
            data = _post_json(f"{host}/api/embed", {"model": model, "input": chunk}, timeout)
            vecs = data.get("embeddings")
            if not vecs or len(vecs) != len(chunk):
                raise MonitorError(f"/api/embed returned {len(vecs or [])} of {len(chunk)}")
            out.extend([[float(x) for x in v] for v in vecs])
        except urllib.error.HTTPError:
            for t in chunk:
                data = _post_json(
                    f"{host}/api/embeddings", {"model": model, "prompt": t}, timeout)
                vec = data.get("embedding")
                if not vec:
                    raise MonitorError("ollama returned an empty embedding") from None
                out.append([float(x) for x in vec])
        except urllib.error.URLError as e:
            raise MonitorError(f"ollama unreachable at {host}: {e}") from e
    return out


def ollama_available(host: str = DEFAULTS["ollama_host"], timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(  # noqa: S310 — localhost only
                f"{host.rstrip('/')}/api/tags", timeout=timeout):
            return True
    except Exception:  # noqa: BLE001 — any failure means "not available"
        return False


# ------------------------------------------------------------------------- clustering


def _normalise(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return X / norms


def _sqdist(X: np.ndarray, C: np.ndarray) -> np.ndarray:
    """||x - c||^2 without materialising an n×k×dim tensor."""
    return (
        (X ** 2).sum(1)[:, None] - 2.0 * (X @ C.T) + (C ** 2).sum(1)[None, :]
    )


def kmeans(
    X: np.ndarray, k: int, *, seed: int = 0, iters: int = 100
) -> tuple[np.ndarray, np.ndarray]:
    """Spherical k-means (unit vectors + Euclidean = cosine), k-means++ init, seeded.

    Returns (labels, centers). Deterministic for a given (X, k, seed).
    """
    X = _normalise(np.asarray(X, dtype=np.float64))
    n = X.shape[0]
    k = max(1, min(int(k), n))
    rng = np.random.default_rng(seed)

    centers = np.empty((k, X.shape[1]), dtype=np.float64)
    first = int(rng.integers(n))
    centers[0] = X[first]
    closest = ((X - centers[0]) ** 2).sum(1)
    for c in range(1, k):
        total = float(closest.sum())
        if total <= 0:
            idx = int(rng.integers(n))
        else:
            idx = int(rng.choice(n, p=closest / total))
        centers[c] = X[idx]
        closest = np.minimum(closest, ((X - centers[c]) ** 2).sum(1))

    labels = np.zeros(n, dtype=int)
    for it in range(max(1, iters)):
        new_labels = _sqdist(X, centers).argmin(1)
        converged = it > 0 and np.array_equal(new_labels, labels)
        labels = new_labels
        if converged:
            break
        for c in range(k):
            members = X[labels == c]
            if len(members):
                centers[c] = members.mean(0)
            else:
                # Empty cluster: re-seed it on the point furthest from its own centre,
                # so k really is k rather than silently collapsing.
                far = int(_sqdist(X, centers).min(1).argmax())
                centers[c] = X[far]
        centers = _normalise(centers)
    return labels, centers


# ------------------------------------------------------------------------------- run


def analyse(
    rows: Sequence[tuple[str, str]],
    *,
    clusters: int,
    alert_share: float,
    min_rows: int,
    seed: int = 0,
    exemplars: int = 3,
    embed: Optional[Callable[[Sequence[str]], Sequence[Sequence[float]]]] = None,
    model: str = DEFAULTS["embed_model"],
) -> dict[str, Any]:
    """Embed + cluster + build the receipt. `embed` is injectable so tests need no ollama."""
    if len(rows) < int(min_rows):
        raise MonitorError(f"only {len(rows)} row(s) with a one-liner, min_rows={min_rows}")
    if embed is None:
        raise MonitorError("no embedding function supplied")
    texts = [t for _, t in rows]
    vectors = np.asarray(list(embed(texts)), dtype=np.float64)
    if vectors.ndim != 2 or vectors.shape[0] != len(texts):
        raise MonitorError(f"embedder returned {vectors.shape[0]} vectors for {len(texts)} texts")

    labels, centers = kmeans(vectors, clusters, seed=seed)
    k = centers.shape[0]
    sizes = [int((labels == c).sum()) for c in range(k)]
    n = len(texts)
    order = sorted(range(k), key=lambda c: -sizes[c])
    top = order[0]
    top_share = sizes[top] / n if n else 0.0

    unit = _normalise(vectors)
    out_clusters = []
    for rank, c in enumerate(order):
        idx = np.flatnonzero(labels == c)
        if len(idx):
            # Exemplars = the members closest to their own centroid.
            d = ((unit[idx] - centers[c]) ** 2).sum(1)
            picks = idx[np.argsort(d)[:max(0, exemplars)]]
        else:
            picks = np.asarray([], dtype=int)
        out_clusters.append({
            "rank": rank,
            "cluster": int(c),
            "size": sizes[c],
            "share": round(sizes[c] / n, 4) if n else 0.0,
            "exemplars": [
                {"candidate_id": rows[int(i)][0], "one_liner": rows[int(i)][1]} for i in picks
            ],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": n,
        "embed_model": model,
        "dim": int(vectors.shape[1]),
        "method": "spherical k-means (k-means++ init, numpy, seeded)",
        "seed": seed,
        "clusters_requested": int(clusters),
        "clusters": k,
        "cluster_sizes": [sizes[c] for c in order],
        "top_cluster_share": round(top_share, 4),
        "alert_threshold": float(alert_share),
        "alert": bool(top_share > float(alert_share)),
        "clusters_detail": out_clusters,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="", help="dossier index (default: cfg.store_dir/prospector.db)")
    ap.add_argument("--decision", default="", help="filter rows: pass | kill | defer")
    ap.add_argument("--clusters", type=int, default=None)
    ap.add_argument("--alert-share", type=float, default=None)
    ap.add_argument("--min-rows", type=int, default=None)
    ap.add_argument("--limit", type=int, default=0, help="most recent N rows only (0 = all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--exemplars", type=int, default=3)
    ap.add_argument("--host", default=None, help="ollama base URL")
    ap.add_argument("--model", default=None, help="embedding model")
    ap.add_argument("--out", default="", help="write the receipt here (default: stdout only)")
    ap.add_argument("--fail-on-alert", action="store_true")
    args = ap.parse_args(argv)

    cfg = None
    try:
        from prospector.config import load_config
        cfg = load_config()
    except Exception as e:  # noqa: BLE001 — the monitor must run without a loadable config
        print(f"# config unavailable ({e}); using defaults", file=sys.stderr)
    mcfg = monitor_config(cfg, {
        "clusters": args.clusters,
        "alert_top_cluster_share": args.alert_share,
        "min_rows": args.min_rows,
        "ollama_host": args.host,
        "embed_model": args.model,
    })

    db = args.db
    if not db:
        try:
            db = str(Path(cfg.store_dir) / "prospector.db")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            db = str(Path(__file__).resolve().parent.parent / "store" / "prospector.db")

    host, model = str(mcfg["ollama_host"]), str(mcfg["embed_model"])
    try:
        rows = load_one_liners(db, decision=args.decision, limit=args.limit)
        receipt = analyse(
            rows,
            clusters=int(mcfg["clusters"]),
            alert_share=float(mcfg["alert_top_cluster_share"]),
            min_rows=int(mcfg["min_rows"]),
            seed=args.seed,
            exemplars=args.exemplars,
            model=model,
            embed=lambda ts: embed_texts(ts, host=host, model=model),
        )
    except MonitorError as e:
        print(json.dumps({"error": str(e), "db": db}, indent=2))
        return 3
    receipt["db"] = db
    receipt["decision_filter"] = args.decision or "(all)"

    out_path = args.out or str(mcfg.get("log_dir") or "")
    if out_path:
        p = Path(out_path)
        if p.is_dir() or not p.suffix:
            p.mkdir(parents=True, exist_ok=True)
            p = p / f"meta_shape_{datetime.now(timezone.utc):%Y-%m-%d}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(f"# receipt written to {p}", file=sys.stderr)
    print(json.dumps(receipt, indent=2))
    if receipt["alert"]:
        print(
            f"# ALERT top cluster holds {receipt['top_cluster_share']:.1%} of "
            f"{receipt['rows']} one-liners (threshold {receipt['alert_threshold']:.1%})",
            file=sys.stderr)
        if args.fail_on_alert:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
