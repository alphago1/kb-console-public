"""
Content-aware classification: Full-text → LLM summaries → LLM classification.

Two rounds:
  Round 1: 8-concurrent LLM calls. Each batch of ~35 files → LLM writes 100-200 char summaries.
  Round 2: 1 LLM call. All summaries → LLM classifies into N categories. No preset names.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from openai import OpenAI

from extractor import extract_text

# ═══════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════
CONCURRENCY = 8
FILES_PER_BATCH = 35
MODEL = "deepseek-v4-flash"
KNOWN_CATEGORIES = [
    "交易复盘", "交易系统与方法论", "交易心理与情绪", "交易记录",
    "AI与工具化", "个人随笔与自我观察", "项目想法与反复出现的问题",
    "写作素材与可成文内容", "认知变化记录",
    "外部资料与待排除内容", "无法判断", "_weekly_inbox",
]

# ═══════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════


def _get_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def _call_llm(prompt: str, client: OpenAI, max_retries: int = 3, timeout: int = 120) -> dict:
    """Call DeepSeek, extract JSON. Retries on parse failure."""
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, timeout=timeout,
            )
            content = resp.choices[0].message.content or ""
            m = re.search(r'\{[\s\S]*\}', content)
            if m:
                return json.loads(m.group())
            return json.loads(content)
        except json.JSONDecodeError as e:
            last_err = e
            time.sleep(1)
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"LLM failed after {max_retries} retries: {last_err}")


def _load_config(config_path: Optional[str] = None) -> dict:
    if config_path:
        p = Path(config_path)
    else:
        # Try common locations
        for candidate in ["config.yaml", "kb_tool/config.yaml", "../config.yaml"]:
            if os.path.exists(candidate):
                p = Path(candidate)
                break
        else:
            raise FileNotFoundError("Cannot find config.yaml — pass --config explicitly")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_full_texts(path: str) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def _extract_gt_from_path(parent_folder: str) -> Optional[str]:
    """Extract ground truth category from docs/ folder structure."""
    known = set(KNOWN_CATEGORIES)
    parts = parent_folder.replace("\\", "/").split("/")
    for part in parts:
        if part in known:
            return part
    return None


# ═══════════════════════════════════════════════════════
# Round 1: Full-text → LLM Summaries (8 concurrent)
# ═══════════════════════════════════════════════════════


def build_summary_prompt(batch: list[dict], batch_idx: int, total_batches: int) -> str:
    lines = [
        "你是文档摘要专家。请为下面每个文件写一个 100-200 字的中文摘要。",
        "",
        "摘要必须包含：",
        "1. 核心主题（一句话）",
        "2. 关键内容（2-3 个要点）",
        "3. 文档类型标签（复盘/笔记/分析/草稿/课程/转写/日志/其他）",
        "",
        f"批次 {batch_idx+1}/{total_batches}，共 {len(batch)} 个文件：",
        "",
    ]
    for i, f in enumerate(batch, 1):
        text = f.get("text", "")
        fn = f.get("filename", f"file_{i}")
        lines.append(f"### 文件{i}: `{fn}`")
        lines.append(text[:8000])  # cap per file at 8000 chars
        lines.append("")

    lines.extend([
        "## 输出格式（严格 JSON，不要输出其他内容）",
        "```json",
        "{",
        '  "summaries": [',
        '    {"filename": "xxx.docx", "summary": "100-200字中文摘要..."},',
        "    ...",
        "  ]",
        "}",
        "```",
        f"共 {len(batch)} 个文件，每个文件一条摘要。",
    ])
    return "\n".join(lines)


def _summarize_batch(batch: list[dict], batch_idx: int, total_batches: int, client: OpenAI) -> list[dict]:
    """Summarize one batch. Returns [{filename, summary}, ...]. Falls back to first-200-chars."""
    prompt = build_summary_prompt(batch, batch_idx, total_batches)
    try:
        resp = _call_llm(prompt, client)
        return resp.get("summaries", [])
    except Exception as e:
        print(f"  Batch {batch_idx+1} FAILED after retries: {e}")
        # Fallback: first 200 chars as summary
        fallback = []
        for f in batch:
            text = f.get("text", "")
            fallback.append({
                "filename": f.get("filename", ""),
                "summary": text[:200] + ("..." if len(text) > 200 else ""),
            })
        return fallback


def generate_summaries_concurrent(
    full_texts: list[dict],
    client: OpenAI,
    concurrency: int = CONCURRENCY,
    batch_size: int = FILES_PER_BATCH,
) -> list[dict]:
    """Generate LLM summaries for all files, 8 concurrent."""
    # Filter to files with actual text
    valid = [f for f in full_texts if f.get("text") and len(f["text"].strip()) > 20]
    empty = [f for f in full_texts if not f.get("text") or len(f["text"].strip()) <= 20]

    batches = [valid[i:i+batch_size] for i in range(0, len(valid), batch_size)]
    total_batches = len(batches)

    print(f"\n  Round 1: Summarizing {len(valid)} files in {total_batches} batches ({concurrency} concurrent)...")

    all_summaries: list[dict] = []
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_summarize_batch, batch, i, total_batches, client): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            bi = futures[future]
            try:
                result = future.result()
                all_summaries.extend(result)
                print(f"  Batch {bi+1}/{total_batches} done: {len(result)} summaries")
            except Exception as e:
                print(f"  Batch {bi+1} crashed: {e}")

    # Add empty files with fallback summaries
    for f in empty:
        all_summaries.append({
            "filename": f.get("filename", ""),
            "summary": f"(空文件, {f.get('text_len', 0)} 字符)",
        })

    elapsed = time.perf_counter() - t0
    print(f"  Round 1 done: {len(all_summaries)} summaries in {elapsed:.1f}s")
    return all_summaries


# ═══════════════════════════════════════════════════════
# Round 2: Summaries → Classification (1 call)
# ═══════════════════════════════════════════════════════


def build_classification_prompt(summaries: list[dict], target_count: int, gt_info: dict = None) -> str:
    lines = [
        f"你是知识库自动分类系统。下面有 {len(summaries)} 个文件及其 LLM 摘要。",
        f"请根据摘要内容，将文件分为恰好 **{target_count}** 个分类。",
        "",
        "要求：",
        f"1. 你自己命名每个分类（中文，2-6字），不给定任何预设类别名",
        "2. 每个文件必须且只能属于一个分类",
        "3. 分类应该基于文件的实际内容/主题，不是基于文件名",
        "4. 如果某个文件确实无法归类，放入 'uncertain_indices'",
        "",
        "## 文件列表",
        "",
    ]
    for i, s in enumerate(summaries, 1):
        fn = s.get("filename", "")
        summary = s.get("summary", "")
        lines.append(f"{i}. `{fn}`")
        lines.append(f"   摘要: {summary}")
        lines.append("")

    lines.extend([
        "## 输出格式（严格 JSON）",
        "```json",
        "{",
        f'  "categories": [',
        f'    {{"name": "分类名", "description": "该分类包含什么内容", "file_indices": [1,5,8]}}',
        f"  ],",
        f'  "uncertain_indices": [],',
        f'  "summary": "本次分类总结"',
        "}",
        "```",
        f"恰好 {target_count} 个分类。总共 {len(summaries)} 个文件，索引从 1 到 {len(summaries)}，不能遗漏。",
    ])
    return "\n".join(lines)


def classify_from_summaries(
    summaries: list[dict],
    target_count: int,
    client: OpenAI,
) -> dict:
    """One LLM call: summaries → categories + file assignments."""
    print(f"\n  Round 2: Classifying {len(summaries)} files into {target_count} categories...")
    t0 = time.perf_counter()

    prompt = build_classification_prompt(summaries, target_count)
    result = _call_llm(prompt, client, timeout=180)

    elapsed = time.perf_counter() - t0
    cats = result.get("categories", [])
    uncertain = result.get("uncertain_indices", [])
    print(f"  Round 2 done: {len(cats)} categories, {len(uncertain)} uncertain in {elapsed:.1f}s")
    for c in cats:
        print(f"    [{c['name']}] {c.get('description','')[:60]} → {len(c.get('file_indices',[]))} files")

    return result


# ═══════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════


def build_assignments(
    summaries: list[dict],
    classification: dict,
    inventory_records: list[dict],
) -> list[dict]:
    """Build per-file assignments from classification result, merge with GT."""
    idx_to_cat: dict[int, str] = {}
    for cat in classification.get("categories", []):
        for idx in cat.get("file_indices", []):
            idx_to_cat[idx] = cat["name"]
    for idx in classification.get("uncertain_indices", []):
        idx_to_cat[idx] = "待分类"

    # Build path lookup from inventory
    path_map = {}
    gt_map = {}
    for r in inventory_records:
        path_map[r.get("filename", "")] = r.get("path", "")
        gt_map[r.get("filename", "")] = _extract_gt_from_path(r.get("parent_folder", ""))

    assignments = []
    for i, s in enumerate(summaries):
        file_idx = i + 1
        fn = s.get("filename", "")
        predicted = idx_to_cat.get(file_idx, "待分类")
        gt = gt_map.get(fn)
        assignments.append({
            "file_id": s.get("file_id", fn),
            "filename": fn,
            "predicted_category": predicted,
            "ground_truth": gt,
            "match": predicted == gt if gt else None,
            "summary": s.get("summary", ""),
            "source_path": path_map.get(fn, ""),
        })

    return assignments


def compute_metrics(assignments: list[dict]) -> dict:
    labeled = [a for a in assignments if a["ground_truth"] is not None]
    total = len(labeled)
    correct = sum(1 for a in labeled if a["match"])
    accuracy = correct / total if total > 0 else 0

    # Per-category precision/recall
    cats = set(a["predicted_category"] for a in assignments) | set(
        a["ground_truth"] for a in labeled if a["ground_truth"]
    )
    per_cat = {}
    for cat in sorted(cats):
        tp = sum(1 for a in labeled if a["ground_truth"] == cat and a["predicted_category"] == cat)
        fp = sum(1 for a in labeled if a["ground_truth"] != cat and a["predicted_category"] == cat)
        fn = sum(1 for a in labeled if a["ground_truth"] == cat and a["predicted_category"] != cat)
        p = tp / (tp + fp) if (tp + fp) > 0 else 0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        per_cat[cat] = {"precision": round(p, 3), "recall": round(r, 3),
                        "f1": round(f1, 3), "support": tp + fn, "tp": tp, "fp": fp, "fn": fn}

    # Confusion
    confusion = defaultdict(lambda: defaultdict(int))
    for a in labeled:
        confusion[a["ground_truth"]][a["predicted_category"]] += 1

    return {
        "total": len(assignments), "labeled": total, "correct": correct,
        "accuracy": round(accuracy, 4), "per_category": per_cat,
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def write_outputs(
    summaries: list[dict],
    classification: dict,
    assignments: list[dict],
    metrics: dict,
    output_dir: Path,
    elapsed_ms: float,
) -> list[str]:
    out = output_dir
    out.mkdir(parents=True, exist_ok=True)
    written = []

    # 1. Summaries
    sp = out / "file_summaries.json"
    sp.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(str(sp))

    # 2. Classification result
    cp = out / "classification_result.json"
    cp.write_text(json.dumps(classification, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(str(cp))

    # 3. Assignments JSONL
    ap = out / "final_assignments.jsonl"
    with open(ap, "w", encoding="utf-8") as f:
        for a in assignments:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    written.append(str(ap))

    # 4. Categories YAML
    cats = classification.get("categories", [])
    cat_data = {"categories": {c["name"]: {"description": c.get("description", ""),
        "file_count": len(c.get("file_indices", []))} for c in cats}}
    yp = out / "categories.yaml"
    yp.write_text(yaml.dump(cat_data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    written.append(str(yp))

    # 5. CSV
    csv_path = out / "clustered_files.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=["file_id", "filename", "predicted_category",
                                            "ground_truth", "match", "summary"])
        w.writeheader()
        for a in assignments:
            w.writerow({k: a.get(k, "") for k in ["file_id", "filename", "predicted_category",
                                                     "ground_truth", "match", "summary"]})
    written.append(str(csv_path))

    # 6. Report
    report = build_report(assignments, classification, metrics, elapsed_ms)
    rp = out / "cluster_report.md"
    rp.write_text(report, encoding="utf-8")
    written.append(str(rp))

    return written


def build_report(assignments: list[dict], classification: dict, metrics: dict, elapsed_ms: float) -> str:
    cats = classification.get("categories", [])
    lines = [
        "# 内容感知分类报告 — 全文理解 + LLM 摘要 + 分类",
        "",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 总耗时: {elapsed_ms/1000:.1f}s",
        f"> 方法: 全文 → 8并发 LLM 摘要(100-200字) → LLM 分类",
        f"> Target: {len(cats)} 类 (每30文件1类)",
        "",
        "## 1. 总体结果",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 总文件 | {metrics['total']} |",
        f"| 有 GT 文件 | {metrics['labeled']} |",
        f"| 正确 | {metrics['correct']} |",
        f"| 准确率 | {metrics['accuracy']:.1%} |",
        f"| 发现分类 | {len(cats)} |",
        "",
        "## 2. 发现的分类",
        "",
        "| # | 分类名 | 描述 | 文件数 |",
        "|---|--------|------|--------|",
    ]
    for i, c in enumerate(cats, 1):
        lines.append(f"| {i} | {c['name']} | {c.get('description','')[:60]} | {len(c.get('file_indices',[]))} |")

    lines.extend([
        "",
        "## 3. 每分类代表文件",
        "",
    ])
    for c in cats:
        indices = c.get("file_indices", [])[:5]
        cat_assignments = [assignments[i-1] for i in indices if i <= len(assignments)]
        lines.append(f"### {c['name']}")
        lines.append("| 文件 | GT | 摘要片段 |")
        lines.append("|------|-----|----------|")
        for a in cat_assignments:
            match = "✅" if a.get("match") else ("❌" if a.get("match") is False else "—")
            lines.append(f"| {a['filename'][:40]} | {a.get('ground_truth','?')} {match} | {a['summary'][:60]}... |")
        lines.append("")

    lines.extend([
        "## 4. Per-Category 指标",
        "",
        "| 类别 | Precision | Recall | F1 | Support |",
        "|------|-----------|--------|-----|---------|",
    ])
    for cat, m in sorted(metrics["per_category"].items()):
        lines.append(f"| {cat} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {m['support']} |")

    # Confusion top entries
    lines.extend(["", "## 5. 混淆矩阵", ""])
    confusion = metrics["confusion"]
    all_gt = sorted(confusion.keys())
    all_pred = sorted(set(a["predicted_category"] for a in assignments))
    lines.append("| GT \\ Pred | " + " | ".join(all_pred[:8]) + " |")
    lines.append("|" + "---|" * (min(len(all_pred), 8) + 1))
    for gt in all_gt[:12]:
        row = [str(confusion[gt].get(pred, 0)) for pred in all_pred[:8]]
        lines.append(f"| {gt} | " + " | ".join(row) + " |")

    lines.extend([
        "",
        "---",
        "*两轮 LLM 分类：第1轮 8并发全文摘要 → 第2轮摘要分类*",
    ])
    return "\n".join(lines) + "\n"


def copy_to_folders(assignments: list[dict], output_dir: Path) -> list[str]:
    """Copy files into consolidated/<category>/ folders."""
    root = output_dir / "consolidated"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    copied = 0
    for a in assignments:
        cat = a["predicted_category"]
        safe_cat = re.sub(r'[<>:"/\\|?*]', '_', cat)[:60]
        cat_dir = root / safe_cat
        cat_dir.mkdir(exist_ok=True)

        src = a.get("source_path", "")
        if src and os.path.exists(src):
            try:
                shutil.copy2(src, cat_dir / a["filename"])
                copied += 1
            except Exception:
                pass

    folders = [str(d) for d in sorted(root.iterdir()) if d.is_dir()]
    print(f"\n  Copied {copied}/{len(assignments)} files to {len(folders)} category folders")
    return folders


# ═══════════════════════════════════════════════════════
# Main entry
# ═══════════════════════════════════════════════════════


def run_experiment(
    inventory_path: str,
    output_dir: str,
    target: Optional[int] = None,
    full_texts_path: Optional[str] = None,
    config_path: Optional[str] = None,
    concurrency: int = CONCURRENCY,
    batch_size: int = FILES_PER_BATCH,
    dry_run: bool = False,
) -> dict:
    t0 = time.perf_counter()

    inv_records: list[dict] = []
    with open(inventory_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                inv_records.append(json.loads(line))

    if full_texts_path and os.path.exists(full_texts_path):
        full_texts = _load_full_texts(full_texts_path)
    else:
        print("Extracting full text from files...")
        cfg = _load_config(config_path) if config_path else _load_config()
        full_texts = []
        for r in inv_records:
            text, _, _, err = extract_text(cfg, r["path"], r.get("extension", ""))
            full_texts.append({
                "file_id": r["file_id"], "filename": r["filename"],
                "path": r["path"], "text": text or "", "text_len": len(text or ""),
            })

    total_files = len(full_texts)
    if target is None:
        target = max(5, math.ceil(total_files / 30))
    print(f"Files: {total_files} | Target: {target} categories | Concurrency: {concurrency}")

    if dry_run:
        return {"status": "dry_run", "total_files": total_files, "target": target}

    client = _get_client()

    # Round 1: Summarization (concurrent)
    summaries = generate_summaries_concurrent(full_texts, client, concurrency, batch_size)
    fn_to_id = {f["filename"]: f["file_id"] for f in full_texts}
    for s in summaries:
        s["file_id"] = fn_to_id.get(s.get("filename", ""), "")

    # Round 2: Classification
    classification = classify_from_summaries(summaries, target, client)

    # Build assignments with raw LLM categories
    raw_assignments = build_assignments(summaries, classification, inv_records)

    # Map LLM categories → GT via majority vote (for accuracy comparison)
    # Build co-occurrence: LLM_category → {GT: count}
    cooccur: dict[str, Counter] = defaultdict(Counter)
    for a in raw_assignments:
        if a.get("ground_truth"):
            cooccur[a["predicted_category"]][a["ground_truth"]] += 1

    cluster_to_gt: dict[str, str] = {}
    for cl_name, gt_counts in cooccur.items():
        if gt_counts:
            cluster_to_gt[cl_name] = gt_counts.most_common(1)[0][0]

    # Apply mapping
    assignments = []
    for a in raw_assignments:
        mapped_gt = cluster_to_gt.get(a["predicted_category"], a["predicted_category"])
        assignments.append({
            **a,
            "predicted_category": a["predicted_category"],
            "mapped_gt": mapped_gt,
            "match": mapped_gt == a["ground_truth"] if a["ground_truth"] else None,
        })

    # Metrics using mapped categories
    metrics = compute_metrics(assignments)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    output_files = write_outputs(summaries, classification, assignments, metrics, out, elapsed_ms)
    folders = copy_to_folders(assignments, out)

    return {
        "status": "ok",
        "total_files": total_files,
        "target": target,
        "categories_found": len(classification.get("categories", [])),
        "accuracy": metrics["accuracy"],
        "correct": metrics["correct"],
        "labeled": metrics["labeled"],
        "elapsed_ms": elapsed_ms,
        "cluster_to_gt_mapping": cluster_to_gt,
        "output_dir": str(out),
        "output_files": output_files,
        "consolidated_folders": len(folders),
    }


# ═══════════════════════════════════════════════════════
# CLI wrapper
# ═══════════════════════════════════════════════════════

def run_clustering(
    inventory_path: str,
    output_dir: str,
    llm_provider=None,
    use_llm: bool = True,
    target: Optional[int] = None,
    full_texts_path: Optional[str] = None,
) -> dict:
    return run_experiment(
        inventory_path=inventory_path,
        output_dir=output_dir,
        target=target,
        full_texts_path=full_texts_path,
        dry_run=not use_llm,
    )
