"""
测试：数据回收模块
运行：pytest tests/test_data_collector.py -v
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.tools.data_collector import (
    DataCollector,
    ManualCollector,
    get_collector,
    DEFAULT_DATA_DIR,
)
from src.contracts.schemas import DataPoint, DataReport


class TestManualCollector:
    """ManualCollector 测试"""

    @pytest.fixture
    def collector(self):
        """创建临时目录的收集器，测试后自动清理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield ManualCollector("douyin", data_dir=tmpdir)

    def test_record_creates_data_point(self, collector):
        """record() 返回 DataPoint"""
        dp = collector.record("content_001", views=100, likes=10)
        assert isinstance(dp, DataPoint)
        assert dp.content_id == "content_001"
        assert dp.views == 100
        assert dp.likes == 10
        assert dp.source == "manual"

    def test_record_defaults_to_zero(self, collector):
        """未传的字段默认为 0"""
        dp = collector.record("content_001", views=100)
        assert dp.views == 100
        assert dp.likes == 0
        assert dp.comments == 0
        assert dp.revenue_cny == 0.0

    def test_record_persists_report(self, collector):
        """record() 后报告被持久化"""
        collector.record("content_001", views=100)
        report = collector.get_report("content_001")
        assert len(report.snapshots) == 1
        assert report.snapshots[0].views == 100

    def test_multiple_snapshots_accumulate(self, collector):
        """多次采集数据累加到同一个报告"""
        collector.record("content_001", views=100, likes=10)
        collector.record("content_001", views=500, likes=50, comments=5)
        report = collector.get_report("content_001")
        assert len(report.snapshots) == 2
        # 最新的快照应该反映最新数据
        assert report.latest_snapshot.views == 500
        assert report.latest_snapshot.comments == 5

    def test_get_report_empty(self, collector):
        """空报告返回默认值"""
        report = collector.get_report("nonexistent")
        assert isinstance(report, DataReport)
        assert len(report.snapshots) == 0
        assert report.content_id == "nonexistent"

    def test_list_reports(self, collector):
        """list_reports 列出所有记录过的文章"""
        collector.record("content_001", views=100)
        collector.record("content_002", views=200)
        collector.record("content_001", views=150)  # 同一篇多次只算一个

        reports = collector.list_reports()
        assert len(reports) == 2
        assert "content_001" in reports
        assert "content_002" in reports

    def test_get_latest_snapshot(self, collector):
        """获取最近一次快照"""
        collector.record("content_001", views=100)
        collector.record("content_001", views=200, likes=20)
        latest = collector.get_latest_snapshot("content_001")
        assert latest.views == 200
        assert latest.likes == 20

    def test_get_latest_snapshot_empty(self, collector):
        """没有数据时返回 None"""
        assert collector.get_latest_snapshot("nonexistent") is None

    def test_report_published_at_set_on_first_snapshot(self, collector):
        """第一次快照时自动设置 published_at"""
        collector.record("content_001", views=100)
        report = collector.get_report("content_001")
        assert report.published_at is not None

    def test_report_json_roundtrip(self, collector):
        """报告可以正确序列化和反序列化"""
        collector.record("content_001", views=1000, likes=50, revenue_cny=2.5)
        collector.record("content_001", views=2000, likes=100, comments=20)

        # 重新读取
        report = collector.get_report("content_001")
        assert report.content_id == "content_001"
        assert len(report.snapshots) == 2
        assert report.snapshots[0].views == 1000
        assert report.snapshots[1].views == 2000


class TestParseManualInput:
    """手动输入解析测试"""

    @pytest.fixture
    def collector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield ManualCollector("douyin", data_dir=tmpdir)

    def test_chinese_format(self, collector):
        """中文关键词格式"""
        dp = collector.parse_manual_input(
            "content_001",
            "播放 1234 点赞 56 评论 12 转发 5 涨粉 3 收益 0.5"
        )
        assert dp.views == 1234
        assert dp.likes == 56
        assert dp.comments == 12
        assert dp.shares == 5
        assert dp.followers_change == 3
        assert dp.revenue_cny == 0.5
        assert dp.source == "manual"

    def test_chinese_partial(self, collector):
        """只填部分字段"""
        dp = collector.parse_manual_input("content_001", "播放 500 点赞 20")
        assert dp.views == 500
        assert dp.likes == 20
        assert dp.comments == 0
        assert dp.shares == 0
        assert dp.revenue_cny == 0.0

    def test_chinese_with_commas(self, collector):
        """数字带逗号"""
        dp = collector.parse_manual_input("content_001", "播放 1,234 点赞 56")
        assert dp.views == 1234

    def test_english_format(self, collector):
        """英文关键词"""
        dp = collector.parse_manual_input("content_001", "views 2000 likes 100 comments 30")
        assert dp.views == 2000
        assert dp.likes == 100
        assert dp.comments == 30

    def test_pure_numbers_fallback(self, collector):
        """纯数字 fallback：按顺序解析"""
        dp = collector.parse_manual_input("content_001", "1000 50 10 5 2")
        assert dp.views == 1000
        assert dp.likes == 50
        assert dp.comments == 10
        assert dp.shares == 5
        assert dp.followers_change == 2

    def test_no_data(self, collector):
        """无有效数据"""
        dp = collector.parse_manual_input("content_001", "今天天气不错")
        assert dp.views == 0
        assert dp.likes == 0

    def test_mixed_chinese_english(self, collector):
        """中英混合：中文优先"""
        dp = collector.parse_manual_input(
            "content_001",
            "播放 300 views 999"  # 中文优先
        )
        assert dp.views == 300  # 中文匹配优先

    def test_chinese_no_spaces(self, collector):
        """无空格的中文格式"""
        dp = collector.parse_manual_input("content_001", "播放300点赞20评论5")
        assert dp.views == 300
        assert dp.likes == 20
        assert dp.comments == 5


class TestReminderMessage:
    """提醒消息格式测试"""

    def test_with_title(self):
        collector = ManualCollector("douyin")
        msg = collector.format_reminder_message("content_001", "什么是大模型")
        assert "content_001" in msg
        assert "什么是大模型" in msg
        assert "播放" in msg
        assert "示例" in msg

    def test_without_title(self):
        collector = ManualCollector("douyin")
        msg = collector.format_reminder_message("content_002")
        assert "content_002" in msg
        assert "播放" in msg

    def test_collect_snapshot_returns_manual_point(self):
        collector = ManualCollector("douyin")
        dp = collector.collect_snapshot("test")
        assert dp.source == "manual"
        assert dp.content_id == "test"


class TestSingleton:
    """单例测试"""

    def test_get_collector_returns_same_instance(self):
        c1 = get_collector()
        c2 = get_collector()
        assert c1 is c2
