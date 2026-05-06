"""
KB Console v2 — Word-first 本地知识库管理控制台
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from ui_helpers import (
    AppPaths,
    copy_to_clipboard,
    ensure_dir,
    get_available_folders,
    get_available_months,
    get_dashboard_enriched,
    get_dashboard_state,
    group_reports,
    load_app_paths,
    path_is_under,
    read_markdown,
    recent_markdown_files,
    render_task_progress,
    run_cli_live_async,
    run_cli_sync,
    safe_startfile,
    save_config,
    system_health_check,
    test_deepseek_connection,
    estimate_scope_tokens,
)

st.set_page_config(page_title="KB Console", layout="wide", initial_sidebar_state="expanded")

# ── Init ──
cfg, paths = load_app_paths()
if str(paths.kb_tool_dir) not in sys.path:
    sys.path.insert(0, str(paths.kb_tool_dir))

from workflow_mainline import find_idea, token_budget as trading_token_budget

ALLOWED_OPEN_ROOTS = [paths.docs_dir, paths.reports_dir, paths.bundles_dir, paths.logs_dir, paths.kb_out_dir]

# ── Helpers ──

def show_path_actions(path_str: str, label_prefix: str = "") -> None:
    if not path_str:
        return
    p = Path(path_str)
    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        if st.button(f"📂 打开文件夹", key=f"open_{label_prefix}_{hash(path_str)}"):
            ok, msg = safe_startfile(p.parent if p.is_file() else p, ALLOWED_OPEN_ROOTS)
            if not ok:
                st.warning(msg)
    with c2:
        if st.button(f"📋 复制路径", key=f"copy_{label_prefix}_{hash(path_str)}"):
            ok, msg = copy_to_clipboard(path_str)
            st.toast("已复制到剪贴板" if ok else f"复制失败: {msg}")
    with c3:
        st.text_input("路径", value=path_str, key=f"path_box_{label_prefix}_{hash(path_str)}", label_visibility="collapsed")


def preview_markdown(path_str: str, title: str = "报告预览", expanded: bool = False) -> None:
    if not path_str:
        return
    p = Path(path_str)
    if not p.exists():
        st.warning(f"文件不存在: {path_str}")
        return
    if not path_is_under(p, ALLOWED_OPEN_ROOTS):
        st.warning(f"路径不在允许范围内: {path_str}")
        return
    with st.expander(title, expanded=expanded):
        st.markdown(read_markdown(p))


def show_error(msg: str, exc: Exception | None = None):
    st.error(msg)
    if exc:
        with st.expander("详细信息"):
            st.exception(exc)


# ═══════════════════════════════════════════════════════════════
# Sidebar Navigation
# ═══════════════════════════════════════════════════════════════

st.sidebar.title("KB Console")
st.sidebar.caption("Word-first 本地知识库")

nav = st.sidebar.radio(
    "导航",
    [
        "📊 总览 (Dashboard)",
        "🔍 查找 (Find)",
        "📚 Wiki 阅读",
        "📥 整理与维护",
        "📈 自定义分析 (Custom Analysis)",
        "📋 报告中心 (Reports)",
        "🧭 初始化向导 (Setup Wizard)",
        "⚙️ 设置 (Settings)",
    ],
)

# Sub-navigation
sub_page = None
if "整理与维护" in nav:
    sub_page = st.sidebar.radio(
        "子页面",
        ["每周整理 (Weekly Organize)", "转写压缩 (Transcript Compress)"],
        label_visibility="collapsed",
        key="organize_sub",
    )
if "自定义分析" in nav:
    sub_page = st.sidebar.radio(
        "子页面",
        ["主题分析 (Topic Analyze)", "文件夹分析 (Folder Analyze)", "个人画像 (Profile)"],
        label_visibility="collapsed",
        key="analysis_sub",
    )

st.sidebar.divider()

# ── Persistent background task monitor (visible on all pages) ──
import re as _re
_running_tasks = []
for key in sorted(st.session_state.keys()):
    if key.endswith("_running") and st.session_state[key]:
        task_id = key[: -len("_running")]
        title = st.session_state.get(f"{task_id}_title", task_id)
        phase = st.session_state.get(f"{task_id}_phase", "")
        prog = st.session_state.get(f"{task_id}_progress", 0)
        lines = st.session_state.get(f"{task_id}_lines", [])
        # Parse real progress from JSON lines
        for line in reversed(lines):
            try:
                import json as _j
                obj = _j.loads(line)
                if isinstance(obj, dict) and "progress" in obj:
                    pg = obj["progress"]
                    if isinstance(pg, dict) and "current" in pg and "total" in pg and pg["total"] > 0:
                        prog = int(pg["current"] / pg["total"] * 100)
            except Exception:
                pass
        _running_tasks.append((task_id, title, phase, prog))

if _running_tasks:
    st.sidebar.subheader("🔧 后台任务")
    for task_id, title, phase, prog in _running_tasks:
        icon = {"starting": "⏳", "running": "🔄"}.get(phase, "⏳")
        st.sidebar.caption(f"{icon} {title}")
        st.sidebar.progress(prog / 100 if prog > 0 else 0.05)

# Show recently completed tasks in sidebar
_done_tasks = []
for key in sorted(st.session_state.keys(), reverse=True):
    if key.endswith("_phase") and st.session_state[key] == "done" and not st.session_state.get(key.replace("_phase", "_dismissed")):
        task_id = key[: -len("_phase")]
        title = st.session_state.get(f"{task_id}_title", "")
        result = st.session_state.get(f"{task_id}_result")
        report = result.get("report") if isinstance(result, dict) else None
        _done_tasks.append((task_id, title, report))

if _done_tasks:
    st.sidebar.divider()
    st.sidebar.caption("最近完成:")
    for task_id, title, report in _done_tasks[:3]:
        dismiss_key = f"dismiss_{task_id}"
        c1, c2 = st.sidebar.columns([4, 1])
        with c1:
            st.sidebar.caption(f"✅ {title}")
        with c2:
            if st.sidebar.button("✕", key=dismiss_key):
                st.session_state[f"{task_id}_dismissed"] = True
                st.rerun()

# Check for newly-completed tasks (fire toast even on other pages)
for key in sorted(st.session_state.keys()):
    if key.endswith("_phase") and st.session_state[key] in ("done", "failed") and not st.session_state.get(key.replace("_phase", "_notified")):
        task_id = key[: -len("_phase")]
        title = st.session_state.get(f"{task_id}_title", "")
        from ui_helpers import _beep
        if st.session_state[key] == "done":
            st.toast(f"✅ {title} 已完成！", icon="✅")
            _beep(880, 0.2)
        else:
            st.toast(f"❌ {title} 失败", icon="❌")
            _beep(220, 0.4)
        st.session_state[f"{task_id}_notified"] = True

st.sidebar.caption(f"状态正常 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ═══════════════════════════════════════════════════════════════
# 📊 总览 (Dashboard)
# ═══════════════════════════════════════════════════════════════

if "总览" in nav:
    st.header("📊 总览 (Dashboard)")
    st.caption("知识库整体状态：文档规模、分类分布、Token 预算和最近活动")

    try:
        state = get_dashboard_enriched(paths)
    except Exception as e:
        show_error("获取 Dashboard 数据失败", e)
        st.stop()

    # KPI Cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True):
            st.metric("文档总数", f"{state.get('docs_count', 0)}")
            st.caption(f"待审核: {state.get('pending_review', 0)} 个")
    with c2:
        with st.container(border=True):
            st.metric("总字数（去空白）", f"{state.get('total_chars', 0):,}")
            st.caption(f"估算 {state.get('total_chars', 0)//2.2:,.0f} ~ {state.get('total_chars', 0)//1.2:,.0f} tokens")
    with c3:
        top_cat = state.get("top_category", {})
        with st.container(border=True):
            st.metric("最大分类", top_cat.get("name", "N/A"))
            st.caption(f"占总字数的 {top_cat.get('pct', 0)}%")
    with c4:
        with st.container(border=True):
            st.metric("最近整理", state.get("latest_weekly_time") or "暂无")
            st.caption(f"DB: {'正常' if state.get('db_exists') else '不存在'}")

    st.divider()

    # Charts
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("每月写作量趋势")
        trend = state.get("monthly_trend", [])
        if trend:
            df_trend = pd.DataFrame(trend)
            df_trend["月份"] = df_trend["month"]
            df_trend["字数（千）"] = (df_trend["chars"] // 1000).astype(int)
            st.bar_chart(df_trend.set_index("月份")[["files", "字数（千）"]], height=280)
        else:
            st.info("暂无月度数据")

    with c2:
        st.subheader("分类分布")
        cat_dist = state.get("category_dist", [])
        if cat_dist:
            df_cat = pd.DataFrame(cat_dist)
            st.bar_chart(pd.DataFrame({"分类": [d["category"] for d in cat_dist], "字数": [d["chars"] for d in cat_dist]}).set_index("分类"), height=280)
        else:
            st.info("暂无分类数据")

    # Token forecast
    fc = state.get("token_forecast")
    if fc:
        st.divider()
        st.subheader("Token 预算预测（1M 上下文）")
        st.caption(
            f"当前 ~{fc['current_high']:,} tokens（高估），月均增量 ~{fc['monthly_avg_high']:,} tokens，"
            f"预计 **{fc['months_to_1m']} 个月后** 达到 1,000,000 token 上限"
        )

    st.divider()

    # Quick actions
    st.subheader("快捷操作")
    ca1, ca2, ca3 = st.columns(3)
    with ca1:
        with st.container(border=True):
            st.write("**🔄 本周整理**")
            st.caption("扫描新文件 → AI 分类 → 生成周报")
    with ca2:
        with st.container(border=True):
            st.write("**📈 自定义分析**")
            st.caption("选文件夹+时间范围 → LLM 深度分析")
    with ca3:
        with st.container(border=True):
            st.write("**🔍 查找想法**")
            st.caption("关键词或自然语言搜索")

    # Recent reports
    st.divider()
    st.subheader("最近报告")
    rpts = state.get("recent_reports", [])
    if rpts:
        df_rpt = pd.DataFrame([
            {"报告": str(Path(r).relative_to(paths.reports_dir)) if paths.reports_dir in Path(r).parents else str(r),
             "时间": time.strftime("%Y-%m-%d %H:%M", time.localtime(Path(r).stat().st_mtime)) if Path(r).exists() else "N/A"}
            for r in rpts
        ])
        st.dataframe(df_rpt, use_container_width=True, hide_index=True)
    else:
        st.info("暂无报告")

    if state.get("latest_weekly_report"):
        with st.expander("📄 最近周报预览"):
            st.markdown(read_markdown(Path(state["latest_weekly_report"])))

# ═══════════════════════════════════════════════════════════════
# 📚 Wiki 阅读
# ═══════════════════════════════════════════════════════════════

elif "Wiki" in nav:
    st.header("📚 Wiki 阅读")
    st.caption("AI 自动生成的知识页面——浏览主题、分类和项目，每一条结论都有 source 引用。")

    wiki_dir = Path(paths.kb_out_dir) / "deep_custom_kb" / "session_001" / "wiki"
    page_index_path = wiki_dir / "page_index.json"

    if not page_index_path.exists():
        st.info("Wiki 页面尚未生成。请先运行: ")
    else:
        import json as _json
        with open(page_index_path, encoding="utf-8") as f:
            all_pages = _json.load(f)

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Wiki 页面", len(all_pages))
            by_type = {}
            for p in all_pages:
                t = p.get("type", "other"); by_type[t] = by_type.get(t, 0) + 1
            with c2: st.metric("分类页", by_type.get("category", 0))
            with c3: st.metric("主题页", by_type.get("topic", 0))
            total_docs = sum(p.get("doc_count", 0) for p in all_pages)
            with c4: st.metric("覆盖文档", total_docs)

        st.divider()
        col_left, col_right = st.columns([1, 3])
        with col_left:
            st.subheader("页面索引")
            page_map = {}
            for p in all_pages:
                t = p.get("type", "other")
                page_map.setdefault(t, []).append(p)
            for pt, label in [("category", "📁 分类"), ("topic", "🏷️ 主题"), ("project", "📂 项目")]:
                pages = page_map.get(pt, [])
                if not pages: continue
                with st.expander(f"{label} ({len(pages)})", expanded=(pt=="category")):
                    for p in sorted(pages, key=lambda x: -x.get("doc_count", 0)):
                        if st.button(f"{p['title']} ({p.get('doc_count',0)}篇)", key=f"wiki_{pt}_{p['title']}", use_container_width=True):
                            st.session_state["wiki_selected"] = p["path"]

        with col_right:
            selected = st.session_state.get("wiki_selected", "")
            if selected and Path(selected).exists():
                from ui_helpers import read_markdown
                md = read_markdown(Path(selected))
                # Split body and evidence section for clean rendering
                if "## 证据文件" in md:
                    body_part, evidence_part = md.split("## 证据文件", 1)
                    st.markdown(body_part)
                    # Clickable source files
                    st.divider()
                    st.subheader("📎 源文件")
                    import re as _re
                    source_pattern = _re.compile(r'\*\*\[#(\d+)\]\*\*  \((.+?)\)')
                    sources = source_pattern.findall(evidence_part)
                    if sources:
                        for num, fpath, month in sources[:20]:
                            p = Path(fpath)
                            c1, c2, c3 = st.columns([4, 1, 1])
                            with c1:
                                st.caption(f"**[#{num}]** {p.name} ({month})")
                            with c2:
                                st.caption(p.parent.name if p.parent else "")
                            with c3:
                                if p.exists():
                                    if st.button("📂 打开", key=f"wiki_src_{num}_{hash(fpath)}", use_container_width=True):
                                        ok, msg = safe_startfile(p, ALLOWED_OPEN_ROOTS)
                                        if not ok: st.warning(msg)
                    else:
                        st.caption(evidence_part[:500])
                else:
                    st.markdown(md)
            elif selected:
                st.warning(f"页面文件不存在: {selected}")
            else:
                st.info("← 从左侧选择一个 Wiki 页面阅读")

        st.divider()
        st.caption("Wiki 页面由 AI 自动生成，每条观点附带 source 引用可追溯到原始文件。")

# 🔍 查找 (Find)
# ═══════════════════════════════════════════════════════════════

elif "查找" in nav:
    st.header("🔍 查找 (Find)")
    st.caption("在知识库中找到某个想法出现的位置、演化过程和相关材料")

    search_mode = st.radio(
        "搜索模式",
        ["⚡ 快速搜索（关键词，毫秒级，无 LLM 消耗）",
         "📚 Wiki 优先（先查 AI 知识页，不命中自动回退）",
         "🧠 智能搜索（AI 深度查找，10-30 秒，调用 LLM）"],
        horizontal=True,
        key="search_mode",
    )
    is_smart = "智能" in search_mode
    is_wiki = "Wiki" in search_mode

    docs_folders = sorted([f["name"] for f in get_available_folders(paths)]) if paths.docs_dir.exists() else []
    available_months = get_available_months(paths)

    c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
    with c1:
        query = st.text_input(
            "搜索问题 *",
            placeholder="例：不等回调的教训" if is_smart else "例：止损 回调 执行力",
            key="find_query",
        )
    with c2:
        category = st.selectbox("分类（可选）", ["全部"] + docs_folders)
    with c3:
        month_options = ["全部"] + available_months if available_months else ["全部"]
        month = st.selectbox("时间范围（可选）", month_options)
    with c4:
        st.write("")
        search_btn = st.button("🔍 搜索", use_container_width=True)

    st.divider()

    if search_btn and query:
        if is_wiki:
            # Wiki-first search
            import subprocess, json as _json
            wiki_kb = str(Path(paths.kb_out_dir) / "deep_custom_kb" / "session_001")
            try:
                result = _json.loads(subprocess.check_output(
                    ["python", str(paths.kb_tool_dir / "main.py"), "wiki-route",
                     "--query", query, "--kb", wiki_kb],
                    text=True, timeout=15
                ))
                pages = result.get("selected_pages", [])
                if pages and result.get("confidence", 0) >= 0.5:
                    st.success(f"Wiki 命中 {len(pages)} 个页面（置信度 {result['confidence']:.0%}）")
                    for p_path in pages[:3]:
                        if Path(p_path).exists():
                            from ui_helpers import read_markdown
                            st.markdown(read_markdown(Path(p_path))[:5000])
                    if result.get("fallback_needed"):
                        st.info(f"建议同时参考快速搜索结果: {result.get('fallback_reason','')}")
                else:
                    st.info("Wiki 未命中，自动回退到快速搜索...")
                    is_wiki = False
            except Exception:
                st.info("Wiki 路由暂不可用，自动回退到快速搜索...")
                is_wiki = False

        if is_smart:
            task_id = run_cli_live_async(paths, ["agent", "--query", query], "智能搜索")
            st.session_state["smart_search_task"] = task_id

    # Render smart search progress (persists across reruns)
    smart_task = st.session_state.get("smart_search_task")
    if smart_task and is_smart:
        running = render_task_progress(smart_task)
        if not running:
            result = st.session_state.get(f"{smart_task}_result") or {}
            if result:
                st.divider()
                st.info("智能搜索使用 Agent 多轮调用知识库工具完成。结果汇总：")
                answer = result.get("answer") or result.get("output") or json.dumps(result, ensure_ascii=False, indent=2)
                st.markdown(answer[:5000] if len(answer) > 5000 else answer)

    if search_btn and query:
        if is_smart:
            st.divider()
            st.caption("同时可参考快速搜索结果：")
        elif is_wiki:
            st.divider()
            st.caption("同时可参考快速搜索结果：")
            try:
                fast = find_idea(cfg, query=query, month_start=month if month != "全部" else None, month_end=month if month != "全部" else None, category=category if category != "全部" else None)
                items = fast.get("items", [])
                if items:
                    for i, item in enumerate(items[:5]):
                        with st.expander(f"{Path(item.get('docs_path','')).name} | {item.get('category','')} | {item.get('month','')}"):
                            st.write(item.get("snippet", ""))
            except Exception as e:
                st.warning(f"快速搜索不可用: {e}")
        else:
            # Fast search
            start = time.time()
            try:
                result = find_idea(
                    cfg,
                    query=query,
                    month_start=month if month != "全部" else None,
                    month_end=month if month != "全部" else None,
                    category=category if category != "全部" else None,
                )
                elapsed = time.time() - start
                items = result.get("items", [])

                if items:
                    st.success(f"找到 {len(items)} 条结果（{elapsed*1000:.0f}ms）")
                    # Table
                    df = pd.DataFrame([{
                        "文件名": Path(it.get("docs_path", "")).name,
                        "分类": it.get("category", ""),
                        "月份": it.get("month", ""),
                        "匹配方式": it.get("reason", ""),
                    } for it in items])
                    st.dataframe(df, use_container_width=True, hide_index=True)

                    # Detail expanders
                    for i, it in enumerate(items):
                        with st.expander(f"{Path(it.get('docs_path', '')).name} | {it.get('category', '')} | {it.get('month', '')}"):
                            st.markdown(f"> {it.get('snippet', '')}")
                            p = Path(it.get("docs_path", ""))
                            if p.exists():
                                st.button("📂 打开文件", key=f"find_open_{i}", use_container_width=True, on_click=lambda pp=p: safe_startfile(pp, ALLOWED_OPEN_ROOTS))
                else:
                    st.info("未找到匹配内容。试试换个关键词？或使用 🧠 智能搜索获得更全面的结果。")
            except Exception as e:
                show_error("搜索失败", e)
    elif search_btn:
        st.warning("请输入搜索关键词")

# ═══════════════════════════════════════════════════════════════
# 📥 整理与维护
# ═══════════════════════════════════════════════════════════════

elif nav == "📥 整理与维护" and sub_page and "每周整理" in sub_page:
    st.header("📥 每周整理 (Weekly Organize)")
    st.caption("选择源目录 → 扫描新文件 → AI 自动分类 → 写入知识库 → 生成周报")

    import subprocess as _sp, os as _os

    ext_list = cfg.get("scanner", {}).get("include_extensions", [".docx", ".doc", ".md", ".txt"])

    def _count_files(folder: str, recursive: bool) -> int:
        p = Path(folder)
        if not p.exists():
            return 0
        if recursive:
            return sum(1 for f in p.rglob("*") if f.is_file() and f.suffix.lower() in ext_list)
        return sum(1 for f in p.iterdir() if f.is_file() and f.suffix.lower() in ext_list)

    def _pick_folder() -> str | None:
        """Open Windows folder picker dialog, return selected path or None."""
        try:
            ps_cmd = (
                'Add-Type -AssemblyName System.Windows.Forms; '
                '$f = New-Object System.Windows.Forms.FolderBrowserDialog; '
                '$f.Description = "选择要扫描的文件夹"; '
                'if ($f.ShowDialog() -eq "OK") { $f.SelectedPath } else { "" }'
            )
            r = _sp.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
            path = r.stdout.strip()
            return path if path else None
        except Exception:
            return None

    # Init session state for folder list
    if "wo_folders" not in st.session_state:
        desktop = str(Path(_os.path.expanduser("~")) / "Desktop")
        st.session_state.wo_folders = [{"path": desktop, "recursive": False}]

    def _add_folder(fpath: str, recursive: bool):
        fpath = fpath.strip()
        if fpath and Path(fpath).exists() and fpath not in [f["path"] for f in st.session_state.wo_folders]:
            st.session_state.wo_folders.append({"path": fpath, "recursive": recursive})

    # ── Add folder: text input + browse button ──
    st.subheader("扫描目录")
    c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
    with c1:
        new_path = st.text_input("文件夹路径", placeholder="输入路径或点击「浏览」选择...", key="wo_new_path")
    with c2:
        new_rec = st.checkbox("递归子文件夹", value=False, key="wo_new_rec")
    with c3:
        st.write("")
        if st.button("📂 浏览...", use_container_width=True, key="wo_browse"):
            picked = _pick_folder()
            if picked:
                _add_folder(picked, new_rec)
                st.rerun()
    with c4:
        st.write("")
        if st.button("➕ 添加", use_container_width=True, key="wo_add"):
            _add_folder(new_path, new_rec)
            st.rerun()

    # ── Current folder list ──
    selected_dirs = []
    total_preview = 0
    remove_idx = None

    for i, fd in enumerate(st.session_state.wo_folders):
        cnt = _count_files(fd["path"], fd["recursive"])
        total_preview += cnt
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        with c1:
            st.caption(f"📁 {fd['path']}  ({cnt} 个文件)")
        with c2:
            fd["recursive"] = st.checkbox("递归", value=fd["recursive"], key=f"wo_rec_{i}")
        with c3:
            if st.button("🗑 移除", key=f"wo_rm_{i}"):
                remove_idx = i
        selected_dirs.append(fd["path"])

    if remove_idx is not None:
        st.session_state.wo_folders.pop(remove_idx)
        st.rerun()

    # ── Quick-select expander ──
    with st.expander("⚡ 从桌面子文件夹快速添加", expanded=False):
        desktop = Path(_os.path.expanduser("~")) / "Desktop"
        desktop_folders = sorted([str(p) for p in desktop.iterdir() if p.is_dir() and not p.name.startswith(".")])
        cols_per_row = 2
        for i in range(0, len(desktop_folders), cols_per_row):
            batch = desktop_folders[i:i+cols_per_row]
            row_cols = st.columns(cols_per_row)
            for j, fp in enumerate(batch):
                nm = Path(fp).name
                with row_cols[j]:
                    if st.button(f"📁 {nm}", key=f"wo_quick_{i+j}", use_container_width=True):
                        if fp not in [f["path"] for f in st.session_state.wo_folders]:
                            st.session_state.wo_folders.append({"path": fp, "recursive": False})
                            st.rerun()

    st.divider()
    st.metric("预计扫描文件总数", str(total_preview))

    c1, c2 = st.columns(2)
    with c1:
        max_files = st.number_input("最多处理文件数（0=全部）", min_value=0, max_value=5000, value=min(200, total_preview) if total_preview > 0 else 0, key="wo_max_files")
    with c2:
        concurrency = st.selectbox("LLM 并发数", [1, 2, 4, 6, 8], index=2, key="wo_concurrency")

    st.divider()

    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        dry_run_btn = st.button("🔍 试运行 (Dry Run)", use_container_width=True)
    with c2:
        confirm = st.checkbox("确认调用 LLM", key="wo_confirm")
        real_btn = st.button("▶️ 正式整理", disabled=not confirm or not selected_dirs, use_container_width=True)

    st.divider()

    # Handle task
    task_id = st.session_state.get("wo_task_id", "")
    if (dry_run_btn or (real_btn and confirm)) and selected_dirs:
        dirs = [f["path"] for f in st.session_state.wo_folders]
        all_rec = all(f["recursive"] for f in st.session_state.wo_folders)
        cli_args = ["weekly-organize", "--source-dirs", ",".join(dirs)]
        if not all_rec:
            cli_args.append("--non-recursive")
        if dry_run_btn:
            cli_args += ["--dry-run"]
        if max_files > 0:
            cli_args += ["--max-files", str(max_files)]

        t = "每周整理 (Dry Run)" if dry_run_btn else "每周整理（正式）"
        task_id = run_cli_live_async(paths, cli_args, t)
        st.session_state["wo_task_id"] = task_id

    if task_id:
        render_task_progress(task_id)

    result = st.session_state.get(f"{task_id}_result") if task_id else None
    if result:
        st.json(result)
        weekly_report = result.get("weekly_report") if isinstance(result, dict) else None
        if weekly_report:
            show_path_actions(weekly_report, "weekly")
            preview_markdown(weekly_report, "周报预览")

elif nav == "📥 整理与维护" and sub_page and "转写压缩" in sub_page:
    st.header("📥 转写压缩 (Transcript Compress)")
    st.caption("把课程/会议录音转写文件（通常数万字，含大量口语和重复）用 LLM 压缩为结构化笔记。")

    with st.expander("📖 了解更多：为什么要压缩？"):
        st.markdown("""
        **问题：** 录音转写文件往往 2-3 万字，口语化严重（语气词、重复、跑题闲聊占 60%+）。

        **后果：** 不压缩的话，做分析时大量噪音淹没有效信息。

        **解决方案：** 用 LLM 提取：交易规则、核心概念、买卖点条件、老师纠错、用户提问
        """)

    confirm_c = st.checkbox("确认调用 LLM 执行压缩（会产生 API 费用）", key="cc_confirm")
    if st.button("📝 执行压缩", disabled=not confirm_c):
        task_id = run_cli_live_async(paths, ["compact-course-transcripts"], "转写压缩")
        st.session_state["cc_task_id"] = task_id

    task_id = st.session_state.get("cc_task_id", "")
    if task_id:
        render_task_progress(task_id)

# ═══════════════════════════════════════════════════════════════
# 📈 自定义分析 (Custom Analysis)
# ═══════════════════════════════════════════════════════════════

elif nav == "📈 自定义分析 (Custom Analysis)" and sub_page and "主题分析" in sub_page:
    st.header("📈 主题分析 (Topic Analyze)")
    st.caption("选择文件夹范围 + 时间范围 + 分析主题，LLM 深度分析特定时间段内的特定主题。")

    ta_mode = st.radio("分析模式",
        ["📄 原文优先（直接读文件分析）",
         "📚 Wiki 优先（先读 Wiki 知识页）"],
        horizontal=True, key="ta_mode")

    # Presets
    st.write("**预设模板（一键填充）：**")
    p1, p2, p3 = st.columns(3)
    with p1:
        if st.button("📊 交易系统分析", use_container_width=True, key="preset_trading"):
            st.session_state.ta_folders = ["交易系统与方法论", "交易复盘", "交易记录", "交易心理与情绪"]
            st.session_state.ta_topic = "交易系统变化与执行问题"
    with p2:
        if st.button("🤖 AI 项目分析", use_container_width=True, key="preset_ai"):
            st.session_state.ta_folders = ["AI与工具化"]
            st.session_state.ta_topic = "AI 技术方向与研究进展"
    with p3:
        if st.button("✏️ 自定义", use_container_width=True, key="preset_custom"):
            st.session_state.ta_folders = []
            st.session_state.ta_topic = ""

    st.divider()

    folders_all = [f["name"] for f in get_available_folders(paths)]
    months_all = get_available_months(paths)

    c1, c2 = st.columns(2)
    with c1:
        start_month = st.selectbox("开始月份 *", ["全部"] + months_all, key="ta_start")
        end_month = st.selectbox("结束月份 *", ["全部"] + months_all, key="ta_end")
    with c2:
        topic = st.text_input("分析主题 *", placeholder="例：止损执行的变化", key="ta_topic")
        selected_folders = st.multiselect(
            "数据来源（文件夹）*",
            folders_all,
            default=st.session_state.get("ta_folders", [f for f in folders_all if "交易" in f]),
            key="ta_folders",
        )

    if selected_folders and topic:
        est = estimate_scope_tokens(
            paths, selected_folders,
            start_month if start_month != "全部" else None,
            end_month if end_month != "全部" else None,
        )
        with st.container(border=True):
            st.write("**📊 数据预览**")
            c1, c2 = st.columns(2)
            with c1:
                st.metric("选中文件", f"{est['document_count']} 个")
                st.metric("估算 Tokens", f"{est['token_low']:,} ~ {est['token_high']:,}")
            with c2:
                if est["fits_1m"]:
                    st.success("✅ 可一次性分析")
                else:
                    st.warning(f"⚠️ 需分批分析（策略: {est['strategy']}）")

    confirm_ta = st.checkbox("确认调用 LLM 生成分析报告", key="ta_confirm")
    if st.button("▶️ 生成分析报告", disabled=not confirm_ta or not selected_folders or not topic):
        cli_args = ["trading-analyze", "--topic", topic]
        if selected_folders:
            cli_args += ["--categories", ",".join(selected_folders)]
        task_id = run_cli_live_async(paths, cli_args, f"主题分析: {topic[:30]}")
        st.session_state["ta_task_id"] = task_id

    task_id = st.session_state.get("ta_task_id", "")
    if task_id:
        render_task_progress(task_id)

elif nav == "📈 自定义分析 (Custom Analysis)" and sub_page and "文件夹分析" in sub_page:
    st.header("📈 文件夹分析 (Folder Analyze)")
    st.caption("对某个文件夹全文深度分析——先打包看数据量，再调用 LLM 回答具体问题。")

    fa_path_mode = st.radio("分析路径",
        ["📦 Bundle 深度分析（打包全文，逐步深入）",
         "📚 Folder Wiki（基于该文件夹的 Wiki 知识页）"],
        horizontal=True, key="fa_path_mode")

    with st.expander("📖 什么是 Bundle？为什么需要两步？"):
        st.markdown("""
        **Bundle（知识包）** = 把你选中文件夹内所有文档内容打包成一个 Markdown 文件。

        **为什么要先看 Bundle？**
        1. **知道要传多少数据**：如果 300K tokens → 一次性分析；1.5M tokens → 分批
        2. **验证数据范围**：文件清单确认有没有遗漏或误包含
        3. **Bundle 不用 LLM**，生成极快（几秒），零费用

        **什么时候直接分析？** 你信任文件分类准确，不需要验证 → 直接点「AI 分析」
        """)

    folders_all = [f["name"] for f in get_available_folders(paths)]

    c1, c2 = st.columns(2)
    with c1:
        folder = st.selectbox("目标文件夹 *", folders_all, key="fa_folder")
    with c2:
        question = st.text_input("分析问题 *", placeholder="例：这个方向的核心 novelty 是什么？", key="fa_question")

    st.divider()

    bc1, bc2 = st.columns(2)
    with bc1:
        with st.container(border=True):
            st.subheader("📦 第一步：生成 Bundle")
            st.caption("打包文件夹全文，不调用 LLM，零费用")
            if st.button("📦 生成 Bundle", use_container_width=True, key="fa_bundle_btn") and folder:
                result = run_cli_sync(paths, ["build-folder-bundle", "--folder", folder], "生成 Bundle")
                st.json(result)
                bfiles = result.get("bundle_files") or []
                if bfiles:
                    show_path_actions(bfiles[0], "folder_bundle")
                    preview_markdown(bfiles[0], "Bundle 预览")

    with bc2:
        with st.container(border=True):
            st.subheader("🔬 第二步：AI 深度分析")
            st.caption("基于 Bundle 或直接分析，调用 LLM 回答问题")
            confirm_fa = st.checkbox("确认调用 LLM（会产生 API 费用）", key="fa_confirm")
            if st.button("▶️ AI 分析", disabled=not confirm_fa or not question or not folder, use_container_width=True, key="fa_analyze_btn"):
                task_id = run_cli_live_async(paths, ["analyze-folder", "--folder", folder, "--question", question], f"文件夹分析: {folder}")
                st.session_state["fa_task_id"] = task_id

            task_id = st.session_state.get("fa_task_id", "")
            if task_id:
                render_task_progress(task_id)

elif nav == "📈 自定义分析 (Custom Analysis)" and sub_page and "个人画像" in sub_page:
    st.header("📈 个人画像 (Profile)")
    st.caption("基于知识库内容生成个人认知画像——分析关注主题、决策模式、情绪/执行力模式等。")

    with st.expander("📖 什么是个人画像？"):
        st.markdown("""
        定期生成个人画像可以帮助你看到自己关注焦点的变化、发现反复出现的模式、量化认知输出。

        **Scope 由你自由定义。** 例：
        - "交易心理与执行力" — 只看交易相关文档中的情绪和纪律问题
        - "AI 研究方向" — 只看 AI 相关文档中的技术方向
        - 留空 = 全量画像
        """)

    folders_all = [f["name"] for f in get_available_folders(paths)]

    c1, c2 = st.columns(2)
    with c1:
        scope = st.text_area(
            "画像范围 Scope *",
            placeholder="自由描述你想分析的角度，例：交易心理与执行力 / AI研究方向 / 写作倾向...\n留空 = 全量分析",
            key="prof_scope",
        )
        st.caption("💡 从可用文件夹获取灵感：")
        tag_cols = st.columns(5)
        for idx, f in enumerate(folders_all[:10]):
            with tag_cols[idx % 5]:
                if st.button(f, key=f"prof_tag_{idx}"):
                    current = st.session_state.get("prof_scope", "")
                    st.session_state.prof_scope = ((current + " " + f).strip())

    with c2:
        months_all = get_available_months(paths)
        st.selectbox("开始月份（可选）", ["不限"] + months_all, key="prof_start")
        st.selectbox("结束月份（可选）", ["不限"] + months_all, key="prof_end")

    # Map user scope to CLI scope param
    scope_text = st.session_state.get("prof_scope", "").strip()
    cli_scope = scope_text if scope_text else "all"

    confirm_prof = st.checkbox("确认调用 LLM 生成画像报告", key="prof_confirm")
    if st.button("▶️ 生成画像报告", disabled=not confirm_prof):
        task_id = run_cli_live_async(paths, ["profile-me", "--scope", cli_scope], f"个人画像: {cli_scope}")
        st.session_state["prof_task_id"] = task_id

    task_id = st.session_state.get("prof_task_id", "")
    if task_id:
        render_task_progress(task_id)

# ═══════════════════════════════════════════════════════════════
# 🧭 初始化向导 (Setup Wizard)
# ═══════════════════════════════════════════════════════════════

elif "初始化向导" in nav:
    st.header("🧭 初始化向导")
    st.caption("首次使用或重建知识库时，通过以下步骤让系统从你的数据中自动发现分类体系，替代默认的 11 个硬编码类别。")

    # Resolve default paths
    kb_out = Path(paths.kb_out_dir)
    inventory_dir = kb_out / "file_inventory"
    unsupervised_dir = kb_out / "unsupervised"
    review_dir = kb_out / "review_round_1"
    supervised_policy_dir = kb_out / "supervised_policy"
    supervised_kb_dir = kb_out / "supervised_kb"

    wizard_step = st.radio(
        "选择步骤",
        ["Step 1: 扫描文件地图", "Step 2: 自动聚类", "Step 3: 审核修正", "Step 4: 构建监督版 KB", "Step 5: 深度定制 (可选)"],
        horizontal=True,
    )

    st.divider()

    # ═══════════════════════════════════════════════════
    # Step 1: 扫描文件地图
    # ═══════════════════════════════════════════════════
    if "Step 1" in wizard_step:
        st.subheader("Step 1: 扫描文件地图")
        st.markdown("""
        **目标**：只读文件名和元数据，生成「文件世界地图」。
        **不会**：读取正文、调用 LLM、移动或修改任何文件。

        输出文件（存于 `kb_out/file_inventory/`）：
        - `file_inventory.csv/jsonl` — 全量文件清单
        - `folder_tree.md` — 文件夹层级树
        - `scan_report.md` — 扫描汇总报告
        - `filename_stats.md` / `time_distribution.md` / `extension_distribution.md`
        """)

        # ── Directory picker ──
        default_scan_dir = str(paths.docs_dir)
        if "wizard_scan_dir" not in st.session_state:
            st.session_state["wizard_scan_dir"] = default_scan_dir

        c1, c2 = st.columns([3, 1])
        with c1:
            scan_dir = st.text_input(
                "📁 扫描目录",
                value=st.session_state["wizard_scan_dir"],
                help="输入要扫描的文件夹路径，默认是 docs/ 目录。留空则使用 config.yaml 中配置的全局目录。",
                key="wizard_scan_dir_input",
            )
        with c2:
            st.caption("")
            st.caption("")
            if st.button("🔄 重置为 docs/", key="reset_scan_dir"):
                st.session_state["wizard_scan_dir"] = default_scan_dir
                st.rerun()
        if scan_dir != st.session_state.get("wizard_scan_dir", ""):
            st.session_state["wizard_scan_dir"] = scan_dir

        st.caption(f"当前扫描范围：`{st.session_state['wizard_scan_dir']}`")

        scan_report = inventory_dir / "scan_report.md"
        if scan_report.exists():
            st.success(f"✅ 已扫描 — 最后更新: {time.strftime('%Y-%m-%d %H:%M', time.localtime(scan_report.stat().st_mtime))}")
            with st.expander("📄 查看扫描报告", expanded=False):
                st.markdown(read_markdown(scan_report))
            if st.button("🔄 重新扫描", key="rescan"):
                args = ["scan-filenames", "--config", str(paths.config_path),
                        "--output", str(inventory_dir),
                        "--root-dir", st.session_state["wizard_scan_dir"]]
                task_id = run_cli_live_async(paths, args, "扫描文件地图")
                st.session_state["wizard_s1_task"] = task_id
        else:
            st.info("尚未扫描。请点击下方按钮开始。")
            if st.button("🚀 开始扫描", key="start_scan", type="primary"):
                args = ["scan-filenames", "--config", str(paths.config_path),
                        "--output", str(inventory_dir),
                        "--root-dir", st.session_state["wizard_scan_dir"]]
                task_id = run_cli_live_async(paths, args, "扫描文件地图")
                st.session_state["wizard_s1_task"] = task_id

        task_id = st.session_state.get("wizard_s1_task")
        if task_id:
            still_running = render_task_progress(task_id)
            if not still_running:
                st.session_state["wizard_s1_task"] = None
                st.rerun()

    # ═══════════════════════════════════════════════════
    # Step 2: 自动聚类
    # ═══════════════════════════════════════════════════
    elif "Step 2" in wizard_step:
        st.subheader("Step 2: 自动聚类分析")
        st.markdown("""
        **目标**：基于文件名、路径和文件夹结构，让 LLM 自动归纳候选类别和标签。
        **前提**：需要先完成 Step 1（file_inventory.jsonl 存在）。

        输出文件（存于 `kb_out/unsupervised/`）：
        - `auto_categories.yaml` — 系统发现的候选类别
        - `cluster_report.md` — 聚类分析报告（含置信度、代表文件、噪音标记）
        - `clustered_files.csv` — 每个文件的分类结果
        """)

        inventory_jsonl = inventory_dir / "file_inventory.jsonl"
        cluster_report = unsupervised_dir / "cluster_report.md"

        if not inventory_jsonl.exists():
            st.warning("⚠️ 请先完成 Step 1: 扫描文件地图")
        elif cluster_report.exists():
            st.success(f"✅ 已聚类 — 最后更新: {time.strftime('%Y-%m-%d %H:%M', time.localtime(cluster_report.stat().st_mtime))}")
            with st.expander("📄 查看聚类报告", expanded=False):
                st.markdown(read_markdown(cluster_report))
            if st.button("🔄 重新聚类", key="recluster"):
                args = ["auto-cluster", "--inventory", str(inventory_jsonl),
                        "--output", str(unsupervised_dir),
                        "--config", str(paths.config_path)]
                task_id = run_cli_live_async(paths, args, "自动聚类分析")
                st.session_state["wizard_s2_task"] = task_id
        else:
            if st.button("🚀 开始聚类", key="start_cluster", type="primary"):
                args = ["auto-cluster", "--inventory", str(inventory_jsonl),
                        "--output", str(unsupervised_dir),
                        "--config", str(paths.config_path)]
                task_id = run_cli_live_async(paths, args, "自动聚类分析")
                st.session_state["wizard_s2_task"] = task_id

        task_id = st.session_state.get("wizard_s2_task")
        if task_id:
            still_running = render_task_progress(task_id)
            if not still_running:
                st.session_state["wizard_s2_task"] = None
                st.rerun()

    # ═══════════════════════════════════════════════════
    # Step 3: 审核修正
    # ═══════════════════════════════════════════════════
    elif "Step 3" in wizard_step:
        st.subheader("Step 3: 审核修正")
        st.markdown("""
        **目标**：系统自动挑选一批最有信息量的样本，你只需审核少量文件（约 50-80 个），系统从你的反馈中学习规则。
        **前提**：需要先完成 Step 2（clustered_files.csv 存在）。

        **两步操作**：
        1. **生成审核样本** → 系统选出代表文件、边界文件、低置信度文件
        2. **提交审核结果** → 在下方表格中修正后，系统自动学习分类规则
        """)

        assignments_jsonl = unsupervised_dir / "final_assignments.jsonl"
        review_csv = review_dir / "review_sample.csv"
        learning_report = supervised_policy_dir / "learning_report.md"

        # Sub-step 3a: Generate review sample
        st.write("**① 生成审核样本**")
        if not assignments_jsonl.exists():
            st.warning("⚠️ 请先完成 Step 2: 自动聚类")
        elif review_csv.exists():
            st.success(f"✅ 审核样本已生成 — {time.strftime('%Y-%m-%d %H:%M', time.localtime(review_csv.stat().st_mtime))}")
            if st.button("🔄 重新生成", key="resample"):
                args = ["sample-review", "--assignments", str(assignments_jsonl),
                        "--output", str(review_dir), "--max-samples", "80"]
                task_id = run_cli_live_async(paths, args, "生成审核样本")
                st.session_state["wizard_s3a_task"] = task_id
        else:
            if st.button("🎯 生成审核样本 (最多 80 个文件)", key="gen_sample", type="primary"):
                review_dir.mkdir(parents=True, exist_ok=True)
                args = ["sample-review", "--assignments", str(assignments_jsonl),
                        "--output", str(review_dir), "--max-samples", "80"]
                task_id = run_cli_live_async(paths, args, "生成审核样本")
                st.session_state["wizard_s3a_task"] = task_id

        task_id = st.session_state.get("wizard_s3a_task")
        if task_id:
            if not render_task_progress(task_id):
                st.session_state["wizard_s3a_task"] = None
                st.rerun()

        # Sub-step 3b: Inline review editor
        if review_csv.exists():
            st.divider()
            st.write("**② 在下方表格中修正分类**")
            st.caption("修改 `user_correct_category`、`user_correct_tags`、`user_include_in_kb` 列，完成后点击底部「提交审核结果」。")

            df = pd.read_csv(str(review_csv))
            if "user_correct_category" not in df.columns:
                df["user_correct_category"] = ""
            if "user_correct_tags" not in df.columns:
                df["user_correct_tags"] = ""
            if "user_include_in_kb" not in df.columns:
                df["user_include_in_kb"] = 1
            if "user_comment" not in df.columns:
                df["user_comment"] = ""

            edited = st.data_editor(
                df,
                column_config={
                    "filename": st.column_config.TextColumn("文件名", disabled=True),
                    "predicted_category": st.column_config.TextColumn("系统分类", disabled=True),
                    "user_correct_category": st.column_config.TextColumn("✅ 修正分类", help="输入正确的分类名称"),
                    "user_correct_tags": st.column_config.TextColumn("🏷️ 修正标签", help="用逗号分隔"),
                    "user_include_in_kb": st.column_config.CheckboxColumn("纳入 KB", help="取消勾选 = 排除此文件"),
                    "user_comment": st.column_config.TextColumn("备注", help="可选"),
                },
                use_container_width=True,
                num_rows="dynamic",
                key="review_editor",
            )

            c1, c2 = st.columns([1, 3])
            with c1:
                save_clicked = st.button("💾 保存修正并生成规则", key="learn_rules", type="primary")

            # Count actual user modifications before saving
            user_changes = 0
            for _, row in edited.iterrows():
                if (str(row.get("user_correct_category", "")).strip()
                    or str(row.get("user_correct_tags", "")).strip()
                    or str(row.get("user_include_in_kb", "1")) != "1"
                    or str(row.get("user_comment", "")).strip()):
                    user_changes += 1

            with c2:
                if user_changes > 0:
                    st.success(f"检测到 **{user_changes}** 个文件有修正")
                else:
                    st.info(f"当前未做任何修正（{len(edited)} 个样本）")

            if save_clicked:
                if user_changes == 0:
                    st.warning("⚠️ 你尚未对任何样本做出修正。")
                    st.markdown("""
                    **请先做以下至少一项操作，再保存：**
                    - 在「✅ 修正分类」列输入正确的分类名
                    - 在「🏷️ 修正标签」列修改标签
                    - 取消勾选不该纳入知识库的文件
                    - 如果你完全同意系统自动分类，勾选下方复选框：
                    """)
                    agree_all = st.checkbox("✅ 我审核了样本，完全同意系统自动分类，无需修正", key="agree_all_predicted")
                    if agree_all:
                        # User explicitly agrees with all predictions → fill user_correct_category = predicted_category
                        edited["user_correct_category"] = edited["predicted_category"]
                        review_filled = review_dir / "review_sample_filled.csv"
                        edited.to_csv(str(review_filled), index=False)
                        supervised_policy_dir.mkdir(parents=True, exist_ok=True)
                        args = ["learn-from-review", "--review", str(review_filled),
                                "--assignments", str(assignments_jsonl),
                                "--output", str(supervised_policy_dir)]
                        task_id = run_cli_live_async(paths, args, "学习分类规则")
                        st.session_state["wizard_s3b_task"] = task_id
                        st.rerun()
                else:
                    review_filled = review_dir / "review_sample_filled.csv"
                    edited.to_csv(str(review_filled), index=False)
                    supervised_policy_dir.mkdir(parents=True, exist_ok=True)
                    args = ["learn-from-review", "--review", str(review_filled),
                            "--assignments", str(assignments_jsonl),
                            "--output", str(supervised_policy_dir)]
                    task_id = run_cli_live_async(paths, args, "学习分类规则")
                    st.session_state["wizard_s3b_task"] = task_id
                    st.rerun()

            task_id = st.session_state.get("wizard_s3b_task")
            if task_id:
                if not render_task_progress(task_id):
                    st.session_state["wizard_s3b_task"] = None
                    st.rerun()

            # Show learning report
            if learning_report.exists():
                with st.expander("📄 查看学习报告", expanded=True):
                    st.markdown(read_markdown(learning_report))

    # ═══════════════════════════════════════════════════
    # Step 4: 构建监督版 KB
    # ═══════════════════════════════════════════════════
    elif "Step 4" in wizard_step:
        st.subheader("Step 4: 构建监督版知识库")
        st.markdown("""
        **目标**：用你审核后的分类、标签、规则，全量处理所有文件，写入主知识库数据库。
        **前提**：需要先完成 Step 3（supervised_policy/ 目录存在）。

        输出文件（存于 `kb_out/supervised_kb/`）：
        - 主数据库写入 `kb.sqlite3`（统一管理）
        - `tag_stats.csv` / `category_stats.csv` — 分类统计
        - `dashboard/index.html` — 可视化仪表板
        - `supervised_build_report.md` — 构建报告
        """)

        inventory_jsonl = inventory_dir / "file_inventory.jsonl"
        build_report = supervised_kb_dir / "supervised_build_report.md"

        if not supervised_policy_dir.exists():
            st.warning("⚠️ 请先完成 Step 3: 审核修正（生成分类策略文件）")
        elif build_report.exists():
            st.success(f"✅ 已构建 — 最后更新: {time.strftime('%Y-%m-%d %H:%M', time.localtime(build_report.stat().st_mtime))}")
            with st.expander("📄 查看构建报告", expanded=False):
                st.markdown(read_markdown(build_report))
            if st.button("🔄 重新构建", key="rebuild"):
                assignments_jsonl = unsupervised_dir / "final_assignments.jsonl"
                llm_flag = ["--llm-assignments", str(assignments_jsonl)] if assignments_jsonl.exists() else []
                if not llm_flag:
                    st.warning("⚠️ 未找到 Step 2 的分类结果 (final_assignments.jsonl)，构建将缺少 LLM 分类提示，可能导致大量未分类文件")
                args = ["build-supervised-kb", "--inventory", str(inventory_jsonl),
                        "--policy", str(supervised_policy_dir),
                        "--output", str(supervised_kb_dir),
                        "--sqlite", str(paths.sqlite_path),
                        "--config", str(paths.config_path)] + llm_flag
                task_id = run_cli_live_async(paths, args, "构建监督版知识库")
                st.session_state["wizard_s4_task"] = task_id
        else:
            if st.button("🚀 构建知识库", key="start_build", type="primary"):
                supervised_kb_dir.mkdir(parents=True, exist_ok=True)
                assignments_jsonl = unsupervised_dir / "final_assignments.jsonl"
                llm_flag = ["--llm-assignments", str(assignments_jsonl)] if assignments_jsonl.exists() else []
                if not llm_flag:
                    st.warning("⚠️ 未找到 Step 2 的分类结果 (final_assignments.jsonl)，构建将缺少 LLM 分类提示，可能导致大量未分类文件")
                args = ["build-supervised-kb", "--inventory", str(inventory_jsonl),
                        "--policy", str(supervised_policy_dir),
                        "--output", str(supervised_kb_dir),
                        "--sqlite", str(paths.sqlite_path),
                        "--config", str(paths.config_path)] + llm_flag
                task_id = run_cli_live_async(paths, args, "构建监督版知识库")
                st.session_state["wizard_s4_task"] = task_id

        task_id = st.session_state.get("wizard_s4_task")
        if task_id:
            still_running = render_task_progress(task_id)
            if not still_running:
                st.session_state["wizard_s4_task"] = None
                st.rerun()

        # Show also the dashboard
        dashboard_html = supervised_kb_dir / "dashboard" / "index.html"
        if dashboard_html.exists():
            with st.expander("📊 分类仪表板", expanded=False):
                st.components.v1.html(dashboard_html.read_text(encoding="utf-8"), height=600, scrolling=True)

    # ═══════════════════════════════════════════════════
    # Step 5: 深度定制 (可选)
    # ═══════════════════════════════════════════════════
    elif "Step 5" in wizard_step:
        st.subheader("Step 5: 深度定制构建 (高级)")
        st.markdown("""
        **目标**：完整构建链——从原始文件到 Wiki 页面、全文搜索索引、报告模板、最终配置。
        **前提**：需要先完成 Step 4（有监督分类结果）+ 有 blueprint 和 components 配置。

        ⚠️ 这是高级功能，会调用大量 LLM API，运行时间较长。
        """)

        st.info("此功能需要以下目录中存在配置文件：\n"
                "- `kb_out/blueprints/` — 知识库蓝图\n"
                "- `kb_tool/components/definitions/` — 组件定义\n\n"
                "如果尚未准备，请先在「设置」页面配置。")

        if st.button("🚀 开始深度定制构建", key="start_deep_custom"):
            blueprint_dir = kb_out / "blueprints" / "session_001" / "blueprint"
            components_dir = Path(paths.kb_tool_dir) / "components" / "definitions"
            if not blueprint_dir.exists():
                st.error(f"蓝图目录不存在: {blueprint_dir}")
            elif not components_dir.exists():
                st.error(f"组件定义目录不存在: {components_dir}")
            else:
                deep_custom_out = kb_out / "deep_custom_kb" / "session_002"
                args = ["build-deep-custom", "--config", str(paths.config_path),
                        "--blueprint", str(blueprint_dir),
                        "--policy", str(supervised_policy_dir),
                        "--components", str(components_dir),
                        "--output", str(deep_custom_out)]
                task_id = run_cli_live_async(paths, args, "深度定制构建")
                st.session_state["wizard_s5_task"] = task_id

        task_id = st.session_state.get("wizard_s5_task")
        if task_id:
            still_running = render_task_progress(task_id)
            if not still_running:
                result = st.session_state.get(f"{task_id}_result", {})
                if isinstance(result, dict) and result.get("output_dir"):
                    st.success(f"✅ 深度定制构建完成！输出: {result['output_dir']}")
                st.session_state["wizard_s5_task"] = None
                st.rerun()

# ═══════════════════════════════════════════════════════════════
# 📋 报告中心 (Reports)
# ═══════════════════════════════════════════════════════════════

elif "报告中心" in nav:
    st.header("📋 报告中心 (Reports)")
    st.caption("浏览、预览和下载所有历史报告")

    grouped = group_reports(paths.reports_dir)
    group_names = sorted(grouped.keys())

    if not group_names:
        st.info("暂无报告")
    else:
        grp = st.selectbox("报告分组", group_names)
        files = grouped.get(grp, [])
        labels = [str(p.relative_to(paths.reports_dir)) for p in files]

        if labels:
            # Table view
            df_rpt = pd.DataFrame([
                {"报告": str(p.relative_to(paths.reports_dir)), "修改时间": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)), "大小": f"{p.stat().st_size // 1024} KB"}
                for p in files
            ])
            st.dataframe(df_rpt, use_container_width=True, hide_index=True)

            idx = st.selectbox("选择报告预览", range(len(labels)), format_func=lambda i: labels[i])
            p = files[idx]

            c1, c2, c3 = st.columns(3)
            with c1:
                st.button("📂 打开文件夹", use_container_width=True, key="rpt_open", on_click=lambda: safe_startfile(p.parent, ALLOWED_OPEN_ROOTS))
            with c2:
                if st.button("📋 复制路径", use_container_width=True, key="rpt_copy"):
                    ok, _ = copy_to_clipboard(str(p))
                    st.toast("已复制到剪贴板" if ok else "复制失败")
            with c3:
                fname = Path(str(p)).name
                st.download_button("⬇️ 下载报告", data=read_markdown(p), file_name=fname, use_container_width=True, key="rpt_download")

            preview_markdown(str(p), "报告预览", expanded=False)
        else:
            st.info("该分组暂无报告")

# ═══════════════════════════════════════════════════════════════
# ⚙️ 设置 (Settings)
# ═══════════════════════════════════════════════════════════════

elif "设置" in nav:
    st.header("⚙️ 设置 (Settings)")
    st.caption("配置 LLM 连接、知识库路径、扫描参数，以及系统健康检查")

    tab1, tab2, tab3, tab4 = st.tabs(["LLM 配置", "路径配置", "扫描配置", "系统诊断"])

    # ── Tab 1: LLM Config ──
    with tab1:
        st.subheader("LLM 配置")
        llm_cfg = cfg.get("llm", {})

        with st.container(border=True):
            c1, c2 = st.columns(2)
            with c1:
                base_url = st.text_input("API Base URL", value=llm_cfg.get("base_url", "https://api.deepseek.com"), key="cfg_base_url")
                model = st.text_input("模型 (Model)", value=llm_cfg.get("model", "deepseek-v4-flash"), key="cfg_model")
                api_key_env = st.text_input("API Key 环境变量名", value=llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY"), key="cfg_api_key_env")
            with c2:
                max_concurrency = st.number_input("并发数", min_value=1, max_value=16, value=int(llm_cfg.get("max_concurrency", 4)), key="cfg_concurrency")
                timeout = st.number_input("超时（秒）", min_value=10, max_value=300, value=int(llm_cfg.get("timeout_seconds", 60)), key="cfg_timeout")
                temperature = st.number_input("Temperature", min_value=0.0, max_value=2.0, value=float(llm_cfg.get("temperature", 0.2)), step=0.05, key="cfg_temp")

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("🔍 测试连接", use_container_width=True, key="cfg_test_conn"):
                with st.spinner("测试中..."):
                    r = test_deepseek_connection(cfg)
                if r["ok"]:
                    st.success(f"✅ 连接正常（延迟 {r['latency_ms']}ms, 模型: {r['model']}）")
                else:
                    st.error(f"❌ 连接失败: {r['error']}")
        with c2:
            if st.button("💾 保存 LLM 配置", use_container_width=True, key="cfg_save_llm"):
                cfg["llm"]["base_url"] = base_url
                cfg["llm"]["model"] = model
                cfg["llm"]["api_key_env"] = api_key_env
                cfg["llm"]["max_concurrency"] = max_concurrency
                cfg["llm"]["timeout_seconds"] = timeout
                cfg["llm"]["temperature"] = temperature
                if save_config(cfg, str(paths.config_path)):
                    st.toast("✅ LLM 配置已保存")
                else:
                    st.toast("❌ 保存失败")

    # ── Tab 2: Path Config ──
    with tab2:
        st.subheader("路径配置")
        with st.container(border=True):
            docs_root = st.text_input("docs 目录", value=str(paths.docs_dir), key="cfg_docs_root")
            kb_out = st.text_input("kb_out 输出目录", value=str(paths.kb_out_dir), key="cfg_kbout")
            reports = st.text_input("reports 目录", value=str(paths.reports_dir), key="cfg_reports")

            if st.button("💾 保存路径配置", key="cfg_save_paths"):
                cfg["workflow"]["docs_root"] = docs_root
                cfg["storage"]["output_dir"] = kb_out
                cfg["storage"]["reports_dir"] = reports
                if save_config(cfg, str(paths.config_path)):
                    st.toast("✅ 路径配置已保存（重启 GUI 生效）")
                else:
                    st.toast("❌ 保存失败")

    # ── Tab 3: Scan Config ──
    with tab3:
        st.subheader("扫描配置")
        with st.container(border=True):
            st.write("**支持的文件类型：**")
            inc_ext = cfg.get("scanner", {}).get("include_extensions", [".docx", ".doc", ".md", ".txt"])
            c1, c2, c3, c4 = st.columns(4)
            exts_selected = []
            with c1:
                if st.checkbox(".docx", value=".docx" in inc_ext, key="ext_docx"): exts_selected.append(".docx")
            with c2:
                if st.checkbox(".doc", value=".doc" in inc_ext, key="ext_doc"): exts_selected.append(".doc")
            with c3:
                if st.checkbox(".md", value=".md" in inc_ext, key="ext_md"): exts_selected.append(".md")
            with c4:
                if st.checkbox(".txt", value=".txt" in inc_ext, key="ext_txt"): exts_selected.append(".txt")

            trading_cats = st.text_area(
                "交易相关分类（逗号分隔）",
                value=", ".join(cfg.get("workflow", {}).get("trading_categories", [])),
                key="cfg_trading_cats",
            )

            if st.button("💾 保存扫描配置", key="cfg_save_scan"):
                cfg["scanner"]["include_extensions"] = exts_selected
                cfg["workflow"]["trading_categories"] = [x.strip() for x in trading_cats.split(",") if x.strip()]
                if save_config(cfg, str(paths.config_path)):
                    st.toast("✅ 扫描配置已保存")
                else:
                    st.toast("❌ 保存失败")

    # ── Tab 4: System Health ──
    with tab4:
        st.subheader("系统诊断")
        if st.button("🔍 运行诊断", key="cfg_diag"):
            with st.spinner("诊断中..."):
                results = system_health_check(cfg, paths)

            with st.container(border=True):
                for r in results:
                    icon = "🟢" if r["ok"] is True else ("🟡" if r["ok"] is None else "🔴")
                    st.write(f"{icon} **{r['name']}** — {r['detail']}")

            ok_count = sum(1 for r in results if r["ok"] is True)
            total = len(results)
            st.toast(f"✅ 诊断完成: {ok_count}/{total} 项正常")
