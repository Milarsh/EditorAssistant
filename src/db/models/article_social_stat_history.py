from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class ArticleSocialStatHistory(Base):
    __tablename__ = "article_social_stat_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engagement_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_social_stat_history_entity_time", "entity_id", "collected_at"),
    )
