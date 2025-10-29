import os

from sqlalchemy import String, Boolean, DateTime, Integer, Index, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.models.base import Base
from datetime import datetime

MAX_ATTEMPTS_EMAIL_CONFIRM = int(os.getenv("MAX_ATTEMPTS_EMAIL_CONFIRM", "5"))

class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    login: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    email_confirm_code_hash: Mapped[str | None] = mapped_column(
        String(255), nullable= True
    )
    email_confirm_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_confirm_code_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_confirm_code_attempts_left: Mapped[int] = mapped_column(
        Integer, nullable=False, default=MAX_ATTEMPTS_EMAIL_CONFIRM
    )

    reset_code_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    reset_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reset_code_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reset_code_attempts_left: Mapped[int] = mapped_column(
        Integer, nullable=False, default=MAX_ATTEMPTS_EMAIL_CONFIRM
    )

    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(
        String(45), nullable=True
    )

    current_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    current_session: Mapped["Session | None"] = relationship(
        "Session", primaryjoin="User.current_session_id==Session.id", viewonly=True, uselist=False
    )