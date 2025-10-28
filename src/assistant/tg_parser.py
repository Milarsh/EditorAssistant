import os
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.db import SessionLocal
from src.db.models.source import Source
from src.db.models.article import Article

from pathlib import Path
import json
import sqlite3

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import Message

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_FILE = "./secrets/" + os.getenv("TG_SESSION", "telegram.session")
TG_FETCH_LIMIT = int(os.getenv("TG_FETCH_LIMIT", "100"))
TG_SLEEP_ON_FLOOD = int(os.getenv("TG_SLEEP_ON_FLOOD", "60"))
MEDIA_DIR = "./media"

def _channel_from_url(url: str) -> Optional[str]:
    url = (url or "").strip()
    for prefix in ("https://t.me/", "http://t.me/", "https://telegram.me/", "http://telegram.me/"):
        if url.startswith(prefix):
            tail = url[len(prefix):]
            return tail.split("/", 1)[0] 
    if url.startswith("tg://resolve?domain="):
        return url.split("=", 1)[1].split("&", 1)[0]
    return None

def _msg_to_article_fields(msg: Message, channel: str):
    text = (msg.message or "").strip()
    title = (text[:120] + "…") if len(text) > 120 else (text or f"https://t.me/{channel}/{msg.id}")
    description = text or None
    link = f"https://t.me/{channel}/{msg.id}"
    published_at = msg.date.astimezone(timezone.utc) if msg.date else None
    fetched_at = datetime.now(timezone.utc)
    guid = f"tg:{channel}:{msg.id}"
    return title, description, link, guid, published_at, fetched_at

async def _ensure_client():
    if not API_ID or not API_HASH:
        raise RuntimeError("API_ID/API_HASH are not set")
    Path(os.path.dirname(SESSION_FILE)).mkdir(parents=True, exist_ok=True)

    retries = 10
    backoff = 1

    last_error = None
    for i in range(retries):
        try:
            client = TelegramClient(SESSION_FILE, API_ID, API_HASH, device_model="EditorAssistantHost",
                                    system_version="1.0.0", app_version="1.0.0", system_lang_code="ru-RU",
                                    lang_code="ru")
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return None
            return client
        except sqlite3.OperationalError as error:
            msg = str(error).lower()
            if "database is locked" in msg:
                delay = backoff *  i
                await asyncio.sleep(delay)
                last_error = error
                continue
            raise
        except Exception as exception:
            last_error = exception
            break
    if last_error:
        raise last_error

def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def _save_manifest(dir_path: Path, entries: list[dict]):
    try:
        (dir_path / "media.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2),encoding="utf-8")
    except Exception:
        pass

async def download_tg_media_for_message(client: TelegramClient, msg: Message, channel: str) -> list[str]:
    dest_dir = Path(MEDIA_DIR) / "tg" / channel / str(msg.id)
    _ensure_dir(dest_dir)

    rel_urls: list[str] = []
    manifest: list[dict] = []

    try:
        if msg.media:
            try:
                doc = getattr(msg, "document", None)
                await client.download_media(msg, file=str(dest_dir))
            except Exception as exception:
                pass
    except Exception:
        pass

    for path in sorted(dest_dir.iterdir()) if dest_dir.exists() else []:
        if not path.is_file():
            continue
        if path.name == "media.json":
            continue
        rel = path.relative_to(Path(MEDIA_DIR)).as_posix()
        rel_urls.append(f"/media/{rel}")

        ext = path.suffix.lower()
        type = "image" if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else (
            "video" if ext in {".mp4", ".mov", ".mkv", ".webm"} else "file"
        )
        manifest.append({"type": type, "file": path.name})
    _save_manifest(dest_dir, manifest)
    return rel_urls


async def _process_tg_source(client: TelegramClient, source: Source, logger) -> int:
    channel = _channel_from_url(source.rss_url or "")
    if not channel:
        logger.write(f"[ERROR] TG invalid URL: {source.rss_url}")
        return 0

    window_sec = 10
    added = 0

    def is_child(msg: Message, title: str, description: Optional[str]) -> bool:
        has_text = bool((msg.message or "").strip())
        has_media = bool(getattr(msg, "media", None))
        return (not has_text) and has_media and (description is None) and (title == f"https://t.me/{channel}/{msg.id}")

    def find_parent_by_time(session, source_id: int, time) -> Optional[int]:
        t0 = time - timedelta(seconds=window_sec)
        t1 = time + timedelta(seconds=window_sec)
        rows = session.execute(
            select(Article.id, Article.published_at)
            .where(
                Article.source_id == source_id,
                Article.parent_article_id.is_(None),
                Article.description.is_not(None),
                Article.published_at >= t0,
                Article.published_at <= t1,
            )
        ).all()
        if not rows:
            return None
        parent_id, _ = min(
            rows,
            key=lambda r: abs((r.published_at or time) - time)
        )
        return parent_id

    def attach_children(session, parent_id: int, children_ids: list[int]) -> int:
        if not children_ids:
            return 0
        res = session.execute(
            update(Article)
            .where(
                Article.id.in_(children_ids),
                Article.parent_article_id.is_(None)
            )
            .values(parent_article_id=parent_id)
        )
        session.commit()
        return res.rowcount or 0

    try:
        async for msg in client.iter_messages(channel, limit=TG_FETCH_LIMIT):
            if not isinstance(msg, Message):
                continue

            title, description, link, guid, published_at, fetched_at = _msg_to_article_fields(msg, channel)
            has_text = bool((msg.message or "").strip())
            is_child_var = is_child(msg, title, description)

            with SessionLocal() as session:
                exists = session.scalar(
                    select(Article.id)
                    .where(
                        (Article.source_id == source.id) &
                        (or_(Article.guid == guid, Article.link == link))
                    )
                    .limit(1)
                )
                if exists:
                    continue

                stmt = (
                    pg_insert(Article)
                    .values(
                        source_id=source.id,
                        title=title,
                        link=link,
                        description=description,
                        guid=guid,
                        published_at=published_at,
                        fetched_at=fetched_at,
                    )
                    .returning(Article.id)
                    .on_conflict_do_nothing(index_elements=["source_id", "guid"])
                )
                new_id = session.scalar(stmt)
                if not new_id:
                    session.rollback()
                    continue

                parent_id: Optional[int] = None

                if has_text:
                    parent_id = new_id
                    t0 = published_at - timedelta(seconds=window_sec)
                    t1 = published_at + timedelta(seconds=window_sec)
                    orphan_ids = session.scalars(
                        select(Article.id)
                        .where(
                            Article.source_id == source.id,
                            Article.parent_article_id.is_(None),
                            Article.description.is_(None),
                            Article.title == Article.link,
                            Article.published_at >= t0,
                            Article.published_at <= t1,
                        )
                    ).all()
                    if orphan_ids:
                        updated = attach_children(session, parent_id, orphan_ids)
                        if updated:
                            logger.write(f"[LINK] TG time attached {updated} children to parent {parent_id}")
                elif is_child_var:
                    if parent_id is None:
                        parent_id = find_parent_by_time(session, source.id, published_at)
                    if parent_id:
                        updated = attach_children(session, parent_id, [new_id])
                        if updated:
                            logger.write(f"[LINK] TG set parent {parent_id} for child {new_id}")

                session.commit()
                added += 1
                logger.write(f"[ADD] TG Source={source.name!r} Title={title!r}")

                try:
                    await download_tg_media_for_message(client, msg, channel)
                except Exception as exception:
                    logger.write(f"[WARN] TG media download failed for {channel}/{msg.id}: {exception}")

    except FloodWaitError as error:
        wait_s = int(getattr(error, "seconds", TG_SLEEP_ON_FLOOD) or TG_SLEEP_ON_FLOOD)
        logger.write(f"[WARN] TG FloodWait {wait_s}s for {channel}")
        await asyncio.sleep(wait_s)
    except RPCError as error:
        logger.write(f"[ERROR] TG RPC for {channel}: {error}")
    except Exception as error:
        logger.write(f"[ERROR] TG unexpected for {channel}: {error}")

    return added

async def _run_tg_cycle_async(logger) -> int:
    client = await _ensure_client()
    if client is None:
        logger.write("[INFO] TG parser skipped: not authorized")
        return 0
    total = 0
    try:
        with SessionLocal() as session:
            sources = session.execute(select(Source).where(Source.enabled == True)).scalars().all()
        for source in sources:
            if source.type != "tg" or not source.enabled:
                continue
            total += await _process_tg_source(client, source, logger)
    finally:
        try:
            await client.disconnect()
            try:
                await asyncio.wait_for(client.disconnected, timeout=2.0)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0)
        except Exception as exception:
            logger.write(f"[WARN] TG disconnect cleanup: {exception}")
    return total

def run_tg_cycle(logger) -> int:
    try:
        return asyncio.run(_run_tg_cycle_async(logger))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_tg_cycle_async(logger))
