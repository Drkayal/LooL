import asyncio
import os
import random
import re
import time
import sys
import shutil
from typing import Union, List, Optional, Tuple

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch
from yt_dlp import YoutubeDL

import config
from ZeMusic.utils.database import is_on_off
from ZeMusic.utils.formatters import time_to_seconds, seconds_to_min
from ZeMusic.utils.decorators import asyncify
from ZeMusic.core.cache import (
    get_redis,
    extract_youtube_id,
    get_cached_gurl,
    set_cached_gurl,
    acquire_video_lock,
    release_video_lock,
    is_hard_video,
    set_hard_video,
    record_global_success,
    record_global_failure,
    bump_cookie_leaderboards,
)


# ===== In-memory cache for cookie file discovery (reduce repeated disk I/O) =====
_COOKIE_FILES_CACHE: Tuple[List[str], int] = ([], 0)
_COOKIE_FILES_CACHE_TTL = 300  # 5 minutes


def _cookie_dirs() -> List[str]:
    """Return possible directories that may contain cookie files.
    Priority order: explicit env dir, default 'cookies', and 'strings'.
    """
    dirs: List[str] = []
    env_dir = os.getenv("YT_COOKIES_DIR")
    if env_dir:
        dirs.append(env_dir)
    dirs.append(f"{os.getcwd()}/cookies")
    dirs.append(f"{os.getcwd()}/strings")
    seen = set()
    unique_dirs: List[str] = []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            unique_dirs.append(d)
    return unique_dirs


def _cookie_files() -> List[str]:
    """Collect all candidate cookie files from known dirs and env overrides.

    - Accept files that contain the standard Netscape header.
    - Also accept files that appear to be Netscape TSV cookies (heuristic),
      regardless of extension or name (to support arbitrary filenames like
      'cookies_1.py', 'cookies(2).txt', etc.).
    - Do NOT include obviously invalid files; return an empty list if none valid.
    - If YT_COOKIES_FILE env is set and valid, prioritize it first.
    """
    global _COOKIE_FILES_CACHE
    now = int(time.time())
    # Serve from in-memory cache if fresh
    if _COOKIE_FILES_CACHE[1] and (now - _COOKIE_FILES_CACHE[1] < _COOKIE_FILES_CACHE_TTL):
        return list(_COOKIE_FILES_CACHE[0])

    candidates: List[str] = []
    
    # Priority 1: Environment variable
    env_file = os.getenv("YT_COOKIES_FILE")
    if env_file and os.path.isfile(env_file):
        candidates.append(env_file)
    
    # Priority 2: Known good cookies from strings directory
    priority_cookies = [
        f"{os.getcwd()}/strings/cookies.txt",
        f"{os.getcwd()}/cookies/cookies.txt",
        f"{os.getcwd()}/cookies/cookies_1.txt",
        f"{os.getcwd()}/cookies/cookies(2).txt",
        f"{os.getcwd()}/cookies/cookies(3).txt"
    ]
    
    for cookie_path in priority_cookies:
        if os.path.isfile(cookie_path):
            candidates.append(cookie_path)

    # Priority 3: Scan directories for other cookie files
    for base in _cookie_dirs():
        try:
            for name in os.listdir(base):
                path = os.path.join(base, name)
                if os.path.isfile(path) and path not in candidates:
                    candidates.append(path)
        except FileNotFoundError:
            continue

    def is_netscape_cookie_file(path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                sample = fh.read(4096)
                # Check for Netscape format AND YouTube cookies
                has_netscape_format = "Netscape HTTP Cookie File" in sample
                has_youtube_cookies = ".youtube.com" in sample or "youtube.com" in sample
                
                if has_netscape_format and has_youtube_cookies:
                    return True
                    
                # Fallback: check for TSV format with YouTube cookies
                if has_youtube_cookies:
                    for line in sample.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if len(line.split("\t")) >= 6 and "youtube.com" in line:
                            return True
        except Exception:
            return False
        return False

    valid: List[str] = [p for p in candidates if is_netscape_cookie_file(p)]

    # De-duplicate while preserving order
    seen: set = set()
    filtered: List[str] = []
    for p in valid:
        if p not in seen:
            seen.add(p)
            filtered.append(p)
    _COOKIE_FILES_CACHE = (filtered, now)
    return filtered


def _cookie_basename(path: str) -> str:
    return str(path).split("/")[-1]


def _cookie_key(name: str) -> str:
    return f"ytcookies:file:{name}"


def _cookie_cooldown_key(name: str) -> str:
    return f"ytcookies:cooldown:{name}"


def _cookie_good_key(name: str) -> str:
    return f"ytcookies:good:{name}"


async def get_cookie_candidates() -> List[str]:
    """Return cookie file paths ordered by health/usage (best first).
    Prioritize recently-successful ("good") cookies. Use pipeline for Redis ops.
    Fallback to shuffled list if Redis unavailable.
    """
    files = _cookie_files()
    if not files:
        return []
    r = None
    try:
        r = get_redis()
    except Exception:
        r = None
    if r is None:
        random.shuffle(files)
        return files

    pipe = r.pipeline()
    for path in files:
        name = _cookie_basename(path)
        pipe.ttl(_cookie_cooldown_key(name))
        pipe.hgetall(_cookie_key(name))
        pipe.exists(_cookie_good_key(name))
    try:
        results = await pipe.execute()
    except Exception:
        random.shuffle(files)
        return files

    scored: List[Tuple[int, str]] = []
    for idx, path in enumerate(files):
        try:
            cooling = results[(idx * 3) + 0]
            h = results[(idx * 3) + 1] or {}
            is_good = 1 if results[(idx * 3) + 2] else 0
            usage = int(h.get("usage", 0))
            fail = int(h.get("fail", 0))
            jitter = random.randint(0, 5)
            score = (fail * 1_000_000) + (usage * 10) + jitter
            if cooling and cooling > 0:
                score += 10_000_000
            if is_good:
                score -= 5_000_000
            scored.append((score, path))
        except Exception:
            scored.append((random.randint(0, 1000), path))
    scored.sort(key=lambda x: x[0])
    return [path for _, path in scored]


async def report_cookie_success(cookie_path: str) -> None:
    try:
        r = get_redis()
        name = _cookie_basename(cookie_path)
        await r.hincrby(_cookie_key(name), "usage", 1)
        await r.hset(_cookie_key(name), "ts", str(int(time.time())))
        await r.set(_cookie_good_key(name), "1", ex=600)
    except Exception:
        pass


async def report_cookie_failure(cookie_path: str, cooldown_seconds: int = 1800) -> None:
    try:
        r = get_redis()
        name = _cookie_basename(cookie_path)
        await r.hincrby(_cookie_key(name), "fail", 1)
        await r.hset(_cookie_key(name), "ts", str(int(time.time())))
        await r.set(_cookie_cooldown_key(name), "1", ex=cooldown_seconds)
    except Exception:
        pass


def cookies():
    files = _cookie_files()
    if not files:
        return None
    try:
        choice = random.choice(files)
        for base in _cookie_dirs():
            if choice.startswith(base.rstrip("/")):
                return os.path.relpath(choice, os.getcwd())
        return choice
    except Exception:
        return None


# UA and headers
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)
IOS_SAFARI_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)
MAC_SAFARI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_3) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
)


def _http_headers() -> dict:
    return {
        "User-Agent": ANDROID_UA,
        "Accept-Language": "en-US,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }


def _extractor_args_py() -> dict:
    return {
        "youtubetab": {"skip": ["authcheck"]},
        "youtube": {
            "player_client": ["android_creator", "android", "ios", "tvhtml5", "web_safari", "web"],
            "skip": ["authcheck", "dash", "hls"]
        },
    }


def _extractor_args_cli() -> str:
    return "youtube:player_client=android_creator,android,ios,tvhtml5,web_safari,web:skip=authcheck,dash,hls;youtubetab:skip=authcheck"


def _yt_dlp_base_cmd() -> List[str]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    python_exe = sys.executable or "python3"
    return [python_exe, "-m", "yt_dlp"]


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return True if re.search(self.regex, link) else False

    @asyncify
    def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        # Attempt to extract a stable video_id for caching/locking
        v_id: Optional[str] = None
        try:
            v_id = extract_youtube_id(link)
        except Exception:
            v_id = None
        # Check cached direct url
        if v_id:
            try:
                cached = await get_cached_gurl(v_id)
                if cached:
                    return 1, cached
            except Exception:
                pass
        # Try to acquire short lock to avoid storms
        lock_acquired = True
        if v_id:
            try:
                lock_acquired = await acquire_video_lock(v_id, ttl_seconds=120)
            except Exception:
                lock_acquired = True
        try:
            candidates = await get_cookie_candidates()
        except Exception:
            c = cookies()
            candidates = [c] if c else []
        last_err = None
        UA_POOL = [ANDROID_UA, IOS_SAFARI_UA, MAC_SAFARI_UA]
        extractor_variants = [
            _extractor_args_cli(),
            "youtube:player_client=android;youtubetab:skip=authcheck",
            "youtube:player_client=ios;youtubetab:skip=authcheck",
            "youtube:player_client=web_safari;youtubetab:skip=authcheck",
        ]

        hard = False
        try:
            hard = await is_hard_video(v_id)
        except Exception:
            hard = False
        fmt_order = ("best[height<=?480][width<=?854]",) if hard else (
            "best[height<=?720][width<=?1280]",
            "best[height<=?480][width<=?854]",
        )

        for cookie_path in candidates:
            for extractor_args in extractor_variants:
                if extractor_args.startswith("youtube:player_client=android") and "ios" not in extractor_args:
                    ua = ANDROID_UA
                elif extractor_args.startswith("youtube:player_client=ios"):
                    ua = IOS_SAFARI_UA
                elif extractor_args.startswith("youtube:player_client=web_safari"):
                    ua = MAC_SAFARI_UA
                else:
                    ua = random.choice(UA_POOL)
                for fmt in fmt_order:
                    cmd = [
                        *_yt_dlp_base_cmd(),
                        "-g",
                        "-f",
                        fmt,
                        "--extractor-args", extractor_args,
                        "--user-agent", ua,
                        "--add-header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "--add-header", "Accept-Language: en-US,en;q=0.5",
                        "--force-ipv4",
                        "--geo-bypass",
                        "--geo-bypass-country", "US",
                        "--no-check-certificates",
                        "--retries", "3",
                        "--retry-sleep", "1:5",
                        f"{link}",
                    ]
                    if cookie_path and os.path.exists(cookie_path):
                        cmd[-1:-1] = ["--cookies", cookie_path]
                    start_ts = time.time()
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    latency_ms = int((time.time() - start_ts) * 1000)
                    if stdout:
                        out_url = stdout.decode().split("\n")[0]
                        try:
                            await report_cookie_success(cookie_path)
                        except Exception:
                            pass
                        # cookie success metrics
                        try:
                            r = get_redis()
                            name = _cookie_basename(cookie_path)
                            await r.hset(_cookie_key(name), mapping={
                                "last_latency_ms": str(latency_ms),
                                "last_ok_ts": str(int(time.time())),
                            })
                        except Exception:
                            pass
                        # global metrics
                        try:
                            await record_global_success(latency_ms)
                            await bump_cookie_leaderboards(name, True, latency_ms)
                        except Exception:
                            pass
                        if v_id and out_url:
                            try:
                                await set_cached_gurl(v_id, out_url, ttl_seconds=120)
                            except Exception:
                                pass
                        if v_id and lock_acquired:
                            try:
                                await release_video_lock(v_id)
                            except Exception:
                                pass
                        return 1, out_url
                    else:
                        last_err = (stderr.decode() if stderr else "")
                        cool = 1800
                        err_code = "UNKNOWN"
                        if last_err:
                            lower = last_err.lower()
                            if "sign in to confirm" in lower:
                                cool = 7200
                                err_code = "BOT_DETECTED"
                                try:
                                    await set_hard_video(v_id, ttl_seconds=900)
                                except Exception:
                                    pass
                            elif "429" in lower or "too many requests" in lower:
                                err_code = "RATE_LIMIT"
                        try:
                            await report_cookie_failure(cookie_path, cooldown_seconds=cool)
                        except Exception:
                            pass
                        # cookie failure metrics
                        try:
                            r = get_redis()
                            name = _cookie_basename(cookie_path)
                            await r.hset(_cookie_key(name), mapping={
                                "last_latency_ms": str(latency_ms),
                                "last_err_code": err_code,
                                "last_err_ts": str(int(time.time())),
                            })
                        except Exception:
                            pass
                        # global metrics
                        try:
                            await record_global_failure(latency_ms, err_code)
                            await bump_cookie_leaderboards(name, False, latency_ms)
                        except Exception:
                            pass
                # end fmt loop
            # end strategy loop

        if v_id and lock_acquired:
            try:
                await release_video_lock(v_id)
            except Exception:
                pass
        return 0, (last_err or "yt-dlp failed with all cookies")

    async def playlist(self, link, limit, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]

        try:
            candidates = await get_cookie_candidates()
        except Exception:
            c = cookies()
            candidates = [c] if c else []

        last_output = ""
        for cookie_path in candidates:
            cmd = [
                *_yt_dlp_base_cmd(),
                "-i",
                "--compat-options", "no-youtube-unavailable-videos",
                "--get-id",
                "--flat-playlist",
                "--playlist-end", str(limit),
                "--skip-download",
                "--extractor-args", _extractor_args_cli(),
                "--user-agent", ANDROID_UA,
                "--add-header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "--add-header", "Accept-Language: en-US,en;q=0.5",
                "--force-ipv4",
                "--geo-bypass",
                "--geo-bypass-country", "US",
                "--no-check-certificates",
                "--retries", "3",
                "--retry-sleep", "1:5",
                f"{link}",
            ]
            if cookie_path and os.path.exists(cookie_path):
                cmd[-1:-1] = ["--cookies", cookie_path]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            out = stdout.decode()
            if out.strip():
                try:
                    await report_cookie_success(cookie_path)
                except Exception:
                    pass
                try:
                    return [key for key in out.split("\n") if key]
                except Exception:
                    return []
            else:
                last_output = stderr.decode()
                try:
                    await report_cookie_failure(cookie_path)
                except Exception:
                    pass
                continue
        try:
            return [key for key in last_output.split("\n") if key]
        except Exception:
            return []

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if link.startswith("http://") or link.startswith("https://"):
            return await self._track(link)
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                title = result["title"]
                duration_min = result["duration"]
                vidid = result["id"]
                yturl = result["link"]
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            track_details = {
                "title": title,
                "link": yturl,
                "vidid": vidid,
                "duration_min": duration_min,
                "thumb": thumbnail,
            }
            return track_details, vidid
        except Exception:
            return await self._track(link)

    @asyncify
    def _track(self, q):
        options = {
            "format": "best",
            "noplaylist": True,
            "quiet": True,
            "extract_flat": "in_playlist",
            "http_headers": _http_headers(),
            "extractor_args": _extractor_args_py(),
        }
        c = cookies()
        if c and os.path.exists(c):
            options["cookiefile"] = c
        with YoutubeDL(options) as ydl:
            info_dict = ydl.extract_info(f"ytsearch: {q}", download=False)
            details = info_dict.get("entries")[0]
            info = {
                "title": details["title"],
                "link": details["url"],
                "vidid": details["id"],
                "duration_min": (
                    seconds_to_min(details["duration"]) if details["duration"] != 0 else None
                ),
                "thumb": details["thumbnails"][0]["url"],
            }
            return info, details["id"]

    @asyncify
    def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        ytdl_opts = {
            "quiet": True,
            "http_headers": _http_headers(),
            "extractor_args": _extractor_args_py(),
        }
        c = cookies()
        if c and os.path.exists(c):
            ytdl_opts["cookiefile"] = c

        ydl = YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])  # noqa
                except Exception:
                    continue
                if "dash" not in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except KeyError:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        a = VideosSearch(link, limit=10)
        result = (await a.next()).get("result")
        title = result[query_type]["title"]
        duration_min = result[query_type]["duration"]
        vidid = result[query_type]["id"]
        thumbnail = result[query_type]["thumbnails"][0]["url"].split("?")[0]
        return title, duration_min, thumbnail, vidid

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link
        loop = asyncio.get_running_loop()

        def audio_dl(cookie_path_override: str = None):
            # Try multiple fallback formats
            formats = [
                "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "best[height<=720]/best",
                "worst"
            ]
            
            for format_str in formats:
                try:
                    ydl_optssx = {
                        "format": format_str,
                        "outtmpl": "downloads/%(id)s.%(ext)s",
                        "geo_bypass": True,
                        "nocheckcertificate": True,
                        "quiet": True,
                        "no_warnings": True,
                        "http_headers": _http_headers(),
                        "extractor_args": _extractor_args_py(),
                    }
                    
                    # Try different cookie files
                    cookie_files = _cookie_files()
                    if cookie_path_override:
                        cookie_files.insert(0, cookie_path_override)
                    
                    for c_local in cookie_files:
                        if c_local and os.path.exists(c_local):
                            ydl_optssx["cookiefile"] = c_local
                            break
                    
                    x = YoutubeDL(ydl_optssx)
                    info = x.extract_info(link, False)
                    xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                    if os.path.exists(xyz):
                        return xyz
                    x.download([link])
                    return xyz
                    
                except Exception as e:
                    if "Sign in to confirm" in str(e) and format_str != formats[-1]:
                        continue  # Try next format
                    elif format_str == formats[-1]:
                        raise  # Re-raise on last attempt
            
            return None

        def video_dl():
            # Try multiple video formats as fallback
            formats = [
                "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "best[height<=720]/best[ext=mp4]/best",
                "worst[ext=mp4]/worst"
            ]
            
            for format_str in formats:
                try:
                    ydl_optssx = {
                        "format": format_str,
                        "outtmpl": "downloads/%(id)s.%(ext)s",
                        "geo_bypass": True,
                        "nocheckcertificate": True,
                        "quiet": True,
                        "no_warnings": True,
                        "http_headers": _http_headers(),
                        "extractor_args": _extractor_args_py(),
                    }
                    
                    # Use the best available cookie file
                    cookie_files = _cookie_files()
                    for c_local in cookie_files:
                        if c_local and os.path.exists(c_local):
                            ydl_optssx["cookiefile"] = c_local
                            break

                    x = YoutubeDL(ydl_optssx)
                    info = x.extract_info(link, False)
                    xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                    if os.path.exists(xyz):
                        return xyz
                    x.download([link])
                    return xyz
                    
                except Exception as e:
                    if "Sign in to confirm" in str(e) and format_str != formats[-1]:
                        continue  # Try next format
                    elif format_str == formats[-1]:
                        raise  # Re-raise on last attempt
            
            return None

        def song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            ydl_optssx = {
                "format": formats,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
                "http_headers": _http_headers(),
                "extractor_args": _extractor_args_py(),
            }
            c_local = cookies()
            if c_local and os.path.exists(c_local):
                ydl_optssx["cookiefile"] = c_local

            x = YoutubeDL(ydl_optssx)
            x.download([link])

        def song_audio_dl():
            fpath = f"downloads/{title}.%(ext)s"
            ydl_optssx = {
                "format": format_id,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "http_headers": _http_headers(),
                "extractor_args": _extractor_args_py(),
            }
            c_local = cookies()
            if c_local and os.path.exists(c_local):
                ydl_optssx["cookiefile"] = c_local

            x = YoutubeDL(ydl_optssx)
            x.download([link])

        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = f"downloads/{title}.mp4"
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = f"downloads/{title}.mp3"
            return fpath
        elif video:
            ytdownloader_on = False
            try:
                ytdownloader_on = await is_on_off(getattr(config, "YTDOWNLOADER", 0))
            except Exception:
                ytdownloader_on = False
            if ytdownloader_on:
                direct = True
                downloaded_file = await loop.run_in_executor(None, video_dl)
            else:
                try:
                    candidates = await get_cookie_candidates()
                except Exception:
                    c = cookies()
                    candidates = [c] if c else []
                downloaded_file = None
                last_err = None
                v_id = None
                try:
                    v_id = extract_youtube_id(link)
                except Exception:
                    v_id = None
                if v_id:
                    try:
                        cached = await get_cached_gurl(v_id)
                        if cached:
                            downloaded_file = cached
                            direct = None
                    except Exception:
                        pass
                if not downloaded_file and v_id:
                    try:
                        await acquire_video_lock(v_id, ttl_seconds=120)
                    except Exception:
                        pass
                if not downloaded_file:
                    for cookie_path in candidates:
                        ua = ANDROID_UA
                        for fmt in (
                            "best[height<=?720][width<=?1280]",
                            "best[height<=?480][width<=?854]",
                        ):
                            command = [
                                *_yt_dlp_base_cmd(),
                                "-g",
                                "-f",
                                fmt,
                                "--extractor-args", _extractor_args_cli(),
                                "--user-agent", ua,
                                "--add-header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                                "--add-header", "Accept-Language: en-US,en;q=0.5",
                                "--force-ipv4",
                                "--geo-bypass",
                                "--geo-bypass-country", "US",
                                "--no-check-certificates",
                                "--retries", "3",
                                "--retry-sleep", "1:5",
                                link,
                            ]
                            if cookie_path and os.path.exists(cookie_path):
                                command[-1:-1] = ["--cookies", cookie_path]
                            proc = await asyncio.create_subprocess_exec(
                                *command,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            stdout, stderr = await proc.communicate()
                            if stdout:
                                try:
                                    await report_cookie_success(cookie_path)
                                except Exception:
                                    pass
                                downloaded_file = stdout.decode().split("\n")[0]
                                direct = None
                                break
                            else:
                                last_err = stderr.decode()
                                cool = 1800
                                if last_err and ("sign in to confirm" in last_err.lower()):
                                    cool = 7200
                                try:
                                    await report_cookie_failure(cookie_path, cooldown_seconds=cool)
                                except Exception:
                                    pass
                                continue
                        if downloaded_file:
                            break
                if v_id and downloaded_file:
                    try:
                        await set_cached_gurl(v_id, downloaded_file, ttl_seconds=120)
                    except Exception:
                        pass
                if v_id:
                    try:
                        await release_video_lock(v_id)
                    except Exception:
                        pass
                if not downloaded_file:
                    return
        else:
            direct = True
            downloaded_file = None
            last_err = None
            try:
                candidates = await get_cookie_candidates()
            except Exception:
                c = cookies()
                candidates = [c] if c else []

            for cookie_path in candidates:
                try:
                    downloaded_file = await loop.run_in_executor(None, audio_dl, cookie_path)
                    try:
                        await report_cookie_success(cookie_path)
                    except Exception:
                        pass
                    break
                except Exception as e:
                    last_err = e
                    try:
                        await report_cookie_failure(cookie_path)
                    except Exception:
                        pass
                    continue

            if not downloaded_file:
                downloaded_file = await loop.run_in_executor(None, audio_dl)

        return downloaded_file, direct
