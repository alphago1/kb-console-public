# MCP Server (Plan3B)

本目录实现了基于 JSON-RPC 2.0 的本地 MCP 风格服务封装，复用已有 Agent 工具能力。

## 设计原则
1. 复用 `agent/tool_registry.py` 与 `agent/tool_executor.py`
2. 不重复业务逻辑
3. 默认只读
4. 返回路径可脱敏（`[KB_ROOT]`）
5. 每次调用写入 `kb_out/logs/mcp_audit.jsonl`

## 传输方式
- stdio：`python main.py mcp-stdio --config config.yaml`
- localhost HTTP：`python main.py mcp-http --config config.yaml --host 127.0.0.1 --port 8765`

## 调试命令
- `python main.py mcp-list-tools --config config.yaml`
- `python main.py mcp-smoke-test --config config.yaml`

## 已暴露 MCP Tools（默认）
- `kb.search_documents`
- `kb.search_chunks`
- `kb.get_document`
- `kb.compare_periods`
- `kb.summarize_month`
- `kb.find_writing_candidates`
- `kb.cluster_project_ideas`

`kb.generate_report` 默认在 mcp 配置中禁用。
