from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from operator import itemgetter


@dataclass
class ScenarioResult:
    scenario_id: str
    scenario_name: str
    query: str
    strategy_used: str
    status: str  # "pass" | "partial" | "fail"
    evidence_files: list[str] = field(default_factory=list)
    answer: str = ""
    details: dict = field(default_factory=dict)
    failure_reason: str = ""


def _connect(kb_dir: str) -> sqlite3.Connection:
    db = Path(kb_dir) / "database" / "personal_kb.sqlite"
    if not db.exists():
        db = Path("kb_out/kb.sqlite3")
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    return con


def _select_strategy(query_type: str, corpus_size: int) -> str:
    """Route to the appropriate strategy based on query analysis."""
    if query_type in ("keyword_search", "finding_specific"):
        return "fts_then_deep_read"
    if corpus_size <= 30:
        return "full_read_direct"
    if query_type in ("report_request", "summary"):
        if corpus_size <= 80:
            return "full_read_direct"
        return "map_reduce_summary"
    if query_type == "compare":
        return "hybrid_retrieval_then_deep_read"
    if query_type == "open_analysis":
        return "hybrid_retrieval_then_deep_read"
    return "fts_then_deep_read"


# ── Scenario 1: 找文件 ──

def run_scenario_find_file(kb_dir: str) -> ScenarioResult:
    query = "我以前在哪写过'不要追涨'？"
    con = _connect(kb_dir)

    results = []
    try:
        # FTS5 search
        rows = con.execute(
            "SELECT c.path, c.chunk_index, c.derived_time_month, c.primary_category, "
            "snippet(document_chunks_fts, 0, '**', '**', ' ... ', 20) AS snippet, "
            "bm25(document_chunks_fts) AS score "
            "FROM document_chunks_fts "
            "JOIN document_chunks c ON c.chunk_id = document_chunks_fts.rowid "
            "WHERE document_chunks_fts MATCH ? ORDER BY score LIMIT 10",
            ("追涨",),
        ).fetchall()

        for r in rows:
            results.append({
                "filename": Path(r["path"]).name,
                "path": r["path"],
                "month": r["derived_time_month"],
                "category": r["primary_category"],
                "snippet": r["snippet"],
                "score": round(r["score"], 2) if r["score"] else 0,
            })

        # Fallback: search summary/topic_tags in documents table
        if not results:
            docs = con.execute(
                "SELECT docs_path, filename, derived_time_month, primary_category, summary "
                "FROM documents WHERE include_in_kb=1 AND summary LIKE ? LIMIT 5",
                ("%追涨%",),
            ).fetchall()
            for d in docs:
                results.append({
                    "filename": d["filename"],
                    "path": d["docs_path"],
                    "month": d["derived_time_month"],
                    "category": d["primary_category"],
                    "snippet": (d["summary"] or "")[:200],
                    "score": 0,
                })

    except Exception:
        # FTS table might not exist; fallback to LIKE search
        docs = con.execute(
            "SELECT docs_path, filename, derived_time_month, primary_category, summary "
            "FROM documents WHERE include_in_kb=1 AND (summary LIKE ? OR topic_tags LIKE ?) LIMIT 10",
            ("%追涨%", "%追涨%"),
        ).fetchall()
        for d in docs:
            results.append({
                "filename": d["filename"],
                "path": d["docs_path"],
                "month": d["derived_time_month"],
                "category": d["primary_category"],
                "snippet": (d["summary"] or "")[:200],
                "score": 0,
            })

    con.close()

    evidence = [r["path"] for r in results[:5]]
    status = "pass" if results else "fail"
    strategy = _select_strategy("finding_specific", len(results))

    return ScenarioResult(
        scenario_id="S01",
        scenario_name="找文件 — 全文检索",
        query=query,
        strategy_used=strategy,
        status=status,
        evidence_files=evidence,
        answer=_format_find_results(results),
        details={"hits": len(results), "top_hit": results[0] if results else None},
        failure_reason="" if results else "FTS5 索引中未找到'追涨'关键词匹配；可能需要检查 FTS 建库是否成功",
    )


def _format_find_results(results: list[dict]) -> str:
    if not results:
        return "未找到匹配的文件。"
    lines = [f"找到 {len(results)} 条相关记录：", ""]
    for i, r in enumerate(results[:8], 1):
        lines.append(f"**{i}. {r['filename']}**")
        lines.append(f"- 路径: {r['path']}")
        lines.append(f"- 月份: {r.get('month', '?')} | 分类: {r.get('category', '?')}")
        lines.append(f"- 命中片段: {r.get('snippet', '')}")
        lines.append(f"- 相关度: {r.get('score', 0)}")
        lines.append("")
    return "\n".join(lines)


# ── Scenario 2: 月度复盘 ──

def run_scenario_monthly_review(kb_dir: str) -> ScenarioResult:
    query = "生成 2026-03 的交易复盘月报。"
    con = _connect(kb_dir)

    # Get all March 2026 trading docs
    docs = con.execute(
        "SELECT docs_path, filename, primary_category, source_type, summary, "
        "emotion_tags, topic_tags "
        "FROM documents WHERE include_in_kb=1 AND derived_time_month='2026-03' "
        "AND (primary_category LIKE '%交易%') "
        "ORDER BY filename"
    ).fetchall()

    con.close()

    if not docs:
        return ScenarioResult(
            scenario_id="S02", scenario_name="月度复盘 — 2026-03 交易",
            query=query, strategy_used="report_first", status="fail",
            failure_reason="2026-03 月份没有交易分类的文档",
        )

    # Analyze patterns
    errors = []
    emotions = []
    rule_signals = []
    for d in docs:
        summary = (d["summary"] or "").lower()
        fn = d["filename"]
        if any(kw in summary for kw in ["错误", "失误", "不该", "后悔"]):
            errors.append(fn)
        if any(kw in summary for kw in ["止损", "仓位", "执行力", "纪律"]):
            rule_signals.append(fn)
        emotion_tags = d["emotion_tags"]
        if emotion_tags:
            try:
                tags = json.loads(emotion_tags)
                emotions.extend(tags)
            except Exception:
                pass

    from collections import Counter
    top_emotions = Counter(emotions).most_common(3)

    answer_parts = [
        f"## 2026-03 交易复盘月报",
        f"",
        f"**本月交易相关文档**: {len(docs)} 篇",
        f"",
        f"### 本月错误信号",
    ]
    if errors:
        for e in errors:
            answer_parts.append(f"- ⚠️ {e}")
    else:
        answer_parts.append("- 未检测到明确的错误信号（需要人工确认）")

    answer_parts.extend(["", "### 情绪模式"])
    if top_emotions:
        for tag, cnt in top_emotions:
            answer_parts.append(f"- {tag} (×{cnt})")
    else:
        answer_parts.append("- 无情绪标签数据")

    answer_parts.extend(["", "### 规则变化信号"])
    if rule_signals:
        for r in rule_signals:
            answer_parts.append(f"- 📋 {r}")
    else:
        answer_parts.append("- 未检测到明确的规则变化信号")

    answer_parts.extend(["", "### 下月检查清单", ""])
    checklist = [
        "检查止损纪律是否存在连续违反",
        "回顾最大亏损交易的决策过程",
        "比对月度计划与实际执行的偏差",
        "标记值得深入分析的主题",
    ]
    for c in checklist:
        answer_parts.append(f"- [ ] {c}")

    evidence = [d["docs_path"] for d in docs[:8]]

    return ScenarioResult(
        scenario_id="S02",
        scenario_name="月度复盘 — 2026-03 交易",
        query=query,
        strategy_used="report_first",
        status="pass" if docs else "fail",
        evidence_files=evidence,
        answer="\n".join(answer_parts),
        details={
            "doc_count": len(docs),
            "error_signals": len(errors),
            "emotion_tags": top_emotions,
            "rule_signals": len(rule_signals),
        },
    )


# ── Scenario 3: 项目分析 ──

def run_scenario_project_analysis(kb_dir: str) -> ScenarioResult:
    query = "我的'侦探小说 AI'项目 novelty 在哪里？"
    con = _connect(kb_dir)

    docs = con.execute(
        "SELECT docs_path, filename, primary_category, summary, topic_tags "
        "FROM documents WHERE include_in_kb=1 AND "
        "(filename LIKE '%侦探%' OR summary LIKE '%侦探%' OR topic_tags LIKE '%侦探%') "
        "ORDER BY derived_time_month"
    ).fetchall()

    con.close()

    if not docs:
        return ScenarioResult(
            scenario_id="S03", scenario_name="项目分析 — 侦探小说 AI",
            query=query, strategy_used="hybrid_retrieval_then_deep_read",
            status="fail",
            failure_reason="未找到与'侦探小说 AI'相关的文档；可能是该项目尚未被记录或分类不正确",
        )

    # Extract signals from summaries
    novelty_signals = []
    material_signals = []
    gap_signals = []
    for d in docs:
        summary = (d["summary"] or "").lower()
        fn = d["filename"]
        if any(kw in summary for kw in ["novel", "新", "原创", "独特", "不同"]):
            novelty_signals.append(fn)
        if any(kw in summary for kw in ["对话", "实验", "素材", "材料"]):
            material_signals.append(fn)
        if any(kw in summary for kw in ["缺", "不够", "不足", "需要", "缺少"]):
            gap_signals.append(fn)

    one_liner = "AI 辅助创作的侦探小说生成/分析系统，聚焦叙事结构与推理逻辑的交互"
    if docs:
        first_summary = docs[0]["summary"] or ""
        if len(first_summary) > 20:
            one_liner = f"基于现有文档推断：{first_summary[:120]}..."

    answer = "\n".join([
        f"## 项目: 侦探小说 AI",
        f"",
        f"**一句话定义**: {one_liner}",
        f"",
        f"### Novelty（创新点）",
        f"- **相关文档**: {len(docs)} 篇",
        f"- **新颖信号**: {', '.join(novelty_signals) if novelty_signals else '需要深入阅读确认'}",
        f"",
        f"### 已有材料",
    ] + [f"- {d['filename']} ({d['primary_category']})" for d in docs] + [
        f"",
        f"### 缺口",
        f"- {'; '.join(gap_signals) if gap_signals else '未检测到明确缺口——建议深入阅读项目文件后补充'}",
        f"",
        f"### 证据文件",
    ] + [f"- `{d['docs_path']}`" for d in docs])

    return ScenarioResult(
        scenario_id="S03",
        scenario_name="项目分析 — 侦探小说 AI",
        query=query,
        strategy_used="hybrid_retrieval_then_deep_read",
        status="pass" if docs else "fail",
        evidence_files=[d["docs_path"] for d in docs],
        answer=answer,
        details={
            "related_docs": len(docs),
            "novelty_signals": novelty_signals,
            "material_signals": material_signals,
            "gap_signals": gap_signals,
        },
    )


# ── Scenario 4: 写作素材 ──

def run_scenario_writing_candidates(kb_dir: str) -> ScenarioResult:
    query = "哪些内容可以发展成文章？"
    con = _connect(kb_dir)

    docs = con.execute(
        "SELECT docs_path, filename, primary_category, summary, topic_tags, writing_potential "
        "FROM documents WHERE include_in_kb=1 AND summary IS NOT NULL "
        "ORDER BY confidence DESC LIMIT 80"
    ).fetchall()

    con.close()

    candidates = []
    for d in docs:
        summary = (d["summary"] or "").lower()
        tags = d["topic_tags"] or ""
        fn = d["filename"]

        score = 0
        angles = []
        if any(kw in summary for kw in ["反思", "复盘", "错误", "教训", "经验"]):
            score += 3
            angles.append("经验教训")
        if any(kw in summary for kw in ["系统", "方法", "策略", "规则"]):
            score += 3
            angles.append("方法论")
        if any(kw in summary for kw in ["情绪", "心态", "心理"]):
            score += 2
            angles.append("心理观察")
        if any(kw in summary for kw in ["ai", "工具", "自动化", "prompt"]):
            score += 3
            angles.append("AI/工具")
        if any(kw in summary for kw in ["变化", "演化", "趋势"]):
            score += 2
            angles.append("趋势分析")
        if len(summary) > 200:
            score += 1

        if score >= 3:
            candidates.append({
                "filename": fn,
                "path": d["docs_path"],
                "category": d["primary_category"],
                "angles": angles,
                "score": score,
                "suggested_title": _suggest_title(fn, angles),
            })

    candidates.sort(key=itemgetter("score"), reverse=True)
    top = candidates[:10]

    answer = "\n".join([
        f"## 写作候选 ({len(candidates)} 个中取 Top {len(top)})",
        "",
        "| # | 候选主题 | 分类 | 角度 | 推荐标题 |",
        "|---|---------|------|------|---------|",
    ] + [
        f"| {i} | {c['filename'][:40]} | {c['category']} | {', '.join(c['angles'][:2])} | {c['suggested_title']} |"
        for i, c in enumerate(top, 1)
    ] + [
        "",
        "### 写作角度分布",
    ])
    angle_counts: dict[str, int] = {}
    for c in candidates:
        for a in c["angles"]:
            angle_counts[a] = angle_counts.get(a, 0) + 1
    for a, cnt in sorted(angle_counts.items(), key=lambda x: -x[1]):
        answer += f"\n- **{a}**: {cnt} 篇"

    return ScenarioResult(
        scenario_id="S04",
        scenario_name="写作素材 — 文章候选",
        query=query,
        strategy_used="map_reduce_summary",
        status="pass" if candidates else "fail",
        evidence_files=[c["path"] for c in top[:5]],
        answer=answer,
        details={
            "total_candidates": len(candidates),
            "top_score": top[0]["score"] if top else 0,
            "angle_distribution": angle_counts,
        },
    )


def _suggest_title(filename: str, angles: list[str]) -> str:
    base = filename.rsplit(".", 1)[0][:30]
    if "方法论" in angles or "系统" in str(angles):
        return f"【方法论】从{base}看交易系统的进化"
    if "经验教训" in angles:
        return f"【复盘记录】{base}及其教训"
    if "AI" in str(angles):
        return f"【工具思考】{base}——AI 如何改变我的工作流"
    if "心理" in str(angles):
        return f"【自我观察】{base}——交易中的情绪管理"
    return f"【随笔】{base}"


# ── Scenario 5: 自我画像 ──

def run_scenario_self_profile(kb_dir: str) -> ScenarioResult:
    query = "过去半年我的交易和自我认知有什么变化？"
    con = _connect(kb_dir)

    # Get docs from last 6 months (2024-12 to 2026-05 approximately)
    docs = con.execute(
        "SELECT docs_path, filename, primary_category, derived_time_month, source_type, "
        "summary, emotion_tags, cognition_dimensions, topic_tags "
        "FROM documents WHERE include_in_kb=1 AND derived_time_month >= '2025-11' "
        "ORDER BY derived_time_month"
    ).fetchall()

    con.close()

    if not docs:
        return ScenarioResult(
            scenario_id="S05", scenario_name="自我画像 — 半年认知变化",
            query=query, strategy_used="hybrid_retrieval_then_deep_read",
            status="fail",
            failure_reason="过去半年（2025-11+）没有足够的文档数据",
        )

    # Build timeline
    by_month: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        by_month[d["derived_time_month"] or "unknown"].append(d)

    # Track recurring themes
    all_tags: list[str] = []
    for d in docs:
        tags = d["topic_tags"]
        if tags:
            try:
                all_tags.extend(json.loads(tags))
            except Exception:
                pass

    from collections import Counter
    recurring = Counter(all_tags).most_common(5)

    # Detect changes: compare early months vs recent
    months_sorted = sorted(by_month.keys())
    early = months_sorted[:3] if len(months_sorted) >= 3 else months_sorted[:1]
    recent = months_sorted[-2:] if len(months_sorted) >= 2 else months_sorted[-1:]

    early_docs = [d for m in early for d in by_month.get(m, [])]
    recent_docs = [d for m in (recent if isinstance(recent, list) else [recent]) for d in by_month.get(m, [])]

    early_cats = Counter(d["primary_category"] for d in early_docs)
    recent_cats = Counter(d["primary_category"] for d in recent_docs)

    cat_shifts = []
    for cat in set(list(early_cats.keys()) + list(recent_cats.keys())):
        e = early_cats.get(cat, 0)
        r = recent_cats.get(cat, 0)
        if e != r:
            direction = "↑" if r > e else "↓"
            cat_shifts.append(f"{cat}: {e}→{r} {direction}")

    answer = "\n".join([
        f"## 过去半年（2025-11 ~ 2026-05）交易与自我认知变化",
        f"",
        f"### 时间线",
        f"- 覆盖月份: {', '.join(months_sorted)}",
        f"- 总文档数: {len(docs)}",
        f"",
        f"### 关注变化",
    ] + [f"- {s}" for s in cat_shifts] + [
        f"",
        f"### 反复出现的问题",
    ] + [f"- {tag} (×{cnt})" for tag, cnt in recurring] + [
        f"",
        f"### 旧认知 vs 新认知",
        f"",
        f"**早期阶段** ({', '.join(early) if isinstance(early, list) else early}):",
    ])

    early_themes = Counter(d["primary_category"] for d in early_docs)
    for cat, cnt in early_themes.most_common(3):
        answer += f"\n- 重点关注 **{cat}** ({cnt} 篇)"

    answer += f"\n\n**近期阶段** ({', '.join(recent) if isinstance(recent, list) else recent}):"
    recent_themes = Counter(d["primary_category"] for d in recent_docs)
    for cat, cnt in recent_themes.most_common(3):
        answer += f"\n- 重点关注 **{cat}** ({cnt} 篇)"

    answer += "\n\n### 证据文件\n"
    for d in docs[:10]:
        answer += f"\n- `{d['docs_path']}`"

    return ScenarioResult(
        scenario_id="S05",
        scenario_name="自我画像 — 半年认知变化",
        query=query,
        strategy_used="hybrid_retrieval_then_deep_read",
        status="pass" if docs else "fail",
        evidence_files=[d["docs_path"] for d in docs[:10]],
        answer=answer,
        details={
            "months_covered": len(months_sorted),
            "total_docs": len(docs),
            "recurring_themes": recurring,
            "category_shifts": cat_shifts,
        },
    )


# ── Runner ──

def run_all_scenarios(kb_dir: str) -> list[ScenarioResult]:
    return [
        run_scenario_find_file(kb_dir),
        run_scenario_monthly_review(kb_dir),
        run_scenario_project_analysis(kb_dir),
        run_scenario_writing_candidates(kb_dir),
        run_scenario_self_profile(kb_dir),
    ]
