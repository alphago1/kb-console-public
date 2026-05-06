from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path


def write_coverage_report(selected: list[dict], coverage: dict, output_dir: str) -> str:
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Sample Coverage Report",
        "",
        f"> 样本数: {len(selected)}",
        "",
        "## 各维度覆盖率",
        "",
        "| 维度 | 已覆盖 | 总数 | 覆盖率 | 缺失层 |",
        "|------|--------|------|--------|--------|",
    ]
    for dim, info in sorted(coverage.items()):
        missing = set(info["total"]) - set(info["covered"])
        missing_str = ", ".join(sorted(missing)) if missing else "—"
        lines.append(f"| {dim} | {info['count_covered']} | {info['count_total']} | {info['pct']}% | {missing_str} |")

    lines.extend([
        "",
        "---",
        "",
        "## 样本分布矩阵",
        "",
    ])
    lines.extend(_distribution_matrix(selected))
    lines.extend([
        "",
        "---",
        "",
        "## 各文件覆盖度",
        "",
        "每个文件覆盖了哪些 stratum：",
        "",
    ])
    lines.extend(_per_file_strata(selected))

    out_path = od / "sample_coverage_report.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out_path.resolve())


def write_sample_dashboard(selected: list[dict], coverage: dict, output_dir: str) -> str:
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    # Build data for charts
    by_cat = Counter(s["primary_category"] for s in selected)
    by_month = Counter(s["month"] for s in selected)
    by_type = Counter(s.get("strata", {}).get("type", "?") for s in selected)
    by_risk = Counter(s.get("strata", {}).get("risk", "正常") for s in selected)
    reasons = Counter(s["sampling_reason"].split(":")[0] for s in selected)

    html = f"""<!DOCTYPE html>
<html lang="zh-cn">
<head>
<meta charset="utf-8">
<title>Sample Coverage Dashboard</title>
<style>
 body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
 h1 {{ color: #1a1a2e; }}
 .card {{ background: white; border-radius: 8px; padding: 16px; margin: 12px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
 .stat {{ font-size: 28px; font-weight: bold; color: #2563eb; }}
 .bar {{ height: 24px; background: #e5e7eb; border-radius: 4px; margin: 4px 0; overflow: hidden; }}
 .bar-fill {{ height: 100%; background: #2563eb; border-radius: 4px; }}
 .label {{ font-size: 12px; color: #6b7280; }}
 table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
 th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
 th {{ background: #f3f4f6; }}
 .pass {{ color: #059669; }} .warn {{ color: #d97706; }}
</style>
</head>
<body>
<h1>🔬 Sample Coverage Dashboard</h1>
<p>分层均匀小样本验证 · {len(selected)} 个文件</p>

<div class="grid">
<div class="card">
  <div class="stat">{len(selected)}</div>
  <div class="label">选中文件</div>
</div>
<div class="card">
  <div class="stat">{len(by_cat)}</div>
  <div class="label">覆盖分类</div>
</div>
<div class="card">
  <div class="stat">{max((info['pct'] for info in coverage.values()), default=0)}%</div>
  <div class="label">最高维度覆盖率</div>
</div>
<div class="card">
  <div class="stat">{min((info['pct'] for info in coverage.values()), default=0)}%</div>
  <div class="label">最低维度覆盖率</div>
</div>
</div>

<div class="card">
<h3>6 维覆盖率</h3>
"""
    for dim, info in sorted(coverage.items()):
        pct = info['pct']
        cls = "pass" if pct >= 90 else ("warn" if pct >= 50 else "")
        html += f'<div class="label">{dim} <span class="{cls}">{pct}%</span></div>'
        html += f'<div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>'

    html += """
</div>

<div class="grid">
<div class="card">
<h3>按分类</h3>
<table>
<tr><th>分类</th><th>数量</th></tr>
"""
    for cat, n in by_cat.most_common():
        html += f"<tr><td>{cat}</td><td>{n}</td></tr>"
    html += "</table></div>"

    html += """
<div class="card">
<h3>按采样理由</h3>
<table>
<tr><th>维度</th><th>数量</th></tr>
"""
    for reason, n in reasons.most_common():
        html += f"<tr><td>{reason}</td><td>{n}</td></tr>"
    html += "</table></div>"

    html += """
<div class="card">
<h3>按风险类型</h3>
<table>
<tr><th>风险</th><th>数量</th></tr>
"""
    for risk, n in by_risk.most_common():
        html += f"<tr><td>{risk}</td><td>{n}</td></tr>"
    html += "</table></div>"

    html += """
<div class="card">
<h3>按时间段</h3>
<table>
<tr><th>月份</th><th>数量</th></tr>
"""
    for month, n in sorted(by_month.most_common()):
        html += f"<tr><td>{month}</td><td>{n}</td></tr>"
    html += "</table></div>"
    html += "</div>"

    html += """
<div class="card">
<h3>选中文件列表</h3>
<table>
<tr><th>#</th><th>文件名</th><th>分类</th><th>月份</th><th>理由</th><th>置信度</th></tr>
"""
    for i, s in enumerate(selected, 1):
        conf_str = f"{float(s.get('confidence', 0)):.2f}"
        conf_cls = "warn" if float(s.get('confidence', 0)) < 0.75 else "pass"
        html += f"<tr><td>{i}</td><td>{s['filename'][:50]}</td><td>{s['primary_category']}</td>"
        html += f"<td>{s['month']}</td><td>{s['sampling_reason'][:40]}</td>"
        html += f"<td class='{conf_cls}'>{conf_str}</td></tr>"
    html += "</table></div>"

    html += "</body></html>"

    out_path = od / "sample_dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path.resolve())


def write_review_questions(selected: list[dict], output_dir: str) -> str:
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    low_conf = [s for s in selected if float(s.get("confidence", 0)) < 0.75 or s.get("needs_review")]
    risk_files = [s for s in selected if s.get("strata", {}).get("risk", "正常") != "正常"]

    lines = [
        "# Sample Review Questions",
        "",
        "以下问题基于分层样本生成，用于在正式构建前验证分类策略和报告模板。",
        "",
        "---",
        "",
        "## 结构性问题",
        "",
        "1. 以下分类覆盖是否合理？是否有分类过细（只有 1-2 个样本）或过粗（样本都集中在一个分类）？",
        "2. 时间维度的分布是否符合你的记忆？有没有某段时间明显缺失？",
        "3. 文件类型覆盖是否反映你的实际使用习惯？",
        "",
        "---",
        "",
        "## 边界场景问题",
        "",
    ]

    if low_conf:
        lines.append(f"4. 以下 {len(low_conf)} 个低置信度文件的分类是否准确？")
        lines.append("")
        for s in low_conf[:10]:
            lines.append(f"   - [{s['month']}] {s['filename'][:50]} (当前分类: {s['primary_category']}, 置信度: {float(s.get('confidence', 0)):.2f})")
        lines.append("")

    if risk_files:
        lines.append(f"5. 以下 {len(risk_files)} 个风险文件应如何处理？")
        lines.append("")
        for s in risk_files[:10]:
            risk_label = s.get("strata", {}).get("risk", "未知")
            lines.append(f"   - [{risk_label}] {s['filename'][:50]}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 分类策略问题",
        "",
        "6. 当前 classification_policy.yaml 定义的分类体系能否正确处理以上样本？",
        "7. 是否有文件同时适合多个分类？如何处理跨分类文件？",
        "8. 排除规则是否可能误杀正常文件？",
        "",
        "---",
        "",
        "## 下一步",
        "",
        "1. 审核以上问题，标注同意/不同意/需要修改",
        "2. 将反馈写入 feedback_rules.yaml",
        "3. 重新 sample-run（如需要）",
        "4. 确认后进入 Phase D：正式构建 deep-custom 知识库",
    ])

    out_path = od / "sample_review_questions.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out_path.resolve())


def _distribution_matrix(selected: list[dict]) -> list[str]:
    lines = [
        "### 分类 × 时间段交叉分布",
        "",
    ]
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    months_set: set[str] = set()
    for s in selected:
        cat = s["primary_category"] or "?"
        month = (s["month"] or "?")[:7]
        matrix[cat][month] += 1
        months_set.add(month)

    sorted_months = sorted(months_set)
    header = "| 分类 | " + " | ".join(sorted_months) + " | 合计 |"
    sep = "|------|" + "|".join(["------" for _ in sorted_months]) + "|------|"
    lines.append(header)
    lines.append(sep)
    for cat in sorted(matrix.keys()):
        row = f"| {cat} | "
        row += " | ".join(str(matrix[cat].get(m, 0)) for m in sorted_months)
        row += f" | {sum(matrix[cat].values())} |"
        lines.append(row)
    return lines


def _per_file_strata(selected: list[dict]) -> list[str]:
    lines = [
        "| 文件 | T(时间) | T(类型) | S(大小) | D(目录) | U(用途) | R(风险) |",
        "|------|---------|---------|---------|---------|---------|---------|",
    ]
    for s in selected[:30]:
        st = s.get("strata", {})
        lines.append(
            f"| {s['filename'][:25]} "
            f"| {st.get('time', '?')} "
            f"| {st.get('type', '?')} "
            f"| {st.get('size', '?')} "
            f"| {st.get('dir', '?')[:10]} "
            f"| {st.get('use', '?')} "
            f"| {st.get('risk', '?')} |"
        )
    return lines
