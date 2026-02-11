import os
import asyncpg
import json
import hashlib
import secrets
from datetime import datetime
from typing import Dict, List, Optional

# Получаем переменные окружения
MAIN_ADMIN_ID = int(os.environ.get('MAIN_ADMIN_ID', '8358009538'))
DATABASE_URL = os.environ.get('DATABASE_URL', '')

class PostgresDB:
    """Класс для работы с PostgreSQL"""
    
    _pool = None
    
    @classmethod
    async def init_pool(cls):
        """Инициализация пула соединений"""
        if not cls._pool:
            cls._pool = await asyncpg.create_pool(DATABASE_URL)
        return cls._pool
    
    @classmethod
    async def close_pool(cls):
        """Закрытие пула"""
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
    
    @classmethod
    async def init_db(cls):
        """Создание таблиц"""
        pool = await cls.init_pool()
        async with pool.acquire() as conn:
            # Таблица пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    joined_date TIMESTAMP,
                    earned FLOAT DEFAULT 0,
                    rating INTEGER DEFAULT 0
                )
            ''')
            
            # Таблица администраторов
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    added_by BIGINT,
                    added_date TIMESTAMP,
                    permissions JSONB
                )
            ''')
            
            # Таблица заданий
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    type TEXT,
                    target TEXT,
                    reward FLOAT,
                    requirements TEXT,
                    created_by BIGINT,
                    created_date TIMESTAMP,
                    active BOOLEAN DEFAULT true,
                    taken_by BIGINT,
                    assigned_date TIMESTAMP,
                    completed BOOLEAN DEFAULT false,
                    completed_date TIMESTAMP,
                    proof TEXT,
                    work_link TEXT,
                    available BOOLEAN DEFAULT true
                )
            ''')
            
            # Таблица активных заданий пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_tasks (
                    user_id BIGINT,
                    task_id TEXT,
                    status TEXT,
                    taken_date TIMESTAMP,
                    completed_date TIMESTAMP,
                    PRIMARY KEY (user_id, task_id)
                )
            ''')
            
            # Таблица для отслеживания ссылок
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tracking_links (
                    link_id TEXT PRIMARY KEY,
                    user_id BIGINT,
                    task_id TEXT,
                    created TIMESTAMP,
                    clicks INTEGER DEFAULT 0,
                    conversions INTEGER DEFAULT 0,
                    active BOOLEAN DEFAULT true,
                    work_link TEXT
                )
            ''')
            
            # Таблица для ожидающих ссылок
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS pending_links (
                    task_id TEXT PRIMARY KEY,
                    user_id BIGINT,
                    username TEXT,
                    task_title TEXT,
                    message_sent TIMESTAMP,
                    tracking_link TEXT
                )
            ''')
            
            print("✅ Таблицы PostgreSQL созданы/проверены")

class UserManager:
    @staticmethod
    async def get_or_create_user(user_id: int, username: str = "", first_name: str = ""):
        """Получение или создание пользователя"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            # Пытаемся найти пользователя
            user = await conn.fetchrow(
                'SELECT * FROM users WHERE user_id = $1',
                user_id
            )
            
            if not user:
                # Создаем нового пользователя
                await conn.execute('''
                    INSERT INTO users (user_id, username, first_name, joined_date, earned, rating)
                    VALUES ($1, $2, $3, $4, 0, 0)
                ''', user_id, username, first_name, datetime.now())
                return None
            return dict(user) if user else None
    
    @staticmethod
    async def get_user_stats(user_id: int) -> Dict:
        """Получение статистики пользователя"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            # Получаем выполненные задания
            completed = await conn.fetch('''
                SELECT t.task_id, t.reward 
                FROM user_tasks ut
                JOIN tasks t ON ut.task_id = t.task_id
                WHERE ut.user_id = $1 AND ut.status = 'completed'
            ''', user_id)
            
            # Получаем активные задания
            active = await conn.fetch('''
                SELECT task_id 
                FROM user_tasks 
                WHERE user_id = $1 AND status = 'active'
            ''', user_id)
            
            # Получаем пользователя
            user = await conn.fetchrow(
                'SELECT earned FROM users WHERE user_id = $1',
                user_id
            )
            
            completed_count = len(completed)
            active_count = len(active)
            total_earned = user['earned'] if user else 0
            
            return {
                "completed_count": completed_count,
                "active_count": active_count,
                "total_earned": total_earned,
                "rating": completed_count * 10
            }
    
    @staticmethod
    async def add_earned(user_id: int, amount: float):
        """Добавление заработка пользователю"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                UPDATE users 
                SET earned = earned + $1 
                WHERE user_id = $2
            ''', amount, user_id)

class TaskManager:
    @staticmethod
    async def create_task(
        title: str,
        description: str,
        task_type: str,
        target: str,
        reward: float,
        created_by: int,
        requirements: str = ""
    ) -> str:
        """Создание нового задания"""
        task_id = hashlib.md5(f"{title}_{datetime.now()}".encode()).hexdigest()[:8]
        
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO tasks (
                    task_id, title, description, type, target, reward,
                    requirements, created_by, created_date, active, available
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true, true)
            ''', task_id, title, description, task_type, target, reward,
                requirements, created_by, datetime.now())
        
        return task_id
    
    @staticmethod
    async def get_available_tasks() -> List[Dict]:
        """Получение списка доступных заданий"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM tasks 
                WHERE available = true AND active = true AND taken_by IS NULL
                ORDER BY created_date DESC
            ''')
            return [dict(row) for row in rows]
    
    @staticmethod
    async def get_task(task_id: str) -> Optional[Dict]:
        """Получение задания по ID"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM tasks WHERE task_id = $1',
                task_id
            )
            return dict(row) if row else None
    
    @staticmethod
    async def assign_task(task_id: str, user_id: int) -> bool:
        """Назначение задания пользователю"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            # Проверяем доступность задания
            task = await conn.fetchrow(
                'SELECT * FROM tasks WHERE task_id = $1 AND available = true AND taken_by IS NULL',
                task_id
            )
            if not task:
                return False
            
            # Назначаем задание
            await conn.execute('''
                UPDATE tasks 
                SET taken_by = $1, available = false, assigned_date = $2
                WHERE task_id = $3
            ''', user_id, datetime.now(), task_id)
            
            # Добавляем в user_tasks
            await conn.execute('''
                INSERT INTO user_tasks (user_id, task_id, status, taken_date)
                VALUES ($1, $2, 'active', $3)
                ON CONFLICT (user_id, task_id) DO NOTHING
            ''', user_id, task_id, datetime.now())
            
            return True
    
    @staticmethod
    async def set_work_link(task_id: str, link: str) -> bool:
        """Установка рабочей ссылки"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            result = await conn.execute('''
                UPDATE tasks SET work_link = $1 WHERE task_id = $2
            ''', link, task_id)
            return 'UPDATE 1' in result
    
    @staticmethod
    async def complete_task(task_id: str, user_id: int, proof: str = "") -> bool:
        """Завершение задания"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            # Проверяем, что задание взято этим пользователем
            task = await conn.fetchrow(
                'SELECT * FROM tasks WHERE task_id = $1 AND taken_by = $2',
                task_id, user_id
            )
            if not task:
                return False
            
            # Завершаем задание
            await conn.execute('''
                UPDATE tasks 
                SET completed = true, completed_date = $1, proof = $2, active = false
                WHERE task_id = $3
            ''', datetime.now(), proof, task_id)
            
            # Обновляем статус в user_tasks
            await conn.execute('''
                UPDATE user_tasks 
                SET status = 'completed', completed_date = $1
                WHERE user_id = $2 AND task_id = $3
            ''', datetime.now(), user_id, task_id)
            
            # Добавляем заработок пользователю
            await UserManager.add_earned(user_id, task['reward'])
            
            return True
    
    @staticmethod
    async def generate_tracking_link(user_id: int, task_id: str) -> str:
        """Генерация отслеживающей ссылки"""
        token = secrets.token_urlsafe(16)
        link_id = hashlib.md5(f"{user_id}_{task_id}_{token}".encode()).hexdigest()[:8]
        
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO tracking_links (link_id, user_id, task_id, created, clicks, conversions, active)
                VALUES ($1, $2, $3, $4, 0, 0, true)
            ''', link_id, user_id, task_id, datetime.now())
        
        return f"https://t.me/your_tracking_bot?start={link_id}"

class AdminManager:
    @staticmethod
    async def is_admin(user_id: int) -> bool:
        """Проверка, является ли пользователь админом"""
        if user_id == MAIN_ADMIN_ID:
            return True
        
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM admins WHERE user_id = $1',
                user_id
            )
            return row is not None
    
    @staticmethod
    async def is_main_admin(user_id: int) -> bool:
        """Проверка, является ли пользователь главным админом"""
        return user_id == MAIN_ADMIN_ID
    
    @staticmethod
    async def add_admin(user_id: int, username: str = "", added_by: int = None):
        """Добавление администратора"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO admins (user_id, username, added_by, added_date, permissions)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (user_id) DO NOTHING
            ''', user_id, username, added_by, datetime.now(), 
                json.dumps(["manage_tasks", "view_stats"]))
    
    @staticmethod
    async def remove_admin(user_id: int) -> bool:
        """Удаление администратора"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                'DELETE FROM admins WHERE user_id = $1',
                user_id
            )
            return 'DELETE 1' in result
    
    @staticmethod
    async def get_all_admins() -> List[Dict]:
        """Получение всех администраторов"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM admins')
            return [dict(row) for row in rows]

class PendingLinksManager:
    @staticmethod
    async def save_pending(task_id: str, data: Dict):
        """Сохранение ожидающей ссылки"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO pending_links (task_id, user_id, username, task_title, message_sent, tracking_link)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (task_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    username = EXCLUDED.username,
                    task_title = EXCLUDED.task_title,
                    message_sent = EXCLUDED.message_sent,
                    tracking_link = EXCLUDED.tracking_link
            ''', task_id, data['user_id'], data['username'], data['task_title'], 
                data['message_sent'], data['tracking_link'])
    
    @staticmethod
    async def get_pending(task_id: str) -> Optional[Dict]:
        """Получение ожидающей ссылки"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM pending_links WHERE task_id = $1',
                task_id
            )
            return dict(row) if row else None
    
    @staticmethod
    async def delete_pending(task_id: str):
        """Удаление ожидающей ссылки"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                'DELETE FROM pending_links WHERE task_id = $1',
                task_id
            )
    
    @staticmethod
    async def get_all_pending() -> List[Dict]:
        """Получение всех ожидающих ссылок"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM pending_links')
            return [dict(row) for row in rows]

class TrackingLinksManager:
    @staticmethod
    async def get_link(link_id: str) -> Optional[Dict]:
        """Получение ссылки по ID"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM tracking_links WHERE link_id = $1',
                link_id
            )
            return dict(row) if row else None
    
    @staticmethod
    async def increment_clicks(link_id: str):
        """Увеличение счетчика кликов"""
        pool = await PostgresDB.init_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                UPDATE tracking_links 
                SET clicks = clicks + 1, last_click = $1
                WHERE link_id = $2
            ''', datetime.now(), link_id)