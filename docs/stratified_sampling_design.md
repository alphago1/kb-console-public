# Stratified Sampling — 设计文档

> v1.0 | 2026-05-04 | deep-custom Phase C 验证组件

## 1. 问题

正式构建 deep-custom 知识库之前，必须在 30-80 个文件的小样本上验证分类策略和报告模板的质量。样本必须均匀覆盖用户资料的所有维度——不能随机抽。

## 2. 6 个分层维度

| 维度 | 层数 | 说明 |
|------|------|------|
| 时间 | 4 | 最近1月 / 最近3月 / 今年 / 去年或更早 |
| 文件类型 | 5 | docx / doc / md / txt / 转写稿 |
| 文件大小 | 4 | 短(<10KB) / 中(10-100KB) / 长(100KB-1MB) / 超长(>1MB) |
| 目录(分类) | N | 每个核心分类至少1个，高密度分类按比例多抽 |
| 疑似用途 | 7 | 交易/AI/写作/项目/个人随笔/课程/外部资料 |
| 风险 | 6 | 疑似电子书/课程讲义/合同证件/空文档乱码/低置信度/重复文件 |

## 3. 采样算法

**Greedy Coverage Maximization**:

1. 对每个文件计算6维 strata key
2. Phase 1 — **强制覆盖**: 每个未覆盖的 stratum 至少选 1 个文件（按置信度降序）
3. Phase 2 — **比例填充**: 按各分类的文件占比分配剩余名额
4. Phase 3 — **风险兜底**: 确保风险文件至少占 10%

**优先级**: 强制覆盖 > 风险兜底 > 比例填充

## 4. 隔离保证

- 只读 SQLite SELECT，不执行 INSERT/UPDATE/DELETE
- 所有输出写入 `kb_out/sample_runs/`（与 `kb_out/reports/` 等隔离）
- 不移动、不删除、不改名源文件
- 不创建独立数据库——采样结果写入 CSV/Markdown/HTML

## 5. 输出文件

| 文件 | 内容 |
|------|------|
| sample_manifest.md | 采样说明：为什么选、覆盖了什么、缺了什么 |
| sample_selection.csv | 每个文件的选中理由 |
| sample_coverage_report.md | 6 维 × N 层的覆盖率矩阵 |
| sample_knowledge_map.md | 可视化的样本文件地图 |
| sample_classification.csv | 样本分类结果 |
| sample_dashboard.html | 可打开的覆盖度 Dashboard |
| sample_review_questions.md | 基于样本的审核问题 |
