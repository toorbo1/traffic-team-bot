import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
# CHANNEL_ID может быть числовым ID (например, -1001234567890) или юзернеймом (@example)
RAW_CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003810467733")  # по умолчанию ваш ID как строка
REDIS_URL = os.getenv("REDIS_URL")
# ========================================================

# Преобразуем CHANNEL_ID в нужный тип (int для числовых ID, str для юзернеймов)
try:
    # Убираем пробелы и проверяем, похоже ли на число (с учётом ведущего минуса)
    cleaned = RAW_CHANNEL_ID.strip()
    if cleaned.lstrip('-').isdigit():
        CHANNEL_ID = int(cleaned)
    else:
        CHANNEL_ID = cleaned  # оставляем как есть (например, @username)
except:
    CHANNEL_ID = RAW_CHANNEL_ID.strip()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ----- Хранилище активных ответов (с поддержкой Redis) -----
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
    logger.warning("⚠️ Redis не используется, состояния хранятся в памяти")

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
# -----------------------------------------------------------

def get_reply_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой ответа пользователю"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить пользователю", callback_data=f"reply:{user_id}")]
        ]
    )

def is_target_chat(chat: types.Chat) -> bool:
    """Проверяет, является ли чат целевой группой (по ID или username)"""
    # Приводим CHANNEL_ID к строке для сравнения
    target = str(CHANNEL_ID)
    if str(chat.id) == target:
        return True
    # Если CHANNEL_ID задан как @username
    if target.startswith('@') and chat.username == target[1:]:
        return True
    return False

async def get_chat_admins(chat_id: int):
    """Возвращает список ID администраторов чата"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins]
        logger.info(f"Получены администраторы чата {chat_id}: {admin_ids}")
        return admin_ids
    except Exception as e:
        logger.exception(f"Не удалось получить администраторов чата {chat_id}: {e}")
        return []

# ========== КОМАНДА /start ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info(f"Команда /start от {message.from_user.id}")
    await message.answer(
        "👋 Привет! Я бот-посредник для связи с группой.\n"
        "Напишите любое сообщение, и оно будет отправлено в группу.\n"
        "Ответы из группы вы получите здесь."
    )

# ========== КОМАНДА /cancel ==========
@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    admin_id = message.from_user.id
    await clear_admin_reply(admin_id)
    await message.answer("✅ Режим ответа сброшен.")

# ========== КОМАНДА /debug (для проверки статуса бота в группе) ==========
@dp.message(Command("debug"))
async def cmd_debug(message: types.Message):
    """Показывает информацию о группе и правах бота (только для администраторов)"""
    if not is_target_chat(message.chat) and message.chat.type != "private":
        await message.answer("❌ Эта команда работает только в целевой группе или личке.")
        return

    try:
        # Пытаемся получить информацию о чате
        chat = await bot.get_chat(CHANNEL_ID)
        bot_member = await chat.get_member(bot.id)
        status = "✅ Бот является администратором" if bot_member.status == "administrator" else f"❌ Статус бота: {bot_member.status}"
        await message.answer(
            f"**Информация о группе:**\n"
            f"ID: `{chat.id}`\n"
            f"Название: {chat.title}\n"
            f"Тип: {chat.type}\n"
            f"Бот: {status}\n\n"
            f"Убедитесь, что бот добавлен в администраторы с правом 'Читать сообщения'."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении информации: {e}")

# ========== ОБРАБОТКА КНОПКИ "ОТВЕТИТЬ" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery):
    logger.info(f"🔘 Получен callback: {callback.data} от {callback.from_user.id}")
    await callback.answer()

    _, user_id_str = callback.data.split(':')
    target_user_id = int(user_id_str)
    admin_id = callback.from_user.id

    await set_admin_reply(admin_id, target_user_id)

    await callback.message.reply(
        f"✍️ Теперь напишите ваш ответ в группу. Он будет отправлен пользователю."
    )

# ========== ОБЩИЙ ОБРАБОТЧИК СООБЩЕНИЙ ==========
@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.is_bot:
        return

    logger.info(f"Получено сообщение: чат={message.chat.id} ({message.chat.type}), от={message.from_user.id}")

    # --- Сообщение из ЦЕЛЕВОЙ ГРУППЫ (потенциальный ответ администратора) ---
    if is_target_chat(message.chat):
        logger.info("Сообщение из целевой группы")
        # Проверяем, является ли отправитель администратором группы
        admins = await get_chat_admins(message.chat.id)
        if message.from_user.id not in admins:
            logger.debug("Сообщение от обычного участника группы проигнорировано")
            return

        admin_id = message.from_user.id
        target_user_id = await get_admin_reply(admin_id)

        if target_user_id:
            logger.info(f"👤 Админ {admin_id} отвечает пользователю {target_user_id}")
            try:
                # Отправка ответа пользователю с поддержкой разных типов контента
                if message.text:
                    await bot.send_message(
                        target_user_id,
                        f"✉️ **Ответ от администратора группы:**\n\n{message.text}"
                    )
                elif message.photo:
                    photo = message.photo[-1]
                    caption = f"✉️ **Ответ от администратора группы:**\n\n{message.caption or ''}"
                    await bot.send_photo(target_user_id, photo.file_id, caption=caption)
                elif message.video:
                    caption = f"✉️ **Ответ от администратора группы:**\n\n{message.caption or ''}"
                    await bot.send_video(target_user_id, message.video.file_id, caption=caption)
                elif message.document:
                    caption = f"✉️ **Ответ от администратора группы:**\n\n{message.caption or ''}"
                    await bot.send_document(target_user_id, message.document.file_id, caption=caption)
                elif message.voice:
                    await bot.send_voice(target_user_id, message.voice.file_id,
                                         caption="✉️ Ответ от администратора группы (голосовое)")
                elif message.audio:
                    await bot.send_audio(target_user_id, message.audio.file_id,
                                         caption="✉️ Ответ от администратора группы (аудио)")
                elif message.sticker:
                    await bot.send_sticker(target_user_id, message.sticker.file_id)
                    await bot.send_message(target_user_id, "✉️ Ответ от администратора группы (стикер)")
                else:
                    await message.reply("❌ Неподдерживаемый тип ответа")
                    return

                logger.info(f"✅ Ответ отправлен пользователю {target_user_id}")
                await message.reply("✅ Ответ отправлен пользователю!")
            except Exception as e:
                logger.exception(f"❌ Ошибка при отправке ответа пользователю {target_user_id}")
                await message.reply(f"❌ Не удалось отправить ответ: {str(e)[:200]}")
            finally:
                await clear_admin_reply(admin_id)
            return
        else:
            logger.debug("Сообщение администратора в группе проигнорировано (нет активного ответа)")
            return

    # --- Сообщение от пользователя (личка) → пересылаем в ГРУППУ ---
    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        base = f"📨 Сообщение от {user.full_name} ({username})"

        # Отправляем в группу (CHANNEL_ID)
        if message.text:
            await bot.send_message(
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

        await message.answer("✅ Сообщение отправлено в группу!")
    except Exception as e:
        logger.exception("❌ Ошибка при отправке в группу")
        # Пытаемся отправить пользователю более конкретное сообщение, но не раскрывая технических деталей
        error_text = str(e)
        if "chat not found" in error_text.lower():
            user_msg = "❌ Группа не найдена. Проверьте CHANNEL_ID."
        elif "forbidden" in error_text.lower():
            user_msg = "❌ Бот не имеет прав для отправки сообщений в группу. Убедитесь, что он администратор."
        else:
            user_msg = "❌ Ошибка при отправке, попробуйте позже."
        await message.answer(user_msg)

# ========== HEALTH CHECK ДЛЯ RAILWAY ==========
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