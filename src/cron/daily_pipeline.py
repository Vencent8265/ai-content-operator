"""
MVP 每日管线脚本
────────────────
被 Hermes Cron 定时调用的主流程：

  早晨（如 9:00）：生成文章 → 推送审核 → 等待审核 → 提醒手动发布
  下午（如 16:00）：提醒数据回收
  晚间（如 21:00）：执行日复盘

用法：
  python src/cron/daily_pipeline.py              # 默认执行全流程
  python src/cron/daily_pipeline.py --step gen    # 只执行内容生成
  python src/cron/daily_pipeline.py --step review # 只执行日复盘
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.content_writer import ContentWriter
from src.agents.review_notifier import ReviewNotifier
from src.agents.daily_reviewer import DailyReviewer
from src.tools.data_collector import ManualCollector, get_collector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_pipeline")


# ══════════════════════════════════════════════════════════════
# 管线步骤
# ══════════════════════════════════════════════════════════════

def step_generate_article(topic: str = "技术解读", direction: str = "") -> dict | None:
    """
    步骤1：生成文章并推送审核。

    Returns:
        生成的文章信息，或 None（失败时）
    """
    logger.info("=" * 50)
    logger.info("步骤1：内容生成 + 审核推送")
    logger.info("=" * 50)

    writer = ContentWriter()

    try:
        item = writer.generate(topic=topic, direction=direction)
    except Exception as e:
        logger.error(f"内容生成失败: {e}")
        return None

    logger.info(f"文章生成成功: {item.id} — {item.title}")

    # 推送审核
    notifier = ReviewNotifier()
    success = notifier.send_for_review(item)

    return {
        "id": item.id,
        "title": item.title,
        "topic": item.topic,
        "word_count": item.word_count,
        "tags": item.tags,
        "review_sent": success,
        "time": datetime.now().isoformat(),
    }


def step_data_collection_reminder(last_content_id: str = "", last_title: str = ""):
    """
    步骤2：提醒数据回收。
    """
    logger.info("=" * 50)
    logger.info("步骤2：数据回收提醒")
    logger.info("=" * 50)

    collector = get_collector()

    if last_content_id:
        msg = collector.format_reminder_message(last_content_id, last_title)
        notifier = ReviewNotifier()
        # 直接用 hermes send 推送到微信
        import subprocess
        try:
            subprocess.run(
                ["hermes", "send", "--to", notifier.wechat_target, msg],
                capture_output=True, timeout=15,
            )
            logger.info(f"数据回收提醒已发送: {last_content_id}")
        except Exception as e:
            logger.error(f"数据回收提醒失败: {e}")
    else:
        logger.info("没有需要回收数据的文章")


def step_daily_review():
    """
    步骤3：执行日复盘。
    """
    logger.info("=" * 50)
    logger.info("步骤3：日复盘")
    logger.info("=" * 50)

    reviewer = DailyReviewer()
    # 获取今日所有报告数据
    collector = get_collector()
    today = datetime.now().strftime("%Y%m%d")

    try:
        result = reviewer.review_today(collector)
        logger.info(f"日复盘完成: {len(result.key_insights)} 条洞察")
        return result
    except Exception as e:
        logger.error(f"日复盘失败: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="MVP 每日管线")
    parser.add_argument("--step", choices=["gen", "collect", "review", "all"],
                        default="all", help="执行哪个步骤（默认全部）")
    parser.add_argument("--topic", default="技术解读", help="内容话题")
    parser.add_argument("--direction", default="", help="写作方向")
    parser.add_argument("--content-id", default="", help="上次生成的文章 ID")
    parser.add_argument("--content-title", default="", help="上次生成的文章标题")

    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"  MVP Daily Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    result = {"pipeline": "mvp_daily", "time": datetime.now().isoformat()}

    if args.step in ("gen", "all"):
        gen_result = step_generate_article(args.topic, args.direction)
        result["generation"] = gen_result
        if gen_result:
            args.content_id = gen_result["id"]
            args.content_title = gen_result["title"]

    if args.step in ("collect", "all"):
        step_data_collection_reminder(args.content_id, args.content_title)
        result["collection_reminder"] = "sent" if args.content_id else "skipped"

    if args.step in ("review", "all"):
        review_result = step_daily_review()
        if review_result:
            result["review"] = {
                "period": review_result.period,
                "insights_count": len(review_result.key_insights),
                "alerts": review_result.risk_alerts,
            }

    print(f"\n{'='*50}")
    print("  管线执行完毕")
    print(f"{'='*50}\n")

    return result


if __name__ == "__main__":
    main()
