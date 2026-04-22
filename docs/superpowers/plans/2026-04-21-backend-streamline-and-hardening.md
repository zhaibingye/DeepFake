# Backend Streamline And Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove redundant non-stream chat code, refactor the backend into clearer units, and fix the current high-priority auth/admin/chat persistence issues.

**Architecture:** The backend keeps FastAPI and SQLite, but narrows `backend/app/main.py` to route wiring and app setup. Database helpers move to `db.py`, auth/session helpers move to `auth.py`, first-run admin bootstrap moves to `admin_setup.py`, and stream-only chat orchestration plus commit rules move to `chat_service.py`.

**Tech Stack:** FastAPI, SQLite, Python stdlib `unittest`, FastAPI `TestClient`, React + TypeScript

---

### Task 0: Remove All Non-Stream Chat Paths

**Files:**
- Modify: `backend/app/main.py`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/types.ts`

- [ ] **Step 1: Write the failing backend test for route removal**

Create or extend `backend/tests/test_chat_stream_commit.py` with:

```python
import unittest
from fastapi.testclient import TestClient

from app.main import app


class ChatRouteShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_non_stream_chat_route_is_not_exposed(self) -> None:
        response = self.client.post("/api/chat", json={})
        self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd backend && python -m unittest tests.test_chat_stream_commit.ChatRouteShapeTests -v`
Expected: FAIL because `POST /api/chat` still exists.

- [ ] **Step 3: Remove the backend non-stream endpoint**

Delete the `@app.post("/api/chat")` handler from `backend/app/main.py` so only `POST /api/chat/stream` remains.

- [ ] **Step 4: Remove frontend non-stream API helpers**

In `frontend/src/api.ts`, delete the `sendMessage` export and keep only `streamMessage` for chat execution.

- [ ] **Step 5: Remove frontend non-stream compatibility code**

In `frontend/src/App.tsx`, keep `sendMessage()` as the local submit handler name if useful, but remove any code paths or types that assume a non-stream backend response payload. The chat UI should only use `api.streamMessage(...)` and final `done` events.

- [ ] **Step 6: Remove dead chat response types if they are no longer needed**

In `frontend/src/types.ts`, remove any chat payload/result typing that only existed for non-stream `POST /api/chat` behavior. Do not remove `Message` or `Conversation`.

- [ ] **Step 7: Run targeted checks**

Run: `cd backend && python -m unittest tests.test_chat_stream_commit.ChatRouteShapeTests -v`
Expected: PASS.

Run: `cd frontend && npm run lint`
Expected: ESLint exits with code 0.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py frontend/src/api.ts frontend/src/App.tsx frontend/src/types.ts backend/tests/test_chat_stream_commit.py
git commit -m "refactor: remove non-stream chat path"
```

### Task 1: Extract Database And Auth Foundations

**Files:**
- Create: `backend/app/db.py`
- Create: `backend/app/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth_flows.py`

- [ ] **Step 1: Write failing tests for shared auth helpers**

Create `backend/tests/test_auth_flows.py` with:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main


class AuthFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=main.BASE_DIR)
        db.DATA_DIR = Path(self.temp_dir.name)
        db.DB_PATH = db.DATA_DIR / "test.db"
        main.ensure_tables()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_register_returns_complete_user_shape(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={"username": "demo-user", "password": "secret123"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user"]["username"], "demo-user")
        self.assertEqual(payload["user"]["role"], "user")
        self.assertTrue(payload["user"]["is_enabled"])
        self.assertIn("token", payload)
```

- [ ] **Step 2: Run the test to confirm the current failure**

Run: `cd backend && python -m unittest tests.test_auth_flows.AuthFlowTests -v`
Expected: FAIL with the current registration bug or missing imports after initial extraction.

- [ ] **Step 3: Create `backend/app/db.py`**

Move database infrastructure into `backend/app/db.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 4: Create `backend/app/auth.py`**

Move password/session/current-user helpers into `backend/app/auth.py`, including:

```python
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from app.db import get_conn


TOKEN_EXPIRE_DAYS = 30


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(username: str) -> str:
    value = username.strip()
    if not value:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    return value


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    )
    return salt, hashed.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    _, computed = hash_password(password, salt)
    return hmac.compare_digest(computed, password_hash)


def row_to_user(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_enabled": bool(row["is_enabled"]),
    }
```

Also implement `create_session()`, `get_token()`, `get_user_by_id()`, `get_current_user()`, and `require_admin()` in the same module. `get_user_by_id()` must always select `id, username, role, is_enabled`.

- [ ] **Step 5: Update `backend/app/main.py` to import and reuse the extracted helpers**

Replace inline database/auth implementations in `backend/app/main.py` with imports from `app.db` and `app.auth`. Keep route behavior unchanged at this task except for fixing registration to read the user through the shared helper before serializing.

- [ ] **Step 6: Run auth tests and syntax check**

Run: `cd backend && python -m unittest tests.test_auth_flows.AuthFlowTests -v`
Expected: PASS.

Run: `cd backend && python -m compileall app`
Expected: syntax check completes with no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db.py backend/app/auth.py backend/app/main.py backend/tests/test_auth_flows.py
git commit -m "refactor: extract db and auth foundations"
```

### Task 2: Add First-Run Admin Bootstrap And Remove Default Admin Seed

**Files:**
- Create: `backend/app/admin_setup.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_setup_admin.py`

- [ ] **Step 1: Reuse the existing failing setup tests**

Keep `backend/tests/test_setup_admin.py` as the red test suite for:
- `GET /api/setup/status`
- first successful `POST /api/setup/admin`
- second `POST /api/setup/admin` returning `409`

- [ ] **Step 2: Create `backend/app/admin_setup.py`**

Add:

```python
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.auth import (
    create_session,
    get_user_by_id,
    hash_password,
    normalize_username,
    row_to_user,
    utcnow,
)
from app.db import get_conn


def has_admin_account() -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
    return row is not None


def create_initial_admin(username: str, password: str) -> dict[str, Any]:
    if has_admin_account():
        raise HTTPException(status_code=409, detail="管理员已初始化")
    normalized = normalize_username(username)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        salt, password_hash = hash_password(password)
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at)
            VALUES (?, ?, ?, 'admin', 1, ?)
            """,
            (normalized, salt, password_hash, utcnow()),
        )
        conn.commit()
        user_id = cursor.lastrowid
    token = create_session(user_id)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=500, detail="初始化管理员后读取用户失败")
    return {"token": token, "user": row_to_user(user)}
```

- [ ] **Step 3: Remove default admin seeding**

Delete the old `ensure_admin()` function and remove its startup call from `backend/app/main.py`. Startup should keep `ensure_tables()` only.

- [ ] **Step 4: Wire the setup routes**

Add these routes in `backend/app/main.py`:

```python
@app.get("/api/setup/status")
def setup_status() -> dict[str, bool]:
    return {"needs_admin_setup": not has_admin_account()}


@app.post("/api/setup/admin")
def setup_admin(payload: SetupAdminPayload) -> dict[str, Any]:
    return create_initial_admin(payload.username, payload.password)
```

- [ ] **Step 5: Run setup tests**

Run: `cd backend && python -m unittest tests.test_setup_admin -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/admin_setup.py backend/app/main.py backend/tests/test_setup_admin.py
git commit -m "feat: add admin bootstrap setup flow"
```

### Task 3: Centralize The Enabled-Admin Safety Rule

**Files:**
- Modify: `backend/app/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_admin_rules.py`

- [ ] **Step 1: Write failing admin rule tests**

Create `backend/tests/test_admin_rules.py` with:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, main
from app.auth import hash_password


class AdminRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=main.BASE_DIR)
        db.DATA_DIR = Path(self.temp_dir.name)
        db.DB_PATH = db.DATA_DIR / "test.db"
        main.ensure_tables()
        with db.get_conn() as conn:
            salt, password_hash = hash_password("secret123")
            conn.execute(
                "INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at) VALUES (?, ?, ?, 'admin', 1, ?)",
                ("root", salt, password_hash, main.utcnow()),
            )
            conn.commit()
        self.client = TestClient(main.app)
        login = self.client.post(
            "/api/auth/login",
            json={"username": "root", "password": "secret123"},
        )
        self.token = login.json()["token"]

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_cannot_disable_last_enabled_admin(self) -> None:
        response = self.client.put(
            "/api/admin/users/1",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"is_enabled": False},
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_delete_last_enabled_admin(self) -> None:
        response = self.client.delete(
            "/api/admin/users/1",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: Run the tests to confirm the delete-path failure**

Run: `cd backend && python -m unittest tests.test_admin_rules -v`
Expected: FAIL because delete currently uses a weaker count rule.

- [ ] **Step 3: Add a shared guard helper**

In `backend/app/auth.py`, add a helper such as:

```python
def ensure_other_enabled_admin_exists(conn: sqlite3.Connection, user_id: int) -> None:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        WHERE role = 'admin' AND is_enabled = 1 AND id != ?
        """,
        (user_id,),
    ).fetchone()
    if not row or row["count"] < 1:
        raise HTTPException(status_code=400, detail="至少保留一个启用中的管理员")
```

- [ ] **Step 4: Make both disable and delete use the shared guard**

Update `PUT /api/admin/users/{user_id}` and `DELETE /api/admin/users/{user_id}` in `backend/app/main.py` to call the same helper when the target is an enabled admin that would otherwise remove the last enabled admin.

- [ ] **Step 5: Run the tests**

Run: `cd backend && python -m unittest tests.test_admin_rules -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth.py backend/app/main.py backend/tests/test_admin_rules.py
git commit -m "fix: enforce last enabled admin rule"
```

### Task 4: Move Stream Commit Logic Into `chat_service.py`

**Files:**
- Create: `backend/app/chat_service.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_chat_stream_commit.py`

- [ ] **Step 1: Write failing stream commit tests**

Create `backend/tests/test_chat_stream_commit.py` with:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, main
from app.auth import hash_password


class ChatStreamCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=main.BASE_DIR)
        db.DATA_DIR = Path(self.temp_dir.name)
        db.DB_PATH = db.DATA_DIR / "test.db"
        main.ensure_tables()
        with db.get_conn() as conn:
            salt, password_hash = hash_password("secret123")
            conn.execute(
                "INSERT INTO users (username, password_salt, password_hash, role, is_enabled, created_at) VALUES (?, ?, ?, 'admin', 1, ?)",
                ("root", salt, password_hash, main.utcnow()),
            )
            conn.execute(
                \"\"\"INSERT INTO providers
                (name, api_format, api_url, api_key, model_name, supports_thinking, supports_vision, supports_mcp_tools, thinking_effort, max_context_window, max_output_tokens, is_enabled, created_at, updated_at)
                VALUES (?, 'responses', ?, ?, ?, 1, 0, 0, 'high', 256000, 32000, 1, ?, ?)
                \"\"\",
                ("Demo Provider", "https://api.openai.com/v1", "test-key", "gpt-test", main.utcnow(), main.utcnow()),
            )
            conn.commit()
        self.client = TestClient(main.app)
        login = self.client.post(
            "/api/auth/login",
            json={"username": "root", "password": "secret123"},
        )
        self.headers = {"Authorization": f"Bearer {login.json()['token']}"}

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def _messages_for_conversation(self, conversation_id: int) -> list[dict]:
        response = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self.headers,
        )
        return response.json()["messages"]

    def test_successful_stream_persists_round(self) -> None:
        def fake_stream_provider_events(provider, payload):
            async def iterator():
                yield 'data: {"type":"response.output_text.delta","delta":"hello"}'
                yield 'data: {"type":"response.completed","response":{"output_text":"hello","output":[]}}'
                yield "data: [DONE]"
            return iterator()

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                headers=self.headers,
                json={
                    "provider_id": 1,
                    "text": "hi",
                    "enable_thinking": False,
                    "effort": "high",
                    "enable_search": False,
                    "attachments": [],
                },
            )

        chunks = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        done = next(chunk for chunk in chunks if chunk["type"] == "done")
        messages = self._messages_for_conversation(done["conversation"]["id"])
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])

    def test_aborted_stream_does_not_persist_round(self) -> None:
        def fake_stream_provider_events(provider, payload):
            async def iterator():
                yield 'data: {"type":"response.output_text.delta","delta":"partial"}'
                raise RuntimeError("stream aborted")
            return iterator()

        response = self.client.post(
            "/api/chat/stream",
            headers=self.headers,
            json={
                "provider_id": 1,
                "text": "hi",
                "enable_thinking": False,
                "effort": "high",
                "enable_search": False,
                "attachments": [],
            },
        )

        chunks = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        conversation = next(chunk for chunk in chunks if chunk["type"] == "conversation")
        self.assertEqual(
            self._messages_for_conversation(conversation["conversation"]["id"]),
            [],
        )
```

- [ ] **Step 2: Run the tests to confirm current persistence mismatch**
Run: `cd backend && python -m unittest tests.test_chat_stream_commit -v`
Expected: FAIL because user messages are currently inserted before stream completion.

- [ ] **Step 3: Create `backend/app/chat_service.py`**

Move stream-only chat preparation and final commit behavior into helpers such as:

```python
from __future__ import annotations

from typing import Any


def prepare_stream_chat_context(payload, user) -> dict[str, Any]:
    return {
        "provider": provider,
        "conversation_id": conversation_id,
        "history": history,
        "pending_user_content": pending_user_content,
        "created_at": created_at,
    }


def commit_completed_stream_round(context, assistant_text: str, thinking_text: str) -> dict[str, Any]:
    # Insert the user message and assistant message in one durable commit,
    # then return the same conversation/messages payload shape the frontend
    # already expects from the final `done` event.
    return result


def rollback_incomplete_stream_round(context) -> None:
    # This is intentionally a no-op for durable state because incomplete
    # rounds must never be committed.
    return None
```

The durable write must happen only after the stream reaches a successful completion point.

- [ ] **Step 4: Update `backend/app/main.py` to delegate chat behavior**

Keep the route:

```python
@app.post("/api/chat/stream")
async def stream_message(
    payload: ChatPayload,
    user: dict[str, Any] = Depends(get_current_user),
):
    return StreamingResponse(
        build_stream_response(payload, user),
        media_type="application/x-ndjson",
    )
```

but move direct user-message insertion and assistant-message save logic behind `chat_service.py`. Do not save any part of the round on abort or error.

- [ ] **Step 5: Run the stream tests and syntax check**

Run: `cd backend && python -m unittest tests.test_chat_stream_commit -v`
Expected: PASS.

Run: `cd backend && python -m compileall app`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat_service.py backend/app/main.py backend/tests/test_chat_stream_commit.py
git commit -m "refactor: commit chat rounds only on stream success"
```

### Task 5: Update README And Align Existing Tests

**Files:**
- Modify: `README.md`
- Modify: `backend/tests/test_setup_admin.py`
- Modify: `backend/tests/test_auth_flows.py`
- Modify: `backend/tests/test_admin_rules.py`
- Modify: `backend/tests/test_chat_stream_commit.py`

- [ ] **Step 1: Update README**

Replace the default admin section with bootstrap instructions and document that chat is stream-only.

Include:

````md
## 首次初始化管理员

系统不再在启动时自动创建默认管理员。

```bash
curl http://127.0.0.1:8000/api/setup/status
curl -X POST http://127.0.0.1:8000/api/setup/admin \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"your-password\"}"
```

## 聊天接口说明

聊天仅支持流式接口：

```text
POST /api/chat/stream
```
````

- [ ] **Step 2: Make sure all backend tests use the extracted modules**

Make all backend tests import `app.db` for `DATA_DIR` and `DB_PATH`, and use shared helpers from `app.auth` instead of reaching back into removed inline implementations from `app.main`.

- [ ] **Step 3: Run the full backend test suite**

Run: `cd backend && python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md backend/tests/test_setup_admin.py backend/tests/test_auth_flows.py backend/tests/test_admin_rules.py backend/tests/test_chat_stream_commit.py
git commit -m "test: align backend tests with stream-only refactor"
```

### Task 6: Final Verification

**Files:**
- Modify: none

- [ ] **Step 1: Run repository verification**

Run: `cd frontend && npm run lint`
Expected: PASS.

Run: `cd frontend && npm run build`
Expected: PASS.

Run: `cd backend && python -m unittest discover -s tests -v`
Expected: PASS.

Run: `cd backend && python -m compileall app`
Expected: PASS.

- [ ] **Step 2: Manual verification**

1. Start with a fresh database.
2. Call `GET /api/setup/status`; expect `needs_admin_setup: true`.
3. Create the first admin with `POST /api/setup/admin`.
4. Log in as that admin through the existing UI.
5. Confirm a normal streamed chat completes and appears in history.
6. Abort a streamed chat mid-way; refresh and confirm that round is absent from history.
7. Confirm the last enabled admin cannot be disabled or deleted.

- [ ] **Step 3: Commit verification checkpoint**

```bash
git add -A
git commit -m "chore: verify backend streamline and hardening"
```
