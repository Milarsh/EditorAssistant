import time
from datetime import datetime, timezone

from sqlalchemy import select
from src.assistant.vk_parser import run_vk_cycle
from src.assistant.rss_parser import run_rss_cycle
from src.assistant.tg_parser import run_tg_cycle
from src.db.db import SessionLocal
from src.db.models.article import Article
from src.db.models.article_stat import ArticleStat
from src.utils.analyzer import analyze_article_words
from src.utils.logger import Logger

from src.utils.settings import get_setting_int

logger = Logger("parser")

def run_stats_cycle():
    with SessionLocal() as session:
        stmt = (
            select(Article)
            .outerjoin(
                ArticleStat,
                Article.id == ArticleStat.entity_id,
            )
            .where(ArticleStat.entity_id.is_(None))
            .order_by(Article.id)
        )

        articles = session.execute(stmt).scalars().all()
        if not articles:
            return 0

        processed = 0
        for article in articles:
            try:
                analyze_article_words(session, article.id)
                processed += 1
            except Exception as exception:
                session.rollback()
                logger.write(
                    f"[STATS-ERROR] article_id={article.id} error={exception!r}"
                )

        logger.write(f"[STATS] calculated for {processed} articles")
        return processed

def run_cycle():
    logger.ensure_log_dir()
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-START] {start}")

    total_added = 0
    total_added += run_vk_cycle(logger)
    total_added += run_rss_cycle(logger)
    total_added += run_tg_cycle(logger)

    stats_processed = run_stats_cycle()

    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-END] {end} added={total_added} stats_processed={stats_processed}")

def main():
    logger.ensure_log_dir()
    logger.write("[PARSER] Parser started")
    interval = get_setting_int("poll_interval", 300)
    while True:
        run_cycle()
        time.sleep(interval)

if __name__ == "__main__":
    main()