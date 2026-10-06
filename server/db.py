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
            -- Phase 0: Messbarkeit (Tokens, Kosten, Laufzeit) je LLM-Call
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                tile_id TEXT,
                feature TEXT NOT NULL DEFAULT 'chat',
                model TEXT NOT NULL,
                model_requested TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                tokens_estimated INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at);
            CREATE INDEX IF NOT EXISTS idx_llm_calls_tile ON llm_calls(tile_id);
            -- Phase 0: Audit-Log (wer/wann/was) – Voraussetzung für Kommunen
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'anonym',
                event TEXT NOT NULL,
                tile_id TEXT,
                conversation_id TEXT,
                detail TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
            -- Phase 0: Ergebnis-Cache der Modell-/Endpunkt-Prüfung
            CREATE TABLE IF NOT EXISTS model_health (
                model TEXT PRIMARY KEY,
                checked_at TEXT NOT NULL,
                ok INTEGER NOT NULL DEFAULT 0,
                endpoints INTEGER NOT NULL DEFAULT 0,
                uptime REAL NOT NULL DEFAULT 0,
                context_length INTEGER NOT NULL DEFAULT 0,
                structured INTEGER NOT NULL DEFAULT 0,
                vision INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT ''
            );
            -- Phase 1: Artefakte (Excel/JSON/SVG/…) je Unterhaltung
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                tile_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                meta TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_conv ON artifacts(conversation_id);
            -- Phase 2: Eval-Läufe (Regressionsschutz für Prompts/Modelle)
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tile_id TEXT NOT NULL,
                model TEXT NOT NULL,
                test_name TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                max_score INTEGER NOT NULL DEFAULT 0,
                checks TEXT NOT NULL DEFAULT '[]',
                content TEXT NOT NULL DEFAULT '',
                cost_usd REAL NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
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
    if "fallback_models" not in _columns(conn, "tiles"):
        # Phase 0: Fallback-Kette je Kachel (JSON-Liste von Modell-IDs)
        conn.execute("ALTER TABLE tiles ADD COLUMN fallback_models TEXT NOT NULL DEFAULT ''")
    # Phase 0: Usage-Angaben direkt an der Assistenten-Nachricht (Anzeige im Chat)
    msg_cols = _columns(conn, "messages")
    for name, typ in [
        ("model", "TEXT NOT NULL DEFAULT ''"),
        ("prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("completion_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("cost_usd", "REAL NOT NULL DEFAULT 0"),
        ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if name not in msg_cols:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {typ}")


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
