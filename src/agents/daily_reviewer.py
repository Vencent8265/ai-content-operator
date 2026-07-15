"""
日复盘 Agent
───────────
职责：每天根据当日数据生成简报，推送到微信。

输入：当日各文章的数据报告（从 ManualCollector 获取）
输出：ReviewSummary（含关键洞察、改进建议、风险预警）
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from ..models.adapter import ModelRouter, create_default_router
from ..contracts.schemas import ReviewSummary, DataReport
from ..tools.data_collector import ManualCollector

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = """你是一个 AI 内容运营分析师，负责每日复盘。

## 你的职责
根据当天的文章数据，给出：
1. 关键洞察（1-3 条）：今天表现好/差的原因可能是什么
2. 改进建议（1-2 条）：明天可以在哪些方面调整
3. 风险预警：如果有数据异常，及时提醒

## 分析原则
- 基于数据说话，不要凭空猜测
- 对新账号的低流量不要过度解读（前几周流量低是正常的）
- 关注趋势而非单点：连续下降比单日低更值得关注
- 建议要具体可执行，不要说「优化内容」而要说「标题可以加一个问句」

## 输出格式
用 JSON，包含：
- key_insights: 1-3 条关键洞察
- improvement_suggestions: 1-2 条改进建议
- risk_alerts: 风险预警（如果没有就空数组）"""


class DailyReviewer:
    """
    日复盘 Agent。

    用法：
        reviewer = DailyReviewer()
        summary = reviewer.review_today(collector)
        # summary 是一个 ReviewSummary，可直接推送微信
    """

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or create_default_router()

    def _parse_json_response(self, raw_text: str) -> dict:
        """从 LLM 返回文本中提取 JSON"""
        import json, re

        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, re.DOTALL)
        if json_match:
            raw_text = json_match.group(1)

        brace_match = re.search(r'\{[\s\S]*\}', raw_text)
        if brace_match:
            raw_text = brace_match.group(0)

        return json.loads(raw_text)

    def _gather_today_data(self, collector: ManualCollector) -> list[dict]:
        """
        从 collector 中收集今日数据。

        Returns:
            每篇文章的数据摘要列表
        """
        today = datetime.now().strftime("%Y%m%d")
        reports = []

        for content_id in collector.list_reports():
            report = collector.get_report(content_id)
            if not report.snapshots:
                continue

            # 只取今日的快照
            today_snapshots = [
                s for s in report.snapshots
                if s.timestamp and s.timestamp.strftime("%Y%m%d") == today
            ]
            if not today_snapshots:
                continue

            latest = today_snapshots[-1]
            reports.append({
                "content_id": content_id,
                "views": latest.views,
                "likes": latest.likes,
                "comments": latest.comments,
                "shares": latest.shares,
                "followers_change": latest.followers_change,
                "revenue_cny": latest.revenue_cny,
            })

        return reports

    def review_today(self, collector: ManualCollector) -> ReviewSummary:
        """
        对今日所有文章数据进行复盘分析。

        Args:
            collector: 数据收集器实例

        Returns:
            ReviewSummary: 复盘摘要
        """
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")

        # 收集数据
        data = self._gather_today_data(collector)

        if not data:
            # 今日没有数据，返回空复盘
            return ReviewSummary(
                period="daily",
                start_date=today_str,
                end_date=today_str,
                key_insights=["今日暂无数据，可能是文章尚未发布或尚未采集数据"],
                improvement_suggestions=["请及时进行数据回收"],
                risk_alerts=[],
            )

        # 计算汇总
        total_views = sum(d["views"] for d in data)
        total_likes = sum(d["likes"] for d in data)
        total_comments = sum(d["comments"] for d in data)
        total_shares = sum(d["shares"] for d in data)
        total_revenue = sum(d["revenue_cny"] for d in data)
        total_followers = sum(d["followers_change"] for d in data)

        # 找最佳文章
        best = max(data, key=lambda d: d["views"]) if data else None

        # 构建 LLM 分析请求
        data_text = "\n".join(
            f"- {d['content_id']}: 播放{d['views']} 点赞{d['likes']} "
            f"评论{d['comments']} 转发{d['shares']} 涨粉{d['followers_change']} "
            f"收益{d['revenue_cny']}元"
            for d in data
        )

        user_message = f"""今日数据汇总：
日期：{today_str}
文章数：{len(data)}
总播放：{total_views}
总点赞：{total_likes}
总评论：{total_comments}
总转发：{total_shares}
涨粉：{total_followers}
收益：{total_revenue} 元

各文章详情：
{data_text}

请分析今日数据表现，给出关键洞察、改进建议和风险预警。"""

        # 调用 LLM 分析
        try:
            response = self.router.call(
                task="analysis",
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.3,  # 分析任务需要更确定性
            )
            parsed = self._parse_json_response(response["content"])
        except Exception as e:
            logger.warning(f"LLM 复盘分析失败，使用默认分析: {e}")
            parsed = {
                "key_insights": [f"今日发布 {len(data)} 篇文章，总播放 {total_views}"],
                "improvement_suggestions": ["继续观察数据趋势"],
                "risk_alerts": [],
            }

        return ReviewSummary(
            period="daily",
            start_date=today_str,
            end_date=today_str,
            total_views=total_views,
            total_likes=total_likes,
            total_comments=total_comments,
            total_shares=total_shares,
            total_revenue_cny=total_revenue,
            followers_net_change=total_followers,
            top_content_id=best["content_id"] if best else None,
            key_insights=parsed.get("key_insights", []),
            improvement_suggestions=parsed.get("improvement_suggestions", []),
            risk_alerts=parsed.get("risk_alerts", []),
        )

    def format_wechat_message(self, summary: ReviewSummary) -> str:
        """将复盘摘要格式化为微信推送消息"""
        insights = "\n".join(f"  • {s}" for s in summary.key_insights)
        suggestions = "\n".join(f"  • {s}" for s in summary.improvement_suggestions)

        alerts = ""
        if summary.risk_alerts:
            alerts = "\n⚠️ 风险预警\n" + "\n".join(f"  • {s}" for s in summary.risk_alerts)

        return f"""📊 日复盘 — {summary.start_date}

【数据概览】
  播放 {summary.total_views}  |  点赞 {summary.total_likes}
  评论 {summary.total_comments}  |  转发 {summary.total_shares}
  涨粉 {summary.followers_net_change}  |  收益 ¥{summary.total_revenue_cny}

【关键洞察】
{insights}

【改进建议】
{suggestions}
{alerts}"""
