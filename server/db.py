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

            -- Phase 0: Messbarkeit -------------------------------------------------
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'chat',
                tile_id TEXT NOT NULL DEFAULT '',
                conversation_id TEXT NOT NULL DEFAULT '',
                requested_model TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 1,
                used_fallback INTEGER NOT NULL DEFAULT 0,
                ok INTEGER NOT NULL DEFAULT 1,
                status_code INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                cached_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                cost_estimated INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                chars_in INTEGER NOT NULL DEFAULT 0,
                chars_out INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
            CREATE INDEX IF NOT EXISTS idx_llm_calls_tile ON llm_calls(tile_id);

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'anonym',
                action TEXT NOT NULL,
                object_type TEXT NOT NULL DEFAULT '',
                object_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

            -- Phase 1: Artefakte / Exporte ---------------------------------------
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                tile_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                stored_path TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_conv ON artifacts(conversation_id);

            -- Modell-Gesundheit (Health-Check gegen OpenRouter) -------------------
            CREATE TABLE IF NOT EXISTS model_health (
                model TEXT PRIMARY KEY,
                checked_at TEXT NOT NULL DEFAULT '',
                ok INTEGER NOT NULL DEFAULT 0,
                endpoints INTEGER NOT NULL DEFAULT 0,
                active_endpoints INTEGER NOT NULL DEFAULT 0,
                uptime REAL,
                context_length INTEGER,
                max_completion INTEGER,
                supports_structured INTEGER NOT NULL DEFAULT 0,
                supports_json_mode INTEGER NOT NULL DEFAULT 0,
                supports_tools INTEGER NOT NULL DEFAULT 0,
                supports_vision INTEGER NOT NULL DEFAULT 0,
                pricing_prompt REAL,
                pricing_completion REAL,
                note TEXT NOT NULL DEFAULT ''
            );

            -- Phase 2: Qualitätssicherung ----------------------------------------
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                tile_id TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                test_case_id INTEGER,
                test_case_name TEXT NOT NULL DEFAULT '',
                score INTEGER NOT NULL DEFAULT 0,
                checks TEXT NOT NULL DEFAULT '{}',
                findings TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                chars_out INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_eval_tile ON eval_runs(tile_id);
            """
        )
        _migrate(conn)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Ergänzt Spalten/Tabellen, die in älteren Datenbanken noch fehlen."""
    if "is_example" not in _columns(conn, "conversations"):
        conn.execute("ALTER TABLE conversations ADD COLUMN is_example INTEGER NOT NULL DEFAULT 0")
    # Phase 0/1: Fallback-Kette je Kachel, Bild-Uploads erkennbar machen
    if "fallback_models" not in _columns(conn, "tiles"):
        conn.execute("ALTER TABLE tiles ADD COLUMN fallback_models TEXT NOT NULL DEFAULT ''")
    if "rechner" not in _columns(conn, "tiles"):
        conn.execute("ALTER TABLE tiles ADD COLUMN rechner TEXT NOT NULL DEFAULT ''")
    if "kind" not in _columns(conn, "files"):
        conn.execute("ALTER TABLE files ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'")
    if "mime" not in _columns(conn, "files"):
        conn.execute("ALTER TABLE files ADD COLUMN mime TEXT NOT NULL DEFAULT ''")


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
