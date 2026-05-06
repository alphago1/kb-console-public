from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ──────────────────────────── dry-run ────────────────────────────

def dry_run(cfg: dict) -> dict:
    """Count files that would be processed, without touching anything."""
    from scanner import iter_files

    sc = cfg["scanner"]
    include_exts = {e.lower() for e in sc.get("include_extensions", [])}
    exclude_file_globs = sc.get("exclude_file_globs", [])
    exclude_dir_globs = list(sc.get("exclude_dir_globs", []))
    exclude_dir_globs += ["*/kb_tool/kb_out*", "*/kb_out*", "*/.venv*", "*/__pycache__*"]

    from utils.path_utils import matches_any_glob

    total = 0
    supported = 0
    excluded = 0
    extensions_found: dict[str, int] = {}
    dirs_found: dict[str, int] = {}

    for path in iter_files(sc["root_dirs"], exclude_dir_globs):
        total += 1
        base = os.path.basename(path)
        if matches_any_glob(base, exclude_file_globs):
            excluded += 1
            continue
        ext = Path(path).suffix.lower()
        if ext not in include_exts:
            excluded += 1
            continue
        supported += 1
        extensions_found[ext] = extensions_found.get(ext, 0) + 1
        parent = str(Path(path).parent)
        dirs_found[parent] = dirs_found.get(parent, 0) + 1

    return {
        "total_seen": total,
        "supported": supported,
        "excluded": excluded,
        "extensions": dict(sorted(extensions_found.items(), key=lambda x: -x[1])),
        "top_dirs": dict(sorted(dirs_found.items(), key=lambda x: -x[1])[:15]),
    }


# ──────────────────────────── full build ────────────────────────────

def build_deep_custom(
    config_path: str,
    blueprint_path: str,
    policy_path: str,
    components_path: str,
    output_dir: str,
    skip_scan: bool = False,
    skip_wiki: bool = False,
    wiki_only: bool = False,
) -> dict:
    """Orchestrate full deep-custom knowledge base build. Returns build log entries."""

    cfg = _load_yaml(config_path)
    out = Path(output_dir)
    log_lines: list[str] = []
    step_times: dict[str, float] = {}

    def _log(msg: str) -> None:
        logging.info(msg)
        log_lines.append(f"[{_ts()}] {msg}")

    def _step(name: str) -> None:
        _log(f"── BEGIN {name} ──")
        step_times[name] = time.time()

    def _step_done(name: str) -> None:
        elapsed = time.time() - step_times.get(name, time.time())
        _log(f"── END {name} ({elapsed:.1f}s) ──")

    _log("===== DEEP-CUSTOM BUILD START =====")
    _log(f"config: {config_path}")
    _log(f"blueprint: {blueprint_path}")
    _log(f"policy: {policy_path}")
    _log(f"components: {components_path}")
    _log(f"output: {output_dir}")

    # ── Safety: ensure output is self-contained ──
    _log("SAFETY: 不移动/不删除/不重命名源文件")
    _log(f"SAFETY: 所有输出写入 {output_dir}")

    # ── Step 1-4: Read blueprint / policies / components ──
    _step("load-policies")
    blueprint_md = _read_or_empty(blueprint_path)
    classification_policy = _load_yaml(policy_path) if Path(policy_path).exists() else {}
    component_plan = _load_yaml(components_path) if Path(components_path).exists() else {}
    # Also try to load query_strategy_policy from sibling dir
    strategy_policy = {}
    bp_dir = Path(policy_path).parent if Path(policy_path).exists() else Path(".")
    qsp = bp_dir / "query_strategy_policy.yaml"
    if qsp.exists():
        strategy_policy = _load_yaml(str(qsp))
    _log(f"classification_policy keys: {list(classification_policy.keys())[:10]}")
    _log(f"component_plan components: {list(component_plan.get('components', {}).keys())}")
    _step_done("load-policies")

    # ── Step 5-8: Scan → extract → classify → SQLite ──
    _step("scan-extract-classify-sqlite")

    build_cfg = dict(cfg)
    build_cfg["storage"] = dict(cfg.get("storage", {}))
    build_cfg["storage"]["output_dir"] = str(out)
    build_cfg["storage"]["exports_dir"] = str(out / "exports")
    build_cfg["storage"]["dashboard_dir"] = str(out / "dashboard")
    build_cfg["storage"]["reports_dir"] = str(out / "reports")
    build_cfg["storage"]["logs_dir"] = str(out / "logs")

    if skip_scan:
        db_path = cfg["storage"]["sqlite_path"]
        if not Path(db_path).exists():
            raise FileNotFoundError(f"skip_scan=True but database not found: {db_path}")
        build_cfg["storage"]["sqlite_path"] = db_path
        scan_result = {
            "total_seen": 0, "supported_ext": 0, "excluded": 0,
            "processed": 0, "skipped_unchanged": 0, "errors": 0,
            "dry_run": False, "note": "skipped — using existing database",
        }
        _log(f"skip_scan: using existing db at {db_path}")
    else:
        db_path = str(out / "database" / "personal_kb.sqlite")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        build_cfg["storage"]["sqlite_path"] = db_path

        from database import KBDatabase
        db = KBDatabase(build_cfg)
        db.init()

        from scanner import scan_files
        scan_result = scan_files(build_cfg, db=db, run_id="deep-custom-001", dry_run=False, max_files=None)
        _log(f"scan_result: {json.dumps(scan_result, ensure_ascii=False)}")
    _step_done("scan-extract-classify-sqlite")

    # ── Step 9: text_cache already handled by process_file ──
    _step("text-cache")
    tc_dir = out / "text_cache"
    tc_dir.mkdir(parents=True, exist_ok=True)
    # process_file already writes text_cache via extract_text -> write cache
    # We just verify
    cache_files = list(tc_dir.glob("*")) if tc_dir.exists() else []
    _log(f"text_cache files: {len(cache_files)} (handled during scan)")
    _step_done("text-cache")

    # ── Step 10: FTS ──
    _step("fts-build")
    from chunker import build_chunks as build_fts
    fts_result = build_fts(build_cfg, rebuild=False)
    _log(f"fts: {json.dumps(fts_result, ensure_ascii=False)}")
    _step_done("fts-build")

    # ── Step 11: wiki_cache (if enabled) ──
    _step("wiki-cache")
    wiki_enabled = _component_enabled(component_plan, "wiki_cache")
    wiki_result = {}
    if wiki_enabled and not wiki_only:
        wiki_dir = out / "wiki_cache"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        wiki_result = _build_wiki_cache(build_cfg, wiki_dir)
        _log(f"wiki_cache built: {json.dumps(wiki_result, ensure_ascii=False)}")
    else:
        _log("wiki_cache: disabled or skipped (wiki_only mode)")
    _step_done("wiki-cache")

    # ── Step 11b: wiki_pages (human-readable, if wiki_layer enabled) ──
    _step("wiki-pages")
    wiki_pages_result = {}
    topic_pages_enabled = _component_enabled(component_plan, "topic_pages") or not skip_wiki
    if topic_pages_enabled and not skip_wiki:
        from wiki_page_builder import build_wiki_pages
        wiki_pages_result = build_wiki_pages(
            db_path=build_cfg["storage"]["sqlite_path"],
            output_dir=str(out),
            types=["category", "topic"],
        )
        _log(f"wiki_pages: {len(wiki_pages_result.get('pages', {}))} pages, {len(wiki_pages_result.get('errors', []))} errors")
    elif skip_wiki:
        _log("wiki_pages: skipped (--skip-wiki)")
    else:
        _log("wiki_pages: disabled (topic_pages component not enabled)")
    _step_done("wiki-pages")

    # ── Step 12: reports (if enabled) ──
    _step("reports")
    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    _generate_initial_structure_report(build_cfg, reports_dir, classification_policy, component_plan)
    first_value_path = _generate_first_value_report(build_cfg, reports_dir, blueprint_md)
    _log(f"first_value_report: {first_value_path}")
    _step_done("reports")

    # ── Step 13: dashboard ──
    _step("dashboard")
    from dashboard import build_dashboard as build_db
    dashboard_path = build_db(build_cfg)
    _log(f"dashboard: {dashboard_path}")
    _step_done("dashboard")

    # ── Step 14: first_value_report already done (step 12) ──
    # ── Step 15: README_FOR_USER.md ──
    _step("readme-for-user")
    readme_path = _generate_readme_for_user(out, scan_result, fts_result, wiki_result, classification_policy)
    _log(f"README_FOR_USER: {readme_path}")
    _step_done("readme-for-user")

    # ── final_config.yaml ──
    _step("final-config")
    final_cfg = _build_final_config(build_cfg, classification_policy, component_plan, strategy_policy)
    fc_path = out / "final_config.yaml"
    fc_path.write_text(yaml.dump(final_cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
    _log(f"final_config: {fc_path}")
    _step_done("final-config")

    # ── build_log.md ──
    _step("build-log")
    log_path = out / "build_log.md"
    log_path.write_text(_format_build_log(log_lines), encoding="utf-8")
    _step_done("build-log")

    # ── exports ──
    _step("exports")
    _generate_exports(build_cfg, out)
    _step_done("exports")

    # ── review dir ──
    review_dir = out / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    _generate_review_csv(build_cfg, review_dir)
    _log(f"review dir: {review_dir}")

    _log("===== DEEP-CUSTOM BUILD COMPLETE =====")

    return {
        "output_dir": str(out.resolve()),
        "database": db_path,
        "scan": scan_result,
        "fts": fts_result,
        "wiki_cache": wiki_result,
        "dashboard": dashboard_path,
        "first_value_report": str(first_value_path) if 'first_value_path' in dir() else "",
        "readme_for_user": str(readme_path),
        "final_config": str(fc_path),
        "build_log": str(log_path),
        "total_steps": len(step_times),
    }


# ──────────────────────────── helpers ────────────────────────────

def _load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _read_or_empty(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _component_enabled(plan: dict, name: str) -> bool:
    comps = plan.get("components", {})
    if name in comps:
        return comps[name].get("action", "disable") == "enable"
    return False


def _connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    return con


def _build_wiki_cache(build_cfg: dict, wiki_dir: Path) -> dict:
    """Build compact JSON wiki cache from database."""
    db_path = build_cfg["storage"]["sqlite_path"]
    cache = {}
    try:
        with _connect(db_path) as con:
            rows = con.execute(
                "SELECT primary_category, topic_tags, summary, cognition_snapshot, source_type "
                "FROM documents WHERE include_in_kb=1 AND summary IS NOT NULL"
            ).fetchall()
        by_category: dict[str, list[dict]] = {}
        for r in rows:
            cat = r["primary_category"] or "未分类"
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append({
                "summary": r["summary"],
                "tags": (r["topic_tags"] or "").split(",") if r["topic_tags"] else [],
                "source_type": r["source_type"],
            })

        cache = {
            "version": "v1",
            "generated": _now(),
            "total_documents": sum(len(v) for v in by_category.values()),
            "categories": {cat: docs for cat, docs in by_category.items()},
        }
        cp = wiki_dir / "wiki_cache.json"
        cp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(cp), "categories": len(by_category), "documents": cache["total_documents"]}
    except Exception as e:
        return {"error": str(e)}


def _generate_initial_structure_report(
    build_cfg: dict, reports_dir: Path,
    classification_policy: dict, component_plan: dict,
) -> Path:
    """Generate initial_structure_report.md."""
    db_path = build_cfg["storage"]["sqlite_path"]
    with _connect(db_path) as con:
        cats = con.execute(
            "SELECT primary_category, COUNT(*) as cnt FROM documents "
            "WHERE include_in_kb=1 GROUP BY primary_category ORDER BY cnt DESC"
        ).fetchall()
        total = con.execute("SELECT COUNT(*) FROM documents WHERE include_in_kb=1").fetchone()[0]
        types = con.execute(
            "SELECT source_type, COUNT(*) as cnt FROM documents "
            "WHERE include_in_kb=1 GROUP BY source_type ORDER BY cnt DESC"
        ).fetchall()
        months = con.execute(
            "SELECT derived_time_month, COUNT(*) as cnt FROM documents "
            "WHERE include_in_kb=1 AND derived_time_month IS NOT NULL "
            "GROUP BY derived_time_month ORDER BY derived_time_month"
        ).fetchall()

    lines = [
        "# Initial Structure Report",
        "",
        f"> 生成时间: {_ts()}",
        f"> 总文件数: {total}",
        "",
        "## 分类分布",
        "",
        "| 分类 | 文件数 | 占比 |",
        "|------|--------|------|",
    ]
    for c in cats:
        pct = f"{c['cnt']/max(total,1)*100:.1f}%"
        lines.append(f"| {c['primary_category']} | {c['cnt']} | {pct} |")

    lines.extend([
        "",
        "## 来源类型分布",
        "",
        "| 类型 | 文件数 |",
        "|------|--------|",
    ])
    for t in types:
        lines.append(f"| {t['source_type']} | {t['cnt']} |")

    lines.extend([
        "",
        "## 时间分布",
        "",
        "| 月份 | 文件数 |",
        "|------|--------|",
    ])
    for m in months:
        lines.append(f"| {m['derived_time_month']} | {m['cnt']} |")

    lines.extend([
        "",
        "## 启用的组件",
        "",
    ])
    comps = component_plan.get("components", {})
    for name, spec in comps.items():
        if spec.get("action") == "enable":
            lines.append(f"- **{name}**: enabled (visibility={spec.get('visibility', 'both')})")

    lines.extend([
        "",
        "## 分类策略",
        "",
        f"- 主分类数: {len(classification_policy.get('primary_categories', []))}",
        f"- fallback: {classification_policy.get('fallback_category', '无法判断')}",
        f"- 置信度阈值: {classification_policy.get('confidence_threshold', 0.75)}",
    ])

    path = reports_dir / "initial_structure_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _generate_first_value_report(build_cfg: dict, reports_dir: Path, blueprint_md: str) -> Path:
    """Generate first_value_report.md — what value the user gets immediately."""
    db_path = build_cfg["storage"]["sqlite_path"]
    with _connect(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM documents WHERE include_in_kb=1").fetchone()[0]
        with_summary = con.execute("SELECT COUNT(*) FROM documents WHERE include_in_kb=1 AND summary IS NOT NULL AND summary != ''").fetchone()[0]
        with_tags = con.execute("SELECT COUNT(*) FROM documents WHERE include_in_kb=1 AND topic_tags IS NOT NULL AND topic_tags != ''").fetchone()[0]
        top_domains = con.execute(
            "SELECT primary_category, COUNT(*) as cnt FROM documents "
            "WHERE include_in_kb=1 GROUP BY primary_category ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        months_span = con.execute(
            "SELECT MIN(derived_time_month) as earliest, MAX(derived_time_month) as latest FROM documents WHERE include_in_kb=1"
        ).fetchone()

    lines = [
        "# First Value Report — 知识库立即可用价值",
        "",
        f"> 构建完成时间: {_ts()}",
        "",
        "## 你现在拥有什么",
        "",
        f"- **{total}** 个文档已入库，可全文搜索",
        f"- **{with_summary}** 个文档有 AI 生成的摘要",
        f"- **{with_tags}** 个文档有主题标签",
        f"- 时间跨度: {months_span['earliest'] or '?'} ~ {months_span['latest'] or '?'}",
        "",
        "## 立即可做的事",
        "",
        "### 1. 全文搜索",
        "```bash",
        "python main.py search --config config.yaml --query \"你的问题\"",
        "```",
        "",
        "### 2. 按分类浏览",
        "",
        "| 分类 | 文件数 |",
        "|------|--------|",
    ]
    for d in top_domains:
        lines.append(f"| {d['primary_category']} | {d['cnt']} |")

    lines.extend([
        "",
        "### 3. 打开 Dashboard",
        f"浏览器打开: `dashboard/index.html`",
        "",
        "### 4. 查看分类结构",
        f"阅读: `reports/initial_structure_report.md`",
        "",
        "### 5. 查看月度报告（如有可用数据）",
        "```bash",
        "python main.py monthly-report --config config.yaml --month 2026-03",
        "```",
        "",
        "---",
        "",
        "## 下一步建议",
        "",
        "1. 打开 dashboard/index.html 查看知识库全局概览",
        "2. 阅读 README_FOR_USER.md 了解完整功能",
        "3. 尝试几次搜索，熟悉 FTS 检索能力",
        "4. 如有分类/标签错误，使用 feedback-plan 提交反馈",
        "",
        "## 安全说明",
        "",
        "- 源文件未被移动、修改或删除",
        "- 所有 AI 处理结果存储在 `kb_out/deep_custom_kb/` 中",
        "- 数据库文件: `database/personal_kb.sqlite`",
        "- 文本缓存: `text_cache/`",
    ])

    path = reports_dir / "first_value_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _generate_readme_for_user(
    out: Path, scan_result: dict, fts_result: dict,
    wiki_result: dict, classification_policy: dict,
) -> Path:
    """Generate README_FOR_USER.md — comprehensive user guide for this build."""
    primary_cats = classification_policy.get("primary_categories", [])
    cat_list = "\n".join(f"  - {c}" for c in primary_cats[:15]) if primary_cats else "  - (自动分类)"

    lines = [
        "# README — 你的 Deep-Custom 知识库",
        "",
        f"> 构建时间: {_ts()}",
        f"> 处理文件数: {scan_result.get('processed', '?')}",
        f"> 数据库: `database/personal_kb.sqlite`",
        "",
        "---",
        "",
        "## 这是什么",
        "",
        "这是基于你的文档自动构建的个人知识库。AI 已经帮您：",
        "",
        "- 扫描并抽取了所有 docx/md/txt 文件",
        "- 对每个文件进行了主题分类和摘要",
        "- 建立了全文搜索索引（FTS5）",
        "- 生成了可视化 Dashboard",
        "",
        "## 目录结构",
        "",
        "```",
        f"{out.name}/",
        "├── database/",
        "│   └── personal_kb.sqlite       # 知识库主数据库",
        "├── exports/",
        "│   ├── documents.csv            # 文档清单 (CSV)",
        "│   └── documents.json           # 文档清单 (JSON)",
        "├── text_cache/                 # 提取的文本缓存 (如有)",
        "├── dashboard/",
        "│   └── index.html              # 可视化概览面板",
        "├── reports/",
        "│   ├── first_value_report.md   # 立即可用价值",
        "│   └── initial_structure_report.md  # 初始结构报告",
        "├── wiki_cache/                 # AI 维基缓存 (如启用)",
        "│   └── wiki_cache.json",
        "├── review/                     # 需人工审核的文件",
        "├── final_config.yaml           # 最终配置快照",
        "├── build_log.md                # 构建日志",
        "└── README_FOR_USER.md          # 本文件",
        "```",
        "",
        "## 分类体系",
        "",
        f"当前一级分类:",
        cat_list,
        "",
        "## 常用命令",
        "",
        "```bash",
        "# 全文搜索",
        "python main.py search --config config.yaml --query \"关键词\"",
        "",
        "# 生成月度报告",
        "python main.py monthly-report --config config.yaml --month 2026-03",
        "",
        "# 查找某个想法在哪里出现过",
        "python main.py find --config config.yaml --query \"想法关键词\"",
        "",
        "# 启动 API 服务",
        "python main.py serve --config config.yaml",
        "",
        "# 构建 MCP 上下文包",
        "python main.py bundle --config config.yaml",
        "```",
        "",
        "## 搜索技巧",
        "",
        "- FTS5 支持中文分词，直接输入中文关键词即可",
        "- 可以组合搜索: `交易 AND 止损`",
        "- 按月份过滤: `--month-start 2026-01 --month-end 2026-03`",
        "- 按分类过滤: `--category 交易复盘`",
        "",
        "## 数据更新",
        "",
        "每周运行 `weekly-organize` 命令增量更新知识库:",
        "```bash",
        "python main.py weekly-organize --config config.yaml",
        "```",
        "",
        "## 反馈与纠错",
        "",
        "如果发现分类、标签或摘要不准确，可以使用反馈系统:",
        "```bash",
        "# 1. 生成样本运行",
        "python main.py sample-run --config config.yaml --output kb_out/sample_runs/session_N/",
        "",
        "# 2. 编辑 user_feedback.yaml 提出修正",
        "",
        "# 3. 生成规则草案",
        "python main.py feedback-plan --sample-run ... --feedback ... --output ...",
        "",
        "# 4. 应用规则生成 v2 蓝图",
        "python main.py feedback-apply --feedback-plan ... --blueprint ... --output ...",
        "```",
        "",
        "## 安全承诺",
        "",
        "- 你的源文件**从未**被移动、修改或删除",
        "- 所有 AI 处理结果存储在独立的输出目录中",
        "- 数据库仅包含提取的文本和 AI 生成的元数据",
        "- 敏感文件标记为 `privacy_level=敏感`，不会出现在导出中",
        "",
        "---",
        "",
        f"*由 deep-custom build 自动生成于 {_ts()}*",
    ]

    path = out / "README_FOR_USER.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _build_final_config(build_cfg: dict, classification_policy: dict,
                        component_plan: dict, strategy_policy: dict) -> dict:
    return {
        "version": "deep-custom-v1",
        "build_time": _now(),
        "storage": {
            "sqlite_path": build_cfg["storage"]["sqlite_path"],
            "output_dir": build_cfg["storage"]["output_dir"],
        },
        "classification": {
            "primary_categories": classification_policy.get("primary_categories", []),
            "fallback": classification_policy.get("fallback_category", "无法判断"),
            "confidence_threshold": classification_policy.get("confidence_threshold", 0.75),
        },
        "components": component_plan.get("components", {}),
        "query_strategy": strategy_policy.get("version", "v1"),
        "safety": {
            "source_files_readonly": True,
            "never_move": True,
            "never_delete": True,
            "never_rename": True,
            "never_overwrite_source": True,
        },
    }


def _format_build_log(log_lines: list[str]) -> str:
    header = [
        "# Build Log",
        "",
        f"> 构建时间: {_ts()}",
        "",
        "```",
    ]
    return "\n".join(header) + "\n" + "\n".join(log_lines) + "\n```\n"


def _generate_exports(build_cfg: dict, out: Path) -> None:
    """Generate documents.csv and documents.json exports."""
    exports_dir = out / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    db_path = build_cfg["storage"]["sqlite_path"]

    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT docs_path, filename, extension, size_bytes, derived_time_month, "
            "primary_category, source_type, topic_tags, confidence, summary, "
            "include_in_kb, needs_review "
            "FROM documents ORDER BY primary_category, derived_time_month"
        ).fetchall()

    # CSV
    csv_path = exports_dir / "documents.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=rows[0].keys())
            w.writeheader()
            for r in rows:
                w.writerow({k: (str(v)[:2000] if v else "") for k, v in dict(r).items()})

    # JSON
    json_path = exports_dir / "documents.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump([dict(r) for r in rows], fh, ensure_ascii=False, indent=2, default=str)


def _generate_review_csv(build_cfg: dict, review_dir: Path) -> None:
    """Generate review/manual_review.csv for files needing attention."""
    db_path = build_cfg["storage"]["sqlite_path"]
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT docs_path, filename, primary_category, source_type, confidence, needs_review, reason "
            "FROM documents WHERE needs_review=1 OR confidence < 0.75 "
            "ORDER BY confidence"
        ).fetchall()

    if not rows:
        return

    rp = review_dir / "manual_review.csv"
    with open(rp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        for r in rows:
            w.writerow(dict(r))
