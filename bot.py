import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@rethewf")
REDIS_URL = os.getenv("REDIS_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CHANNEL_USERNAME = CHANNEL_ID[1:] if CHANNEL_ID.startswith('@') else None

# ----- Хранилище активных ответов с обработкой ошибок -----
if REDIS_URL:
    try:
        import redis.asyncio as redis
        redis_client = redis.from_url(REDIS_URL)
        logger.info("✅ Redis подключён")
    except Exception as e:
        logger.exception(f"❌ Ошибка подключения к Redis: {e}")
        redis_client = None
else:
    redis_client = None
    active_replies = {}
    logger.warning("⚠️ Redis не используется, состояния в памяти")

async def set_admin_reply(admin_id: int, user_id: int):
    try:
        if redis_client:
            await redis_client.set(f"admin_reply:{admin_id}", user_id, ex=3600)
            logger.info(f"📦 Redis: сохранено admin_reply:{admin_id} = {user_id}")
        else:
            active_replies[admin_id] = user_id
            logger.info(f"📦 Memory: сохранено admin_reply:{admin_id} = {user_id}")
    except Exception as e:
        logger.exception(f"❌ Ошибка при сохранении состояния admin {admin_id}")

async def get_admin_reply(admin_id: int) -> int | None:
    try:
        if redis_client:
            val = await redis_client.get(f"admin_reply:{admin_id}")
            if val:
                logger.info(f"📦 Redis: получено admin_reply:{admin_id} = {val}")
                return int(val)
            else:
                logger.info(f"📦 Redis: admin_reply:{admin_id} не найдено")
                return None
        else:
            val = active_replies.get(admin_id)
            logger.info(f"📦 Memory: admin_reply:{admin_id} = {val}")
            return val
    except Exception as e:
        logger.exception(f"❌ Ошибка при чтении состояния admin {admin_id}")
        return None

async def clear_admin_reply(admin_id: int):
    try:
        if redis_client:
            await redis_client.delete(f"admin_reply:{admin_id}")
            logger.info(f"📦 Redis: удалено admin_reply:{admin_id}")
        else:
            active_replies.pop(admin_id, None)
            logger.info(f"📦 Memory: удалено admin_reply:{admin_id}")
    except Exception as e:
        logger.exception(f"❌ Ошибка при удалении состояния admin {admin_id}")
# ---------------------------------------------------------

def get_reply_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить пользователю", callback_data=f"reply:{user_id}")]
        ]
    )

def is_channel(chat: types.Chat) -> bool:
    """Сравнивает с CHANNEL_ID (учитывая @ и числовые ID)"""
    if str(chat.id) == CHANNEL_ID:
        return True
    if CHANNEL_USERNAME and chat.username == CHANNEL_USERNAME:
        return True
    return False

# ========== КОМАНДА /start ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info(f"Команда /start от {message.from_user.id}")
    await message.answer(
        "👋 Привет! Я бот-посредник для связи с каналом.\n"
        "Напишите любое сообщение, и оно будет отправлено в канал.\n"
        "Ответы из канала вы получите здесь."
    )

# ========== КОМАНДА /cancel (сброс состояния ответа) ==========
@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    admin_id = message.from_user.id
    await clear_admin_reply(admin_id)
    await message.answer("✅ Режим ответа сброшен. Теперь ваши сообщения в канале не будут отправляться пользователям.")

# ========== ОБРАБОТКА КНОПКИ "ОТВЕТИТЬ" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery):
    logger.info(f"🔘 Получен callback: {callback.data} от {callback.from_user.id}")
    await callback.answer()

    _, user_id_str = callback.data.split(':')
    target_user_id = int(user_id_str)
    admin_id = callback.from_user.id

    # Сохраняем состояние
    await set_admin_reply(admin_id, target_user_id)

    await callback.message.reply(
        f"✍️ Теперь напишите ваш ответ в этот чат (или в канал). "
        f"Он будет отправлен пользователю."
    )

# ========== ОБЩИЙ ОБРАБОТЧИК СООБЩЕНИЙ ==========
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot:
        return

    # --- Сообщение из КАНАЛА (потенциальный ответ администратора) ---
    if is_channel(message.chat):
        admin_id = message.from_user.id
        target_user_id = await get_admin_reply(admin_id)

        if target_user_id:
            logger.info(f"👤 Админ {admin_id} отвечает пользователю {target_user_id}")
            try:
                # Определяем тип содержимого
                if message.text:
                    await bot.send_message(
                        target_user_id,
                        f"✉️ **Ответ от администратора канала:**\n\n{message.text}"
                    )
                elif message.photo:
                    photo = message.photo[-1]
                    caption = f"✉️ **Ответ от администратора канала:**\n\n{message.caption or ''}"
                    await bot.send_photo(target_user_id, photo.file_id, caption=caption)
                elif message.video:
                    caption = f"✉️ **Ответ от администратора канала:**\n\n{message.caption or ''}"
                    await bot.send_video(target_user_id, message.video.file_id, caption=caption)
                elif message.document:
                    caption = f"✉️ **Ответ от администратора канала:**\n\n{message.caption or ''}"
                    await bot.send_document(target_user_id, message.document.file_id, caption=caption)
                elif message.voice:
                    await bot.send_voice(target_user_id, message.voice.file_id,
                                         caption="✉️ Ответ от администратора канала (голосовое)")
                elif message.audio:
                    await bot.send_audio(target_user_id, message.audio.file_id,
                                         caption="✉️ Ответ от администратора канала (аудио)")
                elif message.sticker:
                    await bot.send_sticker(target_user_id, message.sticker.file_id)
                    await bot.send_message(target_user_id, "✉️ Ответ от администратора канала (стикер)")
                else:
                    await message.reply("❌ Неподдерживаемый тип ответа")
                    return

                logger.info(f"✅ Ответ отправлен пользователю {target_user_id}")
                await message.reply("✅ Ответ отправлен пользователю!")
            except Exception as e:
                logger.exception(f"❌ Ошибка при отправке ответа пользователю {target_user_id}")
                await message.reply(f"❌ Не удалось отправить ответ: {str(e)[:100]}")
            finally:
                await clear_admin_reply(admin_id)
            return
        else:
            logger.debug("Сообщение из канала проигнорировано (нет активного ответа)")
            return

    # --- Сообщение от пользователя (личка) → пересылаем в канал ---
    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        base = f"📨 Сообщение от {user.full_name} ({username})"

        if message.text:
            sent = await bot.send_message(
                CHANNEL_ID,
                f"{base}:\n\n{message.text}",
                reply_markup=get_reply_keyboard(user.id)
            )
        elif message.photo:
            photo = message.photo[-1]
            caption = f"{base} 📸" + (f"\n\n{message.caption}" if message.caption else "")
            await bot.send_photo(
                CHANNEL_ID, photo.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.video:
            caption = f"{base} 🎥" + (f"\n\n{message.caption}" if message.caption else "")
            await bot.send_video(
                CHANNEL_ID, message.video.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.document:
            caption = f"{base} 📄" + (f"\n\n{message.caption}" if message.caption else "")
            await bot.send_document(
                CHANNEL_ID, message.document.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.voice:
            await bot.send_voice(
                CHANNEL_ID, message.voice.file_id,
                caption=f"{base} 🎤", reply_markup=get_reply_keyboard(user.id)
            )
        elif message.audio:
            await bot.send_audio(
                CHANNEL_ID, message.audio.file_id,
                caption=f"{base} 🎵", reply_markup=get_reply_keyboard(user.id)
            )
        elif message.sticker:
            await bot.send_sticker(CHANNEL_ID, message.sticker.file_id)
            await bot.send_message(
                CHANNEL_ID, f"{base} (стикер)",
                reply_markup=get_reply_keyboard(user.id)
            )
        else:
            await message.answer("❌ Неподдерживаемый тип сообщения")
            return

        await message.answer("✅ Сообщение отправлено в канал!")
    except Exception as e:
        logger.exception("❌ Ошибка при отправке в канал")
        await message.answer("❌ Ошибка при отправке, попробуйте позже.")

# ========== HEALTH CHECK ==========
async def health_check(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web server started on port {port}")

async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не задан!")
        exit(1)
    asyncio.run(main())