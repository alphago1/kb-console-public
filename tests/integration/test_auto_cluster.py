"""
Integration test for content-aware clustering (2-round LLM pipeline).
All tests use MockLLM — no real API calls.
"""
from __future__ import annotations

import json, sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kb_tool"))

# Mock responses for Round 1 (summarization) and Round 2 (classification)
MOCK_SUMMARIES = [
    {"filename": "trading_review_2026_03.md",
     "summary": "2026年3月交易复盘，23笔交易胜率47.8%，止损执行率85%。关注追高和过早止盈问题，强调用规则代替感觉。"},
    {"filename": "止损执行力反思.md",
     "summary": "反思止损执行不到位的根本原因：心理恐惧和仓位管理不当。提出将止损重新定义为获取市场信息而非认错。"},
    {"filename": "仓位管理问题记录.md",
     "summary": "记录仓位忽大忽小的问题，分析原因与止损犹豫的关联，提出2%单笔风险控制规则。"},
    {"filename": "交易系统框架v3.md",
     "summary": "交易系统v3版本框架文档，涵盖入场策略、止损规则、仓位公式和复盘流程的完整方法论。"},
    {"filename": "入场策略对比分析.md",
     "summary": "对比突破入场、回调入场和趋势跟踪三种策略的优劣，用历史数据计算胜率和盈亏比。"},
    {"filename": "RAG知识库技术选型.md",
     "summary": "探讨RAG知识库技术选型：tag-first vs embedding-first，提出多维标注的个人知识库架构方案。"},
    {"filename": "Agent多轮对话设计.md",
     "summary": "设计Agent多轮工具调用的架构，包括上下文管理、工具注册和权限控制机制。"},
    {"filename": "embedding模型对比测试.md",
     "summary": "测试对比多个embedding模型在中文文档检索中的表现，评估召回率和推理速度。"},
    {"filename": "Q1个人反思.md",
     "summary": "2026年Q1个人反思：交易执行力提升，学习RAG和Agent技术，社交投入不足，Q2目标调整。"},
    {"filename": "习惯追踪2月.md",
     "summary": "2月习惯追踪：运动坚持2-3次/周，阅读每日30分钟，冥想放弃需重新捡起，交易日志坚持最好。"},
    {"filename": "知识库项目迭代想法.md",
     "summary": "本地知识库项目迭代方向：tag-first个性化召回、wiki做缓存层、多维文档标注、反馈闭环机制。"},
    {"filename": "追高冲动分析.md",
     "summary": "深入分析追高冲动的心理学根源（FOMO），提出用规则代替感觉的行动方案和入场checklist。"},
    {"filename": "合同模板-采购协议.md",
     "summary": "标准采购合同模板，包含合同标的、金额、付款方式、交付时间和违约责任条款，属于行政模板。"},
    {"filename": "授权书模板.docx",
     "summary": "空白授权书模板文件，包含授权人、被授权人、授权范围和期限的标准格式，属于证件类模板。"},
    {"filename": "交易心理文章草稿.md",
     "summary": "关于交易心理的未完成文章草稿，主题是'最大的敌人是自己'，涵盖追高和过早止盈的心理分析。"},
    {"filename": "0305临时笔记.md",
     "summary": "3月5日的临时笔记，内容涉及当日计划和零散想法，未整理和分类。"},
    {"filename": "0301盘前计划.md",
     "summary": "3月1日盘前交易计划，列出当日关注股票、关键价位和操作策略，属于日常交易准备。"},
    {"filename": "unknown_doc_123.md",
     "summary": "内容模糊的文档，无明显主题或关键信息，无法判断具体用途和分类。"},
]

MOCK_CLASSIFICATION = {
    "categories": [
        {"name": "交易复盘与执行", "description": "交易复盘、止损反思、仓位管理、盘前计划等",
         "file_indices": [1, 2, 3, 12, 17]},
        {"name": "交易系统与方法", "description": "交易系统框架、入场策略、方法论",
         "file_indices": [4, 5]},
        {"name": "AI与技术工具", "description": "RAG、Agent、embedding、模型等技术文档",
         "file_indices": [6, 7, 8]},
        {"name": "个人随笔与成长", "description": "个人反思、习惯追踪、季度总结",
         "file_indices": [9, 10]},
        {"name": "项目与写作", "description": "项目想法、写作草稿",
         "file_indices": [11, 15]},
        {"name": "合同模板与证件", "description": "合同、授权书等行政模板",
         "file_indices": [13, 14]},
        {"name": "临时与杂项", "description": "临时笔记、未整理内容",
         "file_indices": [16, 18]},
    ],
    "uncertain_indices": [],
    "summary": "共7个分类：交易复盘、交易系统、AI技术、个人随笔、项目写作、合同模板、临时杂项",
}

# Mock LLM response dispatcher
_call_count = [0]


def _mock_call_llm(prompt: str, client=None, max_retries=3, timeout=120):
    _call_count[0] += 1
    if "写一个" in prompt and "摘要" in prompt:
        return {"summaries": MOCK_SUMMARIES}
    return MOCK_CLASSIFICATION


@pytest.fixture(autouse=True)
def reset_call_count():
    _call_count[0] = 0


@pytest.fixture
def inventory_path():
    p = PROJECT_ROOT / "tests" / "fixtures" / "inventory" / "test_docs_inventory.jsonl"
    return str(p)


@pytest.fixture
def full_texts_path():
    p = PROJECT_ROOT / "tests" / "fixtures" / "inventory" / "test_full_texts.jsonl"
    return str(p)


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "content_cluster_test"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def test_module_imports():
    from auto_cluster import (run_experiment, generate_summaries_concurrent,
                               classify_from_summaries, build_assignments, compute_metrics)
    assert run_experiment is not None


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_full_two_round_pipeline(mock_client, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment

    result = run_experiment(
        inventory_path=inventory_path,
        output_dir=output_dir,
        target=7,
        full_texts_path=full_texts_path,
    )

    assert result["status"] == "ok"
    assert result["total_files"] == 18
    assert result["categories_found"] == 7
    assert result["accuracy"] >= 0.7
    assert _call_count[0] >= 2  # at least 1 summary + 1 classification


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_output_files(mock_client, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment

    result = run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )

    for f in result["output_files"]:
        assert Path(f).exists(), f"Missing: {f}"

    report = (Path(output_dir) / "cluster_report.md").read_text(encoding="utf-8")
    assert "内容感知分类" in report
    assert "全文理解" in report


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_consolidated_folders(mock_client, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment

    run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )

    consolidated = Path(output_dir) / "consolidated"
    assert consolidated.exists()
    subdirs = list(consolidated.iterdir())
    assert len(subdirs) >= 5


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_csv_match_column(mock_client, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment
    import csv

    run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=7, full_texts_path=full_texts_path,
    )

    with open(Path(output_dir) / "clustered_files.csv", encoding="utf-8") as cf:
        rows = list(csv.DictReader(cf))
    assert len(rows) == 18
    assert "predicted_category" in rows[0]
    assert "ground_truth" in rows[0]
    assert "match" in rows[0]


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_target_auto_calc(mock_client, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment

    result = run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        target=None, full_texts_path=full_texts_path,
    )
    assert result["target"] == max(5, __import__("math").ceil(18 / 30))


@patch("auto_cluster._call_llm", side_effect=_mock_call_llm)
@patch("auto_cluster._get_client")
def test_dry_run(mock_client, mock_llm, inventory_path, output_dir, full_texts_path):
    from auto_cluster import run_experiment

    result = run_experiment(
        inventory_path=inventory_path, output_dir=output_dir,
        dry_run=True, full_texts_path=full_texts_path,
    )
    assert result["status"] == "dry_run"
    assert _call_count[0] == 0
