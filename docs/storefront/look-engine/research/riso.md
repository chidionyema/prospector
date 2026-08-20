# Risograph inks — the real numbers

Data: `research/riso-inks.json`, 82 pages from `Category:Riso inks` on stencil.wiki, fetched
2026-08-20 through the MediaWiki API. 80 carry a hex; the two that do not are Clear Medium (a
transparent extender, so correctly has no colour) and a category page.

The agent doing this died twice on API errors, but it found the route before it went, and the
route is the whole trick. **Plain page URLs on stencil.wiki return 403. The API does not.**

    https://stencil.wiki/api.php?action=query&prop=revisions&rvprop=content&rvslots=main
        &format=json&titles=Fluorescent%20Pink|Blue|...          (40 titles per call, 2 calls)

Each page is an `{{Ink}}` template with `hex`, `rgb`, `cmyk`, `cielab`, `pantone`, `brand`,
`series` and a product list. The wiki throws intermittent `DBConnectionError`; retry.

## The finding that matters: hex and CIELAB disagree, with no systematic direction

75 inks carry both a hex and a measured CIELAB. They do not agree:

    median dE(declared Lab vs Lab-of-hex) = 6.96      max = 43.16
    hex more chromatic than the declared Lab: 37 inks | less chromatic: 38
    L* difference (hex minus declared): median -0.3, range -10.7 to +17.1

Worst cases, and they are the fluorescents, which is where a screen colour and a printed ink can
least agree:

    Fluorescent Yellow  dE 43.2   declared (97, -19, 51)   from hex (96.5, -24.8, 93.8)
    Fluorescent Green   dE 40.2   declared (85, -47, 33)   from hex (75.8, -67.3, 66.4)
    Cranberry           dE 27.1   declared (50,  48, 17)   from hex (39.3,  62.5, 37.2)

A JND is about 2.3 dE, so a median of 6.96 is three JNDs — visible, on most of the catalogue.
The even 37/38 split and the near-zero median lightness difference say these are two independently
entered fields, not one converted from the other. **Use the hex. It is what every riso tool and
every printer's swatch page uses, and it is the only one of the two that is self-consistent with
the rgb field (1 mismatch in 80).** Treat the CIELAB as `unverifiable` per ink.

## Chroma ceiling for the look engine

The most saturated inks in OKLCH C:

    Fluorescent Pink   0.236   #FF48B0        Fluorescent Yellow  0.213   #F7FF00
    Fluorescent Green  0.236   #44D62C        Scarlet             0.202   #F65058
    Fluorescent Red    0.214   #FF4C65        Cranberry           0.198   #BA0C24

So a riso look tops out around **C = 0.236** in sRGB. That is the ceiling to design the palette
against — well inside the 0.4 that OKLCH allows, and it is why a riso look reads as bright rather
than as neon: the hue is extreme, the chroma is not.

## The inks worth having in the engine

| ink | hex | rgb | Pantone |
|---|---|---|---|
| Fluorescent Pink     | #FF48B0 | 255,72,176    | 806 U      |
| Riso-Federal Blue    | #3D5588 | 61,85,136     | 281 U      |
| Bright Red           | #F15060 | 241,80,96     | 032 U      |
| Yellow               | #FFE800 | 255,232,0     | Yellow U   |
| Blue                 | #0078BF | 0,120,191     | 3005 U     |
| Green                | #00A95C | 0,169,92      | 354 U      |
| Orange               | #FF6C2F | 255,108,47    | Orange 021 U |
| Purple               | #765BA7 | 118,91,167    | 2685 U     |
| Teal                 | #00838A | 0,131,138     | 321 U      |
| Black                | #000000 | 0,0,0         | Black U    |
| Fluorescent Orange   | #FF7477 | 255,116,119   | 805 U      |
| Aqua                 | #5EC8E5 | 94,200,229    | 637 U      |
| Burgundy             | #914E72 | 145,78,114    | 235 U      |
| Mint                 | #82D8D5 | 130,216,213   | 3242 U     |
| Sunflower            | #FFB511 | 255,181,17    | 116 U      |
| Crimson              | #E45D50 | 228,93,80     | 485 U      |
| Turquoise            | #00AA93 | 0,170,147     | 3275 U     |
| Violet               | #9D7AD2 | 157,122,210   | 2097 U     |
| Scarlet              | #F65058 | 246,80,88     | 185 U      |
Full set of 80 in `research/riso-inks.json`, with cmyk, cielab and the product ids.

## Still open

Registration offset was not reached before the agent died — no sourced millimetre figure for
how far a riso print's colour layers drift between passes. Marked `unverifiable`. It is the one
remaining number for this look, and it governs how far apart to offset the layers on screen.
