from __future__ import annotations

import json
import yaml
from pathlib import Path

from diagnosis.schemas import UserKnowledgeProfile

from .schema_generator import generate_folder_schema, write_folder_schema
from .policy_generator import (
    generate_classification_policy,
    generate_exclusion_policy,
    generate_source_type_policy,
    write_policy,
)
from .report_template_generator import generate_report_template_plan, write_report_template_plan


def generate_blueprint(profile_path: str, component_plan_path: str | None,
                       output_dir: str) -> dict:
    profile = UserKnowledgeProfile.model_validate_json(
        Path(profile_path).read_text(encoding="utf-8")
    )
    cp: dict = {}
    if component_plan_path and Path(component_plan_path).exists():
        cp = yaml.safe_load(Path(component_plan_path).read_text(encoding="utf-8")) or {}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    # 1. folder_schema.yaml
    folder_schema = generate_folder_schema(profile, cp)
    fp = write_folder_schema(folder_schema, str(out / "folder_schema.yaml"))
    results["folder_schema"] = fp

    # 2. classification_policy.yaml
    class_policy = generate_classification_policy(profile, folder_schema, cp)
    fp = write_policy(class_policy, str(out / "classification_policy.yaml"))
    results["classification_policy"] = fp

    # 3. source_type_policy.yaml
    src_policy = generate_source_type_policy(profile)
    fp = write_policy(src_policy, str(out / "source_type_policy.yaml"))
    results["source_type_policy"] = fp

    # 4. exclusion_policy.yaml
    excl_policy = generate_exclusion_policy(profile)
    fp = write_policy(excl_policy, str(out / "exclusion_policy.yaml"))
    results["exclusion_policy"] = fp

    # 5. report_template_plan.yaml
    report_plan = generate_report_template_plan(profile, cp)
    fp = write_report_template_plan(report_plan, str(out / "report_template_plan.yaml"))
    results["report_template_plan"] = fp

    # 6. query_strategy_policy.yaml (from strategy/)
    from strategy.query_strategy_router import generate_strategy_policy
    strategy_policy = generate_strategy_policy(profile, cp)
    sp_path = out / "query_strategy_policy.yaml"
    sp_path.write_text(yaml.dump(
        strategy_policy.model_dump(mode="json"),
        allow_unicode=True, default_flow_style=False, sort_keys=False,
    ), encoding="utf-8")
    results["query_strategy_policy"] = str(sp_path.resolve())

    # 7. final_config_draft.yaml
    final_config = _build_final_config(profile, cp, results)
    fc_path = out / "final_config_draft.yaml"
    fc_path.write_text(yaml.dump(final_config, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
    results["final_config_draft"] = str(fc_path.resolve())

    # 8. knowledge_blueprint.md
    kb_md = _build_blueprint_markdown(profile, cp, results)
    kb_path = out / "knowledge_blueprint.md"
    kb_path.write_text(kb_md, encoding="utf-8")
    results["knowledge_blueprint"] = str(kb_path.resolve())

    return results


def _build_final_config(profile: UserKnowledgeProfile, cp: dict, results: dict) -> dict:
    return {
        "version": "deep-custom-v1",
        "generated_from": {
            "profile": "UserKnowledgeProfile",
            "component_plan": cp.get("version", "unknown"),
        },
        "structure": results.get("folder_schema", ""),
        "classification": results.get("classification_policy", ""),
        "source_types": results.get("source_type_policy", ""),
        "exclusions": results.get("exclusion_policy", ""),
        "reports": results.get("report_template_plan", ""),
        "query_strategy": results.get("query_strategy_policy", ""),
        "notes": [
            "这是 deep-custom 自动生成的配置草案",
            "所有路径需要在实际部署前验证",
            "LLM 配置需要设置 DEEPSEEK_API_KEY 环境变量",
        ],
    }


def _build_blueprint_markdown(profile: UserKnowledgeProfile, cp: dict, results: dict) -> str:
    domains = ", ".join(
        d.get("name", str(d)) if isinstance(d, dict) else str(d)
        for d in (profile.core_domains or [])[:5]
    )
    outputs = ", ".join(str(o) for o in (profile.preferred_outputs or [])[:5])

    lines = [
        "# Deep-Custom Knowledge Blueprint",
        "",
        f"> 生成时间: auto",
        f"> 基于: UserKnowledgeProfile",
        "",
        "## 用户概览",
        "",
        f"- **首要目标**: {profile.primary_goal or '未指定'}",
        f"- **核心领域**: {domains or '未指定'}",
        f"- **结构偏好**: {profile.structure_preference or '未指定'}",
        f"- **维护意愿**: {profile.maintenance_willingness or '未指定'}",
        f"- **隐私级别**: {profile.privacy_level or '未指定'}",
        f"- **期望产出**: {outputs or '未指定'}",
        "",
        "---",
        "",
        "## 知识库结构",
        "",
        f"详见 `folder_schema.yaml`",
        "",
        "---",
        "",
        "## 分类策略",
        "",
        f"详见 `classification_policy.yaml`",
        "",
        "### 源类型处理",
        "",
        f"详见 `source_type_policy.yaml`",
        "",
        "### 排除规则",
        "",
        f"详见 `exclusion_policy.yaml`",
        "",
        "---",
        "",
        "## 查询策略",
        "",
        "系统根据语料规模和问题类型自动选择最优策略：",
        "",
        "| 策略 | 适用场景 |",
        "|------|---------|",
        "| full_read_direct | 小语料（< 50k tokens）需完整上下文 |",
        "| metadata_filter_then_full_read | 有明确过滤条件且过滤后语料可控 |",
        "| fts_then_deep_read | 关键词明确，FTS5 快速定位 |",
        "| hybrid_retrieval_then_deep_read | 大语料开放式问题 |",
        "| wiki_cache_first | 有 AI wiki 缓存的概括性问题 |",
        "| report_first | 月报/季报/复盘请求 |",
        "| map_reduce_summary | 超长语料或文件夹级别分析 |",
        "",
        f"详见 `query_strategy_policy.yaml`",
        "",
        "---",
        "",
        "## 报告模板",
        "",
        f"详见 `report_template_plan.yaml`",
        "",
        "---",
        "",
        "## 配置文件",
        "",
        f"所有策略的合并配置: `final_config_draft.yaml`",
        "",
    ]

    return "\n".join(lines) + "\n"
