from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DiagnosisSignal(BaseModel):
    signal_id: str
    source: str  # "inference_from_text" | "user_answer" | "file_analysis"
    evidence_text: str
    inferred_value: Any = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    affects_decision: str  # "classification_policy" | "query_strategy" | "report_template" | "organize_schedule"


class MissingInformation(BaseModel):
    field_name: str
    current_confidence: float = 0.0
    why_needed: str
    possible_questions: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)
    priority: str = "medium"  # "critical" | "high" | "medium" | "low"


class InterviewQuestion(BaseModel):
    question_id: str
    question_text: str
    question_type: str = "open"  # "single_choice" | "multi_choice" | "open"
    options: Optional[list[str]] = None
    why_this_question: str
    affects_fields: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)


class InterviewPlan(BaseModel):
    existing_profile_summary: str
    missing_information: list[MissingInformation] = Field(default_factory=list)
    selected_questions: list[InterviewQuestion] = Field(default_factory=list)
    skipped_questions: list[dict] = Field(default_factory=list)
    reason_for_each_question: dict[str, str] = Field(default_factory=dict)


class UserKnowledgeProfile(BaseModel):
    # ── 使用场景组 ──
    primary_goal: str = ""
    core_scenarios: list[str] = Field(default_factory=list)
    core_domains: list[dict] = Field(default_factory=list)
    corpus_scale_estimate: dict = Field(default_factory=dict)

    # ── 维护意愿组 ──
    maintenance_willingness: str = ""  # "高" | "中" | "低"
    current_workflow: str = ""
    source_file_types: list[str] = Field(default_factory=list)
    privacy_level: str = ""  # "本地" | "可脱敏上传" | "可上传"

    # ── 结构偏好组 ──
    structure_preference: str = ""  # "扁平" | "层级" | "时间优先" | "领域优先"
    time_axis_preference: str = ""  # "按创建时间" | "按修改时间" | "按文档内部时间" | "不关心"
    source_type_policy: dict = Field(default_factory=dict)
    exclusion_policy: dict = Field(default_factory=dict)

    # ── 消费入口组 ──
    human_reading_entry: str = ""
    ai_reading_entry: str = ""
    query_patterns: list[str] = Field(default_factory=list)

    # ── 输出偏好组 ──
    preferred_outputs: list[str] = Field(default_factory=list)
    report_preferences: dict = Field(default_factory=dict)
    enabled_components: list[str] = Field(default_factory=list)
    disabled_components: list[str] = Field(default_factory=list)

    # ── Wiki 模式组 ──
    wiki_mode: str = "ai_generated_human_browsable"
    wiki_editing: str = "disabled_for_user"
    wiki_maintenance: str = "automatic"
    wiki_role: list[str] = Field(default_factory=lambda: ["ai_memory_layer", "human_browsing_layer", "routing_layer"])

    # ── 元信息 ──
    confidence_map: dict[str, float] = Field(default_factory=dict)

    def field_names(self) -> list[str]:
        return [
            "primary_goal", "core_scenarios", "core_domains", "corpus_scale_estimate",
            "maintenance_willingness", "current_workflow", "source_file_types", "privacy_level",
            "structure_preference", "time_axis_preference", "source_type_policy", "exclusion_policy",
            "human_reading_entry", "ai_reading_entry", "query_patterns",
            "preferred_outputs", "report_preferences", "enabled_components", "disabled_components",
            "wiki_mode", "wiki_editing", "wiki_maintenance", "wiki_role",
        ]
