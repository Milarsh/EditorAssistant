import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from src.db.models.base import Base

pg_db = os.getenv("POSTGRES_DB", "editor_assistant")
pg_user = os.getenv("POSTGRES_USER", "editor")
pg_password = os.getenv("POSTGRES_PASSWORD", "editor_pwd_dev")
pg_host = os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "db"))
pg_port = os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432"))
DATABASE_URL = f"postgresql+psycopg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

REQUIRED_TABLES = {"sources", "articles", "users", "sessions", "auth_codes", "rubric", "settings",
                   "article_key_word", "article_stat", "article_social_stat", "article_social_stat_history", "stop_word", "stop_category", "key_word", "article_stop_word"}

def create_schema():
    Base.metadata.create_all(engine)

def schema_exists() -> bool:
    with engine.begin() as connection:
        inspection = inspect(connection)
        existing = set(inspection.get_table_names(schema="public"))
        return REQUIRED_TABLES.issubset(existing)