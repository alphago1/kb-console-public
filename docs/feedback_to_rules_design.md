# Feedback-to-Rules System Design

> 版本: v1 | 分支: feature/deep-custom-diagnosis-baseline

## 设计目标

用户对 sample-run 的反馈不只是一次性修文件，而是转成长期规则，并允许修改知识库结构。

## 数据流

```
user_feedback.yaml
    │
    ▼
feedback-plan ──► feedback_rule_plan.yaml
    │               ├── policy_diff.md
    │               ├── structure_diff.md
    │               ├── affected_sample_files.csv
    │               └── expected_changes.md
    │
    │  (用户审阅确认)
    │
    ▼
feedback-apply ──► v2 blueprint/
                     ├── updated_classification_policy.yaml
                     ├── updated_source_type_policy.yaml
                     ├── updated_exclusion_policy.yaml
                     ├── updated_folder_schema.yaml
                     ├── updated_component_plan.yaml
                     ├── updated_knowledge_blueprint.md
                     └── rule_change_log.md
```

## 四大反馈类型

### 1. 文件级纠错 (File-Level)

| 纠错类型 | 操作 | 示例 |
|---------|------|------|
| exclude | 标记文件不应纳入 | 电子书被误摄入 |
| recategorize | 修改分类 | 交易心理分析 → 交易复盘 |
| mark_external | 标注为外部资料 | 转载文章标注来源 |
| mark_original | 标注为原创 | 误标外部资料的文件 |

### 2. 规则级反馈 (Rule-Level)

批量规则，匹配条件 + 操作：

- `exclude_by_keyword` / `exclude_by_source_type` / `exclude_by_pattern` / `exclude_by_category` — 自动排除
- `set_default_category` / `set_default_source_type` — 设置默认值
- `recategorize_by_category` — 批量重新分类
- `treat_as_tag` — 降级分类为标签

### 3. 结构级反馈 (Structure-Level)

修改知识库目录结构本身：

- `merge_categories` — 合并两个一级分类
- `split_category` — 拆分一个分类
- `delete_category` / `create_category` — 增删分类
- `change_time_axis` — 修改时间维度（按文档时间 vs 修改时间）
- `change_dir_structure` — 修改目录层级（时间优先 vs 分类优先）
- `change_report_template` — 修改报告模板

### 4. 组件级反馈 (Component-Level)

开关系统组件：

- `enable` / `disable` — 启用/禁用组件
- `set_visibility` — 设置可见性（human/ai/both）

相关组件：`wiki_cache`, `embedding`, `hybrid_retrieval`, `monthly_review`, `weekly_summary`, `quarterly_evolution`, `blind_spot_alert`, `writing_candidates`, `profile_report`, `dashboard`

## 关键设计原则

1. **不直接应用** — 先生成 preview diff，用户确认后才 apply
2. **所有规则有人类可读解释** — 每一条 FormalRule 都有 `human_explanation`
3. **先预览后生成** — feedback-plan 产出 diff 文件，feedback-apply 才生成 v2
4. **允许修改结构** — 分类合并/拆分/增删都是正常操作
5. **追踪变更链** — rule_change_log.md 记录所有变更原因和时间

## 文件结构

```
feedback/
  __init__.py              # 包导出
  feedback_schema.py       # 48 个数据模型（Pydantic）
  rule_generator.py        # 反馈→规则引擎
  policy_diff.py           # 策略 diff 生成
  structure_diff.py        # 结构 diff 生成
  preview.py               # 影响预览
  apply_feedback.py        # 应用规则到 v2 蓝图

kb_out/feedback/session_001/
  feedback_rule_plan.yaml   # 正式规则计划
  policy_diff.md            # 策略差异
  structure_diff.md         # 结构差异
  affected_sample_files.csv # 影响的样本文件
  expected_changes.md       # 预期变更摘要

kb_out/blueprints/session_001_v2/
  updated_classification_policy.yaml
  updated_component_plan.yaml
  updated_knowledge_blueprint.md
  rule_change_log.md
```

## CLI 命令

```bash
# 生成规则草案和预览
python main.py feedback-plan \
  --sample-run kb_out/sample_runs/session_001/ \
  --feedback kb_out/sample_runs/session_001/user_feedback.yaml \
  --output kb_out/feedback/session_001/

# 生成 v2 蓝图
python main.py feedback-apply \
  --feedback-plan kb_out/feedback/session_001/feedback_rule_plan.yaml \
  --blueprint kb_out/blueprints/session_001/ \
  --output kb_out/blueprints/session_001_v2/
```
