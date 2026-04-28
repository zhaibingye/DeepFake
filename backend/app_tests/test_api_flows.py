from __future__ import annotations

import asyncio
import json
import shutil
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import db
from app.db import get_conn
from app.main import app
from app.provider_client import (
    append_provider_tool_result_messages,
    build_provider_curl_request,
    build_provider_payload,
    convert_openai_chat_payload_to_internal_events,
    convert_openai_chunk_to_events,
    convert_openai_response_event_to_events,
    GatewayState,
    OpenAIChatAdapter,
    OpenAIResponsesAdapter,
    resolve_adapter,
    provider_supports_native_tool_calling,
    ProviderRuntimeState,
    stream_gateway_events,
    stream_provider_events,
)


def text_stream_lines(text: str) -> list[str]:
    return [
        f'data: {json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}, ensure_ascii=False)}',
        f'data: {json.dumps({"type": "content_block_delta", "index": 0, "delta": {"text": text}}, ensure_ascii=False)}',
        f'data: {json.dumps({"type": "content_block_stop", "index": 0}, ensure_ascii=False)}',
        f'data: {json.dumps({"type": "message_stop"}, ensure_ascii=False)}',
    ]


class ApiFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path.cwd() / ".test-data"
        test_root.mkdir(exist_ok=True)
        self.temp_path = test_root / f"case-{uuid4().hex}"
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self.data_dir_patch = patch.object(db, "DATA_DIR", self.temp_path)
        self.db_path_patch = patch.object(db, "DB_PATH", self.temp_path / "app.db")
        self.data_dir_patch.start()
        self.db_path_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.db_path_patch.stop()
        self.data_dir_patch.stop()
        shutil.rmtree(self.temp_path, ignore_errors=True)

    def auth_header(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def setup_admin(self) -> dict[str, object]:
        response = self.client.post(
            "/api/setup/admin",
            json={"username": "admin", "password": "password123"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def create_provider(self, token: str) -> dict[str, object]:
        return self.create_provider_with(token)

    def create_provider_with(self, token: str, **overrides: object) -> dict[str, object]:
        payload = {
            "name": "Test Provider",
            "api_format": "anthropic_messages",
            "api_url": "https://example.com/anthropic/v1",
            "api_key": "test-key",
            "model_name": "claude-test",
            "supports_thinking": True,
            "supports_vision": False,
            "supports_tool_calling": False,
            "thinking_effort": "high",
            "max_context_window": 256000,
            "max_output_tokens": 32000,
            "is_enabled": True,
        }
        payload.update(overrides)
        response = self.client.post(
            "/api/admin/providers",
            headers=self.auth_header(token),
            json=payload,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def stream_chat(
        self,
        token: str,
        provider_id: int,
        stream_lines: list[str],
        conversation_id: int | None = None,
    ) -> list[dict[str, object]]:
        async def fake_stream_provider_events(provider, payload, runtime_state=None):
            for line in stream_lines:
                yield line

        with patch(
            "app.chat_stream_service.stream_provider_events",
            fake_stream_provider_events,
        ):
            with self.client.stream(
                "POST",
                "/api/chat/stream",
                headers=self.auth_header(token),
                json={
                    "provider_id": provider_id,
                    "conversation_id": conversation_id,
                    "text": "hello",
                    "enable_thinking": False,
                    "enable_search": False,
                    "search_provider": None,
                    "effort": "high",
                    "attachments": [],
                },
            ) as response:
                self.assertEqual(response.status_code, 200)
                return [json.loads(line) for line in response.iter_lines() if line]

    def test_admin_setup_and_login_flow(self) -> None:
        status_response = self.client.get("/api/setup/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json(), {"needs_admin_setup": True})

        setup_payload = self.setup_admin()
        token = str(setup_payload["token"])

        me_response = self.client.get("/api/auth/me", headers=self.auth_header(token))
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["username"], "admin")

        login_response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("token", login_response.json())

    def test_disabled_user_session_is_rejected(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])

        create_user = self.client.post(
            "/api/admin/users",
            headers=self.auth_header(admin_token),
            json={
                "username": "member",
                "password": "password123",
                "role": "user",
                "is_enabled": True,
            },
        )
        self.assertEqual(create_user.status_code, 200)
        user_id = create_user.json()["id"]

        login_response = self.client.post(
            "/api/auth/login",
            json={"username": "member", "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)
        user_token = login_response.json()["token"]

        disable_response = self.client.put(
            f"/api/admin/users/{user_id}",
            headers=self.auth_header(admin_token),
            json={"is_enabled": False},
        )
        self.assertEqual(disable_response.status_code, 200)

        me_response = self.client.get("/api/auth/me", headers=self.auth_header(user_token))
        self.assertEqual(me_response.status_code, 401)
        self.assertEqual(me_response.json()["detail"], "登录已失效")

    def test_conversation_crud_roundtrip(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider(admin_token)

        events = self.stream_chat(
            admin_token,
            int(provider["id"]),
            text_stream_lines("streamed answer"),
        )
        done_event = events[-1]
        self.assertEqual(done_event["type"], "done")
        conversation_id = int(done_event["conversation"]["id"])

        list_response = self.client.get(
            "/api/conversations",
            headers=self.auth_header(admin_token),
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        messages_response = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self.auth_header(admin_token),
        )
        self.assertEqual(messages_response.status_code, 200)
        self.assertEqual(len(messages_response.json()["messages"]), 2)

        rename_response = self.client.put(
            f"/api/conversations/{conversation_id}",
            headers=self.auth_header(admin_token),
            json={"title": "renamed"},
        )
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.json()["title"], "renamed")

        delete_response = self.client.delete(
            f"/api/conversations/{conversation_id}",
            headers=self.auth_header(admin_token),
        )
        self.assertEqual(delete_response.status_code, 200)

        final_list = self.client.get(
            "/api/conversations",
            headers=self.auth_header(admin_token),
        )
        self.assertEqual(final_list.json(), [])

    def test_chat_stream_failure_rolls_back_new_conversation(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider(admin_token)

        failed_events = self.stream_chat(
            admin_token,
            int(provider["id"]),
            [
                f'data: {json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}, ensure_ascii=False)}',
                f'data: {json.dumps({"type": "response.error", "error": {"message": "provider failed"}}, ensure_ascii=False)}',
            ],
        )
        self.assertEqual(failed_events[-1], {"type": "error", "detail": "provider failed"})

        list_response = self.client.get(
            "/api/conversations",
            headers=self.auth_header(admin_token),
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), [])

    def test_openai_chat_stream_preserves_answer_tool_followup_timeline_order(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider_with(
            admin_token,
            name="OpenAI Chat Provider",
            api_format="openai_chat",
            api_url="https://example.com/openai/v1",
            model_name="gpt-4o",
            supports_thinking=False,
            supports_tool_calling=True,
        )

        stream_rounds = [
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"text":"先回答一段"}}',
                'data: {"type":"content_block_stop","index":0}',
                'data: {"type":"content_block_start","index":100,"content_block":{"type":"tool_use","id":"call_1","name":"exa_search","input":{}}}',
                'data: {"type":"content_block_delta","index":100,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":\\"hello\\"}"}}',
                'data: {"type":"content_block_stop","index":100}',
                "data: [DONE]",
            ],
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"text":"工具后补充回答"}}',
                'data: {"type":"content_block_stop","index":0}',
                'data: {"type":"message_stop"}',
                "data: [DONE]",
            ],
        ]
        seen_payloads: list[dict[str, object]] = []
        seen_runtime_states: list[list[dict[str, object]] | None] = []

        async def fake_stream_provider_events(provider, payload, runtime_state=None):
            seen_payloads.append(json.loads(json.dumps(payload)))
            seen_runtime_states.append(
                None
                if runtime_state is None
                else json.loads(json.dumps(runtime_state.responses_input_history))
            )
            current_round = stream_rounds[len(seen_payloads) - 1]
            for line in current_round:
                yield line

        with (
            patch(
                "app.chat_stream_service.stream_provider_events",
                fake_stream_provider_events,
            ),
            patch(
                "app.chat_stream_service.tool_runtime.execute_native_search_tool",
                return_value={
                    "label": "Exa 搜索",
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
            ),
            patch(
                "app.chat_stream_service.get_exa_config",
                return_value={"api_key": "", "is_enabled": True},
            ),
            patch(
                "app.chat_stream_service.get_tavily_config",
                return_value={"api_key": "", "is_enabled": False},
            ),
        ):
            with self.client.stream(
                "POST",
                "/api/chat/stream",
                headers=self.auth_header(admin_token),
                json={
                    "provider_id": int(provider["id"]),
                    "conversation_id": None,
                    "text": "hello",
                    "enable_thinking": False,
                    "enable_search": True,
                    "search_provider": "exa",
                    "effort": "high",
                    "attachments": [],
                },
            ) as response:
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.iter_lines() if line]

        self.assertEqual(len(seen_payloads), 2)
        self.assertEqual(
            seen_payloads[1]["messages"][-2],
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "exa_search",
                            "arguments": '{"query": "hello"}',
                        },
                    }
                ],
            },
        )
        self.assertEqual(
            seen_payloads[1]["messages"][-1],
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "search result",
            },
        )

        event_types = [event["type"] for event in events]
        self.assertEqual(
            event_types,
            [
                "conversation",
                "timeline_part_start",
                "timeline_part_delta",
                "timeline_part_end",
                "timeline_part_start",
                "timeline_part_delta",
                "timeline_part_end",
                "timeline_part_start",
                "timeline_part_delta",
                "timeline_part_end",
                "done",
            ],
        )
        started_parts = [
            (event["part"]["kind"], event["part"]["id"])
            for event in events
            if event["type"] == "timeline_part_start"
        ]
        self.assertEqual(
            started_parts,
            [
                ("answer", "answer-1"),
                ("tool", "call_1"),
                ("answer", "answer-2"),
            ],
        )
        done_event = events[-1]
        self.assertEqual(done_event["type"], "done")
        self.assertEqual(
            done_event["messages"][-1]["parts"],
            [
                {
                    "id": "answer-1",
                    "kind": "answer",
                    "status": "done",
                    "text": "先回答一段",
                },
                {
                    "id": "call_1",
                    "kind": "tool",
                    "status": "done",
                    "tool_name": "exa_search",
                    "label": "Exa 搜索",
                    "input": '{"query": "hello"}',
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
                {
                    "id": "answer-2",
                    "kind": "answer",
                    "status": "done",
                    "text": "工具后补充回答",
                },
            ],
        )

    def test_openai_responses_followup_error_is_reported_without_message_replay(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider_with(
            admin_token,
            name="OpenAI Responses Provider",
            api_format="openai_responses",
            api_url="https://example.com/openai/v1",
            model_name="gpt-5.4",
            supports_thinking=False,
            supports_tool_calling=True,
        )

        seen_payloads: list[dict[str, object]] = []
        seen_runtime_states: list[list[dict[str, object]] | None] = []

        async def fake_stream_provider_events(provider, payload, runtime_state=None):
            seen_payloads.append(json.loads(json.dumps(payload)))
            seen_runtime_states.append(
                None
                if runtime_state is None
                else json.loads(json.dumps(runtime_state.responses_input_history))
            )
            if len(seen_payloads) == 1:
                if runtime_state is not None:
                    runtime_state.last_response_id = "resp_1"
                    runtime_state.responses_output_items = [
                        {
                            "type": "function_call",
                            "call_id": "call_resp_1",
                            "name": "exa_search",
                            "arguments": '{"query":"hello"}',
                        }
                    ]
                payload["_last_response_id"] = "resp_1"
                payload["_responses_output_items"] = [
                    {
                        "type": "function_call",
                        "call_id": "call_resp_1",
                        "name": "exa_search",
                        "arguments": '{"query":"hello"}',
                    }
                ]
                yield 'data: {"type":"content_block_start","index":100,"content_block":{"type":"tool_use","id":"call_resp_1","name":"exa_search","input":{}}}'
                yield 'data: {"type":"content_block_delta","index":100,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":\\"hello\\"}"}}'
                yield 'data: {"type":"content_block_stop","index":100}'
                yield 'data: {"type":"message_stop"}'
                yield "data: [DONE]"
                return
            raise HTTPException(
                status_code=502,
                detail="供应商调用失败: No tool call found for function call output with call_id call_resp_1.",
            )

        with (
            patch(
                "app.chat_stream_service.stream_provider_events",
                fake_stream_provider_events,
            ),
            patch(
                "app.chat_stream_service.tool_runtime.execute_native_search_tool",
                return_value={
                    "label": "Exa 搜索",
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
            ),
            patch(
                "app.chat_stream_service.get_exa_config",
                return_value={"api_key": "", "is_enabled": True},
            ),
            patch(
                "app.chat_stream_service.get_tavily_config",
                return_value={"api_key": "", "is_enabled": False},
            ),
        ):
            with self.client.stream(
                "POST",
                "/api/chat/stream",
                headers=self.auth_header(admin_token),
                json={
                    "provider_id": int(provider["id"]),
                    "conversation_id": None,
                    "text": "hello",
                    "enable_thinking": False,
                    "enable_search": True,
                    "search_provider": "exa",
                    "effort": "high",
                    "attachments": [],
                },
            ) as response:
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.iter_lines() if line]

        self.assertEqual(len(seen_payloads), 2)
        self.assertEqual(
            seen_runtime_states[1],
            [
                {"role": "user", "content": "hello"},
                {
                    "type": "function_call",
                    "call_id": "call_resp_1",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_resp_1",
                    "output": "search result",
                }
            ],
        )
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("No tool call found", events[-1]["detail"])

    def test_openai_responses_stream_preserves_answer_tool_followup_timeline_order(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider_with(
            admin_token,
            name="OpenAI Responses Provider",
            api_format="openai_responses",
            api_url="https://example.com/openai/v1",
            model_name="gpt-4.1",
            supports_thinking=False,
            supports_tool_calling=True,
        )

        stream_rounds = [
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"text":"先回答一段"}}',
                'data: {"type":"content_block_stop","index":0}',
                'data: {"type":"content_block_start","index":100,"content_block":{"type":"tool_use","id":"call_resp_1","name":"exa_search","input":{}}}',
                'data: {"type":"content_block_delta","index":100,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":\\"hello\\"}"}}',
                'data: {"type":"content_block_stop","index":100}',
                'data: {"type":"message_stop"}',
                "data: [DONE]",
            ],
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"text":"工具后补充回答"}}',
                'data: {"type":"content_block_stop","index":0}',
                'data: {"type":"message_stop"}',
                "data: [DONE]",
            ],
        ]
        seen_payloads: list[dict[str, object]] = []
        seen_runtime_states: list[list[dict[str, object]] | None] = []

        async def fake_stream_provider_events(provider, payload, runtime_state=None):
            seen_payloads.append(json.loads(json.dumps(payload)))
            seen_runtime_states.append(
                None
                if runtime_state is None
                else json.loads(json.dumps(runtime_state.responses_input_history))
            )
            if runtime_state is not None:
                runtime_state.last_response_id = f"resp_{len(seen_payloads)}"
            payload["_last_response_id"] = f"resp_{len(seen_payloads)}"
            if len(seen_payloads) == 1:
                if runtime_state is not None:
                    runtime_state.responses_output_items = [
                        {
                            "type": "function_call",
                            "call_id": "call_resp_1",
                            "name": "exa_search",
                            "arguments": '{"query":"hello"}',
                        }
                    ]
                payload["_responses_output_items"] = [
                    {
                        "type": "function_call",
                        "call_id": "call_resp_1",
                        "name": "exa_search",
                        "arguments": '{"query":"hello"}',
                    }
                ]
            current_round = stream_rounds[len(seen_payloads) - 1]
            for line in current_round:
                yield line

        with (
            patch(
                "app.chat_stream_service.stream_provider_events",
                fake_stream_provider_events,
            ),
            patch(
                "app.chat_stream_service.tool_runtime.execute_native_search_tool",
                return_value={
                    "label": "Exa 搜索",
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
            ),
            patch(
                "app.chat_stream_service.get_exa_config",
                return_value={"api_key": "", "is_enabled": True},
            ),
            patch(
                "app.chat_stream_service.get_tavily_config",
                return_value={"api_key": "", "is_enabled": False},
            ),
        ):
            with self.client.stream(
                "POST",
                "/api/chat/stream",
                headers=self.auth_header(admin_token),
                json={
                    "provider_id": int(provider["id"]),
                    "conversation_id": None,
                    "text": "hello",
                    "enable_thinking": False,
                    "enable_search": True,
                    "search_provider": "exa",
                    "effort": "high",
                    "attachments": [],
                },
            ) as response:
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.iter_lines() if line]

        self.assertEqual(len(seen_payloads), 2)
        self.assertEqual(
            seen_runtime_states[1],
            [
                {"role": "user", "content": "hello"},
                {
                    "type": "function_call",
                    "call_id": "call_resp_1",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_resp_1",
                    "output": "search result",
                }
            ],
        )

        started_parts = [
            (event["part"]["kind"], event["part"]["id"])
            for event in events
            if event["type"] == "timeline_part_start"
        ]
        self.assertEqual(
            started_parts,
            [
                ("answer", "answer-1"),
                ("tool", "call_resp_1"),
                ("answer", "answer-2"),
            ],
        )
        done_event = events[-1]
        self.assertEqual(
            done_event["messages"][-1]["parts"],
            [
                {
                    "id": "answer-1",
                    "kind": "answer",
                    "status": "done",
                    "text": "先回答一段",
                },
                {
                    "id": "call_resp_1",
                    "kind": "tool",
                    "status": "done",
                    "tool_name": "exa_search",
                    "label": "Exa 搜索",
                    "input": '{"query": "hello"}',
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
                {
                    "id": "answer-2",
                    "kind": "answer",
                    "status": "done",
                    "text": "工具后补充回答",
                },
            ],
        )

    def test_openai_responses_followup_waits_for_stream_done_after_message_stop(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider_with(
            admin_token,
            name="OpenAI Responses Provider",
            api_format="openai_responses",
            api_url="https://example.com/openai/v1",
            model_name="gpt-5.4",
            supports_thinking=False,
            supports_tool_calling=True,
        )

        rounds = [
            [
                'data: {"type":"content_block_start","index":100,"content_block":{"type":"tool_use","id":"call_resp_1","name":"exa_search","input":{}}}',
                'data: {"type":"content_block_delta","index":100,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":\\"hello\\"}"}}',
                'data: {"type":"content_block_stop","index":100}',
                'data: {"type":"message_stop"}',
                "data: [DONE]",
            ],
            [
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"text":"ok"}}',
                'data: {"type":"content_block_stop","index":0}',
                'data: {"type":"message_stop"}',
                "data: [DONE]",
            ],
        ]
        seen_payloads: list[dict[str, object]] = []
        first_round_done_seen = False

        async def fake_stream_provider_events(provider, payload, runtime_state=None):
            nonlocal first_round_done_seen
            seen_payloads.append(json.loads(json.dumps(payload)))
            current_round = rounds[len(seen_payloads) - 1]
            if len(seen_payloads) == 2:
                self.assertTrue(first_round_done_seen)
                self.assertIsNotNone(runtime_state.responses_input_history)
            for line in current_round:
                if len(seen_payloads) == 1 and line == "data: [DONE]":
                    if runtime_state is not None:
                        runtime_state.last_response_id = "resp_1"
                        runtime_state.responses_output_items = [
                            {
                                "type": "function_call",
                                "call_id": "call_resp_1",
                                "name": "exa_search",
                                "arguments": '{"query":"hello"}',
                            }
                        ]
                    payload["_last_response_id"] = "resp_1"
                    payload["_responses_output_items"] = [
                        {
                            "type": "function_call",
                            "call_id": "call_resp_1",
                            "name": "exa_search",
                            "arguments": '{"query":"hello"}',
                        }
                    ]
                    first_round_done_seen = True
                yield line

        with (
            patch(
                "app.chat_stream_service.stream_provider_events",
                fake_stream_provider_events,
            ),
            patch(
                "app.chat_stream_service.tool_runtime.execute_native_search_tool",
                return_value={
                    "label": "Exa 搜索",
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
            ),
            patch(
                "app.chat_stream_service.get_exa_config",
                return_value={"api_key": "", "is_enabled": True},
            ),
            patch(
                "app.chat_stream_service.get_tavily_config",
                return_value={"api_key": "", "is_enabled": False},
            ),
        ):
            with self.client.stream(
                "POST",
                "/api/chat/stream",
                headers=self.auth_header(admin_token),
                json={
                    "provider_id": int(provider["id"]),
                    "conversation_id": None,
                    "text": "hello",
                    "enable_thinking": False,
                    "enable_search": True,
                    "search_provider": "exa",
                    "effort": "xhigh",
                    "attachments": [],
                },
            ) as response:
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.iter_lines() if line]

        self.assertEqual(len(seen_payloads), 2)
        self.assertTrue(first_round_done_seen)
        self.assertEqual(events[-1]["type"], "done")

    def test_native_search_tool_calls_are_not_capped_per_response(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider_with(
            admin_token,
            name="OpenAI Responses Provider",
            api_format="openai_responses",
            api_url="https://example.com/openai/v1",
            model_name="gpt-5.4",
            supports_thinking=False,
            supports_tool_calling=True,
        )
        seen_payloads: list[dict[str, object]] = []

        async def fake_stream_provider_events(provider, payload, runtime_state=None):
            seen_payloads.append(json.loads(json.dumps(payload)))
            if len(seen_payloads) == 5:
                for line in text_stream_lines("final answer"):
                    yield line
                return
            call_id = f"call_{len(seen_payloads)}"
            if runtime_state is not None:
                runtime_state.responses_output_items = [
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": "exa_search",
                        "arguments": '{"query":"hello"}',
                    }
                ]
            payload["_responses_output_items"] = [
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                }
            ]
            yield f'data: {{"type":"content_block_start","index":100,"content_block":{{"type":"tool_use","id":"{call_id}","name":"exa_search","input":{{}}}}}}'
            yield 'data: {"type":"content_block_delta","index":100,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":\\"hello\\"}"}}'
            yield 'data: {"type":"content_block_stop","index":100}'
            yield 'data: {"type":"message_stop"}'
            yield "data: [DONE]"

        with (
            patch("app.chat_stream_service.stream_provider_events", fake_stream_provider_events),
            patch(
                "app.chat_stream_service.tool_runtime.execute_native_search_tool",
                return_value={
                    "label": "Exa 搜索",
                    "detail": "命中 1 条结果",
                    "output": "search result",
                },
            ),
            patch(
                "app.chat_stream_service.get_exa_config",
                return_value={"api_key": "", "is_enabled": True},
            ),
            patch(
                "app.chat_stream_service.get_tavily_config",
                return_value={"api_key": "", "is_enabled": False},
            ),
        ):
            with self.client.stream(
                "POST",
                "/api/chat/stream",
                headers=self.auth_header(admin_token),
                json={
                    "provider_id": int(provider["id"]),
                    "conversation_id": None,
                    "text": "hello",
                    "enable_thinking": False,
                    "enable_search": True,
                    "search_provider": "exa",
                    "effort": "xhigh",
                    "attachments": [],
                },
            ) as response:
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line) for line in response.iter_lines() if line]

        self.assertEqual(len(seen_payloads), 5)
        self.assertIn("tools", seen_payloads[2])
        self.assertIn("tools", seen_payloads[3])
        self.assertIn("tools", seen_payloads[4])
        self.assertEqual(events[-1]["type"], "done")
        tool_parts = [
            part
            for part in events[-1]["messages"][-1]["parts"]
            if part["kind"] == "tool"
        ]
        self.assertEqual(len(tool_parts), 4)

    def test_provider_update_keeps_existing_url_and_key_when_left_blank(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])
        provider = self.create_provider(admin_token)

        update_response = self.client.put(
            f"/api/admin/providers/{provider['id']}",
            headers=self.auth_header(admin_token),
            json={
                "name": "Updated Provider",
                "api_format": "openai_chat",
                "api_url": "",
                "api_key": "   ",
                "model_name": "claude-next",
                "supports_thinking": False,
                "supports_vision": True,
                "supports_tool_calling": True,
                "thinking_effort": "medium",
                "max_context_window": 128000,
                "max_output_tokens": 16000,
                "is_enabled": False,
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["name"], "Updated Provider")

        with closing(get_conn()) as conn:
            row = conn.execute(
                "SELECT api_format, api_url, api_key FROM providers WHERE id = ?",
                (provider["id"],),
            ).fetchone()
        self.assertEqual(row["api_format"], "openai_chat")
        self.assertEqual(row["api_url"], "https://example.com/anthropic/v1")
        self.assertEqual(row["api_key"], "test-key")

    def test_openai_responses_provider_normalizes_legacy_max_to_xhigh(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])

        response = self.client.post(
            "/api/admin/providers",
            headers=self.auth_header(admin_token),
            json={
                "name": "Responses Provider",
                "api_format": "openai_responses",
                "api_url": "https://example.com/openai/v1",
                "api_key": "test-key",
                "model_name": "gpt-5.4",
                "supports_thinking": True,
                "supports_vision": False,
                "supports_tool_calling": True,
                "thinking_effort": "max",
                "max_context_window": 256000,
                "max_output_tokens": 32000,
                "is_enabled": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["thinking_effort"], "xhigh")

    def test_provider_create_still_requires_url_and_key(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])

        response = self.client.post(
            "/api/admin/providers",
            headers=self.auth_header(admin_token),
            json={
                "name": "Invalid Provider",
                "api_format": "anthropic_messages",
                "api_url": "",
                "api_key": "",
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
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(len(detail), 2)
        self.assertEqual(detail[0]["loc"], ["body", "api_url"])
        self.assertEqual(detail[1]["loc"], ["body", "api_key"])

    def test_convert_openai_chat_chunk_to_internal_events(self) -> None:
        role_events = convert_openai_chunk_to_events(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant"}}],
            }
        )
        text_events = convert_openai_chunk_to_events(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": "hello"}}],
            }
        )
        stop_events = convert_openai_chunk_to_events(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": " world"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

        self.assertEqual(
            [json.loads(event) for event in role_events],
            [],
        )
        self.assertEqual(
            [json.loads(event) for event in text_events],
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"text": "hello"},
                }
            ],
        )
        self.assertEqual(
            [json.loads(event) for event in stop_events],
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"text": " world"},
                },
                {"type": "content_block_stop", "index": 0},
                {"type": "message_stop"},
            ],
        )

    def test_convert_anthropic_stream_events_to_gateway_events(self) -> None:
        adapter = resolve_adapter("anthropic_messages")
        state = GatewayState()

        events: list[dict[str, object]] = []
        for payload in [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0, "delta": {"text": "hello"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ]:
            events.extend(adapter.convert_gateway_event(payload, state=state))

        self.assertEqual(
            events,
            [
                {"type": "text_start", "index": 0},
                {"type": "text_delta", "index": 0, "text": "hello"},
                {"type": "text_end", "index": 0},
                {"type": "turn_end"},
            ],
        )

    def test_convert_openai_responses_events_to_internal_events(self) -> None:
        created_events = convert_openai_response_event_to_events(
            {"type": "response.created", "response": {"id": "resp_1"}}
        )
        thinking_events = convert_openai_response_event_to_events(
            {"type": "response.reasoning_summary_text.delta", "delta": "先想一下"}
        )
        delta_events = convert_openai_response_event_to_events(
            {"type": "response.output_text.delta", "delta": "hello"}
        )
        function_call_events = convert_openai_response_event_to_events(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                },
            }
        )
        completed_events = convert_openai_response_event_to_events(
            {"type": "response.completed", "response": {"id": "resp_1"}}
        )

        self.assertEqual(
            [json.loads(event) for event in created_events],
            [],
        )
        self.assertEqual(
            [json.loads(event) for event in thinking_events],
            [
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "thinking"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"thinking": "先想一下"},
                },
            ],
        )
        self.assertEqual(
            [json.loads(event) for event in delta_events],
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"text": "hello"},
                }
            ],
        )
        self.assertEqual(
            [json.loads(event) for event in function_call_events],
            [
                {
                    "type": "content_block_start",
                    "index": 100,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "exa_search",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 100,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"query":"hello"}',
                    },
                },
                {"type": "content_block_stop", "index": 100},
            ],
        )
        self.assertEqual(
            [json.loads(event) for event in completed_events],
            [{"type": "message_stop"}],
        )

    def test_convert_openai_responses_text_and_reasoning_to_gateway_events(self) -> None:
        adapter = OpenAIResponsesAdapter()
        state = GatewayState()

        reasoning_events = adapter.convert_gateway_event(
            {"type": "response.reasoning_summary_text.delta", "delta": "checking"},
            state=state,
        )
        text_events = adapter.convert_gateway_event(
            {"type": "response.output_text.delta", "delta": "answer"},
            state=state,
        )

        self.assertEqual(
            reasoning_events,
            [
                {"type": "reasoning_start", "index": 1},
                {"type": "reasoning_delta", "index": 1, "text": "checking"},
            ],
        )
        self.assertEqual(
            text_events,
            [
                {"type": "reasoning_end", "index": 1},
                {"type": "text_start", "index": 0},
                {"type": "text_delta", "index": 0, "text": "answer"},
            ],
        )

    def test_convert_openai_responses_function_call_done_to_gateway_events(self) -> None:
        events = OpenAIResponsesAdapter().convert_gateway_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                },
            },
            state=GatewayState(),
        )

        self.assertEqual(
            events,
            [
                {
                    "type": "tool_call_start",
                    "index": 100,
                    "id": "call_1",
                    "name": "exa_search",
                    "input": {},
                },
                {
                    "type": "tool_call_delta",
                    "index": 100,
                    "partial_json": '{"query":"hello"}',
                },
                {"type": "tool_call_end", "index": 100},
            ],
        )

    def test_convert_openai_responses_completed_to_gateway_turn_end(self) -> None:
        events = OpenAIResponsesAdapter().convert_gateway_event(
            {"type": "response.completed", "response": {"id": "resp_1", "output": []}},
            state=GatewayState(),
        )

        self.assertEqual(events, [{"type": "turn_end"}])

    def test_convert_openai_responses_reasoning_output_item_summary_to_internal_events(self) -> None:
        reasoning_events = convert_openai_response_event_to_events(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "reasoning",
                    "summary": [
                        {"type": "summary_text", "text": "先分析问题"},
                    ],
                },
            }
        )
        self.assertEqual(
            [json.loads(event) for event in reasoning_events],
            [
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "thinking"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"thinking": "先分析问题"},
                },
            ],
        )

    def test_provider_stream_uses_reasoning_placeholder_when_proxy_hides_text(self) -> None:
        stdout_chunks = [
            b"event: response.output_item.done\n",
            b'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"reasoning","encrypted_content":"secret","summary":[]}}\n',
            b"event: response.output_text.delta\n",
            b'data: {"type":"response.output_text.delta","output_index":1,"delta":"hello"}\n',
            b"event: response.completed\n",
            b'data: {"type":"response.completed","response":{"id":"resp_1"}}\n',
        ]

        class FakeStdout:
            def __init__(self, chunks: list[bytes]) -> None:
                self._chunks = list(chunks)

            async def readline(self) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        class FakeStderr:
            async def read(self) -> bytes:
                return b""

        class FakeStdin:
            def write(self, data: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout(stdout_chunks)
                self.stderr = FakeStderr()
                self.stdin = FakeStdin()
                self.returncode = None

            async def wait(self) -> int:
                self.returncode = 0
                return 0

            def kill(self) -> None:
                self.returncode = 0

        async def run_case() -> list[str]:
            with patch(
                "app.provider_client.asyncio.create_subprocess_exec",
                return_value=FakeProcess(),
            ):
                events: list[str] = []
                async for event in stream_provider_events(
                    {
                        "api_format": "openai_responses",
                        "api_url": "https://example.com/openai/v1",
                        "api_key": "test-key",
                    },
                    {
                        "model": "gpt-5.4",
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": True,
                    },
                ):
                    events.append(event)
                return events

        events = asyncio.run(run_case())
        self.assertEqual(
            events,
            [
                'data: {"type": "content_block_start", "index": 1, "content_block": {"type": "thinking"}}',
                'data: {"type": "content_block_delta", "index": 1, "delta": {"thinking": "模型已完成思考，但当前供应商未返回可展示的思维文本。"}}',
                'data: {"type": "content_block_stop", "index": 1}',
                'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}',
                'data: {"type": "content_block_delta", "index": 0, "delta": {"text": "hello"}}',
                'data: {"type": "content_block_stop", "index": 0}',
                'data: {"type": "message_stop"}',
            ],
        )

    def test_gateway_stream_emits_neutral_events_without_legacy_content_blocks(self) -> None:
        stdout_chunks = [
            b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hello"}}]}\n',
            b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n',
        ]

        class FakeStdout:
            def __init__(self, chunks: list[bytes]) -> None:
                self._chunks = list(chunks)

            async def readline(self) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        class FakeStderr:
            async def read(self) -> bytes:
                return b""

        class FakeStdin:
            def write(self, data: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout(stdout_chunks)
                self.stderr = FakeStderr()
                self.stdin = FakeStdin()
                self.returncode = None

            async def wait(self) -> int:
                self.returncode = 0
                return 0

            def kill(self) -> None:
                self.returncode = 0

        async def run_case() -> list[dict[str, object]]:
            with patch(
                "app.provider_client.asyncio.create_subprocess_exec",
                return_value=FakeProcess(),
            ):
                events: list[dict[str, object]] = []
                async for event in stream_gateway_events(
                    {
                        "api_format": "openai_chat",
                        "api_url": "https://example.com/openai/v1",
                        "api_key": "test-key",
                    },
                    {
                        "model": "gpt-5.4",
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": True,
                    },
                ):
                    events.append(event)
                return events

        events = asyncio.run(run_case())

        self.assertEqual(
            events,
            [
                {"type": "text_start", "index": 0},
                {"type": "text_delta", "index": 0, "text": "hello"},
                {"type": "text_end", "index": 0},
                {"type": "turn_end"},
            ],
        )
        self.assertNotIn("content_block_start", json.dumps(events))

    def test_openai_chat_thinking_effort_maps_to_completion_budget(self) -> None:
        payload = build_provider_payload(
            {"api_format": "openai_chat"},
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 32000,
                "output_config": {"effort": " medium "},
            },
        )
        self.assertEqual(payload["max_completion_tokens"], 16000)

    def test_openai_chat_thinking_effort_caps_max_to_high_budget(self) -> None:
        payload = build_provider_payload(
            {"api_format": "openai_chat"},
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 8000,
                "output_config": {"effort": "max"},
            },
        )
        self.assertEqual(payload["max_completion_tokens"], 32000)

    def test_openai_responses_thinking_effort_uses_reasoning_and_xhigh(self) -> None:
        payload = build_provider_payload(
            {"api_format": "openai_responses"},
            {
                "model": "gpt-5.4",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 32000,
                "reasoning": {"effort": "xhigh"},
            },
        )
        self.assertEqual(payload["reasoning"], {"effort": "xhigh", "summary": "auto"})
        self.assertEqual(payload["include"], ["reasoning.encrypted_content"])
        self.assertEqual(payload["max_output_tokens"], 32000)

    def test_provider_curl_request_sends_large_payload_via_stdin(self) -> None:
        command, request_body = build_provider_curl_request(
            {
                "api_format": "openai_responses",
                "api_url": "https://example.com/openai/v1",
                "api_key": "test-key",
            },
            {
                "model": "gpt-5.4",
                "messages": [{"role": "user", "content": "x" * 50000}],
                "max_tokens": 32000,
            },
        )
        self.assertIn("--data-binary", command)
        self.assertIn("@-", command)
        self.assertNotIn("--data-raw", command)
        self.assertTrue(any(len(part) > 10000 for part in [request_body.decode("utf-8")]))
        self.assertFalse(any(len(part) > 10000 for part in command))

    def test_provider_stream_surfaces_non_sse_json_error_body(self) -> None:
        stdout_chunks = [
            b'{"error":{"message":"reasoning.effort does not support xhigh"}}\n',
        ]

        class FakeStdout:
            def __init__(self, chunks: list[bytes]) -> None:
                self._chunks = list(chunks)

            async def readline(self) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        class FakeStderr:
            async def read(self) -> bytes:
                return b"curl: (22) The requested URL returned error: 400"

        class FakeStdin:
            def write(self, data: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout(stdout_chunks)
                self.stderr = FakeStderr()
                self.stdin = FakeStdin()
                self.returncode = None

            async def wait(self) -> int:
                self.returncode = 22
                return 22

            def kill(self) -> None:
                self.returncode = 22

        async def run_case() -> str:
            with patch(
                "app.provider_client.asyncio.create_subprocess_exec",
                return_value=FakeProcess(),
            ):
                try:
                    async for _ in stream_provider_events(
                        {
                            "api_format": "openai_responses",
                            "api_url": "https://example.com/openai/v1",
                            "api_key": "test-key",
                        },
                        {
                            "model": "gpt-5.4",
                            "messages": [{"role": "user", "content": "hello"}],
                            "stream": True,
                        },
                    ):
                        pass
                except Exception as exc:  # noqa: BLE001
                    return str(exc)
            return ""

        message = asyncio.run(run_case())
        self.assertIn("供应商调用失败", message)
        self.assertIn("reasoning.effort does not support xhigh", message)

    def test_provider_stream_ignores_sse_event_headers_when_completed(self) -> None:
        stdout_chunks = [
            b"event: response.created\n",
            b'data: {"type":"response.created","response":{"id":"resp_1"}}\n',
            b"event: response.completed\n",
            b'data: {"type":"response.completed","response":{"id":"resp_1"}}\n',
        ]

        class FakeStdout:
            def __init__(self, chunks: list[bytes]) -> None:
                self._chunks = list(chunks)

            async def readline(self) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        class FakeStderr:
            async def read(self) -> bytes:
                return b""

        class FakeStdin:
            def write(self, data: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout(stdout_chunks)
                self.stderr = FakeStderr()
                self.stdin = FakeStdin()
                self.returncode = None

            async def wait(self) -> int:
                self.returncode = 0
                return 0

            def kill(self) -> None:
                self.returncode = 0

        async def run_case() -> list[str]:
            with patch(
                "app.provider_client.asyncio.create_subprocess_exec",
                return_value=FakeProcess(),
            ):
                events: list[str] = []
                async for event in stream_provider_events(
                    {
                        "api_format": "openai_responses",
                        "api_url": "https://example.com/openai/v1",
                        "api_key": "test-key",
                    },
                    {
                        "model": "gpt-5.4",
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": True,
                    },
                ):
                    events.append(event)
                return events

        events = asyncio.run(run_case())
        self.assertEqual(
            events,
            ['data: {"type": "message_stop"}'],
        )

    def test_provider_stream_persists_responses_output_items_for_followup(self) -> None:
        stdout_chunks = [
            b"event: response.output_item.done\n",
            b'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"exa_search","arguments":"{\\"query\\":\\"hello\\"}"}}\n',
            b"event: response.completed\n",
            b'data: {"type":"response.completed","response":{"id":"resp_1","output":[{"type":"function_call","id":"fc_1","call_id":"call_1","name":"exa_search","arguments":"{\\"query\\":\\"hello\\"}"}]}}\n',
        ]

        class FakeStdout:
            def __init__(self, chunks: list[bytes]) -> None:
                self._chunks = list(chunks)

            async def readline(self) -> bytes:
                if self._chunks:
                    return self._chunks.pop(0)
                return b""

        class FakeStderr:
            async def read(self) -> bytes:
                return b""

        class FakeStdin:
            def write(self, data: bytes) -> None:
                return None

            async def drain(self) -> None:
                return None

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout(stdout_chunks)
                self.stderr = FakeStderr()
                self.stdin = FakeStdin()
                self.returncode = None

            async def wait(self) -> int:
                self.returncode = 0
                return 0

            def kill(self) -> None:
                self.returncode = 0

        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }
        runtime_state = ProviderRuntimeState()

        async def run_case() -> None:
            with patch(
                "app.provider_client.asyncio.create_subprocess_exec",
                return_value=FakeProcess(),
            ):
                async for _ in stream_provider_events(
                    {
                        "api_format": "openai_responses",
                        "api_url": "https://example.com/openai/v1",
                        "api_key": "test-key",
                    },
                    payload,
                    runtime_state,
                ):
                    pass

        asyncio.run(run_case())
        self.assertEqual(runtime_state.last_response_id, "resp_1")
        self.assertEqual(
            runtime_state.responses_output_items,
            [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                }
            ],
        )

    def test_openai_chat_tools_are_mapped_to_openai_payload(self) -> None:
        payload = build_provider_payload(
            {"api_format": "openai_chat"},
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [
                    {
                        "name": "exa_search",
                        "description": "Search",
                        "input_schema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    }
                ],
            },
        )
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["tools"][0]["function"]["name"], "exa_search")

    def test_openai_responses_tools_are_mapped_to_responses_payload(self) -> None:
        payload = build_provider_payload(
            {"api_format": "openai_responses"},
            {
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [
                    {
                        "name": "exa_search",
                        "description": "Search",
                        "input_schema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    }
                ],
            },
        )
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(
            payload["tools"][0],
            {
                "type": "function",
                "name": "exa_search",
                "description": "Search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        )

    def test_convert_openai_chat_tool_call_chunk_to_internal_events(self) -> None:
        gateway_events = OpenAIChatAdapter().convert_gateway_event(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_123",
                                    "function": {
                                        "name": "exa_search",
                                        "arguments": '{"query":"hel',
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
            state=GatewayState(),
        )
        self.assertEqual(
            gateway_events,
            [
                {
                    "type": "tool_call_start",
                    "index": 100,
                    "id": "call_123",
                    "name": "exa_search",
                    "input": {},
                },
                {
                    "type": "tool_call_delta",
                    "index": 100,
                    "partial_json": '{"query":"hel',
                },
            ],
        )

        start_and_delta = convert_openai_chunk_to_events(
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_123",
                                    "function": {
                                        "name": "exa_search",
                                        "arguments": '{"query":"hel',
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        )
        self.assertEqual(
            [json.loads(event) for event in start_and_delta],
            [
                {
                    "type": "content_block_start",
                    "index": 100,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "exa_search",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 100,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"query":"hel',
                    },
                },
            ],
        )

    def test_openai_chat_gateway_closes_answer_before_tool_call(self) -> None:
        events_1, text_open, tool_indexes = convert_openai_chat_payload_to_internal_events(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "先回答一段"},
                    }
                ]
            },
            text_block_open=False,
            active_tool_indexes=set(),
        )
        events_2, text_open, tool_indexes = convert_openai_chat_payload_to_internal_events(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "exa_search",
                                        "arguments": '{"query":"hello"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            text_block_open=text_open,
            active_tool_indexes=tool_indexes,
        )
        events_3, _, _ = convert_openai_chat_payload_to_internal_events(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "工具后补充回答"},
                        "finish_reason": "stop",
                    }
                ]
            },
            text_block_open=False,
            active_tool_indexes=set(),
        )

        self.assertEqual(
            [json.loads(event) for event in events_1],
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"text": "先回答一段"},
                },
            ],
        )
        self.assertEqual(
            [json.loads(event) for event in events_2],
            [
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "content_block_start",
                    "index": 100,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "exa_search",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 100,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"query":"hello"}',
                    },
                },
                {"type": "content_block_stop", "index": 100},
            ],
        )
        self.assertEqual(
            [json.loads(event) for event in events_3],
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"text": "工具后补充回答"},
                },
                {"type": "content_block_stop", "index": 0},
                {"type": "message_stop"},
            ],
        )

    def test_openai_chat_tool_followup_messages_use_tool_calls_and_tool_roles(self) -> None:
        request_payload = {"messages": [{"role": "user", "content": "hello"}]}
        append_provider_tool_result_messages(
            {"api_format": "openai_chat"},
            request_payload,
            [
                {
                    "type": "tool_use",
                    "id": "call_123",
                    "name": "exa_search",
                    "input": {"query": "hello"},
                }
            ],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_123",
                    "content": "search result",
                }
            ],
        )
        self.assertEqual(
            request_payload["messages"][-2],
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "exa_search",
                            "arguments": '{"query": "hello"}',
                        },
                    }
                ],
            },
        )
        self.assertEqual(
            request_payload["messages"][-1],
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": "search result",
            },
        )

    def test_openai_responses_tool_followup_replays_output_items_and_function_output(self) -> None:
        runtime_state = ProviderRuntimeState(
            responses_output_items=[
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_123",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                }
            ]
        )
        request_payload = {
            "messages": [{"role": "user", "content": "hello"}],
        }
        append_provider_tool_result_messages(
            {"api_format": "openai_responses"},
            request_payload,
            [
                {
                    "type": "tool_use",
                    "id": "call_123",
                    "name": "exa_search",
                    "input": {"query": "hello"},
                }
            ],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_123",
                    "content": "search result",
                }
            ],
            runtime_state,
        )
        self.assertNotIn("previous_response_id", request_payload)
        self.assertEqual(
            runtime_state.responses_input_history,
            [
                {"role": "user", "content": "hello"},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_123",
                    "name": "exa_search",
                    "arguments": '{"query":"hello"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_123",
                    "output": "search result",
                }
            ],
        )

    def test_openai_responses_tool_followup_preserves_cumulative_input_history(self) -> None:
        runtime_state = ProviderRuntimeState(
            responses_input_history=[
                {"role": "user", "content": "hello"},
                {"type": "function_call", "call_id": "call_1", "name": "exa_search", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_1", "output": "first result"},
            ],
            responses_output_items=[
                {"type": "function_call", "call_id": "call_2", "name": "exa_search", "arguments": "{}"},
            ],
        )
        request_payload = {
            "messages": [{"role": "user", "content": "hello"}],
        }
        append_provider_tool_result_messages(
            {"api_format": "openai_responses"},
            request_payload,
            [{"type": "tool_use", "id": "call_2", "name": "exa_search", "input": {}}],
            [{"type": "tool_result", "tool_use_id": "call_2", "content": "second result"}],
            runtime_state,
        )
        self.assertEqual(
            runtime_state.responses_input_history,
            [
                {"role": "user", "content": "hello"},
                {"type": "function_call", "call_id": "call_1", "name": "exa_search", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_1", "output": "first result"},
                {"type": "function_call", "call_id": "call_2", "name": "exa_search", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "call_2", "output": "second result"},
            ],
        )
        self.assertEqual(runtime_state.responses_output_items, [])

    def test_openai_responses_completed_output_does_not_drop_streamed_items(self) -> None:
        stream_lines = [
            'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"exa_search","arguments":"{}"}}',
            'data: {"type":"response.completed","response":{"id":"resp_1","output":[]}}',
        ]

        async def collect() -> None:
            payload = {"model": "gpt-test", "messages": [{"role": "user", "content": "hello"}]}
            runtime_state = ProviderRuntimeState()

            async def fake_exec(*args, **kwargs):
                class FakeStdout:
                    def __init__(self) -> None:
                        self.lines = [line.encode() for line in stream_lines]

                    async def readline(self):
                        if self.lines:
                            return self.lines.pop(0)
                        return b""

                class FakeStdin:
                    def write(self, data):
                        return None

                    async def drain(self):
                        return None

                    def close(self):
                        return None

                class FakeProcess:
                    stdout = FakeStdout()
                    stderr = FakeStdout()
                    stdin = FakeStdin()
                    returncode = 0

                    async def wait(self):
                        return 0

                    def kill(self):
                        return None

                return FakeProcess()

            with patch("asyncio.create_subprocess_exec", fake_exec):
                lines = [line async for line in stream_provider_events(
                    {"api_format": "openai_responses", "api_url": "https://example.com/v1", "api_key": "key"},
                    payload,
                    runtime_state,
                )]
            self.assertEqual(runtime_state.responses_output_items[0]["call_id"], "call_1")
            self.assertTrue(any("message_stop" in line for line in lines))

        asyncio.run(collect())

    def test_gemini_payload_and_tool_followup(self) -> None:
        payload = {
            "model": "gemini-test",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{"name": "exa_search", "description": "Search", "input_schema": {"type": "object"}}],
        }
        runtime_state = ProviderRuntimeState()
        command, request_body = build_provider_curl_request(
            {
                "api_format": "gemini",
                "api_url": "https://generativelanguage.googleapis.com/v1beta",
                "api_key": "test-key",
                "model_name": "gemini-test",
            },
            payload,
            runtime_state,
        )
        self.assertIn("https://generativelanguage.googleapis.com/v1beta/models/gemini-test:streamGenerateContent?alt=sse", command)
        body = json.loads(request_body.decode("utf-8"))
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "hello"}]}])
        self.assertEqual(body["tools"][0]["functionDeclarations"][0]["name"], "exa_search")

        append_provider_tool_result_messages(
            {"api_format": "gemini"},
            payload,
            [{"type": "tool_use", "id": "call_1", "name": "exa_search", "input": {"query": "hello"}}],
            [{"type": "tool_result", "tool_use_id": "call_1", "content": "result"}],
            runtime_state,
        )
        self.assertEqual(runtime_state.gemini_contents[-2]["role"], "model")
        self.assertEqual(runtime_state.gemini_contents[-1]["parts"][0]["functionResponse"]["response"], {"result": "result"})

    def test_convert_gemini_text_and_tool_call_to_gateway_events(self) -> None:
        events = resolve_adapter("gemini").convert_gateway_event(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "before tool"},
                                {
                                    "functionCall": {
                                        "id": "call_1",
                                        "name": "exa_search",
                                        "args": {"query": "hello"},
                                    }
                                },
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
            state=GatewayState(),
        )

        self.assertEqual(
            events,
            [
                {"type": "text_start", "index": 0},
                {"type": "text_delta", "index": 0, "text": "before tool"},
                {"type": "text_end", "index": 0},
                {
                    "type": "tool_call_start",
                    "index": 100,
                    "id": "call_1",
                    "name": "exa_search",
                    "input": {"query": "hello"},
                },
                {
                    "type": "tool_call_delta",
                    "index": 100,
                    "partial_json": '{"query": "hello"}',
                },
                {"type": "tool_call_end", "index": 100},
                {"type": "turn_end"},
            ],
        )

    def test_tool_calling_capability_helper_only_allows_supported_native_gateways(self) -> None:
        self.assertTrue(
            provider_supports_native_tool_calling(
                {"api_format": "openai_chat", "supports_tool_calling": True}
            )
        )
        self.assertTrue(
            provider_supports_native_tool_calling(
                {"api_format": "anthropic_messages", "supports_tool_calling": True}
            )
        )
        self.assertTrue(
            provider_supports_native_tool_calling(
                {"api_format": "openai_responses", "supports_tool_calling": True}
            )
        )
        self.assertTrue(
            provider_supports_native_tool_calling(
                {"api_format": "gemini", "supports_tool_calling": True}
            )
        )
        self.assertFalse(
            provider_supports_native_tool_calling(
                {"api_format": "openai_chat", "supports_tool_calling": False}
            )
        )

    def test_admin_search_provider_config_roundtrip(self) -> None:
        setup_payload = self.setup_admin()
        admin_token = str(setup_payload["token"])

        initial_response = self.client.get(
            "/api/admin/search-providers",
            headers=self.auth_header(admin_token),
        )
        self.assertEqual(initial_response.status_code, 200)
        self.assertEqual(
            initial_response.json(),
            {
                "exa": {
                    "kind": "exa",
                    "name": "Exa",
                    "is_enabled": True,
                    "is_configured": True,
                    "api_key_masked": "未设置（可选）",
                },
                "tavily": {
                    "kind": "tavily",
                    "name": "Tavily",
                    "is_enabled": False,
                    "is_configured": False,
                    "api_key_masked": "未设置",
                },
            },
        )

        exa_response = self.client.put(
            "/api/admin/search-providers/exa",
            headers=self.auth_header(admin_token),
            json={"api_key": "exa-key", "is_enabled": False},
        )
        self.assertEqual(exa_response.status_code, 200)
        self.assertEqual(exa_response.json()["is_enabled"], False)
        self.assertEqual(exa_response.json()["api_key_masked"], "已配置")

        tavily_response = self.client.put(
            "/api/admin/search-providers/tavily",
            headers=self.auth_header(admin_token),
            json={"api_key": "tavily-key", "is_enabled": True},
        )
        self.assertEqual(tavily_response.status_code, 200)
        self.assertEqual(tavily_response.json()["is_enabled"], True)
        self.assertEqual(tavily_response.json()["is_configured"], True)

        public_response = self.client.get("/api/search-providers")
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(
            public_response.json(),
            {
                "exa": {"is_enabled": False, "is_configured": True},
                "tavily": {"is_enabled": True, "is_configured": True},
            },
        )


if __name__ == "__main__":
    unittest.main()
