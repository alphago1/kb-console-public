from __future__ import annotations

from typing import Any

from diagnosis.schemas import UserKnowledgeProfile
from .baseline_schema import AdaptationDecision, BaselineComponent


def _val(profile: UserKnowledgeProfile, field: str) -> str:
    """Get profile field as lowercase string for flexible matching."""
    v = getattr(profile, field, None) or ""
    if isinstance(v, list):
        return " ".join(str(x) for x in v).lower()
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values()).lower()
    return str(v).lower()


# Each rule: (condition_fn, action, reason_template)
# Using _val() for flexible substring matching against inference output

RULES: list[tuple[Any, str, str]] = [
    # ── raw_sources: always KEEP ──
    (lambda p, c: c.layer == "raw_sources", "KEEP",
     "原始资料只读保存是所有知识库的底线，无论用户画像如何都需要"),

    # ── wiki_layer: AI-only wiki cache always KEEP ──
    (lambda p, c: c.component_id == "wiki_layer.ai_wiki_cache", "KEEP",
     "AI 内部缓存是所有后续分析的基础设施"),

    # ── wiki_mode: ai_generated_human_browsable → re-activate all wiki human-facing components ──
    (lambda p, c: "ai_generated" in _val(p, "wiki_mode")
                  and c.component_id in ("wiki_layer.topic_pages", "wiki_layer.project_pages",
                                         "wiki_layer.cross_references", "index_log.update_log"),
     "KEEP",
     "用户启用 AI 自动生成 Wiki 人类可浏览模式 → 激活所有 wiki 页面"),

    # ── wiki_layer: human-facing pages → depends on maintenance_willingness ──
    (lambda p, c: c.component_id in ("wiki_layer.topic_pages", "wiki_layer.project_pages")
                  and any(kw in _val(p, "maintenance_willingness") for kw in ["自动", "低", "懒得", "不想", "全自动"]),
     "DOWNGRADE",
     "用户维护意愿低 → 降级为 AI 内部结构化缓存，不生成人类可读的 wiki 页面"),

    # ── wiki_layer: profile_pages → depends on preferred_outputs ──
    (lambda p, c: c.component_id == "wiki_layer.profile_pages"
                  and any(kw in _val(p, "preferred_outputs") for kw in ["画像", "profile"]),
     "KEEP",
     "用户在 preferred_outputs 中明确需要个人画像报告"),

    # ── wiki_layer: cross_references → Observian 双链降级 ──
    (lambda p, c: c.component_id == "wiki_layer.cross_references"
                  and any(kw in _val(p, "maintenance_willingness") for kw in ["自动", "低"]),
     "DOWNGRADE",
     "用户维护意愿低 → Obsidian 双链降级为 topic relation metadata（JSON）"),

    # ── index_log: human_index → 取决于 human_reading_entry ──
    (lambda p, c: c.component_id == "index_log.human_index"
                  and any(kw in _val(p, "human_reading_entry") for kw in ["搜索", "ai", "找", "搜"]),
     "DOWNGRADE",
     "用户主要通过搜索/AI 消费知识库 → 人类可读 index.md 降级为 AI-readable JSON index"),

    # ── index_log: update_log → 取决于 maintenance_willingness ──
    (lambda p, c: c.component_id == "index_log.update_log"
                  and any(kw in _val(p, "maintenance_willingness") for kw in ["自动", "低", "懒得", "全自动"]),
     "DOWNGRADE",
     "用户维护意愿低，不会主动看 update log → 降级为 update_log.jsonl"),

    # ── index_log: topic_index → always KEEP for AI ──
    (lambda p, c: c.component_id == "index_log.topic_index", "KEEP",
     "topic_index 是 Agent 工具调用的核心索引，所有用户都需要"),

    # ── index_log: ingest_log → always KEEP for AI ──
    (lambda p, c: c.component_id == "index_log.ingest_log", "KEEP",
     "ingest_log 是增量更新和审计追踪的基础"),

    # ── schema_rules: all KEEP (AI-facing) but naming_convention may be adjusted ──
    (lambda p, c: c.layer == "schema_rules" and c.component_id != "schema_rules.naming_convention",
     "KEEP",
     "AI 行为规则是基础设施，所有用户都需要"),

    # ── lint: always KEEP (fully automated) ──
    (lambda p, c: c.layer == "lint",
     "KEEP",
     "质量检查全自动运行，不需要用户维护，因此所有用户都保留"),

    # ── Word-first ENHANCE ──
    (lambda p, c: c.component_id == "raw_sources.format_agnostic"
                  and any(kw in _val(p, "source_file_types") for kw in ["docx", "word", ".doc"]),
     "ENHANCE",
     "用户使用 Word → 增强 Word-first 文档迁移管线和 docx 文本提取"),

    # ── Report-first REPLACE ──
    (lambda p, c: c.component_id in ("wiki_layer.topic_pages", "wiki_layer.project_pages")
                  and any(kw in _val(p, "preferred_outputs") for kw in ["报告", "report", "月报", "周报", "月度"]),
     "REPLACE",
     "用户主要消费报告而非浏览 wiki 页面 → 主入口替换为 report-first 工作流"),

    # ── FTS search ENHANCE ──
    (lambda p, c: c.component_id == "index_log.topic_index"
                  and any(kw in _val(p, "human_reading_entry") for kw in ["搜索", "搜"]),
     "ENHANCE",
     "用户主要用搜索 → 增强 FTS5 全文检索作为主要入口"),

    # ── DISABLE: complex wiki for users who don't want decision system ──
    (lambda p, c: c.component_id == "wiki_layer.topic_pages"
                  and not any(kw in _val(p, "primary_goal") for kw in ["决策", "认知", "系统"]),
     "DOWNGRADE",
     "用户主要目标是归档/写作/搜索 → wiki 页面降级为摘要索引而非完整知识页"),
]


def _match_rule(profile: UserKnowledgeProfile, component: BaselineComponent) -> tuple[str, str] | None:
    for condition, action, reason in RULES:
        try:
            if condition(profile, component):
                return action, reason
        except Exception:
            continue
    return None


def adapt_component(profile: UserKnowledgeProfile,
                    component: BaselineComponent) -> AdaptationDecision:
    matched = _match_rule(profile, component)
    if matched:
        action, reason = matched
    else:
        action, reason = "KEEP", "无特殊适配规则触发，保留默认行为"

    signals_used = []
    for field in profile.field_names():
        val = getattr(profile, field, None)
        if val and val != [] and val != {} and val != "":
            if field in reason or str(val)[:30] in reason:
                signals_used.append(field)

    return AdaptationDecision(
        component_id=component.component_id,
        action=action,
        reason=reason,
        original_policy=component.default_policy,
        adapted_policy=_compute_adapted_policy(component, action),
        profile_signals_used=signals_used,
    )


def _compute_adapted_policy(component: BaselineComponent, action: str) -> str:
    if action == "KEEP":
        return component.default_policy
    if action == "DOWNGRADE":
        return f"[降级] {component.default_policy} → 简化为 AI-internal 版本，去掉人类可读界面"
    if action == "REPLACE":
        return f"[替换] {component.default_policy} → 替换为更适合用户工作流的方案（见 adapted_blueprint）"
    if action == "ENHANCE":
        return f"[增强] {component.default_policy} → 在本项目特有能力的加持下增强"
    if action == "DISABLE":
        return f"[禁用] {component.default_policy} → 完全禁用，不启用此组件"
    return component.default_policy
