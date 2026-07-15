"""
内容生成 Agent
─────────────
职责：根据选题生成一篇符合抖音风格的 AI 知识文章。
输入：话题标签 + 可选的方向描述
输出：ContentItem（含标题、正文、标签、合规标记）
"""

import logging
from datetime import datetime
from typing import Optional

from ..models.adapter import ModelRouter, create_default_router
from ..contracts.schemas import ContentItem
from ..utils.compliance_filter import check_compliance, ComplianceResult

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 选题模板库
# ══════════════════════════════════════════════════════════════

# 预定义的选题方向，避免每次从零想话题
TOPIC_POOL = {
    "技术解读": [
        "通俗解释一个大模型概念（如 RAG、Agent、Function Calling）",
        "对比两个 AI 工具的优缺点",
        "解读一篇最新的 AI 论文（去技术化，讲给普通人听）",
    ],
    "工具教程": [
        "手把手教你用一个 AI 工具（如 Cursor、ChatGPT、Hermes）",
        "AI + 某个领域的实用技巧（如 AI + Excel、AI + 写作）",
    ],
    "行业新闻": [
        "本周 AI 领域最重要的 3 件事",
        "某大厂的 AI 战略解读",
    ],
    "观点/思考": [
        "AI 时代普通人该怎么学习",
        "一个 AI 从业者的日常是什么样的",
    ],
}


# ══════════════════════════════════════════════════════════════
# System Prompt
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个 AI 知识领域的专业内容创作者，负责为抖音平台撰写科普文章。

## 你的写作风格
- 口语化、有网感，像在和读者聊天，不要学术论文腔
- 开篇前 3 句必须抓住注意力（可以用提问、反常识数据、场景描述）
- 每段不超过 3-4 行手机屏幕，善用短句和换行
- 适当使用 emoji 增加可读性（但不要过度）

## 内容要求
- 准确：技术概念不能有硬伤，不确定的地方标注"目前业界还在探索"
- 实用：读者看完能带走一个知识点或一个能用的技巧
- 正向：不制造焦虑，不夸大 AI 威胁，不推荐投资建议
- 字数：300-800 字（抖音图文/口播脚本的最佳长度）

## 输出格式
用 JSON 格式输出，包含：
- title: 标题（15-30 字，有吸引力）
- body: 正文（Markdown 格式，不用 # 标题，用自然分段）
- tags: 3-5 个标签
- topic: 话题分类（技术解读/工具教程/行业新闻/观点思考）"""


# ══════════════════════════════════════════════════════════════
# ContentWriter
# ══════════════════════════════════════════════════════════════

class ContentWriter:
    """
    内容生成 Agent。

    用法:
        writer = ContentWriter()
        item = writer.generate(topic="技术解读", direction="讲讲什么是 RAG")
        # item 是一个 ContentItem，可以直接丢给审核流程
    """

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or create_default_router()
        self._id_counter = 0

    def _next_id(self) -> str:
        """生成文章唯一 ID"""
        self._id_counter += 1
        date_str = datetime.now().strftime("%Y%m%d")
        return f"content_{date_str}_{self._id_counter:03d}"

    def _suggest_topic(self, topic: str, direction: str) -> str:
        """如果有选题池匹配，使用模板；否则直接用用户输入"""
        if topic in TOPIC_POOL and not direction:
            import random
            directions = TOPIC_POOL[topic]
            direction = random.choice(directions)
            logger.info(f"从选题池随机选择方向: {direction}")
        return direction or topic

    def _parse_json_response(self, raw_text: str) -> dict:
        """从 LLM 返回的文本中提取 JSON"""
        import json
        import re

        # 尝试找 ```json ... ``` 代码块
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, re.DOTALL)
        if json_match:
            raw_text = json_match.group(1)

        # 尝试找 { ... } 块
        brace_match = re.search(r'\{[\s\S]*\}', raw_text)
        if brace_match:
            raw_text = brace_match.group(0)

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            # 最后的 fallback：尝试修复常见问题
            cleaned = raw_text.replace('\n', ' ').replace('，', ',')
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                raise ValueError(f"无法解析 LLM 返回的 JSON: {e}\n原始内容前 300 字: {raw_text[:300]}")

    def generate(
        self,
        topic: str,
        direction: str = "",
        *,
        extra_instructions: str = "",
        dry_run: bool = False,
    ) -> ContentItem:
        """
        根据选题生成一篇 AI 知识文章。

        Args:
            topic: 话题分类，如 "技术解读"、"工具教程"
            direction: 具体方向/角度，留空则从选题池随机选
            extra_instructions: 额外的写作要求（如 "今天要讲 Transformer"）
            dry_run: True 时不实际调用 LLM，返回模拟数据（测试用）

        Returns:
            ContentItem: 完整的文章数据，含合规检查结果
        """
        # 1. 确定选题
        resolved_direction = self._suggest_topic(topic, direction)

        user_message = f"""话题分类：{topic}
写作方向：{resolved_direction}"""

        if extra_instructions:
            user_message += f"\n额外要求：{extra_instructions}"

        user_message += "\n\n请生成一篇 AI 知识科普文章。"

        if dry_run:
            # 测试模式，返回模拟数据
            return ContentItem(
                id=self._next_id(),
                title="[DRY RUN] 什么是大语言模型？三分钟讲明白",
                body="大语言模型就是训练了大量文本后，学会了理解语言规律的 AI。\n\n你可以把它理解成一个读过整个图书馆的人。\n\n它能写文章、翻译、写代码，但本质上是「预测下一个词」。",
                tags=["AI", "大模型", "科普", "ChatGPT"],
                topic=topic,
                platform="douyin",
                status="draft",
            )

        # 2. 调用 LLM 生成
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        response = self.router.call(
            task="content_gen",
            messages=messages,
            max_tokens=2000,
            temperature=0.8,  # 写作任务需要一定创造性
        )

        # 3. 解析结果
        parsed = self._parse_json_response(response["content"])

        # 4. 构建 ContentItem
        item = ContentItem(
            id=self._next_id(),
            title=parsed.get("title", ""),
            body=parsed.get("body", ""),
            tags=parsed.get("tags", []),
            topic=parsed.get("topic", topic),
            platform="douyin",
            status="draft",
        )

        # 5. 合规检查
        compliance = check_compliance(item.title, item.body)
        if not compliance.passed or compliance.flags:
            logger.warning(
                f"内容 {item.id} 合规检查发现问题: "
                f"risk={compliance.risk_level}, flags={compliance.flags}"
            )

        # 把合规结果附在 ContentItem 的上下文中（通过 status 和后续处理）
        # 注意：这里不直接改 ContentItem 的 status，
        # 由审核 Agent 根据 compliance 结果决定是否打回

        return item


# ══════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════

_default_writer: ContentWriter | None = None


def get_writer() -> ContentWriter:
    """获取全局单例 ContentWriter"""
    global _default_writer
    if _default_writer is None:
        _default_writer = ContentWriter()
    return _default_writer


def generate_article(topic: str, direction: str = "", **kwargs) -> ContentItem:
    """快捷生成一篇文章"""
    return get_writer().generate(topic, direction, **kwargs)
