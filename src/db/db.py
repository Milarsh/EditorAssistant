import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from src.db.models.base import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://editor:editor_pwd_dev@db:5432/editor_assistant")

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

REQUIRED_TABLES = {"sources", "articles", "users", "sessions", "auth_codes", "rubric", "stopword"}

def create_schema():
    Base.metadata.create_all(engine)

def schema_exists() -> bool:
    with engine.begin() as connection:
        inspection = inspect(connection)
        existing = set(inspection.get_table_names(schema="public"))
        return REQUIRED_TABLES.issubset(existing)