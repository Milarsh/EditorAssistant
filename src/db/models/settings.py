from src.db.models.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Index, UniqueConstraint, Integer


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("code", name="uq_settings_code"),
        Index("ix_settings_code", "code"),
    )
