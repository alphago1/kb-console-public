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


def build_monthly_report(cfg: dict, month: str) -> str:
    sqlite_path = cfg["storage"]["sqlite_path"]
    reports_dir = cfg["storage"]["reports_dir"]
    Path(reports_dir).mkdir(parents=True, exist_ok=True)

    with _connect(sqlite_path) as con:
        rows = con.execute(
            """
                        SELECT *, COALESCE(docs_path, path) AS used_path FROM documents
            WHERE include_in_kb = 1
              AND COALESCE(derived_time_month, time_month) = ?
            """,
            (month,),
        ).fetchall()

    trade_docs = [r for r in rows if (r["primary_category"] or "").startswith("交易")]
    cognition_docs = [r for r in rows if r["contains_cognition_change"] == 1]
    project_docs = [r for r in rows if r["contains_project_idea"] == 1]
    writing_docs = [r for r in rows if r["contains_writing_potential"] == 1]

    emotion_counter = Counter()
    for r in rows:
        if not r["emotion_tags"]:
            continue
        try:
            tags = json.loads(r["emotion_tags"]) or []
        except Exception:
            tags = []
        for t in tags:
            emotion_counter[t] += 1

    major_errors = [r for r in trade_docs if (r["confidence"] or 0) < 0.8][:20]

    lines = [f"# {month} 月报", ""]

    lines.append("## 交易复盘总结")
    lines.append(f"- 交易相关文档数：{len(trade_docs)}")
    for r in trade_docs[:20]:
        lines.append(f"- {r['summary'] or ''} ({r['used_path']})")
    lines.append("")

    lines.append("## 主要交易错误")
    for r in major_errors:
        lines.append(f"- {r['summary'] or ''} | 置信度 {r['confidence']:.2f} ({r['used_path']})")
    if not major_errors:
        lines.append("- 无明显低置信度交易错误记录")
    lines.append("")

    lines.append("## 情绪标签趋势")
    for t, c in emotion_counter.most_common(20):
        lines.append(f"- {t}: {c}")
    if not emotion_counter:
        lines.append("- 无")
    lines.append("")

    lines.append("## 认知变化")
    for r in cognition_docs[:30]:
        lines.append(f"- {r['summary'] or ''} ({r['used_path']})")
    if not cognition_docs:
        lines.append("- 无")
    lines.append("")

    lines.append("## 项目想法")
    for r in project_docs[:30]:
        lines.append(f"- {r['summary'] or ''} ({r['used_path']})")
    if not project_docs:
        lines.append("- 无")
    lines.append("")

    lines.append("## 写作素材")
    for r in writing_docs[:30]:
        lines.append(f"- [{r['writing_potential'] or ''}] {r['summary'] or ''} ({r['used_path']})")
    if not writing_docs:
        lines.append("- 无")
    lines.append("")

    out = os.path.join(reports_dir, f"{month}-monthly-report.md")
    Path(out).write_text("\n".join(lines), encoding="utf-8")
    return out
