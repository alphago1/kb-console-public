from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from classifier_rules import apply_rules
from extractor import extract_text
from models import FileRecord, LLMResult
from sampler import sample_text
from tag_normalizer import normalize_emotion_tags, normalize_topic_tags
from utils.time_utils import derive_time_month


class KBDatabase:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sqlite_path = cfg["storage"]["sqlite_path"]
        Path(os.path.dirname(self.sqlite_path)).mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.sqlite_path)
        con.row_factory = sqlite3.Row
        return con

    def init(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                  path TEXT PRIMARY KEY,
                  source_path TEXT,
                  docs_path TEXT,
                  text_cache_path TEXT,
                  filename TEXT,
                  extension TEXT,
                  size_bytes INTEGER,
                  filesystem_created_time TEXT,
                  filesystem_modified_time TEXT,
                  document_created_time TEXT,
                  document_modified_time TEXT,
                  derived_time_month TEXT,
                  time_source TEXT,

                  fingerprint_size INTEGER,
                  fingerprint_mtime REAL,
                  fingerprint_sha256 TEXT,

                  extracted_char_count INTEGER,
                  extract_error TEXT,
                  sampled_text TEXT,
                  sampled_char_count INTEGER,

                  llm_json TEXT,
                  include_in_kb INTEGER,
                  exclude_reason TEXT,
                  primary_category TEXT,
                  secondary_category TEXT,
                  topic_tags TEXT,
                  source_type TEXT,
                  time_year INTEGER,
                  time_month TEXT,
                  emotion_tags TEXT,
                  cognition_dimensions TEXT,
                  contains_trade_data INTEGER,
                  contains_reflection INTEGER,
                  contains_cognition_change INTEGER,
                  contains_project_idea INTEGER,
                  contains_writing_potential INTEGER,
                  contains_emotion INTEGER,
                  writing_potential TEXT,
                  summary TEXT,
                  cognition_snapshot TEXT,
                  confidence REAL,
                  needs_more_text INTEGER,
                  needs_review INTEGER,
                  recurrence_signal INTEGER,
                  reason TEXT,

                  run_id TEXT,
                  processed_at TEXT
                );
                """
            )
            self._ensure_optional_columns(con)

    def _ensure_optional_columns(self, con: sqlite3.Connection) -> None:
        cols = {r[1] for r in con.execute("PRAGMA table_info(documents)").fetchall()}
        if "source_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN source_path TEXT")
        if "docs_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN docs_path TEXT")
        if "text_cache_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN text_cache_path TEXT")
        # Backfill docs_path for old rows so docs becomes first-class path alias.
        con.execute("UPDATE documents SET docs_path=path WHERE docs_path IS NULL OR docs_path='' ")

    def _get_fingerprint(self, path: str) -> tuple[int, float]:
        st = os.stat(path)
        return int(st.st_size), float(st.st_mtime)

    def _sha256_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def is_unchanged(self, fr: FileRecord) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT fingerprint_size, fingerprint_mtime FROM documents WHERE path = ?",
                (fr.path,),
            ).fetchone()
            if not row:
                return False
            if not fr.filesystem_modified_time:
                return False
            return int(row["fingerprint_size"] or -1) == fr.size_bytes and float(row["fingerprint_mtime"] or -1) == float(fr.filesystem_modified_time.timestamp())

    def process_file(self, fr: FileRecord, run_id: str, allowed_categories: Optional[list[str]] = None) -> bool:
        # returns True if processed (new/changed), False if skipped unchanged
        size, mtime = self._get_fingerprint(fr.path)
        fr.size_bytes = size

        if self.is_unchanged(fr):
            return False

        decision = apply_rules(self.cfg, fr.filename, fr.path)

        text, doc_created, doc_modified, err = extract_text(self.cfg, fr.path, fr.extension)
        fr.document_created_time = doc_created
        fr.document_modified_time = doc_modified

        # derive time month (needs document times)
        dt = derive_time_month(
            fr.filename,
            fr.filesystem_created_time,
            fr.filesystem_modified_time,
            fr.document_created_time,
            fr.document_modified_time,
        )
        fr.derived_time_month = dt.derived_time_month
        fr.time_source = dt.time_source

        extracted_len = len(text) if text else 0

        sampled = ""
        sampled_len = 0
        llm_result: Optional[LLMResult] = None
        llm_json: Optional[str] = None

        include_in_kb = None
        exclude_reason = None
        needs_review = False

        if err:
            include_in_kb = 0
            exclude_reason = "无法读取文件"
            needs_review = True
        else:
            # if rule says exclude, skip LLM
            if decision and decision.include_in_kb is False:
                include_in_kb = 0
                exclude_reason = decision.exclude_reason
                needs_review = decision.needs_review
            else:
                # sample and call LLM
                from llm_classifier import classify_with_llm

                sampled_obj = sample_text(self.cfg, text or "", seed=fr.path, deep=False)
                sampled = sampled_obj.sampled_text
                sampled_len = sampled_obj.sampled_char_count

                llm_result = classify_with_llm(
                    self.cfg,
                    filename=fr.filename,
                    path=fr.path,
                    extension=fr.extension,
                    size=fr.size_bytes,
                    created_time=fr.filesystem_created_time,
                    modified_time=fr.filesystem_modified_time,
                    document_created_time=fr.document_created_time,
                    sampled_text=sampled,
                    allowed_categories=allowed_categories,
                )

                # deep read on low confidence
                thr = float(self.cfg["sampler"].get("confidence_threshold", 0.75))
                if llm_result.needs_more_text or llm_result.confidence < thr:
                    deep_sample = sample_text(self.cfg, text or "", seed=fr.path, deep=True)
                    llm_result = classify_with_llm(
                        self.cfg,
                        filename=fr.filename,
                        path=fr.path,
                        extension=fr.extension,
                        size=fr.size_bytes,
                        created_time=fr.filesystem_created_time,
                        modified_time=fr.filesystem_modified_time,
                        document_created_time=fr.document_created_time,
                        sampled_text=deep_sample.sampled_text,
                        allowed_categories=allowed_categories,
                    )
                    sampled = deep_sample.sampled_text
                    sampled_len = deep_sample.sampled_char_count

                include_in_kb = 1 if llm_result.include_in_kb else 0
                exclude_reason = llm_result.exclude_reason
                needs_review = bool(llm_result.needs_review) or (decision.needs_review if decision else False)

                llm_json = json.dumps(llm_result.model_dump(mode="json"), ensure_ascii=False)

        processed_at = datetime.now().isoformat(timespec="seconds")

        with self._connect() as con:
            con.execute(
                """
                INSERT INTO documents(
                  path, filename, extension, size_bytes,
                  filesystem_created_time, filesystem_modified_time,
                  document_created_time, document_modified_time,
                  derived_time_month, time_source,
                  fingerprint_size, fingerprint_mtime, fingerprint_sha256,
                  extracted_char_count, extract_error,
                  sampled_text, sampled_char_count,
                  llm_json, include_in_kb, exclude_reason,
                  primary_category, secondary_category, topic_tags, source_type,
                  time_year, time_month, emotion_tags, cognition_dimensions,
                  contains_trade_data, contains_reflection, contains_cognition_change,
                  contains_project_idea, contains_writing_potential, contains_emotion,
                  writing_potential, summary, cognition_snapshot,
                  confidence, needs_more_text, needs_review,
                  recurrence_signal, reason,
                  run_id, processed_at
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                  filename=excluded.filename,
                  extension=excluded.extension,
                  size_bytes=excluded.size_bytes,
                  filesystem_created_time=excluded.filesystem_created_time,
                  filesystem_modified_time=excluded.filesystem_modified_time,
                  document_created_time=excluded.document_created_time,
                  document_modified_time=excluded.document_modified_time,
                  derived_time_month=excluded.derived_time_month,
                  time_source=excluded.time_source,
                  fingerprint_size=excluded.fingerprint_size,
                  fingerprint_mtime=excluded.fingerprint_mtime,
                  fingerprint_sha256=excluded.fingerprint_sha256,
                  extracted_char_count=excluded.extracted_char_count,
                  extract_error=excluded.extract_error,
                  sampled_text=excluded.sampled_text,
                  sampled_char_count=excluded.sampled_char_count,
                  llm_json=excluded.llm_json,
                  include_in_kb=excluded.include_in_kb,
                  exclude_reason=excluded.exclude_reason,
                  primary_category=excluded.primary_category,
                  secondary_category=excluded.secondary_category,
                  topic_tags=excluded.topic_tags,
                  source_type=excluded.source_type,
                  time_year=excluded.time_year,
                  time_month=excluded.time_month,
                  emotion_tags=excluded.emotion_tags,
                  cognition_dimensions=excluded.cognition_dimensions,
                  contains_trade_data=excluded.contains_trade_data,
                  contains_reflection=excluded.contains_reflection,
                  contains_cognition_change=excluded.contains_cognition_change,
                  contains_project_idea=excluded.contains_project_idea,
                  contains_writing_potential=excluded.contains_writing_potential,
                  contains_emotion=excluded.contains_emotion,
                  writing_potential=excluded.writing_potential,
                  summary=excluded.summary,
                  cognition_snapshot=excluded.cognition_snapshot,
                  confidence=excluded.confidence,
                  needs_more_text=excluded.needs_more_text,
                  needs_review=excluded.needs_review,
                  recurrence_signal=excluded.recurrence_signal,
                  reason=excluded.reason,
                  run_id=excluded.run_id,
                  processed_at=excluded.processed_at
                """,
                self._row_values(fr, mtime, llm_result, llm_json, include_in_kb, exclude_reason, needs_review, err, extracted_len, sampled, sampled_len, text or "", run_id, processed_at),
            )

        return True

    def _row_values(
        self,
        fr: FileRecord,
        mtime: float,
        llm_result: Optional[LLMResult],
        llm_json: Optional[str],
        include_in_kb: int,
        exclude_reason: Optional[str],
        needs_review: bool,
        extract_error: Optional[str],
        extracted_len: int,
        sampled: str,
        sampled_len: int,
        full_text: str,
        run_id: str,
        processed_at: str,
    ) -> tuple[Any, ...]:
        def dt(v: Optional[datetime]) -> Optional[str]:
            return v.isoformat(timespec="seconds") if v else None

        # flatten llm
        def jlist(v):
            if v is None:
                return None
            return json.dumps(v, ensure_ascii=False)

        primary_category = llm_result.primary_category if llm_result else None
        secondary_category = llm_result.secondary_category if llm_result else None
        norm_topic_tags = normalize_topic_tags(llm_result.topic_tags if llm_result else [])
        topic_tags = jlist(norm_topic_tags) if llm_result else None
        source_type = llm_result.source_type if llm_result else None
        time_year = llm_result.time_year if llm_result else None
        time_month = llm_result.time_month if llm_result else None
        norm_emotion_tags = normalize_emotion_tags(llm_result.emotion_tags if llm_result else [])
        emotion_tags = jlist(norm_emotion_tags) if llm_result else None
        cognition_dimensions = jlist(llm_result.cognition_dimensions) if llm_result else None

        contains_trade_data = int(bool(llm_result.contains_trade_data)) if llm_result else 0
        contains_reflection = int(bool(llm_result.contains_reflection)) if llm_result else 0
        contains_cognition_change = int(bool(llm_result.contains_cognition_change)) if llm_result else 0
        contains_project_idea = int(bool(llm_result.contains_project_idea)) if llm_result else 0
        contains_writing_potential = int(bool(llm_result.contains_writing_potential)) if llm_result else 0
        contains_emotion = int(bool(llm_result.contains_emotion)) if (llm_result and llm_result.contains_emotion is not None) else None

        writing_potential = llm_result.writing_potential if llm_result else None
        summary = llm_result.summary if llm_result else None
        cognition_snapshot = jlist(llm_result.cognition_snapshot) if llm_result else None

        confidence = float(llm_result.confidence) if llm_result else 0.0
        needs_more_text = int(bool(llm_result.needs_more_text)) if llm_result else 0

        recurrence_signal = int(bool(llm_result.recurrence_signal)) if (llm_result and llm_result.recurrence_signal is not None) else None
        reason = llm_result.reason if llm_result else None

        fingerprint_sha256 = self._sha256_text(full_text) if full_text else None

        return (
            fr.path,
            fr.filename,
            fr.extension,
            fr.size_bytes,
            dt(fr.filesystem_created_time),
            dt(fr.filesystem_modified_time),
            dt(fr.document_created_time),
            dt(fr.document_modified_time),
            fr.derived_time_month,
            fr.time_source,
            fr.size_bytes,
            float(fr.filesystem_modified_time.timestamp()) if fr.filesystem_modified_time else mtime,
            fingerprint_sha256,
            extracted_len,
            extract_error,
            sampled,
            sampled_len,
            llm_json,
            include_in_kb,
            exclude_reason,
            primary_category,
            secondary_category,
            topic_tags,
            source_type,
            time_year,
            time_month,
            emotion_tags,
            cognition_dimensions,
            contains_trade_data,
            contains_reflection,
            contains_cognition_change,
            contains_project_idea,
            contains_writing_potential,
            contains_emotion,
            writing_potential,
            summary,
            cognition_snapshot,
            confidence,
            needs_more_text,
            int(bool(needs_review)),
            recurrence_signal,
            reason,
            run_id,
            processed_at,
        )

    def export_all(self) -> dict:
        exports_dir = self.cfg["storage"]["exports_dir"]
        Path(exports_dir).mkdir(parents=True, exist_ok=True)
        csv_path = os.path.join(exports_dir, "documents.csv")
        json_path = os.path.join(exports_dir, "documents.json")

        with self._connect() as con:
            rows = con.execute("SELECT * FROM documents").fetchall()

        # json
        docs = [dict(r) for r in rows]
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

        # csv
        if docs:
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(docs[0].keys()))
                w.writeheader()
                w.writerows(docs)

        return {"csv": csv_path, "json": json_path}
