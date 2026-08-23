#!/usr/bin/env python3
"""PaperTrail v0.2 — fetch recent arXiv papers + HN stories, score, render a markdown digest.

Zero-dependency (stdlib only): arXiv Atom API + HN Algolia API via urllib,
scored with keyword weights, rendered to a dated markdown digest. Designed for cron.
"""
import time
import sys
import re
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, timedelta, timezone
from pathlib import Path

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}

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

def fetch_papers(categories: list[str], max_results: int = 40) -> list[dict]:
    cats = " OR ".join(f"cat:{c}" for c in categories)
    query = urllib.parse.urlencode({
        "search_query": cats,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": max_results,
    })
    url = f"{ARXIV_API}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "PaperTrail/0.1"})
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

HN_ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"

def fetch_hn(tags: str = "story", min_points: int = 20, hits_per_page: int = 50) -> list[dict]:
    """Fetch recent front-page-worthy HN stories via Algolia, filtered by interest keywords."""
    query = urllib.parse.urlencode({
        "tags": tags,
        "numericFilters": f"points>{min_points},created_at_i>{int(time.time()) - 86400*3}",
        "hitsPerPage": hits_per_page,
    })
    req = urllib.request.Request(f"{HN_ALGOLIA}?{query}", headers={"User-Agent": "PaperTrail/0.2"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
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

def score(paper: dict) -> tuple[int, list[str]]:
    text = f"{paper['title']} {paper['abstract']}".lower()
    hits = [kw for kw in KEYWORDS if kw in text]
    return sum(KEYWORDS[kw] for kw in hits), hits

def render(papers: list[dict], out_path: Path) -> None:
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
        f"Auto-generated from arXiv ({', '.join(CATEGORIES)}) + Hacker News, top {len(papers)} by keyword relevance.",
        "",
    ]
    for i, (s, hits, p) in enumerate(papers, 1):
        first_author = p["authors"][0] if p["authors"] else "Unknown"
        et_al = " et al." if len(p["authors"]) > 1 else ""
        lines += [
            f"## {i}. {p['title']}",
            "",
            f"*{first_author}{et_al} · {p['published']} · score {s} (matched: {', '.join(hits) or '—'}) · source: `{p.get('source', '?')}`*",
            "",
            p["abstract"][:600] + ("…" if len(p["abstract"]) > 600 else ""),
            "",
            f"[{p['link']}]({p['link']})",
            "",
        ]
    out_path.write_text("\n".join(lines), encoding="utf-8")

CATEGORIES = ["cs.AI", "cs.CL", "cs.LG", "cs.SE"]

def main() -> int:
    vault_digest_dir = Path.home() / "raghav/Raghav-obsidian/Notes/Digests"
    vault_digest_dir.mkdir(parents=True, exist_ok=True)
    papers = []
    try:
        papers += [dict(p, source="arxiv") for p in fetch_papers(CATEGORIES)]
    except Exception as e:
        print(f"FETCH_ERROR arxiv: {e}", file=sys.stderr)
    try:
        papers += [dict(s, source="hn") for s in fetch_hn()]
    except Exception as e:
        print(f"FETCH_ERROR hn: {e}", file=sys.stderr)
    if not papers:
        print("NO_SOURCES_SUCCEEDED", file=sys.stderr)
        return 1
    scored = sorted(
        ((score(p)[0], score(p)[1], i, p) for i, p in enumerate(papers)),
        key=lambda t: (t[0], -t[2]), reverse=True
    )
    # keep only last 7 days of submissions, top 10
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    recent = [(s, h, p) for s, h, _i, p in scored if p["published"] >= cutoff]
    top = [r for r in recent if r[2].get("source") != "hn"][:7]
    for r in recent:
        if r[2].get("source") == "hn" and len(top) < 10 and r not in top:
            top.append(r)
        if len(top) >= 10:
            break
    # fill remaining slots from everything else by score
    for r in recent:
        if len(top) >= 10:
            break
        if r not in top:
            top.append(r)
    if not top:
        print("NO_RECENT_PAPERS")
        return 0
    out = vault_digest_dir / f"{date.today().isoformat()}-papertrail.md"
    render(top, out)
    print(f"WROTE {out} ({len(top)} papers)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
