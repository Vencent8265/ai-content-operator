"""
发文排版工具
──────────
将 ContentItem 组装成抖音文章发布所需的完整格式，包含头图、封面、话题标签。
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.schemas import ContentItem

logger = logging.getLogger(__name__)


@dataclass
class PublishCard:
    """抖音文章发布所需的完整信息"""
    title: str              # 标题 ≤30字
    summary: str            # 摘要 ≤30字
    body: str               # 正文（带一二级标题）
    tags: list[str]         # 标签
    topic_tags: list[str]   # 参与话题（抖音 #话题 格式）
    header_image_url: str   # 头图 URL
    cover_image_url: str    # 封面 URL（AI 生成）
    header_image_prompt: str = ""  # 头图的搜索关键词
    cover_image_prompt: str = ""   # 封面生成提示词


class PublishFormatter:
    """将内容格式化为发布卡片"""

    def format(self, item: ContentItem, header_image_url: str = "",
               cover_image_url: str = "", topic_tags: list[str] | None = None) -> PublishCard:
        """
        组装完整的发布卡片。

        Args:
            item: 内容项
            header_image_url: 头图 URL
            cover_image_url: 封面 URL
            topic_tags: 参与话题列表（如 ["#AI", "#DeepSeek"]）
        """
        return PublishCard(
            title=item.title[:30],
            summary=item.summary[:30],
            body=item.body,
            tags=item.tags,
            topic_tags=topic_tags or [f"#{t}" for t in item.tags[:3]],
            header_image_url=header_image_url,
            cover_image_url=cover_image_url,
            header_image_prompt=f"{item.topic} {item.title}",
            cover_image_prompt=f"AI技术封面图 {item.tags[0] if item.tags else ''} 简洁科技风格",
        )

    def to_publish_doc(self, card: PublishCard) -> str:
        """生成 Markdown 格式的发布文档，可直接在 VSCode 查看"""
        topics = " ".join(card.topic_tags)

        return f"""# 抖音文章发布卡

## 基础信息
| 字段 | 内容 |
|------|------|
| 标题 | {card.title} |
| 摘要 | {card.summary} |
| 话题 | {topics} |
| 标签 | {' '.join(f'#{t}' for t in card.tags)} |

## 头图
搜索关键词: {card.header_image_prompt}
图片链接: {card.header_image_url or '（待手动配图）'}

## 封面（AI生成）
生成提示词: {card.cover_image_prompt}
图片链接: {card.cover_image_url or '（待生成）'}

---

## 正文

{card.body}

---

## 发布步骤
1. 打开抖音创作者中心 → 文章发布
2. 复制标题、摘要
3. 上传头图和封面
4. 粘贴正文
5. 添加参与话题
6. 预览 → 发布
"""
