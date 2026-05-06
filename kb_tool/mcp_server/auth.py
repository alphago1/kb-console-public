from __future__ import annotations


def enforce_local_http(host: str) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("mcp-http only allows localhost (127.0.0.1)")


def sampling_enabled(cfg: dict) -> bool:
    return bool(cfg.get("mcp", {}).get("enable_sampling", False))
