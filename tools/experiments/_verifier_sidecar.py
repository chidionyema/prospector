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

THE SIX FAMILIES, EACH IMPLEMENTED FROM ITS REFERENCE AND NOT FROM MEMORY.

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

`causal-minicheck` — bespokelabs/Bespoke-MiniCheck-7B, the current LLM-AggreFact leader. Read from
    the same repo's `inference.py` (`LLMCheck`) plus `utils.py` for the prompts:
      input   the chat template over SYSTEM_PROMPT and "Document: ...\nClaim: ...", with
              add_generation_prompt=True
      score   probability mass on the word "yes" in the FIRST generated position
      chunks  max over document chunks per claim sentence, then MIN over claim sentences
    Two deliberate departures, both in the receipts. The reference runs vLLM and sums exp(logprob)
    over the top-k decoded tokens; this runs plain transformers and sums the FULL softmax over
    every id that decodes to "yes", which is the same quantity computed exactly rather than
    truncated at k. And nltk Punkt is replaced by a regex sentence split, which `n_multi_sentence`
    shows barely fires on this corpus.

`causal-judge` — PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct, prompt verbatim from the model card.
    Lynx is a GENERATIVE judge: it is trained to write REASONING and only then a SCORE of PASS or
    FAIL, roughly 600 tokens in. Generating that for 3,472 pairs on CPU is not affordable, so the
    JSON prefix is teacher-forced and the PASS/FAIL choice is read at the next position, normalised
    P(PASS)/(P(PASS)+P(FAIL)). THIS REMOVES THE MODEL'S CHAIN OF THOUGHT. A weak AUC here is a
    lower bound on Lynx and must never be reported as Lynx's score; the faithful run needs a GPU
    and belongs in a separate stage. The corpus also has no question field, so the QUESTION slot
    carries a declared constant.

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
           "nli-entailment": 512, "hhem-custom": 512,
           # The two causal references allow far more (Bespoke 32,768; Lynx 8,000). These windows
           # are CPU budgets, not the references' limits, and they are safe on THIS corpus only
           # because premises are clipped to 1,500 characters upstream. `n_over_window` in the
           # receipts counts any pair that actually hit the cap, so the assumption is measured
           # rather than asserted.
           "causal-minicheck": 4096, "causal-judge": 4096}

# Verbatim from github.com/Liyan06/MiniCheck `minicheck/utils.py`, fetched 2026-08-20. The wording
# is part of the instrument: this model was fine-tuned against these exact strings, so an
# "improved" prompt measures a different model.
BESPOKE_SYSTEM_PROMPT = (
    "Determine whether the provided claim is consistent with the corresponding document. "
    "Consistency in this context implies that all information presented in the claim is "
    "substantiated by the document. If not, it should be considered inconsistent. Please assess "
    "the claim's consistency with the document by responding with either \"Yes\" or \"No\"."
)
BESPOKE_USER_PROMPT = "Document: [DOCUMENT]\nClaim: [CLAIM]"

# Verbatim from the PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct model card, fetched 2026-08-20.
LYNX_PROMPT = """Given the following QUESTION, DOCUMENT and ANSWER you must analyze the provided answer and determine whether it is faithful to the contents of the DOCUMENT. The ANSWER must not offer new information beyond the context provided in the DOCUMENT. The ANSWER also must not contradict information provided in the DOCUMENT. Output your final verdict by strictly following this format: "PASS" if the answer is faithful to the DOCUMENT and "FAIL" if the answer is not faithful to the DOCUMENT. Show your reasoning.

--
QUESTION (THIS DOES NOT COUNT AS BACKGROUND INFORMATION):
{question}

--
DOCUMENT:
{context}

--
ANSWER:
{answer}

--

Your output should be in JSON FORMAT with the keys "REASONING" and "SCORE":
{{"REASONING": <your reasoning as bullet points>, "SCORE": <your final score>}}"""

# Lynx wants a question its two siblings do not. This corpus has no question field -- a check
# holds a claim and the passages retrieved for it, not the question a user asked -- so rather than
# invent one per pair, the slot is filled with the task itself and the substitution is declared.
# The model card states the question is not background information, which is what makes a constant
# defensible here. It is still a deviation and it is in the receipts.
LYNX_NO_QUESTION = "Is the claim below supported by the document?"
LYNX_FORCED_PREFIX = '{"REASONING": ["<omitted>"], "SCORE": "'

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _sentences(claim: str) -> list[str]:
    """Split a claim the way the 7B reference does, to the extent this corpus needs it.

    The reference uses nltk's Punkt tokenizer. That is a dependency this sidecar does not have and
    a download this experiment will not make, so the split is a regex on terminal punctuation
    followed by a capital or a digit. It is weaker than Punkt on abbreviations ("Inc. The" splits,
    "approx. 5" splits), and the honest defence is that it barely fires: `n_multi_sentence` in the
    receipts reports how many of the corpus's claims produced more than one sentence at all. If
    that count is 0 the difference between this and Punkt cannot have moved any score.
    """
    parts = [s.strip() for s in _SENT_SPLIT.split(claim.strip()) if s.strip()]
    return parts or [claim.strip()]


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


def _run(model_id: str, family: str, pairs: list[tuple[str, str]], batch_size: int,
         revision: str | None = None) -> dict:
    import os as _os

    import torch
    torch.set_num_threads(max(1, int(_os.environ.get("VERIFIER_THREADS")
                                     or _os.cpu_count() or 1)))
    from transformers import (
        AutoModelForSeq2SeqLM,
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    meta: dict = {"family": family, "max_length": MAX_LEN.get(family, 512),
                  "revision": revision}
    # None means "whatever refs/main is today", which is how nine arms came to be
    # scored from a commit nobody recorded. Passed through to every from_pretrained
    # below so the pin in the registry is load-bearing and not decorative.
    _rev = {"revision": revision} if revision else {}
    t0 = time.time()

    if family == "hhem-custom":
        model = AutoModelForSequenceClassification.from_pretrained(model_id, **_rev,
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

    tok = AutoTokenizer.from_pretrained(model_id, **_rev)

    if family == "nli-entailment":
        model = AutoModelForSequenceClassification.from_pretrained(model_id, **_rev)
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

    # --- the two 7B/8B causal families: score a single decision token, never a generation ---
    if family in ("causal-minicheck", "causal-judge"):
        from transformers import AutoModelForCausalLM

        # LEFT padding is not a style choice. Both families read the next-token distribution at
        # the LAST position, and with the default right padding that position holds a pad token,
        # so every score in a padded batch would be the model's opinion about padding. It would
        # not look broken -- it would look like a model that disagrees with the moat, which is the
        # finding this experiment exists to measure.
        tok.padding_side = "left"
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token

        # Device and dtype are chosen here and REPORTED, never assumed. A 7B float32 forward pass
        # over a 400-token prompt is about 5.6 TFLOPs; measured on the 16-core Fly host that is
        # roughly 112 s/pair, so 3,472 pairs is four days. These two arms are GPU arms and the
        # receipts must say which device actually ran them, because "bespoke-7b scored 0.7" means
        # different things at float32 and at bfloat16.
        if torch.cuda.is_available():
            device, dtype = "cuda", torch.bfloat16
        else:
            device, dtype = "cpu", torch.float32
        # VERIFIER_DTYPE exists because the CPU answer is not knowable in advance. torch routes
        # bfloat16 matmul through oneDNN, which is fast on hardware with AVX512-BF16 (AMD Genoa)
        # and SLOWER than float32 on hardware without it (AMD Milan), because it upcasts. Which
        # one this rented host is cannot be assumed, so both are measurable and the receipts say
        # which ran. float32 also needs ~28 GB for a 7B model against this box's 32 GB.
        override = _os.environ.get("VERIFIER_DTYPE")
        if override:
            dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16,
                     "float16": torch.float16}[override]
        model = AutoModelForCausalLM.from_pretrained(model_id, **_rev, trust_remote_code=True, dtype=dtype)
        model.eval().to(device)
        load_s = time.time() - t0
        max_len = meta["max_length"]
        meta.update({"device": device, "dtype": str(dtype)})

        def _ids_for(words: tuple[str, ...]) -> list[int]:
            """Every token id that decodes to one of `words`, ignoring case and word-start marks.

            The reference sums probability mass over vLLM's top-k logprobs wherever
            `decoded_token.lower() == 'yes'`, so the quantity is "mass on the word", not "mass on
            one id". A tokenizer spells that word several ways -- 'yes', 'Yes', 'YES', and again
            with a leading space mark -- and picking a single id silently drops the rest.
            """
            want = {w.lower() for w in words}
            out = []
            for tokstr, tid in tok.get_vocab().items():
                if tokstr.lstrip("▁Ġ ").lower() in want:
                    out.append(int(tid))
            if not out:
                raise ValueError(
                    f"tokenizer has no id decoding to any of {sorted(want)}; refusing to guess a "
                    "decision token, because a wrong one inverts the score silently")
            return sorted(out)

        if family == "causal-minicheck":
            pos_ids, neg_ids = _ids_for(("yes",)), _ids_for(("no",))
            # The reference chunks at max_model_len - 300 TOKENS and caps context at 32768. On
            # this corpus that is one chunk for every pair (premises are clipped to 1,500 chars
            # by _groundedness.py:35), so max_length is set to a CPU-affordable window instead and
            # the over-window count is reported rather than assumed to be zero.
            def build(chunk: str, claim: str) -> str:
                return tok.apply_chat_template(
                    [{"role": "system", "content": BESPOKE_SYSTEM_PROMPT},
                     {"role": "user",
                      "content": BESPOKE_USER_PROMPT.replace("[DOCUMENT]", chunk)
                                                    .replace("[CLAIM]", claim)}],
                    add_generation_prompt=True, tokenize=False)
        else:
            pos_ids, neg_ids = _ids_for(("pass",)), _ids_for(("fail",))

            def build(chunk: str, claim: str) -> str:
                body = LYNX_PROMPT.format(question=LYNX_NO_QUESTION, context=chunk, answer=claim)
                text = tok.apply_chat_template([{"role": "user", "content": body}],
                                               add_generation_prompt=True, tokenize=False)
                # Lynx is trained to emit REASONING before SCORE, so the decision token is ~600
                # tokens into a generation. Generating that for 3,472 pairs on CPU is not
                # affordable, so the JSON prefix is TEACHER-FORCED and the distribution over
                # PASS/FAIL is read at the next position. This is a deviation from the reference
                # and it is recorded in the receipts: it removes the model's chain of thought, so
                # a low AUC here is a LOWER BOUND on Lynx and not a refutation of it.
                return text + LYNX_FORCED_PREFIX

        # The reference splits the CLAIM into sentences, takes the max over document chunks per
        # sentence, then the MIN over sentences -- one unsupported sentence condemns the claim.
        # Both reductions are implemented; `n_multi_sentence` says whether either did any work.
        units: list[tuple[int, int, str]] = []          # (pair, sentence, prompt)
        multi = 0
        for i, (premise, hypothesis) in enumerate(pairs):
            sents = _sentences(hypothesis)
            if len(sents) > 1:
                multi += 1
            for s_i, sent in enumerate(sents):
                for chunk in _word_chunks(premise, CHUNK_WORDS):
                    units.append((i, s_i, build(chunk, sent)))
        meta.update({"n_units": len(units), "n_multi_sentence": multi,
                     "padding_side": tok.padding_side,
                     "positive_ids": pos_ids, "negative_ids": neg_ids,
                     "forced_prefix": LYNX_FORCED_PREFIX if family == "causal-judge" else None})

        order = sorted(range(len(units)), key=lambda k: len(units[k][2]))
        by_sentence: dict[tuple[int, int], float] = {}
        over = 0
        t1 = time.time()
        with torch.inference_mode():
            for b in range(0, len(order), batch_size):
                sel = order[b:b + batch_size]
                enc = tok([units[k][2] for k in sel], add_special_tokens=False,
                          max_length=max_len, truncation=True, padding=True,
                          return_tensors="pt").to(device)
                over += int((enc["input_ids"].size(1) >= max_len)
                            and sum(1 for k in sel if len(tok(units[k][2],
                                    add_special_tokens=False)["input_ids"]) > max_len))
                probs = torch.softmax(model(**enc).logits[:, -1, :].float(), dim=-1)
                pos = probs[:, torch.tensor(pos_ids)].sum(dim=-1)
                if family == "causal-judge":
                    # PASS and FAIL are the only two legal SCORE values, so the honest quantity is
                    # the choice BETWEEN them, not the absolute mass on PASS -- a model that spends
                    # most of its mass on a quote character would otherwise score near zero for
                    # every pair and produce an AUC of 0.5 by construction.
                    neg = probs[:, torch.tensor(neg_ids)].sum(dim=-1)
                    vals = (pos / (pos + neg).clamp_min(1e-12)).tolist()
                else:
                    vals = pos.tolist()
                for k, v in zip(sel, vals):
                    key = (units[k][0], units[k][1])
                    if v > by_sentence.get(key, -1.0):       # max over document chunks
                        by_sentence[key] = float(v)
        scores = []
        for i in range(len(pairs)):
            per = [v for (p, _s), v in by_sentence.items() if p == i]
            scores.append(min(per))                          # min over claim sentences
        meta["n_over_window"] = over
        return {"scores": scores, "load_seconds": round(load_s, 2),
                "predict_seconds": round(time.time() - t1, 2), **meta}

    # --- the two MiniCheck families: chunk, score every chunk, take the max ---
    if family == "seq2seq-minicheck":
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id, **_rev)
        chunker = lambda d: _word_chunks(d, CHUNK_WORDS)                       # noqa: E731
    elif family == "seqclass-minicheck":
        model = AutoModelForSequenceClassification.from_pretrained(model_id, **_rev)
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
                      int(payload.get("batch_size") or 8),
                      payload.get("revision"))
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
