#!/usr/bin/env python3
"""PaperTrail v0.3 — two feeds from arXiv (+ HN signals).

Zero-dependency (stdlib only):
  DAILY FEED   arXiv papers submitted *yesterday*, keyword-scored, top N by
               quality threshold; friendly empty state when nothing qualifies.
  MONTHLY POOL rolling 30-day arXiv value pool: keyword score + cheap HN
               engagement signals, persisted between runs so ranks evolve,
               old entries decayed, rank movement tracked.

HN stories never appear as standalone items; they only feed the pool's value
signal (and serve as an emergency fallback source for the daily feed when
arXiv is unreachable).
"""
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ARXIV_API = "http://export.arxiv.org/api/query"
HN_API = "https://hn.algolia.com/api/v1"
HN_ALGOLIA_SEARCH = f"{HN_API}/search"
NS = {"a": "http://www.w3.org/2005/Atom"}

# Note: stdlib xml.etree.ElementTree is used deliberately (zero-dependency
# constraint). Since Python 3.x it does not resolve external entities, and the
# input is the trusted arXiv export API over its official endpoint — XXE/billion-
# laughs exposure here is not a realistic concern.

CATEGORIES = ["cs.AI", "cs.CL", "cs.LG", "cs.SE"]

# Keyword scoring: topic interest weights for Raghav
KEYWORDS = {
    "agent": 3, "agentic": 3, "multi-agent": 3, "tool use": 3,
    "interpretability": 4, "mechanistic": 4, "steering": 3, "sparse autoencoder": 4,
    "memory": 2, "retrieval": 2, "rag": 2,
    "mcp": 4, "protocol": 1,
    "efficien": 2, "quantiz": 2, "inference": 2, "kv cache": 3,
    "code generation": 2, "swe-bench": 3, "benchmark": 1,
    "security": 2, "prompt injection": 3,
}

# Pool tuning
POOL_WINDOW_DAYS = 30      # entries older than this are pruned
POOL_DECAY_PER_DAY = 0.95  # multiplicative decay applied per day since publication
POOL_MAX_ITEMS = 150       # hard cap on persisted pool size
DAILY_MIN_SCORE = 2        # quality threshold for the daily feed
DAILY_MAX_ITEMS = 10

# State lives next to the script; not committed (see .gitignore)
POOL_STATE_PATH = Path(__file__).resolve().parent / "pool_state.json"


# ---------------------------------------------------------------- fetching

def _http_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "PaperTrail/0.3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_papers(categories: list[str], max_results: int = 60) -> list[dict]:
    cats = " OR ".join(f"cat:{c}" for c in categories)
    query = urllib.parse.urlencode({
        "search_query": cats,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": max_results,
    })
    url = f"{ARXIV_API}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "PaperTrail/0.3"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    papers = []
    for entry in root.findall("a:entry", NS):
        title = re.sub(r"\s+", " ", entry.findtext("a:title", "", NS)).strip()
        abstract = re.sub(r"\s+", " ", entry.findtext("a:summary", "", NS)).strip()
        link = entry.findtext("a:id", "", NS).strip()
        published = entry.findtext("a:published", "", NS)[:10]
        authors = [a.findtext("a:name", "", NS) for a in entry.findall("a:author", NS)]
        papers.append({"title": title, "abstract": abstract, "link": link,
                       "published": published, "authors": authors})
    return papers


def parse_arxiv_atom(xml_text: str) -> list[dict]:
    """Parse arXiv Atom XML text into paper dicts (testable without network)."""
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall("a:entry", NS):
        title = re.sub(r"\s+", " ", entry.findtext("a:title", "", NS)).strip()
        abstract = re.sub(r"\s+", " ", entry.findtext("a:summary", "", NS)).strip()
        link = entry.findtext("a:id", "", NS).strip()
        published = entry.findtext("a:published", "", NS)[:10]
        authors = [a.findtext("a:name", "", NS) for a in entry.findall("a:author", NS)]
        papers.append({"title": title, "abstract": abstract, "link": link,
                       "published": published, "authors": authors})
    return papers


def fetch_hn_stories(min_points: int = 20, hits_per_page: int = 30) -> list[dict]:
    """Recent HN stories — emergency fallback source for the daily feed only."""
    query = urllib.parse.urlencode({
        "tags": "story",
        "numericFilters": f"points>{min_points},created_at_i>{int(time.time()) - 86400*3}",
        "hitsPerPage": hits_per_page,
    })
    data = _http_json(f"{HN_ALGOLIA_SEARCH}/search_by_date?{query}")
    stories = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        stories.append({
            "title": title,
            "abstract": f"{hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments on Hacker News",
            "link": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            "published": (hit.get("created_at") or "")[:10],
            "authors": [],
        })
    return stories


def fetch_hn_signals(title: str) -> tuple[int, int]:
    """Cheap HN engagement lookup: (mention_count, best_points) for a paper title."""
    try:
        query = urllib.parse.urlencode({"query": title, "tags": "story", "hitsPerPage": 10})
        data = _http_json(f"{HN_ALGOLIA_SEARCH}?{query}", timeout=15)
        hits = [h for h in data.get("hits", []) if h.get("title")]
        points = max((h.get("points") or 0) for h in hits) if hits else 0
        return len(hits), points
    except Exception:
        return 0, 0


# ---------------------------------------------------------------- scoring

def score(paper: dict) -> tuple[int, list[str]]:
    text = f"{paper['title']} {paper['abstract']}".lower()
    hits = [kw for kw in KEYWORDS if kw in text]
    return sum(KEYWORDS[kw] for kw in hits), hits


def item_id(url: str) -> str:
    """Frozen contract: sha1(url)[:12]."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def make_item(paper: dict, s: int, hits: list[str]) -> dict:
    return {
        "title": paper["title"],
        "url": paper["link"],
        "source": paper.get("source", "arxiv"),
        "score": s,
        "matched": hits,
        "summary": paper["abstract"][:600] + ("…" if len(paper["abstract"]) > 600 else ""),
        "published": paper["published"],
        "item_id": item_id(paper["link"]),
    }


# ---------------------------------------------------------------- daily feed

def filter_yesterday(papers: list[dict], today: date | None = None) -> list[dict]:
    """Keep only papers whose arXiv submitted date == yesterday."""
    y = (today or date.today()) - timedelta(days=1)
    y_str = y.isoformat()
    return [p for p in papers if p.get("published") == y_str]


def select_daily(papers: list[dict], today: date | None = None,
                 min_score: int = DAILY_MIN_SCORE,
                 limit: int = DAILY_MAX_ITEMS) -> list[dict]:
    """Yesterday-only papers scoring >= min_score, best first, up to limit."""
    yesterdays = filter_yesterday(papers, today)
    scored = []
    for i, p in enumerate(yesterdays):
        s, hits = score(p)
        if s >= min_score:
            scored.append((s, i, p, hits))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [make_item(p, s, hits) for s, _i, p, hits in scored[:limit]]


# ---------------------------------------------------------------- value pool

def engagement_value(mentions: int, points: int) -> float:
    """Cheap engagement signal from HN: mention presence + traction."""
    return round(math.log1p(max(mentions, 0)) * 2.0 + math.log1p(max(points, 0)) * 1.5, 3)


def load_pool_state(path: Path = POOL_STATE_PATH) -> dict:
    try:
        state = json.loads(path.read_text())
        if isinstance(state, dict) and isinstance(state.get("entries"), dict):
            return state
    except Exception:
        pass
    return {"entries": {}}


def save_pool_state(state: dict, path: Path = POOL_STATE_PATH) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def compute_value(paper: dict, kw_score: int, mentions: int, points: int,
                  today: date | None = None) -> float:
    """Current decayed value of a pool candidate."""
    t = today or date.today()
    try:
        pub = date.fromisoformat(paper["published"])
    except (ValueError, KeyError):
        pub = t
    age_days = max((t - pub).days, 0)
    raw = kw_score + engagement_value(mentions, points)
    return round(raw * (POOL_DECAY_PER_DAY ** age_days), 3)


def update_pool(state: dict, candidates: list[dict], today: date | None = None,
                signals_fn=None) -> dict:
    """Merge fresh candidates into the persisted pool and recompute values.

    candidates: full paper dicts (any of the last ~30 days).
    signals_fn(paper_title) -> (mentions, points); defaults to live HN lookup.
    Mutates and returns state.
    """
    t = today or date.today()
    signals_fn = signals_fn or fetch_hn_signals
    entries = state.setdefault("entries", {})
    # previous ranks, for movement tracking
    prev_ranks = {eid: e.get("rank") for eid, e in entries.items()}

    for p in candidates:
        eid = item_id(p["link"])
        if not eid:
            continue
        s, _hits = score(p)
        mentions, points = signals_fn(p["title"])
        val = compute_value(p, s, mentions, points, t)
        ent = entries.get(eid)
        if ent is None:
            entries[eid] = {
                "item_id": eid,
                "title": p["title"],
                "url": p["link"],
                "published": p.get("published", ""),
                "first_seen": t.isoformat(),
                "kw_score": s,
                "mentions": mentions,
                "points": points,
                "value": val,
            }
        else:
            ent.update({
                "title": p["title"],
                "kw_score": s,
                "mentions": mentions,
                "points": points,
                "value": val,
            })

    prune_pool(entries, t)

    ranked = sorted(entries.values(), key=lambda e: (-e["value"], e["item_id"]))
    for rank, ent in enumerate(ranked, 1):
        eid = ent["item_id"]
        ent["rank"] = rank
        ent["prev_rank"] = prev_ranks.get(eid)
    return state


def prune_pool(entries: dict, today: date | None = None,
               window_days: int = POOL_WINDOW_DAYS,
               max_items: int = POOL_MAX_ITEMS) -> None:
    """Drop entries outside the rolling window, then cap size by value."""
    t = today or date.today()
    cutoff = t - timedelta(days=window_days)
    stale = [eid for eid, e in entries.items()
             if _parse_date(e.get("published")) < cutoff]
    for eid in stale:
        del entries[eid]
    if len(entries) > max_items:
        ranked = sorted(entries.items(), key=lambda kv: (-kv[1]["value"], kv[0]))
        for eid, _e in ranked[max_items:]:
            del entries[eid]


def _parse_date(s: str | None) -> date:
    try:
        return date.fromisoformat(s or "")
    except ValueError:
        return date.min


def pool_render_list(state: dict) -> list[dict]:
    """Sorted-by-value pool items shaped for rendering / JSON export."""
    out = []
    for e in sorted(state.get("entries", {}).values(),
                    key=lambda e: (-e["value"], e["item_id"])):
        out.append({
            "title": e["title"],
            "url": e["url"],
            "source": "arxiv",
            "score": e.get("kw_score", 0),
            "summary": "",
            "published": e.get("published", ""),
            "item_id": e["item_id"],
            "value": e["value"],
            "first_seen": e.get("first_seen"),
            "prev_rank": e.get("prev_rank"),
            "rank": e.get("rank"),
            "mentions": e.get("mentions", 0),
            "points": e.get("points", 0),
        })
    return out


# ---------------------------------------------------------------- outputs

def render_markdown(daily: list[dict], pool: list[dict], out_path: Path) -> None:
    today = date.today().isoformat()
    lines = [
        "---",
        f"created: {today}",
        f"last: {today}",
        'categories: ["[[Digests]]"]',
        "tags: [papertrail, arxiv]",
        "---",
        "",
        f"# PaperTrail Digest — {today}",
        "",
    ]
    if not daily:
        lines += [
            "Nothing worth your time today — no arXiv submissions from yesterday crossed the relevance bar.",
            "",
        ]
    else:
        lines += [f"## Daily feed — {len(daily)} papers from yesterday", ""]
        for i, it in enumerate(daily, 1):
            lines += [
                f"### {i}. {it['title']}",
                "",
                f"*{it['published']} · score {it['score']} · [{it['url']}]({it['url']})*",
                "",
                it["summary"],
                "",
            ]
    lines += ["## Monthly value pool — top 10", ""]
    if not pool:
        lines += ["_Pool warming up._", ""]
    else:
        for i, it in enumerate(pool[:10], 1):
            move = ""
            pr = it.get("prev_rank")
            r = it.get("rank")
            if pr and r:
                d = pr - r
                move = " ▲" * d if d > 0 else (" ▼" * -d if d < 0 else " =")
            lines += [
                f"- **{i}.** {it['title']} — value {it['value']} "
                f"(score {it['score']}, first seen {it.get('first_seen', '?')}){move}",
            ]
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    vault_digest_dir = Path.home() / "raghav/Raghav-obsidian/Notes/Digests"
    vault_digest_dir.mkdir(parents=True, exist_ok=True)
    web_dir = Path("/var/www/papertrail")
    web_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # --- fetch
    papers: list[dict] = []
    arxiv_ok = True
    try:
        papers = [dict(p, source="arxiv") for p in fetch_papers(CATEGORIES)]
    except Exception as e:
        arxiv_ok = False
        print(f"FETCH_ERROR arxiv: {e}", file=sys.stderr)
        try:
            papers = [dict(s, source="hn") for s in fetch_hn_stories()]
        except Exception as e2:
            print(f"FETCH_ERROR hn-fallback: {e2}", file=sys.stderr)

    # --- daily feed (strictly yesterday)
    daily = select_daily([p for p in papers if p.get("source") != "hn"], today)
    if arxiv_ok and not daily:
        print("EMPTY_DAILY (nothing passed threshold)")
    elif not arxiv_ok:
        # fallback: score whatever we have (HN stories) against yesterday
        daily = select_daily(papers, today)

    # --- monthly pool (only meaningful with arXiv data)
    pool: list[dict] = []
    if arxiv_ok:
        state = load_pool_state()
        cutoff = today - timedelta(days=POOL_WINDOW_DAYS + 2)
        candidates = [p for p in papers if p.get("published", "") >= cutoff.isoformat()]
        update_pool(state, candidates, today)
        try:
            save_pool_state(state)
        except Exception as e:
            print(f"WARNING: could not persist pool state: {e}", file=sys.stderr)
        pool = pool_render_list(state)

    # --- structured payloads for render_site.py
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        (web_dir / "daily.json").write_text(json.dumps(
            {"date": today.isoformat(), "empty_message":
             "Nothing worth your time today — no arXiv submissions from yesterday crossed the relevance bar.",
             "items": daily}, indent=2) + "\n")
        (web_dir / "pool.json").write_text(json.dumps(
            {"generated": generated, "items": pool}, indent=2) + "\n")
    except Exception as e:
        print(f"WARNING: could not write web payloads: {e}", file=sys.stderr)

    # --- markdown digest (vault)
    out = vault_digest_dir / f"{today.isoformat()}-papertrail.md"
    render_markdown(daily, pool, out)

    print(f"WROTE {out} (daily={len(daily)}, pool={len(pool)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
