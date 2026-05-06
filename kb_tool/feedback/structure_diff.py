from __future__ import annotations

from pathlib import Path

from .feedback_schema import FeedbackRulePlan, StructureDiffEntry, StructureAction


def generate_structure_diff_markdown(plan: FeedbackRulePlan, current_schema: dict | None = None) -> str:
    """Generate a human-readable markdown diff of all structure changes."""
    lines = [
        "# Structure Diff",
        "",
        f"> 会话: {plan.session}",
        f"> 结构变更数: {len(plan.structure_diffs)}",
        "",
        "---",
        "",
    ]

    if not plan.structure_diffs:
        lines.append("无结构变更。")
        return "\n".join(lines) + "\n"

    for i, sd in enumerate(plan.structure_diffs, 1):
        lines.append(f"## {i}. {sd.description}")
        lines.append("")
        lines.append(f"- **类型**: `{sd.change_type}`")
        lines.append(f"- **文件**: `{sd.structure_file}`")
        lines.append(f"- **变更前**: {sd.before}")
        lines.append(f"- **变更后**: {sd.after}")
        lines.append(f"- **预计影响文件数**: {sd.affected_files_estimate}")
        lines.append(f"- **原因**: {sd.reason}")
        lines.append("")

        # Visual diff box
        lines.append("```diff")
        lines.append(f"- {sd.before}")
        lines.append(f"+ {sd.after}")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines) + "\n"


def apply_structure_changes(plan: FeedbackRulePlan, current_schema: dict | None = None) -> dict:
    """Return the updated folder_schema dict after applying structure rules."""
    schema = dict(current_schema or {})
    if not schema:
        schema = {
            "version": "v2",
            "root": "docs/",
            "structure": {"type": "domain_first", "primary_axis": "category", "secondary_axis": "time"},
            "levels": 2,
            "categories": [],
            "time_granularity": "month",
        }

    schema["version"] = "v2"
    existing_cats: list[dict] = schema.get("categories", [])

    for rule in plan.formal_rules:
        if rule.rule_type not in ("folder_schema", "report"):
            continue
        act = rule.action_spec.get("action", "")

        if act == StructureAction.MERGE_CATEGORIES.value:
            source = set(rule.condition_spec.get("source_categories", []))
            target = rule.action_spec.get("target_category", "")
            new_cats = []
            merged_desc = []
            for c in existing_cats:
                name = c.get("name", "")
                if name in source:
                    merged_desc.append(c.get("description", name))
                    continue
                new_cats.append(c)
            if target:
                new_cats.append({
                    "name": target,
                    "description": f"合并自: {', '.join(merged_desc)}",
                    "source": "feedback_merge",
                })
            existing_cats = new_cats

        elif act == StructureAction.DELETE_CATEGORY.value:
            source = set(rule.condition_spec.get("source_categories", []))
            existing_cats = [c for c in existing_cats if c.get("name", "") not in source]

        elif act == StructureAction.CREATE_CATEGORY.value:
            target = rule.action_spec.get("target_category", "")
            if target:
                existing_cats.append({
                    "name": target,
                    "description": rule.human_explanation,
                    "source": "feedback_create",
                })

        elif act == StructureAction.SPLIT_CATEGORY.value:
            split_rules = rule.action_spec.get("split_rules", {})
            source_name = split_rules.get("source_category", "")
            new_names = split_rules.get("new_categories", [])
            new_cats = []
            for c in existing_cats:
                if c.get("name", "") == source_name:
                    for nn in new_names:
                        new_cats.append({
                            "name": nn,
                            "description": f"拆分自: {source_name}",
                            "source": "feedback_split",
                        })
                else:
                    new_cats.append(c)
            existing_cats = new_cats

        elif act == StructureAction.CHANGE_TIME_AXIS.value:
            tp = rule.action_spec.get("time_preference", "")
            schema["time_granularity"] = "none" if "不关心" in tp else "month"

        elif act == StructureAction.CHANGE_DIR_STRUCTURE.value:
            ds = rule.action_spec.get("dir_structure", "")
            if "时间" in ds:
                schema["structure"] = {"type": "time_first", "primary_axis": "time", "secondary_axis": "category"}
                schema["levels"] = 2
            else:
                schema["structure"] = {"type": "domain_first", "primary_axis": "category", "secondary_axis": "time"}
                schema["levels"] = 2 if schema.get("time_granularity") != "none" else 1

    # Ensure 无法判断 is always the last category
    fallback_exists = any(c.get("name") == "无法判断" for c in existing_cats)
    if not fallback_exists:
        existing_cats.append({"name": "无法判断", "description": "AI 无法确定分类的文档", "source": "system"})
    else:
        # Move it to end
        fb = [c for c in existing_cats if c.get("name") == "无法判断"]
        others = [c for c in existing_cats if c.get("name") != "无法判断"]
        existing_cats = others + fb

    schema["categories"] = existing_cats
    return schema
