from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _time_stratum(month_str: str | None) -> str:
    if not month_str:
        return "unknown"
    now = datetime.now()
    try:
        parts = month_str.split("-")
        y, m = int(parts[0]), int(parts[1])
        dt = datetime(y, m, 1)
        if dt >= now - timedelta(days=30):
            return "最近1个月"
        if dt >= now - timedelta(days=90):
            return "最近3个月"
        if y == now.year:
            return "今年"
        return "去年或更早"
    except (ValueError, IndexError):
        return "unknown"


def _size_stratum(size_bytes: int | None) -> str:
    if not size_bytes or size_bytes <= 0:
        return "短文件"
    if size_bytes < 10_000:
        return "短文件"
    if size_bytes < 100_000:
        return "中等文件"
    if size_bytes < 1_000_000:
        return "长文件"
    return "超长文件"


def _type_stratum(extension: str, source_type: str) -> str:
    ext = (extension or "").lower()
    if "转写" in str(source_type) or "录音" in str(source_type):
        return "转写稿"
    if ext in (".docx", ".doc"):
        return ext
    if ext == ".md":
        return ".md"
    if ext == ".txt":
        return ".txt"
    return f"other_{ext}"


def _dir_stratum(category: str | None) -> str:
    return category or "未分类"


def _use_stratum(category: str | None, tags: str | None) -> str:
    cat = str(category or "").lower()
    if "交易" in cat:
        return "交易"
    if "ai" in cat or "工具" in cat:
        return "AI"
    if "写作" in cat:
        return "写作"
    if "项目" in cat:
        return "项目"
    if "随笔" in cat or "个人" in cat:
        return "个人随笔"
    if "课程" in cat:
        return "课程"
    if "外部" in cat:
        return "外部资料"
    if "认知" in cat:
        return "个人随笔"
    return "其他"


def _risk_stratum(row: sqlite3.Row) -> str:
    filename = str(row["filename"] or "").lower()
    cat = str(row["primary_category"] or "")
    source = str(row["source_type"] or "")
    confidence = float(row["confidence"] or 0.0)
    needs_review = int(row["needs_review"] or 0)
    size = int(row["size_bytes"] or 0)

    if "电子书" in filename or "ebook" in filename:
        return "疑似电子书"
    if "讲义" in filename or "课件" in filename or "slides" in filename:
        return "疑似课程讲义"
    if "合同" in filename or "证件" in filename or "简历" in filename:
        return "疑似合同/证件"
    if size == 0 or (row["extracted_char_count"] or 0) == 0:
        return "空文档/乱码"
    if confidence < 0.75 or needs_review:
        return "低置信度"
    return "正常"


def _build_strata_key(row: sqlite3.Row) -> dict[str, str]:
    return {
        "time": _time_stratum(row["month"]),
        "type": _type_stratum(row["extension"], row["source_type"]),
        "size": _size_stratum(row["size_bytes"]),
        "dir": _dir_stratum(row["primary_category"]),
        "use": _use_stratum(row["primary_category"], row["topic_tags"]),
        "risk": _risk_stratum(row),
    }


def stratified_sample(sqlite_path: str, max_files: int = 60) -> tuple[list[dict], dict]:
    with _connect(sqlite_path) as con:
        rows = con.execute("""
            SELECT docs_path, filename, extension, size_bytes, extracted_char_count,
                   COALESCE(derived_time_month, time_month) AS month,
                   primary_category, source_type, topic_tags,
                   confidence, needs_review, summary
            FROM documents WHERE include_in_kb=1
        """).fetchall()

    all_files = [dict(r) for r in rows]
    if not all_files:
        return [], {}

    # Phase 1: compute strata for every file
    for f in all_files:
        f["_strata"] = _build_strata_key(f)
        f["_row"] = f

    # Phase 2: mandatory coverage — one per stratum
    selected: list[dict] = []
    selected_paths: set[str] = set()
    strata_covered: dict[str, int] = defaultdict(int)

    for dim in ["use", "dir", "type", "size", "time", "risk"]:
        seen_values: set[str] = set()
        for f in sorted(all_files, key=lambda x: float(x.get("confidence", 0)), reverse=True):
            val = f["_strata"][dim]
            if val in seen_values:
                continue
            if f["docs_path"] in selected_paths:
                continue
            if len(selected) >= max_files:
                break
            seen_values.add(val)
            selected.append(_enrich_selection(f, dim, val))
            selected_paths.add(f["docs_path"])
            strata_covered[f"{dim}:{val}"] += 1

    # Phase 3: proportional fill
    remaining = max_files - len(selected)
    if remaining > 0:
        by_category: dict[str, list[dict]] = defaultdict(list)
        for f in all_files:
            if f["docs_path"] not in selected_paths:
                by_category[f["primary_category"] or "未分类"].append(f)

        total_remaining = sum(len(v) for v in by_category.values())
        for cat, files in sorted(by_category.items(), key=lambda x: -len(x[1])):
            quota = max(1, int(remaining * len(files) / total_remaining)) if total_remaining > 0 else 0
            taken = 0
            for f in sorted(files, key=lambda x: float(x.get("confidence", 0)), reverse=True):
                if taken >= quota or len(selected) >= max_files:
                    break
                if f["docs_path"] in selected_paths:
                    continue
                selected.append(_enrich_selection(f, "proportional", cat))
                selected_paths.add(f["docs_path"])
                taken += 1

    # Metadata
    all_strata: dict[str, set[str]] = defaultdict(set)
    covered_strata: dict[str, set[str]] = defaultdict(set)
    for f in all_files:
        s = f.get("_strata", {})
        for dim, val in s.items():
            all_strata[dim].add(val)
    for f in selected:
        s = f.get("strata", f.get("_strata", {}))
        for dim, val in s.items():
            covered_strata[dim].add(val)

    coverage = {
        dim: {
            "covered": sorted(covered_strata.get(dim, set())),
            "total": sorted(all_strata.get(dim, set())),
            "count_covered": len(covered_strata.get(dim, set())),
            "count_total": len(all_strata.get(dim, set())),
            "pct": round(100 * len(covered_strata.get(dim, set())) / max(1, len(all_strata.get(dim, set()))), 1),
        }
        for dim in ["time", "type", "size", "dir", "use", "risk"]
    }

    return selected, coverage


def _enrich_selection(f: dict, reason_dim: str, reason_val: str) -> dict:
    return {
        "docs_path": f["docs_path"],
        "filename": f.get("filename", ""),
        "extension": f.get("extension", ""),
        "size_bytes": f.get("size_bytes", 0),
        "month": f.get("month", ""),
        "primary_category": f.get("primary_category", ""),
        "source_type": f.get("source_type", ""),
        "confidence": f.get("confidence", 0),
        "needs_review": f.get("needs_review", 0),
        "summary": f.get("summary", "") or "",
        "sampling_reason": f"{reason_dim}:{reason_val}",
        "strata": f.get("_strata", {}),
    }


def write_selection_csv(selected: list[dict], path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    headers = ["docs_path", "filename", "extension", "size_bytes", "month",
               "primary_category", "source_type", "confidence", "needs_review",
               "sampling_reason",
               "strata_time", "strata_type", "strata_size", "strata_dir", "strata_use", "strata_risk"]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=headers)
        w.writeheader()
        for s in selected:
            strata = s.get("strata", {})
            w.writerow({
                "docs_path": s["docs_path"],
                "filename": s["filename"],
                "extension": s["extension"],
                "size_bytes": s["size_bytes"],
                "month": s["month"],
                "primary_category": s["primary_category"],
                "source_type": s["source_type"],
                "confidence": s["confidence"],
                "needs_review": s["needs_review"],
                "sampling_reason": s["sampling_reason"],
                "strata_time": strata.get("time", ""),
                "strata_type": strata.get("type", ""),
                "strata_size": strata.get("size", ""),
                "strata_dir": strata.get("dir", ""),
                "strata_use": strata.get("use", ""),
                "strata_risk": strata.get("risk", ""),
            })
    return str(Path(path).resolve())
