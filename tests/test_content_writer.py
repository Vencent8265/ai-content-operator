"""
测试：内容生成 Agent
运行：pytest tests/test_content_writer.py -v
"""

import pytest
from datetime import datetime

from src.agents.content_writer import ContentWriter, SYSTEM_PROMPT, TOPIC_POOL
from src.contracts.schemas import ContentItem
from src.utils.compliance_filter import check_compliance, ComplianceResult


class TestContentWriter:
    """ContentWriter 基础测试"""

    def test_init_creates_default_router(self):
        """初始化时自动创建 ModelRouter"""
        writer = ContentWriter()
        assert writer.router is not None
        assert writer.router._models  # 有注册的模型

    def test_next_id_format(self):
        """文章 ID 格式：content_YYYYMMDD_NNN"""
        writer = ContentWriter()
        id1 = writer._next_id()
        today = datetime.now().strftime("%Y%m%d")
        assert id1 == f"content_{today}_001"

        id2 = writer._next_id()
        assert id2 == f"content_{today}_002"

    def test_suggest_topic_with_pool(self):
        """有选题池匹配时，从选题池选方向"""
        writer = ContentWriter()
        direction = writer._suggest_topic("技术解读", "")
        # 应该从 TOPIC_POOL["技术解读"] 中选了一个
        assert direction in TOPIC_POOL["技术解读"]

    def test_suggest_topic_with_user_direction(self):
        """用户指定方向时，使用用户输入"""
        writer = ContentWriter()
        direction = writer._suggest_topic("技术解读", "讲讲 Transformer")
        assert direction == "讲讲 Transformer"

    def test_suggest_topic_no_pool_match(self):
        """选题池没有匹配时，用 topic 本身"""
        writer = ContentWriter()
        direction = writer._suggest_topic("不存在的话题", "")
        assert direction == "不存在的话题"

    def test_parse_json_from_code_block(self):
        """能从 markdown 代码块中提取 JSON"""
        writer = ContentWriter()
        text = '```json\n{"title": "测试", "body": "内容", "tags": ["AI"], "topic": "test"}\n```'
        result = writer._parse_json_response(text)
        assert result["title"] == "测试"
        assert result["tags"] == ["AI"]

    def test_parse_json_plain(self):
        """能解析纯 JSON"""
        writer = ContentWriter()
        text = '{"title": "测试", "body": "内容", "tags": ["AI"], "topic": "test"}'
        result = writer._parse_json_response(text)
        assert result["title"] == "测试"

    def test_parse_json_invalid_raises(self):
        """非法 JSON 抛出异常"""
        writer = ContentWriter()
        with pytest.raises(ValueError, match="无法解析"):
            writer._parse_json_response("这不是 JSON")

    def test_dry_run_returns_content_item(self):
        """dry_run 模式返回模拟 ContentItem"""
        writer = ContentWriter()
        item = writer.generate(topic="技术解读", direction="测试", dry_run=True)
        assert isinstance(item, ContentItem)
        assert item.status == "draft"
        assert item.platform == "douyin"
        assert "[DRY RUN]" in item.title

    def test_system_prompt_contains_douyin_style(self):
        """System prompt 包含抖音风格要求"""
        assert "抖音" in SYSTEM_PROMPT
        assert "口语化" in SYSTEM_PROMPT
        assert "网感" in SYSTEM_PROMPT


class TestComplianceFilter:
    """合规过滤器测试"""

    def test_clean_content_passes(self):
        """正常内容通过检测"""
        result = check_compliance(
            title="什么是大语言模型？三分钟讲明白",
            body="大语言模型（LLM）是一种基于深度学习的自然语言处理技术。"
                 "它通过学习海量文本数据，掌握了语言的统计规律。"
                 "目前主流的 LLM 包括 GPT、Claude、DeepSeek 等。"
                 "它们可以写文章、翻译语言、编写代码，应用场景非常广泛。"
                 "但 LLM 本质上是「预测下一个词」的数学模型，并不真正理解语义。"
                 "不过，这并不影响它们在日常工作中的实用价值，越来越多的人开始使用 AI 辅助工作。"
                 "未来，LLM 将继续进化，更好地辅助人类工作。"
        )
        assert result.passed is True
        assert result.risk_level == "low"

    def test_high_risk_word_triggers(self):
        """高危词触发高风险"""
        result = check_compliance(
            title="AI 炒股稳赚不赔的秘密",
            body="用这个 AI 工具，稳赚不赔，日入过万。"
        )
        assert result.passed is False
        assert result.risk_level == "high"
        assert any("稳赚" in f for f in result.flags) or any("日入" in f for f in result.flags)

    def test_sensitive_word_triggers_medium(self):
        """敏感词触发中等风险"""
        result = check_compliance(
            title="AI 会取代人类吗？",
            body="很多人担心 AI 最终会取代人类..."
        )
        assert "取代人类" in str(result.flags)

    def test_short_body_flags(self):
        """正文过短触发标记"""
        result = check_compliance(
            title="AI 入门指南",
            body="AI 很有趣。"
        )
        assert any("过短" in f for f in result.flags)

    def test_long_title_flags(self):
        """标题过长触发标记"""
        result = check_compliance(
            title="这是一个超级超级超级超级超级超级超级超级超级超级超级超级长的标题" + "长" * 30,
            body="这是正文内容，足够长的正文内容来通过字数检查。" * 20,
        )
        assert any("标题" in f and "50" in f for f in result.flags)

    def test_url_in_content_flags(self):
        """包含链接触发标记"""
        result = check_compliance(
            title="AI 工具推荐",
            body="推荐这个工具 https://example.com 很好用"
        )
        assert any("链接" in f for f in result.flags)

    def test_ai_content_flag_medical(self):
        """AI 医疗相关内容触发标记"""
        result = check_compliance(
            title="AI 在医疗诊断中的应用",
            body="现在的 AI 已经可以完全替代医生进行医疗诊断了。"
        )
        assert any("医疗诊断" in f for f in result.flags)

    def test_no_false_positive_on_normal_ai_talk(self):
        """正常 AI 讨论不应该被误判"""
        result = check_compliance(
            title="推荐 3 个好用的 AI 编程工具",
            body="Copilot 可以帮你自动补全代码，Cursor 可以理解你的项目上下文，Hermes 能帮你完成复杂的开发任务。"
        )
        # 正常的 AI 工具推荐不应该有高危/敏感标记
        assert result.risk_level == "low"


class TestTopicPool:
    """选题池测试"""

    def test_all_categories_have_directions(self):
        """所有话题分类都有至少一个方向"""
        for category, directions in TOPIC_POOL.items():
            assert len(directions) > 0, f"{category} 没有方向"
            assert all(isinstance(d, str) for d in directions)

    def test_categories_match_contract(self):
        """分类名称和 ContentItem 的话题一致"""
        valid_topics = set(TOPIC_POOL.keys())
        # ContentItem 不限制 topic 值，但推荐用这些
        assert "技术解读" in valid_topics
        assert "工具教程" in valid_topics
