from __future__ import annotations

import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _quarter_months(quarter: str) -> list[str]:
    # format YYYY-QX
    y, q = quarter.split("-Q")
    y = int(y)
    q = int(q)
    start_m = (q - 1) * 3 + 1
    return [f"{y:04d}-{m:02d}" for m in range(start_m, start_m + 3)]


def build_quarterly_report(cfg: dict, quarter: str) -> str:
    reports_dir = cfg["storage"]["reports_dir"]
    Path(reports_dir).mkdir(parents=True, exist_ok=True)

    months = set(_quarter_months(quarter))

    sqlite_path = cfg["storage"]["sqlite_path"]
    with _connect(sqlite_path) as con:
        rows = con.execute("SELECT * FROM documents WHERE include_in_kb = 1").fetchall()

    q_rows = [r for r in rows if (r["derived_time_month"] or r["time_month"]) in months]

    by_cat = Counter(r["primary_category"] or "未知" for r in q_rows)
    trade = sum(1 for r in q_rows if r["contains_trade_data"] == 1 or (r["primary_category"] or "").startswith("交易"))
    cognition = [r for r in q_rows if r["contains_cognition_change"] == 1]
    writing = [r for r in q_rows if r["contains_writing_potential"] == 1]

    lines: list[str] = []
    lines.append(f"# {quarter} 知识库季度报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(f"本季度纳入文档数：{len(q_rows)}")
    lines.append(f"交易相关文档数：{trade}")
    lines.append(f"认知变化文档数：{len(cognition)}")
    lines.append(f"写作潜力文档数：{len(writing)}")
    lines.append("")

    lines.append("## 一级分类分布")
    for k, v in by_cat.most_common():
        lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("## 认知变化（最多 30）")
    for r in cognition[:30]:
        lines.append(f"- {r['derived_time_month'] or r['time_month']}: {r['summary'] or ''} ({r['path']})")
    lines.append("")

    lines.append("## 写作潜力（最多 30）")
    for r in writing[:30]:
        lines.append(f"- {r['derived_time_month'] or r['time_month']}: {r['writing_potential'] or ''} | {r['summary'] or ''} ({r['path']})")
    lines.append("")

    out_path = os.path.join(reports_dir, f"{quarter}-report.md")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return out_path
