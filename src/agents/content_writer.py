"""
内容生成 Agent
─────────────
职责：根据资讯素材整理成专业 AI 技术分享文章。

v2 改动：
  - 风格：专业技术分享（机器之心/量子位风格），非抖音口语化
  - 标题：不用 emoji
  - 输入：NewsBundle 资讯聚合包
  - 输出：ContentItem
"""

import json
import logging
import re
from datetime import datetime

from ..models.adapter import ModelRouter, create_default_router
from ..contracts.schemas import ContentItem
from ..utils.compliance_filter import check_compliance
from ..tools.news_fetcher import NewsBundle

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# System Prompt（v2 — 专业技术分享风格）
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个 AI 技术领域的专业内容作者，为抖音文章（长文）撰写内容。

## 抖音文章格式（严格遵守字数限制）
- 标题：必须 ≤30 字，超出则被截断。直接点明主题，不用 emoji
- 摘要：必须 ≤30 字，一句话说清文章看点
- 正文：1000-1500 字，用 ## 小标题分段

## 写作风格
- 专业技术分享，目标读者是 AI 从业者和技术爱好者
- 语言准确但不学术化——像《机器之心》或《量子位》的风格
- 有小标题分段，每段不宜过长
- 不编造数据

## 内容要求
- 准确：技术事实不能有硬伤
- 有信息量：读者读完有收获
- 尊重原文：素材来自论文/公告，保留核心观点

## 输出格式
用 JSON 格式输出，包含：
- title: 标题（≤30 字，无 emoji）
- summary: 摘要（≤30 字，吸引点击的一句话）
- body: 正文（Markdown，可用 ## 小标题分段）
- tags: 3-5 个标签
- topic: 话题分类（行业动态/论文解读/技术分析/工具推荐）"""


# ══════════════════════════════════════════════════════════════
# ContentWriter
# ══════════════════════════════════════════════════════════════

class ContentWriter:
    """
    内容生成 Agent。

    用法:
        writer = ContentWriter()
        # 从资讯聚合包生成文章
        item = writer.generate_from_news(news_bundle)
        # 或直接指定主题
        item = writer.generate(topic="技术分析", direction="讲讲 MoE 架构")
    """

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or create_default_router()
        self._id_counter = 0

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"content_{datetime.now().strftime('%Y%m%d')}_{self._id_counter:03d}"

    def _parse_json_response(self, raw_text: str) -> dict:
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, re.DOTALL)
        if json_match:
            raw_text = json_match.group(1)
        brace_match = re.search(r'\{[\s\S]*\}', raw_text)
        if brace_match:
            raw_text = brace_match.group(0)
        return json.loads(raw_text, strict=False)

    def generate_from_news(self, bundle: NewsBundle, max_items: int = 10) -> ContentItem:
        """
        从资讯聚合包生成一篇技术分享文章。

        Args:
            bundle: NewsFetcher 返回的资讯聚合包
            max_items: 最多使用多少条资讯作为素材

        Returns:
            ContentItem
        """
        # 格式化资讯为 LLM 可读文本
        from ..tools.news_fetcher import NewsFetcher
        fetcher = NewsFetcher()
        news_text = fetcher.to_formatted_text(bundle, max_items=max_items)

        user_message = f"""以下是今天聚合的最新 AI 资讯：

{news_text}

请从中选取 1-3 条最有价值的资讯，写成一篇专业的技术分享文章。
可以是一个主题的深入解读，也可以是多条资讯的综合汇总。
不要逐条罗列新闻——要提炼出对读者有信息增量的内容。"""

        response = self.router.call(
            task="content_gen",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=2000,
            temperature=0.7,
        )

        parsed = self._parse_json_response(response["content"])

        item = ContentItem(
            id=self._next_id(),
            title=parsed.get("title", ""),
            summary=parsed.get("summary", ""),
            body=parsed.get("body", ""),
            tags=parsed.get("tags", []),
            topic=parsed.get("topic", "行业动态"),
            platform="douyin",
            status="draft",
        )

        # 合规检查
        compliance = check_compliance(item.title, item.body)
        if compliance.flags:
            logger.warning(f"合规标记: {item.id} risk={compliance.risk_level}")

        return item

    def generate(
        self,
        topic: str = "技术分析",
        direction: str = "",
        *,
        dry_run: bool = False,
        extra_context: str = "",
    ) -> ContentItem:
        """
        直接根据主题生成文章（不依赖资讯聚合）。

        Args:
            topic: 话题分类
            direction: 具体方向
            dry_run: 测试模式
            extra_context: 额外上下文（如用户提供的链接或文本）
        """
        if dry_run:
            return ContentItem(
                id=self._next_id(),
                title="[DRY RUN] DeepSeek-V3 技术报告解读：MoE 架构的新进展",
                summary="DeepSeek V3 采用 MoE 架构，性能比肩 GPT-4",
                body="DeepSeek 近日发布了 V3 模型的技术报告。"
                     "在推理效率上相比前代有显著提升。报告显示，V3 在多个基准测试中达到了与 "
                     "GPT-4 相当的性能水平。",
                tags=["DeepSeek", "MoE", "大模型", "技术解读"],
                topic=topic,
                platform="douyin",
                status="draft",
            )

        user_message = f"""话题：{topic}
方向：{direction or '请选择一个有价值的 AI 技术主题'}"""

        if extra_context:
            user_message += f"\n\n参考素材：\n{extra_context}"

        response = self.router.call(
            task="content_gen",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=2000,
            temperature=0.7,
        )

        parsed = self._parse_json_response(response["content"])

        item = ContentItem(
            id=self._next_id(),
            title=parsed.get("title", ""),
            summary=parsed.get("summary", ""),
            body=parsed.get("body", ""),
            tags=parsed.get("tags", []),
            topic=parsed.get("topic", topic),
            platform="douyin",
            status="draft",
        )

        compliance = check_compliance(item.title, item.body)
        if compliance.flags:
            logger.warning(f"合规标记: {item.id} risk={compliance.risk_level}")

        return item


# 便捷函数
_default_writer: ContentWriter | None = None


def get_writer() -> ContentWriter:
    global _default_writer
    if _default_writer is None:
        _default_writer = ContentWriter()
    return _default_writer
