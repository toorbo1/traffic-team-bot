import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiohttp import web

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@rethewf")
REDIS_URL = os.getenv("REDIS_URL")  # если есть Redis на Railway
# ========================================================

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Выбор хранилища для FSM
if REDIS_URL:
    storage = RedisStorage.from_url(REDIS_URL)
    logger.info("✅ Используется Redis для хранения состояний")
else:
    storage = MemoryStorage()
    logger.warning("⚠️ REDIS_URL не задан, состояния хранятся в памяти (будут сбрасываться при перезапуске)")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Для сравнения канала
CHANNEL_USERNAME = CHANNEL_ID[1:] if CHANNEL_ID.startswith('@') else None

# Состояния FSM
class AdminReply(StatesGroup):
    waiting_for_reply = State()

def get_reply_keyboard(user_id: int):
    """Кнопка для ответа пользователю"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить пользователю", callback_data=f"reply:{user_id}")]
        ]
    )

def is_channel(chat: types.Chat) -> bool:
    """Проверяет, является ли чат целевым каналом"""
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

# ========== ОБРАБОТКА НАЖАТИЯ КНОПКИ "ОТВЕТИТЬ" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"🔘 Получен callback: {callback.data} от {callback.from_user.id}")
    await callback.answer()

    _, user_id_str = callback.data.split(':')
    target_user_id = int(user_id_str)

    # Сохраняем состояние для администратора
    await state.set_state(AdminReply.waiting_for_reply)
    await state.update_data(target_user_id=target_user_id)
    logger.info(f"✅ Установлено состояние ожидания ответа для админа {callback.from_user.id} -> пользователь {target_user_id}")

    await callback.message.reply(f"✍️ Напишите ответ для пользователя (ID: {target_user_id})")

# ========== ОБРАБОТЧИК ОТВЕТОВ АДМИНИСТРАТОРА ==========
@dp.message(AdminReply.waiting_for_reply)
async def send_admin_reply(message: types.Message, state: FSMContext):
    logger.info(f"📩 Получено сообщение от админа в состоянии: {message.text}")
    data = await state.get_data()
    target_user_id = data.get('target_user_id')

    if not target_user_id:
        logger.warning("❌ target_user_id не найден в состоянии")
        await message.reply("❌ Ошибка: получатель не найден. Нажмите кнопку заново.")
        await state.clear()
        return

    try:
        # Отправляем ответ пользователю
        await bot.send_message(
            target_user_id,
            f"✉️ **Ответ от администратора канала:**\n\n{message.text}"
        )
        logger.info(f"✅ Ответ отправлен пользователю {target_user_id}")
        await message.reply("✅ Ответ отправлен пользователю!")
    except Exception as e:
        logger.exception(f"❌ Ошибка при отправке ответа пользователю {target_user_id}")
        await message.reply(f"❌ Не удалось отправить ответ: {str(e)[:100]}")
    finally:
        await state.clear()
        logger.info(f"🧹 Состояние очищено для админа {message.from_user.id}")

# ========== ОБЩИЙ ОБРАБОТЧИК (ПЕРЕСЫЛКА СООБЩЕНИЙ В КАНАЛ) ==========
@dp.message()
async def forward_to_channel(message: types.Message):
    logger.info(f"📨 Общий обработчик: сообщение от {message.from_user.id} в чате {message.chat.id}")

    # Игнорируем сообщения из самого канала
    if is_channel(message.chat):
        logger.debug("🚫 Сообщение из канала проигнорировано (чтобы избежать зацикливания)")
        return

    if message.from_user.is_bot:
        return

    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        base = f"📨 Сообщение от {user.full_name} ({username})"

        # Определяем тип контента и отправляем в канал с кнопкой
        if message.text:
            sent = await bot.send_message(
                CHANNEL_ID,
                f"{base}:\n\n{message.text}",
                reply_markup=get_reply_keyboard(user.id)
            )
        elif message.photo:
            photo = message.photo[-1]
            caption = f"{base} 📸" + (f"\n\n{message.caption}" if message.caption else "")
            sent = await bot.send_photo(
                CHANNEL_ID, photo.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.video:
            caption = f"{base} 🎥" + (f"\n\n{message.caption}" if message.caption else "")
            sent = await bot.send_video(
                CHANNEL_ID, message.video.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.document:
            caption = f"{base} 📄" + (f"\n\n{message.caption}" if message.caption else "")
            sent = await bot.send_document(
                CHANNEL_ID, message.document.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.voice:
            sent = await bot.send_voice(
                CHANNEL_ID, message.voice.file_id,
                caption=f"{base} 🎤", reply_markup=get_reply_keyboard(user.id)
            )
        elif message.audio:
            sent = await bot.send_audio(
                CHANNEL_ID, message.audio.file_id,
                caption=f"{base} 🎵", reply_markup=get_reply_keyboard(user.id)
            )
        elif message.sticker:
            await bot.send_sticker(CHANNEL_ID, message.sticker.file_id)
            sent = await bot.send_message(
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

# ========== ВЕБ-СЕРВЕР ДЛЯ HEALTH CHECK (RAILWAY) ==========
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

# ========== ЗАПУСК БОТА ==========
async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не задан! Укажите переменную окружения.")
        exit(1)
    asyncio.run(main())