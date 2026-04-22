import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main
from app.auth import hash_password, utcnow


class SearchProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_data_dir = db.DATA_DIR
        self.original_db_path = db.DB_PATH
        self.addCleanup(setattr, db, "DATA_DIR", self.original_data_dir)
        self.addCleanup(setattr, db, "DB_PATH", self.original_db_path)

        db.ensure_data_dir()
        self.test_file = tempfile.NamedTemporaryFile(
            dir=self.original_data_dir, suffix=".db", delete=False
        )
        self.test_file.close()
        self.test_db_path = Path(self.test_file.name)
        db.DATA_DIR = self.test_db_path.parent
        db.DB_PATH = self.test_db_path
        self.addCleanup(self.cleanup_test_db)

        main.ensure_tables()
        self.admin = self.create_user("admin-user", "admin")
        main.app.dependency_overrides[main.require_admin] = lambda: self.admin
        self.addCleanup(main.app.dependency_overrides.clear)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def cleanup_test_db(self) -> None:
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def create_user(self, username: str, role: str) -> dict[str, object]:
        salt, password_hash = hash_password("secret123")
        with closing(db.get_conn()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (username, salt, password_hash, role, utcnow()),
            )
            conn.commit()
        return {
            "id": int(cursor.lastrowid),
            "username": username,
            "role": role,
            "is_enabled": True,
        }

    def test_public_search_provider_status_exposes_exa_and_tavily(self) -> None:
        response = self.client.get("/api/search-providers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "exa": {"is_enabled": True, "is_configured": True},
                "tavily": {"is_enabled": False, "is_configured": False},
            },
        )

    def test_public_search_provider_status_does_not_imply_tool_support(self) -> None:
        response = self.client.get("/api/search-providers")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["exa"]["is_enabled"])
        self.assertNotIn("supports_tool_calling", response.json()["exa"])

    def test_admin_provider_round_trip_persists_tool_support_flag(self) -> None:
        create_response = self.client.post(
            "/api/admin/providers",
            json={
                "name": "Anthropic Provider",
                "api_url": "https://api.anthropic.com/v1",
                "api_key": "test-key",
                "model_name": "claude-test",
                "supports_thinking": True,
                "supports_vision": False,
                "supports_tool_calling": True,
                "thinking_effort": "high",
                "max_context_window": 256000,
                "max_output_tokens": 32000,
                "is_enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 200)
        self.assertTrue(create_response.json()["supports_tool_calling"])

        provider_id = create_response.json()["id"]
        update_response = self.client.put(
            f"/api/admin/providers/{provider_id}",
            json={
                "name": "Anthropic Provider",
                "api_url": "https://api.anthropic.com/v1",
                "api_key": "test-key",
                "model_name": "claude-test",
                "supports_thinking": True,
                "supports_vision": False,
                "supports_tool_calling": False,
                "thinking_effort": "high",
                "max_context_window": 256000,
                "max_output_tokens": 32000,
                "is_enabled": True,
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertFalse(update_response.json()["supports_tool_calling"])

        list_response = self.client.get("/api/admin/providers")
        self.assertEqual(list_response.status_code, 200)
        self.assertFalse(list_response.json()[0]["supports_tool_calling"])

    def test_admin_can_configure_tavily(self) -> None:
        response = self.client.put(
            "/api/admin/search-providers/tavily",
            json={"api_key": "tvly-secret", "is_enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "tavily")
        self.assertTrue(response.json()["is_enabled"])
        self.assertTrue(response.json()["is_configured"])

    def test_admin_tavily_update_requires_full_payload(self) -> None:
        response = self.client.put(
            "/api/admin/search-providers/tavily",
            json={"api_key": "tvly-secret", "is_enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.get_tavily_config()["api_key"], "tvly-secret")
        self.assertTrue(main.get_tavily_config()["is_enabled"])

        partial_response = self.client.put(
            "/api/admin/search-providers/tavily",
            json={"is_enabled": False},
        )
        self.assertEqual(partial_response.status_code, 422)
        self.assertEqual(main.get_tavily_config()["api_key"], "tvly-secret")
        self.assertTrue(main.get_tavily_config()["is_enabled"])
