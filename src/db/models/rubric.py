from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base


class Rubric(Base):
    __tablename__ = "rubric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)