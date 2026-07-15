"""
AI 资讯聚合器
────────────
从多个公开信息源获取最新 AI 相关资讯。

数据源（MVP 阶段）：
  1. Hacker News — search "AI" / "LLM" / "GPT" 相关帖子
  2. ArXiv — 最新 AI/cs.CL/cs.CV 论文
  3. GitHub Trending — AI/ML 项目

输出：结构化资讯列表，供 ContentWriter 整理成文章。
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """单条资讯"""
    title: str
    url: str
    source: str           # "hackernews" | "arxiv" | "github"
    summary: str = ""     # 摘要
    published_at: str = ""  # ISO 日期
    score: int = 0        # 热度分数
    tags: list[str] = field(default_factory=list)


@dataclass
class NewsBundle:
    """资讯聚合结果"""
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())
    items: list[NewsItem] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)


class NewsFetcher:
    """
    AI 资讯聚合器。

    用法：
        fetcher = NewsFetcher()
        bundle = fetcher.fetch_all()
        for item in bundle.items:
            print(item.title)
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "AI-Content-Operator/1.0"},
        )

    # ── 数据源 1: Hacker News ──────────────────────────────

    HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
    AI_KEYWORDS = ["AI", "LLM", "GPT", "Claude", "DeepSeek", "Gemini",
                   "OpenAI", "Anthropic", "大模型", "machine learning"]

    def fetch_hackernews(self, limit: int = 10) -> list[NewsItem]:
        """获取 Hacker News 上最近 24h 的 AI 相关帖子"""
        items = []
        try:
            for keyword in self.AI_KEYWORDS[:6]:  # MVP 限制搜索量
                resp = self.client.get(
                    self.HN_SEARCH_URL,
                    params={
                        "query": keyword,
                        "tags": "story",
                        "hitsPerPage": 3,
                    },
                )
                hits = resp.json().get("hits", [])
                for h in hits:
                    items.append(NewsItem(
                        title=h.get("title", ""),
                        url=h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                        source="hackernews",
                        summary=f"{h.get('points', 0)} points, {h.get('num_comments', 0)} comments",
                        published_at=h.get("created_at", ""),
                        score=h.get("points", 0),
                        tags=[keyword],
                    ))
                logger.info(f"HN '{keyword}': {len(hits)} 条")

        except Exception as e:
            logger.warning(f"HackerNews 抓取失败: {e}")

        # 去重 + 按分数排序 + 截取
        seen = set()
        unique = []
        for item in sorted(items, key=lambda x: x.score, reverse=True):
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)
        return unique[:limit]

    # ── 数据源 2: ArXiv ────────────────────────────────────

    ARXIV_API = "https://export.arxiv.org/api/query"

    def fetch_arxiv(self, limit: int = 5) -> list[NewsItem]:
        """获取 ArXiv 最新 AI 相关论文"""
        import xml.etree.ElementTree as ET

        items = []
        try:
            query = "(cat:cs.AI OR cat:cs.CL OR cat:cs.LG)"
            params = {
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": limit,
            }
            resp = self.client.get(self.ARXIV_API, params=params)
            root = ET.fromstring(resp.text)

            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }

            for entry in root.findall("atom:entry", ns)[:limit]:
                title = entry.find("atom:title", ns)
                summary = entry.find("atom:summary", ns)
                link = entry.find("atom:id", ns)
                published = entry.find("atom:published", ns)

                items.append(NewsItem(
                    title=title.text.strip().replace("\n", " ") if title is not None else "",
                    url=link.text.strip() if link is not None else "",
                    source="arxiv",
                    summary=(summary.text.strip()[:200] if summary is not None else ""),
                    published_at=published.text.strip() if published is not None else "",
                ))
            logger.info(f"ArXiv: {len(items)} 篇论文")

        except Exception as e:
            logger.warning(f"ArXiv 抓取失败: {e}")

        return items

    # ── 数据源 3: GitHub Trending ──────────────────────────

    def fetch_github_trending(self, limit: int = 5) -> list[NewsItem]:
        """获取 GitHub 上 AI/ML 相关热门项目"""
        items = []
        try:
            # 使用 GitHub search API 找最近一周的 AI 项目
            last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            resp = self.client.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"ai OR llm OR machine-learning created:>={last_week}",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": limit,
                },
            )
            repos = resp.json().get("items", [])
            for r in repos:
                items.append(NewsItem(
                    title=r.get("full_name", ""),
                    url=r.get("html_url", ""),
                    source="github",
                    summary=r.get("description", "") or "",
                    score=r.get("stargazers_count", 0),
                    tags=[r.get("language", "")],
                ))
            logger.info(f"GitHub Trending: {len(items)} 个项目")

        except Exception as e:
            logger.warning(f"GitHub Trending 抓取失败: {e}")

        return items

    # ── 聚合 ───────────────────────────────────────────────

    def fetch_all(
        self,
        sources: list[str] | None = None,
        limit_per_source: int = 5,
    ) -> NewsBundle:
        """
        从所有数据源聚合资讯。

        Args:
            sources: 数据源列表，默认全部
            limit_per_source: 每个数据源的条数上限

        Returns:
            NewsBundle: 聚合结果
        """
        if sources is None:
            sources = ["hackernews", "arxiv", "github"]

        bundle = NewsBundle(sources_used=sources)

        for source in sources:
            try:
                if source == "hackernews":
                    bundle.items.extend(self.fetch_hackernews(limit=limit_per_source))
                elif source == "arxiv":
                    bundle.items.extend(self.fetch_arxiv(limit=limit_per_source))
                elif source == "github":
                    bundle.items.extend(self.fetch_github_trending(limit=limit_per_source))
            except Exception as e:
                bundle.errors.append(f"{source}: {e}")

        logger.info(f"聚合完成: {bundle.count} 条资讯, {len(bundle.errors)} 个错误")
        return bundle

    def to_formatted_text(self, bundle: NewsBundle, max_items: int = 15) -> str:
        """
        将资讯包格式化为 LLM 友好的文本，供 ContentWriter 使用。

        Returns:
            格式化后的文本
        """
        lines = [f"## AI 资讯聚合 — {datetime.now().strftime('%Y-%m-%d')}\n"]

        by_source = {}
        for item in bundle.items[:max_items]:
            by_source.setdefault(item.source, []).append(item)

        for source, items in by_source.items():
            source_name = {
                "hackernews": "💬 Hacker News 讨论",
                "arxiv": "📄 ArXiv 最新论文",
                "github": "⭐ GitHub 热门项目",
            }.get(source, source)

            lines.append(f"### {source_name}")
            for item in items:
                line = f"- **{item.title}**"
                if item.summary:
                    line += f"\n  {item.summary}"
                if item.url:
                    line += f"\n  {item.url}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)
