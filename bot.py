import logging
import json
import hashlib
import secrets
from datetime import datetime, timedelta
import os
import asyncio
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ========== ИМПОРТ БАЗЫ ДАННЫХ ==========
from database import (
    PostgresDB, UserManager, TaskManager, AdminManager, 
    PendingLinksManager, TrackingLinksManager, MAIN_ADMIN_ID
)

# ========== КОНФИГУРАЦИЯ ==========
# Берем настройки из переменных окружения
BOT_TOKEN = os.environ.get('8719482043:AAE6posoOel7sOz8cou-Q2KWkPphuXduosw')  # УБРАЛИ ДЕФОЛТНЫЙ ТОКЕН!
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен в переменных окружения!")

TASK_NOTIFICATION_GROUP = os.environ.get('TASK_NOTIFICATION_GROUP', "@wedferfwewf")
REPORT_GROUP = os.environ.get('REPORT_GROUP', "@ertghpjoterg")

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== ОСНОВНЫЕ ФУНКЦИИ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    
    # Создаем или получаем пользователя в базе данных
    await UserManager.get_or_create_user(
        user.id, 
        user.username or "", 
        user.first_name or ""
    )
    
    if context.args and len(context.args) > 0:
        link_id = context.args[0]
        await handle_tracking_link(update, context, link_id)
        return
    
    welcome_text = (
        "🚀 *Приветствуем, будущий трафик-менеджер!*\n\n"
        "Переходи по ссылкам — мы покажем и научим, "
        "как действительно зарабатывать на трафике.\n\n"
        "❗️ Мы работаем *ТОЛЬКО* с белым трафиком — честно, стабильно и без рисков.\n\n"
        "*Вступая в нашу команду, ты получаешь:*\n"
        "✅ готового бота для работы\n"
        "✅ подробный и понятный мануал\n"
        "✅ поддержку кураторов\n"
        "✅ работу бок о бок с профессионалами\n"
        "✅ практику, опыт и рост с первого дня\n\n"
        "*Если хочешь развиваться и зарабатывать — тебе точно к нам!*"
    )
    
    keyboard = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("📋 Доступные задания", callback_data="available_tasks")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    
    if await AdminManager.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_tracking_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link_id: str):
    """Обработка переходов по отслеживающим ссылкам"""
    # Получаем информацию о ссылке
    link_data = await TrackingLinksManager.get_link(link_id)
    
    if not link_data:
        await update.message.reply_text("Ссылка не найдена или устарела.")
        return
    
    # Увеличиваем счетчик кликов
    await TrackingLinksManager.increment_clicks(link_id)
    
    # Получаем информацию о задании
    task = await TaskManager.get_task(link_data["task_id"])
    
    if task:
        await update.message.reply_text(
            f"🎯 *Отслеживание включено!*\n\n"
            f"*Задание:* {task['title']}\n"
            f"*Описание:* {task['description']}\n\n"
            f"Теперь ваши переходы по этой ссылке отслеживаются.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("🎯 Отслеживание включено!")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "profile":
        await show_profile(query, context)
    elif data == "available_tasks":
        await show_available_tasks(query, context)
    elif data == "my_stats":
        await show_my_stats(query, context)
    elif data == "help":
        await show_help(query, context)
    elif data == "admin_panel":
        await show_admin_panel(query, context)
    elif data == "my_active_tasks":
        await show_my_active_tasks(query, context)
    elif data == "my_completed_tasks":
        await show_my_completed_tasks(query, context)
    
    elif data.startswith("view_task_"):
        task_id = data.replace("view_task_", "")
        await view_task_details(query, context, task_id)
    elif data.startswith("take_task_"):
        task_id = data.replace("take_task_", "")
        await take_task(query, context, task_id)
    elif data.startswith("complete_task_"):
        task_id = data.replace("complete_task_", "")
        await complete_task_dialog(query, context, task_id)
    
    elif data == "admin_manage_admins":
        await manage_admins(query, context)
    elif data == "admin_create_task":
        await create_task_dialog(query, context)
    elif data == "admin_view_stats":
        await view_admin_stats(query, context)
    elif data == "admin_manage_blocks":
        await manage_blocks(query, context)
    elif data == "admin_add_admin":
        await add_admin_dialog(query, context)
    elif data == "admin_pending_links":
        await show_pending_links(query, context)
    elif data.startswith("admin_remove_"):
        admin_id = int(data.replace("admin_remove_", ""))
        await remove_admin(query, context, admin_id)
    elif data.startswith("admin_set_link_"):
        task_id = data.replace("admin_set_link_", "")
        await set_work_link_dialog(query, context, task_id)
    elif data.startswith("admin_skip_link_"):
        task_id = data.replace("admin_skip_link_", "")
        await skip_work_link(query, context, task_id)
    elif data == "back_to_admin":
        await show_admin_panel(query, context)
    elif data == "back_to_main":
        await back_to_main_menu(query, context)
    
    elif data.startswith("task_type_"):
        await handle_task_type_selection(query, context, data)
    
    elif data == "admin_manage_tasks":
        await manage_tasks_menu(query, context)
    elif data == "edit_welcome":
        await edit_welcome_message(query, context)
    elif data == "notification_settings":
        await notification_settings_menu(query, context)
    elif data == "link_templates":
        await link_templates_menu(query, context)
    elif data == "view_all_tasks":
        await view_all_tasks_admin(query, context)

async def back_to_main_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться в главное меню"""
    user = query.from_user
    
    welcome_text = "🚀 *Главное меню*\n\nВыберите раздел для работы:"
    
    keyboard = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("📋 Доступные задания", callback_data="available_tasks")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    
    if await AdminManager.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_task_type_selection(query, context, data):
    """Обработка выбора типа задания"""
    task_type_map = {
        "task_type_subscribers": "Привлечение подписчиков",
        "task_type_ad": "Рекламный пост",
        "task_type_clicks": "Переходы по ссылке",
        "task_type_install": "Установка приложения"
    }
    
    task_type = task_type_map.get(data, "Другое")
    
    if "creating_task" in context.user_data:
        context.user_data["creating_task"]["data"]["type"] = task_type
        context.user_data["creating_task"]["step"] = "target"
        
        await query.edit_message_text(
            "*Шаг 4 из 6*\n"
            "Введите цель (количество/результат):\n\n"
            "*Пример:* 1000 подписчиков, 500 переходов, 100 установок",
            parse_mode='Markdown'
        )

async def show_profile(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать профиль пользователя"""
    user = query.from_user
    stats = await UserManager.get_user_stats(user.id)
    
    profile_text = (
        f"👤 *Ваш профиль*\n\n"
        f"*ID:* {user.id}\n"
        f"*Имя:* {user.first_name}\n"
        f"*Username:* @{user.username if user.username else 'не указан'}\n\n"
        f"*Статистика:*\n"
        f"✅ Выполнено заданий: {stats['completed_count']}\n"
        f"📊 Активных заданий: {stats['active_count']}\n"
        f"💰 Заработано всего: {stats['total_earned']} руб.\n"
        f"⭐ Рейтинг: {stats['rating']}/100\n\n"
        f"*Статус:* {'👑 Администратор' if await AdminManager.is_admin(user.id) else '👤 Исполнитель'}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📋 Мои активные задания", callback_data="my_active_tasks")],
        [InlineKeyboardButton("📋 Мои выполненные", callback_data="my_completed_tasks")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_my_active_tasks(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать активные задания пользователя"""
    user_id = query.from_user.id
    
    # Получаем активные задания пользователя
    pool = await PostgresDB.init_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT t.* FROM tasks t
            JOIN user_tasks ut ON t.task_id = ut.task_id
            WHERE ut.user_id = $1 AND ut.status = 'active'
        ''', user_id)
    
    if not rows:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="profile")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 У вас нет активных заданий.",
            reply_markup=reply_markup
        )
        return
    
    tasks_text = "📋 *Ваши активные задания:*\n\n"
    keyboard = []
    
    for row in rows:
        task = dict(row)
        tasks_text += f"• {task['title']} - {task['reward']} руб.\n"
        keyboard.append([InlineKeyboardButton(f"✅ Завершить: {task['title'][:20]}", callback_data=f"complete_task_{task['task_id']}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="profile")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(tasks_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_my_completed_tasks(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать выполненные задания пользователя"""
    user_id = query.from_user.id
    
    # Получаем выполненные задания пользователя
    pool = await PostgresDB.init_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT t.* FROM tasks t
            JOIN user_tasks ut ON t.task_id = ut.task_id
            WHERE ut.user_id = $1 AND ut.status = 'completed'
            ORDER BY ut.completed_date DESC
            LIMIT 10
        ''', user_id)
    
    if not rows:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="profile")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 У вас нет выполненных заданий.",
            reply_markup=reply_markup
        )
        return
    
    tasks_text = "📋 *Ваши последние выполненные задания:*\n\n"
    
    for row in rows:
        task = dict(row)
        tasks_text += f"✅ {task['title']} - {task['reward']} руб.\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="profile")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(tasks_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_available_tasks(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать доступные задания"""
    tasks = await TaskManager.get_available_tasks()
    
    if not tasks:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 На данный момент нет доступных заданий.\n"
            "Загляните позже!",
            reply_markup=reply_markup
        )
        return
    
    keyboard = []
    for task in tasks[:10]:
        btn_text = f"{task['title']} - {task['reward']} руб."
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_task_{task['task_id']}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📋 *Доступные задания:*\n\n"
        "Выберите задание для просмотра деталей:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def view_task_details(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Показать детали задания"""
    task = await TaskManager.get_task(task_id)
    
    if not task:
        await query.answer("Задание не найдено!", show_alert=True)
        return
    
    task_text = (
        f"🎯 *{task['title']}*\n\n"
        f"*Описание:* {task['description']}\n"
        f"*Тип:* {task['type']}\n"
        f"*Цель:* {task['target']}\n"
        f"*Вознаграждение:* {task['reward']} руб.\n"
        f"*Требования:* {task['requirements']}\n\n"
        f"*Статус:* {'✅ Доступно' if task.get('available') else '❌ Занято'}"
    )
    
    keyboard = []
    
    if task.get('available') and not task.get('taken_by'):
        keyboard.append([InlineKeyboardButton("✅ Взять задание", callback_data=f"take_task_{task_id}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад к заданиям", callback_data="available_tasks")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(task_text, reply_markup=reply_markup, parse_mode='Markdown')

async def take_task(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Взять задание"""
    user = query.from_user
    task = await TaskManager.get_task(task_id)
    
    if not task:
        await query.answer("Задание не найдено!", show_alert=True)
        return
    
    # Назначаем задание пользователю
    if await TaskManager.assign_task(task_id, user.id):
        # Генерируем отслеживающую ссылку
        tracking_link = await TaskManager.generate_tracking_link(user.id, task_id)
        
        # Сохраняем информацию о ожидающей ссылке
        await PendingLinksManager.save_pending(task_id, {
            'user_id': user.id,
            'username': user.username or f"id{user.id}",
            'task_title': task['title'],
            'message_sent': datetime.now(),
            'tracking_link': tracking_link
        })
        
        notification_text = (
            f"🚀 *НОВОЕ ЗАДАНИЕ ВЗЯТО!*\n\n"
            f"*Исполнитель:* {user.first_name} (@{user.username if user.username else 'без username'})\n"
            f"*Задание:* {task['title']}\n"
            f"*Цель:* {task['target']}\n"
            f"*Вознаграждение:* {task['reward']} руб.\n\n"
            f"👑 *Администратору:*\n"
            f"Выдайте исполнителю рабочую ссылку:\n"
            f"`{tracking_link}`\n\n"
            f"Используйте кнопки ниже для управления:"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔗 Отправить ссылку", callback_data=f"admin_set_link_{task_id}")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data=f"admin_skip_link_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await context.bot.send_message(
                chat_id=TASK_NOTIFICATION_GROUP,
                text=notification_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в группу: {e}")
        
        success_text = (
            f"✅ *Задание успешно взято!*\n\n"
            f"*{task['title']}*\n\n"
            f"Ожидайте, когда администратор выдаст вам "
            f"специальную ссылку для работы в группе {TASK_NOTIFICATION_GROUP}\n\n"
            f"Как получите ссылку — начинайте работу!\n"
            f"После выполнения не забудьте отправить отчет."
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 Мои задания", callback_data="my_active_tasks")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await query.answer("Не удалось взять задание. Возможно, оно уже занято.", show_alert=True)

async def complete_task_dialog(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Диалог завершения задания"""
    context.user_data["waiting_for_proof"] = task_id
    
    await query.edit_message_text(
        "📝 *Отправка отчета*\n\n"
        "Пожалуйста, отправьте доказательство выполнения задания:\n"
        "• Ссылку на результат\n"
        "• Скриншот\n"
        "• Текстовый отчет\n\n"
        "Отправьте одним сообщением.",
        parse_mode='Markdown'
    )

async def handle_proof_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка доказательств выполнения задания"""
    user_id = update.effective_user.id
    proof_text = update.message.text or update.message.caption or "Доказательство предоставлено"
    
    task_id = context.user_data.get("waiting_for_proof")
    
    if not task_id:
        return
    
    if await TaskManager.complete_task(task_id, user_id, proof_text):
        task = await TaskManager.get_task(task_id)
        
        report_text = (
            f"📊 *ЕЖЕДНЕВНЫЙ ОТЧЕТ*\n\n"
            f"*Исполнитель:* {update.effective_user.first_name}\n"
            f"*Задание:* {task['title']}\n"
            f"*Результат:* Выполнено ✅\n"
            f"*Вознаграждение:* {task['reward']} руб.\n"
            f"*Доказательство:* {proof_text[:200]}..."
        )
        
        try:
            await context.bot.send_message(
                chat_id=REPORT_GROUP,
                text=report_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки отчета: {e}")
        
        await update.message.reply_text(
            "✅ *Отчет успешно отправлен!*\n\n"
            "Ваше задание отмечено как выполненное.\n"
            "Вознаграждение будет начислено после проверки администратором.",
            parse_mode='Markdown'
        )
        
        if "waiting_for_proof" in context.user_data:
            del context.user_data["waiting_for_proof"]
    else:
        await update.message.reply_text("❌ Не удалось отправить отчет. Обратитесь к администратору.")

async def show_my_stats(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя"""
    user = query.from_user
    stats = await UserManager.get_user_stats(user.id)
    
    stats_text = (
        f"📊 *Ваша статистика*\n\n"
        f"✅ *Выполнено заданий:* {stats['completed_count']}\n"
        f"🎯 *Активных заданий:* {stats['active_count']}\n"
        f"💰 *Всего заработано:* {stats['total_earned']} руб.\n"
        f"⭐ *Рейтинг исполнителя:* {stats['rating']}/100\n\n"
        f"*Эффективность:* {'🔥 Отличная' if stats['rating'] > 70 else '👍 Хорошая' if stats['rating'] > 40 else '💪 Набираете опыт'}\n\n"
        f"Продолжайте в том же духе! Каждое выполненное задание повышает ваш рейтинг."
    )
    
    keyboard = [
        [InlineKeyboardButton("📋 Мои задания", callback_data="my_active_tasks")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_help(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать справку"""
    help_text = (
        "❓ *Помощь и поддержка*\n\n"
        "*Как работать с ботом:*\n"
        "1. 👤 *Профиль* — ваша статистика и рейтинг\n"
        "2. 📋 *Доступные задания* — выбирайте задания для выполнения\n"
        "3. ✅ *Взятие задания* — после взятия ожидайте ссылку от админа\n"
        "4. 📊 *Отчет* — после выполнения отправьте доказательство\n"
        "5. 💰 *Вывод средств* — доступен от 500 руб. (обращаться к админу)\n\n"
        "*Важные моменты:*\n"
        "• Работаем только с белым трафиком\n"
        "• Качество выполнения влияет на рейтинг\n"
        "• Регулярные исполнители получают более выгодные задания\n"
        "• Все вопросы к администратору\n\n"
        "*Контакты поддержки:*\n"
        "👑 Главный администратор: @main_admin"
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

# ========== АДМИН-ПАНЕЛЬ ==========
async def show_admin_panel(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать админ-панель"""
    user = query.from_user
    
    if not await AdminManager.is_admin(user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    is_main = await AdminManager.is_main_admin(user.id)
    
    # Получаем количество ожидающих ссылок
    pending_links = await PendingLinksManager.get_all_pending()
    pending_count = len(pending_links)
    
    admin_text = (
        f"👑 *Панель администратора*\n\n"
        f"*Ваш статус:* {'Главный администратор' if is_main else 'Администратор'}\n"
        f"*ID:* {user.id}\n"
        f"*Дата входа:* {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"*Ожидает ссылок:* {pending_count}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📊 Общая статистика", callback_data="admin_view_stats")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="admin_create_task")],
        [InlineKeyboardButton("📁 Управление заданиями", callback_data="admin_manage_tasks")],
    ]
    
    if pending_count > 0:
        keyboard.append([InlineKeyboardButton(f"🔗 Выдать ссылки ({pending_count})", callback_data="admin_pending_links")])
    
    if is_main:
        keyboard.append([InlineKeyboardButton("👥 Управление админами", callback_data="admin_manage_admins")])
    
    keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_pending_links(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать ожидающие ссылки"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    pending_links = await PendingLinksManager.get_all_pending()
    
    if not pending_links:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔗 *Нет ожидающих ссылок*\n\n"
            "Все ссылки выданы.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    text = "🔗 *Ожидают выдачи ссылок:*\n\n"
    keyboard = []
    
    for i, pending in enumerate(pending_links[:5], 1):
        text += f"{i}. *{pending['task_title']}*\n"
        text += f"   Исполнитель: {pending['username']}\n"
        text += f"   ID: {pending['user_id']}\n"
        text += f"   Ссылка: `{pending['tracking_link']}`\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"✅ {pending['task_title'][:20]} - отметить выдано", 
            callback_data=f"admin_set_link_{pending['task_id']}"
        )])
    
    if len(pending_links) > 5:
        text += f"... и еще {len(pending_links) - 5} заданий\n\n"
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def set_work_link_dialog(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Диалог установки рабочей ссылки"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    pending = await PendingLinksManager.get_pending(task_id)
    
    if not pending:
        await query.answer("Задание не найдено в списке ожидающих!", show_alert=True)
        return
    
    context.user_data["setting_link_for"] = task_id
    
    await query.edit_message_text(
        f"🔗 *Установка рабочей ссылки*\n\n"
        f"*Задание:* {pending['task_title']}\n"
        f"*Исполнитель:* {pending['username']}\n"
        f"*Отслеживающая ссылка:*\n"
        f"`{pending['tracking_link']}`\n\n"
        f"Отправьте рабочую ссылку для этого задания.\n"
        f"Или нажмите кнопку 'Пропустить'.",
        parse_mode='Markdown'
    )
    
    keyboard = [[InlineKeyboardButton("⏭ Пропустить", callback_data=f"admin_skip_link_{task_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_reply_markup(reply_markup=reply_markup)

async def skip_work_link(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Пропустить установку рабочей ссылки"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await PendingLinksManager.delete_pending(task_id)
    await query.answer("✅ Задание отмечено как выданное", show_alert=True)
    await show_pending_links(query, context)

async def handle_work_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка рабочей ссылки от админа"""
    user_id = update.effective_user.id
    
    if not await AdminManager.is_admin(user_id):
        return
    
    task_id = context.user_data.get("setting_link_for")
    if not task_id:
        return
    
    work_link = update.message.text
    
    # Сохраняем рабочую ссылку
    await TaskManager.set_work_link(task_id, work_link)
    
    # Получаем информацию о задании и исполнителе
    pending = await PendingLinksManager.get_pending(task_id)
    task = await TaskManager.get_task(task_id)
    
    if pending and task:
        # Отправляем ссылку исполнителю
        try:
            await context.bot.send_message(
                chat_id=pending['user_id'],
                text=(
                    f"🔗 *Рабочая ссылка готова!*\n\n"
                    f"*Задание:* {task['title']}\n"
                    f"*Ваша ссылка:*\n"
                    f"{work_link}\n\n"
                    f"Используйте эту ссылку для выполнения задания.\n"
                    f"После выполнения отправьте отчет командой /start и выберите задание."
                ),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки ссылки пользователю: {e}")
        
        # Удаляем из ожидающих
        await PendingLinksManager.delete_pending(task_id)
        
        await update.message.reply_text(
            f"✅ *Ссылка отправлена!*\n\n"
            f"Задание: {task['title']}\n"
            f"Исполнитель: {pending['username']}\n"
            f"Ссылка: {work_link}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Информация о задании не найдена.")
    
    del context.user_data["setting_link_for"]

async def manage_admins(query, context: ContextTypes.DEFAULT_TYPE):
    """Управление администраторами"""
    if not await AdminManager.is_main_admin(query.from_user.id):
        await query.answer("Только главный админ может управлять администраторами!", show_alert=True)
        return
    
    admins = await AdminManager.get_all_admins()
    
    admin_list = "👥 *Список администраторов:*\n\n"
    admin_list += f"👑 Главный администратор (ID: {MAIN_ADMIN_ID})\n\n"
    
    for admin in admins:
        admin_list += f"👤 Администратор (ID: {admin['user_id']})\n"
        admin_list += f"   Username: {admin.get('username', 'не указан')}\n"
        admin_list += f"   Добавлен: {admin['added_date'].strftime('%d.%m.%Y')}\n\n"
    
    keyboard = []
    
    for admin in admins:
        btn_text = f"❌ Удалить ID {admin['user_id']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_remove_{admin['user_id']}")])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_admin")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(admin_list, reply_markup=reply_markup, parse_mode='Markdown')

async def add_admin_dialog(query, context: ContextTypes.DEFAULT_TYPE):
    """Диалог добавления администратора"""
    if not await AdminManager.is_main_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    context.user_data["waiting_for_admin_id"] = True
    
    await query.edit_message_text(
        "👥 *Добавление администратора*\n\n"
        "Отправьте мне ID пользователя, которого хотите сделать администратором.\n\n"
        "*Как получить ID пользователя:*\n"
        "1. Попросите пользователя написать @userinfobot\n"
        "2. Или перешлите мне любое сообщение от этого пользователя\n\n"
        "Отправьте ID или перешлите сообщение:",
        parse_mode='Markdown'
    )

async def handle_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ID нового администратора"""
    user_id = update.effective_user.id
    
    if not await AdminManager.is_main_admin(user_id):
        return
    
    if not context.user_data.get("waiting_for_admin_id"):
        return
    
    target_user_id = None
    target_username = ""
    
    if update.message.forward_from:
        target_user_id = update.message.forward_from.id
        target_username = update.message.forward_from.username or update.message.forward_from.first_name
    elif update.message.text and update.message.text.isdigit():
        target_user_id = int(update.message.text)
        target_username = "Новый админ"
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user_id = update.message.reply_to_message.from_user.id
        target_username = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
    
    if target_user_id:
        await AdminManager.add_admin(target_user_id, target_username, user_id)
        
        del context.user_data["waiting_for_admin_id"]
        
        success_text = (
            f"✅ *Администратор добавлен!*\n\n"
            f"*ID:* {target_user_id}\n"
            f"*Имя:* {target_username}\n"
            f"*Добавил:* {update.effective_user.first_name}\n\n"
            f"Пользователь теперь имеет доступ к админ-панели."
        )
        
        keyboard = [[InlineKeyboardButton("◀️ К списку админов", callback_data="admin_manage_admins")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    f"🎉 *Поздравляем!*\n\n"
                    f"Вас назначили администратором в боте Traffic Team!\n\n"
                    f"Теперь у вас есть доступ к админ-панели. Используйте команду /start для начала работы."
                ),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить нового админа: {e}")
    else:
        await update.message.reply_text(
            "❌ Не удалось распознать ID пользователя.\n"
            "Пожалуйста, отправьте числовой ID или перешлите сообщение от пользователя."
        )

async def remove_admin(query, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    """Удаление администратора"""
    if not await AdminManager.is_main_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    if admin_id == MAIN_ADMIN_ID:
        await query.answer("Нельзя удалить главного администратора!", show_alert=True)
        return
    
    if await AdminManager.remove_admin(admin_id):
        await query.answer("✅ Администратор удален!", show_alert=True)
        await manage_admins(query, context)
    else:
        await query.answer("❌ Не удалось удалить администратора", show_alert=True)

async def create_task_dialog(query, context: ContextTypes.DEFAULT_TYPE):
    """Диалог создания задания"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    context.user_data["creating_task"] = {
        "step": "title",
        "data": {}
    }
    
    await query.edit_message_text(
        "➕ *Создание нового задания*\n\n"
        "*Шаг 1 из 6*\n"
        "Введите заголовок задания:\n\n"
        "*Пример:* Привлечение подписчиков в Telegram-канал",
        parse_mode='Markdown'
    )

async def handle_task_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка создания задания по шагам"""
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь админом
    if not await AdminManager.is_admin(user_id):
        return
    
    # Проверяем, находится ли пользователь в процессе создания задания
    if "creating_task" not in context.user_data:
        return
    
    task_data = context.user_data["creating_task"]
    step = task_data["step"]
    text = update.message.text
    
    logger.info(f"Создание задания: шаг {step}, текст: {text}")
    
    if step == "title":
        task_data["data"]["title"] = text
        task_data["step"] = "description"
        
        await update.message.reply_text(
            "*Шаг 2 из 6*\n"
            "Введите подробное описание задания:\n\n"
            "*Пример:* Необходимо привлечь 1000 реальных подписчиков в канал @example. "
            "Подписчики должны быть активными, не ботами.",
            parse_mode='Markdown'
        )
    
    elif step == "description":
        task_data["data"]["description"] = text
        task_data["step"] = "type"
        
        keyboard = [
            [InlineKeyboardButton("👥 Привлечение подписчиков", callback_data="task_type_subscribers")],
            [InlineKeyboardButton("📢 Рекламный пост", callback_data="task_type_ad")],
            [InlineKeyboardButton("🔗 Переходы по ссылке", callback_data="task_type_clicks")],
            [InlineKeyboardButton("📱 Установка приложения", callback_data="task_type_install")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "*Шаг 3 из 6*\n"
            "Выберите тип задания:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif step == "target":
        task_data["data"]["target"] = text
        task_data["step"] = "reward"
        
        await update.message.reply_text(
            "*Шаг 5 из 6*\n"
            "Введите вознаграждение (в рублях):\n\n"
            "*Пример:* 1500",
            parse_mode='Markdown'
        )
    
    elif step == "reward":
        try:
            reward = float(text)
            task_data["data"]["reward"] = reward
            task_data["step"] = "requirements"
            
            await update.message.reply_text(
                "*Шаг 6 из 6*\n"
                "Введите дополнительные требования (или '-' если нет):\n\n"
                "*Пример:* Только реальные пользователи, без накрутки",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, введите число (например: 1500)")
    
    elif step == "requirements":
        task_data["data"]["requirements"] = text
        
        # Создаем задание
        task_id = await TaskManager.create_task(
            title=task_data["data"]["title"],
            description=task_data["data"]["description"],
            task_type=task_data["data"].get("type", "other"),
            target=task_data["data"]["target"],
            reward=task_data["data"]["reward"],
            created_by=user_id,
            requirements=task_data["data"]["requirements"]
        )
        
        # Очищаем состояние
        del context.user_data["creating_task"]
        
        # Сообщаем об успехе
        success_text = (
            f"✅ *Задание успешно создано!*\n\n"
            f"*ID задания:* {task_id}\n"
            f"*Название:* {task_data['data']['title']}\n"
            f"*Цель:* {task_data['data']['target']}\n"
            f"*Вознаграждение:* {task_data['data']['reward']} руб.\n\n"
            f"Задание теперь доступно для выполнения в разделе 'Доступные задания'."
        )
        
        keyboard = [[InlineKeyboardButton("➕ Создать еще", callback_data="admin_create_task")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')

async def view_admin_stats(query, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр статистики для администратора"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    pool = await PostgresDB.init_pool()
    async with pool.acquire() as conn:
        # Общая статистика
        total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
        total_tasks = await conn.fetchval('SELECT COUNT(*) FROM tasks')
        active_tasks = await conn.fetchval('SELECT COUNT(*) FROM tasks WHERE active = true AND taken_by IS NOT NULL')
        completed_tasks = await conn.fetchval('SELECT COUNT(*) FROM tasks WHERE completed = true')
        total_payout = await conn.fetchval('SELECT COALESCE(SUM(reward), 0) FROM tasks WHERE completed = true')
        
        # Топ исполнителей
        top_users = await conn.fetch('''
            SELECT user_id, earned FROM users 
            WHERE earned > 0 
            ORDER BY earned DESC 
            LIMIT 5
        ''')
    
    stats_text = (
        f"📊 *Общая статистика системы*\n\n"
        f"*Пользователей:* {total_users}\n"
        f"*Всего заданий:* {total_tasks}\n"
        f"*Активных заданий:* {active_tasks}\n"
        f"*Выполненных заданий:* {completed_tasks}\n"
        f"*Общая выплата:* {total_payout} руб.\n\n"
        f"*Топ-5 исполнителей:*\n"
    )
    
    for i, user in enumerate(top_users, 1):
        stats_text += f"{i}. ID {user['user_id']}: {user['earned']} руб.\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def view_all_tasks_admin(query, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр всех заданий для администратора"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    pool = await PostgresDB.init_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT * FROM tasks 
            ORDER BY created_date DESC 
            LIMIT 20
        ''')
    
    if not rows:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📁 *Все задания*\n\n"
            "Пока нет созданных заданий.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    tasks_text = "📁 *Все задания (последние 20):*\n\n"
    keyboard = []
    
    for row in rows:
        task = dict(row)
        status = "✅" if task.get('completed') else "🟡" if task.get('taken_by') else "🟢"
        taken_by = task.get('taken_by', '—')
        tasks_text += f"{status} {task['task_id']}: {task['title'][:30]} - {task['reward']} руб.\n"
        tasks_text += f"   Взял: {taken_by}, Выполнено: {'✅' if task.get('completed') else '❌'}\n\n"
    
    keyboard.append([InlineKeyboardButton("➕ Создать задание", callback_data="admin_create_task")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(tasks_text, reply_markup=reply_markup, parse_mode='Markdown')

async def manage_blocks(query, context: ContextTypes.DEFAULT_TYPE):
    """Управление блоками и подблоками"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    blocks_text = (
        "📁 *Управление структурой бота*\n\n"
        "*Основные блоки:*\n"
        "1. 👤 Профиль пользователя\n"
        "2. 📋 Система заданий\n"
        "3. 📊 Статистика и отчетность\n"
        "4. 👥 Админ-панель\n"
        "5. ❓ Помощь и поддержка\n\n"
        "*Подблоки заданий:*\n"
        "• Создание/редактирование заданий\n"
        "• Назначение/проверка заданий\n"
        "• Генерация отслеживающих ссылок\n"
        "• Автоматические отчеты\n\n"
        "*Настройки коммуникации:*\n"
        "• Уведомления в группы\n"
        "• Личные сообщения пользователям\n"
        "• Система эскалации проблем"
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Редактировать приветствие", callback_data="edit_welcome")],
        [InlineKeyboardButton("⚙️ Настройки уведомлений", callback_data="notification_settings")],
        [InlineKeyboardButton("🔗 Шаблоны ссылок", callback_data="link_templates")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(blocks_text, reply_markup=reply_markup, parse_mode='Markdown')

async def manage_tasks_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления заданиями"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    pool = await PostgresDB.init_pool()
    async with pool.acquire() as conn:
        total_tasks = await conn.fetchval('SELECT COUNT(*) FROM tasks')
        active_tasks = await conn.fetchval('SELECT COUNT(*) FROM tasks WHERE active = true')
        completed_tasks = await conn.fetchval('SELECT COUNT(*) FROM tasks WHERE completed = true')
        
        rows = await conn.fetch('''
            SELECT * FROM tasks 
            ORDER BY created_date DESC 
            LIMIT 5
        ''')
    
    stats_text = (
        f"📁 *Управление заданиями*\n\n"
        f"*Всего заданий:* {total_tasks}\n"
        f"*Активных:* {active_tasks}\n"
        f"*Завершенных:* {completed_tasks}\n\n"
        f"*Последние 5 заданий:*\n"
    )
    
    for i, row in enumerate(rows, 1):
        task = dict(row)
        status = "✅" if task.get('completed') else "🟡" if task.get('taken_by') else "🟢"
        stats_text += f"{i}. {status} {task['title']} - {task['reward']} руб.\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ Создать задание", callback_data="admin_create_task")],
        [InlineKeyboardButton("📋 Просмотреть все", callback_data="view_all_tasks")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def edit_welcome_message(query, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование приветственного сообщения"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await query.edit_message_text(
        "📝 *Редактирование приветственного сообщения*\n\n"
        "Эта функция в разработке.\n"
        "В будущих обновлениях вы сможете:\n"
        "• Изменять текст приветствия\n"
        "• Загружать новое видео\n"
        "• Настраивать кнопки меню\n\n"
        "Сейчас используется стандартное приветствие.",
        parse_mode='Markdown'
    )

async def notification_settings_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Настройки уведомлений"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await query.edit_message_text(
        "⚙️ *Настройки уведомлений*\n\n"
        "*Текущие настройки:*\n"
        f"• Группа уведомлений: {TASK_NOTIFICATION_GROUP}\n"
        f"• Группа отчетов: {REPORT_GROUP}\n"
        f"• Ежедневный отчет: 23:00\n\n"
        "*Что можно настроить:*\n"
        "• Изменить группы для уведомлений\n"
        "• Настроить время отчетов\n"
        "• Включить/выключить уведомления\n\n"
        "*Для изменения настроек обратитесь к разработчику.*",
        parse_mode='Markdown'
    )

async def link_templates_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Шаблоны ссылок"""
    if not await AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    await query.edit_message_text(
        "🔗 *Шаблоны отслеживающих ссылок*\n\n"
        "*Текущий шаблон:*\n"
        "`https://t.me/your_bot_username?start={link_id}`\n\n"
        "*Как это работает:*\n"
        "1. Бот генерирует уникальный {link_id}\n"
        "2. Пользователь получает ссылку с этим ID\n"
        "3. При переходе по ссылке отслеживаются клики\n"
        "4. Статистика сохраняется в базу данных\n\n"
        "*Для изменения шаблона обратитесь к разработчику.*",
        parse_mode='Markdown'
    )

# ========== УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ ==========
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный обработчик всех текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    logger.info(f"Получено сообщение от {user_id}: {text}")
    
    # Проверяем, находится ли пользователь в процессе создания задания
    if "creating_task" in context.user_data:
        logger.info(f"Пользователь {user_id} в процессе создания задания, шаг: {context.user_data['creating_task']['step']}")
        await handle_task_creation(update, context)
        return
    
    # Проверяем, ожидается ли ID админа
    if context.user_data.get("waiting_for_admin_id"):
        logger.info(f"Пользователь {user_id} отправляет ID админа")
        await handle_admin_id(update, context)
        return
    
    # Проверяем, ожидается ли доказательство выполнения задания
    if context.user_data.get("waiting_for_proof"):
        logger.info(f"Пользователь {user_id} отправляет доказательство")
        await handle_proof_message(update, context)
        return
    
    # Проверяем, ожидается ли рабочая ссылка от админа
    if context.user_data.get("setting_link_for"):
        logger.info(f"Админ {user_id} отправляет рабочую ссылку")
        await handle_work_link(update, context)
        return
    
    # Если сообщение не обработано другими обработчиками
    logger.info(f"Сообщение от {user_id} не обработано: {text}")

# ========== АВТОМАТИЧЕСКИЕ ОТЧЕТЫ ==========
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Отправка ежедневного отчета"""
    try:
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            today = datetime.now().date()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            
            # Задания выполненные сегодня
            today_tasks = await conn.fetch('''
                SELECT * FROM tasks 
                WHERE completed = true 
                AND completed_date BETWEEN $1 AND $2
            ''', today_start, today_end)
            
            today_earnings = sum(t.get('reward', 0) for t in today_tasks)
            
            # Активные пользователи
            active_users = await conn.fetchval('SELECT COUNT(DISTINCT user_id) FROM user_tasks')
            
            # Топ дня
            top_users = await conn.fetch('''
                SELECT ut.user_id, SUM(t.reward) as total
                FROM user_tasks ut
                JOIN tasks t ON ut.task_id = t.task_id
                WHERE ut.status = 'completed'
                AND ut.completed_date BETWEEN $1 AND $2
                GROUP BY ut.user_id
                ORDER BY total DESC
                LIMIT 1
            ''', today_start, today_end)
        
        report_text = (
            f"📊 *ЕЖЕДНЕВНЫЙ ОТЧЕТ {today.strftime('%d.%m.%Y')}*\n\n"
            f"*Выполнено заданий за день:* {len(today_tasks)}\n"
            f"*Выплачено за день:* {today_earnings} руб.\n"
            f"*Активных пользователей:* {active_users}\n\n"
            f"*Топ дня:*\n"
        )
        
        if top_users:
            top = top_users[0]
            report_text += f"Лучший исполнитель: ID {top['user_id']} - {top['total']} руб.\n"
        else:
            report_text += "Нет выполненных заданий за сегодня\n"
        
        report_text += "\n*Система работает стабильно. Все задачи выполнены.*"
        
        await context.bot.send_message(
            chat_id=REPORT_GROUP,
            text=report_text,
            parse_mode='Markdown'
        )
        
        logger.info(f"Ежедневный отчет отправлен в {REPORT_GROUP}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневного отчета: {e}")

async def show_admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin"""
    user = update.effective_user
    
    if not await AdminManager.is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав для использования этой команды.")
        return
    
    # Получаем количество ожидающих ссылок
    pending_links = await PendingLinksManager.get_all_pending()
    pending_count = len(pending_links)
    
    keyboard = [
        [InlineKeyboardButton("📊 Общая статистика", callback_data="admin_view_stats")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="admin_create_task")],
        [InlineKeyboardButton("📁 Управление заданиями", callback_data="admin_manage_tasks")],
    ]
    
    if pending_count > 0:
        keyboard.append([InlineKeyboardButton(f"🔗 Выдать ссылки ({pending_count})", callback_data="admin_pending_links")])
    
    if await AdminManager.is_main_admin(user.id):
        keyboard.append([InlineKeyboardButton("👥 Управление админов", callback_data="admin_manage_admins")])
    
    keyboard.append([InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👑 *Панель администратора*\n\n*Ожидает ссылок:* {pending_count}\n\nВыберите раздел для управления:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def shutdown(application):
    """Корректное завершение работы"""
    logger.info("Завершение работы бота...")
    await PostgresDB.close_pool()
    logger.info("Соединения с БД закрыты")

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
async def main_async():
    
    """Асинхронная основная функция"""
    # Инициализация базы данных
    await PostgresDB.init_db()
    logger.info("База данных инициализирована")
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", show_admin_panel_command))
    
    # Добавляем обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Добавляем УНИВЕРСАЛЬНЫЙ обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    
    # Настраиваем ежедневные отчеты
    job_queue = application.job_queue
    if job_queue:
        from datetime import time as dt_time
        job_queue.run_daily(send_daily_report, time=dt_time(hour=23, minute=0))
    
    # Добавляем обработчик завершения
    application.post_shutdown = shutdown
    
    print("=" * 50)
    print("🚀 БОТ TRAFFIC TEAM ЗАПУЩЕН С POSTGRESQL")
    print("=" * 50)
    print(f"🤖 Токен бота: {BOT_TOKEN[:10]}...")
    print(f"👑 Главный админ: {MAIN_ADMIN_ID}")
    print(f"📢 Группа уведомлений: {TASK_NOTIFICATION_GROUP}")
    print(f"📊 Группа отчетов: {REPORT_GROUP}")
    print("=" * 50)
    print("📁 Используется база данных PostgreSQL")
    print("=" * 50)
    print("Нажмите Ctrl+C для остановки")
    
    # Запускаем бота
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Основная функция запуска"""
    asyncio.run(main_async())

if __name__ == '__main__':
    main()