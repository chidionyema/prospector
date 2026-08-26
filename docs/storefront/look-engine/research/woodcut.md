# Woodcut / linocut — the numbers the renderer needs

Full brief: task output `ae9a996816f5e983b.output` (raw transcript, 1MB).
Primary sources that were actually read in full:
- Okada, Mizuno & Toriwaki, *Virtual Sculpting and Virtual Woodblock Printing by Model-Driven
  Scheme*, J. Soc. Art and Science 1(2):74-84 (2002). Diamond OA.
  https://www.jstage.jst.go.jp/article/artsci/1/2/1_2_74/_pdf
- Mesquita & Walter, *Reaction-diffusion Woodcuts*, GRAPP 2019, 89-99.
  https://www.scitepress.org/Papers/2019/73859/73859.pdf
- Winkenbach & Salesin, *Rendering Parametric Surfaces in Pen and Ink*, SIGGRAPH 1996.

The three Mizuno papers named in the brief (1998 Visual Computer, 1999 CGF, 2000 CGF) are all
paywalled. The 2002 paper is by the same three authors and restates their models with equations,
citing those three as [17], [19], [23]. That is the substitute, and it is a good one.

## Sourced equations

Ink transfer under pressure (Eq. 4). `l` is paper-to-block distance, `lt` a threshold, `w` moisture:

    coverage(l, w) = w^2 * (1 - (l/lt)^2) / (1 + (l/lt)^2),  0 <= l <= lt

Nearly flat at contact, falling steeply near `lt`. That abrupt shoulder is the hard-edged look of
relief printing. The sign in the PDF is unrecoverable (embedded font); use the magnitude form.

Ink layering (Eq. 5) — plain source-over starting from paper, not from transparent:

    f_i = rho_i * C_i + (1 - rho_i) * f_(i-1),   f_0 = paper colour

For one black block: `f = rho*ink + (1-rho)*paper`. Use rho = 0.90. Ink is never `#000`.

Spacing from tone (Winkenbach & Salesin s4, verbatim): `d = t / T`. Linearise first — coverage is
an area ratio, so it is linear light. `coverage = 1 - srgbToLinear(target)`. Keep `d` fractional.

Orientation (Mesquita & Walter s3.1, 5x5 window, Sobel):

    Vx = sum 2*Gx*Gy ;  Vy = sum (Gx^2 - Gy^2)
    theta = PI/2 + 0.5*atan2(Vx, Vy)

## Black-line vs white-line

The marks swap meaning, and so does the arithmetic:

| | black-line | white-line |
|---|---|---|
| a mark is | the standing ridge, inked | the gouge cut, paper |
| coverage | `t/d` | `1 - w/d` |
| spacing for darkness D | `d = t/D` | `d = w/(1-D)` |
| what fails | nothing much | thin black ridges drop out |

Inverting the bitmap (which is what the published renderer does) also inverts the tone mapping and
does not protect the ridges. Clamp `d >= w + alpha` or the light areas collapse to solid white.

## The alpha-hull, which is the one thing nobody implements

Mizuno Fig. 6: the paper is a sheet that cannot bend tighter than radius alpha, so it bridges
narrow cuts instead of descending into them. A gouge narrower than ~2*alpha never reaches the
floor and prints grey or fills in solid. This is the physical reason thin whites close up and why
white-line woodcuts are dark pictures. Implement as a morphological close on ink coverage, whole
pixels, alpha = 1px at DPR 1.

## Scale, and why it decides everything

Mizuno's own numbers (p.80): an oban ukiyo-e is 26.3 x 39.3 cm; their experiment was 512 px
across, "about 50 dpi"; their stated target for print fidelity is 600 dpi.

Our 320 CSS px across an A5 sheet is 54.9 dpi — 9.2% of that target. We sit exactly where their
512-px experiment sat. Sub-millimetre carving detail is not representable, so set every constant
in pixels and back-check against mm, never the other way round.

## Constants (DPR 1; double for DPR 2)

gouge width t = 2px (0.93mm at A5, a real gouge size) | taper exponent p = 1.0, range 0.5-2.0 |
entry taper = min(3t, 0.35L) | exit taper = 0.6 x entry | stroke length log-uniform [8t, 60] |
spacing d = t/coverage, fractional, clamped [t, 16] | flat black below region mean 25, flat white
above 210 (sourced) | border dilate 1px | **ink squash 0.5px, sub-pixel** | alpha-hull close 1px |
min region area 500px^2 (sourced) | orientation window 5x5 (sourced) | per-pixel orientation only
where S > 0.010 (sourced) | rho = 0.90 | 3x3 median (sourced) | edge-grey kernel
[1,2,1;2,10,2;1,2,1]/22 (sourced) | jitter: spacing +/-8%, angle +/-2deg, width +/-10%.

## The taper exponent, derived

No published woodcut stroke profile exists — this is derived from Eq.(1) plus tool geometry.
Width follows depth: V-tool `w ∝ d`, U-gouge `w ∝ sqrt(d)`. Depth follows entry: straight plunge
`d ∝ s`, rocking entry `d ∝ s^2`. Compose, and p = 1.0 falls out of BOTH common combinations
(V-tool plunged, U-gouge rocked). Taper length works out at ~3x stroke width and is weakly
sensitive to the wrist-pivot assumption (s ∝ sqrt(rho): 25-100mm moves it only 2.1 to 4.2).

## Why renders read as a threshold filter

Sourced: Mesquita & Walter tested Photoshop's "Wood Carving" and a GIMP pipeline and reported
neither resembled a real carving. The specific faults, each with its fix:

constant-width strokes (taper them, fill a polygon, never stroke a path) | grey anywhere but at a
mark edge (binarise, then re-add grey ONLY at edges with the 22-kernel) | no solid blacks and no
bare paper (the 25/210 cutoffs) | wallpaper hatching that ignores form (the orientation field) |
uniform detail everywhere (per-region stroke size) | speckle (3x3 median + merge regions under
500px^2) | hairline outlines (dilate borders; woodcut outlines are thick) | strokes running across
region boundaries (clip to the region) | **whole-pixel ink squash** (2-5x too thick at our
resolution) | perfect parallelism (jitter) | ink at #000 on paper at #fff (Eq. 5).

Strokes start at the BRIGHT end of a region and run toward the centroid — sourced, from Mello et
al.'s observation that carving initiates in the brighter parts. Nothing in ETF or pen-and-ink says
this. It makes hatching directed, not merely aligned.

## Marked unverifiable

No published stroke taper function for woodcut. No published mm figure for relief-print ink squash
(the only spread literature is offset dot gain, a different process; Wikipedia's "Causes" section
on it carries an uncited-section banner from 2010). The sign of Mizuno Eq. 4. Mello 2007 and the
three paywalled Mizuno papers were read only through Mesquita & Walter and the 2002 overview.
Wrist pivot 50mm, exit/entry 0.6, rho 0.90, stroke length bounds, all jitter values, alpha = 1px.

## Environment note for the next agent

Google and Bing return HTTP 200 with no usable results (Google serves a redirect stub, Bing strips
every external href). DuckDuckGo unreachable. What works: api.crossref.org, api.openalex.org,
api.jstage.jst.go.jp/searchapi/do, web.archive.org/cdx/search/cdx, api.semanticscholar.org
(429 on the second call), www.scitepress.org, en.wikipedia.org/wiki/Special:Export/<Page>.
MoMA is behind a JS challenge; Tate is plain HTML.
