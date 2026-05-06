from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*]')
_WHITESPACE = re.compile(r"\s+")


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _sanitize_segment(seg: str, fallback: str) -> str:
    seg = (seg or "").strip()
    if not seg:
        return fallback
    seg = _INVALID_WIN_CHARS.sub("_", seg)
    seg = _WHITESPACE.sub(" ", seg).strip()
    seg = seg.rstrip(". ")
    return seg or fallback


def _safe_stem(filename: str, max_len: int = 80) -> str:
    stem = Path(filename).stem if filename else "file"
    stem = _INVALID_WIN_CHARS.sub("_", stem)
    stem = _WHITESPACE.sub(" ", stem).strip()
    stem = stem.rstrip(". ")
    if not stem:
        stem = "file"
    if len(stem) > max_len:
        stem = stem[:max_len].rstrip(". ")
    return stem


def _ensure_dot_ext(ext: str) -> str:
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


@dataclass(frozen=True)
class PathMapping:
    old_path: str
    new_path: str


def migrate_docs(
    cfg: dict,
    docs_root: str | None = None,
    include_excluded: bool = True,
    dry_run: bool = False,
) -> dict:
    """Copy KB source files into a workspace-local docs folder and rewrite paths in SQLite.

    Classification:
      docs/<primary_category>/<derived_time_month>/<safe_filename>_<sha8><ext>

    Updates path in:
      - documents.path (PK)
      - document_chunks.path
      - document_chunks_fts.path

    Returns a stats dict.
    """

    sqlite_path = cfg["storage"]["sqlite_path"]

    if docs_root is None:
        # kb_tool/main.py is under kb_tool/, so workspace root is parent of that.
        workspace_root = Path(__file__).resolve().parents[1]
        docs_root_path = workspace_root / "docs"
    else:
        docs_root_path = Path(docs_root)

    docs_root_path.mkdir(parents=True, exist_ok=True)

    stats = {
        "sqlite_path": str(Path(sqlite_path).resolve()),
        "docs_root": str(docs_root_path.resolve()),
        "dry_run": dry_run,
        "include_excluded": include_excluded,
        "documents_seen": 0,
        "documents_copied": 0,
        "documents_missing_source": 0,
        "documents_skipped_existing": 0,
        "documents_path_updated": 0,
        "chunks_path_updated": 0,
        "fts_path_updated": 0,
        "errors": 0,
    }

    mappings: list[PathMapping] = []

    with _connect(sqlite_path) as con:
        rows = con.execute(
            """
            SELECT path, filename, extension, include_in_kb, primary_category, derived_time_month, fingerprint_sha256
            FROM documents
            """
        ).fetchall()

        for r in rows:
            stats["documents_seen"] += 1
            old_path = r["path"]
            include_in_kb = int(r["include_in_kb"] or 0)

            if (not include_excluded) and include_in_kb != 1:
                continue

            primary_category = r["primary_category"]
            derived_month = r["derived_time_month"]
            filename = r["filename"] or (Path(old_path).name if old_path else "")
            ext = r["extension"] or Path(filename).suffix
            ext = _ensure_dot_ext(ext)

            cat_seg = _sanitize_segment(primary_category, fallback=("_excluded" if include_in_kb != 1 else "_uncategorized"))
            month_seg = _sanitize_segment(derived_month, fallback="_unknown_month")

            sha = (r["fingerprint_sha256"] or "")
            sha8 = sha[:8] if sha else ""
            stem = _safe_stem(filename)

            suffix = f"_{sha8}" if sha8 else ""
            dest_dir = docs_root_path / cat_seg / month_seg
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / f"{stem}{suffix}{ext}"

            try:
                if not old_path or not os.path.exists(old_path):
                    stats["documents_missing_source"] += 1
                    continue

                if dest_path.exists():
                    stats["documents_skipped_existing"] += 1
                else:
                    if not dry_run:
                        shutil.copy2(old_path, dest_path)
                    stats["documents_copied"] += 1

                mappings.append(PathMapping(old_path=old_path, new_path=str(dest_path)))
            except Exception as e:
                stats["errors"] += 1
                logging.exception("docs migrate failed old=%s new=%s err=%s", old_path, dest_path, e)

    if dry_run:
        stats["mappings_preview"] = [{"old": m.old_path, "new": m.new_path} for m in mappings[:10]]
        return stats

    # Apply DB updates in a single transaction.
    with _connect(sqlite_path) as con:
        con.execute("BEGIN")
        try:
            for m in mappings:
                cur = con.execute("UPDATE documents SET path=? WHERE path=?", (m.new_path, m.old_path))
                stats["documents_path_updated"] += int(cur.rowcount or 0)

                cur = con.execute("UPDATE document_chunks SET path=? WHERE path=?", (m.new_path, m.old_path))
                stats["chunks_path_updated"] += int(cur.rowcount or 0)

                # FTS5 table stores path as an unindexed column
                try:
                    cur = con.execute("UPDATE document_chunks_fts SET path=? WHERE path=?", (m.new_path, m.old_path))
                    stats["fts_path_updated"] += int(cur.rowcount or 0)
                except sqlite3.OperationalError:
                    # table might not exist yet
                    pass

            con.commit()
        except Exception as e:
            con.rollback()
            stats["errors"] += 1
            logging.exception("docs migrate DB update failed: %s", e)

    return stats
