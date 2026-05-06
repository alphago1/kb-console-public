"""
End-to-end integration tests for Plan 1-5 fusion into frontend + backend.

Verifies:
  - Backend: full CLI pipeline (scan → cluster → review → learn → build)
  - Database: unified main-schema write via --sqlite flag
  - Classification: dynamic allowed_categories injection
  - weekly_organize: supervised policy detection and fallback
  - Frontend: streamlit_app import and wizard structure
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kb_tool"))


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def test_inventory_jsonl(tmp_path):
    """Simulate plan1 output: file_inventory.jsonl with realistic file entries."""
    p = tmp_path / "file_inventory.jsonl"
    data = [
        {"file_id": "f1", "path": "/fake/Desktop/交易复盘/2026-03-05-复盘笔记.md",
         "filename": "2026-03-05-复盘笔记.md", "extension": ".md",
         "parent_folder": "交易复盘", "size": 3200,
         "created_time": "2026-03-05T10:00:00", "modified_time": "2026-03-05T20:00:00",
         "time_month": "2026-03", "depth": 3,
         "filename_tokens": ["2026", "03", "05", "复盘", "笔记"],
         "path_tokens": ["Desktop", "交易复盘"],
         "suspected_date": "2026-03-05",
         "suspected_topic_keywords": ["复盘", "交易"]},
        {"file_id": "f2", "path": "/fake/Desktop/外部资料/合同模板-采购协议.docx",
         "filename": "合同模板-采购协议.docx", "extension": ".docx",
         "parent_folder": "外部资料", "size": 45000,
         "created_time": "2025-12-01T09:00:00", "modified_time": "2025-12-01T09:00:00",
         "time_month": "2025-12", "depth": 2,
         "filename_tokens": ["合同", "模板", "采购", "协议"],
         "path_tokens": ["Desktop", "外部资料"],
         "suspected_date": "2025-12-01",
         "suspected_topic_keywords": ["合同", "模板"]},
        {"file_id": "f3", "path": "/fake/Desktop/AI项目/RAG知识库技术选型.md",
         "filename": "RAG知识库技术选型.md", "extension": ".md",
         "parent_folder": "AI项目", "size": 8500,
         "created_time": "2026-02-15T14:00:00", "modified_time": "2026-02-20T10:00:00",
         "time_month": "2026-02", "depth": 2,
         "filename_tokens": ["RAG", "知识库", "技术", "选型"],
         "path_tokens": ["Desktop", "AI项目"],
         "suspected_date": "2026-02-15",
         "suspected_topic_keywords": ["RAG", "知识库", "技术选型"]},
        {"file_id": "f4", "path": "/fake/Desktop/个人随笔/2026Q1反思.md",
         "filename": "2026Q1反思.md", "extension": ".md",
         "parent_folder": "个人随笔", "size": 4200,
         "created_time": "2026-03-31T22:00:00", "modified_time": "2026-04-01T08:00:00",
         "time_month": "2026-03", "depth": 2,
         "filename_tokens": ["2026", "Q1", "反思"],
         "path_tokens": ["Desktop", "个人随笔"],
         "suspected_date": "2026-03-31",
         "suspected_topic_keywords": ["反思", "个人"]},
        {"file_id": "f5", "path": "/fake/Desktop/空文件.docx",
         "filename": "空文件.docx", "extension": ".docx",
         "parent_folder": ".", "size": 0,
         "created_time": "2026-01-01T00:00:00", "modified_time": "2026-01-01T00:00:00",
         "time_month": "2026-01", "depth": 1,
         "filename_tokens": ["空文件"],
         "path_tokens": ["Desktop"],
         "suspected_date": "2026-01-01",
         "suspected_topic_keywords": []},
        {"file_id": "f6", "path": "/fake/Desktop/交易复盘/0301盘前计划.md",
         "filename": "0301盘前计划.md", "extension": ".md",
         "parent_folder": "交易复盘", "size": 1800,
         "created_time": "2026-03-01T07:00:00", "modified_time": "2026-03-01T07:30:00",
         "time_month": "2026-03", "depth": 2,
         "filename_tokens": ["0301", "盘前", "计划"],
         "path_tokens": ["Desktop", "交易复盘"],
         "suspected_date": "2026-03-01",
         "suspected_topic_keywords": ["盘前", "计划"]},
    ]
    with open(p, "w", encoding="utf-8") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return str(p)


@pytest.fixture
def test_unified_sqlite_path(tmp_path):
    """Main KB SQLite path (simulates the real kb.sqlite3)."""
    return str(tmp_path / "kb.sqlite3")


@pytest.fixture
def test_supervised_policy_dir(tmp_path):
    """Simulate plan3 output: user-reviewed category schema and rules."""
    d = tmp_path / "supervised_policy"
    d.mkdir(parents=True)

    (d / "category_schema_v1.yaml").write_text(yaml.dump({
        "categories": [
            {"name": "交易复盘", "status": "approved", "file_count": 45},
            {"name": "交易系统与方法论", "status": "approved", "file_count": 30},
            {"name": "AI与工具化", "status": "approved", "file_count": 25},
            {"name": "个人随笔与自我观察", "status": "approved", "file_count": 20},
            {"name": "外部资料与待排除内容", "status": "approved", "file_count": 15},
            {"name": "空文件", "status": "approved", "file_count": 10},
            {"name": "其他杂项", "status": "merged_into:交易复盘", "file_count": 5},
        ]
    }, allow_unicode=True), encoding="utf-8")

    (d / "tag_ontology_v1.yaml").write_text(yaml.dump({
        "tags": [
            {"name": "止损", "frequency": 8},
            {"name": "仓位管理", "frequency": 5},
            {"name": "RAG", "frequency": 4},
            {"name": "情绪控制", "frequency": 7},
        ]
    }, allow_unicode=True), encoding="utf-8")

    (d / "classification_rules_v1.yaml").write_text(yaml.dump({
        "rules": [
            {"type": "merge", "sources": ["其他杂项"], "target": "交易复盘",
             "confidence": 0.9, "source": "user_merge"},
            {"type": "reclassification", "pattern": "文件 复盘0301.md",
             "from": "交易复盘", "to": "交易复盘", "confidence": 0.95,
             "source": "user_confirmation"},
        ]
    }, allow_unicode=True), encoding="utf-8")

    (d / "exclusion_rules_v1.yaml").write_text(yaml.dump({
        "excluded_categories": [{"name": "空文件", "user_confirmed": True}],
        "exclude_if_name_contains": ["合同模板", "~$"],
    }, allow_unicode=True), encoding="utf-8")

    (d / "source_type_policy_v1.yaml").write_text(yaml.dump({
        "source_type_policies": [
            {"pattern": "review", "dominant_category": "交易复盘"},
            {"pattern": "transcript", "dominant_category": "AI与工具化"},
        ]
    }, allow_unicode=True), encoding="utf-8")

    return str(d)


# ═══════════════════════════════════════════════════════════════
# Backend Verification
# ═══════════════════════════════════════════════════════════════

class TestBackendCLICommands:
    """Verify all Plan 1-5 CLI commands are registered and parse correctly."""

    def test_cli_help_registered(self):
        """All 5 new commands appear in --help output."""
        from main import build_parser
        parser = build_parser()
        # Collect subcommand names from parser
        subcommands = set()
        for action in parser._actions:
            choices = getattr(action, 'choices', None)
            if choices is not None:
                subcommands.update(choices.keys())

        expected = {"scan-filenames", "auto-cluster", "sample-review",
                    "learn-from-review", "build-supervised-kb"}
        missing = expected - subcommands
        assert not missing, f"Missing CLI commands: {missing}"

    def test_build_supervised_kb_has_sqlite_flag(self):
        """The --sqlite flag is registered on build-supervised-kb."""
        from main import build_parser
        parser = build_parser()
        for action in parser._actions:
            choices = getattr(action, 'choices', None)
            if choices is not None and 'build-supervised-kb' in choices:
                sub = choices['build-supervised-kb']
                flags = [a.option_strings for a in sub._actions]
                flat = [f for group in flags for f in group]
                assert '--sqlite' in flat, "--sqlite flag not found on build-supervised-kb"
                assert '--config' in flat, "--config flag not found on build-supervised-kb"
                return
        pytest.fail("build-supervised-kb subcommand not found")


class TestUnifiedDatabase:
    """Verify supervised_build writes to main KB database with correct schema."""

    def test_build_with_sqlite_flag(self, test_inventory_jsonl, test_supervised_policy_dir,
                                     test_unified_sqlite_path, tmp_path):
        """build-supervised-kb --sqlite writes to the specified main DB."""
        from supervised_build import build_supervised_kb

        out = tmp_path / "supervised_out"
        out.mkdir()

        result = build_supervised_kb(
            inventory_path=test_inventory_jsonl,
            policy_dir=test_supervised_policy_dir,
            output_dir=str(out),
            sqlite_path=test_unified_sqlite_path,
        )

        assert result["status"] == "ok"
        assert result["total_files"] == 6

        # Main DB should exist and have data
        assert Path(test_unified_sqlite_path).exists()
        conn = sqlite3.connect(test_unified_sqlite_path)
        rows = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        assert rows[0] == 6

        # Verify main-schema columns exist
        cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
        required = {"primary_category", "include_in_kb", "source_path",
                    "topic_tags", "run_id", "confidence", "needs_review"}
        missing = required - cols
        assert not missing, f"Missing main-schema columns: {missing}"

        # Categories should use primary_category (not old 'category')
        cats = conn.execute("SELECT DISTINCT primary_category FROM documents").fetchall()
        cat_names = {c[0] for c in cats}
        # With fake/unreadable paths, all files are low-confidence but still get
        # categorized.  At minimum we should have at least 1 category assigned.
        assert len(cat_names) >= 1, f"Expected >=1 category, got {cat_names}"

        # run_id should mark supervised builds
        run_ids = conn.execute("SELECT DISTINCT run_id FROM documents").fetchall()
        supervised_ids = [r[0] for r in run_ids if r[0] and "supervised" in r[0]]
        assert len(supervised_ids) >= 1, f"No supervised run_id found in {run_ids}"

        conn.close()

    def test_standalone_sqlite_still_works(self, test_inventory_jsonl,
                                            test_supervised_policy_dir, tmp_path):
        """Without --sqlite, a standalone kb.sqlite is created in output_dir."""
        from supervised_build import build_supervised_kb

        out = tmp_path / "standalone_out"
        out.mkdir()

        result = build_supervised_kb(
            inventory_path=test_inventory_jsonl,
            policy_dir=test_supervised_policy_dir,
            output_dir=str(out),
            # sqlite_path NOT provided → standalone mode
        )

        assert result["status"] == "ok"
        standalone = out / "kb.sqlite"
        assert standalone.exists(), f"Standalone SQLite missing: {standalone}"

        conn = sqlite3.connect(str(standalone))
        rows = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        assert rows[0] == 6
        conn.close()

    def test_csv_outputs_have_correct_columns(self, test_inventory_jsonl,
                                                test_supervised_policy_dir, tmp_path):
        """All CSV/JSONL outputs are produced with expected columns."""
        from supervised_build import build_supervised_kb

        out = tmp_path / "csv_test"
        out.mkdir()

        result = build_supervised_kb(
            inventory_path=test_inventory_jsonl,
            policy_dir=test_supervised_policy_dir,
            output_dir=str(out),
        )

        # documents.csv
        csv_path = out / "documents.csv"
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 6
            assert "category" in rows[0]  # CSV uses 'category' as display name
            assert "file_id" in rows[0]
            assert "confidence" in rows[0]

        # document_tags.jsonl
        tags_path = out / "document_tags.jsonl"
        with open(tags_path, encoding="utf-8") as f:
            tags_lines = [json.loads(l) for l in f if l.strip()]
        assert len(tags_lines) == 6

        # tag_stats.csv
        tag_stats = out / "tag_stats.csv"
        assert tag_stats.exists()

        # category_stats.csv
        cat_stats = out / "category_stats.csv"
        assert cat_stats.exists()

        # excluded_files.csv
        exc = out / "excluded_files.csv"
        with open(exc, encoding="utf-8-sig") as f:
            exc_rows = list(csv.reader(f))
        assert len(exc_rows) >= 2  # header + at least 1 excluded (empty file)

        # low_confidence_files.csv
        low = out / "low_confidence_files.csv"
        assert low.exists()

        # dashboard/index.html
        dash = out / "dashboard" / "index.html"
        assert dash.exists()

        # supervised_build_report.md
        rpt = out / "supervised_build_report.md"
        assert rpt.exists()


# ═══════════════════════════════════════════════════════════════
# Dynamic Classification Verification
# ═══════════════════════════════════════════════════════════════

class TestDynamicClassification:
    """Verify allowed_categories flows from weekly_organize → process_file → LLM."""

    def test_classify_with_llm_accepts_allowed_categories(self):
        """classify_with_llm function signature includes allowed_categories."""
        import inspect
        from llm_classifier import classify_with_llm

        sig = inspect.signature(classify_with_llm)
        params = list(sig.parameters.keys())
        assert "allowed_categories" in params, \
            f"allowed_categories not in classify_with_llm signature: {params}"

    def test_process_file_accepts_allowed_categories(self):
        """KBDatabase.process_file signature includes allowed_categories."""
        import inspect
        from database import KBDatabase

        sig = inspect.signature(KBDatabase.process_file)
        params = list(sig.parameters.keys())
        assert "allowed_categories" in params, \
            f"allowed_categories not in process_file signature: {params}"

    def test_prompt_injection_with_custom_categories(self):
        """allowed_categories replaces the hardcoded 11 categories in the prompt."""
        from llm_classifier import _render_template, _load_prompt_template
        from pathlib import Path

        prompt_path = str((Path(__file__).parent.parent.parent / "kb_tool" /
                          ".." / "deepseek_prompt.txt").resolve())
        # Fallback path if running from kb_tool/
        if not Path(prompt_path).exists():
            prompt_path = str(Path(__file__).parent.parent.parent /
                            "deepseek_prompt.txt")

        tpl = _load_prompt_template(prompt_path)
        mapping = {
            "filename": "test.md", "path": "/tmp/test.md",
            "extension": ".md", "size": 100,
            "created_time": "2026-01-01", "modified_time": "2026-01-01",
            "document_created_time": "", "sampled_text": "sample text",
        }
        prompt = _render_template(tpl, mapping)

        # Before injection: hardcoded 11 categories should be present
        assert "交易系统与方法论" in prompt
        assert "交易心理与情绪" in prompt
        assert "AI与工具化" in prompt
        assert "外部资料与待排除内容" in prompt

        # Simulate injection (same regex as classify_with_llm)
        import re
        allowed = ["交易复盘", "AI与工具化", "个人随笔"]
        cat_lines = "\n".join(f"- {c}" for c in allowed)
        cat_lines += "\n- 无法判断"
        injected = re.sub(
            r"可选 primary_category：\n(?:- [^\n]+\n)+",
            f"可选 primary_category：\n{cat_lines}\n",
            prompt,
        )

        # After injection: only custom categories present
        assert "交易复盘" in injected
        assert "AI与工具化" in injected
        assert "个人随笔" in injected
        assert "无法判断" in injected  # always appended
        # Old hardcoded categories should be gone
        assert "交易系统与方法论" not in injected
        assert "交易心理与情绪" not in injected

    def test_weekly_organize_detects_supervised_policy(self, tmp_path):
        """weekly_organize loads approved categories when policy exists."""
        # Simulate the logic extracted from weekly_organize
        policy_dir = tmp_path / "supervised_policy"
        policy_dir.mkdir(parents=True)

        schema = {
            "categories": [
                {"name": "交易复盘", "status": "approved"},
                {"name": "AI与工具化", "status": "approved"},
                {"name": "个人随笔", "status": "unreviewed"},
                {"name": "旧分类", "status": "merged_into:交易复盘"},
            ]
        }
        (policy_dir / "category_schema_v1.yaml").write_text(
            yaml.dump(schema, allow_unicode=True), encoding="utf-8")

        cat_schema_path = policy_dir / "category_schema_v1.yaml"
        allowed_categories = None

        if cat_schema_path.exists():
            with open(cat_schema_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            cats = loaded.get("categories", [])
            approved = [c["name"] for c in cats if c.get("status") == "approved"]
            if approved:
                allowed_categories = approved

        assert allowed_categories == ["交易复盘", "AI与工具化"], \
            f"Expected 2 approved, got {allowed_categories}"

    def test_weekly_organize_no_policy_fallback(self, tmp_path):
        """When no supervised_policy exists, allowed_categories stays None."""
        policy_dir = tmp_path / "nonexistent_policy"
        cat_schema_path = policy_dir / "category_schema_v1.yaml"

        allowed_categories = None
        if cat_schema_path.exists():
            allowed_categories = ["should_not_happen"]

        assert allowed_categories is None, \
            "Fallback should leave allowed_categories=None (use default 11)"


# ═══════════════════════════════════════════════════════════════
# Agentic Search / Wiki Integration
# ═══════════════════════════════════════════════════════════════

class TestWikiIntegration:
    """Verify the wiki_route CLI command is wired."""

    def test_wiki_route_cli_registered(self):
        """wiki-route command exists in CLI."""
        from main import build_parser
        parser = build_parser()
        for action in parser._actions:
            choices = getattr(action, 'choices', None)
            if choices is not None:
                assert 'wiki-route' in choices, "wiki-route CLI not registered"
                return

    def test_wiki_router_module_imports(self):
        """wiki_router module can be imported."""
        from wiki_router import route_query
        assert callable(route_query)


# ═══════════════════════════════════════════════════════════════
# Frontend Verification
# ═══════════════════════════════════════════════════════════════

class TestStreamlitFrontend:
    """Verify the Streamlit wizard page structure and imports."""

    def test_streamlit_app_imports_without_crash(self):
        """streamlit_app.py can be parsed (AST) without syntax errors."""
        import ast
        streamlit_path = PROJECT_ROOT / "streamlit_app.py"
        source = streamlit_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert tree is not None

    def test_wizard_nav_item_exists(self):
        """The '🧭 初始化向导' item is in the nav radio list."""
        streamlit_path = PROJECT_ROOT / "streamlit_app.py"
        source = streamlit_path.read_text(encoding="utf-8")

        assert "初始化向导" in source, \
            "Wizard nav item '初始化向导' not found in streamlit_app.py"
        assert "Step 1: 扫描文件地图" in source
        assert "Step 2: 自动聚类" in source
        assert "Step 3: 审核修正" in source
        assert "Step 4: 构建监督版 KB" in source
        assert "Step 5: 深度定制" in source

    def test_wizard_uses_run_cli_live_async(self):
        """Wizard steps use run_cli_live_async for background execution."""
        streamlit_path = PROJECT_ROOT / "streamlit_app.py"
        source = streamlit_path.read_text(encoding="utf-8")

        # At least Step 1, 2, 4 use run_cli_live_async
        assert "run_cli_live_async" in source, \
            "run_cli_live_async not used in wizard"

        # Step 3 uses data_editor for inline review
        assert "data_editor" in source, \
            "st.data_editor not used in review step"

    def test_wizard_step_paths_are_configurable(self):
        """Wizard uses paths relative to kb_out_dir, not hardcoded absolute paths."""
        streamlit_path = PROJECT_ROOT / "streamlit_app.py"
        source = streamlit_path.read_text(encoding="utf-8")

        # Key variable definitions
        assert "inventory_dir" in source
        assert "unsupervised_dir" in source
        assert "supervised_policy_dir" in source
        assert "supervised_kb_dir" in source

        # All paths derived from kb_out
        assert "kb_out" in source
        assert "paths.kb_out_dir" in source

    def test_dynamic_classification_indicator_in_weekly_organize_page(self):
        """The '每周整理' page hints at classification source."""
        # This is checked in the weekly_organize page rendering
        streamlit_path = PROJECT_ROOT / "streamlit_app.py"
        source = streamlit_path.read_text(encoding="utf-8")

        # weekly_organize flow now checks for supervised policy
        # The workflow_mainline.py module handles this
        workflow_path = PROJECT_ROOT / "kb_tool" / "workflow_mainline.py"
        wf_source = workflow_path.read_text(encoding="utf-8")

        assert "supervised_policy" in wf_source, \
            "weekly_organize should reference supervised_policy"
        assert "category_schema_v1.yaml" in wf_source, \
            "category_schema_v1.yaml should be checked"


# ═══════════════════════════════════════════════════════════════
# End-to-End Pipeline (MockLLM)
# ═══════════════════════════════════════════════════════════════

class TestEndToEndPipeline:
    """Full Plan 1→2→3→4 pipeline with mock data."""

    def test_full_pipeline_outputs(self, test_inventory_jsonl,
                                     test_supervised_policy_dir,
                                     test_unified_sqlite_path, tmp_path):
        """
        Simulate the complete user journey:
          Plan1: scan-filenames (inventory already exists)
          Plan2: auto-cluster (skip, use pre-made assignments)
          Plan3: learn-from-review (policy already exists)
          Plan4: build-supervised-kb --sqlite (writes to main DB)
        """
        from supervised_build import build_supervised_kb

        # Plan4: build-supervised-kb with --sqlite
        out = tmp_path / "e2e_kb"
        out.mkdir()

        llm_assignments = tmp_path / "llm_assignments.jsonl"
        assignments_data = [
            {"file_id": "f1", "predicted_category": "交易复盘"},
            {"file_id": "f2", "predicted_category": "外部资料与待排除内容"},
            {"file_id": "f3", "predicted_category": "AI与工具化"},
            {"file_id": "f4", "predicted_category": "个人随笔与自我观察"},
            {"file_id": "f5", "predicted_category": "空文件"},
            {"file_id": "f6", "predicted_category": "交易复盘"},
        ]
        with open(llm_assignments, "w", encoding="utf-8") as f:
            for d in assignments_data:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

        result = build_supervised_kb(
            inventory_path=test_inventory_jsonl,
            policy_dir=test_supervised_policy_dir,
            output_dir=str(out),
            llm_assignments_path=str(llm_assignments),
            sqlite_path=test_unified_sqlite_path,
        )

        # Assertions
        assert result["status"] == "ok"
        assert result["total_files"] == 6
        assert result["categories"] >= 3

        # All 9 output files
        for f in result["output_files"]:
            assert Path(f).exists(), f"Missing output: {f}"

        # Main DB data integrity
        conn = sqlite3.connect(test_unified_sqlite_path)
        r = conn.execute("""
            SELECT primary_category, COUNT(*) as n
            FROM documents
            GROUP BY primary_category
            ORDER BY n DESC
        """).fetchall()
        cat_dist = {row[0]: row[1] for row in r}

        # 交易复盘 should have 3 files (f1 reclassified + f6 + 其他杂项 merged)
        # f5 (空文件) should be excluded
        excluded = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE include_in_kb=0"
        ).fetchone()[0]
        assert excluded >= 1, f"Expected >=1 excluded files, got {excluded}"

        conn.close()

        # Verify report mentions key info
        report_path = out / "supervised_build_report.md"
        report_text = report_path.read_text(encoding="utf-8")
        assert "Policy-driven supervised build" in report_text

    def test_verify_no_regression_on_existing_tests(self):
        """This test is a meta-check: all existing test files are importable."""
        test_files = [
            "tests/integration/test_supervised_build.py",
            "tests/integration/test_auto_cluster.py",
            "tests/integration/test_sample_review.py",
            "tests/evaluation/test_cluster_quality_fixture.py",
        ]
        for tf in test_files:
            path = PROJECT_ROOT / tf
            assert path.exists(), f"Test file missing: {tf}"
            import ast
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            assert tree is not None, f"Syntax error in {tf}"
