from __future__ import annotations

import json
from typing import Any


def extract_json_object(text: str) -> str:
    """Extract first JSON object substring from a possibly fenced response."""
    if not text:
        raise ValueError("empty response")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        # remove code fences
        cleaned = cleaned.strip("`")
        # try to drop optional language tag line
        lines = cleaned.splitlines()
        if lines and lines[0].lower().strip() in {"json", "javascript"}:
            cleaned = "\n".join(lines[1:]).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json object found")
    return cleaned[start : end + 1]


def loads_json(text: str) -> Any:
    return json.loads(text)


def dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
