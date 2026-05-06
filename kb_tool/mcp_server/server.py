from __future__ import annotations

import json
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .adapters import call_tool
from .auth import enforce_local_http, sampling_enabled
from .prompts import get_prompt, list_prompts
from .resources import list_resources, read_resource
from .tools import list_tools


def _rpc_ok(rid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_rpc(cfg: dict, req: dict, client: str = "local") -> dict:
    rid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if method == "initialize":
        return _rpc_ok(
            rid,
            {
                "serverInfo": {"name": "kb-mcp", "version": "0.1"},
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                    "sampling": bool(sampling_enabled(cfg)),
                },
            },
        )

    if method == "tools/list":
        return _rpc_ok(rid, {"tools": list_tools(cfg)})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        result = call_tool(cfg, name, arguments, client=client)
        return _rpc_ok(rid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})

    if method == "resources/list":
        return _rpc_ok(rid, {"resources": list_resources(cfg)})

    if method == "resources/read":
        uri = params.get("uri", "")
        r = read_resource(cfg, uri)
        return _rpc_ok(rid, {"contents": [{"uri": uri, "mimeType": r.get("mimeType", "text/plain"), "text": r.get("text", "")}]})

    if method == "prompts/list":
        return _rpc_ok(rid, {"prompts": list_prompts()})

    if method == "prompts/get":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        p = get_prompt(name, arguments)
        if p.get("error"):
            return _rpc_err(rid, -32602, p["error"])
        return _rpc_ok(rid, {"messages": [{"role": "user", "content": {"type": "text", "text": p["content"]}}]})

    return _rpc_err(rid, -32601, f"method not found: {method}")


def run_stdio_server(cfg: dict) -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            resp = _rpc_err(None, -32700, "parse error")
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        resp = handle_rpc(cfg, req, client="stdio")
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def create_http_app(cfg: dict) -> FastAPI:
    app = FastAPI(title="KB MCP HTTP", version="0.1")

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/rpc")
    async def rpc(req: Request):
        payload = await req.json()
        out = handle_rpc(cfg, payload, client="http")
        return JSONResponse(out)

    return app


def run_http_server(cfg: dict, host: str, port: int) -> int:
    import uvicorn

    enforce_local_http(host)
    app = create_http_app(cfg)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
