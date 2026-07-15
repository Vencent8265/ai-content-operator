"""
Agent 通信契约 — Pydantic Schema 定义
────────────────────────────────────
所有 Agent 之间的数据交换都走这些 Schema。
换框架、换模型，只要 Schema 不变，其他 Agent 不用改。
"""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# 内容项
# ══════════════════════════════════════════════════════════════

class ContentItem(BaseModel):
    """一篇文章的完整数据结构"""
    id: str = Field(description="文章唯一标识，如 content_20260715_001")
    title: str = Field(description="文章标题")
    summary: str = Field(default="", description="文章摘要（抖音文章格式，≤30字）")
    body: str = Field(description="正文内容（Markdown 格式）")
    tags: list[str] = Field(default_factory=list, description="标签，如 ['AI', '大模型', '教程']")
    topic: str = Field(description="话题分类，如 '技术解读'、'行业新闻'、'工具教程'")
    platform: str = Field(default="douyin", description="目标平台")
    status: Literal["draft", "pending_review", "approved", "rejected", "published"] = "draft"
    created_at: datetime = Field(default_factory=datetime.now)
    word_count: int = Field(default=0, description="正文字数（自动计算）")

    def model_post_init(self, __context):
        if self.word_count == 0:
            self.word_count = len(self.body)


# ══════════════════════════════════════════════════════════════
# 审核
# ══════════════════════════════════════════════════════════════

class ReviewResult(BaseModel):
    """审核结果"""
    content_id: str = Field(description="被审核的文章 ID")
    decision: Literal["approved", "rejected", "needs_revision"]
    reviewer: Literal["human", "agent"]
    comments: str = Field(default="", description="审核意见 / 驳回原因")
    risk_flags: list[str] = Field(default_factory=list, description="风险标记")
    reviewed_at: datetime = Field(default_factory=datetime.now)


# ══════════════════════════════════════════════════════════════
# 发布任务
# ══════════════════════════════════════════════════════════════

class PublishTask(BaseModel):
    """发布任务"""
    task_id: str
    content_id: str
    platform: str
    scheduled_at: datetime | None = None
    status: Literal["pending", "published", "failed", "cancelled"] = "pending"
    publish_url: str | None = None
    error_msg: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


# ══════════════════════════════════════════════════════════════
# 数据
# ══════════════════════════════════════════════════════════════

class DataPoint(BaseModel):
    """单个时间点的数据快照"""
    content_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    followers_change: int = 0
    revenue_cny: float = 0.0
    source: Literal["api", "manual", "estimated"] = "manual"


class DataReport(BaseModel):
    """单篇文章的完整数据报告"""
    content_id: str
    platform: str
    snapshots: list[DataPoint] = Field(default_factory=list)
    published_at: datetime | None = None
    first_24h_views: int = 0
    first_7d_views: int = 0

    @property
    def latest_snapshot(self) -> DataPoint | None:
        return self.snapshots[-1] if self.snapshots else None


# ══════════════════════════════════════════════════════════════
# 复盘
# ══════════════════════════════════════════════════════════════

class ReviewSummary(BaseModel):
    """日/周复盘摘要"""
    period: Literal["daily", "weekly", "monthly"]
    start_date: str = Field(description="YYYY-MM-DD")
    end_date: str = Field(description="YYYY-MM-DD")
    total_views: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    total_revenue_cny: float = 0.0
    followers_net_change: int = 0
    top_content_id: str | None = None
    key_insights: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    risk_alerts: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 投流
# ══════════════════════════════════════════════════════════════

class AdSuggestion(BaseModel):
    """投流建议"""
    content_id: str
    suggested_budget_cny: float
    suggested_platform: str = "douyin"
    suggested_duration_days: int = 3
    reason: str = ""
    expected_roi_range: str = "0.8-1.5"
    risk_level: Literal["low", "medium", "high"] = "medium"


class AdCampaign(BaseModel):
    """投流活动记录"""
    campaign_id: str
    content_id: str
    budget_cny: float
    spent_cny: float = 0.0
    views_gained: int = 0
    followers_gained: int = 0
    roi: float = 0.0
    status: Literal["running", "paused", "completed", "stopped_loss"] = "running"
    started_at: datetime = Field(default_factory=datetime.now)
    auto_stop_reason: str | None = None
