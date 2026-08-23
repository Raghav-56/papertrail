#!/usr/bin/env python3
"""Render the latest PaperTrail digest markdown into /var/www/papertrail/index.html."""
import html
import re
import sys
from datetime import date
from pathlib import Path

VAULT = Path.home() / "raghav/Raghav-obsidian/Notes/Digests"
OUT = Path("/var/www/papertrail")

def parse(md: str):
    entries = []
    cur = None
    for line in md.splitlines():
        if line.startswith("## "):
            if cur:
                entries.append(cur)
            cur = {"title": line[3:].strip(), "meta": "", "abstract": "", "link": ""}
        elif cur is not None:
            if line.startswith("*") and line.endswith("*") and not cur["meta"]:
                cur["meta"] = line.strip("*")
            elif line.startswith("http"):
                cur["link"] = line.strip()
            elif line.strip() and not cur["link"]:
                cur["abstract"] += (" " if cur["abstract"] else "") + line.strip()
    if cur:
        entries.append(cur)
    return entries

def main() -> int:
    files = sorted(VAULT.glob("*-papertrail.md"))
    if not files:
        print("NO_DIGESTS", file=sys.stderr)
        return 1
    latest = files[-1]
    entries = parse(latest.read_text())
    cards = []
    for i, e in enumerate(entries, 1):
        link = f'<a class="lnk" href="{html.escape(e["link"])}">{html.escape(e["link"])}</a>' if e["link"] else ""
        cards.append(f"""
<article class="card">
  <div class="num">{i}</div>
  <div>
    <h2>{html.escape(e['title'])}</h2>
    <p class="meta">{html.escape(e['meta'])}</p>
    <p>{html.escape(e['abstract'])}</p>
    {link}
  </div>
</article>""")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PaperTrail — {html.escape(latest.stem[:10])}</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; margin: 0; }}
body {{ background:#0b0b0f; color:#d8d4e8; font:16px/1.6 Inter,system-ui,sans-serif; padding:2rem; max-width:56rem; margin-inline:auto; }}
header h1 {{ color:#a882ff; font-size:1.9rem; letter-spacing:.5px; }}
header p {{ color:#8a86a0; margin-top:.3rem; font-size:.9rem; }}
.card {{ display:flex; gap:1.1rem; background:#14121c; border:1px solid #241f33; border-left:3px solid #a882ff;
  border-radius:10px; padding:1.2rem 1.3rem; margin-top:1.1rem; }}
.num {{ color:#a882ff; font-weight:700; font-size:1.05rem; min-width:1.6rem; }}
h2 {{ font-size:1.06rem; color:#efeafd; line-height:1.4; }}
.meta {{ color:#7d7895; font-size:.82rem; margin:.25rem 0 .5rem; }}
.lnk {{ display:inline-block; margin-top:.45rem; color:#8f76d9; font-size:.83rem; text-decoration:none; word-break:break-all; }}
.lnk:hover {{ color:#c3aeff; }}
footer {{ margin-top:2rem; color:#5c5875; font-size:.8rem; text-align:center; }}
</style></head><body>
<header><h1>PaperTrail</h1><p>scored research digest · {html.escape(str(date.today()))} · auto-generated daily at 02:00 UTC</p></header>
{''.join(cards)}
<footer>papertrail · built by an agent on an oracle VPS · <a style="color:#8f76d9" href="https://github.com/Raghav-56/papertrail">source</a></footer>
</body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(page)
    print(f"WROTE {OUT/'index.html'} ({len(entries)} papers)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
