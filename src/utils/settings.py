from sqlalchemy import select
from src.db.db import SessionLocal
from src.db.models.settings import Settings

BASE_SETTINGS= {
    "poll_interval": "60"
}

def ensure_base_settings() -> None:
    with SessionLocal() as session:
        existing_codes = set(
            session.execute(select(Settings.code)).scalars().all()
        )
        created = False
        for code, value in BASE_SETTINGS.items():
            if code not in existing_codes:
                session.add(Settings(code=code, value=str(value)))
                created = True
        if created:
            session.commit()

def get_setting_str(code: str, default: str | None = None) -> str | None:
    with SessionLocal() as session:
        val = session.execute(
            select(Settings.value).where(Settings.code == code)
        ).scalar_one_or_none()
    return val if val is not None else default

def get_setting_bool(code: str, default: bool = False) -> bool:
    val = get_setting_str(code)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")

def get_setting_int(code: str, default: int) -> int:
    val = get_setting_str(code)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default
