from __future__ import annotations

from contextlib import closing

from app.auth import utcnow
from app.db import get_conn
from app.settings_service import (
    ALLOW_REGISTRATION_KEY,
    SEARCH_TAVILY_API_KEY,
    SEARCH_TAVILY_ENABLED,
)


def ensure_tables() -> None:
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                api_format TEXT NOT NULL DEFAULT 'anthropic_messages',
                api_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model_name TEXT NOT NULL,
                supports_thinking INTEGER NOT NULL DEFAULT 1,
                supports_vision INTEGER NOT NULL DEFAULT 0,
                supports_tool_calling INTEGER NOT NULL DEFAULT 0,
                thinking_effort TEXT NOT NULL DEFAULT 'high',
                max_context_window INTEGER NOT NULL DEFAULT 256000,
                max_output_tokens INTEGER NOT NULL DEFAULT 32000,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(provider_id) REFERENCES providers(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content_text TEXT,
                content_json TEXT,
                thinking_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_enabled" not in columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 1"
            )
        provider_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(providers)").fetchall()
        }
        if "supports_tool_calling" not in provider_columns:
            conn.execute(
                "ALTER TABLE providers ADD COLUMN supports_tool_calling INTEGER NOT NULL DEFAULT 0"
            )
        if "api_format" not in provider_columns:
            conn.execute(
                "ALTER TABLE providers ADD COLUMN api_format TEXT NOT NULL DEFAULT 'anthropic_messages'"
            )

        default_settings = {
            ALLOW_REGISTRATION_KEY: "1",
            SEARCH_TAVILY_API_KEY: "",
            SEARCH_TAVILY_ENABLED: "0",
        }
        for key, value in default_settings.items():
            setting_row = conn.execute(
                "SELECT key FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
            if setting_row:
                continue
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, utcnow()),
            )
        conn.commit()
