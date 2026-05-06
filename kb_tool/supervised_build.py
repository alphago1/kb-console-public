"""
Supervised Knowledge Base Builder.

Takes user-approved policies (category schema, tag ontology, classification rules,
exclusion rules, source type policies) and applies them to ALL files to produce
the official knowledge base: SQLite database, dashboard, stats, and reports.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

# ═══════════════════════════════════════════════════════════
# Policy Loader
# ═══════════════════════════════════════════════════════════


def load_policies(policy_dir: str) -> dict:
    """Load all 5 policy YAML files. Returns unified policy dict."""
    d = Path(policy_dir)
    policies = {}

    for name in ["category_schema_v1", "tag_ontology_v1", "classification_rules_v1",
                  "exclusion_rules_v1", "source_type_policy_v1"]:
        path = d / f"{name}.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                policies[name] = yaml.safe_load(f)
        else:
            policies[name] = {}

    return policies


def build_rule_index(policies: dict) -> dict:
    """Build lookup structures from policies for fast classification."""
    rules = {"merge_map": {}, "reclassify_map": {}, "excluded_cats": set(),
             "approved_cats": set(), "tag_index": set(), "source_patterns": []}

    # Category schema
    schema = policies.get("category_schema_v1", {}).get("categories", [])
    for cat in schema:
        status = str(cat.get("status", ""))
        name = cat.get("name", "")
        # merged_into:X → this category is merged INTO X (remap files to X)
        if "merged_into:" in status:
            target = status.split("merged_into:", 1)[-1].strip()
            rules["merge_map"][name] = target
        # approved / partially_reclassified / unreviewed → all valid categories
        elif status in ("approved", "unreviewed", "partially_reclassified"):
            rules["approved_cats"].add(name)

    # Classification rules
    cls_rules = policies.get("classification_rules_v1", {}).get("rules", [])
    for r in cls_rules:
        if r.get("type") == "merge":
            for src in r.get("sources", []):
                rules["merge_map"][src] = r.get("target", src)
        elif r.get("type") == "reclassification":
            pattern = r.get("pattern", "")
            fn = pattern.replace("文件 ", "").strip()
            rules["reclassify_map"][fn] = r.get("to", "")

    # Exclusion rules
    exc = policies.get("exclusion_rules_v1", {}).get("excluded_categories", [])
    for e in exc:
        rules["excluded_cats"].add(e.get("name", ""))

    # Tag ontology
    tags = policies.get("tag_ontology_v1", {}).get("tags", [])
    rules["tag_index"] = {t.get("name", "") for t in tags}

    # Source type policies
    src_pols = policies.get("source_type_policy_v1", {}).get("source_type_policies", [])
    rules["source_patterns"] = src_pols

    return rules


# ═══════════════════════════════════════════════════════════
# Classification Engine
# ═══════════════════════════════════════════════════════════


def classify_file(record: dict, rules: dict, llm_category: Optional[str] = None) -> dict:
    """
    Classify a single file using policy rules.
    Returns {category, tags, confidence, excluded, reason}.
    """
    fn = record.get("filename", "")
    ext = record.get("extension", "")
    parent = record.get("parent_folder", "")
    tokens = record.get("filename_tokens", [])
    size = record.get("size", 0)
    llm_cat = llm_category or ""

    # Step 1: Apply merge rules (LLM category → user-approved category)
    category = llm_cat
    if category in rules["merge_map"]:
        category = rules["merge_map"][category]

    # Step 2: Apply per-file reclassification
    if fn in rules["reclassify_map"]:
        category = rules["reclassify_map"][fn]

    # Step 3: Source-type pattern matching (for files without LLM category)
    if not category:
        for sp in rules["source_patterns"]:
            pattern_type = sp.get("pattern", "")
            if _match_source_type(fn, pattern_type):
                category = sp.get("dominant_category", "")
                break

    # Step 4: Tag assignment
    tags = _assign_tags(fn, tokens, category, rules["tag_index"])

    # Step 5: Exclusion check
    excluded = False
    exclude_reason = ""
    if category in rules["excluded_cats"]:
        excluded = True
        exclude_reason = f"政策排除: 类别 '{category}' 标记为排除"
    if size == 0:
        excluded = True
        exclude_reason = "空文件"

    # Step 6: Confidence
    confidence = 1.0
    if category in rules["excluded_cats"]:
        confidence = 0.9  # High confidence exclusion
    if category in rules["approved_cats"]:
        confidence = 0.95
    if not llm_cat and not category:
        confidence = 0.1
    if fn in rules["reclassify_map"]:
        confidence = 0.85

    return {
        "category": category or "未分类",
        "tags": tags,
        "confidence": confidence,
        "excluded": excluded,
        "exclude_reason": exclude_reason,
        "llm_original_category": llm_cat,
    }


def _match_source_type(fn: str, pattern_type: str) -> bool:
    patterns = {
        "transcript": ["转写", "文稿", "meeting", ".mp4", ".mp3", ".m4a"],
        "leetcode_algorithm": ["题解", "并查集", "GetMapping", "Lowbit", "def read"],
        "draft": ["草稿", "未完", "待完成"],
        "review": ["复盘", "简评"],
    }
    keywords = patterns.get(pattern_type, [])
    return any(k in fn for k in keywords)


def _assign_tags(fn: str, tokens: list[str], category: str, tag_index: set[str]) -> list[str]:
    """Assign tags from ontology + auto-extract from filename."""
    assigned = []
    fn_lower = fn.lower()

    # Check against known tag ontology
    for tag in tag_index:
        if tag.lower() in fn_lower or tag in tokens:
            assigned.append(tag)

    # Auto-extract: tokens that look like meaningful tags (Chinese 2-4 chars, English >= 3)
    for t in tokens:
        if t not in assigned and len(t) >= 2:
            # Filter out dates and common words
            if not t.isdigit() and not re.match(r'^\d{2,4}[-/]\d{2}', t):
                assigned.append(t)

    # Category-derived domain tag
    domain_map = {
        "股票交易": "交易", "法律AI": "AI", "AI应用": "AI",
        "机器学习": "AI", "游戏动漫": "娱乐", "职业规划": "职业",
        "宏观政策": "政策", "产品设计": "设计",
    }
    domain = domain_map.get(category, "")
    if domain and domain not in assigned:
        assigned.insert(0, domain)

    return assigned[:10]


# ═══════════════════════════════════════════════════════════
# Content Sampler (for low-confidence files)
# ═══════════════════════════════════════════════════════════


def sample_low_confidence(
    results: list[dict],
    inventory: list[dict],
    threshold: float = 0.5,
    client=None,
) -> list[dict]:
    """
    For files with confidence < threshold, optionally use LLM to reclassify.
    Without LLM client, just flag them as needs_review.
    """
    low_conf = []
    for i, r in enumerate(results):
        if r["confidence"] < threshold and not r["excluded"]:
            inv = inventory[i] if i < len(inventory) else {}
            # Try to read content sample
            content_sample = ""
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from extractor import extract_text
                cfg_path = Path(__file__).parent / "config.yaml"
                if cfg_path.exists():
                    with open(cfg_path, encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                    text, _, _, _ = extract_text(cfg, inv.get("path", ""), inv.get("extension", ""))
                    content_sample = (text or "")[:500]
            except Exception:
                pass

            r["needs_review"] = True
            r["content_sample"] = content_sample[:200]
            low_conf.append(r)
        else:
            r["needs_review"] = False
            r["content_sample"] = ""

    return low_conf


# ═══════════════════════════════════════════════════════════
# SQLite Builder
# ═══════════════════════════════════════════════════════════


def build_sqlite(results: list[dict], inventory: list[dict], output_dir: Path,
                 main_sqlite_path: Optional[str] = None) -> str:
    """Build or update the main kb.sqlite3 with supervised classification results.

    When main_sqlite_path is provided, writes into the main knowledge-base database
    (the same one used by KBDatabase / weekly_organize) using the standard documents
    table schema.  Otherwise falls back to a standalone kb.sqlite in output_dir.
    """
    if main_sqlite_path:
        db_path = Path(main_sqlite_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure standard schema exists
        try:
            from database import KBDatabase
            # Use a minimal cfg just for init
            KBDatabase({"storage": {"sqlite_path": str(db_path)}}).init()
        except Exception:
            pass
    else:
        db_path = output_dir / "kb.sqlite"

    conn = sqlite3.connect(str(db_path))

    # Ensure main-schema columns exist (idempotent, from KBDatabase.init)
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "primary_category" not in existing_cols:
        # Fallback: create minimal main-schema documents table
        conn.execute("""
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
            )
        """)

    run_id = f"supervised-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    now = datetime.now(timezone.utc).isoformat()

    for i, r in enumerate(results):
        inv = inventory[i] if i < len(inventory) else {}
        file_path = inv.get("path", "")
        tags_json = json.dumps(r["tags"], ensure_ascii=False) if r.get("tags") else "[]"
        include_in_kb = 0 if r["excluded"] else 1

        conn.execute("""
            INSERT INTO documents(
                path, source_path, filename, extension, size_bytes,
                filesystem_created_time, filesystem_modified_time,
                derived_time_month, time_month,
                primary_category, secondary_category, topic_tags,
                confidence, include_in_kb, exclude_reason, needs_review,
                sampled_text, reason,
                run_id, processed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                source_path=excluded.source_path,
                filename=excluded.filename,
                extension=excluded.extension,
                size_bytes=excluded.size_bytes,
                filesystem_created_time=excluded.filesystem_created_time,
                filesystem_modified_time=excluded.filesystem_modified_time,
                derived_time_month=excluded.derived_time_month,
                time_month=excluded.time_month,
                primary_category=excluded.primary_category,
                secondary_category=excluded.secondary_category,
                topic_tags=excluded.topic_tags,
                confidence=excluded.confidence,
                include_in_kb=excluded.include_in_kb,
                exclude_reason=excluded.exclude_reason,
                needs_review=excluded.needs_review,
                sampled_text=excluded.sampled_text,
                reason=excluded.reason,
                run_id=excluded.run_id,
                processed_at=excluded.processed_at
        """, (
            file_path,                    # path (PRIMARY KEY)
            file_path,                    # source_path (same as path for supervised)
            inv.get("filename", ""),
            inv.get("extension", ""),
            inv.get("size", 0),
            inv.get("created_time", ""),
            inv.get("modified_time", ""),
            inv.get("time_month", ""),
            inv.get("time_month", ""),
            r["category"],                # primary_category
            r.get("llm_original_category", ""),  # secondary_category
            tags_json,                    # topic_tags
            r["confidence"],
            include_in_kb,
            r.get("exclude_reason", ""),
            1 if r.get("needs_review") else 0,
            r.get("content_sample", ""),  # sampled_text
            "supervised build",           # reason
            run_id,
            now,
        ))

    conn.commit()
    conn.close()
    return str(db_path)


# ═══════════════════════════════════════════════════════════
# Output Generators
# ═══════════════════════════════════════════════════════════


def write_documents_csv(results: list[dict], inventory: list[dict], output_dir: Path) -> str:
    p = output_dir / "documents.csv"
    fields = ["file_id", "filename", "category", "tags", "confidence",
              "excluded", "exclude_reason", "needs_review"]
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(results):
            inv = inventory[i] if i < len(inventory) else {}
            w.writerow({
                "file_id": inv.get("file_id", ""), "filename": inv.get("filename", ""),
                "category": r["category"], "tags": "|".join(r["tags"]),
                "confidence": r["confidence"], "excluded": r["excluded"],
                "exclude_reason": r.get("exclude_reason", ""),
                "needs_review": r.get("needs_review", False),
            })
    return str(p)


def write_document_tags_jsonl(results: list[dict], inventory: list[dict], output_dir: Path) -> str:
    p = output_dir / "document_tags.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for i, r in enumerate(results):
            inv = inventory[i] if i < len(inventory) else {}
            f.write(json.dumps({
                "file_id": inv.get("file_id", ""), "filename": inv.get("filename", ""),
                "category": r["category"], "tags": r["tags"], "confidence": r["confidence"],
            }, ensure_ascii=False) + "\n")
    return str(p)


def write_tag_stats(results: list[dict], output_dir: Path) -> str:
    p = output_dir / "tag_stats.csv"
    tag_counter = Counter()
    for r in results:
        for t in r["tags"]:
            tag_counter[t] += 1
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "file_count"])
        for tag, count in tag_counter.most_common():
            w.writerow([tag, count])
    return str(p)


def write_category_stats(results: list[dict], output_dir: Path) -> str:
    p = output_dir / "category_stats.csv"
    cat_counter = Counter()
    cat_size = defaultdict(int)
    cat_tags = defaultdict(set)
    for r in results:
        if not r["excluded"]:
            cat_counter[r["category"]] += 1
            cat_tags[r["category"]].update(r["tags"])
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "file_count", "unique_tags", "pct"])
        total = sum(cat_counter.values()) or 1
        for cat, count in cat_counter.most_common():
            w.writerow([cat, count, len(cat_tags.get(cat, set())), f"{count/total*100:.1f}%"])
    return str(p)


def write_excluded_files(results: list[dict], inventory: list[dict], output_dir: Path) -> str:
    p = output_dir / "excluded_files.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "category", "exclude_reason"])
        for i, r in enumerate(results):
            if r["excluded"]:
                inv = inventory[i] if i < len(inventory) else {}
                w.writerow([inv.get("filename", ""), r["category"], r.get("exclude_reason", "")])
    return str(p)


def write_low_confidence_files(results: list[dict], inventory: list[dict], output_dir: Path) -> str:
    p = output_dir / "low_confidence_files.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "category", "confidence", "content_sample"])
        for i, r in enumerate(results):
            if r.get("needs_review"):
                inv = inventory[i] if i < len(inventory) else {}
                w.writerow([inv.get("filename", ""), r["category"],
                           r["confidence"], r.get("content_sample", "")[:100]])
    return str(p)


def build_dashboard(results: list[dict], output_dir: Path) -> str:
    """Generate a simple HTML dashboard."""
    cat_counter = Counter(r["category"] for r in results if not r["excluded"])
    excluded_count = sum(1 for r in results if r["excluded"])
    total = len(results)
    low_conf_count = sum(1 for r in results if r.get("needs_review"))

    tag_counter = Counter()
    for r in results:
        for t in r["tags"]:
            tag_counter[t] += 1
    top_tags = tag_counter.most_common(20)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cat_rows = "".join(
        f"<tr><td>{cat}</td><td>{count}</td><td>{count/total*100:.1f}%</td></tr>"
        for cat, count in cat_counter.most_common(15)
    )
    tag_rows = "".join(
        f"<tr><td>{tag}</td><td>{count}</td></tr>"
        for tag, count in top_tags
    )

    html = f"""<!doctype html>
<html lang="zh-cn">
<head><meta charset="utf-8"/><title>Supervised KB Dashboard</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#f8f9fa}}
.card{{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.kpi{{display:flex;gap:16px}}
.kpi-item{{flex:1;text-align:center;padding:12px;background:#e9ecef;border-radius:6px}}
.kpi-value{{font-size:28px;font-weight:700;color:#0d6efd}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #dee2e6;padding:6px 10px;font-size:13px}}
th{{background:#f1f3f5}}
</style></head>
<body>
<h1>Supervised Knowledge Base</h1>
<p>Generated: {now} | Policy-driven classification | {total} files processed</p>
<div class="kpi">
<div class="kpi-item"><div class="kpi-value">{total}</div>Total Files</div>
<div class="kpi-item"><div class="kpi-value">{len(cat_counter)}</div>Categories</div>
<div class="kpi-item"><div class="kpi-value">{len(top_tags)}</div>Unique Tags</div>
<div class="kpi-item"><div class="kpi-value">{excluded_count}</div>Excluded</div>
<div class="kpi-item"><div class="kpi-value">{low_conf_count}</div>Needs Review</div>
</div>
<div class="card"><h2>Category Distribution</h2><table><tr><th>Category</th><th>Files</th><th>%</th></tr>{cat_rows}</table></div>
<div class="card"><h2>Top 20 Tags</h2><table><tr><th>Tag</th><th>Files</th></tr>{tag_rows}</table></div>
</body></html>"""

    dashboard_dir = output_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    dp = dashboard_dir / "index.html"
    dp.write_text(html, encoding="utf-8")
    return str(dp)


def build_report(results: list[dict], inventory: list[dict], output_dir: Path, elapsed_ms: float) -> str:
    """Generate supervised_build_report.md."""
    total = len(results)
    excluded = sum(1 for r in results if r["excluded"])
    included = total - excluded
    low_conf = sum(1 for r in results if r.get("needs_review"))
    cat_counter = Counter(r["category"] for r in results if not r["excluded"])
    tag_counter = Counter()
    for r in results:
        for t in r["tags"]:
            tag_counter[t] += 1

    lines = [
        "# Supervised KB Build Report",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> Build time: {elapsed_ms/1000:.1f}s",
        f"> Method: Policy-driven (user-reviewed rules)",
        "",
        "## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total files | {total} |",
        f"| Included | {included} |",
        f"| Excluded | {excluded} |",
        f"| Categories | {len(cat_counter)} |",
        f"| Unique tags | {len(tag_counter)} |",
        f"| Low confidence | {low_conf} |",
        "",
        "## Category Distribution",
        "| Category | Files | % |",
        "|----------|-------|---|",
    ]
    for cat, count in cat_counter.most_common(20):
        lines.append(f"| {cat} | {count} | {count/max(included,1)*100:.1f}% |")

    lines.extend([
        "",
        "## Top Tags",
        "| Tag | Files |",
        "|-----|-------|",
    ])
    for tag, count in tag_counter.most_common(30):
        lines.append(f"| {tag} | {count} |")

    lines.extend([
        "",
        "## Excluded Files",
        f"Total excluded: {excluded}",
        "",
        "| Reason | Count |",
        "|--------|-------|",
    ])
    reason_count = Counter(r.get("exclude_reason", "") for r in results if r["excluded"])
    for reason, count in reason_count.most_common():
        lines.append(f"| {reason} | {count} |")

    lines.extend([
        "",
        "## Low Confidence Files (Needs Review)",
        f"Total: {low_conf}",
        "",
    ])
    if low_conf > 0:
        lines.append("| File | Category | Confidence |")
        lines.append("|------|----------|------------|")
        for i, r in enumerate(results):
            if r.get("needs_review"):
                inv = inventory[i] if i < len(inventory) else {}
                lines.append(f"| {inv.get('filename','')[:50]} | {r['category']} | {r['confidence']:.2f} |")

    lines.extend(["", "---", "*Policy-driven supervised build*"])
    rp = output_dir / "supervised_build_report.md"
    rp.write_text("\n".join(lines), encoding="utf-8")
    return str(rp)


# ═══════════════════════════════════════════════════════════
# Main Entry
# ═══════════════════════════════════════════════════════════


def build_supervised_kb(
    inventory_path: str,
    policy_dir: str,
    output_dir: str,
    llm_assignments_path: Optional[str] = None,
    sqlite_path: Optional[str] = None,
) -> dict:
    t0 = time.perf_counter()

    # Load
    policies = load_policies(policy_dir)
    rules = build_rule_index(policies)

    inventory = []
    with open(inventory_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                inventory.append(json.loads(line))

    # Load LLM assignments if available (for category mapping)
    llm_cats: dict[str, str] = {}
    if llm_assignments_path and os.path.exists(llm_assignments_path):
        with open(llm_assignments_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    a = json.loads(line)
                    llm_cats[a.get("file_id", a.get("filename", ""))] = a.get("predicted_category", "")

    # Classify all files
    print(f"Classifying {len(inventory)} files with supervised policies...")
    results = []
    for inv in inventory:
        fid = inv.get("file_id", inv.get("filename", ""))
        llm_cat = llm_cats.get(fid, llm_cats.get(inv.get("filename", ""), ""))
        r = classify_file(inv, rules, llm_cat)
        results.append(r)

    # Sample low-confidence
    low_conf = sample_low_confidence(results, inventory, threshold=0.5)
    print(f"  Low confidence: {len(low_conf)} files")

    # Output directory
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. SQLite (writes to main KB database when sqlite_path provided)
    db_path = build_sqlite(results, inventory, out, main_sqlite_path=sqlite_path)
    # 2-7. CSVs + JSONL
    csv_path = write_documents_csv(results, inventory, out)
    tags_jsonl = write_document_tags_jsonl(results, inventory, out)
    tag_stats = write_tag_stats(results, out)
    cat_stats = write_category_stats(results, out)
    exc_csv = write_excluded_files(results, inventory, out)
    low_csv = write_low_confidence_files(results, inventory, out)
    # 8. Dashboard
    dash_path = build_dashboard(results, out)
    # 9. Report
    elapsed_ms = (time.perf_counter() - t0) * 1000
    report_path = build_report(results, inventory, out, elapsed_ms)

    cat_counter = Counter(r["category"] for r in results if not r["excluded"])
    excluded = sum(1 for r in results if r["excluded"])

    return {
        "status": "ok",
        "total_files": len(results),
        "included": len(results) - excluded,
        "excluded": excluded,
        "categories": len(cat_counter),
        "low_confidence": len(low_conf),
        "elapsed_ms": elapsed_ms,
        "output_dir": str(out),
        "output_files": [
            db_path, csv_path, tags_jsonl, tag_stats, cat_stats,
            exc_csv, low_csv, dash_path, report_path,
        ],
    }
