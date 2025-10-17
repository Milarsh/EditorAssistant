from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, ForeignKey, Index, UniqueConstraint
from sqlalchemy import DateTime
from datetime import datetime
from src.db.models.base import Base
from src.db.models.source import Source

class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    guid: Mapped[str] = mapped_column(Text, nullable=False)

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source: Mapped[Source] = relationship(back_populates="articles")

    __table_args__ = (
        UniqueConstraint("source_id", "guid", name="uq_article_guid"),
        UniqueConstraint("source_id", "link", name="uq_article_link"),
        Index("idx_articles_source_time", "source_id", "published_at"),
    )