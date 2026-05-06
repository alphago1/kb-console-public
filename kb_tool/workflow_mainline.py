from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from chunker import build_chunks, ensure_chunk_tables
from database import KBDatabase
from extractor import extract_text
from llm_classifier import classify_with_llm
from llm_providers.deepseek_provider import DeepSeekProvider
from models import FileRecord
from sampler import sample_text
from scanner import iter_files
from utils.time_utils import derive_time_month


DEFAULT_TRADING_CATEGORIES = ["交易系统与方法论", "交易心理与情绪", "交易复盘", "交易记录"]


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _ws_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _docs_root(cfg: dict | None = None) -> Path:
    if cfg:
        p = cfg.get("workflow", {}).get("docs_root")
        if p:
            return Path(p)
    return _ws_root() / "docs"


def _trading_categories(cfg: dict) -> list[str]:
    cats = cfg.get("workflow", {}).get("trading_categories")
    if isinstance(cats, list) and cats:
        return [str(x) for x in cats]
    return DEFAULT_TRADING_CATEGORIES


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sanitize(seg: str, default: str) -> str:
    seg = (seg or "").strip() or default
    seg = re.sub(r'[<>:"/\\|?*]', "_", seg)
    seg = re.sub(r"\s+", " ", seg).strip().rstrip(". ")
    return seg or default


def _safe_stem(name: str) -> str:
    stem = Path(name).stem if name else "file"
    stem = re.sub(r'[<>:"/\\|?*]', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip().rstrip(". ")
    if not stem:
        stem = "file"
    return stem[:100]


def _ext(name: str, ext: str) -> str:
    e = ext or Path(name).suffix
    if not e:
        return ""
    return e if e.startswith(".") else f".{e}"


def _chars_no_ws(text: str) -> int:
    return sum(1 for ch in (text or "") if not ch.isspace())


def _build_blocks_with_budget(cfg: dict, rows: list, max_chars: int = 1_000_000, max_per_doc: int = 3000) -> tuple[list[str], int]:
    """Accumulate document text blocks until hitting max_chars budget. Returns (blocks, total_chars)."""
    blocks = []
    total = 0
    for r in rows:
        text = _read_doc_text(cfg, r)
        if not text:
            continue
        block = f"### {r['filename']} ({r['month']}/{r['primary_category']})\n- {r['docs_path']}\n\n{text[:max_per_doc]}"
        chars = _chars_no_ws(block)
        if total + chars > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                blocks.append(f"### {r['filename']} ({r['month']}/{r['primary_category']})\n- {r['docs_path']}\n\n{text[:remaining]}")
            blocks.append(f"\n⚠️ 已达 {max_chars:,} 字上限，剩余 {len(rows) - len(blocks)} 篇文档未读入")
            break
        blocks.append(block)
        total += chars
    return blocks, total


def _estimate_tokens(chars_no_ws: int) -> tuple[int, int]:
    if chars_no_ws <= 0:
        return 0, 0
    return max(1, int(chars_no_ws / 2.2)), max(1, int(chars_no_ws / 1.2))


def _llm_log_path(cfg: dict) -> Path:
    return Path(cfg["storage"]["logs_dir"]) / "llm_calls.jsonl"


def _write_llm_log(cfg: dict, payload: dict[str, Any]) -> None:
    p = _llm_log_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"time": _now(), **payload}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _init_and_ensure_columns(cfg: dict) -> None:
    from database import KBDatabase

    KBDatabase(cfg).init()
    sqlite_path = cfg["storage"]["sqlite_path"]
    ensure_chunk_tables(sqlite_path)
    with _connect(sqlite_path) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(documents)").fetchall()}
        if "source_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN source_path TEXT")
        if "docs_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN docs_path TEXT")
        if "text_cache_path" not in cols:
            con.execute("ALTER TABLE documents ADD COLUMN text_cache_path TEXT")
        con.execute("UPDATE documents SET docs_path=path WHERE docs_path IS NULL OR docs_path='' ")


def _unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    base = p.with_suffix("")
    suf = p.suffix
    i = 2
    while True:
        c = Path(f"{base}_{i}{suf}")
        if not c.exists():
            return c
        i += 1


def _update_all_path_refs(con: sqlite3.Connection, old_path: str, new_path: str) -> None:
    if old_path == new_path:
        return
    con.execute("UPDATE documents SET path=? WHERE path=?", (new_path, old_path))
    con.execute("UPDATE document_chunks SET path=? WHERE path=?", (new_path, old_path))
    try:
        con.execute("UPDATE document_chunks_fts SET path=? WHERE path=?", (new_path, old_path))
    except sqlite3.OperationalError:
        pass


def _weekly_report_path(cfg: dict, week_label: str) -> Path:
    return Path(cfg["storage"]["reports_dir"]) / "weekly" / f"{week_label}.md"


def _week_label(dt: datetime | None = None) -> str:
    now = dt or datetime.now()
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def _is_supported(path: str, include_exts: set[str], exclude_file_globs: list[str]) -> bool:
    name = os.path.basename(path)
    for pat in exclude_file_globs:
        if Path(name).match(pat):
            return False
    return Path(path).suffix.lower() in include_exts


def _iter_source_files(cfg: dict, source_dirs: list[str] | None = None, recursive: bool = True) -> list[str]:
    sc = cfg["scanner"]
    include_exts = {e.lower() for e in sc.get("include_extensions", [])}
    exclude_file_globs = sc.get("exclude_file_globs", [])
    exclude_dir_globs = list(sc.get("exclude_dir_globs", [])) + ["*/kb_out*", "*/docs*", "*/.venv*", "*/__pycache__*"]

    dirs = source_dirs if source_dirs else (cfg.get("workflow", {}).get("source_dirs") or sc.get("root_dirs", []))
    files: list[str] = []

    if recursive:
        for p in iter_files(dirs, exclude_dir_globs):
            if _is_supported(p, include_exts, exclude_file_globs):
                files.append(p)
    else:
        import glob as glob_mod
        for d in dirs:
            for ext in include_exts:
                for f in glob_mod.glob(os.path.join(d, f"*{ext}")):
                    if os.path.isfile(f):
                        name = os.path.basename(f)
                        if any(Path(name).match(pat) for pat in exclude_file_globs):
                            continue
                        files.append(f)
    return files


def weekly_organize(cfg: dict, dry_run: bool = False, max_files: int | None = None, source_dirs: list[str] | None = None, recursive: bool = True) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)

    run_id = datetime.now().strftime("weekly-%Y%m%d-%H%M%S")
    processed: list[dict[str, Any]] = []
    skipped_unchanged = 0
    errors = 0

    files = _iter_source_files(cfg, source_dirs=source_dirs, recursive=recursive)
    total_files = len(files)
    print(json.dumps({"phase": "scan_done", "total_files": total_files}, ensure_ascii=False))

    if max_files and max_files > 0:
        files = files[:max_files]
    docs_root = _docs_root(cfg)
    docs_root.mkdir(parents=True, exist_ok=True)

    db = KBDatabase(cfg)

    # Load supervised policy categories if available (replaces hardcoded 11 categories)
    supervised_policy_dir = Path(cfg["storage"]["output_dir"]) / "supervised_policy"
    allowed_categories: Optional[list[str]] = None
    cat_schema_path = supervised_policy_dir / "category_schema_v1.yaml"
    if cat_schema_path.exists():
        try:
            with open(cat_schema_path, encoding="utf-8") as f:
                schema = yaml.safe_load(f)
            cats = schema.get("categories", [])
            approved = [c["name"] for c in cats if c.get("status") == "approved"]
            if approved:
                allowed_categories = approved
                logging.info("weekly_organize: using supervised policy categories (%d approved)", len(approved))
        except Exception:
            logging.warning("weekly_organize: failed to load supervised policy, falling back to default categories")

    for idx, src in enumerate(files):
        if idx % 10 == 0:
            print(json.dumps({"progress": {"current": idx, "total": len(files)}}, ensure_ascii=False))
        try:
            st = os.stat(src)
            fsize = int(st.st_size)
            fmtime = float(st.st_mtime)
            src_abs = str(Path(src).resolve())

            with _connect(sqlite_path) as con:
                row = con.execute(
                    """
                    SELECT path, fingerprint_size, fingerprint_mtime, fingerprint_sha256
                    FROM documents
                    WHERE source_path=? OR path=?
                    ORDER BY CASE WHEN source_path=? THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (src_abs, src_abs, src_abs),
                ).fetchone()

            existing_path = row["path"] if row else None
            existing_size = int(row["fingerprint_size"] or -1) if row else -1
            existing_mtime = float(row["fingerprint_mtime"] or -1) if row else -1
            existing_sha = row["fingerprint_sha256"] if row else None

            if existing_path and existing_size == fsize and abs(existing_mtime - fmtime) < 0.1:
                skipped_unchanged += 1
                continue

            if dry_run:
                processed.append({"source": src_abs, "docs": "<dry-run>", "category": "<unknown>", "month": "<unknown>"})
                continue

            # First copy to inbox, then classify and relocate into category/month.
            mtime_dt = datetime.fromtimestamp(fmtime)
            ctime_dt = datetime.fromtimestamp(float(st.st_ctime))
            dt = derive_time_month(os.path.basename(src_abs), ctime_dt, mtime_dt, None, None)
            month_guess = dt.derived_time_month or "_unknown_month"
            ext = Path(src_abs).suffix.lower()
            stem = _safe_stem(os.path.basename(src_abs))
            inbox_dir = docs_root / "_weekly_inbox" / month_guess
            inbox_dir.mkdir(parents=True, exist_ok=True)
            temp_dest = _unique_path(inbox_dir / f"{stem}{ext}")
            shutil.copy2(src_abs, temp_dest)

            fr = FileRecord(
                path=str(temp_dest),
                filename=temp_dest.name,
                extension=ext,
                size_bytes=fsize,
                filesystem_created_time=ctime_dt,
                filesystem_modified_time=mtime_dt,
            )
            db.process_file(fr, run_id=run_id, allowed_categories=allowed_categories)

            with _connect(sqlite_path) as con:
                doc = con.execute("SELECT * FROM documents WHERE path=?", (str(temp_dest),)).fetchone()
                if not doc:
                    raise RuntimeError("processed document missing in sqlite")

                category = _sanitize(doc["primary_category"] or "无法判断", "无法判断")
                month = _sanitize(doc["derived_time_month"] or month_guess, "_unknown_month")
                sha = (doc["fingerprint_sha256"] or "")[:8]
                final_dir = docs_root / category / month
                final_dir.mkdir(parents=True, exist_ok=True)
                final_name = f"{_safe_stem(doc['filename'])}{'_' + sha if sha else ''}{_ext(doc['filename'], doc['extension'])}"
                final_candidate = final_dir / final_name

                if final_candidate.exists():
                    # Same name+SHA already on disk — update the existing DB row in place,
                    # remove the temp inbox file + delete its stale DB row.
                    final_dest = final_candidate
                    if str(final_dest) != str(temp_dest):
                        Path(temp_dest).unlink(missing_ok=True)
                        con.execute("DELETE FROM documents WHERE path=?", (str(temp_dest),))
                else:
                    final_dest = _unique_path(final_candidate)
                    if str(final_dest) != str(temp_dest):
                        shutil.move(str(temp_dest), str(final_dest))
                        _update_all_path_refs(con, str(temp_dest), str(final_dest))

                full_text, _, _, _ = extract_text(cfg, str(final_dest), Path(final_dest).suffix.lower())
                cache_root = Path(cfg["storage"]["output_dir"]) / "text_cache" / category / month
                cache_root.mkdir(parents=True, exist_ok=True)
                cache_path = cache_root / f"{final_dest.stem}.txt"
                cache_path.write_text(full_text or "", encoding="utf-8")

                con.execute(
                    """
                    UPDATE documents
                    SET source_path=?, docs_path=?, text_cache_path=?,
                        fingerprint_size=?, fingerprint_mtime=?
                    WHERE path=?
                    """,
                    (src_abs, str(final_dest), str(cache_path), fsize, fmtime, str(final_dest)),
                )
                con.commit()

            processed.append({"source": src_abs, "docs": str(final_dest), "category": category, "month": month})
        except Exception:
            errors += 1
            logging.exception("weekly-organize failed on %s", src)

    # Keep chunks in sync with new/changed docs paths.
    if not dry_run:
        build_chunks(cfg, rebuild=True)

    week = _week_label()
    rp = _weekly_report_path(cfg, week)
    rp.parent.mkdir(parents=True, exist_ok=True)

    by_cat = Counter(p["category"] for p in processed)
    lines = [
        f"# Weekly Organize {week}",
        "",
        f"- 扫描文件数：{len(files)}",
        f"- 新增/变更处理：{len(processed)}",
        f"- 跳过未变化：{skipped_unchanged}",
        f"- 错误：{errors}",
        "",
        "## 分类分布",
    ]
    for k, v in by_cat.most_common():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 处理清单")
    for item in processed:
        lines.append(f"- [{item['category']}|{item['month']}] {item['source']} -> {item['docs']}")
    rp.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "week": week,
        "dry_run": dry_run,
        "scanned": len(files),
        "processed": len(processed),
        "skipped_unchanged": skipped_unchanged,
        "errors": errors,
        "weekly_report": str(rp.resolve()),
    }


def _fetch_docs(con: sqlite3.Connection, where: str = "", params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    sql = (
        "SELECT rowid AS document_id, COALESCE(docs_path, path) AS docs_path, source_path, text_cache_path, "
        "filename, extension, primary_category, COALESCE(derived_time_month, time_month) AS month, summary, source_type "
        "FROM documents WHERE include_in_kb=1"
    )
    if where:
        sql += " AND " + where
    sql += " ORDER BY primary_category, month, filename"
    return con.execute(sql, params).fetchall()


def _read_doc_text(cfg: dict, row: sqlite3.Row) -> str:
    cache = row["text_cache_path"]
    if cache and os.path.exists(cache):
        return Path(cache).read_text(encoding="utf-8", errors="ignore")

    path = row["docs_path"]
    if not path or not Path(path).exists():
        return ""
    ext = Path(path).suffix.lower() if path else (row["extension"] or "")
    text, _, _, _ = extract_text(cfg, path, ext)
    return text or ""


def token_budget(cfg: dict, scope: str = "trading") -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)

    if scope != "trading":
        raise ValueError("only trading scope is supported")

    categories = _trading_categories(cfg)

    with _connect(sqlite_path) as con:
        ph = ",".join(["?"] * len(categories))
        rows = _fetch_docs(con, where=f"primary_category IN ({ph})", params=tuple(categories))

    total_chars = 0
    for r in rows:
        text = _read_doc_text(cfg, r)
        total_chars += _chars_no_ws(text)

    t_low, t_high = _estimate_tokens(total_chars)
    if t_high < 850_000:
        plan = "single_full_read"
    elif t_high <= 1_500_000:
        plan = "category_batches"
    else:
        plan = "monthly_batches_or_compacted"

    return {
        "scope": scope,
        "categories": categories,
        "document_count": len(rows),
        "total_chars_no_ws": total_chars,
        "token_estimate_low": t_low,
        "token_estimate_high": t_high,
        "fits_1m_context": t_high <= 1_000_000,
        "strategy": plan,
    }


def build_trading_bundle(cfg: dict) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)

    categories = _trading_categories(cfg)
    with _connect(sqlite_path) as con:
        ph = ",".join(["?"] * len(categories))
        rows = _fetch_docs(con, where=f"primary_category IN ({ph})", params=tuple(categories))

    budget = token_budget(cfg, scope="trading")

    lines = [
        f"# Trading Full Bundle {datetime.now().date().isoformat()}",
        "",
        "## Token Budget",
        f"- 文档数: {budget['document_count']}",
        f"- 总字数(去空白): {budget['total_chars_no_ws']:,}",
        f"- token 估算: {budget['token_estimate_low']:,} ~ {budget['token_estimate_high']:,}",
        f"- 1M 一次性读入: {'是' if budget['fits_1m_context'] else '否'}",
        f"- 建议策略: {budget['strategy']}",
        "",
        "## 文件清单",
    ]
    for r in rows:
        lines.append(f"- {r['primary_category']} | {r['month']} | {r['filename']} | {r['docs_path']}")

    for r in rows:
        text = _read_doc_text(cfg, r)
        lines.extend(
            [
                "",
                "---",
                f"## {r['filename']}",
                f"- docs_path: {r['docs_path']}",
                f"- month: {r['month']}",
                f"- category: {r['primary_category']}",
                "",
                text,
            ]
        )

    out = Path(cfg["storage"]["output_dir"]) / "bundles" / f"trading_full_{datetime.now().date().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"bundle": str(out.resolve()), "documents": len(rows), "budget": budget}


def _provider(cfg: dict) -> DeepSeekProvider:
    return DeepSeekProvider(
        api_key_env=cfg.get("llm", {}).get("api_key_env", "DEEPSEEK_API_KEY"),
        base_url=cfg.get("llm", {}).get("base_url", "https://api.deepseek.com"),
        model=cfg.get("llm", {}).get("model", "deepseek-v4-flash"),
    )


def _llm_report(cfg: dict, task: str, prompt: str) -> str:
    p = _provider(cfg)
    _write_llm_log(cfg, {"task": task, "model": p.model, "prompt_chars": len(prompt)})
    out = p.chat([{"role": "user", "content": prompt}], temperature=0.2)
    _write_llm_log(cfg, {"task": task, "model": p.model, "response_chars": len(out)})
    return out


def trading_monthly_report(cfg: dict, month: str) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)

    categories = _trading_categories(cfg)
    with _connect(sqlite_path) as con:
        ph = ",".join(["?"] * len(categories))
        month_rows = _fetch_docs(
            con,
            where=f"primary_category IN ({ph}) AND COALESCE(derived_time_month, time_month)=?",
            params=tuple(categories) + (month,),
        )
        bg_rows = _fetch_docs(
            con,
            where="primary_category=? AND COALESCE(derived_time_month, time_month) < ?",
            params=("交易系统与方法论", month),
        )

    month_blocks, _ = _build_blocks_with_budget(cfg, month_rows, max_chars=800_000, max_per_doc=999_999)
    bg_blocks, _ = _build_blocks_with_budget(cfg, bg_rows, max_chars=200_000)

    prompt = (
        f"你是交易复盘分析助手。请基于以下当月全文与历史系统背景，生成 {month} 月报。\n"
        "必须包含并使用中文一级标题：\n"
        "本月主要操作\n本月反复错误\n执行力问题\n情绪问题\n交易系统变化\n新增规则\n被证伪旧规则\n下月检查清单\n证据文件\n\n"
        "要求：每条结论后附证据文件路径。\n\n"
        "[当月全文]\n" + "\n\n".join(month_blocks) + "\n\n"
        "[历史交易系统背景]\n" + "\n\n".join(bg_blocks)
    )

    content = _llm_report(cfg, "trading-monthly-report", prompt)
    out = Path(cfg["storage"]["reports_dir"]) / "trading_monthly" / f"{month}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return {"month": month, "report": str(out.resolve()), "docs": len(month_rows)}


def trading_system_build(cfg: dict) -> dict:
    bundle = build_trading_bundle(cfg)
    budget = bundle["budget"]
    strategy = budget["strategy"]
    sqlite_path = cfg["storage"]["sqlite_path"]
    categories = _trading_categories(cfg)

    with _connect(sqlite_path) as con:
        ph = ",".join(["?"] * len(categories))
        rows = _fetch_docs(con, where=f"primary_category IN ({ph})", params=tuple(categories))

    def _doc_block(r: sqlite3.Row, max_chars: int = 4000) -> str:
        txt = _read_doc_text(cfg, r)
        if len(txt) > max_chars:
            txt = txt[:max_chars] + "\n...<truncated>"
        return f"### {r['filename']} ({r['month']}/{r['primary_category']})\n- path: {r['docs_path']}\n\n{txt}"

    partials: list[str] = []
    if strategy == "single_full_read":
        btxt = Path(bundle["bundle"]).read_text(encoding="utf-8", errors="ignore")
        prompt = (
            "你是交易系统构建助手。请阅读下面材料，输出结构化报告，必须包含标题：\n"
            "买入规则\n卖出规则\n止损规则\n仓位规则\n等待回调规则\n不追涨规则\n情绪控制规则\n规则证据\n规则冲突\n待验证问题\n"
            f"[预算]{json.dumps(budget, ensure_ascii=False)}\n\n[材料]\n{btxt}"
        )
        content = _llm_report(cfg, "trading-system-build", prompt)
    elif strategy == "category_batches":
        for cat in categories:
            c_rows = [r for r in rows if r["primary_category"] == cat]
            if not c_rows:
                continue
            c_prompt = (
                f"请先抽取类别“{cat}”里的交易系统候选规则，输出：规则、证据路径、冲突、待验证。\n\n"
                + "\n\n".join(_doc_block(r, max_chars=3500) for r in c_rows)
            )
            part = _llm_report(cfg, "trading-system-build-category", c_prompt)
            partials.append(f"## 类别批次: {cat}\n\n{part}")

        synth_prompt = (
            "请综合以下类别批次结果，输出最终交易系统构建报告，必须包含标题：\n"
            "买入规则\n卖出规则\n止损规则\n仓位规则\n等待回调规则\n不追涨规则\n情绪控制规则\n规则证据\n规则冲突\n待验证问题\n\n"
            + "\n\n".join(partials)
        )
        content = _llm_report(cfg, "trading-system-build-synthesis", synth_prompt)
    else:
        months = sorted({r["month"] for r in rows if r["month"]})
        for m in months:
            m_rows = [r for r in rows if r["month"] == m]
            if not m_rows:
                continue
            m_prompt = (
                f"请抽取月份 {m} 的交易规则证据，输出：规则、证据路径、冲突、待验证。\n\n"
                + "\n\n".join(_doc_block(r, max_chars=2800) for r in m_rows)
            )
            part = _llm_report(cfg, "trading-system-build-month", m_prompt)
            partials.append(f"## 月份批次: {m}\n\n{part}")

        synth_prompt = (
            "请综合以下月份批次结果，输出最终交易系统构建报告，必须包含标题：\n"
            "买入规则\n卖出规则\n止损规则\n仓位规则\n等待回调规则\n不追涨规则\n情绪控制规则\n规则证据\n规则冲突\n待验证问题\n\n"
            + "\n\n".join(partials)
        )
        content = _llm_report(cfg, "trading-system-build-synthesis", synth_prompt)

    out = Path(cfg["storage"]["reports_dir"]) / "trading_system" / f"trading_system_build_{datetime.now().date().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return {"report": str(out.resolve()), "strategy": strategy}


def trading_analyze(cfg: dict, topic: str, categories: list[str] | None = None) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)
    cats = categories if categories else _trading_categories(cfg)
    with _connect(sqlite_path) as con:
        ph = ",".join(["?"] * len(cats))
        rows = _fetch_docs(
            con,
            where=f"primary_category IN ({ph})",
            params=tuple(cats),
        )

    blocks, total_chars = _build_blocks_with_budget(cfg, rows, max_chars=1_000_000)

    if not blocks:
        out = Path(cfg["storage"]["reports_dir"]) / "trading_topics" / f"{topic[:40].replace('/', '_')}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        msg = (
            f"# 主题分析：{topic}\n\n"
            f"**⚠️ 未读入任何文件。**\n\n"
            f"原因：在以下分类中没有找到与「{topic}」相关的文档：\n"
            + "\n".join(f"- {c}" for c in cats) +
            f"\n\n建议：\n"
            f"1. 检查搜索范围是否包含相关文件夹\n"
            f"2. 尝试用不同的关键词\n"
            f"3. 确认知识库中有相关文档"
        )
        out.write_text(msg, encoding="utf-8")
        return {"topic": topic, "report": str(out.resolve()), "docs_used": 0, "warning": "未读入任何文件"}

    prompt = (
        f"请围绕主题「{topic}」分析知识库文档。以下是你必须严格基于的内容，不得编造：\n"
        "输出必须包含：结论、证据列表（附docs_path）、冲突点、下一步实验。\n\n"
        "⚠️ 重要约束：\n"
        "- 只能基于下面提供的文档内容进行分析\n"
        "- 如果文档中缺乏某些信息，明确说「文档中未涉及」而不是猜测\n"
        "- 每条结论必须引用具体的文档路径作为证据\n\n"
        "--- 以下为知识库文档 ---\n\n"
        + "\n\n".join(blocks)
    )
    content = _llm_report(cfg, "trading-analyze", prompt)
    out = Path(cfg["storage"]["reports_dir"]) / "trading_topics" / f"{topic[:40].replace('/', '_')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return {"topic": topic, "report": str(out.resolve()), "docs_used": min(len(rows), 80)}


def find_idea(cfg: dict, query: str, month_start: str | None = None, month_end: str | None = None, category: str | None = None) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)
    with _connect(sqlite_path) as con:
        sql = (
            "SELECT c.path AS docs_path, c.chunk_index, c.derived_time_month AS month, c.primary_category AS category, "
            "snippet(document_chunks_fts,0,'[',']',' ... ',12) AS snippet, bm25(document_chunks_fts) AS score "
            "FROM document_chunks_fts JOIN document_chunks c ON c.chunk_id=document_chunks_fts.rowid "
            "WHERE document_chunks_fts MATCH ?"
        )
        params: list[Any] = [" ".join([f'\"{t}\"' for t in query.split() if t.strip()]) or '""']
        if month_start:
            sql += " AND c.derived_time_month >= ?"
            params.append(month_start)
        if month_end:
            sql += " AND c.derived_time_month <= ?"
            params.append(month_end)
        if category:
            sql += " AND c.primary_category = ?"
            params.append(category)
        sql += " ORDER BY score LIMIT 30"
        rows = [dict(r) for r in con.execute(sql, params).fetchall()]

        fn_rows = [
            dict(r)
            for r in con.execute(
                """
                SELECT COALESCE(docs_path, path) AS docs_path, COALESCE(derived_time_month, time_month) AS month,
                       primary_category AS category, filename, summary
                FROM documents
                WHERE include_in_kb=1 AND filename LIKE ?
                ORDER BY confidence DESC LIMIT 20
                """,
                (f"%{query}%",),
            ).fetchall()
        ]

    out = []
    for r in rows:
        out.append(
            {
                "docs_path": r["docs_path"],
                "month": r.get("month"),
                "category": r.get("category"),
                "snippet": r.get("snippet"),
                "reason": "FTS5 命中片段",
            }
        )
    for r in fn_rows:
        out.append(
            {
                "docs_path": r["docs_path"],
                "month": r.get("month"),
                "category": r.get("category"),
                "snippet": (r.get("summary") or "")[:180],
                "reason": "文件名命中",
            }
        )

    # de-dup by path while preserving rank
    seen = set()
    dedup = []
    for x in out:
        p = x["docs_path"]
        if p in seen:
            continue
        seen.add(p)
        dedup.append(x)

    return {"query": query, "count": len(dedup), "items": dedup[:30]}


def compact_course_transcripts(cfg: dict) -> dict:
    sqlite_path = cfg["storage"]["sqlite_path"]
    _init_and_ensure_columns(cfg)
    categories = _trading_categories(cfg)
    with _connect(sqlite_path) as con:
        ph = ",".join(["?"] * len(categories))
        rows = _fetch_docs(
            con,
            where=(
                f"primary_category IN ({ph}) AND ("
                "source_type='课程转写' OR filename LIKE '%转写%' OR filename LIKE '%文稿%' "
                "OR filename LIKE '%meeting%' OR filename LIKE '%.mp3%' OR filename LIKE '%.mp4%')"
            ),
            params=tuple(categories),
        )

    out_dir = Path(cfg["storage"]["output_dir"]) / "compacted" / "course_transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    made = 0
    for r in rows:
        text = _read_doc_text(cfg, r)
        prompt = (
            "请压缩以下课程转写内容，仅保留并按小标题输出："
            "交易规则、核心概念、买卖点条件、反例、老师纠错、用户提问、认知变化、可执行规则。\n\n"
            f"文档: {r['docs_path']}\n\n{text}"
        )
        content = _llm_report(cfg, "compact-course-transcripts", prompt)
        out = out_dir / f"{r['month']}__{Path(r['filename']).stem}.md"
        out.write_text(content, encoding="utf-8")
        made += 1

    return {"input_docs": len(rows), "compacted_docs": made, "output_dir": str(out_dir.resolve())}
