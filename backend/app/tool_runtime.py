from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.chat_service import (
    EXA_REMOTE_MCP_URL,
    TAVILY_REMOTE_MCP_URL,
    call_remote_mcp_tool,
    normalize_search_query,
    normalize_search_result,
)


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
    try:
        return schemas[kind]
    except KeyError as exc:
        raise RuntimeError("未知搜索工具") from exc


def execute_native_search_tool(
    kind: str,
    arguments: dict[str, Any],
    tavily_api_key: str = "",
) -> dict[str, str]:
    query = normalize_search_query(str(arguments.get("query", "")))
    if kind == "exa":
        return normalize_search_result(
            "Exa 搜索",
            call_remote_mcp_tool(
                EXA_REMOTE_MCP_URL,
                "web_search_exa",
                {"query": query},
            ),
        )
    if kind == "tavily":
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
