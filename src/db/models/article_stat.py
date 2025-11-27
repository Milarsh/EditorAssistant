from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.base import Base
from src.db.models.rubric import Rubric
from src.db.models.stop_category import StopCategory


class ArticleStat(Base):
    __tablename__ = "article_stat"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_words_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    key_words_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rubric_id: Mapped[int] = mapped_column(Integer, ForeignKey("rubric.id"), nullable=True)
    stop_category_id: Mapped[int] = mapped_column(Integer, ForeignKey("stop_category.id"), nullable=True)