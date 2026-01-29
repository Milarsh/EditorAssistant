from sqlalchemy import select
from src.db.db import SessionLocal
from src.db.models.settings import Settings

SETTINGS_SCHEMA = {
    "poll_interval": {
        "type": "int",
        "default": 5,
        "options": [5, 10, 15, 30, 45, 60],
        "allow_custom": True,
        "min": 1,
        "max": 60,
    },
    "media_keep": {
        "type": "bool",
        "default": True,
        "options": [True, False],
    },
    "media_max_size_mb": {
        "type": "int",
        "default": 50,
        "options": [5, 10, 25, 50, 100, 0],
        "allow_custom": True,
        "min": 1,
        "max": 2048,
        "zero_is_unlimited": True,
    },
}

BASE_SETTINGS = {code: str(meta.get("default")) for code, meta in SETTINGS_SCHEMA.items()}

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


def get_setting_schema(code: str) -> dict | None:
    return SETTINGS_SCHEMA.get(code)


def get_all_setting_codes() -> list[str]:
    return list(SETTINGS_SCHEMA.keys())


def get_setting_options(code: str) -> dict | None:
    schema = SETTINGS_SCHEMA.get(code)
    if not schema:
        return None

    res = {
        "code": code,
        "type": schema.get("type"),
        "default": schema.get("default"),
    }
    for key in ("options", "allow_custom", "min", "max", "zero_is_unlimited"):
        if key in schema:
            res[key] = schema[key]
    return res


def _parse_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return None


def validate_setting_value(code: str, value) -> tuple[str | None, dict | None]:
    schema = SETTINGS_SCHEMA.get(code)
    if not schema:
        return None, {"code": "Unknown setting"}

    setting_type = schema.get("type")
    options = schema.get("options") or []
    allow_custom = bool(schema.get("allow_custom", False))
    min_val = schema.get("min")
    max_val = schema.get("max")
    zero_is_unlimited = bool(schema.get("zero_is_unlimited", False))

    if setting_type == "int":
        try:
            parsed = int(value)
        except Exception:
            return None, {"value": "Must be integer"}

        if options and parsed not in options and not allow_custom:
            return None, {"value": "Must be one of options"}

        if not (zero_is_unlimited and parsed == 0):
            if min_val is not None and parsed < int(min_val):
                return None, {"value": f"Must be >= {min_val}"}
            if max_val is not None and parsed > int(max_val):
                return None, {"value": f"Must be <= {max_val}"}

        return str(parsed), None

    if setting_type == "bool":
        parsed = _parse_bool(value)
        if parsed is None:
            return None, {"value": "Must be boolean"}
        if options and parsed not in options and not allow_custom:
            return None, {"value": "Must be one of options"}
        return "true" if parsed else "false", None

    if setting_type == "string":
        if not isinstance(value, str):
            return None, {"value": "Must be string"}
        if options and value not in options and not allow_custom:
            return None, {"value": "Must be one of options"}
        return value, None

    return None, {"value": "Unsupported type"}
