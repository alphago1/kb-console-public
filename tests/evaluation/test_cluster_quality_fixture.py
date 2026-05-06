"""
Evaluation: content-aware clustering quality (2-round LLM with full text summaries).
"""
from __future__ import annotations

import json, sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kb_tool"))

MOCK_SUMMARIES = [
    {"filename": "trading_review_2026_03.md", "summary": "3月交易复盘，23笔胜率47.8%，止损执行率85%"},
    {"filename": "止损执行力反思.md", "summary": "止损执行反思，将止损从认错重新定义为获取信息"},
    {"filename": "仓位管理问题记录.md", "summary": "仓位忽大忽小问题，提出2%单笔风险控制"},
    {"filename": "交易系统框架v3.md", "summary": "交易系统v3框架，含入场止损仓位复盘完整方法论"},
    {"filename": "入场策略对比分析.md", "summary": "对比突破/回调/趋势三种入场策略的优劣"},
    {"filename": "RAG知识库技术选型.md", "summary": "RAG技术选型：tag-first vs embedding-first架构"},
    {"filename": "Agent多轮对话设计.md", "summary": "Agent多轮工具调用架构设计"},
    {"filename": "embedding模型对比测试.md", "summary": "中文embedding模型对比测试"},
    {"filename": "Q1个人反思.md", "summary": "Q1反思：交易提升，学习RAG，社交不足"},
    {"filename": "习惯追踪2月.md", "summary": "2月习惯追踪：运动坚持，冥想放弃需重捡"},
    {"filename": "知识库项目迭代想法.md", "summary": "本地知识库迭代：tag-first、wiki缓存、多维标注"},
    {"filename": "追高冲动分析.md", "summary": "追高冲动心理学根源(FOMO)，规则代替感觉"},
    {"filename": "合同模板-采购协议.md", "summary": "标准采购合同模板，含金额付款交付违约条款"},
    {"filename": "授权书模板.docx", "summary": "空白授权书模板，含授权人范围和期限"},
    {"filename": "交易心理文章草稿.md", "summary": "未完成交易心理文章，最大敌人是自己"},
    {"filename": "0305临时笔记.md", "summary": "3月5日临时笔记，当日计划和零散想法"},
    {"filename": "0301盘前计划.md", "summary": "3月1日盘前计划，关注股票和关键价位"},
    {"filename": "unknown_doc_123.md", "summary": "内容模糊，无明显主题或关键信息"},
]

MOCK_CLASSIFICATION = {
    "categories": [
        {"name": "交易复盘", "description": "交易复盘反思止损仓位", "file_indices": [1,2,3,12,17]},
        {"name": "交易系统方法论", "description": "交易系统框架和入场策略", "file_indices": [4,5]},
        {"name": "AI与工具化", "description": "RAG Agent embedding技术", "file_indices": [6,7,8]},
        {"name": "个人随笔", "description": "反思习惯季度总结", "file_indices": [9,10]},
        {"name": "项目与写作", "description": "项目想法写作草稿", "file_indices": [11,15]},
        {"name": "合同模板", "description": "合同授权书行政模板", "file_indices": [13,14]},
        {"name": "临时杂项", "description": "临时笔记未整理", "file_indices": [16,18]},
    ],
    "uncertain_indices": [],
}

_call_count = [0]


def _mock_call_llm(prompt, client=None, max_retries=3, timeout=120):
    _call_count[0] += 1
    # Round 1: "请为每个文件写一个 100-200 字的中文摘要"
    if "写一个" in prompt and "摘要" in prompt:
        return {"summaries": MOCK_SUMMARIES}
    # Round 2: classification
    return MOCK_CLASSIFICATION


@pytest.fixture(autouse=True)
def reset_call():
    _call_count[0] = 0


@pytest.fixture
def inventory_path():
    return str(PROJECT_ROOT / "tests" / "fixtures" / "inventory" / "test_docs_inventory.jsonl")


@pytest.fixture
def full_texts_path():
    return str(PROJECT_ROOT / "tests" / "fixtures" / "inventory" / "test_full_texts.jsonl")


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "eval_content"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_two_round_pipeline_runs(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    result = run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )
    assert result["status"] == "ok"
    assert result["categories_found"] == 7
    assert _call_count[0] >= 2


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_accuracy_with_mapping(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    """After majority-vote GT mapping, accuracy should be high on mock data."""
    from auto_cluster import run_experiment
    result = run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )
    assert result["accuracy"] >= 0.7
    assert "cluster_to_gt_mapping" in result


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_trading_files_in_trading_cluster(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    import csv
    run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )
    with open(Path(output_dir) / "clustered_files.csv", encoding="utf-8") as cf:
        rows = list(csv.DictReader(cf))
    trading_gt = {"交易复盘", "交易系统与方法论", "交易心理与情绪", "交易记录"}
    trading = [r for r in rows if r["ground_truth"] in trading_gt]
    # After mapping, most trading files should match
    matched = sum(1 for r in trading if r["match"] == "True")
    assert matched >= len(trading) * 0.6


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_noise_files_excluded(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    import csv
    run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )
    with open(Path(output_dir) / "clustered_files.csv", encoding="utf-8") as cf:
        rows = list(csv.DictReader(cf))
    noise = [r for r in rows if "合同" in r["filename"] or "授权" in r["filename"]]
    # After GT mapping, noise files should match their GT
    for r in noise:
        assert r["match"] == "True", f"Noise file {r['filename']} should match after GT mapping"


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_report_has_sections(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )
    report = (Path(output_dir) / "cluster_report.md").read_text(encoding="utf-8")
    for section in ["内容感知分类", "总体结果", "发现的分类", "Per-Category", "混淆矩阵"]:
        assert section in report, f"Missing '{section}'"


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_target_calc(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    import math
    result = run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=None, full_texts_path=full_texts_path,
    )
    assert result["target"] == max(5, math.ceil(18 / 30))


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_consolidated_structure(mock_cl, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )
    consolidated = Path(output_dir) / "consolidated"
    assert consolidated.exists()
    # Fake file paths don't exist, but category folders are still created
    assert len(list(consolidated.iterdir())) >= 1
