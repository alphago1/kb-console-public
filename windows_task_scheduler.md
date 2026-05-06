# Windows 任务计划程序配置说明

## 1. 每周自动整理（weekly-organize）

1. 打开“任务计划程序”。
2. 选择“创建基本任务”。
3. 名称建议：`KB Weekly Organize`。
4. 触发器选择：每周（例如每周日 21:30）。
5. 操作选择：启动程序。
6. 程序/脚本填写：
   - `C:\Windows\System32\cmd.exe`
7. 添加参数填写：
   - `/c "C:\Users\<your-username>\Desktop\kb-console\run_weekly_organize.bat"`
8. 完成并保存。

## 2. 每月交易月报（trading-monthly-report）

建议在每月 1 号执行上个月报告，可创建单独任务：

1. 任务名称建议：`KB Trading Monthly Report`。
2. 触发器：每月（例如每月 1 日 08:30）。
3. 程序/脚本：
   - `C:\Windows\System32\cmd.exe`
4. 添加参数（示例生成 2026-04 月报）：
   - `/c "C:\Users\<your-username>\Desktop\kb-console\run_trading_monthly_report.bat 2026-04"`

> 注意：计划任务里月份参数是固定值，建议每月手动更新，或后续改成一个自动计算上月的 PowerShell 脚本。

## 3. 日志与审计

- 应用日志：`C:\Users\<your-username>\Desktop\kb-console\kb_tool\kb_out\logs`
- weekly 周报：`C:\Users\<your-username>\Desktop\kb-console\kb_tool\kb_out\reports\weekly`
- LLM 调用日志：`C:\Users\<your-username>\Desktop\kb-console\kb_tool\kb_out\logs\llm_calls.jsonl`
