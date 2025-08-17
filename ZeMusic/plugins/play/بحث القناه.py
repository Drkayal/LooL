import os
import re
import config
import aiohttp
import aiofiles
from ZeMusic.platforms.Youtube import cookies, get_cookie_candidates, report_cookie_success, report_cookie_failure
import yt_dlp
from yt_dlp import YoutubeDL
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from youtube_search import YoutubeSearch
from ZeMusic import app
from ZeMusic.plugins.play.filters import command
from ZeMusic.core.cache import (
    normalize_query,
    extract_youtube_id,
    get_cached_by_query,
    get_cached_by_video_id,
    set_cache_from_message,
    acquire_lock,
    release_lock,
    bump_usage,
)


def remove_if_exists(path):
    if os.path.exists(path):
        os.remove(path)

channel = "KHAYAL70"
lnk = f"https://t.me/{config.CHANNEL_LINK}"
Nem = config.BOT_NAME + " ابحث"

@app.on_message(command(["song", "/song", "بحث", Nem,"يوت"]) & filters.channel)
async def song_downloader3(client, message: Message):
    query = " ".join(message.command[1:]).strip()
    if not query:
        return await message.reply_text("- يرجى كتابة اسم المقطع بعد الأمر.")

    # Try cache first
    qnorm = normalize_query(query)
    vid = extract_youtube_id(query)
    cached = None
    try:
        if vid:
            cached = await get_cached_by_video_id(vid)
        if not cached:
            cached = await get_cached_by_query(qnorm)
    except Exception:
        cached = None

    if cached and cached.get("file_id"):
        try:
            await message.reply_audio(
                audio=cached["file_id"],
                caption=f"ᴍʏ ᴡᴏʀʟᴅ 𓏺 @{channel} ",
                title=cached.get("title") or None,
                performer=cached.get("performer") or None,
                duration=int(cached.get("duration") or 0) or None,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(text="♪ 𝐋𝐚𝐫𝐢𝐧 ♪", url=lnk),
                        ],
                    ]
                ),
            )
            await bump_usage(qnorm, cached.get("video_id"))
            return
        except Exception:
            pass

    m = await message.reply_text("<b>⇜ جـارِ البحث ..</b>")
    
    try:
        results = YoutubeSearch(query, max_results=1).to_dict()
        if not results:
            await m.edit("- لم يتم العثـور على نتائج حاول مجددا")
            return

        link = f"https://youtube.com{results[0]['url_suffix']}"
        title = results[0]["title"][:40]
        title_clean = re.sub(r'[\\/*?:"<>|]', "", title)  # تنظيف اسم الملف
        thumbnail = results[0]["thumbnails"][0]
        thumb_name = f"{title_clean}.jpg"

        # تحميل الصورة المصغرة
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail) as resp:
                if resp.status == 200:
                    f = await aiofiles.open(thumb_name, mode='wb')
                    await f.write(await resp.read())
                    await f.close()

        duration = results[0]["duration"]

    except Exception as e:
        await m.edit("- لم يتم العثـور على نتائج حاول مجددا")
        print(str(e))
        return
    
    await m.edit("<b>جاري التحميل ♪</b>")

    # Acquire lock
    lock_acquired = False
    try:
        lock_acquired = await acquire_lock(qnorm)
    except Exception:
        lock_acquired = False

    # Rotate cookie files
    candidates = []
    try:
        candidates = await get_cookie_candidates()
    except Exception:
        candidates = [cookies()]

    info_dict = None
    audio_file = None
    last_error = None

    for cookie_path in candidates:
        ydl_opts = {
            "format": "bestaudio[ext=m4a]",  # تحديد صيغة M4A
            "keepvideo": False,
            "geo_bypass": True,
            "outtmpl": f"{title_clean}.%(ext)s",  # استخدام اسم نظيف للملف
            "quiet": True,
            "cookiefile": cookie_path,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(link, download=True)  # التنزيل مباشرة
                audio_file = ydl.prepare_filename(info_dict)
            await report_cookie_success(cookie_path)
            break
        except Exception as e:
            last_error = e
            try:
                await report_cookie_failure(cookie_path)
            except Exception:
                pass
            continue

    if not info_dict or not audio_file:
        await m.edit(f"error, wait for bot owner to fix\n\nError: {str(last_error) if last_error else 'Unknown error'}")
        if lock_acquired:
            try:
                await release_lock(qnorm)
            except Exception:
                pass
        return

    try:
        # حساب مدة الأغنية
        secmul, dur, dur_arr = 1, 0, duration.split(":")
        for i in range(len(dur_arr) - 1, -1, -1):
            dur += int(float(dur_arr[i])) * secmul
            secmul *= 60

        # إرسال الصوت
        sent = await message.reply_audio(
            audio=audio_file,
            caption=f"ᴍʏ ᴡᴏʀʟᴅ 𓏺 @{channel} ",
            title=title,
            performer=info_dict.get("uploader", "Unknown"),
            thumb=thumb_name,
            duration=dur,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(text="♪ 𝐋𝐚𝐫𝐢𝐧 ♪", url=lnk),
                    ],
                ]
            ),
        )
        await m.delete()

        # Save to cache
        try:
            await set_cache_from_message(
                query,
                {
                    "file_id": getattr(getattr(sent, "audio", None), "file_id", None),
                    "title": title,
                    "duration": dur,
                    "performer": info_dict.get("uploader", "Unknown"),
                    "video_id": extract_youtube_id(link),
                    "source": "youtube",
                },
            )
        except Exception:
            pass

    except Exception as e:
        await m.edit(f"error, wait for bot owner to fix\n\nError: {str(e)}")
        print(e)
    finally:
        # حذف الملفات المؤقتة
        try:
            remove_if_exists(audio_file)
            remove_if_exists(thumb_name)
        except Exception as e:
            print(e)
        if lock_acquired:
            try:
                await release_lock(qnorm)
            except Exception:
                pass
