# Blueprint Generator — 设计文档

> v1.0 | 2026-05-04 | deep-custom Phase B 蓝图生成组件

## 1. 定位

Blueprint Generator 是诊断结果（profile.json + component_plan.yaml）到可执行知识库配置（8 个策略/模板文件）的转换器。

输入：用户画像 + 组件计划
输出：完整的 deep-custom 知识库蓝图配置包

## 2. 模块职责

| 模块 | 职责 | 输出 |
|------|------|------|
| `generator.py` | 主编排器，读取输入，调度各生成器 | knowledge_blueprint.md, 最终汇总 |
| `schema_generator.py` | 生成分类目录结构 | folder_schema.yaml |
| `policy_generator.py` | 生成三个分类策略文件 | classification_policy.yaml, source_type_policy.yaml, exclusion_policy.yaml |
| `report_template_generator.py` | 生成报告模板计划 | report_template_plan.yaml |

## 3. 输出文件

### folder_schema.yaml
```yaml
version: v1
root: docs/
structure:
  type: "domain_first" | "time_first" | "hybrid"
  levels: 2  # 分类/月份
categories: [...]
time_granularity: "month" | "quarter" | "year"
naming_convention: "{category}/{month}/{filename}_{sha8}.{ext}"
```

### classification_policy.yaml
```yaml
version: v1
primary_categories: [...]
rules:
  - name: ...
    condition: ...
    action: "include" | "exclude" | "review"
confidence_threshold: 0.75
deep_read_threshold: 0.60
llm_model: "deepseek-v4-flash"
```

### source_type_policy.yaml
```yaml
version: v1
types:
  原创思考: { handling: "full_classify", weight: 1.0 }
  摘录: { handling: "classify_with_label", weight: 0.7 }
  AI生成: { handling: "separate_category", weight: 0.5 }
  ...
```

### exclusion_policy.yaml
```yaml
version: v1
exclude_patterns:
  - glob: "~$*"
    reason: "Office 临时文件"
  - glob: "*.exe"
    reason: "二进制文件"
exclude_keywords: [...]
exclude_source_types: [...]
```

### report_template_plan.yaml
```yaml
version: v1
templates:
  weekly_summary: { enabled: true, frequency: "weekly", ... }
  monthly_review: { enabled: true, frequency: "monthly", ... }
  ...
```

### query_strategy_policy.yaml
由 strategy/ 子系统生成，详见 query_strategy_router_design.md

### knowledge_blueprint.md
人类可读的蓝图文档，整合以上所有内容

### final_config_draft.yaml
合并所有策略的最终配置草案
