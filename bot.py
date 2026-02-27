import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiohttp import web

# ========== НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@rethewf")  # можно указать @username или числовой ID

# Если CHANNEL_ID указан как @username, сохраняем также имя без @ для сравнения
CHANNEL_USERNAME = CHANNEL_ID[1:] if CHANNEL_ID.startswith('@') else None
# ========================================================

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище связей сообщений в канале с пользователями (в памяти)
message_owners = {}

# Состояния для ответа администратора
class AdminReply(StatesGroup):
    waiting_for_reply = State()

def get_reply_keyboard(user_id: int):
    """Кнопка для ответа пользователю, которая будет в канале"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить пользователю", callback_data=f"reply:{user_id}")]
        ]
    )

def is_channel(chat: types.Chat) -> bool:
    """Проверяет, является ли чат целевым каналом"""
    # Сравниваем по ID (если CHANNEL_ID числовой)
    if str(chat.id) == CHANNEL_ID:
        return True
    # Сравниваем по username (если CHANNEL_ID был @username)
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

# ========== ОБРАБОТКА НАЖАТИЯ КНОПКИ "ОТВЕТИТЬ" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _, user_id_str = callback.data.split(':')
    target_user_id = int(user_id_str)
    # Устанавливаем состояние ожидания ответа
    await state.set_state(AdminReply.waiting_for_reply)
    await state.update_data(target_user_id=target_user_id)
    await callback.message.reply(f"✍️ Напишите ответ для пользователя (ID: {target_user_id})")

# ========== ОБРАБОТЧИК ОТВЕТОВ АДМИНИСТРАТОРА (ИЗ КАНАЛА) ==========
# Этот обработчик должен быть ДО общего, чтобы перехватывать сообщения, когда активно состояние
@dp.message(AdminReply.waiting_for_reply)
async def send_admin_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    if not target_user_id:
        await message.reply("❌ Ошибка: получатель не найден.")
        await state.clear()
        return

    try:
        # Отправляем ответ пользователю
        await bot.send_message(
            target_user_id,
            f"✉️ **Ответ от администратора канала:**\n\n{message.text}"
        )
        await message.reply("✅ Ответ отправлен пользователю!")
        logger.info(f"Ответ отправлен пользователю {target_user_id}")
    except Exception as e:
        logger.exception("Ошибка при отправке ответа пользователю")
        await message.reply("❌ Не удалось отправить ответ. Возможно, пользователь заблокировал бота.")
    finally:
        await state.clear()

# ========== ОБЩИЙ ОБРАБОТЧИК СООБЩЕНИЙ (ПЕРЕСЫЛКА В КАНАЛ) ==========
@dp.message()
async def forward_to_channel(message: types.Message):
    # Игнорируем сообщения из самого канала (чтобы избежать зацикливания)
    if is_channel(message.chat):
        logger.debug(f"Сообщение из канала проигнорировано: {message.text}")
        return

    # Игнорируем служебные сообщения (например, от самого бота)
    if message.from_user and message.from_user.is_bot:
        return

    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        caption_base = f"📨 Сообщение от {user.full_name} ({username})"

        # Определяем тип сообщения и отправляем в канал с кнопкой
        if message.text:
            sent = await bot.send_message(
                CHANNEL_ID,
                f"{caption_base}:\n\n{message.text}",
                reply_markup=get_reply_keyboard(user.id)
            )
        elif message.photo:
            photo = message.photo[-1]
            caption = f"{caption_base} 📸"
            if message.caption:
                caption += f"\n\n{message.caption}"
            sent = await bot.send_photo(
                CHANNEL_ID, photo.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.video:
            caption = f"{caption_base} 🎥"
            if message.caption:
                caption += f"\n\n{message.caption}"
            sent = await bot.send_video(
                CHANNEL_ID, message.video.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.document:
            caption = f"{caption_base} 📄"
            if message.caption:
                caption += f"\n\n{message.caption}"
            sent = await bot.send_document(
                CHANNEL_ID, message.document.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.voice:
            caption = f"{caption_base} 🎤 (голосовое)"
            sent = await bot.send_voice(
                CHANNEL_ID, message.voice.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.audio:
            caption = f"{caption_base} 🎵 (аудио)"
            sent = await bot.send_audio(
                CHANNEL_ID, message.audio.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.sticker:
            # Стикер отправляем отдельно, потом текстовое уведомление
            await bot.send_sticker(CHANNEL_ID, message.sticker.file_id)
            sent = await bot.send_message(
                CHANNEL_ID, f"{caption_base} (стикер)",
                reply_markup=get_reply_keyboard(user.id)
            )
        else:
            await message.answer("❌ Этот тип сообщений не поддерживается.")
            return

        # Сохраняем связь: message_id в канале -> user_id
        if sent:
            message_owners[sent.message_id] = user.id

        await message.answer("✅ Сообщение отправлено в канал!")

    except Exception as e:
        logger.exception("Ошибка при отправке в канал")
        await message.answer("❌ Произошла ошибка, попробуйте позже.")

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
    # Запускаем веб-сервер для health check
    asyncio.create_task(start_web_server())
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан! Укажите переменную окружения.")
        exit(1)
    asyncio.run(main())