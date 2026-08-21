# The Rust rewrite: the spec

Status: the founder's design, written 2026-08-21. This is the specification `engine-rs/` was
built against. Before this file, `engine-rs/` existed on main with no prose describing it
anywhere — `git grep -in "engine-rs" origin/main -- '*.md'` returned nothing, and the only
written scope was the body of PR #644 plus a comment in `engine-rs/Cargo.toml` referring to a
"parity tier T1" that was defined nowhere.

The founder's framing, verbatim: "I was designing for a Series C company. You're building on
ramen. Let me fix that."

Four Fly apps, zero GPU, zero new infrastructure bills. (The design said two. The founder
settled on 2026-08-21 that the API stays .NET, which puts it back to four — see section 4a.)

---

## 1. The lean stack (4 apps, $0 extra)

| What | Current | Lean rebuild | Why |
|---|---|---|---|
| Fly apps | 5 deployed (engine, store-api, store-web, searxng, hermes) | 4 (engine, store-api, store-web, searxng) | The CI runner dies — use the GitHub Actions free tier. Everything else stays. **The API stays .NET** (founder, 2026-08-21). |
| Engine | Python 73k LOC + supervisord (10 programs) | One Rust binary (Tokio) | Single binary, no GIL, no supervisord. Runs the scheduler, vets, generates packs, and serves its own internal/ops HTTP. It does **not** serve the storefront API. |
| Brain | Python threads in the same process | Python HTTP server on localhost inside the same container | The LLM logic stays Python. Rust calls it over `localhost:8001`. One container, two processes. |
| Database | SQLite | Fly Postgres (free tier) | 3GB, shared CPU, $0. MVCC. Real backups. You can query it. |
| Queue / checkpointing | `threading.Timer` + files | pgmq (Postgres message queue) | A queue built into Postgres. Free. Durable. If the engine dies, another worker picks up the job and resumes from the last checkpoint. |
| Cache | Disk | Fly Upstash Redis (free tier) | Rate limits, search cache, brain slot locks. |
| Dedup / retrieval | `difflib` + Jaccard | CPU embeddings + pgvector | Same Postgres instance. Just an extension. No GPU. |
| Pack gen | `fpdf2` + `mistune` | Typst + `pulldown-cmark` (Rust) | Native PDF, parallel render, no Python GIL blocking. |
| Ops console | Next.js inside the engine image (`supervisord` program `ops-console`, port 8611) | Unchanged | Deferred. Section 9 rejects rewriting it and section 9 wins: it works, there are zero users, and it is not on the critical path. |

Total new bill: **$0**. Fly Postgres free tier plus Upstash Redis free tier. Fly is already
being paid for.

**The API stays .NET.** The founder settled this on 2026-08-21, after the design above was
written. Section 4a is the correction; where the rest of this document implies Rust serves the
storefront API, section 4a overrules it.

---

## 2. Embeddings without a GPU (the two-minute explanation)

You don't need to understand transformers. You need to understand hashing meaning.

**What an embedding actually is.** Take the text `"AI-powered compliance tool for EU banks"`.
Run it through a tiny model (22MB, runs on CPU) that converts it to a list of 384 numbers:
`[-0.02, 0.15, -0.07, ...]`. Two ideas that mean the same thing get lists that are close
together in 384-dimensional space. "Close" means cosine similarity. Postgres with pgvector
computes it in milliseconds.

**The workflow.**

1. When a candidate is generated, compute its 384 numbers (CPU, ~50ms) and store them in
   Postgres.
2. When deduping a new candidate, ask Postgres for the five candidates whose number-lists are
   closest to this one.
3. If similarity is above 0.92 it is a semantic clone, even when the words are completely
   different.

**The tool.** `fastembed-rs`. It downloads the model once (22MB), runs via ONNX Runtime
(CPU-only), and has a Rust API. No PyTorch. No CUDA. No GPU.

**The database.** pgvector is a Postgres extension. Enable it with `CREATE EXTENSION vector;`.
One column per row: `embedding vector(384)`.

---

## 3. Why this is still 100x better

The multiplier does not need Kubernetes. The wins come from removing Python's architectural
limits, not from adding ops complexity.

**Throughput: 10x.** The current vet pool is thread-bound by the GIL. Rust async (Tokio)
handles thousands of concurrent I/O operations — HTTP fetches, DB writes — on a single core. On
the same Fly machine, ten times more candidates vetted per hour.

**Dedup: 50x.** Jaccard catches "AI compliance tool" against "AI compliance tool". It misses
"RegTech SaaS for MiFID II" against "Automated EU banking compliance platform". Embeddings
catch both. Fewer duplicate vets, less wasted retrieval spend.

**Reliability: 100x.** Today a SIGKILL during check 3 loses checks 1 to 3. pgmq plus
checkpointing means every check writes its result to Postgres before the next one starts. Die
and resume. No lost money.

**Pack generation: 50x.** `fpdf2` is pure Python and single-threaded. Rust `typst` renders PDFs
in parallel via Rayon. A 300KB pack drops from 8 seconds to 150ms.

**State: infinity.** SQLite on a Fly volume is a single file with one writer. Lose the file and
you lose everything. Fly Postgres has automated backups, point-in-time recovery, and `psql`
from a laptop against production. The backup anxiety disappears.

---

## 4. The single-container architecture

Inside the one `prospector` Fly app:

```
┌─────────────────────────────────────────────┐
│           prospector (Fly app)              │
│  ┌───────────────────────────────────────┐  │
│  │         Rust Binary (Tokio)           │  │
│  │  ┌─────────┐ ┌──────────┐ ┌────────┐  │  │
│  │  │Internal │ │Scheduler │ │  Pack  │  │  │
│  │  │ /ops    │ │  (pgmq)  │ │  Gen   │  │  │
│  │  │  HTTP   │ │          │ │        │  │  │
│  │  └────┬────┘ └────┬─────┘ └───┬────┘  │  │
│  │       │           │           │       │  │
│  │  ┌────┴───────────┴───────────┴────┐  │  │
│  │  │        Retrieval Layer          │  │  │
│  │  │  (SearXNG + cache + reranker)   │  │  │
│  │  └─────────────────────────────────┘  │  │
│  └──────────────┬────────────────────────┘  │
│                 │ localhost:8001            │
│  ┌──────────────┴────────────────────────┐  │
│  │      Python Brain (subprocess)        │  │
│  │   (Claude/GPT calls, generation,      │  │
│  │    verdict ruling, structured JSON)   │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
      │              │                │
      │         Fly Postgres      Fly Upstash
      │      (dossiers + queue)   (cache + locks)
      │
      │ HTTPS, STORE_API_URL, STORE_INTERNAL_API_KEY
      ▼
┌─────────────────────────────────────────────┐
│   prospector-store-api (.NET) — UNCHANGED   │
│   checkout, entitlements, downloads,        │
│   orders, catalog, auth, disputes           │
└──────────────────┬──────────────────────────┘
                   ▼
        prospector-store-web (Next.js)
```

The Python brain is not a separate Fly app. It is a subprocess — or a sidecar container on the
same machine — exposing `POST /generate` and `POST /verdict`. Rust owns orchestration, state
and I/O. Python owns the LLM prompts.

**Why this works.** The GIL does not matter if the process handles one LLM call at a time. Rust
handles 100 concurrent candidates; each fires one blocking Python call. The parallelism is at
the Rust level, not the Python level.

---

## 4a. The API stays .NET

Founder decision, 2026-08-21. The storefront API is not in scope for the rewrite and never was.
Where section 1 or section 4 implies the Rust binary serves the storefront, this section
overrules them.

**What stays.** `prospector-store-api` is a deployed Fly app. Its source is
`store_platform/src/Store.Api` — 110 C# files, 11,794 lines — plus `store_platform/src/Store.Catalog`
at 13,757 lines. It is deployed by `.github/workflows/deploy-api.yml`. It owns everything a
customer or a card touches:

| Surface | Endpoints |
|---|---|
| Money | `POST /checkout`, `POST /entitlements`, `GET /download/{token}`, `GET /healthz/money-rail` |
| Orders | `GET /api/orders/{token}`, `GET /api/orders/by-session/{sessionId}`, `GET /v1/auth/me/orders` |
| Catalog (public) | `GET /catalog`, `GET /catalog/{id}`, `GET /catalog/stats`, `POST /catalog/waitlist` |
| Catalog (internal) | `POST /internal/catalog`, `PATCH /internal/catalog/{id}/{listing,price,copy,facets,content}` |
| Ops | `GET /internal/ops/{orders,sales,deliveries,disputes}`, `POST /internal/ops/deliveries/{id}/resend` |
| Auth | `POST /login`, `POST /exchange`, `GET /me`, `GET /providers`, provider link and unlink |
| Backup | `GET /internal/backup/database`, `GET /internal/backup/keyring` |

Rewriting that in Rust would mean re-deriving Stripe handling, entitlement issuance, download
token signing and dispute handling — the parts where a bug is money, not latency. It is not on
the critical path to a faster engine.

**The boundary the rewrite inherits.** The engine is already an HTTP client of the .NET API and
nothing about that changes. Today, in Python:

- `prospector/bridge.py:629` reads `STORE_API_URL`, defaulting to `http://localhost:5291`.
- `prospector/bridge.py:558` is `_validate_store_api_url`, an SSRF and credential-leak guard.
  It refuses a non-`http(s)` scheme, a missing host, a host containing `metadata`, and any
  link-local, unspecified, multicast or reserved IP. It fails closed: a bad URL raises and stops
  the publish rather than forwarding the internal key to it.
- Auth is `STORE_INTERNAL_API_KEY`. Unset means `None`, and `_update_catalog` refuses to publish
  rather than falling back to a committed key in a public repo.
- The two call sites are `prospector/bridge.py:1710` and `prospector/bridge.py:2269`, both
  `requests.post(url, json=payload, headers=headers, timeout=10)`.

**What that means for the Rust port.** `prospector/bridge.py` still moves to Rust — it is on the
hot path list in section 9 — but it moves as a **client**, not as a replacement. The port has to
carry three things across, and each is a place where a miss is money:

1. The SSRF guard. Port `_validate_store_api_url` behaviour first, with the same fail-closed
   default, before any code path can send `STORE_INTERNAL_API_KEY` anywhere.
2. The fail-closed missing-key rule. No default key, no publish without one.
3. The six listing fences. Section 9 says Rust's type system makes them unmissable. They fence
   what the engine sends to `PATCH /internal/catalog/{id}/listing`; the .NET side keeps its own
   checks and neither replaces the other.

**Contract stability is now a hard requirement.** The Python engine and the .NET API share
request shapes today — `prospector/price_rationale.py:4` cites
`store_platform/src/Store.Api/Contracts/PricePatchRequest.cs:28` directly, and
`prospector/bridge.py:1625` cites `Store.Api`'s `Program.cs` for update-path behaviour. The
Rust client must serialise to the same JSON the C# contracts deserialise. That is a parity
obligation with a live money rail on the other side of it, and it belongs in whatever the
parity tiers turn out to mean (see section 10).

**Effect on the app count.** The target is four Fly apps, not two: `prospector` (Rust engine plus
the Python brain subprocess), `prospector-store-api` (.NET), `prospector-store-web` (Next.js) and
`prospector-searxng`. The only app the rewrite removes is the CI runner, which the GitHub Actions
free tier replaces.

## 5. The migration: no big bang, no downtime

The engine cannot stop. It gets strangled over eight weeks.

**Weeks 1–2: Postgres shadow.** Spin up Fly Postgres (free). Dual-write: every time Python
writes to SQLite, also write to Postgres. Do not read from Postgres yet. Just prove the data
lands correctly.

**Weeks 3–4: Rust retrieval (sidecar).** Build a Rust binary that does one thing: fetch a page,
extract passages, cache in Redis. Run it on localhost inside the engine container. Have Python
call it over HTTP. Compare results. It should be faster and more reliable.

**Weeks 5–6: embeddings (shadow mode).** Add a pgvector column. When a candidate generates,
compute its embedding via `fastembed-rs` — or even a Python script triggered locally. Run dedup
in shadow: Jaccard decides, the embedding logs disagreement. Measure how many clones Jaccard
missed.

**Week 7: Rust pack generation.** Build one pack in Rust (Typst). A/B against Python `fpdf2`.
Benchmark speed, file size, font correctness.

**Weeks 8–10: the scheduler cutover.** Replace `threading.Timer` with pgmq. One queue for
signals, one for candidates, one for publish. Each vet check writes a checkpoint row before
proceeding. Run one lane — for example `side_hustle` — through pgmq and keep the rest on the old
scheduler.

**Weeks 11–12: full cutover.** Kill the old scheduler. Kill SQLite. The Rust binary is the
engine. The Python brain is only the LLM subprocess.

---

## 6. What the founder needs to learn (two days)

**Day 1, morning.** Install pgvector locally. `CREATE EXTENSION vector;`. Create a table with a
`vector(384)` column. Insert ten rows of text. Run a similarity query. Two hours and it is
understood.

**Day 1, afternoon.** Try `fastembed` (the Python version) on the laptop. `pip install
fastembed`. Embed two candidate descriptions. Print the similarity score. That is it.

**Day 2.** Read the `fastembed-rs` README. It is a 1:1 port. The API is `TextEmbedding::try_new()`
then `embed()`.

You do not need to know what a transformer is. You do not need to know what ONNX is. Treat it as
a library that converts text to numbers.

---

## 7. The honest trade-offs

| Proposed before | Proposed now | Why the change |
|---|---|---|
| Temporal | pgmq (Postgres queue) | Temporal needs a server. pgmq is a table. Same durability, zero infra cost. |
| Kubernetes | Single Fly app | Zero users. One app is enough. Scale later. |
| 6 microservices | 4 Fly apps | `prospector` (Rust + Python brain), `prospector-store-api` (.NET), `prospector-store-web` (Next.js) and `prospector-searxng`. Only the CI runner goes. |
| GPU embeddings | CPU embeddings (`fastembed-rs`) | 22MB model, 50ms per doc on CPU. Good enough. |
| Rust for everything | Rust for engine and API, Python for the brain | The prompts already exist and work. Don't rewrite what works. |

---

## 8. The bottom line

No platform team required. What is required:

1. One Rust binary to replace the Python orchestration layer.
2. One Fly Postgres to replace SQLite and files.
3. One CPU embedding model to replace Jaccard.
4. One queue table to replace `threading.Timer`.

What is explicitly **not** required: rewriting the .NET storefront API, the Next.js ops console,
or the tuned prompt layer. All three work, none is the bottleneck, and each is a place where a
rewrite trades working code for regression risk.

That is 100x on throughput, 50x on dedup accuracy and unbounded improvement on state
durability, for $0 extra per month and a single developer.

The invariants stay sacred. The Rust compiler enforces them better than Python ever could. The
rest is removing the ceilings.

Start here:

```
fly postgres create --name prospector-db --region lhr --vm-size shared-cpu-1x
```

Then dual-write. Everything else follows.

---

## 9. Scope: how much of the engine goes to Rust

The engine is 73,401 LOC across roughly 110 modules. The decision is **option 1, the hot path
only**, and it is not close.

The options that were rejected:

**Option 2, everything except prompts.** Rust takes all of `prospector/` including the
14,382-LOC ops console, rewritten as Axum plus htmx. Roughly twice the work of the hot path.
Rejected: there are zero users. The ops console is a founder tool and it works today. Rewriting
it because a document said so is cosmetic surgery during a heart attack. The console's problem
is not its stack — its problem is that it lives inside the engine image. Move it to a separate
process in the same container if isolation matters, or leave it. It is not on the critical path
to a 100x improvement, and the 2x work buys nothing that moves revenue.

**Option 3, all 73k with no Python left.** Rust calls Anthropic and OpenAI over HTTP directly,
no Python process in the container. Rejected: the prompt layer is not slow because of Python. It
is slow because it calls Claude and GPT over HTTP. Porting 20,000 lines of prompt engineering,
`_extract_json` strategies and provider failover to Rust saves milliseconds on a multi-second
API roundtrip. Worse, the prompts work. They are tuned, with golden sets behind them. A Rust
rewrite means re-tuning every prompt boundary, every JSON schema and every edge case where
`json_repair` saved us — months of regression risk for a rounding error. Throw away working
prompt code only when the prompts are the bottleneck. They are not.

### What option 1 covers (~25k LOC)

These are the files that hurt. Everything else stays.

The "founder" column is the estimate in the original design. The "measured" column is `wc -l`
against this commit, added because a number in a plan is a claim. Where they disagree, the
measured number is the one to plan against — the totals move the same way.

| Module | Founder | Measured | Why it moves |
|---|---:|---:|---|
| `prospector/run.py` | 4,532 | 4,532 | The orchestration loop. The GIL killer. The `threading.Timer` suicide vest. |
| `prospector/scheduler/` | ~3,000 | 5,189 | Tick logic, spend guard, backlog, PAUSE file checks. Becomes pgmq consumers. |
| `prospector/retrieval.py` | ~2,500 | 2,522 | HTTP concurrency, circuit breakers, disk cache. Tokio handles this natively. |
| `prospector/verify.py` | ~2,000 | 1,336 | The orchestration of the six checks, not the verdict ruling. The loop, the kill-fast logic, the confidence scoring. The `verdict_for()` call itself becomes an HTTP POST to Python. |
| `prospector/bridge.py` | ~2,500 | 2,511 | Publish, bundle, listing fences. The engine's side of the money rail. Rust's type system makes the six fences unmissable. It moves as an HTTP **client** of the .NET API, not as a replacement for it — see section 4a. |
| `prospector/pack_*.py` | ~3,500 | 7,786 | HTML, PDF, manifest, CSV, card generation. Rayon parallelism plus Typst. |
| `prospector/dedup.py` | ~400 | 190 | Jaccard dies. pgvector plus `fastembed-rs` lives. |
| `prospector/dossier.py` | ~300 | 1,090 | JSON file writes become Postgres rows. |
| `prospector/inflight.py` | ~200 | 264 | Markers on disk become pgmq status columns. |
| `prospector/jsonl_atomic.py` | ~150 | 419 | Atomic file hacks become Postgres transactions. |
| `prospector/cli_governor.py` | ~400 | 232 | `flock` files become Redis leases. |
| `prospector/store.py` | ~2,000 | 666 | SQLite file ops become SQLx plus Postgres. The design named a `prospector/store/` package; the state layer is one module, `prospector/store.py`. |
| `prospector/adaptive.py` | ~800 | 545 | Controller logic. Reads from Postgres instead of JSONL. |
| `prospector/diagnostics.py` | ~1,000 | 797 | Funnel metrics. Writes to Postgres. |

Founder's total: 23,000 to 25,000 LOC. **Measured total: 28,079 LOC.** The two biggest gaps are
`pack_*.py` (7,786, not ~3,500) and `prospector/scheduler/` (5,189, not ~3,000). Both are on the
hot path either way, so the shape of the decision does not change — the week-7 pack milestone and
the week-8-to-10 scheduler cutover are each about twice the work the plan assumed.

### What stays Python (~20k LOC)

| Module | Founder | Measured | Why it stays |
|---|---:|---:|---|
| `prospector/generate.py` | ~1,500 | 1,106 | Candidate generation. Pure prompt engineering. |
| `prospector/artifacts.py` | ~2,000 | 1,529 | Marketing content, GTM plan, ops plan. All LLM text generation. |
| `prospector/score.py` | ~600 | 75 | Deterministic maths, but it runs after the LLM verdicts. Keep it in Python, or move it to Rust in half an hour — it is weighted arithmetic. |
| `prospector/ops/` | 14,382 | 14,518 | The console. Leave it alone. |
| `prompts/*.md` | ~2,000 | 1,098 | Prompt files. No code change needed. |

Measured Python that stays: **17,228 LOC** of code plus 1,098 lines of prompts.

### The measurement

Two angles agree that the engine is roughly 73k lines and that `run.py` is exactly 4,532:

```
$ find prospector -name '*.py' -exec cat {} + | wc -l
   73593
$ wc -l < prospector/run.py
    4532
```

The design said 73,401. The 192-line difference is commits landed since it was written.

---

## 10. Open: what the parity tiers are

`engine-rs/Cargo.toml:61` is the only place in the repo that uses the phrase, and it assumes a
scheme that is written down nowhere:

> Parity tier T1 requires bit-exact f64 against the Python implementation, so an accidental...

T1 implies a T2 and probably a T3. Nothing defines them. The rewrite needs them, because "does
the Rust match the Python" has at least three different right answers depending on what is being
ported:

- **Scoring and money maths** — `prospector/score.py`, the price patch path, anything the .NET
  API deserialises. Bit-exact f64 or the port is wrong.
- **Retrieval and ranking** — same inputs should give the same ordering, but a float in the
  fifteenth place does not matter.
- **LLM-adjacent output** — nothing is reproducible; the bar is a golden-set score that does not
  regress.

Naming the tiers is a founder decision and is not made in this document. Until it is made, the
week-1-to-2 dual-write and the week-5-to-6 shadow dedup have no defined pass mark.
