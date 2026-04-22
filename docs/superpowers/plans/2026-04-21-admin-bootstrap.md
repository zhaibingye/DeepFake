# Admin Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the hard-coded default admin account and replace it with a first-run bootstrap API that creates the first admin explicitly.

**Architecture:** Keep database schema initialization in `backend/app/main.py`, but stop seeding a default admin on startup. Add two public setup endpoints that report initialization state and create the first admin once, then document the new bootstrap flow in the README.

**Tech Stack:** FastAPI, SQLite, Python stdlib `unittest`, FastAPI `TestClient`

---

### Task 1: Add Failing Backend Tests For Admin Bootstrap

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_setup_admin.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing test package marker**

Create `backend/tests/__init__.py` with:

```python
# Test package marker for python -m unittest discovery.
```

- [ ] **Step 2: Write the failing bootstrap tests**

Create `backend/tests/test_setup_admin.py` with:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import main


class AdminBootstrapApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        main.DATA_DIR = Path(self.temp_dir.name)
        main.DB_PATH = main.DATA_DIR / "test.db"
        main.ensure_tables()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_setup_status_reports_bootstrap_needed_without_admin(self) -> None:
        response = self.client.get("/api/setup/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"needs_admin_setup": True})

    def test_setup_admin_creates_first_admin_and_returns_session(self) -> None:
        response = self.client.post(
            "/api/setup/admin",
            json={"username": "owner", "password": "secret123"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("token", payload)
        self.assertEqual(payload["user"]["username"], "owner")
        self.assertEqual(payload["user"]["role"], "admin")
        self.assertTrue(payload["user"]["is_enabled"])

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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && python -m unittest tests.test_setup_admin -v`
Expected: FAIL because `/api/setup/status` and `/api/setup/admin` do not exist yet, and startup still creates a default admin.

- [ ] **Step 4: Commit the failing tests**

```bash
git add backend/tests/__init__.py backend/tests/test_setup_admin.py
git commit -m "test: cover admin bootstrap setup flow"
```

### Task 2: Implement Setup Endpoints And Remove Default Admin Seeding

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_setup_admin.py`

- [ ] **Step 1: Add the setup payload model and helper**

In `backend/app/main.py`, add:

```python
class SetupAdminPayload(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


def has_admin_account() -> bool:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
    return row is not None
```

- [ ] **Step 2: Remove automatic default admin creation from startup**

Replace the startup hook in `backend/app/main.py` with:

```python
@app.on_event("startup")
def on_startup() -> None:
    ensure_tables()
```

Delete the old `ensure_admin()` function entirely so the code no longer contains the hard-coded `admin123` seed path.

- [ ] **Step 3: Add the setup status endpoint**

In `backend/app/main.py`, add:

```python
@app.get("/api/setup/status")
def setup_status() -> dict[str, bool]:
    return {"needs_admin_setup": not has_admin_account()}
```

- [ ] **Step 4: Add the first-admin bootstrap endpoint**

In `backend/app/main.py`, add:

```python
@app.post("/api/setup/admin")
def setup_admin(payload: SetupAdminPayload) -> dict[str, Any]:
    if has_admin_account():
        raise HTTPException(status_code=409, detail="管理员已初始化")

    username = normalize_username(payload.username)
    with closing(get_conn()) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        salt, password_hash = hash_password(payload.password)
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at)
            VALUES (?, ?, ?, 'admin', 1, ?)
            """,
            (username, salt, password_hash, utcnow()),
        )
        conn.commit()
        user_id = cursor.lastrowid
        user = conn.execute(
            "SELECT id, username, role, is_enabled FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    token = create_session(user_id)
    return {"token": token, "user": row_to_user(user)}
```

- [ ] **Step 5: Run the targeted tests**

Run: `cd backend && python -m unittest tests.test_setup_admin -v`
Expected: PASS for all three bootstrap tests.

- [ ] **Step 6: Run the backend syntax check**

Run: `cd backend && python -m compileall app`
Expected: output includes `Listing 'app'...` with no errors.

- [ ] **Step 7: Commit the backend implementation**

```bash
git add backend/app/main.py backend/tests/test_setup_admin.py
git commit -m "feat: add first-run admin bootstrap endpoints"
```

### Task 3: Update README For The New Bootstrap Flow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the default admin section with setup instructions**

Update `README.md` so the old default-credential section is replaced with guidance like:

````md
## 首次初始化管理员

系统不再在启动时自动创建默认管理员。

首次启动后，请先调用初始化接口创建第一个管理员：

```bash
curl -X POST http://127.0.0.1:8000/api/setup/admin \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"your-password\"}"
```

可先检查当前实例是否仍需初始化：

```bash
curl http://127.0.0.1:8000/api/setup/status
```

注意：该初始化接口仅适用于本机或可信内网环境，未初始化完成前不要直接暴露到公网。
````

- [ ] **Step 2: Run the backend checks again after docs sync**

Run: `cd backend && python -m unittest tests.test_setup_admin -v && python -m compileall app`
Expected: tests PASS and compile step finishes without errors.

- [ ] **Step 3: Commit the documentation update**

```bash
git add README.md
git commit -m "docs: describe admin bootstrap setup flow"
```

### Task 4: Final Verification

**Files:**
- Modify: none

- [ ] **Step 1: Run the full required verification for this repository**

Run: `cd frontend && npm run lint`
Expected: ESLint exits with code 0.

Run: `cd frontend && npm run build`
Expected: Vite production build succeeds.

Run: `cd backend && python -m unittest tests.test_setup_admin -v`
Expected: PASS.

Run: `cd backend && python -m compileall app`
Expected: syntax check completes without errors.

- [ ] **Step 2: Manually verify the bootstrap flow**

1. Delete the local test database or use a fresh one.
2. Start the backend.
3. `GET /api/setup/status` should return `{"needs_admin_setup": true}`.
4. `POST /api/setup/admin` should return a token and admin user payload.
5. Repeat `POST /api/setup/admin`; it should return `409`.
6. Log in with the created admin through the existing auth flow.

- [ ] **Step 3: Commit the verification checkpoint**

```bash
git add -A
git commit -m "chore: verify admin bootstrap change"
```
