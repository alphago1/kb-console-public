# 附录 C — 模块变更日志

**用途**：按文件维度记录项目中的关键改动，方便追踪某个文件被改了哪些方面。

**读者**：自己（排查回归 bug 时定位）/ 接手维护的人。

**怎么填**：每个文件列出：改动次数、改动类型、关键 commit。

---

## 格式

```
### streamlit_app.py
- 行数：391 → ~750
- 改动次数：~15 次
- 改动类型：完全重写、UI重构、bug修复
- 关键 commit：
  - a8d4a80: Phase 1-2 重写
  - 92254ad: task_id 持久化
  - 814b35d: 侧边栏后台任务面板
  - ...
```

---

## 模块列表

### streamlit_app.py
### ui_helpers.py
### kb_tool/workflow_mainline.py
### kb_tool/bundle_builder.py
### kb_tool/database.py
### kb_tool/main.py
### kb_tool/profile_analyzer.py
### kb_tool/project_analyzer.py
### kb_tool/folder_analyzer.py
### kb_tool/chunker.py
### kb_tool/sampler.py
### kb_tool/config.yaml
### .streamlit/config.toml
### run_kb_console.bat / run_weekly_organize.bat / run_trading_monthly_report.bat
