from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.admin_service import (
    create_admin_user,
    delete_admin_user,
    get_admin_settings,
    list_admin_search_providers,
    list_admin_users,
    reset_admin_user_password,
    update_exa_search_provider,
    update_admin_profile,
    update_admin_settings,
    update_admin_user,
    update_tavily_search_provider,
)
from app.auth import require_admin
from app.provider_service import (
    create_provider,
    delete_provider,
    list_admin_providers,
    update_provider,
)
from app.schemas import (
    AdminProfilePayload,
    AdminUserCreatePayload,
    AdminUserPasswordResetPayload,
    AdminUserUpdatePayload,
    ProviderPayload,
    ProviderUpdatePayload,
    RegistrationSettingsPayload,
    SearchProviderConfigPayload,
)


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/providers")
def get_admin_providers(
    admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    return list_admin_providers()


@router.get("/search-providers")
def get_admin_search_providers(
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, dict[str, Any]]:
    return list_admin_search_providers()


@router.put("/search-providers/tavily")
def put_tavily_search_provider(
    payload: SearchProviderConfigPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return update_tavily_search_provider(payload)


@router.put("/search-providers/exa")
def put_exa_search_provider(
    payload: SearchProviderConfigPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return update_exa_search_provider(payload)


@router.post("/providers")
def post_provider(
    payload: ProviderPayload, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    return create_provider(payload)


@router.put("/providers/{provider_id}")
def put_provider(
    provider_id: int,
    payload: ProviderUpdatePayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return update_provider(provider_id, payload)


@router.delete("/providers/{provider_id}")
def remove_provider(
    provider_id: int, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, str]:
    delete_provider(provider_id)
    return {"status": "ok"}


@router.put("/profile")
def put_admin_profile(
    payload: AdminProfilePayload, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    return update_admin_profile(admin["id"], payload)


@router.get("/settings")
def get_settings(
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    return get_admin_settings()


@router.put("/settings")
def put_settings(
    payload: RegistrationSettingsPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    return update_admin_settings(payload)


@router.get("/users")
def get_admin_users(
    admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    return list_admin_users()


@router.post("/users")
def post_admin_user(
    payload: AdminUserCreatePayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return create_admin_user(payload)


@router.put("/users/{user_id}")
def put_admin_user(
    user_id: int,
    payload: AdminUserUpdatePayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return update_admin_user(user_id, admin["id"], payload)


@router.delete("/users/{user_id}")
def remove_admin_user(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    delete_admin_user(user_id, admin["id"])
    return {"status": "ok"}


@router.put("/users/{user_id}/password")
def put_admin_user_password(
    user_id: int,
    payload: AdminUserPasswordResetPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    reset_admin_user_password(user_id, payload)
    return {"status": "ok"}
