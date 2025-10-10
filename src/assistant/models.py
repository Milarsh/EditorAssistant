from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Text, Boolean, ForeignKey, Index, UniqueConstraint
from sqlalchemy import DateTime
from datetime import datetime, timezone

class Base(DeclarativeBase):
    pass

class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rss_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,default=lambda: datetime.now(timezone.utc))

    articles: Mapped[list["Article"]] = relationship(back_populates="source", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_sources_rss_url", "rss_url"),
    )

    def __repr__(self) -> str:
        return f"<Source id={self.id} name={self.name!r}>"

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