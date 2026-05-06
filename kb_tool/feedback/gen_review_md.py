"""Generate user-facing review_sample.md from review_sample.csv."""
import csv, sys
from collections import Counter
from pathlib import Path

csv_path = sys.argv[1] if len(sys.argv) > 1 else "kb_out/unsupervised/review_sample.csv"
out_path = sys.argv[2] if len(sys.argv) > 2 else csv_path.replace(".csv", ".md")

rows = []
with open(csv_path, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append(r)

cats = Counter(r["current_category"] for r in rows)
reasons = Counter(r["sample_reason"] for r in rows)
label_map = {
    "representative": "representative",
    "boundary": "boundary",
    "time_coverage": "time_coverage",
    "gap_fill": "gap_fill",
}

L = []
L.append("# 分类审查 — 用户检查清单")
L.append("")
L.append(f"> 从 276 个文件中抽取 **{len(rows)} 个**（{len(cats)} 类全覆盖）供人工审查。")
L.append(f"> 每个文件附 LLM 摘要，**无需打开原文**即可判断分类是否正确。")
L.append("")
L.append("## 怎么用")
L.append("")
L.append("| 写法 | 含义 |")
L.append("|------|------|")
L.append("| `正确` | 分类没问题 |")
L.append("| `应为:新分类名` | 分错了，改成新分类 |")
L.append("| `合并到:目标分类` | 这个分类太细，合并到其他类 |")
L.append(f"| （留空） | 跳过，不做判断 |")
L.append("")
L.append("## 抽样概况")
L.append("")
L.append("| 指标 | 值 |")
L.append("|------|-----|")
L.append(f"| 抽样数 | {len(rows)} / 276 |")
L.append(f"| 分类数 | {len(cats)} |")
L.append(f"| 边界文件（最可能错） | {reasons.get('boundary',0)} |")
L.append(f"| 代表文件（最典型） | {reasons.get('representative',0)} |")
L.append(f"| 时间段覆盖 | {reasons.get('time_coverage',0)} |")
L.append("")
L.append("---")
L.append("")

for cat in sorted(cats.keys(), key=lambda c: -cats[c]):
    cat_rows = [r for r in rows if r["current_category"] == cat]
    L.append(f"## {cat}（{len(cat_rows)} 个样本）")
    L.append("")
    L.append("| # | 文件名 | 原因 | LLM 摘要 | 你的判断 |")
    L.append("|---|--------|------|----------|----------|")
    for i, r in enumerate(cat_rows, 1):
        fn = r["filename"][:50]
        reason_short = {
            "representative": "代表", "boundary": "边界",
            "time_coverage": "时间", "gap_fill": "补充",
        }.get(r["sample_reason"], r["sample_reason"])
        summary = (r.get("summary", "") or "")[:100].replace("|", "/").replace("\n", " ")
        L.append(f"| {i} | {fn} | {reason_short} | {summary}... | _________ |")
    L.append("")

Path(out_path).write_text("\n".join(L), encoding="utf-8")
print(f"Written {len(L)} lines to {out_path}")
