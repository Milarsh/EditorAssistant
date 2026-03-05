from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.models.article_social_stat import ArticleSocialStat
from src.db.models.article_social_stat_history import ArticleSocialStatHistory


def compute_engagement_score(
    like_count: int,
    repost_count: int,
    comment_count: int,
) -> float:
    return (
        max(0, int(comment_count or 0)) * 1.0
        + max(0, int(like_count or 0)) * 0.5
        + max(0, int(repost_count or 0)) * 2.0
    )


def insert_article_social_stat_history(
    session,
    article_id: int,
    like_count: int,
    repost_count: int,
    comment_count: int,
    view_count: int,
    engagement_score: float,
    collected_at: datetime | None = None,
) -> None:
    ts = collected_at or datetime.now(timezone.utc)
    session.execute(
        pg_insert(ArticleSocialStatHistory).values(
            entity_id=article_id,
            like_count=max(0, int(like_count or 0)),
            repost_count=max(0, int(repost_count or 0)),
            comment_count=max(0, int(comment_count or 0)),
            view_count=max(0, int(view_count or 0)),
            engagement_score=float(engagement_score or 0.0),
            collected_at=ts,
        )
    )


def upsert_article_social_stat(
    session,
    article_id: int,
    like_count: int,
    repost_count: int,
    comment_count: int,
    view_count: int,
    engagement_score: float | None = None,
    previous_engagement: float | None = None,
    engagement_delta: float | None = None,
    is_trending: bool | None = None,
    collected_at: datetime | None = None,
) -> None:
    ts = collected_at or datetime.now(timezone.utc)
    score = float(engagement_score or 0.0)
    stmt = (
        pg_insert(ArticleSocialStat)
        .values(
            entity_id=article_id,
            like_count=max(0, int(like_count or 0)),
            repost_count=max(0, int(repost_count or 0)),
            comment_count=max(0, int(comment_count or 0)),
            view_count=max(0, int(view_count or 0)),
            engagement_score=score,
            previous_engagement=previous_engagement,
            engagement_delta=engagement_delta,
            is_trending=bool(is_trending) if is_trending is not None else False,
            collected_at=ts,
        )
        .on_conflict_do_update(
            index_elements=["entity_id"],
            set_={
                "like_count": max(0, int(like_count or 0)),
                "repost_count": max(0, int(repost_count or 0)),
                "comment_count": max(0, int(comment_count or 0)),
                "view_count": max(0, int(view_count or 0)),
                "engagement_score": score,
                "previous_engagement": previous_engagement,
                "engagement_delta": engagement_delta,
                "is_trending": bool(is_trending) if is_trending is not None else False,
                "collected_at": ts,
            },
        )
    )
    session.execute(stmt)
