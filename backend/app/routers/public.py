from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.provider_service import list_public_providers as list_public_provider_rows
from app.settings_service import public_search_provider_status


router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/providers")
def list_public_providers(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return list_public_provider_rows()


@router.get("/search-providers")
def list_search_providers() -> dict[str, dict[str, bool]]:
    return public_search_provider_status()
