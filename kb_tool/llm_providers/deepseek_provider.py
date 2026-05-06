from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from .base import LLMProvider


class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key_env: str = "DEEPSEEK_API_KEY", base_url: str = "https://api.deepseek.com", model: str = "deepseek-v4-flash"):
        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(f"missing api key env: {api_key_env}")
        self.client = OpenAI(api_key=key, base_url=base_url)
        self.model = model

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        resp = self.client.chat.completions.create(model=self.model, messages=messages, **kwargs)
        return (resp.choices[0].message.content or "").strip()

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict],
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        msg = resp.choices[0].message
        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
        return {
            "content": (msg.content or "").strip(),
            "reasoning_content": (getattr(msg, "reasoning_content", None) or ""),
            "tool_calls": tool_calls,
        }
