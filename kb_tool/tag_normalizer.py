from __future__ import annotations

import json
import sqlite3
from typing import Iterable


_EMOTION_CANONICAL = {
    "后悔": "后悔",
    "自责": "后悔",
    "懊悔": "后悔",
    "regret": "后悔",
    "remorse": "后悔",
    "贪婪": "贪婪",
    "贪欲": "贪婪",
    "greed": "贪婪",
    "焦虑": "焦虑",
    "anxiety": "焦虑",
    "恐惧": "恐惧",
    "fear": "恐惧",
    "冲动": "冲动",
    "impulsive": "冲动",
    "自信": "自信",
    "confidence": "自信",
    "平静": "平静",
    "calm": "平静",
    "沮丧": "沮丧",
    "frustrated": "沮丧",
}

_TOPIC_CANONICAL = {
    "rag": "检索增强生成",
    "检索增强生成": "检索增强生成",
    "retrieval augmented generation": "检索增强生成",
    "ai": "大模型",
    "llm": "大模型",
    "大模型": "大模型",
    "人工智能": "大模型",
    "agent": "智能体",
    "智能体": "智能体",
    "trade": "交易",
    "trading": "交易",
}


def _clean(tag: str) -> str:
    return (tag or "").strip()


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def normalize_emotion_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    for t in tags:
        raw = _clean(t)
        if not raw:
            continue
        key = raw.lower()
        out.append(_EMOTION_CANONICAL.get(key, _EMOTION_CANONICAL.get(raw, raw)))
    return _dedupe_keep_order(out)


def normalize_topic_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    for t in tags:
        raw = _clean(t)
        if not raw:
            continue
        key = raw.lower()
        out.append(_TOPIC_CANONICAL.get(key, _TOPIC_CANONICAL.get(raw, raw)))
    return _dedupe_keep_order(out)


def normalize_tags_in_db(sqlite_path: str) -> dict:
    updated = 0
    with sqlite3.connect(sqlite_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT path, emotion_tags, topic_tags FROM documents").fetchall()
        for r in rows:
            changed = False
            emo_json = r["emotion_tags"]
            top_json = r["topic_tags"]

            new_emo_json = emo_json
            new_top_json = top_json

            if emo_json:
                try:
                    emo = json.loads(emo_json)
                    emo2 = normalize_emotion_tags(emo)
                    new_emo_json = json.dumps(emo2, ensure_ascii=False)
                    if new_emo_json != emo_json:
                        changed = True
                except Exception:
                    pass

            if top_json:
                try:
                    top = json.loads(top_json)
                    top2 = normalize_topic_tags(top)
                    new_top_json = json.dumps(top2, ensure_ascii=False)
                    if new_top_json != top_json:
                        changed = True
                except Exception:
                    pass

            if changed:
                con.execute(
                    "UPDATE documents SET emotion_tags=?, topic_tags=?, processed_at=datetime('now') WHERE path=?",
                    (new_emo_json, new_top_json, r["path"]),
                )
                updated += 1
        con.commit()
    return {"updated": updated}
