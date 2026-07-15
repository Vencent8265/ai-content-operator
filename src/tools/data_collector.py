"""
数据回收模块
───────────
职责：定时收集文章发布后的流量/收益数据。

两种模式：
  1. 手动模式（MVP 默认）：微信提醒 → 用户手动输入数据 → 格式化存储
  2. API 模式（后期）：对接平台官方 API 自动抓取

输出：DataPoint / DataReport（符合 contracts 契约）
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..contracts.schemas import DataPoint, DataReport

logger = logging.getLogger(__name__)

# 默认数据存储路径
DEFAULT_DATA_DIR = Path("data/reports")


# ══════════════════════════════════════════════════════════════
# 数据收集器基类
# ══════════════════════════════════════════════════════════════

class DataCollector(ABC):
    """数据收集器抽象基类。所有平台的数据收集器都继承这个。"""

    def __init__(self, platform: str, data_dir: str | Path = DEFAULT_DATA_DIR):
        self.platform = platform
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def collect_snapshot(self, content_id: str) -> DataPoint:
        """
        采集单次数据快照。

        Returns:
            DataPoint: 单时间点的数据
        """
        ...

    def get_report(self, content_id: str) -> DataReport:
        """
        获取某篇文章的完整数据报告（所有历史快照）。

        Returns:
            DataReport: 如果之前没有数据，返回空报告
        """
        report_path = self._report_path(content_id)
        if report_path.exists():
            return DataReport.model_validate_json(report_path.read_text())

        return DataReport(
            content_id=content_id,
            platform=self.platform,
            snapshots=[],
        )

    def add_snapshot(self, content_id: str, snapshot: DataPoint) -> DataReport:
        """
        添加一次数据快照，更新报告文件。

        Args:
            content_id: 文章 ID
            snapshot: 数据快照

        Returns:
            DataReport: 更新后的完整报告
        """
        report = self.get_report(content_id)
        report.snapshots.append(snapshot)

        # 更新快捷字段
        if not report.published_at:
            report.published_at = snapshot.timestamp

        # 计算 24h / 7d 的累计数据
        now = snapshot.timestamp or datetime.now()
        report.first_24h_views = self._sum_views_since(report, now - timedelta(hours=24))
        report.first_7d_views = self._sum_views_since(report, now - timedelta(days=7))

        # 持久化
        self._save_report(report)
        return report

    def _sum_views_since(self, report: DataReport, since: datetime) -> int:
        """计算指定时间范围内的总播放量（用最近一次快照的累计值）"""
        recent = [s for s in report.snapshots if s.timestamp and s.timestamp >= since]
        if not recent:
            return 0
        # 使用最后一个快照的 views（平台通常给的是累计值）
        return recent[-1].views

    def _report_path(self, content_id: str) -> Path:
        """报告文件路径"""
        return self.data_dir / f"{content_id}.json"

    def _save_report(self, report: DataReport):
        """保存报告到文件"""
        data = json.loads(report.model_dump_json(indent=2))
        # datetime 字段转换为 ISO 字符串
        if "published_at" in data and data["published_at"]:
            pass  # pydantic 会自动处理
        for s in data.get("snapshots", []):
            if "timestamp" in s and s["timestamp"]:
                pass
        self._report_path(report.content_id).write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def list_reports(self) -> list[str]:
        """列出所有已记录的文章 ID"""
        return [p.stem for p in self.data_dir.glob("*.json")]

    def get_latest_snapshot(self, content_id: str) -> DataPoint | None:
        """获取最近一次数据快照"""
        report = self.get_report(content_id)
        return report.latest_snapshot


# ══════════════════════════════════════════════════════════════
# 手动数据收集器（MVP 使用）
# ══════════════════════════════════════════════════════════════

class ManualCollector(DataCollector):
    """
    手动数据收集器 — MVP 阶段使用。

    因为抖音 API 权限在个人开发者阶段很难拿到，
    这里通过微信提醒用户去后台截图/查看数据，然后手动输入。

    用法：
        collector = ManualCollector("douyin")
        dp = collector.record(content_id="content_001",
                              views=1234, likes=56, comments=12,
                              shares=5, followers_change=3, revenue=0.0)
    """

    def collect_snapshot(self, content_id: str) -> DataPoint:
        """
        手动模式下不自动采集，返回一个待填充的 DataPoint。
        实际数据通过 record() 方法录入。
        """
        return DataPoint(
            content_id=content_id,
            timestamp=datetime.now(),
            source="manual",
        )

    def record(
        self,
        content_id: str,
        *,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        followers_change: int = 0,
        revenue_cny: float = 0.0,
        timestamp: datetime | None = None,
    ) -> DataPoint:
        """
        手动录入一次数据。

        所有字段都可以不传（默认 0），只填你有数据的字段即可。
        """
        dp = DataPoint(
            content_id=content_id,
            timestamp=timestamp or datetime.now(),
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            followers_change=followers_change,
            revenue_cny=revenue_cny,
            source="manual",
        )

        self.add_snapshot(content_id, dp)
        logger.info(f"手动录入数据: {content_id} views={views} likes={likes}")
        return dp

    def format_reminder_message(self, content_id: str, title: str = "") -> str:
        """
        生成数据采集提醒消息（用于微信推送）。
        """
        now = datetime.now().strftime("%H:%M")
        title_line = f"\n【文章】{title}" if title else ""

        return f"""📊 数据采集提醒 {now}
{title_line}
【ID】{content_id}

请打开抖音创作者中心，查看以下数据：

回复格式（每条一行，用空格分隔）：
  {{播放}} {{views}} {{点赞}} {{likes}} {{评论}} {{comments}} {{转发}} {{shares}} {{涨粉}} {{followers}} {{收益}} {{revenue}}

示例：
  {{播放}} 1234 {{点赞}} 56 {{评论}} 12 {{转发}} 5 {{涨粉}} 3 {{收益}} 0.5

或简化版（只填有的）：
  {{播放}} 1234 {{点赞}} 56"""

    def parse_manual_input(self, content_id: str, raw_text: str) -> DataPoint:
        """
        解析用户手动输入的原始文本，提取数据。

        支持格式：
          "播放 1234 点赞 56 评论 12 转发 5 涨粉 3 收益 0.5"
          "views 1234 likes 56"
          "1234 56 12 5 3"  （按顺序：播放 点赞 评论 转发 涨粉）
        """
        import re

        data = {
            "views": 0, "likes": 0, "comments": 0,
            "shares": 0, "followers_change": 0, "revenue_cny": 0.0,
        }

        # 中文关键词匹配
        patterns = [
            (r"播放\s*(\d[\d,]*)", "views"),
            (r"点赞\s*(\d[\d,]*)", "likes"),
            (r"评论\s*(\d[\d,]*)", "comments"),
            (r"转发\s*(\d[\d,]*)", "shares"),
            (r"涨粉\s*(\d[\d,]*)", "followers_change"),
            (r"收益\s*(\d+\.?\d*)", "revenue_cny"),
        ]

        for pattern, key in patterns:
            m = re.search(pattern, raw_text)
            if m:
                val = m.group(1).replace(",", "")
                if key == "revenue_cny":
                    data[key] = float(val)
                else:
                    data[key] = int(val)

        # 如果中文关键词没匹配到，尝试英文
        if all(v == 0 for k, v in data.items() if k != "revenue_cny"):
            en_patterns = [
                (r"views?\s*(\d[\d,]*)", "views"),
                (r"likes?\s*(\d[\d,]*)", "likes"),
                (r"comments?\s*(\d[\d,]*)", "comments"),
                (r"shares?\s*(\d[\d,]*)", "shares"),
                (r"followers?\s*(\d[\d,]*)", "followers_change"),
                (r"revenue\s*(\d+\.?\d*)", "revenue_cny"),
            ]
            for pattern, key in en_patterns:
                m = re.search(pattern, raw_text, re.IGNORECASE)
                if m:
                    val = m.group(1).replace(",", "")
                    if key == "revenue_cny":
                        data[key] = float(val)
                    else:
                        data[key] = int(val)

        # 最后的 fallback：纯数字（按顺序）
        if all(v == 0 for k, v in data.items() if k != "revenue_cny"):
            nums = re.findall(r"\d+", raw_text)
            keys = ["views", "likes", "comments", "shares", "followers_change"]
            for i, key in enumerate(keys):
                if i < len(nums):
                    data[key] = int(nums[i])

        dp = DataPoint(
            content_id=content_id,
            timestamp=datetime.now(),
            source="manual",
            **data,
        )

        self.add_snapshot(content_id, dp)
        return dp


# ══════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════

_default_collector: ManualCollector | None = None


def get_collector() -> ManualCollector:
    """获取全局单例数据收集器"""
    global _default_collector
    if _default_collector is None:
        _default_collector = ManualCollector("douyin")
    return _default_collector
