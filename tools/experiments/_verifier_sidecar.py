#!/usr/bin/env python3
"""Generic local-verifier scorer — runs ONLY under the python3.12 sidecar interpreter.

Why a second process: the project venv is CPython 3.14 on macOS x86_64, where no torch wheel
exists (torch dropped macOS x86_64 after 2.2). Same shape and contract as `_hhem_sidecar.py`:
file-in / file-out JSON, because torch and transformers both write progress bars and warnings to
streams this caller cannot predict.

    python3.12 _verifier_sidecar.py <input.json> <output.json>

    input.json  : {"model_id": "...", "family": "...", "pairs": [[premise, hypothesis], ...],
                   "batch_size": 8}
    output.json : {"ok": true, "scores": [...], "label_map": {...}, ...} | {"ok": false, ...}

Every score is P(the hypothesis is supported by the premise), 0..1, comparable across families.

THE FOUR FAMILIES, EACH IMPLEMENTED FROM ITS REFERENCE AND NOT FROM MEMORY.

`hhem-custom` — vectara/hallucination_evaluation_model. Ships its own `predict` via
    trust_remote_code; the model's own method is used rather than reimplemented.

`seq2seq-minicheck` — lytang/MiniCheck-Flan-T5-Large. Read from
    github.com/Liyan06/MiniCheck `minicheck/inference.py`:
      input   "predict: " + chunk + tokenizer.eos_token + claim
      forward decoder_input_ids = [[0]], one step
      score   softmax(logits[:, [3, 209]])[:, 1]   -- token 3 = no support, 209 = support
      chunks  max of the support probability over the document's chunks

`seqclass-minicheck` — MiniCheck-RoBERTa-Large / MiniCheck-DeBERTa-v3-Large. Same source, the
    non-flan-t5 branch: input is `tokenizer.eos_token.join([chunk, claim])` with NO "predict: "
    prefix, a plain 2-label sequence classification head, score = softmax(logits)[:, 1], max over
    chunks. The reference chunks these by TOKEN count rather than word count.

`nli-entailment` — general 3-way NLI checkpoints. Standard sentence-pair encoding
    `tokenizer(premise, hypothesis)`, score = P(entailment).

    THE LABEL INDEX IS READ, NEVER ASSUMED. This is the one place a silent wrong answer was
    cheapest to produce: `microsoft/deberta-large-mnli` orders its labels
    CONTRADICTION/NEUTRAL/ENTAILMENT, while MoritzLaurer's DeBERTa-v3 checkpoints order them
    entailment/neutral/contradiction. Hardcoding index 2 would invert one of the two, and an
    inverted score does not look broken -- it looks like a model that disagrees with the moat,
    which is exactly the finding the experiment is trying to measure. `_entailment_index` reads
    `config.id2label`, matches case-insensitively, and RAISES if it cannot find the label. The
    resolved map is returned in the receipts so the reader can check it.

CHUNKING. Both MiniCheck families aggregate with max over document chunks. On this corpus that is
a no-op -- premises are clipped to 1,500 characters by `_groundedness.py:35`, measured p50 45
words / max 294 against a 500-word chunk size, 0 of 3,472 pairs over -- but it is implemented so a
longer premise is still handled the reference's way rather than silently truncated.
"""
from __future__ import annotations

import json
import re
import sys
import time

FLAN_LABEL_TOKENS = [3, 209]      # inference.py: 3 = no support, 209 = support
CHUNK_WORDS = 500                 # minicheck.py:148, flan-t5 default
CHUNK_TOKENS = 400                # minicheck.py:148, roberta/deberta default
MAX_LEN = {"seq2seq-minicheck": 2048, "seqclass-minicheck": 512,
           "nli-entailment": 512, "hhem-custom": 512}


def _normalise(doc: str) -> str:
    """The reference's sentence-split-then-rejoin, collapsed to what it actually does per line."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in doc.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def _word_chunks(doc: str, n: int = CHUNK_WORDS) -> list[str]:
    words = _normalise(doc).split()
    if not words:
        return [""]
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)]


# Three vocabularies for one concept. NLI checkpoints say "entailment"; fact-verification
# checkpoints trained on FEVER or VitaminC say "SUPPORTS". Measured 2026-08-20:
# tals/albert-xlarge-vitaminc-mnli publishes id2label {0: SUPPORTS, 1: REFUTES, 2: NOT ENOUGH
# INFO} -- FEVER's three classes, which are exactly prospector's supported / refuted /
# unverifiable. The names differ; the quantity is the same one, so the alias set is explicit and
# anything outside it still raises.
_SUPPORT_LABELS = {"entailment", "entail", "label_entailment", "supports", "supported",
                   "support", "consistent", "factual", "true"}


def _entailment_index(config) -> tuple[int, dict]:
    """Find the supported/entailment logit by NAME. Raises rather than guessing an index."""
    id2label = {int(k): str(v) for k, v in (config.id2label or {}).items()}
    for i, name in id2label.items():
        if name.strip().lower().replace("-", "_").replace(" ", "_") in _SUPPORT_LABELS:
            return i, id2label
    raise ValueError(
        f"no label named 'entailment' in id2label={id2label}; refusing to guess an index, "
        "because guessing wrong inverts the score and looks like model disagreement")


def _run(model_id: str, family: str, pairs: list[tuple[str, str]], batch_size: int) -> dict:
    import os as _os

    import torch
    torch.set_num_threads(max(1, int(_os.environ.get("VERIFIER_THREADS")
                                     or _os.cpu_count() or 1)))
    from transformers import (
        AutoModelForSeq2SeqLM,
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    meta: dict = {"family": family, "max_length": MAX_LEN.get(family, 512)}
    t0 = time.time()

    if family == "hhem-custom":
        model = AutoModelForSequenceClassification.from_pretrained(model_id,
                                                                   trust_remote_code=True)
        load_s = time.time() - t0
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        got: dict[int, float] = {}
        t1 = time.time()
        with torch.inference_mode():
            for b in range(0, len(order), batch_size):
                sel = order[b:b + batch_size]
                for i, v in zip(sel, model.predict([pairs[j] for j in sel])):
                    got[i] = float(v)
        scores = [got[i] for i in range(len(pairs))]
        return {"scores": scores, "load_seconds": round(load_s, 2),
                "predict_seconds": round(time.time() - t1, 2), **meta}

    tok = AutoTokenizer.from_pretrained(model_id)

    if family == "nli-entailment":
        model = AutoModelForSequenceClassification.from_pretrained(model_id)
        model.eval()
        load_s = time.time() - t0
        ent_i, id2label = _entailment_index(model.config)
        meta.update({"entailment_index": ent_i, "id2label": id2label})
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        got = {}
        t1 = time.time()
        with torch.inference_mode():
            for b in range(0, len(order), batch_size):
                sel = order[b:b + batch_size]
                enc = tok([pairs[i][0] for i in sel], [pairs[i][1] for i in sel],
                          max_length=meta["max_length"], truncation="only_first",
                          padding=True, return_tensors="pt")
                probs = torch.softmax(model(**enc).logits, dim=-1)[:, ent_i]
                for i, p in zip(sel, probs.tolist()):
                    got[i] = float(p)
        return {"scores": [got[i] for i in range(len(pairs))], "load_seconds": round(load_s, 2),
                "predict_seconds": round(time.time() - t1, 2), **meta}

    # --- the two MiniCheck families: chunk, score every chunk, take the max ---
    if family == "seq2seq-minicheck":
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
        chunker = lambda d: _word_chunks(d, CHUNK_WORDS)                       # noqa: E731
    elif family == "seqclass-minicheck":
        model = AutoModelForSequenceClassification.from_pretrained(model_id)
        def chunker(d, _tok=tok):
            norm = _normalise(d)
            ids = _tok(norm, add_special_tokens=False)["input_ids"]
            if len(ids) <= CHUNK_TOKENS:
                return [norm]
            return [_tok.decode(ids[i:i + CHUNK_TOKENS])
                    for i in range(0, len(ids), CHUNK_TOKENS)]
    else:
        raise ValueError(f"unknown family {family!r}")
    model.eval()
    load_s = time.time() - t0

    flat: list[tuple[int, str]] = []
    for i, (premise, _h) in enumerate(pairs):
        for ch in chunker(premise):
            flat.append((i, ch))
    meta["n_chunks"] = len(flat)
    order = sorted(range(len(flat)), key=lambda k: len(flat[k][1]) + len(pairs[flat[k][0]][1]))

    best: dict[int, float] = {}
    t1 = time.time()
    with torch.inference_mode():
        for b in range(0, len(order), batch_size):
            sel = order[b:b + batch_size]
            joined = [flat[k][1] + tok.eos_token + pairs[flat[k][0]][1] for k in sel]
            if family == "seq2seq-minicheck":
                enc = tok(["predict: " + t for t in joined], max_length=meta["max_length"],
                          truncation=True, padding=True, return_tensors="pt")
                dec = torch.zeros((enc["input_ids"].size(0), 1), dtype=torch.long)
                logits = model(input_ids=enc["input_ids"],
                               attention_mask=enc["attention_mask"],
                               decoder_input_ids=dec).logits.squeeze(1)
                probs = torch.softmax(logits[:, torch.tensor(FLAN_LABEL_TOKENS)], dim=-1)[:, 1]
            else:
                enc = tok(joined, max_length=meta["max_length"], truncation=True,
                          padding=True, return_tensors="pt")
                probs = torch.softmax(model(**enc).logits, dim=-1)[:, 1]
            for k, p in zip(sel, probs.tolist()):
                idx = flat[k][0]
                if p > best.get(idx, -1.0):
                    best[idx] = float(p)
    return {"scores": [best[i] for i in range(len(pairs))], "load_seconds": round(load_s, 2),
            "predict_seconds": round(time.time() - t1, 2), **meta}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: _verifier_sidecar.py <input.json> <output.json>", file=sys.stderr)
        return 2
    in_path, out_path = sys.argv[1], sys.argv[2]
    try:
        with open(in_path) as fh:
            payload = json.load(fh)
        result = _run(payload["model_id"], payload["family"],
                      [(str(p), str(h)) for p, h in payload["pairs"]],
                      int(payload.get("batch_size") or 8))
        result.update({"ok": True, "model": payload["model_id"],
                       "n": len(result["scores"]), "python": sys.version.split()[0]})
        import torch
        result["torch_threads"] = torch.get_num_threads()
    except Exception as exc:
        import traceback
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc()}
    tmp = out_path + ".partial"
    with open(tmp, "w") as fh:
        json.dump(result, fh)
    import os
    os.replace(tmp, out_path)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
