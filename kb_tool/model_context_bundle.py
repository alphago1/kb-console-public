from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def build_model_context_bundle(cfg: dict) -> str:
    sqlite_path = cfg["storage"]["sqlite_path"]
    out_path = os.path.join(cfg["storage"]["output_dir"], "model_context_bundle.md")
    Path(cfg["storage"]["output_dir"]).mkdir(parents=True, exist_ok=True)

    with _connect(sqlite_path) as con:
        rows = con.execute("SELECT * FROM documents WHERE include_in_kb=1 ORDER BY COALESCE(derived_time_month,time_month) DESC").fetchall()

    by_cat = Counter((r["primary_category"] or "未知") for r in rows)
    by_month = Counter((r["derived_time_month"] or r["time_month"] or "未知") for r in rows)

    lines = ["# Model Context Bundle", "", "该文件用于手动上传给任意大模型，帮助快速理解个人知识库。", ""]
    lines.append("## 全局统计")
    lines.append(f"- 纳入文档数: {len(rows)}")
    lines.append("- 一级分类分布:")
    for k, v in by_cat.most_common():
        lines.append(f"  - {k}: {v}")
    lines.append("- 月份分布:")
    for k, v in by_month.most_common(24):
        lines.append(f"  - {k}: {v}")
    lines.append("")

    lines.append("## 最近高价值文档（写作潜力/认知变化/项目想法）")
    selected = [
        r
        for r in rows
        if r["contains_writing_potential"] == 1 or r["contains_cognition_change"] == 1 or r["contains_project_idea"] == 1
    ][:120]
    for r in selected:
        lines.append(f"- 月份: {r['derived_time_month'] or r['time_month'] or '未知'}")
        lines.append(f"  - 分类: {r['primary_category'] or ''} / {r['secondary_category'] or ''}")
        lines.append(f"  - 路径: {r['path']}")
        lines.append(f"  - 摘要: {r['summary'] or ''}")
        lines.append(f"  - 置信度: {r['confidence']}")
        if r["topic_tags"]:
            try:
                tags = json.loads(r["topic_tags"])
            except Exception:
                tags = []
            lines.append(f"  - 标签: {', '.join(tags)}")
    lines.append("")

    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return out_path
