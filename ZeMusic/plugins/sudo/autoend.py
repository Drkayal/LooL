import asyncio
import time
from typing import Dict, List

from pyrogram import filters
from pyrogram.types import Message

from ZeMusic import app
from ZeMusic.misc import SUDOERS
from config import LOGGER_ID
from ZeMusic.utils.database import (
    autoend_off,
    autoend_on,
    is_autoend,
    get_active_chats,
    get_active_video_chats,
    is_active_chat,
    is_active_video_chat,
    get_served_chats,
    get_assistant,
)

# Inactivity window set to 10 minutes (600 seconds)
INACTIVITY_SECONDS = 600

# Tracks the last time a chat was seen "active" for assistant usage
_last_active_ts: Dict[int, float] = {}

_auto_leave_task = None


async def _ensure_worker_started():
    global _auto_leave_task
    if _auto_leave_task is None or _auto_leave_task.done():
        _auto_leave_task = asyncio.create_task(_auto_leave_worker())


async def _mark_active(chat_id: int, now_ts: float) -> None:
    _last_active_ts[chat_id] = now_ts


async def _should_leave(chat_id: int, now_ts: float) -> bool:
    last_ts = _last_active_ts.get(chat_id)
    if last_ts is None:
        # Initialize baseline so we wait a full window after enabling feature
        _last_active_ts[chat_id] = now_ts
        return False
    return (now_ts - last_ts) >= INACTIVITY_SECONDS


async def _leave_silently(chat_id: int) -> None:
    try:
        assistant_client = await get_assistant(chat_id)
        await assistant_client.leave_chat(chat_id)
    except Exception:
        # Ignore all errors to keep worker silent and resilient
        pass
    finally:
        _last_active_ts.pop(chat_id, None)


async def _auto_leave_worker():
    # Periodically checks all served chats and leaves the ones inactive
    # for INACTIVITY_SECONDS, if autoend is enabled. Excludes LOGGER_ID.
    while True:
        try:
            if await is_autoend():
                now_ts = time.time()

                # Snapshot current active chats for quick membership test
                try:
                    active_audio: List[int] = await get_active_chats()
                except Exception:
                    active_audio = []
                try:
                    active_video: List[int] = await get_active_video_chats()
                except Exception:
                    active_video = []

                active_set = set(active_audio) | set(active_video)

                # Iterate over served chats only
                try:
                    served_docs = await get_served_chats()
                except Exception:
                    served_docs = []

                for chat_doc in served_docs:
                    chat_id = chat_doc.get("chat_id") if isinstance(chat_doc, dict) else None
                    if not isinstance(chat_id, int):
                        continue
                    if chat_id == LOGGER_ID:
                        # Never leave the log group
                        await _mark_active(chat_id, now_ts)
                        continue

                    # If currently active, refresh activity timestamp
                    if (chat_id in active_set) or (await is_active_chat(chat_id)) or (await is_active_video_chat(chat_id)):
                        await _mark_active(chat_id, now_ts)
                        continue

                    # If inactive for long enough, leave silently
                    if await _should_leave(chat_id, now_ts):
                        await _leave_silently(chat_id)
            # Sleep between cycles
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception:
            # Never crash; wait briefly and continue
            await asyncio.sleep(10)


# Commands without slash for enabling/disabling
@app.on_message(filters.regex(r"^تفعيل المغادره التلقائيه$") & SUDOERS)
async def cmd_enable_auto_leave(_, message: Message):
    await autoend_on()
    _last_active_ts.clear()
    await _ensure_worker_started()
    await message.reply_text("تم تفعيل المغادرة التلقائية بنجاح.")


@app.on_message(filters.regex(r"^تعطيل المغادره التلقائيه$") & SUDOERS)
async def cmd_disable_auto_leave(_, message: Message):
    await autoend_off()
    await message.reply_text("تم تعطيل المغادرة التلقائية بنجاح.")


# Lazy start worker on first seen update if autoend already enabled
_worker_started_flag = False

@app.on_message(filters.all, group=-1001)
async def _lazy_start_worker(_, message: Message):
    global _worker_started_flag
    if _worker_started_flag:
        return
    try:
        if await is_autoend():
            await _ensure_worker_started()
        _worker_started_flag = True
    except Exception:
        _worker_started_flag = True
