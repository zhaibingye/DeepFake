from __future__ import annotations

import json
from typing import Any


def create_part(
    part_id: str, kind: str, *, status: str = "running", **fields: Any
) -> dict[str, Any]:
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
        parts.append(
            create_part(
                "legacy-thinking",
                "thinking",
                status="done",
                text=thinking_text,
            )
        )
    if text_content:
        parts.append(
            create_part(
                "legacy-answer",
                "answer",
                status="done",
                text=text_content,
            )
        )
    return parts


def message_parts_from_row(row: Any) -> list[dict[str, Any]]:
    if row["role"] != "assistant":
        return []
    if row["content_json"]:
        content = json.loads(row["content_json"])
        if isinstance(content, dict) and isinstance(content.get("parts"), list):
            return content["parts"]
    return legacy_message_parts(row["content_text"] or "", row["thinking_text"] or "")


def answer_text_from_parts(parts: list[dict[str, Any]]) -> str:
    return "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "answer"
    )


def thinking_text_from_parts(parts: list[dict[str, Any]]) -> str:
    return "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "thinking"
    )


def assistant_content_from_row(row: Any) -> str:
    parts = message_parts_from_row(row)
    answer_text = answer_text_from_parts(parts)
    if answer_text:
        return answer_text
    content_text = row["content_text"]
    return content_text if isinstance(content_text, str) else ""
