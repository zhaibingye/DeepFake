# Search Tools And Stream UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix streamed chat completion, add fixed Exa/Tavily search tools, and restore a clear chat UI for thinking, tool activity, and answer output.

**Architecture:** Normalize provider stream completion in the backend, add a narrow search-tool layer with explicit `Exa` and `Tavily` selection, and keep the frontend consuming a single normalized event contract. Reuse the existing stream-only persistence rule so failed, aborted, or tool-error rounds are not committed.

**Tech Stack:** FastAPI, sqlite3, httpx, unittest, React, TypeScript, Vite

---

## File Map

- `backend/app/main.py`
  Route shapes, request/response models, provider streaming adapter, admin search-provider routes.
- `backend/app/chat_service.py`
  Stream chat preparation, tool injection, request payload shaping, commit/rollback helpers.
- `backend/app/db.py`
  Search-provider settings persistence helpers if shared access is needed.
- `backend/tests/test_chat_stream_commit.py`
  Stream completion, tool success/failure, rollback regression coverage.
- `backend/tests/test_search_providers.py`
  New search-provider configuration and availability tests.
- `frontend/src/types.ts`
  Search request fields, search-provider types, stream activity shape updates.
- `frontend/src/api.ts`
  Search-provider endpoints and updated stream request shape.
- `frontend/src/App.tsx`
  Search toggle/select UI, thinking auto-collapse state, tool card rendering, error handling.
- `frontend/src/App.css`
  Thinking container and tool activity card styling.

### Task 1: Fix Stream Completion Detection

**Files:**
- Modify: `backend/tests/test_chat_stream_commit.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing backend test for natural completion without `[DONE]`**

Add this test to `backend/tests/test_chat_stream_commit.py`:

```python
    def test_stream_natural_completion_without_done_still_commits(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"thinking":"先想一下"}}'
            yield 'data: {"type":"content_block_delta","delta":{"text":"正常结束"}}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "测试自然结束", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            self.fetch_messages(),
            [
                {
                    "role": "user",
                    "content_text": "测试自然结束",
                    "content_json": None,
                    "thinking_text": "",
                },
                {
                    "role": "assistant",
                    "content_text": "正常结束",
                    "content_json": None,
                    "thinking_text": "先想一下",
                },
            ],
        )
```

- [ ] **Step 2: Run the targeted test to verify it fails for the expected reason**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_stream_natural_completion_without_done_still_commits -v
```

Expected: `FAIL` because the last stream event is currently `error` with `流式响应未正确完成`.

- [ ] **Step 3: Implement minimal completion normalization in `backend/app/main.py`**

Update the stream loop so these provider end conditions count as successful completion:

```python
            async for line in stream_provider_events(
                context.provider, context.request_payload
            ):
                if not line or line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    continue
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    completed = True
                    break
                data = json.loads(raw)
                event_type = data.get("type")

                if event_type in {"message_stop", "response.completed"}:
                    completed = True
                    break

                if event_type in {"error", "response.error"}:
                    detail = data.get("error", {}).get("message") or data.get("detail") or "供应商流返回错误事件"
                    raise RuntimeError(detail)
```

After the loop, only raise `流式响应未正确完成` when there was no recognized successful completion marker and the stream ended without one.

- [ ] **Step 4: Run the targeted test again to verify it passes**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_stream_natural_completion_without_done_still_commits -v
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_chat_stream_commit.py
git commit -m "fix: accept natural stream completion"
```

### Task 2: Add Fixed Search Tool Backend

**Files:**
- Modify: `backend/tests/test_chat_stream_commit.py`
- Create: `backend/tests/test_search_providers.py`
- Modify: `backend/app/chat_service.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing tests for search tool selection and Tavily configuration**

Create `backend/tests/test_search_providers.py` with:

```python
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
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
        return {"id": int(cursor.lastrowid), "username": username, "role": role, "is_enabled": True}

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

    def test_admin_can_configure_tavily(self) -> None:
        response = self.client.put(
            "/api/admin/search-providers/tavily",
            json={"api_key": "tvly-secret", "is_enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "tavily")
        self.assertTrue(response.json()["is_enabled"])
        self.assertTrue(response.json()["is_configured"])
```

Also add this failing test to `backend/tests/test_chat_stream_commit.py`:

```python
    def test_tavily_search_without_configured_key_fails_and_rolls_back(self) -> None:
        provider_id = self.create_provider()

        response = self.client.post(
            "/api/chat/stream",
            json={
                "provider_id": provider_id,
                "text": "测试 tavily",
                "enable_search": True,
                "search_provider": "tavily",
                "attachments": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("Tavily", events[-1]["detail"])
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)
```

- [ ] **Step 2: Run the new backend tests to verify they fail**

Run:

```bash
cd backend && python -m unittest tests.test_search_providers tests.test_chat_stream_commit.ChatStreamCommitTests.test_tavily_search_without_configured_key_fails_and_rolls_back -v
```

Expected: `FAIL` because the routes and request fields do not exist yet.

- [ ] **Step 3: Add search-provider models and persistence**

In `backend/app/main.py`, add request models:

```python
class SearchProviderSelection(str, Enum):
    exa = "exa"
    tavily = "tavily"


class SearchProviderConfigPayload(BaseModel):
    api_key: str = Field(default="", max_length=500)
    is_enabled: bool = False
```

Extend `ChatPayload`:

```python
class ChatPayload(BaseModel):
    provider_id: int
    conversation_id: int | None = None
    text: str = Field(default="", max_length=20000)
    enable_thinking: bool = False
    enable_search: bool = False
    search_provider: SearchProviderSelection | None = None
    effort: str = "high"
    attachments: list[ChatAttachment] = Field(default_factory=list)
```

Add app settings keys for Tavily:

- `search_tavily_api_key`
- `search_tavily_enabled`

Add helpers that return:

```python
{
    "exa": {"kind": "exa", "name": "Exa", "is_enabled": True, "is_configured": True},
    "tavily": {"kind": "tavily", "name": "Tavily", "is_enabled": ..., "is_configured": ...},
}
```

- [ ] **Step 4: Add backend routes for public/admin search-provider status**

In `backend/app/main.py`, add:

```python
@app.get("/api/search-providers")
def list_search_providers() -> dict[str, dict[str, Any]]:
    return public_search_provider_status()


@app.get("/api/admin/search-providers")
def list_admin_search_providers(
    admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    return admin_search_provider_status()


@app.put("/api/admin/search-providers/tavily")
def update_tavily_search_provider(
    payload: SearchProviderConfigPayload,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    store_tavily_config(payload.api_key.strip(), payload.is_enabled)
    return admin_search_provider_status()["tavily"]
```

- [ ] **Step 5: Add minimal tool-layer hooks in `backend/app/chat_service.py`**

Add validation before request payload creation:

```python
def resolve_search_tool(payload: Any) -> dict[str, Any] | None:
    if not payload.enable_search:
        return None
    if payload.search_provider == "exa":
        return {"name": "exa_search"}
    if payload.search_provider == "tavily":
        config = get_tavily_config()
        if not config["is_enabled"] or not config["api_key"]:
            raise HTTPException(status_code=400, detail="Tavily 搜索当前不可用，请先在后台配置")
        return {"name": "tavily_search"}
    raise HTTPException(status_code=400, detail="请先选择搜索来源")
```

Then inject the selected tool into the request payload structure that the provider expects.

- [ ] **Step 6: Run the new backend tests again**

Run:

```bash
cd backend && python -m unittest tests.test_search_providers tests.test_chat_stream_commit.ChatStreamCommitTests.test_tavily_search_without_configured_key_fails_and_rolls_back -v
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/chat_service.py backend/tests/test_chat_stream_commit.py backend/tests/test_search_providers.py
git commit -m "feat: add fixed search provider configuration"
```

### Task 3: Stream Tool Activity Events

**Files:**
- Modify: `backend/tests/test_chat_stream_commit.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/chat_service.py`

- [ ] **Step 1: Write the failing backend test for tool activity events**

Add this test to `backend/tests/test_chat_stream_commit.py`:

```python
    def test_search_tool_emits_activity_events_before_final_answer(self) -> None:
        provider_id = self.create_provider()

        with patch("app.chat_service.execute_search_tool") as execute_search_tool:
            execute_search_tool.return_value = {
                "label": "Exa 搜索",
                "detail": "找到 2 条结果",
                "output": "- result 1\\n- result 2",
            }

            async def fake_stream_provider_events(provider, payload):
                yield 'data: {"type":"content_block_delta","delta":{"text":"搜索后回答"}}'
                yield 'data: {"type":"message_stop"}'

            with patch("app.main.stream_provider_events", fake_stream_provider_events):
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "provider_id": provider_id,
                        "text": "查一下",
                        "enable_search": True,
                        "search_provider": "exa",
                        "attachments": [],
                    },
                )

        events = self.parse_stream_events(response)
        self.assertEqual(events[1]["type"], "activity")
        self.assertEqual(events[1]["activity"]["status"], "running")
        self.assertEqual(events[2]["type"], "activity")
        self.assertEqual(events[2]["activity"]["status"], "done")
        self.assertEqual(events[-1]["type"], "done")
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_search_tool_emits_activity_events_before_final_answer -v
```

Expected: `FAIL` because no `activity` events are emitted yet.

- [ ] **Step 3: Implement a minimal tool execution helper and activity emission**

In `backend/app/chat_service.py`, add:

```python
def execute_search_tool(tool_name: str, query: str) -> dict[str, str]:
    if tool_name == "exa_search":
        return run_exa_search(query)
    if tool_name == "tavily_search":
        return run_tavily_search(query)
    raise HTTPException(status_code=400, detail="未知搜索工具")
```

In `backend/app/main.py`, before provider streaming begins:

```python
            if context.search_tool:
                activity_id = f"tool-{context.conversation_id}-1"
                yield json.dumps(
                    {
                        "type": "activity",
                        "activity": {
                            "id": activity_id,
                            "kind": "tool",
                            "label": context.search_tool["label"],
                            "status": "running",
                            "detail": "正在执行搜索",
                        },
                    },
                    ensure_ascii=False,
                ) + "\n"

                tool_result = execute_search_tool(
                    context.search_tool["name"], context.pending_user_text or ""
                )
                yield json.dumps(
                    {
                        "type": "activity",
                        "activity": {
                            "id": activity_id,
                            "kind": "tool",
                            "label": tool_result["label"],
                            "status": "done",
                            "detail": tool_result["detail"],
                            "output": tool_result["output"],
                        },
                    },
                    ensure_ascii=False,
                ) + "\n"
```

If `execute_search_tool` raises, emit an `activity(status="error")` event first, then propagate the failure so the round rolls back.

- [ ] **Step 4: Run the targeted test again**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_search_tool_emits_activity_events_before_final_answer -v
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/chat_service.py backend/tests/test_chat_stream_commit.py
git commit -m "feat: stream search tool activity events"
```

### Task 4: Restore Frontend Search Controls And Event Handling

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the frontend type changes first**

Update `frontend/src/types.ts`:

```ts
export type SearchProvider = 'exa' | 'tavily'

export type SearchProviderStatus = {
  kind: SearchProvider
  name: string
  is_enabled: boolean
  is_configured: boolean
}

export type ChatRequest = {
  provider_id: number
  conversation_id?: number
  text: string
  enable_thinking: boolean
  enable_search: boolean
  search_provider?: SearchProvider
  effort: string
  attachments: Attachment[]
}
```

- [ ] **Step 2: Add the API endpoints**

Update `frontend/src/api.ts`:

```ts
  listSearchProviders: (token: string) =>
    request<Record<string, SearchProviderStatus>>('/search-providers', { token }),
  listAdminSearchProviders: (token: string) =>
    request<SearchProviderStatus[]>('/admin/search-providers', { token }),
  updateTavilySearchProvider: (
    token: string,
    body: { api_key: string; is_enabled: boolean },
  ) => request<SearchProviderStatus>('/admin/search-providers/tavily', { method: 'PUT', token, body }),
```

- [ ] **Step 3: Restore minimal chat-side search controls in `frontend/src/App.tsx`**

Add state:

```ts
  const [searchEnabled, setSearchEnabled] = useState(false)
  const [searchProvider, setSearchProvider] = useState<SearchProvider>('exa')
  const [searchProviders, setSearchProviders] = useState<Record<string, SearchProviderStatus>>({})
```

Load availability during bootstrap:

```ts
  const loadSearchProviders = useCallback(async (currentToken = token) => {
    if (!currentToken) return
    const list = await api.listSearchProviders(currentToken)
    setSearchProviders(list)
  }, [token])
```

Include it in bootstrap:

```ts
      await Promise.all([
        loadProviders(currentToken),
        loadSearchProviders(currentToken),
        loadConversations(currentToken),
      ])
```

Send request fields:

```ts
        enable_search: searchEnabled,
        search_provider: searchEnabled ? searchProvider : undefined,
```

- [ ] **Step 4: Render the restored search controls**

In the composer toolbar:

```tsx
                <button
                  className={searchEnabled ? 'tool-btn active' : 'tool-btn'}
                  onClick={() => setSearchEnabled((value) => !value)}
                  type="button"
                >
                  <Wrench size={15} />
                  联网搜索
                </button>
                {searchEnabled ? (
                  <select value={searchProvider} onChange={(event) => setSearchProvider(event.target.value as SearchProvider)}>
                    <option value="exa">Exa</option>
                    <option value="tavily">Tavily</option>
                  </select>
                ) : null}
```

Block send when the selected provider is known-unavailable:

```ts
    if (searchEnabled) {
      const selectedSearch = searchProviders[searchProvider]
      if (!selectedSearch?.is_enabled || !selectedSearch?.is_configured) {
        setChatError(`${selectedSearch?.name ?? '搜索来源'} 当前不可用`)
        return
      }
    }
```

- [ ] **Step 5: Run frontend verification**

Run:

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

Expected: both commands succeed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/App.tsx
git commit -m "feat: restore fixed search controls"
```

### Task 5: Improve Thinking Panel And Tool Card UX

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add explicit UI state for thinking auto-collapse**

In `frontend/src/App.tsx`, add:

```ts
  const [streamThinkingExpanded, setStreamThinkingExpanded] = useState(true)
  const streamThinkingManuallyExpandedRef = useRef(false)
```

Reset at the start of each round:

```ts
    setStreamThinkingExpanded(true)
    streamThinkingManuallyExpandedRef.current = false
```

When the first `text_delta` arrives:

```ts
          if (!streamThinkingManuallyExpandedRef.current) {
            setStreamThinkingExpanded(false)
          }
```

User-driven reopen:

```ts
  function toggleStreamThinkingExpanded(next: boolean) {
    setStreamThinkingExpanded(next)
    if (next) {
      streamThinkingManuallyExpandedRef.current = true
    }
  }
```

- [ ] **Step 2: Update the streaming thinking panel markup**

Replace the current streaming thinking block with:

```tsx
                  {streamingAssistant.thinking ? (
                    <details
                      className="thinking-box thinking-box-stream"
                      open={streamThinkingExpanded}
                      onToggle={(event) => toggleStreamThinkingExpanded((event.currentTarget as HTMLDetailsElement).open)}
                    >
                      <summary>
                        <span className="thinking-summary-main">
                          <BrainCircuit size={14} /> {formatThinkingLabel(sumThinkingDuration(streamingAssistant.activities), true)}
                        </span>
                        <ChevronRight className="thinking-summary-chevron" size={14} />
                      </summary>
                      <div className="thinking-content-shell">
                        <MarkdownView content={streamingAssistant.thinking} enableMath={false} />
                      </div>
                    </details>
                  ) : null}
```

Apply the same content shell wrapper to persisted thinking blocks.

- [ ] **Step 3: Keep tool cards collapsed by default but expandable**

In `ActivityList`, keep `open={activity.status === 'error'}` and ensure the summary remains compact. Do not auto-open success cards.

Use the tool output body exactly once:

```tsx
            <div className="stream-activity-output">
              <div className="markdown-body compact">
                <MarkdownView content={activity.output || ''} enableMath={false} />
              </div>
            </div>
```

- [ ] **Step 4: Add the CSS for thinking shell and compact tool cards**

In `frontend/src/App.css`, add or update:

```css
.thinking-content-shell {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid #d7c5b3;
  border-radius: 12px;
  background: #fbf3ea;
}

.thinking-box-stream[open] .thinking-content-shell {
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.5);
}

.stream-activity-card {
  border: 1px solid #d6dde6;
  border-radius: 12px;
  background: #f7fafc;
}

.stream-activity-card summary {
  cursor: pointer;
  list-style: none;
}
```

- [ ] **Step 5: Run full verification**

Run:

```bash
cd frontend && npm run lint
cd frontend && npm run build
cd backend && python -m unittest discover -s tests -v
cd backend && python -m compileall app
```

Expected: all commands succeed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.css backend/app/main.py backend/app/chat_service.py backend/tests
git commit -m "feat: polish stream thinking and tool activity ui"
```

## Self-Review

- Spec coverage:
  - stream failure root cause: Task 1
  - fixed search tools: Tasks 2 and 3
  - admin-side Tavily configuration: Task 2
  - frontend search controls: Task 4
  - thinking/tool UI behavior: Task 5
- Placeholder scan: no `TBD`, `TODO`, or “implement later” placeholders remain.
- Type consistency:
  - request fields use `enable_search` and `search_provider` consistently
  - tool events use the existing `activity` stream event shape
  - frontend search provider identifiers stay `exa` / `tavily`

Plan complete and saved to `docs/superpowers/plans/2026-04-22-search-tools-and-stream-ui.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
