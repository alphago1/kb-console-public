from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


class FileRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    filename: str
    extension: str
    size_bytes: int

    filesystem_created_time: Optional[datetime] = None
    filesystem_modified_time: Optional[datetime] = None

    document_created_time: Optional[datetime] = None
    document_modified_time: Optional[datetime] = None

    derived_time_month: Optional[str] = None
    time_source: Optional[str] = None


class SamplingResult(BaseModel):
    sampled_text: str
    sampled_char_count: int
    keyword_contexts: int = 0


class LLMResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    include_in_kb: bool
    exclude_reason: Optional[str] = None

    primary_category: str
    secondary_category: Optional[str] = None
    topic_tags: list[str] = Field(default_factory=list)
    source_type: str

    time_year: Optional[int] = None
    time_month: Optional[str] = None

    emotion_tags: list[str] = Field(default_factory=list)
    cognition_dimensions: list[str] = Field(default_factory=list)

    contains_trade_data: bool = False
    contains_reflection: bool = False
    contains_cognition_change: bool = False
    contains_project_idea: bool = False
    contains_writing_potential: bool = False

    # deepseek_prompt.txt includes this field
    contains_emotion: Optional[bool] = None

    writing_potential: Optional[str] = None

    summary: Optional[str] = None
    cognition_snapshot: Optional[dict[str, Any]] = None

    confidence: float = 0.0
    needs_more_text: bool = False
    needs_review: bool = False

    recurrence_signal: Optional[bool] = None
    reason: Optional[str] = None
