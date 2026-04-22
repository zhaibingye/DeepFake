import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


class AuthFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_data_dir = db.DATA_DIR
        self.original_db_path = db.DB_PATH
        db.ensure_data_dir()
        self.test_file = tempfile.NamedTemporaryFile(
            dir=self.original_data_dir, suffix=".db", delete=False
        )
        self.test_file.close()
        self.test_data_dir = Path(self.test_file.name).parent
        self.test_db_path = Path(self.test_file.name)
        db.DATA_DIR = self.test_data_dir
        db.DB_PATH = self.test_db_path
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        db.DATA_DIR = self.original_data_dir
        db.DB_PATH = self.original_db_path
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_ensure_tables_uses_db_module_configuration(self) -> None:
        main.ensure_tables()

        self.assertEqual(db.DB_PATH, self.test_db_path)
        self.assertTrue(self.test_db_path.exists())

    def test_register_returns_complete_user_shape(self) -> None:
        main.ensure_tables()
        response = self.client.post(
            "/api/auth/register",
            json={"username": "new-user", "password": "secret123"},
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
                "username": "new-user",
                "role": "user",
                "is_enabled": True,
            },
        )
