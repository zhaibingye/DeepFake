from __future__ import annotations

from contextlib import closing
from typing import Any

from fastapi import HTTPException, status

from app.auth import (
    create_session,
    get_user_by_id,
    hash_password,
    normalize_username,
    utcnow,
)
from app.db import get_conn


def has_admin_account() -> bool:
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
    return existing is not None


def create_initial_admin(username: str, password: str) -> dict[str, Any]:
    normalized_username = normalize_username(username)
    with closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            existing_admin = conn.execute(
                "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone()
            if existing_admin:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="管理员已初始化"
                )

            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?", (normalized_username,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail="用户名已存在")

            salt, password_hash = hash_password(password)
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, password_salt, password_hash, role, is_enabled, created_at
                ) VALUES (?, ?, ?, 'admin', 1, ?)
                """,
                (normalized_username, salt, password_hash, utcnow()),
            )
            conn.commit()
            user_id = cursor.lastrowid
        except Exception:
            conn.rollback()
            raise

    token = create_session(user_id)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=500, detail="用户创建后读取失败")
    return {"token": token, "user": user}
