from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from bundle_builder import DISCLAIMER, build_budget, compress_and_synthesize, fetch_profile_docs


def _profile_prompt(scope: str, bundle_md: str) -> str:
    return (
        f"你是用户画像分析助手。当前 scope={scope}。\n"
        f"必须遵守：{DISCLAIMER}\n"
        "输出必须包含以下一级标题：\n"
        "长期关注主题\n决策模式\n交易画像\nAI项目画像\n情绪/执行力模式\n写作倾向\n证据文件\n\n"
        "每条结论必须给证据文件路径。\n\n"
        f"[BUNDLE]\n{bundle_md}"
    )


def profile_me(cfg: dict, scope: str) -> dict[str, Any]:
    docs = fetch_profile_docs(cfg, scope)
    budget = build_budget(docs)
    content = compress_and_synthesize(
        cfg, "profile-me", f"profile_scope={scope}", docs,
        _profile_prompt, "按画像要求输出并附证据。",
    )

    out_dir = Path(cfg["storage"]["reports_dir"]) / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"profile_{scope}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out.write_text(content, encoding="utf-8")

    return {
        "scope": scope,
        "strategy": strategy,
        "report": str(out.resolve()),
        "document_count": len(docs),
        "token_estimate_high": budget["token_estimate_high"],
    }
