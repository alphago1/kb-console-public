from __future__ import annotations

import os
from pathlib import Path


READ_ONLY_TOOLS = {
    "search_documents",
    "search_chunks",
    "get_document",
    "compare_periods",
    "summarize_month",
}

WRITE_REPORT_TOOL = "generate_report"


def is_tool_enabled(tool_name: str, cfg: dict) -> bool:
    enabled = cfg.get("tools", {}).get("enabled")
    if not enabled:
        return True
    return tool_name in set(enabled)


def is_tool_allowed(tool_name: str, cfg: dict) -> bool:
    if tool_name in READ_ONLY_TOOLS:
        return True
    if tool_name == WRITE_REPORT_TOOL:
        return bool(cfg.get("agent", {}).get("allow_write_reports", True))
    return False


def ensure_report_path_allowed(cfg: dict, target_file: str) -> bool:
    reports_dir = cfg.get("permissions", {}).get("output_dirs", {}).get("reports") or cfg["storage"].get("reports_dir")
    reports_dir_abs = os.path.abspath(reports_dir)
    target_abs = os.path.abspath(target_file)
    return os.path.commonpath([reports_dir_abs, target_abs]) == reports_dir_abs


def safe_report_path(cfg: dict, filename: str) -> str:
    reports_dir = cfg.get("permissions", {}).get("output_dirs", {}).get("reports") or cfg["storage"].get("reports_dir")
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    name = os.path.basename(filename)
    return os.path.join(reports_dir, name)
