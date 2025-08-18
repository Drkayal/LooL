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


# ===== Direct URL (-g) cache and per-video locks =====

def _kgurl(video_id: str) -> str:
    return _k("gurl", video_id)


def _kvidlock(video_id: str) -> str:
    return _k("vidlock", video_id)


async def get_cached_gurl(video_id: Optional[str]) -> Optional[str]:
    if not video_id:
        return None
    r = get_redis()
    try:
        url = await r.get(_kgurl(video_id))
        return url
    except Exception:
        return None


async def set_cached_gurl(video_id: Optional[str], url: Optional[str], ttl_seconds: int = 120) -> None:
    if not video_id or not url:
        return
    r = get_redis()
    try:
        await r.set(_kgurl(video_id), url, ex=ttl_seconds)
    except Exception:
        pass


async def acquire_video_lock(video_id: Optional[str], ttl_seconds: int = 120) -> bool:
    if not video_id:
        return True
    r = get_redis()
    try:
        ok = await r.set(_kvidlock(video_id), "1", ex=ttl_seconds, nx=True)
        return ok is True
    except Exception:
        return True


async def release_video_lock(video_id: Optional[str]) -> None:
    if not video_id:
        return
    r = get_redis()
    try:
        await r.delete(_kvidlock(video_id))
    except Exception:
        pass


# ===== Hard video flag (to reduce blind retries for difficult videos) =====

def _khard(video_id: str) -> str:
    return _k("hard", video_id)


async def is_hard_video(video_id: Optional[str]) -> bool:
    if not video_id:
        return False
    r = get_redis()
    try:
        return bool(await r.exists(_khard(video_id)))
    except Exception:
        return False


async def set_hard_video(video_id: Optional[str], ttl_seconds: int = 900) -> None:
    if not video_id:
        return
    r = get_redis()
    try:
        await r.set(_khard(video_id), "1", ex=ttl_seconds)
    except Exception:
        pass


# ===== Global monitoring counters (totals) and per-cookie leaderboards =====

def _kmetrics(field: str) -> str:
    return _k("metrics", field)


def _zcookie(field: str) -> str:
    # sorted sets for cookie-based leaderboards
    return _k("cookies:z", field)


async def record_global_success(latency_ms: int) -> None:
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(_kmetrics("total"), 1)
        pipe.incr(_kmetrics("success"), 1)
        pipe.incrby(_kmetrics("latency_ms_sum"), int(latency_ms))
        pipe.set(_kmetrics("last_ts"), str(int(time.time())))
        await pipe.execute()
    except Exception:
        pass


async def record_global_failure(latency_ms: int, err_code: str = "") -> None:
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(_kmetrics("total"), 1)
        pipe.incr(_kmetrics("fail"), 1)
        pipe.incrby(_kmetrics("latency_ms_sum"), int(latency_ms))
        if err_code:
            pipe.incr(_kmetrics(f"err:{err_code}"), 1)
        pipe.set(_kmetrics("last_ts"), str(int(time.time())))
        await pipe.execute()
    except Exception:
        pass


async def bump_cookie_leaderboards(cookie_basename: str, success: bool, latency_ms: int) -> None:
    try:
        r = get_redis()
        if success:
            await r.zincrby(_zcookie("succ"), 1, cookie_basename)
        else:
            await r.zincrby(_zcookie("fail"), 1, cookie_basename)
        await r.zincrby(_zcookie("latency_sum"), int(latency_ms), cookie_basename)
    except Exception:
        pass