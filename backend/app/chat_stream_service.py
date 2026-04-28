from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app import timeline, tool_runtime
from app.chat_service import (
    SearchProviderUnavailableError,
    commit_stream_chat,
    prepare_stream_chat,
    rollback_stream_chat,
)
from app.provider_client import (
    append_provider_tool_result_messages,
    legacy_stream_data_to_gateway_event,
    stream_gateway_events as stream_provider_gateway_events,
    stream_provider_events,
)
from app.settings_service import get_exa_config, get_tavily_config


async def stream_gateway_events(provider, payload, runtime_state=None):
    if stream_provider_events is _ORIGINAL_STREAM_PROVIDER_EVENTS:
        async for event in stream_provider_gateway_events(provider, payload, runtime_state):
            yield event
        return
    active_kinds: dict[int, str] = {}
    async for line in stream_provider_events(provider, payload, runtime_state):
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if raw == "[DONE]":
            yield {"type": "stream_done"}
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        event = legacy_stream_data_to_gateway_event(data, active_kinds)
        if event is not None:
            yield event


_ORIGINAL_STREAM_PROVIDER_EVENTS = stream_provider_events

def create_chat_stream_response(payload: Any, user: dict[str, Any]) -> StreamingResponse:
    try:
        context = prepare_stream_chat(payload, user)
    except SearchProviderUnavailableError as exc:
        detail = exc.detail

        async def unavailable_event_generator():
            yield (
                json.dumps({"type": "error", "detail": detail}, ensure_ascii=False)
                + "\n"
            )

        return StreamingResponse(
            unavailable_event_generator(),
            media_type="application/x-ndjson",
        )

    async def event_generator():
        completed = False
        committed = False
        active_parts: dict[int, dict[str, Any]] = {}
        part_positions: dict[int, int] = {}
        assistant_parts: list[dict[str, Any]] = []
        pending_assistant_tool_uses: list[dict[str, Any]] = []
        pending_tool_results: list[tuple[str, dict[str, str]]] = []
        pending_tool_use_inputs: dict[int, dict[str, Any]] = {}
        thinking_count = 0
        answer_count = 0
        fallback_index = 0

        def emit(event: dict[str, Any]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        def remember_part(index: int, part: dict[str, Any]) -> dict[str, Any]:
            active_parts[index] = part
            if index in part_positions:
                assistant_parts[part_positions[index]] = part
            else:
                part_positions[index] = len(assistant_parts)
                assistant_parts.append(part)
            return part

        def start_part(
            index: int,
            part_id: str,
            kind: str,
            **fields: Any,
        ) -> dict[str, Any]:
            part = timeline.create_part(part_id, kind, **fields)
            return remember_part(index, part)

        def resolve_index(
            data: dict[str, Any],
            *,
            prefer_active: bool = True,
            expected_kind: str | None = None,
        ) -> int:
            nonlocal fallback_index
            raw_index = data.get("index")
            if isinstance(raw_index, int):
                return raw_index
            if prefer_active and active_parts:
                if expected_kind:
                    for active_index in reversed(active_parts):
                        if active_parts[active_index].get("kind") == expected_kind:
                            return active_index
                else:
                    return next(reversed(active_parts))
            fallback_index += 1
            return 1000 + fallback_index

        def tool_kind_from_name(tool_name: str) -> str:
            if tool_name == "exa_search":
                return "exa"
            if tool_name == "tavily_search":
                return "tavily"
            raise RuntimeError("未知搜索工具")

        try:
            initial = {
                "type": "conversation",
                "conversation": {
                    "id": context.conversation_id,
                    "provider_id": context.provider["id"],
                    "provider_name": context.provider["name"],
                    "model_name": context.provider["model_name"],
                },
            }
            yield emit(initial)
            while True:
                follow_up_required = False
                async for data in stream_gateway_events(
                    context.provider,
                    context.request_payload,
                    context.provider_runtime_state,
                ):
                    event_type = data.get("type")
                    if event_type == "stream_done":
                        if pending_tool_results:
                            follow_up_required = True
                        else:
                            completed = True
                        break

                    if event_type == "turn_end":
                        if pending_tool_results:
                            follow_up_required = True
                        else:
                            completed = True
                        continue

                    if event_type in {"error", "response.error"}:
                        error_payload = data.get("error")
                        detail = (
                            error_payload.get("message")
                            if isinstance(error_payload, dict)
                            else None
                        )
                        detail = (
                            detail
                            or data.get("detail")
                            or (error_payload if isinstance(error_payload, str) else None)
                            or "供应商流返回错误事件"
                        )
                        raise RuntimeError(detail)

                    if event_type in {"reasoning_start", "text_start", "tool_call_start"}:
                        index = resolve_index(data, prefer_active=False)
                        block_type = {"reasoning_start": "thinking", "text_start": "text", "tool_call_start": "tool_use"}.get(event_type)
                        if block_type == "thinking":
                            thinking_count += 1
                            part = start_part(
                                index,
                                f"thinking-{thinking_count}",
                                "thinking",
                                text="",
                            )
                            yield emit({"type": "timeline_part_start", "part": part})
                            continue
                        if block_type == "text":
                            answer_count += 1
                            part = start_part(
                                index,
                                f"answer-{answer_count}",
                                "answer",
                                text="",
                            )
                            yield emit({"type": "timeline_part_start", "part": part})
                            continue
                        if block_type == "tool_use":
                            tool_name = str(data.get("name") or "").strip()
                            part_id = str(data.get("id") or f"tool-{index}")
                            tool_input = data.get("input", {})
                            if not isinstance(tool_input, dict):
                                tool_input = {}
                            pending_tool_use_inputs[index] = {
                                "type": "tool_use",
                                "id": part_id,
                                "name": tool_name,
                                "input": tool_input,
                                "partial_json": "",
                            }
                            part = start_part(
                                index,
                                part_id,
                                "tool",
                                tool_name=tool_name,
                                label=tool_name,
                                input=json.dumps(
                                    tool_input,
                                    ensure_ascii=False,
                                ),
                            )
                            yield emit({"type": "timeline_part_start", "part": part})
                    elif event_type in {"text_delta", "reasoning_delta", "tool_call_delta"}:
                        if event_type == "tool_call_delta":
                            index = resolve_index(data)
                            tool_use_block = pending_tool_use_inputs.get(index)
                            if tool_use_block is not None:
                                tool_use_block["partial_json"] = (
                                    f"{tool_use_block['partial_json']}{data.get('partial_json', '')}"
                                )
                            continue
                        text = data.get("text") if event_type == "text_delta" else None
                        thinking = data.get("text") if event_type == "reasoning_delta" else None
                        if thinking:
                            index = resolve_index(data, expected_kind="thinking")
                            part = active_parts.get(index)
                            if not part:
                                thinking_count += 1
                                part = start_part(
                                    index,
                                    f"thinking-{thinking_count}",
                                    "thinking",
                                    text="",
                                )
                                yield emit(
                                    {"type": "timeline_part_start", "part": part}
                                )
                            updated_part = timeline.append_text(part, thinking)
                            remember_part(index, updated_part)
                            yield emit(
                                {
                                    "type": "timeline_part_delta",
                                    "part_id": updated_part["id"],
                                    "delta": {"text": thinking},
                                }
                            )
                        if text:
                            index = resolve_index(data, expected_kind="answer")
                            part = active_parts.get(index)
                            if not part:
                                answer_count += 1
                                part = start_part(
                                    index,
                                    f"answer-{answer_count}",
                                    "answer",
                                    text="",
                                )
                                yield emit(
                                    {"type": "timeline_part_start", "part": part}
                                )
                            updated_part = timeline.append_text(part, text)
                            remember_part(index, updated_part)
                            yield emit(
                                {
                                    "type": "timeline_part_delta",
                                    "part_id": updated_part["id"],
                                    "delta": {"text": text},
                                }
                            )
                    elif event_type in {"text_end", "reasoning_end", "tool_call_end", "part_end"}:
                        index = resolve_index(data)
                        tool_use_block = pending_tool_use_inputs.pop(index, None)
                        if tool_use_block is not None:
                            part = active_parts.pop(index, None)
                            if not part:
                                continue
                            tool_input = tool_use_block["input"]
                            partial_json = str(
                                tool_use_block.get("partial_json", "")
                            ).strip()
                            if partial_json:
                                parsed_input = json.loads(partial_json)
                                if not isinstance(parsed_input, dict):
                                    raise RuntimeError("工具参数格式不合法")
                                tool_input = parsed_input
                            tool_use_block["input"] = tool_input
                            part = remember_part(
                                index,
                                {
                                    **part,
                                    "input": json.dumps(tool_input, ensure_ascii=False),
                                },
                            )
                            try:
                                exa_api_key = get_exa_config().get("api_key", "").strip()
                                tavily_api_key = (
                                    get_tavily_config().get("api_key", "").strip()
                                )
                                tool_result = await asyncio.to_thread(
                                    tool_runtime.execute_native_search_tool,
                                    tool_kind_from_name(str(tool_use_block["name"])),
                                    tool_input,
                                    exa_api_key,
                                    tavily_api_key,
                                )
                            except Exception as exc:  # noqa: BLE001
                                failed_part = timeline.fail_part(part, str(exc))
                                remember_part(index, failed_part)
                                yield emit(
                                    {
                                        "type": "timeline_part_error",
                                        "part_id": part["id"],
                                        "detail": str(exc),
                                    }
                                )
                                raise
                            updated_part = timeline.finalize_part(
                                {
                                    **part,
                                    "label": tool_result["label"],
                                    "detail": tool_result["detail"],
                                    "output": tool_result["output"],
                                }
                            )
                            remember_part(index, updated_part)
                            pending_assistant_tool_uses.append(
                                {
                                    "type": "tool_use",
                                    "id": str(tool_use_block["id"]),
                                    "name": str(tool_use_block["name"]),
                                    "input": tool_input,
                                }
                            )
                            pending_tool_results.append(
                                (str(tool_use_block["id"]), tool_result)
                            )
                            yield emit(
                                {
                                    "type": "timeline_part_delta",
                                    "part_id": part["id"],
                                    "delta": {
                                        "label": tool_result["label"],
                                        "detail": tool_result["detail"],
                                        "output": tool_result["output"],
                                    },
                                }
                            )
                            yield emit(
                                {
                                    "type": "timeline_part_end",
                                    "part_id": updated_part["id"],
                                }
                            )
                            active_parts.pop(index, None)
                            part_positions.pop(index, None)
                            continue
                        part = active_parts.pop(index, None)
                        if not part:
                            continue
                        finalized_part = part
                        if part.get("status") != "done":
                            finalized_part = timeline.finalize_part(part)
                            remember_part(index, finalized_part)
                            active_parts.pop(index, None)
                        yield emit(
                            {
                                "type": "timeline_part_end",
                                "part_id": finalized_part["id"],
                            }
                        )
                        part_positions.pop(index, None)
                    elif event_type == "usage":
                        usage = data.get("usage")
                        if usage:
                            yield emit({"type": "usage", "usage": usage})
                if follow_up_required:
                    append_provider_tool_result_messages(
                        context.provider,
                        context.request_payload,
                        pending_assistant_tool_uses,
                        [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": tool_result["output"],
                            }
                            for tool_use_id, tool_result in pending_tool_results
                        ],
                        context.provider_runtime_state,
                    )
                    pending_assistant_tool_uses.clear()
                    pending_tool_results.clear()
                    continue
                if completed:
                    break
                raise RuntimeError("流式响应未正确完成")

            for index, part in list(active_parts.items()):
                finalized_part = part
                if part.get("status") != "done":
                    finalized_part = timeline.finalize_part(part)
                    remember_part(index, finalized_part)
                    active_parts.pop(index, None)
                yield emit(
                    {
                        "type": "timeline_part_end",
                        "part_id": finalized_part["id"],
                    }
                )
                active_parts.pop(index, None)
                part_positions.pop(index, None)

            assistant_content_json = json.dumps(
                {"parts": assistant_parts},
                ensure_ascii=False,
            )
            result = commit_stream_chat(
                context,
                timeline.answer_text_from_parts(assistant_parts),
                timeline.thinking_text_from_parts(assistant_parts),
                assistant_content_json=assistant_content_json,
            )
            committed = True
            yield emit({"type": "done", **result})
        except asyncio.CancelledError:
            if not committed:
                rollback_stream_chat(context)
            raise
        except HTTPException as exc:
            if not committed:
                rollback_stream_chat(context)
            yield emit({"type": "error", "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001
            if not committed:
                rollback_stream_chat(context)
            yield emit({"type": "error", "detail": str(exc)})

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

