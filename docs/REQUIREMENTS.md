# Requirements — the one register

Every requirement the founder has stated, in one place, with one number sequence, each one
carrying the founder's own words and a link to the thing that proves its state.

**Why this file exists.** Founder directive 2026-08-21: *"we need to be better at tracccking"*,
*"and linking"*, *"this ned deep deep linking"*. Requirements had accumulated in four separate
documents with four separate numbering schemes, so "is R4 done?" had four possible answers
depending on which file you opened. There is now one sequence. Where a programme document owns
the detail, this register links to it rather than repeating it — a requirement restated in two
places drifts, and then neither copy can be trusted.

**The rule for every row: a requirement is DONE when a command says so, not when a reply says
so.** The Proof column is a `file:line`, a merged PR, or an explicit "unproven" naming the check
that would settle it. A row with no proof is not done, however finished it feels.

**Where the detail lives.** This register is the index. The programme documents are the record:

| Programme | Owns |
| --- | --- |
| [`PROVIDER_PLUGGABILITY_PROGRAM.md`](PROVIDER_PLUGGABILITY_PROGRAM.md) | R1–R11 — providers, the console, the heartbeat, the rate brake |
| [`ENGINE_100X_PROGRAM.md`](ENGINE_100X_PROGRAM.md) | the eight axes A1–A8 and every experiment E-nnn |
| [`ML_OPPORTUNITY_AUDIT_2026-08-15.md`](ML_OPPORTUNITY_AUDIT_2026-08-15.md) | what ML was tried on the candidate funnel and what it measured |
| [`PLATFORM_MANIFESTO.md`](PLATFORM_MANIFESTO.md) | the platform laws L1–L13 |
| [`PACK_NARRATIVE_PROGRAM.md`](PACK_NARRATIVE_PROGRAM.md) | what the buyer reads, and why the renderers stay model-free |
| [`WORK_REGISTER.md`](WORK_REGISTER.md) | strands in flight across the whole estate, not just the engine |

---

## 1. The register

| # | Requirement | Founder's words | State | Proof |
| --- | --- | --- | --- | --- |
| R1 | Any provider can be added to **any part of the engine** — moat, non-critical, artifacts | "add any provider to any part of the engine" | **PARTLY** | every part accepts a declared name; the trust fence still bars a declared provider from `moat_primary` pending Q2 |
| R2 | Any provider can be added to the **harness agent** too | "and also to the hernes agnt" | **NOT STARTED** | — |
| R3 | Ship **preloaded** with providers, not an empty mechanism | "preloaded with providers" | **DONE** | 15 providers in `config.yaml providers:`, each inert until its key is set |
| R4 | Adding one more is **seamless** — no code edit | "seanless ability ti add nore" | **DONE** (engine + config page) | a declaration is one config block |
| R5 | **Groq** as a fallback | "lets add Groq fallback" | **DONE** | `config.yaml:67 operator: [minimax, claude_cli, groq, mistral]` |
| R6 | Research **all** providers possible | "reserach all providers possible" | **DONE** | 18 endpoints probed live 2026-08-21, 2 rejected on 404 |
| R7 | Requirements written down, not held in session | "nake not of all the requrenents" | **DONE** | this file |
| R8 | A provider enabled from ops can be **tested from ops**, confirming the model answers | "when enabeld fron ops, should be able to test fron ops console and cconfirn nodel is active" | **DONE** | `act providers.test`, preview then apply |
| R9 | A **heartbeat** on a cadence, not only when a run calls | "need heatbeat" | **DONE** | scheduler tick + `read heartbeat` |
| R10 | R8 and R9 cover **every model the platform can build** | "for all nodels in platforn" | **DONE** | 21 tiers from `buildable_tiers` |
| R11 | When the **primary brain is down**, cut the rate across the platform — 10 not 50 — switch and numbers editable from ops | "when ninina is down we need to reduce the rate of processing across platfron", "else the free ones will ehaust fast", "so just 10", "rather than 50", "but fully confugurble fron ops" | **PARTLY** | unconditional floor `batch_size: 10` in **PR #546**; the *conditional* brake is designed in [`PROVIDER_PLUGGABILITY_PROGRAM.md`](PROVIDER_PLUGGABILITY_PROGRAM.md) §7 and NOT built |
| R12 | **"Run your idea through the engine" — a registered user types their own idea on the storefront and watches the same six checks rule it, with sources.** Not internal dogfooding: the founder asked for UX and front-end work, which a batch job does not need | "and also the run you idea through engine", "needs adding to requrenents", "new featire in the way", "killer featuure", "needs uxx and fe input", "talke to peeers to flesh out dtails", "only for registered uers i nust say" | **NOT STARTED** | spec written 2026-08-21: [`SITE_SPEC_PROGRAM.md` §12](SITE_SPEC_PROGRAM.md#12-run-your-idea-through-the-engine--the-vetting-desk-founder-2026-08-21). Blocked on a cost defect, not on A1: the MiniMax adapter emits no `cost_usd`, so `spend.daily_cap_usd` caps only the `claude_cli` fallback — measured, 39 of 528 ledger rows priced, all of them `claude` — and a public endpoint on that cap has no cap |
| R13 | The engine is a **white box**: fully transparent, every artifact **deep-linked** to the thing that proves it, and that rule written into the engine's own guidelines | "it ust be a while box", "nust", "fully transparent", "deeplined", "linked", "add that to guidlines for engine" | **PARTLY** | drafted as platform law L13; not yet landed in [`PLATFORM_MANIFESTO.md`](PLATFORM_MANIFESTO.md) |
| R14 | **Strict engineering standards, researched and documented**, and the engine work gets **strong adversarial review** | "your engine work needs string adveserial review, the engine is our golden goose and we need stricct enginerring standards researched and docuected" | **PARTLY** | 24 findings from two adversarial reviews, saved; standards S1–S15 drafted, not landed |
| R15 | **Extreme tooling and diagnostics, automated**, including **real-time diagnostics** | "etrene tooling and diangnitis autonated", "ultra extrene", "observable", "real tine diagnossic" | **NOT STARTED** | `scripts/engine_doctor.py` specified, not written |
| R16 | **Drastically reduce bugs, aim to eliminate.** Research it and form a plan | "we need to drastically reduce bugs , even eliniate forn and research plan alo" | **NOT STARTED** | plan section outstanding in the standards programme |
| R17 | **Experiments are held to the same standards** as engine code | "how about the experinest also" | **NOT STARTED** | — |
| R18 | **Track all founder wishes** | "track all founders wishes" | **DONE** | this register + GitHub issues labelled `founder-task` (`scripts/founder_tasks.py`) |
| R19 | An **extreme ML review** covering brand, packaging, language and the **end-to-end** engine workflow — not just the candidate funnel | "while we are at it see how nachine learning acan inprove what we have also exxtrene , and brad the packaageing, he language stuff end to end engine workflow", "revisit and review for anything we have not considered the machine learning stuff", "fresjh eyes etrene creativity with strion g enginerrin nous" | **IN PROGRESS** | three reviews running 2026-08-21; funnel half already answered by [`ML_OPPORTUNITY_AUDIT_2026-08-15.md`](ML_OPPORTUNITY_AUDIT_2026-08-15.md) |
| R20 | The engineering itself is **clean, elegant, robust, scalable, maintainable, performant, observable, easy to grow and modify**, with **strong craftsmanship** | "needs strong clean elegant roust enginerring, secalable, naintainbble, easy to grow and nodify", "strong craftsnanship", "scalable", "perfornaant" | **NOT STARTED** | each adjective needs a measurable test or it is decoration; that mapping is R14's job |
| R21 | **No concurrency on Claude Code** — it is too expensive | "i dont want consurreny onclaude code", "for the last fuckinng tine", "its too expencice" | **unproven** | needs the check that shows concurrency is 1 wherever `claude_cli` is called |
| R22 | Everything **configurable from the ops dashboard** | "lastly ensure configurability via ops dashboad" | **PARTLY** | providers and models yes; the rate brake's numbers not yet (R11) |

---

## 2. What blocks the most rows right now

**A1, availability, is measured at 0%** — the percentage of hours the engine can mint a trusted
verdict. The Fly box has no Claude login and MiniMax is out of credit. R12 cannot start, E-102
cannot run, and every quality experiment is stalled behind it. See
[`ENGINE_100X_PROGRAM.md`](ENGINE_100X_PROGRAM.md) §1.

**A4, discrimination, is saturated at 1.00 on nine items** (`fixtures/golden_set.json`). A
benchmark that cannot register a regression cannot grade an improvement either, so every quality
claim downstream of it is unfalsifiable. E-001 — build a golden set with resolution — gates the
rest and needs no money.

---

## 3. Decisions that are the founder's alone

These are not blocked on work. They are blocked on a ruling, and they are listed here so they
stop being rediscovered.

| Q | Question | Why it is the founder's |
| --- | --- | --- |
| Q1 | Buying MiniMax credit, Cerebras credit, or Groq's paid tier | money leaving the account |
| Q2 | May a declared provider outside the current roster be trusted to **finalise** a PASS? | it decides what may reach a buyer |
| Q3 | Do Groq's free-tier terms allow posting our candidate text and retrieved passages? | free-tier traffic may be retained or trained on, and the corpus is the asset |
| Q4 | Is per-check grounding verification an acceptable **operational** cost, or one-off only? | the standing ruling is that operational costs demand a more creative answer |

---

## 4. How to add a row

Append with the next number. Put the founder's words in verbatim — a wish paraphrased is a wish
reinterpreted. Set State to `NOT STARTED` and Proof to `—`. Never renumber: a stable number is
what makes a link to it worth anything.
