#!/usr/bin/env python3
"""Render PaperTrail digests into /var/www/papertrail/ — dated editions + index.html (latest).

Shares the news-digest theme system (data-theme attribute + CSS custom properties,
persisted in localStorage) so both sites feel like one suite while staying separate repos.
"""
import html
import sys
from datetime import date
from pathlib import Path

VAULT = Path.home() / "raghav/Raghav-obsidian/Notes/Digests"
OUT = Path("/var/www/papertrail")

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
::selection{background:var(--accent);color:#fff}
/* Dark default (renamed from AMOLED to match news.raghav56.tech) — same tokens */
:root{
  --bg:#000000; --bg2:#0a0a0a; --card:#0d0d0d; --fg:#e6e6e6; --mut:#888888;
  --accent:#8b5cf6; --accent2:#6366f1; --border:#191919;
  --shadow:0 4px 20px rgba(0,0,0,.7); color-scheme:dark;
}
[data-theme=dark]{
  --bg:#000000; --bg2:#0a0a0a; --card:#0d0d0d; --fg:#e6e6e6; --mut:#888888;
  --accent:#8b5cf6; --accent2:#6366f1; --border:#191919;
  --shadow:0 4px 20px rgba(0,0,0,.7);
}
[data-theme=paper]{
  --bg:#fffcf0; --bg2:#f2ede4; --card:#faf6ec; --fg:#100f0c; --mut:#6f6e69;
  --accent:#205ea6; --accent2:#da702c; --border:#e2ddcf;
  --shadow:0 4px 16px rgba(80,60,20,.12); color-scheme:light;
}
[data-theme=light]{
  --bg:#ffffff; --bg2:#f4f2fa; --card:#fbfaff; --fg:#1e1e26; --mut:#767684;
  --accent:#7852ee; --accent2:#9f6fff; --border:#e6e3ef;
  --shadow:0 3px 14px rgba(90,70,180,.09); color-scheme:light;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font:15.5px/1.65 'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;
     max-width:720px;margin:0 auto;padding:1.6rem 1.25rem 4rem;transition:background .3s,color .3s}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(600px 300px at 85% -50px, color-mix(in srgb, var(--accent) 13%, transparent), transparent),
    radial-gradient(500px 260px at 0% 30%, color-mix(in srgb, var(--accent2) 8%, transparent), transparent)}
.topbar{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:1rem;
  flex-wrap:wrap;padding:.55rem .2rem;margin:-.6rem -1rem 1rem;border-radius:.9rem;
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  background:color-mix(in srgb, var(--bg) 72%, transparent);
  border-bottom:1px solid var(--border);position:sticky;top:0;z-index:10}
.brand{display:flex;align-items:center;gap:.55rem;font-weight:800;font-size:1.28rem;letter-spacing:-.02em;color:var(--fg);text-decoration:none}
.brand svg{width:22px;height:22px;stroke:var(--accent)}
.brand em{font-style:normal;background:linear-gradient(120deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.themes{display:flex;gap:.3rem;background:var(--bg2);padding:.28rem;border-radius:.8rem;border:1px solid var(--border)}
.themes button{background:transparent;color:var(--mut);border:none;border-radius:.55rem;
  padding:.32rem .7rem;font-size:.78rem;font-weight:500;cursor:pointer;transition:.18s;font-family:inherit}
.themes button:hover{color:var(--fg)}
.themes button.active{background:var(--accent);color:#fff;box-shadow:0 2px 8px color-mix(in srgb,var(--accent) 45%,transparent)}
.meta{color:var(--mut);font-size:.86rem;display:flex;gap:.9rem;align-items:center;flex-wrap:wrap;margin-bottom:1.1rem;position:relative;z-index:1}
.meta a{color:var(--mut);text-decoration:none;display:inline-flex;align-items:center;gap:.3rem;
  padding:.28rem .65rem;border-radius:.55rem;background:var(--bg2);border:1px solid var(--border);transition:.15s}
.meta a:hover{color:var(--accent);border-color:var(--accent)}
.card{position:relative;z-index:1;display:flex;gap:1.1rem;background:var(--card);border:1px solid var(--border);
  border-radius:.75rem;padding:1rem 1.15rem;margin-top:.75rem;box-shadow:var(--shadow);transition:border-color .18s,transform .18s}
.card:hover{border-color:color-mix(in srgb,var(--accent) 55%,var(--border));transform:translateX(4px)}
.num{color:var(--accent);font-weight:700;font-size:1.05rem;min-width:1.6rem}
h2.t{font-size:1.02rem;font-weight:600;line-height:1.45}
h2.t a{color:var(--fg);text-decoration:none}
h2.t a:hover{color:var(--accent)}
.meta-line{color:var(--mut);font-size:.78rem;margin:.25rem 0 .45rem;text-transform:uppercase;letter-spacing:.05em}
.abs{font-size:.9rem;color:color-mix(in srgb,var(--fg) 80%,var(--mut))}
.lnk{display:inline-block;margin-top:.45rem;color:var(--accent);font-size:.82rem;text-decoration:none;word-break:break-all}
.lnk:hover{text-decoration:underline}
.pn{display:flex;justify-content:space-between;gap:1rem;margin:2.2rem 0 0;position:relative;z-index:1}
.pn a{color:var(--fg);text-decoration:none;background:var(--card);border:1px solid var(--border);
      border-radius:.75rem;padding:.6rem 1rem;font-size:.85rem;flex:1;transition:.18s}
.pn a:hover{border-color:var(--accent)}
.pn a.next{text-align:right}
.pn small{display:block;color:var(--mut);font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.15rem}
footer{margin-top:3.2rem;color:var(--mut);font-size:.8rem;text-align:center;position:relative;z-index:1}
footer a{color:var(--mut)}
@media(max-width:640px){.themes button{padding:.28rem .5rem;font-size:.72rem}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

THEME_JS = """
const r=document.documentElement;
var th=localStorage.getItem('theme');if(th==='amoled')th='dark';r.dataset.theme=th||'';
document.getElementById('themes').addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  r.dataset.theme=b.dataset.t;localStorage.setItem('theme',b.dataset.t);sync();
});
function sync(){document.querySelectorAll('.themes button').forEach(b=>
  b.classList.toggle('active',b.dataset.t===r.dataset.theme));}
sync();
"""


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
                cur["meta"] = line.strip("*").strip()
            elif line.startswith("http"):
                cur["link"] = line.strip()
            elif line.strip() and not cur["link"]:
                cur["abstract"] += (" " if cur["abstract"] else "") + line.strip()
    if cur:
        entries.append(cur)
    return entries


def render_edition(editions, idx, out_path):
    when_str, entries = editions[idx]
    cards = []
    for i, e in enumerate(entries, 1):
        title = (
            f'<a href="{html.escape(e["link"], quote=True)}">{html.escape(e["title"])}</a>'
            if e["link"] else html.escape(e["title"])
        )
        link = f'<a class="lnk" href="{html.escape(e["link"], quote=True)}">{html.escape(e["link"])}</a>' if e["link"] else ""
        cards.append(f"""
<article class="card">
  <div class="num">{i}</div>
  <div>
    <h2 class="t">{title}</h2>
    <p class="meta-line">{html.escape(e['meta'])}</p>
    {f'<p class="abs">{html.escape(e["abstract"])}</p>' if e['abstract'] else ''}
    {link}
  </div>
</article>""")

    nav = []
    if idx > 0:
        prev = editions[idx - 1][0]
        nav.append(f'<a href="{prev}.html"><small>← Previous</small>{prev}</a>')
    else:
        nav.append('<a style="visibility:hidden" aria-hidden="true"></a>')
    if idx < len(editions) - 1:
        nxt = editions[idx + 1][0]
        nav.append(f'<a class="next" href="{nxt}.html"><small>Next →</small>{nxt}</a>')
    else:
        nav.append('<a style="visibility:hidden" aria-hidden="true"></a>')

    page = f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%20100%20100%22%3E%3Ctext%20y=%22.9em%22%20font-size=%2290%22%3E%F0%9F%A7%BE%3C/text%3E%3C/svg%3E">
<title>PaperTrail — {when_str}</title>
<style>{CSS}</style></head><body>
<header class="topbar">
<a class="brand" href="/"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/></svg> Paper<em>Trail</em></a>
<nav class="themes" id="themes">
<button data-t="dark">Dark</button>
<button data-t="paper">Paper</button>
<button data-t="light">Light</button>
</nav>
</header>
<p class="meta"><span>{len(entries)} papers · scored research digest</span><a href="/">📄 Latest</a><a href="/archive.html">🗂 Archive</a><a href="https://news.raghav56.tech">📰 News Digest</a></p>
{''.join(cards)}
<div class="pn">{''.join(nav)}</div>
<footer>papertrail · built by an agent on an oracle VPS · <a href="https://github.com/Raghav-56/papertrail">source</a> · sister site: <a href="https://news.raghav56.tech">news.raghav56.tech</a></footer>
<script>{THEME_JS}</script>
</body></html>"""
    out_path.write_text(page)
    return len(cards)


def main() -> int:
    files = sorted(VAULT.glob("*-papertrail.md"))
    if not files:
        print("NO_DIGESTS", file=sys.stderr)
        return 1
    editions = []  # (date_str, entries) newest last
    seen = set()
    for f in files:
        d = f.stem[:10]
        if d in seen:
            continue
        seen.add(d)
        entries = parse(f.read_text())
        if entries:
            editions.append((d, entries))
    if not editions:
        print("NO_ENTRIES", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    # archive page
    rows = "".join(
        f'<li><a href="{d}.html">{d}</a><span class="meta-line" style="margin:0">{len(e)} papers</span></li>'
        for d, e in reversed(editions)
    )
    archive = f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PaperTrail Archive</title>
<style>{CSS}ul{{list-style:none}}li{{display:flex;justify-content:space-between;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:.75rem;padding:.7rem 1rem;margin-top:.5rem;position:relative;z-index:1}}
li a{{color:var(--fg);text-decoration:none;font-weight:500}}li a:hover{{color:var(--accent)}}</style></head><body>
<header class="topbar"><a class="brand" href="/">Paper<em>Trail</em></a>
<nav class="themes" id="themes"><button data-t="dark">Dark</button><button data-t="paper">Paper</button><button data-t="light">Light</button></nav></header>
<p class="meta"><a href="/">📄 Latest</a><a href="https://news.raghav56.tech">📰 News Digest</a></p>
<h2 class="t">Editions</h2><ul>{rows}</ul>
<footer><a href="https://github.com/Raghav-56/papertrail">source</a></footer>
<script>{THEME_JS}</script></body></html>"""
    (OUT / "archive.html").write_text(archive)

    for i, (_d, entries) in enumerate(editions):
        n = render_edition(editions, i, OUT / f"{_d}.html")
        total += n

    latest_n = render_edition(editions, len(editions) - 1, OUT / "index.html")
    print(f"WROTE {OUT}/index.html ({latest_n} papers) + {len(editions) - 1} older editions, archive ({total} total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
