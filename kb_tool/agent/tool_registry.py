from __future__ import annotations

from .tool_schemas import get_tool_schemas


def get_enabled_tool_schemas(cfg: dict) -> list[dict]:
    enabled = set(cfg.get("tools", {}).get("enabled", []))
    all_tools = get_tool_schemas()
    if not enabled:
        return all_tools
    filtered: list[dict] = []
    for t in all_tools:
        name = t.get("function", {}).get("name")
        if name in enabled:
            filtered.append(t)
    return filtered
