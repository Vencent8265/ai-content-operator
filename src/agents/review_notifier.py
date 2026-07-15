"""
审核推送 Agent
─────────────
职责：将生成的文章推送到微信供人工审核，解析审核回复。

用法：
    notifier = ReviewNotifier()
    notifier.send_for_review(content_item)       # 推送到微信
    result = notifier.parse_reply("通过")         # 解析用户回复
    result = notifier.parse_reply("驳回:标题太夸张了")  # 解析驳回+原因
"""

import logging
import subprocess
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal

from ..contracts.schemas import ContentItem, ReviewResult
from ..utils.compliance_filter import check_compliance, ComplianceResult

logger = logging.getLogger(__name__)

# 推送目标（微信 + 飞书）
WECHAT_TARGET = "weixin:o9cq80zsimutxfYumlCLtlaoTNN4@im.wechat"
FEISHU_TARGET = "feishu:oc_434e3f5c39328ab277afc306472846f0"
ALL_TARGETS = [WECHAT_TARGET, FEISHU_TARGET]


# ══════════════════════════════════════════════════════════════
# 审核回复解析
# ══════════════════════════════════════════════════════════════

# 通过类的回复模式
APPROVE_PATTERNS = [
    r"^通过$", r"^ok$", r"^OK$", r"^可以$", r"^发吧$", r"^没问题$",
    r"^批准$", r"^同意$", r"^发$", r"^行$", r"^好$", r"^好的$",
    r"^yes$", r"^Y$", r"^y$", r"^1$", r"^√$", r"^✓$",
]

# 驳回类的回复模式（提取原因）
REJECT_PATTERNS = [
    r"^驳回[:：]?(.*)$", r"^拒绝[:：]?(.*)$", r"^不行[:：]?(.*)$",
    r"^重写[:：]?(.*)$", r"^打回[:：]?(.*)$", r"^no[:：]?(.*)$",
    r"^不通过[:：]?(.*)$", r"^有问题[:：]?(.*)$",
]

# 需要修改类的回复模式
REVISION_PATTERNS = [
    r"^修改[:：]?(.*)$", r"^改改[:：]?(.*)$", r"^调整[:：]?(.*)$",
    r"^优化[:：]?(.*)$", r"^润色[:：]?(.*)$",
    r"^改一下[:：]?(.*)$", r"^改[:：]?(.*)$",
]


@dataclass
class ParsedReply:
    """解析后的审核回复"""
    decision: Literal["approved", "rejected", "needs_revision", "unknown"]
    reason: str = ""
    raw_text: str = ""


def parse_reply(text: str) -> ParsedReply:
    """
    解析用户的审核回复。

    支持自然语言：
      "通过" / "ok" / "发吧"       → approved
      "驳回:标题太夸张"              → rejected，原因="标题太夸张"
      "修改:把开头改得更有吸引力"     → needs_revision，原因="把开头改得更有吸引力"
      "改一下"                      → needs_revision
    """
    text = text.strip()

    # 1. 检查驳回模式
    for pattern in REJECT_PATTERNS:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            return ParsedReply(
                decision="rejected",
                reason=m.group(1).strip() if m.group(1) else "",
                raw_text=text,
            )

    # 2. 检查修改模式
    for pattern in REVISION_PATTERNS:
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            return ParsedReply(
                decision="needs_revision",
                reason=m.group(1).strip() if m.group(1) else "",
                raw_text=text,
            )

    # 3. 检查通过模式
    for pattern in APPROVE_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return ParsedReply(decision="approved", raw_text=text)

    # 4. 无法识别
    return ParsedReply(decision="unknown", raw_text=text)


# ══════════════════════════════════════════════════════════════
# ReviewNotifier
# ══════════════════════════════════════════════════════════════

class ReviewNotifier:
    """
    审核推送 Agent。

    用法：
        notifier = ReviewNotifier()
        notifier.send_for_review(item)   # 推送微信
        # 用户回复后：
        result = notifier.handle_reply("通过", item)
    """

    def __init__(self, wechat_target: str | None = None):
        self.wechat_target = wechat_target or WECHAT_TARGET
        self.targets = ALL_TARGETS

    def format_message(self, item: ContentItem) -> str:
        """将 ContentItem 格式化为微信审核消息"""
        # 合规检查
        compliance = check_compliance(item.title, item.body)

        # 风险标记符号
        risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(
            compliance.risk_level, "⚪"
        )

        tags_str = " ".join(f"#{t}" for t in item.tags)

        # 正文摘要（截取前 200 字）
        body_preview = item.body[:200]
        if len(item.body) > 200:
            body_preview += "..."

        msg = f"""📝 待审核文章

【标题】{item.title}
【话题】{item.topic}
【标签】{tags_str}
【字数】{item.word_count} 字
【合规】{risk_icon} {compliance.risk_level}"""

        if compliance.flags:
            for flag in compliance.flags[:3]:  # 最多显示 3 个标记
                msg += f"\n  ⚠️ {flag}"

        msg += f"""

【正文预览】
{body_preview}

───────────────
请回复审核意见：
  • 回复「通过」→ 发布
  • 回复「驳回:原因」→ 不发布并记录原因
  • 回复「修改:要求」→ 按要���修改后重新审核"""

        return msg

    def send_for_review(self, item: ContentItem) -> bool:
        """
        将文章推送到审核（微信 + 飞书）。
        """
        msg = self.format_message(item)
        success = False

        for target in self.targets:
            try:
                result = subprocess.run(
                    ["hermes", "send", "--to", target, msg],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    logger.info(f"审核推送成功 [{target}]: {item.id}")
                    success = True
                else:
                    logger.warning(f"审核推送失败 [{target}]: {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                logger.warning(f"审核推送超时 [{target}]")
            except FileNotFoundError:
                logger.error("hermes 命令不可用")
                return False

        return success

    def handle_reply(self, reply_text: str, item: ContentItem) -> ReviewResult:
        """
        处理用户审核回复。

        Args:
            reply_text: 用户在微信或聊天中的回复文本
            item: 对应的文章

        Returns:
            ReviewResult: 结构化的审核结果
        """
        parsed = parse_reply(reply_text)

        return ReviewResult(
            content_id=item.id,
            decision=parsed.decision,
            reviewer="human",
            comments=parsed.reason or parsed.raw_text,
            risk_flags=[],
            reviewed_at=datetime.now(),
        )

    def send_review_result(self, result: ReviewResult) -> bool:
        """审核结果回执（双平台）"""
        decision_map = {
            "approved": "✅ 已通过，进入发布流程",
            "rejected": f"❌ 已驳回" + (f"：{result.comments}" if result.comments else ""),
            "needs_revision": f"✏️ 需修改" + (f"：{result.comments}" if result.comments else ""),
            "unknown": "❓ 未识别，请回复「通过」「驳回:原因」或「修改:要求」",
        }
        msg = decision_map.get(result.decision, "未知操作")

        for target in self.targets:
            try:
                subprocess.run(
                    ["hermes", "send", "--to", target, msg],
                    capture_output=True, timeout=15,
                )
            except Exception as e:
                logger.warning(f"审核结果推送失败 [{target}]: {e}")
        return True
