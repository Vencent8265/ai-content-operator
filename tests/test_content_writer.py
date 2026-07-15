"""
测试：内容生成 Agent v2
运行：pytest tests/test_content_writer.py -v
"""

import pytest
import json
from datetime import datetime

from src.agents.content_writer import ContentWriter, SYSTEM_PROMPT
from src.contracts.schemas import ContentItem
from src.utils.compliance_filter import check_compliance


class TestContentWriter:
    """ContentWriter v2 测试"""

    def test_init_creates_default_router(self):
        writer = ContentWriter()
        assert writer.router is not None
        assert writer.router._models

    def test_next_id_format(self):
        writer = ContentWriter()
        id1 = writer._next_id()
        today = datetime.now().strftime("%Y%m%d")
        assert id1 == f"content_{today}_001"
        id2 = writer._next_id()
        assert id2 == f"content_{today}_002"

    def test_parse_json_from_code_block(self):
        writer = ContentWriter()
        text = '```json\n{"title": "测试", "body": "内容", "tags": ["AI"], "topic": "test"}\n```'
        result = writer._parse_json_response(text)
        assert result["title"] == "测试"

    def test_parse_json_plain(self):
        writer = ContentWriter()
        text = '{"title": "测试", "body": "内容", "tags": ["AI"], "topic": "test"}'
        result = writer._parse_json_response(text)
        assert result["title"] == "测试"

    def test_parse_json_invalid_raises(self):
        writer = ContentWriter()
        with pytest.raises((ValueError, json.JSONDecodeError)):
            writer._parse_json_response("这不是 JSON")

    def test_dry_run_returns_content_item(self):
        writer = ContentWriter()
        item = writer.generate(topic="技术分析", dry_run=True)
        assert isinstance(item, ContentItem)
        assert item.status == "draft"
        assert item.platform == "douyin"
        assert "[DRY RUN]" in item.title
        # v2: 标题不应有 emoji
        assert "🤖" not in item.title
        assert "🧠" not in item.title

    def test_system_prompt_no_emoji_requirement(self):
        """v2 System prompt 不应要求使用 emoji"""
        assert "适当使用 emoji" not in SYSTEM_PROMPT
        assert "网感" not in SYSTEM_PROMPT
        assert "口语化" not in SYSTEM_PROMPT

    def test_system_prompt_professional_style(self):
        """v2 System prompt 应提及专业技术分享"""
        assert "专业" in SYSTEM_PROMPT
        assert "技术分享" in SYSTEM_PROMPT or "从业者" in SYSTEM_PROMPT


class TestComplianceFilter:
    """合规过滤器测试（不变）"""

    def test_clean_content_passes(self):
        result = check_compliance(
            title="DeepSeek-V3 技术报告解读",
            body="DeepSeek 近日发布了 V3 模型的技术报告。该模型采用混合专家架构（MoE），"
                 "在推理效率上相比前代有显著提升。报告显示，V3 在多个基准测试中达到了与 "
                 "GPT-4 相当的性能水平。这是中文 AI 社区的一个重要里程碑。"
                 "我们将持续关注该模型的开源进展和社区反馈。"
        )
        assert result.passed is True
        assert result.risk_level == "low"

    def test_high_risk_word_triggers(self):
        result = check_compliance(
            title="AI 炒股稳赚不赔的秘密",
            body="用这个 AI 工具，稳赚不赔，日入过万。"
        )
        assert result.passed is False
        assert result.risk_level == "high"

    def test_sensitive_word_triggers_medium(self):
        result = check_compliance(
            title="AI 会取代人类吗？",
            body="很多人担心 AI 最终会取代人类..."
        )
        assert "取代人类" in str(result.flags)

    def test_short_body_flags(self):
        result = check_compliance(
            title="AI 入门指南",
            body="AI 很有趣。"
        )
        assert any("过短" in f for f in result.flags)

    def test_no_false_positive_on_tech_article(self):
        """技术文章不应被误判"""
        result = check_compliance(
            title="Transformer 架构详解：从 Attention 到多头注意力",
            body="Transformer 架构的核心是自注意力机制。它允许模型在处理序列时，"
                 "同时关注序列中所有位置的信息，而不是像 RNN 那样逐步处理。"
                 "这种并行化特性使得 Transformer 在大规模训练中具有显著优势。"
                 "多头注意力则进一步增强了模型对不同位置关系的捕捉能力。"
        )
        assert result.risk_level == "low"
