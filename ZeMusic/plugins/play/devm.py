import os
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from ZeMusic import app
from config import OWNER_ID, BOT_NAME
import config

lnk = "https://t.me/" + config.CHANNEL_LINK

@app.on_message(filters.regex(r"^(المطور|مطور)$"))
async def devid(c: Client, m: Message):
    usr = await c.get_users(OWNER_ID)
    name = usr.first_name
    usrnam = usr.username
    idd = usr.id
 
    info = await app.get_chat(idd)
    bioo = info.bio
    
    aname = f"<a href='tg://user?id={idd}'>{name}</a>"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
                InlineKeyboardButton(f"{name}", url=f"tg://openmessage?user_id={idd}")
            ]]
    )

    # نستخدم async for للحصول على الصور
    photos = []
    async for photo in c.get_chat_photos(idd, limit=1):
        photos.append(photo)

    if not photos:
        # إذا لم يكن هناك صور
        await m.reply_text(f"⟡ 𝙳𝚎𝚟 𝙱𝚘𝚝 ↦ {BOT_NAME}\n━━━━━━━━━━━━━\n• 𝙽𝚊𝚖𝚎 ↦ {aname}\n• 𝚄𝚜𝚎𝚛 ↦ @{usrnam}\n• 𝙱𝚒𝚘 ↦ {bioo}",reply_markup=keyboard)
    else:
        # إذا كانت هناك صورة
        await m.reply_photo(
            photos[0].file_id,
            caption=f"⟡ 𝙳𝚎𝚟 𝙱𝚘𝚝 ↦ {BOT_NAME}\n━━━━━━━━━━━━━\n• 𝙽𝚊𝚖𝚎 ↦ {aname}\n• 𝚄𝚜𝚎𝚛 ↦ @{usrnam}\n• 𝙱𝚒𝚘 ↦ {bioo}",
            reply_markup=keyboard)
