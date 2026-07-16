"""
MVP 每日管线 v3
──────────────
流程：获取资讯 → AI成文 → 搜头图 → 组装发布卡 → 推送审核
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
from src.utils.publish_formatter import PublishFormatter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daily_pipeline")


def step_fetch_and_generate():
    """步骤1：获取资讯 → AI成文 → 搜头图 → 发审核"""
    logger.info("=" * 50)
    logger.info("步骤1：资讯聚合 + AI成文 + 组装发布卡")
    logger.info("=" * 50)

    fetcher = NewsFetcher()
    bundle = fetcher.fetch_all(sources=["hackernews", "arxiv", "github"])
    logger.info(f"聚合: {bundle.count} 条资讯 ({len(bundle.errors)} 个错误)")

    if bundle.count == 0:
        logger.error("未获取到资讯")
        return None

    # AI 成文
    writer = ContentWriter()
    try:
        item = writer.generate_from_news(bundle)
    except Exception as e:
        logger.error(f"文章生成失败: {e}")
        return None

    logger.info(f"文章: {item.title}")

    # 搜头图
    header_img = fetcher.find_header_image(f"{item.topic} {item.tags[0] if item.tags else 'technology'}")
    if header_img:
        logger.info(f"头图已获取")
    else:
        logger.warning("头图未获取到")

    # 组装发布卡
    formatter = PublishFormatter()
    topic_tags = [f"#{t}" for t in item.tags[:3]] + ["#AI", "#科技"]
    card = formatter.format(item, header_image_url=header_img, topic_tags=topic_tags)
    publish_doc = formatter.to_publish_doc(card)

    # 保存发布文档
    doc_path = Path(f"data/articles/{item.id}_publish.md")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(publish_doc, encoding="utf-8")
    logger.info(f"发布卡: {doc_path}")

    # 推送审核
    notifier = ReviewNotifier()
    notifier.send_for_review(item)

    return {
        "id": item.id,
        "title": item.title,
        "topic": item.topic,
        "publish_doc": str(doc_path.absolute()),
        "header_image": header_img,
        "news_count": bundle.count,
        "time": datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="MVP 每日管线 v3")
    parser.add_argument("--step", choices=["gen", "all"], default="all")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"  MVP Pipeline v3 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if args.step in ("gen", "all"):
        result = step_fetch_and_generate()
        if result:
            print(f"\n✅ 文章: {result['title']}")
            print(f"✅ 发布卡: {result['publish_doc']}")
            print(f"✅ 头图: {'已获取' if result['header_image'] else '未获取'}")
        else:
            print("\n❌ 管线失败")

    print(f"\n{'='*50}")
    print("  管线执行完毕")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
