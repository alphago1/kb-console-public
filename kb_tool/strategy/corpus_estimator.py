from __future__ import annotations

from diagnosis.schemas import UserKnowledgeProfile
from .strategy_schemas import CorpusEstimate


def estimate_corpus(profile: UserKnowledgeProfile) -> CorpusEstimate:
    scale = profile.corpus_scale_estimate or {}
    source_types = profile.source_file_types or []
    domains = profile.core_domains or []

    total_files = _estimate_file_count(scale, source_types)
    total_chars = _estimate_chars(total_files, source_types)
    t_low, t_high = _estimate_tokens(total_chars)

    bucket = _bucket(t_high)

    return CorpusEstimate(
        total_files=total_files,
        total_chars_no_ws=total_chars,
        token_estimate_low=t_low,
        token_estimate_high=t_high,
        primary_format=_primary_format(source_types),
        domain_count=max(1, len(domains)),
        month_span=_estimate_month_span(profile),
        size_bucket=bucket,
    )


def _estimate_file_count(scale: dict, source_types: list) -> int:
    raw = str(scale).lower()
    if "几十" in raw or "<100" in raw or "< 100" in raw:
        return 60
    if "几百" in raw or "100-500" in raw or "100" in raw:
        return 300
    if "千" in raw or "500-2000" in raw or "2000" in raw:
        return 800
    if "万" in raw or ">2000" in raw or "> 2000" in raw:
        return 3000
    if "很多" in raw:
        return 2000
    return 200


def _estimate_chars(file_count: int, source_types: list) -> int:
    avg_chars_per_file = 3000
    if any("docx" in str(t).lower() or "word" in str(t).lower() for t in source_types):
        avg_chars_per_file = 5000
    if any("md" in str(t).lower() for t in source_types):
        avg_chars_per_file = max(avg_chars_per_file, 2500)
    return file_count * avg_chars_per_file


def _estimate_tokens(chars_no_ws: int) -> tuple[int, int]:
    if chars_no_ws <= 0:
        return 0, 0
    return max(1, int(chars_no_ws / 2.2)), max(1, int(chars_no_ws / 1.2))


def _bucket(token_high: int) -> str:
    if token_high <= 50_000:
        return "tiny"
    if token_high <= 200_000:
        return "small"
    if token_high <= 800_000:
        return "medium"
    if token_high <= 2_000_000:
        return "large"
    return "xlarge"


def _primary_format(source_types: list) -> str:
    st = " ".join(str(t).lower() for t in source_types)
    if "docx" in st or "word" in st:
        return "docx"
    if "md" in st or "markdown" in st:
        return "md"
    if "txt" in st:
        return "txt"
    return "unknown"


def _estimate_month_span(profile: UserKnowledgeProfile) -> int:
    return 12
