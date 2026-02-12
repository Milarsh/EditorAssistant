from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.models.article_social_stat import ArticleSocialStat


def upsert_article_social_stat(
    session,
    article_id: int,
    like_count: int,
    repost_count: int,
    comment_count: int,
    view_count: int,
    collected_at: datetime | None = None,
) -> None:
    ts = collected_at or datetime.now(timezone.utc)
    stmt = (
        pg_insert(ArticleSocialStat)
        .values(
            entity_id=article_id,
            like_count=max(0, int(like_count or 0)),
            repost_count=max(0, int(repost_count or 0)),
            comment_count=max(0, int(comment_count or 0)),
            view_count=max(0, int(view_count or 0)),
            collected_at=ts,
        )
        .on_conflict_do_update(
            index_elements=["entity_id"],
            set_={
                "like_count": max(0, int(like_count or 0)),
                "repost_count": max(0, int(repost_count or 0)),
                "comment_count": max(0, int(comment_count or 0)),
                "view_count": max(0, int(view_count or 0)),
                "collected_at": ts,
            },
        )
    )
    session.execute(stmt)
