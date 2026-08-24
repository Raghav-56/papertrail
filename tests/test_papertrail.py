"""Tests for PaperTrail v0.3: yesterday filter, scoring, pool persistence,
decay/rescoring, and schema v2 export shape. Run: python3 -m unittest -v"""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import papertrail as pt
import render_site as rs


def _entry_xml(title, abstract, link_id, published):
    return f"""
<entry>
  <title>{title}</title>
  <summary>{abstract}</summary>
  <id>http://arxiv.org/abs/{link_id}</id>
  <published>{published}T00:00:00Z</published>
  <author><name>Test Author</name></author>
</entry>"""


def make_feed(entries_xml):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            + "".join(entries_xml) + "</feed>")


FIXTURE_YESTERDAY_MIX = make_feed([
    _entry_xml("Yesterday paper", "agentic tool use", "2408.0001",
               (date.today() - timedelta(days=1)).isoformat()),
    _entry_xml("Today paper", "agents everywhere", "2408.0002", date.today().isoformat()),
    _entry_xml("Old paper", "interpretability study", "2408.0003",
               (date.today() - timedelta(days=5)).isoformat()),
])


class YesterdayFilterTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 24)
        self.papers = pt.parse_arxiv_atom(make_feed([
            _entry_xml("Yesterday paper", "agentic tool use", "2408.0001",
                       (self.today - timedelta(days=1)).isoformat()),
            _entry_xml("Today paper", "agents everywhere", "2408.0002",
                       self.today.isoformat()),
            _entry_xml("Old paper", "interpretability study", "2408.0003",
                       (self.today - timedelta(days=5)).isoformat()),
        ]))

    def test_parse_fixture(self):
        self.assertEqual(len(self.papers), 3)
        self.assertEqual(self.papers[0]["title"], "Yesterday paper")
        self.assertEqual(self.papers[0]["published"],
                         (self.today - timedelta(days=1)).isoformat())

    def test_yesterday_only(self):
        kept = pt.filter_yesterday(self.papers, today=self.today)
        self.assertEqual([p["title"] for p in kept], ["Yesterday paper"])

    def test_select_daily_threshold_and_cap(self):
        y = (self.today - timedelta(days=1)).isoformat()
        papers = [
            {"title": "low relevance weather", "abstract": "rainfall", "link": "u0",
             "published": y},
            {"title": "high agentic mcp interpretability sparse autoencoder",
             "abstract": "tool use", "link": "u1", "published": y},
        ] + [{"title": f"agent {i}", "abstract": "mcp agent", "link": f"u{i+2}",
              "published": y} for i in range(15)]
        items = pt.select_daily(papers, today=self.today)
        self.assertLessEqual(len(items), pt.DAILY_MAX_ITEMS)
        self.assertTrue(all(it["score"] >= pt.DAILY_MIN_SCORE for it in items))
        self.assertEqual(items[0]["item_id"], pt.item_id("u1"))  # top scorer first

    def test_empty_when_nothing_passes(self):
        y = (self.today - timedelta(days=1)).isoformat()
        items = pt.select_daily(
            [{"title": "weather", "abstract": "rain", "link": "u9", "published": y}],
            today=self.today)
        self.assertEqual(items, [])


class ScoringTest(unittest.TestCase):
    def test_keyword_score(self):
        s, hits = pt.score({"title": "Sparse autoencoder steering",
                            "abstract": "mechanistic interpretability of agents"})
        self.assertGreaterEqual(s, 14)
        self.assertIn("sparse autoencoder", hits)

    def test_zero_score_for_noise(self):
        s, _ = pt.score({"title": "Quantum chemistry", "abstract": "molecular bonds"})
        self.assertEqual(s, 0)

    def test_item_id_contract_sha1_12(self):
        import hashlib
        url = "https://arxiv.org/abs/2408.12345v1"
        self.assertEqual(pt.item_id(url), hashlib.sha1(url.encode()).hexdigest()[:12])


class PoolTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 24)
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "pool_state.json"
        self.no_signals = lambda t: (0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def _paper(self, n, days_ago, kw="agent"):
        return {"title": f"{kw} paper {n}", "abstract": kw,
                "link": f"https://arxiv.org/abs/2408.{n:05d}",
                "published": (self.today - timedelta(days=days_ago)).isoformat()}

    def test_persistence_and_first_seen(self):
        state = pt.load_pool_state(self.state_path)
        pt.update_pool(state, [self._paper(1, 0)], today=self.today,
                       signals_fn=self.no_signals)
        pt.save_pool_state(state, self.state_path)
        reloaded = pt.load_pool_state(self.state_path)
        ent = reloaded["entries"][pt.item_id("https://arxiv.org/abs/2408.00001")]
        self.assertEqual(ent["first_seen"], self.today.isoformat())
        self.assertEqual(ent["rank"], 1)

    def test_rescoring_updates_value_keeps_first_seen(self):
        state = pt.load_pool_state(self.state_path)
        pt.update_pool(state, [self._paper(1, 0)], today=self.today,
                       signals_fn=self.no_signals)
        eid = pt.item_id("https://arxiv.org/abs/2408.00001")
        first_seen = state["entries"][eid]["first_seen"]
        old_val = state["entries"][eid]["value"]
        pt.update_pool(state, [self._paper(1, 0)], today=self.today,
                       signals_fn=lambda t: (5, 120))
        self.assertGreater(state["entries"][eid]["value"], old_val)
        self.assertEqual(state["entries"][eid]["first_seen"], first_seen)

    def test_decay_prefers_recent(self):
        state = pt.load_pool_state(self.state_path)
        fresh, stale = self._paper(1, 0), self._paper(2, 20)
        pt.update_pool(state, [fresh, stale], today=self.today,
                       signals_fn=self.no_signals)
        e_fresh = state["entries"][pt.item_id(fresh["link"])]
        e_stale = state["entries"][pt.item_id(stale["link"])]
        self.assertEqual(e_fresh["rank"], 1)
        self.assertLess(e_stale["value"], e_fresh["value"])

    def test_prune_outside_window_and_engagement_boost(self):
        state = pt.load_pool_state(self.state_path)
        pt.update_pool(state, [self._paper(1, 40)], today=self.today,
                       signals_fn=self.no_signals)
        self.assertEqual(state["entries"], {})  # outside 30-day window

    def test_prev_rank_movement(self):
        state = pt.load_pool_state(self.state_path)
        a = self._paper(1, 5, kw="mcp interpretability sparse autoencoder")
        b = self._paper(2, 6, kw="benchmark protocol")
        ida = pt.item_id(a["link"])
        pt.update_pool(state, [a, b], today=self.today, signals_fn=self.no_signals)
        first_rank = state["entries"][ida]["rank"]
        # b gets huge engagement on rescore → ranks shift, prev_rank recorded
        pt.update_pool(state, [a, b], today=self.today,
                       signals_fn=lambda t: (10, 300) if "benchmark" in t else (0, 0))
        ent = state["entries"][ida]
        self.assertIsNotNone(ent["prev_rank"])
        self.assertNotEqual(ent["prev_rank"], ent["rank"])
        self.assertTrue(first_rank >= 1)

    def test_render_list_shape_sorted_by_value(self):
        state = pt.load_pool_state(self.state_path)
        pt.update_pool(state, [self._paper(1, 0), self._paper(2, 15)],
                       today=self.today, signals_fn=self.no_signals)
        items = pt.pool_render_list(state)
        values = [it["value"] for it in items]
        self.assertEqual(values, sorted(values, reverse=True))
        for key in ("title", "url", "source", "score", "summary", "published",
                    "item_id", "value", "first_seen", "prev_rank"):
            self.assertIn(key, items[0])


class SchemaV2ExportTest(unittest.TestCase):
    def test_v2_shape(self):
        daily = {"date": "2026-08-23", "items": [{
            "title": "T", "url": "https://arxiv.org/abs/a", "source": "arxiv",
            "score": 5, "summary": "s", "published": "2026-08-23"}]}
        pool = {"generated": "2026-08-24T00:00:00Z",
                "items": [dict(daily["items"][0], value=7.5,
                               first_seen="2026-08-20", prev_rank=3)]}
        data = rs.build_v2_payload(daily, pool)
        self.assertEqual(data["schema"], 2)
        self.assertEqual(set(data.keys()), {"schema", "generated", "daily", "pool"})
        base_keys = {"title", "url", "source", "score", "summary", "published", "item_id"}
        self.assertTrue(base_keys <= set(data["daily"][0].keys()))
        self.assertTrue(base_keys <= set(data["pool"][0].keys()))
        self.assertEqual(data["pool"][0]["value"], 7.5)
        self.assertEqual(data["pool"][0]["first_seen"], "2026-08-20")
        self.assertEqual(data["pool"][0]["prev_rank"], 3)

    def test_write_never_raises_on_bad_input(self):
        with tempfile.TemporaryDirectory() as d:
            old_out, rs.OUT = rs.OUT, Path(d)
            try:
                rs.write_json_export(None, None)  # must not raise
                payload = json.loads((Path(d) / "papertrail.json").read_text())
                self.assertEqual(payload["schema"], 2)
                self.assertEqual(payload["daily"], [])
                self.assertEqual(payload["pool"], [])
            finally:
                rs.OUT = old_out

    def test_render_index_empty_state(self):
        page, n = rs.render_index({"date": "2026-08-23", "items": [],
                                   "empty_message": "Nothing worth your time today."})
        self.assertEqual(n, 0)
        self.assertIn("Nothing worth your time today", page)
        self.assertIn("/pool.html", page)

    def test_render_pool_movement_badge(self):
        page, n = rs.render_pool({"generated": "", "items": [{
            "title": "T", "url": "https://arxiv.org/abs/x", "score": 3, "value": 9.1,
            "first_seen": "2026-08-01", "prev_rank": 4, "rank": 1,
            "mentions": 2, "points": 30, "published": "2026-08-02"}]})
        self.assertEqual(n, 1)
        self.assertIn("▲ 4→1", page)


def _paper(link_id, title="T", abstract="x", published="2026-08-23"):
    return {"title": title, "abstract": abstract, "link":
            f"https://arxiv.org/abs/{link_id}", "published": published,
            "source": "arxiv"}


class SuppressionTest(unittest.TestCase):
    def setUp(self):
        self.papers = [_paper("2408.0001", "agentic tool use"),
                       _paper("2408.0002", "interpretability study")]

    def test_load_suppressed_ids_dict_shape(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"ids": [pt.item_id("https://arxiv.org/abs/2408.0001")]}, f)
        self.assertEqual(pt.load_suppressed_ids(f.name),
                         {pt.item_id("https://arxiv.org/abs/2408.0001")})

    def test_load_suppressed_ids_plain_list_shape(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(["aaa", "bbb"], f)
        self.assertEqual(pt.load_suppressed_ids(f.name), {"aaa", "bbb"})

    def test_missing_or_corrupt_file_means_no_suppression(self):
        self.assertEqual(pt.load_suppressed_ids("/nonexistent/suppressions.json"), set())
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
        self.assertEqual(pt.load_suppressed_ids(f.name), set())

    def test_suppression_filters_daily_feed(self):
        sup = {pt.item_id("https://arxiv.org/abs/2408.0001")}
        daily = pt.select_daily([p for p in self.papers
                                 if pt.item_id(p["link"]) not in sup],
                                today=date(2026, 8, 24))
        self.assertEqual([d["item_id"] for d in daily],
                         [pt.item_id("https://arxiv.org/abs/2408.0002")])

    def test_apply_suppression_reports_count(self):
        sup = {pt.item_id("https://arxiv.org/abs/2408.0001")}
        kept, n = pt.apply_suppression(self.papers, sup)
        self.assertEqual(n, 1)
        self.assertEqual(len(kept), 1)

    def test_pool_entries_skip_suppressed(self):
        state = {"entries": {}}
        sup = {pt.item_id("https://arxiv.org/abs/2408.0001")}
        candidates = [p for p in self.papers if pt.item_id(p["link"]) not in sup]
        pt.update_pool(state, candidates, today=date(2026, 8, 24),
                       signals_fn=lambda t: (0, 0))
        self.assertNotIn(pt.item_id("https://arxiv.org/abs/2408.0001"), state["entries"])
        self.assertIn(pt.item_id("https://arxiv.org/abs/2408.0002"), state["entries"])


class KeywordsConfigTest(unittest.TestCase):
    KW = {"agent": 9}

    def test_config_keywords_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"interests": {"keywords": self.KW}}, f)
        self.assertEqual(pt.load_keywords(f.name), self.KW)

    def test_fallback_when_config_missing(self):
        self.assertEqual(pt.load_keywords("/nonexistent/config.json"),
                         dict(pt.KEYWORDS))

    def test_fallback_when_config_corrupt(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{oops")
        self.assertEqual(pt.load_keywords(f.name), dict(pt.KEYWORDS))

    def test_fallback_when_interests_shape_bad(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"interests": {"keywords": ["not", "a", "dict"]}}, f)
        self.assertEqual(pt.load_keywords(f.name), dict(pt.KEYWORDS))

    def test_score_uses_active_keywords(self):
        old = pt._ACTIVE_KEYWORDS
        try:
            pt._ACTIVE_KEYWORDS = dict(self.KW)
            s, hits = pt.score({"title": "an agent paper", "abstract": ""})
            self.assertEqual(s, 9)
            self.assertEqual(hits, ["agent"])
        finally:
            pt._ACTIVE_KEYWORDS = old


if __name__ == "__main__":
    unittest.main()
