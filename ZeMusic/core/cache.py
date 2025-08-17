import asyncio
import re
import time
import unicodedata
from typing import Optional, Dict, Any

from redis.asyncio import Redis

import config

_redis_instance: Optional[Redis] = None


def _make_redis() -> Redis:
    return Redis.from_url(
        url=config.REDIS_URL,
        password=config.REDIS_PASSWORD,
        encoding="utf-8",
        decode_responses=True,
    )


def get_redis() -> Redis:
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = _make_redis()
    return _redis_instance


def normalize_query(text: str) -> str:
    if not text:
        return ""
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)
    # Basic Arabic normalization (optional light)
    table = str.maketrans({
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
    })
    s = s.translate(table)
    # Remove diacritics
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s


_youtube_regex = re.compile(r"(?:v=|youtu\.be/|youtube\.com/watch\?v=)([\w-]{6,})", re.I)


def extract_youtube_id(text: str) -> Optional[str]:
    if not text:
        return None
    m = _youtube_regex.search(text)
    if m:
        return m.group(1)
    return None


def _k(prefix: str, suffix: str) -> str:
    return f"music:v{config.CACHE_SCHEMA_VERSION}:{prefix}:{suffix}"


async def get_cached_by_query(q: str) -> Optional[Dict[str, Any]]:
    r = get_redis()
    qn = normalize_query(q)
    if not qn:
        return None
    # map q -> id if available
    v_id = await r.get(_k("q2id", qn))
    if v_id:
        data = await r.hgetall(_k("id", v_id))
        if data:
            # refresh TTL
            await r.expire(_k("id", v_id), config.CACHE_TTL_SECONDS)
            await r.expire(_k("q2id", qn), config.CACHE_TTL_SECONDS)
            return data
    # or direct q hash
    data = await r.hgetall(_k("q", qn))
    if data:
        await r.expire(_k("q", qn), config.CACHE_TTL_SECONDS)
        return data
    return None


async def get_cached_by_video_id(video_id: str) -> Optional[Dict[str, Any]]:
    if not video_id:
        return None
    r = get_redis()
    data = await r.hgetall(_k("id", video_id))
    if data:
        await r.expire(_k("id", video_id), config.CACHE_TTL_SECONDS)
        return data
    return None


async def set_cache_from_message(q: str, meta: Dict[str, Any]) -> None:
    r = get_redis()
    now = int(time.time())
    qn = normalize_query(q)
    payload = {
        "file_id": meta.get("file_id", ""),
        "title": meta.get("title", ""),
        "duration": str(meta.get("duration", "")),
        "performer": meta.get("performer", ""),
        "video_id": meta.get("video_id", ""),
        "source": meta.get("source", "youtube"),
        "usage": str(1),
        "ts": str(now),
    }
    pipe = r.pipeline()
    if qn:
        pipe.hset(_k("q", qn), mapping=payload)
        pipe.expire(_k("q", qn), config.CACHE_TTL_SECONDS)
    v_id = payload.get("video_id")
    if v_id:
        pipe.hset(_k("id", v_id), mapping=payload)
        pipe.expire(_k("id", v_id), config.CACHE_TTL_SECONDS)
        if qn:
            pipe.set(_k("q2id", qn), v_id, ex=config.CACHE_TTL_SECONDS)
            pipe.sadd(_k("aliases", v_id), qn)
            pipe.expire(_k("aliases", v_id), config.CACHE_TTL_SECONDS)
    await pipe.execute()


async def bump_usage(q: Optional[str], video_id: Optional[str]) -> None:
    r = get_redis()
    now = int(time.time())
    pipe = r.pipeline()
    if video_id:
        pipe.hincrby(_k("id", video_id), "usage", 1)
        pipe.hset(_k("id", video_id), "ts", str(now))
        pipe.expire(_k("id", video_id), config.CACHE_TTL_SECONDS)
    if q:
        qn = normalize_query(q)
        if qn:
            pipe.hincrby(_k("q", qn), "usage", 1)
            pipe.hset(_k("q", qn), "ts", str(now))
            pipe.expire(_k("q", qn), config.CACHE_TTL_SECONDS)
    await pipe.execute()


async def acquire_lock(q: str, ttl: int = 60) -> bool:
    r = get_redis()
    qn = normalize_query(q)
    if not qn:
        return True
    return await r.set(_k("lock", qn), "1", ex=ttl, nx=True) is True


async def release_lock(q: str) -> None:
    r = get_redis()
    qn = normalize_query(q)
    if not qn:
        return
    try:
        await r.delete(_k("lock", qn))
    except Exception:
        pass