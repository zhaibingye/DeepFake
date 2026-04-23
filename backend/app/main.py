from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.admin_setup import create_initial_admin, has_admin_account
from app import tool_runtime, timeline
from app.chat_service import (
    SearchProviderUnavailableError,
    append_tool_result_message,
    commit_stream_chat,
    prepare_stream_chat,
    rollback_stream_chat,
)
from app import db
from app.auth import (
    create_session,
    ensure_other_enabled_admin_exists,
    get_current_user,
    get_token,
    get_user_by_id,
    hash_password,
    normalize_username,
    require_admin,
    row_to_user,
    utcnow,
    verify_password,
)
from app.db import get_conn
from app.timeline import assistant_content_from_row, message_parts_from_row

BASE_DIR = db.BASE_DIR
ANTHROPIC_VERSION = "2023-06-01"
ALLOW_REGISTRATION_KEY = "allow_registration"
SEARCH_TAVILY_API_KEY = "search_tavily_api_key"
SEARCH_TAVILY_ENABLED = "search_tavily_enabled"


app = FastAPI(title="Anthropic Chat Console")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterPayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginPayload(RegisterPayload):
    pass


class SetupAdminPayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class AdminProfilePayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    current_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class RegistrationSettingsPayload(BaseModel):
    allow_registration: bool


class AdminUserCreatePayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default="user", pattern="^(admin|user)$")
    is_enabled: bool = True


class AdminUserUpdatePayload(BaseModel):
    is_enabled: bool


class AdminUserPasswordResetPayload(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


class ProviderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    api_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1, max_length=500)
    model_name: str = Field(min_length=1, max_length=128)
    supports_thinking: bool = True
    supports_vision: bool = False
    supports_tool_calling: bool = False
    thinking_effort: str = "high"
    max_context_window: int = 256000
    max_output_tokens: int = 32000
    is_enabled: bool = True


class SearchProviderSelection(str, Enum):
    exa = "exa"
    tavily = "tavily"


class ChatAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    media_type: str
    data: str


class SearchProviderConfigPayload(BaseModel):
    api_key: str = Field(max_length=500)
    is_enabled: bool


class ChatPayload(BaseModel):
    provider_id: int
    conversation_id: int | None = None
    text: str = Field(default="", max_length=20000)
    enable_thinking: bool = False
    enable_search: bool = False
    search_provider: SearchProviderSelection | None = None
    effort: str = "high"
    attachments: list[ChatAttachment] = Field(default_factory=list)


class ConversationTitlePayload(BaseModel):
    title: str = Field(min_length=1, max_length=80)


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

@app.on_event("startup")
def on_startup() -> None:
    ensure_tables()


def row_to_admin_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_enabled": bool(row["is_enabled"]),
        "created_at": row["created_at"],
    }


def get_allow_registration() -> bool:
    return get_setting_bool(ALLOW_REGISTRATION_KEY, True)


def get_setting_value(key: str, default: str = "") -> str:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return default
    return row["value"]


def get_setting_bool(key: str, default: bool = False) -> bool:
    return get_setting_value(key, "1" if default else "0") == "1"


def upsert_setting_value(key: str, value: str) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utcnow()),
        )
        conn.commit()


def get_tavily_config() -> dict[str, Any]:
    api_key = get_setting_value(SEARCH_TAVILY_API_KEY, "").strip()
    is_enabled = get_setting_bool(SEARCH_TAVILY_ENABLED, False)
    return {
        "api_key": api_key,
        "is_enabled": is_enabled,
        "is_configured": bool(api_key),
    }


def store_tavily_config(api_key: str, is_enabled: bool) -> None:
    upsert_setting_value(SEARCH_TAVILY_API_KEY, api_key)
    upsert_setting_value(SEARCH_TAVILY_ENABLED, "1" if is_enabled else "0")


def admin_search_provider_status() -> dict[str, dict[str, Any]]:
    tavily_config = get_tavily_config()
    return {
        "exa": {
            "kind": "exa",
            "name": "Exa",
            "is_enabled": True,
            "is_configured": True,
        },
        "tavily": {
            "kind": "tavily",
            "name": "Tavily",
            "is_enabled": tavily_config["is_enabled"],
            "is_configured": tavily_config["is_configured"],
        },
    }


def public_search_provider_status() -> dict[str, dict[str, bool]]:
    status = admin_search_provider_status()
    return {
        kind: {
            "is_enabled": bool(provider["is_enabled"]),
            "is_configured": bool(provider["is_configured"]),
        }
        for kind, provider in status.items()
    }


def provider_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "model_name": row["model_name"],
        "supports_thinking": bool(row["supports_thinking"]),
        "supports_vision": bool(row["supports_vision"]),
        "supports_tool_calling": bool(row["supports_tool_calling"]),
        "thinking_effort": row["thinking_effort"],
        "max_context_window": row["max_context_window"],
        "max_output_tokens": row["max_output_tokens"],
        "is_enabled": bool(row["is_enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def provider_admin(row: sqlite3.Row) -> dict[str, Any]:
    data = provider_public(row)
    data["api_key_masked"] = mask_secret(row["api_key"])
    return data


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def fetch_conversation(conversation_id: int, user_id: int) -> sqlite3.Row:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="会话不存在")
        return row


def parse_message(row: sqlite3.Row) -> dict[str, Any]:
    content = row["content_text"]
    if row["role"] != "assistant" and row["content_json"]:
        content = json.loads(row["content_json"])
    message = {
        "id": row["id"],
        "role": row["role"],
        "content": content,
        "thinking_text": row["thinking_text"] or "",
        "created_at": row["created_at"],
    }
    if row["role"] == "assistant":
        message["content"] = assistant_content_from_row(row)
        message["parts"] = message_parts_from_row(row)
    return message


def guess_media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


def ensure_anthropic_messages_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="供应商 API URL 不合法")
    normalized = api_url.rstrip("/")
    if normalized.endswith("/messages"):
        return normalized
    return f"{normalized}/messages"


async def stream_provider_events(provider: sqlite3.Row, payload: dict[str, Any]):
    url = ensure_anthropic_messages_url(provider["api_url"])
    headers = {
        "x-api-key": provider["api_key"],
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    client = httpx.AsyncClient(timeout=180)
    try:
        async with client.stream(
            "POST", url, headers=headers, json=payload
        ) as response:
            if response.status_code >= 400:
                detail = await response.aread()
                raise HTTPException(
                    status_code=502,
                    detail=f"供应商调用失败: {detail.decode('utf-8', errors='ignore')}",
                )
            async for line in response.aiter_lines():
                yield line
    finally:
        await client.aclose()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/setup/status")
def setup_status() -> dict[str, bool]:
    return {"needs_admin_setup": not has_admin_account()}


@app.post("/api/setup/admin")
def setup_admin(payload: SetupAdminPayload) -> dict[str, Any]:
    return create_initial_admin(payload.username, payload.password)


@app.post("/api/auth/register")
def register(payload: RegisterPayload) -> dict[str, Any]:
    if not get_allow_registration():
        raise HTTPException(status_code=403, detail="当前已关闭注册")
    username = normalize_username(payload.username)
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        salt, password_hash = hash_password(payload.password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at) VALUES (?, ?, ?, 'user', 1, ?)",
            (username, salt, password_hash, utcnow()),
        )
        conn.commit()
        user_id = cursor.lastrowid
    token = create_session(user_id)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=500, detail="用户创建后读取失败")
    return {"token": token, "user": user}


@app.post("/api/auth/login")
def login(payload: LoginPayload) -> dict[str, Any]:
    username = normalize_username(payload.username)
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not user or not verify_password(
            payload.password, user["password_salt"], user["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user["is_enabled"]:
            raise HTTPException(status_code=403, detail="账号已停用")
    token = create_session(user["id"])
    return {"token": token, "user": row_to_user(user)}


@app.get("/api/auth/settings")
def auth_settings() -> dict[str, bool]:
    return {"allow_registration": get_allow_registration()}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    token = get_token(authorization)
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    return {"status": "ok"}


@app.get("/api/providers")
def list_public_providers(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM providers WHERE is_enabled = 1 ORDER BY id DESC"
        ).fetchall()
    return [provider_public(row) for row in rows]


@app.get("/api/search-providers")
def list_search_providers() -> dict[str, dict[str, bool]]:
    return public_search_provider_status()


@app.get("/api/admin/providers")
def list_admin_providers(
    admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT * FROM providers ORDER BY id DESC").fetchall()
    return [provider_admin(row) for row in rows]


@app.get("/api/admin/search-providers")
def list_admin_search_providers(
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, dict[str, Any]]:
    return admin_search_provider_status()


@app.put("/api/admin/search-providers/tavily")
def update_tavily_search_provider(
    payload: SearchProviderConfigPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    store_tavily_config(payload.api_key.strip(), payload.is_enabled)
    return admin_search_provider_status()["tavily"]


@app.post("/api/admin/providers")
def create_provider(
    payload: ProviderPayload, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    now = utcnow()
    with closing(get_conn()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO providers (
                name, api_url, api_key, model_name, supports_thinking, supports_vision,
                supports_tool_calling, thinking_effort, max_context_window, max_output_tokens,
                is_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.api_url.strip(),
                payload.api_key.strip(),
                payload.model_name.strip(),
                int(payload.supports_thinking),
                int(payload.supports_vision),
                int(payload.supports_tool_calling),
                payload.thinking_effort,
                payload.max_context_window,
                payload.max_output_tokens,
                int(payload.is_enabled),
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return provider_admin(row)


@app.put("/api/admin/providers/{provider_id}")
def update_provider(
    provider_id: int,
    payload: ProviderPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    now = utcnow()
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="供应商不存在")
        conn.execute(
            """
            UPDATE providers
            SET name = ?, api_url = ?, api_key = ?, model_name = ?, supports_thinking = ?, supports_vision = ?,
                supports_tool_calling = ?, thinking_effort = ?, max_context_window = ?, max_output_tokens = ?,
                is_enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.name.strip(),
                payload.api_url.strip(),
                payload.api_key.strip(),
                payload.model_name.strip(),
                int(payload.supports_thinking),
                int(payload.supports_vision),
                int(payload.supports_tool_calling),
                payload.thinking_effort,
                payload.max_context_window,
                payload.max_output_tokens,
                int(payload.is_enabled),
                now,
                provider_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
    return provider_admin(row)


@app.delete("/api/admin/providers/{provider_id}")
def delete_provider(
    provider_id: int, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, str]:
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="供应商不存在")
        in_use = conn.execute(
            "SELECT id FROM conversations WHERE provider_id = ? LIMIT 1", (provider_id,)
        ).fetchone()
        if in_use:
            raise HTTPException(
                status_code=400, detail="该供应商已有会话记录，不能删除"
            )
        conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        conn.commit()
    return {"status": "ok"}


@app.put("/api/admin/profile")
def update_admin_profile(
    payload: AdminProfilePayload, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    username = normalize_username(payload.username)
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (admin["id"],)
        ).fetchone()
        if not verify_password(
            payload.current_password, user["password_salt"], user["password_hash"]
        ):
            raise HTTPException(status_code=400, detail="当前密码错误")
        duplicate = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (username, admin["id"]),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=400, detail="用户名已存在")
        salt, password_hash = hash_password(payload.new_password)
        conn.execute(
            "UPDATE users SET username = ?, password_salt = ?, password_hash = ? WHERE id = ?",
            (username, salt, password_hash, admin["id"]),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT id, username, role, is_enabled FROM users WHERE id = ?",
            (admin["id"],),
        ).fetchone()
    return row_to_user(updated)


@app.get("/api/admin/settings")
def get_admin_settings(
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    return {"allow_registration": get_allow_registration()}


@app.put("/api/admin/settings")
def update_admin_settings(
    payload: RegistrationSettingsPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    upsert_setting_value(
        ALLOW_REGISTRATION_KEY,
        "1" if payload.allow_registration else "0",
    )
    return {"allow_registration": payload.allow_registration}


@app.get("/api/admin/users")
def list_admin_users(
    admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT id, username, role, is_enabled, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [row_to_admin_user(row) for row in rows]


@app.post("/api/admin/users")
def create_admin_user(
    payload: AdminUserCreatePayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    username = normalize_username(payload.username)
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        salt, password_hash = hash_password(payload.password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                username,
                salt,
                password_hash,
                payload.role,
                int(payload.is_enabled),
                utcnow(),
            ),
        )
        conn.commit()
        user = conn.execute(
            "SELECT id, username, role, is_enabled, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return row_to_admin_user(user)


@app.put("/api/admin/users/{user_id}")
def update_admin_user(
    user_id: int,
    payload: AdminUserUpdatePayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, username, role, is_enabled, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user["id"] == admin["id"] and not payload.is_enabled:
            raise HTTPException(status_code=400, detail="不能停用当前管理员")
        if user["role"] == "admin" and user["is_enabled"] and not payload.is_enabled:
            ensure_other_enabled_admin_exists(conn, user_id)
        conn.execute(
            "UPDATE users SET is_enabled = ? WHERE id = ?",
            (int(payload.is_enabled), user_id),
        )
        if not payload.is_enabled:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        updated = conn.execute(
            "SELECT id, username, role, is_enabled, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return row_to_admin_user(updated)


@app.delete("/api/admin/users/{user_id}")
def delete_admin_user(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, role, is_enabled FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user["id"] == admin["id"]:
            raise HTTPException(status_code=400, detail="不能删除当前管理员")
        if user["role"] == "admin" and user["is_enabled"]:
            ensure_other_enabled_admin_exists(conn, user_id)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)",
            (user_id,),
        )
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return {"status": "ok"}


@app.put("/api/admin/users/{user_id}/password")
def reset_admin_user_password(
    user_id: int,
    payload: AdminUserPasswordResetPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        salt, password_hash = hash_password(payload.new_password)
        conn.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (salt, password_hash, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    return {"status": "ok"}


@app.get("/api/conversations")
def list_conversations(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT conversations.*, providers.name AS provider_name, providers.model_name AS model_name
            FROM conversations
            JOIN providers ON providers.id = conversations.provider_id
            WHERE conversations.user_id = ?
            ORDER BY conversations.updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "provider_id": row["provider_id"],
            "provider_name": row["provider_name"],
            "model_name": row["model_name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@app.get("/api/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    convo = fetch_conversation(conversation_id, user["id"])
    with closing(get_conn()) as conn:
        messages = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return {
        "conversation": {
            "id": convo["id"],
            "title": convo["title"],
            "provider_id": convo["provider_id"],
            "created_at": convo["created_at"],
            "updated_at": convo["updated_at"],
        },
        "messages": [parse_message(row) for row in messages],
    }


@app.put("/api/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    payload: ConversationTitlePayload,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    with closing(get_conn()) as conn:
        convo = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user["id"]),
        ).fetchone()
        if not convo:
            raise HTTPException(status_code=404, detail="会话不存在")
        now = utcnow()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title[:80], now, conversation_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT conversations.*, providers.name AS provider_name, providers.model_name AS model_name FROM conversations JOIN providers ON providers.id = conversations.provider_id WHERE conversations.id = ?",
            (conversation_id,),
        ).fetchone()
    return {
        "id": updated["id"],
        "title": updated["title"],
        "provider_id": updated["provider_id"],
        "provider_name": updated["provider_name"],
        "model_name": updated["model_name"],
        "created_at": updated["created_at"],
        "updated_at": updated["updated_at"],
    }


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    with closing(get_conn()) as conn:
        convo = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user["id"]),
        ).fetchone()
        if not convo:
            raise HTTPException(status_code=404, detail="会话不存在")
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
    return {"status": "ok"}


@app.post("/api/chat/stream")
async def stream_message(
    payload: ChatPayload, user: dict[str, Any] = Depends(get_current_user)
):
    try:
        context = prepare_stream_chat(payload, user)
    except SearchProviderUnavailableError as exc:
        detail = exc.detail

        async def unavailable_event_generator():
            yield (
                json.dumps({"type": "error", "detail": detail}, ensure_ascii=False)
                + "\n"
            )

        return StreamingResponse(
            unavailable_event_generator(),
            media_type="application/x-ndjson",
        )

    async def event_generator():
        completed = False
        committed = False
        active_parts: dict[int, dict[str, Any]] = {}
        part_positions: dict[int, int] = {}
        assistant_parts: list[dict[str, Any]] = []
        pending_assistant_tool_uses: list[dict[str, Any]] = []
        pending_tool_results: list[tuple[str, dict[str, str]]] = []
        pending_tool_use_inputs: dict[int, dict[str, Any]] = {}
        thinking_count = 0
        answer_count = 0
        fallback_index = 0

        def emit(event: dict[str, Any]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        def remember_part(index: int, part: dict[str, Any]) -> dict[str, Any]:
            active_parts[index] = part
            if index in part_positions:
                assistant_parts[part_positions[index]] = part
            else:
                part_positions[index] = len(assistant_parts)
                assistant_parts.append(part)
            return part

        def start_part(
            index: int,
            part_id: str,
            kind: str,
            **fields: Any,
        ) -> dict[str, Any]:
            part = timeline.create_part(part_id, kind, **fields)
            return remember_part(index, part)

        def resolve_index(
            data: dict[str, Any],
            *,
            prefer_active: bool = True,
            expected_kind: str | None = None,
        ) -> int:
            nonlocal fallback_index
            raw_index = data.get("index")
            if isinstance(raw_index, int):
                return raw_index
            if prefer_active and active_parts:
                if expected_kind:
                    for active_index in reversed(active_parts):
                        if active_parts[active_index].get("kind") == expected_kind:
                            return active_index
                else:
                    return next(reversed(active_parts))
            fallback_index += 1
            return 1000 + fallback_index

        def tool_kind_from_name(tool_name: str) -> str:
            if tool_name == "exa_search":
                return "exa"
            if tool_name == "tavily_search":
                return "tavily"
            raise RuntimeError("未知搜索工具")

        try:
            initial = {
                "type": "conversation",
                "conversation": {
                    "id": context.conversation_id,
                    "provider_id": context.provider["id"],
                    "provider_name": context.provider["name"],
                    "model_name": context.provider["model_name"],
                },
            }
            yield emit(initial)
            while True:
                follow_up_required = False
                async for line in stream_provider_events(
                    context.provider, context.request_payload
                ):
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if raw == "[DONE]":
                        if pending_tool_results:
                            follow_up_required = True
                        else:
                            completed = True
                        break
                    data = json.loads(raw)
                    event_type = data.get("type")

                    if event_type in {"message_stop", "response.completed"}:
                        if pending_tool_results:
                            follow_up_required = True
                        else:
                            completed = True
                        break

                    if event_type in {"error", "response.error"}:
                        error_payload = data.get("error")
                        detail = (
                            error_payload.get("message")
                            if isinstance(error_payload, dict)
                            else None
                        )
                        detail = (
                            detail
                            or data.get("detail")
                            or (error_payload if isinstance(error_payload, str) else None)
                            or "供应商流返回错误事件"
                        )
                        raise RuntimeError(detail)

                    if event_type == "content_block_start":
                        index = resolve_index(data, prefer_active=False)
                        content_block = data.get("content_block")
                        if not isinstance(content_block, dict):
                            continue
                        block_type = content_block.get("type")
                        if block_type == "thinking":
                            thinking_count += 1
                            part = start_part(
                                index,
                                f"thinking-{thinking_count}",
                                "thinking",
                                text="",
                            )
                            yield emit({"type": "timeline_part_start", "part": part})
                            continue
                        if block_type == "text":
                            answer_count += 1
                            part = start_part(
                                index,
                                f"answer-{answer_count}",
                                "answer",
                                text="",
                            )
                            yield emit({"type": "timeline_part_start", "part": part})
                            continue
                        if block_type == "tool_use":
                            tool_name = str(content_block.get("name") or "").strip()
                            part_id = str(content_block.get("id") or f"tool-{index}")
                            tool_input = content_block.get("input", {})
                            if not isinstance(tool_input, dict):
                                tool_input = {}
                            pending_tool_use_inputs[index] = {
                                "type": "tool_use",
                                "id": part_id,
                                "name": tool_name,
                                "input": tool_input,
                                "partial_json": "",
                            }
                            part = start_part(
                                index,
                                part_id,
                                "tool",
                                tool_name=tool_name,
                                label=tool_name,
                                input=json.dumps(
                                    tool_input,
                                    ensure_ascii=False,
                                ),
                            )
                            yield emit({"type": "timeline_part_start", "part": part})
                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "input_json_delta":
                            index = resolve_index(data)
                            tool_use_block = pending_tool_use_inputs.get(index)
                            if tool_use_block is not None:
                                tool_use_block["partial_json"] = (
                                    f"{tool_use_block['partial_json']}{delta.get('partial_json', '')}"
                                )
                            continue
                        text = delta.get("text")
                        thinking = delta.get("thinking")
                        if thinking:
                            index = resolve_index(data, expected_kind="thinking")
                            part = active_parts.get(index)
                            if not part:
                                thinking_count += 1
                                part = start_part(
                                    index,
                                    f"thinking-{thinking_count}",
                                    "thinking",
                                    text="",
                                )
                                yield emit(
                                    {"type": "timeline_part_start", "part": part}
                                )
                            updated_part = timeline.append_text(part, thinking)
                            remember_part(index, updated_part)
                            yield emit(
                                {
                                    "type": "timeline_part_delta",
                                    "part_id": updated_part["id"],
                                    "delta": {"text": thinking},
                                }
                            )
                        if text:
                            index = resolve_index(data, expected_kind="answer")
                            part = active_parts.get(index)
                            if not part:
                                answer_count += 1
                                part = start_part(
                                    index,
                                    f"answer-{answer_count}",
                                    "answer",
                                    text="",
                                )
                                yield emit(
                                    {"type": "timeline_part_start", "part": part}
                                )
                            updated_part = timeline.append_text(part, text)
                            remember_part(index, updated_part)
                            yield emit(
                                {
                                    "type": "timeline_part_delta",
                                    "part_id": updated_part["id"],
                                    "delta": {"text": text},
                                }
                            )
                    elif event_type == "content_block_stop":
                        index = resolve_index(data)
                        tool_use_block = pending_tool_use_inputs.pop(index, None)
                        if tool_use_block is not None:
                            part = active_parts.pop(index, None)
                            if not part:
                                continue
                            tool_input = tool_use_block["input"]
                            partial_json = str(tool_use_block.get("partial_json", "")).strip()
                            if partial_json:
                                parsed_input = json.loads(partial_json)
                                if not isinstance(parsed_input, dict):
                                    raise RuntimeError("工具参数格式不合法")
                                tool_input = parsed_input
                            tool_use_block["input"] = tool_input
                            part = remember_part(
                                index,
                                {
                                    **part,
                                    "input": json.dumps(tool_input, ensure_ascii=False),
                                },
                            )
                            try:
                                tool_result = await asyncio.to_thread(
                                    tool_runtime.execute_native_search_tool,
                                    tool_kind_from_name(str(tool_use_block["name"])),
                                    tool_input,
                                    get_tavily_config().get("api_key", "").strip(),
                                )
                            except Exception as exc:  # noqa: BLE001
                                failed_part = timeline.fail_part(part, str(exc))
                                remember_part(index, failed_part)
                                yield emit(
                                    {
                                        "type": "timeline_part_error",
                                        "part_id": part["id"],
                                        "detail": str(exc),
                                    }
                                )
                                raise
                            updated_part = timeline.finalize_part(
                                {
                                    **part,
                                    "label": tool_result["label"],
                                    "detail": tool_result["detail"],
                                    "output": tool_result["output"],
                                }
                            )
                            remember_part(index, updated_part)
                            pending_assistant_tool_uses.append(
                                {
                                    "type": "tool_use",
                                    "id": str(tool_use_block["id"]),
                                    "name": str(tool_use_block["name"]),
                                    "input": tool_input,
                                }
                            )
                            pending_tool_results.append((str(tool_use_block["id"]), tool_result))
                            yield emit(
                                {
                                    "type": "timeline_part_delta",
                                    "part_id": part["id"],
                                    "delta": {
                                        "label": tool_result["label"],
                                        "detail": tool_result["detail"],
                                        "output": tool_result["output"],
                                    },
                                }
                            )
                            yield emit(
                                {
                                    "type": "timeline_part_end",
                                    "part_id": updated_part["id"],
                                }
                            )
                            active_parts.pop(index, None)
                            part_positions.pop(index, None)
                            continue
                        part = active_parts.pop(index, None)
                        if not part:
                            continue
                        finalized_part = part
                        if part.get("status") != "done":
                            finalized_part = timeline.finalize_part(part)
                            remember_part(index, finalized_part)
                            active_parts.pop(index, None)
                        yield emit(
                            {
                                "type": "timeline_part_end",
                                "part_id": finalized_part["id"],
                            }
                        )
                        part_positions.pop(index, None)
                    elif event_type == "message_delta":
                        usage = data.get("usage")
                        if usage:
                            yield emit({"type": "usage", "usage": usage})

                if follow_up_required:
                    append_tool_result_message(
                        context.request_payload,
                        pending_assistant_tool_uses,
                        [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": tool_result["output"],
                            }
                            for tool_use_id, tool_result in pending_tool_results
                        ],
                    )
                    pending_assistant_tool_uses.clear()
                    pending_tool_results.clear()
                    continue
                if completed:
                    break
                raise RuntimeError("流式响应未正确完成")

            for index, part in list(active_parts.items()):
                finalized_part = part
                if part.get("status") != "done":
                    finalized_part = timeline.finalize_part(part)
                    remember_part(index, finalized_part)
                    active_parts.pop(index, None)
                yield emit(
                    {
                        "type": "timeline_part_end",
                        "part_id": finalized_part["id"],
                    }
                )
                active_parts.pop(index, None)
                part_positions.pop(index, None)

            assistant_content_json = json.dumps(
                {"parts": assistant_parts},
                ensure_ascii=False,
            )
            result = commit_stream_chat(
                context,
                timeline.answer_text_from_parts(assistant_parts),
                timeline.thinking_text_from_parts(assistant_parts),
                assistant_content_json=assistant_content_json,
            )
            committed = True
            yield emit({"type": "done", **result})
        except asyncio.CancelledError:
            if not committed:
                rollback_stream_chat(context)
            raise
        except HTTPException as exc:
            if not committed:
                rollback_stream_chat(context)
            yield emit({"type": "error", "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001
            if not committed:
                rollback_stream_chat(context)
            yield emit({"type": "error", "detail": str(exc)})

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
