# 05 — Vibe Coding 行为准则

**用途**：下次用 AI Copilot 写代码时遵守。每条来自 KB Console 项目的真实踩坑。

**读者的正确用法**：开新项目前通读一遍，把相关 prompt 模板粘贴到 CLAUDE.md 或 system prompt。

**更新规则**：每踩一个新坑就加一条。不要让这个文件变成"写完就忘"的文档。

---

## 1. 路径必须在启动时绝对化，永远不依赖 cwd

**为什么重要**：同一个 `config.yaml` 中的 `"./kb_out/kb.sqlite3"`，在 CLI（cwd=kb_tool/）和 GUI（cwd=项目根）下解析到不同的文件。CLI 连的是 201 条文档的真库，GUI 连的是 0 条文档的空库。我花了一个小时在 find_idea 代码和 FTS5 表结构上排查，实际问题是"两个进程读的不是同一个数据库"。

**本项目中的对应坑**：BUG-009（GUI 搜索 0 结果）、BUG-012（文件夹分析路径基准错误）。

**下次如何执行**：
```python
# config 加载后立即替换所有相对路径
cfg["storage"]["sqlite_path"] = str(Path(kb_tool_dir) / cfg["storage"]["sqlite_path"])
cfg["storage"]["output_dir"] = str(Path(kb_tool_dir) / cfg["storage"]["output_dir"])
# ... 所有路径字段
```

**可直接复制的 prompt 模板**：
```
项目中有 config.yaml 包含文件路径。请确保加载配置后立即把所有相对路径
（如 "./kb_out/kb.sqlite3"）替换为基于 config 文件所在目录的绝对路径。
任何使用配置路径的函数都不应依赖 os.getcwd() 来解析路径。
```

---

## 2. 内容指纹必须是确定性的全量数据

**为什么重要**：`fingerprint_sha256 = sha256(sampled_text)`，其中 `sampled_text` 包含随机采样的 3 段 500 字。同一文件处理两次 → 采样不同 → SHA 不同 → 文件名中的指纹不同 → 去重完全失效。产生 199 个重复文件，5 轮清理才清完。

**本项目中的对应坑**：BUG-008c（SHA 非确定性）。

**下次如何执行**：
```python
# 对：全文 SHA
fingerprint_sha256 = hashlib.sha256(full_text.encode()).hexdigest()

# 错：采样文本 SHA（非确定性）
fingerprint_sha256 = hashlib.sha256(sampled_text.encode()).hexdigest()
```

**可直接复制的 prompt 模板**：
```
文件内容指纹（fingerprint SHA256）必须基于全文内容计算，不能基于采样或摘要。
如果 sampler 中有 random_segments 配置，采样的文本不能用于生成唯一 ID。
文件名中如果嵌入了 SHA 作为唯一标识，这个 SHA 必须来自全文。
```

---

## 3. 测试的工作目录和配置加载路径必须和运行时一致

**为什么重要**：本项目所有测试从 `kb_tool/` 目录跑 → 相对路径解析正确 → 全部通过。GUI 从项目根跑 → 相对路径解析错误 → 搜不到东西。最危险的 bug 不是"测试失败"，是"测试通过了但功能不工作"。这是假阳性。

**本项目中的对应坑**：BUG-009 排查过程——我反复验证 `find_idea` 没问题，但因为测试目录和运行目录不同，验证的是错误的前提。

**下次如何执行**：
```bash
# 测试脚本必须从项目根跑，和运行时一致
cd $PROJECT_ROOT && python tests/test_all.py

# 不要 cd 到子目录再跑测试
# cd $PROJECT_ROOT/kb_tool && python test.py  ← 错
```

**可直接复制的 prompt 模板**：
```
测试脚本必须从项目根目录运行，和实际运行时的工作目录一致。
在测试中加载配置时，使用和 main app 相同的 load_config 函数，
不要直接 yaml.safe_load() 而跳过路径解析逻辑。
```

---

## 4. 子进程 stdout 必须禁用缓冲

**为什么重要**：Python 在管道模式下默认 4KB 全缓冲。`print()` 不立即输出 → `readline()` 一直等 → GUI 永远显示"子进程启动中..."。用户等了 1 分钟以为是死机。

**本项目中的对应坑**：BUG-011（子进程 stdout 缓冲）。

**下次如何执行**：
```python
# subprocess 调用
cmd = [sys.executable, "-u", "main.py"]  # -u 禁用缓冲
env = {**os.environ, "PYTHONUNBUFFERED": "1"}
proc = subprocess.Popen(cmd, env=env, stdout=PIPE, ...)
```

**可直接复制的 prompt 模板**：
```
所有通过 subprocess 启动的 Python 子进程：
1. 命令行中 python 后面紧跟 -u 标志
2. 环境变量设置 PYTHONUNBUFFERED=1
3. 任何需要实时读取输出的场景，子进程必须在启动后 1 秒内有第一行输出
```

---

## 5. Streamlit 中任何跨 rerun 的状态必须进 session_state

**为什么重要**：Streamlit 每次 widget 交互触发完整脚本重跑。局部变量全部重置。异步任务的 task_id 是局部变量 → 下次重跑时变成 `""` → `render_task_progress` 找不到任务 → 进度条消失。

**本项目中的对应坑**：BUG-007（task_id 不持久化）、BUG-013（切页面结果丢失）。

**下次如何执行**：
```python
# 错
task_id = run_cli_live_async(...)  # 局部变量，下次 rerun 丢失

# 对
task_id = run_cli_live_async(...)
st.session_state["current_task_id"] = task_id  # 持久化
# render 时：
task_id = st.session_state.get("current_task_id", "")
```

**可直接复制的 prompt 模板**：
```
Streamlit 的每个 widget 交互都触发完整脚本重跑。
所有需要在 rerun 之间保持的值（task_id、进度、结果、表单状态）
必须通过 st.session_state 存取，不能用普通 Python 变量。
```

---

## 6. LLM 调用前必须检查输入是否有实际数据

**为什么重要**：主题分析 0 篇文档时仍然调了 LLM → LLM 在没有任何信息的情况下列出了"我假设您研究过……"——完全是编造的。用户读到虚假报告。浪费了 token。

**本项目中的对应坑**：BUG-010（0 文档时 LLM 编造）。

**下次如何执行**：
```python
if not blocks or len(blocks) == 0:
    return {"warning": "未读入任何文件", "report": "..."}
# 只有有实际数据时才调 LLM
content = llm_call(cfg, task, prompt)
```

**可直接复制的 prompt 模板**：
```
任何调用 LLM API 的函数，在构造 prompt 前必须检查 blocks 是否为空。
blocks 为空 → 不调 API → 直接返回 "未读入任何文件"。
不要在 prompt 中只放一句 "请分析以下内容" 然后让 LLM 面对空上下文。
```

---

## 7. 硬编码的数据量上限必须改为动态预算

**为什么重要**：`rows[:80]` 对 80 篇小文档浪费空余 token，对 80 篇大文档可能炸上下文。"每篇 3000 字" 对短文档浪费，对长文档不够。应该按实际字数/Tokens 累积到上限。

**本项目中的对应坑**：BUG-015（80 篇硬上限 → 100 万字预算制）。

**下次如何执行**：
```python
# 错
for r in rows[:80]:
    blocks.append(text[:3000])

# 对
for r in rows:
    block_chars = len(text)
    if total + block_chars > MAX_CHARS:
        break
    blocks.append(text)
    total += block_chars
```

**可直接复制的 prompt 模板**：
```
不要在循环中硬编码 `[:N]` 的上限。改为基于数据量的预算制：
- 维护当前已累积的字符/Tokens 数
- 每加入一个文档前检查是否超出预算
- 超出时标注 "剩余 N 篇文档将在后续批次处理"
```

---

## 8. 浮点数跨存储介质后不用 `==` 比较

**为什么重要**：`os.stat().st_mtime` 是高精度浮点（`1746123456.789123`）。存入 SQLite REAL 后再读出可能变成 `1746123456.78912`。`==` 比较失败 → 去重失效 → 同一文件被反复处理。

**本项目中的对应坑**：BUG-008a（mtime 浮点精度）。

**下次如何执行**：
```python
# 错
if float(row["fingerprint_mtime"]) == fmtime: ...

# 对
if abs(float(row["fingerprint_mtime"]) - fmtime) < 0.1: ...
```

**可直接复制的 prompt 模板**：
```
任何跨 SQLite 存取的浮点数比较，使用容差 abs(old - new) < epsilon，
不能直接用 ==。st_mtime 的高精度小数位在 SQLite REAL 中可能丢失。
```

---

## 9. 写了一个 bug 的修复后，立即 grep 同类代码

**为什么重要**：BUG-001 发现 `weekly_organize` 调了 `KBDatabase.init()` 但 `token_budget` 没调。grep 后发现 11 个函数全有同样问题。单独修一个函数没用——修完还会炸在下一个函数。

**本项目中的对应坑**：BUG-001 泛化修复、BUG-008 三道防线、BUG-012 同类路径问题。

**下次如何执行**：
```bash
# 修完一个 bug 后
grep -rn "相同的错误模式" --include="*.py" .
```

**可直接复制的 prompt 模板**：
```
修复这个 bug 后，请用 grep 搜索全项目是否有相同的模式，一并修复。
不要只修当前报错的那个——同一个模式可能出现在 10 个函数里。
```

---

## 10. 设计函数时假设资源不存在（冷启动安全）

**为什么重要**：`_ensure_doc_columns` 假设 `documents` 表已存在，只做 ALTER TABLE。但新数据库没有这张表 → ALTER 报 `no such table`。开发环境因为已经初始化过了，永远发现不了这个问题。

**本项目中的对应坑**：BUG-001（DB 初始化缺失）。

**下次如何执行**：
```python
def init_db():
    """幂等初始化：不管表存不存在，都能安全调用"""
    con.execute("CREATE TABLE IF NOT EXISTS documents (...)")
    ensure_chunk_tables()  # 也必须是幂等的
    ensure_columns()       # PRAGMA table_info + ALTER
```

**可直接复制的 prompt 模板**：
```
每个访问数据库/文件系统的函数，入口处调用幂等的初始化函数，
不假设资源已存在。初始化函数内部用 CREATE TABLE IF NOT EXISTS。
新增表/列时同步更新初始化函数。
```

---

## 11. API 调用是 I/O 密集操作——默认并发

**为什么重要**：`compress_and_synthesize` 把文档分成 3 批，串行调 LLM —— 每批 30 秒 × 3 = 90 秒。改成 `ThreadPoolExecutor` 并发后，3 批同时跑 = 30 秒。LLM API 调用是无状态的独立 HTTP 请求，天生适合并发。

**本项目中的对应坑**：用户指出分批压缩应该并发执行。

**下次如何执行**：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
    futures = {pool.submit(llm_call, chunk): i for i, chunk in enumerate(chunks)}
    for f in as_completed(futures):
        results[futures[f]] = f.result()
```

**可直接复制的 prompt 模板**：
```
LLM API 调用是无状态的 HTTP 请求。多批次处理时使用 ThreadPoolExecutor
并发执行，max_workers 从 config 的 max_concurrency 读取。
不要用 for 循环串行调 LLM。
```

---

## 12. 空口说"完成了"比什么都不说更差——用命令验证

**为什么重要**：我多次对用户说"修复完成"但实际没验证。用户自己测试发现还是坏的。最严重的是 BUG-009——我声称搜索正常但其实从来没从项目根跑过测试。

**本项目中的对应坑**：BUG-009 排查全过程——我在错误方向上浪费了 1 小时，因为我"确认"后端正常，但确认的方法是错的。

**下次如何执行**：
```bash
# 每次说"修好了"之前
python -c "实际模拟用户操作的测试" && echo "PASS" || echo "FAIL"
```

**可直接复制的 prompt 模板**：
```
完成修复后，必须运行一个验证命令来证明修复生效。
验证命令应该在和用户实际使用环境相同的条件下执行。
输出验证命令和关键输出，而不是只说"已完成"。
```

---

## 使用方式

下次开项目时，把这份文件作为 CLAUDE.md 的一部分：

```
本项目遵循 Vibe Coding Rules（见 docs_dev_retro/05_vibe_coding_rules.md）。
所有代码生成和修改必须遵守这些规则。
每发现一个新 bug 后，更新该文件添加新规则。
```
