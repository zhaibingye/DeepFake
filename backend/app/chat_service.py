from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.auth import utcnow
from app.db import get_conn

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_CLIENT_INFO = {"name": "deepfake-backend", "version": "1.0.0"}
MCP_ACCEPT = "application/json, text/event-stream"
EXA_REMOTE_MCP_URL = "https://mcp.exa.ai/mcp"
TAVILY_REMOTE_MCP_URL = "https://mcp.tavily.com/mcp/"


class SearchProviderUnavailableError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(slots=True)
class ChatStreamContext:
    provider: sqlite3.Row
    conversation_id: int
    created_new_conversation: bool
    search_query_text: str
    pending_user_text: str | None
    pending_user_content_json: str | None
    created_at: str
    request_payload: dict[str, Any]
    search_tool: dict[str, Any] | None


def parse_message(row: sqlite3.Row) -> dict[str, Any]:
    content = row["content_text"]
    if row["content_json"]:
        content = json.loads(row["content_json"])
    return {
        "id": row["id"],
        "role": row["role"],
        "content": content,
        "thinking_text": row["thinking_text"] or "",
        "created_at": row["created_at"],
    }


def fetch_provider(provider_id: int, include_disabled: bool = False) -> sqlite3.Row:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if not include_disabled and not row["is_enabled"]:
            raise HTTPException(status_code=400, detail="供应商已禁用")
        return row


def validate_attachment(attachment: Any) -> None:
    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if attachment.media_type not in allowed:
        raise HTTPException(
            status_code=400, detail=f"不支持的图片类型: {attachment.media_type}"
        )
    try:
        base64.b64decode(attachment.data, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail="图片不是合法的 base64 数据"
        ) from exc


def message_to_anthropic_content(
    text: str, attachments: list[Any]
) -> str | list[dict[str, Any]]:
    if not attachments:
        return text
    blocks: list[dict[str, Any]] = []
    for attachment in attachments:
        validate_attachment(attachment)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": attachment.media_type,
                    "data": attachment.data,
                },
            }
        )
    if text.strip():
        blocks.append({"type": "text", "text": text})
    return blocks


def build_history(conversation_id: int) -> list[dict[str, Any]]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT role, content_text, content_json FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        content: Any = row["content_text"]
        if row["content_json"]:
            content = json.loads(row["content_json"])
        history.append({"role": row["role"], "content": content})
    return history


def build_chat_request_payload(
    provider: sqlite3.Row,
    history: list[dict[str, Any]],
    payload: Any,
    stream: bool = False,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "model": provider["model_name"],
        "max_tokens": provider["max_output_tokens"],
        "messages": history,
    }
    if payload.enable_thinking and provider["supports_thinking"]:
        request_payload["thinking"] = {"type": "adaptive"}
        request_payload["output_config"] = {
            "effort": payload.effort or provider["thinking_effort"]
        }
    if stream:
        request_payload["stream"] = True
    return request_payload


def resolve_search_tool(payload: Any) -> dict[str, Any] | None:
    if not getattr(payload, "enable_search", False):
        return None
    if payload.search_provider == "exa":
        return {"name": "exa_search", "label": "Exa 搜索"}
    if payload.search_provider == "tavily":
        from app.main import get_tavily_config

        config = get_tavily_config()
        if not config["is_enabled"] or not config["api_key"]:
            raise SearchProviderUnavailableError(
                "Tavily 搜索当前不可用，请先在后台配置"
            )
        return {"name": "tavily_search", "label": "Tavily 搜索"}
    raise HTTPException(status_code=400, detail="请先选择搜索来源")


def normalize_search_query(query: str) -> str:
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")
    return normalized_query


def _extract_jsonrpc_response_from_sse(response_text: str) -> dict[str, Any] | None:
    event_data: list[str] = []
    payloads: list[str] = []
    for line in response_text.splitlines():
        if not line.strip():
            if event_data:
                payloads.append("\n".join(event_data))
                event_data = []
            continue
        if line.startswith("data:"):
            event_data.append(line.removeprefix("data:").strip())
    if event_data:
        payloads.append("\n".join(event_data))
    for payload in reversed(payloads):
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(data, dict)
            and data.get("jsonrpc") == "2.0"
            and ("result" in data or "error" in data)
        ):
            return data
    return None


def _header_value(headers: dict[str, str], name: str) -> str | None:
    lowered_name = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered_name:
            return value
    return None


def _base_mcp_headers(extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Accept": MCP_ACCEPT,
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _post_mcp_jsonrpc(
    server_url: str, payload: dict[str, Any], headers: dict[str, str]
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.post(server_url, json=payload, headers=headers)

    response_headers = dict(response.headers)
    response_text = response.text.strip()
    if response.status_code >= 400:
        detail = response_text or "empty response"
        raise RuntimeError(
            f"远程 MCP 请求失败: {response.status_code} {detail}"
        )
    if not response_text:
        return None, response_headers

    content_type = _header_value(response_headers, "Content-Type") or ""
    if "text/event-stream" in content_type.lower():
        body = _extract_jsonrpc_response_from_sse(response_text)
    else:
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("远程 MCP 返回了不合法的 JSON 响应") from exc
    if body is not None and not isinstance(body, dict):
        raise RuntimeError("远程 MCP 返回了不合法的 JSON-RPC 响应")
    return body, response_headers


def _extract_jsonrpc_result(
    method_name: str, response_body: dict[str, Any] | None
) -> dict[str, Any] | None:
    if response_body is None:
        if method_name == "notifications/initialized":
            return None
        raise RuntimeError(f"远程 MCP {method_name} 未返回响应体")
    if "error" in response_body:
        error = response_body["error"]
        if isinstance(error, dict):
            detail = error.get("message") or json.dumps(error, ensure_ascii=False)
        else:
            detail = str(error)
        raise RuntimeError(f"远程 MCP {method_name} 失败: {detail}")
    result = response_body.get("result")
    if result is None:
        raise RuntimeError(f"远程 MCP {method_name} 未返回 result")
    if not isinstance(result, dict):
        raise RuntimeError(f"远程 MCP {method_name} 返回了不合法的 result")
    return result


def call_remote_mcp_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    initialize_body, initialize_headers = _post_mcp_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": MCP_CLIENT_INFO,
            },
        },
        _base_mcp_headers(
            {
                **(headers or {}),
                "Mcp-Method": "initialize",
            }
        ),
    )
    initialize_result = _extract_jsonrpc_result("initialize", initialize_body)
    protocol_version = (
        initialize_result.get("protocolVersion")
        if isinstance(initialize_result.get("protocolVersion"), str)
        else MCP_PROTOCOL_VERSION
    )
    session_id = _header_value(initialize_headers, "MCP-Session-Id")
    session_headers: dict[str, str] = {
        **(headers or {}),
        "MCP-Protocol-Version": protocol_version,
    }
    if session_id:
        session_headers["MCP-Session-Id"] = session_id

    _post_mcp_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        _base_mcp_headers(
            {
                **session_headers,
                "Mcp-Method": "notifications/initialized",
            }
        ),
    )

    tools_body, _ = _post_mcp_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        },
        _base_mcp_headers(
            {
                **session_headers,
                "Mcp-Method": "tools/call",
                "Mcp-Name": tool_name,
            }
        ),
    )
    tools_result = _extract_jsonrpc_result("tools/call", tools_body)
    return tools_result


def normalize_search_result(tool_label: str, result: Any) -> dict[str, str]:
    if not isinstance(result, dict):
        raise RuntimeError(f"{tool_label} 返回了不合法的搜索结果")
    content = result.get("content")
    if not isinstance(content, list) or not content:
        raise RuntimeError(f"{tool_label} 未返回搜索内容")

    output_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            output_parts.append(text.strip())
        else:
            output_parts.append(json.dumps(block, ensure_ascii=False))

    output = "\n\n".join(part for part in output_parts if part.strip()).strip()
    if result.get("isError"):
        raise RuntimeError(output or f"{tool_label} 执行失败")
    if not output:
        raise RuntimeError(f"{tool_label} 未返回可显示内容")
    return {
        "label": tool_label,
        "detail": f"返回 {len(content)} 个内容块",
        "output": output,
    }


def run_exa_search(query: str) -> dict[str, str]:
    normalized_query = normalize_search_query(query)
    return normalize_search_result(
        "Exa 搜索",
        call_remote_mcp_tool(
            EXA_REMOTE_MCP_URL,
            "web_search_exa",
            {"query": normalized_query},
        ),
    )


def run_tavily_search(query: str) -> dict[str, str]:
    normalized_query = normalize_search_query(query)
    from app.main import get_tavily_config

    config = get_tavily_config()
    api_key = config.get("api_key", "").strip()
    if not api_key:
        raise RuntimeError("Tavily 搜索当前不可用，请先在后台配置")
    return normalize_search_result(
        "Tavily 搜索",
        call_remote_mcp_tool(
            f"{TAVILY_REMOTE_MCP_URL}?tavilyApiKey={quote(api_key, safe='')}",
            "tavily-search",
            {"query": normalized_query},
        ),
    )


def execute_search_tool(tool_name: str, query: str) -> dict[str, str]:
    if tool_name == "exa_search":
        return run_exa_search(query)
    if tool_name == "tavily_search":
        return run_tavily_search(query)
    raise HTTPException(status_code=400, detail="未知搜索工具")


def inject_search_result_into_request_payload(
    request_payload: dict[str, Any], tool_result: dict[str, str]
) -> None:
    request_payload["messages"].append(
        {
            "role": "user",
            "content": (
                f"以下是本轮问题的联网搜索结果，请基于这些结果回答。\n"
                f"工具: {tool_result['label']}\n"
                f"摘要: {tool_result['detail']}\n\n"
                f"联网搜索结果:\n{tool_result['output']}"
            ),
        }
    )


def prepare_stream_chat(payload: Any, user: dict[str, Any]) -> ChatStreamContext:
    if not payload.text.strip() and not payload.attachments:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    if getattr(payload, "enable_search", False) and not payload.text.strip():
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")

    provider = fetch_provider(payload.provider_id)
    if payload.enable_thinking and not provider["supports_thinking"]:
        raise HTTPException(status_code=400, detail="当前模型不支持思考")
    if payload.attachments and not provider["supports_vision"]:
        raise HTTPException(status_code=400, detail="当前模型不支持图片")
    search_tool = resolve_search_tool(payload)

    now = utcnow()
    search_query_text = payload.text.strip()
    content = message_to_anthropic_content(search_query_text, payload.attachments)
    pending_user_text = search_query_text if isinstance(content, str) else None
    pending_user_content_json = (
        json.dumps(content, ensure_ascii=False) if isinstance(content, list) else None
    )

    with closing(get_conn()) as conn:
        created_new_conversation = payload.conversation_id is None
        if created_new_conversation:
            title_source = payload.text.strip() or (
                payload.attachments[0].name if payload.attachments else "新对话"
            )
            title = title_source[:40]
            cursor = conn.execute(
                "INSERT INTO conversations (user_id, provider_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user["id"], provider["id"], title, now, now),
            )
            conversation_id = int(cursor.lastrowid)
        else:
            convo = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (payload.conversation_id, user["id"]),
            ).fetchone()
            if not convo:
                raise HTTPException(status_code=404, detail="会话不存在")
            conversation_id = int(convo["id"])
        conn.commit()

    history = build_history(conversation_id)
    history.append({"role": "user", "content": content})
    request_payload = build_chat_request_payload(
        provider,
        history,
        payload,
        stream=True,
    )

    return ChatStreamContext(
        provider=provider,
        conversation_id=conversation_id,
        created_new_conversation=created_new_conversation,
        search_query_text=search_query_text,
        pending_user_text=pending_user_text,
        pending_user_content_json=pending_user_content_json,
        created_at=now,
        request_payload=request_payload,
        search_tool=search_tool,
    )


def commit_stream_chat(
    context: ChatStreamContext, assistant_text: str, thinking_text: str
) -> dict[str, Any]:
    assistant_created_at = utcnow()
    final_assistant_text = assistant_text.strip() or "模型没有返回可显示文本。"
    final_thinking_text = thinking_text.strip()
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content_text, content_json, thinking_text, created_at) VALUES (?, 'user', ?, ?, '', ?)",
            (
                context.conversation_id,
                context.pending_user_text,
                context.pending_user_content_json,
                context.created_at,
            ),
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content_text, content_json, thinking_text, created_at) VALUES (?, 'assistant', ?, NULL, ?, ?)",
            (
                context.conversation_id,
                final_assistant_text,
                final_thinking_text,
                assistant_created_at,
            ),
        )
        conn.execute(
            "UPDATE conversations SET provider_id = ?, updated_at = ? WHERE id = ?",
            (context.provider["id"], assistant_created_at, context.conversation_id),
        )
        conn.commit()
        convo = conn.execute(
            "SELECT conversations.*, providers.name AS provider_name, providers.model_name AS model_name FROM conversations JOIN providers ON providers.id = conversations.provider_id WHERE conversations.id = ?",
            (context.conversation_id,),
        ).fetchone()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 2",
            (context.conversation_id,),
        ).fetchall()
    return {
        "conversation": {
            "id": convo["id"],
            "title": convo["title"],
            "provider_id": convo["provider_id"],
            "provider_name": convo["provider_name"],
            "model_name": convo["model_name"],
            "created_at": convo["created_at"],
            "updated_at": convo["updated_at"],
        },
        "messages": [parse_message(row) for row in reversed(rows)],
    }


def rollback_stream_chat(context: ChatStreamContext) -> None:
    if not context.created_new_conversation:
        return
    with closing(get_conn()) as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (context.conversation_id,)
        )
        conn.execute(
            "DELETE FROM conversations WHERE id = ?", (context.conversation_id,)
        )
        conn.commit()
