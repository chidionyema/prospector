# Card imagery — research, licences, and the open decision

> Status: RESEARCH COMPLETE, DECISION OPEN. Nothing built, no code changed.
> Every licence row below was fetched from its primary source on 2026-08-15. Rows marked
> `unverified` were NOT retrieved — do not promote them to fact without fetching them.
>
> The question that produced this doc: "can we use open source image generation for our cards
> for better engagement? even videos if possible" (founder, 2026-08-15).

---

## 0. The short version

1. **Licence-wise you are clear to generate.** FLUX.1 [schnell] and Qwen-Image are both Apache-2.0;
   outputs are yours outright, commercially, with no revenue threshold and no attribution.
2. **Hardware-wise you cannot generate here.** The dev machine is a 2018 Intel MacBook Pro with a
   4 GB AMD GPU. Video models want 80 GB. A rented GPU hour or a one-month-then-cancel subscription
   is the practical route for a one-off batch.
3. **There is no image slot to put anything in.** No field on the entity, no field in the API, no
   slot in the card component, no media path in the publish pipeline or R2. Five layers of new work.
4. **Three rules in `SITE_SPEC_PROGRAM.md` currently forbid it**, one of them naming AI output
   explicitly. That is a founder decision to make or overrule, not a technical blocker — §4.

---

## 1. Licences — fetched 2026-08-15, primary sources

| Model | Licence | Model use | Output use | Notes | Source |
|---|---|---|---|---|---|
| **FLUX.1 [schnell]** | **Apache-2.0** | ✅ commercial | ✅ commercial | *"can be used for personal, scientific, and commercial purposes"* | [HF card](https://huggingface.co/black-forest-labs/FLUX.1-schnell) |
| FLUX.1 [dev] | FLUX.1 [dev] Non-Commercial | ❌ | ✅ | **The rights split.** See §1.1 | [LICENSE.md](https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md) |
| **Qwen-Image** | **Apache-2.0** | ✅ | ✅ | Claims *"complex text rendering"* — the best option if a card ever carries a label | [HF card](https://huggingface.co/Qwen/Qwen-Image) |
| Stable Diffusion 3.5 | Stability Community | ✅ **below $1M/yr** | ✅ *"You own any outputs"* | Licence **terminates** above USD $1,000,000 annual revenue | [Community licence](https://stability.ai/community-license-agreement) |
| Wan 2.2 (video) | Apache-2.0 | ✅ | ✅ | Clean licence, impossible hardware — §2 | [HF card](https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B) |
| HunyuanVideo | tencent-hunyuan-community | `unverified` | `unverified` | Licence file 404'd. A suspected EU/UK territorial exclusion is **neither confirmed nor refuted**. A UK company must resolve this before use. | — |
| **unDraw** (not AI) | unDraw licence | ✅ | ✅ | No attribution: *"You do not need to ask permission from or provide credit"*. May not *"compile assets… to replicate a similar or competing service"* or redistribute *"in packs"*. | [Licence](https://undraw.co/license) |

### 1.1 The FLUX [dev] rights split — the trap

The licence grants two different things and people quote whichever half suits them:

- **Model:** *"You may only access, use, Distribute, or create Derivatives of the FLUX.1 [dev] Model
  or Derivatives for Non-Commercial Purposes."*
- **Output:** *"You may use Output for any purpose (including for commercial purposes), except as
  expressly prohibited herein."*

Black Forest Labs separately **sells** a paid FLUX.1 [dev] commercial licence, which is only coherent
if running the model inside a revenue-generating business is the restricted act. So the two clauses
are in tension for exactly our case. **FLUX.1 [schnell] has no such tension — use schnell.**

The popular claim *"Flux is Apache-2.0, so you own everything"* is **false as stated**: it is true of
schnell and false of dev, and dev is the one people mean when they praise FLUX quality.

**Adapter mislabelling is real.** `XLabs-AI/flux-ip-adapter-v2` carries an `apache-2.0` metadata tag
on Hugging Face while its own README says the weights follow the FLUX.1 [dev] Non-Commercial terms.
Read the README, never the tag. (Reported by a research subagent, single-source, `unverified`.)

---

## 2. Hardware — measured on this machine 2026-08-15

```
Intel(R) Core(TM) i7-8850H @ 2.60GHz, 6 cores   (2018 MacBook Pro)
RAM 16 GB   ·   Radeon Pro 560X, 4 GB VRAM (Metal 2)   ·   Intel UHD 630, 1.5 GB
Disk free 59 GB   ·   no CUDA   ·   ffmpeg present at /usr/local/bin/ffmpeg
torch / diffusers / mlx: NOT installed. MLX is Apple-Silicon-only, so unavailable here.
```

Consequence, from Wan 2.2's own model card: the A14B needs *"at least 80GB VRAM"*; the small
TI2V-5B does a 5-second 720p clip in *"under 9 minutes"* **on an RTX 4090**. Neither runs on 4 GB.

**Image generation on this box is `unverified`.** Quantised GGUF on CPU is the plausible path but no
seconds-per-image figure was measured for this chip — do not quote one until it is.

**The honest route for a one-off 61-image batch is not this machine.** Renting a GPU by the hour to
run weights you own is still the open-source route; it just is not the local one.

---

## 3. Style consistency across 61 cards

The measurement that matters, from StyleAligned's Table 2 (SDXL, DINO set-consistency — higher is
more consistent). Source: [arXiv 2312.02133](https://arxiv.org/abs/2312.02133).

| Method | Set consistency |
|---|---|
| Shared style prompt only ("same template, change the subject") | 0.245 |
| IP-Adapter | 0.44 |
| StyleAligned (Apache-2.0, training-free) | 0.51 |
| **Style LoRA** | **0.537** |

Two conclusions:

- **A fixed seed is not a style mechanism.** It correlates layout and colour statistics, not style
  ([WACV 2025, arXiv 2405.14828](https://arxiv.org/abs/2405.14828)).
- **The obvious plan is the worst-measuring one.** "Same prompt structure for every card, only
  change the subject" is the 0.245 row. StyleAligned's own paper says it directly: a shared style
  description *"results in an unaligned set, since each image is unaware of the exact appearance of
  other images in the set."*

Caveat: these are 2023-era SDXL numbers published by the method's own authors. Treat the ranking as
directional, not as a benchmark of today's models.

---

## 4. The conflict with SITE_SPEC_PROGRAM.md — founder decision

Three standing rules bear on this, and they were written before the question was asked:

| Rule | Text |
|---|---|
| `SITE_SPEC_PROGRAM.md:28-30` | *"Restraint + real data + zero latency. **No stock imagery, no decorative icons** — every visual is generated from real engine data (verdicts, source counts, kill ratios). Reject glassmorphism, neon gradients, 3D blobs, mascots, **AI-slop gradients**."* |
| `SITE_SPEC_PROGRAM.md:690` | *"No parallax, no scroll-jacking, **no decorative motion**."* |
| `SITE_SPEC_PROGRAM.md:1007` | *"**Remove the black media block until there is real imagery for it.**"* |

And the precedent, from the deletion itself (`Store.Web/src/pages/index.tsx:297`): the removed
cover's mark *"was a hash of the pack id, **which encodes nothing about the pack**"* — so
seed-derived generative art has already been tried here and rejected on that specific ground.

What replaced it (`index.tsx:293`): **"THE CARD'S VISUAL, AND IT IS A NUMBER."** The pack's strongest
financial figure at display size — *"it cannot be unearned, because it is a number the engine
computed about THIS pack"* (`:300-302`).

**Reading these together:** the objection was never "no picture". It was *a picture that encodes
nothing*. An illustration of a tipper truck for "Trades and site work" encodes the sector — which
the sector chip already states in text.

**This is the founder's call.** The spec is the founder's own document and can be amended. What
should not happen is imagery landing without that amendment, because §1007 conditions the media
block's return on "real imagery" and §28 defines what counts as real here.

### 4.1 The option that needs no amendment

Imagery **generated from engine data** is already explicitly permitted by §28, and the renderer
already exists: `next/og` + satori at `Store.Web/src/pages/og/pack/[id].tsx` composes SVG at build
time with no GPU — it runs fine on the 2018 Intel machine. Fields available on all 61 packs today:
`sourceCount`, `verifiedAt`, `financialSnapshot`, `sector`, `effortTag`, `market`, `payer`.

Candidates: a citation-density plot per pack (61 genuinely different shapes, each one true); a
gate-survival glyph (the filter is the product); a time-to-first-revenue axis rendered to scale.

### 4.2 BUILT 2026-08-15 — citation density on the share card

The founder chose the citation-density visual. What was actually missing turned out to be narrower
than §5 suggests, and in a different place:

- **The shelf card already draws it.** `EvidenceBar` renders one tick per cited source and is live
  at three sizes (`index.tsx:533`, `:674` at `size="lg"`, `:827`, and `DossierCard.tsx:99`). No new
  on-page work was needed, and none was done.
- **The share card did not.** `pages/og/pack/[id].tsx` — the 1200x630 PNG every social platform and
  AI citation card scrapes — stated the count as text only: `34 sources cited`, 24px, in the grey
  used for timestamps, below the brand name. At thumbnail size in a timeline, nothing at 24px
  survives. That was the gap, and it is the surface with the most reach.

What shipped (four files, no backend change — `sourceCount` was already on the DTO at
`lib/discovery.ts:50` and `lib/api/client.ts:118`, populated on 62 of 62 packs):

| File | Change |
|---|---|
| `lib/evidenceTicks.ts` | **new.** The run as geometry: tick count, the 5-step height cycle, the tail fade, the cap. One source of truth. |
| `components/ui/EvidenceBar.tsx` | consumes it. Pixel-identical output; the shape is no longer decided here. |
| `pages/og/pack/[id].tsx` | draws the run between title and footer; card tree extracted as `PackOgCard` so it renders without a server. |
| `__tests__/evidenceRunIsOneDrawing.test.tsx` | **new.** 10 tests, incl. two real satori rasterisations of the whole card. |

The geometry is shared rather than copied for a specific reason: the two surfaces have **no common
renderer** (DOM vs satori), which is exactly the condition under which one drawing silently becomes
two. `PackCardHeader`'s own note records that failure happening to a card header — "four hand-rolled
headers in three files, and that is the whole reason the shelf looked like two different shops".

No spec amendment was needed. §28 permits a visual "generated from real engine data (… source
counts …)", which is what a run of ticks counted off `sourceCount` is. No GPU, no licence, no model.

---

## 5. What building it would actually cost — there is no image slot

Verified on disk 2026-08-15. Adding per-pack imagery is **five layers**, not a generation task:

| Layer | Current state | Evidence |
|---|---|---|
| Entity | No image/thumbnail/cover/media field | `Store.Catalog/Domain/Pack.cs` |
| API | `GET /catalog` projection omits any image field | `Store.Api/Program.cs:280-324`, `:353-386` |
| Card component | Text-only; renders zero `<img>` | `Store.Web/src/components/discovery/PackRow.tsx` |
| Publish pipeline | Listing schema has 6 fields, none an image | `publish/publish.py:160-167`; `prospector/bridge.py:1945-1980` |
| Asset storage | R2 uploads `ContentType: "application/zip"` only — no media path | `prospector/bridge.py:2017-2088` |

Live catalogue confirms it end-to-end: all 61 packs, **zero image-like keys**
(`curl https://api.mumchimp.com/catalog`, 2026-08-15).

Static assets today are branding only: 7 files, ~156 KB — favicon, icons, one generic `og.png`.

---

## 6. Video — the verdict

**No, and twice over.** `SITE_SPEC_PROGRAM.md:690` forbids decorative motion outright; and the
hardware cannot produce it (§2). The licence is the *only* part that is clean (Wan 2.2, Apache-2.0).

If motion is ever wanted, `ffmpeg` is already installed and a Ken Burns pan over a still costs no
model, no GPU and no licence question. That was being measured when the research was stopped, so it
is **`unverified`** — no file sizes or encode times were captured.

---

## 7. Open items

- **Founder decision:** amend §28/§690/§1007, or build only §4.1 engine-data imagery, or leave the
  cards as they are. Nothing proceeds until this is settled.
- `unverified`: HunyuanVideo's territorial terms; seconds-per-image for quantised models on this
  Intel/AMD hardware; ffmpeg Ken Burns file sizes and encode times; the XLabs adapter mislabelling.
- If generation is approved, the batch runs on rented GPU, on **schnell or Qwen-Image**, and style
  consistency comes from a LoRA or StyleAligned — not from a shared prompt template (§3).
