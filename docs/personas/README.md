# The platform, seen from twenty seats

One document per persona. Same platform, twenty different sets of questions.

The point is coverage. A single architecture document is written from one seat, and everything that
seat does not care about goes missing. Someone joining as an on-call engineer does not need the
scoring weights; someone tuning the scoring weights does not need the launchd job list. Both need to
find their half in under a minute, and neither should have to read the other's half to get there.

## How these relate to the rest of the docs

- **[ESTATE_MAP.md](../ESTATE_MAP.md) is the factual spine.** What runs, where, and how the parts
  connect. Every persona document points back at it rather than restating it, because a fact
  restated in twenty places drifts in nineteen of them.
- **`scripts/estate_map.py` is the live answer.** State asserted in prose goes stale. Run the probe.
- **The programme docs are the depth.** `docs/COST_PROGRAM.md`, `docs/PACK_NARRATIVE_PROGRAM.md`,
  `docs/SITE_SPEC_PROGRAM.md`, `docs/GRAPHIFY_ENFORCEMENT_SPEC.md`, `docs/LAUNCH_OPS_PROGRAM.md`.
  A persona document tells you which of those is yours.

## The seats

### The ones who decide

| Persona | The question they arrive with |
|---|---|
| [Founder](founder.md) | Is this making money, is it about to break, and what is the one thing to do next |
| [Product manager](product-manager.md) | What does the buyer actually get, and what should we build next |
| [Finance](finance.md) | What does it cost to run, what does it earn, and where can that surprise us |
| [Analyst](analyst.md) | Where does the funnel leak, and can I trust the number I am about to quote |

### The ones who run it

| Persona | The question they arrive with |
|---|---|
| [Ops](ops.md) | What is the state right now, and which button changes it |
| [SRE / on-call](sre-on-call.md) | It is 3am and something is red. What is broken and what do I do |
| [Security](security.md) | What is the blast radius, where are the secrets, who can reach what |
| [Legal and privacy](legal-privacy.md) | What personal data do we hold, and what do we claim in public |

### The ones who build it

| Persona | The question they arrive with |
|---|---|
| [Developer](developer.md) | How do I get a change from my head to production without breaking anything |
| [Senior developer](senior-developer.md) | Where are the sharp edges, and which mechanism already does this |
| [Principal developer](principal-developer.md) | Which of our invariants are actually enforced, and which are only written down |
| [Architect](architect.md) | What are the seams, and what happens the day we leave Fly |
| [QA / test engineer](qa-test-engineer.md) | What does green mean here, and where does green lie |

### The ones who work with the data and the words

| Persona | The question they arrive with |
|---|---|
| [Machine learning engineer](machine-learning-engineer.md) | Where do models make decisions, and how would I know if one got worse |
| [Data engineer](data-engineer.md) | Where does every byte live, what shape is it, and how do I get it back |
| [Content management](content-management.md) | Who writes the words a buyer reads, and how do I change them |
| [Growth and marketing](growth-marketing.md) | How does anybody find us, and what can I change without a deploy |

### The ones on the other side of the counter

| Persona | The question they arrive with |
|---|---|
| [Buyer](buyer.md) | What am I paying for, and what happens after I pay |
| [Support](support.md) | A customer says it did not arrive. How do I find out and fix it |
| [New joiner](new-joiner.md) | It is day one. What is this thing and what do I read first |

## The rule these all obey

Every document here says where its facts come from: a `file:line`, a command you can run, or a
receipt on disk. Where something is not built, it says so out loud rather than leaving a gap that
reads as coverage. If you find a claim in here with no source behind it, that is a defect — fix it in
place.
