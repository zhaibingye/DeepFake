from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.chat_stream_service import create_chat_stream_response
from app.schemas import ChatPayload


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
async def stream_message(
    payload: ChatPayload, user: dict[str, Any] = Depends(get_current_user)
):
    return create_chat_stream_response(payload, user)
