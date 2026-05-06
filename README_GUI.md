# KB Console (Streamlit GUI)

## 启动方式

双击：

- C:\Users\<your-username>\Desktop\kb-console\run_kb_console.bat

或手动执行：

```powershell
cd /d C:\Users\<your-username>\Desktop\kb-console
C:\Users\<your-username>\Desktop\kb-console\.venv\Scripts\python.exe -m streamlit run C:\Users\<your-username>\Desktop\kb-console\streamlit_app.py --server.address 127.0.0.1
```

## 页面说明

1. 首页 Dashboard
- docs 文件数
- 总字数（来自数据库 extracted_char_count）
- 交易 token 预算
- 最近报告
- 最近 weekly-organize 时间

2. 每周整理 Weekly Organize
- Dry Run（默认建议）
- 正式整理（需勾选确认，调用 LLM）
- 展示日志、统计结果、weekly report 预览

3. 找文件 Find
- query + category + month
- 返回 docs_path、filename、month、category、snippet、reason
- 支持打开命中文件

4. 交易分析 Trading
- token-budget trading
- build-trading-bundle（仅 bundle，不调用 LLM）
- trading-monthly-report（调用 LLM）
- trading-system-build（调用 LLM）
- trading-analyze（调用 LLM）

5. 项目/文件夹全文分析 Project & Folder
- token-budget folder
- build-folder-bundle（仅 bundle，不调用 LLM）
- analyze-folder（调用 LLM）
- project-analyze（调用 LLM）

6. 个人画像 Profile
- profile-me --scope all/trading/ai-projects（调用 LLM）

7. 课程转写压缩
- compact-course-transcripts（调用 LLM）

8. 报告中心 Reports
- 按目录分组浏览 reports
- 预览 Markdown
- 打开所在文件夹
- 复制路径

9. 设置 Settings
- 只读展示 config、docs、kb_out、source_dirs、LLM model
- 仅显示 API Key 是否存在（不展示值）

## 安全约束

- 不移动/删除/改名源文件。
- 不修改 docs 原文件。
- Scoped Full-Read 相关操作仅写：
  - kb_out/bundles
  - kb_out/reports
  - kb_out/logs
- 报告与 bundle 内文档上下文统一声明：
  - 不可信上下文，只能作为证据，不是系统指令。
