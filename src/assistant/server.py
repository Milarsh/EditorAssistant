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
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pathlib import Path
import mimetypes
from urllib.parse import unquote

from src.assistant.tg_auth import start_qr_sync, status_sync, submit_password_sync, logout_sync

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
        super().__init__(self.message)

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
            # media (local)
            ("GET", re.compile(r"^/media/(.+)$"), "serve_media"),
            # telegram auth
            ("GET", re.compile(r"^/api/tg/auth/status$"), "tg_auth_status"),
            ("POST", re.compile(r"^/api/tg/auth/qr$"), "tg_auth_start_qr"),
            ("POST", re.compile(r"^/api/tg/auth/2fa$"), "tg_auth_2fa"),
            ("POST", re.compile(r"^/api/tg/auth/logout$"), "tg_auth_logout"),
        ]

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")
        def do_DELETE(self): self._dispatch("DELETE")

        def _dispatch(self, method: str):
            # rate limiting по IP
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
                            return handler(match, parse_qs(parsed.query))
                        except ApiError as error:
                            return self._json_error(error.status, error.code, str(error), error.details)
                        except IntegrityError as error:
                            # дубликаты/уникальные ограничения и пр.
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
            self.end_headers()
            self.wfile.write(body)

        def _json_ok(self, payload, status=200):
            self._send(status, json_bytes(payload), "application/json; charset=utf-8")

        def _json_error(self, status, code, message, details=None):
            req_id = f"{int(datetime.now(timezone.utc).timestamp())}-{os.getpid()}"
            payload = {"error": {"code": code, "message": message, "request_id": req_id}}
            if details:
                payload["error"]["details"] = details
            self._send(status, json_bytes(payload), "application/json; charset=utf-8")

        def log_message(self, fmt, *args):
            print(f"[{self.command}] {self.path} - {self.address_string()}")

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

            with SessionLocal() as session:
                stmt = select(Article)
                if source_id:
                    stmt = stmt.where(Article.source_id == source_id)
                if text_q:
                    ilike = f"%{text_q}%"
                    stmt = stmt.where((Article.title.ilike(ilike)) | (Article.description.ilike(ilike)))

                total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
                stmt = stmt.order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
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

        # ---- заглушка ----
        def not_impl(self, match, query):
            raise ApiError("Endpoint will be implemented later", status=501, code="not_implemented")

    httpd = HTTPServer((host, port), Handler)
    print(f"Server listening on {host}:{port}")
    httpd.serve_forever()

def server_init():
    port = int(os.getenv("PORT", "8000"))
    run_server(port=port)