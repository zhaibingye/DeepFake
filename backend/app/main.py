from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
ANTHROPIC_VERSION = "2023-06-01"
TOKEN_EXPIRE_DAYS = 30


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
    thinking_effort: str = "high"
    max_context_window: int = 256000
    max_output_tokens: int = 32000
    is_enabled: bool = True


class ChatAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    media_type: str
    data: str


class ChatPayload(BaseModel):
    provider_id: int
    conversation_id: int | None = None
    text: str = Field(default="", max_length=20000)
    enable_thinking: bool = False
    effort: str = "high"
    attachments: list[ChatAttachment] = Field(default_factory=list)


class ConversationTitlePayload(BaseModel):
    title: str = Field(min_length=1, max_length=80)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_username(username: str) -> str:
    value = username.strip()
    if not value:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    return value


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    )
    return salt, hashed.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    _, computed = hash_password(password, salt)
    return hmac.compare_digest(computed, password_hash)


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

        registration_row = conn.execute(
            "SELECT key FROM app_settings WHERE key = 'allow_registration'"
        ).fetchone()
        if not registration_row:
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES ('allow_registration', '1', ?)",
                (utcnow(),),
            )
        conn.commit()


def ensure_admin() -> None:
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if existing:
            return
        salt, password_hash = hash_password("admin123")
        conn.execute(
            "INSERT INTO users (username, password_salt, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
            ("admin", salt, password_hash, utcnow()),
        )
        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    ensure_tables()
    ensure_admin()


def row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_enabled": bool(row["is_enabled"]),
    }


def row_to_admin_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_enabled": bool(row["is_enabled"]),
        "created_at": row["created_at"],
    }


def get_allow_registration() -> bool:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'allow_registration'"
        ).fetchone()
    return row is None or row["value"] == "1"


def provider_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "model_name": row["model_name"],
        "supports_thinking": bool(row["supports_thinking"]),
        "supports_vision": bool(row["supports_vision"]),
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


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=TOKEN_EXPIRE_DAYS)
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, token, now.isoformat(), expires_at.isoformat()),
        )
        conn.commit()
    return token


def get_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return token


def get_current_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = get_token(authorization)
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT users.id, users.username, users.role, users.is_enabled, sessions.expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效"
            )
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期"
            )
        if not row["is_enabled"]:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用"
            )
        return row_to_user(row)


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def fetch_provider(provider_id: int, include_disabled: bool = False) -> sqlite3.Row:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if not include_disabled and not row["is_enabled"]:
            raise HTTPException(status_code=400, detail="供应商已禁用")
        return row


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
    if row["content_json"]:
        content = json.loads(row["content_json"])
    return {
        "id": row["id"],
        "role": row["role"],
        "content": content,
        "thinking_text": row["thinking_text"] or "",
        "created_at": row["created_at"],
    }


def guess_media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


def validate_attachment(attachment: ChatAttachment) -> None:
    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if attachment.media_type not in allowed:
        raise HTTPException(
            status_code=400, detail=f"不支持的图片类型: {attachment.media_type}"
        )
    try:
        base64.b64decode(attachment.data, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail="图片不是合法的 base64 数据"
        ) from exc


def ensure_anthropic_messages_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="供应商 API URL 不合法")
    normalized = api_url.rstrip("/")
    if normalized.endswith("/messages"):
        return normalized
    return f"{normalized}/messages"


def message_to_anthropic_content(
    text: str, attachments: list[ChatAttachment]
) -> str | list[dict[str, Any]]:
    if not attachments:
        return text
    blocks: list[dict[str, Any]] = []
    for attachment in attachments:
        validate_attachment(attachment)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": attachment.media_type,
                    "data": attachment.data,
                },
            }
        )
    if text.strip():
        blocks.append({"type": "text", "text": text})
    return blocks


def build_history(conversation_id: int) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT role, content_text, content_json FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        content: Any = row["content_text"]
        if row["content_json"]:
            content = json.loads(row["content_json"])
        history.append({"role": row["role"], "content": content})
    return history


def build_chat_request_payload(
    provider: sqlite3.Row,
    history: list[dict[str, Any]],
    payload: ChatPayload,
    stream: bool = False,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "model": provider["model_name"],
        "max_tokens": provider["max_output_tokens"],
        "messages": history,
    }
    if payload.enable_thinking and provider["supports_thinking"]:
        request_payload["thinking"] = {"type": "adaptive"}
        request_payload["output_config"] = {
            "effort": payload.effort or provider["thinking_effort"]
        }
    if stream:
        request_payload["stream"] = True
    return request_payload


def prepare_chat_context(
    payload: ChatPayload, user: dict[str, Any]
) -> tuple[sqlite3.Row, int, Any]:
    if not payload.text.strip() and not payload.attachments:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    provider = fetch_provider(payload.provider_id)
    if payload.enable_thinking and not provider["supports_thinking"]:
        raise HTTPException(status_code=400, detail="当前模型不支持思考")
    if payload.attachments and not provider["supports_vision"]:
        raise HTTPException(status_code=400, detail="当前模型不支持图片")

    now = utcnow()
    content = message_to_anthropic_content(payload.text.strip(), payload.attachments)

    with closing(get_conn()) as conn:
        if payload.conversation_id is None:
            title_source = payload.text.strip() or (
                payload.attachments[0].name if payload.attachments else "新对话"
            )
            title = title_source[:40]
            cursor = conn.execute(
                "INSERT INTO conversations (user_id, provider_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user["id"], provider["id"], title, now, now),
            )
            conversation_id = cursor.lastrowid
        else:
            convo = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (payload.conversation_id, user["id"]),
            ).fetchone()
            if not convo:
                raise HTTPException(status_code=404, detail="会话不存在")
            conversation_id = convo["id"]
            conn.execute(
                "UPDATE conversations SET provider_id = ?, updated_at = ? WHERE id = ?",
                (provider["id"], now, conversation_id),
            )

        conn.execute(
            "INSERT INTO messages (conversation_id, role, content_text, content_json, thinking_text, created_at) VALUES (?, 'user', ?, ?, '', ?)",
            (
                conversation_id,
                payload.text.strip() if isinstance(content, str) else None,
                json.dumps(content, ensure_ascii=False)
                if isinstance(content, list)
                else None,
                now,
            ),
        )
        conn.commit()

    return provider, conversation_id, content


def save_assistant_message(
    conversation_id: int, assistant_text: str, thinking_text: str
) -> dict[str, Any]:
    assistant_created_at = utcnow()
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content_text, content_json, thinking_text, created_at) VALUES (?, 'assistant', ?, NULL, ?, ?)",
            (conversation_id, assistant_text, thinking_text, assistant_created_at),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (assistant_created_at, conversation_id),
        )
        conn.commit()
        convo = conn.execute(
            "SELECT conversations.*, providers.name AS provider_name, providers.model_name AS model_name FROM conversations JOIN providers ON providers.id = conversations.provider_id WHERE conversations.id = ?",
            (conversation_id,),
        ).fetchone()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 2",
            (conversation_id,),
        ).fetchall()
    return {
        "conversation": {
            "id": convo["id"],
            "title": convo["title"],
            "provider_id": convo["provider_id"],
            "provider_name": convo["provider_name"],
            "model_name": convo["model_name"],
            "created_at": convo["created_at"],
            "updated_at": convo["updated_at"],
        },
        "messages": [parse_message(row) for row in reversed(rows)],
    }


async def call_provider(
    provider: sqlite3.Row, payload: dict[str, Any]
) -> dict[str, Any]:
    url = ensure_anthropic_messages_url(provider["api_url"])
    headers = {
        "x-api-key": provider["api_key"],
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        detail = response.text
        raise HTTPException(status_code=502, detail=f"供应商调用失败: {detail}")
    return response.json()


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


def extract_response_content(data: dict[str, Any]) -> tuple[str, str]:
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    for block in data.get("content", []):
        block_type = block.get("type")
        if block_type == "text" and block.get("text"):
            text_parts.append(block["text"])
        elif block_type == "thinking" and block.get("thinking"):
            thinking_parts.append(block["thinking"])
    text = "\n\n".join(part.strip() for part in text_parts if part.strip())
    thinking = "\n\n".join(part.strip() for part in thinking_parts if part.strip())
    if not text:
        text = data.get("completion", "") or "模型没有返回可显示文本。"
    return text, thinking


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, username, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return {"token": token, "user": row_to_user(user)}


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


@app.get("/api/admin/providers")
def list_admin_providers(
    admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT * FROM providers ORDER BY id DESC").fetchall()
    return [provider_admin(row) for row in rows]


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
                thinking_effort, max_context_window, max_output_tokens, is_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.api_url.strip(),
                payload.api_key.strip(),
                payload.model_name.strip(),
                int(payload.supports_thinking),
                int(payload.supports_vision),
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
                thinking_effort = ?, max_context_window = ?, max_output_tokens = ?, is_enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.name.strip(),
                payload.api_url.strip(),
                payload.api_key.strip(),
                payload.model_name.strip(),
                int(payload.supports_thinking),
                int(payload.supports_vision),
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
    with closing(get_conn()) as conn:
        conn.execute(
            "UPDATE app_settings SET value = ?, updated_at = ? WHERE key = 'allow_registration'",
            ("1" if payload.allow_registration else "0", utcnow()),
        )
        conn.commit()
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
        if user["role"] == "admin" and not payload.is_enabled:
            enabled_admins = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND is_enabled = 1"
            ).fetchone()
            if enabled_admins["count"] <= 1:
                raise HTTPException(
                    status_code=400, detail="至少保留一个启用中的管理员"
                )
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
            "SELECT id, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user["id"] == admin["id"]:
            raise HTTPException(status_code=400, detail="不能删除当前管理员")
        if user["role"] == "admin":
            admin_count = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'admin'"
            ).fetchone()
            if admin_count["count"] <= 1:
                raise HTTPException(status_code=400, detail="至少保留一个管理员")
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


@app.post("/api/chat")
async def send_message(
    payload: ChatPayload, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    provider, conversation_id, _ = prepare_chat_context(payload, user)
    history = build_history(conversation_id)
    request_payload = build_chat_request_payload(provider, history, payload)
    response_data = await call_provider(provider, request_payload)
    assistant_text, thinking_text = extract_response_content(response_data)
    return save_assistant_message(conversation_id, assistant_text, thinking_text)


@app.post("/api/chat/stream")
async def stream_message(
    payload: ChatPayload, user: dict[str, Any] = Depends(get_current_user)
):
    provider, conversation_id, _ = prepare_chat_context(payload, user)
    history = build_history(conversation_id)
    request_payload = build_chat_request_payload(
        provider, history, payload, stream=True
    )

    async def event_generator():
        thinking_parts: list[str] = []
        text_parts: list[str] = []
        try:
            initial = {
                "type": "conversation",
                "conversation": {
                    "id": conversation_id,
                    "provider_id": provider["id"],
                    "provider_name": provider["name"],
                    "model_name": provider["model_name"],
                },
            }
            yield json.dumps(initial, ensure_ascii=False) + "\n"
            async for line in stream_provider_events(provider, request_payload):
                if not line or line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    break
                data = json.loads(raw)
                event_type = data.get("type")
                if event_type == "content_block_delta":
                    delta = data.get("delta", {})
                    text = delta.get("text")
                    thinking = delta.get("thinking")
                    if text:
                        text_parts.append(text)
                        yield (
                            json.dumps(
                                {"type": "text_delta", "delta": text},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                    if thinking:
                        thinking_parts.append(thinking)
                        yield (
                            json.dumps(
                                {"type": "thinking_delta", "delta": thinking},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                elif event_type == "message_delta":
                    usage = data.get("usage")
                    if usage:
                        yield (
                            json.dumps(
                                {"type": "usage", "usage": usage}, ensure_ascii=False
                            )
                            + "\n"
                        )
            assistant_text = "".join(text_parts).strip() or "模型没有返回可显示文本。"
            thinking_text = "".join(thinking_parts).strip()
            result = save_assistant_message(
                conversation_id, assistant_text, thinking_text
            )
            yield json.dumps({"type": "done", **result}, ensure_ascii=False) + "\n"
        except HTTPException as exc:
            yield (
                json.dumps({"type": "error", "detail": exc.detail}, ensure_ascii=False)
                + "\n"
            )
        except Exception as exc:  # noqa: BLE001
            yield (
                json.dumps({"type": "error", "detail": str(exc)}, ensure_ascii=False)
                + "\n"
            )

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
