from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class ArticleSocialStat(Base):
    __tablename__ = "article_social_stat"

    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engagement_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    previous_engagement: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_trending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
