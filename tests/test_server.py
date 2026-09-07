import tempfile
import unittest
from unittest.mock import patch
import json
from datetime import datetime, timezone
from pathlib import Path

import server


def sample(item_id="one", title="OpenAI 发布智能体教程", url="https://example.com/post?utm_source=x", selected=True):
    return {
        "id": item_id,
        "title": title,
        "originalTitle": title,
        "summary": "这是一份 Agent 与 RAG 实践指南",
        "source": {"name": "OpenAI Blog"},
        "links": {"aihot": f"https://aihot.virxact.com/items/{item_id}", "original": url},
        "publishedAt": "2026-09-01T08:00:00Z",
        "discoveredAt": "2026-09-01T08:05:00Z",
        "category": "tip",
        "score": 80,
        "selected": selected,
        "reason": "值得阅读",
    }


class PersonalSourcesTests(unittest.TestCase):
    def test_category_access_denial_is_not_retried(self):
        error = server.urllib.error.HTTPError('https://www.producthunt.com/categories/productivity', 403, 'Forbidden', {}, None)
        with patch.object(server.urllib.request, 'urlopen', side_effect=error) as request, patch.object(server.time, 'sleep') as sleep:
            with self.assertRaises(server.ProductHuntAccessRestricted):
                server.fetch_producthunt_category_page('productivity', 1)
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()

    def test_category_access_denial_stops_queue_and_preserves_snapshot(self):
        with server.connect() as conn:
            conn.execute('INSERT INTO producthunt_category_snapshots VALUES(?,?,?,?,?,?)',
                ('productivity','Productivity','效率工具','2026-09-01T00:00:00Z','https://www.producthunt.com/categories/productivity',20))
        conn.close()
        with patch.object(server, 'NETWORK_WORKERS', 1), patch.object(server, 'fetch_producthunt_category_page', side_effect=server.ProductHuntAccessRestricted('HTTP 403: access restricted')) as fetch:
            with self.assertRaises(RuntimeError):
                server.sync_producthunt_categories(force=True)
            self.assertEqual(fetch.call_count, 1)
        with patch.object(server, 'NETWORK_ENABLED', False):
            result = server.query_producthunt({'category':['productivity']})
        self.assertEqual(result['snapshot']['fetched_at'], '2026-09-01T00:00:00Z')
        self.assertEqual(result['sourceStatus'], 'access-restricted')
        import gc
        gc.collect()

    def test_cache_mode_does_not_fetch_or_translate_on_page_reads(self):
        with patch.object(server, "NETWORK_ENABLED", False), \
             patch.object(server, "sync_xrank") as xrank, \
             patch.object(server, "sync_hacker_news") as hn, \
             patch.object(server, "ensure_hn_translations") as hn_translation, \
             patch.object(server, "ensure_producthunt_translations") as ph_translation:
            server.query_xrank({})
            server.query_hacker_news({})
            server.query_producthunt({})
            for operation in (xrank, hn, hn_translation, ph_translation):
                operation.assert_not_called()
            self.assertFalse(server.query_meta()["autoSync"]["enabled"])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = server.DB_PATH
        server.DB_PATH = Path(self.tempdir.name) / "test.db"
        server.init_db()

    def tearDown(self):
        server.DB_PATH = self.original_db
        self.tempdir.cleanup()

    def test_canonical_url_removes_tracking_only(self):
        self.assertEqual(server.canonical_url("https://WWW.Example.com/a/?utm_source=x&id=2#part"), "https://example.com/a?id=2")

    def test_auto_sync_interval_is_thirty_minutes(self):
        self.assertEqual(server.AUTO_SYNC_INTERVAL_SECONDS, 30 * 60)

    def test_local_taxonomy_keeps_multiple_dimensions(self):
        tags = server.classify(sample())
        self.assertIn("agent", tags["technology"])
        self.assertIn("rag", tags["technology"])
        self.assertIn("official", tags["form"])
        self.assertIn("openai", tags["entity"])

    def test_hard_duplicate_becomes_alias(self):
        first = server.upsert_content([sample()])
        second = server.upsert_content([sample(item_id="two", url="https://example.com/post")])
        meta = server.query_meta()["counts"]
        self.assertEqual(first["upserted"], 1)
        self.assertEqual(second["aliases"], 1)
        self.assertEqual(meta["content"], 1)
        self.assertEqual(meta["aliases"], 1)

    def test_cross_filter_is_and_between_dimensions(self):
        server.upsert_content([sample()])
        hit = server.query_content({"scope": ["selected"], "topic": ["agent"], "entity": ["openai"]})
        miss = server.query_content({"scope": ["selected"], "topic": ["embodied"], "entity": ["openai"]})
        self.assertEqual(hit["page"]["total"], 1)
        self.assertEqual(miss["page"]["total"], 0)

    def test_parse_github_trending_keeps_official_order_and_metadata(self):
        page = '''<article class="Box-row"><h2><a href="/openai/example">Example</a></h2>
        <p class="col-9 color-fg-muted">A useful &amp; small project</p>
        <span itemprop="programmingLanguage">Python</span>
        <a href="/openai/example/stargazers">1,234</a><a href="/openai/example/forks">56</a>
        <span class="d-inline-block float-sm-right">78 stars today</span></article>'''
        items = server.parse_github_trending(page)
        self.assertEqual(items[0]["rank"], 1)
        self.assertEqual(items[0]["full_name"], "openai/example")
        self.assertEqual(items[0]["description"], "A useful & small project")
        self.assertEqual(items[0]["stars_total"], 1234)
        self.assertEqual(items[0]["stars_today"], 78)

    def test_producthunt_parser_keeps_rank_icon_intro_and_link(self):
        payload = {"data": {"posts": {"edges": [{"node": {
            "id": "ph-1", "name": "Agent Desk", "tagline": "A calm home for agents",
            "description": "Longer description", "url": "https://www.producthunt.com/posts/agent-desk",
            "website": "https://example.com", "votesCount": 88, "commentsCount": 12,
            "createdAt": "2026-09-05T08:00:00Z", "featuredAt": "2026-09-05T08:00:00Z",
            "thumbnail": {"url": "https://ph-files.imgix.net/icon.png"},
            "topics": {"edges": [{"node": {"name": "Artificial Intelligence"}}]},
        }}]}}}
        items = server.parse_producthunt_posts(payload)
        self.assertEqual(items[0]["rank"], 1)
        self.assertEqual(items[0]["thumbnail_url"], "https://ph-files.imgix.net/icon.png")
        self.assertEqual(items[0]["tagline"], "A calm home for agents")
        self.assertEqual(items[0]["url"], "https://www.producthunt.com/posts/agent-desk")
        self.assertEqual(items[0]["topics"], ["Artificial Intelligence"])

    def test_producthunt_today_uses_pacific_day_boundary(self):
        after, before = server.producthunt_range_bounds(
            "today", datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(after, "2026-09-05T07:00:00Z")
        self.assertEqual(before, "2026-09-06T07:00:00Z")

    def test_producthunt_has_fourteen_official_primary_categories(self):
        self.assertEqual(len(server.PRODUCTHUNT_CATEGORIES), 14)
        self.assertIn(("ai-agents", "AI Agents", "AI 智能体"), server.PRODUCTHUNT_CATEGORIES)

    def test_producthunt_category_parser_reads_official_item_list(self):
        structured = {
            "@context": "https://schema.org",
            "mainEntity": {
                "@type": "ItemList",
                "itemListElement": [{
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Agent Desk",
                    "item": {
                        "@id": "https://www.producthunt.com/products/agent-desk",
                        "@type": ["WebApplication", "Product"],
                        "url": "https://www.producthunt.com/products/agent-desk",
                        "name": "Agent Desk",
                        "description": "A calm workspace for useful AI agents.",
                        "image": "https://ph-files.imgix.net/agent.png",
                        "aggregateRating": {"ratingValue": 4.9, "reviewCount": 12},
                    },
                }],
            },
        }
        page = f'<script type="application/ld+json">{json.dumps(structured)}</script>'
        items = server.parse_producthunt_category_page(page)
        self.assertEqual(items[0]["id"], "product:agent-desk")
        self.assertEqual(items[0]["name"], "Agent Desk")
        self.assertEqual(items[0]["reviews_count"], 12)
        self.assertEqual(items[0]["thumbnail_url"], "https://ph-files.imgix.net/agent.png")

    def flight_page(self, payload):
        return f'<script>self.__next_f.push({json.dumps([1, payload], ensure_ascii=False)})</script>'

    def test_xrank_tweets_combines_both_ai_boards(self):
        payload = '6:{"risingTweets":[{"id":"1","text":"Agent news"}],"hotTweets":[{"id":"2","text":"LLM news"}]}'
        items = server.parse_xrank_page("tweets", self.flight_page(payload))
        self.assertEqual([item["_board"] for item in items], ["rising", "hot"])
        self.assertEqual([item["_rank"] for item in items], [1, 2])

    def test_xrank_uses_sopilot_ai_category_for_creators_and_topics(self):
        creators = {"accounts": [
            {"accountId": "1", "screenName": "ai", "category": "AI"},
            {"accountId": "2", "screenName": "web3", "category": "Web3"},
        ]}
        payload = f'6:{{"initialData":{json.dumps(creators)}}}'
        items = server.parse_xrank_page("creators", self.flight_page(payload))
        self.assertEqual([item["screenName"] for item in items], ["ai"])

    def test_xrank_reads_total_pages_and_builds_page_url(self):
        payload = '6:{"initialData":{"totalPages":4,"accounts":[]}}'
        self.assertEqual(server.xrank_total_pages("creators", self.flight_page(payload)), 4)
        self.assertIn("page=3", server.sopilot_url("creators", "7d", 3))

    def test_hn_ai_classification_is_conservative(self):
        self.assertTrue(server.is_hn_ai_item({"title": "Can AI design circuit boards yet?"}))
        self.assertTrue(server.is_hn_ai_item({"title": "Formalizing Fermat", "url": "https://anthropic.com/research/fermat"}))
        self.assertFalse(server.is_hn_ai_item({"title": "Open-Source eInk Bike Computer", "text": "Built for cyclists"}))

    def test_hn_feed_keeps_official_order_and_metadata(self):
        source = {
            22: {"id": 22, "type": "story", "title": "Show HN: Agent tool", "by": "maker", "score": 8, "descendants": 3, "time": 100, "url": "https://example.com/tool"},
            11: {"id": 11, "type": "story", "title": "A regular story", "by": "writer", "score": 5, "time": 90, "url": "https://example.org/post"},
        }
        items = server.build_hn_feed_items("new", [22, 11], source)
        self.assertEqual([item["item_id"] for item in items], [22, 11])
        self.assertEqual([item["rank"] for item in items], [1, 2])
        self.assertTrue(items[0]["is_ai"])
        self.assertEqual(items[0]["comments"], 3)

    def test_hn_description_excerpt_is_bounded_at_word_boundary(self):
        source = "A local-first AI assistant " * 80
        excerpt = server.hn_text_excerpt(source, 100)
        self.assertLessEqual(len(excerpt), 101)
        self.assertTrue(excerpt.endswith("…"))
        self.assertEqual(server.hn_text_excerpt("https://example.com/story"), "")

    def test_hn_translation_polishes_ai_terminology(self):
        result = server.polish_hn_translation(
            "Discovery of a new OpenAI agent message board",
            "发现新的 OpenAI 代理留言板",
        )
        self.assertEqual(result, "发现新的 OpenAI 智能体留言板")


if __name__ == "__main__":
    unittest.main()
