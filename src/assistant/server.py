import os
import json
import re
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from collections import deque, defaultdict

from src.db.db import SessionLocal
from src.db.models import Source, Article
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# -------- утилиты JSON --------
def json_bytes(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")

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
class ApiError(Exception):
    status = 500
    code = "internal_error"
    def __init__(self, message="Internal error", *, status=None, code=None, details=None):
        super().__init__(message)
        if status: self.status = status
        if code: self.code = code
        self.details = details or {}

class ValidationError(ApiError):
    def __init__(self, msg="Validation error", details=None):
        super().__init__(msg, status=400, code="bad_request", details=details)

class NotFound(ApiError):
    def __init__(self, msg="Not found"):
        super().__init__(msg, status=404, code="not_found")

class MethodNotAllowed(ApiError):
    def __init__(self, msg="Method not allowed"):
        super().__init__(msg, status=405, code="method_not_allowed")

class Conflict(ApiError):
    def __init__(self, msg="Conflict"):
        super().__init__(msg, status=409, code="conflict")

class TooManyRequests(ApiError):
    def __init__(self, msg="Rate limit exceeded"):
        super().__init__(msg, status=429, code="too_many_requests")

# Ошибки домена
class SourceError(ApiError):
    def __init__(self, msg="Source error", details=None):
        super().__init__(msg, status=400, code="source_error", details=details)

class ParserError(ApiError):
    def __init__(self, msg="Parser error", details=None):
        super().__init__(msg, status=502, code="parser_error", details=details)

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
            # стоп-слова и категории
            ("GET", re.compile(r"^/api/stopwords$"), "stopwords_placeholder"),
            ("POST", re.compile(r"^/api/stopwords$"), "stopwords_placeholder"),
            ("GET", re.compile(r"^/api/categories$"), "stopwords_placeholder"),
            ("POST", re.compile(r"^/api/categories$"), "stopwords_placeholder"),
        ]

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")
        def do_DELETE(self): self._dispatch("DELETE")

        def _dispatch(self, method: str):
            # rate limiting по IP
            ip = self.address_string()
            try:
                _rate_check(ip)
            except ApiError as e:
                return self._json_error(e.status, e.code, str(e))

            parsed = urlparse(self.path)
            path = parsed.path
            for m, regex, handler_name in self.routes:
                if m == method:
                    mobj = regex.match(path)
                    if mobj:
                        try:
                            return getattr(self, handler_name)(mobj, parse_qs(parsed.query))
                        except ApiError as e:
                            return self._json_error(e.status, e.code, str(e), e.details)
                        except IntegrityError as e:
                            # дубликаты/уникальные ограничения и пр.
                            return self._json_error(409, "conflict", "Database constraint violation", {"detail": str(e.orig)})
                        except Exception as e:
                            print(f"[ERROR] {method} {path}: {e}")
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
        def healthz(self, m, q):
            self._send(200, b"OK\n", "text/plain; charset=utf-8")

        def root(self, m, q):
            self._send(200, b"Editor Assistant backend is running\n", "text/plain; charset=utf-8")

        # ---- Sources ----
        def list_sources(self, m, q):
            with SessionLocal() as s:
                rows = s.execute(select(Source).order_by(Source.id)).scalars().all()
                self._json_ok([{
                    "id": r.id, "name": r.name, "rss_url": r.rss_url,
                    "enabled": r.enabled, "created_at": r.created_at
                } for r in rows])

        def create_source(self, m, q):
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
                raise ValidationError("Invalid fields", errors)

            with SessionLocal() as s:
                try:
                    obj = Source(name=name, rss_url=rss_url, enabled=enabled)
                    s.add(obj);
                    s.commit();
                    s.refresh(obj)
                except IntegrityError as e:
                    s.rollback()
                    raise Conflict("rss_url already exists")
                self._json_ok({"id": obj.id, "name": obj.name, "rss_url": obj.rss_url,
                               "enabled": obj.enabled, "created_at": obj.created_at}, status=201)

        def delete_source(self, m, q):
            source_id = int(m.group(1))
            with SessionLocal() as s:
                obj = s.get(Source, source_id)
                if not obj:
                    raise NotFound("Source not found")
                s.delete(obj);
                s.commit()
                self._json_ok({"status": "deleted", "id": source_id})

        # ---- Articles ----
        def list_articles(self, m, q):
            source_id = int(q.get("source_id", [0])[0]) if "source_id" in q else None
            text_q = (q.get("q", [""])[0] or "").strip()
            limit = max(1, min(100, int(q.get("limit", [20])[0])))
            offset = max(0, int(q.get("offset", [0])[0]))

            with SessionLocal() as s:
                stmt = select(Article)
                if source_id:
                    stmt = stmt.where(Article.source_id == source_id)
                if text_q:
                    ilike = f"%{text_q}%"
                    stmt = stmt.where((Article.title.ilike(ilike)) | (Article.description.ilike(ilike)))

                total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
                stmt = stmt.order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
                rows = s.execute(stmt.limit(limit).offset(offset)).scalars().all()

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

        def get_article(self, m, q):
            art_id = int(m.group(1))
            with SessionLocal() as s:
                a = s.get(Article, art_id)
                if not a:
                    raise NotFound("Article not found")
                self._json_ok({
                    "id": a.id,
                    "source_id": a.source_id,
                    "title": a.title,
                    "link": a.link,
                    "description": a.description,
                    "guid": a.guid,
                    "published_at": a.published_at,
                    "fetched_at": a.fetched_at,
                })

        # ---- заглушка ----
        def not_impl(self, m, q):
            raise ApiError("Endpoint will be implemented later", status=501, code="not_implemented")

    httpd = HTTPServer((host, port), Handler)
    print(f"Server listening on {host}:{port}")
    httpd.serve_forever()

def server_init():
    port = int(os.getenv("PORT", "8000"))
    run_server(port=port)