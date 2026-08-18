# Persona documents — the index

Twenty-one documents. Twenty seats plus this index.

**What the set is.** Each document is a **total system audit from one seat**. Not a summary, not a
job description, not an onboarding blurb. Each one answers, for its reader: what exists, where it
runs, what it costs, what is broken, what is unknown, and which command settles each question. The
target is that a reader — human or model — can hand one of these to an unfamiliar reader and they
can reason about the whole system from that angle without opening anything else.

**The rule that governs the set.** A fact lives in **one** place. The shared factual spine is
[../ESTATE_MAP.md](../ESTATE_MAP.md) — deployment topology, service names, store paths, config keys,
the risk register. A persona document reads that spine and adds the *seat's* reading of it: what
this reader does about it, in what order, with what authority. When a persona document and the
estate map disagree, the estate map is the one to fix first, then the persona.

The failure this rule exists to prevent is already on the record in `CLAUDE.md`: the same claim
written in four places goes stale in three of them, and nobody can tell which copy is current. Twenty
documents multiply that risk by twenty unless facts are centralised.

---

## The twenty-one documents

Grouped by what the reader is there to do. Line counts measured **2026-08-18 13:07Z**. Several
siblings were being rewritten at that moment, so the short ones are the pre-rewrite versions and
will have grown — re-run `wc -l docs/personas/*.md` for current figures.

### Decide — the people who choose

| Document | The question it answers | Lines (13:07Z) |
|---|---|---|
| [founder.md](founder.md) | What is this business worth, what does it cost me, what is about to break, and what can only I decide? | 791 |
| [finance.md](finance.md) | Where did the money go, what came back, and which meter is blind? | 92 |
| [product-manager.md](product-manager.md) | What are we building next, and what evidence says so? | 100 |
| [analyst.md](analyst.md) | What do the numbers actually say, and which ones are measurement artefacts? | 127 |
| [legal-privacy.md](legal-privacy.md) | Are we lawful, and what personal data do we hold? | 106 |

### Run — the people who keep it alive

| Document | The question it answers | Lines (13:07Z) |
|---|---|---|
| [sre-on-call.md](sre-on-call.md) | It is broken right now. What do I check, in what order, and what do I touch? | 936 |
| [ops.md](ops.md) | What is the daily operating surface, and which button does what? | 108 |
| [security.md](security.md) | Where are the secrets, who can reach them, and what is the blast radius? | 103 |
| [support.md](support.md) | A buyer has a problem. What can I see and what can I fix? | 89 |

### Build — the people who change it

| Document | The question it answers | Lines (13:07Z) |
|---|---|---|
| [architect.md](architect.md) | Why is the system shaped this way, and which seams are load-bearing? | 810 |
| [principal-developer.md](principal-developer.md) | How do I hold a large, multi-part change together across the estate? | 102 |
| [senior-developer.md](senior-developer.md) | How do I make a non-trivial change without breaking a rail? | 97 |
| [developer.md](developer.md) | How do I make a change at all, from branch to merged PR? | 120 |
| [qa-test-engineer.md](qa-test-engineer.md) | What is tested, what only looks tested, and how does a green run lie? | 116 |
| [new-joiner.md](new-joiner.md) | I start today. What is this, how do I set it up, and what will trip me up? | 583 |

### Data — the people who move and judge the information

| Document | The question it answers | Lines (13:07Z) |
|---|---|---|
| [data-engineer.md](data-engineer.md) | Where does the data live, how does it move, and what would we lose? | 106 |
| [machine-learning-engineer.md](machine-learning-engineer.md) | Which model rules what, on what evidence, behind which fence? | 126 |
| [content-management.md](content-management.md) | What does a pack actually say, who wrote it, and what grades it? | 565 |

### Outside — the people the system is for

| Document | The question it answers | Lines (13:07Z) |
|---|---|---|
| [buyer.md](buyer.md) | What does a customer see, pay and receive? | 89 |
| [growth-marketing.md](growth-marketing.md) | How does anyone find the shop, and what converts? | 79 |

### Index

| Document | The question it answers | Lines (13:07Z) |
|---|---|---|
| [README.md](README.md) | Which document do I open for this question? | this file |

### Related documents outside this directory

| Document | What it carries |
|---|---|
| [../ESTATE_MAP.md](../ESTATE_MAP.md) | The shared factual spine. Every persona reads it. 293 lines at 13:07Z. |
| [../LOGGING_AND_RETENTION.md](../LOGGING_AND_RETENTION.md) | What the system logs, where it lands, and how long it is kept. **Not yet on disk at 13:07Z** — being written now. The check: `ls -la docs/LOGGING_AND_RETENTION.md`. |
| `../RUNBOOKS.md` | Step-by-step recovery procedures the on-call document points at. |
| `../LAUNCH_OPS_PROGRAM.md` | The tracked risk programme that `scripts/ops_status.py` grades. |
| `../COST_PROGRAM.md` | Every cost lever, measurement and retired number. |
| `../PACK_NARRATIVE_PROGRAM.md` | What the buyer reads, and the renderers that produce it. |
| `../SITE_SPEC_PROGRAM.md` | The storefront design, UX and copy spec, plus its live status ledger. |

---

## Start here — a routing table

Given a question, open this.

| Your question | Open |
|---|---|
| Is the engine running right now? | [sre-on-call.md](sre-on-call.md) §probes, or run `fly status -a prospector-engine` and read `/data/store/scheduler/heartbeat.json` on the volume. **Not** `scripts/live_checkout.py` — it probes the laptop deployment retired on 2026-08-18 (see [founder.md](founder.md) §4.0) |
| Is the shop up and can it take money? | [founder.md](founder.md) §9, or `curl -s https://api.mumchimp.com/healthz/money-rail` |
| How much have we spent, in total and today? | [finance.md](finance.md); [founder.md](founder.md) §2 |
| How much have we earned? | [finance.md](finance.md) — and note this needs a key; [founder.md](founder.md) §2.2 marks it unproven |
| Which spend meter is blind, and to what? | [founder.md](founder.md) §2.3; [finance.md](finance.md) |
| How do I stop all spending right now? | [ops.md](ops.md); the switch is `touch store/scheduler/PAUSE` |
| What is on the shelf and what is it worth? | [founder.md](founder.md) §1.2; [buyer.md](buyer.md) |
| Why did the engine kill this idea? | [machine-learning-engineer.md](machine-learning-engineer.md); the dossier at `store/dossiers/<id>.kill.json` |
| Why is a finished pack not for sale? | [content-management.md](content-management.md); [ops.md](ops.md) |
| What does a pack contain and who decided the wording? | [content-management.md](content-management.md) |
| How is a price chosen? | [founder.md](founder.md) §1.1; [analyst.md](analyst.md); `config.yaml:1829` |
| Which model rules a verdict, and can I change it? | [machine-learning-engineer.md](machine-learning-engineer.md) |
| What happens when a provider runs out of credit? | [machine-learning-engineer.md](machine-learning-engineer.md); [sre-on-call.md](sre-on-call.md) |
| I am new. Where do I start? | [new-joiner.md](new-joiner.md) |
| How do I set up a worktree without breaking the gate? | [new-joiner.md](new-joiner.md) §4; [developer.md](developer.md) |
| My commit was refused and I do not know why | [developer.md](developer.md); [qa-test-engineer.md](qa-test-engineer.md) |
| The tests are green but I do not trust them | [qa-test-engineer.md](qa-test-engineer.md) |
| I need to change something across the engine and the shop | [principal-developer.md](principal-developer.md); [architect.md](architect.md) |
| Why is it built this way? | [architect.md](architect.md) |
| Where does production actually run? | [../ESTATE_MAP.md](../ESTATE_MAP.md); [sre-on-call.md](sre-on-call.md) |
| What would we lose if the laptop died? | [founder.md](founder.md) §4.4; [data-engineer.md](data-engineer.md) |
| Are the backups real, and has a restore ever been proven? | [data-engineer.md](data-engineer.md); [founder.md](founder.md) §5 Rank 3 |
| Where are the secrets and who can reach them? | [security.md](security.md) |
| A customer says their download did not arrive | [support.md](support.md) |
| A customer wants a refund | [support.md](support.md); [finance.md](finance.md) |
| Do we have a lawful basis for the data we hold? | [legal-privacy.md](legal-privacy.md) |
| Is the site discoverable, and what converts? | [growth-marketing.md](growth-marketing.md) |
| What is worth building next? | [product-manager.md](product-manager.md); [analyst.md](analyst.md) |
| Is this number real? | [analyst.md](analyst.md); [founder.md](founder.md) §8 |
| What gets logged, and for how long? | [../LOGGING_AND_RETENTION.md](../LOGGING_AND_RETENTION.md) |
| What decisions are blocked on the founder? | [founder.md](founder.md) §6 |

---

## The rules every document in this set obeys

If you write or edit one of these, keep the standard. All five come from `CLAUDE.md` at the repo
root, which governs the whole estate.

**1. Every claim carries its receipt inline.** A `path/file.py:123`, a command with its actual
output, or a named artefact on disk. In the same sentence or the same table row — not in a footnote,
not "see the code". If you cannot prove it, write `HYPOTHESIS:` and the exact command that would
confirm or kill it. An honest unknown with a check attached is worth more than a confident guess.

**2. No number you did not measure.** Run the command. Paste the output. Every count, size, line
number and price in these documents was measured by the writer in the session that wrote it, and
each document says when. Numbers copied from another document are how the estate went stale in the
first place.

**3. Plain English.** Short sentences. Subject, verb, object. Conclusion first, then the evidence.
No aphorisms as headings, no dramatic reveals, no rhetorical questions, no personification — say who
did what. One idea per sentence. If a sentence needs a second read, rewrite it.

**4. State is a probe, never a sentence.** Anything that can change — is it running, is it deployed,
is it green, how much did it cost — is written as a **command**, not as a claim. A document that
says "the daemon is running" is wrong within the hour. A document that says "run `fly status -a
prospector-engine`; `state = started` is healthy" is right for as long as the app exists. Prose
describes mechanisms; commands report state.

The corollary was paid for on 2026-08-18: **a probe must be retired with the thing it probes.**
`scripts/live_checkout.py` outlived the laptop deployment it was written for, so it now reports a
total outage that is not happening. A stale command is as wrong as a stale sentence, and it is more
convincing.

**5. A fact lives in one place.** Shared facts go in [../ESTATE_MAP.md](../ESTATE_MAP.md) and are
linked, not copied. A persona document may *interpret* a shared fact for its seat — that is the
whole point of the seat — but it must not restate it as an independent claim, because the copy will
drift and nobody will know which one is current.

**Two more, specific to this set:**

**6. Never print a secret value.** Key *names* are fine and useful — `STRIPE_LIVE_API_KEY`,
`MINIMAX_API_KEY`. Values never appear, in any document, in any example, in any pasted command
output. When a command needs a key, show the shell variable, not the string.

**7. Cross-link by relative path.** `[ops.md](ops.md)` for siblings, `[../ESTATE_MAP.md](../ESTATE_MAP.md)`
for the spine. The set is meant to be read as a web, and a reader who lands on one document should
be one click from the right one.

---

## Keeping the set honest

The set has the same failure mode as everything else here: it is prose, and prose drifts. Three
mechanical checks keep it from rotting.

```bash
# Are all twenty-one present, and how long is each?
wc -l docs/personas/*.md

# Does every relative link resolve?
grep -oh '](\.\./\?[A-Za-z0-9_./-]*\.md)' docs/personas/*.md | tr -d '](' | sort -u

# Does the doc linter still pass on this directory?
.venv/bin/python scripts/doc_lint.py
```

When a document's numbers are older than the thing they describe, the fix is to re-measure, not to
soften the wording. A stale number stated confidently is the exact defect this whole standard exists
to prevent.

---

*Index measured 2026-08-18 13:07Z from
`/Users/chidionyema/Documents/code/prospector` at HEAD `c3cb68b`. Sibling documents were being
written at that moment; re-run `wc -l docs/personas/*.md` for current lengths.*
