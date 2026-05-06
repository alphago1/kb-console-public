from __future__ import annotations

from pathlib import Path

from diagnosis.schemas import UserKnowledgeProfile
from .adaptation_rules import adapt_component
from .baseline_schema import AdaptationDecision, AdaptationDiff, AdaptedBlueprint, BaselineComponent
from .compatibility import check_report_first_compatibility, check_word_compatibility


def generate_diff(profile: UserKnowledgeProfile,
                  baseline_components: list[BaselineComponent],
                  session: str = "session_001") -> AdaptationDiff:
    decisions: list[AdaptationDecision] = []
    for comp in baseline_components:
        decisions.append(adapt_component(profile, comp))

    diff = AdaptationDiff(
        profile_session=session,
        summary="",
        decisions=decisions,
    )
    diff.compute_counts()

    keep = [d for d in decisions if d.action == "KEEP"]
    downgrade = [d for d in decisions if d.action == "DOWNGRADE"]
    replace = [d for d in decisions if d.action == "REPLACE"]
    enhance = [d for d in decisions if d.action == "ENHANCE"]
    disable = [d for d in decisions if d.action == "DISABLE"]

    parts: list[str] = []
    parts.append(f"基于用户画像（session={session}），从 Karpathy baseline（20 个组件）做了以下适配：")
    if keep:
        parts.append(f"保留 {len(keep)} 个组件：{', '.join(d.component_id for d in keep)}")
    if downgrade:
        parts.append(f"降级 {len(downgrade)} 个组件：{', '.join(d.component_id for d in downgrade)}")
    if replace:
        parts.append(f"替换 {len(replace)} 个组件：{', '.join(d.component_id for d in replace)}")
    if enhance:
        parts.append(f"增强 {len(enhance)} 个组件：{', '.join(d.component_id for d in enhance)}")
    if disable:
        parts.append(f"禁用 {len(disable)} 个组件：{', '.join(d.component_id for d in disable)}")
    diff.summary = "；".join(parts)

    return diff


def write_diff_markdown(diff: AdaptationDiff, output_path: str) -> str:
    lines = [
        "# Adaptation Diff — Karpathy Baseline → Adapted Blueprint",
        "",
        f"> Session: {diff.profile_session}",
        f"> Baseline: {diff.baseline_version}",
        "",
        "---",
        "",
        "## 适配概览",
        "",
        diff.summary,
        "",
        f"| 操作 | 数量 |",
        f"|------|------|",
        f"| KEEP | {diff.keep_count} |",
        f"| DOWNGRADE | {diff.downgrade_count} |",
        f"| REPLACE | {diff.replace_count} |",
        f"| ENHANCE | {diff.enhance_count} |",
        f"| DISABLE | {diff.disable_count} |",
        "",
        "---",
        "",
    ]

    for action, heading in [
        ("KEEP", "## 保留的组件"),
        ("DOWNGRADE", "## 降级的组件"),
        ("REPLACE", "## 替换的组件"),
        ("ENHANCE", "## 增强的组件"),
        ("DISABLE", "## 禁用的组件"),
    ]:
        items = [d for d in diff.decisions if d.action == action]
        if not items:
            continue
        lines.append(heading)
        lines.append("")
        for d in items:
            lines.append(f"### {d.component_id}")
            lines.append("")
            lines.append(f"**操作**: {action}")
            lines.append(f"**原因**: {d.reason}")
            lines.append(f"**原始策略**: {d.original_policy}")
            lines.append(f"**适配后策略**: {d.adapted_policy}")
            if d.profile_signals_used:
                lines.append(f"**使用的画像信号**: {', '.join(d.profile_signals_used)}")
            lines.append("")

    md = "\n".join(lines) + "\n"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(md, encoding="utf-8")
    return str(Path(output_path).resolve())


def generate_blueprint(profile: UserKnowledgeProfile,
                       baseline_components: list[BaselineComponent],
                       diff: AdaptationDiff,
                       session: str = "session_001") -> AdaptedBlueprint:
    word_notes = check_word_compatibility(profile)
    report_policy = check_report_first_compatibility(profile)

    enabled: list[BaselineComponent] = []
    downgraded: list[BaselineComponent] = []
    replaced: list[dict] = []
    enhanced: list[dict] = []
    disabled_ids: list[str] = []

    comp_map = {c.component_id: c for c in baseline_components}

    for d in diff.decisions:
        comp = comp_map.get(d.component_id)
        if not comp:
            continue
        if d.action == "KEEP":
            enabled.append(comp)
        elif d.action == "DOWNGRADE":
            downgraded.append(comp)
        elif d.action == "REPLACE":
            replaced.append({"component_id": d.component_id, "original": comp.name, "new_policy": d.adapted_policy, "reason": d.reason})
        elif d.action == "ENHANCE":
            enhanced.append({"component_id": d.component_id, "base": comp.name, "enhanced_policy": d.adapted_policy, "reason": d.reason})
        elif d.action == "DISABLE":
            disabled_ids.append(d.component_id)

    # Determine strategies
    human_index_strategy = "full_index_md"
    for d in diff.decisions:
        if d.component_id == "index_log.human_index" and d.action == "DOWNGRADE":
            human_index_strategy = "ai_only_json"
            break

    log_strategy = "human_readable_md"
    for d in diff.decisions:
        if d.component_id == "index_log.update_log" and d.action == "DOWNGRADE":
            log_strategy = "jsonl_only"
            break

    wiki_cache_strategy = "full_pages"
    if any(d.component_id == "wiki_layer.topic_pages" and d.action == "DOWNGRADE" for d in diff.decisions):
        wiki_cache_strategy = "compact_cache"

    report_first = report_policy.get("strategy") == "report_first"

    summary_parts = [
        f"用户主要目标: {profile.primary_goal or '未知'}",
        f"结构偏好: {profile.structure_preference or '未知'}",
        f"维护意愿: {profile.maintenance_willingness or '未知'}",
        f"主入口: {'report-first' if report_first else 'wiki-first'}",
        f"索引策略: {human_index_strategy}",
        f"日志策略: {log_strategy}",
        f"Wiki 缓存: {wiki_cache_strategy}",
        f"Word-first: {any('Word' in n for n in word_notes)}",
    ]

    return AdaptedBlueprint(
        profile_session=session,
        summary_narrative=". ".join(summary_parts) + ".",
        enabled_components=enabled,
        downgraded_components=downgraded,
        replaced_components=replaced,
        enhanced_components=enhanced,
        disabled_components=disabled_ids,
        word_compatibility_notes=word_notes,
        entry_point="reports" if report_first else "wiki",
        human_index_strategy=human_index_strategy,
        log_strategy=log_strategy,
        wiki_cache_strategy=wiki_cache_strategy,
        report_first=report_first,
        word_first=any("Word" in n or ".docx" in n for n in word_notes),
    )
