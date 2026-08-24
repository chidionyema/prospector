"""W0.1, dense arm — the feature the war plan actually named.

The lexical arm (TF-IDF) came back at chance out-of-time. Before ruling on W0.1 the plan's
OWN feature has to be tried: "local `nomic-embed-text` embedding of the one-liner, k-NN
distance to historical PASS/KILL centroids". That model is installed
(`ollama list` -> nomic-embed-text:latest, 274 MB, 768-dim) and the repo already speaks to
it (`prospector/prescreen_prefilter.py:149`), so this costs zero tokens and zero web calls.

Same pre-registered temporal split as auc.py, plus the regime-restricted control that
exposed the June confound.
"""
import json, os, math, collections, urllib.request, sys, glob, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# The store is wherever PROSPECTOR_STORE_DIR points, which on the engine is a mounted volume.
# These globs were relative to the working directory, so they read whatever `store/` happened
# to sit beside the shell. INC-2026-08-18-store-resolver.
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from prospector.config import store_root  # noqa: E402

CACHE = os.path.join(HERE, 'emb_cache.json')
rows = json.load(open(os.path.join(HERE, 'labelled.json')))
data = [r for r in rows if r['decision'] in ('pass', 'kill')]

raw = {}
for f in glob.glob(str(store_root() / 'dossiers' / '*.json')):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if isinstance(d, dict) and 'decision' in d and isinstance(d.get('candidate'), dict):
        raw[os.path.basename(f)] = d['candidate']

TEXT_FIELDS = ('one_liner', 'title', 'hypothesis', 'who_pays', 'why_now',
               'structural_form', 'weak_monetisation', 'automatability')


def text_of(r):
    c = raw.get(r['file'], {})
    parts = []
    for k in TEXT_FIELDS:
        v = c.get(k)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.append(' '.join(str(x) for x in v))
        elif v is not None:
            parts.append(str(v))
    return ' \n '.join(parts)


def one_liner_of(r):
    c = raw.get(r['file'], {})
    return str(c.get('one_liner') or c.get('title') or '')


docs_full = [text_of(r) for r in data]
docs_ol = [one_liner_of(r) for r in data]
y = np.array([1.0 if r['decision'] == 'pass' else 0.0 for r in data])
dates = [r['created'][:10] for r in data]

cache = {}
if os.path.exists(CACHE):
    cache = json.load(open(CACHE))


def embed(texts, tag):
    out = []
    miss = 0
    for n, t in enumerate(texts):
        key = f"{tag}:{hash(t)}"
        v = cache.get(key)
        if v is None:
            miss += 1
            body = json.dumps({"model": "nomic-embed-text",
                               "prompt": t[:8000] or "empty"}).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/embeddings", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                v = json.loads(resp.read())["embedding"]
            cache[key] = v
            if miss % 200 == 0:
                print(f"    embedded {n+1}/{len(texts)}", flush=True)
        out.append(v)
    X = np.asarray(out, dtype=np.float64)
    nrm = np.linalg.norm(X, axis=1, keepdims=True); nrm[nrm == 0] = 1.0
    return X / nrm


def auc(yt, s):
    yt = np.asarray(yt); s = np.asarray(s, dtype=float)
    n1 = yt.sum(); n0 = len(yt) - n1
    if n1 == 0 or n0 == 0:
        return float('nan')
    order = np.argsort(s, kind='mergesort')
    ranks = np.empty(len(s), dtype=float); ss = s[order]
    i = 0; r = 1
    while i < len(s):
        j = i
        while j + 1 < len(s) and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (r + r + (j - i)) / 2.0
        r += (j - i + 1); i = j + 1
    return float((ranks[yt == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def logreg(X, yv, iters=600, lr=0.5, l2=1e-2):
    X = np.ascontiguousarray(X, dtype=np.float64)
    w = np.zeros(X.shape[1]); b = 0.0
    pos = yv.sum(); neg = len(yv) - pos
    sw = np.where(yv == 1, neg / max(pos, 1), 1.0); sw = sw / sw.mean()
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(X @ w + b, -30, 30)))
        g = (p - yv) * sw
        w -= lr * (X.T @ g / len(yv) + l2 * w); b -= lr * g.mean()
    return w, b


def knn(Xtr, ytr, Xte, k=15):
    P = Xtr[ytr == 1]; K = Xtr[ytr == 0]
    if len(P) == 0 or len(K) == 0:
        return np.zeros(len(Xte))
    sp = np.sort(Xte @ P.T, axis=1)[:, -min(k, len(P)):].mean(axis=1)
    sk = np.sort(Xte @ K.T, axis=1)[:, -min(k, len(K)):].mean(axis=1)
    return sp - sk


def centroid(Xtr, ytr, Xte):
    """The plan's literal wording: distance to historical PASS/KILL centroids."""
    cp = Xtr[ytr == 1].mean(axis=0); ck = Xtr[ytr == 0].mean(axis=0)
    cp /= max(np.linalg.norm(cp), 1e-9); ck /= max(np.linalg.norm(ck), 1e-9)
    return Xte @ cp - Xte @ ck


print("embedding one-liners ...", flush=True)
X_ol = embed(docs_ol, 'ol')
print("embedding full candidate text ...", flush=True)
X_full = embed(docs_full, 'full')
json.dump(cache, open(CACHE, 'w'))
print(f"cached vectors: {len(cache)}  dim={X_ol.shape[1]}", flush=True)

CUT = '2026-08-05'


def run(name, tr, te):
    ytr, yte = y[tr], y[te]
    print(f"\n--- {name}: train n={len(tr)} (pass={int(ytr.sum())})  "
          f"test n={len(te)} (pass={int(yte.sum())})")
    if ytr.sum() < 3 or yte.sum() < 3:
        print("    TOO FEW POSITIVES — skipping")
        return
    for label, X in (('one-liner', X_ol), ('full text', X_full)):
        A, B = X[tr], X[te]
        print(f"    AUC {auc(yte, B @ logreg(A, ytr)[0]):.3f}   nomic {label} logreg")
        print(f"    AUC {auc(yte, knn(A, ytr, B)):.3f}   nomic {label} kNN(15)")
        print(f"    AUC {auc(yte, centroid(A, ytr, B)):.3f}   nomic {label} PASS/KILL centroid")


tr = np.array([i for i, d in enumerate(dates) if d < CUT])
te = np.array([i for i, d in enumerate(dates) if d >= CUT])
print("\n=== PRE-REGISTERED TEMPORAL SPLIT (all data) ===")
run(f'fit<{CUT} test>={CUT}', tr, te)

print("\n=== REGIME-RESTRICTED CONTROL (>= 2026-07-01) ===")
keep = [i for i, d in enumerate(dates) if d >= '2026-07-01']
run(f'post-regime fit<{CUT} test>={CUT}',
    np.array([i for i in keep if dates[i] < CUT]),
    np.array([i for i in keep if dates[i] >= CUT]))
