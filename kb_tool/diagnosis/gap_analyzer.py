from __future__ import annotations

from .schemas import MissingInformation, UserKnowledgeProfile

CONFIDENCE_THRESHOLD = 0.6

_FIELD_WHY_NEEDED: dict[str, str] = {
    "primary_goal": "决定知识库架构取向——归档型 vs 认知型 vs 写作型，不同方向的分量完全不同",
    "core_scenarios": "决定 MCP/agent 的检索优先级和工具调用链设计",
    "core_domains": "直接决定一级分类体系，是整个 classification_policy 的基础",
    "corpus_scale_estimate": "决定分析策略——小规模全量读入 vs 大规模预算制分批压缩",
    "maintenance_willingness": "决定自动化程度——全自动 vs 周报+review vs 深度迭代",
    "current_workflow": "决定迁移策略和对现有分类体系的兼容方式",
    "source_file_types": "决定 extractor 策略和采样方法",
    "privacy_level": "决定 LLM 调用策略——本地模型 vs 脱敏管道 vs 云端全量分析",
    "structure_preference": "决定一级分类维度——领域优先 vs 时间优先，是最根本的架构决策",
    "time_axis_preference": "决定时间轴策略——文档内容时间 vs 修改时间 vs 双标注",
    "source_type_policy": "决定原创/摘录/AI生成内容的处理——混合还是分离",
    "exclusion_policy": "决定哪些文件不纳入——排错比漏分类的伤害更大",
    "human_reading_entry": "决定检索界面和导航设计——浏览导向 vs 搜索导向 vs AI导向",
    "ai_reading_entry": "决定 MCP 工具设计和 Context Bundle 更新策略",
    "query_patterns": "决定不同搜索模式的权重分配和工具调用链",
    "preferred_outputs": "决定 enabled_components 和报告生成管线",
    "report_preferences": "决定报告的频率、粒度和风格",
    "enabled_components": "决定哪些组件需要构建和激活",
    "disabled_components": "决定哪些组件明确不需要——资源配置的排除清单",
}

_FIELD_COMPONENTS: dict[str, list[str]] = {
    "primary_goal": ["classification_policy", "query_strategy", "report_template"],
    "core_scenarios": ["query_strategy"],
    "core_domains": ["classification_policy"],
    "corpus_scale_estimate": ["query_strategy", "organize_schedule"],
    "maintenance_willingness": ["organize_schedule"],
    "current_workflow": ["classification_policy"],
    "source_file_types": ["classification_policy"],
    "privacy_level": ["classification_policy", "query_strategy", "report_template"],
    "structure_preference": ["classification_policy"],
    "time_axis_preference": ["classification_policy"],
    "source_type_policy": ["classification_policy"],
    "exclusion_policy": ["classification_policy"],
    "human_reading_entry": ["query_strategy", "report_template"],
    "ai_reading_entry": ["query_strategy", "organize_schedule"],
    "query_patterns": ["query_strategy"],
    "preferred_outputs": ["report_template"],
    "report_preferences": ["report_template", "organize_schedule"],
    "enabled_components": ["report_template", "organize_schedule"],
    "disabled_components": ["report_template", "organize_schedule"],
}

_FIELD_PRIORITY: dict[str, str] = {
    "primary_goal": "critical",
    "structure_preference": "critical",
    "core_domains": "critical",
    "privacy_level": "critical",
    "preferred_outputs": "high",
    "maintenance_willingness": "high",
    "current_workflow": "high",
    "core_scenarios": "high",
    "source_type_policy": "medium",
    "time_axis_preference": "medium",
    "exclusion_policy": "medium",
    "human_reading_entry": "medium",
    "ai_reading_entry": "medium",
    "query_patterns": "medium",
    "report_preferences": "medium",
    "corpus_scale_estimate": "medium",
    "source_file_types": "low",
    "enabled_components": "low",
    "disabled_components": "low",
}


def analyze_gaps(profile: UserKnowledgeProfile,
                 threshold: float = CONFIDENCE_THRESHOLD) -> list[MissingInformation]:
    gaps: list[MissingInformation] = []

    for field in profile.field_names():
        conf = profile.confidence_map.get(field, 0.0)
        if conf >= threshold:
            continue

        val = getattr(profile, field, None)
        is_empty = val is None or val == "" or val == [] or val == {}
        if is_empty and conf < 0.3:
            gaps.append(MissingInformation(
                field_name=field,
                current_confidence=conf,
                why_needed=_FIELD_WHY_NEEDED.get(field, f"缺少 {field} 信息"),
                affects_components=_FIELD_COMPONENTS.get(field, []),
                priority=_FIELD_PRIORITY.get(field, "medium"),
            ))

    gaps.sort(key=lambda g: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(g.priority, 99))
    return gaps
