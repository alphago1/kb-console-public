# Core Scenario Validation — Design

> 版本: v1 | Plan 8

## 设计理念

不验证"功能清单"，验证"真实任务"。5 个核心场景覆盖用户最高频需求：

| ID | 场景 | 用户价值 | 策略 |
|----|------|---------|------|
| S01 | 找文件 — "我以前在哪写过 X？" | 最基础日常需求 | fts_then_deep_read |
| S02 | 月度复盘 — "生成 N 月月报" | 核心复盘流程 | report_first |
| S03 | 项目分析 — "X 项目 novelty 在哪？" | 创意工作辅助 | hybrid_retrieval_then_deep_read |
| S04 | 写作素材 — "哪些能发展成文章？" | 内容产出驱动 | map_reduce_summary |
| S05 | 自我画像 — "半年变化？" | 长期认知追踪 | hybrid_retrieval_then_deep_read |

## 策略路由

每个场景根据 query_strategy_policy 自动选择检索策略：

```
keyword_search → fts_then_deep_read
report_request & small corpus → full_read_direct
report_request & large corpus → map_reduce_summary
compare / open_analysis → hybrid_retrieval_then_deep_read
```

## 输出

| 文件 | 内容 |
|------|------|
| scenario_results.md | 每个场景的完整回答 + 证据文件 + 数据细节 |
| scenario_failures.md | 失败场景的根因分析 + 修复建议 |
| value_validation_report.md | 5 个关键问题：最有价值场景 / 失败原因 / 是否值得继续 / 需改哪些规则 |

## CLI

```bash
python main.py validate-deep-custom \
  --kb kb_out/deep_custom_kb/session_001/ \
  --output kb_out/validation/session_001/
```
