from sqlalchemy import String, Integer, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base

class KeyWord(Base):
    __tablename__ = "key_word"
    __table_args__ = (
        UniqueConstraint("code", "rubric_id", name="uq_key_word_code_rubric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    rubric_id: Mapped[int] = mapped_column(Integer, ForeignKey("rubric.id"), nullable=False)