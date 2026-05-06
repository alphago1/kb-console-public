from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from extractor import extract_text


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _split_chunks(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        out.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return out


def ensure_chunk_tables(sqlite_path: str) -> None:
    with _connect(sqlite_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
              chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
              path TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              chunk_text TEXT NOT NULL,
              derived_time_month TEXT,
              primary_category TEXT,
              topic_tags TEXT,
              UNIQUE(path, chunk_index)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON document_chunks(path)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_month ON document_chunks(derived_time_month)")
        con.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts
            USING fts5(chunk_text, path UNINDEXED, chunk_id UNINDEXED)
            """
        )


def build_chunks(cfg: dict, rebuild: bool = False) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    ensure_chunk_tables(sqlite_path)

    with _connect(sqlite_path) as con:
        docs = con.execute(
            """
            SELECT COALESCE(docs_path, path) AS docs_path, extension, derived_time_month, primary_category, topic_tags
            FROM documents
            WHERE include_in_kb = 1
            """
        ).fetchall()

        if rebuild:
            con.execute("DELETE FROM document_chunks")
            con.execute("DELETE FROM document_chunks_fts")

        chunked_docs = 0
        inserted_chunks = 0

        for d in docs:
            path = d["docs_path"]
            ext = d["extension"]

            if not rebuild:
                existing = con.execute("SELECT 1 FROM document_chunks WHERE path=? LIMIT 1", (path,)).fetchone()
                if existing:
                    continue

            text, _, _, err = None, None, None, None
            if Path(path).exists():
                text, _, _, err = extract_text(cfg, path, ext)
            if err or not text:
                continue

            chunks = _split_chunks(text)
            if not chunks:
                continue

            con.execute("DELETE FROM document_chunks WHERE path=?", (path,))
            con.execute("DELETE FROM document_chunks_fts WHERE path=?", (path,))

            for idx, ch in enumerate(chunks):
                con.execute(
                    """
                    INSERT INTO document_chunks(path, chunk_index, chunk_text, derived_time_month, primary_category, topic_tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (path, idx, ch, d["derived_time_month"], d["primary_category"], d["topic_tags"]),
                )
                rowid = con.execute("SELECT chunk_id FROM document_chunks WHERE path=? AND chunk_index=?", (path, idx)).fetchone()[0]
                con.execute(
                    "INSERT INTO document_chunks_fts(rowid, chunk_text, path, chunk_id) VALUES (?, ?, ?, ?)",
                    (rowid, ch, path, rowid),
                )
                inserted_chunks += 1
            chunked_docs += 1

        con.commit()

    return {"documents_chunked": chunked_docs, "chunks_inserted": inserted_chunks}


def search_chunks(cfg: dict, query: str, limit: int = 20) -> list[dict]:
    sqlite_path = cfg["storage"]["sqlite_path"]
    ensure_chunk_tables(sqlite_path)

    with _connect(sqlite_path) as con:
        rows = con.execute(
            """
            SELECT c.chunk_id, c.path, c.chunk_index, c.derived_time_month, c.primary_category,
                   snippet(document_chunks_fts, 0, '[', ']', ' ... ', 12) AS snippet,
                   bm25(document_chunks_fts) AS score
            FROM document_chunks_fts
            JOIN document_chunks c ON c.chunk_id = document_chunks_fts.rowid
            WHERE document_chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()

    return [dict(r) for r in rows]
