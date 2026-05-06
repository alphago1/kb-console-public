from __future__ import annotations

import csv
import yaml
from pathlib import Path
from collections import defaultdict

from .feedback_schema import (
    UserFeedbackBundle,
    FileLevelFeedback,
    RuleLevelFeedback,
    StructureLevelFeedback,
    ComponentLevelFeedback,
    FileCorrectionType,
    RuleAction,
    StructureAction,
    ComponentAction,
    FormalRule,
    PolicyDiffEntry,
    StructureDiffEntry,
    FeedbackRulePlan,
)


def parse_user_feedback(feedback_path: str) -> UserFeedbackBundle:
    """Parse user_feedback.yaml into typed feedback objects."""
    raw = yaml.safe_load(Path(feedback_path).read_text(encoding="utf-8")) or {}
    session = raw.get("session", "")

    file_fb = []
    for item in raw.get("file_corrections", []):
        file_fb.append(FileLevelFeedback(
            file_path=item.get("file_path", ""),
            correction=FileCorrectionType(item.get("correction", "exclude")),
            new_category=item.get("new_category", ""),
            new_source_type=item.get("new_source_type", ""),
            reason=item.get("reason", ""),
            confidence=item.get("confidence", 1.0),
        ))

    rule_fb = []
    for item in raw.get("rule_feedback", []):
        rule_fb.append(RuleLevelFeedback(
            description=item.get("description", ""),
            action=RuleAction(item.get("action", "exclude_by_keyword")),
            match_keywords=item.get("match_keywords", []),
            match_source_types=item.get("match_source_types", []),
            match_categories=item.get("match_categories", []),
            match_patterns=item.get("match_patterns", []),
            target_action_value=item.get("target_action_value", ""),
            reason=item.get("reason", ""),
            priority=item.get("priority", 5),
        ))

    struct_fb = []
    for item in raw.get("structure_feedback", []):
        struct_fb.append(StructureLevelFeedback(
            description=item.get("description", ""),
            action=StructureAction(item.get("action", "merge_categories")),
            source_categories=item.get("source_categories", []),
            target_category=item.get("target_category", ""),
            split_rules=item.get("split_rules", {}),
            time_preference=item.get("time_preference", ""),
            dir_structure=item.get("dir_structure", ""),
            report_changes=item.get("report_changes", {}),
            reason=item.get("reason", ""),
        ))

    comp_fb = []
    for item in raw.get("component_feedback", []):
        comp_fb.append(ComponentLevelFeedback(
            component_name=item.get("component_name", ""),
            action=ComponentAction(item.get("action", "disable")),
            visibility=item.get("visibility", ""),
            reason=item.get("reason", ""),
        ))

    return UserFeedbackBundle(
        session=session,
        file_feedback=file_fb,
        rule_feedback=rule_fb,
        structure_feedback=struct_fb,
        component_feedback=comp_fb,
    )


def _load_sample_paths(sample_csv_path: str) -> dict[str, dict]:
    """Load sample CSV into dict keyed by docs_path."""
    out: dict[str, dict] = {}
    if not sample_csv_path or not Path(sample_csv_path).exists():
        return out
    with open(sample_csv_path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row.get("docs_path", "")] = row
    return out


def generate_rule_plan(
    feedback_path: str,
    sample_csv_path: str = "",
    blueprint_dir: str = "",
) -> FeedbackRulePlan:
    bundle = parse_user_feedback(feedback_path)
    sample_rows = _load_sample_paths(sample_csv_path)

    formal_rules: list[FormalRule] = []
    policy_diffs: list[PolicyDiffEntry] = []
    structure_diffs: list[StructureDiffEntry] = []
    rule_counter = 1

    # ── Process file-level feedback ──
    for idx, fb in enumerate(bundle.file_feedback):
        fid = f"R{rule_counter:03d}"
        rule_counter += 1

        if fb.correction == FileCorrectionType.EXCLUDE:
            rule = FormalRule(
                rule_id=fid, source="file_feedback", source_item_index=idx,
                rule_type="exclusion",
                human_explanation=f"文件 '{fb.file_path}' 应排除：{fb.reason}",
                condition_spec={"file_path": fb.file_path},
                action_spec={"action": "set_include_in_kb", "value": False},
                affected_file_count_estimate=1,
                requires_confirmation=True,
            )
            formal_rules.append(rule)
            policy_diffs.append(PolicyDiffEntry(
                policy_file="classifications in SQLite",
                section_path=f"include_in_kb for {Path(fb.file_path).name}",
                change_type="modify",
                old_value="include_in_kb=1",
                new_value="include_in_kb=0",
                reason=fb.reason,
                human_readable=f"排除文件: {Path(fb.file_path).name}",
            ))

        elif fb.correction == FileCorrectionType.RECATEGORIZE:
            old_cat = sample_rows.get(fb.file_path, {}).get("primary_category", "unknown")
            rule = FormalRule(
                rule_id=fid, source="file_feedback", source_item_index=idx,
                rule_type="classification",
                human_explanation=f"文件 '{fb.file_path}' 从 '{old_cat}' 重新分类为 '{fb.new_category}'：{fb.reason}",
                condition_spec={"file_path": fb.file_path},
                action_spec={"action": "set_category", "value": fb.new_category},
                affected_file_count_estimate=1,
                requires_confirmation=True,
            )
            formal_rules.append(rule)
            policy_diffs.append(PolicyDiffEntry(
                policy_file="classifications in SQLite",
                section_path=f"primary_category for {Path(fb.file_path).name}",
                change_type="modify",
                old_value=old_cat,
                new_value=fb.new_category,
                reason=fb.reason,
                human_readable=f"重分类: {Path(fb.file_path).name} ({old_cat} → {fb.new_category})",
            ))

        elif fb.correction in (FileCorrectionType.MARK_EXTERNAL, FileCorrectionType.MARK_ORIGINAL):
            old_st = sample_rows.get(fb.file_path, {}).get("source_type", "unknown")
            new_st = fb.new_source_type or ("外部资料" if fb.correction == FileCorrectionType.MARK_EXTERNAL else "原创思考")
            rule = FormalRule(
                rule_id=fid, source="file_feedback", source_item_index=idx,
                rule_type="source_type",
                human_explanation=f"文件 '{fb.file_path}' 来源类型从 '{old_st}' 改为 '{new_st}'：{fb.reason}",
                condition_spec={"file_path": fb.file_path},
                action_spec={"action": "set_source_type", "value": new_st},
                affected_file_count_estimate=1,
                requires_confirmation=True,
            )
            formal_rules.append(rule)
            policy_diffs.append(PolicyDiffEntry(
                policy_file="source_type_policy.yaml",
                section_path=f"source_type for {Path(fb.file_path).name}",
                change_type="modify",
                old_value=old_st,
                new_value=new_st,
                reason=fb.reason,
                human_readable=f"源类型修正: {Path(fb.file_path).name} ({old_st} → {new_st})",
            ))

    # ── Process rule-level feedback ──
    for idx, rb in enumerate(bundle.rule_feedback):
        fid = f"R{rule_counter:03d}"
        rule_counter += 1
        rule_type = _rule_action_to_type(rb.action)

        affected_estimate = _estimate_affected(rb, sample_rows)

        rule = FormalRule(
            rule_id=fid, source="rule_feedback", source_item_index=idx,
            rule_type=rule_type,
            human_explanation=rb.description or rb.reason,
            condition_spec={
                "match_keywords": rb.match_keywords,
                "match_source_types": rb.match_source_types,
                "match_categories": rb.match_categories,
                "match_patterns": rb.match_patterns,
            },
            action_spec={
                "action": rb.action.value,
                "value": rb.target_action_value,
            },
            affected_file_count_estimate=affected_estimate,
            priority=rb.priority,
            requires_confirmation=True,
        )
        formal_rules.append(rule)

        # Build human-readable diff entry
        hr = _describe_rule_diff(rb)
        entry = PolicyDiffEntry(
            policy_file=("classification_policy.yaml" if rule_type == "classification"
                         else "source_type_policy.yaml" if rule_type == "source_type"
                         else "exclusion_policy.yaml"),
            section_path=f"rules[{idx}]",
            change_type="add",
            old_value="",
            new_value=hr,
            reason=rb.reason,
            human_readable=hr,
        )
        policy_diffs.append(entry)

    # ── Process structure-level feedback ──
    for idx, sb in enumerate(bundle.structure_feedback):
        fid = f"R{rule_counter:03d}"
        rule_counter += 1

        rule = FormalRule(
            rule_id=fid, source="structure_feedback", source_item_index=idx,
            rule_type="folder_schema" if sb.action != StructureAction.CHANGE_REPORT_TEMPLATE else "report",
            human_explanation=sb.description or sb.reason,
            condition_spec={"source_categories": sb.source_categories},
            action_spec={
                "action": sb.action.value,
                "target_category": sb.target_category,
                "split_rules": sb.split_rules,
                "time_preference": sb.time_preference,
                "dir_structure": sb.dir_structure,
                "report_changes": sb.report_changes,
            },
            affected_file_count_estimate=_estimate_structure_affected(sb, sample_rows),
            requires_confirmation=True,
        )
        formal_rules.append(rule)

        sde = _describe_structure_diff(sb, sample_rows)
        structure_diffs.append(sde)

    # ── Process component-level feedback ──
    for idx, cb in enumerate(bundle.component_feedback):
        fid = f"R{rule_counter:03d}"
        rule_counter += 1

        rule = FormalRule(
            rule_id=fid, source="component_feedback", source_item_index=idx,
            rule_type="component",
            human_explanation=f"组件 '{cb.component_name}' {cb.action.value}: {cb.reason}" if cb.reason
            else f"组件 '{cb.component_name}' -> {cb.action.value}",
            condition_spec={"component_name": cb.component_name},
            action_spec={"action": cb.action.value, "visibility": cb.visibility},
            affected_file_count_estimate=0,
            requires_confirmation=True,
        )
        formal_rules.append(rule)

        policy_diffs.append(PolicyDiffEntry(
            policy_file="component_plan.yaml",
            section_path=cb.component_name,
            change_type="modify",
            old_value="enabled" if cb.action == ComponentAction.DISABLE else "disabled",
            new_value=cb.action.value,
            reason=cb.reason,
            human_readable=f"组件: {cb.component_name} → {cb.action.value}{(' (visibility=' + cb.visibility + ')') if cb.visibility else ''}",
        ))

    # ── Compute summary ──
    affected_total = sum(r.affected_file_count_estimate for r in formal_rules)
    summary_parts = []
    if bundle.file_feedback:
        summary_parts.append(f"{len(bundle.file_feedback)} 个文件级修正")
    if bundle.rule_feedback:
        summary_parts.append(f"{len(bundle.rule_feedback)} 条规则级反馈")
    if bundle.structure_feedback:
        summary_parts.append(f"{len(bundle.structure_feedback)} 个结构变更")
    if bundle.component_feedback:
        summary_parts.append(f"{len(bundle.component_feedback)} 个组件调整")

    return FeedbackRulePlan(
        session=bundle.session or "session_001",
        source_feedback=f"{Path(feedback_path).resolve()}",
        source_sample=f"{Path(sample_csv_path).resolve()}" if sample_csv_path else "",
        source_blueprint=f"{Path(blueprint_dir).resolve()}" if blueprint_dir else "",
        formal_rules=formal_rules,
        policy_diffs=policy_diffs,
        structure_diffs=structure_diffs,
        affected_file_count=affected_total,
        summary="；".join(summary_parts) if summary_parts else "无变更",
    )


def _rule_action_to_type(action: RuleAction) -> str:
    mapping = {
        RuleAction.EXCLUDE_BY_KEYWORD: "exclusion",
        RuleAction.EXCLUDE_BY_SOURCE_TYPE: "exclusion",
        RuleAction.EXCLUDE_BY_PATTERN: "exclusion",
        RuleAction.EXCLUDE_BY_CATEGORY: "exclusion",
        RuleAction.SET_DEFAULT_CATEGORY: "classification",
        RuleAction.SET_DEFAULT_SOURCE_TYPE: "source_type",
        RuleAction.RECATEGORIZE_BY_CATEGORY: "classification",
        RuleAction.TREAT_AS_TAG: "classification",
    }
    return mapping.get(action, "classification")


def _estimate_affected(rb: RuleLevelFeedback, sample_rows: dict[str, dict]) -> int:
    count = 0
    if not sample_rows:
        return count
    for path, row in sample_rows.items():
        cat = row.get("primary_category", "")
        st = row.get("source_type", "")
        fn = row.get("filename", "")
        if rb.match_categories and cat in rb.match_categories:
            count += 1
        elif rb.match_source_types and st in rb.match_source_types:
            count += 1
        elif rb.match_keywords:
            if any(kw in fn for kw in rb.match_keywords):
                count += 1
    return max(count, 1)


def _estimate_structure_affected(sb: StructureLevelFeedback, sample_rows: dict[str, dict]) -> int:
    if not sample_rows or not sb.source_categories:
        return 0
    count = 0
    for row in sample_rows.values():
        if row.get("primary_category", "") in sb.source_categories:
            count += 1
    return count


def _describe_rule_diff(rb: RuleLevelFeedback) -> str:
    parts = [rb.description or rb.action.value]
    if rb.match_keywords:
        parts.append(f"匹配关键词: {rb.match_keywords}")
    if rb.match_source_types:
        parts.append(f"匹配来源类型: {rb.match_source_types}")
    if rb.match_categories:
        parts.append(f"匹配分类: {rb.match_categories}")
    if rb.target_action_value:
        parts.append(f"→ {rb.target_action_value}")
    return " | ".join(parts)


def _describe_structure_diff(sb: StructureLevelFeedback, sample_rows: dict[str, dict]) -> StructureDiffEntry:
    action_map = {
        StructureAction.MERGE_CATEGORIES: "合并分类",
        StructureAction.SPLIT_CATEGORY: "拆分分类",
        StructureAction.DELETE_CATEGORY: "删除分类",
        StructureAction.CREATE_CATEGORY: "新增分类",
        StructureAction.CHANGE_TIME_AXIS: "修改时间维度",
        StructureAction.CHANGE_DIR_STRUCTURE: "修改目录结构",
        StructureAction.CHANGE_REPORT_TEMPLATE: "修改报告模板",
    }
    affected = _estimate_structure_affected(sb, sample_rows)
    before = ", ".join(sb.source_categories) if sb.source_categories else "—"
    after = sb.target_category or sb.time_preference or sb.dir_structure or str(sb.report_changes) or "—"

    return StructureDiffEntry(
        structure_file=("folder_schema.yaml" if sb.action != StructureAction.CHANGE_REPORT_TEMPLATE
                        else "report_template_plan.yaml"),
        change_type=sb.action.value,
        description=sb.description,
        before=before,
        after=after,
        affected_files_estimate=affected,
        reason=sb.reason,
    )
