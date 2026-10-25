import asyncpg
from app.config import DATABASE_URL

pool: asyncpg.Pool | None = None

async def connect() -> None:
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, command_timeout=30)

async def close() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None

def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError('Database pool has not been initialized')
    return pool
