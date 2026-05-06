from __future__ import annotations

import csv
from pathlib import Path

from .feedback_schema import FeedbackRulePlan, FileCorrectionType, RuleAction, StructureAction


def preview_affected_files(
    plan: FeedbackRulePlan,
    sample_csv_path: str,
    output_csv_path: str,
) -> str:
    """Generate affected_sample_files.csv showing how each rule impacts sample files."""
    sample_rows = _load_csv(sample_csv_path)
    if not sample_rows:
        return ""

    affected_rows: list[dict] = []

    for rule in plan.formal_rules:
        _apply_rule_to_sample(rule, sample_rows, affected_rows)

    # Write CSV
    Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "file_path", "current_category", "current_source_type",
        "rule_id", "rule_type", "change_description",
        "old_value", "new_value", "affected",
    ]
    with open(output_csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=headers)
        w.writeheader()
        for row in affected_rows:
            w.writerow(row)

    return str(Path(output_csv_path).resolve())


def generate_expected_changes_markdown(plan: FeedbackRulePlan, affected_files_path: str = "") -> str:
    """Generate expected_changes.md summarizing all changes."""
    lines = [
        "# Expected Changes",
        "",
        f"> 会话: {plan.session}",
        f"> 规则总数: {len(plan.formal_rules)}",
        f"> 预计影响文件: {plan.affected_file_count}",
        "",
        "---",
        "",
        "## 变更摘要",
        "",
        plan.summary,
        "",
        "---",
        "",
    ]

    # Group rules by type
    by_type: dict[str, list] = {}
    for r in plan.formal_rules:
        by_type.setdefault(r.rule_type, []).append(r)

    type_labels = {
        "exclusion": "排除规则",
        "classification": "分类规则",
        "source_type": "源类型规则",
        "folder_schema": "结构变更",
        "component": "组件变更",
        "report": "报告模板变更",
    }

    for rt, rules in by_type.items():
        label = type_labels.get(rt, rt)
        lines.append(f"## {label} ({len(rules)} 条)")
        lines.append("")
        for r in rules:
            confirm = "⚠️ 需确认" if r.requires_confirmation else "✅ 自动应用"
            lines.append(f"- **[{r.rule_id}]** {r.human_explanation} _({confirm}, 优先级={r.priority})_")
            if r.affected_file_count_estimate:
                lines.append(f"  - 预计影响文件: ~{r.affected_file_count_estimate} 个")
        lines.append("")

    if affected_files_path and Path(affected_files_path).exists():
        lines.append("---")
        lines.append("")
        lines.append("## 受影响的文件清单")
        lines.append("")
        lines.append(f"详见 [{Path(affected_files_path).name}]({Path(affected_files_path).name})")

    return "\n".join(lines) + "\n"


def _load_csv(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _apply_rule_to_sample(rule, sample_rows: list[dict], affected: list[dict]):
    """Check each sample row against a rule and record affected entries."""
    cs = rule.condition_spec
    act = rule.action_spec

    for row in sample_rows:
        file_path = row.get("docs_path", "")
        cat = row.get("primary_category", "")
        st = row.get("source_type", "")
        fn = row.get("filename", "")

        matched = False
        old_val = ""
        new_val = ""
        desc = ""

        # ── File-level rules ──
        if rule.source == "file_feedback":
            if cs.get("file_path") == file_path:
                matched = True
                if rule.rule_type == "exclusion":
                    old_val = "include_in_kb=1"
                    new_val = "include_in_kb=0"
                    desc = f"排除: {fn}"
                elif rule.rule_type == "classification":
                    old_val = cat
                    new_val = act.get("value", "")
                    desc = f"重分类: {cat} → {new_val}"
                elif rule.rule_type == "source_type":
                    old_val = st
                    new_val = act.get("value", "")
                    desc = f"源类型: {st} → {new_val}"

        # ── Rule-level rules ──
        elif rule.source == "rule_feedback":
            kw_match = not cs.get("match_keywords") or any(
                kw in fn for kw in cs["match_keywords"]
            )
            st_match = not cs.get("match_source_types") or st in cs["match_source_types"]
            cat_match = not cs.get("match_categories") or cat in cs["match_categories"]

            if kw_match and st_match and cat_match:
                matched = True
                action = act.get("action", "")
                if "exclude" in action:
                    old_val = "include_in_kb=1"
                    new_val = "include_in_kb=0"
                    desc = f"规则排除: {rule.human_explanation[:60]}"
                else:
                    old_val = cat
                    new_val = act.get("value", cat)
                    desc = rule.human_explanation[:80]

        # ── Structure-level rules ──
        elif rule.source == "structure_feedback":
            source_cats = set(cs.get("source_categories", []))
            if cat in source_cats:
                matched = True
                s_action = act.get("action", "")
                if s_action == StructureAction.DELETE_CATEGORY.value:
                    old_val = cat
                    new_val = "无法判断 (fallback)"
                    desc = f"分类 '{cat}' 被删除，文件移至 fallback"
                elif s_action == StructureAction.MERGE_CATEGORIES.value:
                    old_val = cat
                    new_val = act.get("target_category", "")
                    desc = f"合并分类: {cat} → {new_val}"
                elif s_action == StructureAction.CREATE_CATEGORY.value:
                    old_val = ""
                    new_val = act.get("target_category", "")
                    desc = f"新分类可用: {new_val}"
                elif s_action == StructureAction.SPLIT_CATEGORY.value:
                    old_val = cat
                    new_val = f"拆分 → {act.get('split_rules', {}).get('new_categories', [])}"
                    desc = f"分类 '{cat}' 将被拆分"

        if matched:
            affected.append({
                "file_path": file_path,
                "current_category": cat,
                "current_source_type": st,
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "change_description": desc,
                "old_value": old_val,
                "new_value": new_val,
                "affected": "yes",
            })
