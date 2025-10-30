from src.db.models.base import Base
from sqlalchemy import String, DateTime, Integer, Index, ForeignKey, UniqueConstraint, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

class AuthCode(Base):
    __tablename__ = "auth_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    AuthCodePurpose = Enum("email_confirm", "password_reset", "auth_code_purpose")
    purpose: Mapped[str] = mapped_column(AuthCodePurpose, nullable=False, index=True)

    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_input_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="auth_codes")

    __table_args__ = (
        UniqueConstraint("user_id", "purpose", name="uq_auth_codes_active_per_user_purpose",
                         deferrable=False, initially="IMMEDIATE"),
    )