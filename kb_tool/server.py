from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from chunker import ensure_chunk_tables, search_chunks


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def create_app(cfg: dict) -> FastAPI:
    app = FastAPI(title="Personal KB API", version="0.2")
    sqlite_path = cfg["storage"]["sqlite_path"]

    @app.get("/search")
    def search(q: str = Query(..., min_length=1), limit: int = 20):
        ensure_chunk_tables(sqlite_path)
        return {"query": q, "results": search_chunks(cfg, q, limit=limit)}

    @app.get("/document/{doc_id}")
    def get_document(doc_id: int):
        with _connect(sqlite_path) as con:
            row = con.execute("SELECT rowid AS id, * FROM documents WHERE rowid=?", (doc_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="document not found")
            data = dict(row)
            for k in ("topic_tags", "emotion_tags", "cognition_dimensions", "cognition_snapshot"):
                if data.get(k):
                    try:
                        data[k] = json.loads(data[k])
                    except Exception:
                        pass
            return data

    @app.get("/summary/month/{month}")
    def summary_month(month: str):
        with _connect(sqlite_path) as con:
            rows = con.execute(
                "SELECT primary_category, count(*) AS n FROM documents WHERE include_in_kb=1 AND COALESCE(derived_time_month, time_month)=? GROUP BY primary_category",
                (month,),
            ).fetchall()
            return {"month": month, "categories": [dict(r) for r in rows]}

    @app.get("/compare")
    def compare(start: str, end: str, topic: str):
        like = f"%{topic}%"
        with _connect(sqlite_path) as con:
            rows = con.execute(
                """
                SELECT COALESCE(derived_time_month, time_month) AS month, count(*) AS n
                FROM documents
                WHERE include_in_kb=1
                  AND COALESCE(derived_time_month, time_month) >= ?
                  AND COALESCE(derived_time_month, time_month) <= ?
                  AND (primary_category LIKE ? OR summary LIKE ? OR topic_tags LIKE ?)
                GROUP BY month
                ORDER BY month
                """,
                (start, end, like, like, like),
            ).fetchall()
            return {"start": start, "end": end, "topic": topic, "series": [dict(r) for r in rows]}

    @app.get("/writing-candidates")
    def writing_candidates(limit: int = 50):
        with _connect(sqlite_path) as con:
            rows = con.execute(
                """
                SELECT rowid AS id, path, COALESCE(derived_time_month, time_month) AS month, writing_potential, confidence, summary
                FROM documents
                WHERE include_in_kb=1 AND contains_writing_potential=1
                ORDER BY CASE writing_potential WHEN '高' THEN 3 WHEN '中' THEN 2 ELSE 1 END DESC, confidence DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/project-ideas")
    def project_ideas(limit: int = 80):
        with _connect(sqlite_path) as con:
            rows = con.execute(
                """
                SELECT rowid AS id, path, COALESCE(derived_time_month, time_month) AS month, confidence, summary, topic_tags
                FROM documents
                WHERE include_in_kb=1 AND contains_project_idea=1
                ORDER BY confidence DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            if d.get("topic_tags"):
                try:
                    d["topic_tags"] = json.loads(d["topic_tags"])
                except Exception:
                    pass
            items.append(d)
        return {"items": items}

    return app
