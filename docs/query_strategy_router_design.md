# Query Strategy Router — 设计文档

> v1.0 | 2026-05-04 | deep-custom Phase B 查询策略组件

## 1. 问题

不同语料规模、不同问题类型、不同用户约束下，最优的检索和分析策略完全不同。不能一刀切"100 万字以内全量读"。

## 2. 7 种策略

### Strategy 1: full_read_direct
**适用**: 小范围（< 50k tokens）、需要完整上下文、用户问的是"帮我全面分析这个问题"
**流程**: 全文读入 → 直接 LLM 分析
**决策条件**: corpus < 50k tokens AND (question_type == "open_analysis" OR need_full_accuracy)

### Strategy 2: metadata_filter_then_full_read
**适用**: 用户指定了时间范围/分类/标签，过滤后语料小到可以全量读
**流程**: SQL WHERE 过滤 → 全文读入 → LLM 分析
**决策条件**: has_time_filter OR has_category_filter, filtered_corpus < 80k tokens

### Strategy 3: fts_then_deep_read
**适用**: 关键词明确的查询（"止损"、"RAG"、"离职"），不关心同义词
**流程**: FTS5 BM25 搜索 → 取 top-N 文档 → 深度读入 → LLM 分析
**决策条件**: question_type == "keyword_search" OR query_has_explicit_terms, corpus > 50k tokens

### Strategy 4: hybrid_retrieval_then_deep_read
**适用**: 大语料、开放式问题、同义表达多、需要语义理解
**流程**: FTS5 关键词 + Agentic 语义搜索 → 合并去重 → 深度读入 → LLM 分析
**决策条件**: corpus > 200k tokens, question_type == "open_analysis", need_citation == True

### Strategy 5: wiki_cache_first
**适用**: 有 AI 维护的 wiki 缓存, 用户问的是概括性问题
**流程**: 读 wiki_cache → 如果不充分 → fallback 到 strategy 3 或 4
**决策条件**: wiki_cache_strategy != "off", question_type == "summary" OR "概括"

### Strategy 6: report_first
**适用**: 用户问月报/季报/阶段总结类问题
**流程**: 搜索已有报告 → 如果不充分 → fallback 到 strategy 4
**决策条件**: "月报" in query OR "复盘" in query, report_first == True

### Strategy 7: map_reduce_summary
**适用**: 文件夹级别总结、超长语料（> 1M tokens）、需要全量覆盖但无法全量读入
**流程**: 按分类/月份分块 → 每块 LLM 压缩 → 合并压缩结果 → LLM 综合
**决策条件**: corpus > 500k tokens OR question_type == "folder_summary"

## 3. 策略选择维度（9 维）

| 维度 | 类型 | 来源 | 说明 |
|------|------|------|------|
| corpus_size_tokens | int | corpus_estimator | 预估 token 数 |
| file_count | int | corpus_estimator | 预估文件数 |
| question_type | str | query 分析 | keyword_search / open_analysis / compare / summary / folder_summary / finding_specific |
| need_citation | bool | query 分析 | 是否需要引用源文件 |
| need_full_accuracy | bool | query 分析 | 是否不能遗漏任何相关文档 |
| enabled_components | list[str] | component_plan | 启用的组件列表 |
| latency_budget | str | profile | "fast" / "balanced" / "deep" |
| cost_budget | str | profile | "low" / "medium" / "high" |
| privacy_level | str | profile | "本地" / "可脱敏上传" / "可上传" |

## 4. 路由算法

```
1. 解析 query → question_type, need_citation, need_full_accuracy
2. 估算 corpus → corpus_size_tokens, file_count
3. 读取 profile → latency_budget, cost_budget, privacy_level
4. 读取 component_plan → enabled_components, report_first, wiki_cache_strategy

5. 按优先级匹配策略:
   IF report_first AND question_type IN (summary, compare)
      → Strategy 6 (report_first)
   ELIF wiki_cache_strategy != "off" AND question_type == "summary"
      → Strategy 5 (wiki_cache_first)
   ELIF corpus < 50k AND (question_type == "open_analysis" OR need_full_accuracy)
      → Strategy 1 (full_read_direct)
   ELIF has_filters AND filtered_corpus < 80k
      → Strategy 2 (metadata_filter_then_full_read)
   ELIF question_type == "keyword_search" OR has_explicit_terms
      → Strategy 3 (fts_then_deep_read)
   ELIF corpus > 500k OR question_type == "folder_summary"
      → Strategy 7 (map_reduce_summary)
   ELIF corpus > 200k AND question_type == "open_analysis"
      → Strategy 4 (hybrid_retrieval_then_deep_read)
   ELSE
      → Strategy 3 (fts_then_deep_read)  # 默认安全策略
```

## 5. fallback 链

每种策略只有一个 fallback 目标，防止无限回退：
- Strategy 1 → Strategy 3（全量读不下就 FTS 搜索）
- Strategy 2 → Strategy 3（过滤后语料仍太大）
- Strategy 3 → Strategy 4（关键词搜不到就语义搜索）
- Strategy 4 → Strategy 7（语义搜索太慢就 map-reduce）
- Strategy 5 → Strategy 3（wiki cache 不充分）
- Strategy 6 → Strategy 4（报告不够）
- Strategy 7 → 无 fallback（最终策略）
