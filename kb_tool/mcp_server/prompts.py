from __future__ import annotations


def list_prompts() -> list[dict]:
    return [
        {"name": "kb.trading_review", "description": "按月份分析交易错误与复盘证据"},
        {"name": "kb.cognition_evolution", "description": "分析认知变化与演化路径"},
        {"name": "kb.monthly_reflection", "description": "生成月度反思结构化摘要"},
        {"name": "kb.article_outline", "description": "从写作候选文档生成文章大纲"},
        {"name": "kb.project_synthesis", "description": "聚合项目想法并输出阶段建议"},
    ]


def get_prompt(name: str, arguments: dict | None = None) -> dict:
    arguments = arguments or {}

    templates = {
        "kb.trading_review": (
            "请基于知识库工具分析指定时间段内的交易复盘。\\n"
            "要求：\\n"
            "1. 先搜索交易复盘和交易系统文档\\n"
            "2. 再搜索情绪标签和执行力相关片段\\n"
            "3. 按月份归纳错误类型\\n"
            "4. 输出证据文档\\n"
            "5. 不得编造未检索到的结论"
        ),
        "kb.cognition_evolution": "请梳理认知变化：旧观点、新观点、触发证据、未解决问题。",
        "kb.monthly_reflection": "请输出本月交易/情绪/认知/项目/写作五部分反思摘要。",
        "kb.article_outline": "请基于写作候选文档，生成可执行文章大纲与论点结构。",
        "kb.project_synthesis": "请聚合重复出现的项目想法，给出优先级和下一步验证计划。",
    }

    content = templates.get(name)
    if not content:
        return {"error": "prompt not found", "name": name}

    if arguments:
        content += "\\n\\n参数：" + str(arguments)

    return {"name": name, "content": content}
