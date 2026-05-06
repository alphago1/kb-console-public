from __future__ import annotations

import datetime
import json
import yaml
from pathlib import Path
from typing import Any

from .feedback_schema import FeedbackRulePlan, ComponentAction
from .policy_diff import generate_policy_changes_for_apply
from .structure_diff import apply_structure_changes


def apply_feedback_plan(
    plan_path: str,
    blueprint_dir: str,
    output_dir: str,
) -> dict[str, str]:
    """Apply a confirmed feedback rule plan to generate v2 blueprint artifacts."""

    plan_raw = yaml.safe_load(Path(plan_path).read_text(encoding="utf-8"))
    plan = FeedbackRulePlan(**plan_raw)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    # ── 1. Load current blueprint policies ──
    current_policies = _load_existing_policies(blueprint_dir)
    current_schema = _load_yaml_or_empty(Path(blueprint_dir) / "folder_schema.yaml")
    current_component = _load_yaml_or_empty(Path(blueprint_dir) / "component_plan.yaml") if Path(
        blueprint_dir, "component_plan.yaml").exists() else {}

    # ── 2. Compute updated policies ──
    updated_policies = generate_policy_changes_for_apply(plan, current_policies)

    # ── 3. Compute updated folder schema ──
    updated_schema = apply_structure_changes(plan, current_schema)

    # ── 4. Write updated classification_policy.yaml ──
    cp_path = out / "updated_classification_policy.yaml"
    _write_yaml(updated_policies.get("classification_policy", {}), cp_path)
    results["updated_classification_policy"] = str(cp_path.resolve())

    # ── 5. Write updated source_type_policy.yaml (if present) ──
    sp = updated_policies.get("source_type_policy", {})
    if sp:
        sp_path = out / "updated_source_type_policy.yaml"
        _write_yaml(sp, sp_path)
        results["updated_source_type_policy"] = str(sp_path.resolve())

    # ── 6. Write updated exclusion_policy.yaml ──
    ep = updated_policies.get("exclusion_policy", {})
    if ep:
        ep_path = out / "updated_exclusion_policy.yaml"
        _write_yaml(ep, ep_path)
        results["updated_exclusion_policy"] = str(ep_path.resolve())

    # ── 7. Write updated folder_schema.yaml ──
    fs_path = out / "updated_folder_schema.yaml"
    _write_yaml(updated_schema, fs_path)
    results["updated_folder_schema"] = str(fs_path.resolve())

    # ── 8. Write updated component_plan.yaml ──
    comp_updates = {
        r.condition_spec.get("component_name", ""): {
            "action": r.action_spec.get("action", ""),
            "visibility": r.action_spec.get("visibility", ""),
        }
        for r in plan.formal_rules
        if r.rule_type == "component"
    }
    if comp_updates:
        updated_components = _apply_component_updates(current_component, comp_updates)
        cmp_path = out / "updated_component_plan.yaml"
        _write_yaml(updated_components, cmp_path)
        results["updated_component_plan"] = str(cmp_path.resolve())

    # ── 9. Write updated knowledge_blueprint.md ──
    kb_path = out / "updated_knowledge_blueprint.md"
    kb_md = _build_v2_blueprint_markdown(plan, results)
    kb_path.write_text(kb_md, encoding="utf-8")
    results["updated_knowledge_blueprint"] = str(kb_path.resolve())

    # ── 10. Write rule_change_log.md ──
    log_path = out / "rule_change_log.md"
    log_md = _build_change_log(plan, results)
    log_path.write_text(log_md, encoding="utf-8")
    results["rule_change_log"] = str(log_path.resolve())

    return results


def _load_existing_policies(blueprint_dir: str) -> dict:
    bp = Path(blueprint_dir)
    policies: dict[str, Any] = {}
    for name in ["classification_policy.yaml", "source_type_policy.yaml", "exclusion_policy.yaml"]:
        p = bp / name
        if p.exists():
            policies[name.replace(".yaml", "")] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return policies


def _load_yaml_or_empty(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def _write_yaml(data: dict, path: Path) -> None:
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _apply_component_updates(current: dict, updates: dict[str, dict]) -> dict:
    result = dict(current)
    result.setdefault("version", "v2")
    result.setdefault("components", {})
    for name, spec in updates.items():
        result["components"][name] = spec
    return result


def _build_v2_blueprint_markdown(plan: FeedbackRulePlan, results: dict[str, str]) -> str:
    lines = [
        "# Deep-Custom Knowledge Blueprint v2",
        "",
        f"> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 会话: {plan.session}",
        f"> 基于反馈自动生成",
        "",
        "## 本次变更",
        "",
        plan.summary,
        "",
        "### 变更详情",
        "",
    ]

    for r in plan.formal_rules:
        lines.append(f"- **[R{r.rule_id}]** {r.rule_type}: {r.human_explanation}")

    lines.extend([
        "",
        "---",
        "",
        "## 配置文件",
        "",
    ])

    for name, path in sorted(results.items()):
        p = Path(path)
        lines.append(f"- **{name}**: [{p.name}]({p.name})")

    lines.extend([
        "",
        "---",
        "",
        "## 注意事项",
        "",
        "- 这是 v2 版本，基于用户对 sample-run 的反馈生成",
        "- 所有规则均需人工确认后应用",
        "- 正式应用前请仔细查看所有 diff 文件",
    ])

    return "\n".join(lines) + "\n"


def _build_change_log(plan: FeedbackRulePlan, results: dict[str, str]) -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Rule Change Log",
        "",
        f"> 时间: {ts}",
        f"> 会话: {plan.session}",
        f"> 规则数: {len(plan.formal_rules)}",
        "",
        "---",
        "",
        "## 变更记录",
        "",
    ]

    for r in plan.formal_rules:
        lines.append(f"### {r.rule_id} — {r.rule_type}")
        lines.append(f"- **来源**: {r.source}")
        lines.append(f"- **说明**: {r.human_explanation}")
        lines.append(f"- **条件**: `{json.dumps(r.condition_spec, ensure_ascii=False)}`")
        lines.append(f"- **动作**: `{json.dumps(r.action_spec, ensure_ascii=False)}`")
        lines.append(f"- **需确认**: {'是' if r.requires_confirmation else '否'}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 生成文件")
    for name, path in sorted(results.items()):
        lines.append(f"- `{Path(path).name}`")

    return "\n".join(lines) + "\n"
