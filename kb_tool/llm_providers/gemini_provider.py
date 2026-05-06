from __future__ import annotations

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Gemini provider scaffolded but not configured in this project")

    def chat(self, messages, **kwargs):
        raise NotImplementedError

    def chat_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
        raise NotImplementedError
