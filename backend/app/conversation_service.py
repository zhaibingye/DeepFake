from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Any

from fastapi import HTTPException

from app.auth import utcnow
from app.db import get_conn
from app.timeline import assistant_content_from_row, message_parts_from_row


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


def serialize_conversation(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "provider_id": row["provider_id"],
        "provider_name": row["provider_name"],
        "model_name": row["model_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_conversations_for_user(user_id: int) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT conversations.*, providers.name AS provider_name, providers.model_name AS model_name
            FROM conversations
            JOIN providers ON providers.id = conversations.provider_id
            WHERE conversations.user_id = ?
            ORDER BY conversations.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [serialize_conversation(row) for row in rows]


def get_conversation_messages_for_user(
    conversation_id: int, user_id: int
) -> dict[str, Any]:
    convo = fetch_conversation(conversation_id, user_id)
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


def rename_conversation_for_user(
    conversation_id: int, user_id: int, title: str
) -> dict[str, Any]:
    normalized_title = title.strip()
    if not normalized_title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    with closing(get_conn()) as conn:
        convo = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not convo:
            raise HTTPException(status_code=404, detail="会话不存在")
        now = utcnow()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (normalized_title[:80], now, conversation_id),
        )
        conn.commit()
        updated = conn.execute(
            """
            SELECT conversations.*, providers.name AS provider_name, providers.model_name AS model_name
            FROM conversations
            JOIN providers ON providers.id = conversations.provider_id
            WHERE conversations.id = ?
            """,
            (conversation_id,),
        ).fetchone()
    return serialize_conversation(updated)


def delete_conversation_for_user(conversation_id: int, user_id: int) -> None:
    with closing(get_conn()) as conn:
        convo = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not convo:
            raise HTTPException(status_code=404, detail="会话不存在")
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
