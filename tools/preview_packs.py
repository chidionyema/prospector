"""Read any pack in full, without buying it.

Everything a buyer receives is a zip behind a Stripe entitlement: `GET /download/{token}`
(store_platform/.../DeliveryEndpoints.cs) presigns an R2 URL for five minutes and only after
an Active entitlement exists. There is no operator route past that — verified 2026-08-14 —
so the only way anyone here could read a pack was to buy it, which meant nobody read them.

This is that route, at the operator's own grain: it takes the SAME bytes the buyer's
presigned URL resolves to (R2, keyed by the catalogue's own contentKey) and renders every
pack's `index.html` into one browsable page. It reads; it never writes to the catalogue, the
bucket or the ledger.

Two sources, and the difference matters:

    --from r2      (default) the object the buyer's download actually resolves to. This is
                   the only source that can prove the shipped bytes, because publishing can
                   succeed locally and fail to upload.
    --from disk    publish/bundles/<id>/*.zip on this machine. No credentials needed, but it
                   is what was BUILT, not necessarily what is SERVED.

    set -a; . .env; set +a          # R2_* and STORE_INTERNAL_API_KEY, never echoed
    python tools/preview_packs.py --open
    python tools/preview_packs.py --from disk --open        # no credentials
    python tools/preview_packs.py --id 8d5e24fbe6c1f5d3     # one pack

That distinction is not academic. On 2026-08-14 `publish/bundles/` reported seven packs on
sale with four missing documents each, carrying the generator's "not generated" notice. Read
from R2, all seven are complete — 1,559 to 3,056 words per document. The local zips were
first attempts that were regenerated and re-uploaded, and never refreshed on this disk. A
disk-only reading of the estate would have had someone rewriting seven packs that were fine.

A pack is reported INCOMPLETE when any of the four core documents is under `--thin` words.
That is a floor, not a quality judgement: the generator writes a "not generated" notice
rather than inventing prose when the operator returns nothing, and this catches that.
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sys
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

DEFAULT_API_URL = os.environ.get("STORE_API_URL") or f"https://api.{os.environ['ESTATE_ZONE']}"
CACHE = Path(os.environ.get("PROSPECTOR_PREVIEW_CACHE", ".cache/pack_preview"))

#: The four documents that carry the work. The executive summary, the checklist and the QA
#: report are assembled deterministically from the dossier, so they are present even when the
#: prose operator returns nothing — which is exactly why they cannot be the completeness test.
CORE = ["01_Blueprint_BuildSpec.md", "02_Marketing_Plan_GTM.md",
        "03_Operations_Plan.md", "04_Financial_Model.md"]

READER = "index.html"


def fetch_catalogue(api_url: str) -> list[dict]:
    with urllib.request.urlopen(f"{api_url}/catalog", timeout=60) as r:
        body = json.load(r)
    return body if isinstance(body, list) else body.get("items") or body.get("packs") or []


def _s3():
    """The bucket, from env only. A missing credential is a refusal, never a silent fallback
    to disk: 'what is served' and 'what was built' are different questions and answering the
    wrong one quietly is how a broken pack stays on sale."""
    import boto3  # imported here so --from disk needs no dependency

    account = os.environ.get("R2_ACCOUNT_ID")
    bucket = os.environ.get("R2_BUCKET")
    missing = [n for n in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                           "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
               if not os.environ.get(n)]
    if missing:
        sys.exit(f"missing credentials: {', '.join(missing)}. "
                 "Run `set -a; . .env; set +a` first, or pass --from disk.")
    return boto3.client("s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                        region_name="auto"), bucket


def _content_key(api_url: str, pid: str, internal_key: str, s3, bucket: str) -> str | None:
    """The catalogue's pointer first, the prefix only as a fallback. Keys are content
    addressed, so a prefix with two objects is genuinely ambiguous and is skipped rather than
    guessed — guessing would show a pack that is not the one on sale."""
    if internal_key:
        try:
            req = urllib.request.Request(
                f"{api_url}/internal/catalog/{pid}/content",
                headers={"X-Internal-Key": internal_key})
            with urllib.request.urlopen(req, timeout=20) as r:
                key = json.load(r).get("contentKey")
            if key:
                return key
        except Exception:
            pass
    objects = s3.list_objects_v2(Bucket=bucket, Prefix=f"packs/{pid}/").get("Contents", [])
    return objects[0]["Key"] if len(objects) == 1 else None


def zip_for(pid: str, source: str, ctx: dict) -> tuple[zipfile.ZipFile | None, str]:
    if source == "disk":
        hits = sorted(glob.glob(f"publish/bundles/{pid}/*.zip"))
        if not hits:
            return None, "no bundle on this disk"
        return zipfile.ZipFile(hits[0]), Path(hits[0]).name
    key = _content_key(ctx["api_url"], pid, ctx["internal_key"], ctx["s3"], ctx["bucket"])
    if not key:
        return None, "no unambiguous object in the bucket"
    cached = CACHE / f"{pid}.zip"
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        blob = ctx["s3"].get_object(Bucket=ctx["bucket"], Key=key)["Body"].read()
        cached.write_bytes(blob)
    return zipfile.ZipFile(io.BytesIO(cached.read_bytes())), key


def collect(rows: list[dict], source: str, ctx: dict, thin: int) -> list[dict]:
    packs = []
    for row in rows:
        pid = row["id"]
        zf, where = zip_for(pid, source, ctx)
        if zf is None:
            print(f"  skip {pid}: {where}", file=sys.stderr)
            continue
        names = set(zf.namelist())
        words = {f: len(zf.read(f).decode("utf8", "replace").split())
                 for f in names if f.endswith(".md")}
        doc = zf.read(READER).decode("utf8", "replace") if READER in names else ""
        packs.append({
            "id": pid,
            "title": row.get("title") or pid,
            "price": row.get("price") or "",
            "market": (row.get("market") or "").upper(),
            "sector": row.get("sector") or "",
            "words": sum(words.values()),
            "broken": [f for f in CORE if words.get(f, 0) < thin],
            "where": where,
            "kb": len(doc.encode()) // 1024,
            "doc": doc.replace("</script", r"<\/script"),
        })
    return packs


# --------------------------------------------------------------------------------------
# The page. The pack's own index.html goes in a frame verbatim: its stylesheet is part of
# what was sold, so re-rendering the markdown here would review a document nobody receives.
# --------------------------------------------------------------------------------------
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Every pack, without paying for one</title>
<style>
:root{--ground:#f7f6f3;--raise:#fff;--sunk:#eeece7;--line:#ded9d0;--ink:#1b1a17;
 --ink-2:#57534a;--ink-3:#8a857a;--accent:#1f5f5b;--accent-soft:#dfeceb;--bad:#a3341f;
 --bad-soft:#f6e2dd;--mono:ui-monospace,SFMono-Regular,Menlo,monospace;
 --ui:system-ui,-apple-system,"Segoe UI",sans-serif;--doc:Georgia,"Iowan Old Style",serif}
@media (prefers-color-scheme:dark){:root{--ground:#14140f;--raise:#1c1c17;--sunk:#100f0b;
 --line:#2f2e27;--ink:#eceadf;--ink-2:#a9a498;--ink-3:#767165;--accent:#6fc0b6;
 --accent-soft:#16302e;--bad:#e08a72;--bad-soft:#331d17}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--ui);font-size:15px;
 display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
header{padding:15px 22px;border-bottom:1px solid var(--line);background:var(--raise);flex:0 0 auto}
h1{font-family:var(--doc);font-size:19px;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
header p{margin:0;color:var(--ink-2);font-size:13px;max-width:74ch}
code{font-family:var(--mono);font-size:.86em;background:var(--sunk);padding:1px 5px;border-radius:3px}
main{flex:1 1 auto;display:grid;grid-template-columns:312px minmax(0,1fr);min-height:0}
@media(max-width:820px){main{grid-template-columns:1fr;grid-template-rows:210px 1fr}}
aside{border-right:1px solid var(--line);background:var(--sunk);overflow-y:auto;min-height:0}
.ah{position:sticky;top:0;background:var(--sunk);padding:11px 14px 8px;
 border-bottom:1px solid var(--line);z-index:2}
input[type=search]{width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:6px;
 background:var(--raise);color:var(--ink);font:inherit;font-size:13px}
input[type=search]:focus{outline:2px solid var(--accent);outline-offset:1px}
ul{list-style:none;margin:0;padding:0 0 26px}li{border-bottom:1px solid var(--line)}
button.pick{display:block;width:100%;text-align:left;background:none;border:0;cursor:pointer;
 padding:10px 14px;color:inherit;font:inherit;border-left:3px solid transparent}
button.pick:hover{background:var(--raise)}
button.pick:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
button.pick[aria-current=true]{background:var(--raise);border-left-color:var(--accent)}
.t{font-size:13px;line-height:1.35;margin-bottom:3px}
.m{font-size:11px;color:var(--ink-3);display:flex;gap:7px;font-variant-numeric:tabular-nums}
.chip{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;
 padding:1px 5px;border-radius:3px;background:var(--accent-soft);color:var(--accent)}
.chip.bad{background:var(--bad-soft);color:var(--bad)}
.stage{display:flex;flex-direction:column;min-width:0;min-height:0}
.bar{padding:9px 16px;border-bottom:1px solid var(--line);display:flex;gap:14px;
 align-items:center;flex-wrap:wrap;background:var(--raise);flex:0 0 auto}
.bar .ti{font-weight:600;font-size:13.5px}
.bar .fn{font-family:var(--mono);font-size:11.5px;color:var(--ink-3);background:none;padding:0}
.warn{background:var(--bad-soft);color:var(--bad);border:1px solid var(--bad);
 padding:7px 12px;font-size:12.5px;margin:0}
iframe{flex:1 1 auto;width:100%;border:0;background:#fff;min-height:0}
</style></head><body>
<header><h1>Every pack, without paying for one</h1>
<p>__SOURCELINE__ Each frame below is that bundle's <code>index.html</code>, byte for byte —
the file a buyer opens after unzipping. __N__ on sale, __B__ of them opening on a notice where
a document should be.</p></header>
<main>
 <aside><div class="ah"><input type="search" id="q" placeholder="Filter __N__ packs&hellip;"
   aria-label="Filter packs"></div><ul id="list"></ul></aside>
 <div class="stage"><div class="bar" id="bar"></div><p class="warn" id="warn" hidden></p>
   <iframe id="view" title="Pack contents as the buyer sees them"></iframe></div>
</main>
<script id="meta" type="application/json">__META__</script>
__BLOBS__
<script>
const P=JSON.parse(document.getElementById('meta').textContent);
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
let cur=0;const listEl=document.getElementById('list');
function drawList(f){const q=(f||'').toLowerCase();listEl.innerHTML='';
 P.forEach((p,i)=>{
  if(q&&!(p.title+' '+p.sector+' '+p.id).toLowerCase().includes(q))return;
  const li=document.createElement('li'),b=document.createElement('button');
  b.className='pick';b.setAttribute('aria-current',i===cur);
  b.innerHTML='<div class="t">'+esc(p.title)+'</div><div class="m">'+
   (p.broken.length?'<span class="chip bad">'+p.broken.length+' missing</span>'
                   :'<span class="chip">complete</span>')+
   '<span>'+esc(p.price)+'</span><span>'+p.words.toLocaleString()+' words</span></div>';
  b.onclick=()=>{cur=i;show();drawList(document.getElementById('q').value)};
  li.appendChild(b);listEl.appendChild(li);});}
function show(){const p=P[cur];
 document.getElementById('bar').innerHTML='<span class="ti">'+esc(p.title)+'</span>'+
  '<span class="fn">'+esc(p.where)+' &rsaquo; index.html &middot; '+p.kb+' KB</span>'+
  '<span class="fn">'+esc(p.price)+(p.market?' &middot; '+esc(p.market):'')+'</span>';
 const w=document.getElementById('warn');
 if(p.broken.length){w.hidden=false;w.textContent='On sale at '+p.price+'. '+p.broken.length+
   ' of the four core documents were never generated — scroll to them and read what the '+
   'buyer gets instead.';}else w.hidden=true;
 document.getElementById('view').srcdoc=document.getElementById('d'+cur).textContent;}
document.getElementById('q').addEventListener('input',e=>drawList(e.target.value));
drawList('');show();
</script></body></html>
"""


def build_page(packs: list[dict], source: str) -> str:
    meta = json.dumps([{k: v for k, v in p.items() if k != "doc"} for p in packs],
                      ensure_ascii=False, separators=(",", ":"))
    blobs = "\n".join(f'<script type="text/plain" id="d{i}">{p["doc"]}</script>'
                      for i, p in enumerate(packs))
    line = ("Pulled from R2 by the catalogue&rsquo;s own <code>contentKey</code> — the same "
            "object a paid download resolves to."
            if source == "r2" else
            "Read from <code>publish/bundles/</code> on this machine: what was BUILT, which "
            "is not proof of what is served.")
    return (PAGE.replace("__META__", meta).replace("__BLOBS__", blobs)
            .replace("__SOURCELINE__", line)
            .replace("__N__", str(len(packs)))
            .replace("__B__", str(sum(1 for p in packs if p["broken"]))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", choices=["r2", "disk"], default="r2",
                    help="r2 (default) reads what is actually served; disk reads what this "
                         "machine built")
    ap.add_argument("--id", action="append", default=[],
                    help="only this pack id (repeatable)")
    ap.add_argument("--api-url", default=DEFAULT_API_URL)
    ap.add_argument("--out", default="publish/preview/packs.html")
    ap.add_argument("--thin", type=int, default=300,
                    help="words below which a core document is a stub, not a document")
    ap.add_argument("--open", action="store_true", help="open the page when it is written")
    args = ap.parse_args()

    rows = fetch_catalogue(args.api_url)
    if args.id:
        wanted = set(args.id)
        rows = [r for r in rows if r["id"] in wanted]
        if not rows:
            return print("no listed pack matches that id", file=sys.stderr) or 2

    ctx = {"api_url": args.api_url,
           "internal_key": os.environ.get("STORE_INTERNAL_API_KEY", "")}
    if args.source == "r2":
        ctx["s3"], ctx["bucket"] = _s3()

    print(f"reading {len(rows)} listed packs from {args.source}…", file=sys.stderr)
    packs = collect(rows, args.source, ctx, args.thin)
    if not packs:
        return print("nothing to show", file=sys.stderr) or 1
    packs.sort(key=lambda p: (not p["broken"], -p["words"]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(packs, args.source))

    broken = [p for p in packs if p["broken"]]
    print(f"\n{len(packs)} packs, {out} ({out.stat().st_size / 1048576:.1f} MB)")
    if broken:
        print(f"\nINCOMPLETE AND ON SALE — {len(broken)}:")
        for p in broken:
            names = ", ".join(f.split("_", 1)[1][:-3] for f in p["broken"])
            print(f"  {p['id']}  {p['price']:>8}  {p['title'][:44]:44}  {names}")
    else:
        print("\nevery listed pack carries all four core documents")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
