# Evidence recall — the research, and the number it puts a scale on

Commissioned 2026-08-20 under `docs/ENGINE_1000X_ACTION_PLAN.md` phase 3. Every figure below
carries a URL. Where a source could not be fetched the row says `unverifiable` rather than
guessing, and those rows are listed together at the end.

## The finding that reorders the whole plan

`tools/engine_baseline.py` measured our abstention rate on 14,006 checks: **73.3% `unverifiable`**
(10,265 of 14,006; supported 3,079, refuted 662). Until today that was a number with no scale.
Nobody could say whether 73.3% is what the open web does to anyone, or whether it is our defect.

It is our defect. The comparable published rate is **6.2% to 9.2%**.

| Corpus | Label | Rate | Source |
|---|---|---|---|
| AVeriTeC train (4,568 real claims, live-web evidence, human annotators) | Not Enough Evidence | **9.2%** | [ar5iv 2305.13117 Table 2](https://ar5iv.labs.arxiv.org/html/2305.13117) |
| AVeriTeC dev | Not Enough Evidence | **7.0%** | same |
| AVeriTeC test | Not Enough Evidence | **6.2%** | same |
| FEVER train (145,449 claims) | NotEnoughInfo | 24.5% — but NEI there is CONSTRUCTED, so it is not a natural base rate | [ar5iv 1803.05355 Table 1](https://ar5iv.labs.arxiv.org/html/1803.05355) |

We are 8 to 12 times the human rate. AVeriTeC's NEI label means "a competent human searcher
looked and could not find evidence", which is exactly what our `unverifiable` claims to mean.

**The caveat, stated so nobody quotes this table wrongly.** AVeriTeC claims were pre-selected by
professional fact-checkers, who choose suspicious claims. That is why their *refuted* rate is
57-62% and ours is 4.7%. Those two numbers are NOT comparable and must never be set against each
other. The NEI rate is the comparable one.

**Second angle, independent of the first.** In the AVeriTeC shared task every system ran against
the SAME fixed knowledge store. The baseline scored Q-only 0.24 and AVeriTeC score 0.11; the
winner scored Q-only 0.45 and 0.63. The corpus was identical, so the entire gap is query quality
([arXiv 2410.23850](https://arxiv.org/abs/2410.23850)). The organisers' own words: *"generating
questions, rather than simply searching for the claim, was noted by many top-scoring systems to be
essential for good retrieval performance."*

Two angles that can fail differently agree: the bottleneck is **how we query**, not what exists
on the web.

## The test that decides it, before we build anything

One cheap model call per failed check, run only on the 73.3%:

> Re-decompose the claim into a DIFFERENT question set and search again. A claim that stays empty
> across two independently generated question sets is evidence of true absence. A claim that flips
> is evidence we searched badly.

If the rate moves toward 6-9%, retrieval is the bottleneck and the shortlist below is worth
building. If it does not move, the diagnosis is wrong and the money goes elsewhere. This is the
whole experiment, and it costs one generation call on failures only.

The mechanism is not invented here. It is AVeriTeC's own **Evidence Sufficiency Check**: a second
annotator sees only the claim plus the question/answer pairs, rules independently, and *if the two
disagree the question generation is repeated with new annotators*. That protocol is what produces
their 6.2-9.2% figure.

## Why abstention must be instrumented and can never be asked

AA-Omniscience scores 6,000 questions across 42 economically relevant topics on an index that
*"jointly penalizes hallucinations and rewards abstention when uncertain"*, bounded -100 to +100,
where 0 means as many right as wrong. **Claude 4.1 Opus is top at 4.8, and is one of only three
models above zero out of 31 evaluated.** Their conclusion, verbatim: *"These results reveal
persistent factuality and calibration weaknesses across frontier models."*
([artificialanalysis.ai/evaluations/omniscience](https://artificialanalysis.ai/evaluations/omniscience))

The best-calibrated model on the market scores 4.8 out of 100 at knowing what it does not know.
Asking a brain whether evidence exists is not a measurement.

## Ranked shortlist, gain per pound

Costs are USD as published. One-off means engineering time; operational means it bills forever,
which is the distinction the founder's cost ruling turns on.

| # | Option | Measured gain | Cost | Class |
|---|---|---|---|---|
| 1 | **Claim to 2-3 question decomposition, search each, union the results** | AVeriTeC score 0.11 to 0.63, Q-score 0.24 to 0.45, on a FIXED corpus. Human annotators use 2.60 questions per claim. | 1 cheap call per claim, search calls x2.6 | one-off build, small operational |
| 2 | **URL-keyed durable passage store** | Removes the measured 21.84% refetch by construction. 1M cleaned pages = 2.9 GB = $0.044/month on R2, and 3.4M pages fit inside R2's free 10 GB. | ~$0 operational | one-off |
| 3 | **Re-search on `unverifiable` with a different question set; abstain only on stable-empty** | Turns a terminal state into a retry. Base rate says 6.2-9.2% should truly be empty against our 73.3%. | 1 extra call on failures only | one-off + small operational |
| 4 | **Fan out across free tiers and multi-backend metasearch, fuse with RRF** | Four independent indexes, roughly 6,400 free searches/month. `ddgs` exposes 10 backends where we query 1. | $0 | one-off |
| 5 | **Route business claims to free registries first** | Companies House, SEC EDGAR, Wikidata answer incumbency / solvency / existence with structured facts where web search returns marketing pages. Every hit is a search credit never spent. | $0 forever | one-off |
| 6 | **Rule on the SERP snippet before fetching the page** | Brave ships "extra alternate snippets" free with every search we already buy, at 50 QPS. | $0 marginal | one-off |
| 7 | **FlashRank + ms-marco-MiniLM-L6-v2, local CPU rerank** | nDCG@10 74.30 on TREC DL19 against BM25's 50.6. 4-34 MB, ~1800 docs/sec, no GPU, no torch, no API. | $0 operational | one-off |
| 8 | **HyDE / CoT query expansion, gated by an A/B on our own corpus** | Recall@1k 75.0 to 88.0 on DL19. Recall@100: SciFact 92.5 to 96.4, FiQA 54.0 to 62.1, ArguAna 93.2 to 97.9. | 1 generation per query | operational, gate it |

**Ranked OUT, with the reason:**

- **doc2query / docTTTTTquery.** It expands documents in an index you own, at indexing time. We
  query third-party search APIs and own no index. Architecturally inapplicable, and it is the
  option most often mis-recommended for this shape of system.
- **RM3 and classical PRF.** Free, no model call, and marginal: MS MARCO Recall@1K 87.82 to 88.68
  (+0.86) while MRR@10 falls 18.77 to 17.75. Buying recall with precision at that ratio is not
  worth the wiring unless a local BM25 index already exists.
- **GenRead as a verdict source.** It reaches 71.6 EM on TriviaQA with zero retrieval, which
  proves the parametric knowledge is there, and that is exactly why it violates
  verdict-from-retrieval-only. The safe half is option 8 below the table: let the model name
  WHICH registry or domain would hold the answer, then retrieve from it. The model chooses where
  to look, never what is true.
- **Full Common Crawl processing.** One monthly crawl is 2.14 billion pages: WARC 84.69 TiB, WET
  5.89 TiB compressed. Filtering that is a project, not a task, and no published dollar figure
  was found. The 0.22 TiB URL index is the part worth a look, strictly as a one-off.
- **Any hosted reranker in the operational path.** Voyage's 200M free rerank tokens is a one-off
  A/B budget to establish a quality ceiling, never a running bill.

## Reranking cannot raise recall, and that ordering matters

A document search never returned cannot be reranked into view. Reranking raises precision@k and
nDCG, which matters only because a better-ordered pool puts the right passage inside the verdict
model's context budget. If the 73.3% is a retrieval failure, reranking is a second-order fix and
belongs after items 1 through 4, not before.

### CPU cross-encoders, free, no GPU

| Model | nDCG@10 TREC DL19 | MRR@10 MS MARCO dev | Docs/sec | Size |
|---|---|---|---|---|
| BM25 baseline, for reference | 50.6 | — | — | — |
| ms-marco-TinyBERT-L2-v2 | 69.84 | 32.56 | 9000 | ~4 MB |
| ms-marco-MiniLM-L4-v2 | 73.04 | 37.70 | 2500 | — |
| **ms-marco-MiniLM-L6-v2** | **74.30** | **39.01** | 1800 | — |
| ms-marco-MiniLM-L12-v2 | 74.31 | 39.02 | 960 | ~34 MB |

Docs/sec are the model card's own figures on unspecified hardware: relative, not absolute.
[HF cross-encoder/ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
[FlashRank](https://github.com/PrithivirajDamodaran/FlashRank).

## Search and content APIs, priced 2026-08-20

| Provider | Price / 1000 queries | Free tier | Returns content? |
|---|---|---|---|
| [Brave Search](https://brave.com/search/api/) | $5 | $5/mo credits, ~1,000 queries, card required | links + text + extra alternate snippets, 50 QPS |
| [Tavily](https://docs.tavily.com/documentation/api-credits) | $8 PAYG; basic 1 credit, advanced 2 | 1,000 credits/mo, no card | yes |
| [Exa](https://exa.ai/pricing) | $7 search | $20 signup (~2,800 searches) + $10/mo | contents $1/1k pages |
| [Google Programmable Search](https://developers.google.com/custom-search/v1/overview) | $5 | 100/day free (~3,000/mo) | snippets only |
| [SerpAPI](https://serpapi.com/pricing) | $25 starter to $3.75 at 1M | 250/mo | real Google SERP snippets |
| [Perplexity Search](https://docs.perplexity.ai/getting-started/pricing) | $5, no token cost | not stated | search results |
| [Firecrawl](https://www.firecrawl.dev/pricing) | search 2 credits / 10 results; ~$1.13 per 1k credits at Scale | 1,000 credits/mo | full page markdown |
| [Jina Reader](https://jina.ai/reader) | token-based, per-1M price `unverifiable` (pricing page 404) | 10M free tokens | full page markdown |
| [`ddgs`](https://pypi.org/project/ddgs/) | $0 | unofficial | links + snippets |
| [SearXNG](https://docs.searxng.org/) | $0 + compute | self-hosted | links + snippets |

**The DuckDuckGo finding, which is a free config win.** There is no official DuckDuckGo web-results
API; `api.duckduckgo.com` is an Instant Answer endpoint. The library our chain calls has been
renamed and re-scoped: `ddgs` is now a metasearch aggregator whose `text()` backends are
`bing, brave, duckduckgo, google, grokipedia, mojeek, startpage, yandex, yahoo, wikipedia`. If we
call it as a DuckDuckGo-only provider we leave nine free backends unqueried.

**Free-tier arithmetic, derived:** Tavily 1,000 + Brave ~1,000 + Exa ~1,400 + Google CSE ~3,000
plus Firecrawl's 1,000 page scrapes is roughly **6,400 free searches a month at zero operational
cost, across four independent indexes**. The fan-out across different indexes is the point, not
the volume: different indexes fail differently.

## Free structured sources, confirmed

| Source | Free? | Limit | What it settles |
|---|---|---|---|
| [UK Companies House](https://developer-specs.company-information.service.gov.uk/guides/rateLimiting) | yes | 600 requests / 5 min, 429 on exceed | existence, incorporation, officers, filings, accounts — kills incumbency claims outright |
| [SEC EDGAR](https://www.sec.gov/os/webmaster-faq) | yes, no key | 10 req/sec; must send `User-Agent: Company AdminContact@domain` and `Accept-Encoding: gzip, deflate` | revenue, segment size, named risks; XBRL `frames` gives one metric across all filers |
| [Wikidata SPARQL](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual) | yes, no key | 60s query deadline, 60s processing per 60s, 5 parallel per IP | entity existence, industry, ownership, country, founding date |
| [Wayback CDX](https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server) | yes | supports `collapse`, `filter`, `limit`, pagination | historical pricing pages — the only free structured route to what buyers paid in 2023 |

These three registries answer exactly the claim classes where general web search returns marketing
pages: incumbency, payer solvency, market existence. Routing a claim to the register BEFORE
spending a search credit is free forever.

## Caching arithmetic

Derived from Common Crawl's published July 2026 crawl, CC-MAIN-2026-30
([blog](https://commoncrawl.org/blog/july-2026-crawl-archive-now-available),
[index](https://data.commoncrawl.org/crawl-data/CC-MAIN-2026-30/index.html)): 2.14 billion pages,
WET extracted text 5.89 TiB compressed. That is **~2.9 KB of compressed text per page**, so one
million cached pages is **2.9 GB**.

[Cloudflare R2](https://www.cloudflare.com/developer-platform/products/r2/) is $0.015/GB-month
with zero egress and a 10 GB-month free tier. One million pages costs **$0.044/month**, and the
first ~3.4 million pages are free. Against a measured 21.84% refetch rate this is the cheapest
win available: it removes the fetch, removes its latency, and makes evidence reproducible when
the source 404s.

On staleness, no published measurement of how fast web facts decay was found — `unverifiable`.
What is documented is the practice: AVeriTeC's authors cache every evidence page in the Internet
Archive *"as a result of pages disappearing from the web"*. Archive-on-fetch is the field norm.

A second fact supports building a local corpus rather than always searching live: **13 of 16
AVeriTeC system papers used the provided fixed knowledge store; only 3 used live Google Search**,
because of API cost. The organisers report the store *"did not trivialise the task"* thanks to
deliberate distractor documents. A fetched-once local corpus is a legitimate architecture, not a
degradation.

## The measuring stick we should adopt

**AVeriTeC dev — 500 claims with gold questions — costs $0 to download and reports evidence
quality separately from verdict accuracy.** That separation is exactly what our A4 lacks. It gives
a Q-score we can move, against published baselines (0.24) and published winners (0.45-0.48).

One honest caveat from the organisers: their human evaluation found *"low correlation between the
Hungarian Meteor and the assessed dimensions"*, so treat Q/Q+A as a rough instrument.

## Not closed

The session's web-search budget ran out part way through. These are `unverifiable` this session
rather than negative findings, and none of them change the top five, because the top five are all
zero-or-near-zero cost and rest on sources that were fetched:

Bing API retirement date and its successor's price; Cohere Rerank per-search-unit price; Jina
per-1M-token prices; AWS S3 and Backblaze per-GB rates; doc2query--; RaFe; current-best retrieval
scores for FEVER, HoVer, FEVEROUS and QuanTemp; BEIR BM25-vs-SOTA Recall@100; the RRF paper's own
numbers; and most structured sources beyond the four confirmed above (patents, statistical
offices, job boards, app stores, OpenAlex, GLEIF, OpenCorporates). Crossref returned HTTP 429 on a
single unauthenticated request, which is itself worth knowing.
