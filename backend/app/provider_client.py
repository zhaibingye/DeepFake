from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from urllib.parse import urlparse

from fastapi import HTTPException


ANTHROPIC_VERSION = "2023-06-01"
OPENAI_CHAT_THINKING_BUDGETS = {
    "low": 8000,
    "medium": 16000,
    "high": 32000,
}
DEEPSEEK_THINKING_EFFORTS = {"high", "max"}
SILICONFLOW_THINKING_BUDGETS = {
    "low": 8000,
    "medium": 16000,
    "high": 32000,
}


def _require_valid_base_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="供应商 API URL 不合法")
    return api_url.rstrip("/")


def _internal_text_start(index: int = 0) -> str:
    return json.dumps(
        {
            "type": "content_block_start",
            "index": index,
            "content_block": {"type": "text"},
        },
        ensure_ascii=False,
    )


def _internal_text_delta(text: str, index: int = 0) -> str:
    return json.dumps(
        {
            "type": "content_block_delta",
            "index": index,
            "delta": {"text": text},
        },
        ensure_ascii=False,
    )


def _internal_text_stop(index: int = 0) -> str:
    return json.dumps(
        {"type": "content_block_stop", "index": index},
        ensure_ascii=False,
    )


def _internal_message_stop() -> str:
    return json.dumps({"type": "message_stop"}, ensure_ascii=False)


def _gateway_event_to_legacy_json(event: dict[str, object]) -> str | None:
    event_type = event.get("type")
    index = event.get("index", 0)
    if not isinstance(index, int):
        index = 0
    if event_type == "text_start":
        return _internal_text_start(index)
    if event_type == "text_delta":
        return _internal_text_delta(str(event.get("text", "")), index)
    if event_type == "text_end":
        return _internal_text_stop(index)
    if event_type == "reasoning_start":
        return json.dumps(
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "thinking"},
            },
            ensure_ascii=False,
        )
    if event_type == "reasoning_delta":
        return json.dumps(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"thinking": str(event.get("text", ""))},
            },
            ensure_ascii=False,
        )
    if event_type == "reasoning_end":
        return _internal_text_stop(index)
    if event_type == "tool_call_start":
        tool_input = event.get("input", {})
        return json.dumps(
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": str(event.get("id") or f"tool-{index}"),
                    "name": str(event.get("name") or ""),
                    "input": tool_input if isinstance(tool_input, dict) else {},
                },
            },
            ensure_ascii=False,
        )
    if event_type == "tool_call_delta":
        return json.dumps(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": str(event.get("partial_json", "")),
                },
            },
            ensure_ascii=False,
        )
    if event_type == "tool_call_end":
        return _internal_text_stop(index)
    if event_type == "turn_end":
        return _internal_message_stop()
    if event_type == "usage":
        return json.dumps(
            {"type": "message_delta", "usage": event.get("usage")},
            ensure_ascii=False,
        )
    if event_type in {"error", "response.error"}:
        return json.dumps(event, ensure_ascii=False)
    return None


def _extract_responses_reasoning_summary(item: dict[str, object]) -> str:
    summary = item.get("summary")
    if not isinstance(summary, list):
        return ""
    chunks: list[str] = []
    for part in summary:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text)
            continue
        summary_text = part.get("summary_text")
        if isinstance(summary_text, str) and summary_text.strip():
            chunks.append(summary_text)
    return "".join(chunks).strip()


def _json_clone(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _merge_response_output_items(
    current: list[dict[str, object]],
    incoming: list[object],
) -> list[dict[str, object]]:
    merged = [_json_clone(item) for item in current if isinstance(item, dict)]
    seen: set[str] = set()
    for item in merged:
        key = str(item.get("id") or item.get("call_id") or "")
        if key:
            seen.add(key)
    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or item.get("call_id") or "")
        if key and key in seen:
            continue
        merged.append(_json_clone(item))
        if key:
            seen.add(key)
    return merged


def _to_openai_messages(api_format: str, messages: object) -> list[dict[str, object]]:
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="消息格式不合法")

    openai_messages: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "user"))
        if api_format in {"openai_chat", "deepseek_chat", "siliconflow_chat"}:
            if role == "assistant" and isinstance(message.get("tool_calls"), list):
                assistant_message: dict[str, object] = {
                    "role": "assistant",
                    "content": str(message.get("content", "")),
                    "tool_calls": message.get("tool_calls", []),
                }
                reasoning_content = message.get("reasoning_content")
                if api_format in {"deepseek_chat", "siliconflow_chat"} and isinstance(reasoning_content, str):
                    assistant_message["reasoning_content"] = reasoning_content
                openai_messages.append(assistant_message)
                continue
            if role == "tool":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(message.get("tool_call_id", "")),
                        "content": str(message.get("content", "")),
                    }
                )
                continue

        content = message.get("content", "")
        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue
        if isinstance(content, list):
            blocks: list[dict[str, object]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    blocks.append(
                        {
                            "type": "text",
                            "text": str(block.get("text", "")),
                        }
                    )
                elif block_type == "image":
                    source = block.get("source", {})
                    if not isinstance(source, dict):
                        continue
                    media_type = str(source.get("media_type", "image/png"))
                    image_data = str(source.get("data", ""))
                    blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_data}",
                            },
                        }
                    )
            openai_messages.append({"role": role, "content": blocks})
            continue
        openai_messages.append({"role": role, "content": str(content)})
    return openai_messages


def _to_openai_tools(tools: object) -> list[dict[str, object]]:
    if not isinstance(tools, list) or not tools:
        return []
    openai_tools: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool.get("name", "")),
                    "description": str(tool.get("description", "")),
                    "parameters": tool.get("input_schema", {}),
                },
            }
        )
    return openai_tools


def _to_openai_responses_tools(tools: object) -> list[dict[str, object]]:
    if not isinstance(tools, list) or not tools:
        return []
    openai_tools: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        openai_tools.append(
            {
                "type": "function",
                "name": str(tool.get("name", "")),
                "description": str(tool.get("description", "")),
                "parameters": tool.get("input_schema", {}),
            }
        )
    return openai_tools


def _to_gemini_contents(messages: object) -> list[dict[str, object]]:
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="消息格式不合法")
    contents: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = "model" if message.get("role") == "assistant" else "user"
        content = message.get("content", "")
        parts: list[dict[str, object]] = []
        if isinstance(content, str):
            parts.append({"text": content})
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append({"text": str(block.get("text", ""))})
                elif block.get("type") == "image":
                    source = block.get("source", {})
                    if not isinstance(source, dict):
                        continue
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": str(source.get("media_type", "image/png")),
                                "data": str(source.get("data", "")),
                            }
                        }
                    )
        else:
            parts.append({"text": str(content)})
        if parts:
            contents.append({"role": role, "parts": parts})
    return contents


def _to_gemini_tools(tools: object) -> list[dict[str, object]]:
    if not isinstance(tools, list) or not tools:
        return []
    declarations: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        declarations.append(
            {
                "name": str(tool.get("name", "")),
                "description": str(tool.get("description", "")),
                "parameters": tool.get("input_schema", {}),
            }
        )
    return [{"functionDeclarations": declarations}] if declarations else []


@dataclass(slots=True)
class GatewayState:
    text_block_open: bool = False
    thinking_block_open: bool = False
    saw_reasoning_item: bool = False
    visible_reasoning_text: bool = False
    active_tool_indexes: set[int] | None = None
    response_id: str = ""
    response_function_calls: dict[int, dict[str, str]] | None = None
    response_argument_delta_indexes: set[int] | None = None
    response_output_items: list[dict[str, object]] | None = None
    response_output_item_keys: set[str] | None = None
    active_block_kinds: dict[int, str] | None = None
    deepseek_reasoning_chunks: list[str] | None = None

    def __post_init__(self) -> None:
        if self.active_tool_indexes is None:
            self.active_tool_indexes = set()
        if self.response_function_calls is None:
            self.response_function_calls = {}
        if self.response_argument_delta_indexes is None:
            self.response_argument_delta_indexes = set()
        if self.response_output_items is None:
            self.response_output_items = []
        if self.response_output_item_keys is None:
            self.response_output_item_keys = set()
        if self.active_block_kinds is None:
            self.active_block_kinds = {}
        if self.deepseek_reasoning_chunks is None:
            self.deepseek_reasoning_chunks = []


@dataclass(slots=True)
class ProviderRuntimeState:
    last_response_id: str = ""
    responses_input_history: list[dict[str, object]] | None = None
    responses_output_items: list[dict[str, object]] = field(default_factory=list)
    gemini_contents: list[dict[str, object]] | None = None
    deepseek_reasoning_content: str = ""


class ProviderAdapter:
    api_format: str
    supports_native_tools: bool = False

    def ensure_url(self, api_url: str) -> str:
        raise NotImplementedError

    def build_headers(self, provider) -> list[str]:
        raise NotImplementedError

    def build_payload(self, provider, payload: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError

    def build_payload_with_state(
        self,
        provider,
        payload: dict[str, object],
        runtime_state: ProviderRuntimeState,
    ) -> dict[str, object]:
        return self.build_payload(provider, payload)

    def normalize_thinking_effort(self, effort: str) -> str:
        return effort

    def apply_thinking_config(
        self,
        request_payload: dict[str, object],
        effort: str,
    ) -> None:
        request_payload["thinking"] = {"type": "adaptive"}
        request_payload["output_config"] = {
            "effort": self.normalize_thinking_effort(effort)
        }

    def append_tool_result_messages(
        self,
        request_payload: dict[str, object],
        assistant_tool_uses: list[dict[str, object]],
        tool_results: list[dict[str, object]],
        runtime_state: ProviderRuntimeState,
    ) -> None:
        request_payload["messages"].append(
            {
                "role": "assistant",
                "content": list(assistant_tool_uses),
            }
        )
        request_payload["messages"].append(
            {
                "role": "user",
                "content": tool_results,
            }
        )

    def convert_stream_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[str]:
        return [
            legacy
            for event in self.convert_gateway_event(payload, state=state)
            if (legacy := _gateway_event_to_legacy_json(event)) is not None
        ]

    def convert_gateway_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[dict[str, object]]:
        raise NotImplementedError

    def finalize_stream(self, state: GatewayState) -> list[str]:
        return [
            legacy
            for event in self.finalize_gateway_events(state)
            if (legacy := _gateway_event_to_legacy_json(event)) is not None
        ]

    def finalize_gateway_events(self, state: GatewayState) -> list[dict[str, object]]:
        return []

    def export_stream_state(
        self,
        payload: dict[str, object],
        state: GatewayState,
        runtime_state: ProviderRuntimeState | None = None,
    ) -> None:
        return None


class AnthropicMessagesAdapter(ProviderAdapter):
    api_format = "anthropic_messages"
    supports_native_tools = True

    def ensure_url(self, api_url: str) -> str:
        normalized = _require_valid_base_url(api_url)
        if normalized.endswith("/messages"):
            return normalized
        return f"{normalized}/messages"

    def build_headers(self, provider) -> list[str]:
        return [
            "-H",
            f"x-api-key: {provider['api_key']}",
            "-H",
            f"anthropic-version: {ANTHROPIC_VERSION}",
            "-H",
            "content-type: application/json",
        ]

    def build_payload(self, provider, payload: dict[str, object]) -> dict[str, object]:
        return payload

    def convert_gateway_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[dict[str, object]]:
        event = legacy_stream_data_to_gateway_event(payload, state.active_block_kinds)
        return [event] if event is not None else []


class OpenAIChatAdapter(ProviderAdapter):
    api_format = "openai_chat"
    supports_native_tools = True

    def ensure_url(self, api_url: str) -> str:
        normalized = _require_valid_base_url(api_url)
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    def build_headers(self, provider) -> list[str]:
        return [
            "-H",
            f"Authorization: Bearer {provider['api_key']}",
            "-H",
            "content-type: application/json",
        ]

    def build_payload(self, provider, payload: dict[str, object]) -> dict[str, object]:
        request_payload: dict[str, object] = {
            "model": payload.get("model"),
            "messages": _to_openai_messages(self.api_format, payload.get("messages", [])),
            "stream": True,
        }
        openai_tools = _to_openai_tools(payload.get("tools"))
        if openai_tools:
            request_payload["tools"] = openai_tools
            request_payload["tool_choice"] = "auto"

        output_config = payload.get("output_config", {})
        thinking_effort = ""
        if isinstance(output_config, dict):
            raw_effort = output_config.get("effort")
            if isinstance(raw_effort, str):
                thinking_effort = raw_effort.strip()
        if thinking_effort:
            request_payload["max_completion_tokens"] = OPENAI_CHAT_THINKING_BUDGETS.get(
                thinking_effort,
                OPENAI_CHAT_THINKING_BUDGETS["high"],
            )
        elif "max_tokens" in payload:
            request_payload["max_completion_tokens"] = payload["max_tokens"]
        return request_payload

    def normalize_thinking_effort(self, effort: str) -> str:
        if effort == "max":
            return "high"
        return effort if effort in OPENAI_CHAT_THINKING_BUDGETS else "high"

    def apply_thinking_config(
        self,
        request_payload: dict[str, object],
        effort: str,
    ) -> None:
        request_payload["output_config"] = {
            "effort": self.normalize_thinking_effort(effort)
        }

    def append_tool_result_messages(
        self,
        request_payload: dict[str, object],
        assistant_tool_uses: list[dict[str, object]],
        tool_results: list[dict[str, object]],
        runtime_state: ProviderRuntimeState,
    ) -> None:
        request_payload["messages"].append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": str(tool_use["id"]),
                        "type": "function",
                        "function": {
                            "name": str(tool_use["name"]),
                            "arguments": json.dumps(
                                tool_use.get("input", {}),
                                ensure_ascii=False,
                            ),
                        },
                    }
                    for tool_use in assistant_tool_uses
                ],
            }
        )
        request_payload["messages"].extend(
            {
                "role": "tool",
                "tool_call_id": str(tool_result["tool_use_id"]),
                "content": str(tool_result["content"]),
            }
            for tool_result in tool_results
        )

    def convert_gateway_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[dict[str, object]]:
        output: list[str] = []
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return output
        choice = choices[0]
        if not isinstance(choice, dict):
            return output

        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")
        if isinstance(delta, dict):
            text = delta.get("content")
            tool_calls = delta.get("tool_calls")

            if isinstance(tool_calls, list) and tool_calls and state.text_block_open:
                output.append({"type": "text_end", "index": 0})
                state.text_block_open = False

            if isinstance(text, str) and text:
                if not state.text_block_open:
                    output.append({"type": "text_start", "index": 0})
                    state.text_block_open = True
                output.append({"type": "text_delta", "index": 0, "text": text})

            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    tool_index = tool_call.get("index", 0)
                    if not isinstance(tool_index, int):
                        tool_index = 0
                    internal_index = tool_index + 100
                    tool_id = str(tool_call.get("id") or f"tool-call-{tool_index}")
                    function_payload = tool_call.get("function", {})
                    function_name = ""
                    partial_arguments = ""
                    if isinstance(function_payload, dict):
                        raw_name = function_payload.get("name")
                        if isinstance(raw_name, str):
                            function_name = raw_name
                        raw_arguments = function_payload.get("arguments")
                        if isinstance(raw_arguments, str):
                            partial_arguments = raw_arguments
                    if function_name and internal_index not in state.active_tool_indexes:
                        output.append(
                            {
                                "type": "tool_call_start",
                                "index": internal_index,
                                "id": tool_id,
                                "name": function_name,
                                "input": {},
                            }
                        )
                        state.active_tool_indexes.add(internal_index)
                    if partial_arguments:
                        output.append(
                            {
                                "type": "tool_call_delta",
                                "index": internal_index,
                                "partial_json": partial_arguments,
                            }
                        )

        if finish_reason is not None:
            if finish_reason == "tool_calls":
                for tool_index in sorted(state.active_tool_indexes):
                    output.append({"type": "tool_call_end", "index": tool_index})
                state.active_tool_indexes.clear()
                return output
            if state.text_block_open:
                output.append({"type": "text_end", "index": 0})
                state.text_block_open = False
            output.append({"type": "turn_end"})
        return output

    def finalize_gateway_events(self, state: GatewayState) -> list[dict[str, object]]:
        if state.text_block_open:
            state.text_block_open = False
            return [{"type": "text_end", "index": 0}]
        return []


class DeepSeekChatAdapter(OpenAIChatAdapter):
    api_format = "deepseek_chat"

    def build_payload(self, provider, payload: dict[str, object]) -> dict[str, object]:
        request_payload: dict[str, object] = {
            "model": payload.get("model"),
            "messages": _to_openai_messages(self.api_format, payload.get("messages", [])),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        thinking = payload.get("thinking")
        if isinstance(thinking, dict):
            request_payload["thinking"] = {
                "type": "enabled",
                "reasoning_effort": self.normalize_thinking_effort(
                    str(thinking.get("reasoning_effort") or thinking.get("effort") or "high")
                ),
            }
        else:
            request_payload["thinking"] = {"type": "disabled"}
        openai_tools = _to_openai_tools(payload.get("tools"))
        if openai_tools:
            request_payload["tools"] = openai_tools
            request_payload["tool_choice"] = "auto"
        if "max_tokens" in payload:
            request_payload["max_tokens"] = payload["max_tokens"]
        return request_payload

    def normalize_thinking_effort(self, effort: str) -> str:
        normalized = effort.strip() or "high"
        if normalized in {"low", "medium"}:
            return "high"
        if normalized == "xhigh":
            return "max"
        return normalized if normalized in DEEPSEEK_THINKING_EFFORTS else "high"

    def apply_thinking_config(
        self,
        request_payload: dict[str, object],
        effort: str,
    ) -> None:
        request_payload["thinking"] = {
            "type": "enabled",
            "reasoning_effort": self.normalize_thinking_effort(effort),
        }

    def append_tool_result_messages(
        self,
        request_payload: dict[str, object],
        assistant_tool_uses: list[dict[str, object]],
        tool_results: list[dict[str, object]],
        runtime_state: ProviderRuntimeState,
    ) -> None:
        assistant_message: dict[str, object] = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": str(tool_use["id"]),
                    "type": "function",
                    "function": {
                        "name": str(tool_use["name"]),
                        "arguments": json.dumps(
                            tool_use.get("input", {}),
                            ensure_ascii=False,
                        ),
                    },
                }
                for tool_use in assistant_tool_uses
            ],
        }
        if runtime_state.deepseek_reasoning_content:
            assistant_message["reasoning_content"] = runtime_state.deepseek_reasoning_content
        request_payload["messages"].append(assistant_message)
        request_payload["messages"].extend(
            {
                "role": "tool",
                "tool_call_id": str(tool_result["tool_use_id"]),
                "content": str(tool_result["content"]),
            }
            for tool_result in tool_results
        )
        runtime_state.deepseek_reasoning_content = ""

    def convert_gateway_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        usage = payload.get("usage")
        if isinstance(usage, dict):
            output.append({"type": "usage", "usage": usage})

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return output
        choice = choices[0]
        if not isinstance(choice, dict):
            return output

        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")
        if isinstance(delta, dict):
            reasoning = delta.get("reasoning_content")
            text = delta.get("content")
            tool_calls = delta.get("tool_calls")

            if isinstance(reasoning, str) and reasoning:
                if state.deepseek_reasoning_chunks is not None:
                    state.deepseek_reasoning_chunks.append(reasoning)
                if not state.thinking_block_open:
                    output.append({"type": "reasoning_start", "index": 1})
                    state.thinking_block_open = True
                output.append({"type": "reasoning_delta", "index": 1, "text": reasoning})

            if isinstance(text, str) and text:
                if state.thinking_block_open:
                    output.append({"type": "reasoning_end", "index": 1})
                    state.thinking_block_open = False
                if not state.text_block_open:
                    output.append({"type": "text_start", "index": 0})
                    state.text_block_open = True
                output.append({"type": "text_delta", "index": 0, "text": text})

            if isinstance(tool_calls, list) and tool_calls:
                if state.thinking_block_open:
                    output.append({"type": "reasoning_end", "index": 1})
                    state.thinking_block_open = False
                if state.text_block_open:
                    output.append({"type": "text_end", "index": 0})
                    state.text_block_open = False
                output.extend(self._convert_deepseek_tool_call_deltas(tool_calls, state))

        if finish_reason is not None:
            if finish_reason == "tool_calls":
                for tool_index in sorted(state.active_tool_indexes):
                    output.append({"type": "tool_call_end", "index": tool_index})
                state.active_tool_indexes.clear()
                return output
            if state.thinking_block_open:
                output.append({"type": "reasoning_end", "index": 1})
                state.thinking_block_open = False
            if state.text_block_open:
                output.append({"type": "text_end", "index": 0})
                state.text_block_open = False
            output.append({"type": "turn_end"})
        return output

    def _convert_deepseek_tool_call_deltas(
        self,
        tool_calls: list[object],
        state: GatewayState,
    ) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_index = tool_call.get("index", 0)
            if not isinstance(tool_index, int):
                tool_index = 0
            internal_index = tool_index + 100
            tool_id = str(tool_call.get("id") or f"tool-call-{tool_index}")
            function_payload = tool_call.get("function", {})
            function_name = ""
            partial_arguments = ""
            if isinstance(function_payload, dict):
                raw_name = function_payload.get("name")
                if isinstance(raw_name, str):
                    function_name = raw_name
                raw_arguments = function_payload.get("arguments")
                if isinstance(raw_arguments, str):
                    partial_arguments = raw_arguments
            if function_name and internal_index not in state.active_tool_indexes:
                output.append(
                    {
                        "type": "tool_call_start",
                        "index": internal_index,
                        "id": tool_id,
                        "name": function_name,
                        "input": {},
                    }
                )
                state.active_tool_indexes.add(internal_index)
            if partial_arguments:
                output.append(
                    {
                        "type": "tool_call_delta",
                        "index": internal_index,
                        "partial_json": partial_arguments,
                    }
                )
        return output

    def finalize_gateway_events(self, state: GatewayState) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        if state.thinking_block_open:
            output.append({"type": "reasoning_end", "index": 1})
            state.thinking_block_open = False
        if state.text_block_open:
            output.append({"type": "text_end", "index": 0})
            state.text_block_open = False
        return output

    def export_stream_state(
        self,
        payload: dict[str, object],
        state: GatewayState,
        runtime_state: ProviderRuntimeState | None = None,
    ) -> None:
        if runtime_state is not None and state.deepseek_reasoning_chunks is not None:
            runtime_state.deepseek_reasoning_content = "".join(
                state.deepseek_reasoning_chunks
            )


class SiliconFlowChatAdapter(DeepSeekChatAdapter):
    api_format = "siliconflow_chat"

    def build_payload(self, provider, payload: dict[str, object]) -> dict[str, object]:
        request_payload: dict[str, object] = {
            "model": payload.get("model"),
            "messages": _to_openai_messages(self.api_format, payload.get("messages", [])),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if payload.get("enable_thinking") is True:
            raw_budget = payload.get("thinking_budget")
            budget = raw_budget if isinstance(raw_budget, int) else SILICONFLOW_THINKING_BUDGETS["high"]
            request_payload["enable_thinking"] = True
            request_payload["thinking_budget"] = min(32768, max(128, budget))
        else:
            request_payload["enable_thinking"] = False

        openai_tools = _to_openai_tools(payload.get("tools"))
        if openai_tools:
            request_payload["tools"] = openai_tools
            request_payload["tool_choice"] = "auto"
        if "max_tokens" in payload:
            request_payload["max_tokens"] = payload["max_tokens"]
        return request_payload

    def normalize_thinking_effort(self, effort: str) -> str:
        normalized = effort.strip() or "high"
        return normalized if normalized in SILICONFLOW_THINKING_BUDGETS else "high"

    def apply_thinking_config(
        self,
        request_payload: dict[str, object],
        effort: str,
    ) -> None:
        request_payload["enable_thinking"] = True
        request_payload["thinking_budget"] = SILICONFLOW_THINKING_BUDGETS[
            self.normalize_thinking_effort(effort)
        ]


class OpenAIResponsesAdapter(ProviderAdapter):
    api_format = "openai_responses"
    supports_native_tools = True

    def ensure_url(self, api_url: str) -> str:
        normalized = _require_valid_base_url(api_url)
        if normalized.endswith("/responses"):
            return normalized
        return f"{normalized}/responses"

    def build_headers(self, provider) -> list[str]:
        return [
            "-H",
            f"Authorization: Bearer {provider['api_key']}",
            "-H",
            "content-type: application/json",
        ]

    def build_payload_with_state(
        self,
        provider,
        payload: dict[str, object],
        runtime_state: ProviderRuntimeState,
    ) -> dict[str, object]:
        input_history = runtime_state.responses_input_history
        if input_history is None:
            input_history = _to_openai_messages(self.api_format, payload.get("messages", []))
            runtime_state.responses_input_history = _json_clone(input_history)
        request_payload: dict[str, object] = {
            "model": payload.get("model"),
            "input": _json_clone(input_history),
            "stream": True,
        }
        reasoning = payload.get("reasoning")
        if isinstance(reasoning, dict):
            request_payload["reasoning"] = {
                **reasoning,
                "summary": reasoning.get("summary") or "auto",
            }
            request_payload["include"] = ["reasoning.encrypted_content"]
        openai_tools = _to_openai_responses_tools(payload.get("tools"))
        if openai_tools:
            request_payload["tools"] = openai_tools
            request_payload["tool_choice"] = "auto"
        if "max_tokens" in payload:
            request_payload["max_output_tokens"] = payload["max_tokens"]
        return request_payload

    def normalize_thinking_effort(self, effort: str) -> str:
        normalized = effort.strip() or "high"
        if normalized == "max":
            return "xhigh"
        if normalized not in {"low", "medium", "high", "xhigh"}:
            return "high"
        return normalized

    def apply_thinking_config(
        self,
        request_payload: dict[str, object],
        effort: str,
    ) -> None:
        request_payload["reasoning"] = {
            "effort": self.normalize_thinking_effort(effort),
            "summary": "auto",
        }

    def append_tool_result_messages(
        self,
        request_payload: dict[str, object],
        assistant_tool_uses: list[dict[str, object]],
        tool_results: list[dict[str, object]],
        runtime_state: ProviderRuntimeState,
    ) -> None:
        prior_output_items = runtime_state.responses_output_items
        input_history = runtime_state.responses_input_history
        if input_history is None:
            prior_messages = request_payload.get("messages")
            if isinstance(prior_messages, list):
                input_history = _to_openai_messages(self.api_format, prior_messages)
            else:
                input_history = []
        if not prior_output_items:
            raise HTTPException(
                status_code=502,
                detail="OpenAI Responses 工具调用缺少上一轮输出上下文",
            )
        function_outputs = [
            {
                "type": "function_call_output",
                "call_id": str(tool_result["tool_use_id"]),
                "output": str(tool_result["content"]),
            }
            for tool_result in tool_results
        ]
        next_input = [
            *_json_clone(input_history),
            *_json_clone(prior_output_items),
            *function_outputs,
        ]
        runtime_state.responses_input_history = next_input
        runtime_state.responses_output_items = []
        request_payload.pop("previous_response_id", None)

    def export_stream_state(
        self,
        payload: dict[str, object],
        state: GatewayState,
        runtime_state: ProviderRuntimeState | None = None,
    ) -> None:
        runtime_state = runtime_state or ProviderRuntimeState()
        if state.response_id:
            runtime_state.last_response_id = state.response_id
        if state.response_output_items:
            runtime_state.responses_output_items = _json_clone(
                state.response_output_items
            )

    def convert_gateway_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[dict[str, object]]:
        event_type = payload.get("type")
        output: list[dict[str, object]] = []
        if event_type == "response.created":
            response = payload.get("response")
            if isinstance(response, dict):
                response_id = response.get("id")
                if isinstance(response_id, str):
                    state.response_id = response_id
        if event_type == "response.output_item.added":
            item = payload.get("item")
            output_index = payload.get("output_index", 0)
            if not isinstance(output_index, int):
                output_index = 0
            if (
                isinstance(item, dict)
                and item.get("type") == "function_call"
            ):
                if state.thinking_block_open:
                    output.append({"type": "reasoning_end", "index": 1})
                    state.thinking_block_open = False
                if state.text_block_open:
                    output.append({"type": "text_end", "index": 0})
                    state.text_block_open = False
                internal_index = output_index + 100
                call_id = str(item.get("call_id") or item.get("id") or f"call-{output_index}")
                name = str(item.get("name") or "")
                state.response_function_calls[internal_index] = {
                    "id": call_id,
                    "name": name,
                }
                if internal_index not in state.active_tool_indexes and name:
                    output.append(
                        {
                            "type": "tool_call_start",
                            "index": internal_index,
                            "id": call_id,
                            "name": name,
                            "input": {},
                        }
                    )
                    state.active_tool_indexes.add(internal_index)
        if event_type in {
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        }:
            delta = payload.get("delta")
            if isinstance(delta, str) and delta:
                state.visible_reasoning_text = True
                if not state.thinking_block_open:
                    output.append({"type": "reasoning_start", "index": 1})
                    state.thinking_block_open = True
                output.append({"type": "reasoning_delta", "index": 1, "text": delta})
        if event_type == "response.output_text.delta":
            delta = payload.get("delta")
            if isinstance(delta, str) and delta:
                if state.saw_reasoning_item and not state.visible_reasoning_text:
                    output.append({"type": "reasoning_start", "index": 1})
                    output.append(
                        {
                            "type": "reasoning_delta",
                            "index": 1,
                            "text": "模型已完成思考，但当前供应商未返回可展示的思维文本。",
                        }
                    )
                    output.append({"type": "reasoning_end", "index": 1})
                    state.saw_reasoning_item = False
                    state.visible_reasoning_text = True
                if state.thinking_block_open:
                    output.append({"type": "reasoning_end", "index": 1})
                    state.thinking_block_open = False
                if not state.text_block_open:
                    output.append({"type": "text_start", "index": 0})
                    state.text_block_open = True
                output.append({"type": "text_delta", "index": 0, "text": delta})
        if event_type in {
            "response.reasoning_summary_text.done",
            "response.reasoning_text.done",
        }:
            text = payload.get("text")
            if isinstance(text, str) and text and not state.thinking_block_open:
                state.visible_reasoning_text = True
                output.append({"type": "reasoning_start", "index": 1})
                state.thinking_block_open = True
                output.append({"type": "reasoning_delta", "index": 1, "text": text})
        if event_type == "response.function_call_arguments.delta":
            partial_json = payload.get("delta")
            output_index = payload.get("output_index", 0)
            if not isinstance(output_index, int):
                output_index = 0
            internal_index = output_index + 100
            if isinstance(partial_json, str) and partial_json:
                state.response_argument_delta_indexes.add(internal_index)
                output.append(
                    {
                        "type": "tool_call_delta",
                        "index": internal_index,
                        "partial_json": partial_json,
                    }
                )
        if event_type == "response.output_item.done":
            item = payload.get("item")
            output_index = payload.get("output_index", 0)
            if not isinstance(output_index, int):
                output_index = 0
            internal_index = output_index + 100
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("call_id") or "")
                if not key or key not in state.response_output_item_keys:
                    state.response_output_items.append(_json_clone(item))
                    if key:
                        state.response_output_item_keys.add(key)
            if isinstance(item, dict) and item.get("type") == "reasoning":
                state.saw_reasoning_item = True
                summary_text = _extract_responses_reasoning_summary(item)
                if summary_text:
                    state.visible_reasoning_text = True
                    if not state.thinking_block_open:
                        output.append({"type": "reasoning_start", "index": 1})
                        state.thinking_block_open = True
                    output.append({"type": "reasoning_delta", "index": 1, "text": summary_text})
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, list) and not state.text_block_open:
                    output_text = "".join(
                        str(block.get("text", ""))
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "output_text"
                    )
                    if output_text:
                        if state.thinking_block_open:
                            output.append({"type": "reasoning_end", "index": 1})
                            state.thinking_block_open = False
                        output.append({"type": "text_start", "index": 0})
                        output.append({"type": "text_delta", "index": 0, "text": output_text})
                        output.append({"type": "text_end", "index": 0})
            if isinstance(item, dict) and item.get("type") == "function_call":
                call_id = str(item.get("call_id") or item.get("id") or f"call-{output_index}")
                name = str(item.get("name") or "")
                if internal_index not in state.active_tool_indexes and name:
                    output.append(
                        {
                            "type": "tool_call_start",
                            "index": internal_index,
                            "id": call_id,
                            "name": name,
                            "input": {},
                        }
                    )
                    state.active_tool_indexes.add(internal_index)
                arguments = item.get("arguments")
                if (
                    isinstance(arguments, str)
                    and arguments
                    and internal_index not in state.response_argument_delta_indexes
                ):
                    output.append(
                        {
                            "type": "tool_call_delta",
                            "index": internal_index,
                            "partial_json": arguments,
                        }
                    )
                if internal_index in state.active_tool_indexes:
                    output.append({"type": "tool_call_end", "index": internal_index})
                    state.active_tool_indexes.remove(internal_index)
                state.response_argument_delta_indexes.discard(internal_index)
        if event_type in {"response.completed", "response.incomplete"}:
            response = payload.get("response")
            if isinstance(response, dict):
                response_id = response.get("id")
                if isinstance(response_id, str):
                    state.response_id = response_id
                output_items = response.get("output")
                if isinstance(output_items, list) and output_items:
                    state.response_output_items = _merge_response_output_items(
                        state.response_output_items,
                        output_items,
                    )
                    state.response_output_item_keys = {
                        str(item.get("id") or item.get("call_id") or "")
                        for item in state.response_output_items
                        if isinstance(item, dict)
                        and str(item.get("id") or item.get("call_id") or "")
                    }
            if state.thinking_block_open:
                output.append({"type": "reasoning_end", "index": 1})
                state.thinking_block_open = False
            if state.text_block_open:
                output.append({"type": "text_end", "index": 0})
                state.text_block_open = False
            output.append({"type": "turn_end"})
        return output

    def finalize_gateway_events(self, state: GatewayState) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        if state.thinking_block_open:
            output.append({"type": "reasoning_end", "index": 1})
            state.thinking_block_open = False
        if state.text_block_open:
            output.append({"type": "text_end", "index": 0})
            state.text_block_open = False
        for tool_index in sorted(state.active_tool_indexes):
            output.append({"type": "tool_call_end", "index": tool_index})
        state.active_tool_indexes.clear()
        return output


class GeminiAdapter(ProviderAdapter):
    api_format = "gemini"
    supports_native_tools = True

    def ensure_url(self, api_url: str) -> str:
        normalized = _require_valid_base_url(api_url)
        if ":streamGenerateContent" in normalized:
            return normalized if "alt=sse" in normalized else f"{normalized}?alt=sse"
        return normalized

    def build_headers(self, provider) -> list[str]:
        return [
            "-H",
            f"x-goog-api-key: {provider['api_key']}",
            "-H",
            "content-type: application/json",
        ]

    def build_payload_with_state(
        self,
        provider,
        payload: dict[str, object],
        runtime_state: ProviderRuntimeState,
    ) -> dict[str, object]:
        contents = runtime_state.gemini_contents
        if contents is None:
            contents = _to_gemini_contents(payload.get("messages", []))
            runtime_state.gemini_contents = _json_clone(contents)
        request_payload: dict[str, object] = {
            "contents": _json_clone(contents),
        }
        max_tokens = payload.get("max_tokens")
        generation_config: dict[str, object] = {}
        if isinstance(max_tokens, int):
            generation_config["maxOutputTokens"] = max_tokens
        thinking = payload.get("thinking")
        if isinstance(thinking, dict):
            generation_config["thinkingConfig"] = thinking
        if generation_config:
            request_payload["generationConfig"] = generation_config
        gemini_tools = _to_gemini_tools(payload.get("tools"))
        if gemini_tools:
            request_payload["tools"] = gemini_tools
        return request_payload

    def apply_thinking_config(
        self,
        request_payload: dict[str, object],
        effort: str,
    ) -> None:
        budgets = {"low": 1024, "medium": 4096, "high": 8192, "max": -1}
        request_payload["thinking"] = {
            "thinkingBudget": budgets.get(self.normalize_thinking_effort(effort), 8192)
        }

    def append_tool_result_messages(
        self,
        request_payload: dict[str, object],
        assistant_tool_uses: list[dict[str, object]],
        tool_results: list[dict[str, object]],
        runtime_state: ProviderRuntimeState,
    ) -> None:
        contents = runtime_state.gemini_contents
        if contents is None:
            contents = _to_gemini_contents(request_payload.get("messages", []))
        model_parts = []
        for tool_use in assistant_tool_uses:
            model_parts.append(
                {
                    "functionCall": {
                        "name": str(tool_use.get("name", "")),
                        "args": tool_use.get("input", {}),
                    }
                }
            )
        response_parts = []
        tool_by_id = {
            str(tool_use.get("id", "")): str(tool_use.get("name", ""))
            for tool_use in assistant_tool_uses
        }
        for tool_result in tool_results:
            tool_use_id = str(tool_result.get("tool_use_id", ""))
            response_parts.append(
                {
                    "functionResponse": {
                        "name": tool_by_id.get(tool_use_id, tool_use_id),
                        "response": {"result": str(tool_result.get("content", ""))},
                    }
                }
            )
        if model_parts:
            contents.append({"role": "model", "parts": model_parts})
        if response_parts:
            contents.append({"role": "user", "parts": response_parts})
        runtime_state.gemini_contents = _json_clone(contents)

    def convert_gateway_event(
        self,
        payload: dict[str, object],
        *,
        state: GatewayState,
    ) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return output
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return output
        content = candidate.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    if not state.text_block_open:
                        output.append({"type": "text_start", "index": 0})
                        state.text_block_open = True
                    output.append({"type": "text_delta", "index": 0, "text": text})
                function_call = part.get("functionCall")
                if isinstance(function_call, dict):
                    if state.text_block_open:
                        output.append({"type": "text_end", "index": 0})
                        state.text_block_open = False
                    tool_index = len(state.active_tool_indexes or set()) + 100
                    name = str(function_call.get("name", ""))
                    call_id = str(function_call.get("id") or f"gemini-call-{tool_index}")
                    args = function_call.get("args", {})
                    output.append(
                        {
                            "type": "tool_call_start",
                            "index": tool_index,
                            "id": call_id,
                            "name": name,
                            "input": args if isinstance(args, dict) else {},
                        }
                    )
                    if isinstance(args, dict) and args:
                        output.append(
                            {
                                "type": "tool_call_delta",
                                "index": tool_index,
                                "partial_json": json.dumps(args, ensure_ascii=False),
                            }
                        )
                    output.append({"type": "tool_call_end", "index": tool_index})
        finish_reason = candidate.get("finishReason")
        if finish_reason and finish_reason != "STOP":
            if state.text_block_open:
                output.append({"type": "text_end", "index": 0})
                state.text_block_open = False
        if finish_reason == "STOP":
            if state.text_block_open:
                output.append({"type": "text_end", "index": 0})
                state.text_block_open = False
            output.append({"type": "turn_end"})
        return output

    def finalize_gateway_events(self, state: GatewayState) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        if state.text_block_open:
            output.append({"type": "text_end", "index": 0})
            state.text_block_open = False
        output.append({"type": "turn_end"})
        return output


ADAPTERS: dict[str, ProviderAdapter] = {
    "anthropic_messages": AnthropicMessagesAdapter(),
    "openai_chat": OpenAIChatAdapter(),
    "deepseek_chat": DeepSeekChatAdapter(),
    "siliconflow_chat": SiliconFlowChatAdapter(),
    "openai_responses": OpenAIResponsesAdapter(),
    "gemini": GeminiAdapter(),
}


def resolve_adapter(api_format: str) -> ProviderAdapter:
    try:
        return ADAPTERS[api_format]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="未知供应商接口格式") from exc


def ensure_provider_url(api_url: str, api_format: str) -> str:
    return resolve_adapter(api_format).ensure_url(api_url)


def build_provider_payload(provider, payload: dict[str, object]) -> dict[str, object]:
    return resolve_adapter(provider["api_format"]).build_payload_with_state(
        provider,
        payload,
        ProviderRuntimeState(),
    )


def build_provider_headers(provider) -> list[str]:
    return resolve_adapter(provider["api_format"]).build_headers(provider)


def normalize_provider_thinking_effort(provider, effort: str) -> str:
    return resolve_adapter(provider["api_format"]).normalize_thinking_effort(effort)


def apply_provider_thinking_config(
    provider,
    request_payload: dict[str, object],
    effort: str,
) -> None:
    resolve_adapter(provider["api_format"]).apply_thinking_config(
        request_payload,
        effort,
    )


def append_provider_tool_result_messages(
    provider,
    request_payload: dict[str, object],
    assistant_tool_uses: list[dict[str, object]],
    tool_results: list[dict[str, object]],
    runtime_state: ProviderRuntimeState | None = None,
) -> None:
    state = runtime_state or ProviderRuntimeState()
    resolve_adapter(provider["api_format"]).append_tool_result_messages(
        request_payload,
        assistant_tool_uses,
        tool_results,
        state,
    )


def provider_supports_native_tool_calling(provider) -> bool:
    return bool(provider["supports_tool_calling"]) and resolve_adapter(
        provider["api_format"]
    ).supports_native_tools


def convert_openai_chunk_to_events(payload: dict[str, object]):
    return OpenAIChatAdapter().convert_stream_event(payload, state=GatewayState())


def convert_openai_chat_payload_to_internal_events(
    payload: dict[str, object],
    *,
    text_block_open: bool,
    active_tool_indexes: set[int],
    text_index: int = 0,
) -> tuple[list[str], bool, set[int]]:
    if text_index != 0:
        raise HTTPException(status_code=400, detail="当前仅支持默认文本块索引")
    state = GatewayState(
        text_block_open=text_block_open,
        active_tool_indexes=set(active_tool_indexes),
    )
    events = OpenAIChatAdapter().convert_stream_event(payload, state=state)
    return events, state.text_block_open, state.active_tool_indexes


def convert_openai_response_event_to_events(payload: dict[str, object]):
    return OpenAIResponsesAdapter().convert_stream_event(
        payload,
        state=GatewayState(),
    )


def build_provider_curl_request(
    provider,
    payload: dict[str, object],
    runtime_state: ProviderRuntimeState | None = None,
) -> tuple[list[str], bytes]:
    adapter = resolve_adapter(provider["api_format"])
    url = adapter.ensure_url(provider["api_url"])
    if provider["api_format"] == "gemini" and ":streamGenerateContent" not in url:
        model = str(payload.get("model") or provider["model_name"])
        url = f"{url}/models/{model}:streamGenerateContent?alt=sse"
    state = runtime_state or ProviderRuntimeState()
    request_payload = adapter.build_payload_with_state(provider, payload, state)
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--no-buffer",
        "-X",
        "POST",
        url,
        *adapter.build_headers(provider),
        "--data-binary",
        "@-",
    ]
    return command, request_body


def _extract_provider_error_detail(lines: list[str], fallback: str) -> str:
    body = "\n".join(line for line in lines if line.strip()).strip()
    if not body:
        return fallback
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:1000]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail")
            if message:
                return str(message)
            return json.dumps(error, ensure_ascii=False)
        if isinstance(error, str):
            return error
        detail = payload.get("detail")
        if detail:
            return str(detail)
    return body[:1000]


async def stream_provider_events(
    provider,
    payload: dict[str, object],
    runtime_state: ProviderRuntimeState | None = None,
):
    # Legacy NDJSON stream for callers that still consume Anthropic-style
    # content_block events. New chat orchestration should use stream_gateway_events.
    adapter = resolve_adapter(provider["api_format"])
    runtime_state = runtime_state or ProviderRuntimeState()
    command, request_body = build_provider_curl_request(provider, payload, runtime_state)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    assert process.stdin is not None
    process.stdin.write(request_body)
    await process.stdin.drain()
    process.stdin.close()
    gateway_state = GatewayState()
    passthrough_lines: list[str] = []
    emitted_terminal_event = False

    try:
        while True:
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if provider["api_format"] == "anthropic_messages":
                emitted_terminal_event = emitted_terminal_event or line == "data: [DONE]"
                yield line
                continue
            if line.startswith("event:"):
                if line in {"event: response.completed", "event: response.incomplete"}:
                    emitted_terminal_event = True
                continue
            if not line.startswith("data:"):
                passthrough_lines.append(line)
                continue
            data = line.removeprefix("data:").strip()
            if not data or data == "[DONE]":
                for event in adapter.finalize_stream(gateway_state):
                    yield f"data: {event}"
                yield "data: [DONE]"
                emitted_terminal_event = True
                continue
            try:
                payload_obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            converted_events = adapter.convert_stream_event(payload_obj, state=gateway_state)
            for event in converted_events:
                try:
                    emitted_terminal_event = (
                        emitted_terminal_event
                        or json.loads(event).get("type") == "message_stop"
                    )
                except json.JSONDecodeError:
                    pass
                yield f"data: {event}"
            if payload_obj.get("type") in {"response.completed", "response.incomplete"}:
                emitted_terminal_event = True
            adapter.export_stream_state(payload, gateway_state, runtime_state)
        adapter.export_stream_state(payload, gateway_state, runtime_state)
        return_code = await process.wait()
        if return_code != 0:
            detail = (await process.stderr.read()).decode("utf-8", errors="ignore")
            detail = _extract_provider_error_detail(passthrough_lines, detail)
            raise HTTPException(status_code=502, detail=f"供应商调用失败: {detail}")
        if not emitted_terminal_event:
            detail = _extract_provider_error_detail(
                passthrough_lines,
                "供应商未返回有效的流式响应",
            )
            raise HTTPException(status_code=502, detail=f"供应商调用失败: {detail}")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def legacy_stream_data_to_gateway_event(
    data: dict[str, object],
    active_kinds: dict[int, str],
) -> dict[str, object] | None:
    event_type = data.get("type")
    if event_type == "content_block_start":
        index = data.get("index", 0)
        if not isinstance(index, int):
            index = 0
        content_block = data.get("content_block")
        if not isinstance(content_block, dict):
            return None
        block_type = content_block.get("type")
        if block_type == "text":
            active_kinds[index] = "text"
            return {"type": "text_start", "index": index}
        if block_type == "thinking":
            active_kinds[index] = "reasoning"
            return {"type": "reasoning_start", "index": index}
        if block_type == "tool_use":
            active_kinds[index] = "tool_call"
            tool_input = content_block.get("input", {})
            return {
                "type": "tool_call_start",
                "index": index,
                "id": str(content_block.get("id") or f"tool-{index}"),
                "name": str(content_block.get("name") or ""),
                "input": tool_input if isinstance(tool_input, dict) else {},
            }
        return None
    if event_type == "content_block_delta":
        index = data.get("index", 0)
        if not isinstance(index, int):
            index = 0
        delta = data.get("delta", {})
        if not isinstance(delta, dict):
            return None
        if delta.get("type") == "input_json_delta":
            return {
                "type": "tool_call_delta",
                "index": index,
                "partial_json": str(delta.get("partial_json", "")),
            }
        text = delta.get("text")
        if isinstance(text, str) and text:
            return {"type": "text_delta", "index": index, "text": text}
        reasoning = delta.get("thinking")
        if isinstance(reasoning, str) and reasoning:
            return {"type": "reasoning_delta", "index": index, "text": reasoning}
        return None
    if event_type == "content_block_stop":
        index = data.get("index", 0)
        if not isinstance(index, int):
            index = 0
        kind = active_kinds.pop(index, "")
        if kind == "text":
            return {"type": "text_end", "index": index}
        if kind == "reasoning":
            return {"type": "reasoning_end", "index": index}
        if kind == "tool_call":
            return {"type": "tool_call_end", "index": index}
        return {"type": "part_end", "index": index}
    if event_type in {"message_stop", "response.completed"}:
        return {"type": "turn_end"}
    if event_type == "message_delta":
        usage = data.get("usage")
        if usage:
            return {"type": "usage", "usage": usage}
    if event_type in {"error", "response.error"}:
        return data
    return None


async def stream_gateway_events(
    provider,
    payload: dict[str, object],
    runtime_state: ProviderRuntimeState | None = None,
):
    adapter = resolve_adapter(provider["api_format"])
    runtime_state = runtime_state or ProviderRuntimeState()
    command, request_body = build_provider_curl_request(provider, payload, runtime_state)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    assert process.stdin is not None
    process.stdin.write(request_body)
    await process.stdin.drain()
    process.stdin.close()
    gateway_state = GatewayState()
    passthrough_lines: list[str] = []
    emitted_terminal_event = False

    try:
        while True:
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if line.startswith("event:"):
                continue
            if not line.startswith("data:"):
                passthrough_lines.append(line)
                continue
            data = line.removeprefix("data:").strip()
            if not data:
                continue
            if data == "[DONE]":
                for event in adapter.finalize_gateway_events(gateway_state):
                    yield event
                    emitted_terminal_event = emitted_terminal_event or event.get("type") == "turn_end"
                yield {"type": "stream_done"}
                emitted_terminal_event = True
                continue
            try:
                payload_obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            for event in adapter.convert_gateway_event(payload_obj, state=gateway_state):
                yield event
                emitted_terminal_event = emitted_terminal_event or event.get("type") == "turn_end"
            if payload_obj.get("type") in {"response.completed", "response.incomplete"}:
                emitted_terminal_event = True
            adapter.export_stream_state(payload, gateway_state, runtime_state)
        adapter.export_stream_state(payload, gateway_state, runtime_state)
        return_code = await process.wait()
        if return_code != 0:
            detail = (await process.stderr.read()).decode("utf-8", errors="ignore")
            detail = _extract_provider_error_detail(passthrough_lines, detail)
            raise HTTPException(status_code=502, detail=f"供应商调用失败: {detail}")
        if not emitted_terminal_event:
            detail = _extract_provider_error_detail(
                passthrough_lines,
                "供应商未返回有效的流式响应",
            )
            raise HTTPException(status_code=502, detail=f"供应商调用失败: {detail}")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
