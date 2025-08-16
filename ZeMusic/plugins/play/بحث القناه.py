import os
import re
import config
import aiohttp
import aiofiles
from ZeMusic.platforms.Youtube import cookies
import yt_dlp
from yt_dlp import YoutubeDL
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from youtube_search import YoutubeSearch
from ZeMusic import app
from ZeMusic.plugins.play.filters import command


def remove_if_exists(path):
    if os.path.exists(path):
        os.remove(path)

channel = "KHAYAL70"
lnk = f"https://t.me/{config.CHANNEL_LINK}"
Nem = config.BOT_NAME + " ابحث"

@app.on_message(command(["song", "/song", "بحث", Nem,"يوت"]) & filters.channel)
async def song_downloader3(client, message: Message):
    query = " ".join(message.command[1:])
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
    
    ydl_opts = {
        "format": "bestaudio[ext=m4a]",  # تحديد صيغة M4A
        "keepvideo": False,
        "geo_bypass": True,
        "outtmpl": f"{title_clean}.%(ext)s",  # استخدام اسم نظيف للملف
        "quiet": True,
        "cookiefile": f"{cookies()}",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=True)  # التنزيل مباشرة
            audio_file = ydl.prepare_filename(info_dict)

        # حساب مدة الأغنية
        secmul, dur, dur_arr = 1, 0, duration.split(":")
        for i in range(len(dur_arr) - 1, -1, -1):
            dur += int(float(dur_arr[i])) * secmul
            secmul *= 60

        # إرسال الصوت
        await message.reply_audio(
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

    except Exception as e:
        await m.edit(f"error, wait for bot owner to fix\n\nError: {str(e)}")
        print(e)

    # حذف الملفات المؤقتة
    try:
        remove_if_exists(audio_file)
        remove_if_exists(thumb_name)
    except Exception as e:
        print(e)
