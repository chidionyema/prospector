"""E-101 Stage B — Bespoke-MiniCheck-7B on the lab host, from the reference implementation.

Stage A measured eleven arms up to 400M parameters and every one of them lost to token overlap.
The obvious objection is that they were all too small. Stage B is the test of that objection: a 7B
causal model, purpose-trained for exactly this task, on the same 3,472 frozen pairs.

**Pre-registered refuting outcome.** Stage A found that in BOTH families with two sizes the LARGER
model scored WORSE (`nli-fever-lg` 0.4495 < `nli-fever-bs` 0.4836; `minicheck-t5` 0.4973 <
`minicheck-rob` 0.7136). If Bespoke-MiniCheck-7B also fails to beat `lex-token`'s 0.8273, scale is
ruled out across roughly three orders of magnitude of parameter count and the local-classifier route
is closed, not merely unproven. If it DOES beat 0.8273, Stage A's conclusion is wrong about scale
and this programme has a local verifier worth the engineering.

THE IMPLEMENTATION IS FROM THE REFERENCE, NOT FROM MEMORY. Fetched 2026-08-20 from
github.com/Liyan06/MiniCheck:

    minicheck/utils.py
      SYSTEM_PROMPT = "Determine whether the provided claim is consistent with the corresponding
      document. Consistency in this context implies that all information presented in the claim is
      substantiated by the document. If not, it should be considered inconsistent. Please assess
      the claim's consistency with the document by responding with either "Yes" or "No"."
      USER_PROMPT   = "Document: [DOCUMENT]\\nClaim: [CLAIM]"

    minicheck/inference.py, LLMCheck
      user_prompt = self.user_prompt.replace("[DOCUMENT]", doc).replace("[CLAIM]", claim)
      message = [{"role": "system", ...}, {"role": "user", ...}]
      SamplingParams(temperature=0, max_tokens=..., stop_token_ids=..., logprobs=5)
      for token_prob in response.outputs[0].logprobs[0].values():
          if token_prob.decoded_token.lower() == 'yes':
              support_prob += math.exp(token_prob.logprob)

THREE DEVIATIONS, RECORDED RATHER THAN HIDDEN.

1.  vLLM is replaced by one transformers forward pass. The reference reads the logprobs of the
    FIRST generated token; that distribution is fully determined by a single forward pass over the
    prompt, so generating is wasted work at temperature 0. Same number, far less compute.

2.  The reference sums over the top FIVE logprobs only, so a prompt where "Yes" falls outside the
    top 5 scores exactly 0.0 — a floor that is an artefact of the sampler, not of the model. This
    file sums over the FULL vocabulary and also records the top-5-restricted value, so the size of
    that artefact is measured instead of assumed. `auc_top5` in the receipt is the reference's own
    number; `auc` is the full-vocabulary one. If they disagree the receipt says so.

3.  No sentence fusion and no chunking. The reference splits a multi-sentence claim, scores each
    sentence against each chunk, and takes min-over-sentences of max-over-chunks. Premises here are
    clipped to 1,500 characters by `_groundedness.py:35` so there is never more than one chunk, and
    the Stage A MiniCheck arms were run the same single-claim way. Matching them matters more than
    matching a code path that is a no-op on this corpus, because the comparison across arms is the
    experiment.

TRUST_REMOTE_CODE. The checkpoint is InternLM2 (not a stock architecture), so transformers refuses
to load it without `trust_remote_code=True`. Read before trusting, per LAW 2: the four .py files in
the snapshot are the InternLM team's published Apache-2.0 tokenizer and modelling code, and a scan
for `urllib|requests|socket|subprocess|os.system|popen|eval(|exec(|__import__|pickle|base64` matches
exactly one line — the tokenizer writing its own vocab file. It runs on the disposable lab host,
which holds no estate credentials, and nowhere else.

**Loading is CHECKED, not assumed.** `output_loading_info=True` returns the keys transformers could
not fill, and this file refuses to score if there are any. Memory
`a-remote-code-model-can-load-as-a-different-model` is exactly this trap: transformers 5.x handed
HHEM a newly initialised embedding table, which produces a fully working model that has learned
nothing and a plausible-looking AUC near chance — indistinguishable from the finding this experiment
is trying to measure.

Runs on the Fly lab host only: 7B weights, 32 GB of RAM, and no estate credentials anywhere near it.

    BATCH=4 python3 e101_stageB_fly.py bespoke-7b
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DATA = Path("/data")

ARMS = {
    # name          model id                                      hf revision pin
    "bespoke-7b": ("bespokelabs/Bespoke-MiniCheck-7B", "1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8"),
}

SYSTEM_PROMPT = (
    "Determine whether the provided claim is consistent with the corresponding document. "
    "Consistency in this context implies that all information presented in the claim is "
    "substantiated by the document. If not, it should be considered inconsistent. Please assess "
    "the claim's consistency with the document by responding with either \"Yes\" or \"No\"."
)
USER_PROMPT = "Document: [DOCUMENT]\nClaim: [CLAIM]"


def yes_token_ids(tok) -> tuple[list[int], list[int]]:
    """Every vocabulary id whose decoded form is the word "yes", and the same for "no".

    Decoded rather than looked up: the tokenizer emits "Yes", " Yes", "yes" and "▁Yes" as different
    ids, the reference compares `decoded_token.lower() == 'yes'`, and a hardcoded id list is the
    same class of defect as a hardcoded NLI label index — it produces a confident wrong number on
    the next model. See memory `an-nli-label-index-must-be-read-by-name`.
    """
    yes, no = [], []
    for i in range(len(tok)):
        d = tok.convert_ids_to_tokens(i)
        if d is None:
            continue
        w = tok.convert_tokens_to_string([d]).strip().lower()
        if w == "yes":
            yes.append(i)
        elif w == "no":
            no.append(i)
    if not yes:
        raise SystemExit("no vocabulary token decodes to 'yes' — the scorer would report 0.0 for "
                         "every pair, which reads as a model that supports nothing")
    return yes, no


def main() -> int:
    # The weights cache is pinned HERE, not in the launch command, because a launch command is a
    # thing a human retypes. Measured 2026-08-20: one relaunch omitted HF_HOME, transformers
    # silently fell back to ~/.cache/huggingface on the 7.8 GB ROOT filesystem, re-downloaded 15 GB
    # of shards that were already on the 59 GB volume, filled / to 100% and died with
    # `RuntimeError: Internal error: Internal Writer Error: Background writer channel closed` — a
    # message that names a writer, not a disk, and cost 15 minutes to read as "full disk".
    # setdefault, not assignment, so an operator can still override it.
    #
    # It sits INSIDE main(), not at module level, and that placement is load-bearing in two
    # directions. It must run BEFORE transformers is imported, which is the only point at which it
    # has any effect -- hence above the two imports below, not lower down. And it must NOT run at
    # import time: `experiment_runner.discover()` imports every module in this directory to read
    # its registration, so a module-level `os.environ[...] = ...` leaks into whichever pytest
    # worker imported it and poisons every later test in that worker. tests/conftest.py:172 catches
    # exactly that and failed the whole suite with `1 error` at TEARDOWN of an unrelated test --
    # `test_discover_defaults_to_the_real_experiments_directory` -- which is the trap that guard
    # exists to name: the test that fails is never the test that leaked.
    os.environ.setdefault("HF_HOME", str(DATA / "hf"))

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    name = sys.argv[1] if len(sys.argv) > 1 else "bespoke-7b"
    model_id, revision = ARMS[name]
    batch = int(os.environ.get("BATCH", "4"))
    limit = int(os.environ.get("LIMIT", "0"))

    hf_home = Path(os.environ["HF_HOME"]).resolve()
    if not str(hf_home).startswith(str(DATA)):
        raise SystemExit(f"HF_HOME is {hf_home}, which is not under {DATA}. The root filesystem on "
                         f"this host is 7.8 GB and these weights are 15 GB: the run would fill it "
                         f"and fail with a message about a writer channel, not about disk.")

    frozen = json.loads((DATA / "e101_pairs.json").read_text())
    pairs = [tuple(p) for p in frozen["pairs"]]
    if limit:
        pairs = pairs[:limit]

    print(f"{name}: {model_id}@{revision[:8]}  {len(pairs)} pairs, batch {batch}", flush=True)
    tok = AutoTokenizer.from_pretrained(model_id, revision=revision, trust_remote_code=True)
    tok.padding_side = "left"          # the score is read at the LAST position
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    yes_ids, no_ids = yes_token_ids(tok)
    print(f"  yes ids {yes_ids[:8]}{'...' if len(yes_ids) > 8 else ''} ({len(yes_ids)}), "
          f"no ids {len(no_ids)}", flush=True)

    t_load = time.time()
    model, info = AutoModelForCausalLM.from_pretrained(
        model_id, revision=revision, dtype=torch.bfloat16, low_cpu_mem_usage=True,
        trust_remote_code=True, output_loading_info=True)
    missing = info.get("missing_keys") or []
    if missing:
        raise SystemExit(
            f"{len(missing)} weights were NOT loaded from the checkpoint and are randomly "
            f"initialised: {missing[:8]}. Scoring would produce a confident number from a model "
            f"that has not learned this task. See memory "
            f"a-remote-code-model-can-load-as-a-different-model.")
    model.eval()
    print(f"  loaded in {time.time() - t_load:.1f}s, missing_keys 0, "
          f"unexpected {len(info.get('unexpected_keys') or [])}", flush=True)

    prompts = [
        tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": USER_PROMPT.replace("[DOCUMENT]", p)
                                                    .replace("[CLAIM]", h)}],
            tokenize=False, add_generation_prompt=True)
        for p, h in pairs
    ]

    scores, scores_top5 = [], []
    t0 = time.time()
    with torch.no_grad():
        for i in range(0, len(prompts), batch):
            enc = tok(prompts[i:i + batch], return_tensors="pt", padding=True, truncation=True,
                      max_length=2048, add_special_tokens=False)
            logits = model(**enc).logits[:, -1, :].float()
            probs = torch.softmax(logits, dim=-1)
            scores.extend(probs[:, yes_ids].sum(dim=-1).tolist())
            # the reference's own view: only the top 5 tokens are visible to it
            top = torch.topk(probs, 5, dim=-1)
            for row_v, row_i in zip(top.values.tolist(), top.indices.tolist()):
                scores_top5.append(sum(v for v, j in zip(row_v, row_i) if j in set(yes_ids)))
            if (i // batch) % 20 == 0:
                done = min(i + batch, len(prompts))
                rate = done / (time.time() - t0)
                print(f"  {done}/{len(prompts)}  {rate:.2f} pairs/s  "
                      f"eta {(len(prompts) - done) / max(rate, 1e-9) / 60:.0f}m", flush=True)

    wall = time.time() - t0
    dest = DATA / "scores" / f"{name}.json"
    dest.write_text(json.dumps({
        "arm": name, "scores": scores, "scores_top5_reference": scores_top5,
        "corpus_fingerprint": frozen["corpus_fingerprint"],
        "scored_on": "fly:prospector-verifier-lab:performance-16x",
        "wall_seconds": round(wall, 2), "pairs_per_second": round(len(pairs) / wall, 3),
        "meta": {"model_id": model_id, "revision": revision, "dtype": "bfloat16",
                 "n_yes_token_ids": len(yes_ids), "n_no_token_ids": len(no_ids),
                 "trust_remote_code": True, "missing_keys": 0,
                 "batch": batch, "limit": limit,
                 "deviations": ["single forward pass instead of vLLM generate",
                                "full-vocabulary yes-mass; top-5 reference value recorded beside it",
                                "no sentence fusion, no chunking (premises clipped to 1500 chars)"]},
    }))
    print(f"{name}: done {wall:.1f}s ({len(pairs)/wall:.2f} pairs/s) -> {dest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
