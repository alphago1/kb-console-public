# Karpathy-Style Wiki Baseline + Word-first Adaptation — 设计文档

> 版本 v1.0 | 2026-05-04 | deep-custom Phase B 核心组件

## 1. 产品叙事

**不给用户空白画布，不给用户照搬模板。给用户一个接近正确答案的默认结构，然后根据用户画像做个性化适配。**

Karpathy-style AI wiki 是公认的高质量个人知识库架构——raw_sources 只读保留、AI 维护结构化 wiki 层、index/log 可追溯、schema_rules 规范化、lint 质量检查。

本项目不照搬 Karpathy wiki，而是把它作为 **default baseline**——一个"如果你不知道什么样的知识库好，先用这个"的起点。然后根据 deep-custom 用户画像，做五种类型的适配：

- **保留**：通用的好设计，对所有用户都有价值
- **降级**：对当前用户太重或不需要的功能，简化但不删除
- **替换**：用更适合用户工作流的方案替代
- **增强**：本项目的独特能力，超越 baseline 的部分
- **禁用**：对当前用户有害或无意义的功能

结果不是"从零构建知识库"，也不是"套用 Karpathy wiki"，而是 **"基于优秀默认架构做的个性化调整"**。

## 2. 默认 Karpathy Baseline 结构

### 2.1 五层架构

```
┌─────────────────────────────────────────┐
│ Layer 5: Lint                            │
│ - 重复主题检测 · 过期观点检查              │
│ - 孤立页面检测 · 无来源结论检查            │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Layer 4: Schema Rules                    │
│ - AI wiki 更新规则 · 命名规则             │
│ - 冲突处理规则 · 来源记录规则              │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Layer 3: Index & Log                     │
│ - index.md · topic_index · update_log    │
│ - ingest_log · change_tracking           │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Layer 2: Wiki Layer (AI-maintained)      │
│ - topic pages · project pages            │
│ - profile pages · cross-references       │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Layer 1: Raw Sources (read-only)         │
│ - 用户原始文件 · 不可修改 · 不可删除      │
└─────────────────────────────────────────┘
```

### 2.2 各层详细定义

**Layer 1 — raw_sources**：
- 用户所有原始文件只读保存
- 不移动、不重命名（除非用户明确允许）
- 作为一切分析的事实基础

**Layer 2 — wiki_layer**：
- AI 自动维护的结构化知识页面
- topic pages：每个核心话题一页，持续更新
- project pages：每个项目一页，包含状态、进展、关键决策
- profile pages：用户画像页，AI 定期更新

**Layer 3 — index_log**：
- index.md：人类可读的全局索引
- topic_index：机器可读的话题-页面映射
- update_log：每次 AI 更新的记录
- ingest_log：每次新文件摄入的记录

**Layer 4 — schema_rules**：
- AI 更新 wiki 的规则（何时更新、如何更新）
- 页面命名规范
- 冲突处理规则（AI 推断 vs 用户明确表述）
- 来源记录规则（每条结论必须可追溯到源文件）

**Layer 5 — lint**：
- 周期性质量检查
- 重复主题 → 建议合并
- 过期观点 → 标记或归档
- 孤立页面 → 检查是否仍有价值
- 无来源结论 → 标记为待验证

## 3. 适配引擎

### 3.1 适配类型

| 类型 | 含义 | 典型场景 |
|------|------|---------|
| KEEP | 原样保留，不做修改 | raw_sources 只读保存——对所有人都适用 |
| DOWNGRADE | 降级简化，保留核心功能 | 用户不读 index.md → 降为 AI-only JSON index |
| REPLACE | 替换为用户更适应的方案 | 用户主入口不是 wiki pages → 替换为 report-first |
| ENHANCE | 在本项目特有能力的加持下增强 | 加上 Word-first 文档迁移、scoped full-read 分析 |
| DISABLE | 完全禁用，不启用 | 用户不需要 Obsidian 双链 → 禁用图谱功能 |

### 3.2 适配规则引擎

`adaptation_rules.py` 读取 `UserKnowledgeProfile`，按规则表对 baseline 的每个组件做适配决策：

```
IF profile.maintenance_willingness == "低"
   AND component == "wiki_layer.human_readable_pages"
   THEN DOWNGRADE → "AI-internal structured cache, no human-facing pages"

IF profile.source_file_types 包含 ".docx"
   AND component == "raw_sources.format"
   THEN ENHANCE → "添加 Word-first 文档迁移管线"

IF profile.human_reading_entry == "用搜索框搜关键词"
   AND component == "index_log.human_index"
   THEN DOWNGRADE → "降级为 AI-readable JSON index"

IF profile.preferred_outputs 包含 "报告"
   AND component == "wiki_layer.main_entry"
   THEN REPLACE → "主入口替换为 report-first 工作流"
```

## 4. 交付物

所有交付物写入 `kb_out/blueprints/session_NNN/`：

| 文件 | 说明 |
|------|------|
| `karpathy_baseline.md` | 完整的 Karpathy baseline 描述（5 层，所有组件，默认策略） |
| `adaptation_diff.md` | 适配变更清单（KEEP/DOWNGRADE/REPLACE/ENHANCE/DISABLE + 理由） |
| `adapted_knowledge_blueprint.md` | 适配后的最终知识库蓝图——用户可见的核心设计文档 |
| `component_plan.yaml` | 适配后的组件计划（哪些组件启用、哪些降级、哪些自定义） |
| `word_compatibility_plan.md` | Word-first 兼容性计划（docx 迁移、文本提取、分类流程） |
| `wiki_cache_policy.yaml` | AI wiki 缓存策略（更新频率、范围、冲突处理规则） |
| `report_first_policy.yaml` | report-first 策略（报告类型、频率、模板、入口） |

## 5. CLI 命令

```
python main.py karpathy-baseline-generate \
  --output kb_out/baselines/karpathy_default/

python main.py karpathy-adapt \
  --baseline kb_out/baselines/karpathy_default/ \
  --profile kb_out/diagnosis/session_001/user_knowledge_profile.json \
  --output kb_out/blueprints/session_001/
```

## 6. 与现有系统的关系

- 依赖 `diagnosis/` 输出的 `UserKnowledgeProfile`
- 不依赖 scanner / database / chunker（纯设计层）
- 生成的 `component_plan.yaml` 和 `adapted_knowledge_blueprint.md` 是后续 Phase C（sample-run 验证）的输入
