import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiohttp import web  # для health check на Railway

# ========== Настройки из переменных окружения ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@rethewf")  # по умолчанию ваш канал
# =======================================================

# Логирование в файл и в консоль
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

# Хранилище связей (в памяти, но можно заменить на database.py)
# Если используете PostgreSQL, раскомментируйте код в database.py и импортируйте функции
message_owners = {}

# Состояния для ответа администратора
class AdminReply(StatesGroup):
    waiting_for_reply = State()

def get_reply_keyboard(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить пользователю", callback_data=f"reply:{user_id}")]
        ]
    )

# ========== Команда /start ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот-посредник для связи с каналом.\n"
        "Напишите любое сообщение, и оно будет отправлено в канал.\n"
        "Ответы из канала вы получите здесь."
    )

# ========== Пересылка сообщений от пользователя в канал ==========
@dp.message()
async def forward_to_channel(message: types.Message):
    # Если сообщение пришло из самого канала – игнорируем (чтобы не создавать цикл)
    chat = message.chat
    if chat.id == CHANNEL_ID or (hasattr(chat, 'username') and f"@{chat.username}" == CHANNEL_ID):
        logger.info(f"Сообщение из канала проигнорировано (ID: {chat.id})")
        return 
    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        caption_base = f"📨 Сообщение от {user.full_name} ({username})"

        # Определяем тип и отправляем
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
            # Стикер отправляем отдельно + уведомление
            await bot.send_sticker(CHANNEL_ID, message.sticker.file_id)
            sent = await bot.send_message(
                CHANNEL_ID, f"{caption_base} (стикер)",
                reply_markup=get_reply_keyboard(user.id)
            )
        else:
            await message.answer("❌ Этот тип сообщений не поддерживается.")
            return

        # Сохраняем связь (в памяти или БД)
        message_owners[sent.message_id] = user.id

        await message.answer("✅ Сообщение отправлено в канал!")

    except Exception as e:
        logger.exception("Ошибка при отправке в канал")
        await message.answer("❌ Произошла ошибка, попробуйте позже.")

# ========== Обработка нажатия на кнопку "Ответить" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    _, user_id_str = callback.data.split(':')
    target_user_id = int(user_id_str)
    await state.set_state(AdminReply.waiting_for_reply)
    await state.update_data(target_user_id=target_user_id)
    await callback.message.reply(f"✍️ Напишите ответ для пользователя (ID: {target_user_id})")

# ========== Получение ответа от администратора ==========
# ========== СПЕРВА ОБРАБОТЧИК ОТВЕТОВ АДМИНИСТРАТОРА (С FSM) ==========
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
        await state.clear()
    except Exception as e:
        logger.exception("Ошибка при отправке ответа пользователю")
        await message.reply("❌ Не удалось отправить ответ.")

# ========== Простой веб-сервер для health check (Railway) ==========
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

# ========== Главная функция запуска ==========
async def main():
    # Запускаем веб-сервер (в фоне)
    asyncio.create_task(start_web_server())
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан! Укажите переменную окружения.")
        exit(1)
    asyncio.run(main())