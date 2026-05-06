from __future__ import annotations

from diagnosis.schemas import UserKnowledgeProfile
from .corpus_estimator import estimate_corpus
from .strategy_schemas import CorpusEstimate, QueryAnalysis, StrategyLayer, StrategyPolicy, StrategyStack

# ── Layer definitions ──
# Each strategy is defined as a STACK of 1-3 layers, NOT a single choice.

LAYER_PREFILTER_METADATA = StrategyLayer(
    layer=1, strategy_name="metadata_filter",
    description="按时间/分类/标签 SQL WHERE 过滤，缩小候选范围",
    parameters={"filter_type": "sql_where", "max_results": 500},
)

LAYER_PREFILTER_FTS = StrategyLayer(
    layer=1, strategy_name="fts_keyword_filter",
    description="FTS5 BM25 关键词搜索，快速锁定相关文档",
    parameters={"engine": "sqlite_fts5", "top_k": 50, "snippet_length": 12},
)

LAYER_PREFILTER_NONE = StrategyLayer(
    layer=1, strategy_name="no_prefilter",
    description="不预过滤，保留全量文档进入下一层",
    parameters={},
)

LAYER_RETRIEVE_FULL_READ = StrategyLayer(
    layer=2, strategy_name="full_read",
    description="全量读入所有候选文档的全文",
    parameters={"max_chars": 1_000_000, "budget_strategy": "accumulate_until_full"},
)

LAYER_RETRIEVE_CHUNK_TOP = StrategyLayer(
    layer=2, strategy_name="chunk_top_n",
    description="读取 FTS5 命中的 top-N chunk 全文",
    parameters={"top_n": 20, "expand_context_chars": 500},
)

LAYER_RETRIEVE_WIKI_CACHE = StrategyLayer(
    layer=2, strategy_name="wiki_cache",
    description="先读取 AI 维护的 wiki 缓存（压缩版知识页）",
    parameters={"cache_path": "kb_out/cache/wiki_cache.json", "max_chars": 100_000},
)

LAYER_RETRIEVE_REPORT = StrategyLayer(
    layer=2, strategy_name="report_lookup",
    description="搜索已有报告（月报/季报/专题分析）",
    parameters={"report_dir": "kb_out/reports/", "max_reports": 5},
)

LAYER_ANALYZE_DIRECT_LLM = StrategyLayer(
    layer=3, strategy_name="direct_llm",
    description="将检索到的文本直接送入 LLM 分析",
    parameters={"temperature": 0.2, "require_citation": True},
)

LAYER_ANALYZE_MAP_REDUCE = StrategyLayer(
    layer=3, strategy_name="map_reduce",
    description="分批 LLM 压缩 → 合并 → LLM 综合，处理超长语料",
    parameters={"chunk_size": 800_000, "concurrency": 4, "compression_ratio": 0.3},
)

LAYER_ANALYZE_HYBRID = StrategyLayer(
    layer=3, strategy_name="hybrid_synthesize",
    description="关键词结果 + Agent 语义结果 → 合并去重 → LLM 综合分析",
    parameters={"fts_weight": 0.4, "agentic_weight": 0.6, "dedup_method": "sha256"},
)


# ── Strategy Stack definitions ──
# Each stack = a complete 1-3 layer pipeline for a specific query×corpus combination

def _build_all_stacks() -> dict[str, StrategyStack]:
    stacks: dict[str, StrategyStack] = {}

    # ── full_read_direct: tiny/small corpus, need full context ──
    for qtype in ("open_analysis", "compare", "finding_specific"):
        for bucket in ("tiny",):
            key = f"{qtype}:{bucket}"
            stacks[key] = StrategyStack(
                query_type=qtype, corpus_bucket=bucket,
                primary_layers=[LAYER_PREFILTER_NONE, LAYER_RETRIEVE_FULL_READ, LAYER_ANALYZE_DIRECT_LLM],
                fallback_chain=["fts_then_deep_read"],
                trigger_conditions={"max_tokens": 50_000, "corpus_buckets": ["tiny"]},
                latency_estimate="fast", cost_estimate="low",
            )

    # ── metadata_filter_then_full_read: with filters, small filtered corpus ──
    for qtype in ("open_analysis", "compare", "summary"):
        key = f"{qtype}:filtered_small"
        stacks[key] = StrategyStack(
            query_type=qtype, corpus_bucket="small",
            primary_layers=[LAYER_PREFILTER_METADATA, LAYER_RETRIEVE_FULL_READ, LAYER_ANALYZE_DIRECT_LLM],
            fallback_chain=["fts_then_deep_read"],
            trigger_conditions={"has_filters": True, "filtered_tokens_max": 80_000},
            latency_estimate="fast", cost_estimate="low",
        )

    # ── fts_then_deep_read: keyword-explicit queries ──
    for qtype in ("keyword_search", "finding_specific"):
        for bucket in ("small", "medium", "large"):
            key = f"{qtype}:{bucket}"
            stacks[key] = StrategyStack(
                query_type=qtype, corpus_bucket=bucket,
                primary_layers=[LAYER_PREFILTER_FTS, LAYER_RETRIEVE_CHUNK_TOP, LAYER_ANALYZE_DIRECT_LLM],
                fallback_chain=["hybrid_retrieval_then_deep_read", "map_reduce_summary"],
                trigger_conditions={"question_types": ["keyword_search", "finding_specific"]},
                latency_estimate="fast", cost_estimate="low",
            )

    # ── hybrid_retrieval_then_deep_read: large corpus, open-ended ──
    for qtype in ("open_analysis", "compare"):
        for bucket in ("medium", "large"):
            key = f"{qtype}:{bucket}"
            stacks[key] = StrategyStack(
                query_type=qtype, corpus_bucket=bucket,
                primary_layers=[LAYER_PREFILTER_FTS, LAYER_RETRIEVE_CHUNK_TOP, LAYER_ANALYZE_HYBRID],
                fallback_chain=["map_reduce_summary"],
                trigger_conditions={"question_types": ["open_analysis", "compare"], "corpus_buckets": ["medium", "large"]},
                latency_estimate="balanced", cost_estimate="medium",
            )

    # ── wiki_cache_first: summary questions with wiki cache ──
    for qtype in ("summary", "open_analysis"):
        for bucket in ("small", "medium", "large"):
            key = f"{qtype}:{bucket}:wiki"
            stacks[key] = StrategyStack(
                query_type=qtype, corpus_bucket=bucket,
                primary_layers=[LAYER_PREFILTER_NONE, LAYER_RETRIEVE_WIKI_CACHE, LAYER_ANALYZE_DIRECT_LLM],
                fallback_chain=["fts_then_deep_read", "hybrid_retrieval_then_deep_read"],
                trigger_conditions={"wiki_cache_strategy": "full_pages", "question_types": ["summary"]},
                latency_estimate="fast", cost_estimate="low",
            )

    # ── report_first: user asking for reports ──
    for qtype in ("report_request", "summary", "compare"):
        for bucket in ("small", "medium", "large", "xlarge"):
            key = f"{qtype}:{bucket}:report"
            stacks[key] = StrategyStack(
                query_type=qtype, corpus_bucket=bucket,
                primary_layers=[LAYER_PREFILTER_NONE, LAYER_RETRIEVE_REPORT, LAYER_ANALYZE_DIRECT_LLM],
                fallback_chain=["hybrid_retrieval_then_deep_read", "map_reduce_summary"],
                trigger_conditions={"report_first": True, "question_types": ["report_request", "summary"]},
                latency_estimate="fast", cost_estimate="low",
            )

    # ── map_reduce_summary: xlarge corpus or folder_summary ──
    for qtype in ("folder_summary", "open_analysis", "summary"):
        for bucket in ("xlarge",):
            key = f"{qtype}:{bucket}"
            stacks[key] = StrategyStack(
                query_type=qtype, corpus_bucket=bucket,
                primary_layers=[LAYER_PREFILTER_METADATA, LAYER_RETRIEVE_FULL_READ, LAYER_ANALYZE_MAP_REDUCE],
                fallback_chain=[],
                trigger_conditions={"corpus_buckets": ["xlarge"], "question_types": ["folder_summary", "open_analysis"]},
                latency_estimate="deep", cost_estimate="high",
            )

    # ── DEFAULT: fts_then_deep_read for everything else ──
    stacks["default"] = StrategyStack(
        query_type="any", corpus_bucket="any",
        primary_layers=[LAYER_PREFILTER_FTS, LAYER_RETRIEVE_CHUNK_TOP, LAYER_ANALYZE_DIRECT_LLM],
        fallback_chain=["hybrid_retrieval_then_deep_read", "map_reduce_summary"],
        trigger_conditions={"fallback": "default"},
        latency_estimate="balanced", cost_estimate="medium",
    )

    return stacks


def _analyze_query(query: str) -> QueryAnalysis:
    q = query.lower()
    has_time = any(kw in q for kw in ["月", "年", "季度", "202", "最近", "过去", "上个月", "上个", "本月", "今年"])
    has_cat = any(kw in q for kw in ["分类", "类别", "交易", "项目", "随笔", "AI", "工具"])

    qtype = "open_analysis"
    if any(kw in q for kw in ["找", "搜索", "查", "有没有", "在哪", "哪个文件"]):
        qtype = "finding_specific" if not any(kw in q for kw in ["分析", "总结", "趋势", "变化", "对比"]) else "keyword_search"
    elif any(kw in q for kw in ["关键词", "止损", "买入", "卖出"]):
        qtype = "keyword_search"
    elif any(kw in q for kw in ["对比", "比较", "变化", "趋势", "不同", "之前", "现在"]):
        qtype = "compare"
    elif any(kw in q for kw in ["月报", "周报", "季报", "报告", "复盘", "总结", "概括"]):
        qtype = "report_request"
    elif any(kw in q for kw in ["文件夹", "目录", "全部", "所有", "全量"]):
        qtype = "folder_summary"
    elif any(kw in q for kw in ["概括", "摘要", "总结"]):
        qtype = "summary"

    return QueryAnalysis(
        query_text=query,
        question_type=qtype,
        has_time_filter=has_time,
        has_category_filter=has_cat,
        has_explicit_terms=qtype in ("keyword_search", "finding_specific"),
        need_citation=qtype in ("open_analysis", "compare"),
        need_full_accuracy=qtype in ("open_analysis", "compare", "folder_summary"),
        estimated_results_need=5 if qtype == "finding_specific" else 20,
    )


def route_query(query: str, profile: UserKnowledgeProfile,
                component_plan: dict | None = None) -> tuple[StrategyStack, CorpusEstimate, QueryAnalysis]:
    corpus = estimate_corpus(profile)
    analysis = _analyze_query(query)
    stacks = _build_all_stacks()

    cp = component_plan or {}
    report_first = cp.get("report_first", False)
    wiki_strategy = cp.get("wiki_cache_strategy", "full_pages")

    # Layered routing: try specific combinations first, fall back to generic
    candidates = []

    # 1) report_first
    if report_first and analysis.question_type in ("report_request", "summary"):
        candidates.append(f"{analysis.question_type}:{corpus.size_bucket}:report")

    # 2) wiki_cache_first
    if wiki_strategy != "off" and analysis.question_type in ("summary",):
        candidates.append(f"{analysis.question_type}:{corpus.size_bucket}:wiki")

    # 3) filtered small
    if (analysis.has_time_filter or analysis.has_category_filter) and corpus.size_bucket in ("tiny", "small"):
        candidates.append(f"{analysis.question_type}:filtered_small")

    # 4) exact match: question_type:bucket
    candidates.append(f"{analysis.question_type}:{corpus.size_bucket}")

    # 5) generic question_type match
    for bucket in ["tiny", "small", "medium", "large", "xlarge"]:
        candidates.append(f"{analysis.question_type}:{bucket}")

    # resolve
    for key in candidates:
        if key in stacks:
            return stacks[key], corpus, analysis

    return stacks["default"], corpus, analysis


def generate_strategy_policy(profile: UserKnowledgeProfile,
                              component_plan: dict | None = None) -> StrategyPolicy:
    stacks = _build_all_stacks()
    corpus = estimate_corpus(profile)

    routing_rules: list[dict] = []
    cp = component_plan or {}

    # Ordered routing rules — first match wins
    routing_rules.append({
        "priority": 1,
        "condition": "report_first == True AND question_type in ['report_request', 'summary']",
        "stack": "report_first",
        "note": "用户已请求或系统配置了 report-first 模式",
    })
    routing_rules.append({
        "priority": 2,
        "condition": "wiki_cache_strategy != 'off' AND question_type == 'summary'",
        "stack": "wiki_cache_first",
        "note": "有 AI 维护的 wiki 缓存，概括性问题优先读缓存",
    })
    routing_rules.append({
        "priority": 3,
        "condition": f"corpus_size < 50k tokens AND question_type in ['open_analysis', 'compare']",
        "stack": "full_read_direct",
        "note": "小语料直接全量读入，不必预过滤",
    })
    routing_rules.append({
        "priority": 4,
        "condition": "has_time_filter OR has_category_filter, filtered_corpus < 80k tokens",
        "stack": "metadata_filter_then_full_read",
        "note": "有明确过滤条件且过滤后语料可控，先过滤再全量读",
    })
    routing_rules.append({
        "priority": 5,
        "condition": "question_type == 'keyword_search' OR question_type == 'finding_specific'",
        "stack": "fts_then_deep_read",
        "note": "关键词明确，FTS5 快速定位后深度读入",
    })
    routing_rules.append({
        "priority": 6,
        "condition": "corpus_size > 500k tokens OR question_type == 'folder_summary'",
        "stack": "map_reduce_summary",
        "note": "超长语料或文件夹级别总结，map-reduce 分批压缩合成",
    })
    routing_rules.append({
        "priority": 7,
        "condition": f"corpus_size > 200k tokens AND question_type == 'open_analysis'",
        "stack": "hybrid_retrieval_then_deep_read",
        "note": "大语料开放式问题，FTS5 + Agent 语义混合检索",
    })
    routing_rules.append({
        "priority": 8,
        "condition": "default",
        "stack": "fts_then_deep_read",
        "note": "默认策略：FTS5 关键词搜索 → 深度读入 → LLM 分析",
    })

    return StrategyPolicy(
        version="v1",
        default_stack="fts_then_deep_read",
        stacks=stacks,
        routing_rules=routing_rules,
    )
