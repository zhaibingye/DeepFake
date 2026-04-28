from __future__ import annotations

from contextlib import closing
from typing import Any

from fastapi import HTTPException

from app.auth import (
    ensure_other_enabled_admin_exists,
    hash_password,
    normalize_username,
    row_to_user,
    verify_password,
    utcnow,
)
from app.db import get_conn
from app.schemas import (
    AdminProfilePayload,
    AdminUserCreatePayload,
    AdminUserPasswordResetPayload,
    AdminUserUpdatePayload,
    RegistrationSettingsPayload,
    SearchProviderConfigPayload,
)
from app.settings_service import (
    ALLOW_REGISTRATION_KEY,
    admin_search_provider_status,
    get_allow_registration,
    get_exa_config,
    get_tavily_config,
    store_exa_config,
    store_tavily_config,
    upsert_setting_value,
)


def row_to_admin_user(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_enabled": bool(row["is_enabled"]),
        "created_at": row["created_at"],
    }


def list_admin_search_providers() -> dict[str, dict[str, Any]]:
    return admin_search_provider_status()


def update_exa_search_provider(
    payload: SearchProviderConfigPayload,
) -> dict[str, Any]:
    existing = get_exa_config()
    api_key = payload.api_key.strip() or existing["api_key"]
    store_exa_config(api_key, payload.is_enabled)
    return admin_search_provider_status()["exa"]


def update_tavily_search_provider(
    payload: SearchProviderConfigPayload,
) -> dict[str, Any]:
    existing = get_tavily_config()
    api_key = payload.api_key.strip() or existing["api_key"]
    store_tavily_config(api_key, payload.is_enabled)
    return admin_search_provider_status()["tavily"]


def update_admin_profile(
    admin_id: int, payload: AdminProfilePayload
) -> dict[str, Any]:
    username = normalize_username(payload.username)
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (admin_id,)
        ).fetchone()
        if not verify_password(
            payload.current_password, user["password_salt"], user["password_hash"]
        ):
            raise HTTPException(status_code=400, detail="当前密码错误")
        duplicate = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (username, admin_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=400, detail="用户名已存在")
        salt, password_hash = hash_password(payload.new_password)
        conn.execute(
            "UPDATE users SET username = ?, password_salt = ?, password_hash = ? WHERE id = ?",
            (username, salt, password_hash, admin_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT id, username, role, is_enabled FROM users WHERE id = ?",
            (admin_id,),
        ).fetchone()
    return row_to_user(updated)


def get_admin_settings() -> dict[str, bool]:
    return {"allow_registration": get_allow_registration()}


def update_admin_settings(
    payload: RegistrationSettingsPayload,
) -> dict[str, bool]:
    upsert_setting_value(
        ALLOW_REGISTRATION_KEY,
        "1" if payload.allow_registration else "0",
    )
    return {"allow_registration": payload.allow_registration}


def list_admin_users() -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT id, username, role, is_enabled, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [row_to_admin_user(row) for row in rows]


def create_admin_user(payload: AdminUserCreatePayload) -> dict[str, Any]:
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


def update_admin_user(
    user_id: int, admin_id: int, payload: AdminUserUpdatePayload
) -> dict[str, Any]:
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, username, role, is_enabled, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user["id"] == admin_id and not payload.is_enabled:
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


def delete_admin_user(user_id: int, admin_id: int) -> None:
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT id, role, is_enabled FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user["id"] == admin_id:
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


def reset_admin_user_password(
    user_id: int, payload: AdminUserPasswordResetPayload
) -> None:
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
