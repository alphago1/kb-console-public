from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class CorpusEstimate(BaseModel):
    total_files: int = 0
    total_chars_no_ws: int = 0
    token_estimate_low: int = 0
    token_estimate_high: int = 0
    primary_format: str = "unknown"
    domain_count: int = 1
    month_span: int = 1
    # bucket for routing
    size_bucket: str = "unknown"  # "tiny" | "small" | "medium" | "large" | "xlarge"


class QueryAnalysis(BaseModel):
    query_text: str
    question_type: str = "open_analysis"
    # "keyword_search" | "open_analysis" | "compare" | "summary" |
    # "folder_summary" | "finding_specific" | "report_request"
    has_time_filter: bool = False
    has_category_filter: bool = False
    has_explicit_terms: bool = False
    need_citation: bool = False
    need_full_accuracy: bool = False
    estimated_results_need: int = 10


class StrategyLayer(BaseModel):
    """One layer in a layered strategy stack. Not a binary choice — layers compose."""
    layer: int  # 1=prefilter, 2=retrieval, 3=analysis
    strategy_name: str
    description: str
    parameters: dict = Field(default_factory=dict)


class StrategyStack(BaseModel):
    """Complete layered strategy for answering a query."""
    query_type: str
    corpus_bucket: str
    primary_layers: list[StrategyLayer] = Field(default_factory=list)
    fallback_chain: list[str] = Field(default_factory=list)
    # when to trigger this stack
    trigger_conditions: dict = Field(default_factory=dict)
    latency_estimate: str = "unknown"  # "fast" | "balanced" | "deep"
    cost_estimate: str = "unknown"  # "low" | "medium" | "high"


class StrategyPolicy(BaseModel):
    """Complete query strategy policy — maps all query×corpus combinations to strategy stacks."""
    version: str = "v1"
    default_stack: str = "fts_then_deep_read"
    stacks: dict[str, StrategyStack] = Field(default_factory=dict)
    # key = "question_type:corpus_bucket" e.g. "open_analysis:large"
    routing_rules: list[dict] = Field(default_factory=list)
    # ordered list of routing rules, first match wins
