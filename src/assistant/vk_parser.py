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

from pathlib import Path
import json

MEDIA_DIR = "./media"

VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.131")
VK_THROTTLE_SEC = float(os.getenv("VK_THROTTLE_SEC", "0.35"))

FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "10.0"))

def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def _best_photo_url(photo: dict) -> str | None:
    sizes = photo.get("sizes") or []
    best = None
    best_width = -1
    for size in sizes:
        width = int(size.get("width") or 0)
        if width > best_width and size.get("url"):
            best_width = width
            best = size["url"]
    return best

def _best_image_url(images: list[dict]) -> str | None:
    best = None
    best_width = -1
    for image in images or []:
        width = int(image.get("width") or 0)
        if image.get("url") and width > best_width:
            best_width = width
            best = image["url"]
    return best


def _download_file(client: httpx.Client, url: str, dest: Path) -> bool:
    try:
        response = client.get(url, timeout=FETCH_TIMEOUT)
        response.raise_for_status()
        dest.write_bytes(response.content)
        return True
    except Exception:
        return False
    
def _save_manifest(dir_path: Path, entries: list[dict]):
    try:
        (dir_path / "media.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def download_vk_media_for_post(post: dict, owner_id: int, client: httpx.Client) -> list[str]:
    post_id = post.get("id")
    if not post_id:
        return []
    
    dest_dir = Path(MEDIA_DIR) / "vk" / str(owner_id) / str(post_id)
    _ensure_dir(dest_dir)

    rel_urls: list[str] = []
    manifest: list[dict] = []

    attachments = post.get("attachments") or []
    photo_index = 0
    doc_index = 0

    for attachment in attachments:
        type = attachment.get("type")
        obj = attachment.get(type) or {}
        if type == "photo":
            url = _best_photo_url(obj)
            if not url:
                continue
            photo_index += 1
            file_name = f"photo_{photo_index}.jpg"
            if _download_file(client, url, dest_dir / file_name):
                rel = Path("vk") / str(owner_id) / str(post_id) / file_name
                rel_urls.append(f"/media/{rel.as_posix()}")
                manifest.append({"type": "photo", "file": file_name, "src": url})
        elif type == "doc":
            file_url = obj.get("url")
            ext = (obj.get("ext") or "bin").split("?")[0][:8]
            doc_index += 1
            file_name = f"doc_{doc_index}.{ext}"
            if file_url and _download_file(client, file_url, dest_dir / file_name):
                rel = Path("vk") / str(owner_id) / str(post_id) / file_name
                rel_urls.append(f"/media/{rel.as_posix()}")
                manifest.append({"type": "doc", "file": file_name, "src": file_url})
        elif type == "video":
            owner = obj.get("owner_id")
            video = obj.get("id")
            if owner is not None and video is not None:
                page_url = f"https://vk.com/video{owner}_{video}"
                embed_url = f"https://vk.com/video_ext.php?oid={owner}&id={video}&hd=2"
                poster_local = None
                poster_url = None
                if isinstance(obj.get("image"), list) and obj["image"]:
                    poster_url = _best_image_url(obj["image"])
                elif isinstance(obj.get("first_frame"), list) and obj["first_frame"]:
                    poster_url = _best_image_url(obj["first_frame"])
                if poster_url:
                    file_name = "video_poster.jpg"
                    if _download_file(client, poster_url, dest_dir / file_name):
                        rel = Path("vk") / str(owner_id) / str(post_id) / file_name
                        poster_local = f"/media/{rel.as_posix()}"
                manifest.append({
                    "type": "video", 
                    "page_url": page_url,
                    "embed_url": embed_url,
                    "poster": poster_local or poster_url,
                    "owner_id": owner,
                    "video_id": video,
                    })

    _save_manifest(dest_dir, manifest)
    return rel_urls

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
            try:
                with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
                    download_vk_media_for_post(post, owner_id, client)
            except Exception as exception:
                logger.write(f"[WARN] VK media download failed for post {owner_id}_{post_id}: {exception}")

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