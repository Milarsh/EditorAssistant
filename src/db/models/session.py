from sqlalchemy import String, Boolean, DateTime, Integer, Index, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.models.base import Base
from datetime import datetime

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    session_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    ip_first: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ip_last: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ua_first: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ua_last: Mapped[str | None] = mapped_column(String(255), nullable=True)

    csrf_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    remember_me: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship(back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("session_hash", name="uq_sessions_hash"),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_revoked_at", "revoked_at"),
        Index(
            "uq_sessions_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )