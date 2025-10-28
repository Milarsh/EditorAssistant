from src.db.models.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime, Text, Boolean, Index
from datetime import datetime, timezone
from sqlalchemy import Enum

class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    SourceType = Enum("rss", "tg", "vk", name = "source_type")
    type: Mapped[str] = mapped_column(SourceType, nullable=False)

    rss_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,default=lambda: datetime.now(timezone.utc))

    articles: Mapped[list["Article"]] = relationship(back_populates="source", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_sources_rss_url", "rss_url"),
    )

    def __repr__(self) -> str:
        return f"<Source id={self.id} name={self.name!r}>"