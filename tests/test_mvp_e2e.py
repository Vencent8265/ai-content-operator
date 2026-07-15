"""
MVP 端到端集成测试
─────────────────
验证从内容生成到复盘的完整链路（dry run 模式，不调 LLM、不推微信）。

运行：pytest tests/test_mvp_e2e.py -v
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.agents.content_writer import ContentWriter
from src.agents.review_notifier import ReviewNotifier, parse_reply
from src.agents.daily_reviewer import DailyReviewer
from src.tools.data_collector import ManualCollector
from src.contracts.schemas import (
    ContentItem, ReviewResult, DataPoint, DataReport, ReviewSummary,
)


class TestMVPFullPipeline:
    """完整 MVP 流水线测试"""

    @pytest.fixture
    def writer(self):
        return ContentWriter()

    @pytest.fixture
    def notifier(self):
        return ReviewNotifier(wechat_target="test_target")

    @pytest.fixture
    def collector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield ManualCollector("douyin", data_dir=tmpdir)

    def test_pipeline_content_generation(self, writer):
        """步骤1：dry run 生成文章，输出格式正确"""
        item = writer.generate(topic="技术解读", direction="测试", dry_run=True)
        assert isinstance(item, ContentItem)
        assert item.status == "draft"
        assert item.platform == "douyin"
        assert len(item.title) > 0
        assert len(item.body) > 0
        assert len(item.tags) > 0

    def test_pipeline_review_push_format(self, writer, notifier):
        """步骤2：审核消息格式正确"""
        item = writer.generate(topic="技术解读", dry_run=True)
        msg = notifier.format_message(item)
        assert "待审核文章" in msg
        assert item.title in msg
        assert "通过" in msg
        assert "驳回" in msg

    def test_pipeline_review_approve_flow(self, writer, notifier):
        """步骤3：审核通过流程"""
        item = writer.generate(topic="技术解读", dry_run=True)
        result = notifier.handle_reply("通过", item)
        assert result.decision == "approved"
        assert result.content_id == item.id

    def test_pipeline_review_reject_flow(self, writer, notifier):
        """步骤3b：驳回流程"""
        item = writer.generate(topic="技术解读", dry_run=True)
        result = notifier.handle_reply("驳回:标题太夸张", item)
        assert result.decision == "rejected"
        assert "标题太夸张" in result.comments

    def test_pipeline_data_collection(self, writer, collector):
        """步骤4：数据回收"""
        item = writer.generate(topic="技术解读", dry_run=True)

        # 第一次采集
        dp1 = collector.record(item.id, views=100, likes=10, comments=3)
        assert dp1.views == 100

        # 第二次采集（模拟几小时后）
        dp2 = collector.record(item.id, views=500, likes=40, comments=15, shares=5)
        assert dp2.views == 500

        # 验证报告包含两个快照
        report = collector.get_report(item.id)
        assert len(report.snapshots) == 2

    def test_pipeline_data_parsing(self, collector):
        """步骤4b：解析用户手动输入的数据"""
        dp = collector.parse_manual_input(
            "content_test", "播放 1000 点赞 50 评论 10 转发 5 涨粉 2 收益 0.5"
        )
        assert dp.views == 1000
        assert dp.likes == 50
        assert dp.revenue_cny == 0.5

    def test_pipeline_daily_review_empty(self, collector):
        """步骤5：无数据时的日复盘"""
        reviewer = DailyReviewer()
        summary = reviewer.review_today(collector)
        assert isinstance(summary, ReviewSummary)
        assert summary.period == "daily"
        assert len(summary.key_insights) > 0  # 至少有「暂无数据」的提示

    def test_pipeline_daily_review_with_data(self, collector):
        """步骤5b：有数据时的日复盘"""
        # 录入一些数据
        collector.record("content_001", views=500, likes=30, comments=10, shares=5)
        collector.record("content_002", views=200, likes=15, comments=3)

        reviewer = DailyReviewer()
        summary = reviewer.review_today(collector)

        assert isinstance(summary, ReviewSummary)
        assert summary.total_views == 700  # content_001(500) + content_002(200)
        # 注意：review_today 会收集所有文章的最新快照
        assert summary.total_likes >= 0

    def test_pipeline_review_message_format(self, collector):
        """步骤5c：复盘消息格式化"""
        reviewer = DailyReviewer()
        summary = reviewer.review_today(collector)

        msg = reviewer.format_wechat_message(summary)
        assert "日复盘" in msg
        assert "数据概览" in msg or "播放" in msg

    def test_pipeline_full_flow_dry(self, writer, notifier, collector):
        """
        MVP 完整链路（dry run）：
        生成 → 审核通过 → 数据回收 → 复盘
        """
        # 1. 生成
        item = writer.generate(topic="技术解读", dry_run=True)
        assert isinstance(item, ContentItem)

        # 2. 审核（通过）
        result = notifier.handle_reply("通过", item)
        assert result.decision == "approved"

        # 3. 模拟发布后数据回收（2次快照）
        collector.record(item.id, views=100, likes=10, comments=2)
        collector.record(item.id, views=500, likes=40, comments=12, shares=5)

        report = collector.get_report(item.id)
        assert len(report.snapshots) == 2

        # 4. 日复盘
        reviewer = DailyReviewer()
        summary = reviewer.review_today(collector)
        assert summary.period == "daily"
        # 用 dry run 时数据可能为 0，但结构要对
        assert hasattr(summary, 'key_insights')
        assert hasattr(summary, 'improvement_suggestions')


class TestMVPEdgeCases:
    """边界情况测试"""

    def test_empty_collector_review(self):
        """空数据收集器的复盘"""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = ManualCollector("douyin", data_dir=tmpdir)
            reviewer = DailyReviewer()
            summary = reviewer.review_today(collector)
            assert summary.total_views == 0

    def test_multiple_rejection_then_approve(self):
        """多次驳回后通过"""
        writer = ContentWriter()
        notifier = ReviewNotifier(wechat_target="test")

        item = writer.generate(topic="技术解读", dry_run=True)

        # 驳回
        r1 = notifier.handle_reply("驳回:不行", item)
        assert r1.decision == "rejected"

        # 修改
        r2 = notifier.handle_reply("修改:优化标题", item)
        assert r2.decision == "needs_revision"

        # 最终通过
        r3 = notifier.handle_reply("通过", item)
        assert r3.decision == "approved"

    def test_content_id_consistency(self):
        """文章 ID 在整个流程中保持一致"""
        writer = ContentWriter()
        item = writer.generate(topic="技术解读", dry_run=True)
        cid = item.id

        notifier = ReviewNotifier(wechat_target="test")
        result = notifier.handle_reply("通过", item)
        assert result.content_id == cid

        with tempfile.TemporaryDirectory() as tmpdir:
            collector = ManualCollector("douyin", data_dir=tmpdir)
            dp = collector.record(cid, views=100)
            assert dp.content_id == cid


class TestCronPipelineScript:
    """定时管线脚本测试"""

    def test_script_syntax(self):
        """管线脚本可以被正确导入"""
        from src.cron import daily_pipeline
        assert hasattr(daily_pipeline, "main")
        assert hasattr(daily_pipeline, "step_fetch_and_generate")

    def test_gen_step_with_news(self):
        """生成步骤可导入并调用"""
        from src.cron.daily_pipeline import step_fetch_and_generate
        assert callable(step_fetch_and_generate)
