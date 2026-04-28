from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.conversation_service import (
    delete_conversation_for_user,
    get_conversation_messages_for_user,
    list_conversations_for_user,
    rename_conversation_for_user,
)
from app.schemas import ConversationTitlePayload


router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return list_conversations_for_user(user["id"])


@router.get("/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    return get_conversation_messages_for_user(conversation_id, user["id"])


@router.put("/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    payload: ConversationTitlePayload,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return rename_conversation_for_user(conversation_id, user["id"], payload.title)


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    delete_conversation_for_user(conversation_id, user["id"])
    return {"status": "ok"}
