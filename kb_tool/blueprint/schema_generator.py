from __future__ import annotations

import yaml

from diagnosis.schemas import UserKnowledgeProfile


def generate_folder_schema(profile: UserKnowledgeProfile, component_plan: dict | None = None) -> dict:
    cp = component_plan or {}
    structure = _determine_structure(profile)

    categories = _generate_categories(profile)
    time_granularity = "month"
    if profile.time_axis_preference and "不关心" in str(profile.time_axis_preference):
        time_granularity = "none"

    return {
        "version": "v1",
        "root": "docs/",
        "structure": structure,
        "levels": 2 if time_granularity != "none" else 1,
        "categories": categories,
        "time_granularity": time_granularity,
        "naming_convention": "{category}/{month}/{filename}_{sha8}.{ext}",
        "inbox_dir": "_weekly_inbox",
    }


def _determine_structure(profile: UserKnowledgeProfile) -> dict:
    pref = str(profile.structure_preference).lower()
    if "时间" in pref:
        return {"type": "time_first", "primary_axis": "time", "secondary_axis": "category"}
    else:
        return {"type": "domain_first", "primary_axis": "category", "secondary_axis": "time"}


def _generate_categories(profile: UserKnowledgeProfile) -> list[dict]:
    cats: list[dict] = []
    domains = profile.core_domains or []

    for d in domains:
        if isinstance(d, dict):
            name = d.get("name", str(d))
            desc = d.get("description", "")
        else:
            name = str(d)
            desc = ""
        if name and len(name) < 30:
            cats.append({"name": name, "description": desc, "source": "user_profile"})

    if not cats:
        cats = [
            {"name": "个人记录", "description": "日常随笔和思考", "source": "default"},
            {"name": "学习笔记", "description": "课程和阅读笔记", "source": "default"},
            {"name": "项目相关", "description": "项目和任务记录", "source": "default"},
            {"name": "外部资料", "description": "收藏和转载", "source": "default"},
        ]

    cats.append({"name": "无法判断", "description": "AI 无法确定分类的文档", "source": "system"})
    return cats


def write_folder_schema(schema: dict, path: str) -> str:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.dump(schema, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return str(Path(path).resolve())
