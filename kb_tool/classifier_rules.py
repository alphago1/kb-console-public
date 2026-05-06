from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleDecision:
    include_in_kb: bool
    exclude_reason: str | None = None
    needs_review: bool = False
    source_type_hint: str | None = None


def apply_rules(cfg: dict, filename: str, path: str) -> RuleDecision | None:
    # Return None means "no rule decision; continue to LLM"

    rules = cfg.get("rules", {})

    # Office temp files
    if filename.startswith("~$"):
        return RuleDecision(include_in_kb=False, exclude_reason="临时文件")

    cm = rules.get("course_material", {})
    if cm.get("enabled"):
        lowered = filename.lower()
        # if looks like raw slides/handouts => exclude
        for key in cm.get("exclude_if_name_contains", []):
            if key.lower() in lowered:
                return RuleDecision(include_in_kb=False, exclude_reason="课程讲义/课件")
        # transcripts default review
        for key in cm.get("review_if_name_contains", []):
            if key.lower() in lowered:
                return RuleDecision(include_in_kb=True, needs_review=True, source_type_hint="录音转写")
        # notes include
        for key in cm.get("include_if_name_contains", []):
            if key.lower() in lowered:
                return None

    return None
