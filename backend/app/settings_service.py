from __future__ import annotations

from contextlib import closing
from typing import Any

from app.auth import utcnow
from app.db import get_conn


ALLOW_REGISTRATION_KEY = "allow_registration"
SEARCH_EXA_API_KEY = "search_exa_api_key"
SEARCH_EXA_ENABLED = "search_exa_enabled"
SEARCH_TAVILY_API_KEY = "search_tavily_api_key"
SEARCH_TAVILY_ENABLED = "search_tavily_enabled"


def get_setting_value(key: str, default: str = "") -> str:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return default
    return row["value"]


def get_setting_bool(key: str, default: bool = False) -> bool:
    return get_setting_value(key, "1" if default else "0") == "1"


def upsert_setting_value(key: str, value: str) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utcnow()),
        )
        conn.commit()


def get_allow_registration() -> bool:
    return get_setting_bool(ALLOW_REGISTRATION_KEY, True)


def get_exa_config() -> dict[str, Any]:
    api_key = get_setting_value(SEARCH_EXA_API_KEY, "").strip()
    is_enabled = get_setting_bool(SEARCH_EXA_ENABLED, True)
    return {
        "api_key": api_key,
        "is_enabled": is_enabled,
        "is_configured": True,
    }


def get_tavily_config() -> dict[str, Any]:
    api_key = get_setting_value(SEARCH_TAVILY_API_KEY, "").strip()
    is_enabled = get_setting_bool(SEARCH_TAVILY_ENABLED, False)
    return {
        "api_key": api_key,
        "is_enabled": is_enabled,
        "is_configured": bool(api_key),
    }


def store_exa_config(api_key: str, is_enabled: bool) -> None:
    upsert_setting_value(SEARCH_EXA_API_KEY, api_key)
    upsert_setting_value(SEARCH_EXA_ENABLED, "1" if is_enabled else "0")


def store_tavily_config(api_key: str, is_enabled: bool) -> None:
    upsert_setting_value(SEARCH_TAVILY_API_KEY, api_key)
    upsert_setting_value(SEARCH_TAVILY_ENABLED, "1" if is_enabled else "0")


def admin_search_provider_status() -> dict[str, dict[str, Any]]:
    exa_config = get_exa_config()
    tavily_config = get_tavily_config()
    return {
        "exa": {
            "kind": "exa",
            "name": "Exa",
            "is_enabled": exa_config["is_enabled"],
            "is_configured": exa_config["is_configured"],
            "api_key_masked": (
                "已配置"
                if exa_config["api_key"]
                else "未设置（可选）"
            ),
        },
        "tavily": {
            "kind": "tavily",
            "name": "Tavily",
            "is_enabled": tavily_config["is_enabled"],
            "is_configured": tavily_config["is_configured"],
            "api_key_masked": "已配置" if tavily_config["api_key"] else "未设置",
        },
    }


def public_search_provider_status() -> dict[str, dict[str, bool]]:
    status = admin_search_provider_status()
    return {
        kind: {
            "is_enabled": bool(provider["is_enabled"]),
            "is_configured": bool(provider["is_configured"]),
        }
        for kind, provider in status.items()
    }
