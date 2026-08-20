#!/usr/bin/env python3
"""The arm registry for the local-verifier sweep: one interface, many scorers, one pair set.

WHY A REGISTRY AND NOT A SECOND PAIRWISE EXPERIMENT. E17 compared HHEM against the moat and
answered one question. The founder's instruction on 2026-08-20 was to exhaust the options rather
than sample them, so the shape has to make adding an arm cheap and comparing arms exact. Every arm
here scores the IDENTICAL frozen pair set and returns P(hypothesis is supported by premise) in
0..1, so AUCs are directly comparable and disagreements are attributable to the model rather than
to the sample.

THE LEXICAL ARMS ARE NOT FILLER, THEY ARE THE FLOOR. A 435M-parameter entailment model that does
not separate the moat's ruled checks from its unverifiable ones better than counting shared words
is not worth deploying, however good its leaderboard row. Any neural result in this sweep is read
against `lex-token` first. They also cost nothing: no download, no sidecar, no torch.

WHERE EACH ARM RUNS, AND WHY THAT IS DECIDED BY FILE FORMAT RATHER THAN SIZE. Measured 2026-08-20:
transformers 4.57.6 refuses `torch.load` on a `.bin` checkpoint unless torch >= 2.6 (CVE-2025-32434),
and macOS x86_64 has no torch above 2.2.2 -- the last release for this platform. So the entire
MiniCheck family, which publishes pickle only, cannot be loaded on this laptop at ANY size, while
`bespoke-7b` at 15.5 GB is safetensors and would load fine if the disk and the hours existed. The
`fmt` field is therefore load-bearing, not documentation. Pickle arms and the multi-billion arms
run on a disposable Fly host; safetensors arms under 1 GB run here.

There is a security reason to like that split. Loading a pickle checkpoint executes arbitrary code
at load time -- that is what the CVE is about. Doing it on a throwaway machine rather than the
laptop holding the estate's credentials is the correct place for it, so the constraint and the
right answer happen to agree.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "_verifier_cache"
SIDECAR_SCRIPT = HERE / "_verifier_sidecar.py"
HF_HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"


class Arm:
    def __init__(self, name, model_id, family, weights_gb, fmt, where, note, revision=None):
        self.name, self.model_id, self.family = name, model_id, family
        self.weights_gb, self.fmt, self.where, self.note = weights_gb, fmt, where, note
        # A model id names a repository, and a repository moves. `revision` names the ONE commit
        # whose weights produced this programme's numbers. Added 2026-08-20 after building the
        # sources table in docs/ENGINE_100X_PROGRAM.md found that nine of the thirteen arms had
        # been scored with no revision at all: `_verifier_sidecar.py` called
        # `from_pretrained(model_id)` bare. A re-run against a moved checkpoint returns a different
        # number with no error and no warning, which is indistinguishable from a finding.
        self.revision = revision

    @property
    def is_lexical(self) -> bool:
        return self.family == "lexical"

    @property
    def cache_dir_name(self) -> str:
        return "models--" + self.model_id.replace("/", "--")

    def on_disk(self) -> bool:
        return self.is_lexical or (HF_HUB / self.cache_dir_name).exists()

    def __repr__(self) -> str:
        return f"<Arm {self.name} {self.family} {self.where}>"


def unpinned_arms() -> list[str]:
    """Arms that name a model but no commit. `tests/test_verifier_arms_are_pinned.py` fails on any.

    A list rather than a boolean so the failure message can name them.
    """
    return sorted(n for n, a in ARMS.items() if not a.is_lexical and not a.revision)


# Sizes measured 2026-08-20 from the HF tree API; fmt is what the repo actually publishes.
ARMS: dict[str, Arm] = {a.name: a for a in [
    # ---- the floor: no model, no download, no sidecar ----
    Arm("lex-token",  "-", "lexical", 0.0, "-", "local",
        "share of the hypothesis's content words that appear in the premise"),
    Arm("lex-3gram",  "-", "lexical", 0.0, "-", "local",
        "character 3-gram containment; robust to inflection and tokenisation"),
    Arm("lex-number", "-", "lexical", 0.0, "-", "local",
        "share of the hypothesis's numbers, dates and money that appear in the premise"),
    # ---- safetensors, small: run on the laptop ----
    Arm("hhem", "vectara/hallucination_evaluation_model", "hhem-custom", 0.44, "safetensors",
        "local", "HHEM-2.1-Open, 184M. The E17 baseline: AUC 0.673 on this corpus.",
        revision="8e4a2e6e96c708cc76c2344f7e4757df2515292c"),
    Arm("nli-fever-bs", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli", "nli-entailment", 0.37,
        "safetensors", "local", "184M, FEVER-trained. FEVER's 3 classes map onto ours exactly.",
        revision="6f5cf0a2b59cabb106aca4c287eed12e357e90eb"),
    Arm("nli-fever-lg", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli",
        "nli-entailment", 0.87, "safetensors", "local", "435M, the strong general NLI arm.",
        revision="b3546ea6b0346eb6f8d5d68b13c7dc6d0376b3d7"),
    Arm("vitaminc", "tals/albert-xlarge-vitaminc-mnli", "nli-entailment", 0.23, "safetensors",
        "local", "59M, trained on VitaminC: contrastive evidence, built for fact verification.",
        revision="3082ba54344bd9ddada2be1c5e9b4131721d2a5d"),
    # ---- pickle only: cannot load under torch 2.2.2, Fly ----
    Arm("minicheck-t5", "lytang/MiniCheck-Flan-T5-Large", "seq2seq-minicheck", 3.13, "pickle",
        "fly", "770M. Best fact-checker under 1B; the arm E17 explicitly left open.",
        revision="96eafd01cee2d16cf81aaa2fb226b14f422a37b3"),
    Arm("minicheck-deb", "lytang/MiniCheck-DeBERTa-v3-Large", "seqclass-minicheck", 1.74,
        "pickle", "fly", "435M MiniCheck.",
        revision="2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb"),
    Arm("minicheck-rob", "lytang/MiniCheck-RoBERTa-Large", "seqclass-minicheck", 1.42, "pickle",
        "fly", "355M MiniCheck; 512-token window, matching our 1500-char premise clip.",
        revision="74c8919647e61ed0f71bc177d94f10930f090068"),
    Arm("nli-mnli-lg", "microsoft/deberta-large-mnli", "nli-entailment", 1.63, "pickle", "fly",
        "The classic MNLI baseline. Labels are ordered CONTRADICTION/NEUTRAL/ENTAILMENT.",
        revision="7296194b9009373def4f7c5dad292651e4b5cf4e"),
    # ---- large: Fly, GPU ----
    Arm("bespoke-7b", "bespokelabs/Bespoke-MiniCheck-7B", "causal-minicheck", 15.48,
        "safetensors", "fly", "77.4% on LLM-AggreFact -- SOTA, above Claude 3.5 Sonnet.",
        revision="1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8"),
    Arm("lynx-8b", "PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct", "causal-judge", 16.06,
        "safetensors", "fly", "Hallucination judge trained as an instruct model."),
]}

# ----------------------------------------------------------------------------- lexical arms

_WORD = re.compile(r"[a-z0-9]+")
_NUMLIKE = re.compile(
    r"(?:\d[\d,]*\.?\d*\s*(?:%|percent|bn|billion|m|million|k)?|"
    r"[£$€]\s?\d[\d,]*\.?\d*|\b(?:19|20)\d{2}\b)", re.I)
# Closed-class words carry no evidential weight; leaving them in makes every pair look similar.
_STOP = frozenset("""a an the of to in on for and or but is are was were be been being as at by
with from that this these those it its their his her our your my we you they he she i not no nor
than then so such which who whom whose what when where why how all any both each few more most
other some only own same too very can will just should now do does did done has have had having
if into about against between during before after above below up down out off over under again
further once here there when's while may might must shall would could""".split())


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _lex_token(premise: str, hypothesis: str) -> float:
    """Share of the hypothesis's content words present in the premise. Precision, not Jaccard:
    a long premise should not be penalised for containing more than the claim needs."""
    h = _content_words(hypothesis)
    if not h:
        return 0.0
    p = set(_content_words(premise))
    return sum(1 for w in h if w in p) / len(h)


def _ngrams(text: str, n: int = 3) -> set[str]:
    s = re.sub(r"\s+", " ", text.lower()).strip()
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def _lex_3gram(premise: str, hypothesis: str) -> float:
    h = _ngrams(hypothesis)
    if not h:
        return 0.0
    return len(h & _ngrams(premise)) / len(h)


def _lex_number(premise: str, hypothesis: str) -> float:
    """Numbers are where source-or-die actually bites: a fabricated figure is the costly error.

    A hypothesis with no numbers is not evidence of anything either way, so it falls back to
    `_lex_token` rather than scoring 0 or 1 -- both of which would be a claim this arm cannot
    support. The fallback rate is reported by the experiment so the reader can discount it.
    """
    nums = [re.sub(r"[\s,]", "", m.group(0).lower()) for m in _NUMLIKE.finditer(hypothesis)]
    if not nums:
        return _lex_token(premise, hypothesis)
    flat = re.sub(r"[\s,]", "", premise.lower())
    return sum(1 for n in nums if n in flat) / len(nums)


LEXICAL = {"lex-token": _lex_token, "lex-3gram": _lex_3gram, "lex-number": _lex_number}


def number_fallback_rate(pairs: list[tuple[str, str]]) -> float:
    """How often `lex-number` had no number to check. Reported, never hidden."""
    if not pairs:
        return 0.0
    return sum(1 for _p, h in pairs if not _NUMLIKE.search(h)) / len(pairs)


# ----------------------------------------------------------------------------- scoring

class ArmUnavailable(RuntimeError):
    """This arm cannot run here. Says why, and never silently substitutes another."""


def _cache_path(arm: Arm) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{arm.name}.json"


def _key(arm: Arm, premise: str, hypothesis: str) -> str:
    """Deliberately NOT keyed on arm.revision.

    The revisions added on 2026-08-20 were not chosen, they were RECOVERED by measurement: each is
    the commit the cache on the scoring host had actually resolved and loaded (see "Sources" in
    docs/ENGINE_100X_PROGRAM.md for the `cached_file()` probe that established the three ambiguous
    ones). So every cached score already came from the commit now pinned beside it. Adding the
    revision to the key would invalidate a cache of valid data and force a re-score — on the Fly
    arms, hours of compute — to arrive at exactly the same numbers. If an arm's pin is ever CHANGED
    to a different commit, its cache file must be deleted by hand in the same edit, and that is the
    one thing this decision costs.
    """
    h = hashlib.sha256()
    for part in (arm.name, arm.model_id, arm.family, premise, hypothesis):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:24]


def score_arm(name: str, pairs: list[tuple[str, str]], batch_size: int = 8,
              use_cache: bool = True, progress: bool = True) -> tuple[list[float], dict]:
    """Score every pair with one arm. Returns (scores in input order, meta)."""
    arm = ARMS[name]

    if arm.is_lexical:
        fn = LEXICAL[name]
        import time
        t0 = time.time()
        scores = [fn(p, h) for p, h in pairs]
        return scores, {"arm": name, "family": "lexical", "n": len(scores),
                        "predict_seconds": round(time.time() - t0, 3), "cache_hits": 0}

    if arm.fmt == "pickle":
        raise ArmUnavailable(
            f"{name}: the repo publishes pickle (.bin) only. transformers refuses torch.load "
            "below torch 2.6 (CVE-2025-32434), and macOS x86_64 has no torch above 2.2.2. "
            "This arm runs on the Fly host.")
    if not arm.on_disk():
        raise ArmUnavailable(f"{name}: weights not in {HF_HUB}. Fetch deliberately, then re-run.")

    from _hhem import SIDECAR_PYTHON, require_sidecar
    status = require_sidecar(SIDECAR_SCRIPT)
    cache = {}
    cp = _cache_path(arm)
    if use_cache and cp.exists():
        try:
            cache = json.loads(cp.read_text())
        except Exception:
            cache = {}
    keys = [_key(arm, p, h) for p, h in pairs]
    todo = [i for i, k in enumerate(keys) if k not in cache]
    meta = {"arm": name, "model": arm.model_id, "family": arm.family, "sidecar": status,
            "requested": len(pairs), "cache_hits": len(pairs) - len(todo)}

    if todo:
        if progress:
            print(f"  {name}: scoring {len(todo)} new pairs ({meta['cache_hits']} cached)...",
                  flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            fin, fout = Path(tmp) / "in.json", Path(tmp) / "out.json"
            fin.write_text(json.dumps({"model_id": arm.model_id, "revision": arm.revision,
                                       "family": arm.family,
                                       "batch_size": batch_size,
                                       "pairs": [list(pairs[i]) for i in todo]}))
            env = dict(os.environ)
            env.setdefault("HF_HUB_OFFLINE", "1")
            env.setdefault("TRANSFORMERS_OFFLINE", "1")
            env.setdefault("TOKENIZERS_PARALLELISM", "false")
            proc = subprocess.run([str(SIDECAR_PYTHON), str(SIDECAR_SCRIPT), str(fin), str(fout)],
                                  capture_output=True, text=True, env=env, timeout=60 * 240)
            if not fout.exists():
                raise ArmUnavailable(f"{name}: sidecar produced no output (rc={proc.returncode}). "
                                     f"stderr tail: {proc.stderr.strip()[-600:]}")
            out = json.loads(fout.read_text())
        if not out.get("ok"):
            raise ArmUnavailable(f"{name}: sidecar failed: {out.get('error')}")
        for i, s in zip(todo, out["scores"]):
            cache[keys[i]] = s
        meta["sidecar_run"] = {k: out.get(k) for k in
                               ("n", "n_chunks", "load_seconds", "predict_seconds", "python",
                                "torch_threads", "entailment_index", "id2label", "max_length")}
        if use_cache:
            cp.write_text(json.dumps(cache))
    else:
        meta["sidecar_run"] = None
    return [cache[k] for k in keys], meta


def evict(name: str) -> dict:
    """Delete an arm's weights. Scores are already cached, so this is not destructive to results.

    The disk is the binding constraint on this laptop -- it was at 99% with 5.8 GiB free when the
    sweep was designed -- so the sweep fetches, scores, and gives the space back.
    """
    arm = ARMS[name]
    d = HF_HUB / arm.cache_dir_name
    if arm.is_lexical or not d.exists():
        return {"arm": name, "evicted": False, "reason": "nothing on disk"}
    before = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    shutil.rmtree(d)
    return {"arm": name, "evicted": True, "freed_gb": round(before / 1e9, 2)}


def disk_free_gb() -> float:
    st = os.statvfs(str(Path.home()))
    return round(st.f_bavail * st.f_frsize / 1e9, 2)
