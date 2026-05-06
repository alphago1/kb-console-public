from .baseline_schema import AdaptationDecision, AdaptationDiff, AdaptedBlueprint, BaselineComponent
from .baseline_generator import generate_baseline, write_baseline_markdown
from .adaptation_rules import adapt_component
from .compatibility import check_report_first_compatibility, check_word_compatibility
from .diff_generator import generate_blueprint, generate_diff, write_diff_markdown

__all__ = [
    "AdaptationDecision",
    "AdaptationDiff",
    "AdaptedBlueprint",
    "BaselineComponent",
    "generate_baseline",
    "write_baseline_markdown",
    "adapt_component",
    "check_word_compatibility",
    "check_report_first_compatibility",
    "generate_diff",
    "write_diff_markdown",
    "generate_blueprint",
]
