# Deep-Custom 诊断引擎 — 设计文档

> 版本 v1.0 | 2026-05-04 | 实现 Phase A 诊断流程

## 1. 定位

诊断引擎是 deep-custom 流程的**第一步**（对应产品 spec Phase A）。输入用户已有文本（笔记/文件/回答），输出结构化用户画像 `UserKnowledgeProfile`。如果信息不足，生成追问计划 `InterviewPlan`。

**核心原则**：诊断不是固定问卷。系统必须先利用已有信息生成画像草稿，再判断还缺什么，只问会改变知识库结构或组件选择的问题。

## 2. 数据流

```
已有文本（notes/answers/docs）
        │
        ▼
┌──────────────────┐
│  inference.py    │  逐段分析文本，提取 DiagnosisSignal
│  信号推断引擎     │  (signal_id, evidence, inferred_value, confidence)
└────────┬─────────┘
         │ signals: list[DiagnosisSignal]
         ▼
┌──────────────────┐
│  profile_builder │  聚合 signals → UserKnowledgeProfile
│  .py 画像构建器  │  计算每个字段的 confidence
└────────┬─────────┘
         │ profile: UserKnowledgeProfile
         ▼
┌──────────────────┐
│  gap_analyzer.py │  遍历 confidence_map，找出 < 阈值 的字段
│  信息缺口分析器  │  输出 MissingInformation（why_needed, priority, affects_components）
└────────┬─────────┘
         │ gaps: list[MissingInformation]
         ▼
┌──────────────────┐
│  interview_      │  从 question_bank 中匹配问题
│  planner.py      │  按 priority 排序，裁剪到合理数量 (5-8)
│  追问计划器      │  输出 InterviewPlan（含 why_this_question）
└────────┬─────────┘
         │ plan: InterviewPlan
         ▼
    用户回答 → 回到 inference.py（循环）
```

## 3. 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `schemas.py` | 5 个 Pydantic 数据模型 | - | 类型定义 |
| `question_bank.py` | 30-50 个场景化问题，按 domain/component 分类 | domain, components | list[InterviewQuestion] |
| `inference.py` | 从文本中推断用户特征信号 | 文本段落, 问题上下文 | list[DiagnosisSignal] |
| `gap_analyzer.py` | 分析画像中缺失/低置信度字段 | UserKnowledgeProfile, 阈值 | list[MissingInformation] |
| `interview_planner.py` | 根据缺口选择问题，生成追问计划 | list[MissingInformation], question_bank, UserKnowledgeProfile | InterviewPlan |
| `profile_builder.py` | 从 signals 构建/更新 UserKnowledgeProfile | list[DiagnosisSignal], 已有 profile (可选) | UserKnowledgeProfile |

## 4. 数据结构设计

### 4.1 UserKnowledgeProfile

用户知识画像——诊断的最终产物。共 20 个字段，分为 5 组：

**使用场景组** (4 fields)：
- `primary_goal`: str — 用户用知识库的首要目标（例："从交易记录中发现可优化的规则"）
- `core_scenarios`: list[str] — 核心使用场景（例：["每周复盘", "季度回顾", "写作素材检索"]）
- `core_domains`: list[dict] — 核心知识领域，每个领域含 name + description
- `corpus_scale_estimate`: dict — 文件量估算 {"docx": N, "md": N, "txt": N, "total": N}

**维护意愿组** (4 fields)：
- `maintenance_willingness`: str — "高"/"中"/"低"，决定自动化程度
- `current_workflow`: str — 当前工作流描述
- `source_file_types`: list[str] — 用户使用的文件类型
- `privacy_level`: str — "本地"/"可脱敏上传"/"可上传"

**结构偏好组** (4 fields)：
- `structure_preference`: str — "扁平"/"层级"/"时间优先"/"领域优先"
- `time_axis_preference`: str — "按创建时间"/"按修改时间"/"按文档内部时间"/"不关心"
- `source_type_policy`: dict — 对各种 source_type 的处理策略
- `exclusion_policy`: dict — 排除规则（文件类型、关键词、目录模式）

**消费入口组** (3 fields)：
- `human_reading_entry`: str — 用户通常会怎么打开知识库
- `ai_reading_entry`: str — AI 助手会怎么使用知识库
- `query_patterns`: list[str] — 典型查询模式

**输出偏好组** (3 fields)：
- `preferred_outputs`: list[str] — 用户想要的输出类型
- `report_preferences`: dict — 报告偏好（频率、粒度、风格）
- `enabled_components`: list[str] — 需要启用的组件
- `disabled_components`: list[str] — 不需要的组件

**元信息**：
- `confidence_map`: dict[str, float] — 每个字段的置信度 0.0-1.0

### 4.2 DiagnosisSignal

从文本中发现的一个信号。它是 profile 字段值的证据基础。

- `signal_id`: str — 唯一标识
- `source`: str — 信号来源（"inference_from_text" / "user_answer" / "file_analysis"）
- `evidence_text`: str — 支撑文本片段
- `inferred_value`: Any — 推断值
- `confidence`: float — 置信度
- `affects_decision`: str — 此信号影响哪个决策（"classification_policy" / "query_strategy" / "report_template" / "organize_schedule"）

### 4.3 MissingInformation

画像中的信息缺口。

- `field_name`: str — 缺失或低置信的字段名
- `current_confidence`: float — 当前置信度
- `why_needed`: str — 为什么需要这个信息
- `possible_questions`: list[str] — 候选问题文本
- `affects_components`: list[str] — 受影响组件
- `priority`: str — "critical" / "high" / "medium" / "low"

### 4.4 InterviewPlan

一次追问会话的完整计划。

- `existing_profile_summary`: str — 已有画像摘要
- `missing_information`: list[MissingInformation] — 信息缺口列表
- `selected_questions`: list[InterviewQuestion] — 选中要问的问题
- `skipped_questions`: list[dict] — 跳过的问题及原因
- `reason_for_each_question`: dict[str, str] — question_id → 为什么选这个问题

### 4.5 InterviewQuestion

一个问题模板。

- `question_id`: str — 唯一标识
- `question_text`: str — 问题文本
- `question_type`: str — "single_choice" / "multi_choice" / "open"
- `options`: list[str] | None — 选项（选择型）
- `why_this_question`: str — 为什么需要问这个问题
- `affects_fields`: list[str] — 影响的 profile 字段
- `affects_components`: list[str] — 影响的组件

## 5. CLI 命令

### diagnosis-from-notes
```
python main.py diagnosis-from-notes --config config.yaml \
  --input previous_answers.md \
  --output kb_out/diagnosis/session_001/
```
输出：`profile_draft.json` (UserKnowledgeProfile)

### diagnosis-plan
```
python main.py diagnosis-plan --config config.yaml \
  --profile kb_out/diagnosis/session_001/profile_draft.json \
  --output kb_out/diagnosis/session_001/
```
输出：`interview_plan.json` (InterviewPlan)

## 6. Question Bank 设计原则

1. **场景化而非抽象化**：不问"你喜欢什么结构"，问"你平时找文件时是先想'大概什么时候写的'还是先想'大概是关于什么的'"
2. **按组件关联分类**：每个问题标注 `affects_components`，只问会改变实际配置的问题
3. **可跳过的有原因**：interview_planner 跳过的每个问题必须记录原因
4. **支持文本导入**：用户可以用自然语言回答，inference.py 从中提取信号，不强制走问答格式
5. **不一次性全问**：30-50 个问题分布在不同的 gap 场景中，每次访谈最多 5-8 个

## 7. 与现有 kB_tool 的关系

- 所有输出写入 `kb_out/diagnosis/`，遵循现有 security boundary
- 使用 `config.yaml` → `storage.output_dir` 作为基准路径
- 不依赖 scanner / database / chunker（Phase A 只做文本分析）
- 不调用 LLM（v1 用规则引擎 + 关键词，v2 可接入 LLM 做更精确的信号抽取）
