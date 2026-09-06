#!/usr/bin/env python3
"""One picture per pack, drawn from the pack's own title and description, on MiniMax.

WHY PER PACK AND NOT ONLY PER SECTOR. `Store.Web/src/lib/sectorImage.ts` draws one picture per
sector code and every pack in that sector reuses it, which is what the founder asked for first:
"we can run once through a few hundred categories and then reuse for future packs". That still
holds and is still the fallback. This tool is the layer above it, on his instruction of
2026-08-30: "nininax is good enough to use and can even generate per title and desc".

WHAT IT COSTS, because that decides whether the layer is allowed to exist at all. MiniMax lists
`image-01` at $0.0035 an image (https://platform.minimax.io/docs/guides/pricing-paygo, read
2026-08-30). The whole catalogue at that rate is well under a pound and each new pack is a third
of a penny. `--dry-run` prints the bill before anything is spent.

IT NEVER PAYS TWICE. A pack whose file is already on disk is skipped, so re-running after a
failure costs only the packs that failed. Deleting a file is how you ask for one to be redrawn.

WHERE THE FILES GO. `Store.Web/public/pack/<id>.jpg`, committed to the repository, and the tool
regenerates `src/lib/packImages.generated.ts` listing the ids it holds. The storefront reads that
list at build time, so `packImage()` stays a pure function with no filesystem behind it and a pack
published after the last build falls back to its sector picture rather than to a hole.

THE PICTURES CARRY NO WORDS. They are decoration beside copy that already says everything, so
every render site marks them `alt=""` and `aria-hidden`, and the prompt forbids text outright.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

USD_PER_IMAGE = 0.0035

# MiniMax answers HTTP 200 with `base_resp.status_code` 1002 when the account is over its
# requests-per-minute allowance. Measured 2026-08-30 on a 77-pack run at 4 workers: 34 drawn, 43
# refused, every one of the 43 for this reason and no other. It is a queueing signal, not a
# failure, so it is waited out rather than reported. Nothing is charged for a refused request.
RATE_LIMITED = 1002
BACKOFF_S = (5, 15, 30, 60, 60, 60)

MINIMAX_URL = "https://api.minimax.io/v1/image_generation"
# Absolute, never found on PATH: the downscaler is macOS's own tool and nothing else may stand in
# for it. `sips` is the only image binary this machine has -- there is no PIL and no ImageMagick.
SIPS = "/usr/bin/sips"


def _open(url: str, timeout: int):
    """`urlopen`, refusing any scheme but http and https.

    Both URLs this tool opens arrive from outside the file: the catalogue endpoint from a flag or
    an environment variable, the image location from MiniMax's own answer. Without this check a
    `file:` URL would read the local disk into a pack picture.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"refusing a url that is not http or https: {url[:40]}")
    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 - scheme checked above


# The shop's own tokens, read off the served stylesheet on 2026-08-30, and the same house style
# the sector pictures were drawn in so the two layers sit on one shelf without a seam.
PALETTE = (
    "warm off-white paper #fafaf7, deep teal #14706a, ink #17191c, "
    "one muted terracotta only where it helps; no other colours"
)
STYLE = (
    "Flat vector editorial illustration for a research publisher's website, in the style of a "
    "printed report's section opener. Generous negative space, quiet and precise, geometric, "
    f"drawn with a single consistent line weight. Palette: {PALETTE}. "
    "No text, no letters, no numbers, no logos, no faces, no photographic realism, "
    "no gradients, no drop shadows, no 3D."
)


def prompt_for(title: str, one_line: str) -> str:
    """The still life a reader would recognise as this trade, and nothing else.

    Objects, not people and not symbols of money: a person dates the picture and a coin or a
    graph turns a research listing into a stock photograph of finance.
    """
    return (
        f"{STYLE} Subject: a still life of the physical objects and setting of this trade, "
        "arranged on a plain surface, no people. "
        f"The trade: {title}. What the work is: {one_line}"
    )


def fetch_catalogue(url: str) -> list[dict]:
    with _open(url, 120) as r:
        body = json.load(r)
    return body if isinstance(body, list) else body.get("items", [])


def generate(pack: dict, out_dir: pathlib.Path, key: str, width: int, quality: int) -> str:
    pack_id = pack["id"]
    path = out_dir / f"{pack_id}.jpg"
    body = json.dumps(
        {
            "model": "image-01",
            "prompt": prompt_for(pack.get("title", ""), pack.get("oneLine", "")),
            "aspect_ratio": "16:9",
            "n": 1,
            "response_format": "url",
        }
    ).encode()
    for wait in (*BACKOFF_S, None):
        req = urllib.request.Request(  # noqa: S310 - MINIMAX_URL is an https literal above
            MINIMAX_URL,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 - literal url above
            answer = json.load(r)
        status = answer.get("base_resp", {}).get("status_code")
        if status == 0:
            break
        if status != RATE_LIMITED or wait is None:
            return f"FAIL {pack_id}: {answer.get('base_resp')}"
        time.sleep(wait)
    with _open(answer["data"]["image_urls"][0], 180) as r:
        raw = r.read()
    # A dotfile, and deliberately not `*.jpg`: `write_manifest` globs this directory, and a
    # half-written full-size frame left behind by a crash would otherwise enter the manifest as a
    # pack id that has no picture.
    full = out_dir / f".{pack_id}.full.tmp"
    full.write_bytes(raw)
    subprocess.run(  # noqa: S603 - every argument is built here, none comes from input
        [
            SIPS,
            "-s",
            "format",
            "jpeg",
            "-s",
            "formatOptions",
            str(quality),
            "-Z",
            str(width),
            str(full),
            "--out",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    full.unlink()
    return f"ok   {pack_id}  {path.stat().st_size} bytes"


def write_manifest(out_dir: pathlib.Path, manifest: pathlib.Path) -> int:
    ids = sorted(p.stem for p in out_dir.glob("*.jpg") if "." not in p.stem)
    lines = [
        "// GENERATED by tools/gen_pack_images.py. Do not edit by hand.",
        "//",
        "// The ids of the packs that have their own picture in `public/pack/`. It is a build-time",
        "// list rather than a filesystem check so `packImage()` stays a pure function: a pack",
        "// published after the last build is simply not in here and falls back to its sector",
        "// picture, which is a real drawing rather than a hole in the shelf.",
        "export const PACK_IMAGE_IDS: ReadonlySet<string> = new Set([",
        *[f"  '{i}'," for i in ids],
        "]);",
        "",
    ]
    manifest.write_text("\n".join(lines))
    return len(ids)


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent.parent
    web = here / "store_platform" / "src" / "Store.Web"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--catalog-url",
        default=os.environ.get("PACK_CATALOG_URL"),
        help="catalogue endpoint; also read from PACK_CATALOG_URL",
    )
    ap.add_argument("--out", type=pathlib.Path, default=web / "public" / "pack")
    ap.add_argument(
        "--manifest", type=pathlib.Path, default=web / "src" / "lib" / "packImages.generated.ts"
    )
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--quality", type=int, default=72)
    # Two, not four: four spent 43 of 77 requests on a rate-limit refusal (2026-08-30). The retry
    # above makes those survivable, but a request that has to be waited out is slower than one that
    # was never sent.
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0, help="draw at most this many, 0 for all")
    ap.add_argument("--dry-run", action="store_true", help="print the bill and change nothing")
    ap.add_argument(
        "--manifest-only",
        action="store_true",
        help="rewrite the manifest from what is already on disk",
    )
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if args.manifest_only:
        print(f"manifest lists {write_manifest(args.out, args.manifest)} packs")
        return 0

    if not args.catalog_url:
        print("no catalogue url: pass --catalog-url or set PACK_CATALOG_URL", file=sys.stderr)
        return 2

    packs = fetch_catalogue(args.catalog_url)
    todo = [p for p in packs if not (args.out / f"{p['id']}.jpg").exists()]
    if args.limit:
        todo = todo[: args.limit]
    print(
        f"catalogue {len(packs)} packs, {len(packs) - len(todo)} already drawn, {len(todo)} to draw"
    )
    print(f"bill: {len(todo)} x ${USD_PER_IMAGE:.4f} = ${len(todo) * USD_PER_IMAGE:.2f}")
    if args.dry_run:
        return 0
    if not todo:
        print(f"manifest lists {write_manifest(args.out, args.manifest)} packs")
        return 0

    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        print("MINIMAX_API_KEY is not set in this shell", file=sys.stderr)
        return 2

    failures = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(generate, p, args.out, key, args.width, args.quality): p for p in todo
        }
        for f in cf.as_completed(futures):
            try:
                line = f.result()
            except Exception as exc:  # one pack failing must not abandon the other 76
                line = f"FAIL {futures[f]['id']}: {exc}"
            failures += line.startswith("FAIL")
            print(line, flush=True)

    print(f"manifest lists {write_manifest(args.out, args.manifest)} packs")
    print(f"{failures} failed; re-run to draw only those")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
