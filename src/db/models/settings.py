from src.db.models.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, ForeignKey, Index, UniqueConstraint, CheckConstraint

class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column()
    code: Mapped[str] = mapped_column()
    value: Mapped[int] = mapped_column()