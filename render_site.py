#!/usr/bin/env python3
"""Render PaperTrail site into /var/www/papertrail/.

Pages:
  index.html  — daily feed (yesterday's arXiv papers) or friendly empty state
  pool.html   — rolling monthly value pool, sorted by value, with rank movement
  archive.html / dated editions — legacy digest editions from the vault

JSON export is schema v2: {"schema":2,"generated":iso,"daily":[items],"pool":[items]}.
Structured payloads (daily.json/pool.json written by papertrail.py) drive the
new pages; if they're missing or malformed we fall back to parsing the latest
vault digest. JSON failure never blocks HTML rendering.
"""
import html
import json
import re
import sys
from datetime import datetime, timezone
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
.topbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;
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
.meta a.on{color:var(--accent);border-color:var(--accent)}
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
.empty{text-align:center;padding:3rem 1.5rem;background:var(--card);border:1px dashed var(--border);
  border-radius:.9rem;color:var(--mut);position:relative;z-index:1;margin-top:1rem}
.empty .big{font-size:2rem;margin-bottom:.6rem}
.badge{display:inline-block;font-size:.72rem;font-weight:600;padding:.12rem .55rem;border-radius:999px;
  background:var(--bg2);border:1px solid var(--border);color:var(--mut);margin-left:.35rem;text-transform:none;letter-spacing:0}
.badge.up{color:#22c55e;border-color:color-mix(in srgb,#22c55e 40%,var(--border))}
.badge.down{color:#ef4444;border-color:color-mix(in srgb,#ef4444 40%,var(--border))}
footer{margin-top:3.2rem;color:var(--mut);font-size:.8rem;text-align:center;position:relative;z-index:1}
footer a{color:var(--mut)}
.pn{display:flex;justify-content:space-between;gap:1rem;margin:2.2rem 0 0;position:relative;z-index:1}
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

FAVICON = ('<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22'
           '%20viewBox=%220%200%20100%20100%22%3E%3Ctext%20y=%22.9em%22%20font-size=%2290%22%3E'
           '%F0%9F%A7%BE%3C/text%3E%3C/svg%3E">')


def _shell(title: str, meta_links: str, body: str) -> str:
    return f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{FAVICON}
<title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>
<header class="topbar">
<a class="brand" href="/"><svg viewBox="0 0 24 24" fill="none" stroke-width="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/></svg> Paper<em>Trail</em></a>
<nav class="themes" id="themes">
<button data-t="dark">Dark</button>
<button data-t="paper">Paper</button>
<button data-t="light">Light</button>
</nav>
</header>
<p class="meta">{meta_links}</p>
{body}
<footer>papertrail · built by an agent on an oracle VPS · <a href="https://github.com/Raghav-56/papertrail">source</a> · suite: <a href="https://news.raghav56.tech">news</a> · <a href="https://infogain.raghav56.tech">infogain</a></footer>
<script>{THEME_JS}</script>
</body></html>"""


def _nav(active: str) -> str:
    links = [
        ("/", "📄 Daily", "daily"),
        ("/pool.html", "🏆 Value Pool", "pool"),
        ("/archive.html", "🗂 Archive", "archive"),
    ]
    parts = []
    for href, label, key in links:
        cls = ' class="on"' if key == active else ""
        parts.append(f'<a href="{href}"{cls}>{label}</a>')
    parts.append('<a href="https://infogain.raghav56.tech">⚡ InfoGain</a>')
    return "".join(parts)


# ---------------------------------------------------------------- item cards

def _item_card(i: int, it: dict, extra_meta: str = "") -> str:
    title = (
        f'<a href="{html.escape(it["url"], quote=True)}">{html.escape(it["title"])}</a>'
        if it.get("url") else html.escape(it["title"])
    )
    bits = [it.get("published") or "", f"score {it.get('score', 0)}"]
    meta_line = " · ".join(b for b in bits if b).upper() + extra_meta
    link = (f'<a class="lnk" href="{html.escape(it["url"], quote=True)}">'
            f'{html.escape(it["url"])}</a>') if it.get("url") else ""
    summary = it.get("summary") or ""
    return f"""
<article class="card">
  <div class="num">{i}</div>
  <div>
    <h2 class="t">{title}</h2>
    <p class="meta-line">{html.escape(meta_line)}</p>
    {f'<p class="abs">{html.escape(summary)}</p>' if summary else ''}
    {link}
  </div>
</article>"""


def _rank_badge(rank, prev_rank) -> str:
    if not prev_rank or not rank or prev_rank == rank:
        return ""
    if rank < prev_rank:
        return f'<span class="badge up">▲ {prev_rank}→{rank}</span>'
    return f'<span class="badge down">▼ {prev_rank}→{rank}</span>'


def render_index(daily: dict | None) -> tuple[str, int]:
    """Daily feed page. Returns (html, item_count)."""
    date_str = (daily or {}).get("date", "")
    items = (daily or {}).get("items") or []
    empty_msg = (daily or {}).get("empty_message") or \
        "Nothing worth your time today."
    heading = f"<h2 class=\"t\" style=\"margin:1rem 0 0\">Daily Feed — {html.escape(date_str)}</h2>"
    if items:
        body = heading + "".join(_item_card(i, it) for i, it in enumerate(items, 1))
        n = len(items)
    else:
        body = heading + (f'<div class="empty"><div class="big">🌤️</div>'
                          f'<p>{html.escape(empty_msg)}</p><p style="margin-top:.5rem">'
                          f'Check back tomorrow — the pool below keeps tracking what matters.</p></div>'
                          f'<div style="text-align:center;margin-top:1.4rem;position:relative;z-index:1">'
                          f'<a class="lnk" href="/pool.html">Browse the monthly value pool →</a></div>')
        n = 0
    return _shell(f"PaperTrail — {date_str}", _nav("daily"), body), n


def render_pool(pool: dict | None) -> tuple[str, int]:
    """Monthly value pool page sorted by value."""
    generated = (pool or {}).get("generated", "")
    items = (pool or {}).get("items") or []
    heading = ("<h2 class=\"t\" style=\"margin:1rem 0 0\">Monthly Value Pool — "
               "last 30 days, rescored every run</h2>"
               f'<p class="meta-line">value = keyword score + HN engagement · decayed daily · '
               f'updated {html.escape(generated[:10] if generated else "?")}</p>')
    if items:
        cards = []
        for i, it in enumerate(items, 1):
            extra = (f" · VALUE {it.get('value', 0)} · first seen {it.get('first_seen') or '?'}"
                     f" · hn {it.get('mentions', 0)} mentions/{it.get('points', 0)} pts")
            card = _item_card(i, it, extra)
            # insert movement badge after the title link
            badge = _rank_badge(it.get("rank"), it.get("prev_rank"))
            if badge:
                card = card.replace("</h2>", f"{badge}</h2>", 1)
            cards.append(card)
        body = heading + "".join(cards)
    else:
        body = heading + ('<div class="empty"><div class="big">🌱</div>'
                          "<p>The pool is warming up — run the fetcher to seed it.</p></div>")
    return _shell("PaperTrail — Value Pool", _nav("pool"), body), len(items)


# ---------------------------------------------------------------- legacy digest pages

def parse(md: str):
    entries = []
    cur = None
    for line in md.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            if cur:
                entries.append(cur)
            cur = {"title": line[3:].strip(), "meta": "", "abstract": "", "link": ""}
        elif cur is not None:
            if line.startswith("*") and line.endswith("*") and not cur["meta"]:
                cur["meta"] = line.strip("*").strip()
            elif line.startswith("http"):
                cur["link"] = line.strip()
            elif line.startswith("[") and "](" in line:
                cur["link"] = line[line.index("](") + 2:].rstrip(")").strip()
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

    pn_css = ".pn a{color:var(--fg);text-decoration:none;background:var(--card);border:1px solid var(--border);border-radius:.75rem;padding:.6rem 1rem;font-size:.85rem;flex:1;transition:.18s}.pn a:hover{border-color:var(--accent)}.pn a.next{text-align:right}.pn small{display:block;color:var(--mut);font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.15rem}"
    page = f"""<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{FAVICON}
<title>PaperTrail — {when_str}</title>
<style>{CSS}{pn_css}</style></head><body>
<div class="pn" style="margin-top:0"><span></span></div>
{''.join(cards)}
<div class="pn">{''.join(nav)}</div>
<footer><a href="/">back to today</a> · <a href="https://github.com/Raghav-56/papertrail">source</a></footer>
<script>{THEME_JS}</script>
</body></html>"""
    out_path.write_text(page)
    return len(cards)


# ---------------------------------------------------------------- JSON export (schema v2)

def build_v2_payload(daily: dict | None, pool: dict | None) -> dict:
    """Frozen contract: {"schema":2,"generated":iso,"daily":[...],"pool":[...]}.

    Each item: title/url/source/score/summary/published/item_id (sha1(url)[:12]);
    pool items additionally carry value/first_seen/prev_rank.
    """

    def base_item(it: dict) -> dict:
        url = it.get("url") or ""
        import hashlib
        return {
            "title": it.get("title", ""),
            "url": url,
            "source": it.get("source", "arxiv"),
            "score": it.get("score"),
            "summary": it.get("summary", ""),
            "published": it.get("published", ""),
            "item_id": it.get("item_id") or hashlib.sha1(url.encode()).hexdigest()[:12],
        }

    daily_items = [base_item(it) for it in ((daily or {}).get("items") or [])]
    pool_items = []
    for it in (pool or {}).get("items") or []:
        p = base_item(it)
        p.update({
            "value": it.get("value"),
            "first_seen": it.get("first_seen"),
            "prev_rank": it.get("prev_rank"),
        })
        pool_items.append(p)
    return {
        "schema": 2,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "daily": daily_items,
        "pool": pool_items,
    }


def write_json_export(daily: dict | None, pool: dict | None) -> None:
    """Write /var/www/papertrail/papertrail.json. Never raises: a JSON
    failure must not block HTML rendering, only warn."""
    try:
        data = build_v2_payload(daily, pool)
        (OUT / "papertrail.json").write_text(json.dumps(data, indent=2) + "\n")
    except Exception as exc:
        print(f"WARNING: failed to write {OUT}/papertrail.json: {exc}", file=sys.stderr)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"WARNING: could not load {path.name}: {e}", file=sys.stderr)
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    daily = _load_json(OUT / "daily.json")
    pool = _load_json(OUT / "pool.json")

    # fallback: derive daily from latest vault digest when payload missing
    if not daily or not isinstance(daily.get("items"), list):
        files = sorted(VAULT.glob("*-papertrail.md"))
        if files:
            entries = parse(files[-1].read_text())
            arxiv_entries = [e for e in entries if "arxiv.org" in e.get("link", "")]
            if arxiv_entries:
                daily = {"date": files[-1].stem[:10], "items": [
                    {"title": e["title"], "url": e["link"], "source": "arxiv",
                     "score": None, "summary": e["abstract"],
                     "published": files[-1].stem[:10], "item_id": None}
                    for e in arxiv_entries]}
    if not pool or not isinstance(pool.get("items"), list):
        pool = {"generated": "", "items": []}

    # --- pages
    index_html, daily_n = render_index(daily)
    (OUT / "index.html").write_text(index_html)

    pool_html, pool_n = render_pool(pool)
    (OUT / "pool.html").write_text(pool_html)

    # --- legacy archive + dated editions (best-effort)
    editions = []
    try:
        seen = set()
        for f in sorted(VAULT.glob("*-papertrail.md")):
            d = f.stem[:10]
            if d in seen:
                continue
            seen.add(d)
            entries = parse(f.read_text())
            if entries:
                editions.append((d, entries))
        if editions:
            ul_css = "ul.archive{list-style:none}ul.archive li{display:flex;justify-content:space-between;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:.75rem;padding:.7rem 1rem;margin-top:.5rem;position:relative;z-index:1}ul.archive li a{color:var(--fg);text-decoration:none;font-weight:500}ul.archive li a:hover{color:var(--accent)}"
            rows = "".join(
                f'<li><a href="{d}.html">{d}</a><span class="meta-line" style="margin:0">{len(e)} papers</span></li>'
                for d, e in reversed(editions))
            archive_body = f'<h2 class="t" style="margin-top:1rem">Editions</h2><ul class="archive">{rows}</ul>'
            (OUT / "archive.html").write_text(
                _shell("PaperTrail Archive", _nav("archive"), archive_body).replace(
                    "</style>", ul_css + "</style>", 1))
            for i, (_d, _entries) in enumerate(editions):
                render_edition(editions, i, OUT / f"{_d}.html")
    except Exception as exc:
        print(f"WARNING: archive rendering skipped: {exc}", file=sys.stderr)

    # --- JSON export last, non-blocking
    write_json_export(daily, pool)

    print(f"WROTE {OUT}/index.html ({daily_n} daily) + pool.html ({pool_n} pooled)"
          + (f" + {len(editions)} editions/archive" if editions else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
