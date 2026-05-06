from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Feedback item types ──

class FileCorrectionType(str, Enum):
    EXCLUDE = "exclude"              # 这个文件不该纳入
    RECATEGORIZE = "recategorize"    # 这个文件分类错了
    MARK_EXTERNAL = "mark_external"  # 这个文件是外部资料
    MARK_ORIGINAL = "mark_original"  # 这个文件是原创


class RuleAction(str, Enum):
    EXCLUDE_BY_KEYWORD = "exclude_by_keyword"
    EXCLUDE_BY_SOURCE_TYPE = "exclude_by_source_type"
    EXCLUDE_BY_PATTERN = "exclude_by_pattern"
    EXCLUDE_BY_CATEGORY = "exclude_by_category"
    SET_DEFAULT_CATEGORY = "set_default_category"
    SET_DEFAULT_SOURCE_TYPE = "set_default_source_type"
    RECATEGORIZE_BY_CATEGORY = "recategorize_by_category"
    TREAT_AS_TAG = "treat_as_tag"


class StructureAction(str, Enum):
    MERGE_CATEGORIES = "merge_categories"
    SPLIT_CATEGORY = "split_category"
    DELETE_CATEGORY = "delete_category"
    CREATE_CATEGORY = "create_category"
    CHANGE_TIME_AXIS = "change_time_axis"
    CHANGE_DIR_STRUCTURE = "change_dir_structure"
    CHANGE_REPORT_TEMPLATE = "change_report_template"


class ComponentAction(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    SET_VISIBILITY = "set_visibility"  # human-only / ai-only / both


# ── Feedback items ──

class FileLevelFeedback(BaseModel):
    """Single file-level correction from user review of sample run."""
    file_path: str
    correction: FileCorrectionType
    new_category: str = ""        # if recategorize
    new_source_type: str = ""     # if mark_external / mark_original
    reason: str = ""
    confidence: float = 1.0


class RuleLevelFeedback(BaseModel):
    """User specifies a general rule — apply to all matching files."""
    description: str              # human-readable, e.g. "以后课程转写默认外部资料"
    action: RuleAction
    # condition fields
    match_keywords: list[str] = Field(default_factory=list)
    match_source_types: list[str] = Field(default_factory=list)
    match_categories: list[str] = Field(default_factory=list)
    match_patterns: list[str] = Field(default_factory=list)
    target_action_value: str = ""  # what to set (category / source_type / label)
    reason: str = ""
    priority: int = 5             # 1=highest, 10=lowest


class StructureLevelFeedback(BaseModel):
    """User changes the knowledge base structure itself."""
    description: str
    action: StructureAction
    source_categories: list[str] = Field(default_factory=list)  # for merge / delete
    target_category: str = ""     # for create / merge result
    split_rules: dict = Field(default_factory=dict)  # for split
    time_preference: str = ""     # for change_time_axis
    dir_structure: str = ""       # for change_dir_structure
    report_changes: dict = Field(default_factory=dict)  # for change_report_template
    reason: str = ""


class ComponentLevelFeedback(BaseModel):
    """User enables/disables/changes component visibility."""
    component_name: str
    action: ComponentAction
    visibility: str = ""          # "human" | "ai" | "both"
    reason: str = ""


# ── Aggregated bundles ──

class UserFeedbackBundle(BaseModel):
    session: str = ""
    file_feedback: list[FileLevelFeedback] = Field(default_factory=list)
    rule_feedback: list[RuleLevelFeedback] = Field(default_factory=list)
    structure_feedback: list[StructureLevelFeedback] = Field(default_factory=list)
    component_feedback: list[ComponentLevelFeedback] = Field(default_factory=list)


# ── Formalized rule plan (output of feedback-plan) ──

class FormalRule(BaseModel):
    """One formalized rule derived from feedback."""
    rule_id: str
    source: str                    # "file_feedback" | "rule_feedback" | "structure_feedback" | "component_feedback"
    source_item_index: int         # index in source list
    rule_type: str                 # "exclusion" | "classification" | "source_type" | "folder_schema" | "component" | "report"
    human_explanation: str         # always human-readable
    condition_spec: dict = Field(default_factory=dict)
    action_spec: dict = Field(default_factory=dict)
    affected_file_count_estimate: int = 0
    priority: int = 5
    requires_confirmation: bool = True


class PolicyDiffEntry(BaseModel):
    """One entry in policy_diff."""
    policy_file: str               # classification_policy.yaml / source_type_policy.yaml / exclusion_policy.yaml
    section_path: str              # e.g. "primary_categories[2]" or "rules.classification[0]"
    change_type: str               # "add" | "remove" | "modify" | "reorder"
    old_value: str = ""
    new_value: str = ""
    reason: str = ""
    human_readable: str = ""


class StructureDiffEntry(BaseModel):
    """One entry in structure_diff."""
    structure_file: str            # folder_schema.yaml / report_template_plan.yaml
    change_type: str               # "merge_categories" | "split_category" | "delete_category" | "create_category" | "rename_category" | "change_time" | "change_report"
    description: str
    before: str
    after: str
    affected_files_estimate: int = 0
    reason: str = ""


class FeedbackRulePlan(BaseModel):
    """Complete feedback rule plan — the output format of feedback-plan command."""
    version: str = "v1"
    session: str = ""
    source_feedback: str = ""      # path to user_feedback.yaml
    source_sample: str = ""        # path to sample_selection.csv
    source_blueprint: str = ""     # path to blueprint dir
    formal_rules: list[FormalRule] = Field(default_factory=list)
    policy_diffs: list[PolicyDiffEntry] = Field(default_factory=list)
    structure_diffs: list[StructureDiffEntry] = Field(default_factory=list)
    affected_file_count: int = 0
    summary: str = ""
