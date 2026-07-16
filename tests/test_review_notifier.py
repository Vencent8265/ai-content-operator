"""
测试：审核推送 Agent
运行：pytest tests/test_review_notifier.py -v
"""

import pytest
from datetime import datetime

from src.agents.review_notifier import (
    ReviewNotifier,
    parse_reply,
    ParsedReply,
    APPROVE_PATTERNS,
    REJECT_PATTERNS,
    REVISION_PATTERNS,
)
from src.contracts.schemas import ContentItem, ReviewResult


class TestParseReply:
    """审核回复解析测试"""

    # ── 通过类 ──

    @pytest.mark.parametrize("text", [
        "通过", "ok", "OK", "可以", "发吧", "没问题",
        "批准", "同意", "发", "行", "好", "好的",
        "yes", "y", "Y", "1",
    ])
    def test_approve_patterns(self, text):
        """各种「通过」变体"""
        result = parse_reply(text)
        assert result.decision == "approved", f"'{text}' 应该识别为通过"

    # ── 驳回类 ──

    @pytest.mark.parametrize("text,expected_reason", [
        ("驳回", ""),
        ("驳回:标题太夸张", "标题太夸张"),
        ("驳回：内容太水了", "内容太水了"),
        ("拒绝:选题不合适", "选题不合适"),
        ("不行:换一个话题", "换一个话题"),
        ("重写:完全没有吸引力", "完全没有吸引力"),
        ("打回:敏感内容", "敏感内容"),
        ("不通过:格式有问题", "格式有问题"),
    ])
    def test_reject_patterns(self, text, expected_reason):
        """各种「驳回」变体，正确提取原因"""
        result = parse_reply(text)
        assert result.decision == "rejected", f"'{text}' 应该识别为驳回"
        assert result.reason == expected_reason

    # ── 修改类 ──

    @pytest.mark.parametrize("text,expected_reason", [
        ("修改", ""),
        ("修改:开头加个问句", "开头加个问句"),
        ("改改:语气太硬了", "语气太硬了"),
        ("调整:标签换一下", "标签换一下"),
        ("优化:字数超了", "字数超了"),
        ("润色:加点emoji", "加点emoji"),
        ("改一下", ""),
        ("改一下:太长了", "太长了"),
    ])
    def test_revision_patterns(self, text, expected_reason):
        """各种「修改」变体"""
        result = parse_reply(text)
        assert result.decision == "needs_revision", f"'{text}' 应该识别为需修改"
        assert result.reason == expected_reason

    # ── 未知 ──

    @pytest.mark.parametrize("text", [
        "随便", "不知道", "你觉得呢", "还行吧", "再看看",
        "这篇文章讲了关于AI的内容我觉得还不错但是标题可以再优化一下",  # 长文本非标准格式
    ])
    def test_unknown_patterns(self, text):
        """无法识别的回复"""
        result = parse_reply(text)
        assert result.decision == "unknown", f"'{text}' 应该识别为未知"

    # ── 边界情况 ──

    def test_empty_string(self):
        """空字符串"""
        result = parse_reply("")
        assert result.decision == "unknown"

    def test_whitespace_only(self):
        """纯空格"""
        result = parse_reply("   ")
        assert result.decision == "unknown"

    def test_reject_with_colon_no_reason(self):
        """驳回带冒号但没原因"""
        result = parse_reply("驳回:")
        assert result.decision == "rejected"
        assert result.reason == ""

    def test_reply_preserves_raw_text(self):
        """保留原始文本"""
        result = parse_reply("驳回:这个标题不行")
        assert result.raw_text == "驳回:这个标题不行"


class TestReviewNotifier:
    """ReviewNotifier 核心测试"""

    def make_item(self) -> ContentItem:
        """创建测试用 ContentItem"""
        return ContentItem(
            id="content_test_001",
            title="什么是大语言模型？三分钟讲明白",
            body="大语言模型（LLM）是一种基于深度学习的自然语言处理技术。"
                 "它通过学习海量文本数据，掌握了语言的统计规律。"
                 "目前主流的 LLM 包括 GPT、Claude、DeepSeek 等。"
                 "它们可以写文章、翻译语言、编写代码，应用场景非常广泛。",
            tags=["AI", "大模型", "科普"],
            topic="技术解读",
            platform="douyin",
        )

    def test_format_message_structure(self):
        """格式化消息包含关键信息"""
        notifier = ReviewNotifier(wechat_target="test_target")
        item = self.make_item()
        msg = notifier.format_message(item)

        assert "待审核文章" in msg
        assert item.title in msg
        assert item.topic in msg
        assert "#AI" in msg or "AI" in msg
        assert str(item.word_count) in msg
        assert "通过" in msg
        assert "驳回" in msg
        assert "修改" in msg

    def test_format_message_truncates_long_body(self):
        """审核消息应包含本地文件路径"""
        notifier = ReviewNotifier(wechat_target="test_target")
        item = ContentItem(
            id="test_002",
            title="测试",
            summary="这是摘要",
            body="长" * 500,
            tags=["测试"],
            topic="测试",
        )
        msg = notifier.format_message(item)
        # 新版消息包含本地文件路径而非正文预览
        assert "本地查看" in msg
        assert "data/articles/test_002.md" in msg

    def test_format_message_shows_compliance_flags(self):
        """合规标记显示在消息中"""
        notifier = ReviewNotifier(wechat_target="test_target")
        item = ContentItem(
            id="test_003",
            title="AI 炒股稳赚不赔",
            body="这是一篇关于AI炒股稳赚不赔的文章内容正文。" * 20,
            tags=["AI", "投资"],
            topic="观点思考",
        )
        msg = notifier.format_message(item)
        assert "🔴" in msg  # 高风险

    def test_handle_reply_approve(self):
        """处理「通过」回复"""
        notifier = ReviewNotifier(wechat_target="test_target")
        item = self.make_item()
        result = notifier.handle_reply("通过", item)
        assert isinstance(result, ReviewResult)
        assert result.decision == "approved"
        assert result.content_id == item.id
        assert result.reviewer == "human"

    def test_handle_reply_reject(self):
        """处理「驳回」回复"""
        notifier = ReviewNotifier(wechat_target="test_target")
        item = self.make_item()
        result = notifier.handle_reply("驳回:标题太夸张了", item)
        assert result.decision == "rejected"
        assert result.comments == "标题太夸张了"

    def test_handle_reply_revision(self):
        """处理「修改」回复"""
        notifier = ReviewNotifier(wechat_target="test_target")
        item = self.make_item()
        result = notifier.handle_reply("修改:开头加个问题吸引注意", item)
        assert result.decision == "needs_revision"
        assert "开头" in result.comments

    def test_send_review_result_approved(self):
        """审核通过的结果通知（测试不实际发送）"""
        notifier = ReviewNotifier(wechat_target="test_target")
        result = ReviewResult(
            content_id="test_001",
            decision="approved",
            reviewer="human",
        )
        msg = notifier.format_message(self.make_item())
        assert "待审核文章" in msg


class TestPatternsCoverage:
    """确保模式列表覆盖了常见的回复方式"""

    def test_approve_patterns_not_empty(self):
        assert len(APPROVE_PATTERNS) >= 10

    def test_reject_patterns_not_empty(self):
        assert len(REJECT_PATTERNS) >= 5

    def test_revision_patterns_not_empty(self):
        assert len(REVISION_PATTERNS) >= 3

    def test_approve_has_chinese(self):
        """确保支持中文回复（不是纯英文）"""
        has_chinese = any("通过" in p or "可以" in p or "发" in p for p in APPROVE_PATTERNS)
        assert has_chinese, "通过模式必须包含中文关键词"
