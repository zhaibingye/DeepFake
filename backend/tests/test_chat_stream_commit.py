import asyncio
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import chat_service, db, main
from app.auth import hash_password, utcnow


class ChatRouteShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_post_chat_route_is_removed(self) -> None:
        response = self.client.post("/api/chat", json={})

        self.assertEqual(response.status_code, 404)


class ChatStreamCommitTests(unittest.TestCase):
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
        self.user = self.create_user("stream-user")
        main.app.dependency_overrides[main.get_current_user] = self.fake_user
        self.addCleanup(main.app.dependency_overrides.clear)

        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def cleanup_test_db(self) -> None:
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def fake_user(self) -> dict[str, object]:
        return self.user

    def create_user(self, username: str) -> dict[str, object]:
        salt, password_hash = hash_password("secret123")
        with closing(db.get_conn()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    username, password_salt, password_hash, role, is_enabled, created_at
                ) VALUES (?, ?, ?, 'user', 1, ?)
                """,
                (username, salt, password_hash, utcnow()),
            )
            conn.commit()
            user_id = int(cursor.lastrowid)
        return {
            "id": user_id,
            "username": username,
            "role": "user",
            "is_enabled": True,
        }

    def create_provider(
        self,
        supports_vision: bool = False,
        supports_tool_calling: bool = False,
    ) -> int:
        now = utcnow()
        with closing(db.get_conn()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO providers (
                    name, api_url, api_key, model_name, supports_thinking, supports_vision,
                    supports_tool_calling, thinking_effort, max_context_window, max_output_tokens,
                    is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, 'high', 256000, 32000, 1, ?, ?)
                """,
                (
                    "Test Provider",
                    "https://example.invalid/v1",
                    "secret",
                    "test-model",
                    int(supports_vision),
                    int(supports_tool_calling),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def enable_provider_tool_support(self, provider_id: int) -> None:
        with closing(db.get_conn()) as conn:
            conn.execute(
                "UPDATE providers SET api_url = ?, supports_tool_calling = 1 WHERE id = ?",
                ("https://api.anthropic.com/v1", provider_id),
            )
            conn.commit()

    def disable_provider_tool_support(self, provider_id: int) -> None:
        with closing(db.get_conn()) as conn:
            conn.execute(
                "UPDATE providers SET api_url = ?, supports_tool_calling = 0 WHERE id = ?",
                ("https://api.anthropic.com/v1", provider_id),
            )
            conn.commit()

    def create_conversation(self, provider_id: int, title: str = "已有会话") -> int:
        now = utcnow()
        with closing(db.get_conn()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversations (
                    user_id, provider_id, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (self.user["id"], provider_id, title, now, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def insert_message(
        self,
        conversation_id: int,
        role: str,
        content_text: str | None,
        content_json: str | None,
        thinking_text: str,
    ) -> None:
        with closing(db.get_conn()) as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    conversation_id, role, content_text, content_json, thinking_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content_text,
                    content_json,
                    thinking_text,
                    utcnow(),
                ),
            )
            conn.commit()

    def create_conversation_with_message(self, provider_id: int) -> int:
        conversation_id = self.create_conversation(provider_id)
        self.insert_message(conversation_id, "user", "旧消息", None, "")
        return conversation_id

    def parse_stream_events(self, response) -> list[dict[str, object]]:
        lines = [line for line in response.text.splitlines() if line.strip()]
        return [json.loads(line) for line in lines]

    async def collect_stream_chunks(self, response) -> list[str]:
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return chunks

    def fetch_messages(self) -> list[dict[str, object]]:
        with closing(db.get_conn()) as conn:
            rows = conn.execute(
                """
                SELECT role, content_text, content_json, thinking_text
                FROM messages
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def count_conversations(self) -> int:
        with closing(db.get_conn()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM conversations").fetchone()
        return int(row["count"])

    def test_stream_completion_persists_user_and_assistant_messages(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            self.assertEqual(payload["messages"][-1]["role"], "user")
            self.assertEqual(payload["messages"][-1]["content"], "你好")
            yield 'data: {"type":"content_block_delta","delta":{"text":"世界"}}'
            yield 'data: {"type":"content_block_delta","delta":{"thinking":"思考中"}}'
            yield 'data: {"type":"message_delta","usage":{"output_tokens":3}}'
            yield "data: [DONE]"

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "你好", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1]["type"], "done")
        self.assertFalse(
            any(
                event["type"] in {"text_delta", "thinking_delta", "activity"}
                for event in events
            )
        )

        messages = self.fetch_messages()
        self.assertEqual(self.count_conversations(), 1)
        self.assertEqual(
            messages[0],
            {
                "role": "user",
                "content_text": "你好",
                "content_json": None,
                "thinking_text": "",
            },
        )
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content_text"], "世界")
        self.assertEqual(messages[1]["thinking_text"], "思考中")
        assistant_parts = json.loads(messages[1]["content_json"] or "{}")["parts"]
        self.assertEqual(
            {(part["kind"], part["text"], part["status"]) for part in assistant_parts},
            {
                ("thinking", "思考中", "done"),
                ("answer", "世界", "done"),
            },
        )

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
        self.assertFalse(
            any(
                event["type"] in {"text_delta", "thinking_delta", "activity"}
                for event in events
            )
        )
        assistant = events[-1]["messages"][1]
        self.assertEqual(assistant["role"], "assistant")
        self.assertIsInstance(assistant["content"], str)
        self.assertEqual(assistant["content"], "最终回答")
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
        self.assertIsInstance(assistant["content"], str)
        self.assertEqual(assistant["content"], "旧回答")
        self.assertEqual(
            [part["kind"] for part in assistant["parts"]],
            ["thinking", "answer"],
        )
        self.assertEqual(assistant["parts"][0]["text"], "旧思考")
        self.assertEqual(assistant["parts"][1]["text"], "旧回答")

    def test_conversation_messages_returns_string_content_for_persisted_assistant_parts(
        self,
    ) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"thinking":"先判断"}}'
            yield 'data: {"type":"content_block_delta","delta":{"text":"最终回答"}}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "你好", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        done_event = self.parse_stream_events(response)[-1]
        conversation_id = done_event["conversation"]["id"]

        messages_response = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        )

        self.assertEqual(messages_response.status_code, 200)
        assistant = messages_response.json()["messages"][1]
        self.assertIsInstance(assistant["content"], str)
        self.assertEqual(assistant["content"], "最终回答")
        self.assertEqual(
            [part["kind"] for part in assistant["parts"]],
            ["thinking", "answer"],
        )

    def test_stream_provider_error_does_not_persist_partial_round(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"text":"半截"}}'
            raise RuntimeError("provider boom")

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "这轮不能保存", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_existing_conversation_keeps_original_messages_on_stream_error(self) -> None:
        provider_id = self.create_provider()
        conversation_id = self.create_conversation_with_message(provider_id)
        original_messages = self.fetch_messages()

        async def fake_stream_provider_events(provider, payload):
            self.assertEqual(payload["messages"][0]["content"], "旧消息")
            self.assertEqual(payload["messages"][-1]["content"], "这轮失败后不能写入")
            yield 'data: {"type":"content_block_delta","delta":{"text":"半截"}}'
            raise RuntimeError("provider boom")

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider_id": provider_id,
                    "conversation_id": conversation_id,
                    "text": "这轮失败后不能写入",
                    "attachments": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.fetch_messages(), original_messages)
        self.assertEqual(self.count_conversations(), 1)

    def test_stream_without_done_marker_does_not_persist_partial_round(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"text":"未完成"}}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "不要提交", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

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
                    "content_json": json.dumps(
                        {
                            "parts": [
                                {
                                    "id": "thinking-1",
                                    "kind": "thinking",
                                    "status": "done",
                                    "text": "先想一下",
                                },
                                {
                                    "id": "answer-1",
                                    "kind": "answer",
                                    "status": "done",
                                    "text": "正常结束",
                                },
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    "thinking_text": "先想一下",
                },
            ],
        )

    def test_stream_response_completed_still_commits(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"text":"完成事件也提交"}}'
            yield 'data: {"type":"response.completed"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "测试 response.completed", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            self.fetch_messages(),
            [
                {
                    "role": "user",
                    "content_text": "测试 response.completed",
                    "content_json": None,
                    "thinking_text": "",
                },
                {
                    "role": "assistant",
                    "content_text": "完成事件也提交",
                    "content_json": json.dumps(
                        {
                            "parts": [
                                {
                                    "id": "answer-1",
                                    "kind": "answer",
                                    "status": "done",
                                    "text": "完成事件也提交",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    "thinking_text": "",
                },
            ],
        )

    def test_stream_error_event_returns_error_and_rolls_back(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"text":"半截"}}'
            yield 'data: {"type":"error","error":{"message":"provider event boom"}}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "错误事件不提交", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1], {"type": "error", "detail": "provider event boom"})
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_stream_response_error_event_uses_stable_detail_and_rolls_back(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"text":"半截"}}'
            yield 'data: {"type":"response.error","error":"bad shape","detail":"response event boom"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={"provider_id": provider_id, "text": "response.error 不提交", "attachments": []},
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1], {"type": "error", "detail": "response event boom"})
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_tavily_search_without_configured_key_fails_and_rolls_back(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

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

    def test_search_enabled_injects_only_selected_tool_schema(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

        async def fake_stream_provider_events(provider, payload):
            self.assertEqual(len(payload["tools"]), 1)
            self.assertEqual(payload["tools"][0]["name"], "exa_search")
            yield 'data: {"type":"content_block_delta","delta":{"text":"已使用 Exa"}}'
            yield "data: [DONE]"

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider_id": provider_id,
                    "text": "请搜索",
                    "enable_search": True,
                    "search_provider": "exa",
                    "attachments": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(self.count_conversations(), 1)

    def test_native_tool_call_emits_timeline_parts_in_order(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)
        provider_payloads: list[dict[str, object]] = []

        async def fake_stream_provider_events(provider, payload):
            provider_payloads.append(json.loads(json.dumps(payload)))
            if len(provider_payloads) == 1:
                self.assertEqual(payload["tools"][0]["name"], "exa_search")
                yield 'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}'
                yield 'data: {"type":"content_block_delta","index":0,"delta":{"thinking":"先分析"}}'
                yield 'data: {"type":"content_block_stop","index":0}'
                yield 'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","name":"exa_search","id":"toolu_1","input":{"query":"你好"}}}'
                yield 'data: {"type":"content_block_stop","index":1}'
                yield 'data: {"type":"message_stop"}'
                return

            assistant_tool_use_message = payload["messages"][-2]
            tool_result_message = payload["messages"][-1]
            self.assertEqual(assistant_tool_use_message["role"], "assistant")
            self.assertEqual(
                assistant_tool_use_message["content"],
                [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "exa_search",
                        "input": {"query": "你好"},
                    }
                ],
            )
            self.assertEqual(tool_result_message["role"], "user")
            self.assertEqual(
                tool_result_message["content"],
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "结果",
                    }
                ],
            )
            yield 'data: {"type":"content_block_start","index":2,"content_block":{"type":"text"}}'
            yield 'data: {"type":"content_block_delta","index":2,"delta":{"text":"最终回答"}}'
            yield 'data: {"type":"content_block_stop","index":2}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events), patch(
            "app.tool_runtime.execute_native_search_tool",
            return_value={"label": "Exa 搜索", "detail": "返回 1 个内容块", "output": "结果"},
        ) as execute_native_search_tool:
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

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
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
        execute_native_search_tool.assert_called_once_with("exa", {"query": "你好"}, "")
        self.assertEqual(len(provider_payloads), 2)
        self.assertEqual(events[-1]["type"], "done")
        assistant = events[-1]["messages"][1]
        self.assertEqual(
            [part["kind"] for part in assistant["parts"]],
            ["thinking", "tool", "answer"],
        )
        self.assertEqual(assistant["parts"][0]["text"], "先分析")
        self.assertEqual(assistant["parts"][1]["output"], "结果")
        self.assertEqual(assistant["parts"][2]["text"], "最终回答")
        messages = self.fetch_messages()
        self.assertEqual(len(messages), 2)
        persisted_parts = json.loads(messages[1]["content_json"])["parts"]
        self.assertEqual(
            [part["kind"] for part in persisted_parts],
            ["thinking", "tool", "answer"],
        )

    def test_native_tool_call_waits_for_input_json_delta_until_content_block_stop(
        self,
    ) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)
        provider_payloads: list[dict[str, object]] = []
        state = {"tool_stop_seen": False}

        async def fake_stream_provider_events(provider, payload):
            provider_payloads.append(json.loads(json.dumps(payload)))
            if len(provider_payloads) == 1:
                yield 'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"exa_search","id":"toolu_1","input":{}}}'
                yield 'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\": \\"你"}}'
                yield 'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"好\\"}"}}'
                state["tool_stop_seen"] = True
                yield 'data: {"type":"content_block_stop","index":0}'
                yield 'data: {"type":"message_stop"}'
                return

            assistant_tool_use_message = payload["messages"][-2]
            tool_result_message = payload["messages"][-1]
            self.assertEqual(
                assistant_tool_use_message,
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "exa_search",
                            "input": {"query": "你好"},
                        }
                    ],
                },
            )
            self.assertEqual(
                tool_result_message,
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "结果",
                        }
                    ],
                },
            )
            yield 'data: {"type":"content_block_start","index":1,"content_block":{"type":"text"}}'
            yield 'data: {"type":"content_block_delta","index":1,"delta":{"text":"最终回答"}}'
            yield 'data: {"type":"content_block_stop","index":1}'
            yield 'data: {"type":"message_stop"}'

        def fake_execute_native_search_tool(
            kind: str,
            arguments: dict[str, object],
            tavily_api_key: str = "",
        ) -> dict[str, str]:
            self.assertTrue(state["tool_stop_seen"])
            self.assertEqual(kind, "exa")
            self.assertEqual(arguments, {"query": "你好"})
            self.assertEqual(tavily_api_key, "")
            return {"label": "Exa 搜索", "detail": "返回 1 个内容块", "output": "结果"}

        with patch("app.main.stream_provider_events", fake_stream_provider_events), patch(
            "app.tool_runtime.execute_native_search_tool",
            side_effect=fake_execute_native_search_tool,
        ) as execute_native_search_tool:
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

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")
        execute_native_search_tool.assert_called_once()
        self.assertEqual(len(provider_payloads), 2)

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

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(
            [event["type"] for event in events],
            [
                "conversation",
                "timeline_part_start",
                "timeline_part_error",
                "error",
            ],
        )
        self.assertEqual(events[1]["part"]["kind"], "tool")
        self.assertEqual(events[2]["part_id"], "toolu_1")
        self.assertEqual(events[2]["detail"], "搜索失败")
        self.assertEqual(events[-1]["detail"], "搜索失败")
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_search_enabled_on_provider_without_tool_calling_fails(self) -> None:
        provider_id = self.create_provider()
        self.disable_provider_tool_support(provider_id)

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

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("工具调用", events[-1]["detail"])

    def test_search_with_only_image_and_empty_text_returns_http_400(self) -> None:
        provider_id = self.create_provider(supports_vision=True)

        response = self.client.post(
            "/api/chat/stream",
            json={
                "provider_id": provider_id,
                "text": "   ",
                "enable_search": True,
                "search_provider": "exa",
                "attachments": [
                    {
                        "name": "image.png",
                        "media_type": "image/png",
                        "data": "aGVsbG8=",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "搜索关键词不能为空")
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_execute_search_tool_dispatches_to_exa_runner(self) -> None:
        with patch("app.chat_service.run_exa_search") as run_exa_search:
            run_exa_search.return_value = {
                "label": "Exa 搜索",
                "detail": "找到 2 条结果",
                "output": "- result 1\n- result 2",
            }

            result = chat_service.execute_search_tool("exa_search", "查一下")

        run_exa_search.assert_called_once_with("查一下")
        self.assertEqual(
            result,
            {
                "label": "Exa 搜索",
                "detail": "找到 2 条结果",
                "output": "- result 1\n- result 2",
            },
        )

    def test_execute_search_tool_dispatches_to_tavily_runner(self) -> None:
        with patch("app.chat_service.run_tavily_search") as run_tavily_search:
            run_tavily_search.return_value = {
                "label": "Tavily 搜索",
                "detail": "找到 1 条结果",
                "output": "- tavily result",
            }

            result = chat_service.execute_search_tool("tavily_search", "查 tavily")

        run_tavily_search.assert_called_once_with("查 tavily")
        self.assertEqual(
            result,
            {
                "label": "Tavily 搜索",
                "detail": "找到 1 条结果",
                "output": "- tavily result",
            },
        )

    def test_post_mcp_jsonrpc_posts_http_jsonrpc_request(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.headers = {"Content-Type": "application/json"}
        response.text = '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
        response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"ok": True},
        }

        client = MagicMock()
        client.post.return_value = response

        httpx_client = MagicMock()
        httpx_client.return_value.__enter__.return_value = client

        with patch("app.chat_service.httpx.Client", httpx_client):
            body, headers = chat_service._post_mcp_jsonrpc(
                "https://example.invalid/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                {"Mcp-Method": "initialize"},
            )

        client.post.assert_called_once_with(
            "https://example.invalid/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Mcp-Method": "initialize"},
        )
        self.assertEqual(body, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_extract_jsonrpc_response_from_sse_prefers_last_rpc_response_over_notification(
        self,
    ) -> None:
        response_text = (
            'data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"搜索结果"}]}}\n\n'
            'data: {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info"}}\n\n'
        )

        result = chat_service._extract_jsonrpc_response_from_sse(response_text)

        self.assertEqual(
            result,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "搜索结果"}]},
            },
        )

    def test_extract_jsonrpc_response_from_sse_ignores_trailing_server_request_with_id(
        self,
    ) -> None:
        response_text = (
            'data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"搜索结果"}]}}\n\n'
            'data: {"jsonrpc":"2.0","id":99,"method":"ping","params":{"value":"still not response"}}\n\n'
        )

        result = chat_service._extract_jsonrpc_response_from_sse(response_text)

        self.assertEqual(
            result,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "搜索结果"}]},
            },
        )

    def test_call_remote_mcp_tool_initializes_notifies_then_calls_tool(self) -> None:
        with patch("app.chat_service._post_mcp_jsonrpc") as post_mcp_jsonrpc:
            post_mcp_jsonrpc.side_effect = [
                (
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "exa", "version": "1.0.0"},
                        },
                    },
                    {"MCP-Session-Id": "session-123"},
                ),
                (None, {"MCP-Session-Id": "session-123"}),
                (
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "content": [{"type": "text", "text": "搜索结果正文"}],
                        },
                    },
                    {"MCP-Session-Id": "session-123"},
                ),
            ]

            result = chat_service.call_remote_mcp_tool(
                "https://mcp.exa.ai/mcp",
                "web_search_exa",
                {"query": "查一下"},
            )

        self.assertEqual(
            result,
            {"content": [{"type": "text", "text": "搜索结果正文"}]},
        )
        self.assertEqual(post_mcp_jsonrpc.call_count, 3)

        initialize_call = post_mcp_jsonrpc.call_args_list[0]
        self.assertEqual(initialize_call.args[0], "https://mcp.exa.ai/mcp")
        self.assertEqual(initialize_call.args[1]["method"], "initialize")
        self.assertEqual(
            initialize_call.args[1]["params"]["protocolVersion"], "2025-06-18"
        )
        self.assertEqual(
            initialize_call.args[1]["params"]["clientInfo"]["name"],
            "deepfake-backend",
        )
        self.assertEqual(initialize_call.args[2]["Mcp-Method"], "initialize")

        initialized_call = post_mcp_jsonrpc.call_args_list[1]
        self.assertEqual(initialized_call.args[1]["method"], "notifications/initialized")
        self.assertEqual(
            initialized_call.args[2]["MCP-Protocol-Version"], "2025-06-18"
        )
        self.assertEqual(initialized_call.args[2]["MCP-Session-Id"], "session-123")
        self.assertEqual(
            initialized_call.args[2]["Mcp-Method"], "notifications/initialized"
        )

        tools_call = post_mcp_jsonrpc.call_args_list[2]
        self.assertEqual(tools_call.args[1]["method"], "tools/call")
        self.assertEqual(tools_call.args[1]["params"]["name"], "web_search_exa")
        self.assertEqual(tools_call.args[1]["params"]["arguments"], {"query": "查一下"})
        self.assertEqual(tools_call.args[2]["Mcp-Method"], "tools/call")
        self.assertEqual(tools_call.args[2]["Mcp-Name"], "web_search_exa")
        self.assertEqual(tools_call.args[2]["MCP-Protocol-Version"], "2025-06-18")
        self.assertEqual(tools_call.args[2]["MCP-Session-Id"], "session-123")

    def test_run_exa_search_calls_exa_remote_mcp_tool(self) -> None:
        with patch("app.tool_runtime.execute_native_search_tool") as execute_native_search_tool:
            execute_native_search_tool.return_value = {
                "label": "Exa 搜索",
                "detail": "返回 2 个内容块",
                "output": "结果 1\n\n结果 2",
            }

            result = chat_service.run_exa_search("查一下")

        execute_native_search_tool.assert_called_once_with(
            "exa",
            {"query": "查一下"},
        )
        self.assertEqual(
            result,
            {
                "label": "Exa 搜索",
                "detail": "返回 2 个内容块",
                "output": "结果 1\n\n结果 2",
            },
        )

    def test_run_tavily_search_calls_tavily_remote_mcp_tool(self) -> None:
        with patch(
            "app.main.get_tavily_config",
            return_value={
                "api_key": "tvly-secret",
                "is_enabled": True,
                "is_configured": True,
            },
        ):
            with patch(
                "app.tool_runtime.execute_native_search_tool"
            ) as execute_native_search_tool:
                execute_native_search_tool.return_value = {
                    "label": "Tavily 搜索",
                    "detail": "返回 1 个内容块",
                    "output": "Tavily 结果",
                }

                result = chat_service.run_tavily_search("查 tavily")

        execute_native_search_tool.assert_called_once_with(
            "tavily",
            {"query": "查 tavily"},
            tavily_api_key="tvly-secret",
        )
        self.assertEqual(
            result,
            {
                "label": "Tavily 搜索",
                "detail": "返回 1 个内容块",
                "output": "Tavily 结果",
            },
        )

    def test_search_enabled_does_not_preinject_search_result_message(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

        async def fake_stream_provider_events(provider, payload):
            self.assertEqual(payload["messages"][-1]["role"], "user")
            self.assertEqual(payload["messages"][-1]["content"], "查一下")
            self.assertEqual(payload["tools"][0]["name"], "exa_search")
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

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")

    def test_multimodal_search_keeps_original_user_content_and_selected_tool(self) -> None:
        provider_id = self.create_provider(supports_vision=True)
        self.enable_provider_tool_support(provider_id)

        async def fake_stream_provider_events(provider, payload):
            self.assertIsInstance(payload["messages"][-1]["content"], list)
            self.assertEqual(payload["tools"][0]["name"], "exa_search")
            yield 'data: {"type":"content_block_delta","delta":{"text":"回答"}}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = self.client.post(
                "/api/chat/stream",
                json={
                    "provider_id": provider_id,
                    "text": "图里是什么，顺便搜一下",
                    "enable_search": True,
                    "search_provider": "exa",
                    "attachments": [
                        {
                            "name": "test.png",
                            "media_type": "image/png",
                            "data": "aGVsbG8=",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")

    def test_search_enabled_does_not_invoke_app_side_search_before_streaming(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

        async def fake_stream_provider_events(provider, payload):
            self.assertEqual(payload["messages"][-1]["content"], "线程搜索")
            self.assertEqual(payload["tools"][0]["name"], "exa_search")
            yield 'data: {"type":"content_block_delta","delta":{"text":"线程回答"}}'
            yield 'data: {"type":"message_stop"}'

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            with patch("app.main.asyncio.to_thread") as to_thread:
                response = self.client.post(
                    "/api/chat/stream",
                    json={
                        "provider_id": provider_id,
                        "text": "线程搜索",
                        "enable_search": True,
                        "search_provider": "exa",
                        "attachments": [],
                    },
                )

        self.assertEqual(response.status_code, 200)
        to_thread.assert_not_called()
        events = self.parse_stream_events(response)
        self.assertEqual(events[-1]["type"], "done")

    def test_search_enabled_does_not_emit_legacy_stream_events(self) -> None:
        provider_id = self.create_provider()
        self.enable_provider_tool_support(provider_id)

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

        self.assertEqual(response.status_code, 200)
        events = self.parse_stream_events(response)
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[-1]["type"], "done")
        self.assertFalse(
            any(
                event["type"] in {"text_delta", "thinking_delta", "activity"}
                for event in events
            )
        )
        self.assertEqual(self.count_conversations(), 1)

    def test_empty_message_keeps_original_http_400(self) -> None:
        provider_id = self.create_provider()

        response = self.client.post(
            "/api/chat/stream",
            json={"provider_id": provider_id, "text": "   ", "attachments": []},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "消息内容不能为空")
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_missing_provider_keeps_original_http_404(self) -> None:
        response = self.client.post(
            "/api/chat/stream",
            json={"provider_id": 999999, "text": "provider missing", "attachments": []},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "供应商不存在")
        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)

    def test_cancelled_stream_rolls_back_new_conversation(self) -> None:
        provider_id = self.create_provider()

        async def fake_stream_provider_events(provider, payload):
            yield 'data: {"type":"content_block_delta","delta":{"text":"取消前输出"}}'
            raise asyncio.CancelledError()

        with patch("app.main.stream_provider_events", fake_stream_provider_events):
            response = asyncio.run(
                main.stream_message(
                    main.ChatPayload(
                        provider_id=provider_id,
                        text="取消这轮",
                        attachments=[],
                    ),
                    self.user,
                )
            )
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.collect_stream_chunks(response))

        self.assertEqual(self.fetch_messages(), [])
        self.assertEqual(self.count_conversations(), 0)
