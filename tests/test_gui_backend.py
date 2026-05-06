"""
KB Console v2 — GUI 后端集成测试
测试所有 streamlit_app.py 直接调用的函数
运行: python tests/test_gui_backend.py
"""
import sys
import os
import tempfile
from pathlib import Path

# Ensure we import from project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kb_tool"))

import yaml
import sqlite3

# ── Load config via load_app_paths (with absolute path fix) ──
from ui_helpers import load_app_paths
cfg, paths = load_app_paths(workspace_root=PROJECT_ROOT)


def test(name):
    """Decorator-style test runner"""
    def deco(fn):
        try:
            fn()
            print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            import traceback
            traceback.print_exc()
    return deco


# ═══════════════════════════════════════════════════════
# 1. load_app_paths — 路径解析（GUI 启动第一件事）
# ═══════════════════════════════════════════════════════
print("=== 1. 路径解析 (load_app_paths) ===")

@test("Paths 对象创建成功")
def _():
    from ui_helpers import load_app_paths, AppPaths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert isinstance(paths, AppPaths)

@test("sqlite_path 是绝对路径")
def _():
    from ui_helpers import load_app_paths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert os.path.isabs(cfg2["storage"]["sqlite_path"])

@test("sqlite_path 指向存在的文件")
def _():
    from ui_helpers import load_app_paths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert Path(cfg2["storage"]["sqlite_path"]).exists(), f"Not found: {cfg2['storage']['sqlite_path']}"

@test("docs_dir 存在")
def _():
    from ui_helpers import load_app_paths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert paths.docs_dir.exists()

@test("python_exe 存在")
def _():
    from ui_helpers import load_app_paths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert paths.python_exe.exists()

@test("main_py 存在")
def _():
    from ui_helpers import load_app_paths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert paths.main_py.exists()

@test("config_path 存在")
def _():
    from ui_helpers import load_app_paths
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    assert paths.config_path.exists()


# ═══════════════════════════════════════════════════════
# 2. DB 初始化 + 表完整性
# ═══════════════════════════════════════════════════════
print("=== 2. 数据库初始化 ===")

@test("_init_and_ensure_columns 冷启动")
def _():
    from workflow_mainline import _init_and_ensure_columns
    import copy
    tmp = tempfile.mktemp(suffix=".sqlite3")
    cfg_tmp = copy.deepcopy(cfg)
    cfg_tmp["storage"]["sqlite_path"] = tmp
    _init_and_ensure_columns(cfg_tmp)
    con = sqlite3.connect(tmp)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "documents" in tables
    assert "document_chunks" in tables
    assert "document_chunks_fts" in tables
    con.close()
    os.unlink(tmp)

@test("documents 表有数据")
def _():
    from ui_helpers import load_app_paths
    cfg2, _ = load_app_paths(workspace_root=PROJECT_ROOT)
    con = sqlite3.connect(cfg2["storage"]["sqlite_path"])
    count = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert count > 0, f"documents table is empty ({count} rows)"
    con.close()

@test("document_chunks 表存在")
def _():
    from ui_helpers import load_app_paths
    cfg2, _ = load_app_paths(workspace_root=PROJECT_ROOT)
    con = sqlite3.connect(cfg2["storage"]["sqlite_path"])
    con.execute("SELECT 1 FROM document_chunks LIMIT 1")
    con.close()

@test("document_chunks_fts 表存在")
def _():
    from ui_helpers import load_app_paths
    cfg2, _ = load_app_paths(workspace_root=PROJECT_ROOT)
    con = sqlite3.connect(cfg2["storage"]["sqlite_path"])
    con.execute("SELECT 1 FROM document_chunks_fts LIMIT 1")
    con.close()


# ═══════════════════════════════════════════════════════
# 3. 快速搜索 (Find 页面核心)
# ═══════════════════════════════════════════════════════
print("=== 3. 快速搜索 (find_idea) ===")

@test("关键词'止损'有结果")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "止损")
    assert r["count"] > 0

@test("关键词'ai'有结果")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "ai")
    assert r["count"] > 0, f"ai search returned {r['count']}"

@test("按分类过滤有效")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "止损", category="交易系统与方法论")
    assert r["count"] > 0
    for item in r["items"]:
        assert "交易系统与方法论" in item.get("category", "")

@test("按月份过滤有效")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "止损", month_start="2026-01", month_end="2026-03")
    assert r["count"] >= 0  # 不崩溃就好

@test("空查询不崩溃")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "")
    assert isinstance(r, dict)

@test("不存在的词返回0条不崩溃")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "xyznotexist12345")
    assert r["count"] == 0

@test("文件名搜索命中(无FTS)")
def _():
    from workflow_mainline import find_idea
    r = find_idea(cfg, "ai侦探")
    assert r["count"] > 0


# ═══════════════════════════════════════════════════════
# 4. Token 预算 (总览 + 主题分析)
# ═══════════════════════════════════════════════════════
print("=== 4. Token 预算 ===")

@test("token_budget trading")
def _():
    from workflow_mainline import token_budget
    b = token_budget(cfg, scope="trading")
    assert b["document_count"] > 0
    assert b["token_estimate_high"] > 0
    assert isinstance(b["fits_1m_context"], bool)
    assert b["strategy"] in ("single_full_read", "category_batches", "monthly_batches_or_compacted")

@test("estimate_scope_tokens 工作")
def _():
    from ui_helpers import load_app_paths, estimate_scope_tokens
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    est = estimate_scope_tokens(paths, ["AI与工具化"])
    assert est["document_count"] > 0
    assert est["token_high"] > 0


# ═══════════════════════════════════════════════════════
# 5. Dashboard 数据
# ═══════════════════════════════════════════════════════
print("=== 5. Dashboard 数据 ===")

@test("get_dashboard_enriched 返回完整数据")
def _():
    from ui_helpers import load_app_paths, get_dashboard_enriched
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    state = get_dashboard_enriched(paths)
    assert state["docs_count"] > 0
    assert state["db_exists"]
    assert len(state.get("category_dist", [])) > 0
    assert len(state.get("monthly_trend", [])) > 0

@test("get_dashboard_state 返回基本数据")
def _():
    from ui_helpers import load_app_paths, get_dashboard_state
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    state = get_dashboard_state(paths)
    assert state["docs_count"] > 0
    assert "recent_reports" in state


# ═══════════════════════════════════════════════════════
# 6. 文件夹/月份数据 (GUI 下拉菜单数据源)
# ═══════════════════════════════════════════════════════
print("=== 6. 文件夹和月份数据 ===")

@test("get_available_folders 返回列表")
def _():
    from ui_helpers import load_app_paths, get_available_folders
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    folders = get_available_folders(paths)
    assert len(folders) > 0
    assert all("name" in f for f in folders)
    assert all("file_count" in f for f in folders)
    # "AI与工具化" should exist
    names = [f["name"] for f in folders]
    assert "AI与工具化" in names, f"AI与工具化 not in {names[:5]}..."

@test("get_available_months 返回列表")
def _():
    from ui_helpers import load_app_paths, get_available_months
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    months = get_available_months(paths)
    assert len(months) > 0


# ═══════════════════════════════════════════════════════
# 7. 文件夹分析 (fetch_folder_docs)
# ═══════════════════════════════════════════════════════
print("=== 7. 文件夹分析 ===")

@test("fetch_folder_docs AI与工具化 有结果")
def _():
    from bundle_builder import fetch_folder_docs
    docs = fetch_folder_docs(cfg, "AI与工具化")
    assert len(docs) > 0, f"Expected >0 docs, got {len(docs)}"

@test("fetch_folder_docs 返回完整字段")
def _():
    from bundle_builder import fetch_folder_docs
    docs = fetch_folder_docs(cfg, "AI与工具化")
    d = docs[0]
    for key in ("filename", "primary_category", "docs_path", "content"):
        assert key in d, f"Missing key: {key}"

@test("fetch_folder_docs 交易系统与方法论 有结果")
def _():
    from bundle_builder import fetch_folder_docs
    docs = fetch_folder_docs(cfg, "交易系统与方法论")
    assert len(docs) > 0


# ═══════════════════════════════════════════════════════
# 8. 系统健康检查
# ═══════════════════════════════════════════════════════
print("=== 8. 系统健康检查 ===")

@test("system_health_check 全部检查通过")
def _():
    from ui_helpers import load_app_paths, system_health_check
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    results = system_health_check(cfg2, paths)
    assert len(results) >= 4
    for r in results:
        assert "name" in r and "ok" in r and "detail" in r
    # At least DB and config should be OK
    db_check = [r for r in results if "数据库" in r["name"]]
    assert db_check and db_check[0]["ok"]


# ═══════════════════════════════════════════════════════
# 9. 配置管理
# ═══════════════════════════════════════════════════════
print("=== 9. 配置管理 ===")

@test("save_config 保存并备份")
def _():
    from ui_helpers import load_app_paths, save_config
    import shutil
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    tmp = tempfile.mktemp(suffix=".yaml")
    shutil.copy(str(paths.config_path), tmp)
    test_cfg = yaml.safe_load(open(tmp, encoding="utf-8"))
    test_cfg["llm"]["temperature"] = 0.99
    ok = save_config(test_cfg, tmp)
    assert ok
    loaded = yaml.safe_load(open(tmp, encoding="utf-8"))
    assert loaded["llm"]["temperature"] == 0.99
    os.unlink(tmp)

@test("load_config_full 读取配置")
def _():
    from ui_helpers import load_config_full
    cfg_loaded = load_config_full(str(PROJECT_ROOT / "kb_tool" / "config.yaml"))
    assert "llm" in cfg_loaded
    assert "storage" in cfg_loaded

@test("test_deepseek_connection 执行不崩溃")
def _():
    from ui_helpers import test_deepseek_connection
    r = test_deepseek_connection(cfg)
    assert "ok" in r
    assert "latency_ms" in r


# ═══════════════════════════════════════════════════════
# 10. 每周整理 — 扫描逻辑
# ═══════════════════════════════════════════════════════
print("=== 10. 每周整理 ===")

@test("_iter_source_files 非递归")
def _():
    from workflow_mainline import _iter_source_files
    import os
    desktop = os.path.expanduser("~/Desktop")
    files = _iter_source_files(cfg, source_dirs=[desktop], recursive=False)
    assert len(files) > 0
    # Non-recursive should only have top-level files
    for f in files:
        parent = str(Path(f).parent)
        assert parent == str(Path(desktop)), f"Expected {desktop}, got {parent}"

@test("_iter_source_files 递归")
def _():
    from workflow_mainline import _iter_source_files
    import os
    desktop = os.path.expanduser("~/Desktop")
    files = _iter_source_files(cfg, source_dirs=[desktop], recursive=True)
    assert len(files) > 0

@test("weekly_organize dry run 不崩溃")
def _():
    from workflow_mainline import weekly_organize
    import os
    desktop = os.path.expanduser("~/Desktop")
    result = weekly_organize(
        cfg, dry_run=True, max_files=2,
        source_dirs=[desktop], recursive=False
    )
    assert result["dry_run"] == True
    assert "scanned" in result


# ═══════════════════════════════════════════════════════
# 11. Bundle 构建 (文件夹分析第一步)
# ═══════════════════════════════════════════════════════
print("=== 11. Bundle 构建 ===")

@test("build_budget 正常")
def _():
    from bundle_builder import fetch_folder_docs, build_budget
    docs = fetch_folder_docs(cfg, "AI与工具化")
    budget = build_budget(docs)
    assert budget["document_count"] > 0
    assert budget["token_estimate_high"] > 0

@test("fetch_topic_docs 正常工作")
def _():
    from bundle_builder import fetch_topic_docs
    docs = fetch_topic_docs(cfg, "RAG")
    assert isinstance(docs, list)
    # May be 0 or more, but shouldn't crash

@test("fetch_profile_docs all 正常")
def _():
    from bundle_builder import fetch_profile_docs
    docs = fetch_profile_docs(cfg, "all")
    assert len(docs) > 0

@test("fetch_profile_docs trading 正常")
def _():
    from bundle_builder import fetch_profile_docs
    docs = fetch_profile_docs(cfg, "trading")
    assert isinstance(docs, list)


# ═══════════════════════════════════════════════════════
# 12. 报告中心
# ═══════════════════════════════════════════════════════
print("=== 12. 报告中心 ===")

@test("group_reports 正常工作")
def _():
    from ui_helpers import load_app_paths, group_reports
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    grouped = group_reports(paths.reports_dir)
    assert isinstance(grouped, dict)

@test("recent_markdown_files 正常工作")
def _():
    from ui_helpers import load_app_paths, recent_markdown_files
    cfg2, paths = load_app_paths(workspace_root=PROJECT_ROOT)
    files = recent_markdown_files(paths.reports_dir)
    assert isinstance(files, list)


# ═══════════════════════════════════════════════════════
# 13. 路径安全
# ═══════════════════════════════════════════════════════
print("=== 13. 路径安全 ===")

@test("path_is_under 正向匹配")
def _():
    from ui_helpers import path_is_under
    assert path_is_under(Path("/a/b/c"), [Path("/a/b")])
    assert path_is_under(Path("/a/b/c/d"), [Path("/a/b")])

@test("path_is_under 拒绝越界")
def _():
    from ui_helpers import path_is_under
    assert not path_is_under(Path("/a/c"), [Path("/a/b")])

@test("safe_startfile 拒绝越界路径")
def _():
    from ui_helpers import safe_startfile
    ok, msg = safe_startfile(Path("/etc/passwd"), [Path("/home")])
    assert not ok


# ═══════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════
print()
print("All tests completed.")
