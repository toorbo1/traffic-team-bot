import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@rethewf")
REDIS_URL = os.getenv("REDIS_URL")  # опционально
# ================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Для сравнения канала
CHANNEL_USERNAME = CHANNEL_ID[1:] if CHANNEL_ID.startswith('@') else None

# Хранилище активных ответов: { admin_id: target_user_id }
# Если Redis доступен, используем его, иначе простой словарь (не сохраняется между перезапусками)
if REDIS_URL:
    import redis.asyncio as redis
    redis_client = redis.from_url(REDIS_URL)
    logger.info("✅ Используется Redis для хранения ответов")
else:
    redis_client = None
    active_replies = {}
    logger.warning("⚠️ Redis не задан, ответы хранятся в памяти и сбросятся при перезапуске")

async def set_admin_reply(admin_id: int, user_id: int):
    """Сохранить, что админ сейчас отвечает пользователю user_id"""
    if redis_client:
        await redis_client.set(f"admin_reply:{admin_id}", user_id, ex=3600)  # таймаут 1 час
    else:
        active_replies[admin_id] = user_id

async def get_admin_reply(admin_id: int) -> int | None:
    """Получить user_id, которому админ сейчас отвечает (или None)"""
    if redis_client:
        val = await redis_client.get(f"admin_reply:{admin_id}")
        return int(val) if val else None
    else:
        return active_replies.get(admin_id)

async def clear_admin_reply(admin_id: int):
    """Очистить запись после ответа"""
    if redis_client:
        await redis_client.delete(f"admin_reply:{admin_id}")
    else:
        active_replies.pop(admin_id, None)

def get_reply_keyboard(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить пользователю", callback_data=f"reply:{user_id}")]
        ]
    )

def is_channel(chat: types.Chat) -> bool:
    """Проверка, является ли чат целевым каналом"""
    if str(chat.id) == CHANNEL_ID:
        return True
    if CHANNEL_USERNAME and chat.username == CHANNEL_USERNAME:
        return True
    return False

# ========== КОМАНДА /start ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот-посредник для связи с каналом.\n"
        "Напишите любое сообщение, и оно будет отправлено в канал.\n"
        "Ответы из канала вы получите здесь."
    )

# ========== ОБРАБОТКА КНОПКИ "ОТВЕТИТЬ" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery):
    await callback.answer()
    _, user_id_str = callback.data.split(':')
    target_user_id = int(user_id_str)
    admin_id = callback.from_user.id

    # Сохраняем, что этот админ собирается ответить пользователю
    await set_admin_reply(admin_id, target_user_id)
    logger.info(f"✅ Админ {admin_id} будет отвечать пользователю {target_user_id}")

    await callback.message.reply(f"✍️ Теперь напишите ваш ответ в этот чат (или в канал). Он будет отправлен пользователю.")

# ========== ОБРАБОТКА ВСЕХ СООБЩЕНИЙ ==========
@dp.message()
async def handle_message(message: types.Message):
    # Если сообщение пришло из канала – проверим, не ответ ли это администратора
    if is_channel(message.chat):
        # Это сообщение из канала. Проверяем, не является ли отправитель администратором с активным ответом
        admin_id = message.from_user.id
        target_user_id = await get_admin_reply(admin_id)
        if target_user_id:
            # Это ответ администратора конкретному пользователю
            try:
                await bot.send_message(
                    target_user_id,
                    f"✉️ **Ответ от администратора канала:**\n\n{message.text}"
                )
                logger.info(f"✅ Ответ отправлен пользователю {target_user_id} от админа {admin_id}")
                await message.reply("✅ Ответ отправлен пользователю!")
            except Exception as e:
                logger.exception("Ошибка при отправке ответа")
                await message.reply(f"❌ Не удалось отправить ответ: {e}")
            finally:
                await clear_admin_reply(admin_id)
            return  # Важно! Не обрабатываем как обычное сообщение в канал
        else:
            # Сообщение из канала, но не от админа с активным ответом – игнорируем, чтобы не зациклиться
            logger.debug("Сообщение из канала проигнорировано (не ответ)")
            return

    # Если это не канал – значит, сообщение от обычного пользователя (или админа в личку)
    # Но нужно различать: если админ пишет в личку боту, это может быть тестовое сообщение, а не ответ.
    # По нашей логике ответы админ пишет в канале, поэтому сообщения в личку обрабатываем как обычные (пересылаем в канал).
    # Однако если админ случайно напишет в личку, это тоже перешлётся в канал. Чтобы избежать путаницы,
    # можно добавить проверку: если отправитель есть в списке администраторов, но нет активного ответа,
    # то это обычное сообщение (пересылаем). А если есть активный ответ, но сообщение не из канала – возможно, ошибка.
    # Для простоты будем считать: любое сообщение не из канала – от пользователя, пересылаем.

    # Пересылка сообщения пользователя в канал
    if message.from_user.is_bot:
        return

    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        base = f"📨 Сообщение от {user.full_name} ({username})"

        if message.text:
            sent = await bot.send_message(CHANNEL_ID, f"{base}:\n\n{message.text}",
                                          reply_markup=get_reply_keyboard(user.id))
        elif message.photo:
            photo = message.photo[-1]
            caption = f"{base} 📸" + (f"\n\n{message.caption}" if message.caption else "")
            sent = await bot.send_photo(CHANNEL_ID, photo.file_id, caption=caption,
                                        reply_markup=get_reply_keyboard(user.id))
        elif message.video:
            caption = f"{base} 🎥" + (f"\n\n{message.caption}" if message.caption else "")
            sent = await bot.send_video(CHANNEL_ID, message.video.file_id, caption=caption,
                                        reply_markup=get_reply_keyboard(user.id))
        elif message.document:
            caption = f"{base} 📄" + (f"\n\n{message.caption}" if message.caption else "")
            sent = await bot.send_document(CHANNEL_ID, message.document.file_id, caption=caption,
                                           reply_markup=get_reply_keyboard(user.id))
        elif message.voice:
            sent = await bot.send_voice(CHANNEL_ID, message.voice.file_id, caption=f"{base} 🎤",
                                        reply_markup=get_reply_keyboard(user.id))
        elif message.audio:
            sent = await bot.send_audio(CHANNEL_ID, message.audio.file_id, caption=f"{base} 🎵",
                                        reply_markup=get_reply_keyboard(user.id))
        elif message.sticker:
            await bot.send_sticker(CHANNEL_ID, message.sticker.file_id)
            sent = await bot.send_message(CHANNEL_ID, f"{base} (стикер)",
                                          reply_markup=get_reply_keyboard(user.id))
        else:
            await message.answer("❌ Неподдерживаемый тип")
            return

        await message.answer("✅ Сообщение отправлено в канал!")
    except Exception as e:
        logger.exception("Ошибка при отправке в канал")
        await message.answer("❌ Ошибка при отправке")

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
    logger.info(f"Web server started on port {port}")

async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан")
        exit(1)
    asyncio.run(main())