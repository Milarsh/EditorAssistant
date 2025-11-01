import os
import re
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
import bcrypt

from sqlalchemy import select, func, text

from src.db.models.user import User
from src.db.models.session import Session as DbSession
from src.db.models.auth_code import AuthCode

from src.db.db import SessionLocal
import json
from http.server import BaseHTTPRequestHandler

from src.utils.logger import Logger
from src.utils.mailer import send_email, build_confirm_email, build_reset_email

# Config
PASSWORD_MIN_LEN     = int(os.getenv("PASSWORD_MIN_LEN", "8"))
AUTH_CODE_LEN        = int(os.getenv("AUTH_CODE_LEN", "6"))
AUTH_CODE_TTL_MIN    = int(os.getenv("AUTH_CODE_TTL_MIN", "30"))
MAX_SEND_PER_CODE    = int(os.getenv("MAX_SEND_PER_CODE", "5"))
MAX_INPUT_ATTEMPTS   = int(os.getenv("MAX_INPUT_ATTEMPTS", "5"))

SESSION_TTL_DAYS     = int(os.getenv("SESSION_TTL_DAYS", "30"))
ROLLING_TTL_ON_TOUCH = os.getenv("ROLLING_TTL_ON_TOUCH", "true").lower() == "true"

_AUTH_CODE_PEPPER    = os.getenv("AUTH_CODE_PEPPER", "dev-pepper-change-me")

UTC = timezone.utc

logger = Logger("auth")
logger.ensure_log_dir()

# Helpers
def _now_utc() -> datetime:
    return datetime.now(tz=UTC)

def _validate_email(email: str) -> bool:
    return bool(email) and "@" in email and "." in email and len(email) <= 320

def _validate_login(login: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]{3,64}", login))

def _hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def _verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def _gen_code(n: int = AUTH_CODE_LEN) -> str:
    first = str(secrets.randbelow(9) + 1)
    rest = "".join(str(secrets.randbelow(10)) for _ in range(max(0, n -1)))
    return first + rest

def _hash_code(code: str) -> str:
    h = hashlib.sha256()
    h.update(_AUTH_CODE_PEPPER.encode("utf-8"))
    h.update(code.encode("utf-8"))
    return h.hexdigest()

def _extract_bearer(self) -> str | None:
    auth = self.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None

def _parse_json_body(handler: BaseHTTPRequestHandler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length == 0:
        return None
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        from src.assistant.server import ValidationError
        raise ValidationError("Invalid JSON body")

def _client_ip(handler: BaseHTTPRequestHandler) -> str | None:
    xff = handler.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = handler.headers.get("X-Real-IP")
    if xri:
        return xri
    try:
        return handler.client_address[0]
    except Exception:
        return None

# Auth routes
AUTH_ROUTES = [
    ("POST", re.compile(r"^/api/auth/register$"),           "auth_register"),
    ("POST", re.compile(r"^/api/auth/register/confirm$"),   "auth_register_confirm"),
    ("POST", re.compile(r"^/api/auth/register/resend$"),    "auth_register_resend"),
    ("GET",  re.compile(r"^/api/auth/register/status$"),    "auth_register_status"),

    ("POST", re.compile(r"^/api/auth/login$"),              "auth_login"),
    ("POST", re.compile(r"^/api/auth/logout$"),             "auth_logout"),
    ("GET",  re.compile(r"^/api/auth/whoami$"),             "auth_whoami"),

    ("POST", re.compile(r"^/api/auth/password/send-code$"), "auth_password_send_code"),
    ("POST", re.compile(r"^/api/auth/password/reset$"),     "auth_password_reset"),
]

# Implementations
def auth_register(self, match, query):
    body = _parse_json_body(self) or {}
    email = (body.get("email") or "").strip().lower()
    login = (body.get("login") or "").strip()
    password = body.get("password") or ""
    password_confirm = body.get("password_confirm") or ""

    errors = {}
    if not _validate_email(email): errors["email"] = "Invalid email"
    if not _validate_login(login): errors["login"] = "3-64 latin letters/digits/_"
    if len(password) < PASSWORD_MIN_LEN: errors["password"] = f"Min length {PASSWORD_MIN_LEN}"
    if password != password_confirm: errors["password_confirm"] = "Must match password"
    if errors:
        return self._json_error(400, "bad_request", "Invalid fields", errors)

    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User).where(User.email == email)) > 0:
            return self._json_error(409, "conflict", "Email already registered")
        if db.scalar(select(func.count()).select_from(User).where(User.login == login)) > 0:
            return self._json_error(409, "conflict", "Login already taken")

        user = User(email=email, login=login, password_hash=_hash_password(password), is_active=False)
        db.add(user)
        db.flush()

        now = _now_utc()
        code = _gen_code(AUTH_CODE_LEN)
        code_hash = _hash_code(code)
        auth_code = db.execute(
            select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "email_confirm")
        ).scalar_one_or_none()

        expires = now + timedelta(minutes=AUTH_CODE_TTL_MIN)
        if auth_code is None:
            auth_code = AuthCode(
                user_id=user.id,
                purpose="email_confirm",
                code_hash=code_hash,
                created_at=now,
                expires_at=expires,
                send_count=1,
                last_sent_at=now,
                input_count=0,
                last_input_at=None,
            )
            db.add(auth_code)
        else:
            if auth_code.send_count >= MAX_SEND_PER_CODE:
                db.rollback()
                return self._json_error(429, "too_many_requests", "Resend limit reached",
                                        {"retry_after": int((auth_code.expires_at - now).total_seconds())})
            auth_code.code_hash = code_hash
            auth_code.created_at = now
            auth_code.expires_at = expires
            auth_code.send_count = auth_code.send_count + 1
            auth_code.last_sent_at = now
            auth_code.input_count = 0
            auth_code.last_input_at = None

        db.commit()
        subject, mail_text, html = build_confirm_email(code, AUTH_CODE_TTL_MIN)
        send_email(email, subject, mail_text, html)

        logger.write(f"[REGISTER] IP: {_client_ip(self)}, Login: {login}, Email: {email}")

        return self._json_ok({
            "status": "pending",
            "email": email,
            "login": login,
            "code_ttl_sec": AUTH_CODE_TTL_MIN * 60,
            "send_count": auth_code.send_count
        }, status=201)


def auth_register_resend(self, match, query):
    body = _parse_json_body(self) or {}
    email = (body.get("email") or "").strip().lower()
    if not _validate_email(email):
        return self._json_error(400, "bad_request", "Invalid fields", {"email": "Invalid email"})

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            return self._json_error(404, "not_found", "User not found")
        if user.is_active:
            return self._json_ok({"status": "already_confirmed"})

        now = _now_utc()
        auth_code = db.execute(
            select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "email_confirm")
        ).scalar_one_or_none()

        if auth_code and auth_code.expires_at <= now:
            db.delete(auth_code)
            db.flush()
            auth_code = None

        if auth_code is None:
            code = _gen_code(AUTH_CODE_LEN)
            auth_code = AuthCode(
                user_id=user.id, purpose="email_confirm",
                code_hash=_hash_code(code),
                created_at=now,
                expires_at=now + timedelta(minutes=AUTH_CODE_TTL_MIN),
                send_count=1, last_sent_at=now,
                input_count=0, last_input_at=None,
            )
            db.add(auth_code)
            db.commit()
            subject, mail_text, html = build_confirm_email(code, AUTH_CODE_TTL_MIN)
            send_email(email, subject, mail_text, html)
            return self._json_ok({"status": "resent", "send_count": 1, "code_ttl_sec": AUTH_CODE_TTL_MIN * 60})

        if auth_code.send_count >= MAX_SEND_PER_CODE:
            return self._json_error(429, "too_many_requests", "Resend limit reached",
                                    {"retry_after": int((auth_code.expires_at - now).total_seconds())})

        code = _gen_code(AUTH_CODE_LEN)
        auth_code.code_hash = _hash_code(code)
        auth_code.created_at = now
        auth_code.expires_at = now + timedelta(minutes=AUTH_CODE_TTL_MIN)
        auth_code.send_count = auth_code.send_count + 1
        auth_code.last_sent_at = now
        auth_code.input_count = 0
        auth_code.last_input_at = None
        db.commit()

        subject, mail_text, html = build_confirm_email(code, AUTH_CODE_TTL_MIN)
        send_email(email, subject, mail_text, html)
        return self._json_ok({"status": "resent", "send_count": auth_code.send_count, "code_ttl_sec": AUTH_CODE_TTL_MIN * 60})


def auth_register_confirm(self, match, query):
    body = _parse_json_body(self) or {}
    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()

    errors = {}
    if not _validate_email(email): errors["email"] = "Invalid email"
    if not code.isdigit() or len(code) != AUTH_CODE_LEN: errors["code"] = "Invalid code"
    if errors:
        return self._json_error(400, "bad_request", "Invalid fields", errors)

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            return self._json_error(404, "not_found", "User not found")
        if user.is_active:
            logger.write(f"[REGISTER CONFIRM] Already confirmed: IP: {_client_ip(self)}, Login: {user.login}, Email: {email}")
            return self._json_ok({"status": "already_confirmed"})

        auth_code = db.execute(
            select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "email_confirm")
        ).scalar_one_or_none()
        if not auth_code:
            return self._json_error(400, "bad_request", "No active code, request a new one")

        now = _now_utc()
        if auth_code.expires_at <= now:
            db.delete(auth_code)
            db.commit()
            logger.write(f"[REGISTER CONFIRM] Code expired: IP: {_client_ip(self)}, Login: {user.login}, Email: {email}")
            return self._json_error(400, "bad_request", "Code expired")

        if auth_code.input_count >= MAX_INPUT_ATTEMPTS:
            db.delete(auth_code)
            db.commit()
            logger.write(f"[REGISTER CONFIRM] Input attempts limit reached: IP: {_client_ip(self)}, Login: {user.login}, Email: {email}")
            return self._json_error(429, "too_many_requests", "Input attempts limit reached")

        auth_code.input_count = auth_code.input_count + 1
        auth_code.last_input_at = now

        if auth_code.code_hash != _hash_code(code):
            db.commit()
            logger.write(f"[REGISTER CONFIRM] Invalid code: IP: {_client_ip(self)}, Login: {user.login}, Email: {email}")
            return self._json_error(400, "bad_request", "Invalid code")

        user.is_active = True
        user.email_confirmed_at = now
        db.delete(auth_code)
        db.commit()

        logger.write(f"[REGISTER CONFIRM] IP: {_client_ip(self)}, Login: {user.login}, Email: {email}")

        return self._json_ok({"status": "confirmed"})


def auth_register_status(self, match, query):
    email = (query.get("email", [""])[0] or "").strip().lower()
    if not _validate_email(email):
        return self._json_error(400, "bad_request", "Invalid fields", {"email": "Invalid email"})

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            return self._json_error(404, "not_found", "User not found")

        if user.is_active:
            return self._json_ok({"status": "confirmed"})

        auth_code = db.execute(
            select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "email_confirm")
        ).scalar_one_or_none()

        now = _now_utc()
        if not auth_code:
            return self._json_ok({"status": "pending", "code": None})

        ttl = max(0, int((auth_code.expires_at - now).total_seconds()))
        return self._json_ok({
            "status": "pending",
            "code": {"send_count": auth_code.send_count, "input_count": auth_code.input_count, "ttl_sec": ttl}
        })


def _make_session(self, db, user: User, remember_me: bool, ip: str | None, ua: str | None):
    if user.current_session_id:
        old = db.get(DbSession, user.current_session_id)
        if old and old.revoked_at is None:
            old.revoked_at = _now_utc()

    now = _now_utc()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session = DbSession(
        user_id=user.id,
        session_hash=token_hash,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=SESSION_TTL_DAYS),
        revoked_at=None,
        ip_first=ip, ip_last=ip,
        ua_first=ua, ua_last=ua,
        remember_me=bool(remember_me),
    )
    db.add(session)
    db.flush()
    user.current_session_id = session.id
    db.commit()
    return token, session


def auth_login(self, match, query):
    body = _parse_json_body(self) or {}
    login = (body.get("login") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    remember = bool(body.get("remember", False))

    if not password or (not login and not email):
        return self._json_error(400, "bad_request", "Provide login or email and password")

    with SessionLocal() as db:
        q = select(User)
        if login:
            q = q.where(User.login == login)
        else:
            q = q.where(User.email == email)
        user = db.execute(q).scalar_one_or_none()
        if not user:
            logger.write(f"[LOGIN] Invalid credentials: IP: {_client_ip(self)}, Login: {login if login else None}, Email: {email if email else None}")
            return self._json_error(401, "unauthorized", "Invalid credentials")
        if not user.is_active:
            logger.write(f"[LOGIN] Email not confirmed: IP: {_client_ip(self)}, Login: {login if login else None}, Email: {email if email else None}")
            return self._json_error(403, "forbidden", "Email not confirmed")

        if not _verify_password(password, user.password_hash):
            logger.write(f"[LOGIN] Invalid password: IP: {_client_ip(self)}, Login: {login if login else None}, Email: {email if email else None}")
            return self._json_error(401, "unauthorized", "Invalid credentials")

        user.last_login_at = _now_utc()
        user.last_login_ip = self.client_address[0] if getattr(self, "client_address", None) else None

        raw_token, session = _make_session(
            self, db, user, remember,
            ip=user.last_login_ip, ua=self.headers.get("User-Agent")
        )

        logger.write(f"[LOGIN] IP: {_client_ip(self)}, Login: {login if login else None}, Email: {email if email else None}")

        return self._json_ok({
            "access_token": raw_token,
            "token_type": "bearer",
            "expires_at": session.expires_at.isoformat().replace("+00:00", "Z")
        })


def auth_logout(self, match, query):
    token = _extract_bearer(self)
    if not token:
        return self._json_error(401, "unauthorized", "Missing bearer token")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    with SessionLocal() as db:
        session = db.execute(select(DbSession).where(DbSession.session_hash == token_hash)).scalar_one_or_none()
        if not session:
            return self._json_error(401, "unauthorized", "Invalid session")
        if session.revoked_at is not None:
            return self._json_ok({"status": "already_revoked"})

        session.revoked_at = _now_utc()
        user = db.get(User, session.user_id)
        if user and user.current_session_id == session.id:
            user.current_session_id = None
        db.commit()

        return self._json_ok({"status": "revoked"})


def auth_whoami(self, match, query):
    token = _extract_bearer(self)
    if not token:
        return self._json_error(401, "unauthorized", "Missing bearer token")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _now_utc()

    with SessionLocal() as db:
        session = db.execute(select(DbSession).where(DbSession.session_hash == token_hash)).scalar_one_or_none()
        if not session or session.revoked_at is not None or session.expires_at <= now:
            return self._json_error(401, "unauthorized", "Invalid session")

        user = db.get(User, session.user_id)
        if not user:
            return self._json_error(401, "unauthorized", "Invalid session")
        if user.current_session_id != session.id:
            return self._json_error(409, "conflict", "Session mismatch")

        session.last_seen_at = now
        if ROLLING_TTL_ON_TOUCH:
            session.expires_at = now + timedelta(days=SESSION_TTL_DAYS)
        db.commit()

        return self._json_ok({
            "id": user.id,
            "email": user.email,
            "login": user.login,
            "is_active": user.is_active,
            "email_confirmed_at": user.email_confirmed_at.isoformat().replace("+00:00", "Z") if user.email_confirmed_at else None,
            "last_login_at": user.last_login_at.isoformat().replace("+00:00", "Z") if user.last_login_at else None,
            "last_login_ip": user.last_login_ip
        })

def auth_password_send_code(self, match, query):
    body = _parse_json_body(self) or {}
    email = (body.get("email") or "").strip().lower()
    if not _validate_email(email):
        return self._json_error(400, "bad_request", "Invalid fields", {"email": "Invalid email"})

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            return self._json_error(404, "not_found", "User not found")

        now = _now_utc()
        auth_code = db.execute(
            select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "password_reset")
        ).scalar_one_or_none()

        if auth_code and auth_code.expires_at <= now:
            db.delete(auth_code)
            db.flush()
            auth_code = None

        code = _gen_code(AUTH_CODE_LEN)
        code_hash = _hash_code(code)
        expires = now + timedelta(minutes=AUTH_CODE_TTL_MIN)

        if auth_code is None:
            auth_code = AuthCode(
                user_id=user.id, purpose="password_reset",
                code_hash=code_hash,
                created_at=now, expires_at=expires,
                send_count=1, last_sent_at=now,
                input_count=0, last_input_at=None,
            )
            db.add(auth_code)
        else:
            if auth_code.send_count >= MAX_SEND_PER_CODE:
                return self._json_error(
                    429, "too_many_requests", "Resend limit reached",
                    {"retry_after": int((auth_code.expires_at - now).total_seconds())}
                )
            auth_code.code_hash = code_hash
            auth_code.created_at = now
            auth_code.expires_at = expires
            auth_code.send_count = auth_code.send_count + 1
            auth_code.last_sent_at = now
            auth_code.input_count = 0
            auth_code.last_input_at = None

        db.commit()
        subject, mail_text, html = build_reset_email(code, AUTH_CODE_TTL_MIN)
        send_email(email, subject, mail_text, html)

        return self._json_ok({"status": "sent", "code_ttl_sec": AUTH_CODE_TTL_MIN * 60})


def auth_password_reset(self, match, query):
    body = _parse_json_body(self) or {}
    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()
    new_password = body.get("new_password") or ""
    new_password_confirm = body.get("new_password_confirm") or ""

    errors = {}
    if not _validate_email(email): errors["email"] = "Invalid email"
    if not code.isdigit() or len(code) != AUTH_CODE_LEN: errors["code"] = "Invalid code"
    if len(new_password) < PASSWORD_MIN_LEN: errors["new_password"] = f"Min length {PASSWORD_MIN_LEN}"
    if new_password != new_password_confirm: errors["new_password_confirm"] = "Must match new_password"
    if errors:
        return self._json_error(400, "bad_request", "Invalid fields", errors)

    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            return self._json_error(404, "not_found", "User not found")

        ac = db.execute(
            select(AuthCode).where(AuthCode.user_id == user.id, AuthCode.purpose == "password_reset")
        ).scalar_one_or_none()
        if not ac:
            return self._json_error(400, "bad_request", "No active reset code, request a new one")

        now = _now_utc()
        if ac.expires_at <= now:
            db.delete(ac)
            db.commit()
            return self._json_error(400, "bad_request", "Code expired")

        if ac.input_count >= MAX_INPUT_ATTEMPTS:
            db.delete(ac)
            db.commit()
            return self._json_error(429, "too_many_requests", "Input attempts limit reached")

        ac.input_count = ac.input_count + 1
        ac.last_input_at = now

        if ac.code_hash != _hash_code(code):
            db.commit()
            return self._json_error(400, "bad_request", "Invalid code")

        user.password_hash = _hash_password(new_password)
        if user.current_session_id:
            sess = db.get(DbSession, user.current_session_id)
            if sess and sess.revoked_at is None:
                sess.revoked_at = now
            user.current_session_id = None

        db.delete(ac)
        db.commit()
        logger.write(f"[PASSWORD RESET] IP: {_client_ip(self)}, Login: {user.login}, Email: {user.email}")
        return self._json_ok({"status": "password_changed"})


# Registration function into server
def register_auth_endpoints(HandlerClass, routes_list):
    HandlerClass.auth_register = auth_register
    HandlerClass.auth_register_confirm = auth_register_confirm
    HandlerClass.auth_register_resend = auth_register_resend
    HandlerClass.auth_register_status = auth_register_status

    HandlerClass.auth_login = auth_login
    HandlerClass.auth_logout = auth_logout
    HandlerClass.auth_whoami = auth_whoami

    HandlerClass.auth_password_send_code = auth_password_send_code
    HandlerClass.auth_password_reset = auth_password_reset

    routes_list.extend(AUTH_ROUTES)

    HandlerClass._auth_guard = _auth_guard


# Handlers available without authorization
PUBLIC_HANDLERS = {
    "healthz", "root",
    "auth_register", "auth_register_resend", "auth_register_confirm", "auth_register_status",
    "auth_login",
    "auth_password_send_code", "auth_password_reset",
}

def _auth_guard(self, handler_name: str):
    if handler_name in PUBLIC_HANDLERS:
        return
    from src.assistant.server import ApiError
    token = _extract_bearer(self)
    if not token:
        raise ApiError("Unauthorized", status=401, code="unauthorized")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _now_utc()

    with SessionLocal() as db:
        session = db.execute(select(DbSession).where(DbSession.session_hash == token_hash)).scalar_one_or_none()
        if not session or session.revoked_at is not None or session.expires_at <= now:
            raise ApiError("Unauthorized", status=401, code="unauthorized")

        user = db.get(User, session.user_id)
        if not user or not user.is_active:
            raise ApiError("Unauthorized", status=401, code="unauthorized")

        if user.current_session_id and user.current_session_id != session.id:
            raise ApiError("Conflict", status=409, code="conflict")

        self.auth_user = user
        self.auth_session = session