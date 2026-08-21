# Every shareable link, in one place

Status: INDEX. Last updated 2026-08-18.

**Why this file exists.** Thirty-nine documents had been published as shareable web pages and not
one of them was linked from anywhere in the repo. Verified before this file was written:

```
$ rg -c "claude.ai/code/artifact" README.md docs/*.md
(no output)
```

Every URL lived only in a chat transcript, which means a link that nobody saved was a link that
was gone. This file is the index. **When you publish a page, add the line here in the same
commit.** A URL that is not in this file does not exist.

Pages are **private by default**. Opening one requires the owner's account, or a share from the
page's own share menu. Nothing here is public.

---

## The prize

The target the platform is being rebuilt against. It is first in this file, and therefore first on
the console's Reports page, because it is the one page that must never go missing: everything else
here describes what the estate IS, and this one describes what it is FOR.

| What | Page | File |
|---|---|---|
| The target platform, the ten planes, and the 60 requirements with the drill that proves each one | [THE GOLD STAR PLAN](https://claude.ai/code/artifact/ef6fe784-7f6c-4981-85cd-37dfbe40b696) | `docs/MIGRATION_AND_DR_PROGRAM.md` |
| The build spec: twelve components, their interfaces, and the six slices that deliver them | — | `docs/GOLD_STANDARD_SPEC.md` |

---

## Estate governance

How this estate governs itself, measured rather than asserted. The design page and its evidence
page are a pair: read the design, and follow any number in it back to the reading that produced it.

| Page | What it is for | File |
|---|---|---|
| [The Closed Loop](https://claude.ai/code/artifact/0fe9a113-b1cb-4b42-8c2f-539bee95a1de) | The design: one defect at three altitudes — the guard, the work item, the session — the seven proposed non-functional laws, and the order to build in | no file, chat only |
| [What Actually Refuses](https://claude.ai/code/artifact/4d93ddd1-fb92-4304-bfe7-1a6f4ff22801) | The evidence behind it: what the 28 guard mechanisms actually refuse, on which runtimes, at what latency, and the three times the instrument was wrong before the reading was | no file, chat only |

---

## The twenty seats

Twenty audits of the same platform, each written for one role. Read the index first if you do
not know which seat you are in.

| Seat | Page | File |
|---|---|---|
| Index, all twenty | [The platform, seen from twenty seats](https://claude.ai/code/artifact/61068c14-8180-4aac-9d1d-cae0145f29ce) | `docs/personas/README.md` |
| Founder | [link](https://claude.ai/code/artifact/b1870433-3533-4822-ab62-fec68ad7ce74) | `docs/personas/founder.md` |
| Architect | [link](https://claude.ai/code/artifact/5c0f15ea-f9a1-4b83-a9da-34cc45f73991) | `docs/personas/architect.md` |
| Principal developer | [link](https://claude.ai/code/artifact/ddde9818-b923-413a-b5d3-40fcc8a23127) | `docs/personas/principal-developer.md` |
| Senior developer | [link](https://claude.ai/code/artifact/9a6233e6-1246-4e78-b74b-ba747a1b91da) | `docs/personas/senior-developer.md` |
| Developer | [link](https://claude.ai/code/artifact/aafe1b35-d40b-4bb0-9d04-a802c261c593) | `docs/personas/developer.md` |
| New joiner | [link](https://claude.ai/code/artifact/c34e9dab-44d7-4b84-bac8-0943ad03acd1) | `docs/personas/new-joiner.md` |
| QA / test engineer | [link](https://claude.ai/code/artifact/49dffe7c-2631-4318-bede-e92e737f13e8) | `docs/personas/qa-test-engineer.md` |
| Data engineer | [link](https://claude.ai/code/artifact/75a35197-b3d6-4ec0-a33d-5c6325d37088) | `docs/personas/data-engineer.md` |
| ML engineer | [link](https://claude.ai/code/artifact/a3004bad-4517-4665-86aa-2ba3c48d93e1) | `docs/personas/machine-learning-engineer.md` |
| SRE / on-call | [link](https://claude.ai/code/artifact/f3018fb1-1ad0-4355-b58e-3204579b1d8a) | `docs/personas/sre-on-call.md` |
| Ops | [link](https://claude.ai/code/artifact/0642e280-36c0-4678-88fa-bad05368f5ae) | `docs/personas/ops.md` |
| Security | [link](https://claude.ai/code/artifact/328b4fb5-3f33-4656-9781-bf966140208b) | `docs/personas/security.md` |
| Legal and privacy | [link](https://claude.ai/code/artifact/f4214028-8e7b-4af2-9ff7-96bc7baf884d) | `docs/personas/legal-privacy.md` |
| Finance | [link](https://claude.ai/code/artifact/0826c2c8-d0ae-4cf9-bab8-d2213ea8e6de) | `docs/personas/finance.md` |
| Product manager | [link](https://claude.ai/code/artifact/9bd80663-4926-43e6-a1cf-ed977763d2d3) | `docs/personas/product-manager.md` |
| Growth and marketing | [link](https://claude.ai/code/artifact/e667db19-d3ff-411e-b914-aac3e6fc4e3f) | `docs/personas/growth-marketing.md` |
| Content management | [link](https://claude.ai/code/artifact/ac19b8bc-558a-4211-9dcd-704401494bb2) | `docs/personas/content-management.md` |
| Analyst | [link](https://claude.ai/code/artifact/e6e72ad3-9742-4487-acac-c7bc7e62dadf) | `docs/personas/analyst.md` |
| Support | [link](https://claude.ai/code/artifact/e40baaa6-f771-4a77-bce2-73ba31c705bf) | `docs/personas/support.md` |
| Buyer | [link](https://claude.ai/code/artifact/d50c6ed8-1e1c-4fc0-8d8a-c0c2dd3cc723) | `docs/personas/buyer.md` |

## Briefs and programmes

| Page | What it is for | File |
|---|---|---|
| [Pricing and content, end to end](https://claude.ai/code/artifact/b8892420-5a6d-43df-9aad-bc17e8d550ae) | Briefing an external consultant on the two fragile parts of the system | `docs/CONSULTANT_BRIEF_PRICING_AND_CONTENT.md` |
| [Ops console programme](https://claude.ai/code/artifact/544dcf99-afe1-49e9-9f39-b727ea9fce9d) | What the operator console must do, and its status ledger | `docs/OPS_CONSOLE_PROGRAM.md` |
| [Engine audit and story backlog, 2026-08-13](https://claude.ai/code/artifact/f8a47a1d-19e6-4459-99ea-ba16f7d2e169) | The engine's defects, ranked, with the stories that clear them | no file, chat only |
| [Engine war plan, order of attack](https://claude.ai/code/artifact/e3bda52e-84ce-4758-8e47-f535a60c105e) | Which engine problem to fix first and why | no file, chat only |
| [Launch blocker report and plan](https://claude.ai/code/artifact/8cdb6490-208b-4de3-81aa-927eaad8e2bd) | What stood between the estate and selling, 2026-07-28 | no file, chat only |
| [The demand rail](https://claude.ai/code/artifact/590905ac-52dd-40c2-b207-78670756b26a) | Persona-aware packaging and learning, proposal | no file, chat only |
| [Hermes cockpit UX review](https://claude.ai/code/artifact/68a4c251-ea8a-461e-889b-c970db2b74f7) | What the cockpit gets wrong and a proposed shape | no file, chat only |

Five of those seven exist **only** as a web page. If the page goes, the thinking goes. Pulling
them back into `docs/` is tracked as its own job.

## Design and brand

| Page | What it decided |
|---|---|
| [Mumchimp brand mark, six concepts](https://claude.ai/code/artifact/475ffec4-dfc0-4cbc-931b-8002dc0fd667) | Mark options. One of ten was accepted; the rest were rejected |
| [Colour as a weapon, decision sheet](https://claude.ai/code/artifact/cb8c58ee-a808-4a54-ba0c-f5feb8b63596) | How colour is allowed to work on the storefront |
| [Five colourways](https://claude.ai/code/artifact/ea047d6b-0331-4737-9fc6-8417e6987e5e) | Palette options |
| [Card directions, four ways out of monochrome](https://claude.ai/code/artifact/4d5a1146-d133-4f64-bfa9-0dc54d8fb3fe) | Shelf card treatment |
| [Shelf cards: three packs, two title registers](https://claude.ai/code/artifact/f1256b3d-12c4-4688-adc9-72c23089ffec) | Which title register a card should use |
| [2050 hero specimen](https://claude.ai/code/artifact/5950ca8f-21b4-4629-a86e-2787c2acbf5e) | Hero type treatment |
| [The Cut](https://claude.ai/code/artifact/8d146770-b0dc-4208-a5b9-1e6c94b94093) | A storefront direction |
| [Sample Sheet](https://claude.ai/code/artifact/3fc0d907-a9c0-44ef-abae-569fe94c4c3d) | All 29 plates from the 2026-08-20 redesign session, in the order they were made |
| [The Assay Sheet](https://claude.ai/code/artifact/d0ada5d9-4994-434f-b6cd-e5bdac499a14) | All **18 designed routes** as light-on-dark plates, with the real on-disk copy for each, the copy-layer coverage, and the pack-image collision measurement with its fix |
| [Ten Looks](https://claude.ai/code/artifact/06f86a35-a240-4495-a685-fac2aed5684e) | The look engine itself, live — switch identity, flip theme, roll an eleventh from a seed |
| [Storefront Today](https://claude.ai/code/artifact/8d204575-9ecd-45c6-b1e2-7b86fc8b826c) | The site as it stands at `017516af`, so the ten looks have a before to be compared against |

## Tooling

| Page | What it shows |
|---|---|
| [The Automation Ledger](https://claude.ai/code/artifact/ec383383-851a-41ae-8215-477d7e96244e) | Every tool built, which gate it implements, and what it refuses. Generated from the tools' own header lines, so it cannot list a tool that is not on disk. Linked from `README.md` under Tooling and quality gates. |

## Product samples

| Page | What it shows |
|---|---|
| [Every pack, without paying for one](https://claude.ai/code/artifact/79d0dd5a-c6c3-44a8-8d6b-b73b968729c1) | The whole catalogue as a browsable preview |
| [Pack contents, what a buyer actually receives](https://claude.ai/code/artifact/fb38c322-6f14-4b8e-b623-1c84df79684b) | The 14 sections, rendered |
| [The rewritten pack](https://claude.ai/code/artifact/37d754e6-eef9-4035-a9de-363397f920a8) | A pack after the copy rewrite, for comparison |
| [StorySprout operator kit](https://claude.ai/code/artifact/e729c389-7cab-4e67-82a2-ee60dc8c466e) | One pack's operator kit in full |

---

## The estate, in commands rather than links

A link is a document. The live answer to "is it working" is always a command. These are the ones
that matter, and none of them changes anything:

```bash
bash ~/.hermes/scripts/verify_estate.sh          # whole estate: DEPLOY / DOOR / R1-R5 / FENCES
.venv/bin/python scripts/live_checkout.py        # is production running the code we think it is
.venv/bin/python scripts/ops_status.py           # the readiness grades
.venv/bin/python scripts/estate_census.py        # what is in the repo and what nothing refers to
python3 scripts/graphify_sweep.py --check-hooks  # is the knowledge graph actually being kept fresh
```

The map of what each `verify_estate.sh` line means is `~/.hermes/ESTATE_STATE.md`. The map of the
whole estate as a system is [`docs/ESTATE_MAP.md`](ESTATE_MAP.md).

## Tracked programmes

Each of these has its own spec and its own status ledger. Append results there, never in
`CLAUDE.md`:

- [`docs/PLATFORM_MANIFESTO.md`](PLATFORM_MANIFESTO.md) — the constitution: ten laws, the agent
  tenets, portability targets and drills, the automation audit. Read this one first
- [`docs/ARCHITECTURE_SECURITY_BASELINE.md`](ARCHITECTURE_SECURITY_BASELINE.md) — the measured
  baseline: architecture, critical path tests, security posture, mud
- [`docs/WAYS_OF_WORKING.md`](WAYS_OF_WORKING.md) — the 25 working rules and which of them a
  machine actually enforces
- [`docs/COST_PROGRAM.md`](COST_PROGRAM.md) — every cost lever, every measurement, every retired number
- [`docs/GRAPHIFY_ENFORCEMENT_SPEC.md`](GRAPHIFY_ENFORCEMENT_SPEC.md) — keeping the knowledge graph fresh across the estate
- [`docs/SITE_SPEC_PROGRAM.md`](SITE_SPEC_PROGRAM.md) — the storefront design, UX and copy spec
- [`docs/PACK_NARRATIVE_PROGRAM.md`](PACK_NARRATIVE_PROGRAM.md) — what the buyer actually reads
- [`docs/CONTENT_CONTRACT_PROGRAM.md`](CONTENT_CONTRACT_PROGRAM.md) — why copy rules exist and which ones actually bite
- [`docs/LAUNCH_OPS_PROGRAM.md`](LAUNCH_OPS_PROGRAM.md) — the production automation programme
