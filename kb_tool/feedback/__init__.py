from .feedback_schema import (
    FileCorrectionType,
    RuleAction,
    StructureAction,
    ComponentAction,
    FileLevelFeedback,
    RuleLevelFeedback,
    StructureLevelFeedback,
    ComponentLevelFeedback,
    UserFeedbackBundle,
    FormalRule,
    PolicyDiffEntry,
    StructureDiffEntry,
    FeedbackRulePlan,
)
from .rule_generator import parse_user_feedback, generate_rule_plan
from .policy_diff import generate_policy_diff_markdown, generate_policy_changes_for_apply
from .structure_diff import generate_structure_diff_markdown, apply_structure_changes
from .preview import preview_affected_files, generate_expected_changes_markdown
from .apply_feedback import apply_feedback_plan

__all__ = [
    # Schema
    "FileCorrectionType",
    "RuleAction",
    "StructureAction",
    "ComponentAction",
    "FileLevelFeedback",
    "RuleLevelFeedback",
    "StructureLevelFeedback",
    "ComponentLevelFeedback",
    "UserFeedbackBundle",
    "FormalRule",
    "PolicyDiffEntry",
    "StructureDiffEntry",
    "FeedbackRulePlan",
    # Core functions
    "parse_user_feedback",
    "generate_rule_plan",
    "generate_policy_diff_markdown",
    "generate_policy_changes_for_apply",
    "generate_structure_diff_markdown",
    "apply_structure_changes",
    "preview_affected_files",
    "generate_expected_changes_markdown",
    "apply_feedback_plan",
]
