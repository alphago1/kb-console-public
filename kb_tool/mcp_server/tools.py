from __future__ import annotations

from agent.tool_registry import get_enabled_tool_schemas


PREFIX = "kb."


def _enabled_from_cfg(cfg: dict) -> set[str]:
    enabled = cfg.get("mcp", {}).get("enabled_tools") or []
    if not enabled:
        return set()
    return set(enabled)


def _disabled_from_cfg(cfg: dict) -> set[str]:
    disabled = cfg.get("mcp", {}).get("disabled_tools") or []
    return set(disabled)


def list_tools(cfg: dict) -> list[dict]:
    base_tools = get_enabled_tool_schemas(cfg)
    enabled = _enabled_from_cfg(cfg)
    disabled = _disabled_from_cfg(cfg)

    out: list[dict] = []
    for t in base_tools:
        fn = t.get("function", {})
        base_name = fn.get("name")
        mcp_name = PREFIX + base_name

        if enabled and mcp_name not in enabled:
            continue
        if mcp_name in disabled:
            continue

        out.append(
            {
                "name": mcp_name,
                "description": fn.get("description", ""),
                "inputSchema": fn.get("parameters", {}),
            }
        )
    return out


def has_tool(cfg: dict, tool_name: str) -> bool:
    names = {t["name"] for t in list_tools(cfg)}
    return tool_name in names
