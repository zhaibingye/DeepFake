from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from app import db


TOKEN_EXPIRE_DAYS = 30


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_enabled": bool(row["is_enabled"]),
    }


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=TOKEN_EXPIRE_DAYS)
    with closing(db.get_conn()) as conn:
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


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with closing(db.get_conn()) as conn:
        row = conn.execute(
            "SELECT id, username, role, is_enabled FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return row_to_user(row)


def ensure_other_enabled_admin_exists(conn: sqlite3.Connection, user_id: int) -> None:
    row = conn.execute(
        """
        SELECT 1
        FROM users
        WHERE role = 'admin' AND is_enabled = 1 AND id != ?
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="至少保留一个启用中的管理员")


def get_current_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = get_token(authorization)
    with closing(db.get_conn()) as conn:
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
