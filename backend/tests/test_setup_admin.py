import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import admin_setup, db, main


class AdminBootstrapApiTests(unittest.TestCase):
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
        self.test_data_dir = Path(self.test_file.name).parent
        self.test_db_path = Path(self.test_file.name)
        db.DATA_DIR = self.test_data_dir
        db.DB_PATH = self.test_db_path
        self.addCleanup(self.cleanup_test_db)
        main.ensure_tables()
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def cleanup_test_db(self) -> None:
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_setup_status_reports_bootstrap_needed_without_admin(self) -> None:
        response = self.client.get("/api/setup/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"needs_admin_setup": True})

    def test_setup_admin_creates_first_admin_and_returns_session(self) -> None:
        response = self.client.post(
            "/api/setup/admin",
            json={"username": " owner ", "password": "secret123"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("token", payload)
        self.assertIsInstance(payload["token"], str)
        self.assertTrue(payload["token"])
        self.assertEqual(
            payload["user"],
            {
                "id": payload["user"]["id"],
                "username": "owner",
                "role": "admin",
                "is_enabled": True,
            },
        )

        status_response = self.client.get("/api/setup/status")
        self.assertEqual(status_response.json(), {"needs_admin_setup": False})

    def test_setup_admin_rejects_second_initialization(self) -> None:
        first = self.client.post(
            "/api/setup/admin",
            json={"username": "owner", "password": "secret123"},
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            "/api/setup/admin",
            json={"username": "other-admin", "password": "secret123"},
        )

        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "管理员已初始化")

    def test_setup_admin_uses_dedicated_request_schema(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        schema_ref = payload["paths"]["/api/setup/admin"]["post"]["requestBody"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        self.assertEqual(schema_ref, "#/components/schemas/SetupAdminPayload")

    def test_create_initial_admin_starts_immediate_transaction_before_checks(self) -> (
        None
    ):
        statements: list[str] = []

        class FakeCursor:
            def __init__(self, row: object = None, lastrowid: int | None = None) -> None:
                self.row = row
                self.lastrowid = lastrowid

            def fetchone(self) -> object:
                return self.row

        class FakeConnection:
            def execute(
                self, sql: str, params: tuple[object, ...] = ()
            ) -> FakeCursor:
                statements.append(sql.strip())
                if "WHERE role = 'admin'" in sql:
                    return FakeCursor(None)
                if "WHERE username = ?" in sql:
                    return FakeCursor(None)
                if "INSERT INTO users" in sql:
                    return FakeCursor(lastrowid=7)
                return FakeCursor()

            def commit(self) -> None:
                statements.append("COMMIT")

            def rollback(self) -> None:
                statements.append("ROLLBACK")

            def close(self) -> None:
                statements.append("CLOSE")

        with (
            patch("app.admin_setup.get_conn", return_value=FakeConnection()),
            patch("app.admin_setup.has_admin_account", side_effect=AssertionError),
            patch("app.admin_setup.create_session", return_value="token"),
            patch(
                "app.admin_setup.get_user_by_id",
                return_value={
                    "id": 7,
                    "username": "owner",
                    "role": "admin",
                    "is_enabled": True,
                },
            ),
        ):
            payload = admin_setup.create_initial_admin("owner", "secret123")

        self.assertEqual(payload["token"], "token")
        self.assertEqual(statements[0], "BEGIN IMMEDIATE")
