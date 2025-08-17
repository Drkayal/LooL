import asyncio
from pyrogram import filters
from pyrogram.types import CallbackQuery, Message
from pyrogram.enums import ChatType

from ZeMusic import app
from config import OWNER_ID, BOT_NAME
from ZeMusic.utils.database import (
    is_music_replies_disabled,
    disable_music_replies,
    enable_music_replies,
    add_served_user,
    add_served_chat,
)


# Owner-only commands (Arabic):
# "تعطيل ردود الميوزك" -> disable; "تفعيل ردود الميوزك" -> enable
@app.on_message(filters.regex(r"^تعطيل ردود الميوزك$") & filters.user(OWNER_ID))
async def disable_music_replies_cmd(_, message: Message):
    await disable_music_replies()
    # Silent confirmation to owner only
    await message.reply_text("تم تعطيل ردود الميوزك بنجاح.")


@app.on_message(filters.regex(r"^تفعيل ردود الميوزك$") & filters.user(OWNER_ID))
async def enable_music_replies_cmd(_, message: Message):
    await enable_music_replies()
    # Silent confirmation to owner only
    await message.reply_text("تم تفعيل ردود الميوزك بنجاح.")


# Silent interceptors: when disabled, stop propagation early for commands
# registered in the specified modules, without affecting other bot features.

# Callback data used by ZeMusic/plugins/play/zzcmd.py
ZZCMD_CALLBACKS = {
    "zzzback",
    "zzzdv",
    "zzzll",
    "zzzad",
    "zzzch",
    "zzzup",
    "zzzsu",
    "zzzbn",
    "zzzas",
}


def _is_target_trigger(text: str) -> bool:
    """Return True if message text is one of the triggers handled by the target modules."""
    if not text:
        return False
    plain = text.strip()

    # Abod.py triggers
    abod_exact = {
        "غنيلي",
        "‹ غنيلي ›",
        "‹ صور ›",
        "صور",
        "‹ انمي ›",
        "انمي",
        "‹ متحركه ›",
        "متحركه",
        "‹ اقتباسات ›",
        "اقتباسات",
        "هيدرات",
        "‹ هيدرات ›",
        "‹ افتارات شباب ›",
        "‹ افتار بنات ›",
        "‹ قران ›",
        "قران",
    }
    if plain in abod_exact:
        return True
    if plain == f"{BOT_NAME} غنيلي" or plain == BOT_NAME:
        return True

    # bot.py triggers
    botpy_exact = {
        "انا من",
        "انا منو",
        "ايديي",
        "id",
        "اسمي",
        "يوزري",
        "البايو",
        "بايو",
        "رابط الحذف",
        "بوت الحذف",
    }
    if plain in botpy_exact:
        return True

    # cmds.py triggers
    cmds_exact = {
        "اوامر الميوزك",
        "ميوزك",
        "الاوامر",
        "الميوزك",
        "اوامر ميوزك",
    }
    if plain in cmds_exact:
        return True

    # devm.py triggers
    if plain in {"المطور", "مطور"}:
        return True

    # كيبورد.py triggers
    if plain == "/cmds" or plain == "‹ اخفاء الكيبورد ›":
        return True

    # نادي المطور.py triggers (with optional '.' prefix)
    if plain == "نادي المطور" or plain == ".نادي المطور":
        return True

    # Managed/Bot.py trigger
    if plain == "بوت":
        return True

    # Managed/BotName.py (exact bot name)
    if plain == BOT_NAME:
        return True

    # Managed/Gpt.py (command without prefix, expects arguments sometimes)
    if plain == "رون" or plain.startswith("رون "):
        return True

    # Managed/Telegraph.py triggers
    if plain in {"تلغراف", "ميديا", "تلكراف", "تلجراف", "‹ تلغراف ›"}:
        return True

    # start.py triggers (/start in private/group with optional args)
    if plain.startswith("/start"):
        return True

    return False


# Intercept both private and group messages at a very early group
@app.on_message(filters.all, group=-1000)
async def silence_music_replies(_, message: Message):
    if not await is_music_replies_disabled():
        return

    text = (message.text or message.caption or "")
    if not text:
        return

    # Allow owner control commands to pass (so owner can re-enable)
    if (text.strip() in ("تفعيل ردود الميوزك", "تعطيل ردود الميوزك")) and message.from_user and message.from_user.id == OWNER_ID:
        return

    if not _is_target_trigger(text):
        return

    # Minimal background work for /start: record served user/chat without replying
    if text.startswith("/start"):
        try:
            if message.chat.type == ChatType.PRIVATE and message.from_user:
                await add_served_user(message.from_user.id)
            elif message.chat.type in (ChatType.SUPERGROUP, ChatType.GROUP):
                await add_served_chat(message.chat.id)
        except Exception:
            pass

    # Silence output: stop further handlers
    try:
        await message.stop_propagation()
    except Exception:
        pass


@app.on_callback_query(group=-1000)
async def silence_music_callbacks(_, query: CallbackQuery):
    if not await is_music_replies_disabled():
        return

    data = (query.data or "").strip()
    if not data:
        return

    if data in ZZCMD_CALLBACKS:
        try:
            await query.stop_propagation()
        except Exception:
            pass