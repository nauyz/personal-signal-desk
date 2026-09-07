from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
DB_PATH = DATA / "personal_sources.db"
API_ROOT = "https://aihot.virxact.com/api/v1"
GITHUB_TRENDING_URL = "https://github.com/trending"
SOPILOT_ROOT = "https://sopilot.net"
HN_API_ROOT = "https://hacker-news.firebaseio.com/v0"
PRODUCTHUNT_API_ROOT = "https://api.producthunt.com/v2/api/graphql"
PRODUCTHUNT_SOURCE_URL = "https://www.producthunt.com/"
USER_AGENT = "PersonalSources/0.1 (+local personal dashboard)"
AUTO_SYNC_INTERVAL_SECONDS = 30 * 60
NETWORK_ENABLED = False
NETWORK_WORKERS = 2

PRODUCTHUNT_RANGES = {"today", "yesterday", "7d", "30d"}
PRODUCTHUNT_CATEGORY_REFRESH_SECONDS = 6 * 60 * 60
PRODUCTHUNT_CATEGORIES = (
    ("productivity", "Productivity", "效率工具"),
    ("engineering-development", "Engineering & Development", "工程与开发"),
    ("design-creative", "Design & Creative", "设计与创意"),
    ("finance", "Finance", "金融"),
    ("social-community", "Social & Community", "社交与社区"),
    ("marketing-sales", "Marketing & Sales", "营销与销售"),
    ("health-fitness", "Health & Fitness", "健康与健身"),
    ("travel", "Travel", "旅行"),
    ("platforms", "Platforms", "平台"),
    ("product-add-ons", "Product add-ons", "产品扩展"),
    ("physical-products", "Physical Products", "实体产品"),
    ("web3", "Web3", "Web3"),
    ("llms", "LLMs", "大语言模型"),
    ("ai-agents", "AI Agents", "AI 智能体"),
)
PRODUCTHUNT_CATEGORY_KEYS = {item[0] for item in PRODUCTHUNT_CATEGORIES}


def producthunt_token() -> str:
    token = (os.environ.get("PRODUCTHUNT_TOKEN") or "").strip()
    if token or os.name != "nt":
        return token
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "PRODUCTHUNT_TOKEN")
        return str(value or "").strip()
    except (FileNotFoundError, OSError):
        return ""

HN_FEEDS = {
    "news": ("topstories", 30, "https://news.ycombinator.com/news"),
    "new": ("newstories", 30, "https://news.ycombinator.com/newest"),
    "show": ("showstories", 30, "https://news.ycombinator.com/show"),
    "ask": ("askstories", 30, "https://news.ycombinator.com/ask"),
}

XRANK_RANGES = {
    "tweets": {"6h", "24h", "7d"},
    "creators": {"today", "yesterday", "7d", "30d"},
    "topics": {"24h", "7d", "all"},
}
XRANK_DEFAULTS = {"tweets": "24h", "creators": "7d", "topics": "7d"}

CATEGORY_LABELS = {
    "ai-models": "模型",
    "ai-products": "产品",
    "industry": "行业",
    "paper": "论文",
    "tip": "教程",
    "tutorial": "教程",
    "opinion": "观点",
}

TAXONOMY: dict[str, dict[str, list[str]]] = {
    "technology": {
        "agent": ["agent", "agentic", "智能体", "代理", "mcp", "harness", "computer use", "code agent"],
        "multimodal": ["multimodal", "多模态", "视觉", "图像", "视频生成", "语音", "audio", "vision"],
        "rag": ["rag", "retrieval", "检索增强", "向量数据库", "embedding"],
        "data-training": ["training", "训练", "微调", "fine-tun", "dataset", "数据集", "蒸馏"],
        "safety": ["safety", "安全", "对齐", "alignment", "越狱", "红队", "system card"],
        "embodied": ["robot", "机器人", "具身", "自动驾驶"],
    },
    "form": {
        "official": ["official", "官方", "发布", "introducing", "announce", "blog", "system card"],
        "news": ["news", "新闻", "报道", "the verge", "techcrunch", "ithome", "it之家"],
        "research": ["paper", "论文", "研究", "arxiv", "benchmark", "评测"],
        "tutorial": ["tutorial", "教程", "指南", "how to", "实践", "入门", "guide"],
        "opinion": ["观点", "评论", "认为", "解读", "分析", "thought", "opinion"],
        "benchmark": ["benchmark", "评测", "榜单", "leaderboard", "arena"],
        "video": ["youtube", "视频", "bilibili", "b站"],
        "podcast": ["podcast", "播客", "小宇宙"],
        "repository": ["github.com", "开源", "repository", "repo", "代码仓库"],
    },
    "entity": {
        "openai": ["openai", "chatgpt"],
        "anthropic": ["anthropic", "claude"],
        "google": ["google", "deepmind", "gemini"],
        "meta": ["meta ", "llama", "facebook"],
        "microsoft": ["microsoft", "微软", "copilot"],
        "nvidia": ["nvidia", "英伟达"],
        "gpt": ["gpt-", " gpt", "chatgpt"],
        "claude": ["claude"],
        "gemini": ["gemini"],
        "qwen": ["qwen", "通义千问"],
    },
}

TAXONOMY_LABELS = {
    "technology": {"agent": "智能体", "multimodal": "多模态", "rag": "RAG", "data-training": "数据与训练", "safety": "安全与对齐", "embodied": "具身智能", "other": "其他"},
    "form": {"official": "官方发布", "news": "新闻报道", "research": "论文研究", "tutorial": "教程实践", "opinion": "观点评论", "benchmark": "评测基准", "video": "视频", "podcast": "播客", "repository": "开源仓库", "other": "其他"},
    "entity": {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "meta": "Meta", "microsoft": "Microsoft", "nvidia": "NVIDIA", "gpt": "GPT", "claude": "Claude", "gemini": "Gemini", "qwen": "Qwen", "other": "其他"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source", "spm"}]
        host = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.rstrip("/") or "/"
        return urllib.parse.urlunsplit((parsed.scheme.lower() or "https", host, path, urllib.parse.urlencode(query), ""))
    except ValueError:
        return value


def platform_id(value: str | None) -> str:
    if not value:
        return ""
    patterns = [
        (r"(?:x|twitter)\.com/[^/]+/status/(\d+)", "x"),
        (r"youtube\.com/watch\?v=([^&]+)", "youtube"),
        (r"youtu\.be/([^?]+)", "youtube"),
        (r"bilibili\.com/video/([^/?]+)", "bilibili"),
    ]
    for pattern, platform in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            return f"{platform}:{match.group(1)}"
    return ""


def fingerprint(item: dict[str, Any]) -> str:
    basis = normalize_text(item.get("title")) + "\n" + normalize_text(item.get("summary"))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest() if basis.strip() else ""


def classify(item: dict[str, Any]) -> dict[str, list[str]]:
    links = item.get("links") or {}
    source = item.get("source") or {}
    haystack = normalize_text(" ".join(str(x or "") for x in [item.get("title"), item.get("originalTitle"), item.get("summary"), source.get("name"), links.get("original")]))
    result: dict[str, list[str]] = {}
    for dimension, groups in TAXONOMY.items():
        matches = [slug for slug, words in groups.items() if any(normalize_text(word) in haystack for word in words)]
        result[dimension] = matches or ["other"]
    return result


def local_category(item: dict[str, Any], tags: dict[str, list[str]]) -> str:
    original = item.get("category") or "other"
    if original != "tip":
        return original
    if "opinion" in tags["form"] and "tutorial" not in tags["form"]:
        return "opinion"
    return "tutorial"


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS content_items (
      id INTEGER PRIMARY KEY, aihot_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
      original_title TEXT, summary TEXT, source_name TEXT, original_url TEXT,
      canonical_url TEXT, platform_id TEXT, aihot_url TEXT, published_at TEXT,
      discovered_at TEXT, category TEXT, original_category TEXT, score REAL,
      selected INTEGER NOT NULL DEFAULT 0, reason TEXT, content_fingerprint TEXT,
      raw_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_content_selected ON content_items(selected);
    CREATE INDEX IF NOT EXISTS idx_content_published ON content_items(published_at DESC);
    CREATE INDEX IF NOT EXISTS idx_content_canonical ON content_items(canonical_url);
    CREATE INDEX IF NOT EXISTS idx_content_fingerprint ON content_items(content_fingerprint);
    CREATE TABLE IF NOT EXISTS content_aliases (
      id INTEGER PRIMARY KEY, content_id INTEGER NOT NULL REFERENCES content_items(id),
      aihot_id TEXT NOT NULL UNIQUE, source_name TEXT, original_url TEXT,
      discovered_at TEXT, reason TEXT NOT NULL, raw_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS taxonomy_tags (
      id INTEGER PRIMARY KEY, dimension TEXT NOT NULL, slug TEXT NOT NULL,
      label TEXT NOT NULL, UNIQUE(dimension, slug)
    );
    CREATE TABLE IF NOT EXISTS content_tag_links (
      content_id INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
      tag_id INTEGER NOT NULL REFERENCES taxonomy_tags(id) ON DELETE CASCADE,
      PRIMARY KEY(content_id, tag_id)
    );
    CREATE TABLE IF NOT EXISTS fact_items (
      id INTEGER PRIMARY KEY, aihot_story_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
      status TEXT, rank INTEGER, representative_source TEXT, source_count INTEGER,
      signal_count INTEGER, latest_at TEXT, digest TEXT, story_url TEXT,
      original_url TEXT, in_current INTEGER NOT NULL DEFAULT 1,
      raw_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS daily_reports (
      date TEXT PRIMARY KEY, window_start TEXT, window_end TEXT, generated_at TEXT,
      aihot_url TEXT, raw_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS github_trending_snapshots (
      date TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL,
      item_count INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS github_trending_items (
      snapshot_date TEXT NOT NULL REFERENCES github_trending_snapshots(date) ON DELETE CASCADE,
      rank INTEGER NOT NULL, full_name TEXT NOT NULL, owner TEXT NOT NULL, repo_name TEXT NOT NULL,
      description TEXT, language TEXT, stars_total INTEGER, forks_total INTEGER,
      stars_today INTEGER, repo_url TEXT NOT NULL,
      PRIMARY KEY(snapshot_date, full_name)
    );
    CREATE INDEX IF NOT EXISTS idx_github_trending_rank ON github_trending_items(snapshot_date, rank);
    CREATE TABLE IF NOT EXISTS producthunt_snapshots (
      range_key TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL,
      window_start TEXT NOT NULL, window_end TEXT NOT NULL, item_count INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS producthunt_items (
      range_key TEXT NOT NULL REFERENCES producthunt_snapshots(range_key) ON DELETE CASCADE,
      rank INTEGER NOT NULL, post_id TEXT NOT NULL, raw_json TEXT NOT NULL,
      PRIMARY KEY(range_key, post_id)
    );
    CREATE INDEX IF NOT EXISTS idx_producthunt_items_rank ON producthunt_items(range_key, rank);
    CREATE TABLE IF NOT EXISTS producthunt_translations (
      post_id TEXT PRIMARY KEY, tagline_source TEXT NOT NULL, tagline_zh TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS producthunt_category_snapshots (
      category_key TEXT PRIMARY KEY, label TEXT NOT NULL, label_zh TEXT NOT NULL,
      fetched_at TEXT NOT NULL, source_url TEXT NOT NULL, item_count INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS producthunt_category_items (
      category_key TEXT NOT NULL REFERENCES producthunt_category_snapshots(category_key) ON DELETE CASCADE,
      rank INTEGER NOT NULL, product_id TEXT NOT NULL, raw_json TEXT NOT NULL,
      PRIMARY KEY(category_key, product_id)
    );
    CREATE INDEX IF NOT EXISTS idx_producthunt_category_rank
      ON producthunt_category_items(category_key, rank);
    CREATE TABLE IF NOT EXISTS xrank_snapshots (
      kind TEXT NOT NULL, range_key TEXT NOT NULL, fetched_at TEXT NOT NULL,
      source_url TEXT NOT NULL, item_count INTEGER NOT NULL,
      PRIMARY KEY(kind, range_key)
    );
    CREATE TABLE IF NOT EXISTS xrank_items (
      kind TEXT NOT NULL, range_key TEXT NOT NULL, rank INTEGER NOT NULL,
      item_id TEXT NOT NULL, raw_json TEXT NOT NULL,
      PRIMARY KEY(kind, range_key, item_id)
    );
    CREATE INDEX IF NOT EXISTS idx_xrank_items_rank ON xrank_items(kind, range_key, rank);
    CREATE TABLE IF NOT EXISTS hn_snapshots (
      feed TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL,
      item_count INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS hn_items (
      feed TEXT NOT NULL REFERENCES hn_snapshots(feed) ON DELETE CASCADE,
      rank INTEGER NOT NULL, item_id INTEGER NOT NULL, title TEXT NOT NULL,
      url TEXT, hn_url TEXT NOT NULL, author TEXT, score INTEGER,
      comments INTEGER, published_at TEXT, source_domain TEXT,
      is_ai INTEGER NOT NULL DEFAULT 0, text TEXT, raw_json TEXT NOT NULL,
      PRIMARY KEY(feed, item_id)
    );
    CREATE INDEX IF NOT EXISTS idx_hn_items_feed_rank ON hn_items(feed, rank);
    CREATE INDEX IF NOT EXISTS idx_hn_items_feed_ai ON hn_items(feed, is_ai, rank);
    CREATE TABLE IF NOT EXISTS hn_translations (
      item_id INTEGER PRIMARY KEY, title_source TEXT NOT NULL, title_zh TEXT NOT NULL,
      text_source TEXT, text_zh TEXT, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sync_state (
      resource TEXT PRIMARY KEY, etag TEXT, last_synced_at TEXT, last_status TEXT,
      last_error TEXT
    );
    """
    with connect() as conn:
        conn.executescript(schema)
        for dimension, labels in TAXONOMY_LABELS.items():
            for slug, label in labels.items():
                conn.execute("INSERT OR IGNORE INTO taxonomy_tags(dimension,slug,label) VALUES(?,?,?)", (dimension, slug, label))


class AIHotClient:
    def __init__(self) -> None:
        self.timeout = 25

    def get(self, path: str, resource: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        query = urllib.parse.urlencode(params or {})
        url = f"{API_ROOT}{path}" + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        with connect() as conn:
            row = conn.execute("SELECT etag FROM sync_state WHERE resource=?", (resource,)).fetchone()
            if row and row["etag"]:
                headers["If-None-Match"] = row["etag"]
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                etag = response.headers.get("ETag")
                self._state(resource, etag, "ok", None)
                return payload
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                self._state(resource, headers.get("If-None-Match"), "not-modified", None)
                return None
            retry_after = exc.headers.get("Retry-After")
            message = f"HTTP {exc.code}" + (f", Retry-After {retry_after}s" if retry_after else "")
            self._state(resource, None, "error", message)
            raise RuntimeError(message) from exc
        except Exception as exc:
            self._state(resource, None, "error", str(exc))
            raise

    @staticmethod
    def _state(resource: str, etag: str | None, status: str, error: str | None) -> None:
        with connect() as conn:
            conn.execute("""
              INSERT INTO sync_state(resource,etag,last_synced_at,last_status,last_error)
              VALUES(?,?,?,?,?) ON CONFLICT(resource) DO UPDATE SET
              etag=COALESCE(excluded.etag,sync_state.etag), last_synced_at=excluded.last_synced_at,
              last_status=excluded.last_status, last_error=excluded.last_error
            """, (resource, etag, utc_now(), status, error))


def find_duplicate(conn: sqlite3.Connection, item: dict[str, Any], canon: str, pid: str, fp: str) -> tuple[int, str] | None:
    checks = [
        ("aihot_id", item.get("id"), "相同 AIHOT id"),
        ("canonical_url", canon, "相同规范化 URL"),
        ("platform_id", pid, "相同平台内容 id"),
        ("content_fingerprint", fp, "相同标题与摘要指纹"),
    ]
    for column, value, reason in checks:
        if not value:
            continue
        row = conn.execute(f"SELECT id,aihot_id FROM content_items WHERE {column}=? LIMIT 1", (value,)).fetchone()
        if row:
            if column == "aihot_id":
                return row["id"], "update"
            return row["id"], reason
    return None


def upsert_content(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"upserted": 0, "aliases": 0}
    now = utc_now()
    with connect() as conn:
        for item in items:
            tags = classify(item)
            category = local_category(item, tags)
            links, source = item.get("links") or {}, item.get("source") or {}
            canon = canonical_url(links.get("original"))
            pid, fp = platform_id(links.get("original")), fingerprint(item)
            duplicate = find_duplicate(conn, item, canon, pid, fp)
            raw = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            if duplicate and duplicate[1] != "update":
                conn.execute("""
                  INSERT OR IGNORE INTO content_aliases(content_id,aihot_id,source_name,original_url,discovered_at,reason,raw_json)
                  VALUES(?,?,?,?,?,?,?)
                """, (duplicate[0], item.get("id"), source.get("name"), links.get("original"), item.get("discoveredAt"), duplicate[1], raw))
                counts["aliases"] += 1
                continue
            conn.execute("""
              INSERT INTO content_items(aihot_id,title,original_title,summary,source_name,original_url,canonical_url,
                platform_id,aihot_url,published_at,discovered_at,category,original_category,score,selected,reason,
                content_fingerprint,raw_json,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(aihot_id) DO UPDATE SET title=excluded.title,original_title=excluded.original_title,
                summary=excluded.summary,source_name=excluded.source_name,original_url=excluded.original_url,
                canonical_url=excluded.canonical_url,platform_id=excluded.platform_id,aihot_url=excluded.aihot_url,
                published_at=excluded.published_at,discovered_at=excluded.discovered_at,category=excluded.category,
                original_category=excluded.original_category,score=excluded.score,selected=excluded.selected,
                reason=excluded.reason,content_fingerprint=excluded.content_fingerprint,raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """, (item.get("id"), item.get("title") or "无标题", item.get("originalTitle"), item.get("summary"),
                  source.get("name"), links.get("original"), canon, pid, links.get("aihot"), item.get("publishedAt"),
                  item.get("discoveredAt"), category, item.get("category"), item.get("score"), int(bool(item.get("selected"))),
                  item.get("reason"), fp, raw, now, now))
            content_id = conn.execute("SELECT id FROM content_items WHERE aihot_id=?", (item.get("id"),)).fetchone()["id"]
            conn.execute("DELETE FROM content_tag_links WHERE content_id=?", (content_id,))
            for dimension, slugs in tags.items():
                for slug in slugs:
                    tag = conn.execute("SELECT id FROM taxonomy_tags WHERE dimension=? AND slug=?", (dimension, slug)).fetchone()
                    if tag:
                        conn.execute("INSERT OR IGNORE INTO content_tag_links(content_id,tag_id) VALUES(?,?)", (content_id, tag["id"]))
            counts["upserted"] += 1
    return counts


def upsert_facts(payload: dict[str, Any], client: AIHotClient) -> int:
    topics = payload.get("items") or []
    now = utc_now()
    enriched: list[tuple[dict[str, Any], str, str | None, dict[str, Any]]] = []
    # Network requests and their sync-state writes must happen before opening the
    # fact-table transaction, otherwise SQLite correctly rejects the nested writer.
    for topic in topics:
        story_url = (topic.get("links") or {}).get("story")
        public_id = story_url.rstrip("/").split("/")[-1] if story_url else topic.get("id")
        story: dict[str, Any] = {}
        if story_url:
            try:
                story_payload = client.get(f"/stories/{public_id}", f"story:{public_id}")
                story = (story_payload or {}).get("story") or {}
            except Exception:
                story = {}
        enriched.append((topic, public_id, story_url, story))
    with connect() as conn:
        conn.execute("UPDATE fact_items SET in_current=0")
        for topic, public_id, story_url, story in enriched:
            links, source = topic.get("links") or {}, topic.get("source") or {}
            raw = json.dumps({"topic": topic, "story": story}, ensure_ascii=False, separators=(",", ":"))
            conn.execute("""
              INSERT INTO fact_items(aihot_story_id,title,status,rank,representative_source,source_count,signal_count,
                latest_at,digest,story_url,original_url,in_current,raw_json,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(aihot_story_id) DO UPDATE SET
                title=excluded.title,status=excluded.status,rank=excluded.rank,representative_source=excluded.representative_source,
                source_count=excluded.source_count,signal_count=excluded.signal_count,latest_at=excluded.latest_at,
                digest=excluded.digest,story_url=excluded.story_url,original_url=excluded.original_url,in_current=1,
                raw_json=excluded.raw_json,updated_at=excluded.updated_at
            """, (public_id, topic.get("title"), story.get("status"), topic.get("rank"), source.get("name"),
                  topic.get("sourceCount"), topic.get("signalCount"), topic.get("latestAt"), story.get("digest"),
                  story_url or links.get("aihot"), links.get("original"), 1, raw, now, now))
    return len(topics)


def upsert_daily(payload: dict[str, Any]) -> bool:
    report = payload.get("report")
    if not report:
        return False
    now = utc_now()
    links = report.get("links") or {}
    with connect() as conn:
        conn.execute("""
          INSERT INTO daily_reports(date,window_start,window_end,generated_at,aihot_url,raw_json,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET window_start=excluded.window_start,
            window_end=excluded.window_end,generated_at=excluded.generated_at,aihot_url=excluded.aihot_url,
            raw_json=excluded.raw_json,updated_at=excluded.updated_at
        """, (report.get("date"), report.get("windowStart"), report.get("windowEnd"), report.get("generatedAt"),
              links.get("aihot"), json.dumps(report, ensure_ascii=False, separators=(",", ":")), now, now))
    return True


def text_from_html(fragment: str | None) -> str:
    if not fragment:
        return ""
    value = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def number_from_html(fragment: str | None) -> int | None:
    match = re.search(r"[\d,]+", text_from_html(fragment))
    return int(match.group(0).replace(",", "")) if match else None


def parse_github_trending(page: str) -> list[dict[str, Any]]:
    articles = re.findall(r'<article\b[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>', page, re.S | re.I)
    items: list[dict[str, Any]] = []
    for article in articles:
        heading = re.search(r"<h2\b.*?</h2>", article, re.S | re.I)
        repo = re.search(r'href="(/([^/\"?#]+)/([^/\"?#]+))"', heading.group(0) if heading else "", re.I)
        if not repo:
            continue
        path, owner, repo_name = repo.groups()
        description = re.search(r'<p\b[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', article, re.S | re.I)
        language = re.search(r'itemprop="programmingLanguage"[^>]*>(.*?)</span>', article, re.S | re.I)
        stars = re.search(r'href="[^"]+/stargazers"[^>]*>(.*?)</a>', article, re.S | re.I)
        forks = re.search(r'href="[^"]+/forks"[^>]*>(.*?)</a>', article, re.S | re.I)
        today = re.search(r'([\d,]+)\s+stars?\s+today', text_from_html(article), re.I)
        items.append({
            "rank": len(items) + 1,
            "full_name": f"{owner}/{repo_name}",
            "owner": owner,
            "repo_name": repo_name,
            "description": text_from_html(description.group(1) if description else ""),
            "language": text_from_html(language.group(1) if language else "") or None,
            "stars_total": number_from_html(stars.group(1) if stars else None),
            "forks_total": number_from_html(forks.group(1) if forks else None),
            "stars_today": int(today.group(1).replace(",", "")) if today else None,
            "repo_url": urllib.parse.urljoin("https://github.com", path),
        })
    if not items:
        raise RuntimeError("GitHub Trending 页面中没有解析到项目")
    return items


def sync_github_trending() -> int:
    headers = {"Accept": "text/html", "User-Agent": USER_AGENT}
    request = urllib.request.Request(GITHUB_TRENDING_URL, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            page = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        items = parse_github_trending(page)
        snapshot_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        fetched_at = utc_now()
        with connect() as conn:
            conn.execute("""
              INSERT INTO github_trending_snapshots(date,fetched_at,source_url,item_count)
              VALUES(?,?,?,?) ON CONFLICT(date) DO UPDATE SET
              fetched_at=excluded.fetched_at,source_url=excluded.source_url,item_count=excluded.item_count
            """, (snapshot_date, fetched_at, GITHUB_TRENDING_URL, len(items)))
            conn.execute("DELETE FROM github_trending_items WHERE snapshot_date=?", (snapshot_date,))
            conn.executemany("""
              INSERT INTO github_trending_items(snapshot_date,rank,full_name,owner,repo_name,description,
                language,stars_total,forks_total,stars_today,repo_url)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, [(snapshot_date, item["rank"], item["full_name"], item["owner"], item["repo_name"],
                    item["description"], item["language"], item["stars_total"], item["forks_total"],
                    item["stars_today"], item["repo_url"]) for item in items])
        AIHotClient._state("github:trending", None, "ok", None)
        return len(items)
    except Exception as exc:
        AIHotClient._state("github:trending", None, "error", str(exc))
        raise


def producthunt_range_bounds(range_key: str, now: datetime | None = None) -> tuple[str, str]:
    if range_key not in PRODUCTHUNT_RANGES:
        raise ValueError("不支持的 Product Hunt 时间范围")
    current = now or datetime.now(timezone.utc)
    local = current.astimezone(ZoneInfo("America/Los_Angeles"))
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "today":
        start, end = today, today + timedelta(days=1)
    elif range_key == "yesterday":
        start, end = today - timedelta(days=1), today
    elif range_key == "7d":
        start, end = today - timedelta(days=6), today + timedelta(days=1)
    else:
        start, end = today - timedelta(days=29), today + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def parse_producthunt_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors = payload.get("errors") or []
    if errors:
        raise RuntimeError(str(errors[0].get("message") or "Product Hunt GraphQL 查询失败"))
    edges = (((payload.get("data") or {}).get("posts") or {}).get("edges") or [])
    items: list[dict[str, Any]] = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        post_id = str(node.get("id") or "").strip()
        name = str(node.get("name") or "").strip()
        if not post_id or not name:
            continue
        thumbnail = node.get("thumbnail") or {}
        topics = [
            str(((topic_edge or {}).get("node") or {}).get("name") or "").strip()
            for topic_edge in (((node.get("topics") or {}).get("edges")) or [])
        ]
        item = {
            "id": post_id,
            "rank": len(items) + 1,
            "name": name,
            "tagline": str(node.get("tagline") or "").strip(),
            "description": str(node.get("description") or "").strip(),
            "thumbnail_url": str(thumbnail.get("url") or "").strip(),
            "url": str(node.get("url") or "").strip(),
            "website": str(node.get("website") or "").strip(),
            "votes_count": node.get("votesCount"),
            "comments_count": node.get("commentsCount"),
            "created_at": node.get("createdAt"),
            "featured_at": node.get("featuredAt"),
            "topics": [topic for topic in topics if topic],
        }
        items.append(item)
    return items


def fetch_producthunt_range(range_key: str, token: str | None = None) -> tuple[list[dict[str, Any]], str, str]:
    access_token = (token or producthunt_token()).strip()
    if not access_token:
        raise RuntimeError("未配置 PRODUCTHUNT_TOKEN")
    window_start, window_end = producthunt_range_bounds(range_key)
    query = """
      query ProductHuntLaunches($after: DateTime!, $before: DateTime!) {
        posts(first: 20, featured: true, order: RANKING, postedAfter: $after, postedBefore: $before) {
          edges { node {
            id name tagline description url website votesCount commentsCount createdAt featuredAt
            thumbnail { url(width: 128, height: 128) }
            topics(first: 4) { edges { node { name } } }
          } }
        }
      }
    """
    body = json.dumps({"query": query, "variables": {"after": window_start, "before": window_end}}).encode("utf-8")
    request = urllib.request.Request(PRODUCTHUNT_API_ROOT, data=body, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Product Hunt API HTTP {exc.code}") from exc
    return parse_producthunt_posts(payload), window_start, window_end


def sync_producthunt(ranges=("today", "yesterday", "7d", "30d")) -> dict[str, int]:
    counts: dict[str, int] = {}
    for range_key in ranges:
        resource = f"producthunt:{range_key}"
        try:
            items, window_start, window_end = fetch_producthunt_range(range_key)
            fetched_at = utc_now()
            with connect() as conn:
                conn.execute("""
                  INSERT INTO producthunt_snapshots(range_key,fetched_at,source_url,window_start,window_end,item_count)
                  VALUES(?,?,?,?,?,?) ON CONFLICT(range_key) DO UPDATE SET
                  fetched_at=excluded.fetched_at,source_url=excluded.source_url,
                  window_start=excluded.window_start,window_end=excluded.window_end,item_count=excluded.item_count
                """, (range_key, fetched_at, PRODUCTHUNT_SOURCE_URL, window_start, window_end, len(items)))
                conn.execute("DELETE FROM producthunt_items WHERE range_key=?", (range_key,))
                conn.executemany(
                    "INSERT INTO producthunt_items(range_key,rank,post_id,raw_json) VALUES(?,?,?,?)",
                    [(range_key, item["rank"], item["id"], json.dumps(item, ensure_ascii=False, separators=(",", ":"))) for item in items],
                )
            AIHotClient._state(resource, None, "ok", None)
            counts[range_key] = len(items)
        except Exception as exc:
            AIHotClient._state(resource, None, "error", str(exc))
            raise
    return counts


def producthunt_category_url(category_key: str, page: int = 1) -> str:
    if category_key not in PRODUCTHUNT_CATEGORY_KEYS:
        raise ValueError("不支持的 Product Hunt 一级分类")
    base = f"{PRODUCTHUNT_SOURCE_URL.rstrip('/')}/categories/{category_key}"
    return base if page <= 1 else f"{base}?page={page}"


def producthunt_description_excerpt(value: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped or text[:limit]}…"


def parse_producthunt_category_page(page: str) -> list[dict[str, Any]]:
    scripts = re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        re.S | re.I,
    )
    elements: list[dict[str, Any]] = []
    for script in scripts:
        try:
            payload = json.loads(html.unescape(script))
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            listing = candidate.get("mainEntity") if isinstance(candidate.get("mainEntity"), dict) else candidate
            if listing.get("@type") == "ItemList" and isinstance(listing.get("itemListElement"), list):
                elements = listing["itemListElement"]
                break
        if elements:
            break
    if not elements:
        raise RuntimeError("Product Hunt 分类页中没有找到产品列表")

    items: list[dict[str, Any]] = []
    for element in elements:
        product = (element or {}).get("item") or {}
        name = str(product.get("name") or element.get("name") or "").strip()
        url = str(product.get("url") or product.get("@id") or "").strip()
        if not name or not url:
            continue
        slug = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
        image = product.get("image")
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl")
        elif isinstance(image, list):
            image = next((entry.get("url") if isinstance(entry, dict) else entry for entry in image if entry), "")
        rating = product.get("aggregateRating") or {}
        description = re.sub(r"\s+", " ", str(product.get("description") or "")).strip()
        items.append({
            "id": f"product:{slug}",
            "rank": len(items) + 1,
            "name": name,
            "tagline": producthunt_description_excerpt(description),
            "description": description,
            "thumbnail_url": str(image or "").strip(),
            "url": url,
            "website": "",
            "votes_count": None,
            "comments_count": None,
            "reviews_count": rating.get("reviewCount") or rating.get("ratingCount"),
            "reviews_rating": rating.get("ratingValue"),
            "created_at": product.get("datePublished"),
            "featured_at": None,
            "topics": [],
        })
    return items


def fetch_producthunt_category_page(category_key: str, page: int, attempts: int = 3) -> str:
    url = producthunt_category_url(category_key, page)
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={
            "Accept": "text/html",
            "Connection": "close",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"Product Hunt 分类页读取失败：{url}: {last_error}")


def producthunt_category_is_fresh(category_key: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT fetched_at,item_count FROM producthunt_category_snapshots WHERE category_key=?",
            (category_key,),
        ).fetchone()
    if not row or int(row["item_count"] or 0) < 20:
        return False
    try:
        fetched = datetime.fromisoformat(str(row["fetched_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - fetched).total_seconds() < PRODUCTHUNT_CATEGORY_REFRESH_SECONDS


def sync_producthunt_categories(force: bool = False) -> dict[str, int]:
    pending = [entry for entry in PRODUCTHUNT_CATEGORIES if force or not producthunt_category_is_fresh(entry[0])]
    if not pending:
        with connect() as conn:
            return {
                row["category_key"]: row["item_count"]
                for row in conn.execute("SELECT category_key,item_count FROM producthunt_category_snapshots")
            }

    def fetch_category(entry: tuple[str, str, str]) -> tuple[tuple[str, str, str], list[dict[str, Any]]]:
        key, _, _ = entry
        pages = [fetch_producthunt_category_page(key, page_number) for page_number in (1, 2)]
        parsed = [item for page_html in pages for item in parse_producthunt_category_page(page_html)]
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in parsed:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append({**item, "rank": len(items) + 1, "topics": [entry[1]]})
            if len(items) == 20:
                break
        if len(items) < 20:
            raise RuntimeError(f"{entry[1]} 分类只解析到 {len(items)} 个产品")
        return entry, items

    completed: list[tuple[tuple[str, str, str], list[dict[str, Any]]]] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NETWORK_WORKERS) as executor:
        futures = {executor.submit(fetch_category, entry): entry for entry in pending}
        for future in concurrent.futures.as_completed(futures):
            try:
                completed.append(future.result())
            except Exception as exc:
                errors.append(f"{futures[future][0]}: {exc}")

    fetched_at = utc_now()
    with connect() as conn:
        for (key, label, label_zh), items in completed:
            source_url = producthunt_category_url(key)
            conn.execute("""
              INSERT INTO producthunt_category_snapshots(category_key,label,label_zh,fetched_at,source_url,item_count)
              VALUES(?,?,?,?,?,?) ON CONFLICT(category_key) DO UPDATE SET
                label=excluded.label,label_zh=excluded.label_zh,fetched_at=excluded.fetched_at,
                source_url=excluded.source_url,item_count=excluded.item_count
            """, (key, label, label_zh, fetched_at, source_url, len(items)))
            conn.execute("DELETE FROM producthunt_category_items WHERE category_key=?", (key,))
            conn.executemany(
                "INSERT INTO producthunt_category_items(category_key,rank,product_id,raw_json) VALUES(?,?,?,?)",
                [(key, item["rank"], item["id"], json.dumps(item, ensure_ascii=False, separators=(",", ":"))) for item in items],
            )
    if errors:
        AIHotClient._state("producthunt:categories", None, "error", "; ".join(errors))
        if not completed:
            raise RuntimeError("; ".join(errors))
    else:
        AIHotClient._state("producthunt:categories", None, "ok", None)
    with connect() as conn:
        return {
            row["category_key"]: row["item_count"]
            for row in conn.execute("SELECT category_key,item_count FROM producthunt_category_snapshots")
        }


def ensure_producthunt_translations(items: list[dict[str, Any]]) -> None:
    pending: list[tuple[str, str]] = []
    with connect() as conn:
        for item in items:
            source = str(item.get("tagline") or "").strip()
            cached = conn.execute(
                "SELECT tagline_source FROM producthunt_translations WHERE post_id=?",
                (item["id"],),
            ).fetchone()
            if source and (not cached or cached["tagline_source"] != source):
                pending.append((item["id"], source))
    if not pending:
        return

    def translate_one(entry: tuple[str, str]) -> tuple[str, str, str]:
        post_id, source = entry
        return post_id, source, translate_hn_text(source)

    completed: list[tuple[str, str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NETWORK_WORKERS) as executor:
        for future in concurrent.futures.as_completed([executor.submit(translate_one, entry) for entry in pending]):
            try:
                completed.append(future.result())
            except Exception:
                continue
    if completed:
        with connect() as conn:
            conn.executemany("""
              INSERT INTO producthunt_translations(post_id,tagline_source,tagline_zh,updated_at)
              VALUES(?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET
              tagline_source=excluded.tagline_source,tagline_zh=excluded.tagline_zh,updated_at=excluded.updated_at
            """, [(*entry, utc_now()) for entry in completed])


def sopilot_url(kind: str, range_key: str, page: int = 1) -> str:
    paths = {
        "tweets": ("tweets", {"range": range_key, "category": "AI"}),
        "creators": ("creators", {"range": range_key, "sort": "growth"}),
        "topics": ("topic", {"range": range_key, "sort": "heat"}),
    }
    path, query = paths[kind]
    # An explicit first-page parameter avoids an intermittently slow redirect/cache path.
    query["page"] = str(page)
    return f"{SOPILOT_ROOT}/zh/rank/{path}?{urllib.parse.urlencode(query)}"


def fetch_sopilot_page(url: str, attempts: int = 4) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={
            "Accept": "text/html",
            "Connection": "close",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"SoPilot 页面读取失败（已重试 {attempts} 次）：{url}: {last_error}")


def next_flight_text(page: str) -> str:
    parts: list[str] = []
    for match in re.finditer(r"self\.__next_f\.push\((\[.*?\])\)</script>", page, re.S):
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if len(value) > 1 and isinstance(value[1], str):
            parts.append(value[1])
    if not parts:
        raise RuntimeError("SoPilot 页面中没有可读取的榜单数据")
    return "".join(parts)


def flight_values(flight: str, key: str) -> list[Any]:
    token, position, values = f'"{key}":', 0, []
    decoder = json.JSONDecoder()
    while True:
        position = flight.find(token, position)
        if position < 0:
            return values
        start = position + len(token)
        try:
            value, _ = decoder.raw_decode(flight[start:])
            values.append(value)
        except json.JSONDecodeError:
            pass
        position = start


AI_ARTICLE_TERMS = (
    "ai", "人工智能", "大模型", "模型", "智能体", "agent", "llm", "gpt", "chatgpt",
    "openai", "claude", "anthropic", "gemini", "qwen", "deepseek", "kimi", "llama",
    "mistral", "codex", "sora", "midjourney", "seedance", "提示词", "prompt", "skill",
    "workbuddy", "混元", "文心", "智谱", "glm", "生成式",
)


def is_ai_content(item: dict[str, Any]) -> bool:
    text = normalize_text(" ".join(str(item.get(key) or "") for key in ("articleTitle", "text")))
    return any(term in text for term in AI_ARTICLE_TERMS)


def parse_xrank_page(kind: str, page: str) -> list[dict[str, Any]]:
    flight = next_flight_text(page)
    if kind == "tweets":
        output: list[dict[str, Any]] = []
        for key, board in (("risingTweets", "rising"), ("hotTweets", "hot")):
            lists = [value for value in flight_values(flight, key) if isinstance(value, list)]
            if not lists:
                continue
            for item in max(lists, key=len):
                if isinstance(item, dict):
                    output.append({**item, "_board": board})
        items = output
    else:
        collection = {"creators": "accounts", "topics": "topics"}[kind]
        candidates = [value for value in flight_values(flight, "initialData") if isinstance(value, dict) and isinstance(value.get(collection), list)]
        items = candidates[-1][collection] if candidates else []
    if kind == "tweets":
        items = [item for item in items if is_ai_content(item)]
    elif kind in {"creators", "topics"}:
        items = [item for item in items if item.get("category") == "AI"]
    if not isinstance(items, list):
        raise RuntimeError("SoPilot 榜单结构无法识别")
    return [{**item, "_rank": index} for index, item in enumerate(items, 1)]


def xrank_total_pages(kind: str, page: str) -> int:
    flight = next_flight_text(page)
    if kind == "tweets":
        values = [value for value in flight_values(flight, "totalPages") if isinstance(value, int)]
    else:
        collection = {"creators": "accounts", "topics": "topics"}[kind]
        values = [value.get("totalPages") for value in flight_values(flight, "initialData") if isinstance(value, dict) and isinstance(value.get(collection), list)]
    return min(max([value for value in values if isinstance(value, int)] or [1]), 100)


def sync_xrank(kind: str, range_key: str) -> int:
    if kind not in XRANK_RANGES or range_key not in XRANK_RANGES[kind]:
        raise ValueError("不支持的 X 热榜类型或时间范围")
    source_url = sopilot_url(kind, range_key)
    try:
        pages = [fetch_sopilot_page(source_url)]
        total_pages = xrank_total_pages(kind, pages[0])
        page_urls = [sopilot_url(kind, range_key, page_number) for page_number in range(2, total_pages + 1)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=NETWORK_WORKERS) as executor:
            pages.extend(executor.map(fetch_sopilot_page, page_urls))
        parsed = [item for page_html in pages for item in parse_xrank_page(kind, page_html)]
        items, seen = [], set()
        for item in parsed:
            base_id = str(item.get("id") or item.get("accountId") or item.get("slug") or item.get("screenName") or len(items) + 1)
            unique_id = f'{item.get("_board", "main")}:{base_id}'
            if unique_id in seen:
                continue
            seen.add(unique_id)
            items.append({**item, "_rank": len(items) + 1})
        fetched_at = utc_now()
        with connect() as conn:
            conn.execute("""
              INSERT INTO xrank_snapshots(kind,range_key,fetched_at,source_url,item_count)
              VALUES(?,?,?,?,?) ON CONFLICT(kind,range_key) DO UPDATE SET
              fetched_at=excluded.fetched_at,source_url=excluded.source_url,item_count=excluded.item_count
            """, (kind, range_key, fetched_at, source_url, len(items)))
            conn.execute("DELETE FROM xrank_items WHERE kind=? AND range_key=?", (kind, range_key))
            rows = []
            for item in items:
                base_id = str(item.get("id") or item.get("accountId") or item.get("slug") or item.get("screenName") or item["_rank"])
                item_id = f'{item.get("_board", "main")}:{base_id}'
                rows.append((kind, range_key, item["_rank"], item_id, json.dumps(item, ensure_ascii=False)))
            conn.executemany("INSERT INTO xrank_items(kind,range_key,rank,item_id,raw_json) VALUES(?,?,?,?,?)", rows)
        AIHotClient._state(f"sopilot:{kind}:{range_key}", None, "ok", None)
        return len(items)
    except Exception as exc:
        AIHotClient._state(f"sopilot:{kind}:{range_key}", None, "error", str(exc))
        raise


HN_AI_PATTERNS = (
    r"\bai\b", r"artificial intelligence", r"machine learning", r"deep learning",
    r"\bllms?\b", r"language models?", r"foundation models?", r"transformers?",
    r"neural networks?", r"generative ai", r"diffusion models?", r"multimodal",
    r"\bagents?\b", r"agentic", r"\bmcp\b", r"model context protocol",
    r"openai", r"chatgpt", r"\bgpt[-\s]?\d", r"anthropic", r"claude",
    r"gemini", r"deepmind", r"\bllama\b", r"qwen", r"deepseek", r"mistral",
    r"hugging face", r"huggingface", r"copilot", r"codex", r"prompt engineering",
    r"inference", r"fine[- ]?tun", r"embeddings?", r"vector database",
)
HN_AI_SOURCES = (
    "anthropic.com", "openai.com", "deepmind.google", "huggingface.co",
    "artificialanalysis.ai", "gimletlabs.ai", "openrouter.ai",
)


def is_hn_ai_item(item: dict[str, Any]) -> bool:
    # Keep the default AI filter conservative: long Ask/Show bodies often mention AI
    # incidentally even when the submitted item is about something else.
    text = normalize_text(" ".join(str(item.get(key) or "") for key in ("title", "url")))
    if any(phrase in text for phrase in ("does not use llm", "without ai", "no ai used")):
        return False
    if any(source in text for source in HN_AI_SOURCES):
        return True
    return any(re.search(pattern, text, re.I) for pattern in HN_AI_PATTERNS)


def fetch_hn_json(path: str, attempts: int = 3) -> Any:
    url = f"{HN_API_ROOT}/{path.lstrip('/')}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.35 * (attempt + 1))
    raise RuntimeError(f"Hacker News API 读取失败：{url}: {last_error}")


def hn_text_excerpt(value: str | None, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if re.fullmatch(r"https?://\S+", text, re.I):
        return ""
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped or text[:limit]}…"


def polish_hn_translation(source: str, translated: str) -> str:
    value = translated.strip()
    value = re.sub(r"^(?:显示|展示)\s*HN\s*[：:]", "Show HN：", value, flags=re.I)
    value = re.sub(r"^询问\s*HN\s*[：:]", "Ask HN：", value, flags=re.I)
    if re.search(r"\bagents?\b|agentic", source, re.I):
        value = value.replace("AI 代理", "AI 智能体").replace("OpenAI 代理", "OpenAI 智能体")
        value = re.sub(r"(?<!代)代理(?=(?:工具|系统|框架|助手|留言板|消息|支付|运行时|调度|治理))", "智能体", value)
    if source.lower().startswith("artificial analysis intelligence index"):
        value = re.sub(r"^人工智能分析智能指数", "Artificial Analysis 智能指数", value)
    return value


def translate_hn_text(value: str, attempts: int = 1) -> str:
    source = hn_text_excerpt(value)
    if not source or re.search(r"[\u4e00-\u9fff]", source):
        return source
    query = urllib.parse.urlencode({
        "client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": source,
    })
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(str(part[0] or "") for part in (payload[0] or []) if part).strip()
            return polish_hn_translation(source, translated)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
    fallback_query = urllib.parse.urlencode({"q": source, "langpair": "en|zh-CN"})
    fallback_url = f"https://api.mymemory.translated.net/get?{fallback_query}"
    try:
        request = urllib.request.Request(fallback_url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        translated = html.unescape(str((payload.get("responseData") or {}).get("translatedText") or "")).strip()
        if translated:
            return polish_hn_translation(source, translated)
    except Exception as exc:
        last_error = exc
    raise RuntimeError(f"中文翻译失败：{last_error}")


def ensure_hn_translations(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    item_ids = [int(item["item_id"]) for item in items]
    placeholders = ",".join("?" for _ in item_ids)
    with connect() as conn:
        cached = {
            row["item_id"]: dict(row)
            for row in conn.execute(f"SELECT * FROM hn_translations WHERE item_id IN ({placeholders})", item_ids)
        }
    pending = []
    for item in items:
        title_source = hn_text_excerpt(item.get("title"), 500)
        text_source = hn_text_excerpt(item.get("text"))
        old = cached.get(int(item["item_id"]))
        if old and old["title_source"] == title_source and (old["text_source"] or "") == text_source:
            continue
        pending.append((int(item["item_id"]), title_source, text_source))
    if not pending:
        return

    def translate_one(entry: tuple[int, str, str]) -> tuple[int, str, str, str, str]:
        item_id, title_source, text_source = entry
        title_zh = translate_hn_text(title_source)
        text_zh = translate_hn_text(text_source) if text_source else ""
        return item_id, title_source, title_zh, text_source, text_zh

    completed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NETWORK_WORKERS) as executor:
        futures = [executor.submit(translate_one, entry) for entry in pending]
        for future in concurrent.futures.as_completed(futures):
            try:
                completed.append(future.result())
            except Exception:
                continue
    if completed:
        with connect() as conn:
            conn.executemany("""
              INSERT INTO hn_translations(item_id,title_source,title_zh,text_source,text_zh,updated_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
              title_source=excluded.title_source,title_zh=excluded.title_zh,
              text_source=excluded.text_source,text_zh=excluded.text_zh,updated_at=excluded.updated_at
            """, [(*entry, utc_now()) for entry in completed])


def build_hn_feed_items(feed: str, ids: list[int], items_by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item_id in ids:
        item = items_by_id.get(item_id)
        if not item or item.get("type") not in {"story", "job"} or item.get("deleted") or item.get("dead"):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
        domain = urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.") or "news.ycombinator.com"
        published = datetime.fromtimestamp(int(item.get("time") or 0), timezone.utc).isoformat().replace("+00:00", "Z")
        items.append({
            "feed": feed,
            "rank": len(items) + 1,
            "item_id": item_id,
            "title": title,
            "url": url,
            "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
            "author": item.get("by"),
            "score": item.get("score"),
            "comments": item.get("descendants") or 0,
            "published_at": published,
            "source_domain": domain,
            "is_ai": is_hn_ai_item(item),
            "text": text_from_html(item.get("text") or ""),
            "raw_json": json.dumps(item, ensure_ascii=False, separators=(",", ":")),
        })
    return items


def sync_hacker_news() -> dict[str, int]:
    try:
        list_ids: dict[str, list[int]] = {}
        raw_ids: dict[str, list[int]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=NETWORK_WORKERS) as executor:
            futures = {
                feed: executor.submit(fetch_hn_json, f"{endpoint}.json")
                for feed, (endpoint, _, _) in HN_FEEDS.items()
            }
            for feed, future in futures.items():
                limit = HN_FEEDS[feed][1]
                raw_ids[feed] = [int(value) for value in (future.result() or [])]
                list_ids[feed] = raw_ids[feed][:limit]

        # HN has no shownew list endpoint. Scan enough of the official newstories
        # stream to reproduce the first page of /shownew without scraping HTML.
        show_new_candidates = raw_ids["new"][:300]
        all_ids = list(dict.fromkeys(
            [item_id for ids in list_ids.values() for item_id in ids] + show_new_candidates
        ))
        items_by_id: dict[int, dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=NETWORK_WORKERS) as executor:
            future_items = {executor.submit(fetch_hn_json, f"item/{item_id}.json"): item_id for item_id in all_ids}
            for future, item_id in [(future, item_id) for future, item_id in future_items.items()]:
                try:
                    item = future.result()
                    if isinstance(item, dict):
                        items_by_id[item_id] = item
                except Exception:
                    continue

        show_new_ids = [
            item_id for item_id in show_new_candidates
            if normalize_text((items_by_id.get(item_id) or {}).get("title")).startswith("show hn:")
        ][:30]
        list_ids["shownew"] = show_new_ids
        source_urls = {feed: spec[2] for feed, spec in HN_FEEDS.items()}
        source_urls["shownew"] = "https://news.ycombinator.com/shownew"
        fetched_at = utc_now()
        counts: dict[str, int] = {}
        with connect() as conn:
            for feed, ids in list_ids.items():
                items = build_hn_feed_items(feed, ids, items_by_id)
                counts[feed] = len(items)
                conn.execute("""
                  INSERT INTO hn_snapshots(feed,fetched_at,source_url,item_count)
                  VALUES(?,?,?,?) ON CONFLICT(feed) DO UPDATE SET
                  fetched_at=excluded.fetched_at,source_url=excluded.source_url,item_count=excluded.item_count
                """, (feed, fetched_at, source_urls[feed], len(items)))
                conn.execute("DELETE FROM hn_items WHERE feed=?", (feed,))
                conn.executemany("""
                  INSERT INTO hn_items(feed,rank,item_id,title,url,hn_url,author,score,comments,
                    published_at,source_domain,is_ai,text,raw_json)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, [(
                    item["feed"], item["rank"], item["item_id"], item["title"], item["url"],
                    item["hn_url"], item["author"], item["score"], item["comments"],
                    item["published_at"], item["source_domain"], int(item["is_ai"]),
                    item["text"], item["raw_json"],
                ) for item in items])
        AIHotClient._state("hacker-news", None, "ok", None)
        return counts
    except Exception as exc:
        AIHotClient._state("hacker-news", None, "error", str(exc))
        raise


SYNC_LOCK = threading.Lock()


def sync_all() -> dict[str, Any]:
    if not SYNC_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "同步正在进行"}
    started = time.time()
    result: dict[str, Any] = {"ok": True, "content": {}, "facts": 0, "daily": False, "projects": 0, "productHunt": {}, "productHuntCategories": {}, "xrank": {}, "hackerNews": {}, "errors": []}
    client = AIHotClient()
    try:
        for window in ("24h", "7d"):
            resource = f"items:all:{window}"
            try:
                payload = client.get("/items", resource, {"mode": "all", "window": window, "limit": "100"})
                if payload:
                    result["content"][window] = upsert_content(payload.get("items") or [])
            except Exception as exc:
                result["errors"].append(f"{resource}: {exc}")
        try:
            payload = client.get("/hot-topics", "hot-topics")
            if payload:
                result["facts"] = upsert_facts(payload, client)
        except Exception as exc:
            result["errors"].append(f"hot-topics: {exc}")
        try:
            payload = client.get("/dailies/latest", "daily:latest")
            if payload:
                result["daily"] = upsert_daily(payload)
        except Exception as exc:
            result["errors"].append(f"daily: {exc}")
        try:
            result["projects"] = sync_github_trending()
        except Exception as exc:
            result["errors"].append(f"github:trending: {exc}")
        if producthunt_token():
            try:
                result["productHunt"] = sync_producthunt()
            except Exception as exc:
                result["errors"].append(f"producthunt: {exc}")
            try:
                result["productHuntCategories"] = sync_producthunt_categories()
            except Exception as exc:
                result["errors"].append(f"producthunt:categories: {exc}")
        for kind, range_key in XRANK_DEFAULTS.items():
            try:
                result["xrank"][kind] = sync_xrank(kind, range_key)
            except Exception as exc:
                result["errors"].append(f"sopilot:{kind}:{range_key}: {exc}")
        try:
            result["hackerNews"] = sync_hacker_news()
        except Exception as exc:
            result["errors"].append(f"hacker-news: {exc}")
        result["ok"] = not result["errors"]
        result["durationMs"] = round((time.time() - started) * 1000)
        return result
    finally:
        SYNC_LOCK.release()


def parse_multi(params: dict[str, list[str]], key: str) -> list[str]:
    values: list[str] = []
    for value in params.get(key, []):
        values.extend(part for part in value.split(",") if part and part != "all")
    return list(dict.fromkeys(values))


def query_content(params: dict[str, list[str]]) -> dict[str, Any]:
    clauses, args = ["1=1"], []
    scope = (params.get("scope") or ["all"])[0]
    if scope == "selected":
        clauses.append("c.selected=1")
    categories = parse_multi(params, "category")
    if categories:
        clauses.append(f"c.category IN ({','.join('?' for _ in categories)})")
        args.extend(categories)
    q = ((params.get("q") or [""])[0]).strip()
    if q:
        clauses.append("(c.title LIKE ? OR c.summary LIKE ? OR c.source_name LIKE ?)")
        args.extend([f"%{q}%"] * 3)
    for dimension, key in (("technology", "topic"), ("form", "form"), ("entity", "entity")):
        values = parse_multi(params, key)
        if values:
            clauses.append(f"EXISTS (SELECT 1 FROM content_tag_links ctl JOIN taxonomy_tags tt ON tt.id=ctl.tag_id WHERE ctl.content_id=c.id AND tt.dimension=? AND tt.slug IN ({','.join('?' for _ in values)}))")
            args.append(dimension)
            args.extend(values)
    limit = min(max(int((params.get("limit") or ["60"])[0]), 1), 200)
    offset = max(int((params.get("offset") or ["0"])[0]), 0)
    where = " AND ".join(clauses)
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) n FROM content_items c WHERE {where}", args).fetchone()["n"]
        rows = conn.execute(f"SELECT c.* FROM content_items c WHERE {where} ORDER BY COALESCE(c.published_at,c.discovered_at) DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        output = []
        for row in rows:
            tags = conn.execute("SELECT tt.dimension,tt.slug,tt.label FROM content_tag_links ctl JOIN taxonomy_tags tt ON tt.id=ctl.tag_id WHERE ctl.content_id=?", (row["id"],)).fetchall()
            aliases = conn.execute("SELECT source_name,original_url,reason FROM content_aliases WHERE content_id=?", (row["id"],)).fetchall()
            item = dict(row)
            item.pop("raw_json", None)
            item["selected"] = bool(item["selected"])
            item["tags"] = [{"dimension": t["dimension"], "slug": t["slug"], "label": t["label"]} for t in tags]
            item["aliases"] = [dict(a) for a in aliases]
            output.append(item)
        return {"items": output, "page": {"count": len(output), "total": total, "offset": offset, "hasMore": offset + len(output) < total}}


def query_facts() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM fact_items WHERE in_current=1 ORDER BY rank ASC").fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.pop("raw_json", None)
            item["in_current"] = bool(item["in_current"])
            items.append(item)
        return {"items": items, "count": len(items)}


def query_daily() -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT raw_json FROM daily_reports ORDER BY date DESC LIMIT 1").fetchone()
        return {"report": json.loads(row["raw_json"]) if row else None}


def query_projects() -> dict[str, Any]:
    with connect() as conn:
        snapshot = conn.execute("SELECT * FROM github_trending_snapshots ORDER BY date DESC LIMIT 1").fetchone()
        if not snapshot:
            return {"snapshot": None, "items": [], "count": 0}
        rows = conn.execute("SELECT * FROM github_trending_items WHERE snapshot_date=? ORDER BY rank", (snapshot["date"],)).fetchall()
        return {"snapshot": dict(snapshot), "items": [dict(row) for row in rows], "count": len(rows)}


def query_producthunt(params: dict[str, list[str]]) -> dict[str, Any]:
    range_key = (params.get("range") or ["today"])[0]
    if range_key not in PRODUCTHUNT_RANGES:
        raise ValueError("不支持的 Product Hunt 时间范围")
    category_key = (params.get("category") or [""])[0]
    if category_key and category_key not in PRODUCTHUNT_CATEGORY_KEYS:
        raise ValueError("不支持的 Product Hunt 一级分类")
    configured = bool(producthunt_token())
    with connect() as conn:
        category_counts = {
            row["category_key"]: row["item_count"]
            for row in conn.execute("SELECT category_key,item_count FROM producthunt_category_snapshots")
        }
        categories = [
            {"key": key, "label": label, "label_zh": label_zh, "count": int(category_counts.get(key, 0))}
            for key, label, label_zh in PRODUCTHUNT_CATEGORIES
        ]
        if category_key:
            snapshot = conn.execute(
                "SELECT * FROM producthunt_category_snapshots WHERE category_key=?", (category_key,)
            ).fetchone()
            rows = conn.execute(
                "SELECT raw_json FROM producthunt_category_items WHERE category_key=? ORDER BY rank",
                (category_key,),
            ).fetchall()
        else:
            snapshot = conn.execute("SELECT * FROM producthunt_snapshots WHERE range_key=?", (range_key,)).fetchone()
            rows = conn.execute(
                "SELECT raw_json FROM producthunt_items WHERE range_key=? ORDER BY rank",
                (range_key,),
            ).fetchall()
    items = [json.loads(row["raw_json"]) for row in rows]
    if NETWORK_ENABLED:
        ensure_producthunt_translations(items)
    if items:
        placeholders = ",".join("?" for _ in items)
        with connect() as conn:
            translations = {
                row["post_id"]: row["tagline_zh"]
                for row in conn.execute(
                    f"SELECT post_id,tagline_zh FROM producthunt_translations WHERE post_id IN ({placeholders})",
                    [item["id"] for item in items],
                )
            }
        for item in items:
            item["tagline_zh"] = translations.get(item["id"], "")
    return {
        "range": range_key,
        "category": category_key or None,
        "mode": "category" if category_key else "launches",
        "categories": categories,
        "configured": configured,
        "snapshot": dict(snapshot) if snapshot else None,
        "items": items,
        "count": len(items),
    }


def query_xrank(params: dict[str, list[str]]) -> dict[str, Any]:
    kind = (params.get("kind") or ["tweets"])[0]
    range_key = (params.get("range") or [XRANK_DEFAULTS.get(kind, "24h")])[0]
    if kind not in XRANK_RANGES or range_key not in XRANK_RANGES[kind]:
        raise ValueError("不支持的 X 热榜类型或时间范围")
    with connect() as conn:
        snapshot = conn.execute("SELECT * FROM xrank_snapshots WHERE kind=? AND range_key=?", (kind, range_key)).fetchone()
    if not snapshot and NETWORK_ENABLED:
        sync_xrank(kind, range_key)
    with connect() as conn:
        snapshot = conn.execute("SELECT * FROM xrank_snapshots WHERE kind=? AND range_key=?", (kind, range_key)).fetchone()
        rows = conn.execute("SELECT raw_json FROM xrank_items WHERE kind=? AND range_key=? ORDER BY rank", (kind, range_key)).fetchall()
    items = [json.loads(row["raw_json"]) for row in rows]
    return {"kind": kind, "range": range_key, "snapshot": dict(snapshot) if snapshot else None, "items": items, "count": len(items)}


def query_hacker_news(params: dict[str, list[str]]) -> dict[str, Any]:
    feed = (params.get("view") or ["news"])[0]
    scope = (params.get("scope") or ["ai"])[0]
    sort = (params.get("sort") or ["rank"])[0]
    if feed not in {*HN_FEEDS, "shownew"}:
        raise ValueError("不支持的 Hacker News 视图")
    if scope not in {"ai", "all"}:
        raise ValueError("不支持的 Hacker News 内容范围")
    sort_sql = {
        "rank": "rank ASC",
        "time": "published_at DESC",
        "score": "COALESCE(score,0) DESC, rank ASC",
        "comments": "COALESCE(comments,0) DESC, rank ASC",
    }
    if sort not in sort_sql:
        raise ValueError("不支持的 Hacker News 排序方式")
    with connect() as conn:
        snapshot = conn.execute("SELECT * FROM hn_snapshots WHERE feed=?", (feed,)).fetchone()
    if not snapshot and NETWORK_ENABLED:
        sync_hacker_news()
    with connect() as conn:
        snapshot = conn.execute("SELECT * FROM hn_snapshots WHERE feed=?", (feed,)).fetchone()
        clause = "feed=?" + (" AND is_ai=1" if scope == "ai" else "")
        total = conn.execute(f"SELECT COUNT(*) n FROM hn_items WHERE {clause}", (feed,)).fetchone()["n"]
        rows = conn.execute(f"SELECT * FROM hn_items WHERE {clause} ORDER BY {sort_sql[sort]} LIMIT 100", (feed,)).fetchall()
    if NETWORK_ENABLED:
        ensure_hn_translations([dict(row) for row in rows])
    with connect() as conn:
        rows = conn.execute(f"""
          SELECT h.*,t.title_zh,t.text_zh,t.text_source
          FROM hn_items h LEFT JOIN hn_translations t ON t.item_id=h.item_id
          WHERE {clause} ORDER BY {sort_sql[sort]} LIMIT 100
        """, (feed,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item.pop("raw_json", None)
        item["is_ai"] = bool(item["is_ai"])
        item["text"] = item.pop("text_source", None) or hn_text_excerpt(item.get("text"))
        item["title_zh"] = polish_hn_translation(item.get("title") or "", item.get("title_zh") or "")
        item["text_zh"] = polish_hn_translation(item.get("text") or "", item.get("text_zh") or "")
        items.append(item)
    return {"view": feed, "scope": scope, "sort": sort, "snapshot": dict(snapshot) if snapshot else None, "items": items, "count": len(items), "total": total}


def query_meta() -> dict[str, Any]:
    with connect() as conn:
        states = [dict(row) for row in conn.execute("SELECT * FROM sync_state ORDER BY resource")]
        counts = {
            "content": conn.execute("SELECT COUNT(*) n FROM content_items").fetchone()["n"],
            "selected": conn.execute("SELECT COUNT(*) n FROM content_items WHERE selected=1").fetchone()["n"],
            "facts": conn.execute("SELECT COUNT(*) n FROM fact_items WHERE in_current=1").fetchone()["n"],
            "aliases": conn.execute("SELECT COUNT(*) n FROM content_aliases").fetchone()["n"],
            "projects": conn.execute("SELECT COUNT(*) n FROM github_trending_items WHERE snapshot_date=(SELECT MAX(date) FROM github_trending_snapshots)").fetchone()["n"],
            "productHunt": conn.execute("SELECT COUNT(*) n FROM producthunt_items WHERE range_key='today'").fetchone()["n"],
            "productHuntCategories": conn.execute("SELECT COUNT(*) n FROM producthunt_category_items").fetchone()["n"],
            "xrank": conn.execute("SELECT COALESCE(SUM(item_count),0) n FROM xrank_snapshots").fetchone()["n"],
            "hackerNews": conn.execute("SELECT COALESCE(SUM(item_count),0) n FROM hn_snapshots").fetchone()["n"],
        }
    return {
        "counts": counts,
        "sync": states,
        "sources": ["AIHOT", "GitHub Trending", "Product Hunt", "SoPilot", "Hacker News"],
        "localTaxonomy": True,
        "productHuntConfigured": bool(producthunt_token()),
        "autoSync": {"enabled": NETWORK_ENABLED, "intervalMinutes": AUTO_SYNC_INTERVAL_SECONDS // 60},
    }


def automatic_sync_loop(stop_event: threading.Event, interval_seconds: float = AUTO_SYNC_INTERVAL_SECONDS) -> None:
    """Run a fixed-interval background sync without delaying HTTP responses."""
    next_run = time.monotonic() + interval_seconds
    while not stop_event.wait(max(0.0, next_run - time.monotonic())):
        started_at = utc_now()
        try:
            result = sync_all()
            print(f"[{started_at}] 自动同步：{json.dumps(result, ensure_ascii=False)}", flush=True)
        except Exception as exc:
            # sync_all normally records per-source failures itself; this guards the scheduler.
            print(f"[{started_at}] 自动同步异常：{exc}", flush=True)
        next_run += interval_seconds
        if next_run <= time.monotonic():
            next_run = time.monotonic() + interval_seconds


def run_initial_sync() -> None:
    """Run the first refresh without blocking the local HTTP server."""
    started_at = utc_now()
    try:
        result = sync_all()
        print(f"[{started_at}] 启动同步：{json.dumps(result, ensure_ascii=False)}", flush=True)
    except Exception as exc:
        print(f"[{started_at}] 启动同步异常：{exc}", flush=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/content":
                return self.send_json(query_content(params))
            if parsed.path == "/api/facts":
                return self.send_json(query_facts())
            if parsed.path == "/api/daily":
                return self.send_json(query_daily())
            if parsed.path == "/api/projects":
                return self.send_json(query_projects())
            if parsed.path == "/api/launches":
                return self.send_json(query_producthunt(params))
            if parsed.path == "/api/xrank":
                return self.send_json(query_xrank(params))
            if parsed.path == "/api/hn":
                return self.send_json(query_hacker_news(params))
            if parsed.path == "/api/meta":
                return self.send_json(query_meta())
            if parsed.path == "/api/health":
                return self.send_json({"ok": True, "time": utc_now()})
            if parsed.path.startswith("/api/"):
                return self.send_json({"error": "not found"}, 404)
            if parsed.path == "/today":
                self.send_response(302)
                self.send_header("Location", "/facts")
                self.end_headers()
                return
            if parsed.path in {"/facts", "/content", "/projects", "/launches", "/xrank", "/hn", "/about"}:
                self.path = "/index.html"
            return super().do_GET()
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

def main() -> None:
    global NETWORK_ENABLED
    parser = argparse.ArgumentParser(description="个人信源网站")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-sync", action="store_true", help="跳过启动时的首次同步（仍每 30 分钟自动同步）")
    parser.add_argument("--sync", action="store_true", help="启用联网采集与自动同步；默认只读取本地缓存")
    args = parser.parse_args()
    NETWORK_ENABLED = args.sync
    # Bind before starting any work: duplicate launches must not start collectors.
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print(f"无法启动：端口 {args.port} 不可用，请检查是否已经启动网站。{exc}", flush=True)
        return
    init_db()
    stop_event = threading.Event()
    scheduler = threading.Thread(
        target=automatic_sync_loop,
        args=(stop_event,),
        name="personal-sources-auto-sync",
        daemon=True,
    )
    if NETWORK_ENABLED:
        scheduler.start()
    mode = "每 30 分钟自动同步" if NETWORK_ENABLED else "本地缓存模式：采集与在线翻译已暂停"
    print(f"个人信源网站：http://{args.host}:{args.port}（{mode}）", flush=True)
    if NETWORK_ENABLED and not args.no_sync:
        print("启动同步已放到后台，网页可以立即打开。", flush=True)
        threading.Thread(target=run_initial_sync, name="personal-sources-initial-sync", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
