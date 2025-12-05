from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base

class ArticleKeyWord(Base):
    __tablename__ = "article_key_word"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_word_id: Mapped[int] = mapped_column(Integer, ForeignKey("key_word.id"), primary_key=True)