# 02 — Bug 案例手册

**用途**：每个 bug 的完整 RCA + 验收证据 + 可复用的预防规则。

**读者**：自己（下次踩坑前翻一遍）/ 用 AI Copilot 做 Python 项目的开发者。

**统计**：开发全程发现 P0 5 个 / P1 6 个 / P2 4 个 = 15 个重要 bug。

---

## Bug 001：DB 初始化缺失 — `no such table: documents`

### 现象
Streamlit 首页加载时报错 `sqlite3.OperationalError: no such table: documents`，traceback 指向 `_ensure_doc_columns()` 中的 `ALTER TABLE documents ADD COLUMN source_path TEXT`。

### 当时上下文
`workflow_mainline.py` 中 11 个函数都需要访问 documents 表。只有 `weekly_organize()` 在 DB 操作前先调了 `KBDatabase(cfg).init()`。另外 10 个函数直接调 `_ensure_doc_columns()` 甚至裸 SQL 查询。

### 错误尝试
最初以为只影响一两个函数，准备逐个加 `init()` 调用。代码审查后发现 10 个函数全有同样问题——从点到面。

### 根因
`_ensure_doc_columns()` 只负责 ALTER TABLE 加列，不负责 CREATE TABLE。表可能不存在，`PRAGMA table_info(documents)` 对不存在的表返回空集（不报错），随后 `ALTER TABLE` 才对不存在的表报错。冷启动（新数据库）必然触发。

### 最终修复
创建 `_init_and_ensure_columns(cfg)` 统一函数，内部先 `KBDatabase(cfg).init()`（CREATE TABLE IF NOT EXISTS）再 `ensure_chunk_tables()`（chunk + FTS 表）再 ALTER COLUMN。全部 11 个调用点替换为这一个入口。`bundle_builder.py` 的 `_ensure_columns()` 同样改造。

### 验收命令
```python
import tempfile; tmp = tempfile.mktemp(suffix='.sqlite3')
cfg['storage']['sqlite_path'] = tmp
_init_and_ensure_columns(cfg)
con = sqlite3.connect(tmp)
assert 'documents' in [r[0] for r in con.execute("SELECT name FROM sqlite_master").fetchall()]
```

### 验收结果
✅ 冷启动自动创建 documents + document_chunks + document_chunks_fts 三张表。

### 下次避免规则
> **规则：任何访问数据库的函数，入口处统一调用幂等的初始化函数。不要假设"表已经存在"。**

### 下次给 AI 的提示
```
写任何从 DB 读写的函数时，第一行必须调用 _init_db()。
_init_db() 内部用 CREATE TABLE IF NOT EXISTS，保证幂等。
```

---

## Bug 002：中文字符路径乱码 — Windows GBK vs UTF-8

### 现象
CLI JSON 输出中所有中文变成乱码（`交易系统与方法论` → `����ϵͳ�뷽����`）。agent_test 中 3/5 测试的 print() 因 Emoji 字符（📊🧠）抛出 `UnicodeEncodeError`。

### 当时上下文
Windows 中文版终端默认代码页 GBK（CP936）。Python 检测终端编码后将 stdout 设为 GBK。文件系统路径是 UTF-8。UTF-8 内容通过 GBK stdout → 乱码。项目根目录名 `kb-console` 本身含中文。

### 错误尝试
最初只改了 `streamlit_app.py` 中 subprocess 的 `errors="ignore"` → `errors="replace"`——但这只是让错误被静默替换，不解决根因。

### 根因
`sys.stdout.encoding = 'gbk'`，`sys.getfilesystemencoding() = 'utf-8'`。Python 没有检测到应该用 UTF-8 的环境变量。批处理文件没设 `chcp 65001`。

### 最终修复
三层修复：
1. `main.py`：`sys.stdout.reconfigure(encoding='utf-8', errors='replace')`（去掉 `isatty()` 判断——管道也需要 UTF-8）
2. 所有 `.bat`：添加 `chcp 65001` + `set PYTHONIOENCODING=utf-8`
3. `streamlit_app.py` subprocess：`errors="ignore"` → `errors="replace"`

### 验收命令
```python
import sys; sys.stdout.reconfigure(encoding='utf-8')
print("交易系统与方法论")  # 应正确显示
```

### 验收结果
✅ 从项目根 `python main.py find --query "止损"` 输出中文正确。

### 下次避免规则
> **规则：项目第一天就在 `.bat` / `CLAUDE.md` / `Makefile` 中设 `chcp 65001` + `PYTHONIOENCODING=utf-8`。**

### 下次给 AI 的提示
```
项目在 Windows 中文版环境运行。所有 Python 入口文件开头加：
if sys.platform == 'win32':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8', errors='replace')
```

---

## Bug 003：agent_test 错误统计 — print 异常被当作工具调用失败

### 现象
agent_test 显示 `PASS=False ERROR='gbk' codec can't encode character '\U0001f4ca'`。但汇总显示 `5/5 passed`。Agent 实际 5/5 返回有效答案。

### 当时上下文
`cmd_agent_test` 中 `try: res = rt.run(q); print(...)` 被一个 `except Exception as e: print(f"PASS=False ERROR={e}")` 包裹。print 抛出 `UnicodeEncodeError`（因为 agent 答案含 Emoji）→ 被 `except Exception` 捕获 → 误显示 `PASS=False`。但 `passed += 1` 在 print 之前执行，所以汇总仍是 `5/5`。

### 根因
`try/except` 的范围太大——覆盖了工具执行和 print 输出两个不同层面的异常。

### 最终修复
分离 Agent 执行和 print：先用变量保存结果，`passed` 计数在 try 内完成。print 单独用 `try/except UnicodeEncodeError` 包裹，失败时打印 `<skipped: encoding error>`。

### 验收命令
（需在 GBK 终端环境验证）

### 验收结果
✅ 代码审查通过——print 异常不再影响测试计数。

### 下次避免规则
> **规则：try/except 范围要精确。I/O 操作（print）和业务逻辑不要放在同一个 try 里。**

### 下次给 AI 的提示
```
print() 语句的异常必须和业务逻辑异常分开捕获。
用单独 try/except UnicodeEncodeError 包裹任何可能输出 Emoji 的 print。
```

---

## Bug 004：search 命令在已删除文件上 extract 报错

### 现象
`search` 命令输出 `ERROR extract failed: ... FileNotFoundError`。DB 中有记录但文件已被移动/删除。

### 根因
`chunker.py build_chunks()` 对 DB 中所有 include_in_kb=1 的文档逐个调 `extract_text()`，不检查文件是否存在。

### 最终修复
三处文件读取前加 `Path.exists()` 检查：
- `chunker.py:88`：`if Path(path).exists(): extract_text(...)`
- `workflow_mainline.py _read_doc_text`：`if not path or not Path(path).exists(): return ""`
- `bundle_builder.py _read_text_by_row`：同上

### 验收命令
```bash
python main.py search --config config.yaml --query "测试"
# 期望：无 FileNotFoundError
```

### 验收结果
✅ search 输出无 FileNotFoundError。

### 下次避免规则
> **规则：任何文件 I/O 前先 `Path.exists()`。DB 中记录的路径可能过期。**

---

## Bug 005：`st.script_run_ctx` 不存在

### 现象
点击智能搜索 → `AttributeError: module 'streamlit' has no attribute 'script_run_ctx'`

### 根因
`ui_helpers.py` line 225 写了 `ctx = st.script_run_ctx`。Streamlit 1.56 中该属性不存在。正确 API 是 `from streamlit.runtime.scriptrunner import get_script_run_ctx`。

### 最终修复
直接导入 `get_script_run_ctx()` 替代 `st.script_run_ctx`。

### 验收命令
Streamlit GUI → 查找 → 智能搜索 → 点击搜索 — 不再报 AttributeError。

### 验收结果
✅ 智能搜索正常启动。

### 下次避免规则
> **规则：AI 生成的 Streamlit 代码中 `st.xxx` 属性可能不存在于当前版本。看到未验证过的 `st.xxx` 属性访问时，先 `grep` 确认。**

### 下次给 AI 的提示
```
不要使用 st.script_run_ctx。正确写法：
from streamlit.runtime.scriptrunner import get_script_run_ctx
ctx = get_script_run_ctx()
```

---

## Bug 006：缺失 `import json`

### 现象
智能搜索完成后 `NameError: name 'json' is not defined`

### 根因
`streamlit_app.py` line 279 用了 `json.dumps()` 但没 import。AI 生成代码时遗漏。

### 最终修复
文件头部添加 `import json`。

### 下次避免规则
> **规则：AI 生成的代码必须通过语法检查（`py_compile.compile`），不能仅凭"看起来 OK"就提交。**

---

## Bug 007：task_id 跨 Streamlit rerun 丢失

### 现象
异步任务启动后，页面 rerun（如进度更新/切换 widget），进度条消失。下次 rerun 时 `task_id` 局部变量被重置为 `""`，`render_task_progress()` 找不到运行中的任务。

### 根因
6 个页面中的 `task_id` 是局部变量，每次 Streamlit 重跑脚本时重新赋值。任务状态（`f"{task_id}_running"`）在 session_state 中存在，但局部变量 `task_id` 的值已经变了。

### 最终修复
所有 `run_cli_live_async` 返回的 task_id 存入 `st.session_state[key]`（`wo_task_id`、`ta_task_id`、`fa_task_id` 等），render 时从 session_state 中读取。

### 验收命令
在 GUI 中启动一个任务 → 切换到其他页面 → 切回来 → 进度条仍在。

### 验收结果
✅ 任务进度跨页面保持。

### 下次避免规则
> **规则：Streamlit 中任何需要跨 rerun 保持的值必须存入 `st.session_state`。局部变量在每次脚本执行时重置。**

### 下次给 AI 的提示
```
Streamlit 的每个 widget 交互触发完整脚本重跑。所有跨 rerun 的状态
（task_id、进度、结果）必须通过 st.session_state 持久化，不能用局部变量。
```

---

## Bug 008：文件重复 — 三道防线全线崩溃

### 现象
`docs/` 目录积累 199 个重复文件，DB 从 400 → 153 真实文档。用户发现 `Gemini的一些问题_b8eb29c9.docx` 和 `Gemini的一些问题_b8eb29c9_2.docx` 同时存在。

### 子案例 Bug 008a：mtime 浮点精度丢失

#### 现象
同一源文件每次 weekly_organize 都被重新处理。

#### 根因
去重检测 `float(row["fingerprint_mtime"]) == fmtime`。`os.stat().st_mtime` 是 `1746123456.789123`，SQLite REAL 存取后可能变成 `1746123456.78912`（末位精度丢失），`==` 比较失败。

#### 最终修复
`==` → `abs(existing_mtime - fmtime) < 0.1`

### 子案例 Bug 008b：`_unique_path()` 无内容去重

#### 现象
文件名出现 `_2`、`_3` 后缀。

#### 根因
mtime 去重失败后文件被重新处理，最终文件名相同，`_unique_path` 发现已存在 → 机械加 `_2` 后缀，不检查内容是否相同。

#### 最终修复
移动到最终位置前，若同名+SHA 文件已存在 → 删除临时文件 + 清理 DB 孤儿行 + 直接更新已有行。

### 子案例 Bug 008c：SHA 来自随机采样（核心设计缺陷）

#### 现象
同一源文件多次处理后文件名中 SHA 不同（`0322笔记_b94d2c1c.docx` vs `0322笔记_9c962cc0.docx`），实际内容完全相同。

#### 根因
`config.yaml` 中 `sampler.random_segments: 3` 使每次采样随机选 3 段 500 字。不同处理 → 不同随机位置 → 采样文本不同 → `fingerprint_sha256 = sha256(sampled_text)` 不同 → 文件名中的 SHA 不同。文件名中嵌入非确定性的值 → 去重完全失效。

#### 最终修复
`database.py` line 340：`fingerprint_sha256 = sha256(sampled)` → `sha256(full_text)`。

### 验收命令
```python
# 同一文件处理两次，SHA 必须相同
db.process_file(fr1, run_id='r1')
sha1 = con.execute("SELECT fingerprint_sha256 FROM documents WHERE path=?", (p,)).fetchone()
db.process_file(fr2, run_id='r2')
sha2 = con.execute("SELECT fingerprint_sha256 FROM documents WHERE path=?", (p,)).fetchone()
assert sha1 == sha2
```

### 验收结果
✅ SHA 确定性验证通过。5 轮清理共删除 199 个重复文件。DB 从 400 → 153 真实文档。

### 下次避免规则
> **规则：内容指纹必须基于确定性全量数据。随机采样的结果不能作为唯一 ID。文件名中的 hash 必须是全文 SHA。**

### 下次给 AI 的提示
```
fingerprint_sha256 必须基于全文计算，不能用 sampled_text。
sampler 的 random_segments 产生非确定性输出 → 不适合做去重。
浮点数跨 SQLite 存取后用 abs(diff) < epsilon 比较，不用 ==。
```

---

## Bug 009：GUI 搜索无结果 — cfg 相对路径指向空库

### 现象
GUI 搜索"ai"返回 0 条结果，但从 CLI 跑 `find --query "ai"` 返回 14 条。用户反复测试后确认 GUI 搜不到任何东西。

### 当时上下文
我（AI Copilot）的所有测试都从 `kb_tool/` 目录运行，测试全部通过。用户用 GUI 搜任何关键词都是 0 结果。

### 错误尝试
我反复检查 `find_idea` 函数逻辑、FTS5 表结构、chunk 数据——全是正常的。浪费了大量时间在错误的方向上。

### 根因
`config.yaml` 中 `sqlite_path: "./kb_out/kb.sqlite3"` 是相对路径。
- CLI 从 `kb_tool/` 运行 → 解析为 `kb_tool/kb_out/kb.sqlite3` → 201 条文档
- GUI（Streamlit）从项目根运行 → 解析为 `root/kb_out/kb.sqlite3` → **0 条文档**
- 项目根 `kb_out/` 目录下确实有一个 SQLite 文件——是早期某个操作留下的空库，有表结构但没有数据
- 我在 `kb_tool/` 下跑的所有测试都在正确的库上 → 全部通过 → 误判"后端正常"

### 最终修复
`load_app_paths()` 中把 `cfg` dict 里的所有相对路径（`sqlite_path`、`output_dir`、`reports_dir`、`logs_dir`、`docs_root`）替换为基于 `kb_tool_dir` 解析的绝对路径。

### 验收命令
```python
from ui_helpers import load_app_paths
cfg, paths = load_app_paths(workspace_root=Path('.'))
assert os.path.isabs(cfg['storage']['sqlite_path'])
from workflow_mainline import find_idea
assert find_idea(cfg, 'ai')['count'] > 0  # 从项目根跑也必须 > 0
```

### 验收结果
✅ 从项目根目录调用 `find_idea(cfg, 'ai')` → 14 条结果。

### 下次避免规则
> **规则：配置文件中的相对路径必须在加载时立即解析为绝对路径。测试必须在和运行时相同的工作目录下执行。不同工作目录下的相同代码=不同行为。**

### 下次给 AI 的提示
```
配置文件中所有路径在加载后立即用 Path.resolve() 转为绝对路径。
不要在运行时依赖 os.getcwd() 解析相对路径。
写测试时从项目根目录跑，不要从子目录。
```

---

## Bug 010：主题分析没读文件 — LLM 凭空编造报告

### 现象
主题分析 "我具体研究了哪些ai技术" 生成的报告中说"根据您的要求，我假设您已研究过一系列用于交易决策的AI技术"——LLM 在编造答案。

### 当时上下文
用户选"AI与工具化"文件夹，topic 填"我具体研究了哪些ai技术"。分析完成后发现报告全是编的，完全没有引用实际文档。

### 根因
两个子问题叠加：
1. **搜索范围错误**：`trading_analyze` 写死了只搜 4 个交易分类（`_trading_categories(cfg)`），用户选的 "AI与工具化" 文件夹被忽略 → 0 篇文档
2. **无文档时不设防**：`blocks` 为空 → prompt 里没有文档内容 → LLM 在缺乏信息的情况下被迫编造

### 最终修复
1. `trading_analyze` 新增 `--categories` CLI 参数，GUI 传入用户选择的文件夹
2. `blocks` 为空时直接输出 `⚠️ 未读入任何文件`，不调用 LLM
3. prompt 中增加约束："只能基于下面提供的文档内容进行分析，缺乏信息时明确说'文档中未涉及'"

### 验收命令
```python
r1 = trading_analyze(cfg, 'AI', categories=['AI与工具化'])
assert r1['docs_used'] > 0
r2 = trading_analyze(cfg, 'nonexistent_xyz', categories=['交易系统与方法论'])
assert r2.get('warning') == '未读入任何文件'
```

### 验收结果
✅ AI与工具化 → 35 docs。不存在主题 → 返回 warning 不调 LLM。

### 下次避免规则
> **规则：LLM 调用前必须检查输入是否包含实际数据。空数据 + LLM = 高质量幻觉。**

### 下次给 AI 的提示
```
任何调用 LLM 的函数，在构造 prompt 前必须检查实际读入了多少文档。
if len(blocks) == 0: 直接返回 "未读入任何文件"，不要调 LLM API。
```

---

## Bug 011：子进程 stdout 缓冲导致 GUI 假死

### 现象
点击"正式整理"或"个人画像"后，界面一直显示"🔄 子进程启动中..."，几分钟没有任何变化。用户以为系统卡死。

### 根因
Python 在管道模式（`subprocess.PIPE`）下默认使用 4KB 全缓冲。`print()` 输出不会立即到达管道，直到缓冲区满或进程退出。`readline()` 一直阻塞 → GUI 永远显示第一行。

### 最终修复
1. 子进程命令加上 `-u` 标志：`[python, -u, main.py, ...]`
2. 子进程环境变量 `PYTHONUNBUFFERED=1`
3. `compress_and_synthesize` 一进入就 `print() + sys.stdout.flush()`

### 验收命令
```bash
# pipeline 中运行，确认立刻有输出
python -u main.py profile-me --config config.yaml --scope all | head -1
# 期望 < 2 秒内输出第一行
```

### 验收结果
✅ 启动后立即输出 `{"phase":"building_bundles",...}`。

### 下次避免规则
> **规则：所有通过 subprocess 调用的 Python 进程必须用 `-u` + `PYTHONUNBUFFERED=1`。**

### 下次给 AI 的提示
```
subprocess.Popen 的 cmd 第一个元素后必须是 "-u"。
env 中必须包含 PYTHONUNBUFFERED=1。
任何需要实时反馈的 Python 子进程必须禁用 stdout 缓冲。
```

---

## Bug 012：文件夹分析找不到文档 — 路径基准错误

### 现象
文件夹分析"AI与工具化"返回"无可用文档"。

### 根因
`_normalize_folder()` 对非绝对路径的基准是 `_workspace_root()`（项目根 `C:\...\kb-console\`），而不是 `_docs_root(cfg)`（`docs/`）。所以 "AI与工具化" → `C:\...\kb-console\AI与工具化`（不存在），实际路径应该是 `C:\...\docs\AI与工具化`。

### 最终修复
`_normalize_folder` 的 fallback 从 `_workspace_root()` 改为 `_docs_root(cfg)`。

### 验收命令
```python
docs = fetch_folder_docs(cfg, 'AI与工具化')
assert len(docs) > 0
```

### 验收结果
✅ 修复前 0 docs，修复后 43 docs。

### 下次避免规则
> **规则：所有路径拼接前确认基准目录。源文件、文档、输出使用不同的 base path。**

---

## Bug 013：后台任务切页面后结果丢失

### 现象
启动主题分析后切到报告中心，再切回来——进度条消失，没有任何结果。任务实际在后台完成了。

### 根因
`render_task_progress` 在 `phase == "done"` 时只显示了一行 `st.success` 就 `return False`。任务的输出 JSON 和报告路径存在 session_state 中但从未被渲染。切页面回来后，`render_task_progress` 再次被调用，发现 phase=done → 显示 success → return False。但 result 数据仍然没被显示。

### 最终修复
1. `render_task_progress` 在 done 时额外显示 report 路径 + JSON 详情（可折叠）
2. 侧边栏添加持久"最近完成"区域
3. 未读的完成通知在任意页面触发 toast + beep

### 下次避免规则
> **规则：后台任务的状态展示必须覆盖三个时间点：运行中、刚完成、已完成（切回来看到的）。**

---

## Bug 014：主题分析用 LIKE 搜文件名而非全文

### 现象
搜索"交易系统的进化过程"返回 0 篇文档。但交易分类有 111 篇文档。

### 根因
`trading_analyze` 用 `filename LIKE '%交易系统的进化过程%'` 过滤——这当然匹配不到。真正的内容在文档正文里。应该读入选定文件夹的全部文档，让 LLM 判断相关性。

### 最终修复
移除 topic-based SQL LIKE 过滤。用户选的文件夹 = 数据范围，topic = LLM 分析指令。全部文档读入。

### 验收命令
```python
r = trading_analyze(cfg, '交易系统的进化过程', categories=['交易系统与方法论','交易复盘','交易记录','交易心理与情绪'])
assert r['docs_used'] >= 80
```

### 验收结果
✅ 修复前 0 docs，修复后 80 docs（上限）。

---

## Bug 015：80 篇硬上限 → 100 万字 Token 预算制

### 现象
`trading_analyze` 最多读 80 篇文档。超出直接截断。

### 根因
代码写死 `rows[:80]` 和 `_read_doc_text(cfg, r)[:3000]`。

### 最终修复
1. 新增 `_build_blocks_with_budget(rows, max_chars=1_000_000)`：按字数累计，超出时标注"剩余 N 篇未读入"而非硬截断
2. `profile_me` / `project_analyze` / `folder_analyze` 接入 `compress_and_synthesize`：超出 100 万字时自动分批 LLM 压缩 + 并发处理 + 合成
3. 分批处理线程池并发（`ThreadPoolExecutor(max_workers=max_concurrency)`）而非串行

### 下次避免规则
> **规则：任何 `rows[:N]` 硬截断都应质疑——N 是怎么来的？应该基于数据量（token/chars）动态决定。**

---

## 高频根因分类

| 根因类别 | 涉及 Bug | 频率 |
|----------|----------|:---:|
| 相对路径 vs 绝对路径 / 工作目录 | 009, 012 | 2 |
| Python stdout 缓冲 | 002, 011 | 2 |
| Streamlit session_state 生命周期 | 007, 013 | 2 |
| 硬编码限制（80篇/20篇/3000字） | 014, 015 | 2 |
| SHA/指纹非确定性 | 008c | 1 |
| 浮点精度 | 008a | 1 |
| DB 初始化假设（冷启动） | 001 | 1 |
| LLM 输入为空时未防护 | 010 | 1 |
| AI 生成代码缺 import / 用错 API | 005, 006 | 2 |
| 测试环境≠运行环境 | 009 | 1 |

---

## Copilot 引入 vs 用户发现的 Bug

| 来源 | 数量 | 典型例子 |
|------|:---:|------|
| AI 生成代码 bug | 005, 006 | 缺 import、用不存在 API |
| 设计缺陷（AI 提的方案有漏洞） | 008c, 009 | SHA 随机采样、路径相对化 |
| 用户发现 | 007, 008, 009, 010, 011, 013, 014 | 切页面丢进度、重复文件、搜索无结果 |
| 代码审查发现 | 001, 002, 003, 004, 012, 015 | DB 初始化、编码、硬上限 |

**结论**：AI 能发现设计层面的模式问题（B001, B015），但**用户在交互中发现的 bug 最多也最关键**——因为这些 bug 只有在真实使用中才会暴露。
