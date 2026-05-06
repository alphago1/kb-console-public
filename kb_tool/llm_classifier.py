from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from openai import OpenAI

from models import LLMResult
from utils.json_utils import extract_json_object, loads_json


def _load_prompt_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _render_template(tpl: str, mapping: dict) -> str:
    # Very simple {{var}} replacement; template already uses these placeholders.
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", str(v) if v is not None else "")
    return out


def _maybe_redact_path(path: str) -> str:
    # v1: user chose no redaction
    return path


def classify_with_llm(cfg: dict, *, filename: str, path: str, extension: str, size: int, created_time, modified_time, document_created_time, sampled_text: str, allowed_categories: Optional[list[str]] = None) -> LLMResult:
    llm = cfg["llm"]
    api_key = os.getenv(llm.get("api_key_env", "DEEPSEEK_API_KEY"))
    if not api_key:
        raise RuntimeError(f"missing api key env: {llm.get('api_key_env')}")

    base_url = llm.get("base_url")
    model = llm.get("model")
    client = OpenAI(api_key=api_key, base_url=base_url)

    prompt_path = llm.get("prompt_template_path")
    prompt_path = str((Path(__file__).parent / prompt_path).resolve()) if prompt_path else None
    if not prompt_path or not os.path.exists(prompt_path):
        raise FileNotFoundError(f"prompt template not found: {prompt_path}")

    tpl = _load_prompt_template(prompt_path)

    mapping = {
        "filename": filename,
        "path": _maybe_redact_path(path) if not llm.get("redact_paths") else os.path.basename(path),
        "extension": extension,
        "size": size,
        "created_time": created_time,
        "modified_time": modified_time,
        "document_created_time": document_created_time,
        "sampled_text": sampled_text,
    }

    prompt = _render_template(tpl, mapping)

    # Inject dynamic categories when supervised policy provides them
    if allowed_categories:
        cat_lines = "\n".join(f"- {c}" for c in allowed_categories)
        if "无法判断" not in allowed_categories:
            cat_lines += "\n- 无法判断"
        prompt = re.sub(
            r"可选 primary_category：\n(?:- [^\n]+\n)+",
            f"可选 primary_category：\n{cat_lines}\n",
            prompt,
        )

    max_snip = int(llm.get("max_snippet_chars", 14000))
    if llm.get("allow_send_snippets") and len(prompt) > max_snip:
        prompt = prompt[:max_snip]

    retries = int(llm.get("retries", 3))
    temperature = float(llm.get("temperature", 0.2))
    timeout = int(llm.get("timeout_seconds", 60))

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                timeout=timeout,
            )
            content = resp.choices[0].message.content or ""
            json_str = extract_json_object(content)
            data = loads_json(json_str)
            return LLMResult.model_validate(data)
        except Exception as e:
            last_err = e
            logging.warning("LLM parse/call failed attempt=%s err=%s", attempt + 1, e)

    raise RuntimeError(f"LLM failed after retries: {last_err}")
