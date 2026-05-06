from __future__ import annotations

import yaml
from pathlib import Path

from .baseline_schema import BaselineComponent

_COMPONENTS_DIR = Path(__file__).resolve().parents[1] / "components" / "definitions"

_KARPATHY_DEFAULTS: list[dict] = [
    # ── Layer 1: Raw Sources ──
    {
        "component_id": "raw_sources.read_only_store",
        "layer": "raw_sources",
        "name": "原始资料只读存储",
        "description": "用户所有原始文件（docx/md/txt）只读保存，不移动、不修改、不删除。作为一切分析的事实基础。",
        "default_policy": "源文件只读，通过 SHA256 指纹去重，通过 source_path 追踪原始位置",
        "human_facing": False,
        "ai_facing": True,
    },
    {
        "component_id": "raw_sources.format_agnostic",
        "layer": "raw_sources",
        "name": "多格式兼容",
        "description": "支持 docx/md/txt 等常见格式的文本提取和索引",
        "default_policy": "LibreOffice 提取 docx，直接读取 md/txt，提取全文缓存到 text_cache/",
        "human_facing": False,
        "ai_facing": True,
    },
    # ── Layer 2: Wiki Layer ──
    {
        "component_id": "wiki_layer.topic_pages",
        "layer": "wiki_layer",
        "name": "AI 维护的主题页面",
        "description": "每个核心话题一个 Markdown 页面，AI 从原始资料中提取、综合、持续更新",
        "default_policy": "每个 core_domain 下的活跃话题自动生成 topic page，包含：定义、关键观点、证据引用、演化时间线、开放问题",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "wiki_layer.project_pages",
        "layer": "wiki_layer",
        "name": "项目页面",
        "description": "每个项目一个页面，包含项目目标、当前状态、关键决策、相关文档",
        "default_policy": "自动从 topic_tags 中检测项目名，生成 project page，包含：目标、状态、里程碑、技术决策、相关文档",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "wiki_layer.profile_pages",
        "layer": "wiki_layer",
        "name": "用户画像页面",
        "description": "AI 定期更新的用户认知画像",
        "default_policy": "基于全量文档每季度更新，包含：关注领域、决策模式、认知演化、情绪模式、开放问题",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "wiki_layer.cross_references",
        "layer": "wiki_layer",
        "name": "跨页面引用",
        "description": "topic/project/profile 页面之间的双向链接",
        "default_policy": "使用 Obsidian-style [[双链]] 语法，AI 自动维护引用关系",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "wiki_layer.ai_wiki_cache",
        "layer": "wiki_layer",
        "name": "AI 维基缓存",
        "description": "AI 内部使用的压缩版 wiki 缓存，供 LLM 上下文消费",
        "default_policy": "全量 wiki 压缩为 compact_cache.json，按 topic 分块，供 Agent/MCP 工具调用时使用",
        "human_facing": False,
        "ai_facing": True,
    },
    # ── Layer 3: Index & Log ──
    {
        "component_id": "index_log.human_index",
        "layer": "index_log",
        "name": "人类可读索引",
        "description": "全局 index.md，列出所有 topic/project/profile 页面，含简要描述和最后更新时间",
        "default_policy": "自动生成 index.md，按 domain 分组，每项含：页面名、简要描述、最后更新时间、证据数量",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "index_log.topic_index",
        "layer": "index_log",
        "name": "话题索引（机器可读）",
        "description": "topic → pages → source_files 的完整映射表",
        "default_policy": "JSON 格式存储，每次 wiki 更新后自动重建，供 Agent 工具调用",
        "human_facing": False,
        "ai_facing": True,
    },
    {
        "component_id": "index_log.update_log",
        "layer": "index_log",
        "name": "更新日志",
        "description": "记录每次 AI 对 wiki 的修改",
        "default_policy": "Markdown 格式，人类可读。每次 wiki 更新追加一条：时间、更新类型、受影响页面、变更摘要、触发来源",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "index_log.ingest_log",
        "layer": "index_log",
        "name": "摄入日志",
        "description": "记录每次新文件进入知识库",
        "default_policy": "JSONL 格式，机器可读。每次新文件摄入记录：时间、文件名、分类、分类置信度、提取字数",
        "human_facing": False,
        "ai_facing": True,
    },
    # ── Layer 4: Schema Rules ──
    {
        "component_id": "schema_rules.update_policy",
        "layer": "schema_rules",
        "name": "AI 更新规则",
        "description": "定义 AI 何时以及如何更新 wiki 页面",
        "default_policy": "新文件摄入后触发 topic update；每月进行一次全量 review；若新证据与现有结论冲突，标记而非覆盖",
        "human_facing": False,
        "ai_facing": True,
    },
    {
        "component_id": "schema_rules.naming_convention",
        "layer": "schema_rules",
        "name": "页面命名规范",
        "description": "wiki 页面的命名规则",
        "default_policy": "topic pages: `topic_{slug}.md`; project pages: `project_{slug}.md`; profile: `profile.md`",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "schema_rules.conflict_handling",
        "layer": "schema_rules",
        "name": "冲突处理规则",
        "description": "AI 推断 vs 用户明确表述冲突时的处理策略",
        "default_policy": "用户明确表述 > AI 推断。冲突时保留两者并标记，等待用户反馈。不自动覆盖用户确认过的内容。",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "schema_rules.source_tracking",
        "layer": "schema_rules",
        "name": "来源追踪",
        "description": "每条 wiki 结论必须能追溯到源文件",
        "default_policy": "每条结论后附 `[source: {filename}#{chunk}]` 引用。不支持无来源的 wiki 内容。",
        "human_facing": True,
        "ai_facing": True,
    },
    # ── Layer 5: Lint ──
    {
        "component_id": "lint.duplicate_topics",
        "layer": "lint",
        "name": "重复主题检测",
        "description": "检查是否存在内容高度重叠的 topic pages",
        "default_policy": "每月运行一次，计算 topic page 之间的语义相似度，>0.7 的建议合并",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "lint.stale_viewpoints",
        "layer": "lint",
        "name": "过期观点检查",
        "description": "检查超过 N 个月未更新且与新证据矛盾的观点",
        "default_policy": "每季度运行一次，对比当前 wiki 内容和最近 3 个月的原始文件，标记可能过期的结论",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "lint.orphan_pages",
        "layer": "lint",
        "name": "孤立页面检测",
        "description": "检查没有被任何其他页面引用且长期未更新的页面",
        "default_policy": "每月运行，标记被 0 个其他页面引用且 3 个月未更新的页面",
        "human_facing": True,
        "ai_facing": True,
    },
    {
        "component_id": "lint.sourceless_claims",
        "layer": "lint",
        "name": "无来源结论检查",
        "description": "检查 wiki 页面中缺少 source 引用的结论",
        "default_policy": "每次 wiki 更新后运行，标记所有缺少 `[source: ...]` 的结论性语句",
        "human_facing": True,
        "ai_facing": True,
    },
]


def _load_component_yaml(component_id: str, layer: str) -> dict | None:
    """Load YAML override for a component. Tries exact match first, then layer-level match."""
    exact_path = _COMPONENTS_DIR / f"{component_id.replace('.', '_')}.yaml"
    layer_path = _COMPONENTS_DIR / f"karpathy_{layer}.yaml"

    for yaml_path in (exact_path, layer_path):
        if not yaml_path.exists():
            continue
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                continue
            yaml_cid = data.get("component_id", "")
            is_exact = yaml_path == exact_path
            is_layer = yaml_path == layer_path
            if is_exact and yaml_cid and yaml_cid != component_id:
                continue
            if is_layer and yaml_cid and yaml_cid != layer and yaml_cid != component_id:
                continue
            return data
        except Exception:
            pass
    return None


def _apply_layer_overrides(d: dict, yaml_data: dict) -> dict:
    """Apply YAML-level overrides to component dict. Top-level keys in YAML override matching keys in component dict."""
    merged = dict(d)
    for key in ("description", "default_policy", "human_facing", "ai_facing", "name"):
        if key in yaml_data and yaml_data[key] is not None:
            merged[key] = yaml_data[key]
    if "rules" in yaml_data:
        merged["default_policy"] = merged.get("default_policy", "") + "\n" + yaml.dump(yaml_data["rules"], allow_unicode=True).strip()
    return merged


def generate_baseline() -> list[BaselineComponent]:
    components: list[BaselineComponent] = []
    for d in _KARPATHY_DEFAULTS:
        yaml_data = _load_component_yaml(d["component_id"], d["layer"])
        if yaml_data:
            d = _apply_layer_overrides(d, yaml_data)
        components.append(BaselineComponent(**d))
    return components


def write_baseline_markdown(components: list[BaselineComponent], output_path: str) -> str:
    lines = [
        "# Karpathy-Style AI Wiki Baseline",
        "",
        "> 版本: karpathy-v1 | 生成时间: auto",
        "> 这是一个默认高质量知识库架构。后续会基于用户画像进行个性化适配。",
        "",
        "---",
        "",
    ]

    layers_order = ["raw_sources", "wiki_layer", "index_log", "schema_rules", "lint"]
    layer_names = {
        "raw_sources": "Layer 1: Raw Sources（原始资料层）",
        "wiki_layer": "Layer 2: Wiki Layer（AI 维护的结构化知识层）",
        "index_log": "Layer 3: Index & Log（索引与日志层）",
        "schema_rules": "Layer 4: Schema Rules（AI 行为规则层）",
        "lint": "Layer 5: Lint（质量检查层）",
    }

    for layer in layers_order:
        layer_comps = [c for c in components if c.layer == layer]
        if not layer_comps:
            continue
        lines.append(f"## {layer_names[layer]}")
        lines.append("")
        for c in layer_comps:
            lines.append(f"### {c.name}")
            lines.append("")
            lines.append(f"- **ID**: `{c.component_id}`")
            lines.append(f"- **描述**: {c.description}")
            lines.append(f"- **默认策略**: {c.default_policy}")
            lines.append(f"- **人类可见**: {'是' if c.human_facing else '否'}")
            lines.append(f"- **AI 可见**: {'是' if c.ai_facing else '否'}")
            lines.append("")

    md = "\n".join(lines) + "\n"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(md, encoding="utf-8")
    return str(Path(output_path).resolve())
