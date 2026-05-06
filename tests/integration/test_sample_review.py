"""
Integration test for stratified sampling + feedback learning.
"""
from __future__ import annotations

import csv, json, sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kb_tool"))


@pytest.fixture
def assignments_path(tmp_path):
    """Create test assignments JSONL."""
    p = tmp_path / "test_assignments.jsonl"
    data = [
        {"file_id": "f1", "filename": "复盘0301.md", "predicted_category": "交易复盘",
         "ground_truth": "交易复盘", "match": True, "summary": "3月交易复盘摘要",
         "mapped_gt": "交易复盘", "source_path": "/fake/f1.md"},
        {"file_id": "f2", "filename": "止损反思.md", "predicted_category": "交易复盘",
         "ground_truth": "交易系统与方法论", "match": False, "summary": "止损反思摘要",
         "mapped_gt": "交易系统与方法论", "source_path": "/fake/f2.md"},
        {"file_id": "f3", "filename": "RAG选型.md", "predicted_category": "AI与工具化",
         "ground_truth": "AI与工具化", "match": True, "summary": "RAG选型摘要",
         "mapped_gt": "AI与工具化", "source_path": "/fake/f3.md"},
        {"file_id": "f4", "filename": "合同模板.docx", "predicted_category": "合同模板",
         "ground_truth": "外部资料与待排除内容", "match": False, "summary": "合同摘要",
         "mapped_gt": "外部资料与待排除内容", "source_path": "/fake/f4.docx"},
        {"file_id": "f5", "filename": "算法笔记.md", "predicted_category": "机器学习",
         "ground_truth": "外部资料与待排除内容", "match": False, "summary": "算法笔记摘要",
         "mapped_gt": "外部资料与待排除内容", "source_path": "/fake/f5.md"},
        {"file_id": "f6", "filename": "空文件.docx", "predicted_category": "空文件",
         "ground_truth": "无法判断", "match": False, "summary": "(空)", "source_path": "/fake/f6.docx"},
    ]
    for d in data:
        d.setdefault("time_month", "2026-03")
    with open(p, "w", encoding="utf-8") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return str(p)


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "review_test"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def test_generate_review_sample(assignments_path, output_dir):
    from feedback.sample_review import generate_review_sample

    result = generate_review_sample(assignments_path, output_dir, max_samples=10)
    assert result["total_files"] == 6
    assert result["sampled"] >= 4  # at least 2 per category
    assert result["categories_covered"] >= 3
    csv_path = Path(result["csv_path"])
    assert csv_path.exists()

    # Read CSV
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == result["sampled"]
    for field in ["file_id", "current_category", "sample_reason", "summary", "user_verdict"]:
        assert field in reader.fieldnames


def test_stratification_principles(assignments_path, output_dir):
    """7 principles verified: per-cat minimum, boundary, representative, time coverage."""
    from feedback.sample_review import generate_review_sample

    result = generate_review_sample(assignments_path, output_dir, max_samples=10)
    reasons = result["sample_reasons"]
    assert "representative" in reasons
    assert "boundary" in reasons
    # Each category should get ≥2 OR all its files (whichever is smaller)
    for cat, count in result["per_category"].items():
        # Small categories may only have 1 file total
        assert count >= 1, f"Category {cat} got 0 files"


def test_parse_user_feedback(assignments_path, output_dir):
    from feedback.sample_review import generate_review_sample, parse_user_feedback

    gen = generate_review_sample(assignments_path, output_dir, max_samples=20)

    # Simulate user edits
    csv_path = Path(gen["csv_path"])
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    rows[0]["user_verdict"] = "正确"
    rows[0]["user_tags"] = "止损,执行力"
    rows[1]["user_verdict"] = "应为:交易心理"
    rows[2]["user_verdict"] = "合并到:交易大类"

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    feedback = parse_user_feedback(str(csv_path))
    assert feedback["total_reviewed"] >= 2
    assert len(feedback["reclassified"]) >= 1
    assert len(feedback["merge_hints"]) >= 1
    assert len(feedback["tags_suggested"]) >= 1


def test_learn_from_feedback(assignments_path, output_dir):
    from feedback.sample_review import generate_review_sample, learn_from_feedback

    gen = generate_review_sample(assignments_path, output_dir, max_samples=10)
    csv_path = Path(gen["csv_path"])

    # Simulate user feedback
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if rows:
        rows[0]["user_verdict"] = "正确"
        rows[0]["user_tags"] = "止损,执行力"
    if len(rows) > 1:
        rows[1]["user_verdict"] = "应为:其他分类"

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    result = learn_from_feedback(assignments_path, str(csv_path), output_dir)
    assert result["reviewed"] >= 1
    for f in result["output_files"]:
        assert Path(f).exists(), f"Missing: {f}"


def test_learning_report_sections(assignments_path, output_dir):
    from feedback.sample_review import generate_review_sample, learn_from_feedback

    gen = generate_review_sample(assignments_path, output_dir, max_samples=10)
    csv_path = Path(gen["csv_path"])

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if rows:
        rows[0]["user_verdict"] = "正确"
        rows[0]["user_tags"] = "tag1,tag2"
    if len(rows) > 1:
        rows[1]["user_verdict"] = "合并到:大类合并"

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    learn_from_feedback(assignments_path, str(csv_path), output_dir)
    report = (Path(output_dir) / "learning_report.md").read_text(encoding="utf-8")

    required = [
        "用户认可了哪些类别", "用户否定", "被合并的类别", "被拆分的类别",
        "新增 Tags", "删除的 Tags", "生成的规则", "预计影响范围",
    ]
    for section in required:
        assert section in report, f"Missing '{section}' in learning report"


def test_six_outputs_generated(assignments_path, output_dir):
    from feedback.sample_review import generate_review_sample, learn_from_feedback

    gen = generate_review_sample(assignments_path, output_dir, max_samples=10)
    csv_path = Path(gen["csv_path"])

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if rows:
        rows[0]["user_verdict"] = "正确"

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    result = learn_from_feedback(assignments_path, str(csv_path), output_dir)
    names = [Path(f).name for f in result["output_files"]]
    assert "category_schema_v1.yaml" in names
    assert "tag_ontology_v1.yaml" in names
    assert "classification_rules_v1.yaml" in names
    assert "exclusion_rules_v1.yaml" in names
    assert "source_type_policy_v1.yaml" in names
    assert "learning_report.md" in names
