# kb_tool（Word-first 每周整理 + 交易分析主线）

## 当前主线

- `weekly-organize`：每周只处理新增/变更文件，复制到 `docs/<category>/<month>/`，更新 SQLite/FTS/text_cache，并输出周报。
- `token-budget --scope trading`：统计四个交易分类的 token 预算并给出读入策略。
- `build-trading-bundle`：生成可直接喂给大模型的交易全文 bundle。
- `trading-monthly-report --month YYYY-MM`：基于当月交易全文生成交易月报。
- `trading-system-build`：从交易全文提炼买卖/止损/仓位等系统规则。
- `trading-analyze --topic "..."`：围绕指定主题做交易深度分析。
- `find --query "..."`：查“某个想法在哪个文件”，输出 docs 路径与命中片段。
- `compact-course-transcripts`：压缩课程转写，保留规则与可执行结论。

## Experimental（降级保留）

- `agent` / `agent-test`
- `mcp-stdio` / `mcp-http` / `mcp-list-tools` / `mcp-smoke-test`

## 快速开始

1) 安装依赖

```powershell
cd "C:\Users\<your-username>\Desktop\kb-console\kb_tool"
python -m pip install -r requirements.txt
```

2) 配置

- 复制 `config.example.yaml` 为 `config.yaml`
- 设置环境变量 `DEEPSEEK_API_KEY`

3) 每周整理（主流程）

```powershell
python main.py weekly-organize --config config.yaml
```

4) 交易分析主流程

```powershell
python main.py token-budget --scope trading --config config.yaml
python main.py build-trading-bundle --config config.yaml
python main.py trading-monthly-report --month 2026-03 --config config.yaml
python main.py trading-system-build --config config.yaml
python main.py trading-analyze --topic "止损执行" --config config.yaml
python main.py find --query "回调确认" --config config.yaml
```

> 安全原则：不会移动/删除/改名原文件；仅复制到 `docs/`，仅写入 `kb_out/`。
