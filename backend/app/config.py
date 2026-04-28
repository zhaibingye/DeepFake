from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _read_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}

    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        data = json.load(config_file)

    if not isinstance(data, dict):
        raise ValueError(f"Backend config must be a JSON object: {CONFIG_PATH}")

    return data


def get_allowed_origins() -> list[str]:
    data = _read_config()
    origins = data.get("allowed_origins", DEFAULT_ALLOWED_ORIGINS)
    if not isinstance(origins, list) or not all(isinstance(origin, str) for origin in origins):
        raise ValueError("backend/config.json field allowed_origins must be a list of strings")

    normalized = [origin.strip().rstrip("/") for origin in origins if origin.strip()]
    return normalized or DEFAULT_ALLOWED_ORIGINS
