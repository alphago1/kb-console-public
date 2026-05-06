from __future__ import annotations

from pathlib import Path

from .feedback_schema import FeedbackRulePlan, PolicyDiffEntry


def generate_policy_diff_markdown(plan: FeedbackRulePlan, current_policies: dict | None = None) -> str:
    """Generate a human-readable markdown diff of all policy changes."""
    lines = [
        "# Policy Diff",
        "",
        f"> 会话: {plan.session}",
        f"> 规则数: {len(plan.formal_rules)}",
        f"> 策略变更数: {len(plan.policy_diffs)}",
        "",
        "---",
        "",
    ]

    if not plan.policy_diffs:
        lines.append("无策略变更。")
        return "\n".join(lines) + "\n"

    # Group by policy file
    by_file: dict[str, list[PolicyDiffEntry]] = {}
    for d in plan.policy_diffs:
        by_file.setdefault(d.policy_file, []).append(d)

    for policy_file, entries in by_file.items():
        lines.append(f"## {policy_file}")
        lines.append("")
        lines.append("| 变更 | 路径 | 旧值 | 新值 | 原因 |")
        lines.append("|------|------|------|------|------|")
        for e in entries:
            change_emoji = {"add": "➕ 新增", "remove": "➖ 删除", "modify": "✏️ 修改", "reorder": "🔀 重排"}.get(
                e.change_type, e.change_type
            )
            lines.append(
                f"| {change_emoji} | `{e.section_path}` | {_trunc(e.old_value, 40)} | "
                f"{_trunc(e.new_value, 40)} | {_trunc(e.reason, 30)} |"
            )
        lines.append("")

        # Detail each change
        lines.append("### 详细说明")
        lines.append("")
        for i, e in enumerate(entries, 1):
            lines.append(f"**{i}. {e.human_readable}**")
            lines.append(f"- 变更类型: `{e.change_type}`")
            lines.append(f"- 原因: {e.reason}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines) + "\n"


def generate_policy_changes_for_apply(plan: FeedbackRulePlan, current_policies: dict | None = None) -> dict:
    """Generate updated policy dicts for apply phase."""
    updated = {
        "classification_policy": {},
        "source_type_policy": {},
        "exclusion_policy": {},
    }

    if current_policies:
        for k in updated:
            updated[k] = dict(current_policies.get(k, {}))

    rules_from_plan = [r for r in plan.formal_rules if r.rule_type in ("classification", "source_type", "exclusion")]

    for rule in rules_from_plan:
        cs = rule.condition_spec
        act = rule.action_spec

        if rule.rule_type == "exclusion":
            updated.setdefault("exclusion_policy", {})
            ep = updated["exclusion_policy"]
            ep.setdefault("version", "v2")

            if "exclude_keywords" not in ep:
                ep["exclude_keywords"] = []
            if "exclude_source_types" not in ep:
                ep["exclude_source_types"] = []

            for kw in cs.get("match_keywords", []):
                if kw not in ep["exclude_keywords"]:
                    ep["exclude_keywords"].append(kw)
            for st in cs.get("match_source_types", []):
                if st not in ep["exclude_source_types"]:
                    ep["exclude_source_types"].append(st)

        elif rule.rule_type == "source_type":
            updated.setdefault("source_type_policy", {})
            sp = updated["source_type_policy"]
            sp.setdefault("version", "v2")
            sp.setdefault("rules", [])
            sp["rules"].append({
                "rule_id": rule.rule_id,
                "description": rule.human_explanation,
                "condition": cs,
                "action": act,
            })

        elif rule.rule_type == "classification":
            updated.setdefault("classification_policy", {})
            cp = updated["classification_policy"]
            cp.setdefault("version", "v2")
            cp.setdefault("rules", [])
            cp["rules"].append({
                "rule_id": rule.rule_id,
                "description": rule.human_explanation,
                "condition": cs,
                "action": act,
            })

    return updated


def _trunc(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n-3] + "..."
