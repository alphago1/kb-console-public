from __future__ import annotations

from .question_bank import QUESTIONS
from .schemas import InterviewPlan, InterviewQuestion, MissingInformation, UserKnowledgeProfile

MAX_QUESTIONS = 8


def _matches_field(q: dict, field_name: str) -> bool:
    return field_name in q.get("affects_fields", [])


def _matches_any_field(q: dict, field_names: list[str]) -> bool:
    return any(_matches_field(q, f) for f in field_names)


def plan_interview(profile: UserKnowledgeProfile,
                   gaps: list[MissingInformation],
                   max_questions: int = MAX_QUESTIONS) -> InterviewPlan:
    # Sort gaps by priority
    gaps_sorted = sorted(
        gaps,
        key=lambda g: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(g.priority, 99),
    )

    gap_fields = {g.field_name for g in gaps_sorted}

    selected: list[InterviewQuestion] = []
    skipped: list[dict] = []
    reason_map: dict[str, str] = {}

    # Phase 1: pick one question per critical/high gap
    for g in gaps_sorted:
        if g.priority not in ("critical", "high"):
            continue
        if len(selected) >= max_questions:
            break
        candidates = [q for q in QUESTIONS if _matches_field(q, g.field_name)]
        if not candidates:
            skipped.append({"field": g.field_name, "reason": "no matching question in bank", "priority": g.priority})
            continue
        best = candidates[0]
        iq = InterviewQuestion(**best)
        selected.append(iq)
        reason_map[iq.question_id] = f"覆盖 critical/high 缺口字段 {g.field_name} (置信度 {g.current_confidence:.2f})"

    # Phase 2: fill remaining slots with medium-priority gaps
    for g in gaps_sorted:
        if g.priority != "medium":
            continue
        if len(selected) >= max_questions:
            break
        already_covered_fields = set()
        for q in selected:
            already_covered_fields.update(q.affects_fields)
        if g.field_name in already_covered_fields:
            continue
        candidates = [q for q in QUESTIONS if _matches_field(q, g.field_name)]
        if not candidates:
            skipped.append({"field": g.field_name, "reason": "no matching question in bank", "priority": g.priority})
            continue
        best = candidates[0]
        iq = InterviewQuestion(**best)
        selected.append(iq)
        reason_map[iq.question_id] = f"覆盖 medium 缺口字段 {g.field_name} (置信度 {g.current_confidence:.2f})"

    # Phase 3: cross-coverage check — ensure each gap field has at least one question
    covered_fields: set[str] = set()
    for q in selected:
        covered_fields.update(q.affects_fields)

    uncovered_gaps = [g for g in gaps_sorted if g.field_name not in covered_fields and g.priority in ("critical", "high")]
    for g in uncovered_gaps:
        if len(selected) >= max_questions:
            break
        candidates = [q for q in QUESTIONS if _matches_field(q, g.field_name)]
        if not candidates:
            skipped.append({"field": g.field_name, "reason": "no question available for critical/high gap", "priority": g.priority})
            continue
        best = candidates[0]
        iq = InterviewQuestion(**best)
        selected.append(iq)
        reason_map[iq.question_id] = f"交叉覆盖检查补充 critical/high 缺口字段 {g.field_name}"

    # Mark skipped questions with reasons
    selected_ids = {q.question_id for q in selected}
    for q in QUESTIONS:
        if q["question_id"] in selected_ids:
            continue
        if _matches_any_field(q, list(gap_fields)):
            # Should have been considered but wasn't picked
            if len(selected) >= max_questions:
                skipped.append({"question_id": q["question_id"], "reason": "超出 max_questions 限制", "priority": "n/a"})
        else:
            skipped.append({"question_id": q["question_id"], "reason": "不影响当前缺口字段", "priority": "n/a"})

    # Build profile summary
    domains_str = ", ".join(d.get("name", d) if isinstance(d, dict) else str(d)
                            for d in (profile.core_domains or [])[:3])
    profile_summary = (
        f"目标: {profile.primary_goal or '未知'}. "
        f"主要领域: {domains_str or '未知'}. "
        f"维护意愿: {profile.maintenance_willingness or '未知'}. "
        f"结构偏好: {profile.structure_preference or '未知'}. "
        f"隐私级别: {profile.privacy_level or '未知'}."
    )

    return InterviewPlan(
        existing_profile_summary=profile_summary,
        missing_information=gaps_sorted,
        selected_questions=selected,
        skipped_questions=skipped,
        reason_for_each_question=reason_map,
    )
