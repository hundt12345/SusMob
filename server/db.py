"""Schlanke SQLite-Datenbank-Schicht für SusMob."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH: Path | None = None


def init(path: Path) -> None:
    global DB_PATH
    DB_PATH = Path(path)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tiles (
                id TEXT PRIMARY KEY,
                emoji TEXT NOT NULL,
                name TEXT NOT NULL,
                short TEXT NOT NULL,
                model TEXT NOT NULL,
                temperature REAL NOT NULL DEFAULT 0.2,
                sort INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS prompts (
                tile_id TEXT PRIMARY KEY REFERENCES tiles(id),
                system_prompt TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tile_id TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS standardwerte (
                tile_id TEXT NOT NULL,
                key TEXT NOT NULL,
                label TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                default_value TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT '',
                sort INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tile_id, key)
            );
            CREATE TABLE IF NOT EXISTS settings (
                tile_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (tile_id, key)
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                tile_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_example INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                tile_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                stored_path TEXT NOT NULL,
                extracted_chars INTEGER NOT NULL DEFAULT 0,
                extracted_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tile_id TEXT NOT NULL,
                name TEXT NOT NULL,
                message TEXT NOT NULL,
                file_content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        _migrate(conn)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Ergänzt Spalten, die in älteren Datenbanken noch fehlen."""
    if "is_example" not in _columns(conn, "conversations"):
        conn.execute("ALTER TABLE conversations ADD COLUMN is_example INTEGER NOT NULL DEFAULT 0")


@contextmanager
def get():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with get() as conn:
        return conn.execute(sql, params).fetchall()


def query1(sql: str, params: tuple = ()):
    with get() as conn:
        return conn.execute(sql, params).fetchone()


def exec(sql: str, params: tuple = ()) -> None:
    with get() as conn:
        conn.execute(sql, params)
