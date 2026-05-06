from __future__ import annotations

import json
import logging
from typing import Any

from llm_providers.deepseek_provider import DeepSeekProvider

from .audit import write_audit
from .permissions import is_tool_allowed, is_tool_enabled
from .prompts import system_prompt
from .tool_executor import execute_tool
from .tool_registry import get_enabled_tool_schemas


class AgentRuntime:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        agent_cfg = cfg.get("agent", {})
        model = agent_cfg.get("model") or cfg.get("llm", {}).get("model", "deepseek-v4-flash")
        api_env = cfg.get("llm", {}).get("api_key_env", "DEEPSEEK_API_KEY")
        base_url = cfg.get("llm", {}).get("base_url", "https://api.deepseek.com")
        self.max_steps = int(agent_cfg.get("max_steps", 6))
        self.max_tool_result_chars = int(agent_cfg.get("max_tool_result_chars", 12000))
        self.provider = DeepSeekProvider(api_key_env=api_env, base_url=base_url, model=model)

    def _validate_args(self, schema: dict, args: dict) -> tuple[bool, str]:
        params = schema.get("function", {}).get("parameters", {})
        required = params.get("required", [])
        props = params.get("properties", {})
        for k in required:
            if k not in args:
                return False, f"missing required argument: {k}"
        for k, v in args.items():
            if k not in props:
                continue
            typ = props[k].get("type")
            allowed = typ if isinstance(typ, list) else [typ]
            if v is None and "null" in allowed:
                continue
            if "string" in allowed and isinstance(v, str):
                continue
            if "integer" in allowed and isinstance(v, int):
                continue
            if "object" in allowed and isinstance(v, dict):
                continue
            return False, f"invalid type for {k}"
        return True, ""

    def run(self, query: str) -> dict:
        tools = get_enabled_tool_schemas(self.cfg)
        schema_by_name = {t["function"]["name"]: t for t in tools}

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": query},
        ]

        final_answer = ""
        steps = 0
        total_calls = 0

        while steps < self.max_steps:
            steps += 1
            resp = self.provider.chat_with_tools(messages=messages, tools=tools, tool_choice="auto")
            content = resp.get("content") or ""
            reasoning_content = resp.get("reasoning_content") or ""
            tool_calls = resp.get("tool_calls") or []

            if not tool_calls:
                if content:
                    msg = {"role": "assistant", "content": content}
                    if reasoning_content:
                        msg["reasoning_content"] = reasoning_content
                    messages.append(msg)
                final_answer = content or final_answer
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content if content else "",
                "tool_calls": tool_calls,
            }
            if reasoning_content:
                assistant_msg["reasoning_content"] = reasoning_content
            messages.append(assistant_msg)

            for tc in tool_calls:
                total_calls += 1
                call_id = tc.get("id") or f"call-{steps}-{total_calls}"
                fn = tc.get("function", {})
                name = fn.get("name")
                arg_str = fn.get("arguments") or "{}"

                try:
                    args = json.loads(arg_str) if isinstance(arg_str, str) else (arg_str or {})
                except Exception as e:
                    args = {}
                    result = {"error": f"invalid tool arguments json: {e}"}
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
                    continue

                allowed = is_tool_enabled(name, self.cfg) and is_tool_allowed(name, self.cfg)
                if not allowed:
                    result = {"error": f"tool not allowed: {name}"}
                    write_audit(
                        self.cfg,
                        {
                            "model": self.provider.model,
                            "user_query": query,
                            "tool": name,
                            "arguments": args,
                            "allowed": False,
                            "result_count": 0,
                        },
                    )
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
                    continue

                schema = schema_by_name.get(name)
                ok, err = self._validate_args(schema, args) if schema else (False, "tool schema missing")
                if not ok:
                    result = {"error": err}
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)})
                    continue

                try:
                    result = execute_tool(self.cfg, name, args, max_chars=self.max_tool_result_chars)
                    result_count = result.get("result_count")
                    if result_count is None:
                        if isinstance(result.get("items"), list):
                            result_count = len(result["items"])
                        else:
                            result_count = 1
                    write_audit(
                        self.cfg,
                        {
                            "model": self.provider.model,
                            "user_query": query,
                            "tool": name,
                            "arguments": args,
                            "allowed": True,
                            "result_count": result_count,
                        },
                    )
                except Exception as e:
                    logging.exception("tool execution failed: %s", name)
                    result = {"error": str(e)}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False)[: self.max_tool_result_chars],
                    }
                )

        if not final_answer:
            try:
                synth_messages = messages + [
                    {
                        "role": "user",
                        "content": "请基于已有工具证据直接给出最终回答，不要再调用工具。必须包含：结论、关键证据、涉及月份、相关文档、下一步建议。",
                    }
                ]
                final_answer = self.provider.chat(messages=synth_messages, temperature=0.2)
            except Exception:
                logging.exception("fallback synthesis failed")
                final_answer = ""

        return {
            "answer": final_answer,
            "steps": steps,
            "tool_calls": total_calls,
            "messages": messages,
        }
