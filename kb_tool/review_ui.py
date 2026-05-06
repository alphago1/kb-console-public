from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

from jinja2 import Template


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def build_review_artifacts(cfg: dict, confidence_threshold: float = 0.75) -> dict:
    dashboard_dir = cfg["storage"]["dashboard_dir"]
    exports_dir = cfg["storage"]["exports_dir"]
    Path(dashboard_dir).mkdir(parents=True, exist_ok=True)
    Path(exports_dir).mkdir(parents=True, exist_ok=True)

    sqlite_path = cfg["storage"]["sqlite_path"]
    with _connect(sqlite_path) as con:
        rows = con.execute(
            """
            SELECT rowid AS doc_id, *
            FROM documents
            WHERE include_in_kb = 1
              AND (needs_review = 1 OR confidence < ?)
            ORDER BY COALESCE(derived_time_month, time_month, '') DESC, confidence ASC
            """,
            (confidence_threshold,),
        ).fetchall()

    review_rows: list[dict] = []
    for r in rows:
        topic_tags = []
        if r["topic_tags"]:
            try:
                topic_tags = json.loads(r["topic_tags"]) or []
            except Exception:
                pass
        review_rows.append(
            {
                "doc_id": r["doc_id"],
                "month": r["derived_time_month"] or r["time_month"] or "未知",
                "path": r["path"],
                "summary": r["summary"] or "",
                "primary_category": r["primary_category"] or "",
                "secondary_category": r["secondary_category"] or "",
                "topic_tags": ", ".join(topic_tags),
                "confidence": r["confidence"] or 0,
                "needs_review": r["needs_review"],
            }
        )

    # HTML
    html_tpl = Template(
        """
<!doctype html>
<html lang=\"zh-cn\"> 
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Review Queue</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, \"Microsoft YaHei\", Arial, sans-serif; margin: 24px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 6px 8px; font-size: 12px; vertical-align: top; }
    th { background: #f6f6f6; text-align: left; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  </style>
</head>
<body>
  <h1>待复核文档队列</h1>
  <p>筛选条件：needs_review=true 或 confidence < {{ threshold }}。可在 review_updates.csv 填写修正后，执行：python main.py apply-review --config config.yaml --file review_updates.csv</p>
  <table>
    <tr>
      <th>ID</th><th>月份</th><th>置信度</th><th>分类</th><th>标签</th><th>摘要</th><th>路径</th>
    </tr>
    {% for d in docs %}
    <tr>
      <td>{{ d.doc_id }}</td>
      <td>{{ d.month }}</td>
      <td>{{ '%.2f'|format(d.confidence) }}</td>
      <td>{{ d.primary_category }} / {{ d.secondary_category }}</td>
      <td>{{ d.topic_tags }}</td>
      <td>{{ d.summary }}</td>
      <td class=\"mono\">{{ d.path }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
        """.strip()
    )
    review_html = os.path.join(dashboard_dir, "review.html")
    Path(review_html).write_text(html_tpl.render(docs=review_rows, threshold=confidence_threshold), encoding="utf-8")

    # CSV template
    review_csv = os.path.join(exports_dir, "review_updates.csv")
    with open(review_csv, "w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "doc_id",
            "path",
            "current_primary_category",
            "current_secondary_category",
            "current_topic_tags",
            "current_confidence",
            "corrected_include_in_kb",
            "corrected_primary_category",
            "corrected_secondary_category",
            "corrected_topic_tags",
            "corrected_emotion_tags",
            "corrected_summary",
            "corrected_confidence",
            "corrected_needs_review",
            "corrected_exclude_reason",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for d in review_rows:
            w.writerow(
                {
                    "doc_id": d["doc_id"],
                    "path": d["path"],
                    "current_primary_category": d["primary_category"],
                    "current_secondary_category": d["secondary_category"],
                    "current_topic_tags": d["topic_tags"],
                    "current_confidence": d["confidence"],
                }
            )

    return {"review_html": review_html, "review_updates_csv": review_csv, "count": len(review_rows)}


def apply_review_updates(cfg: dict, csv_file: str) -> dict:
    from tag_normalizer import normalize_emotion_tags, normalize_topic_tags

    sqlite_path = cfg["storage"]["sqlite_path"]
    updated = 0
    skipped = 0

    def parse_bool(v: str):
        if v is None:
            return None
        t = v.strip().lower()
        if t in {"", "na", "null"}:
            return None
        if t in {"1", "true", "yes", "y", "是"}:
            return 1
        if t in {"0", "false", "no", "n", "否"}:
            return 0
        return None

    def parse_tags(v: str, kind: str) -> str | None:
        if v is None or not v.strip():
            return None
        raw = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
        norm = normalize_emotion_tags(raw) if kind == "emotion" else normalize_topic_tags(raw)
        return json.dumps(norm, ensure_ascii=False)

    with open(csv_file, "r", encoding="utf-8-sig", newline="") as f, sqlite3.connect(sqlite_path) as con:
        con.row_factory = sqlite3.Row
        reader = csv.DictReader(f)
        for row in reader:
            path = (row.get("path") or "").strip()
            if not path:
                skipped += 1
                continue

            updates = {}
            if row.get("corrected_primary_category", "").strip():
                updates["primary_category"] = row["corrected_primary_category"].strip()
            if row.get("corrected_secondary_category", "").strip():
                updates["secondary_category"] = row["corrected_secondary_category"].strip()

            ttags = parse_tags(row.get("corrected_topic_tags", ""), "topic")
            if ttags is not None:
                updates["topic_tags"] = ttags

            etags = parse_tags(row.get("corrected_emotion_tags", ""), "emotion")
            if etags is not None:
                updates["emotion_tags"] = etags

            if row.get("corrected_summary", "").strip():
                updates["summary"] = row["corrected_summary"].strip()

            cb = parse_bool(row.get("corrected_include_in_kb", ""))
            if cb is not None:
                updates["include_in_kb"] = cb

            cr = parse_bool(row.get("corrected_needs_review", ""))
            if cr is not None:
                updates["needs_review"] = cr

            if row.get("corrected_exclude_reason", "").strip():
                updates["exclude_reason"] = row["corrected_exclude_reason"].strip()

            if row.get("corrected_confidence", "").strip():
                try:
                    updates["confidence"] = float(row["corrected_confidence"].strip())
                except Exception:
                    pass

            if not updates:
                skipped += 1
                continue

            sets = ", ".join([f"{k}=?" for k in updates.keys()])
            values = list(updates.values()) + [path]
            con.execute(f"UPDATE documents SET {sets}, processed_at=datetime('now') WHERE path=?", values)
            updated += 1

        con.commit()

    return {"updated": updated, "skipped": skipped, "file": csv_file}
