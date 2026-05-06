from __future__ import annotations

import re
import uuid
from typing import Any

from .schemas import DiagnosisSignal

# ── Signal extraction patterns ──
# Each rule: (field_name, regex or keyword list, extractor fn, affects_decision)
# v1 uses rule-based extraction. v2 can replace with LLM-based extraction.

_FIELD_PATTERNS: list[tuple[str, list[str], str, str]] = [
    (
        "primary_goal",
        [
            "知识库.*目标|目的是|想解决|建立.*为了|希望.*系统|核心需求",
            "整理.*归档|查找|检索|搜索",
            "发现.*规律|洞察|分析|看出|没看到",
            "辅助.*写作|写作.*素材|成文|可发表",
            "构建.*决策|认知.*系统|个人.*系统|决策支持",
        ],
        "",
        "classification_policy",
    ),
    (
        "core_scenarios",
        [
            "场景|使用.*场景|平时.*会|习惯|每周|每月|季度|复盘|回顾",
            r"查.*一下|找.*文件|搜索|检索",
            "写作.*前|写.*之前|准备.*写",
            "交易.*前|做.*决策|决定.*之前",
        ],
        "",
        "query_strategy",
    ),
    (
        "core_domains",
        [
            "领域|关注|主要.*内容|涉及|方向",
            "交易|股票|期货|投资|金融",
            "AI|人工智能|工具|自动化|编程|技术|开发",
            "写作|创作|内容|公众号|博客",
            "心理|情绪|认知|自我|成长|思考",
            "职业|工作|离职|自由职业|收入",
        ],
        "",
        "classification_policy",
    ),
    (
        "maintenance_willingness",
        [
            "自动.*整理|全自动|不要.*手动|不想.*维护|懒|没时间",
            "每周.*花.*时间|可以.*检查|检查.*结果",
            "愿意.*定期.*回顾|调整.*分类|迭代",
            "深度.*参与|设计.*知识库",
        ],
        "",
        "organize_schedule",
    ),
    (
        "current_workflow",
        [
            "现在.*管理|当前.*方式|目录|文件夹|分类|笔记软件",
            "桌面.*文件|随手.*建|习惯.*写",
            "Obsidian|Notion|Logseq|Roam|飞书|语雀",
        ],
        "",
        "classification_policy",
    ),
    (
        "source_file_types",
        [
            r"\.docx|Word|word",
            r"\.md|markdown|md 文件",
            r"\.txt|纯文本|文本文件",
            "其他.*格式|PDF|图片|截图",
        ],
        "",
        "classification_policy",
    ),
    (
        "privacy_level",
        [
            "敏感|隐私|不能.*上传|本地|留在.*本地",
            "脱敏|去掉.*名字|去掉.*个人信息",
            "不.*在意|不.*关心|质量.*第一|分析.*第一",
        ],
        "",
        "classification_policy",
    ),
    (
        "structure_preference",
        [
            "按.*主题|按.*领域|按.*分类",
            "按.*时间|按.*月份|按.*日期",
            "扁平|层级|嵌套|多个.*层级",
        ],
        "",
        "classification_policy",
    ),
    (
        "time_axis_preference",
        [
            "文档.*内容.*时间|内容.*日期|写的.*日期",
            "创建.*时间|修改.*时间|最后.*编辑",
            "不.*关心.*时间|时间.*无所谓",
        ],
        "",
        "classification_policy",
    ),
    (
        "exclusion_policy",
        [
            "排除|不需要|不希望.*进入|不要.*纳入|过滤",
            "讲义|课件|课程.*材料|电子书",
            "合同|证件|简历",
            "下载.*资料|转载|外部.*文章|别人.*发给",
        ],
        "",
        "classification_policy",
    ),
    (
        "human_reading_entry",
        [
            "浏览.*文件夹|打开.*目录|文件.*浏览器",
            "搜索.*框|搜索.*关键词|Ctrl.*F",
            "AI.*助手|AI.*帮.*找|让.*AI",
            "Dashboard|大盘|看.*统计",
        ],
        "",
        "query_strategy",
    ),
    (
        "ai_reading_entry",
        [
            "实时.*搜索|每次.*搜|Agent",
            "Context.*Bundle|打包|丢.*进去|一次.*给",
            "MCP|Claude.*Desktop|Cursor|集成",
        ],
        "",
        "query_strategy",
    ),
    (
        "query_patterns",
        [
            "找.*具体.*文件|知道.*名字|知道.*叫什么",
            "时间段|时间.*范围|时间.*所有",
            "对比|比较|变化|跨.*时间",
            "反复.*提到|反复.*出现|主题.*变化",
            "写作.*潜力|写作.*候选|可以.*写",
        ],
        "",
        "query_strategy",
    ),
    (
        "preferred_outputs",
        [
            "每周.*整理|每周.*摘要|周报|这周",
            "月度.*复盘|月报|这个月",
            "季度.*认知|季度.*报告|跨.*时间.*变化",
            "知识.*盲区|遗漏|应该.*关注.*没",
            "写作.*素材|写作.*汇总|可以.*成文",
            "个人.*画像|认知.*画像|决策.*风格",
            "Dashboard|可视化|大盘",
        ],
        "",
        "report_template",
    ),
    (
        "report_preferences",
        [
            "深度.*优先|一次.*看够|全量|详细",
            "频率.*优先|每周.*简短|摘要",
            "都要|周报.*季报.*都要",
            "先.*看看|不确定.*什么|试试",
        ],
        "",
        "report_template",
    ),
    (
        "source_type_policy",
        [
            "原创.*摘录|原创.*非原创|原创.*外部|混.*一起",
            "分开|不同.*分类|独立.*空间",
            "来源.*标签|标注.*来源|备注",
        ],
        "",
        "classification_policy",
    ),
    (
        "corpus_scale_estimate",
        [
            r"几十.*篇|几十.*个|<100|< 100",
            r"几百.*篇|几百.*个|100.*500|\d{3}.*篇",
            r"上千|>.*1000|> 1000|上千.*篇",
        ],
        "",
        "organize_schedule",
    ),
]


def _extract_value(text: str, field: str, patterns: list[str]) -> Any:
    """Extract the most likely value for a field from matching text segments."""
    matches: list[str] = []

    for pat in patterns:
        found = re.findall(pat, text, re.IGNORECASE)
        if not found:
            continue
        if isinstance(found[0], str):
            matches.extend(found)
        elif isinstance(found[0], tuple):
            for t in found:
                matches.extend(s for s in t if isinstance(s, str) and s)
        else:
            matches.extend(str(m) for m in found)

    if not matches:
        return None

    if field in ("core_scenarios", "core_domains", "source_file_types", "query_patterns",
                 "preferred_outputs", "enabled_components", "disabled_components"):
        return list(dict.fromkeys(matches))[:10]

    return matches[0] if matches else None


def _compute_confidence(field: str, matches: list[str], extracted_value: Any) -> float:
    if extracted_value is None:
        return 0.0
    if field == "primary_goal" and len(matches) >= 2:
        return 0.7
    if field == "core_domains" and len(matches) >= 3:
        return 0.7
    if field == "maintenance_willingness" and len(matches) >= 1:
        return 0.6
    if field == "privacy_level" and len(matches) >= 1:
        return 0.6
    if len(matches) >= 2:
        return 0.65
    return 0.5


def infer_signals_from_text(text: str) -> list[DiagnosisSignal]:
    """Extract DiagnosisSignals from unstructured text using rule-based pattern matching."""
    signals: list[DiagnosisSignal] = []

    for field, patterns, _, affects in _FIELD_PATTERNS:
        val = _extract_value(text, field, patterns)
        if val is not None:
            conf = _compute_confidence(field, patterns, val)
            signals.append(DiagnosisSignal(
                signal_id=f"SIG-{field}-{uuid.uuid4().hex[:6]}",
                source="inference_from_text",
                evidence_text=text[:500],
                inferred_value=val,
                confidence=conf,
                affects_decision=field,
            ))

    return signals


def infer_signal_from_answer(question_id: str, question: str, answer: str,
                              affects_fields: list[str],
                              affects_components: list[str]) -> DiagnosisSignal:
    """Create a DiagnosisSignal from a user's direct answer to a question."""
    primary_field = affects_fields[0] if affects_fields else "unknown"
    return DiagnosisSignal(
        signal_id=f"ANS-{question_id}-{uuid.uuid4().hex[:6]}",
        source="user_answer",
        evidence_text=f"Q: {question}\nA: {answer}",
        inferred_value=answer,
        confidence=0.85,
        affects_decision=affects_components[0] if affects_components else "classification_policy",
    )
