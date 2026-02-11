import logging
import json
import hashlib
import secrets
import os
import asyncio
from datetime import datetime
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

# Импортируем менеджеры базы данных
from database import (
    PostgresDB, UserManager, TaskManager, AdminManager, 
    PendingLinksManager, TrackingLinksManager
)

# ========== КОНФИГУРАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8346231905:AAHHG3of6aAV69uYwF3e3onUjKuA0zIcZn4')
MAIN_ADMIN_ID = int(os.environ.get('MAIN_ADMIN_ID', '8358009538'))
TASK_NOTIFICATION_GROUP = os.environ.get('TASK_NOTIFICATION_GROUP', '@wedferfwewf')
REPORT_GROUP = os.environ.get('REPORT_GROUP', '@ertghpjoterg')

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Файлы для хранения данных
USERS_FILE = "users_data.json"
ADMINS_FILE = "admins_data.json"
TASKS_FILE = "tasks_data.json"
USER_TASKS_FILE = "user_tasks.json"
LINKS_FILE = "tracking_links.json"
PENDING_LINKS_FILE = "pending_links.json"  # Файл для хранения ожидающих ссылок

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== КЛАССЫ ДЛЯ УПРАВЛЕНИЯ ДАННЫМИ ==========
class DataManager:
    """Менеджер для работы с данными"""
    
    @staticmethod
    def load_data(filename: str, default: any = None):
        """Загрузка данных из файла"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default if default is not None else {}
    
    @staticmethod
    def save_data(filename: str, data: any):
        """Сохранение данных в файл"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def generate_tracking_link(user_id: int, task_id: str) -> str:
        """Генерация уникальной ссылки для отслеживания"""
        token = secrets.token_urlsafe(16)
        link_id = hashlib.md5(f"{user_id}_{task_id}_{token}".encode()).hexdigest()[:8]
        
        links = DataManager.load_data(LINKS_FILE, {})
        links[link_id] = {
            "user_id": user_id,
            "task_id": task_id,
            "created": datetime.now().isoformat(),
            "clicks": 0,
            "conversions": 0,
            "active": True,
            "work_link": None  # Здесь будет рабочая ссылка от админа
        }
        DataManager.save_data(LINKS_FILE, links)
        
        return f"https://t.me/your_tracking_bot?start={link_id}"
    
    @staticmethod
    def get_user_stats(user_id: int) -> Dict:
        """Получение статистики пользователя"""
        user_tasks = DataManager.load_data(USER_TASKS_FILE, {})
        tasks = DataManager.load_data(TASKS_FILE, {})
        
        user_data = user_tasks.get(str(user_id), {})
        completed = user_data.get("completed_tasks", [])
        active = user_data.get("active_tasks", [])
        
        total_earned = sum(
            tasks.get(task_id, {}).get("reward", 0) 
            for task_id in completed
        )
        
        return {
            "completed_count": len(completed),
            "active_count": len(active),
            "total_earned": total_earned,
            "rating": len(completed) * 10
        }

class AdminManager:
    """Менеджер для работы с администраторами"""
    
    @staticmethod
    def is_admin(user_id: int) -> bool:
        """Проверка, является ли пользователь админом"""
        if user_id == MAIN_ADMIN_ID:
            return True
        
        admins = DataManager.load_data(ADMINS_FILE, {})
        return str(user_id) in admins
    
    @staticmethod
    def is_main_admin(user_id: int) -> bool:
        """Проверка, является ли пользователь главным админом"""
        return user_id == MAIN_ADMIN_ID
    
    @staticmethod
    def add_admin(user_id: int, username: str = "", added_by: int = MAIN_ADMIN_ID):
        """Добавление администратора"""
        admins = DataManager.load_data(ADMINS_FILE, {})
        admins[str(user_id)] = {
            "username": username,
            "added_by": added_by,
            "added_date": datetime.now().isoformat(),
            "permissions": ["manage_tasks", "view_stats"]
        }
        DataManager.save_data(ADMINS_FILE, admins)
    
    @staticmethod
    def remove_admin(user_id: int):
        """Удаление администратора"""
        admins = DataManager.load_data(ADMINS_FILE, {})
        if str(user_id) in admins:
            del admins[str(user_id)]
            DataManager.save_data(ADMINS_FILE, admins)
            return True
        return False

class TaskManager:
    """Менеджер для работы с заданиями"""
    
    @staticmethod
    def create_task(
        title: str,
        description: str,
        task_type: str,
        target: str,
        reward: float,
        created_by: int,
        requirements: str = ""
    ) -> str:
        """Создание нового задания"""
        tasks = DataManager.load_data(TASKS_FILE, {})
        
        task_id = hashlib.md5(f"{title}_{datetime.now()}".encode()).hexdigest()[:8]
        
        tasks[task_id] = {
            "id": task_id,
            "title": title,
            "description": description,
            "type": task_type,
            "target": target,
            "reward": reward,
            "requirements": requirements,
            "created_by": created_by,
            "created_date": datetime.now().isoformat(),
            "active": True,
            "taken_by": None,
            "completed": False,
            "available": True,
            "work_link": None  # Рабочая ссылка от админа
        }
        
        DataManager.save_data(TASKS_FILE, tasks)
        return task_id
    
    @staticmethod
    def get_available_tasks() -> List[Dict]:
        """Получение списка доступных заданий"""
        tasks = DataManager.load_data(TASKS_FILE, {})
        return [
            task for task in tasks.values() 
            if task.get("available", True) and task.get("active", True) and not task.get("taken_by")
        ]
    
    @staticmethod
    def get_task(task_id: str) -> Optional[Dict]:
        """Получение задания по ID"""
        tasks = DataManager.load_data(TASKS_FILE, {})
        return tasks.get(task_id)
    
    @staticmethod
    def assign_task(task_id: str, user_id: int) -> bool:
        """Назначение задания пользователю"""
        tasks = DataManager.load_data(TASKS_FILE, {})
        
        if task_id not in tasks:
            return False
        
        task = tasks[task_id]
        if task.get("taken_by") or not task.get("available", True):
            return False
        
        task["taken_by"] = user_id
        task["available"] = False
        task["assigned_date"] = datetime.now().isoformat()
        task["work_link"] = None  # Сброс рабочей ссылки
        
        user_tasks = DataManager.load_data(USER_TASKS_FILE, {})
        user_id_str = str(user_id)
        
        if user_id_str not in user_tasks:
            user_tasks[user_id_str] = {
                "active_tasks": [],
                "completed_tasks": [],
                "earned": 0,
                "joined_date": datetime.now().isoformat()
            }
        
        user_tasks[user_id_str]["active_tasks"].append(task_id)
        
        DataManager.save_data(TASKS_FILE, tasks)
        DataManager.save_data(USER_TASKS_FILE, user_tasks)
        
        return True
    
    @staticmethod
    def set_work_link(task_id: str, link: str) -> bool:
        """Установка рабочей ссылки для задания"""
        tasks = DataManager.load_data(TASKS_FILE, {})
        
        if task_id not in tasks:
            return False
        
        tasks[task_id]["work_link"] = link
        DataManager.save_data(TASKS_FILE, tasks)
        return True
    
    @staticmethod
    def complete_task(task_id: str, user_id: int, proof: str = "") -> bool:
        """Завершение задания"""
        tasks = DataManager.load_data(TASKS_FILE, {})
        user_tasks = DataManager.load_data(USER_TASKS_FILE, {})
        
        if task_id not in tasks:
            return False
        
        task = tasks[task_id]
        user_id_str = str(user_id)
        
        if task.get("taken_by") != user_id:
            return False
        
        task["completed"] = True
        task["completed_date"] = datetime.now().isoformat()
        task["proof"] = proof
        task["active"] = False
        
        if user_id_str in user_tasks:
            if task_id in user_tasks[user_id_str]["active_tasks"]:
                user_tasks[user_id_str]["active_tasks"].remove(task_id)
            
            user_tasks[user_id_str]["completed_tasks"].append(task_id)
            user_tasks[user_id_str]["earned"] = user_tasks[user_id_str].get("earned", 0) + task.get("reward", 0)
        
        DataManager.save_data(TASKS_FILE, tasks)
        DataManager.save_data(USER_TASKS_FILE, user_tasks)
        
        return True

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
    
    if AdminManager.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_tracking_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link_id: str):
    """Обработка переходов по отслеживающим ссылкам"""
    link_data = await TrackingLinksManager.get_link(link_id)
    
    if not link_data:
        await update.message.reply_text("Ссылка не найдена или устарела.")
        return
    
    # Увеличиваем счетчик кликов
    await TrackingLinksManager.increment_clicks(link_id)
    
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

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ССЫЛКАМИ В ГРУППЕ ==========
async def send_task_notification(context: ContextTypes.DEFAULT_TYPE, user, task, tracking_link):
    """Отправка уведомления в группу с кнопкой"""
    notification_text = (
        f"🚀 *НОВОЕ ЗАДАНИЕ ВЗЯТО!*\n\n"
        f"*Исполнитель:* {user.first_name} (@{user.username if user.username else 'без username'})\n"
        f"*Задание:* {task['title']}\n"
        f"*Цель:* {task['target']}\n"
        f"*Вознаграждение:* {task['reward']} руб.\n\n"
        f"⚠️ *Администратору:*\n"
        f"Нажмите кнопку ниже, чтобы выдать исполнителю рабочую ссылку:"
    )
    
    # Кнопка для выдачи ссылки
    keyboard = [[
        InlineKeyboardButton(
            "🔗 Дать рабочую ссылку", 
            callback_data=f"give_link_{task['id']}_{user.id}"
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Сохраняем информацию о задании для последующей обработки
    await PendingLinksManager.save_pending(task['id'], {
        "user_id": user.id,
        "username": user.username,
        "task_title": task['title'],
        "message_sent": datetime.now(),
        "tracking_link": tracking_link
    })
    
    await context.bot.send_message(
        chat_id=TASK_NOTIFICATION_GROUP,
        text=notification_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_give_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки 'Дать рабочую ссылку'"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем, что нажавший - администратор
    if not AdminManager.is_admin(query.from_user.id):
        await query.answer("❌ Только администратор может выдавать ссылки!", show_alert=True)
        return
    
    # Парсим данные из callback_data
    data = query.data
    _, task_id, user_id = data.split('_')
    user_id = int(user_id)
    
    # Получаем информацию о задании
    task = TaskManager.get_task(task_id)
    if not task:
        await query.answer("❌ Задание не найдено!", show_alert=True)
        return
    
    # Удаляем кнопку из сообщения
    await query.edit_message_reply_markup(reply_markup=None)
    
    # Сохраняем состояние - ожидаем ссылку от админа
    context.user_data["waiting_for_link"] = {
        "task_id": task_id,
        "user_id": user_id,
        "group_chat_id": query.message.chat_id,
        "group_message_id": query.message.message_id
    }
    
    await query.message.reply_text(
        f"📎 *Отправьте рабочую ссылку для задания:*\n"
        f"*{task['title']}*\n\n"
        f"Ссылка будет автоматически отправлена исполнителю.",
        parse_mode='Markdown'
    )

async def handle_work_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отправки рабочей ссылки администратором"""
    user_id = update.effective_user.id
    
    # Проверяем, что это админ и ожидает ввод ссылки
    if not AdminManager.is_admin(user_id):
        return
    
    if "waiting_for_link" not in context.user_data:
        return
    
    link_data = context.user_data["waiting_for_link"]
    work_link = update.message.text
    
    # Сохраняем ссылку в задании
    TaskManager.set_work_link(link_data["task_id"], work_link)
    
    # Получаем информацию о задании
    task = TaskManager.get_task(link_data["task_id"])
    
    # Отправляем ссылку исполнителю
    try:
        await context.bot.send_message(
            chat_id=link_data["user_id"],
            text=(
                f"🔗 *Вы получили рабочую ссылку!*\n\n"
                f"*Задание:* {task['title']}\n"
                f"*Ссылка для работы:*\n"
                f"`{work_link}`\n\n"
                f"Приступайте к выполнению. После завершения отправьте отчет через бота."
            ),
            parse_mode='Markdown'
        )
        
        # Отправляем подтверждение в группу
        await update.message.reply_text(
            f"✅ *Ссылка отправлена исполнителю!*\n\n"
            f"Задание: {task['title']}",
            parse_mode='Markdown'
        )
        
        # Удаляем ожидающий статус
        pending = DataManager.load_data(PENDING_LINKS_FILE, {})
        if link_data["task_id"] in pending:
            del pending[link_data["task_id"]]
            DataManager.save_data(PENDING_LINKS_FILE, pending)
        
        del context.user_data["waiting_for_link"]
        
    except Exception as e:
        logger.error(f"Ошибка отправки ссылки исполнителю: {e}")
        await update.message.reply_text(
            "❌ Не удалось отправить ссылку исполнителю. Проверьте, что пользователь запустил бота.",
            parse_mode='Markdown'
        )

# ========== ОБРАБОТЧИКИ КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Обработка кнопки выдачи ссылки
    if data.startswith("give_link_"):
        await handle_give_link_callback(update, context)
    
    elif data == "profile":
        await show_profile(query, context)
    elif data == "available_tasks":
        await show_available_tasks(query, context)
    elif data == "my_stats":
        await show_my_stats(query, context)
    elif data == "help":
        await show_help(query, context)
    elif data == "admin_panel":
        await show_admin_panel(query, context)
    elif data.startswith("view_task_"):
        task_id = data.replace("view_task_", "")
        await view_task_details(query, context, task_id)
    elif data.startswith("take_task_"):
        task_id = data.replace("take_task_", "")
        await take_task(query, context, task_id)
    elif data == "admin_create_task":
        await create_task_dialog(query, context)
    elif data.startswith("task_type_"):
        await handle_task_type_selection(query, context, data)
    elif data == "back_to_main":
        await back_to_main_menu(query, context)
    elif data == "admin_view_stats":
        await view_admin_stats(query, context)
    elif data == "admin_manage_admins":
        await manage_admins(query, context)
    elif data == "admin_add_admin":
        await add_admin_dialog(query, context)
    elif data.startswith("admin_remove_"):
        admin_id = int(data.replace("admin_remove_", ""))
        await remove_admin(query, context, admin_id)

async def show_profile(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать профиль пользователя"""
    user = query.from_user
    stats = DataManager.get_user_stats(user.id)
    
    # Получаем активные задания
    user_tasks = DataManager.load_data(USER_TASKS_FILE, {})
    user_data = user_tasks.get(str(user.id), {})
    active_tasks = user_data.get("active_tasks", [])
    
    # Проверяем, есть ли у активных заданий рабочие ссылки
    tasks = DataManager.load_data(TASKS_FILE, {})
    has_work_links = False
    for task_id in active_tasks:
        if task_id in tasks and tasks[task_id].get("work_link"):
            has_work_links = True
            break
    
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
        f"*Статус:* {'👑 Администратор' if AdminManager.is_admin(user.id) else '👤 Исполнитель'}"
    )
    
    if has_work_links:
        profile_text += "\n\n🔗 *У вас есть активные ссылки!*"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_available_tasks(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать доступные задания"""
    tasks = TaskManager.get_available_tasks()
    
    if not tasks:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 На данный момент нет доступных заданий.",
            reply_markup=reply_markup
        )
        return
    
    keyboard = []
    for task in tasks[:10]:
        btn_text = f"{task['title']} - {task['reward']} руб."
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"view_task_{task['id']}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📋 *Доступные задания:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def view_task_details(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Показать детали задания"""
    task = TaskManager.get_task(task_id)
    
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
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="available_tasks")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(task_text, reply_markup=reply_markup, parse_mode='Markdown')

async def take_task(query, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Взять задание"""
    user = query.from_user
    task = TaskManager.get_task(task_id)
    
    if not task:
        await query.answer("Задание не найдено!", show_alert=True)
        return
    
    if TaskManager.assign_task(task_id, user.id):
        # Генерируем отслеживающую ссылку
        tracking_link = DataManager.generate_tracking_link(user.id, task_id)
        
        # Отправляем уведомление в группу с кнопкой
        await send_task_notification(context, user, task, tracking_link)
        
        success_text = (
            f"✅ *Задание успешно взято!*\n\n"
            f"*{task['title']}*\n\n"
            f"Ожидайте, когда администратор выдаст вам рабочую ссылку. "
            f"Как только ссылка будет готова, вы получите её в личные сообщения от бота.\n\n"
            f"После получения ссылки приступайте к работе!"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await query.answer("Не удалось взять задание.", show_alert=True)

async def show_my_stats(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику пользователя"""
    user = query.from_user
    stats = DataManager.get_user_stats(user.id)
    
    stats_text = (
        f"📊 *Ваша статистика*\n\n"
        f"✅ *Выполнено заданий:* {stats['completed_count']}\n"
        f"🎯 *Активных заданий:* {stats['active_count']}\n"
        f"💰 *Всего заработано:* {stats['total_earned']} руб.\n"
        f"⭐ *Рейтинг:* {stats['rating']}/100"
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_help(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать справку"""
    help_text = (
        "❓ *Помощь*\n\n"
        "1. 👤 *Профиль* — ваша статистика\n"
        "2. 📋 *Доступные задания* — выбирайте задания\n"
        "3. ✅ *Взятие задания* — ожидайте ссылку от админа\n"
        "4. 🔗 *Получение ссылки* — ссылка придет в ЛС от бота\n"
        "5. 📊 *Отчет* — после выполнения отправьте отчет\n\n"
        "*Все вопросы к администратору.*"
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

async def back_to_main_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться в главное меню"""
    user = query.from_user
    
    welcome_text = "🚀 *Главное меню*"
    
    keyboard = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("📋 Доступные задания", callback_data="available_tasks")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    
    if AdminManager.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# ========== АДМИН ПАНЕЛЬ ==========
async def show_admin_panel(query, context: ContextTypes.DEFAULT_TYPE):
    """Показать админ-панель"""
    user = query.from_user
    
    if not AdminManager.is_admin(user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    is_main = AdminManager.is_main_admin(user.id)
    
    admin_text = (
        f"👑 *Панель администратора*\n\n"
        f"ID: {user.id}\n"
        f"Статус: {'Главный админ' if is_main else 'Админ'}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_view_stats")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="admin_create_task")],
    ]
    
    if is_main:
        keyboard.append([InlineKeyboardButton("👥 Управление админами", callback_data="admin_manage_admins")])
    
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')

async def manage_admins(query, context: ContextTypes.DEFAULT_TYPE):
    """Управление администраторами"""
    if not AdminManager.is_main_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_admin")],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "👥 *Управление администраторами*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def add_admin_dialog(query, context: ContextTypes.DEFAULT_TYPE):
    """Диалог добавления администратора"""
    if not AdminManager.is_main_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    context.user_data["waiting_for_admin_id"] = True
    
    await query.edit_message_text(
        "👥 *Добавление администратора*\n\n"
        "Отправьте ID пользователя:",
        parse_mode='Markdown'
    )

async def handle_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ID нового администратора"""
    user_id = update.effective_user.id
    
    if not AdminManager.is_main_admin(user_id):
        return
    
    if not context.user_data.get("waiting_for_admin_id"):
        return
    
    try:
        target_user_id = int(update.message.text)
        AdminManager.add_admin(target_user_id, "Новый админ", user_id)
        
        del context.user_data["waiting_for_admin_id"]
        
        await update.message.reply_text(
            f"✅ *Администратор добавлен!*\n\nID: {target_user_id}",
            parse_mode='Markdown'
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="🎉 *Вас назначили администратором!*\n\nИспользуйте /start",
                parse_mode='Markdown'
            )
        except:
            pass
            
    except ValueError:
        await update.message.reply_text("❌ Неверный ID")

async def remove_admin(query, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    """Удаление администратора"""
    if not AdminManager.is_main_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    if admin_id == MAIN_ADMIN_ID:
        await query.answer("Нельзя удалить главного админа!", show_alert=True)
        return
    
    if AdminManager.remove_admin(admin_id):
        await query.answer("✅ Администратор удален!", show_alert=True)

async def create_task_dialog(query, context: ContextTypes.DEFAULT_TYPE):
    """Диалог создания задания"""
    if not AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    context.user_data["creating_task"] = {
        "step": "title",
        "data": {}
    }
    
    await query.edit_message_text(
        "➕ *Создание задания*\n\n"
        "*Шаг 1/6*\n"
        "Введите название задания:",
        parse_mode='Markdown'
    )

async def handle_task_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка создания задания"""
    user_id = update.effective_user.id
    
    if not AdminManager.is_admin(user_id):
        return
    
    if "creating_task" not in context.user_data:
        return
    
    task_data = context.user_data["creating_task"]
    step = task_data["step"]
    text = update.message.text
    
    if step == "title":
        task_data["data"]["title"] = text
        task_data["step"] = "description"
        
        await update.message.reply_text(
            "*Шаг 2/6*\n"
            "Введите описание задания:",
            parse_mode='Markdown'
        )
    
    elif step == "description":
        task_data["data"]["description"] = text
        task_data["step"] = "type"
        
        keyboard = [
            [InlineKeyboardButton("👥 Подписчики", callback_data="task_type_subscribers")],
            [InlineKeyboardButton("📢 Реклама", callback_data="task_type_ad")],
            [InlineKeyboardButton("🔗 Переходы", callback_data="task_type_clicks")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "*Шаг 3/6*\n"
            "Выберите тип задания:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif step == "target":
        task_data["data"]["target"] = text
        task_data["step"] = "reward"
        
        await update.message.reply_text(
            "*Шаг 5/6*\n"
            "Введите вознаграждение (руб):",
            parse_mode='Markdown'
        )
    
    elif step == "reward":
        try:
            reward = float(text)
            task_data["data"]["reward"] = reward
            task_data["step"] = "requirements"
            
            await update.message.reply_text(
                "*Шаг 6/6*\n"
                "Введите требования (или '-'):",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Введите число")
    
    elif step == "requirements":
        task_data["data"]["requirements"] = text
        
        task_id = TaskManager.create_task(
            title=task_data["data"]["title"],
            description=task_data["data"]["description"],
            task_type=task_data["data"].get("type", "other"),
            target=task_data["data"]["target"],
            reward=task_data["data"]["reward"],
            created_by=user_id,
            requirements=task_data["data"]["requirements"]
        )
        
        del context.user_data["creating_task"]
        
        await update.message.reply_text(
            f"✅ *Задание создано!*\n\nID: {task_id}",
            parse_mode='Markdown'
        )

async def handle_task_type_selection(query, context, data):
    """Обработка выбора типа задания"""
    task_type_map = {
        "task_type_subscribers": "Подписчики",
        "task_type_ad": "Реклама",
        "task_type_clicks": "Переходы"
    }
    
    task_type = task_type_map.get(data, "Другое")
    
    if "creating_task" in context.user_data:
        context.user_data["creating_task"]["data"]["type"] = task_type
        context.user_data["creating_task"]["step"] = "target"
        
        await query.edit_message_text(
            "*Шаг 4/6*\n"
            "Введите цель (например: 1000 подписчиков):",
            parse_mode='Markdown'
        )

async def view_admin_stats(query, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр статистики"""
    if not AdminManager.is_admin(query.from_user.id):
        await query.answer("Доступ запрещен!", show_alert=True)
        return
    
    users = DataManager.load_data(USER_TASKS_FILE, {})
    tasks = DataManager.load_data(TASKS_FILE, {})
    
    total_users = len(users)
    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks.values() if t.get("completed"))
    total_payout = sum(t.get("reward", 0) for t in tasks.values() if t.get("completed"))
    pending_links = len(DataManager.load_data(PENDING_LINKS_FILE, {}))
    
    stats_text = (
        f"📊 *Статистика*\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📋 Заданий: {total_tasks}\n"
        f"✅ Выполнено: {completed_tasks}\n"
        f"💰 Выплачено: {total_payout} руб.\n"
        f"⏳ Ожидают ссылки: {pending_links}"
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_creation))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_id))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_work_link))
    
    print("=" * 50)
    print("✅ БОТ TRAFFIC TEAM УСПЕШНО ЗАПУЩЕН!")
    print("=" * 50)
    print(f"👑 Главный админ: {MAIN_ADMIN_ID}")
    print(f"📢 Группа уведомлений: {TASK_NOTIFICATION_GROUP}")
    print(f"📊 Группа отчетов: {REPORT_GROUP}")
    print("=" * 50)
    print("🔄 НОВЫЙ ФУНКЦИОНАЛ:")
    print("• Кнопка 'Дать ссылку' в уведомлениях")
    print("• Автоматическая отправка ссылки исполнителю")
    print("• Исчезновение кнопки после выдачи ссылки")
    print("=" * 50)
    print("Нажмите Ctrl+C для остановки")
    print("=" * 50)
    
    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

async def main():
    """Запуск бота"""
    # Инициализация базы данных
    await PostgresDB.init_db()
    print("=" * 50)
    print("✅ БАЗА ДАННЫХ ИНИЦИАЛИЗИРОВАНА")
    print("=" * 50)
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_creation))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_id))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_work_link))
    
    print("=" * 50)
    print("✅ БОТ TRAFFIC TEAM УСПЕШНО ЗАПУЩЕН!")
    print("=" * 50)
    print(f"👑 Главный админ: {MAIN_ADMIN_ID}")
    print(f"📢 Группа уведомлений: {TASK_NOTIFICATION_GROUP}")
    print(f"📊 Группа отчетов: {REPORT_GROUP}")
    print("=" * 50)
    print("Нажмите Ctrl+C для остановки")
    print("=" * 50)
    
    try:
        # Запускаем бота
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        # Закрываем соединение с базой данных
        await PostgresDB.close_pool()

if __name__ == '__main__':
    asyncio.run(main())