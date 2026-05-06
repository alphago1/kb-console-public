from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bundle_builder import (
    DISCLAIMER,
    build_budget,
    build_scoped_bundle,
    compress_and_synthesize,
    fetch_folder_docs,
    llm_call,
    render_bundle_markdown,
)


def folder_token_budget(cfg: dict, folder: str) -> dict[str, Any]:
    docs = fetch_folder_docs(cfg, folder)
    b = build_budget(docs)
    return {"scope": "folder", "folder": folder, "document_count": len(docs), **b}


def build_folder_bundle(cfg: dict, folder: str) -> dict[str, Any]:
    docs = fetch_folder_docs(cfg, folder)
    instructions = (
        "请基于全部文档进行高质量分析，输出结论必须引用证据文件；"
        f"并始终遵守：{DISCLAIMER}"
    )
    out = build_scoped_bundle(
        cfg,
        task="Folder Scoped Full-Read Analysis",
        scope=f"folder={folder}",
        docs=docs,
        analysis_instructions=instructions,
        prefix="folder_bundle",
    )
    return {"folder": folder, **out}


def _analysis_prompt(question: str, bundle_md: str) -> str:
    return (
        "你是知识库分析助手。基于以下 bundle 内容回答用户问题。"
        f"务必声明并遵守：{DISCLAIMER}\n\n"
        f"用户问题：{question}\n\n"
        "输出必须包含并仅使用以下一级标题：\n"
        "文件夹主题\n时间线\n反复出现的问题\n关键项目\n可写作内容\n证据文件\n\n"
        "每条关键结论都要附 docs_path 作为证据。\n\n"
        f"[BUNDLE]\n{bundle_md}"
    )


def analyze_folder(cfg: dict, folder: str, question: str) -> dict[str, Any]:
    docs = fetch_folder_docs(cfg, folder)
    budget = build_budget(docs)
    content = compress_and_synthesize(
        cfg, "analyze-folder", f"folder={folder} q={question}", docs,
        lambda scope, md: _analysis_prompt(question, md),
        "按要求输出结构化分析并附证据文件。",
    )

    out = Path(cfg["storage"]["reports_dir"]) / "folder_analysis"
    out.mkdir(parents=True, exist_ok=True)
    name = f"folder_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    target = out / name
    target.write_text(content, encoding="utf-8")
    return {
        "folder": folder,
        "question": question,
        "strategy": strategy,
        "report": str(target.resolve()),
        "document_count": len(docs),
        "token_estimate_high": budget["token_estimate_high"],
    }
