"""Local SQLite backend for running EMPIRE CENTURY directly in Termux."""
from __future__ import annotations

import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATABASE_PATH

pool = None


def _dt(value):
    return value.isoformat(sep=" ", timespec="microseconds") if isinstance(value, datetime) else value


def _parse_dt(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.decode().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, AttributeError):
        return value


sqlite3.register_adapter(datetime, _dt)
sqlite3.register_converter("TIMESTAMPTZ", _parse_dt)
sqlite3.register_converter("TIMESTAMP", _parse_dt)


def _sql(statement: str, args: tuple[Any, ...] = ()):
    sql = statement.strip()
    # Handle PostgreSQL interval arithmetic before replacing NOW().
    sql = re.sub(
        r"NOW\(\)\s*\+\s*\(\$(\d+)::(?:int|integer)\s*\*\s*INTERVAL\s*'1 day'\)",
        lambda m: "datetime('now', printf('%+d days', $" + m.group(1) + "))",
        sql, flags=re.I,
    )
    sql = re.sub(
        r"NOW\(\)\s*\+\s*INTERVAL\s*'([^']+)'",
        lambda m: "datetime('now','+" + m.group(1) + "')",
        sql, flags=re.I,
    )
    sql = re.sub(r"\s+FOR\s+UPDATE\b", "", sql, flags=re.I)
    sql = re.sub(r"\bCREATE\s+OR\s+REPLACE\s+VIEW\b", "CREATE VIEW IF NOT EXISTS", sql, flags=re.I)
    sql = re.sub(r"\bBIGSERIAL\b", "INTEGER", sql, flags=re.I)
    sql = re.sub(r"\bBIGINT\b|\bSMALLINT\b", "INTEGER", sql, flags=re.I)
    sql = re.sub(r"\bNUMERIC\([^)]*\)", "REAL", sql, flags=re.I)
    sql = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", sql, flags=re.I)
    sql = re.sub(r"\$(\d+)::(?:timestamptz|timestamp|int|integer|bigint|numeric|text|boolean)", r"$\1", sql, flags=re.I)
    sql = re.sub(r"\$(\d+)::[a-zA-Z_][a-zA-Z_0-9]*(?:\([^)]*\))?", r"$\1", sql)
    # SQLite needs WHERE before ON CONFLICT for INSERT ... SELECT statements.
    sql = re.sub(r"(FROM\s+asset_catalog\s+WHERE\s+asset_key\s*=\s*'[^']+')\s+ON\s+CONFLICT", r"\1 AND 1=1 ON CONFLICT", sql, flags=re.I)
    positions = [int(n) for n in re.findall(r"\$(\d+)", sql)]
    sql = re.sub(r"\$(\d+)", "?", sql)
    ordered = tuple(args[n - 1] for n in positions) if positions else args
    if "pg_advisory_xact_lock" in sql:
        return "SELECT 1", ()
    return sql, ordered


def _statements(script: str):
    script = re.sub(r"--[^\n]*", "", script)
    return [part.strip() for part in script.split(";") if part.strip()]


def _apply_script(conn: sqlite3.Connection, script: str):
    for statement in _statements(script):
        if statement.upper().startswith("SELECT SETVAL("):
            continue
        match = re.match(r"ALTER\s+TABLE\s+(\w+)\s+(.*)", statement, flags=re.I | re.S)
        if match and re.search(r"ADD\s+COLUMN", match.group(2), re.I):
            table, clauses = match.groups()
            parts = re.split(r",\s*(?=ADD\s+COLUMN)", clauses, flags=re.I)
            for clause in parts:
                col = re.sub(r"^ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+", "", clause.strip(), flags=re.I)
                col = re.sub(r"^ADD\s+COLUMN\s+", "", col, flags=re.I)
                name = re.match(r"([A-Za-z_]\w*)", col)
                if not name:
                    continue
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if name.group(1) not in existing:
                    sql, _ = _sql(f"ALTER TABLE {table} ADD COLUMN {col}")
                    conn.execute(sql)
            continue
        sql, params = _sql(statement)
        try:
            conn.execute(sql, params)
        except sqlite3.OperationalError as exc:
            if "already exists" in str(exc).lower() or "duplicate column" in str(exc).lower():
                continue
            raise


class SQLiteConnection:
    def __init__(self, connection):
        self.connection = connection

    async def execute(self, query, *args):
        sql, params = _sql(query, args)
        cur = self.connection.execute(sql, params)
        return f"OK {cur.rowcount}"

    async def fetch(self, query, *args):
        sql, params = _sql(query, args)
        return self.connection.execute(sql, params).fetchall()

    async def fetchrow(self, query, *args):
        sql, params = _sql(query, args)
        return self.connection.execute(sql, params).fetchone()

    async def fetchval(self, query, *args):
        row = await self.fetchrow(query, *args)
        return row[0] if row else None

    def transaction(self):
        return SQLiteTransaction(self.connection)


class SQLiteTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.connection.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


class SQLitePool:
    def __init__(self, connection):
        self.connection = connection
        self.conn = SQLiteConnection(connection)

    @asynccontextmanager
    async def acquire(self):
        yield self.conn

    async def close(self):
        self.connection.close()


async def connect() -> None:
    global pool
    if pool is not None:
        return
    path = Path(DATABASE_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.create_function("LEAST", -1, lambda *v: min(v))
    conn.create_function("GREATEST", -1, lambda *v: max(v))
    conn.create_function("pg_advisory_xact_lock", 1, lambda _: 1)
    root = Path(__file__).resolve().parent.parent
    try:
        _apply_script(conn, (root / "schema.sql").read_text(encoding="utf-8"))
        for migration in sorted((root / "migrations").glob("*.sql")):
            _apply_script(conn, migration.read_text(encoding="utf-8"))
        conn.commit()
    except Exception:
        conn.close()
        raise
    pool = SQLitePool(conn)


async def close() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


def get_pool() -> SQLitePool:
    if pool is None:
        raise RuntimeError("Local SQLite database has not been initialized")
    return pool
