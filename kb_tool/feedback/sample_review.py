"""
Stratified sampling for user review + feedback-driven rule learning.

Takes LLM classification results → picks ≤100 files via 7-principle stratification →
user reviews → system learns category schema, tag ontology, classification/exclusion rules.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

# ═══════════════════════════════════════════════════════════════
# Phase 1: Stratified Sampling
# ═══════════════════════════════════════════════════════════════


def generate_review_sample(
    assignments_path: str,
    output_dir: str,
    max_samples: int = 100,
) -> dict:
    """
    7-principle stratified sampling of LLM classification results.

    1. Each category gets ≥2 files
    2. Large categories get more (proportional, capped)
    3. Low-confidence categories boosted
    4. Suspected-exclusion types sampled
    5. Time period coverage within each category
    6. Boundary files (lowest confidence per category)
    7. Representative files (highest confidence per category)
    """
    assignments = _load_assignments(assignments_path)
    total = len(assignments)
    budget = min(math.ceil(total * 0.1), max_samples)

    # Group by category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for a in assignments:
        by_cat[a["predicted_category"]].append(a)

    cat_names = sorted(by_cat.keys(), key=lambda c: -len(by_cat[c]))

    # Phase 1: Guaranteed minimum per category
    allocation: dict[str, int] = {}
    for cat in cat_names:
        allocation[cat] = min(2, len(by_cat[cat]))
    used = sum(allocation.values())

    # Phase 2: Proportional to category size
    remaining = budget - used
    if remaining > 0:
        total_weight = sum(len(by_cat[c]) for c in cat_names)
        for cat in cat_names:
            extra = max(0, int(remaining * len(by_cat[cat]) / total_weight))
            allocation[cat] = min(allocation[cat] + extra, len(by_cat[cat]))

    # Redistribute leftover
    used = sum(allocation.values())
    leftover = budget - used
    for cat in sorted(cat_names, key=lambda c: -len(by_cat[c])):
        if leftover <= 0:
            break
        can_add = len(by_cat[cat]) - allocation[cat]
        add = min(can_add, leftover)
        allocation[cat] += add
        leftover -= add

    # Phase 3: Boost low-confidence + exclusion categories
    for cat in cat_names:
        files = by_cat[cat]
        avg_match = sum(1 for a in files if a.get("match") == "True" or a.get("match") is True) / max(len(files), 1)
        if avg_match < 0.3 and allocation[cat] < len(files):
            allocation[cat] = min(allocation[cat] + 1, len(files))
        if _is_exclusion_category(cat) and allocation[cat] < len(files):
            allocation[cat] = min(allocation[cat] + 1, len(files))

    # Phase 4-7: Within each category, pick specific files
    sample: list[dict] = []
    for cat in cat_names:
        n = allocation[cat]
        files = by_cat[cat]
        if n == 0:
            continue

        picked: set[int] = set()
        cat_sample: list[dict] = []

        # Sort by confidence desc for representative, asc for boundary
        sorted_by_conf = sorted(files, key=lambda a: _confidence(a), reverse=True)

        # Representative: highest confidence
        if sorted_by_conf and 0 not in picked:
            rep = sorted_by_conf[0]
            cat_sample.append({**rep, "sample_reason": "representative"})
            picked.add(files.index(rep))

        # Boundary: lowest confidence
        if sorted_by_conf and n >= 2:
            bnd = sorted_by_conf[-1]
            idx_b = files.index(bnd)
            if idx_b not in picked:
                cat_sample.append({**bnd, "sample_reason": "boundary"})
                picked.add(idx_b)

        # Time coverage: pick one per distinct time_month
        remaining_slots = n - len(cat_sample)
        if remaining_slots > 0 and picked:
            by_month: dict[str, list[int]] = defaultdict(list)
            for i, a in enumerate(files):
                if i not in picked:
                    m = a.get("time_month", "unknown")
                    by_month[m].append(i)

            # Pick one from each month, round-robin until slots filled
            months = sorted(by_month.keys())
            added = 0
            mi = 0
            while added < remaining_slots and months:
                m = months[mi % len(months)]
                if by_month[m]:
                    idx = by_month[m].pop(0)
                    cat_sample.append({**files[idx], "sample_reason": "time_coverage"})
                    picked.add(idx)
                    added += 1
                mi += 1
                # Avoid infinite loop
                if mi > len(months) * 2:
                    break

        # Fill remaining with top confidence not yet picked
        remaining_slots = n - len(cat_sample)
        if remaining_slots > 0:
            for a in sorted_by_conf:
                idx = files.index(a)
                if idx not in picked:
                    cat_sample.append({**a, "sample_reason": "gap_fill"})
                    picked.add(idx)
                    if len(cat_sample) >= n:
                        break

        sample.extend(cat_sample)

    # Sort output: mismatches first, then by category
    sample.sort(key=lambda a: (a.get("match") != "True" and a.get("match") is not True, a["predicted_category"]))

    # Write CSV
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "review_sample.csv"

    fields = ["file_id", "filename", "current_category", "confidence", "sample_reason",
              "ground_truth", "match", "summary", "user_verdict", "user_tags", "user_notes"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for s in sample:
            row = {k: s.get(k, "") for k in fields}
            # Map from JSONL field names if needed
            if not row["current_category"]:
                row["current_category"] = s.get("predicted_category", "")
            if not row["confidence"]:
                row["confidence"] = _confidence(s)
            w.writerow(row)

    # Stats
    reasons = Counter(s.get("sample_reason", "?") for s in sample)
    cat_counts = Counter(s["predicted_category"] for s in sample)

    return {
        "total_files": total,
        "sampled": len(sample),
        "budget": budget,
        "categories_covered": len(cat_counts),
        "per_category": dict(cat_counts),
        "sample_reasons": dict(reasons),
        "csv_path": str(csv_path),
    }


def _confidence(a: dict) -> float:
    c = a.get("confidence", 0)
    if isinstance(c, str):
        try:
            return float(c)
        except Exception:
            return 0.5
    return float(c) if c else 0.5


def _is_exclusion_category(cat_name: str) -> bool:
    keywords = ["空文件", "杂项", "排除", "噪音", "待分类", "不确定", "合同", "模板"]
    return any(k in cat_name for k in keywords)


def _load_assignments(path: str) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ═══════════════════════════════════════════════════════════════
# Phase 2: Parse User Feedback
# ═══════════════════════════════════════════════════════════════


def parse_user_feedback(review_csv_path: str) -> dict:
    """
    Parse user-edited review CSV.
    Returns structured feedback dict:
    {
      "approved": {cat_name: [file_ids]},
      "reclassified": [{file_id, from_cat, to_cat, user_tags, notes}],
      "merged": [{sources: [catA, catB], target: "new_name"}],
      "split": [{source: cat, targets: [catA, catB], files: [...]}],
      "tags_added": [tag names],
      "tags_removed": [tag names],
    }
    """
    reclassified: list[dict] = []
    approved_cats: dict[str, list[str]] = defaultdict(list)
    merged_hints: list[dict] = []  # user wrote "合并到:X" in verdict
    tags_all: list[str] = []

    with open(review_csv_path, "r", encoding="utf-8-sig", newline="") as cf:
        reader = csv.DictReader(cf)
        for row in reader:
            verdict = (row.get("user_verdict") or "").strip()
            if not verdict:
                continue

            fid = row.get("file_id", "")
            fn = row.get("filename", "")
            cat = row.get("current_category", "")
            tags = [t.strip() for t in (row.get("user_tags") or "").split(",") if t.strip()]
            tags_all.extend(tags)

            # Parse verdict patterns
            # Strip leading emoji/symbols
            clean = verdict.lstrip("✅❌✔✘✓✗⚠️🔴🟢🟡 ")

            if clean.startswith("正确") or verdict.startswith("✅"):
                approved_cats[cat].append(fid)

            elif clean.startswith("应为:") or clean.startswith("应为：") or verdict.startswith("❌"):
                new_cat = clean.replace("应为:", "").replace("应为：", "").strip()
                if new_cat:
                    reclassified.append({
                        "file_id": fid, "filename": fn,
                        "from_category": cat, "to_category": new_cat,
                        "user_tags": tags, "notes": row.get("user_notes", ""),
                    })

            elif "合并到:" in verdict or "合并到：" in verdict:
                target = verdict.split(":", 1)[-1].split("：", 1)[-1].strip()
                merged_hints.append({
                    "source_category": cat,
                    "target_category": target,
                    "file_id": fid,
                })

    return {
        "approved_categories": dict(approved_cats),
        "reclassified": reclassified,
        "merge_hints": merged_hints,
        "tags_suggested": list(set(tags_all)),
        "total_reviewed": len(approved_cats) + len(reclassified) + len(merged_hints),
    }


# ═══════════════════════════════════════════════════════════════
# Phase 3: Learn from Feedback → 6 Output Files
# ═══════════════════════════════════════════════════════════════


def learn_from_feedback(
    assignments_path: str,
    review_csv_path: str,
    output_dir: str,
) -> dict:
    """
    Read user feedback → generate category_schema, tag_ontology,
    classification_rules, exclusion_rules, source_type_policy, learning_report.
    """
    assignments = _load_assignments(assignments_path)
    feedback = parse_user_feedback(review_csv_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_cats = set(a["predicted_category"] for a in assignments)
    cat_files: dict[str, list[str]] = defaultdict(list)
    for a in assignments:
        cat_files[a["predicted_category"]].append(a.get("filename", ""))

    # Collect merge targets
    merges: dict[str, list[str]] = defaultdict(list)
    for m in feedback["merge_hints"]:
        merges[m["target_category"]].append(m["source_category"])

    approved = set(feedback["approved_categories"].keys())
    reclass_from = {r["from_category"] for r in feedback["reclassified"]}
    reclass_to = {r["to_category"] for r in feedback["reclassified"]}
    merged_sources = {s for sources in merges.values() for s in sources}
    merged_targets = set(merges.keys())

    # ── 1. category_schema_v1.yaml ──
    schema = {"generated_at": datetime.now().isoformat(), "categories": []}
    for cat in sorted(all_cats):
        # Determine status: priority: approved > merge_source > merge_target > reclass > unreviewed
        if cat in approved:
            status = "approved"
        elif cat in merged_sources:
            target = [t for t, srcs in merges.items() if cat in srcs][0]
            status = f"merged_into:{target}"
        elif cat in merged_targets:
            # Being a merge target means user explicitly chose it → approved
            status = "approved"
        elif cat in reclass_from:
            status = "partially_reclassified"
        else:
            status = "unreviewed"

        schema["categories"].append({
            "name": cat,
            "status": status,
            "file_count": len(cat_files.get(cat, [])),
            "user_approved_count": len(feedback["approved_categories"].get(cat, [])),
        })
    (out / "category_schema_v1.yaml").write_text(
        yaml.dump(schema, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # ── 2. tag_ontology_v1.yaml ──
    tag_freq = Counter(feedback["tags_suggested"])
    tags_data = {
        "generated_at": datetime.now().isoformat(),
        "tags": [{"name": t, "frequency": c, "suggested_by": "user"} for t, c in tag_freq.most_common()],
    }
    (out / "tag_ontology_v1.yaml").write_text(
        yaml.dump(tags_data, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # ── 3. classification_rules_v1.yaml ──
    rules = []
    # From reclassification patterns
    for r in feedback["reclassified"]:
        rules.append({
            "type": "reclassification",
            "pattern": f"文件 {r['filename'][:30]}",
            "from": r["from_category"],
            "to": r["to_category"],
            "confidence": 0.8,
            "source": "user_correction",
        })
    # From merges
    for target, sources in merges.items():
        rules.append({
            "type": "merge",
            "sources": sources,
            "target": target,
            "confidence": 0.9,
            "source": "user_merge",
        })
    rules_data = {"generated_at": datetime.now().isoformat(), "rules": rules}
    (out / "classification_rules_v1.yaml").write_text(
        yaml.dump(rules_data, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # ── 4. exclusion_rules_v1.yaml ──
    exclusion_cats = [cat for cat in all_cats if _is_exclusion_category(cat)]
    exc_data = {
        "generated_at": datetime.now().isoformat(),
        "excluded_categories": [
            {"name": cat, "file_count": len(cat_files.get(cat, [])),
             "user_confirmed": cat in approved}
            for cat in exclusion_cats
        ],
        "excluded_files_from_reclass": [
            {"filename": r["filename"], "from": r["from_category"], "reason": r.get("notes", "")}
            for r in feedback["reclassified"]
            if _is_exclusion_category(r["to_category"])
        ],
    }
    (out / "exclusion_rules_v1.yaml").write_text(
        yaml.dump(exc_data, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # ── 5. source_type_policy_v1.yaml ──
    # Extract patterns from filenames
    type_patterns: dict[str, list[str]] = defaultdict(list)
    for a in assignments:
        fn = a.get("filename", "")
        if "转写" in fn or "文稿" in fn:
            type_patterns["transcript"].append(fn)
        elif "LeetCode" in fn or any(k in fn for k in ["题解", "并查集", "GetMapping"]):
            type_patterns["leetcode_algorithm"].append(fn)
        elif "草稿" in fn:
            type_patterns["draft"].append(fn)
        elif "复盘" in fn:
            type_patterns["review"].append(fn)

    policies = []
    for ptype, files in type_patterns.items():
        cats = Counter(a["predicted_category"] for a in assignments if a.get("filename") in files)
        top_cat = cats.most_common(1)[0][0] if cats else "unknown"
        policies.append({
            "pattern": ptype, "sample_count": len(files),
            "dominant_category": top_cat, "category_distribution": dict(cats.most_common(3)),
        })

    pol_data = {"generated_at": datetime.now().isoformat(), "source_type_policies": policies}
    (out / "source_type_policy_v1.yaml").write_text(
        yaml.dump(pol_data, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # ── 6. learning_report.md ──
    report = _build_learning_report(feedback, all_cats, cat_files, merges, assignments, tags_data)
    (out / "learning_report.md").write_text(report, encoding="utf-8")

    return {
        "reviewed": feedback["total_reviewed"],
        "approved_categories": len(approved),
        "reclassified": len(feedback["reclassified"]),
        "merges": len(merges),
        "tags_suggested": len(feedback["tags_suggested"]),
        "output_dir": str(out),
        "output_files": [
            str(out / "category_schema_v1.yaml"),
            str(out / "tag_ontology_v1.yaml"),
            str(out / "classification_rules_v1.yaml"),
            str(out / "exclusion_rules_v1.yaml"),
            str(out / "source_type_policy_v1.yaml"),
            str(out / "learning_report.md"),
        ],
    }


def _build_learning_report(
    feedback: dict,
    all_cats: set,
    cat_files: dict[str, list[str]],
    merges: dict[str, list[str]],
    assignments: list[dict],
    tags_data: dict,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    approved = set(feedback["approved_categories"].keys())
    merged_sources = {s for sources in merges.values() for s in sources}

    # Estimate affected files
    affected_reclass = len(feedback["reclassified"])
    affected_merge = sum(len(cat_files.get(src, [])) for src in merged_sources)
    affected_total = affected_reclass + affected_merge

    lines = [
        "# 学习报告 — 用户审查反馈 → 规则提炼",
        f"> 生成时间: {now}",
        f"> 用户审查: {feedback['total_reviewed']} 个样本",
        "",
        "## 1. 用户认可了哪些类别",
        "",
    ]
    for cat in sorted(approved):
        files = cat_files.get(cat, [])
        samples = files[:3]
        lines.append(f"- **{cat}** ({len(files)} 文件): {', '.join(samples)}")

    # 2. Negated
    negated = all_cats - approved - merged_sources
    lines.extend([
        "", "## 2. 用户否定/未确认的类别", "",
    ])
    for cat in sorted(negated):
        lines.append(f"- {cat} ({len(cat_files.get(cat, []))} 文件) — 用户未认可，需进一步确认")

    # 3. Merged
    lines.extend([
        "", "## 3. 被合并的类别", "",
    ])
    if merges:
        for target, sources in merges.items():
            lines.append(f"- **{target}** ← {', '.join(sources)} ({sum(len(cat_files.get(s,[])) for s in sources)} 文件)")
    else:
        lines.append("- 无合并")

    # 4. Split
    lines.extend([
        "", "## 4. 被拆分的类别", "",
    ])
    split_sources = set()
    for r in feedback["reclassified"]:
        split_sources.add(r["from_category"])
    if split_sources:
        for cat in sorted(split_sources):
            reclass_to = set(r["to_category"] for r in feedback["reclassified"] if r["from_category"] == cat)
            lines.append(f"- **{cat}** → 拆出文件到: {', '.join(reclass_to)}")
    else:
        lines.append("- 无拆分")

    # 5. Tags added
    lines.extend([
        "", "## 5. 新增 Tags", "",
    ])
    for t in feedback["tags_suggested"][:15]:
        lines.append(f"- `{t}`")

    # 6. Tags removed
    lines.extend([
        "", "## 6. 删除的 Tags", "",
        "- 用户未标记删除任何 tag（如需要，在 user_tags 列标注 `-tag名`）",
    ])

    # 7. Rules generated
    lines.extend([
        "", "## 7. 生成的规则", "",
    ])
    # Merge rules
    for target, sources in merges.items():
        affected = sum(len(cat_files.get(s, [])) for s in sources)
        lines.append(f"- **合并规则**: {', '.join(sources)} → {target} (影响 {affected} 文件)")
    # Reclassification rules
    for r in feedback["reclassified"]:
        lines.append(f"- **重分类**: `{r['filename'][:40]}` {r['from_category']} → {r['to_category']}")

    # 8. Impact estimate
    lines.extend([
        "", "## 8. 预计影响范围", "",
        f"| 影响类型 | 文件数 |",
        f"|----------|--------|",
        f"| 直接修正（用户明确标注） | {affected_reclass} |",
        f"| 合并影响（规则推及同类文件） | {affected_merge} |",
        f"| **预计总影响** | **{affected_total}** |",
        f"| 总文件数 | {len(assignments)} |",
        f"| 影响比例 | {affected_total/max(len(assignments),1)*100:.0f}% |",
        "",
        "---",
        "*基于用户抽样审查自动生成*",
    ])

    return "\n".join(lines) + "\n"
