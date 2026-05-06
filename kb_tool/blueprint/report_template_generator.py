from __future__ import annotations

import yaml
from pathlib import Path

from diagnosis.schemas import UserKnowledgeProfile


def generate_report_template_plan(profile: UserKnowledgeProfile,
                                   component_plan: dict | None = None) -> dict:
    cp = component_plan or {}
    outputs = str(profile.preferred_outputs).lower()

    templates = {}

    # Weekly summary
    if any(kw in outputs for kw in ["每周", "周报", "weekly"]):
        templates["weekly_summary"] = {
            "enabled": True,
            "frequency": "weekly",
            "trigger": "weekly_organize_complete",
            "description": "本周新入库文件摘要，按分类分组，标注置信度",
            "max_items": 30,
            "include_snippets": True,
        }

    # Monthly review
    if any(kw in outputs for kw in ["月度", "月报", "monthly"]):
        templates["monthly_review"] = {
            "enabled": True,
            "frequency": "monthly",
            "trigger": "first_of_month",
            "description": "本月核心认知变化、新增规则、情绪模式、开放问题进展",
            "sections": ["本月主要输入", "认知变化", "情绪模式", "开放问题", "下月关注"],
            "require_citation": True,
        }

    # Quarterly evolution
    if any(kw in outputs for kw in ["季度", "季报", "演化", "跨时间"]):
        templates["quarterly_evolution"] = {
            "enabled": True,
            "frequency": "quarterly",
            "trigger": "first_of_quarter",
            "description": "跨时间认知变化检测，信念验证/推翻，长期趋势分析",
            "sections": ["认知演化时间线", "被验证的信念", "被推翻的信念", "新出现的关注", "消失的关注"],
            "require_cross_period_comparison": True,
        }

    # Blind spot alert
    if any(kw in outputs for kw in ["盲区", "遗漏", "blind"]):
        templates["blind_spot_alert"] = {
            "enabled": True,
            "frequency": "monthly",
            "trigger": "monthly_review_complete",
            "description": "知识盲区检测——应该关注但未涉及或记录不足的话题",
            "detection_method": "topic_coverage_gap_analysis",
        }

    # Writing candidates
    if any(kw in outputs for kw in ["写作", "素材", "成文", "writing"]):
        templates["writing_candidates"] = {
            "enabled": True,
            "frequency": "weekly",
            "trigger": "weekly_organize_complete",
            "description": "写作潜力高的文档候选列表",
            "sort_by": "writing_potential",
            "max_items": 15,
        }

    # Profile report
    if any(kw in outputs for kw in ["画像", "profile"]):
        templates["profile_report"] = {
            "enabled": True,
            "frequency": "quarterly",
            "trigger": "quarterly_evolution_complete",
            "description": "用户认知画像更新",
            "sections": ["关注领域", "决策模式", "情绪/执行力模式", "写作倾向", "开放问题"],
        }

    # Dashboard
    if any(kw in outputs for kw in ["dashboard", "大盘", "可视化"]):
        templates["dashboard"] = {
            "enabled": True,
            "frequency": "on_demand",
            "trigger": "manual_or_weekly",
            "description": "知识库全局统计大盘",
            "charts": ["heatmap", "trend", "category_distribution"],
        }

    return {
        "version": "v1",
        "templates": templates,
        "output_dir": "kb_out/reports/",
        "format": "markdown",
        "llm_model": "deepseek-v4-flash",
        "budget_aware": True,
    }


def write_report_template_plan(plan: dict, path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.dump(plan, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return str(Path(path).resolve())
