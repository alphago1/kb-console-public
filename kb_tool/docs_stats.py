from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from extractor import extract_text


@dataclass(frozen=True)
class FileStat:
    rel_path: str
    abs_path: str
    category: str
    month: str
    extension: str
    byte_size: int
    char_count_no_ws: int
    extract_error: str | None


def _workspace_root() -> Path:
    # kb_tool/ is one level under workspace root
    return Path(__file__).resolve().parents[1]


def _default_docs_root() -> Path:
    return _workspace_root() / "docs"


def _default_report_path() -> Path:
    return _workspace_root() / "docs_字数统计报告.md"


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _char_count_no_ws(text: str) -> int:
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())


def _estimate_tokens_range(chars_no_ws: int) -> tuple[int, int]:
    """Very rough token estimate.

    For Chinese-heavy text, BPE tokenization is often ~1 token per 1–2 chars.
    We return a conservative range:
      - low: 1 token / 2.2 chars
      - high: 1 token / 1.2 chars
    """

    if chars_no_ws <= 0:
        return 0, 0
    low = int(chars_no_ws / 2.2)
    high = int(chars_no_ws / 1.2)
    return max(low, 1), max(high, 1)


def _add_month(ym: str, delta_months: int) -> str:
    y, m = ym.split("-")
    year = int(y)
    month = int(m)
    total = year * 12 + (month - 1) + delta_months
    out_year = total // 12
    out_month = total % 12 + 1
    return f"{out_year:04d}-{out_month:02d}"


def collect_docs_stats(cfg: dict, docs_root: Path) -> list[FileStat]:
    out: list[FileStat] = []

    root = docs_root
    for p in _iter_files(root):
        rel = str(p.relative_to(root))
        parts = p.relative_to(root).parts
        category = parts[0] if len(parts) >= 1 else "_unknown_category"
        month = parts[1] if len(parts) >= 2 else "_unknown_month"

        ext = p.suffix.lower()
        byte_size = p.stat().st_size

        text, _, _, err = extract_text(cfg, str(p), ext)
        cc = _char_count_no_ws(text or "") if not err else 0

        out.append(
            FileStat(
                rel_path=rel,
                abs_path=str(p),
                category=category,
                month=month,
                extension=ext,
                byte_size=byte_size,
                char_count_no_ws=cc,
                extract_error=err,
            )
        )

    return out


def render_report(stats: list[FileStat]) -> str:
    file_count = len(stats)
    supported = [s for s in stats if not s.extract_error]
    errored = [s for s in stats if s.extract_error]

    chars = [s.char_count_no_ws for s in supported]
    total_chars = sum(chars)
    avg_chars = int(mean(chars)) if chars else 0
    med_chars = int(median(chars)) if chars else 0

    total_tokens_low, total_tokens_high = _estimate_tokens_range(total_chars)

    # per month totals
    months = sorted({s.month for s in supported})
    month_rows = []
    for m in months:
        m_stats = [s for s in supported if s.month == m]
        m_chars = sum(s.char_count_no_ws for s in m_stats)
        m_avg = int(mean([s.char_count_no_ws for s in m_stats])) if m_stats else 0
        month_rows.append((m, len(m_stats), m_chars, m_avg))

    # category x month totals
    categories = sorted({s.category for s in supported})
    pivot = {(c, m): 0 for c in categories for m in months}
    for s in supported:
        pivot[(s.category, s.month)] += s.char_count_no_ws

    # special: 4 trading folders totals (if present)
    focus_categories = ["交易系统与方法论", "交易心理与情绪", "交易复盘", "交易记录"]
    focus_present = [c for c in focus_categories if c in set(categories)]
    focus_stats = [s for s in supported if s.category in focus_present]
    focus_chars = sum(s.char_count_no_ws for s in focus_stats)
    focus_tokens_low, focus_tokens_high = _estimate_tokens_range(focus_chars)

    # linear projection to 1M tokens (use high estimate for safety)
    projection_note = ""
    projection_recent_note = ""
    if months:
        current_tokens = total_tokens_high
        months_count = len(months)
        last_month = max(months)

        avg_tokens_per_month = int(current_tokens / months_count) if months_count else 0
        if avg_tokens_per_month <= 0:
            projection_note = "无法计算（每月平均 token 为 0）。"
        elif current_tokens >= 1_000_000:
            projection_note = "当前估算已超过 1,000,000 token。"
        else:
            remaining = 1_000_000 - current_tokens
            months_to_1m = int((remaining + avg_tokens_per_month - 1) / avg_tokens_per_month)
            reach_month = _add_month(last_month, months_to_1m)
            projection_note = (
                f"口径 A（全跨度平均）：以“当前总量 / 覆盖月份数({months_count})”作为线性月增量（{avg_tokens_per_month:,} token/月，高估口径），"
                f"从最新月份 {last_month} 推算，约 {months_to_1m} 个月后（≈ {reach_month}）达到 1,000,000 token。"
            )

        # Recent 3 months slope
        if len(month_rows) >= 3:
            recent = month_rows[-3:]
            recent_chars = sum(r[2] for r in recent)
            _, recent_tokens_high = _estimate_tokens_range(recent_chars)
            recent_avg = int(recent_tokens_high / 3)
            if current_tokens < 1_000_000 and recent_avg > 0:
                remaining = 1_000_000 - current_tokens
                months_to_1m = int((remaining + recent_avg - 1) / recent_avg)
                reach_month = _add_month(last_month, months_to_1m)
                projection_recent_note = (
                    f"口径 B（最近 3 个月平均）：最近 3 个月合计约 {recent_tokens_high:,} token（高估口径），"
                    f"平均 {recent_avg:,} token/月；从 {last_month} 推算约 {months_to_1m} 个月后（≈ {reach_month}）达到 1,000,000 token。"
                )

    def md_table(rows: list[tuple], headers: list[str]) -> str:
        out_lines = []
        out_lines.append("| " + " | ".join(headers) + " |")
        out_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for r in rows:
            out_lines.append("| " + " | ".join(str(x) for x in r) + " |")
        return "\n".join(out_lines)

    lines: list[str] = []
    lines.append("# docs 字数统计报告")
    lines.append("")
    lines.append("说明：")
    lines.append("- ‘字数’ 口径：对抽取到的文本按 **去空白字符数** 统计（包含中文/英文/数字/标点）。")
    lines.append("- token 估算：基于中文 BPE 的粗略区间估算（低估：1 token≈2.2 字；高估：1 token≈1.2 字）。不同模型实现会有偏差。")
    lines.append("")

    lines.append("## 总览")
    lines.append(f"- 文件总数：{file_count}")
    lines.append(f"- 成功抽取文本：{len(supported)}")
    lines.append(f"- 抽取失败：{len(errored)}")
    lines.append(f"- 总字数（去空白字符）：{total_chars:,}")
    lines.append(f"- 平均每文件字数：{avg_chars:,}")
    lines.append(f"- 中位数每文件字数：{med_chars:,}")
    lines.append(f"- 总 token 估算区间：{total_tokens_low:,} ～ {total_tokens_high:,}")
    lines.append("")

    lines.append("## 按月统计（每个月写了多少）")
    lines.append(md_table(month_rows, ["月份", "文件数", "总字数", "每文件平均字数"]))
    lines.append("")

    lines.append("## 按类别 × 月份统计（每月各类别字数）")
    # render pivot table
    pivot_headers = ["类别"] + months
    pivot_rows = []
    for c in categories:
        row = [c] + [pivot[(c, m)] for m in months]
        pivot_rows.append(tuple(row))
    lines.append(md_table(pivot_rows, pivot_headers))
    lines.append("")

    lines.append("## 四个交易相关文件夹的总量与 1M 上下文可读性")
    if not focus_present:
        lines.append("未在 docs 根目录下发现指定的四个类别文件夹（交易系统与方法论 / 交易心理与情绪 / 交易复盘 / 交易记录）。")
    else:
        lines.append(f"- 覆盖类别：{', '.join(focus_present)}")
        lines.append(f"- 总字数：{focus_chars:,}")
        lines.append(f"- token 估算区间：{focus_tokens_low:,} ～ {focus_tokens_high:,}")
        lines.append(f"- 结论（按高估口径）：{'可以' if focus_tokens_high <= 1_000_000 else '不可以'} 在 1,000,000 token 上下文一次性读完。")
    lines.append("")

    lines.append("## 1M token 规模线性推算（以当前知识库整体为基准）")
    if not months:
        lines.append("数据月份为空，无法推算。")
    else:
        lines.append(projection_note)
        if projection_recent_note:
            lines.append("\n" + projection_recent_note)
    lines.append("")

    if errored:
        lines.append("## 抽取失败文件（原因）")
        err_rows = [(e.rel_path, e.extension, e.extract_error) for e in errored]
        lines.append(md_table(err_rows, ["相对路径", "扩展名", "错误"]))
        lines.append("")

    lines.append("## 文件字数清单")
    rows = [(s.rel_path, s.category, s.month, s.extension, s.char_count_no_ws) for s in sorted(supported, key=lambda x: x.rel_path)]
    lines.append(md_table(rows, ["相对路径", "类别", "月份", "扩展名", "字数"]))

    return "\n".join(lines) + "\n"


def write_docs_stats_report(cfg: dict, docs_root: str | None = None, output_path: str | None = None) -> dict:
    docs_root_path = Path(docs_root) if docs_root else _default_docs_root()
    out_path = Path(output_path) if output_path else _default_report_path()

    if not docs_root_path.exists():
        raise FileNotFoundError(f"docs root not found: {docs_root_path}")

    stats = collect_docs_stats(cfg, docs_root_path)
    md = render_report(stats)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    return {
        "docs_root": str(docs_root_path.resolve()),
        "output": str(out_path.resolve()),
        "file_count": len(stats),
        "ok": sum(1 for s in stats if not s.extract_error),
        "errors": sum(1 for s in stats if s.extract_error),
    }
