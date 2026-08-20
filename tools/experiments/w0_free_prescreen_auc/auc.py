"""W0.1 — retrospective AUC of a FREE (zero-token) proxy for PASS vs KILL.

Features are only those available BEFORE any paid check: the generated candidate
fields themselves. No retrieval, no verdict, no score. Pure numpy + stdlib.

Reports: temporal split (fit early / test late) AND stratified k-fold, because a
single temporal split may not carry enough positives to be readable.
"""
import json, os, re, math, random, collections
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# The store is wherever PROSPECTOR_STORE_DIR points, which on the engine is a mounted volume.
# These globs were relative to the working directory, so they read whatever `store/` happened
# to sit beside the shell. INC-2026-08-18-store-resolver.
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from prospector.config import store_root  # noqa: E402

rows = json.load(open(os.path.join(HERE, 'labelled.json')))

# ---- labels: PASS=1, KILL=0. defer has no outcome -> excluded.
data = [r for r in rows if r['decision'] in ('pass', 'kill')]
print(f"labelled usable: {len(data)}  (pass={sum(1 for r in data if r['decision']=='pass')}, "
      f"kill={sum(1 for r in data if r['decision']=='kill')})")

# ---- re-read the raw candidate text fields (extract.py kept only a few)
import glob
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
    t = c.get('tags')
    if isinstance(t, (list, tuple)):
        parts.append(' '.join(str(x) for x in t))
    return ' \n '.join(parts).lower()

TOK = re.compile(r"[a-z][a-z0-9\-']+")

def tokens(s, ngram=2):
    w = TOK.findall(s)
    out = list(w)
    for n in range(2, ngram + 1):
        out += [' '.join(w[i:i + n]) for i in range(len(w) - n + 1)]
    return out

y = np.array([1.0 if r['decision'] == 'pass' else 0.0 for r in data])
docs = [text_of(r) for r in data]
dates = [r['created'][:10] for r in data]
tiers = [r['tier'] or (raw.get(r['file'], {}).get('ambition_tier') or '') for r in data]
markets = [r['market'] for r in data]

print(f"empty-text docs: {sum(1 for d in docs if not d.strip())}")
print(f"median tokens/doc: {int(np.median([len(TOK.findall(d)) for d in docs]))}")


def auc(yt, s):
    """Rank-based AUC. Ties get average rank."""
    yt = np.asarray(yt); s = np.asarray(s, dtype=float)
    n1 = yt.sum(); n0 = len(yt) - n1
    if n1 == 0 or n0 == 0:
        return float('nan')
    order = np.argsort(s, kind='mergesort')
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    i = 0
    r = 1
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        avg = (r + (r + (j - i))) / 2.0
        ranks[order[i:j + 1]] = avg
        r += (j - i + 1)
        i = j + 1
    return float((ranks[yt == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def build_tfidf(train_docs, all_docs, min_df=3, max_feat=8000, ngram=2):
    df = collections.Counter()
    toks = [tokens(d, ngram) for d in train_docs]
    for t in toks:
        df.update(set(t))
    vocab_terms = [w for w, c in df.items() if c >= min_df]
    vocab_terms.sort(key=lambda w: (-df[w], w))
    vocab_terms = vocab_terms[:max_feat]
    vocab = {w: i for i, w in enumerate(vocab_terms)}
    n_tr = len(train_docs)
    idf = np.zeros(len(vocab))
    for w, i in vocab.items():
        idf[i] = math.log((1 + n_tr) / (1 + df[w])) + 1.0
    X = np.zeros((len(all_docs), len(vocab)), dtype=np.float32)
    for r, d in enumerate(all_docs):
        cnt = collections.Counter(tokens(d, ngram))
        for w, c in cnt.items():
            i = vocab.get(w)
            if i is not None:
                X[r, i] = (1.0 + math.log(c)) * idf[i]
    n = np.linalg.norm(X, axis=1, keepdims=True); n[n == 0] = 1.0
    return X / n, vocab


def logreg(X, yv, iters=400, lr=0.5, l2=1e-3, seed=0):
    """Balanced-class logistic regression, full-batch gradient descent.

    X is cast to float64 ONCE. Leaving it float32 while `g`/`w` are float64 makes numpy
    upcast the whole matrix inside every `X.T @ g` — a fresh multi-hundred-MB temporary per
    iteration, which is what made the first run of this probe compute-bound for minutes.
    """
    X = np.ascontiguousarray(X, dtype=np.float64)
    w = np.zeros(X.shape[1]); b = 0.0
    pos = yv.sum(); neg = len(yv) - pos
    sw = np.where(yv == 1, neg / max(pos, 1), 1.0)
    sw = sw / sw.mean()
    for _ in range(iters):
        z = X @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = (p - yv) * sw
        gw = X.T @ g / len(yv) + l2 * w
        gb = g.mean()
        w -= lr * gw; b -= lr * gb
    return w, b


def centroid_knn(Xtr, ytr, Xte, k=15):
    """k-NN score: mean cosine sim to k nearest PASS minus to k nearest KILL."""
    P = Xtr[ytr == 1]; K = Xtr[ytr == 0]
    if len(P) == 0:
        return np.zeros(len(Xte))
    sp = Xte @ P.T; sk = Xte @ K.T
    kp = min(k, sp.shape[1]); kk = min(k, sk.shape[1])
    top_p = np.sort(sp, axis=1)[:, -kp:].mean(axis=1)
    top_k = np.sort(sk, axis=1)[:, -kk:].mean(axis=1)
    return top_p - top_k


def cat_features(idx_all, train_idx):
    """One-hot tier x market + log length. Zero-token metadata baseline."""
    keys = sorted({tiers[i] for i in train_idx} | {markets[i] for i in train_idx})
    ki = {k: n for n, k in enumerate(keys)}
    X = np.zeros((len(idx_all), len(keys) + 2), dtype=np.float32)
    for n, i in enumerate(idx_all):
        if tiers[i] in ki: X[n, ki[tiers[i]]] = 1.0
        if markets[i] in ki: X[n, ki[markets[i]]] = 1.0
        X[n, -2] = math.log1p(len(docs[i]))
        X[n, -1] = math.log1p(len(set(TOK.findall(docs[i]))))
    return X


def run_split(name, tr, te):
    ytr, yte = y[tr], y[te]
    print(f"\n--- {name}: train n={len(tr)} (pass={int(ytr.sum())})  "
          f"test n={len(te)} (pass={int(yte.sum())})")
    if yte.sum() < 3 or ytr.sum() < 3:
        print("    TOO FEW POSITIVES — AUC unreadable, skipping")
        return {}
    out = {}
    Xc = cat_features(list(tr) + list(te), tr)
    Xc_tr, Xc_te = Xc[:len(tr)], Xc[len(tr):]
    w, b = logreg(Xc_tr, ytr)
    out['metadata only (tier/market/len)'] = auc(yte, Xc_te @ w + b)

    Xt, vocab = build_tfidf([docs[i] for i in tr], [docs[i] for i in list(tr) + list(te)])
    Xt_tr, Xt_te = Xt[:len(tr)], Xt[len(tr):]
    out[f'tfidf logreg (|V|={len(vocab)})'] = auc(yte, Xt_te @ logreg(Xt_tr, ytr)[0])
    out['tfidf kNN centroid (k=15)'] = auc(yte, centroid_knn(Xt_tr, ytr, Xt_te))

    Xb = np.hstack([Xt, np.repeat(Xc, 1, axis=0)])
    out['tfidf + metadata'] = auc(yte, Xb[len(tr):] @ logreg(Xb[:len(tr)], ytr)[0])

    for k, v in out.items():
        print(f"    AUC {v:.3f}   {k}")
    return out


# ---- 1. temporal split (the pre-registered design)
CUT = '2026-08-05'
tr = np.array([i for i, d in enumerate(dates) if d < CUT])
te = np.array([i for i, d in enumerate(dates) if d >= CUT])
run_split(f'TEMPORAL fit<{CUT} test>={CUT}', tr, te)

# ---- 2. earlier cut, so the test half has more positives
for CUT2 in ('2026-07-22', '2026-07-15'):
    tr2 = np.array([i for i, d in enumerate(dates) if d < CUT2])
    te2 = np.array([i for i, d in enumerate(dates) if d >= CUT2])
    run_split(f'TEMPORAL fit<{CUT2} test>={CUT2}', tr2, te2)

# ---- 2b. REGIME-RESTRICTED. June 2026 produced 724 candidates and ZERO passes: a different
# data-generating process (the zero-yield bottlenecks). Training a PASS/KILL proxy on a period
# where nothing could pass teaches it nothing about passing. Refit from 2026-07-01 only.
REGIME = '2026-07-01'
keep = [i for i, d in enumerate(dates) if d >= REGIME]
print(f"\n=== REGIME-RESTRICTED (>= {REGIME}: n={len(keep)}, "
      f"pass={int(sum(y[i] for i in keep))}) ===")
tr4 = np.array([i for i in keep if dates[i] < CUT])
te4 = np.array([i for i in keep if dates[i] >= CUT])
run_split(f'post-regime, fit<{CUT} test>={CUT}', tr4, te4)

# ---- 3. stratified 5-fold (uses every positive; no temporal guarantee)
print("\n=== STRATIFIED 5-FOLD (all data, ignores time) ===")
rng = random.Random(0)
pos = [i for i in range(len(y)) if y[i] == 1]
neg = [i for i in range(len(y)) if y[i] == 0]
rng.shuffle(pos); rng.shuffle(neg)
folds = [[] for _ in range(5)]
for n, i in enumerate(pos): folds[n % 5].append(i)
for n, i in enumerate(neg): folds[n % 5].append(i)
agg = collections.defaultdict(list)
for f in range(5):
    te3 = np.array(folds[f])
    tr3 = np.array([i for g in range(5) if g != f for i in folds[g]])
    r = run_split(f'fold {f+1}/5', tr3, te3)
    for k, v in r.items():
        agg[k].append(v)
print("\n=== 5-FOLD MEAN AUC ===")
for k, v in agg.items():
    print(f"    {np.mean(v):.3f}  +/- {np.std(v):.3f}   {k}")

print("\n=== DECISION RULE (from the war plan) ===")
print("  AUC ~= 0.5  -> the proxy carries no signal; admission ordering loses its funding.")
print("  AUC >  0.75 -> admission ORDERING becomes a headline item (never KILLING).")
