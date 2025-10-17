import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import feedparser
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from src.db.db import SessionLocal
from src.db.models.source import Source
from src.db.models.article import Article

LOG_DIR = os.path.abspath(os.getenv("LOG_DIR", "./log"))
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "10.0"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))

def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def log_path_for_today() -> str:
    return os.path.join(LOG_DIR, datetime.now(timezone.utc).strftime("parser_%Y-%m_%d.log"))

class DailyFileLogger:
    def __init__(self):
        self._path = None
        self._file = None

    def _reopen_if_needed(self):
        path = log_path_for_today()
        if path != self._path:
            if self._file:
                self._file.close()
            self._path = path
            self._file = open(self._path, "a", encoding="utf-8")

    def write(self, line: str):
        self._reopen_if_needed()
        log_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._file.write(f"{log_time} {line.rstrip()}\n")
        self._file.flush()

logger = DailyFileLogger()

def to_dt_utc(entry) -> Optional[datetime]:
    parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed_time:
        return None
    return datetime(*parsed_time[:6], tzinfo=timezone.utc)

def fetch_bytes(url: str) -> bytes:
    headers = {
        "User-Agent": "EditorAssistantBot (+https://localhost)",
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content

def process_source(session, source: Source) -> int:
    added = 0
    try:
        raw = fetch_bytes(source.rss_url)
    except httpx.TimeoutException:
        logger.write(f"[ERROR] Timeout fetching {source.rss_url}")
        return 0
    except httpx.HTTPError as e:
        logger.write(f"[ERROR] HTTP error for {source.rss_url}: {e}")
        return 0
    except Exception as e:
        logger.write(f"[ERROR] Network error for {source.rss_url}: {e}")
        return 0

    parsed = feedparser.parse(raw)

    if parsed.bozo and parsed.bozo_exception:
        logger.write(f"[WARN] Feed parse issue for {source.rss_url}: {parsed.bozo_exception}")

    for entry in parsed.entries:
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        guid = getattr(entry, "id", "") or getattr(entry, "guid", "") or link or title
        description = getattr(entry, "description", "") or ""

        published_at = to_dt_utc(entry)

        if not title or not link or not guid:
            logger.write(f"[WARN] Skip incomplete item from {source.rss_url} (title/link/guid missing)")
            continue

        exists = session.scalar(
            select(Article.id)
            .where(
                (Article.source_id == source.id)
                & (or_(Article.guid == guid, Article.link == link))
            )
            .limit(1)
        )
        if exists:
            continue

        now_utc = datetime.now(timezone.utc)
        article = Article(
            source_id=source.id,
            title=title,
            link=link,
            description=description,
            guid=guid,
            published_at=published_at,
            fetched_at=now_utc,
        )
        try:
            session.add(article)
            added += 1
            session.commit()
            logger.write(f"[ADD] Source={source.name!r} Title={title!r}")
        except IntegrityError:
            session.rollback()
        except Exception as e:
            session.rollback()
            logger.write(f"[ERROR] DB insert failed for source {source.name!r}: {e}")

    return added

def full_cycle():
    ensure_log_dir()
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-START] {start}")

    total_added = 0
    with SessionLocal() as s:
        sources = s.execute(select(Source).where(Source.enabled == True)).scalars().all()
        for src in sources:
            try:
                total_added += process_source(s, src)
            except Exception as e:
                logger.write(f"[ERROR] Unexpected error for source {src.rss_url}: {e}")

    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.write(f"[CYCLE-END] {end} added={total_added}")

def main():
    logger.write("[PARSER] RSS parser started")
    interval = POLL_INTERVAL
    while True:
        full_cycle()
        time.sleep(interval)

if __name__ == "__main__":
    main()