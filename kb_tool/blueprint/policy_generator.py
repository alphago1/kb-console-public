from __future__ import annotations

import yaml
from pathlib import Path

from diagnosis.schemas import UserKnowledgeProfile


def generate_classification_policy(profile: UserKnowledgeProfile,
                                    folder_schema: dict,
                                    component_plan: dict | None = None) -> dict:
    cp = component_plan or {}
    categories = folder_schema.get("categories", [])

    return {
        "version": "v1",
        "primary_categories": [c["name"] for c in categories if c.get("name") != "无法判断"],
        "fallback_category": "无法判断",
        "strategy": "rules_first_then_llm",
        "rules": _build_classification_rules(profile),
        "confidence_threshold": 0.75,
        "deep_read_threshold": 0.60,
        "deep_read_max_chars": 12000,
        "llm_model": "deepseek-v4-flash",
        "llm_temperature": 0.2,
        "max_concurrency": int(cp.get("max_concurrency", 8)),
        "label_normalization": True,
        "tag_normalization_fields": ["topic_tags", "emotion_tags"],
    }


def generate_source_type_policy(profile: UserKnowledgeProfile) -> dict:
    source_pref = str(profile.source_type_policy).lower()
    separate = any(kw in source_pref for kw in ["分开", "分离", "独立", "不能混"])

    types = {
        "原创思考": {
            "handling": "full_classify",
            "weight": 1.0,
            "include_in_kb": True,
        },
        "摘录加评论": {
            "handling": "classify_with_label" if not separate else "separate_category",
            "weight": 0.8,
            "include_in_kb": True,
        },
        "摘录": {
            "handling": "classify_with_label" if not separate else "separate_category",
            "weight": 0.6,
            "include_in_kb": True,
        },
        "课程笔记": {
            "handling": "classify_with_label" if not separate else "separate_category",
            "weight": 0.7,
            "include_in_kb": True,
        },
        "录音转写": {
            "handling": "review_first",
            "weight": 0.5,
            "include_in_kb": True,
        },
        "AI生成内容": {
            "handling": "separate_category" if not separate else "separate_category",
            "weight": 0.5,
            "include_in_kb": True,
        },
        "外部资料": {
            "handling": "classify_with_label" if not separate else "separate_category",
            "weight": 0.4,
            "include_in_kb": True,
        },
        "无法判断": {
            "handling": "review",
            "weight": 0.3,
            "include_in_kb": False,
        },
    }

    return {
        "version": "v1",
        "separate_source_types": separate,
        "types": types,
    }


def generate_exclusion_policy(profile: UserKnowledgeProfile) -> dict:
    excl = profile.exclusion_policy or {}
    exclude_str = str(excl).lower()

    patterns = ["~$*", "desktop.ini", "thumbs.db"]
    keywords = []
    source_types = []

    if "讲义" in exclude_str or "课件" in exclude_str:
        keywords.append("讲义")
        keywords.append("课件")
        keywords.append("slides")
    if "电子书" in exclude_str:
        keywords.append("电子书")
        source_types.append("电子书")
    if "合同" in exclude_str or "证件" in exclude_str:
        keywords.append("合同")
        keywords.append("证件")
        keywords.append("简历")
    if "下载" in exclude_str or "转载" in exclude_str:
        keywords.append("下载")
        keywords.append("转载")

    return {
        "version": "v1",
        "exclude_file_globs": patterns,
        "exclude_keywords": keywords,
        "exclude_source_types": source_types,
        "exclude_dir_globs": ["*/kb_out*", "*/docs*", "*/.venv*", "*/__pycache__*"],
        "exclude_if_empty_text": True,
        "exclude_if_rule_match": True,
    }


def _build_classification_rules(profile: UserKnowledgeProfile) -> list[dict]:
    rules = []
    source_pref = str(profile.source_type_policy).lower()

    if "课程" in source_pref or "讲义" in source_pref:
        rules.append({
            "name": "course_material",
            "condition": "filename contains 讲义/课件/slides",
            "action": "exclude",
            "reason": "外部课程材料，非个人原创内容",
        })

    if any(kw in str(profile.source_file_types).lower() for kw in ["docx", "word"]):
        rules.append({
            "name": "word_temp_files",
            "condition": "filename starts with ~$",
            "action": "exclude",
            "reason": "Word 临时文件",
        })

    rules.append({
        "name": "empty_or_unreadable",
        "condition": "extraction failed or text length == 0",
        "action": "exclude",
        "reason": "文件无法读取或内容为空",
    })

    return rules


def write_policy(policy: dict, path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.dump(policy, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return str(Path(path).resolve())
