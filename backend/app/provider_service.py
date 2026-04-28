from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from fastapi import HTTPException

from app.auth import utcnow
from app.db import get_conn
from app.schemas import ProviderPayload, ProviderUpdatePayload


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def normalize_provider_thinking_effort(
    api_format: str, thinking_effort: str
) -> str:
    normalized = thinking_effort.strip() or "high"
    if api_format == "openai_chat" and normalized == "max":
        return "high"
    if api_format == "openai_chat" and normalized == "xhigh":
        return "high"
    if api_format == "openai_responses" and normalized == "max":
        return "xhigh"
    if api_format != "openai_responses" and normalized == "xhigh":
        return "max"
    return normalized


def provider_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "api_format": row["api_format"],
        "model_name": row["model_name"],
        "supports_thinking": bool(row["supports_thinking"]),
        "supports_vision": bool(row["supports_vision"]),
        "supports_tool_calling": bool(row["supports_tool_calling"]),
        "thinking_effort": normalize_provider_thinking_effort(
            row["api_format"], row["thinking_effort"]
        ),
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


def list_public_providers() -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM providers WHERE is_enabled = 1 ORDER BY id DESC"
        ).fetchall()
    return [provider_public(row) for row in rows]


def list_admin_providers() -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT * FROM providers ORDER BY id DESC").fetchall()
    return [provider_admin(row) for row in rows]


def create_provider(payload: ProviderPayload) -> dict[str, Any]:
    now = utcnow()
    with closing(get_conn()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO providers (
                name, api_format, api_url, api_key, model_name, supports_thinking, supports_vision,
                supports_tool_calling, thinking_effort, max_context_window, max_output_tokens,
                is_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name.strip(),
                payload.api_format,
                payload.api_url.strip(),
                payload.api_key.strip(),
                payload.model_name.strip(),
                int(payload.supports_thinking),
                int(payload.supports_vision),
                int(payload.supports_tool_calling),
                normalize_provider_thinking_effort(
                    payload.api_format, payload.thinking_effort
                ),
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


def update_provider(provider_id: int, payload: ProviderUpdatePayload) -> dict[str, Any]:
    now = utcnow()
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id, api_url, api_key FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="供应商不存在")
        api_url = payload.api_url.strip() or existing["api_url"]
        api_key = payload.api_key.strip() or existing["api_key"]
        conn.execute(
            """
            UPDATE providers
            SET name = ?, api_format = ?, api_url = ?, api_key = ?, model_name = ?, supports_thinking = ?, supports_vision = ?,
                supports_tool_calling = ?, thinking_effort = ?, max_context_window = ?, max_output_tokens = ?,
                is_enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.name.strip(),
                payload.api_format,
                api_url,
                api_key,
                payload.model_name.strip(),
                int(payload.supports_thinking),
                int(payload.supports_vision),
                int(payload.supports_tool_calling),
                normalize_provider_thinking_effort(
                    payload.api_format, payload.thinking_effort
                ),
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


def delete_provider(provider_id: int) -> None:
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
