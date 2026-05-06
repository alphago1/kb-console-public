# 项目理解报告 v3 — 从本地知识库整理工具到 deep-custom AI Knowledge Base Designer

> 生成日期：2026-05-04 | 读者：项目 Owner | 目的：为 deep-custom 升级提供现状基线

---

## 1. 当前项目一句话定位

**Word-first 本地知识库管理系统**：从桌面 `.docx`/`.md`/`.txt` 文件自动扫描、提取、分类、全文检索、AI 深度分析，通过 CLI + Streamlit GUI + MCP 协议提供服务。

核心用户场景：用户随手在桌面建 Word 文件记录想法/交易/笔记 → 每周自动分类归档至 `docs/` 目录 → 按需搜索/分析/画像。

---

## 2. 已实现能力清单

### 2.1 数据接入层

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| 多目录递归扫描（`.docx/.doc/.md/.txt`） | `scanner.py` | 主线 |
| LibreOffice Word 文本提取 | `extractor.py` | 主线 |
| 智能采样（前/中/后/随机段 + 关键词上下文窗口） | `sampler.py` | 主线 |
| 低置信度自动触发深度重读（deep_read_max_chars=12000） | `database.py:process_file` | 主线 |
| 文本缓存（text_cache_path 持久化全文） | `database.py` | 主线 |

### 2.2 分类与标签层

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| 规则分类器（课程材料识别：讲义排除/转写复核/笔记纳入） | `classifier_rules.py` | 主线 |
| LLM 自动分类（DeepSeek 11 个一级分类 + 6 个 bool 标记 + 20+ 标签维度） | `llm_classifier.py` + `deepseek_prompt.txt` | 主线 |
| 规则+LLM 混合策略（规则优先排除，LLM 做精细分类） | `database.py:process_file` | 主线 |
| 标签归一化清洗（emotion_tags + topic_tags） | `tag_normalizer.py` | 主线 |
| 人工复核 UI（HTML review 界面 + CSV 更新写回 SQLite） | `review_ui.py` | 主线 |

### 2.3 存储与检索层

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| SQLite 数据库（43 列 documents 表，完整元数据 schema） | `database.py` | 主线 |
| FTS5 全文检索（chunk 级 BM25 排序 + snippet 高亮） | `chunker.py` | 主线 |
| 确定性内容指纹（全文 SHA256）去重 | `database.py:_sha256_text` | 主线 |
| 文件变更检测（size+mtime+sha256 三重去重） | `workflow_mainline.py:weekly_organize` | 主线 |
| 文档 chunk 表（900 字符 + 120 重叠，独立 FTS 索引） | `chunker.py` | 主线 |

### 2.4 AI 分析引擎

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| Token 预算预估 + 策略选择（<850k 单次读入 / 850k-1.5M 分批 / >1.5M 按月压缩） | `workflow_mainline.py:token_budget` | 主线 |
| 100 万字预算制分析（按字数动态累积，不硬截断） | `workflow_mainline.py:_build_blocks_with_budget` | 主线 |
| 超限分批 LLM 压缩 + ThreadPoolExecutor 并发处理 + 最终合成 | `bundle_builder.py:compress_and_synthesize` | 主线 |
| 文件夹全文分析（两步：Bundle 零费用预览 → LLM 答疑） | `folder_analyzer.py` | 主线 |
| 项目/主题分析（用户自选 topic + 文件夹范围） | `project_analyzer.py` | 主线 |
| 个人画像（scope: all/trading/ai-projects，认知维度抽取） | `profile_analyzer.py` | 主线 |
| 交易月报/季报/系统构建（专用分析管线） | `workflow_mainline.py` `monthly_report.py` `quarterly_report.py` | 主线 |
| 课程转写压缩（LLM 压缩为结构化笔记） | `workflow_mainline.py:compact_course_transcripts` | 主线 |

### 2.5 搜索与 Agent 层

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| 快速搜索（FTS5 + 文件名 LIKE 双重命中） | `workflow_mainline.py:find_idea` | 主线 |
| Agentic Search（Agent Runtime 多轮工具调用理解自然语言） | `agent/runtime.py` | experimental |
| 7 个 Agent 工具（search/search_chunks/get_document/compare/summarize/find_writing/cluster_ideas） | `agent/tool_schemas.py` + `agent/tool_executor.py` | 主线 |
| Agent 权限校验 + 审计日志 | `agent/permissions.py` + `agent/audit.py` | 主线 |

### 2.6 MCP 服务

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| Stdio + HTTP 双传输模式 | `mcp_server/server.py` | 主线 |
| 7 个 MCP 工具（与 Agent 工具共享后端） | `mcp_server/tools.py` | 主线 |
| 路径脱敏（隐藏真实物理路径，显示 `[KB_ROOT]` 占位） | `mcp_server/adapters.py` | 主线 |
| 权限控制（enabled_tools/disabled_tools 白名单+黑名单） | `mcp_server/tools.py` | 主线 |
| MCP 审计日志 + smoke test | `mcp_server/audit.py` + `main.py:cmd_mcp_smoke_test` | 主线 |
| Resources + Prompts 暴露 | `mcp_server/resources.py` + `mcp_server/prompts.py` | experimental |

### 2.7 GUI 与用户体验

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| Streamlit 6 组导航（Dashboard / Find / 整理与维护 / 自定义分析 / 报告中心 / 设置） | `streamlit_app.py` | 主线 |
| 后台异步任务（线程化 + 进度条 + 侧边栏持久面板 + toast+beep 通知） | `ui_helpers.py:run_cli_live_async` | 主线 |
| 配置可读写（LLM / 路径 / 扫描参数 / 连接测试 / 系统诊断） | `ui_helpers.py:save_config` | 主线 |
| Dashboard HTML（月度 × 分类热力图 / 交易趋势 / 情绪趋势 / 认知变化 / 写作候选 / 项目想法 / 低置信度） | `dashboard.py` | 主线 |
| 文件夹选择器（浏览 + 手动 + 快速添加） | `ui_helpers.py:get_available_folders` | 主线 |
| 报告中心（按类型分组浏览/预览/下载历史报告） | `streamlit_app.py` | 主线 |

### 2.8 工程基础设施

| 能力 | 实现文件 | 状态 |
|------|---------|------|
| 4 个 LLM Provider（DeepSeek/Claude/Gemini/OpenAI） | `llm_providers/` | 主线 |
| LLM 调用日志（task/model/prompt_chars/response_chars 完整记录） | `workflow_mainline.py:_write_llm_log` | 主线 |
| 文档迁移工具（源文件复制到 docs/ + 路径重写） | `docs_migrator.py` | 主线 |
| 文档统计报告（字数/字符/分类/月份多维统计） | `docs_stats.py` | 主线 |
| Windows 计划任务配置说明 | `windows_task_scheduler.md` | 主线 |
| 3 个批处理入口（kb console / weekly organize / trading monthly report） | `run_*.bat` | 主线 |

---

## 3. 当前数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据接入 (Scan)                           │
│  Desktop *.docx/*.md/*.txt                                      │
│      ↓ scanner.py → iter_files (递归 + 排除规则)                 │
│      ↓ extractor.py → LibreOffice 提取纯文本                     │
│      ↓ sampler.py → 前中后采样 + 关键词上下文窗口                  │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      分类决策 (Classify)                         │
│  classifier_rules.py → 课程材料/讲义 规则过滤                     │
│      ↓ LLM Classifier (deepseek_prompt.txt)                      │
│      ↓ 11 分类 + 6 bool 标记 + 20+ 标签 + 认知快照 + summary     │
│      ↓ 低置信度 → 深度重读 → 再次 LLM                            │
│      ↓ tag_normalizer.py → 标签清洗归一化                        │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      存储 (Store)                                │
│  database.py → SQLite documents 表 (43 列)                       │
│      ↓ chunker.py → 900 字分块 + FTS5 全文索引                   │
│      ↓ 全文 SHA256 指纹 → 确定性去重                              │
│      ↓ docs/ 目录 → 分类 / 月份 两级物理存储                      │
│      ↓ text_cache/ → 全文缓存（加速重读）                         │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                    查询与分析 (Query & Analyze)                   │
│  ┌─────────────┬──────────────────┬──────────────────┐          │
│  │ 快速搜索     │ Agentic Search   │ 深度分析          │          │
│  │ FTS5 + LIKE  │ Agent Runtime    │ Budget → Bundle   │          │
│  │ find_idea    │ 7 tools × N轮    │ → Compress → LLM  │          │
│  └─────────────┴──────────────────┴──────────────────┘          │
│      ↓ 用户可选的输出路径:                                        │
│  - Dashboard HTML (大盘可视化)                                    │
│  - 月报/季报 Markdown (结构化报告)                                │
│  - 个人画像 Markdown (认知画像)                                   │
│  - 主题分析 Markdown (自定义分析)                                  │
│  - Context Bundle Markdown (全文打包)                             │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                     对外服务 (Expose)                            │
│  MCP Server (stdio + HTTP) → Claude Desktop / Cursor 集成        │
│  FastAPI REST → /search /document /summary /compare              │
│  Streamlit GUI → 用户直接操作                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 当前 CLI 命令

共 **32 个** CLI 子命令，分为 4 类：

### 核心管线（line 498-668 of main.py）
```
scan              扫描目录并分类入库
weekly-organize   每周整理：扫描→分类→写入 docs/ + SQLite → 生成周报
find              快速搜索（FTS5 + 文件名双重命中）
token-budget      估算 Token 预算 + 策略建议
```

### 分析（line 609-667 of main.py）
```
build-folder-bundle   构建文件夹全文 Bundle
analyze-folder        文件夹全文分析（问答模式）
project-analyze       项目/主题分析
profile-me            个人画像（all/trading/ai-projects）
trading-monthly-report   交易月报
trading-system-build     交易系统构建
trading-analyze          交易主题分析
build-trading-bundle     构建交易全文 Bundle
monthly-report           通用月报
report                   季报
compact-course-transcripts  课程转写压缩
```

### 维护（line 531-606 of main.py）
```
export          导出 CSV/JSON
dashboard       生成 Dashboard HTML
review          生成 Review HTML + CSV
apply-review    应用人工复核更新
build-chunks    构建 FTS5 全文索引
search          FTS5 全文搜索
normalize-tags  标签归一化清洗
bundle          构建 model_context_bundle.md
docs-migrate    文档迁移
docs-stats      文档统计报告
```

### 服务与测试（line 437-597 of main.py）
```
serve           启动 FastAPI 服务
agent           运行 Agent（工具调用模式）
agent-test      5 个内置 Agent 测试
mcp-stdio       启动 MCP stdio 服务
mcp-http        启动 MCP HTTP 服务
mcp-list-tools  列出 MCP 工具
mcp-smoke-test  MCP 烟雾测试
```

---

## 5. 当前安全边界

### 5.1 已实现的护栏

| 维度 | 策略 | 实现位置 |
|------|------|---------|
| 源文件保护 | `source_files: {read: true, write/move/delete/rename: false}` | `config.yaml → permissions` |
| 输出隔离 | 所有产出物限于 `kb_out/{reports,bundles,logs,cache,exports,dashboard}` | `config.yaml → permissions.output_dirs` |
| MCP 路径脱敏 | `redact_source_paths: true` → 隐藏真实物理路径 | `mcp_server/adapters.py` |
| MCP 工具白名单 | `enabled_tools` + `disabled_tools` 精细控制暴露 | `mcp_server/tools.py` |
| MCP 结果截断 | `max_result_chars: 12000` | `mcp_server/adapters.py` |
| MCP path-like 输入拒绝 | smoke test 验证 `C:\Windows` 类输入被拦截 | `mcp_server/adapters.py` |
| Agent 权限校验 | `is_tool_allowed` + `is_tool_enabled` 双重检查 | `agent/permissions.py` |
| Agent 报告路径约束 | `ensure_report_path_allowed` 限制写入目录 | `agent/permissions.py` |
| Agent/MCP 审计日志 | 每次工具调用记录 model/user_query/tool/arguments/allowed/result_count | `agent/audit.py` `mcp_server/audit.py` |
| API Key 保护 | 环境变量注入，不出现在日志/界面 | `deepseek_provider.py:__init__` |
| LLM 调用日志 | 记录 task/model/prompt_chars/response_chars（不含内容） | `workflow_mainline.py:_write_llm_log` |
| 配置备份 | `save_config` 自动 `.bak` 备份 | `ui_helpers.py:save_config` |

### 5.2 当前未覆盖的风险

| 风险 | 说明 |
|------|------|
| LLM prompt 注入 | `deepseek_prompt.txt` 中用户文档内容拼入 prompt 时，文档本身可能包含 "忽略之前的指令" 类攻击文本。当前依赖 disclaimer "不可信文档内容" 但不做输入清洗 |
| MCP HTTP 无认证 | HTTP 模式仅 `enforce_local_http` 检查 host=127.0.0.1，无 token/API key 认证 |
| Streamlit 无鉴权 | GUI 本地运行无登录，任何人打开浏览器即可操作 |
| 子进程无 sandbox | CLI 命令通过 subprocess 调用，未限制系统调用范围 |

---

## 6. 哪些模块是主线

| 模块 | 证据 | 判断理由 |
|------|------|---------|
| `scanner.py` | 所有数据流入口 | 无它系统无输入 |
| `extractor.py` | 文本提取是后续一切的基础 | 无它无文本 |
| `sampler.py` | LLM 分类的输入准备 | 决定分类质量 |
| `database.py` | 所有模块都依赖它 | 43 列 schema 是数据中枢 |
| `chunker.py` | FTS5 检索 + find/search 命令依赖 | 检索的基础设施 |
| `classifier_rules.py` | 规则优先策略的载体 | 用户自定义规则入口 |
| `llm_classifier.py` + `deepseek_prompt.txt` | AI 分类核心 | 所有文档分类必经 |
| `tag_normalizer.py` | 标签质量保证 | 数据治理层 |
| `workflow_mainline.py` | 核心管线编排（weekly-organize/trading/find/token-budget） | 业务逻辑中枢 |
| `bundle_builder.py` | 预算制分析的基础能力 | 所有深度分析依赖 |
| `agent/` (除 prompts.py) | 7 工具 + 权限 + 审计 + 执行 | Agentic Search 核心 |
| `mcp_server/` (除 prompts.py, resources.py) | 外部集成唯一通道 | 已有用户（Claude Desktop） |
| `streamlit_app.py` + `ui_helpers.py` | GUI 操作入口 | 用户日常交互界面 |
| `dashboard.py` | 知识库大盘 | 可视化唯一入口 |
| `config.yaml` | 全局配置 | 所有模块依赖 |

---

## 7. 哪些模块是 experimental

| 模块 | 标记证据 | 现状评估 |
|------|---------|---------|
| `agent/prompts.py` | Agent 的 system_prompt 硬编码，未随用户知识库演化 | 需升级为动态 prompt |
| `agent/runtime.py` | CLI 标记 `[experimental]`，DeepSeek tool-calling 的可靠性未充分验证 | 可保留但谨慎扩展 |
| `mcp_server/prompts.py` | MCP prompts 暴露功能，只读无状态 | 低风险，可保留 |
| `mcp_server/resources.py` | 资源暴露，当前内容量少 | 低风险 |
| `llm_providers/claude_provider.py` | 仅框架，实际只用 DeepSeek | 未验证 |
| `llm_providers/gemini_provider.py` | 同上 | 未验证 |
| `llm_providers/openai_provider.py` | 同上 | 未验证 |
| `model_context_bundle.py` | 作用与 `bundle_builder.py` 有重叠 | 待合并或废弃 |
| `profile_analyzer.py` | 画像维度硬编码（交易/AI项目），prompt 模板化 | 功能可用但不够 deep |

---

## 8. 哪些功能不应继续扩展

| 功能 | 原因 | 建议 |
|------|------|------|
| ~~PDF / 图片 OCR 支持~~ | 扩展文件类型是"宽度"扩展，当前阶段应做"深度" | 冻结，不做 |
| ~~多用户 / 多知识库~~ | 当前单用户单库设计够用，多用户需要 auth + 隔离，ROI 低 | 冻结 |
| ~~PyInstaller 打包分发~~ | 打包分发服务于"通用用户"，当前只服务 deep-custom 用户（自己） | 冻结 |
| ~~Watchdog 守护进程~~ | 增量同步有价值，但文件系统监听引入进程管理复杂度 | 暂缓，用每周整理 + 手动触发覆盖 |
| ~~Embedding 语义向量检索（ChromaDB/sqlite-vec）~~ | 引入新依赖 + 新存储 + 新索引维护。当前 Agentic Search 已提供语义级搜索能力，且不需要新基础设施 | 暂缓，评估 Agentic Search 是否够用再决定 |
| 新的 Provider 接入（Claude/Gemini/OpenAI） | 当前只用 DeepSeek，维护 4 个 Provider 的适配层是虚胖 | 删除未验证的 3 个 Provider，保留 base.py + deepseek_provider.py |
| Streamlit GUI 新页面 | GUI 是操作界面，不是 deep-custom 的核心差异化能力 | 功能收敛，不新增导航项 |
| `agent/prompts.py` 硬编码 system_prompt | 当前 prompt 写死 5 个测试问题 + 通用指令 | **这是 deep-custom 的切入点，不是不做，是用新方式做**（见第 9 节） |

---

## 9. 哪些地方适合接入 deep-custom 诊断流程

deep-custom AI Knowledge Base Designer 的核心定义：**系统不是被动执行分类/检索/分析指令，而是主动理解用户的认知模式，诊断知识库的结构质量，提出个性化改进建议，并随着用户的知识积累持续演化自己的理解。**

适合接入 deep-custom 的具体位置：

### 9.1 接入点 A：知识库结构诊断器（新模块，接入 `workflow_mainline.py`）

**为什么要做**：当前系统的分类体系是**静态的 11 个分类**，来自 `deepseek_prompt.txt` 第一次写死后从未更新。用户的知识兴趣在演化（例如从"交易"转向"AI 工具化"），但分类体系不跟着变。

**接入方式**：
- 读取全量 `documents` 表的 category/tag/emotion/cognition 分布统计
- 对比不同时间窗口（如 2025 vs 2026）的分类/标签分布变化
- LLM 生成"知识库结构健康报告"：哪些分类在膨胀（需要拆分），哪些在萎缩（可以合并），哪些话题持续出现但散落在多个分类里（需要新建分类）
- 输出：推荐的新分类体系 + 迁移方案（从哪些旧分类移到新分类）

**涉及文件**：新建 `kb_tool/structure_diagnostician.py`，在 `workflow_mainline.py` 中加一个入口函数

### 9.2 接入点 B：认知演化追踪器（增强现有 `profile_analyzer.py`）

**为什么要做**：当前 `profile_analyzer.py` 做的是"单次快照"——调用一次 LLM，输出一份画像。但 deep-custom 需要的是**跨时间的认知变化检测**。用户 2025 年的交易信念和 2026 年不同——这个变化本身是最有价值的知识。

**接入方式**：
- 利用已有 `cognition_snapshot` 字段（old_beliefs/new_beliefs/self_view/trading_beliefs/open_questions）
- 不只在分类时抽取认知快照，而是在分析时做**跨时间对比**：
  - 同一 open_question 在不同月份是否出现了答案？
  - old_beliefs 在后续文档中是否被证实/证伪？
  - self_view 的变化轨迹是什么？
- LLM 生成"认知演化报告"：从 XX 月到 XX 月，用户关于 [主题] 的认知发生了什么变化？哪些信念被验证了？哪些被推翻了？哪些问题仍未解决？

**涉及文件**：增强 `profile_analyzer.py` 加 `cognition_evolution` 模式；增强 `workflow_mainline.py` 加 `cmd_cognition_evolution`

### 9.3 接入点 C：知识盲区检测器（新模块，接入 `agent/` 工具链）

**为什么要做**：当前系统能回答"知识库里有什么"，但不能回答"知识库里缺什么"。deep-custom 的核心价值之一是**告诉用户他没想到但应该想的事情**。

**接入方式**：
- 新增 Agent 工具 `kb.detect_blind_spots`，内部逻辑：
  - 统计用户文档覆盖的话题（从 topic_tags 聚类）
  - 对每个主要话题，检测相关但未覆盖的子话题（例如：用户有大量"止损"文档但没有"仓位规模计算"文档）
  - 检测时间断档（例如：交易系统 2025-08~2025-10 没有更新，但 11 月突然大幅修改——中间发生了什么？）
  - LLM 生成"知识盲区报告"：你应该补充哪些方面的记录？哪些时段的思考缺失？

**涉及文件**：新建 `kb_tool/blind_spot_detector.py`，在 `agent/tool_schemas.py` 加工具定义，在 `agent/tool_executor.py` 加执行逻辑

### 9.4 接入点 D：动态分类体系（改造 `llm_classifier.py` + `deepseek_prompt.txt`）

**为什么要做**：当前 11 个 `primary_category` 是硬编码在 prompt 里的。用户新关注一个领域时，分类体系不自动更新。

**接入方式**：
- 将分类体系从 prompt 中解耦，存入数据库新表 `category_system`（version / categories / created_at）
- 定期（如每月）运行结构诊断器（9.1），若建议新分类则生成新版本
- LLM 分类时读取**最新版本**的分类体系而非硬编码
- 用户可在 review UI 中批准/拒绝分类体系变更

**涉及文件**：`deepseek_prompt.txt`（改模板化）、`database.py`（加 category_system 表）、`llm_classifier.py`（读动态分类）、`review_ui.py`（加分类审批）

### 9.5 接入点 E：个性化 Prompt 工厂（改造 `agent/prompts.py`）

**为什么要做**：当前 Agent system_prompt 是**通用写死的**："你是一个个人知识库助手"。deep-custom 要求 Agent 的 system_prompt **随着用户的知识库演化**——Agent 应该知道用户的关注领域、常用术语、思维模式。

**接入方式**：
- 从 `profile_analyzer.py` 的画像输出中提取用户特征：
  - 长期关注主题列表
  - 核心术语/概念词表
  - 决策模式描述
  - 当前开放问题清单
- 将这些特征动态注入 Agent system_prompt
- 每次 profile 更新后，agent prompt 自动刷新

**涉及文件**：`agent/prompts.py`（改为模板化 + 动态注入）、`profile_analyzer.py`（输出结构化 JSON 供 prompt 消费）

### 9.6 接入点 F：知识库设计建议引擎（新模块，Streamlit Dashboard 增强）

**为什么要做**：当前 Dashboard 展示"是什么"（统计/热力图/列表），但不提供"应该做什么"的建议。

**接入方式**：
- 在 Dashboard 页面加一个"设计建议"卡片
- 内部整合 9.1（结构诊断）+ 9.3（盲区检测）+ 9.2（认知演化）的摘要
- 以自然语言输出具体建议，例如：
  - "你在'交易心理'分类下有 47 篇文档，但时间分布集中在 2025 下半年。建议回顾 2026 年上半年的交易心理状态。"
  - "你在'AI与工具化'分类中反复提到 RAG 和法律 AI，但这两个话题散落在 6 个月的不同文档里。建议新建'法律AI项目'子分类。"
  - "你关于止损的信念在 2025-09 和 2026-01 有两次明显变化，但中间缺乏记录。建议补充这段时间的交易决策过程。"

**涉及文件**：`dashboard.py`（加 design_advice 卡片）、新建 `kb_tool/design_advisor.py`

---

## 10. 下一步最小可行开发顺序

按 deep-custom 价值密度和实施依赖排序：

```
Phase 1 — 让系统认识自己（零新依赖，只读分析）
├── P1.1  动态分类体系（9.4）          依赖：无          产出：category_system 表 + 动态 prompt
├── P1.2  知识库结构诊断器（9.1）      依赖：P1.1        产出：结构健康报告
└── P1.3  认知演化追踪器（9.2）        依赖：无          产出：认知演化报告

Phase 2 — 让系统主动建议（新 Agent 工具）
├── P2.1  知识盲区检测器（9.3）        依赖：P1.1+P1.2   产出：盲区报告 + Agent 工具
└── P2.2  知识库设计建议引擎（9.6）    依赖：P1.2+P1.3+P2.1   产出：Dashboard 建议卡片

Phase 3 — 让系统随用户演化（闭环反馈）
├── P3.1  个性化 Prompt 工厂（9.5）    依赖：P1.3+P2.1   产出：动态 Agent prompt
└── P3.2  设计建议 → 分类体系变更的闭环 依赖：P1.1+P2.2   产出：用户审批 → 自动迁移
```

**Phase 1 每个任务都不需要新依赖，都只读已有数据，都产出分析报告**——这是最低风险的 deep-custom 切入点。

---

## 附录：项目文件清单（用于快速索引）

### 核心后端（`kb_tool/`）

| 文件 | 行数 | 职责 |
|------|------|------|
| `main.py` | 678 | CLI 入口，32 个子命令 |
| `workflow_mainline.py` | 757 | 核心管线（weekly-organize/trading/find/budget） |
| `database.py` | 411 | SQLite 数据库 + 43 列 schema + process_file + export |
| `scanner.py` | 138 | 文件扫描 + 并发处理 |
| `extractor.py` | - | LibreOffice 文本提取 |
| `sampler.py` | - | 智能采样（前中后/随机/关键词） |
| `chunker.py` | ~150 | 文档分块 + FTS5 全文索引 |
| `llm_classifier.py` | - | DeepSeek LLM 分类调用 |
| `classifier_rules.py` | - | 规则分类器 |
| `tag_normalizer.py` | - | 标签归一化 |
| `bundle_builder.py` | ~200 | Token 预算 + 分批压缩 + 并发合成 |
| `folder_analyzer.py` | - | 文件夹全文分析 |
| `project_analyzer.py` | - | 项目/主题分析 |
| `profile_analyzer.py` | ~40 | 个人画像分析 |
| `monthly_report.py` | - | 月报生成 |
| `quarterly_report.py` | - | 季报生成 |
| `review_ui.py` | ~100 | HTML Review 界面 |
| `dashboard.py` | 180 | Dashboard HTML 生成 |
| `server.py` | ~80 | FastAPI 服务 |
| `docs_migrator.py` | - | 文档迁移 |
| `docs_stats.py` | - | 文档统计 |
| `model_context_bundle.py` | - | Context Bundle（与 bundle_builder 功能重叠） |

### Agent 子系统（`kb_tool/agent/`）

| 文件 | 职责 |
|------|------|
| `runtime.py` | Agent 运行时（多轮工具调用 + fallback synthesis） |
| `tool_schemas.py` | 7 个工具的 JSON Schema 定义 |
| `tool_executor.py` | 工具执行（SQL 查询 + 结果组装） |
| `tool_registry.py` | 工具注册 + enabled 过滤 |
| `permissions.py` | 工具权限校验 |
| `audit.py` | Agent 审计日志 |
| `prompts.py` | System prompt（硬编码，待升级） |

### MCP 子系统（`kb_tool/mcp_server/`）

| 文件 | 职责 |
|------|------|
| `server.py` | Stdio + HTTP 双模式 MCP 服务 |
| `tools.py` | MCP 工具列表（kb. 前缀） |
| `adapters.py` | Ruby 方法映射 + 路径脱敏 + 结果截断 |
| `resources.py` | MCP Resources |
| `prompts.py` | MCP Prompts |
| `audit.py` | MCP 审计日志 |
| `auth.py` | HTTP 本地限制 |

### LLM Provider（`kb_tool/llm_providers/`）

| 文件 | 状态 |
|------|------|
| `base.py` | 抽象基类 |
| `deepseek_provider.py` | **主力**，通过 OpenAI SDK 调用 DeepSeek API |
| `claude_provider.py` | 框架代码，未实际使用（可删除） |
| `gemini_provider.py` | 框架代码，未实际使用（可删除） |
| `openai_provider.py` | 框架代码，未实际使用（可删除） |

### GUI 层

| 文件 | 行数 | 职责 |
|------|------|------|
| `streamlit_app.py` | ~800 | GUI 主入口，6 组导航 |
| `ui_helpers.py` | ~650 | GUI 辅助（路径/任务/配置/诊断/Token预估/剪贴板） |

### 配置与文档

| 文件 | 职责 |
|------|------|
| `kb_tool/config.yaml` | 全局配置（当前在用的配置） |
| `kb_tool/config.example.yaml` | 示例配置 |
| `deepseek_prompt.txt` | LLM 分类 system prompt（110 行，含完整 JSON schema） |
| `README.md` | 项目 README |
| `项目情况总结.md` | 项目结构 + 技术栈 + 安全策略 |
| `当前项目功能总结与演进建议.md` | 功能盘点 + 5 个演进方向 |
| `docs_dev_retro/` | 10 篇复盘文档（时间线/bug案例/需求演化/AI协作复盘/checklist等） |

### 测试

| 文件 | 覆盖率 |
|------|------|
| `tests/test_cli_commands.py` | 33/33 通过（命令解析 + find/token-budget/mcp 烟雾测试） |
| `tests/test_gui_backend.py` | 38/39 通过（路径解析/DB初始化/配置读写/函数调用） |

---

> **底层逻辑**：这个项目不缺功能——32 个 CLI 命令、7 个 MCP 工具、6 组 GUI 页面、100 万字预算制分析。缺的是"从被动工具到主动设计师"的认知跃迁。deep-custom 不是加功能，是加**自我诊断**和**个性化演化**这两个能力维度。
>
> Phase 1 的三个任务（动态分类 / 结构诊断 / 认知演化）全都不需要新依赖，全都只读已有数据。**颗粒度已经拉到最细，现在可以动手了。**
