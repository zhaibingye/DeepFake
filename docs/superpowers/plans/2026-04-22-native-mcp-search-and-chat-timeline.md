# Native MCP Search And Chat Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把搜索改成 provider 原生决定是否调用的 MCP 工具调用，并把 assistant 输出改成可持久化的时间线卡片 UI。

**Architecture:** 后端新增工具运行层与时间线层，统一 provider 工具事件和 assistant timeline 持久化；前端拆出聊天时间线组件与状态管理，只按统一 timeline 事件渲染 `thinking`、`tool`、`answer` 块。继续保持“失败、中断、不完整流都不保存 assistant 回复”的规则。

**Tech Stack:** FastAPI, sqlite3, httpx, unittest, React, TypeScript, Vite, ESLint

---

## File Map

- Create: `backend/app/tool_runtime.py`
  固定 Exa/Tavily 远程 MCP 执行层、工具 schema、tool result 序列化。
- Create: `backend/app/timeline.py`
  assistant timeline part 的创建、追加、结束、错误、兼容映射和序列化。
- Modify: `backend/app/chat_service.py`
  provider payload 构造、tool schema 注入、旧消息兼容映射、stream context。
- Modify: `backend/app/main.py`
  流式路由改成 timeline 事件编排、provider tool call loop、提交与回滚。
- Modify: `backend/tests/test_chat_stream_commit.py`
  原生 tool calling、timeline 事件、回滚回归测试。
- Modify: `backend/tests/test_search_providers.py`
  provider 不支持 tool calling、Tavily 不可用等搜索配置错误路径。
- Modify: `frontend/src/types.ts`
  timeline part、timeline stream event、兼容后的 message 类型。
- Modify: `frontend/src/api.ts`
  stream 事件类型适配，无需改接口地址但要支持新事件形状。
- Create: `frontend/src/components/chat/timeline.ts`
  timeline 纯函数和兼容映射。
- Create: `frontend/src/components/chat/useTimelineState.ts`
  流式 timeline 状态机。
- Create: `frontend/src/components/chat/TimelineList.tsx`
- Create: `frontend/src/components/chat/TimelineBlock.tsx`
- Create: `frontend/src/components/chat/ThinkingBlock.tsx`
- Create: `frontend/src/components/chat/ToolBlock.tsx`
- Create: `frontend/src/components/chat/AnswerBlock.tsx`
- Modify: `frontend/src/App.tsx`
  删除旧 thinking/activity 渲染路径，接入 timeline 组件。
- Modify: `frontend/src/App.css`
  删除旧分区式样式，接入统一 timeline 卡片样式。
- Create: `frontend/src/components/chat/timeline.test.ts`
  纯函数级前端 timeline 回归测试。
- Modify: `frontend/package.json`
  增加前端最小测试命令与依赖。

### Task 1: Introduce Backend Timeline Model And Compatibility

**Files:**
- Create: `backend/app/timeline.py`
- Modify: `backend/app/chat_service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_chat_stream_commit.py`

- [ ] **Step 1: Write the failing backend tests for assistant timeline persistence and legacy compatibility**

Add these tests to `backend/tests/test_chat_stream_commit.py`:

```python
    def test_done_payload_returns_assistant_parts_in_order(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_start","content_block":{"type":"thinking"}}'
            yield 'data: {"type":"content_block_delta","delta":{"thinking":"先判断"}}'
            yield 'data: {"type":"content_block_stop"}'
            yield 'data: {"type":"content_block_start","content_block":{"type":"text"}}'
            yield 'data: {"type":"content_block_delta","delta":{"text":"最终回答"}}'
            yield 'data: {"type":"content_block_stop"}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "你好", "attachments": []},
            )

        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")
        assistant = events[-1]["messages"][1]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(
            [part["kind"] for part in assistant["parts"]],
            ["thinking", "answer"],
        )
        self.assertEqual(assistant["parts"][0]["text"], "先判断")
        self.assertEqual(assistant["parts"][1]["text"], "最终回答")

    def test_legacy_assistant_message_is_mapped_to_timeline_parts(self) -> None:
        provider_id = self.create_provider()
        conversation_id = self.create_conversation(provider_id)
        self.insert_message(conversation_id, "assistant", "旧回答", None, "旧思考")

        response = self.client.get(f"/api/conversations/{conversation_id}/messages")

        self.assertEqual(response.status_code, 200)
        assistant = response.json()["messages"][0]
        self.assertEqual([part["kind"] for part in assistant["parts"]], ["thinking", "answer"])
        self.assertEqual(assistant["parts"][0]["text"], "旧思考")
        self.assertEqual(assistant["parts"][1]["text"], "旧回答")
```

- [ ] **Step 2: Run the targeted backend tests to verify they fail**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_done_payload_returns_assistant_parts_in_order tests.test_chat_stream_commit.ChatStreamCommitTests.test_legacy_assistant_message_is_mapped_to_timeline_parts -v
```

Expected: `FAIL` because assistant messages still expose `thinking_text` + `content` instead of `parts`.

- [ ] **Step 3: Add timeline helpers in `backend/app/timeline.py`**

Create `backend/app/timeline.py`:

```python
from __future__ import annotations

import json
from typing import Any


def create_part(part_id: str, kind: str, *, status: str = "running", **fields: Any) -> dict[str, Any]:
    return {"id": part_id, "kind": kind, "status": status, **fields}


def append_text(part: dict[str, Any], delta: str) -> dict[str, Any]:
    next_part = dict(part)
    next_part["text"] = f"{part.get('text', '')}{delta}"
    return next_part


def finalize_part(part: dict[str, Any]) -> dict[str, Any]:
    next_part = dict(part)
    next_part["status"] = "done"
    return next_part


def fail_part(part: dict[str, Any], detail: str) -> dict[str, Any]:
    next_part = dict(part)
    next_part["status"] = "error"
    next_part["detail"] = detail
    return next_part


def serialize_parts(parts: list[dict[str, Any]]) -> str:
    return json.dumps(parts, ensure_ascii=False)


def legacy_message_parts(content: Any, thinking_text: str) -> list[dict[str, Any]]:
    text_content = content if isinstance(content, str) else ""
    parts: list[dict[str, Any]] = []
    if thinking_text:
        parts.append(create_part("legacy-thinking", "thinking", status="done", text=thinking_text))
    if text_content:
        parts.append(create_part("legacy-answer", "answer", status="done", text=text_content))
    return parts


def message_parts_from_row(row: Any) -> list[dict[str, Any]]:
    if row["content_json"]:
        content = json.loads(row["content_json"])
        if isinstance(content, dict) and isinstance(content.get("parts"), list):
            return content["parts"]
    return legacy_message_parts(row["content_text"] or "", row["thinking_text"] or "")
```

- [ ] **Step 4: Update message parsing and commit payloads to expose `parts`**

Update `backend/app/chat_service.py`:

```python
from app.timeline import legacy_message_parts, message_parts_from_row


def parse_message(row: sqlite3.Row) -> dict[str, Any]:
    content = row["content_text"]
    if row["content_json"]:
        content = json.loads(row["content_json"])
    return {
        "id": row["id"],
        "role": row["role"],
        "content": content,
        "parts": message_parts_from_row(row),
        "thinking_text": row["thinking_text"] or "",
        "created_at": row["created_at"],
    }


def build_history(conversation_id: int) -> list[dict[str, Any]]:
    ...
    for row in rows:
        content: Any = row["content_text"]
        if row["content_json"]:
            content = json.loads(row["content_json"])
        if row["role"] == "assistant" and isinstance(content, dict) and isinstance(content.get("parts"), list):
            answer_text = "".join(
                part.get("text", "")
                for part in content["parts"]
                if isinstance(part, dict) and part.get("kind") == "answer"
            )
            history.append({"role": "assistant", "content": answer_text})
            continue
        history.append({"role": row["role"], "content": content})
```

Update the route return path in `backend/app/main.py` so the `done` payload uses the parsed message rows after commit instead of reconstructing `thinking_text` and `content` manually.

- [ ] **Step 5: Run the targeted tests again**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_done_payload_returns_assistant_parts_in_order tests.test_chat_stream_commit.ChatStreamCommitTests.test_legacy_assistant_message_is_mapped_to_timeline_parts -v
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/timeline.py backend/app/chat_service.py backend/app/main.py backend/tests/test_chat_stream_commit.py
git commit -m "feat: add assistant timeline model"
```

### Task 2: Replace App-Side Search Injection With Native Provider Tool Calling

**Files:**
- Create: `backend/app/tool_runtime.py`
- Modify: `backend/app/chat_service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_chat_stream_commit.py`
- Modify: `backend/tests/test_search_providers.py`

- [ ] **Step 1: Write the failing backend tests for native tool schema injection and unsupported provider failure**

Add these tests:

```python
    def test_search_enabled_injects_only_selected_tool_schema(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

        with patch("app.main.stream_provider_events") as stream_provider_events:
            stream_provider_events.return_value = iter(())
            self.client.post(
                "/api/chat/stream",
                json={
                    "provider_id": provider_id,
                    "text": "查一下",
                    "enable_search": True,
                    "search_provider": "exa",
                    "attachments": [],
                },
            )

        request_payload = stream_provider_events.call_args.args[1]
        self.assertEqual(len(request_payload["tools"]), 1)
        self.assertEqual(request_payload["tools"][0]["name"], "exa_search")

    def test_search_enabled_on_provider_without_tool_calling_fails(self) -> None:
        provider_id = self.create_provider()

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
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("工具调用", events[-1]["detail"])
```

Add to `backend/tests/test_search_providers.py`:

```python
    def test_public_search_provider_status_does_not_imply_tool_support(self) -> None:
        response = self.client.get("/api/search-providers")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["exa"]["is_enabled"])
```

- [ ] **Step 2: Run the targeted backend tests to verify they fail**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_search_enabled_injects_only_selected_tool_schema tests.test_chat_stream_commit.ChatStreamCommitTests.test_search_enabled_on_provider_without_tool_calling_fails tests.test_search_providers.SearchProviderTests.test_public_search_provider_status_does_not_imply_tool_support -v
```

Expected: `FAIL` because the current flow still executes search before provider streaming.

- [ ] **Step 3: Add tool schema and MCP execution helpers in `backend/app/tool_runtime.py`**

Create `backend/app/tool_runtime.py`:

```python
from __future__ import annotations

from typing import Any

from app.chat_service import call_remote_mcp_tool, normalize_search_result, EXA_REMOTE_MCP_URL, TAVILY_REMOTE_MCP_URL


def search_tool_schema(kind: str) -> dict[str, Any]:
    schemas = {
        "exa": {
            "name": "exa_search",
            "description": "Search the web with Exa for fresh sources.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        "tavily": {
            "name": "tavily_search",
            "description": "Search the web with Tavily for fresh sources.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
    return schemas[kind]


def execute_native_search_tool(kind: str, arguments: dict[str, Any], tavily_api_key: str = "") -> dict[str, str]:
    query = str(arguments.get("query", "")).strip()
    if kind == "exa":
        return normalize_search_result(
            "Exa 搜索",
            call_remote_mcp_tool(EXA_REMOTE_MCP_URL, "web_search_exa", {"query": query}),
        )
    if kind == "tavily":
        from urllib.parse import quote

        if not tavily_api_key:
            raise RuntimeError("Tavily 搜索当前不可用，请先在后台配置")
        return normalize_search_result(
            "Tavily 搜索",
            call_remote_mcp_tool(
                f"{TAVILY_REMOTE_MCP_URL}?tavilyApiKey={quote(tavily_api_key, safe='')}",
                "tavily-search",
                {"query": query},
            ),
        )
    raise RuntimeError("未知搜索工具")
```

- [ ] **Step 4: Inject provider tools instead of pre-searching**

Update `backend/app/chat_service.py`:

```python
def provider_supports_tool_calling(provider: sqlite3.Row) -> bool:
    api_url = (provider["api_url"] or "").lower()
    return "/anthropic" in api_url or "messages" in api_url


def selected_search_tool_schema(payload: Any, provider: sqlite3.Row) -> dict[str, Any] | None:
    if not getattr(payload, "enable_search", False):
        return None
    if not provider_supports_tool_calling(provider):
        raise SearchProviderUnavailableError("当前模型不支持原生工具调用，无法开启联网搜索")
    if payload.search_provider == "exa":
        from app.tool_runtime import search_tool_schema

        return search_tool_schema("exa")
    if payload.search_provider == "tavily":
        from app.main import get_tavily_config
        from app.tool_runtime import search_tool_schema

        config = get_tavily_config()
        if not config["is_enabled"] or not config["api_key"]:
            raise SearchProviderUnavailableError("Tavily 搜索当前不可用，请先在后台配置")
        return search_tool_schema("tavily")
    raise HTTPException(status_code=400, detail="请先选择搜索来源")


def build_chat_request_payload(...):
    ...
    selected_tool = selected_search_tool_schema(payload, provider)
    if selected_tool:
        request_payload["tools"] = [selected_tool]
```

Update `ChatStreamContext` to remove `search_tool`, `search_query_text`, and pre-injected search result fields that are no longer needed.

- [ ] **Step 5: Run the targeted tests again**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_search_enabled_injects_only_selected_tool_schema tests.test_chat_stream_commit.ChatStreamCommitTests.test_search_enabled_on_provider_without_tool_calling_fails tests.test_search_providers.SearchProviderTests.test_public_search_provider_status_does_not_imply_tool_support -v
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tool_runtime.py backend/app/chat_service.py backend/app/main.py backend/tests/test_chat_stream_commit.py backend/tests/test_search_providers.py
git commit -m "feat: inject native search tools"
```

### Task 3: Implement Provider Tool Call Loop And Timeline Stream Events

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/chat_service.py`
- Modify: `backend/app/timeline.py`
- Modify: `backend/tests/test_chat_stream_commit.py`

- [ ] **Step 1: Write the failing backend tests for timeline events and native tool loop**

Add these tests:

```python
    def test_native_tool_call_emits_timeline_parts_in_order(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}'
            yield 'data: {"type":"content_block_delta","index":0,"delta":{"thinking":"先分析"}}'
            yield 'data: {"type":"content_block_stop","index":0}'
            yield 'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","name":"exa_search","id":"toolu_1","input":{"query":"你好"}}}'
            yield 'data: {"type":"content_block_stop","index":1}'
            yield 'data: {"type":"content_block_start","index":2,"content_block":{"type":"text"}}'
            yield 'data: {"type":"content_block_delta","index":2,"delta":{"text":"最终回答"}}'
            yield 'data: {"type":"content_block_stop","index":2}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events), patch(
            "app.tool_runtime.execute_native_search_tool",
            return_value={"label": "Exa 搜索", "detail": "返回 1 个内容块", "output": "结果"},
        ):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider_id": provider_id,
                    "text": "你好",
                    "enable_search": True,
                    "search_provider": "exa",
                    "attachments": [],
                },
            )

        events = self.parse_stream_events(response)
        self.assertEqual(
            [event["type"] for event in events if event["type"].startswith("timeline_part")],
            [
                "timeline_part_start",
                "timeline_part_delta",
                "timeline_part_end",
                "timeline_part_start",
                "timeline_part_delta",
                "timeline_part_end",
                "timeline_part_start",
                "timeline_part_delta",
                "timeline_part_end",
            ],
        )

    def test_native_tool_failure_emits_timeline_part_error_and_rolls_back(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"exa_search","id":"toolu_1","input":{"query":"你好"}}}'
            yield 'data: {"type":"content_block_stop","index":0}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events), patch(
            "app.tool_runtime.execute_native_search_tool",
            side_effect=RuntimeError("搜索失败"),
        ):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider_id": provider_id,
                    "text": "你好",
                    "enable_search": True,
                    "search_provider": "exa",
                    "attachments": [],
                },
            )

        events = self.parse_stream_events(response)
        self.assertEqual(events[-2]["type"], "timeline_part_error")
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.fetch_messages(), [])
```

- [ ] **Step 2: Run the targeted backend tests to verify they fail**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_native_tool_call_emits_timeline_parts_in_order tests.test_chat_stream_commit.ChatStreamCommitTests.test_native_tool_failure_emits_timeline_part_error_and_rolls_back -v
```

Expected: `FAIL` because the route still emits `thinking_delta` / `text_delta` / `activity`.

- [ ] **Step 3: Normalize provider blocks into timeline events**

Update `backend/app/main.py` stream loop:

```python
active_parts: dict[int, dict[str, Any]] = {}
assistant_parts: list[dict[str, Any]] = []
tool_results_by_id: dict[str, dict[str, str]] = {}

def emit(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"

...
if event_type == "content_block_start":
    block = data.get("content_block", {})
    index = int(data.get("index", 0))
    block_type = block.get("type")
    if block_type == "thinking":
        part = timeline.create_part(f"thinking-{index}", "thinking")
        active_parts[index] = part
        assistant_parts.append(part)
        yield emit({"type": "timeline_part_start", "part": part})
        continue
    if block_type == "text":
        part = timeline.create_part(f"answer-{index}", "answer")
        active_parts[index] = part
        assistant_parts.append(part)
        yield emit({"type": "timeline_part_start", "part": part})
        continue
    if block_type == "tool_use":
        part = timeline.create_part(
            block.get("id") or f"tool-{index}",
            "tool",
            tool_name=block.get("name"),
            label=block.get("name"),
            input=json.dumps(block.get("input", {}), ensure_ascii=False),
        )
        active_parts[index] = part
        assistant_parts.append(part)
        yield emit({"type": "timeline_part_start", "part": part})
        tool_result = await asyncio.to_thread(
            tool_runtime.execute_native_search_tool,
            "exa" if block.get("name") == "exa_search" else "tavily",
            block.get("input", {}),
            get_tavily_config().get("api_key", "").strip(),
        )
        active_parts[index] = timeline.finalize_part(
            {**part, "label": tool_result["label"], "detail": tool_result["detail"], "output": tool_result["output"]}
        )
        assistant_parts[-1] = active_parts[index]
        tool_results_by_id[part["id"]] = tool_result
        yield emit({"type": "timeline_part_delta", "part_id": part["id"], "delta": {"detail": tool_result["detail"], "output": tool_result["output"]}})
        yield emit({"type": "timeline_part_end", "part_id": part["id"]})
        continue
```

- [ ] **Step 4: Re-issue provider request after tool results and commit `parts`**

In `backend/app/chat_service.py`, add:

```python
def append_tool_result_message(request_payload: dict[str, Any], tool_use_id: str, result: dict[str, str]) -> None:
    request_payload["messages"].append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result["output"],
                }
            ],
        }
    )
```

In `backend/app/main.py`, after a tool call completes, append the tool result message and continue provider streaming with the updated payload. On successful completion, persist assistant parts:

```python
assistant_content_json = json.dumps({"parts": assistant_parts}, ensure_ascii=False)
result = commit_stream_chat(
    context,
    "".join(part.get("text", "") for part in assistant_parts if part["kind"] == "answer"),
    "",
    assistant_content_json=assistant_content_json,
)
```

Adjust `commit_stream_chat` in `backend/app/chat_service.py` to accept `assistant_content_json`.

- [ ] **Step 5: Run the targeted tests again**

Run:

```bash
cd backend && python -m unittest tests.test_chat_stream_commit.ChatStreamCommitTests.test_native_tool_call_emits_timeline_parts_in_order tests.test_chat_stream_commit.ChatStreamCommitTests.test_native_tool_failure_emits_timeline_part_error_and_rolls_back -v
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/app/chat_service.py backend/app/timeline.py backend/tests/test_chat_stream_commit.py
git commit -m "feat: stream native tool calls as timeline events"
```

### Task 4: Add Frontend Timeline Types, Helpers, And Tests

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/components/chat/timeline.ts`
- Create: `frontend/src/components/chat/timeline.test.ts`

- [ ] **Step 1: Write the failing frontend timeline helper tests**

Create `frontend/src/components/chat/timeline.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { applyTimelineEvent, toRenderableTimeline } from './timeline'

describe('timeline helpers', () => {
  it('appends parts in stream order', () => {
    let state = { parts: [], expandedById: {} }
    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'thinking-1', kind: 'thinking', status: 'running', text: '' },
    })
    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'tool-1', kind: 'tool', status: 'running', label: 'Exa 搜索' },
    })

    expect(state.parts.map((part) => part.id)).toEqual(['thinking-1', 'tool-1'])
  })

  it('keeps manual expansion after a part ends', () => {
    let state = {
      parts: [{ id: 'thinking-1', kind: 'thinking', status: 'running', text: '' }],
      expandedById: { 'thinking-1': true },
      manuallyExpanded: { 'thinking-1': true },
    }

    state = applyTimelineEvent(state, { type: 'timeline_part_end', part_id: 'thinking-1' })

    expect(state.expandedById['thinking-1']).toBe(true)
  })

  it('maps legacy assistant messages into thinking and answer parts', () => {
    const message = {
      id: 1,
      role: 'assistant' as const,
      content: '旧回答',
      thinking_text: '旧思考',
      created_at: '2026-04-22T00:00:00Z',
    }

    expect(toRenderableTimeline(message).map((part) => part.kind)).toEqual(['thinking', 'answer'])
  })
})
```

- [ ] **Step 2: Add minimal frontend test tooling and run the test to verify it fails**

Update `frontend/package.json`:

```json
{
  "scripts": {
    "test": "vitest run"
  },
  "devDependencies": {
    "vitest": "^3.2.4"
  }
}
```

Run:

```bash
cd frontend && npm.cmd install
cd frontend && npm.cmd run test -- frontend/src/components/chat/timeline.test.ts
```

Expected: `FAIL` because the helper file does not exist yet.

- [ ] **Step 3: Add timeline types and helper functions**

Update `frontend/src/types.ts`:

```ts
export type TimelinePartKind = 'thinking' | 'tool' | 'answer'

export type TimelinePart = {
  id: string
  kind: TimelinePartKind
  status: 'running' | 'done' | 'error'
  text?: string
  label?: string
  detail?: string
  output?: string
  tool_name?: string
  input?: string
}

export type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string | Array<Record<string, unknown>> | { parts: TimelinePart[] }
  parts?: TimelinePart[]
  thinking_text: string
  created_at: string
}

export type ChatStreamEvent =
  | { type: 'conversation'; conversation: Partial<Conversation> & Pick<Conversation, 'id' | 'provider_id'> }
  | { type: 'timeline_part_start'; part: TimelinePart }
  | { type: 'timeline_part_delta'; part_id: string; delta: Partial<TimelinePart> }
  | { type: 'timeline_part_end'; part_id: string }
  | { type: 'timeline_part_error'; part_id: string; detail: string }
  | ({ type: 'done' } & ChatDonePayload)
  | { type: 'error'; detail: string }
  | { type: 'usage'; usage: Record<string, unknown> }
```

Create `frontend/src/components/chat/timeline.ts`:

```ts
import type { Message, TimelinePart, ChatStreamEvent } from '../../types'

export type TimelineState = {
  parts: TimelinePart[]
  expandedById: Record<string, boolean>
  manuallyExpanded?: Record<string, boolean>
}

export function toRenderableTimeline(message: Message): TimelinePart[] {
  if (Array.isArray(message.parts) && message.parts.length) return message.parts
  if (typeof message.content === 'object' && message.content && 'parts' in message.content) {
    const content = message.content as { parts?: TimelinePart[] }
    if (Array.isArray(content.parts)) return content.parts
  }
  const parts: TimelinePart[] = []
  if (message.thinking_text) {
    parts.push({ id: `legacy-thinking-${message.id}`, kind: 'thinking', status: 'done', text: message.thinking_text })
  }
  if (typeof message.content === 'string' && message.content) {
    parts.push({ id: `legacy-answer-${message.id}`, kind: 'answer', status: 'done', text: message.content })
  }
  return parts
}

export function applyTimelineEvent(state: TimelineState, event: ChatStreamEvent): TimelineState {
  if (event.type === 'timeline_part_start') {
    const nextExpanded = Object.fromEntries(Object.keys(state.expandedById).map((id) => [id, false]))
    return {
      parts: [...state.parts, event.part],
      expandedById: { ...nextExpanded, [event.part.id]: true },
      manuallyExpanded: state.manuallyExpanded ?? {},
    }
  }
  if (event.type === 'timeline_part_delta') {
    return {
      ...state,
      parts: state.parts.map((part) => (part.id === event.part_id ? { ...part, ...event.delta } : part)),
    }
  }
  if (event.type === 'timeline_part_end') {
    return {
      ...state,
      parts: state.parts.map((part) => (part.id === event.part_id ? { ...part, status: 'done' } : part)),
    }
  }
  if (event.type === 'timeline_part_error') {
    return {
      ...state,
      parts: state.parts.map((part) => (part.id === event.part_id ? { ...part, status: 'error', detail: event.detail } : part)),
      expandedById: { ...state.expandedById, [event.part_id]: true },
    }
  }
  return state
}
```

- [ ] **Step 4: Run the frontend timeline tests again**

Run:

```bash
cd frontend && npm.cmd run test -- frontend/src/components/chat/timeline.test.ts
```

Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/src/types.ts frontend/src/api.ts frontend/src/components/chat/timeline.ts frontend/src/components/chat/timeline.test.ts
git commit -m "feat: add frontend timeline model"
```

### Task 5: Extract Chat Timeline Components And Replace Old Rendering

**Files:**
- Create: `frontend/src/components/chat/useTimelineState.ts`
- Create: `frontend/src/components/chat/TimelineList.tsx`
- Create: `frontend/src/components/chat/TimelineBlock.tsx`
- Create: `frontend/src/components/chat/ThinkingBlock.tsx`
- Create: `frontend/src/components/chat/ToolBlock.tsx`
- Create: `frontend/src/components/chat/AnswerBlock.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Write the failing frontend render tests for ordered timeline blocks**

Extend `frontend/src/components/chat/timeline.test.ts`:

```ts
  it('marks the current block expanded and previous auto-collapsed', () => {
    let state = { parts: [], expandedById: {}, manuallyExpanded: {} }
    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'thinking-1', kind: 'thinking', status: 'running', text: '' },
    })
    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'tool-1', kind: 'tool', status: 'running', label: 'Exa 搜索' },
    })

    expect(state.expandedById['thinking-1']).toBe(false)
    expect(state.expandedById['tool-1']).toBe(true)
  })
```

Run:

```bash
cd frontend && npm.cmd run test -- frontend/src/components/chat/timeline.test.ts
```

Expected: `FAIL` until the helper preserves this rule consistently.

- [ ] **Step 2: Add the timeline hook and extracted block components**

Create `frontend/src/components/chat/useTimelineState.ts`:

```ts
import { useMemo, useState } from 'react'
import type { ChatStreamEvent, TimelinePart } from '../../types'
import { applyTimelineEvent } from './timeline'

export function useTimelineState(initialParts: TimelinePart[] = []) {
  const [state, setState] = useState({
    parts: initialParts,
    expandedById: Object.fromEntries(initialParts.map((part) => [part.id, false])),
    manuallyExpanded: {} as Record<string, boolean>,
  })

  function dispatchTimelineEvent(event: ChatStreamEvent) {
    setState((prev) => applyTimelineEvent(prev, event))
  }

  function setExpanded(partId: string, nextExpanded: boolean) {
    setState((prev) => ({
      ...prev,
      expandedById: { ...prev.expandedById, [partId]: nextExpanded },
      manuallyExpanded: nextExpanded ? { ...prev.manuallyExpanded, [partId]: true } : prev.manuallyExpanded,
    }))
  }

  return useMemo(() => ({ ...state, dispatchTimelineEvent, setExpanded }), [state])
}
```

Create `TimelineBlock.tsx`:

```tsx
import { ChevronRight } from 'lucide-react'
import type { PropsWithChildren } from 'react'
import type { TimelinePart } from '../../types'

export function TimelineBlock({
  part,
  open,
  onToggle,
  children,
}: PropsWithChildren<{ part: TimelinePart; open: boolean; onToggle: (nextOpen: boolean) => void }>) {
  return (
    <details className={`timeline-block ${part.kind} ${part.status}`} open={open} onToggle={(event) => onToggle((event.currentTarget as HTMLDetailsElement).open)}>
      <summary className="timeline-block-summary">
        <span className="timeline-block-title">{part.label || part.kind}</span>
        <ChevronRight className="timeline-block-chevron" size={14} />
      </summary>
      <div className="timeline-block-body">{children}</div>
    </details>
  )
}
```

Create `ThinkingBlock.tsx`, `ToolBlock.tsx`, and `AnswerBlock.tsx` as thin wrappers around `TimelineBlock`.

Create `TimelineList.tsx`:

```tsx
import type { TimelinePart } from '../../types'
import { AnswerBlock } from './AnswerBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolBlock } from './ToolBlock'

export function TimelineList({
  parts,
  expandedById,
  onToggle,
}: {
  parts: TimelinePart[]
  expandedById: Record<string, boolean>
  onToggle: (partId: string, nextOpen: boolean) => void
}) {
  return (
    <div className="timeline-list">
      {parts.map((part) => {
        if (part.kind === 'thinking') {
          return <ThinkingBlock key={part.id} part={part} open={Boolean(expandedById[part.id])} onToggle={(next) => onToggle(part.id, next)} />
        }
        if (part.kind === 'tool') {
          return <ToolBlock key={part.id} part={part} open={Boolean(expandedById[part.id])} onToggle={(next) => onToggle(part.id, next)} />
        }
        return <AnswerBlock key={part.id} part={part} open={Boolean(expandedById[part.id])} onToggle={(next) => onToggle(part.id, next)} />
      })}
    </div>
  )
}
```

- [ ] **Step 3: Replace the old `thinking/activity/assistant bubble` path in `App.tsx`**

Update `frontend/src/App.tsx`:

```tsx
import { TimelineList } from './components/chat/TimelineList'
import { toRenderableTimeline } from './components/chat/timeline'
import { useTimelineState } from './components/chat/useTimelineState'

...
const streamingTimeline = useTimelineState()

...
await api.streamMessage(token, body, (chunk: ChatStreamEvent) => {
  ...
  if (
    chunk.type === 'timeline_part_start' ||
    chunk.type === 'timeline_part_delta' ||
    chunk.type === 'timeline_part_end' ||
    chunk.type === 'timeline_part_error'
  ) {
    streamingTimeline.dispatchTimelineEvent(chunk)
    return
  }
  ...
})

...
{messages.map((message) => {
  const parts = message.role === 'assistant' ? toRenderableTimeline(message) : []
  return (
    <article key={message.id} className={message.role === 'user' ? 'message-row user' : 'message-row assistant'}>
      ...
      {message.role === 'assistant' ? (
        <TimelineList parts={parts} expandedById={{}} onToggle={() => undefined} />
      ) : (
        <div className="message-bubble user">...</div>
      )}
    </article>
  )
})}

{streamingTimeline.parts.length ? (
  <article className="message-row assistant">
    ...
    <TimelineList
      parts={streamingTimeline.parts}
      expandedById={streamingTimeline.expandedById}
      onToggle={streamingTimeline.setExpanded}
    />
  </article>
) : null}
```

Delete `ActivityList`, `ThinkingPanel`, `streamThinkingExpanded`, and their related helpers after the new timeline path is wired in.

- [ ] **Step 4: Replace the old split styles in `App.css` and run the tests again**

Update `frontend/src/App.css`:

```css
.timeline-list {
  width: min(100%, 720px);
  display: grid;
  gap: 10px;
}

.timeline-block {
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid rgba(229, 234, 245, 0.96);
  background: rgba(248, 250, 253, 0.96);
}

.timeline-block.thinking {
  background: linear-gradient(180deg, rgba(247, 250, 255, 0.98) 0%, rgba(242, 246, 253, 0.98) 100%);
}

.timeline-block.tool {
  background: linear-gradient(180deg, rgba(250, 251, 253, 0.98) 0%, rgba(245, 247, 251, 0.98) 100%);
}

.timeline-block.answer {
  background: #ffffff;
}

.timeline-block-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  cursor: pointer;
}

.timeline-block-body {
  padding: 0 14px 14px;
}

.timeline-block[open] .timeline-block-chevron {
  transform: rotate(90deg);
}
```

Run:

```bash
cd frontend && npm.cmd run test -- frontend/src/components/chat/timeline.test.ts
```

Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/useTimelineState.ts frontend/src/components/chat/TimelineList.tsx frontend/src/components/chat/TimelineBlock.tsx frontend/src/components/chat/ThinkingBlock.tsx frontend/src/components/chat/ToolBlock.tsx frontend/src/components/chat/AnswerBlock.tsx frontend/src/App.tsx frontend/src/App.css frontend/src/components/chat/timeline.test.ts
git commit -m "feat: render assistant timeline cards"
```

### Task 6: Run Full Verification And Close The Old Paths

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/chat_service.py`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`
- Modify: `backend/tests/test_chat_stream_commit.py`
- Modify: `frontend/src/components/chat/timeline.test.ts`

- [ ] **Step 1: Remove the old stream event and legacy render branches once the new path is green**

Delete:

```python
# backend/app/main.py
{"type": "text_delta", "delta": text}
{"type": "thinking_delta", "delta": thinking}
{"type": "activity", "activity": {...}}
```

Delete:

```tsx
// frontend/src/App.tsx
if (chunk.type === 'text_delta') { ... }
if (chunk.type === 'thinking_delta') { ... }
if (chunk.type === 'activity') { ... }
```

Delete the unused UI helpers and CSS selectors tied only to:

```tsx
ActivityList
ThinkingPanel
streamThinkingExpanded
streamThinkingManuallyExpandedRef
```

- [ ] **Step 2: Run backend verification**

Run:

```bash
cd backend && python -m unittest tests.test_search_providers tests.test_chat_stream_commit -v
cd backend && python -m compileall app
```

Expected:

- `OK`
- `Listing 'app'...`

- [ ] **Step 3: Run frontend verification**

Run:

```bash
cd frontend && npm.cmd run test
cd frontend && npm.cmd run lint
cd frontend && npm.cmd run build
```

Expected:

- all frontend timeline tests `PASS`
- ESLint exits `0`
- Vite build exits `0`

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py backend/app/chat_service.py backend/tests/test_chat_stream_commit.py frontend/src/App.tsx frontend/src/App.css frontend/src/components/chat/timeline.test.ts
git commit -m "refactor: remove legacy chat stream UI paths"
```

## Self-Review

- Spec coverage:
  - provider 原生决定工具调用：Tasks 2 and 3
  - 固定 Exa/Tavily MCP 工具执行层：Tasks 2 and 3
  - assistant timeline 持久化：Tasks 1 and 3
  - 前端完整组件拆分：Tasks 4 and 5
  - 历史消息兼容：Tasks 1 and 4
  - 旧分区式 UI 删除：Task 6
- Placeholder scan:
  - no `TBD`
  - no `TODO`
  - no “similar to previous task”
- Type consistency:
  - 后端统一使用 `parts`
  - 流式事件统一使用 `timeline_part_*`
  - 前端统一使用 `TimelinePart`
  - 搜索来源仍保持 `exa` / `tavily`

Plan complete and saved to `docs/superpowers/plans/2026-04-22-native-mcp-search-and-chat-timeline.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
