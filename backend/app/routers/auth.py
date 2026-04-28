from __future__ import annotations

from contextlib import closing
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from app.admin_setup import create_initial_admin, has_admin_account
from app.auth import (
    create_session,
    get_current_user,
    get_token,
    get_user_by_id,
    hash_password,
    normalize_username,
    row_to_user,
    utcnow,
    verify_password,
)
from app.db import get_conn
from app.schemas import LoginPayload, RegisterPayload, SetupAdminPayload
from app.settings_service import get_allow_registration


router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/setup/status")
def setup_status() -> dict[str, bool]:
    return {"needs_admin_setup": not has_admin_account()}


@router.post("/setup/admin")
def setup_admin(payload: SetupAdminPayload) -> dict[str, Any]:
    return create_initial_admin(payload.username, payload.password)


@router.post("/auth/register")
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


@router.post("/auth/login")
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


@router.get("/auth/settings")
def auth_settings() -> dict[str, bool]:
    return {"allow_registration": get_allow_registration()}


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    token = get_token(authorization)
    with closing(get_conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    return {"status": "ok"}
