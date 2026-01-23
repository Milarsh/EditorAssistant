import os
import json
import re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from collections import deque, defaultdict

from src.db.db import SessionLocal
from src.db.models.source import Source
from src.db.models.article import Article
from src.db.models.stop_category import StopCategory
from src.db.models.rubric import Rubric
from src.db.models.stop_word import StopWord
from src.db.models.key_word import KeyWord
from src.db.models.article_stop_word import ArticleStopWord
from src.db.models.article_key_word import ArticleKeyWord
from src.db.models.article_stat import ArticleStat
from src.db.models.settings import Settings
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from src.utils.slugifier import slugify_code
from src.utils.analyzer import analyze_article_words

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pathlib import Path
import mimetypes
from urllib.parse import unquote

from src.assistant.tg_auth import start_qr_sync, status_sync, submit_password_sync, logout_sync

from src.assistant.auth import register_auth_endpoints

MEDIA_DIR = os.path.abspath(os.getenv("MEDIA_DIR", "./media"))

def _safe_join(base: str, *parts: str) -> Path:
    base_path = Path(base).resolve()
    full = base_path.joinpath(*parts).resolve()
    if not str(full).startswith(str(base_path)):
        raise ValueError("Unsafe path")
    return full

# -------- утилиты JSON --------
def json_bytes(data) -> bytes:
    def _default(value):
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo = timezone.utc)
            s = dt.isoformat(timespec="seconds")
            return s[:-6] + "Z" if s.endswith("+00:00") else s
        return str(value)
    return json.dumps(data, ensure_ascii=False, default=_default).encode("utf-8")

def parse_json_body(handler: BaseHTTPRequestHandler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length == 0:
        return None
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise ValidationError("Invalid JSON body")

# -------- Ошибки --------
@dataclass(slots=True)
class ApiError(Exception):
    message: str = "Internal error"
    status: int = 500
    code: str = "internal_error"
    details: Optional[Dict[str, Any]] = field(default=None)

    def __post_init__(self):
        Exception.__init__(self, self.message)

@dataclass(slots=True)
class ValidationError(ApiError):
    message: str = "Validation error"
    status: int = 400
    code: str = "bad_request"

@dataclass(slots=True)
class NotFound(ApiError):
    message: str = "Not found"
    status: int = 404
    code: str = "not_found"

@dataclass(slots=True)
class MethodNotAllowed(ApiError):
    message: str = "Method not allowed"
    status: int = 405
    code: str = "method_not_allowed"

@dataclass(slots=True)
class Conflict(ApiError):
    message: str = "Conflict"
    status: int = 409
    code: str = "conflict"

@dataclass(slots=True)
class TooManyRequests(ApiError):
    message: str = "Rate limit exceeded"
    status: int = 429
    code: str = "too_many_requests"

@dataclass(slots=True)
class SourceError(ApiError):
    message: str = "Source error"
    status: int = 400
    code: str = "source_error"

@dataclass(slots=True)
class ParserError(ApiError):
    message: str = "Parser error"
    status: int = 502
    code: str = "parser_error"

# -------- Rate Limiting --------
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))         # запросов
RATE_WINDOW = int(os.getenv("RATE_WINDOW", "60"))       # секунд
# очередь временных меток на каждый key (ip)
_rate_buckets = defaultdict(lambda: deque())

def _rate_check(ip: str):
    if RATE_LIMIT <= 0:
        return  # лимит отключен
    now = datetime.now(timezone.utc)
    win_start = now - timedelta(seconds=RATE_WINDOW)
    dq = _rate_buckets[ip]
    # очистим старые записи
    while dq and dq[0] < win_start:
        dq.popleft()
    if len(dq) >= RATE_LIMIT:
        raise TooManyRequests(f"Too many requests: limit {RATE_LIMIT} per {RATE_WINDOW}s")
    dq.append(now)

# ---- Хэндлер ----
def run_server(host: str = "0.0.0.0", port: int = 8000):
    class Handler(BaseHTTPRequestHandler):
        # Маршруты
        routes = [
            ("GET",  re.compile(r"^/healthz$"),               "healthz"),
            ("GET",  re.compile(r"^/$"),                      "root"),
            # sources
            ("GET",  re.compile(r"^/api/sources$"),           "list_sources"),
            ("POST", re.compile(r"^/api/sources$"),           "create_source"),
            ("DELETE", re.compile(r"^/api/sources/(\d+)$"),   "delete_source"),
            # articles
            ("GET",  re.compile(r"^/api/articles$"),          "list_articles"),
            ("GET",  re.compile(r"^/api/articles/(\d+)$"),    "get_article"),
            ("GET", re.compile(r"^/api/articles/(\d+)/media$"), "get_article_media"),
            ("GET", re.compile(r"^/api/articles/(\d+)/children$"), "get_article_children"),
            ("GET", re.compile(r"^/api/articles/(\d+)/parent$"), "get_article_parent"),
            # settings
            ("GET", re.compile(r"^/api/settings$"), "list_settings"), # ave
            ("POST", re.compile(r"^/api/settings$"), "update_settings"), # ave
            # media (local)
            ("GET", re.compile(r"^/media/(.+)$"), "serve_media"),
            # telegram auth
            ("GET", re.compile(r"^/api/tg/auth/status$"), "tg_auth_status"),
            ("POST", re.compile(r"^/api/tg/auth/qr$"), "tg_auth_start_qr"),
            ("POST", re.compile(r"^/api/tg/auth/2fa$"), "tg_auth_2fa"),
            ("POST", re.compile(r"^/api/tg/auth/logout$"), "tg_auth_logout"),

            # категории стоп-слов и рубрики
            ("GET",  re.compile(r"^/api/stop-categories$"),         "list_stop_categories"),
            ("POST", re.compile(r"^/api/stop-categories$"),         "upsert_stop_category"),
            ("DELETE", re.compile(r"^/api/stop-categories/(\d+)$"), "delete_stop_category"),
            
            ("GET",  re.compile(r"^/api/rubrics$"),                 "list_rubrics"),
            ("POST", re.compile(r"^/api/rubrics$"),                 "upsert_rubric"),
            ("DELETE", re.compile(r"^/api/rubrics/(\d+)$"),         "delete_rubric"),

            # стоп-слова и ключевые слова
            ("GET",  re.compile(r"^/api/stop-words$"),              "list_stop_words"),
            ("POST", re.compile(r"^/api/stop-words$"),              "upsert_stop_word"),
            ("DELETE", re.compile(r"^/api/stop-words/(\d+)$"),      "delete_stop_word"),

            ("GET",  re.compile(r"^/api/key-words$"),               "list_key_words"),
            ("POST", re.compile(r"^/api/key-words$"),               "upsert_key_word"),
            ("DELETE", re.compile(r"^/api/key-words/(\d+)$"),       "delete_key_word"),

            # статистика по статье
            ("GET",  re.compile(r"^/api/articles/(\d+)/stats$"),        "get_article_stats"),
            ("GET", re.compile(r"^/api/articles/(\d+)/stop-words$"), "get_article_stop_words"),
            ("GET", re.compile(r"^/api/articles/(\d+)/key-words$"), "get_article_key_words"),
        ]

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")
        def do_DELETE(self): self._dispatch("DELETE")

        def _dispatch(self, method: str):
            ip = self.address_string()
            try:
                _rate_check(ip)
            except ApiError as error:
                return self._json_error(error.status, error.code, str(error))

            parsed = urlparse(self.path)
            path = parsed.path
            for http_method, regex, handler_name in self.routes:
                if http_method == method:
                    match = regex.match(path)
                    if match:
                        try:
                            handler = getattr(self, handler_name)
                            if hasattr(self, "_auth_guard"):
                                self._auth_guard(handler_name)
                            return handler(match, parse_qs(parsed.query))
                        except ApiError as error:
                            return self._json_error(error.status, error.code, str(error), error.details)
                        except IntegrityError as error:
                            return self._json_error(409, "conflict", "Database constraint violation", {"detail": str(error.orig)})
                        except Exception as error:
                            print(f"[ERROR] {method} {path}: {error}")
                            return self._json_error(500, "internal_error", "Internal server error")
            return self._json_error(405, "method_not_allowed", "Method not allowed")

        # ---- Ответы ----
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            origin = self.headers.get("Origin")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin if origin != "null" else "*")
                self.send_header("Vary", "Origin")
            else:
                self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin") or "*"
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin if origin != "null" else "*")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()

        def _json_ok(self, payload, status=200):
            self._send(status, json_bytes(payload), "application/json; charset=utf-8")

        def _json_error(self, status, code, message, details=None):
            req_id = f"{int(datetime.now(timezone.utc).timestamp())}-{os.getpid()}"
            payload = {"error": {"code": code, "message": message, "request_id": req_id}}
            if details:
                payload["error"]["details"] = details
            self._send(status, json_bytes(payload), "application/json; charset=utf-8")

        def log_message(self, fmt, *args):
            method = getattr(self, "command", "-")
            path = getattr(self, "path", "<no-path>")
            print(f"[{method}] {path} - {self.address_string()}")

        # ---- Handlers ----
        def healthz(self, match, query):
            self._send(200, b"OK\n", "text/plain; charset=utf-8")

        def root(self, match, query):
            self._send(200, b"Editor Assistant backend is running\n", "text/plain; charset=utf-8")

        # ---- Sources ----
        def list_sources(self, match, query):
            with SessionLocal() as session:
                rows = session.execute(select(Source).order_by(Source.id)).scalars().all()
                self._json_ok([{
                    "id": r.id, "name": r.name, "type": r.type, "rss_url": r.rss_url,
                    "enabled": r.enabled, "created_at": r.created_at
                } for r in rows])

        def create_source(self, match, query):
            body = parse_json_body(self) or {}
            name = (body.get("name") or "").strip()
            rss_url = (body.get("rss_url") or "").strip()
            enabled = bool(body.get("enabled", True))

            errors = {}
            if not name:
                errors["name"] = "Required"
            if not rss_url or not (rss_url.startswith("http://") or rss_url.startswith("https://")):
                errors["rss_url"] = "Must be valid http(s) URL"
            if errors:
                raise ValidationError("Invalid fields", details=errors)

            if "vk.com" in rss_url:
                source_type = "vk"
            elif "t.me" in rss_url or "telegram.me" in rss_url:
                source_type = "tg"
            else:
                source_type = "rss"

            with SessionLocal() as session:
                try:
                    obj = Source(name=name, type=source_type, rss_url=rss_url, enabled=enabled)
                    session.add(obj)
                    session.commit()
                    session.refresh(obj)
                except IntegrityError as error:
                    session.rollback()
                    raise Conflict("rss_url already exists")
                self._json_ok({"id": obj.id, "name": obj.name, "type": obj.type, "rss_url": obj.rss_url,
                               "enabled": obj.enabled, "created_at": obj.created_at}, status=201)

        def delete_source(self, match, query):
            source_id = int(match.group(1))
            with SessionLocal() as session:
                obj = session.get(Source, source_id)
                if not obj:
                    raise NotFound("Source not found")
                session.delete(obj)
                session.commit()
                self._json_ok({"status": "deleted", "id": source_id})

        # ---- Articles ----
        def list_articles(self, match, query):
            source_id = int(query.get("source_id", [0])[0]) if "source_id" in query else None
            text_q = (query.get("q", [""])[0] or "").strip()
            limit = max(1, min(100, int(query.get("limit", [20])[0])))
            offset = max(0, int(query.get("offset", [0])[0]))

            date_from_raw = (query.get("date_from", [""])[0] or "").strip()
            date_to_raw = (query.get("date_to", [""])[0] or "").strip()
            order = (query.get("order", ["desc"])[0] or "desc").lower()  # asc | desc

            raw_rubric_id = (query.get("rubric_id", [""])[0] or "").strip()
            rubric_id = None
            if raw_rubric_id:
                try:
                    rubric_id = int(raw_rubric_id)
                except Exception:
                    raise ValidationError("Invalid fields", details={"rubric_id": "Must be integer"})

            def _parse_dt(val: str, end_of_day: bool = False):
                if not val:
                    return None
                if len(val) == 10 and val[4] == "-" and val[7] == "-":
                    y, m, d = map(int, val.split("-"))
                    base = datetime(y, m, d, tzinfo=timezone.utc)
                    if end_of_day:
                        return base + timedelta(days=1) - timedelta(microseconds=1)
                    return base
                val = val.replace("Z", "+00:00")
                dt = datetime.fromisoformat(val)
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

            try:
                dt_from = _parse_dt(date_from_raw, end_of_day=False)
                dt_to = _parse_dt(date_to_raw, end_of_day=True)
            except Exception:
                raise ValidationError("Invalid date format", details={
                    "date_from": "Use RFC3339 or YYYY-MM-DD" if date_from_raw else None,
                    "date_to": "Use RFC3339 or YYYY-MM-DD" if date_to_raw else None,
                })

            if dt_from and dt_to and dt_from > dt_to:
                raise ValidationError("Invalid date range", details={"date_from": "must be <= date_to"})

            with SessionLocal() as session:
                stmt = (
                    select(Article)
                    .outerjoin(ArticleStat, ArticleStat.entity_id == Article.id)
                )

                if source_id:
                    stmt = stmt.where(Article.source_id == source_id)

                if text_q:
                    ilike = f"%{text_q}%"
                    stmt = stmt.where((Article.title.ilike(ilike)) | (Article.description.ilike(ilike)))

                if dt_from:
                    stmt = stmt.where(Article.published_at >= dt_from)
                if dt_to:
                    stmt = stmt.where(Article.published_at <= dt_to)

                if rubric_id is not None:
                    stmt = stmt.where(ArticleStat.rubric_id == rubric_id)

                total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

                if order == "asc":
                    stmt = stmt.order_by(
                        Article.published_at.asc().nulls_last(),
                        Article.id.asc(),
                    )
                else:
                    stmt = stmt.order_by(
                        Article.published_at.desc().nulls_last(),
                        Article.id.desc(),
                    )

                rows = session.execute(stmt.limit(limit).offset(offset)).scalars().all()

                self._json_ok({
                    "total": total, "limit": limit, "offset": offset,
                    "items": [{
                        "id": a.id,
                        "source_id": a.source_id,
                        "title": a.title,
                        "link": a.link,
                        "description": a.description,
                        "guid": a.guid,
                        "published_at": a.published_at,
                        "fetched_at": a.fetched_at,
                        "parent_article_id": a.parent_article_id
                    } for a in rows]
                })

        def get_article(self, match, query):
            article_id = int(match.group(1))
            with SessionLocal() as session:
                article = session.get(Article, article_id)
                if not article:
                    raise NotFound("Article not found")
                self._json_ok({
                    "id": article.id,
                    "source_id": article.source_id,
                    "title": article.title,
                    "link": article.link,
                    "description": article.description,
                    "guid": article.guid,
                    "published_at": article.published_at,
                    "fetched_at": article.fetched_at,
                    "parent_article_id": article.parent_article_id
                })

        def get_article_media(self, match, query):
            article_id = int(match.group(1))
            with SessionLocal() as session:
                article = session.get(Article, article_id)
                if not article:
                    raise NotFound("Article not found")

                assets = []

                try:
                    if article.guid and article.guid.startswith("vk:"):
                        _, owner_str, post_str = article.guid.split(":", 2)

                        found_dir = None
                        dir = _safe_join(MEDIA_DIR, "vk", owner_str, post_str)
                        if dir.exists() and dir.is_dir():
                            found_dir = dir

                        if found_dir:
                            for path in sorted(found_dir.iterdir()):
                                if not path.is_file():
                                    continue
                                if path.name == "media.json":
                                    continue
                                rel = path.relative_to(Path(MEDIA_DIR)).as_posix()
                                file_url = f"/media/{rel}"
                                mime, _ = mimetypes.guess_type(path.name)
                                type = "image" if (mime or "").startswith("image/") else "file"
                                assets.append({
                                    "type": type,
                                    "file_url": file_url,
                                    "mime": mime or "application/octet-stream",
                                    "name": path.name,
                                })

                            manifest_path = found_dir / "media.json"
                            if manifest_path.exists():
                                try:
                                    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
                                    for it in meta:
                                        if it.get("type") == "video":
                                            assets.append({
                                                "type": "video",
                                                "page_url": it.get("page_url"),
                                                "embed_url": it.get("embed_url"),
                                            })
                                except Exception as exception:
                                    print(f"[WARN] bad media.json for article {article_id}: {exception}")
                    elif article.guid and article.guid.startswith("tg:"):
                        _, channel, msg_id = article.guid.split(":", 2)
                        found_dir = None
                        dir = _safe_join(MEDIA_DIR, "tg", channel, msg_id)
                        if dir.exists() and dir.is_dir():
                            found_dir = dir

                        if found_dir:
                            for path in sorted(found_dir.iterdir()):
                                if path.is_file() and path.name != "media.json":
                                    rel = path.relative_to(Path(MEDIA_DIR)).as_posix()
                                    mime, _ = mimetypes.guess_type(path.name)
                                    type = "image" if (mime or "").startswith("image/") else (
                                        "video" if (mime or "").startswith("video/") else "file"
                                    )
                                    assets.append({
                                        "type": type,
                                        "file_url": f"/media/{rel}",
                                        "mime": mime or "application/octet-stream",
                                        "name": path.name,
                                    })

                except Exception as exception:
                    print(f"[ERROR] assets for article {article_id}: {exception}")

                self._json_ok({"id": article_id, "assets": assets})

        def get_article_children(self, match, query):
            article_id = int(match.group(1))
            limit = max(1, min(100, int(query.get("limit", [50])[0])))
            offset = max(0, int(query.get("offset", [0])[0]))

            with SessionLocal() as session:
                parent = session.get(Article, article_id)
                if not parent:
                    raise NotFound("Article not found")

                base_stmt = select(Article).where(Article.parent_article_id == article_id)
                total = session.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0

                rows = session.execute(
                    base_stmt
                    .order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
                    .limit(limit)
                    .offset(offset)
                ).scalars().all()

                self._json_ok({
                    "id": article_id,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "items": [{
                        "id": a.id,
                        "source_id": a.source_id,
                        "title": a.title,
                        "link": a.link,
                        "description": a.description,
                        "guid": a.guid,
                        "published_at": a.published_at,
                        "fetched_at": a.fetched_at,
                        "parent_article_id": a.parent_article_id,
                    } for a in rows]
                })

        def get_article_parent(self, match, query):
            article_id = int(match.group(1))
            with SessionLocal() as session:
                article = session.get(Article, article_id)
                if not article:
                    raise NotFound("Article not found")

                if not article.parent_article_id:
                    return self._json_ok({"id": article_id, "parent": None})

                parent = session.get(Article, article.parent_article_id)
                if not parent:
                    return self._json_ok({"id": article_id, "parent": None})

                self._json_ok({
                    "id": article_id,
                    "parent": {
                        "id": parent.id,
                        "source_id": parent.source_id,
                        "title": parent.title,
                        "link": parent.link,
                        "description": parent.description,
                        "guid": parent.guid,
                        "published_at": parent.published_at,
                        "fetched_at": parent.fetched_at,
                        "parent_article_id": parent.parent_article_id,
                    }
                })

        # Settings
        def list_settings(self, match, query):
            raw_codes = (query.get("codes", [""])[0] or "").strip()
            codes = [c.strip() for c in raw_codes.split(",") if c.strip()] if raw_codes else []

            with SessionLocal() as session:
                stmt = select(Settings)
                if codes:
                    stmt = stmt.where(Settings.code.in_(codes))
                stmt = stmt.order_by(Settings.code.asc())

                rows = session.execute(stmt).scalars().all()

                self._json_ok([
                    {
                        "id": s.id,
                        "code": s.code,
                        "value": s.value,
                    }
                    for s in rows
                ])

        def update_settings(self, match, query):
            body = parse_json_body(self) or {}

            code = (body.get("code") or "").strip()
            value = body.get("value")

            errors = {}
            if not code:
                errors["code"] = "Required"
            if value is None:
                errors["value"] = "Required"
            if errors:
                raise ValidationError("Invalid fields", details=errors)
            
            with SessionLocal() as session:
                stmt = session.execute(
                    select(Settings).where(Settings.code == code)
                ).scalar_one_or_none()

                if stmt:
                    stmt.value = str(value)
                    status = 200
                else:
                    stmt = Settings(code=code, value=value)
                    session.add(stmt)
                    status = 201
                
                session.commit()
                session.refresh(stmt)

                res = {
                    "id": stmt.id,
                    "code": stmt.code,
                    "value": stmt.value
                }

                self._json_ok(res, status=status)

        # Media (Local)
        def serve_media(self, match, query):
            rel_path = match.group(1)
            try:
                rel_path = unquote(rel_path)
                rel_path = rel_path.lstrip("/").replace("\\", "/")
                fs_path = _safe_join(MEDIA_DIR, rel_path)
                if not fs_path.exists() or not fs_path.is_file():
                    return self._json_error(404, "not_found", "Media file not found")
                file_size = fs_path.stat().st_size
                mime, _ = mimetypes.guess_type(str(fs_path))
                mime = mime or "application/octet-stream"

                range = self.headers.get("Range")
                start, end = 0, file_size - 1
                status = 200
                extra_headers = []

                if range and range.startswith("bytes="):
                    try:
                        part = range.split("=", 1)[1]
                        s, _, e = part.partition("-")
                        if s.strip():
                            start = max(0, int(s))
                        if e.strip():
                            end = min(file_size - 1, int(e))
                        if start > end:
                            start, end = 0, file_size - 1
                        status = 206
                        extra_headers.extend([
                            ("Content-Range", f"bytes {start}-{end}/{file_size}"),
                            ("Accept-Ranges", "bytes"),
                        ])
                    except Exception:
                        start, end = 0, file_size - 1
                        status = 200

                length = end - start + 1

                try:
                    self.send_response(status)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(length))
                    if status == 206:
                        pass
                    self.send_header("Accept-Ranges", "bytes")
                    for k, v in extra_headers:
                        self.send_header(k, v)
                    self.end_headers()
                    with open(fs_path, "rb") as file:
                        file.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = file.read(min(512 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    return
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as exception:
                    print(f"[ERROR] stream media {rel_path}: {exception}")
                    return

            except ValueError:
                return self._json_error(400, "bad_request", "Invalid media path")
            except Exception as exception:
                print(f"[ERROR] GET /media/{rel_path}: {exception}")
                try:
                    return self._json_error(500, "internal_error", "Internal server error")
                except Exception:
                    return

        # Telegram Auth
        def tg_auth_status(self, match, query):
            data = status_sync()
            self._json_ok(data)

        def tg_auth_start_qr(self, match, query):
            body = parse_json_body(self) or {}
            force = bool(body.get("force", False))
            data = start_qr_sync(force=force)
            self._json_ok(data)

        def tg_auth_2fa(self, match, query):
            body = parse_json_body(self) or {}
            password = (body.get("password") or "").strip()
            if not password:
                raise ValidationError("Invalid fields", details={"password": "Required"})
            data = submit_password_sync(password)
            if data.get("status") == "password_required" and data.get("error") == "bad_password":
                return self._json_error(400, "bad_request", "Bad password", {"password": "bad_password"})
            self._json_ok(data)

        def tg_auth_logout(self, match, query):
            data = logout_sync()
            self._json_ok(data)

        # article word stats
        def get_article_stats(self, match, query):
            article_id = int(match.group(1))
            with SessionLocal() as session:
                try:
                    stats = analyze_article_words(session, article_id)
                except ValueError:
                    raise NotFound("Article not found")

                self._json_ok({
                    "entity_id": stats.entity_id,
                    "stop_words_count": stats.stop_words_count,
                    "key_words_count": stats.key_words_count,
                    "rubric_id": stats.rubric_id,
                    "stop_category_id": stats.stop_category_id,
                })

        def get_article_stop_words(self, match, query):
            article_id = int(match.group(1))
            with SessionLocal() as session:
                article = session.get(Article, article_id)
                if not article:
                    raise NotFound("Article not found")

                rows = session.execute(
                    select(StopWord)
                    .join(ArticleStopWord, ArticleStopWord.stop_word_id == StopWord.id)
                    .where(ArticleStopWord.entity_id == article_id)
                    .order_by(StopWord.id)
                ).scalars().all()

                self._json_ok({
                    "id": article_id,
                    "items": [
                        {
                            "id": w.id,
                            "code": w.code,
                            "value": w.value,
                            "category_id": w.category_id,
                        }
                        for w in rows
                    ],
                })

        def get_article_key_words(self, match, query):
            article_id = int(match.group(1))
            with SessionLocal() as session:
                article = session.get(Article, article_id)
                if not article:
                    raise NotFound("Article not found")

                rows = session.execute(
                    select(KeyWord)
                    .join(ArticleKeyWord, ArticleKeyWord.key_word_id == KeyWord.id)
                    .where(ArticleKeyWord.entity_id == article_id)
                    .order_by(KeyWord.id)
                ).scalars().all()

                self._json_ok({
                    "id": article_id,
                    "items": [
                        {
                            "id": w.id,
                            "code": w.code,
                            "value": w.value,
                            "rubric_id": w.rubric_id,
                        }
                        for w in rows
                    ],
                })

        # key words
        def list_key_words(self, match, query):
            with SessionLocal() as session:
                rows = session.execute(
                    select(KeyWord).order_by(KeyWord.id)
                ).scalars().all()
                self._json_ok([
                    {
                        "id": w.id,
                        "code": w.code,
                        "value": w.value,
                        "rubric_id": w.rubric_id,
                    }
                    for w in rows
                ])

        def upsert_key_word(self, match, query):
            body = parse_json_body(self) or {}
            word_id = body.get("id")
            value = (body.get("value") or "").strip()
            raw_rubric_id = body.get("rubric_id")

            errors = {}
            if not value:
                errors["value"] = "Required"
            try:
                rubric_id = int(raw_rubric_id) if raw_rubric_id is not None else 0
            except Exception:
                rubric_id = 0
                errors["rubric_id"] = "Must be integer"
            if rubric_id <= 0:
                errors.setdefault("rubric_id", "Required")

            if errors:
                raise ValidationError("Invalid fields", details=errors)

            code = slugify_code(value)

            with SessionLocal() as session:
                rubric = session.get(Rubric, rubric_id)
                if not rubric:
                    raise ValidationError("Invalid fields", details={"rubric_id": "Rubric not found"})

                existing = session.execute(
                    select(KeyWord).where(KeyWord.code == code)
                ).scalar_one_or_none()

                if word_id is not None:
                    try:
                        word_id = int(word_id)
                    except Exception:
                        raise ValidationError("Invalid fields", details={"id": "Must be integer"})

                    obj = session.get(KeyWord, word_id)
                    if not obj:
                        raise NotFound("Key word not found")

                    if existing and existing.id != obj.id:
                        raise Conflict(
                            "Key word with same code already exists",
                            details={"code": code}
                        )

                    obj.value = value
                    obj.code = code
                    obj.rubric_id = rubric_id
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({
                        "id": obj.id,
                        "code": obj.code,
                        "value": obj.value,
                        "rubric_id": obj.rubric_id,
                    })
                else:
                    if existing:
                        raise Conflict(
                            "Key word with same code already exists",
                            details={"code": code}
                        )

                    obj = KeyWord(value=value, code=code, rubric_id=rubric_id)
                    session.add(obj)
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({
                        "id": obj.id,
                        "code": obj.code,
                        "value": obj.value,
                        "rubric_id": obj.rubric_id,
                    }, status=201)

        def delete_key_word(self, match, query):
            word_id = int(match.group(1))
            with SessionLocal() as session:
                obj = session.get(KeyWord, word_id)
                if not obj:
                    raise NotFound("Key word not found")
                session.delete(obj)
                session.commit()
                self._json_ok({"status": "deleted", "id": word_id})


        # stop words
        def list_stop_words(self, match, query):
            with SessionLocal() as session:
                rows = session.execute(
                    select(StopWord).order_by(StopWord.id)
                ).scalars().all()
                self._json_ok([
                    {
                        "id": w.id,
                        "code": w.code,
                        "value": w.value,
                        "category_id": w.category_id,
                    }
                    for w in rows
                ])

        def upsert_stop_word(self, match, query):
            body = parse_json_body(self) or {}
            word_id = body.get("id")
            value = (body.get("value") or "").strip()
            raw_category_id = body.get("category_id")

            errors = {}
            if not value:
                errors["value"] = "Required"
            try:
                category_id = int(raw_category_id) if raw_category_id is not None else 0
            except Exception:
                category_id = 0
                errors["category_id"] = "Must be integer"
            if category_id <= 0:
                errors.setdefault("category_id", "Required")

            if errors:
                raise ValidationError("Invalid fields", details=errors)

            code = slugify_code(value)

            with SessionLocal() as session:
                category = session.get(StopCategory, category_id)
                if not category:
                    raise ValidationError("Invalid fields", details={"category_id": "Category not found"})

                existing = session.execute(
                    select(StopWord).where(StopWord.code == code)
                ).scalar_one_or_none()

                if word_id is not None:
                    try:
                        word_id = int(word_id)
                    except Exception:
                        raise ValidationError("Invalid fields", details={"id": "Must be integer"})

                    obj = session.get(StopWord, word_id)
                    if not obj:
                        raise NotFound("Stop word not found")

                    if existing and existing.id != obj.id:
                        raise Conflict(
                            "Stop word with same code already exists",
                            details={"code": code}
                        )

                    obj.value = value
                    obj.code = code
                    obj.category_id = category_id
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({
                        "id": obj.id,
                        "code": obj.code,
                        "value": obj.value,
                        "category_id": obj.category_id,
                    })
                else:
                    if existing:
                        raise Conflict(
                            "Stop word with same code already exists",
                            details={"code": code}
                        )

                    obj = StopWord(value=value, code=code, category_id=category_id)
                    session.add(obj)
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({
                        "id": obj.id,
                        "code": obj.code,
                        "value": obj.value,
                        "category_id": obj.category_id,
                    }, status=201)

        def delete_stop_word(self, match, query):
            word_id = int(match.group(1))
            with SessionLocal() as session:
                obj = session.get(StopWord, word_id)
                if not obj:
                    raise NotFound("Stop word not found")
                session.delete(obj)
                session.commit()
                self._json_ok({"status": "deleted", "id": word_id})

        # rubrics
        def list_rubrics(self, match, query):
            with SessionLocal() as session:
                rows = session.execute(
                    select(Rubric).order_by(Rubric.id)
                ).scalars().all()
                self._json_ok([
                    {"id": r.id, "code": r.code, "title": r.title}
                    for r in rows
                ])

        def upsert_rubric(self, match, query):
            body = parse_json_body(self) or {}
            rubric_id = body.get("id")
            title = (body.get("title") or "").strip()

            errors = {}
            if not title:
                errors["title"] = "Required"
            if errors:
                raise ValidationError("Invalid fields", details=errors)

            code = slugify_code(title)

            with SessionLocal() as session:
                existing = session.execute(
                    select(Rubric).where(Rubric.code == code)
                ).scalar_one_or_none()

                if rubric_id is not None:
                    try:
                        rubric_id = int(rubric_id)
                    except Exception:
                        raise ValidationError("Invalid fields", details={"id": "Must be integer"})

                    obj = session.get(Rubric, rubric_id)
                    if not obj:
                        raise NotFound("Rubric not found")

                    if existing and existing.id != obj.id:
                        raise Conflict(
                            "Rubric with same code already exists",
                            details={"code": code}
                        )

                    obj.title = title
                    obj.code = code
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({"id": obj.id, "code": obj.code, "title": obj.title})
                else:
                    if existing:
                        raise Conflict(
                            "Rubric with same code already exists",
                            details={"code": code}
                        )
                    obj = Rubric(title=title, code=code)
                    session.add(obj)
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({"id": obj.id, "code": obj.code, "title": obj.title}, status=201)

        def delete_rubric(self, match, query):
            rubric_id = int(match.group(1))
            with SessionLocal() as session:
                obj = session.get(Rubric, rubric_id)
                if not obj:
                    raise NotFound("Rubric not found")
                session.delete(obj)
                session.commit()
                self._json_ok({"status": "deleted", "id": rubric_id})

        # stop categories
        def list_stop_categories(self, match, query):
            with SessionLocal() as session:
                rows = session.execute(
                    select(StopCategory)
                    .where(StopCategory.is_active.is_(True))
                    .order_by(StopCategory.id)
                ).scalars().all()
                self._json_ok([
                    {"id": r.id, "code": r.code, "title": r.title}
                    for r in rows
                ])

        def upsert_stop_category(self, match, query):
            body = parse_json_body(self) or {}
            cat_id = body.get("id")
            title = (body.get("title") or "").strip()

            errors = {}
            if not title:
                errors["title"] = "Required"
            if errors:
                raise ValidationError("Invalid fields", details=errors)

            code = slugify_code(title)

            with SessionLocal() as session:
                existing = session.execute(
                    select(StopCategory).where(StopCategory.code == code)
                ).scalar_one_or_none()

                if cat_id is not None:
                    try:
                        cat_id = int(cat_id)
                    except Exception:
                        raise ValidationError("Invalid fields", details={"id": "Must be integer"})

                    obj = session.get(StopCategory, cat_id)
                    if not obj:
                        raise NotFound("Stop category not found")

                    if existing and existing.id != obj.id:
                        raise Conflict(
                            "Stop category with same code already exists",
                            details={"code": code}
                        )

                    obj.title = title
                    obj.code = code
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({"id": obj.id, "code": obj.code, "title": obj.title})
                else:
                    if existing:
                        raise Conflict(
                            "Stop category with same code already exists",
                            details={"code": code}
                        )
                    obj = StopCategory(title=title, code=code)
                    session.add(obj)
                    session.commit()
                    session.refresh(obj)
                    self._json_ok({"id": obj.id, "code": obj.code, "title": obj.title}, status=201)

        def delete_stop_category(self, match, query):
            cat_id = int(match.group(1))
            with SessionLocal() as session:
                obj = session.get(StopCategory, cat_id)
                if not obj:
                    raise NotFound("Stop category not found")
                session.delete(obj)
                session.commit()
                self._json_ok({"status": "deleted", "id": cat_id})

        # ---- заглушка ----
        def not_impl(self, match, query):
            raise ApiError("Endpoint will be implemented later", status=501, code="not_implemented")

    from src.utils.settings import ensure_base_settings
    ensure_base_settings()

    register_auth_endpoints(Handler, Handler.routes)
    httpd = HTTPServer((host, port), Handler)
    print(f"Server listening on {host}:{port}")
    httpd.serve_forever()

def server_init():
    port = int(os.getenv("PORT", "8000"))
    run_server(port=port)