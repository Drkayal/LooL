import asyncio
import glob
import os
import random
import re
import time
import sys
import shutil
from typing import Union, List

from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch
from yt_dlp import YoutubeDL

import config
from ZeMusic.utils.database import is_on_off
from ZeMusic.utils.formatters import time_to_seconds, seconds_to_min
from ZeMusic.utils.decorators import asyncify
from ZeMusic.core.cache import get_redis


def _cookies_folder() -> str:
    return f"{os.getcwd()}/cookies"


def _cookie_files() -> List[str]:
    folder_path = _cookies_folder()
    try:
        entries = [os.path.join(folder_path, name) for name in os.listdir(folder_path)]
        files = [p for p in entries if os.path.isfile(p)]
    except FileNotFoundError:
        files = []
    # Prefer Netscape-format cookie files; fall back to any files if none detected
    valid = []
    for p in files:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read(2048)
                if "Netscape HTTP Cookie File" in head:
                    valid.append(p)
        except Exception:
            continue
    return valid or files


def _cookie_basename(path: str) -> str:
    return str(path).split("/")[-1]


def _cookie_key(name: str) -> str:
    return f"ytcookies:file:{name}"


def _cookie_cooldown_key(name: str) -> str:
    return f"ytcookies:cooldown:{name}"


async def get_cookie_candidates() -> List[str]:
    """Return cookie file paths ordered by health/usage (best first). Fallback to shuffled list if Redis unavailable."""
    files = _cookie_files()
    if not files:
        raise FileNotFoundError("No cookie files found in the cookies folder.")
    r = None
    try:
        r = get_redis()
    except Exception:
        r = None
    if r is None:
        random.shuffle(files)
        return [f"cookies/{_cookie_basename(p)}" for p in files]

    now = int(time.time())
    scored = []
    for path in files:
        name = _cookie_basename(path)
        try:
            cooling = await r.ttl(_cookie_cooldown_key(name))
            h = await r.hgetall(_cookie_key(name)) or {}
            usage = int(h.get("usage", 0))
            fail = int(h.get("fail", 0))
            # Lower score is better. Penalize failures heavily; spread by usage; slight randomness to avoid ties
            jitter = random.randint(0, 5)
            score = (fail * 1000000) + (usage * 10) + (jitter)
            if cooling and cooling > 0:
                score += 10_000_000
            scored.append((score, name))
        except Exception:
            scored.append((random.randint(0, 1000), name))
    scored.sort(key=lambda x: x[0])
    return [f"cookies/{name}" for _, name in scored]


async def report_cookie_success(cookie_path: str) -> None:
    """Increase usage counter and refresh ts for a cookie file."""
    try:
        r = get_redis()
        name = _cookie_basename(cookie_path)
        await r.hincrby(_cookie_key(name), "usage", 1)
        await r.hset(_cookie_key(name), "ts", str(int(time.time())))
    except Exception:
        pass


async def report_cookie_failure(cookie_path: str, cooldown_seconds: int = 1800) -> None:
    """Increase failure counter and set a temporary cooldown to deprioritize the cookie."""
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
        raise FileNotFoundError("No cookie files found in the specified folder.")
    # Prefer best candidate if possible (non-blocking)
    # Fallback to random choice on any error
    try:
        # This function is sync; we pick from current list randomly to keep backward compatibility
        # Rotation and health are handled by get_cookie_candidates for advanced callers
        return f"cookies/{_cookie_basename(random.choice(files))}"
    except Exception:
        return f"cookies/{_cookie_basename(random.choice(files))}"


# Common headers and extractor args to mitigate HTTP 429 and reduce auth checks
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


def _http_headers() -> dict:
    return {"User-Agent": ANDROID_UA, "Accept-Language": "en-US,en;q=0.5"}


def _extractor_args_py() -> dict:
    return {
        "youtubetab": {"skip": ["authcheck"]},
        "youtube": {"player_client": ["android"]},
    }


def _extractor_args_cli() -> str:
    return "youtube:player_client=android;youtubetab:skip=authcheck"


def _yt_dlp_base_cmd() -> List[str]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    python_exe = sys.executable or "python3"
    return [python_exe, "-m", "yt_dlp"]


async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

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
        try:
            candidates = await get_cookie_candidates()
        except Exception:
            candidates = [cookies()]
        last_err = None
        for cookie_path in candidates:
            cmd = [
                *_yt_dlp_base_cmd(),
                "-g",
                "-f",
                "best[height<=?720][width<=?1280]",
                "--cookies", cookie_path,
                "--extractor-args", _extractor_args_cli(),
                "--user-agent", ANDROID_UA,
                "--force-ipv4",
                "--geo-bypass",
                "--geo-bypass-country", "US",
                "--no-check-certificates",
                "--retries", "3",
                "--retry-sleep", "1:5",
                f"{link}",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if stdout:
                try:
                    await report_cookie_success(cookie_path)
                except Exception:
                    pass
                return 1, stdout.decode().split("\n")[0]
            else:
                last_err = stderr.decode()
                try:
                    await report_cookie_failure(cookie_path)
                except Exception:
                    pass
                continue
        return 0, (last_err or "yt-dlp failed with all cookies")

    async def playlist(self, link, limit, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]

        try:
            candidates = await get_cookie_candidates()
        except Exception:
            candidates = [cookies()]

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
                "--cookies", cookie_path,
                "--user-agent", ANDROID_UA,
                "--force-ipv4",
                "--geo-bypass",
                "--geo-bypass-country", "US",
                "--no-check-certificates",
                "--retries", "3",
                "--retry-sleep", "1:5",
                f"{link}",
            ]
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
            "cookiefile": f"{cookies()}",
            "http_headers": _http_headers(),
            "extractor_args": _extractor_args_py(),
        }
        with YoutubeDL(options) as ydl:
            info_dict = ydl.extract_info(f"ytsearch: {q}", download=False)
            details = info_dict.get("entries")[0]
            info = {
                "title": details["title"],
                "link": details["url"],
                "vidid": details["id"],
                "duration_min": (
                    seconds_to_min(details["duration"])
                    if details["duration"] != 0
                    else None
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
            "cookiefile": f"{cookies()}",
            "http_headers": _http_headers(),
            "extractor_args": _extractor_args_py(),
        }

        ydl = YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
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
            ydl_optssx = {
                "format": "bestaudio/best",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                # Prefer an explicit cookie file if provided (for rotation),
                # otherwise fall back to a random cookie file.
                "cookiefile": cookie_path_override or f"{cookies()}",
                "http_headers": _http_headers(),
                "extractor_args": _extractor_args_py(),
            }

            x = YoutubeDL(ydl_optssx)
            info = x.extract_info(link, False)
            xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

        def video_dl():
            ydl_optssx = {
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "cookiefile": f"{cookies()}",
                "http_headers": _http_headers(),
                "extractor_args": _extractor_args_py(),
            }

            x = YoutubeDL(ydl_optssx)
            info = x.extract_info(link, False)
            xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(xyz):
                return xyz
            x.download([link])
            return xyz

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
                "cookiefile": f"{cookies()}",
                "http_headers": _http_headers(),
                "extractor_args": _extractor_args_py(),
            }

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
                "cookiefile": f"{cookies()}",
                "http_headers": _http_headers(),
                "extractor_args": _extractor_args_py(),
            }

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
            # Safely check optional toggle without crashing if missing in config
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
                    candidates = [cookies()]
                downloaded_file = None
                last_err = None
                for cookie_path in candidates:
                    command = [
                        *_yt_dlp_base_cmd(),
                        "-g",
                        "-f",
                        "best[height<=?720][width<=?1280]",
                        "--cookies", cookie_path,
                        "--extractor-args", _extractor_args_cli(),
                        "--user-agent", ANDROID_UA,
                        "--force-ipv4",
                        "--geo-bypass",
                        "--geo-bypass-country", "US",
                        "--no-check-certificates",
                        "--retries", "3",
                        "--retry-sleep", "1:5",
                        link,
                    ]
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
                        try:
                            await report_cookie_failure(cookie_path)
                        except Exception:
                            pass
                        continue
                if not downloaded_file:
                    return
        else:
            # Audio-only: rotate cookies like the search/download commands do,
            # instead of relying on a single random cookie file. This
            # dramatically reduces failures that manifest as play_14.
            direct = True
            downloaded_file = None
            last_err = None
            try:
                candidates = await get_cookie_candidates()
            except Exception:
                candidates = [cookies()]

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

            # Final fallback: try once without forcing a specific cookie (random file)
            if not downloaded_file:
                downloaded_file = await loop.run_in_executor(None, audio_dl)

        return downloaded_file, direct
