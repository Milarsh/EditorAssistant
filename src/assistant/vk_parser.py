import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

import httpx
from sqlalchemy import select, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.db import SessionLocal
from src.db.models.source import Source
from src.db.models.article import Article

VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.131")
VK_THROTTLE_SEC = float(os.getenv("VK_THROTTLE_SEC", "0.35"))

FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "10.0"))

def _sleep_throttle():
    time.sleep(VK_THROTTLE_SEC)

def _utc_from_timestamp(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

def _vk_call(method, params) -> Dict:
    if not VK_TOKEN:
        raise RuntimeError("VK_TOKEN is not set")
    base = f"https://api.vk.com/method/{method}"
    query_params = {"access_token": VK_TOKEN, "v": VK_API_VERSION, **params}
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
        response = client.get(base, params=query_params)
        response.raise_for_status()
        data = response.json()
    if "error" in data:
        raise RuntimeError(f"VK API error: {data['error']}")
    return data["response"]

_RESOLVE_CACHE: Dict[str, Tuple[str, int]] = {}
_VK_URL_RE = re.compile(r"https?://(?:www\.)?vk\.com/(?P<tail>[^/?#]+)")

def _resolve_screen_name(name: str) -> Tuple[str, int]:
    key = name.lower()
    if key in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[key]
    response = _vk_call("utils.resolveScreenName", {"screen_name": key})
    if not response:
        raise RuntimeError(f"VK: unknown screen_name '{key}'")
    vk_type = response["type"]          # user / group / page
    object_id = int(response["object_id"])
    _RESOLVE_CACHE[key] = (vk_type, object_id)
    _sleep_throttle()
    return vk_type, object_id

def owner_id_from_url(url: str) -> int:
    match = _VK_URL_RE.match(url)
    if not match:
        raise RuntimeError(f"Not a VK url: {url}")
    tail = match.group("tail")
    if tail.startswith(("club", "public")) and tail[5:].isdigit():
        return -int(tail[5:])
    vk_type, object_id = _resolve_screen_name(tail)
    if vk_type not in ("group", "page"):
        raise RuntimeError(f"Unsupported VK type '{vk_type}' for '{url}'")
    return -object_id

def is_vk_source(src: Source) -> bool:
    return bool(src.enabled and src.rss_url and "vk.com" in src.rss_url)


def fetch_wall(owner_id: int, count: int = 100) -> list[dict]:
    response = _vk_call("wall.get", {"owner_id": owner_id, "count": count, "filter": "owner"})
    _sleep_throttle()
    return response.get("items", [])

def process_vk_source(session, source, logger) -> int:
    try:
        owner_id = owner_id_from_url(source.rss_url)
    except Exception as exception:
        logger.write(f"[ERROR] VK resolve failed for {source.rss_url}: {exception}")
        return 0

    try:
        posts = fetch_wall(owner_id, count=100)
    except Exception as exception:
        logger.write(f"[ERROR] VK API for {source.rss_url}: {exception}")
        return 0

    added = 0
    for post in posts:
        post_id = post.get("id")
        text = (post.get("text") or "").strip()
        if not post_id:
            continue

        link = f"https://vk.com/wall{owner_id}_{post_id}"
        guid = f"vk:{owner_id}:{post_id}"
        title = (text[:120] + "…") if len(text) > 120 else (text or link)
        description = text or None
        published_at = _utc_from_timestamp(int(post["date"])) if "date" in post else None
        now_utc = datetime.now(timezone.utc)

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
                fetched_at=now_utc,
            )
            .on_conflict_do_nothing(index_elements=["source_id", "guid"])
        )
        res = session.execute(stmt)
        if res.rowcount:
            added += 1
            logger.write(f"[ADD] VK Source={source.name!r} Title={title!r}")

    if added:
        session.commit()
    return added

def run_vk_cycle(logger) -> int:
    total_added = 0
    with SessionLocal() as session:
        sources = session.execute(select(Source).where(Source.enabled == True)).scalars().all()
        for source in sources:
            if not is_vk_source(source):
                continue
            try:
                total_added += process_vk_source(session, source, logger)
            except Exception as e:
                logger.write(f"[ERROR] VK unexpected for {source.rss_url}: {e}")
    return total_added