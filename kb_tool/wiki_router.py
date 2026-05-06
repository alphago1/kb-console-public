from __future__ import annotations

import json, re
from pathlib import Path
from typing import Any


def load_page_index(kb_dir: str) -> list[dict]:
    for candidate in [Path(kb_dir)/"wiki"/"page_index.json", Path(kb_dir)/"page_index.json"]:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return []


def route_query(query: str, kb_dir: str) -> dict[str, Any]:
    pages = load_page_index(kb_dir)
    if not pages:
        return {"selected_pages": [], "confidence": 0.0, "fallback_needed": True,
                "fallback_reason": "wiki_pages_not_built", "matches": [], "strategy": "fallback_fts"}

    ql = query.lower()
    qt = set(re.findall(r"[一-鿿]+|[a-z0-9]+", ql))
    matches: list[dict] = []

    for p in pages:
        score = 0.0; reasons = []
        title = (p.get("title","") or "").lower()
        cat = (p.get("category","") or "").lower()
        tt = set(re.findall(r"[一-鿿]+|[a-z0-9]+", title))

        if ql in title: score += 25; reasons.append("标题完整匹配")
        overlap = qt & tt
        if overlap: score += len(overlap) * 10; reasons.append(f"标题匹配: {','.join(overlap)}")
        for t in qt:
            if len(t) >= 2 and t in cat: score += 3; reasons.append(f"分类含'{t}'")
        if score > 0:
            matches.append({"title": p["title"], "type": p.get("type",""), "category": p.get("category",""),
                            "doc_count": p.get("doc_count",0), "path": p.get("path",""), "score": round(score,1),
                            "match_reasons": reasons})

    matches.sort(key=lambda x: -x["score"])
    if not matches:
        return {"selected_pages": [], "confidence": 0.0, "fallback_needed": True,
                "fallback_reason": f"未匹配任何 wiki 页面", "matches": [], "strategy": "fallback_fts"}

    top = matches[0]["score"]
    top_pages = [m for m in matches if m["score"] >= max(top * 0.5, 5)]

    if top >= 30: conf, fb, reason, strat = 0.9, False, "", "wiki_first"
    elif top >= 15: conf, fb, reason, strat = 0.7, False, "", "wiki_first"
    elif top >= 5: conf, fb, reason, strat = 0.5, True, "置信度中等，建议并用 FTS", "wiki_plus_fts"
    else: conf, fb, reason, strat = 0.3, True, "置信度低，建议用 FTS", "fallback_fts"

    return {"selected_pages": [m["path"] for m in top_pages[:5]], "confidence": conf,
            "fallback_needed": fb, "fallback_reason": reason, "matches": matches[:10], "strategy": strat}
