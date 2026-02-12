import asyncio
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from sqlalchemy import select

from src.assistant.tg_parser import _ensure_client
from src.assistant.vk_parser import _vk_call, _sleep_throttle
from src.db.db import SessionLocal
from src.db.models.article import Article
from src.db.models.source import Source
from src.db.social_stats import upsert_article_social_stat


_VK_LINK_RE = re.compile(r"wall(?P<owner>-?\d+)_(?P<post>\d+)")
_VK_GUID_RE = re.compile(r"vk:(?P<owner>-?\d+):(?P<post>\d+)")
_TG_LINK_RE = re.compile(r"https?://(?:t\.me|telegram\.me)/(?P<channel>[^/]+)/(?P<msg_id>\d+)")


def _parse_vk_ids(link: str | None, guid: str | None) -> Optional[tuple[int, int]]:
    for value, regex in ((link or "", _VK_LINK_RE), (guid or "", _VK_GUID_RE)):
        match = regex.search(value)
        if match:
            return int(match.group("owner")), int(match.group("post"))
    return None


def _parse_tg_ids(link: str | None) -> Optional[tuple[str, int]]:
    match = _TG_LINK_RE.search(link or "")
    if not match:
        return None
    return match.group("channel"), int(match.group("msg_id"))


def _vk_counts_from_post(post: dict) -> tuple[int, int, int, int]:
    likes = int((post.get("likes") or {}).get("count") or 0)
    reposts = int((post.get("reposts") or {}).get("count") or 0)
    comments = int((post.get("comments") or {}).get("count") or 0)
    views = int((post.get("views") or {}).get("count") or 0)
    return likes, reposts, comments, views


def _tg_counts_from_msg(msg) -> tuple[int, int, int, int]:
    reactions = 0
    reactions_obj = getattr(msg, "reactions", None)
    if reactions_obj is not None:
        results = getattr(reactions_obj, "results", None) or []
        reactions = sum(int(getattr(r, "count", 0) or 0) for r in results)
    reposts = int(getattr(msg, "forwards", 0) or 0)
    replies = getattr(msg, "replies", None)
    comments = int(getattr(replies, "replies", 0) or 0) if replies is not None else 0
    views = int(getattr(msg, "views", 0) or 0)
    return reactions, reposts, comments, views


def _iter_batches(items: list[tuple[int, int, int]], size: int) -> Iterable[list[tuple[int, int, int]]]:
    for idx in range(0, len(items), size):
        yield items[idx: idx + size]


def _collect_vk_stats(session, logger, items: list[tuple[int, int, int]], collected_at: datetime) -> int:
    processed = 0
    if not items:
        return 0

    for batch in _iter_batches(items, 100):
        posts = [f"{owner_id}_{post_id}" for _, owner_id, post_id in batch]
        key_to_article = {f"{owner_id}_{post_id}": article_id for article_id, owner_id, post_id in batch}
        try:
            response = _vk_call("wall.getById", {"posts": ",".join(posts)})
            _sleep_throttle()
        except Exception as exc:
            logger.write(f"[WARN] VK stats fetch failed: {exc}")
            continue

        for post in response or []:
            key = f"{post.get('owner_id')}_{post.get('id')}"
            article_id = key_to_article.get(key)
            if not article_id:
                continue
            like_count, repost_count, comment_count, view_count = _vk_counts_from_post(post)
            upsert_article_social_stat(
                session,
                article_id,
                like_count,
                repost_count,
                comment_count,
                view_count,
                collected_at,
            )
            processed += 1

    return processed


async def _collect_tg_stats_async(logger, channel_items: Dict[str, Dict[int, int]]) -> Dict[int, tuple[int, int, int, int]]:
    client = await _ensure_client()
    if client is None:
        logger.write("[INFO] TG stats skipped: not authorized")
        return {}

    results: Dict[int, tuple[int, int, int, int]] = {}
    try:
        for channel, msg_map in channel_items.items():
            if not msg_map:
                continue
            msg_ids = list(msg_map.keys())
            messages = await client.get_messages(channel, ids=msg_ids)
            for msg in messages or []:
                if msg is None:
                    continue
                article_id = msg_map.get(getattr(msg, "id", None))
                if not article_id:
                    continue
                results[article_id] = _tg_counts_from_msg(msg)
    finally:
        try:
            await client.disconnect()
            try:
                await asyncio.wait_for(client.disconnected, timeout=2.0)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0)
        except Exception as exc:
            logger.write(f"[WARN] TG stats disconnect cleanup: {exc}")

    return results


def _collect_tg_stats(logger, channel_items: Dict[str, Dict[int, int]]) -> Dict[int, tuple[int, int, int, int]]:
    if not channel_items:
        return {}
    try:
        return asyncio.run(_collect_tg_stats_async(logger, channel_items))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_collect_tg_stats_async(logger, channel_items))


def run_social_stats_cycle(logger) -> int:
    processed = 0
    collected_at = datetime.now(timezone.utc)

    with SessionLocal() as session:
        vk_rows = session.execute(
            select(Article.id, Article.link, Article.guid)
            .join(Source, Source.id == Article.source_id)
            .where(Source.type == "vk")
        ).all()

        vk_items: list[tuple[int, int, int]] = []
        for article_id, link, guid in vk_rows:
            parsed = _parse_vk_ids(link, guid)
            if not parsed:
                continue
            owner_id, post_id = parsed
            vk_items.append((article_id, owner_id, post_id))

        processed += _collect_vk_stats(session, logger, vk_items, collected_at)

        tg_rows = session.execute(
            select(Article.id, Article.link)
            .join(Source, Source.id == Article.source_id)
            .where(Source.type == "tg", Article.parent_article_id.is_(None))
        ).all()

        channel_items: Dict[str, Dict[int, int]] = {}
        for article_id, link in tg_rows:
            parsed = _parse_tg_ids(link)
            if not parsed:
                continue
            channel, msg_id = parsed
            channel_items.setdefault(channel, {})[msg_id] = article_id

        tg_stats = _collect_tg_stats(logger, channel_items)
        for article_id, counts in tg_stats.items():
            like_count, repost_count, comment_count, view_count = counts
            upsert_article_social_stat(
                session,
                article_id,
                like_count,
                repost_count,
                comment_count,
                view_count,
                collected_at,
            )
            processed += 1

        if processed:
            session.commit()

    logger.write(f"[SOCIAL-STATS] updated={processed}")
    return processed
