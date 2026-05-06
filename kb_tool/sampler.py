from __future__ import annotations

import hashlib
import random
import re
from typing import Iterable

from models import SamplingResult


def _stable_rng(seed_text: str) -> random.Random:
    h = hashlib.sha256(seed_text.encode("utf-8", errors="ignore")).hexdigest()
    seed = int(h[:16], 16)
    return random.Random(seed)


def _slice_safe(text: str, start: int, length: int) -> str:
    start = max(0, min(len(text), start))
    end = max(0, min(len(text), start + length))
    return text[start:end]


def _keyword_contexts(text: str, keywords: list[str], window: int, max_contexts: int) -> list[str]:
    contexts: list[str] = []
    if not text or not keywords:
        return contexts

    # build one regex
    escaped = [re.escape(k) for k in keywords if k]
    if not escaped:
        return contexts
    pat = re.compile("|".join(escaped))

    for m in pat.finditer(text):
        if len(contexts) >= max_contexts:
            break
        s = max(0, m.start() - window)
        e = min(len(text), m.end() + window)
        snippet = text[s:e].strip()
        if snippet and snippet not in contexts:
            contexts.append(snippet)
    return contexts


def sample_text(cfg: dict, full_text: str, seed: str, deep: bool = False) -> SamplingResult:
    sp = cfg["sampler"]

    if not full_text:
        return SamplingResult(sampled_text="", sampled_char_count=0, keyword_contexts=0)

    if not deep:
        head_n = int(sp.get("head_chars", 1000))
        mid_n = int(sp.get("mid_chars", 1000))
        tail_n = int(sp.get("tail_chars", 1000))
        rand_k = int(sp.get("random_segments", 3))
        rand_n = int(sp.get("random_segment_chars", 500))
        max_contexts = int(sp.get("max_keyword_contexts", 12))
    else:
        # deep mode: prefer more continuous coverage, cap by deep_read_max_chars
        deep_max = int(sp.get("deep_read_max_chars", 12000))
        head_n = min(4000, deep_max)
        tail_n = min(4000, max(0, deep_max - head_n))
        mid_n = min(4000, max(0, deep_max - head_n - tail_n))
        rand_k = 0
        rand_n = 0
        max_contexts = 20

    window = int(sp.get("keyword_context_window", 200))

    keywords = []
    for group in (sp.get("keywords", {}) or {}).values():
        keywords.extend(list(group))

    parts: list[str] = []
    text = full_text

    if len(text) <= head_n + mid_n + tail_n + 200:
        parts.append(text)
    else:
        parts.append("==HEAD==\n" + _slice_safe(text, 0, head_n))
        mid_start = max(0, (len(text) // 2) - (mid_n // 2))
        parts.append("==MID==\n" + _slice_safe(text, mid_start, mid_n))
        parts.append("==TAIL==\n" + _slice_safe(text, len(text) - tail_n, tail_n))

    if rand_k > 0 and rand_n > 0 and len(text) > rand_n:
        rng = _stable_rng(seed)
        parts.append("==RANDOM==")
        for i in range(rand_k):
            start = rng.randint(0, max(0, len(text) - rand_n))
            parts.append(_slice_safe(text, start, rand_n))

    ctxs = _keyword_contexts(text, keywords, window=window, max_contexts=max_contexts)
    if ctxs:
        parts.append("==KEYWORDS==")
        parts.extend(ctxs)

    sampled = "\n\n".join([p for p in parts if p and p.strip()])
    return SamplingResult(sampled_text=sampled, sampled_char_count=len(sampled), keyword_contexts=len(ctxs))
