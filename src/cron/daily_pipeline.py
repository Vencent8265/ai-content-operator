"""
MVP 每日管线 v2
──────────────
流程：获取资讯 → AI 整理成文 → 推送审核 → 人工确认 → 发布

被 Hermes Cron 定时调用。
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.news_fetcher import NewsFetcher
from src.agents.content_writer import ContentWriter
from src.agents.review_notifier import ReviewNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_pipeline")


def step_fetch_and_generate():
    """步骤1：获取资讯 → 整理成文章 → 推送审核"""
    logger.info("=" * 50)
    logger.info("步骤1：获取资讯 + 整理成文")
    logger.info("=" * 50)

    # 1a. 获取资讯
    fetcher = NewsFetcher()
    bundle = fetcher.fetch_all(sources=["hackernews", "arxiv", "github"])

    logger.info(f"资讯聚合完成: {bundle.count} 条 ({len(bundle.errors)} 个错误)")
    if bundle.errors:
        for e in bundle.errors:
            logger.warning(f"  抓取错误: {e}")

    if bundle.count == 0:
        logger.error("未获取到任何资讯，管线终止")
        return None

    # 1b. 整理成文章
    writer = ContentWriter()
    try:
        item = writer.generate_from_news(bundle)
    except Exception as e:
        logger.error(f"文章生成失败: {e}")
        return None

    logger.info(f"文章生成: {item.title}")

    # 1c. 推送审核
    notifier = ReviewNotifier()
    notifier.send_for_review(item)

    return {
        "id": item.id,
        "title": item.title,
        "topic": item.topic,
        "news_count": bundle.count,
        "time": datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="MVP 每日管线 v2")
    parser.add_argument("--step", choices=["gen", "review", "all"], default="all")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"  MVP Pipeline v2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if args.step in ("gen", "all"):
        result = step_fetch_and_generate()
        if result:
            print(f"\n✅ 文章已生成并推送审核: {result['title']}")
        else:
            print("\n❌ 管线失败")

    print(f"\n{'='*50}")
    print("  管线执行完毕")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
