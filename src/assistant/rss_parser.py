import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import feedparser
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from src.db.db import SessionLocal
from src.db.models.source import Source
from src.db.models.article import Article

FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "10.0"))

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

def process_source(session, source, logger) -> int:
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

def run_rss_cycle(logger) -> int:
    total_added = 0
    with SessionLocal() as session:
        sources = session.execute(select(Source).where(Source.enabled == True)).scalars().all()
        for source in sources:
            if source.type != "rss" or not source.enabled:
                continue
            try:
                total_added += process_source(session, source, logger)
            except Exception as e:
                logger.write(f"[ERROR] Unexpected error for source {source.rss_url}: {e}")

    return total_added