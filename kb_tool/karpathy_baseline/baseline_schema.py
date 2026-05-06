from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class BaselineComponent(BaseModel):
    component_id: str
    layer: str  # "raw_sources" | "wiki_layer" | "index_log" | "schema_rules" | "lint"
    name: str
    description: str
    default_policy: str
    human_facing: bool = True
    ai_facing: bool = True


class AdaptationDecision(BaseModel):
    component_id: str
    action: str  # "KEEP" | "DOWNGRADE" | "REPLACE" | "ENHANCE" | "DISABLE"
    reason: str
    original_policy: str
    adapted_policy: str
    profile_signals_used: list[str] = Field(default_factory=list)


class AdaptationDiff(BaseModel):
    baseline_version: str = "karpathy-v1"
    profile_session: str = ""
    summary: str = ""
    decisions: list[AdaptationDecision] = Field(default_factory=list)
    keep_count: int = 0
    downgrade_count: int = 0
    replace_count: int = 0
    enhance_count: int = 0
    disable_count: int = 0

    def compute_counts(self) -> None:
        self.keep_count = sum(1 for d in self.decisions if d.action == "KEEP")
        self.downgrade_count = sum(1 for d in self.decisions if d.action == "DOWNGRADE")
        self.replace_count = sum(1 for d in self.decisions if d.action == "REPLACE")
        self.enhance_count = sum(1 for d in self.decisions if d.action == "ENHANCE")
        self.disable_count = sum(1 for d in self.decisions if d.action == "DISABLE")


class AdaptedBlueprint(BaseModel):
    version: str = "adapted-v1"
    profile_session: str = ""
    baseline_used: str = "karpathy-v1"
    summary_narrative: str = ""
    enabled_components: list[BaselineComponent] = Field(default_factory=list)
    downgraded_components: list[BaselineComponent] = Field(default_factory=list)
    replaced_components: list[dict] = Field(default_factory=list)
    enhanced_components: list[dict] = Field(default_factory=list)
    disabled_components: list[str] = Field(default_factory=list)
    word_compatibility_notes: list[str] = Field(default_factory=list)
    entry_point: str = "wiki"  # "wiki" | "reports" | "search"
    human_index_strategy: str = "full_index_md"  # "full_index_md" | "ai_only_json" | "none"
    log_strategy: str = "human_readable_md"  # "human_readable_md" | "jsonl_only" | "none"
    wiki_cache_strategy: str = "full_pages"  # "full_pages" | "compact_cache" | "off"
    report_first: bool = False
    word_first: bool = False
