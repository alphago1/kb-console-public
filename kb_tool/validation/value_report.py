from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .scenario_tests import ScenarioResult


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_scenario_results_md(results: list[ScenarioResult], output_dir: str) -> str:
    """Generate detailed scenario-by-scenario results."""
    lines = [
        "# Scenario Validation Results",
        f"> 时间: {_ts()}",
        f"> 场景数: {len(results)}",
        f"> 通过: {sum(1 for r in results if r.status == 'pass')}",
        f"> 部分: {sum(1 for r in results if r.status == 'partial')}",
        f"> 失败: {sum(1 for r in results if r.status == 'fail')}",
        "",
        "---",
        "",
    ]

    for r in results:
        status_icon = {"pass": "✅", "partial": "⚠️", "fail": "❌"}.get(r.status, "?")
        lines.extend([
            f"## {status_icon} {r.scenario_name} [{r.scenario_id}]",
            "",
            f"- **查询**: {r.query}",
            f"- **策略**: `{r.strategy_used}`",
            f"- **状态**: {r.status}",
            "",
            "### 回答",
            "",
            r.answer,
            "",
            "### 证据文件",
            "",
        ])
        for i, ef in enumerate(r.evidence_files[:8], 1):
            lines.append(f"{i}. `{ef}`")

        if r.failure_reason:
            lines.extend(["", "### 失败原因", "", r.failure_reason])

        lines.extend(["", "### 数据细节", "", "```json", str(r.details), "```", "", "---", ""])

    path = Path(output_dir) / "scenario_results.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.resolve())


def generate_scenario_failures_md(results: list[ScenarioResult], output_dir: str) -> str:
    """Generate failure analysis for failed/partial scenarios."""
    failures = [r for r in results if r.status in ("fail", "partial")]
    lines = [
        "# Scenario Failure Analysis",
        f"> 时间: {_ts()}",
        f"> 失败/部分场景: {len(failures)}",
        "",
        "---",
        "",
    ]

    if not failures:
        lines.append("✅ 所有场景均通过！")
        path = Path(output_dir) / "scenario_failures.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path.resolve())

    for r in failures:
        lines.extend([
            f"## ❌ {r.scenario_name} [{r.scenario_id}]",
            "",
            f"**查询**: {r.query}",
            f"**策略**: `{r.strategy_used}`",
            f"**状态**: {r.status}",
            "",
            "### 根因分析",
            "",
        ])

        diagnosis = _diagnose_failure(r)
        lines.extend([
            f"- **数据充足性**: {'充足' if diagnosis['data_sufficient'] else '不足'}",
            f"- **分类准确性**: {'准确' if diagnosis['classification_ok'] else '可能不准'}",
            f"- **策略选择**: {diagnosis['strategy_assessment']}",
            f"- **需求有效性**: {'有效' if diagnosis['need_valid'] else '可能需要调整'}",
            "",
            "### 建议修复",
            "",
        ])
        for fix in diagnosis["suggested_fixes"]:
            lines.append(f"- {fix}")

        lines.extend(["", "---", ""])

    path = Path(output_dir) / "scenario_failures.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.resolve())


def _diagnose_failure(r: ScenarioResult) -> dict:
    diag = {
        "data_sufficient": True,
        "classification_ok": True,
        "strategy_assessment": "策略选择合理",
        "need_valid": True,
        "suggested_fixes": [],
    }

    details = r.details
    if "hits" in details and details["hits"] == 0:
        diag["data_sufficient"] = False
        diag["suggested_fixes"].append("检查 FTS5 索引是否覆盖了所有文档的全文内容")
        diag["suggested_fixes"].append("考虑增加关键词的同义词扩展（如 '追涨' → '追高' '高买'）")

    if "doc_count" in details and details.get("doc_count", 0) == 0:
        diag["data_sufficient"] = False
        diag["suggested_fixes"].append("检查该月份的数据是否已入库")
        diag["suggested_fixes"].append("验证 derived_time_month 字段是否正确填充")

    if "related_docs" in details and details.get("related_docs", 0) == 0:
        diag["classification_ok"] = False
        diag["suggested_fixes"].append("该主题的文档可能未被正确分类——检查分类规则")
        diag["suggested_fixes"].append("考虑添加该主题的项目关键词到分类规则")

    if "total_candidates" in details and details.get("total_candidates", 0) == 0:
        diag["strategy_assessment"] = "map_reduce_summary 策略可能不适用——尝试降低评分阈值"
        diag["suggested_fixes"].append("降低写作候选评分阈值（当前 score >= 3）")
        diag["suggested_fixes"].append("考虑使用 LLM 重新评估写作潜力")

    if "total_docs" in details and details.get("total_docs", 0) < 10:
        diag["data_sufficient"] = False
        diag["suggested_fixes"].append("过去半年的文档数量不足，无法进行有意义的认知变化分析")

    if not diag["suggested_fixes"]:
        diag["suggested_fixes"].append("深入检查该场景的具体失败原因（需要更细粒度的数据）")

    return diag


def generate_value_validation_report(results: list[ScenarioResult], output_dir: str) -> str:
    """Generate the key value validation report answering 5 critical questions."""
    passed = [r for r in results if r.status == "pass"]
    failed = [r for r in results if r.status == "fail"]
    partial = [r for r in results if r.status == "partial"]

    # Find most valuable scenario
    most_valuable = _rank_value(results)

    lines = [
        "# Value Validation Report",
        "",
        f"> 时间: {_ts()}",
        "",
        "---",
        "",
        "## 1. 哪个场景最有价值？",
        "",
        f"**{most_valuable['name']}** ({most_valuable['id']}) — {most_valuable['reason']}",
        "",
        "### 所有场景价值排序",
        "",
        "| 场景 | 价值评级 | 原因 |",
        "|------|---------|------|",
    ]
    for mv in most_valuable["ranking"]:
        lines.append(f"| {mv['name']} | {mv['value']} | {mv['reason']} |")

    # Question 2: Which failed?
    lines.extend([
        "",
        "## 2. 哪个场景失败？",
        "",
    ])
    if not failed:
        lines.append("✅ 没有完全失败的场景。")
        if partial:
            lines.append(f"⚠️ {len(partial)} 个场景部分通过：{', '.join(r.scenario_name for r in partial)}")
    else:
        for r in failed:
            lines.append(f"- ❌ **{r.scenario_name}**: {r.failure_reason}")

    # Question 3: Root cause
    lines.extend([
        "",
        "## 3. 失败根因：数据、分类、策略，还是需求？",
        "",
    ])

    root_causes = _analyze_root_causes(results)
    for cause in root_causes:
        lines.append(f"### {cause['title']}")
        lines.append(f"- **严重程度**: {cause['severity']}")
        lines.append(f"- **影响场景**: {', '.join(cause['affected'])}")
        lines.append(f"- **分析**: {cause['analysis']}")
        lines.append("")

    # Question 4: Worth continuing?
    lines.extend([
        "## 4. 是否值得继续做这个用户？",
        "",
    ])
    pass_rate = len(passed) / max(len(results), 1)
    if pass_rate >= 0.8:
        lines.append("✅ **值得继续。** 大多数核心场景产出有价值的结果。")
        lines.append("当前知识库架构能够支撑用户的主要查询模式。")
    elif pass_rate >= 0.5:
        lines.append("⚠️ **值得继续，但需调整。** 知识库有基础价值，部分场景需要优化。")
    else:
        lines.append("❌ **需要重新评估。** 多数场景未产出期望价值，但基础数据存在——问题可能在分类或检索层。")

    lines.extend([
        f"- 场景通过率: {pass_rate:.0%}",
        f"- 证据文件总量: {sum(len(r.evidence_files) for r in results)}",
        f"- 涉及分类: 多个（交易/AI/工具/个人随笔）",
        "",
    ])

    # Question 5: What rules need changing?
    lines.extend([
        "## 5. 需要改哪些规则？",
        "",
    ])
    rule_changes = _suggest_rule_changes(results)
    for rc in rule_changes:
        lines.append(f"### {rc['priority']} — {rc['rule']}")
        lines.append(f"- **原因**: {rc['reason']}")
        lines.append(f"- **影响**: {rc['impact']}")
        lines.append("")

    path = Path(output_dir) / "value_validation_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.resolve())


def _rank_value(results: list[ScenarioResult]) -> dict:
    rankings = []
    for r in results:
        if r.scenario_id == "S01":
            rankings.append({"name": r.scenario_name, "id": r.scenario_id,
                           "value": "⭐⭐⭐⭐⭐", "reason": "最核心的日常需求——找文件是知识库的基础价值，FTS 搜索频率最高"})
        elif r.scenario_id == "S02":
            rankings.append({"name": r.scenario_name, "id": r.scenario_id,
                           "value": "⭐⭐⭐⭐⭐", "reason": "月度复盘是用户明确的核心场景，结构化输出有强实用价值"})
        elif r.scenario_id == "S03":
            rankings.append({"name": r.scenario_name, "id": r.scenario_id,
                           "value": "⭐⭐⭐", "reason": "项目分析有价值但依赖准确的分类和丰富的项目文档"})
        elif r.scenario_id == "S04":
            rankings.append({"name": r.scenario_name, "id": r.scenario_id,
                           "value": "⭐⭐⭐⭐", "reason": "写作素材发现能直接推动内容产出，ROI 明确"})
        elif r.scenario_id == "S05":
            rankings.append({"name": r.scenario_name, "id": r.scenario_id,
                           "value": "⭐⭐⭐⭐", "reason": "自我认知变化是最长期的价值锚点，支撑整个知识库存在的意义"})

    rankings.sort(key=lambda x: x["value"], reverse=True)
    best = rankings[0]
    return {
        "name": best["name"],
        "id": best["id"],
        "reason": best["reason"],
        "ranking": rankings,
    }


def _analyze_root_causes(results: list[ScenarioResult]) -> list[dict]:
    causes = []
    for r in results:
        if r.status == "fail":
            details = r.details
            if details.get("hits") == 0 or details.get("doc_count") == 0:
                causes.append({
                    "title": "数据可得性不足",
                    "severity": "高",
                    "affected": [r.scenario_name],
                    "analysis": "部分场景下数据库查询返回空结果。可能原因：(1) FTS5 索引不完整，(2) 时间/分类过滤条件过于严格，(3) 数据量不足以支撑分析。",
                })
            if details.get("related_docs", 0) == 0:
                causes.append({
                    "title": "分类覆盖不完整",
                    "severity": "中",
                    "affected": [r.scenario_name],
                    "analysis": "特定主题（如'侦探小说 AI'）缺少明确的一级分类或标签，导致检索无法定位。需要在分类规则中加入项目名称匹配。",
                })
    if not causes:
        causes.append({
            "title": "整体表现良好",
            "severity": "低",
            "affected": [],
            "analysis": "所有场景至少部分通过。策略路由工作正常。可优化点：增加 LLM 驱动的摘要质量、增强写作潜力检测的准确性。",
        })
    return causes


def _suggest_rule_changes(results: list[ScenarioResult]) -> list[dict]:
    changes = []
    for r in results:
        if r.status == "fail":
            details = r.details
            if details.get("hits") == 0:
                changes.append({
                    "priority": "🔴 高优先级",
                    "rule": "确保 FTS5 索引覆盖所有纳入文档",
                    "reason": f"场景 '{r.scenario_name}' 未返回 FTS5 结果",
                    "impact": "影响所有依赖 FTS5 的查询场景",
                })
            if details.get("related_docs", 0) == 0:
                changes.append({
                    "priority": "🟡 中优先级",
                    "rule": "在分类规则中添加项目级关键词匹配",
                    "reason": f"场景 '{r.scenario_name}' 的分类查询无结果",
                    "impact": "影响特定主题的项目分析能力",
                })

    # Always suggest ongoing improvements
    changes.append({
        "priority": "🟢 低优先级",
        "rule": "定期运行 validate-deep-custom 追踪场景通过率",
        "reason": "持续追踪场景通过率，及早发现质量劣化",
        "impact": "知识库质量保证的基础设施",
    })
    return changes


def generate_all_reports(results: list[ScenarioResult], output_dir: str) -> dict[str, str]:
    return {
        "scenario_results": generate_scenario_results_md(results, output_dir),
        "scenario_failures": generate_scenario_failures_md(results, output_dir),
        "value_validation_report": generate_value_validation_report(results, output_dir),
    }
