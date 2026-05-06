# 06 — AI 编程项目启动 + 执行 Checklist

**用途**：下次开 AI Copilot 项目时，逐项勾选。放在 CLAUDE.md 或 system prompt 中。

---

## 1. 需求边界

- [ ] 核心功能用一句话能说清楚
- [ ] 明确标记哪些是"主线"，哪些是"experimental"
- [ ] 没有硬编码用户特定的业务名称（如"交易分析"）→ 改为通用名 + 预设
- [ ] 问自己：用户实际会每天用吗？还是"看起来很酷"？
- [ ] "以后可能需要"的功能 → 不写。等有人要了再加
- [ ] 先做 mockup（假数据 + 纯 UI）给用户看，确认方向再写代码

## 2. 数据与路径

- [ ] 配置文件中所有路径在加载后立即解析为绝对路径（`Path.resolve()`）
- [ ] 不依赖 `os.getcwd()` 解析相对路径
- [ ] 数据库初始化函数幂等（`CREATE TABLE IF NOT EXISTS`）
- [ ] 内容指纹（SHA256）基于全文，不基于采样/摘要
- [ ] 文件名中嵌入的 hash 来自确定性全量数据
- [ ] 浮点数跨 SQLite 存取后不用 `==` 比较，用 `abs(diff) < epsilon`
- [ ] `Path.exists()` 检查后再读文件——DB 中的路径可能过期

## 3. 文件安全

- [ ] 源文件只读，写操作限定在 `output/` 目录
- [ ] `_unique_path` 在文件已存在时检查内容 SHA，不止看文件名
- [ ] 配置保存前自动备份（`.bak` 文件）
- [ ] API Key 不出现在任何日志/界面上

## 4. CLI / GUI

- [ ] Windows 下 `chcp 65001` + `PYTHONIOENCODING=utf-8`
- [ ] `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`
- [ ] 子进程调用：`python -u` + `PYTHONUNBUFFERED=1`
- [ ] Streamlit：所有跨 rerun 状态进 `st.session_state`
- [ ] 后台任务：task_id 持久化到 session_state
- [ ] 后台任务：启动时 toast 提醒"可浏览其他页面"
- [ ] 后台任务：完成时 toast + 提示音 + 侧边栏显示结果
- [ ] 长操作必配：进度条 / 取消按钮 / 完成通知
- [ ] 按钮标签：中文优先，英文括号补充
- [ ] "全部"作为下拉框默认值，不硬编码特定月份

## 5. LLM 调用

- [ ] 调用前检查 `blocks`/输入是否为空 → 空则直接返回"未读入文件"不调 API
- [ ] 不用 `rows[:N]` 硬截断 → 按字数/Token 预算制动态累积
- [ ] 搜索范围由用户选择的文件夹决定，不在后端写死分类列表
- [ ] Topic 是 LLM 分析指令，不是 SQL 过滤条件
- [ ] 多批次 LLM 调用使用 `ThreadPoolExecutor` 并发（不是 for 循环串行）
- [ ] 超出上下文上限 → 分批 LLM 压缩 → 合成，不截断
- [ ] Prompt 中加约束："只能基于提供的文档，缺乏信息时明确说'文档中未涉及'"

## 6. 日志与验收

- [ ] 每次 LLM 调用记录：task / model / prompt_chars / response_chars / 时间
- [ ] Agent/MCP 工具调用记录审计日志（谁调的、什么参数、是否允许）
- [ ] 重要操作生成 run_id
- [ ] Copilot 说"已完成" → 必须贴出验证命令和关键输出
- [ ] 从用户的实际使用路径验证（不是从开发目录）

## 7. 回归测试

- [ ] 测试从**项目根目录**跑，和运行时工作目录一致
- [ ] 测试用和 main app 相同的配置加载函数（不直接 `yaml.safe_load`）
- [ ] 覆盖所有 GUI 调用的后端函数
- [ ] 覆盖所有 CLI 命令的 `--help` 参数解析
- [ ] 冷启动测试：临时空 DB 验证所有功能不崩
- [ ] 搜索功能：中文/英文/空查询/不存在词/文件名命中 至少 5 个 case
- [ ] 修完 bug 后 `grep` 同类代码模式，一并修复

## 8. 与 Copilot 协作规则

- [ ] 项目根放 `CLAUDE.md`，包含以上规则的精简版
- [ ] 每次 Copilot 生成/修改代码后跑 `py_compile.compile()` 语法检查
- [ ] Copilot 改完函数后，让它 `grep` 列出所有调用方确认不受影响
- [ ] 关键模块（路径/指纹/ID 生成/并发）——人主动审查，不依赖 Copilot 预警
- [ ] Copilot 提出方案后，先问"有没有更简单的做法？"再让它写代码
- [ ] git 的 checkpoint：关键节点前主动 commit，"尽可能少打扰我"
- [ ] 让 Copilot 写测试时，指定"从项目根目录跑，用和 main app 相同的方式加载配置"
- [ ] 每次会话结束前，让 Copilot 更新这份 checklist（加了什么新规则）
