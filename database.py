import os
import asyncpg
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")

async def get_connection():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_connection()
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS message_links (
            channel_msg_id BIGINT PRIMARY KEY,
            user_id BIGINT NOT NULL
        )
    ''')
    await conn.close()

async def add_link(channel_msg_id: int, user_id: int):
    conn = await get_connection()
    await conn.execute(
        'INSERT INTO message_links (channel_msg_id, user_id) VALUES ($1, $2)',
        channel_msg_id, user_id
    )
    await conn.close()

async def get_user_by_message(channel_msg_id: int) -> Optional[int]:
    conn = await get_connection()
    row = await conn.fetchrow('SELECT user_id FROM message_links WHERE channel_msg_id = $1', channel_msg_id)
    await conn.close()
    return row['user_id'] if row else None