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
| R12 | **"Run your idea through the engine" — a registered user types their own idea on the storefront and watches the same six checks rule it, with sources.** Not internal dogfooding: the founder asked for UX and front-end work, which a batch job does not need | "and also the run you idea through engine", "needs adding to requrenents", "new featire in the way", "killer featuure", "needs uxx and fe input", "talke to peeers to flesh out dtails", "only for registered uers i nust say" | **NOT STARTED** | spec written 2026-08-21: [`SITE_SPEC_PROGRAM.md` §12](SITE_SPEC_PROGRAM.md#12-run-your-idea-through-the-engine--the-vetting-desk-founder-2026-08-21). Not blocked on A1, and not blocked on cost: the cost claim that read as a blocker was withdrawn the same day (§12.6) — MiniMax is priced and already inside `spend.daily_cap_usd`. Open: per-vet cost is unmeasured, because the local store carries 0 metered rows |
| R13 | The engine is a **white box**: fully transparent, every artifact **deep-linked** to the thing that proves it, and that rule written into the engine's own guidelines | "it ust be a while box", "nust", "fully transparent", "deeplined", "linked", "add that to guidlines for engine" | **PARTLY** | drafted as platform law L13; not yet landed in [`PLATFORM_MANIFESTO.md`](PLATFORM_MANIFESTO.md) |
| R14 | **Strict engineering standards, researched and documented**, and the engine work gets **strong adversarial review** | "your engine work needs string adveserial review, the engine is our golden goose and we need stricct enginerring standards researched and docuected" | **PARTLY** | 24 findings from two adversarial reviews, saved; standards S1–S15 drafted, not landed |
| R15 | **Extreme tooling and diagnostics, automated**, including **real-time diagnostics** | "etrene tooling and diangnitis autonated", "ultra extrene", "observable", "real tine diagnossic" | **NOT STARTED** | `scripts/engine_doctor.py` specified, not written <!-- doc-lint-ok: naming a file that deliberately does not exist yet is the status, not a stale path --> |
| R16 | **Drastically reduce bugs, aim to eliminate.** Research it and form a plan | "we need to drastically reduce bugs , even eliniate forn and research plan alo" | **NOT STARTED** | plan section outstanding in the standards programme |
| R17 | **Experiments are held to the same standards** as engine code | "how about the experinest also" | **NOT STARTED** | — |
| R18 | **Track all founder wishes** | "track all founders wishes" | **DONE** | this register + GitHub issues labelled `founder-task` (`scripts/founder_tasks.py`) |
| R19 | An **extreme ML review** covering brand, packaging, language and the **end-to-end** engine workflow — not just the candidate funnel | "while we are at it see how nachine learning acan inprove what we have also exxtrene , and brad the packaageing, he language stuff end to end engine workflow", "revisit and review for anything we have not considered the machine learning stuff", "fresjh eyes etrene creativity with strion g enginerrin nous" | **IN PROGRESS** | three reviews running 2026-08-21; funnel half already answered by [`ML_OPPORTUNITY_AUDIT_2026-08-15.md`](ML_OPPORTUNITY_AUDIT_2026-08-15.md) |
| R20 | The engineering itself is **clean, elegant, robust, scalable, maintainable, performant, observable, easy to grow and modify**, with **strong craftsmanship** | "needs strong clean elegant roust enginerring, secalable, naintainbble, easy to grow and nodify", "strong craftsnanship", "scalable", "perfornaant" | **NOT STARTED** | each adjective needs a measurable test or it is decoration; that mapping is R14's job |
| R21 | **No concurrency on Claude Code** — it is too expensive | "i dont want consurreny onclaude code", "for the last fuckinng tine", "its too expencice" | **unproven** | needs the check that shows concurrency is 1 wherever `claude_cli` is called |
| R22 | Everything **configurable from the ops dashboard** | "lastly ensure configurability via ops dashboad" | **PARTLY** | providers and models yes; the rate brake's numbers not yet (R11) |
| R23 | **Page the founder on Telegram when an agent is stuck** — a task or decision it cannot resolve, a frozen console, a Claude API timeout — and give him a way to **recover** from the page | "sending alert to founder telegran when stck on task/decisino that cant resolve or when console freeses or claude api tines out , need sone process to page founder and be able to recover" | **PARTLY** | the sender exists and works (`~/.hermes/scripts/estate_alert.py`, ledger `~/.hermes/state/telegram_sent.jsonl`); what does NOT exist is a stuck-detector. Research written up: `~/.claude/research/PAGING-AND-REMOTE-CONTROL.md` §2 — absence-based detection, `increase(progress[30m]) == 0`, grace ≥ 2× job period |
| R24 | The founder can **connect to the MacBook from Telegram, remotely**, and the setup must be the most seamless and user-friendly design available | "nsyber founder needs better tooling to be able to connec to nacbook fron telegran renotly", "need thenost seanless and user fiendly setup an design" | **NOT STARTED** | designed in the research §4 and §6. Two measured constraints that decide the design: **Tailscale SSH does not run on a normal Mac install** (tailscale/tailscale#4518, #18957), and Telegram inline buttons cap `callback_data` at 64 bytes, so the control plane is a menu of pre-registered actions, never free-typed shell |
| R25 | **Exhaustively map what can go wrong while the founder is away** from autonomous workers, and how not to lose sight of what is happening | "eed to thik ehaustivelt about challenges founder ca face leaaving autononous workker s while renove and how not to lose connection to thwhts goig on" | **NOT STARTED** | the sharpest one found so far, and it is not in any vendor's list: **a sleeping MacBook is byte-identical to a dead agent** — both stop emitting, and `StartInterval` misses firings during sleep |
| R26 | **Hermes is fully embedded into the team and the project**, not a side project | "we have herness agebt also so needs tying tinto the borader project work also . this is an oversight and a nissing piece of the whole pule , hernes aget needs to be fully enbedded into the tean and project" | **NOT STARTED** | — |
| R27 | **Hermes gets a cleanup and an audit** of its current state, plus improvement, so the two join into one coherent system | "the hernes prohec needs cleanup and audiit current state and inprovenent also so jon the tiw tother into a super coherent systen" | **NOT STARTED** | — |
| R28 | **Deep research Hermes online** and make it a masterpiece — it is leverage that must not be missed, and it gets the biggest brains | "look at the hernes project, deep researcj hernes online and see how o nake this a trie naster piece beause we can leverage it to really super chregae things , not an opportunity to be niseed , needs the biggest brains on this", "and the deepest researcjers" | **IN PROGRESS** | research agent run 2026-08-21; write-up owed at `~/.claude/research/HERMES.md` |
| R29 | **Knowledge is shared between Hermes and the local agents** — a lot of it can be | "a lot of kow legecan be shared bewennthen", "heres and locala agnets" | **NOT STARTED** | — |
| R30 | **Skills and runbooks are shared between them**, continuously and automatically | "and runbooks also", "skills and runboks sharing between then", "super inprotant", "cotiuosly", "autoated" | **NOT STARTED** | — |
| R31 | **Hermes has permanent memory** — dig deep into how it works | "herhens has pernanent nennory also", "dig ddp into how this work" | **NOT STARTED** | — |
| R32 | **Portability outside Claude Code is crucial, and portability also means model-agnostic** | "rnenebr portblity outsidee of cloaud cod ei scrucial", "portability also nneans nodel agnostic" | **PARTLY** | 3 of 8 governance pieces ported (prompt ledger, decision class, goal holder); target 8 of 8 |
| R33 | **Baseline everything before the port and compare after**, to find the gaps | "need to c=baseline everyhtig and conpare whgen proted", "ti find gaps" | **NOT STARTED** | this is the falsification test for R32 and it must be written BEFORE the port finishes, or the comparison has no before |
| R34 | An **ultra-efficient, seamless divide-and-conquer / parallel agent protocol**: take a raw prompt spec, distribute it, coordinate, manage collisions, review and ship | "critial an ultra efficient seanless divive and conqure/ parallel agent protocol , including taking raw pronp spec, distibute andc coordinate, collision nanagennt, etc reviw-ship anything i niss, we have atteped this bitneeds perfectin" | **NOT STARTED** | 40 measured failure modes collected at `~/.claude/research/RAW-multi-agent-failure-modes.md`; design not started. The finding that most constrains the design: **debate between agents that share inputs is a martingale** — clones of one model add cost and no accuracy |
| R35 | **A failed PR alerts and gets a reaction**, but a condition that **clears itself must never page** | "also failed prs should alert and get a reaction/respone", "that dot self heal" | **PARTLY** | PR-failure messages are reaching the board; the self-healing exclusion is not implemented. Google SRE's rule is the standard to hold it to: *"If a page merely merits a robotic response, it shouldn't be a page"* |
| R36 | **`~/.claude` is in GitHub** | "also recall ~/.claude need to be in github" | **NOT STARTED** | measured 2026-08-21: `~/.claude` IS a git repo with commits and has **no remote**. Publishing it is outward-facing and needs a secret audit first — it is a founder ruling (Q5) |
| R37 | **Research means the internet, starting with reputable sources** — wide, deep, exhaustive, leaving no stone unturned, with **every source and every search documented** so decisions can be tracked | "research neans inetrnet stat with reputable sources, etc , go wide and deep, exhautive dont leav any stone untured, docunet all sources and searches etc so tracking decision", "all reseach est edocunented" | **PARTLY** | three write-ups on disk under `~/.claude/research/`, each carrying its own search log and a `[PRIMARY]`/`[SEARCH]` tag per claim. No machine enforces the standard yet |
| R38 | **A decision log, and a way to track decisions across sessions and agents** | "deccision log also", "and how we track desicions across sessions and agents" | **DONE** | `~/.claude/DECISIONS.jsonl`, 82 entries, injected at every session start; `decision-log.py --check "<question>"` before deciding |
| R39 | **Open-source solutions are part of the research aims** | "open source solutions also part of reseach ais" | **PARTLY** | done for paging (healthchecks.io BSD-3, Uptime Kuma MIT, Gatus Apache-2.0, ntfy Apache-2.0, ccgram MIT; `claude-code-telegram` rejected — **no licence**). Not done for the other programmes |
| R40 | **TDD, edge-case mapping and 2nd/3rd-order effect mapping are first-class principles and law** | "tdd and edge case and 2nd /d order effect napping as first class principles and laaw" | **PARTLY** | LAW 4 covers effect mapping and edge cases; TDD is not law anywhere. Both are words, not machines |
| R41 | **Guidance that improves problem solving, decision making and above all judgement** — researched, in chain-of-reasoning and critical thinking | "reseach chainn of reaoning and critical thinkig, is ther anything er cn add to iorive or guide probklen solving decision naking and nnost iportsnly judgenenr" | **IN PROGRESS** | 1,830 lines at `~/.claude/research/RAW-reasoning-and-judgement.md`, every claim tagged by provenance. Ten ranked recommendations, five of them not covered by any existing law. **The single most important finding is a negative one:** an LLM grading another LLM's reasoning tracks fluency at rank correlation +0.75 while the causal-importance signal sits at −0.004 — at chance (arXiv:2608.19760). Any judgement guard that asks a model to grade reasoning quality is graded on how good it sounds |
| R42 | **A board** — the founder should not have to ask what is done | "we dothave a borard", "should notave to be asking these questions", "need to know what is done, what is outstanding before going tinto liower level detail" | **IN PROGRESS** | `~/.claude/scripts/founder_board.py`, generated from commands, never hand-written; every row carries the command that produced it and a failed probe shows `UNKNOWN — why`, never a zero |
| R43 | **A researched project-management plan, with a backlog, mapped out** | "what isthe wholeproject naannennt pla]have youy reseached it", "do w have apropos and plan", "is itnapped out", "backlog etc?" | **NOT STARTED** | — |
| R44 | **How work is split and coordinated** across sessions and agents, written down | "how is work split and coordinnated" | **PARTLY** | the mechanisms exist and are undocumented: `~/.claude/ESTATE_BOARD.jsonl`, `peer-loop-fence.py`, `agent-fleet-fence.py` (cap 3 + main loop), one-session-one-worktree, GitHub issues labelled `founder-task` |
| R45 | **Frictionless, with barely any human in the loop** | "frcction", "recall nonn functional", "frictioless and barelt any hunan inloop" | **NOT STARTED** | a non-functional requirement, so it needs a number before it can be graded: founder interruptions per day, and how many of them were questions a board would have answered |
| R46 | **Updates are top-notch** — high level first, what is done and what is outstanding, before any lower-level detail, with the detail snapshotted | "so updates neeed to be top notch", "whars the high lebe l update", "snapshot the deetail" | **NOT STARTED** | R42's board is the mechanism; the reply format is the other half |
| R47 | **Close things properly.** Bugs and issues do not get left open and chaotic | "we dont close anything preoperly, bugs ,issues chaos everythre", "we need to close loops asap" | **NOT STARTED** | — |
| R48 | **Verify what we ship** | "we shi and dont verify" | **PARTLY** | LAW 2 and LAW 15 are the rule; `.state-probe` and `scripts/live_checkout.py` are the mechanism for the engine. Nothing verifies a governance change |
| R49 | **Autoresearch as a game-changer for the platform** — brainstorm it separately | "separatetly , brainstorn how autoreserch could be a ganechanger for our platforn" | **NOT STARTED** | — |
| R50 | **The cheapest capable agent for each task** | "cheapest capable agent" | **PARTLY** | the rule is in the global rules file (haiku for all recon); no machine checks it and no measurement says what it saved |
| R51 | **A solid plan for how the whole thing gets delivered** | "i need a solit plan of how this whole thing will be delivedered" | **NOT STARTED** | R43 is the mechanism; this row is the deliverable he asked for and has not had |
| R52 | **The database decisions** — storefront onto Postgres | "are yoy aware of the db decisions? storefrint to postgress etc" | **NOT STARTED** | asked and never answered. Unknown to this register: which store, which migration, who decided |
| R53 | **DNS, everything** | "dns everthng" | **NOT STARTED** | asked and never answered |
| R54 | **Automated mutation testing, on its own pipeline, once a day** | "we eed autonated nutatuon tests', it does ot have o be part of the nain build pipeline but wwe need across pipleline running once a day, add to board" | **PARTLY** | mutmut 3.7.0 is the only mutation framework that declares this venv's Python, and it is installed in the sidecar venv rather than the engine's. A daily runner, its scheduled workflow and a test that fails if a commit or a pull request can trigger it are all written, and all parked: a new workflow must be registered in the pipeline failure ledger and classified in the deploy gate before it may exist on disk, and doing that is a branch of its own. Nothing is merged and no mutation score exists |
| R55 | **The modern Python toolchain, operational** | "also we need to get all of this operatioal" — uv, Ruff, Pytest with xdist and pytest-cov, Mypy or Pyright, LangGraph, LlamaIndex, CrewAI, DSPy | **PARTLY** | measured 2026-08-21. Operational: uv (CI builds every venv with it), Ruff as a linter (`ruff.toml`, run first in the commit gate, scoped to the diff), pytest-xdist (`pytest.ini` runs `-n auto --dist loadfile`). NOT operational: Ruff as a formatter (1430 of 1822 files would be reformatted, so nothing enforces it), pytest-cov (not installed, not declared, no coverage number exists), Mypy or Pyright (not installed, no config, no gate step, no CI job). LangGraph has a standing ruling: no for the engine core, yes for new agent-coordination work. LlamaIndex, CrewAI and DSPy have never been ruled on |

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
| Q5 | Does `~/.claude` go to a **public** GitHub repository, or a private one? (R36) | it is outward-facing, and the directory holds credentials, transcripts and estate state — a secret audit must precede either answer |
| Q6 | May an agent **page the founder's phone** out of hours, and at what severity? (R23) | it interrupts him, which is the cost this whole programme exists to reduce |

---

## 4. How to add a row

**Never link to a path outside the repository.** `~/.claude/...`, `~/.hermes/...` and any
other absolute home path goes in a code span, never in `[text](../../...)` form.
`tests/unit/test_doc_lint_links.py` resolves every link target on disk relative to the repo,
so a repo-escaping link is a guaranteed CI failure. It cost a revert of PR #558 on
2026-08-21: the PR was green because a docs-only diff SKIPS the `python` lane, and the test
that grades docs lives in that lane, so the failure only appeared once it was on `main`.

Append with the next number. Put the founder's words in verbatim — a wish paraphrased is a wish
reinterpreted. Set State to `NOT STARTED` and Proof to `—`. Never renumber: a stable number is
what makes a link to it worth anything.
