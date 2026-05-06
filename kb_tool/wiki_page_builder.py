from __future__ import annotations

import json, os, sqlite3, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml


WIKI_PAGE_PROMPT = """你是一个个人知识库 Wiki 页面生成器。系统会先列出所有证据文件（含编号），然后请你基于这些材料合成一个结构化的 Wiki 页面。

## 约束
1. 引用证据文件时使用编号 `[source: #1]`、`[source: #2]` 等，对应下方系统提供的文件编号。
2. 不得编造不在给定材料中的内容。证据不足时在 confidence 标 low。
3. 用中文输出，内容不要省略，完整写出。

## 输出结构

--- (YAML frontmatter)
title: {主题名}
type: {页面类型}
category: {分类名}
doc_count: {文档数}
generated_at: {时间}
confidence: high
---

## 定义
1-2 句话。

## 关键观点
- 观点一 [source: #1]
- 观点二 [source: #2]

## 演化时间线
| 月份 | 关键变化 |
|------|---------|

## 开放问题
- 问题描述

---
系统提供的证据文件如下："""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _group_by_category(db_path: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT docs_path, filename, derived_time_month, primary_category, "
            "source_type, topic_tags, summary, confidence "
            "FROM documents WHERE include_in_kb=1 AND summary IS NOT NULL "
            "ORDER BY derived_time_month"
        ).fetchall()
    for r in rows:
        cat = r["primary_category"] or "未分类"
        groups[cat].append(dict(r))
    return groups


def _group_by_tags(db_path: str, min_freq: int = 2) -> dict[str, list[dict]]:
    doc_tags: list[tuple[dict, list[str]]] = []
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT docs_path, filename, derived_time_month, primary_category, "
            "source_type, topic_tags, summary "
            "FROM documents WHERE include_in_kb=1 AND topic_tags IS NOT NULL "
            "ORDER BY derived_time_month"
        ).fetchall()
    tag_counter: Counter = Counter()
    for r in rows:
        try:
            tags = json.loads(r["topic_tags"])
        except Exception:
            tags = []
        if isinstance(tags, list):
            tag_counter.update(tags)
            doc_tags.append((dict(r), tags))
    frequent = {t for t, c in tag_counter.most_common(30) if c >= min_freq}
    groups: dict[str, list[dict]] = defaultdict(list)
    for doc, tags in doc_tags:
        for t in tags:
            if t in frequent:
                groups[t].append(doc)
    return {k: v for k, v in groups.items() if len(v) >= min_freq}


def _get_chunks(db_path: str, doc_path: str, max_chunks: int = 3) -> list[dict]:
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT chunk_index, chunk_text FROM document_chunks "
            "WHERE path=? ORDER BY chunk_index LIMIT ?", (doc_path, max_chunks)
        ).fetchall()
    return [dict(r) for r in rows]


def _call_llm(title: str, page_type: str, category: str, docs: list[dict], db_path: str) -> dict:
    # Build clean numbered source list
    source_ids = [d["docs_path"] for d in docs]
    source_lines = []
    for i, d in enumerate(docs, 1):
        source_lines.append(f"**[#{i}]** {d['filename']}")
        source_lines.append(f"  分类: {d.get('primary_category','')} | 月份: {d.get('derived_time_month','')}")
        source_lines.append(f"  摘要: {d.get('summary','')}")
        source_lines.append("")

    prompt = WIKI_PAGE_PROMPT.replace("{主题名}", title).replace("{页面类型}", page_type).replace("{分类名}", category).replace("{文档数}", str(len(docs))).replace("{时间}", _now())
    prompt += "\n".join(source_lines)

    from llm_providers.deepseek_provider import DeepSeekProvider
    try:
        provider = DeepSeekProvider(model="deepseek-v4-flash")
        content = provider.chat([{"role": "user", "content": prompt}], temperature=0.3)
    except Exception as e:
        return {"error": str(e), "raw": prompt[:500]}

    parsed = _parse_frontmatter(content)
    parsed["title"] = title
    parsed["type"] = page_type
    parsed["category"] = category
    parsed.setdefault("generated_at", _now())
    parsed.setdefault("doc_count", len(docs))
    parsed.setdefault("confidence", "high" if len(docs) >= 3 else "medium")
    parsed.setdefault("open_questions", 0)

    # Append source file list after the body
    body = parsed.pop("body", parsed.pop("raw", ""))
    evidence = "\n\n## 证据文件\n\n"
    for i, d in enumerate(docs[:15], 1):
        month = d.get("derived_time_month", "")
        fn = d["filename"]
        evidence += f"- **[#{i}]** `{d['docs_path']}` ({month}) — {fn}\n"
    parsed["body"] = body + evidence
    parsed["source_ids"] = source_ids[:20]
    return parsed


def _parse_frontmatter(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                fm = {}
            fm["body"] = parts[2].strip()
            fm["raw"] = text
            return fm
    return {"body": text, "raw": text}


def _write_page(page: dict, out_dir: Path, page_type: str) -> Path:
    slug = page.get("title", "untitled").replace("/", "-").replace(" ", "_")[:64]
    path = out_dir / "pages" / page_type / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = page.pop("body", page.pop("raw", ""))
    page.pop("raw", None); page.pop("error", None)
    lines = ["---"]
    for k, v in page.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v: lines.append(f"  - {item}")
        elif isinstance(v, dict):
            lines.append(f"{k}:")
            for dk, dv in v.items(): lines.append(f"  {dk}: {dv}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---"); lines.append(""); lines.append(body)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_wiki_pages(db_path: str, output_dir: str, types=None, max_per_type: int = 30) -> dict:
    if types is None:
        types = ["category", "topic"]
    out = Path(output_dir) / "wiki"
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"pages": {}, "index": "", "errors": []}
    all_pages: list[dict] = []

    if "category" in types:
        for cat, docs in list(_group_by_category(db_path).items())[:max_per_type]:
            if len(docs) < 2: continue
            try:
                page = _call_llm(cat, "category", cat, docs, db_path)
                if "error" in page:
                    results["errors"].append(f"category/{cat}: {page['error']}"); continue
                p = _write_page(page, out, "category")
                results["pages"][f"category/{cat}"] = str(p)
                all_pages.append({"title": cat, "type": "category", "path": str(p.resolve()), "doc_count": len(docs), "category": cat})
            except Exception as e:
                results["errors"].append(f"category/{cat}: {e}")

    if "topic" in types:
        for topic, docs in list(_group_by_tags(db_path).items())[:max_per_type]:
            if len(docs) < 2: continue
            try:
                page = _call_llm(topic, "topic", docs[0].get("primary_category",""), docs, db_path)
                if "error" in page:
                    results["errors"].append(f"topic/{topic}: {page['error']}"); continue
                p = _write_page(page, out, "topic")
                results["pages"][f"topic/{topic}"] = str(p)
                all_pages.append({"title": topic, "type": "topic", "path": str(p.resolve()), "doc_count": len(docs), "category": docs[0].get("primary_category","")})
            except Exception as e:
                results["errors"].append(f"topic/{topic}: {e}")

    # index.md
    by_type: dict[str, list[dict]] = defaultdict(list)
    for p in all_pages: by_type[p["type"]].append(p)
    lines = ["# Wiki 索引", "", f"> 生成时间: {_ts()}", f"> 页面数: {len(all_pages)}", ""]
    for pt, label in [("category","分类页面"), ("topic","主题页面"), ("project","项目页面")]:
        pages = by_type.get(pt, [])
        if not pages: continue
        lines.append(f"## {label} ({len(pages)})")
        for p in sorted(pages, key=lambda x: -x.get("doc_count",0)):
            lines.append(f"- **[{p['title']}](pages/{pt}/{p['title']}.md)** — {p.get('doc_count',0)} 篇")
        lines.append("")
    (out/"index.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    results["index"] = str(out/"index.md")

    # page_index.json
    (out/"page_index.json").write_text(json.dumps(all_pages, ensure_ascii=False, indent=2), encoding="utf-8")
    results["page_index"] = str(out/"page_index.json")

    # cross_refs.json
    cr: dict[str, list[str]] = defaultdict(list)
    for p in all_pages:
        for o in all_pages:
            if o["title"] != p["title"] and o.get("category") == p.get("category"):
                cr[p["title"]].append(o["title"])
    (out/"cross_refs.json").write_text(json.dumps(cr, ensure_ascii=False, indent=2), encoding="utf-8")
    results["cross_refs"] = str(out/"cross_refs.json")

    # build_log.jsonl
    with open(out/"build_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts":_now(), "pages":len(all_pages), "errors":len(results["errors"])}, ensure_ascii=False)+"\n")
    results["build_log"] = str(out/"build_log.jsonl")
    return results
