# 03 — 需求演进记录

**用途**：追溯"最初想做什么 → 实际做了哪些 → 为什么有些被砍掉"的完整过程。

**读者**：自己 / 做类似项目时参考需求漂移规律的人。

**核心问题**：为什么最终是 Word-first + docs/ + reports/ + full-read analysis + GUI 这个结构？

---

## 1. 最初我们以为要做什么

项目最早叫"kb-console"，2025-04 启动。最初的 README 和 `当前项目功能总结与演进建议.md` 记录了原始雄心：

### 1.1 原始目标：一个"全能型"本地知识库系统

```
数据接入层         存储与检索层         AI 分析层            展现层           对外接口层
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐
│ 多格式扫描 │ →  │ SQLite   │ →  │ LLM 分类  │ →  │ Dashboard│ →  │ MCP Server   │
│ 智能采样  │    │ + FTS5   │    │ 标签归一  │    │ 月报/季报│    │ Agent Runtime│
│ 标签清洗  │    │          │    │ 混合策略  │    │ Bundle   │    │ FastAPI Web  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────────┘
```

当时以为要做一个"本地智能化知识库系统"，具备：
- **完整的 Agent Runtime**：沙盒执行环境、Tool Registry、Schema、权限校验
- **MCP 协议标准接口**：stdio + HTTP 双模式，给 Claude Desktop / Cursor 集成
- **FastAPI Web 服务**：Dashboard HTML、API 端点
- **Review UI**：HTML 人工复核界面，置信度存疑的结果写入 CSV，人工改完写回 SQLite
- **多 LLM Provider**：DeepSeek / Claude / Gemini / OpenAI 四个适配器
- **季报生成**：季度性统计报告
- **模型上下文打包**：Context Bundle 一键丢给在线大模型
- **标签归一化**：emotion_tags / topic_tags 清洗

### 1.2 原始用户画像

当时假设的用户是**自己**——一个既有交易笔记又有 AI 研究笔记的人。系统需要处理两类完全不同的内容（交易复盘 vs AI 论文笔记），所以设计了复杂的分类体系（11 个分类）。

### 1.3 原始数据流

当时设想的数据流是：桌面文件 → scan 扫描 → 采样 → LLM 分类 → 写入 SQLite → 构建 Chunk → FTS 索引 → Dashboard 大盘。每一步都是独立的 CLI 命令。

---

## 2. 哪些需求被证明是过度设计

### 2.1 FastAPI Web 服务 → 被 Streamlit 取代

**最初**：`server.py` 用 FastAPI + uvicorn 提供 Web 服务和 API。还有 Jinja2 模板渲染 HTML Dashboard。

**演化**：实际使用中，单用户本地应用不需要 FastAPI 的重量。Streamlit 更适合——改动即时可见，不需要前后端分离。FastAPI 的代码 (`server.py`) 和 Dashboard 模板 (`templates/dashboard.html.j2`) 仍然存在但**从未被实际使用**。

**教训**：单用户本地工具不需要 Web API 层。Streamlit 的"Python 即 UI"模型比 FastAPI + 前端框架的组合更适合这种场景。

### 2.2 多 LLM Provider → 只用 DeepSeek

**最初**：`llm_providers/` 目录下有 `deepseek_provider.py`、`claude_provider.py`、`gemini_provider.py`、`openai_provider.py` 四个适配器。

**演化**：实际只用 DeepSeek。其他三个 provider 的代码存在但从没被调用过。后来所有 LLM 调用都直接 hardcode 了 `DeepSeekProvider`。

**教训**："以后可能换模型" 的抽象成本很高——4 个 provider 类、1 个 base 类——但实际收益为零。应该先用一个 provider 硬编码，真的需要换了再抽象。

### 2.3 Review UI → 从未使用

**最初**：`review_ui.py` 生成 HTML 界面，展示低置信度分类结果。用户可以手动修改分类/标签，导出 CSV，通过 `apply-review` 命令写回 SQLite。

**演化**：这套流程从未被实际使用。低置信度的文档要么被放在"无法判断"分类里，要么在下次 weekly_organize 中被重新分类。

**教训**：人工审核流程的设计假设是"用户愿意花时间审核 AI 结果"——但实际用户更倾向于"差不多就行，下次再扫"。在设计人工干预流程之前，先确认用户真的有耐心用它。

### 2.4 季报 → 被月报/周报取代

**最初**：`quarterly_report.py` 生成季度报告。

**演化**：weekly_organize 自动生成周报，trading_monthly_report 生成月报。季报从未被实际使用——用户的分析节奏是周/月，不是季度。

**教训**：报告周期应该匹配用户的实际使用频率。如果用户每周跑一次整理，就生成周报。不要因为"季报看起来更正式"就做。

### 2.5 复杂的标签归一化系统 → 简单化

**最初**：`tag_normalizer.py` 对 emotion_tags 和 topic_tags 做归一化清洗。还有 `classifier_rules.py` 做规则+LLM 混合分类。

**演化**：这些模块存在但功能有限。大多数文档的标签是由 LLM 一次性生成的，归一化的需求没有预想的那么大。

---

## 3. 哪些需求被降级为 experimental

### 3.1 Agent Runtime

**最初标记**：`agent: ... [experimental]`

**演化**：Agent 在 v1 时是"实验性"的，但在 v2 中成为了智能搜索的核心引擎。它从 experimental 升格为主线功能——但 CLI 入口仍然标着 `[experimental]`。

**当前状态**：Agent 是智能搜索的后端，但 `main.py` 中的 help 文本没更新。

### 3.2 MCP Server

**最初标记**：`mcp-stdio` 和 `mcp-http` 标着 `[experimental]`

**演化**：MCP 接口实际上工作正常。`mcp-smoke-test` 全部通过（路径脱敏、审计日志、未知工具拒绝、路径输入拒绝）。但它没有被实际集成到 Claude Desktop 中使用。

**当前状态**：代码完整、测试通过，但缺乏实际端侧验证。

### 3.3 课程转写压缩

**最初**：`compact-course-transcripts` 是一个独立 CLI 命令。

**演化**：在 v2 GUI 中保留了页面入口，但加了详细的功能解释（"为什么要压缩"）。用户使用频率低——它是一个"知道有但很少用"的功能。

**当前状态**：保留在"整理与维护"分组中，功能完整但非主线。

---

## 4. 哪些需求被保留为主线

### 4.1 Word-first 入库流程（scan → extract → classify → store）

**为什么保留**：这是整个系统的核心价值——用户不改习惯，桌面随手建 Word 文件就能自动入库。

**演化过程**：
- v0：每个步骤都是独立 CLI 命令
- v1：`weekly_organize` 一线串联，但需要手动触发
- v2：GUI 中文件夹选择器 + 递归开关 + 实时文件计数 → 从"全量盲扫 3792 个文件"变成"精确选择 329 个文件"

### 4.2 全文检索（Find）

**为什么保留**：找到"某个想法在哪个文件里"是最高频的操作。

**演化过程**：
- v0：FTS5 关键词搜索
- v1：GUI 中加了 category/month 过滤
- v2：双模式——快速搜索（毫秒级）+ 智能搜索（Agentic，10-30 秒）

### 4.3 全文分析（Full-Read Analysis）

**为什么保留**：这是"区别于普通笔记软件"的杀手功能——不是搜关键词，而是"把相关文档全读一遍，告诉我结论"。

**演化过程**：
- v0：hardcoded "交易分析"，只搜 4 个交易分类
- v1：加了"文件夹分析"和"个人画像"
- v2：统一为"自定义分析"模块，通用化 + 预设模板
- 后续：80 篇硬上限 → 100 万字预算制 → 超出自动分批并发压缩合成

### 4.4 报告中心

**为什么保留**：所有 LLM 生成的分析报告需要一个统一的浏览/下载入口。

**演化过程**：从简单的 Markdown 预览 → 加了分组浏览、下载按钮、排序。

### 4.5 后台任务 + 进度反馈

**为什么保留**：LLM 分析需要 30 秒到几分钟，不能让用户干等。

**演化过程**：
- v1：同步阻塞 `while True` 循环
- v2：后台线程 + 进度条 + 切页面不丢进度
- 后续：toast 通知 + 提示音 + 侧边栏持久面板 + "可浏览其他页面" 提示

---

## 5. 为什么最终是这个结构

### 最终结构

```
kb-console/
├── docs/           ← 知识库本体（按分类/月份组织）
├── kb_tool/        ← 后端引擎（CLI + Agent + MCP）
│   └── kb_out/     ← 所有产物
│       ├── kb.sqlite3     ← 元数据库
│       ├── reports/       ← LLM 分析报告
│       ├── bundles/       ← 全文分析 bundle
│       └── logs/          ← 运行日志
├── streamlit_app.py ← GUI 入口
├── ui_helpers.py    ← GUI 基础设施
└── tests/           ← 测试套件
```

### 5.1 为什么是 Word-first

用户的笔记习惯是**桌面随手建 `.docx`**。改变习惯的成本远高于适配习惯的成本。系统通过 `weekly_organize` 桥接"用户的习惯"和"系统的存储"：桌面文件 → AI 分类 → 按 category/month 归入 `docs/`。

这个决策意味着：不需要导入、不需要迁移、不需要学习新工具。用户在桌面上怎么做，系统就怎么接。

### 5.2 为什么 docs/ + reports/ 分离

- `docs/`：用户的原始内容（被分类和重命名，但内容不变）。这是"source of truth"。
- `kb_out/reports/`：LLM 分析生成的二次内容（月报、画像、主题分析）。这是"derived insights"。

分离的原因是：reports 可以被删除和重新生成（跑一次分析就行），docs 不能丢。这对应了数据管理的两个层级。

### 5.3 为什么是 Full-Read Analysis 而不是 RAG

RAG（检索增强生成）的典型流程是：用户提问 → embedding 检索相关 chunks → LLM 基于 chunks 回答。这个流程在知识库场景下有一个致命问题：**用户不知道自己的知识库中有什么，所以无法提出精确的问题**。

Full-Read Analysis 的流程是：用户选一个范围（文件夹 + 时间）→ 系统把范围内**所有内容**读给 LLM → LLM 输出结构化分析。这个流程更适合"我想知道我在这段时间写了什么、想了什么"的场景。不是"我有个问题要查答案"，而是"帮我理解我自己"。

### 5.4 为什么是 Streamlit GUI 而不是 CLI 或 FastAPI

CLI 适合开发者，不适合日常使用。FastAPI 需要前后端分离——对于一个单用户本地应用来说太重了。Streamlit 的"Python 即 UI"模型最小化了从"后端能力"到"用户界面"的转换成本。新增一个分析功能只需要：写一个 Python 函数 + 在 GUI 里加一个按钮。

### 5.5 为什么保留 MCP 但不作为主交互方式

MCP 接口的价值在于**外部工具的集成**（Claude Desktop、Cursor）。它不是日常使用的入口，但它是"让知识库成为 AI 基础设施的一部分"的关键。保留它的成本极低（已经写好了），但用户需要的时候直接可用。

---

## 6. 需求变化规律（从本项目总结）

| 规律 | 本项目中的例子 |
|------|------|
| **用户实际使用后才暴露真实需求** | GUI 上线后才发现搜索、后台任务、文件夹选择器的真实需求 |
| **"以后可能需要"的功能大概率不需要** | 多 LLM Provider、Review UI、季报 |
| **用户一句话推翻复杂设计** | "就和下载文件选定目录一样" → 文件夹选择器 |
| **技术方案从复杂变简单的方向** | Embedding → Agentic Search、递归嵌套 → split+并发 |
| **硬编码的业务名称必然被泛化** | "交易分析" → "自定义分析" |
| **用户更关心"少等"而非"功能多"** | 并发压缩、后台任务、进度条的需求优先级高于新功能 |

---

## 7. 如果重来：应该先做和后做的顺序

**先做**：
1. Word-first 入库流程（这是核心价值）
2. 全文检索（最高频操作）
3. Full-Read Analysis（差异化能力）
4. Streamlit GUI（降低使用门槛）

**后做**：
5. 后台任务 + 进度反馈（功能有了再优化体验）
6. MCP 接口（有人要集成再加）
7. 并发优化（量大了再加）

**不做**：
8. 多 LLM Provider 适配（实际只有一个在用）
9. Review UI 人工审核（用户没耐心）
10. FastAPI Web 服务（Streamlit 就够了）
