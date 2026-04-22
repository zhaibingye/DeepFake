import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main
from app.auth import hash_password, utcnow


class AdminSafetyRuleTests(unittest.TestCase):
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
        main.app.dependency_overrides[main.require_admin] = self.fake_admin
        self.addCleanup(main.app.dependency_overrides.clear)

        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

        self.current_admin = self.fake_admin_payload()

    def cleanup_test_db(self) -> None:
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    @staticmethod
    def fake_admin_payload() -> dict[str, object]:
        return {
            "id": 999,
            "username": "review-admin",
            "role": "admin",
            "is_enabled": True,
        }

    def fake_admin(self) -> dict[str, object]:
        return self.current_admin

    def set_current_admin(self, user_id: int, username: str) -> None:
        self.current_admin = {
            "id": user_id,
            "username": username,
            "role": "admin",
            "is_enabled": True,
        }

    def create_user(self, username: str, role: str, is_enabled: bool) -> int:
        salt, password_hash = hash_password("secret123")
        with closing(db.get_conn()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, password_salt, password_hash, role, is_enabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, salt, password_hash, role, int(is_enabled), utcnow()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def test_cannot_disable_the_last_enabled_admin(self) -> None:
        admin_id = self.create_user("only-enabled-admin", "admin", True)
        self.create_user("disabled-admin", "admin", False)

        response = self.client.put(
            f"/api/admin/users/{admin_id}",
            json={"is_enabled": False},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "至少保留一个启用中的管理员")

    def test_cannot_delete_the_last_enabled_admin(self) -> None:
        admin_id = self.create_user("only-enabled-admin", "admin", True)
        self.create_user("disabled-admin", "admin", False)

        response = self.client.delete(f"/api/admin/users/{admin_id}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "至少保留一个启用中的管理员")

    def test_can_delete_a_disabled_admin_without_triggering_enabled_admin_guard(
        self,
    ) -> None:
        self.create_user("remaining-enabled-admin", "admin", True)
        disabled_admin_id = self.create_user("disabled-admin", "admin", False)

        response = self.client.delete(f"/api/admin/users/{disabled_admin_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        with closing(db.get_conn()) as conn:
            deleted_user = conn.execute(
                "SELECT id FROM users WHERE id = ?", (disabled_admin_id,)
            ).fetchone()
        self.assertIsNone(deleted_user)

    def test_current_admin_cannot_disable_self(self) -> None:
        current_admin_id = self.create_user("current-admin", "admin", True)
        self.create_user("other-enabled-admin", "admin", True)
        self.set_current_admin(current_admin_id, "current-admin")

        response = self.client.put(
            f"/api/admin/users/{current_admin_id}",
            json={"is_enabled": False},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "不能停用当前管理员")

    def test_current_admin_cannot_delete_self(self) -> None:
        current_admin_id = self.create_user("current-admin", "admin", True)
        self.create_user("other-enabled-admin", "admin", True)
        self.set_current_admin(current_admin_id, "current-admin")

        response = self.client.delete(f"/api/admin/users/{current_admin_id}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "不能删除当前管理员")
