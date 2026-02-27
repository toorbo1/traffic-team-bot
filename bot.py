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
CHANNEL_ID = os.getenv("CHANNEL_ID", "@rethewf")

# Если CHANNEL_ID указан как @username, сохраняем также имя без @ для сравнения
CHANNEL_USERNAME = CHANNEL_ID[1:] if CHANNEL_ID.startswith('@') else None
# ========================================================

# Логирование с уровнем DEBUG для большей информативности
logging.basicConfig(
    level=logging.DEBUG,
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
    logger.info(f"Команда /start от пользователя {message.from_user.id}")
    await message.answer(
        "👋 Привет! Я бот-посредник для связи с каналом.\n"
        "Напишите любое сообщение, и оно будет отправлено в канал.\n"
        "Ответы из канала вы получите здесь."
    )

# ========== ОБРАБОТКА НАЖАТИЯ КНОПКИ "ОТВЕТИТЬ" ==========
@dp.callback_query(lambda c: c.data and c.data.startswith('reply:'))
async def process_reply_callback(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"🔘 ПОЛУЧЕН КОЛЛБЭК: {callback.data}")
    logger.info(f"🔘 От пользователя: {callback.from_user.id} ({callback.from_user.username})")
    logger.info(f"🔘 В чате: {callback.message.chat.id} ({callback.message.chat.type})")
    
    await callback.answer()
    
    try:
        _, user_id_str = callback.data.split(':')
        target_user_id = int(user_id_str)
        logger.info(f"🎯 Целевой пользователь ID: {target_user_id}")
        
        # Устанавливаем состояние ожидания ответа
        await state.set_state(AdminReply.waiting_for_reply)
        await state.update_data(target_user_id=target_user_id)
        logger.info(f"✅ Установлено состояние waiting_for_reply для админа {callback.from_user.id}")
        
        # Отправляем сообщение админу с просьбой написать ответ
        await callback.message.reply(f"✍️ Напишите ответ для пользователя (ID: {target_user_id})")
        logger.info(f"📤 Отправлен запрос ответа админу")
        
    except Exception as e:
        logger.exception(f"❌ Ошибка в обработке коллбэка: {e}")
        await callback.message.reply("❌ Произошла ошибка при обработке запроса")

# ========== ОБРАБОТЧИК ОТВЕТОВ АДМИНИСТРАТОРА (ИЗ КАНАЛА) ==========
@dp.message(AdminReply.waiting_for_reply)
async def send_admin_reply(message: types.Message, state: FSMContext):
    logger.info(f"📩 ПОЛУЧЕНО СООБЩЕНИЕ ОТ АДМИНА В СОСТОЯНИИ")
    logger.info(f"📩 От пользователя: {message.from_user.id} ({message.from_user.username})")
    logger.info(f"📩 В чате: {message.chat.id} ({message.chat.type})")
    logger.info(f"📩 Текст: {message.text}")
    
    # Получаем данные из состояния
    data = await state.get_data()
    logger.info(f"📦 Данные состояния: {data}")
    
    target_user_id = data.get('target_user_id')
    if not target_user_id:
        logger.warning("❌ target_user_id не найден в состоянии")
        await message.reply("❌ Ошибка: получатель не найден. Попробуйте нажать кнопку заново.")
        await state.clear()
        return

    # Проверяем, что сообщение действительно от админа (опционально)
    # Можно добавить проверку на ID администратора

    try:
        # Отправляем ответ пользователю
        logger.info(f"📤 Попытка отправить ответ пользователю {target_user_id}")
        
        await bot.send_message(
            target_user_id,
            f"✉️ **Ответ от администратора канала:**\n\n{message.text}"
        )
        
        logger.info(f"✅ ОТВЕТ УСПЕШНО ОТПРАВЛЕН пользователю {target_user_id}")
        
        # Подтверждаем админу
        await message.reply("✅ Ответ успешно отправлен пользователю!")
        
    except Exception as e:
        logger.exception(f"❌ ОШИБКА при отправке ответа пользователю {target_user_id}")
        
        error_message = str(e)
        if "bot was blocked by the user" in error_message:
            await message.reply("❌ Не удалось отправить ответ: пользователь заблокировал бота.")
        elif "chat not found" in error_message:
            await message.reply("❌ Не удалось отправить ответ: пользователь не найден (возможно, удалил аккаунт).")
        else:
            await message.reply(f"❌ Не удалось отправить ответ: {error_message[:100]}")
    
    finally:
        # Очищаем состояние
        await state.clear()
        logger.info(f"🧹 Состояние очищено для админа {message.from_user.id}")

# ========== ОБЩИЙ ОБРАБОТЧИК СООБЩЕНИЙ (ПЕРЕСЫЛКА В КАНАЛ) ==========
@dp.message()
async def forward_to_channel(message: types.Message):
    logger.info(f"📨 ОБЩИЙ ОБРАБОТЧИК: сообщение от {message.from_user.id if message.from_user else '?'}")
    logger.info(f"📨 Тип чата: {message.chat.type}, ID чата: {message.chat.id}")
    
    # Проверяем, не сообщение ли это из канала
    if is_channel(message.chat):
        logger.debug(f"🚫 Сообщение из канала проигнорировано")
        return

    # Игнорируем служебные сообщения (например, от самого бота)
    if message.from_user and message.from_user.is_bot:
        logger.debug(f"🚫 Сообщение от бота проигнорировано")
        return

    try:
        user = message.from_user
        username = f"@{user.username}" if user.username else "нет username"
        caption_base = f"📨 Сообщение от {user.full_name} ({username})"
        
        logger.info(f"👤 Пользователь: ID={user.id}, имя={user.full_name}, username={username}")

        # Определяем тип сообщения и отправляем в канал с кнопкой
        if message.text:
            logger.info(f"📝 Тип: текст, длина: {len(message.text)}")
            sent = await bot.send_message(
                CHANNEL_ID,
                f"{caption_base}:\n\n{message.text}",
                reply_markup=get_reply_keyboard(user.id)
            )
        elif message.photo:
            logger.info(f"🖼️ Тип: фото, file_id: {message.photo[-1].file_id}")
            photo = message.photo[-1]
            caption = f"{caption_base} 📸"
            if message.caption:
                caption += f"\n\n{message.caption}"
            sent = await bot.send_photo(
                CHANNEL_ID, photo.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.video:
            logger.info(f"🎥 Тип: видео, file_id: {message.video.file_id}")
            caption = f"{caption_base} 🎥"
            if message.caption:
                caption += f"\n\n{message.caption}"
            sent = await bot.send_video(
                CHANNEL_ID, message.video.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.document:
            logger.info(f"📄 Тип: документ, file_id: {message.document.file_id}")
            caption = f"{caption_base} 📄"
            if message.caption:
                caption += f"\n\n{message.caption}"
            sent = await bot.send_document(
                CHANNEL_ID, message.document.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.voice:
            logger.info(f"🎤 Тип: голосовое, file_id: {message.voice.file_id}")
            caption = f"{caption_base} 🎤 (голосовое)"
            sent = await bot.send_voice(
                CHANNEL_ID, message.voice.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.audio:
            logger.info(f"🎵 Тип: аудио, file_id: {message.audio.file_id}")
            caption = f"{caption_base} 🎵 (аудио)"
            sent = await bot.send_audio(
                CHANNEL_ID, message.audio.file_id,
                caption=caption, reply_markup=get_reply_keyboard(user.id)
            )
        elif message.sticker:
            logger.info(f"😊 Тип: стикер, file_id: {message.sticker.file_id}")
            # Стикер отправляем отдельно, потом текстовое уведомление
            await bot.send_sticker(CHANNEL_ID, message.sticker.file_id)
            sent = await bot.send_message(
                CHANNEL_ID, f"{caption_base} (стикер)",
                reply_markup=get_reply_keyboard(user.id)
            )
        else:
            logger.warning(f"❓ Неподдерживаемый тип сообщения: {message.content_type}")
            await message.answer("❌ Этот тип сообщений не поддерживается.")
            return

        # Сохраняем связь: message_id в канале -> user_id
        if sent:
            message_owners[sent.message_id] = user.id
            logger.info(f"💾 Сохранена связь: сообщение {sent.message_id} в канале -> пользователь {user.id}")

        await message.answer("✅ Сообщение отправлено в канал!")
        logger.info(f"✅ Сообщение успешно отправлено в канал")

    except Exception as e:
        logger.exception("❌ Ошибка при отправке в канал")
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
    logger.info("🚀 Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не задан! Укажите переменную окружения.")
        exit(1)
    
    logger.info(f"✅ BOT_TOKEN загружен")
    logger.info(f"✅ CHANNEL_ID: {CHANNEL_ID}")
    if CHANNEL_USERNAME:
        logger.info(f"✅ CHANNEL_USERNAME: {CHANNEL_USERNAME}")
    
    asyncio.run(main())