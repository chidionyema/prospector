# Open work — the plate

> One tracked file listing everything asked for and not yet delivered. It exists because a worklist
> held in a chat window is gone at the next compaction (LAW 9: track the workload on disk; LAW 16:
> leave a path back when you drop something). Every row names the founder's words, the owning
> document, and the exact next command or file. Close a row by deleting it and writing the receipt
> into the owning doc — never by marking it done here.
>
> Last measured 2026-08-20.

## A. Live now

| # | What was asked, in the founder's words | Owning doc | Next action |
|---|---|---|---|
| A1 | "radicall inprovent in quality and relevance" of the pack image; "eponential" | `CARD_IMAGERY_RESEARCH.md` §8 | §8 written. Build the evidence-field renderer behind the existing `evidenceTicks.ts` seam. |
| A2 | "1000 inprevevnt insanples" | this file, §D | The bar is now four rules, §D. Assay Sheet is the first sheet made at it. |
| A3 | "need all pages not just landing" | this file, §D | DONE for plates: all **18 designed routes** on the Assay Sheet. 24 route files, 5 render no pixels. Still open: rendered screenshots of each. |
| A4 | "light over dark background for sanples" | this file, §D | DONE on the Assay Sheet — committed single-theme, cold slate ground, bone type, one hallmark gold. Earlier plate sets are still light-ground. |
| A5 | "update readne with this <tooling ledger> all tooling and quality tolls also engine etc" | `README.md` | DONE. New "Tooling and quality gates" section, 15 gates each with what it refuses, ledger linked. Also fixed the stale "no hosted API" heading, superseded 2026-08-18. Four artifacts added to `docs/LINKS.md`. |
| A6 | "how about content nanagenet" | this file, §C | ANSWERED and measured. The seam exists (`copyConfig.ts`, 13 slots) and 4 of ~18 routes use it. Proposal is 3 steps, start at 1. |

## B. Carried, not dropped

| # | What | Owning doc | State |
|---|---|---|---|
| B1 | Docs-as-shareable-links from the ops dashboard | `docs.tsx` | Rail proven live end-to-end. `/docs` share button written, uncommitted, needs a `pages.test.ts` assertion. |
| B2 | Every report reachable from the ops dashboard | Ops.Console `/docs`, `/reports` | **CLOSED 2026-08-20.** Two halves. The read half was already working: `READS['docs']` indexes 128 documents in 11 sections, `LINKS.md` is one of them and holds 44 artifact URLs with the Assay Sheet (`d0ada5d9`) among them, and `docs.tsx:247` reads `router.query.open` so `/docs?open=LINKS.md` opens the list directly. The gap was that no nav entry pointed at it, so the gallery was one row among 128. The founder ruled on it — "new link for it" — so `/reports` is now its own screen with its own nav entry beside Docs in the Data group. It holds no list of its own: it parses `docs/LINKS.md` through the same `docs` read, so it updates when LINKS.md updates. It also carries the on/off switch the founder asked for ("the links can be turned on/off fron being publically share"): every sheet with a repo file behind it gets a `share.create` / `share.revoke` pair, and the second card lists every token ever minted with its read count and status. 23 of the 44 have a source file; the other 21 were written straight to claude.ai and carry no switch, which the page says once at the top. The nav screen cap in `nav.test.ts` moved 4 -> 5 on a two-angle measurement: `Shell.tsx:102,121` are both `flex flex-wrap` so neither row can scroll sideways, and `e2e/mobile.spec.ts` walked eleven screens at 390x844 and 320x568 with zero horizontal overflow, 6 passed 0 failed. |
| B3 | Laws injector cap | `~/.claude/scripts/memory-loop.py` | FIXED, 22/22 selftest. A peer proposes a smaller trim; that is a founder decision, not mine. |
| B4 | Auth + payments modularisation (C40) | — | PARKED at the founder's instruction: "sorry lowest priotity that one". |
| B7 | No POPDD lane claims `scripts/*.sh`, so a shell change is proven by nothing | `scripts/popdd_verify.py:97` `SOURCE_EXTS`, `:325` `lanes_for` | **OPEN, measured 2026-08-20.** `lanes_for` is pure, so it can be called directly: `scripts/setup_worktree.sh` returns `lanes=[] unclassified=[]`, and so do `scripts/verify_engine_change.sh` and `deploy/engine/supervisord.conf`. `.sh` is not in `SOURCE_EXTS`, so a shell file is neither claimed by a lane nor flagged as unclassified — it falls through both branches. A commit carrying only a shell script therefore prints a green verdict having run no lane at all. Same class as Ops.Console before 2026-08-16, when no lane claimed it and every file in it read as proven. `setup_worktree.sh` is load-bearing infrastructure and is in exactly this position. Proposed fix: a `shell` lane running `bash -n` over the staged `.sh` files, plus `shellcheck` when it is installed. NOT taken unilaterally — the lane map is shared by every session, and macOS ships bash 3.2, so `bash -n` could refuse valid bash 5 syntax and block commits estate-wide. That needs a peer to check before it lands. Handed over by wt-storeroot-1e, who found it. |
| B8 | The push fence exempts a just-merged branch, so the next push lands with no PR and merges nothing | `~/.claude/scripts/push-pr-fence.py:444` | **OPEN, measured 2026-08-20 22:03-22:30.** PR #528 merged at 22:03:07 with head `21920978`. Two commits pushed onto `integrate/2026-08-20-final` minutes later: push succeeded, CI ran, CI passed, work reached nothing. `gh pr list --head integrate/2026-08-20-final --state open` -> `[]`, and `automerge.yml` only merges an OPEN pull request, so a green run is worth nothing. It looks exactly like shipping. The fence has the check and never reaches it: `if merged_into_main(out.split()[0], cwd): continue` grades the REMOTE tip, which seconds after a merge is by definition an ancestor of main. It grades the ref you push ONTO, not the commits you push — same class as the other proxy guards measured today. The obvious fix is wrong: adding "and the local head is also in main" re-creates the deadlock the exemption exists for, where `gh pr create` answers "No commits between main and <branch>" and the fence demands a review that cannot be opened. A PreToolUse hook cannot solve this by blocking — the push is what makes the PR openable, so the warning has to come AFTER it succeeds, which is a PostToolUse hook rather than an edit to this one. NOT taken alone: machine-wide guard, and cross-session messaging was down, so no second angle was available. Needs a peer to check before it lands. Interim: run `gh pr list --head <branch> --state open` after every push to a branch that has just merged. Memory: `a-merged-branch-swallows-your-next-push.md`. |

## C. Content management — answered, 2026-08-20

Founder: *"how about content nanagenet"*.

**The seam already exists and only three pages use it.** This is not a missing system; it is a
half-adopted one, which is the more expensive state because it looks solved.

What is on disk:

| Piece | What it is | Lines |
|---|---|---|
| `lib/copyConfig.ts` | Centralised A/B/C copy dictionary, **13 slots**. Its own docblock: *"OWNER: the founder. Every string below is the founder's copy, no AI generation, no runtime modification."* | 230 |
| `lib/getCopyVariant.ts` | Resolves the variant: `?variant=` → cookie → default `a`. Crawlers always get `a`, so SEO stays stable. | 38 |
| `lib/faqContent.ts` | The **one** source read by both the visible FAQ and its `FAQPage` structured data, because Google drops schema that says more than the page does. | 206 |
| `lib/siteCopy.ts`, `lib/gateLabels.ts`, `lib/disclaimer.ts` | Other extracted copy surfaces. | — |

**The coverage measurement.** Pages that read the copy layer: `how-it-works.tsx`,
`ideas/index.tsx`, `ideas/[slug].tsx`, `faq.tsx`. That is 4 of ~18 designed routes.

Authored copy by page, counting string literals of 25+ characters:

```
32  pages/index.tsx          <- the densest page, and it reads NO dictionary
27  pages/pack/[id].tsx      <- the page a buyer reads before paying
17  pages/orders/success.tsx
13  pages/pricing.tsx
11  pages/ideas/index.tsx        (reads the dictionary)
10  pages/how-it-works.tsx       (reads the dictionary)
 9  pages/kill-log.tsx
 8  pages/privacy.tsx
```

**What this costs today.** Changing a word on the landing page is a code edit, a PR, a CI run and a
deploy. Changing a word on `how-it-works` is an edit to one dictionary. The two most commercially
important pages — the landing page and the pack page — are on the expensive side.

**What is deliberately out of scope.** Pack copy is engine-owned: the `pack_*.py` renderers are
deterministic and model-free by rule (`PACK_NARRATIVE_PROGRAM.md`), and the catalogue is the source
for anything about a specific pack. A CMS must never be able to edit a claim the engine grounded —
source-or-die applies to the storefront too. The line is: **chrome is authored, evidence is
generated.**

**The proposal, smallest first.** No new system, no headless CMS, no new dependency:

1. Extend `copyConfig.ts` to cover `index.tsx` and `pack/[id].tsx` chrome. Same dictionary, same
   ownership note, more slots. This alone moves the two expensive pages onto the cheap path.
2. Add a test that fails when a page renders an authored string of over N characters that is not
   from the dictionary — the guard, so coverage cannot silently rot back. Grade it on a closed
   allow-list of dictionary KEYS, never a grep for English words: a peer's write-time refusal
   rejected two correct rows on its first two runs doing exactly that.
3. Only if 1 and 2 are not enough: an `Ops.Console` editing surface. The write path already exists
   and is governed — every write goes through `Confirm` (preview what would change, then apply
   quoting the token the preview handed back). A copy editor is a new `ACTS` entry, not a new app.

Do not start at 3. Steps 1 and 2 are a day and remove the recurring cost; step 3 adds a surface to
maintain forever (LAW 14 — an operational cost needs a stronger case than a one-off).

## D. The samples — the bar, and what has been made

Founder: *"1000 inprevevnt insanples"*, *"need all pages not just landing"*, *"light over dark
background for sanples"*.

**The bar a sample has to clear now.** Earlier plate sets looked finished and were not checkable.
Every plate must meet all four:

1. **No invented copy.** Every headline on a plate is a string that exists on disk, at a named path.
2. **Every number measured**, with the command that produced it recorded in the owning doc.
3. **Structure encodes something true.** Plate size, bar height, ordering — each must be a
   measurement, not a layout choice. On the Assay Sheet, plate size is authored-copy density.
4. **An honest-gaps section on the sheet itself.** A sample that cannot say what it is *not* proving
   is a picture, not evidence.

**Made so far:**

| Sheet | Covers | Ground |
|---|---|---|
| [The Assay Sheet](https://claude.ai/code/artifact/d0ada5d9-4994-434f-b6cd-e5bdac499a14) | All 18 designed routes + the pack-image measurement | light on dark |
| [Sample Sheet](https://claude.ai/code/artifact/3fc0d907-a9c0-44ef-abae-569fe94c4c3d) | 29 plates, 3 cover + 13 storefront looks in both themes | light ground |
| [Ten Looks](https://claude.ai/code/artifact/06f86a35-a240-4495-a685-fac2aed5684e) | The look engine live — switch identity, flip theme, roll a seed | both |
| [Storefront Today](https://claude.ai/code/artifact/8d204575-9ecd-45c6-b1e2-7b86fc8b826c) | The site at `017516af`, as the before | as built |

**Still open.** Rendered screenshots of each of the 18 routes, so a plate can be held against the
live page rather than against its source. That needs the Next app running, which needs the missing
`node_modules` in this checkout (`@axe-core/playwright`, `react-markdown`, `remark-gfm`,
`eslint-plugin-tailwindcss` are all absent — an install gap, not a defect).
