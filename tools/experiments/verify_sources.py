"""Check every external source the programme cites actually resolves, and record the check.

A URL written into a doc is a CLAIM that something is there. This file turns each one into a
measured fact: HTTP status now, and for a paper the title the arXiv API returns, so a reader can
see the identifier and the title agree without leaving the page. Model links are pinned to the
exact commit whose weights produced our numbers, never to a branch that moves.
"""
import json
import re
import time
import urllib.error
import urllib.request

MODELS = {  # arm -> (hf id, commit sha actually loaded, how the sha was established)
 "hhem":        ("vectara/hallucination_evaluation_model","8e4a2e6e96c708cc76c2344f7e4757df2515292c","laptop HF cache refs/main"),
 "nli-fever-bs":("MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli","6f5cf0a2b59cabb106aca4c287eed12e357e90eb","laptop HF cache refs/main"),
 "nli-fever-lg":("MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli","b3546ea6b0346eb6f8d5d68b13c7dc6d0376b3d7","laptop HF cache refs/main"),
 "vitaminc":    ("tals/albert-xlarge-vitaminc-mnli","3082ba54344bd9ddada2be1c5e9b4131721d2a5d","laptop HF cache refs/main"),
 "minicheck-t5":("lytang/MiniCheck-Flan-T5-Large","96eafd01cee2d16cf81aaa2fb226b14f422a37b3","cached_file() resolved pytorch_model.bin on the lab host"),
 "minicheck-deb":("lytang/MiniCheck-DeBERTa-v3-Large","2f2d01a54fa022a7ffadb76260e1ea8bc88c82bb","cached_file() resolved pytorch_model.bin on the lab host"),
 "minicheck-rob":("lytang/MiniCheck-RoBERTa-Large","74c8919647e61ed0f71bc177d94f10930f090068","cached_file() resolved pytorch_model.bin on the lab host"),
 "nli-mnli-lg": ("microsoft/deberta-large-mnli","7296194b9009373def4f7c5dad292651e4b5cf4e","lab host HF cache refs/main"),
 "bespoke-7b":  ("bespokelabs/Bespoke-MiniCheck-7B","1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8","pinned in e101_stageB_fly.py:91"),
 "lynx-8b":     ("PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct",None,"designed, never downloaded, never scored"),
}
DATASETS = {"tals/vitaminc": "https://huggingface.co/datasets/tals/vitaminc",
            "lytang/LLM-AggreFact": "https://huggingface.co/datasets/lytang/LLM-AggreFact"}
REPOS = {"MiniCheck reference implementation": "https://github.com/Liyan06/MiniCheck"}
PAPERS = {  # arXiv id -> what this programme uses it for
 "2103.08541": "VitaminC: the contrastive fact-verification corpus used as E-101g's external control",
 "2404.10774": "MiniCheck: the four MiniCheck arms and their reference scoring procedure",
 "2407.08488": "Lynx: the causal-judge arm (designed, not run)",
 "2006.03654": "DeBERTa: architecture behind four arms",
 "1909.11942": "ALBERT: architecture behind the vitaminc arm",
 "1803.05355": "FEVER: training corpus named in two arm ids",
 "1704.05426": "MultiNLI: training corpus named in four arm ids",
 "1910.14599": "ANLI: training corpus named in two arm ids",
}

def head(url, tries=2):
    for k in range(tries):
        try:
            r = urllib.request.Request(url, method="GET",
                headers={"User-Agent": "Mozilla/5.0 (prospector source verifier)"})
            with urllib.request.urlopen(r, timeout=25) as resp:
                return resp.status, resp.read(20000)
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception as e:
            if k == tries - 1:
                return None, str(e).encode()
            time.sleep(2)

out = {"checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "models": {}, "datasets": {}, "repos": {}, "papers": {}}

for arm, (mid, sha, prov) in MODELS.items():
    url = f"https://huggingface.co/{mid}" + (f"/tree/{sha}" if sha else "")
    st, _ = head(url)
    out["models"][arm] = {"model_id": mid, "commit": sha, "sha_established_by": prov,
                          "url": url, "http": st}
    print(f"{st}  {arm:14s} {url}")

for k, url in {**DATASETS, **REPOS}.items():
    st, _ = head(url)
    key = "datasets" if k in DATASETS else "repos"
    out[key][k] = {"url": url, "http": st}
    print(f"{st}  {k}  {url}")

for aid, use in PAPERS.items():
    st, body = head(f"http://export.arxiv.org/api/query?id_list={aid}")
    m = re.search(rb"<entry>.*?<title>(.*?)</title>", body, re.S)
    if not m:
        st2, body2 = head(f"http://export.arxiv.org/api/query?id_list={aid}&max_results=1")
        m = re.search(rb"<entry>.*?<title>(.*?)</title>", body2, re.S)
    title = re.sub(r"\s+", " ", m.group(1).decode()).strip() if m else None
    out["papers"][aid] = {"url": f"https://arxiv.org/abs/{aid}", "http": st,
                          "title_from_arxiv_api": title, "used_for": use}
    print(f"{st}  arXiv:{aid}  {title}")

bad = [k for sec in ("models","datasets","repos","papers") for k, v in out[sec].items()
       if v.get("http") != 200]
out["all_resolved"] = not bad
out["unresolved"] = bad
print(f"\nunresolved: {bad or 'none'}")
open("tools/experiments/sources_verified.json","w").write(json.dumps(out, indent=1)+"\n")
