import asyncio

from pyrogram import filters
from pyrogram.enums import ChatMembersFilter
from pyrogram.errors import FloodWait

from ZeMusic import app
from ZeMusic.misc import SUDOERS
from ZeMusic.utils.database import (
    get_active_chats,
    get_authuser_names,
    get_client,
    get_served_chats,
    get_served_users,
)
from ZeMusic.utils.decorators.language import language
from ZeMusic.utils.formatters import alpha_to_int
from config import adminlist, OWNER_ID

IS_BROADCASTING = False


async def send_broadcast(
    target_ids: list,
    query: str = "",
    reply_chat_id: int = None,
    reply_message_id: int = None,
    pin_silent: bool = False,
    pin_loud: bool = False,
    forward: bool = True,
    delay: float = 0.2,
):
    """
    دالة مساعدة لإرسال/إعادة توجيه الرسائل إلى قائمة من القنوات/المجموعات/الأشخاص.

    المعاملات:
    - target_ids (list): قائمة بمعرفات الدردشات أو المستخدمين المراد الإرسال لهم.
    - query (str): النص المطلوب إرساله في حال عدم وجود رسالة للرد عليها.
    - reply_chat_id (int): رقم معرف الدردشة التي تحتوي على الرسالة الأصلية (لإعادة التوجيه).
    - reply_message_id (int): رقم معرف الرسالة الأصلية (لإعادة التوجيه).
    - pin_silent (bool): إذا كان True، يتم تثبيت الرسالة بصمت (دون إشعار الأعضاء).
    - pin_loud (bool): إذا كان True، يتم تثبيت الرسالة مع إشعار الأعضاء.
    - forward (bool): إذا كان True، يتم إعادة توجيه الرسالة بدلاً من إرسال نص جديد.
    - delay (float): مدة الانتظار (بالثواني) بين كل إرسال لتفادي FloodWait.

    تعيد الدالة Tuple مكونة من قيمتين:
    1) عدد الرسائل المرسلة/المعاد توجيهها بنجاح.
    2) عدد الرسائل المثبتة بنجاح.
    """
    sent_count = 0
    pinned_count = 0

    for target_id in target_ids:
        try:
            # إذا كنا نرغب في إعادة توجيه رسالة مقتبسة
            if reply_chat_id and reply_message_id and forward:
                msg = await app.forward_messages(
                    chat_id=target_id,
                    from_chat_id=reply_chat_id,
                    message_ids=reply_message_id,
                )
            else:
                # إرسال نص فقط في حال عدم تفعيل إعادة التوجيه
                msg = await app.send_message(chat_id=target_id, text=query)

            sent_count += 1

            # عملية تثبيت الرسالة إن طُلب ذلك
            if pin_silent or pin_loud:
                try:
                    await msg.pin(disable_notification=pin_silent)
                    pinned_count += 1
                except Exception:
                    pass

            # تأخير بسيط لتجنّب الـFloodWait الكبير
            await asyncio.sleep(delay)

        except FloodWait as fw:
            # إذا كان الانتظار كبيرًا جدًا، نتجاهل هذه الجهة ونكمل مع البقية
            if fw.value > 200:
                continue
            # ننتظر الوقت المطلوب ثم نكمل
            await asyncio.sleep(fw.value)

        except Exception:
            # تجاوز أي خطأ آخر والاستمرار
            continue

    return sent_count, pinned_count


@app.on_message(filters.command(["اذاعة", "بث"]) & SUDOERS)
@language
async def broadcast_message(client, message, _):
    """
    دالة الأمر الرئيسي للبث من خلال البوت، تتيح:
    - إرسال رسالة نصية جديدة.
    - أو إعادة توجيه رسالة من الرد عليها (Message Reply).
    
    خيارات مع الأمر (تُكتب في نص الرسالة بعد الأمر):
        -تثبيت         : تثبيت الرسالة بصمت (دون إشعارات).
        -تثبيت_بتنبيه  : تثبيت الرسالة مع إشعار الأعضاء.
        -بدون_بوت      : عدم الإرسال عبر حساب البوت 
                         (إذا أردت إرسال الرسائل فقط بالمساعد أو بأي طريقة أخرى).
        -مساعد         : إرسال/إعادة توجيه الرسائل عبر حسابات المساعد (Userbots).

    الخيارات الجديدة لتحديد الهدف من الإذاعة:
        -المشتركين     : إذاعة لجميع مستخدمي البوت (فقط).
        -المجموعات     : إذاعة لجميع المجموعات/القنوات التي يخدمها البوت (فقط).
        -الكل          : إذاعة للمستخدمين والمجموعات معًا.

    أمثلة للاستخدام:
      /اذاعة هذا نص تجريبي
      /اذاعة -تثبيت نص يتم تثبيته بصمت
      /اذاعة -المشتركين (لإرسال هذا النص إلى جميع من استخدم البوت فقط)
      /اذاعة -الكل تابعونا!
      (بالرد على رسالة لإعادة توجيهها): /بث
    """
    global IS_BROADCASTING

    if IS_BROADCASTING:
        return await message.reply_text("هناك عملية بث جارية حاليًا. الرجاء انتظار انتهائها.")

    # تحديد ما إذا كنا سنعيد توجيه رسالة مقتبسة أم سنرسل نصاً
    reply_chat_id = None
    reply_message_id = None
    query = ""

    if message.reply_to_message:
        reply_chat_id = message.chat.id
        reply_message_id = message.reply_to_message.id
    else:
        # إذا لم يكن هناك رد، نتحقق من وجود نص مع الأمر
        if len(message.command) < 2:
            return await message.reply_text(_["broad_2"])
        query = message.text.split(None, 1)[1]

    # استخلاص الخيارات من النص
    pin_silent = "-تثبيت" in message.text
    pin_loud = "-تثبيت_بتنبيه" in message.text
    no_bot = "-بدون_بوت" in message.text
    assistant_send = "-مساعد" in message.text

    # الإذاعة حسب الفئة:
    subs_flag = "-المشتركين" in message.text      # إذاعة للمستخدمين فقط
    groups_flag = "-المجموعات" in message.text    # إذاعة للمجموعات فقط
    all_flag = "-الكل" in message.text            # الجميع

    # إزالة العلامات من نص الإذاعة حتى لا تظهر للمستلم
    for opt in [
        "-تثبيت", "-تثبيت_بتنبيه", "-بدون_بوت", "-مساعد",
        "-المشتركين", "-المجموعات", "-الكل"
    ]:
        query = query.replace(opt, "")

    query = query.strip()  # إزالة الفراغات الزائدة في بداية/نهاية النص

    # إن لم يكن لدينا نص مُعد للإرسال ولا رسالة للرد عليها
    if not query and not reply_message_id:
        return await message.reply_text(_["broad_8"])

    IS_BROADCASTING = True
    await message.reply_text(_["broad_1"])  # رسالة بدء العملية

    # ----------------------------------------
    # منطق الإذاعة وفق العلامات المختارة:
    # ----------------------------------------
    # سنحدد ما إذا كان سيتم الإرسال للمستخدمين (subscribers)
    # أو للمجموعات/القنوات (chats) أو كليهما.

    def should_broadcast_to_users():
        # إذا تم اختيار -الكل أو -المشتركين فقط
        # أو تم استخدامFLAGS: -المشتركين + -المجموعات = -الكل
        if all_flag or (subs_flag and groups_flag):
            return True
        if subs_flag:
            return True
        return False

    def should_broadcast_to_groups():
        # إذا تم اختيار -الكل أو -المجموعات فقط
        # أو تم استخدامFLAGS: -المشتركين + -المجموعات = -الكل
        if all_flag or (subs_flag and groups_flag):
            return True
        if groups_flag:
            return True
        return False

    # إذا لم تُستخدم أي مِن هذه العلامات الثلاثة (المشتركين، المجموعات، الكل),
    # نعود للسلوك القديم: إرسال للمجموعات فقط إذا لم يتم وضع -بدون_بوت
    old_behavior = not (subs_flag or groups_flag or all_flag)

    # (A) إذاعة للمجموعات عبر حساب البوت (في حال كانت مطلوبة ولم يوضع -بدون_بوت)
    if (should_broadcast_to_groups() or old_behavior) and not no_bot:
        served_chats_data = await get_served_chats()
        served_chats = [int(chat["chat_id"]) for chat in served_chats_data]

        sent_count, pinned_count = await send_broadcast(
            target_ids=served_chats,
            query=query,
            reply_chat_id=reply_chat_id,
            reply_message_id=reply_message_id,
            pin_silent=pin_silent,
            pin_loud=pin_loud,
            forward=bool(reply_message_id),
        )
        try:
            await message.reply_text(_["broad_3"].format(sent_count, pinned_count))
        except:
            pass

    # (B) إذاعة للمستخدمين (المشتركين)
    if should_broadcast_to_users() and not no_bot:
        users_data = await get_served_users()
        served_users_ids = [int(u["user_id"]) for u in users_data]

        sent_count_users, _ = await send_broadcast(
            target_ids=served_users_ids,
            query=query,
            reply_chat_id=reply_chat_id,
            reply_message_id=reply_message_id,
            pin_silent=False,  # عادة لا يلزم تثبيت لدى المستخدم
            pin_loud=False,
            forward=bool(reply_message_id),
        )
        try:
            await message.reply_text(_["broad_4"].format(sent_count_users))
        except:
            pass

    # (C) البث عبر حسابات المساعد (Userbots) - في حال وضع -مساعد
    # ملاحظة: هنا لا نفرق بين مشتركين/مجموعات، لأنه يرسل لكل المحادثات في حساب المساعد
    if assistant_send:
        await_msg = await message.reply_text(_["broad_5"])
        from ZeMusic.core.userbot import assistants

        result_text = _["broad_6"]
        for num in assistants:
            sent_count_assistant = 0
            client_assistant = await get_client(num)

            # تجميع جميع الدردشات لدى حساب المساعد
            async for dialog in client_assistant.get_dialogs():
                try:
                    if reply_message_id:
                        # إعادة توجيه من الرسالة الأصلية
                        await client_assistant.forward_messages(
                            chat_id=dialog.chat.id,
                            from_chat_id=reply_chat_id,
                            message_ids=reply_message_id
                        )
                    else:
                        # إرسال نص
                        await client_assistant.send_message(dialog.chat.id, text=query)
                    sent_count_assistant += 1
                    # تأخير لمنع الـFloodWait
                    await asyncio.sleep(3)
                except FloodWait as fw:
                    if fw.value > 200:
                        continue
                    await asyncio.sleep(fw.value)
                except:
                    continue

            # إضافة ملخص لكل حساب مساعد
            result_text += _["broad_7"].format(num, sent_count_assistant)

        try:
            await await_msg.edit_text(result_text)
        except:
            pass

    IS_BROADCASTING = False


async def auto_clean():
    """
    دالة تعمل تلقائياً كل 10 ثوانٍ،
    تقوم بتحديث قائمة المشرفين في الدردشات التي يديرها البوت
    وفقاً لصلاحيات إدارة الدردشة الصوتية أو عبر قاعدة البيانات (authuser).
    """
    while not await asyncio.sleep(10):
        try:
            active_chats = await get_active_chats()
            for chat_id in active_chats:
                if chat_id not in adminlist:
                    adminlist[chat_id] = []

                    # جلب جميع الإداريين/المديرين
                    async for user in app.get_chat_members(
                        chat_id,
                        filter=ChatMembersFilter.ADMINISTRATORS
                    ):
                        if user.privileges.can_manage_video_chats:
                            adminlist[chat_id].append(user.user.id)

                    # جلب المستخدمين المخوّلين من قاعدة البيانات
                    authusers = await get_authuser_names(chat_id)
                    for authuser in authusers:
                        user_id = await alpha_to_int(authuser)
                        adminlist[chat_id].append(user_id)

        except:
            continue


# إطلاق مهمة تحديث قائمة المشرفين في الخلفية
asyncio.create_task(auto_clean())
