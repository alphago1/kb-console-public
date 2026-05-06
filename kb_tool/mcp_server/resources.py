from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def list_resources(cfg: dict) -> list[dict]:
    return [
        {"uri": "kb://dashboard/summary", "title": "Dashboard Summary", "mimeType": "text/markdown"},
        {"uri": "kb://months/{YYYY-MM}", "title": "Monthly Summary", "mimeType": "text/markdown"},
        {"uri": "kb://documents/{document_id}", "title": "Document Detail", "mimeType": "application/json"},
        {"uri": "kb://categories/{category}", "title": "Category Summary", "mimeType": "application/json"},
        {"uri": "kb://reports/{report_id}", "title": "Report Content", "mimeType": "text/markdown"},
    ]


def read_resource(cfg: dict, uri: str) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    reports_dir = Path(cfg["storage"]["reports_dir"])

    if uri == "kb://dashboard/summary":
        with _connect(sqlite_path) as con:
            total = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            included = con.execute("SELECT COUNT(*) FROM documents WHERE include_in_kb=1").fetchone()[0]
            review = con.execute("SELECT COUNT(*) FROM documents WHERE needs_review=1").fetchone()[0]
        text = f"# Dashboard Summary\\n\\n- total: {total}\\n- included: {included}\\n- needs_review: {review}\\n"
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    if uri.startswith("kb://months/"):
        month = uri.split("kb://months/", 1)[1]
        with _connect(sqlite_path) as con:
            rows = con.execute(
                "SELECT primary_category, count(*) AS n FROM documents WHERE include_in_kb=1 AND COALESCE(derived_time_month,time_month)=? GROUP BY primary_category",
                (month,),
            ).fetchall()
        text = "# " + month + " 月度摘要\\n\\n" + "\\n".join([f"- {r['primary_category'] or '未知'}: {r['n']}" for r in rows])
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    if uri.startswith("kb://documents/"):
        doc_id = int(uri.split("kb://documents/", 1)[1])
        with _connect(sqlite_path) as con:
            row = con.execute("SELECT rowid AS document_id, filename, path, summary, primary_category, confidence FROM documents WHERE rowid=?", (doc_id,)).fetchone()
        if not row:
            return {"uri": uri, "mimeType": "application/json", "text": json.dumps({"error": "not found"}, ensure_ascii=False)}
        d = dict(row)
        d["path"] = "[KB_ROOT]/" + (d["filename"] or str(d["document_id"]))
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(d, ensure_ascii=False)}

    if uri.startswith("kb://categories/"):
        cat = uri.split("kb://categories/", 1)[1]
        with _connect(sqlite_path) as con:
            rows = con.execute(
                "SELECT rowid AS document_id, filename, COALESCE(derived_time_month,time_month) AS month, confidence FROM documents WHERE include_in_kb=1 AND primary_category=? ORDER BY confidence DESC LIMIT 50",
                (cat,),
            ).fetchall()
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps([dict(r) for r in rows], ensure_ascii=False)}

    if uri.startswith("kb://reports/"):
        rid = uri.split("kb://reports/", 1)[1]
        target = reports_dir / rid
        if not target.exists():
            return {"uri": uri, "mimeType": "text/markdown", "text": "# report not found"}
        return {"uri": uri, "mimeType": "text/markdown", "text": target.read_text(encoding="utf-8", errors="ignore")}

    return {"uri": uri, "mimeType": "application/json", "text": json.dumps({"error": "unsupported uri"}, ensure_ascii=False)}
