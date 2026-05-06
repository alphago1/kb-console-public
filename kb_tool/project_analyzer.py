from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from bundle_builder import DISCLAIMER, build_budget, compress_and_synthesize, fetch_topic_docs


def _project_prompt(topic: str, question: str, bundle_md: str) -> str:
    return (
        f"你是项目分析助手，请围绕主题“{topic}”回答问题：{question}。\n"
        f"必须遵守：{DISCLAIMER}\n"
        "输出必须包含以下一级标题：\n"
        "项目一句话定义\nnovelty\n与已有普通方案的区别\n已有材料中的核心设计\n可推进方向\n风险与缺口\n证据文件\n\n"
        "每条结论必须给证据文件路径。\n\n"
        f"[BUNDLE]\n{bundle_md}"
    )


def project_analyze(cfg: dict, topic: str, question: str) -> dict[str, Any]:
    docs = fetch_topic_docs(cfg, topic)
    budget = build_budget(docs)
    content = compress_and_synthesize(
        cfg, "project-analyze", f"topic={topic} q={question}", docs,
        lambda scope, md: _project_prompt(topic, question, md),
        "按项目分析要求输出并附证据。",
    )

    out_dir = Path(cfg["storage"]["reports_dir"]) / "project_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"project_{topic[:40].replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out.write_text(content, encoding="utf-8")

    return {
        "topic": topic,
        "question": question,
        "strategy": strategy,
        "report": str(out.resolve()),
        "document_count": len(docs),
        "token_estimate_high": budget["token_estimate_high"],
    }
