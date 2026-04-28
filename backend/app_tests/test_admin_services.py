from __future__ import annotations

import shutil
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException

from app import db
from app.admin_service import (
    create_admin_user,
    delete_admin_user,
    get_admin_settings,
    list_admin_search_providers,
    reset_admin_user_password,
    update_exa_search_provider,
    update_admin_profile,
    update_admin_settings,
    update_admin_user,
    update_tavily_search_provider,
)
from app.auth import create_session, hash_password, utcnow
from app.bootstrap import ensure_tables
from app.db import get_conn
from app.provider_service import create_provider, delete_provider, list_admin_providers, update_provider
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


class AdminServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path.cwd() / ".test-data"
        test_root.mkdir(exist_ok=True)
        self.temp_path = test_root / f"case-{uuid4().hex}"
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self.data_dir_patch = patch.object(db, "DATA_DIR", self.temp_path)
        self.db_path_patch = patch.object(db, "DB_PATH", self.temp_path / "app.db")
        self.data_dir_patch.start()
        self.db_path_patch.start()
        ensure_tables()

    def tearDown(self) -> None:
        self.db_path_patch.stop()
        self.data_dir_patch.stop()
        shutil.rmtree(self.temp_path, ignore_errors=True)

    def insert_user(
        self,
        username: str,
        password: str,
        role: str = "admin",
        is_enabled: bool = True,
    ) -> int:
        salt, password_hash = hash_password(password)
        with closing(get_conn()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, salt, password_hash, role, int(is_enabled), utcnow()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def test_provider_service_roundtrip_and_delete_guard(self) -> None:
        created = create_provider(
            ProviderPayload(
                name="Test Provider",
                api_format="anthropic_messages",
                api_url="https://example.com/anthropic/v1",
                api_key="secret-key-value",
                model_name="claude-test",
                supports_thinking=True,
                supports_vision=False,
                supports_tool_calling=True,
                thinking_effort="high",
                max_context_window=256000,
                max_output_tokens=32000,
                is_enabled=True,
            )
        )

        self.assertEqual(created["name"], "Test Provider")
        self.assertIn("api_key_masked", created)
        self.assertEqual(len(list_admin_providers()), 1)

        updated = update_provider(
            int(created["id"]),
            ProviderPayload(
                name="Updated Provider",
                api_format="anthropic_messages",
                api_url="https://example.com/anthropic/v1",
                api_key="updated-secret-key",
                model_name="claude-next",
                supports_thinking=False,
                supports_vision=True,
                supports_tool_calling=False,
                thinking_effort="medium",
                max_context_window=128000,
                max_output_tokens=16000,
                is_enabled=False,
            ),
        )
        self.assertEqual(updated["name"], "Updated Provider")
        self.assertFalse(updated["is_enabled"])

        admin_id = self.insert_user("admin", "password123")
        with closing(get_conn()) as conn:
            conn.execute(
                """
                INSERT INTO conversations (user_id, provider_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (admin_id, created["id"], "In Use", utcnow(), utcnow()),
            )
            conn.commit()

        with self.assertRaises(HTTPException) as delete_error:
            delete_provider(int(created["id"]))
        self.assertEqual(delete_error.exception.status_code, 400)
        self.assertEqual(delete_error.exception.detail, "该供应商已有会话记录，不能删除")

        with closing(get_conn()) as conn:
            conn.execute("DELETE FROM conversations")
            conn.commit()

        delete_provider(int(created["id"]))
        self.assertEqual(list_admin_providers(), [])

    def test_update_provider_keeps_existing_connection_fields_when_blank(self) -> None:
        created = create_provider(
            ProviderPayload(
                name="Test Provider",
                api_format="anthropic_messages",
                api_url="https://example.com/anthropic/v1",
                api_key="secret-key-value",
                model_name="claude-test",
                supports_thinking=True,
                supports_vision=False,
                supports_tool_calling=True,
                thinking_effort="high",
                max_context_window=256000,
                max_output_tokens=32000,
                is_enabled=True,
            )
        )

        update_provider(
            int(created["id"]),
            ProviderUpdatePayload(
                name="Updated Provider",
                api_format="openai_chat",
                api_url="   ",
                api_key="",
                model_name="claude-next",
                supports_thinking=False,
                supports_vision=True,
                supports_tool_calling=False,
                thinking_effort="medium",
                max_context_window=128000,
                max_output_tokens=16000,
                is_enabled=False,
            ),
        )

        with closing(get_conn()) as conn:
            row = conn.execute(
                "SELECT api_format, api_url, api_key FROM providers WHERE id = ?",
                (created["id"],),
            ).fetchone()

        self.assertEqual(row["api_format"], "openai_chat")
        self.assertEqual(
            update_provider(
                int(created["id"]),
                ProviderUpdatePayload(
                    name="Updated Provider 2",
                    api_format="openai_chat",
                    api_url="   ",
                    api_key="",
                    model_name="gpt-4o",
                    supports_thinking=True,
                    supports_vision=True,
                    supports_tool_calling=False,
                    thinking_effort="max",
                    max_context_window=128000,
                    max_output_tokens=16000,
                    is_enabled=True,
                ),
            )["thinking_effort"],
            "high",
        )
        self.assertEqual(row["api_url"], "https://example.com/anthropic/v1")
        self.assertEqual(row["api_key"], "secret-key-value")

    def test_admin_service_moves_user_profile_and_settings_logic_out_of_router(self) -> None:
        admin_id = self.insert_user("admin", "password123")

        created_user = create_admin_user(
            AdminUserCreatePayload(
                username="member",
                password="password123",
                role="user",
                is_enabled=True,
            )
        )
        self.assertEqual(created_user["username"], "member")

        settings = update_admin_settings(
            RegistrationSettingsPayload(allow_registration=False)
        )
        self.assertEqual(settings, {"allow_registration": False})
        self.assertEqual(get_admin_settings(), {"allow_registration": False})

        profile = update_admin_profile(
            admin_id,
            AdminProfilePayload(
                username="owner",
                current_password="password123",
                new_password="new-password123",
            ),
        )
        self.assertEqual(profile["username"], "owner")

        user_token = create_session(int(created_user["id"]))
        reset_admin_user_password(
            int(created_user["id"]),
            AdminUserPasswordResetPayload(new_password="reset1234"),
        )
        with closing(get_conn()) as conn:
            session = conn.execute(
                "SELECT id FROM sessions WHERE token = ?", (user_token,)
            ).fetchone()
        self.assertIsNone(session)

        with self.assertRaises(HTTPException) as disable_self_error:
            update_admin_user(
                admin_id, admin_id, AdminUserUpdatePayload(is_enabled=False)
            )
        self.assertEqual(disable_self_error.exception.status_code, 400)
        self.assertEqual(disable_self_error.exception.detail, "不能停用当前管理员")

        with self.assertRaises(HTTPException) as delete_self_error:
            delete_admin_user(admin_id, admin_id)
        self.assertEqual(delete_self_error.exception.status_code, 400)
        self.assertEqual(delete_self_error.exception.detail, "不能删除当前管理员")

        update_tavily_search_provider(
            SearchProviderConfigPayload(api_key="tavily-key", is_enabled=True)
        )
        update_exa_search_provider(
            SearchProviderConfigPayload(api_key="", is_enabled=False)
        )
        self.assertEqual(
            list_admin_search_providers()["exa"],
            {
                "kind": "exa",
                "name": "Exa",
                "is_enabled": False,
                "is_configured": True,
                "api_key_masked": "未设置（可选）",
            },
        )
        self.assertEqual(
            list_admin_search_providers()["tavily"],
            {
                "kind": "tavily",
                "name": "Tavily",
                "is_enabled": True,
                "is_configured": True,
                "api_key_masked": "已配置",
            },
        )

        delete_admin_user(int(created_user["id"]), admin_id)
        with closing(get_conn()) as conn:
            deleted_user = conn.execute(
                "SELECT id FROM users WHERE id = ?", (created_user["id"],)
            ).fetchone()
        self.assertIsNone(deleted_user)


if __name__ == "__main__":
    unittest.main()
