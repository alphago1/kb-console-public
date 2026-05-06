from __future__ import annotations

import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from jinja2 import Template


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def build_dashboard(cfg: dict) -> str:
    out_dir = cfg["storage"]["dashboard_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    sqlite_path = cfg["storage"]["sqlite_path"]
    with _connect(sqlite_path) as con:
        rows = con.execute("SELECT * FROM documents").fetchall()

    total = len(rows)
    included = sum(1 for r in rows if r["include_in_kb"] == 1)
    excluded = sum(1 for r in rows if r["include_in_kb"] == 0)
    review = sum(1 for r in rows if r["needs_review"] == 1)

    by_month = Counter(r["derived_time_month"] or r["time_month"] or "未知" for r in rows)
    by_cat = Counter(r["primary_category"] or "未知" for r in rows if r["include_in_kb"] == 1)

    # heatmap month x category
    heat = defaultdict(lambda: Counter())
    months = sorted(set(by_month.keys()))
    cats = sorted(set(by_cat.keys()))
    for r in rows:
        if r["include_in_kb"] != 1:
            continue
        m = r["derived_time_month"] or r["time_month"] or "未知"
        c = r["primary_category"] or "未知"
        heat[m][c] += 1

    # trade trend
    trade_trend = Counter()
    for r in rows:
        m = r["derived_time_month"] or r["time_month"] or "未知"
        is_trade = (r["contains_trade_data"] == 1) or ((r["primary_category"] or "").startswith("交易"))
        if is_trade and r["include_in_kb"] == 1:
            trade_trend[m] += 1

    # emotion trend: top tags
    emotion_by_month: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        m = r["derived_time_month"] or r["time_month"] or "未知"
        tags_json = r["emotion_tags"]
        if not tags_json:
            continue
        try:
            import json

            tags = json.loads(tags_json)
        except Exception:
            continue
        for t in tags:
            emotion_by_month[m][t] += 1

    # cognition change list
    cognition_docs = [
        {
            "path": r["path"],
            "month": r["derived_time_month"] or r["time_month"] or "未知",
            "summary": r["summary"] or "",
            "confidence": r["confidence"],
        }
        for r in rows
        if r["include_in_kb"] == 1 and r["contains_cognition_change"] == 1
    ][:50]

    writing_docs = [
        {
            "path": r["path"],
            "month": r["derived_time_month"] or r["time_month"] or "未知",
            "writing_potential": r["writing_potential"] or "",
            "summary": r["summary"] or "",
            "confidence": r["confidence"],
        }
        for r in rows
        if r["include_in_kb"] == 1 and r["contains_writing_potential"] == 1
    ]
    # sort writing potential heuristic: 高>中>低
    rank = {"高": 3, "中": 2, "低": 1}
    writing_docs.sort(key=lambda x: (rank.get(x["writing_potential"], 0), x["confidence"]), reverse=True)
    writing_docs = writing_docs[:50]

    # project ideas
    project_docs = []
    project_tag_counter = Counter()
    for r in rows:
        if r["include_in_kb"] != 1 or r["contains_project_idea"] != 1:
            continue
        tags = []
        if r["topic_tags"]:
            try:
                import json

                tags = json.loads(r["topic_tags"]) or []
            except Exception:
                tags = []
        for t in tags:
            if isinstance(t, str) and t.strip():
                project_tag_counter[t.strip()] += 1
        project_docs.append(
            {
                "path": r["path"],
                "month": r["derived_time_month"] or r["time_month"] or "未知",
                "summary": r["summary"] or "",
                "confidence": r["confidence"],
            }
        )
    project_docs = project_docs[:80]

    low_conf = [
        {
            "path": r["path"],
            "month": r["derived_time_month"] or r["time_month"] or "未知",
            "confidence": r["confidence"],
            "needs_review": r["needs_review"],
            "summary": r["summary"] or "",
        }
        for r in rows
        if r["include_in_kb"] == 1
        and (((r["confidence"] is not None) and float(r["confidence"]) < 0.75) or r["needs_review"] == 1)
    ][:80]

    tpl_path = Path(__file__).parent / "templates" / "dashboard.html.j2"
    tpl = Template(tpl_path.read_text(encoding="utf-8"))

    html = tpl.render(
        total=total,
        included=included,
        excluded=excluded,
        review=review,
        by_month=by_month.most_common(),
        by_cat=by_cat.most_common(),
        months=months,
        cats=cats,
        heat=heat,
        trade_trend=sorted(trade_trend.items()),
        emotion_by_month={k: v.most_common(10) for k, v in emotion_by_month.items()},
        cognition_docs=cognition_docs,
        writing_docs=writing_docs,
        project_docs=project_docs,
        project_tags=project_tag_counter.most_common(20),
        low_conf=low_conf,
        review_link="review.html",
        search_link="search.html",
        report_link="../reports/" + cfg.get("report", {}).get("default_quarter", "2026-Q2") + "-report.md",
    )

    out_path = os.path.join(out_dir, "index.html")
    Path(out_path).write_text(html, encoding="utf-8")

    search_page = os.path.join(out_dir, "search.html")
    Path(search_page).write_text(
        """
<!doctype html>
<html lang=\"zh-cn\">
<head><meta charset=\"utf-8\"><title>Search Guide</title></head>
<body>
<h1>检索入口</h1>
<p>CLI 检索命令：python main.py search --config config.yaml --query \"止损 执行力\"</p>
<p>本地 API 检索：GET /search?q=止损 执行力</p>
</body>
</html>
        """.strip(),
        encoding="utf-8",
    )
    return out_path
