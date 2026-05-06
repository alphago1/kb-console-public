"""
Integration test for supervised_build module.
Validates policy-driven classification pipeline with SQLite output.
"""
from __future__ import annotations

import csv, json, sqlite3, sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kb_tool"))


@pytest.fixture
def inventory_path(tmp_path):
    p = tmp_path / "inventory.jsonl"
    data = [
        {"file_id": "f1", "filename": "复盘0301.md", "extension": ".md", "parent_folder": ".",
         "path": "/fake/f1.md", "size": 1000, "filename_tokens": ["复盘", "0301"],
         "created_time": "2026-03-01", "modified_time": "2026-03-01", "time_month": "2026-03"},
        {"file_id": "f2", "filename": "合同模板.docx", "extension": ".docx", "parent_folder": ".",
         "path": "/fake/f2.docx", "size": 500, "filename_tokens": ["合同", "模板"],
         "created_time": "2026-01-01", "modified_time": "2026-01-01", "time_month": "2026-01"},
        {"file_id": "f3", "filename": "RAG选型.md", "extension": ".md", "parent_folder": ".",
         "path": "/fake/f3.md", "size": 2000, "filename_tokens": ["RAG", "选型"],
         "created_time": "2026-02-01", "modified_time": "2026-02-01", "time_month": "2026-02"},
        {"file_id": "f4", "filename": "空文件.docx", "extension": ".docx", "parent_folder": ".",
         "path": "/fake/f4.docx", "size": 0, "filename_tokens": ["空文件"],
         "created_time": "2026-03-01", "modified_time": "2026-03-01", "time_month": "2026-03"},
    ]
    with open(p, "w", encoding="utf-8") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return str(p)


@pytest.fixture
def policy_dir(tmp_path):
    import yaml
    d = tmp_path / "policy"
    d.mkdir()

    (d / "category_schema_v1.yaml").write_text(yaml.dump({
        "categories": [
            {"name": "股票交易", "status": "approved", "file_count": 147},
            {"name": "AI与工具化", "status": "approved", "file_count": 50},
            {"name": "其他杂项", "status": "merged_into:股票交易", "file_count": 10},
            {"name": "空文件", "status": "unreviewed", "file_count": 10},
        ]
    }, allow_unicode=True), encoding="utf-8")

    (d / "tag_ontology_v1.yaml").write_text(yaml.dump({
        "tags": [{"name": "止损", "frequency": 1}, {"name": "RAG", "frequency": 1}]
    }, allow_unicode=True), encoding="utf-8")

    (d / "classification_rules_v1.yaml").write_text(yaml.dump({
        "rules": [
            {"type": "merge", "sources": ["其他杂项"], "target": "股票交易", "confidence": 0.9,
             "source": "user_merge"},
            {"type": "reclassification", "pattern": "文件 复盘0301.md", "from": "股票交易",
             "to": "交易复盘", "confidence": 0.8, "source": "user_correction"},
        ]
    }, allow_unicode=True), encoding="utf-8")

    (d / "exclusion_rules_v1.yaml").write_text(yaml.dump({
        "excluded_categories": [{"name": "空文件", "file_count": 10, "user_confirmed": False}]
    }, allow_unicode=True), encoding="utf-8")

    (d / "source_type_policy_v1.yaml").write_text(yaml.dump({
        "source_type_policies": [
            {"pattern": "review", "dominant_category": "交易复盘", "sample_count": 5},
        ]
    }, allow_unicode=True), encoding="utf-8")

    return str(d)


@pytest.fixture
def llm_assignments_path(tmp_path):
    p = tmp_path / "llm_assignments.jsonl"
    data = [
        {"file_id": "f1", "filename": "复盘0301.md", "predicted_category": "股票交易", "ground_truth": "交易复盘"},
        {"file_id": "f2", "filename": "合同模板.docx", "predicted_category": "其他杂项", "ground_truth": "外部资料"},
        {"file_id": "f3", "filename": "RAG选型.md", "predicted_category": "AI与工具化", "ground_truth": "AI与工具化"},
        {"file_id": "f4", "filename": "空文件.docx", "predicted_category": "空文件", "ground_truth": "无法判断"},
    ]
    with open(p, "w", encoding="utf-8") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return str(p)


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "supervised_test"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def test_policy_loading(policy_dir):
    from supervised_build import load_policies, build_rule_index
    policies = load_policies(policy_dir)
    assert "category_schema_v1" in policies
    rules = build_rule_index(policies)
    assert "merge_map" in rules
    assert "其他杂项" in rules["merge_map"]
    assert rules["merge_map"]["其他杂项"] == "股票交易"


def test_classify_file(policy_dir, inventory_path):
    from supervised_build import load_policies, build_rule_index, classify_file
    import json as _json

    policies = load_policies(policy_dir)
    rules = build_rule_index(policies)

    with open(inventory_path, encoding="utf-8") as f:
        inv = [_json.loads(l) for l in f if l.strip()]

    # File 1: gets LLM cat "股票交易", reclassified to "交易复盘"
    r1 = classify_file(inv[0], rules, "股票交易")
    assert r1["category"] == "交易复盘"

    # File 2: gets LLM cat "其他杂项", merged to "股票交易"
    r2 = classify_file(inv[1], rules, "其他杂项")
    assert r2["category"] == "股票交易"

    # File 3: LLM cat "AI与工具化", approved
    r3 = classify_file(inv[2], rules, "AI与工具化")
    assert r3["category"] == "AI与工具化"

    # File 4: empty file, excluded
    r4 = classify_file(inv[3], rules, "空文件")
    assert r4["excluded"] is True


def test_build_supervised_kb(inventory_path, policy_dir, llm_assignments_path, output_dir):
    from supervised_build import build_supervised_kb

    result = build_supervised_kb(
        inventory_path=inventory_path,
        policy_dir=policy_dir,
        output_dir=output_dir,
        llm_assignments_path=llm_assignments_path,
    )

    assert result["status"] == "ok"
    assert result["total_files"] == 4
    assert result["categories"] >= 3
    assert result["excluded"] >= 1

    # Verify output files
    for f in result["output_files"]:
        assert Path(f).exists(), f"Missing: {f}"


def test_sqlite_integrity(inventory_path, policy_dir, llm_assignments_path, output_dir):
    from supervised_build import build_supervised_kb

    build_supervised_kb(inventory_path, policy_dir, output_dir, llm_assignments_path)
    db_path = Path(output_dir) / "kb.sqlite"

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
    assert rows[0] == 4
    cats = conn.execute("SELECT DISTINCT primary_category FROM documents").fetchall()
    assert len(cats) >= 3
    conn.close()


def test_csv_outputs(inventory_path, policy_dir, llm_assignments_path, output_dir):
    from supervised_build import build_supervised_kb

    build_supervised_kb(inventory_path, policy_dir, output_dir, llm_assignments_path)

    # documents.csv
    with open(Path(output_dir) / "documents.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 4
        assert "category" in rows[0]

    # tag_stats.csv
    with open(Path(output_dir) / "tag_stats.csv", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
        assert len(rows) >= 2  # header + data

    # excluded_files.csv
    with open(Path(output_dir) / "excluded_files.csv", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
        assert len(rows) >= 2  # header + 1 excluded


def test_dashboard_generated(inventory_path, policy_dir, llm_assignments_path, output_dir):
    from supervised_build import build_supervised_kb

    build_supervised_kb(inventory_path, policy_dir, output_dir, llm_assignments_path)
    dash = Path(output_dir) / "dashboard" / "index.html"
    assert dash.exists()
    html = dash.read_text(encoding="utf-8")
    assert "Supervised KB Dashboard" in html
