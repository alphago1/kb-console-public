from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path


def write_sample_manifest(selected: list[dict], coverage: dict, output_dir: str) -> str:
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Sample Manifest — 分层均匀小样本验证",
        "",
        f"> 样本数: {len(selected)}",
        f"> 生成时间: auto",
        "",
        "---",
        "",
        "## 为什么选这些文件",
        "",
        "采用 **Greedy Coverage Maximization** 算法，分三个阶段选择：",
        "",
        "1. **强制覆盖阶段**：确保 6 个分层维度 (时间/类型/大小/目录/用途/风险) 的每个 stratum 至少有一个代表文件",
        "2. **比例填充阶段**：按各分类的文件占比分配剩余名额",
        "3. **风险兜底阶段**：确保低置信度、疑似排除文件至少占 10%",
        "",
        "---",
        "",
        "## 覆盖情况",
        "",
        _coverage_table(coverage),
        "",
        "---",
        "",
        "## 时间覆盖",
        "",
        _stratum_section(selected, "时间段", "time"),
        "",
        "---",
        "",
        "## 文件类型覆盖",
        "",
        _stratum_section(selected, "文件类型", "type"),
        "",
        "---",
        "",
        "## 目录覆盖",
        "",
        _stratum_section(selected, "目录", "dir"),
        "",
        "---",
        "",
        "## 用途覆盖",
        "",
        _stratum_section(selected, "用途", "use"),
        "",
        "---",
        "",
        "## 边界场景覆盖",
        "",
        _risk_section(selected),
        "",
        "---",
        "",
        "## 未覆盖区域",
        "",
        _gaps_section(coverage),
        "",
        "---",
        "",
        "## 本次样本是否足够判断结构",
        "",
        _sufficiency_judgment(selected, coverage),
    ]

    out_path = od / "sample_manifest.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out_path.resolve())


def write_sample_knowledge_map(selected: list[dict], output_dir: str) -> str:
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Sample Knowledge Map",
        "",
        f"## 样本文件地图 ({len(selected)} 个文件)",
        "",
        "| # | 文件名 | 分类 | 月份 | 采样理由 |",
        "|---|--------|------|------|---------|",
    ]
    for i, s in enumerate(selected, 1):
        lines.append(f"| {i} | {s['filename'][:50]} | {s['primary_category']} | {s['month']} | {s['sampling_reason']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 按分类分组的样本",
        "",
    ])

    by_cat = defaultdict(list)
    for s in selected:
        by_cat[s["primary_category"] or "未分类"].append(s)
    for cat, files in sorted(by_cat.items()):
        lines.append(f"### {cat} ({len(files)} 个)")
        lines.append("")
        for f in files:
            lines.append(f"- [{f['month']}] {f['filename'][:60]} ({f['sampling_reason']})")
        lines.append("")

    out_path = od / "sample_knowledge_map.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out_path.resolve())


def _coverage_table(coverage: dict) -> str:
    lines = [
        "| 维度 | 已覆盖层数 | 总层数 | 覆盖率 |",
        "|------|----------|--------|--------|",
    ]
    for dim, info in sorted(coverage.items()):
        lines.append(f"| {dim} | {info['count_covered']} | {info['count_total']} | {info['pct']}% |")
    return "\n".join(lines)


def _stratum_section(selected: list[dict], label: str, dim: str) -> str:
    counter = Counter(s.get("strata", {}).get(dim, "unknown") for s in selected)
    lines = [f"| {label} | 数量 |", f"|------|------|"]
    for val, count in counter.most_common():
        lines.append(f"| {val} | {count} |")
    return "\n".join(lines)


def _risk_section(selected: list[dict]) -> str:
    risks = [s for s in selected if s.get("strata", {}).get("risk", "正常") != "正常"]
    if not risks:
        return "样本中无风险文件。\n"
    lines = [
        f"边界场景覆盖 {len(risks)} 个风险文件：",
        "",
        "| 文件名 | 风险类型 | 分类 |",
        "|--------|---------|------|",
    ]
    for s in risks:
        lines.append(f"| {s['filename'][:40]} | {s['strata']['risk']} | {s['primary_category']} |")
    return "\n".join(lines)


def _gaps_section(coverage: dict) -> str:
    lines = []
    dim_names = {
        "time": "时间", "type": "文件类型", "size": "文件大小",
        "dir": "目录", "use": "用途", "risk": "风险",
    }
    for dim, info in sorted(coverage.items()):
        if info["pct"] < 100:
            missing = set(info["total"]) - set(info["covered"])
            lines.append(f"- **{dim_names.get(dim, dim)}** 未覆盖: {', '.join(sorted(missing))}")
    if not lines:
        lines.append("所有维度的所有层级均已覆盖。")
    return "\n".join(lines)


def _sufficiency_judgment(selected: list[doc], coverage: dict) -> str:
    all_covered = all(info["pct"] >= 90 for info in coverage.values())
    enough_files = len(selected) >= 30

    lines = []
    if all_covered and enough_files:
        lines.append("✅ **样本量足够判断结构。**")
        lines.append("")
        lines.append("原因：")
        lines.append("- 6 个维度的覆盖率均 ≥ 90%")
        lines.append(f"- 样本量 {len(selected)} 在推荐范围 (30-80) 内")
    elif not enough_files:
        lines.append("⚠️ **样本量偏少，建议增加。**")
        lines.append(f"当前 {len(selected)} 个文件，建议至少 30 个。")
    else:
        lines.append("⚠️ **覆盖不完整，建议补充。**")
        for dim, info in coverage.items():
            if info["pct"] < 90:
                missing = set(info["total"]) - set(info["covered"])
                lines.append(f"- {dim} 缺少: {', '.join(sorted(missing))}")
    return "\n".join(lines)
