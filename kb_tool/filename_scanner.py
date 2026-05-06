"""
Filename-first scanner: build a file world map without reading file bodies.

Reads only file names, paths, and OS metadata. Generates inventory reports
so the user can see the full landscape before any content processing.

Zero LLM calls. Zero file content reads. Zero file modifications.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

from utils.path_utils import matches_any_glob, norm_abs

# ── date extraction patterns ──
_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-_/.]?(0[1-9]|1[0-2])[-_/.]?(0[1-9]|[12]\d|3[01])?"),  # 2026-03-15
    re.compile(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])?"),                  # 20260315
    re.compile(r"(20\d{2})年(0[1-9]|1[0-2])月"),                                    # 2026年3月
    re.compile(r"(0[1-9]|1[0-2])月(0[1-9]|[12]\d|3[01])[日号]"),                    # 3月15日
    re.compile(r"Q([1-4])\s*(20\d{2})"),                                              # Q1 2026
    re.compile(r"(20\d{2})\s*Q([1-4])"),                                              # 2026 Q1
]

# ── topic keyword extraction ──
# Chinese: split by common separators; English: split by non-alphanumeric
_WORD_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "如何", "为什么", "因为", "所以", "但是", "然后",
    "可以", "需要", "应该", "可能", "已经", "还是", "只是", "而且",
    "v1", "v2", "v3", "v4", "final", "draft", "copy", "version",
    "the", "a", "an", "is", "of", "and", "or", "in", "to", "for",
    "with", "on", "at", "by", "from", "as", "this", "that", "it",
    "不是", "就是", "还是", "没有", "知道", "觉得", "应该", "可以",
    "tmp", "temp", "backup", "old", "new",
}
_MIN_TOKEN_LEN = 2  # skip single-char tokens


def _iter_files(
    root_dirs: list[str],
    include_exts: set[str],
    exclude_dir_globs: list[str],
    exclude_file_globs: list[str],
    recursive: bool = True,
    max_files: Optional[int] = None,
) -> Iterable[dict]:
    """Walk root_dirs, yield file metadata dicts. Does NOT read file contents."""
    seen = 0
    for root in root_dirs:
        root_abs = norm_abs(root)
        if not os.path.isdir(root_abs):
            continue

        if recursive:
            for dirpath, dirnames, filenames in os.walk(root_abs):
                # prune excluded dirs
                pruned = []
                for d in list(dirnames):
                    full = os.path.join(dirpath, d)
                    if matches_any_glob(full, exclude_dir_globs):
                        pruned.append(d)
                for d in pruned:
                    dirnames.remove(d)

                for name in filenames:
                    filepath = os.path.join(dirpath, name)
                    if matches_any_glob(name, exclude_file_globs):
                        continue
                    ext = Path(name).suffix.lower()
                    if ext not in include_exts:
                        continue
                    yield _build_record(filepath, root_abs, include_exts)
                    seen += 1
                    if max_files and seen >= max_files:
                        return
        else:
            # Non-recursive: only top-level files
            try:
                with os.scandir(root_abs) as entries:
                    for entry in entries:
                        if not entry.is_file():
                            continue
                        name = entry.name
                        if matches_any_glob(name, exclude_file_globs):
                            continue
                        ext = Path(name).suffix.lower()
                        if ext not in include_exts:
                            continue
                        yield _build_record(entry.path, root_abs, include_exts)
                        seen += 1
                        if max_files and seen >= max_files:
                            return
            except OSError:
                continue


def _build_record(filepath: str, root_abs: str, _include_exts: set[str]) -> dict:
    path_obj = Path(filepath)
    filename = path_obj.name
    ext = path_obj.suffix.lower()

    # stat
    try:
        st = os.stat(filepath)
        size = st.st_size
        ctime = datetime.fromtimestamp(st.st_ctime)
        mtime = datetime.fromtimestamp(st.st_mtime)
    except OSError:
        size = 0
        ctime = datetime.min
        mtime = datetime.min

    # depth relative to root
    rel_path = str(path_obj.relative_to(root_abs))
    depth = len(Path(rel_path).parts) - 1 if rel_path != filename else 0

    # parent folder (relative)
    parent_folder = str(Path(rel_path).parent) if rel_path != filename else "."

    # time_month from mtime
    try:
        time_month = mtime.strftime("%Y-%m")
    except Exception:
        time_month = "unknown"

    # tokenize filename
    stem = path_obj.stem
    filename_tokens = _tokenize(stem)

    # tokenize path
    path_tokens_raw: list[str] = []
    for part in Path(rel_path).parts:
        path_tokens_raw.extend(_tokenize(part))
    # dedup preserving order
    path_tokens: list[str] = list(dict.fromkeys(path_tokens_raw))

    # suspected date from filename
    suspected_date = _extract_date(filename)

    # suspected topic keywords from filename + parent folder
    suspected_topic_keywords = _extract_keywords(stem, parent_folder)

    return {
        "file_id": _short_hash(filepath),
        "path": filepath,
        "filename": filename,
        "extension": ext,
        "parent_folder": parent_folder,
        "size": size,
        "created_time": ctime.isoformat() if ctime != datetime.min else None,
        "modified_time": mtime.isoformat() if mtime != datetime.min else None,
        "time_month": time_month,
        "depth": depth,
        "filename_tokens": filename_tokens,
        "path_tokens": path_tokens,
        "suspected_date": suspected_date,
        "suspected_topic_keywords": suspected_topic_keywords,
    }


def _short_hash(path: str) -> str:
    """Stable short hash for file identity."""
    import hashlib
    return hashlib.sha256(path.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _tokenize(text: str) -> list[str]:
    """Split a string into meaningful tokens."""
    tokens: list[str] = []
    # Split on common delimiters
    parts = re.split(r"[\s\-_.,;:!?()（）\[\]【】「」『』、。，；：！？…—\-\+]+", text)
    for part in parts:
        part = part.strip()
        if not part or len(part) < _MIN_TOKEN_LEN:
            continue
        # Normalize unicode
        part = unicodedata.normalize("NFKC", part)
        part_lower = part.lower()
        if part_lower in _STOP_WORDS:
            continue
        tokens.append(part)
    return tokens


def _extract_date(text: str) -> Optional[str]:
    """Extract the most plausible date from text. Returns YYYY-MM-DD or YYYY-MM or YYYY-QN or None."""
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            groups = m.groups()
            # 2026-03-15 style
            if len(groups) >= 3 and groups[2]:
                return f"{groups[0]}-{groups[1]}-{groups[2]}"
            # 2026-03 style
            if len(groups) >= 2 and groups[1]:
                return f"{groups[0]}-{groups[1]}"
            # year + quarter
            if "Q" in m.group():
                year = groups[0] if groups[0].isdigit() else (groups[1] if len(groups) > 1 and groups[1].isdigit() else None)
                q = groups[1] if len(groups) > 1 and groups[1].isdigit() else groups[0]
                if year and q.isdigit():
                    return f"{year}-Q{q}"
            # year only
            if groups[0].isdigit() and len(groups[0]) == 4:
                return groups[0]
            break
    return None


def _extract_keywords(stem: str, parent_folder: str) -> list[str]:
    """Extract meaningful topic keywords from filename stem and parent folder."""
    all_tokens = _tokenize(stem) + _tokenize(parent_folder)
    # Dedup, keep order
    seen: set[str] = set()
    result: list[str] = []
    for t in all_tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:20]  # cap


# ──────────────────────────── report generators ────────────────────────────

def _generate_folder_tree(records: list[dict], root_dirs: list[str]) -> str:
    """Generate a markdown folder tree showing document distribution."""
    # Build tree structure: ignore root-level (parent_folder == ".") from the tree
    # since they are direct children of root.
    tree: dict[str, Any] = {}
    for rec in records:
        parent = rec["parent_folder"]
        if parent == ".":
            continue  # root-level files are counted separately
        parts = parent.replace("\\", "/").split("/")
        node = tree
        for part in parts:
            if not part:
                continue
            node = node.setdefault(part, {})

    # Count files per folder
    folder_counts: dict[str, int] = defaultdict(int)
    root_count = 0
    for rec in records:
        if rec["parent_folder"] == ".":
            root_count += 1
        else:
            folder_counts[rec["parent_folder"]] += 1
            # Also count intermediate path segments for cumulative counts
            parts = rec["parent_folder"].replace("\\", "/").split("/")
            for i in range(1, len(parts) + 1):
                ancestor = "/".join(parts[:i])
                if ancestor not in folder_counts:
                    folder_counts[ancestor] = 0
                folder_counts[ancestor] += 1

    lines = [
        "# Folder Tree — Document Distribution",
        "",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> Root directories: {', '.join(root_dirs)}",
        f"> Total files: {len(records)}",
        "",
    ]

    # Build indented tree
    # display_prefix: what comes before THIS node's name
    # children_prefix: what comes before children's connectors (continuation from parent)
    def _render_tree(node: dict, display_prefix: str, name: str, children_prefix: str) -> list[str]:
        out: list[str] = []
        display = name if name else "(root)"
        count = folder_counts.get(name, 0)
        if not name:
            count = root_count
        out.append(f"{display_prefix}{display} ({count} files)")
        if node:
            items = sorted(node.items())
            for i, (child_name, child_node) in enumerate(items):
                is_last_child = (i == len(items) - 1)
                connector = "└── " if is_last_child else "├── "
                continuation = "    " if is_last_child else "│   "
                full_child = f"{name}/{child_name}" if name else child_name
                child_display = children_prefix + connector
                child_children_prefix = children_prefix + continuation
                out.extend(_render_tree(child_node, child_display, full_child, child_children_prefix))
        return out

    lines.append("```")
    lines.extend(_render_tree(tree, "", "", ""))
    lines.append("```")

    # Detailed folder list
    lines.append("")
    lines.append("## Folder Details")
    lines.append("")
    lines.append("| Folder | Files |")
    lines.append("|--------|-------|")
    shown: set[str] = set()
    if root_count > 0:
        lines.append(f"| (root) | {root_count} |")
        shown.add(".")
    for folder, count in sorted(folder_counts.items(), key=lambda x: -x[1]):
        if folder not in shown:
            lines.append(f"| {folder} | {count} |")
            shown.add(folder)

    return "\n".join(lines) + "\n"


def _generate_filename_stats(records: list[dict]) -> str:
    """Statistics about filenames: lengths, token counts, patterns."""
    total = len(records)
    if total == 0:
        return "# Filename Statistics\n\nNo files found.\n"

    lengths = [len(r["filename"]) for r in records]
    token_counts = [len(r["filename_tokens"]) for r in records]

    # Token frequency
    token_freq: Counter = Counter()
    for r in records:
        token_freq.update(r["filename_tokens"])

    lines = [
        "# Filename Statistics",
        "",
        f"> Total files: {total}",
        "",
        "## Name Length",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Min | {min(lengths)} chars |",
        f"| Max | {max(lengths)} chars |",
        f"| Median | {sorted(lengths)[len(lengths)//2]} chars |",
        f"| Mean | {sum(lengths)/total:.1f} chars |",
        "",
        "## Token Count per Filename",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Min | {min(token_counts)} |",
        f"| Max | {max(token_counts)} |",
        f"| Mean | {sum(token_counts)/total:.1f} |",
        "",
        "## Top 30 Filename Tokens",
        "",
        "| Token | Frequency |",
        "|-------|-----------|",
    ]
    for token, freq in token_freq.most_common(30):
        lines.append(f"| {token} | {freq} |")

    return "\n".join(lines) + "\n"


def _generate_time_distribution(records: list[dict]) -> str:
    """Monthly distribution of files by modification time."""
    month_counts: Counter = Counter()
    date_counts: Counter = Counter()
    year_counts: Counter = Counter()

    for r in records:
        month = r.get("time_month", "unknown")
        month_counts[month] += 1
        year = month[:4] if month != "unknown" else "unknown"
        year_counts[year] += 1
        sd = r.get("suspected_date")
        if sd:
            date_counts[sd[:7] if len(sd) >= 7 else sd] += 1

    lines = [
        "# Time Distribution",
        "",
        f"> Files with suspected_date extracted from filename: {sum(1 for r in records if r.get('suspected_date'))}",
        "",
        "## By Year (modified time)",
        "",
        "| Year | Files |",
        "|------|-------|",
    ]
    for year in sorted(year_counts.keys()):
        lines.append(f"| {year} | {year_counts[year]} |")

    lines.extend([
        "",
        "## By Month (modified time)",
        "",
        "| Month | Files |",
        "|-------|-------|",
    ])
    for month in sorted(month_counts.keys()):
        lines.append(f"| {month} | {month_counts[month]} |")

    if date_counts:
        lines.extend([
            "",
            "## By Suspected Date (from filename)",
            "",
            "| Date | Files |",
            "|------|-------|",
        ])
        for date in sorted(date_counts.keys()):
            lines.append(f"| {date} | {date_counts[date]} |")

    return "\n".join(lines) + "\n"


def _generate_extension_distribution(records: list[dict]) -> str:
    """Extension distribution statistics."""
    ext_counts: Counter = Counter()
    ext_sizes: dict[str, int] = defaultdict(int)

    for r in records:
        ext = r["extension"]
        ext_counts[ext] += 1
        ext_sizes[ext] += r["size"]

    total_files = len(records)
    total_size = sum(r["size"] for r in records)

    lines = [
        "# Extension Distribution",
        "",
        f"> Total files: {total_files}",
        f"> Total size: {_fmt_size(total_size)}",
        "",
        "| Extension | Count | % | Total Size |",
        "|-----------|-------|---|------------|",
    ]
    for ext, count in ext_counts.most_common():
        pct = count / total_files * 100 if total_files > 0 else 0
        sz = _fmt_size(ext_sizes[ext])
        lines.append(f"| {ext or '(none)'} | {count} | {pct:.1f}% | {sz} |")

    return "\n".join(lines) + "\n"


def _generate_scan_report(
    records: list[dict],
    root_dirs: list[str],
    include_exts: set[str],
    exclude_patterns: dict,
    recursive: bool,
    elapsed_ms: float,
) -> str:
    """Main scan report summarizing everything."""
    total_files = len(records)
    total_folders = len(set(r["parent_folder"] for r in records))
    total_size = sum(r["size"] for r in records)
    depth_counts = Counter(r["depth"] for r in records)

    # Largest directories
    folder_sizes: dict[str, int] = defaultdict(int)
    folder_counts: dict[str, int] = defaultdict(int)
    for r in records:
        folder_counts[r["parent_folder"]] += 1
        folder_sizes[r["parent_folder"]] += r["size"]

    ext_counts = Counter(r["extension"] for r in records)

    lines = [
        "# Scan Report — File Inventory",
        "",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> Scan duration: {elapsed_ms/1000:.1f}s",
        "",
        "## Scan Configuration",
        "",
        f"| Setting | Value |",
        f"|---------|-------|",
        f"| Root directories | {', '.join(root_dirs)} |",
        f"| Include extensions | {', '.join(sorted(include_exts))} |",
        f"| Exclude dir patterns | {', '.join(exclude_patterns.get('dirs', [])) or '(none)'} |",
        f"| Exclude file patterns | {', '.join(exclude_patterns.get('files', [])) or '(none)'} |",
        f"| Recursive | {recursive} |",
        f"| LLM calls | 0 |",
        f"| File content reads | 0 |",
        f"| Files modified/deleted | 0 |",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total files scanned | {total_files} |",
        f"| Unique folders | {total_folders} |",
        f"| Total size | {_fmt_size(total_size)} |",
        f"| Max depth | {max(depth_counts.keys()) if depth_counts else 0} |",
        f"| Files with suspected date | {sum(1 for r in records if r.get('suspected_date'))} |",
        "",
        "## Top 10 Largest Directories (by file count)",
        "",
        "| Directory | Files | Size |",
        "|-----------|-------|------|",
    ]
    for folder, count in sorted(folder_counts.items(), key=lambda x: -x[1])[:10]:
        lines.append(f"| {folder} | {count} | {_fmt_size(folder_sizes[folder])} |")

    lines.extend([
        "",
        "## Top Extensions",
        "",
        "| Extension | Count |",
        "|-----------|-------|",
    ])
    for ext, count in ext_counts.most_common(10):
        lines.append(f"| {ext or '(none)'} | {count} |")

    lines.extend([
        "",
        "## Depth Distribution",
        "",
        "| Depth | Files |",
        "|-------|-------|",
    ])
    for depth in sorted(depth_counts.keys()):
        lines.append(f"| {depth} | {depth_counts[depth]} |")

    lines.extend([
        "",
        "## Output Files",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| file_inventory.csv | Full inventory in CSV format |",
        "| file_inventory.jsonl | Full inventory in JSONL format |",
        "| folder_tree.md | Visual directory tree |",
        "| filename_stats.md | Token frequency, length statistics |",
        "| time_distribution.md | Monthly/yearly file distribution |",
        "| extension_distribution.md | Extension counts and sizes |",
        "| scan_report.md | This file |",
    ])

    return "\n".join(lines) + "\n"


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes/1_000_000_000:.1f} GB"
    if size_bytes >= 1_000_000:
        return f"{size_bytes/1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes/1_000:.1f} KB"
    return f"{size_bytes} B"


# ──────────────────────────── main entry ────────────────────────────

CSV_FIELDS = [
    "file_id", "path", "filename", "extension", "parent_folder",
    "size", "created_time", "modified_time", "time_month", "depth",
    "filename_tokens", "path_tokens", "suspected_date", "suspected_topic_keywords",
]


def scan_filenames(
    config_path: str,
    output_dir: str = "./kb_out/file_inventory",
    recursive: bool = True,
    max_files: Optional[int] = None,
    root_dirs: Optional[List[str]] = None,
) -> dict:
    """Main entry: scan filenames and generate all inventory reports. Returns summary dict.

    When root_dirs is provided, it overrides the scanner.root_dirs from config.yaml.
    """
    import yaml

    t0 = time.perf_counter()

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    sc = cfg.get("scanner", {})
    if root_dirs is None:
        root_dirs = [norm_abs(d) for d in sc.get("root_dirs", [])]
    else:
        root_dirs = [norm_abs(d) for d in root_dirs]
    include_exts = {e.lower() for e in sc.get("include_extensions", [".docx", ".doc", ".md", ".txt"])}
    # Add pdf if in config; if not, respect the configured list
    exclude_dir_globs = list(sc.get("exclude_dir_globs", []))
    exclude_file_globs = list(sc.get("exclude_file_globs", []))

    # Auto-exclude our own output + venv + cache dirs
    auto_exclude = ["*/kb_tool/kb_out*", "*/kb_out*", "*/.venv*", "*/__pycache__*",
                    "*/node_modules*", "*/.git*", "*/file_inventory*"]
    exclude_dir_globs = list(exclude_dir_globs) + auto_exclude

    # Collect records
    records = list(_iter_files(
        root_dirs=root_dirs,
        include_exts=include_exts,
        exclude_dir_globs=exclude_dir_globs,
        exclude_file_globs=exclude_file_globs,
        recursive=recursive,
        max_files=max_files,
    ))

    # Prepare output directory
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. CSV
    csv_path = out_path / "file_inventory.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            row = {k: r.get(k) for k in CSV_FIELDS}
            # Flatten lists for CSV
            row["filename_tokens"] = "|".join(r.get("filename_tokens", []))
            row["path_tokens"] = "|".join(r.get("path_tokens", []))
            row["suspected_topic_keywords"] = "|".join(r.get("suspected_topic_keywords", []))
            writer.writerow(row)

    # 2. JSONL
    jsonl_path = out_path / "file_inventory.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for r in records:
            jf.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 3-7: Markdown reports
    reports: dict[str, str] = {
        "folder_tree.md": _generate_folder_tree(records, root_dirs),
        "filename_stats.md": _generate_filename_stats(records),
        "time_distribution.md": _generate_time_distribution(records),
        "extension_distribution.md": _generate_extension_distribution(records),
    }

    for filename, content in reports.items():
        (out_path / filename).write_text(content, encoding="utf-8")

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # scan_report.md (generated last so it can reference all outputs)
    scan_report = _generate_scan_report(
        records=records,
        root_dirs=root_dirs,
        include_exts=include_exts,
        exclude_patterns={"dirs": exclude_dir_globs, "files": exclude_file_globs},
        recursive=recursive,
        elapsed_ms=elapsed_ms,
    )
    (out_path / "scan_report.md").write_text(scan_report, encoding="utf-8")

    # Summary
    total_folders = len(set(r["parent_folder"] for r in records))
    ext_counts = Counter(r["extension"] for r in records)

    return {
        "total_files": len(records),
        "total_folders": total_folders,
        "total_size_bytes": sum(r["size"] for r in records),
        "extensions": dict(ext_counts.most_common()),
        "recursive": recursive,
        "elapsed_ms": elapsed_ms,
        "output_dir": str(out_path),
        "output_files": [
            str(csv_path),
            str(jsonl_path),
            str(out_path / "folder_tree.md"),
            str(out_path / "filename_stats.md"),
            str(out_path / "time_distribution.md"),
            str(out_path / "extension_distribution.md"),
            str(out_path / "scan_report.md"),
        ],
    }
