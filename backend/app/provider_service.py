from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from fastapi import HTTPException

from app.auth import utcnow
from app.db import get_conn
from app.schemas import ProviderModelPayload, ProviderPayload, ProviderUpdatePayload


PROVIDER_SELECT = """
    SELECT
        p.id AS id,
        p.connection_id AS connection_id,
        COALESCE(c.name, p.name) AS name,
        COALESCE(c.api_format, p.api_format) AS api_format,
        COALESCE(c.api_url, p.api_url) AS api_url,
        COALESCE(c.api_key, p.api_key) AS api_key,
        p.model_name AS model_name,
        p.supports_thinking AS supports_thinking,
        p.supports_vision AS supports_vision,
        p.supports_tool_calling AS supports_tool_calling,
        p.thinking_effort AS thinking_effort,
        p.max_context_window AS max_context_window,
        p.max_output_tokens AS max_output_tokens,
        p.is_enabled AS is_enabled,
        p.created_at AS created_at,
        p.updated_at AS updated_at,
        COALESCE(c.created_at, p.created_at) AS connection_created_at,
        COALESCE(c.updated_at, p.updated_at) AS connection_updated_at
    FROM providers p
    LEFT JOIN provider_connections c ON c.id = p.connection_id
"""


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def normalize_provider_thinking_effort(
    api_format: str, thinking_effort: str
) -> str:
    normalized = thinking_effort.strip() or "high"
    if api_format == "deepseek_chat":
        if normalized in {"low", "medium"}:
            return "high"
        if normalized == "xhigh":
            return "max"
        return normalized if normalized in {"high", "max"} else "high"
    if api_format == "siliconflow_chat":
        return normalized if normalized in {"low", "medium", "high"} else "high"
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
        "connection_id": row["connection_id"],
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


def provider_group_admin(rows: list[sqlite3.Row]) -> dict[str, Any]:
    first = rows[0]
    connection_id = first["connection_id"] or first["id"]
    return {
        "id": connection_id,
        "name": first["name"],
        "api_format": first["api_format"],
        "api_key_masked": mask_secret(first["api_key"]),
        "model_count": len(rows),
        "models": [provider_admin(row) for row in rows],
        "created_at": first["connection_created_at"],
        "updated_at": first["connection_updated_at"],
    }


def _fetch_provider_rows_for_connection(
    conn: sqlite3.Connection, connection_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        f"{PROVIDER_SELECT} WHERE p.connection_id = ? ORDER BY p.id DESC",
        (connection_id,),
    ).fetchall()


def _normalize_models(
    api_format: str, models: list[ProviderModelPayload]
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_model_names: set[str] = set()
    for model in models:
        model_name = model.model_name.strip()
        if not model_name:
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        model_key = model_name.lower()
        if model_key in seen_model_names:
            raise HTTPException(status_code=400, detail="同一供应商下不能重复添加同名模型")
        seen_model_names.add(model_key)
        normalized.append(
            {
                "id": model.id,
                "model_name": model_name,
                "supports_thinking": int(model.supports_thinking),
                "supports_vision": int(model.supports_vision),
                "supports_tool_calling": int(model.supports_tool_calling),
                "thinking_effort": normalize_provider_thinking_effort(
                    api_format, model.thinking_effort
                ),
                "max_context_window": model.max_context_window,
                "max_output_tokens": model.max_output_tokens,
                "is_enabled": int(model.is_enabled),
            }
        )
    return normalized


def _insert_provider_model(
    conn: sqlite3.Connection,
    connection_id: int,
    *,
    name: str,
    api_format: str,
    api_url: str,
    api_key: str,
    model: dict[str, Any],
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO providers (
            connection_id, name, api_format, api_url, api_key, model_name,
            supports_thinking, supports_vision, supports_tool_calling,
            thinking_effort, max_context_window, max_output_tokens,
            is_enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            connection_id,
            name,
            api_format,
            api_url,
            api_key,
            model["model_name"],
            model["supports_thinking"],
            model["supports_vision"],
            model["supports_tool_calling"],
            model["thinking_effort"],
            model["max_context_window"],
            model["max_output_tokens"],
            model["is_enabled"],
            now,
            now,
        ),
    )


def _delete_models_if_unused(
    conn: sqlite3.Connection, model_ids: set[int], message: str
) -> None:
    if not model_ids:
        return
    placeholders = ",".join("?" for _ in model_ids)
    in_use = conn.execute(
        f"SELECT id FROM conversations WHERE provider_id IN ({placeholders}) LIMIT 1",
        tuple(model_ids),
    ).fetchone()
    if in_use:
        raise HTTPException(status_code=400, detail=message)
    conn.execute(
        f"DELETE FROM providers WHERE id IN ({placeholders})",
        tuple(model_ids),
    )


def list_public_providers() -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"{PROVIDER_SELECT} WHERE p.is_enabled = 1 ORDER BY p.connection_id DESC, p.id DESC"
        ).fetchall()
    return [provider_public(row) for row in rows]


def list_admin_providers() -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"{PROVIDER_SELECT} ORDER BY p.connection_id DESC, p.id DESC"
        ).fetchall()
    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        connection_id = row["connection_id"] or row["id"]
        grouped.setdefault(connection_id, []).append(row)
    return [provider_group_admin(group_rows) for group_rows in grouped.values()]


def create_provider(payload: ProviderPayload) -> dict[str, Any]:
    now = utcnow()
    name = payload.name.strip()
    api_url = payload.api_url.strip()
    api_key = payload.api_key.strip()
    models = _normalize_models(payload.api_format, payload.models)
    with closing(get_conn()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO provider_connections (
                name, api_format, api_url, api_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                payload.api_format,
                api_url,
                api_key,
                now,
                now,
            ),
        )
        connection_id = int(cursor.lastrowid)
        for model in models:
            _insert_provider_model(
                conn,
                connection_id,
                name=name,
                api_format=payload.api_format,
                api_url=api_url,
                api_key=api_key,
                model=model,
                now=now,
            )
        conn.commit()
        rows = _fetch_provider_rows_for_connection(conn, connection_id)
    return provider_group_admin(rows)


def update_provider(connection_id: int, payload: ProviderUpdatePayload) -> dict[str, Any]:
    now = utcnow()
    name = payload.name.strip()
    models = _normalize_models(payload.api_format, payload.models)
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id, api_url, api_key FROM provider_connections WHERE id = ?",
            (connection_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="供应商不存在")
        api_url = payload.api_url.strip() or existing["api_url"]
        api_key = payload.api_key.strip() or existing["api_key"]
        conn.execute(
            """
            UPDATE provider_connections
            SET name = ?, api_format = ?, api_url = ?, api_key = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                payload.api_format,
                api_url,
                api_key,
                now,
                connection_id,
            ),
        )

        existing_model_rows = conn.execute(
            "SELECT id FROM providers WHERE connection_id = ?", (connection_id,)
        ).fetchall()
        existing_model_ids = {int(row["id"]) for row in existing_model_rows}
        incoming_model_ids = {
            int(model["id"]) for model in models if model["id"] is not None
        }
        invalid_model_ids = incoming_model_ids - existing_model_ids
        if invalid_model_ids:
            raise HTTPException(status_code=400, detail="模型不属于该供应商")

        _delete_models_if_unused(
            conn,
            existing_model_ids - incoming_model_ids,
            "被移除的模型已有会话记录，不能删除",
        )

        for model in models:
            if model["id"] is None:
                _insert_provider_model(
                    conn,
                    connection_id,
                    name=name,
                    api_format=payload.api_format,
                    api_url=api_url,
                    api_key=api_key,
                    model=model,
                    now=now,
                )
                continue
            conn.execute(
                """
                UPDATE providers
                SET name = ?, api_format = ?, api_url = ?, api_key = ?,
                    model_name = ?, supports_thinking = ?, supports_vision = ?,
                    supports_tool_calling = ?, thinking_effort = ?,
                    max_context_window = ?, max_output_tokens = ?,
                    is_enabled = ?, updated_at = ?
                WHERE id = ? AND connection_id = ?
                """,
                (
                    name,
                    payload.api_format,
                    api_url,
                    api_key,
                    model["model_name"],
                    model["supports_thinking"],
                    model["supports_vision"],
                    model["supports_tool_calling"],
                    model["thinking_effort"],
                    model["max_context_window"],
                    model["max_output_tokens"],
                    model["is_enabled"],
                    now,
                    model["id"],
                    connection_id,
                ),
            )

        conn.commit()
        rows = _fetch_provider_rows_for_connection(conn, connection_id)
    return provider_group_admin(rows)


def delete_provider(connection_id: int) -> None:
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM provider_connections WHERE id = ?", (connection_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="供应商不存在")
        model_rows = conn.execute(
            "SELECT id FROM providers WHERE connection_id = ?", (connection_id,)
        ).fetchall()
        model_ids = {int(row["id"]) for row in model_rows}
        _delete_models_if_unused(
            conn,
            model_ids,
            "该供应商已有会话记录，不能删除",
        )
        conn.execute("DELETE FROM provider_connections WHERE id = ?", (connection_id,))
        conn.commit()
