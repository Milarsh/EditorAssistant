from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base

class ArticleStopWord(Base):
    __tablename__ = "article_stop_word"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_word_id: Mapped[int] = mapped_column(Integer, ForeignKey("stop_word.id"), primary_key=True)